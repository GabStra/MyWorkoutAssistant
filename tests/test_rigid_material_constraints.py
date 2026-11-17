import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.rigid_material_constraints import rigid_material_point_kinematics


def make_rig(frame_count=3):
    fixture = json.loads((Path(__file__).parent / 'fixtures' / 'sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile(np.asarray([fixture['joints'][name] for name in names], dtype=float),
                     (frame_count, 1, 1))
    return FixedRig(points, names)


def test_material_point_jacobian_matches_full_point_finite_differences():
    rig = make_rig()
    coordinates = rig.initial.copy()
    coordinates[:, 0] += [0.0, 0.025, -0.01]
    coordinates[:, rig.slots[rig.names.index('left_knee')]] += [0.04, -0.03, 0.02]
    origin = rig.names.index('left_ankle')
    rotation = rig.names.index('left_foot')
    local = np.asarray([[0.045, 0.012, -0.018],
                        [0.03, -0.04, 0.02],
                        [-0.02, 0.01, 0.035]])
    active = np.asarray([True, False, True])

    points, jacobian = rigid_material_point_kinematics(
        rig, coordinates, origin, rotation, local, active)
    assert jacobian.shape == (len(coordinates) * 3, len(coordinates) * rig.width)
    assert jacobian.format == 'csr'
    np.testing.assert_array_equal(jacobian[3:6].toarray(), 0.)
    expected = (rig.decode(coordinates)[:, origin]
                + np.einsum('fij,fj->fi',
                            rig.global_rotations(coordinates)[rotation], local))
    np.testing.assert_allclose(points, expected, atol=1e-12)

    frame = 2
    columns = [0, rig.slots[rig.root], rig.slots[rig.names.index('left_knee')],
               rig.slots[rig.names.index('left_ankle')], rig.slots[rotation] + 1]
    for column in columns:
        step = 1e-6
        plus = coordinates.copy()
        minus = coordinates.copy()
        plus[frame, column] += step
        minus[frame, column] -= step
        plus_point, _ = rigid_material_point_kinematics(
            rig, plus, origin, rotation, local, active)
        minus_point, _ = rigid_material_point_kinematics(
            rig, minus, origin, rotation, local, active)
        numeric = (plus_point[frame] - minus_point[frame]) / (2. * step)
        analytic = jacobian[frame * 3:(frame + 1) * 3,
                            frame * rig.width + column].toarray().ravel()
        np.testing.assert_allclose(analytic, numeric, rtol=3e-5, atol=3e-7)

    inactive_columns = np.arange(rig.width, 2 * rig.width)
    np.testing.assert_array_equal(jacobian[3:6, inactive_columns].toarray(), 0.)
    assert np.isfinite(points).all()


def test_rigid_roll_moves_material_point_while_held_joint_stays_fixed():
    rig = make_rig(frame_count=2)
    coordinates = rig.initial.copy()
    foot = rig.names.index('left_foot')
    slot = rig.slots[foot]
    coordinates[:, slot:slot + 3] = [0., 0., 0.]
    rolled = coordinates.copy()
    rolled[:, slot:slot + 3] = [0., 0.45, 0.]
    local = np.tile([0.05, 0., 0.], (len(coordinates), 1))

    held_before = rig.decode(coordinates)[:, foot]
    held_after = rig.decode(rolled)[:, foot]
    point_before, _ = rigid_material_point_kinematics(
        rig, coordinates, foot, foot, local)
    point_after, _ = rigid_material_point_kinematics(
        rig, rolled, foot, foot, local)

    np.testing.assert_allclose(held_before, held_after, atol=1e-12)
    assert np.max(np.linalg.norm(point_after - point_before, axis=-1)) > 0.01


def test_zero_local_offset_keeps_origin_jacobian_and_masks_only_inactive_frames():
    rig = make_rig()
    coordinates = rig.initial.copy()
    origin = rig.names.index('right_knee')
    active = np.asarray([True, False, True])
    zero_local = np.zeros((len(coordinates), 3))

    points, jacobian = rigid_material_point_kinematics(
        rig, coordinates, origin, rig.names.index('right_foot'), zero_local, active)
    full_fk = rig.fk_jacobian(coordinates)
    rows = (np.arange(len(coordinates))[:, None] * len(rig.names) * 3
            + origin * 3 + np.arange(3)[None, :]).ravel()
    expected = full_fk[rows].toarray()
    expected[3:6] = 0.

    np.testing.assert_allclose(points, rig.decode(coordinates)[:, origin], atol=1e-12)
    np.testing.assert_allclose(jacobian.toarray(), expected, atol=1e-12)
