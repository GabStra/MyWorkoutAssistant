import hashlib
import json
import math

import pytest

from exercise_motion_pkg import bake_and_rank, controlled_motion


def _bound_payload(*, source_phase_passed=True, mapping_bound=True):
    contract = {"completionMode": "return_to_start", "exerciseName": "Test Movement"}
    identity = {
        "selectedSegmentSha256": "1" * 64,
        "parentSourceSha256": "2" * 64,
        "selectedFrameClockReceiptSha256": "3" * 64,
        "sourcePosePayloadSha256": "4" * 64,
    }
    mapping = {
        "schemaVersion": 1,
        "verified": True,
        "mappingKind": "selected_segment_to_parent_source",
        "selectedFrameCount": 7,
        "selectedFrameLineage": [
            {"selectedFrameIndex": i, "parentSourceFrameIndex": i + 20,
             "selectedFrameTimeSec": i / 30, "parentSourceTimeSec": 2 + i / 30}
            for i in range(7)
        ],
        **identity,
    }
    if not mapping_bound:
        mapping["selectedSegmentSha256"] = "5" * 64
    authority = {
        "authoritative": True,
        "reason": "exact_pre_reconstruction_return_cycle_validated",
        "exactValidationSource": "standalone_file",
        "selectedSegmentPath": "verified-selected-segment.mp4",
        "selectedSegmentSha256": identity["selectedSegmentSha256"],
        "movementInstance": {"available": True, "trimmed": False},
    }
    source_pose = {"sourceVideoSha256": identity["selectedSegmentSha256"], "frames": [{}] * 7}
    frames = [
        {"timeSec": i / 30, "sourceTimeSec": 2 + i / 30,
         "joints": {"pelvis": [0.0, 0.0, 0.0]}}
        for i in range(7)
    ]
    payload = {
        "frames": frames,
        "frameCount": len(frames),
        "fps": 30.0,
        "jointNames": ["pelvis"],
        "loop": {"enabled": True},
        "exerciseMotionContract": contract,
        "sourcePoseReference": source_pose,
        "sourcePoseCameraReference": {
            "sourceTimelineMapping": mapping,
            "camera": {"available": True, "sourceTimelineMappingIdentity": identity.copy()},
        },
        "preReconstructionSourceIntervalAuthority": authority,
    }
    return payload, source_pose, contract, source_phase_passed


def _source_only_preflight(_payload, _source_pose, _contract):
    return {
        "passed": True,
        "required": True,
        "sourcePhase": {"required": True, "passed": True, "hasSingleMajorCycle": True,
                        "majorPhaseSequence": ["low", "high", "low"]},
        "sourcePhaseFootOrientationEvidence": {
            "right": {"sampleCount": 52, "observationFrameIndices": list(range(52)),
                      "observationFrameIndexDomain": "selected_segment"},
        },
        # A reconstructed-output failure must not veto this source-owned proposal.
        "outputPhase": {"required": True, "passed": False},
    }


def _install_no_fallback_proposals(monkeypatch):
    monkeypatch.setattr(bake_and_rank, "observable_motion_spec_for_contract", lambda _contract: None)
    from exercise_motion_pkg import loop_cycles
    monkeypatch.setattr(loop_cycles, "rank_loop_cycles", lambda *_args, **_kwargs: [])


def test_exact_source_cycle_can_reach_fit_with_bad_reconstructed_boundary(monkeypatch):
    payload, source_pose, contract, _ = _bound_payload()
    monkeypatch.setattr(bake_and_rank, "selected_interval_source_phase_preflight", _source_only_preflight)

    proposals, diagnostics = bake_and_rank.source_validated_cycle_proposals(
        payload, source_pose, contract)

    assert len(proposals) == 1
    selection = proposals[0]
    assert (selection["startFrame"], selection["stopFrameExclusive"]) == (0, 7)
    assert selection["sourceOwnedCycleAuthority"]["kind"] == "verified_pre_reconstruction_source_cycle"
    assert diagnostics[0]["passed"] is True
    assert diagnostics[0]["sourcePhase"]["majorPhaseSequence"] == ["low", "high", "low"]
    assert diagnostics[0]["outputPhaseDeferredUntilAfterFit"] is True


@pytest.mark.parametrize("failure", ["unbound_mapping", "source_phase_incomplete", "contract_mismatch"])
def test_source_owned_cycle_fails_closed_when_authority_or_source_phase_is_invalid(monkeypatch, failure):
    payload, source_pose, contract, _ = _bound_payload(mapping_bound=failure != "unbound_mapping")
    _install_no_fallback_proposals(monkeypatch)
    if failure == "source_phase_incomplete":
        def incomplete(*_args, **_kwargs):
            result = _source_only_preflight(None, None, None)
            result["passed"] = False
            result["sourcePhase"]["passed"] = False
            return result
        monkeypatch.setattr(bake_and_rank, "selected_interval_source_phase_preflight", incomplete)
    else:
        monkeypatch.setattr(bake_and_rank, "selected_interval_source_phase_preflight", _source_only_preflight)
    if failure == "contract_mismatch":
        payload["exerciseMotionContract"] = {**contract, "exerciseName": "Different Movement"}

    proposals, diagnostics = bake_and_rank.source_validated_cycle_proposals(
        payload, source_pose, contract)

    assert not any("sourceOwnedCycleAuthority" in item for item in proposals)
    assert proposals == []


def test_bad_final_fit_gate_still_rejects_source_owned_cycle(monkeypatch):
    payload, source_pose, contract, _ = _bound_payload()
    monkeypatch.setattr(bake_and_rank, "selected_interval_source_phase_preflight", _source_only_preflight)
    proposals, diagnostics = bake_and_rank.source_validated_cycle_proposals(payload, source_pose, contract)
    payload["observedCycleProposals"] = proposals
    payload["sourceCyclePreflight"] = diagnostics
    calls = []

    from exercise_motion_pkg import loop_cycles
    monkeypatch.setattr(loop_cycles, "cycle_boundary_motion_metrics", lambda *_args, **_kwargs: {
        "passed": False, "rejectionReasons": ["source_support_wrap_unrepairable"],
    })
    monkeypatch.setattr(controlled_motion, "_verified_support_wrap_deferral", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(controlled_motion, "SOURCE_CONFIRMED_CYCLE_MINIMUM_BUDGET_SECONDS", 0.0)
    monkeypatch.setattr(controlled_motion, "retained_interval_minimum_budget_seconds", lambda: 999.0)

    def reject_after_fit(candidate, **_kwargs):
        calls.append(candidate)
        return candidate, {
            "applied": False,
            "reason": "fit_validation_failed",
            "checks": {"loopSeam": False, "sourceProjection": True},
        }

    monkeypatch.setattr(controlled_motion, "_fit_controlled_motion", reject_after_fit)
    result, report = controlled_motion._fit_observed_cycles(
        payload, max_evaluations=1200, timeout_seconds=120.0)

    assert len(calls) == 1
    assert report.get("applied") is False
    assert report.get("reason") != "validated_controlled_motion"
    assert result.get("controlledMotionFit", {}).get("applied") is not True


def test_source_owned_cycle_rejects_authority_for_different_selected_bytes(monkeypatch):
    payload, source_pose, contract, _ = _bound_payload()
    monkeypatch.setattr(bake_and_rank, "selected_interval_source_phase_preflight", _source_only_preflight)
    proposals, diagnostics = bake_and_rank.source_validated_cycle_proposals(
        payload, source_pose, contract)
    assert len(proposals) == 1

    # The authority path alone cannot bind a different selected source. The
    # consumer must recheck its byte identity against both mapping and proof.
    payload["observedCycleProposals"] = proposals
    payload["sourceCyclePreflight"] = diagnostics
    selection = proposals[0]
    assert controlled_motion._verified_source_owned_cycle_choice(payload, selection)
    payload["preReconstructionSourceIntervalAuthority"]["selectedSegmentSha256"] = "f" * 64
    assert not controlled_motion._verified_source_owned_cycle_choice(payload, selection)
    proposals, _ = bake_and_rank.source_validated_cycle_proposals(
        payload, source_pose, contract)
    assert proposals == []


def test_validated_native_fullsole_owner_requires_articulation_guard_without_joint_pins():
    names = ["left_ankle", "left_foot"]
    track = {
        "version": 2,
        "left": {
            "active": [True, True],
            "directions": [[0.0, 0.0, 1.0]] * 2,
            "sideAxes": [[1.0, 0.0, 0.0]] * 2,
            "anchorIds": ["left:sole:0"] * 2,
            "episodes": [{
                "startFrame": 0, "endFrame": 1, "anchorId": "left:sole:0",
                "regionRole": "full_sole", "mode": "stationary",
                "primitiveId": "wearShoe:left_ankle->left_foot",
                "triangleIndex": 10, "barycentric": [0.2, 0.4, 0.4],
                "materialOffsetLocalMeters": [0.0, 0.0, 0.0],
                "referenceLengthMeters": 0.2, "targetWorld": [0.0, 0.0, 0.0],
                "surfaceNormal": [0.0, 1.0, 0.0], "planeOffsetMeters": 0.0,
            }],
        },
    }
    support = {"_nativeFootMaterialTracks": track}

    # Native ownership has suppressed the source joint pins, but remains a
    # validated stationary material support and must keep the shared guard.
    assert controlled_motion.support_articulation_guard_required(
        False, support, names=names, frame_count=2)
    assert not controlled_motion.support_articulation_guard_required(
        False, {"_nativeFootMaterialTracks": {"version": 2, "left": {"active": [True]}}},
        names=names, frame_count=2)


def test_source_owned_preflight_retains_bound_foot_ray_frame_identity():
    digest = "a" * 64
    pose = {
        "sourceVideoSha256": digest,
        "sourceTimeOriginSec": 0.0,
        "frames": [{"sourceTimeSec": index / 30.0, "joints": {}}
                   for index in range(52)],
    }
    observations = []
    for index in range(52):
        angle = 0.2 * math.sin(2 * math.pi * index / 51)
        observations.append({
            "sourceFrameIndex": index,
            "sourceParentFrameIndex": index + 52,
            "sourceTimeSec": index / 30.0,
            "ankleToToeImageRay": [math.cos(angle), math.sin(angle)],
            "confidence": 0.95,
        })
    evidence = {
        "sourceVideoSha256": digest,
        "footPatchEvidence": {
            "available": True,
            "sourceVideoSha256": digest,
            "sourceTimeBasis": "absolute_source_video",
            "sourceTimeOriginSec": 0.0,
            "feet": {"right": {"rayObservations": observations}},
        },
    }

    tracks = bake_and_rank.source_foot_orientation_phase_tracks(pose, evidence)

    assert tracks["right"]["sampleCount"] == 52
    assert tracks["right"]["observationFrameIndexDomain"] == "selected_segment"
    assert tracks["right"]["observationFrameIndices"] == list(range(52))
    assert tracks["right"]["observationParentFrameIndices"] == list(range(52, 104))
