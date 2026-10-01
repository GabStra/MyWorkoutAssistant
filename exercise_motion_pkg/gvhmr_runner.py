"""GVHMR reconstruction runner (Docker).

Mirrors wham_runner.run_wham_locally's contract but executes the GVHMR demo
pipeline inside the myworkoutassistant/gvhmr image and exports a WHAM-schema
pkl so the generation pipeline can consume either backend unchanged.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exercise_motion_pkg.gpu_lock import gpu_stage_lock
from exercise_motion_pkg.wham_runner import (
    copy_worker_log,
    ensure_warm_worker_ready,
    path_inside_worker_mount,
    run_wham_process,
    wait_for_warm_worker_result,
    wham_docker_run_lock,
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
) -> GvhmrRunResult:
    session_dir = resolve_gvhmr_warm_worker_session_dir(warm_worker_session_dir)
    mount_root = resolve_gvhmr_warm_worker_mount_root(warm_worker_mount_root)
    timeout = resolve_gvhmr_warm_worker_timeout_seconds(warm_worker_timeout_seconds)
    jobs_dir = session_dir / "jobs"
    results_dir = session_dir / "results"
    job_logs_dir = session_dir / "job_logs"
    for path in (jobs_dir, results_dir, job_logs_dir):
        path.mkdir(parents=True, exist_ok=True)
    ensure_warm_worker_ready(
        session_dir,
        timeout_seconds=timeout if timeout is not None else DEFAULT_GVHMR_WARM_WORKER_TIMEOUT_SECONDS,
        lazy_start_env_var=GVHMR_WARM_WORKER_LAZY_START_ENV_VAR,
        label="GVHMR",
    )

    job_id = uuid.uuid4().hex
    container_input_video = path_inside_worker_mount(input_video, mount_root=mount_root)
    container_output_root = path_inside_worker_mount(output_root, mount_root=mount_root)
    job_payload = {
        "jobId": job_id,
        "video": container_input_video,
        "outputRoot": container_output_root,
        "staticCam": static_camera,
        "keepSourceBetas": False,
    }
    job_path = jobs_dir / f"{job_id}.json"
    tmp_job_path = jobs_dir / f"{job_id}.json.tmp"
    result_path = results_dir / f"{job_id}.json"
    started = time.perf_counter()
    lock_wait_seconds = 0.0
    gpu_lock_wait_seconds = 0.0
    with gpu_stage_lock(stage="gvhmr_warm_worker_job") as gpu_lock_wait_seconds:
        with wham_docker_run_lock(enabled=True) as lock_wait_seconds:
            tmp_job_path.write_text(json.dumps(job_payload, indent=2), encoding="utf-8")
            tmp_job_path.replace(job_path)
            result_payload = wait_for_warm_worker_result(
                result_path,
                timeout_seconds=timeout,
                heartbeat_path=session_dir / "heartbeat.json",
                stopped_path=session_dir / "stopped.json",
            )
    elapsed = time.perf_counter() - started
    worker_stdout_log = job_logs_dir / f"{job_id}.stdout.log"
    worker_stderr_log = job_logs_dir / f"{job_id}.stderr.log"
    copy_worker_log(worker_stdout_log, stdout_log)
    copy_worker_log(worker_stderr_log, stderr_log)
    if result_payload.get("status") != "completed":
        error = result_payload.get("error") or "unknown warm worker failure"
        raise RuntimeError(
            "Warm GVHMR worker run failed. Check logs:\n"
            f"- {stdout_log}\n"
            f"- {stderr_log}\n"
            f"Error: {error}"
        )
    sequence_dir = output_root / input_video.stem
    results_pkl = sequence_dir / "wham_output.pkl"
    if not results_pkl.exists():
        raise RuntimeError(
            "Warm GVHMR worker completed but no wham_output.pkl was found.\n"
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
    # step converts it to the WHAM-schema pkl the pipeline expects at
    # <output_root>/<video-stem>/wham_output.pkl.
    container_stem = input_video.stem
    demo_results = f"/output/demo/{container_stem}/hmr4d_results.pt"
    output_pkl = f"/output/{container_stem}/wham_output.pkl"
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
        command.extend(["--gpus", docker_gpus])
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


def run_gvhmr_locally(
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
) -> GvhmrRunResult:
    """Run GVHMR in Docker and return a WHAM-schema results pkl path."""
    timeout = (
        DEFAULT_GVHMR_TIMEOUT_SECONDS
        if timeout_seconds is None or float(timeout_seconds) <= 0.0
        else max(1.0, float(timeout_seconds))
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
        with gpu_stage_lock(stage="gvhmr") as gpu_lock_wait_seconds:
            with wham_docker_run_lock(enabled=True) as lock_wait_seconds:
                returncode = run_wham_process(
                    command,
                    cwd=str(Path(__file__).resolve().parent),
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    timeout_seconds=timeout,
                    docker_container_name=docker_container_name,
                )
    elapsed = time.perf_counter() - started
    if returncode != 0:
        raise RuntimeError(
            "GVHMR run failed. Check logs:\n"
            f"- {stdout_log}\n- {stderr_log}"
        )
    sequence_dir = output_root / input_video.stem
    results_pkl = sequence_dir / "wham_output.pkl"
    if not results_pkl.exists():
        raise RuntimeError(
            "GVHMR run completed but no wham_output.pkl was found.\n"
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
