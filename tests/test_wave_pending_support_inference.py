from __future__ import annotations

import copy
import hashlib
import json

import pytest

from exercise_motion_pkg import body_support_observation, foot_contact_observation
from exercise_motion_pkg import source_frame_clock, source_support_tracking
from exercise_motion_pkg.bake_and_rank import source_pose_support_contract_fingerprint
from exercise_motion_pkg.wave_pipeline import (
    _reconstruction_only_pending_support_is_valid,
    artifact_disposition,
    final_processing_diagnostics,
    wave_manifest_is_exportable,
)


def _stage(tmp_path, monkeypatch):
    video = tmp_path / "selected.mp4"
    pose_path = tmp_path / "exact_source_pose_reference.json"
    clock_path = tmp_path / "selected.source_frame_clock.json"
    video.write_bytes(b"selected-source-bytes")
    pose_payload = {"frames": [{"sourceTimeSec": 0.0}, {"sourceTimeSec": 1 / 30}]}
    pose_reference = {"sourceVideoSha256": hashlib.sha256(video.read_bytes()).hexdigest(), "pose": pose_payload}
    pose_path.write_text(json.dumps(pose_reference), encoding="utf-8")
    clock_path.write_bytes(b"verified-clock-receipt")
    video_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    pose_reference_sha = hashlib.sha256(pose_path.read_bytes()).hexdigest()
    pose_payload_sha = "2" * 64
    clock_sha = hashlib.sha256(clock_path.read_bytes()).hexdigest()
    clock_frames = [
        {"sourceTimeSec": index / 30, "sourceFrameIndex": 700 + index}
        for index in range(4)
    ]

    monkeypatch.setattr(source_frame_clock, "source_frame_clock_path_for_video", lambda _path: clock_path)
    monkeypatch.setattr(
        source_frame_clock,
        "load_verified_source_frame_clock",
        lambda *_args, **_kwargs: {"outputFps": 30.0, "outputFrameCount": 4, "frames": clock_frames},
    )
    monkeypatch.setattr(
        "exercise_motion_pkg.pose_fidelity._canonical_source_pose_sha256",
        lambda _pose: pose_payload_sha,
    )
    answer = {
        "leftFoot": "stationary_full_sole", "leftFootSurface": "ground",
        "rightFoot": "stationary_full_sole", "rightFootSurface": "ground",
    }
    monkeypatch.setattr(body_support_observation, "validated_body_support_answer", lambda _observation: answer)
    monkeypatch.setattr(body_support_observation, "validated_body_support_contact_timeline", lambda *_a, **_kw: [])

    contract = {"bodySupportRequirements": {"required": [
        {"region": "upper_back", "side": "center", "surface": "bench", "contactMode": "stationary"},
        {"region": "foot", "side": "both", "surface": "ground", "contactMode": "stationary"},
    ]}}
    upper_back = {
        "requirement": {"region": "upper_back", "side": "center", "surface": "bench", "contactMode": "stationary"},
        "sourceVideoSha256": video_sha, "sourcePoseReferenceSha256": pose_reference_sha,
        "reviewContactIds": ["upper-back-contact"], "observedStates": ["unknown"],
        "sourceApproval": False, "geometryApproval": False,
    }
    foot_rows = []
    for side, states in (("left", ["unknown"] * 4), ("right", ["unknown", "toe_only", "unknown", "toe_only"])):
        foot_rows.append({
            "kind": "required_foot_ground_material_inference",
            "requirement": {"region": "foot", "side": side, "surface": "ground", "contactMode": "stationary"},
            "sourceVideoSha256": video_sha, "sourcePoseReferenceSha256": pose_reference_sha,
            "sourcePosePayloadSha256": pose_payload_sha, "sourceFrameClockReceiptSha256": clock_sha,
            "footPatchEvidencePolicyVersion": foot_contact_observation.POLICY_VERSION,
            "materialStationarityPolicyVersion": source_support_tracking.FOOT_MATERIAL_POLICY_VERSION,
            "sourceFrameCount": 4, "sourcePoseFrameCount": 2,
            "unknownFrameIndexes": [i for i, state in enumerate(states) if state == "unknown"],
            "unknownSelectedSourceFrameIndexes": [700 + i for i, state in enumerate(states) if state == "unknown"],
            "observedPatchStates": sorted(set(states)),
            "coarseObservedState": answer[f"{side}Foot"],
            "coarseObservedSurface": answer[f"{side}FootSurface"],
            "accountsForReadinessReasons": ["source_support_contact_evidence_incomplete"],
            "sourceApproval": False, "geometryApproval": False,
        })
    evidence = {
        "sourceVideoSha256": video_sha,
        "bodySupportObservation": {"sourceVideoSha256": video_sha},
        "footPatchEvidence": {
            "available": True,
            "policyVersion": foot_contact_observation.POLICY_VERSION,
            "materialStationarityPolicyVersion": source_support_tracking.FOOT_MATERIAL_POLICY_VERSION,
            "sourceVideoSha256": video_sha, "sourcePoseVideoSha256": video_sha,
            "sourcePosePayloadSha256": pose_payload_sha, "sourcePoseFrameCount": 2,
            "sourceFrameCount": 4, "sourceFps": 30.0,
            "sourceTimesSec": [frame["sourceTimeSec"] for frame in clock_frames],
            "feet": {
                "left": {"states": ["unknown"] * 4},
                "right": {"states": ["unknown", "toe_only", "unknown", "toe_only"]},
            },
        },
    }
    evidence["sourcePoseSupportEvidencePolicyVersion"] = 3
    evidence["sourcePoseSupportContractFingerprint"] = source_pose_support_contract_fingerprint(contract)
    stage = {
        "reconstructionOnlyPendingInference": True, "contradiction": False, "timelineError": None,
        "contractInsufficient": True,
        "contractStatus": {
            "status": "insufficient_evidence",
            "failures": ["required_upper_back_center_support_unobserved"],
            "pendingInferenceRequirements": [upper_back],
        },
        "pendingInferenceRequirements": [upper_back, *foot_rows],
        "readiness": {
            "status": "incomplete", "passed": False, "required": True,
            "requiredSides": ["left", "right"], "unresolvedSides": ["left", "right"],
            "rejectionReasons": ["source_support_contact_evidence_incomplete"],
        },
        "evidence": evidence,
    }
    return stage, video, pose_path, contract


def test_required_foot_pending_route_is_exactly_bound_and_reconstruction_only(tmp_path, monkeypatch):
    stage, video, pose, contract = _stage(tmp_path, monkeypatch)
    readiness_before = copy.deepcopy(stage["readiness"])

    assert _reconstruction_only_pending_support_is_valid(
        stage, selected_video=video, source_pose_reference_path=pose, contract=contract,
    ) is True
    assert stage["readiness"] == readiness_before
    assert stage["contractStatus"]["status"] == "insufficient_evidence"
    assert stage["contractInsufficient"] is True


@pytest.mark.parametrize("mutation", [
    lambda stage: stage.update(reconstructionOnlyPendingInference=False),
    lambda stage: stage["readiness"].update(rejectionReasons=["source_support_contact_evidence_incomplete", "source_support_evidence_persistence_unavailable"]),
    lambda stage: stage["pendingInferenceRequirements"][1].update(sourceApproval=True),
    lambda stage: stage["pendingInferenceRequirements"][1].update(geometryApproval=True),
    lambda stage: stage["pendingInferenceRequirements"][1].update(sourceFrameClockReceiptSha256="0" * 64),
    lambda stage: stage["pendingInferenceRequirements"][2].update(unknownSelectedSourceFrameIndexes=[999]),
    lambda stage: stage["evidence"]["footPatchEvidence"]["feet"]["left"].update(states=["no_contact"] * 4),
    lambda stage: stage["readiness"].update(unresolvedSides=["left", "right", "center"]),
    lambda stage: stage["contractStatus"].update(failures=["required_foot_both_support_missing"]),
])
def test_pending_inference_fails_closed_on_unaccounted_or_unbound_evidence(tmp_path, monkeypatch, mutation):
    stage, video, pose, contract = _stage(tmp_path, monkeypatch)
    mutation(stage)

    assert _reconstruction_only_pending_support_is_valid(
        stage, selected_video=video, source_pose_reference_path=pose, contract=contract,
    ) is False


def test_pending_support_inference_is_nonexportable_and_nonterminal_processing():
    manifest = {"candidateResults": [{"status": "pending_support_inference"}]}

    diagnostics = final_processing_diagnostics(manifest)["candidateDiagnostics"]
    assert diagnostics[0]["stage"] == "support_inference"
    assert artifact_disposition(manifest) == "processing_incomplete"
    assert wave_manifest_is_exportable(manifest) is False
