from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import ctypes
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from exercise_motion_pkg.process_lock import InterProcessFileLock


GPU_LOCK_ENABLED_ENV_VAR = "EXERCISE_MOTION_GPU_LOCK"
GPU_LOCK_PATH_ENV_VAR = "EXERCISE_MOTION_GPU_LOCK_PATH"
GPU_LOCK_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_GPU_LOCK_TIMEOUT_SECONDS"
DEFAULT_GPU_LOCK_TIMEOUT_SECONDS = 6 * 60 * 60
EXCLUSIVE_GPU_DEVICE_ENV_VAR = "EXERCISE_MOTION_EXCLUSIVE_GPU_DEVICE"
_GPU_COUNT_CACHE: tuple[float, int | None] = (0.0, None)


def exclusive_gpu_device() -> str | None:
    """Secondary CUDA device for exclusive GPU stages, or None for one lane.

    When set to a device index (e.g. "1"), exclusive stages run on that
    physical device behind a per-device lock lane, and the resident llama
    server is pinned to a different device, so reviews and reconstruction
    overlap instead of trading drain/restart cycles. Unset, empty, or "0"
    keeps the legacy single-lane behavior.
    """
    raw = os.environ.get(EXCLUSIVE_GPU_DEVICE_ENV_VAR)
    if raw is None:
        return None
    device = raw.strip()
    if not device or device == "0":
        return None
    try:
        device_index = int(device)
    except ValueError:
        raise ValueError(
            f"{EXCLUSIVE_GPU_DEVICE_ENV_VAR} must be a CUDA device index, got {raw!r}"
        )
    if device_index < 1:
        raise ValueError(
            f"{EXCLUSIVE_GPU_DEVICE_ENV_VAR} must be a device index >= 1, got {raw!r}"
        )
    count = visible_gpu_count()
    if count is not None and device_index >= count:
        raise ValueError(
            f"{EXCLUSIVE_GPU_DEVICE_ENV_VAR} selects CUDA device {device_index}, "
            f"but only {count} device(s) are visible."
        )
    return str(device_index)


def visible_gpu_count() -> int | None:
    """Cached CUDA device count from nvidia-smi; None when unknowable."""
    global _GPU_COUNT_CACHE
    with _FREE_VRAM_CACHE_LOCK:
        cached_at, cached_value = _GPU_COUNT_CACHE
        if time.perf_counter() - cached_at < 30.0:
            return cached_value
    count: int | None = None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5.0,
        )
        if result.returncode == 0:
            count = len([line for line in result.stdout.splitlines() if line.strip()])
    except (OSError, subprocess.SubprocessError):
        pass
    with _FREE_VRAM_CACHE_LOCK:
        _GPU_COUNT_CACHE = (time.perf_counter(), count)
    return count


def resolve_stage_cuda_device(device: str) -> str:
    """Map bare "cuda" to the exclusive lane's device for subprocess launchers."""
    lane = exclusive_gpu_device()
    normalized = device.strip().lower()
    if lane is not None:
        if normalized in {"cuda", "gpu"}:
            return f"cuda:{lane}"
        if normalized.startswith("cuda:") and normalized[5:].isdigit():
            requested_device = normalized[5:]
        elif normalized.isdigit():
            requested_device = normalized
        else:
            return device
        if requested_device != lane:
            raise ValueError(
                f"CUDA device {device!r} conflicts with exclusive GPU {lane}; "
                f"use cuda:{lane} or disable the exclusive GPU lane."
            )
    return device


def resolve_llama_server_cuda_visibility(exclusive_device: str | None) -> str | None:
    """Pin the resident llama server to GPU 0 when exclusive work uses another card."""
    if exclusive_device is None:
        return None
    gpu_uuid = gpu_device_uuid("0")
    if gpu_uuid is None:
        raise RuntimeError("Could not resolve physical GPU UUID for the resident llama server on GPU 0.")
    return gpu_uuid


def gpu_device_uuid(device_index: str) -> str | None:
    """Return the physical NVIDIA UUID for a host GPU index."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5.0,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            index, gpu_uuid = (part.strip() for part in line.split(",", 1))
            if index == str(device_index):
                return gpu_uuid
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def resolve_docker_gpu_selection(docker_gpus: str) -> str:
    """Pin Docker's grant to the same physical GPU used by the exclusive lane."""
    lane = exclusive_gpu_device()
    if lane is None:
        return docker_gpus

    gpu_selection = docker_gpus.strip()
    gpu_uuid = gpu_device_uuid(lane)
    if gpu_uuid is None:
        raise RuntimeError(f"Could not resolve physical GPU UUID for exclusive GPU {lane}.")
    if gpu_selection.lower() in {"", "all"}:
        return f"device={gpu_uuid}"

    selector_name, separator, selector_value = gpu_selection.partition("=")
    selector_value = selector_value.strip()
    if (
        separator
        and selector_name.strip().lower() == "device"
        and selector_value
        and "," not in selector_value
        and selector_value.lower() in {lane.lower(), gpu_uuid.lower()}
    ):
        return f"device={gpu_uuid}"

    raise ValueError(
        f"Docker GPU selection {docker_gpus!r} conflicts with exclusive GPU {lane}; "
        f"select device={gpu_uuid} or leave Docker GPU selection as 'all'."
    )


def _activate_torch_device(device: str) -> None:
    """Point current-device CUDA calls (.cuda(), tensor.to("cuda")) at this lane."""
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.set_device(int(device))
GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS_ENV_VAR = (
    "EXERCISE_MOTION_GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS"
)
# A same-process holder is a resident model session, not another job; if it
# starves the rest of the pipeline for this long something is pinned, so the
# wait must fail (and repair) long before the cross-process timeout.
DEFAULT_GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS = 15 * 60
GPU_LOCK_WAIT_LOG_SECONDS = 60.0
_LOCAL_GPU_LOCK_RELEASED = threading.Condition()
_LOCAL_GPU_LOCK_WAIT_SECONDS = 0.25

_HOLDER_REGISTRY: dict[int, list["GlobalGpuLock"]] = {}
_REGISTRY_LOCK = threading.Lock()

# Co-residency support for small CUDA ops (pose prefilter, UniDepth sampling):
# they may run beside a resident exclusive holder (the llama.cpp server) when
# free VRAM allows, instead of draining it and paying a ~40s server restart.
SMALL_GPU_PROBE_CACHE_SECONDS = 1.0
_SMALL_OP_SERIALIZE = threading.RLock()
_SMALL_OP_CONTEXT = threading.local()
_FREE_VRAM_CACHE: tuple[float, int | None] = (0.0, None)
_FREE_VRAM_CACHE_LOCK = threading.Lock()

GPU_COOLING_PAUSE_C = 80
GPU_COOLING_RESUME_C = 74
GPU_COOLING_TIMEOUT_SECONDS = 10 * 60
GPU_COOLING_POLL_SECONDS = 2.0
_TEMPERATURE_WARNING_SHOWN = False


def query_gpu_temperature_c() -> int | None:
    """Read the hottest NVIDIA GPU; model layers may span both cards."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5.0,
        )
        if result.returncode == 0:
            return max(int(line.strip()) for line in result.stdout.splitlines())
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def wait_for_gpu_cooling(
    stage: str,
    *,
    deadline: float | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> float:
    """Gate new GPU operations only; active work and CPU workers keep running."""
    global _TEMPERATURE_WARNING_SHOWN
    from exercise_motion_pkg.motion_scheduler import current_gpu_stage_deadline

    candidate_deadline = current_gpu_stage_deadline()
    started = time.perf_counter()
    cooling_deadline = started + GPU_COOLING_TIMEOUT_SECONDS
    for budget_deadline in (deadline, candidate_deadline):
        if budget_deadline is not None:
            cooling_deadline = min(cooling_deadline, budget_deadline)

    def check_wait() -> None:
        if cancelled():
            raise RuntimeError(f"GPU cooling wait cancelled: stage={stage}")
        if time.perf_counter() >= cooling_deadline:
            raise TimeoutError(f"GPU cooling wait exceeded its budget: stage={stage}")

    check_wait()
    # Keep sibling processes from admitting work at 79C while another waits for 74C.
    cooling_path = gpu_lock_path().with_suffix(".cooling.oslock")
    with InterProcessFileLock(
        cooling_path, stage=f"gpu_cooling:{stage}",
        timeout_seconds=max(0.0, cooling_deadline - time.perf_counter()),
        stale_after_seconds=GPU_COOLING_TIMEOUT_SECONDS,
    ):
        check_wait()
        temperature = query_gpu_temperature_c()
        check_wait()
        if temperature is None:
            if not _TEMPERATURE_WARNING_SHOWN:
                _gpu_lock_log("GPU temperature unavailable; cooling admission is not enforced.")
                _TEMPERATURE_WARNING_SHOWN = True
            return time.perf_counter() - started
        if temperature < GPU_COOLING_PAUSE_C:
            return time.perf_counter() - started
        _gpu_lock_log(
            f"cooling before stage={stage}: temperature={temperature}C "
            f"resumeAt={GPU_COOLING_RESUME_C}C; active GPU work may finish"
        )
        while temperature > GPU_COOLING_RESUME_C:
            check_wait()
            time.sleep(min(GPU_COOLING_POLL_SECONDS, cooling_deadline - time.perf_counter()))
            check_wait()
            temperature = query_gpu_temperature_c()
            check_wait()
            if temperature is None:
                raise RuntimeError(f"GPU temperature became unavailable during cooling: stage={stage}")
        waited = time.perf_counter() - started
        _gpu_lock_log(f"cooling finished before stage={stage}: temperature={temperature}C waited={waited:.1f}s")
        return waited


def _probe_free_gpu_memory_mib() -> int | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def query_free_gpu_memory_mib() -> int | None:
    """Best-effort free-VRAM reading in MiB, cached briefly. None = unknown."""
    global _FREE_VRAM_CACHE
    with _FREE_VRAM_CACHE_LOCK:
        cached_at, cached_value = _FREE_VRAM_CACHE
        if time.perf_counter() - cached_at < SMALL_GPU_PROBE_CACHE_SECONDS:
            return cached_value
    value = _probe_free_gpu_memory_mib()
    with _FREE_VRAM_CACHE_LOCK:
        _FREE_VRAM_CACHE = (time.perf_counter(), value)
    return value


@dataclass(frozen=True)
class SmallGpuLease:
    granted: bool
    free_mib: int | None


@contextmanager
def small_gpu_stage_lock(stage: str, *, min_free_mib: int) -> Iterator[SmallGpuLease]:
    """Try to co-reside a small CUDA op with a resident exclusive GPU holder.

    Grants only when the free-VRAM probe clears ``min_free_mib``; small ops are
    serialized among themselves in-process. When not granted, the caller must
    fall back to the exclusive handoff (drain the resident holder, then run) -
    acquiring the global lease here would stall behind the very holder the
    caller intends to keep alive. While a section is granted, inner
    ``gpu_stage_lock`` acquisitions on the same thread are no-ops, so callees
    that take the global lock themselves need no changes.
    """
    if getattr(_SMALL_OP_CONTEXT, "stage", None) is not None:
        # Nested inside an already-granted section that owns VRAM clearance.
        yield SmallGpuLease(granted=True, free_mib=query_free_gpu_memory_mib())
        return
    from exercise_motion_pkg.motion_scheduler import current_gpu_stage_deadline

    deadline = current_gpu_stage_deadline()
    if deadline is None:
        acquired = _SMALL_OP_SERIALIZE.acquire()
    else:
        acquired = _SMALL_OP_SERIALIZE.acquire(timeout=max(0.0, deadline - time.perf_counter()))
    if not acquired:
        raise TimeoutError(f"Candidate deadline expired waiting for small GPU stage lock: {stage}")
    try:
        wait_for_gpu_cooling(stage)
        free_mib = query_free_gpu_memory_mib()
        if free_mib is None or free_mib < min_free_mib:
            yield SmallGpuLease(granted=False, free_mib=free_mib)
            return
        _SMALL_OP_CONTEXT.stage = stage
        try:
            yield SmallGpuLease(granted=True, free_mib=free_mib)
        finally:
            _SMALL_OP_CONTEXT.stage = None
    finally:
        _SMALL_OP_SERIALIZE.release()


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


@contextmanager
def lock_lease_acquisition_guard(
    path: Path,
    *,
    stage: str,
    timeout_seconds: float,
) -> Iterator[None]:
    """Serialize lease creation and stale-file recovery across processes.

    The lease itself remains readable for diagnostics and keeps its existing
    process-exit behavior. This kernel-owned guard ensures two waiters cannot
    both act on the same stale-file observation while one replaces it.
    """
    guard_path = path.with_name(f"{path.name}.admission.oslock")
    with InterProcessFileLock(
        guard_path,
        stage=stage,
        timeout_seconds=timeout_seconds,
        stale_after_seconds=timeout_seconds,
    ):
        yield


class GlobalGpuLock:
    def __init__(
        self,
        *,
        stage: str,
        enabled: bool = True,
        on_force_release: Callable[[], None] | None = None,
        deadline: float | None = None,
        device: str | None = None,
    ) -> None:
        self.stage = stage
        self.enabled = enabled and gpu_lock_enabled()
        self.device = device
        self.path = gpu_lock_path(device)
        self.timeout_seconds = gpu_lock_timeout_seconds()
        self.same_process_timeout_seconds = gpu_lock_same_process_timeout_seconds()
        self.wait_seconds = 0.0
        self._handle: int | None = None
        self._force_released = False
        self.on_force_release = on_force_release
        try:
            from exercise_motion_pkg.motion_scheduler import current_gpu_stage_deadline

            inherited_deadline = current_gpu_stage_deadline()
            if inherited_deadline is not None:
                deadline = inherited_deadline if deadline is None else min(deadline, inherited_deadline)
        except ImportError:
            pass
        self.deadline = deadline

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
        """Stop the holder before releasing its lease so GPU use cannot overlap."""
        if self._handle is None:
            return False
        _gpu_lock_log(
            f"force-releasing GPU lock holder stage={self.stage} "
            f"threadId={threading.get_ident()}: {reason}"
        )
        callback = self.on_force_release
        if callback is not None:
            try:
                callback()
            except Exception as error:
                _gpu_lock_log(f"force-release callback failed for stage={self.stage}: {error}")
                return False
        self._force_released = True
        self._release_lease()
        return True

    def __enter__(self) -> float:
        if not self.enabled:
            return 0.0
        if getattr(_SMALL_OP_CONTEXT, "stage", None) is not None:
            # Inside a granted small-op co-residency section: VRAM clearance and
            # small-op serialization are already owned by this thread.
            return 0.0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        last_wait_log = 0.0
        while True:
            if self.deadline is not None and time.perf_counter() >= self.deadline:
                raise TimeoutError(
                    f"Candidate deadline expired waiting for global GPU lock: {self.path}"
                )
            active_payload: dict[str, Any] | None = None
            same_process = False
            guard_timeout = self.timeout_seconds
            if self.deadline is not None:
                guard_timeout = min(
                    guard_timeout,
                    max(0.0, self.deadline - time.perf_counter()),
                )
            try:
                with lock_lease_acquisition_guard(
                    self.path,
                    stage=f"gpu_lock_admission:{self.stage}",
                    timeout_seconds=guard_timeout,
                ):
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
                        break
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
            except TimeoutError as error:
                if self.deadline is not None and time.perf_counter() >= self.deadline:
                    raise TimeoutError(
                        f"Candidate deadline expired waiting for global GPU lock: {self.path}"
                    ) from error
                raise TimeoutError(
                    f"Timed out waiting for global GPU lock admission: {self.path}"
                ) from error
            except BaseException:
                if self._handle is not None:
                    handle, self._handle = self._handle, None
                    close_lock_lease(handle, self.path)
                raise
            elapsed = time.perf_counter() - started
            if self.deadline is not None and time.perf_counter() >= self.deadline:
                raise TimeoutError(
                    f"Candidate deadline expired waiting for global GPU lock: {self.path}"
                )
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
            if self.deadline is not None:
                effective_timeout = min(
                    effective_timeout,
                    max(0.0, self.deadline - started),
                )
            if elapsed >= effective_timeout:
                if self.deadline is not None and time.perf_counter() >= self.deadline:
                    raise TimeoutError(
                        f"Candidate deadline expired waiting for global GPU lock: {self.path}"
                    )
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
                sleep_seconds = 2.0
                if self.deadline is not None:
                    sleep_seconds = min(
                        sleep_seconds,
                        max(0.0, self.deadline - time.perf_counter()),
                    )
                time.sleep(sleep_seconds)
        try:
            wait_for_gpu_cooling(self.stage, deadline=self.deadline)
            if self.device is not None:
                _activate_torch_device(self.device)
            self.wait_seconds = time.perf_counter() - started
            return self._acquired()
        except BaseException:
            self._release_lease()
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


def gpu_stage_lock(
    *,
    stage: str,
    enabled: bool = True,
    deadline: float | None = None,
    device: str | None = None,
) -> GlobalGpuLock:
    if deadline is None:
        try:
            from exercise_motion_pkg.motion_scheduler import current_gpu_stage_deadline

            deadline = current_gpu_stage_deadline()
        except ImportError:
            pass
    return GlobalGpuLock(stage=stage, enabled=enabled, deadline=deadline, device=device)


def gpu_lock_enabled() -> bool:
    value = os.environ.get(GPU_LOCK_ENABLED_ENV_VAR)
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "off", "no"}


def gpu_lock_path(device: str | None = None) -> Path:
    configured = os.environ.get(GPU_LOCK_PATH_ENV_VAR)
    if configured:
        base = Path(configured).expanduser()
    else:
        base = Path(tempfile.gettempdir()) / "myworkoutassistant-gpu.lock"
    if device:
        # One lane per physical device so stages on different GPUs never wait
        # for each other; the legacy unsuffixed path remains lane zero.
        return base.with_name(f"{base.stem}-{device}{base.suffix}")
    return base


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
        # Unknown ownership cannot be revoked safely by age. The waiter will
        # time out while retaining the evidence for an explicit repair.
        return False
    pid = payload.get("pid") if isinstance(payload, dict) else None
    expected_identity = payload.get("processIdentity") if isinstance(payload, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        return False
    if not process_is_running(pid):
        return True
    if isinstance(expected_identity, int):
        active_identity = process_identity(pid)
        if active_identity is not None and active_identity != expected_identity:
            return True
    # A live owner keeps the lease regardless of age. Age is a wait bound,
    # never authority to evict an owner whose identity cannot be confirmed.
    return False


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
