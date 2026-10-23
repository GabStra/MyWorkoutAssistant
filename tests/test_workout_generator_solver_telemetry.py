from types import SimpleNamespace

import pytest

from workout_generator_pkg import allocation


def _variables():
    return [{'lower': 0, 'upper': 20, 'current': [3], 'members': [{}]}]


def test_solver_diagnostics_report_termination_incumbent_and_timing(monkeypatch):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=1, message='Time limit reached', x=[3, 0], mip_dual_bound=2.5,
        mip_gap=0.125, mip_node_count=7))
    diagnostics = {}

    status, counts = allocation._milp_solve(_variables(), [], diagnostics=diagnostics)

    assert (status, counts) == ('feasible', [3])
    assert {key: value for key, value in diagnostics.items()
            if key not in ('modelBuildSeconds', 'solveSeconds')} == {
        'terminationStatus': 1, 'terminationMessage': 'Time limit reached',
        'incumbentFound': True, 'incumbentValidated': True,
        'objectiveBound': 2.5, 'relativeGap': 0.125, 'nodeCount': 7,
        'returnReason': 'accepted_feasible'}
    assert diagnostics['modelBuildSeconds'] >= 0
    assert diagnostics['solveSeconds'] >= 0


@pytest.mark.parametrize(('result', 'features', 'expected_status', 'expected_reason', 'validated'), [
    (SimpleNamespace(status=2, message='infeasible', x=None), [], 'infeasible', 'solver_infeasible', False),
    (SimpleNamespace(status=1, message='limit', x=None), [], 'unproven', 'no_incumbent', False),
    (SimpleNamespace(status=3, message='error', x=[3, 0]), [], 'unproven', 'unsupported_solver_status', False),
    (SimpleNamespace(status=1, message='limit', x=[3.5, 0]), [], 'unproven', 'invalid_count_value', False),
    (SimpleNamespace(status=1, message='limit', x=[21, 0]), [], 'unproven', 'count_outside_bounds', False),
    (SimpleNamespace(status=1, message='limit', x=[3, 0]),
     [(('weekly', 'chest'), 4, 5, 0, [1])], 'unproven', 'feature_constraint_violation', False),
])
def test_solver_diagnostics_name_each_rejection(monkeypatch, result, features, expected_status, expected_reason, validated):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: result)
    diagnostics = {}

    status, candidate = allocation._milp_solve(_variables(), features, diagnostics=diagnostics)

    assert status == expected_status
    assert candidate is None
    assert diagnostics['returnReason'] == expected_reason
    assert diagnostics['incumbentFound'] is (result.x is not None)
    assert diagnostics['incumbentValidated'] is validated


def test_empty_variable_domain_is_reported_without_changing_return_shape():
    diagnostics = {}

    assert allocation._milp_solve([], [], diagnostics=diagnostics) == ('optimal', [])

    assert diagnostics == {
        'terminationStatus': None, 'terminationMessage': None,
        'incumbentFound': False, 'incumbentValidated': True,
        'objectiveBound': None, 'relativeGap': None, 'nodeCount': None,
        'modelBuildSeconds': 0.0, 'solveSeconds': 0.0,
        'returnReason': 'empty_variable_domain',
    }


def test_joint_receipt_preserves_solver_diagnostics_and_verified_candidate():
    from test_workout_generator_joint_prescriptions import _distribution_solver_case
    from workout_generator_pkg import joint_planning
    from workout_generator_pkg.alternative_repair import _joint_repair_summary
    equipment, requirements, sessions, _ = _distribution_solver_case([4])
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    assert result['feasible'] and not result['audit']['errors']
    assert result['solverDiagnostics']
    assert result['solverDiagnostics'][0]['goal'] == 'distribution'
    assert result['solverDiagnostics'][0]['incumbentValidated']
    assert result['solverDiagnostics'][0]['terminationStatus'] in (0, 1)
    assert _joint_repair_summary(result)['solverDiagnostics'] == result['solverDiagnostics']
