import copy
import uuid

import pytest

from workout_generator_pkg.domain_ops import (
    apply_exercise_library_schema_v2,
    ensure_unique_ids,
)
from workout_generator_pkg.generation_pipeline import _extract_exercise_library_from_messages
from workout_generator_pkg.plan_contract import ContractValidationError, validate_plan_index_contract


def _exercise(exercise_id, set_id, *, weight, equipment_id, name="Back Squat"):
    return {
        "id": exercise_id,
        "type": "Exercise",
        "enabled": True,
        "name": name,
        "notes": "emitter-owned text",
        "sets": [{"id": set_id, "type": "WeightSet", "reps": 5, "weight": weight}],
        "exerciseType": "WEIGHT",
        "equipmentId": equipment_id,
        "bodyWeightPercentage": None,
        "muscleGroups": ["FRONT_QUADRICEPS"],
        "progressionMode": "AUTO_REGULATION",
    }


def test_periodized_occurrences_share_definition_but_keep_unique_prescription_and_set_ids():
    equipment_id = str(uuid.uuid4())
    definition_id = str(uuid.uuid4())
    duplicate_exercise_id = str(uuid.uuid4())
    duplicate_set_id = str(uuid.uuid4())
    supplied_definition = {
        "id": definition_id,
        "name": "Back Squat",
        "instructions": "Canonical bracing instructions",
        "exerciseType": "WEIGHT",
        "equipmentId": equipment_id,
        "muscleGroups": ["FRONT_QUADRICEPS", "BACK_GLUTEAL"],
    }
    package = {
        "name": "Three-phase block",
        "workouts": [
            {
                "id": str(uuid.uuid4()),
                "globalId": str(uuid.uuid4()),
                "workoutComponents": [
                    _exercise(duplicate_exercise_id, duplicate_set_id, weight=70.0, equipment_id=equipment_id)
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "globalId": str(uuid.uuid4()),
                "workoutComponents": [
                    _exercise(duplicate_exercise_id, duplicate_set_id, weight=85.0, equipment_id=equipment_id)
                ],
            },
        ],
    }

    ensure_unique_ids(package)
    result = apply_exercise_library_schema_v2(package, [supplied_definition])
    prescriptions = [workout["workoutComponents"][0] for workout in result["workouts"]]

    assert result["schemaVersion"] == 2
    assert result["exerciseDefinitions"] == [supplied_definition]
    assert len({item["id"] for item in prescriptions}) == 2
    assert len({item["sets"][0]["id"] for item in prescriptions}) == 2
    assert {item["sets"][0]["weight"] for item in prescriptions} == {70.0, 85.0}
    assert {item["exerciseDefinitionId"] for item in prescriptions} == {definition_id}
    assert all(item["notes"] == "Canonical bracing instructions" for item in prescriptions)
    assert all(item["placementNotes"] == "" for item in prescriptions)
    assert all(item["muscleGroups"] == supplied_definition["muscleGroups"] for item in prescriptions)


def test_equipment_variations_create_separate_definitions():
    package = {
        "workouts": [{
            "id": str(uuid.uuid4()),
            "globalId": str(uuid.uuid4()),
            "workoutComponents": [
                _exercise(str(uuid.uuid4()), str(uuid.uuid4()), weight=40, equipment_id=str(uuid.uuid4()), name="Row"),
                _exercise(str(uuid.uuid4()), str(uuid.uuid4()), weight=40, equipment_id=str(uuid.uuid4()), name="Row"),
            ],
        }],
    }

    result = apply_exercise_library_schema_v2(package)

    assert len(result["exerciseDefinitions"]) == 2
    assert len({item["exerciseDefinitionId"] for item in result["workouts"][0]["workoutComponents"]}) == 2


def test_only_referenced_movement_assets_are_emitted():
    movement_ref = {"movementId": "squat", "contentHash": "abc", "format": "WEAR_SKELETON_JSON"}
    package = {
        "workouts": [{
            "id": str(uuid.uuid4()),
            "globalId": str(uuid.uuid4()),
            "workoutComponents": [
                {**_exercise(
                    str(uuid.uuid4()), str(uuid.uuid4()), weight=80,
                    equipment_id=str(uuid.uuid4()), name="Squat",
                ), "movementRef": movement_ref},
            ],
        }],
    }
    referenced = {"movementRef": movement_ref, "json": "{\"frames\": []}"}
    unrelated = {"movementRef": {"movementId": "row"}, "json": "{}"}

    result = apply_exercise_library_schema_v2(package, supplied_exercise_movements=[referenced, unrelated])

    assert result["exerciseMovements"] == [referenced]


def test_superset_duplicate_prescription_ids_rewrite_rest_map_keys():
    exercise_id = str(uuid.uuid4())
    package = {
        "workouts": [{
            "id": str(uuid.uuid4()),
            "globalId": str(uuid.uuid4()),
            "workoutComponents": [{
                "id": str(uuid.uuid4()),
                "type": "Superset",
                "exercises": [
                    _exercise(exercise_id, str(uuid.uuid4()), weight=40, equipment_id=str(uuid.uuid4()), name="Row"),
                    _exercise(exercise_id, str(uuid.uuid4()), weight=20, equipment_id=str(uuid.uuid4()), name="Press"),
                ],
                "restSecondsByExercise": {exercise_id: 60},
            }],
        }],
    }

    ensure_unique_ids(package)
    superset = package["workouts"][0]["workoutComponents"][0]

    assert len({exercise["id"] for exercise in superset["exercises"]}) == 2
    assert set(superset["restSecondsByExercise"]) == {exercise["id"] for exercise in superset["exercises"]}


def test_conflicting_supplied_definition_ids_are_rejected():
    definition_id = str(uuid.uuid4())
    definitions = [
        {"id": definition_id, "name": "Squat", "exerciseType": "WEIGHT", "equipmentId": None},
        {"id": definition_id, "name": "Deadlift", "exerciseType": "WEIGHT", "equipmentId": None},
    ]

    with pytest.raises(ValueError, match="Conflicting content"):
        apply_exercise_library_schema_v2({"workouts": []}, definitions)


def test_library_context_is_restored_from_conversation_messages():
    definitions = [{"id": "definition-1", "name": "Squat", "exerciseType": "WEIGHT"}]
    messages = [{
        "role": "system",
        "content": "EXERCISE LIBRARY (schema v2):\n"
        "[{\"id\":\"definition-1\",\"name\":\"Squat\",\"exerciseType\":\"WEIGHT\"}]\n"
        "Treat these fields as definition-owned and immutable.",
    }]

    assert _extract_exercise_library_from_messages(messages) == definitions


def test_plan_contract_rejects_one_prescription_reused_across_periodized_phases():
    plan_index = {
        "planName": "Periodized block",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [{
            "id": "EXERCISE_0",
            "name": "Squat",
            "exerciseType": "WEIGHT",
            "equipmentId": None,
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "minReps": 3,
            "maxReps": 8,
        }],
        "workouts": [
            {
                "id": "WORKOUT_0", "name": "Accumulation",
                "exerciseIds": ["EXERCISE_0"], "restToNextSeconds": [0],
                "supersetGroups": [],
            },
            {
                "id": "WORKOUT_1", "name": "Intensification",
                "exerciseIds": ["EXERCISE_0"], "restToNextSeconds": [0],
                "supersetGroups": [],
            },
        ],
    }

    with pytest.raises(ContractValidationError, match="reused_exercise_prescription"):
        validate_plan_index_contract(plan_index)
