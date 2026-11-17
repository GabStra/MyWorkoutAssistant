"""Fractional stationary native-material authority follows the candidate frame.

v702 causal evidence (preserved): the exact-key stationary material measurement
(calibrated actual shoe plus transported side axes) is invariant under a legal
rigid pivot of the shoe about its real material anchor, while the dense
fractional playback branch reconstructed the material point from the candidate
ankle plus the *stored* track direction and side axis.  With unrefreshed source
frames that branch pinned the inferred original ankle placement by exactly
``2 * |anchor - ankle| * sin(theta / 2)`` (15.200318772044401 mm at 25 degrees for
the fixture below, 27.36726608234028 mm at 45.87 degrees), orders of magnitude
over the 3 mm dense playback limit, even though the exact-key authority allowed
the same pivot.

v703 invariant: supplying the FK-transported candidate side axes makes the
fractional branch measure the pose frame, exactly as
``supported_contact_rig._material_points`` and the serialized-output playback
sampler do.  A legal pivot is then accepted at both clocks, while an
ankle-fixed foot twist that displaces the actual material anchor still fails.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.contact_interpolation import (
    native_material_key_sample_requirements,
    native_material_playback_residuals,
)
from exercise_motion_pkg.controlled_motion import native_material_contact_verdict
from exercise_motion_pkg.native_foot_geometry import native_foot_bone_frame
from exercise_motion_pkg.rig_interpolation import INTERPOLATION

from test_native_material_authority import _geometry, _mesh_material, _stationary_track

_PIVOT_DEGREES = 25.
_SIDES = ('left', 'right')
_JOINT_INDEX = {
    'left': (0, 1),
    'right': (2, 3),
}


def _producer_bound_stationary_fixture(*, sides=_SIDES):
    """Fixture track carrying the producer's compact material offset.

    ``_stationary_track`` caches ``materialOffsetLocalMeters=[0,0,0]``, which
    never exercises the fractional production binding.  Rebuild the exact
    offset ``_bind_native_material_episode`` would store (material delta in the
    native bone frame over the episode reference ratio) and verify the stored
    fractional reconstruction reproduces the anchor for the source pose, the
    same rebuilt==point contract the producer enforces before publishing.
    """
    geometry = _geometry()
    material = _mesh_material(geometry, 11, (.2, .3, .5))
    names, offsets, points, tracks, key_axes = _stationary_track(
        target_world=material, sides=sides)
    reference = float(tracks[sides[0]]['episodes'][0]['referenceLengthMeters'])
    forward, lateral, up, length = native_foot_bone_frame(
        points[0, 0][None], points[0, 1][None], np.asarray([0., 0., 1.])[None])
    delta = material - points[0, 0]
    local = np.array([np.dot(delta, forward[0]), np.dot(delta, lateral[0]),
                      np.dot(delta, up[0])]) / (
        float(np.asarray(length).reshape(-1)[0]) / reference)
    for side in sides:
        tracks[side]['episodes'][0]['materialOffsetLocalMeters'] = local.tolist()
    baseline = native_material_playback_residuals(
        points, names, offsets, tracks, [0.5], interpolation=INTERPOLATION)
    assert np.linalg.norm(baseline[0, :3]) < 1e-12
    return geometry, material, names, offsets, points, tracks, key_axes


def _anchor_pivot(points, material, degrees=_PIVOT_DEGREES):
    rotation = Rotation.from_rotvec(np.asarray([0., np.deg2rad(degrees), 0.])).as_matrix()
    pivoted = points.copy()
    pivoted[:, 0] = (points[:, 0] - material) @ rotation.T + material  # ankle
    pivoted[:, 1] = (points[:, 1] - material) @ rotation.T + material  # foot
    return rotation, pivoted


def _merged_metrics(key_metrics, fractional_metrics):
    metrics = dict(key_metrics)
    metrics.update({
        'playbackStationarySampleCount': fractional_metrics[
            'playbackStationarySampleCount'],
        'playbackStationaryMaximumErrorMeters': fractional_metrics[
            'playbackStationaryMaximumErrorMeters'],
    })
    return metrics


def test_anchor_pivot_is_legal_at_key_and_fractional_clocks():
    geometry, material, names, offsets, points, tracks, _ = (
        _producer_bound_stationary_fixture())
    rotation, pivoted = _anchor_pivot(points, material)
    pivoted_axes = {
        side: np.tile(rotation @ np.asarray([0., 0., 1.]), (len(points), 1))
        for side in _SIDES}
    pivot_radius = float(np.linalg.norm(material - points[0, 0]))
    # Preserve the v702 closed form: the stale-frame branch would pin the
    # original ankle by this displacement (15.2 mm at 25 degrees), far beyond
    # the unchanged 3 mm dense playback limit.  The corrected branch must not.
    stale_closed_form = 2.0 * pivot_radius * np.sin(np.deg2rad(_PIVOT_DEGREES) / 2.)
    assert stale_closed_form > 3e-3

    # Exact-key authority on the pivoted pose: calibrated actual-shoe material
    # points measured with the transported axes stay on the anchor.
    _, key_metrics = native_material_playback_residuals(
        pivoted, names, offsets, tracks, np.arange(len(points), dtype=float),
        return_metrics=True, interpolation=INTERPOLATION,
        key_side_axes=pivoted_axes,
        native_geometry=geometry, foot_scale=1.)
    assert key_metrics['keyframeStationarySampleCount'] == 4
    assert key_metrics['keyframeStationaryMaximumErrorMeters'] < 1e-9

    # The corrected fractional branch consumes the same candidate ankle/foot
    # and FK-transported material frame at every fractional sample.
    fractional_axes = {
        side: np.tile(rotation @ np.asarray([0., 0., 1.]), (3, 1))
        for side in _SIDES}
    fractional_residual, fractional_metrics = native_material_playback_residuals(
        np.tile(pivoted[0], (3, 1, 1)), names, offsets, tracks,
        [0.25, 0.5, 0.75], return_metrics=True,
        interpolation=INTERPOLATION, fractional_side_axes=fractional_axes)
    assert fractional_residual.shape == (3, 6)
    assert float(np.abs(fractional_residual).max()) < 1e-9
    assert fractional_metrics['playbackStationarySampleCount'] == 6
    assert native_material_contact_verdict(
        _merged_metrics(key_metrics, fractional_metrics),
        required=native_material_key_sample_requirements(tracks))['passed'] is True

    # Bone lengths and the actual material points themselves survive the pivot.
    for side in _SIDES:
        ankle, foot = _JOINT_INDEX[side]
        assert abs(np.linalg.norm(pivoted[0, foot] - pivoted[0, ankle])
                   - np.linalg.norm(points[0, foot] - points[0, ankle])) < 1e-12


def test_ankle_fixed_foot_twist_that_displaces_anchor_fails_fractional():
    geometry, material, names, offsets, points, tracks, _ = (
        _producer_bound_stationary_fixture(sides=('left',)))
    # Rotate the foot frame about the ankle-held ankle-to-foot bone: the ankle
    # and bone direction are unchanged, only the carried side axis twists.
    twist = Rotation.from_rotvec(np.asarray([np.deg2rad(30.), 0., 0.])).as_matrix()
    twisted = points.copy()
    twisted[:, 1] = (points[:, 1] - points[:, 0]) @ twist.T + points[:, 0]
    twisted_axes = {'left': np.tile(twist @ np.asarray([0., 0., 1.]), (len(points), 1))}
    twisted_fractional_axes = {
        'left': np.tile(twist @ np.asarray([0., 0., 1.]), (1, 1))}
    displacement = 2.0 * abs(float(np.dot(
        material - points[0, 0], np.asarray([0., 0., 1.])))) * np.sin(np.deg2rad(15.))
    assert displacement > 3e-3
    residual = native_material_playback_residuals(
        twisted[:1], names, offsets, tracks, [0.5],
        interpolation=INTERPOLATION, fractional_side_axes=twisted_fractional_axes)
    assert float(np.linalg.norm(residual[0, :3])) > 3e-3
    _, key_metrics = native_material_playback_residuals(
        twisted, names, offsets, tracks, np.arange(len(points), dtype=float),
        return_metrics=True, interpolation=INTERPOLATION,
        key_side_axes=twisted_axes, native_geometry=geometry, foot_scale=1.)
    _, fractional_metrics = native_material_playback_residuals(
        twisted[:1], names, offsets, tracks, [0.5], return_metrics=True,
        interpolation=INTERPOLATION, fractional_side_axes=twisted_fractional_axes)
    verdict = native_material_contact_verdict(
        _merged_metrics(key_metrics, fractional_metrics),
        required=native_material_key_sample_requirements(tracks))
    assert verdict['passed'] is False
    assert verdict['reason'] == 'native_material_typed_contact_exceeded'
    failed = [row['feature'] for row in verdict['components'] if not row['passed']]
    assert 'playback_stationary_material_xyz' in failed
