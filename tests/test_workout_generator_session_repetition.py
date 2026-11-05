import copy

import pytest

from workout_generator_pkg import allocation, joint_planning, recipe_contracts, session_drafting
from workout_generator_pkg.planning_tools import library_fingerprint
from test_workout_generator_generic_policy_outcome import tradeoff_case
from test_workout_generator_planning_tools import requirement_messages


def repetition_case(monkeypatch):
    equipment, record, draft = tradeoff_case()
    for definition in equipment['exerciseDefinitions']:
        definition.update(muscleGroups=['BACK_CALVES'], secondaryMuscleGroups=[], exerciseCategory='ISOLATION')
    annotations = {definition['id']: {'exerciseFamilyId': 'fixture_family',
        'source': 'https://example.org/reviewed-family', 'basis': 'Fixture reviewed movement identity.'}
        for definition in equipment['exerciseDefinitions']}
    monkeypatch.setattr(recipe_contracts, '_reviewed_exercise_annotations_by_definition', lambda: annotations)
    requirements = record['requirements']
    requirements.update(objectiveOrder=['volume_target', 'movement_overlap', 'workload_economy',
        'duration_economy', 'setup_economy'], objectiveTiers=[[
            {'metric': 'weekly_volume:calves', 'target': 0, 'scale': 5},
            {'metric': 'movement_overlap', 'target': 0, 'scale': 2}]])
    requirements['auditTargets']['weeklyEffectiveSets'] = {
        'calves': {'minimum': 0, 'maximum': None, 'preferredMinimum': 5, 'preferredMaximum': 8}}
    requirements['requiredCoverage'] = [{'key': 'calves', 'scope': 'eachSession', 'intent': 'inclusion',
        'description': 'Fixture direct calf work.'}]
    for item in draft['workouts'][0]['exercises']:
        item['satisfiesCoverage'] = ['calves']
    definitions = recipe_contracts.library_definitions_by_reference(equipment)
    context = {'restrictionPolicy': {}, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'sourceWorkingSetBudget': None,
        'qualifiedRoleEvidence': {ref: ['calves'] for ref in definitions},
        'exerciseFamilyEvidence': recipe_contracts.reviewed_exercise_family_evidence(equipment),
        'demandEvidence': {}, 'demandUnion': None, 'setupDefinitions': definitions}
    monkeypatch.setattr(allocation, '_joint_candidate_comparison_context', lambda *a, **k: context)
    return equipment, record, draft, context


def test_reviewed_family_overlap_reaches_solver_comparison_and_existing_choice_gate(monkeypatch):
    equipment, record, draft, context = repetition_case(monkeypatch)
    original = copy.deepcopy((record, draft))
    items = draft['workouts'][0]['exercises']
    families = context['exerciseFamilyEvidence']['familyByReference']
    assert joint_planning.overlapping_movement_pairs(items) == []
    assert joint_planning.overlapping_movement_pairs(items, families) == [('LIBRARY_0', 'LIBRARY_1')]
    assert joint_planning.overlapping_movement_pairs(items, {'LIBRARY_0': 'known'}) == []

    requirements = copy.deepcopy(record['requirements'])
    requirements.pop('objectiveTiers')
    requirements['objectiveOrder'] = ['movement_overlap']
    requirements['auditTargets']['weeklyEffectiveSets']['calves'].update(minimum=5, maximum=6, preferredMaximum=6)
    result = joint_planning.solve_prescribed_week(draft['workouts'], requirements, equipment,
        preserve_source_selection=True)
    assert result['feasible'], result
    stage = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'movement_overlap')
    assert stage['value'] == 1
    assert joint_planning._joint_candidate_objective_costs(
        {'workouts': result['sessions'], 'audit': result['audit']}, requirements, context)['movement_overlap'] == 1

    result = session_drafting._fresh_development_tradeoff(draft, record, equipment,
        requirement_messages(record), None, None, {})
    assert result.get('userQuestion'), result
    comparison = result['jointCandidateComparison']
    assert comparison['programmingTradeoff']['status'] == 'requires_programming_decision'
    assert comparison['baselineAuditErrors'] == comparison['candidateAuditErrors'] == []
    artifacts = comparison['programmingArtifacts']
    selected = artifacts['candidate']['submittedDraft']['workouts'][0]['exercises']
    assert len(selected) == 1 and selected[0]['numWorkSets'] == 3
    assert comparison['programmingTradeoff']['developmentChanges'] == []
    assert comparison['programmingTradeoff']['goalTiers']
    assert comparison['programmingTradeoff']['volumeChanges'][0]['baselineEffectiveSets'] == 5
    assert '5 -> 3' in result['userQuestion']['question']
    assert len(result['programmingDecisionChoices']) == 2
    assert (record, draft) == original


def test_dose_preserving_consolidation_is_applied_without_an_unnecessary_choice(monkeypatch):
    equipment, record, draft, _ = repetition_case(monkeypatch)
    record['requirements']['executionRules'][0]['maximumSets'] = 6
    for item in draft['workouts'][0]['exercises']:
        item['allocationBounds']['maximum'] = 6
    result = session_drafting._fresh_development_tradeoff(draft, record, equipment,
        requirement_messages(record), None, None, {})
    selected = result['proposedSubmission']['workouts'][0]['exercises']
    assert len(selected) == 1 and selected[0]['numWorkSets'] == 5
    assert result['audit']['weeklyVolume']['calves']['effective'] == 5
    assert 'userQuestion' not in result
    assert result['jointPlanning'] == {}  # The source solver proof does not describe this changed artifact.


def test_consolidation_rebuilds_affected_superset_rest_without_changing_source(monkeypatch):
    equipment, record, draft, _ = repetition_case(monkeypatch)
    for index, item in enumerate(draft['workouts'][0]['exercises']):
        item.update(numWorkSets=2, superset='PAIR', restBetweenSetsSeconds=0,
            restAfterSupersetExerciseSeconds=60 if index else 0)
    original = copy.deepcopy(draft)
    options = list(session_drafting._same_family_consolidations(draft, record['requirements'], equipment))
    assert options and draft == original
    for option in options:
        items = option['workouts'][0]['exercises']
        assert len(items) == 1 and items[0]['numWorkSets'] == 3
        assert items[0]['superset'] is None
        assert items[0]['restAfterSupersetExerciseSeconds'] == 0
        assert items[0]['restBetweenSetsSeconds'] >= 60


@pytest.mark.parametrize('blocked', ['hard_floor', 'exact_prescription', 'unknown_family'])
def test_consolidation_never_weakens_hard_or_prescription_evidence(monkeypatch, blocked):
    equipment, record, draft, _ = repetition_case(monkeypatch)
    if blocked == 'hard_floor':
        record['requirements']['auditTargets']['weeklyEffectiveSets']['calves']['minimum'] = 5
        result = session_drafting._fresh_development_tradeoff(draft, record, equipment,
            requirement_messages(record), None, None, {})
        assert not result.get('programmingDecisionChoices') and not result.get('userQuestion')
    else:
        if blocked == 'exact_prescription':
            for item in draft['workouts'][0]['exercises']:
                item['targetSetPrescriptions'] = [{'workSetIndex': i, 'reps': 8} for i in range(item['numWorkSets'])]
        else:
            monkeypatch.setattr(recipe_contracts, '_reviewed_exercise_annotations_by_definition', lambda: {})
        assert list(session_drafting._same_family_consolidations(draft, record['requirements'], equipment)) == []
