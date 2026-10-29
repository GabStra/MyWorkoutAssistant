"""Process-owned admission for GPU stages and shared CPU-heavy work.

The scheduler deliberately provides asynchronous submission primitives while
keeping the current synchronous stage APIs as compatibility adapters. GPU
workers still acquire the existing cross-process GPU and Docker leases; the
scheduler owns only the in-process queue and executes lease-owning code on its
worker thread.
"""
from __future__ import annotations

import atexit
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
import os
from queue import Queue
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, Iterator, TypeVar


T = TypeVar("T")
_STOP = object()
_GPU_STAGE_DEADLINE: ContextVar[float | None] = ContextVar(
    "motion_gpu_stage_deadline", default=None
)
_CANDIDATE_DEADLINE: ContextVar[float | None] = ContextVar(
    "motion_candidate_deadline", default=None
)
MACHINE_CPU_SLOT_WAIT_TIMEOUT_SECONDS = 6 * 60 * 60
MACHINE_CPU_SLOT_LOCK_DIR_ENV_VAR = "EXERCISE_MOTION_CPU_SLOT_LOCK_DIR"


def _machine_cpu_slot_lock_root() -> Path:
    configured = os.environ.get(MACHINE_CPU_SLOT_LOCK_DIR_ENV_VAR)
    if configured:
        return Path(configured).expanduser().resolve()
    # TEMP is shared by the generator processes launched by the same user,
    # including workers with different workspace roots.
    return Path(tempfile.gettempdir()) / "myworkoutassistant-cpu-slots-v1"


def _try_acquire_machine_cpu_slot():
    from .process_lock import InterProcessFileLock
    from .resource_budget import machinewide_cpu_fit_slot_limit

    root = _machine_cpu_slot_lock_root()
    root.mkdir(parents=True, exist_ok=True)
    for slot_index in range(machinewide_cpu_fit_slot_limit()):
        lock = InterProcessFileLock(
            root / f"cpu-slot-{slot_index:02d}.lock",
            stage=f"machinewide_cpu_slot_{slot_index}",
            timeout_seconds=0,
            stale_after_seconds=0,
            poll_interval_seconds=0.01,
        )
        try:
            lock.__enter__()
        except TimeoutError:
            continue
        return lock
    return None


def current_gpu_stage_deadline() -> float | None:
    """Return the earliest active candidate or GPU-stage deadline."""
    deadlines = [value for value in (_GPU_STAGE_DEADLINE.get(), _CANDIDATE_DEADLINE.get()) if value is not None]
    return min(deadlines) if deadlines else None


def set_current_candidate_deadline(deadline: float | None) -> None:
    """Expose a caller-owned candidate deadline to synchronous shared helpers."""
    _CANDIDATE_DEADLINE.set(None if deadline is None else float(deadline))


@contextmanager
def candidate_deadline_scope(deadline: float | None) -> Iterator[None]:
    """Apply a candidate deadline for one operation and restore its caller context."""
    token = _CANDIDATE_DEADLINE.set(None if deadline is None else float(deadline))
    try:
        yield
    finally:
        _CANDIDATE_DEADLINE.reset(token)


def monotonic_deadline_from_perf_counter(deadline: float | None) -> float | None:
    """Translate a candidate deadline to the monotonic clock used by file locks."""
    if deadline is None:
        return None
    return time.monotonic() + float(deadline) - time.perf_counter()


def timeout_with_candidate_deadline(
    timeout_seconds: float | None,
    deadline: float | None,
    *,
    stage_name: str,
) -> float | None:
    """Cap a stage timeout at the remaining candidate budget."""
    if deadline is None:
        return timeout_seconds
    remaining = deadline - time.perf_counter()
    if remaining <= 0.0:
        raise TimeoutError(f"Candidate deadline expired before {stage_name} started")
    if timeout_seconds is None or timeout_seconds <= 0.0:
        return remaining
    return min(float(timeout_seconds), remaining)


class MotionResourceScheduler:
    """Own one FIFO GPU dispatcher and a shared CPU admission limit."""

    def __init__(self, *, name: str = "motion-resource-scheduler") -> None:
        self._name = name
        self._gpu_queue: Queue[Any] = Queue()
        self._start_lock = threading.Lock()
        self._gpu_worker: threading.Thread | None = None
        self._worker_local = threading.local()
        self._closed = False
        self._cpu_condition = threading.Condition()
        self._cpu_in_use = 0
        self._cpu_priority_waiters = 0
        self._cpu_slot_depth: ContextVar[int] = ContextVar(
            f"{name}_cpu_slot_depth_{id(self)}", default=0
        )

    def submit_gpu(
        self,
        operation: Callable[[], T],
        *,
        task_name: str,
        deadline: float | None = None,
    ) -> Future[T]:
        """Queue a GPU operation and return immediately with its result handle."""
        if deadline is not None and time.perf_counter() >= deadline:
            raise TimeoutError(f"GPU stage '{task_name}' reached its candidate deadline before enqueue")
        future: Future[T] = Future()
        with self._start_lock:
            if self._closed:
                raise RuntimeError("Motion resource scheduler is closed")
            if self._gpu_worker is None:
                self._gpu_worker = threading.Thread(
                    target=self._run_gpu_queue,
                    name=f"{self._name}-gpu",
                    daemon=True,
                )
                self._gpu_worker.start()
            self._gpu_queue.put((future, copy_context(), operation, task_name, deadline))
        return future

    def run_gpu_stage(
        self,
        operation: Callable[[], T],
        *,
        task_name: str,
        deadline: float | None = None,
    ) -> T:
        """Synchronous bridge; callers wait without owning GPU/Docker leases."""
        if deadline is not None and time.perf_counter() >= deadline:
            raise TimeoutError(f"GPU stage '{task_name}' reached its candidate deadline before start")
        if self.is_gpu_worker:
            return operation()
        future = self.submit_gpu(operation, task_name=task_name, deadline=deadline)
        try:
            if deadline is None:
                return future.result()
            remaining = max(0.0, deadline - time.perf_counter())
            try:
                return future.result(timeout=remaining)
            except FutureTimeoutError:
                if future.done():
                    raise
                if future.cancel():
                    raise TimeoutError(
                        f"GPU stage '{task_name}' was cancelled before start at its candidate deadline"
                    ) from None
                # Once the worker has started it owns the leases and workspace
                # until terminal completion. Never detach that operation from
                # its caller just because the candidate budget expired.
                return future.result()
        except BaseException:
            if not future.done() and not future.cancel():
                try:
                    future.result()
                except BaseException:
                    pass
            raise

    @property
    def is_gpu_worker(self) -> bool:
        return bool(getattr(self._worker_local, "active", False))

    def _run_gpu_queue(self) -> None:
        self._worker_local.active = True
        try:
            while True:
                job = self._gpu_queue.get()
                if job is _STOP:
                    return
                future, context, operation, task_name, deadline = job
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    if deadline is not None and time.perf_counter() >= deadline:
                        raise TimeoutError(
                            f"GPU stage '{task_name}' reached its candidate deadline while queued"
                        )

                    def run_with_stage_context() -> T:
                        cpu_depth_token = self._cpu_slot_depth.set(0)
                        deadline_token = _GPU_STAGE_DEADLINE.set(deadline)
                        try:
                            return operation()
                        finally:
                            _GPU_STAGE_DEADLINE.reset(deadline_token)
                            self._cpu_slot_depth.reset(cpu_depth_token)

                    result = context.run(run_with_stage_context)
                except BaseException as exc:
                    if hasattr(exc, "add_note"):
                        exc.add_note(f"GPU stage: {task_name}")
                    future.set_exception(exc)
                else:
                    future.set_result(result)
        finally:
            self._worker_local.active = False

    @contextmanager
    def cpu_slot(
        self,
        *,
        priority: bool = False,
        timeout_seconds: float | None = None,
    ) -> Iterator[float]:
        """Share CPU-heavy admission across processes, browser tasks, and fits.

        Reentrant use is intentional: a browser bake may call the fitter before
        its browser job returns, and should consume one shared CPU permit for
        that combined task rather than deadlocking on a second permit. The
        process-wide lane is acquired only after local admission succeeds; if
        all global lanes are busy, the local permit is released before waiting.
        """
        if self._cpu_slot_depth.get() > 0:
            yield 0.0
            return

        from .resource_budget import cpu_fit_slot_limit

        queued_at = time.perf_counter()
        deadline = (
            None
            if timeout_seconds is None
            else queued_at + max(0.0, float(timeout_seconds))
        )
        machine_wait_started: float | None = None
        while True:
            with self._cpu_condition:
                if priority:
                    self._cpu_priority_waiters += 1
                try:
                    while (
                        self._cpu_in_use >= max(1, int(cpu_fit_slot_limit()))
                        or (self._cpu_priority_waiters > 0 and not priority)
                    ):
                        remaining = None if deadline is None else deadline - time.perf_counter()
                        if remaining is not None and remaining <= 0.0:
                            raise TimeoutError(
                                "Timed out waiting for a local motion CPU lane after "
                                f"{time.perf_counter() - queued_at:.1f}s"
                            )
                        self._cpu_condition.wait(
                            timeout=0.25 if remaining is None else min(0.25, remaining)
                        )
                finally:
                    if priority:
                        self._cpu_priority_waiters = max(0, self._cpu_priority_waiters - 1)
                self._cpu_in_use += 1

            token = self._cpu_slot_depth.set(1)
            try:
                machine_slot = _try_acquire_machine_cpu_slot()
            except BaseException:
                self._cpu_slot_depth.reset(token)
                with self._cpu_condition:
                    self._cpu_in_use = max(0, self._cpu_in_use - 1)
                    self._cpu_condition.notify_all()
                raise
            if machine_slot is not None:
                break

            self._cpu_slot_depth.reset(token)
            with self._cpu_condition:
                self._cpu_in_use = max(0, self._cpu_in_use - 1)
                self._cpu_condition.notify_all()
            if machine_wait_started is None:
                machine_wait_started = time.perf_counter()
            waited = time.perf_counter() - machine_wait_started
            machine_remaining = MACHINE_CPU_SLOT_WAIT_TIMEOUT_SECONDS - waited
            budget_remaining = None if deadline is None else deadline - time.perf_counter()
            remaining = (
                machine_remaining
                if budget_remaining is None
                else min(machine_remaining, budget_remaining)
            )
            if remaining <= 0.0:
                if budget_remaining is not None and budget_remaining <= machine_remaining:
                    raise TimeoutError(
                        "Timed out waiting for a motion CPU lane within the candidate "
                        f"budget after {time.perf_counter() - queued_at:.1f}s"
                    )
                raise TimeoutError(
                    "Timed out waiting for a machine-wide motion CPU lane after "
                    f"{waited:.1f}s"
                )
            # Other processes cannot notify this process's condition. Poll the
            # OS-backed lane set while holding no local permit.
            with self._cpu_condition:
                self._cpu_condition.wait(timeout=min(0.25, remaining))

        try:
            yield time.perf_counter() - queued_at
        finally:
            self._cpu_slot_depth.reset(token)
            machine_slot.__exit__(None, None, None)
            with self._cpu_condition:
                self._cpu_in_use = max(0, self._cpu_in_use - 1)
                self._cpu_condition.notify_all()

    def run_cpu_task(self, operation: Callable[[], T]) -> T:
        """Run a worker task with a fresh permit even if submitter context held one."""
        inherited = self._cpu_slot_depth.set(0)
        try:
            with self.cpu_slot():
                return operation()
        finally:
            self._cpu_slot_depth.reset(inherited)

    def close(self, *, wait: bool = True) -> None:
        with self._start_lock:
            if self._closed:
                worker = self._gpu_worker
            else:
                self._closed = True
                worker = self._gpu_worker
                if worker is not None:
                    self._gpu_queue.put(_STOP)
        if wait and worker is not None and worker is not threading.current_thread():
            worker.join()


_DEFAULT_SCHEDULER: MotionResourceScheduler | None = None
_DEFAULT_SCHEDULER_LOCK = threading.Lock()


def get_motion_resource_scheduler() -> MotionResourceScheduler:
    global _DEFAULT_SCHEDULER
    with _DEFAULT_SCHEDULER_LOCK:
        if _DEFAULT_SCHEDULER is None:
            _DEFAULT_SCHEDULER = MotionResourceScheduler()
        return _DEFAULT_SCHEDULER


def submit_gpu_stage(
    operation: Callable[[], T],
    *,
    task_name: str,
    deadline: float | None = None,
) -> Future[T]:
    return get_motion_resource_scheduler().submit_gpu(
        operation,
        task_name=task_name,
        deadline=deadline,
    )


def run_gpu_stage(
    operation: Callable[[], T],
    *,
    task_name: str,
    deadline: float | None = None,
) -> T:
    return get_motion_resource_scheduler().run_gpu_stage(
        operation,
        task_name=task_name,
        deadline=deadline,
    )


def cpu_resource_slot(
    *,
    priority: bool = False,
    timeout_seconds: float | None = None,
) -> Any:
    return get_motion_resource_scheduler().cpu_slot(
        priority=priority,
        timeout_seconds=timeout_seconds,
    )


def run_cpu_task(operation: Callable[[], T]) -> T:
    return get_motion_resource_scheduler().run_cpu_task(operation)


def gpu_stage_task(task_name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Move an existing lease-owning runner onto the scheduler's GPU queue."""
    def decorate(operation: Callable[..., T]) -> Callable[..., T]:
        @wraps(operation)
        def wrapped(*args: Any, **kwargs: Any) -> T:
            deadline = kwargs.get("candidate_deadline")
            return run_gpu_stage(
                lambda: operation(*args, **kwargs),
                task_name=task_name,
                deadline=deadline if isinstance(deadline, (int, float)) else None,
            )
        return wrapped
    return decorate


def _close_default_scheduler() -> None:
    scheduler = _DEFAULT_SCHEDULER
    if scheduler is not None:
        scheduler.close(wait=False)


atexit.register(_close_default_scheduler)
