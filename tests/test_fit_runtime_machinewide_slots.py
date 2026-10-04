from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


def _wait_for_file(path: Path, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file():
            return True
        time.sleep(0.02)
    return path.is_file()


def test_motion_cpu_slots_are_capped_across_processes_and_released_if_owner_dies(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    lock_dir = tmp_path / "cpu-slots"
    holder_entered = tmp_path / "holder-entered"
    release_holder = tmp_path / "release-holder"
    waiter_entered = tmp_path / "waiter-entered"
    env = os.environ.copy()
    env["EXERCISE_MOTION_CPU_SLOT_LOCK_DIR"] = str(lock_dir)
    env["EXERCISE_MOTION_MACHINE_FIT_LANES"] = "1"
    holder_code = """
from pathlib import Path
import sys, time
from exercise_motion_pkg.motion_scheduler import cpu_resource_slot
entered, release = map(Path, sys.argv[1:3])
with cpu_resource_slot():
    entered.write_text('entered', encoding='utf-8')
    while not release.exists():
        time.sleep(0.02)
"""
    waiter_code = """
from pathlib import Path
import sys
from exercise_motion_pkg.motion_scheduler import cpu_resource_slot
with cpu_resource_slot():
    Path(sys.argv[1]).write_text('entered', encoding='utf-8')
"""

    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(holder_entered), str(release_holder)],
        cwd=repo_root,
        env=env,
    )
    waiter = None
    try:
        assert _wait_for_file(holder_entered, 10), "first process did not acquire the CPU lane"
        waiter = subprocess.Popen(
            [sys.executable, "-c", waiter_code, str(waiter_entered)],
            cwd=repo_root,
            env=env,
        )
        time.sleep(0.2)
        assert not waiter_entered.exists(), "separate process entered an already-held CPU lane"

        # Kernel-owned file locks release on process death; the waiting service
        # should then acquire the same lane without stale-file cleanup.
        holder.terminate()
        holder.wait(timeout=5)
        assert _wait_for_file(waiter_entered, 10), "waiter did not acquire the released CPU lane"
        assert waiter.wait(timeout=10) == 0
    finally:
        release_holder.touch()
        for process in (holder, waiter):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def test_machinewide_cpu_slot_wait_fails_closed_after_bounded_timeout(tmp_path: Path, monkeypatch):
    from exercise_motion_pkg import motion_scheduler
    from exercise_motion_pkg.motion_scheduler import cpu_resource_slot

    monkeypatch.setenv("EXERCISE_MOTION_CPU_SLOT_LOCK_DIR", str(tmp_path / "cpu-slots"))
    monkeypatch.setenv("EXERCISE_MOTION_MACHINE_FIT_LANES", "1")
    monkeypatch.setattr(motion_scheduler, "MACHINE_CPU_SLOT_WAIT_TIMEOUT_SECONDS", 0.03)
    owner = motion_scheduler._try_acquire_machine_cpu_slot()
    assert owner is not None
    try:
        with pytest.raises(TimeoutError, match="machine-wide motion CPU lane"):
            with cpu_resource_slot():
                pytest.fail("CPU task proceeded without acquiring a machine-wide lane")
    finally:
        owner.__exit__(None, None, None)


def test_local_pool_waiter_does_not_reserve_machine_slot(tmp_path: Path, monkeypatch):
    from exercise_motion_pkg import motion_scheduler
    from exercise_motion_pkg import resource_budget
    from exercise_motion_pkg.motion_scheduler import MotionResourceScheduler

    monkeypatch.setenv("EXERCISE_MOTION_CPU_SLOT_LOCK_DIR", str(tmp_path / "cpu-slots"))
    monkeypatch.setenv("EXERCISE_MOTION_MACHINE_FIT_LANES", "1")
    monkeypatch.setattr(resource_budget, "cpu_fit_slot_limit", lambda: 1)
    scheduler = MotionResourceScheduler(name="test-machine-slot-local-wait")
    acquired = threading.Event()
    attempts = []
    attempts_lock = threading.Lock()
    real_try_acquire = motion_scheduler._try_acquire_machine_cpu_slot

    def record_global_attempt():
        with attempts_lock:
            attempts.append(True)
        return real_try_acquire()

    monkeypatch.setattr(motion_scheduler, "_try_acquire_machine_cpu_slot", record_global_attempt)
    with scheduler._cpu_condition:
        scheduler._cpu_in_use = 1
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(lambda: _run_one_cpu_slot(scheduler, acquired))
        time.sleep(0.15)
        assert not attempts, "task tried to reserve a machine slot before local admission"
        with scheduler._cpu_condition:
            scheduler._cpu_in_use = 0
            scheduler._cpu_condition.notify_all()
        assert acquired.wait(timeout=3)
        future.result(timeout=3)
        assert len(attempts) == 1
    finally:
        with scheduler._cpu_condition:
            scheduler._cpu_in_use = 0
            scheduler._cpu_condition.notify_all()
        executor.shutdown(wait=True)
        scheduler.close()


def _run_one_cpu_slot(scheduler, acquired) -> None:
    with scheduler.cpu_slot():
        acquired.set()
