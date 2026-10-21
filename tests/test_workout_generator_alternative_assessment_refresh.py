import copy
import datetime as dt
import json
from types import SimpleNamespace

import pytest

from workout_generator_pkg import alternative_repair, interactive_shell
from workout_generator_pkg.review_assessment import assessment_hash, validate_assessment


def _assessment(review, version):
    assessment = {'version': version,
        'inputHash': assessment_hash(review),
        'groups': ([{'findingIndexes': list(range(len(review.get('findings', [])))),
                    'disposition': 'repair', 'repairDimensions': ['guidance'],
                    'reason': 'Repair the saved guidance finding.'}]
                   if review.get('findings') else []),
        'repairPlan': 'Repair the saved guidance finding.'}
    return assessment


@pytest.mark.parametrize(('review_passed', 'review_failed'), [(False, False), (True, False), (False, True)])
def test_resume_refreshes_only_saved_alternative_assessment_without_rediagnosing(monkeypatch, review_passed, review_failed):
    import workout_generator_pkg.conflict_resolution as conflict_resolution
    import workout_generator_pkg.plan_review as plan_review
    import workout_generator_pkg.planning_tools as planning_tools
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION

    old_findings = [{'severity': 'warning', 'message': f'Saved finding {index}.'}
        for index in range(32)]
    old_review = {'version': REVIEW_VERSION, 'inputHash': 'saved-review', 'findings': old_findings}
    old_review['assessment'] = _assessment(old_review, ASSESSMENT_VERSION - 1)
    # An old assessment with repair dimensions still needs current reassessment.
    assert 'repairDimensions' in old_review['assessment']['groups'][0]
    try:
        validate_assessment(old_review)
    except ValueError:
        pass
    else:
        raise AssertionError('the saved old-version assessment must be stale')

    candidate = {'repairCandidateId': 'REVISION_123', 'originalRequirementsId': 'REQ_ORIGINAL',
        'originalRequirementsHash': 'requirements-hash', 'sourceDraftId': 'DRAFT_7',
        'baseDraftId': 'DRAFT_7', 'requirementsId': 'REQ_ALT', 'requirements': {'auditTargets': {}},
        'workouts': [{'name': 'Saved alternative', 'exercises': []}], 'candidateName': 'Saved alternative',
        'changes': [{'path': '/volume', 'from': 12, 'to': 8}], 'restrictionPolicy': {},
        'libraryFingerprint': 'library', 'trainingHistoryFingerprint': None, 'resolvedDecisions': {},
        'sourceMenuFingerprint': 'source-menu', 'candidateMenuFingerprint': 'alternative-menu',
        'reviewVersion': REVIEW_VERSION, 'audit': {'errors': []},
        'review': old_review, 'reviewFindings': copy.deepcopy(old_findings),
        'findingsAssessment': copy.deepcopy(old_review['assessment']),
        'diagnosisDeadlineUTC': (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')}
    from workout_generator_pkg.conflict_resolution import CONFLICT_RESOLUTION_VERSION
    diagnosis = {'outcome': 'unresolved', 'requirementsId': 'REQ_ORIGINAL', 'baseDraftId': 'DRAFT_7',
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION, 'diagnosisDeadlineUTC': candidate['diagnosisDeadlineUTC'],
        'jointPlanningStopped': True, 'errors': [{'code': 'joint_diagnosis_unresolved'}],
        'instruction': 'Stop the exhausted diagnosis.',
        'alternativeRepairCandidates': [candidate]}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'saved-diagnosis', 'type': 'function',
            'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'saved-diagnosis', 'content': json.dumps(diagnosis)},
    ]
    fresh_findings = [{'severity': 'warning', 'message': f'Current finding {index}.'}
        for index in range(35)]
    fresh_assessment_review = {'version': REVIEW_VERSION, 'inputHash': 'fresh-review',
        'findings': fresh_findings}
    fresh_assessment_review['assessment'] = _assessment(fresh_assessment_review, ASSESSMENT_VERSION)
    if review_failed:
        fresh_assessment_review.update(failure='Invalid confirmation output.', failureStage='independent_review_confirmation',
            confirmationProgress={'inputHash': 'fresh-review', 'outcomes': {'execution': {'completed': True}}})

    monkeypatch.setattr(interactive_shell, '_latest_result', lambda *_args: (-1, diagnosis))
    monkeypatch.setattr(planning_tools, '_latest_result', lambda *_args: (-1, {
        'requirementsId': 'REQ_ORIGINAL', 'requirements': {'auditTargets': {}}, 'restrictionPolicy': {}}))
    monkeypatch.setattr(alternative_repair, '_latest_result', lambda *_args: (-1, {
        'requirementsId': 'REQ_ORIGINAL', 'requirements': {'auditTargets': {}}, 'restrictionPolicy': {}}))
    monkeypatch.setattr(interactive_shell, 'require_approved_requirements', lambda *_args: None)
    monkeypatch.setattr(planning_tools, 'require_approved_requirements', lambda *_args: None)
    monkeypatch.setattr(alternative_repair, '_fresh_binding', lambda *_args: True)
    audited_names = []
    def audit_saved_candidate(saved, *_args):
        audited_names.append(saved['name'])
        return ({'requirementsId': candidate['requirementsId'], 'name': saved['name'],
            'workouts': copy.deepcopy(candidate['workouts'])}, {'plan': True}, {'errors': []}, {})
    monkeypatch.setattr(alternative_repair, '_audit_candidate', audit_saved_candidate)
    review_inputs = []
    def append_saved_receipt(_messages, saved, *_args):
        review_inputs.append(copy.deepcopy(saved['review']))
        return [{'role': 'tool', 'content': json.dumps({'review': saved['review']})}]
    monkeypatch.setattr(alternative_repair, '_append_hypothetical_requirements', append_saved_receipt)
    monkeypatch.setattr(planning_tools, 'library_fingerprint', lambda *_args: 'library')
    monkeypatch.setattr(planning_tools, 'render_draft', lambda *_args: 'saved preview')
    def refresh_review(_client, snapshot, review_messages, *_args):
        assert snapshot['submittedDraft']['name'] == candidate['candidateName']
        assert json.loads(review_messages[0]['content'])['review']['assessment']['version'] == ASSESSMENT_VERSION - 1
        return {'passed': review_passed, 'preview': 'refreshed review preview',
            'review': copy.deepcopy(fresh_assessment_review), 'errors': []}
    monkeypatch.setattr(plan_review, 'review_draft', refresh_review)
    monkeypatch.setattr(conflict_resolution, 'diagnose_conflict_and_propose',
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError('full diagnosis must not run')))

    response = interactive_shell.handle_function_call(None, messages, 'propose_workout_alternatives', {
        'staleAlternativeAssessment': True, 'repairCandidateId': candidate['repairCandidateId'],
        'requirementsId': 'REQ_ORIGINAL', 'baseDraftId': 'DRAFT_7',
        'repairDeadlineUTC': candidate['diagnosisDeadlineUTC']}, provided_equipment={},
        deps=SimpleNamespace(execute_workout_generation=None))
    refreshed_result = json.loads(response['result'])
    refreshed = refreshed_result['alternativeRepairCandidates'][0]

    assert refreshed_result['assessmentRefresh']['status'] == (
        'unresolved' if review_failed else 'proposal_ready' if review_passed else 'refreshed')
    assert refreshed['repairCandidateId'] == candidate['repairCandidateId']
    assert refreshed['originalRequirementsId'] == candidate['originalRequirementsId']
    assert refreshed['diagnosisVersion'] == CONFLICT_RESOLUTION_VERSION
    assert refreshed['requirementsId'] == candidate['requirementsId']
    assert refreshed['requirements'] == candidate['requirements']
    assert refreshed['workouts'] == candidate['workouts']
    assert refreshed['audit'] == candidate['audit']
    assert refreshed['review']['version'] == REVIEW_VERSION
    assert refreshed['review']['assessment']['version'] == ASSESSMENT_VERSION
    assert refreshed['review']['findings'] == fresh_findings
    if not review_failed:
        assert refreshed['findingsAssessment'] == refreshed['review']['assessment']
        assert refreshed['reviewFindings'] == refreshed['review']['findings']
    assert audited_names == [candidate['candidateName']]
    assert review_inputs == [old_review]
    if review_failed:
        assert refreshed['review'] == fresh_assessment_review
        assert refreshed_result['outcome'] == 'unresolved' and refreshed_result['passed'] is False
        assert 'confirmation' in refreshed_result['reason']
        assert not refreshed_result.get('proposals')
        return
    assert ('alternatives_ready' if review_passed else 'unresolved') == refreshed_result['outcome']
    assert refreshed_result['jointPlanningStopped'] is False
    assert refreshed_result['errors'] == []
    if review_passed:
        assert len(refreshed_result['proposals']) == 1
        assert refreshed_result['passed'] is True
        assert refreshed_result['errors'] == []
        assert refreshed_result['jointPlanningStopped'] is False
        assert 'explicit approval' in refreshed_result['instruction']
        assert response['alternative_previews'][0]['id'] == refreshed_result['proposals'][0]['proposalId']


def test_api_projection_reconciles_saved_candidate_review_summaries():
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION

    findings = [{'severity': 'warning', 'action': 'advisory', 'message': f'Finding {index}.'}
        for index in range(35)]
    review = {'version': REVIEW_VERSION, 'inputHash': 'current-review', 'findings': findings}
    review['assessment'] = {
        'version': ASSESSMENT_VERSION,
        'inputHash': assessment_hash(review),
        'groups': [{'findingIndexes': list(range(len(findings))), 'disposition': 'advisory',
            'repairDimensions': [], 'reason': 'These findings are advisory.', 'errorKind': 'none',
            'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}],
        'repairPlan': '',
    }
    stale_findings = copy.deepcopy(findings[:32])
    candidate = {'repairCandidateId': 'REVISION_REFRESHED', 'review': review,
        'reviewFindings': stale_findings,
        'findingsAssessment': {'version': ASSESSMENT_VERSION - 1,
            'inputHash': 'stale', 'groups': [], 'repairPlan': ''}}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'proposal-result', 'type': 'function',
            'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'proposal-result', 'content': json.dumps({
            'outcome': 'unresolved', 'alternativeRepairCandidates': [candidate]})},
    ]

    projected = interactive_shell._messages_for_api(messages)
    payload = json.loads(projected[1]['content'])
    projected_candidate = payload['alternativeRepairCandidates'][0]

    assert len(projected_candidate['reviewFindings']) == 35
    assert projected_candidate['reviewFindings'] == projected_candidate['review']['findings']
    assert projected_candidate['findingsAssessment'] == projected_candidate['review']['assessment']
    # The persisted transcript stays intact; only the model-facing copy is reconciled.
    persisted = json.loads(messages[1]['content'])['alternativeRepairCandidates'][0]
    assert len(persisted['reviewFindings']) == 32


@pytest.mark.parametrize('review_state', ['stale', 'failed_confirmation', 'failed_review'])
def test_planner_routes_stale_assessment_to_exact_candidate_refresh_task(review_state):
    from workout_generator_pkg.joint_planning import candidate_menu_fingerprint
    from workout_generator_pkg.planning_tools import _fingerprint, audit_workout_plan, library_fingerprint
    from workout_generator_pkg.conflict_resolution import CONFLICT_RESOLUTION_VERSION
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION
    from test_workout_generator_planner_context import _state, _tool
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft, equipment, messages)
    audited['reviewVersion'] = REVIEW_VERSION
    _tool(messages, 'audit_workout_plan', draft, audited, 'base-audit')
    review = {'version': REVIEW_VERSION, 'inputHash': 'saved-review', 'instructionBoundary': 1,
        'findings': [{'severity': 'warning', 'message': 'Saved finding.'}]}
    if review_state != 'failed_review':
        review['assessment'] = _assessment(review, ASSESSMENT_VERSION - 1 if review_state == 'stale' else ASSESSMENT_VERSION)
    if review_state != 'stale':
        review['failure'] = 'Incomplete confirmation or reviewer output.'
    candidate = {'repairCandidateId': 'REVISION_STALE_6',
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'originalRequirementsId': stored['requirementsId'],
        'originalRequirementsHash': _fingerprint(stored['requirements']),
        'baseDraftId': audited['currentDraftId'], 'requirementsId': 'ALT_REQUIREMENTS',
        'requirements': copy.deepcopy(stored['requirements']), 'workouts': copy.deepcopy(draft['workouts']),
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'libraryFingerprint': library_fingerprint(equipment), 'trainingHistoryFingerprint': None,
        'resolvedDecisions': {}, 'sourceMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'candidateMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'audit': {'errors': []}, 'review': review,
        'diagnosisDeadlineUTC': (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)).isoformat().replace('+00:00', 'Z'),
        'repairDeadlineUTC': (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=6)).isoformat().replace('+00:00', 'Z')}
    _tool(messages, 'propose_workout_alternatives', {}, {'outcome': 'candidate_feasible_pending_review',
        'requirementsId': stored['requirementsId'], 'baseDraftId': audited['currentDraftId'],
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'alternativeRepairCandidates': [candidate]}, 'saved-diagnosis')
    messages.append({'role': 'user', 'content': '/continue',
        'timestamp': dt.datetime.now(dt.timezone.utc).isoformat()})

    state = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))

    task = state['conflictDiagnosisTask']
    assert 'alternativeRepairTask' not in state
    assert task['staleAlternativeAssessment'] is True
    assert task['repairCandidateId'] == candidate['repairCandidateId']
    assert 'repairDeadlineUTC' not in task

    stale_outer_receipt = copy.deepcopy(messages)
    for message in stale_outer_receipt:
        if message.get('tool_call_id') == 'saved-diagnosis':
            stored_result = json.loads(message['content'])
            stored_result['diagnosisVersion'] = CONFLICT_RESOLUTION_VERSION - 1
            message['content'] = json.dumps(stored_result)
            break
    stale_state = _state(interactive_shell._messages_for_api(stale_outer_receipt, True, provided_equipment=equipment))
    assert stale_state['conflictDiagnosisTask'].get('staleAlternativeAssessment') is None
    assert stale_state['conflictDiagnosisTask']['requirementsId'] == stored['requirementsId']

    failed_refresh = {'outcome': 'unresolved', 'requirementsId': stored['requirementsId'],
        'baseDraftId': audited['currentDraftId'], 'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'assessmentRefresh': {'status': 'unresolved',
            'repairCandidateId': candidate['repairCandidateId'], 'reason': 'Assessment refresh failed.'},
        'alternativeRepairCandidates': [candidate]}
    _tool(messages, 'propose_workout_alternatives', {}, failed_refresh, 'failed-refresh')
    state = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert 'conflictDiagnosisTask' not in state
    assert state['alternativeAssessmentRefreshUnresolved']['reason'] == 'Assessment refresh failed.'

    messages.append({'role': 'user', 'content': '/continue',
        'timestamp': (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)).isoformat()})
    state = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['conflictDiagnosisTask']['repairCandidateId'] == candidate['repairCandidateId']


def test_decision_mismatch_routes_bound_alternative_to_targeted_assessment_refresh(monkeypatch):
    from workout_generator_pkg.conflict_resolution import CONFLICT_RESOLUTION_VERSION
    from workout_generator_pkg.joint_planning import candidate_menu_fingerprint
    from workout_generator_pkg.planning_tools import _fingerprint, audit_workout_plan, library_fingerprint
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.restriction_policy import effective_restrictions
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION
    from test_workout_generator_planner_context import _state, _tool
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    current_decisions = {'DECISION_0': {'topic': 'session layout', 'choice': 'Use the approved layout',
        'sourceReferences': ['SOURCE_0']}}
    _tool(messages, 'record_planning_decisions', {}, {'passed': True, 'decisions': current_decisions,
        'decisionReview': {'passed': True}}, 'current-decision')
    audited = audit_workout_plan(draft, equipment, messages)
    audited['reviewVersion'] = REVIEW_VERSION
    _tool(messages, 'audit_workout_plan', draft, audited, 'base-audit-current-decision')

    review = {'version': REVIEW_VERSION, 'inputHash': 'old-decision-review',
        'findings': [{'severity': 'warning', 'message': 'Saved alternative finding.'}]}
    review['assessment'] = _assessment(review, ASSESSMENT_VERSION)
    candidate = {'repairCandidateId': 'REVISION_DECISION_MISMATCH',
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'originalRequirementsId': stored['requirementsId'],
        'originalRequirementsHash': _fingerprint(stored['requirements']),
        'baseDraftId': audited['currentDraftId'], 'sourceDraftId': audited['currentDraftId'],
        'requirementsId': 'ALT_REQUIREMENTS_DECISION_MISMATCH',
        'requirements': copy.deepcopy(stored['requirements']), 'workouts': copy.deepcopy(draft['workouts']),
        'restrictionPolicy': effective_restrictions(stored, equipment),
        'libraryFingerprint': library_fingerprint(equipment), 'trainingHistoryFingerprint': None,
        'resolvedDecisions': {}, 'sourceMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'candidateMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'audit': {'errors': []}, 'review': review}
    _tool(messages, 'propose_workout_alternatives', {}, {'outcome': 'candidate_feasible_pending_review',
        'requirementsId': stored['requirementsId'], 'baseDraftId': audited['currentDraftId'],
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'alternativeRepairCandidates': [candidate]}, 'saved-decision-bound-diagnosis')
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'interrupted-duplicate-diagnosis', 'type': 'function',
            'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'interrupted-duplicate-diagnosis',
            'content': 'Tool call was not completed in the previous session. Treat this as a failed tool result and continue.'},
    ])
    from workout_generator_pkg.planning_tools import _latest_result
    assert _latest_result(messages, 'propose_workout_alternatives')[1]['outcome'] == 'candidate_feasible_pending_review'

    state = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))

    assert state['resolvedDecisions'] == current_decisions
    assert 'savedDraftReaudit' not in state
    assert state['conflictDiagnosisTask']['staleAlternativeAssessment'] is True
    assert state['conflictDiagnosisTask']['repairCandidateId'] == candidate['repairCandidateId']
    assert 'alternativeRepairTask' not in state

    seen = {}
    def refresh(saved_candidate, *_args):
        seen['candidate'] = copy.deepcopy(saved_candidate)
        return {'status': 'refreshed', 'candidate': copy.deepcopy(saved_candidate)}
    monkeypatch.setattr(alternative_repair, 'refresh_candidate_assessment', refresh)
    import workout_generator_pkg.conflict_resolution as conflict_resolution
    monkeypatch.setattr(conflict_resolution, 'diagnose_conflict_and_propose',
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError('stale assessment must not rerun diagnosis')))

    response = interactive_shell.handle_function_call(None, messages, 'propose_workout_alternatives', {
        'staleAlternativeAssessment': True, 'repairCandidateId': candidate['repairCandidateId'],
        'requirementsId': stored['requirementsId'], 'baseDraftId': audited['currentDraftId']},
        provided_equipment=equipment)
    refreshed_result = json.loads(response['result'])
    assert seen['candidate']['resolvedDecisions'] == current_decisions
    assert refreshed_result['assessmentRefresh']['status'] == 'refreshed'


def test_failed_assessment_refresh_keeps_prior_candidate_obligations_for_resume():
    from workout_generator_pkg.conflict_resolution import CONFLICT_RESOLUTION_VERSION
    from workout_generator_pkg.joint_planning import candidate_menu_fingerprint
    from workout_generator_pkg.plan_review import REVIEW_VERSION, _review_checklist, _review_obligation_id
    from workout_generator_pkg.planning_tools import _fingerprint, audit_workout_plan, library_fingerprint
    from workout_generator_pkg.restriction_policy import effective_restrictions
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION
    from test_workout_generator_planner_context import _tool
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, audited, 'ledger-source-base')

    findings = [{'severity': 'warning', 'reviewScope': 'execution', 'message': f'Saved candidate obligation {index}.',
        'path': f'/draft/workouts/{index}', 'draftPath': f'/workouts/{index}'} for index in range(3)]
    original_review = {'version': REVIEW_VERSION, 'inputHash': 'review-205',
        'instructionBoundary': len(messages) - 1, 'findings': findings}
    original_review['assessment'] = {
        'version': ASSESSMENT_VERSION, 'inputHash': assessment_hash(original_review),
        'groups': [{'findingIndexes': [0, 1, 2], 'disposition': 'repair',
            'repairDimensions': ['guidance'], 'reason': 'Repair all saved candidate findings.'}],
        'repairPlan': 'Repair all saved candidate findings.'}
    candidate = {'repairCandidateId': 'REVISION_LEDGER_205',
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'originalRequirementsId': stored['requirementsId'],
        'originalRequirementsHash': _fingerprint(stored['requirements']),
        'baseDraftId': audited['currentDraftId'], 'sourceDraftId': audited['currentDraftId'],
        'requirementsId': 'ALT_REQUIREMENTS_LEDGER', 'requirements': copy.deepcopy(stored['requirements']),
        'workouts': copy.deepcopy(draft['workouts']), 'candidateName': 'Saved alternative',
        'changes': [{'path': '/volume', 'from': 12, 'to': 8}],
        'restrictionPolicy': effective_restrictions(stored, equipment),
        'libraryFingerprint': library_fingerprint(equipment), 'trainingHistoryFingerprint': None,
        'resolvedDecisions': {}, 'sourceMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'candidateMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'audit': {'errors': []}, 'review': original_review}
    _tool(messages, 'propose_workout_alternatives', {}, {'outcome': 'candidate_feasible_pending_review',
        'requirementsId': stored['requirementsId'], 'baseDraftId': audited['currentDraftId'],
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'alternativeRepairCandidates': [candidate]}, 'candidate-review-205')

    current_decisions = {'DECISION_0': {'topic': 'session layout', 'choice': 'Use the approved layout',
        'sourceReferences': ['SOURCE_0']}}
    _tool(messages, 'record_planning_decisions', {}, {'passed': True, 'decisions': current_decisions,
        'decisionReview': {'passed': True}}, 'decision-refresh')
    failed_candidate = copy.deepcopy(candidate)
    failed_candidate['resolvedDecisions'] = current_decisions
    failed_candidate['review'] = {'version': REVIEW_VERSION, 'inputHash': 'failed-review-210',
        'instructionBoundary': len(messages) - 1, 'findings': findings[:1],
        'failure': 'Reviewer reference does not exist in supplied input.',
        'failureStage': 'independent_review_confirmation'}
    _tool(messages, 'propose_workout_alternatives', {}, {'outcome': 'unresolved',
        'assessmentRefresh': {'status': 'unresolved'},
        'alternativeRepairCandidates': [failed_candidate]}, 'failed-review-210')

    ledger = alternative_repair._candidate_review_ledger(failed_candidate, messages)
    assert ledger is not None
    assert ledger['review']['inputHash'] == 'review-205'
    assert ledger['resolvedDecisions'] == {}
    assert failed_candidate['review']['failure']

    review_messages = alternative_repair._append_hypothetical_requirements(
        messages, failed_candidate, stored, equipment, None, False)
    result = {'requirementsId': failed_candidate['requirementsId'],
        'libraryFingerprint': failed_candidate['libraryFingerprint'], 'historyFingerprint': None,
        'resolvedDecisions': current_decisions, 'allowEducatedLoadGuesses': False,
        'submittedDraft': {'requirementsId': failed_candidate['requirementsId'],
            'name': failed_candidate['candidateName'], 'workouts': failed_candidate['workouts']}}
    checklist = _review_checklist(result, review_messages)
    assert checklist is not None
    assert len(checklist['findings']) == 3
    assert {entry['finding']['message'] for entry in checklist['findings'].values()} == {
        finding['message'] for finding in findings}
    assert all(key.startswith('OBLIGATION_') for key in checklist['findings'])

    descendant = copy.deepcopy(failed_candidate)
    descendant.update(repairCandidateId='REVISION_LEDGER_MATERIALIZED',
        diagnosisCandidateId=candidate['repairCandidateId'],
        parentRepairCandidateId=candidate['repairCandidateId'])
    descendant['workouts'][0]['exercises'][0]['numWorkSets'] += 1
    descendant['candidateMenuFingerprint'] = 'materialized-menu'
    _tool(messages, 'repair_workout_alternative', {}, {'outcome': 'unresolved',
        'attemptStatus': 'repair_review_failed', 'repairCandidateId': descendant['repairCandidateId'],
        'candidateSnapshot': descendant}, 'materialized-refresh-failure')

    descendant_ledger = alternative_repair._candidate_review_ledger(descendant, messages)
    assert descendant_ledger is not None
    source_submitted = {'requirementsId': candidate['requirementsId'], 'name': candidate['candidateName'],
        'workouts': candidate['workouts']}
    original_ids = {_review_obligation_id(finding, source_submitted, original_review['inputHash'])
        for finding in original_review['findings']}
    recovered_ids = {_review_obligation_id(finding, source_submitted, descendant_ledger['review']['inputHash'])
        for finding in descendant_ledger['review']['findings']}
    assert recovered_ids == original_ids
    sibling = copy.deepcopy(descendant)
    sibling.update(repairCandidateId='REVISION_LEDGER_SIBLING', parentRepairCandidateId='UNRELATED_BRANCH')
    assert alternative_repair._candidate_review_ledger(sibling, messages) is None


def test_newer_diagnosis_assessment_wins_over_older_failed_repair_snapshot():
    from workout_generator_pkg.conflict_resolution import CONFLICT_RESOLUTION_VERSION
    from workout_generator_pkg.joint_planning import candidate_menu_fingerprint
    from workout_generator_pkg.planning_tools import _fingerprint, audit_workout_plan, library_fingerprint
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION
    from test_workout_generator_planner_context import _state, _tool
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft, equipment, messages)
    audited['reviewVersion'] = REVIEW_VERSION
    _tool(messages, 'audit_workout_plan', draft, audited, 'base-audit-newer-diagnosis')
    now = dt.datetime.now(dt.timezone.utc)
    deadline = (now + dt.timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')
    old_review = {'version': REVIEW_VERSION - 1, 'inputHash': 'old-review',
        'findings': [{'severity': 'warning', 'message': 'Saved finding.'}]}
    old_review['assessment'] = _assessment(old_review, ASSESSMENT_VERSION - 1)
    current_review = {'version': REVIEW_VERSION, 'inputHash': 'fresh-review',
        'findings': copy.deepcopy(old_review['findings'])}
    current_review['assessment'] = _assessment(current_review, ASSESSMENT_VERSION)
    candidate = {'repairCandidateId': 'REVISION_CHRONOLOGY',
        'originalRequirementsId': stored['requirementsId'],
        'originalRequirementsHash': _fingerprint(stored['requirements']),
        'baseDraftId': audited['currentDraftId'], 'sourceDraftId': audited['currentDraftId'],
        'requirementsId': 'ALT_REQUIREMENTS_CHRONOLOGY',
        'requirements': copy.deepcopy(stored['requirements']), 'workouts': copy.deepcopy(draft['workouts']),
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'libraryFingerprint': library_fingerprint(equipment), 'trainingHistoryFingerprint': None,
        'resolvedDecisions': {}, 'sourceMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'candidateMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'audit': {'errors': []}, 'review': current_review, 'reviewVersion': REVIEW_VERSION,
        'diagnosisDeadlineUTC': deadline}
    diagnosis = {'outcome': 'unresolved', 'requirementsId': stored['requirementsId'],
        'baseDraftId': audited['currentDraftId'], 'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'alternativeRepairCandidates': [candidate]}
    _tool(messages, 'propose_workout_alternatives', {}, diagnosis, 'fresh-diagnosis')
    state = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    failed_snapshot = copy.deepcopy(state['alternativeRepairTask'])
    failed_snapshot['review'] = copy.deepcopy(old_review)
    failed_snapshot['reviewVersion'] = REVIEW_VERSION - 1
    _tool(messages, 'repair_workout_alternative', {}, {
        'outcome': 'unresolved', 'attemptStatus': 'repair_failed',
        'repairCandidateId': candidate['repairCandidateId'], 'candidateSnapshot': failed_snapshot,
        'errors': [{'code': 'invalid_patch'}]}, 'older-repair-failure')
    refreshed_candidate = copy.deepcopy(candidate)
    refreshed_candidate['baseDraftId'] = 'REVISION_13575305261751'
    newer_diagnosis = {**diagnosis, 'alternativeRepairCandidates': [refreshed_candidate]}
    _tool(messages, 'propose_workout_alternatives', {}, newer_diagnosis, 'newer-diagnosis')

    replay = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))

    assert replay['alternativeRepairTask']['repairCandidateId'] == candidate['repairCandidateId']
    assert replay['alternativeRepairTask']['review']['version'] == REVIEW_VERSION
    assert replay['alternativeRepairTask']['findingsAssessment']['version'] == ASSESSMENT_VERSION
    assert replay['alternativeRepairTask']['sourceDraftId'] == audited['currentDraftId']
    assert replay['alternativeRepairTask']['baseDraftId'] == candidate['repairCandidateId']
    assert 'alternativeReviewAssessmentStale' not in replay


def test_stale_refresh_uses_newer_authority_bound_materialized_revision(monkeypatch):
    from workout_generator_pkg.conflict_resolution import CONFLICT_RESOLUTION_VERSION
    from workout_generator_pkg.joint_planning import candidate_menu_fingerprint
    from workout_generator_pkg.planning_tools import _fingerprint, audit_workout_plan, library_fingerprint
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION
    from workout_generator_pkg.restriction_policy import effective_restrictions
    from test_workout_generator_planner_context import _state, _tool
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft, equipment, messages)
    audited['reviewVersion'] = REVIEW_VERSION
    _tool(messages, 'audit_workout_plan', draft, audited, 'base-audit-materialized-refresh')
    review = {'version': REVIEW_VERSION - 1, 'inputHash': 'stale-review', 'instructionBoundary': 1,
        'findings': [{'severity': 'warning', 'message': 'Saved finding.'}]}
    review['assessment'] = _assessment(review, ASSESSMENT_VERSION - 1)
    candidate = {'repairCandidateId': 'REVISION_REFRESH_BASE',
        'originalRequirementsId': stored['requirementsId'],
        'originalRequirementsHash': _fingerprint(stored['requirements']),
        'baseDraftId': audited['currentDraftId'], 'sourceDraftId': audited['currentDraftId'],
        'requirementsId': 'ALT_REQUIREMENTS_REFRESH', 'requirements': copy.deepcopy(stored['requirements']),
        'workouts': copy.deepcopy(draft['workouts']), 'candidateName': 'Saved alternative',
        'changes': [], 'restrictionPolicy': effective_restrictions(stored, equipment),
        'libraryFingerprint': library_fingerprint(equipment), 'trainingHistoryFingerprint': None,
        'resolvedDecisions': {}, 'sourceMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'candidateMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION, 'reviewVersion': REVIEW_VERSION - 1,
        'audit': {'errors': []}, 'review': review,
        'diagnosisDeadlineUTC': (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')}
    _tool(messages, 'propose_workout_alternatives', {}, {'outcome': 'unresolved',
        'requirementsId': stored['requirementsId'], 'baseDraftId': audited['currentDraftId'],
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION, 'alternativeRepairCandidates': [candidate]}, 'stale-diagnosis')
    state = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['conflictDiagnosisTask']['staleAlternativeAssessment'] is True

    previous_snapshot = copy.deepcopy(candidate)
    previous_snapshot.update(repairCandidateId='REVISION_REFRESH_PREVIOUS',
        diagnosisCandidateId=candidate['repairCandidateId'],
        parentRepairCandidateId=candidate['repairCandidateId'],
        baseDraftId='REVISION_REFRESH_PREVIOUS',
        programGuidance='First reviewed revision guidance.')
    previous_snapshot['review'] = copy.deepcopy(review)
    previous_snapshot['review']['inputHash'] = 'stale-review-first-revision'
    previous_snapshot['review']['assessment'] = _assessment(
        previous_snapshot['review'], ASSESSMENT_VERSION - 1)
    _tool(messages, 'repair_workout_alternative', {}, {
        'outcome': 'unresolved', 'attemptStatus': 'repair_review_failed',
        'repairCandidateId': candidate['repairCandidateId'], 'candidateSnapshot': previous_snapshot,
        'errors': [{'code': 'review_finding'}]}, 'first-materialized-revision')
    snapshot = copy.deepcopy(previous_snapshot)
    snapshot.update(repairCandidateId='REVISION_REFRESH_MATERIALIZED',
        parentRepairCandidateId=previous_snapshot['repairCandidateId'],
        baseDraftId='REVISION_REFRESH_MATERIALIZED',
        programGuidance='Second reviewed revision guidance.')
    snapshot['review'] = copy.deepcopy(review)
    snapshot['review']['inputHash'] = 'stale-review-second-revision'
    snapshot['review']['assessment'] = _assessment(
        snapshot['review'], ASSESSMENT_VERSION - 1)
    _tool(messages, 'repair_workout_alternative', {}, {
        'outcome': 'unresolved', 'attemptStatus': 'repair_review_failed',
        'repairCandidateId': snapshot['repairCandidateId'], 'candidateSnapshot': snapshot,
        'errors': [{'code': 'review_finding'}]}, 'latest-materialized-revision-rejected')

    seen = {}
    def refresh(saved_candidate, *_args):
        seen['candidate'] = copy.deepcopy(saved_candidate)
        refreshed_candidate = copy.deepcopy(saved_candidate)
        refreshed_candidate['review'] = {'version': REVIEW_VERSION, 'inputHash': 'fresh-review',
            'findings': copy.deepcopy(review['findings']),
            'assessment': _assessment({'version': REVIEW_VERSION, 'inputHash': 'fresh-review',
                'findings': review['findings']}, ASSESSMENT_VERSION)}
        refreshed_candidate['reviewVersion'] = REVIEW_VERSION
        return {'status': 'refreshed', 'candidate': refreshed_candidate}
    monkeypatch.setattr(alternative_repair, 'refresh_candidate_assessment', refresh)
    monkeypatch.setattr(__import__('workout_generator_pkg.conflict_resolution', fromlist=['diagnose_conflict_and_propose']),
        'diagnose_conflict_and_propose',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('refresh must not rerun diagnosis')))

    response = interactive_shell.handle_function_call(None, messages, 'propose_workout_alternatives', {
        'requirementsId': stored['requirementsId'], 'baseDraftId': audited['currentDraftId'],
        'staleAlternativeAssessment': True, 'repairCandidateId': snapshot['repairCandidateId']},
        provided_equipment=equipment)
    result = json.loads(response['result'])

    assert seen['candidate']['repairCandidateId'] == snapshot['repairCandidateId']
    assert result['assessmentRefresh']['status'] == 'refreshed'
    refreshed = result['alternativeRepairCandidates'][0]
    assert refreshed['repairCandidateId'] == snapshot['repairCandidateId']
    assert refreshed['diagnosisCandidateId'] == candidate['repairCandidateId']
    assert refreshed['review']['version'] == REVIEW_VERSION


def test_failed_repair_snapshot_resumes_without_legacy_deadlines_on_explicit_continue():
    from workout_generator_pkg.conflict_resolution import CONFLICT_RESOLUTION_VERSION
    from workout_generator_pkg.joint_planning import candidate_menu_fingerprint
    from workout_generator_pkg.planning_tools import _fingerprint, audit_workout_plan, library_fingerprint
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION
    from test_workout_generator_planner_context import _state, _tool
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft, equipment, messages)
    audited['reviewVersion'] = REVIEW_VERSION
    _tool(messages, 'audit_workout_plan', draft, audited, 'base-audit')
    review = {'version': REVIEW_VERSION, 'inputHash': 'saved-review', 'instructionBoundary': 1,
        'findings': [{'severity': 'warning', 'message': 'Saved finding.'}]}
    review['assessment'] = _assessment(review, ASSESSMENT_VERSION)
    candidate = {'repairCandidateId': 'REVISION_RESUME',
        'originalRequirementsId': stored['requirementsId'],
        'originalRequirementsHash': _fingerprint(stored['requirements']),
        'baseDraftId': audited['currentDraftId'], 'requirementsId': 'ALT_REQUIREMENTS',
        'requirements': copy.deepcopy(stored['requirements']), 'workouts': copy.deepcopy(draft['workouts']),
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
        'libraryFingerprint': library_fingerprint(equipment), 'trainingHistoryFingerprint': None,
        'resolvedDecisions': {}, 'sourceMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'candidateMenuFingerprint': candidate_menu_fingerprint(draft['workouts']),
        'audit': {'errors': []}, 'review': review, 'diagnosisDeadlineUTC': '2000-01-01T00:00:00Z'}
    _tool(messages, 'propose_workout_alternatives', {}, {'outcome': 'unresolved',
        'requirementsId': stored['requirementsId'], 'baseDraftId': audited['currentDraftId'],
        'diagnosisVersion': CONFLICT_RESOLUTION_VERSION, 'alternativeRepairCandidates': [candidate]}, 'saved-diagnosis')
    messages.append({'role': 'user', 'content': '/continue',
        'timestamp': dt.datetime.now(dt.timezone.utc).isoformat()})

    state = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    task = state['alternativeRepairTask']
    assert 'repairDeadlineUTC' not in task
    assert task['baseDraftId'] == candidate['repairCandidateId']
    assert task['sourceDraftId'] == candidate['baseDraftId']

    schema_failure = {'outcome': 'unresolved', 'attemptStatus': 'repair_failed',
        'repairCandidateId': candidate['repairCandidateId'],
        'originalRequirementsId': candidate['originalRequirementsId'],
        'candidateSnapshot': copy.deepcopy(task), 'errors': [{'code': 'invalid_patch'}]}
    _tool(messages, 'repair_workout_alternative', {}, schema_failure, 'schema-failure')
    same_turn = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert 'repairDeadlineUTC' not in same_turn['alternativeRepairTask']
    assert same_turn['alternativeRepairTask']['baseDraftId'] == candidate['repairCandidateId']
    assert same_turn['alternativeRepairTask']['sourceDraftId'] == candidate['baseDraftId']

    revised_snapshot = copy.deepcopy(same_turn['alternativeRepairTask'])
    revised_snapshot.update(repairCandidateId='REVISION_RESUME_2',
        diagnosisCandidateId=candidate['repairCandidateId'],
        parentRepairCandidateId=candidate['repairCandidateId'],
        programGuidance='Keep the work controlled and leave one repetition in reserve.')
    revised_snapshot['review'] = copy.deepcopy(review)
    revised_snapshot['review']['inputHash'] = 'review-after-revision'
    revised_snapshot['review']['assessment'] = _assessment(
        revised_snapshot['review'], ASSESSMENT_VERSION)
    revised_snapshot['reviewVersion'] = REVIEW_VERSION
    semantic_failure = {'outcome': 'unresolved', 'attemptStatus': 'repair_review_failed',
        'repairCandidateId': candidate['repairCandidateId'],
        'originalRequirementsId': candidate['originalRequirementsId'],
        'candidateSnapshot': revised_snapshot, 'errors': [{'code': 'review_finding'}]}
    _tool(messages, 'repair_workout_alternative', {}, semantic_failure, 'review-failure')
    revised_turn = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert revised_turn['alternativeRepairTask']['repairCandidateId'] == 'REVISION_RESUME_2'
    assert 'repairDeadlineUTC' not in revised_turn['alternativeRepairTask']

    second_schema_failure = {'outcome': 'unresolved', 'attemptStatus': 'repair_failed',
        'repairCandidateId': 'REVISION_RESUME_2',
        'originalRequirementsId': candidate['originalRequirementsId'],
        'candidateSnapshot': {**copy.deepcopy(revised_turn['alternativeRepairTask']),
            'programGuidance': 'UNREVIEWED PARTIAL MUTATION'},
        'submittedEdits': {'programGuidance': 'Latest complete proposal remains available.'},
        'errors': [{'code': 'invalid_patch'}]}
    _tool(messages, 'repair_workout_alternative', {}, second_schema_failure, 'second-schema-failure')
    second_rejection_turn = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert second_rejection_turn['alternativeRepairTask']['repairCandidateId'] == 'REVISION_RESUME_2'
    assert second_rejection_turn['alternativeRepairTask']['programGuidance'] == revised_snapshot['programGuidance']
    assert second_rejection_turn['alternativeRepairTask']['review']['inputHash'] == 'review-after-revision'
    assert second_rejection_turn['alternativeRepairTask']['submissionCorrectionEdits'] == second_schema_failure['submittedEdits']
    assert 'repairDeadlineUTC' not in second_rejection_turn['alternativeRepairTask']

    messages.append({'role': 'user', 'content': '/continue',
        'timestamp': (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)).isoformat()})
    resumed = _state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    resumed_task = resumed['alternativeRepairTask']
    assert resumed_task['repairCandidateId'] == 'REVISION_RESUME_2'
    assert 'repairDeadlineUTC' not in resumed_task
    assert resumed_task['workouts'] == candidate['workouts']
