from __future__ import annotations

import json
import os
import shutil
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
    RESIDENT_COMPUTE_INTENT_FILE_NAME,
    SHARED_LLAMA_SESSION_DIR_ENV_VAR,
    START_REQUEST_FILE_NAME,
    STOP_INTENT_FILE_NAME,
    SharedLlamaExclusivePhaseActive,
    SharedLlamaServerCoordinator,
    detach_shared_llama_request_publisher,
    install_shared_llama_request_publisher,
    resident_gpu_compute_scope,
    shared_llama_coordinator_for,
)


def _powershell_function(source: str, name: str) -> str:
    marker = f"function {name} {{"
    start = source.index(marker)
    next_function = source.find("\nfunction ", start + len(marker))
    return source[start:] if next_function < 0 else source[start:next_function]


@pytest.fixture(autouse=True)
def _isolated_shared_llama_process_state():
    # The request publisher and coordinator registry are process-global; keep
    # tests independent of each other's installations.
    from exercise_motion_pkg.shared_llama_server import (
        reset_shared_llama_process_state_for_tests,
    )

    reset_shared_llama_process_state_for_tests()
    yield
    reset_shared_llama_process_state_for_tests()


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


def test_candidate_deadline_bounds_shared_transition_lock_wait(tmp_path):
    coordinator = SharedLlamaServerCoordinator(
        session_dir=tmp_path / "coord",
        base_url="http://127.0.0.1:8090",
        stop_server=lambda: pytest.fail("server must not stop before transition admission"),
        poll_seconds=0.01,
    )
    held = threading.Event()
    release = threading.Event()

    def hold_transition():
        with coordinator._transition_lock():
            held.set()
            assert release.wait(timeout=2)

    holder = threading.Thread(target=hold_transition)
    holder.start()
    assert held.wait(timeout=2)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            coordinator.begin_exclusive_phase(deadline=started + 0.08)
        assert time.monotonic() - started < 0.5
        assert not (coordinator.session_dir / STOP_INTENT_FILE_NAME).exists()
    finally:
        release.set()
        holder.join(timeout=2)
    assert not holder.is_alive()


def test_counted_request_budget_bounds_transition_lock_without_intent(tmp_path):
    coordinator = SharedLlamaServerCoordinator(
        session_dir=tmp_path / "coord",
        base_url="http://127.0.0.1:8090",
        stop_server=lambda: None,
        poll_seconds=0.01,
    )
    held = threading.Event()
    release = threading.Event()

    def hold_transition():
        with coordinator._transition_lock():
            held.set()
            assert release.wait(timeout=2)

    holder = threading.Thread(target=hold_transition)
    holder.start()
    assert held.wait(timeout=2)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            with coordinator.counted_request_scope(max_wait_seconds=0.08):
                raise AssertionError("request should not pass the held transition lock")
        assert time.monotonic() - started < 0.5
    finally:
        release.set()
        holder.join(timeout=2)
    assert not holder.is_alive()


def test_counted_request_scope_inherits_candidate_deadline(tmp_path):
    from exercise_motion_pkg.motion_scheduler import candidate_deadline_scope

    coordinator = SharedLlamaServerCoordinator(
        session_dir=tmp_path / "coord",
        base_url="http://127.0.0.1:8090",
        stop_server=lambda: None,
        poll_seconds=0.01,
    )
    held = threading.Event()
    release = threading.Event()

    def hold_transition():
        with coordinator._transition_lock():
            held.set()
            assert release.wait(timeout=2)

    holder = threading.Thread(target=hold_transition)
    holder.start()
    assert held.wait(timeout=2)
    started = time.perf_counter()
    try:
        with candidate_deadline_scope(started + 0.08):
            with pytest.raises(TimeoutError):
                with coordinator.counted_request_scope():
                    raise AssertionError("request should inherit the candidate deadline")
        assert time.perf_counter() - started < 0.5
    finally:
        release.set()
        holder.join(timeout=2)
    assert not holder.is_alive()


def test_exclusive_handoff_waits_for_powershell_startup_transition(tmp_path, monkeypatch):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is required to verify shared transition-lock interoperability")
    from exercise_motion_pkg import shared_llama_server as shared_module
    from exercise_motion_pkg.process_lock import InterProcessFileLock

    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_exercise_motion_workout_plan.ps1"
    )
    source = script_path.read_text(encoding="utf-8-sig")
    lock_function = _powershell_function(source, "Enter-SharedLlamaTransitionLock")
    ready_path = tmp_path / "server-ready"
    release_path = tmp_path / "release-startup-lock"
    session_dir = tmp_path / "shared-llama"
    command = f"""
$ErrorActionPreference = 'Stop'
{lock_function}
$lock = Enter-SharedLlamaTransitionLock -SessionDir '{str(session_dir).replace("'", "''")}' -TimeoutSeconds 10
Set-Content -LiteralPath '{str(ready_path).replace("'", "''")}' -Value 'startup owns transition'
while (-not (Test-Path -LiteralPath '{str(release_path).replace("'", "''")}')) {{ Start-Sleep -Milliseconds 20 }}
$lock.Dispose()
"""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startup_process = subprocess.Popen(
        [pwsh, "-NoProfile", "-Command", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    attempting_lock = threading.Event()
    completed = threading.Event()
    events: list[str] = []
    errors: list[BaseException] = []

    class ObservedTransitionLock(InterProcessFileLock):
        def __enter__(self):
            if self.stage == "shared_llama_transition":
                attempting_lock.set()
            return super().__enter__()

    monkeypatch.setattr(shared_module, "InterProcessFileLock", ObservedTransitionLock)
    coordinator = SharedLlamaServerCoordinator(
        session_dir=session_dir,
        base_url="http://127.0.0.1:8090",
        stop_server=lambda: events.append("stop_server"),
        poll_seconds=0.05,
    )

    def begin_exclusive():
        try:
            coordinator.begin_exclusive_phase()
        except BaseException as exc:
            errors.append(exc)
        finally:
            completed.set()

    try:
        assert _wait_until(ready_path.exists, timeout_seconds=5)
        thread = threading.Thread(target=begin_exclusive, daemon=True)
        thread.start()
        assert attempting_lock.wait(timeout=5)
        assert not completed.is_set()
        assert events == []
        assert not (session_dir / STOP_INTENT_FILE_NAME).exists()
        assert not (session_dir / INFLIGHT_DIRECTORY_NAME / f"{os.getpid()}.json").exists()

        release_path.write_text("ready", encoding="utf-8")
        assert completed.wait(timeout=5)
        thread.join(timeout=5)
        assert not errors
        assert events == ["stop_server"]
        assert (session_dir / STOP_INTENT_FILE_NAME).exists()
        assert (session_dir / INFLIGHT_DIRECTORY_NAME / f"{os.getpid()}.json").exists()
        coordinator.end_exclusive_phase()
        assert (session_dir / START_REQUEST_FILE_NAME).exists()

        start_function = _powershell_function(source, "Start-SharedLlamaServer")
        assert start_function.index("Enter-SharedLlamaTransitionLock") < start_function.index(
            "Test-SharedLlamaExclusiveHandoffActive"
        )
        assert "Remove-StaleSharedLlamaInflightCounters -SessionDir $SessionDir" in start_function
        assert "Get-ChildItem -LiteralPath (Join-Path $SessionDir \"in-flight\") -Filter \"*.json\"" not in start_function
        assert start_function.index("Start-Process") < start_function.index("Shared llama.cpp server ready")
        assert "finally" in start_function and "$transitionLock.Dispose()" in start_function
    finally:
        release_path.write_text("release", encoding="utf-8")
        try:
            startup_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            startup_process.kill()
            startup_process.wait(timeout=5)


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


# ---------------------------------------------------------------------------
# Client-level in-flight request publisher (discovery / non-session clients)
# ---------------------------------------------------------------------------


def _published_active_requests(session_dir: Path) -> int | None:
    counter_path = session_dir / INFLIGHT_DIRECTORY_NAME / f"{os.getpid()}.json"
    try:
        payload = json.loads(counter_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload.get("activeRequests")


class _FakeHttpResponse:
    status_code = 200
    text = ""

    def json(self) -> dict[str, object]:
        return {"choices": [{"message": {"content": "{}"}}]}


def _attached_publisher_session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    session_dir = tmp_path / "publisher-session"
    monkeypatch.setenv(SHARED_LLAMA_SESSION_DIR_ENV_VAR, str(session_dir))
    install_shared_llama_request_publisher(base_url="http://127.0.0.1:18090")
    return session_dir


def _vision_client_with_recording_transport(
    monkeypatch: pytest.MonkeyPatch,
    session_dir: Path,
    *,
    observed: list[int | None],
    error: Exception | None = None,
):
    from exercise_motion_pkg.segment_detection import LlamaCppVisionClient

    client = LlamaCppVisionClient(base_url="http://127.0.0.1:18090", model="model.gguf")

    def fake_post(**_kwargs: object):
        observed.append(_published_active_requests(session_dir))
        if error is not None:
            raise error
        return _FakeHttpResponse()

    monkeypatch.setattr(client, "_post_chat_completion", fake_post)
    return client


def test_discovery_request_publishes_and_releases_inflight_counter(tmp_path, monkeypatch):
    session_dir = _attached_publisher_session_dir(tmp_path, monkeypatch)
    assert _published_active_requests(session_dir) == 0

    observed: list[int | None] = []
    client = _vision_client_with_recording_transport(monkeypatch, session_dir, observed=observed)
    assert client.caption_images(frame_paths=[], prompt="p") == "{}"

    # The counter must be visible at 1 while the HTTP request is in flight and
    # return to 0 afterwards, so a wave's quiesce drains the request first.
    assert observed == [1]
    assert _published_active_requests(session_dir) == 0


def test_discovery_request_releases_counter_on_exception(tmp_path, monkeypatch):
    session_dir = _attached_publisher_session_dir(tmp_path, monkeypatch)
    observed: list[int | None] = []
    client = _vision_client_with_recording_transport(
        monkeypatch, session_dir, observed=observed, error=RuntimeError("transport exploded")
    )
    with pytest.raises(RuntimeError, match="transport exploded"):
        client.caption_images(frame_paths=[], prompt="p")
    assert observed == [1]
    assert _published_active_requests(session_dir) == 0


def test_wave_session_request_is_counted_once(tmp_path, monkeypatch):
    session_dir = tmp_path / "shared-session"
    observed: list[int | None] = []
    client = _vision_client_with_recording_transport(monkeypatch, session_dir, observed=observed)

    class FakeRanker:
        def __init__(self, _settings: object) -> None:
            self.client = client
            self.gpu_lock_wait_seconds = 0.0

        def close(self, *, force_stop_server: bool = False) -> None:
            pass

    monkeypatch.setattr(bake_and_rank_module, "LlamaCppVisionRanker", FakeRanker)
    session = LazyLlamaCppVisionSession(_shared_request(tmp_path))
    try:
        assert session.caption_images(frame_paths=[], prompt="p") == "{}"
        # The session publishes its admitted count; the client-level publisher
        # must stay silent for its threads - exactly one counter, not two.
        assert observed == [1]
        assert _published_active_requests(session_dir) == 0
    finally:
        session.close(force_stop_server=True)
    assert not (session_dir / INFLIGHT_DIRECTORY_NAME / f"{os.getpid()}.json").exists()


def test_foreign_stop_intent_gates_discovery_request_until_released(tmp_path, monkeypatch):
    session_dir = _attached_publisher_session_dir(tmp_path, monkeypatch)
    observed: list[int | None] = []
    client = _vision_client_with_recording_transport(monkeypatch, session_dir, observed=observed)

    foreign = _LiveForeignProcess()
    try:
        foreign.write_stop_intent(session_dir)
        completed = threading.Event()
        errors: list[BaseException] = []

        def run_caption():
            try:
                client.caption_images(frame_paths=[], prompt="p", request_timeout_seconds=10.0)
                completed.set()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        caption_thread = threading.Thread(target=run_caption)
        caption_thread.start()
        time.sleep(0.8)
        # A live foreign exclusive phase queues the request before any HTTP
        # call and before the counter is published.
        assert not completed.is_set()
        assert observed == []
        assert _published_active_requests(session_dir) == 0

        (session_dir / STOP_INTENT_FILE_NAME).unlink()
        assert _wait_until(completed.is_set, timeout_seconds=5)
        caption_thread.join(timeout=5)
        assert not errors
        assert observed == [1]
        assert _published_active_requests(session_dir) == 0
    finally:
        foreign.stop()
        detach_shared_llama_request_publisher()


def test_request_admission_rechecks_intent_under_transition_lock(tmp_path, monkeypatch):
    from contextlib import contextmanager
    coordinator = SharedLlamaServerCoordinator(tmp_path, base_url=None, stop_server=lambda: None)
    locked = False

    @contextmanager
    def transition():
        nonlocal locked
        locked = True
        try:
            yield
        finally:
            locked = False

    def publish():
        assert locked, 'Counter publication raced the stop-intent publisher'

    monkeypatch.setattr(coordinator, '_transition_lock', transition)
    monkeypatch.setattr(coordinator, 'begin_counted_request', publish)
    monkeypatch.setattr(coordinator, 'foreign_stop_intent_live', lambda: True)
    assert not coordinator.try_begin_counted_request()
    monkeypatch.setattr(coordinator, 'foreign_stop_intent_live', lambda: False)
    assert coordinator.try_begin_counted_request()


def test_resident_compute_drains_all_requests_and_blocks_same_process_admission(tmp_path):
    session_dir = tmp_path / "shared-session"
    coordinator = shared_llama_coordinator_for(session_dir, base_url=None)
    coordinator.register()
    # Multiple VLM requests remain admissible concurrently before a reservation.
    assert coordinator.try_begin_counted_request()
    assert coordinator.try_begin_counted_request()
    assert coordinator.counted_active_requests() == 2
    entered = threading.Event()
    errors: list[BaseException] = []

    def reserve():
        try:
            with resident_gpu_compute_scope(session_dir, deadline=time.perf_counter() + 5):
                assert coordinator.counted_active_requests() == 0
                assert not coordinator.try_begin_counted_request()
                entered.set()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=reserve)
    thread.start()
    assert _wait_until(
        lambda: (session_dir / RESIDENT_COMPUTE_INTENT_FILE_NAME).exists(),
        timeout_seconds=3,
    )
    # A new request in this same process is refused while the GPU reservation is live.
    assert not coordinator.try_begin_counted_request()
    coordinator.end_counted_request()
    coordinator.end_counted_request()
    thread.join(timeout=5)
    assert entered.is_set()
    assert not errors
    assert not (session_dir / RESIDENT_COMPUTE_INTENT_FILE_NAME).exists()
    assert not (session_dir / STOP_INTENT_FILE_NAME).exists()
    assert not (session_dir / "start_requested.json").exists()


def test_resident_compute_cleans_intent_after_error_and_does_not_stop_server(tmp_path):
    session_dir = tmp_path / "shared-session"
    stop_calls: list[bool] = []
    coordinator = shared_llama_coordinator_for(
        session_dir, base_url=None, stop_server=lambda: stop_calls.append(True),
    )
    coordinator.register()
    with pytest.raises(RuntimeError, match="prediction failed"):
        with resident_gpu_compute_scope(session_dir, deadline=time.perf_counter() + 3):
            assert (session_dir / RESIDENT_COMPUTE_INTENT_FILE_NAME).exists()
            raise RuntimeError("prediction failed")
    assert not (session_dir / RESIDENT_COMPUTE_INTENT_FILE_NAME).exists()
    assert not (session_dir / STOP_INTENT_FILE_NAME).exists()
    assert not (session_dir / "start_requested.json").exists()
    assert stop_calls == []


def test_counted_publisher_waits_out_resident_compute_intent(tmp_path):
    session_dir = tmp_path / "shared-session"
    coordinator = shared_llama_coordinator_for(session_dir, base_url=None)
    coordinator.register()
    admitted = threading.Event()

    def request():
        with coordinator.counted_request_scope(max_wait_seconds=3):
            admitted.set()

    with resident_gpu_compute_scope(session_dir, deadline=time.perf_counter() + 3):
        thread = threading.Thread(target=request)
        thread.start()
        time.sleep(0.35)
        assert not admitted.is_set()
    thread.join(timeout=3)
    assert admitted.is_set()
    assert coordinator.counted_active_requests() == 0


def test_resident_compute_reclaims_same_pid_marker_with_stale_identity(tmp_path):
    session_dir = tmp_path / "shared-session"
    session_dir.mkdir()
    marker = session_dir / RESIDENT_COMPUTE_INTENT_FILE_NAME
    marker.write_text(json.dumps({
        "pid": os.getpid(),
        "processIdentity": (process_identity(os.getpid()) or 0) + 1,
        "intentToken": "stale-owner",
    }), encoding="utf-8")
    with resident_gpu_compute_scope(session_dir, deadline=time.perf_counter() + 3):
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["intentToken"] != "stale-owner"


def test_resident_compute_caps_explicit_deadline_to_expired_candidate(tmp_path):
    from exercise_motion_pkg.motion_scheduler import candidate_deadline_scope

    with candidate_deadline_scope(time.perf_counter() - 1):
        with pytest.raises(TimeoutError, match="Timed out waiting to reserve resident GPU compute"):
            with resident_gpu_compute_scope(tmp_path / "shared-session", deadline=time.perf_counter() + 30):
                pytest.fail("expired candidate deadline must not admit resident compute")


def test_handoff_wait_records_owner_identity(tmp_path, capsys):
    from exercise_motion_pkg.shared_llama_server import QuiesceSummary
    coordinator = SharedLlamaServerCoordinator(tmp_path, base_url=None, stop_server=lambda: None)
    summary = QuiesceSummary()
    owner = {'pid': 42, 'processIdentity': 123, 'activeRequests': 1}
    coordinator._record_quiesce_blocker(summary, 'inflight', owner, time.monotonic())
    assert summary.blocking_owners == [{'phase': 'inflight', 'owner': owner}]
    event = json.loads(capsys.readouterr().out)
    assert event['owner'] == owner and event['waiterPid'] == os.getpid()


def test_foreign_stop_intent_refuses_after_request_wait_budget(tmp_path, monkeypatch):
    session_dir = _attached_publisher_session_dir(tmp_path, monkeypatch)
    observed: list[int | None] = []
    client = _vision_client_with_recording_transport(monkeypatch, session_dir, observed=observed)

    foreign = _LiveForeignProcess()
    try:
        foreign.write_stop_intent(session_dir)
        started = time.monotonic()
        with pytest.raises(SharedLlamaExclusivePhaseActive):
            client.caption_images(frame_paths=[], prompt="p", request_timeout_seconds=1.0)
        waited = time.monotonic() - started
        # Refused after the bounded wait, without contacting the server and
        # without ever publishing an in-flight request.
        assert waited >= 1.0
        assert observed == []
        assert _published_active_requests(session_dir) == 0
    finally:
        foreign.stop()
        detach_shared_llama_request_publisher()


def test_publisher_attachments_refcount_until_the_last_detach(tmp_path, monkeypatch):
    session_dir = _attached_publisher_session_dir(tmp_path, monkeypatch)
    counter_path = session_dir / INFLIGHT_DIRECTORY_NAME / f"{os.getpid()}.json"
    assert counter_path.exists()

    # A second attaching ranker reuses the same coordinator and keeps the
    # counter alive after the first one closes.
    install_shared_llama_request_publisher(base_url="http://127.0.0.1:18090")
    detach_shared_llama_request_publisher()
    assert counter_path.exists()

    detach_shared_llama_request_publisher()
    assert not counter_path.exists()
    # Extra detaches are harmless (ranker close + atexit both fire).
    detach_shared_llama_request_publisher()


def test_shared_rankers_install_the_publisher_for_their_process(monkeypatch, tmp_path):
    from exercise_motion_pkg import youtube as youtube_module

    session_dir = tmp_path / "ranker-publisher-session"
    monkeypatch.setenv(SHARED_LLAMA_SESSION_DIR_ENV_VAR, str(session_dir))
    monkeypatch.setattr(
        youtube_module.LlamaCppVisionRanker,
        "_ensure_server",
        lambda self: None,
    )
    settings = youtube_module.YouTubeRankingSettings(
        llama_cpp_base_url="http://127.0.0.1:18090",
        llama_cpp_shared_server=True,
        vision_llm_workers=1,
    )
    counter_path = session_dir / INFLIGHT_DIRECTORY_NAME / f"{os.getpid()}.json"
    first = youtube_module.LlamaCppVisionRanker(settings)
    assert counter_path.exists()
    second = youtube_module.LlamaCppVisionRanker(settings)
    first.close()
    assert counter_path.exists()
    second.close()
    assert not counter_path.exists()



def test_generation_holder_marker_lifecycle(tmp_path) -> None:
    from exercise_motion_pkg.shared_llama_server import (
        clear_generation_holder_marker,
        live_foreign_generation_holders,
        write_generation_holder_marker,
    )

    session_dir = tmp_path / "shared"
    marker = write_generation_holder_marker(session_dir, holder="wave-0001")
    assert marker.exists()
    # Own-process holders are never "foreign".
    assert live_foreign_generation_holders(session_dir) == []

    foreign = _LiveForeignProcess()
    try:
        write_generation_holder_marker(session_dir, holder="wave-0002")
        # Overwrite the pid with the live foreign one to simulate that wave's process.
        marker2 = session_dir / "generation-holders" / f"{foreign.pid}.json"
        marker2.write_text(json.dumps({
            "pid": foreign.pid,
            "processIdentity": foreign.identity,
            "holder": "wave-0002",
            "startedAtUnixSeconds": time.time(),
        }), encoding="utf-8")
        holders = live_foreign_generation_holders(session_dir)
        assert [h.get("holder") for h in holders] == ["wave-0002"]
    finally:
        foreign.stop()

    # Dead foreign holders are reclaimed on read.
    time.sleep(0.2)
    assert live_foreign_generation_holders(session_dir) == []
    assert not (session_dir / "generation-holders" / f"{foreign.pid}.json").exists()

    clear_generation_holder_marker(session_dir)
    assert not marker.exists()


def test_stop_before_vlm_skips_while_foreign_generation_active(tmp_path) -> None:
    from types import SimpleNamespace
    from exercise_motion_pkg import wave_pipeline
    from exercise_motion_pkg.shared_llama_server import write_generation_holder_marker

    shared_dir = tmp_path / "shared"
    worker_dir = tmp_path / "gvhmr-worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "ready.json").write_text("{}", encoding="utf-8")

    item = SimpleNamespace(
        request=SimpleNamespace(
            use_warm_gvhmr_worker=True,
            gvhmr_worker_session_dir=worker_dir,
            shared_llama_server=True,
            shared_llama_server_session_dir=shared_dir,
            llama_cpp_base_url="http://127.0.0.1:8090",
        )
    )

    # No foreign generation: the worker stop proceeds. A fake worker answers
    # the stop handshake so the release wait completes.
    def fake_worker_answers_stop() -> None:
        stop_path = worker_dir / "stop"
        for _ in range(120):
            if stop_path.exists():
                (worker_dir / "stopped.json").write_text("{}", encoding="utf-8")
                return
            time.sleep(0.25)

    responder = threading.Thread(target=fake_worker_answers_stop, daemon=True)
    responder.start()
    release = wave_pipeline._stop_warm_reconstruction_worker_before_vlm([item])
    assert release["stopped"] is True
    responder.join(timeout=5)

    # Reset worker state, then announce a live foreign generation.
    for name in ("stop", "stopped.json"):
        path = worker_dir / name
        if path.exists():
            path.unlink()
    (worker_dir / "ready.json").write_text("{}", encoding="utf-8")
    foreign = _LiveForeignProcess()
    try:
        holder = shared_dir / "generation-holders" / f"{foreign.pid}.json"
        holder.parent.mkdir(parents=True, exist_ok=True)
        holder.write_text(json.dumps({
            "pid": foreign.pid,
            "processIdentity": foreign.identity,
            "holder": "wave-0009",
            "startedAtUnixSeconds": time.time(),
        }), encoding="utf-8")
        release = wave_pipeline._stop_warm_reconstruction_worker_before_vlm([item])
        assert release["stopped"] is False
        assert release["skippedForForeignGeneration"] is True
        assert release["foreignHolders"] == ["wave-0009"]
        # The warm worker was left untouched.
        assert not (worker_dir / "stop").exists()
    finally:
        foreign.stop()


def test_supervised_server_wait_extends_for_foreign_generation(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace
    from exercise_motion_pkg import youtube as youtube_module
    from exercise_motion_pkg.youtube import LlamaCppVisionRanker

    foreign = _LiveForeignProcess()
    try:
        shared_dir = tmp_path / "shared"
        holder = shared_dir / "generation-holders" / f"{foreign.pid}.json"
        holder.parent.mkdir(parents=True, exist_ok=True)
        holder.write_text(json.dumps({
            "pid": foreign.pid,
            "processIdentity": foreign.identity,
            "holder": "wave-0007",
            "startedAtUnixSeconds": time.time(),
        }), encoding="utf-8")
        monkeypatch.setenv("EXERCISE_MOTION_SHARED_LLAMA_SESSION_DIR", str(shared_dir))

        ranker = object.__new__(LlamaCppVisionRanker)
        ranker._source_startup_deadline = None
        ranker.settings = SimpleNamespace(
            llama_cpp_base_url="http://127.0.0.1:8090",
            llama_cpp_server_startup_timeout_seconds=2.0,
        )
        attempts = {"count": 0}

        def never_ready() -> None:
            attempts["count"] += 1

        monkeypatch.setattr(ranker, "_server_models_payload", lambda: None)
        monkeypatch.setattr(LlamaCppVisionRanker, "_raise_if_server_model_mismatch", lambda self, payload: None)
        monkeypatch.setattr(LlamaCppVisionRanker, "_raise_if_server_runtime_mismatch", lambda self: None)
        monkeypatch.setattr(LlamaCppVisionRanker, "_wait_for_chat_completions_ready", lambda self: None)

        started = time.perf_counter()
        with pytest.raises(RuntimeError, match="did not become ready"):
            ranker._wait_for_supervised_server()
        elapsed = time.perf_counter() - started
        # The foreign generation keeps extending the 2s startup timeout well
        # past its normal expiry (bounded by the hard ceiling).
        assert elapsed >= 3.0
    finally:
        foreign.stop()
