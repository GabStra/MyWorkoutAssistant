import pytest

from workout_generator_pkg.generation_audit import (
    _setup_resource_transition, executable_setup_evidence, session_setup_evidence, setup_resource_profile,
)
from workout_generator_pkg import joint_planning


def test_missing_resource_references_remain_unknown_for_optimization():
    profile = setup_resource_profile({})
    assert profile['resourceIds'] == []
    assert profile['resourceEvidence'] == 'no_declared_resources'
    assert profile['physicalConfigurationKnown'] is False


def test_exact_same_and_changed_loads_are_distinguished_but_calibration_stays_unknown():
    definition = {'id': 'barbell_row', 'equipmentId': 'bar',
        'requiredAccessoryEquipmentIds': [], 'exerciseType': 'WEIGHT'}
    first = setup_resource_profile(definition, {'definition_id': 'barbell_row',
        'targetSetPrescriptions': [{'workSetIndex': 0, 'weight': 40, 'reps': 8}],
        'requiresLoadCalibration': False})
    same = setup_resource_profile(definition, {'definition_id': 'barbell_row',
        'targetSetPrescriptions': [{'workSetIndex': 0, 'weight': 40, 'reps': 8}],
        'requiresLoadCalibration': False})
    changed = setup_resource_profile(definition, {'definition_id': 'barbell_row',
        'targetSetPrescriptions': [{'workSetIndex': 0, 'weight': 45, 'reps': 8}],
        'requiresLoadCalibration': False})
    calibration = setup_resource_profile(definition, {'definition_id': 'barbell_row',
        'targetSetPrescriptions': [{'workSetIndex': 0, 'weight': 40, 'reps': 8}],
        'requiresLoadCalibration': True})

    assert _setup_resource_transition(first, same)['configurationRelation'] == 'known_same'
    assert _setup_resource_transition(first, changed)['configurationRelation'] == 'known_changed'
    assert _setup_resource_transition(first, calibration)['configurationRelation'] == 'unknown_configuration'
    assert calibration['preparationTaskKey']['configuration'] == 'unknown'
    assert first['physicalConfigurationKnown'] is False


def test_setup_evidence_reports_resource_reuse_returns_and_unknown_physical_setup():
    sources = {
        'squat': ({'numWorkSets': 3}, {}, {}, {'libraryDefinitionId': 'squat'}),
        'raise': ({'numWorkSets': 2}, {}, {}, {'libraryDefinitionId': 'raise'}),
        'crunch': ({'numWorkSets': 2}, {}, {}, {'libraryDefinitionId': 'crunch'}),
        'press': ({'numWorkSets': 3}, {}, {}, {'libraryDefinitionId': 'press'}),
    }
    definitions = {
        'squat': {'id': 'squat', 'equipmentId': 'bar', 'requiredAccessoryEquipmentIds': ['bench']},
        'raise': {'id': 'raise', 'equipmentId': 'dumbbells', 'requiredAccessoryEquipmentIds': []},
        'crunch': {'id': 'crunch', 'equipmentId': 'cable', 'requiredAccessoryEquipmentIds': ['rope']},
        'press': {'id': 'press', 'equipmentId': 'bar', 'requiredAccessoryEquipmentIds': ['bench']},
    }
    artifact = {'components': [
        {'type': 'Exercise', 'id': 'squat'},
        {'type': 'Superset', 'exercises': [{'id': 'raise'}, {'id': 'crunch'}]},
        {'type': 'Exercise', 'id': 'press'},
    ]}

    evidence = session_setup_evidence(artifact, sources, definitions)

    assert evidence['blockCount'] == 3
    assert evidence['supersetGroupCount'] == 1
    assert evidence['distinctEquipmentIds'] == ['bar', 'cable', 'dumbbells']
    assert evidence['distinctAccessoryIds'] == ['bench', 'rope']
    assert evidence['resourceReferenceReturnCount'] == 2
    block_transitions = [item for item in evidence['transitions'] if item['scope'] != 'within_exercise']
    assert block_transitions[0]['scope'] == 'between_blocks'
    assert block_transitions[0]['resourceSelection'] == 'changed_references'
    assert block_transitions[1]['scope'] == 'superset_member'
    assert block_transitions[1]['scheduledRepeatsPerRound'] == 2
    assert block_transitions[1]['scheduledTransitionCount'] == 1
    assert block_transitions[2]['scope'] == 'superset_round_return'
    assert block_transitions[2]['scheduledTransitionCount'] == 1
    assert block_transitions[3]['scope'] == 'superset_member'
    assert evidence['scheduledTransitionOccurrenceCount'] == 9
    assert block_transitions[-1]['scope'] == 'between_blocks'
    assert block_transitions[-1]['resourceSelection'] == 'changed_references'
    assert all(item['configurationRelation'] == 'unknown_configuration'
        and item['physicalConfigurationKnown'] is False
        for item in evidence['transitions'])
    assert 'not proven station returns' in evidence['interpretation']


@pytest.mark.parametrize('second_load, relation', [(40, 'known_same'), (60, 'known_changed')])
def test_known_load_transition_is_reported_across_distinct_exercises_sharing_equipment(second_load, relation):
    first = setup_resource_profile({'id': 'row', 'equipmentId': 'bar', 'exerciseType': 'WEIGHT'}, {
        'definition_id': 'row', 'requiresLoadCalibration': False,
        'targetSetPrescriptions': [{'weight': 40}]})
    second = setup_resource_profile({'id': 'press', 'equipmentId': 'bar', 'exerciseType': 'WEIGHT'}, {
        'definition_id': 'press', 'requiresLoadCalibration': False,
        'targetSetPrescriptions': [{'weight': second_load}]})

    transition = _setup_resource_transition(first, second)

    assert transition['configurationRelation'] == relation
    assert transition['resourceSelection'] == 'same_references'
    assert transition['preparationTaskRelation'] == 'different_task'
    assert transition['physicalConfigurationKnown'] is False


@pytest.mark.parametrize('middle,last,groups,changes,reuses', [
    ('other', 'flat', None, 0, 1),
    ('other', 'incline', None, 1, 0),
    ('unannotated', 'flat', None, 0, 0),
    ('partial', 'flat', None, 0, 0),
    ('other', 'flat', [['BENCH', 'OTHER']], 0, 0),
])
def test_sourced_required_setup_states_track_returns_without_inventing_actual_configurations(
        middle, last, groups, changes, reuses):
    definitions = {name: {'id': name, 'equipmentId': 'BAR', 'exerciseType': 'WEIGHT',
        'requiredAccessoryEquipmentIds': ['BENCH'], 'requiresLoadCalibration': True,
        'reviewedExecution': {'setupConfiguration': [{'resourceId': 'BENCH',
            'state': {'angleDegrees': angle, 'support': 'bench'},
            'source': 'https://example.test/reviewed-setup', 'basis': 'Controlled required-state fixture.'}]}}
        for name, angle in [('flat', 0), ('incline', 45)]}
    definitions['other'] = {'id': 'other', 'equipmentId': 'OTHER', 'exerciseType': 'WEIGHT'}
    definitions['unannotated'] = {'id': 'unannotated', 'equipmentId': 'BENCH', 'exerciseType': 'WEIGHT'}
    definitions['partial'] = {**definitions['flat'], 'id': 'partial', 'reviewedExecution': {
        'setupConfiguration': [{**definitions['flat']['reviewedExecution']['setupConfiguration'][0],
            'state': {'angleDegrees': 0}}]}}
    sources = [{'definition_id': name, 'numWorkSets': 1, 'requiresLoadCalibration': True,
        'workSetTemplate': {'weight': 0}} for name in ('flat', middle, last)]
    evidence = executable_setup_evidence({'exercises': sources}, definitions, groups)
    assert evidence['knownPhysicalConfigurationChanges'] == changes
    assert evidence['sameDeclaredPhysicalConfigurationStates'] == reuses
    assert evidence['unknownPhysicalConfigurationTransitions'] > 0
    assert evidence['physicalConfigurationEvidencePartial'] is True
    assert evidence['physicalResourceIndependenceVerified'] is False
    for source in sources:
        profile = setup_resource_profile(definitions[source['definition_id']], source)
        assert profile['physicalConfigurationKnown'] is False
        assert profile['configurationStatus'] == 'unknown'
    transition = _setup_resource_transition(setup_resource_profile(definitions['flat']),
        setup_resource_profile(definitions['incline']))
    assert transition['physicalConfigurationRelation'] == 'required_change'
    assert transition['configurationRelation'] == 'unknown_configuration'
    required = next(row['requiredConfiguration'] for row in evidence['physicalConfigurationTransitions']
        if row['requiredConfiguration'])
    assert required['source'] == 'https://example.test/reviewed-setup'


@pytest.mark.parametrize('groups', [[], [['BENCH', 'OTHER']]])
def test_execution_comparison_preserves_shared_physical_setup_evidence_and_station_scope(groups):
    definitions = {name: {'id': name, 'equipmentId': 'BENCH', 'exerciseType': 'WEIGHT',
        'reviewedExecution': {'setupConfiguration': [{'resourceId': 'BENCH', 'state': {'angle': angle},
            'source': 'https://example.test/reviewed-setup', 'basis': 'Controlled requirement fixture.'}]}}
        for name, angle in [('flat', 0), ('incline', 45)]}
    definitions['other'] = {'id': 'other', 'equipmentId': 'OTHER', 'exerciseType': 'WEIGHT'}
    workout = {'timesCompletedInAWeek': 2, 'exercises': [{'definition_id': name, 'numWorkSets': 1,
        'requiresLoadCalibration': True, 'workSetTemplate': {'weight': 0}} for name in ('flat', 'other', 'incline')]}
    requirements = {'executionRules': [{'kind': 'supersetNoReconfiguration', 'sharedResourceGroups': groups}]}
    expected = executable_setup_evidence(workout, definitions, groups)
    projected = joint_planning._candidate_setup_transition_evidence(workout, definitions, requirements)
    result = joint_planning.evaluate_audited_execution({'workouts': [workout],
        'audit': {'workouts': [{'estimatedSeconds': 0}]}}, definitions, requirements)
    assert result['sessions'][0]['setup'] == projected
    assert all(expected[key] == value for key, value in projected.items())
    assert result['weeklyKnownPhysicalConfigurationChanges'] == (0 if groups else 2)
    assert result['weeklyUnknownPhysicalConfigurationTransitions'] == 2 * expected['unknownPhysicalConfigurationTransitions']
    assert projected['physicalConfigurationTransitions'][-1]['requiredConfiguration']['source'] == (
        'https://example.test/reviewed-setup')


def test_superset_evidence_counts_interleaved_work_from_earlier_rounds():
    from workout_generator_pkg.generation_audit import session_interference_evidence

    members = [{'id': 'rdl'}, {'id': 'nordic'}]
    sources = {
        'rdl': ({'numWorkSets': 2, 'satisfiesCoverage': []}, {}, {},
            {'libraryDefinitionId': 'rdl'}),
        'nordic': ({'numWorkSets': 2, 'satisfiesCoverage': []}, {}, {},
            {'libraryDefinitionId': 'nordic'}),
    }
    definitions = {
        'rdl': {'muscleGroups': ['BACK_HAMSTRING'], 'secondaryMuscleGroups': [],
            'reviewedExecution': {'supportingMuscles': ['hamstrings', 'lowerBack'],
                'source': 'https://example.test/reviewed-support', 'basis': 'Controlled execution-support fixture.'}},
        'nordic': {'muscleGroups': ['BACK_HAMSTRING'], 'secondaryMuscleGroups': []},
    }

    evidence = session_interference_evidence({'components': [
        {'type': 'Superset', 'exercises': members}]}, sources, definitions, {}, {}, {})

    group = evidence['wholeSessionSupersetEvidence']['groups'][0]
    assert group['scheduledRounds'] == 2
    assert group['memberExposure'][0]['firstRoundPriorExposure']['primaryWorkingSets']['hamstrings'] == 0
    assert group['memberExposure'][1]['firstRoundPriorExposure']['primaryWorkingSets']['hamstrings'] == 1
    assert group['memberExposure'][0]['finalRoundPriorExposure']['primaryWorkingSets']['hamstrings'] == 2
    assert group['memberExposure'][1]['finalRoundPriorExposure']['primaryWorkingSets']['hamstrings'] == 3
    assert group['memberExposure'][0]['supportingMuscles'] == ['lowerBack']
    assert group['memberExposure'][0]['executionSupportEvidence']['source'] == 'https://example.test/reviewed-support'
    assert group['memberExposure'][1]['executionSupportEvidence'] == {'status': 'unknown'}
    assert group['memberExposure'][0]['finalRoundPriorExposure'][
        'priorSupportingWorkingSetsOnSupportingMuscles'] == {'lowerBack': 1}
    assert evidence['wholeSessionExposure']['totalMemberWorkingSets'] == 4
    assert evidence['wholeSessionExposure']['supersetMemberWorkingSets'] == 4
    assert evidence['wholeSessionExposure']['supersetPrimaryWorkingSetsByMuscle']['hamstrings'] == 4


def test_setup_task_count_distinguishes_same_barbell_exercise_loads():
    source_rows = {
        'same': {'numWorkSets': 3, 'targetSetPrescriptions': [
            {'workSetIndex': index, 'weight': 40, 'reps': 8} for index in range(3)], 'requiresLoadCalibration': False},
        'changed': {'numWorkSets': 3, 'targetSetPrescriptions': [
            {'workSetIndex': index, 'weight': 45, 'reps': 8} for index in range(3)], 'requiresLoadCalibration': False},
    }
    sources = {identifier: (source_rows[row], {}, {}, {'libraryDefinitionId': 'row'})
        for identifier, row in [('row1', 'same'), ('row2', 'changed'), ('row3', 'same')]}
    evidence = session_setup_evidence({'components': [
        {'type': 'Exercise', 'id': 'row1'}, {'type': 'Exercise', 'id': 'row2'},
        {'type': 'Exercise', 'id': 'row3'},]}, sources,
        {'row': {'id': 'row', 'equipmentId': 'bar', 'exerciseType': 'WEIGHT'}})

    assert evidence['distinctEquipmentIds'] == ['bar']
    assert evidence['preparationTaskCount'] == 2
    assert evidence['preparationTasks'][0]['configurationStatus'] == 'known'
    assert [item['configurationRelation'] for item in evidence['transitions']
        if item['scope'] == 'between_blocks'] == [
        'known_changed', 'known_changed']


def test_executable_and_emitted_setup_evaluate_the_same_round_specific_load_edges():
    definitions = {name: {'id': name, 'equipmentId': 'bar', 'exerciseType': 'WEIGHT'}
        for name in ('row', 'press', 'curl')}
    exercises = [{'id': name, 'definition_id': name, 'numWorkSets': len(loads),
        'superset': group, 'targetSetPrescriptions': [{'weight': load} for load in loads]}
        for name, group, loads in [('row', 'PAIR', [40, 50]),
            ('press', 'PAIR', [40, 50]), ('curl', None, [50, 55, 55])]]
    sources = {item['id']: (item, {}, {}, {'libraryDefinitionId': item['definition_id']})
        for item in exercises}
    artifact = {'components': [{'type': 'Superset', 'exercises': [{'id': 'row'}, {'id': 'press'}]},
        {'type': 'Exercise', 'id': 'curl'}]}

    evidence = executable_setup_evidence({'exercises': exercises}, definitions)

    assert evidence == session_setup_evidence(artifact, sources, definitions)
    assert evidence['preparationTaskCount'] == 3
    assert evidence['scheduledTransitionOccurrenceCount'] == 6
    assert [item['configurationRelation'] for item in evidence['transitions']] == [
        'known_same', 'known_changed', 'known_same', 'known_same', 'known_changed', 'known_same']
    assert evidence['knownDeclaredChanges'] == 2
    assert evidence['unknownTransitions'] == 0


def test_missing_load_is_unknown_while_declared_equipment_switch_remains_known():
    definitions = {'row': {'id': 'row', 'equipmentId': 'bar', 'exerciseType': 'WEIGHT'},
        'press': {'id': 'press', 'equipmentId': 'dumbbells', 'exerciseType': 'WEIGHT'}}
    exercises = [{'definition_id': name, 'numWorkSets': 1,
        'workSetTemplate': {'weight': None}} for name in definitions]

    evidence = executable_setup_evidence({'exercises': exercises}, definitions)

    assert evidence['knownDeclaredChanges'] == 1
    assert evidence['unknownTransitions'] == 0
    assert evidence['unknownConfigurationTransitions'] == 1
    assert all(item['configurationStatus'] == 'unknown' for item in evidence['preparationTasks'])
    exercises[1]['definition_id'] = 'row'
    evidence = executable_setup_evidence({'exercises': exercises}, definitions)
    assert evidence['knownDeclaredChanges'] == 0
    assert evidence['unknownTransitions'] == 1


def test_incomplete_per_set_loads_are_unknown_but_a_template_repeats():
    definition = {'id': 'row', 'equipmentId': 'bar', 'exerciseType': 'WEIGHT'}
    partial = setup_resource_profile(definition, {'numWorkSets': 3,
        'targetSetPrescriptions': [{'weight': 40}]})
    template = executable_setup_evidence({'exercises': [{'definition_id': 'row',
        'numWorkSets': 3, 'workSetTemplate': {'weight': 40}}]}, {'row': definition})

    assert partial['configurationStatus'] == 'unknown'
    assert template['scheduledTransitionOccurrencesByConfigurationRelation'] == {'known_same': 2}


def test_joint_objective_and_candidate_comparator_count_same_bar_different_exercises_as_two_tasks():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['setup_economy']
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'name': 'Adjustable barbell', 'type': 'BARBELL',
        'barWeight': 20, 'sleeveLength': 100,
        'availablePlates': [{'weight': 20, 'thickness': 10}] * 2}]
    for index, definition in enumerate(equipment['exerciseDefinitions']):
        definition.update(exerciseType='WEIGHT', equipmentId='EQUIPMENT_0', bodyWeightPercentage=None)
        sessions[0]['exercises'][index].update(workSetTemplate={
            'reps': 9, 'weight': 20 if index == 0 else 60})

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result.get('rejectedOptions')
    stages = {stage['goal']: stage for stage in result['objectiveProgress']}
    assert stages['setup_economy']['value'] == 2
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda item: item['id']))}
    costs = joint_planning._joint_candidate_objective_costs(
        {'workouts': result['sessions'], 'audit': result['audit']}, requirements,
        {'setupDefinitions': definitions})
    assert costs['setup_economy'] == stages['setup_economy']['value'] == 2
