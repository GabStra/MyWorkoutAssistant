import copy
import json

import pytest
from jsonschema import ValidationError, validate

from workout_generator_pkg import allocation, api_client, plan_review, session_drafting
from workout_generator_pkg.planner_context import planner_response_profile
from workout_generator_pkg.planning_tools import (
    REPAIR_WORKOUT_PLAN_TOOL, _EXERCISE, PlanningInputError, audit_workout_plan,
    metadata_patch_tool, planning_failure_signature,
)
from test_workout_generator_planning_tools import planning_case, requirement_messages
from test_workout_generator_parallel_planning import store_tool
from test_workout_generator_week_structure import prepared_case


@pytest.fixture(autouse=True)
def qualified_recipe_fixture(monkeypatch):
    # Recipe qualification has dedicated tests; these tests isolate drafting/repair behavior.
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *args, **kwargs: {'inputHash': 'qualified-fixture', 'contracts': [], 'capabilities': {}})


def test_movement_selection_leaves_arithmetic_to_allocator_and_preserves_source_state():
    from workout_generator_pkg.interactive_shell import _messages_for_api
    from workout_generator_pkg.planner_context import request_planning_state
    equipment, requirements, messages, arguments, _ = prepared_case()
    before = copy.deepcopy(messages)
    # Retain a selectable movement, including the numerical credits returned by discovery.
    from workout_generator_pkg.exercise_library_tools import get_exercise_candidates
    result = get_exercise_candidates({'definition_ids': ['LIBRARY_0']}, equipment, messages)
    store_tool(messages, 'get_exercise_candidates', {'definition_ids': ['LIBRARY_0']}, result)
    saved = copy.deepcopy(messages)
    state = request_planning_state(_messages_for_api(messages, True, provided_equipment=equipment))
    assert state['constructionTask']['stage'] == 'choose_movements'
    assert state['requirements']['auditTargets']['weeklyEffectiveSets'] == requirements['auditTargets']['weeklyEffectiveSets']
    assert state['requirements']['auditTargets']['maximumSessionSeconds'] == requirements['auditTargets']['maximumSessionSeconds']
    candidate = state['exerciseCandidates']['LIBRARY_0']
    assert candidate['creditsPerWorkingSet'] == result['exercises'][0]['creditsPerWorkingSet']
    assert candidate['muscleGroups'] == ['FRONT_CHEST']
    profile = planner_response_profile(state)
    assert profile['reasoning_effort'] is None and profile['activity'] == 'Selecting weekly movements'
    assert messages == saved and messages[:len(before)] == before
    # The backend still checks every numerical target against the selected structure.
    impossible = copy.deepcopy(arguments)
    from workout_generator_pkg.planning_tools import set_workout_requirements
    limited = set_workout_requirements({**requirements, 'executionRules': [
        {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 1, 'maximumSets': 1}]},
        [{'role': 'user', 'content': 'Exactly one set per exercise.'}], equipment)
    messages = requirement_messages(limited)
    impossible['requirementsId'] = limited['requirementsId']
    for day in impossible['sessions']:
        day['exercises'][0]['allocationBounds'] = {'minimum': 1, 'maximum': 1}
        day['exercises'][0]['numWorkSets'] = 1
    with pytest.raises(PlanningInputError) as caught:
        session_drafting.prepare_workout_sessions(impossible, messages, equipment)
    assert caught.value.code == 'infeasible_set_allocation'
    from workout_generator_pkg.planning_tools import planning_tool_failure, _latest_result
    store_tool(messages, 'prepare_workout_sessions', impossible,
               planning_tool_failure('prepare_workout_sessions', caught.value, impossible))
    repair_state = request_planning_state(_messages_for_api(messages, True, provided_equipment=equipment))
    assert repair_state['preparationRepairTask']['needsAlternatives']
    assert planner_response_profile(repair_state)['reasoning_effort'] is None
    assert repair_state['requirements']['auditTargets']['weeklyEffectiveSets'] == requirements['auditTargets']['weeklyEffectiveSets']
    assert repair_state['exerciseCandidates']['LIBRARY_0']['muscleGroups'] == ['FRONT_CHEST']
    _, retained = _latest_result(messages, 'set_workout_requirements')
    assert retained['requirements']['auditTargets']['weeklyEffectiveSets'] == requirements['auditTargets']['weeklyEffectiveSets']


def test_prepared_session_stage_keeps_prescription_reasoning_budget():
    profile = planner_response_profile({'constructionTask': {'stage': 'draft_sessions', 'remainingWeeklySessions': 3}})
    assert profile['reasoning_effort'] == 'low' and profile['activity'] == 'Drafting session'


def test_movement_repair_uses_solver_feedback_without_restarting_extended_reasoning():
    profile = planner_response_profile({'preparationRepairTask': {'needsAlternatives': True,
        'errors': [{'code': 'infeasible_set_allocation', 'path': '/sessions'}]}})
    assert profile['reasoning_effort'] is None and profile['activity'] == 'Repairing weekly selection'
    assert profile['max_tokens'] == 16384


def test_retry_identity_ignores_preparation_receipts_and_overwritten_note_operations():
    failures = [{'code': 'export_description_too_long', 'path': '/sessions/0/description'}]
    feedback = {'preparationArguments': {'sessions': [{'description': 'Too long'}]}, 'errors': failures}
    assert planning_failure_signature('prepare_workout_sessions', {'basePreparationId': 'PREPARATION_1'}, feedback, []) == \
        planning_failure_signature('prepare_workout_sessions', {'basePreparationId': 'PREPARATION_3'}, feedback, [])
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    store_tool(messages, 'audit_workout_plan', draft, result)
    path = '/workouts/0/exercises/0/placementNotes'
    patch = {'requirementsId': stored['requirementsId'], 'baseDraftId': result['currentDraftId'],
             'patch': [{'op': 'replace', 'path': path, 'value': 'Too long'}]}
    first = {'errors': failures, 'rejectedSubmission': patch}
    accumulated = copy.deepcopy(first)
    accumulated['rejectedSubmission']['patch'].append(copy.deepcopy(patch['patch'][0]))
    assert planning_failure_signature('audit_workout_plan', patch, first, messages) == \
        planning_failure_signature('audit_workout_plan', accumulated['rejectedSubmission'], accumulated, messages)
    accumulated['rejectedSubmission']['patch'][-1]['value'] = 'Shorter'
    assert planning_failure_signature('audit_workout_plan', patch, first, messages) != \
        planning_failure_signature('audit_workout_plan', accumulated['rejectedSubmission'], accumulated, messages)


@pytest.mark.parametrize('arguments', [None, [], 'invalid'])
def test_retry_identity_preserves_invalid_non_object_arguments(arguments):
    feedback = {'errors': [{'code': 'invalid_arguments', 'path': '/'}]}
    signature = planning_failure_signature('audit_workout_plan', arguments, feedback, [])
    assert json.loads(signature)[1] == arguments


def test_metadata_tool_enforces_the_actual_field_budget_without_mutating_shared_schema():
    original = copy.deepcopy(REPAIR_WORKOUT_PLAN_TOOL)
    path = '/workouts/0/exercises/0/placementNotes'
    tool = metadata_patch_tool(REPAIR_WORKOUT_PLAN_TOOL, {path: {'maximumCharacters': 226}})
    args = {'requirementsId': 'R', 'baseDraftId': 'REVISION_1',
            'patch': [{'op': 'replace', 'path': path, 'value': 'x' * 226}]}
    validate(args, tool['function']['parameters'])
    args['patch'][0]['value'] += 'x'
    with pytest.raises(ValidationError):
        validate(args, tool['function']['parameters'])
    args['patch'][0].update(path='/workouts/1/description', value='Short')
    with pytest.raises(ValidationError):
        validate(args, tool['function']['parameters'])
    assert REPAIR_WORKOUT_PLAN_TOOL == original


def test_first_preparation_rejection_contains_usable_budget_purpose_and_repair_scope():
    from workout_generator_pkg.planning_tools import planning_tool_failure
    equipment, _, messages, arguments, _ = prepared_case()
    arguments['sessions'][0].update(description='Front squat, bench/row, hip hinge, lateral delts, arms, calves', trainingDays=[0])
    arguments['sessions'][1].update(description='Overhead press, split squat, row/floor press, chin-up, Nordic curl', trainingDays=[2])
    with pytest.raises(PlanningInputError) as caught:
        session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    feedback = planning_tool_failure('prepare_workout_sessions', caught.value, arguments)
    assert [error['expected'] for error in feedback['errors']] == [32, 29]
    assert all('textFieldContract' in error for error in feedback['errors'])
    store_tool(messages, 'prepare_workout_sessions', arguments, feedback)
    task = session_drafting.preparation_repair_task(messages)
    assert len(task['metadataFields']) == len(task['errors']) == 2
    for field in task['metadataFields'].values():
        assert field['maximumCharacters'] + field['reservedCharacters'] == 50
        assert field['charactersToRemove'] == field['currentCharacters'] - field['maximumCharacters']
        assert 'not an exercise list' in field['purpose'] and field['repair']
    repaired = session_drafting.prepare_workout_sessions({'basePreparationId': task['basePreparationId'], 'patch': [
        {'op': 'replace', 'path': path, 'value': field['example']} for path, field in task['metadataFields'].items()]}, messages, equipment)
    assert repaired['sessions'][0]['description'] == 'Full body'
    assert repaired['sessions'][1]['description'] == 'Full body'


def test_workout_citation_permits_description_fix_without_authorizing_other_sessions():
    equipment, _, messages, arguments, _ = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', arguments, prepared)
    store_tool(messages, 'draft_workout_sessions', {}, {'preparationId': prepared['preparationId'],
        'structureReview': {'version': plan_review.STRUCTURE_REVIEW_VERSION, 'passed': False, 'findings': [{'severity': 'blocking', 'path': '/draft/workouts/0',
            'evidencePaths': ['/draft/workouts/0'], 'message': 'Description names the wrong movement.',
            'repair': 'Correct the description.'}]}})
    task = session_drafting.preparation_repair_task(messages)
    repair = {'basePreparationId': task['basePreparationId'], 'patch': [
        {'op': 'replace', 'path': '/sessions/0/description', 'value': 'Push'}]}
    corrected = session_drafting.resolve_preparation_patch(repair, messages)
    assert corrected['sessions'][0]['exercises'] == prepared['sessions'][0]['exercises']
    repair['patch'][0]['path'] = '/sessions/1/description'
    with pytest.raises(PlanningInputError, match='outside|not one of'):
        session_drafting.resolve_preparation_patch(repair, messages)


def test_allocator_identifies_forced_counts_and_releases_them_when_placement_changes():
    candidates = {'LIBRARY_0': {'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}}}}
    item = {'definition_id': 'LIBRARY_0', 'numWorkSets': 3, 'superset': None,
            'allocationBounds': {'minimum': 1, 'maximum': 20}}
    sessions = [{'timesCompletedInAWeek': 1, 'exercises': [item]},
                {'timesCompletedInAWeek': 1, 'exercises': []}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 15, 'maximum': 18}},
                                    'perSessionEffectiveSets': {}}}
    before = copy.deepcopy(sessions)
    result = allocation.allocate_prepared_sets(sessions, candidates, requirements)
    assert result['sessions'][0]['exercises'][0]['numWorkSets'] == 15
    assert result['allocationDiagnostics'][0]['minimumRequiredSets'] == 15
    sessions[1]['exercises'].append(copy.deepcopy(item))
    spread = allocation.allocate_prepared_sets(sessions, candidates, requirements)
    assert sorted(day['exercises'][0]['numWorkSets'] for day in spread['sessions']) == [7, 8]
    assert not spread['allocationDiagnostics']
    assert sessions[0] == before[0]


def test_review_distinguishes_builtin_progression_from_local_notes_and_maps_repairs():
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0].update(progressionMethod='reps', placementNotes='Keep the body rigid.')
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed']
    reviewed = plan_review._compact_review_draft(result['planIndex'], equipment, draft)
    authority = reviewed['exercises'][0]['coachingAuthority']
    assert authority['localNotes'] == 'Keep the body rigid.'
    assert 'Stop at the rep ceiling' in authority['generatedProgression']
    assert reviewed['exercises'][0]['placementNotes'] == 'Keep the body rigid.'
    assert reviewed['exercises'][0]['renderedGuidance'] == result['planIndex']['exercises'][0]['placementNotes']
    assert authority['generatedProgression'] in reviewed['exercises'][0]['renderedGuidance']
    assert plan_review._draft_patch_path('/draft/exercises/0/coachingAuthority/generatedProgression',
        result['planIndex'], draft) is None
    assert plan_review._draft_patch_path('/draft/exercises/0/renderedGuidance',
        result['planIndex'], draft) is None
    assert plan_review._draft_patch_path('/draft/exercises/0/coachingAuthority/localNotes',
        result['planIndex'], draft) == '/workouts/0/exercises/0/placementNotes'
    context = plan_review._context(result, messages, equipment, None, len(messages) - 1)
    tampered = copy.deepcopy(result)
    tampered['planIndex']['exercises'][0]['placementNotes'] += ' Tampered assembled guidance.'
    tampered_context = plan_review._context(tampered, messages, equipment, None, len(messages) - 1)
    assert context['draft']['exercises'][0]['renderedGuidance'] == result['planIndex']['exercises'][0]['placementNotes']
    assert plan_review._hash(context) != plan_review._hash(tampered_context)


def test_repair_capability_contract_keeps_native_calibration_code_owned():
    from workout_generator_pkg.repair_capabilities import repair_capability_contract
    contract = repair_capability_contract()
    assert 'calibration' not in contract['editableDimensions']
    assert contract['editableFields']['effortAcceptance'] == ['prescription']
    assert 'requiresEffortCalibration' not in contract['editableFields']
    assert 'calibrationAttempts' not in contract['editableFields']
    assert 'native_load_calibration' in contract['codeOwnedBehaviors']
    assert 'app-native requiresLoadCalibration' in contract['codeOwnedBehaviors']['native_load_calibration']


def test_repair_budgets_reach_the_real_api_wrapper(monkeypatch):
    options = planner_response_profile({'metadataOnlyRepair': True})
    calls = []
    def chat(*args, **kwargs):
        calls.append(kwargs)
        return 'done', None, None
    monkeypatch.setattr(api_client, 'chat_call', chat)
    assert api_client.chat_call_with_loading(None, [], **options) == ('done', None, None)
    assert calls == [{'reasoning_effort': None, 'max_tokens': 2048, 'timeout': None}]
    assert planner_response_profile({'repairTask': {'baseDraftId': 'REVISION_1'}})['max_tokens'] == 16384


def test_mixed_preparation_errors_keep_structural_repair_budget():
    task = {'metadataFields': {'/sessions/0/description': {'maximumCharacters': 100}},
            'errors': [{'code': 'export_description_too_long', 'path': '/sessions/0/description'}]}
    assert planner_response_profile({'preparationRepairTask': task})['max_tokens'] == 2048
    task['errors'].append({'code': 'infeasible_set_allocation', 'path': '/sessions'})
    profile = planner_response_profile({'preparationRepairTask': task})
    assert profile['max_tokens'] == 16384 and profile['reasoning_effort'] == 'low'


@pytest.mark.parametrize('mixed', [False, True])
def test_shell_advertises_structural_patches_for_mixed_repairs(monkeypatch, tmp_path, mixed):
    from workout_generator_pkg import interactive_shell
    from test_workout_generator_conversation_sessions import make_shell_deps, run_shell
    task = {'metadataFields': {'/sessions/0/description': {'maximumCharacters': 100}},
            'errors': [{'code': 'export_description_too_long', 'path': '/sessions/0/description'}]}
    if mixed:
        task['errors'].append({'code': 'infeasible_set_allocation', 'path': '/sessions'})
    monkeypatch.setattr(interactive_shell, 'request_planning_state', lambda messages: {'preparationRepairTask': task})
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    advertised = []
    def capture(client, messages, tools, logger, **options):
        advertised.extend(tools)
        return 'Repair needs attention.', None, None
    deps.chat_call_with_loading = capture
    run_shell(monkeypatch, deps, ['Repair the preparation', '/exit'])
    schema = next(tool['function']['parameters'] for tool in advertised
                  if tool.get('function', {}).get('name') == 'prepare_workout_sessions')
    patch = {'basePreparationId': 'PREPARATION_1', 'patch': [
        {'op': 'replace', 'path': '/sessions/0/exercises/0/allocationBounds/maximum', 'value': 12}]}
    if mixed:
        validate(patch, schema)
    else:
        with pytest.raises(ValidationError):
            validate(patch, schema)


@pytest.mark.parametrize('mode, expected_calls', [('progress', 2), ('changing', 3), ('unchanged', 1)])
def test_worker_repair_tracks_proposal_progress_and_has_a_total_limit(monkeypatch, mode, expected_calls):
    from workout_generator_pkg import interactive_shell
    from workout_generator_pkg.planner_context import request_planning_state
    from test_workout_generator_parallel_planning import week_case
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    repairs = []
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        if 'permittedPaths' in payload:
            repairs.append(payload)
            value = ('x' * (510 + len(repairs)) if len(repairs) == 1 else 'Controlled execution.') if mode == 'progress' else (
                'x' * (510 + len(repairs)) if mode == 'changing' else 'x' * 505)
            return json.dumps({'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes',
                                         'value': value}]}), None, None
        selection = payload['session']
        values = copy.deepcopy(exercises)
        if selection['name'] == 'Session 0':
            values[0]['placementNotes'] = 'x' * 505
        return json.dumps({**selection, 'exercises': values}), None, None
    monkeypatch.setattr(plan_review, 'review_week_structure', lambda *args, **kwargs: {'passed': True, 'findings': []})
    monkeypatch.setattr(session_drafting, 'chat_call', respond)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, state)
    assert len(repairs) == expected_calls
    assert ('proposedSubmission' in result) is (mode == 'progress')


@pytest.mark.parametrize('metadata, expected_calls', [(True, 3), (False, 40)])
def test_shell_stops_bounded_repair_work_and_saves_feedback(monkeypatch, tmp_path, capsys, metadata, expected_calls):
    from test_workout_generator_conversation_sessions import (
        FakeFunction, FakeToolCall, make_shell_deps, run_shell, load_active_conversation_record,
    )
    calls = [FakeToolCall(str(index), 'function', FakeFunction('audit_workout_plan', json.dumps({'attempt': index})))
             for index in range(41)]
    deps = make_shell_deps(tmp_path, chat_results=[('', [call]) for call in calls],
                           generation_results=[], generation_calls=[])
    attempts = []
    def reject(*args, **kwargs):
        attempts.append(len(attempts))
        error = {'code': 'export_notes_too_long' if metadata else 'invalid_arguments',
                 'path': '/workouts/0/exercises/0/placementNotes' if metadata else '/workouts/0',
                 'message': f'Unresolved attempt {len(attempts)}'}
        return {'result': json.dumps({'passed': False, 'errors': [error]}),
                'should_exit': False, 'generation_result': None}
    deps.handle_function_call = reject
    run_shell(monkeypatch, deps, ['Repair my draft', '/exit'])
    assert len(attempts) == expected_calls
    expected_reason = 'Text repair failed three times' if metadata else '40-round work budget'
    assert expected_reason in capsys.readouterr().out
    saved = load_active_conversation_record(str(tmp_path))['messages']
    feedback = [json.loads(message['content']) for message in saved if message['role'] == 'tool']
    assert len(feedback) == expected_calls and feedback[-1]['errors']
