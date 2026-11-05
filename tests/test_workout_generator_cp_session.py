import math
from types import SimpleNamespace

import pytest
from ortools.sat.python import cp_model

from workout_generator_pkg.cp_solver import SolverSession, solve


def model():
    variables = [{'lower': 0, 'upper': 4, 'integer': True, 'objectiveCost': 1},
        {'lower': 0, 'upper': 4, 'integer': True, 'objectiveCost': 0}]
    return variables, [(('dose',), 3, math.inf, 0, {0: 1, 1: 1})]


def test_session_appends_locks_and_rebuilds_changed_bounds_without_stale_constraints():
    variables, features = model()
    session = SolverSession()
    assert solve(variables, features, session=session)[0] == 'optimal'
    locked = [*features, (('previous_objective',), -math.inf, 0, 0, {0: 1})]
    changed_objective = [{**variables[0], 'objectiveCost': 0}, {**variables[1], 'objectiveCost': 1}]
    diagnostics = {}
    status, candidate = solve(changed_objective, locked, session=session, diagnostics=diagnostics)
    assert status == 'optimal' and candidate == [0, 3]
    assert diagnostics['modelReused'] and diagnostics['appendedLinearConstraintCount'] == 1
    changed_bounds = [changed_objective[0], {**changed_objective[1], 'upper': 0}]
    diagnostics = {}
    status, candidate = solve(changed_bounds, features, session=session, diagnostics=diagnostics)
    assert status == 'optimal' and candidate[0] >= 3 and candidate[1] == 0
    assert not diagnostics['modelReused']


def test_changed_feature_prefix_rebuilds_same_variable_context():
    variables, features = model()
    session = SolverSession()
    solve(variables, features, session=session)
    diagnostics = {}
    status, candidate = solve(variables, [(('dose',), 8, 8, 0, {0: 1, 1: 1})],
        session=session, diagnostics=diagnostics)
    assert status == 'optimal' and candidate == [4, 4]
    assert not diagnostics['modelReused']


def test_partial_hint_completion_is_verified_and_unknown_search_retains_feasible_candidate(monkeypatch):
    variables, features = model()
    real_solver = cp_model.CpSolver

    class UnknownSearch:
        parameters = SimpleNamespace()
        best_objective_bound = 0

        def solve(self, model):
            assert not getattr(self.parameters, 'fix_variables_to_their_hinted_value', False)
            return cp_model.UNKNOWN

        def status_name(self, status):
            return 'UNKNOWN'

    solvers = iter([real_solver(), UnknownSearch()])
    monkeypatch.setattr(cp_model, 'CpSolver', lambda: next(solvers))
    diagnostics = {}
    status, candidate = solve(variables, features, incumbent={0: 1}, diagnostics=diagnostics)
    assert status == 'feasible' and candidate[0] == 1 and sum(candidate) >= 3
    assert diagnostics['incumbentSource'] == 'cp_verified_hint_completion'
    assert diagnostics['hintCompletionBudgetSeconds'] <= 5
    assert diagnostics['searchBudgetSeconds'] < diagnostics['requestedBudgetSeconds']


def test_infeasible_partial_hint_does_not_freeze_the_unrestricted_search():
    variables, features = model()
    diagnostics = {}
    status, candidate = solve(variables, features, incumbent={0: 0, 1: 0}, diagnostics=diagnostics)
    assert status == 'optimal' and candidate[0] == 0 and candidate[1] >= 3
    assert diagnostics['hintCompletionStatus'] == 'INFEASIBLE'


@pytest.mark.parametrize(('cost', 'hint', 'bound'), [(1, 0, 0), (-0.5, 3, -1.5)])
def test_verified_hint_matching_exact_domain_bound_skips_unrestricted_search(monkeypatch, cost, hint, bound):
    variables, features = model()
    variables[0].update(upper=3, objectiveCost=cost)
    real_solver = cp_model.CpSolver
    calls = []

    def completion_only():
        assert not calls, 'A verified bound witness must skip unrestricted search.'
        calls.append(True)
        return real_solver()

    monkeypatch.setattr(cp_model, 'CpSolver', completion_only)
    diagnostics = {}
    status, candidate = solve(variables, features, incumbent={0: hint}, diagnostics=diagnostics)
    assert status == 'optimal' and candidate[0] == hint
    assert diagnostics['objectiveBound'] == diagnostics['objectiveValue'] == bound
    assert diagnostics['incumbentSource'] == 'cp_verified_hint_completion'
    assert diagnostics['boundWitness'] == 'verified_incumbent_matches_exact_variable_domain_lower_bound'
    assert diagnostics['searchBudgetSeconds'] == 0
