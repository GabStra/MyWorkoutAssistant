import copy
import json
import pytest

from workout_generator_pkg import session_drafting as drafting
from workout_generator_pkg.planning_tools import library_fingerprint
from test_workout_generator_planning_tools import planning_case, requirement_messages


def tradeoff_case():
    equipment, _, record, draft = planning_case()
    donor = equipment['exerciseDefinitions'][0]
    donor.update(id='a', name='Fixture press', secondaryMuscleGroups=[])
    recipient = copy.deepcopy(donor)
    recipient.update(id='b', name='Fixture lateral pattern', muscleGroups=['SIDE_DELTS'],
                     exerciseCategory='ISOLATION')
    equipment['exerciseDefinitions'].append(recipient)
    first = draft['workouts'][0]['exercises'][0]
    first.pop('placementNotes', None)
    first.update(numWorkSets=3, allocationBounds={'minimum': 2, 'maximum': 3},
                 satisfiesCoverage=['horizontal_push'])
    second = copy.deepcopy(first)
    second.update(definition_id='LIBRARY_1', numWorkSets=2, satisfiesCoverage=['lateral_delt'])
    draft['workouts'][0]['exercises'].append(second)
    requirements = {'sessionsPerWeek': 1, 'preferenceResolution': 'explicit_tradeoffs',
        'objectiveOrder': ['volume_target', 'workload_economy', 'duration_economy'],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 0, 'maximum': None,
                         'preferredMinimum': 3, 'preferredMaximum': 15}}, 'perSessionEffectiveSets': {},
                         'maximumSessionSeconds': 2000},
        'requiredCoverage': [{'key': 'horizontal_push', 'scope': 'weekly', 'intent': 'inclusion'},
                             {'key': 'lateral_delt', 'scope': 'weekly', 'intent': 'development'}],
        'executionRules': [{'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 3}]}
    for rule in requirements['requiredCoverage']:
        rule['description'] = 'Fixture requested movement.'
    for rule in requirements['executionRules']:
        rule['description'] = 'Fixture approved count range.'
    record['requirements'] = requirements
    record['restrictionPolicy'] = {}
    return equipment, record, draft


def native_choice_case(monkeypatch):
    from workout_generator_pkg import allocation
    equipment, record, draft = tradeoff_case()
    requirements = record['requirements']
    context = {'restrictionPolicy': record['restrictionPolicy'],
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'sourceWorkingSetBudget': {'variableWeeklyWorkingSets': 5, 'source': 'fixture'},
        'qualifiedRoleEvidence': {'LIBRARY_0': ['horizontal_push'], 'LIBRARY_1': ['lateral_delt']},
        'demandEvidence': {}, 'demandUnion': None,
        'setupDefinitions': {'LIBRARY_0': equipment['exerciseDefinitions'][0],
                             'LIBRARY_1': equipment['exerciseDefinitions'][1]}}
    monkeypatch.setattr(allocation, '_joint_candidate_comparison_context', lambda *a, **k: context)
    result = drafting._fresh_development_tradeoff(draft, record, equipment,
        requirement_messages(record), None, context['sourceWorkingSetBudget'], {})
    return equipment, record, draft, result, requirement_messages(record)


def test_native_count_tradeoff_uses_existing_gate_and_preserves_workload(monkeypatch):
    equipment, record, draft, result, _ = native_choice_case(monkeypatch)
    assert result.get('userQuestion'), result
    comparison = result['jointCandidateComparison']
    assert comparison['baselineAuditErrors'] == comparison['candidateAuditErrors'] == []
    assert comparison['programmingTradeoff']['developmentChanges'] == [
        {'role': 'lateral_delt', 'baselineWorkingSets': 2.0, 'candidateWorkingSets': 3.0}]
    artifacts = comparison['programmingArtifacts']
    assert sum(e['numWorkSets'] for e in artifacts['candidate']['submittedDraft']['workouts'][0]['exercises']) == 5
    assert artifacts['baseline']['submittedDraft'] == draft
    assert set(result['programmingDecisionChoices']) == {
        'CONCERN_programming_retain_baseline', 'CONCERN_programming_use_candidate'}
    assert draft['workouts'][0]['exercises'][0]['numWorkSets'] == 3


def test_count_domain_keeps_exact_arrays_and_can_split_optional_group():
    equipment, record, draft = tradeoff_case()
    grouped = copy.deepcopy(draft)
    for item in grouped['workouts'][0]['exercises']:
        item.update(superset='pair', numWorkSets=2, restBetweenSetsSeconds=0,
                    restAfterSupersetExerciseSeconds=60)
    donor = copy.deepcopy(draft['workouts'][0]['exercises'][0])
    grouped['workouts'][0]['exercises'].append(donor)
    before = copy.deepcopy(grouped)
    options = list(drafting._one_set_development_transfers(grouped, record['requirements'], equipment))
    assert options and any(any(item['definition_id'] == 'LIBRARY_1' and item['numWorkSets'] == 3
        and item['superset'] is None and item['restBetweenSetsSeconds'] == 120
        for item in option['workouts'][0]['exercises']) for option in options)
    assert all(sum(e['numWorkSets'] for e in option['workouts'][0]['exercises']) == 7 for option in options)
    assert grouped == before
    exact = copy.deepcopy(draft)
    exact['workouts'][0]['exercises'][0]['targetSetPrescriptions'] = [
        {'workSetIndex': index, 'reps': 8} for index in range(3)]
    assert list(drafting._one_set_development_transfers(exact, record['requirements'], equipment)) == []


@pytest.mark.parametrize('selection', ['baseline', 'candidate'])
def test_fresh_frontdoor_resumes_saved_choice_before_any_worker_or_solver(monkeypatch, selection):
    from workout_generator_pkg import planning_decisions, repair_execution
    equipment, record, draft = tradeoff_case()
    preparation = {'preparationId': 'prepared', 'requirementsId': record['requirementsId'],
        'baseDraftId': None, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'draftingVersion': drafting.DRAFTING_VERSION,
        'sourceMessages': []}
    candidate = copy.deepcopy(draft)
    candidate['workouts'][0]['exercises'][0]['numWorkSets'] = 2
    candidate['workouts'][0]['exercises'][1]['numWorkSets'] = 3
    def audited(value):
        return {'requirementsId': record['requirementsId'], 'submittedDraft': value,
            'audit': {'issues': [], 'errors': []}, 'libraryFingerprint': library_fingerprint(equipment),
            'historyFingerprint': None}
    baseline, alternative = audited(draft), audited(candidate)
    previous = {**preparation, **alternative, 'jointPlanning': {'solvedPrescriptionHash': 'baseline-only'},
        'proposedSubmission': draft, 'userQuestion': {'question': 'choose'},
        'jointCandidateComparison': {'baselineAcceptanceScope': planning_decisions.candidate_acceptance_scope(baseline),
            'programmingArtifacts': {'baseline': baseline, 'candidate': alternative}}}
    monkeypatch.setattr(drafting, 'require_approved_requirements', lambda messages: None)
    monkeypatch.setattr(drafting, 'latest_draft_submission', lambda *a: (None, None))
    monkeypatch.setattr(drafting, 'accepted_menu_preparation', lambda *a: None)
    monkeypatch.setattr(drafting, '_latest_result', lambda messages, name: (-1, {
        'set_workout_requirements': record, 'prepare_workout_sessions': preparation,
        'draft_workout_sessions': previous}[name]))
    monkeypatch.setattr(repair_execution, 'resolved_programming_selection',
                        lambda *a: {'decisionId': 'DECISION_1', 'selection': selection})
    monkeypatch.setattr(drafting, '_preparation_schedule_errors',
        lambda *a, **k: pytest.fail('Resume reached preparation/qualification instead of saved choice.'))
    messages = [{'role': 'user', 'content': 'Use the candidate option.' if selection == 'candidate' else 'Keep the baseline option.'}]
    result = drafting.draft_workout_sessions(None, {'preparationId': 'prepared'}, messages, equipment, {})
    assert result['proposedSubmission'] == (candidate if selection == 'candidate' else draft)
    assert result['programmingDecision']['selection'] == selection
    assert 'userQuestion' not in result
    if selection == 'candidate':
        assert 'jointPlanning' not in result
        assert result['jointCandidateComparison']['programmingArtifacts']['baseline']['jointPlanning']['solvedPrescriptionHash'] == 'baseline-only'
    assert 'independent semantic review and confirmation' in result['instruction']


def test_selected_fresh_artifact_survives_actual_audit_without_requalification_or_solve(monkeypatch):
    from workout_generator_pkg import allocation, interactive_shell, joint_planning
    equipment, record, _, pending, messages = native_choice_case(monkeypatch)
    selected_draft = pending['jointCandidateComparison']['programmingArtifacts']['candidate']['submittedDraft']
    scope = pending['programmingDecisionChoices']['CONCERN_programming_use_candidate']['acceptedCandidateScope']
    worker = {**pending, 'proposedSubmission': selected_draft,
        'programmingDecision': {'decisionId': 'DECISION_0', 'selection': 'candidate'},
        'recipeQualification': {'contracts': [{'definition_id': 'unused-menu-reference'}]}}
    def store(name, payload, identifier):
        messages.extend([{'role': 'assistant', 'tool_calls': [{'id': identifier,
            'function': {'name': name, 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': identifier, 'content': json.dumps(payload)}])
    store('draft_workout_sessions', worker, 'saved-choice')
    messages.append({'role': 'user', 'content': 'Use the candidate, and I confirm capability for both fixture bodyweight configurations.'})
    decisions = {'DECISION_0': {'topic': 'Programming choice', 'choice': 'Use candidate',
        'sourceReferences': ['SOURCE_0'], 'acceptedConcernGroupId': 'CONCERN_programming_use_candidate',
        'acceptedCandidateScope': scope}}
    for index in range(2):
        decisions[f'DECISION_{index + 1}'] = {'topic': 'Fixture capability', 'choice': 'Confirmed exact fixture setup.',
            'confirmedCapabilityReference': f'LIBRARY_{index}',
            'capabilityLibraryFingerprint': library_fingerprint(equipment)}
    store('record_planning_decisions', {'passed': True, 'decisionReview': {'passed': True},
        'decisions': decisions}, 'selection-decision')
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week',
        lambda *a, **k: pytest.fail('An accepted exact artifact was reoptimized.'))
    monkeypatch.setattr(allocation, 'qualify_coordinated_candidate',
        lambda *a, **k: pytest.fail('An accepted exact artifact was requalified.'))
    reviewed = []
    def review(client, result, *args, **kwargs):
        reviewed.append(copy.deepcopy(result))
        return result
    monkeypatch.setattr(interactive_shell, 'review_draft', review)
    response = interactive_shell.handle_function_call(None, messages, 'audit_workout_plan',
        copy.deepcopy(selected_draft), equipment)
    result = json.loads(response['result'])
    assert result['passed'], result.get('errors')
    assert result['submittedDraft'] == selected_draft
    assert result['programmingDecision'] == {'decisionId': 'DECISION_0', 'selection': 'candidate'}
    assert not result.get('coordinatedJointPlanning') and not result.get('automaticAllocation')
    assert reviewed and reviewed[0]['submittedDraft'] == selected_draft
    assert 'review' not in result  # The fixture observed review entry; it did not manufacture a review approval.
    changed = copy.deepcopy(result)
    changed['submittedDraft']['workouts'][0]['exercises'][0]['numWorkSets'] += 1
    assert drafting.accepted_fresh_programming_artifact(changed, equipment, messages) is None
    changed = copy.deepcopy(result)
    changed['audit']['errors'].append({'code': 'fixture_native_failure'})
    assert drafting.accepted_fresh_programming_artifact(changed, equipment, messages) is None
