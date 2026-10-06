import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.motion_placement import contact_consistent_target, root_motion_quality, register_contact_placement


def test_contacts_remove_common_drift_without_changing_articulation():
    stance = np.array([[0., 1., 0.], [-.2, 0., 0.], [.2, 0., 0.], [0., 1.5, .1]])
    truth = np.tile(stance, (60, 1, 1))
    truth[:, 0, 1] += .1*np.sin(np.arange(60)/10.)
    drift = np.column_stack([.2*np.sin(np.arange(60)), np.zeros(60), np.arange(60)*.01])
    observed = truth+drift[:, None, :]
    pinned = np.zeros(observed.shape[:2], dtype=bool)
    pinned[:, 1:3] = True
    result, shift, report = contact_consistent_target(observed, pinned, truth)
    np.testing.assert_allclose(result, truth, atol=1e-12)
    np.testing.assert_allclose(shift, -drift, atol=1e-12)
    assert report['supportedFrames'] == 60
    rotation = Rotation.from_euler('xyz', [.2, .7, -.4]).as_matrix()
    rotated, _, _ = contact_consistent_target(observed@rotation+3, pinned, truth@rotation+3)
    np.testing.assert_allclose(rotated, result@rotation+3, atol=1e-12)


def test_release_preserves_jump_and_no_contact_preserves_travel():
    target = np.zeros((48, 3, 3))
    target[:, :, 0] = np.arange(48)[:, None]*.02
    pinned = np.zeros(target.shape[:2], dtype=bool)
    unchanged, shift, _ = contact_consistent_target(target, pinned, target+10)
    np.testing.assert_array_equal(unchanged, target)
    assert not shift.any()
    target[10:38, :, 1] += (.22*np.sin(np.linspace(0, np.pi, 28)))[:, None]
    pinned[:10, 1:] = True
    pinned[38:, 1:] = True
    anchors = target+[.2, 0., -.3]
    result, _, _ = contact_consistent_target(target, pinned, anchors)
    np.testing.assert_allclose(result[:, :, 1], target[:, :, 1])
    np.testing.assert_allclose(np.diff(result[:, 0, 0]), .02)
    assert root_motion_quality(result[:, 0], 30., .8)['passed']


def test_root_continuity_rejects_teleport_but_allows_fast_travel():
    root = np.column_stack([np.arange(60)*.25, np.zeros(60), np.zeros(60)])
    assert root_motion_quality(root, 30., .8)['passed']
    root[30:] += [.3, 0., 0.]
    report = root_motion_quality(root, 30., .8)
    assert not report['passed']
    assert report['frames'] == [29, 30]
    rotation = Rotation.from_euler('xyz', [.2, .7, -.4]).as_matrix()
    assert root_motion_quality(root@rotation+5, 30., .8)['frames'] == report['frames']


def test_stance_registration_removes_placement_reset_without_inventing_contacts():
    truth = np.tile(np.array([[0., 1., 0.], [-.2, 0., 0.], [.2, 0., 0.]]), (60, 1, 1))
    truth[:, 0, 1] += .1*np.sin(np.arange(60)/10.)
    observed = truth.copy()
    observed[30:] += [.3, 0., .2]
    pinned = np.zeros(observed.shape[:2], dtype=bool)
    pinned[:29, 1:] = True
    pinned[31:, 1:] = True
    original_mask = pinned.copy()
    registered, report = register_contact_placement(observed, pinned, 0, 30., truth[:, 0])
    assert report['applied']
    assert root_motion_quality(registered[:, 0], 30., .8)['passed']
    np.testing.assert_array_equal(pinned, original_mask)
    np.testing.assert_allclose(registered-registered[:, :1], observed-observed[:, :1], atol=1e-12)
    # A global coordinate origin remains arbitrary; motion must match.
    np.testing.assert_allclose(np.diff(registered[:, 0], axis=0), np.diff(truth[:, 0], axis=0), atol=.003)


@pytest.mark.parametrize('count,release,landing,reset', [(48, 10, 38, 20), (540, 110, 430, 230)])
def test_registration_preserves_flight_with_an_independent_root_reference(count, release, landing, reset):
    truth = np.tile(np.array([[0., 1., 0.], [-.2, 0., 0.], [.2, 0., 0.]]), (count, 1, 1))
    truth[release:landing, :, 1] += (.22*np.sin(np.linspace(0., np.pi, landing-release)))[:, None]
    observed = truth.copy()
    observed[reset:] += [.3, 0., .2]
    pinned = np.zeros(observed.shape[:2], dtype=bool)
    pinned[:release, 1:] = True
    pinned[landing:, 1:] = True
    registered, report = register_contact_placement(observed, pinned, 0, 30., truth[:, 0])
    assert report['applied']
    np.testing.assert_allclose(registered[:, 0, 1], truth[:, 0, 1], atol=1e-7)
    assert np.ptp(registered[:, 0, 1]) > .21
    np.testing.assert_allclose(registered-registered[:, :1], observed-observed[:, :1], atol=1e-12)


def test_already_registered_stance_is_an_exact_noop():
    points = np.tile(np.array([[0., 1., 0.], [-.2, 0., 0.], [.2, 0., 0.]]), (30, 1, 1))
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, 1:] = True
    registered, report = register_contact_placement(points, pinned, 0, 30., points[:, 0])
    np.testing.assert_array_equal(registered, points)
    assert report['reason'] == 'placement_already_coherent'


def test_observed_floor_anchors_remove_vertical_reset_and_preserve_flight():
    count, release, landing = 90, 25, 65
    truth = np.tile(np.array([[0., 1., 0.], [-.2, 0., 0.], [.2, 0., 0.]]), (count, 1, 1))
    truth[release:landing, :, 1] += (.22*np.sin(np.linspace(0., np.pi, landing-release)))[:, None]
    observed = truth.copy()
    observed[:45, :, 1] += .35
    observed[45:, :, 1] -= .2
    pinned = np.zeros(observed.shape[:2], dtype=bool)
    pinned[:release, 1:] = True
    pinned[landing:, 1:] = True
    registered, report = register_contact_placement(observed, pinned, 0, 30., truth[:, 0],
                                                     ground_contacts=pinned, floor=0.)
    assert report['observedGroundEpisodes'] == 4
    np.testing.assert_allclose(registered[:, 0], truth[:, 0], atol=.0001)
    np.testing.assert_allclose(registered-registered[:, :1], observed-observed[:, :1], atol=1e-12)
    assert np.max(registered[release:landing, 1:, 1]) > .21


def test_contact_height_gauge_preserves_articulation_and_relative_support_heights():
    from exercise_motion_pkg.motion_placement import align_registered_contacts_above_floor

    points = np.tile(np.array([[0., 1., 0.], [-.2, -.03, 0.], [.2, .2, 0.]]), (8, 1, 1))
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, 1:] = True
    result, shift = align_registered_contacts_above_floor(points, pinned, [1, 2], 0.)
    assert shift == .03
    np.testing.assert_allclose(result[:, 1, 1], 0.)
    np.testing.assert_allclose(result[:, 2, 1], .23)
    np.testing.assert_allclose(result-result[:, :1], points-points[:, :1])
    result, shift = align_registered_contacts_above_floor(points, np.zeros_like(pinned), [1, 2], 0.)
    assert shift == 0.
    np.testing.assert_array_equal(result, points)
