import hashlib
import json
from pathlib import Path

import pytest
from exercise_motion_pkg.bake_and_rank import (
    BakeAndRankRequest, RankedCandidate, _source_review_contract_exercise,
)
from exercise_motion_pkg.cli import (
    ApprovedSourceReferenceContextError,
    approved_source_reference_target_for_staged_plan,
)
from exercise_motion_pkg.wave_pipeline import StagedWaveItem, _candidate_key, _source_review_request


def _json_sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def test_source_reference_uses_approved_target_context_but_keeps_source_candidate_key(tmp_path):
    source_id, target_id = "source-id", "target-id"
    source_name, target_name = "Nordic Curl", "Weighted Vest Nordic Curl"
    source_context = {"exerciseDefinition": {"requiredPhases": ["lower", "return"]}, "exerciseType": "BODY_WEIGHT"}
    source_exercise_context = {
        "exerciseDefinition": {"requiredPhases": ["lower", "return"]},
        "exerciseType": "BODY_WEIGHT",
        "exerciseCategory": "ISOLATION",
        "bodyWeightPercentage": 100,
        "requiredAccessoryEquipmentIds": ["setup-id"],
        "requiredAccessories": [{"id": "setup-id", "type": "ACCESSORY", "name": "Nordic Curl Setup"}],
        "muscleGroups": ["BACK_HAMSTRING"],
    }
    target_context = {
        "exerciseDefinition": {"requiredPhases": ["lower", "return"], "variantQualifiers": ["weighted vest"]},
        "exerciseType": "BODY_WEIGHT",
        "primaryEquipment": {"id": "vest", "type": "WEIGHTVEST", "name": "Weight Vest"},
    }
    target_definition = {"id": target_id, "name": target_name, "motionContext": target_context}
    approval = {
        "authority": "explicit_user_approval", "exportedExerciseUnchanged": True,
        "exerciseName": target_name, "sourceReferenceExerciseName": source_name,
        "allowedDifference": "external_load_not_shown", "userAnswer": "approved",
    }
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps(approval), encoding="utf-8")
    source_hash, target_hash = _json_sha(source_context), _json_sha(target_context)
    source_definition_hash, target_definition_hash = _json_sha({"id": source_id}), _json_sha(target_definition)
    approval_hash = hashlib.sha256(approval_path.read_bytes()).hexdigest()
    mapping = {
        "bindings": [{
            "sourceReferenceDefinitionId": source_id, "targetDefinitionId": target_id,
            "motionReferenceOnly": True, "allowedDifference": "external_load_not_shown",
            "approvalPath": str(approval_path), "approvalSha256": approval_hash,
            "sourceMotionContextSha256": source_hash, "targetMotionContextSha256": target_hash,
            "sourceDefinitionSha256": source_definition_hash, "targetDefinitionSha256": target_definition_hash,
        }],
    }
    workspace = tmp_path / "workspace"
    item_workspace = workspace / "nordic-curl" / "bake"
    item_workspace.mkdir(parents=True)
    (workspace / "source_reference_mapping.json").write_text(json.dumps(mapping), encoding="utf-8")
    mapped_plan = {
        "exerciseDefinitions": [{"id": source_id, "name": source_name, "motionContext": source_context}],
        "motionSourceReferenceBindings": [{
            "sourceReferenceDefinitionId": source_id, "sourceReferenceExerciseName": source_name,
            "targetDefinitionId": target_id, "targetExerciseName": target_name,
            "sourceMotionContext": source_context, "sourceMotionContextSha256": source_hash,
            "targetMotionContext": target_context, "targetMotionContextSha256": target_hash,
            "sourceDefinitionSha256": source_definition_hash, "targetDefinitionSha256": target_definition_hash,
            "targetDefinition": target_definition, "motionReferenceOnly": True,
            "allowedDifference": "external_load_not_shown", "approvalSha256": approval_hash,
            "sourceExerciseMotionContext": source_exercise_context,
            "sourceExerciseMotionContextSha256": _json_sha(source_exercise_context),
            "targetExerciseMotionContext": target_context,
            "targetExerciseMotionContextSha256": target_hash,
            "targetExerciseSlug": "weighted-vest-nordic-curl",
        }],
    }
    mapped_plan_path = workspace / "effective_workout_plan.json"
    mapped_plan_path.write_text(json.dumps(mapped_plan), encoding="utf-8")
    exercise_plan_path = workspace / "nordic-curl" / "exercise_plan.json"
    exercise_plan_path.parent.mkdir(parents=True, exist_ok=True)
    exercise_plan_path.write_text(json.dumps({"sourcePlanPath": str(mapped_plan_path)}), encoding="utf-8")

    target = approved_source_reference_target_for_staged_plan(
        exercise_plan_path=exercise_plan_path, item_workspace=item_workspace,
        source_exercise_id=source_id, source_exercise_name=source_name,
        source_motion_context=source_exercise_context,
        expected_mapping_sha256=hashlib.sha256(
            (workspace / "source_reference_mapping.json").read_bytes()
        ).hexdigest(),
    )
    assert target is not None
    assert target["motionReferenceOnly"] is True
    assert target["allowedDifference"] == "external_load_not_shown"
    assert target["approvalAuthority"] == "explicit_user_approval"
    assert target["exportedExerciseUnchanged"] is True
    assert target["approvalUserAnswerPresent"] is True
    assert target["sourceMotionContext"] == source_context
    assert target["sourceMotionContextSha256"] == source_hash
    assert target["sourceExerciseMotionContext"] == source_exercise_context
    assert target["sourceExerciseMotionContextSha256"] == _json_sha(source_exercise_context)
    for mismatch in ("extra_equipment", "changed_action"):
        mutated = json.loads(json.dumps(source_exercise_context))
        if mismatch == "extra_equipment":
            mutated["primaryEquipment"] = {"id": "unapproved", "type": "WEIGHTVEST", "name": "Weight Vest"}
        else:
            mutated["exerciseDefinition"]["definingAction"] = "Changed source action"
        with pytest.raises(ApprovedSourceReferenceContextError, match="does not match staged item"):
            approved_source_reference_target_for_staged_plan(
                exercise_plan_path=exercise_plan_path, item_workspace=item_workspace,
                source_exercise_id=source_id, source_exercise_name=source_name,
                source_motion_context=mutated,
                expected_mapping_sha256=hashlib.sha256(
                    (workspace / "source_reference_mapping.json").read_bytes()
                ).hexdigest(),
            )
    with pytest.raises(ValueError, match="does not match invocation digest"):
        approved_source_reference_target_for_staged_plan(
            exercise_plan_path=exercise_plan_path, item_workspace=item_workspace,
            source_exercise_id=source_id, source_exercise_name=source_name,
            source_motion_context=source_exercise_context, expected_mapping_sha256="0" * 64,
        )
    request = BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json", workspace=item_workspace, body_model_root=None,
        authoritative_exercise_motion_context=source_exercise_context,
    )
    item = StagedWaveItem(source_id, source_name, request, source_reference_target=target)
    candidate = RankedCandidate(0, 0, source_id, source_name, "nordic-curl", {"videoId": "YCOZLcqu7qU"})
    review_request = _source_review_request(item)
    contract_exercise = _source_review_contract_exercise(
        candidate, review_request,
        motion_context=review_request.authoritative_exercise_motion_context,
    )

    assert _candidate_key(candidate) == "source-id:nordic-curl-001-ycozlcqu7qu"
    assert item.exercise_id == source_id
    assert review_request.source_reference_target_exercise_id == target_id
    assert review_request.source_reference_target_exercise_name == target_name
    assert review_request.authoritative_exercise_motion_context == target_context
    assert review_request.source_reference_mapping["sourceMotionContext"] == source_context
    assert review_request.source_reference_mapping["sourceMotionContextSha256"] == source_hash
    assert (contract_exercise.exercise_id, contract_exercise.name, contract_exercise.motion_context) == (
        target_id, target_name, target_context,
    )
    assert (candidate.exercise_id, candidate.exercise_name) == (source_id, source_name)
    assert request.authoritative_exercise_motion_context == source_exercise_context


def test_unmapped_staged_exercise_keeps_its_normal_context(tmp_path):
    request = BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json", workspace=tmp_path, body_model_root=None,
        authoritative_exercise_motion_context={"exerciseDefinition": {"requiredPhases": ["move"]}},
    )
    item = StagedWaveItem("plain-id", "Plain Exercise", request)

    assert _source_review_request(item) is request
    assert item.source_reference_target is None
