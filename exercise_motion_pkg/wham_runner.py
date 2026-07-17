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

from exercise_motion_pkg.gpu_lock import gpu_stage_lock


DEFAULT_WHAM_DOCKER_IMAGE = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1"
DEFAULT_WHAM_DOCKER_SHM_SIZE = "16g"
DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY = True
DEFAULT_WHAM_TIMEOUT_SECONDS = 0.0
WHAM_DOCKER_LOCK_ENV_VAR = "EXERCISE_MOTION_WHAM_DOCKER_LOCK"
WHAM_DOCKER_LOCK_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_WHAM_DOCKER_LOCK_TIMEOUT_SECONDS"
WHAM_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_WHAM_TIMEOUT_SECONDS"
WHAM_WARM_WORKER_SESSION_DIR_ENV_VAR = "EXERCISE_MOTION_WHAM_WARM_WORKER_SESSION_DIR"
WHAM_WARM_WORKER_MOUNT_ROOT_ENV_VAR = "EXERCISE_MOTION_WHAM_WARM_WORKER_MOUNT_ROOT"
WHAM_WARM_WORKER_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_WHAM_WARM_WORKER_TIMEOUT_SECONDS"
DEFAULT_WHAM_DOCKER_LOCK_TIMEOUT_SECONDS = 6 * 60 * 60
DEFAULT_WHAM_WARM_WORKER_TIMEOUT_SECONDS = DEFAULT_WHAM_TIMEOUT_SECONDS
WHAM_TRACKING_PREFLIGHT_REJECTED_EXIT_CODE = 42


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
            "stdoutLog": str(self.stdout_log),
            "stderrLog": str(self.stderr_log),
            "command": self.command,
            "outputDir": str(self.output_dir),
            "resultsPkl": str(self.results_pkl),
            "dockerLockWaitSeconds": round(self.docker_lock_wait_seconds, 3) if self.use_docker else 0.0,
            "gpuLockWaitSeconds": round(self.gpu_lock_wait_seconds, 3),
            "stageTimings": self.stage_timings,
        }


@dataclass(frozen=True)
class WhamTrackingPreflightResult:
    passed: bool
    report_path: Path
    stdout_log: Path
    stderr_log: Path
    command: list[str]
    elapsed_seconds: float
    payload: dict[str, Any]


def run_wham_tracking_preflight(
    *,
    wham_repo_path: Path,
    input_video: Path,
    output_root: Path,
    logs_dir: Path,
    python_command: str,
    required_start_seconds: float | None,
    required_end_seconds: float | None,
    use_docker: bool,
    docker_image: str,
    docker_gpus: str,
    docker_shm_size: str,
    timeout_seconds: float | None,
) -> WhamTrackingPreflightResult:
    output_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    report_path = logs_dir / "wham_tracking_preflight.json"
    stdout_log = logs_dir / "wham_tracking_preflight.stdout.log"
    stderr_log = logs_dir / "wham_tracking_preflight.stderr.log"
    script_path = Path(__file__).with_name("wham_tracking_preflight.py").resolve()
    docker_container_name = f"mwa-wham-preflight-{uuid.uuid4().hex}" if use_docker else None
    command = build_wham_tracking_preflight_command(
        wham_repo_path=wham_repo_path,
        script_path=script_path,
        input_video=input_video,
        output_root=output_root,
        report_path=report_path,
        python_command=python_command,
        required_start_seconds=required_start_seconds,
        required_end_seconds=required_end_seconds,
        use_docker=use_docker,
        docker_image=docker_image,
        docker_gpus=docker_gpus,
        docker_shm_size=docker_shm_size,
        docker_container_name=docker_container_name,
    )
    started = time.perf_counter()
    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open("w", encoding="utf-8") as stderr_handle:
        with gpu_stage_lock(stage="wham_tracking_preflight"):
            returncode = run_wham_process(
                command,
                cwd=str(wham_repo_path),
                stdout=stdout_handle,
                stderr=stderr_handle,
                timeout_seconds=resolve_wham_timeout_seconds(timeout_seconds),
                docker_container_name=docker_container_name,
            )
    elapsed = time.perf_counter() - started
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if returncode not in {0, WHAM_TRACKING_PREFLIGHT_REJECTED_EXIT_CODE}:
        raise RuntimeError(
            "WHAM tracking preflight failed. Check logs:\n"
            f"- {stdout_log}\n- {stderr_log}"
        )
    passed = returncode == 0 and bool(payload.get("passed"))
    return WhamTrackingPreflightResult(
        passed=passed,
        report_path=report_path,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        command=command,
        elapsed_seconds=elapsed,
        payload=payload,
    )


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
) -> WhamRunResult:
    validate_wham_repo_layout(wham_repo_path, estimate_local_only=estimate_local_only)
    output_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = logs_dir / "wham.stdout.log"
    stderr_log = logs_dir / "wham.stderr.log"
    if use_warm_worker:
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
            timeout_seconds=warm_worker_timeout_seconds if warm_worker_timeout_seconds is not None else timeout_seconds,
        )
    timeout = resolve_wham_timeout_seconds(timeout_seconds)
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
                returncode = run_wham_process(
                    command,
                    cwd=str(wham_repo_path),
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    timeout_seconds=timeout,
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
) -> WhamRunResult:
    if not use_docker:
        raise ValueError("Warm WHAM worker mode currently requires Docker WHAM execution.")
    session_dir = resolve_warm_worker_session_dir(warm_worker_session_dir)
    mount_root = resolve_warm_worker_mount_root(warm_worker_mount_root)
    timeout = resolve_warm_worker_timeout_seconds(timeout_seconds)
    jobs_dir = session_dir / "jobs"
    results_dir = session_dir / "results"
    job_logs_dir = session_dir / "job_logs"
    for path in (jobs_dir, results_dir, job_logs_dir):
        path.mkdir(parents=True, exist_ok=True)
    ready_path = session_dir / "ready.json"
    if not ready_path.exists():
        raise RuntimeError(f"Warm WHAM worker is not ready: {ready_path}")

    job_id = uuid.uuid4().hex
    container_input_video = path_inside_worker_mount(input_video, mount_root=mount_root)
    container_output_root = path_inside_worker_mount(output_root, mount_root=mount_root)
    job_payload = {
        "jobId": job_id,
        "video": container_input_video,
        "outputRoot": container_output_root,
        "estimateLocalOnly": estimate_local_only,
        "runSmplify": run_smplify,
    }
    job_path = jobs_dir / f"{job_id}.json"
    tmp_job_path = jobs_dir / f"{job_id}.json.tmp"
    result_path = results_dir / f"{job_id}.json"
    started = time.perf_counter()
    lock_wait_seconds = 0.0
    gpu_lock_wait_seconds = 0.0
    with gpu_stage_lock(stage="wham_warm_worker_job") as gpu_lock_wait_seconds:
        with wham_docker_run_lock(enabled=True) as lock_wait_seconds:
            tmp_job_path.write_text(json.dumps(job_payload, indent=2), encoding="utf-8")
            tmp_job_path.replace(job_path)
            result_payload = wait_for_warm_worker_result(result_path, timeout_seconds=timeout)
    elapsed = time.perf_counter() - started
    worker_stdout_log = job_logs_dir / f"{job_id}.stdout.log"
    worker_stderr_log = job_logs_dir / f"{job_id}.stderr.log"
    copy_worker_log(worker_stdout_log, stdout_log)
    copy_worker_log(worker_stderr_log, stderr_log)
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
    docker_container_name: str | None,
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


def wait_for_warm_worker_result(path: Path, *, timeout_seconds: float | None) -> dict[str, Any]:
    started = time.perf_counter()
    while True:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if timeout_seconds is not None and time.perf_counter() - started >= timeout_seconds:
            raise TimeoutError(f"Timed out waiting for warm WHAM worker result: {path}")
        time.sleep(0.5)


def copy_worker_log(source: Path, destination: Path) -> None:
    if source.exists():
        destination.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    else:
        destination.write_text("", encoding="utf-8")


@contextmanager
def wham_docker_run_lock(*, enabled: bool):
    if not enabled:
        yield 0.0
        return

    lock_path = wham_docker_lock_path()
    timeout_seconds = wham_docker_lock_timeout_seconds()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    lock_handle: int | None = None
    while True:
        try:
            lock_handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {
                "pid": os.getpid(),
                "createdAt": time.time(),
            }
            os.write(lock_handle, json.dumps(payload).encode("utf-8"))
            break
        except FileExistsError:
            if wham_docker_lock_is_stale(lock_path, timeout_seconds=timeout_seconds):
                try:
                    lock_path.unlink()
                    continue
                except OSError:
                    pass
            elapsed = time.perf_counter() - started
            if elapsed >= timeout_seconds:
                raise TimeoutError(f"Timed out waiting for WHAM Docker lock: {lock_path}")
            time.sleep(2.0)
    try:
        yield time.perf_counter() - started
    finally:
        if lock_handle is not None:
            os.close(lock_handle)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


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
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return lock_age_seconds(lock_path) > timeout_seconds
    pid = payload.get("pid") if isinstance(payload, dict) else None
    if isinstance(pid, int) and pid > 0 and not process_is_running(pid):
        return True
    return lock_age_seconds(lock_path) > timeout_seconds


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
        command.extend(
            [
                "-v",
                f"{wham_repo_path.resolve()}:/code",
                "-v",
                f"{input_video.parent.resolve()}:/input",
                "-v",
                f"{output_root.resolve()}:/output",
                "-w",
                "/code",
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
        command.extend(
            [
                "-v",
                f"{wham_repo_path.resolve()}:/code",
                "-v",
                f"{script_path.parent.resolve()}:/mwa",
                "-v",
                f"{input_video.parent.resolve()}:/input",
                "-v",
                f"{output_root.resolve()}:/output",
                "-v",
                f"{report_path.parent.resolve()}:/logs",
                "-w",
                "/code",
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


def validate_wham_repo_layout(wham_repo_path: Path, *, estimate_local_only: bool) -> None:
    required_paths = [
        wham_repo_path / "demo.py",
        wham_repo_path / "requirements.txt",
        wham_repo_path / "checkpoints" / "wham_vit_w_3dpw.pth.tar",
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
