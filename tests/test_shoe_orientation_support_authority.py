import copy

import numpy as np

from exercise_motion_pkg.foot_geometry import shoe_orientation_tracks


_NAMES = ['left_hip', 'right_hip', 'left_ankle', 'left_foot',
          'right_ankle', 'right_foot']


def _points():
    points = np.zeros((3, len(_NAMES), 3))
    points[:, _NAMES.index('left_hip')] = [-.11, 1., .02]
    points[:, _NAMES.index('right_hip')] = [.13, 1., -.01]
    points[:, _NAMES.index('left_ankle')] = [-.08, .10, .05]
    points[:, _NAMES.index('left_foot')] = [-.08, .08, .25]
    points[:, _NAMES.index('right_ankle')] = [.14, .10, .03]
    points[:, _NAMES.index('right_foot')] = [.14, .08, .23]
    return points


def _payload(points, *, observe_right):
    contacts = ([{
        'jointName': 'right_foot', 'contactState': 'full_sole',
        'contactMotion': 'stationary', 'surfaceKind': 'ground',
        'startFrame': 0, 'endFrame': 2,
    }] if observe_right else [])
    states = {'left': ['unknown'] * 3,
              'right': ['full_sole'] * 3 if observe_right else ['unknown'] * 3}
    evidence = {
        'sharedSupportPlaneY': .85224,
        'contacts': contacts,
        'footPatchEvidence': {'available': True, 'feet': {
            side: {'states': list(states[side])} for side in ('left', 'right')
        }},
        '_fitFrameFootPatchStatesBySide': {
            side: list(states[side]) for side in ('left', 'right')
        },
    }
    frames = [{'joints': dict(zip(_NAMES, row.tolist()))} for row in points]
    payload = {
        'frames': frames,
        'jointNames': list(_NAMES),
        'sourceFootSupportEvidence': evidence,
        'groundContactMode': 'continuous',
        'footRestPitchRadians': {'left': 0., 'right': 0.},
        'canonicalExecution': {'legs': 'mirrored'},
    }
    return payload, evidence


def _reflected_hip_axis(points):
    axis = points[:, _NAMES.index('right_hip')] - points[:, _NAMES.index('left_hip')]
    return axis / np.linalg.norm(axis, axis=1, keepdims=True)


def test_observed_ground_orientation_does_not_require_render_floor():
    # The render floor height is not an orientation input: an observed ground
    # mask must activate the producer when renderFloorY is absent.
    points = _points()
    payload, evidence = _payload(points, observe_right=True)
    source_payload, source_points = copy.deepcopy(payload), points.copy()
    assert 'renderFloorY' not in payload

    tracks = shoe_orientation_tracks(payload, points)

    assert set(tracks) == {'left', 'right'}
    assert tracks['right']['contactMask'].tolist() == [True, True, True]
    assert 'modelMirroredFrom' not in tracks['right']
    # Only the genuinely observed right ground rows own an orientation; the
    # unobserved left shoe is reflected from that authority without inventing
    # left contact.
    assert tracks['left']['modelMirroredFrom'] == 'right'
    assert tracks['left']['contactMask'].tolist() == [False, False, False]
    axis = _reflected_hip_axis(points)
    expected_forward = tracks['right']['forward'] - 2 * np.sum(
        tracks['right']['forward'] * axis, axis=1, keepdims=True) * axis
    expected_side = -(tracks['right']['side'] - 2 * np.sum(
        tracks['right']['side'] * axis, axis=1, keepdims=True) * axis)
    np.testing.assert_allclose(
        tracks['left']['forward'],
        expected_forward / np.linalg.norm(expected_forward, axis=1, keepdims=True))
    np.testing.assert_allclose(
        tracks['left']['side'],
        expected_side / np.linalg.norm(expected_side, axis=1, keepdims=True))
    np.testing.assert_array_equal(points, source_points)
    assert payload == source_payload
    assert evidence['sharedSupportPlaneY'] is not None

    # The mode alone is not contact evidence: without an observed ground row
    # the same payload stays unknown for both shoes.
    unobserved_payload, _ = _payload(points, observe_right=False)
    assert shoe_orientation_tracks(unobserved_payload, points) == {}


def test_pose_bound_partial_shoe_orientation_mirrors_basis_without_contact():
    import hashlib

    from exercise_motion_pkg.foot_contact_observation import POLICY_VERSION
    from exercise_motion_pkg.pose_fidelity import _canonical_source_pose_sha256

    points = _points()
    # A genuine time-varying free foot pitch; no frame is a ground anchor.
    vectors = np.asarray([[.18, .03, .11], [.20, .08, .07], [.16, .13, .06]])
    right_ankle = points[:, _NAMES.index('right_ankle')].copy()
    points[:, _NAMES.index('right_foot')] = right_ankle + vectors
    frames = [{'sourceTimeSec': float(i), 'joints': {'right_ankle': [.5, .5]}}
              for i in range(3)]
    source_sha = hashlib.sha256(b'partial-foot-source').hexdigest()
    source_pose = {
        'frames': frames, 'sourceVideoSha256': source_sha,
        'sourceTimeOriginSec': 0., 'sourcePoseSampleBoundaryToleranceSeconds': .01,
        'imageWidth': 640, 'imageHeight': 360,
    }
    patch = {
        'available': True, 'policyVersion': POLICY_VERSION,
        'source': 'mediapipe_full_heel_forefoot',
        'sourceVideoSha256': source_sha, 'sourcePoseVideoSha256': source_sha,
        'sourcePosePayloadSha256': _canonical_source_pose_sha256(source_pose),
        'sourcePoseFrameCount': 3, 'sourcePoseSampleBoundaryToleranceSeconds': .01,
        'sourceFrameCount': 3, 'sourceTimeBasis': 'absolute_source_video',
        'sourceTimeOriginSec': 0., 'sourceTimesSec': [0., 1., 2.],
        'imageWidth': 640, 'imageHeight': 360,
        'feet': {
            'left': {'states': ['unknown'] * 3, 'rayObservations': []},
            'right': {'states': ['toe_only'] * 3, 'rayObservations': []},
        },
    }
    evidence = {
        'sourceVideoSha256': source_sha,
        'footPatchEvidence': patch,
        'contacts': [{'jointName': 'right_foot', 'contactState': 'toe_only',
                      'contactMotion': 'stationary', 'surfaceKind': 'ground',
                      'supportKind': 'observed_source_stance_interval',
                      'sourceVideoSha256': source_sha, 'sourceFrameCount': 3,
                      'sourceFrameBounds': [0, 2], 'startFrame': 0, 'endFrame': 2}],
        '_fitFrameFootPatchStatesBySide': {
            'left': ['unknown'] * 3, 'right': ['toe_only'] * 3,
        },
    }
    payload = {
        'frames': [{'sourceTimeSec': float(i),
                    'joints': dict(zip(_NAMES, row.tolist()))}
                   for i, row in enumerate(points)],
        'jointNames': list(_NAMES), 'sourceFootSupportEvidence': evidence,
        'sourcePoseCameraReference': {'sourcePose': source_pose},
        'groundContactMode': 'continuous', 'canonicalExecution': {'legs': 'mirrored'},
    }
    side = np.tile([0., 1., 0.], (3, 1))
    resolved = [{f'{s}_ankle->{s}_foot': side[i].tolist()
                 for s in ('left', 'right')} for i in range(3)]

    from exercise_motion_pkg.foot_contact_observation import foot_patch_pose_binding_failure
    from exercise_motion_pkg.foot_geometry import (
        _source_partial_foot_observation_sides, shoe_orientation_context,
    )
    assert foot_patch_pose_binding_failure(patch, source_pose) is None
    states = {'left': ('unknown',) * 3, 'right': ('toe_only',) * 3}
    assert _source_partial_foot_observation_sides(payload, evidence, states, 3) == {'right'}
    full_sole_opposite = copy.deepcopy(evidence)
    full_sole_opposite['footPatchEvidence']['feet']['left']['states'] = ['full_sole'] * 3
    assert _source_partial_foot_observation_sides(
        payload, full_sole_opposite,
        {'left': ('full_sole',) * 3, 'right': ('toe_only',) * 3}, 3) == set()
    context = {'states': states, 'ground': np.zeros((3, len(_NAMES)), dtype=bool),
               'planeGroups': [], 'evidence': evidence, 'mirroredPartialSides': {'right'}}
    with shoe_orientation_context(context):
        tracks = shoe_orientation_tracks(payload, points, resolved_sides=resolved)

    assert set(tracks) == {'left', 'right'}
    np.testing.assert_array_equal(tracks['right']['contactMask'], [False] * 3)
    np.testing.assert_array_equal(tracks['left']['contactMask'], [False] * 3)
    assert tracks['left']['modelMirroredFrom'] == 'right'
    expected = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    np.testing.assert_allclose(tracks['right']['forward'], expected, atol=1e-12)
    assert np.max(np.linalg.norm(np.diff(tracks['right']['forward'], axis=0), axis=1)) > .1
    axis = _reflected_hip_axis(points)
    expected_left = tracks['right']['forward'] - 2 * np.sum(
        tracks['right']['forward'] * axis, axis=1, keepdims=True) * axis
    np.testing.assert_allclose(tracks['left']['forward'], expected_left, atol=1e-12)

    # Without the explicit mirrored-leg contract, or without observed partial
    # evidence, this extension must not create free material tracks.
    nonmirrored = copy.deepcopy(payload)
    nonmirrored['canonicalExecution'] = {'legs': 'independent'}
    assert shoe_orientation_tracks(nonmirrored, points, resolved_sides=resolved) == {}
    unknown = copy.deepcopy(payload)
    unknown['sourceFootSupportEvidence']['footPatchEvidence']['feet']['right']['states'] = ['unknown'] * 3
    unknown['sourceFootSupportEvidence']['_fitFrameFootPatchStatesBySide']['right'] = ['unknown'] * 3
    unknown_context = {**context, 'states': {'left': ('unknown',) * 3,
                                             'right': ('unknown',) * 3},
                       'mirroredPartialSides': set()}
    with shoe_orientation_context(unknown_context):
        assert shoe_orientation_tracks(unknown, points, resolved_sides=resolved) == {}
