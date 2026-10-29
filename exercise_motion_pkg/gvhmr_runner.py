"""GVHMR reconstruction runner (Docker).

Runs the GVHMR demo inside Docker and exports SMPL reconstruction results for
the shared normalization and retargeting pipeline.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from exercise_motion_pkg.gpu_lock import (
    exclusive_gpu_device,
    gpu_device_uuid,
    gpu_stage_lock,
    resolve_docker_gpu_selection,
)
from exercise_motion_pkg.motion_scheduler import gpu_stage_task, timeout_with_candidate_deadline
from exercise_motion_pkg.reconstruction_runner import (
    assert_warm_worker_available,
    copy_worker_log,
    ensure_warm_worker_ready,
    path_inside_worker_mount,
    run_reconstruction_process,
    wait_for_warm_worker_result,
    reconstruction_docker_run_lock,
)


DEFAULT_GVHMR_DOCKER_IMAGE = "myworkoutassistant/gvhmr:torch2.3-cu121"
DEFAULT_GVHMR_DOCKER_SHM_SIZE = "8g"
GVHMR_DOCKER_SOURCE_ROOT = "/opt/gvhmr"
DEFAULT_GVHMR_TIMEOUT_SECONDS = 20 * 60.0
DEFAULT_GVHMR_WARM_WORKER_TIMEOUT_SECONDS = DEFAULT_GVHMR_TIMEOUT_SECONDS
GVHMR_WARM_WORKER_SESSION_DIR_ENV_VAR = "EXERCISE_MOTION_GVHMR_WARM_WORKER_SESSION_DIR"
GVHMR_WARM_WORKER_MOUNT_ROOT_ENV_VAR = "EXERCISE_MOTION_GVHMR_WARM_WORKER_MOUNT_ROOT"
GVHMR_WARM_WORKER_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_GVHMR_WARM_WORKER_TIMEOUT_SECONDS"
GVHMR_WARM_WORKER_LAZY_START_ENV_VAR = "EXERCISE_MOTION_GVHMR_LAZY_START"


class GvhmrWarmWorkerInterruptedAmbiguous(RuntimeError):
    """A claimed GVHMR warm-worker request stopped without trustworthy completion."""

    failure_code = "gvhmr_worker_interrupted_ambiguous"
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
            f"GVHMR warm-worker job {job_id} was interrupted after claim and was not replayed: {detail}"
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


@dataclass(frozen=True)
class GvhmrRunResult:
    output_dir: Path
    results_pkl: Path
    demo_output_dir: Path
    stdout_log: Path
    stderr_log: Path
    command: list[str]
    elapsed_seconds: float
    returncode: int
    docker_image: str
    gpu_lock_wait_seconds: float
    docker_lock_wait_seconds: float
    phase_timings: dict[str, dict[str, float]]
    unattributed_runner_seconds: float
    timeout_seconds: float | None
    warm_worker: bool = False
    warm_worker_job_id: str | None = None
    warm_worker_session_dir: Path | None = None
    stage_identity: dict[str, Any] | None = None

    def timing_payload(self) -> dict[str, Any]:
        return {
            "elapsedSeconds": round(self.elapsed_seconds, 3),
            "returncode": self.returncode,
            "useDocker": True,
            "backend": "gvhmr",
            "dockerImage": self.docker_image,
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
            "demoOutputDir": str(self.demo_output_dir),
            "dockerLockWaitSeconds": round(self.docker_lock_wait_seconds, 3),
            "gpuLockWaitSeconds": round(self.gpu_lock_wait_seconds, 3),
            "phaseTimings": self.phase_timings,
            "unattributedRunnerSeconds": round(self.unattributed_runner_seconds, 3),
        }


@dataclass(frozen=True)
class GvhmrPreprocessResult:
    preprocess_manifest: Path
    output_root: Path
    elapsed_seconds: float
    timings: dict[str, float]
    worker_session_dir: Path
    gpu_lock_wait_seconds: float

    def timing_payload(self) -> dict[str, Any]:
        return {
            "stage": "preprocess",
            "elapsedSeconds": round(self.elapsed_seconds, 3),
            "timings": self.timings,
            "preprocessManifest": str(self.preprocess_manifest),
            "workerSessionDir": str(self.worker_session_dir),
            "gpuLockWaitSeconds": round(self.gpu_lock_wait_seconds, 3),
        }


def _read_phase_timing_markers(log_path: Path) -> dict[str, dict[str, float]]:
    markers = {
        "GVHMR_PHASE_TIMINGS_JSON:": "inference",
        "GVHMR_EXPORT_TIMINGS_JSON:": "export",
    }
    timings: dict[str, dict[str, float]] = {}
    if not log_path.is_file():
        return timings
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        for prefix, phase_name in markers.items():
            if not line.startswith(prefix):
                continue
            try:
                payload = json.loads(line[len(prefix):])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            numeric = {
                str(key): float(value)
                for key, value in payload.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
            if numeric:
                timings[phase_name] = numeric
            break
    return timings


def resolve_gvhmr_warm_worker_session_dir(configured: Path | None) -> Path:
    if configured is not None:
        return configured.expanduser().resolve()
    raw = os.environ.get(GVHMR_WARM_WORKER_SESSION_DIR_ENV_VAR)
    if raw:
        return Path(raw).expanduser().resolve()
    raise ValueError(
        "Warm GVHMR worker mode requires a session directory. "
        f"Pass --gvhmr-worker-session-dir or set {GVHMR_WARM_WORKER_SESSION_DIR_ENV_VAR}."
    )


def resolve_gvhmr_warm_worker_mount_root(configured: Path | None) -> Path:
    if configured is not None:
        return configured.expanduser().resolve()
    raw = os.environ.get(GVHMR_WARM_WORKER_MOUNT_ROOT_ENV_VAR)
    if raw:
        return Path(raw).expanduser().resolve()
    raise ValueError(
        "Warm GVHMR worker mode requires the host mount root. "
        f"Pass --gvhmr-worker-mount-root or set {GVHMR_WARM_WORKER_MOUNT_ROOT_ENV_VAR}."
    )


def resolve_gvhmr_warm_worker_timeout_seconds(configured: float | None) -> float | None:
    if configured is not None:
        return None if float(configured) <= 0.0 else max(1.0, float(configured))
    raw = os.environ.get(GVHMR_WARM_WORKER_TIMEOUT_SECONDS_ENV_VAR)
    if raw is not None:
        try:
            value = float(raw)
            return None if value <= 0.0 else max(1.0, value)
        except ValueError:
            pass
    return (
        None
        if DEFAULT_GVHMR_WARM_WORKER_TIMEOUT_SECONDS <= 0.0
        else float(DEFAULT_GVHMR_WARM_WORKER_TIMEOUT_SECONDS)
    )


def _docker_image_identity(docker_image: str) -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format={{.Id}}", docker_image],
        capture_output=True, text=True, timeout=15.0, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"Could not resolve immutable GVHMR Docker image identity for {docker_image!r}.")
    return result.stdout.strip()


def _run_gvhmr_stage_worker(
    *, input_video: Path, output_root: Path, logs_dir: Path, docker_image: str,
    static_camera: bool, warm_worker_session_dir: Path | None,
    warm_worker_mount_root: Path | None, warm_worker_timeout_seconds: float | None,
    stage_identity: dict[str, Any] | None, candidate_deadline: float | None,
    stage_mode: str, gpu_device: str, shared_llama_session_dir: Path | None = None,
) -> tuple[dict[str, Any], str, Path, float, float]:
    session_dir = resolve_gvhmr_warm_worker_session_dir(warm_worker_session_dir)
    mount_root = resolve_gvhmr_warm_worker_mount_root(warm_worker_mount_root)
    worker_timeout = resolve_gvhmr_warm_worker_timeout_seconds(warm_worker_timeout_seconds)
    timeout = timeout_with_candidate_deadline(
        worker_timeout, candidate_deadline, stage_name=f"GVHMR {stage_mode} stage",
    )
    jobs_dir, results_dir, job_logs_dir = (session_dir / name for name in ("jobs", "results", "job_logs"))
    for path in (jobs_dir, results_dir, job_logs_dir):
        path.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    job_payload = {
        "jobId": job_id,
        "video": path_inside_worker_mount(input_video, mount_root=mount_root),
        "outputRoot": path_inside_worker_mount(output_root, mount_root=mount_root),
        "staticCam": static_camera,
        "keepSourceBetas": False,
        "stageIdentity": stage_identity,
        "imageIdentity": _docker_image_identity(docker_image),
    }
    job_path = jobs_dir / f"{job_id}.json"
    tmp_job_path = jobs_dir / f"{job_id}.json.tmp"
    result_path = results_dir / f"{job_id}.json"
    started = time.perf_counter()
    gpu_lock_wait = 0.0

    def submit() -> dict[str, Any]:
        ensure_warm_worker_ready(
            session_dir,
            timeout_seconds=worker_timeout if worker_timeout is not None else DEFAULT_GVHMR_WARM_WORKER_TIMEOUT_SECONDS,
            lazy_start_env_var=GVHMR_WARM_WORKER_LAZY_START_ENV_VAR,
            label=f"GVHMR {stage_mode}",
        )
        assert_warm_worker_available(session_dir, label=f"GVHMR {stage_mode}")
        try:
            ready = json.loads((session_dir / "ready.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"GVHMR {stage_mode} worker readiness record is invalid") from exc
        if (
            ready.get("stageMode") != stage_mode
            or str(ready.get("gpuDevice")) != str(gpu_device)
            or ready.get("imageIdentity") != job_payload["imageIdentity"]
        ):
            raise RuntimeError(
                f"GVHMR worker role mismatch: expected {stage_mode} on GPU {gpu_device}, "
                f"got {ready.get('stageMode')} on GPU {ready.get('gpuDevice')} "
                f"with image {ready.get('imageIdentity')}"
            )
        tmp_job_path.write_text(json.dumps(job_payload, indent=2), encoding="utf-8")
        tmp_job_path.replace(job_path)
        return wait_for_warm_worker_result(
            result_path, timeout_seconds=timeout,
            candidate_deadline=candidate_deadline,
            heartbeat_path=session_dir / "heartbeat.json",
            stopped_path=session_dir / "stopped.json",
        )

    with gpu_stage_lock(stage=f"gvhmr_{stage_mode}", device=gpu_device) as gpu_lock_wait_seconds:
        if shared_llama_session_dir is not None:
            from exercise_motion_pkg.shared_llama_server import resident_gpu_compute_scope

            with resident_gpu_compute_scope(
                shared_llama_session_dir,
            ):
                result_payload = submit()
        else:
            result_payload = submit()
    gpu_lock_wait = gpu_lock_wait_seconds
    elapsed = time.perf_counter() - started
    copy_worker_log(job_logs_dir / f"{job_id}.stdout.log", logs_dir / f"gvhmr_{stage_mode}.stdout.log")
    copy_worker_log(job_logs_dir / f"{job_id}.stderr.log", logs_dir / f"gvhmr_{stage_mode}.stderr.log")
    if str(result_payload.get("jobId") or "") != job_id:
        raise RuntimeError("Warm GVHMR worker result job ID does not match the submitted request.")
    if result_payload.get("stageIdentity") != stage_identity:
        raise RuntimeError("Warm GVHMR worker result stage identity does not match the submitted candidate.")
    if result_payload.get("status") != "completed":
        error = result_payload.get("error") or "unknown warm worker failure"
        raise RuntimeError(f"GVHMR {stage_mode} stage failed: {error}")
    return result_payload, job_id, session_dir, elapsed, gpu_lock_wait


def run_gvhmr_preprocess_stage(
    *, input_video: Path, output_root: Path, logs_dir: Path, docker_image: str,
    static_camera: bool, warm_worker_session_dir: Path | None,
    warm_worker_mount_root: Path | None, warm_worker_timeout_seconds: float | None,
    stage_identity: dict[str, Any] | None = None,
    candidate_deadline: float | None = None, gpu_device: str = "1",
) -> GvhmrPreprocessResult:
    logs_dir.mkdir(parents=True, exist_ok=True)
    worker_session = resolve_gvhmr_warm_worker_session_dir(warm_worker_session_dir) / "preprocess"
    payload, _, session_dir, elapsed, gpu_lock_wait = _run_gvhmr_stage_worker(
        input_video=input_video, output_root=output_root, logs_dir=logs_dir,
        docker_image=docker_image, static_camera=static_camera,
        warm_worker_session_dir=worker_session,
        warm_worker_mount_root=warm_worker_mount_root,
        warm_worker_timeout_seconds=warm_worker_timeout_seconds,
        stage_identity=stage_identity, candidate_deadline=candidate_deadline,
        stage_mode="preprocess", gpu_device=gpu_device,
    )
    manifest = output_root / "demo" / input_video.stem / "preprocess_manifest.json"
    expected_container_manifest = path_inside_worker_mount(
        manifest, mount_root=resolve_gvhmr_warm_worker_mount_root(warm_worker_mount_root),
    )
    if not manifest.is_file() or payload.get("preprocessManifest") != expected_container_manifest:
        raise RuntimeError(f"GVHMR preprocessing completed without its expected manifest: {manifest}")
    return GvhmrPreprocessResult(
        preprocess_manifest=manifest, output_root=output_root,
        elapsed_seconds=elapsed,
        timings={str(k): float(v) for k, v in (payload.get("timings") or {}).items()
                 if isinstance(v, (int, float)) and not isinstance(v, bool)},
        worker_session_dir=session_dir,
        gpu_lock_wait_seconds=gpu_lock_wait,
    )


def run_gvhmr_prediction_stage(
    *, input_video: Path, output_root: Path, logs_dir: Path, docker_image: str,
    static_camera: bool, warm_worker_session_dir: Path | None,
    warm_worker_mount_root: Path | None, warm_worker_timeout_seconds: float | None,
    preprocess_manifest: Path, shared_llama_session_dir: Path | None,
    stage_identity: dict[str, Any] | None = None,
    candidate_deadline: float | None = None, gpu_device: str = "0",
) -> GvhmrRunResult:
    if shared_llama_session_dir is None:
        raise ValueError("Split GVHMR prediction requires the shared llama session for GPU admission")
    expected_manifest = output_root / "demo" / input_video.stem / "preprocess_manifest.json"
    if Path(preprocess_manifest).expanduser().resolve() != expected_manifest.expanduser().resolve():
        raise ValueError("GVHMR prediction handoff is not the manifest for this output/video pair")
    if not expected_manifest.is_file():
        raise FileNotFoundError(f"GVHMR preprocessing handoff is missing: {expected_manifest}")
    logs_dir.mkdir(parents=True, exist_ok=True)
    worker_session = resolve_gvhmr_warm_worker_session_dir(warm_worker_session_dir) / "predict"
    payload, job_id, session_dir, elapsed, gpu_lock_wait = _run_gvhmr_stage_worker(
        input_video=input_video, output_root=output_root, logs_dir=logs_dir,
        docker_image=docker_image, static_camera=static_camera,
        warm_worker_session_dir=worker_session,
        warm_worker_mount_root=warm_worker_mount_root,
        warm_worker_timeout_seconds=warm_worker_timeout_seconds,
        stage_identity=stage_identity, candidate_deadline=candidate_deadline,
        stage_mode="predict", gpu_device=gpu_device,
        shared_llama_session_dir=shared_llama_session_dir,
    )
    sequence_dir = output_root / input_video.stem
    results_pkl = sequence_dir / "reconstruction_output.pkl"
    if not results_pkl.is_file():
        raise RuntimeError(f"GVHMR prediction worker completed without writing {results_pkl}")
    timings = {
        str(k): float(v) for k, v in (payload.get("timings") or {}).items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    stdout_log, stderr_log = logs_dir / "gvhmr_predict.stdout.log", logs_dir / "gvhmr_predict.stderr.log"
    return GvhmrRunResult(
        output_dir=sequence_dir, results_pkl=results_pkl,
        demo_output_dir=output_root / "demo" / input_video.stem,
        stdout_log=stdout_log, stderr_log=stderr_log,
        command=["gvhmr-stage-worker", "predict", job_id],
        elapsed_seconds=elapsed, returncode=0, docker_image=docker_image,
        gpu_lock_wait_seconds=gpu_lock_wait, docker_lock_wait_seconds=0.0,
        phase_timings={"inference": timings}, unattributed_runner_seconds=0.0,
        timeout_seconds=resolve_gvhmr_warm_worker_timeout_seconds(warm_worker_timeout_seconds),
        warm_worker=True, warm_worker_job_id=job_id,
        warm_worker_session_dir=session_dir, stage_identity=stage_identity,
    )


@gpu_stage_task("gvhmr_warm_worker_reconstruction")
def run_gvhmr_with_warm_worker(
    *,
    input_video: Path,
    output_root: Path,
    logs_dir: Path,
    stdout_log: Path,
    stderr_log: Path,
    docker_image: str,
    static_camera: bool,
    warm_worker_session_dir: Path | None,
    warm_worker_mount_root: Path | None,
    warm_worker_timeout_seconds: float | None,
    stage_identity: dict[str, Any] | None = None,
    candidate_deadline: float | None = None,
) -> GvhmrRunResult:
    session_dir = resolve_gvhmr_warm_worker_session_dir(warm_worker_session_dir)
    mount_root = resolve_gvhmr_warm_worker_mount_root(warm_worker_mount_root)
    worker_timeout = resolve_gvhmr_warm_worker_timeout_seconds(warm_worker_timeout_seconds)
    timeout = worker_timeout
    timeout = timeout_with_candidate_deadline(
        timeout,
        candidate_deadline,
        stage_name="GVHMR warm-worker reconstruction",
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
        "staticCam": static_camera,
        "keepSourceBetas": False,
        "stageIdentity": stage_identity,
    }
    job_path = jobs_dir / f"{job_id}.json"
    tmp_job_path = jobs_dir / f"{job_id}.json.tmp"
    result_path = results_dir / f"{job_id}.json"
    started = time.perf_counter()
    lock_wait_seconds = 0.0
    gpu_lock_wait_seconds = 0.0
    with gpu_stage_lock(stage="gvhmr_warm_worker_job", device=exclusive_gpu_device()) as gpu_lock_wait_seconds:
        with reconstruction_docker_run_lock(enabled=True) as lock_wait_seconds:
            # Model loading during lazy startup uses CUDA too. Keep GPU and
            # Docker admission through startup, then verify readiness again
            # immediately before publishing a request.
            ensure_warm_worker_ready(
                session_dir,
                timeout_seconds=(
                    worker_timeout
                    if worker_timeout is not None
                    else DEFAULT_GVHMR_WARM_WORKER_TIMEOUT_SECONDS
                ),
                lazy_start_env_var=GVHMR_WARM_WORKER_LAZY_START_ENV_VAR,
                label="GVHMR",
            )
            timeout = timeout_with_candidate_deadline(
                worker_timeout,
                candidate_deadline,
                stage_name="GVHMR warm-worker reconstruction",
            )
            assert_warm_worker_available(session_dir, label="GVHMR")
            timeout = timeout_with_candidate_deadline(
                timeout,
                candidate_deadline,
                stage_name="GVHMR warm-worker request",
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
            "Warm GVHMR worker result job ID does not match the submitted request."
        )
    if result_payload.get("status") == GvhmrWarmWorkerInterruptedAmbiguous.status:
        raise GvhmrWarmWorkerInterruptedAmbiguous(
            job_id=job_id,
            session_dir=session_dir,
            result_path=result_path,
            result_payload=result_payload,
            expected_stage_identity=stage_identity,
        )
    if result_payload.get("stageIdentity") != stage_identity:
        raise RuntimeError(
            "Warm GVHMR worker result stage identity does not match the submitted candidate."
        )
    if result_payload.get("status") != "completed":
        error = result_payload.get("error") or "unknown warm worker failure"
        raise RuntimeError(
            "Warm GVHMR worker run failed. Check logs:\n"
            f"- {stdout_log}\n"
            f"- {stderr_log}\n"
            f"Error: {error}"
        )
    sequence_dir = output_root / input_video.stem
    results_pkl = sequence_dir / "reconstruction_output.pkl"
    if not results_pkl.exists():
        raise RuntimeError(
            "Warm GVHMR worker completed but no reconstruction_output.pkl was found.\n"
            f"Expected: {results_pkl}\n"
            f"Worker result: {result_path}\n"
            f"Logs:\n- {stdout_log}\n- {stderr_log}"
        )
    job_timings = {
        str(key): float(value)
        for key, value in (result_payload.get("timings") or {}).items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    phase_timings = {"inference": job_timings} if job_timings else {}
    worker_elapsed = float(result_payload.get("elapsedSeconds") or 0.0)
    unattributed_runner_seconds = elapsed - worker_elapsed - gpu_lock_wait_seconds - lock_wait_seconds
    return GvhmrRunResult(
        output_dir=sequence_dir,
        results_pkl=results_pkl,
        demo_output_dir=output_root / "demo" / input_video.stem,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        command=["gvhmr-warm-worker", job_id],
        elapsed_seconds=elapsed,
        returncode=0,
        docker_image=docker_image,
        gpu_lock_wait_seconds=gpu_lock_wait_seconds,
        docker_lock_wait_seconds=lock_wait_seconds,
        phase_timings=phase_timings,
        unattributed_runner_seconds=max(0.0, unattributed_runner_seconds),
        timeout_seconds=timeout,
        warm_worker=True,
        warm_worker_job_id=job_id,
        warm_worker_session_dir=session_dir,
        stage_identity=stage_identity,
    )


def build_gvhmr_command(
    *,
    input_video: Path,
    output_root: Path,
    export_script: Path,
    docker_image: str,
    docker_gpus: str,
    docker_shm_size: str,
    docker_container_name: str | None,
    static_camera: bool,
) -> list[str]:
    # demo.py writes to <output_root>/<video-stem>/hmr4d_results.pt; the export
    # step converts it to the RECONSTRUCTION-schema pkl the pipeline expects at
    # <output_root>/<video-stem>/reconstruction_output.pkl.
    container_stem = input_video.stem
    demo_results = f"/output/demo/{container_stem}/hmr4d_results.pt"
    output_pkl = f"/output/{container_stem}/reconstruction_output.pkl"
    bridge_script = export_script.with_name("gvhmr_inference.py")
    demo_command = [
        "python",
        f"/mwa/{bridge_script.name}",
        "--video",
        f"/input/{input_video.name}",
        "--output_root",
        "/output/demo",
    ]
    if static_camera:
        demo_command.append("-s")
    inner_script = (
        f"{' '.join(demo_command)} && "
        f"python /mwa/gvhmr_pkl_export.py --results {demo_results} --output-pkl {output_pkl}"
    )
    command = ["docker", "run", "--rm"]
    if docker_container_name:
        command.extend(["--name", docker_container_name])
    if docker_gpus:
        command.extend(["--gpus", resolve_docker_gpu_selection(docker_gpus)])
    exclusive_device = exclusive_gpu_device()
    if exclusive_device is not None:
        gpu_uuid = gpu_device_uuid(exclusive_device)
        if gpu_uuid is None:
            raise RuntimeError(f"Could not resolve physical GPU UUID for exclusive GPU {exclusive_device}.")
        command.extend(["--env", f"CUDA_VISIBLE_DEVICES={gpu_uuid}"])
    if docker_shm_size:
        command.extend(["--shm-size", docker_shm_size])
    command.extend(
        [
            "-v",
            f"{input_video.parent.resolve()}:/input",
            "-v",
            f"{output_root.resolve()}:/output",
            "-v",
            f"{bridge_script.parent.resolve()}:/mwa",
            "-w",
            GVHMR_DOCKER_SOURCE_ROOT,
            docker_image,
            "bash",
            "-lc",
            inner_script,
        ]
    )
    return command


@gpu_stage_task("gvhmr_reconstruction")
def _run_gvhmr_locally_queued(
    *,
    input_video: Path,
    output_root: Path,
    logs_dir: Path,
    docker_image: str = DEFAULT_GVHMR_DOCKER_IMAGE,
    docker_gpus: str = "all",
    docker_shm_size: str = DEFAULT_GVHMR_DOCKER_SHM_SIZE,
    static_camera: bool = True,
    timeout_seconds: float | None = None,
    use_warm_worker: bool = False,
    warm_worker_session_dir: Path | None = None,
    warm_worker_mount_root: Path | None = None,
    warm_worker_timeout_seconds: float | None = None,
    stage_identity: dict[str, Any] | None = None,
    candidate_deadline: float | None = None,
) -> GvhmrRunResult:
    """Run GVHMR in Docker and return a RECONSTRUCTION-schema results pkl path."""
    timeout = (
        DEFAULT_GVHMR_TIMEOUT_SECONDS
        if timeout_seconds is None or float(timeout_seconds) <= 0.0
        else max(1.0, float(timeout_seconds))
    )
    timeout = timeout_with_candidate_deadline(
        timeout,
        candidate_deadline,
        stage_name="GVHMR reconstruction",
    )
    output_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = logs_dir / "gvhmr.stdout.log"
    stderr_log = logs_dir / "gvhmr.stderr.log"
    if use_warm_worker:
        return run_gvhmr_with_warm_worker(
            input_video=input_video,
            output_root=output_root,
            logs_dir=logs_dir,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            docker_image=docker_image,
            static_camera=static_camera,
            warm_worker_session_dir=warm_worker_session_dir,
            warm_worker_mount_root=warm_worker_mount_root,
            warm_worker_timeout_seconds=(
                warm_worker_timeout_seconds
                if warm_worker_timeout_seconds is not None
                else timeout
            ),
            stage_identity=stage_identity,
            candidate_deadline=candidate_deadline,
        )
    docker_container_name = f"mwa-gvhmr-job-{uuid.uuid4().hex}"
    command = build_gvhmr_command(
        input_video=input_video,
        output_root=output_root,
        export_script=Path(__file__).with_name("gvhmr_pkl_export.py"),
        docker_image=docker_image,
        docker_gpus=docker_gpus,
        docker_shm_size=docker_shm_size,
        docker_container_name=docker_container_name,
        static_camera=static_camera,
    )
    started = time.perf_counter()
    lock_wait_seconds = 0.0
    gpu_lock_wait_seconds = 0.0
    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        with gpu_stage_lock(stage="gvhmr", device=exclusive_gpu_device()) as gpu_lock_wait_seconds:
            with reconstruction_docker_run_lock(enabled=True) as lock_wait_seconds:
                returncode = run_reconstruction_process(
                    command,
                    cwd=str(Path(__file__).resolve().parent),
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    timeout_seconds=timeout_with_candidate_deadline(
                        timeout,
                        candidate_deadline,
                        stage_name="GVHMR reconstruction",
                    ),
                    docker_container_name=docker_container_name,
                )
    elapsed = time.perf_counter() - started
    if returncode != 0:
        raise RuntimeError(
            "GVHMR run failed. Check logs:\n"
            f"- {stdout_log}\n- {stderr_log}"
        )
    sequence_dir = output_root / input_video.stem
    results_pkl = sequence_dir / "reconstruction_output.pkl"
    if not results_pkl.exists():
        raise RuntimeError(
            "GVHMR run completed but no reconstruction_output.pkl was found.\n"
            f"Expected: {results_pkl}\nLogs:\n- {stdout_log}\n- {stderr_log}"
        )
    phase_timings = _read_phase_timing_markers(stdout_log)
    inference_total = phase_timings.get("inference", {}).get("scriptTotalSeconds", 0.0)
    export_total = phase_timings.get("export", {}).get("processTotalSeconds", 0.0)
    unattributed_runner_seconds = (
        elapsed - inference_total - export_total
        - gpu_lock_wait_seconds - lock_wait_seconds
    )
    return GvhmrRunResult(
        output_dir=sequence_dir,
        results_pkl=results_pkl,
        demo_output_dir=output_root / "demo" / input_video.stem,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        command=command,
        elapsed_seconds=elapsed,
        returncode=returncode,
        docker_image=docker_image,
        gpu_lock_wait_seconds=gpu_lock_wait_seconds,
        docker_lock_wait_seconds=lock_wait_seconds,
        phase_timings=phase_timings,
        unattributed_runner_seconds=unattributed_runner_seconds,
        timeout_seconds=timeout,
    )


def run_gvhmr_locally(
    *, stage_split: bool = False,
    shared_llama_session_dir: Path | None = None,
    **kwargs: Any,
) -> GvhmrRunResult:
    """Keep legacy scheduling while routing the verified split path per GPU."""
    if not stage_split:
        return _run_gvhmr_locally_queued(**kwargs)
    if not bool(kwargs.get("use_warm_worker")):
        raise ValueError("GVHMR stage splitting requires the supervised warm worker")
    preprocess_gpu = exclusive_gpu_device()
    if preprocess_gpu is None or preprocess_gpu == "0":
        raise ValueError("GVHMR stage splitting requires an explicitly configured nonzero preprocessing GPU")
    if shared_llama_session_dir is None:
        raise ValueError("GVHMR stage splitting requires the shared llama session for GPU admission")
    worker_timeout = kwargs.get("warm_worker_timeout_seconds")
    if worker_timeout is None:
        worker_timeout = kwargs.get("timeout_seconds")
    preprocess = run_gvhmr_preprocess_stage(
        input_video=kwargs["input_video"], output_root=kwargs["output_root"],
        logs_dir=kwargs["logs_dir"], docker_image=kwargs.get("docker_image", DEFAULT_GVHMR_DOCKER_IMAGE),
        static_camera=kwargs.get("static_camera", True),
        warm_worker_session_dir=kwargs.get("warm_worker_session_dir"),
        warm_worker_mount_root=kwargs.get("warm_worker_mount_root"),
        warm_worker_timeout_seconds=worker_timeout,
        stage_identity=kwargs.get("stage_identity"), candidate_deadline=kwargs.get("candidate_deadline"),
        gpu_device=preprocess_gpu,
    )
    prediction = run_gvhmr_prediction_stage(
        input_video=kwargs["input_video"], output_root=kwargs["output_root"],
        logs_dir=kwargs["logs_dir"], docker_image=kwargs.get("docker_image", DEFAULT_GVHMR_DOCKER_IMAGE),
        static_camera=kwargs.get("static_camera", True),
        warm_worker_session_dir=kwargs.get("warm_worker_session_dir"),
        warm_worker_mount_root=kwargs.get("warm_worker_mount_root"),
        warm_worker_timeout_seconds=worker_timeout,
        preprocess_manifest=preprocess.preprocess_manifest,
        shared_llama_session_dir=shared_llama_session_dir,
        stage_identity=kwargs.get("stage_identity"), candidate_deadline=kwargs.get("candidate_deadline"),
    )
    phase_timings = dict(prediction.phase_timings)
    phase_timings["preprocess"] = preprocess.timings
    return replace(
        prediction,
        elapsed_seconds=preprocess.elapsed_seconds + prediction.elapsed_seconds,
        gpu_lock_wait_seconds=preprocess.gpu_lock_wait_seconds + prediction.gpu_lock_wait_seconds,
        phase_timings=phase_timings,
        unattributed_runner_seconds=(
            prediction.unattributed_runner_seconds + max(
                0.0, preprocess.elapsed_seconds - sum(preprocess.timings.values())
            )
        ),
    )
