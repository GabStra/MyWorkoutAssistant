import sys
import copy
from pathlib import Path
import json

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_workout_generator_joint_prescriptions import two_recipe_order_case
from workout_generator_pkg import joint_planning


def development_case(source_counts=(4, 2), target_total=6):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': target_total, 'maximum': target_total}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': target_total, 'maximum': target_total}
    requirements['requiredCoverage'] = [
        {'key': 'role_a', 'scope': 'weekly', 'description': 'Role A', 'intent': 'development'},
        {'key': 'role_b', 'scope': 'weekly', 'description': 'Role B', 'intent': 'development'},
    ]
    requirements['objectiveOrder'] = ['distribution', 'preservation']
    sessions[0]['exercises'][0].update(numWorkSets=source_counts[0], satisfiesCoverage=['role_a'])
    sessions[0]['exercises'][1].update(numWorkSets=source_counts[1], satisfiesCoverage=['role_b'])
    return equipment, requirements, sessions


def test_explicit_development_objective_maximizes_minimum_exposure_without_an_inferred_cap():
    equipment, requirements, sessions = development_case()
    requirements['objectiveOrder'] = ['development_emphasis', 'distribution', 'preservation']

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    selected = result['sessions'][0]['exercises']
    assert [item['numWorkSets'] for item in selected] == [3, 3]
    assert sum(item['numWorkSets'] for item in selected) == 6
    development = result['priorityExecution']['developmentEmphasis']
    assert development['status'] == 'optimal'
    assert development['minimumWeeklyWorkingSets'] == 3
    assert result['objectiveProgress'][0]['goal'] == 'development_emphasis'
    assert result['sourceWorkingSetBudget'] == {
        'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}


def test_omitted_development_objectives_do_not_run_from_development_intent_alone():
    equipment, requirements, sessions = development_case()

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    goals = [stage['goal'] for stage in result['objectiveProgress']]
    assert 'development_emphasis' not in goals
    assert 'development_exposure' not in goals
    assert result['priorityExecution']['developmentEmphasis']['status'] == 'not_requested'


def test_combined_development_exposure_survives_lower_priority_preservation_and_higher_priorities():
    equipment, requirements, sessions = development_case(source_counts=(4, 8), target_total=12)
    requirements['sessionsPerWeek'] = 2
    requirements['objectiveOrder'] = [
        'demand_distribution', 'duration_balance', 'development_emphasis', 'source_balance',
        'development_exposure', 'distribution', 'preservation']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 24, 'maximum': 24}
    requirements['executionRules'] = [
        {'kind': 'workSets', 'coverageKey': 'role_a', 'minimumSets': 1, 'maximumSets': 4},
        {'kind': 'workSets', 'coverageKey': 'role_b', 'minimumSets': 1, 'maximumSets': 8},
        {'kind': 'coverageBalance', 'first': 'role_a', 'second': 'role_b', 'scope': 'weekly'},
    ]
    neutral = copy.deepcopy(sessions[0]['exercises'][0])
    neutral.update(definition_id='LIBRARY_2', numWorkSets=4)
    neutral.pop('satisfiesCoverage')
    sessions[0]['exercises'].append(neutral)
    neutral_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    neutral_definition.update(id='zz_neutral', name='Neutral Chest Press')
    equipment['exerciseDefinitions'].append(neutral_definition)
    sessions.append(copy.deepcopy(sessions[0]))
    sessions[0].update(name='Day A', trainingDays=[0])
    sessions[1].update(name='Day B', trainingDays=[1])
    for definition in equipment['exerciseDefinitions']:
        definition['programmingDemands'] = {
            'unsupported_trunk': {'present': True, 'source': 'controlled regression classification'},
            'axial_loading': {'present': False, 'source': 'controlled regression classification'},
            'eccentric_emphasis': {'present': False, 'source': 'controlled regression classification'},
        }

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        source_working_set_budget={'source': 'controlled_test_budget', 'variableWeeklyWorkingSets': 24},
        reviewed_baseline_workouts=sessions)

    assert result['feasible'], result
    stages = result['objectiveProgress']
    goals = [stage['goal'] for stage in stages]
    assert goals.index('demand_distribution') < goals.index('development_emphasis')
    assert goals.index('duration_balance') < goals.index('development_emphasis')
    assert goals.index('development_emphasis') < goals.index('source_balance')
    assert goals.index('source_balance') < goals.index('development_exposure')
    assert goals.index('development_exposure') < goals.index('distribution') < goals.index('preservation')
    development_stage = next(stage for stage in stages if stage['goal'] == 'development_emphasis')
    combined_stage = next(stage for stage in stages if stage['goal'] == 'development_exposure')
    preservation_stage = next(stage for stage in stages if stage['goal'] == 'preservation')
    assert development_stage['value'] == 8
    assert combined_stage['value'] == 16
    assert combined_stage['roleWeeklyWorkingSets'] == {'role_a': 8, 'role_b': 8}
    balance_stage = next(stage for stage in stages if stage['goal'] == 'source_balance')
    assert balance_stage['value'] == 0
    assert preservation_stage['value'] > 0  # It prefers the submitted 4/8/4 allocation.
    assert result['priorityExecution']['developmentEmphasis']['status'] == 'optimal'
    assert result['priorityExecution']['developmentEmphasis']['combinedExposure'] == {
        'status': 'optimal', 'weeklyWorkingSets': 16,
        'roleWeeklyWorkingSets': {'role_a': 8, 'role_b': 8},
        'unit': 'sum_of_weekly_qualified_role_working_sets',
        'solverStage': combined_stage,
    }
    assert result['sourceWorkingSetBudget']['variableWeeklyWorkingSets'] == 24
    assert sum(item['numWorkSets'] for day in result['sessions'] for item in day['exercises']) == 24
    assert all({item['satisfiesCoverage'][0]: item['numWorkSets']
        for item in day['exercises'] if item.get('satisfiesCoverage')} == {'role_a': 4, 'role_b': 4}
        for day in result['sessions'])


def test_generated_preparation_budget_seed_does_not_cap_user_required_volume():
    equipment, requirements, sessions = development_case(source_counts=(3, 3), target_total=8)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        source_working_set_budget={'source': 'code_preparation_hard_feasible_set_allocation_plus_existing_source_sessions',
                                   'variableWeeklyWorkingSets': 4, 'preparationId': 'PREP_1'})

    assert result['feasible'], result
    assert sum(item['numWorkSets'] for item in result['sessions'][0]['exercises']) == 8
    assert sum(item['numWorkSets'] for item in result['sessions'][0]['exercises']) > 4
    assert result['sourceWorkingSetBudget'] == {
        'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}


def test_nonbinding_preparation_seed_is_not_persisted_as_a_hard_cap():
    equipment, requirements, sessions = development_case(source_counts=(2, 2), target_total=8)
    seed = {'source': 'code_preparation_volume_only_seed',
        'variableWeeklyWorkingSets': 4, 'preparationId': 'PREP_SEED'}

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        source_working_set_budget=seed)

    assert result['feasible'], result
    assert result['sourceWorkingSetBudget'] == {
        'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}
    assert sum(item['numWorkSets'] for day in result['sessions']
        for item in day['exercises']) == 8
    development_budget = result['priorityExecution']['developmentEmphasis']['sourceBudget']
    assert development_budget == {
        'status': 'unbounded_by_user', 'source': 'unbounded_by_user',
        'variableSourceWorkingSets': None, 'fixedExistingWorkingSets': 0,
        'sourceBudgetWeeklyWorkingSets': None, 'variableMenuCapWorkingSets': None}


def test_variable_source_budget_excludes_fixed_existing_workouts():
    equipment, requirements, sessions = development_case(source_counts=(4, 2), target_total=6)
    requirements['sessionsPerWeek'] = 2
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 12, 'maximum': 12}
    existing = {'name': 'Fixed', 'workouts': copy.deepcopy(sessions)}

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        existing=existing, source_working_set_budget={
            'source': 'controlled_test_budget', 'variableWeeklyWorkingSets': 6})

    assert result['feasible'], result
    assert result['priorityExecution']['developmentEmphasis']['sourceBudget'] == {
        'status': 'applied', 'source': 'controlled_test_budget',
        'variableSourceWorkingSets': 6, 'fixedExistingWorkingSets': 6,
        'sourceBudgetWeeklyWorkingSets': 12, 'variableMenuCapWorkingSets': 6,
    }
    assert result['audit']['weeklyVolume']['chest']['effective'] == 12


def test_source_budget_counts_superset_members_and_session_frequency():
    equipment, requirements, sessions = development_case(source_counts=(3, 3), target_total=12)
    requirements['sessionsPerWeek'] = 2
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 6, 'maximum': 6}
    sessions[0].update(timesCompletedInAWeek=2, trainingDays=[0, 3])
    for item in sessions[0]['exercises']:
        item.update(superset='PAIR', restBetweenSetsSeconds=0, restAfterExerciseSeconds=0,
                    restAfterSupersetExerciseSeconds=30)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        source_working_set_budget={'source': 'controlled_test_budget', 'variableWeeklyWorkingSets': 12},
        preserve_source_selection=True)

    assert result['feasible'], result
    selected = result['sessions'][0]['exercises']
    assert sum(item['numWorkSets'] * 2 for item in selected) == 12
    assert all(item['numWorkSets'] == 3 for item in selected)
    assert len({item['superset'] for item in selected}) == 1
    assert selected[0]['superset'] is not None
    development = result['priorityExecution']['developmentEmphasis']
    assert development['minimumWeeklyWorkingSets'] == 6
    assert development['sourceBudget']['variableMenuCapWorkingSets'] == 12


def test_fresh_source_budget_receipt_is_reusable_for_the_same_solved_candidate():
    from workout_generator_pkg.allocation import reusable_joint_receipt
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, requirements, sessions = development_case(source_counts=(3, 3), target_total=8)
    source_budget = {'source': 'code_preparation_hard_feasible_set_allocation_plus_existing_source_sessions',
                     'variableWeeklyWorkingSets': 8, 'preparationId': 'PREP_3'}
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        source_working_set_budget=source_budget)
    owner = {'coordinatedJointPlanning': result, 'requirementsId': 'REQ_1',
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None}

    reusable = reusable_joint_receipt(owner, 'REQ_1', result['sessions'], requirements,
        equipment, [], preserve_source_selection=False)
    explicit_cap_reusable = reusable_joint_receipt(owner, 'REQ_1', result['sessions'], requirements,
        equipment, [], preserve_source_selection=False,
        source_working_set_budget={'source': 'controlled_test_budget', 'variableWeeklyWorkingSets': 6})

    assert reusable is not None
    assert explicit_cap_reusable is None
    assert reusable['sourceWorkingSetBudget'] == {
        'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None,
    }


def test_explicit_numeric_source_cap_is_binding_and_reports_conflict():
    equipment, requirements, sessions = development_case(source_counts=(1, 1))

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        source_working_set_budget={'source': 'user_approved_cap', 'variableWeeklyWorkingSets': 2})
    larger_budget = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        source_working_set_budget={'source': 'user_approved_cap', 'variableWeeklyWorkingSets': 8})

    assert result['feasible'] is False
    assert result['status'] == 'source_budget_conflict_requires_review'
    assert 'sessions' not in result
    assert result['sourceBudgetDiagnostic']['diagnosticOnly'] is True
    assert result['sourceBudgetDiagnostic']['cappedStatus'] == 'infeasible'
    assert result['sourceBudgetDiagnostic']['uncappedHardFeasibilityStatus'] in ('optimal', 'feasible')
    development = result['priorityExecution']['developmentEmphasis']
    assert development['status'] == 'source_budget_conflict_requires_review'
    assert development['sourceBudget']['variableSourceWorkingSets'] == 2
    assert development['sourceBudget']['sourceBudgetWeeklyWorkingSets'] == 2
    assert larger_budget['feasible'] is True
    assert result['feasibilityDomainFingerprint'] == larger_budget['feasibilityDomainFingerprint']


def test_development_status_reflects_unavailable_preceding_approved_priority():
    priority_execution = joint_planning._priority_execution(
        ['demand_distribution', 'duration_balance', 'development_emphasis', 'distribution', 'source_balance'],
        {'demand_distribution': {}, 'duration_balance': {}, 'distribution': {1: 1},
         'source_balance': {}, 'development_emphasis': {0: 1}},
        [{'goal': 'development_emphasis', 'status': 'optimal', 'value': 4,
          'roleWeeklyWorkingSets': {'role_a': 4}},
         {'goal': 'distribution', 'status': 'feasible', 'value': 2}],
        ['development_emphasis', 'distribution'], [], demand_evidence_status='unavailable',
        development_roles=['role_a'], development_budget={'status': 'applied'})

    assert priority_execution['approvedPriorities'][0]['status'] == 'unavailable_evidence'
    assert priority_execution['developmentEmphasis']['status'] == 'feasible'


def test_later_feasible_priority_does_not_downgrade_optimal_development_stage():
    priority_execution = joint_planning._priority_execution(
        ['demand_distribution', 'duration_balance', 'development_emphasis', 'distribution', 'source_balance'],
        {'demand_distribution': {0: 1}, 'duration_balance': {}, 'distribution': {1: 1},
         'source_balance': {}, 'development_emphasis': {2: 1}},
        [{'goal': 'demand_distribution', 'status': 'optimal', 'value': 1},
         {'goal': 'development_emphasis', 'status': 'optimal', 'value': 4,
          'roleWeeklyWorkingSets': {'role_a': 4}},
         {'goal': 'distribution', 'status': 'feasible', 'value': 2}],
        ['demand_distribution', 'development_emphasis', 'distribution'], [],
        demand_evidence_status='available', development_roles=['role_a'],
        development_budget={'status': 'applied'})

    assert priority_execution['developmentEmphasis']['status'] == 'optimal'


def test_unproven_combined_exposure_downgrades_effective_development_status():
    priority_execution = joint_planning._priority_execution(
        ['development_emphasis', 'distribution', 'source_balance', 'development_exposure', 'preservation'],
        {'distribution': {0: 1}, 'source_balance': {1: 1}, 'preservation': {2: 1},
         'development_emphasis': {3: 1}},
        [{'goal': 'development_emphasis', 'status': 'optimal', 'value': 4,
          'roleWeeklyWorkingSets': {'role_a': 4, 'role_b': 8}},
         {'goal': 'distribution', 'status': 'optimal', 'value': 0},
         {'goal': 'source_balance', 'status': 'feasible', 'value': 1},
         {'goal': 'development_exposure', 'status': 'optimal', 'value': 12,
          'roleWeeklyWorkingSets': {'role_a': 4, 'role_b': 8}},
        ],
        ['development_emphasis', 'distribution', 'source_balance', 'development_exposure', 'preservation'], [],
        development_roles=['role_a', 'role_b'], development_budget={'status': 'applied'})

    assert priority_execution['developmentEmphasis']['solverStage']['status'] == 'optimal'
    assert priority_execution['developmentEmphasis']['combinedExposure']['solverStage']['status'] == 'optimal'
    assert priority_execution['developmentEmphasis']['combinedExposure']['status'] == 'feasible'
    assert priority_execution['developmentEmphasis']['status'] == 'feasible'
    development_priority = next(priority for priority in priority_execution['approvedPriorities']
        if priority['priority'] == 'development_emphasis')
    assert development_priority['status'] == 'optimal'


def test_final_development_exposure_is_reported_separately_from_optimization_stage():
    priority_execution = joint_planning._priority_execution(
        ['development_emphasis'], {'development_emphasis': {0: 1}},
        [{'goal': 'development_emphasis', 'status': 'optimal', 'value': 10,
          'roleWeeklyWorkingSets': {'role_a': 12, 'role_b': 10}}],
        ['development_emphasis'], [], development_roles=['role_a', 'role_b'],
        development_budget={'status': 'applied'})

    joint_planning._finalize_development_exposure(priority_execution, {'role_a': 12, 'role_b': 4})
    development = priority_execution['developmentEmphasis']

    assert development['optimizationStageMinimumWeeklyWorkingSets'] == 10
    assert development['optimizationStageRoleWeeklyWorkingSets'] == {'role_a': 12, 'role_b': 10}
    assert development['minimumWeeklyWorkingSets'] == 4
    assert development['roleWeeklyWorkingSets'] == {'role_a': 12, 'role_b': 4}
    assert development['finalExposureSource'] == 'final_production_audit'




@pytest.mark.parametrize('stale_identity_field', [None, 'requirementsId', 'libraryFingerprint',
                                                  'historyFingerprint', 'preparationId'])
def test_auto_allocation_does_not_treat_generated_worker_seed_as_a_hard_cap(monkeypatch, stale_identity_field):
    from types import SimpleNamespace
    from test_workout_generator_allocation import _audited_messages
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg import allocation
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 7
    messages, result = _audited_messages(equipment, stored, draft)
    assert any(error['code'] == 'volume_above_target' for error in result['errors'])
    current_history = SimpleNamespace(fingerprint='history-current')
    budget = {'source': 'code_preparation_hard_feasible_set_allocation_plus_existing_source_sessions',
              'variableWeeklyWorkingSets': 8, 'preparationId': 'PREP_CURRENT'}
    from workout_generator_pkg import session_drafting
    preparation_arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None}
    source_authority = session_drafting._preparation_authority(
        messages, preparation_arguments, equipment, current_history.fingerprint)
    prepared = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': current_history.fingerprint,
        'preparationId': 'PREP_CURRENT', 'sourceWorkingSetBudget': budget,
        'sourceBudgetAuthority': source_authority}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'prepare_current', 'function': {
            'name': 'prepare_workout_sessions', 'arguments': json.dumps(preparation_arguments)}}]},
        {'role': 'tool', 'tool_call_id': 'prepare_current', 'content': json.dumps(prepared)},
    ])
    worker = {'requirementsId': stored['requirementsId'],
        'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': current_history.fingerprint,
        'baseDraftId': None,
        'preparationId': 'PREP_CURRENT',
        'jointPlanning': {'sourceWorkingSetBudget': budget}}
    if stale_identity_field:
        if stale_identity_field == 'preparationId':
            worker['preparationId'] = 'PREP_OLD'
        elif stale_identity_field == 'requirementsId':
            worker['requirementsId'] = 'REQ_OLD'
        elif stale_identity_field == 'libraryFingerprint':
            worker['libraryFingerprint'] = 'LIBRARY_OLD'
        else:
            worker['historyFingerprint'] = 'history-old'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'session_draft', 'function': {
            'name': 'draft_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'session_draft', 'content': json.dumps(worker)},
    ])
    solve_calls = []

    def solve(*args, **kwargs):
        solve_calls.append(kwargs)
        return {'feasible': False, 'status': 'unproven', 'problemFingerprint': 'fresh',
                'instruction': 'Recomputed with current worker provenance.'}

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    allocated = allocation.auto_allocate_workout(result, equipment, messages,
        training_history=current_history)

    assert solve_calls
    assert solve_calls[0]['source_working_set_budget'] is None
    assert allocated['automaticAllocation']['instruction'] == 'Recomputed with current worker provenance.'
