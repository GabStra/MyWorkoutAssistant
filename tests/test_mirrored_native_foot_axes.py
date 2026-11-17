import json
from copy import deepcopy
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates
from exercise_motion_pkg.supported_contact_rig import project_mirrored_native_foot_axes


def _case():
    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    pose = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    rig = motion.FixedRig(np.tile(pose, (2, 1, 1)), names)
    q = rig.initial.copy()
    world = rig.global_rotations(q)
    tracks = {'version': 2}
    for side in ('left', 'right'):
        foot = names.index(f'{side}_foot')
        axes = world[foot] @ np.asarray([1., 0., 0.])
        tracks[side] = {
            'active': [side == 'right', side == 'right'],
            'sideAxes': axes.tolist(),
        }
    return rig, q, tracks


def _mirrored_side_axis(points, names, active_axis, target_side):
    left_hip, right_hip = (points[names.index(f'{side}_hip')]
                           for side in ('left', 'right'))
    normal = right_hip - left_hip
    normal /= np.linalg.norm(normal)
    desired = -(active_axis - 2. * normal * np.dot(active_axis, normal))
    ankle, foot = (points[names.index(f'left_{part}')]
                   for part in ('ankle', 'foot')) if target_side == 'left' else (
        points[names.index(f'right_{part}')] for part in ('ankle', 'foot'))
    forward = foot - ankle
    forward /= np.linalg.norm(forward)
    desired -= forward * np.dot(desired, forward)
    return desired / np.linalg.norm(desired)


def test_mirrored_native_axis_bake_changes_only_unobserved_terminal_roll():
    rig, q, tracks = _case()
    names = rig.names
    left_foot = names.index('left_foot')
    right_foot = names.index('right_foot')
    left_slot, right_slot = rig.slots[left_foot], rig.slots[right_foot]
    q[:, left_slot:left_slot + 3] = (
        Rotation.from_rotvec(np.tile([.0, .65, .0], (len(q), 1)))
        * Rotation.from_rotvec(q[:, left_slot:left_slot + 3])).as_rotvec()
    original_tracks = deepcopy(tracks)
    before_points = rig.decode(q)
    before_axes = _native_side_axes_for_coordinates(
        rig, q, {'_nativeFootMaterialTracks': tracks})
    desired_left = np.asarray([
        _mirrored_side_axis(before_points[row], names, before_axes['right'][row], 'left')
        for row in range(len(q))])

    projected = project_mirrored_native_foot_axes(rig, q, tracks)
    after_points = rig.decode(projected)
    after_axes = _native_side_axes_for_coordinates(
        rig, projected, {'_nativeFootMaterialTracks': tracks})

    np.testing.assert_allclose(after_points, before_points, atol=1e-12)
    np.testing.assert_allclose(projected[:, right_slot:right_slot + 3],
                               q[:, right_slot:right_slot + 3], atol=0.)
    np.testing.assert_allclose(after_axes['right'], before_axes['right'], atol=1e-12)
    np.testing.assert_allclose(after_axes['left'], desired_left, atol=1e-10)
    assert np.max(np.linalg.norm(after_axes['left'] - before_axes['left'], axis=1)) > .1
    assert tracks == original_tracks
    assert tracks['right']['active'] == [True, True]
    assert tracks['left']['active'] == [False, False]

    both_active = deepcopy(tracks)
    both_active['left']['active'] = [True, True]
    np.testing.assert_array_equal(
        project_mirrored_native_foot_axes(rig, q, both_active), q)
    no_active = deepcopy(tracks)
    no_active['right']['active'] = [False, False]
    np.testing.assert_array_equal(
        project_mirrored_native_foot_axes(rig, q, no_active), q)
