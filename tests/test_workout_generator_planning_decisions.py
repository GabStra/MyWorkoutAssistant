import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.interactive_shell import handle_function_call, _messages_for_api
from workout_generator_pkg.planning_decisions import (
    candidate_acceptance_scope, propose_decisions, record_planning_decisions_tool,
    resolved_decisions, reviewable_concern_ids, seed_approved_policy_context)
from workout_generator_pkg.planning_tools import PlanningInputError, confirmed_draft
from test_workout_generator_planning_tools import planning_case, requirement_messages


def store(messages, name, arguments, result, key):
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': key, 'function': {
        'name': name, 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(result)}])


def choice():
    return {'decisions': [{'topic': 'Balance counting', 'choice': 'Count each working set once for movement balance.',
                          'sourceReferences': ['SOURCE_1']}]}


def _without_review_refs(value):
    if isinstance(value, dict):
        return {key: _without_review_refs(child) for key, child in value.items() if key != '_reviewRef'}
    if isinstance(value, list):
        return [_without_review_refs(child) for child in value]
    return value


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
        assert _without_review_refs(context['auditPolicy']) == audit_policy(available_muscle_targets(equipment))
        assert context['newDecisionIds'] == ['DECISION_0']
        return json.dumps({'findings': [{'severity': 'blocking', 'action': 'clarify',
            'path': '/decisions/DECISION_0', 'message': 'This choice promises unsupported numerical verification.',
            'evidencePaths': ['/sourceMessages/SOURCE_1/content', '/auditPolicy/supportedMuscleTargets'],
            'repair': 'Disclose the limitation and ask about supported targets.'}]}), None, None
    monkeypatch.setattr(review, 'chat_call', reject)
    rejected = json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result'])
    assert not rejected['passed'] and rejected['decisions'] == original['decisions']
    assert rejected['errors'][0]['code'] == 'decision_source_finding', rejected['errors']
    store(messages, 'record_planning_decisions', choice(), rejected, 'capability-recheck')
    assert json.loads(handle_function_call(None, messages, 'record_planning_decisions', choice(), equipment)['result']) == rejected
    assert len(calls) == 1


def test_fresh_policy_seed_preserves_approved_requirements_and_source_references_without_plan_state():
    from workout_generator_pkg.planning_tools import (library_fingerprint, requirement_sources,
        source_message_context, requirements_approved)

    equipment, _, stored, draft = planning_case()
    stored['libraryFingerprint'] = library_fingerprint(equipment)
    stored['resolvedDecisions'] = {'DECISION_0': {
        'topic': 'Exercise choice', 'choice': 'Use the explicitly selected exercise.',
        'sourceReferences': ['SOURCE_0']}}
    messages = requirement_messages(stored)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'audit-plan', 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit-plan', 'content': json.dumps({
            'currentDraftId': 'REVISION_1', 'submittedDraft': draft, 'review': {'passed': True}})},
        {'role': 'assistant', 'content': 'A prior plan preview.', 'canonicalDraftPreview': 'REVISION_1'},
    ])

    seeded = seed_approved_policy_context(messages, [{'role': 'system', 'content': 'fresh'}], equipment)

    assert seeded is not None and not seeded['requiresReapproval']
    assert requirements_approved(seeded['messages'])
    assert source_message_context(requirement_sources(seeded['messages'])) == source_message_context(
        stored['sourceMessages'])
    assert seeded['messages'][-1]['content'] == 'CONFIRM REQUIREMENTS'
    assert not any(message.get('canonicalDraftPreview') or message.get('canonicalAlternativePreview')
        for message in seeded['messages'])
    assert not any(message.get('role') == 'tool' and message.get('tool_call_id') == 'audit-plan'
        for message in seeded['messages'])


def test_fresh_policy_seed_reopens_review_for_changed_library_and_drops_candidate_acceptance():
    from workout_generator_pkg.planning_tools import (library_fingerprint, requirement_sources,
        requirements_approved, source_message_context)

    equipment, _, stored, _ = planning_case()
    stored['libraryFingerprint'] = library_fingerprint(equipment)
    stored['resolvedDecisions'] = {
        'DECISION_0': {'topic': 'Base choice', 'choice': 'Keep the source-backed choice.',
            'sourceReferences': ['SOURCE_0']},
        'DECISION_1': {'topic': 'Candidate acceptance', 'choice': 'Accept the concern for this candidate.',
            'sourceReferences': ['SOURCE_0'], 'acceptedConcernGroupId': 'CONCERN_1',
            'acceptedCandidateScope': {'workoutsFingerprint': 'candidate'}},
    }
    messages = requirement_messages(stored)
    changed_library = copy.deepcopy(equipment)
    changed_library['exerciseDefinitions'][0]['name'] += ' changed'

    seeded = seed_approved_policy_context(messages, [{'role': 'system', 'content': 'fresh'}], changed_library)

    assert seeded is not None and seeded['requiresReapproval']
    assert not requirements_approved(seeded['messages'])
    carry = json.loads(seeded['messages'][-2]['content'])
    assert carry['sourceReview'] == {} and carry['jointDecisionReview'] == {}
    assert list(carry['resolvedDecisions']) == ['DECISION_0']
    assert not any(message.get('canonicalRequirementsPreview') for message in seeded['messages'])
    assert source_message_context(requirement_sources(seeded['messages'])) == source_message_context(
        stored['sourceMessages'])


def test_fresh_policy_seed_requires_reapproval_for_unfingerprinted_or_candidate_scoped_receipts():
    from workout_generator_pkg.planning_tools import library_fingerprint, requirements_approved

    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    without_fingerprint = seed_approved_policy_context(
        messages, [{'role': 'system', 'content': 'fresh'}], equipment)
    assert without_fingerprint is not None and without_fingerprint['requiresReapproval']
    assert not requirements_approved(without_fingerprint['messages'])

    stored['libraryFingerprint'] = library_fingerprint(equipment)
    stored['resolvedDecisions'] = {'DECISION_0': {
        'topic': 'Candidate acceptance', 'choice': 'Accept this concern for the reviewed candidate.',
        'sourceReferences': ['SOURCE_0'], 'acceptedConcernGroupId': 'CONCERN_1',
        'acceptedCandidateScope': {'workoutsFingerprint': 'candidate'}}}
    scoped = seed_approved_policy_context(requirement_messages(stored),
        [{'role': 'system', 'content': 'fresh'}], equipment)
    assert scoped is not None and scoped['requiresReapproval']
    carry = json.loads(scoped['messages'][-2]['content'])
    assert carry['resolvedDecisions'] == {}
    assert not requirements_approved(scoped['messages'])


def test_fresh_policy_seed_filters_approved_alternative_menu_and_remaps_source_ids():
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, _, stored, _ = planning_case()
    alternative_id = 'ALT_reviewed'
    stored['libraryFingerprint'] = library_fingerprint(equipment)
    stored['approvedAlternativeId'] = alternative_id
    stored['sourceMessages'].extend([
        {'messageIndex': 1, 'role': 'assistant', 'content': 'Stale alternative menu preview.'},
        {'messageIndex': 2, 'role': 'user', 'content': 'APPROVE ALTERNATIVE ' + alternative_id},
    ])
    stored['resolvedDecisions'] = {'DECISION_0': {'topic': 'Source choice',
        'choice': 'Preserve the user-backed choice.', 'sourceReferences': ['SOURCE_0', 'SOURCE_2']}}
    messages = requirement_messages(stored)
    messages[1]['canonicalAlternativePreview'] = alternative_id

    seeded = seed_approved_policy_context(messages, [{'role': 'system', 'content': 'fresh'}], equipment)

    assert seeded is not None and seeded['requiresReapproval']
    assert not any('Stale alternative menu preview.' in message.get('content', '')
        or 'APPROVE ALTERNATIVE ' + alternative_id == message.get('content') for message in seeded['messages'])
    carry = json.loads(seeded['messages'][-2]['content'])
    assert carry['sourceMessages'] == [stored['sourceMessages'][0]]
    assert carry['resolvedDecisions']['DECISION_0']['sourceReferences'] == ['SOURCE_0']


def test_fresh_policy_seed_does_not_resurrect_superseded_choices_but_ignores_later_candidate_acceptance():
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, _, stored, _ = planning_case()
    stored['libraryFingerprint'] = library_fingerprint(equipment)
    stored['resolvedDecisions'] = {'DECISION_0': {'topic': 'Session order',
        'choice': 'Keep the source-backed sequence.', 'sourceReferences': ['SOURCE_0']}}

    def with_later_decision(decisions):
        messages = requirement_messages(stored)
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': 'later-choice', 'function': {
                'name': 'record_planning_decisions', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'later-choice', 'content': json.dumps({
                'passed': True, 'decisionReview': {'passed': True}, 'decisions': decisions})},
        ])
        return messages

    changed = with_later_decision({'DECISION_0': {
        'topic': 'Session order', 'choice': 'Use the newer independently reviewed sequence.',
        'sourceReferences': ['SOURCE_0']}})
    blocked = seed_approved_policy_context(changed, [{'role': 'system', 'content': 'fresh'}], equipment)
    assert blocked is not None and 'newer independently reviewed programming choice' in blocked['blockedReason']

    candidate_acceptance = with_later_decision({
        'DECISION_0': {**stored['resolvedDecisions']['DECISION_0'], 'supersededBy': 'DECISION_1'},
        'DECISION_1': {'topic': 'Accept current soft concern', 'choice': 'Accept for this candidate.',
            'sourceReferences': ['SOURCE_0'], 'acceptedConcernGroupId': 'CONCERN_1',
            'acceptedCandidateScope': {'workoutsFingerprint': 'current-candidate'},
            'supersedes': 'DECISION_0'},
    })
    carried = seed_approved_policy_context(candidate_acceptance,
        [{'role': 'system', 'content': 'fresh'}], equipment)
    assert carried is not None and 'blockedReason' not in carried
    receipt = next(message for message in carried['messages']
        if message.get('role') == 'tool' and message.get('tool_call_id') == 'carry_requirements')
    assert 'DECISION_1' not in json.loads(receipt['content'])['resolvedDecisions']


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
    finding = {'severity': 'blocking', 'basis': 'established_violation', 'muscleTargets': [], 'action': 'clarify', 'decisionId': 'DECISION_0',
               'path': '/resolvedDecisions/DECISION_0', 'message': 'Ask the user to choose a balance convention again.',
               'evidencePaths': ['/sourceMessages/SOURCE_1/content'], 'repair': 'Ask again.',
               'newConflictEvidencePaths': (['/auditPolicy/supportedMuscleTargets'] if new_conflict == 'capability' else
                   ['/audit/workouts/0/estimatedSeconds'] if new_conflict else ['/sourceMessages/SOURCE_0/content'])}
    def check(client, request, **kwargs):
        context = json.loads(request[-1]['content'])
        assert _without_review_refs(context['resolvedDecisions']) == decisions
        from workout_generator_pkg.generation_audit import audit_policy, available_muscle_targets
        assert _without_review_refs(context['auditPolicy']) == audit_policy(available_muscle_targets(equipment))
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


def test_concern_bound_decision_offers_current_uncertainty_ids_and_persists_identity():
    equipment, _, stored, draft = planning_case()
    draft = copy.deepcopy(draft)
    for workout in draft['workouts']:
        for exercise in workout['exercises']:
            exercise.pop('placementNotes', None)
    messages = source_messages(stored)
    result = {'passed': False, 'review': {'findings': [
        {'concernGroupId': 'CONCERN_soft', 'basis': 'uncertainty', 'severity': 'warning'},
        {'concernGroupId': 'CONCERN_nordic', 'basis': 'material_uncertainty', 'severity': 'blocking'},
        {'concernGroupId': 'CONCERN_hard', 'basis': 'established_violation', 'severity': 'blocking'},
    ]}, 'audit': {'issues': [], 'errors': []}, 'submittedDraft': draft,
        'requirementsId': stored['requirementsId'],
        'libraryFingerprint': 'library-checkpoint', 'historyFingerprint': None}
    store(messages, 'audit_workout_plan', {}, result, 'review')

    decision_schema = record_planning_decisions_tool(messages)['function']['parameters']
    decision_properties = decision_schema['properties']['decisions']['items']['properties']
    concern_schema = decision_properties['acceptedConcernGroupId']
    assert concern_schema['enum'] == ['CONCERN_nordic', 'CONCERN_soft']
    assert 'concernGroupId' not in decision_properties
    from workout_generator_pkg.planning_tools import _requirement_update_tool, workout_requirements_tool
    fresh_messages = [{'role': 'user', 'content': 'Plan my next workout.'}]
    store(fresh_messages, 'audit_workout_plan', {}, result, 'fresh-review')
    fresh_schema = workout_requirements_tool(equipment, fresh_messages)['function']['parameters']
    assert fresh_schema['properties']['planningDecisions']['properties']['decisions']['items'][
        'properties']['acceptedConcernGroupId']['enum'] == ['CONCERN_nordic', 'CONCERN_soft']
    embedded_schema = workout_requirements_tool(equipment, messages)['function']['parameters']
    assert embedded_schema['properties']['planningDecisions']['properties']['decisions']['items'][
        'properties']['acceptedConcernGroupId']['enum'] == ['CONCERN_nordic', 'CONCERN_soft']
    update_schema = _requirement_update_tool(equipment, {'requirementsId': 'REQUIREMENTS_test'}, messages)[
        'function']['parameters']
    assert update_schema['properties']['planningDecisions']['properties']['decisions']['items'][
        'properties']['acceptedConcernGroupId']['enum'] == ['CONCERN_nordic', 'CONCERN_soft']

    args = {'decisions': [{'topic': 'Accept disclosed Nordic uncertainty',
        'choice': 'Accept this reviewed concern for the current plan.',
        'sourceReferences': ['SOURCE_1'], 'acceptedConcernGroupId': 'CONCERN_nordic'}]}
    proposal = propose_decisions(args, messages)
    assert proposal['decisions']['DECISION_0']['acceptedConcernGroupId'] == 'CONCERN_nordic'
    scope = candidate_acceptance_scope(result)
    assert proposal['decisions']['DECISION_0']['acceptedCandidateScope'] == scope
    changed_candidate = copy.deepcopy(result)
    changed_candidate['submittedDraft']['workouts'][0]['name'] += ' changed'
    assert candidate_acceptance_scope(changed_candidate) != scope
    for field, changed_value in (('libraryFingerprint', 'different-library'),
                                 ('historyFingerprint', 'different-history')):
        changed_evidence = copy.deepcopy(result)
        changed_evidence[field] = changed_value
        assert candidate_acceptance_scope(changed_evidence) != scope
    generic = propose_decisions({'decisions': [{'topic': 'Ordinary interpretation',
        'choice': 'Use the existing counting convention.', 'sourceReferences': ['SOURCE_1']}]}, messages)
    assert 'acceptedConcernGroupId' not in generic['decisions']['DECISION_0']
    assert 'acceptedCandidateScope' not in generic['decisions']['DECISION_0']
    for invalid_concern in ('CONCERN_hard', 'CONCERN_stale'):
        with pytest.raises(ValidationError):
            propose_decisions({**args, 'decisions': [{**args['decisions'][0],
                'acceptedConcernGroupId': invalid_concern}]}, messages)
    with pytest.raises(ValidationError):
        propose_decisions({**args, 'decisions': [{**args['decisions'][0],
            'concernGroupId': 'CONCERN_nordic'}]}, messages)


def test_concern_choice_survives_a_rejected_attempt_only_for_the_same_current_candidate():
    equipment, _, stored, draft = planning_case()
    draft = copy.deepcopy(draft)
    for workout in draft['workouts']:
        for exercise in workout['exercises']:
            exercise.pop('placementNotes', None)
    messages = source_messages(stored)
    reviewed = {'passed': False, 'review': {'findings': [
        {'concernGroupId': 'CONCERN_soft', 'basis': 'uncertainty', 'severity': 'warning'}]},
        'audit': {'issues': [], 'errors': []}, 'submittedDraft': copy.deepcopy(draft),
        'currentDraftId': 'REVISION_0', 'requirementsId': stored['requirementsId'],
        'libraryFingerprint': 'library-checkpoint', 'historyFingerprint': 'history-checkpoint'}
    store(messages, 'audit_workout_plan', {}, reviewed, 'review')

    rejected_attempt = {'passed': False, 'tool': 'audit_workout_plan',
        'currentDraftId': 'REVISION_0', 'requirementsId': stored['requirementsId'],
        'currentDraft': copy.deepcopy(draft), 'errors': [{'code': 'repair_rejected'}]}
    store(messages, 'audit_workout_plan', {}, rejected_attempt, 'rejected-attempt')

    properties = record_planning_decisions_tool(messages)['function']['parameters'][
        'properties']['decisions']['items']['properties']
    assert properties['acceptedConcernGroupId']['enum'] == ['CONCERN_soft']
    arguments = {'decisions': [{'topic': 'Accept the disclosed tradeoff',
        'choice': 'Accept this soft tradeoff for the current candidate.',
        'sourceReferences': ['SOURCE_1'], 'acceptedConcernGroupId': 'CONCERN_soft'}]}
    proposal = propose_decisions(arguments, messages)
    assert proposal['decisions']['DECISION_0']['acceptedCandidateScope'] == candidate_acceptance_scope(reviewed)

    changed_attempt = copy.deepcopy(rejected_attempt)
    changed_attempt['currentDraft']['workouts'][0]['name'] += ' changed'
    store(messages, 'audit_workout_plan', {}, changed_attempt, 'changed-attempt')
    changed_properties = record_planning_decisions_tool(messages)['function']['parameters'][
        'properties']['decisions']['items']['properties']
    assert 'acceptedConcernGroupId' not in changed_properties

    for field in ('libraryFingerprint', 'historyFingerprint'):
        mismatched_evidence = copy.deepcopy(rejected_attempt)
        mismatched_evidence[field] = 'different-checkpoint'
        store(messages, 'audit_workout_plan', {}, mismatched_evidence, f'mismatched-{field}')
        mismatched_properties = record_planning_decisions_tool(messages)['function']['parameters'][
            'properties']['decisions']['items']['properties']
        assert 'acceptedConcernGroupId' not in mismatched_properties


def test_failed_saved_review_exposes_only_current_carried_material_uncertainty():
    path = Path('build/workout_concentration_20261026/review_source_decision_v1/workouts/conversation_sessions/'
                'd697dfae-c3f5-412c-8660-3617297ce94e/messages.json')
    messages = json.loads(path.read_text(encoding='utf-8'))

    concern_ids = reviewable_concern_ids(messages)

    assert concern_ids == ['CONCERN_b3fbf6ab8f3b4a1eb942', 'CONCERN_cea4e58931f0e85c24b9']


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
    finding = {'severity': 'blocking', 'basis': 'established_violation', 'muscleTargets': [], 'action': 'clarify', 'decisionId': 'DECISION_0',
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


def test_rejected_decision_reference_retries_as_draft_without_superseding_approved_choice(monkeypatch):
    from workout_generator_pkg.planning_tools import requirement_sources

    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    approved = record(monkeypatch, messages, equipment)
    rejected = {'passed': False, 'requirements': stored['requirements'],
        'requirementsId': stored['requirementsId'], 'sourceMessages': requirement_sources(messages),
        'sourceReview': {'passed': False}, 'resolvedDecisions': approved['decisions'],
        'proposedDecisions': {'DECISION_1': {
            'topic': 'Exercise exposure limits',
            'choice': 'A rejected explanation of the delegated exposure limits.',
            'sourceReferences': ['SOURCE_1']}},
        'errors': [{'code': 'decision_source_finding', 'path': '/decisions/DECISION_1'}]}
    store(messages, 'set_workout_requirements', {}, rejected, 'rejected-proposal')

    schema = record_planning_decisions_tool(messages)['function']['parameters']
    supersedes = schema['properties']['decisions']['items']['properties']['supersedes']
    assert supersedes['enum'] == [None, 'DECISION_0']
    from workout_generator_pkg.api_client import _strict_wire_schema
    from jsonschema import validate as validate_schema
    wire = _strict_wire_schema(supersedes)
    validate_schema(None, wire)
    validate_schema('DECISION_0', wire)
    with pytest.raises(ValidationError):
        validate_schema('DECISION_1', wire)

    corrected = {'decisions': [{'topic': 'Exercise exposure limits',
        'choice': 'Use the delegated limits without claiming they force family diversity.',
        'sourceReferences': ['SOURCE_1'], 'supersedes': 'DECISION_1',
        'reason': 'Correct the rejected rationale while keeping the delegated choice.'}]}
    proposal = propose_decisions(corrected, messages)

    assert proposal['newDecisionIds'] == ['DECISION_1']
    assert proposal['decisions']['DECISION_0'] == approved['decisions']['DECISION_0']
    assert 'supersededBy' not in proposal['decisions']['DECISION_0']
    assert 'supersedes' not in proposal['decisions']['DECISION_1']
    assert json.loads(messages[-1]['content']) == rejected


def test_pending_decision_reference_is_source_scoped_and_cannot_shadow_active_choice(monkeypatch):
    from workout_generator_pkg.planning_tools import requirement_sources

    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    approved = record(monkeypatch, messages, equipment)
    pending = {'passed': False, 'requirements': stored['requirements'],
        'requirementsId': stored['requirementsId'], 'sourceMessages': requirement_sources(messages),
        'sourceReview': {'passed': False}, 'resolvedDecisions': approved['decisions'],
        'proposedDecisions': {'DECISION_0': {
            'topic': 'Balance counting', 'choice': 'Rejected replacement.',
            'sourceReferences': ['SOURCE_1']}}}
    store(messages, 'set_workout_requirements', {}, pending, 'colliding-proposal')
    replacement = {'decisions': [{'topic': 'Balance counting',
        'choice': 'A changed choice without a newly reviewed conflict.',
        'sourceReferences': ['SOURCE_1'], 'supersedes': 'DECISION_0',
        'reason': 'Try the colliding rejected reference.'}]}
    with pytest.raises(PlanningInputError) as error:
        propose_decisions(replacement, messages)
    assert error.value.code == 'decision_already_recorded'

    messages.append({'role': 'user', 'content': 'A new instruction changes the choice context.'})
    with pytest.raises(PlanningInputError) as error:
        propose_decisions({**replacement, 'decisions': [{**replacement['decisions'][0],
            'topic': 'New exposure choice', 'supersedes': 'DECISION_1'}]}, messages)
    assert error.value.code == 'unknown_decision_reference'
    assert 'rejected proposal is not settled' in error.value.repair
    with pytest.raises(ValidationError):
        propose_decisions({**replacement, 'decisions': [{**replacement['decisions'][0],
            'supersedes': ['DECISION_0']}]}, messages)


def test_corrected_pending_replacement_keeps_its_approved_target_and_requires_same_guard(monkeypatch):
    from workout_generator_pkg.planning_tools import requirement_sources

    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    approved = record(monkeypatch, messages, equipment)
    conflict = {'passed': False, 'review': {'findings': [{
        'decisionId': 'DECISION_0', 'action': 'clarify',
        'newConflictEvidencePaths': ['/audit/weeklyVolume']} ]}}
    store(messages, 'audit_workout_plan', {}, conflict, 'new-conflict')
    pending = {'passed': False, 'requirements': stored['requirements'],
        'requirementsId': stored['requirementsId'], 'sourceMessages': requirement_sources(messages),
        'sourceReview': {'passed': False}, 'resolvedDecisions': approved['decisions'],
        'proposedDecisions': {'DECISION_1': {
            'topic': 'Balance counting', 'choice': 'A rejected replacement.',
            'sourceReferences': ['SOURCE_1'], 'supersedes': 'DECISION_0',
            'reason': 'A new audited conflict was identified.'}}}
    store(messages, 'set_workout_requirements', {}, pending, 'rejected-replacement')
    corrected = {'decisions': [{'topic': 'Balance counting',
        'choice': 'Use the corrected convention for the audited conflict.',
        'sourceReferences': ['SOURCE_1'], 'supersedes': 'DECISION_1',
        'reason': 'Correct the rejected replacement while preserving its approved target.'}]}

    proposal = propose_decisions(corrected, messages)

    assert proposal['newDecisionIds'] == ['DECISION_1']
    assert proposal['decisions']['DECISION_0']['supersededBy'] == 'DECISION_1'
    assert proposal['decisions']['DECISION_1']['supersedes'] == 'DECISION_0'


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
