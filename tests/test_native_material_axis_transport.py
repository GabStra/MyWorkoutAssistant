import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates


class _TinyRig:
    def __init__(self):
        self.names = ['pelvis', 'right_ankle', 'right_foot']
        self.parents = [-1, 0, 1]
        self.order = [0, 1, 2]
        self.active = [0, 1, 2]
        self.slots = {0: 3, 1: 6, 2: 9}
        self.offsets = np.asarray([[0., 0., 0.], [0., -1., 0.], [0., 0., .2]])
        self.material_reference_coordinates = np.zeros((3, 12), dtype=float)
        # Give the reference foot a changing parent-frame basis so fractional
        # sampling must follow the reference rig clock as well.
        self.material_reference_coordinates[0, 6:9] = [0., 0., .15]
        self.material_reference_coordinates[1, 6:9] = [0., 0., .4]
        self.material_reference_coordinates[2, 6:9] = [0., 0., .7]
        self.initial = self.material_reference_coordinates.copy()

    def global_rotations(self, values):
        values = np.asarray(values, dtype=float)
        if values.ndim == 1:
            values = values[None, :]
        local = Rotation.from_rotvec(values[:, 3:].reshape(-1, 3)).as_matrix().reshape(
            len(values), len(self.active), 3, 3)
        world = {}
        for joint in self.order:
            matrix = local[:, self.active.index(joint)]
            parent = self.parents[joint]
            world[joint] = matrix if parent < 0 else world[parent] @ matrix
        return world

    def decode_points(self, values):
        values = np.asarray(values, dtype=float)
        if values.ndim == 1:
            values = values[None, :]
        world = self.global_rotations(values)
        points = np.empty((len(values), len(self.names), 3), dtype=float)
        points[:, 0] = values[:, :3]
        for joint in self.order[1:]:
            parent = self.parents[joint]
            points[:, joint] = points[:, parent] + np.einsum(
                'fij,j->fi', world[parent], self.offsets[joint])
        return points


def _evidence(side_axes):
    return {'_nativeFootMaterialTracks': {
        'version': 2,
        'right': {'sideAxes': np.asarray(side_axes, dtype=float).tolist()},
    }}


def test_native_axes_follow_fractional_reference_clock_and_terminal_fk():
    from exercise_motion_pkg.rig_interpolation import INTERPOLATION
    from exercise_motion_pkg.rig_interpolation import hermite_samples
    from exercise_motion_pkg.rig_playback import sample_rig_coordinates

    rig = _TinyRig()
    reference = rig.material_reference_coordinates
    reference_rig = {'coordinates': reference, 'interpolation': INTERPOLATION}
    foot = rig.names.index('right_foot')
    reference_world = rig.global_rotations(reference)[foot]
    local_axis = np.asarray([1., 0., 0.])
    source_axes = np.einsum('fij,fj->fi', reference_world, np.broadcast_to(
        local_axis, (len(reference), 3)))
    evidence = _evidence(source_axes)

    integer = _native_side_axes_for_coordinates(
        rig, reference[[0, 2]], evidence, frame_positions=[0., 2.])['right']
    np.testing.assert_allclose(integer, source_axes[[0, 2]], atol=1e-12)
    legacy_integer = _native_side_axes_for_coordinates(
        rig, reference[[0, 2]], evidence, frame_indices=[0, 2])['right']
    np.testing.assert_allclose(legacy_integer, source_axes[[0, 2]], atol=1e-12)

    cursor = .5
    sampled_reference = sample_rig_coordinates(reference_rig, [cursor])
    current = sampled_reference.copy()
    current[:, rig.slots[foot]:rig.slots[foot] + 3] = [0., .6, 0.]
    # Terminal foot twist changes its world material axis without moving any joint.
    np.testing.assert_allclose(rig.decode_points(current), rig.decode_points(sampled_reference),
                               atol=1e-12)
    transported = _native_side_axes_for_coordinates(
        rig, current, evidence, frame_positions=[cursor])['right']
    sampled_source_axis = hermite_samples(
        source_axes, np.asarray([0]), np.asarray([1]), np.asarray([cursor]),
        wrap=False, smooth_limiter=True)[0]
    expected = rig.global_rotations(current)[foot][0] @ (
        rig.global_rotations(sampled_reference)[foot][0].T @ sampled_source_axis)
    np.testing.assert_allclose(transported[0], expected, atol=1e-12)
    assert np.linalg.norm(transported[0] - source_axes[0]) > .1


def test_native_axis_transport_keeps_legacy_none_without_tracks():
    rig = _TinyRig()
    assert _native_side_axes_for_coordinates(
        rig, rig.material_reference_coordinates[:1], {}) is None
