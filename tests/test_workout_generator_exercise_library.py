import json

import pytest

from workout_generator_pkg.interactive_shell import (
    _build_initial_messages,
    _load_exercise_definitions,
    _load_exercise_library_payload,
)
from workout_generator_pkg.domain_ops import apply_exercise_library_schema_v2
from workout_generator_pkg.plan_contract import (
    ContractValidationError,
    hydrate_plan_index_from_exercise_library,
    validate_plan_index_contract,
)


def test_load_exercise_definitions_accepts_store_and_backup_wrapper(tmp_path):
    definition = {"id": "definition-1", "name": "Bench", "exerciseType": "WEIGHT"}
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"WorkoutStore": {"schemaVersion": 2, "exerciseDefinitions": [definition]}}))

    assert _load_exercise_definitions(str(path)) == [definition]


def test_load_exercise_library_payload_carries_store_equipment_and_movement_assets(tmp_path):
    definition = {"id": "definition-1", "name": "Bench", "exerciseType": "WEIGHT"}
    equipment = {"id": "equipment-1", "name": "Barbell", "type": "BARBELL"}
    movement = {"movementRef": {"movementId": "bench"}, "json": "{}"}
    path = tmp_path / "library-backup.json"
    path.write_text(json.dumps({
        "WorkoutStore": {
            "schemaVersion": 2,
            "exerciseDefinitions": [definition],
            "equipments": [equipment],
            "accessoryEquipments": [],
        },
        "ExerciseMovements": [movement],
    }))

    payload = _load_exercise_library_payload(str(path))

    assert payload["exerciseDefinitions"] == [definition]
    assert payload["equipments"] == [equipment]
    assert payload["exerciseMovements"] == [movement]


def test_initial_messages_preserve_compact_library_authority_context():
    definitions = [{
        "id": "definition-1",
        "name": "Bench",
        "exerciseType": "WEIGHT",
        "equipmentId": "equipment-1",
        "unused": "not included",
    }]

    messages = _build_initial_messages("base", None, lambda _: "equipment", definitions)

    assert len(messages) == 2
    assert "strict exercise library with 1 definitions" in messages[1]["content"]
    assert "sole allowed movement source" in messages[1]["content"]
    assert "unused" not in messages[1]["content"]


def test_library_selection_hydrates_canonical_identity_and_preserves_alias():
    definition = {
        "id": "definition-1",
        "name": "Stationary Cycling",
        "exerciseType": "COUNTUP",
        "equipmentId": "EQUIPMENT_0",
        "bodyWeightPercentage": None,
        "muscleGroups": ["FRONT_QUADRICEPS"],
        "secondaryMuscleGroups": [],
        "requiredAccessoryEquipmentIds": [],
        "exerciseCategory": None,
    }
    plan = {
        "planName": "Cardio",
        "equipments": [{"id": "EQUIPMENT_0", "type": "CARDIO_MACHINE", "name": "Spin Bike"}],
        "accessoryEquipments": [],
        "exercises": [{
            "id": "EXERCISE_0",
            "libraryDefinitionId": "definition-1",
            "name": "Invented identity",
            "nameOverride": "Bike Warm-up",
            "exerciseType": "WEIGHT",
            "equipmentId": None,
            "requiredAccessoryEquipmentIds": [],
        }],
        "workouts": [],
    }

    hydrate_plan_index_from_exercise_library(plan, [definition])

    exercise = plan["exercises"][0]
    assert exercise["name"] == "Stationary Cycling"
    assert exercise["nameOverride"] == "Bike Warm-up"
    assert exercise["exerciseType"] == "COUNTUP"
    assert exercise["equipmentId"] == "EQUIPMENT_0"


def test_library_mode_rejects_exercises_without_a_selected_definition():
    provided = {
        "equipments": [],
        "accessoryEquipments": [],
        "exerciseDefinitions": [{
            "id": "definition-1",
            "name": "Push-Up",
            "exerciseType": "BODY_WEIGHT",
        }],
    }
    plan = {
        "planName": "Invalid",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [{
            "id": "EXERCISE_0",
            "name": "Invented Exercise",
            "exerciseType": "COUNTUP",
        }],
        "workouts": [],
    }

    with pytest.raises(ContractValidationError, match="invalid_library_definition_reference"):
        validate_plan_index_contract(plan, provided)


def test_library_mode_rejects_new_gear():
    provided = {
        "equipments": [],
        "accessoryEquipments": [],
        "exerciseDefinitions": [{
            "id": "definition-1",
            "name": "Push-Up",
            "exerciseType": "BODY_WEIGHT",
        }],
    }
    plan = {
        "planName": "Invalid",
        "equipments": [{"id": "EQUIPMENT_0", "type": "MACHINE", "name": "New Machine"}],
        "accessoryEquipments": [],
        "exercises": [],
        "workouts": [],
    }

    with pytest.raises(ContractValidationError, match="library_mode_created_gear"):
        validate_plan_index_contract(plan, provided)


def test_schema_v2_linking_keeps_workout_alias_on_library_definition():
    definition = {
        "id": "definition-1",
        "name": "Stationary Cycling",
        "exerciseType": "COUNTUP",
        "equipmentId": "equipment-1",
        "bodyWeightPercentage": None,
        "muscleGroups": ["FRONT_QUADRICEPS"],
        "secondaryMuscleGroups": [],
        "requiredAccessoryEquipmentIds": [],
        "exerciseCategory": None,
    }
    workout_package = {
        "workouts": [{
            "workoutComponents": [{
                "id": "exercise-1",
                "type": "Exercise",
                **definition,
                "id": "exercise-1",
                "nameOverride": "Bike Warm-up",
                "notes": "",
            }],
        }],
    }

    result = apply_exercise_library_schema_v2(workout_package, [definition], [])
    exercise = result["workouts"][0]["workoutComponents"][0]

    assert exercise["exerciseDefinitionId"] == "definition-1"
    assert exercise["name"] == "Stationary Cycling"
    assert exercise["nameOverride"] == "Bike Warm-up"
