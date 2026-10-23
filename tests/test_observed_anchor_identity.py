import copy

import numpy as np
import pytest

from exercise_motion_pkg.contact_constraints import stationary_target_track
from exercise_motion_pkg.contact_constraints import vertical_only_contact_mask
from exercise_motion_pkg.foot_contact_observation import assign_stationary_anchor_groups


@pytest.mark.parametrize('roll', [0., .7])
@pytest.mark.parametrize('pitch,state', [(0., 'full_sole'), (.5, 'heel_only'), (-.5, 'toe_only')])
def test_persistent_foot_pitch_is_measured_against_observed_ground(roll, pitch, state):
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts
    rotation = np.array([[np.cos(roll), -np.sin(roll), 0.],
                         [np.sin(roll), np.cos(roll), 0.], [0., 0., 1.]])
    normal = rotation @ np.array([0., -1., 0.])
    delta = rotation @ np.array([.2 * np.cos(pitch), -.2 * np.sin(pitch), 0.])
    joints = {
        'left_ankle': {'image': [.5, .5], 'world': [0., 0., 0.], 'confidence': .99},
        'left_heel': {'image': [.5, .5], 'world': [0., 0., 0.], 'confidence': .99},
        'left_toe': {'image': (np.array([.5, .5]) + delta[:2]).tolist(),
                     'world': delta.tolist(), 'confidence': .99},
    }
    observations = {'available': True, 'source': 'observed', 'fps': 30.,
                    'frames': [{'timeSeconds': i / 30, 'joints': copy.deepcopy(joints)} for i in range(8)]}
    source = {'frames': [{'sourceTimeSec': i / 30, 'joints': {'left_ankle': [.5, .5]}} for i in range(8)]}
    evidence = {'contacts': [{'jointName': 'left_ankle', 'startRatio': 0., 'endRatio': 1.}]}
    result = classify_foot_contacts(observations, evidence, source, normal.tolist())
    assert result['feet']['left']['states'] == [state] * 8
    assert result['contacts'][0]['minimumLiftRatio'] == pytest.approx(
        0. if pitch == 0. else np.sin(abs(pitch) - np.deg2rad(8)))
    assert result['contacts'][0]['verticalOnly'] == (state == 'heel_only')


@pytest.mark.parametrize('image_height', [360, 640, 960])
def test_heel_lift_uses_pixel_angles_across_image_aspect_ratios(image_height):
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts

    # Identical observed foot geometry on differently sized canvases must
    # impose the same lift constraint. Sizes in the source also support old
    # landmark caches that did not store image dimensions.
    frames = []
    for index in range(12):
        lifted = index >= 6
        joints = {
            'left_ankle': {'image': [320 / 640, 260 / image_height],
                           'world': [0., 0., 0.], 'confidence': .99},
            'left_heel': {'image': [320 / 640, (280 if lifted else 300) / image_height],
                          'world': [0., -.2 if lifted else 0., 0.], 'confidence': .99},
            'left_toe': {'image': [360 / 640, 300 / image_height],
                         'world': [.2, 0., 0.], 'confidence': .99},
        }
        frames.append({'timeSeconds': index / 30, 'joints': joints})
    observations = {'available': True, 'source': 'observed', 'fps': 30., 'frames': frames}
    source = {'imageWidth': 640, 'imageHeight': image_height,
              'frames': [{'sourceTimeSec': frame['timeSeconds'],
                          'joints': {'left_ankle': frame['joints']['left_ankle']['image']}}
                         for frame in frames]}
    evidence = {'contacts': [
        {'jointName': 'left_ankle', 'startFrame': 0, 'endFrame': 5},
        {'jointName': 'left_foot', 'verticalOnly': True, 'startFrame': 6, 'endFrame': 11},
    ]}
    result = classify_foot_contacts(observations, evidence, source)
    assert result['feet']['left']['states'] == ['full_sole'] * 6 + ['toe_only'] * 6
    assert result['contacts'][-1]['minimumLiftRatio'] == pytest.approx(
        np.sin(np.arctan2(20., 40.) - np.deg2rad(8.)))


@pytest.mark.parametrize('scenario,expected', [
    ('stable', 'toe_only'), ('moving_toe', 'unknown'), ('foreshortened', 'unknown'),
])
def test_stable_image_heel_pivot_survives_world_pose_disagreement(scenario, expected):
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts

    frames = []
    for index in range(12):
        lifted = index >= 6
        progress = (index - 6) / 5 if scenario == 'moving_toe' and lifted else 0.
        heel_x = .5
        toe_x = .6 + .04 * progress
        toe_y = .55 + .014 * progress
        if scenario == 'foreshortened' and lifted:
            toe_x = .53
        joints = {
            'left_ankle': {'image': [.5, .5], 'world': [0., 0., 0.], 'confidence': .99},
            'left_heel': {'image': [heel_x, .55 if not lifted else .515],
                          'world': [0., 0., 0.], 'confidence': .99},
            'left_toe': {'image': [toe_x, toe_y], 'world': [.1, 0., 0.], 'confidence': .99},
        }
        frames.append({'timeSeconds': index / 30., 'joints': joints})
    observations = {'available': True, 'source': 'observed', 'fps': 30.,
                    'imageWidth': 640, 'imageHeight': 480, 'frames': frames}
    source = {'imageWidth': 640, 'imageHeight': 480,
              'frames': [{'sourceTimeSec': frame['timeSeconds'],
                          'joints': {'left_ankle': frame['joints']['left_ankle']['image']}}
                         for frame in frames]}
    evidence = {'contacts': [
        {'jointName': 'left_ankle', 'startFrame': 0, 'endFrame': 5},
        {'jointName': 'left_foot', 'supportKind': 'forefoot', 'verticalOnly': True,
         'startFrame': 6, 'endFrame': 11},
    ]}

    result = classify_foot_contacts(observations, evidence, source)

    assert result['feet']['left']['states'][:6] == ['full_sole'] * 6
    assert result['feet']['left']['states'][6:] == [expected] * 6
    assert result['sourceFrameCount'] == 12
    assert result['sourceFps'] == 30.
    assert result['sourceStartTimeSec'] == 0.
    assert result['sourceEndTimeSec'] == pytest.approx(11 / 30.)
    if scenario == 'stable':
        assert result['contacts'][-1]['contactState'] == 'toe_only'
        toe_only_rays = result['feet']['left']['rayObservations'][6:]
        assert len({row['stationaryAnchorGroupId'] for row in toe_only_rays}) == 1
        assert all(row['state'] == 'toe_only' for row in toe_only_rays)


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


def test_ankle_toe_ray_survives_missing_heel_and_uses_absolute_source_time():
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts

    origin = 7.25
    frames = []
    source_frames = []
    for index in range(5):
        ankle = [.45, .70]
        toe = [.57, .72 + .01 * index]
        frames.append({
            'timeSeconds': index / 30.,
            'joints': {
                'left_ankle': {'image': ankle, 'world': [0., 0., 0.], 'confidence': .99},
                'left_heel': {'image': [.45, .74], 'world': [0., 0., 0.], 'confidence': .2},
                'left_toe': {'image': toe, 'world': [.2, 0., 0.], 'confidence': .99},
            },
        })
        source_frames.append({
            'sourceTimeSec': origin + index / 30.,
            'joints': {'left_ankle': ankle},
        })
    result = classify_foot_contacts(
        {'available': True, 'source': 'test', 'fps': 30., 'imageWidth': 640,
         'imageHeight': 480, 'frames': frames},
        {'contacts': []},
        {'sourceTimeOriginSec': origin, 'imageWidth': 640, 'imageHeight': 480,
         'frames': source_frames},
    )

    foot = result['feet']['left']
    assert set(foot['states']) == {'unknown'}
    assert foot['rayObservationCount'] == 5
    assert foot['rayObservations'][0]['sourceTimeSec'] == pytest.approx(origin)
    assert foot['rayObservations'][-1]['sourceTimeSec'] == pytest.approx(origin + 4 / 30.)
    assert foot['rayObservations'][0]['state'] == 'unknown'
    assert foot['rayObservations'][0]['ankleToToeImageRay'][0] == pytest.approx(.12 * 640 / 480)
    assert foot['rayObservations'][-1]['toeImagePoint'][0] == pytest.approx(.57 * 640 / 480)
    assert foot['rayObservations'][-1]['toeImagePoint'][1] > foot['rayObservations'][0]['toeImagePoint'][1]


@pytest.mark.parametrize('foot_pixels', [12., 48.])
@pytest.mark.parametrize('ankle_error_ratio', [.2, .8])
def test_foot_patch_requires_independent_ankle_agreement_at_foot_scale(foot_pixels, ankle_error_ratio):
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts

    width, height = 800, 400
    joints = {
        'left_ankle': {'image': [.5, .8], 'world': [0., 0., 0.], 'confidence': .99},
        'left_heel': {'image': [.5, .9], 'world': [0., 0., 0.], 'confidence': .99},
        'left_toe': {'image': [.5 + foot_pixels / width, .9],
                     'world': [.2, 0., 0.], 'confidence': .99},
    }
    observations = {'available': True, 'source': 'observed', 'fps': 30.,
                    'frames': [{'timeSeconds': i / 30, 'joints': copy.deepcopy(joints)}
                               for i in range(10)]}
    source = {'imageWidth': width, 'imageHeight': height,
              'frames': [{'sourceTimeSec': i / 30,
                          'joints': {'left_ankle': [.5 + ankle_error_ratio * foot_pixels / width, .8]}}
                         for i in range(10)]}
    evidence = {'contacts': [{'jointName': 'left_ankle', 'startRatio': 0., 'endRatio': 1.}]}
    result = classify_foot_contacts(observations, evidence, source)
    expected = 'full_sole' if ankle_error_ratio == .2 else 'unknown'
    assert set(result['feet']['left']['states']) == {expected}
    assert bool(result['contacts']) == (expected == 'full_sole')


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


def test_stationary_toe_anchor_survives_missing_heel_observations():
    from exercise_motion_pkg.foot_contact_observation import assign_stationary_anchor_groups

    contacts = [
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'startFrame': 0, 'endFrame': 4},
        {'jointName': 'left_foot', 'contactState': 'toe_only', 'contactMotion': 'stationary',
         'startFrame': 8, 'endFrame': 12},
    ]
    valid = np.ones(13, dtype=bool)
    valid[5:8] = False  # heel/ankle validity is lost; toe observations remain usable.
    toe_valid = np.ones(13, dtype=bool)
    points = np.full((13, 2), .5)
    states = ['full_sole'] * 5 + ['unknown'] * 3 + ['toe_only'] * 5

    assign_stationary_anchor_groups(
        contacts, side='left', valid=valid, toe_valid=toe_valid,
        toe_points=points, foot_sizes=np.full(13, .05), states=states,
    )

    assert contacts[0]['anchorGroupId'] == contacts[1]['anchorGroupId']


def test_heel_recontact_preserves_toe_prefix_and_stops_at_missing_toe():
    from exercise_motion_pkg.foot_contact_observation import _preserve_heel_release_until_recontact

    states = ['full_sole'] * 4 + ['toe_only'] * 2 + ['unknown'] * 2 + ['full_sole'] * 5
    valid = np.ones(len(states), dtype=bool)
    valid[10] = False  # Heel contact is unresolved from here onward.
    toe_valid = np.ones(len(states), dtype=bool)
    toe_valid[10] = False  # A real toe-observation gap ends the forefoot anchor.
    toe_points = np.tile([.5, .6], (len(states), 1))
    heel_points = np.tile([.5, .5], (len(states), 1))
    heel_points[6:] = [.5, .52]  # Still outside the pre-release stance track.
    foot_sizes = np.full(len(states), .1)
    contacts = [
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'startFrame': 0,
         'endFrame': 3, 'anchorGroupId': 'toe-a'},
        {'jointName': 'left_foot', 'contactState': 'toe_only', 'startFrame': 4,
         'endFrame': 5, 'anchorGroupId': 'toe-a'},
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'startFrame': 8,
         'endFrame': 12, 'anchorGroupId': 'toe-a'},
    ]
    unresolved = np.zeros(len(states), dtype=bool)

    _preserve_heel_release_until_recontact(
        side='left', states=states, contacts=contacts, valid=valid, toe_valid=toe_valid,
        heel_points=heel_points, toe_points=toe_points, foot_sizes=foot_sizes,
        heel_toe_confidence=np.ones(len(states)), image_axes=np.asarray([640., 480.]),
        unresolved_heel_recontact=unresolved,
    )

    assert states[6:10] == ['toe_only'] * 4
    assert states[10:] == ['unknown'] * 3


def test_airborne_gap_starts_a_new_heel_stance_track():
    from exercise_motion_pkg.foot_contact_observation import _preserve_heel_release_until_recontact

    states = ['full_sole'] * 4 + ['toe_only'] * 2 + ['airborne'] * 2 + ['full_sole'] * 4
    valid = np.ones(len(states), dtype=bool)
    toe_valid = np.ones(len(states), dtype=bool)
    toe_points = np.tile([.5, .6], (len(states), 1))
    heel_points = np.tile([.5, .5], (len(states), 1))
    toe_points[8:] = [.7, .6]
    heel_points[8:] = [.7, .5]  # A distinct landing pose, unrelated to the old toe anchor.
    foot_sizes = np.full(len(states), .1)
    contacts = [
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'startFrame': 0,
         'endFrame': 3, 'anchorGroupId': 'toe-a'},
        {'jointName': 'left_foot', 'contactState': 'toe_only', 'startFrame': 4,
         'endFrame': 5, 'anchorGroupId': 'toe-a'},
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'startFrame': 8,
         'endFrame': 11, 'anchorGroupId': 'toe-b'},
    ]
    unresolved = np.zeros(len(states), dtype=bool)

    _preserve_heel_release_until_recontact(
        side='left', states=states, contacts=contacts, valid=valid, toe_valid=toe_valid,
        heel_points=heel_points, toe_points=toe_points, foot_sizes=foot_sizes,
        heel_toe_confidence=np.ones(len(states)), image_axes=np.asarray([640., 480.]),
        unresolved_heel_recontact=unresolved,
    )

    assert states[6:8] == ['airborne'] * 2
    assert states[8:] == ['full_sole'] * 4


@pytest.mark.parametrize('same_ankle,toe_returned,gap_state', [
    (True, True, 'unknown'), (False, True, 'unknown'),
    (True, False, 'unknown'), (True, True, 'airborne'),
])
def test_independent_stance_and_observed_sole_return_resolve_missing_toe_gap(same_ankle, toe_returned, gap_state):
    contacts = [
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'startFrame': 0, 'endFrame': 4, 'ankleAnchorGroupId': 'ankle-a'},
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'startFrame': 8, 'endFrame': 12, 'ankleAnchorGroupId': 'ankle-a' if same_ankle else 'ankle-b'},
    ]
    valid = np.ones(13, dtype=bool)
    valid[5:8] = gap_state != 'unknown'
    points = np.full((13, 2), .5)
    points[5:8] = 0.
    if not toe_returned:
        points[8:, 0] += .04
    states = ['full_sole'] * 5 + [gap_state] * 3 + ['full_sole'] * 5
    assign_stationary_anchor_groups(contacts, side='left', valid=valid, toe_points=points,
                                    foot_sizes=np.full(13, .05), states=states)
    assert (contacts[0]['anchorGroupId'] == contacts[1]['anchorGroupId']) == (
        same_ankle and toe_returned and gap_state != 'airborne')
    from exercise_motion_pkg.sequence_stabilization import contact_mask
    mask = contact_mask({'sourceFootSupportEvidence': {'contacts': contacts}},
                        ['left_ankle', 'left_foot'], 13)
    assert not mask[5:8].any()


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
    height_only = vertical_only_contact_mask(
        result, ['left_ankle', 'left_foot'], 20,
    )
    assert not height_only[10:, 1].any()
    assert not height_only[10:, 0].any()
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


def test_image_only_heel_pivot_is_annotated_as_phase_without_fake_height():
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts

    frames = []
    for index in range(20):
        heel_pivot = index >= 10
        ankle_y = .77 if heel_pivot else .8
        heel_y = .86 if heel_pivot else .9
        frames.append({'timeSeconds': index / 30., 'joints': {
            'left_ankle': {'image': [.5, ankle_y], 'world': [0., 0., 0.],
                           'confidence': .99},
            'left_heel': {'image': [.5, heel_y], 'world': [0., -.1, 0.],
                          'confidence': .99},
            'left_toe': {'image': [.6, .9], 'world': [.2, -.1, 0.],
                         'confidence': .99},
        }})
    observations = {'available': True, 'source': 'observed', 'fps': 30.,
                    'frames': frames}
    source = {'frames': [
        {'sourceTimeSec': index / 30., 'joints': {'left_ankle': [.5, .8]}}
        for index in range(20)
    ]}
    evidence = {'contacts': [{'jointName': 'left_ankle', 'startFrame': 0,
                              'endFrame': 19}]}

    result = classify_foot_contacts(observations, evidence, source, [0., -1., 0.])
    pivot = next(contact for contact in result['contacts']
                 if contact['contactState'] == 'toe_only')
    assert pivot['minimumLiftRatio'] == 0.
    assert pivot['heelPhaseEvidence'] == {
        'source': 'image_only_toe_pitch', 'worldHeightResolved': False,
    }


def test_full_sole_recontact_waits_for_heel_to_return_to_its_stance_track():
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts

    frames = []
    for index in range(16):
        if index < 6 or index >= 13:
            heel_y = .55
        elif index < 10:
            heel_y = .51  # clear toe pivot
        else:
            heel_y = .54  # neutral within the angle band, but not back at stance
        joints = {
            'left_ankle': {'image': [.5, .5], 'world': [0., 0., 0.], 'confidence': .99},
            'left_heel': {'image': [.5, heel_y], 'world': [0., 0., 0.], 'confidence': .99},
            'left_toe': {'image': [.6, .55], 'world': [.2, 0., 0.], 'confidence': .99},
        }
        frames.append({'timeSeconds': index / 30., 'joints': joints})
    observations = {'available': True, 'source': 'observed', 'fps': 30.,
                    'imageWidth': 640, 'imageHeight': 480, 'frames': frames}
    source = {'imageWidth': 640, 'imageHeight': 480,
              'frames': [{'sourceTimeSec': frame['timeSeconds'],
                          'joints': {'left_ankle': frame['joints']['left_ankle']['image']}}
                         for frame in frames]}
    evidence = {'contacts': [
        {'jointName': 'left_ankle', 'contactMotion': 'stationary',
         'startFrame': 0, 'endFrame': 5},
        {'jointName': 'left_foot', 'supportKind': 'forefoot', 'contactMotion': 'stationary',
         'verticalOnly': True, 'startFrame': 6, 'endFrame': 12},
        {'jointName': 'left_ankle', 'contactMotion': 'stationary',
         'startFrame': 13, 'endFrame': 15},
    ]}

    result = classify_foot_contacts(observations, evidence, source)

    states = result['feet']['left']['states']
    assert states[:6] == ['full_sole'] * 6
    assert states[6:13] == ['toe_only'] * 7
    assert states[13:] == ['full_sole'] * 3
    contacts = result['contacts']
    assert all(not contact.get('ankleAnchorGroupId') for contact in contacts
               if contact['contactState'] == 'toe_only')


def test_heel_image_observations_do_not_require_ankle_identity():
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts

    frames = []
    for index in range(4):
        frames.append({'timeSeconds': index / 30., 'joints': {
            'left_ankle': {'image': [.5, .5], 'world': [0., 0., 0.], 'confidence': .2},
            'left_heel': {'image': [.5, .55], 'world': [0., 0., 0.], 'confidence': .99},
            'left_toe': {'image': [.6, .55], 'world': [.2, 0., 0.], 'confidence': .98},
        }})
    source = {'imageWidth': 640, 'imageHeight': 480,
              'frames': [{'sourceTimeSec': frame['timeSeconds'],
                          'joints': {'left_ankle': [.5, .5]}}
                         for frame in frames]}

    result = classify_foot_contacts(
        {'available': True, 'source': 'observed', 'fps': 30., 'imageWidth': 640,
         'imageHeight': 480, 'frames': frames}, {'contacts': []}, source,
    )

    foot = result['feet']['left']
    assert foot['rayObservationCount'] == 0
    assert len(foot['heelImageObservations']) == 4
    assert foot['heelImageObservations'][0]['sourceTimeSec'] == pytest.approx(0.)
    assert foot['heelImageObservations'][0]['heelImagePoint'] == pytest.approx([.5 * 640 / 480, .55])
    assert foot['heelImageObservations'][0]['heelConfidence'] == pytest.approx(.99)
    assert all(row['state'] == 'unknown' for row in foot['heelImageObservations'])


@pytest.mark.parametrize('failure', [None, 'different_video', 'moving_toe', 'wrong_ankle'])
def test_uncalibrated_visible_contact_requires_matching_video_and_independent_still_toe(failure):
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts
    from exercise_motion_pkg.sequence_stabilization import contact_mask
    joints = {
        'left_ankle': {'image': [.5, .8], 'world': [0., 0., 0.], 'confidence': .99},
        'left_heel': {'image': [.5, .9], 'world': [0., 0., 0.], 'confidence': .99},
        'left_toe': {'image': [.6, .9], 'world': [.2, 0., 0.], 'confidence': .99},
    }
    observations = {'available': True, 'source': 'observed', 'fps': 30., 'sourceVideoSha256': 'same',
                    'frames': [{'timeSeconds': i / 30., 'joints': copy.deepcopy(joints)} for i in range(12)]}
    source = {'frames': [{'sourceTimeSec': i / 30., 'joints': {'left_ankle': [.5, .8]}}
                         for i in range(12)]}
    evidence = {'contacts': [], 'bodySupportObservation': {
        'status': 'observed', 'sourceVideoSha256': 'other' if failure == 'different_video' else 'same',
        'observation': {'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground'}}}
    if failure == 'moving_toe':
        observations['frames'][6]['joints']['left_toe']['image'][0] += .04
    if failure == 'wrong_ankle':
        for frame in source['frames']:
            frame['joints']['left_ankle'][0] = .4
    result = classify_foot_contacts(observations, evidence, source)
    mask = contact_mask({'sourceFootSupportEvidence': result}, ['left_ankle', 'left_foot'], 12)
    if failure:
        assert not result['contacts'] and not mask.any()
    else:
        assert mask[:, 1].all() and not mask[:, 0].any()
        assert result['contacts'][0]['minimumLiftRatio'] == 0.
        assert result['contacts'][0]['source'] == 'exact_visual_contact_and_independent_stationary_toe'
        assert result['feet']['left']['pitchReferenceSource'] == 'heel_unobserved'


@pytest.mark.parametrize(
    'states,expected_pins,continuous',
    [
        (['full_sole', 'unknown', 'unknown', 'full_sole'], [False] * 4, False),
        (
            ['unknown', 'unknown', 'airborne', 'airborne', 'airborne', 'unknown', 'unknown'],
            [False] * 7,
            False,
        ),
        (
            ['full_sole', 'full_sole', 'unknown', 'unknown', 'airborne', 'airborne',
             'airborne', 'full_sole', 'full_sole', 'unknown', 'unknown', 'full_sole', 'full_sole'],
            [True, True, False, False, False, False, False, True, True, False, False, True, True],
            False,
        ),
    ],
    ids=['unknown-patch-does-not-authorize-source-stance', 'airborne-unknown-patches-stay-unresolved',
         'mixed-unknown-airborne-only-keeps-confirmed-sole'],
)
def test_foot_patch_merge_preserves_source_support_unless_airborne_is_observed(
    monkeypatch, states, expected_pins, continuous,
):
    import exercise_motion_pkg.foot_contact_observation as foot_observation
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    source_evidence = {
        'contacts': [{'jointName': 'left_ankle', 'startFrame': 0, 'endFrame': len(states) - 1}],
        'feet': {
            'left': {
                'jointName': 'left_ankle',
                'continuousSupport': True,
                'confidence': 0.9,
            },
        },
    }
    patch_evidence = {
        'available': True,
        'contacts': [],
        'feet': {'left': {'states': states}},
    }
    monkeypatch.setattr(
        foot_observation,
        'classify_foot_contacts',
        lambda *_args, **_kwargs: copy.deepcopy(patch_evidence),
    )

    merged = foot_observation.add_observed_foot_contacts(
        source_evidence,
        {'available': True},
        {'frames': []},
    )

    assert merged['feet']['left']['continuousSupport'] is continuous
    mask = contact_mask(
        {'sourceFootSupportEvidence': merged},
        ['left_ankle'],
        len(states),
    )[:, 0]
    assert mask.tolist() == expected_pins


def test_foot_patch_airborne_does_not_promote_sliding_source_support_to_stationary_contact(monkeypatch):
    import exercise_motion_pkg.foot_contact_observation as foot_observation
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    source_evidence = {
        'contacts': [{'jointName': 'left_ankle', 'startFrame': 0, 'endFrame': 4}],
        'feet': {
            'left': {
                'jointName': 'left_ankle',
                'continuousSupport': True,
                'contactMotion': 'sliding',
                'confidence': 0.9,
            },
        },
    }
    patch_evidence = {
        'available': True,
        'contacts': [],
        'feet': {'left': {'states': ['unknown', 'unknown', 'airborne', 'unknown', 'unknown']}},
    }
    monkeypatch.setattr(
        foot_observation,
        'classify_foot_contacts',
        lambda *_args, **_kwargs: copy.deepcopy(patch_evidence),
    )

    merged = foot_observation.add_observed_foot_contacts(
        source_evidence,
        {'available': True},
        {'frames': []},
    )

    assert merged['feet']['left']['continuousSupport'] is True
    assert not contact_mask(
        {'sourceFootSupportEvidence': merged},
        ['left_ankle'],
        5,
    ).any()


def test_vertical_only_contact_targets_hold_height_and_leave_tangent_free():
    from exercise_motion_pkg.rig_playback import rig_contact_targets
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    names = ['left_ankle', 'left_foot', 'right_ankle', 'right_foot']
    points = np.zeros((8, len(names), 3), dtype=float)
    points[:, names.index('left_foot'), 0] = np.linspace(-.2, .2, 8)
    points[:, names.index('left_foot'), 1] = .03
    points[:, names.index('left_foot'), 2] = np.linspace(.1, -.1, 8)
    evidence = {
        'contacts': [{
            'jointName': 'left_foot',
            'supportKind': 'observed_foot_patch',
            'surfaceKind': 'ground',
            'contactState': 'toe_only',
            'contactMotion': 'stationary',
            'verticalOnly': True,
            'startFrame': 2,
            'endFrame': 5,
        }],
    }

    pinned = contact_mask({'sourceFootSupportEvidence': evidence}, names, len(points))
    targets, _ = rig_contact_targets(
        points, names, pinned, np.zeros((len(names), 3)), evidence=evidence, floor=0.,
    )

    assert not pinned[:, names.index('left_foot')].any()
    np.testing.assert_allclose(targets[2:6, names.index('left_foot'), 1], 0.)
    np.testing.assert_allclose(
        targets[2:6, names.index('left_foot'), [0, 2]],
        points[2:6, names.index('left_foot'), [0, 2]],
    )
