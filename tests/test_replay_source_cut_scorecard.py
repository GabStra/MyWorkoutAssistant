import json

from scripts.replay_source_cut_scorecard import debug_identity


def test_debug_identity_finds_selection_manifest_at_workspace_ancestor(tmp_path):
    workspace = tmp_path / "workspace"
    debug_path = workspace / "source_candidate_A" / "replay" / "vlm_review_debug.json"
    debug_path.parent.mkdir(parents=True)
    selection_path = workspace / "segment_selection.json"
    selection_path.write_text(
        json.dumps(
            {
                "sourceVideoPath": str(
                    workspace
                    / "single-arm-dumbbell-windmill-WeLKI4z41j8"
                    / "input"
                    / "selected_segment.mp4"
                )
            }
        ),
        encoding="utf-8",
    )
    debug_path.write_text("{}", encoding="utf-8")

    assert debug_identity(debug_path, {"candidateId": "A"}) == (
        "WeLKI4z41j8",
        "A",
    )
