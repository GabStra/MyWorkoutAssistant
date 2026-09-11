import json
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from exercise_motion_pkg import wham_runner


def write_ready(path):
    (path / "ready.json").write_text("{}")
    (path / "heartbeat.json").write_text(json.dumps({"updatedAtUnixSeconds": time.time()}))


def test_lazy_worker_waits_for_supervisor_acknowledgment(tmp_path, monkeypatch):
    monkeypatch.setenv("EXERCISE_MOTION_WHAM_LAZY_START", "1")
    # Leftovers from a terminated worker must not satisfy a new startup.
    write_ready(tmp_path)
    (tmp_path / "stopped.json").write_text("{}")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(wham_runner.ensure_warm_worker_ready, tmp_path, timeout_seconds=3)
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


def test_lazy_worker_timeout_cleans_request(tmp_path, monkeypatch):
    monkeypatch.setenv("EXERCISE_MOTION_WHAM_LAZY_START", "1")
    with pytest.raises(TimeoutError):
        wham_runner.ensure_warm_worker_ready(tmp_path, timeout_seconds=0)
    assert not (tmp_path / "start_requested.json").exists()


def test_existing_worker_needs_no_startup_request(tmp_path, monkeypatch):
    monkeypatch.delenv("EXERCISE_MOTION_WHAM_LAZY_START", raising=False)
    write_ready(tmp_path)
    wham_runner.ensure_warm_worker_ready(tmp_path, timeout_seconds=0)
    assert not (tmp_path / "start_requested.json").exists()


def test_shared_vision_deadlines_are_independent(tmp_path):
    from exercise_motion_pkg.bake_and_rank import BakeAndRankRequest, LazyLlamaCppVisionSession

    session = LazyLlamaCppVisionSession(BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json", workspace=tmp_path,
        wham_repo_path=None, body_model_root=None,
    ))
    barrier = threading.Barrier(2)

    def set_deadline(value):
        session.set_candidate_deadline(value)
        barrier.wait(timeout=2)
        return session._candidate_deadlines.value

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(set_deadline, [1.0, 2.0])) == [1.0, 2.0]


def test_cache_only_wave_does_not_wait_for_unstarted_worker(tmp_path):
    from types import SimpleNamespace
    from exercise_motion_pkg.wave_pipeline import _stop_warm_wham_worker_before_vlm

    item = SimpleNamespace(request=SimpleNamespace(
        use_warm_wham_worker=True, wham_worker_session_dir=tmp_path,
    ))
    assert _stop_warm_wham_worker_before_vlm([item])["stopped"] is True
    assert not (tmp_path / "stop").exists()


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
                                  wham_repo_path=None, body_model_root=None),
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
        wham_cache_status="reused_local", wham_results_pkl=tmp_path / "wham.pkl"))
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
            assert request.require_wham_cache
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
