import math

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.articulation_trajectory import fit_chain_rotations
from exercise_motion_pkg.foot_kinematics import solve_rigid_foot_contacts, stabilize_rigid_feet
from exercise_motion_pkg.limb_bend_repair import repair_limb_bend_bursts
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.physics_bundle import _smooth_reference_clip


def _assert_source_clock_preserved(before, after):
    assert len(after.frames) == len(before.frames)
    assert [
        (frame.source_time_sec, frame.source_frame_index) for frame in after.frames
    ] == [
        (frame.source_time_sec, frame.source_frame_index) for frame in before.frames
    ]


def _timed_frame(index, fps, joints):
    return MotionFrame(
        time_sec=index / fps,
        joints=joints,
        source_time_sec=2.25 + index / fps,
        source_frame_index=80 + index,
    )


def test_frame_preserving_motion_clones_keep_native_source_clock():
    fps = 30.

    arm_frames = []
    for index, angle in enumerate((0., 0., 0., 45., 0., 0., 0.)):
        rotation = Rotation.from_euler('z', angle, degrees=True)
        shoulder = np.array([0., 1., 0.])
        elbow = shoulder + rotation.apply([.3, -.3, 0.])
        wrist = elbow + rotation.apply([.3, -.1, 0.])
        hand = wrist + rotation.apply([.1, 0., 0.])
        joints = {'pelvis': (0., .5, 0.), 'head': (0., 1.5, 0.)}
        joints.update({name: tuple(float(v) for v in point) for name, point in zip(
            ('left_shoulder', 'left_elbow', 'left_wrist', 'left_hand'),
            (shoulder, elbow, wrist, hand),
        )})
        arm_frames.append(_timed_frame(index, fps, joints))
    arm_clip = MotionClip(fps, list(arm_frames[0].joints), arm_frames)
    fitted_arm = fit_chain_rotations(
        arm_clip, ('left_shoulder', 'left_elbow', 'left_wrist', 'left_hand'))
    _assert_source_clock_preserved(arm_clip, fitted_arm)

    foot_frames = []
    for index, angle in enumerate(np.linspace(-.1, .1, 5)):
        ankle = np.array([0., 0., 0.])
        direction = Rotation.from_euler('y', angle).apply([0., 0., .2])
        foot_frames.append(_timed_frame(index, fps, {
            'left_ankle': tuple(ankle),
            'left_foot': tuple(ankle + direction),
        }))
    foot_clip = MotionClip(fps, list(foot_frames[0].joints), foot_frames)
    stabilized, _ = stabilize_rigid_feet(foot_clip)
    _assert_source_clock_preserved(foot_clip, stabilized)

    contact_joints = {
        'left_hip': (0., .8, 0.), 'left_knee': (0., .4, .1),
        'left_ankle': (0., 0., 0.), 'left_foot': (0., 0., .2),
    }
    contact_frames = [_timed_frame(index, fps, dict(contact_joints)) for index in range(5)]
    contact_clip = MotionClip(fps, list(contact_joints), contact_frames)
    fitted_contact, contact_report = solve_rigid_foot_contacts(contact_clip, {'contacts': [{
        'jointName': 'left_foot', 'startRatio': 0., 'endRatio': 1.,
        'contactState': 'full_sole', 'contactMotion': 'stationary',
    }]})
    assert contact_report['applied']
    _assert_source_clock_preserved(contact_clip, fitted_contact)

    limb_frames = []
    for index in range(20):
        angle = math.radians(150. if 7 <= index < 9 else 0.)
        joints = {
            'pelvis': (0., 1., 0.), 'neck': (0., 2., 0.),
            'left_shoulder': (-.25, 1.8, 0.), 'right_shoulder': (.25, 1.8, 0.),
            'left_hip': (0., 0., 0.),
            'left_knee': (.5 * math.cos(angle), .5 * math.sin(angle), .5),
            'left_ankle': (0., 0., 1.),
        }
        limb_frames.append(_timed_frame(index, fps, joints))
    limb_clip = MotionClip(fps, list(limb_frames[0].joints), limb_frames)
    repaired_limb, limb_report = repair_limb_bend_bursts(limb_clip)
    assert limb_report['applied']
    _assert_source_clock_preserved(limb_clip, repaired_limb)

    reference_clip = _smooth_reference_clip(
        contact_clip, window=3, root_joint='left_hip', root_window=5)
    _assert_source_clock_preserved(contact_clip, reference_clip)
