import copy

import pytest

from exercise_motion_pkg import bake_and_rank as b


def pose_frames(*, seated=False):
    joints = {
        "nose": [.5, .1, 0], "left_shoulder": [.4, .25, 0],
        "right_shoulder": [.6, .25, 0], "left_hip": [.43, .55, 0],
        "right_hip": [.57, .55, 0], "left_wrist": [.3, .3, 0],
        "right_wrist": [.7, .3, 0],
    }
    for side, x in (("left", .43), ("right", .57)):
        joints[f"{side}_knee"] = [x + .2, .57, 0] if seated else [x, .73, 0]
        joints[f"{side}_ankle"] = [x + .2, .9, 0] if seated else [x, .95, 0]
    return [{"sourceTimeSec": i / 10, "joints": copy.deepcopy(joints)} for i in range(12)]


def seated_contract():
    return {"exerciseName": "Seated Overhead Press", "completionMode": "return_to_start",
            "startPoseConstraints": {"supportMode": "seated"},
            "endPoseConstraints": {"supportMode": "seated"}}


def test_stationary_seated_legs_do_not_create_standing_conflict():
    endpoints = b.source_pose_endpoint_feature_summary({"frames": pose_frames(seated=True)})
    assert endpoints["dynamicSupportEvidence"]["lowerLegMotionIndependentOfPelvis"] is False
    assert endpoints["start"]["supportMode"] == "unknown"
    assert endpoints["end"]["supportMode"] == "unknown"
    verdict = b.validate_source_pose_endpoints_against_contract(endpoints, seated_contract())
    assert not verdict.get("blockingMismatches")


def test_clear_standing_pose_still_conflicts_with_explicit_seated_requirement():
    endpoints = b.source_pose_endpoint_feature_summary({"frames": pose_frames()})
    assert endpoints["start"]["supportMode"] == "standing"
    verdict = b.validate_source_pose_endpoints_against_contract(endpoints, seated_contract())
    assert verdict["passed"] is False
    assert any(row["field"] == "supportMode" for row in verdict["blockingMismatches"])


@pytest.mark.parametrize("missing", ["left_knee", "right_ankle"])
def test_incomplete_legs_do_not_imply_standing(missing):
    frames = pose_frames()
    for frame in frames:
        del frame["joints"][missing]
    assert b.source_pose_endpoint_features(frames)["supportMode"] == "unknown"


def test_crouched_pose_is_not_relabelled_as_seated():
    frames = pose_frames(seated=True)
    for frame in frames:
        frame["joints"]["left_hip"][1] = .7
        frame["joints"]["right_hip"][1] = .7
    assert b.source_pose_endpoint_features(frames)["supportMode"] == "unknown"
