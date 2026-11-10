import copy
import json

import pytest
from jsonschema import Draft7Validator

from workout_generator_pkg import allocation, joint_planning, session_drafting
from workout_generator_pkg.planning_tools import PlanningInputError
from test_workout_generator_planning_tools import planning_case
from test_workout_generator_weekly_shortlist import shortlist_case, store_preparation


@pytest.fixture
def selected_case(monkeypatch):
    equipment, messages, arguments = shortlist_case()
    arguments['selectionMode'] = 'selected_menu'
    calls = []

    def allocate(sessions, *args, **kwargs):
        calls.append(copy.deepcopy(kwargs))
        return {'feasible': True, 'status': 'feasible', 'sessions': copy.deepcopy(sessions)}

    monkeypatch.setattr(allocation, 'allocate_prepared_sets', allocate)
    return equipment, messages, arguments, calls


def test_fresh_selector_commits_menu_and_legacy_calls_keep_pool_semantics(selected_case):
    equipment, messages, arguments, _ = selected_case
    tool = session_drafting.prepare_workout_sessions_tool(messages, equipment,
        selection_options={'admissibleDefinitionIds': ['LIBRARY_0']})
    validator = Draft7Validator(tool['function']['parameters'])
    validator.validate({key: value for key, value in arguments.items()
        if key not in ('requirementsId', 'baseDraftId')})
    legacy = {key: value for key, value in arguments.items() if key != 'selectionMode'}
    assert not validator.is_valid(legacy)
    Draft7Validator(session_drafting._preparation_schema(legacy)).validate(legacy)
    assert 'semanticSelection' not in session_drafting._expand_weekly_shortlist(legacy, messages, equipment)


def test_backend_fills_omitted_scope_but_rejects_wrong_submitted_scope(selected_case):
    equipment, messages, arguments, _ = selected_case
    choices = {key: value for key, value in arguments.items()
        if key not in ('requirementsId', 'baseDraftId')}
    prepared = session_drafting.prepare_workout_sessions(choices, messages, equipment)
    assert prepared['requirementsId'] == arguments['requirementsId']
    assert prepared['baseDraftId'] is None
    assert choices == {'selectionMode': 'selected_menu', 'definition_ids': ['LIBRARY_0']}
    with pytest.raises(ValueError, match='stale'):
        session_drafting.prepare_workout_sessions({**choices, 'requirementsId': 'wrong'}, messages, equipment)
    with pytest.raises(ValueError, match='stale'):
        session_drafting.prepare_workout_sessions({**choices, 'baseDraftId': 'REVISION_999'}, messages, equipment)


def test_selected_menu_binds_canonical_id_and_skips_unselected_supplemental_recipes(selected_case, monkeypatch):
    equipment, messages, arguments, calls = selected_case
    original = copy.deepcopy(arguments)

    def unexpected(*_, **__):
        pytest.fail('A committed semantic menu must not expand from a mathematical search pool.')

    monkeypatch.setattr(session_drafting, '_reviewed_recipe_candidate_references', unexpected)
    monkeypatch.setattr(session_drafting, '_prior_preparation_for_authority', unexpected)
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment, preserve_prior_menu=True)
    selection = {'mode': 'selected_menu', 'definitionIds': [equipment['exerciseDefinitions'][0]['id']]}
    assert arguments == original
    assert prepared['semanticSelection'] == selection
    assert calls[0]['semantic_selection'] == selection
    assert prepared['preparationArguments'] == arguments
    assert prepared['definition_ids'] == ['LIBRARY_0']


def test_semantic_selection_is_part_of_preparation_cache_identity(selected_case):
    equipment, messages, arguments, calls = selected_case
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_preparation(messages, arguments, prepared)
    legacy = {key: value for key, value in arguments.items() if key != 'selectionMode'}
    session_drafting.prepare_workout_sessions(legacy, messages, equipment)
    assert len(calls) == 2
    assert calls[1]['semantic_selection'] is None


def test_reusable_objective_fingerprint_binds_menu_and_fixed_prefix_scope(selected_case):
    equipment, messages, arguments, _ = selected_case
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    _, receipt = session_drafting._latest_result(messages, 'set_workout_requirements')
    sessions = prepared['recipeSessions']
    selection = prepared['semanticSelection']

    def fingerprint(binding):
        return joint_planning.joint_objective_input_fingerprint(sessions, receipt['requirements'], equipment,
            semantic_selection=binding)

    pool = fingerprint(None)
    committed = fingerprint(selection)
    fixed_scope = fingerprint({**selection, 'fixedWorkouts': [sessions[0]]})
    assert len({pool, committed, fixed_scope}) == 3
    store_preparation(messages, arguments, prepared)
    recovered = joint_planning.joint_objective_input_fingerprint(sessions, receipt['requirements'], equipment,
        messages=messages)
    explicit = joint_planning.joint_objective_input_fingerprint(sessions, receipt['requirements'], equipment,
        messages=messages, semantic_selection=selection)
    assert recovered == explicit


def test_selected_menu_repair_cannot_downgrade_to_candidate_pool(selected_case, monkeypatch):
    equipment, messages, arguments, _ = selected_case
    failure = {'preparationArguments': arguments,
        'errors': [{'code': 'infeasible_set_allocation', 'path': '/sessions'}]}
    store_preparation(messages, arguments, failure)
    monkeypatch.setattr(session_drafting, 'preparation_selection_options',
        lambda *_: {'admissibleDefinitionIds': ['LIBRARY_0', 'LIBRARY_1']})
    task = session_drafting.preparation_repair_task(messages, equipment)
    correction = {'basePreparationId': task['basePreparationId'], 'definition_ids': ['LIBRARY_1']}
    with pytest.raises(PlanningInputError):
        session_drafting.resolve_preparation_patch(correction, messages, equipment)
    correction['selectionMode'] = 'selected_menu'
    revised = session_drafting.resolve_preparation_patch(correction, messages, equipment)
    assert revised['selectionMode'] == 'selected_menu'
    assert revised['definition_ids'] == ['LIBRARY_1']


def test_current_binding_survives_status_and_edit_turns_without_reopening_pool(selected_case):
    equipment, messages, arguments, _ = selected_case
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_preparation(messages, arguments, prepared)
    expected = {**prepared['semanticSelection'], 'fixedWorkouts': []}
    messages.extend([{'role': 'assistant', 'content': 'The current plan is ready for review.'},
        {'role': 'user', 'content': 'CONFIRM GENERATE'}, {'role': 'user', 'content': '/continue'}])
    assert session_drafting.current_semantic_selection(messages, equipment) == expected
    messages.append({'role': 'user', 'content': 'What is the current status?'})
    assert session_drafting.current_semantic_selection(messages, equipment) == expected
    messages.append({'role': 'user', 'content': 'Replace the push-up with another movement.'})
    assert session_drafting.current_semantic_selection(messages, equipment) == expected
    with pytest.raises(PlanningInputError, match='committed exercise menu'):
        session_drafting.current_semantic_selection(messages, equipment, requirements_id='changed')
    with pytest.raises(PlanningInputError, match='committed exercise menu'):
        session_drafting.current_semantic_selection(messages, equipment, history_fingerprint='changed')
    changed_equipment = copy.deepcopy(equipment)
    changed_equipment['exerciseDefinitions'][0]['name'] = 'Changed exercise'
    with pytest.raises(PlanningInputError, match='committed exercise menu'):
        session_drafting.current_semantic_selection(messages, changed_equipment)


def test_current_binding_rejects_changed_original_sources(selected_case):
    equipment, messages, arguments, _ = selected_case
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_preparation(messages, arguments, prepared)
    messages[-1]['content'] = json.dumps({**prepared, 'sourceMessages': {}})
    with pytest.raises(PlanningInputError, match='source identity'):
        session_drafting.current_semantic_selection(messages, equipment)


def test_admitted_audit_menu_supersedes_prepared_commitment(selected_case, monkeypatch):
    equipment, messages, arguments, _ = selected_case
    alternative = {**copy.deepcopy(equipment['exerciseDefinitions'][0]), 'id': 'variant', 'name': 'Variant'}
    equipment['exerciseDefinitions'].append(alternative)
    monkeypatch.setattr(session_drafting, '_history_configuration_concerns', lambda *_, **__: {})
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_preparation(messages, arguments, prepared)
    replacement = {'mode': 'selected_menu', 'definitionIds': ['variant'], 'fixedWorkouts': []}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'admitted', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'admitted', 'content': json.dumps({
            'requirementsId': prepared['requirementsId'], 'libraryFingerprint': prepared['libraryFingerprint'],
            'historyFingerprint': None, 'semanticSelection': replacement})}])
    assert session_drafting.current_semantic_selection(messages, equipment) == replacement
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'rejected', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'rejected', 'content': json.dumps({'passed': False,
            'errors': [{'code': 'invalid_draft_patch'}]})}])
    assert session_drafting.current_semantic_selection(messages, equipment) == replacement


def test_exact_existing_menu_acceptance_preserves_binding_through_completed_workers(selected_case):
    from workout_generator_pkg.user_interaction import answer_question

    equipment, messages, arguments, _ = selected_case
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    prepared['sourceWorkingSetBudget'] = {'source': 'retained_source',
        'variableWeeklyWorkingSets': 15, 'preparationId': prepared['preparationId']}
    store_preparation(messages, arguments, prepared)
    question = {'kind': 'clarification', 'question': 'Revise this menu or accept the disclosed limits?',
        'options': ['Revise the menu.', 'Accept these menu limits.']}
    key = 'menu_gate'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': key, 'function': {'name': 'draft_workout_sessions'}}]},
        {'role': 'tool', 'tool_call_id': key, 'content': json.dumps({
            'preparationId': prepared['preparationId'], 'userQuestion': question,
            'menuReview': {'question': question, 'accepted': False}})},
        {'role': 'assistant', 'content': question['question']},
        {'role': 'user', 'content': answer_question(question, '2')}])
    expected = {**prepared['semanticSelection'], 'fixedWorkouts': []}
    assert session_drafting.current_semantic_selection(messages, equipment) == expected
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'completed', 'function': {'name': 'draft_workout_sessions'}}]},
        {'role': 'tool', 'tool_call_id': 'completed', 'content': json.dumps({
            'preparationId': prepared['preparationId'], 'semanticSelection': prepared['semanticSelection'],
            'passed': True, 'proposedSubmission': {'workouts': prepared['sessions']}})}])
    assert session_drafting.current_semantic_selection(messages, equipment) == expected
    messages.append({'role': 'user', 'content': 'Use a different exercise menu.'})
    assert session_drafting.current_semantic_selection(messages, equipment) == expected


@pytest.mark.parametrize('blocker', ['warmup', 'execution'])
def test_selected_recipe_execution_uncertainty_stops_before_prescriptions(selected_case, monkeypatch, blocker):
    equipment, messages, arguments, _ = selected_case
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_preparation(messages, arguments, prepared)
    monkeypatch.setattr(session_drafting, '_history_configuration_concerns', lambda *_, **__: {})
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *_, **__: {'contracts': [], 'capabilities': {}})
    if blocker == 'warmup':
        monkeypatch.setattr('workout_generator_pkg.planning_tools._filter_unsupported_warmup_candidates',
            lambda sessions, *_: [sessions[0]['exercises'][0]])
    else:
        monkeypatch.setattr(session_drafting, '_execution_recipe_issues', lambda *args: {'LIBRARY_0': {
            'code': 'execution_semantics_unresolved', 'definition_id': 'LIBRARY_0',
            'canonicalDefinitionId': equipment['exerciseDefinitions'][0]['id'],
            'path': '/sessions/0/exercises/0', 'roles': []}})

    def unexpected(*_, **__):
        pytest.fail('Unresolved committed recipes must stop before prescription calls.')

    monkeypatch.setattr(session_drafting, 'chat_call', unexpected)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, {})
    assert result['passed'] is False
    assert result['semanticSelection'] == prepared['semanticSelection']
    assert result['errors'][0]['code'] == ('infeasible_set_allocation' if blocker == 'warmup'
        else 'execution_semantics_unresolved')
    if blocker == 'execution':
        assert result['userQuestion']['executionChoices'][0]['definition_id'] == 'LIBRARY_0'


def test_selected_worker_solve_keeps_fixed_prefix_outside_variable_menu(selected_case, monkeypatch):
    equipment, messages, arguments, _ = selected_case
    _, _, _, draft = planning_case()
    fixed = {'name': 'Program', 'workouts': copy.deepcopy(draft['workouts'])}
    fixed['workouts'][0].update(name='Accepted fixed session', trainingDays=[0])
    original = copy.deepcopy(fixed)
    monkeypatch.setattr(session_drafting, 'latest_draft_submission', lambda *_: (fixed, 'REVISION_1'))
    arguments['baseDraftId'] = 'REVISION_1'
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_preparation(messages, arguments, prepared)
    assert session_drafting.current_semantic_selection(messages, equipment)['fixedWorkouts'] == fixed['workouts']
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *_, **__: {'contracts': [], 'capabilities': {}})
    monkeypatch.setattr(session_drafting, '_history_configuration_concerns', lambda *_, **__: {})
    monkeypatch.setattr(session_drafting, '_fresh_development_tradeoff', lambda *_, **__: None)
    captured = {}

    def solve(sessions, *_, **kwargs):
        captured.update(kwargs)
        captured['sessions'] = copy.deepcopy(sessions)
        return {'feasible': True, 'status': 'feasible', 'sessions': copy.deepcopy(sessions)}

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    template = copy.deepcopy(draft['workouts'][0]['exercises'][0])
    template['repDurationSeconds'] = 3

    def recipe(_, request, **options):
        return json.dumps({reference: {key: copy.deepcopy(value) for key, value in template.items()
            if key in schema['properties']}
            for reference, schema in options['output_schema']['properties'].items()}), None, None

    monkeypatch.setattr(session_drafting, 'chat_call', recipe)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, {})
    assert 'proposedSubmission' in result, result
    assert len(captured['sessions']) == 2
    assert captured['existing'] == original
    assert captured['semantic_selection'] == {**prepared['semanticSelection'], 'fixedWorkouts': original['workouts']}
    assert result['semanticSelection'] == prepared['semanticSelection']
    assert len(result['proposedSubmission']['workouts']) == 3
    assert result['proposedSubmission']['workouts'][0] == original['workouts'][0]
    assert fixed == original
