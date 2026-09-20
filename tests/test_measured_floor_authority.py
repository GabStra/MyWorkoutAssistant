import pytest

from exercise_motion_pkg.cleanup import clip_preserves_video_floor_orientation
from exercise_motion_pkg.models import MotionClip
from exercise_motion_pkg.preview import _clip_has_authoritative_video_floor_alignment


@pytest.mark.parametrize('policy,applied,expected', [
    ('measured_floor_leveling_without_body_fit', True, True),
    ('measured_floor_leveling_without_body_fit', False, False),
    ('tier2_unidepth_floor_distance_pitch', True, True),
    ('unknown', True, False),
])
def test_cleanup_and_preview_agree_on_measured_floor(policy, applied, expected):
    clip = MotionClip(fps=30., joint_names=[], frames=[], metadata={
        'videoWorldAlignment': {'policy': policy, 'applied': applied,
                               'rejectedBodyFit': True},
    })
    assert clip_preserves_video_floor_orientation(clip) is expected
    assert _clip_has_authoritative_video_floor_alignment(clip) is expected


def test_rigid_support_alignment_prevents_floor_pins_from_stretching_thighs():
    import math
    from exercise_motion_pkg.models import MotionFrame
    from exercise_motion_pkg.cleanup import (
        lock_support_pair_midpoint_rigidly, lock_planted_support_joints,
    )
    from exercise_motion_pkg.render_geometry import support_joint_height_for_surface

    joints = {'pelvis': (0., .5, 0.),
              'left_hip': (-.1, .45, 0.), 'right_hip': (.1, .45, 0.),
              'left_knee': (-.15, .03, .15), 'right_knee': (.15, .07, .15),
              'left_ankle': (-.15, .08, .5), 'right_ankle': (.15, .12, .5)}
    clip = MotionClip(fps=30., joint_names=list(joints), frames=[
        MotionFrame(i / 30., {n: (p[0] + i * .01, p[1], p[2])
                              for n, p in joints.items()}) for i in range(4)])
    aligned, _ = lock_support_pair_midpoint_rigidly(
        clip, left_joint_names=['left_knee'], right_joint_names=['right_knee'])
    locked, _ = lock_planted_support_joints(aligned, ['left_knee', 'right_knee'])
    for before, after in zip(clip.frames, locked.frames):
        for side in ('left', 'right'):
            hip, knee = side + '_hip', side + '_knee'
            assert after.joints[knee][1] == pytest.approx(support_joint_height_for_surface(0.))
            assert math.dist(after.joints[hip], after.joints[knee]) == pytest.approx(
                math.dist(before.joints[hip], before.joints[knee]), abs=1e-12)


def test_core_support_repair_preserves_lengths_and_planted_endpoints():
    import math
    from dataclasses import replace
    from exercise_motion_pkg.models import MotionFrame
    from exercise_motion_pkg.cleanup import restore_bilateral_support_chain_lengths

    joints = {'pelvis': (0., .5, 0.), 'head': (0., 1., 0.),
              'left_hip': (-.1, .5, 0.), 'right_hip': (.1, .5, 0.),
              'left_knee': (-.15, 0., .1), 'right_knee': (.15, 0., .1),
              'left_ankle': (-.15, 0., .4), 'right_ankle': (.15, 0., .4)}
    reference = MotionClip(30., list(joints), [MotionFrame(0., joints)])
    displaced = dict(joints, left_knee=(-.17, 0., .1), right_knee=(.17, 0., .1))
    clip = replace(reference, frames=[MotionFrame(0., displaced)])
    pairs = (('left_hip', 'left_knee'), ('right_hip', 'right_knee'))
    repaired, report = restore_bilateral_support_chain_lengths(
        clip, reference, parent_support_pairs=pairs)
    assert report['applied']
    result = repaired.frames[0].joints
    for parent, support in pairs:
        assert result[support] == displaced[support]
        assert math.dist(result[parent], result[support]) == pytest.approx(
            math.dist(joints[parent], joints[support]), abs=1e-12)
    for a, b in [('left_hip', 'right_hip'), ('pelvis', 'head')]:
        assert math.dist(result[a], result[b]) == pytest.approx(math.dist(joints[a], joints[b]))
    assert result['left_ankle'] == joints['left_ankle']
    impossible = replace(clip, frames=[MotionFrame(0., dict(displaced, right_knee=(5., 0., 0.)))])
    unchanged, report = restore_bilateral_support_chain_lengths(
        impossible, reference, parent_support_pairs=pairs)
    assert not report['applied']
    assert unchanged is impossible
    symmetric = dict(joints, left_knee=(-.1, 0., 0.), right_knee=(.1, 0., 0.))
    symmetric_clip = replace(reference, frames=[MotionFrame(0., symmetric)])
    repaired, report = restore_bilateral_support_chain_lengths(
        symmetric_clip, symmetric_clip, parent_support_pairs=pairs)
    assert report['applied']
    assert repaired.frames[0].joints == symmetric
