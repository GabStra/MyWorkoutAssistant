import math
from dataclasses import replace

import numpy as np
import pytest

from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg import structural_refinement as s
from exercise_motion_pkg import bake_and_rank as b
from exercise_motion_pkg.foot_kinematics import solve_rigid_foot_contacts, _knee_angles
from exercise_motion_pkg.bilateral_evidence import source_arm_symmetry_evidence


def test_body_supported_upper_back_bar_retains_hand_constraint():
    contract = {"implementSupportMode": "body_supported", "requiredEquipment": ["barbell"],
                "validStartState": "Standing with a barbell across the upper back",
                "validEndState": "Standing with a barbell across the upper back",
                "startPoseConstraints": {"handHeight": "shoulder_chest"},
                "endPoseConstraints": {"handHeight": "shoulder_chest"}}
    assert b.exercise_motion_contract_requires_rigid_paired_hands(contract)
    contract["validStartState"] = "Lying with a barbell across the hips"
    contract["validEndState"] = contract["validStartState"]
    assert not b.exercise_motion_contract_requires_rigid_paired_hands(contract)


def leg_clip():
    joints = {"pelvis": (0, 1, 0), "neck": (0, 1.5, 0)}
    for side, x, bend in [("left", -.15, .3), ("right", .15, .4)]:
        joints.update({f"{side}_hip": (x, 1, 0), f"{side}_knee": (x, .5, bend),
                       f"{side}_ankle": (x, 0, 0), f"{side}_foot": (x, 0, .15)})
    return MotionClip(30, list(joints), [MotionFrame(i / 30, dict(joints)) for i in range(5)])


def test_contact_solver_preserves_unobserved_leg_and_observed_knee_angle():
    clip = leg_clip()
    result, report = solve_rigid_foot_contacts(clip, {"contacts": [
        {"jointName": "left_foot", "contactState": "full_sole", "startRatio": 0, "endRatio": 1}
    ]})
    assert report["applied"]
    assert set(report["feet"]) == {"left"}
    for before, after in zip(clip.frames, result.frames):
        delta = np.array(after.joints["pelvis"]) - before.joints["pelvis"]
        for name in ("right_hip", "right_knee", "right_ankle", "right_foot"):
            assert np.array(after.joints[name]) == pytest.approx(np.array(before.joints[name]) + delta)
        def angle(frame):
            return _knee_angles(*[np.array(frame.joints[f"left_{name}"]) for name in ("hip", "knee", "ankle")])
        assert abs(angle(after) - angle(before)) <= math.radians(1.001)
        assert after.joints["left_foot"][1] == pytest.approx(0)
        for parent, child in [("hip", "knee"), ("knee", "ankle"), ("ankle", "foot")]:
            assert math.dist(after.joints[f"left_{parent}"], after.joints[f"left_{child}"]) == pytest.approx(
                math.dist(before.joints[f"left_{parent}"], before.joints[f"left_{child}"]))


@pytest.mark.parametrize("mirror", [False, True])
def test_source_articulation_is_independent_of_source_translation(mirror):
    args = dict(parent=(.5, 1, .2), transform=(1, 0, 0, 0, 0, 0),
                horizontal_vector=(1, 0), mirror=mirror)
    expected = s._source_relative_endpoint_projection(source_parent=(0, 0), source_child=(.2, .4), **args)
    shifted = s._source_relative_endpoint_projection(source_parent=(8, -3), source_child=(8.2, -2.6), **args)
    assert shifted == pytest.approx(expected)


def test_independently_validated_repair_is_not_clamped_to_erroneous_input(monkeypatch):
    before = leg_clip()
    frames = [MotionFrame(f.time_sec, {**f.joints, "left_knee": (-.15, .5, .1)}) for f in before.frames]
    proposed = replace(before, frames=frames)
    monkeypatch.setattr(s, "registered_camera_pose_fidelity_metrics", lambda *a, **k: {
        "available": True, "p90JointErrorBodyRatio": .1 if k.get('camera_reference') else .2})
    repaired, report = s._accept_source_preserving_refinement_step(
        before, proposed, source_pose_payload={}, step_name="source_guided", source_guided_articulation=True)
    assert report["accepted"]
    assert repaired.frames == proposed.frames
    constrained, _ = s._accept_source_preserving_refinement_step(
        before, proposed, source_pose_payload=None, step_name="ordinary_cleanup")
    assert constrained.frames != proposed.frames


def press_clip():
    clip = leg_clip()
    frames = []
    for index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        joints["neck"] = (0, 1, .7)
        for side, x, height, bend in [("left", -.2, 1.04, .05), ("right", .2, .96, .16)]:
            joints.update({f"{side}_shoulder": (x, height, .6),
                           f"{side}_elbow": (x, height + .3, .6 + bend),
                           f"{side}_wrist": (x, height + .55 - index * .015, .6),
                           f"{side}_hand": (x, height + .63 - index * .015, .62)})
        frames.append(MotionFrame(frame.time_sec, joints))
    return replace(clip, frames=frames, joint_names=list(frames[0].joints))


def test_supported_press_levels_shoulders_without_moving_feet_or_stretching_arms():
    clip = press_clip()
    result, _ = s._align_upper_body_to_horizontal_support(clip, level_shoulders=True)
    for before, after in zip(clip.frames, result.frames):
        assert after.joints["left_shoulder"][1] == pytest.approx(after.joints["right_shoulder"][1])
        for side in ("left", "right"):
            assert after.joints[f"{side}_foot"] == before.joints[f"{side}_foot"]
            assert math.dist(after.joints[f"{side}_shoulder"], after.joints[f"{side}_hand"]) == pytest.approx(
                math.dist(before.joints[f"{side}_shoulder"], before.joints[f"{side}_hand"]))


def test_rigid_hand_solver_preserves_shared_endpoints_and_all_arm_bone_lengths():
    clip = press_clip()
    result, report = s._stabilize_rigid_paired_hand_spacing(clip)
    for before, after in zip(clip.frames, result.frames):
        assert math.dist(after.joints["left_hand"], after.joints["right_hand"]) == pytest.approx(report["targetSpacing"], abs=1e-7)
        before_axis = np.subtract(before.joints["left_hand"], before.joints["right_hand"])
        after_axis = np.subtract(after.joints["left_hand"], after.joints["right_hand"])
        np.testing.assert_allclose(after_axis/np.linalg.norm(after_axis),
                                   before_axis/np.linalg.norm(before_axis), atol=1e-7)
        for side in ("left", "right"):
            for parent, child in [("shoulder", "elbow"), ("elbow", "wrist"), ("wrist", "hand")]:
                assert math.dist(after.joints[f"{side}_{parent}"], after.joints[f"{side}_{child}"]) == pytest.approx(
                    math.dist(before.joints[f"{side}_{parent}"], before.joints[f"{side}_{child}"]))


def test_rigid_grip_preserves_measured_midpoint_axis_and_independent_elbow_bends():
    clip = press_clip()
    frames = []
    for index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        joints["left_elbow"] = (-.2, 1.5, .5)
        joints["right_elbow"] = (.2, 1.1, -.25)
        frames.append(MotionFrame(frame.time_sec, joints))
    clip = replace(clip, frames=frames)
    result, report = s._stabilize_rigid_paired_hand_spacing(clip)
    assert report["preservedMeasuredHandMidpoint"]
    assert report["preservedMeasuredHandAxis"]
    for before, after in zip(clip.frames, result.frames):
        before_mid = (np.array(before.joints["left_hand"]) + np.array(before.joints["right_hand"])) / 2
        after_mid = (np.array(after.joints["left_hand"]) + np.array(after.joints["right_hand"])) / 2
        np.testing.assert_allclose(after_mid, before_mid, atol=1e-7)
        before_axis = np.subtract(before.joints["right_hand"], before.joints["left_hand"])
        after_axis = np.subtract(after.joints["right_hand"], after.joints["left_hand"])
        np.testing.assert_allclose(after_axis / np.linalg.norm(after_axis),
                                   before_axis / np.linalg.norm(before_axis), atol=1e-7)
        assert after.joints["left_elbow"][2] > 0
        assert after.joints["right_elbow"][2] < 0


def test_2d_symmetric_projection_and_rigid_grip_do_not_mirror_3d_arm_pose():
    frames = []
    source_frames = []
    for index in range(12):
        phase = index / 11
        joints = {
            "pelvis": (0, 0, 0), "neck": (0, 1.5, 0),
            "left_shoulder": (-.2, 1, 0), "right_shoulder": (.2, 1, 0),
            "left_hip": (-.15, .4, 0), "right_hip": (.15, .4, 0),
            "left_elbow": (-.4, 1.3 + .15 * phase, .35),
            "right_elbow": (.4, 1.3 + .15 * phase, -.35),
            "left_wrist": (-.6, 1.7 + .15 * phase, .35),
            "right_wrist": (.6, 1.7 + .15 * phase, -.35),
            "left_hand": (-.7, 1.75 + .15 * phase, .35),
            "right_hand": (.7, 1.75 + .15 * phase, -.35),
        }
        frames.append(MotionFrame(index / 30, joints))
        source_frames.append({"sourceTimeSec": index / 30,
                              "joints": {name: [point[0], -point[1]]
                                         for name, point in joints.items()}})
    clip = MotionClip(30, list(frames[0].joints), frames)
    source = {"frames": source_frames}
    assert source_arm_symmetry_evidence(source)["accepted"]

    refined = s.refine_motion_clip_structurally(
        clip, source_pose_payload=source, rigid_paired_hands_required=True)

    for frame in refined.frames:
        assert frame.joints["left_elbow"][2] > 0.2
        assert frame.joints["right_elbow"][2] < -0.2
        assert frame.joints["left_hand"][2] > 0.2
        assert frame.joints["right_hand"][2] < -0.2
    report = refined.metadata["structuralRefinement"]
    assert report["finalSamePhaseArmSymmetry"]["applied"] is False


def test_terminal_cleanup_preserves_supported_press_constraints():
    clip = press_clip()
    result = s.refine_motion_clip_structurally(
        clip, rigid_paired_hands_required=True, horizontal_torso_required=True)
    distances = []
    for source_frame, frame in zip(clip.frames, result.frames):
        j = frame.joints
        assert (j["left_shoulder"][1] - j["right_shoulder"][1]) == pytest.approx(
            source_frame.joints["left_shoulder"][1] - source_frame.joints["right_shoulder"][1],
            abs=1e-7)
        distances.append(math.dist(j["left_hand"], j["right_hand"]))
    assert max(distances) - min(distances) < 1e-7


def test_vertical_arm_ik_has_a_valid_bend_plane():
    elbow, hand = s._solve_two_bone(
        root=(0, 0, 0), current_mid=(0, .5, 0), target_end=(0, .8, 0),
        upper_len=.5, lower_len=.5, fallback_axis=(0, 1, 0),
        preferred_bend_direction=(0, .5, 0))
    assert hand == pytest.approx((0, .8, 0))
    assert math.dist((0, 0, 0), elbow) == pytest.approx(.5)
    assert math.dist(elbow, hand) == pytest.approx(.5)


def test_source_guided_single_arm_fit_does_not_move_opposite_arm(monkeypatch):
    clip = press_clip()
    source = {"frames": [{"sourceTimeSec": f.time_sec,
                          "joints": {k: [v[0], -v[1]] for k, v in f.joints.items()}}
                         for f in clip.frames]}
    for frame in source["frames"]:
        frame["joints"]["left_elbow"][0] -= .15
    monkeypatch.setattr(s, "source_to_motion_pose_fidelity_metrics", lambda *a: {
        "available": True, "projectionHorizontalVector": [1, 0]})
    monkeypatch.setattr(s.pose_fidelity, "_global_similarity_transform", lambda *a, **k: (1, 0, 0, 0, 0, 0))
    result, report = s._align_hinge_articulation_to_source_pose(
        clip, source_pose_payload=source, chains=(s.SOURCE_GUIDED_ARM_CHAINS[0],))
    assert report["applied"]
    for before, after in zip(clip.frames, result.frames):
        for name in ("right_shoulder", "right_elbow", "right_wrist", "right_hand"):
            assert after.joints[name] == before.joints[name]
        for parent, child in [("shoulder", "elbow"), ("elbow", "wrist"), ("wrist", "hand")]:
            assert math.dist(after.joints[f"left_{parent}"], after.joints[f"left_{child}"]) == pytest.approx(
                math.dist(before.joints[f"left_{parent}"], before.joints[f"left_{child}"]))
