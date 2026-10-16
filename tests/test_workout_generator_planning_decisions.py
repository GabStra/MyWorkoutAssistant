import copy
import json

import pytest

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.interactive_shell import handle_function_call, _messages_for_api
from workout_generator_pkg.planning_decisions import propose_decisions, resolved_decisions
from workout_generator_pkg.planning_tools import PlanningInputError, confirmed_draft
from test_workout_generator_planning_tools import planning_case, requirement_messages


def store(messages, name, arguments, result, key):
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': key, 'function': {
        'name': name, 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(result)}])


def choice():
    return {'decisions': [{'topic': 'Balance counting', 'choice': 'Count each working set once for movement balance.',
                          'sourceReferences': ['SOURCE_1']}]}


def record(monkeypatch, messages, equipment):
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    arguments = choice()
    payload = json.loads(handle_function_call(None, messages, 'record_planning_decisions', arguments, equipment)['result'])
    store(messages, 'record_planning_decisions', arguments, payload, 'choice')
    return payload


def source_messages(stored):
    return requirement_messages(stored) + [
        {'role': 'user', 'content': 'Choose a sensible counting convention while preserving my targets.'}]


def test_legacy_choice_is_rechecked_against_capabilities_and_rejection_is_cached(monkeypatch):
    from workout_generator_pkg.generation_audit import audit_policy, available_muscle_targets
    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    original = record(monkeypatch, messages, equipment)
    original['decisionReview'].pop('auditPolicy')
    messages[-1]['content'] = json.dumps(original)
    calls = []
    def reject(client, request, **kwargs):
        context = json.loads(request[-1]['content'])
        calls.append(context)
        assert context['auditPolicy'] == audit_policy(available_muscle_targets(equipment))
        assert context['newDecisionIds'] == ['DECISION_0']
        return json.dumps({'findings': [{'severity': 'blocking', 'action': 'clarify',
            'path': '/decisions/DECISION_0', 'message': 'This choice promises unsupported numerical verification.',
            'evidencePaths': ['/sourceMessages/SOURCE_1/content', '/auditPolicy/supportedMuscleTargets'],
            'repair': 'Disclose the limitation and ask about supported targets.'}]}), None, None
    monkeypatch.setattr(review, 'chat_call', reject)
    rejected = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert not rejected['passed'] and rejected['decisions'] == original['decisions']
    assert rejected['errors'][0]['code'] == 'decision_source_finding'
    store(messages, 'record_planning_decisions', choice(), rejected, 'capability-recheck')
    assert json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result']) == rejected
    assert len(calls) == 1


@pytest.mark.parametrize('new_conflict', [False, True, 'capability'])
def test_checked_choice_survives_resume_and_reviewer_must_cite_a_new_conflict(monkeypatch, new_conflict):
    equipment, _, stored, draft = planning_case()
    messages = source_messages(stored)
    payload = record(monkeypatch, messages, equipment)
    assert payload['passed']
    messages = json.loads(json.dumps(messages))
    decisions = resolved_decisions(messages)
    assert list(decisions) == ['DECISION_0']
    assert decisions['DECISION_0']['sourceCountAtResolution'] == 2
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('An unchanged choice should reuse its authorization'))
    repeated = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert repeated['cached'] and repeated['decisions'] == payload['decisions']
    state = json.loads(next(m['content'].split('\n', 1)[1] for m in _messages_for_api(messages, True, provided_equipment=equipment)
                            if m.get('content', '').startswith('Current planning state')))
    assert state['resolvedDecisions'] == decisions
    finding = {'severity': 'blocking', 'action': 'clarify', 'decisionId': 'DECISION_0',
               'path': '/resolvedDecisions/DECISION_0', 'message': 'Ask the user to choose a balance convention again.',
               'evidencePaths': ['/sourceMessages/SOURCE_1/content'], 'repair': 'Ask again.',
               'newConflictEvidencePaths': (['/auditPolicy/supportedMuscleTargets'] if new_conflict == 'capability' else
                   ['/audit/workouts/0/estimatedSeconds'] if new_conflict else ['/sourceMessages/SOURCE_0/content'])}
    def check(client, request, **kwargs):
        context = json.loads(request[-1]['content'])
        assert context['resolvedDecisions'] == decisions
        from workout_generator_pkg.generation_audit import audit_policy, available_muscle_targets
        assert context['auditPolicy'] == audit_policy(available_muscle_targets(equipment))
        return json.dumps({'findings': [finding]}), None, None
    monkeypatch.setattr(review, 'chat_call', check)
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and 'preview' not in result
    if not new_conflict:
        assert result['review']['findings'][0]['severity'] == 'blocking'
        assert result['review']['findings'][0]['action'] == 'repair'
        assert result['review']['findings'][0]['message'] == finding['message']
        assert 'without asking again' in result['review']['findings'][0]['repair']
    else:
        assert result['errors'][0]['action'] == 'clarify'
    assert result['errors'][0]['decisionId'] == 'DECISION_0'


def test_missing_conflict_metadata_cannot_approve_a_real_prescription_violation(monkeypatch):
    equipment, _, stored, draft = planning_case()
    stored['sourceMessages'][0]['content'] += '. All working sets must stay at 1-2 RIR.'
    messages = source_messages(stored)
    arguments = {'decisions': [{'topic': 'Working effort', 'choice': 'Keep working sets at 1-2 RIR.',
                               'sourceReferences': ['SOURCE_0']}]}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    receipt = json.loads(handle_function_call(None, messages, 'record_planning_decisions', arguments, equipment)['result'])
    assert receipt['passed']
    store(messages, 'record_planning_decisions', arguments, receipt, 'effort')
    draft['workouts'][0]['exercises'][0]['placementNotes'] = 'Take every working set to failure.'
    finding = {'severity': 'blocking', 'action': 'clarify', 'decisionId': 'DECISION_0',
               'path': '/draft/exercises/0/placementNotes',
               'message': 'Working sets to failure contradict the required 1-2 RIR.',
               'evidencePaths': ['/sourceMessages/SOURCE_0/content', '/draft/exercises/0/placementNotes'],
               'repair': 'Restore working sets at 1-2 RIR.'}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and 'preview' not in result
    error = result['errors'][0]
    assert error['severity'] == 'blocking' and error['action'] == 'repair'
    assert error['message'] == finding['message'] and finding['repair'] in error['repair']


def test_repeated_choice_is_rechecked_after_user_reversal_and_rejection_is_cached(monkeypatch):
    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    original = record(monkeypatch, messages, equipment)
    messages.append({'role': 'user', 'content': 'Do not count each working set once. Use summed muscle credits instead.'})
    calls = []
    def reject(client, request, **kwargs):
        context = json.loads(request[-1]['content'])
        calls.append(context)
        assert context['newDecisionIds'] == ['DECISION_0']
        finding = {'severity': 'blocking', 'path': '/decisions/DECISION_0/choice',
                   'message': 'The latest user instruction reverses this choice.',
                   'evidencePaths': ['/sourceMessages/SOURCE_2/content'],
                   'repair': 'Record the new choice as a replacement for DECISION_0.'}
        return json.dumps({'findings': [finding]}), None, None
    monkeypatch.setattr(review, 'chat_call', reject)
    rejected = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert not rejected['passed'] and len(calls) == 1
    assert rejected['decisions'] == original['decisions']
    store(messages, 'record_planning_decisions', choice(), rejected, 'revalidation')
    repeated = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert repeated == rejected and len(calls) == 1


@pytest.mark.parametrize('followup', [
    {'role': 'assistant', 'content': 'I will apply the settled counting choice.'},
    {'role': 'user', 'content': '/continue'},
    {'role': 'user', 'content': 'CONFIRM GENERATE'},
])
def test_decision_authorization_reuse_ignores_assistant_prose_and_control_commands(monkeypatch, followup):
    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    original = record(monkeypatch, messages, equipment)
    messages.append(followup)
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('User instructions have not changed'))
    repeated = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert repeated['cached'] and repeated['decisions'] == original['decisions']


@pytest.mark.parametrize('legacy_receipt', [False, True])
def test_successful_revalidation_is_saved_once_without_creating_a_new_decision(monkeypatch, legacy_receipt):
    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    original = record(monkeypatch, messages, equipment)
    if legacy_receipt:
        original['decisions']['DECISION_0'].pop('authorizationSourceHash')
        original['decisionReview']['inputHash'] = 'legacy-input-without-source-hash'
        messages[-1]['content'] = json.dumps(original)
    else:
        messages.append({'role': 'user', 'content': 'Keep that counting choice and continue planning.'})
    calls = []
    def accept(client, request, **kwargs):
        calls.append(json.loads(request[-1]['content']))
        return '{"findings":[]}', None, None
    monkeypatch.setattr(review, 'chat_call', accept)
    refreshed = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert refreshed['passed'] and len(calls) == 1
    assert calls[0]['newDecisionIds'] == ['DECISION_0']
    assert list(refreshed['decisions']) == ['DECISION_0']
    assert refreshed['decisions']['DECISION_0']['authorizationSourceHash']
    store(messages, 'record_planning_decisions', choice(), refreshed, 'refreshed')
    messages = json.loads(json.dumps(messages))
    repeated = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert repeated['cached'] and repeated['decisions'] == refreshed['decisions'] and len(calls) == 1


def test_unsupported_choice_is_not_saved_and_genuine_user_revisions_invalidate_old_preview(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = source_messages(stored)
    record(monkeypatch, messages, equipment)
    first = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    store(messages, 'audit_workout_plan', draft, first, 'audit')
    messages.extend([{'role': 'assistant', 'content': first['preview'], 'canonicalDraftPreview': first['draftId']},
                     {'role': 'user', 'content': 'CONFIRM GENERATE'}])
    confirmed_draft(messages, equipment, require_confirmation=True)
    changed = {'decisions': [{'topic': 'Balance counting', 'choice': 'Use the new user-requested convention.',
                             'sourceReferences': ['SOURCE_2'], 'supersedes': 'DECISION_0', 'reason': 'The user changed this choice.'}]}
    messages.append({'role': 'user', 'content': 'Use a different counting convention.'})
    invalid = copy.deepcopy(changed)
    invalid['decisions'][0].pop('reason')
    with pytest.raises(PlanningInputError, match='silently replaced'):
        propose_decisions(invalid, messages)
    finding = {'severity': 'blocking', 'path': '/decisions/DECISION_1/choice',
               'message': 'The choice is unsupported.', 'evidencePaths': ['/sourceMessages/SOURCE_2/content'], 'repair': 'Keep the authorized choice.'}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    rejected = json.loads(handle_function_call(None, messages, 'record_planning_decisions', changed, equipment)['result'])
    store(messages, 'record_planning_decisions', changed, rejected, 'rejected')
    assert not rejected['passed'] and list(resolved_decisions(messages)) == ['DECISION_0']
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    replacement = json.loads(handle_function_call(None, messages, 'record_planning_decisions', changed, equipment)['result'])
    assert not replacement['passed']  # A valid blocking review cannot be retried unchanged to fish for approval.
    changed['decisions'][0]['choice'] = 'A corrected choice consistent with the new user instruction.'
    replacement = json.loads(handle_function_call(None, messages, 'record_planning_decisions', changed, equipment)['result'])
    store(messages, 'record_planning_decisions', changed, replacement, 'replacement')
    assert replacement['passed'] and list(resolved_decisions(messages)) == ['DECISION_1']
    with pytest.raises(ValueError, match='Planning choices changed'):
        confirmed_draft(messages, equipment)


def test_invalid_sources_and_cancelled_authorization_never_commit_decisions(monkeypatch):
    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    invalid = choice()
    invalid['decisions'][0]['sourceReferences'] = ['SOURCE_999']
    with pytest.raises(PlanningInputError, match='existing source'):
        propose_decisions(invalid, messages)
    invalid['decisions'][0]['sourceReferences'] = ['SOURCE_0']
    with pytest.raises(PlanningInputError, match='including a user statement'):
        propose_decisions(invalid, [{'role': 'assistant', 'content': 'I suggest this choice.'}])
    def cancel(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(review, 'chat_call', cancel)
    with pytest.raises(KeyboardInterrupt):
        handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)
    assert resolved_decisions(messages) == {}


def test_decision_review_failure_is_cached_until_explicit_retry(monkeypatch):
    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    calls = []
    def fail(*a, **k):
        calls.append(1)
        raise ValueError()
    monkeypatch.setattr(review, 'chat_call', fail)
    failure = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert not failure['passed'] and failure['errors'][0]['code'] == 'decision_review_failed'
    store(messages, 'record_planning_decisions', choice(), failure, 'failed')
    repeated = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert not repeated['passed'] and len(calls) == 1
    messages.append({'role': 'user', 'content': '/continue'})
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or '{"findings":[]}', None, None))
    retried = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert retried['passed'] and len(calls) == 2


def test_decision_review_uses_shared_budget_and_deadline_defaults(monkeypatch):
    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    options = []
    def accept(client, request, **kwargs):
        options.append(kwargs)
        return '{"findings":[]}', None, None
    monkeypatch.setattr(review, 'chat_call', accept)
    result = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert result['passed'] and options == [{'reasoning_effort': 'low', 'response_format': {'type': 'json_object'}}]


def test_choice_review_repairs_missing_source_citation_without_dropping_blockers(monkeypatch):
    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    blocking = {'severity': 'blocking', 'path': '/decisions/DECISION_0/choice',
        'message': 'This choice is not authorized.', 'repair': 'Preserve the user instruction.',
        'evidencePaths': ['/sourceMessages/SOURCE_1/content']}
    malformed = {**blocking, 'severity': 'warning', 'evidencePaths': ['/auditPolicy/supportedMuscleTargets']}
    calls = []
    def respond(client, request, **options):
        calls.append(request)
        assert 'absence from sourceMessages does not mean equipment or history is unavailable' in request[0]['content']
        return json.dumps({'findings': [blocking, malformed] if len(calls) == 1 else [
            {**malformed, 'evidencePaths': ['/sourceMessages/SOURCE_1/content']}]}), None, None
    monkeypatch.setattr(review, 'chat_call', respond)
    result = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert not result['passed'] and not result['decisionReview'].get('failure')
    assert len(calls) == 2 and len(result['decisionReview']['findings']) == 2
    assert result['errors'][0]['code'] == 'decision_source_finding'
    assert result['decisions'] == {}


def test_choices_are_available_before_requirements_are_extracted(monkeypatch):
    equipment, _, _, _ = planning_case()
    messages = [{'role': 'assistant', 'content': 'Which convention?'},
                {'role': 'user', 'content': 'Choose a sensible convention.'}]
    record(monkeypatch, messages, equipment)
    outgoing = _messages_for_api(messages, True, provided_equipment=equipment)
    state = json.loads(next(m['content'].split('\n', 1)[1] for m in outgoing
                            if m.get('content', '').startswith('Requirement discussion state')))
    assert state['resolvedDecisions']['DECISION_0']['sourceReferences'] == ['SOURCE_1']
