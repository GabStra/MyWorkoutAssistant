"""Shared GVHMR process, admission-lock and warm-worker lifecycle utilities."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from exercise_motion_pkg.gpu_lock import (
    open_lock_lease, close_lock_lease, read_lock_text, lock_open_is_contention,
    process_identity, lock_lease_acquisition_guard,
)

DEFAULT_RECONSTRUCTION_DOCKER_IMAGE = "myworkoutassistant/gvhmr:torch2.3-cu121"
DEFAULT_RECONSTRUCTION_DOCKER_SHM_SIZE = "8g"
DEFAULT_RECONSTRUCTION_BODY_MODEL_ROOT = (
    Path(__file__).resolve().parents[1] / "third_party" / "GVHMR"
    / "inputs" / "checkpoints" / "body_models"
)
DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS = 20 * 60.0
RECONSTRUCTION_DOCKER_LOCK_ENV_VAR = "EXERCISE_MOTION_RECONSTRUCTION_DOCKER_LOCK"
RECONSTRUCTION_DOCKER_LOCK_TIMEOUT_SECONDS_ENV_VAR = "EXERCISE_MOTION_RECONSTRUCTION_DOCKER_LOCK_TIMEOUT_SECONDS"
DEFAULT_RECONSTRUCTION_DOCKER_LOCK_TIMEOUT_SECONDS = 6 * 60 * 60
RECONSTRUCTION_WARM_WORKER_HEARTBEAT_STALE_SECONDS = 30.0


def ensure_warm_worker_ready(
    session_dir: Path,
    *,
    timeout_seconds: float,
    deadline: float | None = None,
    lazy_start_env_var: str = "EXERCISE_MOTION_RECONSTRUCTION_LAZY_START",
    label: str = "GVHMR",
) -> None:
    """Ask the supervising wrapper to start the worker only on a cache miss."""
    if deadline is None:
        from exercise_motion_pkg.motion_scheduler import current_gpu_stage_deadline

        deadline = current_gpu_stage_deadline()
    if deadline is not None:
        remaining = deadline - time.perf_counter()
        if remaining <= 0.0:
            raise TimeoutError(f"Candidate deadline expired before supervised {label} worker readiness.")
        timeout_seconds = min(timeout_seconds, remaining)
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
    startup_deadline = time.perf_counter() + timeout_seconds
    if deadline is not None:
        startup_deadline = min(startup_deadline, deadline)
    try:
        while time.perf_counter() < startup_deadline:
            # The supervisor removes the request only after successful startup.
            if not request_path.exists() and ready_path.exists():
                assert_warm_worker_heartbeat(session_dir / "heartbeat.json")
                return
            time.sleep(min(0.25, max(0.0, startup_deadline - time.perf_counter())))
        raise TimeoutError(f"Timed out waiting for supervised {label} worker startup")
    finally:
        request_path.unlink(missing_ok=True)



def run_reconstruction_process(
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
            f"GVHMR run exceeded the {timeout_seconds:.0f}s timeout. "
            f"Logs may contain partial output for command: {' '.join(command)}"
        ) from exc



def path_inside_worker_mount(path: Path, *, mount_root: Path) -> str:
    resolved_path = path.expanduser().resolve()
    resolved_root = mount_root.expanduser().resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Path is outside the warm GVHMR worker mount root: {resolved_path} not under {resolved_root}") from exc
    return "/workspace" if str(relative) == "." else "/workspace/" + relative.as_posix()



def assert_warm_worker_heartbeat(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"Warm GVHMR worker heartbeat is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated_at = float(payload.get("updatedAtUnixSeconds") or 0.0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Warm GVHMR worker heartbeat is unreadable: {path}") from exc
    heartbeat_age = max(0.0, time.time() - updated_at)
    if heartbeat_age > RECONSTRUCTION_WARM_WORKER_HEARTBEAT_STALE_SECONDS:
        raise RuntimeError(
            "Warm GVHMR worker heartbeat became stale "
            f"({heartbeat_age:.1f}s old): {path}"
        )



def assert_warm_worker_available(session_dir: Path, *, label: str = "GVHMR") -> None:
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
            f"Timed out waiting for warm GVHMR worker result: {path}; "
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
                "Warm GVHMR worker stopped before producing the requested result: "
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
def reconstruction_docker_run_lock(*, enabled: bool, deadline: float | None = None):
    if not enabled:
        yield 0.0
        return

    if deadline is None:
        from exercise_motion_pkg.motion_scheduler import current_gpu_stage_deadline

        deadline = current_gpu_stage_deadline()

    lock_path = reconstruction_docker_lock_path()
    timeout_seconds = reconstruction_docker_lock_timeout_seconds()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    lock_handle: int | None = None
    while True:
        if deadline is not None and time.perf_counter() >= deadline:
            raise TimeoutError(f"Candidate deadline expired waiting for reconstruction Docker lock: {lock_path}")
        guard_timeout = timeout_seconds
        if deadline is not None:
            guard_timeout = min(
                guard_timeout,
                max(0.0, deadline - time.perf_counter()),
            )
        try:
            with lock_lease_acquisition_guard(
                lock_path,
                stage="reconstruction_docker_lock_admission",
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
                    if reconstruction_docker_lock_is_stale(lock_path, timeout_seconds=timeout_seconds):
                        try:
                            lock_path.unlink()
                            continue
                        except OSError:
                            pass
        except TimeoutError as error:
            if deadline is not None and time.perf_counter() >= deadline:
                raise TimeoutError(
                    f"Candidate deadline expired waiting for reconstruction Docker lock: {lock_path}"
                ) from error
            raise TimeoutError(f"Timed out waiting for reconstruction Docker lock: {lock_path}") from error
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
            raise TimeoutError(f"Timed out waiting for reconstruction Docker lock: {lock_path}")
        sleep_seconds = min(2.0, effective_timeout - elapsed)
        time.sleep(max(0.01, sleep_seconds))
    try:
        yield time.perf_counter() - started
    finally:
        if lock_handle is not None:
            close_lock_lease(lock_handle, lock_path)



def reconstruction_docker_lock_path() -> Path:
    configured = os.environ.get(RECONSTRUCTION_DOCKER_LOCK_ENV_VAR)
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / "myworkoutassistant-reconstruction-docker.lock"



def reconstruction_docker_lock_timeout_seconds() -> float:
    raw = os.environ.get(RECONSTRUCTION_DOCKER_LOCK_TIMEOUT_SECONDS_ENV_VAR)
    if raw is None:
        return float(DEFAULT_RECONSTRUCTION_DOCKER_LOCK_TIMEOUT_SECONDS)
    try:
        return max(1.0, float(raw))
    except ValueError:
        return float(DEFAULT_RECONSTRUCTION_DOCKER_LOCK_TIMEOUT_SECONDS)



def reconstruction_docker_lock_is_stale(lock_path: Path, *, timeout_seconds: float) -> bool:
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



