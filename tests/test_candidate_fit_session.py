import json
from pathlib import Path
from time import monotonic

import numpy as np

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg import anatomical_repair as anatomy
from exercise_motion_pkg import fit_runtime


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


def test_cpu_queue_wait_preserves_remaining_candidate_budget(monkeypatch):
    from contextlib import contextmanager
    now = [0.]
    monkeypatch.setattr(fit_runtime, 'monotonic', lambda: now[0])

    @contextmanager
    def queued_lock():
        now[0] += 20.
        yield

    monkeypatch.setattr(fit_runtime, '_CPU_FIT_LOCK', queued_lock())
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
