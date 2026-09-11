import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.foot_kinematics import blend_contact_transition_rotations
from exercise_motion_pkg.foot_kinematics import solve_rigid_foot_contacts
from exercise_motion_pkg.foot_kinematics import _leg_candidates
from exercise_motion_pkg.models import MotionClip, MotionFrame
import pytest


def test_contact_entry_is_smooth_without_shortening_bones_or_moving_anchors():
    original = np.tile([[0., 1., 0.], [0., .5, .1], [0., 0., .1], [0., 0., .3]], (15, 1, 1))
    supported = np.arange(15) >= 3
    corrected = original.copy()
    rotation = Rotation.from_euler('x', 25, degrees=True)
    hip = original[0, 0]
    corrected[supported] = rotation.apply((original[supported] - hip).reshape(-1, 3)).reshape(-1, 4, 3) + hip
    result = blend_contact_transition_rotations(original, corrected, supported, 30)
    assert np.array_equal(result[supported], corrected[supported])
    for frame in np.flatnonzero(~supported):
        np.testing.assert_allclose(np.linalg.norm(np.diff(result[frame], axis=0), axis=1),
                                   np.linalg.norm(np.diff(original[frame], axis=0), axis=1), atol=1e-10)
    before_jump = np.linalg.norm(corrected[3, -1] - corrected[2, -1])
    after_jump = np.linalg.norm(result[3, -1] - result[2, -1])
    assert after_jump < before_jump


def test_swing_transition_preserves_contacts_and_is_independent_of_clip_cut():
    original = np.tile([[0., 1., 0.], [0., .5, .1], [0., 0., .1], [0., 0., .3]], (30, 1, 1))
    original[:, :, 0] += np.sin(np.arange(30)[:, None] / 10)
    corrected = original.copy()
    supported = np.arange(30) >= 25
    corrected[supported, 2:, 2] += .1
    result = blend_contact_transition_rotations(original, corrected, supported, 30)
    assert np.array_equal(result[supported], corrected[supported])
    shortened = blend_contact_transition_rotations(original[:28], corrected[:28], supported[:28], 30)
    np.testing.assert_allclose(shortened, result[:28], atol=1e-10)


def test_unobserved_tail_is_not_forced_back_to_source_at_file_end():
    original = np.tile([[0., 1., 0.], [0., .5, .1], [0., 0., .1], [0., 0., .3]], (30, 1, 1))
    supported = np.arange(30) <= 5
    corrected = original.copy()
    rotation = Rotation.from_euler('x', 20, degrees=True)
    hip = original[0, 0]
    corrected[supported] = rotation.apply((original[supported] - hip).reshape(-1, 3)).reshape(-1, 4, 3) + hip
    result = blend_contact_transition_rotations(original, corrected, supported, 30)
    shortened = blend_contact_transition_rotations(original[:18], corrected[:18], supported[:18], 30)
    np.testing.assert_allclose(shortened, result[:18], atol=1e-10)
    assert not np.allclose(shortened[-1], original[17])
    assert np.array_equal(result[supported], corrected[supported])


@pytest.mark.parametrize("angle", [65.0, 145.0])
def test_grounded_source_pose_outside_old_ankle_range_is_not_forced_into_range(angle):
    # The same joint convention used by the solver: shin-to-toe separation.
    # A geometric fixture, not a claim of clinically normal range of motion.
    ankle = np.array([0., 0., 0.])
    knee = .5 * np.array([0., np.sin(np.deg2rad(angle)), np.cos(np.deg2rad(angle))])
    hip = knee + np.array([0., .2, -np.sqrt(.21)])
    joints = {"left_hip": tuple(hip), "left_knee": tuple(knee),
              "left_ankle": tuple(ankle), "left_foot": (0., 0., .2)}
    clip = MotionClip(fps=30, joint_names=list(joints),
                      frames=[MotionFrame(i / 30, dict(joints)) for i in range(3)])
    result, report = solve_rigid_foot_contacts(clip, {"contacts": [{
        "jointName": "left_foot", "startRatio": 0., "endRatio": 1.,
        "contactState": "full_sole", "motion": "stationary",
    }]})
    assert report["applied"]
    for frame in result.frames:
        for name, point in joints.items():
            np.testing.assert_allclose(frame.joints[name], point, atol=1e-5)


def test_collinear_pole_cannot_produce_valid_shortened_leg():
    _, _, _, valid = _leg_candidates(
        np.array([0., 1., 0.]), np.array([0., 0., 0.]),
        np.array([0., -1., 0.]), np.deg2rad(np.array([60., 90., 120.])),
        np.ones(3), .6, .5, .2,
    )
    assert not np.any(valid)


def test_transition_blending_preserves_knee_flexion():
    original = np.tile([[0., 1., 0.], [0., .6, .2], [0., .1, .1], [0., .1, .3]], (15, 1, 1))
    corrected = original.copy()
    supported = np.arange(15) >= 3
    # Different thigh/shin corrections previously changed free-frame flexion.
    corrected[supported, 1] += [.1, 0., .1]
    corrected[supported, 2:] += [.2, .05, .15]
    result = blend_contact_transition_rotations(original, corrected, supported, 30)
    def cosine(poses):
        thigh = poses[:, 0] - poses[:, 1]
        shin = poses[:, 2] - poses[:, 1]
        return np.sum(thigh * shin, axis=1) / (np.linalg.norm(thigh, axis=1) * np.linalg.norm(shin, axis=1))
    np.testing.assert_allclose(cosine(result[~supported]), cosine(original[~supported]), atol=1e-10)


def test_contact_solver_uses_exported_floor():
    joints = {"left_hip": (0., .8, 0.), "left_knee": (0., .4, .1),
              "left_ankle": (0., 0., 0.), "left_foot": (0., 0., .2)}
    clip = MotionClip(fps=30, joint_names=list(joints), metadata={"renderFloorY": .15},
                      frames=[MotionFrame(i / 30, dict(joints)) for i in range(5)])
    result, report = solve_rigid_foot_contacts(clip, {"contacts": [{
        "jointName": "left_foot", "startRatio": 0., "endRatio": 1.,
        "contactState": "full_sole", "contactMotion": "stationary",
    }]})
    assert report["applied"]
    assert report["supportPlaneY"] == .15
    for frame in result.frames:
        assert frame.joints["left_foot"][1] == pytest.approx(.15)
        assert frame.joints["left_ankle"][1] == pytest.approx(.15)


def test_generated_support_surface_is_not_a_stationary_anchor():
    from exercise_motion_pkg.contact_constraints import is_stationary_contact
    assert not is_stationary_contact({"surfaceKind": "contract_inferred_support_surface",
                                      "sourceStationarySupportCandidate": True})
    assert is_stationary_contact({"surfaceKind": "observed_support_surface",
                                  "contactMotion": "stationary"})


def test_full_sole_support_allows_a_straight_leg_at_maximum_reach():
    joints = {"left_hip": (0., .8, 0.), "left_knee": (0., .4, 0.),
              "left_ankle": (0., 0., 0.), "left_foot": (0., 0., .2)}
    clip = MotionClip(fps=30, joint_names=list(joints),
                      frames=[MotionFrame(i / 30, dict(joints)) for i in range(5)])
    result, report = solve_rigid_foot_contacts(clip, {"contacts": [{
        "jointName": "left_foot", "startRatio": 0., "endRatio": 1.,
        "contactState": "full_sole", "contactMotion": "stationary",
    }]})
    assert report["applied"]
    for frame in result.frames:
        for name, point in joints.items():
            np.testing.assert_allclose(frame.joints[name], point, atol=1e-7)


def test_source_knee_pole_does_not_flip_with_a_shifted_target_axis():
    from exercise_motion_pkg.foot_kinematics import _flat_leg_pose, _source_knee_poles
    hip = np.array([0., 1., 0.])
    knee = np.array([0., .5, .03])
    ankle = np.array([0., 0., 0.])
    # The axial thigh component dominated the small forward bend before.
    target = np.array([0., 0., -.1])
    heading = np.array([0., 0., 1.])
    pole = _source_knee_poles(hip, knee, ankle)
    result, new_ankle, _, _ = _flat_leg_pose(
        hip, target, heading, .6, .6, .2, knee_poles=pole)
    axis = new_ankle - hip
    bend = result - hip - axis * np.dot(result - hip, axis) / np.dot(axis, axis)
    assert np.dot(bend, pole) > 0


def test_contact_pass_cannot_spend_source_articulation_tolerance_twice():
    from exercise_motion_pkg.foot_kinematics import source_knee_angle_bounds, _contact_knee_bounds
    def points(angle):
        return np.array([[0., 1., 0.], [0., 0., 0.],
                         [0., np.cos(np.deg2rad(angle)), np.sin(np.deg2rad(angle))]])
    source = points(100)
    names = ["left_hip", "left_knee", "left_ankle"]
    clip = MotionClip(fps=30, joint_names=names, frames=[
        MotionFrame(i / 30, dict(zip(names, source))) for i in range(3)])
    bounds = source_knee_angle_bounds(clip, envelope_tolerance_degrees=1., phase_tolerance_degrees=10.)
    repaired = np.tile(points(101), (3, 1, 1))
    low, high = _contact_knee_bounds(repaired[:, 0], repaired[:, 1], repaired[:, 2], bounds["left"])
    np.testing.assert_allclose(np.rad2deg(low), 99.)
    np.testing.assert_allclose(np.rad2deg(high), 101.)
