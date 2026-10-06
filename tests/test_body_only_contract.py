import copy
import json

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.visual_evidence import body_evidence_exclusion, localize_review_evidence
from exercise_motion_pkg.review_consensus import corroborate_rejection


def claim(observation, **changes):
    return {"tag": "equipment_holding_pose_invalid", "basis": "body_motion",
            "defectType": "grip_contradiction", "bodyRegion": "hands", "frameIndices": [0],
            "bodyRelation": {"subject": "hands", "reference": "shoulders", "relation": "above"},
            "observation": observation, **changes}


def interpret(rows):
    parsed = bake.parse_final_output_validation_response(json.dumps({
        "approved": False, "confidence": .95, "retry": True,
        "reject": list(dict.fromkeys(row["tag"] for row in rows)),
        "rejectionEvidence": rows, "note": "Observed findings."}), min_score=.9)
    parsed = bake.enforce_body_only_rejection_evidence(parsed)
    return localize_review_evidence(parsed, {"frames": [{"joints": {}}]}, [0])


@pytest.mark.parametrize("observation", [
    "There is no barbell visible on the body.",
    "The subject is performing a bodyweight squat.",
    "The hands are raised, not holding a bar across the shoulders.",
    "The hands are above the shoulders, so this is an unweighted variation.",
    "The bench is missing.", "There are no rings visible.",
    "The subject is using dumbbells instead of a cable.",
    "The hands grip a bar above the chest, which is required for the movement.",
    "Hands below shoulders make this a dumbbell press instead of the target.",
    "The load is 20 kg instead of 40 kg.",
])
def test_mislabeled_equipment_assertions_cannot_reject_even_with_valid_body_fields(observation):
    result = interpret([claim(observation)])
    assert result["reviewStatus"] == "needs_manual_review"
    assert not result["needsRetry"] and not result["passed"]
    assert not result["localizedClaims"]
    assert result["excludedBodyEvidence"][0]["reason"] == "equipment_assertion_outside_final_review_scope"
    assert not corroborate_rejection(result, lambda: result)["boundedReview"]["corroborated"]


@pytest.mark.parametrize("relation", [None, {},
    {"subject": "hands", "reference": "shoulders", "relation": "above", "equipmentType": "barbell"},
    {"subject": ["hands"], "reference": "shoulders", "relation": "above"},
    {"subject": "barbell", "reference": "shoulders", "relation": "above"},
    {"subject": "hands", "reference": "machine", "relation": "near"},
    {"subject": "hands", "reference": "shoulders", "relation": "holding_barbell"}])
def test_arbitrary_objects_cannot_enter_body_relationship_schema(relation):
    row = claim("The hand position is wrong.", bodyRelation=relation)
    assert body_evidence_exclusion(row) == "observable_body_relationship_missing"


def test_real_hand_position_contradiction_remains_reviewable():
    row = claim("Both hands remain above the head throughout the shown frames.",
                bodyRelation={"subject": "hands", "reference": "head", "relation": "above"})
    result = interpret([row])
    assert result["localizedClaims"][0]["status"] == "observed"
    assert corroborate_rejection(result, lambda: copy.deepcopy(result))["boundedReview"]["corroborated"]


def test_body_weight_shift_description_is_not_equipment_identity():
    assert body_evidence_exclusion(claim("The torso shifts weight laterally relative to the hips.")) is None


def test_separate_body_claim_survives_equipment_claim_with_same_tag():
    result = interpret([claim("No barbell is visible."),
                        claim("The left hand stays above the right shoulder.",
                            bodyRelation={"subject": "left_hand", "reference": "right_shoulder", "relation": "above"})])
    assert len(result["localizedClaims"]) == 1
    assert corroborate_rejection(result, lambda: result)["boundedReview"]["corroborated"]


def test_actual_squat_review_mixed_claim_is_excluded_without_auto_approval():
    row = claim("The subject is performing a bodyweight squat or a squat without a barbell. "
        "The hands are raised in a guard position, not holding a bar across the upper back or shoulders. "
        "There is no barbell visible on the body.", tag="wrong_variant", defectType="wrong_action", bodyRegion="both_legs")
    result = interpret([row])
    assert result["reviewStatus"] == "needs_manual_review"
    assert not result["underlyingMotionRejected"] and not result["localizedClaims"]


def test_final_contract_does_not_promote_library_equipment_or_generated_mechanics():
    prompt = bake.build_final_output_source_contract_prompt_section({"motionContext": {
        "requiredEquipment": ["Distinctive training machine"], "requiredAccessories": ["Special attachment"]},
        "advisoryText": "Hands must hold the special attachment."})
    assert "Distinctive training machine" not in prompt and "Special attachment" not in prompt
    assert "Hands must hold" not in prompt
    assert '"equipmentIdentityOwner": "source_video_validation"' in prompt
    assert '"bodyParts"' in prompt


def test_corroboration_requires_same_body_relationship():
    a = interpret([claim("Hands remain above shoulders.")])
    b = interpret([claim("Hands remain below shoulders.",
                        bodyRelation={"subject": "hands", "reference": "shoulders", "relation": "below"})])
    assert not corroborate_rejection(a, lambda: b)["boundedReview"]["corroborated"]
