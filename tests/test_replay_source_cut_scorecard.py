import json
import sys
import pytest

from scripts.replay_source_cut_scorecard import debug_identity


@pytest.mark.parametrize("backend", ["qwen-chat", "clef-systemone"])
def test_live_replay_preserves_backend_and_filters_routing_options(
    tmp_path, monkeypatch, backend, capsys
):
    from scripts import replay_source_cut_scorecard as replay

    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"retained frame")
    debug = tmp_path / "candidate" / "vlm_review_debug.json"
    debug.parent.mkdir()
    debug.write_text(json.dumps({
        "candidateId": "A", "window": {"startSeconds": 0, "endSeconds": 2},
        "framePaths": [str(frame)], "prompt": "review",
        "requestKwargs": {"max_tokens": 48, "clef_visual_decision_backend": backend},
    }))
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({
        "exerciseName": "Barbell Floor Press",
        "motionContext": {
            "primaryEquipment": {"name": "barbell"},
            "requiredAccessories": [{
                "name": "squat rack",
                "capabilities": ["RACKED_BAR_SUPPORT"],
            }],
        },
    }))
    calls = []

    class Session:
        def __init__(self, request):
            calls.append("constructed")

        def caption_images(self, *, frame_paths, prompt, max_tokens):
            calls.append((frame_paths, prompt, max_tokens))
            return "{}"

        def close(self):
            calls.append("closed")

        def timing_manifest(self):
            return {}

    monkeypatch.setattr(replay, "LazyLlamaCppVisionSession", Session)
    monkeypatch.setattr(sys, "argv", ["replay", str(debug), "--contract", str(contract)])
    if backend == "clef-systemone":
        raw = json.dumps({
            "candidates": [{
                "id": "A",
                "approved": True,
                "confidence": 0.9,
                "completeMovement": True,
                "startBoundaryClean": True,
                "finishBoundaryClean": True,
                "setupOrFiller": False,
                "namedEquipmentEngagedStatus": "not_applicable",
                "identityMatch": "match",
                "identityEvidence": "The target action is visible.",
                "reject": [],
                "note": "approved",
            }],
            "clefSystemOne": {
                "decisions": {
                    "approval": {"choice": "approved"},
                    "identity": {"choice": "match"},
                },
                "rawSystemOneResponse": {"mock": "native"},
            },
        })
        native_calls = []
        monkeypatch.setattr(replay, "request_clef_source_cut_scorecard", lambda **kwargs: (
            native_calls.append(kwargs) or raw
        ))
        def managed_owner(**kwargs):
            native_calls.append({"managedBaseUrl": kwargs["base_url"]})
            assert kwargs.get("exclusive_runner") is None
            return kwargs["operation"]()

        monkeypatch.setattr(replay.clef_systemone, "run_clef_visual_decision_exclusively", managed_owner)
        assert replay.main() == 0
        assert calls == []
        assert len(native_calls) == 2
        assert native_calls[1]["equipment_policy"] == replay.two_scale_equipment_role_policy(
            "Barbell Floor Press",
            {
                "exerciseName": "Barbell Floor Press",
                "motionContext": {
                    "primaryEquipment": {"name": "barbell"},
                    "requiredAccessories": [{
                        "name": "squat rack",
                        "capabilities": ["RACKED_BAR_SUPPORT"],
                    }],
                },
            },
        )
        report = json.loads(capsys.readouterr().out)
        assert report["backend"] == "clef-systemone"
        assert report["modelCalls"] == 1
        assert report["cases"][0]["backend"] == "clef-systemone"
        assert report["cases"][0]["requestPayloadIdentity"].startswith("sha256:")
        assert report["typedDecisionDistribution"]["approval"]["approved"] == 1
    else:
        assert replay.main() == 0
        assert calls == ["constructed", ([frame], "review", 48), "closed"]
        report = json.loads(capsys.readouterr().out)
        assert report["backend"] == "qwen-chat"


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
