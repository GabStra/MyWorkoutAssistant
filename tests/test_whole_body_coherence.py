import numpy as np
from exercise_motion_pkg.whole_body_repair import (
    TorsoCoordinates, body_orientation_axes, pair_distances, torso_shape_pairs, trajectory_acceleration,
)


def test_torso_shape_detects_shear_that_preserves_spinal_bone_lengths():
    names = ['pelvis', 'spine1', 'spine2', 'neck', 'left_hip', 'right_hip']
    source = np.array([[[0., 0., 0.], [0., .3, 0.], [0., .6, 0.],
                        [0., .9, 0.], [-.2, 0., 0.], [.2, 0., 0.]]])
    sheared = source.copy()
    sheared[:, 1] = [.18, .24, 0.]
    sheared[:, 2] = [.36, .48, 0.]
    sheared[:, 3] = [.54, .72, 0.]
    np.testing.assert_allclose(np.linalg.norm(np.diff(source[:, :4], axis=1), axis=-1),
                               np.linalg.norm(np.diff(sheared[:, :4], axis=1), axis=-1))
    pairs = torso_shape_pairs(names)
    assert np.max(abs(pair_distances(sheared, pairs) - pair_distances(source, pairs))) > .1
    rotated = source @ np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]]) + 2.
    np.testing.assert_allclose(pair_distances(rotated, pairs), pair_distances(source, pairs))


def test_acceleration_penalizes_inherited_shake_without_penalizing_constant_velocity():
    time = np.arange(30) / 30.
    smooth = np.tile(time[:, None, None], (1, 2, 3))
    noisy = smooth.copy()
    noisy[:, 0, 0] += .003 * (-1.) ** np.arange(30)
    np.testing.assert_allclose(trajectory_acceleration(smooth, 30., 1.), 0., atol=1e-13)
    assert np.linalg.norm(trajectory_acceleration(noisy, 30., 1.)) > 1.
    # The old correction-only objective is identically zero for noisy input.
    np.testing.assert_array_equal(trajectory_acceleration(noisy - noisy, 30., 1.), 0.)


def test_torso_coordinates_preserve_curved_asymmetric_source_under_rotation():
    names = ['pelvis', 'spine1', 'neck', 'left_hip', 'right_hip', 'left_wrist']
    source = np.tile([[0., 0., 0.], [.1, .3, 0.], [0., .9, .1],
                      [-.2, 0., 0.], [.25, .01, 0.], [-.5, 1., 0.]], (4, 1, 1))
    torso = TorsoCoordinates(source, names, np.zeros(source.shape[:2], dtype=bool))
    coordinates = np.tile([.2, .1, -.1, .2, -.3, .1], (4, 1))
    result = torso.apply(source.copy(), coordinates)
    np.testing.assert_allclose(pair_distances(result, torso_shape_pairs(names)),
                               pair_distances(source, torso_shape_pairs(names)), atol=1e-12)
    np.testing.assert_allclose(result[:, 0], coordinates[:, :3])
    np.testing.assert_array_equal(result[:, -1], source[:, -1])


def test_supported_torso_does_not_override_pinned_coordinates():
    names = ['pelvis', 'spine1', 'neck']
    source = np.tile([[0., 0., 0.], [.1, .3, 0.], [0., .9, 0.]], (3, 1, 1))
    pinned = np.zeros(source.shape[:2], dtype=bool)
    pinned[1, 0] = True
    torso = TorsoCoordinates(source, names, pinned)
    assert torso.width == 0
    np.testing.assert_array_equal(torso.apply(source.copy(), np.empty((3, 0))), source)


def test_orientation_regularization_detects_yaw_shake_independent_of_body_size():
    from scipy.spatial.transform import Rotation
    names = ['left_hip', 'right_hip', 'pelvis', 'neck']
    source = np.tile([[-.1, 0., 0.], [.1, 0., 0.], [0., 0., 0.], [0., 1., 0.]], (9, 1, 1))
    yaw = np.deg2rad([0., 5., -5., 5., -5., 5., -5., 5., 0.])
    matrices = Rotation.from_euler('y', yaw[:, None]).as_matrix()
    shaking = np.einsum('fij,fkj->fki', matrices, source)
    axes = body_orientation_axes(shaking, names)
    assert np.linalg.norm(np.diff(axes, n=2, axis=0)) > .5
    np.testing.assert_allclose(body_orientation_axes(shaking * .01 + 2., names), axes, atol=1e-12)
    np.testing.assert_allclose(np.diff(body_orientation_axes(source, names), n=2, axis=0), 0.)


def test_body_axes_crossing_angle_wrap_remain_continuous():
    from scipy.spatial.transform import Rotation
    names = ['left_hip', 'right_hip', 'pelvis', 'neck']
    source = np.tile([[-.1, 0., 0.], [.1, 0., 0.], [0., 0., 0.], [0., 1., 0.]], (5, 1, 1))
    matrices = Rotation.from_euler('y', np.arange(178., 183.)[:, None], degrees=True).as_matrix()
    turning = np.einsum('fij,fkj->fki', matrices, source)
    assert np.max(abs(np.diff(body_orientation_axes(turning, names), n=2, axis=0))) < .001

def test_thruster_rotation_regression_is_rejected_and_corrected_poses_pass():
    import json
    from pathlib import Path
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg.temporal_quality import body_orientation_noise_from_payload
    payload = json.loads((Path(__file__).parent / 'fixtures/thruster_body_rotation_noise.json').read_text())
    noisy = body_orientation_noise_from_payload(payload)
    assert noisy['severe']
    assert 'postprocess_body_rotation_jitter' in bake.compute_kinematic_plausibility_metrics_from_payload(payload)['artifactReasons']
    fixed = {**payload, 'frames': [{**f, 'joints': f['repairedJoints']} for f in payload['frames']]}
    corrected = body_orientation_noise_from_payload(fixed)
    assert not corrected['severe']
    assert corrected['outputRmsDegreesAt30Hz'] < noisy['outputRmsDegreesAt30Hz'] * .3
    assert 'postprocess_body_rotation_jitter' not in bake.compute_kinematic_plausibility_metrics_from_payload(fixed)['artifactReasons']


def test_rotation_noise_check_is_world_rotation_invariant_and_requires_source():
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg.temporal_quality import body_orientation_noise, body_orientation_noise_from_payload
    names = ['left_hip', 'right_hip', 'pelvis', 'neck']
    source = np.tile([[-.1, 0., 0.], [.1, 0., 0.], [0., 0., 0.], [0., 1., 0.]], (9, 1, 1))
    matrices = Rotation.from_euler('y', np.array([0., 5., -5., 5., -5., 5., -5., 5., 0.])[:, None], degrees=True).as_matrix()
    shaking = np.einsum('fij,fkj->fki', matrices, source)
    basis = Rotation.from_euler('xyz', [.3, -.7, 1.2]).as_matrix()
    before = body_orientation_noise(shaking, names, source, 30.)
    rotated = body_orientation_noise(shaking @ basis + 2., names, source @ basis + 2., 30.)
    assert rotated['severe'] == before['severe']
    np.testing.assert_allclose(rotated['outputRmsDegreesAt30Hz'], before['outputRmsDegreesAt30Hz'])
    assert not body_orientation_noise_from_payload({'frames': [{'joints': {}}]})['available']

def test_attached_head_keeps_intentional_nod_while_torso_moves():
    from exercise_motion_pkg.temporal_quality import body_local_head_direction
    names = ['left_hip', 'right_hip', 'pelvis', 'neck', 'head']
    source = np.tile([[-.1, 0., 0.], [.1, 0., 0.], [0., 0., 0.], [0., 1., 0.], [0., 1.2, 0.]], (7, 1, 1))
    nod = np.linspace(-.3, .3, 7)
    source[:, 4] = source[:, 3] + np.column_stack([np.zeros(7), .2*np.cos(nod), .2*np.sin(nod)])
    torso = TorsoCoordinates(source, names, np.zeros(source.shape[:2], dtype=bool))
    coordinates = np.column_stack([np.linspace(0., .4, 7), np.zeros((7, 2)),
                                   np.linspace(0., .5, 7), np.linspace(0., -.3, 7), np.zeros(7)])
    result = torso.apply(source.copy(), coordinates)
    np.testing.assert_allclose(body_local_head_direction(result, names), body_local_head_direction(source, names), atol=1e-12)
    np.testing.assert_allclose(np.linalg.norm(result[:, 4]-result[:, 3], axis=1), .2)
    assert np.ptp(body_local_head_direction(result, names)[:, 2]) > .5


def test_supported_head_is_not_moved_by_torso_coordinates():
    names = ['left_hip', 'right_hip', 'pelvis', 'neck', 'head']
    source = np.tile([[-.1, 0., 0.], [.1, 0., 0.], [0., 0., 0.], [0., 1., 0.], [0., 1.2, 0.]], (3, 1, 1))
    pinned = np.zeros(source.shape[:2], dtype=bool)
    pinned[:, 4] = True
    torso = TorsoCoordinates(source, names, pinned)
    result = torso.apply(source.copy(), np.tile([.2, .1, 0., 0., .1, 0.], (3, 1)))
    np.testing.assert_array_equal(result[:, 4], source[:, 4])


def test_final_validator_rejects_retained_head_wobble():
    import json
    from pathlib import Path
    from exercise_motion_pkg.physical_validation import physical_metrics_from_payload
    payload = json.loads((Path(__file__).parent / 'fixtures/thruster_head_wobble.json').read_text())
    assert 'repair_head_articulation_distortion' in physical_metrics_from_payload(payload)['reasons']
    original = {**payload, 'frames': [{**f, 'joints': f['sourceJoints']} for f in payload['frames']]}
    assert 'repair_head_articulation_distortion' not in physical_metrics_from_payload(original)['reasons']
