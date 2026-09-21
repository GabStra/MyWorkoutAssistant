from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import ctypes
from pathlib import Path
from typing import Any, Callable


GPU_LOCK_ENABLED_ENV_VAR = "EXERCISE_MOTION_GPU_LOCK"
GPU_LOCK_PATH_ENV_VAR = "EXERCISE_MOTION_GPU_LOCK_PATH"
GPU_LOCK_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_GPU_LOCK_TIMEOUT_SECONDS"
DEFAULT_GPU_LOCK_TIMEOUT_SECONDS = 6 * 60 * 60
GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS_ENV_VAR = (
    "EXERCISE_MOTION_GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS"
)
# A same-process holder is a resident model session, not another job; if it
# starves the rest of the pipeline for this long something is pinned, so the
# wait must fail (and repair) long before the cross-process timeout.
DEFAULT_GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS = 15 * 60
GPU_LOCK_WAIT_LOG_SECONDS = 60.0
LEGACY_GPU_LOCK_GRACE_SECONDS = 60.0
_LOCAL_GPU_LOCK_RELEASED = threading.Condition()
_LOCAL_GPU_LOCK_WAIT_SECONDS = 0.25

_HOLDER_REGISTRY: dict[int, list["GlobalGpuLock"]] = {}
_REGISTRY_LOCK = threading.Lock()


def _gpu_lock_log(message: str) -> None:
    print(f"[gpu-lock] {message}", file=sys.stderr, flush=True)


def _windows_file_handle(path: Path, *, create: bool) -> int:
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_file = kernel.CreateFileW
    open_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                          wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_file.restype = wintypes.HANDLE
    # OS-owned deletion removes the lease even on process death. Readers must
    # share DELETE access, so inspecting metadata cannot prevent release.
    handle = open_file(str(path), 0x40010000 if create else 0x80000000,
                       7, None, 1 if create else 3, 0x04000080 if create else 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def open_lock_lease(path: Path) -> int:
    if os.name != "nt":
        return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    import msvcrt
    return msvcrt.open_osfhandle(_windows_file_handle(path, create=True), os.O_WRONLY)


def read_lock_text(path: Path) -> str:
    if os.name != "nt":
        return path.read_text(encoding="utf-8")
    import msvcrt
    descriptor = msvcrt.open_osfhandle(_windows_file_handle(path, create=False), os.O_RDONLY)
    with os.fdopen(descriptor, "r", encoding="utf-8") as reader:
        return reader.read()


def lock_open_is_contention(error: OSError) -> bool:
    # DELETE_PENDING is reported as access denied until the last reader closes.
    return isinstance(error, FileExistsError) or getattr(error, "winerror", None) in {5, 32, 80, 183}


def close_lock_lease(handle: int, path: Path) -> None:
    os.close(handle)
    if os.name != "nt":
        path.unlink(missing_ok=True)


class GlobalGpuLock:
    def __init__(
        self,
        *,
        stage: str,
        enabled: bool = True,
        on_force_release: Callable[[], None] | None = None,
    ) -> None:
        self.stage = stage
        self.enabled = enabled and gpu_lock_enabled()
        self.path = gpu_lock_path()
        self.timeout_seconds = gpu_lock_timeout_seconds()
        self.same_process_timeout_seconds = gpu_lock_same_process_timeout_seconds()
        self.wait_seconds = 0.0
        self._handle: int | None = None
        self._force_released = False
        self.on_force_release = on_force_release

    def _acquired(self) -> float:
        with _REGISTRY_LOCK:
            _HOLDER_REGISTRY.setdefault(os.getpid(), []).append(self)
        return self.wait_seconds

    def _release_lease(self) -> None:
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        close_lock_lease(handle, self.path)
        with _REGISTRY_LOCK:
            holders = _HOLDER_REGISTRY.get(os.getpid())
            if holders and self in holders:
                holders.remove(self)
                if not holders:
                    _HOLDER_REGISTRY.pop(os.getpid(), None)

    def force_release(self, reason: str) -> bool:
        """Last-resort repair: drop this holder's lease so starvation ends."""
        if self._handle is None:
            return False
        self._force_released = True
        _gpu_lock_log(
            f"force-releasing GPU lock holder stage={self.stage} "
            f"threadId={threading.get_ident()}: {reason}"
        )
        self._release_lease()
        callback = self.on_force_release
        if callback is not None:
            try:
                callback()
            except Exception as error:  # The lease is already gone; keep going.
                _gpu_lock_log(f"force-release callback failed for stage={self.stage}: {error}")
        return True

    def __enter__(self) -> float:
        if not self.enabled:
            return 0.0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        last_wait_log = 0.0
        while True:
            try:
                self._handle = open_lock_lease(self.path)
                payload = {
                    "pid": os.getpid(),
                    "processIdentity": process_identity(os.getpid()),
                    "threadId": threading.get_ident(),
                    "stage": self.stage,
                    "createdAt": time.time(),
                }
                os.write(self._handle, json.dumps(payload).encode("utf-8"))
                self.wait_seconds = time.perf_counter() - started
                self._acquired()
                return self.wait_seconds
            except OSError as error:
                if self._handle is not None:
                    handle, self._handle = self._handle, None
                    close_lock_lease(handle, self.path)
                    raise
                if not lock_open_is_contention(error):
                    raise
                active_payload = lock_payload(self.path)
                same_process = (
                    isinstance(active_payload, dict)
                    and active_payload.get("pid") == os.getpid()
                )
                if same_process:
                    current_thread_id = threading.get_ident()
                    if active_payload.get("threadId") == current_thread_id:
                        raise RuntimeError(
                            "Nested global GPU lock acquisition in the same thread would deadlock: "
                            f"currentStage={active_payload.get('stage')} requestedStage={self.stage} "
                            f"threadId={current_thread_id} lockPath={self.path}"
                        )
                elif not self.path.exists():
                    continue
                elif gpu_lock_is_stale(self.path, timeout_seconds=self.timeout_seconds):
                    try:
                        self.path.unlink()
                        continue
                    except OSError:
                        pass
                elapsed = time.perf_counter() - started
                if elapsed - last_wait_log >= GPU_LOCK_WAIT_LOG_SECONDS:
                    last_wait_log = elapsed
                    holder_stage = active_payload.get("stage") if isinstance(active_payload, dict) else None
                    holder_pid = active_payload.get("pid") if isinstance(active_payload, dict) else None
                    _gpu_lock_log(
                        f"waiting for global GPU lock: requestedStage={self.stage} "
                        f"waited={elapsed:.0f}s holderStage={holder_stage} "
                        f"holderPid={holder_pid} sameProcess={same_process}"
                    )
                effective_timeout = (
                    min(self.timeout_seconds, self.same_process_timeout_seconds)
                    if same_process
                    else self.timeout_seconds
                )
                if elapsed >= effective_timeout:
                    if same_process and force_release_gpu_lock_holders(
                        self.path,
                        reason=(
                            f"same-process holder starved {self.stage} for {elapsed:.0f}s"
                        ),
                    ):
                        continue
                    raise TimeoutError(f"Timed out waiting for global GPU lock: {self.path}")
                if same_process:
                    remaining_seconds = effective_timeout - elapsed
                    with _LOCAL_GPU_LOCK_RELEASED:
                        _LOCAL_GPU_LOCK_RELEASED.wait(
                            timeout=min(_LOCAL_GPU_LOCK_WAIT_SECONDS, remaining_seconds)
                        )
                else:
                    time.sleep(2.0)
            except BaseException:
                if self._handle is not None:
                    handle, self._handle = self._handle, None
                    close_lock_lease(handle, self.path)
                raise

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            self._release_lease()
        finally:
            with _LOCAL_GPU_LOCK_RELEASED:
                _LOCAL_GPU_LOCK_RELEASED.notify_all()


def force_release_gpu_lock_holders(lock_path: Path, *, reason: str) -> bool:
    """Force-release live holders owned by this process (crashed or pinned)."""
    payload = lock_payload(lock_path)
    if not isinstance(payload, dict) or payload.get("pid") != os.getpid():
        return False
    with _REGISTRY_LOCK:
        holders = list(_HOLDER_REGISTRY.get(os.getpid(), []))
    released = False
    for holder in holders:
        if holder.force_release(reason):
            released = True
    if not released:
        _gpu_lock_log(
            f"cannot force-release same-process GPU lock holder: no registered holder. {reason}"
        )
    return released


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


def gpu_lock_same_process_timeout_seconds() -> float:
    raw = os.environ.get(GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS_ENV_VAR)
    if raw is None:
        return float(DEFAULT_GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS)
    try:
        return max(1.0, float(raw))
    except ValueError:
        return float(DEFAULT_GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS)


def gpu_lock_is_stale(lock_path: Path, *, timeout_seconds: float) -> bool:
    try:
        payload = json.loads(read_lock_text(lock_path))
    except (OSError, json.JSONDecodeError):
        return lock_age_seconds(lock_path) > timeout_seconds
    pid = payload.get("pid") if isinstance(payload, dict) else None
    if isinstance(pid, int) and pid > 0 and not process_is_running(pid):
        return True
    expected_identity = payload.get("processIdentity") if isinstance(payload, dict) else None
    if isinstance(pid, int) and isinstance(expected_identity, int):
        active_identity = process_identity(pid)
        if active_identity is None or active_identity != expected_identity:
            return True
    elif isinstance(pid, int) and lock_age_seconds(lock_path) > LEGACY_GPU_LOCK_GRACE_SECONDS:
        # Locks created before process identities were recorded cannot distinguish
        # their owner from an unrelated process that later reused the same PID.
        return True
    return lock_age_seconds(lock_path) > timeout_seconds


def process_identity(pid: int) -> int | None:
    """Return an OS process-start identity so recycled PIDs do not retain locks."""
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return None
        try:
            creation = ctypes.c_ulonglong()
            exit_time = ctypes.c_ulonglong()
            kernel = ctypes.c_ulonglong()
            user = ctypes.c_ulonglong()
            if not ctypes.windll.kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            return int(creation.value)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        return int(Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21])
    except (OSError, IndexError, ValueError):
        return None


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
        payload = json.loads(read_lock_text(lock_path))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
