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
    from exercise_motion_pkg import reconstruction_runner
    path = tmp_path / "docker.lock"
    monkeypatch.setenv(reconstruction_runner.RECONSTRUCTION_DOCKER_LOCK_ENV_VAR, str(path))
    reader = None
    try:
        with pytest.raises(ValueError, match="tracking rejected"):
            with reconstruction_runner.reconstruction_docker_run_lock(enabled=True):
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
    callback_saw_lock: list[bool] = []

    def stop_holder() -> None:
        callback_saw_lock.append(lock_path.exists())
        released.append("holder")

    holder = GlobalGpuLock(
        stage="llama_cpp_server",
        on_force_release=stop_holder,
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
    assert callback_saw_lock == [True]
    assert released == ["holder"]


def test_failed_force_release_keeps_gpu_lease_until_owner_stops(tmp_path, monkeypatch):
    lock_path = tmp_path / "gpu.lock"
    monkeypatch.setenv(GPU_LOCK_PATH_ENV_VAR, str(lock_path))

    def stop_failed_owner():
        raise TimeoutError("server stop was not confirmed")

    holder = GlobalGpuLock(stage="llama_cpp_server", on_force_release=stop_failed_owner)
    holder.__enter__()
    try:
        assert not holder.force_release("test stop failure")
        assert lock_path.exists()
    finally:
        holder.__exit__(None, None, None)
    assert not lock_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows kill-on-job-close ownership")
def test_python_model_child_dies_if_its_owner_process_crashes():
    import subprocess
    import sys

    from exercise_motion_pkg.process_lock import process_is_running

    owner_script = (
        "import os, subprocess, sys; "
        "from exercise_motion_pkg.child_process import ChildProcessOwner; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "ChildProcessOwner(child); print(child.pid, flush=True); os._exit(0)"
    )
    owner = subprocess.run(
        [sys.executable, "-c", owner_script],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    child_pid = int(owner.stdout.strip())
    deadline = time.monotonic() + 5
    while process_is_running(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not process_is_running(child_pid)

    close_script = (
        "import subprocess, sys; "
        "from exercise_motion_pkg.child_process import ChildProcessOwner; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "owner = ChildProcessOwner(child); print(child.pid, flush=True); owner.close()"
    )
    closed_owner = subprocess.run(
        [sys.executable, "-c", close_script],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    child_pid = int(closed_owner.stdout.strip())
    deadline = time.monotonic() + 5
    while process_is_running(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not process_is_running(child_pid)


def test_old_gpu_and_reconstruction_lock_metadata_does_not_evict_live_owner(tmp_path: Path):
    import json

    from exercise_motion_pkg import gpu_lock, reconstruction_runner

    identity = gpu_lock.process_identity(os.getpid())
    gpu_path = tmp_path / "gpu-old-live.lock"
    gpu_path.write_text(json.dumps({"pid": os.getpid(), "processIdentity": identity}))
    reconstruction_path = tmp_path / "reconstruction-old-live.lock"
    reconstruction_path.write_text(json.dumps({"pid": os.getpid(), "processIdentity": identity}))
    old_timestamp = time.time() - 24 * 60 * 60
    os.utime(gpu_path, (old_timestamp, old_timestamp))
    os.utime(reconstruction_path, (old_timestamp, old_timestamp))

    assert not gpu_lock.gpu_lock_is_stale(gpu_path, timeout_seconds=1.0)
    assert not reconstruction_runner.reconstruction_docker_lock_is_stale(reconstruction_path, timeout_seconds=1.0)


def test_corrupt_or_ownerless_old_gpu_locks_are_not_age_evicted(tmp_path: Path):
    from exercise_motion_pkg import gpu_lock, reconstruction_runner

    for lock_path, is_stale in (
        (tmp_path / "gpu-corrupt.lock", gpu_lock.gpu_lock_is_stale),
        (tmp_path / "reconstruction-corrupt.lock", reconstruction_runner.reconstruction_docker_lock_is_stale),
    ):
        lock_path.write_text("{truncated", encoding="utf-8")
        os.utime(lock_path, (time.time() - 120, time.time() - 120))
        assert not is_stale(lock_path, timeout_seconds=1.0)

        lock_path.write_text("{}", encoding="utf-8")
        os.utime(lock_path, (time.time() - 120, time.time() - 120))
        assert not is_stale(lock_path, timeout_seconds=1.0)


def test_gpu_stale_lock_recovery_is_serialized_between_waiters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from exercise_motion_pkg import gpu_lock

    lock_path = tmp_path / "gpu-stale.lock"
    lock_path.write_text(
        json.dumps({"pid": 987654, "processIdentity": 42, "stage": "crashed"}),
        encoding="utf-8",
    )
    monkeypatch.setenv(GPU_LOCK_PATH_ENV_VAR, str(lock_path))
    monkeypatch.setattr(gpu_lock, "process_is_running", lambda _pid: False)
    original_is_stale = gpu_lock.gpu_lock_is_stale
    check_lock = threading.Lock()
    active_stale_checks = 0
    max_concurrent_stale_checks = 0
    active_sections = 0
    max_concurrent_sections = 0
    counts_lock = threading.Lock()
    start_together = threading.Barrier(3)
    failures: list[BaseException] = []

    def observe_stale_check(path: Path, *, timeout_seconds: float) -> bool:
        nonlocal active_stale_checks, max_concurrent_stale_checks
        with check_lock:
            active_stale_checks += 1
            max_concurrent_stale_checks = max(max_concurrent_stale_checks, active_stale_checks)
        try:
            # Keep the stale observation open long enough for a second waiter
            # to reach the same decision point if admission is not serialized.
            time.sleep(0.1)
            return original_is_stale(path, timeout_seconds=timeout_seconds)
        finally:
            with check_lock:
                active_stale_checks -= 1

    monkeypatch.setattr(gpu_lock, "gpu_lock_is_stale", observe_stale_check)

    def acquire() -> None:
        nonlocal active_sections, max_concurrent_sections
        try:
            start_together.wait()
            with GlobalGpuLock(stage="stale-recovery-test"):
                with counts_lock:
                    active_sections += 1
                    max_concurrent_sections = max(max_concurrent_sections, active_sections)
                try:
                    time.sleep(0.05)
                finally:
                    with counts_lock:
                        active_sections -= 1
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    workers = [threading.Thread(target=acquire) for _ in range(2)]
    for worker in workers:
        worker.start()
    start_together.wait()
    for worker in workers:
        worker.join(timeout=5.0)

    assert all(not worker.is_alive() for worker in workers)
    assert not failures
    assert max_concurrent_stale_checks == 1
    assert max_concurrent_sections == 1


def test_reconstruction_stale_lock_recovery_is_serialized_between_waiters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from exercise_motion_pkg import reconstruction_runner

    lock_path = tmp_path / "reconstruction-stale.lock"
    lock_path.write_text(
        json.dumps({"pid": 987654, "processIdentity": 42}),
        encoding="utf-8",
    )
    monkeypatch.setenv(reconstruction_runner.RECONSTRUCTION_DOCKER_LOCK_ENV_VAR, str(lock_path))
    monkeypatch.setenv(reconstruction_runner.RECONSTRUCTION_DOCKER_LOCK_TIMEOUT_SECONDS_ENV_VAR, "5")
    monkeypatch.setattr(reconstruction_runner, "process_is_running", lambda _pid: False)
    original_is_stale = reconstruction_runner.reconstruction_docker_lock_is_stale
    check_lock = threading.Lock()
    active_stale_checks = 0
    max_concurrent_stale_checks = 0
    active_sections = 0
    max_concurrent_sections = 0
    counts_lock = threading.Lock()
    start_together = threading.Barrier(3)
    failures: list[BaseException] = []

    def observe_stale_check(path: Path, *, timeout_seconds: float) -> bool:
        nonlocal active_stale_checks, max_concurrent_stale_checks
        with check_lock:
            active_stale_checks += 1
            max_concurrent_stale_checks = max(max_concurrent_stale_checks, active_stale_checks)
        try:
            time.sleep(0.1)
            return original_is_stale(path, timeout_seconds=timeout_seconds)
        finally:
            with check_lock:
                active_stale_checks -= 1

    monkeypatch.setattr(reconstruction_runner, "reconstruction_docker_lock_is_stale", observe_stale_check)

    def acquire() -> None:
        nonlocal active_sections, max_concurrent_sections
        try:
            start_together.wait()
            with reconstruction_runner.reconstruction_docker_run_lock(enabled=True):
                with counts_lock:
                    active_sections += 1
                    max_concurrent_sections = max(max_concurrent_sections, active_sections)
                try:
                    time.sleep(0.05)
                finally:
                    with counts_lock:
                        active_sections -= 1
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    workers = [threading.Thread(target=acquire) for _ in range(2)]
    for worker in workers:
        worker.start()
    start_together.wait()
    for worker in workers:
        worker.join(timeout=5.0)

    assert all(not worker.is_alive() for worker in workers)
    assert not failures
    assert max_concurrent_stale_checks == 1
    assert max_concurrent_sections == 1


def test_cross_process_gpu_wait_sleep_is_bounded_by_candidate_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from types import SimpleNamespace

    from exercise_motion_pkg import gpu_lock

    lock_path = tmp_path / "gpu-external.lock"
    lock_path.write_text(
        json.dumps({"pid": 987654, "processIdentity": 42, "stage": "external"}),
        encoding="utf-8",
    )
    monkeypatch.setenv(GPU_LOCK_PATH_ENV_VAR, str(lock_path))
    monkeypatch.setattr(gpu_lock, "process_is_running", lambda _pid: True)
    monkeypatch.setattr(gpu_lock, "process_identity", lambda _pid: 42)

    observed_sleeps: list[float] = []

    def observe_sleep(seconds: float) -> None:
        observed_sleeps.append(seconds)
        raise RuntimeError("sleep observed")

    monkeypatch.setattr(
        gpu_lock,
        "time",
        SimpleNamespace(perf_counter=lambda: 9.95, sleep=observe_sleep),
    )
    with pytest.raises(RuntimeError, match="sleep observed"):
        with GlobalGpuLock(stage="deadline-bound", deadline=10.0):
            pass

    assert observed_sleeps
    assert 0.0 <= observed_sleeps[0] <= 0.051


def test_exclusive_gpu_device_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    import exercise_motion_pkg.gpu_lock as gpu_lock
    from exercise_motion_pkg.gpu_lock import (
        EXCLUSIVE_GPU_DEVICE_ENV_VAR,
        exclusive_gpu_device,
        resolve_docker_gpu_selection,
        resolve_llama_server_cuda_visibility,
        resolve_stage_cuda_device,
    )

    monkeypatch.delenv(EXCLUSIVE_GPU_DEVICE_ENV_VAR, raising=False)
    assert exclusive_gpu_device() is None
    for off in ("", "0", "  "):
        monkeypatch.setenv(EXCLUSIVE_GPU_DEVICE_ENV_VAR, off)
        assert exclusive_gpu_device() is None
    monkeypatch.setattr(gpu_lock, "visible_gpu_count", lambda: 2)
    monkeypatch.setenv(EXCLUSIVE_GPU_DEVICE_ENV_VAR, "1")
    monkeypatch.setattr(gpu_lock, "gpu_device_uuid", lambda index: f"GPU-test-{index}")
    assert exclusive_gpu_device() == "1"
    monkeypatch.setenv(EXCLUSIVE_GPU_DEVICE_ENV_VAR, "3")
    assert exclusive_gpu_device() is None
    monkeypatch.setattr(gpu_lock, "visible_gpu_count", lambda: None)
    monkeypatch.setenv(EXCLUSIVE_GPU_DEVICE_ENV_VAR, "1")
    assert exclusive_gpu_device() == "1"
    monkeypatch.setenv(EXCLUSIVE_GPU_DEVICE_ENV_VAR, "abc")
    with pytest.raises(ValueError, match="EXCLUSIVE_GPU_DEVICE"):
        exclusive_gpu_device()

    monkeypatch.setenv(EXCLUSIVE_GPU_DEVICE_ENV_VAR, "1")
    assert resolve_docker_gpu_selection("all") == "device=GPU-test-1"
    assert resolve_llama_server_cuda_visibility("1") == "GPU-test-0"
    assert resolve_docker_gpu_selection("device=1") == "device=GPU-test-1"
    assert resolve_docker_gpu_selection("device=GPU-test-1") == "device=GPU-test-1"
    with pytest.raises(ValueError, match="conflicts with exclusive GPU 1"):
        resolve_docker_gpu_selection("device=0")
    assert resolve_stage_cuda_device("cuda") == "cuda:1"
    assert resolve_stage_cuda_device("cpu") == "cpu"
    assert resolve_stage_cuda_device("cuda:1") == "cuda:1"
    with pytest.raises(ValueError, match="conflicts with exclusive GPU 1"):
        resolve_stage_cuda_device("cuda:0")
    monkeypatch.delenv(EXCLUSIVE_GPU_DEVICE_ENV_VAR)
    assert resolve_docker_gpu_selection("all") == "all"
    assert resolve_llama_server_cuda_visibility(None) is None
    assert resolve_stage_cuda_device("cuda") == "cuda"


def test_gvhmr_command_masks_cuda_to_exclusive_physical_gpu_uuid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import exercise_motion_pkg.gvhmr_runner as gvhmr_runner
    import exercise_motion_pkg.gpu_lock as gpu_lock

    monkeypatch.setattr(gvhmr_runner, "exclusive_gpu_device", lambda: "1")
    monkeypatch.setattr(gvhmr_runner, "gpu_device_uuid", lambda index: f"GPU-test-{index}")
    monkeypatch.setattr(gpu_lock, "exclusive_gpu_device", lambda: "1")
    monkeypatch.setattr(gpu_lock, "gpu_device_uuid", lambda index: f"GPU-test-{index}")

    command = gvhmr_runner.build_gvhmr_command(
        input_video=tmp_path / "input.mp4",
        output_root=tmp_path / "output",
        export_script=Path("gvhmr_pkl_export.py"),
        docker_image="gvhmr:test",
        docker_gpus="all",
        docker_shm_size="8g",
        docker_container_name="smoke",
        static_camera=True,
    )

    assert command[command.index("--gpus") + 1] == "device=GPU-test-1"
    assert command[command.index("--env") + 1] == "CUDA_VISIBLE_DEVICES=GPU-test-1"

    with pytest.raises(ValueError, match="conflicts with exclusive GPU 1"):
        gvhmr_runner.build_gvhmr_command(
            input_video=tmp_path / "input.mp4",
            output_root=tmp_path / "output",
            export_script=Path("gvhmr_pkl_export.py"),
            docker_image="gvhmr:test",
            docker_gpus="device=GPU-test-0",
            docker_shm_size="8g",
            docker_container_name="smoke",
            static_camera=True,
        )


def test_per_device_lock_lanes_are_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import exercise_motion_pkg.gpu_lock as gpu_lock
    from exercise_motion_pkg.gpu_lock import gpu_lock_path

    monkeypatch.setenv(GPU_LOCK_PATH_ENV_VAR, str(tmp_path / "gpu.lock"))
    monkeypatch.setattr(gpu_lock, "_activate_torch_device", lambda device: None)
    secondary_path = gpu_lock_path("1")

    with GlobalGpuLock(stage="secondary", device="1"):
        assert secondary_path.exists()
        with GlobalGpuLock(stage="primary"):
            pass
        with pytest.raises(RuntimeError, match="would deadlock"):
            with GlobalGpuLock(stage="nested-secondary", device="1"):
                pass
    assert not secondary_path.exists()
    assert not (tmp_path / "gpu.lock").exists()
