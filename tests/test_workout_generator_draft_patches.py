import copy
import json

import pytest
from jsonschema import ValidationError

from workout_generator_pkg.interactive_shell import _messages_for_api
from workout_generator_pkg.json_patching import apply_json_patch
from workout_generator_pkg.planning_tools import (
    PlanningInputError, audit_workout_plan, latest_draft_submission, planning_tool_failure, set_workout_requirements,
)
from test_workout_generator_planning_tools import planning_case, requirement_messages


def store(messages, arguments, result, key):
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': key, 'function': {
            'name': 'audit_workout_plan', 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(result)}])


def patch_for(result, operations):
    return {'requirementsId': result['requirementsId'], 'baseDraftId': result['currentDraftId'], 'patch': operations}


def test_patch_repairs_volume_and_keeps_untouched_prescriptions_across_resume():
    equipment, _, stored, draft = planning_case()
    exercise = draft['workouts'][0]['exercises'][0]
    exercise['targetSetPrescriptions'] = [
        {'workSetIndex': i, 'reps': reps, 'additionalWeight': 0} for i, reps in enumerate([10, 9, 8, 8, 8])]
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    store(messages, draft, initial, 'initial')
    patch = patch_for(initial, [{'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Updated setup.'}])
    repaired = audit_workout_plan(patch, equipment, messages)
    expected = copy.deepcopy(draft)
    expected['workouts'][0]['exercises'][0]['placementNotes'] = 'Updated setup.'
    assert repaired['passed'] and repaired['submittedDraft'] == expected
    assert initial['currentDraftId'] == 'REVISION_0' and repaired['currentDraftId'] == 'REVISION_1'
    store(messages, patch, repaired, 'patch')
    resumed = json.loads(json.dumps(messages))
    assert latest_draft_submission(resumed, equipment) == (expected, 'REVISION_1')
    outgoing = _messages_for_api(resumed, True, provided_equipment=equipment)
    state = json.loads(next(m['content'].split('\n', 1)[1] for m in outgoing if m.get('content', '').startswith('Current planning state')))
    assert state['currentDraft'] == expected and state['currentDraftId'] == 'REVISION_1'
    assert json.dumps(outgoing).count('Updated setup.') == 1
    assert draft['workouts'][0]['exercises'][0]['placementNotes'] == 'Controlled reps.'


def test_structurally_invalid_draft_remains_patchable_without_changing_other_sets():
    equipment, _, stored, draft = planning_case()
    exercise = draft['workouts'][0]['exercises'][0]
    exercise['targetSetPrescriptions'] = [
        {'workSetIndex': i, 'reps': reps, 'additionalWeight': 0} for i, reps in enumerate([10, 9, 8, 8, 7])]
    messages = requirement_messages(stored)
    with pytest.raises(PlanningInputError) as caught:
        audit_workout_plan(draft, equipment, messages)
    failure = planning_tool_failure('audit_workout_plan', caught.value, draft)
    assert failure['currentDraftId'] == 'REVISION_0'
    store(messages, draft, failure, 'invalid')
    patch = patch_for({**failure, 'requirementsId': draft['requirementsId']}, [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/targetSetPrescriptions/4/reps', 'value': 8}])
    result = audit_workout_plan(patch, equipment, messages)
    assert result['passed']
    assert [s['reps'] for s in result['submittedDraft']['workouts'][0]['exercises'][0]['targetSetPrescriptions']] == [10, 9, 8, 8, 8]


def test_patch_numerical_failure_is_saved_and_can_be_repaired_again():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    store(messages, draft, initial, 'initial')
    patch = patch_for(initial, [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 3}])
    failed = audit_workout_plan(patch, equipment, messages)
    assert not failed['passed'] and failed['currentDraftId'] == 'REVISION_1'
    store(messages, patch, failed, 'failed')
    repair = patch_for(failed, [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 5}])
    assert audit_workout_plan(repair, equipment, messages)['passed']
    with pytest.raises(PlanningInputError, match='stale'):
        audit_workout_plan(patch, equipment, messages)


def test_partial_repair_cannot_hide_another_sessions_volume_failure():
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 2
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 12}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content':
        'Two sessions, 5-6 chest sets each, 10-12 per week.'}])
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    draft['workouts'].append(copy.deepcopy(draft['workouts'][0]))
    draft['workouts'][1]['name'] = 'Day B'
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    store(messages, draft, initial, 'initial')
    first_patch = patch_for(initial, [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 5}])
    partial = audit_workout_plan(first_patch, equipment, messages)
    assert not partial['passed'] and 'preview' not in partial
    assert any(error.get('path') == '/workouts/1/exercises' for error in partial['errors'])
    store(messages, first_patch, partial, 'partial')
    second_patch = patch_for(partial, [{'op': 'replace', 'path': '/workouts/1/exercises/0/numWorkSets', 'value': 5}])
    complete = audit_workout_plan(second_patch, equipment, messages)
    assert complete['passed'] and complete['audit']['weeklyVolume']['chest']['effective'] == 10


@pytest.mark.parametrize('operation', [
    {'op': 'replace', 'path': '/requirementsId', 'value': 'invented'},
    {'op': 'replace', 'path': '', 'value': {}},
    {'op': 'replace', 'path': '/workouts/0/exercises/99/numWorkSets', 'value': 5},
    {'op': 'replace', 'path': '/workouts/0/exercises/0/muscleGroups', 'value': []},
    {'op': 'test', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 99},
])
def test_invalid_patch_is_atomic_and_keeps_previous_revision(operation):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    store(messages, draft, initial, 'initial')
    before = copy.deepcopy(messages)
    patch = patch_for(initial, [{'op': 'replace', 'path': '/name', 'value': 'Must roll back'}, operation])
    with pytest.raises(PlanningInputError) as caught:
        audit_workout_plan(patch, equipment, messages)
    failure = planning_tool_failure('audit_workout_plan', caught.value, patch)
    assert 'submittedDraft' not in failure and messages == before
    store(messages, patch, failure, 'failed-patch')
    assert latest_draft_submission(messages, equipment) == (draft, initial['currentDraftId'])


@pytest.mark.parametrize('failure_kind', ['schema', 'requirements', 'cancelled'])
def test_rejected_full_submission_keeps_the_existing_patch_base_across_resume(failure_kind):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    store(messages, draft, initial, 'initial')
    rejected = copy.deepcopy(draft)
    if failure_kind == 'cancelled':
        failure = 'Tool execution cancelled by the user. Do not treat this as a successful result.'
    else:
        if failure_kind == 'schema':
            del rejected['name']
        else:
            rejected['requirementsId'] = 'not-approved'
        with pytest.raises((ValidationError, PlanningInputError)) as caught:
            audit_workout_plan(rejected, equipment, messages)
        failure = planning_tool_failure('audit_workout_plan', caught.value, rejected)
        assert 'submittedDraft' not in failure
    store(messages, rejected, failure, 'rejected')
    if failure_kind == 'cancelled':
        messages[-1]['content'] = failure
    resumed = json.loads(json.dumps(messages))
    assert latest_draft_submission(resumed, equipment) == (draft, initial['currentDraftId'])
    patch = patch_for(initial, [{'op': 'replace', 'path': '/name', 'value': 'Valid repair'}])
    result = audit_workout_plan(patch, equipment, resumed)
    assert result['passed'] and result['currentDraftId'] == 'REVISION_1'
    assert result['submittedDraft']['name'] == 'Valid repair'


def test_changed_library_rejects_patch_before_reinterpreting_library_references():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    store(messages, draft, initial, 'initial')
    changed = copy.deepcopy(equipment)
    changed['exerciseDefinitions'][0]['name'] = 'Changed movement'
    with pytest.raises(PlanningInputError, match='stale'):
        audit_workout_plan(patch_for(initial, []), changed, messages)


def test_newly_approved_requirements_can_reuse_draft_but_unapproved_ids_cannot():
    equipment, requirements, stored, draft = planning_case()
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    store(messages, draft, initial, 'initial')
    invalid = {**patch_for(initial, []), 'requirementsId': 'not-approved'}
    with pytest.raises(PlanningInputError, match='current requirementsId'):
        audit_workout_plan(invalid, equipment, messages)
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 6, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 6, 'maximum': 6}
    updated = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Raise chest targets to six sets.'}])
    messages.extend(requirement_messages(updated))
    outgoing = _messages_for_api(messages, True, provided_equipment=equipment)
    state = json.loads(next(m['content'].split('\n', 1)[1] for m in outgoing if m.get('content', '').startswith('Current planning state')))
    assert state['currentDraft'] == draft and state['currentDraftId'] == initial['currentDraftId']
    assert state['requirementsId'] == updated['requirementsId'] and state['draftRequiresReaudit']
    patch = {**patch_for(initial, [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 6}]),
             'requirementsId': updated['requirementsId']}
    result = audit_workout_plan(patch, equipment, messages)
    assert result['passed'] and result['submittedDraft']['requirementsId'] == updated['requirementsId']


def test_legacy_full_submission_can_be_patched_without_regeneration():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    store(messages, draft, {'passed': False, 'errors': []}, 'legacy')
    result = audit_workout_plan({'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Legacy repair.'}]}, equipment, messages)
    assert result['passed'] and result['currentDraftId'] == 'REVISION_1'


def test_rfc6902_array_insertion_move_copy_null_and_escaped_paths():
    original = {'items': [1, 3], 'a/b': {'~key': None}}
    result = apply_json_patch(original, [
        {'op': 'add', 'path': '/items/1', 'value': 2},
        {'op': 'add', 'path': '/items/-', 'value': 4},
        {'op': 'move', 'from': '/items/0', 'path': '/items/2'},
        {'op': 'copy', 'from': '/a~1b/~0key', 'path': '/copied'},
        {'op': 'test', 'path': '/copied', 'value': None},
        {'op': 'remove', 'path': '/a~1b/~0key'},
    ])
    assert result == {'items': [2, 3, 1, 4], 'a/b': {}, 'copied': None}
    assert original == {'items': [1, 3], 'a/b': {'~key': None}}


@pytest.mark.parametrize('operation', [
    {'op': 'unsupported', 'path': '/value'},
    {'op': 'replace', 'path': '/missing', 'value': 1},
    {'op': 'remove', 'path': '/missing'},
    {'op': 'add', 'path': '/missing/child', 'value': 1},
    {'op': 'add', 'path': '/items/01', 'value': 1},
    {'op': 'replace', 'path': '/value'},
    {'op': 'replace', 'path': '/bad~2escape', 'value': 1},
    {'op': 'test', 'path': '/value', 'value': True},
    {'op': 'move', 'from': '/items', 'path': '/items/0'},
])
def test_invalid_rfc6902_operations_never_modify_source(operation):
    original = {'value': 1, 'items': [0]}
    with pytest.raises(ValueError):
        apply_json_patch(original, [{'op': 'replace', 'path': '/value', 'value': 2}, operation])
    assert original == {'value': 1, 'items': [0]}
