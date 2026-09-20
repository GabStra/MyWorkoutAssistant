import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.controlled_motion import FixedRig, body_relative_points, controlled_target, fit_controlled_motion


def stance(count=45):
    fixture=json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names=list(fixture['joints'])
    points=np.tile(np.array([fixture['joints'][n] for n in names]),(count,1,1))
    return names,points


def payload(names,points,fps=30.):
    return {'fps':fps,'jointNames':names,'frames':[{'timeSec':i/fps,'joints':dict(zip(names,p.tolist()))}
                                                for i,p in enumerate(points)]}


def test_velocity_repair_checks_grip_after_smoothing_and_skips_valid_projection(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, rig_interpolation
    from exercise_motion_pkg.equipment_constraints import calibrated_grip_constraint, validate_grip
    names, points = stance(7)
    rig = FixedRig(points, names)
    original = rig.initial.copy()
    equipment = calibrated_grip_constraint({'equipmentConstraints': {'handRelationship': 'rigid_pair'}},
                                           rig.decode(original), names)
    changed = original.copy()
    slot = rig.slots[names.index('right_elbow')]
    changed[:, slot:slot+3] += [.8, .5, .4]
    assert not validate_grip(rig.decode(changed), names, equipment)['passed']
    calls = []
    monkeypatch.setattr(motion, 'project_playback_neck_clearance', lambda coords, *a, **k: coords)
    monkeypatch.setattr(motion, 'temporal_coordinate_smooth', lambda *a, **k: changed.copy())
    def restore(values, *args, **kwargs):
        calls.append('grip')
        return original.copy()
    monkeypatch.setattr(motion, 'project_rigid_pair_grip_coordinates', restore)
    monkeypatch.setattr(motion, 'project_playback_rigid_pair_grip', lambda coords, *a, **k: coords)
    jumps = iter([1., 0., 0.])
    monkeypatch.setattr(rig_interpolation, 'frame_boundary_velocity_jump', lambda *a: next(jumps))
    repaired = motion.repair_playback_velocity_continuity(original, rig, None, None,
                                                        names=names, equipment=equipment)
    assert calls == ['grip']
    assert validate_grip(rig.decode(repaired), names, equipment)['passed']
    monkeypatch.setattr(rig_interpolation, 'frame_boundary_velocity_jump', lambda *a: 0.)
    motion.repair_playback_velocity_continuity(original, rig, None, None, names=names, equipment=equipment)
    assert calls == ['grip']


def test_cyclic_fit_evaluates_all_seam_residuals_with_matching_dependencies(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    calls = []
    socket_errors = []
    original_structure = motion.anatomical_structure_residuals
    def record_structure(values, *args, **kwargs):
        errors, labels = original_structure(values, *args, **kwargs)
        socket_errors.append((len(values), float(np.max(
            errors[:, labels.index('anatomy_socket_alignment:neck')]))))
        return errors, labels
    monkeypatch.setattr(motion, 'anatomical_structure_residuals', record_structure)
    neck_slot = FixedRig(points, names).slots[names.index('neck')]
    def solve(residual, initial, pattern, max_evaluations):
        errors = residual(initial)
        assert pattern.shape == (len(errors), len(initial))
        assert np.isfinite(errors).all()
        probe = initial.reshape(len(points), -1).copy()
        probe[:, neck_slot:neck_slot + 3] = [0., 0., .3]
        socket_errors.clear()
        probe_errors = residual(probe.ravel())
        assert np.isfinite(probe_errors).all()
        # Both keyframes and interpolated samples must expose the underlying
        # socket violation, even though playback itself clamps that geometry.
        assert any(count == len(points) and error > .1 for count, error in socket_errors)
        assert any(count > len(points) and error > .1 for count, error in socket_errors)
        calls.append(True)
        return SimpleNamespace(x=initial, nfev=1, status=0)
    monkeypatch.setattr(motion, 'solve_trajectory', solve)
    motion.fit_controlled_motion(current, timeout_seconds=10.)
    assert calls


def test_slow_solver_block_hands_unused_budget_to_polish(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    now = [0.]
    calls = []
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    def slow_block(residual, initial, pattern, max_evaluations):
        calls.append(now[0])
        residual(initial)
        now[0] += 40.
        return SimpleNamespace(x=initial, nfev=5, status=0)
    monkeypatch.setattr(motion, 'solve_trajectory', slow_block)
    _, report = motion._fit_controlled_motion(current, timeout_seconds=60.)
    assert calls == [0.]
    deferred = report['deferredOptimizerBlock']
    assert deferred['minimumUpdateSeconds'] > deferred['remainingSolveSeconds']
    assert report['optimizerTermination'] == 'solve_phase_budget'
    assert 40. + report['polishReserveRemainingSeconds'] < report['polishUntilSeconds'] <= 60.


def test_temporal_reference_is_unchanged_by_preview_noise(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    names, reference = stance(12)
    reference[:, names.index('head'), 0] += .0002*np.sin(np.arange(12))
    monkeypatch.setattr(motion, 'solve_trajectory', lambda residual, initial, pattern, max_evaluations:
                        SimpleNamespace(x=initial, nfev=1, status=0))
    reports = []
    for noise in (.0001, .002):
        points = reference.copy()
        points[:, names.index('head'), 0] += noise*(-1.)**np.arange(12)
        current = payload(names, points)
        for frame, source in zip(current['frames'], reference):
            frame['controlledArticulationReferenceJoints'] = dict(zip(names, source.tolist()))
        _, report = fit_controlled_motion(current, timeout_seconds=10.)
        assert report['temporalReference'] == 'source_articulation_before_repairs'
        assert report['settlingReference'] == 'source_articulation_before_repairs'
        reports.append(report)
    expected = float(np.sqrt(np.mean(np.diff(reference, n=3, axis=0)**2)))
    assert reports[0]['jerkBefore'] == reports[1]['jerkBefore'] == expected
    assert reports[0]['settlingSpeedBefore'] == reports[1]['settlingSpeedBefore']


def test_fit_commits_guarded_initializer_pose_before_optimizing(monkeypatch):
    import pytest
    from exercise_motion_pkg import anatomical_repair, controlled_motion as motion

    names, points = stance(12)
    verification_rig = FixedRig(points, names)
    guarded_poses = []
    def initialize(rig, observed, **kwargs):
        slot = rig.slots[names.index('neck')]
        rig.initial[:, slot + 2] += .8
        guarded = rig.decode(rig.initial)
        assert np.max(np.abs(guarded - rig.decode(rig.initial, project_socket=False))) > .01
        guarded_poses.append(guarded)
        return guarded, {'passed': True, 'applied': True, 'sourceViolations': []}
    monkeypatch.setattr(anatomical_repair, 'repair_rig_anatomy', initialize)
    class Captured(Exception):
        pass
    def inspect_initial(residual, initial, pattern, max_evaluations):
        coordinates = initial.reshape(len(points), -1)
        guarded = verification_rig.decode(coordinates)
        unguarded = verification_rig.decode(coordinates, project_socket=False)
        np.testing.assert_allclose(unguarded, guarded, atol=1e-12)
        # Root placement may change, but canonicalization preserves articulation.
        np.testing.assert_allclose(guarded - guarded[:, :1],
                                   guarded_poses[0] - guarded_poses[0][:, :1], atol=1e-12)
        raise Captured()
    monkeypatch.setattr(motion, 'solve_trajectory', inspect_initial)
    with pytest.raises(Captured):
        motion._fit_controlled_motion(payload(names, points), timeout_seconds=10.)


def test_supported_settling_baseline_uses_supported_reference_not_source():
    from exercise_motion_pkg.controlled_motion import (
        controlled_target, settling_hold_basis, weighted_settling_speed,
    )
    names, source = stance(24)
    supported = source.copy()
    # Intentional support rewrite with extra hold-interval motion.
    supported[:, :, 1] += .04
    t = np.linspace(0., 1., 24)
    quiet = (t > .3) & (t < .7)
    supported[quiet, names.index('left_wrist'), 0] += .015 * np.sin(np.linspace(0., np.pi, quiet.sum()))
    assert settling_hold_basis(source, supported, {'required': True}) is supported
    assert settling_hold_basis(source, supported, {}) is source
    assert float(np.sqrt(np.mean(np.diff(supported, n=3, axis=0)**2))) >= float(
        np.sqrt(np.mean(np.diff(source, n=3, axis=0)**2)))
    source_holds = controlled_target(source, names, 30.)[1]
    supported_holds = controlled_target(supported, names, 30.)[1]
    source_weights = np.minimum(source_holds[1:], source_holds[:-1])[:, :, None]
    supported_weights = np.minimum(supported_holds[1:], supported_holds[:-1])[:, :, None]
    source_limit = max(weighted_settling_speed(source, names, 30., source_weights) * 1.1, .003)
    supported_speed = weighted_settling_speed(supported, names, 30., supported_weights)
    mismatched = weighted_settling_speed(supported, names, 30., source_weights)
    # Pre-support quiet holds + post-support motion is the unreachable baseline.
    assert mismatched > source_limit
    assert supported_speed <= max(supported_speed * 1.1, .003)


def test_supported_joint_range_uses_articulation_metric_and_fit_residual(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg.controlled_motion import support_joint_range_preserved
    from exercise_motion_pkg.support_geometry import moving_support_articulations
    # Bench Dips signature: positional head under-range with articulations still OK.
    assert support_joint_range_preserved({'left_shoulder': 0.878})
    assert not support_joint_range_preserved({'left_elbow': 0.80, 'right_elbow': 0.819})
    names, points = stance(12)
    # Free-arm angular excursion that survives feet-only support constraints.
    theta = np.deg2rad(np.linspace(-40., 50., 12))
    for side in ('left', 'right'):
        elbow = names.index(f'{side}_elbow')
        wrist = names.index(f'{side}_wrist')
        shoulder = names.index(f'{side}_shoulder')
        points[:, elbow] = points[:, shoulder] + np.c_[np.cos(theta), np.sin(theta), np.zeros(12)] * .28
        points[:, wrist] = points[:, elbow] + [0., -.22, 0.]
    rig = FixedRig(points, names)
    points = rig.decode(rig.initial)
    feet = [f'{side}_{part}' for side in ('left', 'right') for part in ('ankle', 'foot')]
    floor = float(points[0, names.index('left_foot'), 1])
    current = payload(names, points)
    current['sourceFootSupportEvidence'] = {
        'bodySupport': {
            'required': True, 'status': 'confirmed', 'stationaryJoints': feet,
            'coplanarGroups': [{'joints': feet, 'normal': [0., 1., 0.],
                               'planeOffsetMeters': floor}],
        }}
    tracks = moving_support_articulations(
        points, names, current['sourceFootSupportEvidence']['bodySupport'])
    assert tracks, 'fixture needs moving free-chain articulations'
    residual_widths = []

    def solve(residual, initial, pattern, max_evaluations):
        errors = residual(initial)
        assert pattern.shape == (len(errors), len(initial))
        assert np.isfinite(errors).all()
        residual_widths.append(len(errors))
        n_tracks = len(tracks)
        assert len(errors) >= n_tracks
        # Soft floor is .92 of source excursion; identity must clear it with margin.
        assert np.all(errors[-n_tracks:] < 1.), errors[-n_tracks:]
        return SimpleNamespace(x=initial, nfev=1, status=0)

    monkeypatch.setattr(motion, 'solve_trajectory', solve)
    _, report = motion.fit_controlled_motion(current, timeout_seconds=45.)
    assert residual_widths and residual_widths[0] > 0
    assert 'supportArticulationRangeRatios' in report, report
    assert len(report['supportArticulationRangeRatios']) == len(tracks)
    assert report['checks']['jointRange'], report


def test_project_contact_root_translation_clears_uniform_plant_offset():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, project_contact_root_translation)
    names, points = stance(8)
    rig = FixedRig(points, names)
    coords = rig.initial.copy()
    foot = names.index('left_foot')
    pinned = np.zeros((len(points), len(names)), dtype=bool)
    pinned[:, foot] = True
    targets = points.copy()
    # Decode offset: shift world targets up so contacts need +2mm root Y.
    targets[:, foot, 1] += 0.002
    projected = project_contact_root_translation(coords, rig, pinned, targets)
    result = FixedRig(points, names)
    result.initial[:] = projected
    decoded = result.decode(projected)
    err = float(np.max(np.linalg.norm((decoded - targets)[pinned], axis=-1)))
    assert err < 1e-6, err


def test_supported_geometry_ready_skips_when_plants_and_grip_hold():
    from exercise_motion_pkg.controlled_motion import (
        supported_geometry_ready_for_skip_soft_solve)
    names, points = stance(8)
    equipment = {'handRelationship': 'none'}
    payload = {'sourceFootSupportEvidence': {'bodySupport': {'required': False}}}
    assert supported_geometry_ready_for_skip_soft_solve(
        anchored=True, playback_anchored=False, floor_clear=True,
        points=points, names=names, equipment=equipment, payload=payload,
        support_strategy='plant_projection')
    assert not supported_geometry_ready_for_skip_soft_solve(
        anchored=True, playback_anchored=True, floor_clear=True,
        points=points, names=names, equipment=equipment, payload=payload,
        support_strategy='supported_motion_ls')
    assert not supported_geometry_ready_for_skip_soft_solve(
        anchored=False, playback_anchored=True, floor_clear=True,
        points=points, names=names, equipment=equipment, payload=payload,
        support_strategy='plant_projection')
    payload.update(fps=30., loop={'enabled': True})
    stationary = np.repeat(points[:1], len(points), axis=0)
    assert supported_geometry_ready_for_skip_soft_solve(
        anchored=True, playback_anchored=True, floor_clear=True,
        points=stationary, names=names, equipment=equipment, payload=payload,
        support_strategy='plant_projection')
    stationary[-1, names.index('left_hand'), 0] += .03
    assert not supported_geometry_ready_for_skip_soft_solve(
        anchored=True, playback_anchored=True, floor_clear=True,
        points=stationary, names=names, equipment=equipment, payload=payload,
        support_strategy='plant_projection')


def test_temporal_free_smooth_leaves_plant_chain_rotations():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, temporal_free_coordinate_smooth, _plant_chain_slots)
    names, points = stance(16)
    points = points.copy()
    # High-frequency free-chain noise on the chest slot.
    rig = FixedRig(points, names)
    coords = rig.initial.copy()
    chest = names.index('chest') if 'chest' in names else names.index('spine3')
    hand = names.index('left_hand')
    coords[:, rig.slots[chest]:rig.slots[chest] + 3] += (
        0.02 * np.sin(np.linspace(0, 12 * np.pi, len(coords)))[:, None])
    coords[:, rig.slots[hand]:rig.slots[hand] + 3] += (
        0.03 * np.sin(np.linspace(0, 18 * np.pi, len(coords)))[:, None])
    pinned = np.zeros((len(coords), len(names)), dtype=bool)
    for foot in ('left_foot', 'right_foot'):
        pinned[:, names.index(foot)] = True
    before = coords.copy()
    after = temporal_free_coordinate_smooth(
        coords, rig, pinned, cyclic=True, sigma=1.5)
    plant_chain = set(_plant_chain_slots(rig, pinned))
    for joint in plant_chain:
        start = rig.slots[joint]
        assert np.allclose(after[:, start:start + 3], before[:, start:start + 3])
    assert not np.allclose(
        after[:, rig.slots[hand]:rig.slots[hand] + 3],
        before[:, rig.slots[hand]:rig.slots[hand] + 3])


def test_polish_free_temporal_restores_physical_after_torso_smooth():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, polish_free_temporal_preserving_anatomy)
    from exercise_motion_pkg.physical_validation import validate_physical_motion
    names, points = stance(24)
    points = points.copy()
    # Inject high-frequency spine noise that free-smooth would otherwise leave
    # as anatomy_torso_bend until repair runs.
    spine = names.index('spine1')
    points[:, spine] += (
        0.01 * np.sin(np.linspace(0, 20 * np.pi, len(points)))[:, None]
        * np.array([1., 0., 0.]))
    rig = FixedRig(points, names)
    pinned = np.zeros((len(points), len(names)), dtype=bool)
    for foot in ('left_foot', 'right_foot'):
        if foot in names:
            pinned[:, names.index(foot)] = True
    targets = rig.decode(rig.initial)
    polished = polish_free_temporal_preserving_anatomy(
        rig.initial, rig, pinned, targets, cyclic=True, sigma=1.25)
    world = rig.decode(polished)
    assert validate_physical_motion(world, names, fps=30.)['passed']


def test_temporal_anatomy_polish_preserves_caller_deadline(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg import anatomical_repair

    names, points = stance(4)
    rig = motion.FixedRig(points, names)
    pinned = np.ones((len(points), len(names)), dtype=bool)
    targets = rig.decode(rig.initial)
    deadlines = []
    monkeypatch.setattr(motion, 'monotonic', lambda: 10.)
    monkeypatch.setattr(motion, 'temporal_free_coordinate_smooth',
                        lambda coordinates, *args, **kwargs: coordinates + 0.001)
    monkeypatch.setattr(anatomical_repair, 'repair_rig_anatomy',
                        lambda *args, **kwargs: (None, {'passed': True}))
    monkeypatch.setattr(motion, '_playback_contact_sample_error',
                        lambda *args, **kwargs: 1.)
    monkeypatch.setattr(motion, '_playback_failing_intervals',
                        lambda *args, **kwargs: [0])

    def capture_deadline(coordinates, *args, deadline=None, **kwargs):
        deadlines.append((deadline, kwargs))
        return coordinates

    for name in ('project_contact_plant_coordinates',
                 'project_interval_playback_plants',
                 'repair_playback_velocity_continuity'):
        monkeypatch.setattr(motion, name, capture_deadline)
    motion.polish_free_temporal_preserving_anatomy(
        rig.initial, rig, pinned, targets, cyclic=True, sigma=1., deadline=9.,
        spike_reference=points, fps=60.)
    assert [deadline for deadline, _ in deadlines] == [9., 9., 9.]
    assert all(kwargs['spike_reference'] is points for _, kwargs in deadlines[1:])
    assert deadlines[2][1]['fps'] == 60.


def test_rigid_pair_grip_projection_collapses_spacing_variance():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, project_rigid_pair_grip_coordinates)
    from exercise_motion_pkg.equipment_constraints import validate_grip
    names, points = stance(12)
    # Stretch one hand outward so rigid_pair fails, then project back.
    left, right = names.index('left_hand'), names.index('right_hand')
    points = points.copy()
    points[3:8, left] += [0.12, 0.0, 0.0]
    points[3:8, right] -= [0.08, 0.0, 0.0]
    rig = FixedRig(points, names)
    decoded = rig.decode(rig.initial)
    spacing = np.linalg.norm(decoded[:, left] - decoded[:, right], axis=-1)
    equipment = {
        'handRelationship': 'rigid_pair', 'available': True,
        'endpointPair': ['left_hand', 'right_hand'],
        'distanceMeters': float(np.median(spacing)),
        'distanceSource': 'robust_reconstruction_estimate',
        'toleranceMeters': max(0.005, 0.02 * float(np.median(spacing))),
    }
    before = validate_grip(decoded, names, equipment)
    assert not before['passed'], before
    projected = project_rigid_pair_grip_coordinates(
        rig.initial, rig, names, equipment, max_nfev=30)
    after = validate_grip(rig.decode(projected), names, equipment)
    assert after['passed'], (before, after)
    assert after['maximumSpacingErrorMeters'] < before['maximumSpacingErrorMeters']


def test_playback_rigid_pair_grip_closes_mid_sample_spacing_bow():
    """Keyframe grip can pass while hermite mids miss rigid_pair tolerance."""
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, project_rigid_pair_grip_coordinates, project_playback_rigid_pair_grip,
        _playback_grip_sample_error)
    from exercise_motion_pkg.equipment_constraints import validate_grip
    names, points = stance(24)
    left, right = names.index('left_hand'), names.index('right_hand')
    wrist = names.index('left_wrist')
    points = points.copy()
    points[1:-1, left] += [0.18, 0.0, 0.04]
    points[1:-1, right] -= [0.12, 0.0, 0.04]
    rig = FixedRig(points, names)
    # After FK encode, twist mid-frame wrists so hermite mids bow even once
    # keyframe spacing is projected back onto the rigid_pair target.
    shifted = rig.initial.copy()
    slot = rig.slots[wrist]
    shifted[1:-1, slot:slot + 3] += [0.35, 0.15, 0.08]
    decoded = rig.decode(shifted)
    spacing = np.linalg.norm(decoded[:, left] - decoded[:, right], axis=-1)
    equipment = {
        'handRelationship': 'rigid_pair', 'available': True,
        'endpointPair': ['left_hand', 'right_hand'],
        'distanceMeters': float(np.median(spacing[[0, -1]])),
        'distanceSource': 'robust_reconstruction_estimate',
        'toleranceMeters': 0.008,
    }
    keyed = project_rigid_pair_grip_coordinates(
        shifted, rig, names, equipment, max_nfev=40)
    assert validate_grip(rig.decode(keyed), names, equipment)['passed']
    before = _playback_grip_sample_error(keyed, rig, names, equipment, cyclic=False)
    assert before > equipment['toleranceMeters'], before
    planted = project_playback_rigid_pair_grip(
        keyed, rig, names, equipment, cyclic=False, max_nfev=24)
    after = _playback_grip_sample_error(planted, rig, names, equipment, cyclic=False)
    assert after <= equipment['toleranceMeters'], (before, after)
    assert validate_grip(rig.decode(planted), names, equipment)['passed']


def test_velocity_continuity_repair_replants_under_playback_gate(monkeypatch):
    """Smooth clears C1 jumps but lifts plants; repair must restore the 0.5 mm gate.

    When the jump already clears, repair must not smooth (that would reopen plants).
    """
    from exercise_motion_pkg import rig_interpolation as ri
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, project_contact_plant_coordinates, project_interval_playback_plants,
        repair_playback_velocity_continuity, _playback_contact_sample_error,
        _sampling_payload)
    from exercise_motion_pkg.physical_validation import body_scale
    from exercise_motion_pkg.rig_playback import (
        PLAYBACK_CONTACT_LIMIT_METERS, rig_contact_targets, sample_rig)
    names, points = stance(32)
    points = points.copy()
    # Bow mid-frame ankle DOFs so keyframe plants hold while hermite mids miss.
    rig = FixedRig(points, names)
    ankle = rig.slots[names.index('left_ankle')]
    feet = [names.index('left_foot'), names.index('right_foot')]
    pinned = np.zeros((len(points), len(names)), dtype=bool)
    pinned[:, feet] = True
    targets, _ = rig_contact_targets(rig.decode(rig.initial), names, pinned, rig.offsets)
    bowed = rig.initial.copy()
    bowed[1:-1, ankle:ankle + 3] += [0.15, 0.0, 0.05]
    keyed = project_contact_plant_coordinates(
        bowed, rig, pinned, targets, max_nfev=40, freeze_root=True)
    mid = project_interval_playback_plants(
        keyed, rig, pinned, targets, cyclic=False, max_nfev=20, spike_reference=points)
    play_mid = _playback_contact_sample_error(mid, rig, pinned, targets, cyclic=False)
    assert play_mid < PLAYBACK_CONTACT_LIMIT_METERS, play_mid

    # Already continuous: must keep plants (no destructive smooth).
    kept = repair_playback_velocity_continuity(
        mid, rig, pinned, targets, cyclic=False, sigma=0.85, spike_reference=points)
    assert np.allclose(kept, mid)
    assert _playback_contact_sample_error(
        kept, rig, pinned, targets, cyclic=False) < PLAYBACK_CONTACT_LIMIT_METERS

    # Force the smooth path once; replant must recover under the playback gate.
    real_jump = ri.frame_boundary_velocity_jump
    state = {'forced': True}

    def jump_with_force(sampler, knots, fps):
        value = real_jump(sampler, knots, fps)
        if state['forced']:
            state['forced'] = False
            return max(value, 1.0)
        return value

    monkeypatch.setattr(ri, 'frame_boundary_velocity_jump', jump_with_force)
    repaired = repair_playback_velocity_continuity(
        mid, rig, pinned, targets, cyclic=False, sigma=0.85, spike_reference=points)
    assert not np.allclose(repaired, mid)
    play = _playback_contact_sample_error(repaired, rig, pinned, targets, cyclic=False)
    assert play < PLAYBACK_CONTACT_LIMIT_METERS, play
    payload = _sampling_payload(rig, repaired)
    knots = np.arange(1, len(repaired) - 1)
    jump = real_jump(lambda cursors: sample_rig(payload, cursors, wrap=False), knots, 30.)
    assert jump <= 0.001 * body_scale(rig.decode(repaired), names) * 1.05
    from exercise_motion_pkg.controlled_motion import relative_motion_quality
    repaired_points = rig.decode(repaired)
    assert not relative_motion_quality(
        repaired_points, points, names, 30., spike_reference=points)['introducedSpikes']['severe']


def test_smooth_root_translation_reduces_second_difference():
    from exercise_motion_pkg.controlled_motion import (
        smooth_root_translation_coordinates, project_root_continuity_coordinates)
    from exercise_motion_pkg.motion_placement import root_motion_quality
    coords = np.zeros((20, 6), dtype=float)
    coords[:, 0] = np.linspace(0, 0.2, 20)
    coords[10, 0] += 0.08  # spike
    before = root_motion_quality(coords[:, :3], 30., 0.8)
    assert not before['passed']
    smoothed = smooth_root_translation_coordinates(coords, 30., scale=0.8)
    after = root_motion_quality(smoothed[:, :3], 30., 0.8)
    assert after['maximumSecondDifferenceMetersAt30Hz'] < before['maximumSecondDifferenceMetersAt30Hz']
    assert after['passed']
    projected = project_root_continuity_coordinates(coords, 30., 0.8)
    assert root_motion_quality(projected[:, :3], 30., 0.8)['passed']


def test_polish_stages_order_contact_before_temporal_before_seam():
    from exercise_motion_pkg.controlled_motion import (
        polish_stage_for_failures, polishable_near_miss)
    assert polish_stage_for_failures(['equipment', 'loopSeam']) == 'A'
    assert polish_stage_for_failures(['loopSeam', 'jerk']) == 'C'
    assert polish_stage_for_failures(['jerk', 'jointShake']) == 'C'
    assert polish_stage_for_failures(['rootContinuity', 'loopSeam']) == 'C'
    assert polish_stage_for_failures(['motionDiscontinuity']) == 'C'
    assert polish_stage_for_failures(['loopSeam']) == 'B'
    assert polish_stage_for_failures(['playback']) == 'C'
    assert polishable_near_miss(['contacts', 'equipment'])
    assert polishable_near_miss(['loopSeam'])
    assert polishable_near_miss(['rootContinuity', 'settling'])
    assert not polishable_near_miss(['anatomy', 'contacts'])


def test_repair_motion_discontinuity_clears_swing_foot_velocity_spike():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, polish_worsened_jerk, repair_motion_discontinuity_coordinates,
        smooth_extremity_coordinates)
    from exercise_motion_pkg.temporal_quality import track_discontinuity_metrics
    names, points = stance(48)
    # Smooth swing of the free right leg, then a one-frame world snap matching
    # retained reverse-lunge ~0.2 body-ratio extremity events.
    foot = names.index('right_foot')
    ankle = names.index('right_ankle')
    knee = names.index('right_knee')
    phase = np.linspace(0., np.pi, len(points))
    points[:, foot, 2] += 0.12 * np.sin(phase)
    points[:, ankle, 2] += 0.10 * np.sin(phase)
    points[:, knee, 2] += 0.05 * np.sin(phase)
    points[24, foot] += (0., 0., 0.35)
    points[24, ankle] += (0., 0., 0.30)
    points[24, knee] += (0., 0., 0.15)
    rig = FixedRig(points, names)
    coords = rig.initial.copy()
    decoded = rig.decode(coords)
    before = track_discontinuity_metrics(
        {name: decoded[:, j].tolist() for j, name in enumerate(names)},
        root_joint='pelvis', fps=30.)
    assert before['severe'], before
    mild = smooth_extremity_coordinates(coords, rig, names, cyclic=False, sigma=1.5)
    mild_points = rig.decode(mild)
    mild_metrics = track_discontinuity_metrics(
        {name: mild_points[:, j].tolist() for j, name in enumerate(names)},
        root_joint='pelvis', fps=30.)
    assert mild_metrics['severe'], mild_metrics
    repaired = repair_motion_discontinuity_coordinates(
        coords, rig, names, cyclic=False, fps=30., scale=0.8)
    after_points = rig.decode(repaired)
    after = track_discontinuity_metrics(
        {name: after_points[:, j].tolist() for j, name in enumerate(names)},
        root_joint='pelvis', fps=30.)
    assert not after['severe'], (mild_metrics, after)
    assert polish_worsened_jerk({'jerkAfter': 0.004}, 0.0008)
    assert not polish_worsened_jerk({'jerkAfter': 0.00081}, 0.0008)


def test_polish_reserve_scales_and_protects_stage_deadlines(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion
    assert motion.polish_reserve_seconds(120., cyclic=True) >= 12.
    assert motion.polish_reserve_seconds(120., cyclic=True) <= 15.
    assert motion.polish_reserve_seconds(10., cyclic=True) <= 4. + 1e-9
    assert motion.polish_reserve_seconds(120., cyclic=False) <= motion.polish_reserve_seconds(120., cyclic=True)
    now = [1000.]
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    # Pre-solve stages still use full outer mins; polish is carved at solve time.
    anatomy = motion._stage_deadline(1000., 120., fraction=0.35, minimum_seconds=75.)
    assert anatomy == 1000. + 75.
    now[0] = anatomy
    support = motion._stage_deadline(1000., 120., fraction=0.3, minimum_seconds=60.)
    # Capped by outer fit deadline (1000+120), not anatomy+60.
    assert support == 1000. + 120.


def test_support_init_minimum_scales_past_flat_ninety_for_long_cycles():
    from exercise_motion_pkg.controlled_motion import (
        SUPPORT_INIT_COLD_EVALUATIONS,
        SUPPORT_INIT_MIN_SECONDS,
        SUPPORT_INIT_SECONDS_PER_FRAME_EVAL,
        SUPPORT_INIT_SOLVE_RESERVE_FRACTION,
        SUPPORT_INIT_SOLVE_RESERVE_MIN_SECONDS,
        _stage_deadline,
    )
    frames = 129
    timeout = 240.
    support_cost = (SUPPORT_INIT_SECONDS_PER_FRAME_EVAL
                    * float(frames) * float(SUPPORT_INIT_COLD_EVALUATIONS))
    solve_reserve = max(
        SUPPORT_INIT_SOLVE_RESERVE_MIN_SECONDS,
        SUPPORT_INIT_SOLVE_RESERVE_FRACTION * timeout,
    )
    support_min = max(SUPPORT_INIT_MIN_SECONDS, support_cost)
    support_min = min(
        support_min,
        max(SUPPORT_INIT_MIN_SECONDS, timeout - solve_reserve),
    )
    # Retained GM-length cold init (~146s) must not be clipped by a flat 90s cap.
    assert support_cost > 90.
    assert support_min > 90.
    assert support_min <= timeout - solve_reserve
    deadline = _stage_deadline(0., timeout, fraction=0.3, minimum_seconds=support_min)
    assert deadline >= support_min


def test_seam_boundary_nudge_reduces_first_last_root_gap():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, seam_boundary_coordinate_nudge, close_loop_seam_coordinates,
        seam_velocity_neighbor_nudge, seam_playback_over_limit_score,
        project_loop_seam_coordinates, body_scale)
    from exercise_motion_pkg.loop_seam import seam_errors
    names, points = stance(12)
    points[-1, names.index('pelvis'), 0] += 0.04
    points[0, names.index('pelvis'), 0] -= 0.01
    # Asymmetric neighbors create a wrap velocity hitch.
    points[1, names.index('pelvis'), 0] += 0.02
    points[-2, names.index('pelvis'), 0] -= 0.02
    rig = FixedRig(points, names)
    pinned = np.zeros((12, len(names)), dtype=bool)
    scale = body_scale(points, names)
    before = seam_errors(rig.decode(rig.initial))[0]
    before_gap = float(np.linalg.norm(before[names.index('pelvis')]))
    before_score = seam_playback_over_limit_score(rig.decode(rig.initial), scale=scale, fps=30.)
    nudged = seam_boundary_coordinate_nudge(rig.initial, rig, pinned, strength=0.8)
    after = seam_errors(rig.decode(nudged))[0]
    after_gap = float(np.linalg.norm(after[names.index('pelvis')]))
    assert after_gap < before_gap
    velocity = seam_velocity_neighbor_nudge(nudged, rig, pinned, strength=0.8)
    velocity_score = seam_playback_over_limit_score(rig.decode(velocity), scale=scale, fps=30.)
    assert velocity_score <= before_score
    closed = close_loop_seam_coordinates(
        rig.initial, rig, pinned, scale=scale, fps=30., passes=6)
    closed_gap = float(np.linalg.norm(seam_errors(rig.decode(closed))[0][names.index('pelvis')]))
    closed_score = seam_playback_over_limit_score(rig.decode(closed), scale=scale, fps=30.)
    assert closed_gap < before_gap
    assert closed_score < before_score
    projected = project_loop_seam_coordinates(
        closed, rig, pinned, scale=scale, fps=30., max_nfev=40)
    projected_score = seam_playback_over_limit_score(
        rig.decode(projected), scale=scale, fps=30.)
    assert projected_score <= closed_score + 1e-9


def test_seam_projection_scores_anatomy_hidden_by_socket_guard(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    names, points = stance(4)
    rig = FixedRig(points, names)
    pinned = np.zeros((4, len(names)), dtype=bool)
    original_structure = motion.anatomical_structure_residuals
    socket_errors = []
    def structure(candidate, *args, **kwargs):
        errors, labels = original_structure(candidate, *args, **kwargs)
        socket_errors.append(float(np.max(errors[:, labels.index('anatomy_socket_alignment:neck')])))
        return errors, labels
    monkeypatch.setattr(motion, 'anatomical_structure_residuals', structure)
    def solve(residual, initial, *, jac, **kwargs):
        baseline = residual(initial)
        assert jac(initial).shape == (len(baseline), len(initial))
        probe = initial.reshape(4, rig.width).copy()
        slot = rig.slots[names.index('neck')]
        probe[:, slot:slot + 3] = [0., 0., .3]
        socket_errors.clear()
        errors = residual(probe.ravel())
        assert socket_errors and max(socket_errors) > .1
        assert np.max(np.abs(errors)) > 1000.
        return SimpleNamespace(x=initial)
    monkeypatch.setattr(motion, 'least_squares', solve)
    motion.project_loop_seam_coordinates(
        rig.initial, rig, pinned, scale=motion.body_scale(points, names), fps=30.)


def test_open_seam_is_applied_when_only_loop_wrap_fails():
    """Seam-only leftovers ship the fitted body with an honest open wrap label."""
    from exercise_motion_pkg import controlled_motion as motion
    checks = {name: True for name in motion.REQUIRED_FIT_CHECKS}
    checks['loopSeam'] = False
    checks['playback'] = True
    failed = {name for name, passed in checks.items() if not passed}
    assert failed == {'loopSeam'}
    assert failed <= {'loopSeam', 'playback'}


def test_seam_only_fit_reaches_bounded_projection(monkeypatch):
    import pytest
    from exercise_motion_pkg import controlled_motion as motion, rig_playback
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    original = rig_playback.validate_rig_playback

    def open_wrap(candidate, **kwargs):
        result = original(candidate, **kwargs)
        if candidate.get('loop', {}).get('enabled'):
            result.update(seamContinuous=False, seamVelocityMismatchMetersPerSecond=.3)
        return result

    class ProjectionReached(Exception):
        pass

    def project(*args, **kwargs):
        assert kwargs['deadline'] <= motion.monotonic() + 10.
        raise ProjectionReached()

    monkeypatch.setattr(rig_playback, 'validate_rig_playback', open_wrap)
    monkeypatch.setattr(motion, 'project_loop_seam_coordinates', project)
    with pytest.raises(ProjectionReached):
        motion._fit_controlled_motion(current, timeout_seconds=20.)


def test_seam_projection_continues_within_budget_only_when_body_valid_and_improving(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, rig_playback
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    original = rig_playback.validate_rig_playback
    state = {'calls': 0, 'improving': True}

    def playback(candidate, **kwargs):
        result = original(candidate, **kwargs)
        if candidate.get('loop', {}).get('enabled'):
            closed = state['improving'] and state['calls'] >= 3
            result.update(seamContinuous=closed,
                seamVelocityMismatchMetersPerSecond=0. if closed else
                    (.9 * .5 ** state['calls'] if state['improving'] else .9))
        return result

    def project(coords, *args, **kwargs):
        state['calls'] += 1
        assert kwargs['deadline'] <= motion.monotonic() + 10.
        return coords.copy()

    monkeypatch.setattr(rig_playback, 'validate_rig_playback', playback)
    monkeypatch.setattr(motion, 'project_loop_seam_coordinates', project)
    _, report = motion._fit_controlled_motion(current, timeout_seconds=30.)
    assert state['calls'] == 3
    assert report['checks']['loopSeam'] is True
    state.update(calls=0, improving=False)
    _, report = motion._fit_controlled_motion(current, timeout_seconds=30.)
    assert state['calls'] == 1
    assert report['checks']['loopSeam'] is False


def test_open_seam_can_reuse_and_passes_physical_gate():
    """Applied open-seam must not be rejected again by reuse/physical policy."""
    from copy import deepcopy
    from exercise_motion_pkg.controlled_motion import (
        can_reuse_controlled_motion, intentional_open_loop_seam)
    from exercise_motion_pkg.physical_validation import physical_metrics_from_payload
    from test_controlled_motion_pipeline import accepted_payload

    payload = accepted_payload()
    payload['loop'] = {
        'enabled': True,
        'transition': 'requires_cycle_repair',
        'restartFadeMillis': 0,
    }
    report = payload['controlledMotionFit']
    report['reason'] = 'validated_controlled_motion_open_seam'
    report['loopSeamOpen'] = True
    report['checks'] = {**report['checks'], 'loopSeam': False}
    report['outputPoseDigest'] = __import__(
        'exercise_motion_pkg.sequence_stabilization', fromlist=['pose_digest']
    ).pose_digest(payload)

    assert intentional_open_loop_seam(payload)
    assert can_reuse_controlled_motion(payload)

    # Playback false is also waived when the fit labeled an open seam.
    both = deepcopy(payload)
    both['controlledMotionFit']['checks']['playback'] = False
    both['controlledMotionFit']['outputPoseDigest'] = __import__(
        'exercise_motion_pkg.sequence_stabilization', fromlist=['pose_digest']
    ).pose_digest(both)
    assert can_reuse_controlled_motion(both)

    physical = physical_metrics_from_payload(payload)
    assert physical['passed'], physical.get('reasons')
    assert 'unsafe_loop_transition' not in physical.get('reasons', [])
    assert (physical.get('rigPlayback') or {}).get('openLoopSeam') is True


def test_open_seam_requires_body_playback_without_wrap():
    from test_controlled_motion_pipeline import accepted_payload
    from exercise_motion_pkg.controlled_motion import loop_disabled_playback_passed

    payload = accepted_payload()
    assert loop_disabled_playback_passed(payload)
    payload['loop'] = {'enabled': True, 'transition': 'requires_cycle_repair'}
    assert loop_disabled_playback_passed(payload)
    payload.pop('fixedRig')
    assert not loop_disabled_playback_passed(payload)


def test_evidence_terminations_are_decisive_not_incomplete():
    from exercise_motion_pkg import controlled_motion as motion
    assert motion.unreachable_without_polish({
        'checks': {'trajectoryFit': False, 'rootTravel': False}})
    assert motion.unreachable_without_polish({
        'checks': {'anatomy': False, 'sourceArticulation': False, 'contacts': True},
        'physicalReasons': ['repair_articulation_distortion']})
    assert not motion.unreachable_without_polish({
        'checks': {'loopSeam': False, 'playback': False}})
    for stop in motion.EVIDENCE_TERMINATIONS:
        report = {
            'applied': False,
            'reason': 'fit_timeout',
            'termination': stop,
            'checks': {'loopSeam': False},
            'optimizerTermination': 'time_budget',
        }
        assert not motion.controlled_fit_processing_incomplete(report), stop
        report = {
            'applied': False,
            'reason': 'fit_timeout',
            'boundedRefinement': {'stopReason': stop},
            'checks': {'jerk': False},
        }
        assert not motion.controlled_fit_processing_incomplete(report), stop
    # Validated reject mislabeled as fit_timeout must still be decisive.
    assert not motion.controlled_fit_processing_incomplete({
        'applied': False,
        'reason': 'fit_timeout',
        'optimizerTermination': 'time_budget',
        'checks': {'loopSeam': False, 'playback': False},
    })
    assert motion.controlled_fit_processing_incomplete({
        'applied': False,
        'reason': 'fit_timeout',
        'optimizerTermination': 'time_budget',
    })


def test_default_fit_refines_failed_cycle_without_exceeding_explicit_iteration_cap(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    calls = []
    clean = []
    stalled = [False]

    def solve(residual, initial, pattern, limit):
        calls.append(limit)
        # First chunk always breaks the seam so validation has something to polish.
        if len(calls) == 1:
            clean.append(initial.copy())
            bad = initial.copy().reshape(12, -1)
            bad[-1, 0] += .01  # A broken restart in an otherwise stationary rig.
            return SimpleNamespace(x=bad.ravel(), nfev=limit, status=0)
        if stalled[0]:
            return SimpleNamespace(x=initial.copy(), nfev=1, status=1)
        # Two more flat bad chunks trip main-solve objective_stalled.
        if len(calls) <= 3:
            bad = clean[0].copy().reshape(12, -1)
            bad[-1, 0] += .01
            return SimpleNamespace(x=bad.ravel(), nfev=limit, status=0)
        if len(calls) == 4:
            improving = clean[0].copy().reshape(12, -1)
            improving[-1, 0] += .005
            return SimpleNamespace(x=improving.ravel(), nfev=limit, status=0)
        return SimpleNamespace(x=clean[0].copy(), nfev=1, status=1)

    monkeypatch.setattr(motion, 'solve_trajectory', solve)
    _, refined = motion.fit_controlled_motion(current, timeout_seconds=10.)
    assert refined['applied'], refined
    # Main solve is chunked (5-eval blocks) until cost stalls / converges; polish
    # then uses short blocks. Explicit max_evaluations still caps total work.
    assert calls[0] == 5 and all(size <= 5 for size in calls), calls
    assert sum(calls) <= 25 + 5 + 5, calls
    assert refined['boundedRefinement']['initialFailedChecks']
    assert len([block for block in refined['boundedRefinement']['blocks']
                if block.get('method') != 'temporal_smooth']) == 2
    calls.clear()
    stalled[0] = True
    _, stopped = motion.fit_controlled_motion(current, timeout_seconds=10.)
    assert not stopped['applied']
    assert stopped['boundedRefinement']['stopReason'] in {
        'objective_stalled', 'acceptance_stalled', 'polish_stalled',
        'seam_playback_only'}, stopped
    assert stopped.get('termination') in motion.EVIDENCE_TERMINATIONS, stopped
    assert stopped['reason'] == 'fit_validation_failed', stopped
    assert not motion.controlled_fit_processing_incomplete(stopped), stopped
    assert calls and calls[0] == 5 and all(size <= 5 for size in calls), calls
    calls.clear()
    _, capped = motion.fit_controlled_motion(current, max_evaluations=25, timeout_seconds=10.)
    assert not capped['applied']
    assert calls and sum(calls) <= 25 and all(size <= 5 for size in calls), calls


def test_sample_rig_projects_interpolated_neck_socket_alignment():
    from exercise_motion_pkg.physical_validation import (
        SOCKET_ALIGNMENT_MAX_LATERAL_RATIO, anatomical_structure_residuals)
    from exercise_motion_pkg.controlled_motion import (
        ANATOMY_FIT_MARGIN, align_vectors, project_neck_attachment_values)
    from exercise_motion_pkg.rig_playback import sample_rig, _decode_rig_matrices
    rig_names, points = stance(2)
    rig = FixedRig(points, rig_names)
    names = rig.names
    left, right, neck = [names.index(n) for n in ('left_collar', 'right_collar', 'neck')]
    span = rig.decode(rig.initial)[0, right] - rig.decode(rig.initial)[0, left]
    neck_slot = rig.slots[neck]
    # Opposite keyframe neck pushes so the interpolated midpoint leaves the socket.
    for frame, sign in ((0, 1.), (1, -1.)):
        points = rig.decode(rig.initial)
        center = (points[frame, left] + points[frame, right]) * .5
        target = center + sign * (SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN) * span
        parent = points[frame, rig.parents[neck]]
        desired = target - parent
        desired = desired / np.linalg.norm(desired) * np.linalg.norm(rig.offsets[neck])
        old = Rotation.from_rotvec(rig.initial[frame, neck_slot:neck_slot + 3])
        world = old.apply(rig.offsets[neck])
        rig.initial[frame, neck_slot:neck_slot + 3] = (
            Rotation.from_rotvec(align_vectors(world[None], desired[None])) * old).as_rotvec()[0]
    limit = SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN
    coordinates = project_neck_attachment_values(
        rig.initial, rig.offsets, names, rig.active, limit)
    payload = {
        'jointNames': names, 'parents': rig.parents, 'order': rig.order,
        'offsets': rig.offsets.tolist(),
        'rotationJointNames': [names[j] for j in rig.active],
        'coordinates': coordinates.tolist(),
        'interpolation': 'linear_slerp',
    }
    values = np.asarray(payload['coordinates'], dtype=float)
    quats = Rotation.from_rotvec(values[:, 3:].reshape(-1, 3)).as_quat().reshape(2, -1, 4)
    right_q = np.where(np.sum(quats[0] * quats[1], axis=-1, keepdims=True) < 0., -quats[1], quats[1])
    mid_quat = .5 * quats[0] + .5 * right_q
    mid_quat /= np.linalg.norm(mid_quat, axis=-1, keepdims=True)
    unprojected = _decode_rig_matrices(
        payload, (values[0, :3] + values[1, :3]) * .5,
        Rotation.from_quat(mid_quat.reshape(-1, 4)).as_matrix().reshape(1, -1, 3, 3))
    labels = anatomical_structure_residuals(unprojected, names, pose_only=True)[1]
    socket = labels.index('anatomy_socket_alignment:neck')
    unprojected_err = anatomical_structure_residuals(unprojected, names, pose_only=True)[0][0, socket]
    projected_err = anatomical_structure_residuals(
        sample_rig(payload, [.5]), names, pose_only=True)[0][0, socket]
    assert unprojected_err > 0.
    assert projected_err <= 1e-9


def test_rig_has_constant_bones_and_fixed_sockets_under_arbitrary_rotation():
    names,points=stance()
    rig=FixedRig(points,names)
    values=rig.initial.copy()
    values+=np.random.default_rng(31).normal(0,.1,values.shape)
    result=rig.decode(values)
    for j in rig.order[1:]:
        np.testing.assert_allclose(np.linalg.norm(result[:,j]-result[:,rig.parents[j]],axis=1),
                                   np.linalg.norm(rig.offsets[j]),atol=1e-12)
    for a,b in [('left_hip','right_hip'),('left_collar','right_collar')]:
        distances=np.linalg.norm(result[:,names.index(a)]-result[:,names.index(b)],axis=1)
        assert np.ptp(distances)<1e-12


def test_solver_can_leave_an_inactive_stiff_constraint_toward_a_better_fit():
    from scipy.sparse import csr_matrix
    from exercise_motion_pkg.controlled_motion import solve_trajectory
    def residual(values):
        x = values[0]
        return np.array([x-.09, 1e8*max(x-.10000005, 0.)])
    solved = solve_trajectory(residual, np.array([.1]), csr_matrix(np.ones((2, 1))), 25)
    assert abs(solved.x[0]-.09) < 1e-7


def test_anatomy_fit_margin_has_consistent_derivatives_at_socket_boundary():
    from exercise_motion_pkg.physical_validation import anatomical_structure_residuals, SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    names, points = stance(1)
    left, right, neck = [names.index(n) for n in ('left_collar', 'right_collar', 'neck')]
    span = points[0, right]-points[0, left]
    center = (points[0, right]+points[0, left])*.5
    current = np.dot(points[0, neck]-center, span)/np.dot(span, span)
    margin = 1e-4
    points[0, neck] += (SOCKET_ALIGNMENT_MAX_LATERAL_RATIO-margin-current)*span
    def evaluate(offset, fitting_margin):
        moved = points.copy()
        moved[0, neck] += offset*span
        values, labels = anatomical_structure_residuals(moved, names, pose_only=True, margin=fitting_margin)
        return values[0, labels.index('anatomy_socket_alignment:neck')]
    step = 1e-8
    midpoint = evaluate(0., margin)
    left_derivative = (midpoint-evaluate(-step, margin))/step
    right_derivative = (evaluate(step, margin)-midpoint)/step
    assert abs(left_derivative-right_derivative) < 1e-3
    assert midpoint > 0.
    assert evaluate(0., 0.) == 0.


def test_positive_kernel_does_not_rebound_at_a_stop():
    names,points=stance(120)
    travel=np.minimum(np.arange(120)/60.,1.)*.5
    points[:,:,0]+=travel[:,None]
    target,_,_=controlled_target(points,names,30.)
    root=names.index('pelvis')
    assert np.all(np.diff(target[:,root,0])>=-1e-10)
    assert target[:,root,0].max()<=points[:,root,0].max()+1e-10
    assert target[:,root,0].min()>=points[:,root,0].min()-1e-10


def test_sideways_travel_and_asymmetry_are_preserved_and_rotation_equivariant():
    names,points=stance(90)
    points[:,:,0]+=np.arange(90)[:,None]*.005
    points[:,names.index('left_wrist'),2]+=.1
    target,_,_=controlled_target(points,names,30.)
    root=names.index('pelvis')
    assert np.ptp(target[:,root,0])>.95*np.ptp(points[:,root,0])
    rotation=Rotation.from_euler('xyz',[.2,.6,-.3]).as_matrix()
    rotated,_,_=controlled_target(points@rotation,names,30.)
    np.testing.assert_allclose(rotated,target@rotation,atol=1e-9)
    np.testing.assert_allclose(target[:,names.index('left_wrist')]-target[:,root],
                               points[:,names.index('left_wrist')]-points[:,root],atol=1e-10)


def test_small_subordinate_deviations_reduce_without_a_world_axis_lock():
    names,points=stance(120)
    t=np.arange(120)/30.
    points[:,:,1]+=(.15*np.sin(2*np.pi*.5*t))[:,None]
    points[:,:,0]+=(.008*np.sin(2*np.pi*2.5*t))[:,None]
    target,_,evidence=controlled_target(points,names,30.)
    root=names.index('pelvis')
    assert np.std(target[20:-20,root,0])<np.std(points[20:-20,root,0])*.7
    assert np.ptp(target[:,root,1])>.9*np.ptp(points[:,root,1])
    assert evidence['maximumMinorDeviationCorrectionMeters']>0


def test_fit_preserves_contact_and_rig_and_is_reusable():
    # A short stationary clip covers denoising, contact, rig and cache reuse;
    # longer trajectories have separate motion and loop regression coverage.
    names,points=stance(12)
    rng=np.random.default_rng(13)
    head=names.index('head')
    points[:,head,0]+=rng.normal(0,.002,len(points))
    p=payload(names,points)
    p['sourceFootSupportEvidence']={'contacts':[{'jointName':s+'_foot','contactState':'full_sole',
                                               'contactMotion':'stationary','startRatio':0.,'endRatio':1.}
                                              for s in ('left','right')]}
    result,report=fit_controlled_motion(p,max_evaluations=25,timeout_seconds=60.)
    assert report['applied'],report
    assert report['maximumBoneLengthVariationMeters']<1e-10
    assert report['maximumContactErrorMeters']<.0005
    assert report['jerkAfter']<report['jerkBefore']
    assert report['settlingPreserved']
    assert all(report['checks'].values())
    result['controlledMotionFit']=report
    again,audit=fit_controlled_motion(result)
    assert again is result and audit['reused']


def test_timeout_and_irregular_sampling_return_original():
    names,points=stance(10)
    p=payload(names,points)
    result,report=fit_controlled_motion(p,timeout_seconds=0.)
    # A zero watchdog still validates the initialized rig instead of discarding it.
    assert report.get('validatedInitializedCoordinatesOnTimeout')
    assert report['applied'] and result.get('fixedRig')
    p['frames'][3]['timeSec']+=.01
    result,report=fit_controlled_motion(p)
    assert result is p and report['reason']=='irregular_sampling'


def test_playback_contact_repair_stops_if_deadline_expires_before_or_during_scan(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    names, points = stance(12)
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    pinned = np.ones(points.shape[:2], dtype=bool)
    now = [10.]
    scans = []

    def scan(*args, **kwargs):
        scans.append(True)
        now[0] = 10.
        return [0]

    def unexpected_decode(*args, **kwargs):
        raise AssertionError('Expired repair must not start FK or mutate the pose')

    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    monkeypatch.setattr(motion, '_playback_failing_intervals', scan)
    monkeypatch.setattr(rig, 'decode', unexpected_decode)
    for start, expected_scans in [(10., 0), (9., 1)]:
        now[0] = start
        result = motion.project_interval_playback_plants(
            coordinates, rig, pinned, points, deadline=10.)
        np.testing.assert_array_equal(result, coordinates)
        assert len(scans) == expected_scans


def test_initial_validation_preserves_polish_reserve_within_outer_budget(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, rig_playback
    real_clock = motion.monotonic
    real_validation = rig_playback.validate_rig_playback
    delay = [0.]
    validation_cost = [20.]

    def expensive_validation(candidate):
        result = real_validation(candidate)
        delay[0] += validation_cost[0]
        return result

    monkeypatch.setattr(motion, 'monotonic', lambda: real_clock() + delay[0])
    monkeypatch.setattr(rig_playback, 'validate_rig_playback', expensive_validation)
    names, points = stance(12)
    _, report = motion.fit_controlled_motion(payload(names, points), timeout_seconds=60.)
    assert report['applied']
    assert report['initialValidationSeconds'] >= 20.
    assert 20. < report['polishUntilSeconds'] <= 60.
    # Validation can finish after the watchdog, but cannot grant extra repair time.
    validation_cost[0] = 80.
    _, report = motion.fit_controlled_motion(payload(names, points), timeout_seconds=60.)
    assert report['initialValidationSeconds'] >= 80.
    assert report['polishUntilSeconds'] <= 60.


def test_time_budget_validates_saved_progress_before_discarding_it(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}

    def timed_out(residual, initial, pattern, max_evaluations):
        residual(initial)
        raise TimeoutError

    monkeypatch.setattr(motion, 'solve_trajectory', timed_out)
    result, report = motion.fit_controlled_motion(current, timeout_seconds=20.)
    # Soft LS may stop on the solve-phase cap while outer time remains for polish.
    assert report['optimizerTermination'] in {'time_budget', 'solve_phase_budget'}
    assert report['applied']
    assert all(report['checks'].values())
    assert result.get('fixedRig')
    assert not motion.controlled_fit_processing_incomplete(report)

    def invalid_progress(residual, initial, pattern, max_evaluations):
        shifted = initial.copy().reshape(12, -1)
        shifted[:, 1] -= 1.
        residual(shifted.ravel())
        raise TimeoutError

    monkeypatch.setattr(motion, 'solve_trajectory', invalid_progress)
    rejected, failure = motion.fit_controlled_motion(current, timeout_seconds=20.)
    assert rejected is current
    assert not failure['applied']
    assert failure.get('checks'), failure
    # Finished checks are a decisive reject even when the soft LS hit a deadline.
    assert failure['reason'] == 'fit_validation_failed', failure
    assert not motion.controlled_fit_processing_incomplete(failure), failure


def test_support_init_watchdog_continues_to_acceptance(monkeypatch):
    """A support-stage clock stop must not discard the pose before validation."""
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg import support_geometry
    names, points = stance(12)
    current = payload(names, points)
    # Torso support still uses the heavy LS path; plant-only feet skip it.
    stationary = [name for name in ('pelvis', 'spine1', 'spine2', 'spine3') if name in names]
    if len(stationary) < 2:
        stationary = [name for name in names if 'spine' in name or name == 'pelvis'][:3]
    evidence = {
        'required': True, 'status': 'confirmed', 'stationaryJoints': stationary,
        'coplanarGroups': [{'joints': stationary, 'normal': [0, 1, 0],
                            'planeOffsetMeters': float(points[0, names.index(stationary[0]), 1])}],
    }
    current['sourceFootSupportEvidence'] = {'bodySupport': evidence}
    monkeypatch.setattr(support_geometry, 'support_evidence', lambda payload: evidence)
    monkeypatch.setattr(support_geometry, 'plant_only_body_support', lambda evidence: False)
    monkeypatch.setattr(support_geometry, 'calibrate_support_pose',
                        lambda *args, **kwargs: (points[0], {}))
    monkeypatch.setattr(support_geometry, 'initialize_supported_motion',
                        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))
    result, report = motion.fit_controlled_motion(current, timeout_seconds=20.)
    assert report.get('supportInitializationTimedOut')
    assert report.get('checks'), report
    assert not motion.controlled_fit_processing_incomplete(report)


def test_small_monotonic_motion_is_not_a_hold():
    names,points=stance(90)
    joint=names.index('head')
    points[:,joint,0]+=np.arange(90)*.0001
    _,holds,_=controlled_target(points,names,30.)
    assert np.max(holds[10:-10,joint])<1e-10


def test_hold_coordinates_ignore_rigid_body_turns():
    names,points=stance(45)
    rotations=Rotation.from_euler('y',np.linspace(0.,.6,len(points))[:,None]).as_matrix()
    turned=np.einsum('fij,fkj->fki',rotations,points)
    np.testing.assert_allclose(body_relative_points(turned,names),body_relative_points(points,names),atol=1e-10)


def test_jump_releases_feet_and_preserves_height():
    names,points=stance(48)
    rig=FixedRig(points,names)
    points=rig.decode(rig.initial)
    phase=np.linspace(0.,np.pi,28)
    points[10:38,:,1]+=(.22*np.sin(phase))[:,None]
    p=payload(names,points)
    p['sourceFootSupportEvidence']={'contacts':[
        {'jointName':side+'_foot','contactState':'full_sole','contactMotion':'stationary',
         'startFrame':start,'endFrame':end}
        for side in ('left','right') for start,end in [(0,9),(38,47)]]}
    result,report=fit_controlled_motion(p)
    assert report['applied'],report
    track=np.array([f['joints']['pelvis'] for f in result['frames']])
    assert np.ptp(track[:,1])>.19
    assert report['maximumContactErrorMeters']<.0005


def test_small_slow_articulation_survives_full_fit():
    names,points=stance(60)
    rig=FixedRig(points,names)
    values=rig.initial.copy()
    slot=rig.slots[names.index('head')]
    values[:,slot]+=.07*np.sin(np.linspace(0.,2*np.pi,len(points)))
    points=rig.decode(values)
    result,report=fit_controlled_motion(payload(names,points))
    assert report['applied'],report
    fitted=np.array([[f['joints'][n] for n in names] for f in result['frames']])
    first=body_relative_points(points,names)[:,names.index('head')]
    last=body_relative_points(fitted,names)[:,names.index('head')]
    assert np.linalg.norm(np.ptp(last,axis=0))>.8*np.linalg.norm(np.ptp(first,axis=0))


def test_excursion_constraint_protects_large_range_without_locking_small_motion():
    from exercise_motion_pkg.controlled_motion import excursion_constraints
    names,points=stance(60)
    root=names.index('pelvis');wrist=names.index('left_wrist');head=names.index('head')
    phase=np.arange(60)*2*np.pi/60
    points[:,wrist,0]+=.2*np.sin(phase)
    points[:,head,0]+=.002*np.sin(phase)
    center,direction,minimum,active=excursion_constraints(points,root,1.)
    assert active[:,wrist].any()
    assert not active[:,head].any()
    relative=points-points[:,root:root+1]
    projection=np.sum((relative-center)*direction,axis=-1)
    assert np.all(projection[active]>=minimum[active])
    compressed=center+.5*(relative-center)
    assert np.all(np.sum((compressed-center)*direction,axis=-1)[active]<minimum[active])
    rotation=Rotation.from_euler('xyz',[.2,.5,.8]).as_matrix()
    c,d,m,a=excursion_constraints(points@rotation,root,1.)
    np.testing.assert_allclose(c,center@rotation,atol=1e-12)
    np.testing.assert_allclose(m,minimum,atol=1e-12)
    np.testing.assert_array_equal(a,active)
    np.testing.assert_allclose(d[:,wrist],direction[:,wrist]@rotation,atol=1e-12)


def test_downward_bone_does_not_invent_axial_half_turns():
    from exercise_motion_pkg.controlled_motion import transported_bone_rotations
    phase=np.linspace(0.,2*np.pi,80)
    directions=np.column_stack([.001*np.cos(phase),-np.ones(80),.001*np.sin(phase)])
    directions/=np.linalg.norm(directions,axis=1)[:,None]
    rotations=transported_bone_rotations(directions)
    np.testing.assert_allclose(rotations.apply(np.tile([0.,1.,0.],(80,1))),directions,atol=1e-12)
    changes=(rotations[:-1].inv()*rotations[1:]).magnitude()
    observed=np.arccos(np.clip(np.sum(directions[:-1]*directions[1:],axis=1),-1.,1.))
    np.testing.assert_allclose(changes,observed,atol=1e-10)
    assert np.rad2deg(changes.max())<.01


def test_vectorized_hinge_frames_match_the_final_branch_validator():
    from exercise_motion_pkg.controlled_motion import hinge_coordinates,transported_hinge_dots
    from exercise_motion_pkg.physical_validation import ARTICULATIONS
    from exercise_motion_pkg.structural_refinement import _local_hinge_bend
    from exercise_motion_pkg.models import MotionFrame
    names,points=stance(3)
    parent,bend,sine=hinge_coordinates(points,names)
    specs=[s for s in ARTICULATIONS if s[0].endswith(('_knee','_elbow'))]
    for index,(_,a,h,b,_) in enumerate(specs):
        expected=_local_hinge_bend(MotionFrame(0.,dict(zip(names,map(tuple,points[0])))),a,h,b)
        if expected is not None:
            np.testing.assert_allclose(parent[0,index],expected[0],atol=1e-12)
            np.testing.assert_allclose(bend[0,index],expected[1],atol=1e-12)
    dots=transported_hinge_dots(parent,bend,parent,-bend)
    np.testing.assert_allclose(dots[sine>1e-8],-1.,atol=1e-12)


def test_fit_budget_scales_with_frames_and_preserves_explicit_limits():
    from exercise_motion_pkg.controlled_motion import fit_time_budget
    assert fit_time_budget({'frames':[None]*60})==180.
    assert fit_time_budget({'frames':[None]*92})==230.
    assert fit_time_budget({'frames':[None]*146})==360.
    assert fit_time_budget({'frames':[None]*240})==360.
    assert fit_time_budget({'frames':[None]*2000})==360.
    assert fit_time_budget({'frames':[None]*240},60.)==60.
    assert fit_time_budget({'frames':[None]*240},0.)==0.


def test_neck_socket_repair_clears_interpolated_guard_without_moving_limbs():
    from exercise_motion_pkg.controlled_motion import (
        project_playback_neck_clearance, repair_playback_velocity_continuity, _sampling_payload)
    from exercise_motion_pkg.rig_playback import sample_rig, sample_rig_coordinates, decode_rig
    from exercise_motion_pkg.rig_interpolation import frame_boundary_velocity_jump
    fixture = json.loads((Path(__file__).parent / 'fixtures' /
        'neck_socket_interpolation_corner.json').read_text())
    names, points = stance(5)
    rig = FixedRig(points, names)
    for joint, offset in fixture['offsets'].items():
        rig.offsets[names.index(joint)] = offset
    for joint, rotations in fixture['rotations'].items():
        slot = rig.slots[names.index(joint)]
        rig.initial[:, slot:slot + 3] = rotations
    original = rig.initial.copy()
    def jump(values):
        return frame_boundary_velocity_jump(
            lambda cursors: sample_rig(_sampling_payload(rig, values), cursors),
            np.arange(1, 4), 30.)
    assert jump(original) > .001
    repaired = repair_playback_velocity_continuity(original, rig, None, None)
    assert jump(repaired) < 1e-6
    cursors = np.arange(4 * 64 + 1) / 64.
    before = sample_rig(_sampling_payload(rig, original), cursors)
    after_payload = _sampling_payload(rig, repaired)
    after = sample_rig(after_payload, cursors)
    raw = decode_rig(after_payload, sample_rig_coordinates(after_payload, cursors))
    # The guard is inactive along the dense path, not just at the knot check.
    np.testing.assert_allclose(after, raw, atol=1e-10)
    limbs = [index for index, name in enumerate(names) if name not in ('neck', 'head')]
    np.testing.assert_array_equal(after[:, limbs], before[:, limbs])
    assert np.max(np.linalg.norm(after - before, axis=-1)) < .0001
    np.testing.assert_array_equal(
        project_playback_neck_clearance(repaired, rig), repaired)


def test_support_range_derivative_matches_full_numerical_objective():
    from scipy.optimize._numdiff import approx_derivative
    from exercise_motion_pkg.controlled_motion import support_range_jacobian, angles
    names, points = stance(5)
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    coordinates[:, rig.slots[names.index('left_ankle')]] += np.linspace(.1, .5, len(points))
    joints = tuple(names.index(name) for name in ('left_hip', 'left_knee', 'left_ankle'))
    source = np.array([0., 1.])
    tracks = [('left_knee', joints, source)]
    def residual(values):
        candidate = rig.decode(values.reshape(coordinates.shape))
        return np.array([12000. * max(0., .92 * np.ptp(source)
            - np.ptp(angles(*(candidate[:, joint] for joint in joints))))])
    expected = approx_derivative(residual, coordinates.ravel(), method='3-point')
    actual = support_range_jacobian(coordinates.ravel(), rig, tracks).toarray()
    assert residual(coordinates.ravel())[0] > 0.
    assert np.max(np.abs(expected)) > 100.
    np.testing.assert_allclose(actual, np.atleast_2d(expected), atol=.05, rtol=1e-4)
    assert support_range_jacobian(coordinates.ravel(), rig,
        [('left_knee', joints, np.zeros(2))]).nnz == 0


def test_global_range_derivative_does_not_force_full_clip_difference_groups():
    from scipy.sparse import csr_matrix, eye, vstack
    from exercise_motion_pkg.controlled_motion import solve_trajectory
    count = 120
    initial = np.linspace(0., 1., count)
    calls = []
    def residual(values):
        calls.append(1)
        return np.r_[values - initial, 10. * max(0., 2. - np.ptp(values))]
    def tail_jacobian(values):
        result = np.zeros((1, count))
        if np.ptp(values) < 2.:
            result[0, np.argmin(values)] += 10.
            result[0, np.argmax(values)] -= 10.
        return csr_matrix(result)
    pattern = vstack([eye(count), csr_matrix(np.ones((1, count)))], format='csr')
    solved = solve_trajectory(residual, initial, pattern, 5, tail_jacobian=tail_jacobian)
    assert np.ptp(solved.x) > 1.9
    assert len(calls) < 30


def test_solver_can_move_a_tiny_nonzero_rotation():
    from exercise_motion_pkg.controlled_motion import solve_trajectory
    from scipy.sparse import csr_matrix
    names,points=stance(1)
    rig=FixedRig(points,names)
    slot=rig.slots[names.index('left_ankle')]
    base=rig.initial.copy()
    base[:,:3]+=[2.,3.,4.]
    def decode(values):
        coordinates=base.copy()
        coordinates[0,slot]=values[0]
        coordinates[0,2]+=values[1]
        return rig.decode(coordinates).ravel()
    expected=np.array([.02,.11])
    target=decode(expected)
    probes=[]
    def residual(values):
        probes.append(values.copy())
        return decode(values)-target
    initial=np.array([5e-16,.1])
    solved=solve_trajectory(residual,initial,csr_matrix(np.ones((len(target),2))),25)
    np.testing.assert_allclose(solved.x,expected,atol=1e-6)
    first_rotation_probe=next(v for v in probes if v[0]!=initial[0] and v[1]==initial[1])
    derivative=(decode(first_rotation_probe)-decode(initial))/(first_rotation_probe[0]-initial[0])
    assert np.linalg.norm(derivative)>.1


def test_sparse_dependencies_cover_coupled_rotations_and_body_relative_motion():
    from exercise_motion_pkg.controlled_motion import joint_dependencies,rotation_prior_dependencies
    from scipy.optimize._numdiff import approx_derivative
    initial=Rotation.from_euler('xyz',[.3,.4,.5])
    values=np.array([0.,0.,0.,.25,-.37,.22])
    derivative=approx_derivative(lambda v:(initial.inv()*Rotation.from_rotvec(v[3:])).as_rotvec(),values)
    pattern=rotation_prior_dependencies(6).astype(bool)
    assert np.all(abs(derivative[~pattern])<1e-8)
    assert np.any(abs(derivative[:,3:]-np.diag(np.diag(derivative[:,3:])))>1e-3)
    names,points=stance(1)
    rig=FixedRig(points,names)
    values=rig.initial.ravel()+.01
    derivative=approx_derivative(lambda v:body_relative_points(rig.decode(v[None,:]),names).ravel(),values)
    basis=joint_dependencies(rig,('pelvis','left_hip','right_hip','neck'))
    pattern=np.maximum(rig.dependencies,basis[None,:]).astype(bool)
    assert np.all(abs(derivative[~pattern])<1e-7)
    assert not pattern.all()
