"""Run staged-wave manifests through one queue-backed Python process."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import copy_context
from exercise_motion_pkg.request_logging import route_request_logs, request_log
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import ctypes
import hashlib
import json
import os
import sys
import threading
import time
import traceback
import uuid
from typing import Any, Callable

from exercise_motion_pkg.process_lock import process_identity
from exercise_motion_pkg.process_lock import InterProcessFileLock


SERVICE_SCHEMA_VERSION = 1
ADMISSION_LOCK_VERSION = 2
DEFAULT_IDLE_TIMEOUT_SECONDS = 10 * 60
STALLED_OPERATION_GRACE_SECONDS = 10.0
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


class WaveGpuGate:
    """Share a wave's VLM slots; serialize extraction and prefer ready reviews."""

    def __init__(self):
        self.condition = threading.Condition()
        self.owner = None
        self.users = 0
        self.review_waiters = 0
        self._lanes = {"__global__": {"owner": None, "users": 0, "review_waiters": 0}}

    @contextmanager
    def phase(self, wave_id, stage, cancelled=lambda: False, *, deadline=None, gpu_lane=None):
        if stage == "cpu_preparation":
            yield cancelled
            return
        def check_deadline():
            if deadline is not None and time.perf_counter() >= deadline:
                from .bake_and_rank import CandidateWallTimeBudgetExpired
                raise CandidateWallTimeBudgetExpired("Candidate budget expired waiting for the GPU")

        key = (wave_id, stage)
        review = stage == "final_review"
        lane_name = str(gpu_lane) if gpu_lane is not None else "__global__"
        queued_at = time.perf_counter()
        next_wait_log = queued_at + 5.0
        with self.condition:
            lane = self._lanes.setdefault(
                lane_name, {"owner": None, "users": 0, "review_waiters": 0}
            )
            if review:
                lane["review_waiters"] += 1
                if lane_name == "__global__":
                    self.review_waiters += 1
            try:
                while True:
                    global_lane = self._lanes["__global__"]
                    other_named_lanes_busy = any(
                        name != "__global__" and state["users"] > 0
                        for name, state in self._lanes.items()
                    )
                    exclusive_conflict = (
                        other_named_lanes_busy
                        if lane_name == "__global__"
                        else global_lane["users"] > 0 or global_lane["review_waiters"] > 0
                    )
                    review_waiters = (
                        sum(state["review_waiters"] for state in self._lanes.values())
                        if lane_name == "__global__"
                        else lane["review_waiters"] + global_lane["review_waiters"]
                    )
                    same_lane_conflict = lane["owner"] is not None and not (
                        review and lane["owner"] == key
                    )
                    if not same_lane_conflict and not exclusive_conflict and (review or not review_waiters):
                        break
                    if cancelled():
                        raise KeyboardInterrupt("Motion run was cancelled waiting for the GPU")
                    check_deadline()
                    if time.perf_counter() >= next_wait_log:
                        print(json.dumps({"event": "wave_gpu_admission_wait", "waveId": wave_id,
                                          "requestedPhase": stage, "gpuLane": gpu_lane,
                                          "owner": lane["owner"],
                                          "reviewWaiters": lane["review_waiters"],
                                          "waitSeconds": round(time.perf_counter() - queued_at, 3)}), flush=True)
                        next_wait_log = time.perf_counter() + 5.0
                    self.condition.wait(timeout=0.25)
                check_deadline()
                if cancelled():
                    raise KeyboardInterrupt("Motion run was cancelled before the next GPU phase")
                lane["owner"] = key
                lane["users"] += 1
                if lane_name == "__global__":
                    self.owner = lane["owner"]
                    self.users = lane["users"]
            finally:
                if review:
                    lane["review_waiters"] -= 1
                    if lane_name == "__global__":
                        self.review_waiters -= 1
                self.condition.notify_all()
        try:
            yield
        finally:
            with self.condition:
                lane["users"] -= 1
                if not lane["users"]:
                    lane["owner"] = None
                if lane_name == "__global__":
                    self.users = lane["users"]
                    self.owner = lane["owner"]
                self.condition.notify_all()


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
    for attempt in range(25):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            # Windows readers can briefly hold the destination during replacement.
            if attempt == 24:
                raise
            time.sleep(0.02)


def _execute_wave_request(
    request: dict[str, Any],
    *,
    render_executor: ThreadPoolExecutor,
    accelerator_phase=None,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    from exercise_motion_pkg.cli import build_parser, run_staged_bake_wave_manifest

    arguments = request.get("arguments")
    if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
        raise ValueError("Staged-wave service request has no valid CLI arguments")
    args = build_parser().parse_args(arguments)
    if args.command != "bake-and-rank" or args.staged_wave_manifest is None:
        raise ValueError("Staged-wave service request must describe a bake-and-rank manifest")
    def report_progress(message: str) -> None:
        print(message, flush=True)
        if on_progress is not None:
            on_progress(str(message))

    report = run_staged_bake_wave_manifest(
        args,
        progress=report_progress,
        render_executor=render_executor,
        accelerator_phase=accelerator_phase,
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
    recover_only: bool = False,
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
    with service_lease, route_request_logs():
        return _run_staged_wave_service_locked(
            queue_root,
            execute_wave=execute_wave,
            recover_only=recover_only,
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
    recover_only: bool,
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
    recovery_paths = list(processing.glob("*.json"))
    for pending_path in requests.glob("*.json"):
        try:
            pending_request = json.loads(pending_path.read_text(encoding="utf-8"))
            run_id = _request_run_id(pending_request) if isinstance(pending_request, dict) else ""
            if run_id and (cancelled_runs / f"{run_id}.json").is_file():
                recovery_paths.append(pending_path)
        except (OSError, ValueError, TypeError):
            continue
    for claimed_path in recovery_paths:
        result_path = results / claimed_path.name
        request_path = requests / claimed_path.name
        if result_path.exists():
            claimed_path.unlink(missing_ok=True)
        elif claimed_path.parent == processing and request_path.exists():
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
                run_id = _request_run_id(recovered_request)
                if run_id and (cancelled_runs / f"{run_id}.json").is_file():
                    _publish_result(
                        results,
                        request_id=request_id,
                        wave_id=wave_id,
                        exit_code=130,
                        error="The motion run was cancelled before service recovery; this request was not replayed.",
                        status="cancelled",
                    )
                    _write_json_atomic(
                        consumed / f"{request_id}.request.json",
                        recovered_request,
                    )
                    claimed_path.unlink(missing_ok=True)
                    continue
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
    if recover_only:
        return 0
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

    def capture_expired_operation_stacks() -> None:
        now_epoch = time.time()
        with state_lock:
            active = [dict(value) for value in active_requests.values()]
        for entry in active:
            checkpoint_path = entry.get("checkpointPath")
            source_activities = []
            checkpoint_stage = None
            if checkpoint_path:
                try:
                    checkpoint = json.loads(Path(checkpoint_path).read_text(encoding="utf-8"))
                    checkpoint_stage = checkpoint.get("stage")
                    for item_state in checkpoint.get("items", []):
                        activity = item_state.get("sourceActivity")
                        if isinstance(activity, dict):
                            deadline = activity.get("operationDeadlineEpoch")
                            if isinstance(deadline, (int, float)) and deadline > 0:
                                source_activities.append({
                                    "deadlineEpoch": float(deadline),
                                    "exerciseName": item_state.get("exerciseName"),
                                    "operation": activity.get("operation"),
                                    "videoId": activity.get("videoId"),
                                    "candidateKey": activity.get("candidateKey"),
                                    "threadId": activity.get("threadId"),
                                })
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pass
            active_phase_deadlines = list((entry.get("activeDeadlines") or {}).values())
            known_deadlines = [
                *[
                    {**deadline, "owner": "accelerator_phase"}
                    for deadline in active_phase_deadlines
                ],
                *[
                    {**activity, "owner": "source_activity_checkpoint"}
                    for activity in source_activities
                ],
            ]
            known_deadlines.sort(key=lambda value: float(value["deadlineEpoch"]))
            earliest_deadline = known_deadlines[0] if known_deadlines else None
            with state_lock:
                current = active_requests.get(str(entry.get("requestId")))
                if current is not None:
                    current["sourceActivities"] = source_activities
                    if earliest_deadline:
                        current["operationDeadlineEpoch"] = earliest_deadline["deadlineEpoch"]
                        current["operationDeadlineSource"] = earliest_deadline["owner"]
                        current["phase"] = checkpoint_stage or current.get("phase")
                        current["lastProgress"] = (
                            f"{earliest_deadline.get('exerciseName', '')}: {earliest_deadline.get('operation', current.get('phase'))}"
                        )[:1000]
                        if current.get("stallDiagnosticDeadlineEpoch") != earliest_deadline["deadlineEpoch"]:
                            current.pop("stallDiagnosticPath", None)
                            current.pop("stallDiagnosticError", None)
                            current.pop("operationDeadlineExceededAtEpoch", None)
                            current.pop("stallDiagnosticDeadlineEpoch", None)
                            stalled = state.get("stalledOperation")
                            if isinstance(stalled, dict) and stalled.get("requestId") == entry.get("requestId"):
                                state.pop("stalledOperation", None)
                    else:
                        current.pop("operationDeadlineEpoch", None)
                        current.pop("operationDeadlineSource", None)
                        current.pop("stallDiagnosticPath", None)
                        current.pop("stallDiagnosticError", None)
                        current.pop("operationDeadlineExceededAtEpoch", None)
                        current.pop("stallDiagnosticDeadlineEpoch", None)
                        stalled = state.get("stalledOperation")
                        if isinstance(stalled, dict) and stalled.get("requestId") == entry.get("requestId"):
                            state.pop("stalledOperation", None)
            publish_active_state()
            deadline_epoch = earliest_deadline.get("deadlineEpoch") if earliest_deadline else None
            if (
                not isinstance(deadline_epoch, (int, float))
                or now_epoch < float(deadline_epoch) + STALLED_OPERATION_GRACE_SECONDS
                or entry.get("stallDiagnosticPath")
            ):
                continue
            frames = sys._current_frames()
            stacks = []
            for thread in threading.enumerate():
                frame = frames.get(thread.ident)
                if frame is None:
                    continue
                stacks.append({
                    "threadName": thread.name,
                    "threadId": thread.ident,
                    "stack": traceback.format_list(traceback.extract_stack(frame)),
                })
            diagnostic_path = queue_root / "diagnostics" / (
                f"expired-operation-{entry.get('requestId')}-{int(now_epoch)}.json"
            )
            diagnostic = {
                "requestId": entry.get("requestId"),
                "waveId": entry.get("waveId"),
                "runId": entry.get("runId"),
                "phase": entry.get("phase"),
                "operation": entry.get("lastProgress"),
                "operationStartedAtEpoch": entry.get("operationStartedAtEpoch"),
                "operationDeadlineEpoch": deadline_epoch,
                "activeDeadlines": known_deadlines,
                "sourceActivities": source_activities,
                "capturedAtEpoch": now_epoch,
                "threads": stacks,
            }
            try:
                _write_json_atomic(diagnostic_path, diagnostic)
                diagnostic_error = None
            except OSError as exc:
                diagnostic_error = f"{type(exc).__name__}: {exc}"
            with state_lock:
                current = active_requests.get(str(entry.get("requestId")))
                if current is not None:
                    current["stallDiagnosticPath"] = str(diagnostic_path)
                    current["stallDiagnosticError"] = diagnostic_error
                    current["operationDeadlineExceededAtEpoch"] = now_epoch
                    current["stallDiagnosticDeadlineEpoch"] = deadline_epoch
            with state_lock:
                state["stalledOperation"] = {
                    "requestId": entry.get("requestId"),
                    "waveId": entry.get("waveId"),
                    "deadlineEpoch": deadline_epoch,
                    "detectedAtEpoch": now_epoch,
                    "diagnosticPath": str(diagnostic_path),
                    "diagnosticError": diagnostic_error,
                }
            publish_active_state()

    def heartbeat() -> None:
        while not heartbeat_stop.is_set():
            try:
                capture_expired_operation_stacks()
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
    from exercise_motion_pkg.resource_budget import render_prefetch_worker_limit

    render_executor = ThreadPoolExecutor(
        max_workers=render_prefetch_worker_limit(max(1, int(max_wave_items))),
        thread_name_prefix="motion-render-prefetch-service",
    )
    processed_count = 0
    idle_since = time.monotonic()
    active_requests: dict[str, dict[str, Any]] = {}
    gpu_gate = WaveGpuGate()
    gpu_lease_count = 0
    gpu_owner = None

    def publish_active_state():
        with state_lock:
            active = [dict(value) for value in active_requests.values()]
            current = gpu_owner or (active[0] if active else {})
            state.update(
                status="running" if active else "idle",
                currentRequestId=current.get("requestId"),
                currentWaveId=current.get("waveId"),
                gpuOwnerWaveId=gpu_owner.get("waveId") if gpu_owner else None,
                activeRequests=active,
            )
        write_state_snapshot()

    heartbeat_thread.start()

    def process_request(claimed_path):
        try:
            return process_claimed_request(claimed_path)
        finally:
            with state_lock:
                active_requests.pop(claimed_path.stem, None)
                stalled = state.get("stalledOperation")
                if isinstance(stalled, dict) and stalled.get("requestId") == claimed_path.stem:
                    state.pop("stalledOperation", None)
            publish_active_state()

    def process_claimed_request(claimed_path):
        request_key = claimed_path.stem

        def record_progress(message: str) -> None:
            with state_lock:
                entry = active_requests.get(request_key)
                if entry is not None:
                    entry["lastProgress"] = message[:1000]
                    entry["lastProgressAtEpoch"] = time.time()
            publish_active_state()

        @contextmanager
        def accelerator_phase(wave_id, stage, *, deadline=None, gpu_lane=None):
            nonlocal gpu_owner, gpu_lease_count
            operation_started_at = time.time()
            with state_lock:
                entry = active_requests[request_key]
                run_id = entry.get("runId")
                active_deadline = (
                    {
                        "deadlineEpoch": time.time() + max(0.0, float(deadline) - time.perf_counter()),
                        "stage": stage,
                        "startedAtEpoch": operation_started_at,
                        "threadId": threading.get_ident(),
                    }
                    if deadline is not None
                    else None
                )
                deadline_token = uuid.uuid4().hex
                if active_deadline is not None:
                    entry.setdefault("activeDeadlines", {})[deadline_token] = active_deadline
                if gpu_owner is None or gpu_owner.get("requestId") != request_key:
                    entry["phase"] = stage if stage == "cpu_preparation" else "waiting_gpu"
                    entry["waitingForPhase"] = stage
                    entry["operationStartedAtEpoch"] = operation_started_at
            publish_active_state()
            cancelled = lambda: bool(run_id and (cancelled_runs / f"{run_id}.json").exists())
            try:
                with gpu_gate.phase(
                    wave_id, stage, cancelled, deadline=deadline, gpu_lane=gpu_lane,
                ):
                    if stage == "cpu_preparation":
                        yield cancelled
                        return
                    with state_lock:
                        entry.pop("waitingForPhase", None)
                        entry["phase"] = stage
                        gpu_lease_count += 1
                        gpu_owner = dict(entry)
                    publish_active_state()
                    try:
                        yield
                    finally:
                        with state_lock:
                            gpu_lease_count -= 1
                            if not gpu_lease_count:
                                entry["phase"] = "cpu_preparation"
                                gpu_owner = None
                        publish_active_state()
            finally:
                with state_lock:
                    active_deadlines = entry.get("activeDeadlines")
                    if active_deadlines is not None:
                        active_deadlines.pop(deadline_token, None)
                        if not active_deadlines:
                            entry.pop("activeDeadlines", None)
                    if entry.get("operationStartedAtEpoch") == operation_started_at:
                        entry.pop("operationStartedAtEpoch", None)
                publish_active_state()

        def execute(request):
            if execute_wave is not None:
                with accelerator_phase(request["waveId"], "whole_wave"):
                    return execute_wave(request)
            return _execute_wave_request(
                request,
                render_executor=render_executor,
                accelerator_phase=accelerator_phase,
                on_progress=record_progress,
            )

        request_path = requests / claimed_path.name
        wave_id = claimed_path.stem
        result_path = results / f"{wave_id}.json"
        if result_path.exists():
            claimed_path.unlink(missing_ok=True)
            request_path.unlink(missing_ok=True)
            return 0
        started = time.perf_counter()
        request_payload: dict[str, Any] = {}
        error_message = None
        execution_result: dict[str, Any] = {}
        execution_completed_successfully = False
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
            with state_lock:
                active_requests[request_key]["waveId"] = wave_id_value
                active_requests[request_key]["checkpointPath"] = request_payload.get("checkpointPath")
            publish_active_state()
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
                    execution_result = execute(request_payload)
                else:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    with log_path.open("a", encoding="utf-8", newline="\n") as log_stream:
                        with request_log(log_stream):
                            execution_result = execute(request_payload)
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
        return 1

    request_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="motion-wave-service")
    running_requests = {}
    try:
        while True:
            for future in list(running_requests):
                if future.done():
                    processed_count += future.result()
                    del running_requests[future]
                    idle_since = time.monotonic()
                    _prune_staged_wave_records(queue_root)
            request_paths = sorted(requests.glob("*.json"), key=_request_enqueued_order)
            if not request_paths and not running_requests:
                stop_requested = stop_path.exists()
                idle_expired = time.monotonic() - idle_since >= idle_timeout_seconds
                if stop_requested or idle_expired:
                    with staged_wave_admission_lock(queue_root):
                        if not list(requests.glob("*.json")):
                            update_state(status="stopping", currentRequestId=None, currentWaveId=None, publish=True)
                            break
            for request_path in request_paths:
                with state_lock:
                    active = list(active_requests.values())
                    can_overlap = bool(active) and all(entry.get("allowCpuPhaseOverlap") is True for entry in active)
                    cpu_ready = any(entry.get("phase") == "cpu_preparation" for entry in active)
                if len(running_requests) >= 2 or (running_requests and not (can_overlap and cpu_ready)):
                    break
                try:
                    payload = json.loads(request_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                if running_requests and payload.get("allowCpuPhaseOverlap") is not True:
                    break
                claimed_path = processing / request_path.name
                try:
                    os.replace(request_path, claimed_path)
                except FileNotFoundError:
                    continue
                with state_lock:
                    active_requests[claimed_path.stem] = {
                        "requestId": claimed_path.stem,
                        "waveId": payload.get("waveId"),
                        "runId": payload.get("runId"),
                        "phase": "starting",
                "operationStartedAtEpoch": time.time(),
                "lastProgressAtEpoch": time.time(),
                        "allowCpuPhaseOverlap": payload.get("allowCpuPhaseOverlap") is True,
                    }
                publish_active_state()
                future = request_executor.submit(copy_context().run, process_request, claimed_path)
                running_requests[future] = claimed_path
            time.sleep(max(0.01, poll_interval_seconds))
    except BaseException:
        with state_lock:
            run_ids = {entry.get("runId") for entry in active_requests.values()}
        for run_id in run_ids:
            if run_id:
                _write_json_atomic(cancelled_runs / f"{run_id}.json", {"runId": run_id})
        raise
    finally:
        request_executor.shutdown(wait=True)
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
    parser.add_argument("--recover-only", action="store_true", help="Recover abandoned claims under the worker lease without executing queued work")
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
        recover_only=args.recover_only,
        max_wave_items=args.max_wave_items,
        idle_timeout_seconds=args.idle_timeout_seconds,
        source_identity_fingerprint=args.source_identity_fingerprint or None,
        service_configuration_fingerprint=(
            args.service_configuration_fingerprint or None
        ),
    )
    if args.recover_only:
        print("Staged-wave queue recovery complete; no generation executed.", flush=True)
    else:
        print(f"Staged-wave service stopped after {processed} waves.", flush=True)


if __name__ == "__main__":
    main()
