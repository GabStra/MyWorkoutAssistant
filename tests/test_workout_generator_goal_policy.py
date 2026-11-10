import copy
from fractions import Fraction

import pytest
from jsonschema import validate

from workout_generator_pkg import joint_planning as joint
from workout_generator_pkg.planning_tools import _REQUIREMENTS
from workout_generator_pkg.programming_policy import (
    goal_programming_costs, goal_total_weights, programming_policy_errors,
    assess_audited_programming_tradeoff,
)


def test_group_means_remove_field_count_weight_without_changing_worst_or_legacy_goals():
    def score(muscle_count):
        tier = [{'metric': f'weekly_volume:muscle_{index}', 'target': 0, 'scale': 1,
            'group': 'muscle_volume'} for index in range(muscle_count)] + [
            {'metric': 'setup_economy', 'target': 0, 'scale': 1, 'group': 'practical_execution'},
            {'metric': 'movement_overlap', 'target': 0, 'scale': 1}]
        assert goal_total_weights(tier) == [Fraction(1, muscle_count)] * muscle_count + [1, 1]
        costs = {goal['metric']: .75 for goal in tier[:-2]}
        costs.update(setup_economy=.5, movement_overlap=.25)
        return goal_programming_costs({'objectiveTiers': [tier]}, costs, {})

    assert score(1) == score(20) == {'goal_tier_0_worst': .75, 'goal_tier_0_total': 1.5}
    legacy = [{'metric': 'setup_economy', 'target': 0, 'scale': 1},
        {'metric': 'movement_overlap', 'target': 0, 'scale': 1}]
    assert goal_programming_costs({'objectiveTiers': [legacy]},
        {'setup_economy': .5, 'movement_overlap': .25}, {}) == {
            'goal_tier_0_worst': .5, 'goal_tier_0_total': .75}


@pytest.mark.parametrize('aggregation,expected', [(None, 1), ('worst_then_total', 1), ('total_then_worst', 0)])
def test_approved_aggregation_ranks_the_same_feasible_choices_in_solver_and_comparison(aggregation, expected):
    from workout_generator_pkg.cp_solver import solve
    from workout_generator_pkg.programming_policy import goal_tier_names, normalize_programming_policy

    requirements = {'objectiveOrder': ['volume_target', 'setup_economy'], 'objectiveTiers': [[
        {'metric': 'volume_target', 'target': 0, 'scale': 1},
        {'metric': 'setup_economy', 'target': 0, 'scale': 1}]]}
    if aggregation:
        requirements['goalAggregation'] = aggregation
        assert normalize_programming_policy(requirements)['goalAggregation'] == aggregation
    # A has better combined quality (.6 versus .8); B has a better worst miss (.4 versus .6).
    profiles = {'volume_target': [.6, .4], 'setup_economy': [0, .4]}
    variables = [{'lower': 0, 'upper': 1, 'integer': True} for _ in range(2)]
    rows = [(('choose_one',), 1, 1, 0, {0: 1, 1: 1})]

    def variable(**kwargs):
        index = len(variables)
        variables.append({'lower': kwargs.get('lower', 0), 'upper': kwargs['upper'],
            'integer': kwargs['integer'], 'domainIdentity': kwargs['domain_identity']})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        rows.append((label, lower, upper, intercept, coefficients))

    stages = joint._goal_programming_objectives(variable, constraint, variables, requirements,
        {name: dict(enumerate(values)) for name, values in profiles.items()}, {})
    assert [name for name, _ in stages] == goal_tier_names(requirements)
    for name, costs in stages:
        status, chosen = solve([{**v, 'objectiveCost': costs.get(i, 0)}
            for i, v in enumerate(variables)], rows, timeout_seconds=5)
        assert status == 'optimal'
        assert chosen[expected] == 1
        score = sum(chosen[i] * cost for i, cost in costs.items())
        rows.append((('attained', name), -float('inf'), score, 0, costs))
    before = {name: values[0] for name, values in profiles.items()}
    after = {name: values[1] for name, values in profiles.items()}
    before.update(goal_programming_costs(requirements, before, {}))
    after.update(goal_programming_costs(requirements, after, {}))
    compared = assess_audited_programming_tradeoff({'audit': {'errors': []}}, {'audit': {'errors': []}},
        requirements=requirements, baseline_costs=before, candidate_costs=after,
        objective_names=requirements['objectiveOrder'], same_selected_work=False)
    assert compared['status'] == ('baseline_preferred' if expected == 0 else 'candidate_preferred')


def test_approved_cost_goals_reward_improvement_without_duration_similarity_dominating():
    from pathlib import Path
    import json

    approved = json.loads(Path('docs/workout_generator_initial_requirements.json').read_text(encoding='utf-8'))
    costs = {'setup_economy': 37, 'exercise_count': 3, 'movement_overlap': 1, 'duration_balance': 312}
    tier = [goal for source_tier in approved['objectiveTiers'] for goal in source_tier
        if goal['metric'] in {'setup_economy', 'exercise_count', 'movement_overlap'}]
    requirements = {'objectiveTiers': [tier]}
    baseline = goal_programming_costs(requirements, costs, {})
    improved = goal_programming_costs(requirements,
        {**costs, 'setup_economy': 30, 'exercise_count': 0, 'movement_overlap': 0}, {})
    assert baseline['goal_tier_0_worst'] > improved['goal_tier_0_worst']
    assert improved['goal_tier_0_total'] < baseline['goal_tier_0_total']
    balanced = goal_programming_costs(requirements, {**costs, 'duration_balance': 0}, {})
    assert balanced == baseline


def test_joint_selection_setup_and_exposure_choose_a_compromise_before_single_metric_extremes():
    from pathlib import Path
    import json
    from workout_generator_pkg.cp_solver import solve

    approved = json.loads(Path('docs/workout_generator_initial_requirements.json').read_text(encoding='utf-8'))
    validate(approved, _REQUIREMENTS)
    assert not programming_policy_errors(approved)
    goals = {goal['metric']: goal for tier in approved['objectiveTiers'] for goal in tier}
    metrics = ('weekly_volume:chest', 'execution_blocks', 'movement_overlap')
    requirements = {'objectiveTiers': [[goals[metric] for metric in metrics]]}
    # Each column is an alternative: favor dose, favor setup, compromise, forbidden ideal.
    misses = ((0, 1, .5, 0), (1, 0, .5, 0), (1, 1, .5, 0))
    values = {metric: [goals[metric]['target'] + goals[metric]['scale'] * miss
        for miss in profile] for metric, profile in zip(metrics, misses)}
    variables = [{'lower': 0, 'upper': 1, 'integer': True} for _ in range(4)]
    rows = [(('choose_one',), 1, 1, 0, dict.fromkeys(range(4), 1)),
        (('hard_requirement',), 0, 0, 0, {3: 1})]

    def variable(**kwargs):
        index = len(variables)
        variables.append({'lower': 0, 'upper': kwargs['upper'], 'integer': kwargs['integer'],
            'domainIdentity': kwargs['domain_identity']})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        rows.append((label, lower, upper, intercept, coefficients))

    stages = joint._goal_programming_objectives(variable, constraint, variables, requirements,
        {metric: dict(enumerate(profile)) for metric, profile in values.items()}, {})
    for name, coefficients in stages:
        status, selected = solve([{**v, 'objectiveCost': coefficients.get(i, 0)}
            for i, v in enumerate(variables)], rows, timeout_seconds=5)
        assert status == 'optimal' and selected[:4] == [0, 0, 1, 0]
        optimum = sum(selected[i] * value for i, value in coefficients.items())
        rows.append((('attained_goal', name), optimum, optimum, 0, coefficients))
        native = goal_programming_costs(requirements,
            {metric: profile[2] for metric, profile in values.items()}, {})
        assert optimum == native[name]
    assert native == {'goal_tier_0_worst': .5, 'goal_tier_0_total': 1.5}
    assert goal_programming_costs(requirements, {'setup_economy': 0}, {})[
        'goal_tier_0_worst'] is None


def test_goal_policy_jointly_settles_dose_before_minimizing_work_and_matches_comparison():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 0, 'maximum': None,
        'preferredMinimum': 4, 'preferredMaximum': 12}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['objectiveOrder'] = ['volume_target', 'workload_economy', 'duration_economy']
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 2, 'maximumSets': 3}]
    for item in sessions[0]['exercises']:
        item['numWorkSets'] = 2
    baseline = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert baseline['feasible'] and baseline['audit']['weeklyWorkingSets'] == 4, baseline
    requirements['objectiveTiers'] = [[
        {'metric': 'weekly_volume:chest', 'target': 0, 'scale': 4},
        {'metric': 'coverage:first', 'target': -3, 'scale': 3},
        {'metric': 'coverage:second', 'target': -3, 'scale': 3},
    ]]
    assert not programming_policy_errors(requirements)
    validate(requirements, _REQUIREMENTS)
    original = copy.deepcopy(requirements)
    candidate = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert candidate['feasible'] and candidate['audit']['weeklyWorkingSets'] == 6, candidate
    assert candidate['audit']['weeklyCoverageSets']['first'] == 3
    assert candidate['audit']['weeklyCoverageSets']['second'] == 3
    assert requirements == original
    assert candidate['priorityExecution']['goalPolicy']['stages'][0]['value'] == 0
    from workout_generator_pkg.generation_audit import render_optimization_disclosure
    disclosure = render_optimization_disclosure(candidate['priorityExecution'])
    assert 'Shared goal tiers' in disclosure and 'first ≥ 3 weekly working sets (soft)' in disclosure
    scored = []
    for plan in (baseline, candidate):
        costs = {'volume_target': 0, 'weekly_volume:chest': 0, 'workload_economy': plan['audit']['weeklyWorkingSets'],
            'duration_economy': sum(day['estimatedSeconds'] for day in plan['audit']['workouts'])}
        costs.update(goal_programming_costs(requirements, costs, plan['audit']['weeklyCoverageSets']))
        scored.append(costs)
    for stage in candidate['priorityExecution']['goalPolicy']['stages']:
        assert stage['value'] == pytest.approx(scored[1][stage['goal']])
    result = assess_audited_programming_tradeoff(baseline, candidate, requirements=requirements,
        baseline_costs=scored[0], candidate_costs=scored[1],
        objective_names=requirements['objectiveOrder'], same_selected_work=False)
    assert result['status'] == 'candidate_preferred', result
    assert any(row['objective'] == 'workload_economy' for row in result['worsened'])
    from test_workout_generator_joint_candidate_comparison import _context
    context = _context()
    context['qualifiedRoleEvidence'] = {'LIBRARY_0': ['first'], 'LIBRARY_1': ['second']}
    requirements['preferenceResolution'] = 'explicit_tradeoffs'
    compared = joint.compare_audited_joint_candidates(
        {'workouts': baseline['sessions'], 'audit': baseline['audit']},
        {'workouts': candidate['sessions'], 'audit': candidate['audit']},
        requirements=requirements, context=context)
    assert compared['decision'] == 'promote_candidate', compared
    broken = {'workouts': candidate['sessions'], 'audit': copy.deepcopy(candidate['audit'])}
    broken['audit']['errors'].append({'code': 'fixture_hard_constraint'})
    assert joint.compare_audited_joint_candidates(
        {'workouts': baseline['sessions'], 'audit': baseline['audit']}, broken,
        requirements=requirements, context=context)['decision'] == 'retain_baseline'
    unreachable = copy.deepcopy(requirements)
    for goal in unreachable['objectiveTiers'][0]:
        if goal['metric'].startswith('coverage:'):
            goal.update(target=-4, scale=3)
    residual = joint.solve_prescribed_week(sessions, unreachable, equipment)
    assert residual['feasible'], residual
    assert residual['priorityExecution']['goalPolicy']['stages'][0]['value'] == pytest.approx(1 / 3)


def test_goal_targets_saturate_and_missing_evidence_stays_unknown():
    requirements = {'objectiveTiers': [[{'metric': 'coverage:pull', 'target': -4, 'scale': 4},
        {'metric': 'time_budget', 'target': 0, 'scale': 4500}]]}
    exact = goal_programming_costs(requirements, {'time_budget': 0}, {'pull': 4})
    assert exact == goal_programming_costs(requirements, {'time_budget': 0}, {'pull': 8})
    assert exact == {'goal_tier_0_worst': 0, 'goal_tier_0_total': 0}
    assert goal_programming_costs(requirements, {}, {'pull': 4})['goal_tier_0_worst'] is None
    assert goal_programming_costs(requirements, {'time_budget': 0}, None)['goal_tier_0_total'] is None
    assert goal_programming_costs(requirements, {'time_budget': 0}, {})['goal_tier_0_total'] is None
    invalid = {'requiredCoverage': [], 'objectiveOrder': [], 'objectiveTiers': [[
        {'metric': 'coverage:pull', 'target': -4, 'scale': 0}]]}
    assert len(programming_policy_errors(invalid)) == 2
    requirements['objectiveOrder'] = ['time_budget', 'workload_economy']
    requirements['requiredCoverage'] = [{'key': 'pull', 'intent': 'development'}]
    comparison = assess_audited_programming_tradeoff(
        {'audit': {'errors': [], 'weeklyCoverageSets': {'pull': 4}}},
        {'audit': {'errors': [], 'weeklyCoverageSets': {'pull': 8}}}, requirements=requirements,
        baseline_costs={**exact, 'time_budget': 0, 'workload_economy': 6},
        candidate_costs={**exact, 'time_budget': 0, 'workload_economy': 8},
        objective_names=requirements['objectiveOrder'], same_selected_work=False)
    assert comparison['status'] == 'baseline_preferred'


def test_fractional_target_misses_use_the_exact_cp_lattice_and_preserve_hard_rows():
    from workout_generator_pkg.cp_solver import solve

    requirements = {'objectiveTiers': [[
        {'metric': 'first', 'target': 0, 'scale': 3},
        {'metric': 'second', 'target': 0, 'scale': 4}]]}
    variables = [{'lower': 0, 'upper': 1, 'integer': True} for _ in range(2)]
    rows = [(('choose_one',), 1, 1, 0, {0: 1, 1: 1})]
    def variable(**kwargs):
        index = len(variables)
        variables.append({'lower': 0, 'upper': kwargs['upper'], 'integer': kwargs['integer'],
            'domainIdentity': kwargs['domain_identity']})
        return index
    def constraint(label, lower, upper, coefficients, intercept=0):
        rows.append((label, lower, upper, intercept, coefficients))
    goals = joint._goal_programming_objectives(variable, constraint, variables, requirements,
        {'first': {0: 1}, 'second': {1: 1}}, {})
    diagnostics = {}
    status, selected = solve([{**v, 'objectiveCost': goals[0][1].get(i, 0)}
        for i, v in enumerate(variables)], rows, diagnostics=diagnostics)
    assert status == 'optimal' and selected[:2] == [0, 1], diagnostics
    assert selected[-1] == .25
    assert diagnostics['exactAuxiliaryLattice'] == 12
    rows.append((('user_forbids_second',), 0, 0, 0, {1: 1}))
    status, selected = solve([{**v, 'objectiveCost': goals[0][1].get(i, 0)}
        for i, v in enumerate(variables)], rows)
    assert status == 'optimal' and selected[:2] == [1, 0]
    assert selected[-1] == pytest.approx(1 / 3)


@pytest.mark.parametrize('aspiration', [5, 6])
def test_later_effective_set_aspiration_adds_dose_inside_range_and_matches_native_comparison(aspiration):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    from test_workout_generator_joint_candidate_comparison import _context

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['auditTargets']['weeklyEffectiveSets'] = {'chest': {
        'minimum': 0, 'maximum': None, 'preferredMinimum': 4, 'preferredMaximum': 12}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['objectiveOrder'] = ['volume_target', 'workload_economy', 'duration_economy']
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 2, 'maximumSets': 3}]
    requirements['objectiveTiers'] = [[{'metric': 'weekly_volume:chest', 'target': 0, 'scale': 4}]]
    baseline = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert baseline['feasible'] and baseline['audit']['weeklyWorkingSets'] == 4
    requirements['objectiveTiers'].append([{
        'metric': 'weekly_effective_sets:chest', 'target': -aspiration, 'scale': aspiration - 4}])
    validate(requirements, _REQUIREMENTS)
    assert programming_policy_errors(requirements) == []
    candidate = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert candidate['feasible'] and not candidate['audit']['errors'], candidate
    assert candidate['audit']['weeklyVolume']['chest']['effective'] == aspiration
    assert candidate['audit']['weeklyWorkingSets'] == aspiration
    context = _context()
    context['qualifiedRoleEvidence'] = {'LIBRARY_0': ['first'], 'LIBRARY_1': ['second']}
    compared = joint.compare_audited_joint_candidates(
        {'workouts': baseline['sessions'], 'audit': baseline['audit']},
        {'workouts': candidate['sessions'], 'audit': candidate['audit']},
        requirements=requirements, context=context)
    assert compared['decision'] == 'promote_candidate', compared
    costs = joint._joint_candidate_objective_costs(
        {'workouts': candidate['sessions'], 'audit': candidate['audit']}, requirements, context)
    for stage in candidate['priorityExecution']['goalPolicy']['stages']:
        assert stage['value'] == pytest.approx(costs[stage['goal']])
    from workout_generator_pkg.generation_audit import render_optimization_disclosure
    assert f'chest ≥ {aspiration} weekly effective sets' in render_optimization_disclosure(candidate['priorityExecution'])
    # A soft aspiration must not override an explicit hard dose ceiling.
    requirements['auditTargets']['weeklyEffectiveSets']['chest']['maximum'] = 4
    requirements['auditTargets']['weeklyEffectiveSets']['chest']['preferredMaximum'] = 4
    limited = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert limited['feasible'] and limited['audit']['weeklyVolume']['chest']['effective'] == 4
    assert limited['priorityExecution']['goalPolicy']['stages'][-1]['value'] == 1
    evidence = limited['audit']['volumePreferenceEvidence']['weekly'][0]
    assert evidence['aspiration'] == aspiration and evidence['aspirationShortfall'] == aspiration - 4
    from workout_generator_pkg.generation_audit import render_plan_disclosures
    assert f'soft aspiration {aspiration}; aspiration shortfall {aspiration - 4}' in render_plan_disclosures(
        limited['audit'], muscles=['chest'])


def test_movement_balance_precedes_optional_within_range_volume():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['auditTargets']['weeklyEffectiveSets'] = {'chest': {
        'minimum': 0, 'maximum': 5, 'preferredMinimum': 4, 'preferredMaximum': 5}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['objectiveOrder'] = ['volume_target', 'source_balance', 'workload_economy']
    requirements['executionRules'] = [
        {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 3},
        {'kind': 'coverageBalance', 'first': 'first', 'second': 'second',
            'scope': 'weekly', 'relationship': 'balanced'}]
    requirements['objectiveTiers'] = [
        [{'metric': 'weekly_volume:chest', 'target': 0, 'scale': 4}],
        [{'metric': 'weekly_effective_sets:chest', 'target': -5, 'scale': 1}]]
    unprotected = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert unprotected['feasible'] and unprotected['audit']['weeklyWorkingSets'] == 5
    assert abs(unprotected['audit']['weeklyCoverageSets']['first']
        - unprotected['audit']['weeklyCoverageSets']['second']) == 1
    requirements['objectiveTiers'].insert(1, [{'metric': 'source_balance', 'target': 0, 'scale': 1}])
    validate(requirements, _REQUIREMENTS)
    assert not programming_policy_errors(requirements)
    balanced = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert balanced['feasible'] and not balanced['audit']['errors']
    assert balanced['audit']['weeklyWorkingSets'] == 4
    assert balanced['audit']['weeklyCoverageSets']['first'] == balanced['audit']['weeklyCoverageSets']['second']
    assert balanced['priorityExecution']['goalPolicy']['stages'][-1]['value'] == 1


def test_known_goal_prefix_decides_before_unknown_lower_priority_evidence():
    requirements = {'objectiveOrder': ['time_budget', 'workload_economy', 'exercise_distribution'],
        'requiredCoverage': [], 'objectiveTiers': [[{'metric': 'time_budget', 'target': 0, 'scale': 1}]]}
    plan = {'audit': {'errors': [], 'weeklyCoverageSets': {}}}
    before = {'goal_tier_0_worst': 1, 'goal_tier_0_total': 1,
        'time_budget': 1, 'workload_economy': 4, 'exercise_distribution': None}
    after = {**before, 'goal_tier_0_worst': 0, 'goal_tier_0_total': 0, 'time_budget': 0,
        'workload_economy': 5}

    def assess(left, right):
        return assess_audited_programming_tradeoff(plan, plan, requirements=requirements,
            baseline_costs=left, candidate_costs=right,
            objective_names=requirements['objectiveOrder'], same_selected_work=False)

    result = assess(before, after)
    assert result['status'] == 'candidate_preferred'
    assert result['unknownObjectives'] == ['exercise_distribution']
    assert assess_audited_programming_tradeoff({'audit': {}}, plan, requirements=requirements,
        baseline_costs=before, candidate_costs=after, objective_names=requirements['objectiveOrder'],
        same_selected_work=False)['status'] == 'unknown'
    assert assess({**before, 'goal_tier_0_worst': None}, after)['status'] == 'unknown'
    # Equal tiers must still stop at unknown higher-ranked tie-break evidence.
    requirements['objectiveOrder'] = ['time_budget', 'exercise_distribution', 'workload_economy']
    assert assess(after, {**after, 'workload_economy': 4})['status'] == 'unknown'
    requirements['objectiveOrder'] = ['time_budget', 'workload_economy', 'exercise_distribution']
    assert assess(after, {**after, 'workload_economy': 4})['status'] == 'candidate_preferred'


def test_explicit_ordering_goal_reaches_joint_solver_and_native_comparison():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    from workout_generator_pkg.programming_guidelines import execution_interference_profile, execution_interference_score

    equipment, requirements, sessions = two_recipe_order_case()
    requirements.update(objectiveOrder=['duration_economy', 'execution_order'],
        orderingPreferences={'phaseOrder': [['HEAVY_COMPOUND', 'MODERATE_COMPOUND'], ['ISOLATION'], ['CORE']],
            'protectionOrder': ['heavy_direct']},
        objectiveTiers=[[{'metric': 'ordering_heavy_direct', 'target': 0, 'scale': 5}]])
    validate(requirements, _REQUIREMENTS)
    assert not programming_policy_errors(requirements)
    for field in ('objectiveOrder', 'orderingPreferences'):
        missing = copy.deepcopy(requirements)
        missing.pop(field)
        assert programming_policy_errors(missing)
    result = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'] and not result['audit']['errors'], result
    assert 'splitArchitecture' not in result  # Selection must remain coupled to an explicit execution goal.
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda definition: definition['id']))}
    selected = result['sessions'][0]['exercises']
    profiles = [execution_interference_profile([definitions[item['definition_id']]],
        [item['numWorkSets']], item['satisfiesCoverage'], requirements) for item in selected]
    raw = execution_interference_score(list(range(len(profiles))), profiles, requirements)[0]
    costs = goal_programming_costs(requirements, {'ordering_heavy_direct': raw}, {})
    assert result['priorityExecution']['goalPolicy']['stages'][0]['value'] == costs['goal_tier_0_worst']
    plan = {'audit': {'errors': [], 'weeklyCoverageSets': {}}}
    assessment = assess_audited_programming_tradeoff(plan, plan, requirements=requirements,
        baseline_costs={**costs, 'ordering_heavy_direct': raw, 'duration_economy': 100},
        candidate_costs={**goal_programming_costs(requirements, {'ordering_heavy_direct': raw + 1}, {}),
            'ordering_heavy_direct': raw + 1, 'duration_economy': 90},
        objective_names=['duration_economy', 'ordering_heavy_direct'], same_selected_work=False)
    assert any(row['objective'] == 'ordering_heavy_direct' for row in assessment['worsened'])
    assert assessment['status'] == 'baseline_preferred'


@pytest.mark.parametrize('metric', ['session_heavy_exercise_balance', 'session_heavy_set_balance'])
def test_heavy_session_balance_uses_the_same_counts_in_solver_and_comparison(monkeypatch, metric):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    from workout_generator_pkg.programming_policy import session_balance_count

    monkeypatch.setenv('MYWORKOUT_SOLVER_SEARCH_SECONDS', '15')
    equipment, requirements, sessions = two_recipe_order_case()
    template = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [{**copy.deepcopy(template), 'id': f'definition-{index}',
        'name': f'Exercise {index}', 'exerciseCategory': 'HEAVY_COMPOUND' if index < 3 else 'ISOLATION'}
        for index in range(6)]
    item = sessions[0]['exercises'][0]
    menu = [{**copy.deepcopy(item), 'definition_id': f'LIBRARY_{index}', 'numWorkSets': 2,
        'satisfiesCoverage': [], 'superset': None} for index in range(6)]
    sessions = [{**copy.deepcopy(sessions[0]), 'name': f'Day {index}', 'trainingDays': [index * 2],
        'exercises': copy.deepcopy(menu)} for index in range(3)]
    requirements.update(sessionsPerWeek=3, requiredCoverage=[],
        auditTargets={'weeklyEffectiveSets': {'chest': {'minimum': 12, 'maximum': 12}},
            'perSessionEffectiveSets': {}},
        executionRules=[{'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 2},
            {'kind': 'sessionStructure', 'maximumExercises': 2, 'maximumSupersetSize': 2,
                'maximumSupersets': 0}],
        objectiveOrder=['goal_tier_0', metric],
        objectiveTiers=[[{'metric': metric, 'target': 0, 'scale': 1}]],
        goalAggregation='total_then_worst')
    validate(requirements, _REQUIREMENTS)
    result = joint.solve_prescribed_week(sessions, requirements, equipment,
        semantic_selection={'mode': 'selected_menu',
            'definitionIds': [definition['id'] for definition in equipment['exerciseDefinitions']]})
    assert result['feasible'], result
    definitions = {f'LIBRARY_{i}': definition for i, definition in enumerate(equipment['exerciseDefinitions'])}
    counts = [session_balance_count(day['exercises'], definitions, metric) for day in result['sessions']]
    assert counts == ([1, 1, 1] if metric.endswith('exercise_balance') else [2, 2, 2])
    artifact = {'workouts': result['sessions'], 'audit': result['audit']}
    costs = joint._joint_candidate_objective_costs(artifact, requirements, {'setupDefinitions': definitions})
    assert costs[metric] == 0
    assert next(stage['value'] for stage in result['objectiveProgress']
        if stage['goal'] == 'goal_tier_0_total') == costs['goal_tier_0_total'] == 0
    definitions['LIBRARY_0'].pop('exerciseCategory')
    assert session_balance_count(menu, definitions, metric) is None
    assert joint._joint_candidate_objective_costs(artifact, requirements,
        {'setupDefinitions': definitions})[metric] is None


def test_shared_quality_compares_dose_balance_setup_and_sequence_before_workload(monkeypatch):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    from test_workout_generator_joint_candidate_comparison import _context
    from workout_generator_pkg.programming_policy import selection_precedes_execution

    monkeypatch.setenv('MYWORKOUT_SOLVER_SEARCH_SECONDS', '15')
    equipment, requirements, sessions = two_recipe_order_case()
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'type': 'BARBELL', 'name': 'Barbell',
        'barWeight': 10, 'sleeveLength': 100,
        'availablePlates': [{'weight': 5, 'thickness': 1}] * 2}]
    for definition in equipment['exerciseDefinitions']:
        definition.update(exerciseType='WEIGHT', equipmentId='EQUIPMENT_0', bodyWeightPercentage=None)
    sessions.append(copy.deepcopy(sessions[0]))
    sessions[1].update(name='Day 2', trainingDays=[2])
    requirements.update(sessionsPerWeek=2,
        objectiveOrder=['volume_target', 'workload_economy', 'execution_order'],
        orderingPreferences={'phaseOrder': [], 'protectionOrder': ['main_direct']})
    requirements['auditTargets'] = {'weeklyEffectiveSets': {'chest': {
        'minimum': 0, 'maximum': None, 'preferredMinimum': 9, 'preferredMaximum': 12}},
        'perSessionEffectiveSets': {}}
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 2, 'maximumSets': 3}]
    for day in sessions:
        for item in day['exercises']:
            item['numWorkSets'] = 2
            item['workSetTemplate'] = {'reps': 8, 'weight': 10}
    baseline = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert baseline['feasible'], baseline
    assert baseline['audit']['weeklyWorkingSets'] == 9

    requirements.update(
        objectiveOrder=['goal_tier_0', 'session_exercise_balance', 'session_set_balance',
            'setup_economy', 'workload_economy', 'relative_distribution', 'execution_order'],
        objectiveTiers=[[
            {'metric': 'weekly_volume:chest', 'target': 0, 'scale': 9, 'group': 'training'},
            {'metric': 'session_exercise_balance', 'target': 0, 'scale': 1, 'group': 'balance'},
            {'metric': 'session_set_balance', 'target': 0, 'scale': 1, 'group': 'balance'},
            {'metric': 'setup_economy', 'target': 0, 'scale': 40, 'group': 'setup'},
            {'metric': 'setup_economy_resource_switches', 'target': 0, 'scale': 40, 'group': 'setup'},
            {'metric': 'execution_blocks', 'target': 0, 'scale': 40, 'group': 'setup'},
            {'metric': 'relative_distribution', 'target': 0, 'scale': 1, 'group': 'exposure'},
            {'metric': 'relative_distribution_worst', 'target': 0, 'scale': 1, 'group': 'exposure'},
            {'metric': 'ordering_main_direct', 'target': 0, 'scale': 16, 'group': 'interference'},
        ]], goalAggregation='total_then_worst', preferenceResolution='explicit_tradeoffs')
    validate(requirements, _REQUIREMENTS)
    assert not programming_policy_errors(requirements)
    assert not selection_precedes_execution(requirements)
    candidate = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert candidate['feasible'], (candidate.get('status'), candidate.get('instruction'), candidate.get('errors'))
    assert candidate['audit']['weeklyWorkingSets'] == 10
    assert [day['workingSets'] for day in candidate['audit']['workouts']] == [5, 5]
    assert candidate['objectiveProgress'][0]['goal'] == 'goal_tier_0_total'
    assert candidate['finalOrdering']['status'] == 'evaluated_in_shared_goal_tier'

    context = _context()
    context.update(qualifiedRoleEvidence={'LIBRARY_0': ['first'], 'LIBRARY_1': ['second']},
        setupDefinitions={f'LIBRARY_{i}': value for i, value in enumerate(
            sorted(equipment['exerciseDefinitions'], key=lambda definition: definition['id']))},
        setupEquipmentById={item['id']: item for item in equipment['equipments']})
    artifacts = [{'workouts': plan['sessions'], 'audit': plan['audit']} for plan in (baseline, candidate)]
    scores = [joint._joint_candidate_objective_costs(artifact, requirements, context) for artifact in artifacts]
    for stage in candidate['objectiveProgress']:
        if stage['goal'].startswith('goal_tier_'):
            assert stage['value'] == pytest.approx(scores[1][stage['goal']])
    compared = joint.compare_audited_joint_candidates(*artifacts, requirements=requirements, context=context)
    assert compared['decision'] == 'promote_candidate', compared
    assert any(row['objective'] == 'workload_economy'
        for row in compared['programmingTradeoff']['worsened'])
