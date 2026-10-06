import json
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake


@pytest.mark.parametrize("source_key,span_key", [
    ("detectionSourceVideoPath", "selectedSpan"),
    ("sourceVideoPath", "selectedSpanInOriginalSource"),
])
def test_failed_candidate_retains_source_context_for_identical_resume(
    tmp_path, monkeypatch, source_key, span_key
):
    candidate = tmp_path / "candidate"
    source = candidate / "source" / "source.mp4"
    selected = candidate / "input" / "selected_segment.mp4"
    garbage = candidate / "review" / "frame_001.png"
    selection = candidate / "segment_detection" / "segment_selection.json"
    for path in (source, selected, garbage, selection):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    selection.write_text(json.dumps({
        source_key: str(source),
        span_key: {"startSeconds": 4.0, "endSeconds": 8.0},
    }), encoding="utf-8")
    preparations = []
    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda path: SimpleNamespace(
        duration_seconds=12.0, fps=30.0
    ))
    monkeypatch.setattr(bake, "prepare_cached_wham_video", lambda **kwargs: preparations.append(kwargs))

    def prepare():
        return bake.prepare_wham_inference_video(
            candidate_workspace=candidate, selected_video_path=selected, padding_seconds=2.0
        )

    before = prepare()
    report = bake.apply_artifact_retention_policy(tmp_path, {"candidateResults": [{
        "candidateWorkspace": str(candidate), "status": "rejected_raw_wham_validation",
        "inputVideoPath": str(selected),
    }]})
    assert not report["errors"]
    assert source.exists()
    assert selection.exists()
    assert not garbage.exists()
    assert prepare() == before
    assert preparations[0] == preparations[1]
    assert preparations[1]["source_path"] == source
    assert before[1:] == (2.0, 6.0)


def test_source_context_protection_ignores_missing_or_outside_paths(tmp_path):
    workspace = tmp_path / "workspace"
    candidate = workspace / "candidate"
    selection = candidate / "segment_detection" / "segment_selection.json"
    selection.parent.mkdir(parents=True)
    external = tmp_path / "external.mp4"
    external.write_bytes(b"external")
    selection.write_text(json.dumps({
        "sourceVideoPath": str(external),
        "detectionSourceVideoPath": str(candidate / "missing.mp4"),
    }), encoding="utf-8")
    protected = bake.collect_artifact_retention_protected_paths(workspace, {
        "candidateResults": [{"candidateWorkspace": str(candidate)}]
    })
    assert external.resolve() not in protected
