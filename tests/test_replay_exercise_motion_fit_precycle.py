from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from exercise_motion_pkg.artifact_state import (
    CYCLIC_REBAKE,
    CYCLE_SELECTION,
    baked_payload_identity,
    build_artifact_state,
)
from exercise_motion_pkg import controlled_motion
from scripts import replay_exercise_motion_fit as replay


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _precycle_case(tmp_path: Path) -> dict:
    source = tmp_path / "selected.mp4"
    source.write_bytes(b"exact selected source bytes")
    selected_sha = _sha(source)
    parent_sha = "2" * 64
    clock = _write_json(tmp_path / "clock.json", {"sourceVideoSha256": parent_sha})
    selection_receipt = _write_json(tmp_path / "selection.json", {"role": "pre_reconstruction_validated_source_cut"})
    manifest = _write_json(tmp_path / "manifest.json", {"source": selected_sha})
    exact = _write_json(tmp_path / "exact-phase.json", {"passed": True})
    pose = {
        "sourceVideoSha256": selected_sha,
        "frames": [
            {"sourceTimeSec": index / 30.0, "joints": {"pelvis": [0.0, 0.0, 0.0]}}
            for index in range(3)
        ],
    }
    pose_path = _write_json(tmp_path / "pose.json", pose)
    contract = {
        "contractPolicyVersion": 39,
        "completionMode": "return_to_start",
        "exerciseName": "Synthetic Cycle",
    }
    contract_sha = hashlib.sha256(json.dumps(
        contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    identity = {
        "selectedSegmentSha256": selected_sha,
        "parentSourceSha256": parent_sha,
        "selectedFrameClockReceiptSha256": _sha(clock),
        "sourcePosePayloadSha256": "4" * 64,
    }
    mapping = {
        "schemaVersion": 1,
        "verified": True,
        "mappingKind": "selected_segment_to_parent_source",
        "selectedFrameCount": 3,
        "selectedFrameLineage": [
            {"selectedFrameIndex": i, "parentSourceFrameIndex": i + 20,
             "selectedFrameTimeSec": i / 30.0, "parentSourceTimeSec": 2.0 + i / 30.0}
            for i in range(3)
        ],
        "sourcePoseReferencePath": str(pose_path),
        "sourcePoseReferenceSha256": _sha(pose_path),
        "clockReceiptPath": str(clock),
        "clockReceiptSha256": _sha(clock),
        "selectionReceiptPath": str(selection_receipt),
        "selectionReceiptSha256": _sha(selection_receipt),
        "selectedSegmentPath": str(source),
        "selectedFrameClockReceiptSha256": _sha(clock),
        **identity,
    }
    payload = {
        "fps": 30.0,
        "frameCount": 3,
        "jointNames": ["pelvis"],
        "rootJoint": "pelvis",
        "loop": {"enabled": True},
        "frames": [
            {"timeSec": i / 30.0, "sourceTimeSec": 2.0 + i / 30.0,
             "joints": {"pelvis": [0.0, 1.0, 0.0]}}
            for i in range(3)
        ],
        "sourcePoseReference": pose,
        "exerciseMotionContract": contract,
        "sourcePoseCameraReference": {
            "sourceTimelineMapping": mapping,
            "camera": {"available": True, "sourceTimelineMappingIdentity": identity.copy()},
        },
        "preReconstructionSourceIntervalAuthority": {
            "authoritative": True,
            "reason": "exact_pre_reconstruction_return_cycle_validated",
            "exactValidationSource": "standalone_file",
            "selectedSegmentPath": str(source),
            "selectedSegmentSha256": selected_sha,
            "movementInstance": {"available": True, "trimmed": False},
        },
    }
    full_clip_identity = {
        "algorithm": "sha256", "identityVersion": 2,
        "contentSha256": "a" * 64, "frameCount": 3, "fps": 30.0,
    }
    selection_evidence = {
        "completionMode": "return_to_start",
        "loopEnabled": True,
        "cycleSelection": {"interval": {"startFrame": 0, "stopFrameExclusive": 3}},
        "fullClipBake": full_clip_identity,
        "cyclicRebake": baked_payload_identity(payload),
    }
    payload["artifactState"] = build_artifact_state(
        artifact_class=CYCLIC_REBAKE,
        selection_class=CYCLE_SELECTION,
        required_class=CYCLIC_REBAKE,
        selection_evidence=selection_evidence,
    )
    source_proof = {
        "schemaVersion": 1,
        "kind": "verified_pre_reconstruction_source_cycle",
        **identity,
        "authoritySelectedSegmentSha256": selected_sha,
        "contractSha256": contract_sha,
        "selectedFrameCount": 3,
        "phaseValidationSource": "standalone_file",
        "authorityReason": "exact_pre_reconstruction_return_cycle_validated",
    }
    proposal = {
        "startFrame": 0,
        "stopFrameExclusive": 3,
        "score": 1.0,
        "sourceOwnedCycleAuthority": source_proof,
    }
    payload["observedCycleProposals"] = [proposal]
    payload["sourceCyclePreflight"] = [{
        "passed": True,
        "reason": "verified_source_cycle_deferred_to_controlled_fit",
        "selection": proposal,
        "sourceOwnedCycleAuthority": source_proof,
        "sourcePhase": {"required": True, "passed": True, "hasSingleMajorCycle": True},
    }]
    prefit = _write_json(tmp_path / "prefit.json", payload)
    clearance = {
        "status": "cleared",
        "sourceManifestPath": str(manifest),
        "sourceManifestSha256": _sha(manifest),
        "selectedSegmentSha256": selected_sha,
    }
    proof = {
        "status": "ready",
        "contractUsable": True,
        "phasePassed": True,
        "prefitLineageValidated": True,
        "contractPolicyVersion": 39,
        "sourcePoseFrames": 3,
        "sourcePoseReferenceSha256": _sha(pose_path),
        "selectedSourceSha256": selected_sha,
        "phaseSourceSha256": selected_sha,
        "sourceManifestSha256": _sha(manifest),
        "sourceClearance": clearance,
        "sourceIntervalAuthority": payload["preReconstructionSourceIntervalAuthority"],
        "selectedSourcePath": str(source),
        "prefitPath": str(prefit),
        "prefitSha256": _sha(prefit),
    }
    receipt = {
        "schemaVersion": 1,
        "variantIdentity": "synthetic-normal-precycle-fit-input",
        "solverInputPoseDigest": replay.current_pose_digest(payload),
        "solverInputPayloadDigest": replay.canonical_digest(payload),
        "sourceEvidenceDigest": replay.current_source_evidence_digest(payload),
        "fitStrategy": "fixed_rig_controlled_motion_test",
        "fitKwargs": {"timeout_seconds": 360.0},
        "payload": payload,
        "sourcePoseReference": pose,
        "exerciseMotionContract": contract,
    }
    receipt_path = _write_json(tmp_path / "fit-input.json", receipt)
    proof_path = _write_json(tmp_path / "normal-proof.json", proof)
    return {
        "payload": payload,
        "receipt": receipt,
        "receiptPath": receipt_path,
        "proofPath": proof_path,
        "variant": receipt["variantIdentity"],
        "source": source,
    }


def test_normal_source_owned_precycle_fit_input_seals_with_exact_identity_and_kwargs(tmp_path):
    case = _precycle_case(tmp_path)
    identity = replay._selection_identity(case["payload"])
    assert identity["stage"] == "pre_cycle_fit_input"
    assert "selectionId" not in identity
    assert identity["selectedSegmentSha256"] == case["payload"][
        "preReconstructionSourceIntervalAuthority"]["selectedSegmentSha256"]

    output = tmp_path / "sealed.json"
    sealed = replay.seal_input(
        receipt_path=case["receiptPath"],
        receipt_sha256=_sha(case["receiptPath"]),
        variant_identity=case["variant"],
        payload_digest=case["receipt"]["solverInputPayloadDigest"],
        proof_path=case["proofPath"],
        output=output,
    )
    validated = replay._load_and_validate_bundle(
        bundle_path=output, bundle_sha256=sealed["bundleSha256"])
    content = validated["content"]
    assert content["selection"]["selectionIdentity"] == identity
    assert content["fit"]["kwargs"] == {"timeout_seconds": 360.0}
    assert "max_evaluations" not in content["fit"]["kwargs"]
    assert validated["payload"] == case["payload"]


@pytest.mark.parametrize("mutation", ["wrong_authority_digest", "two_proposals", "partial_interval", "terminal_state"])
def test_precycle_replay_rejects_unbound_or_incomplete_source_inputs(tmp_path, mutation):
    case = _precycle_case(tmp_path)
    payload = case["payload"]
    if mutation == "wrong_authority_digest":
        payload["preReconstructionSourceIntervalAuthority"]["selectedSegmentSha256"] = "f" * 64
    elif mutation == "two_proposals":
        payload["observedCycleProposals"].append(dict(payload["observedCycleProposals"][0]))
    elif mutation == "partial_interval":
        payload["observedCycleProposals"][0]["stopFrameExclusive"] = 2
    elif mutation == "terminal_state":
        payload["artifactState"]["terminal"] = True

    with pytest.raises(replay.ReplayError):
        replay._selection_identity(payload)
