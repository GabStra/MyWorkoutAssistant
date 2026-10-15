from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading

import pytest

from exercise_motion_pkg import gpu_lock


_temperature_probe = gpu_lock.query_gpu_temperature_c


@pytest.fixture(autouse=True)
def isolated_gpu_admission(tmp_path, monkeypatch):
    monkeypatch.setenv(gpu_lock.GPU_LOCK_PATH_ENV_VAR, str(tmp_path / "gpu.lock"))
    monkeypatch.setattr(gpu_lock, "query_gpu_temperature_c", lambda: 45)
    monkeypatch.setattr(gpu_lock, "_TEMPERATURE_WARNING_SHOWN", False)


def test_cooling_waits_until_resume_temperature(monkeypatch, capsys):
    temperatures = iter([80, 79, 75, 74])
    sleeps = []
    monkeypatch.setattr(gpu_lock, "query_gpu_temperature_c", lambda: next(temperatures))
    monkeypatch.setattr(gpu_lock.time, "sleep", sleeps.append)
    gpu_lock.wait_for_gpu_cooling("reconstruction")
    assert sleeps == [2.0, 2.0, 2.0]
    assert "cooling finished" in capsys.readouterr().err


def test_cool_gpu_does_not_sleep(monkeypatch):
    monkeypatch.setattr(gpu_lock, "query_gpu_temperature_c", lambda: 79)
    monkeypatch.setattr(gpu_lock.time, "sleep", lambda _: pytest.fail("Unexpected cooling pause"))
    gpu_lock.wait_for_gpu_cooling("review")


def test_unavailable_temperature_warns_without_blocking(monkeypatch, capsys):
    monkeypatch.setattr(gpu_lock, "query_gpu_temperature_c", lambda: None)
    gpu_lock.wait_for_gpu_cooling("review")
    gpu_lock.wait_for_gpu_cooling("review")
    assert capsys.readouterr().err.count("temperature unavailable") == 1


def test_losing_temperature_during_cooling_does_not_admit_work(monkeypatch):
    temperatures = iter([80, None])
    monkeypatch.setattr(gpu_lock, "query_gpu_temperature_c", lambda: next(temperatures))
    monkeypatch.setattr(gpu_lock.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="became unavailable"):
        gpu_lock.wait_for_gpu_cooling("review")


@pytest.mark.parametrize("candidate_budget", [None, 1.0])
def test_cooling_wait_is_bounded_and_releases_gpu_lease(monkeypatch, tmp_path, candidate_budget):
    clock = [0.0]
    monkeypatch.setattr(gpu_lock.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(gpu_lock.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(gpu_lock, "GPU_COOLING_TIMEOUT_SECONDS", 4.0)
    monkeypatch.setattr(gpu_lock, "query_gpu_temperature_c", lambda: 80)
    with pytest.raises(TimeoutError, match="cooling wait"):
        with gpu_lock.GlobalGpuLock(stage="reconstruction", deadline=candidate_budget):
            pytest.fail("Hot GPU admitted work")
    assert clock[0] == (candidate_budget or 4.0)
    assert not (tmp_path / "gpu.lock").exists()
    monkeypatch.setattr(gpu_lock, "query_gpu_temperature_c", lambda: 45)
    with gpu_lock.GlobalGpuLock(stage="next"):
        pass


def test_cooling_blocks_new_gpu_work_but_cpu_phase_and_active_work_continue(monkeypatch):
    from exercise_motion_pkg.staged_wave_service import WaveGpuGate

    cooling_started = threading.Event()
    active_finished = threading.Event()
    admitted = threading.Event()

    def temperature():
        cooling_started.set()
        return 74 if active_finished.is_set() else 80

    monkeypatch.setattr(gpu_lock, "query_gpu_temperature_c", temperature)
    monkeypatch.setattr(gpu_lock, "GPU_COOLING_POLL_SECONDS", 0.01)
    gate = WaveGpuGate()

    def next_gpu_operation():
        gpu_lock.wait_for_gpu_cooling("next_request")
        admitted.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with gate.phase("wave", "final_review"):
            pending = executor.submit(next_gpu_operation)
            try:
                assert cooling_started.wait(timeout=2)
                with gate.phase("wave", "cpu_preparation"):
                    assert not admitted.is_set()
                # The already active operation can finish while admission waits.
            finally:
                active_finished.set()
        pending.result(timeout=2)
    assert admitted.is_set()


def test_small_operation_checks_cooling_before_vram_admission(monkeypatch):
    calls = []
    monkeypatch.setattr(gpu_lock, "wait_for_gpu_cooling", lambda stage: calls.append(stage))
    monkeypatch.setattr(gpu_lock, "query_free_gpu_memory_mib", lambda: calls.append("vram") or 2000)
    with gpu_lock.small_gpu_stage_lock("pose", min_free_mib=600) as lease:
        assert lease.granted
    assert calls == ["pose", "vram"]


def test_llama_request_cools_without_reloading_and_preserves_timeout(monkeypatch):
    from exercise_motion_pkg import segment_detection

    requests = []
    client = segment_detection.LlamaCppVisionClient(base_url="http://localhost:8090", model="test")
    try:
        monkeypatch.setattr(segment_detection, "wait_for_gpu_cooling", lambda stage, **kwargs: 2.0)
        monkeypatch.setattr(client.client, "post", lambda url, **kwargs: requests.append(kwargs) or "response")
        assert client._post_chat_completion(timeout=10.0, json={}) == "response"
        assert requests[0]["timeout"] == 8.0
        assert client._client_generation == 0
        client.backend = "cpu"
        monkeypatch.setattr(segment_detection, "wait_for_gpu_cooling", lambda *args, **kwargs: pytest.fail("CPU request paused"))
        assert client._post_chat_completion(timeout=10.0, json={}) == "response"
    finally:
        client.close()


def test_cooling_failure_does_not_send_or_restart_llama_request(monkeypatch):
    from exercise_motion_pkg import segment_detection
    from exercise_motion_pkg.vlm_errors import CriticalVlmInteractionError

    def cooling_timeout(*args, **kwargs):
        raise TimeoutError("GPU cooling wait exceeded its budget")

    client = segment_detection.LlamaCppVisionClient(
        base_url="http://localhost:8090", model="test",
        recovery_callback=lambda: pytest.fail("Cooling failure restarted the model"),
    )
    try:
        monkeypatch.setattr(segment_detection, "wait_for_gpu_cooling", cooling_timeout)
        monkeypatch.setattr(client.client, "post", lambda *args, **kwargs: pytest.fail("Hot GPU received a request"))
        with pytest.raises(CriticalVlmInteractionError, match="cooling wait") as failure:
            client.caption_images(frame_paths=[], prompt="review")
        assert not failure.value.recoverable
        assert failure.value.cause_type == "GpuCooling"
    finally:
        client.close()


@pytest.mark.parametrize("output, expected", [("75\n81\n", 81), ("N/A\n75\n", None), ("", None)])
def test_temperature_probe_checks_both_cards(monkeypatch, output, expected):
    monkeypatch.setattr(gpu_lock.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=output))
    assert _temperature_probe() == expected
