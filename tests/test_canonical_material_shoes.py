import copy

import numpy as np
import pytest

from exercise_motion_pkg.foot_geometry import (
    canonical_material_shoe_evidence, shoe_orientation_tracks,
)


def _producer_case(*, legs='mirrored', right_states=('unknown', 'unknown', 'unknown')):
    names = ['left_hip', 'right_hip', 'left_ankle', 'left_foot',
             'right_ankle', 'right_foot']
    points = np.zeros((3, len(names), 3))
    points[:, names.index('left_hip')] = [-.11, 1., .02]
    points[:, names.index('right_hip')] = [.13, 1., -.01]
    points[:, names.index('left_ankle')] = [-.08, .10, .05]
    points[:, names.index('left_foot')] = [-.08, .08, .25]
    points[:, names.index('right_ankle')] = [.14, .10, .03]
    points[:, names.index('right_foot')] = [.14, .08, .23]
    frames = [
        {'joints': dict(zip(names, row.tolist()))} for row in points
    ]
    evidence = {
        'contacts': [{
            'jointName': 'left_foot', 'contactState': 'full_sole',
            'contactMotion': 'stationary', 'surfaceKind': 'ground',
            'startFrame': 0, 'endFrame': 2,
        }],
        'footPatchEvidence': {'available': True, 'feet': {
            'left': {'states': ['full_sole'] * 3},
            'right': {'states': list(right_states)},
        }},
        '_fitFrameFootPatchStatesBySide': {
            'left': ['full_sole'] * 3,
            'right': list(right_states),
        },
    }
    payload = {
        'frames': frames,
        'jointNames': names,
        'sourceFootSupportEvidence': evidence,
        'renderFloorY': 0.,
        'groundContactMode': 'continuous',
        'footRestPitchRadians': {'left': 0., 'right': 0.},
        'canonicalExecution': {'legs': legs},
    }
    return payload, points, evidence


def _expected_mirror(points, names, track):
    lateral = (points[:, names.index('right_hip')]
               - points[:, names.index('left_hip')])
    lateral /= np.linalg.norm(lateral, axis=1, keepdims=True)
    forward = track['forward'] - 2 * np.sum(
        track['forward'] * lateral, axis=1, keepdims=True) * lateral
    side = -(track['side'] - 2 * np.sum(
        track['side'] * lateral, axis=1, keepdims=True) * lateral)
    forward /= np.linalg.norm(forward, axis=1, keepdims=True)
    side /= np.linalg.norm(side, axis=1, keepdims=True)
    return forward, side


@pytest.mark.parametrize('right_states', [
    ('unknown', 'unknown', 'unknown'),
    ('full_sole', 'full_sole', 'full_sole'),
])
def test_single_observed_shoe_fills_unknown_or_unresolved_counterpart(right_states):
    payload, points, evidence = _producer_case(right_states=right_states)
    source_evidence = copy.deepcopy(evidence)
    source_points = points.copy()

    tracks = shoe_orientation_tracks(payload, points)

    assert set(tracks) == {'left', 'right'}
    expected_forward, expected_side = _expected_mirror(
        points, payload['jointNames'], tracks['left'])
    np.testing.assert_allclose(tracks['right']['forward'], expected_forward)
    np.testing.assert_allclose(tracks['right']['side'], expected_side)
    assert tracks['right']['contactMask'].tolist() == [False, False, False]
    assert tracks['right']['modelMirroredFrom'] == 'left'
    assert 'modelMirroredFrom' not in tracks['left']
    # The inferred side carries no observed labels or contact facts.
    assert set(tracks['right']) == {'forward', 'side', 'contactMask',
                                    'modelMirroredFrom'}
    np.testing.assert_array_equal(points, source_points)
    assert payload['sourceFootSupportEvidence'] == source_evidence


@pytest.mark.parametrize('contrary', ['toe_only', 'heel_only', 'airborne'])
def test_known_contrary_counterpart_is_never_overwritten(contrary):
    payload, points, _ = _producer_case(
        right_states=('unknown', contrary, 'unknown'))

    tracks = shoe_orientation_tracks(payload, points)

    assert set(tracks) == {'left'}


def test_unconstrained_legs_do_not_fill_the_missing_shoe():
    payload, points, _ = _producer_case(legs='unconstrained')

    tracks = shoe_orientation_tracks(payload, points)

    assert set(tracks) == {'left'}


_MATERIAL_NAMES = [
    'left_hip', 'right_hip', 'left_knee', 'right_knee',
    'left_ankle', 'left_foot', 'right_ankle', 'right_foot',
    'left_shoulder', 'right_shoulder',
]


def _reflect_x(vector):
    return np.asarray(vector, dtype=float) * np.array([-1., 1., 1.])


def _roll(vector, axis, degrees):
    angle = np.deg2rad(degrees)
    return (vector * np.cos(angle)
            + np.cross(axis, vector) * np.sin(angle)
            + axis * np.dot(axis, vector) * (1. - np.cos(angle)))


def _symmetric_material_case(*, legs='mirrored', store_left=True, store_right=True,
                            rolled_right=False, right_roll_degrees=12.):
    count = 3
    left = np.zeros((count, len(_MATERIAL_NAMES), 3))
    for frame in range(count):
        lift = .01 * frame
        left[frame, _MATERIAL_NAMES.index('left_hip')] = [-.15, 1., 0.]
        left[frame, _MATERIAL_NAMES.index('left_knee')] = [-.11, .55, .03]
        left[frame, _MATERIAL_NAMES.index('left_ankle')] = [-.10, .10 + lift, -.05]
        left[frame, _MATERIAL_NAMES.index('left_foot')] = [-.10, .04 + lift, .20]
        left[frame, _MATERIAL_NAMES.index('left_shoulder')] = [-.18, .85, 0.]
    right = left.copy()
    for name in _MATERIAL_NAMES:
        if name.startswith('right_'):
            left_name = 'left_' + name.removeprefix('right_')
            right[:, _MATERIAL_NAMES.index(name)] = _reflect_x(
                left[:, _MATERIAL_NAMES.index(left_name)])

    forward = np.asarray([.02, -.15, .99])
    forward /= np.linalg.norm(forward)
    side = np.asarray([1., 0., .02])
    side -= forward * np.dot(side, forward)
    side /= np.linalg.norm(side)
    right_forward = _reflect_x(forward)
    right_side = -_reflect_x(side)
    if rolled_right:
        right_side = _roll(right_side, right_forward, right_roll_degrees)
    if not store_right:
        right_forward = right_side = None

    frames = []
    for frame in range(count):
        joints = {}
        for index, name in enumerate(_MATERIAL_NAMES):
            source = left if name.startswith('left_') else right
            joints[name] = source[frame, index].tolist()
        orientation = {}
        if store_left:
            orientation['left'] = {'forward': forward.tolist(),
                                   'side': side.tolist()}
        if store_right:
            orientation['right'] = {'forward': right_forward.tolist(),
                                    'side': right_side.tolist()}
        frames.append({'joints': joints, 'shoeOrientation': orientation})
    payload = {
        'frames': frames,
        'jointNames': list(_MATERIAL_NAMES),
        'canonicalExecution': {'legs': legs},
        'footRestPitchRadians': {'left': 0., 'right': 0.},
        'loop': {'enabled': False},
    }
    return payload


def test_material_checker_passes_symmetric_heel_articulation():
    payload = _symmetric_material_case()
    points = np.asarray([
        [frame['joints'][name] for name in _MATERIAL_NAMES]
        for frame in payload['frames']
    ])
    result = canonical_material_shoe_evidence(
        payload, points, np.arange(len(points), dtype=float))

    assert result['required'] is True
    assert result['passed'] is True
    assert result['sampleCount'] == len(points)
    assert result['toleranceMeters'] == .003
    # The production mesh has a small fixed chirality difference between the
    # reflected vertex sets even when the pose is exactly symmetric.
    assert result['maximumReflectedVertexErrorMeters'] <= result['toleranceMeters']


def test_material_checker_requires_estimated_orientation_to_be_exported():
    payload = _symmetric_material_case(store_left=False, store_right=False)
    payload['renderFloorY'] = 0.
    payload['groundContactMode'] = 'continuous'
    payload['sourceFootSupportEvidence'] = _producer_case()[2]
    points = np.array([[frame['joints'][name] for name in _MATERIAL_NAMES]
                       for frame in payload['frames']])
    source_evidence = copy.deepcopy(payload['sourceFootSupportEvidence'])
    tracks = shoe_orientation_tracks(payload, points)
    assert tracks['right']['modelMirroredFrom'] == 'left'
    for index, frame in enumerate(payload['frames']):
        frame['shoeOrientation']['left'] = {
            key: tracks['left'][key][index].tolist() for key in ('forward', 'side')}
    # A predicted counterpart is not present in the renderer's input yet.
    assert canonical_material_shoe_evidence(payload)['passed'] is False
    for index, frame in enumerate(payload['frames']):
        frame['shoeOrientation']['right'] = {
            key: tracks['right'][key][index].tolist() for key in ('forward', 'side')}
    assert canonical_material_shoe_evidence(payload)['passed'] is True
    assert payload['sourceFootSupportEvidence'] == source_evidence


def test_material_checker_rejects_stale_one_sided_stored_orientation():
    payload = _symmetric_material_case(store_right=False)
    forward = np.asarray([.02, -.15, .99])
    forward /= np.linalg.norm(forward)
    side = np.asarray([1., 0., .02])
    side -= forward * np.dot(side, forward)
    side = _roll(side / np.linalg.norm(side), forward, 12.)
    for frame in payload['frames']:
        frame['shoeOrientation']['left']['side'] = side.tolist()
    points = np.asarray([
        [frame['joints'][name] for name in _MATERIAL_NAMES]
        for frame in payload['frames']
    ])

    result = canonical_material_shoe_evidence(
        payload, points, np.arange(len(points), dtype=float))

    assert result['passed'] is False
    assert result['maximumReflectedVertexErrorMeters'] > result['toleranceMeters']


def test_material_checker_rejects_conflicting_right_roll():
    payload = _symmetric_material_case(rolled_right=True)
    points = np.asarray([
        [frame['joints'][name] for name in _MATERIAL_NAMES]
        for frame in payload['frames']
    ])

    result = canonical_material_shoe_evidence(
        payload, points, np.arange(len(points), dtype=float))

    assert result['passed'] is False
    assert result['maximumReflectedVertexErrorMeters'] > result['toleranceMeters']


def test_material_checker_is_inactive_without_mirrored_legs():
    payload = _symmetric_material_case(legs='unconstrained')

    assert canonical_material_shoe_evidence(payload) == {
        'required': False, 'passed': True}


def test_material_checker_fails_closed_when_geometry_is_unavailable():
    result = canonical_material_shoe_evidence({
        'canonicalExecution': {'legs': 'mirrored'},
        'frames': [], 'jointNames': [],
    })

    assert result['required'] is True
    assert result['passed'] is False
    assert result['reason'] == 'canonical_material_shoe_frame_geometry_unavailable'

    payload = _symmetric_material_case()
    payload['jointNames'] = [name for name in _MATERIAL_NAMES
                             if name != 'right_foot']
    result = canonical_material_shoe_evidence(payload)
    assert result['passed'] is False
    assert result['reason'] == 'canonical_material_shoe_joint_geometry_unavailable'
