from workout_generator_pkg.joint_planning import _canonicalize_objective_epigraphs
from workout_generator_pkg import joint_planning
from test_workout_generator_joint_prescriptions import _distribution_solver_case


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


def test_prior_stage_slack_is_tightened_before_the_next_objective_receives_its_incumbent(monkeypatch):
    equipment, requirements, sessions, _ = _distribution_solver_case([7, 1])
    requirements['objectiveOrder'] = ['duration_balance', 'distribution']
    original = joint_planning._milp_solve
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

    monkeypatch.setattr(joint_planning, '_milp_solve', bounded)
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
