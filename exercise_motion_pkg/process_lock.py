from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, Callable


WORKSPACE_LEASE_FILENAME = ".motion_workspace.lock"
WORKSPACE_LEASE_OWNER_FILENAME = ".motion_workspace.owner.json"


class WorkspaceLease:
    """Hold an OS-level exclusive lease for a workspace's persistent state."""

    def __init__(self, workspace: Path, *, stage: str) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.lock_path = self.workspace / WORKSPACE_LEASE_FILENAME
        self.owner_path = self.workspace / WORKSPACE_LEASE_OWNER_FILENAME
        self.stage = stage
        self.owner_token = uuid.uuid4().hex
        self._descriptor: int | None = None

    def __enter__(self) -> "WorkspaceLease":
        self.workspace.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            self._acquire_windows()
        else:
            self._acquire_posix()
        try:
            self._reject_live_persisted_service_owner()
            owner = self._owner_payload()
            self._write_lock_metadata(owner)
            self._write_owner_metadata(owner)
        except Exception:
            self._release_lock()
            raise
        return self

    def _reject_live_persisted_service_owner(self) -> None:
        try:
            previous = json.loads(self.owner_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as exc:
            raise TimeoutError(
                "Workspace has an unreadable previous owner record; refusing to "
                f"replace it without confirming service shutdown: {self.owner_path}"
            ) from exc
        if not isinstance(previous, dict) or not previous.get("ownerToken"):
            raise TimeoutError(
                "Workspace has an incomplete previous owner record; refusing to "
                f"replace it without confirming service shutdown: {self.owner_path}"
            )
        runtime_owner = previous.get("runtimeOwner")
        if runtime_owner is None:
            return
        if not isinstance(runtime_owner, dict):
            raise TimeoutError(
                "Workspace has malformed service ownership evidence; refusing to "
                f"replace it without confirming service shutdown: {self.owner_path}"
            )
        state = service_runtime_state(runtime_owner)
        if state != "stopped":
            raise TimeoutError(
                "Workspace is retained by a previous motion service owner; "
                f"runtime state is {state}: {self.workspace}; "
                f"owner={json.dumps(previous, sort_keys=True)}"
            )

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            try:
                owner = json.loads(self.owner_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                owner = None
            if isinstance(owner, dict) and owner.get("ownerToken") == self.owner_token:
                self.owner_path.unlink(missing_ok=True)
        finally:
            self._release_lock()

    def _owner_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "pid": os.getpid(),
            "threadId": threading.get_ident(),
            "stage": self.stage,
            "workspaceRoot": str(self.workspace),
            "ownerToken": self.owner_token,
            "acquiredAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _acquire_windows(self) -> None:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(self.lock_path),
            0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
            0,  # No sharing: interoperates with PowerShell FileShare.None.
            None,
            4,  # OPEN_ALWAYS
            0x00000080,  # FILE_ATTRIBUTE_NORMAL
            None,
        )
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if error in (32, 33):  # Sharing or lock violation.
                raise self._already_leased_error() from ctypes.WinError(error)
            raise ctypes.WinError(error)
        try:
            self._descriptor = msvcrt.open_osfhandle(
                int(handle), os.O_RDWR | os.O_BINARY,
            )
        except Exception:
            kernel32.CloseHandle(handle)
            raise

    def _acquire_posix(self) -> None:
        import fcntl

        descriptor = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise self._already_leased_error() from exc
        self._descriptor = descriptor

    def _already_leased_error(self) -> TimeoutError:
        try:
            owner = self.owner_path.read_text(encoding="utf-8").strip()
        except OSError:
            owner = "owner metadata unavailable"
        return TimeoutError(
            f"Workspace is already owned by another motion run: {self.workspace}; "
            f"owner={owner}"
        )

    def _write_lock_metadata(self, owner: dict[str, Any]) -> None:
        if self._descriptor is None:
            raise RuntimeError("Workspace lease was not acquired")
        encoded = json.dumps(owner, sort_keys=True).encode("utf-8")
        os.lseek(self._descriptor, 0, os.SEEK_SET)
        os.ftruncate(self._descriptor, 0)
        os.write(self._descriptor, encoded)
        os.fsync(self._descriptor)

    def _write_owner_metadata(self, owner: dict[str, Any]) -> None:
        temporary = self.owner_path.with_name(
            f"{self.owner_path.name}.{self.owner_token}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(owner, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.owner_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _release_lock(self) -> None:
        if self._descriptor is None:
            return
        descriptor = self._descriptor
        self._descriptor = None
        os.close(descriptor)


def exclusive_workspace_lease(
    workspace_for_call: Callable[..., Path],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a workspace-owning entrypoint with an exclusive OS lease."""

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            workspace = Path(workspace_for_call(*args, **kwargs))
            with WorkspaceLease(workspace, stage=function.__name__):
                return function(*args, **kwargs)

        return wrapped

    return decorate


def service_runtime_state(runtime_owner: dict[str, Any]) -> str:
    """Return running/stopped/unknown for a service recorded in a lease file."""
    kind = str(runtime_owner.get("kind") or "")
    if kind == "process":
        try:
            pid = int(runtime_owner.get("pid") or 0)
        except (TypeError, ValueError):
            return "unknown"
        if pid <= 0:
            return "unknown"
        if not process_is_running(pid):
            return "stopped"
        active_identity = process_identity(pid)
        if active_identity is None:
            return "unknown"
        expected_identity = runtime_owner.get("processIdentity")
        if expected_identity is not None:
            try:
                if active_identity != int(expected_identity):
                    return "stopped"
            except (TypeError, ValueError):
                return "unknown"
        return "running"
    if kind == "docker":
        identifier = str(runtime_owner.get("containerId") or runtime_owner.get("containerName") or "")
        if not identifier:
            return "unknown"
        try:
            inspected = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", identifier],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if inspected.returncode == 0:
                state = inspected.stdout.strip().lower()
                return "running" if state == "true" else "stopped" if state == "false" else "unknown"
            # Warm-worker containers use --rm. Confirm the daemon can list
            # containers and that this exact ID/name is absent before treating
            # an uninspectable container as stopped.
            selector = (
                f"id={runtime_owner['containerId']}"
                if runtime_owner.get("containerId")
                else f"name={runtime_owner['containerName']}"
            )
            listed = subprocess.run(
                ["docker", "ps", "--all", "--filter", selector, "--format", "{{.ID}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if listed.returncode != 0:
                return "unknown"
            return "stopped" if not listed.stdout.strip() else "unknown"
        except (OSError, subprocess.SubprocessError):
            return "unknown"
    return "unknown"


def process_identity(pid: int) -> int | None:
    """Return a stable process start identity, or None when it cannot be read.

    The value matches PowerShell's Process.StartTime.ToFileTimeUtc() on
    Windows. On Linux it uses procfs starttime ticks. Callers must treat None
    as unknown rather than as proof that a process has exited.
    """
    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class FileTime(ctypes.Structure):
                _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            open_process.restype = wintypes.HANDLE
            get_process_times = kernel32.GetProcessTimes
            get_process_times.argtypes = (
                wintypes.HANDLE,
                ctypes.POINTER(FileTime),
                ctypes.POINTER(FileTime),
                ctypes.POINTER(FileTime),
                ctypes.POINTER(FileTime),
            )
            get_process_times.restype = wintypes.BOOL
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle.restype = wintypes.BOOL

            handle = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                created = FileTime()
                exited = FileTime()
                kernel = FileTime()
                user = FileTime()
                if not get_process_times(
                    handle,
                    ctypes.byref(created),
                    ctypes.byref(exited),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                ):
                    return None
                return (int(created.high) << 32) | int(created.low)
            finally:
                close_handle(handle)
        except (AttributeError, OSError, ValueError):
            return None

    try:
        # /proc/<pid>/stat's command can contain spaces and ')' characters,
        # so split after its final ')' before indexing fields after comm.
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        _prefix, separator, tail = stat.rpartition(")")
        if not separator:
            return None
        fields = tail.split()  # starts at field 3 (state)
        return int(fields[19])  # field 22: starttime
    except (OSError, UnicodeError, ValueError, IndexError):
        return None


class InterProcessFileLock:
    """OS-backed lock for work shared by sibling Python processes.

    The lock file is intentionally persistent. Kernel lock ownership is released
    when a process exits, so age-based unlinking is unnecessary and can evict a
    live owner during long-running work.
    """

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
                self._handle = self._try_acquire_os_lock()
                if self._handle is None:
                    raise BlockingIOError
                self._write_owner_metadata()
                return time.monotonic() - started
            except BlockingIOError:
                if self._handle is not None:
                    os.close(self._handle)
                    self._handle = None
                if time.monotonic() - started >= self.timeout_seconds:
                    raise TimeoutError(f"Timed out waiting for process lock: {self.path}")
                time.sleep(self.poll_interval_seconds)
            except Exception:
                if self._handle is not None:
                    os.close(self._handle)
                    self._handle = None
                raise

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._handle is not None:
            os.close(self._handle)
            self._handle = None

    def _try_acquire_os_lock(self) -> int | None:
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_file = kernel32.CreateFileW
            create_file.argtypes = (
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            )
            create_file.restype = wintypes.HANDLE
            handle = create_file(
                str(self.path),
                0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
                0,  # No sharing: only one process may own the lock file.
                None,
                4,  # OPEN_ALWAYS
                0x00000080,  # FILE_ATTRIBUTE_NORMAL
                None,
            )
            if handle == ctypes.c_void_p(-1).value:
                error = ctypes.get_last_error()
                if error in (32, 33):  # Sharing or lock violation.
                    return None
                raise ctypes.WinError(error)
            try:
                return msvcrt.open_osfhandle(
                    int(handle), os.O_RDWR | os.O_BINARY,
                )
            except Exception:
                kernel32.CloseHandle(handle)
                raise

        import fcntl

        descriptor = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            return None
        return descriptor

    def _write_owner_metadata(self) -> None:
        if self._handle is None:
            raise RuntimeError("Process lock was not acquired")
        payload = {
            "pid": os.getpid(),
            "threadId": threading.get_ident(),
            "stage": self.stage,
            "createdAt": time.time(),
        }
        encoded = json.dumps(payload).encode("utf-8")
        os.lseek(self._handle, 0, os.SEEK_SET)
        os.ftruncate(self._handle, 0)
        os.write(self._handle, encoded)
        os.fsync(self._handle)


def interprocess_lock_is_stale(path: Path, *, stale_after_seconds: float) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return lock_age_seconds(path) > stale_after_seconds
    pid = payload.get("pid") if isinstance(payload, dict) else None
    if isinstance(pid, int) and pid > 0:
        # A live process owns its critical section regardless of lock age.
        # Timeouts bound how long a waiter waits; they do not revoke ownership.
        return not process_is_running(pid)
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
