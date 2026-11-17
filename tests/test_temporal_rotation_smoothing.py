import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.temporal_rotation_smoothing import (
    _nearest_rotation,
    temporal_world_rotation_smooth,
)


def _stance(frame_count):
    fixture = json.loads(
        (Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile(np.asarray(list(fixture['joints'].values())), (frame_count, 1, 1))
    return names, points


def test_temporal_polish_smooths_root_travel_while_restoring_planted_feet():
    names, points = _stance(15)
    rig = motion.FixedRig(points, names)
    coordinates = rig.initial.copy()
    coordinates[:, 0] += .005 * (-1.) ** np.arange(len(points))
    pins = np.zeros(points.shape[:2], dtype=bool)
    for side in ('left', 'right'):
        for joint in ('ankle', 'foot'):
            pins[:, names.index(f'{side}_{joint}')] = True
    targets = rig.decode(rig.initial)

    polished = motion.polish_free_temporal_preserving_anatomy(
        coordinates, rig, pins, targets, cyclic=False, sigma=1.75,
        reference=points)

    before = np.linalg.norm(np.diff(coordinates[:, :3], n=3, axis=0))
    after = np.linalg.norm(np.diff(polished[:, :3], n=3, axis=0))
    assert after < before * .5
    error = np.linalg.norm((rig.decode(polished) - targets)[pins], axis=-1)
    assert np.max(error) < motion.KEYFRAME_CONTACT_LIMIT_METERS


def test_world_smoothing_preserves_child_compensation_under_locked_parent():
    count = 15
    names, points = _stance(count)
    rig = motion.FixedRig(points, names)
    coordinates = rig.initial.copy()
    pelvis = names.index('pelvis')
    spine1 = names.index('spine1')
    pelvis_slot = rig.slots[pelvis]
    child_slot = rig.slots[spine1]
    phase = np.linspace(-1., 1., count)

    initial_world = rig.global_rotations(coordinates, project_socket=False)
    held_child_world = initial_world[spine1][0]
    for frame, angle in enumerate(.35 * phase):
        coordinates[frame, pelvis_slot:pelvis_slot + 3] = Rotation.from_rotvec(
            [angle, 0., 0.]).as_rotvec()
        parent_world = rig.global_rotations(
            coordinates[frame:frame + 1], project_socket=False)[pelvis][0]
        coordinates[frame, child_slot:child_slot + 3] = Rotation.from_matrix(
            parent_world.T @ held_child_world).as_rotvec()

    pins = np.zeros((count, len(names)), dtype=bool)
    pins[:, names.index('right_foot')] = True
    smoothed = temporal_world_rotation_smooth(
        coordinates, rig, pins, cyclic=False, sigma=1.5)
    result_world = rig.global_rotations(smoothed, project_socket=False)

    np.testing.assert_array_equal(smoothed[:, :3], coordinates[:, :3])
    np.testing.assert_array_equal(smoothed[:, pelvis_slot:pelvis_slot + 3],
                                  coordinates[:, pelvis_slot:pelvis_slot + 3])
    np.testing.assert_allclose(result_world[spine1],
                               np.broadcast_to(held_child_world, (count, 3, 3)),
                               atol=1e-10)
    for joint in rig.order:
        if np.all(pins[:, joint]):
            slot = rig.slots.get(joint)
            if slot is not None:
                np.testing.assert_array_equal(
                    smoothed[:, slot:slot + 3], coordinates[:, slot:slot + 3])


def test_world_mean_smooths_across_rotvec_branch_cut():
    count = 9
    names, points = _stance(count)
    rig = motion.FixedRig(points, names)
    coordinates = rig.initial.copy()
    joint = names.index('left_wrist')
    slot = rig.slots[joint]
    angles = np.deg2rad([176., 178., 179., -179., -178., -176., -174., -172., -170.])
    coordinates[:, slot:slot + 3] = np.column_stack((angles, np.zeros((count, 2))))
    pins = np.zeros((count, len(names)), dtype=bool)

    smoothed = temporal_world_rotation_smooth(
        coordinates, rig, pins, cyclic=False, sigma=1.2)
    original_rotations = Rotation.from_rotvec(coordinates[:, slot:slot + 3])
    smoothed_rotations = Rotation.from_rotvec(smoothed[:, slot:slot + 3])
    angular_change = (original_rotations.inv() * smoothed_rotations).magnitude()

    assert np.isfinite(smoothed).all()
    assert np.max(angular_change) < np.deg2rad(5.)


def test_rank_one_rotation_mean_falls_back_to_observed_orientation():
    fallback = Rotation.from_euler('xyz', [0.2, -0.1, 0.3]).as_matrix()
    ambiguous_mean = np.diag([1., 0., 0.])

    result = _nearest_rotation(ambiguous_mean, fallback)

    np.testing.assert_array_equal(result, fallback)
