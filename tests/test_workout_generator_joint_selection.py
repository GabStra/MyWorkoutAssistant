import copy

import pytest
from jsonschema import ValidationError, validate

from workout_generator_pkg import allocation, session_drafting
from workout_generator_pkg.planning_tools import PlanningInputError
from workout_generator_pkg.programming_guidelines import audit_execution_rules, execution_rule_errors


def joint_case():
    credits = {
        'press': {'chest': (1, 0), 'shoulders': (0, .5)},
        'row': {'back': (1, 0), 'shoulders': (0, .5)},
        'overhead': {'shoulders': (1, 0), 'chest': (0, .5)},
        'raise': {'shoulders': (1, 0)},
    }
    candidates = {ref: {'exerciseCategory': 'MODERATE_COMPOUND', 'creditsPerWorkingSet': {
        muscle: dict(zip(('direct', 'indirect'), values)) for muscle, values in muscles.items()}}
        for ref, muscles in credits.items()}
    roles = {'press': 'push', 'row': 'pull', 'overhead': 'vertical', 'raise': 'lateral'}
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        muscle: {'minimum': 15, 'maximum': 18} for muscle in ('chest', 'back', 'shoulders')},
        'perSessionEffectiveSets': {}}, 'requiredCoverage': [
            {'key': key, 'description': key, 'scope': scope} for key, scope in
            [('push', 'eachSession'), ('pull', 'eachSession'), ('vertical', 'weekly'), ('lateral', 'weekly')]]}
    sessions = [{'name': f'Day {i}', 'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': ref, 'numWorkSets': 3, 'allocationBounds': {'minimum': 3, 'maximum': 4},
         'superset': 'PREFERRED', 'satisfiesCoverage': [roles[ref]]} for ref in credits]} for i in range(3)]
    return sessions, candidates, requirements


def solve(sessions, candidates, requirements):
    pool = session_drafting._movement_pool(sessions, candidates, requirements)
    return allocation.allocate_prepared_sets(pool, candidates, requirements, select_movements=True)


def test_joint_selection_removes_invented_limits_and_redundant_weekly_exposures():
    sessions, candidates, requirements = joint_case()
    original = copy.deepcopy(sessions)
    assert not allocation.allocate_prepared_sets(sessions, candidates, requirements)['feasible']
    result = solve(sessions, candidates, requirements)
    assert result['feasible'] and sessions == original
    totals = dict.fromkeys(('chest', 'back', 'shoulders'), 0)
    selected = [item for day in result['sessions'] for item in day['exercises']]
    assert len(selected) < 12
    for day in result['sessions']:
        for item in day['exercises']:
            assert item['numWorkSets'] > 0
            assert item['allocationBounds'] == {'minimum': 1, 'maximum': 20}
            for muscle, values in candidates[item['definition_id']]['creditsPerWorkingSet'].items():
                totals[muscle] += item['numWorkSets'] * sum(values.values())
    assert all(15 <= value <= 18 for value in totals.values())
    # Model-proposed roles are retained in the proposal but are not trusted
    # until recipe qualification; the early solve only proves muscle counts.
    assert 'selectionPreview' not in result


def test_approved_count_rule_is_preserved_by_selection_and_final_audit():
    sessions, candidates, requirements = joint_case()
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': 'vertical',
        'minimumSets': 2, 'maximumSets': 2}]
    assert not execution_rule_errors(requirements)
    result = solve(sessions, candidates, requirements)
    assert result['feasible']
    vertical = [item for day in result['sessions'] for item in day['exercises'] if 'vertical' in item['satisfiesCoverage']]
    assert vertical and all(item['numWorkSets'] == 2 for item in vertical)
    report = {'errors': [], 'issues': []}
    audit_execution_rules({'workouts': result['sessions']}, requirements, report)
    assert not report['errors']
    vertical[0]['numWorkSets'] = 1
    audit_execution_rules({'workouts': result['sessions']}, requirements, report)
    assert report['errors'][0]['code'] == 'execution_workSets'


def test_prequalification_does_not_apply_role_keyed_set_constraints():
    sessions, candidates, requirements = joint_case()
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': 'vertical',
        'minimumSets': 20, 'maximumSets': 20}]
    result = solve(sessions, candidates, requirements)
    assert result['feasible']


def test_joint_placement_fills_daily_coverage_and_counts_frequency():
    sessions, candidates, requirements = joint_case()
    sessions = sessions[:2]
    sessions[0]['timesCompletedInAWeek'] = 2
    sessions[0]['exercises'] = sessions[0]['exercises'][:1]
    sessions[1]['exercises'] = sessions[1]['exercises'][1:2]
    requirements['requiredCoverage'] = requirements['requiredCoverage'][:2]
    requirements['auditTargets']['weeklyEffectiveSets'] = {
        muscle: {'minimum': 6, 'maximum': 6} for muscle in ('chest', 'back')}
    result = solve(sessions, candidates, requirements)
    assert result['feasible']
    for ref in ('press', 'row'):
        assert sum(day['timesCompletedInAWeek'] * item['numWorkSets'] for day in result['sessions']
                   for item in day['exercises'] if item['definition_id'] == ref) == 6


def test_prequalification_selection_does_not_use_unqualified_roles_for_objectives():
    sessions = [{'name': 'Day A', 'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'focus', 'numWorkSets': 2, 'allocationBounds': {'minimum': 1, 'maximum': 5},
         'superset': None, 'satisfiesCoverage': ['focus']},
        {'definition_id': 'support', 'numWorkSets': 3, 'allocationBounds': {'minimum': 1, 'maximum': 5},
         'superset': None, 'satisfiesCoverage': ['support']}]}]
    candidates = {reference: {'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}}}
                  for reference in ('focus', 'support')}
    requirements = {'objectiveOrder': ['source_balance'], 'requiredCoverage': [
        {'key': 'focus', 'scope': 'weekly'}, {'key': 'support', 'scope': 'weekly'}],
        'executionRules': [{'kind': 'coverageBalance', 'first': 'focus', 'second': 'support',
            'scope': 'weekly', 'relationship': 'first_not_less_than_second'}],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 5, 'maximum': 5}},
                         'perSessionEffectiveSets': {}}}

    result = allocation.allocate_prepared_sets(sessions, candidates, requirements, select_movements=True)

    assert result['feasible']
    # Role labels are unqualified here, so they cannot create a hard gate or
    # claim the directional relationship has been met.
    assert 'selectionPreview' not in result


def test_unproven_later_selection_stage_keeps_verified_feasible_menu(monkeypatch):
    sessions = [{'name': 'Day A', 'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'focus', 'numWorkSets': 2, 'allocationBounds': {'minimum': 1, 'maximum': 5},
         'superset': None, 'satisfiesCoverage': ['focus']},
        {'definition_id': 'support', 'numWorkSets': 3, 'allocationBounds': {'minimum': 1, 'maximum': 5},
         'superset': None, 'satisfiesCoverage': ['support']}]}]
    candidates = {reference: {'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}}}
                  for reference in ('focus', 'support')}
    requirements = {'objectiveOrder': ['distribution'], 'requiredCoverage': [
        {'key': 'focus', 'scope': 'weekly'}, {'key': 'support', 'scope': 'weekly'}],
        'executionRules': [{'kind': 'coverageBalance', 'first': 'focus', 'second': 'support',
            'scope': 'weekly', 'relationship': 'first_not_less_than_second'}],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 5, 'maximum': 5}},
                         'perSessionEffectiveSets': {}}}
    original_solve = allocation._milp_solve
    original_objectives = allocation._prepared_selection_objectives
    def two_distribution_stages(*args, **kwargs):
        details = original_objectives(*args, **kwargs)
        details['order'] = ['distribution', 'distribution']
        return details
    monkeypatch.setattr(allocation, '_prepared_selection_objectives', two_distribution_stages)
    stage_calls = 0
    first_stage_counts = None

    def solve_one_stage(variables, features, **kwargs):
        nonlocal stage_calls, first_stage_counts
        stage_calls += 1
        if stage_calls == 1:
            status, counts = original_solve(variables, features, **kwargs)
            first_stage_counts = counts
            return status, counts
        return 'unproven', None

    monkeypatch.setattr(allocation, '_milp_solve', solve_one_stage)
    result = allocation.allocate_prepared_sets(sessions, candidates, requirements, select_movements=True)

    assert stage_calls == 2
    assert first_stage_counts is not None
    assert result['feasible'] and result['solveStatus'] == 'feasible'
    assert {item['definition_id']: item['numWorkSets'] for item in result['sessions'][0]['exercises']} == {
        reference: count for reference, count in zip(('focus', 'support'), first_stage_counts[:2]) if count}
    assert result['selectionPreview']['objectiveStatus'] == 'feasible'
    assert result['selectionPreview']['baselineFeasibleWithinCountDomain']


def test_pre_prescription_selection_distributes_targeted_work_across_sessions():
    sessions = [{'name': f'Day {index}', 'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'press', 'numWorkSets': 5 if index == 0 else 1,
         'allocationBounds': {'minimum': 1, 'maximum': 5}, 'superset': None,
         'satisfiesCoverage': ['push']}]} for index in range(2)]
    candidates = {'press': {'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}}}}
    requirements = {'objectiveOrder': ['distribution'], 'requiredCoverage': [
        {'key': 'push', 'scope': 'eachSession'}], 'executionRules': [],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 6, 'maximum': 6}},
                         'perSessionEffectiveSets': {}}}

    result = allocation.allocate_prepared_sets(sessions, candidates, requirements, select_movements=True)

    assert result['feasible']
    assert [day['exercises'][0]['numWorkSets'] for day in result['sessions']] == [3, 3]
    objective = result['selectionPreview']['objectives'][0]
    assert objective['priority'] == 'distribution'
    assert objective['proposalCost'] == 0 < objective['baselineCost']


def test_pre_prescription_preview_does_not_report_unqualified_role_comparisons():
    sessions = [{'name': 'Day A', 'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': reference, 'numWorkSets': 1, 'allocationBounds': {'minimum': 1, 'maximum': 5},
         'superset': None, 'satisfiesCoverage': [reference]} for reference in ('focus', 'support')]}]
    candidates = {reference: {'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}}}
                  for reference in ('focus', 'support')}
    requirements = {'objectiveOrder': ['distribution'], 'requiredCoverage': [
        {'key': 'focus', 'scope': 'weekly'}, {'key': 'support', 'scope': 'weekly'}],
        'executionRules': [{'kind': 'coverageBalance', 'first': 'focus', 'second': 'support',
            'scope': 'weekly', 'relationship': 'balanced'}],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 5, 'maximum': 5}},
                         'perSessionEffectiveSets': {}}}

    result = allocation.allocate_prepared_sets(sessions, candidates, requirements, select_movements=True)

    assert result['feasible']
    assert not result['selectionPreview']['baselineFeasibleWithinCountDomain']
    assert result['selectionPreview']['roleComparisons'] == []


def test_solver_timeout_and_invalid_solution_cannot_approve_selection(monkeypatch):
    sessions, candidates, requirements = joint_case()
    monkeypatch.setattr(allocation, '_milp_solve', lambda *a, **k: ('unproven', None))
    assert solve(sessions, candidates, requirements)['status'] == 'unproven'
    monkeypatch.setattr(allocation, '_milp_solve', lambda variables, *a, **k: ('optimal', [0] * len(variables)))
    result = solve(sessions, candidates, requirements)
    assert not result['feasible'] and result['status'] == 'unverified'


@pytest.mark.parametrize('candidate,accepted', [(3, True), (3.5, False), (1, False), (0, False), (21, False)])
def test_bounded_solver_accepts_only_independently_verified_incumbents(monkeypatch, candidate, accepted):
    from types import SimpleNamespace
    monkeypatch.setattr(allocation, 'milp', lambda *a, **k: SimpleNamespace(status=1, x=[candidate]))
    variables = [{'lower': 0, 'upper': 20, 'minimumWhenSelected': 2, 'current': [3], 'members': [{}]}]
    features = [(('weekly', 'chest'), 2, 4, 0, [1])]
    status, counts = allocation._milp_solve(variables, features)
    assert (status, counts) == (('feasible', [3]) if accepted else ('unproven', None))


def test_movement_api_cannot_submit_hard_counts():
    block = session_drafting.PREPARE_WORKOUT_SESSIONS_TOOL['function']['parameters']['properties']['sessions']['items']['properties']['blocks']['items']
    assert 'allocationBounds' not in block['properties'] and 'numWorkSets' not in block['properties']
    with pytest.raises(ValidationError):
        validate({'exercises': [{'definition_id': 'LIBRARY_0'}],
                  'allocationBounds': {'minimum': 3, 'maximum': 4}}, block)


def test_resume_revalidates_obsolete_failure_without_reselecting_or_changing_source():
    from test_workout_generator_week_structure import prepared_case
    from test_workout_generator_parallel_planning import store_tool
    equipment, _, messages, arguments, _ = prepared_case()
    store_tool(messages, 'prepare_workout_sessions', arguments, {'draftingVersion': 1,
        'preparationArguments': arguments, 'errors': [{'code': 'infeasible_set_allocation'}]})
    messages.append({'role': 'user', 'content': '/continue'})
    before = copy.deepcopy(messages)
    replayed, result = session_drafting.revalidate_saved_preparation(messages, equipment)
    assert replayed == arguments and messages == before
    assert result['draftingVersion'] == session_drafting.DRAFTING_VERSION
    assert result['setAllocation']['feasible']
    store_tool(messages, 'prepare_workout_sessions', replayed, result)
    assert session_drafting.revalidate_saved_preparation(messages, equipment) is None
    messages[-1]['content'] = before[-2]['content']
    messages.append({'role': 'user', 'content': 'Change my goals instead.'})
    assert session_drafting.revalidate_saved_preparation(messages, equipment) is None


def test_unproven_preparation_pauses_and_preserves_the_proposal(monkeypatch):
    from test_workout_generator_week_structure import prepared_case
    from workout_generator_pkg.planning_tools import planning_tool_failure
    equipment, _, messages, arguments, _ = prepared_case()
    monkeypatch.setattr(allocation, '_milp_solve', lambda *a, **k: ('unproven', None))
    with pytest.raises(PlanningInputError) as caught:
        session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert caught.value.code == 'set_allocation_unproven'
    result = planning_tool_failure('prepare_workout_sessions', caught.value, arguments)
    assert result['executionFailure'] and result['preparationArguments']
    assert 'do not claim infeasibility' in result['instruction']


def test_metadata_edit_reuses_verified_allocation_without_moving_exercises(monkeypatch):
    from test_workout_generator_week_structure import prepared_case
    from test_workout_generator_parallel_planning import store_tool
    equipment, _, messages, arguments, _ = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', arguments, prepared)
    edit = {key: copy.deepcopy(prepared[key]) for key in ('requirementsId', 'baseDraftId', 'name', 'sessions')}
    edit['sessions'][1]['description'] = 'Updated focus'
    monkeypatch.setattr(allocation, 'allocate_prepared_sets', lambda *a, **k: pytest.fail('Metadata must not rerun selection'))
    updated = session_drafting.prepare_workout_sessions(edit, messages, equipment)
    assert updated['preparationId'] != prepared['preparationId']
    assert updated['sessions'][1]['description'] == 'Updated focus'
    assert [d['exercises'] for d in updated['sessions']] == [d['exercises'] for d in prepared['sessions']]
