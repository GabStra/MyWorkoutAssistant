import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from exercise_motion_pkg.acceptance import (decide_acceptance, selected_artifact_identity,
                                           source_contract_clearance_sha256,
                                           invalidate_retained_acceptance, promote_verified_artifact,
                                           selected_bake_code_problem)
from exercise_motion_pkg.contract_authority import contract_field_authority
from exercise_motion_pkg.review_consensus import corroborate_rejection
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.structural_refinement import enforce_final_structural_invariant
from exercise_motion_pkg import bake_and_rank as bake
from scripts.promote_validated_motion_artifact import current_promotion_policies


def _attach_current_source_clearance(tmp_path, source, manifest):
    source_manifest = tmp_path / "source_segment_selection.json"
    source_manifest.write_text('{"sourcePrepReason":"pre_reconstruction_source_window_choice"}')
    reviewed_image = tmp_path / "reviewed_source_frame.jpg"
    reviewed_image.write_bytes(b"reviewed image")
    profile = {"sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION}
    profile_sha256 = hashlib.sha256(json.dumps(
        profile, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    frame_evidence = {
        "candidateId": "A",
        "startSeconds": 0.0,
        "endSeconds": 8.0,
        "framePaths": [str(reviewed_image.resolve())],
        "endpointFramePaths": [],
        "images": [{
            "path": str(reviewed_image.resolve()),
            "sha256": hashlib.sha256(reviewed_image.read_bytes()).hexdigest(),
        }],
        "extractionProfile": profile,
        "extractionProfileSha256": profile_sha256,
    }
    clearance = manifest["selected"]["sourceSelectionClearance"]
    clearance.update({
        "sourceManifestPath": str(source_manifest),
        "sourceManifestSha256": hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
        "selectedSegmentPath": str(source),
        "selectedSegmentSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sourceCutReviewVideoPath": str(source),
        "sourceCutReviewVideoSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sourceCutOriginalVideoPath": str(source),
        "sourceCutOriginalVideoSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sourceCutReviewFrameEvidence": frame_evidence,
        "sourceCutReviewFrameEvidenceSha256": hashlib.sha256(json.dumps(
            frame_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest(),
        "reviewedExerciseName": "Example",
        "exerciseMotionContractSha256": source_contract_clearance_sha256(None),
    })
    return manifest


def test_identity_changes_for_source_skeleton_contract_and_policy(tmp_path):
    source = tmp_path / "x_selected_input.mp4"
    skeleton = tmp_path / "x_wear_skeleton.json"
    source.write_bytes(b"source")
    skeleton.write_text("{}")
    manifest = {
        "preReconstructionSourceValidationEnabled": True,
        "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
        "selected": {
            "loopIndex": 0,
            "exerciseName": "Example",
            "sourceSelectionClearance": {
                "status": "cleared",
                "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
                "sourceSelectionClearancePolicyVersion": bake.SOURCE_SELECTION_CLEARANCE_POLICY_VERSION,
                "authorizedCandidateId": "A",
            },
        },
    }
    _attach_current_source_clearance(tmp_path, source, manifest)
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
    manifest["selected"]["artifactClass"] = "cyclic_rebake"
    manifest["selected"]["artifactState"] = {
        "artifactClass": "cyclic_rebake",
        "terminal": True,
    }
    assert identity() != original
    manifest["selected"].pop("artifactClass")
    manifest["selected"].pop("artifactState")
    assert identity() == original
    (tmp_path / "other_selected_input.mp4").write_bytes(b"ambiguous")
    assert identity() is None


@pytest.mark.parametrize(
    "fit_report,expected_problem",
    [
        (
            {"applied": True, "strategy": "fixed_rig_controlled_motion_v125_selector_consistent_temporal_feasibility"},
            "controlled_motion_fit_strategy_mismatch",
        ),
        (
            {"applied": True, "strategy": "fixed_rig_controlled_motion_v126_unknown_heel_direction_continuity"},
            "controlled_motion_fit_receipt_invalid",
        ),
    ],
)
def test_selected_artifact_identity_rejects_stale_or_invalid_applied_fit(
    tmp_path, fit_report, expected_problem,
):
    from exercise_motion_pkg.acceptance import selected_fit_receipt_problem
    from exercise_motion_pkg.controlled_motion import CONTROLLED_MOTION_STRATEGY

    source = tmp_path / "x_selected_input.mp4"
    skeleton = tmp_path / "x_wear_skeleton.json"
    source.write_bytes(b"source")
    skeleton.write_text(json.dumps({"controlledMotionFit": fit_report}))
    manifest = {
        "preReconstructionSourceValidationEnabled": True,
        "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
        "selected": {
            "loopIndex": 0,
            "exerciseName": "Example",
            "ranking": {"payload": {}},
            "sourceSelectionClearance": {
                "status": "cleared",
                "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
                "sourceSelectionClearancePolicyVersion": bake.SOURCE_SELECTION_CLEARANCE_POLICY_VERSION,
                "authorizedCandidateId": "A",
            },
        },
    }
    _attach_current_source_clearance(tmp_path, source, manifest)
    policies = {
        "selection": bake.SELECTION_VALIDATION_POLICY_VERSION,
        "visual": bake.FINAL_OUTPUT_VALIDATION_POLICY_VERSION,
        "source": bake.SOURCE_SELECTION_POLICY_VERSION,
        "controlledMotionFit": CONTROLLED_MOTION_STRATEGY,
    }

    assert selected_fit_receipt_problem(
        json.loads(skeleton.read_text()), CONTROLLED_MOTION_STRATEGY,
    ) == expected_problem
    assert selected_artifact_identity(tmp_path, manifest, policies=policies) is None


def test_selected_artifact_identity_allows_no_applied_fit_with_current_fit_policy(tmp_path):
    source = tmp_path / "x_selected_input.mp4"
    skeleton = tmp_path / "x_wear_skeleton.json"
    source.write_bytes(b"source")
    skeleton.write_text("{}")
    manifest = {
        "preReconstructionSourceValidationEnabled": True,
        "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
        "selected": {
            "loopIndex": 0,
            "exerciseName": "Example",
            "ranking": {"payload": {}},
            "sourceSelectionClearance": {
                "status": "cleared",
                "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
                "sourceSelectionClearancePolicyVersion": bake.SOURCE_SELECTION_CLEARANCE_POLICY_VERSION,
                "authorizedCandidateId": "A",
            },
        },
    }
    _attach_current_source_clearance(tmp_path, source, manifest)
    from exercise_motion_pkg.controlled_motion import CONTROLLED_MOTION_STRATEGY

    identity = selected_artifact_identity(
        tmp_path,
        manifest,
        policies={"controlledMotionFit": CONTROLLED_MOTION_STRATEGY},
    )

    assert identity is not None
    assert identity["policies"]["controlledMotionFit"] == CONTROLLED_MOTION_STRATEGY


def test_selected_artifact_identity_rejects_old_bake_processing_signature(tmp_path):
    source = tmp_path / "x_selected_input.mp4"
    skeleton = tmp_path / "x_wear_skeleton.json"
    source.write_bytes(b"source")
    skeleton.write_text(json.dumps({"selectedSectionBakePathCodeDigest": "old"}))
    manifest = {
        "preReconstructionSourceValidationEnabled": True,
        "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
        "selected": {
            "loopIndex": 0,
            "exerciseName": "Example",
            "ranking": {"payload": {}},
            "sourceSelectionClearance": {
                "status": "cleared",
                "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
                "sourceSelectionClearancePolicyVersion": bake.SOURCE_SELECTION_CLEARANCE_POLICY_VERSION,
                "authorizedCandidateId": "A",
            },
        },
    }
    _attach_current_source_clearance(tmp_path, source, manifest)

    assert selected_bake_code_problem({}, "current") == "selected_bake_processing_digest_mismatch"
    assert selected_bake_code_problem({"selectedSectionBakePathCodeDigest": "old"}, "current") == (
        "selected_bake_processing_digest_mismatch"
    )
    assert selected_bake_code_problem(
        {"selectedSectionBakePathCodeDigest": "current"}, "current",
    ) is None
    assert selected_artifact_identity(
        tmp_path, manifest, policies={"bakeCode": "current"},
    ) is None

    skeleton.write_text(json.dumps({"selectedSectionBakePathCodeDigest": "current"}))
    assert selected_artifact_identity(
        tmp_path, manifest, policies={"bakeCode": "current"},
    ) is not None


def test_selected_bake_processing_signature_tracks_pipeline_and_chain_depth_code(tmp_path, monkeypatch):
    from exercise_motion_pkg import fit_runtime

    bake_source = tmp_path / "bake_and_rank.py"
    bake_source.write_text("def bake_preview_loops_with_playwright(): pass\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.py"
    chain_depth = tmp_path / "chain_depth_correction.py"
    pipeline.write_text("pipeline version one\n", encoding="utf-8")
    chain_depth.write_text("chain version one\n", encoding="utf-8")
    monkeypatch.setattr(fit_runtime, "fit_cache_source_paths", lambda: ())
    monkeypatch.setattr(bake, "__file__", str(bake_source))

    original = bake._selected_section_bake_code_digest()["sha256"]
    pipeline.write_text("pipeline version two\n", encoding="utf-8")
    pipeline_changed = bake._selected_section_bake_code_digest()["sha256"]
    chain_depth.write_text("chain version two\n", encoding="utf-8")
    both_changed = bake._selected_section_bake_code_digest()["sha256"]

    assert pipeline_changed != original
    assert both_changed != pipeline_changed


def test_normal_selection_identity_requires_current_source_clearance(tmp_path):
    (tmp_path / "x_selected_input.mp4").write_bytes(b"source")
    (tmp_path / "x_wear_skeleton.json").write_text("{}")
    manifest = {
        "preReconstructionSourceValidationEnabled": True,
        "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
        "selected": {
            "loopIndex": 0,
            "exerciseName": "Example",
            "sourceSelectionClearance": {
                "status": "cleared",
                "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
                "sourceSelectionClearancePolicyVersion": bake.SOURCE_SELECTION_CLEARANCE_POLICY_VERSION,
                "authorizedCandidateId": "A",
            },
        },
    }
    _attach_current_source_clearance(tmp_path, tmp_path / "x_selected_input.mp4", manifest)
    policies = {"visual": 1, "source": bake.SOURCE_SELECTION_POLICY_VERSION}

    assert selected_artifact_identity(tmp_path, manifest, policies=policies)

    source_manifest_path = manifest["selected"]["sourceSelectionClearance"]["sourceManifestPath"]
    source_manifest_bytes = open(source_manifest_path, "rb").read()
    with open(source_manifest_path, "wb") as source_manifest_file:
        source_manifest_file.write(b'{"changed":true}')
    assert selected_artifact_identity(tmp_path, manifest, policies=policies) is None
    with open(source_manifest_path, "wb") as source_manifest_file:
        source_manifest_file.write(source_manifest_bytes)

    manifest["selected"].pop("sourceSelectionClearance")
    assert selected_artifact_identity(tmp_path, manifest, policies=policies) is None

    manifest["preReconstructionSourceValidationEnabled"] = False
    assert selected_artifact_identity(tmp_path, manifest, policies=policies) is None


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


def test_single_dumbbell_requires_one_arm_without_inventing_carry_position():
    fields = contract_field_authority("Single Dumbbell Forward Lunge", {"carryPosition": "hip"})
    assert fields["implementCount"]["required"]
    assert fields["actingArmCount"]["required"]
    assert fields["actingArmCount"]["value"] == 1
    assert "actingArmCount" not in contract_field_authority("Single Kettlebell Forward Lunge", {})
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
    manifest = {
        "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
        "selected": {
            "exerciseName": "Example",
            "ranking": {"payload": {}},
            "sourceSelectionClearance": {
                "status": "cleared",
                "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
                "sourceSelectionClearancePolicyVersion": bake.SOURCE_SELECTION_CLEARANCE_POLICY_VERSION,
                "authorizedCandidateId": "A",
            },
        },
    }
    _attach_current_source_clearance(tmp_path, source / "x_selected_input.mp4", manifest)
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


def test_promotion_policy_binds_current_source_clearance_version():
    policies = current_promotion_policies()
    assert policies["source"] == bake.SOURCE_SELECTION_POLICY_VERSION
    from exercise_motion_pkg.controlled_motion import CONTROLLED_MOTION_STRATEGY

    assert policies["controlledMotionFit"] == CONTROLLED_MOTION_STRATEGY
    assert policies["bakeCode"] == bake._selected_section_bake_code_digest()["sha256"]
    assert bake.SELECTION_VALIDATION_POLICY_VERSION == 139


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


def test_incomplete_source_cut_recovery_runs_even_after_deterministic_confirmation():
    """Regression: confirmed-but-partial cuts used to skip parent recovery and hit fit empty."""
    assert bake.incomplete_source_cut_requires_same_source_recovery("partial")
    assert bake.incomplete_source_cut_requires_same_source_recovery("invalid")
    assert not bake.incomplete_source_cut_requires_same_source_recovery("complete")
    assert not bake.incomplete_source_cut_requires_same_source_recovery("uncertain")
