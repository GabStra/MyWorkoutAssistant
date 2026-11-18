"""Ensure accepted rigs are not sent through positional repairs on reuse."""
import ast
import json
import copy
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg import bake_and_rank
from exercise_motion_pkg import controlled_motion
from exercise_motion_pkg.controlled_motion import (
    CONTROLLED_MOTION_STRATEGY, REQUIRED_FIT_CHECKS, FixedRig,
    can_reuse_controlled_motion, controlled_motion_fit_source_evidence_digest,
)
from exercise_motion_pkg.sequence_stabilization import pose_digest


def accepted_payload():
    fixture=json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names=list(fixture['joints'])
    points=np.tile(np.asarray(list(fixture['joints'].values())),(7,1,1))
    rig=FixedRig(points,names)
    payload={'fps':30,'jointNames':names,'loop':{'enabled':False},
             'fixedRig':{'version':1,'jointNames':names,'parents':rig.parents,
                         'order':rig.order,'offsets':rig.offsets.tolist(),
                         'rotationJointNames':[names[j] for j in rig.active],
                         'coordinates':rig.initial.tolist()},
             'frames':[{'timeSec':i/30,'joints':dict(zip(names,p.tolist())),
                        'sourceJoints':dict(zip(names,p.tolist())),
                        'controlledSourceJoints':dict(zip(names,p.tolist()))}
                       for i,p in enumerate(rig.decode(rig.initial))]}
    payload['controlledMotionFit']={'applied':True,'strategy':CONTROLLED_MOTION_STRATEGY,
                                    'checks':dict.fromkeys(REQUIRED_FIT_CHECKS,True),
                                    'outputPoseDigest':pose_digest(payload)}
    payload['controlledMotionFit']['fitSourceEvidenceDigest'] = (
        controlled_motion_fit_source_evidence_digest(payload)
    )
    return payload


def _native_height_track(frame_count, mode='verticalOnly'):
    anchor = f'native-material:left:0:0:{frame_count - 1}'
    episode = {
        'startFrame': 0,
        'endFrame': frame_count - 1,
        'anchorId': anchor,
        'regionRole': 'forefoot',
        'mode': mode,
        'primitiveId': 'wearShoe:left_ankle->left_foot',
        'triangleIndex': 11,
        'barycentric': [0.2, 0.3, 0.5],
        'materialOffsetLocalMeters': [0.0, 0.0, 0.0],
        'referenceLengthMeters': 0.1,
        'surfaceNormal': [0.0, 1.0, 0.0],
        'planeOffsetMeters': 0.0,
    }
    if mode == 'stationary':
        episode['targetWorld'] = [0.0, 0.0, 0.0]
    return {
        'version': 2,
        'left': {
            'active': [True] * frame_count,
            'directions': [[0.0, 0.0, 1.0]] * frame_count,
            'sideAxes': [[1.0, 0.0, 0.0]] * frame_count,
            'anchorIds': [anchor] * frame_count,
            'episodes': [episode],
        },
    }


def _native_height_reuse_payload(mode='verticalOnly', *, proof=None):
    payload = accepted_payload()
    frame_count = len(payload['frames'])
    tracks = _native_height_track(frame_count, mode)
    payload['fixedRig']['contactFootTracks'] = tracks
    fit = payload['controlledMotionFit']
    fit['checks']['heightOnlyContacts'] = True
    fit['heightOnlyContactConstraint'] = {
        'available': True,
        'axis': 'floor_normal_y',
        'frameJointCount': frame_count,
        'nativeMaterialFrameCount': (
            frame_count if mode == 'verticalOnly' else 0),
        'nativeMaterialMeasured': False,
    }
    fit['playback'] = {'passed': True}
    if proof is not None:
        fit['heightOnlyContactConstraint'].update(proof['constraint'])
        fit['playback']['nativeHeightOnlyMaterialShoes'] = dict(proof['material'])
    fit['contactConstraintEvidence'] = _typed_material_evidence(
        tracks, frame_count, cyclic=payload['loop']['enabled'])
    fit['fitSourceEvidenceDigest'] = (
        controlled_motion_fit_source_evidence_digest(payload))
    fit['outputPoseDigest'] = pose_digest(payload)
    return payload


def _typed_material_evidence(tracks, frame_count, *, cyclic):
    """Persisted typed raw+rendered proof matching the retained track semantics."""
    from exercise_motion_pkg.contact_interpolation import (
        native_material_key_sample_requirements)
    from exercise_motion_pkg.controlled_motion import (
        native_material_dense_playback_cursors,
        native_material_key_sample_requirements_by_side,
        native_material_playback_sample_requirements)

    required = native_material_key_sample_requirements(tracks)
    required_by_side = native_material_key_sample_requirements_by_side(tracks)
    raw = {
        'available': True,
        'keyframeStationarySampleCount':
            required['keyframeStationarySampleCount'],
        'keyframeStationaryMaximumErrorMeters':
            1e-5 if required['keyframeStationarySampleCount'] else 0.,
        'keyframeHeightSampleCount': required['keyframeHeightSampleCount'],
        'keyframeHeightMaximumErrorMeters':
            1e-5 if required['keyframeHeightSampleCount'] else 0.,
        'playbackStationarySampleCount': 0,
        'playbackStationaryMaximumErrorMeters': 0.,
        'playbackHeightSampleCount': 0,
        'playbackHeightMaximumErrorMeters': 0.,
        'sampleCount': sum(int(value) for value in required.values()),
        'maximumErrorMeters': 1e-5,
        'bySide': {
            side: {
                'keyframeStationarySampleCount':
                    counts['keyframeStationarySampleCount'],
                'keyframeStationaryMaximumErrorMeters':
                    1e-5 if counts['keyframeStationarySampleCount'] else 0.,
                'keyframeHeightSampleCount':
                    counts['keyframeHeightSampleCount'],
                'keyframeHeightMaximumErrorMeters':
                    1e-5 if counts['keyframeHeightSampleCount'] else 0.,
            }
            for side, counts in required_by_side.items()
        },
    }
    cursors = native_material_dense_playback_cursors(
        frame_count, cyclic=cyclic)
    playback_required, playback_by_side = (
        native_material_playback_sample_requirements(
            tracks, cursors, cyclic=cyclic))

    def row(counts):
        return {
            'sampleCount': sum(int(value) for value in counts.values()),
            'playbackStationarySampleCount':
                counts['playbackStationarySampleCount'],
            'playbackStationaryMaximumErrorMeters':
                1e-5 if counts['playbackStationarySampleCount'] else 0.,
            'playbackHeightSampleCount':
                counts['playbackHeightSampleCount'],
            'playbackHeightMaximumErrorMeters':
                1e-5 if counts['playbackHeightSampleCount'] else 0.,
        }

    rendered = {
        **row(playback_required),
        'available': True,
        'maximumErrorMeters': 1e-5,
        'bySide': {side: row(counts)
                   for side, counts in playback_by_side.items()},
    }
    return {
        'nativeMaterialActive': True,
        'nativeMaterialEvaluated': True,
        'nativeMaterialPlayback': raw,
        'nativeMaterialRenderedApplicable': True,
        'nativeMaterialRenderedEvaluated': True,
        'nativeMaterialRenderedPlayback': rendered,
    }


def _native_material_proof(*, passed, error=0.001, samples=7, **overrides):
    constraint = {
        'nativeMaterialMeasured': True,
        'nativeMaterialKeySampleCount': samples,
        'nativeMaterialPlaybackSampleCount': samples,
        'nativeMaterialKeyMaximumErrorMeters': error,
        'nativeMaterialPlaybackMaximumErrorMeters': error,
        'nativeMaterialPassed': passed,
    }
    material = {
        'applicable': True,
        'available': True,
        'passed': passed,
        'storedFrameSampleCount': samples,
        'sampleCount': samples,
        'storedFrameMaximumErrorMeters': error,
        'maximumErrorMeters': error,
    }
    constraint.update(overrides)
    return {'constraint': constraint, 'material': material}


def test_native_height_only_reuse_requires_actual_material_proof():
    assert can_reuse_controlled_motion(accepted_payload())

    legacy = _native_height_reuse_payload()
    assert not can_reuse_controlled_motion(legacy)

    failed = _native_height_reuse_payload(
        proof=_native_material_proof(passed=False, error=0.01))
    assert not can_reuse_controlled_motion(failed)

    over_limit = _native_height_reuse_payload(
        proof=_native_material_proof(passed=True, error=0.01))
    assert not can_reuse_controlled_motion(over_limit)

    nonfinite = _native_height_reuse_payload(
        proof=_native_material_proof(passed=True, error=float('nan')))
    assert not can_reuse_controlled_motion(nonfinite)

    passing = _native_height_reuse_payload(
        proof=_native_material_proof(passed=True, error=0.001))
    assert can_reuse_controlled_motion(passing)

    stationary = _native_height_reuse_payload(mode='stationary')
    assert can_reuse_controlled_motion(stationary)


def test_reviewed_bilateral_target_reaches_rig_seed_without_rewriting_source(monkeypatch):
    original = accepted_payload()
    assert can_reuse_controlled_motion(original)
    changed_intent = copy.deepcopy(original)
    changed_intent['canonicalExecution'] = {'arms': 'mirrored'}
    assert not can_reuse_controlled_motion(changed_intent)
    original['frames'][0]['sourceJoints']['left_elbow'][2] += .05
    original['frames'][0]['joints']['left_elbow'][2] += .05
    before = copy.deepcopy(original)
    captured = []

    def fit(working):
        captured.append(working)
        return working, {'applied': False, 'reason': 'test_capture'}

    monkeypatch.setattr(controlled_motion, 'fit_controlled_motion', fit)
    monkeypatch.setattr(bake_and_rank, 'constrain_to_source_articulation_envelope',
                        lambda source, proposed, **kwargs: (proposed, {'applied': False}))
    bake_and_rank.constrain_baked_payload_to_source_articulation(original, exercise_motion_contract={
        'bilateralExecution': {'arms': 'mirrored'},
        'bilateralExecutionAuthority': 'structured_definition',
    })
    working, = captured
    assert working['canonicalExecution'] == {'arms': 'mirrored'}
    assert not can_reuse_controlled_motion(working)
    for frame, source in zip(working['frames'], before['frames']):
        assert frame['sourceJoints'] == source['sourceJoints']
        assert frame['joints'] == frame['controlledArticulationReferenceJoints']
    assert working['frames'][0]['joints'] != before['frames'][0]['joints']
    assert original == before


def test_support_wrap_deferral_requires_verified_camera_clock_and_bilateral_endpoint_pins(monkeypatch):
    from exercise_motion_pkg import body_support_observation, support_geometry
    from exercise_motion_pkg import sequence_stabilization

    identity = {
        'selectedSegmentSha256': 'selected',
        'parentSourceSha256': 'parent',
        'selectedFrameClockReceiptSha256': 'clock',
        'sourcePosePayloadSha256': 'pose',
    }
    payload = {
        'sourcePoseCameraReference': {
            'camera': {'available': True, 'sourceTimelineMappingIdentity': dict(identity)},
            'sourceTimelineMapping': {
                'schemaVersion': 1, 'verified': True,
                'mappingKind': 'selected_segment_to_parent_source', **identity,
            },
            'sourcePose': {'frames': []},
        },
        'sourceFootSupportEvidence': {'sourceVideoSha256': 'selected'},
        'jointNames': ['left_ankle', 'left_foot', 'right_ankle', 'right_foot'],
        'frames': [{'joints': {}} for _ in range(3)],
    }
    all_pinned = np.ones((3, 4), dtype=bool)
    monkeypatch.setattr(body_support_observation, 'materialize_stationary_sole_support',
                        lambda _payload: {'materialized': True})
    monkeypatch.setattr(support_geometry, 'support_contact_readiness',
                        lambda *_args, **_kwargs: {'passed': True})
    monkeypatch.setattr(sequence_stabilization, 'contact_mask',
                        lambda *_args, **_kwargs: all_pinned.copy())

    complete_phase = {'required': True, 'passed': True, 'hasSingleMajorCycle': True}
    assert controlled_motion._verified_support_wrap_deferral(payload, source_phase=complete_phase)
    incomplete = all_pinned.copy()
    incomplete[0, 1] = False
    monkeypatch.setattr(sequence_stabilization, 'contact_mask',
                        lambda *_args, **_kwargs: incomplete.copy())
    assert not controlled_motion._verified_support_wrap_deferral(
        payload, source_phase=complete_phase)

    anchored = {
        'bodySupport': {'required': True, 'status': 'confirmed',
                        'sourceVideoSha256': 'selected',
                        'stationaryJoints': ['left_wrist', 'right_wrist'],
                        'coplanarGroups': [{'joints': ['left_wrist', 'right_wrist'],
                                            'normal': [0, 1, 0]}]},
        'bodySupportObservation': {'sourceVideoSha256': 'selected'},
    }
    payload['jointNames'] += ['left_wrist', 'right_wrist']
    monkeypatch.setattr(body_support_observation, 'materialize_stationary_sole_support',
                        lambda _payload: anchored)
    monkeypatch.setattr(sequence_stabilization, 'contact_mask',
                        lambda *_args, **_kwargs: np.zeros((3, 6), dtype=bool))
    assert controlled_motion._verified_support_wrap_deferral(payload, source_phase=complete_phase)
    assert not controlled_motion._verified_support_wrap_deferral(payload)
    anchored['bodySupport']['sourceVideoSha256'] = 'different-video'
    assert not controlled_motion._verified_support_wrap_deferral(payload, source_phase=complete_phase)
    anchored['bodySupport']['sourceVideoSha256'] = 'selected'
    payload['sourceCyclePreflight'] = [{
        'passed': True, 'selection': {'startFrame': 0, 'stopFrameExclusive': 3},
        'sourcePhase': complete_phase,
    }]
    payload['loop'] = {'enabled': True}
    payload['loopCycleSelection'] = {'startFrame': 0, 'stopFrameExclusive': 3}
    from exercise_motion_pkg import loop_cycles
    monkeypatch.setattr(loop_cycles, 'cycle_boundary_motion_metrics', lambda *_args, **_kwargs: {
        'passed': False, 'rejectionReasons': [
            'source_support_wrap_unrepairable', 'source_boundary_tangents_incompatible']})
    fit_calls = []
    def fit(candidate, **kwargs):
        fit_calls.append(candidate)
        return candidate, {'applied': False, 'reason': 'final_validation_failed'}
    monkeypatch.setattr(controlled_motion, '_fit_controlled_motion', fit)
    _, result = controlled_motion._fit_observed_cycles(payload, timeout_seconds=60)
    assert len(fit_calls) == 1
    assert result['applied'] is False
    assert result['reason'] == 'final_validation_failed'

    payload['sourcePoseCameraReference']['camera']['sourceTimelineMappingIdentity'][
        'selectedFrameClockReceiptSha256'] = 'different-clock'
    monkeypatch.setattr(sequence_stabilization, 'contact_mask',
                        lambda *_args, **_kwargs: all_pinned.copy())
    assert not controlled_motion._verified_support_wrap_deferral(payload, source_phase=complete_phase)


def test_supported_fit_anatomy_gate_keeps_source_bounds_independent_of_spatial_reference():
    from exercise_motion_pkg.controlled_motion import (
        ANATOMY_FIT_MARGIN, fit_anatomy_constraint_reference,
        fit_anatomy_structure_residuals,
    )
    from exercise_motion_pkg.physical_validation import (
        anatomical_structure_residuals, validate_physical_motion,
    )
    from exercise_motion_pkg.anatomical_repair import repair_residuals

    names = ['pelvis', 'left_hip', 'right_hip', 'spine1', 'spine2', 'spine3', 'neck',
             'left_collar', 'right_collar', 'left_shoulder', 'right_shoulder',
             'left_knee', 'left_ankle', 'left_foot', 'right_knee', 'right_ankle', 'right_foot']

    def pose(shoulder_bend_degrees):
        deviation = np.deg2rad(180. - shoulder_bend_degrees)
        shoulders = np.array([.5 * np.sin(deviation), .25 + .5 * np.cos(deviation), 0.])
        points = np.array([
            [0., 0., 0.], [-.1, 0., 0.], [.1, 0., 0.], [0., .25, 0.],
            [0., .5, 0.], [0., .75, 0.], [0., 1., 0.],
            [-.05, .75, .1], [-.05, .75, -.1],
            shoulders + [0., 0., .1], shoulders + [0., 0., -.1],
            [-.1, -.4, 0.], [-.1, -.8, 0.], [-.1, -.8, .2],
            [.1, -.4, 0.], [.1, -.8, 0.], [.1, -.8, .2],
        ])
        return points[None, :, :]

    source_reference = pose(145.)
    support_reference = pose(143.)
    fitted_points = pose(143.5)

    selected_source_reference = fit_anatomy_constraint_reference(source_reference)
    source_residuals = fit_anatomy_structure_residuals(
        fitted_points, names, selected_source_reference)
    selected_support_reference = fit_anatomy_constraint_reference(source_reference)
    supported_residuals = fit_anatomy_structure_residuals(
        fitted_points, names, selected_support_reference)
    expected_residuals, labels = repair_residuals(
        fitted_points, names, reference=selected_support_reference)
    bend_index = labels.index('anatomy_torso_bend:shoulders')
    # Ask the same hard validator used by both fit completion and materialization.
    source_gate = validate_physical_motion(
        fitted_points, names, reference=source_reference,
        anatomy_reference=support_reference)
    supported_gate = validate_physical_motion(
        fitted_points, names, reference=support_reference,
        anatomy_reference=selected_support_reference)
    assert not any(e.get('reason') == 'anatomy_torso_bend'
                   for e in source_gate['events'])
    assert any(e.get('reason') == 'anatomy_torso_bend'
               for e in supported_gate['events'])
    np.testing.assert_allclose(supported_residuals, expected_residuals)
    assert source_residuals[0, bend_index] > 1e-6
    assert supported_residuals[0, bend_index] > 1e-6
    assert fit_anatomy_constraint_reference(source_reference) is source_reference


def test_pipeline_reuse_skips_earlier_positional_repairs(monkeypatch):
    from exercise_motion_pkg.scene_placement import normalize_scene_placement
    payload=normalize_scene_placement(accepted_payload())
    payload['controlledMotionFit']['outputPoseDigest'] = pose_digest(payload)
    payload['controlledMotionFit']['fitSourceEvidenceDigest'] = (
        controlled_motion_fit_source_evidence_digest(payload)
    )
    before=pose_digest(payload)

    def unexpected_repair(*args,**kwargs):
        raise AssertionError('An accepted fixed rig must not be modified on reuse')

    monkeypatch.setattr(bake_and_rank,'constrain_to_source_articulation_envelope',unexpected_repair)
    result,_=bake_and_rank.constrain_baked_payload_to_source_articulation(payload,use_controlled_motion_fit=True)
    assert result is payload
    assert result['controlledMotionFit']['reused']
    assert pose_digest(result)==before


def test_support_materialization_keeps_source_and_rig_evidence_separate(monkeypatch):
    from exercise_motion_pkg import body_support_observation, controlled_motion, support_geometry
    from exercise_motion_pkg import scene_placement
    from exercise_motion_pkg.contact_constraints import (
        _source_evidence_from_motion_space, motion_space_support_evidence,
        fit_motion_space_support_evidence_scope,
    )
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    payload = accepted_payload()
    payload['sourcePoseCameraReference'] = {
        'camera': {'bilateralAssignment': 'swapped'},
    }
    source_evidence = {
        'contacts': [{'jointName': 'left_foot', 'contactMotion': 'stationary'}],
    }
    rig_evidence = {
        'contacts': [{'jointName': 'right_foot', 'contactMotion': 'stationary'}],
        'bodySupport': {'required': True, 'status': 'confirmed',
                        'stationaryJoints': ['right_foot']},
    }
    payload['sourceFootSupportEvidence'] = copy.deepcopy(source_evidence)
    source_view = motion_space_support_evidence(payload)
    payload['motionSpaceSupportEvidence'] = copy.deepcopy(source_view)
    monkeypatch.setattr(support_geometry, 'declare_support_requirements', lambda *_: None)
    for name in ('materialize_body_support', 'materialize_hand_support',
                 'materialize_observed_ground_contacts'):
        monkeypatch.setattr(body_support_observation, name, lambda *_: None)
    monkeypatch.setattr(body_support_observation, 'materialize_stationary_sole_support',
                        lambda _: copy.deepcopy(rig_evidence))
    monkeypatch.setattr(controlled_motion, 'can_reuse_controlled_motion', lambda _: True)
    monkeypatch.setattr(scene_placement, 'normalize_scene_placement', lambda value: value)
    payload['controlledMotionFit']['fitSourceEvidenceDigest'] = (
        controlled_motion_fit_source_evidence_digest(payload)
    )

    result, _ = bake_and_rank.constrain_baked_payload_to_source_articulation(payload)

    assert result is payload
    assert result['sourceFootSupportEvidence'] == source_evidence
    assert result['motionSpaceSupportEvidence'] == source_view
    assert _source_evidence_from_motion_space(result['motionSpaceSupportEvidence']) == source_evidence
    portable_digest = pose_digest(result)
    with fit_motion_space_support_evidence_scope(result, rig_evidence):
        assert pose_digest(result) == portable_digest

    monkeypatch.setattr(body_support_observation, 'materialize_stationary_sole_support',
                        lambda _: copy.deepcopy(rig_evidence))
    pinned = contact_mask(result, result['jointNames'], len(result['frames']))
    assert pinned[:, result['jointNames'].index('right_foot')].all()
    assert not pinned[:, result['jointNames'].index('left_foot')].any()


def test_stale_materialized_source_recovers_only_matching_valid_rig_view():
    from exercise_motion_pkg import controlled_motion
    from exercise_motion_pkg.contact_constraints import (
        _source_evidence_from_motion_space, _support_evidence_digest,
        _swap_support_evidence_sides, motion_space_support_evidence,
        source_support_mapping_unresolved,
    )

    canonical = {
        'contacts': [{'jointName': 'left_foot', 'contactMotion': 'stationary'}],
        'bodySupportObservation': {'status': 'observed', 'sourceVideoSha256': 'video-A'},
    }
    source_digest = _support_evidence_digest(canonical)
    mapped = _swap_support_evidence_sides(canonical)
    mapped['motionSpaceMapping'] = {
        'bilateralAssignment': 'swapped', 'sourceEvidenceSha256': source_digest,
    }
    stale_source = copy.deepcopy(mapped)
    stale_source['bodySupport'] = {'stationaryJoints': ['right_foot']}
    payload = {
        'sourceFootSupportEvidence': stale_source,
        'motionSpaceSupportEvidence': copy.deepcopy(mapped),
        'sourcePoseCameraReference': {'camera': {'bilateralAssignment': 'swapped'}},
    }

    assert _source_evidence_from_motion_space(stale_source) is None
    assert _source_evidence_from_motion_space(mapped) == canonical
    assert motion_space_support_evidence(payload) == mapped
    assert not source_support_mapping_unresolved(payload)

    changed_contact = copy.deepcopy(payload)
    changed_contact['sourceFootSupportEvidence']['contacts'][0][
        'contactMotion'] = 'airborne'
    assert motion_space_support_evidence(changed_contact) == {}
    assert source_support_mapping_unresolved(changed_contact)

    changed_identity = copy.deepcopy(payload)
    changed_identity['sourceFootSupportEvidence']['bodySupportObservation'][
        'sourceVideoSha256'] = 'video-B'
    assert motion_space_support_evidence(changed_identity) == {}
    assert source_support_mapping_unresolved(changed_identity)

    mismatched = copy.deepcopy(payload)
    mismatched['motionSpaceSupportEvidence']['motionSpaceMapping'][
        'sourceEvidenceSha256'] = '0' * 64
    assert motion_space_support_evidence(mismatched) == {}
    assert source_support_mapping_unresolved(mismatched)

    legacy_fit = accepted_payload()
    legacy_fit['sourcePoseCameraReference'] = payload['sourcePoseCameraReference']
    legacy_fit['sourceFootSupportEvidence'] = stale_source
    legacy_fit['motionSpaceSupportEvidence'] = mismatched['motionSpaceSupportEvidence']
    assert not can_reuse_controlled_motion(legacy_fit)
    _, report = controlled_motion.fit_controlled_motion(legacy_fit)
    assert report['reason'] == 'source_support_mapping_unresolved'


def test_timed_contact_rematerialization_preserves_swapped_source_digest():
    from exercise_motion_pkg.body_support_observation import (
        materialize_timed_visual_contact_points,
    )
    from exercise_motion_pkg.contact_constraints import (
        _source_evidence_from_motion_space, motion_space_support_evidence,
    )

    digest = 'c' * 64
    canonical = {
        'sourceVideoSha256': digest,
        'footPatchEvidence': {'sourceVideoSha256': digest},
        'bodySupportObservation': {
            'source': 'exact_source_visual_support_observation',
            'status': 'observed',
            'sourceVideoSha256': digest,
            'contactTimeline': {
                'schemaVersion': 1,
                'policyVersion': 1,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest,
                'sourceClock': 'video_frame_zero_seconds',
                'status': 'observed',
                'requestSha256': 'request',
                'responseSha256': 'response',
                'samples': [{
                    'sampleId': 'left-static-sole',
                    'sourceTimeSec': 0.5,
                    'sourceFrameIndex': 15,
                    'sourceFps': 30.0,
                    'sourcePoseFrameIndex': 1,
                    'side': 'left',
                    'contactState': 'full_sole',
                    'surface': 'ground',
                    'visible': True,
                    'sourceTrackStationary': True,
                }],
            },
        },
    }
    payload = {
        'sourceFootSupportEvidence': copy.deepcopy(canonical),
        'sourcePoseCameraReference': {
            'camera': {'bilateralAssignment': 'swapped'},
        },
    }
    mapped = motion_space_support_evidence(payload)
    frames = [{'sourceTimeSec': 0.5}]

    materialize_timed_visual_contact_points(mapped, frames, ['left_foot', 'right_foot'])
    assert len(mapped['supportContacts']) == 1
    assert mapped['supportContacts'][0]['jointName'] == 'right_foot'
    assert _source_evidence_from_motion_space(mapped) == canonical

    materialize_timed_visual_contact_points(mapped, frames, ['left_foot', 'right_foot'])
    assert len(mapped['supportContacts']) == 1
    assert _source_evidence_from_motion_space(mapped) == canonical
    assert payload['sourceFootSupportEvidence'] == canonical


def test_validated_fit_owns_final_pose_and_preserves_source_evidence(monkeypatch):
    import copy
    from exercise_motion_pkg import controlled_motion, sequence_stabilization

    payload = accepted_payload()
    original_source_tracks = [copy.deepcopy(frame['sourceJoints']) for frame in payload['frames']]
    source_heel_events = {
        'heelEvents': [{'side': 'right', 'frameIndex': 3, 'amplitude': 0.04}],
        'acceptedIntervalSeconds': [0.0, 6.0 / 30.0],
    }
    payload['sourceFootSupportEvidence'] = copy.deepcopy(source_heel_events)
    payload.pop('controlledMotionFit')
    fitted_frames = []

    def fake_fit(candidate, **kwargs):
        fitted = copy.deepcopy(candidate)
        fitted_frames.append(copy.deepcopy(fitted['frames']))
        report = {
            'applied': True,
            'strategy': CONTROLLED_MOTION_STRATEGY,
            'checks': dict.fromkeys(REQUIRED_FIT_CHECKS, True),
            'outputPoseDigest': pose_digest(fitted),
            'fitSourceEvidenceDigest': controlled_motion_fit_source_evidence_digest(fitted),
        }
        return fitted, report

    def fail_if_stabilized(candidate):
        raise AssertionError('validated controlled-fit geometry must not be mutated downstream')

    monkeypatch.setattr(controlled_motion, 'fit_controlled_motion', fake_fit)
    monkeypatch.setattr(sequence_stabilization, 'stabilize_exported_sequence', fail_if_stabilized)

    result, _ = bake_and_rank.constrain_baked_payload_to_source_articulation(payload)

    assert result['frames'] == fitted_frames[0]
    assert [frame['sourceJoints'] for frame in result['frames']] == original_source_tracks
    assert result['sourceFootSupportEvidence'] == source_heel_events
    assert 'sequenceStabilization' not in result
    assert result['controlledMotionFit']['outputPoseDigest'] == pose_digest(result)
    assert result['controlledMotionFit']['fitSourceEvidenceDigest'] == (
        controlled_motion_fit_source_evidence_digest(result)
    )
    assert can_reuse_controlled_motion(result)


@pytest.mark.parametrize(
    'dependency_name',
    ('contact_constraints.py', 'temporal_quality.py'),
)
def test_persisted_fit_cache_is_rejected_after_constraint_code_changes(
    tmp_path,
    monkeypatch,
    dependency_name,
):
    from exercise_motion_pkg import fit_runtime

    source = tmp_path / dependency_name
    source.write_text("constraint_policy = 'before'", encoding='utf-8')
    monkeypatch.setattr(fit_runtime, 'fit_cache_source_paths', lambda: (source,))
    first = fit_runtime.CandidateFitSession(tmp_path)
    checkpoint = tmp_path / 'anatomy_repair_checkpoint.json'
    checkpoint.write_text(json.dumps({
        'version': 1,
        'namespace': first.cache_namespace,
        'repairs': {'stale': {'value': 1}},
        'trajectories': {},
    }), encoding='utf-8')

    source.write_text("constraint_policy = 'after'", encoding='utf-8')
    refreshed = fit_runtime.CandidateFitSession(tmp_path)

    assert refreshed.cache_namespace != first.cache_namespace
    assert refreshed.repairs == {}


def test_fit_cache_identity_includes_transitive_motion_constraint_dependencies():
    from exercise_motion_pkg import fit_runtime

    dependency_names = {path.name for path in fit_runtime.fit_cache_source_paths()}

    assert {
        'fit_runtime.py',
        'trajectory_restoration.py',
        'body_surface_contacts.py',
        'body_surface_geometry.py',
        'contact_heel_pitch.py',
        'contact_heel_repair.py',
        'contact_interpolation.py',
        'joint_plant_initialization.py',
        'foot_kinematics.py',
        'ground_contact_plane.py',
        'motion_placement.py',
        'smpl_joint_names.py',
        'structural_refinement.py',
        'temporal_quality.py',
    } <= dependency_names


def test_fit_cache_identity_covers_local_imports_of_tracked_modules():
    from exercise_motion_pkg import fit_runtime

    package_dir = Path(fit_runtime.__file__).parent
    tracked_names = {Path(name).stem for name in fit_runtime.FIT_CACHE_SOURCE_MODULES}
    uncovered = set()
    for module_name in tracked_names:
        source_path = package_dir / f'{module_name}.py'
        syntax_tree = ast.parse(source_path.read_text(encoding='utf-8'))
        imported_names = set()
        for node in ast.walk(syntax_tree):
            if isinstance(node, ast.ImportFrom):
                if node.level == 1:
                    if node.module:
                        imported_names.add(node.module.split('.')[0])
                    else:
                        imported_names.update(alias.name.split('.')[0] for alias in node.names)
                elif (
                    node.level == 0
                    and node.module
                    and node.module.startswith('exercise_motion_pkg.')
                ):
                    imported_names.add(node.module.split('.')[1])
            elif isinstance(node, ast.Import):
                imported_names.update(
                    alias.name.split('.')[1]
                    for alias in node.names
                    if alias.name.startswith('exercise_motion_pkg.')
                )
        uncovered.update(
            name for name in imported_names
            if (package_dir / f'{name}.py').is_file()
            and name not in tracked_names
            and name != 'bake_and_rank'
        )

    assert uncovered == set()


def test_modified_contact_evidence_and_incomplete_reports_cannot_reuse():
    payload=accepted_payload()
    assert can_reuse_controlled_motion(payload)
    payload['sourceFootSupportEvidence']={'contacts':[]}
    assert not can_reuse_controlled_motion(payload)
    payload=accepted_payload()
    payload['controlledMotionFit']['checks'].pop('playback')
    assert not can_reuse_controlled_motion(payload)
    payload=accepted_payload()
    payload['controlledMotionFit']['strategy']='fixed_rig_controlled_motion_v51_contact_boundary_consistency'
    assert not can_reuse_controlled_motion(payload)


def test_fit_from_before_selected_interval_constraints_cannot_be_reused():
    payload = accepted_payload()
    payload['controlledMotionFit']['strategy'] = (
        'fixed_rig_controlled_motion_v57_source_projection_constraint'
    )
    assert not can_reuse_controlled_motion(payload)


def test_fit_reuse_is_invalidated_when_source_fit_evidence_changes():
    from exercise_motion_pkg.controlled_motion import controlled_motion_fit_source_evidence_digest

    payload = accepted_payload()
    payload['artifactState'] = {
        'selectionEvidence': {
            'cycleSelection': {
                'interval': {'startFrame': 12, 'endFrame': 48, 'startTimeSec': 0.4, 'endTimeSec': 1.6}
            }
        }
    }
    payload['sourcePoseCameraReference'] = {
        'camera': {'cameraRotation': [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
        'sourcePose': {'frames': [{'timeSec': 0.4, 'joints': {'pelvis': [0, 0, 0]}}]},
    }
    payload['controlledMotionFit']['fitSourceEvidenceDigest'] = (
        controlled_motion_fit_source_evidence_digest(payload)
    )
    assert can_reuse_controlled_motion(payload)

    payload['artifactState']['selectionEvidence']['cycleSelection']['interval']['startFrame'] = 15
    assert not can_reuse_controlled_motion(payload)

    camera_payload = accepted_payload()
    camera_payload['sourcePoseCameraReference'] = {
        'camera': {'cameraRotation': [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
        'sourcePose': {'frames': [{'sourceTimeSec': 0.0, 'joints': {'pelvis': [0, 0, 0]}}]},
    }
    camera_payload['controlledMotionFit']['fitSourceEvidenceDigest'] = (
        controlled_motion_fit_source_evidence_digest(camera_payload)
    )
    assert can_reuse_controlled_motion(camera_payload)
    camera_payload['sourcePoseCameraReference']['camera']['cameraRotation'][0][0] = 0.99
    assert not can_reuse_controlled_motion(camera_payload)


def test_fit_source_identity_binds_support_and_articulation_inputs():
    from exercise_motion_pkg.contact_constraints import motion_space_support_evidence
    from exercise_motion_pkg.controlled_motion import controlled_motion_fit_source_evidence_digest

    payload = accepted_payload()
    payload['sourcePoseCameraReference'] = {
        'camera': {'bilateralAssignment': 'swapped'},
    }
    payload['sourceFootSupportEvidence'] = {
        'contacts': [{
            'jointName': 'left_ankle',
            'startFrame': 0,
            'endFrame': 6,
            'contactMotion': 'stationary',
        }],
    }
    source_digest = controlled_motion_fit_source_evidence_digest(payload)
    mapped_support = motion_space_support_evidence(payload)
    assert payload['sourceFootSupportEvidence']['contacts'][0]['jointName'] == 'left_ankle'
    assert mapped_support['contacts'][0]['jointName'] == 'right_ankle'
    assert controlled_motion_fit_source_evidence_digest(payload) == source_digest

    changed_support = copy.deepcopy(payload)
    changed_support['sourceFootSupportEvidence']['contacts'][0]['startFrame'] = 1
    assert controlled_motion_fit_source_evidence_digest(changed_support) != source_digest

    changed_source_pose = copy.deepcopy(payload)
    changed_source_pose['frames'][0]['sourceJoints']['pelvis'][0] += 0.01
    assert controlled_motion_fit_source_evidence_digest(changed_source_pose) != source_digest

    changed_articulation_reference = copy.deepcopy(payload)
    changed_articulation_reference['frames'][0]['controlledArticulationReferenceJoints'] = copy.deepcopy(
        changed_articulation_reference['frames'][0]['joints']
    )
    changed_articulation_reference['frames'][0]['controlledArticulationReferenceJoints']['pelvis'][0] += 0.01
    assert controlled_motion_fit_source_evidence_digest(changed_articulation_reference) != source_digest

    changed_support_surface = copy.deepcopy(payload)
    changed_support_surface['elevatedSupportSurfaces'] = [{'kind': 'bench', 'heightMeters': 0.4}]
    assert controlled_motion_fit_source_evidence_digest(changed_support_surface) != source_digest

    changed_foot_rest_pitch = copy.deepcopy(payload)
    changed_foot_rest_pitch['footRestPitchRadians'] = {'left': 0.1}
    assert controlled_motion_fit_source_evidence_digest(changed_foot_rest_pitch) != source_digest

    changed_bridge_authority = copy.deepcopy(payload)
    changed_bridge_authority['frames'][0]['syntheticLoopBridge'] = True
    assert controlled_motion_fit_source_evidence_digest(changed_bridge_authority) != source_digest

    payload['controlledMotionFit']['fitSourceEvidenceDigest'] = source_digest
    payload['controlledMotionFit']['outputPoseDigest'] = pose_digest(payload)
    assert can_reuse_controlled_motion(payload)
    stale_strategy = copy.deepcopy(payload)
    stale_strategy['controlledMotionFit']['strategy'] = (
        'fixed_rig_controlled_motion_v96_contact_foot_playback')
    assert not can_reuse_controlled_motion(stale_strategy)
    changed_fit_gate = copy.deepcopy(payload)
    changed_fit_gate['postBakeForefootContactConstraint'] = {'requiresReconstruction': True}
    assert not can_reuse_controlled_motion(changed_fit_gate)


def test_loop_reuse_requires_a_positive_seam_result():
    payload=accepted_payload()
    payload['loop']['enabled']=True
    payload['controlledMotionFit']['outputPoseDigest']=pose_digest(payload)
    assert not can_reuse_controlled_motion(payload)
    payload['controlledMotionFit']['checks']['loopSeam']=True
    assert can_reuse_controlled_motion(payload)


def test_open_seam_reuse_does_not_require_closed_loop_seam():
    payload = accepted_payload()
    payload['loop'] = {
        'enabled': True,
        'transition': 'requires_cycle_repair',
        'restartFadeMillis': 0,
    }
    fit = payload['controlledMotionFit']
    fit['reason'] = 'validated_controlled_motion_open_seam'
    fit['loopSeamOpen'] = True
    fit['checks']['loopSeam'] = False
    fit['outputPoseDigest'] = pose_digest(payload)
    assert can_reuse_controlled_motion(payload)
    # Unrelated body check failures still block reuse.
    fit['checks']['trajectoryFit'] = False
    assert not can_reuse_controlled_motion(payload)


def test_default_controlled_path_preserves_original_reference_and_skips_legacy_repairs(monkeypatch):
    from exercise_motion_pkg import controlled_motion

    payload = accepted_payload()
    payload.pop('fixedRig')
    payload.pop('controlledMotionFit')
    payload['postBakeForefootContactConstraint'] = {'requiresReconstruction': True}
    original = copy.deepcopy(payload)

    def guard(source, proposed, **kwargs):
        proposed.frames[0].joints['head'] = (0.1, 1.5, 0.2)
        return proposed, {'applied': True}

    def unexpected_repair(*args, **kwargs):
        raise AssertionError('Legacy positional repairs must not precede the unified fit')

    def fit(working):
        assert 'postBakeForefootContactConstraint' not in working
        assert working['controlledMotionInputRepairs']['postBakeForefootContactConstraint']['requiresReconstruction']
        assert working['frames'][0]['joints']['head'] == [0.1, 1.5, 0.2]
        for frame, source in zip(working['frames'], original['frames']):
            assert frame['controlledArticulationReferenceJoints'] == source['sourceJoints']
        return working, {'applied': True}

    monkeypatch.setattr(bake_and_rank, 'constrain_to_source_articulation_envelope', guard)
    for name in ('suppress_post_ik_anatomical_spikes', 'stabilize_distal_foot_heading',
                 'stabilize_forefoot_ground_contacts'):
        monkeypatch.setattr(bake_and_rank, name, unexpected_repair)
    monkeypatch.setattr(controlled_motion, 'fit_controlled_motion', fit)
    result, _ = bake_and_rank.constrain_baked_payload_to_source_articulation(payload)
    assert result['controlledMotionFit']['applied']
    assert payload == original


def test_failed_controlled_fit_keeps_original_pose(monkeypatch):
    from exercise_motion_pkg import controlled_motion

    payload = accepted_payload()
    payload.pop('fixedRig')
    payload.pop('controlledMotionFit')
    original = copy.deepcopy(payload)
    monkeypatch.setattr(bake_and_rank, 'constrain_to_source_articulation_envelope',
                        lambda source, proposed, **kwargs: (proposed, {'applied': False}))

    def reject(working):
        working['frames'][0]['joints']['head'] = [99, 99, 99]
        return working, {'applied': False, 'reason': 'fit_validation_failed'}

    monkeypatch.setattr(controlled_motion, 'fit_controlled_motion', reject)
    result, _ = bake_and_rank.constrain_baked_payload_to_source_articulation(
        payload, use_controlled_motion_fit=True)
    assert result['frames'] == original['frames']
    assert not result['controlledMotionFit']['applied']
    assert payload == original


def test_controlled_fit_receives_remaining_exercise_timeout(monkeypatch):
    from exercise_motion_pkg import controlled_motion

    payload = accepted_payload()
    payload.pop('fixedRig')
    payload.pop('controlledMotionFit')
    monkeypatch.setattr(
        bake_and_rank,
        'constrain_to_source_articulation_envelope',
        lambda source, proposed, **kwargs: (proposed, {'applied': False}),
    )
    captured = {}

    def fit(working, **kwargs):
        captured.update(kwargs)
        return working, {'applied': False, 'reason': 'fit_timeout'}

    monkeypatch.setattr(controlled_motion, 'fit_controlled_motion', fit)
    bake_and_rank.constrain_baked_payload_to_source_articulation(
        payload,
        timeout_seconds=17.5,
    )
    assert captured == {'timeout_seconds': 17.5}


def test_controlled_fit_queue_wait_uses_exercise_timeout(monkeypatch):
    from contextlib import contextmanager
    from exercise_motion_pkg import fit_runtime
    from exercise_motion_pkg import controlled_motion

    captured = {}

    @contextmanager
    def delayed_slot(*, timeout_seconds=None):
        captured['slotTimeoutSeconds'] = timeout_seconds
        yield 4.0

    def fit(payload, **kwargs):
        captured.update(kwargs)
        return payload, {'applied': False, 'reason': 'fit_timeout'}

    monkeypatch.setattr(fit_runtime, 'cpu_fit_slot', delayed_slot)
    monkeypatch.setattr(controlled_motion, '_fit_candidate_motion', fit)
    controlled_motion.fit_controlled_motion({}, timeout_seconds=10.0)
    assert captured == {
        'slotTimeoutSeconds': 10.0,
        'max_evaluations': None,
        'timeout_seconds': 6.0,
    }


def test_global_translation_jitter_cannot_mask_an_introduced_limb_spike():
    from exercise_motion_pkg.controlled_motion import relative_motion_quality

    payload = accepted_payload()
    names = payload['jointNames']
    source = np.asarray([[f['joints'][n] for n in names] for f in payload['frames']])
    translated = source.copy()
    translated[3, :, 0] += .3
    candidate = source.copy()
    candidate[3, names.index('left_wrist'), 0] += .08
    # The old world-space check regards removing the larger translation spike
    # as improvement even though the originally still wrist now twitches.
    rms = lambda p: np.sqrt(np.mean(np.diff(p, n=2, axis=0)**2, axis=(0, 2)))
    assert np.all(rms(candidate) <= np.maximum(rms(translated)*1.2, .003))
    report = relative_motion_quality(candidate, translated, names, 30.)
    assert not report['relativeJointShake']
    assert report['introducedSpikes']['severe']
    assert relative_motion_quality(source, translated, names, 30.)['relativeJointShake']


def test_temporal_fit_budget_is_consistent_across_duration_and_frame_rate():
    from exercise_motion_pkg.controlled_motion import temporal_fit_scales, relative_motion_quality

    payload = accepted_payload()
    names = payload['jointNames']
    pose = np.asarray([payload['frames'][0]['joints'][name] for name in names])
    for count, fps in ((10, 30.), (40, 30.), (40, 60.)):
        source = np.tile(pose, (count, 1, 1))
        candidate = source.copy()
        wrist = names.index('left_wrist')
        # A known second difference at 80% of the independent jitter limit.
        amplitude = .8*.003*(30./fps)**2*np.sqrt(3)/4
        candidate[:, wrist, 0] += np.where(np.arange(count)%2, amplitude, -amplitude)
        scale, _ = temporal_fit_scales(source, names, fps)
        normalized = np.diff(candidate[:, wrist]-candidate[:, names.index('pelvis')], n=2, axis=0)/scale[wrist]
        np.testing.assert_allclose(np.linalg.norm(normalized), 1., atol=1e-10)
        assert relative_motion_quality(candidate, source, names, fps)['relativeJointShake']


def test_final_acceptance_requires_the_complete_current_fit_contract():
    payload = accepted_payload()
    metrics = bake_and_rank.compute_kinematic_plausibility_metrics_from_payload(payload)
    assert 'controlled_motion_fit_rejected' not in metrics['artifactReasons']
    payload['controlledMotionFit']['checks'].pop('relativeJointShake')
    metrics = bake_and_rank.compute_kinematic_plausibility_metrics_from_payload(payload)
    assert 'controlled_motion_fit_rejected' in metrics['artifactReasons']


def test_proven_source_boundary_failure_is_not_incomplete_motion_processing():
    payload = accepted_payload()
    payload['controlledMotionFit'] = {
        'applied': False, 'reason': 'source_cycle_preflight_rejected',
        'boundaryMotion': {'passed': False, 'failureOwner': 'source',
                           'rejectionReasons': ['source_boundary_tangents_incompatible']},
    }
    metrics = bake_and_rank.compute_kinematic_plausibility_metrics_from_payload(payload)
    assert 'source_cycle_boundary_incompatible' in metrics['artifactReasons']
    assert 'controlled_motion_cycle_proposal_unavailable' not in metrics['processingIncompleteReasons']


def test_terminal_fit_rejection_falls_back_only_for_unchanged_raw_reconstruction_pose():
    from exercise_motion_pkg.controlled_motion import REQUIRED_FIT_CHECKS, controlled_motion_fit_raw_fallback
    from exercise_motion_pkg.sequence_stabilization import pose_digest

    payload = accepted_payload()
    fit_input_digest = pose_digest(payload)
    failed_checks = dict.fromkeys(REQUIRED_FIT_CHECKS, True)
    failed_checks.update(anatomy=False, contacts=False, trajectoryFit=False)
    payload['controlledMotionFit'] = {
        'applied': False,
        'reason': 'retained_interval_skipped_after_unreachable_core_cycle_failure',
        'cycleSelectionAttempts': [{
            'reason': 'fit_validation_failed',
            'fitReport': {
                'applied': False,
                'reason': 'fit_validation_failed',
                'termination': 'unreachable_conflict',
                'checks': failed_checks,
            },
        }, {
            'reason': 'retained_interval_skipped_after_unreachable_core_cycle_failure',
            'fitReport': {
                'applied': False,
                'reason': 'retained_interval_skipped_after_unreachable_core_cycle_failure',
                'checks': {},
            },
        }],
        'fitInputPoseDigest': fit_input_digest,
    }
    payload['controlledMotionFit']['fitSourceEvidenceDigest'] = (
        controlled_motion_fit_source_evidence_digest(payload)
    )
    assert controlled_motion_fit_raw_fallback(payload) is None

    payload['rawMotionFallbackEvidence'] = {
        'schemaVersion': 1,
        'rawReconstructionMotionGatePassed': True,
        'rawReconstructionMotionGateFingerprint': 'a' * 64,
    }
    metrics = bake_and_rank.compute_kinematic_plausibility_metrics_from_payload(payload)
    assert 'controlled_motion_fit_rejected' not in metrics['artifactReasons']
    assert metrics['controlledMotionFitFallback']['used'] is True

    payload['frames'][1]['joints']['left_wrist'][0] += 0.01
    metrics = bake_and_rank.compute_kinematic_plausibility_metrics_from_payload(payload)
    assert 'controlled_motion_fit_rejected' in metrics['artifactReasons']
    assert controlled_motion_fit_raw_fallback(payload) is None


def test_final_validation_catches_whole_body_jump_independently_of_fit_report():
    payload = accepted_payload()
    payload.pop('fixedRig')
    payload.pop('controlledMotionFit')
    for frame in payload['frames'][3:]:
        for point in frame['joints'].values():
            point[0] += .3
    metrics = bake_and_rank.compute_kinematic_plausibility_metrics_from_payload(payload)
    assert 'root_translation_discontinuity' in metrics['artifactReasons']
    assert metrics['rootMotion']['frames'] == [2, 3]

def test_complete_source_phase_requires_bilateral_endpoint_pins_for_support_wrap_deferral(monkeypatch):
    from exercise_motion_pkg import body_support_observation, support_geometry, sequence_stabilization
    identity = dict(selectedSegmentSha256='source', parentSourceSha256='parent',
                    selectedFrameClockReceiptSha256='clock', sourcePosePayloadSha256='pose')
    payload = {'sourcePoseCameraReference':{
        'camera':{'available':True, 'sourceTimelineMappingIdentity':identity},
        'sourceTimelineMapping':{'schemaVersion':1, 'verified':True,
                                'mappingKind':'selected_segment_to_parent_source', **identity},
        'sourcePose':{'frames':[]}},
        'sourceFootSupportEvidence':{'sourceVideoSha256':'source'},
        'jointNames':['left_ankle','left_foot','right_ankle','right_foot'],
        'frames':[{'joints':{}} for _ in range(4)],
        'sourceCyclePreflight':[{'selection':{'startFrame':0,'stopFrameExclusive':4},
                                'sourcePhase':{'required':True,'passed':True}}]}
    monkeypatch.setattr(body_support_observation,'materialize_stationary_sole_support',lambda _: {})
    monkeypatch.setattr(support_geometry,'support_contact_readiness',lambda *a, **k: {'passed':True})
    pins=np.zeros((4,4),dtype=bool);pins[1,0]=True
    monkeypatch.setattr(sequence_stabilization,'contact_mask',lambda *a, **k: pins)
    assert not controlled_motion._verified_support_wrap_deferral(payload)
    assert not controlled_motion._verified_support_wrap_deferral(payload,{'startFrame':1,'stopFrameExclusive':3})
    pins[:] = True
    assert controlled_motion._verified_support_wrap_deferral(payload)
    payload['sourceCyclePreflight'][0]['sourcePhase']['passed']=False
    assert not controlled_motion._verified_support_wrap_deferral(payload)

    payload.pop('sourceCyclePreflight')
    fresh_phase = {'required': True, 'passed': True, 'hasSingleMajorCycle': True}
    assert controlled_motion._verified_support_wrap_deferral(payload, source_phase=fresh_phase)
    assert not controlled_motion._verified_support_wrap_deferral(
        payload, source_phase={**fresh_phase, 'hasSingleMajorCycle': False})
    pins[:] = False
    pins[[0, 2], :] = True
    assert controlled_motion._verified_support_wrap_deferral(
        payload, {'startFrame': 0, 'stopFrameExclusive': 2}, source_phase=fresh_phase)


def test_unresolved_support_does_not_reuse_an_otherwise_accepted_fit():
    candidate = accepted_payload()
    assert can_reuse_controlled_motion(candidate)
    candidate['controlledMotionFit']['sourceSupportAuthority'] = {
        'status': 'unresolved', 'required': False, 'passed': None,
    }
    assert not can_reuse_controlled_motion(candidate)

def test_materialized_cycle_phase_receipt_keeps_exact_native_interval_authority():
    from copy import deepcopy
    from exercise_motion_pkg import controlled_motion
    interval = {'startFrame':0,'endFrame':2,'startTimeSec':0.,'endTimeSec':2/30}
    cycle = {'selectionId':'retained-cycle','interval':dict(interval),'sourceInterval':dict(interval)}
    payload = {'fps':30.,'loop':{'enabled':True},
        'frames':[{'sourceFrameIndex':i,'sourceTimeSec':i/30}for i in range(3)],
        'artifactState':{'selectionEvidence':{'cycleSelection':cycle}},
        'sourceCyclePreflight':[{'reason':'no_feasible_observed_cycle'}],
        'selectedIntervalSourcePhasePreflight':{
            'selection':{'source':'artifactState.selectionEvidence.cycleSelection','selection':deepcopy(cycle)},
            'required':True,'passed':True,
            'sourcePhase':{'required':True,'passed':True,'hasSingleMajorCycle':True}}}
    assert controlled_motion._source_phase_confirms_interval(payload)
    assert not controlled_motion._source_phase_confirms_interval(payload,{'startFrame':1,'stopFrameExclusive':3})
    wrong = deepcopy(payload)
    wrong['frames'][-1]['sourceTimeSec'] += .01
    assert not controlled_motion._source_phase_confirms_interval(wrong)
    wrong = deepcopy(payload)
    wrong['selectedIntervalSourcePhasePreflight']['selection']['selection']['sourceInterval']['endFrame'] = 1
    assert not controlled_motion._source_phase_confirms_interval(wrong)
    wrong = deepcopy(payload)
    wrong['selectedIntervalSourcePhasePreflight']['sourcePhase']['hasSingleMajorCycle'] = False
    assert not controlled_motion._source_phase_confirms_interval(wrong)
    # An old legacy pass cannot override an explicit current failed receipt.
    payload['sourceCyclePreflight'] = [{'selection':{'startFrame':0,'stopFrameExclusive':3},
                                      'sourcePhase':{'required':True,'passed':True}}]
    payload['selectedIntervalSourcePhasePreflight']['sourcePhase']['passed'] = False
    assert not controlled_motion._source_phase_confirms_interval(payload)
