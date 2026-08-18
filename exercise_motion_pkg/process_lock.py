from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path


class InterProcessFileLock:
    """Small dependency-free lock for work shared by sibling Python processes."""

    def __init__(
        self,
        path: Path,
        *,
        stage: str,
        timeout_seconds: float,
        stale_after_seconds: float,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self.path = path
        self.stage = stage
        self.timeout_seconds = timeout_seconds
        self.stale_after_seconds = stale_after_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._handle: int | None = None

    def __enter__(self) -> float:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
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
                return time.monotonic() - started
            except FileExistsError:
                if interprocess_lock_is_stale(
                    self.path,
                    stale_after_seconds=self.stale_after_seconds,
                ):
                    try:
                        self.path.unlink()
                        continue
                    except OSError:
                        pass
                if time.monotonic() - started >= self.timeout_seconds:
                    raise TimeoutError(f"Timed out waiting for process lock: {self.path}")
                time.sleep(self.poll_interval_seconds)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._handle is not None:
            os.close(self._handle)
            self._handle = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def interprocess_lock_is_stale(path: Path, *, stale_after_seconds: float) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return lock_age_seconds(path) > stale_after_seconds
    pid = payload.get("pid") if isinstance(payload, dict) else None
    if isinstance(pid, int) and pid > 0 and not process_is_running(pid):
        return True
    return lock_age_seconds(path) > stale_after_seconds


def lock_age_seconds(path: Path) -> float:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
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
