from copy import deepcopy
import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.body_support_observation import (
    _confirmed_observed_ground_sole_sides,
    materialize_body_support,
)


def test_stationary_unobserved_sole_is_not_promoted_to_ground_contact():
    joints = {'left_hip': [.4, .5, 0], 'right_hip': [.6, .5, 0],
              'left_knee': [.4, .6, 0], 'right_knee': [.6, .7, 0],
              'left_ankle': [.4, .55, 0], 'right_ankle': [.6, .9, 0]}
    pose = {'coordinateSpace': 'normalized_image_xy',
            'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    evidence = {'bodySupport': {'status': 'confirmed', 'sourceVideoSha256': 'same'},
                'bodySupportObservation': {'status': 'observed', 'sourceVideoSha256': 'same',
                    'observation': {'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground',
                                    'rightFoot': 'stationary_full_sole', 'rightFootSurface': 'ground'}},
                'footPatchEvidence': {'available': True, 'feet': {
                    'left': {'states': ['unknown'] * 12},
                    'right': {'states': ['unknown'] * 4 + ['full_sole'] * 4 + ['unknown'] * 4}}}}
    names = [f'{side}_{joint}' for side in ('left', 'right') for joint in ('knee', 'ankle', 'foot')]
    assert _confirmed_observed_ground_sole_sides(evidence, pose, names) == {'right'}


def test_hinged_torso_does_not_reuse_a_cached_rigid_torso_support_plane():
    payload = {'sourceFootSupportEvidence': {
        'bodySupport': {'required': True, 'status': 'confirmed',
                        'stationaryJoints': ['pelvis'],
                        'nonPenetrationChains': [{'endpoints': ['pelvis', 'neck']}]},
        'contacts': [{'jointName': 'right_foot', 'contactMotion': 'stationary'}]}}
    contract = {'startPoseConstraints': {'supportMode': 'seated', 'torsoOrientation': 'hinged'}}
    materialize_body_support(payload, {}, contract)
    assert 'bodySupport' not in payload['sourceFootSupportEvidence']
    assert payload['sourceFootSupportEvidence']['contacts'][0]['jointName'] == 'right_foot'


@pytest.mark.parametrize('surface_kind', ['contract_confirmed_seated_support',
                                         'contract_confirmed_suspended_support',
                                         'contract_inferred_support_surface'])
def test_legacy_seat_hint_cannot_be_promoted_by_stationary_reconstruction(surface_kind):
    evidence = {'feet': {}, 'supportContacts': [{
        'jointName': 'pelvis', 'surfaceKind': surface_kind,
        'sourceStationarySupportCandidate': True, 'continuousSupport': True}]}
    original = deepcopy(evidence)
    payload = {'frames': [{'joints': {'head': [0, 1.8, 0], 'pelvis': [0, 1, 0],
                                    'right_foot': [0, 0, 0]}} for _ in range(12)]}
    fused, _ = bake.fuse_reconstructed_support_evidence(payload, evidence)
    assert fused['supportContacts'][0]['sourceStationarySupportCandidate'] is False
    assert fused['supportContacts'][0]['continuousSupport'] is False
    assert evidence == original


def test_contract_contacts_cannot_lock_but_observed_contacts_remain_authoritative():
    from exercise_motion_pkg.contact_constraints import stationary_contact_anchor_ids
    import numpy as np

    contacts = [
        {'jointName': 'pelvis', 'surfaceKind': 'contract_confirmed_seated_support',
         'continuousSupport': True, 'contactMotion': 'stationary'},
        {'jointName': 'left_wrist', 'surfaceKind': 'contract_confirmed_suspended_support',
         'sourceStationarySupportCandidate': True},
        {'jointName': 'right_wrist', 'surfaceKind': 'observed_support_surface',
         'contactMotion': 'stationary', 'anchorGroupId': 'observed-hand'},
    ]
    mask = stationary_contact_anchor_ids({'supportContacts': contacts},
                                   ['pelvis', 'left_wrist', 'right_wrist'], 12)
    assert np.all(mask[:, :2] == None)
    assert np.all(mask[:, 2] == 'observed-hand')
