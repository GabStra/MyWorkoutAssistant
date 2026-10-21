import copy
import json
import re

import pytest

from workout_generator_pkg import joint_planning
from workout_generator_pkg.json_patching import apply_json_patch
from test_workout_generator_planning_tools import planning_case


def prescription_case():
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    sessions = []
    for index in range(3):
        day = copy.deepcopy(draft['workouts'][0])
        day.update(name=f'Day {index}', trainingDays=[2 * index])
        for item in day['exercises']:
            item.update(numWorkSets=8)
        sessions.append(day)
    return equipment, requirements, sessions


def _repair_solver_messages(equipment, requirements, sessions, call_number=1,
                            prior_receipt=None, candidate=None):
    from workout_generator_pkg.joint_planning import candidate_menu_fingerprint
    from workout_generator_pkg.planning_tools import _fingerprint, library_fingerprint

    candidate = candidate or {
        'repairCandidateId': 'ALT_1', 'originalRequirementsId': 'REQ_1',
        'originalRequirementsHash': _fingerprint(requirements), 'requirementsId': 'REQ_1',
        'sourceDraftId': 'DRAFT_1', 'baseDraftId': 'DRAFT_1',
        'sourceMenuFingerprint': candidate_menu_fingerprint(sessions),
        'libraryFingerprint': library_fingerprint(equipment), 'trainingHistoryFingerprint': None,
    }
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'proposal', 'type': 'function',
            'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'proposal', 'content': json.dumps({
            'alternativeRepairCandidates': [candidate]})},
    ]
    if prior_receipt is not None:
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': 'repair-previous', 'type': 'function',
                'function': {'name': 'repair_workout_alternative', 'arguments': json.dumps({
                    'repairCandidateId': candidate['repairCandidateId'],
                    'originalRequirementsId': candidate['originalRequirementsId']})}}]},
            {'role': 'tool', 'tool_call_id': 'repair-previous', 'content': json.dumps({
                'outcome': 'unresolved', 'attemptStatus': 'repair_menu_infeasible',
                'repairCandidateId': candidate['repairCandidateId'],
                'originalRequirementsId': candidate['originalRequirementsId'],
                'requirementsId': candidate['requirementsId'],
                'libraryFingerprint': candidate['libraryFingerprint'],
                'trainingHistoryFingerprint': candidate['trainingHistoryFingerprint'],
                'candidateSnapshot': candidate, 'workouts': sessions,
                'requirements': requirements, 'jointSolve': prior_receipt})},
        ])
    messages.append({'role': 'assistant', 'tool_calls': [{'id': f'repair-{call_number}', 'type': 'function',
        'function': {'name': 'repair_workout_alternative', 'arguments': json.dumps({
            'repairCandidateId': candidate['repairCandidateId'],
            'originalRequirementsId': candidate['originalRequirementsId']})}}]})
    return messages, candidate


def two_recipe_order_case():
    equipment, requirements, sessions = prescription_case()
    requirements['sessionsPerWeek'] = 1
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 12}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 12}
    requirements['requiredCoverage'] = [
        {'key': 'first', 'scope': 'eachSession', 'description': 'First movement'},
        {'key': 'second', 'scope': 'eachSession', 'description': 'Second movement'},
    ]
    sessions = [sessions[0]]
    first = sessions[0]['exercises'][0]
    first.update(numWorkSets=5, satisfiesCoverage=['first'], setupSeconds=0)
    second = copy.deepcopy(first)
    second.update(definition_id='LIBRARY_1', satisfiesCoverage=['second'], setupSeconds=300)
    sessions[0]['exercises'].append(second)
    second_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    second_definition.update(id='row', name='Chest Row')
    equipment['exerciseDefinitions'].append(second_definition)
    requirements['auditTargets']['maximumSessionSeconds'] = 2000
    return equipment, requirements, sessions


def test_volume_and_prescribed_time_are_solved_together_without_calibration_mode_overhead():
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 807
    requirements['executionRules'] = [{'kind': 'rest', 'coverageKey': None, 'context': 'straightSets',
                                     'minimumSeconds': 60, 'maximumSeconds': 120}]
    before = copy.deepcopy(sessions)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert result['recipeCount'] > result['physicalBlockCount']
    assert result['physicalBlockCount'] == result['firstVariableCount'] == len(sessions)
    assert 15 <= result['audit']['weeklyVolume']['chest']['effective'] <= 18
    assert all(day['estimatedSeconds'] <= 807 for day in result['audit']['workouts'])
    assert all(day['timing']['calibrationSeconds'] == 0 for day in result['audit']['workouts'])
    for day in result['sessions']:
        item = day['exercises'][0]
        assert item['numWorkSets'] >= 5 and item['restBetweenSetsSeconds'] == 60
        assert (item['minReps'], item['maxReps'], item['generateWarmUpSets']) == (
            before[0]['exercises'][0]['minReps'], before[0]['exercises'][0]['maxReps'],
            before[0]['exercises'][0]['generateWarmUpSets'])
    assert sessions == before
    patch = joint_planning.prescription_patch(sessions, result['sessions'])
    assert apply_json_patch({'workouts': sessions}, patch)['workouts'] == result['sessions']


def test_fixed_recovery_and_volume_conflict_fails_without_relaxing_either():
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 807
    before = copy.deepcopy(sessions)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert not result['feasible'] and result['status'] == 'infeasible'
    assert 'sessions' not in result and sessions == before
    assert 'every possible workout' in result['instruction']


def test_feasibility_domain_ignores_count_seed_and_objective_slack_but_tracks_prescription_options():
    equipment, requirements, sessions = prescription_case()
    baseline = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    seeded = copy.deepcopy(sessions)
    for day in seeded:
        day['exercises'][0]['numWorkSets'] = 13
    with_objective_slack = joint_planning.solve_prescribed_week(seeded, requirements, equipment,
        preserve_source_selection=True, balance=True)
    assert baseline['feasibilityDomainFingerprint'] == with_objective_slack['feasibilityDomainFingerprint']

    changed = copy.deepcopy(seeded)
    changed[0]['exercises'][0].update(minReps=8, maxReps=8)
    changed_domain = joint_planning.solve_prescribed_week(changed, requirements, equipment,
        preserve_source_selection=True)
    assert baseline['feasibilityDomainFingerprint'] != changed_domain['feasibilityDomainFingerprint']


def test_proven_infeasible_repair_domain_skips_repeat_solver_only_for_same_options(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    calls = []
    def infeasible(*args, **kwargs):
        calls.append(1)
        return 'infeasible', None
    monkeypatch.setattr(joint_planning, '_milp_solve', infeasible)
    first_messages, candidate = _repair_solver_messages(equipment, requirements, sessions)
    first = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        messages=first_messages, preserve_source_selection=True)
    assert first['status'] == 'infeasible' and first['feasibilityDomainFingerprint']
    assert calls

    changed_seed = copy.deepcopy(sessions)
    for day in changed_seed:
        day['exercises'][0]['numWorkSets'] = 12
    retry_messages, _ = _repair_solver_messages(equipment, requirements, changed_seed,
        call_number=2, prior_receipt=first, candidate=candidate)
    retry = joint_planning.solve_prescribed_week(changed_seed, requirements, equipment,
        messages=retry_messages, preserve_source_selection=True)
    assert retry['knownPriorInfeasibility'] is True
    assert retry['knownInfeasibleDomainMatch'] == 'generated_model_domain'
    assert retry['feasibilityDomainFingerprint'] == first['feasibilityDomainFingerprint']
    call_count_after_proof = len(calls)

    incomplete_receipt_messages, _ = _repair_solver_messages(equipment, requirements, changed_seed,
        call_number=3, prior_receipt={**first, 'rejectedOptions': [{'code': 'rejected_recipe'}]},
        candidate=candidate)
    incomplete = joint_planning.solve_prescribed_week(changed_seed, requirements, equipment,
        messages=incomplete_receipt_messages, preserve_source_selection=True)
    assert not incomplete.get('knownPriorInfeasibility')
    assert len(calls) > call_count_after_proof
    calls_after_incomplete = len(calls)

    changed_option = copy.deepcopy(changed_seed)
    changed_option[0]['exercises'][0].update(minReps=8, maxReps=8)
    new_domain_messages, _ = _repair_solver_messages(equipment, requirements, changed_option,
        call_number=4, prior_receipt=first, candidate=candidate)
    new_domain = joint_planning.solve_prescribed_week(changed_option, requirements, equipment,
        messages=new_domain_messages, preserve_source_selection=True)
    assert new_domain['feasibilityDomainFingerprint'] != first['feasibilityDomainFingerprint']
    assert len(calls) > calls_after_incomplete


def test_revision_two_infeasibility_survives_later_admission_failure(monkeypatch):
    from workout_generator_pkg.joint_planning import candidate_menu_fingerprint
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.planning_tools import _fingerprint, library_fingerprint
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION, assessment_hash

    equipment, requirements, sessions = prescription_case()
    menu = candidate_menu_fingerprint(sessions)
    finding = {'severity': 'warning', 'basis': 'uncertainty', 'path': '/draft/programGuidance',
        'evidencePaths': ['/draft/programGuidance'], 'message': 'Add guidance.', 'repair': 'Add guidance.',
        'action': 'repair', 'decisionId': None, 'newConflictEvidencePaths': [],
        'muscleTargets': [], 'draftPath': '/programGuidance'}
    review = {'version': REVIEW_VERSION, 'instructionBoundary': 0, 'inputHash': 'review-2',
        'findings': [finding]}
    review['assessment'] = {'version': ASSESSMENT_VERSION, 'inputHash': assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['program_guidance'], 'reason': 'Add guidance.'}],
        'repairPlan': 'Add guidance.'}
    candidate = {
        'repairCandidateId': 'REV_1', 'originalRequirementsId': 'REQ_1',
        'originalRequirementsHash': _fingerprint(requirements), 'requirementsId': 'REQ_1',
        'requirements': requirements, 'baseDraftId': 'DRAFT_1', 'sourceDraftId': 'DRAFT_1',
        'sourceMenuFingerprint': menu, 'candidateMenuFingerprint': menu,
        'libraryFingerprint': library_fingerprint(equipment), 'trainingHistoryFingerprint': None,
        'resolvedDecisions': {}, 'reviewVersion': REVIEW_VERSION, 'workouts': sessions,
        'audit': {'errors': []}, 'review': review,
    }
    revision_review = copy.deepcopy(review)
    revision_review['inputHash'] = 'review-2-materialized'
    revision_review['assessment']['inputHash'] = assessment_hash(revision_review)
    revision = {**copy.deepcopy(candidate), 'repairCandidateId': 'REV_2',
        'diagnosisCandidateId': 'REV_1', 'parentRepairCandidateId': 'REV_1',
        'review': revision_review,
        'programGuidance': 'New guidance for the reviewed revision.'}

    def add_tool_result(messages, name, arguments, payload, call_id):
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': call_id, 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(arguments)}}]},
            {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(payload)},
        ])

    messages = []
    add_tool_result(messages, 'propose_workout_alternatives', {'requirementsId': 'REQ_1'},
        {'alternativeRepairCandidates': [candidate]}, 'diagnosis')
    add_tool_result(messages, 'repair_workout_alternative', {'repairCandidateId': 'REV_1'},
        {'attemptStatus': 'repair_review_failed', 'candidateSnapshot': revision}, 'review-failed')
    calls = []
    monkeypatch.setattr(joint_planning, '_milp_solve', lambda *a, **k: (calls.append(1) or 'infeasible', None))
    add_tool_result(messages, 'repair_workout_alternative', {'repairCandidateId': 'REV_2',
        'originalRequirementsId': 'REQ_1'}, {}, 'first-revision-call')
    first = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        messages=messages, preserve_source_selection=True)
    assert first['status'] == 'infeasible'
    infeasible = {'outcome': 'unresolved', 'attemptStatus': 'repair_menu_infeasible',
        'repairCandidateId': 'REV_2', 'originalRequirementsId': 'REQ_1', 'requirementsId': 'REQ_1',
        'libraryFingerprint': candidate['libraryFingerprint'], 'trainingHistoryFingerprint': None,
        'candidateSnapshot': revision, 'jointSolve': first, 'workouts': sessions, 'requirements': requirements}
    add_tool_result(messages, 'repair_workout_alternative', {'repairCandidateId': 'REV_2',
        'originalRequirementsId': 'REQ_1'}, infeasible, 'infeasible-revision')
    add_tool_result(messages, 'repair_workout_alternative', {'repairCandidateId': 'REV_2',
        'originalRequirementsId': 'REQ_1'}, {'outcome': 'unresolved', 'attemptStatus': 'repair_failed',
            'repairCandidateId': 'REV_2', 'candidateSnapshot': revision, 'submittedEdits': {'patch': []}},
        'later-admission-failure')
    add_tool_result(messages, 'repair_workout_alternative', {'repairCandidateId': 'REV_2',
        'originalRequirementsId': 'REQ_1'}, {}, 'resumed-revision-call')
    resumed = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        messages=messages, preserve_source_selection=True)
    assert resumed['knownPriorInfeasibility'] is True
    assert resumed['knownInfeasibleDomainMatch'] == 'generated_model_domain'
    assert len(calls) == 1


def test_load_suitability_reuses_each_audited_option_across_placements(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    audits, checks = [], []
    original = joint_planning._audit_raw
    def audit(draft, *args):
        audits.append(len(draft['workouts']))
        return original(draft, *args)
    class History:
        fingerprint = 'test-history'
        def load_suitability_validator(self, messages, equipment):
            def check(plan):
                checks.append(len(plan['workouts']))
                return []
            return check
    monkeypatch.setattr(joint_planning, '_audit_raw', audit)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        training_history=History(), messages=[])
    assert result['feasible'], result
    assert checks == audits and checks[-1] == 3


def test_supported_shorter_prescription_is_selected_instead_of_inventing_reps():
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 950
    for day in sessions:
        day['exercises'][0].update(minReps=20, maxReps=20)
    sessions[-1]['exercises'][0].update(minReps=8, maxReps=8)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert all(day['exercises'][0]['minReps'] == 8 for day in result['sessions'])


def test_approved_count_limits_survive_recipe_selection():
    equipment, requirements, sessions = prescription_case()
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
                                      'minimumSets': 5, 'maximumSets': 5}]
    for day in sessions:
        day['exercises'][0]['allocationBounds'] = {'minimum': 1, 'maximum': 1}
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert all(day['exercises'][0]['numWorkSets'] == 5 for day in result['sessions'])


def test_missing_setup_cannot_be_hidden_by_reordering_a_submitted_block():
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 2500
    definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    definition.update(id='second', muscleGroups=['BACK_UPPER_BACK'], secondaryMuscleGroups=[])
    equipment['exerciseDefinitions'].append(definition)
    requirements['auditTargets']['weeklyEffectiveSets']['back'] = {'minimum': 15, 'maximum': 18}
    for day in sessions:
        second = copy.deepcopy(day['exercises'][0])
        second['definition_id'] = 'LIBRARY_1'
        second.pop('setupSeconds', None)
        day['exercises'].append(second)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert not result['feasible'] and result['status'] == 'infeasible'
    assert result['candidateOrderPolicy']['policy'] == 'submitted_order_with_approved_order_rules'


def test_final_production_audit_disagreement_fails_closed(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    original = joint_planning._audit_raw
    def audit(draft, *args):
        plan, report = original(draft, *args)
        if len(draft['workouts']) == 3:
            report['errors'].append({'code': 'unexpected_global_conflict', 'message': 'Retained validation.'})
        return plan, report
    monkeypatch.setattr(joint_planning, '_audit_raw', audit)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert not result['feasible'] and result['status'] == 'unverified'
    assert 'sessions' not in result and result['errors'][0]['code'] == 'unexpected_global_conflict'


@pytest.mark.parametrize('status', ['unproven', 'infeasible'])
def test_solver_failure_never_produces_a_submission(monkeypatch, status):
    equipment, requirements, sessions = prescription_case()
    monkeypatch.setattr(joint_planning, '_milp_solve', lambda *args, **kwargs: (status, None))
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert not result['feasible'] and result['status'] == status and 'sessions' not in result


def test_exact_per_set_prescriptions_are_not_resized():
    equipment, requirements, sessions = prescription_case()
    for day in sessions:
        item = day['exercises'][0]
        item.update(numWorkSets=2, targetSetPrescriptions=[
            {'workSetIndex': index, 'reps': 8, 'additionalWeight': 0} for index in range(2)])
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert not result['feasible'] and result['status'] == 'infeasible'


def test_joint_solve_ignores_request_deadline_and_frequency_mismatch_stays_invalid(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    from workout_generator_pkg import api_metrics
    monkeypatch.setattr(api_metrics, 'remaining_request_timeout', lambda _: 0)
    original = joint_planning._milp_solve
    solver_time_limits = []
    def solve_without_cap(variables, features, *, timeout_seconds, **kwargs):
        solver_time_limits.append(timeout_seconds)
        return original(variables, features, timeout_seconds=timeout_seconds, **kwargs)
    monkeypatch.setattr(joint_planning, '_milp_solve', solve_without_cap)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert solver_time_limits and all(limit is None for limit in solver_time_limits)
    result = joint_planning.solve_prescribed_week(sessions[:2], requirements, equipment)
    assert result['status'] == 'invalid_schedule' and not result['feasible']


def test_lineage_patch_moves_exact_duplicate_occurrence_across_workouts_and_preserves_identity():
    before = [
        {'name': 'Day 1', 'description': 'Day 1', 'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'LIBRARY_1', 'placementNotes': 'first cue', 'numWorkSets': 3},
        {'definition_id': 'LIBRARY_1', 'placementNotes': 'second cue', 'numWorkSets': 3},
        {'definition_id': 'LIBRARY_2', 'placementNotes': 'removed', 'numWorkSets': 3},
    ]},
        {'name': 'Day 2', 'description': 'Day 2', 'timesCompletedInAWeek': 1, 'exercises': [
            {'definition_id': 'LIBRARY_3', 'placementNotes': 'third cue', 'numWorkSets': 3},
        ]},
    ]
    after = [
        {'name': 'Day 1', 'description': 'Day 1', 'timesCompletedInAWeek': 1, 'exercises': [
            {'definition_id': 'LIBRARY_1', 'placementNotes': 'second cue', 'numWorkSets': 4},
        ]},
        {'name': 'Day 2', 'description': 'Day 2', 'timesCompletedInAWeek': 1, 'exercises': [
            {'definition_id': 'LIBRARY_1', 'placementNotes': 'repaired first cue', 'numWorkSets': 4},
            {'definition_id': 'LIBRARY_3', 'placementNotes': 'third cue', 'numWorkSets': 3},
        ]},
    ]

    patch = joint_planning.prescription_patch(before, after, [[[0, 1]], [[0, 0], [1, 0]]])

    assert {'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes',
        'value': 'repaired first cue'} in patch
    assert any(operation['op'] == 'move' for operation in patch)
    assert apply_json_patch({'workouts': before}, patch)['workouts'] == after

    from workout_generator_pkg.planning_tools import PlanningInputError, validate_repair_scope
    operation_refs = []
    for operation in patch:
        refs = set()
        for path in (operation.get('path', ''), operation.get('from', '')):
            match = re.match(r'^/workouts/(\d+)(?:/exercises/(\d+))?', path)
            if match:
                workout = int(match[1])
                refs.add(f'WORKOUT_{workout}')
                if match[2] is not None:
                    refs.add(f'EXERCISE_{sum(len(day["exercises"]) for day in before[:workout]) + int(match[2])}')
        operation_refs.append(sorted(refs))

    task = {'baseDraftId': 'REVISION_1', 'findingsAssessment': {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance']} ]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/1/placementNotes'}]}
    arguments = {'requirementsId': 'REQ_1', 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': patch}
    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope(arguments, {**task, '_compiledRepairOperationRefs': operation_refs},
            {'requirementsId': 'REQ_1', 'workouts': before})


def test_group_counts_order_and_full_timing_share_one_solve():
    equipment, requirements, sessions = prescription_case()
    second = copy.deepcopy(equipment['exerciseDefinitions'][0])
    second.update(id='row', muscleGroups=['BACK_UPPER_BACK'], secondaryMuscleGroups=[])
    equipment['exerciseDefinitions'].append(second)
    requirements['auditTargets']['maximumSessionSeconds'] = 2500
    requirements['auditTargets']['weeklyEffectiveSets']['back'] = {'minimum': 15, 'maximum': 18}
    for day in sessions:
        first = day['exercises'][0]
        first.update(superset='PAIR', restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=30)
        other = copy.deepcopy(first)
        other.update(definition_id='LIBRARY_1', restAfterSupersetExerciseSeconds=90)
        day['exercises'].append(other)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    for day, audited in zip(result['sessions'], result['audit']['workouts']):
        assert 1 <= len(day['exercises']) <= 2
        first = day['exercises'][0]
        if first['superset'] is not None:
            second = day['exercises'][1]
            assert first['superset'] == second['superset']
            assert first['numWorkSets'] == second['numWorkSets']
        else:
            assert all(item['superset'] is None and item['restAfterSupersetExerciseSeconds'] == 0 for item in day['exercises'])
        assert all(1 <= item['numWorkSets'] <= 20 for item in day['exercises'])
        assert audited['timing']['calibrationSeconds'] == 0 and audited['estimatedSeconds'] <= 2500


def test_invalid_pairing_keeps_eligible_standalone_movements_without_duplicate_inventory():
    equipment, requirements, sessions = prescription_case()
    other = copy.deepcopy(equipment['exerciseDefinitions'][0])
    other.update(id='row', muscleGroups=['BACK_UPPER_BACK'], secondaryMuscleGroups=[])
    equipment['exerciseDefinitions'].append(other)
    requirements['auditTargets']['weeklyEffectiveSets']['back'] = {'minimum': 15, 'maximum': 18}
    requirements['executionRules'] = [{'kind': 'straightSets', 'coverageKey': 'press'},
        {'kind': 'rest', 'coverageKey': None, 'context': 'straightSets', 'minimumSeconds': 60, 'maximumSeconds': 90}]
    requirements['requiredCoverage'] = [{'key': 'press', 'description': 'Press', 'scope': 'eachSession'},
        {'key': 'row', 'description': 'Row', 'scope': 'eachSession'}]
    requirements['auditTargets']['maximumSessionSeconds'] = 2500
    for day in sessions:
        first = day['exercises'][0]
        first.update(superset='PAIR', restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=30,
                     satisfiesCoverage=['press'])
        second = copy.deepcopy(first)
        second.update(definition_id='LIBRARY_1', satisfiesCoverage=['row'], restAfterSupersetExerciseSeconds=90)
        day['exercises'].append(second)
    before = copy.deepcopy(sessions)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    for day in result['sessions']:
        assert sorted(item['definition_id'] for item in day['exercises']) == ['LIBRARY_0', 'LIBRARY_1']
        assert all(item['superset'] is None and (item['numWorkSets'] == 1 or 60 <= item['restBetweenSetsSeconds'] <= 90) for item in day['exercises'])
    assert sessions == before


def test_weekly_frequency_weights_volume_without_changing_the_schedule():
    equipment, requirements, sessions = prescription_case()
    sessions = sessions[:2]
    sessions[0].update(timesCompletedInAWeek=2, trainingDays=[0, 3])
    sessions[1]['trainingDays'] = [5]
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert 15 <= result['audit']['weeklyVolume']['chest']['effective'] <= 18
    assert [(s['trainingDays'], s['timesCompletedInAWeek']) for s in result['sessions']] == [([0, 3], 2), ([5], 1)]


def test_partial_week_keeps_existing_workouts_immutable():
    equipment, requirements, sessions = prescription_case()
    existing = {'name': 'Week', 'workouts': [copy.deepcopy(sessions[0])]}
    existing['workouts'][0]['exercises'][0]['numWorkSets'] = 5
    before = copy.deepcopy(existing)
    result = joint_planning.solve_prescribed_week(sessions[1:], requirements, equipment, existing=existing)
    assert result['feasible'], result
    assert existing == before and len(result['sessions']) == 2
    assert 15 <= result['audit']['weeklyVolume']['chest']['effective'] <= 18


@pytest.mark.parametrize('limit, expected_difference', [(2000, 0), (1000, 0)])
def test_source_balance_is_optimized_with_volume_and_time_without_inventing_a_ratio(limit, expected_difference):
    from workout_generator_pkg.programming_guidelines import execution_rule_errors, render_execution_rule
    equipment, requirements, sessions = prescription_case()
    definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    definition['id'] = 'press_b'
    equipment['exerciseDefinitions'].append(definition)
    requirements['auditTargets']['maximumSessionSeconds'] = limit
    requirements['objectiveOrder'] = ['source_balance', 'preservation']
    requirements['requiredCoverage'] = [{'key': key, 'description': key, 'scope': 'weekly'} for key in ('first', 'second')]
    rule = {'kind': 'coverageBalance', 'first': 'first', 'second': 'second', 'scope': 'weekly'}
    requirements['executionRules'] = [rule]
    assert execution_rule_errors(requirements) == []
    assert 'no numerical tolerance' in render_execution_rule(rule)
    for day in sessions:
        day['exercises'][0]['satisfiesCoverage'] = ['first']
        other = copy.deepcopy(day['exercises'][0])
        other.update(definition_id='LIBRARY_1', satisfiesCoverage=['second'])
        day['exercises'].append(other)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'] and result['status'] == 'optimal', result
    coverage = result['audit']['weeklyCoverageSets']
    assert abs(coverage['first'] - coverage['second']) == expected_difference
    assert all(day['estimatedSeconds'] <= limit for day in result['audit']['workouts'])
    assert 15 <= result['audit']['weeklyVolume']['chest']['effective'] <= 18


def test_balanced_valid_week_is_not_resolved_for_a_notes_edit(monkeypatch):
    from workout_generator_pkg.allocation import auto_allocate_workout
    from workout_generator_pkg.planning_tools import set_workout_requirements, audit_workout_plan
    from test_workout_generator_planning_tools import requirement_messages
    equipment, requirements, sessions = prescription_case()
    requirements['requiredCoverage'] = [{'key': key, 'description': key, 'scope': 'weekly'} for key in ('first', 'second')]
    requirements['executionRules'] = [{'kind': 'coverageBalance', 'first': 'first', 'second': 'second', 'scope': 'weekly'}]
    for day in sessions:
        day['exercises'][0].update(numWorkSets=5, satisfiesCoverage=['first', 'second'], placementNotes='New execution cue.')
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Balance first and second weekly.'}], equipment)
    messages = requirement_messages(stored)
    raw = audit_workout_plan({'requirementsId': stored['requirementsId'], 'name': 'Week', 'workouts': sessions}, equipment, messages)
    assert raw['passed']
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', lambda *a, **k: pytest.fail('Already at the balance lower bound; preserve prescriptions'))
    assert auto_allocate_workout(raw, equipment, messages) == raw


def test_qualitative_coverage_balance_does_not_trigger_joint_optimization(monkeypatch):
    from workout_generator_pkg import allocation
    from workout_generator_pkg.planning_tools import set_workout_requirements, audit_workout_plan
    from test_workout_generator_planning_tools import requirement_messages
    equipment, requirements, sessions = prescription_case()
    requirements['requiredCoverage'] = [{'key': key, 'description': key, 'scope': 'weekly'} for key in ('first', 'second')]
    requirements['executionRules'] = [{'kind': 'coverageBalance', 'first': 'first', 'second': 'second', 'scope': 'weekly'}]
    requirements['auditTargets']['maximumSessionSeconds'] = 1200
    second_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    second_definition['id'] = 'press_b'
    equipment['exerciseDefinitions'].append(second_definition)
    for day in sessions:
        first = day['exercises'][0]
        first.update(numWorkSets=3, satisfiesCoverage=['first'])
        second = copy.deepcopy(first)
        second.update(definition_id='LIBRARY_1', numWorkSets=2, satisfiesCoverage=['second'])
        day['exercises'] = [first, second]
    source = [{'role': 'user', 'content': 'Include both roles and aim for broad weekly balance.'}]
    stored = set_workout_requirements(requirements, source, equipment)
    messages = requirement_messages(stored)
    raw = audit_workout_plan({'requirementsId': stored['requirementsId'], 'name': 'Week', 'workouts': sessions}, equipment, messages)
    assert raw['passed'] and raw['audit']['weeklyCoverageSets']['first'] != raw['audit']['weeklyCoverageSets']['second']
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', lambda *a, **k: pytest.fail('Qualitative balance remains for semantic review'))
    assert allocation.auto_allocate_workout(raw, equipment, messages) == raw


def test_progression_objective_is_not_inferred_from_mixed_capabilities(monkeypatch):
    from workout_generator_pkg import allocation
    from workout_generator_pkg.planning_tools import audit_workout_plan
    from test_workout_generator_planning_tools import requirement_messages
    equipment, requirements, sessions = prescription_case()
    second_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    second_definition['id'] = 'press_b'
    equipment['exerciseDefinitions'].append(second_definition)
    sessions[1]['exercises'][0]['definition_id'] = 'LIBRARY_1'
    for day in sessions:
        day['exercises'][0]['numWorkSets'] = 5
    from workout_generator_pkg.planning_tools import set_workout_requirements
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Plan a 3-day full-body hypertrophy program.'}], equipment)
    messages = requirement_messages(stored)
    raw = audit_workout_plan({'requirementsId': stored['requirementsId'], 'name': 'Week', 'workouts': sessions}, equipment, messages)
    assert raw['passed']
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.progression_margin',
        lambda item, capability: {'penalty': 0 if item['definition_id'] == 'LIBRARY_0' else 1})
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', lambda *a, **k: pytest.fail('No progression objective was approved'))
    assert allocation.auto_allocate_workout(raw, equipment, messages) == raw


def test_joint_priorities_use_small_sequential_objectives_and_keep_attained_distribution(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 2000
    requirements['objectiveOrder'] = ['progression', 'distribution', 'preservation']
    solve = joint_planning._milp_solve
    calls = []
    def record(variables, features, **options):
        assert max(abs(variable['objectiveCost']) for variable in variables) < 1_000_000
        calls.append([feature[0] for feature in features if feature[0][0] == 'objective'])
        return solve(variables, features, **options)
    monkeypatch.setattr(joint_planning, '_milp_solve', record)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment, balance=True)
    assert result['feasible'], result
    assert result['problemFingerprint'] == joint_planning.joint_problem_fingerprint(sessions, requirements, equipment)
    stages = result['objectiveProgress']
    assert stages[0]['goal'] == 'progression'
    assert stages[1]['goal'] == 'distribution' and 74 <= stages[1]['value'] <= 75
    assert [stage['goal'] for stage in stages] == requirements['objectiveOrder']
    assert result['objectivePolicy'] == 'approved' and result['objectiveOrderUsed'] == requirements['objectiveOrder']
    assert len(calls) >= 3 and ('objective', 'progression') in calls[1] and ('objective', 'distribution') in calls[2]
    assert sum(item['numWorkSets'] ** 2 for day in result['sessions'] for item in day['exercises']) == 75


def test_joint_solver_discloses_preservation_only_fallback_without_approved_order():
    equipment, requirements, sessions = prescription_case()
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment, balance=True)
    assert result['feasible'], result
    assert result['objectivePolicy'] == 'preserve_candidate_only'
    assert result['objectiveOrderUsed'] == ['preservation']
    assert [stage['goal'] for stage in result['objectiveProgress']] == ['preservation']


def test_preserve_source_selection_keeps_each_submitted_block_and_labels(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    requirements['sessionsPerWeek'] = 1
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 5, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 5, 'maximum': 6}
    requirements['objectiveOrder'] = ['progression']
    sessions = [sessions[0]]
    sessions[0].update(name='Bench + hinge focus', description='Press and hinge.')
    optional_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    optional_definition['id'] = 'zz_optional'
    equipment['exerciseDefinitions'].append(optional_definition)
    optional = copy.deepcopy(sessions[0]['exercises'][0])
    optional['definition_id'] = 'LIBRARY_1'
    sessions[0]['exercises'].append(optional)
    monkeypatch.setattr(joint_planning, 'progression_margin', lambda item, capability: {
        'penalty': 100 if item['definition_id'] == 'LIBRARY_0' else 0})

    broad = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    preserved = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)

    assert broad['feasible'] and [item['definition_id'] for item in broad['sessions'][0]['exercises']] == ['LIBRARY_1']
    assert preserved['feasible'], preserved
    assert {item['definition_id'] for item in preserved['sessions'][0]['exercises']} == {'LIBRARY_0', 'LIBRARY_1'}
    assert preserved['sessions'][0]['name'] == sessions[0]['name']
    assert preserved['sessions'][0]['description'] == sessions[0]['description']
    assert preserved['preserveSourceSelection'] is True
    assert joint_planning.joint_problem_fingerprint(sessions, requirements, equipment,
        preserve_source_selection=True) != joint_planning.joint_problem_fingerprint(sessions, requirements, equipment)
    assert joint_planning.joint_objective_input_fingerprint(sessions, requirements, equipment,
        preserve_source_selection=True) != joint_planning.joint_objective_input_fingerprint(sessions, requirements, equipment)

    rest_options = joint_planning._rest_options
    def reject_first_source_block(block, *args):
        if block[0]['definition_id'] == 'LIBRARY_0':
            return
        yield from rest_options(block, *args)
    monkeypatch.setattr(joint_planning, '_rest_options', reject_first_source_block)
    missing_source = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    assert not missing_source['feasible'] and missing_source['status'] == 'invalid_options'
    assert any(error['code'] == 'submitted_block_without_executable_options'
               for error in missing_source['errors'])


def test_preserve_source_selection_keeps_duplicate_definition_recipes_and_superset_group():
    equipment, requirements, sessions = prescription_case()
    requirements['sessionsPerWeek'] = 1
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 12}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 12}
    requirements['auditTargets']['maximumSessionSeconds'] = 4000
    sessions = [sessions[0]]
    first = sessions[0]['exercises'][0]
    first.update(numWorkSets=5, superset='PAIR', restBetweenSetsSeconds=0,
        restAfterSupersetExerciseSeconds=90)
    second_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    second_definition['id'] = 'zz_optional'
    equipment['exerciseDefinitions'].append(second_definition)
    second = copy.deepcopy(first)
    second.update(definition_id='LIBRARY_1', minReps=12, maxReps=15)
    duplicate = copy.deepcopy(first)
    duplicate.update(superset=None, restBetweenSetsSeconds=90, restAfterSupersetExerciseSeconds=0,
        numWorkSets=1, minReps=16, maxReps=20)
    sessions[0]['exercises'] = [first, second, duplicate]

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)

    assert result['feasible'], result
    solved = result['sessions'][0]['exercises']
    assert [(item['definition_id'], item['minReps'], item['superset'] is not None)
            for item in solved] == [
        ('LIBRARY_0', 8, True), ('LIBRARY_1', 12, True), ('LIBRARY_0', 16, False)]
    assert result['candidateOrderChanges'] == []


def test_preserve_source_selection_maps_duplicate_recipe_occurrences_across_workouts():
    equipment, requirements, sessions = prescription_case()
    sessions[2]['exercises'].append(copy.deepcopy(sessions[2]['exercises'][0]))

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)

    assert result['feasible'], result
    assert [item['definition_id'] for item in result['sessions'][2]['exercises']].count(
        sessions[2]['exercises'][0]['definition_id']) == 2


def test_progression_choice_does_not_redistribute_sets_toward_lower_penalty_blocks(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    alternative_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    alternative_definition['id'] = 'zz_alternative'
    equipment['exerciseDefinitions'].append(alternative_definition)
    sessions[1]['exercises'][0]['definition_id'] = 'LIBRARY_1'
    for day in sessions:
        day['exercises'][0]['numWorkSets'] = 5
    requirements['objectiveOrder'] = ['progression']
    monkeypatch.setattr(joint_planning, 'progression_margin', lambda item, capability: {
        'penalty': 100 if item['definition_id'] == 'LIBRARY_0' else 0})

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)

    assert result['feasible'], result
    assert [day['exercises'][0]['numWorkSets'] for day in result['sessions']] == [5, 5, 5]
    assert [day['exercises'][0]['definition_id'] for day in result['sessions']] == [
        'LIBRARY_0', 'LIBRARY_1', 'LIBRARY_0']
    assert [stage['goal'] for stage in result['objectiveProgress']] == [
        'progression', 'neutral_preservation']


def test_recipe_variant_collection_keeps_valid_options_and_handles_empty_enumeration(monkeypatch):
    equipment, requirements, sessions = prescription_case()

    def valid_then_rejected(block, *args):
        yield copy.deepcopy(block)
        rejected = copy.deepcopy(block)
        rejected[0]['restBetweenSetsSeconds'] = 100000
        yield rejected

    monkeypatch.setattr(joint_planning, '_rest_options', valid_then_rejected)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert any(item['code'] == 'invalid_recipe' for item in result['rejectedOptions'])

    monkeypatch.setattr(joint_planning, '_rest_options', lambda *args: iter(()))
    empty = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert not empty['feasible'] and empty['status'] == 'invalid_options'


@pytest.mark.parametrize(('preview', 'expected_preservation'), [(False, True), (True, False)])
def test_automatic_audit_uses_preserved_selection_and_preview_uses_proposal_scope(
        monkeypatch, preview, expected_preservation):
    from workout_generator_pkg import allocation
    from workout_generator_pkg.planning_tools import audit_workout_plan, set_workout_requirements
    from test_workout_generator_planning_tools import requirement_messages

    equipment, requirements, sessions = prescription_case()
    requirements['objectiveOrder'] = ['progression']
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Use the submitted movement choices.'}], equipment)
    messages = requirement_messages(stored)
    if preview:
        messages.append({'role': 'assistant', 'canonicalDraftPreview': True})
    raw = audit_workout_plan({'requirementsId': stored['requirementsId'], 'name': 'Week',
        'workouts': sessions}, equipment, messages)
    assert any(error['code'] == 'volume_above_target' for error in raw['errors'])
    observed = []

    def solve(*args, **kwargs):
        observed.append(kwargs['preserve_source_selection'])
        return {'feasible': False, 'status': 'infeasible', 'instruction': 'No feasible repair.'}

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    allocation.auto_allocate_workout(raw, equipment, messages)
    assert observed == [expected_preservation]


def test_preservation_cost_includes_omitted_source_blocks():
    equipment, requirements, sessions = prescription_case()
    optional_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    optional_definition['id'] = 'zz_optional'
    equipment['exerciseDefinitions'].append(optional_definition)
    for day in sessions:
        optional = copy.deepcopy(day['exercises'][0])
        optional['definition_id'] = 'LIBRARY_1'
        day['exercises'].append(optional)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    expected_edit_distance = 0
    for submitted, solved in zip(sessions, result['sessions']):
        solved_by_definition = {item['definition_id']: item for item in solved['exercises']}
        for item in submitted['exercises']:
            selected = solved_by_definition.get(item['definition_id'])
            expected_edit_distance += (abs(item['numWorkSets'] - selected['numWorkSets'])
                                       if selected else item['numWorkSets'])
    preservation = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'preservation')
    assert preservation['value'] == expected_edit_distance
    assert expected_edit_distance > 0


def test_neutral_preservation_tiebreak_does_not_change_approved_objectives(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    requirements['objectiveOrder'] = ['progression']
    monkeypatch.setattr(joint_planning, 'progression_margin', lambda item, capability: {'penalty': 1})

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert result['objectiveOrderUsed'] == ['progression']
    assert result['neutralTieBreak'] == 'preservation'
    assert [stage['goal'] for stage in result['objectiveProgress']] == ['progression', 'neutral_preservation']
    assert [day['exercises'][0]['numWorkSets'] for day in result['sessions']] == [5, 5, 5]


def test_joint_objective_fingerprint_ignores_resequence_but_binds_recipe_and_requirements():
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['auditTargets']['maximumSessionSeconds'] = None
    original = joint_planning.joint_objective_input_fingerprint(sessions, requirements, equipment)
    resequenced = copy.deepcopy(sessions)
    resequenced[0]['exercises'].reverse()
    assert joint_planning.joint_objective_input_fingerprint(resequenced, requirements, equipment) == original
    changed = copy.deepcopy(sessions)
    changed[0]['exercises'][0]['numWorkSets'] += 1
    assert joint_planning.joint_objective_input_fingerprint(changed, requirements, equipment) != original
    changed_requirements = copy.deepcopy(requirements)
    changed_requirements['objectiveOrder'] = ['progression']
    assert joint_planning.joint_objective_input_fingerprint(sessions, changed_requirements, equipment) != original


def test_unproven_joint_solve_returns_receipt_without_candidate_result(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    monkeypatch.setattr(joint_planning, '_milp_solve', lambda *a, **k: ('unproven', None))
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['status'] == 'unproven' and not result['feasible']
    assert result['objectiveInputFingerprint'] == joint_planning.joint_objective_input_fingerprint(
        sessions, requirements, equipment)


def test_submitted_order_is_a_hard_default_and_needs_no_second_order_solve(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    solve = joint_planning._milp_solve
    calls = []
    def record(*args, **kwargs):
        calls.append(1)
        return solve(*args, **kwargs)
    monkeypatch.setattr(joint_planning, '_milp_solve', record)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert [item['definition_id'] for item in result['sessions'][0]['exercises']] == [
        'LIBRARY_0', 'LIBRARY_1']
    assert result['candidateOrderPolicy'] == {
        'policy': 'submitted_order_with_approved_order_rules',
        'mode': 'stable_topological', 'reviewRequired': False,
    }
    assert len(calls) == 1
    assert result['candidateOrderChanges'] == []


def test_explicit_approved_order_overrides_candidate_order_and_is_reported():
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 1700
    requirements['executionRules'] = [{'kind': 'order', 'before': 'second', 'after': 'first'}]
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert [item['definition_id'] for item in result['sessions'][0]['exercises']] == [
        'LIBRARY_1', 'LIBRARY_0']
    assert result['candidateOrderChanges'] == [{
        'workoutIndex': 0,
        'submittedOrder': [['LIBRARY_0'], ['LIBRARY_1']],
        'solvedOrder': [['LIBRARY_1'], ['LIBRARY_0']],
        'removedBlocks': [], 'addedBlocks': [], 'retainedOrderChanged': True,
        'reason': ('The solver reordered retained blocks; independent session review should reassess '
                   'the candidate arrangement.'),
    }]
    assert result['candidateOrderPolicy']['reviewRequired']
    assert result['audit']['workouts'][0]['estimatedSeconds'] <= 1700


def test_numeric_time_limit_cannot_silently_reorder_submitted_exercises():
    equipment, requirements, sessions = two_recipe_order_case()
    # The 300-second setup belongs to the second movement; the solver must
    # satisfy the limit without silently changing exercise order.
    requirements['auditTargets']['maximumSessionSeconds'] = 1700
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert [item['definition_id'] for item in result['sessions'][0]['exercises']] == [
        item['definition_id'] for item in sessions[0]['exercises']]
    assert result['audit']['workouts'][0]['estimatedSeconds'] <= 1700
    assert result['candidateOrderPolicy']['policy'] == 'submitted_order_with_approved_order_rules'


def test_feasible_numeric_incumbent_does_not_need_a_second_order_solve(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    original = joint_planning._milp_solve
    calls = []
    def feasible_incumbent(*args, **kwargs):
        status, candidate = original(*args, **kwargs)
        calls.append((status, candidate))
        return ('feasible', candidate) if candidate is not None else (status, candidate)
    monkeypatch.setattr(joint_planning, '_milp_solve', feasible_incumbent)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert len(calls) == 1
    assert result['feasible'] and result['status'] == 'feasible'
    assert result['audit']['errors'] == []
    assert result['candidateOrderReviewRequired'] is False


def test_joint_problem_fingerprint_binds_requirements_and_full_workout_fields():
    equipment, requirements, sessions = prescription_case()
    fingerprint = joint_planning.joint_problem_fingerprint(sessions, requirements, equipment)
    assert fingerprint == joint_planning.joint_problem_fingerprint(copy.deepcopy(sessions),
        copy.deepcopy(requirements), copy.deepcopy(equipment))

    changed_requirements = copy.deepcopy(requirements)
    changed_requirements['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] += 1
    assert fingerprint != joint_planning.joint_problem_fingerprint(sessions, changed_requirements, equipment)

    changed_workouts = copy.deepcopy(sessions)
    changed_workouts[0]['exercises'][0]['satisfiesCoverage'] = ['new_role']
    assert fingerprint != joint_planning.joint_problem_fingerprint(changed_workouts, requirements, equipment)


def test_candidate_menu_fingerprint_ignores_numeric_and_note_edits_but_tracks_choices_and_pairings():
    sessions = [{'timesCompletedInAWeek': 1, 'name': 'Day', 'exercises': [
        {'definition_id': 'LIBRARY_1', 'numWorkSets': 3, 'placementNotes': 'Cue'},
        {'definition_id': 'LIBRARY_2', 'numWorkSets': 3, 'placementNotes': 'Cue'},
    ]}]
    fingerprint = joint_planning.candidate_menu_fingerprint(sessions)
    changed_prescription = copy.deepcopy(sessions)
    changed_prescription[0]['name'] = 'Renamed'
    changed_prescription[0]['exercises'][0].update(numWorkSets=7, placementNotes='Different coaching')
    assert fingerprint == joint_planning.candidate_menu_fingerprint(changed_prescription)

    added_movement = copy.deepcopy(sessions)
    added_movement[0]['exercises'].append({'definition_id': 'LIBRARY_3', 'numWorkSets': 3})
    assert fingerprint != joint_planning.candidate_menu_fingerprint(added_movement)

    paired = copy.deepcopy(sessions)
    paired[0]['exercises'][0]['superset'] = paired[0]['exercises'][1]['superset'] = 'SUPERSET_1'
    assert fingerprint != joint_planning.candidate_menu_fingerprint(paired)


def test_execution_order_preserves_source_order_and_applies_approved_edges():
    blocks = [{'options': [0], 'first': 1, 'sourceRank': 0, 'recipe': {'roles': {'isolation'}}},
        {'options': [3], 'first': 4, 'sourceRank': 1, 'recipe': {'roles': {'compound'}}},
        {'options': [6], 'first': 7, 'sourceRank': 2, 'recipe': {'roles': {'later'}}}]
    chosen = [1, 0, 0, 1, 1, 99, 1, 0, 0]
    assert joint_planning._execution_order(blocks, chosen, {}) == [0, 1, 2]
    assert joint_planning._execution_order(blocks, chosen, {'executionRules': [
        {'kind': 'order', 'before': 'later', 'after': 'isolation'}]}) == [1, 2, 0]
