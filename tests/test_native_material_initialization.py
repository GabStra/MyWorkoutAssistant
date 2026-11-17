import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates
from exercise_motion_pkg.supported_contact_rig import project_supported_native_foot_coordinates


def _material_frame(ankle, foot, axis):
    forward = foot - ankle
    forward /= np.linalg.norm(forward, axis=1)[:, None]
    lateral = axis - forward * np.sum(axis * forward, axis=1, keepdims=True)
    lateral /= np.linalg.norm(lateral, axis=1)[:, None]
    up = np.cross(lateral, forward)
    return np.stack((forward, lateral, up), axis=2)


def test_material_initialization_uses_transient_knee_and_preserves_other_support():
    fixture_path = Path(__file__).parent / 'fixtures' / 'sequence_stabilization_stance.json'
    fixture = json.loads(fixture_path.read_text(encoding='utf-8'))
    names = list(fixture['joints'])
    rest = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    frame_count = 4
    rig = motion.FixedRig(np.tile(rest, (frame_count, 1, 1)), names)
    coordinates = rig.initial.copy()
    points = rig.decode(coordinates)

    ankle_i = names.index('left_ankle')
    foot_i = names.index('left_foot')
    knee_i = names.index('left_knee')
    right_knee_i = names.index('right_knee')
    right_ankle_i = names.index('right_ankle')
    right_foot_i = names.index('right_foot')
    source_axis = (rig.global_rotations(rig.material_reference_coordinates)[foot_i]
                   @ np.array([1., 0., 0.]))
    side_axes = np.broadcast_to(source_axis, (frame_count, 3)).copy()
    local_offset = np.array([.075, .012, .018])
    source_material = points[:, ankle_i] + np.einsum(
        'fij,j->fi', _material_frame(
            points[:, ankle_i], points[:, foot_i], side_axes), local_offset)
    target = source_material[0] + np.array([.003, .001, .001])
    direction = points[:, foot_i] - points[:, ankle_i]
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    native_tracks = {'version': 2, 'left': {
        'active': [True] * frame_count,
        'directions': direction.tolist(),
        'sideAxes': side_axes.tolist(),
        'anchorIds': ['left-sole-episode'] * frame_count,
        'episodes': [{
            'startFrame': 0, 'endFrame': frame_count - 1,
            'anchorId': 'left-sole-episode', 'regionRole': 'full_sole',
            'mode': 'stationary', 'primitiveId': 'wearShoe:left_ankle->left_foot',
            'triangleIndex': 0, 'barycentric': [.25, .5, .25],
            'materialOffsetLocalMeters': local_offset.tolist(),
            'referenceLengthMeters': float(np.linalg.norm(rig.offsets[foot_i])),
            'targetWorld': target.tolist(),
            'surfaceNormal': [0., 1., 0.], 'planeOffsetMeters': float(target[1]),
        }],
    }}
    # Only the opposite knee has explicit stationary support. The left material
    # episode must not acquire a synthetic knee or ankle observation.
    support_tracks = {'version': 1, 'source': 'validated_stationary_body_support',
                      'joints': {'right_knee': {
                          'episodeIds': ['right-knee-anchor'] * frame_count,
                      }}}

    legacy_result = project_supported_native_foot_coordinates(
        rig, coordinates, native_tracks, support_tracks)
    np.testing.assert_array_equal(legacy_result, coordinates)

    projected_coordinates = project_supported_native_foot_coordinates(
        rig, coordinates, native_tracks, support_tracks, current_knee_pivot=True)
    projected = rig.decode(projected_coordinates)
    np.testing.assert_array_equal(coordinates, rig.initial)
    for joint_i in (knee_i, right_knee_i, right_ankle_i, right_foot_i):
        np.testing.assert_allclose(projected[:, joint_i], points[:, joint_i], atol=1e-10)

    axes = _native_side_axes_for_coordinates(
        rig, projected_coordinates, {'_nativeFootMaterialTracks': native_tracks})['left']
    material = projected[:, ankle_i] + np.einsum(
        'fij,j->fi', _material_frame(
            projected[:, ankle_i], projected[:, foot_i], axes), local_offset)
    np.testing.assert_allclose(material, np.broadcast_to(target, material.shape), atol=1e-6)

    parents = np.asarray(rig.parents, dtype=int)
    child_ids = np.flatnonzero(parents >= 0)
    parent_ids = parents[child_ids]
    original_lengths = np.linalg.norm(points[:, child_ids] - points[:, parent_ids], axis=-1)
    projected_lengths = np.linalg.norm(
        projected[:, child_ids] - projected[:, parent_ids], axis=-1)
    np.testing.assert_allclose(projected_lengths, original_lengths, atol=1e-9)
