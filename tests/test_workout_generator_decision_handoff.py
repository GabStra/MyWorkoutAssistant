import copy
import json

import pytest

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.interactive_shell import handle_function_call, _messages_for_api
from workout_generator_pkg.planner_context import pending_reaudit
from workout_generator_pkg.planning_decisions import propose_decisions, resolved_decisions
from workout_generator_pkg.planning_tools import PlanningInputError, planning_tool_failure
from test_workout_generator_planning_tools import planning_case
from test_workout_generator_planner_context import _state
from test_workout_generator_planning_decisions import source_messages, record, choice, store, _without_review_refs


def _reviewed_choice(monkeypatch):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['description'] = 'Perform the lateral-delt/core pair as a superset.'
    messages = source_messages(stored)
    record(monkeypatch, messages, equipment)
    finding = {'severity': 'blocking', 'basis': 'established_violation', 'muscleTargets': [], 'action': 'clarify',
        'decisionId': 'DECISION_0', 'path': '/resolvedDecisions/DECISION_0',
        'message': 'The current audit exposes a conflict in the chosen interpretation.',
        'evidencePaths': ['/sourceMessages/SOURCE_1/content', '/audit/weeklyVolume'],
        'newConflictEvidencePaths': ['/audit/weeklyVolume'], 'repair': 'Ask about the conflict.'}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed']
    store(messages, 'audit_workout_plan', draft, result, 'reviewed')
    return equipment, messages, draft


def _clarify(monkeypatch, messages, equipment):
    messages.append({'role': 'user', 'content': 'Keep the combined targets, but omit the unsupported separate regional report.'})
    args = {'decisions': [{'topic': 'Balance counting', 'choice': 'Use the supported combined report without separate regional totals.',
                          'sourceReferences': ['SOURCE_2'], 'supersedes': 'DECISION_0',
                          'reason': 'The user explicitly clarified the reporting convention.'}]}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    result = json.loads(handle_function_call(None, messages, 'record_planning_decisions', args, equipment)['result'])
    assert result['passed']
    store(messages, 'record_planning_decisions', args, result, 'clarified')
    return args, result


def test_saved_clarification_refreshes_review_once_and_preserves_actual_workout_findings(monkeypatch):
    equipment, messages, draft = _reviewed_choice(monkeypatch)
    args, accepted = _clarify(monkeypatch, messages, equipment)
    duplicate = copy.deepcopy(args)
    duplicate['decisions'][0].update(topic='Same choice restated against stale feedback',
        choice='Continue to use combined-only totals, with no separately audited regional values.', supersedes='DECISION_1')
    with pytest.raises(PlanningInputError) as error:
        propose_decisions(duplicate, messages)
    assert error.value.code == 'decision_already_recorded'
    store(messages, 'record_planning_decisions', duplicate,
          planning_tool_failure('record_planning_decisions', error.value, duplicate), 'duplicate')
    before = copy.deepcopy(messages)
    state = _state(_messages_for_api(messages, True, provided_equipment=equipment))
    request = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': []}
    assert state['decisionReaudit'] == pending_reaudit(state, 'My answer: combined-only reporting') == request
    assert state['lastAudit']['errors'] == [] and not state.get('repairTask')
    assert not state['planningDecisionNeeded'] and 'record_planning_decisions' not in state['otherToolResults']
    assert state['currentDraft'] == draft and messages == before
    # A later, unresolved user reversal must not be consumed by the earlier receipt.
    reversed_state = _state(_messages_for_api(messages + [{'role': 'user', 'content': 'Actually use a different reporting convention.'}],
                                             True, provided_equipment=equipment))
    assert reversed_state['planningDecisionNeeded'] and not reversed_state.get('decisionReaudit')
    calls = []
    remaining = {'severity': 'blocking', 'basis': 'established_violation', 'muscleTargets': [], 'path': '/draft/workouts/0',
        'message': 'The description declares a superset but the workout contains no superset group.',
        'evidencePaths': ['/draft/workouts/0'], 'repair': 'Encode the pair or correct the description.'}
    def fresh_review(client, request, **options):
        context = json.loads(request[-1]['content'])
        calls.append(context)
        clean = _without_review_refs(context['resolvedDecisions'])
        assert set(clean) == {'DECISION_1'} and clean == resolved_decisions(messages)
        return json.dumps({'findings': [remaining]}), None, None
    monkeypatch.setattr(review, 'chat_call', fresh_review)
    refreshed = json.loads(handle_function_call(None, messages, 'audit_workout_plan', request, equipment)['result'])
    assert len(calls) == 1 and not refreshed['passed']
    assert refreshed['submittedDraft'] == draft and refreshed['currentDraftId'] == 'REVISION_0'
    assert refreshed['errors'][0]['message'] == remaining['message']
    store(messages, 'audit_workout_plan', request, refreshed, 'fresh-review')
    state = _state(_messages_for_api(messages, True, provided_equipment=equipment))
    assert pending_reaudit(state, '/continue') is None and not state['planningDecisionNeeded']
    assert state['repairTask']['findingCode'] == 'independent_review_finding'
    assert state['resolvedDecisions']['DECISION_1'] == accepted['decisions']['DECISION_1']
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('A numerical failure must not rerun semantic review.'))
    patch = {**request, 'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 3}]}
    numerical = json.loads(handle_function_call(None, messages, 'audit_workout_plan', patch, equipment)['result'])
    assert numerical['previousReviewFindings'][0]['message'] == remaining['message']


def test_renamed_exact_choice_reuses_last_success_even_after_a_failed_proposal(monkeypatch):
    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    original = record(monkeypatch, messages, equipment)
    store(messages, 'record_planning_decisions', {}, {'passed': False, 'errors': [{'code': 'decision_already_recorded'}]}, 'failed')
    args = choice()
    args['decisions'][0].update(topic='A different title', choice='  COUNT EACH WORKING SET ONCE\nFOR MOVEMENT BALANCE.  ',
                              supersedes='DECISION_0', reason='Restating the same recorded choice.')
    assert propose_decisions(args, messages)['newDecisionIds'] == []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('The same authorization must be reused.'))
    result = json.loads(handle_function_call(None, messages, 'record_planning_decisions', args, equipment)['result'])
    assert result['cached'] and result['decisions'] == original['decisions']


def test_identical_wording_on_distinct_topics_is_not_silently_merged(monkeypatch):
    equipment, _, stored, _ = planning_case()
    messages = source_messages(stored)
    record(monkeypatch, messages, equipment)
    args = choice()
    args['decisions'][0]['topic'] = 'A separate counting topic'
    assert propose_decisions(args, messages)['newDecisionIds'] == ['DECISION_1']


def test_new_reviewed_conflict_can_reopen_a_delegated_choice_without_another_user_message(monkeypatch):
    _, messages, _ = _reviewed_choice(monkeypatch)
    args = choice()
    args['decisions'][0].update(choice='Use a different disclosed convention within the delegated targets.',
        supersedes='DECISION_0', reason='The new review identifies a concrete numerical conflict.')
    proposal = propose_decisions(args, messages)
    assert proposal['newDecisionIds'] == ['DECISION_1']
    assert proposal['decisions']['DECISION_0']['supersededBy'] == 'DECISION_1'
    assert list(resolved_decisions(messages)) == ['DECISION_0']


def test_changed_decision_drops_old_review_findings_during_numerical_repair(monkeypatch):
    equipment, messages, draft = _reviewed_choice(monkeypatch)
    _clarify(monkeypatch, messages, equipment)
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('Numerical failure defers review.'))
    args = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 3}]}
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', args, equipment)['result'])
    assert not result['passed'] and result['reviewPending']
    assert result['previousReviewFindings'] == []
    assert list(result['resolvedDecisions']) == ['DECISION_1']
