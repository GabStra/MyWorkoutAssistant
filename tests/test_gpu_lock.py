from __future__ import annotations

import threading
import time
import os
from pathlib import Path

import pytest

from exercise_motion_pkg.gpu_lock import (
    GPU_LOCK_PATH_ENV_VAR,
    GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS_ENV_VAR,
    GlobalGpuLock,
)


def test_global_gpu_lock_serializes_different_threads_in_same_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "gpu.lock"
    monkeypatch.setenv(GPU_LOCK_PATH_ENV_VAR, str(lock_path))
    second_started = threading.Event()
    second_acquired = threading.Event()
    failures: list[BaseException] = []

    def acquire_from_second_thread() -> None:
        second_started.set()
        try:
            with GlobalGpuLock(stage="second"):
                second_acquired.set()
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    with GlobalGpuLock(stage="first"):
        worker = threading.Thread(target=acquire_from_second_thread)
        worker.start()
        assert second_started.wait(timeout=1.0)
        time.sleep(0.05)
        assert not second_acquired.is_set()

    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert not failures
    assert second_acquired.is_set()
    assert not lock_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows delete-on-close sharing semantics")
def test_metadata_reader_cannot_orphan_released_gpu_lock(tmp_path, monkeypatch):
    import msvcrt
    from exercise_motion_pkg.gpu_lock import _windows_file_handle, lock_payload
    path = tmp_path / "reader.lock"
    monkeypatch.setenv(GPU_LOCK_PATH_ENV_VAR, str(path))
    lock = GlobalGpuLock(stage="owner")
    lock.__enter__()
    assert lock_payload(path)["stage"] == "owner"
    reader = msvcrt.open_osfhandle(_windows_file_handle(path, create=False), os.O_RDONLY)
    try:
        # Release must not raise or lose the operation result with an open reader.
        lock.__exit__(None, None, None)
    finally:
        os.close(reader)
    assert not path.exists()
    with GlobalGpuLock(stage="next"):
        assert lock_payload(path)["stage"] == "next"


@pytest.mark.skipif(os.name != "nt", reason="Windows process-exit lease semantics")
def test_process_crash_does_not_leave_gpu_lock(tmp_path, monkeypatch):
    import subprocess
    import sys
    path = tmp_path / "crash.lock"
    monkeypatch.setenv(GPU_LOCK_PATH_ENV_VAR, str(path))
    child = subprocess.run([sys.executable, "-c",
        "import os; from exercise_motion_pkg.gpu_lock import GlobalGpuLock; "
        "lock=GlobalGpuLock(stage='crash'); lock.__enter__(); os._exit(3)"], timeout=20)
    assert child.returncode == 3
    assert not path.exists()


def test_global_gpu_lock_rejects_recursive_acquisition_in_same_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "gpu.lock"
    monkeypatch.setenv(GPU_LOCK_PATH_ENV_VAR, str(lock_path))

    with GlobalGpuLock(stage="outer"):
        with pytest.raises(RuntimeError, match="same thread would deadlock"):
            with GlobalGpuLock(stage="inner"):
                pass
        assert lock_path.exists()

    assert not lock_path.exists()


def test_failed_metadata_write_releases_lease(tmp_path, monkeypatch):
    from exercise_motion_pkg import gpu_lock
    path = tmp_path / "failed-write.lock"
    monkeypatch.setenv(GPU_LOCK_PATH_ENV_VAR, str(path))
    def fail(*args):
        raise OSError("metadata write failed")
    monkeypatch.setattr(gpu_lock.os, "write", fail)
    with pytest.raises(OSError, match="metadata write failed"):
        with GlobalGpuLock(stage="write-failure"):
            pass
    assert not path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows delete-on-close sharing semantics")
def test_docker_lease_reader_does_not_mask_operation_failure(tmp_path, monkeypatch):
    import msvcrt
    from exercise_motion_pkg.gpu_lock import _windows_file_handle
    from exercise_motion_pkg import wham_runner
    path = tmp_path / "docker.lock"
    monkeypatch.setenv(wham_runner.WHAM_DOCKER_LOCK_ENV_VAR, str(path))
    reader = None
    try:
        with pytest.raises(ValueError, match="tracking rejected"):
            with wham_runner.wham_docker_run_lock(enabled=True):
                reader = msvcrt.open_osfhandle(_windows_file_handle(path, create=False), os.O_RDONLY)
                raise ValueError("tracking rejected")
    finally:
        if reader is not None:
            os.close(reader)
    assert not path.exists()


def test_same_process_timeout_force_releases_pinned_holder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "gpu.lock"
    monkeypatch.setenv(GPU_LOCK_PATH_ENV_VAR, str(lock_path))
    monkeypatch.setenv(GPU_LOCK_SAME_PROCESS_TIMEOUT_SECONDS_ENV_VAR, "1")
    released: list[str] = []

    holder = GlobalGpuLock(
        stage="llama_cpp_server",
        on_force_release=lambda: released.append("holder"),
    )
    holder.__enter__()
    failures: list[BaseException] = []

    def acquire_from_worker_thread() -> None:
        try:
            with GlobalGpuLock(stage="yolo_pose_prefilter"):
                # The pinned holder was force-released, so the waiter acquired.
                assert lock_path.exists()
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    started = time.perf_counter()
    worker = threading.Thread(target=acquire_from_worker_thread)
    worker.start()
    worker.join(timeout=30.0)
    holder.__exit__(None, None, None)

    assert not worker.is_alive()
    assert not failures
    assert released == ["holder"]
    assert time.perf_counter() - started < 30.0
    assert not lock_path.exists()
