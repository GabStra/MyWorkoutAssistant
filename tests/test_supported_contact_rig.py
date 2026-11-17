import json
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates
from exercise_motion_pkg.supported_contact_rig import (
    project_supported_native_foot_coordinates,
)

FIXTURES = Path(__file__).parent / 'fixtures'
OFFSET_LOCAL = np.array([0., 0.5, 0.])


def _rig(frame_count):
    fixture = json.loads(
        (FIXTURES / 'sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    pose = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    return motion.FixedRig(np.tile(pose, (frame_count, 1, 1)), names), names


def _material_frame(ankle, foot, axis):
    bone = foot - ankle
    forward = bone / np.linalg.norm(bone, axis=1)[:, None]
    lateral = axis - forward * np.sum(axis * forward, axis=1, keepdims=True)
    lateral /= np.linalg.norm(lateral, axis=1)[:, None]
    up = np.cross(lateral, forward)
    return np.stack((forward, lateral, up), axis=2)


def _material_point(points, names, axis, local):
    ankle = points[:, names.index('right_ankle')]
    foot = points[:, names.index('right_foot')]
    return ankle + np.einsum('fij,j->fi', _material_frame(ankle, foot, axis), local)


def _scenario(frame_count):
    rig, names = _rig(frame_count)
    coordinates = rig.initial.copy()
    points = rig.decode(coordinates)
    foot = names.index('right_foot')
    ankle = names.index('right_ankle')
    source_axis = (rig.global_rotations(rig.material_reference_coordinates)[foot]
                   @ np.array([1., 0., 0.]))
    side_axes = np.broadcast_to(source_axis, (frame_count, 3)).copy()
    bone_length = float(np.linalg.norm(rig.offsets[foot]))
    material = _material_point(points, names, side_axes, OFFSET_LOCAL)
    target = material + np.array([0.0065, 0.002, 0.0])
    episode = {
        'startFrame': 0, 'endFrame': frame_count - 1,
        'anchorId': 'support-anchor', 'mode': 'stationary',
        'materialOffsetLocalMeters': OFFSET_LOCAL.tolist(),
        'referenceLengthMeters': bone_length,
        'targetWorld': target[0].tolist(),
        'surfaceNormal': [0., 1., 0.],
        'planeOffsetMeters': float(target[0, 1]),
    }
    direction = points[:, foot] - points[:, ankle]
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    track = {'version': 2, 'right': {
        'active': [True] * frame_count,
        'directions': direction.tolist(),
        'sideAxes': side_axes.tolist(),
        'anchorIds': ['support-anchor'] * frame_count,
        'episodes': [episode],
    }}
    support = {'version': 1, 'source': 'validated_stationary_body_support', 'joints': {
        'right_knee': {'episodeIds': ['support-anchor'] * frame_count},
    }}
    return rig, names, coordinates, points, track, support, target


def test_encoder_corrects_material_target_with_fixed_knee_and_bones():
    rig, names, coordinates, points, track, support, target = _scenario(4)
    original = coordinates.copy()
    q = project_supported_native_foot_coordinates(rig, coordinates, track, support)

    assert q is not coordinates
    assert not np.shares_memory(q, coordinates)
    np.testing.assert_array_equal(coordinates, original)

    corrected = rig.decode(q)
    knee = names.index('right_knee')
    ankle = names.index('right_ankle')
    foot = names.index('right_foot')
    hip = names.index('right_hip')
    np.testing.assert_allclose(corrected[:, knee], points[:, knee], atol=1e-10)
    np.testing.assert_allclose(corrected[:, hip], points[:, hip], atol=1e-10)
    for name in ('left_knee', 'left_ankle', 'left_foot'):
        joint = names.index(name)
        np.testing.assert_allclose(corrected[:, joint], points[:, joint], atol=1e-10)

    np.testing.assert_allclose(
        np.linalg.norm(corrected[:, ankle] - corrected[:, knee], axis=1),
        np.linalg.norm(points[:, ankle] - points[:, knee], axis=1), atol=1e-9)
    np.testing.assert_allclose(
        np.linalg.norm(corrected[:, foot] - corrected[:, ankle], axis=1),
        np.linalg.norm(points[:, foot] - points[:, ankle], axis=1), atol=1e-9)
    assert np.max(np.linalg.norm(corrected[:, ankle] - points[:, ankle], axis=1)) > 1e-4

    axes = _native_side_axes_for_coordinates(
        rig, q, {'_nativeFootMaterialTracks': track})['right']
    material = _material_point(corrected, names, axes, OFFSET_LOCAL)
    np.testing.assert_allclose(material, target, atol=1e-6)


def test_encoder_noop_copy_without_native_track_or_protection():
    rig, names, coordinates, _, track, _, _ = _scenario(3)

    legacy = project_supported_native_foot_coordinates(rig, coordinates, None, {})
    np.testing.assert_array_equal(legacy, coordinates)
    assert legacy is not coordinates

    unprotected = {'version': 1, 'source': 'validated_stationary_body_support', 'joints': {
        'right_knee': {'episodeIds': [None] * 3},
    }}
    np.testing.assert_array_equal(
        project_supported_native_foot_coordinates(rig, coordinates, track, unprotected),
        coordinates)


def test_encoder_unreachable_target_raises_without_mutating_input():
    rig, _, coordinates, _, track, support, target = _scenario(3)
    bad_track = json.loads(json.dumps(track))
    bad_track['right']['episodes'][0]['targetWorld'] = (
        np.asarray(target[0]) + np.array([5., 0., 0.])).tolist()
    original = coordinates.copy()
    with pytest.raises(ValueError):
        project_supported_native_foot_coordinates(rig, coordinates, bad_track, support)
    np.testing.assert_array_equal(coordinates, original)
