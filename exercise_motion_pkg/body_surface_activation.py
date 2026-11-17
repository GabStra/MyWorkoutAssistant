"""Infer a bounded support interval from a stationary source track.

An inferred activation is not an observation: only the two boundary rows are
direct contacts, and the frames between them are admitted only because the
canonical source pose track is stationary there. Material joint stationarity
supports an inferred episode, never a fixed material point or contactMode.
"""

from __future__ import annotations

import hashlib
import json

from .body_support_observation import (
    _nonfoot_support_receipts, _verified_source_pose_track_proof,
    stationary_source_track, validated_body_support_answer,
    validated_body_support_contact_timeline,
)
from .body_surface_contacts import INFERRED_ACTIVATION_KINDS

INFERRED_ACTIVATION_KIND = INFERRED_ACTIVATION_KINDS[0]
_JOINT_FIELDS = {"ankle": ("Ankle", "AnkleContactSurface"),
                 "knee": ("Knee", "KneeContactSurface"),
                 "hand": ("Hand", "HandContactSurface"),
                 "wrist": ("Hand", "HandContactSurface")}


def _canonical_sha256(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _joint_claim(joint_name):
    side, _, suffix = joint_name.partition("_")
    fields = _JOINT_FIELDS.get(suffix)
    return (None if side not in ("left", "right") or fields is None
            else (side, f"{side}{fields[0]}", f"{side}{fields[1]}"))


def _as_pose(reference):
    return (reference.get("pose")
            if isinstance(reference, dict) and isinstance(reference.get("pose"), dict)
            else reference or {})


def _track_proof_sha256(proof, pose, joint_name, start, end, sample_ids):
    return _canonical_sha256({
        "sourceVideoSha256": proof.get("sourceVideoSha256"),
        "sourcePoseReferenceSha256": proof.get("sourcePoseReferenceSha256"),
        "sourcePoseTrackSha256": proof.get("sourcePoseTrackSha256"),
        "sourcePoseFrameCount": proof.get("sourcePoseFrameCount"),
        "jointName": joint_name,
        "stationarySourceTrack": stationary_source_track(pose, joint_name),
        "startSourcePoseFrameIndex": start,
        "endSourcePoseFrameIndex": end,
        "sourceSampleIds": list(sample_ids)})


def _interval_has_no_release(observed, joint_name, start, end):
    return not any(
        row.get("jointName") == joint_name and type(row.get("sourcePoseFrameIndex")) is int
        and start <= row["sourcePoseFrameIndex"] <= end
        and (row.get("contactState") != "direct_contact" or row.get("visible") is not True)
        for row in validated_body_support_contact_timeline(observed) or [])


def build_inferred_activation(observed, joint_name, *, source_video_path):
    """Return a verified activation dict, or None when evidence cannot support one."""
    claim = _joint_claim(joint_name)
    digest = (observed or {}).get("sourceVideoSha256")
    if claim is None or not digest or not source_video_path:
        return None
    side, state_field, surface_field = claim
    answer = validated_body_support_answer(observed) or {}
    surface = answer.get(surface_field)
    if answer.get(state_field) != "stationary_support" or not surface:
        return None
    proof, reference = _verified_source_pose_track_proof(source_video_path, side, digest)
    if proof is None or proof.get("sourceVideoSha256") != digest:
        return None
    pose = _as_pose(reference)
    if not stationary_source_track(pose, joint_name):
        return None
    receipts = _nonfoot_support_receipts(
        observed, pose, joint_name, surface, source_video_path, proof)
    if not isinstance(receipts, list) or len(receipts) != 2:
        return None
    rows = sorted(receipts, key=lambda receipt: (
        receipt["row"]["sourcePoseFrameIndex"], receipt["rowId"]))
    sample_ids = [receipt["rowId"] for receipt in rows]
    start, end = rows[0]["row"]["sourcePoseFrameIndex"], rows[-1]["row"]["sourcePoseFrameIndex"]
    if (len(set(sample_ids)) != 2 or end <= start
            or not _interval_has_no_release(observed, joint_name, start, end)):
        return None
    return {"kind": INFERRED_ACTIVATION_KIND, "jointName": joint_name,
            "startSourcePoseFrameIndex": start, "endSourcePoseFrameIndex": end,
            "sourceSampleIds": sample_ids,
            "trackProofSha256": _track_proof_sha256(
                proof, pose, joint_name, start, end, sample_ids)}


def verify_inferred_activation(contact_record, observed, *, source_video_path,
                               source_pose_reference=None):
    """Recompute activation identity against canonical source, pose, clock and rows."""
    from .body_surface_evidence import _reopen_source_identity

    try:
        contact, video, video_sha, _, _, reference, _, _ = _reopen_source_identity(
            contact_record, source_video_path, source_pose_reference)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False
    source = contact["sourceEvidence"]
    if "inferredActivation" not in source:
        return True
    activation = source["inferredActivation"]
    claim = _joint_claim(activation["jointName"])
    answer = validated_body_support_answer(observed) or {}
    observations = sorted(source["observations"], key=lambda row: row["sampleId"])
    if claim is None:
        return False
    side, state_field, surface_field = claim
    surface = answer.get(surface_field)
    start, end = (activation["startSourcePoseFrameIndex"],
                  activation["endSourcePoseFrameIndex"])
    if (answer.get(state_field) != "stationary_support" or not surface
            or len(observations) != 2
            or sorted(activation["sourceSampleIds"]) != [row["sampleId"] for row in observations]
            or any(row["contactState"] != "direct_contact" or row["visible"] is not True
                   or row["surfaceId"] != surface for row in observations)
            or sorted(row["sourcePoseFrameIndex"] for row in observations) != [start, end]
            or not stationary_source_track(_as_pose(reference), activation["jointName"])
            or not _interval_has_no_release(observed, activation["jointName"], start, end)):
        return False
    proof, reopened = _verified_source_pose_track_proof(video, side, video_sha)
    if proof is None or proof.get("sourceVideoSha256") != video_sha:
        return False
    reopened = _as_pose(reopened)
    receipts = _nonfoot_support_receipts(
        observed, reopened, activation["jointName"], surface, video, proof)
    return (isinstance(receipts, list) and len(receipts) == 2
            and sorted(receipt["rowId"] for receipt in receipts)
            == sorted(activation["sourceSampleIds"])
            and _track_proof_sha256(
                proof, reopened, activation["jointName"], start, end,
                activation["sourceSampleIds"]) == activation["trackProofSha256"])


__all__ = ["INFERRED_ACTIVATION_KIND", "build_inferred_activation",
           "verify_inferred_activation"]
