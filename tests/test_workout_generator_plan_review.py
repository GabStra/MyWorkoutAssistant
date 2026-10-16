import copy
import json
from types import SimpleNamespace

import pytest

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.interactive_shell import handle_function_call, _messages_for_api
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages, approved_messages


def _finding(severity='blocking'):
    return {'severity': severity, 'path': '/exercises/0/placementNotes',
            'message': 'Execution instructions conflict with approved effort.',
            'evidencePaths': ['/sourceMessages/SOURCE_0/content', '/draft/exercises/0/placementNotes'],
            'repair': 'Match the prescribed effort to the approved requirement and re-audit.'}


def _store(messages, result, call_id='audit'):
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {'name': 'audit_workout_plan'}}]},
                     {'role': 'tool', 'tool_call_id': call_id, 'content': result['result']}])


@pytest.mark.parametrize('stage, code', [
    ('decision', 'decision_review_failed'), ('requirements', 'requirements_review_failed'), ('draft', 'review_execution_failed')])
def test_truncated_reviews_log_diagnostics_and_never_approve_or_retry(monkeypatch, stage, code):
    from workout_generator_pkg.api_client import TruncatedResponseError
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content='rejected partial output', reasoning_content='unfinished reasoning', tool_calls=None))],
        usage=SimpleNamespace(model_dump=lambda: {'completion_tokens': 65536}))
    error = TruncatedResponseError(response, 65536, 'low')
    calls, logged = [], []
    def truncate(*a, **k):
        calls.append(1)
        raise error
    monkeypatch.setattr(review, 'chat_call', truncate)
    logger = SimpleNamespace(log_request=lambda *a: None,
        log_response=lambda label, data, **options: logged.append((label, json.loads(data), options)))
    if stage == 'requirements':
        candidate = copy.deepcopy(stored)
        candidate['sourceMessages'].append({'role': 'user', 'content': 'Keep these targets.', 'messageIndex': len(messages)})
        result = review.review_requirements(None, candidate, messages, logger=logger)
    else:
        name, args = ('audit_workout_plan', draft) if stage == 'draft' else ('record_planning_decisions', {'decisions': [
            {'topic': 'Volume', 'choice': 'Keep the requested volume.', 'sourceReferences': ['SOURCE_0']}]})
        result = json.loads(handle_function_call(None, messages, name, args, equipment, logger=logger)['result'])
    assert not result['passed'] and 'preview' not in result and 'requirementsPreview' not in result
    assert result['errors'][0]['code'] == code and len(calls) == 1
    assert len(logged) == 1 and logged[0][0].startswith('rejected ')
    assert logged[0][1] == error.diagnostics and logged[0][2]['truncate_at'] == 0


@pytest.mark.parametrize('repair_succeeds', [True, False])
def test_finding_reference_repair_keeps_valid_blockers_and_is_bounded(monkeypatch, repair_succeeds):
    equipment, _, stored, draft = planning_case()
    valid = _finding()
    malformed = {**_finding('warning'), 'evidencePaths': ['/missing_evidence']}
    calls = []
    def respond(client, request, **options):
        calls.append((request, options))
        findings = [valid, malformed] if len(calls) == 1 else [
            _finding('warning') if repair_succeeds else malformed]
        return json.dumps({'findings': findings}), None, None
    monkeypatch.setattr(review, 'chat_call', respond)
    result = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and 'preview' not in result
    assert len(calls) == 2 and calls[-1][1]['reasoning_effort'] == 'low'
    assert len(json.loads(calls[-1][0][-1]['content'])['invalidFindings']) == 1
    assert result['review']['findings'][0]['severity'] == 'blocking'
    assert bool(result['review'].get('failure')) is not repair_succeeds


def test_malformed_blocker_cannot_be_downgraded_by_reference_repair(monkeypatch):
    equipment, _, stored, draft = planning_case()
    responses = iter([
        {'findings': [{**_finding(), 'path': '/invalid'}]},
        {'findings': [_finding('warning')]},
    ])
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps(next(responses)), None, None))
    result = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and 'preview' not in result
    assert 'cannot downgrade' in result['review']['failure']


def test_required_coverage_is_checked_before_review_and_claims_are_verified(monkeypatch):
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    requirements['requiredCoverage'] = [{'key': 'requested_pattern', 'description': 'The requested movement pattern', 'scope': 'eachSession'}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Include the requested movement pattern in each session.'}], equipment)
    messages = requirement_messages(stored)
    draft['requirementsId'] = stored['requirementsId']
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('Missing coverage must defer full review'))
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and result['reviewPending']
    assert result['errors'][0]['code'] == 'required_coverage_missing'
    assert result['errors'][0]['path'] == '/workouts/0/exercises'
    draft['workouts'][0]['exercises'][0]['satisfiesCoverage'] = ['requested_pattern']
    def reject_false_assignment(client, request, **options):
        context = json.loads(request[-1]['content'])
        assert context['coverageAssignments'] == {'EXERCISE_0': ['requested_pattern']}
        assert context['requirements']['requiredCoverage'] == requirements['requiredCoverage']
        return json.dumps({'findings': [{**_finding(), 'path': '/coverageAssignments/EXERCISE_0/0',
            'message': 'Assigned exercise does not satisfy the requested movement pattern.'}]}), None, None
    monkeypatch.setattr(review, 'chat_call', reject_false_assignment)
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and result['errors'][0]['code'] == 'independent_review_finding'
    assert result['errors'][0]['draftPath'] == '/workouts/0/exercises/0/satisfiesCoverage'


def test_coverage_claim_changes_invalidate_a_successful_review(monkeypatch):
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    requirements['requiredCoverage'] = [{'key': 'chest', 'description': 'Chest work', 'scope': 'eachSession'}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Include chest work in each session.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0]['satisfiesCoverage'] = ['chest']
    messages = requirement_messages(stored)
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert result['passed']
    review.require_current_review(result, messages, equipment)
    result['submittedDraft']['workouts'][0]['exercises'][0]['satisfiesCoverage'] = []
    with pytest.raises(ValueError, match='missing or stale'):
        review.require_current_review(result, messages, equipment)


@pytest.mark.parametrize('needs_related', ['none', 'concern', 'missing_exact', 'claim'])
def test_review_history_keeps_material_related_records_but_omits_unused_details(needs_related):
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    if needs_related == 'claim':
        draft['workouts'][0]['exercises'][0]['placementNotes'] = 'Compared to Historical movement.'
    result = audit_workout_plan(draft, equipment, messages)
    related = {'reference': 'HISTORY_0', 'definitionId': 'old', 'name': 'Historical movement',
        'sessions': [{'date': '2026-10-01', 'performances': [{'record': {
            'actualReps': 10, 'loadKg': 40, 'loadMeaning': 'pair_total', 'autoRegulationRIR': 2}}]}]}
    item = {'reference': 'LIBRARY_0', 'definitionId': 'press', 'name': 'Push-Up',
        'sessions': [] if needs_related == 'missing_exact' else [{'date': '2026-10-10', 'performances': [{'record': {'actualReps': 8}}]}],
        'loadSuitabilityConcerns': [{'code': 'related_history_only'}] if needs_related == 'concern' else [],
        'relatedMovementHistory': [related]}
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'history', 'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': 'history', 'content': json.dumps({
            'historyFingerprint': 'current', 'libraryFingerprint': library_fingerprint(equipment), 'exercises': [item]})}])
    before = copy.deepcopy(messages)
    context = review._context(result, messages, equipment, 'current', len(messages)-1)
    other = context['history']['HISTORY_0']
    if needs_related == 'none':
        assert 'sessions' not in other and other['historyDetailsOmitted']
    else:
        assert other['sessions'][0]['performances'][0]['record']['autoRegulationRIR'] == 2
        assert other['sessions'][0]['performances'][0]['record']['loadMeaning'] == 'pair_total'
    assert messages == before


def test_numerical_repairs_defer_review_but_keep_prior_findings_until_fresh_review(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    calls, stages = [], []
    def call(client, request, **options):
        calls.append(json.loads(request[-1]['content']))
        assert options['response_format'] == {'type': 'json_object'}
        return json.dumps({'findings': [_finding()]}), None, None
    monkeypatch.setattr(review, 'chat_call', call)
    prior = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    _store(messages, prior, 'prior')
    assert len(calls) == 1
    bad = copy.deepcopy(draft)
    bad['workouts'][0]['exercises'][0]['numWorkSets'] = 1
    failed = handle_function_call(None, messages, 'audit_workout_plan', bad, equipment)
    combined = json.loads(failed['result'])
    assert not combined['passed'] and failed['draft_preview'] is None
    assert combined['reviewPending'] and 'review' not in combined
    assert {e['code'] for e in combined['errors']} == {'volume_below_target'}
    finding = combined['previousReviewFindings'][0]
    assert finding['draftPath'] == '/workouts/0/exercises/0/placementNotes'
    assert len(calls) == 1
    _store(messages, failed, 'numerical')
    compact = json.loads(next(m['content'].split('\n', 1)[1] for m in _messages_for_api(messages, True)
        if m.get('content', '').startswith('Current planning state')))['lastAudit']
    assert compact['previousReviewFindings'][0] == finding
    draft['workouts'][0]['exercises'][0]['placementNotes'] = 'Repaired effort instructions.'
    result = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment, progress=stages.append)
    payload = json.loads(result['result'])
    assert not payload['passed'] and result['draft_preview'] is None
    assert payload['errors'][0]['repair'] == _finding()['repair']
    assert stages and len(calls) == 2
    _store(messages, result)
    snapshot = next(m['content'] for m in _messages_for_api(messages, True) if m.get('content', '').startswith('Current planning state'))
    compact = json.loads(snapshot.split('\n', 1)[1])['lastAudit']
    assert compact['errors'][0]['evidencePaths'] == _finding()['evidencePaths']
    assert compact['errors'][0]['repair'] == _finding()['repair']
    handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    assert len(calls) == 2  # Failed review is also cached; unchanged retries cannot fish for approval.
    revised = copy.deepcopy(draft)
    revised['workouts'][0]['exercises'][0]['placementNotes'] = 'Revised execution.'
    handle_function_call(None, messages, 'audit_workout_plan', revised, equipment)
    assert len(calls) == 3


def test_successful_review_is_reused_and_confirmation_rejects_stale_or_missing_review(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    calls = []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or '{"findings":[]}', None, None))
    result = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    payload = json.loads(result['result'])
    assert payload['passed'] and result['draft_preview']
    approved = approved_messages(stored, payload)
    review.require_current_review(payload, approved, equipment)
    _store(messages, result)
    handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    assert len(calls) == 1
    changed = copy.deepcopy(payload)
    changed['planIndex']['exercises'][0]['placementNotes'] = 'Changed after review.'
    with pytest.raises(ValueError, match='missing or stale'):
        review.require_current_review(changed, approved, equipment)
    missing = audit_workout_plan(draft, equipment, requirement_messages(stored))
    bypass = handle_function_call(None, approved_messages(stored, missing), 'generate_workout', {}, equipment,
                                 deps=SimpleNamespace(execute_workout_generation=lambda *a, **k: pytest.fail('Export bypassed review')))
    assert bypass['continue_planning'] and 'missing or stale' in bypass['result']


@pytest.mark.parametrize('read_only', [True, False])
def test_followup_check_preserves_questions_but_blocks_new_constraints(monkeypatch, read_only):
    equipment, _, stored, draft = planning_case()
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    payload = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    messages = approved_messages(stored, payload)
    messages.append({'role': 'user', 'content': 'Why this order?' if read_only else 'Remove push-ups; I cannot perform them.'})
    messages.append({'role': 'user', 'content': 'CONFIRM GENERATE'})
    with pytest.raises(ValueError, match='New conversation instructions'):
        review.require_current_review(payload, messages, equipment)
    calls = []
    def classify(client, request, **options):
        calls.append(request)
        assert options['reasoning_effort'] == 'low'
        assert 'workouts' not in json.loads(request[-1]['content'])
        return json.dumps({'readOnly': read_only, 'reason': 'Question only' if read_only else 'New exercise restriction'}), None, None
    monkeypatch.setattr(review, 'chat_call', classify)
    for _ in range(2):
        if read_only:
            review.review_followup_instructions(None, payload, messages, equipment)
            review.require_current_review(payload, messages, equipment)
        else:
            blocked = handle_function_call(None, messages, 'generate_workout', {}, equipment,
                deps=SimpleNamespace(execute_workout_generation=lambda *a, **k: pytest.fail('Exported stale approval')))
            assert blocked['continue_planning'] and 'review_source_changed' in blocked['result']
    assert len(calls) == 1
    saved = review._latest_result(messages, 'audit_workout_plan')[1]
    assert saved['review']['followupReview']['readOnly'] is read_only
    assert saved['draftId'] == payload['draftId']
    if not read_only:
        from workout_generator_pkg.interactive_shell import _messages_for_api
        request = _messages_for_api(messages, True, provided_equipment=equipment)
        state = json.loads(next(m['content'].split('\n', 1)[1] for m in request
                                if (m.get('content') or '').startswith('Current planning state')))
        assert not state['lastAudit']['passed']
        assert state['lastAudit']['errors'][0]['code'] == 'review_source_changed'
    messages.append({'role': 'user', 'content': 'Also avoid jumping.'})
    with pytest.raises(ValueError, match='New conversation instructions'):
        review.require_current_review(saved, messages, equipment)


def test_followup_failure_is_cached_until_explicit_retry(monkeypatch):
    equipment, _, stored, draft = planning_case()
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    payload = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    messages = approved_messages(stored, payload) + [{'role': 'user', 'content': 'Why these rests?'}]
    calls = []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or 'invalid json', None, None))
    for _ in range(2):
        with pytest.raises(ValueError, match='Follow-up review failed'):
            review.review_followup_instructions(None, payload, messages, equipment)
    assert len(calls) == 1
    messages.append({'role': 'user', 'content': '/continue'})
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or '{"readOnly":true,"reason":"Question only"}', None, None))
    review.review_followup_instructions(None, payload, messages, equipment)
    assert len(calls) == 2
    review.require_current_review(payload, messages, equipment)
    messages.append({'role': 'user', 'content': 'Explain the exercise selection too.'})
    def cancel(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(review, 'chat_call', cancel)
    with pytest.raises(KeyboardInterrupt):
        review.review_followup_instructions(None, payload, messages, equipment)
    with pytest.raises(ValueError, match='New conversation instructions'):
        review.require_current_review(payload, messages, equipment)


@pytest.mark.parametrize('response', ['not json', '{"findings":[{"severity":"warning"}]}',
    json.dumps(review._RESPONSE), json.dumps(review._RESPONSE) + ',"findings":[]}',
    json.dumps({'findings': [{**_finding(), 'path': '/exercises/999'}]}),
    json.dumps({'findings': [{**_finding(), 'evidencePaths': ['/invented']}]}),])
def test_invalid_review_cannot_approve_a_preview(monkeypatch, response):
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (response, None, None))
    messages = requirement_messages(stored)
    failed = review.review_draft(None, result, messages, equipment)
    assert not failed['passed'] and 'preview' not in failed
    assert failed['errors'][0]['code'] == 'review_execution_failed'
    _store(messages, {'result': json.dumps(failed)})
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('Unchanged failed reviews must be cached'))
    cached = review.review_draft(None, result, messages, equipment)
    assert cached['errors'] == failed['errors']


def test_explicit_continue_retries_failed_output_but_not_valid_blocking_findings(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    calls = []
    responses = iter([json.dumps(review._RESPONSE), json.dumps({'findings': [_finding()]})])
    def call(client, request, **options):
        calls.append(1)
        assert 'Never return a JSON Schema' in request[0]['content']
        assert json.dumps(review._RESPONSE) not in request[0]['content']
        return next(responses), None, None
    monkeypatch.setattr(review, 'chat_call', call)
    failed = review.review_draft(None, result, messages, equipment)
    _store(messages, {'result': json.dumps(failed)}, 'failed-format')
    assert review.review_draft(None, result, messages, equipment)['review']['failure']
    assert len(calls) == 1
    messages.append({'role': 'user', 'content': '/continue'})
    retried = review.review_draft(None, result, messages, equipment)
    assert len(calls) == 2 and not retried['passed']
    assert retried['errors'][0]['code'] == 'independent_review_finding'
    _store(messages, {'result': json.dumps(retried)}, 'valid-blocker')
    messages.append({'role': 'user', 'content': '/continue'})
    assert not review.review_draft(None, result, messages, equipment)['passed']
    assert len(calls) == 2


@pytest.mark.parametrize('path,evidence', [
    ('/draft/workouts/0', '/draft/workouts/0'), ('/workouts/0', '/workouts/0'),
    ('/draft/workouts/0', '/workouts/0'), ('/workouts/0', '/draft/workouts/0')])
def test_review_normalizes_both_path_roots_without_another_model_call(monkeypatch, path, evidence):
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    finding = {**_finding(), 'path': path, 'evidencePaths': [evidence]}
    calls = []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or json.dumps({'findings': [finding]}), None, None))
    outcome = review.review_draft(None, result, requirement_messages(stored), equipment)
    assert len(calls) == 1 and outcome['errors'][0]['code'] == 'independent_review_finding'
    assert outcome['errors'][0]['path'] == '/draft/workouts/0'
    assert outcome['errors'][0]['draftPath'] == '/workouts/0'
    assert outcome['errors'][0]['evidencePaths'] == ['/draft/workouts/0']


def test_wrong_wrapper_is_repaired_only_when_the_remaining_path_is_unique():
    context = {'draft': {'workouts': [{}]}, 'audit': {}, 'calibrationPolicy': False}
    assert review._review_pointer(context, '/audit/calibrationPolicy') == '/calibrationPolicy'
    context['draft']['calibrationPolicy'] = True
    with pytest.raises(ValueError, match='reference does not exist'):
        review._review_pointer(context, '/audit/calibrationPolicy')


def test_original_user_constraints_reach_the_reviewer(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = [{'role': 'user', 'content': 'Allow opposing OR non-competing groups; preserve movement qualifiers.'}] + requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    inputs = []
    def call(client, request, **kwargs):
        inputs.append(json.loads(request[-1]['content']))
        return '{"findings":[]}', None, None
    monkeypatch.setattr(review, 'chat_call', call)
    review.review_draft(None, result, messages, equipment)
    assert messages[0]['content'] == inputs[0]['sourceMessages']['SOURCE_0']['content']
    assert 'CONFIRM REQUIREMENTS' not in [m['content'] for m in inputs[0]['sourceMessages'].values()]
    assert inputs[0]['audit']['workouts'][0]['volume'] == result['audit']['workouts'][0]['volume']
    assert inputs[0]['audit']['workouts'][0]['contributions'] == result['audit']['workouts'][0]['contributions']


def test_export_requires_confirmation_after_the_repaired_preview(monkeypatch):
    from dataclasses import replace
    from workout_generator_pkg.deps import resolve_pipeline_deps
    from workout_generator_pkg.generation_pipeline import execute_workout_generation
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    first = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    _store(messages, first, 'first')
    payload = json.loads(first['result'])
    messages.extend([{'role': 'assistant', 'canonicalDraftPreview': payload['draftId'], 'content': payload['preview']},
                     {'role': 'user', 'content': 'CONFIRM GENERATE'}])
    patch = {'requirementsId': draft['requirementsId'], 'baseDraftId': payload['currentDraftId'], 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Revised after confirmation.'}]}
    revised = handle_function_call(None, messages, 'audit_workout_plan', patch, equipment)
    _store(messages, revised, 'revised')
    payload = json.loads(revised['result'])
    messages.append({'role': 'assistant', 'canonicalDraftPreview': payload['draftId'], 'content': payload['preview']})
    calls = []
    deps = SimpleNamespace(execute_workout_generation=lambda *a, **k: calls.append(1) or {
        'success': True, 'filepath': 'mock.json', 'error': None})
    blocked = handle_function_call(None, messages, 'generate_workout', {}, equipment, deps=deps)
    assert not calls and 'fresh CONFIRM GENERATE' in blocked['result']
    pipeline_deps = replace(resolve_pipeline_deps(), test_connection=lambda *a, **k: (True, None))
    exported = execute_workout_generation(None, messages, provided_equipment=equipment, deps=pipeline_deps)
    assert not exported['success'] and 'fresh CONFIRM GENERATE' in exported['error']
    messages.append({'role': 'user', 'content': 'CONFIRM GENERATE'})
    handle_function_call(None, messages, 'generate_workout', {}, equipment, deps=deps)
    assert calls == [1]


@pytest.mark.parametrize('path,expected', [
    ('/draft/planName', '/name'),
    ('/draft/exercises/0/libraryDefinitionId', '/workouts/0/exercises/0/definition_id'),
    ('/draft/workouts/0/restToNextSeconds/0', '/workouts/0/exercises/0/restAfterExerciseSeconds'),
    ('/draft/workouts/0/supersetGroups/0/restSecondsByExercise/EXERCISE_0', '/workouts/0/exercises/0/restAfterSupersetExerciseSeconds'),
    ('/draft/workouts/0/supersetGroups/0', '/workouts/0/exercises'),
    ('/draft/workouts/0/exerciseIds/0', '/workouts/0/exercises/0'),
    ('/draft/workouts/0/id', None),
])
def test_derived_review_paths_resolve_to_editable_source_fields(monkeypatch, path, expected):
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets']['weeklyEffectiveSets'] = {}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['auditTargets']['maximumSessionSeconds'] = 4500
    stored = set_workout_requirements(requirements, [])
    draft['requirementsId'] = stored['requirementsId']
    first = draft['workouts'][0]['exercises'][0]
    first.update(superset='A', restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=40)
    second = copy.deepcopy(first)
    second['restAfterSupersetExerciseSeconds'] = 75
    draft['workouts'][0]['exercises'].append(second)
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    finding = {**_finding(), 'path': path, 'evidencePaths': [path]}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    outcome = review.review_draft(None, result, messages, equipment)
    assert 'failure' not in outcome['review']
    if expected is None:
        assert 'draftPath' not in outcome['errors'][0]
    else:
        assert outcome['errors'][0]['draftPath'] == expected
        review._pointer(draft, expected)


def test_timed_review_finding_maps_to_seconds_in_the_editable_draft(monkeypatch):
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    equipment['exerciseDefinitions'][0].update(exerciseType='COUNTUP', bodyWeightPercentage=None, name='Hold')
    requirements['auditTargets']['weeklyEffectiveSets'] = {}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use a 45-second hold.'}])
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0].update(minReps=None, maxReps=None, durationSeconds=45)
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    finding = {**_finding(), 'path': '/draft/exercises/0/timeInMillis'}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    outcome = review.review_draft(None, result, messages, equipment)
    error = outcome['errors'][0]
    assert error['path'] == '/draft/exercises/0/timeInMillis'
    assert error['draftPath'] == '/workouts/0/exercises/0/durationSeconds'
    assert review._pointer(draft, error['draftPath']) == 45
    assert 'source-schema units' in outcome['instruction']


def test_review_preserves_questions_and_answers_in_order_without_requiring_copied_notes(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    clarification = [
        {'role': 'assistant', 'content': 'Exclude just conventional deadlift or every hinge?'},
        {'role': 'user', 'content': 'Only conventional.'},
        {'role': 'assistant', 'content': 'Which balance convention should I use?'},
        {'role': 'user', 'content': 'Use your judgment within my other constraints.'}]
    messages.extend(clarification)
    requests = []
    def check(client, request, **kwargs):
        context = json.loads(request[-1]['content'])
        requests.append(context)
        assert list(context['sourceMessages'].values())[-4:] == clarification
        assert 'notes' not in context['requirements']
        assert context['restrictionPolicy'] == {'excludedExerciseNames': [], 'exceptExerciseNames': []}
        assert 'Do not request notes or a rewritten recap' in request[0]['content']
        assert 'When the user explicitly delegates a decision' in request[0]['content']
        finding = {**_finding(), 'path': '/audit/restrictionPolicy/excludedExerciseNames',
                   'evidencePaths': ['/sourceMessages/SOURCE_2/content']}
        return json.dumps({'findings': [finding]}), None, None
    monkeypatch.setattr(review, 'chat_call', check)
    result = audit_workout_plan(draft, equipment, messages)
    outcome = review.review_draft(None, result, messages, equipment)
    assert not outcome['passed'] and 'failure' not in outcome['review']
    assert outcome['errors'][0]['path'] == '/restrictionPolicy/excludedExerciseNames'
    assert len(requests) == 1


def test_raw_review_is_logged_even_when_references_are_invalid(monkeypatch):
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    raw = json.dumps({'findings': [{**_finding(), 'path': '/invented'}]})
    logged = []
    logger = SimpleNamespace(log_request=lambda *a: None, log_response=lambda label, content, **k: logged.append(content))
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (raw, None, None))
    outcome = review.review_draft(None, result, requirement_messages(stored), equipment, logger=logger)
    assert logged == [raw, raw] and outcome['review']['failure']  # Original and one bounded finding repair.


def test_warnings_are_displayed_without_mutating_draft_and_changed_context_invalidates_cache(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    calls = []
    def call(*args, **kwargs):
        calls.append(1)
        return json.dumps({'findings': [_finding('warning')]}), None, None
    monkeypatch.setattr(review, 'chat_call', call)
    before = copy.deepcopy(draft)
    result = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    assert draft == before and 'Independent review notes:' in result['draft_preview']
    _store(messages, result)
    messages.append({'role': 'user', 'content': 'Keep all movements as straight sets.'})
    handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    assert len(calls) == 2


def test_review_cancellation_propagates(monkeypatch):
    equipment, _, stored, draft = planning_case()
    def cancel(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(review, 'chat_call', cancel)
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    with pytest.raises(KeyboardInterrupt):
        review.review_draft(None, result, requirement_messages(stored), equipment)


@pytest.mark.parametrize('resume_id', [None, 'saved-generation'])
def test_pipeline_and_resume_cannot_bypass_missing_review(tmp_path, resume_id):
    from dataclasses import replace
    from workout_generator_pkg.deps import resolve_pipeline_deps
    from workout_generator_pkg.generation_pipeline import execute_workout_generation
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    deps = replace(resolve_pipeline_deps(), test_connection=lambda *a, **k: (True, None))
    exported = execute_workout_generation(None, approved_messages(stored, result), provided_equipment=equipment,
                                         script_dir=str(tmp_path), resume_session_id=resume_id, deps=deps)
    assert not exported['success'] and 'missing or stale' in exported['error']


def test_review_history_snapshot_and_json_request_use_the_configured_thinking_budget(monkeypatch):
    from workout_generator_pkg import api_client
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
            content='{"findings":[]}', reasoning_content='checked'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.with_options = lambda **kwargs: client
    api_client.chat_call(client, [], response_format={'type': 'json_object'})
    assert len(requests) == 1 and requests[0]['response_format'] == {'type': 'json_object'}
    assert requests[0]['extra_body']['thinking']['type'] == 'enabled'
    assert requests[0]['reasoning_effort'] == 'high' and requests[0]['max_tokens'] == 65536
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    history = SimpleNamespace(fingerprint='current-history')
    result = review.review_draft(None, result, requirement_messages(stored), equipment, history)
    review.require_current_review(result, requirement_messages(stored), equipment, history)
    review.require_current_review(result, requirement_messages(stored), equipment, 'current-history')
    with pytest.raises(ValueError, match='missing or stale'):
        review.require_current_review(result, requirement_messages(stored), equipment, SimpleNamespace(fingerprint='new-history'))


def test_numerical_failure_never_calls_expensive_review_or_exports(monkeypatch):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 1
    calls = []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or 'invalid JSON', None, None))
    messages = requirement_messages(stored)
    result = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    payload = json.loads(result['result'])
    assert {e['code'] for e in payload['errors']} == {'volume_below_target'}
    assert not payload['passed'] and result['draft_preview'] is None and 'planIndex' not in payload
    assert payload['reviewPending'] and 'review' not in payload
    _store(messages, result)
    handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    assert not calls


def test_previous_review_warning_remains_guidance_during_numerical_failure(monkeypatch):
    equipment, _, stored, draft = planning_case()
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [_finding('warning')]}), None, None))
    messages = requirement_messages(stored)
    previous = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    _store(messages, previous)
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 1
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('Numerical repairs must defer the reviewer'))
    result = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    payload = json.loads(result['result'])
    assert not payload['passed'] and payload['previousReviewFindings'][0]['severity'] == 'warning'
    assert 'preview' not in payload and 'planIndex' not in payload


def test_invalid_rep_targets_stop_before_expensive_execution_review(monkeypatch):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['targetSetPrescriptions'] = [
        {'workSetIndex': i, 'reps': 1, 'additionalWeight': 0} for i in range(5)]
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('Invalid contract must not invoke a reviewer'))
    with pytest.raises(ValueError, match='outside minReps'):
        handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)


def test_review_shares_definitions_losslessly_and_still_detects_changed_occurrence_fields(monkeypatch):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    second = copy.deepcopy(draft['workouts'][0]['exercises'][0])
    second['placementNotes'] = 'Different setup and effort instructions.'
    draft['workouts'][0]['exercises'].append(second)
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    context = review._context(result, messages, equipment, None, len(messages)-1)
    compact = context['draft']
    assert list(compact['libraryDefinitions']) == ['LIBRARY_0']
    for original, occurrence in zip(result['planIndex']['exercises'], compact['exercises']):
        restored = {**compact['libraryDefinitions'][occurrence['libraryDefinitionId']], **occurrence}
        restored['libraryDefinitionId'] = equipment['exerciseDefinitions'][0]['id']
        assert restored == original
        assert 'muscleGroups' not in occurrence and 'exerciseType' not in occurrence
    assert review._review_pointer(context, '/draft/libraryDefinitions/LIBRARY_0/exerciseType')
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    approved = review.review_draft(None, result, messages, equipment)
    review.require_current_review(approved, messages, equipment)
    for key, value in [('bodyWeightPercentage', 66), ('movementRef', None)]:
        changed = copy.deepcopy(approved)
        changed['planIndex']['exercises'][1][key] = value
        with pytest.raises(ValueError, match='missing or stale'):
            review.require_current_review(changed, messages, equipment)


def test_related_summary_cannot_hide_material_records_from_another_selected_movement():
    related = {'reference': 'HISTORY_0', 'name': 'Historical movement', 'sessions': [
        {'performances': [{'record': {'actualReps': 8, 'loadKg': 40, 'autoRegulationRIR': 2}}]}]}
    summary = {key: value for key, value in related.items() if key != 'sessions'} | {'historyDetailsOmitted': True}
    compact = review._compact_review_history([
        {'reference': 'LIBRARY_0', 'relatedMovementHistory': [summary]},
        {'reference': 'LIBRARY_1', 'relatedMovementHistory': [related]},
    ])
    assert not compact['HISTORY_0'].get('historyDetailsOmitted')
    assert compact['HISTORY_0']['sessions'][0]['performances'][0]['record']['autoRegulationRIR'] == 2


def test_review_history_compacts_only_reconstructible_repetition_and_keeps_effort_and_load_units():
    caution = review.RELATED_LOAD_TRANSFER_CAUTION
    record = {'actualReps': 8, 'loadKg': 40, 'loadMeaning': 'app_total_external_load', 'autoRegulationRIR': 2}
    historical = {'reference': 'LIBRARY_1', 'definitionId': 'historical-uuid', 'name': 'Single-arm row',
        'sessions': [{'date': '2026-10-01', 'performances': [{'order': 0, 'intraSetRestInSeconds': 20, 'record': record}]}]}
    roots = [{'reference': 'LIBRARY_0', 'name': 'Pair row', 'relatedMovementHistory': [
        {**historical, 'differences': {'name': {'candidate': 'Pair row', 'historical': 'Single-arm row'},
             'equipmentId': {'candidate': 'pair', 'historical': 'single'}}, 'loadTransfer': caution}]},
        {'reference': 'LIBRARY_2', 'name': 'Other row', 'relatedMovementHistory': [
             {**historical, 'loadTransfer': 'The historical load excludes the implement.'}]}]
    before = copy.deepcopy(roots)
    compact = review._compact_review_history(roots)
    link = compact['LIBRARY_0']['relatedMovementHistory'][0]
    assert 'loadTransfer' not in link and 'name' not in link['differences']
    assert link['differences']['equipmentId'] == {'candidate': 'pair', 'historical': 'single'}
    assert compact['LIBRARY_2']['relatedMovementHistory'][0]['loadTransfer'] == 'The historical load excludes the implement.'
    performance = compact['LIBRARY_1']['sessions'][0]['performances'][0]
    assert performance['record'] == record and performance['intraSetRestInSeconds'] == 20
    assert roots == before


@pytest.mark.parametrize('path', ['/draft/exercises/0/name', '/exercises/0/muscleGroups/0'])
def test_reviewer_occurrence_field_citations_resolve_to_shared_data_without_losing_patch_location(monkeypatch, path):
    equipment, _, stored, draft = planning_case()
    finding = {**_finding(), 'path': path, 'evidencePaths': [path]}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    result = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and not result['review'].get('failure')
    error = result['errors'][0]
    assert error['path'].startswith('/draft/libraryDefinitions/LIBRARY_0/')
    assert error['draftPath'] == '/workouts/0/exercises/0'
