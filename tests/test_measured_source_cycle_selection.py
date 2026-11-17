import math

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import controlled_motion as controlled
from exercise_motion_pkg.pose_fidelity import _canonical_source_pose_sha256


def _mapped_cycle_payload():
    selected_sha, parent_sha = "a" * 64, "b" * 64
    times = [index / 10 for index in range(31)]
    angles = [0.12 * math.sin(2.0 * math.pi * index / 15.0) for index in range(31)]
    pose = {
        "sourceVideoSha256": selected_sha, "sourceTimeOriginSec": 0.0,
        "jointNames": ["pelvis", "left_knee", "right_knee", "left_ankle", "right_ankle"],
        "rootJoint": "pelvis",
        "frames": [{"timeSec": time, "sourceTimeSec": time, "joints": {
            "pelvis": [0.0, 1.0, 0.0], "left_knee": [-0.1, 0.5, 0.0],
            "right_knee": [0.1, 0.5, 0.0], "left_ankle": [-0.1, 0.1, 0.0],
            "right_ankle": [0.1, 0.1, 0.0],
        }} for time in times],
    }
    evidence = {"sourceVideoSha256": selected_sha, "footPatchEvidence": {
        "available": True, "sourceVideoSha256": selected_sha,
        "sourceTimeBasis": "absolute_source_video", "sourceTimeOriginSec": 0.0,
        "sourceTimesSec": times,
        "feet": {"right": {"rayObservations": [
            {"sourceTimeSec": time, "ankleToToeImageRay": [math.cos(angle), math.sin(angle)],
             "confidence": 0.95}
            for time, angle in zip(times, angles)
        ]}},
    }}
    mapping = {
        "schemaVersion": 1, "verified": True,
        "mappingKind": "selected_segment_to_parent_source",
        "selectedSegmentSha256": selected_sha, "parentSourceSha256": parent_sha,
        "selectedFrameClockReceiptSha256": "c" * 64,
        "sourcePosePayloadSha256": _canonical_source_pose_sha256(pose),
        "selectedOutputFps": 10.0, "selectedFrameCount": len(times),
        "selectedFrameLineage": [
            {"selectedFrameIndex": index, "selectedFrameTimeSec": time,
             "parentSourceFrameIndex": index + 100, "parentSourceTimeSec": time + 2.0}
            for index, time in enumerate(times)
        ],
    }
    motion = {
        "frames": [{"timeSec": time, "sourceTimeSec": time + 2.0, "joints": {
            "pelvis": [0.0, 1.0, 0.0], "left_knee": [-0.1, 0.5, 0.0],
            "right_knee": [0.1, 0.5, 0.0], "left_ankle": [-0.1, 0.1, 0.0],
            "right_ankle": [0.1, 0.1, 0.0], "left_foot": [-0.1, 0.0, 0.0],
            "right_foot": [0.1, 0.0, 0.0],
        }} for time in times],
        "jointNames": ["pelvis", "left_knee", "right_knee", "left_ankle", "right_ankle",
                       "left_foot", "right_foot"],
        "loop": {"enabled": True}, "fps": 10.0,
        "exerciseMotionContract": {"exerciseName": "Calf Raise"},
        "sourcePoseReference": pose,
        "sourcePoseCameraReference": {"sourceTimelineMapping": mapping},
        "sourceFootSupportEvidence": evidence,
    }
    return pose, motion


def test_one_source_orientation_cycle_is_materialized_only_after_phase_and_endpoint_pass(monkeypatch):
    pose, payload = _mapped_cycle_payload()
    spec = {"primaryMovingRegions": ["feet"], "referenceRegions": ["knees"],
            "primaryAxis": "vertical", "motionPattern": "distal_limb_vertical"}
    monkeypatch.setattr(bake, "observable_motion_spec_for_contract", lambda _contract: spec)
    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_source_pose_payload",
                        lambda _frames, **_kwargs: {
                            "required": True, "passed": True, "hasSingleMajorCycle": True,
                            "dominantJointSelection": "observable_source_foot_orientation",
                        })
    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_payload",
                        lambda *_args, **_kwargs: {"required": True, "passed": False,
                                                  "reason": "one_way_partial_repetition_phase"})
    monkeypatch.setattr(bake, "body_height_from_payload_frames", lambda _frames: 1.0)
    from exercise_motion_pkg import loop_cycles
    monkeypatch.setattr(loop_cycles, "cycle_boundary_motion_metrics",
                        lambda *_args, **_kwargs: {"passed": True, "rejectionReasons": []})

    candidate, evidence = controlled._first_verified_source_orientation_cycle(payload)

    assert candidate is not None
    assert evidence["selection"] == {"startFrame": 9, "stopFrameExclusive": 30, "score": 1.0}
    assert evidence["sourcePhase"]["passed"] is True
    assert evidence["outputPhaseBeforeFit"]["passed"] is False
    assert candidate["selectedIntervalSourcePhasePreflight"]["passed"] is True


def test_no_proposals_path_fits_one_source_cycle_instead_of_rejecting_empty_cache(monkeypatch):
    pose, payload = _mapped_cycle_payload()
    payload["observedCycleProposals"] = []
    payload["sourceCyclePreflight"] = [{"passed": False, "reason": "no_feasible_observed_cycle"}]
    spec = {"primaryMovingRegions": ["feet"], "referenceRegions": ["knees"],
            "primaryAxis": "vertical", "motionPattern": "distal_limb_vertical"}
    monkeypatch.setattr(bake, "observable_motion_spec_for_contract", lambda _contract: spec)
    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_source_pose_payload",
                        lambda _frames, **_kwargs: {
                            "required": True, "passed": True, "hasSingleMajorCycle": True,
                            "dominantJointSelection": "observable_source_foot_orientation",
                        })
    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_payload",
                        lambda *_args, **_kwargs: {"required": True, "passed": False,
                                                  "reason": "one_way_partial_repetition_phase"})
    monkeypatch.setattr(bake, "body_height_from_payload_frames", lambda _frames: 1.0)
    from exercise_motion_pkg import loop_cycles

    def boundary(candidate, *_args, **_kwargs):
        return {"passed": len(candidate["frames"]) < len(payload["frames"]),
                "rejectionReasons": [] if len(candidate["frames"]) < len(payload["frames"])
                else ["source_support_wrap_unrepairable"]}

    monkeypatch.setattr(loop_cycles, "cycle_boundary_motion_metrics", boundary)
    attempts = []

    def capture_fit(candidate, **kwargs):
        attempts.append((candidate, kwargs))
        return candidate, {"applied": False, "reason": "captured_single_trial",
                           "checks": {"trajectoryFit": False}}

    monkeypatch.setattr(controlled, "_fit_controlled_motion", capture_fit)

    fitted, report = controlled._fit_observed_cycles(
        payload, max_evaluations=7, timeout_seconds=60.0,
    )

    assert len(attempts) == 1
    assert attempts[0][0]["loopCycleSelection"]["startFrame"] == 9
    assert attempts[0][0]["loopCycleSelection"]["stopFrameExclusive"] == 30
    assert attempts[0][1]["timeout_seconds"] <= 60.0
    assert fitted is attempts[0][0]
    assert report["sourceMeasuredCycleFitEvidence"]["fitReason"] == "captured_single_trial"
    assert report["sourceMeasuredCycleFitEvidence"]["checks"] == {"trajectoryFit": False}
