import copy

import numpy as np
import pytest


def _rig_candidate(motion):
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg.artifact_state import FULL_CLIP_BAKE
    from exercise_motion_pkg.rig_playback import sample_rig

    rig = {
        'jointNames': ['pelvis', 'spine3', 'left_collar', 'right_collar',
                       'left_shoulder', 'right_shoulder', 'left_elbow',
                       'right_elbow', 'left_wrist', 'right_wrist',
                       'left_hand', 'right_hand'],
        'rotationJointNames': ['pelvis', 'spine3', 'left_shoulder', 'right_shoulder',
                               'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist',
                               'left_hand', 'right_hand'],
        'parents': [-1, 0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        'order': list(range(12)),
        'offsets': [[0., 0., 0.], [0., .4, 0.], [-.08, .1, .02], [.08, .1, .02],
                    [0., .1, 0.], [0., .1, 0.], [0., .25, 0.], [0., .25, 0.],
                    [0., .24, 0.], [0., .24, 0.], [0., .08, 0.], [0., .08, 0.]],
        'interpolation': motion.INTERPOLATION,
        'coordinates': np.zeros((4, 3 + 3 * 10)).tolist(),
    }
    phase = np.arange(4) * (2. * np.pi / 4.)
    values = np.asarray(rig['coordinates'])
    values[:, :3] = np.column_stack([.01 * np.sin(phase), np.ones(4),
                                     .01 * np.cos(phase)])
    for part in range(10):
        values[:, 3 + 3 * part:6 + 3 * part] = np.column_stack([
            .03 * np.sin(phase + part * .02),
            .05 * np.cos(phase + part * .02),
            .02 * np.sin(phase),
        ])
    rig['coordinates'] = values.tolist()
    points = sample_rig(rig, np.arange(4))
    reference = {
        'sourceTimelineMapping': {
            'selectedSegmentSha256': 'a' * 64,
            'parentSourceSha256': 'b' * 64,
        },
        'sourcePose': {'frames': [{'sourceTimeSec': 0., 'joints': {'nose': [0., 0.]}}]},
        'coordinateReference': {'frames': [{'joints': {'pelvis': [0., 1., 0.]}}]},
        'camera': {'cameraRotation': np.eye(3).tolist()},
    }
    payload = {
        'kind': 'wearPreviewSkeleton', 'source': 'portable-validation-fixture',
        'fps': 30., 'frameCount': 4, 'jointNames': rig['jointNames'],
        'rootJoint': 'pelvis', 'renderFloorY': 0., 'groundContactMode': 'none',
        'elevatedSupportSurfaces': [], 'loop': {'enabled': False}, 'frames': [],
        'sourcePoseCameraReference': copy.deepcopy(reference),
        'sourceFootSupportEvidence': {'sourceVideoSha256': 'a' * 64},
        'sourceFootMarkerPrior': {'version': 1},
        'equipmentConstraints': {}, 'canonicalExecution': {},
        'fixedRig': copy.deepcopy(rig),
    }
    for index, row in enumerate(points):
        joints = dict(zip(rig['jointNames'], row.tolist()))
        payload['frames'].append({
            'timeSec': index / 30., 'sourceTimeSec': index / 30.,
            'sourceFrameIndex': index, 'inferenceFrameIndex': index,
            'sourceJoints': copy.deepcopy(joints),
            'controlledArticulationReferenceJoints': copy.deepcopy(joints),
            'joints': joints,
        })
    bake.artifact_state_for_baked_payload(
        payload, contract=None, selection_class=FULL_CLIP_BAKE)
    return payload


def test_immutable_validation_preserves_bake_identity_and_rebinds_current_receipts(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg.artifact_state import validate_artifact_state

    candidate = _rig_candidate(motion)
    frozen = copy.deepcopy(candidate)
    current_evidence = {'sourceVideoSha256': 'a' * 64, 'reviewRevision': 'current'}
    payload = copy.deepcopy(candidate)
    payload['sourceFootSupportEvidence'] = current_evidence
    validation_result = copy.deepcopy(payload)
    # The production decode/export is allowed the established floating-point
    # consistency tolerance, but its re-serialization must not replace lineage.
    validation_result['frames'][1]['joints']['pelvis'][0] += 1e-16
    validation_result['fixedRig']['coordinates'][1][0] += 1e-16
    report = {
        'applied': True,
        'validationOnly': True,
        'immutableCandidateUnchanged': True,
        'checks': dict.fromkeys(motion.REQUIRED_FIT_CHECKS, True),
        'fitSourceEvidenceDigest': motion.controlled_motion_fit_source_evidence_digest(
            validation_result),
    }

    def validated_fit(actual_payload, **kwargs):
        assert actual_payload == payload
        assert kwargs['max_evaluations'] == 0
        assert kwargs['_validation_candidate'] == candidate
        return copy.deepcopy(validation_result), copy.deepcopy(report)

    monkeypatch.setattr(motion, 'fit_controlled_motion', validated_fit)

    result, receipt = motion.validate_controlled_motion_candidate(payload, candidate)

    assert candidate == frozen
    assert result['frames'] == frozen['frames']
    assert result['loop'] == frozen['loop']
    assert result['fixedRig'] == frozen['fixedRig']
    assert result['artifactState'] == frozen['artifactState']
    assert result['sourceFootSupportEvidence'] == current_evidence
    assert receipt['outputPoseDigest'] == motion.pose_digest(result)
    assert receipt['fitSourceEvidenceDigest'] == (
        motion.controlled_motion_fit_source_evidence_digest(result))
    assert np.isclose(
        receipt['immutableCandidatePreservation']['maximumJointDeltaMeters'], 1e-16,
        rtol=0., atol=1e-17)
    validate_artifact_state(result['artifactState'], movement_payload=result)


def test_immutable_scene_placement_reuses_candidate_gauge_instead_of_recentering(monkeypatch):
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg.scene_placement import normalize_scene_placement
    from exercise_motion_pkg import rig_playback

    monkeypatch.setattr(rig_playback, 'validate_rig_playback', lambda _: {'passed': True})

    payload = _rig_candidate(motion)
    original = copy.deepcopy(payload)
    placement = {
        'version': 1,
        'orientationReason': 'retained_candidate_gauge',
        'referenceFrames': 0,
        'rotationVector': [0.01, -0.02, 0.005],
        'rotationDegrees': float(np.rad2deg(np.linalg.norm([0.01, -0.02, 0.005]))),
        'originAfterRotation': [0.012, 0.0, -0.007],
        'floorInferred': False,
    }
    points = np.asarray([
        [frame['joints'][name] for name in payload['jointNames']]
        for frame in payload['frames']
    ])
    rotation = Rotation.from_rotvec(placement['rotationVector'])
    expected = rotation.apply(points.reshape(-1, 3)).reshape(points.shape)
    expected -= np.asarray(placement['originAfterRotation'])

    placed = normalize_scene_placement(payload, placement_override=placement)

    assert payload == original
    assert placed['scenePlacement'] == placement
    actual = np.asarray([
        [frame['joints'][name] for name in placed['jointNames']]
        for frame in placed['frames']
    ])
    np.testing.assert_allclose(actual, expected, rtol=0., atol=1e-12)
    assert normalize_scene_placement(placed) is placed


def test_immutable_validation_rejects_export_outside_existing_geometry_tolerance():
    from exercise_motion_pkg import controlled_motion as motion

    candidate = _rig_candidate(motion)
    validation_result = copy.deepcopy(candidate)
    validation_result['frames'][1]['joints']['pelvis'][0] += (
        motion.RIG_NUMERICAL_CONSISTENCY_METERS * 2.)
    report = {'applied': True, 'validationOnly': True}

    try:
        motion._preserve_immutable_validation_candidate(
            candidate, candidate, validation_result, report)
    except ValueError as error:
        assert 'geometry exceeds rig consistency tolerance' in str(error)
    else:
        raise AssertionError('materially different exported geometry must be rejected')


@pytest.mark.parametrize('stretch', [False, True])
def test_immutable_basis_rebinding_preserves_source_bone_lengths(stretch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion

    source = _rig_candidate(motion)
    candidate = copy.deepcopy(source)
    fixed = source['fixedRig']
    offsets = np.asarray(fixed['offsets'], dtype=float)
    rig = SimpleNamespace(
        names=fixed['jointNames'], parents=fixed['parents'], order=fixed['order'],
        active=[fixed['jointNames'].index(name) for name in fixed['rotationJointNames']],
        initial=np.asarray(fixed['coordinates']), offsets=offsets.copy())
    joint = fixed['jointNames'].index('left_shoulder')
    length = np.linalg.norm(offsets[joint])
    candidate['fixedRig']['offsets'][joint] = [.6 * length, .8 * length, 0.]
    if stretch:
        candidate['fixedRig']['offsets'][joint][0] *= 1.1
        with pytest.raises(ValueError, match='fixed-rig basis differs'):
            motion._immutable_candidate_coordinates(source, candidate, rig)
        np.testing.assert_array_equal(rig.offsets, offsets)
    else:
        coordinates = motion._immutable_candidate_coordinates(source, candidate, rig)
        np.testing.assert_array_equal(coordinates, fixed['coordinates'])
        np.testing.assert_allclose(np.linalg.norm(rig.offsets, axis=1),
                                   np.linalg.norm(offsets, axis=1), atol=1e-12)
        np.testing.assert_array_equal(rig.offsets, candidate['fixedRig']['offsets'])
    np.testing.assert_array_equal(source['fixedRig']['offsets'], offsets)
