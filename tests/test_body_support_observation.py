from copy import deepcopy
import json
from pathlib import Path

from exercise_motion_pkg.body_support_observation import materialize_body_support, body_support_source_readiness


def test_observed_hand_plane_requires_both_stationary_source_tracks():
    from exercise_motion_pkg.body_support_observation import materialize_hand_support
    from exercise_motion_pkg.support_geometry import validate_support_geometry
    joints = {'left_wrist': [.2, .3, 0.], 'right_wrist': [.7, .4, 0.],
              'pelvis': [.5, .6, 0.], 'head': [.5, .1, 0.]}
    pose = {'coordinateSpace': 'normalized_image_xy',
            'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    base = {'jointNames': list(joints), 'frames': [{'joints': deepcopy(joints)} for _ in range(12)],
            'sourceFootSupportEvidence': {'bodySupportObservation': {'status': 'observed',
                'observation': {'leftHand': 'stationary_support', 'rightHand': 'stationary_support',
                                'handsSameHorizontalSurface': True}}}}
    accepted = deepcopy(base)
    materialize_hand_support(accepted, pose)
    support = accepted['sourceFootSupportEvidence']['bodySupport']
    assert support['stationaryJoints'] == ['left_wrist', 'right_wrist']
    assert not validate_support_geometry(accepted)['passed']  # Unequal hand heights remain a real failure.
    for frame in accepted['frames']:
        frame['joints']['right_wrist'][1] = .3
    assert validate_support_geometry(accepted)['passed']
    for index, frame in enumerate(pose['frames']):
        frame['joints']['right_wrist'][0] += index*.015
    partial = deepcopy(base)
    materialize_hand_support(partial, pose)
    assert partial['sourceFootSupportEvidence']['bodySupport']['stationaryJoints'] == ['left_wrist']
    assert partial['sourceFootSupportEvidence']['bodySupport']['coplanarGroups'] == []
    partial = deepcopy(base)
    partial['sourceFootSupportEvidence']['bodySupportObservation']['observation']['leftHand'] = 'unknown'
    materialize_hand_support(partial, pose)
    assert 'bodySupport' not in partial['sourceFootSupportEvidence']


def test_observed_ground_toe_keeps_heel_pitch_free_and_rejects_release():
    from exercise_motion_pkg.body_support_observation import materialize_observed_ground_contacts
    from exercise_motion_pkg.support_geometry import validate_support_geometry
    joints = {'left_ankle': [.2, .2, 0.], 'left_foot': [.2, 0., .1], 'head': [.5, .9, 0.]}
    source = {'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    base = {'jointNames': list(joints), 'renderFloorY': 0.,
            'frames': [{'joints': deepcopy(joints)} for _ in range(12)],
            'sourceFootSupportEvidence': {'bodySupportObservation': {'status': 'observed',
                'observation': {'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground'}}}}
    result = deepcopy(base)
    materialize_observed_ground_contacts(result, source)
    support = result['sourceFootSupportEvidence']['bodySupport']
    assert support['stationaryJoints'] == ['left_foot']
    assert support['soleContacts'] == []
    assert validate_support_geometry(result)['passed']
    result['frames'][0]['joints']['left_foot'][1] = .02
    assert not validate_support_geometry(result)['passed']
    for contradiction in ['airborne', 'heel_only']:
        result = deepcopy(base)
        result['sourceFootSupportEvidence']['footPatchEvidence'] = {
            'feet': {'left': {'states': ['unknown']*5 + [contradiction]}}}
        materialize_observed_ground_contacts(result, source)
        assert 'bodySupport' not in result['sourceFootSupportEvidence']
    for mode in ('intermittent', 'none'):
        result = deepcopy(base)
        result['groundContactMode'] = mode
        timed = [{'jointName': 'left_foot', 'startRatio': .1, 'endRatio': .3}]
        result['sourceFootSupportEvidence']['supportContacts'] = deepcopy(timed)
        materialize_observed_ground_contacts(result, source)
        assert 'bodySupport' not in result['sourceFootSupportEvidence']
        assert result['sourceFootSupportEvidence']['supportContacts'] == timed


def test_visual_contact_needs_independent_stationarity_and_keeps_moving_parts_free():
    joints = {'pelvis': [0., 1., 0.], 'left_hip': [-.1, 1., 0.], 'right_hip': [.1, 1., 0.],
              'left_shoulder': [-.2, 1., .5], 'right_shoulder': [.2, 1., .5],
              'neck': [0., 1., .6], 'head': [0., 1., .7],
              'spine1': [0., 1., .2], 'spine2': [0., 1., .3], 'spine3': [0., 1., .4]}
    answer = {'pelvisAndUpperBackSameSurface': True, 'torsoSurface': 'horizontal',
              'pelvis': 'stationary_support', 'upperBack': 'stationary_support',
              'head': 'moving', 'leftFoot': 'moving', 'rightFoot': 'unknown'}
    base = {'jointNames': list(joints), 'frames': [{'joints': joints}],
            'sourceFootSupportEvidence': {'bodySupport': {'required': True, 'status': 'unknown'},
            'bodySupportObservation': {'status': 'observed', 'sourceVideoSha256': 'fixture', 'observation': answer}}}
    pose = {'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    assert body_support_source_readiness(pose)['ready']
    accepted = deepcopy(base)
    materialize_body_support(accepted, pose)
    support = accepted['sourceFootSupportEvidence']['bodySupport']
    assert support['status'] == 'confirmed'
    assert support['stationaryJoints'] == ['pelvis', 'left_shoulder', 'right_shoulder']
    for index, frame in enumerate(pose['frames']):
        frame['joints']['pelvis'][0] += index*.1
    rejected = deepcopy(base)
    materialize_body_support(rejected, pose)
    assert rejected['sourceFootSupportEvidence']['bodySupport']['status'] == 'unknown'
    readiness = body_support_source_readiness(pose)
    assert not readiness['ready']
    from exercise_motion_pkg.bake_and_rank import exact_source_phase_validation_rejection_reasons, exact_source_validation_effectively_passed
    validation = {'passed': True, 'required': True, 'sourceBodySupportReadiness': readiness}
    assert not exact_source_validation_effectively_passed(validation)
    assert exact_source_phase_validation_rejection_reasons(validation) == ['source_cut_supported_body_stationarity_unresolved']
    unknown = deepcopy(base)
    unknown['sourceFootSupportEvidence']['bodySupportObservation']['observation']['pelvis'] = 'unknown'
    materialize_body_support(unknown, {'frames': [{'joints': joints} for _ in range(12)]})
    assert unknown['sourceFootSupportEvidence']['bodySupport']['status'] == 'unknown'


def test_ground_sole_requires_observed_surface_and_full_selected_cycle():
    from exercise_motion_pkg.body_support_observation import materialize_stationary_sole_support
    from exercise_motion_pkg.loop_cycles import slice_loop_cycle
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    joints = fixture['joints']
    payload = {'jointNames': list(joints), 'fps': 30., 'renderFloorY': fixture['renderFloorY'],
               'frames': [{'timeSec': i/30., 'joints': deepcopy(joints)} for i in range(12)],
               'sourceFootSupportEvidence': {
                   'contacts': [{'jointName': 'left_foot', 'contactState': 'full_sole',
                                 'contactMotion': 'stationary', 'startFrame': 2, 'endFrame': 11}],
                   'bodySupportObservation': {'status': 'observed', 'sourceVideoSha256': 'fixture',
                       'observation': {'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground'}}}}
    materialize_stationary_sole_support(payload)
    assert 'bodySupport' not in payload['sourceFootSupportEvidence']
    corroborated = deepcopy(payload)
    evidence = corroborated['sourceFootSupportEvidence']
    evidence['temporalResolutionSufficient'] = True
    evidence['footContactCandidates'] = [{'jointName': 'left_ankle',
        'contactMotion': 'stationary', 'startRatio': 0., 'endRatio': 1.}]
    evidence['footPatchEvidence'] = {'available': True, 'feet': {'left': {
        'states': ['unknown']*2+['full_sole']*10}}}
    for contradiction in ['release', 'partial_tracking']:
        incomplete = deepcopy(corroborated)
        if contradiction == 'release':
            incomplete['sourceFootSupportEvidence']['footPatchEvidence']['feet']['left']['states'][0] = 'airborne'
        else:
            incomplete['sourceFootSupportEvidence']['footContactCandidates'][0]['startRatio'] = .1
        materialize_stationary_sole_support(incomplete)
        assert 'bodySupport' not in incomplete['sourceFootSupportEvidence']
    materialize_stationary_sole_support(corroborated)
    assert corroborated['sourceFootSupportEvidence']['bodySupport']['stationaryJoints'] == ['left_ankle', 'left_foot']
    cycle = slice_loop_cycle(payload, {'startFrame': 2, 'stopFrameExclusive': 12})
    for surface in ['raised_surface', 'unknown']:
        unsupported = deepcopy(cycle)
        unsupported['sourceFootSupportEvidence']['bodySupportObservation']['observation']['leftFootSurface'] = surface
        materialize_stationary_sole_support(unsupported)
        assert 'bodySupport' not in unsupported['sourceFootSupportEvidence']
    unresolved = deepcopy(cycle)
    unresolved['sourceFootSupportEvidence']['bodySupport'] = {'required': True, 'status': 'unknown'}
    materialize_stationary_sole_support(unresolved)
    assert unresolved['sourceFootSupportEvidence']['bodySupport']['status'] == 'unknown'
    materialize_stationary_sole_support(cycle)
    support = cycle['sourceFootSupportEvidence']['bodySupport']
    assert support['stationaryJoints'] == ['left_ankle', 'left_foot']
    assert support['soleContacts'][0]['joints'] == ['left_knee', 'left_ankle', 'left_foot']

    # The selected cycle can be wholly inside a stance that did not cover its
    # parent clip. Upgrading an observed toe must preserve unrelated supports.
    partial = deepcopy(payload)
    evidence = partial['sourceFootSupportEvidence']
    evidence['temporalResolutionSufficient'] = True
    evidence['footContactCandidates'] = [{'jointName': 'left_ankle', 'contactMotion': 'stationary',
                                         'startFrame': 2, 'endFrame': 11}]
    evidence['footPatchEvidence'] = {'available': True, 'feet': {'left': {
        'states': ['airborne']*2+['full_sole']*4+['unknown']*2+['full_sole']*4}}}
    evidence['bodySupport'] = {'required': True, 'status': 'confirmed',
        'stationaryJoints': ['left_foot', 'right_wrist'],
        'coplanarGroups': [{'joints': ['left_foot'], 'normal': [0, 1, 0], 'planeOffsetMeters': fixture['renderFloorY']},
                          {'joints': ['right_wrist'], 'normal': [0, 1, 0], 'planeOffsetMeters': 2.}],
        'soleContacts': [], 'nonPenetrationChains': []}
    original = deepcopy(partial)
    selected = slice_loop_cycle(partial, {'startFrame': 2, 'stopFrameExclusive': 12})
    materialize_stationary_sole_support(selected)
    upgraded = selected['sourceFootSupportEvidence']['bodySupport']
    assert set(upgraded['stationaryJoints']) == {'left_ankle', 'left_foot', 'right_wrist'}
    assert len(upgraded['stationaryJoints']) == 3
    assert upgraded['soleContacts'][0]['joints'] == ['left_knee', 'left_ankle', 'left_foot']
    assert upgraded['coplanarGroups'][0]['joints'] == ['right_wrist']
    assert upgraded['coplanarGroups'][0]['planeOffsetMeters'] == 2.
    assert partial == original


def test_lying_press_does_not_require_moving_shoulder_anchors():
    joints = {
        'pelvis': [0.5, 0.6, 0.0],
        'left_shoulder': [0.3, 0.4, 0.0],
        'right_shoulder': [0.7, 0.4, 0.0],
    }
    pose = {'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    for index, frame in enumerate(pose['frames']):
        frame['joints']['right_shoulder'] = [0.7 + index * 0.01, 0.4, 0.0]
    contract = {
        'startPoseConstraints': {'supportMode': 'lying'},
        'referenceRegions': ['torso'],
        'primaryMovingRegions': ['elbows', 'shoulders'],
        'observableMotionSpec': {
            'primaryMovingRegions': ['elbows', 'shoulders'],
            'referenceRegions': ['torso'],
        },
    }
    readiness = body_support_source_readiness(pose, contract)
    assert readiness['requiredAnchors'] == ['pelvis']
    assert readiness['ready']
    assert readiness['unresolvedAnchors'] == []
    blocked = body_support_source_readiness(pose)
    assert 'right_shoulder' in blocked['unresolvedAnchors']
    joints_full = {
        **joints,
        'left_hip': [0.4, 0.6, 0.0],
        'right_hip': [0.6, 0.6, 0.0],
        'neck': [0.5, 0.35, 0.0],
        'spine1': [0.5, 0.55, 0.0],
        'spine2': [0.5, 0.5, 0.0],
        'spine3': [0.5, 0.45, 0.0],
    }
    answer = {
        'pelvisAndUpperBackSameSurface': True,
        'torsoSurface': 'horizontal',
        'pelvis': 'stationary_support',
        'upperBack': 'stationary_support',
        'head': 'moving',
        'leftFoot': 'moving',
        'rightFoot': 'unknown',
    }
    base = {
        'jointNames': list(joints_full),
        'frames': [{'joints': deepcopy(joints_full)}],
        'sourceFootSupportEvidence': {
            'bodySupport': {'required': True, 'status': 'unknown'},
            'bodySupportObservation': {
                'status': 'observed',
                'sourceVideoSha256': 'fixture',
                'observation': answer,
            },
        },
    }
    blocked_payload = deepcopy(base)
    materialize_body_support(blocked_payload, pose)
    assert blocked_payload['sourceFootSupportEvidence']['bodySupport']['status'] == 'unknown'
    accepted = deepcopy(base)
    materialize_body_support(accepted, pose, contract)
    support = accepted['sourceFootSupportEvidence']['bodySupport']
    assert support['status'] == 'confirmed'
    assert support['stationaryJoints'] == ['pelvis']
    assert support['coplanarGroups'][0]['joints'] == ['pelvis']
    from exercise_motion_pkg.bake_and_rank import (
        exact_source_phase_validation_rejection_reasons,
        exact_source_validation_effectively_passed,
    )
    validation = {
        'required': True,
        'passed': True,
        'sourceBodySupportReadiness': readiness,
    }
    assert exact_source_validation_effectively_passed(validation)
    assert exact_source_phase_validation_rejection_reasons(validation) == []
