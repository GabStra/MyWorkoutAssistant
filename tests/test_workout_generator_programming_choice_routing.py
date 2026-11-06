import copy
import json

import pytest

from test_workout_generator_context_decisions import programming_choice_case
from test_workout_generator_conversation_sessions import make_shell_deps
from test_workout_generator_planning_decisions import store
from workout_generator_pkg import interactive_shell, plan_review
from workout_generator_pkg.conversation_store import load_active_conversation_record, save_conversation
from workout_generator_pkg.planning_decisions import resolved_decisions
from workout_generator_pkg.user_interaction import (
    answer_question, answered_programming_decision, pending_question,
)


@pytest.mark.parametrize('answer,receipt_tool,review_passes', [
    ('1', 'draft_workout_sessions', True),
    ('label', 'audit_workout_plan', True),
    ('1', 'draft_workout_sessions', False),
])
def test_shell_compiles_displayed_programming_answer_before_routing_model(
        tmp_path, monkeypatch, answer, receipt_tool, review_passes):
    equipment, stored, _, _, messages, gated = programming_choice_case(receipt_tool, unknown=True)
    labels = gated['userQuestion']['options']
    answer = labels[1] if answer == 'label' else answer
    selected = list(gated['programmingDecisionChoices'])[0 if answer == '1' else 1]
    expected = gated['programmingDecisionChoices'][selected]
    conversation_id = save_conversation(messages, script_dir=str(tmp_path), migrate=False)
    library = tmp_path / 'library.json'
    library.write_text(json.dumps(equipment), encoding='utf-8')
    reviews, routed = [], []

    def review(_client, request, **_options):
        context = json.loads(request[-1]['content'])
        decision = context['decisions']['DECISION_0']
        reviews.append(context)
        assert decision['choice'] == expected['label']
        assert decision['acceptedConcernGroupId'] == selected
        assert decision['acceptedCandidateScope'] == expected['acceptedCandidateScope']
        sources = [context['sourceMessages'][reference]['content']
            for reference in decision['sourceReferences']]
        assert sources == ['My answer: ' + expected['label']]
        if review_passes:
            return '{"findings":[]}', None, None
        return json.dumps({'findings': [{'severity': 'blocking',
            'path': decision['_reviewRef'], 'message': 'Independent review withheld approval.',
            'evidencePaths': [], 'repair': 'Clarify the selected artifact.'}]}), None, None

    def followup(_client, _request, *_args, **_options):
        assert reviews, 'The exact choice must reach independent review before any routing model call.'
        saved = load_active_conversation_record(str(tmp_path))['messages']
        assert resolved_decisions(saved)['DECISION_0']['acceptedCandidateScope'] == expected['acceptedCandidateScope']
        routed.append(True)
        return 'The selected artifact remains subject to final review and export confirmation.', None, None

    monkeypatch.setattr(plan_review, '_review_call', review)
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    deps.chat_call_with_loading = followup
    inputs = iter(['/resume-conversation ' + conversation_id, answer, '/exit'])
    monkeypatch.setattr('builtins.input', lambda _prompt='': next(inputs))
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(library)])
    interactive_shell.main(deps=deps)

    saved = load_active_conversation_record(str(tmp_path))['messages']
    call = next(call for message in saved for call in message.get('tool_calls', [])
        if call['id'].startswith('programming_choice_'))
    arguments = json.loads(call['function']['arguments'])
    assert arguments == {'decisions': [{'topic': 'Displayed programming choice',
        'choice': expected['label'], 'sourceReferences': ['SOURCE_1'], 'acceptedConcernGroupId': selected}]}
    result = json.loads(next(message['content'] for message in saved if message.get('tool_call_id') == call['id']))
    assert len(reviews) == 1
    assert result['passed'] is review_passes
    if not review_passes:
        assert not routed
    assert resolved_decisions(saved) == (result['decisions'] if review_passes else {})
    if review_passes:
        assert result['decisions']['DECISION_0']['sourceCountAtResolution'] == 2
    assert stored['requirementsId'] == gated['requirementsId']


@pytest.mark.parametrize('change', ['freeform', 'unbound', 'new_question', 'new_candidate',
    'changed_comparison', 'changed_requirements', 'changed_library', 'changed_history'])
def test_programming_answer_compiler_rejects_ambiguous_or_stale_choices(change):
    equipment, stored, _, _, messages, _ = programming_choice_case()
    question = pending_question(messages)
    reply = 'Keep whichever is better.' if change == 'freeform' else '1'
    messages.append({'role': 'user', 'content': answer_question(question, reply),
        'userInteraction': {'question': question, 'input': reply}})
    if change == 'unbound':
        messages[-1].pop('userInteraction')
    elif change == 'new_question':
        messages[-1]['userInteraction']['question'] = {**question, 'question': 'A different question'}
    elif change in ('new_candidate', 'changed_comparison'):
        index = question['messageIndex']
        result = json.loads(messages[index]['content'])
        if change == 'new_candidate':
            store(messages, 'audit_workout_plan', {}, result, 'new-artifact')
        else:
            result['jointPromotionGate']['programmingTradeoff']['unknownObjectives'] = ['changed-evidence']
            messages[index]['content'] = json.dumps(result)
    elif change == 'changed_requirements':
        result = {**stored, 'requirementsId': 'CHANGED'}
        store(messages, 'set_workout_requirements', {}, result, 'new-requirements')
    elif change == 'changed_library':
        equipment = copy.deepcopy(equipment)
        equipment['exerciseDefinitions'][0]['name'] += ' changed'
    history = 'changed-history' if change == 'changed_history' else None
    assert answered_programming_decision(messages, equipment, history) is None
