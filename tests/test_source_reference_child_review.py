import hashlib
import json
import copy

import pytest
from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.source_evidence import (
    source_reference_review_context,
    source_reference_review_context_sha256,
)
from exercise_motion_pkg.segment_detection import DetectionWindow


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _target_and_mapping():
    phases = ["Lower through knee extension", "Return upright through knee flexion"]
    source_context = {"exerciseDefinition": {
        "definingAction": "Lower forward from anchored kneeling, then return upright.",
        "variantQualifiers": ["Kneeling Nordic curl with ankles anchored."],
        "requiredPhases": phases,
        "completionMode": "return_to_start",
        "bilateralExecution": {"arms": "none", "legs": "symmetric"},
    }}
    source_context_sha = hashlib.sha256(json.dumps(
        source_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    target = {
        "exerciseName": "Weighted Vest Nordic Curl",
        "contractPolicyVersion": 39,
        "definingAction": "Perform a weighted vest Nordic curl.",
        "variantQualifiers": ["Wear a weighted vest."],
        "requiredPhases": phases,
        "completionMode": "return_to_start",
        "motionContext": {
            "primaryEquipment": {"id": "vest", "type": "WEIGHTVEST", "name": "Weighted vest"},
            "requiredAccessories": [{"id": "anchor", "type": "ACCESSORY", "name": "Nordic Setup"}],
            "exerciseDefinition": {
                "requiredPhases": phases,
                "completionMode": "return_to_start",
                "bilateralExecution": {"arms": "none", "legs": "symmetric"},
            },
        },
    }
    target_bytes = json.dumps(target, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    mapping = {
        "sourceExerciseId": "source-nordic",
        "sourceExerciseName": "Nordic Curl",
        "exerciseId": "target-nordic",
        "exerciseName": target["exerciseName"],
        "motionReferenceOnly": True,
        "allowedDifference": "external_load_not_shown",
        "approvalAllowedDifference": "The external vest load need not be visible.",
        "approvalAuthority": "explicit_user_approval",
        "approvalUserAnswerPresent": True,
        "exportedExerciseUnchanged": True,
        "mappingSha256": _sha("mapping"),
        "approvalSha256": _sha("approval"),
        "motionContext": {"equipment": "weighted vest"},
        "sourceMotionContext": source_context,
        "sourceMotionContextSha256": source_context_sha,
    }
    return target, mapping


def test_child_scorecard_prompt_waives_only_mapped_load_and_binds_authority():
    target, mapping = _target_and_mapping()
    context = source_reference_review_context(
        mapping, target_exercise_name=target["exerciseName"], target_contract=target,
    )
    candidate = bake.SourceCutCandidate(
        candidate_id="NORDIC-A", window=DetectionWindow(0, 0.0, 3.3667), frame_paths=[],
    )
    prompt = bake.build_source_cut_child_review_prompt(
        exercise_name=target["exerciseName"], candidate_title=target["exerciseName"],
        candidate=candidate, exercise_motion_contract=target, extension=False,
        source_reference_context=context,
    ).casefold()

    assert "primary visible-motion identity: nordic curl" in prompt
    assert "external load alone is not an identity mismatch" in prompt
    assert "nordic setup" in prompt
    assert "lower through knee extension" in prompt
    assert "return upright through knee flexion" in prompt
    assert "weighted vest must be visible" not in prompt
    tampered_context = copy.deepcopy(context)
    tampered_context["sourceMotionContext"]["exerciseDefinition"]["definingAction"] = "changed after approval"
    with pytest.raises(ValueError, match="source motion context digest mismatch"):
        bake.build_source_cut_child_review_prompt(
            exercise_name=target["exerciseName"], candidate_title=target["exerciseName"],
            candidate=candidate, exercise_motion_contract=target, extension=False,
            source_reference_context=tampered_context,
        )

    context_sha = source_reference_review_context_sha256(context)
    visual_spec = bake.source_reference_visual_review_cache_identity(target, context)
    binding = {
        "sourceReferenceReviewContextSha256": context_sha,
        **visual_spec,
    }
    candidate_row = {"passed": True, "sourceReviewAuthorityBinding": binding}
    coverage = {}
    mismatch = bake.source_cut_child_semantic_review_approval(
        candidate_row, {"candidateId": "NORDIC-A"}, coverage,
        expected_source_reference_review_context_sha256=_sha("different"),
        expected_source_reference_visual_review_spec=visual_spec,
    )
    matching_context = bake.source_cut_child_semantic_review_approval(
        candidate_row, {"candidateId": "NORDIC-A"}, coverage,
        expected_source_reference_review_context_sha256=context_sha,
        expected_source_reference_visual_review_spec=visual_spec,
    )
    assert mismatch["reason"] == "child_semantic_review_source_reference_context_mismatch"
    assert matching_context["reason"] == "child_semantic_review_candidate_mismatch"


def test_single_sample_endpoint_image_is_deduplicated(tmp_path):
    one_sample = tmp_path / "frame.jpg"
    one_sample.write_bytes(b"frame")
    candidate = bake.SourceCutCandidate(
        candidate_id="A", window=DetectionWindow(0, 0.0, 1.0), frame_paths=[],
        sample_frame_paths=[one_sample],
    )

    evidence = bake.source_cut_review_frame_evidence([candidate], source_frame_count=1)[0]

    assert evidence["endpointFramePaths"] == [str(one_sample.resolve())]
    assert [row["path"] for row in evidence["images"]] == [str(one_sample.resolve())]
