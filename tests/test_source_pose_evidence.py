from copy import deepcopy
from pathlib import Path

import pytest

from exercise_motion_pkg.source_pose_evidence import audit_source_pose, verify_source_pose
from exercise_motion_pkg import bake_and_rank as bake


def reference():
    joints = {'left_shoulder': [.3, .3, 0], 'right_shoulder': [.7, .3, 0],
              'left_elbow': [.3, .4, 0], 'right_elbow': [.7, .4, 0],
              'left_wrist': [.3, .5, 0], 'right_wrist': [.7, .5, 0],
              'left_hip': [.4, .6, 0], 'right_hip': [.6, .6, 0],
              'left_knee': [.4, .75, 0], 'right_knee': [.6, .75, 0],
              'left_ankle': [.4, .9, 0], 'right_ankle': [.6, .9, 0],
              'pelvis': [.5, .6, 0], 'shoulders': [.5, .3, 0]}
    return {'coordinateSpace': 'normalized_image_xy', 'imageWidth': 600, 'imageHeight': 600,
            'frames': [{'sourceTimeSec': i/8, 'joints': deepcopy(joints),
                        'jointConfidence': {n: .99 for n in joints}} for i in range(12)]}


def corrupt(payload):
    result = deepcopy(payload)
    for frame in result['frames'][4:7]:
        frame['joints']['right_wrist'] = [.31, .5, 0]
    return result


def observations(payload):
    return {'available': True, 'source': 'independent_test_observer', 'frames': [
        {'timeSeconds': f['sourceTimeSec'], 'joints': {n: {'image': p[:2], 'confidence': .95}
         for n, p in f['joints'].items()}} for f in payload['frames']]}


def test_high_confidence_identity_failure_becomes_unknown_without_mutating_input():
    primary = corrupt(reference()); original = deepcopy(primary)
    result = audit_source_pose(primary)
    assert primary == original
    assert result['sourcePoseEvidenceAudit']['unresolved']
    assert len(result['sourcePoseEvidenceAudit']['events']) == 3
    assert 'right_wrist' not in result['frames'][5]['joints']
    assert 'shoulders' not in result['frames'][5]['joints']
    assert result['frames'][5]['jointConfidence']['right_wrist'] == 0
    assert result['frames'][3] == primary['frames'][3]


def test_independent_anchored_track_recovers_faulty_chain():
    good = reference(); result = audit_source_pose(corrupt(good), observations(good))
    assert not result['sourcePoseEvidenceAudit']['unresolved']
    assert result['frames'][5]['joints']['right_wrist'] == good['frames'][5]['joints']['right_wrist']
    assert all(e['status'] == 'recovered' for e in result['sourcePoseEvidenceAudit']['events'])


def test_wrong_independent_person_cannot_replace_source():
    other = observations(reference())
    for frame in other['frames']:
        for point in frame['joints'].values():
            point['image'][0] += .3
    result = audit_source_pose(corrupt(reference()), other)
    assert result['sourcePoseEvidenceAudit']['unresolved']


def test_independently_confirmed_real_crossing_is_retained():
    actual = corrupt(reference())
    result = audit_source_pose(actual, observations(actual))
    assert not result['sourcePoseEvidenceAudit']['unresolved']
    assert result['frames'][5]['joints']['right_wrist'] == actual['frames'][5]['joints']['right_wrist']


def test_close_hands_and_smooth_crossing_do_not_trigger_recovery(monkeypatch):
    from exercise_motion_pkg import foot_contact_observation as observer
    monkeypatch.setattr(observer, 'observe_foot_landmarks', lambda *a: pytest.fail('Unneeded inference'))
    for close in (True, False):
        source = reference()
        for i, frame in enumerate(source['frames']):
            frame['joints']['right_wrist'][0] = .32 if close else .7-i*.035
        assert not verify_source_pose(source, Path('unused.mp4'))['sourcePoseEvidenceAudit']['events']


def test_unresolved_source_cannot_be_overridden_or_used_as_pose_verdict():
    source = audit_source_pose(corrupt(reference()))
    assert not bake.exact_source_validation_effectively_passed({
        'passed': True, 'poseFailureOverriddenByVlm': True,
        'sourcePoseEvidenceAudit': source['sourcePoseEvidenceAudit']})
    result = bake.materialized_source_pose_fidelity_metrics(
        source_pose_payload=source, output_motion_payload={}, required=True)
    assert not result['available'] and not result['passed']
    assert result['skippedReason'] == 'source_pose_reference_unreliable'
