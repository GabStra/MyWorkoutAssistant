from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest

from exercise_motion_pkg import gvhmr_runner, gvhmr_warm_worker
from exercise_motion_pkg.wave_pipeline import (
    candidate_generation_failure_details,
    generation_failure_status,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_worker_startup_archives_claimed_jobs_and_preserves_unclaimed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "worker-state"
    for child in ("jobs", "running", "results", "job_logs"):
        (state_dir / child).mkdir(parents=True, exist_ok=True)

    pending_payload = {"jobId": "unclaimed-job", "stageIdentity": {"candidateId": "pending"}}
    pending_path = state_dir / "jobs" / "unclaimed-job.json"
    _write_json(pending_path, pending_payload)
    interrupted_identity = {"runId": "run-1", "waveId": "wave-1", "candidateId": "candidate-a"}
    interrupted_payload = {
        "jobId": "interrupted-job",
        "stageIdentity": interrupted_identity,
        "video": "/workspace/input.mp4",
    }
    _write_json(state_dir / "running" / "interrupted-job.json", interrupted_payload)
    completed_payload = {"jobId": "completed-job", "stageIdentity": {"candidateId": "done"}}
    _write_json(state_dir / "running" / "completed-job.json", completed_payload)
    completed_result = {
        "jobId": "completed-job",
        "stageIdentity": completed_payload["stageIdentity"],
        "status": "completed",
    }
    completed_result_path = state_dir / "results" / "completed-job.json"
    _write_json(completed_result_path, completed_result)

    (state_dir / "stop").write_text("stop\n", encoding="utf-8")
    monkeypatch.setattr(
        gvhmr_warm_worker,
        "parse_args",
        lambda: SimpleNamespace(state_dir=state_dir, poll_seconds=0.01),
    )

    def fake_load_gvhmr_once() -> dict:
        recovered = json.loads((state_dir / "results" / "interrupted-job.json").read_text())
        assert recovered["status"] == "interrupted_ambiguous"
        return {"loadSeconds": 0.0, "gpuName": "test-only"}

    monkeypatch.setattr(gvhmr_warm_worker, "load_gvhmr_once", fake_load_gvhmr_once)
    monkeypatch.setattr(gvhmr_warm_worker, "release_gvhmr_state", lambda _state: None)

    assert gvhmr_warm_worker.main() == 0
    assert json.loads(pending_path.read_text(encoding="utf-8")) == pending_payload
    assert not list((state_dir / "running").glob("*.json"))
    assert {path.name for path in (state_dir / "ambiguous").glob("*.json")} == {
        "interrupted-job.json",
        "completed-job.json",
    }
    result = json.loads((state_dir / "results" / "interrupted-job.json").read_text())
    assert result["stageIdentity"] == interrupted_identity
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["recovery"]["partialOutputPossible"] is True
    assert result["recovery"]["automaticReplay"] is False
    assert json.loads(completed_result_path.read_text()) == completed_result


def test_runner_surfaces_interrupted_claim_as_typed_candidate_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mount_root = tmp_path / "workspace"
    input_video = mount_root / "candidate" / "input.mp4"
    input_video.parent.mkdir(parents=True)
    input_video.write_bytes(b"video")
    logs_dir = mount_root / "candidate" / "logs"
    session_dir = tmp_path / "worker-state"
    for child in ("jobs", "results", "job_logs", "ambiguous"):
        (session_dir / child).mkdir(parents=True, exist_ok=True)
    (session_dir / "ready.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")
    (session_dir / "heartbeat.json").write_text(
        json.dumps({"status": "alive", "updatedAtUnixSeconds": time.time()}),
        encoding="utf-8",
    )
    lease_threads: list[str] = []
    active_locks: list[str] = []

    @contextmanager
    def fake_gpu_lock(**_kwargs):
        lease_threads.append(threading.current_thread().name)
        active_locks.append("gpu")
        try:
            yield 0.0
        finally:
            active_locks.remove("gpu")

    @contextmanager
    def fake_docker_lock(*, enabled: bool = True, **_kwargs):
        assert active_locks == ["gpu"]
        lease_threads.append(threading.current_thread().name)
        active_locks.append("docker")
        try:
            yield 0.0 if enabled else 0.0
        finally:
            active_locks.remove("docker")

    def ensure_ready_under_leases(*_args, **_kwargs):
        assert active_locks == ["gpu", "docker"]

    real_assert_available = gvhmr_runner.assert_warm_worker_available

    def assert_available_under_leases(*args, **kwargs):
        assert active_locks == ["gpu", "docker"]
        return real_assert_available(*args, **kwargs)

    monkeypatch.setattr(gvhmr_runner, "gpu_stage_lock", fake_gpu_lock)
    monkeypatch.setattr(gvhmr_runner, "reconstruction_docker_run_lock", fake_docker_lock)
    monkeypatch.setattr(gvhmr_runner, "ensure_warm_worker_ready", ensure_ready_under_leases)
    monkeypatch.setattr(gvhmr_runner, "assert_warm_worker_available", assert_available_under_leases)
    monkeypatch.setattr(gvhmr_runner, "path_inside_worker_mount", lambda path, **_kwargs: str(path))
    monkeypatch.setattr(gvhmr_runner, "copy_worker_log", lambda *_args, **_kwargs: None)

    stage_identity = {"runId": "run-2", "waveId": "wave-2", "candidateId": "candidate-b"}

    def interrupted_result(result_path: Path, **_kwargs):
        request_path = session_dir / "jobs" / f"{result_path.stem}.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        return {
            "jobId": result_path.stem,
            "stageIdentity": request["stageIdentity"],
            "status": "interrupted_ambiguous",
            "terminal": True,
            "retryable": False,
            "error": "worker restarted after claim",
            "recovery": {
                "partialOutputPossible": True,
                "automaticReplay": False,
                "archivedRequestPath": f"ambiguous/{result_path.stem}.json",
            },
        }

    monkeypatch.setattr(gvhmr_runner, "wait_for_warm_worker_result", interrupted_result)

    with pytest.raises(gvhmr_runner.GvhmrWarmWorkerInterruptedAmbiguous) as raised:
        gvhmr_runner.run_gvhmr_with_warm_worker(
            input_video=input_video,
            output_root=mount_root / "candidate" / "raw",
            logs_dir=logs_dir,
            stdout_log=logs_dir / "gvhmr.stdout.log",
            stderr_log=logs_dir / "gvhmr.stderr.log",
            docker_image="gvhmr:test",
            static_camera=True,
            warm_worker_session_dir=session_dir,
            warm_worker_mount_root=mount_root,
            warm_worker_timeout_seconds=5.0,
            stage_identity=stage_identity,
        )

    error = raised.value
    assert lease_threads and all(name.endswith("-gpu") for name in lease_threads)
    assert error.stage_identity == stage_identity
    assert generation_failure_status(error) == "interrupted_ambiguous"
    assert candidate_generation_failure_details(error) == {
        "failureCode": "gvhmr_worker_interrupted_ambiguous",
        "status": "interrupted_ambiguous",
        "jobId": error.job_id,
        "stageIdentity": stage_identity,
        "resultPath": str((session_dir / "results" / f"{error.job_id}.json").resolve()),
        "ambiguousArchivePath": str((session_dir / "ambiguous" / f"{error.job_id}.json").resolve()),
        "partialOutputPossible": True,
        "automaticReplay": False,
        "error": "worker restarted after claim",
    }
