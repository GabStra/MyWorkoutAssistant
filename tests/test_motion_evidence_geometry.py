import copy
import math
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import pose_fidelity as fidelity
from exercise_motion_pkg.repetition_phase import complete_repetition


@pytest.mark.parametrize('width,height', [(640, 360), (360, 640), (1000, 1000)])
def test_image_geometry_is_invariant_to_canvas_aspect_ratio(width, height):
    # Same physical triangle, expressed in three differently shaped images.
    points = {'a': [20, 20], 'b': [80, 20], 'c': [80, 90]}
    payload = {'coordinateSpace': 'normalized_image_xy', 'imageWidth': width,
               'imageHeight': height, 'frames': [{'sourceTimeSec': 0,
               'joints': {n: [x / width, y / height] for n, (x, y) in points.items()}}]}
    observed = fidelity._pose_frames(payload, source=True)[0]['joints']
    for name, point in points.items():
        assert observed[name] == pytest.approx([v / height for v in point])


def test_missing_image_dimensions_do_not_silently_assume_square_pixels():
    assert fidelity._pose_frames({'coordinateSpace': 'normalized_image_xy',
        'frames': [{'sourceTimeSec': 0, 'joints': {'a': [.1, .2]}}]}, source=True) == []


def test_sparse_observations_do_not_stretch_motion_or_extrapolate():
    frames = [{'time': t, 'joints': {'wrist': (2*t, t, 0)}} for t in [0., 1., 2.]]
    assert fidelity._motion_frame_at_time(frames, 1.8)['joints']['wrist'] == pytest.approx((3.6, 1.8, 0))
    assert fidelity._motion_frame_at_time(frames, 2.1) is None
    assert fidelity._motion_frame_at_time(frames, -.1) is None


def test_fidelity_matches_sparse_video_to_motion_in_metric_space():
    base = {'left_shoulder': (1., 1.), 'right_shoulder': (2., 1.),
            'left_hip': (1., 2.), 'right_hip': (2., 2.),
            'left_knee': (1., 3.), 'right_knee': (2., 3.),
            'left_ankle': (1., 4.), 'right_ankle': (2., 4.),
            'left_elbow': (.5, 1.5), 'right_elbow': (2.5, 1.5),
            'left_wrist': (.2, 2.), 'right_wrist': (2.8, 2.)}
    def joints(t):
        return {n: (x + (.2*t if 'wrist' in n else 0), y) for n, (x, y) in base.items()}
    source = {'coordinateSpace': 'normalized_image_xy', 'imageWidth': 640, 'imageHeight': 360,
              'frames': [{'sourceTimeSec': t, 'joints': {n: [x*50/640, y*50/360]
                          for n, (x, y) in joints(t).items()}} for t in [.15, .3, .7, 1.1, 1.8]]}
    motion = {'frames': [{'timeSec': t, 'joints': {n: [x, -y, 0]
                         for n, (x, y) in joints(t).items()}} for t in [0., 1., 2., 3., 4.]]}
    result = fidelity.source_to_motion_pose_fidelity_metrics_for_projection(source, motion,
        projection_reference={'projectionHorizontalVector': [1., 0.], 'mirrored': False})
    assert result['available']
    assert result['comparableFrameCount'] == 5
    assert result['p90JointErrorBodyRatio'] < 1e-10


@pytest.mark.parametrize('closed', [False, True])
def test_empty_cycle_proposals_attempt_retained_seam_and_preserve_verdict(monkeypatch, closed):
    from exercise_motion_pkg import controlled_motion
    calls = []
    def retained_fit(payload, **kwargs):
        calls.append(payload.get('loop', {}).get('enabled'))
        return payload, {'applied': closed, 'reason': 'validated_controlled_motion' if closed
                         else 'loop_requires_cycle_repair', 'checks': {'loopSeam': closed}}
    monkeypatch.setattr(controlled_motion, '_fit_controlled_motion', retained_fit)
    payload = {'loop': {'enabled': True}, 'observedCycleProposals': [], 'sourceCyclePreflight': []}
    result, report = controlled_motion._fit_observed_cycles(payload, timeout_seconds=10)
    assert result is not None
    assert calls == [True]
    assert report['applied'] is closed
    assert report['retainedIntervalFit'] is True
    assert report['checks']['loopSeam'] is closed
    assert report['reason'] == ('validated_controlled_motion' if closed else 'loop_requires_cycle_repair')
    assert not report.get('loopSeamOpen')


def test_cycle_budget_does_not_reserve_unaffordable_later_attempts(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles
    elapsed = [0.]
    budgets = []

    def fit(payload, **kwargs):
        budget = kwargs['timeout_seconds']
        budgets.append(budget)
        if len(budgets) == 1:
            elapsed[0] += 265.
            return payload, {'applied': False, 'reason': 'fit_validation_failed',
                             'checks': {'jointShake': False}}
        # This wrap needs 80 s; a 55 s turn fails even though 95 s is available.
        passed = budget >= 80.
        elapsed[0] += min(80., budget)
        return payload, {'applied': passed, 'reason': 'validated_controlled_motion' if passed
                         else 'fit_validation_failed', 'checks': {'jointShake': passed}}

    monkeypatch.setattr(motion, 'monotonic', lambda: elapsed[0])
    monkeypatch.setattr(motion, '_fit_controlled_motion', fit)
    monkeypatch.setattr(loop_cycles, 'slice_loop_cycle', lambda payload, choice: dict(payload))
    _, report = motion._fit_observed_cycles(
        {'loop': {'enabled': True}, 'observedCycleProposals': [{}, {}, {}]}, timeout_seconds=360.)
    assert report['applied']
    assert len(budgets) == 2
    assert 80. <= budgets[1] <= 95.
    assert elapsed[0] <= 360.


def test_phase_valid_wrap_uses_leftover_budget_after_retained_fit(monkeypatch):
    from exercise_motion_pkg import controlled_motion
    reasons = []
    def fake_fit(payload, **kwargs):
        kind = 'slice' if payload.get('_sliced') else 'retained'
        reasons.append((kind, payload.get('loop', {}).get('enabled')))
        if kind == 'slice':
            return payload, {'applied': True, 'reason': 'validated_controlled_motion', 'checks': {'loopSeam': True}}
        return payload, {'applied': True, 'reason': 'validated_controlled_motion_open_seam', 'checks': {}}
    monkeypatch.setattr(controlled_motion, '_fit_controlled_motion', fake_fit)
    monkeypatch.setattr(
        'exercise_motion_pkg.loop_cycles.slice_loop_cycle',
        lambda payload, choice: {**payload, '_sliced': True, 'choice': choice},
    )
    payload = {
        'loop': {'enabled': True},
        'observedCycleProposals': [{'startFrame': 0, 'stopFrameExclusive': 20}],
    }
    _, report = controlled_motion._fit_observed_cycles(payload, timeout_seconds=120)
    assert report['applied'] is True
    assert report['reason'] == 'validated_controlled_motion'
    assert reasons[0] == ('retained', False)
    assert any(kind == 'slice' for kind, _ in reasons)


@pytest.mark.parametrize('second_closes', [True, False])
def test_open_cycle_does_not_discard_budgeted_alternatives(monkeypatch, second_closes):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles
    calls = []

    def fit(payload, **kwargs):
        calls.append(payload)
        index = payload.get('crop')
        if index is None:
            return payload, {'applied': False, 'reason': 'fit_validation_failed',
                             'checks': {'jointShake': False}}
        closed = index == 2 and second_closes
        return payload, {'applied': True, 'loopSeamOpen': not closed,
                         'reason': 'validated_controlled_motion' if closed else
                                   'validated_controlled_motion_open_seam',
                         'termination': None if closed else 'seam_excess_needs_different_cycle',
                         'checks': {'loopSeam': closed}}

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit)
    monkeypatch.setattr(loop_cycles, 'slice_loop_cycle', lambda payload, choice: {**payload, 'crop': choice})
    result, report = motion._fit_observed_cycles(
        {'loop': {'enabled': True}, 'observedCycleProposals': [1, 2]}, timeout_seconds=360.)
    assert len(calls) == 3
    assert result['crop'] == (2 if second_closes else 1)
    assert report['checks']['loopSeam'] is second_closes
    assert len(report['cycleSelectionAttempts']) == 3


@pytest.mark.parametrize('completion_mode', ['stable_hold', 'representative_cycle', 'active_travel'])
def test_source_coverage_requires_locomotion_only_for_active_travel(monkeypatch, completion_mode):
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg.segment_detection import DetectionWindow

    joints = {'head': [0., 1.8, 0.], 'pelvis': [0., 1., 0.],
              'left_ankle': [-.1, 0., 0.], 'right_ankle': [.1, 0., 0.]}
    payload = {'jointNames': list(joints), 'rootJoint': 'pelvis',
               'frames': [{'timeSec': i / 4., 'joints': dict(joints)} for i in range(8)]}
    monkeypatch.setattr(bake, 'source_pose_skeleton_payload_for_window', lambda *args, **kwargs: payload)
    metrics = bake.source_cut_candidate_motion_coverage_metrics(
        candidate_window=DetectionWindow(0, 0., 2.), pose_payload={}, exercise_name='Exercise',
        chunk_estimate=None, exercise_motion_contract={'completionMode': completion_mode,
                                                     'requiresReturnToStart': False})
    locomotion = metrics['activeTravelLocomotion']
    assert locomotion['required'] is (completion_mode == 'active_travel')
    assert locomotion['passed'] is (completion_mode != 'active_travel')
    assert ('source_cut_missing_active_travel_locomotion' in metrics['rejectionReasons']) is (
        completion_mode == 'active_travel')


@pytest.mark.parametrize('verified_fit', [False, True])
def test_support_invariant_uses_verified_fit_ownership(tmp_path, monkeypatch, verified_fit):
    from exercise_motion_pkg import bake_and_rank as bake, controlled_motion
    baseline = SimpleNamespace(settings_variant_id='adaptive-baseline', settings_options={},
        export_payload={}, skeleton_path=tmp_path/'baseline.json')
    alternative = SimpleNamespace(settings_variant_id='adaptive-trial',
        settings_options={'lockPlantedFeet': True}, export_payload={'controlledMotionFit': {'applied': True}},
        skeleton_path=tmp_path/'trial.json')
    monkeypatch.setattr(controlled_motion, 'can_reuse_controlled_motion', lambda payload: verified_fit)
    checks = []
    def distal_check(*args):
        checks.append(True)
        return {'passed': False, 'rejectionReasons': ['upstream_pose_changed']}
    monkeypatch.setattr(bake, 'support_lock_baseline_safety_metrics', distal_check)
    kept = bake.prefer_baseline_safe_support_lock_artifacts([baseline, alternative])
    assert (alternative in kept) == verified_fit
    assert bool(checks) == (not verified_fit)


def test_support_gate_uses_cropped_contact_timing_and_still_rejects_sliding():
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg.loop_cycles import slice_loop_cycle

    evidence = {'contacts': [{'jointName': 'left_ankle', 'supportKind': 'foot',
                             'startRatio': 0., 'endRatio': 39 / 79, 'confidence': .9}]}
    payload = {'fps': 30., 'sourceFootSupportEvidence': evidence, 'frames': [
        {'timeSec': i / 30., 'joints': {
            'head': [0., 1.8, 0.], 'pelvis': [0., 1., 0.],
            'left_ankle': [max(0, i - 39) * .06, 0., 0.],
            'right_ankle': [.2, 0., 0.]}} for i in range(80)]}
    cropped = slice_loop_cycle(payload, {'startFrame': 30, 'stopFrameExclusive': 70})
    assert bake.source_confirmed_support_stationarity_metrics(cropped, evidence)['passed']
    stale = copy.deepcopy(cropped)
    stale.pop('sourceFootSupportEvidence')
    assert not bake.source_confirmed_support_stationarity_metrics(stale, evidence)['passed']
    drifting = copy.deepcopy(cropped)
    for i in range(10):
        drifting['frames'][i]['joints']['left_ankle'][0] += i * .04
    assert not bake.source_confirmed_support_stationarity_metrics(drifting, evidence)['passed']


def test_retained_source_window_uses_explicit_time_origin_without_mutation():
    source = {'frames': [{'sourceTimeSec': t, 'joints': {'wrist': [t, 0]}}
                         for t in [0., 10., 10.5, 11., 12.]]}
    original = copy.deepcopy(source)
    motion = {'frames': [{'sourceTimeSec': t, 'timeSec': t-10} for t in [10., 11.]]}
    selected = fidelity.source_pose_reference_for_motion(source, motion)
    assert [f['time'] for f in fidelity._pose_frames(selected, source=True)] == [0., .5, 1.]
    assert source == original


@pytest.mark.parametrize('offset', [0, math.pi/4, math.pi/2, math.pi, 1.7*math.pi])
def test_complete_cycle_is_independent_of_start_phase(offset):
    values = [math.sin(offset + i*2*math.pi/120) for i in range(121)]
    assert complete_repetition(values)[0]


def test_partial_multiple_and_stationary_sequences_are_not_single_cycles():
    for half_cycles in (3, 4, 5):
        values = [math.cos(i*math.pi/120) for i in range(120*half_cycles+1)]
        assert complete_repetition(values, exactly_one=False)[0]
        assert not complete_repetition(values)[0]
    assert not complete_repetition([math.cos(i*math.pi/120) for i in range(121)], exactly_one=False)[0]
    assert not complete_repetition([1.] * 121, exactly_one=False)[0]
    assert not complete_repetition([math.cos(i*math.pi/120) for i in range(121)])[0]
    assert not complete_repetition([math.sin(i*4*math.pi/120) for i in range(121)])[0]
    assert not complete_repetition([1.] * 121)[0]
    # Both extreme bands were visited, but the endpoints neither return nor
    # continue in the same direction. Coverage alone must not pass this.
    assert not complete_repetition([.5, .2, 0., .2, .8, 1., .8])[0]
