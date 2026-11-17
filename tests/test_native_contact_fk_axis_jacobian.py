import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.contact_interpolation import (
    native_material_playback_residuals,
    refresh_contact_foot_tracks,
)
from exercise_motion_pkg.foot_geometry import shoe_vertices
from exercise_motion_pkg.material_region_support import shoe_triangles
from exercise_motion_pkg.rig_playback import sample_rig_coordinates
from exercise_motion_pkg.support_geometry import (
    _native_foot_material_contact_residuals,
    _native_side_axes_for_coordinates,
)
from exercise_motion_pkg.supported_contact_rig import _material_frame


def _case(frame_count):
    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    pose = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    rig = motion.FixedRig(np.tile(pose, (frame_count, 1, 1)), names)
    coordinates = rig.initial.copy()
    points = rig.decode(coordinates)
    foot = names.index('right_foot')
    ankle = names.index('right_ankle')
    source_axis = rig.global_rotations(rig.material_reference_coordinates)[foot]
    source_axis = np.broadcast_to(source_axis @ np.array([1., 0., 0.]), (frame_count, 3)).copy()
    geometry = json.loads((Path(__file__).parent / 'fixtures/native_foot_geometry_v1.json').read_text())['reference']
    scale = .5
    triangles = shoe_triangles()
    triangle_index = 12
    bary = np.asarray([.2, .3, .5])
    baseline_axes = _native_side_axes_for_coordinates(
        rig, coordinates, {'_nativeFootMaterialTracks': {'version': 2,
            'right': {'sideAxes': source_axis.tolist()}}})['right']
    mesh = shoe_vertices(points[:, ankle], points[:, foot], baseline_axes, None,
                         scale, native_geometry=geometry['sides']['right'])
    target = bary @ mesh[0, triangles[triangle_index]]
    episode = {
        'startFrame': 0, 'endFrame': frame_count - 1, 'anchorId': 'observed-anchor',
        'regionRole': 'forefoot', 'mode': 'stationary',
        'primitiveId': 'wearShoe:right_ankle->right_foot',
        'triangleIndex': triangle_index, 'barycentric': bary.tolist(),
        'materialOffsetLocalMeters': [0., 0., 0.],
        'referenceLengthMeters': float(np.linalg.norm(rig.offsets[foot])),
        'targetWorld': target.tolist(), 'surfaceNormal': [0., 1., 0.],
        'planeOffsetMeters': float(target[1]),
    }
    track = {
        'version': 2,
        'right': {
            'active': [True] * frame_count,
            'directions': ((points[:, foot] - points[:, ankle]) /
                           np.linalg.norm(points[:, foot] - points[:, ankle], axis=1)[:, None]).tolist(),
            'sideAxes': source_axis.tolist(),
            'anchorIds': ['observed-anchor'] * frame_count,
            'episodes': [episode],
        },
    }
    evidence = {'_nativeFootMaterialTracks': track, 'nativeFootGeometry': geometry,
                '_nativeFootScale': scale}
    return rig, names, coordinates, points, evidence, track, source_axis


def _contact_rows(points, names, evidence, axes, positions=None):
    return _native_foot_material_contact_residuals(
        points, names, evidence, frame_positions=positions,
        side_axes_override={'right': axes})[0][:, :3]


def test_native_material_rows_follow_terminal_and_ancestor_fk_in_key_and_dense_paths():
    rig, names, coordinates, points, evidence, track, source_axis = _case(2)
    foot = names.index('right_foot')
    ankle = names.index('right_ankle')
    foot_slot = rig.slots[foot]
    ankle_slot = rig.slots[ankle]
    base_axes = _native_side_axes_for_coordinates(rig, coordinates, evidence)['right']
    base_rows = _contact_rows(points, names, evidence, base_axes, np.arange(2, dtype=float))
    np.testing.assert_allclose(base_rows, 0., atol=1e-10)

    def check_axis_jacobian(slot, local_axis):
        epsilon = 1e-5
        twist = np.array(local_axis, dtype=float, copy=True)
        twist /= np.linalg.norm(twist)
        plus, minus = coordinates.copy(), coordinates.copy()
        for frame in range(len(coordinates)):
            for q, sign in ((plus, 1.), (minus, -1.)):
                coordinate_start = slot
                start = q[frame, coordinate_start:coordinate_start + 3]
                q[frame, coordinate_start:coordinate_start + 3] = (
                    Rotation.from_rotvec(start)
                    * Rotation.from_rotvec(sign * epsilon * twist)).as_rotvec()
        plus_points, minus_points = rig.decode(plus), rig.decode(minus)
        plus_axes = _native_side_axes_for_coordinates(rig, plus, evidence)['right']
        minus_axes = _native_side_axes_for_coordinates(rig, minus, evidence)['right']
        plus_rows = _contact_rows(plus_points, names, evidence, plus_axes, np.arange(2, dtype=float))
        minus_rows = _contact_rows(minus_points, names, evidence, minus_axes, np.arange(2, dtype=float))
        whole_fd = (plus_rows - minus_rows) / (2. * epsilon)
        point_fd = (
            _contact_rows(plus_points, names, evidence, base_axes, np.arange(2, dtype=float))
            - _contact_rows(minus_points, names, evidence, base_axes, np.arange(2, dtype=float))
        ) / (2. * epsilon)
        axis_fd = (
            _contact_rows(points, names, evidence, plus_axes, np.arange(2, dtype=float))
            - _contact_rows(points, names, evidence, minus_axes, np.arange(2, dtype=float))
        ) / (2. * epsilon)
        np.testing.assert_allclose(whole_fd, point_fd + axis_fd, atol=2e-5, rtol=2e-5)
        assert np.linalg.norm(axis_fd) > 1e-5
        return plus

    foot_roll = check_axis_jacobian(foot_slot, rig.offsets[foot])
    np.testing.assert_allclose(rig.decode(foot_roll), points, atol=1e-10)
    ankle_roll = check_axis_jacobian(ankle_slot, np.array([1., 0., 0.]))
    assert np.linalg.norm(rig.decode(ankle_roll) - points) > 1e-7

    # Dense cursor: compare the sampled-q axis block chained through the same
    # Hermite sampler against direct finite differences of source-frame q.
    cursor = np.asarray([.5])
    playback = {'coordinates': coordinates, 'interpolation': motion.INTERPOLATION}
    sample_q = sample_rig_coordinates(playback, cursor, wrap=False)
    sample_points = rig.decode(sample_q)
    sample_axes = _native_side_axes_for_coordinates(
        rig, sample_q, evidence, frame_positions=cursor, wrap=False)['right']
    sample_rows = _contact_rows(sample_points, names, evidence, sample_axes, cursor)
    for slot in (foot_slot, ankle_slot):
        epsilon = 1e-5
        plus, minus = coordinates.copy(), coordinates.copy()
        plus[0, slot + 1] += epsilon
        minus[0, slot + 1] -= epsilon
        plus_q = sample_rig_coordinates({**playback, 'coordinates': plus}, cursor, wrap=False)
        minus_q = sample_rig_coordinates({**playback, 'coordinates': minus}, cursor, wrap=False)
        plus_points, minus_points = rig.decode(plus_q), rig.decode(minus_q)
        plus_axes = _native_side_axes_for_coordinates(
            rig, plus_q, evidence, frame_positions=cursor, wrap=False)['right']
        minus_axes = _native_side_axes_for_coordinates(
            rig, minus_q, evidence, frame_positions=cursor, wrap=False)['right']
        whole_fd = (_contact_rows(plus_points, names, evidence, plus_axes, cursor)
                    - _contact_rows(minus_points, names, evidence, minus_axes, cursor)) / (2. * epsilon)
        point_fd = (_contact_rows(plus_points, names, evidence, sample_axes, cursor)
                    - _contact_rows(minus_points, names, evidence, sample_axes, cursor)) / (2. * epsilon)
        axis_fd = (_contact_rows(sample_points, names, evidence, plus_axes, cursor)
                   - _contact_rows(sample_points, names, evidence, minus_axes, cursor)) / (2. * epsilon)
        np.testing.assert_allclose(whole_fd, point_fd + axis_fd, atol=4e-4, rtol=4e-4)
        assert np.linalg.norm(axis_fd) > 1e-5

    refreshed = refresh_contact_foot_tracks(
        rig, points, track,
        side_axes={'right': _native_side_axes_for_coordinates(rig, foot_roll, evidence)['right']})
    assert refreshed['right']['episodes'] == track['right']['episodes']
    assert refreshed['right']['anchorIds'] == track['right']['anchorIds']
    np.testing.assert_allclose(
        refreshed['right']['sideAxes'],
        _native_side_axes_for_coordinates(rig, foot_roll, evidence)['right'], atol=1e-12)


def _playback_axis_case(frame_count=2):
    """Producer-shaped playback tracks with a real material offset."""
    fixture = json.loads(
        (Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    pose = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    rig = motion.FixedRig(np.tile(pose, (frame_count, 1, 1)), names)
    coordinates = rig.initial.copy()
    points = rig.decode(coordinates)
    geometry = json.loads(
        (Path(__file__).parent / 'fixtures/native_foot_geometry_v1.json').read_text())['reference']
    triangles = shoe_triangles()
    triangle_index, bary = 12, np.asarray([.2, .3, .5])
    scale = .5
    world = rig.global_rotations(rig.material_reference_coordinates)
    tracks = {'version': 2}
    for side in ('left', 'right'):
        ankle, foot = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        axis = np.broadcast_to(
            world[foot][0] @ np.asarray([1., 0., 0.]), (len(points), 3)).copy()
        material = bary @ shoe_vertices(
            points[0, ankle][None], points[0, foot][None], axis[:1], None, scale,
            native_geometry=geometry['sides'][side])[0][triangles[triangle_index]]
        frame, bone = _material_frame(
            points[0, ankle][None], points[0, foot][None], axis[:1])
        local = frame[0].T @ (material - points[0, ankle])
        tracks[side] = {
            'active': [True] * len(points),
            'directions': ((points[:, foot] - points[:, ankle])
                           / np.linalg.norm(points[:, foot] - points[:, ankle],
                                            axis=1)[:, None]).tolist(),
            'sideAxes': axis.tolist(),
            'anchorIds': ['anchor'] * len(points),
            'episodes': [{
                'startFrame': 0, 'endFrame': len(points) - 1, 'anchorId': 'anchor',
                'regionRole': 'forefoot', 'mode': 'stationary',
                'primitiveId': f'wearShoe:{side}_ankle->{side}_foot',
                'triangleIndex': triangle_index, 'barycentric': bary.tolist(),
                'materialOffsetLocalMeters': local.tolist(),
                'referenceLengthMeters': float(bone[0]),
                'targetWorld': material.tolist(),
                'surfaceNormal': [0., 1., 0.],
                'planeOffsetMeters': float(material[1]),
            }],
        }
    evidence = {'_nativeFootMaterialTracks': tracks,
                'nativeFootGeometry': geometry, '_nativeFootScale': scale}
    return rig, names, coordinates, evidence


def test_native_material_playback_axis_jacobian_matches_terminal_roll():
    """The assembled playback block must include d(axes)/dq, not only points."""
    rig, names, coordinates, evidence = _playback_axis_case()
    tracks = evidence['_nativeFootMaterialTracks']
    cursors = np.asarray([.5])
    scale = .5
    weight = 2000. / scale
    playback = {'coordinates': coordinates, 'interpolation': motion.INTERPOLATION}
    fd = np.sqrt(np.finfo(float).eps)
    sub_q = sample_rig_coordinates(playback, cursors, wrap=False)
    sub_points = rig.decode(sub_q)

    def axes_at(q):
        sampled = sample_rig_coordinates(
            {**playback, 'coordinates': q}, cursors, wrap=False)
        return _native_side_axes_for_coordinates(
            rig, sampled, evidence, frame_positions=cursors, wrap=False)

    def playback_rows(points, axes):
        return native_material_playback_residuals(
            points, names, rig.offsets, tracks, cursors, wrap=False,
            interpolation=motion.INTERPOLATION, fractional_side_axes=axes)

    def section(points, axes):
        return weight * playback_rows(points, axes)

    base_axes = axes_at(coordinates)
    base = section(sub_points, base_axes)
    point_jacobian = np.zeros((base.size, len(names) * 3))
    for column in range(point_jacobian.shape[1]):
        probes = sub_points.copy()
        probes.reshape(-1)[column] += fd
        point_jacobian[:, column] = (
            section(probes, base_axes).reshape(-1) - base.reshape(-1)) / fd
    fk_sub = rig.fk_jacobian(sub_q).toarray()
    J_hermite = np.zeros((sub_q.size, coordinates.size))
    for column in range(coordinates.size):
        probes = coordinates.copy()
        probes.reshape(-1)[column] += fd
        J_hermite[:, column] = (
            sample_rig_coordinates({**playback, 'coordinates': probes}, cursors, wrap=False)
            .reshape(-1) - sub_q.reshape(-1)) / fd

    slots = set()
    joint = names.index('right_foot')
    while joint >= 0:
        if joint in rig.slots:
            slots.add(rig.slots[joint])
        joint = rig.parents[joint]
    axis_block = motion._native_material_subframe_axis_jacobian(
        lambda axes: playback_rows(sub_points, axes), axes_at, sub_q,
        sorted(slots), row_start=0, row_stride=base.shape[1],
        axis_scale=weight, fd_step=fd).toarray()

    def direction(joint, local_axis, h=1e-5):
        slot = rig.slots[joint]
        result = np.zeros_like(coordinates)
        for frame in range(len(coordinates)):
            start = coordinates[frame, slot:slot + 3]
            plus = Rotation.from_rotvec(start) * Rotation.from_rotvec(
                h * np.asarray(local_axis))
            minus = Rotation.from_rotvec(start) * Rotation.from_rotvec(
                -h * np.asarray(local_axis))
            result[frame, slot:slot + 3] = (
                plus.as_rotvec() - minus.as_rotvec()) / (2. * h)
        return result

    def truth(v):
        step = 1e-6
        q_plus, q_minus = coordinates + step * v, coordinates - step * v
        def evaluate(q):
            sampled = sample_rig_coordinates(
                {**playback, 'coordinates': q}, cursors, wrap=False)
            return section(rig.decode(sampled), axes_at(q)).reshape(-1)
        return (evaluate(q_plus) - evaluate(q_minus)) / (2. * step)

    for label, joint, local_axis in (
            ('terminal_foot_roll', names.index('right_foot'), rig.offsets[names.index('right_foot')]),
            ('ancestor_ankle_roll', names.index('right_ankle'), np.array([1., 0., 0.]))):
        v = direction(joint, local_axis)
        expected = truth(v)
        point_only = point_jacobian @ fk_sub @ J_hermite @ v.reshape(-1)
        assembled = (
            point_jacobian @ fk_sub + axis_block) @ J_hermite @ v.reshape(-1)
        assert np.linalg.norm(expected) > 1e-3, label
        np.testing.assert_allclose(assembled, expected, atol=2e-3, rtol=2e-3,
                                   err_msg=label)
        assert np.linalg.norm(assembled - expected) < .1 * np.linalg.norm(
            point_only - expected), label
