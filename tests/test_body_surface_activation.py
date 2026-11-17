"""Focused regressions for bounded source-bound inferred activation contracts."""

from copy import deepcopy
import hashlib

import pytest

from exercise_motion_pkg.body_surface_activation import (
    build_inferred_activation,
    verify_inferred_activation,
)
from exercise_motion_pkg.body_surface_contacts import normalize_body_surface_contact
from exercise_motion_pkg.pose_fidelity import _canonical_source_pose_sha256
from exercise_motion_pkg.source_frame_clock import (
    build_source_frame_clock,
    source_frame_clock_path_for_video,
    write_source_frame_clock,
)
from nonfoot_support_fixture import FPS, build_nonfoot_support_fixture


def _case(tmp_path, *, moving=False):
    positions = ({"left_ankle": lambda index: [.2 + .05 * index, .8]}
                 if moving else None)
    video, _, pose_reference, payload = build_nonfoot_support_fixture(
        tmp_path, frame_count=12, sample_frames=(0, 6),
        joint_positions=positions)
    observed = payload["sourceFootSupportEvidence"]["bodySupportObservation"]
    clock_path = write_source_frame_clock(
        build_source_frame_clock(
            source_video_path=video, output_video_path=video,
            crop_start_seconds=0.0, output_fps=FPS),
        output_path=source_frame_clock_path_for_video(video))
    activation = build_inferred_activation(
        observed, "left_ankle", source_video_path=video)
    return video, pose_reference, observed, activation, clock_path


def _record(video, pose_reference, observed, activation, clock_path):
    rows = observed["contactTimeline"]["samples"]
    return {
        "schemaVersion": 1,
        "contactId": "left-ankle-fixed-bar",
        "bodyRegion": {"name": "ankle", "side": "left"},
        "contactMode": "stationary",
        "sourceEvidence": {
            "sourceVideoSha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            "sourcePosePayloadSha256": _canonical_source_pose_sha256(pose_reference),
            "sourceFrameClockReceiptSha256": hashlib.sha256(
                clock_path.read_bytes()).hexdigest(),
            "observations": [{
                "sampleId": row["sampleId"],
                "sourceTimeSec": row["sourceTimeSec"],
                "sourcePoseFrameIndex": row["sourcePoseFrameIndex"],
                "sourceFrameIndex": row["sourceFrameIndex"],
                "sourceFps": row["sourceFps"],
                "contactState": row["contactState"],
                "visible": row["visible"],
                "surfaceId": row["surface"],
            } for row in rows],
            **({"inferredActivation": deepcopy(activation)} if activation else {}),
        },
        "patchBinding": None,
        "surfaceEstimate": None,
        "geometryProvenance": None,
    }


def test_two_direct_rows_infer_bounded_interval_without_fabricating_observations(tmp_path):
    video, pose_reference, observed, activation, clock_path = _case(tmp_path)
    assert activation["kind"] == "stationary_source_track_between_direct_contacts"
    assert (activation["startSourcePoseFrameIndex"],
            activation["endSourcePoseFrameIndex"]) == (0, 6)
    assert activation["sourceSampleIds"] == ["left-ankle-0", "left-ankle-6"]
    assert len(activation["trackProofSha256"]) == 64

    record = _record(video, pose_reference, observed, activation, clock_path)
    normalized = normalize_body_surface_contact(record)
    assert normalized["sourceEvidence"]["observations"] == record["sourceEvidence"]["observations"]
    assert len(normalized["sourceEvidence"]["observations"]) == 2
    assert normalized["sourceEvidence"]["inferredActivation"] == activation
    assert verify_inferred_activation(
        record, observed, source_video_path=video,
        source_pose_reference=pose_reference)


def test_nonstationary_track_or_unclaimed_joint_never_builds_activation(tmp_path):
    video, _, observed, activation, _ = _case(tmp_path, moving=True)
    assert activation is None
    assert build_inferred_activation(observed, "left_knee", source_video_path=video) is None


def test_explicit_release_inside_interval_fails_closed(tmp_path):
    video, pose_reference, observed, activation, clock_path = _case(tmp_path)
    record = _record(video, pose_reference, observed, activation, clock_path)
    released = deepcopy(observed)
    released["contactTimeline"]["samples"].append({
        **deepcopy(released["contactTimeline"]["samples"][0]),
        "sampleId": "left-ankle-3", "sourceTimeSec": 0.3, "sourceFrameIndex": 3,
        "sourcePoseFrameIndex": 3, "contactState": "no_contact", "visible": False,
    })
    assert build_inferred_activation(
        released, "left_ankle", source_video_path=video) is None
    assert not verify_inferred_activation(
        record, released, source_video_path=video,
        source_pose_reference=pose_reference)


def test_normalizer_refuses_release_bounds_and_id_tampering(tmp_path):
    video, pose_reference, observed, activation, clock_path = _case(tmp_path)
    record = _record(video, pose_reference, observed, activation, clock_path)
    released = deepcopy(record)
    released["sourceEvidence"]["observations"][0]["contactState"] = "no_contact"
    with pytest.raises(ValueError, match="direct-contact observations"):
        normalize_body_surface_contact(released)
    out_of_bounds = deepcopy(record)
    out_of_bounds["sourceEvidence"]["inferredActivation"]["endSourcePoseFrameIndex"] = 7
    with pytest.raises(ValueError, match="source pose bounds"):
        normalize_body_surface_contact(out_of_bounds)
    swapped = deepcopy(record)
    swapped["sourceEvidence"]["inferredActivation"]["sourceSampleIds"] = [
        "left-ankle-0", "not-a-row"]
    with pytest.raises(ValueError, match="direct-contact observations"):
        normalize_body_surface_contact(swapped)


def test_verifier_refuses_stale_hash_tampered_proof_and_source(tmp_path):
    video, pose_reference, observed, activation, clock_path = _case(tmp_path)
    record = _record(video, pose_reference, observed, activation, clock_path)
    stale_proof = deepcopy(record)
    stale_proof["sourceEvidence"]["inferredActivation"]["trackProofSha256"] = "0" * 64
    assert not verify_inferred_activation(
        stale_proof, observed, source_video_path=video,
        source_pose_reference=pose_reference)
    stale_pose = deepcopy(record)
    stale_pose["sourceEvidence"]["sourcePosePayloadSha256"] = "0" * 64
    assert not verify_inferred_activation(
        stale_pose, observed, source_video_path=video,
        source_pose_reference=pose_reference)
    tampered_rows = deepcopy(record)
    tampered_rows["sourceEvidence"]["observations"][1]["sourceFrameIndex"] = 11
    assert not verify_inferred_activation(
        tampered_rows, observed, source_video_path=video,
        source_pose_reference=pose_reference)


def test_generic_record_without_inference_is_unchanged(tmp_path):
    video, pose_reference, observed, activation, clock_path = _case(tmp_path)
    record = _record(video, pose_reference, observed, activation, clock_path)
    record["sourceEvidence"].pop("inferredActivation")
    assert normalize_body_surface_contact(record) == record
    assert verify_inferred_activation(
        record, observed, source_video_path=video,
        source_pose_reference=pose_reference)
