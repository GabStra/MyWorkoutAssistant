from workout_generator_pkg.domain_ops import ensure_requiresLoadCalibration
from workout_generator_pkg.domain_ops import finalize_and_validate_exercise_definition


def test_finalize_strict_mode_forces_calibration_for_weight_exercise():
    exercise = {
        "id": "EXERCISE_0",
        "type": "Exercise",
        "enabled": True,
        "name": "Bench Press",
        "notes": "",
        "sets": [
            {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"},
        ],
        "exerciseType": "WEIGHT",
        "minReps": 6,
        "maxReps": 8,
        "generateWarmUpSets": False,
        "progressionMode": "OFF",
        "keepScreenOn": False,
        "showCountDownTimer": False,
        "requiresLoadCalibration": False,
        "equipmentId": "EQUIPMENT_0",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_CHEST"],
    }
    equipment_subset = [
        {
            "id": "EQUIPMENT_0",
            "type": "BARBELL",
            "name": "Standard Barbell",
            "availablePlates": [{"weight": 20.0, "thickness": 20.0}],
            "barWeight": 20.0,
            "sleeveLength": 300,
        }
    ]

    normalized = finalize_and_validate_exercise_definition(exercise, equipment_subset=equipment_subset)

    assert normalized["requiresLoadCalibration"] is True


def test_finalize_disables_calibration_for_loaded_weight_exercise_when_enabled():
    exercise = {
        "id": "EXERCISE_0",
        "type": "Exercise",
        "enabled": True,
        "name": "Bench Press",
        "notes": "",
        "sets": [
            {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"},
        ],
        "exerciseType": "WEIGHT",
        "minReps": 6,
        "maxReps": 8,
        "generateWarmUpSets": False,
        "progressionMode": "OFF",
        "keepScreenOn": False,
        "showCountDownTimer": False,
        "requiresLoadCalibration": True,
        "equipmentId": "EQUIPMENT_0",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_CHEST"],
    }
    equipment_subset = [
        {
            "id": "EQUIPMENT_0",
            "type": "BARBELL",
            "name": "Standard Barbell",
            "availablePlates": [{"weight": 20.0, "thickness": 20.0}],
            "barWeight": 20.0,
            "sleeveLength": 300,
        }
    ]

    normalized = finalize_and_validate_exercise_definition(
        exercise,
        equipment_subset=equipment_subset,
        allow_educated_load_guesses=True,
    )

    assert normalized["requiresLoadCalibration"] is False


def test_ensure_requires_load_calibration_uses_explicit_work_set_loads_when_enabled():
    workout_store = {
        "workouts": [
            {
                "workoutComponents": [
                    {
                        "id": "EXERCISE_0",
                        "type": "Exercise",
                        "exerciseType": "WEIGHT",
                        "equipmentId": "EQUIPMENT_0",
                        "sets": [
                            {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"},
                        ],
                    },
                    {
                        "id": "EXERCISE_1",
                        "type": "Exercise",
                        "exerciseType": "WEIGHT",
                        "equipmentId": "EQUIPMENT_1",
                        "sets": [
                            {"id": "SET_0", "type": "WeightSet", "reps": 8, "subCategory": "WorkSet"},
                        ],
                    },
                ]
            }
        ]
    }

    ensure_requiresLoadCalibration(workout_store, allow_educated_load_guesses=True)
    components = workout_store["workouts"][0]["workoutComponents"]

    assert components[0]["requiresLoadCalibration"] is False
    assert components[1]["requiresLoadCalibration"] is True
