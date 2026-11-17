"""Native material authority: typed clocks/modes and point-vs-heading ownership."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.contact_interpolation import (
    _native_material_point,
    native_material_key_sample_requirements,
    native_material_playback_residuals,
)
from exercise_motion_pkg.controlled_motion import (
    FixedRig,
    native_material_contact_verdict,
    support_foot_direction_changes,
)
from exercise_motion_pkg.foot_geometry import shoe_vertices
from exercise_motion_pkg.joint_plant_initialization import (
    _native_material_point_solver_constraints,
)
from exercise_motion_pkg.material_region_support import shoe_triangles
from exercise_motion_pkg.native_foot_geometry import validated_native_foot_geometry
from exercise_motion_pkg.support_geometry import _support_foot_p95_rows


def _geometry():
    fixture = json.loads((Path(__file__).parent / 'fixtures'
                          / 'native_foot_geometry_v1.json').read_text())
    return validated_native_foot_geometry(fixture['reference'])


def _stationary_track(*, target_world, triangle=11, barycentric=(.2, .3, .5),
                      sides=('left',)):
    names, offsets, joints, tracks, side_axes = [], [], [], {}, {}
    side_axis = np.asarray([0., 0., 1.])
    for side in sides:
        names.extend([f'{side}_ankle', f'{side}_foot'])
        offsets.extend([[0., 0., 0.], [.134302, 0., 0.]])
        joints.extend([[0., 0., 0.], [.134302, 0., 0.]])
        tracks[side] = {
            'active': [True, True],
            'directions': [[1., 0., 0.], [1., 0., 0.]],
            'sideAxes': [side_axis.tolist(), side_axis.tolist()],
            'anchorIds': ['anchor-a', 'anchor-a'],
            'episodes': [{
                'startFrame': 0,
                'endFrame': 1,
                'anchorId': 'anchor-a',
                'regionRole': 'forefoot',
                'mode': 'stationary',
                'primitiveId': f'wearShoe:{side}_ankle->{side}_foot',
                'triangleIndex': triangle,
                'barycentric': list(barycentric),
                'materialOffsetLocalMeters': [0., 0., 0.],
                'referenceLengthMeters': .134302,
                'targetWorld': list(target_world),
                'surfaceNormal': [0., 1., 0.],
                'planeOffsetMeters': 0.,
            }],
        }
        side_axes[side] = np.tile(side_axis, (2, 1))
    return (names, np.asarray(offsets), np.repeat(
        np.asarray(joints)[None], 2, axis=0),
        {'version': 2, **tracks}, side_axes)


def _mesh_material(geometry, triangle, barycentric):
    mesh = shoe_vertices(
        np.asarray([0., 0., 0.]), np.asarray([.134302, 0., 0.]),
        np.asarray([0., 0., 1.]), None, 1.,
        native_geometry=geometry['sides']['left'])
    return np.asarray(barycentric) @ mesh[shoe_triangles()[triangle]]


def test_typed_native_material_verdict_does_not_mix_clocks_or_modes():
    """The v684 mixed aggregate compared height/playback evidence to 0.5 mm."""
    metrics = {
        'available': True,
        'keyframeStationarySampleCount': 2,
        'keyframeStationaryMaximumErrorMeters': .000248155,
        'keyframeHeightSampleCount': 112,
        'keyframeHeightMaximumErrorMeters': .0013568171553992592,
        'playbackStationarySampleCount': 369,
        'playbackStationaryMaximumErrorMeters': .0008649785478899873,
        'playbackHeightSampleCount': 327,
        'playbackHeightMaximumErrorMeters': .0010635571096124785,
        'maximumErrorMeters': .0013568171553992592,
    }
    required = {
        'keyframeStationarySampleCount': 2,
        'keyframeHeightSampleCount': 112,
    }
    # Reproduce the defect: a single mixed maximum cannot pass the 0.5 mm
    # keyframe anchor even though every typed component is inside its contract.
    assert not metrics['maximumErrorMeters'] < .0005

    verdict = native_material_contact_verdict(metrics, required=required)
    assert verdict['passed'] is True, verdict

    # A genuine stationary keyframe anchor violation still fails at 0.5 mm.
    violating = dict(metrics, keyframeStationaryMaximumErrorMeters=.00065)
    verdict = native_material_contact_verdict(violating, required=required)
    assert verdict['passed'] is False
    assert any(row['feature'] == 'keyframe_stationary_material_xyz'
               and row['passed'] is False for row in verdict['components'])

    # A required stationary proof that is missing must fail closed.
    missing = dict(metrics, keyframeStationarySampleCount=0,
                   keyframeStationaryMaximumErrorMeters=0.)
    verdict = native_material_contact_verdict(missing, required=required)
    assert verdict['passed'] is False
    assert verdict['reason'] == 'native_material_required_proof_missing'


def test_stationary_keyframe_material_xyz_is_measured_on_the_actual_shoe():
    geometry = _geometry()
    material = _mesh_material(geometry, 11, (.2, .3, .5))
    names, offsets, points, tracks, side_axes = _stationary_track(
        target_world=material)

    _, metrics = native_material_playback_residuals(
        points, names, offsets, tracks, np.arange(2, dtype=float),
        return_metrics=True, key_side_axes=side_axes,
        native_geometry=geometry, foot_scale=1.)
    assert metrics['keyframeStationarySampleCount'] == 2
    assert metrics['keyframeStationaryMaximumErrorMeters'] <= 1e-9
    assert native_material_key_sample_requirements(tracks) == {
        'keyframeStationarySampleCount': 2, 'keyframeHeightSampleCount': 0}

    # The playback clock keeps preserving exact keys: without calibrated key
    # geometry there is no stationary keyframe sample to score.
    _, playback_metrics = native_material_playback_residuals(
        points, names, offsets, tracks, [0.], return_metrics=True)
    assert playback_metrics['keyframeStationarySampleCount'] == 0

    # 0.45 mm vertical drift stays inside the 0.5 mm keyframe anchor.
    inside = points.copy()
    inside[:, :, 1] += .00045
    _, inside_metrics = native_material_playback_residuals(
        inside, names, offsets, tracks, np.arange(2, dtype=float),
        return_metrics=True, key_side_axes=side_axes,
        native_geometry=geometry, foot_scale=1.)
    assert inside_metrics['keyframeStationaryMaximumErrorMeters'] < .0005
    assert native_material_contact_verdict(
        inside_metrics, required=native_material_key_sample_requirements(tracks)
    )['passed'] is True

    # 0.65 mm drift is a real stationary keyframe violation.
    outside = points.copy()
    outside[:, :, 1] += .00065
    _, outside_metrics = native_material_playback_residuals(
        outside, names, offsets, tracks, np.arange(2, dtype=float),
        return_metrics=True, key_side_axes=side_axes,
        native_geometry=geometry, foot_scale=1.)
    assert outside_metrics['keyframeStationaryMaximumErrorMeters'] > .0005
    assert native_material_contact_verdict(
        outside_metrics, required=native_material_key_sample_requirements(tracks)
    )['passed'] is False


def test_playback_clock_measures_both_sides_without_state_leak():
    """A second side must still measure the pose, not the first side's totals."""
    geometry = _geometry()
    material = _mesh_material(geometry, 11, (.2, .3, .5))
    names, offsets, points, tracks, side_axes = _stationary_track(
        target_world=material, sides=('left', 'right'))
    # Right-side world points are identical by construction; displace the right
    # material away from its anchor so both sides must report a real error.
    points[:, 2:] += np.asarray([0., .01, 0.])
    residual, metrics = native_material_playback_residuals(
        points, names, offsets, tracks, [0.5], return_metrics=True)
    assert residual.shape == (1, 6)
    assert metrics['sampleCount'] == 2
    assert metrics['playbackStationarySampleCount'] == 2
    assert set(metrics['bySide']) == {'left', 'right'}
    assert metrics['bySide']['right']['maximumErrorMeters'] > 1e-6


def test_stationary_material_point_holds_while_foot_heading_rotates():
    """Controlled pose proof: yaw changes about a fixed material point."""
    geometry = _geometry()
    triangle, barycentric = 11, np.asarray([.2, .3, .5])
    ankle = np.asarray([0., 0., 0.])
    foot = np.asarray([.134302, 0., 0.])
    side = np.asarray([0., 0., 1.])
    episode = {'triangleIndex': triangle, 'barycentric': barycentric.tolist()}
    material = _native_material_point(
        ankle, foot, side, episode, geometry['sides']['left'], 1.)

    rotation = Rotation.from_rotvec(np.asarray([0., np.deg2rad(25.), 0.])).as_matrix()
    ankle_b = rotation @ (ankle - material) + material
    foot_b = rotation @ (foot - material) + material
    side_b = rotation @ side
    material_b = _native_material_point(
        ankle_b, foot_b, side_b, episode, geometry['sides']['left'], 1.)
    np.testing.assert_allclose(material_b, material, atol=1e-12)
    np.testing.assert_allclose(
        np.linalg.norm(foot_b - ankle_b), np.linalg.norm(foot - ankle), atol=1e-12)
    heading_a = np.arctan2(foot[0] - ankle[0], foot[2] - ankle[2])
    heading_b = np.arctan2(foot_b[0] - ankle_b[0], foot_b[2] - ankle_b[2])
    assert abs(np.degrees(heading_b - heading_a)) > 20.


def test_native_material_point_constraints_seed_without_fit_authority():
    """Seed pins place the material point but are explicitly not fit pins."""
    fixture = json.loads((Path(__file__).parent / 'fixtures'
                          / 'sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.repeat(
        np.asarray([fixture['joints'][name] for name in names], dtype=float)[None],
        3, axis=0)
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    decoded = rig.decode(coordinates)
    ankle_i, toe_i = names.index('left_ankle'), names.index('left_foot')
    forward = decoded[:, toe_i] - decoded[:, ankle_i]
    forward /= np.linalg.norm(forward, axis=1)[:, None]
    lateral = np.stack([-forward[:, 2], np.zeros(len(forward)), forward[:, 0]], axis=1)
    lateral /= np.linalg.norm(lateral, axis=1)[:, None]
    tracks = {
        'version': 2,
        'left': {
            'active': [True, True, True],
            'directions': forward.tolist(),
            'sideAxes': lateral.tolist(),
            'anchorIds': ['anchor-a'] * 3,
            'episodes': [{
                'startFrame': 0, 'endFrame': 2, 'anchorId': 'anchor-a',
                'regionRole': 'forefoot', 'mode': 'stationary',
                'primitiveId': 'wearShoe:left_ankle->left_foot',
                'triangleIndex': 0, 'barycentric': [1., 0., 0.],
                'materialOffsetLocalMeters': [.01, 0., 0.],
                'referenceLengthMeters': float(np.linalg.norm(rig.offsets[toe_i])),
                'targetWorld': decoded[0, toe_i].tolist(),
                'surfaceNormal': [0., 1., 0.], 'planeOffsetMeters': 0.,
            }],
        },
    }
    pinned = np.zeros(decoded.shape[:2], dtype=bool)
    targets = decoded.copy()
    result = _native_material_point_solver_constraints(
        rig, decoded, coordinates, pinned, targets, native_foot_tracks=tracks)
    # The initializer may derive a stored-direction seed for the closed chain...
    assert result['pins'][:, ankle_i].all()
    assert result['pins'][:, toe_i].all()
    ankle_target = result['targets'][:, ankle_i]
    # ...reconstructing playback's stored-direction material point on target.
    forward = np.asarray(tracks['left']['directions'], dtype=float)
    lateral = np.asarray(tracks['left']['sideAxes'], dtype=float)
    up = np.cross(lateral, forward)
    local = np.asarray(tracks['left']['episodes'][0][
        'materialOffsetLocalMeters'], dtype=float)
    offset = ((forward * local[0] + lateral * local[1] + up * local[2])
              * (np.linalg.norm(rig.offsets[toe_i])
                 / tracks['left']['episodes'][0]['referenceLengthMeters']))
    np.testing.assert_allclose(
        ankle_target + offset,
        np.broadcast_to(tracks['left']['episodes'][0]['targetWorld'],
                        ankle_target.shape),
        atol=1e-9)
    # ...but the report declares residual ownership for the main fit.
    assert result['report']['seedOnly'] is True
    assert result['report']['fitAuthority'] == 'calibrated_material_point_residual'
    assert result['report']['pinsDerived'] == int(np.count_nonzero(result['pins']))
    assert 'left' in result['coverage']


def test_camera_ray_heading_authority_replaces_only_the_3d_heading_row():
    fixture = json.loads((Path(__file__).parent / 'fixtures'
                          / 'sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.repeat(
        np.asarray([fixture['joints'][name] for name in names], dtype=float)[None],
        3, axis=0)
    rig = FixedRig(points, names)
    reference = rig.decode(rig.initial)
    coordinates = rig.initial.copy()
    foot_i = names.index('left_foot')
    parent_i = rig.parents[foot_i]
    foot_slot = rig.slots[foot_i]
    world = rig.global_rotations(coordinates)
    parent_world = world[parent_i]
    delta = Rotation.from_rotvec(
        np.asarray([0., np.deg2rad(30.), 0.])).as_matrix()
    desired = delta @ world[foot_i]
    local = np.einsum('fji,fjk->fik', parent_world, desired)
    coordinates[:, foot_slot:foot_slot + 3] = Rotation.from_matrix(
        local).as_rotvec()
    candidate = rig.decode(coordinates)
    authority = np.ones(np.asarray(reference).shape[:2], dtype=bool)

    changes = support_foot_direction_changes(
        reference, candidate, names, authority,
        heading_authority={'left': np.zeros(3, dtype=bool),
                           'right': np.ones(3, dtype=bool)})
    assert not changes['left']['headingQualifiedMask'].any()
    assert changes['left']['qualifiedMask'].all()
    assert np.rad2deg(np.max(changes['left']['headingDeltaRadians'])) > 20.

    without = _support_foot_p95_rows(rig, coordinates, reference, authority)
    with_camera = _support_foot_p95_rows(
        rig, coordinates, reference, authority,
        {'left': np.zeros(3, dtype=bool), 'right': np.ones(3, dtype=bool)})
    assert without.shape == with_camera.shape == (4,)
    assert without[0] > 0.
    assert with_camera[0] == 0.
