import copy
import json

import pytest
from jsonschema import Draft7Validator

from workout_generator_pkg import session_drafting
from workout_generator_pkg.planning_tools import PlanningInputError, planning_tool_failure, set_workout_requirements
from test_workout_generator_planning_tools import planning_case, capability_requirement_messages


def shortlist_case():
    equipment, requirements, _, _ = planning_case()
    requirements.update(sessionsPerWeek=3, minimumRestDaysBetweenSessions=1)
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 15}
    requirements['executionRules'] = [
        {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 5, 'maximumSets': 5}]
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Three sessions, exactly five sets per exercise, fifteen weekly chest sets.'}], equipment)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'definition_ids': ['LIBRARY_0']}
    return equipment, capability_requirement_messages(stored, equipment), arguments


def test_weekly_shortlist_wire_shape_is_only_selection():
    equipment, messages, arguments = shortlist_case()
    tool = session_drafting.prepare_workout_sessions_tool(messages, equipment,
        selection_options={'admissibleDefinitionIds': ['LIBRARY_0']})
    schema = tool['function']['parameters']
    assert set(schema['properties']) == {'requirementsId', 'baseDraftId', 'definition_ids'}
    assert schema['properties']['requirementsId']['const'] == arguments['requirementsId']
    assert schema['properties']['baseDraftId']['const'] is None
    validator = Draft7Validator(schema)
    validator.validate(arguments)
    for key, value in [('sessions', []), ('numWorkSets', 3), ('trainingDays', [0, 2, 4]),
                       ('blocks', []), ('satisfiesCoverage', []), ('name', 'Model name')]:
        assert not validator.is_valid({**arguments, key: value})
    assert not validator.is_valid({**arguments, 'definition_ids': ['LIBRARY_0', 'LIBRARY_0']})
    assert not validator.is_valid({**arguments, 'definition_ids': ['LIBRARY_1']})


def test_weekly_shortlist_expands_and_solves_without_inventing_a_source_cap():
    equipment, messages, arguments = shortlist_case()
    original = copy.deepcopy(arguments)
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert arguments == original
    assert len(prepared['sessions']) == 3
    assert all(day['timesCompletedInAWeek'] == 1 for day in prepared['sessions'])
    assert all([item['definition_id'] for item in day['exercises']] == ['LIBRARY_0']
        for day in prepared['recipeSessions'])
    assert [day['exercises'][0]['numWorkSets'] for day in prepared['sessions']] == [5, 5, 5]
    assert all(day['exercises'][0]['allocationBounds'] == {'minimum': 5, 'maximum': 5}
        for day in prepared['sessions'])
    assert prepared['sourceWorkingSetBudget'] == {
        'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}
    assert prepared['setAllocation']['feasible']
    assert sorted(weekday for day in prepared['sessions'] for weekday in day['trainingDays']) == [0, 2, 4]


def test_weekly_shortlist_creates_only_remaining_slots_and_preserves_fixed_workouts(monkeypatch):
    equipment, messages, arguments = shortlist_case()
    fixed = {'name': 'Accepted program', 'workouts': [
        {'name': 'Accepted session', 'timesCompletedInAWeek': 2,
         'trainingDays': [0, 3], 'exercises': [{'definition_id': 'LIBRARY_0', 'numWorkSets': 5}]}]}
    original = copy.deepcopy(fixed)
    monkeypatch.setattr(session_drafting, 'latest_draft_submission', lambda *_: (fixed, 'REVISION_1'))
    arguments['baseDraftId'] = 'REVISION_1'
    expanded = session_drafting._expand_weekly_shortlist(arguments, messages, equipment)
    assert len(expanded['sessions']) == 1
    assert expanded['name'] == fixed['name']
    assert fixed == original
    arguments['baseDraftId'] = None
    with pytest.raises(ValueError, match='stale'):
        session_drafting._expand_weekly_shortlist(arguments, messages, equipment)


def test_weekly_shortlist_keeps_configuration_suitability_gate(monkeypatch):
    equipment, messages, arguments = shortlist_case()
    concern = {'code': 'training_load_suitability_unresolved', 'message': 'Unverified fixed bodyweight capability.'}
    monkeypatch.setattr(session_drafting, '_history_configuration_concerns',
        lambda *_: {'LIBRARY_0': concern})
    with pytest.raises(PlanningInputError) as rejected:
        session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert rejected.value.code == 'training_load_suitability_unresolved'


def store_preparation(messages, arguments, result):
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'shortlist', 'function': {
            'name': 'prepare_workout_sessions', 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': 'shortlist', 'content': json.dumps(result)}])


def test_weekly_shortlist_rejection_retains_selection_and_repairs_only_definition_ids(monkeypatch):
    equipment, messages, arguments = shortlist_case()
    def reject(*_, **__):
        error = PlanningInputError('infeasible_set_allocation', 'The selected pool is infeasible.',
            '/sessions', 'Choose alternatives.', errors=[{'code': 'infeasible_set_allocation', 'path': '/sessions'}])
        error.preparation_arguments = {'sessions': [{'exercises': []}]}
        raise error
    monkeypatch.setattr(session_drafting, '_prepare_week', reject)
    with pytest.raises(PlanningInputError) as rejected:
        session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    failure = planning_tool_failure('prepare_workout_sessions', rejected.value, arguments)
    assert failure['preparationArguments'] == arguments
    store_preparation(messages, arguments, failure)
    monkeypatch.setattr(session_drafting, 'preparation_selection_options',
        lambda *_: {'admissibleDefinitionIds': ['LIBRARY_0', 'LIBRARY_1']})
    task = session_drafting.preparation_repair_task(messages, equipment)
    assert task['arguments'] == arguments and task['blockRepair'] is None
    assert task['permittedPaths'] == ['/definition_ids']
    tool = session_drafting.preparation_patch_tool(task)
    assert set(tool['function']['parameters']['properties']) == {'basePreparationId', 'definition_ids'}
    correction = {'basePreparationId': task['basePreparationId'], 'definition_ids': ['LIBRARY_1']}
    assert session_drafting.resolve_preparation_patch(correction, messages, equipment) == {
        **arguments, 'definition_ids': ['LIBRARY_1']}
    with pytest.raises(PlanningInputError, match='must change'):
        session_drafting.resolve_preparation_patch({**correction, 'definition_ids': ['LIBRARY_0']}, messages, equipment)


def test_weekly_shortlist_capability_failure_does_not_create_a_selection_retry(monkeypatch):
    equipment, messages, arguments = shortlist_case()
    failure = {'preparationArguments': arguments, 'errors': [
        {'code': 'training_load_suitability_unresolved', 'path': '/sessions/0/exercises/0'}]}
    store_preparation(messages, arguments, failure)
    assert session_drafting.preparation_repair_task(messages, equipment) is None
