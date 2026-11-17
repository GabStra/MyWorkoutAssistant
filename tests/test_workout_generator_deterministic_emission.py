import pytest

from workout_generator_pkg import cli
from workout_generator_pkg.domain_ops import build_workout_structure, finalize_and_validate_exercise_definition
from workout_generator_pkg.plan_contract import validate_workout_structures_contract
from workout_generator_pkg.stage_prompts import PLAN_INDEX_EXAMPLE


def test_structure_keeps_round_recovery_and_outer_transition_without_model_calls(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Structure construction must not call a model")

    monkeypatch.setattr(cli, "json_call_chat_max_with_loading", forbidden)
    monkeypatch.setattr(cli, "json_call_reasoner_only_with_loading", forbidden)
    workout = {
        "id": "WORKOUT_0", "name": "Day C", "description": "Full body. Schedule: Monday.",
        "exerciseIds": ["EXERCISE_0", "EXERCISE_1", "EXERCISE_2", "EXERCISE_3"],
        "restToNextSeconds": [90, 0, 75, 0],
        "supersetGroups": [{
            "exerciseIds": ["EXERCISE_1", "EXERCISE_2"],
            "restSecondsByExercise": {"EXERCISE_1": 40, "EXERCISE_2": 75},
            "roundDurationSeconds": 120,
        }],
    }
    plan = {"workouts": [workout]}
    definitions = {reference: {"id": reference} for reference in workout["exerciseIds"]}
    structure, conversation = cli.emit_workout_structure("WORKOUT_0", None, "", plan, definitions)
    assert conversation is None
    assert structure['workoutMetadata']['description'] == workout['description']
    assert [component["componentType"] for component in structure["workoutComponents"]] == ["Exercise", "Rest", "Superset", "Rest", "Exercise"]
    assert structure["workoutComponents"][3]["timeInSeconds"] == 75
    assert structure["workoutComponents"][2]["roundDurationSeconds"] == 120
    validate_workout_structures_contract(plan, {"WORKOUT_0": structure}, definitions)


def test_member_cadence_reaches_the_emitted_superset():
    """Rotating EMOM (one member per slot) must survive structure emission and
    pass the structure contract, which now compares cadenceMode."""
    workout = {
        "id": "WORKOUT_0", "name": "EMOM 9", "description": "Rotating EMOM. Schedule: Monday.",
        "exerciseIds": ["EXERCISE_0", "EXERCISE_1", "EXERCISE_2"],
        "restToNextSeconds": [0, 0, 60],
        "supersetGroups": [{
            "exerciseIds": ["EXERCISE_0", "EXERCISE_1", "EXERCISE_2"],
            "restSecondsByExercise": {"EXERCISE_0": 0, "EXERCISE_1": 0, "EXERCISE_2": 0},
            "roundDurationSeconds": 60,
            "cadenceMode": "MEMBER",
        }],
    }
    plan = {"workouts": [workout]}
    definitions = {reference: {"id": reference} for reference in workout["exerciseIds"]}

    structure, _ = cli.emit_workout_structure("WORKOUT_0", None, "", plan, definitions)

    superset = structure["workoutComponents"][0]
    assert superset["componentType"] == "Superset"
    assert superset["cadenceMode"] == "MEMBER"
    assert superset["roundDurationSeconds"] == 60
    validate_workout_structures_contract(plan, {"WORKOUT_0": structure}, definitions)


def test_member_cadence_requires_a_slot_length():
    from workout_generator_pkg.plan_contract import _normalize_superset_groups

    group = {"exerciseIds": ["EXERCISE_0", "EXERCISE_1"],
             "restSecondsByExercise": {"EXERCISE_0": 0, "EXERCISE_1": 0},
             "cadenceMode": "MEMBER"}
    _, issues = _normalize_superset_groups([group], "Day", {"EXERCISE_0", "EXERCISE_1"})
    assert [issue.code for issue in issues] == ["superset_mode_requires_cadence"]


def test_superset_modes_merge_keys_and_reject_conflicts():
    from workout_generator_pkg.planning_tools import _merge_superset_modes

    def group_dict():
        return {"exerciseIds": ["EXERCISE_0", "EXERCISE_1"], "restSecondsByExercise": {}}

    groups = {"A": group_dict()}
    errors = []
    _merge_superset_modes(
        {"supersetModes": [{"superset": "A", "cadenceMode": "MEMBER", "roundDurationSeconds": 120}]},
        groups, 0, errors,
    )
    assert errors == []
    assert groups["A"]["cadenceMode"] == "MEMBER"
    assert groups["A"]["roundDurationSeconds"] == 120

    groups = {"A": group_dict()}
    errors = []
    _merge_superset_modes(
        {"supersetModes": [
            {"superset": "missing", "cadenceMode": "MEMBER", "roundDurationSeconds": 60},
            {"superset": "A", "cadenceMode": "MEMBER"},
        ]},
        groups, 0, errors,
    )
    assert [error["code"] for error in errors] == [
        "unknown_superset_mode_group",
        "superset_mode_requires_cadence",
    ]

    groups = {"A": group_dict()}
    errors = []
    _merge_superset_modes(
        {"supersetModes": [{"superset": "A", "roundDurationSeconds": 60, "timeCapSeconds": 600}]},
        groups, 0, errors,
    )
    assert [error["code"] for error in errors] == ["superset_mode_conflict"]


def test_legacy_round_rest_does_not_create_an_extra_outer_rest():
    structure = build_workout_structure({
        "id": "WORKOUT_0", "name": "Day", "exerciseIds": ["EXERCISE_0", "EXERCISE_1"],
        "restToNextSeconds": [40, 75], "supersetGroups": [{"exerciseIds": ["EXERCISE_0", "EXERCISE_1"]}],
    })
    assert len(structure["workoutComponents"]) == 1
    assert structure["workoutComponents"][0]["restSecondsByExercise"] == {"EXERCISE_0": 40, "EXERCISE_1": 75}


@pytest.mark.parametrize("guess,expected", [(2.5, 5.0), (22.5, 45.0)])
def test_guessed_pair_load_and_library_muscles_are_normalized_before_validation(guess, expected):
    exercise = {
        "id": "EXERCISE_0", "type": "Exercise", "enabled": True, "name": "Dumbbell Raise",
        "notes": "Preserve controlled motion and the prescribed setup.",
        "placementNotes": "Stop if the prescribed technique cannot be maintained.",
        "exerciseType": "WEIGHT", "equipmentId": "EQUIPMENT_0", "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [], "muscleGroups": ["FRONT_DELTOIDS"], "secondaryMuscleGroups": [],
        "generateWarmUpSets": False, "progressionMode": "OFF", "keepScreenOn": False,
        "showCountDownTimer": False, "requiresLoadCalibration": False, "minReps": 8, "maxReps": 10,
        "sets": [{"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": guess, "subCategory": "WorkSet"}],
    }
    plan = {"id": "EXERCISE_0", "muscleGroups": ["BACK_DELTOIDS"], "secondaryMuscleGroups": ["BACK_UPPER_BACK"]}
    equipment = [{"id": "EQUIPMENT_0", "name": "Dumbbell Pair", "type": "DUMBBELLS", "dumbbells": [{"weight": 2.5}, {"weight": 22.5}]}]
    normalized = finalize_and_validate_exercise_definition(exercise, plan, equipment_subset=equipment)
    assert normalized["sets"][0]["weight"] == expected
    assert normalized["muscleGroups"] == plan["muscleGroups"]
    assert normalized["secondaryMuscleGroups"] == plan["secondaryMuscleGroups"]
    assert normalized["requiresLoadCalibration"] is True
    assert normalized['notes'] == exercise['notes']
    assert normalized['placementNotes'] == exercise['placementNotes']
    plan["targetSetPrescriptions"] = [{"workSetIndex": 0, "reps": 8, "weight": guess}]
    with pytest.raises(ValueError, match="invalid weights"):
        finalize_and_validate_exercise_definition(exercise, plan, equipment_subset=equipment)

    plan.update(requiresLoadCalibration=True,
        targetSetPrescriptions=[{"workSetIndex": 0, "reps": 8, "weight": expected}])
    valid_exercise = {**exercise, "sets": [{**exercise["sets"][0], "weight": expected}]}
    normalized = finalize_and_validate_exercise_definition(valid_exercise, plan, equipment_subset=equipment)
    assert normalized["requiresLoadCalibration"] is True


def test_planner_example_contains_only_referenced_numeric_exercises():
    references = {reference for workout in PLAN_INDEX_EXAMPLE["workouts"] for reference in workout["exerciseIds"]}
    assert {exercise["id"] for exercise in PLAN_INDEX_EXAMPLE["exercises"]} == references
    assert "EXERCISE_WARMUP" not in references


def _warmup_library():
    return {'id': 'warmup-bike', 'name': 'Timed ride', 'exerciseType': 'COUNTDOWN',
        'equipmentId': '11111111-1111-4111-8111-111111111111', 'bodyWeightPercentage': None, 'requiredAccessoryEquipmentIds': [],
        'muscleGroups': ['FRONT_QUADRICEPS'], 'secondaryMuscleGroups': ['BACK_GLUTEAL'], 'exerciseCategory': None}


@pytest.mark.parametrize('seconds', [None, 0, 300, 600])
def test_code_owned_general_warmup_preserves_review_export_and_audit(seconds):
    import copy
    from jsonschema import Draft7Validator
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.constants import JSON_SCHEMA
    from workout_generator_pkg.domain_ops import (
        _materialize_exercise_definition, assemble_placeholder_workout_store,
        apply_exercise_library_schema_v2, convert_placeholders_to_uuids,
        general_warmup_audit_options, general_warmup_exercises, reviewable_workout_artifact,
    )
    from workout_generator_pkg.generation_audit import (
        audit_workout_package, plan_audit_package,
    )
    from workout_generator_pkg.plan_contract import validate_assembled_workout_contract
    from workout_generator_pkg.planning_tools import build_draft_plan

    equipment, requirements, _, draft = planning_case()
    warmup_definition = _warmup_library()
    equipment['equipments'] = [{'id': warmup_definition['equipmentId'], 'name': 'Bike', 'type': 'CARDIO_MACHINE'}]
    equipment['exerciseDefinitions'].append(warmup_definition)
    draft['workouts'] *= 3
    requirements['auditTargets'] = {}
    if seconds is not None:
        requirements['generalWarmupSeconds'] = seconds
    if seconds:
        requirements['generalWarmupDefinitionId'] = warmup_definition['id']
    plan = build_draft_plan(draft, equipment, requirements)
    definitions = {entry['id']: _materialize_exercise_definition(entry) for entry in plan['exercises']}
    structures = {day['id']: build_workout_structure(day) for day in plan['workouts']}
    actual = assemble_placeholder_workout_store({item['id']: item for item in equipment['equipments']}, {}, definitions, structures, plan)
    validate_assembled_workout_contract(plan, actual)
    warmups = general_warmup_exercises(plan)
    if seconds:
        assert len({component['id'] for component in warmups.values()}) == 3
        assert len({component['sets'][0]['id'] for component in warmups.values()}) == 3
    for day in actual['workouts']:
        first = day['workoutComponents'][0]
        if seconds:
            assert first['exerciseType'] == 'COUNTDOWN'
            assert len(first['sets']) == 1 and first['sets'][0]['timeInMillis'] == seconds * 1000
            assert day['workoutComponents'][1]['type'] == 'Exercise'
        else:
            assert first['exerciseType'] == 'BODY_WEIGHT'
    reviewed = reviewable_workout_artifact(plan, 'Guidance')
    manager = cli.PlaceholderIdManager()
    exported = convert_placeholders_to_uuids(actual, manager, validate_final=False)
    exported = apply_exercise_library_schema_v2(exported, equipment['exerciseDefinitions'])
    assert reviewable_workout_artifact(plan, 'Guidance', exported, manager.placeholder_to_uuid) == reviewed
    legacy = copy.deepcopy(exported)
    for key in ('schemaVersion', 'exerciseDefinitions', 'exerciseMovements'):
        legacy.pop(key)
    for day in legacy['workouts']:
        for exercise in day['workoutComponents']:
            exercise.pop('exerciseDefinitionId')
    Draft7Validator(JSON_SCHEMA).validate(legacy)
    if seconds:
        assert {day['workoutComponents'][0]['exerciseDefinitionId'] for day in exported['workouts']} == {warmup_definition['id']}
        report_placeholder = actual['workouts'][0]['workoutComponents'][0]
        assert report_placeholder['name'] == warmup_definition['name']
        assert report_placeholder['nameOverride'] == 'Warm-up'
        assert report_placeholder['equipmentId'] == warmup_definition['equipmentId']
        report_export = exported['workouts'][0]['workoutComponents'][0]
        assert report_export['name'] == warmup_definition['name']
        assert report_export['nameOverride'] == 'Warm-up'
    mapping = manager.placeholder_to_uuid
    report = audit_workout_package(exported, {},
        general_warmup_by_workout=general_warmup_audit_options(plan, mapping))
    planned = audit_workout_package(plan_audit_package(plan), {})
    assert not report['errors']
    assert report['weeklyWorkingSets'] == planned['weeklyWorkingSets'] == 15
    assert report['weeklyVolume'] == planned['weeklyVolume']



@pytest.mark.parametrize('change', ['duration', 'rest'])
def test_explicit_general_warmup_rejects_timer_or_following_rest_changes(change):
    from test_workout_generator_programming_audit import _plan
    from workout_generator_pkg.generation_audit import audit_workout_package, plan_audit_package
    from workout_generator_pkg.plan_contract import validate_assembled_workout_contract, ContractValidationError

    plan = _plan()
    plan['workouts'][0]['generalWarmupSeconds'] = 300
    plan['workouts'][0]['generalWarmupDefinition'] = _warmup_library()
    package = plan_audit_package(plan)
    if change == 'duration':
        package['workouts'][0]['workoutComponents'][0]['sets'][0]['timeInMillis'] = 299000
    else:
        package['workouts'][0]['workoutComponents'].insert(1, {'type': 'Rest', 'timeInSeconds': 60})
    report = audit_workout_package(package, {})
    assert any(error['code'] == 'general_warmup_mismatch' for error in report['errors'])
    with pytest.raises(ContractValidationError, match='General warm-up'):
        validate_assembled_workout_contract(plan, package)


@pytest.mark.parametrize('failure', ['missing', 'unknown', 'type', 'equipment', 'accessory'])
def test_explicit_general_warmup_requires_available_library_binding(failure):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import build_draft_plan, PlanningInputError, workout_requirements_tool

    equipment, requirements, _, draft = planning_case()
    definition = _warmup_library()
    equipment['equipments'] = [{'id': definition['equipmentId'], 'name': 'Bike', 'type': 'CARDIO_MACHINE'}]
    equipment['exerciseDefinitions'].append(definition)
    selection = workout_requirements_tool(equipment)['function']['parameters']['properties']['generalWarmupDefinitionId']
    assert selection['oneOf'] == [{'const': definition['id'], 'title': definition['name']}]
    requirements.update(generalWarmupSeconds=300, generalWarmupDefinitionId=definition['id'])
    if failure == 'missing':
        requirements.pop('generalWarmupDefinitionId')
    elif failure == 'unknown':
        requirements['generalWarmupDefinitionId'] = 'absent'
    elif failure == 'type':
        definition['exerciseType'] = 'COUNTUP'
    elif failure == 'equipment':
        equipment['equipments'] = []
    else:
        definition['requiredAccessoryEquipmentIds'] = ['missing-accessory']
    with pytest.raises(PlanningInputError) as error:
        build_draft_plan(draft, equipment, requirements)
    assert error.value.code == 'general_warmup_definition_required'
