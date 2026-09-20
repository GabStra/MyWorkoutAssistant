"""Ensure accepted rigs are not sent through positional repairs on reuse."""
import json
import copy
from pathlib import Path

import numpy as np

from exercise_motion_pkg import bake_and_rank
from exercise_motion_pkg.controlled_motion import (
    CONTROLLED_MOTION_STRATEGY, REQUIRED_FIT_CHECKS, FixedRig,
    can_reuse_controlled_motion,
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
    return payload


def test_pipeline_reuse_skips_earlier_positional_repairs(monkeypatch):
    from exercise_motion_pkg.scene_placement import normalize_scene_placement
    payload=normalize_scene_placement(accepted_payload())
    before=pose_digest(payload)

    def unexpected_repair(*args,**kwargs):
        raise AssertionError('An accepted fixed rig must not be modified on reuse')

    monkeypatch.setattr(bake_and_rank,'constrain_to_source_articulation_envelope',unexpected_repair)
    result,_=bake_and_rank.constrain_baked_payload_to_source_articulation(payload,use_controlled_motion_fit=True)
    assert result is payload
    assert result['controlledMotionFit']['reused']
    assert pose_digest(result)==before


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
