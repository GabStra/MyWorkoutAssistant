import copy
import json
import pytest
from jsonschema import ValidationError

from workout_generator_pkg import interactive_shell as shell
from workout_generator_pkg.planning_tools import requirements_approved, audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages
from workout_generator_pkg.planner_context import request_repair_task


def _tool(messages, name, arguments, payload, key):
    messages.extend([{'role': 'assistant', 'reasoning_content': 'old-reasoning-' + key,
        'tool_calls': [{'id': key, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(payload)}])


def _state(outgoing):
    snapshot = next(m['content'] for m in outgoing if m.get('content', '').startswith('Current planning state'))
    return json.loads(snapshot.split('\n', 1)[1])


def test_new_selected_evidence_is_reaudited_before_another_planner_response():
    from workout_generator_pkg.planner_context import pending_reaudit
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    failure = {'passed': False, 'errors': [{'code': 'training_evidence_required', 'definition_ids': ['LIBRARY_0']}],
               'submittedDraft': draft, 'planIndex': {'unneeded': 'duplicate'}, 'preview': 'not approved'}
    _tool(messages, 'audit_workout_plan', draft, failure, 'missing')
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0']}, {
        'libraryFingerprint': library_fingerprint(equipment), 'exercises': [
            {'reference': 'LIBRARY_0', 'sessions': [], 'relatedHistoryStatus': 'checked'}]}, 'history')
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending_reaudit(state, 'Create my plan') == {
        'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': []}
    assert not {'submittedDraft', 'planIndex', 'preview'} & state['lastAudit'].keys()
    assert messages == before
    _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': []},
          {**failure, 'errors': [{'code': 'volume_below_target'}]}, 'refreshed')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending_reaudit(state, 'Explain the plan') is None
    messages.append({'role': 'user', 'content': 'Explain the plan'})
    assert pending_reaudit(_state(shell._messages_for_api(messages, True, provided_equipment=equipment)), 'Explain the plan') is None


@pytest.mark.parametrize('pending_clarification', [False, True])
def test_planning_choices_are_only_enabled_for_new_user_instructions_or_pending_authorization(pending_clarification):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    error = {'code': 'independent_review_finding', 'action': 'clarify' if pending_clarification else 'repair'}
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'errors': [error]}, 'audit')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['planningDecisionNeeded'] is pending_clarification
    _tool(messages, 'record_planning_decisions', {}, {'passed': False, 'errors': [
        {'code': 'planning_decision_not_needed', 'repair': 'Use a draft patch.'}]}, 'unneeded')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['planningDecisionNeeded'] is pending_clarification
    messages.append({'role': 'user', 'content': 'Choose the convention for me.'})
    assert _state(shell._messages_for_api(messages, True, provided_equipment=equipment))['planningDecisionNeeded']


def test_construction_is_bounded_and_does_not_treat_partial_weekly_totals_as_repairs():
    from workout_generator_pkg.planning_tools import set_workout_requirements, construction_workout_tool, validate_construction_submission
    from workout_generator_pkg.planner_context import planner_response_profile
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Three sessions, 5-6 chest sets each; 15-18 weekly.'}], equipment)
    messages = requirement_messages(stored)
    draft['requirementsId'] = stored['requirementsId']
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['constructionTask']['action'] == 'create_first_session'
    tool = construction_workout_tool(state['constructionTask'])
    assert tool['function']['parameters']['properties']['workouts']['maxItems'] == 1
    with pytest.raises(ValueError, match='one workout'):
        validate_construction_submission({**draft, 'workouts': draft['workouts'] * 3}, state['constructionTask'])
    for index in range(3):
        if index == 0:
            arguments = draft
        else:
            assert state['constructionTask']['action'] == 'append_session'
            assert not state.get('repairTask')
            assert planner_response_profile(state) == {'reasoning_effort': 'low', 'activity': 'Drafting session'}
            arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': f'REVISION_{index-1}', 'patch': [
                {'op': 'add', 'path': '/workouts/-', 'value': {**copy.deepcopy(draft['workouts'][0]), 'name': f'Day {index + 1}'}}]}
            with pytest.raises(ValueError, match='one workout'):
                validate_construction_submission({**arguments, 'patch': [
                    {'op': 'replace', 'path': '/workouts/0/name', 'value': 'Unrequested rewrite'}]}, state['constructionTask'])
        validate_construction_submission(arguments, state['constructionTask'])
        result = audit_workout_plan(arguments, equipment, messages)
        _tool(messages, 'audit_workout_plan', arguments, result, f'day-{index}')
        state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
        assert len(state['currentDraft']['workouts']) == index + 1
        assert result['passed'] is (index == 2)
        if index == 0:
            append = {'op': 'add', 'path': '/workouts/-', 'value': copy.deepcopy(draft['workouts'][0])}
            rejected = {'requirementsId': stored['requirementsId'], 'baseDraftId': state['currentDraftId'], 'patch': [append, append]}
            from workout_generator_pkg.planning_tools import planning_tool_failure
            with pytest.raises(ValueError) as error:
                validate_construction_submission(rejected, state['constructionTask'])
            failure = planning_tool_failure('audit_workout_plan', error.value, rejected)
            assert failure['errors'][0]['code'] == 'construction_scope_exceeded' and 'audit' not in failure
            _tool(messages, 'audit_workout_plan', rejected, failure, 'rejected-append')
            state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
            assert state['constructionTask']['action'] == 'append_session'
            assert state['currentDraftId'] == 'REVISION_0' and state['currentDraftAudited']
            assert not state.get('repairTask')
    assert not state.get('constructionTask') and len(result['planIndex']['exercises']) == 3


def test_snapshot_keeps_current_draft_and_instructions_without_completed_tool_exchanges():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    for i in range(12):
        old = copy.deepcopy(draft)
        old['name'] = f'Obsolete draft {i}'
        _tool(messages, 'audit_workout_plan', old, {'passed': False, 'errors': [{'message': 'obsolete-error'}]}, f'old-{i}')
    messages.append({'role': 'assistant', 'content': 'Do you want to preserve the original rest limit?'})
    messages.append({'role': 'user', 'content': 'Yes. Keep it, and do not substitute the barbell movement.'})
    result = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, result, 'current')
    before = copy.deepcopy(messages)
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    state = _state(outgoing)
    assert state['currentDraft'] == draft and state['lastAudit']['passed']
    sources = list(state['sourceMessages'].values())
    assert sources[-1]['content'] == messages[-3]['content']
    assert sources[-2] == {'role': 'assistant', 'content': 'Do you want to preserve the original rest limit?'}
    assert state['requirementsApproved'] and requirements_approved(messages)
    assert 'Obsolete draft' not in json.dumps(outgoing) and 'obsolete-error' not in json.dumps(outgoing)
    tool_calls = [c for m in outgoing for c in m.get('tool_calls', [])]
    assert tool_calls == []
    assert not any(m['role'] == 'tool' or m.get('reasoning_content') for m in outgoing)
    assert messages == before


def test_snapshot_preserves_literal_confirmation_and_does_not_invent_approval():
    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)[:-1]
    pending = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending['requirementsApproved'] is False
    messages.append({'role': 'user', 'content': 'CONFIRM REQUIREMENTS'})
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    assert _state(outgoing)['requirementsApproved'] is True
    assert any(m['role'] == 'user' and m['content'] == 'CONFIRM REQUIREMENTS' for m in outgoing)


@pytest.mark.parametrize('approved', [False, True])
def test_rejected_requirement_arguments_survive_compaction_and_skipped_calls(approved):
    from workout_generator_pkg.planning_tools import set_workout_requirements, planning_tool_failure
    equipment, arguments, stored, _ = planning_case()
    messages = requirement_messages(stored)
    if not approved:
        messages.pop()
    messages.append({'role': 'user', 'content': 'Keep each requested muscle region separate.'})
    original = copy.deepcopy(messages)
    before = shell._messages_for_api(messages, True, provided_equipment=equipment)
    invalid = copy.deepcopy(arguments)
    invalid['auditTargets']['weeklyEffectiveSets']['inventedMuscle'] = {'minimum': 15, 'maximum': 18}
    with pytest.raises(ValidationError) as failure:
        set_workout_requirements(invalid, messages, equipment)
    payload = planning_tool_failure('set_workout_requirements', failure.value, invalid)
    _tool(messages, 'set_workout_requirements', invalid, payload, 'rejected')
    _tool(messages, 'set_workout_requirements', arguments, {'skipped': True, 'passed': False}, 'skipped')
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    state = _state(outgoing)
    feedback = state['otherToolResults']['set_workout_requirements'] if approved else state['requirementsFeedback']
    assert feedback['errors'] == payload['errors']
    assert feedback['errors'][0]['code'] == 'invalid_arguments'
    assert 'inventedMuscle' in feedback['errors'][0]['message']
    assert state['requirements'] == stored['requirements'] and outgoing != before
    assert messages[:len(original)] == original


def test_reapproved_requirements_keep_old_audit_as_stale_and_request_a_saved_draft_reaudit():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    approved = json.loads(next(m['content'] for m in messages if m.get('tool_call_id') == 'requirements'))
    result = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, result, 'old-audit')
    _tool(messages, 'set_workout_requirements', {}, approved, 'refresh')
    messages.extend([{'role': 'assistant', 'content': stored['requirementsPreview'], 'canonicalRequirementsPreview': stored['requirementsId']},
                     {'role': 'user', 'content': 'CONFIRM REQUIREMENTS'}])
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['requirementsApproved'] and state['lastAuditStale']
    assert state['lastAudit']['draftId'] == result['draftId']
    assert state['savedDraftReaudit'] == {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': []}
    assert 'repairTask' not in state and messages == before


@pytest.mark.parametrize('execution_failed', [False, True])
def test_stale_review_or_explicit_review_retry_can_reaudit_without_broad_planning(execution_failed):
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    result['review'] = {'version': REVIEW_VERSION if execution_failed else REVIEW_VERSION-1, 'findings': []}
    if execution_failed:
        result['passed'] = False
        result['errors'] = [{'code': 'review_execution_failed', 'message': 'Temporary reviewer error.'}]
    _tool(messages, 'audit_workout_plan', draft, result, 'audit')
    messages.append({'role': 'user', 'content': '/continue'})
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['savedDraftReaudit']['patch'] == [] and 'repairTask' not in state


def test_requirements_refresh_omits_workout_data_until_approval_without_deleting_it():
    from workout_generator_pkg.planning_tools import library_fingerprint, _latest_result
    equipment, _, stored, draft = planning_case()
    draft['name'] = 'SAVED-DRAFT-ONLY'
    messages = requirement_messages(stored)[:-1]
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'errors': [
        {'code': 'volume_below_target', 'path': '/workouts/0/exercises'}]}, 'draft')
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0']}, {
        'libraryFingerprint': library_fingerprint(equipment),
        'exercises': [{'reference': 'LIBRARY_0', 'records': ['SAVED-HISTORY-ONLY']}]}, 'history')
    before = copy.deepcopy(messages)
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    pending = _state(outgoing)
    assert not pending['requirementsApproved'] and pending['savedDraftAvailable']
    assert pending['requirements'] == stored['requirements'] and pending['sourceMessages']['SOURCE_0']['content'] == messages[0]['content']
    assert not {'currentDraft', 'lastAudit', 'trainingEvidence', 'exerciseCandidates'} & pending.keys()
    assert 'SAVED-DRAFT-ONLY' not in json.dumps(outgoing) and 'SAVED-HISTORY-ONLY' not in json.dumps(outgoing)
    assert messages == before
    messages.append({'role': 'user', 'content': 'CONFIRM REQUIREMENTS'})
    resumed = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert resumed['requirementsApproved'] and resumed['currentDraft'] == draft
    assert resumed['trainingEvidenceSummary']['LIBRARY_0'] == {}
    _tool(messages, 'audit_workout_plan', {}, {'passed': False, 'skipped': True, 'tool': 'audit_workout_plan'}, 'skipped')
    assert _latest_result(messages, 'audit_workout_plan')[1]['errors'][0]['code'] == 'volume_below_target'
    assert _state(shell._messages_for_api(messages, True, provided_equipment=equipment))['lastAudit']['errors'][0]['code'] == 'volume_below_target'


def test_planner_and_reviewer_share_ordered_sources_across_multiple_clarifications():
    from workout_generator_pkg.plan_review import _context
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    clarification = [
        {'role': 'assistant', 'content': 'One movement excluded, or the whole family?'},
        {'role': 'user', 'content': 'Only that movement.'},
        {'role': 'assistant', 'content': 'Which of the remaining options do you prefer?'},
        {'role': 'user', 'content': 'Choose what makes sense.'}]
    messages.extend(clarification)
    result = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, result, 'latest')
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    context = _context(result, messages, equipment, None, len(messages) - 3)
    assert state['sourceMessages'] == context['sourceMessages']
    assert list(state['sourceMessages'].values())[-4:] == clarification
    assert not {'userInstructions', 'clarificationContext', 'lastAssistantMessage'} & state.keys()
    assert 'CONFIRM REQUIREMENTS' not in json.dumps(state['sourceMessages'])
    assert messages == before


def test_snapshot_deduplicates_candidates_and_discards_stale_catalog_entries():
    from workout_generator_pkg.exercise_library_tools import _selection_entry
    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    entry = _selection_entry(equipment['exerciseDefinitions'][0], {}, 'LIBRARY_0')
    for i in range(2):
        _tool(messages, 'search_exercise_library', {'queries': ['press']},
              {'libraryFingerprint': 'search-fingerprint', 'results': [{'query': 'press', 'exercises': [entry]}]}, f'search-{i}')
    messages.append({'role': 'user', 'content': 'Use those candidates.'})
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert list(state['exerciseCandidates']) == ['LIBRARY_0']
    changed = copy.deepcopy(equipment)
    changed['exerciseDefinitions'][0]['name'] = 'Different movement'
    stale = _state(shell._messages_for_api(messages, True, provided_equipment=changed))
    assert stale['exerciseCandidates'] == {} and stale['staleLibraryResults']


def test_snapshot_keeps_failures_and_full_original_user_constraints():
    equipment, _, stored, draft = planning_case()
    messages = [{'role': 'user', 'content': 'Allow non-competing supersets. Exclude only the conventional variation.'}] + requirement_messages(stored)
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'errors': [{'code': 'review_execution_failed',
        'message': 'Malformed reviewer output', 'repair': 'Do not retry unchanged.'}]}, 'failed')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert messages[0]['content'] == state['sourceMessages']['SOURCE_0']['content']
    assert state['lastAudit']['errors'][0]['repair'] == 'Do not retry unchanged.'


def test_without_recorded_requirements_the_initial_dialogue_is_retained():
    messages = [{'role': 'system', 'content': 'System'}, {'role': 'user', 'content': 'Help define my requirements'},
                {'role': 'assistant', 'content': 'Which equipment?'}, {'role': 'user', 'content': 'Barbell only'}]
    outgoing = shell._messages_for_api(messages, True)
    assert outgoing[:len(messages)] == messages


def test_snapshot_preserves_fresh_evidence_and_lookup_failures():
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    evidence = {'reference': 'LIBRARY_0', 'records': ['retained history']}
    for key, payload in [('stale', {'staleHistory': True}),
                         ('fresh', {'libraryFingerprint': library_fingerprint(equipment), 'exercises': [evidence]}),
                         ('failure', {'errors': ['Lookup failed; retry requested reference']})]:
        _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0']}, payload, key)
    messages.append({'role': 'user', 'content': 'Repair this draft.'})
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['trainingEvidence'] == {'LIBRARY_0': evidence}
    assert state['staleHistory'] == []
    assert state['otherToolResults']['get_training_evidence']['errors']


def test_snapshot_preserves_latest_invalid_draft_for_repair():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    draft.pop('requirementsId')
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'errors': ['Missing requirementsId']}, 'invalid')
    messages.append({'role': 'user', 'content': 'Fix the missing field.'})
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['currentDraft'] == draft
    assert state['lastAudit']['errors'] == ['Missing requirementsId']


def test_latest_history_payload_is_sent_once_and_related_records_are_deduplicated():
    equipment, _, stored, _ = planning_case()
    from workout_generator_pkg.planning_tools import library_fingerprint
    messages = requirement_messages(stored)
    related = {'reference': 'LIBRARY_99', 'definitionId': 'related',
               'sessions': [{'performances': [{'record': {'loadKg': 81, 'actualReps': 7, 'autoRegulationRIR': 2, 'setHistoryId': 'private-id'}}]}]}
    roots = [{'reference': 'LIBRARY_0', 'relatedMovementHistory': [{**related, 'differences': {'name': 'first comparison'}}]},
             {'reference': 'LIBRARY_1', 'relatedMovementHistory': [{**related, 'differences': {'name': 'second comparison'}}]}]
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0', 'LIBRARY_1']},
          {'libraryFingerprint': library_fingerprint(equipment), 'exercises': roots}, 'latest-history')
    before = copy.deepcopy(messages)
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    state = _state(outgoing)
    assert state['trainingEvidence']['LIBRARY_99']['sessions'][0]['performances'][0]['record'] == {
        'loadKg': 81, 'actualReps': 7, 'autoRegulationRIR': 2}
    assert state['trainingEvidence']['LIBRARY_0']['relatedMovementHistory'] == [
        {'reference': 'LIBRARY_99', 'differences': {'name': 'first comparison'}}]
    assert state['trainingEvidence']['LIBRARY_1']['relatedMovementHistory'][0]['differences']['name'] == 'second comparison'
    assert json.dumps(outgoing).count('autoRegulationRIR') == 1
    assert not any(m['role'] == 'tool' for m in outgoing)
    assert messages == before


def test_latest_submitted_draft_is_not_repeated_in_tool_arguments():
    equipment, _, stored, draft = planning_case()
    draft['name'] = 'UNIQUE-CURRENT-DRAFT'
    messages = requirement_messages(stored)
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'errors': [{'message': 'UNIQUE-FAILURE'}]}, 'latest')
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    assert _state(outgoing)['currentDraft'] == draft
    assert json.dumps(outgoing).count('UNIQUE-CURRENT-DRAFT') == 1
    assert json.dumps(outgoing).count('UNIQUE-FAILURE') == 1


def test_resumed_evidence_keeps_latest_session_but_fresh_requested_pages_remain_complete():
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    sessions = [{'date': f'2026-10-0{day}', 'sessionId': f'session-{day}', 'performances': [
        {'exerciseId': 'private-occurrence', 'order': 2, 'prescribedRestSeconds': [90],
         'record': {'actualReps': day, 'autoRegulationRIR': 2}}]} for day in (3, 2, 1)]
    item = {'reference': 'LIBRARY_0', 'totalSessions': 8, 'hasMore': True, 'nextOffset': 3, 'sessions': sessions,
            'relatedMovementHistory': [{'reference': 'LIBRARY_99', 'sessions': sessions}]}
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0'], 'session_limit': 3},
          {'libraryFingerprint': library_fingerprint(equipment), 'exercises': [item]}, 'paged-history')
    before = copy.deepcopy(messages)
    fresh = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert len(fresh['trainingEvidence']['LIBRARY_0']['sessions']) == 3
    messages.append({'role': 'user', 'content': 'Resume the saved repair.'})
    resumed = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    evidence = resumed['trainingEvidence']['LIBRARY_0']
    assert len(evidence['sessions']) == 1 and evidence['sessions'][0]['date'] == '2026-10-03'
    assert evidence['earlierReturnedSessionsOmitted'] == 2
    assert evidence['hasMore'] and evidence['nextOffset'] == 1 and evidence['totalSessions'] == 8
    assert len(resumed['trainingEvidence']['LIBRARY_99']['sessions']) == 1
    performance = evidence['sessions'][0]['performances'][0]
    assert performance['order'] == 2 and performance['prescribedRestSeconds'] == [90]
    assert performance['record'] == {'actualReps': 3, 'autoRegulationRIR': 2}
    assert 'exerciseId' not in performance and 'sessionId' not in evidence['sessions'][0]
    assert messages[:-1] == before


def test_draft_snapshot_focuses_candidates_and_history_but_keeps_a_cached_alternative_index():
    from workout_generator_pkg.exercise_library_tools import _selection_entry
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, draft = planning_case()
    base = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [{**base, 'id': f'd{i}', 'name': f'Movement {i}'} for i in range(3)]
    entries = [_selection_entry(d, {}, f'LIBRARY_{i}') for i, d in enumerate(equipment['exerciseDefinitions'])]
    messages = requirement_messages(stored)
    _tool(messages, 'search_exercise_library', {'queries': ['push']},
          {'results': [{'query': 'push', 'exercises': entries}]}, 'discovery')
    evidence = [{'reference': f'LIBRARY_{i}', 'sessions': [{'performances': [{'record': {
        'actualReps': 10, 'note': f'HISTORY-MARKER-{i}'}}]}]} for i in range(3)]
    _tool(messages, 'get_training_evidence', {'definition_ids': [f'LIBRARY_{i}' for i in range(3)]},
          {'libraryFingerprint': library_fingerprint(equipment), 'exercises': evidence}, 'history')
    result = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, result, 'draft')
    messages[-2]['content'] = 'Old idea: search for a quad-only movement?'
    messages.append({'role': 'user', 'content': 'Repair the current draft using the audit.'})
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert set(state['exerciseCandidates']) == {'LIBRARY_0'}
    assert set(state['cachedCandidateIndex']) == {'LIBRARY_1', 'LIBRARY_2'}
    assert set(state['trainingEvidence']) == {'LIBRARY_0'}
    assert 'lastAssistantMessage' not in state and 'HISTORY-MARKER-1' not in json.dumps(state)
    assert state['cachedCandidateIndex']['LIBRARY_2']['creditsPerWorkingSet']
    assert messages == before
    _tool(messages, 'search_exercise_library', {'queries': ['Movement 2']},
          {'results': [{'query': 'Movement 2', 'exercises': [entries[2]]}]}, 'targeted')
    active = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert set(active['exerciseCandidates']) == {'LIBRARY_0', 'LIBRARY_2'}
    assert set(active['trainingEvidence']) == {'LIBRARY_0', 'LIBRARY_2'}


def test_old_search_coefficients_are_refreshed_using_current_audit_policy():
    from workout_generator_pkg.exercise_library_tools import _selection_entry
    equipment, _, stored, _ = planning_case()
    definition = equipment['exerciseDefinitions'][0]
    definition.update(exerciseType='COUNTDOWN', muscleGroups=['FRONT_QUADRICEPS'])
    old = _selection_entry(definition, {}, 'LIBRARY_0')
    old['creditsPerWorkingSet'] = {'quads': {'direct': 1, 'indirect': 0}}
    messages = requirement_messages(stored)
    _tool(messages, 'search_exercise_library', {'queries': ['Wall Sit']},
          {'results': [{'query': 'Wall Sit', 'exercises': [old]}]}, 'old-search')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['exerciseCandidates']['LIBRARY_0']['creditsPerWorkingSet'] == {}
    assert state['exerciseCandidates']['LIBRARY_0']['volumeAuditNote']


def test_failed_draft_uses_focused_evidence_and_keeps_all_constraints_and_saved_records():
    from workout_generator_pkg.exercise_library_tools import _selection_entry
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, draft = planning_case()
    base = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [{**base, 'id': f'd{i}', 'name': f'Movement {i}'} for i in range(3)]
    second = copy.deepcopy(draft['workouts'][0])
    second['exercises'][0]['definition_id'] = 'LIBRARY_1'
    draft['workouts'].append(second)
    messages = requirement_messages(stored)
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'errors': [
        {'code': 'prescription_error', 'draftPath': '/workouts/0/exercises/0/targetSetPrescriptions', 'repair': 'Repair this prescription.'},
        {'code': 'duration_exceeded', 'path': '/workouts/1', 'repair': 'Preserve the duration cap.'}],
        'instruction': 'Repair everything together.'}, 'failed')
    entries = [_selection_entry(d, {}, f'LIBRARY_{i}') for i, d in enumerate(equipment['exerciseDefinitions'])]
    _tool(messages, 'search_exercise_library', {'queries': ['alternative']},
          {'results': [{'query': 'alternative', 'exercises': entries}]}, 'alternatives')
    evidence = [{'reference': f'LIBRARY_{i}', 'status': 'comparable_records', 'sessions': [
        {'performances': [{'record': {'actualReps': 10, 'note': f'SAVED-DETAILS-{i}'}}]}]} for i in range(3)]
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0', 'LIBRARY_1', 'LIBRARY_2']},
          {'libraryFingerprint': library_fingerprint(equipment), 'exercises': evidence}, 'old-history')
    messages.append({'role': 'user', 'content': 'Resume the repair, preserving every constraint.'})
    before = copy.deepcopy(messages)
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    state = _state(outgoing)
    assert request_repair_task(outgoing) == state['repairTask']
    assert state['repairTask']['findingIndex'] == 0 and state['repairTask']['baseDraftId'] == 'REVISION_0'
    assert len(state['lastAudit']['errors']) == 2 and state['currentDraft'] == draft
    assert state['requirements'] == stored['requirements'] and state['sourceMessages']['SOURCE_1']['content'] == messages[-1]['content']
    assert set(state['exerciseCandidates']) == {'LIBRARY_0', 'LIBRARY_1'}
    assert set(state['cachedCandidateIndex']) == {'LIBRARY_2'}
    assert set(state['trainingEvidence']) == {'LIBRARY_0'}
    assert state['trainingEvidenceSummary']['LIBRARY_1']['status'] == 'comparable_records'
    assert 'SAVED-DETAILS-1' not in json.dumps(outgoing) and 'SAVED-DETAILS-2' not in json.dumps(outgoing)
    assert messages == before
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_2']},
          {'libraryFingerprint': library_fingerprint(equipment), 'exercises': [evidence[2]]}, 'requested-detail')
    requested = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert 'SAVED-DETAILS-2' in json.dumps(requested['trainingEvidence']['LIBRARY_2'])
    assert 'LIBRARY_2' in requested['exerciseCandidates']


@pytest.mark.parametrize('approved, passed, code', [
    (False, False, 'volume_below_target'), (True, True, 'volume_below_target'),
    (True, False, 'review_execution_failed'),
])
def test_repair_mode_does_not_replace_approval_success_or_execution_failure_handling(approved, passed, code):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    if not approved:
        messages.pop()
    _tool(messages, 'audit_workout_plan', draft, {'passed': passed, 'errors': [{'code': code}]}, 'audit')
    assert request_repair_task(shell._messages_for_api(messages, True, provided_equipment=equipment)) is None
