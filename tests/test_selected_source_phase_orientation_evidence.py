import math

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.pose_fidelity import _canonical_source_pose_sha256


def _cycle_inputs(with_mapping=True):
    video_sha = "a" * 64
    parent_sha = "b" * 64
    local_times = [index / 10 for index in range(31)]
    angles = [0.02 * math.sin(2.0 * math.pi * index / 15.0) for index in range(31)]
    source_pose = {
        "sourceVideoSha256": video_sha,
        "sourceTimeOriginSec": 0.0,
        "jointNames": ["pelvis", "left_knee", "right_knee", "left_ankle", "right_ankle"],
        "rootJoint": "pelvis",
        "frames": [
            {"timeSec": time, "sourceTimeSec": time, "joints": {
                "pelvis": [0.0, 1.0, 0.0], "left_knee": [-0.1, 0.5, 0.0],
                "right_knee": [0.1, 0.5, 0.0], "left_ankle": [-0.1, 0.1, 0.0],
                "right_ankle": [0.1, 0.1, 0.0],
            }} for time in local_times
        ],
    }
    patch = {
        "available": True,
        "sourceVideoSha256": video_sha,
        "sourceTimeBasis": "absolute_source_video",
        "sourceTimeOriginSec": 0.0,
        "sourceTimesSec": local_times,
        "feet": {"right": {"rayObservations": [
            {"sourceTimeSec": time, "ankleToToeImageRay": [math.cos(angle), math.sin(angle)],
             "confidence": 0.95}
            for time, angle in zip(local_times, angles)
        ]}},
    }
    evidence = {"sourceVideoSha256": video_sha, "footPatchEvidence": patch}
    motion = {
        "frames": [
            {"timeSec": time, "sourceTimeSec": time + 2.0, "joints": {}}
            for time in local_times
        ],
        "loop": {"enabled": True},
        "loopCycleSelection": {"startFrame": 0, "stopFrameExclusive": len(local_times)},
        "sourceFootSupportEvidence": evidence,
    }
    if with_mapping:
        mapping = {
            "schemaVersion": 1,
            "verified": True,
            "mappingKind": "selected_segment_to_parent_source",
            "selectedSegmentSha256": video_sha,
            "parentSourceSha256": parent_sha,
            "selectedFrameClockReceiptSha256": "c" * 64,
            "sourcePosePayloadSha256": _canonical_source_pose_sha256(source_pose),
            "selectedOutputFps": 10.0,
            "selectedFrameCount": len(local_times),
            "selectedFrameLineage": [
                {"selectedFrameIndex": index, "selectedFrameTimeSec": time,
                 "parentSourceFrameIndex": index + 100, "parentSourceTimeSec": time + 2.0}
                for index, time in enumerate(local_times)
            ],
        }
        motion["sourcePoseCameraReference"] = {"sourceTimelineMapping": mapping}
    return source_pose, motion


def test_selected_interval_preflight_reuses_verified_mapped_foot_orientation(monkeypatch):
    source_pose, motion = _cycle_inputs()
    spec = {"primaryMovingRegions": ["feet"], "referenceRegions": ["knees"],
            "primaryAxis": "vertical", "motionPattern": "distal_limb_vertical"}

    def measure_source(frames, *, ranking_payload, foot_orientation_tracks=None, **_kwargs):
        track = bake.dominant_observable_motion_phase_track(
            frames, spec=spec, body_span=1.0, foot_orientation_tracks=foot_orientation_tracks,
        )
        return {"required": True, "passed": track is not None and bake.phase_track_has_return(track["values"]),
                "dominantJoint": track["joint"] if track else None,
                "dominantJointSelection": track["selection"] if track else None,
                "sampleCount": len(track["values"]) if track else 0}

    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_source_pose_payload",
                        measure_source)
    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_payload",
                        lambda *_args, **_kwargs: {"required": True, "passed": True})

    result = bake.selected_interval_source_phase_preflight(motion, source_pose, contract={})

    assert result["sourcePhase"]["passed"] is True
    assert result["sourcePhase"]["dominantJointSelection"] == "observable_source_foot_orientation"
    assert result["sourcePhaseFootOrientationEvidence"]["right"]["sampleCount"] == 31
    assert result["sourcePhaseFootOrientationEvidence"]["right"]["sourceTimeOriginSec"] == 2.0


def test_selected_interval_preflight_does_not_use_unmapped_cut_local_evidence(monkeypatch):
    source_pose, motion = _cycle_inputs(with_mapping=False)
    observed_tracks = []

    def fail_closed(frames, *, foot_orientation_tracks=None, **_kwargs):
        observed_tracks.append(foot_orientation_tracks)
        return {"required": True, "passed": bool(foot_orientation_tracks),
                "dominantJointSelection": "observable_source_foot_orientation"
                if foot_orientation_tracks else "observable_motion_spec_relative"}

    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_source_pose_payload",
                        fail_closed)
    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_payload",
                        lambda *_args, **_kwargs: {"required": True, "passed": True})

    result = bake.selected_interval_source_phase_preflight(motion, source_pose, contract={})

    assert observed_tracks == [{}]
    assert result["sourcePhase"]["passed"] is False
    assert result["sourcePhaseFootOrientationEvidence"] == {}


def test_selected_interval_preflight_rejects_malformed_frame_lineage(monkeypatch):
    source_pose, motion = _cycle_inputs()
    lineage = motion["sourcePoseCameraReference"]["sourceTimelineMapping"]["selectedFrameLineage"]
    lineage[12]["selectedFrameTimeSec"] += 0.01
    observed_tracks = []

    def fail_closed(_frames, *, foot_orientation_tracks=None, **_kwargs):
        observed_tracks.append(foot_orientation_tracks)
        return {"required": True, "passed": bool(foot_orientation_tracks)}

    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_source_pose_payload",
                        fail_closed)
    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_payload",
                        lambda *_args, **_kwargs: {"required": True, "passed": True})

    result = bake.selected_interval_source_phase_preflight(motion, source_pose, contract={})

    assert observed_tracks == [{}]
    assert result["sourcePhase"]["passed"] is False
    assert result["sourcePhaseFootOrientationEvidence"] == {}
