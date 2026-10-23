from copy import deepcopy
import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.contact_constraints import is_observed_ground_contact, motion_space_support_evidence
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


def test_pre_reconstruction_source_gate_matches_final_contact_requirements():
    from exercise_motion_pkg.support_geometry import (
        pre_reconstruction_source_support_readiness,
        support_contact_readiness,
    )

    evidence = {
        'bodySupportObservation': {'status': 'observed', 'observation': {
            'leftFoot': 'moving', 'rightFoot': 'stationary_full_sole',
        }},
        'footPatchEvidence': {'available': True, 'policyVersion': 16, 'feet': {
            'left': {'states': ['unknown'] * 8},
            'right': {'states': ['unknown'] * 8},
        }},
        'contacts': [],
    }
    early = pre_reconstruction_source_support_readiness(evidence)
    final = support_contact_readiness({'sourceFootSupportEvidence': evidence})
    assert early == final
    assert early['rejectionReasons'] == ['source_support_contact_evidence_unavailable']
    assert early['unresolvedSides'] == ['right']

    # Traveling or unresolved contacts are not converted into a blanket stance
    # requirement by the pre-reconstruction check.
    evidence['bodySupportObservation']['observation']['rightFoot'] = 'unknown'
    assert pre_reconstruction_source_support_readiness(evidence)['passed']

    # A retained full-clip bodySupport claim can look usable before temporal
    # materialization, then be removed because the active patch track is unknown.
    stale_anchor = deepcopy(evidence)
    stale_anchor['bodySupportObservation']['observation']['rightFoot'] = 'stationary_full_sole'
    stale_anchor['bodySupport'] = {
        'required': True, 'status': 'confirmed',
        'source': 'exact_source_contacts_and_stationary_pose_tracks',
        'stationaryJoints': ['right_ankle', 'right_foot'],
        'coplanarGroups': [], 'soleContacts': [], 'nonPenetrationChains': [],
    }
    raw_only = support_contact_readiness(
        {'sourceFootSupportEvidence': stale_anchor}, evidence=stale_anchor)
    materialized = support_contact_readiness({'sourceFootSupportEvidence': stale_anchor})
    assert raw_only['passed']
    assert not materialized['passed']
    assert pre_reconstruction_source_support_readiness(stale_anchor) == materialized


def test_explicit_observed_raised_foot_surface_overrides_legacy_shared_ground_plane():
    payload = {
        'sourcePoseCameraReference': {'camera': {'bilateralAssignment': 'swapped'}},
        'sourceFootSupportEvidence': {
            'sharedSupportPlaneY': 0.8,
            'bodySupportObservation': {
                'status': 'observed',
                'observation': {
                    'leftFootSurface': 'ground',
                    'rightFootSurface': 'raised_surface',
                },
            },
        },
    }
    mapped = motion_space_support_evidence(payload)

    assert is_observed_ground_contact({
        'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
    }, mapped) is False
    assert is_observed_ground_contact({
        'jointName': 'right_foot', 'supportKind': 'observed_foot_patch',
    }, mapped) is True
    # Per-contact surface classification remains the most local evidence.
    assert is_observed_ground_contact({
        'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
        'surfaceKind': 'ground',
    }, mapped) is True


def test_hinged_torso_does_not_reuse_a_cached_rigid_torso_support_plane():
    payload = {'sourceFootSupportEvidence': {
        'bodySupport': {'required': True, 'status': 'confirmed',
                        'reason': 'supported_reference_body_requires_observed_surface_geometry',
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


@pytest.mark.parametrize('cached_inference', [False, True])
def test_unknown_patch_cannot_be_promoted_by_reconstruction_or_approved_as_no_support(monkeypatch, cached_inference):
    from exercise_motion_pkg.acceptance import decide_acceptance
    from exercise_motion_pkg.support_geometry import validate_support_geometry
    joints = {'head': [0., 1.5, 0.], 'left_foot': [0., 0., 0.],
              'right_foot': [.3, 0., 0.]}
    evidence = {'feet': {side: {'continuousSupport': False, 'chunkCenterRangeRatio': .01,
                               'endpointDisplacementRatio': .01} for side in ('left', 'right')},
                'bodySupportObservation': {'status': 'observed', 'observation': {
                    'leftFoot': 'stationary_full_sole', 'rightFoot': 'stationary_forefoot'}},
                'footPatchEvidence': {'available': True, 'feet': {
                    side: {'states': ['unknown'] * 12} for side in ('left', 'right')}}}
    payload = {'jointNames': list(joints), 'frames': [{'joints': deepcopy(joints)} for _ in range(12)],
               'sourceFootSupportEvidence': deepcopy(evidence)}
    if cached_inference:
        evidence['feet']['left'].update(continuousSupport=True, reconstructed3dSupport={'rangeRatio': .01})
        evidence['supportContacts'] = [{'jointName': 'left_foot', 'continuousSupport': True,
                                        'reconstructed3dSupport': {'rangeRatio': .01}}]
        payload['sourceFootSupportEvidence'] = deepcopy(evidence)
    fused, report = bake.fuse_reconstructed_support_evidence(payload, evidence)
    assert not report['applied']
    assert not bake.source_contact_intervals_from_evidence(fused, frame_count=12)
    metrics = validate_support_geometry(payload)
    assert metrics['required'] and not metrics['available'] and not metrics['passed']
    assert metrics['unresolvedSides'] == ['left', 'right']
    decision = decide_acceptance({'bodySupport': metrics}, {'passed': True},
                                 deterministic_rejections=metrics['rejectionReasons'], review_rejections=[])
    assert decision.status == 'needs_manual_review' and decision.failure_owner == 'evidence'
    assert not decision.can_regenerate_motion
    assert evidence == payload['sourceFootSupportEvidence']
    from exercise_motion_pkg import controlled_motion as motion
    monkeypatch.setattr(motion, '_fit_candidate_motion', lambda *a, **kw: pytest.fail('Missing contacts must not start fitting'))
    result, fit_report = motion.fit_controlled_motion(payload)
    assert result is payload and not fit_report['applied']
    assert fit_report['failureStage'] == 'source_support_contact_readiness'


def test_observed_toe_support_pins_only_its_contact_interval_and_preserves_heel_motion():
    from exercise_motion_pkg.sequence_stabilization import contact_mask
    from exercise_motion_pkg.support_geometry import support_contact_readiness
    import numpy as np
    names = ['left_ankle', 'left_foot']
    evidence = {'contacts': [{'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
                             'contactState': 'toe_only', 'contactMotion': 'stationary',
                             'verticalOnly': False, 'startFrame': 2, 'endFrame': 7}],
                'feet': {'left': {'jointName': 'left_ankle', 'continuousSupport': True}},
                'bodySupportObservation': {'status': 'observed', 'observation': {
                    'leftFoot': 'stationary_forefoot', 'rightFoot': 'moving'}},
                'footPatchEvidence': {'available': True, 'feet': {'left': {
                    'states': ['unknown'] * 2 + ['toe_only'] * 6 + ['unknown'] * 2}}}}
    payload = {'sourceFootSupportEvidence': evidence}
    pinned = contact_mask(payload, names, 10)
    assert not pinned[:, 0].any()
    np.testing.assert_array_equal(pinned[:, 1], [False] * 2 + [True] * 6 + [False] * 2)
    assert support_contact_readiness(payload)['passed']
    intervals = bake.source_contact_intervals_from_evidence(evidence, frame_count=10)
    assert len(intervals) == 1 and intervals[0]['jointName'] == 'left_foot'


@pytest.mark.parametrize('state', ['toe_only', 'heel_only'])
def test_observed_contact_gate_rejects_small_slide_but_not_toe_pivot_or_release(state):
    import numpy as np
    count = 12
    frames = []
    for i in range(count):
        angle = i * .04
        frames.append({'timeSec': i / 30., 'joints': {
            'head': [0., 1.5, 0.], 'left_foot': [0., 0., 0.],
            'left_ankle': [-.2 * np.cos(angle), .2 * np.sin(angle), 0.]}})
        if state == 'heel_only':
            from exercise_motion_pkg.foot_kinematics import HEEL_BEHIND_ANKLE_RATIO
            ray = .2 * np.array([np.cos(angle), np.sin(angle), 0.])
            frames[-1]['joints']['left_ankle'] = (HEEL_BEHIND_ANKLE_RATIO * ray).tolist()
            frames[-1]['joints']['left_foot'] = ((1. + HEEL_BEHIND_ANKLE_RATIO) * ray).tolist()
    contact = {'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
               'contactState': state, 'contactMotion': 'stationary', 'verticalOnly': state == 'heel_only',
               'startFrame': 2, 'endFrame': 9}
    payload = {'fps': 30., 'jointNames': list(frames[0]['joints']), 'frames': frames,
               'sourceFootSupportEvidence': {'contacts': [contact]}}
    assert bake.source_confirmed_support_stationarity_metrics(payload, None)['passed']
    for i in (0, 1, 10, 11):
        payload['frames'][i]['joints']['left_foot'][0] = .5
    assert bake.source_confirmed_support_stationarity_metrics(payload, None)['passed']
    for name in (('left_foot',) if state == 'toe_only' else ('left_ankle', 'left_foot')):
        payload['frames'][6]['joints'][name][0] += .012
    report = bake.source_confirmed_support_stationarity_metrics(payload, None)
    assert not report['passed']
    assert report['rejectionReasons'] == ['left_source_confirmed_support_slides']
