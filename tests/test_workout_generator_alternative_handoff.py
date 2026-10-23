import copy
import json
from types import SimpleNamespace

import pytest

from workout_generator_pkg import conflict_resolution, interactive_shell, plan_review, planning_tools
from test_workout_generator_planning_tools import planning_case


@pytest.mark.parametrize('disposition', ['repair', 'unresolved_capability'])
def test_diagnosis_continues_only_supported_alternative_repairs(monkeypatch, disposition):
    equipment, _, stored, draft = planning_case()
    monkeypatch.setattr(planning_tools, 'require_approved_requirements', lambda *_: None)
    monkeypatch.setattr(interactive_shell, 'require_approved_requirements', lambda *_: None)
    monkeypatch.setattr(interactive_shell, '_latest_result', lambda *_: (0, stored))
    monkeypatch.setattr(planning_tools, 'latest_draft_submission', lambda *_: (copy.deepcopy(draft), 'SOURCE'))
    monkeypatch.setattr(planning_tools, 'render_draft', lambda *_: 'Unapproved alternative')
    review = {'version': plan_review.REVIEW_VERSION,
        'findings': [{'severity': 'warning', 'message': 'Repair the setup cue.'}],
        'assessment': {'groups': [{'findingIndexes': [0], 'disposition': disposition,
            'repairDimensions': ['guidance'] if disposition == 'repair' else []}]}}
    monkeypatch.setattr(interactive_shell, 'review_draft', lambda *_: {
        'passed': False, 'review': review, 'errors': [{'code': 'independent_review_finding'}]})

    def diagnose(**kwargs):
        kwargs['review_candidate'](copy.deepcopy(draft['workouts']), stored['requirements'],
            {'audit': {'errors': []}})
        return {'outcome': 'unresolved', 'reason': 'No reviewed proposal yet.',
            'diagnosisDeadlineUTC': '2099-01-01T00:00:00Z'}

    monkeypatch.setattr(conflict_resolution, 'diagnose_conflict_and_propose', diagnose)
    response = interactive_shell.handle_function_call(None, [], 'propose_workout_alternatives',
        {'requirementsId': stored['requirementsId'], 'baseDraftId': 'SOURCE'},
        provided_equipment=equipment, deps=SimpleNamespace(execute_workout_generation=None))
    result = json.loads(response['result'])
    assert result['passed'] is False
    assert len(result['alternativeRepairCandidates']) == 1
    assert result['jointPlanningStopped'] is (disposition != 'repair')
    if disposition == 'repair':
        assert 'coordinated repair' in result['instruction']
        assert result['errors'] == [{'code': 'independent_review_finding'}]
    assert not result.get('proposals')


@pytest.mark.parametrize('stale_source_audit', [False, True])
@pytest.mark.parametrize('structural_failure', [False, True])
def test_candidate_conflict_diagnosis_uses_exact_saved_failed_menu_and_materialized_guidance(
        monkeypatch, stale_source_audit, structural_failure):
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from workout_generator_pkg import joint_planning
    from workout_generator_pkg.joint_planning import (SELECTION_POLICY_VERSION, candidate_menu_fingerprint,
        joint_problem_fingerprint)
    from workout_generator_pkg.planning_decisions import resolved_decisions
    from workout_generator_pkg.planning_tools import (_fingerprint, audit_workout_plan,
        library_fingerprint, set_workout_requirements)
    from workout_generator_pkg.restriction_policy import effective_restrictions

    equipment, requirements, stored, draft = planning_case()
    requirements['auditTargets']['weeklyEffectiveSets'] = {'chest': {'minimum': 2, 'maximum': 6}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['requirementAccounting'] = [{
        'instruction': 'Negotiable chest minimum', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': ['/auditTargets/weeklyEffectiveSets/chest'], 'priority': 'negotiable',
        'relaxationDirection': 'lower_minimum', 'enforcement': 'constraint',
        'reason': 'The source permits lowering this minimum.'}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Plan chest work.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft, equipment, messages)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'source-audit', 'type': 'function',
            'function': {'name': 'audit_workout_plan', 'arguments': json.dumps(draft)}}]},
        {'role': 'tool', 'tool_call_id': 'source-audit', 'content': json.dumps(audited)},
    ])
    menu = copy.deepcopy(draft['workouts'])
    history_fingerprint = 'current-history' if structural_failure else None
    history = SimpleNamespace(fingerprint=history_fingerprint) if history_fingerprint else None
    candidate = {'repairCandidateId': 'REVISION_CONFLICT_ROUTE',
        'originalRequirementsId': stored['requirementsId'],
        'originalRequirementsHash': _fingerprint(stored['requirements']),
        'requirementsId': 'ALT_REQUIREMENTS_ROUTE', 'requirements': copy.deepcopy(stored['requirements']),
        'sourceDraftId': audited['currentDraftId'], 'baseDraftId': audited['currentDraftId'],
        'sourceMenuFingerprint': candidate_menu_fingerprint(menu),
        'candidateMenuFingerprint': candidate_menu_fingerprint(menu), 'workouts': menu,
        'candidateName': 'Saved alternative', 'programGuidance': 'Keep recovery adjustments manual.',
        'restrictionPolicy': effective_restrictions(stored, equipment),
        'libraryFingerprint': library_fingerprint(equipment), 'trainingHistoryFingerprint': history_fingerprint,
        'resolvedDecisions': {}}
    if structural_failure:
        candidate['requirements']['requiredCoverage'] = [
            {'key': 'press', 'scope': 'eachSession', 'description': 'Pressing movement'}]
        for workout in candidate['workouts']:
            workout['exercises'][0]['satisfiesCoverage'] = ['press']
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'saved-alternatives', 'type': 'function',
            'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'saved-alternatives', 'content': json.dumps({
            'outcome': 'candidate_feasible_pending_review', 'requirementsId': stored['requirementsId'],
            'baseDraftId': audited['currentDraftId'], 'alternativeRepairCandidates': [candidate]})},
    ])
    decision = {'topic': 'Fixture decision', 'choice': 'Use the approved fixture interpretation.',
        'sourceReferences': ['SOURCE_0']}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'saved-decision', 'type': 'function',
            'function': {'name': 'record_planning_decisions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'saved-decision', 'content': json.dumps({'passed': True,
            'decisionReview': {'passed': True}, 'decisions': {'DECISION_0': decision}})},
    ])
    current_decisions = resolved_decisions(messages)
    fresh_audit = audit_workout_plan(draft, equipment, messages)
    fresh_audit['resolvedDecisions'] = current_decisions
    if stale_source_audit:
        fresh_audit['requirementsId'] = 'REQUIREMENTS_BEFORE_PERMISSION_CHANGE'
        fresh_audit['submittedDraft']['requirementsId'] = fresh_audit['requirementsId']
        fresh_audit['draftId'] = 'DRAFT_BEFORE_PERMISSION_CHANGE'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'source-audit-current', 'type': 'function',
            'function': {'name': 'audit_workout_plan', 'arguments': json.dumps(draft)}}]},
        {'role': 'tool', 'tool_call_id': 'source-audit-current', 'content': json.dumps(fresh_audit)},
    ])
    submitted_menu = copy.deepcopy(menu)
    submitted_menu[0]['exercises'][0]['numWorkSets'] = 4
    from workout_generator_pkg.json_patching import apply_json_patch
    repair_operations = [{'op': 'add', 'path': '/programGuidance',
        'value': 'Keep recovery adjustments manual.'},
        {'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 4}]
    materialized_patch = apply_json_patch({'requirementsId': candidate['requirementsId'],
        'name': candidate['candidateName'], 'workouts': candidate['workouts'],
        'programGuidance': candidate['programGuidance']}, repair_operations)
    assert materialized_patch['workouts'] == submitted_menu
    failed_menu = copy.deepcopy(submitted_menu)
    failed_menu[0]['exercises'][0]['numWorkSets'] = 3
    if structural_failure:
        failed_menu[0]['exercises'][0].pop('satisfiesCoverage', None)
    submitted_fingerprint = candidate_menu_fingerprint(failed_menu)
    problem_fingerprint = joint_problem_fingerprint(failed_menu, candidate['requirements'], equipment,
        history, messages, restriction_policy=candidate['restrictionPolicy'], allow_educated_load_guesses=True,
        preserve_source_selection=True)
    repair_result = {'passed': False, 'outcome': 'unresolved', 'attemptStatus': 'repair_menu_infeasible',
        'repairCandidateId': candidate['repairCandidateId'],
        'originalRequirementsId': stored['requirementsId'], 'requirementsId': candidate['requirementsId'],
        'baseDraftId': audited['currentDraftId'], 'candidateSnapshot': {
            **copy.deepcopy(candidate), 'resolvedDecisions': copy.deepcopy(current_decisions)},
        'requirements': copy.deepcopy(candidate['requirements']), 'workouts': failed_menu,
        'submittedMenuFingerprint': submitted_fingerprint, 'repairOperations': repair_operations,
        'libraryFingerprint': candidate['libraryFingerprint'], 'trainingHistoryFingerprint': history_fingerprint,
        'jointSolve': {'status': 'infeasible', 'problemFingerprint': problem_fingerprint,
            'preserveSourceSelection': True, 'selectionPolicyVersion': SELECTION_POLICY_VERSION,
            'feasibilityDomainFingerprint': 'domain-route-test'},
        'errors': [{'code': 'joint_menu_infeasible'}]}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'saved-repair', 'type': 'function',
            'function': {'name': 'repair_workout_alternative', 'arguments': json.dumps({
                'repairCandidateId': candidate['repairCandidateId'],
                'originalRequirementsId': stored['requirementsId']})}}]},
        {'role': 'tool', 'tool_call_id': 'saved-repair', 'content': json.dumps(repair_result)},
    ])
    solver_calls = []
    def solve_saved_menu(workouts, variant, *_args, **_kwargs):
        solver_calls.append(copy.deepcopy(variant))
        minimum = variant['auditTargets']['weeklyEffectiveSets']['chest']['minimum']
        if minimum > 1:
            return {'feasible': False, 'status': 'infeasible'}
        audit_report = copy.deepcopy(audited['audit'])
        audit_report['weeklyVolume']['chest']['effective'] = 1
        return {'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(workouts),
            'audit': audit_report}
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve_saved_menu)
    monkeypatch.setattr(interactive_shell, 'review_draft', lambda *_args, **_kwargs: {
        'passed': True, 'preview': 'Validated candidate preview.',
        'review': {'version': plan_review.REVIEW_VERSION, 'findings': []}})
    response = interactive_shell.handle_function_call(None, messages, 'propose_workout_alternatives', {
        'requirementsId': stored['requirementsId'], 'baseDraftId': audited['currentDraftId'],
        'repairCandidateId': candidate['repairCandidateId'], 'submittedMenuFingerprint': submitted_fingerprint,
        'feasibilityDomainFingerprint': 'domain-route-test'}, provided_equipment=equipment,
        deps=SimpleNamespace(execute_workout_generation=None), training_history=history)

    result = json.loads(response['result'])
    if structural_failure:
        assert result['attemptStatus'] == 'structural_menu_repair_required'
        assert result['outcome'] == 'unresolved'
        assert result['errors'][0]['owner'] == 'structural_repair'
        assert result['libraryFingerprint'] == candidate['libraryFingerprint']
        assert 'historyFingerprint' in result
        assert result['historyFingerprint'] == history_fingerprint
        assert result['alternativeRepairCandidates'] == [candidate]
        assert result['jointPlanningStopped'] is False
        assert not solver_calls
        assert not result.get('proposals')
        assert 'Repair that menu first' in result['instruction']
        preserved = messages + [
            {'role': 'assistant', 'tool_calls': [{'id': 'structural-response', 'type': 'function',
                'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'structural-response', 'content': json.dumps(result)}]
        sanitized = interactive_shell._sanitize_stale_history_receipts(preserved, history_fingerprint, True)
        assert json.loads(sanitized[-1]['content']) == result
        mismatched = copy.deepcopy(preserved)
        inconsistent = copy.deepcopy(result)
        inconsistent['alternativeRepairCandidates'][0]['trainingHistoryFingerprint'] = 'other-history'
        mismatched[-1]['content'] = json.dumps(inconsistent)
        rejected = interactive_shell._sanitize_stale_history_receipts(mismatched, history_fingerprint, True)
        assert json.loads(rejected[-1]['content'])['staleHistory'] is True
        return
    assert result['outcome'] == 'alternatives_ready', (result.get('reason'),
        [attempt for attempt in result.get('attempts', []) if attempt.get('scenario') == 'independent_review'])
    assert solver_calls and solver_calls[0]['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] == 0
    assert result['candidateDiagnosisSource']['feasibilityDomainFingerprint'] == 'domain-route-test'
    assert result['candidateDiagnosisCandidate']['resolvedDecisions'] == current_decisions
    assert result['sourceValidation']['requirementsId'] == stored['requirementsId']
    assert result['sourceValidation']['sourceDraftId'] == audited['currentDraftId']
    assert result['sourceValidation']['resolvedDecisions'] == current_decisions
    assert result['sourceValidation']['libraryFingerprint'] == library_fingerprint(equipment)
    assert planning_tools.latest_draft_submission(messages, equipment)[1] == audited['currentDraftId']
    assert planning_tools._latest_result(messages, 'audit_workout_plan')[1] == fresh_audit
    assert result['proposals'][0]['programGuidance'] == 'Keep recovery adjustments manual.'
    assert result['proposals'][0]['candidateDiagnosisSource'] == result['candidateDiagnosisSource']
    assert result['proposals'][0]['changes'][0]['from'] == 2
    assert result['proposals'][0]['shortfallsAgainstOriginalRequirements']

    stale_candidate_messages = copy.deepcopy(messages)
    saved = next(item for item in stale_candidate_messages if item.get('tool_call_id') == 'saved-alternatives')
    stale_payload = json.loads(saved['content'])
    stale_payload['alternativeRepairCandidates'][0]['originalRequirementsHash'] = 'previous-requirements-hash'
    saved['content'] = json.dumps(stale_payload)
    with pytest.raises(ValueError, match='no longer matches'):
        interactive_shell.handle_function_call(None, stale_candidate_messages, 'propose_workout_alternatives', {
            'requirementsId': stored['requirementsId'], 'baseDraftId': audited['currentDraftId'],
            'repairCandidateId': candidate['repairCandidateId'], 'submittedMenuFingerprint': submitted_fingerprint,
            'feasibilityDomainFingerprint': 'domain-route-test'}, provided_equipment=equipment,
            deps=SimpleNamespace(execute_workout_generation=None))

    with pytest.raises(ValueError, match='only the saved candidate'):
        interactive_shell.handle_function_call(None, messages, 'propose_workout_alternatives', {
            'requirementsId': stored['requirementsId'], 'baseDraftId': audited['currentDraftId'],
            'repairCandidateId': candidate['repairCandidateId'], 'submittedMenuFingerprint': submitted_fingerprint,
            'feasibilityDomainFingerprint': 'domain-route-test', 'workouts': menu}, provided_equipment=equipment,
            deps=SimpleNamespace(execute_workout_generation=None))
