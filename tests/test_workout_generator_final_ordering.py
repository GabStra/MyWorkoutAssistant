import copy
import time

import pytest

from workout_generator_pkg import joint_planning as joint, programming_guidelines as rules


@pytest.mark.parametrize('preserve_placement', [False, True])
@pytest.mark.parametrize('balance_metric', ['duration_balance', 'session_exercise_balance', 'session_set_balance'])
@pytest.mark.parametrize('grouped', [False, True])
def test_final_execution_balances_weekly_work_before_freezing_session_counts(preserve_placement, balance_metric, grouped):
    from test_workout_generator_joint_prescriptions import prescription_case
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, requirements, menu = prescription_case()
    requirements.update(sessionsPerWeek=2,
        objectiveOrder=['workload_economy', balance_metric, 'execution_order'],
        durationBalanceToleranceSeconds=60,
        requiredCoverage=[{'key': 'press', 'scope': 'eachSession', 'description': 'Press work'}],
        executionRules=[{'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 2}],
        orderingPreferences={'phaseOrder': [], 'protectionOrder': ['adjacent_direct']})
    if grouped:
        requirements['objectiveOrder'].insert(1, 'goal_tier_0')
        requirements['objectiveTiers'] = [[{'metric': balance_metric, 'target': 0, 'scale': 1}]]
    requirements['auditTargets']['weeklyEffectiveSets'] = {'chest': {'minimum': 8, 'maximum': 8}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['auditTargets']['maximumSessionSeconds'] = 5000
    menu = menu[:2]
    for index in (1, 2):
        definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
        definition.update(id=f'accessory-{index}', name=f'Accessory {index}')
        equipment['exerciseDefinitions'].append(definition)
    for day in menu:
        day['exercises'][0].update(numWorkSets=2, definition_id='LIBRARY_2', satisfiesCoverage=['press'])
    for ref in ('LIBRARY_0', 'LIBRARY_1'):
        item = copy.deepcopy(menu[1]['exercises'][0])
        item['definition_id'] = ref
        menu[1]['exercises'].append(item)
    definitions = {f'LIBRARY_{i}': definition for i, definition in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda definition: definition['id']))}
    selected = joint._selected_session_work(menu, definitions)
    seed = joint._solve_prescribed_week(menu, requirements, equipment,
        _fixed_session_work=selected, search_deadline=time.monotonic() + 10)
    assert seed['feasible'], seed
    assert joint._needs_session_rebalancing(seed, requirements)
    context = {'restrictionPolicy': {}, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'sourceWorkingSetBudget': None,
        'qualifiedRoleEvidence': {ref: ['press'] for ref in definitions},
        'setupDefinitions': definitions, 'demandEvidence': {'status': 'unavailable', 'groups': {}},
        'demandUnion': None}
    result = joint._polish_selected_execution(seed, menu, requirements, equipment,
        context=context, preserve_source_selection=preserve_placement, search_deadline=time.monotonic() + 10)
    assert result['finalOrdering']['status'] == 'completed', result['finalOrdering']
    assert not result['audit']['errors']
    assert joint._selected_weekly_work(result['sessions'], definitions) == joint._selected_weekly_work(seed['sessions'], definitions)
    assert result['audit']['weeklyVolume'] == seed['audit']['weeklyVolume']
    if balance_metric in ('session_exercise_balance', 'session_set_balance'):
        counts = [sum(item['numWorkSets'] for item in day['exercises'])
            if balance_metric == 'session_set_balance' else len(day['exercises']) for day in result['sessions']]
        stage_name = 'goal_tier_0_total' if grouped else balance_metric
        stage = next(stage for stage in result['objectiveProgress'] if stage['goal'] == stage_name)
        native = joint._joint_candidate_objective_costs(
            {'workouts': result['sessions'], 'audit': result['audit']}, requirements, context)
        assert stage['value'] == native[balance_metric] == max(counts) - min(counts)
        assert stage['value'] == native[stage_name]
        if not preserve_placement:
            assert stage['weeklyDosesLocked']
        priority = next(row for row in result['priorityExecution']['approvedPriorities']
            if row['priority'] == balance_metric)
        assert priority['owner'] == 'joint_solver'
    if preserve_placement:
        assert joint._selected_session_work(result['sessions'], definitions) == selected
        assert joint._needs_session_rebalancing(result, requirements)
    else:
        assert not joint._needs_session_rebalancing(result, requirements)
        assert sorted(day['workingSets'] for day in result['audit']['workouts']) == [4, 4]


def test_final_ordering_runs_on_fixed_work_when_quality_remains_unproven(monkeypatch):
    from test_workout_generator_complete_candidate_refinement import _case

    equipment, requirements, sessions, context, seed = _case()
    requirements['orderingPreferences'] = {'protectionOrder': ['adjacent_direct'],
        'phaseOrder': [['HEAVY_COMPOUND'], ['MODERATE_COMPOUND'], ['ISOLATION'], ['CORE']]}
    seed['objectiveProgress'][0]['status'] = 'feasible'
    before = copy.deepcopy(seed)
    original, calls = joint._cp_solve, []

    def record(*args, **kwargs):
        calls.append(kwargs.get('diagnostics', {}).get('goal'))
        return original(*args, **kwargs)

    monkeypatch.setattr(joint, '_cp_solve', record)
    result = joint._polish_selected_execution(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10, context=context)
    assert result['finalOrdering']['status'] == 'completed', result['finalOrdering']
    assert 'ordering_adjacent_direct' in calls
    assert result['finalOrdering']['selectedSessionWork'] == joint._selected_session_work(
        result['sessions'], context['setupDefinitions'])
    assert result['audit']['weeklyWorkingSets'] == seed['audit']['weeklyWorkingSets']
    assert result['audit']['weeklyVolume'] == seed['audit']['weeklyVolume']
    assert not result['audit']['errors']
    assert result['occurrenceLineage'] == seed['occurrenceLineage']
    assert seed == before
    assert result['finalOrdering']['stages'][0]['priorObjectiveBoundsProven'] is False


def test_final_ordering_timeout_retains_audited_artifact_without_claiming_completion(monkeypatch):
    from test_workout_generator_complete_candidate_refinement import _case

    equipment, requirements, sessions, context, seed = _case()
    requirements['orderingPreferences'] = {'protectionOrder': ['adjacent_direct']}
    monkeypatch.setattr(joint, '_solve_prescribed_week', lambda *args, **kwargs: {
        'feasible': False, 'status': 'unproven', 'objectiveProgress': [],
        'instruction': 'Retain the exact candidate.', 'errors': [{'code': 'fixture_search_failure'}]})
    result = joint._polish_selected_execution(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10, context=context)
    assert result['finalOrdering']['attempted']
    assert result['finalOrdering']['status'] == 'unproven'
    assert result['sessions'] == seed['sessions'] and result['audit'] == seed['audit']
    assert result['finalOrdering']['errors'] == [{'code': 'fixture_search_failure'}]
    assert result['finalOrdering']['instruction'] == 'Retain the exact candidate.'


def test_final_ordering_preserves_a_known_zero_overlap_goal_after_selection_removes_pairs():
    from test_workout_generator_complete_candidate_refinement import _case

    equipment, requirements, sessions, context, seed = _case()
    requirements['objectiveOrder'].insert(0, 'movement_overlap')
    requirements['objectiveTiers'][0].append({'metric': 'movement_overlap', 'target': 0, 'scale': 2})
    requirements['orderingPreferences'] = {'phaseOrder': [], 'protectionOrder': ['adjacent_direct']}
    result = joint._polish_selected_execution(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10, context=context)
    assert result['finalOrdering']['status'] == 'completed', result['finalOrdering']
    assert result['audit']['weeklyWorkingSets'] == seed['audit']['weeklyWorkingSets'] == 5


@pytest.mark.parametrize('second_category,compatible', [
    ('HEAVY_COMPOUND', True), ('MODERATE_COMPOUND', False), ('ISOLATION', False)])
def test_supersets_cannot_hide_a_later_phase_partner(second_category, compatible):
    requirements = {'orderingPreferences': {'phaseOrder': [
        ['HEAVY_COMPOUND'], ['MODERATE_COMPOUND'], ['ISOLATION'], ['CORE']]}}
    heavy = {'id': 'heavy', 'exerciseCategory': 'HEAVY_COMPOUND', 'muscleGroups': ['FRONT_CHEST']}
    second = {'id': 'partner', 'exerciseCategory': second_category, 'muscleGroups': ['FRONT_BICEPS']}
    status = rules.superset_setup_compatibility(heavy, second, requirements)['status']
    assert (status != 'incompatible') is compatible


def test_explicit_precedence_cannot_override_strict_heavy_before_moderate_phases():
    requirements = {'orderingPreferences': {'phaseOrder': [
        ['HEAVY_COMPOUND'], ['MODERATE_COMPOUND']]},
        'executionRules': [{'kind': 'order', 'before': 'moderate', 'after': 'heavy'}]}
    roles = [{'moderate'}, {'heavy'}]
    keys = [(1, ('moderate',)), (0, ('heavy',))]
    assert not rules.execution_order_is_admissible([0, 1], roles, keys, requirements)
    assert not rules.execution_order_is_admissible([1, 0], roles, keys, requirements)
    with pytest.raises(ValueError, match='conflicts'):
        rules.execution_order_indices(roles, keys, requirements)


def test_isolation_and_core_can_share_the_approved_final_phase():
    requirements = {'orderingPreferences': {'phaseOrder': [
        ['HEAVY_COMPOUND'], ['MODERATE_COMPOUND'], ['ISOLATION', 'CORE']]}}
    isolation = {'id': 'isolation', 'exerciseCategory': 'ISOLATION', 'muscleGroups': ['FRONT_BICEPS']}
    core = {'id': 'core', 'exerciseCategory': 'ISOLATION', 'muscleGroups': ['FRONT_ABS']}
    assert rules.superset_setup_compatibility(isolation, core, requirements)['status'] != 'incompatible'


def test_native_circuit_cannot_override_strict_phases_with_an_explicit_predecessor():
    from workout_generator_pkg import cp_solver
    from workout_generator_pkg.generation_audit import setup_resource_profile

    requirements = {'objectiveOrder': ['execution_order'],
        'orderingPreferences': {'phaseOrder': [['HEAVY_COMPOUND'], ['MODERATE_COMPOUND']],
            'protectionOrder': ['adjacent_direct']},
        'executionRules': [{'kind': 'order', 'before': 'moderate', 'after': 'heavy'}]}
    variables, rows, blocks = [], [], []

    def variable(upper=1, lower=0, integer=True, domain_identity=None):
        variables.append({'lower': lower, 'upper': upper, 'integer': integer,
            'domainIdentity': domain_identity})
        return len(variables) - 1

    def constraint(label, lower, upper, coefficients, intercept=0):
        rows.append((label, lower, upper, intercept, coefficients))

    for name, category in [('heavy', 'HEAVY_COMPOUND'), ('moderate', 'MODERATE_COMPOUND')]:
        definition = {'id': name, 'exerciseCategory': category, 'muscleGroups': ['FRONT_CHEST']}
        option = variable(lower=1)
        blocks.append({'first': variable(), 'options': [option],
            'optionValues': {option: {'count': 1, 'setupProfiles': [setup_resource_profile(definition)]}},
            'recipe': {'roles': {name}, 'orderPriority': rules.execution_block_priority([definition]),
                'interferencePerRound': rules.execution_interference_profile(
                    [definition], [1], [name], requirements)}})
    joint._add_execution_sequence(blocks, requirements, variable, constraint, 0, 1)
    status, candidate = cp_solver.solve(variables, rows, timeout_seconds=2)
    assert status == 'infeasible' and candidate is None


def test_explicit_explosive_identity_precedes_heavy_work_in_native_solver_without_adding_work():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    heavy_id = '00000000-0000-0000-0000-000000000001'
    explosive_id = '00000000-0000-0000-0000-000000000002'
    equipment['exerciseDefinitions'][0].update(id=heavy_id, exerciseCategory='HEAVY_COMPOUND')
    equipment['exerciseDefinitions'][1].update(id=explosive_id, exerciseCategory='MODERATE_COMPOUND')
    requirements['objectiveOrder'] = ['execution_order']
    requirements['orderingPreferences'] = {'phaseOrder': [
        ['HEAVY_COMPOUND'], ['MODERATE_COMPOUND'], ['ISOLATION', 'CORE']],
        'protectionOrder': ['adjacent_direct'], 'explosiveDefinitionIds': [explosive_id]}
    result = joint._solve_prescribed_week(sessions, requirements, equipment,
        _fixed_session_work=[{heavy_id: 5, explosive_id: 5}], search_deadline=time.monotonic() + 10)
    assert result['feasible'], result
    assert [item['definition_id'] for item in result['sessions'][0]['exercises']] == ['LIBRARY_1', 'LIBRARY_0']
    assert result['audit']['weeklyWorkingSets'] == 10 and not result['audit']['errors']
    assert rules.superset_setup_compatibility(*equipment['exerciseDefinitions'], requirements)['status'] == 'incompatible'


def test_explosive_selector_is_optional_identity_based_and_validated_against_library():
    from jsonschema import validate
    from workout_generator_pkg.planning_tools import _REQUIREMENTS
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, _ = two_recipe_order_case()
    identifier = '00000000-0000-0000-0000-000000000001'
    definition = equipment['exerciseDefinitions'][0]
    definition.update(id=identifier, name='Explosive Power Example', exerciseCategory='MODERATE_COMPOUND')
    requirements['orderingPreferences'] = {'phaseOrder': [], 'protectionOrder': [], 'explosiveDefinitionIds': []}
    assert rules.execution_block_priority([definition], requirements) == 1
    requirements['orderingPreferences']['explosiveDefinitionIds'] = [identifier]
    validate(requirements, _REQUIREMENTS)
    assert rules.execution_block_priority([definition], requirements) == -1
    assert not rules.execution_rule_errors(requirements, equipment)
    requirements['orderingPreferences']['explosiveDefinitionIds'] = ['00000000-0000-0000-0000-000000000999']
    assert any(error['code'] == 'unknown_explosive_definition'
        for error in rules.execution_rule_errors(requirements, equipment))


def test_qualified_family_profiles_stay_stable_when_selected_options_expose_subset_pools():
    from workout_generator_pkg import cp_solver

    requirements = {'requiredCoverage': [{'key': key} for key in ('whole', 'left', 'right')]}
    context = {'qualifiedRoleEvidence': {'A': ['whole', 'left'],
        'B': ['whole', 'left', 'right'], 'C': ['whole', 'right']},
        'exerciseFamilyEvidence': {'familyByReference': {'A': 'FA', 'B': 'FB', 'C': 'FC'}}}
    profiles = joint._qualified_exercise_distribution_profiles(requirements, context)
    assert [profile['roles'] for profile in profiles] == [['whole']]

    def score(qualified_profiles):
        variables = [{'lower': 1, 'upper': 1, 'integer': True} for _ in range(3)]
        rows = []
        options = [(index, 0, index, {'count': 2, 'items': [{'definition_id': ref,
            'satisfiesCoverage': roles}]}) for index, (ref, roles) in enumerate([
                ('A', ['whole', 'left']), ('B', ['whole', 'left', 'right']), ('C', ['right'])])]

        def variable(upper=1, lower=0, integer=True, domain_identity=None):
            variables.append({'lower': lower, 'upper': upper, 'integer': integer,
                'domainIdentity': domain_identity})
            return len(variables) - 1

        def constraint(label, lower, upper, coefficients, intercept=0):
            rows.append((label, lower, upper, intercept, coefficients))

        costs, _, _ = joint._add_exercise_distribution_objective(variable, constraint, options,
            [{'timesCompletedInAWeek': 1}], [], ['whole', 'left', 'right'],
            context['exerciseFamilyEvidence']['familyByReference'], profiles=qualified_profiles)
        status, chosen = cp_solver.solve([{**value, 'objectiveCost': costs.get(index, 0)}
            for index, value in enumerate(variables)], rows, timeout_seconds=2)
        assert status == 'optimal'
        return sum(chosen[index] * cost for index, cost in costs.items())

    assert score(None) == 4  # Rebuilding the pool from narrowed choices exposes overlapping subsets.
    assert score(profiles) == 2


def test_prefix_duration_bounds_include_exact_warmup_offset_and_terminal_recovery():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, requirements, sessions = two_recipe_order_case()
    requirements.update(objectiveOrder=['duration_economy', 'execution_order'],
        orderingPreferences={'phaseOrder': [], 'protectionOrder': ['adjacent_direct']},
        executionRules=[])
    seed = joint._solve_prescribed_week(sessions, requirements, equipment,
        _selection_only=True, search_deadline=time.monotonic() + 10)
    assert seed['feasible'], seed
    assert seed['_selectionPrefixBounds']['duration_economy'] == seed['audit']['workouts'][0]['estimatedSeconds']
    # Explicit boundary recovery uses the coupled circuit, including its final-block discount.
    requirements['executionRules'] = [{'kind': 'rest', 'coverageKey': None, 'context': 'exerciseTransition',
        'minimumSeconds': 60, 'maximumSeconds': 60}]
    seed = joint._solve_prescribed_week(sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10)
    assert seed['feasible'], seed
    rests = [item['restAfterExerciseSeconds'] for item in seed['sessions'][0]['exercises']]
    assert rests == [60, 0]
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda value: value['id']))}
    context = {'restrictionPolicy': {}, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'sourceWorkingSetBudget': None,
        'qualifiedRoleEvidence': {'LIBRARY_0': ['first'], 'LIBRARY_1': ['second']},
        'demandEvidence': {'status': 'unavailable', 'groups': {}}, 'demandUnion': None,
        'setupDefinitions': definitions}
    result = joint._polish_selected_execution(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10, context=context)
    assert result['finalOrdering']['status'] == 'completed', result['finalOrdering']
    assert result['audit']['workouts'][0]['estimatedSeconds'] <= seed['audit']['workouts'][0]['estimatedSeconds']
    assert not result['audit']['errors']
