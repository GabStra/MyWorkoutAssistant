import copy
import json
import threading
from types import SimpleNamespace

import pytest

from test_workout_generator_planning_tools import planning_case, requirement_messages
from workout_generator_pkg import interactive_shell as shell
from workout_generator_pkg.lookup_batch import execute_lookup_batch
from workout_generator_pkg.planning_tools import audit_workout_plan, requirements_approved


def store_tool(messages, name, arguments, payload, key):
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': key, 'function': {'name': name, 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(payload)},
    ])


def test_shell_allocation_is_a_proposal_until_its_patch_is_audited(monkeypatch):
    gear, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    messages = requirement_messages(stored)
    failed = audit_workout_plan(draft, gear, messages)
    store_tool(messages, 'audit_workout_plan', draft, failed, 'failed')
    before = copy.deepcopy(messages)
    proposed = shell.handle_function_call(None, messages, 'allocate_workout_sets', {
        'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0',
        'boundsBySlot': {'SLOT_0': {'minimum': 5, 'maximum': 6}},
    }, gear)
    patch = json.loads(proposed['result'])
    assert patch['feasible'] and patch['patch']
    assert messages == before and not proposed.get('draft_preview')
    monkeypatch.setattr('workout_generator_pkg.plan_review.chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    audited = shell.handle_function_call(None, messages, 'audit_workout_plan', {
        'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': patch['patch']}, gear)
    assert json.loads(audited['result'])['passed'] and audited['draft_preview']


def test_requirements_and_delegated_choice_use_one_review_then_one_confirmation(monkeypatch):
    gear, requirements, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 effective chest sets weekly in one session; choose the day for me.'}]
    calls = []
    def reviewer(client, request, **options):
        calls.append(request)
        return '{"findings":[]}', None, None
    monkeypatch.setattr('workout_generator_pkg.plan_review.chat_call', reviewer)
    arguments = {**requirements, 'planningDecisions': {'decisions': [{
        'topic': 'Training day', 'choice': 'Monday', 'sourceReferences': ['SOURCE_0']}]}}
    response = shell.handle_function_call(None, messages, 'set_workout_requirements', arguments, gear)
    result = json.loads(response['result'])
    assert result['passed'] and len(calls) == 1
    assert 'Monday' in response['requirements_preview']
    store_tool(messages, 'set_workout_requirements', arguments, result, 'requirements')
    assert not requirements_approved(messages)
    messages.extend([{'role': 'assistant', 'content': response['requirements_preview'],
                      'canonicalRequirementsPreview': result['requirementsId']},
                     {'role': 'user', 'content': 'CONFIRM REQUIREMENTS'}])
    assert requirements_approved(messages)
    from workout_generator_pkg.planning_decisions import resolved_decisions
    assert result['resolvedDecisions'] == resolved_decisions(messages)


def test_independent_lookup_batch_runs_together_and_preserves_a_failed_result(monkeypatch):
    gear, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    rendezvous = threading.Barrier(2)
    def evidence(args, equipment, client=None):
        rendezvous.wait(timeout=3)
        return {'exercises': [{'reference': args['definition_ids'][0]}]}
    def metadata(args, equipment, source):
        rendezvous.wait(timeout=3)
        raise ValueError('Unknown library reference')
    monkeypatch.setattr('workout_generator_pkg.lookup_batch.get_exercise_candidates', metadata)
    calls = [('history', 'get_training_evidence', {'definition_ids': ['LIBRARY_0']}),
             ('metadata', 'get_exercise_candidates', {'definition_ids': ['LIBRARY_999']})]
    before = copy.deepcopy(messages)
    results = execute_lookup_batch(calls, gear, None, messages, SimpleNamespace(evidence=evidence))
    assert results['history']['exercises'][0]['reference'] == 'LIBRARY_0'
    assert results['metadata']['passed'] is False and results['metadata']['errors']
    assert messages == before
    with pytest.raises(ValueError, match='mutations'):
        execute_lookup_batch([('audit', 'audit_workout_plan', {})], gear, None, messages)


def test_stable_policy_precedes_changing_planner_state():
    gear, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    store_tool(messages, 'audit_workout_plan', draft, audit_workout_plan(draft, gear, messages), 'draft')
    outgoing = shell._messages_for_api(messages, True, provided_equipment=gear)
    state = next(i for i, m in enumerate(outgoing) if (m.get('content') or '').startswith('Current planning state'))
    assert all(m['role'] != 'system' for m in outgoing[state + 1:])
    assert not any(m.get('role') == 'user' and m.get('content') == 'CONFIRM REQUIREMENTS' for m in outgoing)


def test_duration_review_cites_a_supplied_fact_without_guessing_nested_fields(monkeypatch):
    gear, _, stored, draft = planning_case()
    calls = []
    def reviewer(client, request, **options):
        calls.append(request)
        context = json.loads(request[-1]['content'])
        workout = context['audit']['workouts'][0]
        assert 'estimatedSeconds' in workout and 'estimatedSeconds' not in workout['timing']
        return json.dumps({'findings': [{
            'severity': 'warning', 'basis': 'uncertainty', 'muscleTargets': [], 'path': workout['_reviewRef'],
            'message': 'Duration is an estimate under the supplied timing assumptions.',
            'evidencePaths': [context['auditPolicy']['_reviewRef']],
            'repair': 'Disclose the timing assumptions alongside the estimated duration.'}]}), None, None
    monkeypatch.setattr('workout_generator_pkg.plan_review.chat_call', reviewer)
    result = shell.handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, gear)
    payload = json.loads(result['result'])
    assert payload['passed'] and result['draft_preview'] and len(calls) == 1, payload.get('errors')
    assert payload['review']['findings'][0]['path'] == '/audit/workouts/0'


def test_request_metrics_preserve_known_zero_cache_hits():
    from workout_generator_pkg.api_metrics import api_metrics_scope
    from workout_generator_pkg.api_client import _record_chat_metric
    lines = []
    with api_metrics_scope(SimpleNamespace(log=lines.append), 'planning'):
        _record_chat_metric(SimpleNamespace(usage={'prompt_cache_hit_tokens': 0, 'prompt_tokens': 100}),
                            0, model='test', reasoning_effort='low', max_tokens=8192,
                            timeout=None, outcome='success')
    assert json.loads(lines[0].split(' ', 1)[1])['cacheHitTokens'] == 0


def test_overlapping_history_requests_share_work_and_preserve_pages():
    gear, _, stored, _ = planning_case()
    gear['exerciseDefinitions'].append({**copy.deepcopy(gear['exerciseDefinitions'][0]), 'id': 'second-definition'})
    calls = []
    def evidence(args, equipment, client=None):
        calls.append(copy.deepcopy(args))
        return {'historyFingerprint': 'history', 'libraryFingerprint': 'library',
                'exercises': [{'reference': ref, 'page': args.get('session_offset', 0)} for ref in args['definition_ids']]}
    requests = [('first', 'get_training_evidence', {'definition_ids': ['LIBRARY_0', 'LIBRARY_1']}),
                ('overlap', 'get_training_evidence', {'definition_ids': ['LIBRARY_1']}),
                ('older', 'get_training_evidence', {'definition_ids': ['LIBRARY_1'], 'session_offset': 1})]
    result = execute_lookup_batch(requests, gear, None, requirement_messages(stored), SimpleNamespace(evidence=evidence))
    assert len(calls) == 2
    assert [item['reference'] for item in result['first']['exercises']] == ['LIBRARY_0', 'LIBRARY_1']
    assert result['overlap']['exercises'] == [{'reference': 'LIBRARY_1', 'page': 0}]
    assert result['older']['exercises'] == [{'reference': 'LIBRARY_1', 'page': 1}]
