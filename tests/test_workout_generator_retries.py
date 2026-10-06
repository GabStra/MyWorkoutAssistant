import threading
from dataclasses import replace

import pytest

import workout_generator_pkg.cli as cli
import workout_generator_pkg.generation_pipeline as pipeline
from workout_generator_pkg.deps import resolve_pipeline_deps
from workout_generator_pkg.generation_pipeline import execute_workout_generation
from workout_generator_pkg.plan_contract import ContractValidationError


def test_exercise_emitter_honors_single_attempt_repair_budget(monkeypatch) -> None:
    calls = []

    def invalid_response(_client, messages, *_args, **_kwargs):
        calls.append(messages)
        return "not-json"

    monkeypatch.setattr(cli, "json_call_chat_max_with_loading", invalid_response)

    with pytest.raises(ValueError, match="failed after 1 auto-heal attempts"):
        cli.emit_exercise_definition(
            "EXERCISE_0",
            client=None,
            context_summary="summary",
            plan_index={
                "exercises": [
                    {
                        "id": "EXERCISE_0",
                        "name": "Test Exercise",
                        "exerciseType": "WEIGHT",
                    }
                ]
            },
            equipment_subset=[],
            use_reasoner=False,
            max_attempts=1,
        )

    assert len(calls) == 1


def test_pipeline_recovers_failed_exercises_and_batches_contract_repairs(
    monkeypatch, tmp_path
) -> None:
    exercise_ids = ["EXERCISE_0", "EXERCISE_1"]
    workout_ids = ["WORKOUT_0", "WORKOUT_1"]
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_0", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": exercise_id,
                "name": f"Exercise {index}",
                "exerciseType": "WEIGHT",
                "equipmentId": "EQUIPMENT_0",
                "requiredAccessoryEquipmentIds": [],
            }
            for index, exercise_id in enumerate(exercise_ids)
        ],
        "workouts": [
            {
                "id": workout_id,
                "name": f"Workout {index}",
                "exerciseIds": [exercise_ids[index]],
            }
            for index, workout_id in enumerate(workout_ids)
        ],
    }
    progress = {
        "session_id": "resume-session",
        "current_step": 2,
        "step_data": {
            "step_0_context_summary": "summary",
            "step_0_structured_generation_facts": "",
            "step_1_plan_index": plan_index,
            "step_1_provided_equipment": None,
            "step_2_equipment_items": {"EQUIPMENT_0": plan_index["equipments"][0]},
            "step_2_accessory_items": {},
        },
        "timing": {},
        "id_manager_state": {},
        "conversation_hash": "test-hash",
        "custom_prompt": "test prompt",
        "use_reasoner_for_emitting": False,
    }

    exercise_repair_gate = threading.Barrier(2)
    workout_repair_gate = threading.Barrier(2)
    active_lock = threading.Lock()
    active_repairs = {"exercise": 0, "workout": 0}
    max_active_repairs = {"exercise": 0, "workout": 0}
    exercise_attempts = []
    workout_attempts = []
    validation_save_calls = []

    def emit_exercise(exercise_id, *, max_attempts=4, contract_error_context=None, **_kwargs):
        if contract_error_context is None:
            raise ValueError("initial exercise emission failed")
        exercise_attempts.append((exercise_id, max_attempts, contract_error_context))
        with active_lock:
            active_repairs["exercise"] += 1
            max_active_repairs["exercise"] = max(
                max_active_repairs["exercise"], active_repairs["exercise"]
            )
        try:
            exercise_repair_gate.wait(timeout=5)
            return ({"id": exercise_id}, None)
        finally:
            with active_lock:
                active_repairs["exercise"] -= 1

    def emit_workout(workout_id, *, contract_error_context=None, **_kwargs):
        if contract_error_context is None:
            return ({"id": workout_id}, None)
        workout_attempts.append((workout_id, contract_error_context))
        with active_lock:
            active_repairs["workout"] += 1
            max_active_repairs["workout"] = max(
                max_active_repairs["workout"], active_repairs["workout"]
            )
        try:
            workout_repair_gate.wait(timeout=5)
            return ({"id": workout_id}, None)
        finally:
            with active_lock:
                active_repairs["workout"] -= 1

    exercise_validation_calls = 0

    def validate_exercises(_plan_index, definitions):
        nonlocal exercise_validation_calls
        exercise_validation_calls += 1
        if set(definitions) != set(exercise_ids):
            raise ContractValidationError(
                "Missing emitted exercise definitions:\n"
                + "\n".join(
                    f"Missing emitted exercise definition for '{exercise_id}'."
                    for exercise_id in exercise_ids
                    if exercise_id not in definitions
                )
            )

    workout_validation_calls = 0

    def validate_workouts(_plan_index, structures, _definitions):
        nonlocal workout_validation_calls
        workout_validation_calls += 1
        if workout_validation_calls == 1:
            raise ContractValidationError(
                "Invalid workouts "
                + " and ".join(
                    f"for workout 'Workout {index}' ({workout_id})"
                    for index, workout_id in enumerate(workout_ids)
                )
            )
        assert set(structures) == set(workout_ids)

    def save_progress(_session_id, step_number, *_args, **_kwargs):
        validation_save_calls.append(step_number)
        return "progress.json", 0.0

    def stop_after_repairs(*_args, **_kwargs):
        raise RuntimeError("stop after verifying repair stages")

    monkeypatch.setattr(pipeline, "hydrate_plan_index_from_exercise_library", lambda *_: None)
    monkeypatch.setattr(pipeline, "validate_plan_index_contract", lambda *_: None)
    monkeypatch.setattr(pipeline, "validate_exercise_definitions_contract", validate_exercises)
    monkeypatch.setattr(pipeline, "validate_workout_structures_contract", validate_workouts)

    deps = replace(
        resolve_pipeline_deps(),
        hash_conversation=lambda _messages: "test-hash",
        load_generation_progress=lambda *_args: progress,
        save_generation_progress=save_progress,
        emit_exercise_definition=emit_exercise,
        emit_workout_structure=emit_workout,
        assemble_placeholder_workout_store=stop_after_repairs,
        default_script_dir=lambda: str(tmp_path),
    )

    result = execute_workout_generation(
        client=None,
        messages=[],
        resume_session_id="resume-session",
        script_dir=str(tmp_path),
        deps=deps,
    )

    assert not result["success"]
    assert result["error"].endswith("stop after verifying repair stages")
    assert exercise_validation_calls == 2
    assert workout_validation_calls == 2
    assert {exercise_id for exercise_id, _, _ in exercise_attempts} == set(exercise_ids)
    assert all(max_attempts == 1 for _, max_attempts, _ in exercise_attempts)
    assert max_active_repairs["exercise"] == 2
    assert {workout_id for workout_id, _ in workout_attempts} == set(workout_ids)
    assert max_active_repairs["workout"] == 2
    assert validation_save_calls == [3, 4]
