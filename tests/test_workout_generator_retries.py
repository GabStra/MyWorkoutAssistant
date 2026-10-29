import threading
import json
import copy
from dataclasses import replace

import pytest

import workout_generator_pkg.cli as cli
import workout_generator_pkg.generation_pipeline as pipeline
from workout_generator_pkg.deps import resolve_pipeline_deps
from workout_generator_pkg.generation_pipeline import execute_workout_generation
from workout_generator_pkg.plan_contract import ContractValidationError


def test_unscoped_plan_index_repair_is_rejected_before_a_model_call(monkeypatch):
    requests = []

    def response(_client, messages, *_args, **_kwargs):
        requests.append(messages[-1]["content"])
        return json.dumps({"equipments": [], "accessoryEquipments": [], "exercises": [], "workouts": []})

    monkeypatch.setattr(cli, "json_call_chat_max_with_loading", response)
    feedback = "Missing selected exercise: Bench (libraryDefinitionId='definition-1')."
    with pytest.raises(cli.SchemaRepairError, match='does not authorize a full-index repair'):
        cli.generate_index(
            None, "confirmed preview", use_reasoner=False,
            provided_equipment={
                "equipments": [], "accessoryEquipments": [],
                "exerciseDefinitions": [{"id": "definition-1", "name": "Bench"}],
                "selectedExerciseDefinitionIds": ["definition-1"],
            },
            contract_error_context=feedback,
        )
    assert not requests


def test_pipeline_returns_unscoped_contract_failure_to_planning_without_rewriting(monkeypatch, tmp_path):
    calls = []
    plan = {'planName': 'Draft', 'equipments': [], 'accessoryEquipments': [], 'exercises': [], 'workouts': []}
    def generate(*args, **kwargs):
        calls.append(1)
        return plan
    def reject(*args, **kwargs):
        raise ContractValidationError('The submitted contract is invalid.')
    monkeypatch.setattr(pipeline, 'validate_plan_index_contract', reject)
    deps = replace(resolve_pipeline_deps(), test_connection=lambda *a, **k: (True, None),
        hash_conversation=lambda *a: 'hash', summarize_conversation=lambda *a: 'summary', generate_index=generate,
        save_generation_progress=lambda *a, **k: ('progress.json', 0))
    result = execute_workout_generation(None, [{'role': 'user', 'content': 'CONFIRM GENERATE'}],
        script_dir=str(tmp_path), force_use_reasoner=False, deps=deps)
    assert calls == [1] and not result['success'] and result['requires_plan_revision']
    assert result['programming_audit']['errors'][0]['code'] == 'plan_contract_requires_revision'


def test_approved_calibration_flags_use_full_original_library_evidence(monkeypatch, tmp_path):
    from workout_generator_pkg.planning_tools import library_fingerprint

    gear_id = '11111111-1111-4111-8111-111111111111'
    selected_id = 'selected-definition'
    equipment = {
        'equipments': [{'id': gear_id, 'name': 'Barbell', 'type': 'BARBELL'}],
        'accessoryEquipments': [],
        'exerciseDefinitions': [
            {'id': selected_id, 'name': 'Barbell Press', 'exerciseType': 'WEIGHT',
             'equipmentId': gear_id, 'requiredAccessoryEquipmentIds': [],
             'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': [],
             'exerciseCategory': 'MODERATE_COMPOUND', 'movementRef': 'horizontal_push'},
            {'id': 'unselected-definition', 'name': 'Unused', 'exerciseType': 'WEIGHT',
             'equipmentId': gear_id, 'requiredAccessoryEquipmentIds': [],
             'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': [],
             'exerciseCategory': 'ISOLATION', 'movementRef': 'horizontal_push'},
        ],
    }
    history_fingerprint = 'history-fingerprint'
    evidence = {'historyFingerprint': history_fingerprint,
        'libraryFingerprint': library_fingerprint(equipment),
        'exercises': [{'definitionId': selected_id, 'status': 'comparable_records',
            'sessions': [{'performances': [{'record': {'setType': 'WeightSetData',
                'actualReps': 8, 'loadKg': 20}}]}]}]}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'evidence', 'type': 'function',
            'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': 'evidence', 'content': json.dumps(evidence)},
        {'role': 'assistant', 'tool_calls': [{'id': 'draft', 'type': 'function',
            'function': {'name': 'audit_workout_plan'}}]},
    ]
    snapshot = {
        'planIndex': {'planName': 'Draft', 'equipments': [], 'accessoryEquipments': [],
            'auditTargets': {}, 'exercises': [{'id': 'EXERCISE_0', 'libraryDefinitionId': selected_id,
                'numWorkSets': 2, 'generateWarmUpSets': False, 'maxReps': 10,
                'requiresLoadCalibration': False}], 'workouts': []},
        'submittedDraft': {}, 'historyFingerprint': history_fingerprint, 'preview': 'Approved draft',
    }
    monkeypatch.setattr(pipeline, 'confirmed_draft', lambda *_args, **_kwargs: copy.deepcopy(snapshot))
    monkeypatch.setattr(pipeline, 'require_current_review', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, 'validate_plan_index_contract', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, 'validate_audit_targets', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, 'plan_audit_package', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline, 'audit_workout_package',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('reached programming audit')))
    deps = replace(resolve_pipeline_deps(), test_connection=lambda *_args, **_kwargs: (True, None),
        hash_conversation=lambda *_: 'hash', save_generation_progress=lambda *_args, **_kwargs: ('progress.json', 0))

    result = execute_workout_generation(None, messages, provided_equipment=equipment,
        script_dir=str(tmp_path), deps=deps, force_use_reasoner=False)

    assert 'reached programming audit' in result['error']
    assert 'calibration flags do not match' not in result['error']


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


def test_fix_set_errors_converts_distance_set_to_goal_encoding() -> None:
    from workout_generator_pkg.domain_ops import fix_set_errors

    fixed = fix_set_errors([{"id": "s1", "type": "DistanceSet", "distance": 500}])

    assert fixed == [
        {
            "id": "s1",
            "type": "EnduranceSet",
            "timeInMillis": 0,
            "autoStart": True,
            "autoStop": False,
            "targetDistanceMeters": 500.0,
        }
    ]


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
