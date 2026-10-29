import copy
import json

import pytest


def test_preference_comparison_uses_current_reviewed_baseline_and_priority_receipt(monkeypatch):
    from workout_generator_pkg import allocation, interactive_shell, planning_decisions, planning_tools
    from workout_generator_pkg import plan_review, review_assessment, session_drafting, training_history

    sessions = [{'name': 'A', 'timesCompletedInAWeek': 1, 'exercises': []}]
    requirements = {'objectiveOrder': ['duration_balance'], 'requirementAccounting': []}
    stored = {'requirementsId': 'REQ', 'requirements': requirements}
    submission = {'requirementsId': 'REQ', 'workouts': sessions, 'programGuidance': ''}
    joint = {'audit': {'errors': []}, 'approvedObjectiveOrder': ['duration_balance'],
        'objectiveOrderUsed': ['duration_balance'], 'objectiveProgress': [{'goal': 'duration_balance'}],
        'sourceWorkingSetBudget': {'total': 1},
        'priorityExecution': {'approvedPriorities': [{'priority': 'duration_balance', 'status': 'optimal'}]}}
    artifact = {'workouts': [{'name': 'A', 'exercises': []}], 'programGuidance': ''}
    review = {'version': plan_review.REVIEW_VERSION, 'instructionBoundary': 0,
        'inputHash': 'input', 'reviewBaseHash': 'base', 'reviewLedgerOutputFingerprint': 'ledger',
        'reviewedArtifact': artifact, 'sourceCoverage': {'SOURCE_0': True},
        'findings': [], 'assessment': {'groups': []}}
    audit_result = {'requirementsId': 'REQ', 'currentDraftId': 'DRAFT', 'draftId': 'DRAFT',
        'libraryFingerprint': 'LIB', 'historyFingerprint': None, 'resolvedDecisions': {},
        'auditVersion': planning_tools.AUDIT_VERSION, 'allowEducatedLoadGuesses': True,
        'submittedDraft': submission, 'audit': {'errors': [], 'weeklyVolume': {}},
        'coordinatedJointPlanning': joint, 'review': review, 'passed': True,
        'preview': 'reviewed baseline'}
    checklist = {'findings': {}, 'acceptedSoftTradeoffs': {}}
    candidate_pool = {'sessions': sessions, 'fixedWorkouts': [],
        'scope': 'retained qualified worker recipes', 'preparationId': 'PREP'}
    monkeypatch.setattr(session_drafting, 'retained_worker_candidate_pool',
        lambda _messages, submission, _equipment, _history: (
            candidate_pool if submission == audit_result['submittedDraft'] else None))

    monkeypatch.setattr(interactive_shell, 'require_approved_requirements', lambda _messages: None)
    monkeypatch.setattr(interactive_shell, 'latest_draft_submission', lambda *_args: (submission, 'DRAFT'))
    monkeypatch.setattr(planning_tools, 'latest_draft_submission', lambda *_args: (submission, 'DRAFT'))
    monkeypatch.setattr(interactive_shell, '_latest_result', lambda _messages, name: {
        'set_workout_requirements': (1, stored), 'audit_workout_plan': (5, audit_result),
        'propose_workout_alternatives': (-1, {})}[name])
    monkeypatch.setattr(planning_tools, 'library_fingerprint', lambda _equipment: 'LIB')
    monkeypatch.setattr(allocation, 'latest_allocation_conflict', lambda _messages: (-1, {}))
    monkeypatch.setattr(planning_decisions, 'resolved_decisions', lambda _messages: {})
    monkeypatch.setattr('workout_generator_pkg.restriction_policy.effective_restrictions',
        lambda *_args: {})
    monkeypatch.setattr(plan_review, '_review_checklist', lambda *_args: checklist)
    monkeypatch.setattr(plan_review, '_context', lambda *_args: {
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Plan one session.'}},
        'finalArtifact': artifact})
    monkeypatch.setattr(plan_review, '_review_base_hash', lambda _context: 'base')
    monkeypatch.setattr(plan_review, '_review_input_hash', lambda *_args: 'input')
    monkeypatch.setattr(plan_review, '_review_ledger_fingerprint', lambda _ledger: 'ledger')
    monkeypatch.setattr(plan_review, '_source_message_items', lambda _sources: [
        ('SOURCE_0', {'role': 'user', 'content': 'Plan one session.'})])
    monkeypatch.setattr(review_assessment, 'validate_assessment', lambda *_args, **_kwargs: review['assessment'])
    monkeypatch.setattr(planning_tools, 'build_draft_plan', lambda *_args: {'exercises': [], 'workouts': []})
    monkeypatch.setattr(planning_tools, 'render_draft', lambda *_args: 'candidate preview')
    monkeypatch.setattr(training_history, 'apply_native_load_calibration_policy', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(interactive_shell, 'review_draft', lambda _client, snapshot, *_args, **_kwargs: (
        pytest.fail('The hypothetical review must receive the exact priority receipt first.')
        if snapshot.get('coordinatedJointPlanning') != {key: value for key, value in joint.items()
            if key not in ('sessions', 'audit')} else {'passed': True, 'review': {'assessment': {'groups': []}}}))

    def diagnose(**kwargs):
        assert kwargs['workouts'] == sessions
        assert kwargs['preference_baseline']['sessions'] == sessions
        assert kwargs['preference_baseline']['candidatePool'] == candidate_pool
        assert kwargs['preference_baseline']['sourceWorkingSetBudget'] == joint['sourceWorkingSetBudget']
        assert kwargs['unresolved_preferences'] == [{
            'priority': 'duration_balance', 'execution': joint['priorityExecution']['approvedPriorities'][0],
            'approvedObjectiveOrder': ['duration_balance'], 'basis': 'requested_comparison'}]
        kwargs['review_candidate'](sessions, requirements, joint)
        return {'outcome': 'unresolved', 'reason': 'No source-authorized change was available.',
            'baseline': {'workouts': sessions}}

    monkeypatch.setattr('workout_generator_pkg.conflict_resolution.diagnose_conflict_and_propose', diagnose)
    messages = [{'role': 'user', 'content': 'Plan one session.'},
        {'role': 'user', 'content': '/continue'}]
    result = interactive_shell.handle_function_call(None, messages, 'propose_workout_alternatives', {
        'requirementsId': 'REQ', 'baseDraftId': 'DRAFT', 'comparisonPriorities': ['duration_balance']},
        provided_equipment={})
    payload = json.loads(result['result'])
    assert payload['outcome'] == 'preference_comparison_unresolved'
    assert payload['passed'] is True and payload['jointPlanningStopped'] is False
    assert payload['errors'] == [] and payload['baseline']['workouts'] == sessions

    from workout_generator_pkg import conflict_resolution
    for mutation in ('reviewedArtifact', 'approvedObjectiveOrder', 'libraryFingerprint', 'auditVersion'):
        stale = copy.deepcopy(audit_result)
        if mutation == 'reviewedArtifact':
            stale['review']['reviewedArtifact'] = {'workouts': []}
        elif mutation == 'approvedObjectiveOrder':
            stale['coordinatedJointPlanning']['approvedObjectiveOrder'] = ['source_balance']
        elif mutation == 'libraryFingerprint':
            stale['libraryFingerprint'] = 'STALE_LIBRARY'
        else:
            stale['auditVersion'] = 'STALE_AUDIT'
        monkeypatch.setattr(interactive_shell, '_latest_result', lambda _messages, name, stale=stale: {
            'set_workout_requirements': (1, stored), 'audit_workout_plan': (5, stale),
            'propose_workout_alternatives': (-1, {})}[name])
        monkeypatch.setattr(conflict_resolution, 'diagnose_conflict_and_propose', lambda **_kwargs:
            pytest.fail('A stale baseline must not reach conflict diagnosis.'))
        with pytest.raises(ValueError):
            interactive_shell.handle_function_call(None, messages, 'propose_workout_alternatives', {
                'requirementsId': 'REQ', 'baseDraftId': 'DRAFT',
                'comparisonPriorities': ['duration_balance']}, provided_equipment={})

    failed_baseline = copy.deepcopy(audit_result)
    failed_baseline.update(passed=False, errors=[{'code': 'review_finding', 'message': 'Still needs review.'}])
    monkeypatch.setattr(interactive_shell, '_latest_result', lambda _messages, name: {
        'set_workout_requirements': (1, stored), 'audit_workout_plan': (5, failed_baseline),
        'propose_workout_alternatives': (-1, {})}[name])
    monkeypatch.setattr(conflict_resolution, 'diagnose_conflict_and_propose', lambda **_kwargs: {
        'outcome': 'unresolved', 'reason': 'No permitted comparison was available.',
        'baseline': {'workouts': sessions}})
    retained = json.loads(interactive_shell.handle_function_call(None, messages,
        'propose_workout_alternatives', {'requirementsId': 'REQ', 'baseDraftId': 'DRAFT',
            'comparisonPriorities': ['duration_balance']}, provided_equipment={})['result'])
    assert retained['passed'] is False and retained['errors'] == failed_baseline['errors']
    assert retained['jointPlanningStopped'] is False

    monkeypatch.setattr(interactive_shell, '_latest_result', lambda _messages, name: {
        'set_workout_requirements': (1, stored), 'audit_workout_plan': (5, audit_result),
        'propose_workout_alternatives': (-1, {})}[name])
    with pytest.raises(ValueError, match='current saved reviewed workout'):
        interactive_shell.handle_function_call(None, messages, 'propose_workout_alternatives', {
            'requirementsId': 'REQ', 'baseDraftId': 'DRAFT', 'repairCandidateId': 'REVISION_1',
            'comparisonPriorities': ['duration_balance']}, provided_equipment={})
