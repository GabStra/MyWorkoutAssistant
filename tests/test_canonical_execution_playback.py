import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.controlled_motion import FixedRig, canonical_bilateral_reference
from exercise_motion_pkg.rig_playback import canonical_execution_policy_evidence


def _stance_points(frame_count=7):
    fixture = json.loads(
        (Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text()
    )
    names = list(fixture['joints'])
    frame = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    return names, np.repeat(frame[None, :, :], frame_count, axis=0)


def _payload(names, points, canonical_execution, *, floor=None):
    rig = FixedRig(points, names)
    fixed_rig = {
        'version': 1,
        'jointNames': list(names),
        'parents': rig.parents,
        'order': rig.order,
        'offsets': rig.offsets.tolist(),
        'rotationJointNames': [names[index] for index in rig.active],
        'coordinates': rig.initial.tolist(),
    }
    payload = {
        'fps': 30.,
        'jointNames': list(names),
        'fixedRig': fixed_rig,
        'canonicalExecution': canonical_execution,
        'loop': {'enabled': False},
        'frames': [
            {'timeSec': index / 30.,
             'joints': dict(zip(names, frame.tolist()))}
            for index, frame in enumerate(points)
        ],
    }
    if floor is not None:
        payload['renderFloorY'] = float(floor)
    return payload


@pytest.mark.parametrize(('group', 'mode'), [
    ('arms', 'mirrored'),
    ('legs', 'mirrored'),
    ('torso', 'sagittal'),
    ('torso', 'support_aligned'),
])
def test_canonical_execution_accepts_its_own_transformed_target(group, mode):
    names, points = _stance_points()
    target = canonical_bilateral_reference(points, names, {group: mode})
    report = canonical_execution_policy_evidence(
        _payload(names, target, {group: mode}), target,
    )
    assert report['required'] is True
    assert report['passed'] is True, report
    assert report['posePolicy']['maximumResidualMeters'] <= report['posePolicy']['toleranceMeters']


def test_mirrored_pose_policy_is_heading_and_translation_invariant_and_detects_skew():
    names, points = _stance_points()
    target = canonical_bilateral_reference(points, names, {'legs': 'mirrored'})
    transform = Rotation.from_euler('y', 37., degrees=True)
    moved = transform.apply(target.reshape(-1, 3)).reshape(target.shape) + [1.3, -0.4, 2.1]
    payload = _payload(names, moved, {'legs': 'mirrored'})
    assert canonical_execution_policy_evidence(payload, moved)['passed'] is True

    skewed = moved.copy()
    skewed[:, names.index('right_foot'), 0] += .002
    rejected = canonical_execution_policy_evidence(payload, skewed)
    assert rejected['passed'] is False
    assert rejected['posePolicy']['maximumResidualMeters'] > .0005


def test_unconstrained_execution_does_not_add_an_implicit_symmetry_requirement():
    payload = {'canonicalExecution': {
        'arms': 'unconstrained', 'legs': 'unconstrained', 'torso': 'unconstrained',
    }}
    assert canonical_execution_policy_evidence(payload) == {'required': False, 'passed': True}


def test_canonical_pose_policy_fails_closed_when_required_geometry_is_missing():
    report = canonical_execution_policy_evidence(
        {'canonicalExecution': {'legs': 'mirrored'}, 'jointNames': [], 'frames': []}
    )
    assert report['required'] is True
    assert report['passed'] is False
    assert report['reason'] == 'canonical_execution_geometry_unavailable'


def _stationary_bilateral_payload(frame_count=7):
    names, points = _stance_points(frame_count)
    left_foot, right_foot = (names.index(f'{side}_foot') for side in ('left', 'right'))
    floor = float(points[0, left_foot, 1])
    points[:, :, 1] -= floor
    points[:, left_foot, 1] = 0.
    points[:, right_foot, 1] = 0.
    # The toe pivots remain planted while ankle/heel pose can still articulate.
    left_ankle = names.index('left_ankle')
    right_ankle = names.index('right_ankle')
    points[:, left_ankle, 0] += np.linspace(0., .01, frame_count)
    points[:, right_ankle, 0] -= np.linspace(0., .01, frame_count)
    payload = _payload(names, points, {'stance': 'stationary_bilateral'}, floor=0.)
    payload['groundContactMode'] = 'continuous'
    return names, points, payload


def test_stationary_bilateral_stance_pins_only_toes_and_preserves_ankle_articulation():
    from exercise_motion_pkg.contact_constraints import motion_space_support_evidence
    from exercise_motion_pkg.sequence_stabilization import fit_contact_mask

    names, points, payload = _stationary_bilateral_payload()
    report = canonical_execution_policy_evidence(payload, points)
    assert report['required'] is True
    stance = report['stationaryBilateralStance']
    assert stance['passed'] is True, report
    assert stance['bothToePivotsPinnedByFitPolicy'] is True
    assert all(x['maximumDriftMeters'] == pytest.approx(0.)
               and x['maximumToeFloorErrorMeters'] == pytest.approx(0.)
               for x in stance['toePivots'].values())

    support_evidence = motion_space_support_evidence(payload)
    fit_mask = fit_contact_mask(
        payload, names, len(points), support_evidence=support_evidence,
    )
    for side in ('left', 'right'):
        assert np.all(fit_mask[:, names.index(f'{side}_foot')])
        assert not np.any(fit_mask[:, names.index(f'{side}_ankle')])


def test_stationary_bilateral_stance_estimates_floor_without_world_origin_assumption():
    names, points, payload = _stationary_bilateral_payload()
    points[:, :, 1] += 1.7
    for frame, joints in zip(payload['frames'], points):
        frame['joints'] = dict(zip(names, joints.tolist()))
    payload.pop('renderFloorY')

    report = canonical_execution_policy_evidence(payload, points)

    stance = report['stationaryBilateralStance']
    assert report['passed'] is True, report
    assert stance['floorY'] == pytest.approx(1.7)
    assert stance['floorAuthority'] == 'estimated_median_bilateral_toe_plane'


@pytest.mark.parametrize('invalid_floor', [True, '0.0', float('nan'), float('inf')])
def test_stationary_bilateral_stance_rejects_explicit_malformed_floor(invalid_floor):
    names, points, payload = _stationary_bilateral_payload()
    payload['renderFloorY'] = invalid_floor

    report = canonical_execution_policy_evidence(payload, points)

    assert report['passed'] is False
    assert report['stationaryBilateralStance']['passed'] is False
    assert report['stationaryBilateralStance']['reason'] == (
        'canonical_bilateral_stance_geometry_unavailable'
    )


def test_stationary_bilateral_stance_rejects_toe_drift_and_toe_above_floor():
    names, points, payload = _stationary_bilateral_payload()
    points[-1, names.index('right_foot'), 0] += .002
    drift = canonical_execution_policy_evidence(payload, points)
    assert drift['passed'] is False
    assert drift['stationaryBilateralStance']['toePivots']['right']['maximumDriftMeters'] > .0005

    names, points, payload = _stationary_bilateral_payload()
    points[:, names.index('left_foot'), 1] += .001
    height = canonical_execution_policy_evidence(payload, points)
    assert height['passed'] is False
    assert height['stationaryBilateralStance']['toePivots']['left']['maximumToeFloorErrorMeters'] > .0005


def test_stationary_bilateral_stance_rejects_known_airborne_source_evidence():
    names, points, payload = _stationary_bilateral_payload()
    payload['sourceFootSupportEvidence'] = {
        'footPatchEvidence': {
            'feet': {
                'left': {'states': ['full_sole'] * len(points)},
                'right': {'states': ['airborne'] * len(points)},
            },
        },
    }
    report = canonical_execution_policy_evidence(payload, points)
    assert report['passed'] is False
    assert report['stationaryBilateralStance']['compatibility']['passed'] is False
