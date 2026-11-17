"""Immutable validation must measure the submitted candidate, not its seed.

The original regression: a source payload whose support initialization would
fail returned that guard result before the existing immutable candidate binder
ran. Both an unmodified candidate and a seam-nudged candidate then reported the
same source-seed support error, so candidate geometry was never measured.

This test keeps a support-owned seed that would require generation-only
initialization, forbids every such initializer/optimizer, and verifies that the
public immutable API reaches and reports the exact submitted candidate.
"""
import copy
import json
from pathlib import Path

import numpy as np


FIXTURE = Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json'


def _fixture():
    from exercise_motion_pkg import controlled_motion as motion

    fixture = json.loads(FIXTURE.read_text())
    names = list(fixture['joints'])
    stance = np.tile(
        np.asarray([fixture['joints'][name] for name in names], dtype=float),
        (10, 1, 1))
    stance_rig = motion.FixedRig(stance, names)
    candidate_coordinates = stance_rig.initial.copy()

    # The source seed keeps the same bone lengths but has feet and knees that a
    # support initializer would have to repair before generation could proceed.
    seed_coordinates = candidate_coordinates.copy()
    for joint, angle in (('left_ankle', 1.4), ('right_ankle', -1.4),
                         ('left_knee', .5), ('right_knee', -.3)):
        slot = stance_rig.slots[names.index(joint)]
        seed_coordinates[:, slot:slot + 3] += np.asarray([angle, 0., 0.])
    seed_points = stance_rig.decode(seed_coordinates)

    payload = {
        'fps': 30.,
        'jointNames': names,
        'frames': [
            {'timeSec': index / 30., 'sourceTimeSec': index / 30.,
             'sourceFrameIndex': index, 'inferenceFrameIndex': index,
             'joints': dict(zip(names, point.tolist()))}
            for index, point in enumerate(seed_points)
        ],
        'sourceFootSupportEvidence': {
            'bodySupport': {
                'required': True,
                'status': 'confirmed',
                'stationaryJoints': [
                    'pelvis', 'left_ankle', 'left_foot',
                    'right_ankle', 'right_foot'],
                'coplanarGroups': [
                    {'joints': ['left_ankle', 'left_foot'],
                     'normal': [0., 1., 0.], 'planeOffsetMeters': 0.},
                    {'joints': ['right_ankle', 'right_foot'],
                     'normal': [0., 1., 0.], 'planeOffsetMeters': 0.},
                ],
            },
        },
        'sourcePoseCameraReference': {
            'sourceTimelineMapping': {
                'selectedSegmentSha256': 'a' * 64,
                'parentSourceSha256': 'b' * 64,
            },
            'sourcePose': {
                'frames': [{'sourceTimeSec': 0.,
                            'joints': {'nose': [0., 0.]}}]},
            'coordinateReference': {
                'frames': [{'joints': {'pelvis': [0., 1., 0.]}}]},
            'camera': {'cameraRotation': np.eye(3).tolist()},
        },
    }
    candidate_rig = motion.FixedRig(seed_points, names)
    fixed_rig = {
        'version': 1,
        'jointNames': names,
        'parents': candidate_rig.parents,
        'order': candidate_rig.order,
        'offsets': candidate_rig.offsets.tolist(),
        'interpolation': motion.INTERPOLATION,
        'rotationJointNames': [names[index] for index in candidate_rig.active],
        'coordinates': candidate_coordinates.tolist(),
    }
    placement = {
        'version': 1,
        'orientationReason': 'retained_candidate_gauge',
        'referenceFrames': 0,
        'rotationVector': [0., 0., 0.],
        'rotationDegrees': 0.,
        'originAfterRotation': [0., 0., 0.],
        'floorInferred': False,
    }

    def candidate(root_x_profile):
        result = copy.deepcopy(payload)
        result['fixedRig'] = copy.deepcopy(fixed_rig)
        result['loop'] = {'enabled': False}
        result['scenePlacement'] = copy.deepcopy(placement)
        coordinates = candidate_coordinates.copy()
        coordinates[:, 0] += root_x_profile
        points = candidate_rig.decode(coordinates)
        for frame, point in zip(result['frames'], points):
            frame['joints'] = dict(zip(names, point.tolist()))
        result['fixedRig']['coordinates'] = coordinates.tolist()
        return result

    return motion, payload, candidate


def test_immutable_validation_measures_candidate_not_support_seed(monkeypatch):
    from exercise_motion_pkg import (
        anatomical_repair, joint_plant_initialization, support_geometry)
    from exercise_motion_pkg.sequence_stabilization import pose_digest

    motion, payload, candidate = _fixture()
    valid = candidate(np.zeros(10))
    root_spike = np.zeros(10)
    root_spike[5] = .2
    altered = candidate(root_spike)

    def forbidden_generation_stage(*_args, **_kwargs):
        raise AssertionError(
            'generation-only initialization/optimization ran during '
            'immutable candidate validation')

    monkeypatch.setattr(
        support_geometry, 'calibrate_support_pose', forbidden_generation_stage)
    monkeypatch.setattr(
        anatomical_repair, 'repair_rig_anatomy', forbidden_generation_stage)
    monkeypatch.setattr(
        joint_plant_initialization, 'initialize_joint_plant_coordinates',
        forbidden_generation_stage)
    monkeypatch.setattr(
        motion, 'solve_trajectory', forbidden_generation_stage)

    valid_result, valid_report = motion.validate_controlled_motion_candidate(
        payload, valid, timeout_seconds=30)
    altered_result, altered_report = motion.validate_controlled_motion_candidate(
        payload, altered, timeout_seconds=30)

    for result, report, submitted in (
            (valid_result, valid_report, valid),
            (altered_result, altered_report, altered)):
        assert report['validationOnly'] is True
        assert report['evaluations'] == 0
        assert report['immutableCandidateUnchanged'] is True
        assert report['supportInitializationAdmission'] == (
            'submitted_immutable_candidate')
        assert report['supportInitializationStrategy'] == (
            'immutable_candidate_no_seed_repair')
        assert report['outputPoseDigest'] == pose_digest(result)
        assert pose_digest(result) == pose_digest(submitted)
        assert result['frames'] == submitted['frames']
        assert result['fixedRig'] == submitted['fixedRig']

    # The source seed fails final source-articulation gates, but both submitted
    # candidates are still measured. The altered root excursion must surface as
    # its own candidate metric instead of the identical source-seed error.
    assert valid_report['reason'] == 'fit_validation_failed'
    assert altered_report['reason'] == 'fit_validation_failed'
    assert valid_report['checks']['rootContinuity'] is True
    assert altered_report['checks']['rootContinuity'] is False
    assert valid_report['rootMotionQuality'][
        'maximumSecondDifferenceMetersAt30Hz'] == 0.
    assert altered_report['rootMotionQuality'][
        'maximumSecondDifferenceMetersAt30Hz'] > (
            valid_report['rootMotionQuality']['limitMetersAt30Hz'])
    assert altered_result['frames'][5]['joints']['pelvis'][0] == (
        altered['frames'][5]['joints']['pelvis'][0])
