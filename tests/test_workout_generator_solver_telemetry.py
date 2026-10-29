from types import SimpleNamespace

import pytest

from workout_generator_pkg import allocation


def _variables():
    return [{'lower': 0, 'upper': 20, 'current': [3], 'members': [{}]}]


def _count_series(counts=(2, 3, 4), *, cover=True, nonaffine=False):
    variables = [{'lower': 0, 'upper': 1, 'current': [], 'members': [],
        'objectiveCost': count, 'countSeriesKey': 'recipe/rest', 'countSeriesValue': count}
        for count in counts]
    features = []
    if cover:
        features.append((('one_option',), 0, 1, 0, {index: 1 for index in range(len(counts))}))
    features.append((('minimum_count',), 3, 10, 0,
        {index: count for index, count in enumerate(counts)}))
    if nonaffine:
        features.append((('nonaffine',), 0, 1, 0, {index: int(index == 1) for index in range(len(counts))}))
    return variables, features


def test_solver_diagnostics_report_termination_incumbent_and_timing(monkeypatch):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=1, message='Time limit reached', x=[3, 0], mip_dual_bound=2.5,
        mip_gap=0.125, mip_node_count=7))
    diagnostics = {}

    status, counts = allocation._milp_solve(_variables(), [], diagnostics=diagnostics)

    assert (status, counts) == ('feasible', [3])
    assert {key: value for key, value in diagnostics.items()
            if key not in ('modelBuildSeconds', 'modelAssemblySeconds',
                           'countSeriesCompileSeconds', 'solveSeconds')} == {
        'terminationStatus': 1, 'terminationMessage': 'Time limit reached',
        'incumbentFound': True, 'incumbentValidated': True,
        'objectiveBound': 2.5, 'relativeGap': 0.125, 'nodeCount': 7,
        'returnReason': 'accepted_feasible'}
    assert diagnostics['modelBuildSeconds'] >= 0
    assert diagnostics['modelAssemblySeconds'] >= 0
    assert diagnostics['countSeriesCompileSeconds'] >= 0
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


def test_solver_records_first_original_row_identity_value_and_slack(monkeypatch):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=0, message='Optimal', x=[3, 0], mip_dual_bound=0, mip_gap=0, mip_node_count=1))
    diagnostics = {}
    features = [
        (('weekly', 'chest'), 4, 5, 0, {0: 1}),
        (('weekly', 'back'), 8, 9, 0, {0: 1}),
    ]

    status, candidate = allocation._milp_solve(_variables(), features, diagnostics=diagnostics)

    assert (status, candidate) == ('unproven', None)
    assert diagnostics['returnReason'] == 'feature_constraint_violation'
    assert diagnostics['rejectedRow'] == {
        'index': 0, 'identity': ('weekly', 'chest'), 'value': 3.0,
        'lower': 4.0, 'upper': 5.0, 'slack': -1.0, 'violation': 1.0}


@pytest.mark.parametrize(('peak', 'expected_status'), [
    (2.999999898593373, 'optimal'),
    (2.999998, 'unproven'),
])
def test_solver_accepts_only_feasibility_scale_epigraph_noise(monkeypatch, peak, expected_status):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=0, message='Optimal', x=[1, 1, 1, 1, 1, peak], mip_dual_bound=0,
        mip_gap=0, mip_node_count=1))
    diagnostics = {}
    variables = [{'lower': 1, 'upper': 1, 'current': [], 'members': []} for _ in range(5)]
    variables.append({'lower': 0, 'upper': 10, 'integer': False,
                      'current': [], 'members': [],
                      'domainIdentity': {'kind': 'role_concentration_profile_peak'}})
    feature = ('role_concentration_profile_peak', 7, 'session', 2)
    features = [(feature, -float('inf'), 0, 0, {0: 8, 1: 4, 2: -4, 3: -2, 4: -3, 5: -1})]

    status, candidate = allocation._milp_solve(variables, features,
        preserve_current=False, diagnostics=diagnostics)

    assert status == expected_status
    if expected_status == 'optimal':
        assert candidate is not None
        assert diagnostics['incumbentValidated']
        assert 'rejectedRow' not in diagnostics
    else:
        assert candidate is None
        assert diagnostics['returnReason'] == 'feature_constraint_violation'
        assert diagnostics['rejectedRow']['identity'] == feature
        assert diagnostics['rejectedRow']['value'] == pytest.approx(2e-6)
        assert diagnostics['rejectedRow']['slack'] == pytest.approx(-2e-6)


def test_continuous_bound_noise_is_snapped_before_selected_minimum_validation(monkeypatch):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=1, message='Time limit reached', x=[-1e-10, 0, 0], mip_dual_bound=0,
        mip_gap=0, mip_node_count=1))
    diagnostics = {}
    variables = [{'lower': 0, 'upper': 3, 'integer': False, 'minimumWhenSelected': 2,
                  'current': [0], 'domainIdentity': {'kind': 'exercise', 'id': 'EXERCISE_A'},
                  'members': [{'slotId': '/sessions/0/exercises/0'}]}]

    status, counts = allocation._milp_solve(variables, [], diagnostics=diagnostics)

    assert (status, counts) == ('feasible', [0])
    assert diagnostics['incumbentValidated']
    assert diagnostics['returnReason'] == 'accepted_feasible'


def test_continuous_bound_noise_is_canonicalized_before_original_row_check(monkeypatch):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=0, message='Optimal', x=[2.0000005], mip_dual_bound=0, mip_gap=0, mip_node_count=1))
    diagnostics = {}
    variables = [{'lower': 0, 'upper': 2, 'integer': False,
                  'current': [], 'members': [], 'domainIdentity': {'kind': 'continuous_test'}}]
    features = [(('upper_limit',), -float('inf'), 2, 0, {0: 1})]

    status, values = allocation._milp_solve(variables, features, preserve_current=False,
        diagnostics=diagnostics)

    assert (status, values) == ('optimal', [2])
    assert diagnostics['incumbentValidated']
    assert 'rejectedRow' not in diagnostics


@pytest.mark.parametrize(('solver_value', 'expected'), [(1.9999995, ('optimal', [2])),
                                                        (1.999998, ('unproven', None))])
def test_continuous_selected_minimum_noise_is_snapped_but_real_shortfall_is_rejected(
        monkeypatch, solver_value, expected):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=0, message='Optimal', x=[solver_value, 1], mip_dual_bound=0, mip_gap=0, mip_node_count=1))
    diagnostics = {}
    variables = [{'lower': 0, 'upper': 3, 'integer': False, 'minimumWhenSelected': 2,
                  'current': [], 'members': [], 'domainIdentity': {'kind': 'continuous_selected'}}]

    status, counts = allocation._milp_solve(variables, [], preserve_current=False,
        diagnostics=diagnostics)

    assert (status, counts) == expected
    if solver_value < 2 - allocation._MILP_SOLUTION_TOLERANCE:
        assert diagnostics['returnReason'] == 'count_outside_bounds'


def test_integer_milp_solution_noise_is_snapped_within_solver_tolerance(monkeypatch):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=0, message='Optimal', x=[3.0000002], mip_dual_bound=0, mip_gap=0, mip_node_count=1))
    diagnostics = {}
    variables = [{'lower': 0, 'upper': 5, 'current': [], 'members': []}]

    status, counts = allocation._milp_solve(variables, [], preserve_current=False,
        diagnostics=diagnostics)

    assert (status, counts) == ('optimal', [3])
    assert type(counts[0]) is int
    assert diagnostics['incumbentValidated']


def test_integer_milp_solution_noise_outside_solver_tolerance_is_rejected(monkeypatch):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=0, message='Optimal', x=[3.000002], mip_dual_bound=0, mip_gap=0, mip_node_count=1))
    diagnostics = {}
    variables = [{'lower': 0, 'upper': 5, 'current': [], 'members': []}]

    status, counts = allocation._milp_solve(variables, [], preserve_current=False,
        diagnostics=diagnostics)

    assert (status, counts) == ('unproven', None)
    assert diagnostics['returnReason'] == 'invalid_count_value'


def test_auxiliary_variable_bound_noise_is_rejected_with_identity(monkeypatch):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=0, message='Optimal', x=[3, -2e-6], mip_dual_bound=0, mip_gap=0, mip_node_count=1))
    diagnostics = {}
    variables = [{'lower': 0, 'upper': 5, 'current': [3], 'members': [{'slotId': '/exercise/0'}]}]

    status, candidate = allocation._milp_solve(variables, [], diagnostics=diagnostics)

    assert (status, candidate) == ('unproven', None)
    assert diagnostics['returnReason'] == 'variable_outside_bounds'
    assert diagnostics['rejectedVariable']['identity'] == {
        'kind': 'preservation_deviation', 'variableIndex': 0,
        'slotId': '/exercise/0', 'memberIndex': 0}


def test_rejected_count_diagnostic_keeps_variable_identity_and_bounds(monkeypatch):
    monkeypatch.setattr(allocation, 'milp', lambda *args, **kwargs: SimpleNamespace(
        status=1, message='Time limit reached', x=[21, 0], mip_dual_bound=0,
        mip_gap=0, mip_node_count=1))
    diagnostics = {}
    variables = [{**_variables()[0], 'domainIdentity': {'kind': 'exercise', 'id': 'EXERCISE_A'},
                  'members': [{'slotId': '/sessions/0/exercises/0'}]}]

    status, candidate = allocation._milp_solve(variables, [], diagnostics=diagnostics)

    assert (status, candidate) == ('unproven', None)
    assert diagnostics['rejectedVariable'] == {
        'index': 0, 'identity': {'kind': 'exercise', 'id': 'EXERCISE_A'},
        'slotIds': ['/sessions/0/exercises/0'], 'value': 21.0, 'lower': 0.0,
        'upper': 20.0, 'minimumWhenSelected': 0.0}


def test_empty_variable_domain_is_reported_without_changing_return_shape():
    diagnostics = {}

    assert allocation._milp_solve([], [], diagnostics=diagnostics) == ('optimal', [])

    assert diagnostics == {
        'terminationStatus': None, 'terminationMessage': None,
        'incumbentFound': False, 'incumbentValidated': True,
        'objectiveBound': None, 'relativeGap': None, 'nodeCount': None,
        'modelBuildSeconds': 0.0, 'modelAssemblySeconds': 0.0,
        'countSeriesCompileSeconds': 0.0, 'solveSeconds': 0.0,
        'returnReason': 'empty_variable_domain',
    }


def test_sparse_row_builder_preserves_constraint_matrix():
    from scipy.sparse import lil_matrix

    rows = [{0: 2, 3: -1}, {}, {1: 0.5, 2: 0}]
    expected = lil_matrix((len(rows), 4), dtype=float)
    for row_index, row in enumerate(rows):
        for column, value in row.items():
            if value:
                expected[row_index, column] = value

    actual = allocation._csr_matrix_from_rows(rows, 4)

    assert actual.shape == (3, 4)
    assert (actual != expected.tocsr()).nnz == 0


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


def test_count_series_compiler_preserves_enumerated_one_hot_solution():
    import numpy as np
    from scipy.optimize import LinearConstraint
    from scipy.sparse import lil_matrix

    variables, features = _count_series()
    original_objective = [item['objectiveCost'] for item in variables]
    original_matrix = lil_matrix((len(features), len(variables)), dtype=float)
    lows, highs = [], []
    for row, (_, lower, upper, intercept, coefficients) in enumerate(features):
        for column, value in coefficients.items():
            original_matrix[row, column] = value
        lows.append(lower - intercept); highs.append(upper - intercept)
    original_matrix = original_matrix.tocsr()
    compiled = allocation._compile_count_series(original_objective, [1] * 3, [0] * 3, [1] * 3,
        LinearConstraint(original_matrix, lows, highs), lows, highs, None, variables, 3)
    assert compiled is not None
    reduced_matrix = compiled['constraints'].A.tocsr()
    states = [([0, 0, 0], [0, 0])]
    states.extend(([int(index == selected) for index in range(3)], [1, count])
        for selected, count in enumerate((2, 3, 4)))
    for original, reduced in states:
        assert np.dot(original_objective, original) == pytest.approx(np.dot(compiled['objective'], reduced))
        assert (original_matrix @ original).tolist() == pytest.approx((reduced_matrix[:len(features)] @ reduced).tolist())
        assert compiled['restore'](reduced) == pytest.approx(original)

    diagnostics = {}

    status, counts = allocation._milp_solve(variables, features, preserve_current=False,
        diagnostics=diagnostics)

    assert (status, counts) == ('optimal', [0, 1, 0])
    assert diagnostics['countSeriesCompressed']
    assert diagnostics['countSeriesInputColumns'] == 3
    assert diagnostics['countSeriesSolverColumns'] == 2


@pytest.mark.parametrize('values', [
    [0, 0, 0, 0],
    [0, 2, 4, 6],
    [1, 3, 5, 7],
    [1, 0, 1, 0],
    [0, 1e-11, 2e-11, 3e-11],
    [0, 1e-9, 2e-9, 3e-9],
])
def test_sparse_count_series_affine_proof_matches_dense_proof(values):
    counts = [2, 3, 4, 5]
    sparse_values = {index: value for index, value in enumerate(values) if value}

    dense_result = allocation._count_series_affine(values, counts)
    sparse_result = allocation._count_series_affine_sparse(sparse_values, counts)

    if dense_result is None:
        assert sparse_result is None
    else:
        assert sparse_result == pytest.approx(dense_result)


def test_count_series_compiler_maps_warm_start_and_restores_original_columns(monkeypatch):
    variables, features = _count_series()
    captured = {}

    def return_start(objective, integrality, bounds, constraints, options, initial_values):
        captured['initialValues'] = initial_values
        return SimpleNamespace(status=0, message='Optimal', x=initial_values,
            mip_dual_bound=3, mip_gap=0, mip_node_count=0)

    monkeypatch.setattr(allocation, '_milp_with_incumbent', return_start)
    diagnostics = {}
    status, counts = allocation._milp_solve(variables, features, preserve_current=False,
        incumbent=[0, 1, 0], diagnostics=diagnostics)

    assert captured['initialValues'] == [1, 3]
    assert (status, counts) == ('optimal', [0, 1, 0])
    assert diagnostics['countSeriesCompressed']
    assert diagnostics['incumbentSupplied'] and diagnostics['incumbentValidated']


def test_count_series_restore_snaps_solver_integrality_noise_and_rechecks_original_rows(monkeypatch):
    variables, features = _count_series()
    monkeypatch.setattr(allocation, '_milp_with_incumbent', lambda *args: SimpleNamespace(
        status=0, message='Optimal', x=[1.0, 2.9999998], mip_dual_bound=3,
        mip_gap=0, mip_node_count=0))
    diagnostics = {}

    status, counts = allocation._milp_solve(variables, features, preserve_current=False,
        incumbent=[0, 1, 0], diagnostics=diagnostics)

    assert (status, counts) == ('optimal', [0, 1, 0])
    assert diagnostics['countSeriesCompressed']
    assert diagnostics['incumbentValidated']


def test_count_series_restore_rejects_values_outside_solver_integrality_noise(monkeypatch):
    variables, features = _count_series()
    monkeypatch.setattr(allocation, '_milp_with_incumbent', lambda *args: SimpleNamespace(
        status=0, message='Optimal', x=[1.0, 2.999998], mip_dual_bound=3,
        mip_gap=0, mip_node_count=0))
    diagnostics = {}

    status, counts = allocation._milp_solve(variables, features, preserve_current=False,
        incumbent=[0, 1, 0], diagnostics=diagnostics)

    assert (status, counts) == ('unproven', None)
    assert diagnostics['countSeriesReconstructionFailed']


def test_count_series_requires_nonnegative_bounds_on_other_choice_row_columns():
    from scipy.optimize import LinearConstraint
    from scipy.sparse import lil_matrix

    variables, features = _count_series()
    variables.append({'lower': -1, 'upper': 1, 'current': [], 'members': [], 'objectiveCost': 0})
    features[0] = (features[0][0], 0, 1, 0, {0: 1, 1: 1, 2: 1, 3: 1})
    matrix = lil_matrix((len(features), len(variables)), dtype=float)
    lows, highs = [], []
    for row, (_, lower, upper, intercept, coefficients) in enumerate(features):
        for column, value in coefficients.items():
            matrix[row, column] = value
        lows.append(lower - intercept); highs.append(upper - intercept)

    compiled = allocation._compile_count_series(
        [item['objectiveCost'] for item in variables], [1] * 4,
        [item['lower'] for item in variables], [item['upper'] for item in variables],
        LinearConstraint(matrix.tocsr(), lows, highs), lows, highs, None, variables, 4)

    assert compiled is None


@pytest.mark.parametrize(('counts', 'cover', 'nonaffine'), [
    ((2, 3, 4), True, True),
    ((2, 4, 5), True, False),
    ((2, 3, 4), False, False),
])
def test_count_series_compiler_falls_back_without_a_proven_affine_choice_series(
        counts, cover, nonaffine):
    variables, features = _count_series(counts, cover=cover, nonaffine=nonaffine)
    diagnostics = {}

    status, candidate = allocation._milp_solve(variables, features,
        preserve_current=False, diagnostics=diagnostics)

    assert status == 'optimal'
    assert candidate is not None
    assert 'countSeriesCompressed' not in diagnostics
