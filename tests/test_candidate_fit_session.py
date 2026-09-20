import json
from pathlib import Path
from time import monotonic

import numpy as np

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg import anatomical_repair as anatomy
from exercise_motion_pkg import fit_runtime


def test_source_confirmed_cycle_precedes_full_interval_with_shared_budget(monkeypatch):
    from exercise_motion_pkg import loop_cycles

    choice = {'startFrame': 10, 'stopFrameExclusive': 50}
    payload = {'frames': [None] * 100, 'loop': {'enabled': True},
               'observedCycleProposals': [choice],
               'sourceCyclePreflight': [{'selection': choice, 'passed': True}]}
    now, calls = [0.], []
    succeeds = [True]
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    monkeypatch.setattr(loop_cycles, 'slice_loop_cycle',
                        lambda p, c: {**p, 'loopCycleSelection': c})

    def fit(candidate, **kwargs):
        calls.append((candidate.get('loopCycleSelection'), kwargs['timeout_seconds']))
        elapsed = 40. if succeeds[0] else kwargs['timeout_seconds']
        now[0] += elapsed
        return candidate, {'applied': succeeds[0], 'reason': 'validated_controlled_motion'
                           if succeeds[0] else 'fit_validation_failed',
                           'checks': {'loopSeam': succeeds[0]}, 'elapsedSeconds': elapsed}

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit)
    _, report = motion._fit_observed_cycles(payload, timeout_seconds=360.)
    assert calls == [(choice, 108.)]
    assert report['applied'] and report['elapsedSeconds'] == 40.
    assert report['cycleSelectionAttempts'][0]['sourceConfirmedFirst']
    succeeds[0] = False
    calls.clear()
    now[0] = 0.
    result, report = motion._fit_observed_cycles(payload, timeout_seconds=360.)
    assert calls == [(choice, 108.), (None, 252.)]
    assert now[0] == 360.
    assert result is payload and not report['applied']


def test_candidate_budget_covers_distinct_variants_and_reuses_exact_fit(monkeypatch):
    now = [0.]
    monkeypatch.setattr(fit_runtime, 'monotonic', lambda: now[0])
    calls = []

    def fit(payload, **kwargs):
        calls.append(kwargs['timeout_seconds'])
        now[0] += 6.
        return payload, {'applied': False, 'reason': 'fit_timeout'}

    monkeypatch.setattr(motion, '_fit_observed_cycles', fit)
    with fit_runtime.candidate_fit_session(budget_seconds=10.) as session:
        motion.fit_controlled_motion({'frames': [], 'variant': 1})
        _, reused = motion.fit_controlled_motion({'frames': [], 'variant': 1})
        assert reused['reusedCandidateFit']
        motion.fit_controlled_motion({'frames': [], 'variant': 2})
        _, exhausted = motion.fit_controlled_motion({'frames': [], 'variant': 3})
        assert exhausted['budgetOwner'] == 'candidate'
        assert session.fit_calls == 2
    assert calls == [10., 4.]
    assert fit_runtime.current_fit_session() is None


def test_observed_cycle_attempts_prefer_top_cycle_budget(monkeypatch):
    now = [0.]
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    received = []

    def fit(payload, **kwargs):
        received.append(kwargs['timeout_seconds'])
        now[0] += kwargs['timeout_seconds']
        return payload, {'applied': False, 'reason': 'fit_timeout', 'elapsedSeconds': kwargs['timeout_seconds']}

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit)
    import exercise_motion_pkg.loop_cycles as loop_cycles
    monkeypatch.setattr(loop_cycles, 'rank_loop_cycles', lambda payload, max_candidates=3: [
        {'start': 0, 'end': 10}, {'start': 5, 'end': 15}])
    monkeypatch.setattr(loop_cycles, 'slice_loop_cycle',
                        lambda payload, choice: {**payload, 'loopCycleSelection': choice})
    payload = {'frames': [None] * 60, 'loop': {'enabled': True}}
    _, report = motion._fit_observed_cycles(payload, timeout_seconds=100.)
    # The retained interval cannot consume the reserved crop allowance; spend
    # the remaining 45 seconds on one crop instead of stranding that budget.
    assert received == [55., 45.]
    assert report['reason'] == 'no_validated_loop_cycle'
    assert len(report['cycleSelectionAttempts']) == 2


def test_observed_cycle_skips_later_cycles_after_seam_only_near_miss(monkeypatch):
    now = [0.]
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    received = []

    def fit(payload, **kwargs):
        received.append(kwargs['timeout_seconds'])
        now[0] += 5.
        return payload, {
            'applied': False,
            'reason': 'loop_requires_cycle_repair',
            'elapsedSeconds': 5.,
            'checks': {
                'trajectoryFit': True,
                'rootTravel': True,
                'jointRange': True,
                'loopSeam': False,
                'playback': False,
            },
            # Within 2× limit → early-stop (near-miss).
            'playback': {
                'seamStepExcessMeters': 0.005,
                'seamStepExcessLimitMeters': 0.003,
            },
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit)
    import exercise_motion_pkg.loop_cycles as loop_cycles
    monkeypatch.setattr(loop_cycles, 'rank_loop_cycles', lambda payload, max_candidates=3: [
        {'startFrame': 2, 'stopFrameExclusive': 40, 'score': 0.1},
        {'startFrame': 10, 'stopFrameExclusive': 50, 'score': 0.2},
    ])
    monkeypatch.setattr(loop_cycles, 'slice_loop_cycle',
                        lambda payload, choice: {**payload, 'loopCycleSelection': choice,
                                                 'frames': payload.get('frames')})
    payload = {'frames': [None] * 60, 'loop': {'enabled': True}, 'fps': 30.0}
    _, report = motion._fit_observed_cycles(payload, timeout_seconds=400.)
    assert received == [310.]
    assert report['reason'] == 'no_validated_loop_cycle'
    assert len(report['cycleSelectionAttempts']) == 1


def test_observed_cycle_tries_next_when_seam_excess_far_from_limit(monkeypatch):
    now = [0.]
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    received = []

    def fit(payload, **kwargs):
        received.append(kwargs['timeout_seconds'])
        now[0] += 5.
        return payload, {
            'applied': False,
            'reason': 'loop_requires_cycle_repair',
            'elapsedSeconds': 5.,
            'checks': {
                'trajectoryFit': True,
                'rootTravel': True,
                'jointRange': True,
                'loopSeam': False,
                'playback': False,
            },
            # ≫2× limit → try next ranked cycle.
            'playback': {
                'seamStepExcessMeters': 0.025,
                'seamStepExcessLimitMeters': 0.003,
                'seamVelocityMismatchMetersPerSecond': 0.2,
                'seamVelocityMismatchLimitMetersPerSecond': 0.2,
            },
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit)
    import exercise_motion_pkg.loop_cycles as loop_cycles
    monkeypatch.setattr(loop_cycles, 'rank_loop_cycles', lambda payload, max_candidates=3: [
        {'startFrame': 2, 'stopFrameExclusive': 40, 'score': 0.1},
        {'startFrame': 10, 'stopFrameExclusive': 50, 'score': 0.2},
    ])
    monkeypatch.setattr(loop_cycles, 'slice_loop_cycle',
                        lambda payload, choice: {**payload, 'loopCycleSelection': choice,
                                                 'frames': payload.get('frames'),
                                                 'fps': payload.get('fps')})
    payload = {'frames': [None] * 60, 'loop': {'enabled': True}, 'fps': 30.0}
    _, report = motion._fit_observed_cycles(payload, timeout_seconds=400.)
    assert len(received) == 2
    assert report['reason'] == 'no_validated_loop_cycle'
    assert len(report['cycleSelectionAttempts']) == 2


def test_observed_cycle_tries_next_when_seam_velocity_far_from_limit(monkeypatch):
    now = [0.]
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    received = []

    def fit(payload, **kwargs):
        received.append(kwargs['timeout_seconds'])
        now[0] += 5.
        return payload, {
            'applied': False,
            'reason': 'loop_requires_cycle_repair',
            'elapsedSeconds': 5.,
            'checks': {
                'trajectoryFit': True,
                'rootTravel': True,
                'jointRange': True,
                'loopSeam': False,
                'playback': False,
            },
            # Step near-miss but velocity ≫2× → still try next cycle.
            'playback': {
                'seamStepExcessMeters': 0.004,
                'seamStepExcessLimitMeters': 0.003,
                'seamVelocityMismatchMetersPerSecond': 0.75,
                'seamVelocityMismatchLimitMetersPerSecond': 0.2,
            },
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit)
    import exercise_motion_pkg.loop_cycles as loop_cycles
    monkeypatch.setattr(loop_cycles, 'rank_loop_cycles', lambda payload, max_candidates=3: [
        {'startFrame': 2, 'stopFrameExclusive': 40, 'score': 0.1},
        {'startFrame': 10, 'stopFrameExclusive': 50, 'score': 0.2},
    ])
    monkeypatch.setattr(loop_cycles, 'slice_loop_cycle',
                        lambda payload, choice: {**payload, 'loopCycleSelection': choice,
                                                 'frames': payload.get('frames'),
                                                 'fps': payload.get('fps')})
    payload = {'frames': [None] * 60, 'loop': {'enabled': True}, 'fps': 30.0}
    _, report = motion._fit_observed_cycles(payload, timeout_seconds=400.)
    assert len(received) == 2
    assert len(report['cycleSelectionAttempts']) == 2


def test_observed_cycle_tries_next_when_non_seam_failure_leaves_budget(monkeypatch):
    now = [0.]
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    received = []

    def fit(payload, **kwargs):
        received.append(kwargs['timeout_seconds'])
        now[0] += 5.
        return payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'elapsedSeconds': 5.,
            'checks': {'jointRange': False, 'trajectoryFit': True, 'rootTravel': True},
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit)
    import exercise_motion_pkg.loop_cycles as loop_cycles
    monkeypatch.setattr(loop_cycles, 'rank_loop_cycles', lambda payload, max_candidates=3: [
        {'startFrame': 0, 'stopFrameExclusive': 12}, {'startFrame': 5, 'stopFrameExclusive': 17}])
    monkeypatch.setattr(loop_cycles, 'slice_loop_cycle',
                        lambda payload, choice: {**payload, 'loopCycleSelection': choice,
                                                 'frames': payload.get('frames')})
    payload = {'frames': [None] * 12, 'loop': {'enabled': True}, 'fps': 30.0}
    _, report = motion._fit_observed_cycles(payload, timeout_seconds=400.)
    assert received == [310., 395.]
    assert report['reason'] == 'no_validated_loop_cycle'
    assert len(report['cycleSelectionAttempts']) == 2


def test_observed_cycle_skips_later_cycles_after_hard_trajectory_root_failure(monkeypatch):
    now = [0.]
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    received = []

    def fit(payload, **kwargs):
        received.append(kwargs['timeout_seconds'])
        now[0] += 5.
        return payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'elapsedSeconds': 5.,
            'checks': {'trajectoryFit': False, 'rootTravel': False, 'loopSeam': True},
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit)
    import exercise_motion_pkg.loop_cycles as loop_cycles
    monkeypatch.setattr(loop_cycles, 'rank_loop_cycles', lambda payload, max_candidates=3: [
        {'startFrame': 0, 'stopFrameExclusive': 12}, {'startFrame': 5, 'stopFrameExclusive': 17}])
    monkeypatch.setattr(loop_cycles, 'slice_loop_cycle',
                        lambda payload, choice: {**payload, 'loopCycleSelection': choice,
                                                 'frames': payload.get('frames')})
    payload = {'frames': [None] * 12, 'loop': {'enabled': True}, 'fps': 30.0}
    _, report = motion._fit_observed_cycles(payload, timeout_seconds=400.)
    assert received == [310.]
    assert report['reason'] == 'no_validated_loop_cycle'
    assert len(report['cycleSelectionAttempts']) == 1


def test_controlled_fit_unusable_for_more_preview_work():
    assert motion.controlled_fit_unusable_for_more_preview_work(
        {'applied': False, 'reason': 'fit_validation_failed'})
    assert motion.controlled_fit_unusable_for_more_preview_work(
        {'applied': False, 'reason': 'fit_timeout'})
    assert motion.controlled_fit_unusable_for_more_preview_work(
        {'applied': False, 'reason': 'other', 'checks': {'trajectoryFit': False, 'rootTravel': False}})
    assert motion.controlled_fit_unusable_for_more_preview_work(
        {'applied': False, 'reason': 'loop_requires_cycle_repair', 'checks': {'loopSeam': False}})
    assert not motion.controlled_fit_unusable_for_more_preview_work(
        {'applied': True, 'reason': 'validated_controlled_motion'})

def test_candidate_fit_can_use_remaining_session_beyond_single_fit_floor(monkeypatch):
    now = [0.]
    monkeypatch.setattr(fit_runtime, 'monotonic', lambda: now[0])
    received = []

    def fit(payload, **kwargs):
        received.append(kwargs['timeout_seconds'])
        return payload, {'applied': False, 'reason': 'fit_timeout'}

    monkeypatch.setattr(motion, '_fit_observed_cycles', fit)
    with fit_runtime.candidate_fit_session(budget_seconds=300.):
        motion.fit_controlled_motion({'frames': [None] * 60})
    # Frame-scaled base is 180s; multi-cycle allocation may use up to 2x when session remains.
    assert received == [300.]


def test_finalization_priority_prefers_kept_candidate_workspace(tmp_path, monkeypatch):
    import threading
    # Force a single slot so priority ordering is observable under contention.
    monkeypatch.setattr(fit_runtime, 'cpu_fit_slot_limit', lambda: 1)
    order = []
    blocker = threading.Event()
    prioritized_started = threading.Event()

    def run_fit(label, workspace):
        with fit_runtime.candidate_fit_session(workspace):
            with fit_runtime.cpu_fit_slot():
                order.append(f'{label}:enter')
                if label == 'other':
                    prioritized_started.wait(5)
                    blocker.wait(5)
                order.append(f'{label}:leave')

    other = threading.Thread(target=run_fit, args=('other', tmp_path / 'other'))
    other.start()
    assert any(item == 'other:enter' for item in order) or other.is_alive()
    # Wait until the non-priority holder owns the slot.
    for _ in range(50):
        if 'other:enter' in order:
            break
        threading.Event().wait(0.05)
    kept = tmp_path / 'kept'
    def run_priority():
        with fit_runtime.prioritize_fit_workspaces([kept]):
            prioritized_started.set()
            run_fit('kept', kept)
    priority = threading.Thread(target=run_priority)
    priority.start()
    # Non-priority follower must not overtake the prioritized workspace once the holder finishes.
    follower = threading.Thread(target=run_fit, args=('follower', tmp_path / 'follower'))
    follower.start()
    threading.Event().wait(0.2)
    blocker.set()
    other.join(5)
    priority.join(5)
    follower.join(5)
    assert order.index('kept:enter') < order.index('follower:enter')


def test_finalization_priority_allows_every_listed_candidate_workspace(tmp_path, monkeypatch):
    """Regression for Reverse Hyper hang: only prioritizing candidate 1/N
    left candidate 2 blocked forever inside the same finalize context."""
    monkeypatch.setattr(fit_runtime, 'cpu_fit_slot_limit', lambda: 1)
    first = tmp_path / 'cand-1'
    second = tmp_path / 'cand-2'
    entered = []

    with fit_runtime.prioritize_fit_workspaces([first, second]):
        with fit_runtime.candidate_fit_session(first):
            with fit_runtime.cpu_fit_slot():
                entered.append('first')
        with fit_runtime.candidate_fit_session(second):
            with fit_runtime.cpu_fit_slot():
                entered.append('second')

    assert entered == ['first', 'second']


def test_speculative_fit_yields_when_any_final_is_prioritized(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(fit_runtime, 'cpu_fit_slot_limit', lambda: 1)
    order = []
    speculative_entered = threading.Event()
    other_priority_armed = threading.Event()
    speculative_left = threading.Event()

    def run_speculative():
        with fit_runtime.speculative_fit_context():
            with fit_runtime.candidate_fit_session(tmp_path / 'speculative'):
                with fit_runtime.cpu_fit_slot():
                    order.append('speculative:enter')
                    speculative_entered.set()
                    assert other_priority_armed.wait(5)
                    deadline = threading.Event()
                    while not deadline.wait(0.05):
                        if fit_runtime.fit_should_yield_for_priority():
                            order.append('speculative:yield')
                            break
                    else:
                        order.append('speculative:timeout')
                order.append('speculative:leave')
                speculative_left.set()

    def run_other_priority():
        speculative_entered.wait(5)
        with fit_runtime.prioritize_fit_workspaces([tmp_path / 'other-final']):
            other_priority_armed.set()
            speculative_left.wait(5)
            with fit_runtime.candidate_fit_session(tmp_path / 'other-final'):
                with fit_runtime.cpu_fit_slot():
                    order.append('final:enter')
                    order.append('final:leave')

    speculative = threading.Thread(target=run_speculative)
    other = threading.Thread(target=run_other_priority)
    speculative.start()
    other.start()
    speculative.join(5)
    other.join(5)
    assert 'speculative:yield' in order
    assert order.index('speculative:leave') < order.index('final:enter')


def test_speculative_fit_waits_while_other_workspace_finalizes(tmp_path, monkeypatch):
    import threading
    from time import sleep
    monkeypatch.setattr(fit_runtime, 'cpu_fit_slot_limit', lambda: 2)
    order = []
    priority_armed = threading.Event()
    final_entered = threading.Event()
    release_final = threading.Event()

    def run_final():
        with fit_runtime.prioritize_fit_workspaces([tmp_path / 'final']):
            priority_armed.set()
            with fit_runtime.candidate_fit_session(tmp_path / 'final'):
                with fit_runtime.cpu_fit_slot():
                    order.append('final:enter')
                    final_entered.set()
                    assert release_final.wait(5)
                    order.append('final:leave')

    def run_speculative():
        assert priority_armed.wait(5)
        acquired = []

        def try_acquire():
            with fit_runtime.speculative_fit_context():
                with fit_runtime.candidate_fit_session(tmp_path / 'speculative'):
                    with fit_runtime.cpu_fit_slot():
                        acquired.append(True)
                        order.append('speculative:enter')

        waiter = threading.Thread(target=try_acquire)
        waiter.start()
        sleep(0.3)
        assert not acquired
        assert final_entered.wait(5)
        release_final.set()
        waiter.join(5)
        assert acquired
        order.append('speculative:after-final')

    final = threading.Thread(target=run_final)
    speculative = threading.Thread(target=run_speculative)
    final.start()
    speculative.start()
    final.join(5)
    speculative.join(5)
    assert order.index('final:enter') < order.index('speculative:enter')
    assert order.index('final:leave') < order.index('speculative:enter')


def test_two_cpu_fit_slots_run_concurrently(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(fit_runtime, 'cpu_fit_slot_limit', lambda: 2)
    entered = []
    both_inside = threading.Event()
    release = threading.Event()

    def run_fit(label):
        with fit_runtime.candidate_fit_session(tmp_path / label):
            with fit_runtime.cpu_fit_slot():
                entered.append(label)
                if len(entered) >= 2:
                    both_inside.set()
                assert both_inside.wait(5)
                release.wait(5)

    first = threading.Thread(target=run_fit, args=('a',))
    second = threading.Thread(target=run_fit, args=('b',))
    first.start()
    second.start()
    assert both_inside.wait(5)
    release.set()
    first.join(5)
    second.join(5)
    assert set(entered) == {'a', 'b'}


def test_abandoned_speculative_fit_raises_instead_of_holding_slot(tmp_path):
    fit_runtime.abandon_speculative_workspace(tmp_path / 'speculative')
    with fit_runtime.speculative_fit_context():
        with fit_runtime.candidate_fit_session(tmp_path / 'speculative'):
            try:
                with fit_runtime.cpu_fit_slot():
                    raise AssertionError('abandoned speculative fit must not acquire a slot')
            except fit_runtime.SpeculativePrefetchAbandoned:
                pass


def test_browser_fit_cancellation_is_owned_by_task_not_workspace(tmp_path):
    import pytest
    from exercise_motion_pkg.browser_workers import BrowserWorkers

    workers = BrowserWorkers(workers=1)

    def fit():
        with fit_runtime.candidate_fit_session(tmp_path):
            with fit_runtime.cpu_fit_slot():
                assert not fit_runtime.fit_should_yield_for_priority()
                return 'finalized'

    try:
        # Prefetch is still active when finalization submits work for the same
        # workspace. Reuse the browser thread to also check context isolation.
        with fit_runtime.speculative_workspace(tmp_path):
            fit_runtime.abandon_speculative_workspace(tmp_path)
            with fit_runtime.speculative_fit_context():
                with pytest.raises(fit_runtime.SpeculativePrefetchAbandoned):
                    workers.run(fit)
            with fit_runtime.prioritize_fit_workspaces([tmp_path]):
                assert workers.run(fit) == 'finalized'
    finally:
        workers.close()


def test_abandoned_speculative_workspace_yields_without_priority(tmp_path):
    import threading
    order = []
    speculative_entered = threading.Event()
    abandon_armed = threading.Event()
    speculative_left = threading.Event()

    def run_speculative():
        with fit_runtime.speculative_fit_context():
            with fit_runtime.candidate_fit_session(tmp_path / 'speculative'):
                with fit_runtime.cpu_fit_slot():
                    order.append('speculative:enter')
                    speculative_entered.set()
                    assert abandon_armed.wait(5)
                    while not fit_runtime.fit_should_yield_for_priority():
                        threading.Event().wait(0.05)
                    order.append('speculative:yield')
                order.append('speculative:leave')
                speculative_left.set()

    def run_abandon():
        speculative_entered.wait(5)
        fit_runtime.abandon_speculative_workspace(tmp_path / 'speculative')
        abandon_armed.set()
        speculative_left.wait(5)
        with fit_runtime.candidate_fit_session(tmp_path / 'speculative'):
            with fit_runtime.cpu_fit_slot():
                order.append('final:enter')
                order.append('final:leave')

    speculative = threading.Thread(target=run_speculative)
    abandon = threading.Thread(target=run_abandon)
    speculative.start()
    abandon.start()
    speculative.join(5)
    abandon.join(5)
    assert order.index('speculative:yield') < order.index('speculative:leave')
    assert order.index('speculative:leave') < order.index('final:enter')


def test_final_fit_does_not_self_preempt_when_only_own_workspace_prioritized(tmp_path):
    import threading
    entered = threading.Event()
    release = threading.Event()
    order = []

    def run_final():
        with fit_runtime.prioritize_fit_workspaces([tmp_path / 'final']):
            with fit_runtime.candidate_fit_session(tmp_path / 'final'):
                with fit_runtime.cpu_fit_slot():
                    order.append('final:enter')
                    entered.set()
                    assert not fit_runtime.fit_should_yield_for_priority()
                    release.wait(5)
                    order.append('final:leave')

    thread = threading.Thread(target=run_final)
    thread.start()
    assert entered.wait(5)
    release.set()
    thread.join(5)
    assert order == ['final:enter', 'final:leave']


def test_cpu_queue_wait_preserves_remaining_candidate_budget(monkeypatch):
    from contextlib import contextmanager
    now = [0.]
    monkeypatch.setattr(fit_runtime, 'monotonic', lambda: now[0])

    @contextmanager
    def delayed_slot():
        now[0] += 20.
        # Match production: queue wait does not consume candidate budget.
        session = fit_runtime.current_fit_session()
        if session is not None and session.started is not None:
            session.started += 20.
        yield 20.

    monkeypatch.setattr(fit_runtime, 'cpu_fit_slot', delayed_slot)
    received = []
    def fit(payload, **kwargs):
        received.append(kwargs['timeout_seconds'])
        return payload, {'applied': False, 'reason': 'fit_timeout'}
    monkeypatch.setattr(motion, '_fit_observed_cycles', fit)
    with fit_runtime.candidate_fit_session(budget_seconds=10.) as session:
        assert session.remaining() == 10.
        now[0] += 3.
        _, report = motion.fit_controlled_motion({'frames': []})
        assert session.remaining() == 7.
    assert received == [7.]
    assert report['cpuFitQueueWaitSeconds'] == 20.


def test_anatomy_resume_reuses_completed_frames_and_invalidates_changed_input(tmp_path, monkeypatch):
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile(np.array(list(fixture['joints'].values())), (3, 1, 1))
    rig = motion.FixedRig(points, names)
    points = rig.decode(rig.initial)
    axis = points[0, names.index('neck')]-points[0, names.index('pelvis')]
    lateral = points[0, names.index('right_hip')]-points[0, names.index('left_hip')]
    forward = np.cross(axis, lateral)
    points[:, names.index('spine1')] += forward/np.linalg.norm(forward)*.14
    with fit_runtime.candidate_fit_session(tmp_path):
        expected, report = anatomy.repair_rig_anatomy(motion.FixedRig(points, names), points, deadline=monotonic()+10.)
    assert report['passed']
    assert (tmp_path/'anatomy_repair_checkpoint.json').exists()
    original_solver = anatomy.least_squares
    calls = []

    def solve(*args, **kwargs):
        calls.append(True)
        return original_solver(*args, **kwargs)

    monkeypatch.setattr(anatomy, 'least_squares', solve)
    with fit_runtime.candidate_fit_session(tmp_path) as session:
        actual, report = anatomy.repair_rig_anatomy(motion.FixedRig(points, names), points, deadline=monotonic()+10.)
        assert session.reused_frames == 3
    assert not calls
    np.testing.assert_array_equal(actual, expected)
    from exercise_motion_pkg import physical_validation
    original_spans = physical_validation.span_rigidity_violations
    def changed_span_targets(values, joint_names, span_targets=None):
        result = original_spans(values, joint_names, span_targets)
        if span_targets is None:
            return {label: (deviation, target * 1.001) for label, (deviation, target) in result.items()}
        return result
    with monkeypatch.context() as context:
        context.setattr(physical_validation, 'span_rigidity_violations', changed_span_targets)
        with fit_runtime.candidate_fit_session(tmp_path) as session:
            _, changed_report = anatomy.repair_rig_anatomy(
                motion.FixedRig(points, names), points, deadline=monotonic()+10.)
            assert session.reused_frames == 2  # Only the two duplicate frames reuse the newly solved constraint.
            assert changed_report['passed']
        assert calls  # Same frame and rig, different clip constraint must be solved again.
    calls.clear()
    altered = points.copy()
    altered[:, names.index('spine1')] += forward/np.linalg.norm(forward)*.005
    with fit_runtime.candidate_fit_session(tmp_path):
        anatomy.repair_rig_anatomy(motion.FixedRig(altered, names), altered, deadline=monotonic()+10.)
    assert calls


def test_timed_out_fit_resumes_trajectory_in_a_later_session(tmp_path, monkeypatch):
    from test_controlled_motion_pipeline import accepted_payload
    payload = accepted_payload()
    payload.pop('fixedRig')
    payload.pop('controlledMotionFit')
    for index, frame in enumerate(payload['frames']):
        frame['joints']['head'][0] += .002*(-1)**index
    solver = motion.solve_trajectory
    first_call = [True]

    def interrupt_after_progress(residual, initial, pattern, max_evaluations):
        solved = solver(residual, initial, pattern, max_evaluations)
        if first_call[0]:
            first_call[0] = False
            residual(solved.x)
            raise TimeoutError('Deadline after completed solver work')
        return solved

    monkeypatch.setattr(motion, 'solve_trajectory', interrupt_after_progress)
    real_fit = motion._fit_controlled_motion

    def keep_timeout_incomplete(payload, **kwargs):
        # A timed-out iterate may already pass independent validation. Keep the
        # incomplete-processing resume path covered even when that happens.
        result, report = real_fit(payload, **kwargs)
        if (report.get('optimizerTermination') in {'time_budget', 'solve_phase_budget'}
                and report.get('applied')):
            return payload, {**report, 'applied': False, 'reason': 'fit_timeout'}
        return result, report

    monkeypatch.setattr(motion, '_fit_controlled_motion', keep_timeout_incomplete)
    with fit_runtime.candidate_fit_session(tmp_path):
        _, first = motion.fit_controlled_motion(payload, max_evaluations=2, timeout_seconds=10.)
    assert motion.controlled_fit_processing_incomplete(first), first
    with fit_runtime.candidate_fit_session(tmp_path) as session:
        assert session.trajectories
        _, second = motion.fit_controlled_motion(payload, max_evaluations=2, timeout_seconds=10.)
    assert second.get('resumedTrajectory'), second


def test_iteration_limit_is_processing_incomplete_without_overriding_acceptance():
    assert motion.controlled_fit_processing_incomplete({'reason': 'fit_evaluation_limit', 'applied': False})
    assert not motion.controlled_fit_processing_incomplete({'reason': 'validated_controlled_motion', 'applied': True})


def test_evaluation_limit_skips_continuation_when_acceptance_stalled(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from test_controlled_motion_pipeline import accepted_payload

    payload = accepted_payload()
    payload.pop('fixedRig', None)
    payload.pop('controlledMotionFit', None)
    for index, frame in enumerate(payload['frames']):
        frame['joints']['head'][0] += .05 * (-1) ** index
        frame['joints']['pelvis'][1] += .02
    eval_sizes = []

    def force_eval_limit(residual, initial, pattern, max_evaluations):
        # Skip the real LS work: return a corrupted iterate that fails checks
        # with optimizer status=0 so the fit_evaluation_limit path owns the report.
        eval_sizes.append(max_evaluations)
        x = np.asarray(initial, dtype=float).copy()
        x = x + (0.15 if max_evaluations >= 25 else 0.02)
        return SimpleNamespace(x=x, nfev=max_evaluations, status=0)

    monkeypatch.setattr(motion, 'solve_trajectory', force_eval_limit)
    with fit_runtime.candidate_fit_session(tmp_path):
        _, report = motion._fit_controlled_motion(payload, timeout_seconds=180.)
    assert not report.get('applied')
    assert report.get('reason') == 'fit_validation_failed', report
    assert not report.get('evaluationContinuation'), report
    assert (report.get('boundedRefinement') or {}).get('stopReason') in {
        'acceptance_stalled', 'objective_stalled'}, report
    assert report.get('termination') in motion.EVIDENCE_TERMINATIONS, report
    assert not motion.controlled_fit_processing_incomplete(report), report
    # Chunked main solve (5) + at most two short refinement blocks; no full continuation.
    assert eval_sizes and all(size <= 8 for size in eval_sizes), eval_sizes
    assert eval_sizes.count(5) >= 1, eval_sizes
    assert len(eval_sizes) <= 1 + 2 + 3, eval_sizes  # chunks + polish


def test_acceptance_stalled_helpers_match_prod_timeout_signatures():
    assert motion.acceptance_stalled_after_refinement({
        'blocks': [
            {'failedChecks': ['jointRange']},
            {'failedChecks': ['jointRange']},
        ]})
    assert not motion.acceptance_stalled_after_refinement({
        'blocks': [
            {'failedChecks': ['jointRange', 'settling']},
            {'failedChecks': ['jointRange']},
        ]})
    assert motion.refinement_improved_acceptance({
        'initialFailedChecks': ['jointRange', 'settling'],
        'blocks': [{'failedChecks': ['jointRange']}],
    })
    assert not motion.refinement_improved_acceptance({
        'initialFailedChecks': ['jointRange'],
        'blocks': [{'failedChecks': ['jointRange']}],
    })
