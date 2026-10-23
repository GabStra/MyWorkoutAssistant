import copy
import json

import pytest


def _review_receipt(review_version, assessment_version):
    from workout_generator_pkg.review_assessment import assessment_hash

    review = {'version': review_version, 'inputHash': 'pending-review-input',
        'instructionBoundary': 0, 'findings': [], 'failure': 'confirmation interrupted',
        'failureStage': 'independent_review_confirmation'}
    review['assessment'] = {'version': assessment_version,
        'inputHash': assessment_hash(review), 'groups': [], 'repairPlan': ''}
    return review


def test_repair_pending_review_retains_the_returned_failure_receipt(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair
    import workout_generator_pkg.cancellation as cancellation
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION
    from test_workout_generator_alternative_repair import _stub_repair_materialization

    candidate, arguments = _stub_repair_materialization(monkeypatch, {'errors': []})
    failed_receipt = _review_receipt(REVIEW_VERSION, ASSESSMENT_VERSION)
    review_result = {'passed': False,
        'errors': [{'code': 'review_execution_failed', 'message': 'Confirmation interrupted.'}],
        'review': failed_receipt}
    monkeypatch.setattr(cancellation, 'run_cancellable', lambda *args, **kwargs: review_result)

    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)

    assert result['attemptStatus'] == 'review_pending'
    assert result['independentReview'] == review_result
    assert result['candidateSnapshot']['reviewPending'] is True
    assert result['candidateSnapshot']['review'] == failed_receipt
    assert result['candidateSnapshot']['reviewErrors'] == review_result['errors']


@pytest.mark.parametrize('mismatch', [None, 'workouts', 'submitted_requirements',
                                      'requirements', 'library', 'history', 'decisions',
                                      'load_guess_policy'])
def test_legacy_pending_receipt_recovers_only_for_matching_submission_and_authority(
        monkeypatch, mismatch):
    import workout_generator_pkg.alternative_repair as alternative_repair
    import workout_generator_pkg.cancellation as cancellation
    import workout_generator_pkg.planning_tools as planning_tools
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION

    candidate = {'repairCandidateId': 'REVISION_PENDING', 'reviewPending': True, 'review': {},
        'originalRequirementsId': 'REQ_ORIGINAL', 'originalRequirementsHash': 'original-hash',
        'sourceDraftId': 'DRAFT_SOURCE', 'baseDraftId': 'DRAFT_SOURCE',
        'requirementsId': 'REQ_ALTERNATIVE', 'requirements': {'auditTargets': {}},
        'workouts': [{'name': 'Session', 'exercises': [{'numWorkSets': 3}]}],
        'candidateName': 'Current candidate name', 'changes': [], 'restrictionPolicy': {},
        'libraryFingerprint': 'library-current', 'trainingHistoryFingerprint': 'history-current',
        'resolvedDecisions': {'DECISION_0': {'choice': 'Keep the current layout'}},
        'sourceMenuFingerprint': 'source-menu', 'candidateMenuFingerprint': 'candidate-menu',
        'audit': {'errors': []}}
    original_record = {'requirementsId': candidate['originalRequirementsId'],
        'requirements': {'auditTargets': {}}}
    submitted = {'requirementsId': candidate['requirementsId'],
        'name': 'Historical reviewed name', 'workouts': copy.deepcopy(candidate['workouts'])}
    authority = {'requirementsId': candidate['requirementsId'], 'libraryFingerprint': 'library-current',
        'historyFingerprint': 'history-current', 'resolvedDecisions': copy.deepcopy(candidate['resolvedDecisions']),
        'allowEducatedLoadGuesses': True}
    if mismatch == 'workouts':
        submitted['workouts'][0]['exercises'][0]['numWorkSets'] += 1
    elif mismatch == 'submitted_requirements':
        submitted['requirementsId'] = 'OTHER_REQUIREMENTS'
    elif mismatch == 'requirements':
        authority['requirementsId'] = 'OTHER_REQUIREMENTS'
    elif mismatch == 'library':
        authority['libraryFingerprint'] = 'old-library'
    elif mismatch == 'history':
        authority['historyFingerprint'] = 'old-history'
    elif mismatch == 'decisions':
        authority['resolvedDecisions'] = {}
    elif mismatch == 'load_guess_policy':
        authority['allowEducatedLoadGuesses'] = False
    independent_review = {'submittedDraft': submitted, **authority,
        'review': _review_receipt(REVIEW_VERSION, ASSESSMENT_VERSION)}
    saved_snapshot = copy.deepcopy(candidate)
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'repair-result', 'type': 'function',
            'function': {'name': 'repair_workout_alternative', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'repair-result', 'content': json.dumps({
            'candidateSnapshot': saved_snapshot, 'independentReview': independent_review})},
    ]

    monkeypatch.setattr(planning_tools, 'require_approved_requirements', lambda *_args: None)
    monkeypatch.setattr(alternative_repair, '_latest_result', lambda *_args: (-1, original_record))
    monkeypatch.setattr(alternative_repair, '_fresh_binding', lambda *_args: True)
    monkeypatch.setattr(alternative_repair, '_audit_candidate', lambda candidate, workouts, *_args:
        ({'requirementsId': candidate['requirementsId'], 'name': candidate.get('reviewedDraftName', candidate['candidateName']),
          'workouts': copy.deepcopy(workouts)}, {'plan': True}, {'errors': []}, {}))
    monkeypatch.setattr(planning_tools, 'library_fingerprint', lambda *_args: 'library-current')
    monkeypatch.setattr(planning_tools, 'render_draft', lambda *_args: 'preview')
    recovered = {}
    monkeypatch.setattr(alternative_repair, '_append_hypothetical_requirements',
        lambda _messages, current, *_args: recovered.update(
            review=copy.deepcopy(current.get('review')), reviewedDraftName=current.get('reviewedDraftName')) or [])
    refreshed_review = _review_receipt(REVIEW_VERSION, ASSESSMENT_VERSION)
    refreshed_review.pop('failure')
    refreshed_review.pop('failureStage')
    monkeypatch.setattr(cancellation, 'run_cancellable', lambda *args, **kwargs: {
        'passed': False, 'errors': [], 'review': refreshed_review})

    result = alternative_repair.refresh_candidate_assessment(
        candidate, messages, {}, None, True, None)

    assert result['status'] == 'refreshed'
    if mismatch is None:
        assert recovered['review'] == independent_review['review']
        # Preserve the name attached to the historical receipt separately from the candidate name.
        assert recovered['reviewedDraftName'] == 'Historical reviewed name'
    else:
        assert recovered['review'] == {}
        assert recovered['reviewedDraftName'] is None


def test_pending_review_append_keeps_parent_ledger_separate_from_failed_receipt(monkeypatch):
    import workout_generator_pkg.planning_tools as planning_tools
    from workout_generator_pkg.alternative_repair import _append_hypothetical_requirements
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION

    monkeypatch.setattr(planning_tools, 'build_draft_plan', lambda *args: {'plan': 'synthetic'})

    parent_review = _review_receipt(REVIEW_VERSION, ASSESSMENT_VERSION)
    parent_review.pop('failure')
    parent_review.pop('failureStage')
    parent = {'repairCandidateId': 'ALT_PARENT', 'requirementsId': 'REQ_ALT',
        'originalRequirementsId': 'REQ_ORIGINAL', 'originalRequirementsHash': 'original-hash',
        'sourceDraftId': 'DRAFT_SOURCE', 'baseDraftId': 'DRAFT_SOURCE',
        'libraryFingerprint': 'library', 'trainingHistoryFingerprint': None,
        'sourceMenuFingerprint': 'source-menu', 'candidateMenuFingerprint': 'parent-menu',
        'resolvedDecisions': {}, 'requirements': {'auditTargets': {}},
        'workouts': [{'name': 'Session', 'exercises': [{'numWorkSets': 3}]}],
        'candidateName': 'Parent candidate', 'changes': [], 'restrictionPolicy': {},
        'audit': {'errors': []}, 'review': parent_review}
    parent['reviewVersion'] = REVIEW_VERSION
    pending = copy.deepcopy(parent)
    pending.update(repairCandidateId='REVISION_PENDING', parentRepairCandidateId='ALT_PARENT',
        candidateMenuFingerprint='pending-menu', reviewPending=True,
        candidateName='Current candidate', reviewedDraftName='Previously reviewed name',
        workouts=[{'name': 'Session', 'exercises': [{'numWorkSets': 4}]}],
        review=_review_receipt(REVIEW_VERSION, ASSESSMENT_VERSION))
    diagnosis_messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'diagnosis', 'type': 'function',
            'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'diagnosis', 'content': json.dumps({
            'alternativeRepairCandidates': [parent]})},
    ]

    messages = _append_hypothetical_requirements(
        diagnosis_messages, pending,
        {'requirementsId': 'REQ_ORIGINAL', 'requirements': {'auditTargets': {}}},
        {}, None, True)
    calls = {call['id']: call['function']['name']
        for message in messages for call in message.get('tool_calls', [])}
    audit_results = [json.loads(message['content']) for message in messages
        if message.get('role') == 'tool' and calls.get(message.get('tool_call_id')) == 'audit_workout_plan']

    assert len(audit_results) == 2
    assert audit_results[0]['review'] == parent_review
    assert audit_results[0]['submittedDraft']['workouts'] == parent['workouts']
    assert audit_results[1]['review'] == pending['review']
    assert audit_results[1]['submittedDraft']['workouts'] == pending['workouts']
    assert audit_results[1]['submittedDraft']['name'] == 'Previously reviewed name'
