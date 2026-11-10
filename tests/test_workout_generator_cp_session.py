import math
from fractions import Fraction
from types import SimpleNamespace

import pytest
from ortools.sat.python import cp_model

from workout_generator_pkg.cp_solver import SolverSession, _rational, solve


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


def test_independent_objective_denominators_do_not_refine_the_feasible_lattice():
    variables, features = model()
    variables[0]['objectiveCost'] = 1 / 999983
    session = SolverSession()
    assert session.solve(variables, features)[0] == 'optimal'
    assert session.auxiliary_lattice == 1
    variables[0]['objectiveCost'] = 1 / 999979
    diagnostics = {}
    assert session.solve(variables, features, diagnostics=diagnostics)[0] == 'optimal'
    assert session.auxiliary_lattice == 1 and diagnostics['modelReused']


def test_exact_internal_fractions_preserve_strict_source_float_admission():
    exact = Fraction(155197, 1_224_000)
    assert _rational(exact) is exact
    with pytest.raises(ValueError, match='exact supported rational representation'):
        _rational(0.1 + 0.2)


def test_composed_auxiliary_lattice_preserves_exact_values_and_next_stage_locks():
    from workout_generator_pkg.joint_planning import (
        _canonicalize_objective_epigraphs, _exact_objective_value,
    )

    variables = [{'lower': 0, 'upper': 1, 'integer': False, 'objectiveCost': int(index == 3),
        'domainIdentity': {'kind': 'goal_target_miss'}} for index in range(4)]
    features = [(('component', index), 1 / denominator, math.inf, 0, {index: 1})
        for index, denominator in enumerate((17000, 9, 64))]
    features.append((('combined_miss',), -math.inf, 0, 0, {0: 1, 1: 1, 2: 1, 3: -1}))
    expected = sum((Fraction(1, denominator) for denominator in (17000, 9, 64)), Fraction())
    assert expected.denominator == 1_224_000
    session = SolverSession()
    status, candidate = session.solve(variables, features)
    assert status == 'optimal' and session.auxiliary_lattice == 1_224_000
    assert candidate[3] == expected
    goals = [('total', dict.fromkeys(range(4), 1))]
    canonical = _canonicalize_objective_epigraphs(variables, features, candidate, goals,
        auxiliary_lattice=session.auxiliary_lattice)
    score = _exact_objective_value(canonical, {3: 1})
    assert score == expected
    locked = [*features, (('previous_objective',), -math.inf, score, 0, {3: 1})]
    variables[0]['objectiveCost'], variables[3]['objectiveCost'] = 1, 0
    diagnostics = {}
    status, result = session.solve(variables, locked, incumbent=canonical, diagnostics=diagnostics)
    assert status == 'optimal' and result[3] == expected
    assert session._validate_candidate(result, variables, locked)
    assert diagnostics['modelReused']


def test_exact_model_still_rejects_integer_overflow():
    variables = [{'lower': 0, 'upper': 2 ** 61, 'integer': True, 'objectiveCost': 0}
        for _ in range(2)]
    diagnostics = {}
    status, candidate = solve(variables, [(('overflow',), 0, math.inf, 0, {0: 4, 1: 4})],
        diagnostics=diagnostics)
    assert status == 'unavailable' and candidate is None
    assert diagnostics['returnReason'] == 'unsupported_exact_model'
    assert 'overflow' in diagnostics['terminationMessage'].lower()


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


@pytest.mark.parametrize('kind', ['relative_share', 'relative_exposure_peak'])
def test_exact_full_incumbent_survives_auxiliary_changes_and_a_fresh_session(kind):
    variables = [{'lower': 1, 'upper': 1, 'integer': True, 'objectiveCost': 0,
                  'domainIdentity': {'kind': 'recipe_option'}},
        {'lower': 0, 'upper': 2, 'integer': True, 'objectiveCost': -1,
         'domainIdentity': {'kind': kind}}]
    features = [(('relative',), 0, math.inf, 0, {1: 1, 0: -1})]
    session = SolverSession()
    assert session.solve(variables, features) == ('optimal', [1, 2])
    next_objective = [{**item, 'objectiveCost': int(index == 1)}
                      for index, item in enumerate(variables)]
    for target in (session, SolverSession()):
        diagnostics = {}
        status, candidate = target.solve(next_objective, features, timeout_seconds=0,
            incumbent=[1, 1], diagnostics=diagnostics)
        assert status == 'feasible' and candidate == [1, 1]
        assert diagnostics['incumbentValidated']
        assert diagnostics['returnReason'] == 'model_build_budget_exhausted'


def _circuit_case(selected_edges):
    edges = [(index, index) for index in range(4)] + [(0, 1), (1, 0), (2, 3), (3, 2)]
    variables = [{'lower': 0, 'upper': 1, 'integer': True, 'objectiveCost': 0,
                  'domainIdentity': {'kind': 'execution_arc', 'workoutIndex': 0,
                                     'tail': tail, 'head': head}}
                 for tail, head in edges]
    features = [((direction, vertex), 1, 1, 0,
        {index: 1 for index, edge in enumerate(edges) if edge[side] == vertex})
        for side, direction in enumerate(('outgoing', 'incoming')) for vertex in range(4)]
    return variables, features, [int(edge in selected_edges) for edge in edges]


def test_full_incumbent_rejects_disjoint_cycles_that_satisfy_all_linear_rows():
    variables, features, incumbent = _circuit_case({(0, 1), (1, 0), (2, 3), (3, 2)})
    assert all(sum(incumbent[index] * cost for index, cost in row[4].items()) == 1
               for row in features)
    session = SolverSession()
    session._prepare(variables, features, cp_model)
    assert not session._validate_candidate(incumbent, variables, features)
    status, candidate = session.solve(variables, features, timeout_seconds=0, incumbent=incumbent)
    assert status == 'unproven' and candidate is None


@pytest.mark.parametrize('case', ['cycle_with_unused', 'all_unused', 'missing_vertex',
                                 'fractional_arc', 'hard_row'])
def test_full_incumbent_checks_circuit_coverage_integer_grid_and_hard_rows(case):
    selected = ({(vertex, vertex) for vertex in range(4)} if case == 'all_unused'
                else {(0, 1), (1, 0), (2, 2), (3, 3)})
    variables, features, incumbent = _circuit_case(selected)
    if case == 'missing_vertex':
        incumbent[3] = 0
    elif case == 'fractional_arc':
        incumbent[4] = 0.5
    elif case == 'hard_row':
        features.append((('hard_limit',), 0, 0, 0, {4: 1}))
    status, candidate = solve(variables, features, timeout_seconds=0, incumbent=incumbent)
    if case in ('cycle_with_unused', 'all_unused'):
        assert status == 'feasible' and candidate == incumbent
    else:
        assert status == 'unproven' and candidate is None
