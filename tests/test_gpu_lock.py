from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from exercise_motion_pkg.gpu_lock import (
    GPU_LOCK_PATH_ENV_VAR,
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
