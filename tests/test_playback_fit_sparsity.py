import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.optimize._numdiff import approx_derivative

from exercise_motion_pkg import controlled_motion as motion


def stance(count):
    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile(np.array(list(fixture['joints'].values())), (count, 1, 1))
    return names, points


@pytest.mark.parametrize('root_drift', [False, True])
def test_seam_repairs_joint_planted_only_inside_repetition(monkeypatch, root_drift):
    names, points = stance(12)
    rig = motion.FixedRig(points, names)
    coordinates = rig.initial.copy()
    coordinates[-1, rig.slots[names.index('right_ankle')]] += .06
    if root_drift:
        coordinates[:, 0] += np.linspace(0., .01, len(coordinates))
    pinned = np.zeros((12, len(names)), dtype=bool)
    pinned[4:8, names.index('right_foot')] = True
    solve = motion.least_squares
    checked = []

    def inspect(residual, initial, *, jac, **kwargs):
        # A perfectly linear stance ties the incoming/outgoing max in the seam
        # residual. Check derivatives away from that nondifferentiable tie.
        probe = initial + np.random.default_rng(9).normal(0., .001, len(initial))
        numerical = approx_derivative(residual, probe, method='3-point', abs_step=1e-7)
        # Contact meters and normalized settling speed have very different row
        # scales. Compare relative to each gradient's size, including its near-
        # zero components where forward differences incur cancellation error.
        row_scale = np.maximum(1., np.max(np.abs(numerical), axis=1))[:, None]
        np.testing.assert_allclose(jac(probe) / row_scale, numerical / row_scale,
                                   atol=2e-6, rtol=1e-3)
        checked.append(True)
        return SimpleNamespace(x=initial)

    monkeypatch.setattr(motion, 'least_squares', inspect)
    settling_weights = np.ones((len(points) - 1, len(names), 1))
    # Stage B receives a body-valid candidate. Preserve its existing settling
    # budget, as the caller does, rather than ask seam repair to also eliminate
    # a separately failing whole-clip settling trajectory.
    settling_limit = max(.003, 1.1 * motion.weighted_settling_speed(
        rig.decode(coordinates), names, 30., settling_weights))
    motion.project_loop_seam_coordinates(
        coordinates, rig, pinned, scale=motion.body_scale(points, names), fps=30.,
        settling_weights=settling_weights, settling_limit=settling_limit)
    assert checked
    # The independent numerical audit must not consume the production solver's
    # wall-clock budget. Run optimization with its own normal deadline.
    monkeypatch.setattr(motion, 'least_squares', solve)
    fitted = motion.project_loop_seam_coordinates(
        coordinates, rig, pinned, scale=motion.body_scale(points, names), fps=30.,
        settling_weights=settling_weights, settling_limit=settling_limit)
    assert motion.seam_playback_over_limit_score(
        rig.decode(fitted), scale=motion.body_scale(points, names), fps=30.) <= 1.
    np.testing.assert_array_equal(fitted[4:8], coordinates[4:8])
    assert motion.weighted_settling_speed(rig.decode(fitted), names, 30., settling_weights) <= settling_limit


def test_free_temporal_smoothing_uses_contact_at_each_frame():
    names, points = stance(16)
    rig = motion.FixedRig(points, names)
    coordinates = rig.initial.copy()
    slot = rig.slots[names.index('right_ankle')]
    coordinates[3, slot] += .06
    pinned = np.zeros((16, len(names)), dtype=bool)
    pinned[9:, names.index('right_foot')] = True
    fitted = motion.temporal_free_coordinate_smooth(
        coordinates, rig, pinned, cyclic=False)
    assert abs(fitted[3, slot] - rig.initial[3, slot]) < .06
    np.testing.assert_array_equal(fitted[9:, slot:slot + 3], coordinates[9:, slot:slot + 3])


def test_supported_working_reference_cannot_hide_introduced_spike():
    names, source = stance(9)
    projected = source.copy()
    projected[4, names.index('right_ankle'), 0] += .08
    result = motion.relative_motion_quality(
        projected, projected, names, 30., spike_reference=source)
    assert not result['relativeJointShake']
    assert result['introducedSpikes']['severe']


def test_retained_touchdown_spike_repairs_without_losing_contacts():
    from time import monotonic
    fixture = json.loads((Path(__file__).parent / 'fixtures/contact_touchdown_spike.json').read_text())
    names = fixture['jointNames']
    points, source = np.asarray(fixture['targets']), np.asarray(fixture['source'])
    rig = motion.FixedRig(points, names)
    rig.offsets = np.asarray(fixture['offsets'])
    coordinates = np.asarray(fixture['coordinates'])
    pinned = np.asarray(fixture['pinned'], dtype=bool)
    assert motion.relative_motion_quality(
        points, points, names, fixture['fps'], spike_reference=source)['introducedSpikes']['severe']
    fitted = motion.project_introduced_spikes_coordinates(
        coordinates, rig, pinned, points, source, fps=fixture['fps'],
        floor=fixture['floor'], deadline=monotonic() + 8.)
    assert not motion.relative_motion_quality(
        rig.decode(fitted), points, names, fixture['fps'], spike_reference=source)['introducedSpikes']['severe']
    assert motion._playback_contact_sample_error(fitted, rig, pinned, points) < motion.PLAYBACK_CONTACT_LIMIT_METERS
    assert motion._playback_floor_penetration(fitted, rig, floor=fixture['floor']) <= motion.PLAYBACK_FLOOR_LIMIT_METERS


def test_contact_transition_repairs_through_fixed_hip_sockets():
    from time import monotonic
    fixture = json.loads((Path(__file__).parent / 'fixtures/playback_contact_transition.json').read_text())
    names = fixture['jointNames']
    targets = np.asarray(fixture['targets'])
    rig = motion.FixedRig(targets, names)
    rig.offsets = np.asarray(fixture['offsets'])
    coordinates = np.asarray(fixture['coordinates'])
    pinned = np.asarray(fixture['pinned'], dtype=bool)
    floor = fixture['floor']
    assert motion._playback_contact_sample_error(coordinates, rig, pinned, targets) > .002
    fitted = motion.project_interval_playback_plants(
        coordinates, rig, pinned, targets, floor=floor, max_nfev=8, deadline=monotonic() + 8.)
    assert motion._playback_contact_sample_error(fitted, rig, pinned, targets) < motion.PLAYBACK_CONTACT_LIMIT_METERS
    assert motion._playback_floor_penetration(fitted, rig, floor=floor) <= motion.PLAYBACK_FLOOR_LIMIT_METERS
    assert np.max(np.linalg.norm((rig.decode(fitted) - targets)[pinned], axis=-1)) < motion.PLAYBACK_CONTACT_LIMIT_METERS


@pytest.mark.parametrize('cyclic', [False, True])
def test_playback_sparse_dependencies_cover_numerical_jacobian(monkeypatch, cyclic):
    names, points = stance(8)
    rig = motion.FixedRig(points, names)
    coordinates = rig.initial.copy()
    coordinates += np.random.default_rng(17).normal(0., .01, coordinates.shape)
    pinned = np.zeros((8, len(names)), dtype=bool)
    pinned[:, names.index('left_foot')] = True
    pinned[2:6, names.index('right_foot')] = True
    chain = motion._distal_plant_chain_slots(rig, pinned, depth=1)
    checked = []

    def inspect(residual, initial, *, jac_sparsity, **kwargs):
        numerical = approx_derivative(residual, initial, method='3-point', abs_step=1e-5)
        declared = jac_sparsity.toarray().astype(bool)
        assert declared.shape == numerical.shape
        assert not np.any((np.abs(numerical) > 1e-5) & ~declared)
        assert declared.mean() < .6
        checked.append(True)
        return SimpleNamespace(x=initial)

    monkeypatch.setattr(motion, 'least_squares', inspect)
    motion._trf_playback_run_coupled(
        coordinates, [0, 4, 7] if cyclic else [0, 4, 6], rig, pinned,
        points, chain, cyclic=cyclic, floor=float(points[0, :, 1].min()) + .02,
        spike_reference=points)
    assert checked


def test_sparse_playback_fit_preserves_contact_accuracy_with_fewer_evaluations(monkeypatch):
    names, points = stance(24)
    rig = motion.FixedRig(points, names)
    coordinates = rig.initial.copy()
    coordinates[:, 0] += .003 * np.sin(np.arange(24) * .3)
    pinned = np.zeros((24, len(names)), dtype=bool)
    pinned[:, names.index('left_foot')] = True
    solve = motion.least_squares
    counts = []
    errors = []
    for sparse in (False, True):
        calls = [0]

        def counted(residual, initial, **kwargs):
            if not sparse:
                kwargs.pop('jac_sparsity')
            def evaluate(values):
                calls[0] += 1
                return residual(values)
            return solve(evaluate, initial, **kwargs)

        monkeypatch.setattr(motion, 'least_squares', counted)
        fitted = motion._trf_playback_run_coupled(
            coordinates, range(23), rig, pinned, points, [], max_nfev=8)
        counts.append(calls[0])
        errors.append(motion._playback_contact_sample_error(fitted, rig, pinned, points))
    assert max(errors) < motion.PLAYBACK_CONTACT_LIMIT_METERS
    assert counts[1] < counts[0] / 2


@pytest.mark.parametrize('remaining_error', [.0001, .0015])
def test_playback_deadline_retains_progress_only_when_contact_gates_pass(monkeypatch, remaining_error):
    names, points = stance(8)
    rig = motion.FixedRig(points, names)
    points = rig.decode(rig.initial)
    coordinates = rig.initial.copy()
    coordinates[:, 0] += .003
    pinned = np.zeros((8, len(names)), dtype=bool)
    pinned[:, names.index('left_foot')] = True
    now = [0.]
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])

    def interrupted_solve(residual, initial, **kwargs):
        residual(initial)
        improved = initial.reshape(-1, 3).copy()
        improved[:, 0] -= .003 - remaining_error
        residual(improved.ravel())
        now[0] = 2.
        residual(improved.ravel())  # The real residual enforces its deadline.
        raise AssertionError('solver continued past deadline')

    monkeypatch.setattr(motion, 'least_squares', interrupted_solve)
    fitted = motion._trf_playback_run_coupled(
        coordinates, range(7), rig, pinned, points, [], deadline=1.)
    error = motion._playback_contact_sample_error(fitted, rig, pinned, points)
    if remaining_error < motion.PLAYBACK_CONTACT_LIMIT_METERS:
        assert error == pytest.approx(remaining_error, abs=1e-8)
    else:
        np.testing.assert_array_equal(fitted, coordinates)


@pytest.mark.parametrize('prior_frame_count', [12, 24])
def test_cycle_support_cache_cannot_replace_selected_interval_articulation(monkeypatch, prior_frame_count):
    from exercise_motion_pkg import support_geometry

    names, points = stance(12)
    payload = {'fps': 30., 'jointNames': names,
               'frames': [{'timeSec': i / 30., 'joints': dict(zip(names, frame.tolist()))}
                          for i, frame in enumerate(points)],
               'sourceFootSupportEvidence': {'bodySupport': {
                   'required': True, 'status': 'confirmed',
                   'stationaryJoints': ['left_foot', 'right_foot'],
                   'coplanarGroups': [{'joints': ['left_foot', 'right_foot'], 'normal': [0., 1., 0.]}]}}}
    prior_rig = motion.FixedRig(np.tile(points[:1], (prior_frame_count, 1, 1)), names)
    prior_rig.initial[:, prior_rig.slots[names.index('left_shoulder')]] += .7
    captured = []

    class ReachedSupportProjection(Exception):
        pass

    def capture(coordinates, rig, *args, **kwargs):
        decoded = rig.decode(coordinates)
        captured.append(decoded - decoded[:, rig.root:rig.root + 1])
        raise ReachedSupportProjection

    monkeypatch.setattr(support_geometry, 'calibrate_support_pose',
                        lambda rig, points, evidence, **kwargs: (np.median(points, axis=0), {'passed': True}))
    monkeypatch.setattr(motion, 'project_contact_root_translation', capture)
    for cache in (None, {'supportInitializedCoordinates': prior_rig.initial}):
        with pytest.raises(ReachedSupportProjection):
            motion._fit_controlled_motion(payload, timeout_seconds=10., shared_support=cache)
    np.testing.assert_allclose(captured[0], captured[1], atol=1e-10)
