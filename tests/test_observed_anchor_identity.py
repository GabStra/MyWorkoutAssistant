import copy

import numpy as np
import pytest

from exercise_motion_pkg.contact_constraints import stationary_target_track
from exercise_motion_pkg.foot_contact_observation import assign_stationary_anchor_groups


@pytest.mark.parametrize('toe_y', [.9, 1.02, float('nan')])
def test_contact_requires_landmarks_inside_observed_image(toe_y):
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts
    joints = {
        'left_ankle': {'image': [.5, .8], 'world': [0., 0., 0.], 'confidence': .99},
        'left_heel': {'image': [.5, .9], 'world': [0., 0., 0.], 'confidence': .99},
        'left_toe': {'image': [.6, toe_y], 'world': [.2, 0., 0.], 'confidence': .99},
    }
    observations = {'available': True, 'source': 'observed', 'fps': 30.,
        'frames': [{'timeSeconds': i / 30, 'joints': copy.deepcopy(joints)} for i in range(10)]}
    source = {'frames': [{'sourceTimeSec': i / 30, 'joints': {'left_ankle': [.5, .8]}}
                         for i in range(10)]}
    evidence = {'contacts': [{'jointName': 'left_ankle', 'startRatio': 0., 'endRatio': 1.}]}
    result = classify_foot_contacts(observations, evidence, source)
    assert bool(result['contacts']) == (toe_y == .9)
    if toe_y != .9:
        assert set(result['feet']['left']['states']) == {'unknown'}


@pytest.mark.parametrize('gap', ['stationary', 'missing', 'moving', 'airborne'])
def test_only_continuously_observed_stationary_toe_links_contact_states(gap):
    contacts = [
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary', 'startFrame': 0, 'endFrame': 4},
        {'jointName': 'left_foot', 'contactState': 'toe_only', 'contactMotion': 'stationary', 'startFrame': 8, 'endFrame': 12},
    ]
    original = copy.deepcopy(contacts)
    valid = np.ones(13, dtype=bool)
    points = np.full((13, 2), .5)
    states = ['full_sole'] * 5 + ['unknown'] * 3 + ['toe_only'] * 5
    if gap == 'missing':
        valid[6] = False
    elif gap == 'moving':
        points[6, 0] += .08
    elif gap == 'airborne':
        states[6] = 'airborne'
    assign_stationary_anchor_groups(contacts, side='left', valid=valid,
                                    toe_points=points, foot_sizes=np.full(13, .05), states=states)
    assert (contacts[0]['anchorGroupId'] == contacts[1]['anchorGroupId']) == (gap == 'stationary')
    # Linking endpoint anchors does not label the uncertain gap as contact.
    assert [{k: v for k, v in c.items() if k != 'anchorGroupId'} for c in contacts] == original


def test_shared_anchor_does_not_fix_unobserved_gap_frames():
    points = np.column_stack([np.linspace(0., .2, 30), np.zeros(30), np.zeros(30)])
    points[12:17, 1] = .3
    mask = np.ones(30, dtype=bool)
    mask[12:17] = False
    ids = np.full(30, 'same-observed-toe', dtype=object)
    ids[~mask] = None
    fitted, _ = stationary_target_track(points, mask, fps=30., anchor_ids=ids)
    np.testing.assert_allclose(fitted[0], fitted[-1], atol=1e-12)
    assert not np.allclose(fitted[14], fitted[0])


def test_neutral_pitch_does_not_promote_forefoot_evidence_to_an_ankle_lock():
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    joints = {
        'left_ankle': {'image': [.5, .8], 'world': [0., 0., 0.], 'confidence': .99},
        'left_heel': {'image': [.5, .9], 'world': [0., 0., 0.], 'confidence': .99},
        'left_toe': {'image': [.6, .9], 'world': [.2, 0., 0.], 'confidence': .99},
    }
    observations = {'available': True, 'source': 'observed', 'fps': 30.,
        'frames': [{'timeSeconds': i/30, 'joints': copy.deepcopy(joints)} for i in range(20)]}
    source = {'frames': [{'sourceTimeSec': i/30, 'joints': {'left_ankle': [.5, .8]}}
                         for i in range(20)]}
    evidence = {'contacts': [
        {'jointName': 'left_ankle', 'startFrame': 0, 'endFrame': 9},
        {'jointName': 'left_foot', 'supportKind': 'forefoot', 'verticalOnly': True,
         'startFrame': 10, 'endFrame': 19}]}
    result = classify_foot_contacts(observations, evidence, source)
    mask = contact_mask({'sourceFootSupportEvidence': result}, ['left_ankle', 'left_foot'], 20)
    assert mask[:10].all()
    assert mask[10:, 1].all()
    assert not mask[10:, 0].any()
    assert result['contacts'][-1]['minimumLiftRatio'] == 0.
    assert result['contacts'][0].get('ankleAnchorGroupId')
    assert not result['contacts'][-1].get('ankleAnchorGroupId')

    # Unknown heel observations split patches but cannot change the identity
    # of an independently observed stationary ankle stance.
    evidence['contacts'] = [{'jointName': 'left_ankle', 'startFrame': 0, 'endFrame': 19}]
    for frame in observations['frames'][8:12]:
        frame['joints']['left_heel']['confidence'] = .1
    result = classify_foot_contacts(observations, evidence, source)
    assert len(result['contacts']) == 2
    assert result['contacts'][0]['ankleAnchorGroupId'] == result['contacts'][1]['ankleAnchorGroupId']
    mask = contact_mask({'sourceFootSupportEvidence': result}, ['left_ankle', 'left_foot'], 20)
    assert not mask[8:12].any()
