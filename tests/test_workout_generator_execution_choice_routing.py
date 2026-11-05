import copy
import json

import pytest

from test_workout_generator_conversation_sessions import make_shell_deps
from test_workout_generator_planning_tools import planning_case, requirement_messages
from workout_generator_pkg import interactive_shell as shell
from workout_generator_pkg.conversation_store import save_conversation, set_active_conversation
from workout_generator_pkg.logging_ui import format_question
from workout_generator_pkg.planning_decisions import propose_decisions
from workout_generator_pkg.planning_tools import library_fingerprint, requirement_sources, source_message_context
from workout_generator_pkg.user_interaction import answered_execution_decision, answer_question, pending_question


def counting_case(batch=False):
    equipment, _, stored, _ = planning_case()
    if batch:
        equipment['exerciseDefinitions'].append({**copy.deepcopy(equipment['exerciseDefinitions'][0]),
            'id': 'rotation', 'name': 'Second rotational movement'})
        stored['libraryFingerprint'] = library_fingerprint(equipment)
    messages = requirement_messages(stored)
    definitions = sorted(equipment['exerciseDefinitions'], key=lambda item: item['id'])
    question = {'question': 'Count the prescribed reps/time once or on each side/direction?',
        'options': ['One complete sequence; reps/time are total',
                    'Repeat prescribed reps/time on each side or direction'],
        'executionChoices': [{'definition_id': f'LIBRARY_{index}',
            'canonicalDefinitionId': definition['id'], 'path': f'/sessions/0/exercises/{index}'}
            for index, definition in enumerate(definitions)]}
    payload = {'requirementsId': stored['requirementsId'],
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'passed': False, 'userQuestion': question,
        'errors': [{'code': 'execution_semantics_unresolved',
            'definition_id': f'LIBRARY_{index}', 'canonicalDefinitionId': definition['id']}
            for index, definition in enumerate(definitions)]}
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'execution', 'type': 'function',
        'function': {'name': 'draft_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'execution', 'content': json.dumps(payload)}])
    question = pending_question(messages)
    messages.append({'role': 'assistant', 'content': format_question(question)})
    return equipment, messages, question


@pytest.mark.parametrize('answer,mode', [('1', 'single_sequence'), ('2', 'paired_sides')])
@pytest.mark.parametrize('batch', [False, True])
def test_numbered_execution_answer_compiles_existing_typed_decision_with_source_provenance(answer, mode, batch):
    equipment, messages, question = counting_case(batch=batch)
    messages.append({'role': 'user', 'content': answer_question(question, answer),
        'userInteraction': {'question': question, 'input': answer}})
    original = copy.deepcopy(messages)
    arguments = answered_execution_decision(messages, equipment)
    assert messages == original
    decision = arguments['decisions'][0]
    assert decision['executionPrescription']['setMode'] == mode
    sources = source_message_context(requirement_sources(messages))
    assert [sources[ref]['role'] for ref in decision['sourceReferences']] == ['assistant', 'user']
    assert sources[decision['sourceReferences'][-1]]['content'] == 'My answer: ' + question['options'][int(answer) - 1]
    proposal = propose_decisions(arguments, messages, equipment)
    assert len(arguments['decisions']) == len(question['executionChoices'])
    for index, choice in enumerate(question['executionChoices']):
        assert proposal['decisions'][f'DECISION_{index}']['executionPrescription'] == {
            'definitionId': choice['canonicalDefinitionId'], 'setMode': mode}


@pytest.mark.parametrize('change', ['missing_error', 'foreign_error_identity', 'omitted_target'])
def test_batch_counting_choice_requires_exact_pending_error_identities(change):
    equipment, messages, question = counting_case(batch=True)
    payload = json.loads(messages[-2]['content'])
    if change == 'missing_error':
        payload['errors'].pop()
    elif change == 'foreign_error_identity':
        payload['errors'][1]['canonicalDefinitionId'] = 'foreign-definition'
    else:
        payload['userQuestion']['executionChoices'].pop()
    messages[-2]['content'] = json.dumps(payload)
    question = pending_question(messages[:-1])
    messages.append({'role': 'user', 'content': answer_question(question, '2'),
        'userInteraction': {'question': question, 'input': '2'}})
    assert answered_execution_decision(messages, equipment) is None


@pytest.mark.parametrize('change', ['freeform', 'stale_library', 'stale_history', 'model_question', 'multiple', 'identity'])
def test_unstructured_or_stale_execution_answers_keep_semantic_routing(change):
    equipment, messages, question = counting_case()
    if change == 'stale_library':
        equipment = copy.deepcopy(equipment)
        equipment['exerciseDefinitions'][0]['name'] += ' changed'
    if change == 'model_question':
        messages[-3]['tool_calls'][0]['function']['name'] = 'ask_user'
    if change in ('multiple', 'identity'):
        payload = json.loads(messages[-2]['content'])
        if change == 'multiple':
            payload['userQuestion']['executionChoices'] *= 2
        else:
            payload['userQuestion']['executionChoices'][0]['canonicalDefinitionId'] = 'unknown'
        messages[-2]['content'] = json.dumps(payload)
        question = pending_question(messages[:-1])
    answer = 'Decide after checking my execution.' if change == 'freeform' else '2'
    messages.append({'role': 'user', 'content': answer_question(question, answer),
        'userInteraction': {'question': question, 'input': answer}})
    assert answered_execution_decision(messages, equipment, 'new-history' if change == 'stale_history' else None) is None


@pytest.mark.parametrize('answer', ['2', 'Decide after checking my execution.'])
def test_shell_routes_numbered_choice_directly_and_keeps_freeform_semantic(monkeypatch, tmp_path, answer):
    equipment, messages, _ = counting_case()
    save_conversation(messages, conversation_id='counting', script_dir=str(tmp_path))
    set_active_conversation('counting', str(tmp_path))
    library = tmp_path / 'library.json'
    library.write_text(json.dumps(equipment), encoding='utf-8')
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    calls, requests = [], []

    def handle(client, messages, name, arguments, *args, **kwargs):
        calls.append((name, arguments))
        assert name == 'record_planning_decisions'
        return {'result': json.dumps({'passed': False,
            'userQuestion': {'question': 'Review needs clarification.', 'options': []}}),
            'waiting_for_user': True, 'should_exit': False, 'generation_result': None}

    deps.handle_function_call = handle
    def planner(*args, **kwargs):
        requests.append(args)
        assert answer != '2', 'A numbered code-owned choice needs no full Planning call.'
        return 'Which execution constraint should I check?', None, None

    deps.chat_call_with_loading = planner
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(library)])
    inputs = iter(['/resume-conversation counting', answer, '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    shell.main(deps=deps)
    assert len(calls) == (1 if answer == '2' else 0)
    assert len(requests) == (0 if answer == '2' else 1)
    if calls:
        assert calls[0][1]['decisions'][0]['executionPrescription']['setMode'] == 'paired_sides'


def test_reviewed_counting_choice_reprepares_exact_saved_menu_and_reaches_workers_without_planner(monkeypatch, tmp_path):
    from test_workout_generator_parallel_planning import week_case, store_tool
    from workout_generator_pkg.conversation_store import load_active_conversation_record

    equipment, messages, prepared, _ = week_case()
    _, _, question = counting_case()
    raw_question = {key: question[key] for key in ('question', 'options', 'executionChoices')}
    store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, {
        'preparationId': prepared['preparationId'], 'requirementsId': prepared['requirementsId'],
        'libraryFingerprint': prepared['libraryFingerprint'], 'historyFingerprint': None,
        'passed': False, 'userQuestion': raw_question,
        'errors': [{'code': 'execution_semantics_unresolved', 'definition_id': 'LIBRARY_0',
            'canonicalDefinitionId': equipment['exerciseDefinitions'][0]['id']}]})
    messages.append({'role': 'assistant', 'content': format_question(pending_question(messages))})
    save_conversation(messages, conversation_id='counting-resume', script_dir=str(tmp_path))
    library = tmp_path / 'library.json'
    library.write_text(json.dumps(equipment), encoding='utf-8')
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    deps.chat_call_with_loading = lambda *a, **k: pytest.fail('Reviewed counting cannot require menu reconstruction by Planning.')
    drafted = []

    def workers(client, arguments, messages, equipment, planning_state, **kwargs):
        drafted.append(arguments)
        _, revalidated = shell._latest_result(messages, 'prepare_workout_sessions')
        assert revalidated['preparationId'] != prepared['preparationId']
        assert revalidated['recipeSessions'] == prepared['recipeSessions']
        assert revalidated['sourceWorkingSetBudget'] == prepared['sourceWorkingSetBudget']
        assert revalidated['sourceMessages'] == source_message_context(requirement_sources(messages))
        return {'passed': False, 'userQuestion': {'question': 'Worker boundary reached.', 'options': []}}

    monkeypatch.setattr(shell, 'draft_workout_sessions', workers)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(library)])
    inputs = iter(['/resume-conversation counting-resume', '2', '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    shell.main(deps=deps)
    assert len(drafted) == 1
    saved = load_active_conversation_record(str(tmp_path))['messages']
    _, decisions = shell._latest_result(saved, 'record_planning_decisions')
    assert decisions['passed'] and decisions['decisionReview']['passed']
    calls = [call['function'] for message in saved[len(messages):] for call in message.get('tool_calls', [])]
    assert [call['name'] for call in calls] == [
        'record_planning_decisions', 'prepare_workout_sessions', 'draft_workout_sessions']
