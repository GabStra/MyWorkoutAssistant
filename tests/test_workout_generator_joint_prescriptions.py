import copy
import json
import os
import re
import subprocess
import sys

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
            item.pop('placementNotes', None)
            item.update(numWorkSets=8)
        sessions.append(day)
    return equipment, requirements, sessions


def test_joint_solver_checks_native_calibration_before_selecting_shared_load_supersets():
    from test_workout_generator_programming_guidelines import case
    equipment, requirements, _, draft = case([{'kind': 'supersetNoReconfiguration', 'coverageKey': None}])
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'type': 'BARBELL', 'name': 'Adjustable barbell',
        'barWeight': 10, 'sleeveLength': 100, 'availablePlates': [{'weight': 5, 'thickness': 1}] * 2}]
    equipment['exerciseDefinitions'][0].update(exerciseType='WEIGHT', equipmentId='EQUIPMENT_0', bodyWeightPercentage=None)
    for index, item in enumerate(draft['workouts'][0]['exercises']):
        item.pop('placementNotes', None)
        item.update(superset='PAIR', restBetweenSetsSeconds=0, restAfterExerciseSeconds=0,
                    restAfterSupersetExerciseSeconds=30 if index == 0 else 90,
                    workSetTemplate={'reps': 9, 'weight': 10}, setupSeconds=60)
    result = joint_planning.solve_prescribed_week(draft['workouts'], requirements, equipment)
    assert result['feasible'], result
    assert len(result['sessions'][0]['exercises']) == 2
    assert all(item['superset'] is None for item in result['sessions'][0]['exercises'])
    assert any(item['code'] == 'execution_supersetNoReconfiguration' for item in result['rejectedOptions'])


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


def test_joint_solver_emits_count_series_hints_without_changing_domain_identity(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['sessionsPerWeek'] = 2
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 20, 'maximum': 24}
    second_day = copy.deepcopy(sessions[0])
    second_day.update(name='Day 1', trainingDays=[2])
    sessions.append(second_day)
    requirements['executionRules'] = [{'kind': 'rest', 'coverageKey': None,
        'context': 'straightSets', 'minimumSeconds': 60, 'maximumSeconds': 90}]
    captured = {}
    solve = joint_planning._milp_solve
    fingerprint = joint_planning._joint_model_domain_fingerprint

    def capture_solver(variables, features, **options):
        if 'variables' not in captured:
            captured['variables'] = copy.deepcopy(variables)
            captured['features'] = copy.deepcopy(features)
        return solve(variables, features, **options)

    def capture_fingerprint(variables, features, **kwargs):
        without_hints = [{key: value for key, value in item.items()
            if key not in ('countSeriesKey', 'countSeriesValue')} for item in variables]
        captured['fingerprintUnchanged'] = (
            fingerprint(variables, features, **kwargs)
            == fingerprint(without_hints, features, **kwargs))
        return fingerprint(variables, features, **kwargs)

    monkeypatch.setattr(joint_planning, '_milp_solve', capture_solver)
    monkeypatch.setattr(joint_planning, '_joint_model_domain_fingerprint', capture_fingerprint)
    result = joint_planning.solve_prescribed_week(
        sessions, requirements, equipment, preserve_source_selection=True)

    assert result['feasible'], result
    assert captured['fingerprintUnchanged'] is True
    option_variables = [item for item in captured['variables']
        if (item.get('domainIdentity') or {}).get('kind') == 'recipe_option']
    series = {}
    for item in option_variables:
        key = item.get('countSeriesKey')
        value = item.get('countSeriesValue')
        assert isinstance(key, tuple) and len(key) == 3
        assert type(value) is int and value > 0
        assert 'countSeriesKey' not in item['domainIdentity']
        assert 'countSeriesValue' not in item['domainIdentity']
        assert item['domainIdentity']['workoutIndex'] == key[0]
        assert item['domainIdentity']['workSetCount'] == value
        series.setdefault(key, []).append(value)

    assert len(series) > 0
    assert all(values == list(range(min(values), max(values) + 1)) for values in series.values())
    assert any(len(values) > 1 for values in series.values())
    variants_by_placement = {}
    workouts_by_variant = {}
    for workout_index, recipe_index, rest_signature in series:
        variants_by_placement.setdefault((workout_index, recipe_index), set()).add(rest_signature)
        workouts_by_variant.setdefault((recipe_index, rest_signature), set()).add(workout_index)
    assert any(len(signatures) > 1 for signatures in variants_by_placement.values())
    assert any(len(workouts) > 1 for workouts in workouts_by_variant.values())


def test_joint_model_emission_is_stable_across_python_hash_seeds():
    script = r'''\
import json
import sys
sys.path.insert(0, 'tests')
from workout_generator_pkg import joint_planning
from test_workout_generator_joint_prescriptions import two_recipe_order_case

class ModelCaptured(Exception):
    pass

equipment, requirements, sessions = two_recipe_order_case()
requirements['sessionsPerWeek'] = 2
requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 20, 'maximum': 24}
second_day = __import__('copy').deepcopy(sessions[0])
second_day.update(name='Day 1', trainingDays=[2])
sessions.append(second_day)
requirements['executionRules'] = [
    {'kind': 'rest', 'coverageKey': None, 'context': 'straightSets',
        'minimumSeconds': 60, 'maximumSeconds': 90},
    {'kind': 'order', 'before': 'first', 'after': 'second'},
]
captured = {}
fingerprint = joint_planning._joint_model_domain_fingerprint
def capture_fingerprint(variables, features, **kwargs):
    captured['fingerprint'] = fingerprint(variables, features, **kwargs)
    return captured['fingerprint']
def capture_solver(variables, features, **kwargs):
    captured['variables'] = variables
    captured['features'] = features
    raise ModelCaptured()
joint_planning._joint_model_domain_fingerprint = capture_fingerprint
joint_planning._milp_solve = capture_solver
try:
    joint_planning.solve_prescribed_week(sessions, requirements, equipment, preserve_source_selection=True)
except ModelCaptured:
    pass
else:
    raise AssertionError('Expected capture before any MILP solve.')
print(json.dumps({key: captured[key] for key in ('fingerprint', 'variables', 'features')},
    sort_keys=True, separators=(',', ':'), default=lambda value: sorted(value) if isinstance(value, set) else repr(value)))
'''
    repository_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outputs = []
    for seed in ('1', '37'):
        environment = os.environ.copy()
        environment['PYTHONHASHSEED'] = seed
        result = subprocess.run([sys.executable, '-c', script], cwd=repository_root,
            env=environment, capture_output=True, text=True, check=True)
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize('coverage_case', ['complete', 'missing_session_role', 'missing_weekly_role', 'unknown_role'])
def test_recipe_screen_contributes_coverage_and_joint_solve_enforces_complete_plan(coverage_case):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['requiredCoverage'].append({'key': 'weekly', 'scope': 'weekly', 'description': 'Weekly role'})
    second = sessions[0]['exercises'][1]
    second['satisfiesCoverage'].append('weekly')
    if coverage_case == 'missing_session_role':
        second['satisfiesCoverage'].remove('second')
    elif coverage_case == 'missing_weekly_role':
        second['satisfiesCoverage'].remove('weekly')
    elif coverage_case == 'unknown_role':
        second['satisfiesCoverage'].append('unapproved_role')
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment, preserve_source_selection=True)
    if coverage_case == 'complete':
        assert result['feasible'], result
        assert not result['audit']['errors']
        assert len(result['sessions'][0]['exercises']) == 2
    else:
        assert not result['feasible'], result


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
    for day in sessions:
        for item in day['exercises']:
            item.pop('placementNotes', None)
    baseline = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    seeded = copy.deepcopy(sessions)
    for day in seeded:
        day['exercises'][0]['numWorkSets'] = 13
    requirements['objectiveOrder'] = ['duration_balance', 'distribution']
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


def test_missing_setup_uses_code_owned_estimate_in_recipe_options():
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 2500
    definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    definition.update(id='second', muscleGroups=['BACK_UPPER_BACK'], secondaryMuscleGroups=[])
    equipment['exerciseDefinitions'].append(definition)
    requirements['auditTargets']['weeklyEffectiveSets']['back'] = {'minimum': 15, 'maximum': 18}
    for day in sessions:
        day['exercises'][0]['setupSeconds'] = 0
        second = copy.deepcopy(day['exercises'][0])
        second['definition_id'] = 'LIBRARY_1'
        second.pop('setupSeconds', None)
        day['exercises'].append(second)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    setup_values = [item.get('setupSeconds') for day in result['sessions'] for item in day['exercises']]
    assert all(value in (0, joint_planning.ASSUMPTIONS['transitionSeconds']) for value in setup_values)
    assert 0 in setup_values and joint_planning.ASSUMPTIONS['transitionSeconds'] in setup_values
    assert all(item.get('setupSeconds') is not None
        for day in result['sessions'] for item in day['exercises'])
    transitions = [workout['timing']['transitionSeconds'] for workout in result['audit']['workouts']]
    assert joint_planning.ASSUMPTIONS['transitionSeconds'] in transitions


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
    for day in sessions:
        for item in day['exercises']:
            item.pop('placementNotes', None)
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
        day['exercises'][0].pop('placementNotes', None)
        day['exercises'][0]['satisfiesCoverage'] = ['first']
        other = copy.deepcopy(day['exercises'][0])
        other.update(definition_id='LIBRARY_1', satisfiesCoverage=['second'])
        day['exercises'].append(other)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'] and result['status'] == 'optimal', result
    coverage = result['audit']['weeklyCoverageSets']
    assert abs(coverage['first'] - coverage['second']) == expected_difference
    assert result['priorityExecution']['approvedPriorities'][0]['status'] == 'optimal'
    assert result['priorityExecution']['coverageBalance'][0]['owner'] == 'joint_solver'
    assert result['priorityExecution']['coverageBalance'][0]['status'] == 'optimal'
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
    for day in sessions:
        for item in day['exercises']:
            item.pop('placementNotes', None)
    requirements['auditTargets']['maximumSessionSeconds'] = 2000
    requirements['objectiveOrder'] = ['progression', 'distribution', 'preservation']
    requirements['requiredCoverage'] = [
        {'key': key, 'description': key, 'scope': 'weekly'} for key in ('first', 'second')]
    requirements['executionRules'] = [
        {'kind': 'coverageBalance', 'first': 'first', 'second': 'second', 'scope': 'weekly'}]
    for day in sessions:
        day['exercises'][0]['satisfiesCoverage'] = ['first', 'second']
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
    assert stages[0]['goal'] == 'distribution' and stages[0]['value'] == pytest.approx(0)
    assert [stage['goal'] for stage in stages] == ['distribution', 'preservation']
    assert result['objectivePolicy'] == 'approved' and result['objectiveOrderUsed'] == ['distribution', 'preservation']
    assert result['approvedObjectiveOrder'] == requirements['objectiveOrder']
    priorities = {item['priority']: item for item in result['priorityExecution']['approvedPriorities']}
    assert priorities['progression']['owner'] == 'movement_selection_and_review'
    assert priorities['progression']['status'] == 'outside_joint_solver'
    assert priorities['progression']['solverStage'] is None
    assert priorities['distribution']['solverStage'] == stages[0]
    assert priorities['preservation']['solverStage'] == stages[1]
    assert result['priorityExecution']['coverageBalance'] == [{
        'kind': 'coverageBalance', 'first': 'first', 'second': 'second', 'scope': 'weekly',
        'owner': 'semantic_review', 'status': 'semantic_review_required', 'solverStage': None}]
    assert len(calls) >= 2 and ('objective', 'distribution') in calls[1]
    assert [day['volume']['chest']['effective'] for day in result['audit']['workouts']] == [6, 6, 6]


def test_directional_emphasis_preserves_supported_surplus_instead_of_forcing_equality():
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['source_balance']
    rule = {'kind': 'coverageBalance', 'first': 'first', 'second': 'second', 'scope': 'weekly',
            'relationship': 'first_not_less_than_second'}
    requirements['executionRules'] = [rule]
    for item, count in zip(sessions[0]['exercises'], (8, 2)):
        item.pop('placementNotes', None)
        item['numWorkSets'] = count
    original = copy.deepcopy(sessions)
    directional = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    assert directional['feasible'], directional
    assert [item['numWorkSets'] for item in directional['sessions'][0]['exercises']] == [8, 2]
    assert directional['priorityTradeoffs'] == []
    assert directional['priorityExecution']['coverageBalance'][0]['relationship'] == rule['relationship']

    rule['relationship'] = 'balanced'
    balanced = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    assert balanced['feasible'], balanced
    first, second = balanced['sessions'][0]['exercises']
    assert first['numWorkSets'] == second['numWorkSets']
    assert sessions == original


def test_residual_emphasis_reports_approved_constraint_conflict_without_relaxation():
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['source_balance']
    requirements['executionRules'] = [
        {'kind': 'coverageBalance', 'first': 'first', 'second': 'second', 'scope': 'weekly',
         'relationship': 'first_not_less_than_second'},
        {'kind': 'workSets', 'coverageKey': 'first', 'minimumSets': 2, 'maximumSets': 2},
        {'kind': 'workSets', 'coverageKey': 'second', 'minimumSets': 8, 'maximumSets': 8},
    ]
    for item in sessions[0]['exercises']:
        item.pop('placementNotes', None)
    original = copy.deepcopy(requirements)
    solved = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert solved['feasible'], solved
    tradeoff, = solved['priorityTradeoffs']
    assert (tradeoff['firstSets'], tradeoff['secondSets'], tradeoff['deviation']) == (2, 8, 6)
    assert tradeoff['status'] == 'residual_at_approved_optimum'
    assert 'Supplied executable recipes' in tradeoff['scopeOfProof']
    assert solved['audit']['errors'] == []
    assert requirements == original


def test_later_balance_stage_is_not_reported_optimal_after_feasible_prior_stage(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['distribution', 'source_balance']
    requirements['executionRules'] = [
        {'kind': 'coverageBalance', 'first': 'first', 'second': 'second', 'scope': 'weekly',
         'relationship': 'first_not_less_than_second'},
        {'kind': 'workSets', 'coverageKey': 'first', 'minimumSets': 2, 'maximumSets': 2},
        {'kind': 'workSets', 'coverageKey': 'second', 'minimumSets': 8, 'maximumSets': 8},
    ]
    for item in sessions[0]['exercises']:
        item.pop('placementNotes', None)

    solve = joint_planning._milp_solve

    def return_feasible_distribution_incumbent(variables, features, **options):
        status, candidate = solve(variables, features, **options)
        if options.get('diagnostics', {}).get('goal') == 'distribution' and candidate is not None:
            return 'feasible', candidate
        return status, candidate

    monkeypatch.setattr(joint_planning, '_milp_solve', return_feasible_distribution_incumbent)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    priorities = {item['priority']: item for item in result['priorityExecution']['approvedPriorities']}
    assert priorities['distribution']['status'] == 'feasible'
    assert priorities['source_balance']['status'] == 'feasible'
    assert priorities['source_balance']['solverStage']['status'] == 'optimal'
    assert result['priorityExecution']['coverageBalance'][0]['status'] == 'feasible'
    tradeoff, = result['priorityTradeoffs']
    assert tradeoff['status'] == 'residual_not_proven_minimal'
    assert 'preceding approved solver priority is only feasible' in tradeoff['scopeOfProof']


def test_automatic_joint_selection_redistributes_muscles_even_when_source_counts_are_equal(monkeypatch):
    import hashlib
    from workout_generator_pkg import allocation
    from workout_generator_pkg.exercise_library_tools import get_exercise_candidates
    from workout_generator_pkg.planning_tools import (
        audit_workout_plan, requirement_sources, set_workout_requirements, source_message_context,
    )
    from workout_generator_pkg.recipe_contracts import _recipe_context
    from test_workout_generator_planning_tools import requirement_messages

    equipment, requirements, sessions = prescription_case()
    requirements.update(sessionsPerWeek=2, objectiveOrder=['distribution'])
    requirements['auditTargets'] = {
        'weeklyEffectiveSets': {muscle: {'minimum': 6, 'maximum': 6} for muscle in ('chest', 'back')},
        'perSessionEffectiveSets': {muscle: {'minimum': 0, 'maximum': 6} for muscle in ('chest', 'back')},
        'maximumSessionSeconds': 2000,
    }
    requirements['requiredCoverage'] = [{'key': 'selected_pattern',
        'description': 'Selected pattern appears in the week.', 'scope': 'weekly'}]
    row = copy.deepcopy(equipment['exerciseDefinitions'][0])
    row.update(id='row', name='Row', muscleGroups=['BACK_UPPER_BACK'], secondaryMuscleGroups=[])
    equipment['exerciseDefinitions'].append(row)
    sessions = sessions[:2]
    for index, day in enumerate(sessions):
        day['exercises'][0].pop('placementNotes', None)
        day['exercises'][0].update(definition_id=f'LIBRARY_{index}', numWorkSets=6)
        day['exercises'][0]['satisfiesCoverage'] = ['selected_pattern']
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Spread chest and back work across two sessions.'}], equipment)
    messages = requirement_messages(stored)
    definitions = sorted(equipment['exerciseDefinitions'], key=lambda item: item['id'])
    references = sorted({item['definition_id'] for day in sessions for item in day['exercises']})
    candidates = {}
    for start in range(0, len(references), 100):
        candidates.update((item['id'], item) for item in get_exercise_candidates(
            {'definition_ids': references[start:start + 100]}, equipment, messages)['exercises'])
    prepared = {'candidates': candidates,
        'sourceMessages': source_message_context(requirement_sources(messages))}
    roles_by_reference = {}
    for day in sessions:
        for item in day['exercises']:
            roles_by_reference.setdefault(item['definition_id'], item.get('satisfiesCoverage', []))
    input_hashes = {reference: hashlib.sha256(json.dumps(
        _recipe_context(prepared, stored['requirements'], reference), sort_keys=True).encode()).hexdigest()
        for reference in references}
    contracts = [{'definition_id': reference,
        'satisfiesCoverage': copy.deepcopy(roles_by_reference[reference])} for reference in references]
    qualification = {'inputHashes': input_hashes, 'contracts': contracts}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'qualified-recipes', 'function': {
            'name': 'draft_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'qualified-recipes', 'content': json.dumps({
            'recipeQualification': qualification})},
    ])
    source_cap = sum(item.get('numWorkSets', 0) * day.get('timesCompletedInAWeek', 1)
        for day in sessions for item in day['exercises'])
    monkeypatch.setattr('workout_generator_pkg.session_drafting.source_working_set_budget_for_worker',
        lambda *args, **kwargs: {'source': 'test_current_source',
            'variableWeeklyWorkingSets': source_cap})
    draft = {'requirementsId': stored['requirementsId'], 'name': 'Week', 'workouts': sessions}
    raw = audit_workout_plan(draft, equipment, messages)
    assert raw['passed'], raw
    original = copy.deepcopy(raw)
    comparison_messages = copy.deepcopy(messages)
    result = allocation.auto_allocate_workout(raw, equipment, messages)
    assert result['passed'], result
    assert result['automaticAllocation']['preserveSourceSelection'] is False
    assert result['automaticAllocation']['application'] == 'automatic'
    assert result['automaticAllocation']['candidateOrderReviewRequired']
    assert result['automaticAllocation']['candidateComparison']['decision'] == 'promote_candidate'
    assert [[day['volume'][muscle]['effective'] for muscle in ('chest', 'back')]
            for day in result['audit']['workouts']] == [[3, 3], [3, 3]]
    assert all(item['numWorkSets'] >= 2 for day in result['submittedDraft']['workouts']
               for item in day['exercises'])
    assert raw == original

    compare_candidates = joint_planning.compare_audited_joint_candidates
    monkeypatch.setattr(joint_planning, 'compare_audited_joint_candidates',
        lambda *args, **kwargs: {'decision': 'retain_baseline', 'reason': 'first_differing_approved_objective',
            'baselineAuditErrors': [], 'candidateAuditErrors': [], 'comparisons': []})
    retained = allocation.auto_allocate_workout(raw, equipment, comparison_messages)
    assert retained['submittedDraft'] == raw['submittedDraft']
    assert 'automaticAllocation' not in retained
    assert retained['jointCandidateComparison']['decision'] == 'retain_baseline'
    monkeypatch.setattr(joint_planning, 'compare_audited_joint_candidates',
        lambda *args, **kwargs: {'decision': 'incomparable',
            'reason': 'higher_priority_demand_evidence_unavailable', 'comparisons': []})
    incomparable = allocation.auto_allocate_workout(raw, equipment, comparison_messages)
    assert incomparable['passed'] is True
    assert incomparable['submittedDraft'] == raw['submittedDraft']
    assert incomparable['jointCandidateComparison']['decision'] == 'incomparable'
    assert 'jointPromotionGate' not in incomparable and 'jointPlanningStopped' not in incomparable
    assert retained['jointCandidateProposal']['jointPlanning']['application'] == 'not_applied'
    assert 'candidateSolvedPrescriptionHash' in retained['jointCandidateProposal']['jointPlanning']
    comparison_messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 're-audited-retained', 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 're-audited-retained', 'content': json.dumps(retained)},
    ])
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week',
        lambda *args, **kwargs: pytest.fail('An unchanged rejected proposal must not be solved again.'))
    reused_retained = allocation.auto_allocate_workout(retained, equipment, comparison_messages)
    assert reused_retained['jointCandidateComparison']['decision'] == 'retain_baseline'
    assert 'automaticAllocation' not in reused_retained
    monkeypatch.setattr(joint_planning, 'compare_audited_joint_candidates', compare_candidates)

    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'solved', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'solved', 'content': json.dumps(result)},
    ])
    fallback_messages = copy.deepcopy(messages[:messages.index(next(
        message for message in messages if message.get('tool_call_id') == 'solved'))])
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', lambda *args, **kwargs: {
        'feasible': False, 'status': 'unproven', 'instruction': 'Bounded solve found no incumbent.',
        'selectionPolicyVersion': joint_planning.SELECTION_POLICY_VERSION,
        'preserveSourceSelection': False,
    })
    search_unproven = allocation.auto_allocate_workout(raw, equipment, fallback_messages)
    assert search_unproven['passed']
    assert not search_unproven.get('jointPlanningStopped')
    assert search_unproven['jointPlanningSearchUnproven'] == 'unproven'
    assert 'automaticAllocation' not in search_unproven
    assert search_unproven['jointCandidateSearchDiagnostic']['application'] == 'not_applied'
    assert search_unproven['jointCandidateSearchDiagnostic']['searchLimitation']['objectiveOptimality'] == 'unproven'
    assert search_unproven['jointCandidateSearchDiagnostic']['problemFingerprint']
    assert search_unproven['jointCandidateSearchDiagnostic']['sourceWorkingSetBudget'] == {
        'source': 'test_current_source', 'variableWeeklyWorkingSets': source_cap}
    fallback_messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 're-audited-unproven', 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 're-audited-unproven', 'content': json.dumps(search_unproven)},
    ])
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week',
        lambda *args, **kwargs: pytest.fail('An unchanged unproven search must not be solved again.'))
    reused_search = allocation.auto_allocate_workout(search_unproven, equipment, fallback_messages)
    assert reused_search['jointPlanningSearchUnproven'] == 'unproven'
    assert reused_search['jointCandidateSearchDiagnostic']['problemFingerprint'] == search_unproven[
        'jointCandidateSearchDiagnostic']['problemFingerprint']
    reused = allocation.auto_allocate_workout(result, equipment, messages)
    assert reused['submittedDraft'] == result['submittedDraft']
    assert reused['coordinatedJointPlanning']['reusedForValidatedCandidate']


def test_directional_surplus_does_not_trigger_an_automatic_equality_repair(monkeypatch):
    from workout_generator_pkg import allocation
    from workout_generator_pkg.planning_tools import audit_workout_plan, set_workout_requirements
    from test_workout_generator_planning_tools import requirement_messages

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['source_balance']
    requirements['executionRules'] = [{'kind': 'coverageBalance', 'first': 'first', 'second': 'second',
        'scope': 'weekly', 'relationship': 'first_not_less_than_second'}]
    for item, count in zip(sessions[0]['exercises'], (8, 2)):
        item.pop('placementNotes', None)
        item['numWorkSets'] = count
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'First gets no fewer sets than second, as a soft preference.'}], equipment)
    messages = requirement_messages(stored)
    raw = audit_workout_plan({'requirementsId': stored['requirementsId'], 'name': 'Week',
        'workouts': sessions}, equipment, messages)
    assert raw['passed'], raw
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week',
        lambda *args, **kwargs: pytest.fail('The approved directional preference is already satisfied.'))
    assert allocation.auto_allocate_workout(raw, equipment, messages) == raw


def _distribution_solver_case(session_counts, *, existing_counts=(), variants=False):
    equipment, requirements, sessions = prescription_case()
    requirements['sessionsPerWeek'] = len(session_counts) + len(existing_counts)
    requirements['objectiveOrder'] = ['distribution']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {
        'minimum': sum(session_counts) + sum(existing_counts),
        'maximum': sum(session_counts) + sum(existing_counts),
    }
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {
        'minimum': 1, 'maximum': max([*session_counts, *existing_counts]),
    }
    requirements['auditTargets']['maximumSessionSeconds'] = 5000
    sessions = sessions[:len(session_counts)]
    def lock_count(item, count):
        item.update(numWorkSets=count, targetSetPrescriptions=[
            {'workSetIndex': index, 'reps': 8} for index in range(count)])
    for day, count in zip(sessions, session_counts):
        day['timesCompletedInAWeek'] = 1
        item = day['exercises'][0]
        item.pop('placementNotes', None)
        lock_count(item, count)
        if variants:
            for suffix, reference, variant_count in (('a', 'LIBRARY_1', 1), ('b', 'LIBRARY_2', 1)):
                variant = copy.deepcopy(item)
                variant.update(definition_id=reference)
                lock_count(variant, variant_count)
                day['exercises'].append(variant)
                definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
                definition.update(id=f'press_{suffix}', name=f'Push-Up ({suffix})')
                equipment['exerciseDefinitions'].append(definition)
            lock_count(item, count - 2)
    existing = None
    if existing_counts:
        fixed = []
        for index, count in enumerate(existing_counts):
            day = copy.deepcopy(sessions[0])
            day.update(name=f'Existing {index}', exercises=[copy.deepcopy(day['exercises'][0])])
            lock_count(day['exercises'][0], count)
            fixed.append(day)
        existing = {'name': 'Existing week', 'workouts': fixed}
    return equipment, requirements, sessions, existing


def _distribution_score(result):
    return next(stage['value'] for stage in result['objectiveProgress']
                if stage['goal'] == 'distribution')


@pytest.mark.parametrize('has_incumbent', [False, True])
def test_joint_stage_deadline_preserves_verified_incumbent_without_claiming_optimality(monkeypatch, has_incumbent):
    equipment, requirements, sessions, _ = _distribution_solver_case([4])
    requirements['objectiveOrder'] = ['distribution', 'progression']
    sessions[0]['exercises'][0]['numWorkSets'] = 5
    sessions[0]['exercises'][0].pop('targetSetPrescriptions')
    sessions[0]['exercises'][0]['workSetTemplate'] = {'reps': 8}
    original = joint_planning._milp_solve
    calls = []
    def bounded(variables, features, **options):
        assert options['timeout_seconds'] == 30
        calls.append(1)
        if not has_incumbent or len(calls) > 1:
            return 'unproven', None
        status, candidate = original(variables, features, **options)
        assert candidate is not None, status
        return 'feasible', candidate
    monkeypatch.setattr(joint_planning, '_milp_solve', bounded)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    assert result['feasible'] is has_incumbent
    assert result['status'] == ('feasible' if has_incumbent else 'unproven')
    if has_incumbent:
        assert result['audit']['errors'] == []
        assert result['objectiveProgress'][-1]['status'] == 'unproven'


def test_distribution_is_invariant_to_splitting_same_session_muscle_dose_across_variants():
    consolidated = _distribution_solver_case([4])
    fragmented = _distribution_solver_case([4], variants=True)
    results = [joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
        for equipment, requirements, sessions, _ in (consolidated, fragmented)]
    assert all(result['feasible'] for result in results), results
    assert [_distribution_score(result) for result in results] == [0, 0]
    assert [result['audit']['weeklyVolume']['chest']['effective'] for result in results] == [4, 4]
    assert [result['audit']['workouts'][0]['volume']['chest']['effective'] for result in results] == [4, 4]
    assert len(results[0]['sessions'][0]['exercises']) == 1
    assert len(results[1]['sessions'][0]['exercises']) == 3


def test_distribution_minimizes_two_session_muscle_dose_imbalance():
    uneven = _distribution_solver_case([7, 1])
    balanced = _distribution_solver_case([4, 4])
    results = [joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
        for equipment, requirements, sessions, _ in (uneven, balanced)]
    assert all(result['feasible'] for result in results), results
    assert _distribution_score(results[0]) == pytest.approx(24)
    assert _distribution_score(results[1]) == pytest.approx(0)
    assert [day['volume']['chest']['effective'] for day in results[0]['audit']['workouts']] == [7, 1]
    assert [day['volume']['chest']['effective'] for day in results[1]['audit']['workouts']] == [4, 4]


def test_distribution_scales_half_credits_across_mixed_session_frequencies():
    uneven = _distribution_solver_case([3, 6])
    balanced = _distribution_solver_case([4, 4])
    results = []
    for case in (uneven, balanced):
        equipment, requirements, sessions, _ = case
        sessions[0]['timesCompletedInAWeek'] = 2
        sessions[0]['trainingDays'] = [0, 1]
        sessions[1]['trainingDays'] = [3]
        requirements['sessionsPerWeek'] = 3
        requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 12, 'maximum': 12}
        results.append(joint_planning.solve_prescribed_week(sessions, requirements, equipment,
            preserve_source_selection=True))
    assert all(result['feasible'] for result in results), results
    assert _distribution_score(results[0]) == pytest.approx(24)
    assert _distribution_score(results[1]) == pytest.approx(0)
    assert [day['volume']['chest']['effective'] for day in results[0]['audit']['workouts']] == [3, 6]
    assert results[0]['audit']['weeklyVolume']['chest']['effective'] == 12


def test_distribution_average_includes_fixed_existing_workouts():
    equipment, requirements, sessions, existing = _distribution_solver_case([2], existing_counts=[6])
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment, existing=existing,
        preserve_source_selection=True)
    assert result['feasible'], result
    assert _distribution_score(result) == pytest.approx(16)
    assert result['audit']['weeklyVolume']['chest']['effective'] == 8
    assert [day['volume']['chest']['effective'] for day in result['audit']['workouts']] == [6, 2]


def test_distribution_does_not_turn_inclusion_only_coverage_into_emphasis():
    equipment, requirements, sessions = prescription_case()
    sessions = sessions[:3]
    requirements['sessionsPerWeek'] = 3
    requirements['objectiveOrder'] = ['distribution']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 3, 'maximum': 3}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 1, 'maximum': 1}
    requirements['auditTargets']['maximumSessionSeconds'] = 5000
    requirements['requiredCoverage'] = [{'key': 'calves_weekly', 'scope': 'weekly',
        'description': 'Dedicated calf training is included weekly.'}]
    for day in sessions:
        day['exercises'] = [day['exercises'][0]]
        day['exercises'][0].pop('placementNotes', None)
        day['exercises'][0].update(numWorkSets=1,
            targetSetPrescriptions=[{'workSetIndex': 0, 'reps': 8}])
    calf = copy.deepcopy(sessions[0]['exercises'][0])
    calf.update(definition_id='LIBRARY_1', satisfiesCoverage=['calves_weekly'])
    sessions[0]['exercises'].append(calf)
    calf_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    calf_definition.update(id='zz_calf_raise', name='Calf Raise', muscleGroups=['CALVES'],
        secondaryMuscleGroups=[], exerciseCategory='ISOLATION')
    equipment['exerciseDefinitions'].append(calf_definition)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=False)

    assert result['feasible'], result
    calf_occurrences = [exercise for day in result['sessions'] for exercise in day['exercises']
        if exercise['definition_id'] == 'LIBRARY_1']
    assert len(calf_occurrences) == 1
    assert result['audit']['weeklyCoverageSets']['calves_weekly'] == 1
    assert 'calves' not in requirements['auditTargets']['weeklyEffectiveSets']


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
    sessions[0]['exercises'][0].pop('placementNotes', None)
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

    assert broad['feasible'], broad
    assert 5 <= sum(item['numWorkSets'] for item in broad['sessions'][0]['exercises']) <= 6
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
    first.pop('placementNotes', None)
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
        day['exercises'][0].pop('placementNotes', None)
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
    assert result['objectiveProgress'] == []


def test_progression_facts_have_no_dose_score_across_weekly_set_segmentation():
    def solve_case(kind):
        equipment, requirements, sessions = prescription_case()
        day = sessions[0]
        sessions = [day]
        repeated = kind == 'frequency_two'
        day['timesCompletedInAWeek'] = 2 if repeated else 1
        day['trainingDays'] = [0, 2] if repeated else [0]
        requirements['sessionsPerWeek'] = 2 if repeated else 1
        requirements['objectiveOrder'] = ['progression']
        requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 4}
        per_session_sets = 2 if repeated else 4
        requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {
            'minimum': per_session_sets, 'maximum': per_session_sets}
        original = day['exercises'][0]
        original.pop('placementNotes', None)

        def lock(item, count):
            item.update(numWorkSets=count, targetSetPrescriptions=[
                {'workSetIndex': index, 'reps': 8} for index in range(count)])

        if kind == 'fragmented':
            equivalent = copy.deepcopy(equipment['exerciseDefinitions'][0])
            equivalent['id'] = 'zz_equivalent'
            equipment['exerciseDefinitions'].append(equivalent)
            equivalent_ref = f"LIBRARY_{sorted(item['id'] for item in equipment['exerciseDefinitions']).index('zz_equivalent')}"
            lock(original, 2)
            duplicate = copy.deepcopy(original)
            duplicate['definition_id'] = equivalent_ref
            lock(duplicate, 2)
            day['exercises'] = [original, duplicate]
        else:
            lock(original, 2 if repeated else 4)
            day['exercises'] = [original]

        result = joint_planning.solve_prescribed_week(
            sessions, requirements, equipment, preserve_source_selection=True)
        assert result['feasible'], result
        assert all('penalty' not in margin for margin in result['progressionMargins'])
        assert result['audit']['weeklyVolume']['chest']['effective'] == 4
        assert [item['numWorkSets'] for item in result['sessions'][0]['exercises']] == (
            [2] if repeated else [2, 2] if kind == 'fragmented' else [4])
        return result['objectiveOrderUsed']

    scores = [solve_case(kind) for kind in ('consolidated', 'fragmented', 'frequency_two')]
    assert scores == [[], [], []]


def test_redistribution_spread_precedes_preservation_and_preserves_weekly_sets():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair
    from workout_generator_pkg.repair_contract import build_repair_contract, repair_contract_errors

    equipment, requirements, source_workouts = prescription_case()
    for day, count in zip(source_workouts, (14, 5, 5)):
        for item in day['exercises']:
            item.pop('placementNotes', None)
            item['numWorkSets'] = count
    requirements['auditTargets'].pop('maximumSessionSeconds', None)
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 20}
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 24, 'maximum': 24}
    requirements['objectiveOrder'] = ['progression']
    source = {'requirementsId': 'REQ_1', 'workouts': source_workouts}
    task = {'requirementsId': 'REQ_1', 'baseDraftId': 'REVISION_0', 'currentDraft': source}
    redistribution = {'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1', 'EXERCISE_2'],
        'workoutRefs': ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2']}
    compiled, _, references = compile_coordinated_repair({
        'requirementsId': 'REQ_1', 'baseDraftId': 'REVISION_0',
        'edits': {'exerciseRedistributions': [redistribution]}}, task, source,
        return_reference_map=True, proposal_context={})
    candidate = apply_json_patch(source, compiled['patch'])
    contract = build_repair_contract([], source, requirements, references['redistributionManifest'])
    constraint = [{key: group[key] for key in (
        'recipeSignature', 'weeklyWorkSets', 'exactSetTargets', 'targetWorkoutIndexes')}
        for group in contract['redistributions']]

    # The intent compiler already spreads seeds. Test the solver's outcome
    # constraint independently against a concentrated, equal-total incumbent.
    for day, count in zip(candidate['workouts'], (14, 5, 5)):
        day['exercises'][0]['numWorkSets'] = count
    without_outcome = joint_planning.solve_prescribed_week(candidate['workouts'], requirements,
        equipment, preserve_source_selection=True)
    solved = joint_planning.solve_prescribed_week(candidate['workouts'], requirements, equipment,
        preserve_source_selection=True, redistribution_constraints=constraint,
        reviewed_baseline_workouts=candidate['workouts'])

    concentrated = [day['exercises'][0]['numWorkSets'] for day in without_outcome['sessions']]
    redistributed = [day['exercises'][0]['numWorkSets'] for day in solved['sessions']]
    assert sum(concentrated) == sum(redistributed) == contract['redistributions'][0]['weeklyWorkSets'] == 24
    assert max(concentrated) > max(redistributed)
    assert redistributed == [8, 8, 8]
    assert [stage['goal'] for stage in solved['objectiveProgress']][:2] == [
        'redistribution_spread', 'neutral_preservation']
    assert solved['redistributionOptimization'] == {
        'goal': 'minimize_total_peak_work_sets_across_target_sessions',
        'status': 'optimal', 'optimal': True, 'totalPeakWorkSets': 8}
    assert repair_contract_errors(contract, {'workouts': solved['sessions']}) == []


def test_redistribution_solver_prohibits_matching_recipe_outside_declared_targets(monkeypatch):
    from workout_generator_pkg.repair_contract import redistribution_recipe_signature

    equipment, requirements, sessions = prescription_case()
    for day in sessions:
        for item in day['exercises']:
            item.pop('placementNotes', None)
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 18, 'maximum': 18}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 20}
    source_recipe = sessions[0]['exercises'][0]
    constraints = [{'recipeSignature': redistribution_recipe_signature(source_recipe),
        'weeklyWorkSets': 16, 'targetWorkoutIndexes': [0, 1]}]

    original_solver = joint_planning._milp_solve
    observed = []

    def capture_boundary(variables, features, **options):
        observed.extend((variables, feature) for feature in features
            if feature[0][0] == 'redistribute_outside_targets')
        return original_solver(variables, features, **options)

    monkeypatch.setattr(joint_planning, '_milp_solve', capture_boundary)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True, redistribution_constraints=constraints)

    # All executable count variants of the exact matching recipe in session two
    # are zeroed; the exact target total alone would leave that source occurrence free.
    assert observed, result
    variables, (label, lower, upper, _, coefficients) = observed[0]
    assert label == ('redistribute_outside_targets', 0)
    assert lower == float('-inf') and upper == 0
    assert coefficients
    assert all(variables[index]['domainIdentity']['workoutIndex'] == 2
        and variables[index]['domainIdentity']['definitionIds'] == [source_recipe['definition_id']]
        for index in coefficients)


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


@pytest.mark.parametrize(('preview', 'expected_preservation'), [(False, False), (True, False)])
def test_automatic_audit_keeps_candidate_selection_open_and_preview_uses_proposal_scope(
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


def test_reviewed_dose_preservation_includes_definitions_missing_from_candidate_options():
    equipment, requirements, sessions = prescription_case()
    optional_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    optional_definition['id'] = 'zz_optional'
    equipment['exerciseDefinitions'].append(optional_definition)
    for day in sessions:
        optional = copy.deepcopy(day['exercises'][0])
        optional['definition_id'] = 'LIBRARY_1'
        day['exercises'].append(optional)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        reviewed_baseline_workouts=sessions)

    assert result['feasible'], result
    reviewed_weekly_sets = {}
    solved_weekly_sets = {}
    for days, totals in ((sessions, reviewed_weekly_sets), (result['sessions'], solved_weekly_sets)):
        for day in days:
            frequency = day['timesCompletedInAWeek']
            for item in day['exercises']:
                ref = item['definition_id']
                totals[ref] = totals.get(ref, 0) + item['numWorkSets'] * frequency
    preservation = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'preservation')
    assert preservation['value'] == sum(abs(reviewed_weekly_sets.get(ref, 0) - solved_weekly_sets.get(ref, 0))
        for ref in reviewed_weekly_sets.keys() | solved_weekly_sets.keys())


def test_worker_seed_counts_are_not_a_preservation_reference(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    for day in sessions:
        day['exercises'][0].pop('placementNotes', None)
    requirements['objectiveOrder'] = ['progression']
    monkeypatch.setattr(joint_planning, 'progression_margin', lambda item, capability: {'penalty': 1})

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert result['objectiveOrderUsed'] == []
    assert result['neutralTieBreak'] is None
    assert result['reviewedDoseReferenceAvailable'] is False
    assert all(stage['goal'] not in ('neutral_preservation', 'dose_selection', 'preservation')
        for stage in result['objectiveProgress'])


def test_reviewed_weekly_dose_reference_replaces_arbitrary_worker_seed(monkeypatch):
    from workout_generator_pkg.allocation import reusable_joint_receipt
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, requirements, sessions = prescription_case()
    baseline = copy.deepcopy(sessions)
    for day in baseline:
        for item in day['exercises']:
            item['numWorkSets'] = 6
    for day in sessions:
        for item in day['exercises']:
            item.pop('placementNotes', None)
            item['numWorkSets'] = 4
    requirements['objectiveOrder'] = ['progression']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 100}

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        reviewed_baseline_workouts=baseline)

    assert result['feasible'], result
    assert result['reviewedDoseReferenceAvailable'] is True
    assert [stage['goal'] for stage in result['objectiveProgress']][-1] == 'neutral_preservation'
    assert result['objectiveProgress'][-1]['value'] == 0
    assert [item['numWorkSets'] for item in result['sessions'][0]['exercises']] == [6] * len(
        result['sessions'][0]['exercises'])

    owner = {'coordinatedJointPlanning': result,
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None}
    reused = reusable_joint_receipt(owner, 'REQ_1', result['sessions'], requirements,
        equipment, [])
    changed_reference = copy.deepcopy(baseline)
    changed_reference[0]['exercises'][0]['numWorkSets'] += 1
    rejected = reusable_joint_receipt(owner, 'REQ_1', result['sessions'], requirements,
        equipment, [], reviewed_baseline_workouts=changed_reference)

    assert reused is not None
    assert reused['reviewedDoseReference'] == result['reviewedDoseReference']
    assert rejected is None
    monkeypatch.setattr(joint_planning, 'JOINT_POLICY_DESCRIPTOR', {
        **joint_planning.JOINT_POLICY_DESCRIPTOR, 'exerciseDistribution': 'different_family_policy'})
    assert reusable_joint_receipt(owner, 'REQ_1', result['sessions'], requirements,
        equipment, []) is None


def test_objective_order_used_reports_attempted_stages_and_reuse_rejects_overclaim(monkeypatch):
    from workout_generator_pkg.allocation import reusable_joint_receipt
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['distribution', 'workload_economy', 'preservation']
    baseline = copy.deepcopy(sessions)
    solve = joint_planning._milp_solve

    def stop_before_preservation(variables, features, **options):
        if options.get('diagnostics', {}).get('goal') == 'workload_economy':
            return 'unproven', None
        return solve(variables, features, **options)

    monkeypatch.setattr(joint_planning, '_milp_solve', stop_before_preservation)
    result = joint_planning.solve_prescribed_week(
        sessions, requirements, equipment, reviewed_baseline_workouts=baseline)

    assert result['feasible'] and result['status'] == 'feasible'
    assert [stage['goal'] for stage in result['objectiveProgress']] == [
        'distribution', 'workload_economy']
    assert result['objectiveOrderUsed'] == ['distribution', 'workload_economy']
    priorities = {item['priority']: item for item in result['priorityExecution']['approvedPriorities']}
    assert priorities['preservation']['status'] == 'not_run_after_solver_stop'

    owner = {'coordinatedJointPlanning': result,
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None}
    assert reusable_joint_receipt(owner, 'REQ_1', result['sessions'], requirements,
        equipment, [], reviewed_baseline_workouts=baseline) is not None

    overstated = copy.deepcopy(owner)
    overstated['coordinatedJointPlanning']['objectiveOrderUsed'].append('preservation')
    assert reusable_joint_receipt(overstated, 'REQ_1', result['sessions'], requirements,
        equipment, [], reviewed_baseline_workouts=baseline) is None


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
    reviewed_baseline = copy.deepcopy(sessions)
    reviewed_baseline[0]['exercises'][0]['numWorkSets'] += 1
    assert joint_planning.joint_objective_input_fingerprint(sessions, requirements, equipment,
        reviewed_baseline_workouts=reviewed_baseline) != original
    assert joint_planning.joint_problem_fingerprint(sessions, requirements, equipment,
        reviewed_baseline_workouts=reviewed_baseline) != joint_planning.joint_problem_fingerprint(
            sessions, requirements, equipment)
    moved = [{'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 2}]},
        {'timesCompletedInAWeek': 1, 'exercises': [
            {'definition_id': 'LIBRARY_0', 'numWorkSets': 3}]}]
    reshuffled = list(reversed(moved))
    assert joint_planning._reviewed_dose_reference_identity(moved) == \
        joint_planning._reviewed_dose_reference_identity(reshuffled)


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
        'policy': 'approved_rules_then_compound_categories_then_isolation_then_core',
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
    assert result['candidateOrderPolicy']['policy'] == 'approved_rules_then_compound_categories_then_isolation_then_core'


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


def test_zero_lower_bound_objective_stages_count_as_optimal(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['distribution']
    solve = joint_planning._milp_solve

    def prove_zero_lower_bound(*args, **kwargs):
        status, candidate = solve(*args, **kwargs)
        return ('optimal_zero_lower_bound' if status == 'optimal' else status), candidate

    monkeypatch.setattr(joint_planning, '_milp_solve', prove_zero_lower_bound)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert result['objectiveProgress']
    assert all(stage['status'] == 'optimal_zero_lower_bound'
        for stage in result['objectiveProgress'])
    assert result['status'] == 'optimal'


def test_joint_solver_enforces_qualified_role_weekly_sets_and_frequency_weighted_sessions():
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 30, 'maximum': 36}
    second_session = copy.deepcopy(sessions[0])
    sessions[0]['trainingDays'] = [0, 1]
    second_session.update(name='Day 1', trainingDays=[2], timesCompletedInAWeek=1)
    sessions[0]['timesCompletedInAWeek'] = 2
    sessions.append(second_session)
    requirements['requiredCoverage'][0]['minimumWeeklySets'] = 18
    requirements['requiredCoverage'][0]['minimumSessions'] = 3

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert result['audit']['weeklyCoverageSets']['first'] >= 6


def test_joint_solver_rejects_unreachable_qualified_role_session_minimum():
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['sessionsPerWeek'] = 2
    second_session = copy.deepcopy(sessions[0])
    second_session.update(name='Day 1', trainingDays=[2], timesCompletedInAWeek=1)
    sessions[0]['timesCompletedInAWeek'] = 1
    sessions.append(second_session)
    requirements['requiredCoverage'][0]['minimumSessions'] = 3

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert not result['feasible']
    assert result['status'] == 'infeasible'


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


def test_joint_receipt_fingerprints_only_history_evidence_used_by_selected_recipes():
    from types import SimpleNamespace
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, requirements, sessions = prescription_case()
    equipment['exerciseDefinitions'].append({**copy.deepcopy(equipment['exerciseDefinitions'][0]), 'id': 'unused'})
    definitions = sorted(equipment['exerciseDefinitions'], key=lambda item: item['id'])
    selected_id = definitions[0]['id']
    unused_id = definitions[1]['id']
    history = SimpleNamespace(fingerprint='history-current')
    def messages_for(selected_value, unused_value):
        result = {'historyFingerprint': history.fingerprint,
            'libraryFingerprint': library_fingerprint(equipment), 'exercises': [
                {'definitionId': selected_id, 'status': 'available', 'sample': selected_value},
                {'definitionId': unused_id, 'status': 'available', 'sample': unused_value}]}
        return [
            {'role': 'assistant', 'tool_calls': [{'id': 'history', 'function': {
                'name': 'get_training_evidence', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'history', 'content': json.dumps(result)}]

    sessions[0]['exercises'] = [sessions[0]['exercises'][0]]
    before = messages_for('same', 'before')
    after_unused_lookup = messages_for('same', 'after')
    changed_selected = messages_for('changed', 'before')
    fingerprint = joint_planning.joint_problem_fingerprint(
        sessions, requirements, equipment, history, before)
    assert fingerprint == joint_planning.joint_problem_fingerprint(
        sessions, requirements, equipment, history, after_unused_lookup)
    assert fingerprint != joint_planning.joint_problem_fingerprint(
        sessions, requirements, equipment, history, changed_selected)

    objective_fingerprint = joint_planning.joint_objective_input_fingerprint(
        sessions, requirements, equipment, history, before)
    assert objective_fingerprint == joint_planning.joint_objective_input_fingerprint(
        sessions, requirements, equipment, history, after_unused_lookup)
    assert objective_fingerprint != joint_planning.joint_objective_input_fingerprint(
        sessions, requirements, equipment, history, changed_selected)


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
    blocks = [{'options': [0], 'first': 1, 'sourceRank': 0, 'recipe': {'roles': {'isolation'}, 'orderPriority': 0}},
        {'options': [3], 'first': 4, 'sourceRank': 1, 'recipe': {'roles': {'compound'}, 'orderPriority': 0}},
        {'options': [6], 'first': 7, 'sourceRank': 2, 'recipe': {'roles': {'later'}, 'orderPriority': 0}}]
    chosen = [1, 0, 0, 1, 1, 99, 1, 0, 0]
    assert joint_planning._execution_order(blocks, chosen, {}) == [0, 1, 2]
    assert joint_planning._execution_order(blocks, chosen, {'executionRules': [
        {'kind': 'order', 'before': 'later', 'after': 'isolation'}]}) == [1, 2, 0]


def test_solver_conserves_selected_destinations_without_absorbing_same_recipe_elsewhere():
    from workout_generator_pkg.repair_contract import redistribution_recipe_signature
    equipment, requirements, sessions = prescription_case()
    for day in sessions:
        for item in day['exercises']:
            item.pop('placementNotes', None)
    requirements['auditTargets'].pop('maximumSessionSeconds', None)
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 24, 'maximum': 24}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 20}
    constraints = [{'recipeSignature': redistribution_recipe_signature(sessions[0]['exercises'][0]),
        'weeklyWorkSets': 16, 'exactSetTargets': None, 'targetWorkoutIndexes': [0, 1]}]
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True, redistribution_constraints=constraints)
    assert result['feasible'], result.get('instruction')
    counts = [day['exercises'][0]['numWorkSets'] for day in result['sessions']]
    assert counts == [8, 8, 8]
