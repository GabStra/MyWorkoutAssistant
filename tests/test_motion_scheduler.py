from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from contextvars import ContextVar
import threading
import time

import pytest

from exercise_motion_pkg.motion_scheduler import MotionResourceScheduler


def test_gpu_dispatch_serializes_and_runs_away_from_submitter():
    scheduler = MotionResourceScheduler(name="test-motion-scheduler")
    active = 0
    peak_active = 0
    lock = threading.Lock()
    caller_thread = threading.current_thread().name

    def operation():
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        try:
            time.sleep(0.02)
            return threading.current_thread().name
        finally:
            with lock:
                active -= 1

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(
                lambda index: scheduler.run_gpu_stage(operation, task_name=f"fake-{index}"),
                range(8),
            ))
        assert peak_active == 1
        assert len(set(results)) == 1
        assert results[0] != caller_thread
        assert results[0].endswith("-gpu")
    finally:
        scheduler.close()


def test_queued_gpu_future_can_cancel_without_cancelling_running_work():
    scheduler = MotionResourceScheduler(name="test-motion-cancel")
    running = threading.Event()
    release = threading.Event()
    try:
        first = scheduler.submit_gpu(
            lambda: (running.set(), release.wait(timeout=2), "finished")[2],
            task_name="running",
        )
        assert running.wait(timeout=2)
        queued = scheduler.submit_gpu(lambda: "must not run", task_name="queued")
        assert queued.cancel()
        release.set()
        assert first.result(timeout=2) == "finished"
        with pytest.raises(CancelledError):
            queued.result()
    finally:
        release.set()
        scheduler.close()


def test_gpu_submission_carries_candidate_context_to_worker():
    scheduler = MotionResourceScheduler(name="test-motion-context")
    deadline = ContextVar("test_candidate_deadline", default=None)
    token = deadline.set(123.5)
    try:
        assert scheduler.run_gpu_stage(deadline.get, task_name="context") == 123.5
    finally:
        deadline.reset(token)
        scheduler.close()


def test_gpu_worker_does_not_inherit_submitters_cpu_slot_depth():
    scheduler = MotionResourceScheduler(name="test-motion-cpu-context")
    try:
        with scheduler.cpu_slot():
            assert scheduler._cpu_slot_depth.get() == 1
            assert scheduler.run_gpu_stage(
                scheduler._cpu_slot_depth.get,
                task_name="check-cpu-context",
            ) == 0
            assert scheduler._cpu_slot_depth.get() == 1
    finally:
        scheduler.close()


def test_gpu_stage_cancels_a_queued_job_when_caller_deadline_expires():
    scheduler = MotionResourceScheduler(name="test-motion-deadline")
    running = threading.Event()
    release = threading.Event()
    late_operation_started = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        first = scheduler.submit_gpu(
            lambda: (running.set(), release.wait(timeout=2), "finished")[2],
            task_name="blocking-stage",
        )
        assert running.wait(timeout=2)
        deadline = time.perf_counter() + 0.05
        late = executor.submit(
            scheduler.run_gpu_stage,
            lambda: late_operation_started.set(),
            task_name="expired-stage",
            deadline=deadline,
        )
        with pytest.raises(TimeoutError, match="cancelled before start"):
            late.result(timeout=2)
        release.set()
        assert first.result(timeout=2) == "finished"
        assert not late_operation_started.is_set()
    finally:
        release.set()
        executor.shutdown(wait=True)
        scheduler.close()


def test_gpu_stage_waits_for_running_work_before_propagating_caller_interruption(
    monkeypatch,
):
    scheduler = MotionResourceScheduler(name="test-motion-running-cancel")
    finished = threading.Event()

    class InterruptedOnceFuture(Future):
        def __init__(self):
            super().__init__()
            self.set_running_or_notify_cancel()
            self.first_wait = True

        def result(self, timeout=None):
            if self.first_wait:
                self.first_wait = False
                raise KeyboardInterrupt()
            return super().result(timeout=timeout)

    future = InterruptedOnceFuture()
    monkeypatch.setattr(scheduler, "submit_gpu", lambda *_args, **_kwargs: future)

    def finish_running_stage():
        time.sleep(0.03)
        finished.set()
        future.set_result("finished")

    worker = threading.Thread(target=finish_running_stage)
    worker.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            scheduler.run_gpu_stage(lambda: None, task_name="interrupted-caller")
        assert finished.is_set()
        assert future.done()
    finally:
        worker.join(timeout=2)
        scheduler.close()


def test_cpu_slot_is_reentrant_and_caps_browser_style_tasks(monkeypatch):
    from exercise_motion_pkg import resource_budget

    monkeypatch.setattr(resource_budget, "cpu_fit_slot_limit", lambda: 1)
    scheduler = MotionResourceScheduler(name="test-motion-cpu")
    active = 0
    peak_active = 0
    lock = threading.Lock()

    def operation():
        nonlocal active, peak_active
        with scheduler.cpu_slot():
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            try:
                # Models a browser bake entering fit admission on the same job.
                with scheduler.cpu_slot():
                    time.sleep(0.02)
            finally:
                with lock:
                    active -= 1

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(scheduler.run_cpu_task, operation) for _ in range(4)]
            for future in futures:
                future.result(timeout=2)
        assert peak_active == 1
    finally:
        scheduler.close()
