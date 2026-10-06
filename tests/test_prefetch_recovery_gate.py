from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import wave_pipeline as wave


@pytest.mark.parametrize("hint,expected", [
    ({"startSeconds": 96.396, "endSeconds": 102.402}, "96.40-102.40s"),
    (None, "automatic selection"),
])
def test_source_attempt_log_identifies_window_without_inventing_times(hint, expected):
    candidate = bake.RankedCandidate(0, 1, "squat", "Squat", "squat",
                                     {"videoId": "id", "sourceWindowHint": hint})
    assert wave.source_attempt_log_context(candidate, 2, 3) == (
        f"attempt 2/3 this turn | candidate window {expected}"
    )


@pytest.mark.parametrize("recoverable,cleaned_passes", [(True, True), (True, False), (False, True)])
def test_prefetch_uses_production_recovery_without_bypassing_rejections(tmp_path, monkeypatch,
                                                                     recoverable, cleaned_passes):
    raw, cleaned, preview = [tmp_path / name for name in ("raw.json", "cleaned.json", "preview.html")]
    for path in (raw, cleaned, preview):
        path.write_text("fixture")
    candidate = bake.RankedCandidate(0, 1, "curl", "Curl", "curl", {"videoId": "id"})
    request = bake.BakeAndRankRequest(candidates_json=tmp_path / "candidates.json", workspace=tmp_path,
                                      wham_repo_path=None, body_model_root=None)
    calls, renders = [], []

    def gate(path, **kwargs):
        calls.append(path)
        return {"passed": path == cleaned and cleaned_passes, "rejectionReasons": ["original defect"]}

    monkeypatch.setattr(bake, "evaluate_raw_wham_motion_gate", gate)
    monkeypatch.setattr(bake, "raw_wham_motion_gate_allows_cleaned_recovery", lambda result: recoverable)
    monkeypatch.setattr(bake, "pre_wham_source_interval_authority", lambda **kwargs: {})
    monkeypatch.setattr(bake, "pre_wham_source_foot_support_evidence", lambda workspace: {})
    monkeypatch.setattr(bake, "load_motion_json", lambda path: path)
    monkeypatch.setattr(bake, "build_candidate_review_eligible_loops", lambda *args, **kwargs: [])

    def render(*args, **kwargs):
        assert kwargs["caption_images"] is None
        renders.append(args)
        return []

    monkeypatch.setattr(bake, "bake_preview_loops_with_playwright", render)
    result = wave.prepare_cpu_render_cache(wave.StagedWaveItem("curl", "Curl", request), candidate,
        SimpleNamespace(raw_motion_json_path=raw, cleaned_motion_json_path=cleaned, preview_html_path=preview), {})
    assert calls == ([raw, cleaned] if recoverable else [raw])
    assert bool(renders) is (recoverable and cleaned_passes)
    assert result["status"] == ("prepared" if recoverable and cleaned_passes else "skipped")
