from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from exercise_motion_pkg import bake_and_rank as bake_and_rank_module
from exercise_motion_pkg.bake_and_rank import BakeAndRankRequest, LazyLlamaCppVisionSession
from exercise_motion_pkg.gpu_lock import process_identity
from exercise_motion_pkg.shared_llama_server import (
    INFLIGHT_DIRECTORY_NAME,
    START_REQUEST_FILE_NAME,
    STOP_INTENT_FILE_NAME,
    SharedLlamaServerCoordinator,
)


class _LiveForeignProcess:
    """A real, short-lived process whose pid/identity look 'live' to the protocol."""

    def __init__(self) -> None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self.pid = self._process.pid
        self.identity = process_identity(self._process.pid)

    def stop(self) -> None:
        self._process.terminate()
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=10)

    def write_counter(self, session_dir: Path, active_requests: int) -> None:
        inflight_dir = session_dir / INFLIGHT_DIRECTORY_NAME
        inflight_dir.mkdir(parents=True, exist_ok=True)
        (inflight_dir / f"{self.pid}.json").write_text(
            json.dumps({
                "pid": self.pid,
                "processIdentity": self.identity,
                "activeRequests": active_requests,
                "updatedAtUnixSeconds": time.time(),
            }),
            encoding="utf-8",
        )

    def write_stop_intent(self, session_dir: Path) -> None:
        (session_dir / STOP_INTENT_FILE_NAME).write_text(
            json.dumps({
                "pid": self.pid,
                "processIdentity": self.identity,
                "requestedAtUnixSeconds": time.time(),
            }),
            encoding="utf-8",
        )


class _ServerStopRecorder:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            bake_and_rank_module,
            "stop_llama_cpp_servers_for_base_url",
            self._record,
        )

    def _record(self, base_url, *, expected_command=None, expected_model=None):
        self.calls.append({
            "baseUrl": base_url,
            "expectedCommand": expected_command,
            "expectedModel": expected_model,
        })
        return [4321]


def _fake_ranker_class(events: list[str]):
    class FakeClient:
        def caption_images(self, *_args: object, **_kwargs: object) -> str:
            events.append("caption")
            return "{}"

        def close(self) -> None:
            pass

    class FakeRanker:
        def __init__(self, _settings: object) -> None:
            self.client = FakeClient()
            self.gpu_lock_wait_seconds = 0.0
            events.append("ranker_started")

        def close(self, *, force_stop_server: bool = False) -> None:
            events.append(f"ranker_closed:force={force_stop_server}")

    return FakeRanker


def _shared_request(tmp_path: Path) -> BakeAndRankRequest:
    return BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=tmp_path,
        wham_repo_path=None,
        body_model_root=None,
        llama_cpp_auto_start_server=False,
        shared_llama_server=True,
        shared_llama_server_session_dir=tmp_path / "shared-session",
    )


def _wait_until(predicate, timeout_seconds: float = 5.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_attach_mode_close_leaves_the_shared_server_alone(tmp_path, monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(
        bake_and_rank_module, "LlamaCppVisionRanker", _fake_ranker_class(events)
    )
    recorder = _ServerStopRecorder(monkeypatch)
    session_dir = tmp_path / "shared-session"
    session = LazyLlamaCppVisionSession(_shared_request(tmp_path))
    assert session._shared is not None
    counter_path = session_dir / INFLIGHT_DIRECTORY_NAME / f"{os.getpid()}.json"
    assert counter_path.exists()

    assert session.caption_images(frame_paths=[], prompt="p") == "{}"
    session.close(force_stop_server=True)

    # Attached sessions release nothing: the server is never stopped, even on
    # the force path that own mode uses for the exclusive handoff.
    assert recorder.calls == []
    assert "ranker_closed:force=True" in events
    assert not counter_path.exists()
    assert not (session_dir / STOP_INTENT_FILE_NAME).exists()


def test_flag_off_close_keeps_today_force_stop_behavior(tmp_path, monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(
        bake_and_rank_module, "LlamaCppVisionRanker", _fake_ranker_class(events)
    )
    recorder = _ServerStopRecorder(monkeypatch)
    request = BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=tmp_path,
        wham_repo_path=None,
        body_model_root=None,
    )
    session = LazyLlamaCppVisionSession(request)
    assert session._shared is None
    # Ranker never started: the force close must stop a foreign server bound
    # to the configured base URL, exactly as before the shared flag existed.
    session.close(force_stop_server=True)
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["baseUrl"] == "http://127.0.0.1:8090"
    timing = session.timing_manifest()
    assert "sharedVisionSession" not in timing


def test_shared_exclusive_phase_quiesces_then_requests_restart(tmp_path, monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(
        bake_and_rank_module, "LlamaCppVisionRanker", _fake_ranker_class(events)
    )
    recorder = _ServerStopRecorder(monkeypatch)
    session_dir = tmp_path / "shared-session"
    session = LazyLlamaCppVisionSession(_shared_request(tmp_path))
    assert session.caption_images(frame_paths=[], prompt="p") == "{}"

    foreign = _LiveForeignProcess()
    try:
        foreign.write_counter(session_dir, active_requests=1)
        operation_ran = threading.Event()

        def operation():
            # The stop-intent must still be live while the GPU is exclusive,
            # keeping every attached process's admissions closed.
            assert (session_dir / STOP_INTENT_FILE_NAME).exists()
            operation_ran.set()
            return "exclusive"

        result: list[object] = []
        exclusive = threading.Thread(
            target=lambda: result.append(session.run_without_llama_overlap(operation))
        )
        exclusive.start()

        assert _wait_until(
            lambda: (session_dir / STOP_INTENT_FILE_NAME).exists()
        ), "quiesce never wrote its stop-intent"
        # The foreign in-flight request must hold the drain open: no stop, no
        # operation, even after multiple settle windows have passed.
        time.sleep(0.8)
        assert recorder.calls == []
        assert not operation_ran.is_set()

        foreign.write_counter(session_dir, active_requests=0)
        exclusive.join(timeout=10)
        assert not exclusive.is_alive()
        assert result == ["exclusive"]
        assert operation_ran.is_set()
    finally:
        foreign.stop()

    assert len(recorder.calls) == 1
    # Release: admissions reopen and the supervisor restart is requested.
    assert not (session_dir / STOP_INTENT_FILE_NAME).exists()
    assert (session_dir / START_REQUEST_FILE_NAME).exists()
    timing = session.timing_manifest()
    assert timing["sharedVisionSession"]["sharedVisionQuiesceCount"] == 1
    assert timing["sharedVisionSession"]["sharedVisionServerStopCount"] == 1
    assert timing["sharedVisionSession"]["sharedVisionRestartRequestCount"] == 1
    assert timing["sharedVisionSession"]["sharedVisionPeakForeignActiveRequests"] == 1
    event_names = [event["event"] for event in timing["visionLifecycleEvents"]]
    assert event_names.index("shared_exclusive_quiesce_finished") < event_names.index("exclusive_gpu_operation_started")
    assert "shared_restart_requested" in event_names
    session.close(force_stop_server=True)
    assert len(recorder.calls) == 1


def test_foreign_stop_intent_gates_caption_admission(tmp_path, monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(
        bake_and_rank_module, "LlamaCppVisionRanker", _fake_ranker_class(events)
    )
    _ServerStopRecorder(monkeypatch)
    session_dir = tmp_path / "shared-session"
    session = LazyLlamaCppVisionSession(_shared_request(tmp_path))

    foreign = _LiveForeignProcess()
    try:
        foreign.write_stop_intent(session_dir)
        assert session._shared.stop_intent_live()

        completed = threading.Event()
        errors: list[BaseException] = []

        def run_caption():
            try:
                session.caption_images(frame_paths=[], prompt="p")
                completed.set()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        caption_thread = threading.Thread(target=run_caption)
        caption_thread.start()
        time.sleep(0.8)
        # A live foreign exclusive phase must block new VLM admissions.
        assert not completed.is_set()
        assert "caption" not in events

        (session_dir / STOP_INTENT_FILE_NAME).unlink()
        assert _wait_until(completed.is_set, timeout_seconds=5)
        caption_thread.join(timeout=5)
        assert not errors
        assert events.count("caption") == 1
    finally:
        foreign.stop()
        session.close(force_stop_server=True)


def test_stale_foreign_counter_and_intent_are_reclaimed(tmp_path):
    session_dir = tmp_path / "coord"
    stopped_servers: list[None] = []
    coordinator = SharedLlamaServerCoordinator(
        session_dir=session_dir,
        base_url="http://127.0.0.1:8090",
        stop_server=lambda: stopped_servers.append(None),
    )
    coordinator.register()

    dead = _LiveForeignProcess()
    dead.stop()
    dead.write_counter(session_dir, active_requests=3)
    dead.write_stop_intent(session_dir)
    assert not coordinator.stop_intent_live()

    started = time.monotonic()
    summary = coordinator.begin_exclusive_phase()
    elapsed = time.monotonic() - started

    # A crashed exclusive owner and its stale in-flight counter must not stall
    # the next quiesce beyond the settle window.
    assert elapsed < 5.0
    assert summary.stopped_server
    assert summary.reclaimed_stale_markers == [STOP_INTENT_FILE_NAME, f"{dead.pid}.json"]
    assert len(stopped_servers) == 1

    coordinator.end_exclusive_phase()
    assert (session_dir / START_REQUEST_FILE_NAME).exists()
    coordinator.detach()
    assert not list((session_dir / INFLIGHT_DIRECTORY_NAME).glob("*.json"))


def test_shared_ranker_never_stops_or_spawns_the_server(tmp_path, monkeypatch):
    from exercise_motion_pkg import youtube as youtube_module

    settings = youtube_module.YouTubeRankingSettings(
        llama_cpp_base_url="http://127.0.0.1:18090",
        llama_cpp_shared_server=True,
        vision_llm_workers=1,
    )
    ensured = []
    monkeypatch.setattr(
        youtube_module.LlamaCppVisionRanker,
        "_ensure_server",
        lambda self: ensured.append(True),
    )
    stopped: list[object] = []
    monkeypatch.setattr(
        youtube_module,
        "stop_llama_cpp_servers_for_base_url",
        lambda *args, **kwargs: stopped.append((args, kwargs)),
    )
    ranker = youtube_module.LlamaCppVisionRanker(settings)
    try:
        # No llama_cpp_server GPU-lock lease: the supervisor's server is not
        # this process's exclusive resource.
        assert ranker.gpu_lock is None
        assert ensured == [True]
        ranker.close(force_stop_server=True)
        assert stopped == []
    finally:
        ranker.close()


def test_shared_ranker_waits_for_supervised_restart_instead_of_spawning(tmp_path, monkeypatch):
    from exercise_motion_pkg import youtube as youtube_module

    def _no_spawn(*_args: object, **_kwargs: object):
        raise AssertionError("attached sessions must never resolve a spawn command")

    monkeypatch.setattr(youtube_module, "resolve_llama_cpp_server_command", _no_spawn)
    payloads = iter([
        None,
        {"data": [{"id": "Qwen3.5-9B-UD-Q4_K_XL.gguf"}]},
    ])
    monkeypatch.setattr(
        youtube_module.LlamaCppVisionRanker,
        "_server_models_payload",
        lambda self: next(payloads, None),
    )
    monkeypatch.setattr(
        youtube_module.LlamaCppVisionRanker,
        "_raise_if_server_model_mismatch",
        lambda self, payload: None,
    )
    monkeypatch.setattr(
        youtube_module.LlamaCppVisionRanker,
        "_raise_if_server_runtime_mismatch",
        lambda self: None,
    )
    chat_ready: list[bool] = []
    monkeypatch.setattr(
        youtube_module.LlamaCppVisionRanker,
        "_wait_for_chat_completions_ready",
        lambda self: chat_ready.append(True),
    )

    settings = youtube_module.YouTubeRankingSettings(
        llama_cpp_base_url="http://127.0.0.1:18090",
        llama_cpp_shared_server=True,
        vision_llm_workers=1,
    )
    ranker = youtube_module.LlamaCppVisionRanker(settings)
    try:
        assert chat_ready == [True]
    finally:
        ranker.close()


def test_shared_ranker_surfaces_server_mismatch_without_evicting_it(monkeypatch):
    from exercise_motion_pkg import youtube as youtube_module

    def _mismatch(self, payload):
        raise RuntimeError("started with reasoning disabled")

    monkeypatch.setattr(
        youtube_module.LlamaCppVisionRanker,
        "_server_models_payload",
        lambda self: {"data": [{"id": "other.gguf"}]},
    )
    monkeypatch.setattr(
        youtube_module.LlamaCppVisionRanker,
        "_raise_if_server_model_mismatch",
        _mismatch,
    )
    stopped: list[object] = []
    monkeypatch.setattr(
        youtube_module,
        "stop_llama_cpp_servers_for_base_url",
        lambda *args, **kwargs: stopped.append((args, kwargs)),
    )
    settings = youtube_module.YouTubeRankingSettings(
        llama_cpp_base_url="http://127.0.0.1:18090",
        llama_cpp_shared_server=True,
        vision_llm_workers=1,
    )
    with pytest.raises(RuntimeError, match="reasoning"):
        youtube_module.LlamaCppVisionRanker(settings)
    assert stopped == []


def test_cli_flags_plumb_into_requests(tmp_path):
    from exercise_motion_pkg.cli import build_bake_and_rank_request, build_parser

    parser = build_parser()
    base_args = [
        "bake-and-rank",
        "--candidates-json", str(tmp_path / "candidates.json"),
        "--workspace", str(tmp_path),
        "--wham-repo-path", str(tmp_path / "wham"),
        "--body-model-root", str(tmp_path / "body"),
    ]
    default_request = build_bake_and_rank_request(parser.parse_args(base_args))
    assert default_request.shared_llama_server is False
    assert default_request.shared_llama_server_session_dir is None

    shared_request = build_bake_and_rank_request(parser.parse_args(
        base_args
        + ["--shared-llama-server", "--shared-llama-server-session-dir", str(tmp_path / "shared")]
    ))
    assert shared_request.shared_llama_server is True
    assert shared_request.shared_llama_server_session_dir == tmp_path / "shared"

    generate_args = parser.parse_args([
        "generate",
        "--exercise-slug", "air-squat",
        "--video-path", str(tmp_path / "source.mp4"),
        "--shared-llama-server",
    ])
    assert generate_args.shared_llama_server is True
