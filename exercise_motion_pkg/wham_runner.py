from __future__ import annotations

import subprocess
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from typing import Any
from dataclasses import dataclass, field
from pathlib import Path

from exercise_motion_pkg.gpu_lock import (gpu_stage_lock, open_lock_lease, close_lock_lease,
                                        read_lock_text, lock_open_is_contention, process_identity,
                                        lock_lease_acquisition_guard)
from exercise_motion_pkg.motion_scheduler import gpu_stage_task, timeout_with_candidate_deadline


DEFAULT_WHAM_DOCKER_IMAGE = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1"
DEFAULT_WHAM_DOCKER_SHM_SIZE = "16g"
WHAM_DOCKER_SOURCE_ROOT = "/opt/wham-src"
DEFAULT_WHAM_REPO_PATH = Path(__file__).resolve().parents[1] / "third_party" / "WHAM"
DEFAULT_WHAM_BODY_MODEL_ROOT = DEFAULT_WHAM_REPO_PATH / "dataset" / "body_models"
DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY = True
DEFAULT_WHAM_TIMEOUT_SECONDS = 20 * 60.0
DEFAULT_WHAM_POSE_BACKEND = "vitpose"
DEFAULT_WHAM_POSE_BATCH_SIZE = 16
WHAM_EVAL_CHECKPOINT_NAME = "wham_vit_w_3dpw.pth.tar"
WHAM_DEMO_CHECKPOINT_NAME = "wham_vit_bedlam_w_3dpw.pth.tar"
DEFAULT_WHAM_FEATURE_BATCH_SIZE = 32
DEFAULT_WHAM_MAX_TRACK_GAP_FRAMES = 3
WHAM_DOCKER_LOCK_ENV_VAR = "EXERCISE_MOTION_WHAM_DOCKER_LOCK"
WHAM_DOCKER_LOCK_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_WHAM_DOCKER_LOCK_TIMEOUT_SECONDS"
WHAM_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_WHAM_TIMEOUT_SECONDS"
WHAM_WARM_WORKER_SESSION_DIR_ENV_VAR = "EXERCISE_MOTION_WHAM_WARM_WORKER_SESSION_DIR"
WHAM_WARM_WORKER_MOUNT_ROOT_ENV_VAR = "EXERCISE_MOTION_WHAM_WARM_WORKER_MOUNT_ROOT"
WHAM_WARM_WORKER_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_WHAM_WARM_WORKER_TIMEOUT_SECONDS"
DEFAULT_WHAM_DOCKER_LOCK_TIMEOUT_SECONDS = 6 * 60 * 60
DEFAULT_WHAM_WARM_WORKER_TIMEOUT_SECONDS = DEFAULT_WHAM_TIMEOUT_SECONDS
WHAM_WARM_WORKER_HEARTBEAT_STALE_SECONDS = 30.0
WHAM_TRACKING_PREFLIGHT_REJECTED_EXIT_CODE = 42


class WhamTrackingPreflightRejected(RuntimeError):
    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__(
            "WHAM tracking preflight rejected the input because the required movement interval "
            "is not continuously tracked."
        )
        self.report = report


class WarmWorkerInterruptedAmbiguous(RuntimeError):
    """A claimed warm-worker request stopped without trustworthy completion."""

    failure_code = "wham_worker_interrupted_ambiguous"
    status = "interrupted_ambiguous"

    def __init__(
        self,
        *,
        job_id: str,
        session_dir: Path,
        result_path: Path,
        result_payload: dict[str, Any],
        expected_stage_identity: dict[str, Any] | None,
    ) -> None:
        self.job_id = job_id
        self.session_dir = Path(session_dir).expanduser().resolve()
        self.result_path = Path(result_path).expanduser().resolve()
        self.result_payload = dict(result_payload)
        self.stage_identity = expected_stage_identity
        recovery = result_payload.get("recovery")
        self.recovery = dict(recovery) if isinstance(recovery, dict) else {}
        archive_name = Path(str(self.recovery.get("archivedRequestPath") or "")).name
        self.archive_path = (
            self.session_dir / "ambiguous" / archive_name if archive_name else None
        )
        detail = str(result_payload.get("error") or "output completeness is unknown")
        super().__init__(
            f"WHAM warm-worker job {job_id} was interrupted after claim and was not replayed: {detail}"
        )

    def diagnostic_payload(self) -> dict[str, Any]:
        return {
            "failureCode": self.failure_code,
            "status": self.status,
            "jobId": self.job_id,
            "stageIdentity": self.stage_identity,
            "resultPath": str(self.result_path),
            "ambiguousArchivePath": str(self.archive_path) if self.archive_path else None,
            "partialOutputPossible": bool(self.recovery.get("partialOutputPossible", True)),
            "automaticReplay": bool(self.recovery.get("automaticReplay", False)),
            "error": str(self.result_payload.get("error") or ""),
        }


def wham_preprocessing_environment() -> dict[str, str]:
    return {
        "WHAM_POSE_BACKEND": DEFAULT_WHAM_POSE_BACKEND,
        "WHAM_POSE_BATCH_SIZE": str(DEFAULT_WHAM_POSE_BATCH_SIZE),
        "WHAM_FEATURE_BATCH_SIZE": str(DEFAULT_WHAM_FEATURE_BATCH_SIZE),
        "WHAM_MAX_TRACK_GAP_FRAMES": str(DEFAULT_WHAM_MAX_TRACK_GAP_FRAMES),
    }


@dataclass(frozen=True)
class WhamRunResult:
    output_dir: Path
    results_pkl: Path
    stdout_log: Path
    stderr_log: Path
    command: list[str]
    elapsed_seconds: float
    returncode: int
    use_docker: bool
    estimate_local_only: bool
    run_smplify: bool
    docker_image: str | None = None
    docker_lock_wait_seconds: float = 0.0
    gpu_lock_wait_seconds: float = 0.0
    timeout_seconds: float | None = None
    warm_worker: bool = False
    warm_worker_job_id: str | None = None
    warm_worker_session_dir: Path | None = None
    stage_timings: dict[str, float | bool] = field(default_factory=dict)
    stage_identity: dict[str, Any] | None = None

    def timing_payload(self) -> dict[str, Any]:
        return {
            "elapsedSeconds": round(self.elapsed_seconds, 3),
            "returncode": self.returncode,
            "useDocker": self.use_docker,
            "estimateLocalOnly": self.estimate_local_only,
            "runSmplify": self.run_smplify,
            "dockerImage": self.docker_image if self.use_docker else None,
            "timeoutSeconds": round(self.timeout_seconds, 3) if self.timeout_seconds is not None else None,
            "warmWorker": self.warm_worker,
            "warmWorkerJobId": self.warm_worker_job_id,
            "warmWorkerSessionDir": str(self.warm_worker_session_dir) if self.warm_worker_session_dir is not None else None,
            "stageIdentity": self.stage_identity,
            "stdoutLog": str(self.stdout_log),
            "stderrLog": str(self.stderr_log),
            "command": self.command,
            "outputDir": str(self.output_dir),
            "resultsPkl": str(self.results_pkl),
            "dockerLockWaitSeconds": round(self.docker_lock_wait_seconds, 3) if self.use_docker else 0.0,
            "gpuLockWaitSeconds": round(self.gpu_lock_wait_seconds, 3),
            "stageTimings": self.stage_timings,
            "preprocessing": {
                "poseBackend": DEFAULT_WHAM_POSE_BACKEND,
                "poseBatchSize": DEFAULT_WHAM_POSE_BATCH_SIZE,
                "featureBatchSize": DEFAULT_WHAM_FEATURE_BATCH_SIZE,
                "maxTrackGapFrames": DEFAULT_WHAM_MAX_TRACK_GAP_FRAMES,
            },
        }






@gpu_stage_task("wham_reconstruction")
def run_wham_locally(
    *,
    wham_repo_path: Path,
    input_video: Path,
    output_root: Path,
    logs_dir: Path,
    python_command: str,
    estimate_local_only: bool = DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY,
    run_smplify: bool = True,
    use_docker: bool = False,
    docker_image: str = DEFAULT_WHAM_DOCKER_IMAGE,
    docker_gpus: str = "all",
    docker_shm_size: str = DEFAULT_WHAM_DOCKER_SHM_SIZE,
    use_warm_worker: bool = False,
    warm_worker_session_dir: Path | None = None,
    warm_worker_mount_root: Path | None = None,
    warm_worker_timeout_seconds: float | None = None,
    timeout_seconds: float | None = None,
    tracking_preflight: bool = False,
    required_start_seconds: float | None = None,
    required_end_seconds: float | None = None,
    stage_identity: dict[str, Any] | None = None,
    candidate_deadline: float | None = None,
) -> WhamRunResult:
    validate_wham_repo_layout(
        wham_repo_path,
        estimate_local_only=estimate_local_only,
        use_docker=use_docker,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = logs_dir / "wham.stdout.log"
    stderr_log = logs_dir / "wham.stderr.log"
    if use_warm_worker:
        warm_timeout = timeout_with_candidate_deadline(
            warm_worker_timeout_seconds
            if warm_worker_timeout_seconds is not None
            else timeout_seconds,
            candidate_deadline,
            stage_name="WHAM warm-worker reconstruction",
        )
        return run_wham_with_warm_worker(
            input_video=input_video,
            output_root=output_root,
            logs_dir=logs_dir,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            estimate_local_only=estimate_local_only,
            run_smplify=run_smplify,
            use_docker=use_docker,
            docker_image=docker_image,
            warm_worker_session_dir=warm_worker_session_dir,
            warm_worker_mount_root=warm_worker_mount_root,
            timeout_seconds=warm_timeout,
            tracking_preflight=tracking_preflight,
            required_start_seconds=required_start_seconds,
            required_end_seconds=required_end_seconds,
            stage_identity=stage_identity,
            candidate_deadline=candidate_deadline,
        )
    timeout = resolve_wham_timeout_seconds(timeout_seconds)
    timeout = timeout_with_candidate_deadline(
        timeout,
        candidate_deadline,
        stage_name="WHAM reconstruction",
    )
    docker_container_name = f"mwa-wham-job-{uuid.uuid4().hex}" if use_docker else None
    command = build_wham_command(
        wham_repo_path=wham_repo_path,
        input_video=input_video,
        output_root=output_root,
        python_command=python_command,
        estimate_local_only=estimate_local_only,
        run_smplify=run_smplify,
        use_docker=use_docker,
        docker_image=docker_image,
        docker_gpus=docker_gpus,
        docker_shm_size=docker_shm_size,
        docker_container_name=docker_container_name,
    )
    started = time.perf_counter()
    lock_wait_seconds = 0.0
    gpu_lock_wait_seconds = 0.0
    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open(
        "w",
        encoding="utf-8",
    ) as stderr_handle:
        with gpu_stage_lock(stage="wham") as gpu_lock_wait_seconds:
            with wham_docker_run_lock(enabled=use_docker) as lock_wait_seconds:
                if tracking_preflight:
                    preflight_report_path = (
                        output_root / input_video.stem / "tracking_preflight.json"
                    )
                    preflight_report_path.parent.mkdir(parents=True, exist_ok=True)
                    preflight_command = build_wham_tracking_preflight_command(
                        wham_repo_path=wham_repo_path,
                        script_path=Path(__file__).with_name("wham_tracking_preflight.py"),
                        input_video=input_video,
                        output_root=output_root,
                        report_path=preflight_report_path,
                        python_command=python_command,
                        required_start_seconds=required_start_seconds,
                        required_end_seconds=required_end_seconds,
                        use_docker=use_docker,
                        docker_image=docker_image,
                        docker_gpus=docker_gpus,
                        docker_shm_size=docker_shm_size,
                    )
                    preflight_returncode = run_wham_process(
                        preflight_command,
                        cwd=str(wham_repo_path),
                        stdout=stdout_handle,
                        stderr=stderr_handle,
                        timeout_seconds=timeout_with_candidate_deadline(
                            timeout,
                            candidate_deadline,
                            stage_name="WHAM tracking preflight",
                        ),
                    )
                    if preflight_returncode == WHAM_TRACKING_PREFLIGHT_REJECTED_EXIT_CODE:
                        try:
                            report = json.loads(preflight_report_path.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            report = {"passed": False, "reportPath": str(preflight_report_path)}
                        raise WhamTrackingPreflightRejected(report)
                    if preflight_returncode != 0:
                        raise RuntimeError(
                            "WHAM tracking preflight failed. Check logs:\n"
                            f"- {stdout_log}\n- {stderr_log}"
                        )
                returncode = run_wham_process(
                    command,
                    cwd=str(wham_repo_path),
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    timeout_seconds=timeout_with_candidate_deadline(
                        timeout,
                        candidate_deadline,
                        stage_name="WHAM reconstruction",
                    ),
                    docker_container_name=docker_container_name,
                )
    elapsed = time.perf_counter() - started
    if returncode != 0:
        raise RuntimeError(
            "WHAM run failed. Check logs:\n"
            f"- {stdout_log}\n"
            f"- {stderr_log}"
        )

    sequence_dir = output_root / input_video.stem
    results_pkl = sequence_dir / "wham_output.pkl"
    if not results_pkl.exists():
        raise RuntimeError(
            "WHAM run completed but no wham_output.pkl was found.\n"
            f"Expected: {results_pkl}\n"
            f"Logs:\n- {stdout_log}\n- {stderr_log}"
        )
    return WhamRunResult(
        output_dir=sequence_dir,
        results_pkl=results_pkl,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        command=command,
        elapsed_seconds=elapsed,
        returncode=returncode,
        use_docker=use_docker,
        estimate_local_only=estimate_local_only,
        run_smplify=run_smplify,
        docker_image=docker_image if use_docker else None,
        docker_lock_wait_seconds=lock_wait_seconds,
        gpu_lock_wait_seconds=gpu_lock_wait_seconds,
        timeout_seconds=timeout,
    )


def ensure_warm_worker_ready(
    session_dir: Path,
    *,
    timeout_seconds: float,
    lazy_start_env_var: str = "EXERCISE_MOTION_WHAM_LAZY_START",
    label: str = "WHAM",
) -> None:
    """Ask the supervising wrapper to start the worker only on a cache miss."""
    ready_path = session_dir / "ready.json"
    try:
        if ready_path.exists() and not any((session_dir / name).exists() for name in ("stop", "stopped.json")):
            assert_warm_worker_heartbeat(session_dir / "heartbeat.json")
            return
    except RuntimeError:
        pass
    if os.environ.get(lazy_start_env_var) != "1":
        raise RuntimeError(f"Warm {label} worker is not ready: {ready_path}")
    request_path = session_dir / "start_requested.json"
    request_path.write_text(json.dumps({"requestedBy": os.getpid()}), encoding="utf-8")
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            # The supervisor removes the request only after successful startup.
            if not request_path.exists() and ready_path.exists():
                assert_warm_worker_heartbeat(session_dir / "heartbeat.json")
                return
            time.sleep(0.25)
        raise TimeoutError(f"Timed out waiting for supervised {label} worker startup")
    finally:
        request_path.unlink(missing_ok=True)


@gpu_stage_task("wham_warm_worker_reconstruction")
def run_wham_with_warm_worker(
    *,
    input_video: Path,
    output_root: Path,
    logs_dir: Path,
    stdout_log: Path,
    stderr_log: Path,
    estimate_local_only: bool,
    run_smplify: bool,
    use_docker: bool,
    docker_image: str,
    warm_worker_session_dir: Path | None,
    warm_worker_mount_root: Path | None,
    timeout_seconds: float | None,
    tracking_preflight: bool = False,
    required_start_seconds: float | None = None,
    required_end_seconds: float | None = None,
    stage_identity: dict[str, Any] | None = None,
    candidate_deadline: float | None = None,
) -> WhamRunResult:
    if not use_docker:
        raise ValueError("Warm WHAM worker mode currently requires Docker WHAM execution.")
    session_dir = resolve_warm_worker_session_dir(warm_worker_session_dir)
    mount_root = resolve_warm_worker_mount_root(warm_worker_mount_root)
    worker_timeout = resolve_warm_worker_timeout_seconds(timeout_seconds)
    timeout = worker_timeout
    timeout = timeout_with_candidate_deadline(
        timeout,
        candidate_deadline,
        stage_name="WHAM warm-worker reconstruction",
    )
    jobs_dir = session_dir / "jobs"
    results_dir = session_dir / "results"
    job_logs_dir = session_dir / "job_logs"
    for path in (jobs_dir, results_dir, job_logs_dir):
        path.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    container_input_video = path_inside_worker_mount(input_video, mount_root=mount_root)
    container_output_root = path_inside_worker_mount(output_root, mount_root=mount_root)
    job_payload = {
        "jobId": job_id,
        "video": container_input_video,
        "outputRoot": container_output_root,
        "estimateLocalOnly": estimate_local_only,
        "runSmplify": run_smplify,
        "trackingPreflight": tracking_preflight,
        "requiredStartSeconds": required_start_seconds,
        "requiredEndSeconds": required_end_seconds,
        "stageIdentity": stage_identity,
    }
    job_path = jobs_dir / f"{job_id}.json"
    tmp_job_path = jobs_dir / f"{job_id}.json.tmp"
    result_path = results_dir / f"{job_id}.json"
    started = time.perf_counter()
    lock_wait_seconds = 0.0
    gpu_lock_wait_seconds = 0.0
    with gpu_stage_lock(stage="wham_warm_worker_job") as gpu_lock_wait_seconds:
        with wham_docker_run_lock(enabled=True) as lock_wait_seconds:
            # Lazy startup loads the model onto CUDA. Keep the same global GPU
            # and Docker leases across startup, readiness, and job admission so
            # startup cannot race another GPU owner and a stopped worker never
            # receives a newly queued request.
            # Startup must finish (or the supervising wrapper must stop the
            # container) before this process can release the GPU lease. A
            # candidate deadline may expire while startup is in progress, but
            # it cannot detach a CUDA-loading service from ownership.
            ensure_warm_worker_ready(session_dir, timeout_seconds=worker_timeout)
            timeout = timeout_with_candidate_deadline(
                worker_timeout,
                candidate_deadline,
                stage_name="WHAM warm-worker reconstruction",
            )
            assert_warm_worker_available(session_dir, label="WHAM")
            timeout = timeout_with_candidate_deadline(
                timeout,
                candidate_deadline,
                stage_name="WHAM warm-worker request",
            )
            tmp_job_path.write_text(json.dumps(job_payload, indent=2), encoding="utf-8")
            tmp_job_path.replace(job_path)
            result_payload = wait_for_warm_worker_result(
                result_path,
                timeout_seconds=timeout,
                candidate_deadline=candidate_deadline,
                heartbeat_path=session_dir / "heartbeat.json",
                stopped_path=session_dir / "stopped.json",
            )
    elapsed = time.perf_counter() - started
    worker_stdout_log = job_logs_dir / f"{job_id}.stdout.log"
    worker_stderr_log = job_logs_dir / f"{job_id}.stderr.log"
    copy_worker_log(worker_stdout_log, stdout_log)
    copy_worker_log(worker_stderr_log, stderr_log)
    if str(result_payload.get("jobId") or "") != job_id:
        raise RuntimeError(
            "Warm WHAM worker result job ID does not match the submitted request."
        )
    if result_payload.get("status") == WarmWorkerInterruptedAmbiguous.status:
        raise WarmWorkerInterruptedAmbiguous(
            job_id=job_id,
            session_dir=session_dir,
            result_path=result_path,
            result_payload=result_payload,
            expected_stage_identity=stage_identity,
        )
    if result_payload.get("stageIdentity") != stage_identity:
        raise RuntimeError(
            "Warm WHAM worker result stage identity does not match the submitted candidate."
        )
    if result_payload.get("status") == "rejected_tracking_preflight":
        raise WhamTrackingPreflightRejected(
            dict(result_payload.get("trackingPreflight") or {"passed": False})
        )
    if result_payload.get("status") != "completed":
        error = result_payload.get("error") or "unknown warm worker failure"
        raise RuntimeError(
            "Warm WHAM worker run failed. Check logs:\n"
            f"- {stdout_log}\n"
            f"- {stderr_log}\n"
            f"Error: {error}"
        )
    sequence_dir = output_root / input_video.stem
    results_pkl = sequence_dir / "wham_output.pkl"
    if not results_pkl.exists():
        raise RuntimeError(
            "Warm WHAM worker completed but no wham_output.pkl was found.\n"
            f"Expected: {results_pkl}\n"
            f"Worker result: {result_path}\n"
            f"Logs:\n- {stdout_log}\n- {stderr_log}"
        )
    return WhamRunResult(
        output_dir=sequence_dir,
        results_pkl=results_pkl,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        command=["wham-warm-worker", job_id],
        elapsed_seconds=elapsed,
        returncode=0,
        use_docker=True,
        estimate_local_only=estimate_local_only,
        run_smplify=run_smplify,
        docker_image=docker_image,
        docker_lock_wait_seconds=lock_wait_seconds,
        gpu_lock_wait_seconds=gpu_lock_wait_seconds,
        timeout_seconds=timeout,
        warm_worker=True,
        warm_worker_job_id=job_id,
        warm_worker_session_dir=session_dir,
        stage_timings=dict(result_payload.get("timings") or {}),
        stage_identity=stage_identity,
    )


def resolve_warm_worker_session_dir(configured: Path | None) -> Path:
    if configured is not None:
        return configured.expanduser().resolve()
    raw = os.environ.get(WHAM_WARM_WORKER_SESSION_DIR_ENV_VAR)
    if raw:
        return Path(raw).expanduser().resolve()
    raise ValueError(
        "Warm WHAM worker mode requires a session directory. "
        f"Pass --wham-worker-session-dir or set {WHAM_WARM_WORKER_SESSION_DIR_ENV_VAR}."
    )


def resolve_warm_worker_mount_root(configured: Path | None) -> Path:
    if configured is not None:
        return configured.expanduser().resolve()
    raw = os.environ.get(WHAM_WARM_WORKER_MOUNT_ROOT_ENV_VAR)
    if raw:
        return Path(raw).expanduser().resolve()
    raise ValueError(
        "Warm WHAM worker mode requires the host mount root. "
        f"Pass --wham-worker-mount-root or set {WHAM_WARM_WORKER_MOUNT_ROOT_ENV_VAR}."
    )


def resolve_warm_worker_timeout_seconds(configured: float | None) -> float | None:
    if configured is not None:
        return None if float(configured) <= 0.0 else max(1.0, float(configured))
    raw = os.environ.get(WHAM_WARM_WORKER_TIMEOUT_SECONDS_ENV_VAR)
    if raw is not None:
        try:
            value = float(raw)
            return None if value <= 0.0 else max(1.0, value)
        except ValueError:
            pass
    return None if DEFAULT_WHAM_WARM_WORKER_TIMEOUT_SECONDS <= 0.0 else float(DEFAULT_WHAM_WARM_WORKER_TIMEOUT_SECONDS)


def resolve_wham_timeout_seconds(configured: float | None) -> float | None:
    if configured is not None:
        return None if float(configured) <= 0.0 else max(1.0, float(configured))
    raw = os.environ.get(WHAM_TIMEOUT_SECONDS_ENV_VAR)
    if raw is not None:
        try:
            value = float(raw)
            return None if value <= 0.0 else max(1.0, value)
        except ValueError:
            pass
    return None if DEFAULT_WHAM_TIMEOUT_SECONDS <= 0.0 else float(DEFAULT_WHAM_TIMEOUT_SECONDS)


def run_wham_process(
    command: list[str],
    *,
    cwd: str,
    stdout: Any,
    stderr: Any,
    timeout_seconds: float | None,
    docker_container_name: str | None = None,
) -> int:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=stdout,
        stderr=stderr,
        text=True,
    )
    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        if docker_container_name is not None:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", docker_container_name],
                    stdout=stderr,
                    stderr=stderr,
                    text=True,
                    check=False,
                    timeout=20,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            process.kill()
        except OSError:
            pass
        process.wait()
        raise TimeoutError(
            f"WHAM run exceeded the {timeout_seconds:.0f}s timeout. "
            f"Logs may contain partial output for command: {' '.join(command)}"
        ) from exc


def path_inside_worker_mount(path: Path, *, mount_root: Path) -> str:
    resolved_path = path.expanduser().resolve()
    resolved_root = mount_root.expanduser().resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Path is outside the warm WHAM worker mount root: {resolved_path} not under {resolved_root}") from exc
    return "/workspace" if str(relative) == "." else "/workspace/" + relative.as_posix()


def assert_warm_worker_heartbeat(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"Warm WHAM worker heartbeat is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated_at = float(payload.get("updatedAtUnixSeconds") or 0.0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Warm WHAM worker heartbeat is unreadable: {path}") from exc
    heartbeat_age = max(0.0, time.time() - updated_at)
    if heartbeat_age > WHAM_WARM_WORKER_HEARTBEAT_STALE_SECONDS:
        raise RuntimeError(
            "Warm WHAM worker heartbeat became stale "
            f"({heartbeat_age:.1f}s old): {path}"
        )


def assert_warm_worker_available(session_dir: Path, *, label: str = "WHAM") -> None:
    """Reject stale readiness after admission locks have been acquired."""
    if any((session_dir / name).exists() for name in ("stop", "stopped.json")):
        raise RuntimeError(f"Warm {label} worker is stopping: {session_dir}")
    ready_path = session_dir / "ready.json"
    if not ready_path.is_file():
        raise RuntimeError(f"Warm {label} worker is not ready: {ready_path}")
    assert_warm_worker_heartbeat(session_dir / "heartbeat.json")


def wait_for_warm_worker_result(
    path: Path,
    *,
    timeout_seconds: float | None,
    candidate_deadline: float | None = None,
    heartbeat_path: Path | None = None,
    stopped_path: Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    deadlines: list[float] = []
    if timeout_seconds is not None:
        deadlines.append(started + max(0.0, float(timeout_seconds)))
    if candidate_deadline is not None:
        deadlines.append(float(candidate_deadline))
    deadline = min(deadlines) if deadlines else None
    deadline_clock = time.perf_counter()
    deadline_wall_time = (
        time.time() + (deadline - deadline_clock)
        if deadline is not None
        else None
    )
    shutdown_requested = False
    shutdown_reason: BaseException | None = None
    stop_path = stopped_path.parent / "stop" if stopped_path is not None else None

    def result_was_published_before_deadline() -> bool:
        if deadline_wall_time is None:
            return True
        try:
            return path.stat().st_mtime <= deadline_wall_time
        except OSError:
            return time.perf_counter() < deadline

    def timeout_error() -> TimeoutError:
        return TimeoutError(
            f"Timed out waiting for warm WHAM worker result: {path}; "
            "waiting for terminal worker shutdown before releasing GPU ownership"
        )

    def archive_unclaimed_request() -> None:
        queued_path = path.parent.parent / "jobs" / path.name
        if not queued_path.is_file():
            return
        cancelled_dir = path.parent.parent / "cancelled_runs"
        cancelled_dir.mkdir(parents=True, exist_ok=True)
        cancelled_path = cancelled_dir / path.name
        if cancelled_path.exists():
            cancelled_path = cancelled_dir / f"{path.stem}-{time.time_ns()}{path.suffix}"
        try:
            # Atomic rename arbitrates with the worker's jobs -> running claim.
            # If this wins, restart recovery cannot replay an expired request.
            os.replace(queued_path, cancelled_path)
        except FileNotFoundError:
            pass

    def request_worker_shutdown(reason: BaseException) -> None:
        nonlocal shutdown_requested, shutdown_reason
        shutdown_requested = True
        shutdown_reason = reason
        if stop_path is not None:
            try:
                archive_unclaimed_request()
            except OSError:
                # If claim/cancellation state cannot be read or moved, keep
                # the worker leased and request its normal between-job stop.
                pass
            try:
                stop_path.write_text(
                    "caller is waiting for terminal worker shutdown\n",
                    encoding="utf-8",
                )
            except OSError:
                # Keep the leases held until the worker itself confirms stop.
                pass

    while True:
        if path.exists() and not shutdown_requested:
            if result_was_published_before_deadline():
                return json.loads(path.read_text(encoding="utf-8"))
            late_result_error = timeout_error()
            if stopped_path is None:
                raise late_result_error
            request_worker_shutdown(late_result_error)
        if stopped_path is not None and stopped_path.exists():
            if shutdown_reason is not None:
                raise shutdown_reason
            raise RuntimeError(
                "Warm WHAM worker stopped before producing the requested result: "
                f"{path}"
            )
        if not shutdown_requested and heartbeat_path is not None:
            try:
                assert_warm_worker_heartbeat(heartbeat_path)
            except RuntimeError as exc:
                if stopped_path is None:
                    raise
                request_worker_shutdown(exc)
        if not shutdown_requested and deadline is not None and time.perf_counter() >= deadline:
            expired_error = timeout_error()
            if stopped_path is None:
                raise expired_error
            request_worker_shutdown(expired_error)
        sleep_seconds = 0.5
        if not shutdown_requested and deadline is not None:
            sleep_seconds = min(sleep_seconds, max(0.0, deadline - time.perf_counter()))
        time.sleep(sleep_seconds)


def copy_worker_log(source: Path, destination: Path) -> None:
    if source.exists():
        destination.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    else:
        destination.write_text("", encoding="utf-8")


@contextmanager
def wham_docker_run_lock(*, enabled: bool, deadline: float | None = None):
    if not enabled:
        yield 0.0
        return

    if deadline is None:
        from exercise_motion_pkg.motion_scheduler import current_gpu_stage_deadline

        deadline = current_gpu_stage_deadline()

    lock_path = wham_docker_lock_path()
    timeout_seconds = wham_docker_lock_timeout_seconds()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    lock_handle: int | None = None
    while True:
        if deadline is not None and time.perf_counter() >= deadline:
            raise TimeoutError(f"Candidate deadline expired waiting for WHAM Docker lock: {lock_path}")
        guard_timeout = timeout_seconds
        if deadline is not None:
            guard_timeout = min(
                guard_timeout,
                max(0.0, deadline - time.perf_counter()),
            )
        try:
            with lock_lease_acquisition_guard(
                lock_path,
                stage="wham_docker_lock_admission",
                timeout_seconds=guard_timeout,
            ):
                try:
                    lock_handle = open_lock_lease(lock_path)
                    payload = {
                        "pid": os.getpid(),
                        "processIdentity": process_identity(os.getpid()),
                        "createdAt": time.time(),
                    }
                    os.write(lock_handle, json.dumps(payload).encode("utf-8"))
                    break
                except OSError as error:
                    if lock_handle is not None:
                        close_lock_lease(lock_handle, lock_path)
                        lock_handle = None
                        raise
                    if not lock_open_is_contention(error):
                        raise
                    if wham_docker_lock_is_stale(lock_path, timeout_seconds=timeout_seconds):
                        try:
                            lock_path.unlink()
                            continue
                        except OSError:
                            pass
        except TimeoutError as error:
            if deadline is not None and time.perf_counter() >= deadline:
                raise TimeoutError(
                    f"Candidate deadline expired waiting for WHAM Docker lock: {lock_path}"
                ) from error
            raise TimeoutError(f"Timed out waiting for WHAM Docker lock: {lock_path}") from error
        except BaseException:
            if lock_handle is not None:
                close_lock_lease(lock_handle, lock_path)
                lock_handle = None
            raise
        if lock_handle is not None:
            break
        elapsed = time.perf_counter() - started
        effective_timeout = timeout_seconds
        if deadline is not None:
            effective_timeout = min(effective_timeout, max(0.0, deadline - started))
        if elapsed >= effective_timeout:
            raise TimeoutError(f"Timed out waiting for WHAM Docker lock: {lock_path}")
        sleep_seconds = min(2.0, effective_timeout - elapsed)
        time.sleep(max(0.01, sleep_seconds))
    try:
        yield time.perf_counter() - started
    finally:
        if lock_handle is not None:
            close_lock_lease(lock_handle, lock_path)


def wham_docker_lock_path() -> Path:
    configured = os.environ.get(WHAM_DOCKER_LOCK_ENV_VAR)
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / "myworkoutassistant-wham-docker.lock"


def wham_docker_lock_timeout_seconds() -> float:
    raw = os.environ.get(WHAM_DOCKER_LOCK_TIMEOUT_SECONDS_ENV_VAR)
    if raw is None:
        return float(DEFAULT_WHAM_DOCKER_LOCK_TIMEOUT_SECONDS)
    try:
        return max(1.0, float(raw))
    except ValueError:
        return float(DEFAULT_WHAM_DOCKER_LOCK_TIMEOUT_SECONDS)


def wham_docker_lock_is_stale(lock_path: Path, *, timeout_seconds: float) -> bool:
    try:
        payload = json.loads(read_lock_text(lock_path))
    except (OSError, json.JSONDecodeError):
        # Unknown ownership cannot be safely revoked based on age alone.
        return False
    pid = payload.get("pid") if isinstance(payload, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        return False
    if not process_is_running(pid):
        return True
    expected_identity = payload.get("processIdentity")
    if isinstance(expected_identity, int):
        active_identity = process_identity(pid)
        if active_identity is not None and active_identity != expected_identity:
            return True
    # A live or unqueryable owner is never evicted by age. The timeout bounds
    # waiters; it does not take ownership away from active work.
    return False


def lock_age_seconds(lock_path: Path) -> float:
    try:
        return max(0.0, time.time() - lock_path.stat().st_mtime)
    except OSError:
        return 0.0


def process_is_running(pid: int) -> bool:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return True
        output = result.stdout.lower()
        return str(pid) in output and "no tasks are running" not in output
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def build_wham_command(
    *,
    wham_repo_path: Path,
    input_video: Path,
    output_root: Path,
    python_command: str,
    estimate_local_only: bool,
    run_smplify: bool,
    use_docker: bool = False,
    docker_image: str = DEFAULT_WHAM_DOCKER_IMAGE,
    docker_gpus: str = "all",
    docker_shm_size: str = DEFAULT_WHAM_DOCKER_SHM_SIZE,
    docker_container_name: str | None = None,
) -> list[str]:
    if use_docker:
        command = ["docker", "run", "--rm"]
        if docker_container_name:
            command.extend(["--name", docker_container_name])
        if docker_gpus:
            command.extend(["--gpus", docker_gpus])
        if docker_shm_size:
            command.extend(["--shm-size", docker_shm_size])
        for name, value in wham_preprocessing_environment().items():
            command.extend(["-e", f"{name}={value}"])
        command.extend(
            [
                "-v",
                f"{input_video.parent.resolve()}:/input",
                "-v",
                f"{output_root.resolve()}:/output",
                "-w",
                WHAM_DOCKER_SOURCE_ROOT,
                docker_image,
                "python",
                "-u",
                "demo.py",
                "--video",
                f"/input/{input_video.name}",
                "--output_pth",
                "/output",
                "--save_pkl",
            ]
        )
        if estimate_local_only:
            command.append("--estimate_local_only")
        if run_smplify:
            command.append("--run_smplify")
        return command

    del wham_repo_path, docker_image, docker_gpus, docker_shm_size
    command = [
        python_command,
        "demo.py",
        "--video",
        str(input_video.resolve()),
        "--output_pth",
        str(output_root.resolve()),
        "--save_pkl",
    ]
    if estimate_local_only:
        command.append("--estimate_local_only")
    if run_smplify:
        command.append("--run_smplify")
    return command


def build_wham_tracking_preflight_command(
    *,
    wham_repo_path: Path,
    script_path: Path,
    input_video: Path,
    output_root: Path,
    report_path: Path,
    python_command: str,
    required_start_seconds: float | None,
    required_end_seconds: float | None,
    use_docker: bool,
    docker_image: str,
    docker_gpus: str,
    docker_shm_size: str,
    docker_container_name: str | None = None,
) -> list[str]:
    if use_docker:
        command = ["docker", "run", "--rm"]
        if docker_container_name:
            command.extend(["--name", docker_container_name])
        if docker_gpus:
            command.extend(["--gpus", docker_gpus])
        if docker_shm_size:
            command.extend(["--shm-size", docker_shm_size])
        for name, value in wham_preprocessing_environment().items():
            command.extend(["-e", f"{name}={value}"])
        command.extend(
            [
                "-v",
                f"{script_path.parent.resolve()}:/mwa",
                "-v",
                f"{input_video.parent.resolve()}:/input",
                "-v",
                f"{output_root.resolve()}:/output",
                "-v",
                f"{report_path.parent.resolve()}:/logs",
                "-w",
                WHAM_DOCKER_SOURCE_ROOT,
                docker_image,
                "python",
                "-u",
                f"/mwa/{script_path.name}",
                "--video",
                f"/input/{input_video.name}",
                "--output-pth",
                "/output",
                "--report",
                f"/logs/{report_path.name}",
            ]
        )
    else:
        command = [
            python_command,
            str(script_path),
            "--video",
            str(input_video.resolve()),
            "--output-pth",
            str(output_root.resolve()),
            "--report",
            str(report_path.resolve()),
        ]
    if required_start_seconds is not None:
        command.extend(["--required-start-seconds", f"{required_start_seconds:.6f}"])
    if required_end_seconds is not None:
        command.extend(["--required-end-seconds", f"{required_end_seconds:.6f}"])
    return command


def validate_wham_repo_layout(
    wham_repo_path: Path,
    *,
    estimate_local_only: bool,
    use_docker: bool = False,
) -> None:
    if use_docker:
        return
    required_paths = [
        wham_repo_path / "demo.py",
        wham_repo_path / "requirements.txt",
        wham_repo_path / "checkpoints" / WHAM_DEMO_CHECKPOINT_NAME,
        wham_repo_path / "checkpoints" / WHAM_EVAL_CHECKPOINT_NAME,
        wham_repo_path / "checkpoints" / "hmr2a.ckpt",
        wham_repo_path / "checkpoints" / "vitpose-h-multi-coco.pth",
        wham_repo_path / "checkpoints" / "yolo26x.pt",
        wham_repo_path / "dataset" / "body_models" / "smpl" / "SMPL_NEUTRAL.pkl",
    ]
    if not estimate_local_only:
        required_paths.append(wham_repo_path / "checkpoints" / "dpvo.pth")
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        formatted = "\n".join(str(path) for path in missing)
        raise RuntimeError(f"WHAM repo is missing required files:\n{formatted}")
