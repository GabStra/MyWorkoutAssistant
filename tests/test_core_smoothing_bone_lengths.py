import math

import pytest

from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.structural_refinement import _stabilize_core_temporal_continuity


def moving_clip(with_leg):
    frames = []
    for index in range(15):
        x = .08 * math.sin(index * 1.5)
        joints = {"pelvis": (x, 1., 0.), "spine1": (x, 1.2, 0.)}
        if with_leg:
            joints.update(right_hip=(x + .1, 1., 0.), right_knee=(x + .1, .6, 0.))
        frames.append(MotionFrame(index / 30, joints))
    return MotionClip(fps=30., joint_names=list(frames[0].joints), frames=frames)


def test_core_smoothing_cannot_stretch_attached_thigh():
    clip = moving_clip(with_leg=True)
    retained, audit = _stabilize_core_temporal_continuity(clip)
    assert audit["jerkProposed"] == audit["jerkBefore"]
    assert not audit["applied"]
    assert audit["reason"] == "core_jerk_not_improved"
    assert not audit["proposedBoneLengthChanges"]
    assert audit["reducedCorrectionFrameCount"] == clip.frame_count
    assert retained.frames == clip.frames


def test_rigid_core_translation_can_still_be_smoothed():
    clip = moving_clip(with_leg=False)
    retained, audit = _stabilize_core_temporal_continuity(clip)
    assert audit["applied"]
    assert audit["jerkProposed"] < audit["jerkBefore"]
    for frame in retained.frames:
        assert math.dist(frame.joints["pelvis"], frame.joints["spine1"]) == pytest.approx(.2)
