import copy
from exercise_motion_pkg import bake_and_rank as bake


def _anchored_source(with_head):
    frames = []
    for index, offset in enumerate([0., 0., .06, .12, .18, .12, .06, 0., 0.]):
        joints = {'pelvis': [0., .5 + offset, 0.],
                  'left_shoulder': [-.1, .3 + offset, 0.],
                  'right_shoulder': [.1, .3 + offset, 0.],
                  'left_hip': [-.08, .5 + offset, 0.],
                  'right_hip': [.08, .5 + offset, 0.],
                  'left_elbow': [-.13, .25 + offset * .5, 0.],
                  'right_elbow': [.13, .25 + offset * .5, 0.],
                  'left_wrist': [-.12, .15, 0.], 'right_wrist': [.12, .15, 0.],
                  'left_knee': [-.08, .7 + offset, 0.],
                  'right_knee': [.08, .7 + offset, 0.],
                  'left_ankle': [-.08, .8 + offset, 0.],
                  'right_ankle': [.08, .8 + offset, 0.]}
        if with_head:
            joints['nose'] = [0., .2 + offset, 0.]
        frames.append({'sourceTimeSec': index / 8., 'joints': joints})
    return {'rootJoint': 'pelvis', 'jointNames': list(frames[0]['joints']), 'frames': frames}


def _contract():
    return {'completionMode': 'return_to_start', 'observableMotionSpec': {
        'primaryMovingRegions': ['torso', 'upper_limb'], 'referenceRegions': ['head'],
        'primaryAxis': 'vertical', 'motionPattern': 'body_toward_anchor',
        'requiresReturnToStart': True, 'oneWayPartialIsInvalid': True, 'mustShowFullCycle': True}}


def test_body_anchor_cycle_requires_observed_relationship_not_wrist_cycle():
    missing = bake.full_repetition_phase_completeness_metrics_from_source_pose_payload(
        _anchored_source(False), exercise_name='Anchored body movement',
        ranking_payload={'exerciseMotionContract': _contract()})
    assert missing['hasCompleteMajorCycle']
    assert not missing['observableMotionMetrics']['passed']
    assert not missing['passed']
    cached = copy.deepcopy(missing)
    cached['passed'] = True
    cached['poseFailureOverriddenByVlm'] = True
    assert not bake.exact_source_validation_effectively_passed(cached)


def test_coco_face_reference_resolves_body_anchor_return_phase():
    complete = bake.full_repetition_phase_completeness_metrics_from_source_pose_payload(
        _anchored_source(True), exercise_name='Anchored body movement',
        ranking_payload={'exerciseMotionContract': _contract()})
    assert complete['observableMotionMetrics']['passed']
    assert complete['dominantJointSelection'] == 'observable_motion_spec_relative'
    assert complete['passed']
