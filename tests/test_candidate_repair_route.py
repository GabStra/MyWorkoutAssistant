"""Boundary regression for the separate production candidate-repair route."""

import ast
import copy
import inspect
import textwrap


def _candidate():
    return {
        'fps': 30.,
        'jointNames': ['pelvis'],
        'frames': [
            {'timeSec': 0., 'sourceTimeSec': 0., 'joints': {'pelvis': [0., 1., 0.]}},
            {'timeSec': 1. / 30., 'sourceTimeSec': 1. / 30.,
             'joints': {'pelvis': [0., 1.01, 0.]}},
        ],
        'fixedRig': {'coordinates': [[0., 1., 0.], [0., 1.01, 0.]],
                     'jointNames': ['pelvis']},
        'loop': {'enabled': False},
        'sourcePoseCameraReference': {'camera': {'id': 'candidate-camera'}},
        'sourceFootSupportEvidence': {'sourceVideoSha256': 'candidate-source'},
        'controlledMotionFit': {'applied': True, 'validationOnly': True},
    }


def test_immutable_validation_never_requests_candidate_repair(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    candidate = _candidate()
    frozen = copy.deepcopy(candidate)
    payload = copy.deepcopy(candidate)
    seen = {}
    report = {
        'applied': True,
        'validationOnly': True,
        'checks': dict.fromkeys(motion.REQUIRED_FIT_CHECKS, True),
    }

    def validated_fit(actual_payload, **kwargs):
        seen.update(kwargs)
        return copy.deepcopy(payload), copy.deepcopy(report)

    monkeypatch.setattr(motion, 'fit_controlled_motion', validated_fit)

    _, receipt = motion.validate_controlled_motion_candidate(payload, candidate)

    assert seen['max_evaluations'] == 0
    assert seen['_validation_candidate'] == frozen
    assert seen.get('_candidate_repair', False) is False
    assert candidate == frozen
    # The wrapper keeps measuring through the immutable path; it never opts
    # into the repair mode.
    assert receipt['validationOnly'] is True


def test_repair_route_binds_changed_proposal_and_clears_immutable_receipts(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    candidate = _candidate()
    frozen_candidate = copy.deepcopy(candidate)
    payload = copy.deepcopy(candidate)
    frozen_payload = copy.deepcopy(payload)
    repaired = copy.deepcopy(candidate)
    repaired['frames'][1]['joints']['pelvis'][1] = 1.02
    repaired['fixedRig']['coordinates'][1][1] = 1.02
    seen = {}
    report = {
        'applied': True,
        'validationOnly': True,
        'immutableCandidateUnchanged': True,
        'immutableCandidatePreservation': {'passed': True},
        'checks': dict.fromkeys(motion.REQUIRED_FIT_CHECKS, True),
        'candidateRepair': {
            'requested': True,
            'initialMeasurement': {'failedChecks': ['jerk']},
            'restoration': {'attempted': True, 'applied': True},
        },
    }

    def repaired_fit(actual_payload, **kwargs):
        seen.update(kwargs)
        return copy.deepcopy(repaired), copy.deepcopy(report)

    monkeypatch.setattr(motion, 'fit_controlled_motion', repaired_fit)

    result, receipt = motion.repair_controlled_motion_candidate(
        payload, candidate, timeout_seconds=120.)

    assert seen['max_evaluations'] == 0
    assert seen['_candidate_repair'] is True
    assert seen['_validation_candidate'] == frozen_candidate
    assert candidate == frozen_candidate
    assert payload == frozen_payload
    assert result == repaired
    assert 'immutableCandidateUnchanged' not in receipt
    assert 'immutableCandidatePreservation' not in receipt
    assert receipt['validationOnly'] is False
    assert receipt['candidateRepair']['geometryChanged'] is True
    assert receipt['candidateRepair']['resultBinding'] == 'measured_candidate'
    assert receipt['candidateRepair']['inputPoseDigest'] == motion.pose_digest(
        frozen_candidate)
    assert receipt['candidateRepair']['outputPoseDigest'] == motion.pose_digest(
        repaired)
    assert receipt['candidateRepair']['restoration']['applied'] is True


def test_repair_route_keeps_submitted_candidate_when_payload_blocked(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    candidate = _candidate()
    payload = copy.deepcopy(candidate)
    monkeypatch.setattr(
        motion, 'fit_controlled_motion',
        lambda *args, **kwargs: (
            payload, {'applied': False,
                      'reason': 'source_support_validation_unresolved'}))

    result, receipt = motion.repair_controlled_motion_candidate(payload, candidate)

    assert result == candidate
    assert receipt['candidateRepair']['resultBinding'] == (
        'submitted_candidate_before_measurement')
    assert receipt['applied'] is False


def test_repair_branch_uses_constrained_restoration_not_global_fit():
    from exercise_motion_pkg import controlled_motion as motion

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(motion._fit_controlled_motion_impl)))
    branch = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == 'validation_candidate'):
            continue
        if any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == 'validate_solution'
                and any(keyword.arg == 'allow_repairs'
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is False
                        for keyword in call.keywords)
                for call in ast.walk(node)):
            branch = node
            break
    assert branch is not None

    called = {
        call.func.id
        for call in ast.walk(branch)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert 'restore_temporal_gates_in_key_pin_tangent_space' in called
    assert 'solve_trajectory' not in called
    assert 'trajectory_solver' not in called
    assert any(
        isinstance(node, ast.If)
        and (
            (isinstance(node.test, ast.UnaryOp)
             and isinstance(node.test.op, ast.Not)
             and isinstance(node.test.operand, ast.Name)
             and node.test.operand.id == 'candidate_repair')
            or (isinstance(node.test, ast.Name)
                and node.test.id == 'candidate_repair')
        )
        for node in ast.walk(branch)
    )
