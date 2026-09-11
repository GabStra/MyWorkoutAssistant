from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from exercise_motion_pkg.observation_cache import ObservationCache
from exercise_motion_pkg import bake_and_rank as bake


def test_content_cache_reuses_renamed_frame_and_invalidates_changes(tmp_path):
    first, second = tmp_path / "one.jpg", tmp_path / "two.jpg"
    first.write_bytes(b"same pixels")
    second.write_bytes(first.read_bytes())
    cache = ObservationCache(max_entries=2)
    calls = []
    def request(path, prompt="observe", model="one"):
        return cache.get_or_compute(frame_paths=[path], prompt=prompt, settings={"model": model},
            compute=lambda: calls.append(path) or str(len(calls)), cacheable=lambda _: True)
    assert request(first) == request(second) == "1"
    second.write_bytes(b"changed pixels")
    assert request(second) == "2"
    assert request(second, prompt="different") == "3"
    assert request(second, prompt="different", model="two") == "4"
    assert cache.metrics()["entries"] == 2
    assert cache.metrics()["hits"] == 1


def test_concurrent_identical_requests_share_one_computation(tmp_path):
    path = tmp_path / "image.jpg"
    path.write_bytes(b"pixels")
    cache = ObservationCache()
    started, release = threading.Event(), threading.Event()
    calls = []
    def compute():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return "observation"
    def request():
        return cache.get_or_compute(frame_paths=[path], prompt="observe", settings={},
            compute=compute, cacheable=lambda _: True, timeout=5)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(request)
        assert started.wait(5)
        second = executor.submit(request)
        deadline = time.monotonic() + 5
        while cache.metrics()["coalescedRequests"] != 1 and time.monotonic() < deadline:
            time.sleep(.01)
        release.set()
        assert first.result() == second.result() == "observation"
    assert len(calls) == 1
    assert cache.metrics()["coalescedRequests"] == 1


def test_errors_and_invalid_responses_are_not_cached(tmp_path):
    path = tmp_path / "image.jpg"
    path.write_bytes(b"pixels")
    cache = ObservationCache()
    def failed():
        raise RuntimeError("transient")
    kwargs = dict(frame_paths=[path], prompt="observe", settings={}, cacheable=lambda raw: raw == "valid")
    with pytest.raises(RuntimeError):
        cache.get_or_compute(**kwargs, compute=failed)
    assert cache.get_or_compute(**kwargs, compute=lambda: "malformed") == "malformed"
    assert cache.get_or_compute(**kwargs, compute=lambda: "valid") == "valid"
    assert cache.metrics()["misses"] == 3


def test_session_cache_survives_gpu_swaps_and_honors_deadline(tmp_path, monkeypatch):
    raw = '{"supportMode":"standing","kneeState":"extended","torsoOrientation":"upright","handHeight":"hip","stance":"narrow"}'
    calls = []
    class Ranker:
        def __init__(self, settings):
            self.client = SimpleNamespace(caption_images=lambda **kwargs: calls.append(kwargs) or raw)
        def close(self, **kwargs):
            pass
    monkeypatch.setattr(bake, "LlamaCppVisionRanker", Ranker)
    monkeypatch.setattr(bake.LazyLlamaCppVisionSession, "_release_cached_exclusive_models", staticmethod(lambda: None))
    session = bake.LazyLlamaCppVisionSession(bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json", workspace=tmp_path, wham_repo_path=None, body_model_root=None))
    path = tmp_path / "image.jpg"
    path.write_bytes(b"pixels")
    kwargs = dict(frame_paths=[path], prompt="observe", max_tokens=200)
    assert session.caption_endpoint_images(**kwargs) == raw
    session.run_without_llama_overlap(lambda: None)
    assert session.caption_endpoint_images(**kwargs) == raw
    assert len(calls) == 1
    assert session.startup_count == 1
    assert session.timing_manifest()["endpointObservationCache"]["hits"] == 1
    session.set_candidate_deadline(time.perf_counter() - 1)
    with pytest.raises(bake.CandidateWallTimeBudgetExpired):
        session.caption_endpoint_images(**kwargs)
    session.set_candidate_deadline(None)
    session.close()
    with pytest.raises(RuntimeError):
        session.caption_endpoint_images(**kwargs)
