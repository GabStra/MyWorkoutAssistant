from workout_generator_pkg.domain_ops import finalize_and_validate_exercise_definition


def _weight_vest(equipment_id="EQUIPMENT_2", name="Weight Vest"):
    return {
        "id": equipment_id,
        "type": "WEIGHTVEST",
        "name": name,
        "availableWeights": [{"weight": 5.0}, {"weight": 10.0}],
    }


def _pullup_bar():
    return {
        "id": "ACCESSORY_0",
        "type": "ACCESSORY",
        "name": "Pull-Up Bar",
    }


def _weighted_pullup_exercise():
    return {
        "id": "EXERCISE_17",
        "type": "Exercise",
        "enabled": True,
        "name": "Weighted Pull-Up",
        "notes": "",
        "sets": [
            {
                "id": "SET_0",
                "type": "BodyWeightSet",
                "reps": 6,
                "additionalWeight": 10.0,
                "subCategory": "WorkSet",
            },
            {
                "id": "SET_1",
                "type": "RestSet",
                "timeInSeconds": 90,
                "subCategory": "WorkSet",
            },
            {
                "id": "SET_2",
                "type": "BodyWeightSet",
                "reps": 6,
                "additionalWeight": 10.0,
                "subCategory": "WorkSet",
            },
        ],
        "exerciseType": "BODY_WEIGHT",
        "minReps": 6,
        "maxReps": 8,
        "generateWarmUpSets": False,
        "progressionMode": "AUTO_REGULATION",
        "keepScreenOn": False,
        "showCountDownTimer": False,
        "requiresLoadCalibration": False,
        "equipmentId": None,
        "bodyWeightPercentage": 100.0,
        "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
        "muscleGroups": ["BACK_UPPER_BACK", "FRONT_BICEPS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "HEAVY_COMPOUND",
        "intraSetRestInSeconds": None,
    }


def test_finalize_preserves_explicit_null_plan_equipment_id():
    normalized = finalize_and_validate_exercise_definition(
        _weighted_pullup_exercise(),
        plan_entry={
            "id": "EXERCISE_17",
            "exerciseType": "BODY_WEIGHT",
            "equipmentId": None,
            "bodyWeightPercentage": 100.0,
            "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
            "exerciseCategory": "HEAVY_COMPOUND",
            "minReps": 6,
            "maxReps": 8,
        },
        equipment_subset=[_weight_vest()],
        accessory_subset=[_pullup_bar()],
        allow_educated_load_guesses=True,
    )

    assert normalized["equipmentId"] is None


def test_finalize_preserves_explicit_plan_equipment_id_over_inference():
    normalized = finalize_and_validate_exercise_definition(
        _weighted_pullup_exercise(),
        plan_entry={
            "id": "EXERCISE_17",
            "exerciseType": "BODY_WEIGHT",
            "equipmentId": "EQUIPMENT_9",
            "bodyWeightPercentage": 100.0,
            "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
            "exerciseCategory": "HEAVY_COMPOUND",
            "minReps": 6,
            "maxReps": 8,
        },
        equipment_subset=[
            _weight_vest(),
            _weight_vest(equipment_id="EQUIPMENT_9", name="Competition Weight Vest"),
        ],
        accessory_subset=[_pullup_bar()],
        allow_educated_load_guesses=True,
    )

    assert normalized["equipmentId"] == "EQUIPMENT_9"
