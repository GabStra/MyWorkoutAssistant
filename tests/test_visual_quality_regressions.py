import math
from dataclasses import replace

import numpy as np
import pytest

from exercise_motion_pkg import bake_and_rank as b
from exercise_motion_pkg import structural_refinement as s
from exercise_motion_pkg.models import MotionClip, MotionFrame


@pytest.mark.parametrize("level_shoulders", [False, True])
def test_support_alignment_preserves_root_bone_with_offset_hip_center(level_shoulders):
    from scipy.spatial.transform import Rotation

    frames = []
    for i, pitch in enumerate((10, 25, 5)):
        joints = {"pelvis": (0., 0., 0.), "left_hip": (-.1, -.03, .04),
                  "right_hip": (.1, -.03, .04)}
        rotation = Rotation.from_euler("x", pitch, degrees=True)
        for name, point in {"spine1": (0., 0., .15), "spine2": (0., 0., .3),
                            "spine3": (0., 0., .4), "neck": (0., 0., .5),
                            "left_collar": (-.1, 0., .4), "right_collar": (.1, 0., .4),
                            "left_shoulder": (-.2, 0., .4), "right_shoulder": (.2, 0., .4)}.items():
            joints[name] = tuple(rotation.apply(point))
        frames.append(MotionFrame(i/30, joints))
    clip = MotionClip(30, list(frames[0].joints), frames)
    result, report = s._align_upper_body_to_horizontal_support(clip, level_shoulders=level_shoulders)
    assert report["applied"]
    for before, after in zip(clip.frames, result.frames):
        for parent, child in s.STRUCTURAL_BONES:
            if parent in before.joints and child in before.joints:
                assert math.dist(before.joints[parent], before.joints[child]) == pytest.approx(
                    math.dist(after.joints[parent], after.joints[child]), abs=1e-10)
        for name in ("pelvis", "left_hip", "right_hip"):
            assert after.joints[name] == before.joints[name]
        assert (after.joints["left_shoulder"][1]+after.joints["right_shoulder"][1])/2 == pytest.approx(-.03)
    _, invariant = s.enforce_final_structural_invariant(clip, result)
    assert invariant["accepted"]


@pytest.mark.parametrize("name", ["Unknown movement", "Cable action", "Bodyweight action"])
def test_loop_requirement_comes_from_completion_contract(name):
    assert 'materialized_loop_bridge_pose_mismatch' in b.FINAL_OUTPUT_HARD_DETERMINISTIC_REJECTION_REASONS
    assert b.exercise_requires_loop_continuity(name, ranking_payload={"exerciseMotionContract": {
        "movementTopology": {"completionMode": "return_to_start"}}})
    assert not b.exercise_requires_loop_continuity(name, ranking_payload={"exerciseMotionContract": {
        "completionMode": "one_way"}})


def test_stale_ranking_cannot_disable_contract_return_requirement(monkeypatch):
    monkeypatch.setattr(b, "exercise_motion_contract_for_review_item", lambda *a: {"requiresReturnToStart": True})
    from types import SimpleNamespace
    assert b.review_item_loop_continuity_required(SimpleNamespace(exercise_name="Arbitrary"),
        b.LoopRanking(1., [], payload={"loopContinuityRequired": False}))


@pytest.mark.parametrize("yaw", [0., 73., 155.])
def test_supported_grip_checks_orientation_not_only_distance(yaw):
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg.equipment_constraints import supported_bilateral_geometry_metrics
    rotation = Rotation.from_euler('xyz', [34., yaw, -20.], degrees=True)
    def payload(left, right):
        joints = dict(zip(('left_shoulder', 'right_shoulder', 'left_hand', 'right_hand'),
                          rotation.apply([[-.2, 0., 0.], [.2, 0., 0.], left, right]).tolist()))
        return {'frames': [{'joints': joints}] * 10}
    valid = payload([-.4, .5, 0.], [.4, .5, 0.])
    # Same 0.8m spacing, incompatible orientation relative to shoulders.
    invalid = payload([0., .5, -.4], [0., .5, .4])
    assert supported_bilateral_geometry_metrics(valid, required=True)['passed']
    assert not supported_bilateral_geometry_metrics(invalid, required=True)['passed']
    assert supported_bilateral_geometry_metrics(invalid, required=False)['passed']


def test_supported_pose_fit_retains_core_and_pair_reference():
    from exercise_motion_pkg.articulation_trajectory import fit_pose_and_temporal_trajectories
    frames = []
    for i in range(8):
        joints = {'pelvis': (0., 0., 0.), 'left_shoulder': (-.2, 0., .5),
                  'right_shoulder': (.2, 0., .5), 'left_hand': (-.4, .5, .5),
                  'right_hand': (.4, .5, .5)}
        frames.append(MotionFrame(i/30, joints))
    clip = MotionClip(30, list(frames[0].joints), frames)
    target = replace(clip, frames=[MotionFrame(f.time_sec, {**f.joints,
        'left_hand': (-.3, .5, .7), 'right_hand': (.3, .5, .3)}) for f in frames])
    fitted, report = fit_pose_and_temporal_trajectories(clip, target,
        (('left_shoulder', 'left_hand'), ('right_shoulder', 'right_hand')),
        rigid_pair=('left_hand', 'right_hand'),
        rigid_pair_reference=('left_shoulder', 'right_shoulder'), max_evaluations=25)
    assert 'rigidPairOrientation' in report['finalObjectiveTerms']
    for frame in fitted.frames:
        assert frame.joints['left_shoulder'] == clip.frames[0].joints['left_shoulder']
        assert abs(frame.joints['left_hand'][2]-frame.joints['right_hand'][2]) < .02


def test_seam_step_bound_detects_small_but_disproportionate_restart():
    from exercise_motion_pkg.loop_seam import seam_errors
    # Slow neighboring motion can have a small absolute velocity residual
    # while its restart step is several times larger than adjacent steps.
    points = np.zeros((4, 1, 3))
    points[:, 0, 0] = [0., .001, -.005, -.004]
    step, excess, velocity = seam_errors(points)
    assert np.max(abs(velocity)) < .006
    assert excess[0] == pytest.approx(.00275)


def test_seam_does_not_require_duplicate_endpoints_for_smooth_cycle():
    from exercise_motion_pkg.loop_seam import seam_errors
    t = np.arange(120) * 2 * np.pi / 120
    points = np.stack((np.sin(t), np.cos(t), np.zeros_like(t)), axis=-1)[:, None, :]
    step, excess, _ = seam_errors(points)
    assert np.linalg.norm(step) > .05
    assert np.max(excess) == pytest.approx(0.)
