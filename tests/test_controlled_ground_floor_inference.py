import numpy as np
from unittest import mock

from exercise_motion_pkg import body_support_observation
from exercise_motion_pkg.controlled_motion import (
    _registered_ground_contact_placement,
)
from exercise_motion_pkg.smpl_joint_names import SMPL_JOINT_NAMES
from exercise_motion_pkg.support_geometry import support_evidence


_REGISTRATION = {'applied': True, 'policy': 'joint_stance_anchor_registration_v4'}
_SOURCE_SHA = 'source-video-sha'


def _toe_only_ground_fixture(*, surface_kind='ground'):
    names = list(SMPL_JOINT_NAMES)
    frames = []
    for index in range(4):
        joints = {name: [0., 1., 0.] for name in names}
        joints['right_hip'] = [0.2, 1.0, 0.]
        joints['right_knee'] = [0.2, 0.92, 0.]
        joints['right_ankle'] = [0.2, 0.82, 0.]
        joints['right_foot'] = [0.2, 0.80, 0.15]
        frames.append({
            'timeSec': index / 25.,
            'sourceTimeSec': index / 25.,
            'joints': joints,
            'boneSides': {
                'right_knee->right_ankle': [0., 0., 1.],
                'right_ankle->right_foot': [0., 1., 0.],
            },
        })
    points = np.asarray([[frame['joints'][name] for name in names]
                         for frame in frames], dtype=float)
    payload = {
        'renderFloorY': None,
        'frames': frames,
        'jointNames': names,
        'fps': 25.,
        'footRestPitchRadians': {'left': 0., 'right': 0.},
        'groundContactMode': 'continuous',
        'loop': {'enabled': False},
    }
    contact = {
        'jointName': 'right_foot',
        'contactState': 'toe_only',
        'contactMotion': 'stationary',
        'surfaceKind': surface_kind,
        'startRatio': 0.,
        'endRatio': 1.,
    }
    observation = {
        'status': 'observed',
        'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': _SOURCE_SHA,
        'policyVersion': 7,
        'observation': {
            'rightKnee': 'stationary_support',
            'rightKneeContactSurface': 'floor',
        },
    }
    evidence = {
        'sourceVideoSha256': _SOURCE_SHA,
        'bodySupport': {
            'status': 'confirmed',
            'required': True,
            'sourceVideoSha256': _SOURCE_SHA,
            'stationaryJoints': ['right_knee'],
            'coplanarGroups': [],
            'nonPenetrationChains': [],
            'soleContacts': [],
        },
        'bodySupportObservation': observation,
        'contacts': [contact],
        'supportContacts': [],
        '_fitFrameStateIndices': list(range(len(frames))),
        '_fitFrameCount': len(frames),
    }
    return payload, points, names, frames, evidence


def test_mutable_toe_only_ground_reaches_existing_knee_material_calibration():
    payload, points, names, frames, evidence = _toe_only_ground_fixture()
    result, provenance = _registered_ground_contact_placement(
        payload, points, names, frames, evidence, registration=_REGISTRATION)

    assert result is not payload
    assert np.isfinite(result['renderFloorY'])
    assert result['renderFloorSource'] == (
        'inferred_ground_contact_material_scene_gauge')
    assert provenance['sides'] == ['right']
    assert provenance['provenance']['observedFloorHeight'] is False
    assert result['frames'] == payload['frames']
    assert result['jointNames'] == payload['jointNames']

    with mock.patch.object(
            body_support_observation, 'materialize_stationary_sole_support',
            return_value=evidence):
        support = support_evidence(result)
    assert support['_floorMaterialContacts'] == ['right_knee']
    assert support['_renderFloorY'] == result['renderFloorY']
    assert support.get('_materialFloorUnresolved') is False


def test_unknown_or_nonground_contacts_do_not_infer_a_floor():
    payload, points, names, frames, evidence = _toe_only_ground_fixture(
        surface_kind='bench')
    result, provenance = _registered_ground_contact_placement(
        payload, points, names, frames, evidence, registration=_REGISTRATION)
    assert result is payload
    assert result['renderFloorY'] is None
    assert provenance is None

    payload, points, names, frames, evidence = _toe_only_ground_fixture()
    result, provenance = _registered_ground_contact_placement(
        payload, points, names, frames, evidence, registration=None)
    assert result['renderFloorY'] is None
    assert provenance is None


def test_existing_explicit_floor_keeps_authority():
    payload, points, names, frames, evidence = _toe_only_ground_fixture()
    payload['renderFloorY'] = 0.42
    payload['renderFloorSource'] = 'explicit_source_floor'
    result, provenance = _registered_ground_contact_placement(
        payload, points, names, frames, evidence, registration=_REGISTRATION)
    assert result is payload
    assert result['renderFloorY'] == 0.42
    assert result['renderFloorSource'] == 'explicit_source_floor'
    assert provenance is None


def test_immutable_candidate_validation_cannot_repair_a_missing_floor():
    payload, points, names, frames, evidence = _toe_only_ground_fixture()
    result, provenance = _registered_ground_contact_placement(
        payload, points, names, frames, evidence, registration=_REGISTRATION,
        allow_inference=False)
    assert result is payload
    assert result['renderFloorY'] is None
    assert provenance is None

    with mock.patch.object(
            body_support_observation, 'materialize_stationary_sole_support',
            return_value=evidence):
        support = support_evidence(result)
    assert not support.get('_floorMaterialContacts')
    assert support.get('_materialFloorUnresolved') is True
