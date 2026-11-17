"""Focused recurring-prescription contract regressions."""

import copy
import json

from jsonschema import Draft7Validator

from workout_generator_pkg import prescribed_plan
from workout_generator_pkg.constants import JSON_SCHEMA
from workout_generator_pkg.prescribed_source import (
    _spans,
    load_prescribed_source,
    map_prescribed_facts,
)


def _library(definitions):
    equipment = {"id": "11111111-1111-4111-8111-111111111111", "name": "Barbell", "type": "BARBELL",
                 "barWeight": 40.0, "availablePlates": [], "sleeveLength": 400}
    return {"equipments": [equipment], "accessoryEquipments": [],
            "exerciseDefinitions": [{
                "id": definition_id, "name": name, "exerciseType": "WEIGHT",
                "equipmentId": equipment["id"], "bodyWeightPercentage": None,
                "muscleGroups": ["FRONT_CHEST"], "secondaryMuscleGroups": [],
                "requiredAccessoryEquipmentIds": [], "exerciseCategory": "MODERATE_COMPOUND",
            } for definition_id, name in definitions]}


def _facts_for(text, names, *, program_key="recurring-fixture", session_key="strength-a",
               track_keys=("slot-a", "slot-b")):
    spans = _spans(text)
    exercise_keys = [key for key, line in spans.items()
                     if any(line.startswith(name) for name in names)]
    rest_keys = [key for key, line in spans.items() if line.startswith("REST")]
    exercises = [{
        "sourceKey": key, "rawName": name, "evidenceKeys": [key],
        "recurringExerciseKey": track_keys[index],
    } for index, (key, name) in enumerate(zip(exercise_keys, names))]
    workouts = []
    for index, (exercise_key, rest_key) in enumerate(zip(exercise_keys, rest_keys)):
        workouts.append({
            "name": f"Workout {chr(65 + index)}",
            "recurringSessionKey": session_key,
            "prescriptionOrdinal": index + 1,
            "prescriptionLabel": f"Prescription {index + 1}",
            "blocks": [{"type": "straight", "exerciseKeys": [exercise_key],
                        "restKey": rest_key}],
        })
    return {"planName": "Recurring fixture", "recurringProgramKey": program_key, "unresolved": [],
            "exercises": exercises, "workouts": workouts}


def test_recurring_metadata_survives_mapping_compile_and_schema_export(tmp_path):
    text = ("Workout A\nBench Press 3 x 8 @RPE 7, 40 kg\nREST 60s\n"
            "Workout B\nBench Press 3 x 10 @RPE 9, 40 kg\nREST 60s\n")
    library = _library([("bench", "Bench Press")])
    facts = _facts_for(text, ["Bench Press", "Bench Press"], track_keys=("slot-a", "slot-a"))
    facts["exercises"][1]["loadHistoryPolicy"] = "PRESCRIBED_WEIGHT"

    def extract(_text, _spans):
        return facts

    source = tmp_path / "recurring.txt"
    source.write_text(text, encoding="utf-8")
    outcome = prescribed_plan.run_prescribed_plan(
        source, library, library, state_dir=tmp_path / "state",
        output_dir=tmp_path, output_file=tmp_path / "package.json",
        extract=extract, allow_educated_load_guesses=False,
    )

    assert outcome["success"], outcome.get("error")
    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    workouts = package["workouts"]
    assert len(workouts) == 2
    assert workouts[0]["recurringSessionId"] == workouts[1]["recurringSessionId"]
    assert [workout["prescriptionOrdinal"] for workout in workouts] == [1, 2]
    assert [workout["prescriptionLabel"] for workout in workouts] == [
        "Prescription 1", "Prescription 2"]

    exercises = [workout["workoutComponents"][0] for workout in workouts]
    assert exercises[0]["recurringExerciseId"] == exercises[1]["recurringExerciseId"]
    assert exercises[0]["recurringExerciseId"] != exercises[0]["id"]
    assert [exercise["loadHistoryPolicy"] for exercise in exercises] == ["NONE", "PRESCRIBED_WEIGHT"]
    reps = [[item["reps"] for item in exercise["sets"] if item["type"] == "WeightSet"]
            for exercise in exercises]
    assert reps == [[8, 8, 8], [10, 10, 10]]
    loads = [[item["weight"] for item in exercise["sets"] if item["type"] == "WeightSet"]
             for exercise in exercises]
    assert loads == [[40.0] * 3, [40.0] * 3]
    assert "RPE 7" in exercises[0]["notes"] and "RPE 9" in exercises[1]["notes"]
    assert all(exercise["progressionMode"] == "OFF" for exercise in exercises)
    assert all(item["shouldReapplyHistoryToSet"] is False
               for exercise in exercises for item in exercise["sets"]
               if item["type"] == "WeightSet")

    workout_ids = [workout["id"] for workout in workouts] + [workout["globalId"] for workout in workouts]
    occurrence_ids = [exercise["id"] for exercise in exercises]
    set_ids = [item["id"] for exercise in exercises for item in exercise["sets"]]
    assert len(workout_ids) == len(set(workout_ids))
    assert len(occurrence_ids) == len(set(occurrence_ids))
    assert len(set_ids) == len(set(set_ids))

    for workout in workouts:
        legacy = copy.deepcopy(workout)
        for component in legacy["workoutComponents"]:
            component.pop("exerciseDefinitionId", None)
        Draft7Validator(
            {"$ref": "#/$defs/Workout", "$defs": JSON_SCHEMA["$defs"]}
        ).validate(legacy)


def test_recurring_slots_are_distinct_and_conflicting_track_identity_fails(tmp_path):
    text = ("Workout A\nBench Press 3 x 8, 40 kg\nREST 60s\n"
            "Workout B\nBench Press 3 x 8, 40 kg\nREST 60s\n")
    library = _library([("bench", "Bench Press")])
    distinct = map_prescribed_facts(
        {"facts": _facts_for(text, ["Bench Press", "Bench Press"]),
         "source": {"spans": _spans(text)}}, library)

    assert distinct["unresolved"] == []
    ids = [exercise["recurringExerciseId"]
           for exercise in distinct["planIndex"]["exercises"]]
    assert len(ids) == 2 and len(set(ids)) == 2
    assert len({exercise["recurringExerciseId"] for exercise in distinct["planIndex"]["exercises"]}) == 2
    assert distinct["planIndex"]["workouts"][0]["recurringSessionId"] == \
        distinct["planIndex"]["workouts"][1]["recurringSessionId"]
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(distinct["planIndex"]), encoding="utf-8")
    imported = load_prescribed_source(plan_path, library)
    assert imported["unresolved"] == []
    assert [exercise["recurringExerciseId"]
            for exercise in imported["planIndex"]["exercises"]] == ids

    conflict_text = ("Workout A\nBench Press 3 x 8, 40 kg\nREST 60s\n"
                     "Workout B\nIncline Press 3 x 8, 40 kg\nREST 60s\n")
    conflict_facts = _facts_for(
        conflict_text, ["Bench Press", "Incline Press"], track_keys=("slot-a", "slot-a"))
    conflict = map_prescribed_facts(
        {"facts": conflict_facts, "source": {"spans": _spans(conflict_text)}},
        _library([("bench", "Bench Press"), ("incline", "Incline Press")]))
    assert conflict["planIndex"] is None
    assert any(issue["reason"] == "conflicting_recurring_exercise_track"
               for issue in conflict["unresolved"])

    no_track_text = "Bench Press 3 x 8, 40 kg\nREST 60s\n"
    no_track_spans = _spans(no_track_text)
    no_track_exercise = next(key for key, line in no_track_spans.items()
                             if line.startswith("Bench Press"))
    no_track_rest = next(key for key, line in no_track_spans.items()
                         if line.startswith("REST"))
    no_track = map_prescribed_facts(
        {"facts": {"planName": "No track", "unresolved": [], "workouts": [{
            "name": "Workout A", "recurringSessionKey": "strength-a",
            "blocks": [{"type": "straight", "exerciseKeys": [no_track_exercise],
                        "restKey": no_track_rest}],
        }], "exercises": [{
            "sourceKey": no_track_exercise, "rawName": "Bench Press",
            "evidenceKeys": [no_track_exercise],
            "loadHistoryPolicy": "LAST_WORKING_LOAD",
        }]}, "source": {"spans": no_track_spans}}, library)
    assert no_track["planIndex"] is None
    assert any(issue["reason"] == "recurring_track_required_for_load_history"
               for issue in no_track["unresolved"])

    tracked_facts = {
        "planName": "Tracked load", "recurringProgramKey": "tracked", "unresolved": [],
        "workouts": [{
            "name": "Workout A", "recurringSessionKey": "strength-a",
            "blocks": [{"type": "straight", "exerciseKeys": [no_track_exercise],
                        "restKey": no_track_rest}],
        }],
        "exercises": [{
            "sourceKey": no_track_exercise, "rawName": "Bench Press",
            "evidenceKeys": [no_track_exercise], "recurringExerciseKey": "slot-a",
            "loadHistoryPolicy": "LAST_WORKING_LOAD",
        }],
    }
    tracked = map_prescribed_facts(
        {"facts": tracked_facts, "source": {"spans": no_track_spans}}, library)
    assert tracked["unresolved"] == []
    assert tracked["planIndex"]["exercises"][0]["loadHistoryPolicy"] == "LAST_WORKING_LOAD"
    assert tracked["planIndex"]["exercises"][0]["minReps"] == 8


def test_non_recurring_source_keeps_existing_metadata_defaults():
    text = "Bench Press 3 x 8, 40 kg\nREST 60s\n"
    spans = _spans(text)
    exercise_key = next(key for key, line in spans.items() if line.startswith("Bench Press"))
    rest_key = next(key for key, line in spans.items() if line.startswith("REST"))
    result = map_prescribed_facts({"facts": {
        "planName": "Legacy", "unresolved": [],
        "exercises": [{"sourceKey": exercise_key, "rawName": "Bench Press",
                       "evidenceKeys": [exercise_key]}],
        "workouts": [{"name": "Workout A", "blocks": [{
            "type": "straight", "exerciseKeys": [exercise_key], "restKey": rest_key}]}],
    }, "source": {"spans": spans}}, _library([("bench", "Bench Press")]))

    assert result["unresolved"] == []
    assert "recurringSessionId" not in result["planIndex"]["workouts"][0]
    assert "recurringExerciseId" not in result["planIndex"]["exercises"][0]
    assert "loadHistoryPolicy" not in result["planIndex"]["exercises"][0]


def test_program_namespace_and_source_order_ordinals_are_stable():
    text = ("Workout A\nBench Press 3 x 8, 40 kg\nREST 60s\n"
            "Workout B\nBench Press 3 x 9, 40 kg\nREST 60s\n")
    library = _library([("bench", "Bench Press")])
    facts = _facts_for(text, ["Bench Press", "Bench Press"], track_keys=("same-slot", "same-slot"))
    facts["workouts"][0].pop("prescriptionOrdinal")
    facts["workouts"][1].pop("prescriptionOrdinal")
    first = map_prescribed_facts({"facts": facts, "source": {"spans": _spans(text)}}, library)
    assert first["unresolved"] == []
    assert [workout["prescriptionOrdinal"] for workout in first["planIndex"]["workouts"]] == [1, 2]

    separate_program = copy.deepcopy(facts)
    separate_program["recurringProgramKey"] = "another-program"
    second = map_prescribed_facts(
        {"facts": separate_program, "source": {"spans": _spans(text)}}, library)
    assert second["unresolved"] == []
    assert first["planIndex"]["workouts"][0]["recurringSessionId"] != \
        second["planIndex"]["workouts"][0]["recurringSessionId"]
    assert first["planIndex"]["exercises"][0]["recurringExerciseId"] != \
        second["planIndex"]["exercises"][0]["recurringExerciseId"]

    missing_namespace = copy.deepcopy(facts)
    missing_namespace.pop("recurringProgramKey")
    rejected = map_prescribed_facts(
        {"facts": missing_namespace, "source": {"spans": _spans(text)}}, library)
    assert rejected["planIndex"] is None
    assert any(issue["reason"] == "recurring_program_key_required" for issue in rejected["unresolved"])

    from workout_generator_pkg.prescribed_recurrence import recurring_session_uuid
    assert recurring_session_uuid("p:a", "b") != recurring_session_uuid("p", "a:b")
