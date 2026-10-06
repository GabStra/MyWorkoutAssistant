from __future__ import annotations

from pathlib import Path

import exercise_motion_pkg.gpu_lock as gpu_lock_module
from exercise_motion_pkg.bake_and_rank import BakeAndRankRequest, LazyLlamaCppVisionSession
from exercise_motion_pkg.gpu_lock import GlobalGpuLock, small_gpu_stage_lock


def _session(tmp_path: Path) -> LazyLlamaCppVisionSession:
    # auto_start_server=False keeps the exclusive fallback from touching any
    # real llama-server process during tests.
    return LazyLlamaCppVisionSession(BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json", workspace=tmp_path,
        wham_repo_path=None, body_model_root=None,
        llama_cpp_auto_start_server=False,
    ))


def test_small_gpu_stage_lock_grants_when_vram_allows(monkeypatch) -> None:
    monkeypatch.setattr(gpu_lock_module, "query_free_gpu_memory_mib", lambda: 2000)
    with small_gpu_stage_lock("yolo_pose_prefilter", min_free_mib=600) as lease:
        assert lease.granted
        assert lease.free_mib == 2000
        # Inner global locks become no-ops inside a granted section, so callees
        # that take the global GPU lock need no changes.
        inner = GlobalGpuLock(stage="yolo_pose_prefilter")
        assert inner.__enter__() == 0.0
        inner.__exit__(None, None, None)
        assert inner._handle is None


def test_free_vram_probe_caches_within_window(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(gpu_lock_module, "_probe_free_gpu_memory_mib", lambda: calls.append(1) or 1234)
    # Force the cache to expire so the first call probes.
    monkeypatch.setattr(gpu_lock_module, "_FREE_VRAM_CACHE", (0.0, None))
    assert gpu_lock_module.query_free_gpu_memory_mib() == 1234
    assert gpu_lock_module.query_free_gpu_memory_mib() == 1234
    assert len(calls) == 1  # second call served from the cache


def test_small_gpu_stage_lock_declines_below_threshold(monkeypatch) -> None:
    monkeypatch.setattr(gpu_lock_module, "query_free_gpu_memory_mib", lambda: 300)
    with small_gpu_stage_lock("yolo_pose_prefilter", min_free_mib=600) as lease:
        assert not lease.granted
        assert lease.free_mib == 300


def test_small_gpu_stage_lock_declines_when_probe_unknown(monkeypatch) -> None:
    monkeypatch.setattr(gpu_lock_module, "query_free_gpu_memory_mib", lambda: None)
    with small_gpu_stage_lock("unidepth", min_free_mib=1400) as lease:
        assert not lease.granted
        assert lease.free_mib is None


def test_nested_small_gpu_sections_stay_granted(monkeypatch) -> None:
    monkeypatch.setattr(gpu_lock_module, "query_free_gpu_memory_mib", lambda: 4000)
    with small_gpu_stage_lock("yolo_pose_prefilter", min_free_mib=600) as outer:
        assert outer.granted
        with small_gpu_stage_lock("unidepth", min_free_mib=1400) as inner:
            assert inner.granted


def test_session_runs_small_op_co_resident_without_exclusive_batch(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    monkeypatch.setattr(gpu_lock_module, "query_free_gpu_memory_mib", lambda: 5000)
    calls: list[int] = []
    result = session.run_without_llama_overlap(
        lambda: (calls.append(1), "ok")[1],
        small_stage="yolo_pose_prefilter",
        small_min_free_mib=600,
    )
    assert result == "ok"
    assert calls == [1]
    manifest = session.timing_manifest()
    assert manifest["coResidentGpuOperationCount"] == 1
    assert manifest["exclusiveGpuBatchCount"] == 0


def test_session_falls_back_to_exclusive_when_declined(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    monkeypatch.setattr(gpu_lock_module, "query_free_gpu_memory_mib", lambda: 100)
    result = session.run_without_llama_overlap(
        lambda: "exclusive",
        small_stage="yolo_pose_prefilter",
        small_min_free_mib=600,
    )
    assert result == "exclusive"
    manifest = session.timing_manifest()
    assert manifest["coResidentGpuDeclinedCount"] == 1
    assert manifest["coResidentGpuOperationCount"] == 0
    assert manifest["exclusiveGpuBatchCount"] == 1


def test_session_oom_race_falls_back_to_exclusive(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    monkeypatch.setattr(gpu_lock_module, "query_free_gpu_memory_mib", lambda: 5000)
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("CUDA out of memory")
        return "recovered"

    result = session.run_without_llama_overlap(
        flaky,
        small_stage="yolo_pose_prefilter",
        small_min_free_mib=600,
    )
    assert result == "recovered"
    assert len(calls) == 2
    manifest = session.timing_manifest()
    assert manifest["coResidentGpuOomFallbackCount"] == 1
    assert manifest["exclusiveGpuBatchCount"] == 1


def test_session_without_small_hint_keeps_exclusive_semantics(tmp_path) -> None:
    session = _session(tmp_path)
    result = session.run_without_llama_overlap(lambda: "exclusive-only")
    assert result == "exclusive-only"
    manifest = session.timing_manifest()
    assert manifest["exclusiveGpuBatchCount"] == 1
    assert manifest["coResidentGpuOperationCount"] == 0
