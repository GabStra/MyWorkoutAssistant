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
        "id": "WORKOUT_0", "name": "Day C", "description": "Full body",
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
    assert [component["componentType"] for component in structure["workoutComponents"]] == ["Exercise", "Rest", "Superset", "Rest", "Exercise"]
    assert structure["workoutComponents"][3]["timeInSeconds"] == 75
    assert structure["workoutComponents"][2]["roundDurationSeconds"] == 120
    validate_workout_structures_contract(plan, {"WORKOUT_0": structure}, definitions)


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
        "notes": "", "exerciseType": "WEIGHT", "equipmentId": "EQUIPMENT_0", "bodyWeightPercentage": None,
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
    plan["targetSetPrescriptions"] = [{"workSetIndex": 0, "reps": 8, "weight": guess}]
    with pytest.raises(ValueError, match="invalid weights"):
        finalize_and_validate_exercise_definition(exercise, plan, equipment_subset=equipment)


def test_planner_example_contains_only_referenced_numeric_exercises():
    references = {reference for workout in PLAN_INDEX_EXAMPLE["workouts"] for reference in workout["exerciseIds"]}
    assert {exercise["id"] for exercise in PLAN_INDEX_EXAMPLE["exercises"]} == references
    assert "EXERCISE_WARMUP" not in references
