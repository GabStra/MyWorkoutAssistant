import json
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake


def test_malformed_review_does_not_request_motion_regeneration():
    result = bake.parse_final_output_validation_response('{"approved": true,', min_score=.9)
    assert result["failureOwner"] == "review"
    assert result["reviewStatus"] == "needs_manual_review"
    assert not result["underlyingMotionRejected"]
    assert not result["needsRetry"]
    assert not result["passed"]
    assert result["rejectionReasons"] == ["final_output_validator_invalid_json"]


@pytest.mark.parametrize("final_approved", [True, False])
def test_final_review_uses_answer_after_reasoning_boundary(final_approved):
    reasoning = json.dumps({"approved": not final_approved, "confidence": .99, "retry": False})
    answer = json.dumps({"approved": final_approved, "confidence": .95, "retry": False, "reject": []})
    result = bake.parse_final_output_validation_response(reasoning + "\n</think>\n" + answer, min_score=.9)
    assert result["approved"] is final_approved


def review(tags, evidence):
    return bake.enforce_body_only_rejection_evidence(
        bake.parse_final_output_validation_response(json.dumps({
            "approved": False, "confidence": .95, "retry": True,
            "reject": tags, "rejectionEvidence": evidence,
            "note": "Review finding.",
        }), min_score=.9)
    )


@pytest.mark.parametrize("prop", ["barbell", "dumbbells", "bench", "rings", "cable"])
def test_omitted_prop_is_review_failure_not_motion_failure(prop):
    result = review(["wrong_variant"], [{
        "tag": "wrong_variant", "basis": "omitted_equipment",
        "observation": f"The skeleton has no visible {prop}.",
    }])
    assert result["failureOwner"] == "review"
    assert not result["underlyingMotionRejected"]
    assert not result["needsRetry"]
    assert not result["passed"]  # Missing evidence must not grant approval.


def test_contradictory_body_mechanics_remain_rejected():
    result = review(["wrong_variant"], [{
        "tag": "wrong_variant", "basis": "body_motion",
        "observation": "Both arms stay below the shoulders throughout the squat.",
        "bodyRelation": {"subject": "hands", "reference": "shoulders", "relation": "below"},
    }])
    assert result["underlyingMotionRejected"]
    assert "wrong_variant" in result["hardRejectionReasons"]


def test_missing_evidence_does_not_authorize_wrong_variant_rejection():
    result = review(["wrong_variant"], [])
    assert result["reviewStatus"] == "needs_manual_review"


def test_omitted_prop_does_not_erase_independent_corruption():
    result = review(["wrong_variant", "severe_tracking_corruption"], [{
        "tag": "wrong_variant", "basis": "omitted_equipment",
        "observation": "No bench is visible.",
    }])
    assert "wrong_variant" not in result["hardRejectionReasons"]
    assert "severe_tracking_corruption" in result["hardRejectionReasons"]
    assert result["underlyingMotionRejected"]


def test_evidenced_support_failure_survives_omitted_equipment_judgment():
    result = review(["wrong_variant", "support_mode_mismatch"], [
        {"tag": "wrong_variant", "basis": "omitted_equipment", "observation": "No rings."},
        {"tag": "support_mode_mismatch", "basis": "body_motion",
         "bodyRelation": {"subject": "hands", "reference": "hips", "relation": "near"},
         "observation": "Hands remain at the hips through the entire pull-up."},
    ])
    assert "support_mode_mismatch" in result["hardRejectionReasons"]
    assert result["failureOwner"] == "motion_output"


@pytest.mark.parametrize("foot_lift,expected_owner", [(0.4, "review"), (0.0, "motion_output")])
def test_planted_feet_claim_checked_against_exported_motion(tmp_path, foot_lift, expected_owner):
    frames = [{"joints": {
        "left_wrist": [0, 2, 0], "right_wrist": [.2, 2, 0],
        "left_foot": [0, foot_lift * index / 9, 0],
        "right_foot": [.2, foot_lift * index / 9, 0],
    }} for index in range(10)]
    path = tmp_path / "skeleton.json"
    path.write_text(json.dumps({"groundContactMode": "none", "frames": frames}))
    parsed = review(["wrong_variant"], [{
        "tag": "wrong_variant", "basis": "body_motion",
        "observation": "The feet remain planted on the ground throughout.",
        "bodyRelation": {"subject": "feet", "reference": "pelvis", "relation": "below"},
    }])
    result = bake.enforce_body_only_rejection_evidence(parsed, item=SimpleNamespace(skeleton_path=path))
    assert result["failureOwner"] == expected_owner
    assert not result["passed"]
