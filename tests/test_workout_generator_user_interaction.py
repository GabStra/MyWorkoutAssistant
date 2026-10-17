import json

import pytest
from jsonschema import ValidationError

from test_workout_generator_conversation_sessions import FakeFunction, FakeToolCall, make_shell_deps, run_shell
from workout_generator_pkg import interactive_shell as shell
from workout_generator_pkg.conversation_store import load_active_conversation_record
from workout_generator_pkg.user_interaction import answer_question, clarification_question, pending_question


@pytest.mark.parametrize('options, answer, expected', [
    (['Stationary work only', 'Walking is fine'], '1', 'Stationary work only'),
    ([], '3', '3'),
    (['CONFIRM GENERATE'], '1', 'CONFIRM GENERATE'),
    (['Stationary work only', 'Walking is fine'], 'Neither; ask me about the available space first.',
     'Neither; ask me about the available space first.'),
])
def test_question_tool_waits_records_answer_and_never_grants_approval(monkeypatch, tmp_path, capsys, options, answer, expected):
    question = {'question': 'Which setup can you use?', 'options': options}
    ask = FakeToolCall('question', 'function', FakeFunction('ask_user', json.dumps(question)))
    dependent = FakeToolCall('export', 'function', FakeFunction('generate_workout', '{}'))
    generated, requests = [], []
    deps = make_shell_deps(tmp_path, chat_results=[(None, [ask, dependent]), ('Answer recorded.', None)],
                           generation_results=[], generation_calls=generated)
    original = deps.chat_call_with_loading

    def capture(client, messages, tools, logger, **options):
        requests.append((messages, tools))
        return original(client, messages, tools, logger, **options)

    deps.chat_call_with_loading = capture
    run_shell(monkeypatch, deps, ['Plan a workout', answer, '/exit'])
    messages = load_active_conversation_record(str(tmp_path))['messages']
    assert not generated and len(requests) == 2
    assert all(any(t.get('function', {}).get('name') == 'ask_user' for t in tools) for _, tools in requests)
    response = next(m for m in messages if m.get('userInteraction'))
    assert response['content'] == 'My answer: ' + expected
    assert response['userInteraction']['input'] == answer
    assert any(m.get('role') == 'assistant' and question['question'] in m.get('content', '')
               and not m.get('tool_calls') for m in messages)
    assert all('userInteraction' not in m for m in shell._messages_for_api(messages))
    skipped = json.loads(next(m['content'] for m in messages if m.get('tool_call_id') == 'export'))
    assert skipped['skipped']
    output = capsys.readouterr().out
    assert 'Question> Which setup can you use?' in output
    assert 'type your own response' in output.casefold()
    assert pending_question(messages) is None


def test_unanswered_question_survives_saved_history_and_commands(monkeypatch, tmp_path):
    question = {'question': 'How many sessions?', 'options': []}
    ask = FakeToolCall('question', 'function', FakeFunction('ask_user', json.dumps(question)))
    deps = make_shell_deps(tmp_path, chat_results=[(None, [ask])], generation_results=[], generation_calls=[])
    run_shell(monkeypatch, deps, ['Plan a workout', '', '/view', '/exit'])
    messages = load_active_conversation_record(str(tmp_path))['messages']
    pending = pending_question(messages)
    assert pending['question'] == question['question']
    assert answer_question(pending, '/exit') == '/exit'
    assert answer_question(pending, '3') == 'My answer: 3'
    assert not any(m.get('userInteraction') for m in messages)


@pytest.mark.parametrize('kind', ['requirements', 'generation'])
def test_approval_requires_explicit_valid_choice_and_supports_revisions(kind):
    question = {'kind': kind, 'question': 'Approve?', 'options': ['Approve', 'Revise']}
    assert answer_question(question, '') == ''
    assert answer_question(question, 'yes') == 'yes'
    assert answer_question(question, 'Change the schedule to Tuesday and Friday.') == 'Change the schedule to Tuesday and Friday.'
    assert answer_question(question, '1') == ('CONFIRM REQUIREMENTS' if kind == 'requirements' else 'CONFIRM GENERATE')
    assert 'Ask what I want changed' in answer_question(question, '2')
    with pytest.raises(ValueError, match='listed number'):
        answer_question(question, '3')


def test_question_validation_rejects_blank_prompts_and_model_approval_actions():
    with pytest.raises(ValueError):
        clarification_question({'question': '   '})
    with pytest.raises(ValidationError):
        clarification_question({'question': 'Approve?', 'action': 'generate_workout'})


@pytest.mark.parametrize('kind', ['requirements', 'generation'])
@pytest.mark.parametrize('reply', ['1', '2', 'no', 'cancel'])
def test_approval_survives_explanations_but_not_approval_or_decline(kind, reply):
    from test_workout_generator_planning_tools import planning_case, requirement_messages, approved_messages
    from workout_generator_pkg.planning_tools import audit_workout_plan
    equipment, _, stored, draft = planning_case()
    if kind == 'generation':
        result = audit_workout_plan(draft, equipment, requirement_messages(stored))
        messages = approved_messages(stored, result)[:-1]
    else:
        messages = requirement_messages(stored)[:-1]
    question = pending_question(messages)
    messages.extend([{'role': 'user', 'content': 'What does RIR mean?'},
                     {'role': 'assistant', 'content': 'RIR means reps in reserve.'}])
    assert pending_question(messages) == question
    messages.extend([{'role': 'user', 'content': answer_question(question, reply),
        'userInteraction': {'question': question, 'input': reply}},
        {'role': 'assistant', 'content': 'Understood.'}])
    assert pending_question(json.loads(json.dumps(messages))) is None
