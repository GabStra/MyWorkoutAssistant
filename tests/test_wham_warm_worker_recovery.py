from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import wham_runner
from exercise_motion_pkg import wham_warm_worker
from exercise_motion_pkg.wave_pipeline import (
    candidate_generation_failure_details,
    generation_failure_status,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_worker_startup_archives_claimed_jobs_and_preserves_unclaimed_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "worker-state"
    for child in ("jobs", "running", "results", "job_logs"):
        (state_dir / child).mkdir(parents=True, exist_ok=True)

    pending_payload = {"jobId": "unclaimed-job", "stageIdentity": {"candidateId": "pending"}}
    pending_path = state_dir / "jobs" / "unclaimed-job.json"
    _write_json(pending_path, pending_payload)

    interrupted_identity = {
        "schemaVersion": 1,
        "runId": "run-1",
        "waveId": "run-1-wave-0001",
        "exerciseId": "ohp",
        "candidateId": "candidate-interrupted",
    }
    interrupted_payload = {
        "jobId": "interrupted-job",
        "stageIdentity": interrupted_identity,
        "video": "/workspace/input.mp4",
    }
    _write_json(state_dir / "running" / "interrupted-job.json", interrupted_payload)

    completed_identity = {"candidateId": "completed-before-restart"}
    _write_json(
        state_dir / "running" / "completed-job.json",
        {"jobId": "completed-job", "stageIdentity": completed_identity},
    )
    completed_result = {
        "jobId": "completed-job",
        "stageIdentity": completed_identity,
        "status": "completed",
        "resultsPkl": "/workspace/output/wham_output.pkl",
    }
    completed_result_path = state_dir / "results" / "completed-job.json"
    _write_json(completed_result_path, completed_result)

    # The replacement worker must recover requests before loading WHAM models.
    (state_dir / "stop").write_text("stop\n", encoding="utf-8")
    monkeypatch.setattr(
        wham_warm_worker,
        "parse_args",
        lambda: SimpleNamespace(state_dir=state_dir, poll_seconds=0.01),
    )

    def fake_load_wham_once() -> dict:
        recovered = json.loads((state_dir / "results" / "interrupted-job.json").read_text())
        assert recovered["status"] == "interrupted_ambiguous"
        return {"loadSeconds": 0.0, "gpuName": "test-only"}

    monkeypatch.setattr(wham_warm_worker, "load_wham_once", fake_load_wham_once)
    monkeypatch.setattr(wham_warm_worker, "release_wham_state", lambda _state: None)

    assert wham_warm_worker.main() == 0

    assert json.loads(pending_path.read_text(encoding="utf-8")) == pending_payload
    assert not list((state_dir / "running").glob("*.json"))
    ambiguous_paths = {path.name for path in (state_dir / "ambiguous").glob("*.json")}
    assert ambiguous_paths == {"interrupted-job.json", "completed-job.json"}

    interrupted_result = json.loads(
        (state_dir / "results" / "interrupted-job.json").read_text(encoding="utf-8")
    )
    assert interrupted_result["jobId"] == "interrupted-job"
    assert interrupted_result["stageIdentity"] == interrupted_identity
    assert interrupted_result["status"] == "interrupted_ambiguous"
    assert interrupted_result["terminal"] is True
    assert interrupted_result["retryable"] is False
    assert interrupted_result["recovery"]["partialOutputPossible"] is True
    assert interrupted_result["recovery"]["automaticReplay"] is False
    assert interrupted_result["recovery"]["archivedRequestPath"] == "ambiguous/interrupted-job.json"
    assert json.loads(completed_result_path.read_text(encoding="utf-8")) == completed_result
    assert json.loads(
        (state_dir / "ambiguous" / "interrupted-job.json").read_text(encoding="utf-8")
    ) == interrupted_payload


@pytest.mark.parametrize("worker_claimed_request", [False, True])
def test_worker_timeout_cancels_or_drains_request_before_shutdown(
    tmp_path: Path,
    worker_claimed_request: bool,
) -> None:
    result_path = tmp_path / "results" / "job-1.json"
    stopped_path = tmp_path / "stopped.json"
    stop_path = tmp_path / "stop"
    queued_path = tmp_path / "jobs" / "job-1.json"
    _write_json(queued_path, {"jobId": "job-1"})
    worker_finished = threading.Event()

    def simulated_worker() -> None:
        running_path = tmp_path / "running" / "job-1.json"
        if worker_claimed_request:
            running_path.parent.mkdir(parents=True, exist_ok=True)
            queued_path.replace(running_path)
        deadline = time.monotonic() + 2.0
        while not stop_path.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert stop_path.exists()
        if worker_claimed_request:
            _write_json(result_path, {"jobId": "job-1", "status": "completed"})
            running_path.unlink(missing_ok=True)
        _write_json(stopped_path, {"status": "stopped"})
        worker_finished.set()

    worker = threading.Thread(target=simulated_worker)
    worker.start()
    candidate_deadline = time.perf_counter() + 0.03
    try:
        with pytest.raises(TimeoutError, match="waiting for terminal worker shutdown"):
            wham_runner.wait_for_warm_worker_result(
                result_path,
                timeout_seconds=5.0,
                candidate_deadline=candidate_deadline,
                stopped_path=stopped_path,
            )
        assert stop_path.exists()
        assert worker_finished.is_set()
        assert stopped_path.exists()
        if worker_claimed_request:
            assert result_path.exists()
            assert not queued_path.exists()
        else:
            assert not queued_path.exists()
            assert (tmp_path / "cancelled_runs" / "job-1.json").exists()
    finally:
        worker.join(timeout=2.0)


def test_late_warm_worker_result_is_not_accepted_after_timeout(
    tmp_path: Path,
) -> None:
    result_path = tmp_path / "results" / "job-late.json"
    stopped_path = tmp_path / "stopped.json"
    stop_path = tmp_path / "stop"
    worker_finished = threading.Event()

    def simulated_worker() -> None:
        time.sleep(0.08)
        _write_json(result_path, {"jobId": "job-late", "status": "completed"})
        deadline = time.monotonic() + 2.0
        while not stop_path.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert stop_path.exists()
        _write_json(stopped_path, {"status": "stopped"})
        worker_finished.set()

    worker = threading.Thread(target=simulated_worker)
    worker.start()
    try:
        with pytest.raises(TimeoutError, match="waiting for terminal worker shutdown"):
            wham_runner.wait_for_warm_worker_result(
                result_path,
                timeout_seconds=0.03,
                stopped_path=stopped_path,
            )
        assert worker_finished.is_set()
        assert result_path.exists()
        assert stop_path.exists()
        assert stopped_path.exists()
    finally:
        worker.join(timeout=2.0)


def test_result_published_before_deadline_survives_a_late_poll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result_path = tmp_path / "results" / "job-on-time.json"
    poll_started = threading.Event()
    original_time = wham_runner.time

    def delayed_poll(_seconds: float) -> None:
        poll_started.set()
        original_time.sleep(0.08)

    def publish_on_time() -> None:
        assert poll_started.wait(timeout=2.0)
        original_time.sleep(0.005)
        _write_json(result_path, {"jobId": "job-on-time", "status": "completed"})

    worker = threading.Thread(target=publish_on_time)
    worker.start()
    monkeypatch.setattr(
        wham_runner,
        "time",
        SimpleNamespace(
            perf_counter=original_time.perf_counter,
            time=original_time.time,
            sleep=delayed_poll,
        ),
    )
    try:
        result = wham_runner.wait_for_warm_worker_result(
            result_path,
            timeout_seconds=5.0,
            candidate_deadline=original_time.perf_counter() + 0.03,
        )
        assert result["status"] == "completed"
    finally:
        worker.join(timeout=2.0)
    assert not worker.is_alive()


@pytest.mark.parametrize("result_job_id_matches", [True, False])
def test_wham_runner_surfaces_interrupted_result_as_typed_candidate_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result_job_id_matches: bool,
) -> None:
    mount_root = tmp_path / "workspace"
    input_video = mount_root / "candidate" / "input" / "selected_segment.mp4"
    input_video.parent.mkdir(parents=True)
    input_video.write_bytes(b"video")
    logs_dir = mount_root / "candidate" / "logs"
    logs_dir.mkdir(parents=True)
    session_dir = tmp_path / "worker-state"
    for child in ("jobs", "results", "job_logs", "ambiguous"):
        (session_dir / child).mkdir(parents=True, exist_ok=True)
    _write_json(session_dir / "ready.json", {"status": "ready"})
    _write_json(
        session_dir / "heartbeat.json",
        {"status": "alive", "updatedAtUnixSeconds": time.time()},
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

    real_ensure_ready = wham_runner.ensure_warm_worker_ready

    def ensure_ready_under_leases(*args, **kwargs):
        assert active_locks == ["gpu", "docker"]
        return real_ensure_ready(*args, **kwargs)

    real_wait_for_result = wham_runner.wait_for_warm_worker_result

    def wait_for_result_under_leases(*args, **kwargs):
        assert active_locks == ["gpu", "docker"]
        return real_wait_for_result(*args, **kwargs)

    monkeypatch.setattr(wham_runner, "gpu_stage_lock", fake_gpu_lock)
    monkeypatch.setattr(wham_runner, "wham_docker_run_lock", fake_docker_lock)
    monkeypatch.setattr(wham_runner, "ensure_warm_worker_ready", ensure_ready_under_leases)
    monkeypatch.setattr(wham_runner, "wait_for_warm_worker_result", wait_for_result_under_leases)

    stage_identity = {
        "schemaVersion": 1,
        "runId": "run-2",
        "waveId": "run-2-wave-0003",
        "exerciseId": "rdl",
        "candidateId": "candidate-b",
    }
    observed: dict[str, str] = {}

    def publish_interrupted_result() -> None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            requests = list((session_dir / "jobs").glob("*.json"))
            if requests:
                job_id = requests[0].stem
                observed["jobId"] = job_id
                _write_json(
                    session_dir / "results" / f"{job_id}.json",
                    {
                        "jobId": job_id if result_job_id_matches else "unrelated-job",
                        "status": "interrupted_ambiguous",
                        "terminal": True,
                        "retryable": False,
                        "error": "worker restarted after claim",
                        "recovery": {
                            "classification": "interrupted_ambiguous",
                            "partialOutputPossible": True,
                            "automaticReplay": False,
                            "archivedRequestPath": f"ambiguous/{job_id}.json",
                        },
                    },
                )
                return
            time.sleep(0.01)
        raise AssertionError("warm-worker client did not submit a job")

    worker = threading.Thread(target=publish_interrupted_result)
    worker.start()
    try:
        expected_error = (
            wham_runner.WarmWorkerInterruptedAmbiguous
            if result_job_id_matches
            else RuntimeError
        )
        with pytest.raises(expected_error) as raised:
            wham_runner.run_wham_with_warm_worker(
                input_video=input_video,
                output_root=mount_root / "candidate" / "raw" / "wham",
                logs_dir=logs_dir,
                stdout_log=logs_dir / "wham.stdout.log",
                stderr_log=logs_dir / "wham.stderr.log",
                estimate_local_only=True,
                run_smplify=False,
                use_docker=True,
                docker_image="wham:test",
                warm_worker_session_dir=session_dir,
                warm_worker_mount_root=mount_root,
                timeout_seconds=5.0,
                stage_identity=stage_identity,
            )
    finally:
        worker.join(timeout=5.0)

    error = raised.value
    assert not worker.is_alive()
    assert lease_threads and all(name.endswith("-gpu") for name in lease_threads)
    if result_job_id_matches:
        details = candidate_generation_failure_details(error)
        assert error.job_id == observed["jobId"]
        assert error.stage_identity == stage_identity
        assert generation_failure_status(error) == "interrupted_ambiguous"
        assert details == {
            "failureCode": "wham_worker_interrupted_ambiguous",
            "status": "interrupted_ambiguous",
            "jobId": observed["jobId"],
            "stageIdentity": stage_identity,
            "resultPath": str((session_dir / "results" / f"{observed['jobId']}.json").resolve()),
            "ambiguousArchivePath": str((session_dir / "ambiguous" / f"{observed['jobId']}.json").resolve()),
            "partialOutputPossible": True,
            "automaticReplay": False,
            "error": "worker restarted after claim",
        }
    else:
        assert isinstance(error, RuntimeError)
        assert "job ID does not match" in str(error)


def test_power_shell_startup_leaves_both_backend_queues_to_worker_recovery() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_exercise_motion_workout_plan.ps1"
    ).read_text(encoding="utf-8-sig")
    marker = "function Start-WhamWarmWorker {"
    start = script.index(marker)
    next_function = script.find("\nfunction ", start + len(marker))
    body = script[start:] if next_function < 0 else script[start:next_function]

    assert '$workerQueueDirectories = @("jobs", "running", "results", "job_logs", "ambiguous")' in body
    assert 'if ($Backend -ne "wham") {' not in body
    assert 'foreach ($queueDirectory in @("jobs", "running"))' not in body
    assert "Each backend worker now preserves unclaimed jobs and classifies claimed" in body
