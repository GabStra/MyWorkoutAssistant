import json
from pathlib import Path
import numpy as np
import pytest
from exercise_motion_pkg.controlled_motion import canonical_bilateral_reference
from exercise_motion_pkg.youtube import normalize_bilateral_execution

def torso_fixture():
    fixture = json.loads(Path('tests/fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile(np.array([fixture['joints'][n] for n in names]), (7, 1, 1))
    points[:, names.index('spine2'), 0] += np.linspace(.01, .03, 7)
    points[:, names.index('spine2'), 2] += np.linspace(.02, .06, 7)
    return names, points

def test_sagittal_torso_preserves_source_arch_and_limb_vectors():
    names, points = torso_fixture()
    original = points.copy()
    result = canonical_bilateral_reference(points, names, {'torso': 'sagittal'})
    np.testing.assert_array_equal(points, original)
    index = names.index
    hips = (points[:, index('left_hip')] + points[:, index('right_hip')]) * .5
    shoulders = (points[:, index('left_shoulder')] + points[:, index('right_shoulder')]) * .5
    longitudinal = shoulders - hips
    longitudinal /= np.linalg.norm(longitudinal, axis=-1, keepdims=True)
    lateral = points[:, index('right_hip')] - points[:, index('left_hip')]
    lateral -= np.sum(lateral * longitudinal, axis=-1, keepdims=True) * longitudinal
    lateral /= np.linalg.norm(lateral, axis=-1, keepdims=True)
    normal = np.cross(lateral, longitudinal)
    corrected_hips = (result[:, index('left_hip')] + result[:, index('right_hip')]) * .5
    corrected_shoulders = (result[:, index('left_shoulder')] + result[:, index('right_shoulder')]) * .5
    corrected_longitudinal = corrected_shoulders - corrected_hips
    corrected_longitudinal /= np.linalg.norm(corrected_longitudinal, axis=-1, keepdims=True)
    corrected_lateral = result[:, index('right_hip')] - result[:, index('left_hip')]
    corrected_lateral -= np.sum(corrected_lateral * corrected_longitudinal, axis=-1, keepdims=True) * corrected_longitudinal
    corrected_lateral /= np.linalg.norm(corrected_lateral, axis=-1, keepdims=True)
    corrected_normal = np.cross(corrected_lateral, corrected_longitudinal)
    for name in ('pelvis', 'spine1', 'spine2', 'spine3', 'neck'):
        before = points[:, index(name)] - hips
        after = result[:, index(name)] - corrected_hips
        np.testing.assert_allclose(np.sum(after * corrected_normal, axis=-1),
                                   np.sum(before * normal, axis=-1), atol=1e-12)
        np.testing.assert_allclose(np.sum(after * corrected_longitudinal, axis=-1),
                                   np.sum(before * longitudinal, axis=-1), atol=1e-12)
        np.testing.assert_allclose(np.sum(after * corrected_lateral, axis=-1), 0., atol=1e-12)
    for side in ('left', 'right'):
        for parent, child in zip(('shoulder', 'elbow', 'wrist'), ('elbow', 'wrist', 'hand')):
            a, b = index(side + '_' + parent), index(side + '_' + child)
            before, after = points[:, b] - points[:, a], result[:, b] - result[:, a]
            for old_axis, new_axis in ((normal, corrected_normal), (lateral, corrected_lateral),
                                       (longitudinal, corrected_longitudinal)):
                np.testing.assert_allclose(np.sum(after * new_axis, axis=-1),
                                           np.sum(before * old_axis, axis=-1), atol=1e-12)
        for part in ('knee', 'ankle', 'foot'):
            joint = index(side + '_' + part)
            np.testing.assert_array_equal(result[:, joint], points[:, joint])
    np.testing.assert_allclose(np.linalg.norm(result[:, index('head')] - result[:, index('neck')], axis=-1),
                               np.linalg.norm(points[:, index('head')] - points[:, index('neck')], axis=-1), atol=1e-12)
    np.testing.assert_allclose(canonical_bilateral_reference(result, names, {'torso': 'sagittal'}), result, atol=1e-12)
    np.testing.assert_array_equal(canonical_bilateral_reference(points, names, {'torso': 'unconstrained'}), points)

@pytest.mark.parametrize('degeneracy', ['coincident_centers', 'parallel_hip_axis', 'nonfinite'])
def test_sagittal_torso_rejects_degenerate_frame(degeneracy):
    names, points = torso_fixture()
    index = names.index
    if degeneracy == 'coincident_centers':
        points[:, index('left_shoulder')] = points[:, index('left_hip')]
        points[:, index('right_shoulder')] = points[:, index('right_hip')]
    elif degeneracy == 'parallel_hip_axis':
        points[:, index('right_hip')] = points[:, index('left_hip')] + [0., .1, 0.]
        midpoint = (points[:, index('left_hip')] + points[:, index('right_hip')]) * .5
        points[:, index('left_shoulder')] = midpoint + [0., .5, 0.]
        points[:, index('right_shoulder')] = midpoint + [0., .7, 0.]
    else:
        points[:, index('right_hip')] = np.nan
    with pytest.raises(ValueError):
        canonical_bilateral_reference(points, names, {'torso': 'sagittal'})


def test_sagittal_torso_levels_rolled_hinge_without_moving_distal_legs():
    from scipy.spatial.transform import Rotation
    names, points = torso_fixture()
    points = Rotation.from_euler('xz', [35., 8.], degrees=True).apply(
        points.reshape(-1, 3)).reshape(points.shape)
    before = points.copy()
    result = canonical_bilateral_reference(points, names, {'torso': 'sagittal'})
    index = names.index
    hips = (points[:, index('left_hip')] + points[:, index('right_hip')]) * .5
    shoulders = (points[:, index('left_shoulder')] + points[:, index('right_shoulder')]) * .5
    np.testing.assert_allclose(result[:, index('left_hip'), 1],
                               result[:, index('right_hip'), 1], atol=1e-12)
    corrected_hips = (result[:, index('left_hip')] + result[:, index('right_hip')]) * .5
    corrected_shoulders = (result[:, index('left_shoulder')] + result[:, index('right_shoulder')]) * .5
    corrected_lateral = result[:, index('right_hip')] - result[:, index('left_hip')]
    corrected_lateral /= np.linalg.norm(corrected_lateral, axis=-1, keepdims=True)
    np.testing.assert_allclose(corrected_hips, hips, atol=1e-12)
    np.testing.assert_allclose(np.linalg.norm(corrected_shoulders - corrected_hips, axis=-1),
                               np.linalg.norm(shoulders - hips, axis=-1), atol=1e-12)
    np.testing.assert_allclose(np.sum((corrected_shoulders - corrected_hips) * corrected_lateral,
                                   axis=-1), 0., atol=1e-12)
    for side in ('left', 'right'):
        for part in ('knee', 'ankle', 'foot'):
            joint = index(side + '_' + part)
            np.testing.assert_array_equal(result[:, joint], points[:, joint])
    np.testing.assert_array_equal(points, before)


def test_sagittal_torso_handles_vertical_frame_without_forcing_a_pose():
    names, points = torso_fixture()
    index = names.index
    hips = (points[:, index('left_hip')] + points[:, index('right_hip')]) * .5
    for side, sign in (('left', -1), ('right', 1)):
        points[:, index(side + '_shoulder')] = hips + [sign * .2, .5, 0.]
    result = canonical_bilateral_reference(points, names, {'torso': 'sagittal'})
    assert np.isfinite(result).all()
    np.testing.assert_allclose((result[:, index('left_shoulder')]
                               + result[:, index('right_shoulder')]) * .5,
                               hips + [0., .5, 0.], atol=1e-12)

@pytest.mark.parametrize('value', [
    {}, {'arms': 'mirrored', 'legs': 'unconstrained'}, {'torso': 'sagittal'}, {'torso': 'unconstrained'},
])
def test_bilateral_execution_retains_explicit_supported_modes(value):
    assert normalize_bilateral_execution(value) == value

@pytest.mark.parametrize('value', [{'torso': 'mirrored'}, {'torso': 'support_aligned'}, {'arms': 'sagittal'}, {'other': 'unconstrained'}])
def test_bilateral_execution_rejects_unsupported_modes(value):
    with pytest.raises(ValueError):
        normalize_bilateral_execution(value)


def test_source_identity_ignores_technique_target_but_preserves_action_and_receipts():
    from copy import deepcopy
    from exercise_motion_pkg.youtube import (
        exercise_motion_contract_prompt_identity_matches,
        exercise_motion_contract_prompt_sha256,
    )
    original = {'exerciseName': 'Movement', 'advisoryText': 'Lower and return.',
                'bilateralExecution': {'arms': 'mirrored'},
                'motionContext': {'exerciseDefinition': {
                    'definingAction': 'Lower and return.',
                    'bilateralExecution': {'arms': 'mirrored'}}}}
    updated = deepcopy(original)
    updated['bilateralExecution']['torso'] = 'sagittal'
    updated['motionContext']['exerciseDefinition']['bilateralExecution']['torso'] = 'sagittal'
    assert exercise_motion_contract_prompt_sha256(original) != exercise_motion_contract_prompt_sha256(updated)
    assert exercise_motion_contract_prompt_identity_matches(original, updated)
    updated['motionContext']['exerciseDefinition']['definingAction'] = 'Jump and land.'
    assert not exercise_motion_contract_prompt_identity_matches(original, updated)


def test_sagittal_torso_preserves_body_relative_hinge_and_camera_heading():
    from scipy.spatial.transform import Rotation

    names, source = torso_fixture()
    clean = canonical_bilateral_reference(source, names, {'torso': 'sagittal'})
    left, right = names.index('left_hip'), names.index('right_hip')
    axis = clean[0, right] - clean[0, left]
    axis /= np.linalg.norm(axis)
    pivot = (clean[0, right] + clean[0, left]) * .5
    hinge = Rotation.from_rotvec(axis * np.deg2rad(25.))
    hinged = hinge.apply((clean - pivot).reshape(-1, 3)).reshape(clean.shape) + pivot
    np.testing.assert_allclose(canonical_bilateral_reference(
        hinged, names, {'torso': 'sagittal'}), hinged, atol=1e-12)
    yaw = Rotation.from_euler('y', 73., degrees=True)
    rotated = yaw.apply(source.reshape(-1, 3)).reshape(source.shape)
    corrected = canonical_bilateral_reference(rotated, names, {'torso': 'sagittal'})
    expected = yaw.apply(clean.reshape(-1, 3)).reshape(clean.shape)
    np.testing.assert_allclose(corrected, expected, atol=1e-12)
