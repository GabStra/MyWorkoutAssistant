import copy
import json
import pytest
from jsonschema import ValidationError

from workout_generator_pkg import interactive_shell as shell
from workout_generator_pkg.plan_review import REVIEW_VERSION
from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION
from workout_generator_pkg.planning_tools import requirements_approved, audit_workout_plan, library_fingerprint, AUDIT_VERSION
from test_workout_generator_planning_tools import planning_case, requirement_messages
from workout_generator_pkg.planner_context import (request_repair_task, _movement_selection_context,
    _available_alternative_replacements,
    focus_alternative_repair_request)


def _tool(messages, name, arguments, payload, key):
    messages.extend([{'role': 'assistant', 'reasoning_content': 'old-reasoning-' + key,
        'tool_calls': [{'id': key, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(payload)}])


def _state(outgoing):
    snapshot = next(m['content'] for m in outgoing if m.get('content', '').startswith('Current planning state'))
    return json.loads(snapshot.split('\n', 1)[1])


def _draft_with_references(draft):
    result = copy.deepcopy(draft)
    occurrence = 0
    for workout_index, workout in enumerate(result['workouts']):
        workout['reference'] = f'WORKOUT_{workout_index}'
        for exercise in workout.get('exercises', []):
            exercise['reference'] = f'EXERCISE_{occurrence}'
            occurrence += 1
    return result


def _unresolved_joint_candidate(equipment, stored, draft, messages, base_draft_id=None):
    import hashlib
    from workout_generator_pkg.joint_planning import joint_problem_fingerprint, prescription_fingerprint
    from workout_generator_pkg.planning_tools import library_fingerprint, source_message_context, requirement_sources

    submission = copy.deepcopy(draft)
    submission['requirementsId'] = stored['requirementsId']
    source_hash = hashlib.sha256(json.dumps(source_message_context(requirement_sources(messages)),
        sort_keys=True).encode()).hexdigest()
    return {'requirementsId': stored['requirementsId'], 'baseDraftId': base_draft_id,
        'submission': submission, 'submissionHash': hashlib.sha256(json.dumps(submission, sort_keys=True).encode()).hexdigest(),
        'solvedPrescriptionHash': prescription_fingerprint(submission['workouts']),
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'sourceMessagesHash': source_hash,
        'jointPlanning': {'problemFingerprint': joint_problem_fingerprint(submission['workouts'],
            stored['requirements'], equipment, messages=messages, restriction_policy=stored.get('restrictionPolicy')),
            'feasible': False, 'status': 'unproven', 'instruction': 'Solver did not establish feasibility.'},
        'recipeQualification': {'contracts': [{'definition_id': 'LIBRARY_0'}], 'inputHashes': {}}}


def _unresolved_worker_result(equipment, stored, candidate):
    from workout_generator_pkg.planning_tools import library_fingerprint
    return {'requirementsId': stored['requirementsId'], 'preparationId': 'PREP_UNRESOLVED', 'baseDraftId': None,
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'jointUnresolvedCandidate': candidate, 'workerResults': {'0': {'name': 'Session A'}}, 'workerFailures': {},
        'passed': False, 'executionFailure': True}


def test_movement_selection_only_prefers_progression_when_approved():
    unapproved = {'requirements': {'objectiveOrder': []}}
    _movement_selection_context(unapproved)
    assert 'Do not prefer a movement' in unapproved['progressionSelectionPolicy']

    approved = {'requirements': {'objectiveOrder': ['progression']}}
    _movement_selection_context(approved)
    assert 'prefer the most supported progression margin' in approved['progressionSelectionPolicy']


def test_continue_hands_off_exact_unproven_joint_candidate_without_redrafting_workers():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    candidate = _unresolved_joint_candidate(equipment, stored, draft, messages)
    worker = _unresolved_worker_result(equipment, stored, candidate)
    _tool(messages, 'draft_workout_sessions', {'preparationId': 'PREP_UNRESOLVED'}, worker, 'unresolved')

    before_continue = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert not before_continue.get('unresolvedJointCandidate')

    messages.append({'role': 'user', 'content': '/continue'})
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['unresolvedJointCandidate'] == candidate
    assert not state.get('constructionTask')
    assert state['unresolvedJointCandidate']['submission'] == candidate['submission']
    assert state['unresolvedJointCandidate']['recipeQualification'] == candidate['recipeQualification']
    assert state['unresolvedJointCandidate']['jointPlanning']['status'] == 'unproven'

    stale = copy.deepcopy(candidate)
    stale['libraryFingerprint'] = 'old-library'
    _tool(messages, 'draft_workout_sessions', {'preparationId': 'PREP_STALE'},
          _unresolved_worker_result(equipment, stored, stale), 'stale-unresolved')
    messages.append({'role': 'user', 'content': '/continue'})
    stale_state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert not stale_state.get('unresolvedJointCandidate')


def test_unresolved_candidate_reaudit_reuses_qualification_and_only_retries_joint_solve(monkeypatch):
    from types import SimpleNamespace
    from workout_generator_pkg import joint_planning

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    candidate = _unresolved_joint_candidate(equipment, stored, draft, messages)
    _tool(messages, 'draft_workout_sessions', {'preparationId': 'PREP_UNRESOLVED'},
          _unresolved_worker_result(equipment, stored, candidate), 'unresolved')
    messages.append({'role': 'user', 'content': '/continue'})
    joint_calls = []

    def audit(arguments, *args, **kwargs):
        return {'passed': True, 'requirementsId': stored['requirementsId'], 'currentDraftId': 'REVISION_0',
            'submittedDraft': copy.deepcopy(arguments), 'historyFingerprint': None, 'errors': []}

    def solve(*args, **kwargs):
        joint_calls.append((args, kwargs))
        return {'feasible': False, 'status': 'unproven', 'problemFingerprint': candidate['jointPlanning']['problemFingerprint'],
            'instruction': 'Solver remains unproven.'}

    monkeypatch.setattr(shell, 'audit_workout_plan', audit)
    monkeypatch.setattr(shell, 'review_draft', lambda client, result, *args, **kwargs: result)
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    monkeypatch.setattr(shell, 'auto_allocate_workout', lambda result, *args, **kwargs: result)
    result = json.loads(shell.handle_function_call(None, messages, 'audit_workout_plan', candidate['submission'], equipment,
        deps=SimpleNamespace(execute_workout_generation=None))['result'])
    assert len(joint_calls) == 1
    assert result['jointUnresolvedCandidate']['recipeQualification'] == candidate['recipeQualification']
    assert result['jointUnresolvedCandidate']['baseDraftId'] == 'REVISION_0'
    assert result['jointUnresolvedCandidate']['jointPlanning']['status'] == 'unproven'
    assert not result.get('jointPlanningStopped')
    assert not result['passed'] and 'preview' not in result
    _tool(messages, 'audit_workout_plan', candidate['submission'], result, 'audit-unresolved')
    messages.append({'role': 'user', 'content': '/continue'})
    resumed = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert resumed['unresolvedJointCandidate']['submission'] == candidate['submission']
    assert not resumed.get('constructionTask')


def test_unresolved_candidate_reaudit_rejects_changed_load_guess_mode(monkeypatch):
    from types import SimpleNamespace
    from workout_generator_pkg import joint_planning

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    candidate = _unresolved_joint_candidate(equipment, stored, draft, messages)
    _tool(messages, 'draft_workout_sessions', {'preparationId': 'PREP_UNRESOLVED'},
          _unresolved_worker_result(equipment, stored, candidate), 'unresolved')
    messages.append({'role': 'user', 'content': '/continue'})
    joint_calls = []
    monkeypatch.setattr(shell, 'audit_workout_plan', lambda arguments, *args, **kwargs: {
        'passed': True, 'requirementsId': stored['requirementsId'], 'currentDraftId': 'REVISION_0',
        'submittedDraft': copy.deepcopy(arguments), 'historyFingerprint': None, 'errors': []})
    monkeypatch.setattr(shell, 'review_draft', lambda client, result, *args, **kwargs: result)
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', lambda *args, **kwargs: joint_calls.append(args))
    monkeypatch.setattr(shell, 'auto_allocate_workout', lambda result, *args, **kwargs: result)
    result = json.loads(shell.handle_function_call(None, messages, 'audit_workout_plan', candidate['submission'], equipment,
        deps=SimpleNamespace(execute_workout_generation=None), allow_educated_load_guesses=False)['result'])
    assert not joint_calls
    assert 'jointUnresolvedCandidate' not in result


def _history_bound_run(history_fingerprint):
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    library = library_fingerprint(equipment)
    errors = [{'code': 'training_load_suitability_unresolved', 'path': '/workouts/0/exercises/0',
               'message': 'Historical Nordic +10 kg evidence conflicts with this prescription.'}]
    audit = {'passed': False, 'requirementsId': stored['requirementsId'], 'currentDraftId': 'DRAFT_1',
        'historyFingerprint': history_fingerprint, 'libraryFingerprint': library,
        'submittedDraft': copy.deepcopy(draft), 'planningOutcome': 'needs_repair', 'errors': errors,
        'reviewFindings': [{'message': 'History based finding'}], 'instruction': 'Repair based on the old evidence.'}
    _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId']}, audit, 'old_audit')
    worker = {'passed': False, 'requirementsId': stored['requirementsId'], 'preparationId': 'PREP_1',
        'baseDraftId': 'DRAFT_1', 'historyFingerprint': history_fingerprint, 'draftingVersion': 3,
        'workerResults': {'0': {'name': 'Session A'}},
        'workerFailures': {'1': {'message': 'old failure', 'errors': errors, 'proposal': draft}},
        'errors': [{'code': 'worker_validation_failed', 'message': 'old Nordic cap warning', 'errors': errors}],
        'instruction': 'Repair using old Nordic evidence.'}
    _tool(messages, 'draft_workout_sessions', {'preparationId': 'PREP_1'}, worker, 'old_workers')
    return equipment, stored, draft, messages


def test_stale_history_receipts_keep_candidate_but_remove_old_findings_and_verdicts():
    from types import SimpleNamespace
    from workout_generator_pkg.planner_context import request_planning_state

    equipment, stored, draft, messages = _history_bound_run('old-history')
    saved_messages = copy.deepcopy(messages)
    outgoing = shell._messages_for_api(messages, True, SimpleNamespace(fingerprint='filtered-history',
        context=lambda: {'historyFingerprint': 'filtered-history'}), equipment)
    state = request_planning_state(outgoing)
    serialized = json.dumps(state)

    assert state['requirementsApproved'] and state['requirementsId'] == stored['requirementsId']
    assert state['currentDraft']['workouts'][0]['exercises'][0]['definition_id'] == draft['workouts'][0]['exercises'][0]['definition_id']
    assert state['savedDraftReaudit']['baseDraftId'] == 'DRAFT_1'
    assert state['otherToolResults']['draft_workout_sessions']['staleHistory'] is True
    assert state['otherToolResults']['draft_workout_sessions']['savedWorkerResults'] == ['0']
    assert {item['tool'] for item in state['staleHistoryBoundReceipts']} == {
        'audit_workout_plan', 'draft_workout_sessions'}
    assert 'training_load_suitability_unresolved' not in serialized
    assert 'old Nordic cap warning' not in serialized
    assert 'needs_repair' not in serialized
    assert messages == saved_messages


def test_receipts_bound_to_current_history_keep_their_findings():
    from types import SimpleNamespace
    from workout_generator_pkg.planner_context import request_planning_state

    equipment, _, _, messages = _history_bound_run('current-history')
    state = request_planning_state(shell._messages_for_api(
        messages, True, SimpleNamespace(fingerprint='current-history',
            context=lambda: {'historyFingerprint': 'current-history'}), equipment))

    assert not state['staleHistoryBoundReceipts']
    assert state['otherToolResults']['draft_workout_sessions']['errors'][0]['code'] == 'worker_validation_failed'
    assert not state.get('savedDraftReaudit'), state.get('staleJointPlanningReceipt')


def test_stale_success_receipt_cannot_claim_verified_feasibility():
    from types import SimpleNamespace
    from workout_generator_pkg.planner_context import request_planning_state

    equipment, _, _, messages = _history_bound_run('old-history')
    tool_result = next(message for message in messages if message.get('tool_call_id') == 'old_audit')
    audit = json.loads(tool_result['content'])
    audit.update(passed=True, errors=[], planningOutcome='verified_feasible', instruction='Ready to generate.')
    tool_result['content'] = json.dumps(audit)
    state = request_planning_state(shell._messages_for_api(messages, True, SimpleNamespace(
        fingerprint='filtered-history', context=lambda: {'historyFingerprint': 'filtered-history'}), equipment))

    assert state['currentDraft'] and state['savedDraftReaudit']
    assert state['lastAudit'] is None
    assert 'verified_feasible' not in json.dumps(state)
    assert 'Ready to generate.' not in json.dumps(state)


def test_stale_joint_solver_fingerprint_queues_saved_draft_reaudit_before_task_projection():
    from types import SimpleNamespace

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audit = audit_workout_plan(draft, equipment, messages)
    audit['automaticAllocation'] = {
        'status': 'invalid_options', 'problemFingerprint': 'old-selection-policy-fingerprint',
        'application': 'automatic', 'preserveSourceSelection': True,
        'allowEducatedLoadGuesses': True,
        'sourcePositions': [[0, 4]],
    }
    _tool(messages, 'audit_workout_plan', draft, audit, 'stale_joint_receipt')

    history = SimpleNamespace(fingerprint=None, context=lambda: {})
    state = _state(shell._messages_for_api(messages, True, history, equipment))

    assert state['savedDraftReaudit'] == {
        'requirementsId': stored['requirementsId'], 'baseDraftId': audit['currentDraftId'], 'patch': []}
    assert state['staleJointPlanningReceipt']['sourceProblemFingerprint'] == 'old-selection-policy-fingerprint'
    assert state['staleJointPlanningReceipt']['currentProblemFingerprint'] != 'old-selection-policy-fingerprint'
    assert 'automaticAllocation' not in state['lastAudit']
    assert 'candidateMenuExpansionTask' not in state
    assert 'conflictDiagnosisTask' not in state


def test_current_joint_solver_receipt_preserves_explicit_disabled_load_guesses():
    from types import SimpleNamespace

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    history = SimpleNamespace(fingerprint=None, context=lambda: {})
    audit = audit_workout_plan(draft, equipment, messages)
    audit['passed'] = False
    audit['errors'] = [{'code': 'volume_below_target', 'message': 'Keep a concrete numeric blocker.'}]
    audit['allowEducatedLoadGuesses'] = False
    audit['automaticAllocation'] = {
        'status': 'infeasible', 'problemFingerprint': 'pending',
        'application': 'automatic', 'preserveSourceSelection': True,
        'allowEducatedLoadGuesses': False,
    }
    _tool(messages, 'audit_workout_plan', draft, audit, 'current_disabled_load_guesses')

    outgoing = shell._messages_for_api(messages, True, history, equipment)
    state = _state(outgoing)
    current_fingerprint = state['staleJointPlanningReceipt']['currentProblemFingerprint']
    assert current_fingerprint
    audit['automaticAllocation']['problemFingerprint'] = current_fingerprint
    next(message for message in messages if message.get('tool_call_id') == 'current_disabled_load_guesses')['content'] = json.dumps(audit)

    state = _state(shell._messages_for_api(messages, True, history, equipment))
    assert not state.get('savedDraftReaudit'), state.get('staleJointPlanningReceipt')
    assert not state.get('staleJointPlanningReceipt')
    assert state['lastAudit']['automaticAllocation']['allowEducatedLoadGuesses'] is False


def test_production_joint_receipt_round_trips_without_display_reference_staleness():
    from types import SimpleNamespace
    from workout_generator_pkg.allocation import auto_allocate_workout

    equipment, _, stored, draft = planning_case()
    stored['requirements']['auditTargets']['maximumSessionSeconds'] = 1
    messages = requirement_messages(stored)
    initial_audit = audit_workout_plan(draft, equipment, messages)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'initial_audit', 'type': 'function',
            'function': {'name': 'audit_workout_plan', 'arguments': json.dumps(draft)}}]},
        {'role': 'tool', 'tool_call_id': 'initial_audit', 'content': json.dumps(initial_audit)},
    ])

    production_audit = auto_allocate_workout(initial_audit, equipment, messages)
    assert production_audit['automaticAllocation']['status'] == 'infeasible'
    assert production_audit['submittedDraft'] == draft
    _tool(messages, 'audit_workout_plan', production_audit['submittedDraft'], production_audit,
        'production_joint_receipt')

    state = _state(shell._messages_for_api(messages, True,
        SimpleNamespace(fingerprint=None, context=lambda: {}), equipment))

    assert not state.get('savedDraftReaudit')
    assert not state.get('staleJointPlanningReceipt')
    assert state['lastAudit']['automaticAllocation']['problemFingerprint'] == production_audit[
        'automaticAllocation']['problemFingerprint']

    changed = copy.deepcopy(production_audit)
    changed['submittedDraft']['workouts'][0]['exercises'][0]['numWorkSets'] += 1
    _tool(messages, 'audit_workout_plan', changed['submittedDraft'], changed, 'changed_joint_candidate')
    changed_state = _state(shell._messages_for_api(messages, True,
        SimpleNamespace(fingerprint=None, context=lambda: {}), equipment))
    assert changed_state.get('savedDraftReaudit')
    assert changed_state['staleJointPlanningReceipt']['sourceProblemFingerprint'] == production_audit[
        'automaticAllocation']['problemFingerprint']


def test_current_repair_group_owns_exact_matching_stable_review_obligation_once():
    from workout_generator_pkg.planner_context import _link_review_obligations_to_assessment

    finding = {'severity': 'blocking', 'message': 'Correct Nordic progression.',
        'draftPath': '/workouts/0/exercises/0/progressionPlan'}
    assessment = {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
        'repairDimensions': ['prescription'], 'reason': 'Update the typed progression plan.'}]}
    obligation = {'obligationId': 'OBLIGATION_12345678901234567890', 'finding': copy.deepcopy(finding),
        'sourceDraftId': 'REVISION_4', 'sourceFingerprint': 'review-hash', 'references': ['LIBRARY_3']}

    linked, pending = _link_review_obligations_to_assessment(assessment, [finding], [obligation])

    assert linked['groups'][0]['obligationIds'] == ['OBLIGATION_12345678901234567890']
    assert pending == []


@pytest.mark.parametrize('stale_after_current', [False, True])
def test_current_audit_supersedes_only_older_stale_audit_for_same_candidate(stale_after_current):
    from types import SimpleNamespace

    equipment, stored, draft, messages = _history_bound_run('old-history')
    current = {'passed': True, 'requirementsId': stored['requirementsId'], 'currentDraftId': 'DRAFT_1',
        'historyFingerprint': 'current-history', 'libraryFingerprint': library_fingerprint(equipment),
        'submittedDraft': copy.deepcopy(draft), 'auditVersion': AUDIT_VERSION, 'reviewVersion': REVIEW_VERSION,
        'errors': [], 'instruction': 'Current candidate audit.'}
    stale = copy.deepcopy(json.loads(next(message['content'] for message in messages
        if message.get('tool_call_id') == 'old_audit')))
    if stale_after_current:
        _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId']}, current, 'current_audit')
        _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId']}, stale, 'later_stale_audit')
    else:
        _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId']}, stale, 'earlier_stale_audit')
        _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId']}, current, 'current_audit')

    state = _state(shell._messages_for_api(messages, True, SimpleNamespace(
        fingerprint='current-history', context=lambda: {'historyFingerprint': 'current-history'}), equipment))

    assert state['lastAudit']['passed'] is True
    assert bool(state.get('savedDraftReaudit')) is stale_after_current


def test_unbound_prevalidation_rejection_is_preserved_without_becoming_stale_audit():
    from types import SimpleNamespace
    from workout_generator_pkg.planner_context import _sanitize_stale_history_receipts

    equipment, stored, _, messages = _history_bound_run('current-history')
    rejection = {'passed': False, 'currentDraftId': 'DRAFT_1', 'code': 'invalid_arguments',
        'errors': [{'code': 'invalid_arguments', 'message': 'maxReps must be greater than minReps.'}]}
    _tool(messages, 'audit_workout_plan', {'baseDraftId': 'DRAFT_1'}, rejection, 'schema_rejection')

    sanitized = _sanitize_stale_history_receipts(messages, 'current-history', True)
    result = next(message for message in sanitized if message.get('tool_call_id') == 'schema_rejection')
    state = _state(shell._messages_for_api(messages, True, SimpleNamespace(
        fingerprint='current-history', context=lambda: {'historyFingerprint': 'current-history'}), equipment))

    assert json.loads(result['content']) == rejection
    assert 'schema_rejection' not in json.dumps(state.get('staleHistoryBoundReceipts', []))
    assert 'invalid_arguments' in json.dumps(state)
    assert stored['requirementsId'] == state['requirementsId']


def test_alternative_repair_snapshot_is_a_history_binding_for_resume_and_conflicts_fail_closed():
    from workout_generator_pkg.planner_context import _sanitize_stale_history_receipts

    _, _, _, messages = _history_bound_run('current-history')
    result = {'outcome': 'unresolved', 'attemptStatus': 'repair_failed',
        'submittedEdits': {'exerciseAdds': [{'definitionId': 'LIBRARY_A'}]},
        'rejectedAttemptEdits': {'exerciseAdds': [{'definitionId': 'LIBRARY_B'}]},
        'candidateSnapshot': {'trainingHistoryFingerprint': 'current-history',
            'repairCandidateId': 'ALT_1'}}
    _tool(messages, 'repair_workout_alternative', {}, result, 'legacy_nested_repair')

    sanitized = _sanitize_stale_history_receipts(messages, 'current-history', True)
    saved = next(message for message in sanitized if message.get('tool_call_id') == 'legacy_nested_repair')
    assert json.loads(saved['content']) == result

    conflicting_messages = copy.deepcopy(messages)
    conflicting_result = {**result, 'trainingHistoryFingerprint': 'other-history'}
    conflicting_messages[-1]['content'] = json.dumps(conflicting_result)
    conflicting = _sanitize_stale_history_receipts(conflicting_messages, 'current-history', True)
    stale = next(message for message in conflicting if message.get('tool_call_id') == 'legacy_nested_repair')
    assert json.loads(stale['content']) == {'staleHistory': True,
        'tool': 'repair_workout_alternative', 'historyFingerprint': 'other-history'}


def test_legacy_diagnosis_candidate_history_binding_uses_same_consistency_check():
    from workout_generator_pkg.planner_context import _sanitize_stale_history_receipts

    _, _, _, messages = _history_bound_run('current-history')
    result = {'outcome': 'unresolved', 'alternativeRepairCandidates': [
        {'repairCandidateId': 'ALT_1', 'trainingHistoryFingerprint': 'current-history'}]}
    _tool(messages, 'propose_workout_alternatives', {}, result, 'legacy_nested_diagnosis')
    sanitized = _sanitize_stale_history_receipts(messages, 'current-history', True)
    saved = next(message for message in sanitized if message.get('tool_call_id') == 'legacy_nested_diagnosis')
    assert json.loads(saved['content']) == result

    result['historyFingerprint'] = 'other-history'
    messages[-1]['content'] = json.dumps(result)
    conflicting = _sanitize_stale_history_receipts(messages, 'current-history', True)
    stale = next(message for message in conflicting if message.get('tool_call_id') == 'legacy_nested_diagnosis')
    assert json.loads(stale['content'])['staleHistory'] is True


def test_alternative_repair_handler_binds_result_for_planner_resume(monkeypatch):
    from types import SimpleNamespace
    from workout_generator_pkg.user_interaction import repair_workout_alternative_tool

    equipment, _, _, messages = _history_bound_run('current-history')
    candidate = {'repairCandidateId': 'ALT_1', 'originalRequirementsId': 'REQ_1',
        'requirementsId': 'REQ_ALT', 'trainingHistoryFingerprint': 'current-history',
        'submissionCorrectionEdits': {'exerciseAdds': [{'definitionId': 'LIBRARY_A'}]},
        'currentDraft': {'workouts': [{'exercises': [{'definition_id': 'LIBRARY_0'}]}]},
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['exercise_selection']} ]}}
    arguments = {'repairCandidateId': 'ALT_1', 'originalRequirementsId': 'REQ_1',
        'addressedFindingIndexes': [0], 'edits': {'exerciseAdds': [{'definitionId': 'LIBRARY_B'}]}}
    assert 'replaceRejectedRepair' in repair_workout_alternative_tool(candidate)['function']['parameters']['properties']

    expected_edits = {'exerciseAdds': [
        {'definitionId': 'LIBRARY_A'}, {'definitionId': 'LIBRARY_B'}]}
    expected_attempt = arguments['edits']
    monkeypatch.setattr('workout_generator_pkg.alternative_repair.execute_repair',
        lambda *args, **kwargs: {'outcome': 'unresolved', 'attemptStatus': 'repair_failed',
            'submittedEdits': expected_edits, 'rejectedAttemptEdits': expected_attempt,
            'candidateSnapshot': {'trainingHistoryFingerprint': 'current-history', 'repairCandidateId': 'ALT_1'}})

    handled = shell.handle_function_call(None, messages, 'repair_workout_alternative', arguments,
        equipment, deps=SimpleNamespace(execute_workout_generation=None), alternative_repair_task=candidate)
    payload = json.loads(handled['result'])
    assert payload['trainingHistoryFingerprint'] == 'current-history'
    assert payload['submittedEdits'] == expected_edits
    assert payload['rejectedAttemptEdits'] == expected_attempt

    _tool(messages, 'repair_workout_alternative', arguments, payload, 'bound_repair')
    sanitized = shell._sanitize_stale_history_receipts(messages, 'current-history', True)
    saved = next(message for message in sanitized if message.get('tool_call_id') == 'bound_repair')
    assert json.loads(saved['content']) == payload
    state = _state(shell._messages_for_api(messages, True,
        SimpleNamespace(fingerprint='current-history', context=lambda: {'historyFingerprint': 'current-history'}), equipment))
    assert not state.get('staleHistoryBoundReceipts')
    assert state['otherToolResults']['repair_workout_alternative']['attemptStatus'] == 'repair_failed'


def test_infeasible_repair_resume_uses_reviewed_candidate_and_keeps_full_proposal(monkeypatch):
    from types import SimpleNamespace
    from workout_generator_pkg.conflict_resolution import CONFLICT_RESOLUTION_VERSION
    from workout_generator_pkg.joint_planning import SELECTION_POLICY_VERSION, candidate_menu_fingerprint
    from workout_generator_pkg.planning_tools import _fingerprint, library_fingerprint
    from workout_generator_pkg.review_assessment import assessment_hash

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audit = audit_workout_plan(draft, equipment, messages)
    audit['reviewVersion'] = REVIEW_VERSION
    _tool(messages, 'audit_workout_plan', draft, audit, 'candidate-audit')

    finding = {'severity': 'warning', 'basis': 'uncertainty', 'path': '/draft/programGuidance',
        'evidencePaths': ['/draft/programGuidance'], 'message': 'Add plan-wide recovery guidance.',
        'repair': 'Describe recovery guidance.', 'action': 'repair', 'decisionId': None,
        'newConflictEvidencePaths': [], 'muscleTargets': [], 'draftPath': '/programGuidance'}
    review = {'version': REVIEW_VERSION, 'inputHash': 'retained-review-input',
        'instructionBoundary': 1, 'findings': [finding]}
    review['assessment'] = {'version': ASSESSMENT_VERSION,
        'inputHash': assessment_hash(review), 'groups': [{'findingIndexes': [0],
            'disposition': 'repair', 'repairDimensions': ['program_guidance'],
            'reason': 'Plan-wide coaching is missing.'}], 'repairPlan': 'Add plan-wide guidance.'}
    source_menu = candidate_menu_fingerprint(draft['workouts'])
    candidate = {'repairCandidateId': 'ALT_RETAINED', 'originalRequirementsId': stored['requirementsId'],
        'originalRequirementsHash': _fingerprint(stored['requirements']), 'requirementsId': stored['requirementsId'],
        'requirements': copy.deepcopy(stored['requirements']), 'baseDraftId': audit['currentDraftId'],
        'sourceDraftId': audit['currentDraftId'], 'sourceMenuFingerprint': source_menu,
        'candidateMenuFingerprint': source_menu, 'libraryFingerprint': library_fingerprint(equipment),
        'trainingHistoryFingerprint': audit.get('historyFingerprint'), 'resolvedDecisions': {},
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION, 'reviewVersion': REVIEW_VERSION,
        'workouts': copy.deepcopy(draft['workouts']), 'audit': copy.deepcopy(audit['audit']),
        'review': review, 'reviewFindings': [finding], 'reviewErrors': [], 'changes': []}
    diagnosis = {'outcome': 'candidate_feasible_pending_review', 'requirementsId': stored['requirementsId'],
        'baseDraftId': audit['currentDraftId'], 'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'alternativeRepairCandidates': [candidate]}
    _tool(messages, 'propose_workout_alternatives', {'requirementsId': stored['requirementsId'],
        'baseDraftId': audit['currentDraftId']}, diagnosis,
        'retained-diagnosis')

    proposal = {'programGuidance': 'Use this plan-wide recovery guidance. ' * 30}
    stale_unreviewed_snapshot = {**copy.deepcopy(candidate), 'programGuidance': proposal['programGuidance']}
    failed = {'outcome': 'unresolved', 'attemptStatus': 'repair_menu_infeasible',
        'repairCandidateId': candidate['repairCandidateId'], 'candidateSnapshot': stale_unreviewed_snapshot,
        'originalRequirementsId': candidate['originalRequirementsId'],
        'requirementsId': candidate['requirementsId'], 'libraryFingerprint': candidate['libraryFingerprint'],
        'trainingHistoryFingerprint': candidate['trainingHistoryFingerprint'],
        'jointSolve': {'status': 'infeasible', 'feasibilityDomainFingerprint': 'PROVEN_DOMAIN',
            'selectionPolicyVersion': SELECTION_POLICY_VERSION,
            'preserveSourceSelection': True, 'recipeCount': 17, 'optionCount': 51},
        'submittedEdits': proposal, 'errors': [{'code': 'joint_menu_infeasible',
            'message': 'No combination in the supplied repair menu is feasible.'}]}
    _tool(messages, 'repair_workout_alternative', {'repairCandidateId': candidate['repairCandidateId']}, failed,
        'failed-infeasible-repair')
    from workout_generator_pkg.planner_context import _known_infeasible_alternative_receipt
    direct = _known_infeasible_alternative_receipt([(0, {'name': 'repair_workout_alternative'}, failed)],
        candidate, equipment, candidate.get('trainingHistoryFingerprint'))
    assert direct

    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    task = state['alternativeRepairTask']
    assert task['repairCandidateId'] == candidate['repairCandidateId']
    assert task['currentDraft'].get('programGuidance') is None
    assert task['submissionCorrectionEdits'] == proposal
    assert task['repairStage'] == 'change_feasibility_domain'
    assert task['decisionRequired'] is True
    assert task['knownInfeasibleMenu']['feasibilityDomainFingerprint'] == 'PROVEN_DOMAIN'

    refreshed_candidates = []
    monkeypatch.setattr('workout_generator_pkg.alternative_repair._fresh_binding', lambda *args, **kwargs: True)
    def refresh(candidate, *args, **kwargs):
        refreshed_candidates.append(copy.deepcopy(candidate))
        return {'status': 'refreshed', 'candidate': candidate}
    monkeypatch.setattr('workout_generator_pkg.alternative_repair.refresh_candidate_assessment', refresh)
    shell.handle_function_call(None, messages, 'propose_workout_alternatives', {
        'requirementsId': stored['requirementsId'], 'baseDraftId': audit['currentDraftId'],
        'repairCandidateId': candidate['repairCandidateId'], 'staleAlternativeAssessment': True,
        'workouts': copy.deepcopy(draft['workouts'])}, equipment,
        deps=SimpleNamespace(execute_workout_generation=None))
    assert len(refreshed_candidates) == 1
    assert refreshed_candidates[0].get('programGuidance') is None


def test_stale_worker_candidate_reassessment_does_not_force_old_preparation_patch():
    from workout_generator_pkg.planner_context import _sanitize_stale_history_receipts
    from workout_generator_pkg.session_drafting import preparation_repair_task, resolve_preparation_patch
    from test_workout_generator_parallel_planning import week_case

    equipment, messages, prepared, _ = week_case()
    error = {'code': 'training_load_suitability_unresolved', 'repairStage': 'candidate_reassessment',
        'path': '/workouts/0/exercises/0', 'repair': 'Select a different movement.'}
    proposal = {'exercises': copy.deepcopy(prepared['recipeSessions'][0]['exercises'])}
    _tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, {
        'preparationId': prepared['preparationId'], 'historyFingerprint': 'old-history',
        'workerFailures': {'0': {'proposal': proposal, 'errors': [error]}},
    }, 'stale_reassessment')
    active = _sanitize_stale_history_receipts(messages, 'current-history', True)
    fresh_full_prepare = {'requirementsId': prepared['requirementsId'], 'baseDraftId': None,
        'name': 'Fresh week', 'sessions': copy.deepcopy(prepared['sessions'])}

    assert preparation_repair_task(messages)
    assert preparation_repair_task(active) is None
    assert resolve_preparation_patch(fresh_full_prepare, active) == fresh_full_prepare


def test_alternative_repair_model_request_contains_only_hypothetical_candidate_and_bound_evidence():
    from workout_generator_pkg.user_interaction import repair_workout_alternative_tool

    original = {'name': 'Original', 'workouts': [{'name': 'Original day', 'exercises': [
        {'definition_id': f'LIBRARY_{index}', 'numWorkSets': 2} for index in range(24)]}]}
    candidate_workouts = [{'name': 'Alternative day', 'exercises': [
        {'definition_id': f'LIBRARY_{index}', 'numWorkSets': 2} for index in range(13)]}]
    findings = {'version': 1, 'groups': [{'disposition': 'repair', 'findingIndexes': [0]}]}
    corrections = [{'code': 'invalid_reference', 'candidateId': 'ALT_7', 'message': 'Use EXERCISE_0.'}]
    task = {
        'repairCandidateId': 'ALT_7', 'originalRequirementsId': 'REQ_ORIGINAL',
        'requirementsId': 'REQ_HYPOTHETICAL', 'sourceDraftId': 'DRAFT_ORIGINAL',
        'requirements': {'weeklyEffectiveSets': {'chest': {'minimum': 7, 'maximum': 12}}},
        'changes': [{'path': '/auditTargets/weeklyEffectiveSets/chest/minimum', 'before': 15, 'after': 7}],
        'baseDraftId': 'ALT_7', 'originalRequirementsHash': 'REQ_HASH',
        'libraryFingerprint': 'LIBRARY_HASH', 'trainingHistoryFingerprint': 'HISTORY_HASH',
        'resolvedDecisions': {'rest': '90 seconds'}, 'sourceMenuFingerprint': 'SOURCE_MENU',
        'candidateMenuFingerprint': 'CANDIDATE_MENU', 'diagnosisVersion': 3, 'reviewVersion': 8,
        'currentDraft': {'requirementsId': 'REQ_HYPOTHETICAL', 'name': 'Alternative day',
            'workouts': copy.deepcopy(candidate_workouts)},
        # These candidate snapshots duplicate currentDraft in backend state and must not reach the model.
        'workouts': copy.deepcopy(candidate_workouts), 'audit': {'largeAuditMarker': 'STALE_AUDIT'},
        'review': {'largeReviewMarker': 'DUPLICATE_REVIEW'},
        'findingsAssessment': findings, 'reviewFindings': [{'path': '/draft/exercises/0'}],
        'errors': [{'code': 'review_finding', 'candidateId': 'ALT_7'}],
        'submissionCorrectionErrors': corrections, 'instruction': 'Repair all candidate findings.',
        'submissionCorrectionEdits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0'}]},
        'submissionJointSolve': {'status': 'infeasible', 'problemFingerprint': 'JOINT_PROBLEM'},
        'replacementCandidates': {'LIBRARY_13': {'id': 'LIBRARY_13', 'name': 'Replacement'}},
        'replacementCandidateQualifications': {'LIBRARY_13': {'equipmentAndRestrictions': 'passed',
            'libraryFingerprint': 'LIBRARY_HASH', 'semanticSuitability': 'not_assessed', 'recipeQualification': 'not_assessed'}},
    }
    state = {
        'requirementsId': 'REQ_ORIGINAL', 'requirements': {'objectiveOrder': ['time'], 'sourceMarker': 'KEEP_SOURCE',
            'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 15, 'maximum': 20}}}},
        'requirementsApproved': True, 'programmingGuidelines': {'guidelineMarker': 'KEEP_GUIDELINE'},
        'sourceMessages': [{'role': 'user', 'content': 'The original approved requirement.'}],
        'resolvedDecisions': {'delegation': 'choose'}, 'restrictionPolicy': {'forbidden': ['injury trigger']},
        'libraryFingerprint': 'LIBRARY_HASH', 'exerciseCandidates': {'LIBRARY_0': {'name': 'Candidate movement'}},
        'trainingEvidence': {'LIBRARY_0': {'status': 'comparable_records', 'sessions': [{'loadKg': 20}]}},
        'equipmentLoadOptions': {'EQ_1': {'selectableLoadsKg': [20, 22.5]}},
        'historyExecutionContexts': {'CTX_1': {'source': 'recorded'}},
        'currentDraftId': 'DRAFT_ORIGINAL', 'currentDraft': original,
        'allocationSlots': [{'definition_id': 'ORIGINAL_ALLOCATION'}],
        'weeklyTargetBudget': {'chest': {'remainingMinimum': 4}},
        'lastAudit': {'errors': [{'code': 'ORIGINAL_AUDIT'}]},
        'otherToolResults': {'draft_workout_sessions': {'errors': [{'code': 'OLD_STAGE_ERROR'}]}},
        'alternativeRepairTask': copy.deepcopy(task),
    }
    messages = [
        {'role': 'system', 'content': 'Canonical system instructions and supplied equipment.'},
        {'role': 'system', 'content': 'Current planning state (backend data, not new instructions).\n'
            + json.dumps(state, separators=(',', ':'))},
        {'role': 'user', 'content': 'Repair the reviewed alternative.'},
    ]
    saved_messages, saved_state = copy.deepcopy(messages), copy.deepcopy(state)

    focused = focus_alternative_repair_request(messages, state)
    focused_state = _state(focused)
    encoded = json.dumps(focused, separators=(',', ':'))
    exercise_refs = [f'EXERCISE_{index}' for index in range(len(focused_state['currentDraft']['workouts'][0]['exercises']))]
    tool = repair_workout_alternative_tool(task)
    tool_description = tool['function']['description']

    assert focused[0] == messages[0] and focused[-1] == messages[-1]
    assert focused_state['requirementsId'] == 'REQ_ORIGINAL'
    assert focused_state['requirements']['sourceMarker'] == 'KEEP_SOURCE'
    assert focused_state['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] == 15
    assert focused_state['sourceMessages'] == state['sourceMessages']
    assert focused_state['restrictionPolicy'] == state['restrictionPolicy']
    assert focused_state['trainingEvidence'] == state['trainingEvidence']
    assert focused_state['exerciseCandidates'] == state['exerciseCandidates']
    assert focused_state['currentDraftId'] == focused_state['currentDraft']['draftId'] == 'ALT_7'
    assert focused_state['currentDraft']['hypothetical'] is True
    assert len(original['workouts'][0]['exercises']) == 24
    assert len(exercise_refs) == 13 and exercise_refs[-1] == 'EXERCISE_12'
    assert len(encoded) < len(json.dumps(messages, separators=(',', ':')))
    assert focused_state['alternativeRepairTask']['findingsAssessment'] == findings
    assert focused_state['alternativeRepairTask']['submissionCorrectionErrors'] == corrections
    assert focused_state['alternativeRepairTask']['submissionCorrectionEdits'] == task['submissionCorrectionEdits']
    assert focused_state['alternativeRepairTask']['submissionJointSolve'] == task['submissionJointSolve']
    assert focused_state['alternativeRepairTask']['replacementCandidates'] == task['replacementCandidates']
    assert focused_state['alternativeRepairTask']['replacementCandidateQualifications'] == task['replacementCandidateQualifications']
    assert focused_state['alternativeRepairTask']['hypotheticalRequirements']['weeklyEffectiveSets']['chest']['minimum'] == 7
    assert focused_state['alternativeRepairTask']['proposedRequirementChanges'] == task['changes']
    assert 'currentDraft' not in focused_state['alternativeRepairTask']
    assert 'workouts' not in focused_state['alternativeRepairTask']
    assert not any(key in focused_state for key in ('allocationSlots', 'weeklyTargetBudget', 'lastAudit', 'otherToolResults'))
    assert all(marker not in encoded for marker in ('ORIGINAL_ALLOCATION', 'ORIGINAL_AUDIT', 'OLD_STAGE_ERROR',
        'STALE_AUDIT', 'DUPLICATE_REVIEW', 'EXERCISE_23'))
    assert 'EXERCISE_12=LIBRARY_12' in tool_description
    assert 'EXERCISE_23' not in tool_description
    assert 'submissionCorrectionErrors and submissionCorrectionEdits describe the prior rejected attempt' in focused[1]['content']
    assert 'fixed hypothetical targets are not approval' in focused[1]['content']
    assert messages == saved_messages and state == saved_state


def test_active_alternative_repair_without_authoritative_snapshot_fails_closed():
    with pytest.raises(ValueError, match='authoritative planning-state snapshot is missing'):
        focus_alternative_repair_request([], {'alternativeRepairTask': {'currentDraft': {'workouts': []}}})


def test_alternative_repair_replacements_resolve_only_currently_available_cached_ids():
    equipment, _, _, _ = planning_case()
    eligible = copy.deepcopy(equipment['exerciseDefinitions'][0])
    unavailable = {**copy.deepcopy(eligible), 'id': 'unavailable', 'name': 'Unavailable', 'equipmentId': 'missing'}
    excluded = {**copy.deepcopy(eligible), 'id': 'excluded', 'name': 'Excluded'}
    catalog = {'LIBRARY_0': eligible, 'LIBRARY_1': unavailable, 'LIBRARY_2': excluded}
    references = {key: {'name': definition['name']} for key, definition in catalog.items()}

    candidates, qualifications = _available_alternative_replacements(
        references, catalog, equipment, {'excludedDefinitionIds': ['excluded']}, {}, 'LIBRARY_HASH')

    assert set(candidates) == {'LIBRARY_0'}
    assert candidates['LIBRARY_0']['name'] == 'Push-Up'
    assert qualifications['LIBRARY_0'] == {
        'equipmentAndRestrictions': 'passed', 'libraryFingerprint': 'LIBRARY_HASH',
        'semanticSuitability': 'not_assessed', 'recipeQualification': 'not_assessed'}


def test_failed_stage_snapshots_are_projected_once_without_changing_saved_evidence():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    error = {'code': 'invalid_arguments', 'message': 'Correct the saved submission.'}
    bulky = {'fullCandidateMarker': 'candidate' * 1000}
    payloads = {
        'draft_workout_sessions': {'passed': False, 'preparationId': 'PREP_1', 'errors': [error],
            'structureReview': {'passed': False, 'findings': ['Fix ordering.']},
            'recipeQualification': bulky, 'workerResults': [bulky]},
        'propose_workout_alternatives': {'outcome': 'unresolved', 'errors': [error],
            'reason': 'Alternative review is incomplete.', 'alternativeRepairCandidates': [],
            'attempts': [{'scenario': 'independent_review', 'status': 'not_passed', 'findings': [bulky]}]},
        'repair_workout_alternative': {'outcome': 'unresolved', 'attemptStatus': 'repair_failed',
            'repairCandidateId': 'ALT_1', 'errors': [error], 'candidateSnapshot': bulky},
    }
    for name, payload in payloads.items():
        _tool(messages, name, {}, payload, name)
    result = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, result, 'audit')
    saved = copy.deepcopy(messages)

    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    state = _state(outgoing)

    assert messages == saved
    assert 'fullCandidateMarker' not in json.dumps(state)
    assert state['currentDraft']['workouts'][0]['exercises'][0]['definition_id'] == draft['workouts'][0]['exercises'][0]['definition_id']
    for name in payloads:
        assert state['otherToolResults'][name]['errors'] == [error]
    assert state['otherToolResults']['draft_workout_sessions']['structureReview'] == payloads['draft_workout_sessions']['structureReview']
    assert state['otherToolResults']['repair_workout_alternative']['repairCandidateId'] == 'ALT_1'
    assert state['otherToolResults']['propose_workout_alternatives']['attempts'] == [
        {'scenario': 'independent_review', 'status': 'not_passed'}]
    assert 'placement notes carry only local execution/progression/stop guidance' not in json.dumps(outgoing)
    assert 'Keep placementNotes for technique, setup, progression' not in json.dumps(outgoing)


def test_repair_snapshots_keep_stable_evidence_before_changing_draft():
    equipment,_,stored,draft=planning_case()
    prefixes=[]
    for count in (3,4):
        current=copy.deepcopy(draft)
        current['workouts'][0]['exercises'][0]['numWorkSets']=count
        messages=requirement_messages(stored)
        result=audit_workout_plan(current,equipment,messages)
        _tool(messages,'audit_workout_plan',current,result,'audit')
        outgoing=shell._messages_for_api(messages,True,provided_equipment=equipment)
        state=_state(outgoing)
        assert state['currentDraft']['workouts'][0]['exercises'][0]['numWorkSets']==count
        text=json.dumps(state,separators=(',',':'))
        assert text.index('"sourceMessages"') < text.index('"currentDraft"')
        prefixes.append(text[:text.index('"currentDraft"')])
    assert prefixes[0]==prefixes[1]


def test_compacted_review_assessment_keeps_its_validation_hash_and_routes_to_coordinated_repair():
    from workout_generator_pkg.review_assessment import assessment_hash

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    finding = {'severity': 'warning', 'basis': 'uncertainty', 'path': '/draft/exercises/0/placementNotes',
        'evidencePaths': ['/draft/exercises/0/placementNotes'], 'message': 'Add the missing local setup cue.',
        'repair': 'Describe the setup.', 'action': 'repair', 'decisionId': None,
        'newConflictEvidencePaths': [], 'muscleTargets': []}
    review_input_hash = 'review-input-hash'
    findings = [finding]
    assessment = {'version': ASSESSMENT_VERSION,
        'inputHash': assessment_hash({'inputHash': review_input_hash, 'findings': findings}),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'],
                    'reason': 'The setup cue is missing.'}], 'repairPlan': 'Add the setup cue.'}
    result.update(passed=False, errors=[{'code': 'independent_review_finding',
        'path': '/draft/exercises/0/placementNotes', 'draftPath': '/workouts/0/exercises/0/placementNotes',
        'reviewScope': 'execution', 'message': finding['message']}],
        review={'version': REVIEW_VERSION, 'inputHash': review_input_hash,
            'findings': findings, 'assessment': assessment})
    _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId'], 'workouts': draft['workouts']},
          result, 'reviewed-candidate')

    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))

    assert state['lastAudit']['reviewInputHash'] == review_input_hash
    assert state['repairTask']['findingsAssessment'] == assessment
    assert state['repairTask']['reviewFindings'] == findings
    assert state.get('savedDraftReaudit') is None


def test_continue_reopens_a_capped_repair_from_its_saved_review_receipt():
    from workout_generator_pkg.review_assessment import assessment_hash

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    baseline = audit_workout_plan(draft, equipment, messages)
    finding = {'severity': 'warning', 'basis': 'uncertainty', 'path': '/draft/exercises/0/placementNotes',
        'evidencePaths': ['/draft/exercises/0/placementNotes'], 'message': 'Add the missing local setup cue.',
        'repair': 'Describe the setup.', 'action': 'repair', 'decisionId': None,
        'newConflictEvidencePaths': [], 'muscleTargets': [], 'draftPath': '/workouts/0/exercises/0/placementNotes',
        'reviewScope': 'execution'}
    review_input_hash = 'saved-review-input'
    findings = [finding]
    assessment = {'version': ASSESSMENT_VERSION,
        'inputHash': assessment_hash({'inputHash': review_input_hash, 'findings': findings}),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'],
                    'reason': 'The setup cue is missing.'}], 'repairPlan': 'Add the setup cue.'}
    baseline.update(passed=False, errors=[{'code': 'independent_review_finding', **finding}],
        review={'version': REVIEW_VERSION, 'inputHash': review_input_hash,
            'findings': findings, 'assessment': assessment})
    baseline.setdefault('historyFingerprint', None)
    baseline.setdefault('resolvedDecisions', {})
    _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId'], 'workouts': draft['workouts']},
          baseline, 'capped-baseline')
    receipt = {'status': 'rejected_before_materialization', 'baseDraftId': baseline['currentDraftId'],
        'currentDraftId': baseline['currentDraftId'], 'requirementsId': stored['requirementsId'],
        'submittedEdits': {'exerciseUpdates': []}, 'findingsAssessment': assessment, 'reviewFindings': findings,
        'assessmentInputHash': assessment['inputHash'],
        'assessmentHash': assessment_hash({'inputHash': assessment['inputHash'], 'findings': findings}),
        'libraryFingerprint': baseline['libraryFingerprint'], 'historyFingerprint': baseline['historyFingerprint'],
        'resolvedDecisions': baseline['resolvedDecisions']}
    _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId'],
        'baseDraftId': baseline['currentDraftId'], 'edits': {'exerciseUpdates': []}},
        {'passed': False, 'requirementsId': stored['requirementsId'], 'currentDraftId': baseline['currentDraftId'],
         'errors': [{'code': 'repair_round_cap_reached', 'path': '/patch', 'message': 'This attempt reached its repair cap.'}],
         'coordinatedRepairReceipt': receipt, 'findingsAssessment': assessment, 'reviewFindings': findings}, 'capped-repair')
    messages.append({'role': 'user', 'content': '/continue'})

    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))

    assert state.get('savedDraftReaudit') is None
    assert state['lastAudit']['errors'][0]['code'] == 'independent_review_finding'
    assert state['lastAudit']['errors'][0]['findingIndex'] == 0
    assert state['repairTask']['findingIndexes'] == [0]
    assert state['repairTask']['findingsAssessment'] == assessment


def test_consecutive_rejected_repairs_keep_bound_review_authority():
    from workout_generator_pkg.interactive_shell import _coordinated_repair_receipt_context
    from workout_generator_pkg.planner_context import _coordinated_receipt_matches
    from workout_generator_pkg.review_assessment import assessment_hash

    assessment_input_hash = 'review-input-182'
    findings = [{'severity': 'warning', 'action': 'repair', 'message': 'Preserve the approved movement choice.'}]
    assessment = {'inputHash': assessment_hash({'inputHash': assessment_input_hash, 'findings': findings}),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['exercise_selection'],
                    'reason': 'The movement choice needs correction.'}], 'repairPlan': 'Correct the movement choice.'}
    task = {'requirementsId': 'REQ_1', 'baseDraftId': 'REVISION_19',
        'findingsAssessment': assessment, 'reviewFindings': findings}
    source_audit = {'requirementsId': 'REQ_1', 'currentDraftId': 'REVISION_19',
        'assessmentDraftId': 'REVISION_19', 'auditVersion': 43,
        'reviewVersion': REVIEW_VERSION, 'reviewInputHash': assessment_input_hash,
        'libraryFingerprint': 'library-current', 'historyFingerprint': 'history-current',
        'resolvedDecisions': {'DECISION_1': 'approved'},
        'review': {'version': REVIEW_VERSION, 'inputHash': assessment_input_hash}}

    first_context = _coordinated_repair_receipt_context(task, source_audit)
    first_receipt = {'status': 'rejected_before_materialization', 'baseDraftId': 'REVISION_19',
        'currentDraftId': 'REVISION_19', 'reviewedDraftId': 'REVISION_19', 'requirementsId': 'REQ_1',
        'assessmentInputHash': assessment['inputHash'],
        'assessmentHash': assessment_hash({'inputHash': assessment['inputHash'], 'findings': findings}),
        'findingsAssessment': assessment, 'reviewFindings': findings, **first_context}
    # A rejection payload can omit library/history at its top level. The next
    # atomic rejection must inherit those fields from this still-bound receipt.
    second_context = _coordinated_repair_receipt_context(task, {
        'requirementsId': 'REQ_1', 'currentDraftId': 'REVISION_19',
        'coordinatedRepairReceipt': first_receipt,
    })
    second_receipt = {**first_receipt, **second_context}

    assert second_context == first_context
    assert _coordinated_receipt_matches(second_receipt, 'REQ_1', 'REVISION_19',
        'library-current', 'history-current', {'DECISION_1': 'approved'})


def test_newer_current_review_supersedes_older_rejected_repair_receipt():
    from workout_generator_pkg.review_assessment import assessment_hash

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    baseline = audit_workout_plan(draft, equipment, messages)

    def reviewed(message, review_input_hash):
        finding = {'severity': 'warning', 'basis': 'uncertainty', 'path': '/draft/exercises/0/placementNotes',
            'evidencePaths': ['/draft/exercises/0/placementNotes'], 'message': message,
            'repair': f'Address: {message}', 'action': 'repair', 'decisionId': None,
            'newConflictEvidencePaths': [], 'muscleTargets': [], 'draftPath': '/workouts/0/exercises/0/placementNotes',
            'reviewScope': 'execution'}
        findings = [finding]
        assessment = {'version': ASSESSMENT_VERSION,
            'inputHash': assessment_hash({'inputHash': review_input_hash, 'findings': findings}),
            'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'],
                'reason': message}], 'repairPlan': finding['repair']}
        result = copy.deepcopy(baseline)
        result.update(passed=False, errors=[{'code': 'independent_review_finding', **finding}],
            review={'version': REVIEW_VERSION, 'inputHash': review_input_hash,
                'findings': findings, 'assessment': assessment})
        return result, assessment, findings

    old_result, old_assessment, old_findings = reviewed('Old review finding.', 'old-review-input')
    _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId'], 'workouts': draft['workouts']},
        old_result, 'old-review')
    receipt = {'status': 'rejected_before_materialization', 'baseDraftId': old_result['currentDraftId'],
        'currentDraftId': old_result['currentDraftId'], 'requirementsId': stored['requirementsId'],
        'submittedEdits': {'exerciseUpdates': []}, 'findingsAssessment': old_assessment,
        'reviewFindings': old_findings, 'assessmentInputHash': old_assessment['inputHash'],
        'libraryFingerprint': old_result['libraryFingerprint'], 'historyFingerprint': old_result.get('historyFingerprint'),
        'resolvedDecisions': old_result.get('resolvedDecisions', {})}
    _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId'],
        'baseDraftId': old_result['currentDraftId'], 'edits': {'exerciseUpdates': []}},
        {'passed': False, 'requirementsId': stored['requirementsId'], 'currentDraftId': old_result['currentDraftId'],
         'errors': [{'code': 'invalid_arguments', 'message': 'The repair request failed validation.'}],
         'coordinatedRepairReceipt': receipt}, 'old-rejected-repair')
    fresh_result, fresh_assessment, fresh_findings = reviewed('Fresh review finding.', 'fresh-review-input')
    _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId'], 'workouts': draft['workouts']},
        fresh_result, 'fresh-review')

    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))

    assert state['lastAudit']['findingsAssessment'] == fresh_assessment
    assert state['repairTask']['reviewFindings'] == fresh_findings
    assert state.get('savedDraftReaudit') is None


@pytest.mark.parametrize('current_review', [False, True])
def test_unresolved_review_capability_pauses_only_for_current_bound_review(current_review):
    from workout_generator_pkg.review_assessment import assessment_hash

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    finding = {'severity': 'blocking', 'message': 'Automatically lower load after a failed repetition.'}
    review = {'version': REVIEW_VERSION if current_review else REVIEW_VERSION - 1,
        'inputHash': 'capability-review', 'findings': [finding]}
    review['assessment'] = {'version': ASSESSMENT_VERSION,
        'inputHash': assessment_hash(review), 'repairPlan': '',
        'groups': [{'findingIndexes': [0], 'disposition': 'unresolved_capability',
            'repairDimensions': [], 'reason': 'Automatic within-set load reduction is unsupported.'}]}
    result = audit_workout_plan(draft, equipment, messages)
    result.update(passed=False,
        errors=[{'code': 'unresolved_review_capability', 'findingIndex': 0,
            'message': finding['message'], 'reviewScope': 'execution'}],
        review=review, reviewVersion=review['version'], findingsAssessment=review['assessment'],
        reviewFindings=[finding])
    _tool(messages, 'audit_workout_plan', draft, result, 'unsupported-review')

    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))

    if current_review:
        assert state['repairCapabilityUnresolved']['status'] == 'unresolved_capability'
        assert state['repairCapabilityUnresolved']['findingIndexes'] == [0]
        assert 'repairTask' not in state and not state.get('savedDraftReaudit')
    else:
        assert state['savedDraftReaudit']['baseDraftId'] == result['currentDraftId']
        assert 'repairTask' not in state and not state.get('repairCapabilityUnresolved')


def test_requirement_shape_error_keeps_prior_source_findings_until_new_source_or_review():
    equipment, requirements, stored, _ = planning_case()
    finding = {'path': '/requirements/requiredCoverage', 'message': 'An explicit source role is missing.',
               'severity': 'blocking', 'basis': 'established_violation'}
    failed = {**stored, 'passed': False, 'errors': [finding],
              'sourceReview': {'passed': False, 'findings': [finding]}}
    messages = [{'role': 'user', 'content': 'Keep the requested coverage.'}]
    _tool(messages, 'set_workout_requirements', requirements, failed, 'review')
    _tool(messages, 'set_workout_requirements', {**requirements, 'requirementsId': 'unexpected'},
          {'passed': False, 'errors': [{'code': 'invalid_arguments', 'path': '/', 'message': 'Unexpected field.'}]}, 'shape')
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['requirementsFeedback']['previousSourceFindings'] == [finding]
    assert state['requirementsFeedback']['errors'][0]['code'] == 'invalid_arguments' and messages == before
    changed_source = messages + [{'role': 'user', 'content': 'Change the coverage requirement.'}]
    assert 'previousSourceFindings' not in _state(shell._messages_for_api(changed_source, True, provided_equipment=equipment))['requirementsFeedback']
    _tool(messages, 'set_workout_requirements', requirements, failed, 'new-review')
    assert 'previousSourceFindings' not in _state(shell._messages_for_api(messages, True, provided_equipment=equipment))['requirementsFeedback']


def test_candidate_history_pooling_is_lossless_and_preserves_distinct_movements_and_types():
    from workout_generator_pkg.planner_context import _pool_candidate_history
    summary = {'status': 'no_comparable_records', 'totalSessions': 0,
        'loadHeadroom': {'maximumSelectableLoadKg': 25, 'observedAtCurrentEquipmentMaximum': False,
                         'loadMeaning': 'single_dumbbell_load'},
        'candidateContext': {'equipment': {'type': 'DUMBBELL'}, 'requiredAccessoryNames': ['Bench']}}
    candidates = {f'LIBRARY_{i}': {'name': f'Movement {i}', 'trainingEvidence': copy.deepcopy(summary)} for i in range(4)}
    candidates['LIBRARY_4'] = {'name': 'Distinct context', 'trainingEvidence': {**summary, 'totalSessions': False}}
    candidates['LIBRARY_5'] = {'name': 'No summary'}
    before = copy.deepcopy(candidates)
    compact, summaries = _pool_candidate_history(candidates)
    assert candidates == before and set(compact) == set(before)
    assert len(summaries) == 1 and 'trainingEvidence' in compact['LIBRARY_4']
    for reference, entry in compact.items():
        if 'trainingEvidenceRef' in entry:
            entry['trainingEvidence'] = copy.deepcopy(summaries[entry.pop('trainingEvidenceRef')])
    assert json.dumps(compact, sort_keys=True) == json.dumps(before, sort_keys=True)
    assert _pool_candidate_history({'LIBRARY_0': before['LIBRARY_0']})[1] == {}


def test_request_pools_search_summaries_without_changing_saved_results_or_candidate_metadata():
    from workout_generator_pkg.exercise_library_tools import _selection_entry, search_catalog
    equipment, _, stored, _ = planning_case()
    base = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [{**base, 'id': f'd{i}', 'name': f'Movement {i}'} for i in range(3)]
    summary = {'status': 'no_comparable_records', 'totalSessions': 0,
               'loadHeadroom': {'maximumSelectableLoadKg': 20, 'loadMeaning': 'additional_bodyweight_load'},
               'candidateContext': {'exerciseType': 'BODY_WEIGHT', 'bodyWeightPercentage': 100}}
    entries = [{**_selection_entry(definition, {}, f'LIBRARY_{i}'), 'trainingEvidence': copy.deepcopy(summary)}
               for i, definition in enumerate(equipment['exerciseDefinitions'])]
    messages = requirement_messages(stored)
    _tool(messages, 'search_exercise_library', {'queries': ['movement']},
          {'libraryFingerprint': search_catalog(equipment, {})[1],
           'results': [{'query': 'movement', 'exercises': entries}]}, 'search')
    before = copy.deepcopy(messages)
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    state = _state(outgoing)
    for reference, original in zip(state['exerciseCandidates'], entries):
        restored = copy.deepcopy(state['exerciseCandidates'][reference])
        restored['trainingEvidence'] = state['candidateHistorySummaries'][restored.pop('trainingEvidenceRef')]
        assert restored == original
    assert len(state['exerciseCandidates']) == 3 and messages == before
    assert 'candidateHistorySummaries' in outgoing[-1]['content']


def test_invalid_atomic_patch_keeps_rejected_request_through_noop_retry_until_changed_revision():
    from workout_generator_pkg.planning_tools import planning_tool_failure
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    initial.update(passed=False, errors=[{'code': 'independent_review_finding', 'reviewScope': 'execution',
        'path': '/draft/exercises/0/placementNotes', 'draftPath': '/workouts/0/exercises/0/placementNotes'}])
    _tool(messages, 'audit_workout_plan', draft, initial, 'initial')
    proposal = {'requirementsId': stored['requirementsId'], 'baseDraftId': initial['currentDraftId'], 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Corrected instructions.'},
        {'op': 'remove', 'path': '/workouts/0/exercises/0/workSetTemplate'}]}
    with pytest.raises(ValueError) as failure:
        audit_workout_plan(proposal, equipment, messages)
    rejected = planning_tool_failure('audit_workout_plan', failure.value, proposal)
    _tool(messages, 'audit_workout_plan', proposal, rejected, 'rejected')
    retry = {**proposal, 'patch': []}
    _tool(messages, 'audit_workout_plan', retry, initial, 'noop')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['lastAudit']['rejectedPatchRequest'] == proposal
    assert 'stable WORKOUT_n and EXERCISE_n edits' in state['repairTask']['instruction']
    expected_context_draft = copy.deepcopy(draft)
    expected_context_draft['workouts'][0]['reference'] = 'WORKOUT_0'
    expected_context_draft['workouts'][0]['exercises'][0]['reference'] = 'EXERCISE_0'
    assert state['currentDraft'] == expected_context_draft
    new_instruction = messages + [{'role': 'user', 'content': 'Explain the plan before doing anything else.'}]
    assert 'rejectedPatchRequest' not in _state(shell._messages_for_api(new_instruction, True, provided_equipment=equipment))['lastAudit']
    corrected = {**proposal, 'patch': proposal['patch'][:1]}
    fixed = audit_workout_plan(corrected, equipment, messages)
    _tool(messages, 'audit_workout_plan', corrected, fixed, 'fixed')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['currentDraft']['workouts'][0]['exercises'][0]['placementNotes'] == 'Corrected instructions.'
    assert 'rejectedPatchRequest' not in state['lastAudit']


@pytest.mark.parametrize('legacy_validation_code', [None, 'unused_superset_rest', 'invalid_superset_group_size'])
def test_coordinated_failure_context_keeps_active_and_background_findings_bound_to_candidate(legacy_validation_code):
    from workout_generator_pkg.review_assessment import assessment_hash

    equipment, _, stored, draft = planning_case()
    findings = [
        {'severity': 'blocking', 'basis': 'established_violation', 'action': 'repair',
         'message': 'Correct the movement choice.', 'draftPath': '/workouts/0/exercises/0/progressionPlan',
         'evidencePaths': ['/draft/exercises/0']},
        {'severity': 'warning', 'basis': 'uncertainty', 'action': 'repair',
         'message': 'Correct the prescription guidance.'},
    ]
    review_input_hash = 'review-input'
    assessment = {'version': ASSESSMENT_VERSION,
        'inputHash': assessment_hash({'inputHash': review_input_hash, 'findings': findings}),
        'repairPlan': 'Fix both groups.',
        'groups': [
            {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['exercise_selection'], 'reason': 'The movement is unsuitable.'},
            {'findingIndexes': [1], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'Guidance is inconsistent.'},
        ]}

    def receipt(status, base_id, current_id, edits, identity_audit):
        return {'status': status, 'requirementsId': stored['requirementsId'], 'baseDraftId': base_id,
            'currentDraftId': current_id, 'submittedEdits': edits, 'assessmentInputHash': assessment['inputHash'],
            'libraryFingerprint': identity_audit['libraryFingerprint'],
            'historyFingerprint': identity_audit['historyFingerprint'], 'resolvedDecisions': {},
            'reviewInputHash': identity_audit.get('review', {}).get('inputHash', review_input_hash),
            'assessmentHash': assessment_hash({'inputHash': assessment['inputHash'], 'findings': findings}),
            'findingsAssessment': copy.deepcopy(assessment), 'reviewFindings': copy.deepcopy(findings)}

    # First branch: a rejected coordinated patch did not materialize. The live candidate
    # and both originally assessed obligations must remain visible in the derived task.
    messages = requirement_messages(stored)
    base_result = audit_workout_plan(draft, equipment, messages)
    base_result.update(historyFingerprint=None, resolvedDecisions={})
    base_result.update(passed=False, errors=[{'code': 'independent_review_finding', 'path': '/workouts/0/name',
        'draftPath': '/workouts/0/name', 'reviewScope': 'execution'}],
        findingsAssessment=copy.deepcopy(assessment), review={'version': REVIEW_VERSION, 'inputHash': review_input_hash,
            'findings': copy.deepcopy(findings),
            'assessment': copy.deepcopy(assessment)}, reviewFindings=copy.deepcopy(findings))
    base_result['reviewChecklist'] = {'findings': {
        'OBLIGATION_a1111111111111111111': {'finding': copy.deepcopy(findings[0]),
            'references': ['LIBRARY_0'], 'sourceFingerprint': review_input_hash,
            'sourceDraftId': base_result['currentDraftId']},
        'OBLIGATION_b2222222222222222222': {'finding': copy.deepcopy(findings[1]),
            'references': [], 'sourceFingerprint': review_input_hash,
            'sourceDraftId': base_result['currentDraftId']},
    }, 'changedDraftPaths': [], 'sourceCount': 1}
    _tool(messages, 'audit_workout_plan', draft, base_result, 'base')
    rejected = {'requirementsId': stored['requirementsId'], 'baseDraftId': base_result['currentDraftId'],
        'edits': [{'op': 'replace', 'exerciseRef': 'EXERCISE_0', 'field': 'placementNotes', 'value': 'Correct technique.'}]}
    rejected_payload = {'passed': False, 'requirementsId': stored['requirementsId'],
        'currentDraftId': base_result['currentDraftId'], 'errors': [{'code': 'assessed_repair_not_addressed',
            'path': '/', 'message': 'Repair edit did not cover all assessed groups.'}],
        'coordinatedRepairReceipt': receipt('rejected_before_materialization', base_result['currentDraftId'],
            base_result['currentDraftId'], rejected['edits'], base_result)}
    _tool(messages, 'audit_workout_plan', rejected, rejected_payload, 'rejected')

    active = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert len(active['repairTask']['findingsAssessment']['groups']) == 2
    assert len(active['repairTask']['reviewFindings']) == 2
    assert active['repairTask']['rejectedCoordinatedRepair']['submittedEdits'] == rejected['edits']
    assert active['currentDraft']['workouts'][0]['exercises'][0]['reference'] == 'EXERCISE_0'
    assert active['repairTask']['editableExerciseReferences'] == ['EXERCISE_0']
    assert active['currentDraft']['workouts'][0]['reference'] == 'WORKOUT_0'

    # Second branch: the repair materialized, but the revised draft failed numeric
    # validation before another review. Prior findings are source-bound re-evaluation
    # obligations alongside the current blocker, not current verdicts.
    changed_messages = requirement_messages(stored)
    _tool(changed_messages, 'audit_workout_plan', draft, base_result, 'base-again')
    candidate = copy.deepcopy(draft)
    candidate['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    numeric_result = audit_workout_plan(candidate, equipment, changed_messages)
    assert numeric_result['passed'] is False
    numeric_result.update(historyFingerprint=None, resolvedDecisions={})
    numeric_result['coordinatedRepairReceipt'] = receipt('attempted_pending_validation',
        base_result['currentDraftId'], numeric_result['currentDraftId'], rejected['edits'], numeric_result)
    numeric_result['reviewChecklist'] = copy.deepcopy(base_result['reviewChecklist'])
    numeric_result['reviewFindings'] = copy.deepcopy(findings)
    _tool(changed_messages, 'audit_workout_plan', candidate, numeric_result, 'materialized')

    pending = _state(shell._messages_for_api(changed_messages, True, provided_equipment=equipment))
    assert 'findingsAssessment' not in pending['repairTask']
    assert pending['repairTask']['attemptedPendingValidation']['findingsAssessment']['groups'] == assessment['groups']
    assert pending['repairTask']['attemptedPendingValidation']['status'] == 'unresolved_background_obligations'
    assert pending['repairTask']['findingCode'] == 'volume_below_target'
    projected_obligations = pending['repairTask']['pendingReviewObligations']
    assert {item['obligationId'] for item in projected_obligations} == set(base_result['reviewChecklist']['findings'])
    assert all('finding' not in item and item['sourceDraftId'] == base_result['currentDraftId']
               and item['sourceFingerprint'] == review_input_hash for item in projected_obligations)
    assert pending['reviewLedgerSummary'] == {
        'status': 'source_bound_pending_adjudication', 'sourceBoundObligationCount': 2,
        'representedByCurrentAssessment': 0, 'pendingAdjudicationCount': 2}
    assert pending['repairTask']['reviewLedgerSummary'] == pending['reviewLedgerSummary']
    assert 'reviewFindings' not in pending['lastAudit']
    assert all('detailsOmitted' not in day for day in pending['currentDraft']['workouts'])

    legacy_messages = copy.deepcopy(changed_messages)
    legacy_result = json.loads(legacy_messages[-1]['content'])
    legacy_result.pop('coordinatedRepairReceipt')
    if legacy_validation_code:
        legacy_result['errors'] = [{'code': legacy_validation_code, 'path': '/workouts/0/exercises/0',
                                    'message': 'The materialized candidate has invalid superset structure.'}]
        legacy_result['audit']['errors'] = copy.deepcopy(legacy_result['errors'])
        legacy_result.pop('audit')
        legacy_result.update(coordinatedCandidatePending=True, findingsAssessment=copy.deepcopy(assessment))
    legacy_messages[-1]['content'] = json.dumps(legacy_result)
    legacy_pending = _state(shell._messages_for_api(legacy_messages, True, provided_equipment=equipment))
    assert legacy_pending['repairTask']['attemptedPendingValidation']['findingsAssessment']['groups'] == assessment['groups']
    assert 'findingsAssessment' not in legacy_pending['repairTask']

    # A later rejected edit must not promote the old assessment onto the changed draft.
    rejected_after_change = copy.deepcopy(rejected_payload)
    rejected_after_change['currentDraftId'] = legacy_result['currentDraftId']
    rejected_after_change['coordinatedRepairReceipt'] = receipt('rejected_before_materialization',
        legacy_result['currentDraftId'], legacy_result['currentDraftId'], rejected['edits'], legacy_result)
    rejected_after_change['coordinatedRepairReceipt'].update(libraryFingerprint=None, historyFingerprint=None)
    _tool(legacy_messages, 'audit_workout_plan', rejected, rejected_after_change, 'rejected-after-change')
    recovered = _state(shell._messages_for_api(legacy_messages, True, provided_equipment=equipment))
    assert 'findingsAssessment' not in recovered['repairTask']
    assert recovered['repairTask']['attemptedPendingValidation']['findingsAssessment']['groups'] == assessment['groups']
    assert recovered['repairTask']['findingCode'] == (legacy_validation_code or 'volume_below_target')


@pytest.mark.parametrize('findings_field', ['reviewFindings', 'review'])
def test_pending_review_obligations_map_only_unique_occurrence_identity(findings_field):
    from workout_generator_pkg.planner_context import _add_occurrence_references, _pending_review_obligations

    equipment, _, stored, draft = planning_case()
    findings = [{'severity': 'blocking', 'action': 'repair', 'message': 'Reassess this progression.',
        'draftPath': '/workouts/0/exercises/0/progressionPlan'}]
    source = {'requirementsId': stored['requirementsId'], 'currentDraftId': 'REVISION_0',
        'libraryFingerprint': 'library', 'historyFingerprint': 'history', 'resolvedDecisions': {},
        'submittedDraft': copy.deepcopy(draft)}
    if findings_field == 'reviewFindings':
        source['reviewFindings'] = findings
    else:
        source['review'] = {'version': REVIEW_VERSION, 'findings': findings}
    results = [(0, {'name': 'audit_workout_plan'}, source)]
    current = copy.deepcopy(draft)
    _add_occurrence_references(current)

    mapped = _pending_review_obligations(findings, results, current, stored['requirementsId'],
        'REVISION_1', 'library', 'history', {})
    assert mapped[0]['mappingStatus'] == 'mapped'
    assert mapped[0]['subjects'][0]['sourceExerciseRef'] == 'EXERCISE_0'
    assert mapped[0]['subjects'][0]['currentExerciseRef'] == 'EXERCISE_0'

    stale_results = [(0, {'name': 'audit_workout_plan'}, {**source, 'libraryFingerprint': 'stale-library'})]
    stale = _pending_review_obligations(findings, stale_results, current, stored['requirementsId'],
        'REVISION_1', 'library', 'history', {})
    assert stale[0]['mappingStatus'] == 'source_unavailable'
    assert stale[0]['subjects'] == []

    duplicate = copy.deepcopy(current['workouts'][0]['exercises'][0])
    draft_with_duplicate = copy.deepcopy(draft)
    draft_with_duplicate['workouts'][0]['exercises'].append(copy.deepcopy(duplicate))
    source['submittedDraft'] = draft_with_duplicate
    current['workouts'][0]['exercises'].append(duplicate)
    _add_occurrence_references(current)
    ambiguous = _pending_review_obligations(findings, results, current, stored['requirementsId'],
        'REVISION_1', 'library', 'history', {})
    assert ambiguous[0]['mappingStatus'] == 'requires_current_reassessment'
    assert ambiguous[0]['subjects'][0]['mappingStatus'] == 'ambiguous'
    assert len(ambiguous[0]['subjects'][0]['possibleCurrentOccurrences']) == 2


@pytest.mark.parametrize('name', ['prepare_workout_session', 'prepare_workout_sessions', 'draft_workout_sessions'])
def test_failed_preparation_feedback_and_arguments_survive_compaction_until_success(name):
    from workout_generator_pkg.planning_tools import planning_tool_failure
    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None, 'sessions': [{'description': 'too long'}]}
    failure = planning_tool_failure(name, ValueError('Invalid preparation'), arguments)
    _tool(messages, name, arguments, failure, 'failed-preparation')
    original = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    feedback = state['otherToolResults'][name]
    assert feedback['rejectedArguments'] == arguments
    assert f'call {name} again' in feedback['errors'][0]['repair']
    assert messages == original
    _tool(messages, name, arguments, {'passed': True}, 'fixed-preparation')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert name not in state['otherToolResults']


def test_movement_selection_allows_new_searches_until_selection_is_committed():
    from workout_generator_pkg.planner_context import construction_tool_failure
    for stage in ('discover_movements', 'choose_movements'):
        assert construction_tool_failure('search_exercise_library', {'queries': ['missing required pattern']},
            {'constructionTask': {'stage': stage}}) is None
    for stage in ('retrieve_evidence', 'draft_sessions', 'submit_session'):
        result = construction_tool_failure('search_exercise_library', {'queries': ['extra alternatives']},
            {'constructionTask': {'stage': stage}})
        assert result['errors'][0]['code'] == 'construction_stage_required'


def test_cached_alternatives_keep_numerical_credits_without_duplicate_full_entries():
    from workout_generator_pkg.exercise_library_tools import get_exercise_candidates
    equipment, _, stored, draft = planning_case()
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0], 'id': 'zzz', 'name': 'Alternative press'})
    messages = requirement_messages(stored)
    lookup = {'definition_ids': ['LIBRARY_1']}
    details = get_exercise_candidates(lookup, equipment, messages)
    _tool(messages, 'get_exercise_candidates', lookup, details, 'old-alternative')
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'submittedDraft': draft,
        'currentDraftId': 'REVISION_0', 'errors': [{'code': 'volume_below_target', 'path': '/workouts',
            'muscle': 'chest', 'scope': 'weekly'}]}, 'numeric-audit')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    alternative = state['cachedCandidateIndex']['LIBRARY_1']
    assert alternative['creditsPerWorkingSet'] == details['exercises'][0]['creditsPerWorkingSet']
    assert alternative['exerciseCategory'] == 'MODERATE_COMPOUND'
    assert 'trainingEvidence' not in alternative
    assert not set(state['cachedCandidateIndex']) & set(state['exerciseCandidates'])
    _tool(messages, 'get_exercise_candidates', lookup, details, 'fresh-alternative')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert 'LIBRARY_1' in state['exerciseCandidates'] and 'LIBRARY_1' not in state['cachedCandidateIndex']


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
    assert state['allocationSlots']['SLOT_0']['path'] == '/workouts/0/exercises/0'
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
    updated = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert updated['newInstructionPending']
    assert updated['planningDecisionNeeded'] is pending_clarification


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
            assert planner_response_profile(state) == {'reasoning_effort': None if index == 1 else 'low',
                                                       'activity': 'Selecting weekly movements' if index == 1 else 'Drafting session',
                                                       'max_tokens': 16384, 'timeout': None}
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
    assert state['currentDraft'] == _draft_with_references(draft) and state['lastAudit']['passed']
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
    state = _state(outgoing)
    assert state['requirementsApproved'] is True
    assert not any(m.get('role') == 'user' and m.get('content') == 'CONFIRM REQUIREMENTS' for m in outgoing)


def test_new_user_instruction_survives_work_order_compaction():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, result, 'audit')
    messages.append({'role': 'user', 'content': 'Keep the exact selected movement; do not substitute it.'})
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    assert messages[-1] in outgoing
    state = _state(outgoing)
    assert state['newInstructionPending']
    assert not state['planningDecisionNeeded']
    assert state['weeklyTargetBudget']['chest'] == {
        'alreadyCredited': 5, 'remainingMinimum': 0, 'remainingMaximum': 1}


def test_new_user_revision_is_not_restricted_to_an_obsolete_automatic_metadata_repair():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'submittedDraft': draft,
        'currentDraftId': 'REVISION_0', 'errors': [{'code': 'export_notes_too_long',
            'path': '/workouts/0/exercises/0/placementNotes'}]}, 'notes')
    automatic = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert automatic['repairTask']['permittedPatchPaths'] == ['/workouts/0/exercises/0/placementNotes']
    messages.append({'role': 'user', 'content': 'Revise the exercise selection and set distribution while preserving my approved requirements.'})
    revision = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert revision['requirementsApproved'] and revision['newInstructionPending']
    assert not revision['planningDecisionNeeded']
    assert not revision.get('repairTask')
    assert revision['currentDraft'] == _draft_with_references(draft)


def test_missing_coverage_is_repaired_before_numeric_allocation():
    equipment, _, stored, draft = planning_case()
    from workout_generator_pkg.planning_tools import library_fingerprint
    messages = requirement_messages(stored)
    errors = [
        {'code': 'volume_below_target', 'path': '/workouts', 'muscle': 'chest', 'scope': 'weekly'},
        {'code': 'required_coverage_missing', 'path': '/workouts', 'coverageKey': 'push'},
        {'code': 'required_coverage_missing', 'path': '/workouts', 'coverageKey': 'calves'}]
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'submittedDraft': draft,
        'requirementsId': stored['requirementsId'], 'currentDraftId': 'REVISION_0',
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'resolvedDecisions': {}, 'coordinatedJointPlanning': {'status': 'infeasible',
            'problemFingerprint': 'source-problem-fingerprint'}, 'errors': errors}, 'audit')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['repairTask']['findingCode'] == 'required_coverage_missing'
    assert state['repairTask']['findingIndexes'] == [1]
    assert state['repairTask']['placementNotesLimits']['/workouts/0/exercises/0/placementNotes']['exportMaximumCharacters'] >= 500
    assert state['lastAudit']['errors'] == errors
    assert state['candidateMenuExpansionTask']['sourceProblemFingerprint'] == 'source-problem-fingerprint'
    assert state['candidateMenuExpansionTask']['blockers'] == [errors[1], errors[2]]
    assert 'Do not offer numeric relaxations' in state['candidateMenuExpansionTask']['instruction']
    assert 'conflictDiagnosisTask' not in state


def test_expansion_marker_requires_changed_menu_and_current_bound_problem_proof():
    from workout_generator_pkg.joint_planning import candidate_menu_fingerprint
    from workout_generator_pkg.planner_context import _candidate_menu_expansion_status, _joint_receipt_is_feasible
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, source = planning_case()
    expanded = copy.deepcopy(source)
    expanded['workouts'][0]['exercises'].append(copy.deepcopy(expanded['workouts'][0]['exercises'][0]))
    expanded['workouts'][0]['exercises'][-1]['definition_id'] = 'LIBRARY_1'
    source_menu = candidate_menu_fingerprint(source['workouts'])
    result_menu = candidate_menu_fingerprint(expanded['workouts'])
    source_payload = {'requirementsId': stored['requirementsId'], 'currentDraftId': 'REVISION_0',
        'libraryFingerprint': 'LIB', 'historyFingerprint': 'HIST', 'resolvedDecisions': {},
        'audit': {},
        'submittedDraft': source, 'coordinatedJointPlanning': {'status': 'infeasible',
            'problemFingerprint': 'SOURCE_FP'}}
    result_payload = {'requirementsId': stored['requirementsId'], 'currentDraftId': 'REVISION_1',
        'libraryFingerprint': 'LIB', 'historyFingerprint': 'HIST', 'resolvedDecisions': {},
        'audit': {},
        'submittedDraft': expanded, 'coordinatedJointPlanning': {'status': 'infeasible',
            'problemFingerprint': 'RESULT_FP'}}
    result_payload['candidateMenuExpansion'] = {'attempted': True,
        'sourceBaseDraftId': 'REVISION_0', 'sourceProblemFingerprint': 'SOURCE_FP',
        'sourceMenuFingerprint': source_menu, 'requirementsId': stored['requirementsId'],
        'libraryFingerprint': 'LIB', 'historyFingerprint': 'HIST', 'resolvedDecisions': {},
        'resultMenuFingerprint': result_menu, 'resultingProblemFingerprint': 'RESULT_FP'}
    results = [(0, {'name': 'audit_workout_plan'}, source_payload),
        (1, {'name': 'audit_workout_plan'}, result_payload)]
    assert _candidate_menu_expansion_status(results, result_payload, expanded['workouts'],
        stored['requirementsId'], 'LIB', {})[0] == 'expanded'
    assert _joint_receipt_is_feasible({'status': 'optimal'})
    assert _joint_receipt_is_feasible({'status': 'unproven', 'feasible': True})
    assert not _joint_receipt_is_feasible({'status': 'unproven', 'feasible': False})

    messages = requirement_messages(stored)
    source_payload = {**source_payload, 'libraryFingerprint': library_fingerprint(equipment)}
    result_payload = {**result_payload, 'libraryFingerprint': library_fingerprint(equipment),
        'passed': True, 'coordinatedJointPlanning': {'status': 'optimal', 'feasible': True,
            'problemFingerprint': 'RESULT_FP'}}
    result_payload['candidateMenuExpansion']['libraryFingerprint'] = library_fingerprint(equipment)
    # Refresh the transcript references after rebinding the payloads to the real
    # authority fingerprints; otherwise the source receipt remains intentionally stale.
    results = [(0, {'name': 'audit_workout_plan'}, source_payload),
        (1, {'name': 'audit_workout_plan'}, result_payload)]
    assert _candidate_menu_expansion_status(results, result_payload, expanded['workouts'],
        stored['requirementsId'], library_fingerprint(equipment), {})[0] == 'expanded'
    _tool(messages, 'audit_workout_plan', source, source_payload, 'expansion-source')
    _tool(messages, 'audit_workout_plan', expanded, result_payload, 'expansion-optimal')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert 'menuExpansionUnresolved' not in state, (state.get('menuExpansionUnresolved'), state.get('lastAudit'), state.get('resolvedDecisions'))
    assert 'candidateMenuExpansionTask' not in state
    assert 'conflictDiagnosisTask' not in state

    notes_only = copy.deepcopy(source_payload)
    notes_only['currentDraftId'] = 'REVISION_NOTES'
    notes_only['submittedDraft']['workouts'][0]['exercises'][0]['placementNotes'] = 'Changed cue'
    notes_only['coordinatedJointPlanning'] = {'status': 'infeasible', 'problemFingerprint': 'NOTES_FP'}
    notes_only['candidateMenuExpansion'] = {'attempted': True,
        'sourceBaseDraftId': 'REVISION_0', 'sourceProblemFingerprint': 'SOURCE_FP',
        'sourceMenuFingerprint': source_menu, 'requirementsId': stored['requirementsId'],
        'libraryFingerprint': 'LIB', 'historyFingerprint': 'HIST', 'resolvedDecisions': {},
        'resultMenuFingerprint': source_menu, 'resultingProblemFingerprint': 'NOTES_FP'}
    assert _candidate_menu_expansion_status(results + [(2, {'name': 'audit_workout_plan'}, notes_only)],
        notes_only, notes_only['submittedDraft']['workouts'], stored['requirementsId'], 'LIB', {})[0] == 'unresolved'
    empty_reaudit = {'name': 'audit_workout_plan', 'arguments': json.dumps({
        'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': []})}
    assert _candidate_menu_expansion_status(results + [(2, empty_reaudit, notes_only)],
        notes_only, notes_only['submittedDraft']['workouts'], stored['requirementsId'], 'LIB', {})[0] == 'not_attempted'

    no_audit_attempt = {'role': 'assistant', 'candidateMenuExpansionAttempt': {
        'version': 1, 'attempted': True, 'auditedCandidate': False,
        'sourceBaseDraftId': 'REVISION_0', 'sourceProblemFingerprint': 'SOURCE_FP',
        'sourceMenuFingerprint': source_menu, 'requirementsId': stored['requirementsId'],
        'libraryFingerprint': 'LIB', 'historyFingerprint': 'HIST', 'resolvedDecisions': {}}}
    assert _candidate_menu_expansion_status([(0, {'name': 'audit_workout_plan'}, source_payload)],
        source_payload, source['workouts'], stored['requirementsId'], 'LIB', {}, [no_audit_attempt])[0] == 'retryable'


def test_changed_expansion_menu_does_not_hide_a_persisting_coverage_blocker():
    from workout_generator_pkg.planner_context import _remaining_menu_expansion_blockers
    blocker = {'code': 'required_coverage_missing', 'coverageKey': 'horizontal_pull_weekly'}
    marker = {'blockers': [blocker]}
    assert _remaining_menu_expansion_blockers(marker, [blocker]) == [blocker]
    assert _remaining_menu_expansion_blockers(marker, [
        {'code': 'required_coverage_missing', 'coverageKey': 'vertical_pull_weekly'}]) == []


def test_invalid_menu_expansion_patch_gets_one_correction_then_pauses():
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    source = {'passed': False, 'requirementsId': stored['requirementsId'], 'currentDraftId': 'REVISION_0',
        'submittedDraft': draft, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'resolvedDecisions': {},
        'errors': [{'code': 'required_coverage_missing', 'coverageKey': 'horizontal_pull'}],
        'coordinatedJointPlanning': {'status': 'infeasible', 'problemFingerprint': 'SOURCE_FP'}}
    _tool(messages, 'audit_workout_plan', draft, source, 'source-audit')
    failed_patch = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': []}
    invalid = {'passed': False, 'currentDraftId': 'REVISION_0',
        'errors': [{'code': 'invalid_draft_patch', 'path': '/', 'message': 'The patch is malformed.'}]}
    _tool(messages, 'audit_workout_plan', failed_patch, invalid, 'invalid-expansion')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['candidateMenuExpansionTask']['sourceProblemFingerprint'] == 'SOURCE_FP'
    assert state['candidateMenuExpansionTask']['submissionCorrectionErrors'] == invalid['errors']
    assert 'repairTask' not in state

    _tool(messages, 'audit_workout_plan', failed_patch, invalid, 'invalid-expansion-again')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['menuExpansionUnresolved']['status'] == 'unresolved'
    assert 'candidateMenuExpansionTask' not in state


def test_preparation_description_repair_is_compact_and_preserves_scope_after_rejection():
    from workout_generator_pkg.session_drafting import preparation_repair_task, resolve_preparation_patch
    from workout_generator_pkg.planning_tools import planning_tool_failure, PlanningInputError
    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None, 'name': 'Week', 'sessions': [
        {'name': name, 'description': 'x' * 45, 'trainingDays': [index * 2], 'timesCompletedInAWeek': 1,
         'exercises': [{'definition_id': 'LIBRARY_0', 'numWorkSets': 3, 'superset': None}]}
        for index, name in enumerate(('A', 'B'))]}
    errors = [{'code': 'export_description_too_long', 'path': f'/sessions/{i}/description'} for i in range(2)]
    _tool(messages, 'prepare_workout_sessions', arguments,
          {'passed': False, 'tool': 'prepare_workout_sessions', 'errors': errors}, 'prepare')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    task = state['preparationRepairTask']
    assert task['arguments'] == arguments
    assert 'exerciseCandidates' not in state and 'sourceMessages' not in state
    assert [item['maximumCharacters'] for item in task['metadataFields'].values()] == [32, 29]
    patch = {'basePreparationId': task['basePreparationId'], 'patch': [
        {'op': 'replace', 'path': f'/sessions/{i}/description', 'value': 'Short focus'} for i in range(2)]}
    fixed = resolve_preparation_patch(patch, messages)
    assert fixed['sessions'][0]['exercises'] == arguments['sessions'][0]['exercises']
    assert arguments['sessions'][0]['description'] == 'x' * 45
    changed = copy.deepcopy(patch)
    changed['patch'].append({'op': 'replace', 'path': '/sessions/0/exercises/0/definition_id', 'value': 'LIBRARY_2'})
    with pytest.raises(PlanningInputError) as caught:
        resolve_preparation_patch(changed, messages)
    _tool(messages, 'prepare_workout_sessions', changed,
          planning_tool_failure('prepare_workout_sessions', caught.value, changed), 'rejected')
    assert preparation_repair_task(messages) == task
    assert resolve_preparation_patch(patch, messages) == fixed
    messages.append({'role': 'user', 'content': 'Change the movement selection before preparing again.'})
    assert preparation_repair_task(messages) is None


def test_execution_and_evidence_findings_are_assessed_and_repaired_together():
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0']}, {
        'libraryFingerprint': library_fingerprint(equipment), 'exercises': [
            {'reference': 'LIBRARY_0', 'sessions': [{'performances': [{'record': {'actualReps': 10}}]}]}]}, 'history')
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'submittedDraft': draft,
        'currentDraftId': 'REVISION_0', 'errors': [
            {'code': 'independent_review_finding', 'path': '/draft', 'reviewScope': 'execution'},
            {'code': 'independent_review_finding', 'draftPath': '/workouts/0/exercises/0',
             'reviewScope': 'evidence', 'evidencePaths': ['/history/LIBRARY_0']}]}, 'audit')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['repairTask']['findingIndexes'] == [0, 1]
    assert 'LIBRARY_0' in state['trainingEvidence']


@pytest.mark.parametrize('linked_alternative', [False, True])
def test_connected_review_findings_share_one_repair_and_keep_needed_history(linked_alternative):
    from workout_generator_pkg.planning_tools import library_fingerprint, set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    base = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [{**base, 'id': f'd{i}', 'name': f'Movement {i}'} for i in range(2)]
    requirements['auditTargets'] = {'weeklyEffectiveSets': {}, 'perSessionEffectiveSets': {}, 'maximumSessionSeconds': 10000}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use the available movements.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'].append(copy.deepcopy(draft['workouts'][0]['exercises'][0]))
    draft['workouts'][0]['exercises'][1]['definition_id'] = 'LIBRARY_1'
    messages = requirement_messages(stored)
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0', 'LIBRARY_1']}, {
        'libraryFingerprint': library_fingerprint(equipment), 'exercises': [
            {'reference': f'LIBRARY_{i}', 'status': 'comparable_records', 'sessions': [
                {'performances': [{'record': {'actualReps': 10, 'note': f'EXACT-HISTORY-{i}'}}]}]} for i in range(2)]}, 'history')
    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed']
    errors = [
        {'code': 'independent_review_finding', 'path': '/draft', 'reviewScope': 'execution',
         'evidencePaths': ['/draft/exercises/0']},
        {'code': 'independent_review_finding', 'draftPath': '/workouts/0/exercises/0', 'reviewScope': 'evidence',
         'evidencePaths': ['/history/LIBRARY_0'] + (['/history/LIBRARY_1'] if linked_alternative else [])},
        {'code': 'independent_review_finding', 'path': '/draft/exercises/1', 'reviewScope': 'evidence',
         'evidencePaths': ['/history/LIBRARY_1']}]
    warning = {'path': '/draft', 'message': 'Advisory recovery concern.', 'basis': 'uncertainty', 'severity': 'warning'}
    findings = [{key:value for key,value in error.items() if key != 'code'} for error in errors] + [warning]
    _tool(messages, 'audit_workout_plan', draft, {**result, 'passed': False, 'errors': errors,
        'review': {'version': REVIEW_VERSION, 'findings': findings, 'scopeResults': {'execution': {'findings': findings}}}}, 'failed')
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['repairTask']['findingIndexes'] == [0, 1, 2]
    assert set(state['trainingEvidence']) == {'LIBRARY_0', 'LIBRARY_1'}
    assert 'EXACT-HISTORY-0' in json.dumps(state['trainingEvidence'])
    assert 'EXACT-HISTORY-1' in json.dumps(state)
    assert state['lastAudit']['errors'] == errors and state['currentDraft'] == _draft_with_references(draft) and messages == before
    assert state['lastAudit']['reviewWarnings'] == [warning]
    assert 'review' not in state['lastAudit']  # Cache internals and duplicate blockers are not author context.
    clarification = copy.deepcopy(errors)
    clarification[0]['action'] = 'clarify'
    _tool(messages, 'audit_workout_plan', draft, {**result, 'passed': False, 'errors': clarification}, 'clarify')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['planningDecisionNeeded'] and state['repairTask']['findingIndexes'] == [0]


def test_continue_replays_a_legacy_unfinished_model_submission_without_applying_it_early():
    from workout_generator_pkg.planner_context import pending_reaudit
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, initial, 'initial')
    submission = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Model-authored progression guidance.'}]}
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'unfinished', 'function': {
        'name': 'audit_workout_plan', 'arguments': json.dumps(submission)}}]},
        {'role': 'tool', 'tool_call_id': 'unfinished', 'content': 'Tool call started but did not complete.'},
        {'role': 'user', 'content': '/continue'}])
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['currentDraft'] == _draft_with_references(draft)
    assert pending_reaudit(state, '/continue') == submission
    messages.append({'role': 'user', 'content': 'Change my requirements instead.'})
    changed = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending_reaudit(changed, 'Change my requirements instead.') is None


def test_explicit_candidate_lookup_survives_numeric_repair_context_filtering():
    from workout_generator_pkg.exercise_library_tools import get_exercise_candidates
    equipment, _, stored, draft = planning_case()
    original = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [{**original, 'id': 'a'},
        {**original, 'id': 'b', 'name': 'Calf Raise', 'muscleGroups': ['BACK_CALVES'], 'secondaryMuscleGroups': []}]
    messages = requirement_messages(stored)
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'submittedDraft': draft,
        'currentDraftId': 'REVISION_0', 'errors': [
            {'code': 'volume_below_target', 'path': '/workouts', 'muscle': 'chest', 'scope': 'weekly'}]}, 'audit')
    arguments = {'definition_ids': ['LIBRARY_1']}
    result = get_exercise_candidates(arguments, equipment, messages)
    _tool(messages, 'get_exercise_candidates', arguments, result, 'candidate')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['exerciseCandidates']['LIBRARY_1']['name'] == 'Calf Raise'
    assert state['exerciseCandidates']['LIBRARY_1']['creditsPerWorkingSet']['calves']['direct'] == 1
    messages.append({'role': 'user', 'content': '/continue'})
    resumed = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert resumed['exerciseCandidates']['LIBRARY_1'] == state['exerciseCandidates']['LIBRARY_1']


@pytest.mark.parametrize('nested_text_value', [False, True])
def test_legacy_rejected_atomic_metadata_patch_remains_available_without_losing_other_repairs(nested_text_value):
    from workout_generator_pkg.planning_tools import PlanningInputError, planning_tool_failure, latest_draft_submission, validate_repair_scope
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, initial, 'initial')
    rejected = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': [
        {'op': 'replace', 'path': '/workouts/0/description', 'value': 'x' * 60},
        {'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Double progression: add reps then the smallest load increment.'}]}
    if nested_text_value:
        rejected['patch'][0] = {'op': 'replace', 'path': '/workouts/0',
                                'value': {**copy.deepcopy(draft['workouts'][0]), 'description': 'x' * 60}}
    # Retained rejection from the former export schema, not a new length failure.
    legacy_error = PlanningInputError('invalid_arguments', 'Legacy description limit.', '/workouts/0/description',
        'Correct this field.', errors=[{'code': 'invalid_arguments', 'validator': 'maxLength',
        'expected': 50, 'path': '/workouts/0/description'}])
    payload = planning_tool_failure('audit_workout_plan', legacy_error, rejected)
    assert payload['rejectedSubmission'] == rejected and 'submittedDraft' not in payload
    _tool(messages, 'audit_workout_plan', rejected, payload, 'rejected')
    assert latest_draft_submission(messages, equipment) == (draft, 'REVISION_0')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    task = state['repairTask']
    assert state['metadataOnlyRepair'] and 'currentDraft' not in state
    assert task['metadataFields']['/workouts/0/description']['text'] == 'x' * 60
    assert task['rejectedSubmission'] == rejected
    assert task['permittedPatchPaths'] == ['/workouts/0/description']
    correction = {**rejected, 'patch': [{'op': 'replace', 'path': '/workouts/0/description', 'value': 'Full body'}]}
    corrected = validate_repair_scope(correction, task)
    assert corrected['patch'][:2] == rejected['patch']
    assert len(corrected['patch']) == 3 and len(correction['patch']) == 1
    changed_other = {**correction, 'patch': [rejected['patch'][1]]}
    with pytest.raises(ValueError):
        validate_repair_scope(changed_other, task)
    discussion = _state(shell._messages_for_api(messages + [{'role':'user','content':'Explain the current problem.'}],
        True,provided_equipment=equipment))
    assert not discussion.get('metadataOnlyRepair') and discussion['currentDraft'] == _draft_with_references(draft)
    # A no-op retry must not erase the original, still-unapplied note repair.
    _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': []},
          {**initial, 'passed': False, 'errors': [{'code': 'independent_review_finding', 'path': '/draft', 'message': 'Progression missing'}]}, 'noop')
    resumed = _state(shell._messages_for_api(messages + [{'role': 'user', 'content': '/continue'}], True, provided_equipment=equipment))
    assert resumed['repairTask']['rejectedSubmission'] == rejected
    result = audit_workout_plan(corrected, equipment, messages)
    assert result['submittedDraft']['workouts'][0]['exercises'][0]['placementNotes'] == rejected['patch'][1]['value']
    _tool(messages, 'audit_workout_plan', corrected, result, 'corrected')
    final = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert not final.get('repairTask')


def test_local_session_duration_error_is_repaired_before_appending_next_session():
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['maximumSessionSeconds'] = 1
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Three sessions under one second each.'}], equipment)
    messages = requirement_messages(stored)
    draft['requirementsId'] = stored['requirementsId']
    result = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, result, 'slow-day')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert any(error['code'] == 'duration_exceeded' for error in state['lastAudit']['errors'])
    assert not state.get('constructionTask')
    assert state['repairTask']['findingCode'] == 'duration_exceeded'


def test_pending_evidence_is_scheduled_only_once_for_audit_requested_references():
    from workout_generator_pkg.planner_context import pending_evidence
    state = {'requirementsApproved': True, 'lastAudit': {'errors': [
        {'code': 'training_evidence_required', 'definition_ids': ['LIBRARY_1']},
        {'code': 'training_load_suitability_unresolved', 'path': '/workouts/0/exercises/0'}]},
        'currentDraft': {'workouts': [{'exercises': [{'definition_id': 'LIBRARY_2'}]}]},
        'trainingEvidence': {'LIBRARY_1': {'status': 'checked'}}}
    assert pending_evidence(state) == ['LIBRARY_2']
    state['attemptedEvidence'] = ['LIBRARY_2']
    assert pending_evidence(state) == []
    state['retryableEvidence'] = ['LIBRARY_2']
    assert pending_evidence(state) == []
    assert pending_evidence(state, '/continue') == ['LIBRARY_2']


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


@pytest.mark.parametrize('changed_authority', [False, True])
def test_reapproved_requirements_reaudit_only_when_authority_changed(changed_authority):
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import assessment_hash
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    approved = json.loads(next(m['content'] for m in messages if m.get('tool_call_id') == 'requirements'))
    result = audit_workout_plan(draft, equipment, messages)
    review = {'version': REVIEW_VERSION, 'inputHash': 'current-review', 'findings': []}
    review['assessment'] = {'version': ASSESSMENT_VERSION, 'inputHash': assessment_hash(review),
        'groups': [], 'repairPlan': ''}
    result['review'] = review
    _tool(messages, 'audit_workout_plan', draft, result, 'old-audit')
    if changed_authority:
        approved['requirementsId'] = 'REQUIREMENTS_changed'
    _tool(messages, 'set_workout_requirements', {}, approved, 'refresh')
    messages.extend([{'role': 'assistant', 'content': approved['requirementsPreview'], 'canonicalRequirementsPreview': approved['requirementsId']},
                     {'role': 'user', 'content': 'CONFIRM REQUIREMENTS'}])
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['requirementsApproved'] and state['lastAuditStale'] is changed_authority
    assert state['lastAudit']['draftId'] == result['draftId']
    if changed_authority:
        assert state['savedDraftReaudit'] == {'requirementsId': approved['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': []}
    else:
        assert not state.get('savedDraftReaudit')
    assert 'repairTask' not in state and messages == before


@pytest.mark.parametrize('fresh_preview', [False, True])
def test_pending_revision_survives_review_refresh_and_confirmation(fresh_preview):
    from workout_generator_pkg.review_assessment import assessment_hash
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft, equipment, messages)
    review = {'version': REVIEW_VERSION, 'inputHash': 'current-review', 'findings': []}
    review['assessment'] = {'version': ASSESSMENT_VERSION, 'inputHash': assessment_hash(review),
        'groups': [], 'repairPlan': ''}
    audited['review'] = review
    _tool(messages, 'audit_workout_plan', draft, audited, 'initial')
    messages.append({'role': 'assistant', 'content': 'Previous checked preview.',
                     'canonicalDraftPreview': audited['draftId']})
    instruction = 'Repair the latest draft against the saved fatigue findings.'
    messages.append({'role': 'user', 'content': instruction})
    _tool(messages, 'audit_workout_plan', {}, audited, 'refresh')
    messages.append({'role': 'user', 'content': 'CONFIRM REQUIREMENTS'})
    if fresh_preview:
        messages.append({'role': 'assistant', 'content': 'Updated checked preview.',
                         'canonicalDraftPreview': audited['draftId']})
    before = copy.deepcopy(messages)
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    state = _state(outgoing)
    if fresh_preview:
        assert 'pendingPreviewFollowup' not in state
    else:
        assert state['pendingPreviewFollowup'] == instruction
    assert messages == before


def test_legacy_metadata_shape_repair_preserves_the_semantic_correction():
    from workout_generator_pkg.planning_tools import PlanningInputError, planning_tool_failure
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft,equipment,messages)
    finding = {'code':'independent_review_finding','path':'/draft/exercises/0',
        'draftPath':'/workouts/0/exercises/0/placementNotes','message':'Fallback must preserve required volume.',
        'repair':'Require re-audit when reducing volume.','severity':'blocking','basis':'established_violation'}
    _tool(messages,'audit_workout_plan',draft,{**audited,'passed':False,'errors':[finding]},'semantic')
    patch = {'requirementsId':stored['requirementsId'],'baseDraftId':audited['currentDraftId'],
        'patch':[{'op':'replace','path':'/workouts/0/exercises/0/placementNotes','value':'x'*501}]}
    legacy_error = PlanningInputError('invalid_arguments', 'Legacy note limit.', '/workouts/0/exercises/0/placementNotes',
        'Correct this field.', errors=[{'code': 'invalid_arguments', 'validator': 'maxLength',
        'expected': 500, 'path': '/workouts/0/exercises/0/placementNotes'}])
    _tool(messages,'audit_workout_plan',patch,planning_tool_failure('audit_workout_plan',legacy_error,patch),'shape')
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages,True,provided_equipment=equipment))
    assert state['repairTask']['preserveFindings'] == [finding]
    assert state['repairTask']['permittedPatchPaths'] == ['/workouts/0/exercises/0/placementNotes']
    assert not state.get('savedDraftReaudit') and messages == before


@pytest.mark.parametrize('execution_failed', [False, True])
def test_stale_review_or_explicit_review_retry_can_reaudit_without_broad_planning(execution_failed):
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    result['review'] = {'version': REVIEW_VERSION if execution_failed else REVIEW_VERSION-1, 'findings': []}
    if not execution_failed:
        result['candidateMenuExpansion'] = {'version': 1, 'attempted': True,
            'auditedCandidate': True, 'sourceBaseDraftId': result['currentDraftId'],
            'sourceProblemFingerprint': None, 'blockers': [],
            'resultingProblemFingerprint': 'unbound-structural-edit'}
    if execution_failed:
        result['passed'] = False
        result['errors'] = [{'code': 'review_execution_failed', 'message': 'Temporary reviewer error.'}]
    _tool(messages, 'audit_workout_plan', draft, result, 'audit')
    messages.append({'role': 'user', 'content': '/continue'})
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['savedDraftReaudit']['patch'] == [] and 'repairTask' not in state
    if not execution_failed:
        assert not state.get('menuExpansionUnresolved')
        assert not state.get('candidateMenuExpansionTask')


def test_new_required_field_failure_routes_stale_draft_to_repair_once():
    from workout_generator_pkg.planning_tools import AUDIT_VERSION
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    old = audit_workout_plan(draft, equipment, messages)
    old['auditVersion'] = AUDIT_VERSION - 1
    old['review'] = {'version': REVIEW_VERSION, 'assessment': {'version': ASSESSMENT_VERSION}}
    _tool(messages, 'audit_workout_plan', draft, old, 'old-version')
    patch = {'requirementsId': stored['requirementsId'], 'baseDraftId': old['currentDraftId'], 'patch': []}
    _tool(messages, 'audit_workout_plan', patch, {'passed': False, 'tool': 'audit_workout_plan',
        'errors': [{'code': 'missing_effort_acceptance', 'path': '/workouts/0/exercises/0/effortAcceptance',
                    'repair': 'Provide the typed effort acceptance for this occurrence.'},
                   {'code': 'invalid_effort_acceptance', 'path': '/workouts/0/exercises/1/effortAcceptance',
                    'repair': 'Correct the typed effort acceptance for this occurrence.'}]}, 'new-field-failure')
    messages.append({'role': 'user', 'content': '/continue'})
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert not state.get('savedDraftReaudit')
    assert state['repairTask']['findingCode'] == 'missing_effort_acceptance'
    assert state['repairTask']['baseDraftId'] == old['currentDraftId']
    assert state['repairTask']['findingIndexes'] == [0, 1]


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
    assert not {'currentDraft', 'lastAudit', 'trainingEvidence', 'exerciseCandidates', 'allocationSlots'} & pending.keys()
    assert 'SAVED-DRAFT-ONLY' not in json.dumps(outgoing) and 'SAVED-HISTORY-ONLY' not in json.dumps(outgoing)
    assert messages == before
    messages.append({'role': 'user', 'content': 'CONFIRM REQUIREMENTS'})
    resumed = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert resumed['requirementsApproved'] and resumed['currentDraft'] == _draft_with_references(draft)
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
    snapshot = next(m['content'] for m in outgoing if m['content'].startswith('Requirement discussion state'))
    sources = json.loads(snapshot.split('\n', 1)[1])['sourceMessages']
    assert list(sources.values()) == messages[1:]
    assert not any(m['role'] in ('user', 'assistant') for m in outgoing)


def test_unrecorded_requirements_keep_latest_failure_without_replaying_tool_reasoning():
    messages = [{'role': 'user', 'content': 'Exclude only the conventional variation.'}]
    _tool(messages, 'set_workout_requirements', {'exerciseRestrictions': {'excludeNameTerms': ['Deadlift']}},
          {'passed': False, 'errors': [{'code': 'ambiguous_restriction_exception'}]}, 'first')
    _tool(messages, 'set_workout_requirements', {'exerciseRestrictions': {'excludeNameTerms': ['Barbell Deadlift']}},
          {'passed': False, 'errors': [{'code': 'unresolved_restriction'}]}, 'second')
    before = copy.deepcopy(messages)
    outgoing = shell._messages_for_api(messages, True)
    snapshot = next(m['content'] for m in outgoing if m['content'].startswith('Requirement discussion state'))
    discussion = json.loads(snapshot.split('\n', 1)[1])
    assert discussion['sourceMessages']['SOURCE_0']['content'] == messages[0]['content']
    assert discussion['proposedRequirements']['exerciseRestrictions']['excludeNameTerms'] == ['Barbell Deadlift']
    assert discussion['toolResults']['set_workout_requirements']['errors'] == [{'code': 'unresolved_restriction'}]
    assert 'old-reasoning-' not in json.dumps(outgoing)
    assert not any(m.get('tool_calls') or m['role'] == 'tool' for m in outgoing)
    assert messages == before


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
    assert state['currentDraft'] == _draft_with_references(draft)
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
    assert _state(outgoing)['currentDraft'] == _draft_with_references(draft)
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


@pytest.mark.parametrize('explicit_offset', [False, True])
@pytest.mark.parametrize('session_count,other_count,next_offset,totals,expected', [
    (3, 3, 3, (8, 8), 1),
    (1, 3, None, (4, 6), 4),
    (3, 1, 6, (8, 4), 4),
])
def test_resumed_mixed_setup_pages_share_one_correct_continuation_offset(
        explicit_offset, session_count, other_count, next_offset, totals, expected):
    from workout_generator_pkg.planner_context import _past_evidence
    item = {'sessions': [{'date': str(i)} for i in range(session_count)],
            'otherSetupSessions': [{'date': str(i)} for i in range(other_count)],
            'totalSessions': totals[0], 'otherSetupSessionCount': totals[1],
            'nextOffset': next_offset, 'hasMore': next_offset is not None}
    if explicit_offset:
        item['sessionOffset'] = expected - 1
    original = copy.deepcopy(item)
    result = _past_evidence(item)
    assert result['nextOffset'] == expected and result['hasMore']
    assert len(result['sessions']) == len(result['otherSetupSessions']) == 1
    assert item == original


def test_draft_snapshot_focuses_candidates_and_history_but_keeps_a_cached_alternative_index():
    from workout_generator_pkg.exercise_library_tools import _selection_entry
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, draft = planning_case()
    base = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [{**base, 'id': f'd{i}', 'name': f'Movement {i}'} for i in range(3)]
    entries = [_selection_entry(d, {}, f'LIBRARY_{i}') for i, d in enumerate(equipment['exerciseDefinitions'])]
    draft['workouts'][0]['exercises'][0].update(definition_id='LIBRARY_0', progressionPlan={
        'kind': 'reps', 'nextDefinitionId': 'LIBRARY_2', 'nextDefinitionName': 'Movement 2',
        'atCeilingAction': 're_audit_variant'})
    messages = requirement_messages(stored)
    _tool(messages, 'search_exercise_library', {'queries': ['push']},
          {'results': [{'query': 'push', 'exercises': entries}]}, 'discovery')
    evidence = [{'reference': f'LIBRARY_{i}', 'sessions': [{'performances': [{'record': {
        'actualReps': 10, 'note': f'HISTORY-MARKER-{i}'}}]}]} for i in range(3)]
    _tool(messages, 'get_training_evidence', {'definition_ids': [f'LIBRARY_{i}' for i in range(3)]},
          {'libraryFingerprint': library_fingerprint(equipment), 'exercises': evidence}, 'history')
    _tool(messages, 'audit_workout_plan', draft, {'submittedDraft': draft, 'currentDraftId': 'REVISION_0',
        'passed': False, 'errors': [{'code': 'prescription_error', 'path': '/workouts/0/exercises/0/targetSetPrescriptions'}]}, 'draft')
    messages[-2]['content'] = 'Old idea: search for a quad-only movement?'
    messages.append({'role': 'user', 'content': 'Repair the current draft using the audit.'})
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert set(state['exerciseCandidates']) == {'LIBRARY_0', 'LIBRARY_2'}
    assert set(state['cachedCandidateIndex']) == {'LIBRARY_1'}
    assert set(state['trainingEvidence']) == {'LIBRARY_0', 'LIBRARY_2'}
    assert 'lastAssistantMessage' not in state and 'HISTORY-MARKER-1' not in json.dumps(state)
    assert set(state['exerciseCandidates']['LIBRARY_2']) >= {
        'name', 'exerciseType', 'equipmentName', 'accessoryNames', 'exerciseCategory', 'creditsPerWorkingSet',
        'muscleGroups', 'secondaryMuscleGroups'}
    assert state['exerciseCandidates']['LIBRARY_2']['creditsPerWorkingSet'] == entries[2]['creditsPerWorkingSet']
    assert state['exerciseCandidates']['LIBRARY_2']['name'] == 'Movement 2'
    assert messages == before
    _tool(messages, 'search_exercise_library', {'queries': ['Movement 2']},
          {'results': [{'query': 'Movement 2', 'exercises': [entries[2]]}]}, 'targeted')
    active = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert set(active['exerciseCandidates']) == {'LIBRARY_0', 'LIBRARY_2'}
    assert set(active['trainingEvidence']) == {'LIBRARY_0', 'LIBRARY_2'}


@pytest.mark.parametrize('change', ['insert', 'edit'])
def test_cached_candidate_details_are_rejected_after_library_changes(change):
    from workout_generator_pkg.exercise_library_tools import get_exercise_candidates
    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    result = get_exercise_candidates({'definition_ids': ['LIBRARY_0']}, equipment, messages)
    _tool(messages, 'get_exercise_candidates', {'definition_ids': ['LIBRARY_0']}, result, 'details')
    fresh = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert fresh['exerciseCandidates']['LIBRARY_0']['name'] == result['exercises'][0]['name']
    changed = copy.deepcopy(equipment)
    if change == 'insert':
        changed['exerciseDefinitions'].insert(0, {**changed['exerciseDefinitions'][0],
            'id': 'aaa-new', 'name': 'New unrelated movement'})
    else:
        changed['exerciseDefinitions'][0]['bodyWeightPercentage'] = 80
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=changed))
    assert state['staleLibraryResults']
    assert 'LIBRARY_0' not in state['exerciseCandidates']
    assert messages == before


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
    messages.append({'role': 'user', 'content': '/continue'})
    before = copy.deepcopy(messages)
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    state = _state(outgoing)
    assert request_repair_task(outgoing) == state['repairTask']
    assert state['repairTask']['findingIndex'] == 0 and state['repairTask']['baseDraftId'] == 'REVISION_0'
    assert len(state['lastAudit']['errors']) == 2
    expected_first_workout = copy.deepcopy(draft['workouts'][0])
    expected_first_workout['reference'] = 'WORKOUT_0'
    expected_first_workout['exercises'][0]['reference'] = 'EXERCISE_0'
    assert state['currentDraft']['workouts'][0] == expected_first_workout
    assert state['currentDraft']['workouts'][1]['detailsOmitted']
    assert state['currentDraft']['workouts'][1]['reference'] == 'WORKOUT_1'
    assert state['currentDraft']['workouts'][1]['exerciseSummary'][0]['reference'] == 'EXERCISE_1'
    assert 'Call get_workout_draft' in state['repairTask']['instruction']
    assert len(state['allocationSlots']) == 2
    assert state['requirements'] == stored['requirements'] and state['sourceMessages']['SOURCE_0']['content'] == messages[0]['content']
    assert set(state['exerciseCandidates']) == {'LIBRARY_0'}
    assert set(state['cachedCandidateIndex']) == {'LIBRARY_1', 'LIBRARY_2'}
    assert set(state['trainingEvidence']) == {'LIBRARY_0'}
    assert state['trainingEvidenceSummary']['LIBRARY_1']['status'] == 'comparable_records'
    assert 'SAVED-DETAILS-1' not in json.dumps(outgoing) and 'SAVED-DETAILS-2' not in json.dumps(outgoing)
    assert messages == before
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_2']},
          {'libraryFingerprint': library_fingerprint(equipment), 'exercises': [evidence[2]]}, 'requested-detail')
    requested = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert 'SAVED-DETAILS-2' in json.dumps(requested['trainingEvidence']['LIBRARY_2'])
    assert 'LIBRARY_2' in requested['exerciseCandidates']


def test_failed_or_missing_evidence_retries_only_after_a_new_user_turn():
    from workout_generator_pkg.planning_tools import library_fingerprint
    from workout_generator_pkg.planner_context import pending_evidence
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'errors': [
        {'code': 'training_evidence_required', 'definition_ids': ['LIBRARY_0']}]}, 'audit')
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0']},
          {'errors': ['history store unavailable']}, 'failed-history')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending_evidence(state) == []
    messages.append({'role': 'user', 'content': '/continue'})
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending_evidence(state, '/continue') == ['LIBRARY_0']
    _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0']},
          {'libraryFingerprint': library_fingerprint(equipment), 'exercises': []}, 'missing-history')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending_evidence(state) == []
    assert pending_evidence(state, '/continue') == []


def test_repair_snapshot_omits_duplicate_audit_errors_and_carries_allocator_work_order():
    from workout_generator_pkg.exercise_library_tools import _selection_entry
    equipment, _, stored, draft = planning_case()
    base = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [
        {**base, 'id': 'd0'}, {**base, 'id': 'd1'},
        {**base, 'id': 'd2', 'muscleGroups': ['FRONT_QUADRICEPS'], 'secondaryMuscleGroups': []}]
    messages = requirement_messages(stored)
    entries = [_selection_entry(d, {}, f'LIBRARY_{i}') for i, d in enumerate(equipment['exerciseDefinitions'])]
    _tool(messages, 'search_exercise_library', {'queries': ['alternatives']},
          {'results': [{'query': 'alternatives', 'exercises': entries}]}, 'search')
    _tool(messages, 'audit_workout_plan', draft, {'passed': False, 'errors': [
        {'code': 'volume_below_target', 'scope': 'weekly', 'muscle': 'chest'}],
        'currentDraftId': 'REVISION_0', 'submittedDraft': draft}, 'audit')
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    state = _state(outgoing)
    assert 'currentDraftAuditErrors' not in state
    assert state['lastAudit']['errors'][0]['muscle'] == 'chest'
    assert state['repairTask']['omittedWorkoutReferences'] == []
    assert 'All currentDraft sessions are supplied in full' in state['repairTask']['instruction']
    assert 'Call get_workout_draft' not in state['repairTask']['instruction']
    assert set(state['cachedCandidateIndex']) == {'LIBRARY_1'}
    assert state['availableAlternativeCountByMuscle']['chest'] == 1
    assert 'Python considers every movable slot using approved count limits' in state['repairTask']['instruction']
    assert 'do not repeat allocate_workout_sets with different preferences' in state['repairTask']['instruction']
    assert 'supply complete allowed minimum and maximum bounds' not in state['repairTask']['instruction']


def test_matching_count_conflict_routes_to_movement_repair_and_surfaces_affected_alternatives(monkeypatch):
    from workout_generator_pkg.allocation import allocation_input_fingerprint
    equipment, _, stored, draft = planning_case()
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0],
        'id': 'shoulder-raise', 'name': 'Shoulder Raise', 'muscleGroups': ['FRONT_DELTOIDS'],
        'secondaryMuscleGroups': []})
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    messages = requirement_messages(stored)
    audit = audit_workout_plan(draft, equipment, messages)
    assert not audit['passed']
    _tool(messages, 'audit_workout_plan', draft, audit, 'audit')
    conflict = {'status': 'infeasible', 'scope': 'count_allocation_for_current_draft',
        'requirementsId': stored['requirementsId'], 'baseDraftId': audit['currentDraftId'],
        'conflictFingerprint': allocation_input_fingerprint(draft, stored['requirementsId'], equipment,
            requirements=stored['requirements']),
        'inputFingerprint': allocation_input_fingerprint(draft, stored['requirementsId'], equipment,
            requirements=stored['requirements']),
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'resolvedDecisions': {}, 'allowEducatedLoadGuesses': True,
        'conflictingTargets': [{'target': 'weekly:shoulders', 'minimum': 0, 'maximum': 0,
            'rangeWithinSlotBounds': [1, 20]}]}
    _tool(messages, 'allocate_workout_sets', {'requirementsId': stored['requirementsId'],
        'baseDraftId': audit['currentDraftId'], 'preferredSetsBySlot': {'SLOT_0': 5}},
        {'feasible': False, 'status': 'infeasible', 'requirementsId': stored['requirementsId'],
         'baseDraftId': audit['currentDraftId'], 'allocationConflict': conflict}, 'allocation')
    _tool(messages, 'allocate_workout_sets', {'preferredSetsBySlot': 'invalid'},
        {'passed': False, 'errors': [{'code': 'invalid_arguments'}]}, 'bad-allocation')
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    state = _state(outgoing)
    task = state['repairTask']
    assert task['allocationConflict'] == conflict
    assert task['allocationNeedsStructuralChange'] and not task['structuralAllocationAvailable']
    assert 'movement-level change' in task['instruction']
    assert state['availableAlternativeCountByMuscle']['shoulders'] == 1
    assert state['candidateMenuExpansionTask']['proofScope'] == 'exercise_selection_repair'
    assert state['candidateMenuExpansionTask']['sourceConflictFingerprint'] == conflict['conflictFingerprint']
    assert state['candidateMenuExpansionTask']['stage'] == 'discover_candidates'
    allowed = shell._candidate_menu_expansion_tools([
        {'function': {'name': name}} for name in ('search_exercise_library', 'get_exercise_candidates',
            'audit_workout_plan', 'propose_workout_alternatives', 'allocate_workout_sets')],
        state['candidateMenuExpansionTask'])
    assert {item['function']['name'] for item in allowed} == {'search_exercise_library'}

    searched_messages = copy.deepcopy(messages)
    candidate = equipment['exerciseDefinitions'][-1]
    from workout_generator_pkg.exercise_library_tools import _selection_entry
    entry = _selection_entry(candidate, {}, 'LIBRARY_1')
    _tool(searched_messages, 'search_exercise_library', {'queries': ['eligible shoulder alternative']},
        {'libraryFingerprint': library_fingerprint(equipment), 'results': [
            {'query': 'eligible shoulder alternative', 'exercises': [entry]}]}, 'targeted-search')
    searched_state = _state(shell._messages_for_api(searched_messages, True, provided_equipment=equipment))
    assert searched_state['candidateMenuExpansionTask']['stage'] == 'choose_candidate'
    allowed = shell._candidate_menu_expansion_tools([
        {'function': {'name': name}} for name in ('search_exercise_library', 'get_exercise_candidates',
            'audit_workout_plan', 'propose_workout_alternatives', 'allocate_workout_sets')],
        searched_state['candidateMenuExpansionTask'])
    assert {item['function']['name'] for item in allowed} == {
        'audit_workout_plan', 'propose_workout_alternatives'}

    from workout_generator_pkg import conflict_resolution
    from workout_generator_pkg.interactive_shell import handle_function_call
    captured = {}
    def capture_diagnosis(**kwargs):
        captured.update(kwargs)
        return {'outcome': 'unresolved', 'reason': 'No validated proposal in this routing test.'}
    monkeypatch.setattr(conflict_resolution, 'diagnose_conflict_and_propose', capture_diagnosis)
    result = handle_function_call(None, messages, 'propose_workout_alternatives', {
        'requirementsId': stored['requirementsId'], 'baseDraftId': audit['currentDraftId']},
        provided_equipment=equipment)
    assert json.loads(result['result'])['outcome'] == 'unresolved'
    assert captured['allocation_conflict']['conflictFingerprint'] == conflict['conflictFingerprint']
    assert captured['existing_conflict'] is None


def test_review_selection_repair_uses_same_no_search_then_atomic_choice_stage():
    equipment, _, stored, draft = planning_case()
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0],
        'id': 'alternative', 'name': 'Alternative', 'muscleGroups': ['FRONT_DELTOIDS'],
        'secondaryMuscleGroups': []})
    messages = requirement_messages(stored)
    audit = audit_workout_plan(draft, equipment, messages)
    audit.update(passed=False, errors=[{'code': 'required_coverage_missing', 'coverageKey': 'upper_back'}])
    _tool(messages, 'audit_workout_plan', draft, audit, 'selection-audit')
    from workout_generator_pkg.exercise_library_tools import _selection_entry
    entry = _selection_entry(equipment['exerciseDefinitions'][-1], {}, 'LIBRARY_1')
    _tool(messages, 'search_exercise_library', {'queries': ['upper back eligible movement']},
        {'libraryFingerprint': library_fingerprint(equipment), 'results': [
            {'query': 'upper back eligible movement', 'exercises': [entry]}]}, 'selection-search')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    task = state['candidateMenuExpansionTask']
    assert task['proofScope'] == 'exercise_selection_repair'
    assert task['sourceConflictFingerprint'] is None
    assert task['stage'] == 'choose_candidate'
    from workout_generator_pkg.interactive_shell import _candidate_menu_expansion_attempt, _candidate_menu_expansion_audit_marker
    assert _candidate_menu_expansion_attempt(task) is None
    assert _candidate_menu_expansion_audit_marker(task, {'currentDraftId': 'REVISION_1',
        'submittedDraft': draft, 'coordinatedJointPlanning': {'status': 'feasible',
            'problemFingerprint': 'CURRENT_FP'}}, {'edits': {'exerciseUpdates': []}}) is None
    allowed = shell._candidate_menu_expansion_tools([
        {'function': {'name': name}} for name in ('search_exercise_library', 'audit_workout_plan',
            'propose_workout_alternatives')], task)
    assert {item['function']['name'] for item in allowed} == {'audit_workout_plan', 'propose_workout_alternatives'}


def test_selection_search_with_no_candidates_stops_as_unresolved():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audit = audit_workout_plan(draft, equipment, messages)
    audit.update(passed=False, errors=[{'code': 'required_coverage_missing', 'coverageKey': 'upper_back'}])
    _tool(messages, 'audit_workout_plan', draft, audit, 'selection-audit')
    _tool(messages, 'search_exercise_library', {'queries': ['eligible upper back movement']},
        {'libraryFingerprint': library_fingerprint(equipment), 'results': [
            {'query': 'eligible upper back movement', 'exercises': []}]}, 'empty-selection-search')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert not state.get('candidateMenuExpansionTask')
    assert state['structuralRepairUnresolved']['status'] == 'unresolved'
    assert 'do not claim global impossibility' in next(message['content'] for message in shell._messages_for_api(
        messages, True, provided_equipment=equipment) if message['content'].startswith('Current planning state'))


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


def test_legacy_calibration_patch_preserves_other_edits_without_reintroducing_protocol():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, initial, 'initial')
    request = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': [
        {'op': 'replace', 'path': '/workouts/0/description', 'value': 'Updated focus'},
        {'op': 'add', 'path': '/workouts/0/exercises/0/requiresEffortCalibration', 'value': True},
        {'op': 'add', 'path': '/workouts/0/exercises/0/calibrationAttempts', 'value': 3},
        {'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Keep the torso steady.'}]}
    result = audit_workout_plan(request, equipment, messages)
    assert result['passed'], result['errors']
    submitted = result['submittedDraft']
    assert submitted['workouts'][0]['description'] == 'Updated focus'
    item = submitted['workouts'][0]['exercises'][0]
    assert item['placementNotes'] == 'Keep the torso steady.'
    assert 'requiresEffortCalibration' not in item and 'calibrationAttempts' not in item
    assert 'trial' not in result['preview'].lower()
