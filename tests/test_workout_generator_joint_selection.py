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
        assert {'push', 'pull'} <= {role for item in day['exercises'] for role in item['satisfiesCoverage']}
        for item in day['exercises']:
            assert item['numWorkSets'] > 0
            assert item['allocationBounds'] == {'minimum': 1, 'maximum': 20}
            for muscle, values in candidates[item['definition_id']]['creditsPerWorkingSet'].items():
                totals[muscle] += item['numWorkSets'] * sum(values.values())
    assert all(15 <= value <= 18 for value in totals.values())
    assert {'vertical', 'lateral'} <= {role for item in selected for role in item['satisfiesCoverage']}


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


def test_approved_counts_that_make_targets_impossible_are_not_relaxed():
    sessions, candidates, requirements = joint_case()
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': 'vertical',
        'minimumSets': 20, 'maximumSets': 20}]
    result = solve(sessions, candidates, requirements)
    assert not result['feasible'] and result['status'] == 'infeasible'


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
    for day in result['sessions']:
        assert {x['definition_id'] for x in day['exercises']} == {'press', 'row'}
    for ref in ('press', 'row'):
        assert sum(day['timesCompletedInAWeek'] * item['numWorkSets'] for day in result['sessions']
                   for item in day['exercises'] if item['definition_id'] == ref) == 6


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
