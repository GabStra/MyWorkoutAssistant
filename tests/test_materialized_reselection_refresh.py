import json

import pytest

from exercise_motion_pkg import bake_and_rank as bake


def make_review_item(tmp_path):
    candidate_workspace = tmp_path / "candidate"
    skeleton_path = candidate_workspace / "wear" / "selected.json"
    skeleton_path.parent.mkdir(parents=True)
    payload = {
        "kind": "wearPreviewSkeleton",
        "fps": 30,
        "frameCount": 2,
        "jointNames": ["pelvis"],
        "rootJoint": "pelvis",
        "frames": [
            {"joints": {"pelvis": [0.0, 0.0, 0.0]}},
            {"joints": {"pelvis": [0.0, 0.1, 0.0]}},
        ],
    }
    bake.artifact_state_for_baked_payload(
        payload,
        contract=None,
        selection_class=bake.FULL_CLIP_BAKE,
    )
    skeleton_path.write_text(json.dumps(payload), encoding="utf-8")
    return bake.ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Movement",
        candidate_title="Movement demo",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=skeleton_path,
        review_video_path=candidate_workspace / "review" / "selected.webm",
        duration_sec=2.0,
        loop_start_seconds=0.0,
        loop_end_seconds=2.0,
        candidate={"videoId": "reviewed-source"},
    )


def stale_rejection_ranking():
    return bake.LoopRanking(
        score=0.49,
        model_score=0.49,
        reasons=[
            "source_interval_approved",
            "materialized_output_rejected",
            "materialized_leg_articulation_changed_by_cleanup",
        ],
        payload={
            "score": 0.95,
            "modelScore": 0.91,
            "materializedOutputRejected": True,
            "materializedOutputRejectionReasons": [
                "materialized_leg_articulation_changed_by_cleanup"
            ],
            "materializedHardRejectionReasons": [
                "materialized_leg_articulation_changed_by_cleanup"
            ],
            "materializedWarnings": [
                "final_output_vlm_skipped_deterministic_hard_rejection"
            ],
            "finalOutputValidation": {
                "passed": False,
                "hardRejectionReasons": [
                    "materialized_leg_articulation_changed_by_cleanup"
                ],
                "visualReview": {"score": 0.87, "status": "previously_skipped"},
            },
        },
    )


def configure_reselection_gate(monkeypatch, *, passed, rejection_reasons=()):
    monkeypatch.setattr(
        bake,
        "source_selection_clearance_for_review_item",
        lambda *_args, **_kwargs: {"status": "cleared"},
    )
    monkeypatch.setattr(
        bake,
        "materialized_metrics_with_gpu_handoff",
        lambda *_args, **_kwargs: {
            "passed": passed,
            "rejectionReasons": list(rejection_reasons),
        },
    )
    monkeypatch.setattr(
        bake,
        "final_output_validation_metrics",
        lambda *_args, **_kwargs: {
            "enabled": True,
            "backend": "stub",
            "passed": passed,
            "score": 0.88,
            "hardRejectionReasons": list(rejection_reasons),
            "deterministicBlockingReasons": list(rejection_reasons),
            "rejectionReasons": list(rejection_reasons),
            "visualReview": {"score": 0.87, "status": "observed"},
        },
    )


def test_reselection_refresh_clears_old_materialized_rejection_and_selects_current_pass(
    tmp_path,
    monkeypatch,
):
    item = make_review_item(tmp_path)
    ranking = stale_rejection_ranking()
    configure_reselection_gate(monkeypatch, passed=True)
    monkeypatch.setattr(
        bake,
        "materialized_weighted_selection_score",
        lambda **_kwargs: (0.91, {"finalScore": 0.91}),
    )

    refreshed = bake.apply_materialized_output_acceptance_gate(
        (item, ranking),
        request=bake.BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path,
            body_model_root=None,
            final_output_validation=True,
        ),
    )
    _item, refreshed_ranking = refreshed

    assert bake.choose_top_review_items([_item], [refreshed_ranking], min_score=0.55) == [refreshed]
    assert refreshed_ranking.score == pytest.approx(0.91)
    assert refreshed_ranking.model_score == pytest.approx(0.91)
    assert refreshed_ranking.payload["score"] == pytest.approx(0.91)
    assert refreshed_ranking.payload["modelScore"] == pytest.approx(0.91)
    assert refreshed_ranking.payload["sourceCandidateScore"] == pytest.approx(0.95)
    assert refreshed_ranking.payload["sourceCandidateModelScore"] == pytest.approx(0.91)
    assert refreshed_ranking.payload["materializedOutputRejected"] is False
    assert refreshed_ranking.payload["materializedOutputRejectionReasons"] == []
    assert refreshed_ranking.payload["materializedHardRejectionReasons"] == []
    assert refreshed_ranking.payload["materializedWarnings"] == []
    assert refreshed_ranking.payload["finalOutputValidation"]["visualReview"]["score"] == pytest.approx(0.87)
    assert refreshed_ranking.reasons == ["source_interval_approved"]


def test_reselection_refresh_keeps_new_hard_rejection_and_source_reason(
    tmp_path,
    monkeypatch,
):
    item = make_review_item(tmp_path)
    ranking = stale_rejection_ranking()
    current_failure = "materialized_support_contact_failure"
    configure_reselection_gate(
        monkeypatch,
        passed=False,
        rejection_reasons=[current_failure],
    )

    refreshed = bake.apply_materialized_output_acceptance_gate(
        (item, ranking),
        request=bake.BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path,
            body_model_root=None,
            final_output_validation=True,
        ),
    )
    _item, refreshed_ranking = refreshed

    assert bake.choose_top_review_items([_item], [refreshed_ranking], min_score=0.55) == []
    assert refreshed_ranking.score == pytest.approx(0.49)
    assert refreshed_ranking.model_score == pytest.approx(0.49)
    assert refreshed_ranking.payload["score"] == pytest.approx(0.49)
    assert refreshed_ranking.payload["modelScore"] == pytest.approx(0.49)
    assert refreshed_ranking.payload["sourceCandidateScore"] == pytest.approx(0.95)
    assert refreshed_ranking.payload["sourceCandidateModelScore"] == pytest.approx(0.91)
    assert refreshed_ranking.payload["materializedOutputRejected"] is True
    assert refreshed_ranking.payload["materializedOutputRejectionReasons"] == [current_failure]
    assert refreshed_ranking.payload["materializedHardRejectionReasons"] == [current_failure]
    assert "materialized_output_rejected" in refreshed_ranking.reasons
    assert current_failure in refreshed_ranking.reasons
    assert "materialized_leg_articulation_changed_by_cleanup" not in refreshed_ranking.reasons
    assert "source_interval_approved" in refreshed_ranking.reasons
