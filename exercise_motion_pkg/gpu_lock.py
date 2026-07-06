from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


GPU_LOCK_ENABLED_ENV_VAR = "EXERCISE_MOTION_GPU_LOCK"
GPU_LOCK_PATH_ENV_VAR = "EXERCISE_MOTION_GPU_LOCK_PATH"
GPU_LOCK_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_GPU_LOCK_TIMEOUT_SECONDS"
DEFAULT_GPU_LOCK_TIMEOUT_SECONDS = 6 * 60 * 60


class GlobalGpuLock:
    def __init__(self, *, stage: str, enabled: bool = True) -> None:
        self.stage = stage
        self.enabled = enabled and gpu_lock_enabled()
        self.path = gpu_lock_path()
        self.timeout_seconds = gpu_lock_timeout_seconds()
        self.wait_seconds = 0.0
        self._handle: int | None = None

    def __enter__(self) -> float:
        if not self.enabled:
            return 0.0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        while True:
            try:
                self._handle = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                payload = {
                    "pid": os.getpid(),
                    "threadId": threading.get_ident(),
                    "stage": self.stage,
                    "createdAt": time.time(),
                }
                os.write(self._handle, json.dumps(payload).encode("utf-8"))
                self.wait_seconds = time.perf_counter() - started
                return self.wait_seconds
            except FileExistsError:
                if gpu_lock_is_stale(self.path, timeout_seconds=self.timeout_seconds):
                    try:
                        self.path.unlink()
                        continue
                    except OSError:
                        pass
                active_payload = lock_payload(self.path)
                if (
                    isinstance(active_payload, dict)
                    and active_payload.get("pid") == os.getpid()
                    and active_payload.get("threadId") == threading.get_ident()
                ):
                    raise RuntimeError(
                        "Nested global GPU lock acquisition in the same thread would deadlock: "
                        f"currentStage={active_payload.get('stage')} requestedStage={self.stage} "
                        f"lockPath={self.path}"
                    )
                elapsed = time.perf_counter() - started
                if elapsed >= self.timeout_seconds:
                    raise TimeoutError(f"Timed out waiting for global GPU lock: {self.path}")
                time.sleep(2.0)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._handle is not None:
            os.close(self._handle)
            self._handle = None
        if self.enabled:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def gpu_stage_lock(*, stage: str, enabled: bool = True) -> GlobalGpuLock:
    return GlobalGpuLock(stage=stage, enabled=enabled)


def gpu_lock_enabled() -> bool:
    value = os.environ.get(GPU_LOCK_ENABLED_ENV_VAR)
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "off", "no"}


def gpu_lock_path() -> Path:
    configured = os.environ.get(GPU_LOCK_PATH_ENV_VAR)
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / "myworkoutassistant-gpu.lock"


def gpu_lock_timeout_seconds() -> float:
    raw = os.environ.get(GPU_LOCK_TIMEOUT_SECONDS_ENV_VAR)
    if raw is None:
        return float(DEFAULT_GPU_LOCK_TIMEOUT_SECONDS)
    try:
        return max(1.0, float(raw))
    except ValueError:
        return float(DEFAULT_GPU_LOCK_TIMEOUT_SECONDS)


def gpu_lock_is_stale(lock_path: Path, *, timeout_seconds: float) -> bool:
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
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
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


def lock_payload(path: Path | None = None) -> dict[str, Any] | None:
    lock_path = path or gpu_lock_path()
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
