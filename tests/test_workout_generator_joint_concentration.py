import copy
import math
import pytest

from workout_generator_pkg import joint_planning
from workout_generator_pkg import recipe_contracts
from workout_generator_pkg.generation_audit import render_optimization_disclosure
from test_workout_generator_joint_prescriptions import two_recipe_order_case


def test_peak_surplus_tiebreak_spreads_only_after_weekly_dose_is_locked():
    variables, rows = [], []

    def variable(**kwargs):
        index = len(variables)
        variables.append({'lower': kwargs.get('lower', 0), 'upper': kwargs.get('upper', 1),
            'integer': kwargs.get('integer', True), 'objectiveCost': 0,
            'domainIdentity': kwargs.get('domain_identity'), 'current': [], 'members': []})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        rows.append((label, lower, upper, intercept, coefficients))

    sessions = [{'timesCompletedInAWeek': 2}, {'timesCompletedInAWeek': 1}]
    options = []
    count_by_option = {}
    for day in range(2):
        day_options = []
        for count in (0, 2, 3, 5, 7):
            index = variable()
            day_options.append(index)
            count_by_option[index] = count
            options.append((index, day, 0, {'count': count, 'items': []}))
        constraint(('one_option_per_day', day), 1, 1, {index: 1 for index in day_options})
    dose = {index: count_by_option[index] * sessions[day]['timesCompletedInAWeek']
        for index, day, _, _ in options}
    constraint(('dose_lock',), 9, 9, dose)
    exposure_by_option = {index: count for index, count in count_by_option.items() if count}
    profiles = [{'key': 'core', 'exposureByOption': exposure_by_option,
        'fixedExposures': [2], 'fixedFrequencies': [1]}]
    peak = joint_planning._add_peak_surplus_objective(variable, constraint, options,
        sessions, profiles, 'role_concentration_peak')
    variables[peak]['objectiveCost'] = 1

    source_incumbent = [0] * len(variables)
    for index, day, _, _ in options:
        if (day == 0 and count_by_option[index] == 2) or (day == 1 and count_by_option[index] == 5):
            source_incumbent[index] = 1
    source_incumbent[peak] = 9
    status, candidate = joint_planning._milp_solve(variables, rows, timeout_seconds=2,
        preserve_current=False, incumbent=source_incumbent)
    assert status == 'optimal'
    selected_counts = [sum(count_by_option[index] * candidate[index]
        for index, option_day, _, _ in options if option_day == day) for day in range(2)]
    assert selected_counts == [3, 3]
    assert sum(selected_counts[index] * sessions[index]['timesCompletedInAWeek']
        for index in range(2)) == 9
    assert candidate[peak] == 1


def test_role_peak_tiebreak_spreads_other_roles_after_an_immovable_peak_without_changing_dose():
    variables, rows = [], []

    def variable(**kwargs):
        index = len(variables)
        variables.append({'lower': kwargs.get('lower', 0), 'upper': kwargs.get('upper', 1),
            'integer': kwargs.get('integer', True), 'objectiveCost': 0,
            'domainIdentity': kwargs.get('domain_identity'), 'current': [], 'members': []})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        rows.append((label, lower, upper, intercept, coefficients))

    sessions = [{'timesCompletedInAWeek': 1}] * 3
    locked_role_index = variable()
    constraint(('immovable_role_peak',), 1, 1, {locked_role_index: 1})
    options = [(locked_role_index, 0, 0, {'count': 8, 'items': []})]
    movable_by_day = []
    count_by_option = {}
    for day in range(3):
        day_options = []
        for count in (0, 2, 6):
            index = variable()
            day_options.append(index)
            count_by_option[index] = count
            options.append((index, day, 0, {'count': count, 'items': []}))
        movable_by_day.append(day_options)
        constraint(('one_movable_option_per_day', day), 1, 1,
            {index: 1 for index in day_options})
    constraint(('movable_role_weekly_dose_lock',), 6, 6,
        {index: count for index, count in count_by_option.items()})
    profiles = [
        {'key': 'locked_peak', 'exposureByOption': {locked_role_index: 8},
            'fixedExposures': [], 'fixedFrequencies': []},
        {'key': 'movable_pull', 'exposureByOption': {
            index: count for index, count in count_by_option.items() if count},
            'fixedExposures': [], 'fixedFrequencies': []},
    ]
    worst_peak = joint_planning._add_peak_surplus_objective(variable, constraint,
        options, sessions, profiles, 'role_concentration_peak')
    profile_peak_costs = {}
    for profile_index, profile in enumerate(profiles):
        profile_peak = joint_planning._add_peak_surplus_objective(variable, constraint,
            options, sessions, [profile], 'role_concentration_profile_peak',
            profile_index_offset=profile_index)
        profile_peak_costs[profile_peak] = 1

    primary_costs = {worst_peak: 1}
    primary_variables = [{**value, 'objectiveCost': primary_costs.get(index, 0)}
        for index, value in enumerate(variables)]
    status, primary = joint_planning._milp_solve(primary_variables, rows,
        timeout_seconds=2, preserve_current=False)
    assert status == 'optimal'
    primary_value = primary[worst_peak]
    rows.append((('objective', 'role_concentration'), -float('inf'), primary_value + 1e-7,
        0, primary_costs))

    secondary_variables = [{**value, 'objectiveCost': profile_peak_costs.get(index, 0)}
        for index, value in enumerate(variables)]
    status, balanced = joint_planning._milp_solve(secondary_variables, rows,
        timeout_seconds=2, preserve_current=False, incumbent=primary)

    assert status == 'optimal'
    selected_counts = [sum(count_by_option[index] * balanced[index]
        for index in day_options) for day_options in movable_by_day]
    assert selected_counts == [2, 2, 2]
    assert sum(selected_counts) == 6
    assert balanced[worst_peak] == primary_value == 16
    assert sum(balanced[index] for index in profile_peak_costs) == 16


def test_fixed_only_role_peak_participates_in_shared_role_profile_objective():
    equipment, requirements, sessions = two_recipe_order_case()
    requirements = copy.deepcopy(requirements)
    sessions = copy.deepcopy(sessions)
    requirements['sessionsPerWeek'] = 2
    requirements['objectiveOrder'] = ['workload_economy', 'distribution']
    requirements['requiredCoverage'] = [
        {'key': 'variable_role', 'scope': 'weekly', 'description': 'Variable role'},
        {'key': 'fixed_only_role', 'scope': 'weekly', 'description': 'Fixed-only role'},
    ]
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 100}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 50}
    for item in sessions[0]['exercises']:
        item['satisfiesCoverage'] = (
            ['variable_role'] if item['definition_id'] == 'LIBRARY_0' else [])
    fixed = copy.deepcopy(sessions[0])
    fixed['name'] = 'Fixed'
    fixed['trainingDays'] = [0]
    for item in fixed['exercises']:
        item['satisfiesCoverage'] = (
            ['fixed_only_role'] if item['definition_id'] == 'LIBRARY_0' else [])
    sessions[0]['name'] = 'Variable'
    sessions[0]['trainingDays'] = [2]

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        existing={'name': 'Fixed week', 'workouts': [fixed]})

    assert result['feasible'], result
    role_placement = result['priorityExecution']['structuralConcentration']['rolePlacement']
    fixed_profile = next(profile for profile in role_placement['profiles']
        if profile['roles'] == ['fixed_only_role'])
    assert fixed_profile['fixedSessionSets'] == [5]
    assert fixed_profile['variableSessionSets'] == [0]
    assert fixed_profile['peakSurplusPerOccurrence'] == 2.5
    assert role_placement['sumTieBreakStatus'] == 'optimal'
    goal_order = [stage['goal'] for stage in result['objectiveProgress']]
    assert goal_order.index('workload_economy') < goal_order.index('role_concentration')
    assert goal_order.index('role_concentration') < goal_order.index('role_concentration_tiebreak')
    assert goal_order.index('role_concentration_tiebreak') < goal_order.index('distribution')


def test_optional_concentration_peaks_do_not_change_hard_feasibility_fingerprint():
    source_variable = {'lower': 0, 'upper': 1, 'integer': True, 'domainIdentity': {'kind': 'source_option'}}
    baseline = joint_planning._joint_model_domain_fingerprint([source_variable], [],
        library_hash='library', history_fingerprint=None, evidence={}, restriction_policy=None,
        allow_educated_load_guesses=True, preserve_source_selection=False)
    variables = [source_variable,
        {'lower': 0, 'upper': 10, 'integer': False, 'domainIdentity': {'kind': 'role_concentration_peak'}},
        {'lower': 0, 'upper': 10, 'integer': False,
            'domainIdentity': {'kind': 'role_concentration_profile_peak'}},
        {'lower': 0, 'upper': 10, 'integer': False, 'domainIdentity': {'kind': 'demand_colocation_peak'}}]
    rows = [
        (('role_concentration_peak', 0, 'session', 0), float('-inf'), 0, 0, {0: 1, 1: -1}),
        (('role_concentration_profile_peak', 0, 'session', 0), float('-inf'), 0, 0, {0: 1, 2: -1}),
        (('demand_colocation_peak', 'session', 0), float('-inf'), 0, 0, {0: 1, 3: -1}),
    ]
    with_optional_peaks = joint_planning._joint_model_domain_fingerprint(variables, rows,
        library_hash='library', history_fingerprint=None, evidence={}, restriction_policy=None,
        allow_educated_load_guesses=True, preserve_source_selection=False)
    assert with_optional_peaks == baseline


def test_unique_union_peak_separates_two_tied_group_peaks():
    variables, rows = [], []

    def variable(**kwargs):
        index = len(variables)
        variables.append({'lower': kwargs.get('lower', 0), 'upper': kwargs.get('upper', 1),
            'integer': kwargs.get('integer', True), 'objectiveCost': 0,
            'domainIdentity': kwargs.get('domain_identity'), 'current': [], 'members': []})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        rows.append((label, lower, upper, intercept, coefficients))

    options, exposures = [], {}
    group_indexes = []
    for group in ('P', 'Q'):
        indexes = []
        for day in range(3):
            index = variable()
            indexes.append(index)
            options.append((index, day, 0, {'count': 4, 'items': [group]}))
            exposures[index] = 4
        group_indexes.append(indexes)
        constraint(('recipe_dose', group), 1, 1, {index: 1 for index in indexes})
        primary_peak = variable(lower=4, upper=4, integer=False)
        for day, index in enumerate(indexes):
            constraint(('primary_group_peak', group, day), -float('inf'), 0,
                {index: 4, primary_peak: -1})

    profile = {'key': 'verified_demand_union', 'exposureByOption': exposures,
        'fixedExposures': [], 'fixedFrequencies': []}
    union_peak = joint_planning._add_peak_session_exposure_objective(variable, constraint,
        options, [{'timesCompletedInAWeek': 1}] * 3, profile, 'demand_colocation_peak')
    variables[union_peak]['objectiveCost'] = 1
    # A valid source plan co-locates both four-set recipes; the group peaks are still 4 each.
    source = [0] * len(variables)
    source[group_indexes[0][0]] = source[group_indexes[1][0]] = 1
    source[3] = source[7] = 4
    source[union_peak] = 8

    status, candidate = joint_planning._milp_solve(variables, rows, timeout_seconds=2,
        preserve_current=False, incumbent=source)
    assert status == 'optimal'
    assert candidate[3] == candidate[7] == 4
    session_peaks = [sum(exposures.get(index, 0) * candidate[index]
        for index, day, _, _ in options if day == session) for session in range(3)]
    assert max(session_peaks) == 4


@pytest.mark.parametrize('demand_distribution_status', ['optimal', 'feasible'])
def test_joint_solver_runs_role_and_verified_union_polishes_after_their_parent_priorities(
        monkeypatch, demand_distribution_status):
    equipment, requirements, source = two_recipe_order_case()
    sessions = []
    for index in range(3):
        day = copy.deepcopy(source[0])
        day.update(name=f'Day {index}', trainingDays=[index * 2])
        for exercise in day['exercises']:
            exercise['numWorkSets'] = 5
            exercise['satisfiesCoverage'] = ['core'] if exercise['definition_id'] == 'LIBRARY_0' else []
        sessions.append(day)

    requirements['sessionsPerWeek'] = 3
    requirements['requiredCoverage'] = [{'key': 'core', 'scope': 'weekly', 'description': 'Core',
        'intent': 'development'}]
    requirements['objectiveOrder'] = ['demand_distribution', 'development_emphasis', 'distribution']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    requirements['auditTargets'].pop('perSessionEffectiveSets', None)
    demand_keys = ('unsupported_trunk', 'axial_loading', 'eccentric_emphasis')
    for index, definition in enumerate(equipment['exerciseDefinitions']):
        definition['programmingDemands'] = {key: {'present': False, 'source': 'controlled fixture'}
            for key in demand_keys}
        definition['programmingDemands'][demand_keys[index]]['present'] = True

    original_solve = joint_planning._milp_solve
    stage_rows = {}
    def record_stage(variables, features, **kwargs):
        goal = (kwargs.get('diagnostics') or {}).get('goal')
        if goal in ('demand_colocation', 'development_emphasis', 'role_concentration',
                'role_concentration_tiebreak'):
            stage_rows[goal] = [label[0] for label, *_ in features]
        result = original_solve(variables, features, **kwargs)
        if (goal == 'demand_distribution' and demand_distribution_status == 'feasible'
                and result[1] is not None):
            return 'feasible', result[1]
        return result
    monkeypatch.setattr(joint_planning, '_milp_solve', record_stage)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    goals = [stage['goal'] for stage in result['objectiveProgress']]
    assert goals.index('demand_distribution') < goals.index('demand_colocation')
    assert goals.index('demand_colocation') < goals.index('development_emphasis')
    assert goals.index('development_emphasis') < goals.index('distribution') < goals.index('role_concentration')
    assert goals.index('role_concentration') < goals.index('role_concentration_tiebreak')
    assert not any(label == 'placement_conservation' for label in stage_rows['demand_colocation'])
    assert not any(label == 'placement_conservation' for label in stage_rows['development_emphasis'])
    assert any(label == 'placement_conservation' for label in stage_rows['role_concentration'])
    assert any(label == 'placement_conservation'
        for label in stage_rows['role_concentration_tiebreak'])
    concentration = result['priorityExecution']['structuralConcentration']
    assert concentration['verifiedDemandUnion']['presentDefinitionIds'] == ['press', 'row']
    expected_status = demand_distribution_status
    assert concentration['verifiedDemandUnion']['optimizationStatus'] == expected_status
    assert concentration['verifiedDemandUnion']['stage']['status'] == expected_status
    if demand_distribution_status == 'feasible':
        assert concentration['verifiedDemandUnion']['stage']['solverStatus'] == 'optimal'
    role = concentration['rolePlacement']
    assert role['status'] == expected_status
    disclosure = render_optimization_disclosure(result['priorityExecution'])
    if demand_distribution_status == 'feasible':
        assert 'Verified-demand co-location: valid candidate found' in disclosure
        assert 'Movement-role placement: valid candidate found' in disclosure
        assert 'Verified-demand co-location: best result proven' not in disclosure
        assert 'Movement-role placement: best result proven' not in disclosure
    core = role['profiles'][0]
    assert core['weeklyWorkingSets'] == sum(core['variableSessionSets'])
    assert max(core['variableSessionSets']) == 5
    assert core['peakSurplusPerOccurrence'] == 0


def test_solver_stop_before_role_polish_reports_planned_substage_as_unresolved(monkeypatch):
    equipment, requirements, source = two_recipe_order_case()
    sessions = [copy.deepcopy(source[0]) for _ in range(3)]
    for index, day in enumerate(sessions):
        day.update(name=f'Day {index}', trainingDays=[index * 2])
        for exercise in day['exercises']:
            exercise['numWorkSets'] = 5
            exercise['satisfiesCoverage'] = ['core'] if exercise['definition_id'] == 'LIBRARY_0' else []
    requirements['sessionsPerWeek'] = 3
    requirements['requiredCoverage'] = [{'key': 'core', 'scope': 'weekly', 'description': 'Core',
        'intent': 'development'}]
    # Preservation establishes the source candidate before distribution times out.
    requirements['objectiveOrder'] = ['preservation', 'distribution']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    requirements['auditTargets'].pop('perSessionEffectiveSets', None)

    original_solve = joint_planning._milp_solve
    def stop_distribution(variables, features, **kwargs):
        if (kwargs.get('diagnostics') or {}).get('goal') == 'distribution':
            return 'timeout', None
        return original_solve(variables, features, **kwargs)
    monkeypatch.setattr(joint_planning, '_milp_solve', stop_distribution)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        reviewed_baseline_workouts=sessions)
    assert result['feasible'], result
    concentration = result['priorityExecution']['structuralConcentration']
    assert concentration['rolePlacement']['status'] == 'not_run_after_solver_stop'
    priority = next(item for item in result['priorityExecution']['approvedPriorities']
        if item['priority'] == 'distribution')
    assert priority['status'] == 'timeout'
    assert priority['subStages'][0]['status'] == 'not_run_after_solver_stop'


def test_exercise_distribution_stage_spreads_fixed_weekly_dose_across_qualified_definitions(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['sessionsPerWeek'] = 1
    requirements['objectiveOrder'] = ['exercise_distribution']
    requirements['requiredCoverage'] = [
        {'key': 'pull', 'scope': 'eachSession', 'description': 'Pulling work'},
    ]
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 4}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 4}
    for item in sessions[0]['exercises']:
        item.update(numWorkSets=4, satisfiesCoverage=['pull'])
    monkeypatch.setattr(joint_planning, 'reviewed_exercise_family_evidence',
        lambda equipment, references=None: {'familyByReference': {
            'LIBRARY_0': 'FAMILY_A', 'LIBRARY_1': 'FAMILY_B'}, 'sourcesByReference': {
            'LIBRARY_0': {}, 'LIBRARY_1': {}}, 'unclassifiedReferences': []})

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    stage = next(stage for stage in result['objectiveProgress']
        if stage['goal'] == 'exercise_distribution')
    assert stage['status'] == 'optimal'
    output_sets = {item['definition_id']: item['numWorkSets']
        for item in result['sessions'][0]['exercises']}
    assert output_sets == {'LIBRARY_0': 2, 'LIBRARY_1': 2}
    assert result['exerciseDistribution']['profiles'][0]['weeklyWorkingSetsByDefinition'] == {
        'LIBRARY_0': 2, 'LIBRARY_1': 2,
    }
    assert result['exerciseDistribution']['doseLocking']['scope'] == 'not_applied'


def test_development_dose_lock_preserves_development_and_leaves_inclusion_mix_free():
    variables, features = [], []

    def variable(**kwargs):
        index = len(variables)
        variables.append({'lower': kwargs.get('lower', 0), 'upper': kwargs.get('upper', 1),
            'integer': kwargs.get('integer', True), 'objectiveCost': 0,
            'domainIdentity': kwargs.get('domain_identity'), 'current': [], 'members': []})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        features.append((label, lower, upper, intercept, coefficients))

    option_variables = []
    for definition in ('A', 'B', 'C'):
        for _ in range(8):
            index = variable()
            option_variables.append((index, 0, 0, {'count': 1,
                'items': [{'definition_id': definition, 'satisfiesCoverage': (
                    ['DEV', 'INC'] if definition == 'A' else
                    ['DEV'] if definition == 'B' else ['INC'])}],
                'coverage': {'DEV': int(definition in ('A', 'B')),
                    'INC': int(definition in ('A', 'C'))}}))
    constraint(('physical_workload',), 8, 8, {index: 1 for index, *_ in option_variables})
    constraint(('coverage', 'INC'), 1, math.inf, {
        index: 1 for index, _, _, option in option_variables
        if option['coverage']['INC']})
    sessions = [{'timesCompletedInAWeek': 1}]
    incumbent = [int(definition == 'A') for _, _, _, option in option_variables
        for definition in [option['items'][0]['definition_id']]]
    role_coefficients = joint_planning._weekly_role_dose_coefficients(
        option_variables, sessions, ['DEV'])
    locked = joint_planning._lock_weekly_role_doses(
        features, incumbent, role_coefficients, ['DEV'])
    costs, profiles, _ = joint_planning._add_exercise_distribution_objective(
        variable, constraint, option_variables, sessions, [], ['DEV', 'INC'],
        {'A': 'FAMILY_A', 'B': 'FAMILY_B', 'C': 'FAMILY_C'},
        {'DEV': 'development', 'INC': 'inclusion'})
    status, candidate = joint_planning._milp_solve(
        [{**item, 'objectiveCost': costs.get(index, 0)} for index, item in enumerate(variables)],
        features, timeout_seconds=2, preserve_current=False)

    assert status == 'optimal'
    selected = [candidate[index] for index, *_ in option_variables]
    selected_role_doses = joint_planning._weekly_role_doses(
        candidate, role_coefficients, ['DEV'])
    selected_by_definition = {definition: sum(candidate[index] for index, _, _, option in option_variables
        if option['items'][0]['definition_id'] == definition) for definition in ('A', 'B', 'C')}
    assert selected != incumbent
    assert sum(selected) == 8
    assert locked == selected_role_doses == {'DEV': 8}
    assert selected_by_definition['B'] == 7
    assert selected_by_definition['A'] == 1
    assert selected_by_definition['C'] == 0
    assert {profile['intent'] for profile in profiles} == {'development', 'inclusion'}


def test_workload_before_family_locks_only_development_role_totals(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['sessionsPerWeek'] = 1
    requirements['objectiveOrder'] = ['workload_economy', 'exercise_distribution']
    requirements['requiredCoverage'] = [
        {'key': 'pull', 'scope': 'eachSession', 'description': 'Pulling work', 'intent': 'development'},
        {'key': 'incidental', 'scope': 'eachSession', 'description': 'Incidental exposure', 'intent': 'inclusion'},
    ]
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 4}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 4}
    for item in sessions[0]['exercises']:
        item.update(numWorkSets=4, satisfiesCoverage=['pull', 'incidental'])
    monkeypatch.setattr(joint_planning, 'reviewed_exercise_family_evidence',
        lambda equipment, references=None: {'familyByReference': {
            'LIBRARY_0': 'FAMILY_A', 'LIBRARY_1': 'FAMILY_B'}, 'sourcesByReference': {
            'LIBRARY_0': {}, 'LIBRARY_1': {}},
            'unclassifiedReferences': []})

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    dose_lock = result['exerciseDistribution']['doseLocking']
    assert dose_lock['scope'] == 'development_role_weekly_totals_after_workload_economy'
    assert dose_lock['roleWeeklyWorkingSets'] == {'pull': 4}
    assert dose_lock['finalWeeklyWorkingSetsByRole'] == {'pull': 4}
    assert dose_lock['matchesLockedDose'] is True
    assert dose_lock['unlockedInclusionRoles'] == ['incidental']


def test_approved_family_bound_counts_fixed_and_variable_weekly_sets(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['sessionsPerWeek'] = 2
    requirements['objectiveOrder'] = ['exercise_distribution']
    requirements['requiredCoverage'] = [
        {'key': 'pull', 'scope': 'eachSession', 'description': 'Pulling work'},
    ]
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 7, 'maximum': 7}
    requirements['auditTargets'].pop('perSessionEffectiveSets', None)
    for item in sessions[0]['exercises']:
        item.update(numWorkSets=4, satisfiesCoverage=['pull'])
    requirements['familySetBounds'] = [{
        'exerciseFamilyId': 'FAMILY_A', 'maximumWeeklySets': 4,
    }]
    fixed = copy.deepcopy(sessions[0])
    fixed.update(name='Fixed day', trainingDays=[0])
    fixed['exercises'] = [copy.deepcopy(fixed['exercises'][0])]
    fixed['exercises'][0]['numWorkSets'] = 3
    family_map = {'LIBRARY_0': 'FAMILY_A', 'LIBRARY_1': 'FAMILY_B'}
    family_evidence = {'familyByReference': family_map,
        'sourcesByReference': {reference: {} for reference in family_map}, 'unclassifiedReferences': []}
    monkeypatch.setattr(joint_planning, 'reviewed_exercise_family_evidence',
        lambda equipment, references=None: copy.deepcopy(family_evidence))
    monkeypatch.setattr(recipe_contracts, 'reviewed_exercise_family_evidence',
        lambda equipment, references=None: copy.deepcopy(family_evidence))

    result = joint_planning.solve_prescribed_week(
        sessions, requirements, equipment, existing={'name': 'Existing week', 'workouts': [fixed]})

    assert result['feasible'], result
    assert 3 <= result['audit']['weeklyFamilyWorkingSets']['FAMILY_A'] <= 4
    assert not any(error['code'].startswith('family_set_bound') for error in result['audit']['errors'])


def test_exercise_distribution_peak_includes_fixed_definition_sets(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['sessionsPerWeek'] = 2
    requirements['objectiveOrder'] = ['exercise_distribution']
    requirements['requiredCoverage'] = [
        {'key': 'pull', 'scope': 'eachSession', 'description': 'Pulling work'},
    ]
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 7, 'maximum': 7}
    requirements['auditTargets'].pop('perSessionEffectiveSets', None)
    for item in sessions[0]['exercises']:
        item.update(numWorkSets=4, satisfiesCoverage=['pull'])
    fixed = copy.deepcopy(sessions[0])
    fixed.update(name='Fixed day', trainingDays=[0])
    fixed['exercises'] = [copy.deepcopy(fixed['exercises'][0])]
    fixed['exercises'][0]['numWorkSets'] = 3
    fixed['exercises'][1:] = []
    monkeypatch.setattr(joint_planning, 'reviewed_exercise_family_evidence',
        lambda equipment, references=None: {'familyByReference': {
            'LIBRARY_0': 'FAMILY_A', 'LIBRARY_1': 'FAMILY_B'}, 'sourcesByReference': {
            'LIBRARY_0': {}, 'LIBRARY_1': {}}, 'unclassifiedReferences': []})

    result = joint_planning.solve_prescribed_week(
        sessions, requirements, equipment,
        existing={'name': 'Existing week', 'workouts': [fixed]})

    assert result['feasible'], result
    stage = next(stage for stage in result['objectiveProgress']
        if stage['goal'] == 'exercise_distribution')
    assert stage['status'] == 'optimal'
    assert {item['definition_id']: item['numWorkSets'] for item in result['sessions'][0]['exercises']} == {
        'LIBRARY_1': 4,
    }
    assert result['exerciseDistribution']['profiles'][0]['weeklyWorkingSetsByDefinition'] == {
        'LIBRARY_0': 3, 'LIBRARY_1': 4,
    }
