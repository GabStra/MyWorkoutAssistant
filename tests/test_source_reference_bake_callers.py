import hashlib
import json

from exercise_motion_pkg.bake_and_rank import (
    DetectionWindow,
    SourceCutCandidate,
    build_source_cut_candidate_choice_prompt,
)
from exercise_motion_pkg.source_evidence import (
    source_reference_review_context,
    source_reference_visual_review_contract,
)


def _context():
    source_motion = {"exerciseDefinition": {
        "definingAction": "Hang from a bar, pull up, then lower back to hang.",
        "completionMode": "return_to_start",
        "variantQualifiers": ["Strict pull-up without kipping."],
        "requiredPhases": ["Pull upward", "Lower back to hang"],
        "bilateralExecution": {"arms": "mirrored"},
    }}
    source_digest = hashlib.sha256(json.dumps(
        source_motion, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    mapping = {
        "sourceExerciseId": "source-pullup",
        "sourceExerciseName": "Pull-Up",
        "exerciseId": "target-weighted-pullup",
        "exerciseName": "Weighted Vest Pull-Up",
        "motionReferenceOnly": True,
        "allowedDifference": "external_load_not_shown",
        "approvalAllowedDifference": "Vest visibility is waived for this motion reference.",
        "approvalAuthority": "explicit_user_approval",
        "exportedExerciseUnchanged": True,
        "approvalUserAnswerPresent": True,
        "mappingSha256": "a" * 64,
        "approvalSha256": "b" * 64,
        "motionContext": {"equipment": "weighted vest"},
        "sourceMotionContext": source_motion,
        "sourceMotionContextSha256": source_digest,
    }
    contract = {
        "exerciseName": "Weighted Vest Pull-Up",
        "contractPolicyVersion": 39,
        "definingAction": "Hang while wearing a weighted vest, pull up, then lower back to hang.",
        "completionMode": "return_to_start",
        "variantQualifiers": ["Strict weighted vest pull-up without kipping."],
        "requiredPhases": ["Pull upward", "Lower back to hang"],
        "bilateralExecution": {"arms": "mirrored"},
        "motionContext": {
            "exerciseDefinition": {"bilateralExecution": {"arms": "mirrored"}},
            "primaryEquipment": {"id": "vest", "name": "Weight Vest", "type": "WEIGHTVEST"},
            "requiredAccessories": [{"id": "station", "name": "Pull-Up Station", "type": "ACCESSORY"}],
        },
    }
    return contract, source_reference_review_context(
        mapping, target_exercise_name=contract["exerciseName"], target_contract=contract,
    )


def _prompt(context):
    contract, _ = _context()
    candidate = SourceCutCandidate(
        "A", DetectionWindow(0, 0.0, 3.0), [], sample_frame_paths=[],
    )
    return build_source_cut_candidate_choice_prompt(
        exercise_name="Weighted Vest Pull-Up",
        candidate_title="",
        candidate=candidate,
        exercise_motion_contract=contract,
        source_reference_context=context,
    )


def test_scorecard_prompt_scopes_approved_external_load_visibility_waiver():
    _, context = _context()
    prompt = _prompt(context)

    assert "Source exercise: Pull-Up." in prompt
    assert "Primary visible-motion identity: Pull-Up" in prompt
    assert "Unchanged export target: Weighted Vest Pull-Up" in prompt
    assert "Source-authored visible action: Hang from a bar, pull up, then lower back to hang." in prompt
    assert 'Unchanged target required phases in order: ["Pull upward", "Lower back to hang"]' in prompt
    assert "Pull-Up Station" in prompt
    assert "waives only visibility of the target external load" in prompt
    assert "absence of the weighted vest or other external load alone is not an identity mismatch" in prompt.lower()
    assert "A different action, grip, support setup, or other non-waived variant remains a rejection" in prompt
    assert "required phases" in prompt
    assert "wearing a weighted vest" not in prompt
    assert "Weighted Vest: active implement" not in prompt
    assert "When the target says weighted or loaded, a real external load/resistance must be visible" not in prompt
    assert "unless an actual load or resistance is visibly attached or held" not in prompt


def test_scorecard_prompt_keeps_load_visibility_required_without_mapping():
    prompt = _prompt(None)

    assert "When the target says weighted or loaded, a real external load/resistance must be visible" in prompt
    assert "unless an actual load or resistance is visibly attached or held" in prompt
    assert "Absence of the weighted vest or other external load alone is not an identity mismatch" not in prompt


def test_mapped_visual_cache_identity_is_policy_bound_and_unmapped_identity_is_unchanged():
    from exercise_motion_pkg.bake_and_rank import source_reference_visual_review_cache_identity
    from exercise_motion_pkg.source_evidence import SOURCE_REFERENCE_VISUAL_REVIEW_SPEC_POLICY_VERSION

    contract, context = _context()
    identity = source_reference_visual_review_cache_identity(contract, context)
    assert identity == {
        "sourceReferenceVisualReviewSpecPolicyVersion": SOURCE_REFERENCE_VISUAL_REVIEW_SPEC_POLICY_VERSION,
        "sourceReferenceVisualReviewSpecSha256": identity["sourceReferenceVisualReviewSpecSha256"],
    }
    assert len(identity["sourceReferenceVisualReviewSpecSha256"]) == 64
    assert source_reference_visual_review_cache_identity(contract, None) == {}

    visual = source_reference_visual_review_contract(contract, context)
    assert visual["exerciseName"] == "Pull-Up"
    assert "primaryEquipment" not in visual["motionContext"]
    assert contract["exerciseName"] == "Weighted Vest Pull-Up"
