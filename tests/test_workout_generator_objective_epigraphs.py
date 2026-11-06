from workout_generator_pkg.joint_planning import (_canonicalize_objective_epigraphs,
    _objective_variable_bound)
from workout_generator_pkg import joint_planning
from workout_generator_pkg.cp_solver import SolverSession, _rational, solve
from test_workout_generator_joint_prescriptions import _distribution_solver_case


def test_interacting_group_goal_epigraphs_stay_on_the_verified_cp_lattice():
    import math
    from fractions import Fraction

    import pytest

    variables = [{'lower': 0, 'upper': 2, 'integer': False,
        'objectiveCost': int(index == 2), 'domainIdentity': {'kind': kind}}
        for index, kind in enumerate(('goal_target_miss', 'goal_target_miss', 'goal_tier_peak'))]
    features = [
        (('goal_target_miss', 0), 5701 / 9000, math.inf, 0, {0: 1}),
        (('goal_target_miss', 1), -math.inf, 0, .77, {0: 1 / 300, 1: -1}),
        (('goal_tier_peak', 0), -math.inf, 0, 0, {0: 1, 2: -1}),
        (('goal_tier_peak', 1), -math.inf, 0, 0, {1: 1, 2: -1}),
    ]
    goals = [('goal_tier_0_worst', {2: 1}), ('goal_tier_0_total', {0: .5, 1: .5})]
    session = SolverSession()
    status, candidate = solve(variables, features, session=session)
    assert status == 'optimal' and session.auxiliary_lattice == 9000
    old_values = _canonicalize_objective_epigraphs(variables, features, candidate, goals)
    assert old_values[1] == .7721114814814815
    with pytest.raises(ValueError, match='exact supported rational'):
        joint_planning._exact_objective_value(old_values, goals[1][1])
    values = _canonicalize_objective_epigraphs(variables, features, candidate, goals,
        auxiliary_lattice=session.auxiliary_lattice)
    assert _rational(values[1]) == Fraction(6950, 9000)
    assert all((_rational(value) * session.auxiliary_lattice).denominator == 1 for value in values)
    assert session._validate_candidate(values, variables, features)
    total = joint_planning._exact_objective_value(values, goals[1][1])
    assert total == Fraction(5701 + 6950, 18000)
    next_variables = [{**variable, 'objectiveCost': goals[1][1].get(index, 0)}
        for index, variable in enumerate(variables)]
    locked = [*features, (('prior_goal',), -math.inf, values[2], 0, {2: 1})]
    status, result = solve(next_variables, locked, session=session, incumbent=values)
    assert status == 'optimal' and session._validate_candidate(result, next_variables, locked)


def test_objective_epigraphs_are_tightened_before_stage_scores_are_locked():
    variables = [
        {'lower': 0, 'upper': 10, 'domainIdentity': {'kind': 'recipe_option'}},
        {'lower': 0, 'upper': 10000, 'domainIdentity': {'kind': 'distribution_deviation'}},
        {'lower': 0, 'upper': 10000, 'domainIdentity': {'kind': 'demand_distribution_peak'}},
        {'lower': 0, 'upper': 10000, 'integer': False,
         'domainIdentity': {'kind': 'duration_balance_bound', 'bound': 'maximum'}},
        {'lower': 0, 'upper': 10000, 'integer': False,
         'domainIdentity': {'kind': 'duration_balance_bound', 'bound': 'minimum'}},
        {'lower': 0, 'upper': 10000, 'domainIdentity': {'kind': 'coverage_balance_deviation'}},
        {'lower': 0, 'upper': 10000, 'domainIdentity': {'kind': 'redistribution_peak'}},
        {'lower': 0, 'upper': 1, 'domainIdentity': {'kind': 'first_block_ready'}},
    ]
    features = [
        (('distribution_deviation', 1), -float('inf'), 0, 0, {0: 2, 1: -1}),
        (('distribution_deviation', -1), -float('inf'), 0, 0, {0: -2, 1: -1}),
        (('demand_distribution_peak', 0), -float('inf'), 0, 0, {0: 2, 2: -1}),
        (('duration_balance', 0, 'maximum'), -float('inf'), 0, 3900, {3: -1}),
        (('duration_balance', 0, 'minimum'), -float('inf'), 0, -3900, {4: 1}),
        (('duration_balance', 1, 'maximum'), -float('inf'), 0, 4500, {3: -1}),
        (('duration_balance', 1, 'minimum'), -float('inf'), 0, -4500, {4: 1}),
        (('coverage_balance', 0, -1), -float('inf'), 0, 0, {0: 5, 5: -1}),
        (('coverage_balance', 0, 1), -float('inf'), 0, 0, {0: -5, 5: -1}),
        (('redistribute_peak', 0, 0), -float('inf'), 0, 4, {6: -1}),
        (('redistribute_peak', 0, 1), -float('inf'), 0, 2, {6: -1}),
    ]
    goals = [
        ('distribution', {1: 1}),
        ('demand_distribution', {2: 1}),
        ('duration_balance', {3: 1, 4: -1}),
        ('source_balance', {5: 1}),
        ('redistribution_spread', {6: 1}),
    ]

    tightened = _canonicalize_objective_epigraphs(
        variables, features, [3, 90, 90, 10000, 0, 80, 50, 1], goals)

    assert tightened == [3, 6, 6, 4500, 3900, 15, 4, 1]


def test_narrow_continuous_epigraph_interval_keeps_solver_value_for_full_tolerance_check():
    variables = [{'lower': 0, 'upper': 10, 'integer': False,
                  'domainIdentity': {'kind': 'duration_balance_bound', 'bound': 'maximum'}}]
    features = [
        (('duration_balance', 0, 'maximum'), 1.00000005, float('inf'), 0, {0: 1}),
        (('duration_balance', 1, 'minimum'), -float('inf'), 1, 0, {0: 1}),
    ]

    tightened = _canonicalize_objective_epigraphs(
        variables, features, [1.000000025], [('duration_balance', {0: 1})])

    assert tightened == [1.000000025]


def test_unscored_role_peak_epigraph_is_clamped_to_its_exact_feasible_interval():
    variables = [
        {'lower': 0, 'upper': 10, 'integer': False,
         'domainIdentity': {'kind': 'role_concentration_profile_peak', 'profile': 7}},
        {'lower': 0, 'upper': 10, 'integer': True,
         'domainIdentity': {'kind': 'recipe_option'}},
    ]
    features = [
        (('role_concentration_profile_peak', 7, 'session', 2), -float('inf'), 0, 3,
         {0: -1}),
    ]

    tightened = _canonicalize_objective_epigraphs(
        variables, features, [2.999999898593373, 1], [('distribution', {})])

    assert tightened == [3, 1]


def test_complete_epigraph_row_failure_reports_identity_activity_and_slack():
    variables = [
        {'lower': 0, 'upper': 10, 'integer': False,
         'domainIdentity': {'kind': 'role_concentration_profile_peak'}},
        {'lower': 0, 'upper': 10, 'integer': True,
         'domainIdentity': {'kind': 'recipe_option'}},
    ]
    features = [
        (('role_concentration_profile_peak', 7, 'session', 2), -float('inf'), 0, 3,
         {0: -1}),
        (('hard_test_row', 4), 0, 0, 0, {1: 2}),
    ]

    try:
        _canonicalize_objective_epigraphs(variables, features, [2.999999898593373, 1], [])
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError('A material source-row violation must remain rejected.')

    assert "('hard_test_row', 4)" in message
    assert 'activity=2' in message
    assert 'slack=(2.0, -2.0)' in message


def test_objective_bound_shortcut_requires_a_finite_proven_variable_bound():
    variables = [
        {'lower': 2, 'upper': 8},
        {'lower': 0, 'upper': 5},
    ]
    assert _objective_variable_bound(variables, {0: 3, 1: -2}, offset=4) == 0
    assert _objective_variable_bound(variables, {0: 3}) == 6
    assert _objective_variable_bound([{'lower': 0, 'upper': float('inf')}], {0: -1}) is None


def test_duration_balance_bounds_are_canonicalized_together_on_the_selected_duration_face():
    variables = [
        {'lower': 0, 'upper': 5400, 'integer': False,
         'domainIdentity': {'kind': 'duration_balance_bound', 'bound': 'maximum'}},
        {'lower': 0, 'upper': 5400, 'integer': False,
         'domainIdentity': {'kind': 'duration_balance_bound', 'bound': 'minimum'}},
        {'lower': 0, 'upper': 5400, 'integer': False,
         'domainIdentity': {'kind': 'duration_balance_excess'}},
    ]
    features = [
        (('duration_balance', 0, 'maximum'), -float('inf'), 0, 4912, {0: -1}),
        (('duration_balance', 0, 'minimum'), -float('inf'), 0, -4912, {1: 1}),
        (('duration_balance', 1, 'maximum'), -float('inf'), 0, 4612, {0: -1}),
        (('duration_balance', 1, 'minimum'), -float('inf'), 0, -4612, {1: 1}),
        (('duration_balance', 'tolerance'), -float('inf'), 300, 0, {0: 1, 1: -1, 2: -1}),
    ]

    normalized = _canonicalize_objective_epigraphs(variables, features,
        [4912, 4611.9999952, 0], [('duration_balance', {2: 1})])

    assert normalized == [4912, 4612, 0]


def test_duration_balance_canonicalization_preserves_real_tolerance_excess():
    variables = [
        {'lower': 0, 'upper': 5400, 'integer': False,
         'domainIdentity': {'kind': 'duration_balance_bound', 'bound': 'maximum'}},
        {'lower': 0, 'upper': 5400, 'integer': False,
         'domainIdentity': {'kind': 'duration_balance_bound', 'bound': 'minimum'}},
        {'lower': 0, 'upper': 5400, 'integer': False,
         'domainIdentity': {'kind': 'duration_balance_excess'}},
    ]
    features = [
        (('duration_balance', 0, 'maximum'), -float('inf'), 0, 5000, {0: -1}),
        (('duration_balance', 0, 'minimum'), -float('inf'), 0, -5000, {1: 1}),
        (('duration_balance', 1, 'maximum'), -float('inf'), 0, 4699.5, {0: -1}),
        (('duration_balance', 1, 'minimum'), -float('inf'), 0, -4699.5, {1: 1}),
        (('duration_balance', 'tolerance'), -float('inf'), 300, 0, {0: 1, 1: -1, 2: -1}),
    ]

    normalized = _canonicalize_objective_epigraphs(variables, features,
        [4999.9999952, 4699.5, 0], [('duration_balance', {2: 1})])

    assert normalized == [5000, 4699.5, 0.5]


def test_prior_stage_slack_is_tightened_before_the_next_objective_receives_its_incumbent(monkeypatch):
    equipment, requirements, sessions, _ = _distribution_solver_case([7, 1])
    requirements['objectiveOrder'] = ['duration_balance', 'distribution']
    original = joint_planning._cp_solve
    calls = []

    def bounded(variables, features, **options):
        if not calls:
            status, candidate = original(variables, features, **options)
            assert candidate is not None, status
            for index, variable in enumerate(variables):
                if (variable.get('domainIdentity') or {}).get('kind') == 'distribution_deviation':
                    candidate[index] = variable['upper']
            calls.append(('duration_balance', 'inflated_distribution_slack'))
            return status, candidate
        if options['diagnostics']['goal'] == 'distribution':
            costs = {index: variable['objectiveCost'] for index, variable in enumerate(variables)
                if (variable.get('domainIdentity') or {}).get('kind') == 'distribution_deviation'}
            tightened = _canonicalize_objective_epigraphs(variables, features, options['incumbent'],
                [('distribution', costs)])
            assert tightened == options['incumbent']
            calls.append(('distribution', 'canonical_incumbent'))
        return original(variables, features, **options)

    monkeypatch.setattr(joint_planning, '_cp_solve', bounded)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)

    assert result['feasible'] and result['audit']['errors'] == []
    assert calls == [('duration_balance', 'inflated_distribution_slack'),
                     ('distribution', 'canonical_incumbent')]
    score = next(stage['value'] for stage in result['objectiveProgress'] if stage['goal'] == 'distribution')
    targets = result['audit']['targets']
    muscles = set(targets['weeklyEffectiveSets']) | set(targets['perSessionEffectiveSets'])
    weekly = result['audit']['weeklyVolume']
    expected = sum(abs(2 * requirements['sessionsPerWeek']
        * workout['volume'].get(muscle, {}).get('effective', 0)
        - 2 * weekly.get(muscle, {}).get('effective', 0))
        * workout['timesCompletedInAWeek'] for muscle in muscles
        for workout in result['audit']['workouts'])
    assert score == expected


def test_grouped_metric_slack_does_not_inflate_the_recorded_compromise_score(monkeypatch):
    equipment, requirements, sessions, _ = _distribution_solver_case([7, 1])
    requirements['objectiveOrder'] = ['distribution']
    requirements['objectiveTiers'] = [[{'metric': 'distribution', 'target': 0, 'scale': 1}]]
    original = joint_planning._cp_solve
    calls = []

    def slack_hint(variables, features, **options):
        status, candidate = original(variables, features, **options)
        if not calls:
            assert candidate is not None, status
            for index, variable in enumerate(variables):
                if (variable.get('domainIdentity') or {}).get('kind') in (
                        'distribution_deviation', 'goal_target_miss', 'goal_tier_peak'):
                    candidate[index] = variable['upper']
        calls.append(options['diagnostics']['goal'])
        return 'feasible', candidate

    monkeypatch.setattr(joint_planning, '_cp_solve', slack_hint)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    assert result['feasible'] and not result['audit']['errors'], result
    report = result['audit']
    muscles = set(report['targets']['weeklyEffectiveSets']) | set(report['targets']['perSessionEffectiveSets'])
    expected = sum(abs(2 * requirements['sessionsPerWeek']
        * day['volume'].get(muscle, {}).get('effective', 0)
        - 2 * report['weeklyVolume'].get(muscle, {}).get('effective', 0))
        * day['timesCompletedInAWeek'] for muscle in muscles for day in report['workouts'])
    assert result['objectiveProgress'][0]['value'] == expected
