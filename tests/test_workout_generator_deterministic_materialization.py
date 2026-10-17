import pytest

from workout_generator_pkg import cli
from workout_generator_pkg.plan_contract import validate_single_exercise_definition_contract, validate_workout_structures_contract


def _plan_entry(exercise_type, **overrides):
    entry = {
        "id": "EXERCISE_0",
        "name": "Library movement",
        "exerciseType": exercise_type,
        "equipmentId": "EQUIPMENT_0" if exercise_type in {"WEIGHT", "BODY_WEIGHT"} else None,
        "bodyWeightPercentage": 100.0 if exercise_type == "BODY_WEIGHT" else None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_QUADRICEPS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "MODERATE_COMPOUND" if exercise_type in {"WEIGHT", "BODY_WEIGHT"} else None,
        "generateWarmUpSets": False,
        "intraSetRestInSeconds": None,
        "numWorkSets": 2,
        "restBetweenSetsSeconds": 60,
        "placementNotes": "approved placement",
    }
    if exercise_type in {"WEIGHT", "BODY_WEIGHT"}:
        entry.update(minReps=8, maxReps=12)
    entry.update(overrides)
    return entry


def _emit(monkeypatch, entry):
    def no_model(*_args, **_kwargs):
        raise AssertionError("Deterministic materialization must not call a model")

    monkeypatch.setattr(cli, "json_call_chat_max_with_loading", no_model)
    monkeypatch.setattr(cli, "json_call_reasoner_only_with_loading", no_model)
    equipment = [{"id": "EQUIPMENT_0", "type": "GENERIC", "name": "Available weights"}]
    result, log_entry = cli.emit_exercise_definition(
        entry["id"], client=None, context_summary="", plan_index={"exercises": [entry]},
        equipment_subset=equipment, accessory_subset=[], provided_equipment={"equipments": equipment},
        deterministic=True,
    )
    assert log_entry is None
    validate_single_exercise_definition_contract(entry, result)
    return result


def test_deterministic_weight_materialization_preserves_exact_targets(monkeypatch):
    entry = _plan_entry("WEIGHT", targetSetPrescriptions=[
        {"workSetIndex": 0, "reps": 10, "weight": 42.5},
        {"workSetIndex": 1, "reps": 9, "weight": 42.5},
    ])

    result = _emit(monkeypatch, entry)

    assert [(s["reps"], s["weight"]) for s in result["sets"] if s["type"] == "WeightSet"] == [(10, 42.5), (9, 42.5)]
    assert [s["timeInSeconds"] for s in result["sets"] if s["type"] == "RestSet"] == [60]
    assert result["requiresLoadCalibration"] is False
    assert result["muscleGroups"] == entry["muscleGroups"]


@pytest.mark.parametrize("exercise_type,load_field", [("WEIGHT", "weight"), ("BODY_WEIGHT", "additionalWeight")])
def test_deterministic_uncalibrated_load_uses_explicit_calibration_placeholder(monkeypatch, exercise_type, load_field):
    result = _emit(monkeypatch, _plan_entry(exercise_type))

    work_sets = [s for s in result["sets"] if s["type"] != "RestSet"]
    assert [s[load_field] for s in work_sets] == [0, 0]
    assert [s["reps"] for s in work_sets] == [8, 8]
    assert result["requiresLoadCalibration"] is True
    assert result["progressionMode"] == "AUTO_REGULATION"


@pytest.mark.parametrize(
    "exercise_type,duration_seconds,expected_type,expected_auto_stop",
    [("COUNTDOWN", 45, "TimedDurationSet", True), ("COUNTUP", 0, "EnduranceSet", False)],
)
def test_deterministic_timed_materialization_uses_app_timer_defaults(
    monkeypatch, exercise_type, duration_seconds, expected_type, expected_auto_stop
):
    result = _emit(monkeypatch, _plan_entry(exercise_type, durationSeconds=duration_seconds))

    work_sets = [s for s in result["sets"] if s["type"] != "RestSet"]
    assert [s["type"] for s in work_sets] == [expected_type, expected_type]
    assert [s["timeInMillis"] for s in work_sets] == [duration_seconds * 1000] * 2
    assert all(s["autoStart"] is True and s["autoStop"] is expected_auto_stop for s in work_sets)
    assert len([s for s in result["sets"] if s["type"] == "RestSet"]) == 1


def test_deterministic_running_materialization_preserves_explicit_target(monkeypatch):
    prescription = {"environment": "OUTDOOR", "targetType": "DISTANCE", "targetValue": 800}
    result = _emit(monkeypatch, _plan_entry("RUNNING", numWorkSets=1, runningPrescription=prescription))

    assert result["sets"] == [{"id": "SET_0", "type": "RunningSet"}]
    assert result["runningPrescription"] == prescription


def test_deterministic_materialization_rejects_missing_approved_load_target(monkeypatch):
    entry = _plan_entry("WEIGHT", targetSetPrescriptions=[{"workSetIndex": 0, "reps": 10, "weight": 42.5}])
    with pytest.raises(ValueError, match="one targetSetPrescriptions entry per work set"):
        _emit(monkeypatch, entry)


def test_production_structure_emitter_keeps_superset_membership_without_model_calls(monkeypatch):
    def no_model(*_args, **_kwargs):
        raise AssertionError("Workout structure construction must not call a model")

    monkeypatch.setattr(cli, "json_call_chat_max_with_loading", no_model)
    monkeypatch.setattr(cli, "json_call_reasoner_only_with_loading", no_model)
    workout = {
        "id": "WORKOUT_0",
        "name": "Full Body",
        "exerciseIds": ["EXERCISE_0", "EXERCISE_1"],
        "restToNextSeconds": [0, 0],
        "supersetGroups": [{
            "exerciseIds": ["EXERCISE_0", "EXERCISE_1"],
            "restSecondsByExercise": {"EXERCISE_0": 40, "EXERCISE_1": 75},
        }],
    }
    plan_index = {"workouts": [workout]}
    definitions = {exercise_id: {"id": exercise_id} for exercise_id in workout["exerciseIds"]}

    structure, conversation = cli.emit_workout_structure(
        "WORKOUT_0", None, "", plan_index, definitions, use_reasoner=True
    )

    assert conversation is None
    assert structure["workoutComponents"][0]["componentType"] == "Superset"
    assert structure["workoutComponents"][0]["restSecondsByExercise"] == {
        "EXERCISE_0": 40, "EXERCISE_1": 75,
    }
    validate_workout_structures_contract(plan_index, {"WORKOUT_0": structure}, definitions)
