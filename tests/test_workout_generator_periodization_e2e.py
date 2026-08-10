from __future__ import annotations

import json
import uuid

from workout_generator_pkg.cli import PlaceholderIdManager, save_workout_to_file
from workout_generator_pkg.domain_ops import (
    apply_exercise_library_schema_v2,
    assemble_placeholder_workout_store,
    convert_placeholders_to_uuids,
    ensure_requiresLoadCalibration,
    sync_exercises_from_definitions,
    sync_exercises_from_plan_index,
)
from workout_generator_pkg.plan_contract import (
    validate_exercise_definitions_contract,
    validate_plan_index_contract,
    validate_uuid_conversion_parity,
    validate_workout_structures_contract,
)


def _plan_exercise(exercise_id: str, *, reps: int, work_sets: int) -> dict:
    return {
        "id": exercise_id,
        "name": "Dumbbell Lateral Raise",
        "exerciseType": "WEIGHT",
        "equipmentId": None,
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "minReps": 10,
        "maxReps": 15,
        "numWorkSets": work_sets,
        "targetSetPrescriptions": [
            {"workSetIndex": index, "reps": reps, "weight": 8.0}
            for index in range(work_sets)
        ],
    }


def _emitted_exercise(exercise_id: str, *, reps: int, work_sets: int, placement_notes: str) -> dict:
    sets = []
    set_index = 0
    for work_set_index in range(work_sets):
        if work_set_index:
            sets.append(
                {
                    "id": f"SET_{set_index}",
                    "type": "RestSet",
                    "timeInSeconds": 75,
                    "subCategory": "WorkSet",
                }
            )
            set_index += 1
        sets.append(
            {
                "id": f"SET_{set_index}",
                "type": "WeightSet",
                "reps": reps,
                "weight": 8.0,
                "subCategory": "WorkSet",
            }
        )
        set_index += 1

    return {
        "id": exercise_id,
        "type": "Exercise",
        "enabled": True,
        "name": "Dumbbell Lateral Raise",
        "notes": "Raise in the scapular plane without shrugging.",
        "placementNotes": placement_notes,
        "exerciseType": "WEIGHT",
        "equipmentId": None,
        "bodyWeightPercentage": None,
        "muscleGroups": ["FRONT_DELTOIDS"],
        "secondaryMuscleGroups": [],
        "requiredAccessoryEquipmentIds": [],
        "exerciseCategory": "ISOLATION",
        "sets": sets,
        "minReps": 10,
        "maxReps": 15,
        "generateWarmUpSets": False,
        "progressionMode": "AUTO_REGULATION",
        "requiresLoadCalibration": False,
        "showCountDownTimer": False,
        "keepScreenOn": False,
        "intraSetRestInSeconds": None,
    }


def test_periodized_generation_writes_importable_schema_v2_package(tmp_path) -> None:
    """Exercise the deterministic generator path from stage artifacts to saved package."""
    phases = [
        ("Week 1 - Hypertrophy A", 10, 2, "Leave three reps in reserve."),
        ("Week 2 - Hypertrophy A", 12, 2, "Add reps while keeping two reps in reserve."),
        ("Week 3 - Hypertrophy A", 12, 3, "Add one work set if recovered."),
        ("Week 4 - Hypertrophy A Deload", 10, 1, "Deload: reduce work sets."),
    ]
    plan_exercises = [
        _plan_exercise(f"EXERCISE_{index}", reps=reps, work_sets=work_sets)
        for index, (_, reps, work_sets, _) in enumerate(phases)
    ]
    plan_index = {
        "planName": "CrossFit Supplemental Hypertrophy",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": plan_exercises,
        "workouts": [
            {
                "id": f"WORKOUT_{index}",
                "name": name,
                "exerciseIds": [f"EXERCISE_{index}"],
                "restToNextSeconds": [0],
                "supersetGroups": [],
            }
            for index, (name, _, _, _) in enumerate(phases)
        ],
    }
    exercise_definitions = {
        f"EXERCISE_{index}": _emitted_exercise(
            f"EXERCISE_{index}",
            reps=reps,
            work_sets=work_sets,
            placement_notes=placement_notes,
        )
        for index, (_, reps, work_sets, placement_notes) in enumerate(phases)
    }
    workout_structures = {
        f"WORKOUT_{index}": {
            "workoutMetadata": {
                "name": name,
                "description": "Hypertrophy around CrossFit.",
                "enabled": True,
                "isActive": True,
            },
            "workoutComponents": [
                {
                    "componentType": "Exercise",
                    "exerciseId": f"EXERCISE_{index}",
                    "enabled": True,
                }
            ],
        }
        for index, (name, _, _, _) in enumerate(phases)
    }

    validate_plan_index_contract(plan_index)
    validate_exercise_definitions_contract(plan_index, exercise_definitions)
    validate_workout_structures_contract(plan_index, workout_structures, exercise_definitions)

    placeholder_package = assemble_placeholder_workout_store(
        {}, {}, exercise_definitions, workout_structures, plan_index
    )
    placeholder_package = sync_exercises_from_definitions(
        placeholder_package, exercise_definitions
    )
    placeholder_package = sync_exercises_from_plan_index(placeholder_package, plan_index)

    id_manager = PlaceholderIdManager()
    uuid_package = convert_placeholders_to_uuids(
        placeholder_package, id_manager, validate_final=True
    )
    validate_uuid_conversion_parity(placeholder_package, uuid_package)

    library_definition_id = str(uuid.uuid4())
    library_definition = {
        "id": library_definition_id,
        "name": "Dumbbell Lateral Raise",
        "instructions": "Raise in the scapular plane without shrugging.",
        "exerciseType": "WEIGHT",
        "equipmentId": None,
        "bodyWeightPercentage": None,
        "muscleGroups": ["FRONT_DELTOIDS"],
        "secondaryMuscleGroups": [],
        "requiredAccessoryEquipmentIds": [],
        "exerciseCategory": "ISOLATION",
    }
    final_package = apply_exercise_library_schema_v2(
        uuid_package, [library_definition]
    )
    ensure_requiresLoadCalibration(
        final_package, allow_educated_load_guesses=False
    )

    saved_path = save_workout_to_file(final_package, str(tmp_path))
    assert saved_path is not None
    persisted = json.loads(open(saved_path, encoding="utf-8").read())

    assert persisted["schemaVersion"] == 2
    assert persisted["exerciseDefinitions"] == [library_definition]
    assert len(persisted["workouts"]) == 4

    prescriptions = [
        workout["workoutComponents"][0] for workout in persisted["workouts"]
    ]
    assert len({exercise["id"] for exercise in prescriptions}) == 4
    assert {exercise["exerciseDefinitionId"] for exercise in prescriptions} == {
        library_definition_id
    }
    assert [
        sum(1 for set_item in exercise["sets"] if set_item["type"] == "WeightSet")
        for exercise in prescriptions
    ] == [2, 2, 3, 1]
    assert [exercise["sets"][0]["reps"] for exercise in prescriptions] == [10, 12, 12, 10]
    assert [exercise["placementNotes"] for exercise in prescriptions] == [
        phase[3] for phase in phases
    ]

    all_set_ids = [
        set_item["id"]
        for exercise in prescriptions
        for set_item in exercise["sets"]
    ]
    assert len(all_set_ids) == len(set(all_set_ids))

    # Transitional fields remain materialized for legacy mobile/Wear readers.
    assert all(exercise["name"] == library_definition["name"] for exercise in prescriptions)
    assert all(
        exercise["notes"] == library_definition["instructions"]
        for exercise in prescriptions
    )
    assert all(exercise["exerciseType"] == "WEIGHT" for exercise in prescriptions)
    assert all(exercise["requiresLoadCalibration"] is True for exercise in prescriptions)
