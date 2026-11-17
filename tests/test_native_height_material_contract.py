"""Native height-only contacts own a calibrated shoe material plane."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg.contact_interpolation import (
    native_height_material_plane_residuals,
    native_material_playback_residuals,
    suppress_native_foot_pins,
)
from exercise_motion_pkg.foot_geometry import shoe_vertices
from exercise_motion_pkg.material_region_support import shoe_triangles


def _height_track(anchor_ids=(None, None), *, mode='verticalOnly',
                  normal=(0., 1., 0.), plane=0., target_world=None,
                  starts=(0,), ends=(1,)):
    episodes = []
    for index, (start, end) in enumerate(zip(starts, ends)):
        stored = anchor_ids[min(start, len(anchor_ids) - 1)]
        anchor = (str(stored) if stored is not None
                  else f'native-material:left:{index}:{start}:{end}')
        episode = {
            'startFrame': start,
            'endFrame': end,
            'anchorId': anchor,
            'regionRole': 'forefoot',
            'mode': mode,
            'primitiveId': 'wearShoe:left_ankle->left_foot',
            'triangleIndex': 0,
            'barycentric': [1., 0., 0.],
            'materialOffsetLocalMeters': [0., 0., 0.],
            'referenceLengthMeters': .1,
            'surfaceNormal': list(normal),
            'planeOffsetMeters': float(plane),
        }
        if mode == 'stationary':
            episode['targetWorld'] = list(
                target_world if target_world is not None else [0., 0., 0.])
        episodes.append(episode)
    return {
        'version': 2,
        'left': {
            'active': [True] * 2,
            'directions': [[0., 0., 1.], [0., 0., 1.]],
            'sideAxes': [[1., 0., 0.], [1., 0., 0.]],
            'anchorIds': list(anchor_ids),
            'episodes': episodes,
        },
    }


def _points(ankle_y=.01):
    return np.asarray([[
        [0., ankle_y, 0.],
        [0., ankle_y, .1],
    ], [
        [0., ankle_y, 0.],
        [0., ankle_y, .1],
    ]], dtype=float)


def test_floating_height_only_contact_is_measured_without_anchor_ids():
    names = ['left_ankle', 'left_foot']
    offsets = np.asarray([[0., 0., 0.], [0., 0., .1]])
    tracks = _height_track(anchor_ids=(None, None))

    residual, metrics = native_material_playback_residuals(
        _points(), names, offsets, tracks, [.5], return_metrics=True)

    assert metrics['available'] is True
    assert metrics['sampleCount'] == 1
    np.testing.assert_allclose(residual[0], [0., .01, 0.], atol=1e-12)

    # Playback preserves the stored key pose, so the key itself must be
    # measured instead of being excluded as an "exact key".
    key_residual, key_metrics = native_material_playback_residuals(
        _points(), names, offsets, tracks, [0.], return_metrics=True)
    assert key_metrics['sampleCount'] == 1
    np.testing.assert_allclose(key_residual[0], [0., .01, 0.], atol=1e-12)


def test_height_only_material_residual_is_tangent_free_and_not_a_joint_target():
    names = ['left_ankle', 'left_foot']
    offsets = np.asarray([[0., 0., 0.], [0., 0., .1]])
    tracks = _height_track(anchor_ids=(None, None))
    floating = native_material_playback_residuals(
        _points(), names, offsets, tracks, [.5])

    tangent = _points()
    tangent[:, :, 0] += .30
    tangent[:, :, 2] -= .20
    tangentially_moved = native_material_playback_residuals(
        tangent, names, offsets, tracks, [.5])
    np.testing.assert_allclose(tangentially_moved, floating, atol=1e-12)

    # The fit composes its height-only mask through the same suppression
    # playback uses: a native-owned foot row never becomes a joint-to-floor
    # target.
    height_mask = np.zeros((2, len(names)), dtype=bool)
    height_mask[:, names.index('left_foot')] = True
    suppressed = suppress_native_foot_pins(height_mask, names, tracks)
    assert not suppressed.any()


def test_height_only_actual_shoe_material_plane_is_checked():
    fixture = json.loads((Path(__file__).parent / 'fixtures'
                          / 'native_foot_geometry_v1.json').read_text())
    geometry = fixture['reference']
    names = ['left_ankle', 'left_foot']
    triangle = shoe_triangles()[11]
    barycentric = np.asarray([.2, .3, .5])
    ankle = np.asarray([0., 0., 0.])
    foot = np.asarray([.134302, 0., 0.])
    side_axis = np.asarray([0., 0., 1.])
    mesh = shoe_vertices(
        ankle, foot, side_axis, None, 1., native_geometry=geometry['sides']['left'])
    material = barycentric @ mesh[triangle]
    plane = float(material[1])
    points = np.repeat(np.asarray([[ankle, foot]]), 2, axis=0)
    tracks = _height_track(anchor_ids=(None, None), plane=plane)
    tracks['left']['episodes'][0].update(
        triangleIndex=11, barycentric=[.2, .3, .5])
    side_axes = {'left': np.tile(side_axis, (2, 1))}

    on_plane, on_plane_metrics = native_height_material_plane_residuals(
        points, names, tracks, [0., 1.], side_axes=side_axes,
        native_geometry=geometry, foot_scale=1., return_metrics=True)
    assert on_plane_metrics['sampleCount'] == 2
    assert float(np.max(np.abs(on_plane), initial=0.)) <= 1e-12

    floating = points.copy()
    floating[:, :, 1] += .01
    residual, metrics = native_height_material_plane_residuals(
        floating, names, tracks, [0., 1.], side_axes=side_axes,
        native_geometry=geometry, foot_scale=1., return_metrics=True)
    assert metrics['sampleCount'] == 2
    np.testing.assert_allclose(residual[0], [0., .01, 0.], atol=1e-9)

    tangent = floating.copy()
    tangent[:, :, 0] += .5
    tangent[:, :, 2] -= .25
    tangent_residual = native_height_material_plane_residuals(
        tangent, names, tracks, [0., 1.], side_axes=side_axes,
        native_geometry=geometry, foot_scale=1.)
    np.testing.assert_allclose(tangent_residual, residual, atol=1e-9)

    # An exact contact key remains owned when the next key starts a new episode.
    adjacent = _height_track(starts=(0, 1), ends=(0, 1), plane=plane)
    for episode in adjacent['left']['episodes']:
        episode.update(triangleIndex=11, barycentric=[.2, .3, .5])
    _, boundary_keys = native_height_material_plane_residuals(
        floating, names, adjacent, [0., 1.], side_axes=side_axes,
        native_geometry=geometry, foot_scale=1., return_metrics=True)
    assert boundary_keys['sampleCount'] == 2


def test_height_only_dense_playback_uses_track_frame_count_not_sample_count():
    fixture = json.loads((Path(__file__).parent / 'fixtures'
                          / 'native_foot_geometry_v1.json').read_text())
    geometry = fixture['reference']
    names = ['left_ankle', 'left_foot']
    angle = .134302
    points = np.asarray([
        [[0., 0., 0.], [angle, 0., 0.]],
        [[0., .001, 0.], [angle, .001, 0.]],
        [[0., .002, 0.], [angle, .002, 0.]],
    ])
    tracks = _height_track(anchor_ids=(None, None))
    side_axes = {'left': np.tile([0., 0., 1.], (len(points), 1))}

    residual, metrics = native_height_material_plane_residuals(
        points, names, tracks, [0., .5, 1.], side_axes=side_axes,
        native_geometry=geometry, foot_scale=1., return_metrics=True)

    # Three dense queries over a two-frame track must still measure; the track
    # is validated against its own frame count, not the playback sample count.
    assert metrics['sampleCount'] == len(points)
    assert residual.shape == (len(points), 3)


def test_height_only_episode_boundary_and_stationary_ownership_are_preserved():
    names = ['left_ankle', 'left_foot']
    offsets = np.asarray([[0., 0., 0.], [0., 0., .1]])
    adjacent = _height_track(
        anchor_ids=(None, None), starts=(0, 1), ends=(0, 1))
    boundary = native_material_playback_residuals(
        _points(), names, offsets, adjacent, [.5])
    assert boundary.shape[1] == 0
    _, boundary_keys = native_material_playback_residuals(
        _points(), names, offsets, adjacent, [0., 1.], return_metrics=True)
    assert boundary_keys['sampleCount'] == 2

    stationary = _height_track(
        anchor_ids=('anchor-a', 'anchor-a'), mode='stationary',
        target_world=[0., 0., 0.])
    # Stationary playback still owns exact keys through its XYZ anchor; the
    # height-only key measurement must not redefine that contract.
    _, stationary_key_metrics = native_material_playback_residuals(
        _points(), names, offsets, stationary, [0.], return_metrics=True)
    assert stationary_key_metrics['sampleCount'] == 0
    stationary_mid = native_material_playback_residuals(
        _points(), names, offsets, stationary, [.5])
    assert stationary_mid.shape == (1, 3)
    np.testing.assert_allclose(stationary_mid[0], [0., .01, 0.], atol=1e-12)


def test_opposite_plane_normals_require_opposite_offsets():
    from exercise_motion_pkg.contact_interpolation import _native_vertical_planes_match

    upward = {'surfaceNormal': [0., 1., 0.], 'planeOffsetMeters': 2.}
    downward_same_plane = {'surfaceNormal': [0., -1., 0.], 'planeOffsetMeters': -2.}
    downward_other_plane = {'surfaceNormal': [0., -1., 0.], 'planeOffsetMeters': 2.}
    assert _native_vertical_planes_match(upward, downward_same_plane)
    assert not _native_vertical_planes_match(upward, downward_other_plane)
