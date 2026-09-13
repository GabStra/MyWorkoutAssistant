import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from exercise_motion_pkg.acceptance import (decide_acceptance, selected_artifact_identity,
                                           invalidate_retained_acceptance, promote_verified_artifact)
from exercise_motion_pkg.contract_authority import contract_field_authority
from exercise_motion_pkg.review_consensus import corroborate_rejection
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.structural_refinement import enforce_final_structural_invariant
from exercise_motion_pkg import bake_and_rank as bake


def test_identity_changes_for_source_skeleton_contract_and_policy(tmp_path):
    source = tmp_path / "x_selected_input.mp4"
    skeleton = tmp_path / "x_wear_skeleton.json"
    source.write_bytes(b"source")
    skeleton.write_text("{}")
    manifest = {"selected": {"loopIndex": 0}}
    def identity(**kwargs):
        return selected_artifact_identity(tmp_path, manifest, policies=kwargs.pop("policies", {"visual": 1}), **kwargs)
    original = identity()
    assert original
    source.write_bytes(b"different source")
    assert identity() != original
    source.write_bytes(b"source")
    skeleton.write_text('{"changed":true}')
    assert identity() != original
    skeleton.write_text("{}")
    assert identity(contract={"carryPosition": "overhead"}) != original
    assert identity(policies={"visual": 2}) != original
    assert identity() == original
    (tmp_path / "other_selected_input.mp4").write_bytes(b"ambiguous")
    assert identity() is None


def test_missing_evidence_cannot_be_approved_by_model():
    decision = decide_acceptance({}, {"passed": True}, deterministic_rejections=[], review_rejections=[])
    assert decision.status == "needs_manual_review"
    assert not decision.can_regenerate_motion


def test_numeric_failure_survives_review_disagreement():
    decision = decide_acceptance({"passed": False}, {"failureOwner": "review"},
                                 deterministic_rejections=["bone_length_variation"], review_rejections=[])
    assert decision.status == "invalid"
    assert decision.can_regenerate_motion


def test_unresolved_review_cannot_queue_source_recut():
    ranking = SimpleNamespace(payload={"acceptanceDecision": {"status": "needs_manual_review"}})
    assert bake.should_queue_parent_source_window_fallback(
        SimpleNamespace(), {}, (None, ranking), request=None,
    ) == (False, None)


def test_required_validator_unavailable_is_not_motion_failure():
    decision = decide_acceptance({"fidelity": {"required": True, "available": False}}, {"passed": True},
                                 deterministic_rejections=[], review_rejections=[])
    assert decision.status == "needs_manual_review"
    assert decision.failure_owner == "evidence"


def test_single_implement_does_not_invent_one_arm_or_carry_position():
    fields = contract_field_authority("Single Dumbbell Forward Lunge", {"carryPosition": "hip"})
    assert fields["implementCount"]["required"]
    assert "actingArmCount" not in fields
    assert not fields["carryPosition"]["required"]
    assert contract_field_authority("Single-Arm Dumbbell Bulgarian Split Squat", {})["actingArmCount"]["value"] == 1


@pytest.mark.parametrize("second", [
    {"passed": True},
    {"passed": False, "reject": ["different_problem"]},
    {"passed": False, "reject": ["wrong_variant"], "failureOwner": "review"},
])
def test_review_disagreement_never_approves_or_regenerates(second):
    calls = []
    def review():
        calls.append(1)
        return second
    result = corroborate_rejection({"passed": False, "reject": ["wrong_variant"]}, review)
    assert len(calls) == 1
    assert result["reviewStatus"] == "needs_manual_review"
    assert not result["passed"] and not result["needsRetry"]


def test_approval_has_no_extra_model_call():
    def forbidden():
        raise AssertionError("unnecessary review")
    assert corroborate_rejection({"passed": True}, forbidden)["passed"]


def test_corroboration_requires_body_evidence_and_retains_only_common_findings():
    evidence = {"tag": "wrong_variant", "basis": "body_motion", "observation": "Both arms move alternately.",
                "bodyRelation": {"subject": "left_wrist", "reference": "right_wrist", "relation": "moving_alternately"}}
    first = {"passed": False, "reject": ["wrong_variant", "unsupported"],
             "modelPayload": {"rejectionEvidence": [evidence]}}
    second = {"passed": False, "reject": ["wrong_variant"], "modelPayload": {"rejectionEvidence": [evidence]}}
    claim = {**evidence, "status": "observed", "defectType": "wrong_action",
             "bodyRegion": "both_arms", "frameIndices": [1, 2]}
    first["localizedClaims"] = [claim]
    second["localizedClaims"] = [claim]
    result = corroborate_rejection(first, lambda: second)
    assert result["boundedReview"]["corroborated"]
    assert result["hardRejectionReasons"] == ["wrong_variant"]
    assert result["boundedReview"]["first"]["reject"] == ["wrong_variant", "unsupported"]


def test_promotion_rejects_stale_evidence_and_preserves_previous_selection(tmp_path):
    source, destination = tmp_path / "candidate", tmp_path / "selected"
    source.mkdir()
    destination.mkdir()
    (destination / "previous.txt").write_text("keep")
    (source / "x_selected_input.mp4").write_bytes(b"source")
    skeleton = source / "x_wear_skeleton.json"
    skeleton.write_text("{}")
    manifest = {"selected": {"ranking": {"payload": {}}}}
    (source / "selection_manifest.json").write_text(json.dumps(manifest))
    identity = selected_artifact_identity(source, manifest, policies={"visual": 1})
    (source / "revalidation.json").write_text(json.dumps({"status": "valid", "artifactIdentity": identity}))
    skeleton.write_text('{"changed":true}')
    with pytest.raises(ValueError, match="current valid verdict"):
        promote_verified_artifact(source, destination, policies={"visual": 1})
    assert (destination / "previous.txt").read_text() == "keep"
    skeleton.write_text("{}")
    backup = promote_verified_artifact(source, destination, policies={"visual": 1})
    assert (backup / "previous.txt").read_text() == "keep"
    invalidate_retained_acceptance(destination, "edited")
    saved = json.loads((destination / "selection_manifest.json").read_text())
    assert saved["selected"]["ranking"]["payload"]["acceptanceDecision"]["status"] == "needs_manual_review"
    with pytest.raises(ValueError):
        promote_verified_artifact(destination, tmp_path / "another", policies={"visual": 1})


@pytest.mark.parametrize("payload", [{}, {"approved": "true"},
    {"approved": True, "confidence": 95, "retry": False, "reject": []},
    {"approved": True, "confidence": .95, "retry": False, "reject": "none"}])
def test_invalid_schema_is_review_failure(payload):
    result = bake.parse_final_output_validation_response(json.dumps(payload), min_score=.9)
    assert result["failureOwner"] == "review"
    assert not result["needsRetry"]


def test_final_invariant_rejects_late_stretch_but_accepts_rigid_translation():
    original = MotionClip(30, ["left_shoulder", "left_elbow"], [
        MotionFrame(i / 30, {"left_shoulder": (0., 0., 0.), "left_elbow": (1., 0., 0.)}) for i in range(3)])
    frames = list(original.frames)
    frames[1] = replace(frames[1], joints={"left_shoulder": (0., 0., 0.), "left_elbow": (2., 0., 0.)})
    result, report = enforce_final_structural_invariant(original, replace(original, frames=frames))
    assert result is original and report["rolledBack"]
    shifted = replace(original, frames=[replace(frame, joints={key: (p[0] + i, p[1], p[2])
        for key, p in frame.joints.items()}) for i, frame in enumerate(original.frames)])
    result, report = enforce_final_structural_invariant(original, shifted)
    assert result is shifted and report["accepted"]
