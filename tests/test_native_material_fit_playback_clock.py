import numpy as np
import pytest

from exercise_motion_pkg.contact_interpolation import (
    ContactFootIKUnreachable, _solve_knee, native_material_playback_residuals,
)


def _native_track_fixture():
    names = ['left_ankle', 'left_foot', 'left_hip', 'left_knee']
    offsets = np.zeros((len(names), 3), dtype=float)
    offsets[names.index('left_foot')] = [0., 0., 1.]
    episodes = [{
        'startFrame': 0,
        'endFrame': 1,
        'anchorId': 'anchor-a',
        'regionRole': 'forefoot',
        'mode': 'stationary',
        'primitiveId': 'wearShoe:left_ankle->left_foot',
        'triangleIndex': 0,
        'barycentric': [1., 0., 0.],
        'materialOffsetLocalMeters': [0.2, 0.2, 0.0],
        'referenceLengthMeters': 1.0,
        'targetWorld': [0.2 * np.sqrt(2.), 0., 0.],
        'surfaceNormal': [0., 1., 0.],
        'planeOffsetMeters': 0.0,
    }]
    tracks = {
        'version': 2,
        'left': {
            'active': [True, True],
            'directions': [[0., 1., 0.], [0., 1., 0.]],
            'sideAxes': [[1., 0., 0.], [1., 0., 0.]],
            'anchorIds': ['anchor-a', 'anchor-a'],
            'episodes': episodes,
        },
    }
    return names, offsets, tracks


def test_native_material_fit_uses_playback_episode_geometry_not_candidate_bone():
    """The fit must score the material point playback will rebuild.

    A candidate foot frame can place the material point on the target while the
    stored episode frame (used by playback) leaves it 0.2166 m away. The fit
    residual must follow the stored frame and the playback key-preserving
    envelope, otherwise a toe contact can pass the fit and fail during playback.
    """
    names, offsets, tracks = _native_track_fixture()
    ankle = np.zeros(3)
    # Candidate pose articulates the foot so the candidate-bone material point
    # coincides with the target: the old fit residual would be zero.
    candidate_forward = np.array([np.sqrt(0.5), -np.sqrt(0.5), 0.])
    candidate_lateral = np.array([np.sqrt(0.5), np.sqrt(0.5), 0.])
    candidate_material = (ankle + candidate_forward * 0.2
                          + candidate_lateral * 0.2)
    target = np.asarray(tracks['left']['episodes'][0]['targetWorld'])
    assert np.linalg.norm(candidate_material - target) < 1e-9

    points = np.zeros((1, len(names), 3))
    points[0, names.index('left_ankle')] = ankle
    points[0, names.index('left_foot')] = ankle + candidate_forward

    residual, metrics = native_material_playback_residuals(
        points, names, offsets, tracks, [0.5], wrap=False, return_metrics=True)

    # Playback rebuilds the offset from the stored direction/side axis:
    # material = ankle + 0.2 * (0, 1, 0) + 0.2 * (1, 0, 0).
    playback_material = ankle + np.array([0.2, 0.2, 0.0])
    expected = playback_material - target
    assert residual.shape == (1, 3)
    assert np.allclose(residual[0], expected, atol=1e-12)
    expected_norm = float(np.linalg.norm(
        np.array([0.2 - 0.2 * np.sqrt(2.), 0.2, 0.])))
    assert abs(float(np.linalg.norm(expected)) - expected_norm) < 1e-12
    assert abs(metrics['maximumErrorMeters'] - float(np.linalg.norm(expected))) < 1e-12
    assert metrics['sampleCount'] == 1

    # The playback fade envelope keeps exact keys unconstrained and scales the
    # correction at quarter frames, so the fit sees the same clock playback does.
    key_residual, key_metrics = native_material_playback_residuals(
        points, names, offsets, tracks, [0.0], wrap=False, return_metrics=True)
    assert key_residual.shape[1] == 0
    assert key_metrics['sampleCount'] == 0
    quarter = native_material_playback_residuals(
        points, names, offsets, tracks, [0.25], wrap=False)
    assert np.allclose(quarter[0], 0.5625 * expected, atol=1e-12)

    # The ankle/foot may keep articulating: only the material anchor is
    # constrained, so changing the candidate foot pitch/roll cannot change the
    # playback-clock residual.
    articulated = points.copy()
    articulated[0, names.index('left_foot')] = ankle + np.array([0., 0., -1.])
    articulated_residual = native_material_playback_residuals(
        articulated, names, offsets, tracks, [0.5], wrap=False)
    assert np.allclose(articulated_residual, residual, atol=1e-12)

    # Independent playback keeps rejecting a genuinely unreachable two-bone
    # chain; the fix adds contact ownership, it does not weaken that gate.
    with pytest.raises(ContactFootIKUnreachable):
        _solve_knee(
            np.zeros((1, 3)), np.array([[0., 0.5, 0.]]),
            np.array([[0., 0., 0.]]), np.array([[0., 2., 0.]]),
            np.array([0.4]), np.array([0.4]), 'left')
