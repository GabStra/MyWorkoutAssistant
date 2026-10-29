import json
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from exercise_motion_pkg import reconstruction_runner


def write_ready(path):
    (path / "ready.json").write_text("{}")
    (path / "heartbeat.json").write_text(json.dumps({"updatedAtUnixSeconds": time.time()}))


@pytest.mark.parametrize(
    ("lazy_start_env_var", "label"),
    [
        ("EXERCISE_MOTION_GVHMR_LAZY_START", "GVHMR"),
    ],
)
def test_lazy_worker_waits_for_supervisor_acknowledgment(
    tmp_path, monkeypatch, lazy_start_env_var, label
):
    monkeypatch.setenv(lazy_start_env_var, "1")
    # Leftovers from a terminated worker must not satisfy a new startup.
    write_ready(tmp_path)
    (tmp_path / "stopped.json").write_text("{}")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            reconstruction_runner.ensure_warm_worker_ready,
            tmp_path,
            timeout_seconds=3,
            lazy_start_env_var=lazy_start_env_var,
            label=label,
        )
        request = tmp_path / "start_requested.json"
        deadline = time.monotonic() + 2
        while not request.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert request.exists()
        assert not future.done()
        (tmp_path / "stopped.json").unlink()
        write_ready(tmp_path)
        request.unlink()
        future.result(timeout=2)


def test_stopped_gvhmr_worker_without_lazy_start_reports_not_ready(tmp_path, monkeypatch):
    monkeypatch.delenv("EXERCISE_MOTION_GVHMR_LAZY_START", raising=False)
    write_ready(tmp_path)
    (tmp_path / "stopped.json").write_text("{}")

    with pytest.raises(RuntimeError, match="Warm GVHMR worker is not ready"):
        reconstruction_runner.ensure_warm_worker_ready(
            tmp_path,
            timeout_seconds=0,
            lazy_start_env_var="EXERCISE_MOTION_GVHMR_LAZY_START",
            label="GVHMR",
        )

    assert not (tmp_path / "start_requested.json").exists()


def test_lazy_worker_timeout_cleans_request(tmp_path, monkeypatch):
    monkeypatch.setenv("EXERCISE_MOTION_GVHMR_LAZY_START", "1")
    with pytest.raises(TimeoutError):
        reconstruction_runner.ensure_warm_worker_ready(
            tmp_path, timeout_seconds=0,
            lazy_start_env_var="EXERCISE_MOTION_GVHMR_LAZY_START", label="GVHMR",
        )
    assert not (tmp_path / "start_requested.json").exists()


def test_candidate_deadline_caps_lazy_worker_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("EXERCISE_MOTION_GVHMR_LAZY_START", "1")
    started = time.perf_counter()
    with pytest.raises(TimeoutError, match="supervised GVHMR worker startup"):
        reconstruction_runner.ensure_warm_worker_ready(
            tmp_path,
            timeout_seconds=30,
            deadline=started + 0.08,
            lazy_start_env_var="EXERCISE_MOTION_GVHMR_LAZY_START",
            label="GVHMR",
        )
    assert time.perf_counter() - started < 0.5
    assert not (tmp_path / "start_requested.json").exists()


def test_existing_worker_needs_no_startup_request(tmp_path, monkeypatch):
    monkeypatch.delenv("EXERCISE_MOTION_GVHMR_LAZY_START", raising=False)
    write_ready(tmp_path)
    reconstruction_runner.ensure_warm_worker_ready(
        tmp_path, timeout_seconds=0,
        lazy_start_env_var="EXERCISE_MOTION_GVHMR_LAZY_START", label="GVHMR",
    )
    assert not (tmp_path / "start_requested.json").exists()


def test_shared_vision_deadlines_are_independent(tmp_path):
    from exercise_motion_pkg.bake_and_rank import BakeAndRankRequest, LazyLlamaCppVisionSession

    session = LazyLlamaCppVisionSession(BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json", workspace=tmp_path,
        body_model_root=None,
    ))
    barrier = threading.Barrier(2)

    def set_deadline(value):
        from exercise_motion_pkg.motion_scheduler import current_gpu_stage_deadline

        session.set_candidate_deadline(value)
        barrier.wait(timeout=2)
        return session._candidate_deadlines.get(), current_gpu_stage_deadline()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(set_deadline, [1.0, 2.0])) == [(1.0, 1.0), (2.0, 2.0)]


def test_candidate_deadline_scope_restores_session_and_scheduler_context(tmp_path):
    from exercise_motion_pkg.bake_and_rank import (
        BakeAndRankRequest,
        LazyLlamaCppVisionSession,
        caption_candidate_deadline_scope,
    )
    from exercise_motion_pkg.motion_scheduler import current_gpu_stage_deadline

    session = LazyLlamaCppVisionSession(BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json", workspace=tmp_path,
        body_model_root=None,
    ))
    deadline = time.perf_counter() + 10
    with pytest.raises(RuntimeError, match="candidate failed"):
        with caption_candidate_deadline_scope((session.caption_images,), deadline):
            assert session._candidate_deadlines.get() == deadline
            assert current_gpu_stage_deadline() == deadline
            raise RuntimeError("candidate failed")
    assert session._candidate_deadlines.get() is None
    assert current_gpu_stage_deadline() is None


def test_cache_only_wave_does_not_wait_for_unstarted_worker(tmp_path):
    from types import SimpleNamespace
    from exercise_motion_pkg.wave_pipeline import _stop_warm_reconstruction_worker_before_vlm

    item = SimpleNamespace(request=SimpleNamespace(
        use_warm_gvhmr_worker=True, gvhmr_worker_session_dir=tmp_path,
    ))
    assert _stop_warm_reconstruction_worker_before_vlm([item])["stopped"] is True
    assert not (tmp_path / "stop").exists()


def test_explicit_split_gpu_lane_keeps_shared_reconstruction_worker_warm(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import wave_pipeline as wave

    worker_dir = tmp_path / "gvhmr-worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "ready.json").write_text("{}", encoding="utf-8")
    item = SimpleNamespace(request=SimpleNamespace(
        use_warm_gvhmr_worker=True,
        gvhmr_worker_session_dir=worker_dir,
        shared_llama_server=True,
        shared_llama_server_session_dir=tmp_path / "llama",
        llama_cpp_base_url="http://127.0.0.1:8090",
    ))
    monkeypatch.setattr(wave, "exclusive_gpu_device", lambda: "1")

    release = wave._stop_warm_reconstruction_worker_before_vlm([item])

    assert wave._wave_uses_separate_gpu_residency([item]) is True
    assert release == {
        "requested": False,
        "stopped": False,
        "skippedForSeparateGpuResidency": True,
    }
    assert not (worker_dir / "stop").exists()


def test_split_gpu_lane_requires_shared_vision_server(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import wave_pipeline as wave

    item = SimpleNamespace(request=SimpleNamespace(shared_llama_server=False))
    monkeypatch.setattr(wave, "exclusive_gpu_device", lambda: "1")

    assert wave._wave_uses_separate_gpu_residency([item]) is False


def test_wave_finalization_overlaps_and_preserves_other_results_on_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import wave_pipeline as wave
    from exercise_motion_pkg.bake_and_rank import BakeAndRankRequest, RankedCandidate

    class FakeSession:
        def __init__(self, request):
            self.closed = False

        def caption_images(self, **kwargs):
            return "{}"

        def run_without_llama_overlap(self, operation):
            return operation()

        def close(self, **kwargs):
            self.closed = True

    items = [wave.StagedWaveItem(
        exercise_id=str(index), exercise_name=f"Exercise {index}",
        request=BakeAndRankRequest(candidates_json=tmp_path / str(index) / "candidates.json",
                                  workspace=tmp_path / str(index) / "bake",
                                  body_model_root=None),
    ) for index in range(3)]
    candidates = {item.exercise_id: RankedCandidate(
        exercise_index=int(item.exercise_id), candidate_rank=0,
        exercise_id=item.exercise_id, exercise_name=item.exercise_name,
        exercise_slug=item.exercise_id, candidate={"videoId": item.exercise_id},
    ) for item in items}
    monkeypatch.setattr(wave, "LazyLlamaCppVisionSession", FakeSession)
    monkeypatch.setattr(wave, "_wave_candidates_for_item", lambda item: [candidates[item.exercise_id]])
    monkeypatch.setattr(wave, "build_exercise_motion_contract_resolver", lambda **kwargs: None)
    monkeypatch.setattr(wave, "evaluate_source_candidate_gate", lambda *args, **kwargs: {"passed": True})
    monkeypatch.setattr(wave, "prepare_candidate_input_video", lambda *args, **kwargs: tmp_path / "source.mp4")
    monkeypatch.setattr(wave, "generate_candidate_motion", lambda *args, **kwargs: SimpleNamespace(
        reconstruction_cache_status="reused_local", reconstruction_results_pkl=tmp_path / "reconstruction.pkl"))
    barrier = threading.Barrier(2)
    active = 0
    peak = 0
    lock = threading.Lock()

    def finalize(request, *, shared_vision_session, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            assert request.require_reconstruction_cache
            assert not shared_vision_session.closed
            if request.workspace.parent.name in {"0", "1"}:
                barrier.wait(timeout=3)
            if request.workspace.parent.name == "1":
                raise ValueError("deliberate failure")
            return {"selected": {"selectedWearSkeletonPath": "retained.json"}}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(wave, "run_bake_and_rank_pipeline", finalize)
    report = wave.run_staged_bake_wave(items, workspace=tmp_path / "wave", wave_id="test")
    assert peak == 2
    assert report["completedExerciseCount"] == 2
    assert report["retryExerciseIds"] == ["1"]
    decisions = [item["finalValidation"] for item in report["items"] if item["status"] == "completed"]
    for decision in decisions:
        snapshot = Path(decision["selectionManifestPath"])
        assert snapshot.exists()
        assert snapshot.parent.name == "final-decisions"
        current = Path(decision["currentSelectionManifestPath"])
        current.parent.mkdir(parents=True, exist_ok=True)
        current.write_text('{"selected": null}')
        assert json.loads(snapshot.read_text())["selected"] is not None
