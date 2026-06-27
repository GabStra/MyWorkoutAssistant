from __future__ import annotations

import subprocess
import json
import os
import tempfile
import time
from contextlib import contextmanager
from typing import Any
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WHAM_DOCKER_IMAGE = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1"
DEFAULT_WHAM_DOCKER_SHM_SIZE = "16g"
DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY = True
WHAM_DOCKER_LOCK_ENV_VAR = "EXERCISE_MOTION_WHAM_DOCKER_LOCK"
WHAM_DOCKER_LOCK_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_WHAM_DOCKER_LOCK_TIMEOUT_SECONDS"
DEFAULT_WHAM_DOCKER_LOCK_TIMEOUT_SECONDS = 6 * 60 * 60


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

    def timing_payload(self) -> dict[str, Any]:
        return {
            "elapsedSeconds": round(self.elapsed_seconds, 3),
            "returncode": self.returncode,
            "useDocker": self.use_docker,
            "estimateLocalOnly": self.estimate_local_only,
            "runSmplify": self.run_smplify,
            "dockerImage": self.docker_image if self.use_docker else None,
            "stdoutLog": str(self.stdout_log),
            "stderrLog": str(self.stderr_log),
            "command": self.command,
            "outputDir": str(self.output_dir),
            "resultsPkl": str(self.results_pkl),
            "dockerLockWaitSeconds": round(self.docker_lock_wait_seconds, 3) if self.use_docker else 0.0,
        }


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
) -> WhamRunResult:
    validate_wham_repo_layout(wham_repo_path, estimate_local_only=estimate_local_only)
    output_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = logs_dir / "wham.stdout.log"
    stderr_log = logs_dir / "wham.stderr.log"
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
    )
    started = time.perf_counter()
    lock_wait_seconds = 0.0
    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open(
        "w",
        encoding="utf-8",
    ) as stderr_handle:
        with wham_docker_run_lock(enabled=use_docker) as lock_wait_seconds:
            process = subprocess.run(
                command,
                cwd=str(wham_repo_path),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                check=False,
            )
    elapsed = time.perf_counter() - started
    if process.returncode != 0:
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
        returncode=process.returncode,
        use_docker=use_docker,
        estimate_local_only=estimate_local_only,
        run_smplify=run_smplify,
        docker_image=docker_image if use_docker else None,
        docker_lock_wait_seconds=lock_wait_seconds,
    )


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
) -> list[str]:
    if use_docker:
        command = ["docker", "run", "--rm"]
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
