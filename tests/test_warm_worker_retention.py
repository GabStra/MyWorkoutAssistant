from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from exercise_motion_pkg import gvhmr_warm_worker, wham_warm_worker
from exercise_motion_pkg import warm_worker_retention


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_job_artifacts(state_dir: Path, job_id: str, status: str, modified_at: float) -> Path:
    result_path = state_dir / "results" / f"{job_id}.json"
    _write_json(result_path, {"jobId": job_id, "status": status})
    for suffix in ("stdout.log", "stderr.log"):
        log_path = state_dir / "job_logs" / f"{job_id}.{suffix}"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"log for {job_id}", encoding="utf-8")
        os.utime(log_path, (modified_at, modified_at))
    os.utime(result_path, (modified_at, modified_at))
    return result_path


@pytest.mark.parametrize(
    ("worker", "load_function", "release_function"),
    [
        (wham_warm_worker, "load_wham_once", "release_wham_state"),
        (gvhmr_warm_worker, "load_gvhmr_once", "release_gvhmr_state"),
    ],
)
def test_worker_startup_prunes_only_expired_or_excess_terminal_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    worker: ModuleType,
    load_function: str,
    release_function: str,
) -> None:
    state_dir = tmp_path / "worker-state"
    for child in ("jobs", "running", "results", "job_logs", "ambiguous"):
        (state_dir / child).mkdir(parents=True, exist_ok=True)

    now = time.time()
    monkeypatch.setattr(warm_worker_retention, "WARM_WORKER_RESULT_RETENTION_SECONDS", 10)
    monkeypatch.setattr(warm_worker_retention, "MAX_RETAINED_WARM_WORKER_RESULTS", 1)

    old_terminal = _write_job_artifacts(state_dir, "old-terminal", "completed", now - 20)
    excess_terminal = _write_job_artifacts(state_dir, "excess-terminal", "failed", now - 5)
    recent_terminal = _write_job_artifacts(state_dir, "recent-terminal", "completed", now - 1)

    ambiguous_result = _write_job_artifacts(
        state_dir, "interrupted", "interrupted_ambiguous", now - 30
    )
    _write_json(
        state_dir / "ambiguous" / "interrupted.json",
        {"jobId": "interrupted", "partialOutputPossible": True},
    )

    queued_result = _write_job_artifacts(state_dir, "queued", "completed", now - 30)
    queued_request = state_dir / "jobs" / "queued.json"
    _write_json(queued_request, {"jobId": "queued"})

    active_identity = {"candidateId": "previously-completed"}
    active_result = _write_job_artifacts(state_dir, "active", "completed", now - 30)
    _write_json(
        state_dir / "results" / "active.json",
        {"jobId": "active", "stageIdentity": active_identity, "status": "completed"},
    )
    active_request = state_dir / "running" / "active.json"
    _write_json(active_request, {"jobId": "active", "stageIdentity": active_identity})
    active_result_time = now - 30
    os.utime(active_result, (active_result_time, active_result_time))
    (state_dir / "stop").write_text("stop\n", encoding="utf-8")

    monkeypatch.setattr(
        worker,
        "parse_args",
        lambda: SimpleNamespace(state_dir=state_dir, poll_seconds=0.01),
    )

    def fake_load_worker() -> dict:
        assert not old_terminal.exists()
        assert not excess_terminal.exists()
        assert recent_terminal.exists()
        return {"loadSeconds": 0.0, "gpuName": "test-only"}

    monkeypatch.setattr(worker, load_function, fake_load_worker)
    monkeypatch.setattr(worker, release_function, lambda _state: None)

    assert worker.main() == 0

    for pruned_job_id in ("old-terminal", "excess-terminal"):
        assert not (state_dir / "results" / f"{pruned_job_id}.json").exists()
        assert not (state_dir / "job_logs" / f"{pruned_job_id}.stdout.log").exists()
        assert not (state_dir / "job_logs" / f"{pruned_job_id}.stderr.log").exists()

    for retained_job_id in ("recent-terminal", "interrupted", "queued", "active"):
        assert (state_dir / "results" / f"{retained_job_id}.json").exists()
        assert (state_dir / "job_logs" / f"{retained_job_id}.stdout.log").exists()
        assert (state_dir / "job_logs" / f"{retained_job_id}.stderr.log").exists()

    assert queued_request.exists()
    assert not active_request.exists()
    assert (state_dir / "ambiguous" / "active.json").exists()
    assert (state_dir / "ambiguous" / "interrupted.json").exists()
    assert json.loads(ambiguous_result.read_text(encoding="utf-8"))["status"] == "interrupted_ambiguous"
    assert json.loads(queued_result.read_text(encoding="utf-8"))["status"] == "completed"


def test_every_warm_worker_docker_launch_mounts_retention_helper() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    launch_scripts = (
        "scripts/run_exercise_motion_workout_plan.ps1",
        "scripts/run_exercise_motion_bake_and_rank.ps1",
        "scripts/run_exercise_motion_youtube_bake_and_rank.ps1",
        "scripts/motion_speed_harness.py",
    )
    for script_relative_path in launch_scripts:
        script_text = (repository_root / script_relative_path).read_text(encoding="utf-8")
        assert "/worker/warm_worker_retention.py:ro" in script_text, script_relative_path

    optional_parity_script = repository_root / "scripts/gvhmr_image_parity.py"
    if optional_parity_script.exists():
        assert "/worker/warm_worker_retention.py:ro" in optional_parity_script.read_text(
            encoding="utf-8"
        )


@pytest.mark.parametrize("worker_filename", ("wham_warm_worker.py", "gvhmr_warm_worker.py"))
def test_mounted_worker_script_imports_retention_helper_without_package(
    tmp_path: Path,
    worker_filename: str,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    package_dir = repository_root / "exercise_motion_pkg"
    worker_mount = tmp_path / "worker"
    worker_mount.mkdir()
    shutil.copy2(package_dir / worker_filename, worker_mount / worker_filename)
    shutil.copy2(
        package_dir / "warm_worker_retention.py",
        worker_mount / "warm_worker_retention.py",
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, "-S", str(worker_mount / worker_filename), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Warm" in completed.stdout
