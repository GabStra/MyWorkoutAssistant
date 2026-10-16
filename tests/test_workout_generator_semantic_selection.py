import copy
import json
import threading
import time

import pytest

from workout_generator_pkg import exercise_library_tools as library_tools
from workout_generator_pkg.domain_ops import (
    finalize_and_validate_exercise_definition, sync_exercises_from_definitions,
    sync_exercises_from_plan_index, ensure_requiresLoadCalibration,
)
from workout_generator_pkg.plan_contract import (
    ContractValidationError, validate_workout_structures_contract,
    validate_assembled_workout_contract,
)


def test_semantic_search_uses_bounded_batches_and_returns_real_entries(monkeypatch):
    definitions = [{"id": f"definition-{i}", "name": f"Exercise {i}"} for i in range(260)]
    definitions[0]["name"] = "Barbell Bench Press"
    batch_sizes = []

    def rank(_client, messages, **kwargs):
        assert kwargs == {"reasoning_effort": "low", "max_tokens": 8192, "timeout": 90}
        request = json.loads(messages[-1]["content"])
        batch_sizes.append(len(request["catalog"]))
        matches = ([{"index": i, "score": 0.99 - i * 0.01} for i in range(10)]
                   if request["catalog"][0][0] == 0 else [])
        return json.dumps({"matches": [matches]}), None, None

    monkeypatch.setattr(library_tools, "chat_call", rank)
    result = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["horizontal chest push"]},
        {"exerciseDefinitions": definitions}, client=object(),
    )
    assert sorted(batch_sizes) == [4, 64, 64, 64, 64]
    assert len(result["results"][0]["exercises"]) == 6
    assert result["results"][0]["exercises"][0]["id"] == "LIBRARY_0"
    assert result["results"][0]["exercises"][0]["name"] == "Barbell Bench Press"
    selection = library_tools.execute_library_tool("select_exercises", {"definition_ids": ["LIBRARY_0"]}, {"exerciseDefinitions": list(reversed(definitions))})
    assert selection["selectedExerciseDefinitionIds"] == ["definition-0"]


def test_semantic_search_jobs_bound_queries_catalog_and_parallelism(monkeypatch):
    active = 0
    max_active = 0
    lock = threading.Lock()
    job_sizes = []

    def rank(_client, messages, **kwargs):
        nonlocal active, max_active
        request = json.loads(messages[-1]["content"])
        with lock:
            active += 1
            max_active = max(max_active, active)
        job_sizes.append((len(request["queries"]), len(request["catalog"])))
        time.sleep(0.01)
        with lock:
            active -= 1
        return json.dumps({"matches": [[] for _ in request["queries"]]}), None, None

    monkeypatch.setattr(library_tools, "chat_call", rank)
    progress = []
    result = library_tools._semantic_matches(
        object(), [f"query {i}" for i in range(7)], [{"name": f"Exercise {i}"} for i in range(130)],
        progress=lambda done, total: progress.append((done, total)),
    )
    assert result == [{} for _ in range(7)]
    assert progress == [(done, 9) for done in range(10)]
    assert len(job_sizes) == 9
    assert all(query_count <= 3 and catalog_count <= 64 for query_count, catalog_count in job_sizes)
    assert max_active <= 3


def test_semantic_search_and_selection_reject_invented_candidates(monkeypatch):
    gear = {"exerciseDefinitions": [{"id": "definition-0", "name": "Bench Press"}]}
    monkeypatch.setattr(library_tools, "chat_call", lambda *_, **kw: ('{"matches":[[{"index":99,"score":1}]]}', None, None))
    failed_search = library_tools.execute_library_tool("search_exercise_library", {"queries": ["press"]}, gear, client=object())
    assert "unknown index" in failed_search["results"][0]["error"]
    assert failed_search["instruction"]
    with pytest.raises(ValueError, match="Unknown library definition IDs"):
        library_tools.execute_library_tool("select_exercises", {"definition_ids": ["invented"]}, gear)


def test_truncated_semantic_search_preserves_exact_hits_and_reports_failed_queries(monkeypatch):
    gear = {"exerciseDefinitions": [
        {"id": "bench", "name": "Bench Press"},
        {"id": "row", "name": "Cable Row"},
    ]}

    def truncated(*_args, **_kwargs):
        raise ValueError("Response truncated at the 4096-token low-effort budget")

    monkeypatch.setattr(library_tools, "chat_call", truncated)
    result = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["bench press", "horizontal pull"]}, gear, client=object(),
    )
    assert result["results"][0]["exercises"][0]["id"] == "LIBRARY_0"
    assert result["results"][1]["error"].startswith("Semantic search failed:")
    assert "exercises" not in result["results"][1]
    assert "do not repeat the same failed query unchanged" in result["instruction"]


def test_selection_must_precede_confirmation_and_survives_saved_messages():
    messages = [
        {"role": "user", "content": "Make a plan"},
        {"role": "assistant", "tool_calls": [{"id": "selection", "function": {"name": "select_exercises"}}]},
        {"role": "tool", "tool_call_id": "selection", "content": '{"selectedExerciseDefinitionIds":["definition-0"]}'},
        {"role": "assistant", "content": "Preview"},
        {"role": "user", "content": "CONFIRM GENERATE"},
    ]
    assert library_tools.selected_library_ids_from_messages(json.loads(json.dumps(messages))) == ["definition-0"]
    late_selection = [messages[0], messages[-1], *messages[1:4]]
    assert library_tools.selected_library_ids_from_messages(late_selection) == []


def _selection_turn(ids, preview):
    return [
        {"role": "assistant", "tool_calls": [{"id": "selection", "function": {"name": "select_exercises"}}]},
        {"role": "tool", "tool_call_id": "selection", "content": json.dumps({"selectedExerciseDefinitionIds": ids})},
        {"role": "assistant", "content": preview},
    ]


def test_revision_invalidates_stale_selection_before_generation():
    messages = [
        {"role": "user", "content": "Create a plan"},
        *_selection_turn(["deadlift"], "| Exercise | Sets |\n|---|---|\n| Barbell Deadlift | 3 |"),
        {"role": "user", "content": "Remove the deadlift; RDL only"},
        {"role": "assistant", "content": "| Exercise | Sets |\n|---|---|\n| Romanian Deadlift | 3 |"},
        {"role": "user", "content": "CONFIRM GENERATE"},
    ]
    assert library_tools.selected_library_ids_from_messages(messages) == []
    messages[-2:-1] = _selection_turn(["rdl"], messages[-2]["content"])
    assert library_tools.selected_library_ids_from_messages(messages, [{"id": "rdl", "name": "Romanian Deadlift"}]) == ["rdl"]


def test_unused_selected_alternative_cannot_be_restored_by_repair():
    definitions = [{"id": "rdl", "name": "Romanian Deadlift"}, {"id": "deadlift", "name": "Barbell Deadlift"}]
    messages = [
        {"role": "user", "content": "RDL only"},
        *_selection_turn(["rdl", "deadlift"],
                        "| Order | Exercise | Sets |\n|---|---|---|\n| 1 | **Romanian Deadlift** | 3 |\n\nBarbell Deadlift is removed."),
        {"role": "user", "content": "CONFIRM GENERATE"},
    ]
    with pytest.raises(ValueError, match="Selected but not in exercise rows.*barbell deadlift"):
        library_tools.selected_library_ids_from_messages(messages, definitions)
    messages[2]["content"] = '{"selectedExerciseDefinitionIds":["rdl"]}'
    assert library_tools.selected_library_ids_from_messages(messages, definitions) == ["rdl"]


def _rest_plan():
    return {
        "exercises": [{"id": f"EXERCISE_{i}"} for i in range(4)],
        "workouts": [{
            "id": "WORKOUT_0", "name": "Day C", "exerciseIds": [f"EXERCISE_{i}" for i in range(4)],
            "restToNextSeconds": [150, 120, 0, 0],
            "supersetGroups": [{
                "exerciseIds": ["EXERCISE_2", "EXERCISE_3"],
                "restSecondsByExercise": {"EXERCISE_2": 40, "EXERCISE_3": 90},
            }],
        }],
    }


def _rest_structure():
    return {"workoutMetadata": {"name": "Day C"}, "workoutComponents": [
        {"componentType": "Exercise", "exerciseId": "EXERCISE_0"},
        {"componentType": "Rest", "timeInSeconds": 150},
        {"componentType": "Exercise", "exerciseId": "EXERCISE_1"},
        {"componentType": "Rest", "timeInSeconds": 120},
        {"componentType": "Superset", "exerciseIds": ["EXERCISE_2", "EXERCISE_3"],
         "restSecondsByExercise": {"EXERCISE_2": 40, "EXERCISE_3": 90}},
    ]}


@pytest.mark.parametrize("defect", ["missing_round_rest", "misplaced_transition"])
def test_rest_contract_separates_round_recovery_and_rejects_misplaced_transitions(defect):
    plan = _rest_plan()
    structure = _rest_structure()
    definitions = {exercise["id"]: exercise for exercise in plan["exercises"]}
    validate_workout_structures_contract(plan, {"WORKOUT_0": structure}, definitions)
    if defect == "missing_round_rest":
        structure["workoutComponents"][-1]["restSecondsByExercise"]["EXERCISE_3"] = 0
    else:
        structure["workoutComponents"].insert(0, structure["workoutComponents"].pop(1))
    with pytest.raises(ContractValidationError, match="rest"):
        validate_workout_structures_contract(plan, {"WORKOUT_0": structure}, definitions)


def test_final_contract_rejects_repair_that_changes_work_set_count():
    plan = {"exercises": [{"id": "EXERCISE_0", "numWorkSets": 3}], "workouts": [
        {"id": "WORKOUT_0", "name": "Day", "exerciseIds": ["EXERCISE_0"], "restToNextSeconds": [0]},
    ]}
    package = {"workouts": [{"id": "WORKOUT_0", "name": "Day", "workoutComponents": [{
        "id": "EXERCISE_0", "type": "Exercise", "sets": [{"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 20}],
    }]}]}
    with pytest.raises(ContractValidationError, match="work set count"):
        validate_assembled_workout_contract(plan, package)


def test_plan_guidance_survives_repair_and_loaded_guesses_require_calibration():
    exercise = {
        "id": "EXERCISE_0", "type": "Exercise", "enabled": True, "name": "Bench Press",
        "notes": "", "placementNotes": "", "exerciseType": "WEIGHT", "equipmentId": "EQUIPMENT_0",
        "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [], "muscleGroups": ["FRONT_CHEST"],
        "minReps": 6, "maxReps": 8, "generateWarmUpSets": False, "progressionMode": "OFF",
        "showCountDownTimer": False, "keepScreenOn": False, "requiresLoadCalibration": False,
        "sets": [{"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"}],
    }
    plan_entry = {
        "id": "EXERCISE_0", "exerciseType": "WEIGHT", "equipmentId": "EQUIPMENT_0",
        "placementNotes": "Keep 1–2 RIR. Add load after reaching 8 reps on every set.",
        "generateWarmUpSets": True, "progressionMode": "AUTO_REGULATION",
    }
    equipment = [{"id": "EQUIPMENT_0", "type": "BARBELL", "name": "Barbell", "barWeight": 20,
                  "sleeveLength": 300, "availablePlates": [{"weight": 20, "thickness": 20}]}]
    normalized = finalize_and_validate_exercise_definition(exercise, plan_entry, equipment_subset=equipment)
    assert normalized["requiresLoadCalibration"] is True
    assert normalized["placementNotes"] == plan_entry["placementNotes"]
    explicit_plan = {**plan_entry, "targetSetPrescriptions": [{"workSetIndex": 0, "reps": 8, "weight": 60.0}]}
    explicit = finalize_and_validate_exercise_definition(exercise, explicit_plan, equipment_subset=equipment)
    assert explicit["requiresLoadCalibration"] is False
    package = {"workouts": [{"workoutComponents": [copy.deepcopy(normalized)]}]}
    package["workouts"][0]["workoutComponents"][0]["placementNotes"] = ""
    sync_exercises_from_definitions(package, {"EXERCISE_0": normalized})
    sync_exercises_from_plan_index(package, {"exercises": [plan_entry]})
    ensure_requiresLoadCalibration(package)
    restored = package["workouts"][0]["workoutComponents"][0]
    assert restored["placementNotes"] == plan_entry["placementNotes"]
    assert restored["requiresLoadCalibration"] is True
