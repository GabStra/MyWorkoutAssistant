import math

import numpy as np

from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.structural_refinement import _apply_soft_same_phase_arm_symmetry
from exercise_motion_pkg.temporal_quality import rendered_leg_sides


def test_bilateral_directions_preserve_unequal_limb_lengths():
    joints = {'pelvis': (0, 0, 0), 'neck': (0, 1, 0),
              'left_shoulder': (-.2, 1, 0), 'right_shoulder': (.2, 1, 0),
              'left_elbow': (-.4, .7, 0), 'right_elbow': (.45, .7, .08),
              'left_wrist': (-.4, 1, .1), 'right_wrist': (.5, 1.1, .2),
              'left_hand': (-.4, 1.1, .1), 'right_hand': (.5, 1.2, .2)}
    clip = MotionClip(fps=30, joint_names=list(joints), frames=[MotionFrame(time_sec=0, joints=joints)], metadata={})
    assert _apply_soft_same_phase_arm_symmetry(clip, bilateral_modes={})[0] is clip
    repaired, _ = _apply_soft_same_phase_arm_symmetry(clip, bilateral_modes={'arms': {
        'mode': 'same_phase_symmetric', 'motionDrivenPoseSymmetryAcceptance': {'accepted': True}}})
    out = repaired.frames[0].joints
    for parent, child in [('shoulder', 'elbow'), ('elbow', 'wrist'), ('wrist', 'hand')]:
        directions = []
        for side in ['left', 'right']:
            a, b = side+'_'+parent, side+'_'+child
            v = np.array(out[b])-out[a]
            np.testing.assert_allclose(np.linalg.norm(v), np.linalg.norm(np.array(joints[b])-joints[a]), atol=1e-10)
            directions.append(v/np.linalg.norm(v))
        np.testing.assert_allclose(directions[0]*[-1, 1, 1], directions[1], atol=1e-10)
    assert out['left_shoulder'] == joints['left_shoulder']


def test_near_extended_knee_does_not_follow_noisy_bend_plane():
    frames = []
    for i in range(30):
        angle = i * .45
        frames.append({'joints': {'left_hip': [.08*math.cos(angle), 1, .08*math.sin(angle)],
                                 'left_knee': [0, .5, 0], 'left_ankle': [0, 0, 0],
                                 'left_foot': [0, 0, .2]}})
    sides = rendered_leg_sides(frames)
    first = sides[0]['left_knee->left_ankle']
    for frame in sides:
        np.testing.assert_allclose(frame['left_knee->left_ankle'], first, atol=1e-10)
