import copy

import pytest

from workout_generator_pkg import joint_planning
from workout_generator_pkg.cp_solver import solve
from workout_generator_pkg.programming_policy import goal_programming_costs
from workout_generator_pkg.programming_guidelines import movement_overlap_roles
from test_workout_generator_joint_candidate_comparison import _candidate, _context, _requirements


@pytest.mark.parametrize('grouped', [False, True])
def test_compiled_goal_totals_match_native_group_means_and_legacy_sums(grouped):
    tier = [{'metric': metric, 'target': 0, 'scale': 1,
        **({'group': 'dose'} if grouped and index < 3 else {})}
        for index, metric in enumerate(('first', 'second', 'third', 'fourth'))]
    requirements = {'objectiveTiers': [tier]}
    profiles = {'first': (.5, .5), 'second': (.5, 0),
        'third': (.5, 0), 'fourth': (0, .5)}
    variables = [{'lower': 0, 'upper': 1, 'integer': True} for _ in range(2)]
    rows = [(('choose_one',), 1, 1, 0, {0: 1, 1: 1})]

    def variable(**kwargs):
        index = len(variables)
        variables.append({'lower': 0, 'upper': kwargs['upper'], 'integer': kwargs['integer'],
            'domainIdentity': kwargs['domain_identity']})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        rows.append((label, lower, upper, intercept, coefficients))

    stages = joint_planning._goal_programming_objectives(variable, constraint, variables,
        requirements, {metric: dict(enumerate(values)) for metric, values in profiles.items()}, {})
    for name, coefficients in stages:
        status, selected = solve([{**v, 'objectiveCost': coefficients.get(index, 0)}
            for index, v in enumerate(variables)], rows, timeout_seconds=5)
        assert status == 'optimal'
        optimum = sum(selected[index] * value for index, value in coefficients.items())
        native = goal_programming_costs(requirements,
            {metric: sum(value * selected[index] for index, value in enumerate(values))
                for metric, values in profiles.items()}, {})
        assert optimum == pytest.approx(native[name])
        rows.append((('attained_goal', name), optimum, optimum, 0, coefficients))
    assert selected[:2] == ([1, 0] if grouped else [0, 1])
    assert native['goal_tier_0_worst'] == .5
    assert native['goal_tier_0_total'] == (.5 if grouped else 1)


def test_shared_planes_parent_roles_and_limb_modes_do_not_make_complementary_patterns_redundant():
    common = ['posterior_chain', 'sagittal_plane', 'unilateral', 'hamstrings']
    hinge = {'definition_id': 'HINGE_A', 'satisfiesCoverage': common + ['hip_dominant']}
    knee_flexion = {'definition_id': 'FLEXION', 'satisfiesCoverage': common + ['knee_flexion_hamstring']}
    other_hinge = {'definition_id': 'HINGE_B', 'satisfiesCoverage': common + ['hip_dominant']}
    assert movement_overlap_roles(common) == set()
    assert joint_planning.overlapping_movement_pairs([hinge, knee_flexion, other_hinge]) == [
        ('HINGE_A', 'HINGE_B')]


def test_sequence_optimization_cannot_drop_selected_compound_but_can_regroup_it():
    definitions = {'C': {'id': 'compound'}, 'S': {'id': 'support'}}
    options = [(0, 0, None, {'count': 2, 'items': [{'definition_id': 'C'}]}),
        (1, 0, None, {'count': 2, 'items': [{'definition_id': 'S'}]}),
        (2, 0, None, {'count': 2, 'items': [{'definition_id': 'C'}, {'definition_id': 'S'}]}),
        (3, 0, None, {'count': 4, 'items': [{'definition_id': 'S'}]})]
    rows = []
    selection = joint_planning._lock_selected_session_work(rows, [1, 1, 0, 0], options, [{}], definitions)
    assert selection == [{'compound': 2, 'support': 2}]
    variables = [{'lower': 0, 'upper': 1, 'integer': True, 'objectiveCost': cost}
        for cost in (0, 0, -1, -10)]
    status, chosen = solve(variables, rows, timeout_seconds=5)
    assert status == 'optimal' and chosen == [0, 0, 1, 0]


def test_raw_order_exposure_cannot_promote_a_different_selected_menu():
    requirements = _requirements(['execution_order'])
    requirements['orderingPreferences'] = {'protectionOrder': ['main_direct']}
    baseline, candidate = _candidate([2]), _candidate([2], definition_id='LIBRARY_2')
    for plan in (baseline, candidate):
        plan['workouts'][0]['exercises'][0]['superset'] = None
    context = _context()
    context['setupDefinitions'] = {reference: {'id': reference, 'exerciseType': 'WEIGHT',
        'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': [],
        'exerciseCategory': 'MODERATE_COMPOUND'} for reference in ('LIBRARY_1', 'LIBRARY_2')}
    result = joint_planning.compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=context)
    assert result['decision'] == 'incomparable'
    assert result['reason'] == 'execution_order_requires_same_selected_session_work'


def test_sequence_equipment_changes_only_break_protected_order_ties():
    requirements = _requirements(['workload_economy', 'duration_economy', 'setup_economy', 'execution_order'])
    requirements['orderingPreferences'] = {'protectionOrder': ['main_direct', 'main_support']}
    available = dict.fromkeys(requirements['objectiveOrder'], True)
    available.update(setup_economy_transitions=True, setup_economy_resource_switches=True)
    assert joint_planning._ordered_joint_objective_names(requirements, available) == [
        'workload_economy', 'duration_economy', 'setup_economy',
        'ordering_main_direct', 'ordering_main_support',
        'setup_economy_transitions', 'setup_economy_resource_switches']


def test_dose_distribution_keeps_physical_workload_without_pinning_roles_before_sequence(monkeypatch):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'role_concentration', 'distribution', 'execution_order']
    requirements['orderingPreferences'] = {'protectionOrder': ['main_direct']}
    requirements['requiredCoverage'][0]['intent'] = 'development'
    before = copy.deepcopy(requirements)
    monkeypatch.setattr(joint_planning, '_lock_weekly_training_doses',
        lambda *args: (_ for _ in ()).throw(AssertionError('Role/muscle doses were pinned before selection.')))
    captured = []
    actual_solve = joint_planning._cp_solve

    def capture(variables, features, **kwargs):
        captured.extend(row for row in features if row[0] in (
            ('objective', 'workload_economy'), ('selection_prefix_bound', 'workload_economy')))
        return actual_solve(variables, features, **kwargs)

    monkeypatch.setattr(joint_planning, '_cp_solve', capture)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert captured and all(row[2] == 10 for row in captured)
    stage = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'ordering_main_direct')
    assert stage['selectionFixed'] and sum(stage['selectedSessionWork'][0].values()) == 10
    assert requirements == before


def test_development_role_mix_can_change_after_a_controlled_equal_workload_tie(monkeypatch):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, original = two_recipe_order_case()
    sessions = [copy.deepcopy(original[0]) for _ in range(3)]
    for index, day in enumerate(sessions):
        day.update(name=f'Day {index}', trainingDays=[2 * index])
    requirements.update(sessionsPerWeek=3,
        objectiveOrder=['workload_economy', 'role_concentration', 'execution_order'],
        orderingPreferences={'protectionOrder': ['main_direct']})
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 6, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 2, 'maximum': 2}
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 2, 'maximumSets': 2}]
    requirements['requiredCoverage'] = [
        {'key': 'first', 'scope': 'weekly', 'intent': 'development', 'description': 'Development role'},
        {'key': 'second', 'scope': 'weekly', 'intent': 'inclusion', 'description': 'Inclusion role'}]
    actual_solve = joint_planning._cp_solve
    initial = []

    def controlled_tie(variables, features, **kwargs):
        if kwargs.get('diagnostics', {}).get('goal') == 'workload_economy':
            coefficients = {index: variable.get('domainIdentity', {}).get('coverage', {}).get('first', 0)
                for index, variable in enumerate(variables)}
            kwargs.pop('session', None)
            status, chosen = actual_solve(variables,
                [*features, (('controlled_initial_tie',), 2, 2, 0, coefficients)], **kwargs)
            initial.append(sum(value * chosen[index] for index, value in coefficients.items()))
            return status, chosen
        return actual_solve(variables, features, **kwargs)

    monkeypatch.setattr(joint_planning, '_cp_solve', controlled_tie)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert initial == [2]
    assert result['audit']['weeklyWorkingSets'] == 6
    assert result['audit']['weeklyCoverageSets']['first'] == 4
    assert result['audit']['weeklyCoverageSets']['second'] == 2
