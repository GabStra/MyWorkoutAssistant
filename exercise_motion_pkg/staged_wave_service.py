"""Run staged-wave manifests through one queue-backed Python process."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import ctypes
import hashlib
import json
import os
import threading
import time
import traceback
from typing import Any, Callable

from exercise_motion_pkg.process_lock import process_identity
from exercise_motion_pkg.process_lock import InterProcessFileLock


SERVICE_SCHEMA_VERSION = 1
ADMISSION_LOCK_VERSION = 2
DEFAULT_IDLE_TIMEOUT_SECONDS = 10 * 60
AMBIGUOUS_RECOVERY_EXIT_CODE = 76
AMBIGUOUS_RECOVERY_STATUS = "ambiguous_recovery"
CONSUMED_RESULT_RETENTION_SECONDS = 14 * 24 * 60 * 60
UNCONSUMED_RESULT_RETENTION_SECONDS = 30 * 24 * 60 * 60
AMBIGUOUS_REQUEST_RETENTION_SECONDS = 90 * 24 * 60 * 60
CANCEL_MARKER_RETENTION_SECONDS = 30 * 24 * 60 * 60
MAX_RETAINED_CONSUMED_RESULTS = 512
MAX_RETAINED_CANCEL_MARKERS = 512
ADMISSION_MUTEX_NAME = r"Global\MyWorkoutAssistant.StagedWaveAdmission.v1"
ADMISSION_MUTEX_PREFIX = r"Global\MyWorkoutAssistant.StagedWaveAdmission.v2."


def _queue_admission_mutex_name(queue_root: Path) -> str:
    normalized_root = os.path.normpath(
        os.path.abspath(os.path.expanduser(os.fspath(queue_root)))
    ).replace("/", "\\").rstrip("\\")
    normalized_root = normalized_root.upper()
    digest = hashlib.sha256(normalized_root.encode("utf-8")).hexdigest()
    return f"{ADMISSION_MUTEX_PREFIX}{digest}"


def _queue_admission_lock_version(queue_root: Path) -> int:
    state_path = Path(queue_root) / "worker_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ADMISSION_LOCK_VERSION
    except (OSError, json.JSONDecodeError):
        # If ownership metadata is malformed, preserve the old shared lock
        # behavior rather than risking a race with an unidentified old worker.
        return 1
    if isinstance(state, dict) and state.get("admissionLockVersion") == ADMISSION_LOCK_VERSION:
        return ADMISSION_LOCK_VERSION
    return 1


def _queue_admission_mutex_names(
    queue_root: Path,
    *,
    include_legacy_compatibility: bool,
) -> list[str]:
    if _queue_admission_lock_version(queue_root) < ADMISSION_LOCK_VERSION:
        return [ADMISSION_MUTEX_NAME]
    queue_mutex = _queue_admission_mutex_name(queue_root)
    if include_legacy_compatibility:
        return [ADMISSION_MUTEX_NAME, queue_mutex]
    return [queue_mutex]


@contextmanager
def staged_wave_admission_lock(queue_root: Path):
    """Serialize request publication with the worker's idle-stop decision.

    The production PowerShell runner uses the same named mutex on Windows.
    POSIX service tests and non-Windows tools share an advisory file lock.
    The critical section only covers queue publication or final idle checks.
    """
    queue_root = Path(queue_root)
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        create_mutex.restype = ctypes.c_void_p
        wait_for_single_object = kernel32.WaitForSingleObject
        wait_for_single_object.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        wait_for_single_object.restype = ctypes.c_uint32
        release_mutex = kernel32.ReleaseMutex
        release_mutex.argtypes = (ctypes.c_void_p,)
        release_mutex.restype = ctypes.c_int
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (ctypes.c_void_p,)
        close_handle.restype = ctypes.c_int

        mutex_names = _queue_admission_mutex_names(
            queue_root,
            include_legacy_compatibility=True,
        )
        handles: list[tuple[ctypes.c_void_p, bool]] = []
        try:
            for mutex_name in mutex_names:
                handle = create_mutex(None, 0, mutex_name)
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                handles.append((handle, False))
                wait_result = wait_for_single_object(handle, 30_000)
                if wait_result in (0, 0x80):  # WAIT_OBJECT_0 or WAIT_ABANDONED
                    handles[-1] = (handle, True)
                elif wait_result == 0x102:  # WAIT_TIMEOUT
                    raise TimeoutError("Timed out waiting for staged-wave admission lock")
                else:
                    raise ctypes.WinError(ctypes.get_last_error())
            yield
        finally:
            for handle, acquired in reversed(handles):
                if acquired:
                    release_mutex(handle)
                close_handle(handle)
        return

    import fcntl

    lock_path = queue_root / "admission.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _execute_wave_request(
    request: dict[str, Any],
    *,
    render_executor: ThreadPoolExecutor,
) -> dict[str, Any]:
    from exercise_motion_pkg.cli import build_parser, run_staged_bake_wave_manifest

    arguments = request.get("arguments")
    if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
        raise ValueError("Staged-wave service request has no valid CLI arguments")
    args = build_parser().parse_args(arguments)
    if args.command != "bake-and-rank" or args.staged_wave_manifest is None:
        raise ValueError("Staged-wave service request must describe a bake-and-rank manifest")
    report = run_staged_bake_wave_manifest(
        args,
        progress=lambda message: print(message, flush=True),
        render_executor=render_executor,
    )
    manifest_path = args.staged_wave_manifest.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wave_workspace = Path(manifest.get("workspace") or manifest_path.parent)
    return {
        "reportPath": str((wave_workspace / "staged_wave_report.json").resolve()),
        "report": report,
    }


def _request_run_id(payload: dict[str, Any]) -> str:
    return str(payload.get("runId") or "")


def _request_id(payload: dict[str, Any], filename_stem: str) -> str:
    request_id = str(payload.get("requestId") or filename_stem)
    if not request_id or request_id != filename_stem:
        raise ValueError("Staged-wave request ID does not match its queue filename")
    return request_id


def _request_enqueued_order(path: Path) -> tuple[int, str]:
    """Order modern requests by enqueue time, with filesystem time for legacy jobs."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        enqueued_at = payload.get("enqueuedAtUnixNs") if isinstance(payload, dict) else None
        if type(enqueued_at) is int and enqueued_at > 0:
            return enqueued_at, path.name
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    try:
        modified_at = path.stat().st_mtime_ns
    except OSError:
        modified_at = 0
    return modified_at, path.name


def _publish_result(
    results: Path,
    *,
    request_id: str,
    wave_id: str,
    exit_code: int,
    report_path: str | None = None,
    error: str | None = None,
    elapsed_seconds: float = 0.0,
    status: str | None = None,
) -> None:
    _write_json_atomic(
        results / f"{request_id}.json",
        {
            "schemaVersion": SERVICE_SCHEMA_VERSION,
            "requestId": request_id,
            "waveId": wave_id,
            "exitCode": exit_code,
            "status": status or ("completed" if exit_code == 0 else "failed"),
            "elapsedSeconds": round(elapsed_seconds, 3),
            "reportPath": report_path,
            "error": error,
        },
    )


def _prune_aged_records(
    directory: Path,
    *,
    now_epoch: float,
    retention_seconds: int,
    max_count: int | None,
    protected_stems: set[str] | None = None,
) -> int:
    """Apply age and optional count limits to records in one terminal directory."""
    protected_stems = protected_stems or set()
    records: list[tuple[float, Path]] = []
    for path in directory.glob("*.json"):
        if path.stem in protected_stems:
            continue
        try:
            records.append((path.stat().st_mtime, path))
        except OSError:
            # An unstatable record is retained; cleanup must fail safe.
            continue
    records.sort(key=lambda record: (record[0], record[1].name))
    cutoff = now_epoch - max(0, int(retention_seconds))
    expired = {path for modified_at, path in records if modified_at < cutoff}
    retained = [(modified_at, path) for modified_at, path in records if path not in expired]
    if max_count is not None:
        excess_count = max(0, len(retained) - max(0, int(max_count)))
        expired.update(path for _, path in retained[:excess_count])

    removed = 0
    for path in expired:
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed


def _prune_staged_wave_records(queue_root: Path, *, now_epoch: float | None = None) -> dict[str, int]:
    """Prune expired terminal records and safe-to-forget cancellation markers.

    Requests and processing records protect their run's cancellation marker.
    If either queue contains an unreadable request, marker pruning is skipped
    because its run identity cannot be established. Results remain available
    for 30 days for a delayed waiter; ambiguous crash records remain available
    for 90 days for recovery inspection.
    """
    now = time.time() if now_epoch is None else float(now_epoch)
    consumed = queue_root / "consumed"
    results = queue_root / "results"
    ambiguous = queue_root / "ambiguous"
    cancelled_runs = queue_root / "cancelled_runs"
    consumed_pruned = _prune_aged_records(
        consumed,
        now_epoch=now,
        retention_seconds=CONSUMED_RESULT_RETENTION_SECONDS,
        max_count=MAX_RETAINED_CONSUMED_RESULTS,
    )
    unconsumed_pruned = _prune_aged_records(
        results,
        now_epoch=now,
        retention_seconds=UNCONSUMED_RESULT_RETENTION_SECONDS,
        max_count=None,
    )
    ambiguous_pruned = _prune_aged_records(
        ambiguous,
        now_epoch=now,
        retention_seconds=AMBIGUOUS_REQUEST_RETENTION_SECONDS,
        max_count=None,
    )

    protected_run_ids: set[str] = set()
    queue_state_known = True
    for directory_name in ("requests", "processing"):
        directory = queue_root / directory_name
        for request_path in directory.glob("*.json"):
            try:
                request = json.loads(request_path.read_text(encoding="utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("request payload is not an object")
                run_id = _request_run_id(request)
                if run_id:
                    protected_run_ids.add(run_id)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                queue_state_known = False
                break
        if not queue_state_known:
            break

    cancelled_pruned = 0
    if queue_state_known:
        cancelled_pruned = _prune_aged_records(
            cancelled_runs,
            now_epoch=now,
            retention_seconds=CANCEL_MARKER_RETENTION_SECONDS,
            max_count=MAX_RETAINED_CANCEL_MARKERS,
            protected_stems=protected_run_ids,
        )
    return {
        "consumedResults": consumed_pruned,
        "unconsumedResults": unconsumed_pruned,
        "ambiguousRequests": ambiguous_pruned,
        "cancelledRuns": cancelled_pruned,
    }


def run_staged_wave_service(
    queue_root: Path,
    *,
    execute_wave: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    poll_interval_seconds: float = 0.2,
    max_wave_items: int = 1,
    idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
    source_identity_fingerprint: str | None = None,
    service_configuration_fingerprint: str | None = None,
) -> int:
    """Consume queued requests under a singleton lease until idle timeout."""
    queue_root = Path(queue_root).expanduser().resolve()
    if idle_timeout_seconds <= 0:
        raise ValueError("Staged-wave service idle timeout must be positive")
    queue_root.mkdir(parents=True, exist_ok=True)
    service_lease = InterProcessFileLock(
        queue_root / "worker.lock",
        stage="staged_wave_service",
        timeout_seconds=0,
        stale_after_seconds=0,
    )
    with service_lease:
        return _run_staged_wave_service_locked(
            queue_root,
            execute_wave=execute_wave,
            poll_interval_seconds=poll_interval_seconds,
            max_wave_items=max_wave_items,
            idle_timeout_seconds=idle_timeout_seconds,
            source_identity_fingerprint=source_identity_fingerprint,
            service_configuration_fingerprint=service_configuration_fingerprint,
        )


def _run_staged_wave_service_locked(
    queue_root: Path,
    *,
    execute_wave: Callable[[dict[str, Any]], dict[str, Any]] | None,
    poll_interval_seconds: float,
    max_wave_items: int,
    idle_timeout_seconds: float,
    source_identity_fingerprint: str | None,
    service_configuration_fingerprint: str | None,
) -> int:
    requests = queue_root / "requests"
    processing = queue_root / "processing"
    results = queue_root / "results"
    consumed = queue_root / "consumed"
    ambiguous = queue_root / "ambiguous"
    cancelled_runs = queue_root / "cancelled_runs"
    state_path = queue_root / "worker_state.json"
    stop_path = queue_root / "stop.request"
    for directory in (requests, processing, results, consumed, ambiguous, cancelled_runs):
        directory.mkdir(parents=True, exist_ok=True)
    for claimed_path in processing.glob("*.json"):
        result_path = results / claimed_path.name
        request_path = requests / claimed_path.name
        if result_path.exists():
            claimed_path.unlink(missing_ok=True)
        elif request_path.exists():
            claimed_path.unlink(missing_ok=True)
        else:
            try:
                recovered_request = json.loads(claimed_path.read_text(encoding="utf-8"))
                if not isinstance(recovered_request, dict):
                    raise ValueError("request payload is not an object")
                request_id = _request_id(recovered_request, claimed_path.stem)
                wave_id = str(recovered_request.get("waveId") or "")
                if not wave_id:
                    raise ValueError("request has no wave ID")
                recovery_error = (
                    "The previous staged-wave service stopped while this request was running. "
                    "Completion is ambiguous, so it was retained for inspection and not replayed."
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                request_id = claimed_path.stem
                wave_id = "unknown"
                recovery_error = f"Staged-wave request recovery could not verify the claimed job: {exc}"
            _publish_result(
                results,
                request_id=request_id,
                wave_id=wave_id,
                exit_code=AMBIGUOUS_RECOVERY_EXIT_CODE,
                error=recovery_error,
                status=AMBIGUOUS_RECOVERY_STATUS,
            )
            os.replace(claimed_path, ambiguous / claimed_path.name)
    stop_path.unlink(missing_ok=True)
    _prune_staged_wave_records(queue_root)

    state_lock = threading.Lock()
    state_publish_lock = threading.Lock()
    state: dict[str, Any] = {
        "schemaVersion": SERVICE_SCHEMA_VERSION,
        "admissionLockVersion": ADMISSION_LOCK_VERSION,
        "queueRoot": str(queue_root),
        "sourceIdentityFingerprint": source_identity_fingerprint,
        "serviceConfigurationFingerprint": service_configuration_fingerprint,
        "pid": os.getpid(),
        "processIdentity": process_identity(os.getpid()),
        "status": "idle",
        "currentWaveId": None,
        "updatedAtEpoch": time.time(),
    }
    heartbeat_stop = threading.Event()

    def update_state(*, publish: bool = False, **changes: Any) -> None:
        with state_lock:
            state.update(changes)
            state["updatedAtEpoch"] = time.time()
        if publish:
            write_state_snapshot()

    def write_state_snapshot() -> None:
        # Serialize heartbeat and lifecycle writes so an older heartbeat
        # cannot overwrite the stopping/stopped transition.
        with state_publish_lock:
            with state_lock:
                snapshot = dict(state)
                snapshot["updatedAtEpoch"] = time.time()
            _write_json_atomic(state_path, snapshot)

    def heartbeat() -> None:
        while not heartbeat_stop.is_set():
            try:
                write_state_snapshot()
            except OSError:
                # The service continues only while its run workspace remains writable.
                pass
            heartbeat_stop.wait(1.0)

    heartbeat_thread = threading.Thread(
        target=heartbeat,
        name="staged-wave-service-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()
    from exercise_motion_pkg.resource_budget import render_prefetch_worker_limit

    render_executor = ThreadPoolExecutor(
        max_workers=render_prefetch_worker_limit(max(1, int(max_wave_items))),
        thread_name_prefix="motion-render-prefetch-service",
    )
    executor = execute_wave or (
        lambda request: _execute_wave_request(request, render_executor=render_executor)
    )
    processed_count = 0
    idle_since = time.monotonic()
    try:
        while True:
            request_paths = sorted(requests.glob("*.json"), key=_request_enqueued_order)
            if not request_paths:
                stop_requested = stop_path.exists()
                idle_expired = time.monotonic() - idle_since >= idle_timeout_seconds
                if stop_requested or idle_expired:
                    # Producers hold this same OS-level admission lock while
                    # publishing. Mark stopping before releasing the lock, and
                    # recheck the queue under the lock, so a producer either
                    # publishes first (and we keep serving) or observes the
                    # stopping worker and starts/reuses a fresh one.
                    with staged_wave_admission_lock(queue_root):
                        request_paths = sorted(
                            requests.glob("*.json"),
                            key=_request_enqueued_order,
                        )
                        if not request_paths:
                            stop_requested = stop_path.exists()
                            idle_expired = (
                                time.monotonic() - idle_since >= idle_timeout_seconds
                            )
                            if stop_requested or idle_expired:
                                update_state(
                                    status="stopping",
                                    currentRequestId=None,
                                    currentWaveId=None,
                                )
                                write_state_snapshot()
                                break
                    if not request_paths:
                        continue
                else:
                    time.sleep(max(0.01, poll_interval_seconds))
                    continue
            for request_path in request_paths:
                claimed_path = processing / request_path.name
                try:
                    os.replace(request_path, claimed_path)
                except FileNotFoundError:
                    continue
                wave_id = request_path.stem
                result_path = results / f"{wave_id}.json"
                if result_path.exists():
                    claimed_path.unlink(missing_ok=True)
                    request_path.unlink(missing_ok=True)
                    continue
                started = time.perf_counter()
                request_payload: dict[str, Any] = {}
                error_message = None
                execution_result: dict[str, Any] = {}
                execution_completed_successfully = False
                update_state(status="running", currentRequestId=wave_id, currentWaveId=None)
                log_path = None
                try:
                    decoded_request = json.loads(claimed_path.read_text(encoding="utf-8"))
                    if not isinstance(decoded_request, dict):
                        raise ValueError("Staged-wave service request must be a JSON object")
                    request_payload = decoded_request
                    request_id = _request_id(request_payload, wave_id)
                    wave_id_value = str(request_payload.get("waveId") or "")
                    if not wave_id_value:
                        raise ValueError("Staged-wave request has no wave ID")
                    # The PowerShell supervisor checks this durable field before
                    # stopping shared model services. Publish synchronously
                    # before the executor can enter model/render work; the
                    # periodic heartbeat alone leaves a shutdown race window.
                    update_state(
                        currentRequestId=request_id,
                        currentWaveId=wave_id_value,
                        publish=True,
                    )
                    log_path_value = request_payload.get("logPath")
                    log_path = Path(str(log_path_value)) if log_path_value else None
                    run_id = _request_run_id(request_payload)
                    if (
                        source_identity_fingerprint is not None
                        and request_payload.get("sourceIdentityFingerprint")
                        != source_identity_fingerprint
                    ):
                        error_message = (
                            "Staged-wave request source identity does not match the "
                            "loaded service code; request was not executed."
                        )
                    elif (
                        service_configuration_fingerprint is not None
                        and request_payload.get("serviceConfigurationFingerprint")
                        != service_configuration_fingerprint
                    ):
                        error_message = (
                            "Staged-wave request runtime configuration does not match "
                            "the loaded service; request was not executed."
                        )
                    elif run_id and (cancelled_runs / f"{run_id}.json").exists():
                        error_message = "Motion run was cancelled before this wave started."
                    else:
                        if log_path is None:
                            execution_result = executor(request_payload)
                        else:
                            log_path.parent.mkdir(parents=True, exist_ok=True)
                            with log_path.open("a", encoding="utf-8", newline="\n") as log_stream:
                                with redirect_stdout(log_stream), redirect_stderr(log_stream):
                                    execution_result = executor(request_payload)
                        execution_completed_successfully = True
                except BaseException as exc:
                    error_message = f"{type(exc).__name__}: {exc}"
                    if log_path is not None:
                        try:
                            with log_path.open("a", encoding="utf-8", newline="\n") as log_stream:
                                traceback.print_exc(file=log_stream)
                        except OSError:
                            pass
                finally:
                    elapsed = time.perf_counter() - started
                    try:
                        request_id = _request_id(request_payload, wave_id)
                    except (TypeError, ValueError):
                        request_id = wave_id
                    result_wave_id = (
                        str(request_payload.get("waveId") or wave_id)
                        if isinstance(request_payload, dict)
                        else wave_id
                    )
                    request_run_id = (
                        _request_run_id(request_payload)
                        if isinstance(request_payload, dict)
                        else ""
                    )
                    cancelled_without_successful_execution = bool(
                        request_run_id
                        and not execution_completed_successfully
                        and (cancelled_runs / f"{request_run_id}.json").exists()
                    )
                    _publish_result(
                        results,
                        request_id=request_id,
                        wave_id=result_wave_id,
                        exit_code=(
                            130
                            if cancelled_without_successful_execution
                            else (1 if error_message else 0)
                        ),
                        report_path=execution_result.get("reportPath"),
                        error=error_message,
                        elapsed_seconds=elapsed,
                        status=(
                            "cancelled"
                            if cancelled_without_successful_execution
                            else "failed"
                            if error_message
                            else "completed"
                        ),
                    )
                    claimed_path.unlink(missing_ok=True)
                    processed_count += 1
                    idle_since = time.monotonic()
                    update_state(status="idle", currentRequestId=None, currentWaveId=None)
                    _prune_staged_wave_records(queue_root)
    finally:
        update_state(
            status="stopped",
            currentRequestId=None,
            currentWaveId=None,
            processedRequestCount=processed_count,
        )
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2.0)
        render_executor.shutdown(wait=True)
        try:
            write_state_snapshot()
        except OSError:
            pass
    return processed_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue-backed staged-wave worker service")
    parser.add_argument("--queue-root", required=True, type=Path)
    parser.add_argument("--max-wave-items", type=int, default=1)
    parser.add_argument(
        "--idle-timeout-seconds",
        type=float,
        default=DEFAULT_IDLE_TIMEOUT_SECONDS,
    )
    parser.add_argument("--source-identity-fingerprint", default="")
    parser.add_argument("--service-configuration-fingerprint", default="")
    args = parser.parse_args()
    processed = run_staged_wave_service(
        args.queue_root,
        max_wave_items=args.max_wave_items,
        idle_timeout_seconds=args.idle_timeout_seconds,
        source_identity_fingerprint=args.source_identity_fingerprint or None,
        service_configuration_fingerprint=(
            args.service_configuration_fingerprint or None
        ),
    )
    print(f"Staged-wave service stopped after {processed} waves.", flush=True)


if __name__ == "__main__":
    main()
