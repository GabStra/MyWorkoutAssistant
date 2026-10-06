import copy

import pytest

from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.structural_refinement import constrain_to_source_articulation_envelope


def leg_clip():
    joints={'pelvis':(0.,0.,0.),'neck':(0.,1.,0.),
        'left_hip':(-.2,0.,0.),'right_hip':(.2,0.,0.),
        'left_shoulder':(-.3,.8,0.),'right_shoulder':(.3,.8,0.),
        'left_knee':(-.2,-.5,0.),'left_ankle':(-.2,-.8,.4),'left_foot':(-.2,-.8,.5)}
    return MotionClip(30.,list(joints),[MotionFrame(i/30.,dict(joints)) for i in range(21)])


def flip_frames(clip):
    for i in (9,10):
        clip.frames[i].joints['left_ankle']=(-.2,-.8,-.4)
        clip.frames[i].joints['left_foot']=(-.2,-.8,-.5)


def test_isolated_source_branch_glitch_is_not_forced_back_into_a_smooth_repair():
    proposed=leg_clip();source=copy.deepcopy(proposed);flip_frames(source)
    repaired,metadata=constrain_to_source_articulation_envelope(source,proposed)
    assert metadata['ignoredUnstableSourceBranchCount']==2
    assert metadata['preventedHingeBranchFlipCount']==0
    assert repaired.frames==proposed.frames


def test_supported_source_branch_still_corrects_a_generated_flip():
    source=leg_clip();proposed=copy.deepcopy(source);flip_frames(proposed)
    repaired,metadata=constrain_to_source_articulation_envelope(source,proposed)
    assert metadata['preventedHingeBranchFlipCount']==2
    for i in (9,10):
        assert repaired.frames[i].joints['left_ankle']==pytest.approx(source.frames[i].joints['left_ankle'])


def test_near_straight_knee_does_not_snap_to_ambiguous_source_branch():
    source = leg_clip()
    for frame in source.frames:
        frame.joints['left_ankle'] = (-.2, -.999, .025)
        frame.joints['left_foot'] = (-.2, -.999, .125)
    proposed = copy.deepcopy(source)
    for frame in proposed.frames:
        frame.joints['left_ankle'] = (-.2, -.999, -.025)
        frame.joints['left_foot'] = (-.2, -.999, .075)
    repaired, metadata = constrain_to_source_articulation_envelope(source, proposed)
    assert metadata['preventedHingeBranchFlipCount'] == 0
    assert repaired.frames == proposed.frames


def test_contact_interval_reset_cannot_teleport_the_body():
    from exercise_motion_pkg.bake_and_rank import apply_source_contact_sequence_correction

    payload = {'fps': 30, 'frames': [
        {'timeSec': i / 30, 'joints': {'pelvis': [i * .02, 1, 0],
                                      'head': [i * .02, 2, 0], 'left_foot': [i * .02, 0, 0]}}
        for i in range(30)]}
    evidence = {'contacts': [
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'confidence': 1., 'startRatio': start / 29, 'endRatio': end / 29,
         'anchorGroupId': str(start)} for start, end in [(0, 14), (15, 29)]]}
    result, metadata = apply_source_contact_sequence_correction(payload, evidence)
    assert metadata['applied'] is False
    assert metadata['reason'] == 'contact_transition_introduces_root_spikes'
    assert result['frames'] == payload['frames']
