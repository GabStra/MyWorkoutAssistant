import json

import pytest

from test_workout_generator_conflict_resolution import _alternative_case
from test_workout_generator_conversation_sessions import make_shell_deps
from workout_generator_pkg import interactive_shell
from workout_generator_pkg.conflict_resolution import render_alternative_preview
from workout_generator_pkg.conversation_store import load_active_conversation_record, save_conversation


@pytest.mark.parametrize('changed_draft', [False, True])
def test_exact_alternative_approval_skips_routing_model_and_retains_shared_gates(
        tmp_path, monkeypatch, changed_draft):
    equipment, requirements, result = _alternative_case()
    proposal = result['proposals'][0]
    messages = [{'role': 'system', 'content': 'Application'}]
    for name, value in (
            ('set_workout_requirements', {'requirementsId': 'REQ_TEST', 'requirements': requirements}),
            ('audit_workout_plan', {'currentDraftId': 'DRAFT_CHANGED' if changed_draft else 'DRAFT_TEST'}),
            ('propose_workout_alternatives', result)):
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': name, 'type': 'function',
                'function': {'name': name, 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': name, 'content': json.dumps(value)}])
    messages.append({'role': 'assistant', 'content': render_alternative_preview(proposal),
        'canonicalAlternativePreview': proposal['proposalId']})
    conversation_id = save_conversation(messages, script_dir=str(tmp_path), migrate=False)
    library = tmp_path / 'library.json'
    library.write_text(json.dumps(equipment), encoding='utf-8')
    monkeypatch.setattr(interactive_shell, 'requirements_approved', lambda *_args: True)
    monkeypatch.setattr(interactive_shell, 'request_planning_state', lambda *_args: {
        'requirementsApproved': True, 'sourceMessages': {}})
    monkeypatch.setattr(interactive_shell, 'pending_reaudit', lambda *_args: None)
    reviewed = []

    def review(_client, candidate, *_args, **_kwargs):
        reviewed.append(candidate)
        # Stop at the next real semantic boundary, retaining its failure handling.
        return {**candidate, 'passed': False, 'errors': [{
            'code': 'requirements_review_failed', 'message': 'Review unavailable in this replay.'}]}

    monkeypatch.setattr(interactive_shell, 'review_requirements', review)
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    routing_calls = []

    def followup_only(_client, model_messages, *_args, **_kwargs):
        # A stale-proposal explanation can use the model only after shared validation.
        checkpoint = load_active_conversation_record(str(tmp_path))['messages']
        calls = {call['id']: call['function']['name'] for message in checkpoint
            for call in message.get('tool_calls', [])}
        acceptance = [message for message in checkpoint
            if calls.get(message.get('tool_call_id')) == 'accept_workout_alternative']
        routing_calls.append(acceptance)
        assert acceptance, 'An exact approval must select the acceptance tool before any model call.'
        return 'The saved proposal is stale; it needs validation again.', None, None

    deps.chat_call_with_loading = followup_only
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(library)])
    inputs = iter(['/resume-conversation ' + conversation_id,
        'APPROVE ALTERNATIVE ' + proposal['proposalId'], '/exit'])
    monkeypatch.setattr('builtins.input', lambda _prompt='': next(inputs))
    interactive_shell.main(deps=deps)

    if not changed_draft:
        assert routing_calls == []
    saved = load_active_conversation_record(str(tmp_path))['messages']
    call = next(call for message in saved for call in message.get('tool_calls', [])
        if call['function']['name'] == 'accept_workout_alternative')
    assert json.loads(call['function']['arguments']) == {'proposalId': proposal['proposalId']}
    feedback = json.loads(next(message['content'] for message in saved
        if message.get('tool_call_id') == call['id']))
    if changed_draft:
        assert not reviewed
        assert len(routing_calls) == 1 and routing_calls[0]
        assert 'draft changed' in json.dumps(feedback).lower()
    else:
        assert len(reviewed) == 1
        assert reviewed[0]['approvedAlternativeId'] == proposal['proposalId']
        assert reviewed[0]['requirements'] == proposal['requirements']
        assert feedback['errors'][0]['code'] == 'requirements_review_failed'
