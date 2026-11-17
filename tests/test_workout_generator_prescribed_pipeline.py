"""Focused checks for direct prescribed-plan compilation and repair artifacts."""

import json
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft7Validator, ValidationError

from workout_generator_pkg import generation_pipeline
from workout_generator_pkg.constants import JSON_SCHEMA
from workout_generator_pkg.planning_tools import confirmed_draft


def test_compile_plan_index_uses_native_gates_without_review_or_provider_calls(tmp_path, monkeypatch):
    from test_workout_generator_compiler_export import confirmed_recipe
    from workout_generator_pkg import api_client, plan_review

    equipment, messages = confirmed_recipe(monkeypatch)
    snapshot = confirmed_draft(messages, equipment, True, require_confirmation=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("direct compilation must not request review or generation")

    monkeypatch.setattr(api_client, "chat_call", forbidden)
    monkeypatch.setattr(plan_review, "_review_call", forbidden)
    plan_index = copy.deepcopy(snapshot["planIndex"])
    plan_index["exercises"][0]["placementNotes"] = "RPE 8; use the listed tempo."
    outcome = generation_pipeline.compile_plan_index(
        plan_index, equipment, output_dir=str(tmp_path),
        audit_requirements=snapshot.get("requirements", {}),
    )

    assert outcome["success"], outcome.get("error")
    package = json.loads(Path(outcome["filepath"]).read_text(encoding="utf-8"))
    assert package["workouts"]
    exercise = package["workouts"][0]["workoutComponents"][0]
    assert exercise["progressionMode"] == "OFF"
    assert exercise["requiresLoadCalibration"] is False
    assert "RPE 8; use the listed tempo." in exercise["notes"]
    work_sets = [set_item for set_item in exercise["sets"] if set_item["type"] != "RestSet"]
    assert work_sets and all(set_item["shouldReapplyHistoryToSet"] is False for set_item in work_sets)
    malformed = copy.deepcopy(package)
    malformed["workouts"][0]["workoutComponents"][0]["sets"][0]["shouldReapplyHistoryToSet"] = "false"
    with pytest.raises(ValidationError):
        Draft7Validator(JSON_SCHEMA).validate(malformed)
    report = json.loads(Path(outcome["filepath"]).with_suffix(".audit.json").read_text(encoding="utf-8"))
    assert report["issues"] == []


def test_prescribed_compile_marks_generated_general_warmup_history_policy_false(tmp_path, monkeypatch):
    from test_workout_generator_compiler_export import confirmed_recipe
    from workout_generator_pkg.planning_tools import confirmed_draft

    equipment, messages = confirmed_recipe(monkeypatch)
    snapshot = confirmed_draft(messages, equipment, True, require_confirmation=True)
    bike_id = "11111111-1111-4111-8111-111111111111"
    definition = {
        "id": "22222222-2222-4222-8222-222222222222", "name": "Timed ride",
        "exerciseType": "COUNTDOWN", "equipmentId": bike_id,
        "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_QUADRICEPS"], "secondaryMuscleGroups": ["BACK_GLUTEAL"],
        "exerciseCategory": None,
    }
    equipment["equipments"].append({"id": bike_id, "name": "Bike", "type": "CARDIO_MACHINE"})
    equipment["exerciseDefinitions"].append(definition)
    plan_index = copy.deepcopy(snapshot["planIndex"])
    plan_index["workouts"][0]["generalWarmupSeconds"] = 300
    plan_index["workouts"][0]["generalWarmupDefinition"] = definition

    outcome = generation_pipeline.compile_plan_index(
        plan_index, equipment, output_dir=str(tmp_path), audit_requirements=snapshot.get("requirements", {})
    )

    assert outcome["success"], outcome.get("error")
    package = json.loads(Path(outcome["filepath"]).read_text(encoding="utf-8"))
    warmup = next(component for component in package["workouts"][0]["workoutComponents"]
        if component.get("notes", "").startswith("General warm-up preparation"))
    timed_sets = [item for item in warmup["sets"] if item["type"] == "TimedDurationSet"]
    assert len(timed_sets) == 1
    assert timed_sets[0]["shouldReapplyHistoryToSet"] is False


def test_prescribed_text_facts_are_reused_across_library_change_and_plan_edit(tmp_path, monkeypatch):
    from workout_generator_pkg import prescribed_plan, prescribed_source

    source_file = tmp_path / "prescription.txt"
    source_file.write_text("source", encoding="utf-8")
    library = {"exerciseDefinitions": [], "equipments": [], "accessoryEquipments": []}
    plan = {"planName": "Example", "exercises": [], "workouts": []}
    extraction_calls = []
    mapping_calls = []
    compile_inputs = []

    def extract(text, spans):
        extraction_calls.append(text)
        return {"facts": {"captured": True}}

    def map_facts(extracted, current_library):
        mapping_calls.append(current_library)
        return {"planIndex": plan, "source": extracted["source"],
                "unresolved": [{"reason": "needs_operator_mapping"}]}

    monkeypatch.setattr(prescribed_source, "map_prescribed_facts", map_facts)

    def compiler(plan_index, equipment, **kwargs):
        compile_inputs.append(plan_index)
        return {"success": True, "filepath": "package.json"}

    state_dir = tmp_path / "state"
    first = prescribed_plan.run_prescribed_plan(
        source_file, library, library, state_dir=state_dir, output_dir=tmp_path,
        extract=extract, compiler=compiler, model_settings={"model": "fixture"})
    assert not first["success"] and first["unresolved"]
    active_plan = Path(first["plan_file"])
    repaired = json.loads(active_plan.read_text(encoding="utf-8"))
    repaired["planName"] = "Operator repair"
    active_plan.write_text(json.dumps(repaired), encoding="utf-8")

    changed_library = {**library, "exerciseMovements": [{"id": "movement"}]}
    class History:
        fingerprint = "changed-history"

    second = prescribed_plan.run_prescribed_plan(
        source_file, changed_library, changed_library, state_dir=state_dir, output_dir=tmp_path,
        extract=extract, compiler=compiler, model_settings={"model": "fixture"},
        training_history=History())

    assert second["success"]
    assert len(extraction_calls) == 1
    assert len(mapping_calls) == 2
    assert compile_inputs[0]["planName"] == "Operator repair"
    metrics = json.loads((state_dir / "workflow_metrics.json").read_text(encoding="utf-8"))
    assert "sourceFacts" in metrics["reusedStages"]
    assert metrics["repairAttempts"] == 1
    assert metrics["attemptCountForSource"] == 2
    assert metrics["cumulativeRepairAttemptsForSource"] == 1
    assert metrics["elapsedSinceFirstAttemptSecondsForSource"] >= metrics["cumulativeRunWallSecondsForSource"]
    assert len(list((state_dir / "attempts").glob("*.json"))) == 3  # two receipts + index


def test_structured_plan_mode_needs_no_api_key(tmp_path, monkeypatch):
    from test_workout_generator_compiler_export import confirmed_recipe
    from workout_generator_pkg import llm_config, prescribed_plan
    from workout_generator_pkg.planning_tools import confirmed_draft

    equipment, messages = confirmed_recipe(monkeypatch)
    plan_index = confirmed_draft(messages, equipment, True, require_confirmation=True)["planIndex"]
    source_file = tmp_path / "plan.json"
    source_file.write_text(json.dumps(plan_index), encoding="utf-8")
    monkeypatch.setattr(llm_config, "require_api_key", lambda *_: (_ for _ in ()).throw(AssertionError("API key requested")))
    compiled = []
    result = prescribed_plan.run_prescribed_plan(source_file, equipment, equipment,
        state_dir=tmp_path / "state", output_dir=tmp_path,
        compiler=lambda plan, _equipment, **_kwargs: compiled.append(plan) or {"success": True, "filepath": "out.json"})
    assert result["success"], result.get("error")
    assert compiled[0]["planName"] == plan_index["planName"]


def test_cli_prescribed_failure_exits_nonzero_without_opening_interactive_client(tmp_path, monkeypatch):
    import sys
    from workout_generator_pkg import interactive_shell, llm_config

    source_file = tmp_path / "invalid-plan.json"
    source_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["workout-generator", "--prescribed-plan-file", str(source_file),
        "--equipment-file", str(tmp_path / "equipment.json"), "--prescribed-state-dir", str(tmp_path / "state")])
    monkeypatch.setattr(llm_config, "require_api_key", lambda *_: (_ for _ in ()).throw(AssertionError("API key requested")))
    stub = lambda *args, **kwargs: None
    deps = SimpleNamespace(
        default_script_dir=lambda: str(tmp_path),
        load_equipment_from_file=lambda _path: {"equipments": [], "accessoryEquipments": []},
        load_conversation_record=stub, list_conversations=stub, set_active_conversation=stub,
        resolve_conversation_id=stub, has_equipment_in_messages=stub, format_equipment_for_conversation=stub,
        base_system_prompt="", get_log_dir=stub, ConversationLogger=stub,
        chat_call_with_loading=stub, generate_workout_tool={}, handle_function_call=stub,
        execute_workout_generation=stub, save_conversation=stub,
        list_available_progress=stub, delete_progress_file=stub, OpenAI=stub, httpx=stub,
    )
    try:
        interactive_shell.main(deps=deps)
    except SystemExit as error:
        assert error.code == 1
    else:
        raise AssertionError("prescribed plan validation failure must exit nonzero")
    metrics = json.loads((tmp_path / "state" / "workflow_metrics.json").read_text(encoding="utf-8"))
    assert metrics["validPackage"] is False
    assert metrics["identity"]["source"]
    assert metrics["apiCalls"] == 0


def test_prescribed_source_change_uses_new_facts_cache(tmp_path, monkeypatch):
    from workout_generator_pkg import prescribed_plan, prescribed_source

    source_file = tmp_path / "prescription.txt"
    source_file.write_text("first", encoding="utf-8")
    library = {"exerciseDefinitions": [], "equipments": [], "accessoryEquipments": []}
    extraction_calls = []

    def extract(text, spans):
        extraction_calls.append(text)
        return {"facts": {"captured": True}}

    monkeypatch.setattr(prescribed_source, "map_prescribed_facts", lambda extracted, _library: {
        "planIndex": {"planName": "Example", "exercises": [], "workouts": []},
        "source": extracted["source"], "unresolved": []})
    compiler = lambda *_args, **_kwargs: {"success": True, "filepath": "package.json"}
    prescribed_plan.run_prescribed_plan(source_file, library, library, output_dir=tmp_path,
        extract=extract, compiler=compiler, model_settings={"model": "fixture"})
    source_file.write_text("second", encoding="utf-8")
    prescribed_plan.run_prescribed_plan(source_file, library, library, output_dir=tmp_path,
        extract=extract, compiler=compiler, model_settings={"model": "fixture"})
    assert extraction_calls == ["first", "second"]


def test_unmapped_source_facts_can_be_repaired_without_reextracting(tmp_path, monkeypatch):
    from workout_generator_pkg import prescribed_plan, prescribed_source

    source_file = tmp_path / "prescription.txt"
    source_file.write_text("prescribed source", encoding="utf-8")
    library = {"exerciseDefinitions": [], "equipments": [], "accessoryEquipments": []}
    extraction_calls = []

    def extract(text, spans):
        extraction_calls.append(text)
        return {"fact": "unmapped"}

    def map_facts(extracted, _library):
        if extracted["facts"].get("operatorRepair"):
            return {"planIndex": {"planName": "Repaired", "exercises": [], "workouts": []},
                    "source": extracted["source"], "unresolved": []}
        return {"planIndex": None, "source": extracted["source"],
                "unresolved": [{"reason": "library_definition_missing"}]}

    monkeypatch.setattr(prescribed_source, "map_prescribed_facts", map_facts)
    compiled = []
    compiler = lambda plan, *_args, **_kwargs: compiled.append(plan) or {"success": True, "filepath": "out.json"}
    first = prescribed_plan.run_prescribed_plan(source_file, library, library, output_dir=tmp_path,
        extract=extract, compiler=compiler, model_settings={"model": "fixture"})
    assert not first["success"]
    source_facts = Path(first["editable_file"])
    repaired = json.loads(source_facts.read_text(encoding="utf-8"))
    repaired["extracted"]["facts"]["operatorRepair"] = True
    source_facts.write_text(json.dumps(repaired), encoding="utf-8")

    second = prescribed_plan.run_prescribed_plan(source_file, library, library, output_dir=tmp_path,
        extract=extract, compiler=compiler, model_settings={"model": "fixture"})
    assert second["success"]
    assert extraction_calls == ["prescribed source"]
    assert compiled[0]["planName"] == "Repaired"
    metrics = json.loads((Path(first["plan_file"]).parent / "workflow_metrics.json").read_text(encoding="utf-8"))
    assert metrics["repairAttempts"] == 1


def test_cold_extraction_client_includes_opencode_session_header(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from workout_generator_pkg import llm_config, prescribed_plan, prescribed_source

    endpoint = SimpleNamespace(model="fixture-model", base_url="https://opencode.ai/api", api_key="fixture-key")
    monkeypatch.setattr(llm_config, "resolve_llm_endpoint", lambda: endpoint)
    monkeypatch.setattr(llm_config, "require_api_key", lambda _endpoint: "fixture-key")
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_config, "OpenAI", Client)
    monkeypatch.setattr(prescribed_source, "chat_call", lambda *_args, **_kwargs: ("{}", None, None))
    monkeypatch.setattr(prescribed_source, "map_prescribed_facts", lambda extracted, _library: {
        "planIndex": {"planName": "Example", "exercises": [], "workouts": []},
        "source": extracted["source"], "unresolved": []})
    source_file = tmp_path / "prescription.txt"
    source_file.write_text("source line", encoding="utf-8")
    library = {"exerciseDefinitions": [], "equipments": [], "accessoryEquipments": []}
    result = prescribed_plan.run_prescribed_plan(source_file, library, library, output_dir=tmp_path,
        compiler=lambda *_args, **_kwargs: {"success": True, "filepath": "out.json"})
    assert result["success"], result.get("error")
    assert captured["default_headers"]["x-opencode-session"]
    assert captured["base_url"] == endpoint.base_url


def test_library_hydration_supplies_only_valid_optional_metadata_defaults():
    from workout_generator_pkg.domain_ops import _materialize_exercise_definition
    from workout_generator_pkg.plan_contract import hydrate_plan_index_from_exercise_library

    definitions = [
        {"id": "weight-def", "name": "Barbell Press", "exerciseType": "WEIGHT",
         "equipmentId": "barbell", "exerciseCategory": "STRENGTH", "muscleGroups": ["chest"]},
        {"id": "bodyweight-def", "name": "Air Squat", "exerciseType": "BODY_WEIGHT",
         "exerciseCategory": "STRENGTH", "muscleGroups": ["quadriceps"]},
    ]
    entries = [
        {"id": "EXERCISE_0", "libraryDefinitionId": "weight-def", "numWorkSets": 1,
         "generateWarmUpSets": False, "intraSetRestInSeconds": None, "minReps": 8, "maxReps": 8,
         "restBetweenSetsSeconds": 60, "requiresLoadCalibration": False,
         "targetSetPrescriptions": [{"workSetIndex": 0, "reps": 8, "weight": 20}]},
        {"id": "EXERCISE_1", "libraryDefinitionId": "bodyweight-def", "numWorkSets": 1,
         "generateWarmUpSets": False, "intraSetRestInSeconds": None, "minReps": 8, "maxReps": 8,
         "restBetweenSetsSeconds": 60, "requiresLoadCalibration": False},
    ]
    plan = {"exercises": entries, "workouts": []}

    hydrate_plan_index_from_exercise_library(plan, definitions)
    materialized = [_materialize_exercise_definition(entry) for entry in entries]

    assert entries[0]["bodyWeightPercentage"] is None
    assert entries[0]["requiredAccessoryEquipmentIds"] == []
    assert entries[0]["secondaryMuscleGroups"] == []
    assert entries[1]["equipmentId"] is None
    assert entries[1]["bodyWeightPercentage"] is None
    assert materialized[0]["sets"][0]["weight"] == 20
    assert materialized[1]["equipmentId"] is None


def test_history_reapply_override_requires_boolean_type():
    from workout_generator_pkg.domain_ops import _materialize_exercise_definition

    with pytest.raises(ValueError, match="must be a boolean"):
        _materialize_exercise_definition({}, should_reapply_history_to_set="false")


@pytest.mark.parametrize("exercise_type,specific_fields", [
    ("WEIGHT", {"minReps": 8, "maxReps": 8,
        "targetSetPrescriptions": [{"workSetIndex": 0, "reps": 8, "weight": 20}]}),
    ("BODY_WEIGHT", {"minReps": 8, "maxReps": 8,
        "targetSetPrescriptions": [{"workSetIndex": 0, "reps": 8, "additionalWeight": 0}]}),
    ("COUNTDOWN", {"timedSetPrescriptions": [{"timeInMillis": 30000, "autoStart": True, "autoStop": True}]}),
    ("COUNTUP", {"timedSetPrescriptions": [{"timeInMillis": 30000, "autoStart": True, "autoStop": True}]}),
    ("RUNNING", {"runningPrescription": {"environment": "OUTDOOR", "targetType": "DISTANCE", "targetValue": 500}}),
    ("WEIGHT", {"targetDistanceMeters": 20}),
])
def test_direct_materializer_flags_every_work_set_type_and_keeps_default_omission(exercise_type, specific_fields):
    from workout_generator_pkg.domain_ops import _materialize_exercise_definition

    entry = {
        "id": "EXERCISE_0", "libraryDefinitionId": "definition",
        "name": "Prescribed movement", "exerciseType": exercise_type,
        "equipmentId": None, "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [], "muscleGroups": ["quadriceps"],
        "secondaryMuscleGroups": [], "generateWarmUpSets": False,
        "intraSetRestInSeconds": None, "exerciseCategory": "STRENGTH",
        "numWorkSets": 1, "restBetweenSetsSeconds": 60,
        **specific_fields,
    }

    prescribed = _materialize_exercise_definition(entry, should_reapply_history_to_set=False)
    assert prescribed["sets"]
    assert all(item["shouldReapplyHistoryToSet"] is False
               for item in prescribed["sets"] if item["type"] != "RestSet")
    reviewed_default = _materialize_exercise_definition(entry)
    assert all("shouldReapplyHistoryToSet" not in item
               for item in reviewed_default["sets"] if item["type"] != "RestSet")
