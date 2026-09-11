import copy

import numpy as np
import pytest

from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.foot_kinematics import _knee_angles, _contact_knee_bounds, _leg_candidates
from exercise_motion_pkg.structural_refinement import constrain_to_source_articulation_envelope
from exercise_motion_pkg.structural_refinement import _rotate_hinge_descendants


def test_branch_restoration_preserves_flexion_when_parent_axis_changes():
    joints = {"pelvis": (0., 0., 0.), "neck": (0., 1., 0.),
              "left_hip": (-.2, 0., 0.), "right_hip": (.2, 0., 0.),
              "left_shoulder": (-.3, .8, 0.), "right_shoulder": (.3, .8, 0.),
              "right_knee": (.2, -.5, 0.), "right_ankle": (.2, -.7, .4)}
    source = MotionClip(30., list(joints), [MotionFrame(i / 30, dict(joints)) for i in range(3)])
    source.frames[1].joints["right_ankle"] = (.2, -.94, .04)
    proposed = copy.deepcopy(source)
    parent_axis = np.array([0., .6, -.8])
    wrong_bend = np.array([0., -.8, -.6])
    cosine = -1 / np.sqrt(5.)
    knee = np.array([.2, -.3, .4])
    ankle = knee + np.sqrt(.2) * (parent_axis * cosine + wrong_bend * np.sqrt(1 - cosine**2))
    proposed.frames[0].joints.update(right_knee=tuple(knee), right_ankle=tuple(ankle))
    result, report = constrain_to_source_articulation_envelope(source, proposed)
    assert report["preventedHingeBranchFlipCount"] >= 1
    def angle(frame):
        return _knee_angles(*[np.array(frame.joints[n]) for n in ["right_hip", "right_knee", "right_ankle"]])
    assert angle(result.frames[0]) == pytest.approx(angle(proposed.frames[0]), abs=1e-10)
    assert np.linalg.norm(np.array(result.frames[0].joints["right_ankle"]) - knee) == pytest.approx(np.sqrt(.2))


def test_authoritative_source_bounds_replace_intermediate_pose_band():
    hips = np.array([[0., 1., 0.]])
    knees = np.array([[0., 0., 0.]])
    ankles = np.array([[0., np.cos(np.deg2rad(110)), np.sin(np.deg2rad(110))]])
    bounds = np.deg2rad([[95., 115.]])
    low, high = _contact_knee_bounds(hips, knees, ankles, bounds)
    assert np.rad2deg(low[0]) == pytest.approx(95.)
    assert np.rad2deg(high[0]) == pytest.approx(115.)


def test_partial_contact_allows_exact_extended_combined_link():
    angle = np.deg2rad(130.687)
    thigh, shin, foot = .3926, .4092, .1322
    reach = thigh + np.sqrt(shin**2 + foot**2 - 2 * shin * foot * np.cos(angle))
    knees, ankles, vectors, valid = _leg_candidates(
        np.array([0., reach, 0.]), np.zeros(3), np.array([0., 0., 1.]),
        np.array([angle]), np.array([1.]), thigh, shin, foot,
        knee_poles=np.array([0., 0., 1.]))
    assert valid[0]
    assert np.linalg.norm(ankles[0] - knees[0]) == pytest.approx(shin)
    assert np.linalg.norm(vectors[0]) == pytest.approx(foot)


def test_hinge_correction_rotates_distal_chain_without_changing_ankle_articulation():
    joints = {"hip": (0., 1., 0.), "knee": (0., 0., 0.),
              "ankle": (0., -.5, 0.), "toe": (0., -.5, .2)}
    before = _knee_angles(*[np.array(joints[n]) for n in ["knee", "ankle", "toe"]])
    _rotate_hinge_descendants(joints, parent="hip", hinge="knee", child="ankle",
                              descendants=("ankle", "toe"), target_child=(0., 0., .5))
    after = _knee_angles(*[np.array(joints[n]) for n in ["knee", "ankle", "toe"]])
    assert after == pytest.approx(before)
    assert np.linalg.norm(np.array(joints["toe"]) - joints["ankle"]) == pytest.approx(.2)


def test_parent_rotation_is_not_misclassified_as_a_hinge_branch_flip():
    from scipy.spatial.transform import Rotation
    joints = {"pelvis": (0., 0., 0.), "neck": (0., 1., 0.),
              "left_hip": (-.2, 0., 0.), "right_hip": (.2, 0., 0.),
              "left_shoulder": (-.3, .8, 0.), "right_shoulder": (.3, .8, 0.),
              "right_knee": (.2, -.5, 0.), "right_ankle": (.2, -.7, .4),
              "right_foot": (.2, -.7, .5)}
    source = MotionClip(30., list(joints), [MotionFrame(i / 30, dict(joints)) for i in range(3)])
    proposed = copy.deepcopy(source)
    origin = np.array(joints["right_hip"])
    rotation = Rotation.from_euler('x', 120, degrees=True)
    for frame in proposed.frames:
        for name in ["right_knee", "right_ankle", "right_foot"]:
            frame.joints[name] = tuple(origin + rotation.apply(np.array(frame.joints[name]) - origin))
    result, report = constrain_to_source_articulation_envelope(source, proposed)
    assert report["preventedHingeBranchFlipCount"] == 0
    for before, after in zip(proposed.frames, result.frames):
        assert before.joints == after.joints


def test_contact_bend_plane_stays_continuous_when_target_crosses_old_pole():
    from exercise_motion_pkg.foot_kinematics import _flat_leg_pose
    angles = np.deg2rad([89., 90., 91.])
    axes = np.column_stack([np.zeros(3), -np.cos(angles), np.sin(angles)])
    headings = np.tile([1., 0., 0.], (3, 1))
    hips = np.zeros((3, 3))
    knees, ankles, _, _ = _flat_leg_pose(
        hips, axes * .7 + headings * .15, headings, .5, .5, .15,
        knee_poles=np.tile([0., 0., 1.], (3, 1)),
        source_axes=np.tile([0., -1., 0.], (3, 1)))
    assert np.max(np.linalg.norm(np.diff(knees, axis=0), axis=1)) < .02
    np.testing.assert_allclose(np.linalg.norm(knees - hips, axis=1), .5)
    np.testing.assert_allclose(np.linalg.norm(ankles - knees, axis=1), .5)


def test_neighboring_anchor_fit_does_not_concentrate_drift_into_short_release():
    from exercise_motion_pkg.contact_constraints import stationary_target_track
    points = np.column_stack([np.linspace(0., .4, 30), np.zeros(30), np.zeros(30)])
    supported = np.ones(30, dtype=bool)
    supported[14:17] = False
    independent, _ = stationary_target_track(points, supported)
    coherent, episodes = stationary_target_track(points, supported, fps=30.)
    assert np.max(np.linalg.norm(np.diff(coherent, axis=0), axis=1)) < np.max(
        np.linalg.norm(np.diff(independent, axis=0), axis=1))
    for episode in episodes:
        start, end = episode['startFrame'], episode['endFrame']
        np.testing.assert_allclose(coherent[start:end + 1], np.tile(coherent[start], (end - start + 1, 1)))
    assert coherent[0, 0] < coherent[-1, 0]


def test_transition_matches_moving_correction_velocity_at_stance_boundaries():
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg.foot_kinematics import blend_contact_transition_rotations
    pose = np.array([[0., 1., 0.], [0., .6, .2], [0., .1, .1], [0., .1, .3]])
    original = np.array([Rotation.from_euler('x', i * .01).apply(pose - pose[0]) + pose[0]
                         for i in range(25)])
    supported = (np.arange(25) <= 5) | (np.arange(25) >= 20)
    corrected = original.copy()
    corrected[supported] = pose
    result = blend_contact_transition_rotations(original, corrected, supported, 30.)
    np.testing.assert_allclose(result, np.tile(pose, (25, 1, 1)), atol=1e-9)
