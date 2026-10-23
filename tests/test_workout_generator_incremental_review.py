import copy
import json

import pytest

from workout_generator_pkg import plan_review, interactive_shell, review_assessment
from workout_generator_pkg.planner_context import request_planning_state, planner_response_profile
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages
from test_workout_generator_plan_review import assessment_transport


def store(messages, result):
    key = f'audit_{len(messages)}'
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': key, 'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
                     {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(result)}])


def case(monkeypatch, *, grouped=False, warning=False, impact='changed_occurrences_only'):
    equipment, _, stored, draft = planning_case()
    definition = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [{**copy.deepcopy(definition), 'id': f'd{i}', 'name': f'Movement {i}'} for i in range(7)]
    template = draft['workouts'][0]['exercises'][0]
    draft['workouts'][0]['exercises'] = [{**copy.deepcopy(template), 'definition_id': f'LIBRARY_{i}', 'numWorkSets': 1} for i in range(6)]
    if grouped:
        for item in draft['workouts'][0]['exercises'][:2]:
            item.update(superset='A', restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=30)
        draft['workouts'][0]['exercises'][1]['restAfterSupersetExerciseSeconds'] = 75
    messages = requirement_messages(stored)
    real_context = plan_review._context
    def context(result, messages, gear, history, boundary):
        value = real_context(result, messages, gear, None, boundary)
        value['history'] = {reference: {'status': 'comparable_records', 'reference': reference,
                                       'sessions': [{'date': '2026-10-01', 'performances': []}]}
                            for reference in value['draft']['libraryDefinitions']}
        return value
    monkeypatch.setattr(plan_review, '_context', context)
    requests = []
    related_index = None
    def respond(client, request, **options):
        nonlocal related_index
        payload = json.loads(request[-1]['content'])
        requests.append(payload)
        response = {'findings': []}
        if payload.get('editScopeCheck'):
            if impact is not None:
                response['sourceImpact'] = impact
        elif warning and 'LIBRARY_0' in payload['draft']['libraryDefinitions'] and 'EXERCISE_0' in payload.get('reviewedExerciseIds', []):
            related_index = next(int(identifier.split('_')[1]) for identifier in payload['reviewedExerciseIds'] if identifier != 'EXERCISE_0')
            response['findings'] = [{'basis': 'uncertainty', 'severity': 'warning', 'muscleTargets': [],
                'path': '/draft/exercises/0', 'evidencePaths': [f'/draft/exercises/{related_index}'],
                'message': 'A coupled advisory about these two movements.', 'repair': 'Check both movements together.'}]
        return json.dumps(response), None, None
    monkeypatch.setattr(plan_review, 'chat_call', respond)
    def assess(_client, request, **_options):
        finding_indexes = sorted(int(index) for index in json.loads(request[-1]['content'])['findings'])
        return json.dumps({'groups': [{'findingIndexes': [index], 'disposition': 'advisory',
            'repairDimensions': [], 'reason': 'This scoped warning is retained as advisory.'}
            for index in finding_indexes], 'repairPlan': ''}), None, None
    monkeypatch.setattr(review_assessment, '_review_call', assess)
    raw = audit_workout_plan(draft, equipment, messages)
    assert raw['passed']
    first = plan_review.review_draft(None, raw, messages, equipment)
    assert first['passed'] and len(first['review']['evidenceUnits']) == 6
    store(messages, first)
    messages.append({'role': 'assistant', 'canonicalDraftPreview': first['draftId'], 'content': first['preview']})
    messages.append({'role': 'user', 'content': 'Replace only the first movement with Movement 6; keep all other prescriptions unchanged.'})
    patch = {'requirementsId': stored['requirementsId'], 'baseDraftId': first['currentDraftId'],
             'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/definition_id', 'value': 'LIBRARY_6'}]}
    edited = audit_workout_plan(patch, equipment, messages)
    assert edited['passed']
    requests.clear()
    return equipment, messages, first, edited, requests, related_index


def test_local_substitution_reviews_only_new_movement_and_preserves_other_prescriptions(monkeypatch):
    equipment, messages, first, edited, requests, _ = case(monkeypatch)
    result = plan_review.review_draft(None, edited, messages, equipment)
    assert result['passed'], result.get('errors')
    receipt = result['review']['editScope']
    assert receipt['reviewedEvidenceUnits'] == ['LIBRARY_6']
    assert set(receipt['reusedEvidenceUnits']) == {f'LIBRARY_{i}' for i in range(1, 6)}
    assert len(requests) == 2
    assert requests[0].get('editScopeCheck')
    assert requests[1]['reviewedExerciseIds'] == ['EXERCISE_0']
    assert result['submittedDraft']['workouts'][0]['exercises'][1:] == first['submittedDraft']['workouts'][0]['exercises'][1:]
    plan_review.require_current_review(result, messages, equipment)


@pytest.mark.parametrize('impact', ['global_or_unclear', None])
def test_global_or_invalid_source_classification_cannot_reuse_old_evidence(monkeypatch, impact):
    equipment, messages, _, edited, requests, _ = case(monkeypatch, impact=impact)
    result = plan_review.review_draft(None, edited, messages, equipment)
    if impact is None:
        assert not result['passed'] and result['review']['failure']
        assert len(requests) == 1 and 'preview' not in result
    else:
        assert result['passed']
        assert result['review']['editScope']['reusedEvidenceUnits'] == []
        assert len(result['review']['editScope']['reviewedEvidenceUnits']) == 6


def test_partner_and_cross_finding_dependencies_are_rereviewed(monkeypatch):
    equipment, messages, _, edited, _, _ = case(monkeypatch, grouped=True)
    result = plan_review.review_draft(None, edited, messages, equipment)
    assert result['passed']
    assert set(result['review']['editScope']['reviewedEvidenceUnits']) == {'LIBRARY_1', 'LIBRARY_6'}


def test_changed_finding_dependency_invalidates_its_other_owner(monkeypatch):
    equipment, messages, _, edited, _, related = case(monkeypatch, warning=True)
    result = plan_review.review_draft(None, edited, messages, equipment)
    assert result['passed']
    assert set(result['review']['editScope']['reviewedEvidenceUnits']) == {f'LIBRARY_{related}', 'LIBRARY_6'}
    assert not result['review']['findings']


def test_review_context_pool_identity_is_stable_and_citations_cannot_redirect():
    history = {'LIBRARY_0': {'sessions': [{'performances': [{'equipmentContextRef': 'CONTEXT_0'}]}]}}
    contexts = {'CONTEXT_0': {'name': 'Barbell', 'type': 'BARBELL'}}
    before = copy.deepcopy(history)
    first = plan_review._stable_review_contexts(history, contexts)
    renamed = copy.deepcopy(history)
    renamed['LIBRARY_0']['sessions'][0]['performances'][0]['equipmentContextRef'] = 'CONTEXT_9'
    second = plan_review._stable_review_contexts(renamed, {'CONTEXT_9': contexts['CONTEXT_0']})
    assert first == second and history == before
    altered = plan_review._stable_review_contexts(history, {'CONTEXT_0': {'name': 'Dumbbells'}})
    assert altered != first


def test_followup_uses_low_effort_patch_work_order(monkeypatch):
    equipment, messages, _, _, _, _ = case(monkeypatch)
    state = request_planning_state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['editTask']['baseDraftId'] == state['currentDraftId']
    assert 'constructionTask' not in state and 'repairTask' not in state
    assert planner_response_profile(state) == {'reasoning_effort': None, 'activity': 'Editing workout',
                                             'max_tokens': 16384, 'timeout': 120}


def test_new_instruction_can_update_requirements_before_construction():
    from workout_generator_pkg.planner_context import construction_tool_failure
    state = {'newInstructionPending': True, 'constructionTask': {'stage': 'choose_movements', 'remainingWeeklySessions': 3}}
    assert construction_tool_failure('set_workout_requirements', {}, state) is None
    assert construction_tool_failure('record_planning_decisions', {}, state) is None


def test_evidence_dependencies_stop_at_direct_comparisons_and_ignore_display_titles():
    context = {'draft': {'exercises': [{'id': 'EXERCISE_0', 'libraryDefinitionId': 'LIBRARY_0'}],
        'libraryDefinitions': {f'LIBRARY_{i}': {'name': f'Movement {i}'} for i in range(3)},
        'workouts': [{'name': 'Original', 'description': 'Display only', 'exerciseIds': ['EXERCISE_0'],
                      'restToNextSeconds': [60], 'supersetGroups': []}]},
        'history': {'LIBRARY_0': {'relatedMovementHistory': [{'reference': 'LIBRARY_1'}], 'loadSuitabilityConcerns': []},
                    'LIBRARY_1': {'sessions': [{'reps': 8}], 'relatedMovementHistory': [{'reference': 'LIBRARY_2'}],
                                  'loadSuitabilityConcerns': ['candidate-specific'], 'relatedHistoryStatus': 'linked'},
                    'LIBRARY_2': {'sessions': [{'reps': 12}]}},
        'historyExecutionContexts': {}, 'audit': {'assumptions': {}}, 'templateExerciseIds': []}
    original = copy.deepcopy(context)
    def project(value):
        return plan_review._evidence_review_context(value, ['EXERCISE_0'])
    first = project(context)
    assert set(first['history']) == {'LIBRARY_0', 'LIBRARY_1'}
    assert set(first['draft']['libraryDefinitions']) == {'LIBRARY_0'}
    context['history']['LIBRARY_1'].update(relatedMovementHistory=[], loadSuitabilityConcerns=[], relatedHistoryStatus='direct')
    context['history']['LIBRARY_2']['sessions'][0]['reps'] = 99
    context['draft']['workouts'][0].update(name='Renamed', description='Rewritten')
    assert project(context) == first
    context['history']['LIBRARY_1']['sessions'][0]['reps'] = 7
    assert project(context) != first  # Actual comparison records remain a dependency.
    context = copy.deepcopy(original)
    context['history']['LIBRARY_0']['loadSuitabilityConcerns'] = ['no headroom']
    assert project(context) != first  # The selected movement's own suitability remains authoritative.
    assert project(original) == first


def test_comparison_finding_keeps_its_actual_target_without_reference_repair(monkeypatch):
    equipment, messages, first, _, _, _ = case(monkeypatch, grouped=True)
    boundary = first['review']['instructionBoundary']
    context = plan_review._context(first, messages, equipment, None, boundary)
    part = plan_review._evidence_review_context(context, ['EXERCISE_0'])
    calls = []
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        calls.append(payload)
        partner = payload['draft']['exercises'][1]
        return json.dumps({'findings': [{'basis': 'uncertainty', 'severity': 'warning', 'muscleTargets': [],
            'path': partner['_reviewRef'], 'evidencePaths': [partner['_reviewRef']],
            'message': 'The visible partner has a progression uncertainty.', 'repair': 'Check that partner.'}]}), None, None
    monkeypatch.setattr(plan_review, 'chat_call', respond)
    checked = plan_review._review_part(None, 'evidence', part, context, first, messages, boundary, None)
    assert len(calls) == 1  # No citation repair that could retarget the unchanged claim.
    assert checked['findings'][0]['path'] == '/draft/exercises/1'
    assert checked['findings'][0]['draftPath'] == '/workouts/0/exercises/1'


def test_comparison_findings_are_cached_on_their_actual_owners():
    context = {'draft': {'exercises': [{'id': 'EXERCISE_0', 'libraryDefinitionId': 'LIBRARY_0'},
        {'id': 'EXERCISE_1', 'libraryDefinitionId': 'LIBRARY_1'}], 'workouts': []}}
    units = {'LIBRARY_0': {'own': 0}, 'LIBRARY_1': {'own': 1}}
    finding = {'path': '/draft/exercises/0', 'evidencePaths': ['/history/LIBRARY_0'],
        'message': 'Movement zero needs attention.'}
    # The other batch saw it as comparison context; its own batch still completed.
    receipts = plan_review._evidence_receipts(context, units,
        {'evidence_0': [], 'evidence_1': [finding]},
        {'evidence_0': ['LIBRARY_0'], 'evidence_1': ['LIBRARY_1']}, {})
    assert receipts['LIBRARY_0']['findings'] == [finding]
    assert receipts['LIBRARY_1']['findings'] == []
    assert receipts['LIBRARY_0']['dependencies'] == {'LIBRARY_0': plan_review._hash(units['LIBRARY_0'])}
    reused = plan_review._evidence_receipts(context, units, {'evidence_1': [finding]},
        {'evidence_1': ['LIBRARY_1']}, {'LIBRARY_0': receipts['LIBRARY_0']})
    assert reused == receipts


def test_partial_review_resume_preserves_cached_scope_blocker_resolutions(monkeypatch):
    equipment, messages, _, edited, _, _ = case(monkeypatch)
    old_audit_calls = {call['id'] for message in messages for call in message.get('tool_calls', [])
                       if call.get('function', {}).get('name') == 'audit_workout_plan'}
    messages[:] = [message for message in messages
                   if message.get('tool_call_id') not in old_audit_calls
                   and not any(call.get('id') in old_audit_calls for call in message.get('tool_calls', []))]
    finding = {'severity': 'blocking', 'basis': 'established_violation', 'reviewScope': 'execution',
        'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0'],
        'message': 'An earlier evidence obligation.', 'repair': 'Resolve this obligation with the current snapshot.'}
    checklist = {'findings': {'OBLIGATION_CACHED': {'finding': finding, 'references': [],
        'changedDraftPaths': [], 'sourceCount': len(plan_review.requirement_sources(messages)),
        'sourceDraftId': edited.get('currentDraftId'), 'sourceFingerprint': 'prior-review'}},
        'changedDraftPaths': [], 'sourceCount': len(plan_review.requirement_sources(messages))}
    monkeypatch.setattr(plan_review, '_review_checklist', lambda *_: copy.deepcopy(checklist))
    resolution = {'OBLIGATION_CACHED': {'status': 'resolved_by_change', 'reason': 'Current evidence verifies the correction.',
        'evidencePaths': ['/draft/exercises/0']}}
    monkeypatch.setattr(plan_review, '_review_part', lambda _client, scope, *_args:
        {'findings': [], **({'blockerResolutions': copy.deepcopy(resolution),
                            'sourceImpact': 'changed_occurrences_only'} if scope == 'execution' else {})})

    checkpoints = []
    def interrupt_after_first_evidence(jobs, on_result=None):
        for key, function in jobs:
            if key == 'evidence_1':
                raise RuntimeError('simulated later-scope failure')
            value = function()
            if on_result:
                on_result(key, value)
    monkeypatch.setattr(plan_review, 'parallel_proposals', interrupt_after_first_evidence)
    partial = plan_review.review_draft(None, edited, messages, equipment, on_checkpoint=checkpoints.append)
    assert partial['review'].get('failure')
    assert checkpoints, 'No partial review checkpoint was saved.'
    saved_scope = checkpoints[-1]['review']['scopeResults'].get('execution')
    assert saved_scope is not None, list(checkpoints[-1]['review']['scopeResults'])
    assert saved_scope['blockerResolutions'] == resolution
    assert saved_scope['sourceImpact'] == 'changed_occurrences_only'

    store(messages, checkpoints[-1])
    resumed_jobs = []
    def complete_remaining(jobs, on_result=None):
        for key, function in jobs:
            resumed_jobs.append(key)
            value = function()
            if on_result:
                on_result(key, value)
        return {key: None for key, _ in jobs}
    monkeypatch.setattr(plan_review, 'parallel_proposals', complete_remaining)

    resumed = plan_review.review_draft(None, edited, messages, equipment)

    assert resumed['review']['scopeResults']['execution']['blockerResolutions'] == resolution
    assert resumed['review']['scopeResults']['execution']['sourceImpact'] == 'changed_occurrences_only'
    assert 'execution' not in resumed_jobs


def test_new_carried_claim_disables_only_its_evidence_unit_cache(monkeypatch):
    equipment, messages, first, edited, _, _ = case(monkeypatch)
    affected_reference, unaffected_reference = 'LIBRARY_1', 'LIBRARY_2'
    finding = {'severity': 'blocking', 'basis': 'established_violation', 'reviewScope': 'evidence',
        'path': '/draft/exercises/1', 'evidencePaths': ['/draft/exercises/1'],
        'message': 'New carried evidence claim.', 'repair': 'Check this movement against current evidence.'}
    checklist = {'findings': {'OBLIGATION_NEW': {'finding': finding, 'references': [affected_reference],
        'changedDraftPaths': [], 'sourceCount': len(plan_review.requirement_sources(messages)),
        'sourceDraftId': first.get('currentDraftId'), 'sourceFingerprint': 'new-claim'}},
        'changedDraftPaths': [], 'sourceCount': len(plan_review.requirement_sources(messages))}
    monkeypatch.setattr(plan_review, '_review_checklist', lambda *_: copy.deepcopy(checklist))
    dispatched = {}

    def review_part(_client, scope, part, *_args):
        if scope == 'execution':
            return {'findings': [], 'sourceImpact': 'changed_occurrences_only'}
        definitions = {item['id']: item.get('libraryDefinitionId')
                       for item in part['draft']['exercises'] if not item.get('detailsOmitted')}
        dispatched[scope] = {'references': set(definitions.values()),
            'obligations': set(part.get('previousBlockingFindings', {}))}
        return {'findings': []}

    monkeypatch.setattr(plan_review, '_review_part', review_part)
    def run_serially(jobs, on_result=None):
        for key, function in jobs:
            value = function()
            if on_result:
                on_result(key, value)
        return {key: None for key, _ in jobs}
    monkeypatch.setattr(plan_review, 'parallel_proposals', run_serially)

    result = plan_review.review_draft(None, edited, messages, equipment)

    affected_scope = next(scope for scope, value in dispatched.items() if affected_reference in value['references'])
    assert 'OBLIGATION_NEW' in dispatched[affected_scope]['obligations']
    assert all(unaffected_reference not in value['references'] for value in dispatched.values())
    assert affected_reference in result['review']['editScope']['reviewedEvidenceUnits']
    assert unaffected_reference in result['review']['editScope']['reusedEvidenceUnits']



def test_evidence_request_resolves_named_sessions_without_title_cache_invalidation(monkeypatch):
    equipment, messages, first, _, _, _ = case(monkeypatch)
    boundary = first['review']['instructionBoundary']
    context = plan_review._context(first, messages, equipment, None, boundary)
    part = plan_review._evidence_review_context(context, ['EXERCISE_0'])
    before = plan_review._hash(part)
    context['draft']['workouts'][0]['name'] = 'Full Body B'
    renamed = plan_review._evidence_review_context(context, ['EXERCISE_0'])
    assert plan_review._hash(renamed) == before
    calls = []
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        calls.append(payload)
        assert payload['workoutNames'] == {'WORKOUT_0': 'Full Body B'}
        assert payload['draft']['workouts'][0]['id'] == 'WORKOUT_0'
        assert 'request about one session does not apply' in request[0]['content']
        return json.dumps({'findings': []}), None, None
    monkeypatch.setattr(plan_review, 'chat_call', respond)
    assert not plan_review._review_part(None, 'evidence', renamed, context, first, messages, boundary, None)['findings']
    assert len(calls) == 1
