from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest



def _fixture(tmp_path):
    from exercise_motion_pkg.body_support_observation import POLICY_VERSION
    from exercise_motion_pkg.source_frame_clock import (
        build_source_frame_clock,
        source_frame_clock_path_for_video,
        write_source_frame_clock,
    )

    workspace = tmp_path / "workspace"
    video = workspace / "input" / "selected_segment.mp4"
    video.parent.mkdir(parents=True)
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10., (96, 64))
    assert writer.isOpened()
    for index in range(12):
        writer.write(np.full((64, 96, 3), index, dtype=np.uint8))
    writer.release()
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    clock = build_source_frame_clock(
        source_video_path=video, output_video_path=video,
        crop_start_seconds=0., crop_end_seconds=1.2, output_fps=10.)
    clock_path = source_frame_clock_path_for_video(video)
    write_source_frame_clock(clock, output_path=clock_path)

    pose_frames = []
    payload_frames = []
    for index in range(12):
        point = [0.45, 0.8]
        pose_frames.append({
            "sourceTimeSec": index / 10.,
            "joints": {
                "left_ankle": point,
                "left_heel": [0.44, 0.81],
                "left_toe": [0.47, 0.82],
            },
            "jointConfidence": {"left_ankle": 0.99},
        })
        payload_frames.append({
            "sourceTimeSec": index / 10.,
            "joints": {
                "left_ankle": [0., 0.1, 0.],
                "left_foot": [0., 0., 0.1],
            },
        })
    pose = {
        "coordinateSpace": "normalized_image_xy",
        "sourceTimeOriginSec": 0.,
        "frames": pose_frames,
    }
    evidence = {
        "sourceVideoSha256": digest,
        "contacts": [],
        "bodySupportObservation": {
            "status": "observed",
            "source": "exact_source_visual_support_observation",
            "sourceVideoSha256": digest,
            "policyVersion": POLICY_VERSION,
            "sourceClock": "video_frame_zero_seconds",
            "sourceTimeOriginSec": 0.,
            "observation": {
                "leftFoot": "stationary_forefoot",
                "leftFootSurface": "ground",
                "leftFootContactContinuity": "continuous",
                "rightFoot": "unknown",
                "rightFootSurface": "unknown",
            },
        },
        "footPatchEvidence": {
            "available": True,
            "sourceVideoSha256": digest,
            "sourceFrameCount": 12,
            "sourceFps": 10.,
            "sourceTimeBasis": "video_frame_zero_seconds",
            "sourceTimeOriginSec": 0.,
            "sourceTimesSec": [index / 10. for index in range(12)],
            "feet": {"left": {"states": ["unknown"] * 12}},
        },
    }
    reference_path = workspace / "segment_detection" / "exact_source_pose_reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"sourceVideoSha256": digest, "pose": pose}), encoding="utf-8")
    return video, digest, clock_path, pose, evidence, payload_frames


def _install_verified_pose_loader(monkeypatch, video, digest, pose):
    from exercise_motion_pkg import bake_and_rank

    reference_path = video.parent.parent / "segment_detection" / "exact_source_pose_reference.json"
    def load_verified(path, source_video_path):
        if Path(path).resolve() != reference_path.resolve() or Path(source_video_path).resolve() != video.resolve():
            return None
        if hashlib.sha256(video.read_bytes()).hexdigest() != digest:
            return None
        return {"sourceVideoSha256": digest, "pose": copy.deepcopy(pose)}
    monkeypatch.setattr(bake_and_rank, "load_verified_source_pose_reference", load_verified)


def _caption(**kwargs):
    sample_ids = sorted(
        set(kwargs["response_schema"]["properties"]) - {"heelMotion", "forefootMotion"},
        key=int,
    )
    labels = {sample_id: ("full_sole_ground" if int(sample_id) < 6 else "unresolved")
              for sample_id in sample_ids}
    return json.dumps({**labels, "heelMotion": "moving", "forefootMotion": "stationary"})


def _payload(evidence, frames):
    return {
        "jointNames": ["left_ankle", "left_foot"],
        "groundContactMode": "continuous",
        "frames": copy.deepcopy(frames),
        "sourceFootSupportEvidence": copy.deepcopy(evidence),
    }


def test_mixed_dense_review_keeps_only_clocked_forefoot_spans(tmp_path, monkeypatch):
    from exercise_motion_pkg.body_support_observation import (
        observe_stationary_sole_intervals,
        materialize_stationary_sole_support,
        validated_body_support_contact_timeline,
    )
    from exercise_motion_pkg.sequence_stabilization import contact_mask
    from exercise_motion_pkg.support_geometry import support_contact_readiness

    video, digest, clock_path, pose, evidence, frames = _fixture(tmp_path)
    _install_verified_pose_loader(monkeypatch, video, digest, pose)
    reference = {"sourceVideoSha256": digest, "pose": pose}
    review = observe_stationary_sole_intervals(
        video, reference, evidence, _caption, tmp_path / "reviews",
        ground_contact_mode="continuous",
    )
    assert review is not None
    assert review["feet"]["left"]["confirmed"] is False
    assert review["sourceFrameClockProof"]["receiptPath"] == str(clock_path.resolve())
    assert len(review["feet"]["left"]["frameObservations"]) == 12
    assert review["feet"]["left"]["frameObservations"][0]["sourcePoseFrameIndex"] == 0
    assert review["feet"]["left"]["frameObservations"][11]["sourcePoseFrameIndex"] == 11

    evidence["stationarySoleIntervalReview"] = review
    materialized = materialize_stationary_sole_support(_payload(evidence, frames))
    observed = materialized["bodySupportObservation"]
    rows = validated_body_support_contact_timeline(observed)
    assert rows is not None
    assert len(rows) == 6
    assert {row["contactState"] for row in rows} == {"forefoot"}
    assert all(row["sourceTrackStationary"] for row in rows)
    assert all(row["selectedSourceFrameIndex"] == row["sourceFrameIndex"] for row in rows)

    sample_payload = _payload(evidence, frames)
    pins = contact_mask(sample_payload, sample_payload["jointNames"], 12,
                        support_evidence=materialized)
    assert pins[:, 1].tolist() == [True] * 6 + [False] * 6
    readiness = support_contact_readiness(sample_payload, evidence=materialized)
    assert readiness["status"] == "incomplete"
    assert readiness["stationaryContactCoverage"]["left"] == {
        "coveredFrames": 6, "requiredFrames": 12,
    }
    assert readiness["rejectionReasons"] == ["source_support_contact_evidence_incomplete"]
    exact = [contact for contact in materialized.get("supportContacts", [])
             if contact.get("supportKind") == "exact_timed_visual_contact"]
    assert len(exact) == 6
    assert all(contact.get("_fitFrameBounds", [None])[0] in range(6) for contact in exact)
    assert not any(contact.get("supportKind") == "observed_source_stance_interval"
                   for contact in materialized.get("contacts", []))
    assert evidence["footPatchEvidence"]["feet"]["left"]["states"] == ["unknown"] * 12


def test_dense_review_rejects_wrong_clock_and_source_hash(tmp_path, monkeypatch):
    from exercise_motion_pkg.body_support_observation import (
        materialize_stationary_sole_support,
        observe_stationary_sole_intervals,
    )
    from exercise_motion_pkg.contact_constraints import motion_support_contacts

    video, digest, _, pose, evidence, frames = _fixture(tmp_path)
    _install_verified_pose_loader(monkeypatch, video, digest, pose)
    review = observe_stationary_sole_intervals(
        video, {"sourceVideoSha256": digest, "pose": pose}, evidence,
        _caption, tmp_path / "reviews", ground_contact_mode="continuous",
    )
    assert review is not None
    evidence["stationarySoleIntervalReview"] = review

    wrong_clock = copy.deepcopy(evidence)
    wrong_clock["stationarySoleIntervalReview"]["sourceFrameClockProof"]["receiptSha256"] = "0" * 64
    materialized = materialize_stationary_sole_support(_payload(wrong_clock, frames))
    assert not any(contact.get("supportKind") == "exact_timed_visual_contact"
                   for contact in motion_support_contacts(materialized))

    wrong_pose_receipt = copy.deepcopy(evidence)
    wrong_pose_receipt["stationarySoleIntervalReview"]["feet"]["left"][
        "sourcePoseTrackProof"]["sourcePoseTrackSha256"] = "0" * 64
    materialized = materialize_stationary_sole_support(_payload(wrong_pose_receipt, frames))
    assert not any(contact.get("supportKind") == "exact_timed_visual_contact"
                   for contact in motion_support_contacts(materialized))

    changed_pose = copy.deepcopy(pose)
    for index, frame in enumerate(changed_pose["frames"]):
        frame["joints"]["left_ankle"] = [0.45 + index * 0.01, 0.8]
    _install_verified_pose_loader(monkeypatch, video, digest, changed_pose)
    materialized = materialize_stationary_sole_support(_payload(evidence, frames))
    assert not any(contact.get("supportKind") == "exact_timed_visual_contact"
                   for contact in motion_support_contacts(materialized))

    _install_verified_pose_loader(monkeypatch, video, digest, pose)
    reference_path = video.parent.parent / "segment_detection" / "exact_source_pose_reference.json"
    reference_path.write_bytes(reference_path.read_bytes() + b" ")
    materialized = materialize_stationary_sole_support(_payload(evidence, frames))
    assert not any(contact.get("supportKind") == "exact_timed_visual_contact"
                   for contact in motion_support_contacts(materialized))

    wrong_sha = copy.deepcopy(evidence)
    wrong_sha["stationarySoleIntervalReview"]["sourceVideoSha256"] = "wrong-source"
    materialized = materialize_stationary_sole_support(_payload(wrong_sha, frames))
    assert not any(contact.get("supportKind") == "exact_timed_visual_contact"
                   for contact in motion_support_contacts(materialized))


def test_invalid_clock_and_malformed_fps_fail_closed(tmp_path, monkeypatch):
    from exercise_motion_pkg import source_frame_clock
    from exercise_motion_pkg.body_support_observation import (
        _source_frame_clock_proof,
        _dense_sole_review_timeline_rows,
    )

    video, digest, clock_path, _, evidence, _ = _fixture(tmp_path)
    original = clock_path.read_bytes()
    clock_path.write_text("{}", encoding="utf-8")
    assert _source_frame_clock_proof(video, digest, 12) == (None, None)
    clock_path.write_bytes(original)

    review = {"sourceVideoSha256": digest, "sourceFrameCount": 12,
              "sourceFrameClockProof": {"receiptPath": str(clock_path),
                                        "receiptSha256": hashlib.sha256(clock_path.read_bytes()).hexdigest(),
                                        "outputVideoPath": str(video), "outputVideoSha256": digest,
                                        "outputFrameCount": 12, "outputFps": "not-a-number"},
              "feet": {}}
    evidence["stationarySoleIntervalReview"] = review
    assert _dense_sole_review_timeline_rows(evidence, {"frames": []}, review) == []


def test_nonzero_pose_origin_maps_to_selected_cut_frames(tmp_path, monkeypatch):
    from exercise_motion_pkg.body_support_observation import (
        observe_stationary_sole_intervals,
        materialize_stationary_sole_support,
        validated_body_support_contact_timeline,
    )

    video, digest, _, pose, evidence, frames = _fixture(tmp_path)
    pose["sourceTimeOriginSec"] = 5.0
    for index, frame in enumerate(pose["frames"]):
        frame["sourceTimeSec"] = 5.0 + index / 10.
    evidence["footPatchEvidence"]["sourceTimeOriginSec"] = 5.0
    evidence["footPatchEvidence"]["sourceTimesSec"] = [5.0 + index / 10. for index in range(12)]
    reference_path = video.parent.parent / "segment_detection" / "exact_source_pose_reference.json"
    reference_path.write_text(json.dumps({"sourceVideoSha256": digest, "pose": pose}), encoding="utf-8")
    _install_verified_pose_loader(monkeypatch, video, digest, pose)
    review = observe_stationary_sole_intervals(
        video, {"sourceVideoSha256": digest, "pose": pose}, evidence,
        _caption, tmp_path / "reviews", ground_contact_mode="continuous",
    )
    assert review is not None
    assert review["feet"]["left"]["frameObservations"][6]["sourceTimeSec"] == pytest.approx(.6)
    evidence["stationarySoleIntervalReview"] = review
    materialized = materialize_stationary_sole_support(_payload(evidence, frames))
    rows = validated_body_support_contact_timeline(materialized["bodySupportObservation"])
    assert rows is not None and len(rows) == 6
    assert [row["sourceTimeSec"] for row in rows] == pytest.approx([i / 10. for i in range(6)])
