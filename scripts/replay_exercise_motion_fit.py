"""Seal and replay one exact controlled-motion fit input.

The wrapper deliberately owns only provenance and persistence.  It does not
recreate fit policy, approve a movement, render, or publish anything.

Usage:
    python scripts/replay_exercise_motion_fit.py seal --help
    python scripts/replay_exercise_motion_fit.py preflight --help
    python scripts/replay_exercise_motion_fit.py run --help
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import inspect
import json
import math
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = 1
BUNDLE_KIND = "exercise_motion_fit_sealed_replay_input"
RESULT_KIND = "exercise_motion_fit_sealed_replay_result"
CANDIDATE_KIND = "exercise_motion_fit_rejected_candidate"
SCREEN_KIND = "exercise_motion_fit_cheap_screen"
SCREEN_CONTEXT_KIND = "controlled_motion_fit_context"
SCREEN_CONTEXT_ORIGINS = ("actual_fit", "reconstructed_normal_context")
SCREEN_STATUS_CONTEXT_UNAVAILABLE = "context_unavailable"
SCREEN_STATUS_KNOWN_FAILED = "known_failed"
SCREEN_STATUS_ELIGIBLE = "eligible_for_full_validation"

# A fixed, explicit set. This is intentionally not a directory scan. It
# includes every module directly imported by controlled_motion.py so the code
# receipt covers the actual fit owners as well as its central coordinator.
DEFAULT_CODE_MODULES = (
    "exercise_motion_pkg/native_material_frames.py",
    "exercise_motion_pkg/anatomical_repair.py",
    "exercise_motion_pkg/artifact_state.py",
    "exercise_motion_pkg/bake_and_rank.py",
    "exercise_motion_pkg/body_support_observation.py",
    "exercise_motion_pkg/canonical_rig_initialization.py",
    "exercise_motion_pkg/canonical_rig_projection.py",
    "exercise_motion_pkg/contact_heel_pitch.py",
    "exercise_motion_pkg/contact_heel_repair.py",
    "exercise_motion_pkg/contact_interpolation.py",
    "exercise_motion_pkg/controlled_motion.py",
    "exercise_motion_pkg/contact_constraints.py",
    "exercise_motion_pkg/equipment_constraints.py",
    "exercise_motion_pkg/fit_runtime.py",
    "exercise_motion_pkg/foot_contact_observation.py",
    "exercise_motion_pkg/support_geometry.py",
    "exercise_motion_pkg/native_foot_geometry.py",
    "exercise_motion_pkg/native_contact_reach.py",
    "exercise_motion_pkg/foot_kinematics.py",
    "exercise_motion_pkg/heel_contacts.py",
    "exercise_motion_pkg/joint_plant_initialization.py",
    "exercise_motion_pkg/loop_cycles.py",
    "exercise_motion_pkg/loop_seam.py",
    "exercise_motion_pkg/material_floor.py",
    "exercise_motion_pkg/material_region_support.py",
    "exercise_motion_pkg/motion_placement.py",
    "exercise_motion_pkg/native_marker_projection.py",
    "exercise_motion_pkg/native_foot_observations.py",
    "exercise_motion_pkg/pose_fidelity.py",
    "exercise_motion_pkg/positional_range.py",
    "exercise_motion_pkg/preview.py",
    "exercise_motion_pkg/rig_interpolation.py",
    "exercise_motion_pkg/rig_playback.py",
    "exercise_motion_pkg/rigid_material_constraints.py",
    "exercise_motion_pkg/scene_placement.py",
    "exercise_motion_pkg/sequence_stabilization.py",
    "exercise_motion_pkg/shoe_floor.py",
    "exercise_motion_pkg/smpl_joint_names.py",
    "exercise_motion_pkg/source_evidence.py",
    "exercise_motion_pkg/structural_refinement.py",
    "exercise_motion_pkg/support_alignment.py",
    "exercise_motion_pkg/support_joint_tracks.py",
    "exercise_motion_pkg/supported_contact_rig.py",
    "exercise_motion_pkg/foot_geometry.py",
    "exercise_motion_pkg/physical_validation.py",
    "exercise_motion_pkg/temporal_quality.py",
    "exercise_motion_pkg/temporal_rotation_smoothing.py",
    "exercise_motion_pkg/trajectory_restoration.py",
    "scripts/replay_exercise_motion_fit.py",
)

# Owned by the capture worker. Registered when present without making existing
# seal/preflight/run fail while the helper is still being created.
OPTIONAL_CODE_MODULES = (
    "exercise_motion_pkg/fit_context.py",
)

POSE_DIGEST_CODE_OWNERS = frozenset({
    "exercise_motion_pkg/sequence_stabilization.py",
    "exercise_motion_pkg/contact_constraints.py",
})
SOURCE_EVIDENCE_DIGEST_CODE_OWNERS = frozenset({
    "exercise_motion_pkg/controlled_motion.py",
    "exercise_motion_pkg/native_foot_geometry.py",
})

NORMAL_OWNER_VALIDATION = {
    "required": True,
    "status": "not_performed_by_wrapper",
    "note": (
        "The normal fit owner still validates policy, clock, pose, source, "
        "ordinary gates, source lineage, and root visual review."
    ),
}


class ReplayError(RuntimeError):
    """Fail-closed replay/provenance error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json_text(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_text(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReplayError(f"required JSON file does not exist: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"cannot read JSON file {path}: {exc}") from exc


def _write_new_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ReplayError(f"refusing to overwrite existing evidence file: {path}")
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _depth_get(mapping: Any, *keys: str) -> Any:
    current = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def current_pose_digest(payload: dict[str, Any]) -> str:
    from exercise_motion_pkg.sequence_stabilization import pose_digest

    return pose_digest(payload)


def current_source_evidence_digest(payload: dict[str, Any]) -> str:
    from exercise_motion_pkg.controlled_motion import (
        controlled_motion_fit_source_evidence_digest,
    )

    return controlled_motion_fit_source_evidence_digest(payload)


def _resolve(path_value: str | Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReplayError(f"{label} must be a JSON object")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ReplayError(f"{label} must be a 64-character sha256 string")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ReplayError(f"{label} is not hexadecimal") from exc
    return value.lower()


def _validate_fit_kwargs(fit_kwargs: dict[str, Any], fitter: Any) -> None:
    try:
        parameters = inspect.signature(fitter).parameters
    except (TypeError, ValueError) as exc:
        raise ReplayError(f"cannot inspect normal fit signature: {exc}") from exc
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD
           for parameter in parameters.values()):
        return
    unsupported = sorted(set(fit_kwargs) - set(parameters))
    if unsupported:
        raise ReplayError(
            "fit receipt contains unsupported keyword arguments: "
            + ", ".join(unsupported)
        )


def _dependency(
    role: str,
    path_value: str | Path,
    *,
    expected_sha256: str | None,
    require_expected_match: bool,
) -> dict[str, Any]:
    path = _resolve(path_value)
    if not path.is_file():
        raise ReplayError(f"{role} dependency does not exist: {path}")
    actual = file_sha256(path)
    expected = (
        _require_sha256(expected_sha256, f"{role} expected sha256")
        if expected_sha256 is not None
        else None
    )
    if expected is not None and actual != expected:
        raise ReplayError(
            f"{role} dependency hash mismatch: {path} expected {expected}, found {actual}"
        )
    if expected is None and require_expected_match:
        raise ReplayError(f"{role} dependency has no proof hash: {path}")
    return {
        "role": role,
        "path": str(path),
        "sha256": actual,
        "expectedSha256": expected,
        "bytes": path.stat().st_size,
    }


def _code_identity(relative_paths: Iterable[str]) -> dict[str, Any]:
    modules: dict[str, dict[str, Any]] = {}
    for relative in relative_paths:
        path = _resolve(relative)
        entry: dict[str, Any] = {"path": str(path)}
        if path.is_file():
            entry["sha256"] = file_sha256(path)
            entry["bytes"] = path.stat().st_size
        else:
            entry["sha256"] = None
            entry["bytes"] = None
        modules[relative] = entry
    hashes = {relative: entry["sha256"] for relative, entry in modules.items()}
    return {
        "modules": modules,
        "fingerprint": canonical_digest(hashes),
    }


def _seal_code_baseline(extra_code_files: Iterable[str]) -> dict[str, Any]:
    relative_paths = list(DEFAULT_CODE_MODULES)
    for optional in OPTIONAL_CODE_MODULES:
        if _resolve(optional).is_file():
            relative_paths.append(optional)
    for extra in extra_code_files:
        path = _resolve(extra)
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            relative = str(path)
        if relative not in relative_paths:
            relative_paths.append(relative)
    identity = _code_identity(relative_paths)
    missing = [name for name, entry in identity["modules"].items() if entry["sha256"] is None]
    if missing:
        raise ReplayError(f"baseline code files are missing: {', '.join(missing)}")
    return identity


def _compare_code_identity(
    baseline_modules: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    relative_paths = list(baseline_modules)
    current = _code_identity(relative_paths)
    baseline_hashes = {
        relative: entry.get("sha256") for relative, entry in baseline_modules.items()
    }
    current_hashes = {
        relative: entry.get("sha256") for relative, entry in current["modules"].items()
    }
    changed = [
        relative
        for relative in relative_paths
        if baseline_hashes.get(relative) != current_hashes.get(relative)
    ]
    comparison = {
        "baseline": baseline_hashes,
        "current": current_hashes,
        "baselineFingerprint": canonical_digest(baseline_hashes),
        "currentFingerprint": canonical_digest(current_hashes),
        "changedModules": changed,
        "concurrentOrIntentionalCodeChangeDetected": bool(changed),
    }
    return current, comparison


def _parse_dependency_argument(value: str) -> tuple[str, Path, str | None]:
    role, separator, rest = value.partition("=")
    if not separator or not role or not rest:
        raise ReplayError(
            "--dependency must be ROLE=PATH or ROLE=PATH=SHA256"
        )
    path_text, separator, sha = rest.rpartition("=")
    if not separator:
        return role, Path(rest), None
    return role, Path(path_text), sha


def _timeline_refs(payload: dict[str, Any]) -> dict[str, Any]:
    timeline = _depth_get(
        payload, "sourcePoseCameraReference", "sourceTimelineMapping"
    )
    timeline = _require_dict(timeline, "fitPayload.sourcePoseCameraReference.sourceTimelineMapping")
    required = {
        "sourcePoseReferencePath": "sourcePoseReferenceSha256",
        "clockReceiptPath": "clockReceiptSha256",
        "selectionReceiptPath": "selectionReceiptSha256",
        "selectedSegmentPath": "selectedSegmentSha256",
    }
    references: dict[str, Any] = {"timeline": timeline}
    for path_key, digest_key in required.items():
        path_value = timeline.get(path_key)
        digest_value = timeline.get(digest_key)
        if not isinstance(path_value, str) or not path_value:
            raise ReplayError(f"source timeline is missing {path_key}")
        if not isinstance(digest_value, str) or not digest_value:
            raise ReplayError(f"source timeline is missing {digest_key}")
        references[path_key] = path_value
        references[digest_key] = digest_value
    return references


def _validate_normal_proof(
    proof: dict[str, Any],
    *,
    payload: dict[str, Any],
    timeline: dict[str, Any],
) -> dict[str, Any]:
    if proof.get("status") != "ready":
        raise ReplayError(f"normal proof is not ready: {proof.get('status')!r}")
    if proof.get("contractUsable") is not True:
        raise ReplayError("normal proof does not declare a usable contract")
    if proof.get("phasePassed") is not True:
        raise ReplayError("normal proof does not declare a passed source phase")
    if proof.get("prefitLineageValidated") is not True:
        raise ReplayError("normal proof does not declare validated prefit lineage")

    contract = _require_dict(
        payload.get("exerciseMotionContract"), "fitPayload.exerciseMotionContract"
    )
    contract_policy = contract.get("contractPolicyVersion")
    if proof.get("contractPolicyVersion") != contract_policy:
        raise ReplayError(
            "normal proof contract policy does not match the sealed fit payload"
        )

    source_pose_frames = len(
        _require_dict(payload.get("sourcePoseReference"), "fitPayload.sourcePoseReference")
        .get("frames") or []
    )
    if proof.get("sourcePoseFrames") != source_pose_frames:
        raise ReplayError(
            "normal proof source pose frame count does not match the sealed payload"
        )

    source_pose_sha = _require_sha256(
        timeline.get("sourcePoseReferenceSha256"), "timeline sourcePoseReferenceSha256"
    )
    if proof.get("sourcePoseReferenceSha256") != source_pose_sha:
        raise ReplayError(
            "normal proof source pose hash does not match the sealed timeline"
        )

    support_evidence = payload.get("sourceFootSupportEvidence")
    if support_evidence is not None:
        support_digest = canonical_digest(support_evidence)
        if proof.get("sourceSupportEvidenceSha256") != support_digest:
            raise ReplayError(
                "normal proof source support evidence hash does not match the sealed payload"
            )

    selected_source_sha = _require_sha256(
        proof.get("selectedSourceSha256"), "normal proof selectedSourceSha256"
    )
    if timeline.get("selectedSegmentSha256") != selected_source_sha:
        raise ReplayError(
            "normal proof selected source hash does not match the sealed timeline"
        )
    if proof.get("phaseSourceSha256") != selected_source_sha:
        raise ReplayError("normal proof phase source hash differs from selected source")

    clearance = _require_dict(proof.get("sourceClearance"), "normal proof sourceClearance")
    if clearance.get("status") != "cleared":
        raise ReplayError("normal proof source clearance is not cleared")
    interval = _require_dict(
        proof.get("sourceIntervalAuthority"), "normal proof sourceIntervalAuthority"
    )
    if interval.get("authoritative") is not True:
        raise ReplayError("normal proof source interval is not authoritative")
    payload_authority = payload.get("preReconstructionSourceIntervalAuthority")
    if isinstance(payload_authority, dict) and payload_authority.get("authoritative") is True:
        if (
            interval.get("selectedSegmentSha256") != selected_source_sha
            or payload_authority.get("selectedSegmentSha256") != selected_source_sha
            or interval.get("selectedSegmentPath") != payload_authority.get("selectedSegmentPath")
        ):
            raise ReplayError(
                "normal source interval authority is not byte-bound to the sealed selected source"
            )
    return {
        "sourceManifestPath": clearance.get("sourceManifestPath"),
        "sourceManifestSha256": _require_sha256(
            proof.get("sourceManifestSha256"), "normal proof sourceManifestSha256"
        ),
        "selectedSourcePath": proof.get("selectedSourcePath"),
        "selectedSourceSha256": selected_source_sha,
        "prefitPath": proof.get("prefitPath"),
        "prefitSha256": _require_sha256(
            proof.get("prefitSha256"), "normal proof prefitSha256"
        ),
        "exactValidationPath": interval.get("exactValidationPath"),
        "sourceIntervalAuthority": interval,
        "sourceClearance": clearance,
    }


def _selection_identity(payload: dict[str, Any]) -> dict[str, Any]:
    selection_evidence = _depth_get(payload, "artifactState", "selectionEvidence")
    if not isinstance(selection_evidence, dict):
        raise ReplayError("fit payload is missing artifactState selection evidence")
    cycle_selection = selection_evidence.get("cycleSelection")
    if cycle_selection is not None and not isinstance(cycle_selection, dict):
        raise ReplayError("fit payload artifactState cycleSelection is malformed")
    selection_id = cycle_selection.get("selectionId") if isinstance(cycle_selection, dict) else None
    if isinstance(selection_id, str) and selection_id:
        return {
            "selectionId": selection_id,
            "interval": cycle_selection.get("interval"),
            "sourceInterval": cycle_selection.get("sourceInterval"),
        }
    return _pre_cycle_fit_input_identity(payload, selection_evidence, cycle_selection)


def _pre_cycle_fit_input_identity(
    payload: dict[str, Any], selection_evidence: dict[str, Any],
    cycle_selection: dict[str, Any] | None,
) -> dict[str, Any]:
    """Bind a normal source-owned pre-cycle fit input without inventing a selection ID."""
    state = _require_dict(_depth_get(payload, "artifactState"), "fitPayload.artifactState")
    evidence = _require_dict(
        state.get("selectionEvidence"), "fitPayload.artifactState.selectionEvidence"
    )
    frames = payload.get("frames")
    count = len(frames) if isinstance(frames, list) else 0
    if (
        state.get("artifactClass") != "cyclic_rebake"
        or state.get("requiredClass") != "cyclic_rebake"
        or state.get("terminal") is not False
        or state.get("lineageComplete") is not False
        or state.get("history") != ["cycle_selection", "cyclic_rebake"]
        or evidence != selection_evidence
        or (isinstance(cycle_selection, dict) and cycle_selection.get("selectionId") not in (None, ""))
        or evidence.get("completionMode") != "return_to_start"
        or evidence.get("loopEnabled") is not True
        or not count
        or payload.get("frameCount") != count
    ):
        raise ReplayError("fit payload is not a normal incomplete pre-cycle input")

    from exercise_motion_pkg.artifact_state import (
        baked_payload_identity,
        validate_artifact_state,
    )
    try:
        validate_artifact_state(state, movement_payload=payload)
        full_clip = _require_dict(evidence.get("fullClipBake"), "pre-cycle fullClipBake")
        cyclic_rebake = _require_dict(evidence.get("cyclicRebake"), "pre-cycle cyclicRebake")
        if cyclic_rebake != baked_payload_identity(payload):
            raise ReplayError("pre-cycle cyclic rebake identity differs from its payload")
    except ReplayError:
        raise
    except (TypeError, ValueError) as exc:
        raise ReplayError(f"pre-cycle artifact state is invalid: {exc}") from exc

    def is_sha256(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value.casefold())
        )

    try:
        fps = float(payload.get("fps"))
        full_fps = float(full_clip.get("fps"))
        rebake_fps = float(cyclic_rebake.get("fps"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReplayError("pre-cycle artifact identities have invalid frame rates") from exc
    if (
        full_clip.get("algorithm") != "sha256"
        or full_clip.get("frameCount") != count
        or not is_sha256(full_clip.get("contentSha256"))
        or cyclic_rebake.get("algorithm") != "sha256"
        or cyclic_rebake.get("frameCount") != count
        or not math.isfinite(fps)
        or full_fps != fps
        or rebake_fps != fps
    ):
        raise ReplayError("pre-cycle full-clip parent identity is incomplete or mismatched")

    authority = _require_dict(
        payload.get("preReconstructionSourceIntervalAuthority"),
        "fitPayload.preReconstructionSourceIntervalAuthority",
    )
    mapping = _require_dict(
        _depth_get(payload, "sourcePoseCameraReference", "sourceTimelineMapping"),
        "fitPayload.sourcePoseCameraReference.sourceTimelineMapping",
    )
    camera = _require_dict(
        _depth_get(payload, "sourcePoseCameraReference", "camera"),
        "fitPayload.sourcePoseCameraReference.camera",
    )
    mapping_identity = _require_dict(
        camera.get("sourceTimelineMappingIdentity"),
        "fitPayload camera sourceTimelineMappingIdentity",
    )
    from exercise_motion_pkg.contact_constraints import _validated_selected_frame_lineage
    lineage = _validated_selected_frame_lineage(mapping)
    selected_sha = mapping.get("selectedSegmentSha256")
    parent_sha = mapping.get("parentSourceSha256")
    clock_sha = mapping.get("selectedFrameClockReceiptSha256")
    pose_sha = mapping.get("sourcePosePayloadSha256")
    identity_keys = (
        "selectedSegmentSha256",
        "parentSourceSha256",
        "selectedFrameClockReceiptSha256",
        "sourcePosePayloadSha256",
    )
    if (
        authority.get("authoritative") is not True
        or authority.get("reason") != "exact_pre_reconstruction_return_cycle_validated"
        or authority.get("exactValidationSource") not in {"standalone_file", "segment_selection_embedded"}
        or not isinstance(authority.get("selectedSegmentPath"), str)
        or not is_sha256(authority.get("selectedSegmentSha256"))
        or authority.get("selectedSegmentSha256") != selected_sha
        or mapping.get("selectedFrameCount") != count
        or not isinstance(lineage, list)
        or len(lineage) != count
        or camera.get("available") is not True
        or not all(is_sha256(mapping.get(key)) and mapping_identity.get(key) == mapping.get(key)
                   for key in identity_keys)
        or not isinstance(payload.get("sourcePoseReference"), dict)
        or payload["sourcePoseReference"].get("sourceVideoSha256") != selected_sha
    ):
        raise ReplayError("pre-cycle source authority does not bind the full selected source")

    proposals = payload.get("observedCycleProposals")
    if not isinstance(proposals, list) or len(proposals) != 1:
        raise ReplayError("pre-cycle fit input must contain exactly one source-owned proposal")
    proposal = _require_dict(proposals[0], "pre-cycle source-owned proposal")
    if proposal.get("startFrame") != 0 or proposal.get("stopFrameExclusive") != count:
        raise ReplayError("pre-cycle source-owned proposal does not cover the full selected clip")
    from exercise_motion_pkg.controlled_motion import _verified_source_owned_cycle_choice
    if not _verified_source_owned_cycle_choice(payload, proposal):
        raise ReplayError("pre-cycle source-owned proposal is not verified against current evidence")
    proposal_proof = _require_dict(
        proposal.get("sourceOwnedCycleAuthority"), "pre-cycle source-owned authority proof"
    )
    if proposal_proof.get("authoritySelectedSegmentSha256") != authority.get("selectedSegmentSha256"):
        raise ReplayError("pre-cycle proposal authority digest differs from selected source bytes")

    return {
        "stage": "pre_cycle_fit_input",
        "selectedFrameCount": count,
        "selectedSegmentSha256": selected_sha,
        "parentSourceSha256": parent_sha,
        "selectedFrameClockReceiptSha256": clock_sha,
        "sourcePosePayloadSha256": pose_sha,
        "fullClipBakeIdentity": full_clip,
        "cyclicRebakeIdentity": cyclic_rebake,
        "sourceOwnedCycleAuthority": proposal_proof,
    }


def seal_input(
    *,
    receipt_path: str | Path,
    receipt_sha256: str,
    variant_identity: str,
    payload_digest: str,
    proof_path: str | Path,
    output: str | Path,
    extra_dependencies: Iterable[str] = (),
    extra_code_files: Iterable[str] = (),
) -> dict[str, Any]:
    """Seal one exact named receipt/variant into one self-contained bundle."""
    receipt_path = _resolve(receipt_path)
    expected_receipt_sha = _require_sha256(receipt_sha256, "--receipt-sha256")
    expected_payload_digest = _require_sha256(payload_digest, "--payload-digest")
    if not variant_identity:
        raise ReplayError("--variant must be an exact non-empty variant identity")
    if not receipt_path.is_file():
        raise ReplayError(f"receipt does not exist: {receipt_path}")
    actual_receipt_sha = file_sha256(receipt_path)
    if actual_receipt_sha != expected_receipt_sha:
        raise ReplayError(
            f"receipt hash mismatch: expected {expected_receipt_sha}, found {actual_receipt_sha}"
        )

    receipt = _require_dict(_read_json(receipt_path), "receipt")
    payload = _require_dict(receipt.get("payload"), "receipt.payload")
    fit_kwargs = _require_dict(receipt.get("fitKwargs"), "receipt.fitKwargs")
    from exercise_motion_pkg.controlled_motion import fit_controlled_motion
    _validate_fit_kwargs(fit_kwargs, fit_controlled_motion)
    if receipt.get("variantIdentity") != variant_identity:
        raise ReplayError(
            f"variant mismatch: receipt has {receipt.get('variantIdentity')!r}, "
            f"requested {variant_identity!r}"
        )
    actual_payload_digest = canonical_digest(payload)
    if actual_payload_digest != expected_payload_digest:
        raise ReplayError(
            f"payload digest mismatch: requested {expected_payload_digest}, "
            f"canonical payload is {actual_payload_digest}"
        )
    if receipt.get("solverInputPayloadDigest") != actual_payload_digest:
        raise ReplayError("receipt solverInputPayloadDigest does not match its payload")

    source_pose_reference = _require_dict(
        receipt.get("sourcePoseReference"), "receipt.sourcePoseReference"
    )
    contract = _require_dict(
        receipt.get("exerciseMotionContract"), "receipt.exerciseMotionContract"
    )
    if payload.get("sourcePoseReference") != source_pose_reference:
        raise ReplayError("receipt sourcePoseReference differs from fit payload")
    if payload.get("exerciseMotionContract") != contract:
        raise ReplayError("receipt exerciseMotionContract differs from fit payload")

    pose_digest_value = current_pose_digest(payload)
    if receipt.get("solverInputPoseDigest") != pose_digest_value:
        raise ReplayError(
            "receipt solverInputPoseDigest does not match the current normal pose digest"
        )
    source_evidence_value = current_source_evidence_digest(payload)
    if receipt.get("sourceEvidenceDigest") != source_evidence_value:
        raise ReplayError(
            "receipt sourceEvidenceDigest does not match the current normal source evidence digest"
        )

    timeline = _timeline_refs(payload)
    proof_path = _resolve(proof_path)
    proof = _require_dict(_read_json(proof_path), "normal proof")
    proof_references = _validate_normal_proof(
        proof, payload=payload, timeline=timeline
    )

    dependencies: list[dict[str, Any]] = []

    def add_dependency(
        role: str,
        path_value: str | Path | None,
        expected_sha: str | None,
    ) -> None:
        if not path_value:
            raise ReplayError(f"normal proof is missing dependency path for {role}")
        dependencies.append(
            _dependency(
                role,
                path_value,
                expected_sha256=expected_sha,
                require_expected_match=False,
            )
        )

    add_dependency(
        "source_pose_reference",
        timeline["sourcePoseReferencePath"],
        timeline["sourcePoseReferenceSha256"],
    )
    add_dependency(
        "source_frame_clock_receipt",
        timeline["clockReceiptPath"],
        timeline["clockReceiptSha256"],
    )
    add_dependency(
        "selection_receipt",
        timeline["selectionReceiptPath"],
        timeline["selectionReceiptSha256"],
    )
    add_dependency(
        "selected_segment",
        timeline["selectedSegmentPath"],
        timeline["selectedSegmentSha256"],
    )
    add_dependency(
        "normal_preflight_proof",
        proof_path,
        file_sha256(proof_path),
    )
    add_dependency("fit_input_receipt", receipt_path, actual_receipt_sha)
    add_dependency(
        "source_manifest",
        proof_references["sourceManifestPath"],
        proof_references["sourceManifestSha256"],
    )
    add_dependency(
        "normal_proof_selected_source",
        proof_references["selectedSourcePath"],
        proof_references["selectedSourceSha256"],
    )
    add_dependency(
        "normal_proof_prefit_artifact",
        proof_references["prefitPath"],
        proof_references["prefitSha256"],
    )
    exact_validation_path = proof_references.get("exactValidationPath")
    if exact_validation_path:
        dependencies.append(
            _dependency(
                "source_interval_exact_validation",
                exact_validation_path,
                expected_sha256=None,
                require_expected_match=False,
            )
        )
    for raw in extra_dependencies:
        role, path, expected = _parse_dependency_argument(raw)
        dependencies.append(
            _dependency(
                role,
                path,
                expected_sha256=expected,
                require_expected_match=False,
            )
        )

    code_baseline = _seal_code_baseline(extra_code_files)
    selection_identity = _selection_identity(payload)
    content = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": BUNDLE_KIND,
        "sealedAtUtc": utc_now(),
        "producer": {
            "script": str(Path(__file__).resolve()),
            "scriptSha256": file_sha256(Path(__file__).resolve()),
        },
        "selection": {
            "variantIdentity": variant_identity,
            "solverInputPayloadDigest": actual_payload_digest,
            "solverInputPoseDigest": pose_digest_value,
            "sourceEvidenceDigest": source_evidence_value,
            "fitStrategy": receipt.get("fitStrategy"),
            "selectionIdentity": selection_identity,
        },
        "receipt": {
            "path": str(receipt_path),
            "sha256": actual_receipt_sha,
            "bytes": receipt_path.stat().st_size,
        },
        "fit": {
            "payload": payload,
            "kwargs": fit_kwargs,
        },
        "references": {
            "sourceTimeline": timeline,
            "normalProof": {
                "path": str(proof_path),
                "sha256": file_sha256(proof_path),
                **proof_references,
            },
            "contract": {
                "canonicalDigest": canonical_digest(contract),
                "policyVersion": contract.get("contractPolicyVersion"),
                "exerciseName": contract.get("exerciseName"),
            },
            "sourceSupportEvidence": {
                "canonicalDigest": (
                    canonical_digest(payload["sourceFootSupportEvidence"])
                    if payload.get("sourceFootSupportEvidence") is not None
                    else None
                ),
                "policyVersion": _depth_get(
                    payload, "sourceFootSupportEvidence", "sourcePoseSupportEvidencePolicyVersion"
                ),
            },
        },
        "dependencies": dependencies,
        "code": {
            "baselineModules": code_baseline["modules"],
            "baselineFingerprint": code_baseline["fingerprint"],
        },
        "normalOwnerValidation": NORMAL_OWNER_VALIDATION,
    }
    content_digest = canonical_digest(content)
    bundle = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": BUNDLE_KIND,
        "contentDigest": content_digest,
        "content": content,
    }

    output_path = _resolve(output)
    if output_path.suffix.lower() != ".json":
        output_path = output_path / f"fit-replay-{content_digest[:16]}.json"
    _write_new_json(output_path, bundle)
    bundle_sha = file_sha256(output_path)
    return {
        "mode": "seal",
        "status": "ok",
        "bundlePath": str(output_path),
        "bundleSha256": bundle_sha,
        "contentDigest": content_digest,
        "variantIdentity": variant_identity,
        "payloadDigest": actual_payload_digest,
        "receiptSha256": actual_receipt_sha,
        "dependencyCount": len(dependencies),
        "codeBaselineFingerprint": code_baseline["fingerprint"],
        "normalOwnerValidation": NORMAL_OWNER_VALIDATION,
    }


def _load_and_validate_bundle(
    *,
    bundle_path: str | Path,
    bundle_sha256: str,
    verify_dependencies: bool = True,
) -> dict[str, Any]:
    bundle_path = _resolve(bundle_path)
    expected_bundle_sha = _require_sha256(bundle_sha256, "--bundle-sha256")
    if not bundle_path.is_file():
        raise ReplayError(f"bundle does not exist: {bundle_path}")
    actual_bundle_sha = file_sha256(bundle_path)
    if actual_bundle_sha != expected_bundle_sha:
        raise ReplayError(
            f"bundle hash mismatch: expected {expected_bundle_sha}, found {actual_bundle_sha}"
        )
    bundle = _require_dict(_read_json(bundle_path), "bundle")
    if bundle.get("kind") != BUNDLE_KIND or bundle.get("schemaVersion") != SCHEMA_VERSION:
        raise ReplayError("bundle kind/schema is not a sealed fit replay input")
    content = _require_dict(bundle.get("content"), "bundle.content")
    if canonical_digest(content) != bundle.get("contentDigest"):
        raise ReplayError("bundle canonical content digest mismatch")

    selection = _require_dict(content.get("selection"), "bundle.selection")
    fit = _require_dict(content.get("fit"), "bundle.fit")
    payload = _require_dict(fit.get("payload"), "bundle.fit.payload")
    _require_dict(fit.get("kwargs"), "bundle.fit.kwargs")
    if not selection.get("variantIdentity"):
        raise ReplayError("bundle has no exact variant identity")
    recorded_selection_identity = _require_dict(
        selection.get("selectionIdentity"), "bundle.selection.selectionIdentity"
    )
    current_selection_identity = _selection_identity(payload)
    if recorded_selection_identity != current_selection_identity:
        raise ReplayError("sealed selection stage identity no longer matches the exact fit payload")
    payload_digest = canonical_digest(payload)
    if payload_digest != selection.get("solverInputPayloadDigest"):
        raise ReplayError("sealed fit payload digest mismatch")
    receipt_identity = _require_dict(content.get("receipt"), "bundle.receipt")
    if receipt_identity.get("sha256") is None:
        raise ReplayError("bundle is missing the exact receipt identity")

    code_baseline = _require_dict(
        _depth_get(content, "code", "baselineModules"), "bundle.code.baselineModules"
    )
    required_digest_owners = (
        POSE_DIGEST_CODE_OWNERS | SOURCE_EVIDENCE_DIGEST_CODE_OWNERS
    )
    missing_digest_owners = sorted(required_digest_owners - set(code_baseline))
    if missing_digest_owners:
        raise ReplayError(
            "sealed code baseline is missing digest owners: "
            + ", ".join(missing_digest_owners)
        )
    current_code, code_comparison = _compare_code_identity(code_baseline)

    pose_digest_matches = None
    source_evidence_matches = None
    try:
        pose_digest_matches = current_pose_digest(payload) == selection.get(
            "solverInputPoseDigest"
        )
        source_evidence_matches = current_source_evidence_digest(payload) == selection.get(
            "sourceEvidenceDigest"
        )
    except Exception as exc:  # pragma: no cover - import/runtime guard
        code_comparison["digestUtilityError"] = f"{type(exc).__name__}: {exc}"

    changed_modules = set(code_comparison.get("changedModules") or [])
    pose_digest_mismatch_owner_changed = (
        pose_digest_matches is False
        and bool(changed_modules & POSE_DIGEST_CODE_OWNERS)
    )
    source_digest_mismatch_owner_changed = (
        source_evidence_matches is False
        and bool(changed_modules & SOURCE_EVIDENCE_DIGEST_CODE_OWNERS)
    )
    code_comparison["poseDigestMismatchOwnerChanged"] = pose_digest_mismatch_owner_changed
    code_comparison["sourceEvidenceMismatchOwnerChanged"] = source_digest_mismatch_owner_changed
    if pose_digest_matches is None or source_evidence_matches is None:
        raise ReplayError("cannot verify sealed pose/source evidence digests")
    if pose_digest_matches is False and not pose_digest_mismatch_owner_changed:
        raise ReplayError("sealed solver input pose digest mismatch")
    if source_evidence_matches is False and not source_digest_mismatch_owner_changed:
        raise ReplayError("sealed source evidence digest mismatch")

    dependencies = content.get("dependencies") or []
    if not isinstance(dependencies, list):
        raise ReplayError("bundle.dependencies must be a list")
    if verify_dependencies:
        receipt_path = _resolve(receipt_identity.get("path") or "")
        expected_receipt_sha = _require_sha256(
            receipt_identity.get("sha256"), "bundle.receipt.sha256"
        )
        if not receipt_path.is_file():
            raise ReplayError(f"fit input receipt is missing: {receipt_path}")
        actual_receipt_sha = file_sha256(receipt_path)
        if actual_receipt_sha != expected_receipt_sha:
            raise ReplayError(
                f"fit input receipt hash mismatch: {receipt_path} expected "
                f"{expected_receipt_sha}, found {actual_receipt_sha}"
            )
        for entry in dependencies:
            entry = _require_dict(entry, "bundle dependency")
            role = entry.get("role") or "dependency"
            path = _resolve(entry.get("path") or "")
            if not path.is_file():
                raise ReplayError(f"{role} dependency is missing: {path}")
            expected = _require_sha256(
                entry.get("sha256"), f"{role} sealed sha256"
            )
            actual = file_sha256(path)
            if actual != expected:
                raise ReplayError(
                    f"{role} dependency hash mismatch: {path} expected {expected}, found {actual}"
                )

    return {
        "bundle": bundle,
        "content": content,
        "payload": payload,
        "payloadDigest": payload_digest,
        "bundlePath": bundle_path,
        "bundleSha256": actual_bundle_sha,
        "currentCode": current_code,
        "codeComparison": code_comparison,
        "poseDigestMatches": pose_digest_matches,
        "sourceEvidenceMatches": source_evidence_matches,
    }


def preflight_bundle(
    *,
    bundle_path: str | Path,
    bundle_sha256: str,
    output: str | Path | None = None,
) -> dict[str, Any]:
    validated = _load_and_validate_bundle(
        bundle_path=bundle_path, bundle_sha256=bundle_sha256
    )
    content = validated["content"]
    result = {
        "mode": "preflight",
        "status": "ok",
        "checkedAtUtc": utc_now(),
        "bundlePath": str(validated["bundlePath"]),
        "bundleSha256": validated["bundleSha256"],
        "contentDigest": validated["bundle"].get("contentDigest"),
        "variantIdentity": content["selection"]["variantIdentity"],
        "payloadDigest": validated["payloadDigest"],
        "dependencyCount": len(content.get("dependencies") or []),
        "dependenciesVerified": True,
        "code": validated["codeComparison"],
        "poseDigestMatches": validated["poseDigestMatches"],
        "sourceEvidenceMatches": validated["sourceEvidenceMatches"],
        "normalOwnerValidation": content.get("normalOwnerValidation"),
        "fitterCalled": False,
    }
    if output is not None:
        path = _resolve(output)
        _write_new_json(path, result)
        result["outputPath"] = str(path)
    return result


def _available_solver_stats(report: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "nfev",
        "njev",
        "cost",
        "optimality",
        "activeMask",
        "status",
        "message",
        "optimizerTermination",
        "timeBudgetSeconds",
        "cpuFitQueueWaitSeconds",
    )
    return {key: report[key] for key in keys if key in report}


def _candidate_record(
    candidate: dict[str, Any],
    report: dict[str, Any],
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": CANDIDATE_KIND,
        "capturedAtUtc": utc_now(),
        "candidatePayload": candidate,
        "report": report,
        "inputPayloadDigest": canonical_digest(input_payload),
        "candidatePayloadDigest": canonical_digest(candidate),
    }
    try:
        record["candidatePoseDigest"] = current_pose_digest(candidate)
    except Exception as exc:  # pragma: no cover - diagnostic only
        record["candidatePoseDigestError"] = f"{type(exc).__name__}: {exc}"
    try:
        record["candidateSourceEvidenceDigest"] = current_source_evidence_digest(candidate)
    except Exception as exc:  # pragma: no cover - diagnostic only
        record["candidateSourceEvidenceDigestError"] = f"{type(exc).__name__}: {exc}"
    return record


def run_bundle(
    *,
    bundle_path: str | Path,
    bundle_sha256: str,
    output_dir: str | Path,
    timeout_seconds: float | None = None,
    max_evaluations: int | None = None,
) -> dict[str, Any]:
    """Run one sealed bundle through the normal fit under the rejected-candidate hook."""
    validated = _load_and_validate_bundle(
        bundle_path=bundle_path, bundle_sha256=bundle_sha256
    )
    content = validated["content"]
    payload = copy.deepcopy(validated["payload"])
    requested_kwargs = dict(_require_dict(content["fit"].get("kwargs"), "sealed fit kwargs"))
    if timeout_seconds is not None:
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0.0:
            raise ReplayError("--timeout-seconds override must be a positive finite number")
        requested_kwargs["timeout_seconds"] = timeout
    if max_evaluations is not None:
        maximum = int(max_evaluations)
        if maximum <= 0:
            raise ReplayError("--max-evaluations override must be positive")
        requested_kwargs["max_evaluations"] = maximum

    from exercise_motion_pkg import controlled_motion as motion
    _validate_fit_kwargs(requested_kwargs, motion.fit_controlled_motion)

    output_path = _resolve(output_dir)
    if output_path.exists() and any(output_path.iterdir()):
        raise ReplayError(f"run output directory is not empty: {output_path}")
    output_path.mkdir(parents=True, exist_ok=True)

    pre_run_code = validated["currentCode"]
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "exercise_motion_fit_sealed_replay_run_manifest",
        "startedAtUtc": utc_now(),
        "bundlePath": str(validated["bundlePath"]),
        "bundleSha256": validated["bundleSha256"],
        "contentDigest": validated["bundle"].get("contentDigest"),
        "variantIdentity": content["selection"]["variantIdentity"],
        "payloadDigest": validated["payloadDigest"],
        "receipt": content.get("receipt"),
        "requestedFitKwargs": requested_kwargs,
        "code": {
            "baseline": content["code"].get("baselineModules"),
            "baselineFingerprint": content["code"].get("baselineFingerprint"),
            "preRun": pre_run_code,
            "comparison": validated["codeComparison"],
        },
        "normalOwnerValidation": content.get("normalOwnerValidation"),
    }
    _write_new_json(output_path / "run-manifest.json", manifest)

    rejected_records: list[dict[str, Any]] = []
    rejected_dir = output_path / "rejected-candidates"

    def persist_rejected(
        candidate: dict[str, Any],
        report: dict[str, Any],
        input_payload: dict[str, Any],
    ) -> dict[str, Any]:
        record = _candidate_record(candidate, report, input_payload)
        rejected_dir.mkdir(parents=True, exist_ok=True)
        index = len(rejected_records) + 1
        digest_prefix = record["candidatePayloadDigest"][:16]
        candidate_path = rejected_dir / f"rejected-{index:03d}-{digest_prefix}.json"
        _write_new_json(candidate_path, record)
        reference = {
            "path": str(candidate_path),
            "sha256": file_sha256(candidate_path),
            "candidatePayloadDigest": record["candidatePayloadDigest"],
        }
        if "candidatePoseDigest" in record:
            reference["candidatePoseDigest"] = record["candidatePoseDigest"]
        rejected_records.append(reference)
        return reference

    started = time.monotonic()
    returned_result: dict[str, Any] | None = None
    fit_report: dict[str, Any] | None = None
    exception_info: dict[str, Any] | None = None
    try:
        with motion.capture_rejected_fit_candidate(persist_rejected):
            returned_result, fit_report = motion.fit_controlled_motion(
                payload, **requested_kwargs
            )
    except BaseException as exc:  # preserve evidence before surfacing
        exception_info = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    wall_seconds = time.monotonic() - started
    post_run_code, post_comparison = _compare_code_identity(
        content["code"]["baselineModules"]
    )

    returned_payload_digest = (
        canonical_digest(returned_result) if isinstance(returned_result, dict) else None
    )
    returned_payload_same_as_input = returned_payload_digest == validated["payloadDigest"]
    if isinstance(returned_result, dict) and not returned_payload_same_as_input:
        _write_new_json(output_path / "fit-returned-payload.json", returned_result)

    report = _require_dict(fit_report, "fit report") if isinstance(fit_report, dict) else {}
    gate_vector = report.get("checks") if isinstance(report.get("checks"), dict) else None
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": RESULT_KIND,
        "status": "error" if exception_info else "ok",
        "finishedAtUtc": utc_now(),
        "bundlePath": str(validated["bundlePath"]),
        "bundleSha256": validated["bundleSha256"],
        "contentDigest": validated["bundle"].get("contentDigest"),
        "variantIdentity": content["selection"]["variantIdentity"],
        "inputIdentities": {
            "payloadDigest": validated["payloadDigest"],
            "solverInputPoseDigest": content["selection"].get("solverInputPoseDigest"),
            "sourceEvidenceDigest": content["selection"].get("sourceEvidenceDigest"),
            "receipt": content.get("receipt"),
            "selectionIdentity": content["selection"].get("selectionIdentity"),
            "poseDigestMatchesCurrentCode": validated["poseDigestMatches"],
            "sourceEvidenceMatchesCurrentCode": validated["sourceEvidenceMatches"],
        },
        "requestedFitKwargs": requested_kwargs,
        "wallClockSeconds": wall_seconds,
        "fitReport": report,
        "fitAppliedAsReturned": report.get("applied"),
        "gateVector": gate_vector,
        "availableSolverStats": _available_solver_stats(report),
        "returnedPayloadDigest": returned_payload_digest,
        "returnedPayloadSameAsInput": returned_payload_same_as_input,
        "rejectedCandidates": rejected_records,
        "codeIdentity": {
            "baseline": content["code"].get("baselineModules"),
            "baselineFingerprint": content["code"].get("baselineFingerprint"),
            "preRun": pre_run_code,
            "postRun": post_run_code,
            "preRunComparison": validated["codeComparison"],
            "postRunComparison": post_comparison,
        },
        "exception": exception_info,
        "acceptance": {
            "status": "not_evaluated_by_wrapper",
            "movementAccepted": False,
            "published": False,
            "rendered": False,
            "note": (
                "Ordinary current gates, source/lineage proof, and root visual review "
                "remain required."
            ),
        },
    }
    result_path = output_path / "run-result.json"
    _write_new_json(result_path, result)
    summary = {
        "mode": "run",
        "status": result["status"],
        "bundlePath": result["bundlePath"],
        "bundleSha256": result["bundleSha256"],
        "outputDir": str(output_path),
        "resultPath": str(result_path),
        "rejectedCandidatePaths": [entry["path"] for entry in rejected_records],
        "fitAppliedAsReturned": report.get("applied"),
        "acceptanceStatus": "not_evaluated_by_wrapper",
        "movementAccepted": False,
        "wallClockSeconds": wall_seconds,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if exception_info is not None:
        raise ReplayError(
            f"fit raised {exception_info['type']}: {exception_info['message']}"
        )
    return result


def _numpy() -> Any:
    import numpy

    return numpy


def _fit_context_helper() -> tuple[Any | None, str | None]:
    """Import the capture-owned helper lazily so seal/preflight/run stay usable."""
    try:
        spec = importlib.util.find_spec("exercise_motion_pkg.fit_context")
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        return None, None
    try:
        from exercise_motion_pkg import fit_context as helper
    except Exception as exc:  # a broken helper must fail closed, not be ignored
        return None, f"fit_context_import_failed: {type(exc).__name__}: {exc}"
    return helper, None


def _candidate_payload_from_document(document: Any) -> dict[str, Any]:
    document = _require_dict(document, "candidate/diagnostic")
    candidate = document.get("candidatePayload")
    if isinstance(candidate, dict):
        return candidate
    if isinstance(document.get("frames"), list) and isinstance(
        document.get("jointNames"), list
    ):
        return document
    raise ReplayError(
        "candidate file must be a candidate payload or a diagnostic with candidatePayload"
    )


def _captured_context_from_document(
    document: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Read only explicitly captured context; never inherited controlledMotionFit data."""
    document = _require_dict(document, "candidate/diagnostic")
    if isinstance(document.get("fitContext"), dict):
        return document["fitContext"], "diagnostic_top_level_fitContext"
    for report_key in ("report", "fitReport"):
        report = document.get(report_key)
        if isinstance(report, dict) and isinstance(report.get("fitContext"), dict):
            return report["fitContext"], f"diagnostic_{report_key}_fitContext"
    return None, None


def _candidate_points(
    candidate: dict[str, Any], names: list[str], *, reasons: list[str]
) -> Any | None:
    np = _numpy()
    frames = candidate.get("frames")
    if not isinstance(frames, list) or not frames:
        reasons.append("candidate_frames_missing")
        return None
    rows: list[list[Any]] = []
    for frame_index, frame in enumerate(frames):
        joints = frame.get("joints") if isinstance(frame, dict) else None
        if not isinstance(joints, dict):
            reasons.append(f"candidate_frame_{frame_index}_joints_missing")
            return None
        row = []
        for name in names:
            if name not in joints:
                reasons.append(f"candidate_joint_missing:{name}")
                return None
            row.append(joints[name])
        rows.append(row)
    try:
        points = np.asarray(rows, dtype=float)
    except (TypeError, ValueError):
        reasons.append("candidate_joints_malformed")
        return None
    if points.shape != (len(frames), len(names), 3):
        reasons.append("candidate_joints_shape_mismatch")
        return None
    if not np.isfinite(points).all():
        reasons.append("candidate_joints_nonfinite")
        return None
    return points


def _float_array(
    value: Any, shape: tuple[int, ...], label: str, reasons: list[str]
) -> Any | None:
    np = _numpy()
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        reasons.append(f"{label}_malformed")
        return None
    if array.shape != shape:
        reasons.append(f"{label}_shape_mismatch")
        return None
    if not np.isfinite(array).all():
        reasons.append(f"{label}_nonfinite")
        return None
    return array


def _bool_mask(
    value: Any, shape: tuple[int, int], label: str, reasons: list[str]
) -> Any | None:
    np = _numpy()
    if not isinstance(value, list) or len(value) != shape[0]:
        reasons.append(f"{label}_malformed")
        return None
    for row in value:
        if not isinstance(row, list) or len(row) != shape[1]:
            reasons.append(f"{label}_malformed")
            return None
        if any(not isinstance(entry, bool) for entry in row):
            reasons.append(f"{label}_not_boolean")
            return None
    return np.asarray(value, dtype=bool)


def _validate_context_association(
    candidate: dict[str, Any],
    context: Any,
    *,
    helper: Any | None,
    helper_error: str | None,
) -> tuple[list[str], str]:
    """Keep context validation with its capture/schema owner."""
    basis = "fit_context.validate_fit_context"
    if helper is None or helper_error:
        return [helper_error or "fit_context_helper_unavailable"], "unavailable"
    try:
        validation = helper.validate_fit_context(candidate, context)
    except Exception as exc:
        return [f"fit_context_validator_error: {type(exc).__name__}: {exc}"], basis
    if not isinstance(validation, dict):
        return ["fit_context_validator_result_invalid"], basis
    if validation.get("passed") is True:
        return [], basis
    return list(validation.get("reasons") or ["fit_context_validator_rejected"]), basis


def _third_difference_rms(points: Any) -> float:
    np = _numpy()
    return float(np.sqrt(np.mean(np.diff(points, n=3, axis=0) ** 2)))


def _jerk_screen(
    points: Any,
    reference: Any,
    *,
    limit: float,
) -> dict[str, Any]:
    candidate_rms = _third_difference_rms(points)
    reference_rms = _third_difference_rms(reference)
    passed = candidate_rms <= limit
    return {
        "available": True,
        "passed": passed,
        "status": "passed" if passed else "failed",
        "candidateRms": candidate_rms,
        "referenceRms": reference_rms,
        "limitRms": float(limit),
        "basis": "discrete_third_difference_rms",
    }


def _keyframe_contact_screen(
    points: Any,
    pinned: Any,
    targets: Any,
    *,
    limit: float,
) -> dict[str, Any]:
    np = _numpy()
    if not bool(pinned.any()):
        return {
            "available": False,
            "passed": None,
            "status": "unavailable",
            "reason": "no_keyframe_contact_pins",
            "pinnedCount": 0,
        }
    error = float(np.max(np.linalg.norm((points - targets)[pinned], axis=-1)))
    passed = error < limit
    return {
        "available": True,
        "passed": passed,
        "status": "passed" if passed else "failed",
        "maximumErrorMeters": error,
        "limitMeters": float(limit),
        "pinnedCount": int(pinned.sum()),
        "basis": "keyframe_contact_error",
    }


def _height_only_contact_screen(
    points: Any,
    pinned: Any,
    targets: Any,
    *,
    limit: float,
) -> dict[str, Any]:
    """Compare only the vertical gate; horizontal motion stays unconstrained."""
    np = _numpy()
    if not bool(pinned.any()):
        return {
            "available": False,
            "passed": None,
            "status": "not_applicable",
            "reason": "no_height_only_contact_frames",
            "pinnedCount": 0,
        }
    vertical_error = np.abs(points[:, :, 1][pinned] - targets[pinned])
    error = float(np.max(vertical_error))
    passed = error <= limit
    return {
        "available": True,
        "passed": passed,
        "status": "passed" if passed else "failed",
        "maximumErrorMeters": error,
        "limitMeters": float(limit),
        "pinnedCount": int(pinned.sum()),
        "axis": "floor_normal_y",
        "basis": "height_only_contact_error",
    }


def _native_material_contact_screen(
    context: dict[str, Any],
) -> dict[str, Any]:
    """Report native material contact as unavailable without a real sampler.

    The candidate stores integer keyframe joints. Production samples actual
    matching subframe rig positions before evaluating native material
    residuals. Shifting integer keyframes by half a frame is not that sample
    and can fabricate contact failures, so no cheap physical check is claimed
    here. Full production validation remains required.
    """
    np = _numpy()
    tracks = context.get("nativeFootMaterialTracks")
    if tracks is None:
        return {
            "available": False,
            "passed": None,
            "status": "not_applicable",
            "reason": "native_material_tracks_absent",
        }
    if not isinstance(tracks, dict) or tracks.get("version") != 2:
        return {
            "available": False,
            "passed": None,
            "status": "unavailable",
            "reason": "native_material_tracks_malformed",
        }
    try:
        active = any(
            bool(np.any(np.asarray((tracks.get(side) or {}).get("active") or (),
                                   dtype=bool)))
            for side in ("left", "right")
        )
    except (TypeError, ValueError):
        active = True
    if not active:
        return {
            "available": False,
            "passed": None,
            "status": "not_applicable",
            "reason": "no_active_native_material_tracks",
        }
    return {
        "available": False,
        "passed": None,
        "status": "unavailable",
        "reason": "native_material_subframe_samples_unavailable",
        "note": (
            "Integer keyframe joints cannot stand in for production subframe "
            "rig samples; full validation owns this physical gate."
        ),
    }


def screen_candidate_payload(
    candidate: dict[str, Any],
    *,
    context: dict[str, Any],
    context_source: str = "in_memory",
    candidate_identity: dict[str, Any] | None = None,
    context_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cheaply reject or triage one actual candidate. Never accepts or publishes."""
    candidate = _require_dict(candidate, "candidate")
    helper, helper_error = _fit_context_helper()
    try:
        candidate_pose_digest = current_pose_digest(candidate)
    except Exception as exc:
        raise ReplayError(
            f"cannot compute candidate pose digest: {type(exc).__name__}: {exc}"
        ) from exc
    context_reasons, validator = _validate_context_association(
        candidate,
        context,
        helper=helper,
        helper_error=helper_error,
    )

    frames = candidate.get("frames") or []
    names = candidate.get("jointNames") or []
    count = len(frames)
    try:
        fps = float(candidate.get("fps"))
    except (TypeError, ValueError, OverflowError):
        fps = None
    candidate_summary = {
        "candidatePoseDigest": candidate_pose_digest,
        "candidatePayloadDigest": canonical_digest(candidate),
        "frameCount": count,
        "jointCount": len(names) if isinstance(names, list) else None,
        "fps": fps if fps is not None and math.isfinite(fps) else None,
    }
    candidate_summary.update(candidate_identity or {})
    context_summary = {
        "source": context_source,
        "validator": validator,
    }
    if isinstance(context, dict):
        for key in (
            "contextOrigin",
            "stage",
            "contextDigest",
            "candidatePoseDigest",
            "frameCount",
            "fps",
        ):
            context_summary[key] = context.get(key)
    context_summary.update(context_identity or {})

    checks: dict[str, Any] = {
        "context": {
            "available": True,
            "passed": not context_reasons,
            "status": "passed" if not context_reasons else "failed",
            "reasons": context_reasons,
        }
    }
    failures: list[str] = list(context_reasons)
    unavailable: list[str] = []
    if context_reasons:
        checks["jerk"] = {"available": False, "passed": None, "status": "not_run"}
        checks["contact"] = {
            "available": False,
            "passed": None,
            "status": "not_run",
            "reason": "context_unavailable",
        }
        status = SCREEN_STATUS_CONTEXT_UNAVAILABLE
    else:
        reasons: list[str] = []
        points = _candidate_points(candidate, list(names), reasons=reasons)
        reference = _float_array(
            context.get("temporalReferenceJoints"),
            (count, len(names), 3),
            "temporalReferenceJoints",
            reasons,
        )
        hard_pinned = None
        hard_targets = None
        if context.get("jointContactPinned") is not None:
            hard_pinned = _bool_mask(
                context.get("jointContactPinned"),
                (count, len(names)),
                "jointContactPinned",
                reasons,
            )
        if context.get("jointContactTargets") is not None:
            hard_targets = _float_array(
                context.get("jointContactTargets"),
                (count, len(names), 3),
                "jointContactTargets",
                reasons,
            )
        height_pinned = None
        height_targets = None
        height_limit = None
        if context.get("heightContactPinned") is not None:
            height_pinned = _bool_mask(
                context.get("heightContactPinned"),
                (count, len(names)),
                "heightContactPinned",
                reasons,
            )
        if context.get("heightContactTargets") is not None:
            height_targets = _float_array(
                context.get("heightContactTargets"),
                (count, len(names)),
                "heightContactTargets",
                reasons,
            )
        if context.get("heightContactLimitMeters") is not None:
            try:
                height_limit = float(context.get("heightContactLimitMeters"))
            except (TypeError, ValueError, OverflowError):
                reasons.append("heightContactLimitMeters_malformed")
            else:
                if not math.isfinite(height_limit) or height_limit <= 0.0:
                    reasons.append("heightContactLimitMeters_invalid")
        if reasons:
            checks["jerk"] = {
                "available": False,
                "passed": None,
                "status": "unavailable",
                "reasons": reasons,
            }
            checks["contact"] = {
                "available": False,
                "passed": None,
                "status": "unavailable",
                "reason": "context_arrays_unavailable",
            }
            failures.extend(reasons)
            status = SCREEN_STATUS_CONTEXT_UNAVAILABLE
        else:
            jerk = _jerk_screen(
                points, reference, limit=float(context["jerkLimit"])
            )
            checks["jerk"] = jerk
            if jerk["status"] == "failed":
                failures.append("jerk_rms_exceeds_limit")

            if hard_pinned is None and hard_targets is None:
                keyframe_contact = {
                    "available": False,
                    "passed": None,
                    "status": "unavailable",
                    "reason": "hard_joint_contact_mask_unavailable",
                }
            elif hard_pinned is None:
                keyframe_contact = {
                    "available": False,
                    "passed": None,
                    "status": "unavailable",
                    "reason": "hard_joint_contact_pins_missing",
                }
            elif hard_targets is None:
                keyframe_contact = {
                    "available": False,
                    "passed": None,
                    "status": "unavailable",
                    "reason": "hard_joint_contact_targets_missing",
                }
            else:
                keyframe_contact = _keyframe_contact_screen(
                    points,
                    hard_pinned,
                    hard_targets,
                    limit=float(context["contactLimitMeters"]),
                )
            if height_pinned is None and height_targets is None:
                height_contact = {
                    "available": False,
                    "passed": None,
                    "status": "unavailable",
                    "reason": "height_only_contact_fields_unavailable",
                }
            elif height_pinned is None:
                height_contact = {
                    "available": False,
                    "passed": None,
                    "status": "unavailable",
                    "reason": "height_only_contact_pins_missing",
                }
            elif height_targets is None:
                height_contact = {
                    "available": False,
                    "passed": None,
                    "status": "unavailable",
                    "reason": "height_only_contact_targets_missing",
                }
            elif height_limit is None:
                height_contact = {
                    "available": False,
                    "passed": None,
                    "status": "unavailable",
                    "reason": "height_only_contact_limit_unavailable",
                }
            else:
                height_contact = _height_only_contact_screen(
                    points,
                    height_pinned,
                    height_targets,
                    limit=height_limit,
                )
            # Native material support is its own physical gate. It stays
            # separately visible and is never hidden by joint pins.
            native_contact = _native_material_contact_screen(context)
            contact_components = {
                "keyframe": keyframe_contact,
                "heightOnly": height_contact,
                "nativeMaterial": native_contact,
            }
            available_components = {
                name: result
                for name, result in contact_components.items()
                if result.get("available") is True
            }
            failed_components = {
                name: result
                for name, result in available_components.items()
                if result.get("passed") is False
            }
            pending_components = {
                name: result
                for name, result in contact_components.items()
                if result.get("available") is not True
                and result.get("status") != "not_applicable"
            }
            if failed_components:
                contact_passed = False
                contact_status = "failed"
                if "keyframe" in failed_components or "nativeMaterial" in failed_components:
                    failures.append("contact_error_exceeds_limit")
                if "heightOnly" in failed_components:
                    failures.append("height_only_contact_error_exceeds_limit")
            elif available_components and not pending_components:
                contact_passed = True
                contact_status = "passed"
            else:
                contact_status = "unavailable"
                contact_passed = None
                unavailable.append("contact")
            checks["contact"] = {
                "available": bool(available_components),
                "passed": contact_passed,
                "status": contact_status,
                "components": contact_components,
                "unavailableReason": (
                    None
                    if available_components and not pending_components
                    else "physical_contact_check_incomplete"
                ),
            }
            status = (
                SCREEN_STATUS_KNOWN_FAILED
                if failures
                else SCREEN_STATUS_ELIGIBLE
            )

    if not checks["jerk"].get("available") and checks["jerk"].get("status") != "not_run":
        unavailable.append("jerk")
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": SCREEN_KIND,
        "screenedAtUtc": utc_now(),
        "status": status,
        "candidate": candidate_summary,
        "context": context_summary,
        "checks": checks,
        "failures": list(dict.fromkeys(failures)),
        "unavailableChecks": list(dict.fromkeys(unavailable)),
        "eligibility": {
            "contextAvailable": status != SCREEN_STATUS_CONTEXT_UNAVAILABLE,
            "eligibleForFullValidation": status == SCREEN_STATUS_ELIGIBLE,
            "fullValidationRequiredBeforeAcceptance": True,
            "fullValidationRecommended": status == SCREEN_STATUS_ELIGIBLE,
            "canAcceptOrPublish": False,
            "screeningOnly": True,
        },
        "fullValidationPerformed": False,
        "acceptance": {
            "movementAccepted": False,
            "published": False,
            "note": (
                "Screening only rejects or triages. Complete production validation "
                "remains mandatory for any eligible candidate."
            ),
        },
    }
    return report


def screen_candidate_file(
    *,
    candidate_path: str | Path,
    context_path: str | Path | None = None,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """Screen one exact candidate/diagnostic path; no wildcard or latest lookup."""
    candidate_path = _resolve(candidate_path)
    if not candidate_path.is_file():
        raise ReplayError(f"candidate/diagnostic does not exist: {candidate_path}")
    document = _read_json(candidate_path)
    candidate = _candidate_payload_from_document(document)
    actual_pose_digest = current_pose_digest(candidate)
    if isinstance(document, dict):
        recorded_pose_digest = document.get("candidatePoseDigest")
        if recorded_pose_digest is not None and recorded_pose_digest != actual_pose_digest:
            raise ReplayError("candidate document pose digest is stale")
        recorded_payload_digest = document.get("candidatePayloadDigest")
        if (
            recorded_payload_digest is not None
            and recorded_payload_digest != canonical_digest(candidate)
        ):
            raise ReplayError("candidate document payload digest is stale")

    if context_path is not None:
        context_file = _resolve(context_path)
        if not context_file.is_file():
            raise ReplayError(f"explicit fit context does not exist: {context_file}")
        context = _require_dict(_read_json(context_file), "fit context")
        context_source = "explicit_file"
        context_identity = {
            "path": str(context_file),
            "sha256": file_sha256(context_file),
        }
    else:
        context, context_source = _captured_context_from_document(document)
        if context is None:
            raise ReplayError(
                "candidate/diagnostic has no captured fitContext; refusing to infer "
                "constraints from an embedded controlledMotionFit report"
            )
        context_identity = {"path": str(candidate_path)}

    report = screen_candidate_payload(
        candidate,
        context=context,
        context_source=context_source,
        candidate_identity={
            "path": str(candidate_path),
            "sha256": file_sha256(candidate_path),
        },
        context_identity=context_identity,
    )
    if output is not None:
        path = _resolve(output)
        _write_new_json(path, report)
        report["outputPath"] = str(path)
    return report


def screen_skips_full_validation(report: dict[str, Any]) -> bool:
    """True only for a completed known cheap failure or an unavailable context."""
    return (
        isinstance(report, dict)
        and report.get("status")
        in (SCREEN_STATUS_KNOWN_FAILED, SCREEN_STATUS_CONTEXT_UNAVAILABLE)
    )


def screen_requires_full_validation(report: dict[str, Any]) -> bool:
    """Full production validation remains mandatory for every eligible candidate."""
    return (
        isinstance(report, dict)
        and report.get("status") == SCREEN_STATUS_ELIGIBLE
        and (report.get("eligibility") or {}).get("eligibleForFullValidation") is True
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seal/preflight/replay one exact controlled-motion fit input."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    seal_parser = subparsers.add_parser("seal", help="seal one exact named receipt")
    seal_parser.add_argument("--receipt", required=True)
    seal_parser.add_argument("--receipt-sha256", required=True)
    seal_parser.add_argument("--variant", required=True)
    seal_parser.add_argument("--payload-digest", required=True)
    seal_parser.add_argument("--proof", required=True, help="actual normal preflight proof")
    seal_parser.add_argument("--output", required=True, help="new bundle path or directory")
    seal_parser.add_argument(
        "--dependency",
        action="append",
        default=[],
        help="extra dependency as ROLE=PATH or ROLE=PATH=SHA256",
    )
    seal_parser.add_argument(
        "--code-file",
        action="append",
        default=[],
        help="extra code file to fingerprint",
    )

    preflight_parser = subparsers.add_parser(
        "preflight", help="validate one sealed bundle without calling the fitter"
    )
    preflight_parser.add_argument("--bundle", required=True)
    preflight_parser.add_argument("--bundle-sha256", required=True)
    preflight_parser.add_argument("--output")

    run_parser = subparsers.add_parser("run", help="run one sealed bundle")
    run_parser.add_argument("--bundle", required=True)
    run_parser.add_argument("--bundle-sha256", required=True)
    run_parser.add_argument("--output-dir", required=True)
    run_parser.add_argument("--timeout-seconds", type=float)
    run_parser.add_argument("--max-evaluations", type=int)

    screen_parser = subparsers.add_parser(
        "screen",
        help="cheaply reject or triage one exact candidate/diagnostic",
    )
    screen_parser.add_argument(
        "--candidate",
        required=True,
        help="exact candidate payload or rejected-fit diagnostic JSON",
    )
    screen_parser.add_argument(
        "--context",
        help="optional explicit captured fitContext JSON file",
    )
    screen_parser.add_argument("--output", help="new screen report path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "seal":
            summary = seal_input(
                receipt_path=args.receipt,
                receipt_sha256=args.receipt_sha256,
                variant_identity=args.variant,
                payload_digest=args.payload_digest,
                proof_path=args.proof,
                output=args.output,
                extra_dependencies=args.dependency,
                extra_code_files=args.code_file,
            )
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0
        if args.command == "preflight":
            summary = preflight_bundle(
                bundle_path=args.bundle,
                bundle_sha256=args.bundle_sha256,
                output=args.output,
            )
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0
        if args.command == "run":
            run_bundle(
                bundle_path=args.bundle,
                bundle_sha256=args.bundle_sha256,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout_seconds,
                max_evaluations=args.max_evaluations,
            )
            return 0
        if args.command == "screen":
            summary = screen_candidate_file(
                candidate_path=args.candidate,
                context_path=args.context,
                output=args.output,
            )
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0
        raise ReplayError(f"unknown command: {args.command}")
    except ReplayError as exc:
        print(f"replay error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
