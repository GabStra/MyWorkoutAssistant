"""Physical contract tests for the native full-sole articulation reference.

The shared helper ``contact_conditioned_articulation_reference`` turns observed
contact targets into a reference foot vector. For a validated, calibrated
native full-sole episode the rigid sole must keep
``bone_forward . world_normal == soleNormalLocal[forward]`` while preserving the
source tangential heading, bone length, knee and ankle.
"""

import numpy as np

from exercise_motion_pkg.joint_plant_initialization import (
    contact_conditioned_articulation_reference,
)

NAMES = ['left_knee', 'left_ankle', 'left_foot']
KNEE, ANKLE, FOOT = (NAMES.index(name) for name in NAMES)
SOLE_FORWARD = -0.3050124518936397
BONE_LENGTH = 0.13455193128488263


def _unit(vector):
    vector = np.asarray(vector, dtype=float)
    return vector / np.linalg.norm(vector)


def _episode(side, start, end, normal, sole_local):
    return {
        'startFrame': int(start),
        'endFrame': int(end),
        'anchorId': f'{side}:test:toe',
        'regionRole': 'full_sole',
        'mode': 'stationary',
        'primitiveId': f'wearShoe:{side}_ankle->{side}_foot',
        'triangleIndex': 0,
        'barycentric': [1. / 3., 1. / 3., 1. / 3.],
        'materialOffsetLocalMeters': [0.05, 0.0, 0.0],
        'referenceLengthMeters': BONE_LENGTH,
        'surfaceNormal': list(normal),
        'planeOffsetMeters': 0.0,
        'targetWorld': [0.0, 0.0, 0.0],
        'soleNormalLocalMeters': list(sole_local),
    }


def _side_track(side, count, episode):
    return {
        'active': [episode['startFrame'] <= frame <= episode['endFrame']
                   for frame in range(count)],
        'directions': [[0.0, 0.0, 1.0]] * count,
        'sideAxes': [[1.0, 0.0, 0.0]] * count,
        'anchorIds': [episode['anchorId']] * count,
        'episodes': [episode],
    }


def _evidence(states, tracks=None):
    evidence = {
        'footPatchEvidence': {
            'available': True,
            'feet': {'left': {'states': list(states)}},
        },
    }
    if tracks is not None:
        evidence['_nativeFootMaterialTracks'] = tracks
    return evidence


def _reference(count, raw_directions, target_directions=None):
    reference = np.zeros((count, len(NAMES), 3), dtype=float)
    reference[:, KNEE] = np.array([0.0, 0.55, 0.0])
    reference[:, ANKLE] = np.array([0.0, 0.45, 0.0])
    raw = np.asarray(raw_directions, dtype=float)
    reference[:, FOOT] = reference[:, ANKLE] + raw * BONE_LENGTH
    if target_directions is None:
        targets = reference.copy()
    else:
        targets = reference.copy()
        targets[:, FOOT] = reference[:, ANKLE] + np.asarray(
            target_directions, dtype=float) * BONE_LENGTH
    return reference, targets


def _pins(count, toe_values=True):
    pins = np.zeros((count, len(NAMES)), dtype=bool)
    pins[:, FOOT] = toe_values
    return pins


def _qualified_directions(reference, conditioned):
    bone = conditioned[:, FOOT] - conditioned[:, ANKLE]
    return bone / np.linalg.norm(bone, axis=1, keepdims=True)


def _assert_preserved_source(reference, conditioned):
    assert np.array_equal(conditioned[:, KNEE], reference[:, KNEE])
    assert np.array_equal(conditioned[:, ANKLE], reference[:, ANKLE])
    source_length = np.linalg.norm(
        reference[:, FOOT] - reference[:, ANKLE], axis=1)
    result_length = np.linalg.norm(
        conditioned[:, FOOT] - conditioned[:, ANKLE], axis=1)
    assert np.allclose(result_length, source_length, rtol=0., atol=1e-12)


def _tangential_direction(vector, normal):
    vector = np.asarray(vector, dtype=float)
    tangential = vector - np.dot(vector, normal) * normal
    return _unit(tangential)


def test_varying_raw_pitch_is_qualified_and_preserves_heading_knee_ankle_length():
    count = 5
    normal = np.array([0.0, 1.0, 0.0])
    sole_local = np.array([SOLE_FORWARD, 0.0, np.sqrt(1.0 - SOLE_FORWARD ** 2)])
    # Vary both pitch and tangential heading so the test cannot pass by
    # collapsing the heading onto a fixed axis.
    headings = np.array([[1.0, 0.0, 0.0], [0.2, 0.0, 1.0], [0.0, 0.0, 1.0],
                         [-0.5, 0.0, 1.0], [-1.0, 0.0, 0.2]])
    pitches = np.array([-0.55, -0.40, -0.10, 0.15, 0.30])
    raw = []
    for heading, pitch in zip(headings, pitches):
        tangent = _unit(heading - np.dot(heading, normal) * normal)
        raw.append(_unit(tangent * np.sqrt(1.0 - pitch ** 2) + pitch * normal))
    raw = np.asarray(raw)
    reference, targets = _reference(count, raw)
    states = ['full_sole'] * count
    tracks = {'version': 2, 'left': _side_track(
        'left', count, _episode('left', 0, count - 1, normal, sole_local))}

    conditioned, masks, observed, report = contact_conditioned_articulation_reference(
        reference, _pins(count), targets, NAMES,
        _evidence(states, tracks), [None] * count)

    _assert_preserved_source(reference, conditioned)
    qualified = _qualified_directions(reference, conditioned)
    raw_dot = raw @ normal
    result_dot = np.sum(qualified * normal, axis=1)
    assert np.ptp(raw_dot) > 0.5
    assert np.ptp(result_dot) < 1e-12
    assert np.allclose(result_dot, SOLE_FORWARD, rtol=0., atol=1e-12)
    for index in range(count):
        assert np.allclose(_tangential_direction(qualified[index], normal),
                           _tangential_direction(raw[index], normal),
                           rtol=0., atol=1e-9)
    assert np.array_equal(masks['left'], np.ones(count, dtype=bool))
    assert np.array_equal(observed['left'], np.ones(count, dtype=bool))
    side_report = report['sides']['left']
    assert side_report['nativeFullsoleReferenceFrameCount'] == count
    assert side_report['nativeFullsoleFallbackFrameCount'] == 0
    assert side_report['nativeFullsoleMaximumNormalInvariantResidual'] < 1e-12
    assert report['reference'] == (
        'source_shin_with_calibrated_native_full_sole_reference_frame')


def test_inclined_support_plane_uses_episode_world_normal_not_world_up():
    count = 4
    incline = np.deg2rad(20.0)
    normal = _unit([np.sin(incline), np.cos(incline), 0.0])
    sole_local = np.array([-0.21, 0.0, np.sqrt(1.0 - 0.21 ** 2)])
    raw = np.array([_unit([0.4, -0.3, 1.0]), _unit([0.1, 0.2, 1.0]),
                    _unit([-0.6, 0.1, 0.8]), _unit([0.0, -0.2, 1.0])])
    reference, targets = _reference(count, raw)
    states = ['full_sole'] * count
    tracks = {'version': 2, 'left': _side_track(
        'left', count, _episode('left', 0, count - 1, normal, sole_local))}

    conditioned, _, _, report = contact_conditioned_articulation_reference(
        reference, _pins(count), targets, NAMES,
        _evidence(states, tracks), [None] * count)

    _assert_preserved_source(reference, conditioned)
    qualified = _qualified_directions(reference, conditioned)
    assert np.allclose(np.sum(qualified * normal, axis=1), -0.21, rtol=0., atol=1e-12)
    for index in range(count):
        assert np.allclose(_tangential_direction(qualified[index], normal),
                           _tangential_direction(raw[index], normal),
                           rtol=0., atol=1e-9)
    world_up = np.array([0.0, 1.0, 0.0])
    world_up_based = []
    for vector in raw:
        tangent = _unit(vector - np.dot(vector, world_up) * world_up)
        world_up_based.append(
            -0.21 * world_up + np.sqrt(1.0 - 0.21 ** 2) * tangent)
    assert not np.allclose(qualified, np.asarray(world_up_based), rtol=0., atol=1e-6)
    assert report['sides']['left']['nativeFullsoleReferenceFrameCount'] == count


def test_unqualified_rows_keep_legacy_raw_contact_vector_and_masks():
    count = 5
    normal = np.array([0.0, 1.0, 0.0])
    sole_local = np.array([SOLE_FORWARD, 0.0, np.sqrt(1.0 - SOLE_FORWARD ** 2)])
    raw = np.array([_unit([0.2, -0.4, 1.0]), _unit([0.5, -0.2, 1.0]),
                    _unit([-0.3, -0.1, 1.0]), _unit([0.1, 0.0, 1.0]),
                    _unit([-0.6, 0.2, 1.0])])
    target = np.array([_unit([1.0, -0.7, 0.1]), _unit([0.8, -0.5, 0.2]),
                       _unit([0.6, -0.3, 0.3]), _unit([0.4, -0.1, 0.4]),
                       _unit([0.2, 0.1, 0.5])])
    reference, targets = _reference(count, raw, target)
    states = ['full_sole'] * count

    # 1) No validated native track: the whole call keeps the legacy raw target.
    conditional, _, _, legacy_report = contact_conditioned_articulation_reference(
        reference, _pins(count), targets, NAMES,
        _evidence(states), [None] * count)
    expected_legacy_foot = (
        reference[:, ANKLE]
        + (targets[:, FOOT] - targets[:, ANKLE]))
    assert np.allclose(conditional[:, FOOT], expected_legacy_foot, rtol=0., atol=1e-12)
    assert legacy_report['reference'] == (
        'source_shin_with_observed_full_sole_foot_vector')
    assert legacy_report['sides']['left']['nativeFullsoleReferenceFrameCount'] == 0

    # 2) A calibrated episode owns only rows 0..2. Active rows 3..4 must keep the
    # legacy raw contact vector while owned rows satisfy the sole invariant.
    tracks = {'version': 2, 'left': _side_track(
        'left', count, _episode('left', 0, 2, normal, sole_local))}
    conditioned, masks, observed, report = contact_conditioned_articulation_reference(
        reference, _pins(count), targets, NAMES,
        _evidence(states, tracks), [None] * count)

    _assert_preserved_source(reference, conditioned)
    assert np.allclose(conditioned[3:5, FOOT], expected_legacy_foot[3:5],
                       rtol=0., atol=1e-12)
    owned = _qualified_directions(reference, conditioned)[:3]
    assert np.allclose(np.sum(owned * normal, axis=1), SOLE_FORWARD,
                       rtol=0., atol=1e-12)
    assert np.array_equal(masks['left'], np.ones(count, dtype=bool))
    assert np.array_equal(observed['left'], np.ones(count, dtype=bool))
    side_report = report['sides']['left']
    assert side_report['nativeFullsoleOwnedFrameCount'] == 3
    assert side_report['nativeFullsoleReferenceFrameCount'] == 3
    assert side_report['nativeFullsoleUnownedFrameCount'] == 2
    assert side_report['nativeFullsoleFallbackFrameCount'] == 0
