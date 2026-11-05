import copy

import pytest

from workout_generator_pkg import joint_planning
from test_workout_generator_planning_tools import planning_case


def pairing_case():
    equipment, requirements, _, draft = planning_case()
    requirements.update(sessionsPerWeek=1, objectiveOrder=['duration_economy'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 3, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 3, 'maximum': 6}
    requirements['requiredCoverage'] = [
        {'key': 'chest', 'scope': 'eachSession', 'description': 'Direct chest work'},
        {'key': 'quads', 'scope': 'eachSession', 'description': 'Direct quad work'},
    ]
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 3, 'maximumSets': 3}]
    first = draft['workouts'][0]['exercises'][0]
    first.pop('placementNotes', None)
    first.update(numWorkSets=3, satisfiesCoverage=['chest'], restBetweenSetsSeconds=90,
        restAfterExerciseSeconds=0, setupSeconds=0, superset=None)
    second = copy.deepcopy(first)
    second.update(definition_id='LIBRARY_1', satisfiesCoverage=['quads'])
    definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    definition.update(id='squat', name='Bodyweight Squat', muscleGroups=['FRONT_QUADRICEPS'],
        secondaryMuscleGroups=['BACK_GLUTEAL'])
    equipment['exerciseDefinitions'].append(definition)
    sessions = [copy.deepcopy(draft['workouts'][0])]
    sessions[0].update(name='Day A', trainingDays=[0], timesCompletedInAWeek=1)
    sessions[0]['exercises'] = [first, second]
    return equipment, requirements, sessions


@pytest.mark.parametrize('transition, round_rest', [(0, 60), (20, 75)])
def test_generated_superset_pair_uses_approved_recovery_without_mutating_sources(transition, round_rest):
    first = {'definition_id': 'FIRST', 'numWorkSets': 2, 'restBetweenSetsSeconds': 90,
        'restAfterExerciseSeconds': 45, 'restAfterSupersetExerciseSeconds': 0}
    second = {'definition_id': 'SECOND', 'numWorkSets': 2, 'restBetweenSetsSeconds': 120,
        'restAfterExerciseSeconds': 75, 'restAfterSupersetExerciseSeconds': 0}
    original_first, original_second = copy.deepcopy(first), copy.deepcopy(second)
    requirements = {'executionRules': [
        {'kind': 'rest', 'context': context, 'coverageKey': None,
            'minimumSeconds': minimum, 'maximumSeconds': maximum}
        for context, minimum, maximum in [('supersetTransition', transition, transition),
            ('supersetRound', round_rest, 120)]]}

    pair = joint_planning._generated_superset_pair(first, second, requirements,
        {'FIRST': {}, 'SECOND': {}})

    assert pair[0]['restAfterSupersetExerciseSeconds'] == transition
    assert pair[0]['restAfterExerciseSeconds'] == 0
    assert pair[1]['restAfterSupersetExerciseSeconds'] == round_rest
    assert pair[1]['restAfterExerciseSeconds'] == 75
    assert (first, second) == (original_first, original_second)


@pytest.mark.parametrize('exact_targets', [False, True])
def test_two_set_pair_with_zero_prescribed_transition_saves_native_time(exact_targets):
    equipment, requirements, sessions = pairing_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] = 2
    requirements['auditTargets']['perSessionEffectiveSets']['chest']['minimum'] = 2
    requirements['executionRules'][0].update(minimumSets=2, maximumSets=2)
    requirements['executionRules'].extend([
        {'kind': 'rest', 'context': 'supersetTransition', 'coverageKey': None,
            'minimumSeconds': 0, 'maximumSeconds': 0},
        {'kind': 'rest', 'context': 'supersetRound', 'coverageKey': None,
            'minimumSeconds': 60, 'maximumSeconds': 120}])
    for item in sessions[0]['exercises']:
        item.update(numWorkSets=2, restBetweenSetsSeconds=60)
        if exact_targets:
            item['targetSetPrescriptions'] = [{'workSetIndex': index, 'reps': 8} for index in range(2)]
    _, baseline = joint_planning._audit_raw({'requirementsId': 'test', 'name': 'Test',
        'workouts': sessions}, equipment, requirements, None, True)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)

    assert result['feasible'], result
    exercises = result['sessions'][0]['exercises']
    assert [item['numWorkSets'] for item in exercises] == [2, 2]
    assert [item['restAfterSupersetExerciseSeconds'] for item in exercises] == [0, 60]
    assert exercises[0]['superset'] is not None and exercises[0]['superset'] == exercises[1]['superset']
    assert result['audit']['weeklyVolume'] == baseline['weeklyVolume']
    assert baseline['workouts'][0]['estimatedSeconds'] - result['audit']['workouts'][0]['estimatedSeconds'] == 60
    assert not result['audit']['errors']


@pytest.mark.parametrize('reviewed', [False, True])
def test_solver_enumerates_compatible_pair_and_keeps_exact_occurrence_lineage(reviewed):
    equipment, requirements, sessions = pairing_case()

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        reviewed_baseline_workouts=sessions if reviewed else None)

    assert result['feasible'], result
    exercises = result['sessions'][0]['exercises']
    assert len(exercises) == 2
    assert exercises[0]['superset'] == exercises[1]['superset']
    assert result['occurrenceLineage'] == [[[0, 0], [0, 1]]]
    assert sum(item['numWorkSets'] for item in exercises) == 6
    assert result['supersetCandidates']['codeGeneratedCandidateCount'] == 1
    assert result['supersetCandidates']['compiledCandidateCount'] == 1
    assert result['supersetCandidates']['selectedCodeGeneratedGroupCount'] == 1
    assert result['supersetCandidates']['selectedSourceGroupCount'] == 0
    assert not result['audit']['errors']


def test_preserved_source_selection_can_group_the_exact_retained_occurrences():
    equipment, requirements, sessions = pairing_case()

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)

    assert result['feasible'], result
    exercises = result['sessions'][0]['exercises']
    assert [item['definition_id'] for item in exercises] == ['LIBRARY_0', 'LIBRARY_1']
    assert [item['numWorkSets'] for item in exercises] == [3, 3]
    assert exercises[0]['superset'] is not None and exercises[0]['superset'] == exercises[1]['superset']
    assert result['occurrenceLineage'] == [[[0, 0], [0, 1]]]
    assert result['supersetCandidates']['codeGeneratedCandidateCount'] == 1
    assert result['supersetCandidates']['selectedCodeGeneratedGroupCount'] == 1


def test_solver_reports_and_rejects_calibrated_pair_with_shared_physical_load():
    equipment, requirements, sessions = pairing_case()
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'type': 'BARBELL', 'name': 'Barbell'}]
    for definition in equipment['exerciseDefinitions']:
        definition.update(equipmentId='EQUIPMENT_0', exerciseType='WEIGHT', requiresLoadCalibration=True,
            bodyWeightPercentage=None)
    for item in sessions[0]['exercises']:
        item['workSetTemplate'] = {'reps': 10}

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert result['supersetCandidates']['codeGeneratedCandidateCount'] == 0
    assert result['supersetCandidates']['rejectionCounts']['shared_equipment_load_unverified'] == 1
    assert all(item['superset'] is None for item in result['sessions'][0]['exercises'])


def test_source_occurrence_identity_does_not_alias_same_slot_from_different_menus():
    equipment, requirements, sessions = pairing_case()
    requirements.update(sessionsPerWeek=2, objectiveOrder=['duration_economy'])
    requirements['auditTargets']['weeklyEffectiveSets'] = {
        'chest': {'minimum': 3, 'maximum': 6}, 'quads': {'minimum': 3, 'maximum': 6}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {
        'chest': {'minimum': 3, 'maximum': 6}, 'quads': {'minimum': 3, 'maximum': 6}}
    requirements['requiredCoverage'] = [
        {'key': 'chest', 'scope': 'eachSession', 'description': 'Chest work'},
        {'key': 'quads', 'scope': 'eachSession', 'description': 'Quadriceps work'}]
    chest, quads = sessions[0]['exercises']
    chest_definition = next(item for item in equipment['exerciseDefinitions'] if item['id'] == 'press')
    quads_definition = next(item for item in equipment['exerciseDefinitions'] if item['id'] == 'squat')
    chest_definition.update(muscleGroups=['FRONT_CHEST'], secondaryMuscleGroups=[])
    quads_definition.update(muscleGroups=['FRONT_QUADRICEPS'], secondaryMuscleGroups=[])
    chest.update(satisfiesCoverage=['chest'])
    quads.update(satisfiesCoverage=['quads'])
    sessions = [copy.deepcopy(sessions[0]), copy.deepcopy(sessions[0])]
    sessions[0]['exercises'] = [chest]
    sessions[1].update(name='Day B', trainingDays=[2])
    sessions[1]['exercises'] = [quads]

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    for workout in result['sessions']:
        roles = {role for item in workout['exercises'] for role in item['satisfiesCoverage']}
        assert {'chest', 'quads'} <= roles
        assert len(workout['exercises']) == 2
    assert not result['audit']['errors']


def test_compiled_recipe_cache_includes_source_work_set_count():
    equipment, requirements, sessions = pairing_case()
    requirements.update(sessionsPerWeek=2, objectiveOrder=['duration_economy'])
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 2, 'maximumSets': 3}]
    requirements['requiredCoverage'] = [
        {'key': 'chest', 'scope': 'eachSession', 'description': 'Chest work'}]
    first = copy.deepcopy(sessions[0]['exercises'][0])
    first.update(satisfiesCoverage=['chest'], numWorkSets=2,
        targetSetPrescriptions=[{'workSetIndex': 0, 'reps': 8}, {'workSetIndex': 1, 'reps': 8}])
    second = copy.deepcopy(first)
    second['numWorkSets'] = 3
    sessions = [copy.deepcopy(sessions[0]), copy.deepcopy(sessions[0])]
    sessions[0]['exercises'] = [first]
    sessions[1].update(name='Day B', trainingDays=[2])
    sessions[1]['exercises'] = [second]

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['supersetCandidates']['uniqueRecipeCompileCount'] >= 2
    assert result['supersetCandidates']['compileCacheHits'] == 0
