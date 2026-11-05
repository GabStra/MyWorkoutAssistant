import copy
import pytest

from workout_generator_pkg.programming_guidelines import audit_execution_rules


def test_confirmed_setup_scope_binds_only_declared_station_configurations_with_source_provenance():
    from workout_generator_pkg.programming_guidelines import (
        bind_confirmed_superset_access, superset_setup_compatibility)

    definitions = [
        {'id': 'INDEPENDENT', 'equipmentId': 'DUMBBELLS'},
        {'id': 'STATION', 'equipmentId': 'BAR', 'requiredAccessoryEquipmentIds': ['BENCH']},
        {'id': 'PULL', 'equipmentId': 'PULLUP'},
        {'id': 'OTHER', 'equipmentId': 'VEST'},
        {'id': 'EXTRA', 'equipmentId': 'BAR', 'requiredAccessoryEquipmentIds': ['UNCONFIRMED']},
        {'id': 'UNASSIGNED', 'equipmentId': None},
    ]
    inventory = {'exerciseDefinitions': definitions,
        'equipments': [{'id': identifier} for identifier in ('DUMBBELLS', 'BAR', 'VEST')],
        'accessoryEquipments': [{'id': identifier} for identifier in ('BENCH', 'PULLUP', 'UNCONFIRMED')]}
    requirements = {'executionRules': [{'kind': 'supersetNoReconfiguration', 'coverageKey': None,
        'sharedResourceGroups': [['BAR', 'BENCH', 'PULLUP']], 'confirmedIndependentPairs': []}]}
    confirmation = {'independentDefinitionIds': ['INDEPENDENT'],
        'retainedResourceIds': ['BAR', 'BENCH', 'PULLUP'], 'sourceReferences': ['SOURCE_0']}
    sources = {'SOURCE_0': {'role': 'user', 'content': 'Confirmed independent space alongside this station.'}}
    result = bind_confirmed_superset_access(requirements, inventory, [confirmation], sources)
    assert requirements['executionRules'][0]['confirmedIndependentPairs'] == []
    assert result['requirements']['executionRules'][0]['confirmedIndependentPairs'] == [
        ['INDEPENDENT', 'PULL'], ['INDEPENDENT', 'STATION']]
    assert result['bindings'][0] == {'pair': ['INDEPENDENT', 'PULL'],
        'independentDefinitionId': 'INDEPENDENT', 'retainedResourceIds': ['BAR', 'BENCH', 'PULLUP'],
        'sourceReferences': ['SOURCE_0'],
        'requirementPath': '/requirements/executionRules/0/confirmedIndependentPairs'}
    by_id = {item['id']: item for item in definitions}
    check = lambda first, second: superset_setup_compatibility(
        by_id[first], by_id[second], result['requirements'])['status']
    assert check('INDEPENDENT', 'STATION') == 'compatible'
    assert check('STATION', 'PULL') == 'incompatible'
    assert all(check('INDEPENDENT', other) == 'unknown' for other in ('OTHER', 'EXTRA', 'UNASSIGNED'))
    assert bind_confirmed_superset_access(result['requirements'], inventory, [confirmation], sources) == result
    with pytest.raises(ValueError, match='user sources'):
        bind_confirmed_superset_access(requirements, inventory, [confirmation], {})
    with pytest.raises(ValueError, match='retained station'):
        bind_confirmed_superset_access(requirements, inventory,
            [{**confirmation, 'independentDefinitionIds': ['STATION']}], sources)


def audit_pair(first, second, first_gear, second_gear, rules=None):
    first = {'equipmentId': 'GEAR_A', 'exerciseType': 'WEIGHT', 'requiresLoadCalibration': False,
        'targetSetPrescriptions': [{'workSetIndex': 0, 'weight': 20}], **first}
    second = {'equipmentId': 'GEAR_B', 'exerciseType': 'WEIGHT', 'requiresLoadCalibration': False,
        'targetSetPrescriptions': [{'workSetIndex': 0, 'weight': 30}], **second}
    draft = {'workouts': [{'name': 'Day A', 'exercises': [
        {'superset': 'PAIR', 'satisfiesCoverage': [], 'numWorkSets': 2},
        {'superset': 'PAIR', 'satisfiesCoverage': [], 'numWorkSets': 2},
    ]}]}
    plan = {'exercises': [dict(first, id='LIBRARY_0'), dict(second, id='LIBRARY_1')],
        'workouts': [{'exerciseIds': ['LIBRARY_0', 'LIBRARY_1']}],
        'equipments': [dict(first_gear, id='GEAR_A'), dict(second_gear, id='GEAR_B')]}
    report = {'issues': [], 'errors': []}
    audit_execution_rules(draft, {'executionRules': rules if rules is not None else [
        {'kind': 'supersetNoReconfiguration', 'coverageKey': None}]}, report, plan)
    return report


@pytest.mark.parametrize('confirmed,shared,status,rejection', [
    (False, False, 'unknown', 'simultaneous_access_unconfirmed'),
    (True, False, 'compatible', None),
    (True, True, 'incompatible', 'shared_physical_station')])
def test_confirmed_access_uses_same_persistent_identity_and_admission_in_solver_and_audit(
        confirmed, shared, status, rejection):
    from workout_generator_pkg.joint_planning import _superset_pair_rejection
    from workout_generator_pkg.programming_guidelines import superset_setup_compatibility

    first = {'id': 'DEF_A', 'equipmentId': 'GEAR_A', 'exerciseType': 'WEIGHT',
        'exerciseCategory': 'MODERATE_COMPOUND', 'muscleGroups': ['FRONT_CHEST'],
        'secondaryMuscleGroups': [], 'requiredAccessoryEquipmentIds': []}
    second = {**first, 'id': 'DEF_B', 'equipmentId': 'GEAR_B', 'muscleGroups': ['FRONT_BICEPS']}
    rule = {'kind': 'supersetNoReconfiguration', 'coverageKey': None,
        'confirmedIndependentPairs': [['DEF_B', 'DEF_A']] if confirmed else []}
    if shared:
        rule['sharedResourceGroups'] = [['GEAR_A', 'GEAR_B']]
    requirements = {'executionRules': [rule]}
    equipment = {'equipments': [{'id': 'GEAR_A', 'type': 'BARBELL'},
                                {'id': 'GEAR_B', 'type': 'DUMBBELL'}]}
    assert superset_setup_compatibility(first, second, requirements)['status'] == status
    assert _superset_pair_rejection({'definition_id': 'LIBRARY_0'}, {'definition_id': 'LIBRARY_1'},
        {'LIBRARY_0': first, 'LIBRARY_1': second}, requirements, equipment) == rejection
    report = audit_pair({**first, 'libraryDefinitionId': 'DEF_A'},
        {**second, 'libraryDefinitionId': 'DEF_B'}, *equipment['equipments'], rules=[rule])
    assert report['supersetEquipmentResources'][0]['setupCompatibility']['status'] == status
    assert bool(report['errors']) == (rejection is not None)


def test_dumbbell_alias_records_do_not_prove_independent_physical_inventory():
    dumbbell_pair = {'type': 'DUMBBELLS', 'dumbbells': [{'weight': 10}, {'weight': 15}],
        'extraWeights': [{'weight': 1}], 'maxExtraWeightsPerLoadingPoint': 1}
    single_dumbbell = {'type': 'DUMBBELL', 'dumbbells': [{'weight': 10}, {'weight': 15}],
        'extraWeights': [{'weight': 1}], 'maxExtraWeightsPerLoadingPoint': 1}

    report = audit_pair(
        {'requiresLoadCalibration': True, 'targetSetPrescriptions': []},
        {'requiresLoadCalibration': True, 'targetSetPrescriptions': []},
        dumbbell_pair, single_dumbbell)

    assert [error['code'] for error in report['errors']] == ['execution_supersetNoReconfiguration']
    assert report['supersetEquipmentResources'][0]['relation'] == 'potentially_shared_family'
    assert report['errors'][0]['equipmentResourceRelation'] == 'potentially_shared_family'


def test_confirmed_access_rule_validates_library_identity_before_approval():
    from jsonschema import ValidationError, validate
    from workout_generator_pkg.planning_tools import _execution_rules_schema
    from workout_generator_pkg.programming_guidelines import execution_rule_errors

    equipment = {'exerciseDefinitions': [{'id': 'DEF_A'}, {'id': 'DEF_B'}]}
    rule = {'kind': 'supersetNoReconfiguration', 'coverageKey': None,
            'confirmedIndependentPairs': [['DEF_A', 'DEF_B']]}
    schema = _execution_rules_schema([], equipment)
    validate([rule], schema)
    assert execution_rule_errors({'executionRules': [rule]}, equipment) == []
    rule['confirmedIndependentPairs'][0][1] = 'UNAVAILABLE'
    with pytest.raises(ValidationError):
        validate([rule], schema)
    assert execution_rule_errors({'executionRules': [rule]}, equipment)[0]['code'] == 'invalid_execution_rule'


def test_same_type_adjustable_equipment_with_different_loads_requires_separation():
    dumbbells = {'type': 'DUMBBELLS', 'dumbbells': [{'weight': 10}, {'weight': 15}],
        'extraWeights': [{'weight': 1}], 'maxExtraWeightsPerLoadingPoint': 1}
    report = audit_pair({}, {}, dumbbells, dumbbells)

    assert [error['code'] for error in report['errors']] == ['execution_supersetNoReconfiguration']
    assert report['errors'][0]['equipmentResourceRelation'] == 'potentially_shared_family'


def test_different_structured_equipment_types_do_not_trigger_alias_load_check():
    report = audit_pair({}, {}, {'type': 'BARBELL'}, {'type': 'WEIGHTVEST'})

    assert report['errors'] == []
    assert report['supersetEquipmentResources'][0]['relation'] == 'different_family_types'


def test_approved_shared_station_group_blocks_superset_in_audit_and_solver_but_not_vest_work():
    from workout_generator_pkg.joint_planning import _superset_pair_rejection
    from workout_generator_pkg.planning_tools import _execution_rules_schema

    barbell, pullup, bench, rack, vest, nordic = (
        'a247d19d-e625-4c84-af6a-f643bb1d076c',
        '49405aae-8e6d-4364-8bd5-cb551fb97631',
        'e3f0e0ee-3433-4435-bed9-c926e23a8468',
        '31159650-e64d-47ba-95b3-a63ce301dbac',
        'e95fb928-2fc9-49b3-8dc9-2c60f5f48cd0',
        'NORDIC_CURL_SETUP',
    )
    group = [barbell, pullup, bench, rack]
    rule = {'kind': 'supersetNoReconfiguration', 'coverageKey': None,
            'sharedResourceGroups': [[barbell, pullup]]}
    overlapping_rule = {'kind': 'supersetNoReconfiguration', 'coverageKey': None,
            'sharedResourceGroups': [[pullup, bench, rack]]}
    requirements = {'executionRules': [rule, overlapping_rule]}
    inventory = {
        'equipments': [
            {'id': barbell, 'type': 'BARBELL', 'name': 'Barbell'},
            {'id': vest, 'type': 'WEIGHTVEST', 'name': 'Weighted Vest'},
        ],
        'accessoryEquipments': [
            {'id': pullup, 'name': 'Pull-Up Station'},
            {'id': bench, 'name': 'Adjustable Bench'},
            {'id': rack, 'name': 'Squat Rack'},
            {'id': nordic, 'name': 'Nordic Curl Setup'},
        ],
    }
    definitions = {
        'barbell_press': {'id': 'barbell_press', 'exerciseCategory': 'MODERATE_COMPOUND',
            'exerciseType': 'WEIGHT', 'equipmentId': barbell,
            'requiredAccessoryEquipmentIds': [bench], 'muscleGroups': ['FRONT_CHEST'],
            'secondaryMuscleGroups': []},
        'pullup': {'id': 'pullup', 'exerciseCategory': 'MODERATE_COMPOUND',
            'exerciseType': 'BODY_WEIGHT', 'equipmentId': pullup,
            'requiredAccessoryEquipmentIds': [], 'muscleGroups': ['BACK_UPPER_BACK'],
            'secondaryMuscleGroups': []},
        'nordic': {'id': 'nordic', 'exerciseCategory': 'MODERATE_COMPOUND',
            'exerciseType': 'BODY_WEIGHT', 'equipmentId': vest,
            'requiredAccessoryEquipmentIds': [nordic], 'muscleGroups': ['BACK_HAMSTRING'],
            'secondaryMuscleGroups': []},
    }
    schema = _execution_rules_schema([], inventory)
    resource_groups = next(branch['properties']['sharedResourceGroups']
        for branch in schema['items']['oneOf']
        if branch['properties']['kind'].get('const') == 'supersetNoReconfiguration')
    assert set(resource_groups['items']['items']['enum']) == {barbell, pullup, bench, rack, vest, nordic}

    def solver_rejection(second_id):
        return _superset_pair_rejection(
            {'definition_id': 'barbell_press', 'satisfiesCoverage': []},
            {'definition_id': second_id, 'satisfiesCoverage': []},
            definitions, requirements, inventory)

    assert solver_rejection('pullup') == 'shared_physical_station'
    assert solver_rejection('nordic') is None

    def audit_pair_ids(second_id):
        plan = {'exercises': [definitions['barbell_press'], definitions[second_id]],
            'workouts': [{'exerciseIds': ['barbell_press', second_id]}],
            'equipments': inventory['equipments'] + inventory['accessoryEquipments']}
        draft = {'workouts': [{'name': 'Day', 'exercises': [
            {'superset': 'PAIR', 'satisfiesCoverage': [], 'numWorkSets': 2},
            {'superset': 'PAIR', 'satisfiesCoverage': [], 'numWorkSets': 2},
        ]}]}
        report = {'issues': [], 'errors': []}
        audit_execution_rules(draft, requirements, report, plan)
        return report

    assert [item['code'] for item in audit_pair_ids('pullup')['errors']] == [
        'execution_supersetNoReconfiguration']
    assert audit_pair_ids('nordic')['errors'] == []


def test_unweighted_bodyweight_member_without_primary_equipment_remains_pairable():
    report = audit_pair({}, {'equipmentId': None, 'exerciseType': 'BODY_WEIGHT', 'requiresLoadCalibration': False},
        {'type': 'BARBELL'}, {})

    assert report['errors'] == []
    assert report['supersetEquipmentResources'][0]['relation'] == 'no_primary_equipment'


def test_joint_solver_splits_unverified_dumbbell_alias_pair_before_timing_optimization():
    from test_workout_generator_programming_guidelines import case
    from workout_generator_pkg.joint_planning import solve_prescribed_week

    equipment, requirements, _, draft = case([
        {'kind': 'supersetNoReconfiguration', 'coverageKey': None}])
    equipment['equipments'] = [
        {'id': f'EQUIPMENT_{index}', 'type': kind, 'name': kind,
         'dumbbells': [{'weight': 10}, {'weight': 15}], 'extraWeights': [],
         'maxExtraWeightsPerLoadingPoint': 0}
        for index, kind in enumerate(('DUMBBELLS', 'DUMBBELL'))]
    original = equipment['exerciseDefinitions'][0]
    original.update(exerciseType='WEIGHT', bodyWeightPercentage=None, equipmentId='EQUIPMENT_0')
    other = copy.deepcopy(original)
    other.update(id='second', name='Second movement', equipmentId='EQUIPMENT_1')
    equipment['exerciseDefinitions'].append(other)
    requirements['objectiveOrder'] = ['duration_economy']
    for index, exercise in enumerate(draft['workouts'][0]['exercises']):
        exercise.pop('placementNotes', None)
        exercise.update(definition_id=f'LIBRARY_{index}', superset='PAIR',
            restBetweenSetsSeconds=0, restAfterExerciseSeconds=0,
            restAfterSupersetExerciseSeconds=15 if index == 0 else 90)
    result = solve_prescribed_week(draft['workouts'], requirements, equipment)

    assert result['feasible'], result
    assert len(result['sessions'][0]['exercises']) == 2
    assert all(exercise['superset'] is None for exercise in result['sessions'][0]['exercises'])
    assert not result['audit']['errors']
    assert any(error['code'] == 'execution_supersetNoReconfiguration'
               and error.get('equipmentResourceRelation') == 'potentially_shared_family'
               for error in result['rejectedOptions'])
