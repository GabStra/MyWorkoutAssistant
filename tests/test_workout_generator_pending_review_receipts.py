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


def test_pending_review_audits_current_candidate_without_reconstructing_old_receipts(monkeypatch):
    from workout_generator_pkg import alternative_repair, cancellation, planning_tools, planning_decisions
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION

    candidate = {'repairCandidateId': 'REVISION_PENDING', 'reviewPending': True, 'review': {},
        'originalRequirementsId': 'REQ_ORIGINAL', 'baseDraftId': 'DRAFT_SOURCE',
        'requirementsId': 'REQ_ALTERNATIVE', 'requirements': {'auditTargets': {}},
        'workouts': [{'name': 'Current session', 'exercises': []}],
        'candidateName': 'Current candidate name', 'audit': {'errors': []}}
    original = {'requirementsId': 'REQ_ORIGINAL', 'requirements': {'auditTargets': {}}}
    messages = [{'role': 'tool', 'content': json.dumps({'candidateSnapshot': candidate,
        'independentReview': {'submittedDraft': {'name': 'Old receipt name'},
            'review': _review_receipt(REVIEW_VERSION, ASSESSMENT_VERSION)}})}]
    monkeypatch.setattr(planning_tools, 'require_approved_requirements', lambda *_: None)
    current_decisions = {'DECISION_0': {'choice': 'Current scoped user decision'}}
    monkeypatch.setattr(planning_decisions, 'resolved_decisions', lambda *_: current_decisions)
    monkeypatch.setattr(alternative_repair, '_latest_result', lambda *_: (-1, original))
    monkeypatch.setattr(alternative_repair, '_fresh_binding', lambda *_: True)
    audited = []
    def audit(current, workouts, *_):
        audited.append(copy.deepcopy(current))
        return ({'requirementsId': current['requirementsId'], 'name': current['name'],
            'workouts': copy.deepcopy(workouts)}, {'currentPlan': True}, {'errors': []}, {})
    monkeypatch.setattr(alternative_repair, '_audit_candidate', audit)
    monkeypatch.setattr(planning_tools, 'library_fingerprint', lambda *_: 'current-library')
    monkeypatch.setattr(planning_tools, 'render_draft', lambda *_: 'current preview')
    monkeypatch.setattr(alternative_repair, '_append_hypothetical_requirements', lambda *_: [])
    receipt = _review_receipt(REVIEW_VERSION, ASSESSMENT_VERSION)
    receipt.pop('failure')
    receipt.pop('failureStage')
    review_calls = []
    def review_current(*args, **kwargs):
        review_calls.append(copy.deepcopy(args[2]))
        return {'passed': False, 'errors': [], 'review': receipt}
    monkeypatch.setattr(cancellation, 'run_cancellable', review_current)

    result = alternative_repair.refresh_candidate_assessment(candidate, messages, {}, None, True, None)

    assert result['status'] == 'refreshed'
    assert len(audited) == len(review_calls) == 1
    assert audited[0]['name'] == 'Current candidate name' and audited[0]['review'] == {}
    assert audited[0]['resolvedDecisions'] == current_decisions
    assert 'resolvedDecisions' not in candidate
    assert review_calls[0]['submittedDraft']['workouts'] == candidate['workouts']
    assert result['candidate']['review'] == receipt


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
