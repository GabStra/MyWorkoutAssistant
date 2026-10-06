import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.rig_interpolation import hermite_samples


def test_boundary_velocity_check_distinguishes_curvature_from_a_real_jump():
    from exercise_motion_pkg.rig_interpolation import frame_boundary_velocity_jump
    knots = np.array([0.])
    smooth = lambda cursors: (1e4*cursors**2)[:, None, None]
    corner = lambda cursors: np.abs(cursors)[:, None, None]
    assert frame_boundary_velocity_jump(smooth, knots, 30.) < 1e-6
    assert frame_boundary_velocity_jump(corner, knots, 30.) > 59.9


def sample(track, cursors, quaternion=False, wrap=False):
    cursors = np.mod(cursors, len(track)) if wrap else np.clip(cursors, 0, len(track)-1)
    first = np.floor(cursors).astype(int)
    last = (first+1) % len(track) if wrap else np.minimum(first+1, len(track)-1)
    return hermite_samples(track, first, last, cursors-first, wrap=wrap, quaternion=quaternion)


def test_continuous_velocity_including_loop_seam_and_quaternion_sign_change():
    angles = np.array([170, 176, 183, 189, 184, 180, 174, 170])
    track = Rotation.from_euler('z', angles[:, None], degrees=True).as_quat()
    track[2::3] *= -1
    knots = np.arange(len(track))
    e = 1e-5
    # Matrix coordinates avoid quaternion sign ambiguity at comparison knots.
    poses = [Rotation.from_quat(sample(track, knots+d, quaternion=True, wrap=True)).as_matrix() for d in [-e, 0, e]]
    np.testing.assert_allclose((poses[2]-poses[1])/e, (poses[1]-poses[0])/e, atol=3e-5)
    np.testing.assert_allclose(poses[1], Rotation.from_quat(track).as_matrix(), atol=1e-12)


def test_holds_and_reversals_do_not_overshoot_scalar_motion():
    track = np.array([0, 0, .01, .08, .3, .3, .3, .15, 0, 0])[:, None]
    cursors = np.arange(0, len(track)-1, .01)
    result = sample(track, cursors)[:, 0]
    first = np.floor(cursors).astype(int)
    assert np.all(result >= np.minimum(track[first, 0], track[first+1, 0])-1e-12)
    assert np.all(result <= np.maximum(track[first, 0], track[first+1, 0])+1e-12)
    assert np.max(np.abs(result[(cursors>=4)&(cursors<=6)]-.3)) < 1e-12


def test_tiny_keyframe_change_cannot_jump_path_at_perpendicular_motion():
    track = np.array([[-1., 0., 0.], [0., 0., 0.], [0., 1., 0.], [0., 2., 0.]])
    left, right = track.copy(), track.copy()
    left[2, 0], right[2, 0] = -1e-8, 1e-8
    cursors = np.linspace(0., 3., 61)
    np.testing.assert_allclose(sample(left, cursors), sample(right, cursors), atol=3e-8)


def test_rotating_the_camera_rotates_the_same_continuous_path():
    rotation = Rotation.from_euler('xyz', [23, -71, 42], degrees=True)
    track = Rotation.from_euler('xyz', [[0, 0, 0], [10, 20, 3], [20, 30, 8], [30, 25, 10]], degrees=True)
    cursors = np.linspace(0, 3, 35)
    expected = rotation*Rotation.from_quat(sample(track.as_quat(), cursors, quaternion=True))
    actual = Rotation.from_quat(sample((rotation*track).as_quat(), cursors, quaternion=True))
    np.testing.assert_allclose(actual.as_matrix(), expected.as_matrix(), atol=1e-12)


def test_review_video_samples_fractional_poses_with_matching_duration():
    from exercise_motion_pkg.bake_and_rank import dense_loop_review_video_frame_indices, parse_review_video_fps
    for cyclic in (True, False):
        payload = {'frameCount': 90, 'fps': 30., 'loop': {'enabled': cyclic},
                   'fixedRig': {'interpolation': 'limited_quaternion_hermite_v1'}}
        cursors = dense_loop_review_video_frame_indices(payload)
        assert len(cursors) <= 180
        assert any(cursor != int(cursor) for cursor in cursors)
        fps = parse_review_video_fps(payload, frame_count=len(cursors))
        duration = len(cursors)/fps if cyclic else (len(cursors)-1)/fps
        np.testing.assert_allclose(duration, (90 if cyclic else 89)/30.)
        if cyclic:
            assert 89 < cursors[-1] < 90
        else:
            assert cursors[-1] == 89


def test_fractional_review_timestamps_retain_source_time_origin():
    from exercise_motion_pkg.bake_and_rank import frame_timestamps_for_indices
    payload = {'fps': 30., 'frames': [{'sourceTimeSec': 4.+i/30.} for i in range(3)]}
    actual = frame_timestamps_for_indices(payload, [0., .5, 1., 1.5, 2.5])
    np.testing.assert_allclose(actual, 4.+np.array([0., .5, 1., 1.5, 2.5])/30.)
