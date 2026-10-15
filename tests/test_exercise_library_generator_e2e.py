from __future__ import annotations

import json
import threading
import time

import pytest
from workout_generator_pkg.domain_ops import build_exercise_definition_id

from exercise_library_generator_pkg.generator import (
    _confirm_capability_suggestions,
    _call_inventory,
    _completed_futures,
    _apply_requirement_verification_patch,
    _capabilities_for_equipment_ids,
    _emit_definition,
    _emit_definition_batch,
    _apply_capability_file,
    _add_confirmation_only_capability_questions,
    _format_equipment_context,
    _generate_capability_suggestions,
    _normalize_and_filter_candidates,
    _normalize_candidate_semantics,
    _normalize_matrix_group_requirements,
    _repair_definition_muscles_with_json_patch,
    _review_definition_batch,
    _review_definition_batch_resilient,
    _review_equipment_context,
    _run_global_semantic_consistency_review,
    _reviews_by_id,
    _save_library_atomic,
    _structured_definition_errors,
    _validate_candidate,
    _validate_definition,
    generate_exercise_library,
    review_library_feasibility,
    review_library_checkpoint,
    review_library_muscle_semantics,
)


def _definition_response(messages, build_definition):
    user_content = messages[-1]["content"]
    if "Candidates:\n" in user_content:
        rows = json.loads(user_content.split("Candidates:\n", 1)[1])
        return json.dumps(
            {
                "definitions": [
                    {
                        "candidateId": row["candidateId"],
                        "definition": build_definition(row["candidate"]),
                    }
                    for row in rows
                ]
            }
        )
    candidate = json.loads(user_content.split("Candidate:\n", 1)[1])
    return json.dumps(build_definition(candidate))


def _generator_review_response(_client, messages, _loading_message, show_loading=False):
    assert show_loading is False
    system_prompt = messages[0]["content"]
    review_input = json.loads(messages[-1]["content"])
    if "Judge whether each exercise is physically executable" in system_prompt:
        return json.dumps(
            {
                "reviews": [
                    {
                        "reference": definition["reference"],
                        "decision": "KEEP",
                        "missingCapabilities": [],
                        "reason": "Declared equipment is sufficient.",
                    }
                    for definition in review_input["definitions"]
                ]
            }
        )
    return json.dumps(
        {
            "reviews": [
                {
                    "reference": definition["reference"],
                    "muscleGroups": definition["currentMuscleGroups"] or ["FRONT_CHEST"],
                    "secondaryMuscleGroups": definition["currentSecondaryMuscleGroups"],
                }
                for definition in review_input["definitions"]
            ]
        }
    )


def test_library_reviews_use_twenty_definition_batches_and_keep_feasibility_consensus() -> None:
    equipment = {
        "equipments": [{"id": "dumbbells", "type": "DUMBBELLS", "name": "Dumbbells"}],
        "accessoryEquipments": [],
    }
    definitions = [
        {
            "id": f"definition-{index}",
            "name": f"Dumbbell Exercise {index}",
            "exerciseType": "WEIGHT",
            "equipmentId": "dumbbells",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "muscleGroups": ["FRONT_CHEST"],
            "secondaryMuscleGroups": [],
        }
        for index in range(21)
    ]
    checkpoint = {**equipment, "exerciseDefinitions": definitions}
    muscle_batch_sizes = []

    def muscle_review_call(client, messages, loading_message, show_loading=False):
        review_input = json.loads(messages[-1]["content"])
        muscle_batch_sizes.append(len(review_input["definitions"]))
        return _generator_review_response(client, messages, loading_message, show_loading)

    reviewed = review_library_muscle_semantics(
        None, checkpoint, review_call=muscle_review_call, max_workers=1
    )

    assert muscle_batch_sizes == [20, 1]
    assert len(reviewed["exerciseDefinitions"]) == len(definitions)

    feasibility_batch_sizes = []

    def feasibility_review_call(client, messages, loading_message, show_loading=False):
        review_input = json.loads(messages[-1]["content"])
        feasibility_batch_sizes.append(len(review_input["definitions"]))
        return _generator_review_response(client, messages, loading_message, show_loading)

    feasible = review_library_feasibility(
        None, checkpoint, review_call=feasibility_review_call, max_workers=1
    )

    assert feasibility_batch_sizes == [20, 20, 1, 1]
    assert len(feasible["exerciseDefinitions"]) == len(definitions)


@pytest.mark.parametrize("discard_feasibility", [False, True])
def test_generator_overlaps_independent_reviews_within_worker_budget(
    discard_feasibility: bool,
) -> None:
    equipment = {
        "equipments": [{"id": "dumbbells", "type": "DUMBBELLS", "name": "Dumbbells"}],
        "accessoryEquipments": [],
    }
    candidate = {
        "name": "Dumbbell Row",
        "exerciseType": "WEIGHT",
        "equipmentId": "dumbbells",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
    }
    review_gate = threading.Barrier(2)
    review_lock = threading.Lock()
    waiting_review_types = set()
    active_reviews = 0
    maximum_active_reviews = 0

    def fake_review_call(_client, messages, _loading_message, show_loading=False):
        nonlocal active_reviews, maximum_active_reviews
        system_prompt = messages[0]["content"]
        review_type = (
            "feasibility"
            if "Judge whether each exercise is physically executable" in system_prompt
            else "muscle"
        )
        with review_lock:
            active_reviews += 1
            maximum_active_reviews = max(maximum_active_reviews, active_reviews)
            should_wait = review_type not in waiting_review_types
            waiting_review_types.add(review_type)
        try:
            if should_wait:
                review_gate.wait(timeout=5)
            review_input = json.loads(messages[-1]["content"])
            if review_type == "feasibility":
                if discard_feasibility:
                    return json.dumps(
                        {
                            "reviews": [
                                {
                                    "reference": definition["reference"],
                                    "decision": "DISCARD",
                                    "missingCapabilities": ["RACKED_BAR_SUPPORT"],
                                    "reason": "The test review marks this definition infeasible.",
                                }
                                for definition in review_input["definitions"]
                            ]
                        }
                    )
                return _generator_review_response(
                    _client, messages, _loading_message, show_loading
                )
            return json.dumps(
                {
                    "reviews": [
                        {
                            "reference": definition["reference"],
                            "muscleGroups": ["BACK_UPPER_BACK"],
                            "secondaryMuscleGroups": ["FRONT_BICEPS"],
                        }
                        for definition in review_input["definitions"]
                    ]
                }
            )
        finally:
            with review_lock:
                active_reviews -= 1

    checkpoints = []
    generation_arguments = {
        "client": None,
        "equipment": equipment,
        "audit_passes": 0,
        "max_workers": 2,
        "scope_inventory_by_equipment": False,
        "inventory_call": lambda *_args, **_kwargs: json.dumps(
            {"exercises": [candidate]}
        ),
        "reasoner_call": fake_review_call,
        "chat_call": lambda _client, messages, _loading_message, show_loading=False: _definition_response(
            messages,
            lambda exercise: {
                **exercise,
                "instructions": "Pull the dumbbell toward the torso.",
                "instructionEquipmentIds": ["dumbbells"],
                "muscleGroups": ["FRONT_CHEST"],
                "secondaryMuscleGroups": [],
                "exerciseCategory": "MODERATE_COMPOUND",
            },
        ),
        "review_checkpoint_callback": checkpoints.append,
    }
    if discard_feasibility:
        with pytest.raises(ValueError, match="Review retained 0/1 definitions"):
            generate_exercise_library(**generation_arguments)
    else:
        generated = generate_exercise_library(**generation_arguments)

    assert waiting_review_types == {"muscle", "feasibility"}
    assert maximum_active_reviews == 2
    if discard_feasibility:
        assert checkpoints[-1]["reviewStatus"] == "FAILED"
        assert checkpoints[-1]["exerciseDefinitions"][0]["muscleGroups"] == [
            "BACK_UPPER_BACK"
        ]
    else:
        assert generated["exerciseDefinitions"][0]["muscleGroups"] == [
            "BACK_UPPER_BACK"
        ]
        assert generated["exerciseDefinitions"][0]["secondaryMuscleGroups"] == [
            "FRONT_BICEPS"
        ]
        # The muscle/feasibility merge rewrites content; the content-derived ID
        # must be re-derived or it goes stale.
        merged = generated["exerciseDefinitions"][0]
        assert merged["id"] == build_exercise_definition_id(merged)
        assert any(
            snapshot["exerciseDefinitions"][0]["muscleGroups"] == ["BACK_UPPER_BACK"]
            for snapshot in checkpoints
        )


def test_generator_emits_definitions_only_with_exact_equipment_and_deterministic_ids(tmp_path) -> None:
    equipment = {
        "equipments": [
            {"id": "equipment-dumbbell", "type": "DUMBBELLS", "name": "Adjustable dumbbells"},
            {"id": "equipment-barbell", "type": "BARBELL", "name": "Barbell"},
        ],
        "accessoryEquipments": [
            {"id": "accessory-bench", "type": "ACCESSORY", "name": "Bench"},
            {
                "id": "accessory-rack",
                "type": "ACCESSORY",
                "name": "Barbell Rack",
                "capabilities": ["RACKED_BAR_SUPPORT"],
            },
        ],
    }
    initial_candidates = {
        "exercises": [
            {
                "name": "Barbell Bench Press",
                "exerciseType": "WEIGHT",
                "equipmentId": "equipment-barbell",
                "bodyWeightPercentage": None,
                "requiredAccessoryEquipmentIds": ["accessory-bench", "accessory-rack"],
            },
            {
                "name": "Dumbbell Bench Press",
                "exerciseType": "WEIGHT",
                "equipmentId": "equipment-dumbbell",
                "bodyWeightPercentage": None,
                "requiredAccessoryEquipmentIds": ["accessory-bench"],
            },
        ]
    }
    audit_candidates = {
        "exercises": [
            {
                "name": "Push-Up",
                "exerciseType": "BODY_WEIGHT",
                "equipmentId": None,
                "bodyWeightPercentage": 100.0,
                "requiredAccessoryEquipmentIds": [],
            }
        ]
    }
    inventory_responses = iter([initial_candidates, audit_candidates])
    definition_batch_sizes = []

    def fake_inventory_call(_client, _messages, _loading_message):
        return json.dumps(next(inventory_responses))

    def fake_definition_call(_client, messages, _loading_message, show_loading=False):
        assert show_loading is False
        if "Candidates:\n" in messages[-1]["content"]:
            definition_batch_sizes.append(
                len(json.loads(messages[-1]["content"].split("Candidates:\n", 1)[1]))
            )
        return _definition_response(
            messages,
            lambda candidate: {
                **candidate,
                "instructions": f"Perform {candidate['name']} with controlled technique.",
                "instructionEquipmentIds": [
                    item
                    for item in [
                        candidate.get("equipmentId"),
                        *candidate.get("requiredAccessoryEquipmentIds", []),
                    ]
                    if item is not None
                ],
                "muscleGroups": ["FRONT_CHEST"],
                "secondaryMuscleGroups": ["FRONT_TRICEPS"],
                "exerciseCategory": "MODERATE_COMPOUND",
            },
        )

    generated = generate_exercise_library(
        client=None,
        equipment=equipment,
        request="Build a comprehensive strength exercise library.",
        audit_passes=1,
        max_workers=2,
        scope_inventory_by_equipment=False,
        inventory_call=fake_inventory_call,
        reasoner_call=_generator_review_response,
        chat_call=fake_definition_call,
    )

    assert generated["schemaVersion"] == 2
    assert generated["format"] == "myworkoutassistant.exercise-library"
    assert generated["equipments"] == equipment["equipments"]
    assert generated["accessoryEquipments"] == equipment["accessoryEquipments"]
    assert "workouts" not in generated
    assert "workoutPlans" not in generated
    assert len(generated["exerciseDefinitions"]) == 3
    assert generated["generationFailures"] == []
    assert definition_batch_sizes == [3]

    definitions = generated["exerciseDefinitions"]
    assert len({definition["id"] for definition in definitions}) == 3
    assert {
        definition["equipmentId"]
        for definition in definitions
        if definition["name"] in {"Barbell Bench Press", "Dumbbell Bench Press"}
    } == {"equipment-barbell", "equipment-dumbbell"}
    assert all(
        not ({"sets", "reps", "weight", "progressionMode", "placementNotes"} & definition.keys())
        for definition in definitions
    )

    destination = _save_library_atomic(generated, tmp_path / "library.json")
    persisted = json.loads(destination.read_text(encoding="utf-8"))
    assert persisted == generated

    repeat_inventory_responses = iter([initial_candidates, audit_candidates])

    def repeat_inventory_call(_client, _messages, _loading_message):
        return json.dumps(next(repeat_inventory_responses))

    repeated = generate_exercise_library(
        client=None,
        equipment=equipment,
        audit_passes=1,
        max_workers=2,
        scope_inventory_by_equipment=False,
        inventory_call=repeat_inventory_call,
        reasoner_call=_generator_review_response,
        chat_call=fake_definition_call,
    )
    assert [item["id"] for item in repeated["exerciseDefinitions"]] == [
        item["id"] for item in definitions
    ]
    assert definition_batch_sizes == [3, 3]


def test_definition_emitter_batches_candidates_with_only_linked_equipment_context() -> None:
    equipment = {
        "equipments": [
            {"id": "barbell-id", "type": "BARBELL", "name": "Barbell"},
            {"id": "dumbbell-id", "type": "DUMBBELL", "name": "Single Dumbbell"},
        ],
        "accessoryEquipments": [
            {"id": "bench-id", "type": "ACCESSORY", "name": "Bench"},
        ],
    }
    candidates = [
        {
            "name": "Barbell Bench Press",
            "exerciseType": "WEIGHT",
            "equipmentId": "barbell-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": ["bench-id"],
            "exerciseCategory": "HEAVY_COMPOUND",
        },
        {
            "name": "Single Dumbbell Curl",
            "exerciseType": "WEIGHT",
            "equipmentId": "dumbbell-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "exerciseCategory": "ISOLATION",
        },
    ]
    calls = []

    def fake_call(_client, messages, _loading_message, show_loading=False):
        calls.append(messages)
        rows = json.loads(messages[-1]["content"].split("Candidates:\n", 1)[1])
        assert "barbell-id" in rows[0]["equipmentContext"]
        assert "bench-id" in rows[0]["equipmentContext"]
        assert "dumbbell-id" not in rows[0]["equipmentContext"]
        assert "dumbbell-id" in rows[1]["equipmentContext"]
        assert "barbell-id" not in rows[1]["equipmentContext"]
        return _definition_response(
            messages,
            lambda candidate: {
                **candidate,
                "muscleGroups": ["FRONT_CHEST"]
                if "Bench Press" in candidate["name"]
                else ["FRONT_BICEPS"],
                "secondaryMuscleGroups": [],
                "exerciseCategory": candidate["exerciseCategory"],
            },
        )

    emitted, errors = _emit_definition_batch(
        client=None,
        candidates=candidates,
        equipment=equipment,
        use_reasoner=False,
        call_reasoner=fake_call,
        call_chat=fake_call,
    )

    assert len(calls) == 1
    assert errors == []
    assert [definition["name"] for definition in emitted if definition] == [
        "Barbell Bench Press",
        "Single Dumbbell Curl",
    ]


def test_definition_emitter_falls_back_to_individual_calls_for_invalid_batch() -> None:
    equipment = {
        "equipments": [{"id": "barbell-id", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [],
    }
    candidates = [
        {
            "name": name,
            "exerciseType": "WEIGHT",
            "equipmentId": "barbell-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "exerciseCategory": "HEAVY_COMPOUND",
        }
        for name in ("Barbell Bench Press", "Barbell Row")
    ]
    calls = []

    def fake_call(_client, messages, _loading_message, show_loading=False):
        calls.append(messages)
        if "Candidates:\n" in messages[-1]["content"]:
            return json.dumps({"definitions": []})
        return _definition_response(
            messages,
            lambda candidate: {
                **candidate,
                "muscleGroups": ["FRONT_CHEST"],
                "secondaryMuscleGroups": [],
                "exerciseCategory": "HEAVY_COMPOUND",
            },
        )

    emitted, errors = _emit_definition_batch(
        client=None,
        candidates=candidates,
        equipment=equipment,
        use_reasoner=False,
        call_reasoner=fake_call,
        call_chat=fake_call,
    )

    assert len(calls) == 3
    assert errors == []
    assert all(definition is not None for definition in emitted)


def test_definition_emitter_retries_only_the_invalid_candidate_from_a_batch() -> None:
    candidates = [
        {
            "name": name,
            "exerciseType": "WEIGHT",
            "equipmentId": "barbell-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "exerciseCategory": "HEAVY_COMPOUND",
        }
        for name in ("Barbell Bench Press", "Barbell Row")
    ]
    equipment = {
        "equipments": [{"id": "barbell-id", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [],
    }
    calls = []

    def build_definition(candidate, *, valid):
        return {
            **candidate,
            "muscleGroups": ["FRONT_CHEST"] if valid else [],
            "secondaryMuscleGroups": [],
            "exerciseCategory": "HEAVY_COMPOUND",
        }

    def fake_call(_client, messages, _loading_message, show_loading=False):
        calls.append(messages)
        if "Candidates:\n" in messages[-1]["content"]:
            rows = json.loads(messages[-1]["content"].split("Candidates:\n", 1)[1])
            return json.dumps(
                {
                    "definitions": [
                        {
                            "candidateId": row["candidateId"],
                            "definition": build_definition(
                                row["candidate"],
                                valid=row["candidate"]["name"] == "Barbell Row",
                            ),
                        }
                        for row in rows
                    ]
                }
            )
        candidate = json.loads(messages[-1]["content"].split("Candidate:\n", 1)[1])
        assert candidate["name"] == "Barbell Bench Press"
        return json.dumps(build_definition(candidate, valid=True))

    emitted, errors = _emit_definition_batch(
        client=None,
        candidates=candidates,
        equipment=equipment,
        use_reasoner=False,
        call_reasoner=fake_call,
        call_chat=fake_call,
    )

    assert len(calls) == 2
    assert errors == []
    assert [definition["name"] for definition in emitted if definition] == [
        "Barbell Bench Press",
        "Barbell Row",
    ]


def test_definition_parser_accepts_wrapped_legacy_emitter_field_names() -> None:
    candidate = {
        "name": "Barbell Back Squat",
        "exerciseType": "WEIGHT",
        "equipmentId": "barbell-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
    }
    parsed = _validate_definition(
        {
            "exerciseDefinition": {
                **candidate,
                "notes": ["Brace before descending. " * 15, "Drive upward under control. " * 15],
                "primaryMuscleGroups": ["FRONT_QUADRICEPS", "BACK_GLUTEAL"],
                "exerciseCategory": "HEAVY_COMPOUND",
            }
        },
        candidate,
    )

    assert parsed["muscleGroups"] == ["FRONT_QUADRICEPS", "BACK_GLUTEAL"]
    assert parsed["secondaryMuscleGroups"] == []
    assert "notes" not in parsed
    assert "instructions" not in parsed


def test_definition_parser_normalizes_model_metadata_to_canonical_enums() -> None:
    candidate = {
        "name": "Barbell Bench Press",
        "exerciseType": "WEIGHT",
        "equipmentId": "barbell-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": ["bench-id"],
        "exerciseCategory": "HEAVY_COMPOUND",
    }

    parsed = _validate_definition(
        {
            **candidate,
            "instructions": "Lower the bar under control and press it upward.",
            "muscleGroups": ["CHEST", "TRICEPS"],
            "secondaryMuscleGroups": ["SHOULDERS", "CHEST"],
            "exerciseCategory": "PUSH",
        },
        candidate,
    )

    assert parsed["muscleGroups"] == ["FRONT_CHEST", "FRONT_TRICEPS"]
    assert parsed["secondaryMuscleGroups"] == ["FRONT_DELTOIDS"]
    assert parsed["exerciseCategory"] == "HEAVY_COMPOUND"


def test_timed_definition_always_has_null_category() -> None:
    candidate = {
        "name": "Stationary Bike Ride",
        "exerciseType": "COUNTDOWN",
        "equipmentId": None,
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": ["bike-id"],
    }

    parsed = _validate_definition(
        {
            **candidate,
            "instructions": "Pedal at the prescribed effort.",
            "muscleGroups": ["QUADS"],
            "secondaryMuscleGroups": [],
            "exerciseCategory": "CARDIO",
        },
        candidate,
    )

    assert parsed["exerciseCategory"] is None
    assert parsed["muscleGroups"] == ["FRONT_QUADRICEPS"]


def test_definition_emitter_repairs_invalid_muscles_with_scoped_json_patch() -> None:
    candidate = {
        "name": "Cable Pull-Through",
        "exerciseType": "WEIGHT",
        "equipmentId": "cable-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "exerciseCategory": "MODERATE_COMPOUND",
    }
    calls = []

    def fake_call(_client, messages, _loading_message, show_loading=False):
        calls.append(messages)
        if len(calls) == 1:
            return json.dumps(
                {
                    **candidate,
                    "instructions": "Hinge at the hips and extend under control.",
                    "muscleGroups": ["POSTERIOR_CHAIN"],
                    "secondaryMuscleGroups": ["HAMSTRINGS"],
                    "exerciseCategory": "HIP_HINGE",
                }
            )
        return json.dumps(
                {
                    "patch": [
                        {
                            "op": "replace",
                            "path": "/muscleGroups",
                            "value": ["BACK_GLUTEAL"],
                        }
                    ]
                }
        )

    emitted = _emit_definition(
        client=None,
        candidate=candidate,
        use_reasoner=False,
        call_reasoner=fake_call,
        call_chat=fake_call,
    )

    assert len(calls) == 2
    assert emitted["muscleGroups"] == ["BACK_GLUTEAL"]
    assert emitted["secondaryMuscleGroups"] == ["BACK_HAMSTRING"]
    assert "instructions" not in emitted


def test_muscle_json_patch_cannot_change_definition_identity() -> None:
    definition = {
        "name": "Cable Pull-Through",
        "exerciseType": "WEIGHT",
        "equipmentId": "cable-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "exerciseCategory": "HEAVY_COMPOUND",
        "instructions": "Use controlled technique.",
        "muscleGroups": ["POSTERIOR_CHAIN"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "HIP_HINGE",
    }

    def illegal_patch(_client, _messages, _loading_message, show_loading=False):
        return json.dumps(
            {"patch": [{"op": "replace", "path": "/name", "value": "Deadlift"}]}
        )

    with pytest.raises(ValueError, match="outside allowed error paths"):
        _repair_definition_muscles_with_json_patch(
            None,
            definition,
            ValueError("invalid muscle group"),
            illegal_patch,
        )


def test_definition_emitter_repairs_candidate_identity_without_regeneration() -> None:
    candidate = {
        "name": "Barbell Row",
        "exerciseType": "WEIGHT",
        "equipmentId": "barbell-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "exerciseCategory": "HEAVY_COMPOUND",
    }
    responses = iter(
        [
            {
                **candidate,
                "equipmentId": "invented-id",
                "instructions": "",
                "muscleGroups": ["BACK_UPPER_BACK"],
                "secondaryMuscleGroups": ["FRONT_BICEPS"],
                "exerciseCategory": "PULL",
            },
            {
                "patch": [
                    {
                        "op": "replace",
                        "path": "/equipmentId",
                        "value": "barbell-id",
                    }
                ]
            },
        ]
    )
    call_count = 0

    def fake_call(_client, _messages, _loading_message, show_loading=False):
        nonlocal call_count
        call_count += 1
        return json.dumps(next(responses))

    emitted = _emit_definition(
        client=None,
        candidate=candidate,
        use_reasoner=False,
        call_reasoner=fake_call,
        call_chat=fake_call,
    )

    assert call_count == 2
    assert emitted["equipmentId"] == "barbell-id"
    assert emitted["muscleGroups"] == ["BACK_UPPER_BACK"]
    assert "instructions" not in emitted


def test_inventory_rejects_hallucinated_equipment_without_losing_valid_candidates() -> None:
    from exercise_library_generator_pkg.generator import _parse_inventory

    equipment = {
        "equipments": [{"id": "barbell-id", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [
            {"id": "rack-id", "type": "ACCESSORY", "name": "Barbell Rack"}
        ],
    }
    content = json.dumps(
        {
            "exercises": [
                {
                    "name": "Barbell Row",
                    "exerciseType": "WEIGHT",
                    "equipmentId": "barbell-id",
                    "bodyWeightPercentage": None,
                    "requiredAccessoryEquipmentIds": [],
                },
                {
                    "name": "Spin Bike Ride",
                    "exerciseType": "COUNTUP",
                    "equipmentId": "invented-bike-id",
                    "bodyWeightPercentage": None,
                    "requiredAccessoryEquipmentIds": [],
                },
            ]
        }
    )

    parsed = _parse_inventory(content, equipment, allowed_equipment_ids={"barbell-id"})

    assert [candidate["name"] for candidate in parsed] == ["Barbell Row"]


def test_inventory_repairs_field_errors_without_inventing_name_requirements() -> None:
    from exercise_library_generator_pkg.generator import _parse_inventory

    equipment = {
        "equipments": [
            {"id": "bike-id", "type": "CARDIO_MACHINE", "name": "Spin Bike"},
            {"id": "vest-id", "type": "WEIGHTVEST", "name": "Weight Vest"},
        ],
        "accessoryEquipments": [
            {"id": "bench-id", "type": "ACCESSORY", "name": "Adjustable Bench"}
        ],
    }
    repair_calls: list[object] = []

    def fake_repair(_client, messages, _label, **_kwargs):
        repair_calls.append(messages)
        return json.dumps(
            {
                "patches": [
                    {
                        "index": 0,
                        "patch": [
                            {"op": "replace", "path": "/bodyWeightPercentage", "value": 70}
                        ],
                    },
                    {
                        "index": 1,
                        "patch": [
                            {
                                "op": "replace",
                                "path": "/requiredAccessoryEquipmentIds",
                                "value": [],
                            },
                            {
                                "op": "replace",
                                "path": "/implementUsage",
                                "value": [{"equipmentId": "bike-id", "quantity": 1}],
                            },
                            {
                                "op": "replace",
                                "path": "/requiredCapabilities",
                                "value": ["USE_EQUIPMENT:bike-id"],
                            },
                        ],
                    },
                ]
            }
        )

    parsed = _parse_inventory(
        json.dumps(
            {
                "exercises": [
                    {
                        "name": "Weighted Push-Up",
                        "exerciseType": "BODY_WEIGHT",
                        "equipmentId": None,
                        "bodyWeightPercentage": None,
                        "requiredAccessoryEquipmentIds": [],
                    },
                    {
                        "name": "Seated Cycling with Weight Vest",
                        "exerciseType": "COUNTUP",
                        "equipmentId": "bike-id",
                        "bodyWeightPercentage": None,
                        "requiredAccessoryEquipmentIds": ["vest-id"],
                    },
                    {
                        "name": "Decline Push-Up",
                        "exerciseType": "BODY_WEIGHT",
                        "equipmentId": None,
                        "bodyWeightPercentage": 65.0,
                        "requiredAccessoryEquipmentIds": ["bench-id"],
                    },
                ]
            }
        ),
        equipment,
        repair_client=object(),
        repair_caller=fake_repair,
    )

    assert {candidate["name"] for candidate in parsed} == {
        "Weighted Push-Up",
        "Seated Cycling with Weight Vest",
        "Decline Push-Up",
    }
    by_name = {candidate["name"]: candidate for candidate in parsed}
    assert by_name["Weighted Push-Up"]["bodyWeightPercentage"] == 70
    assert by_name["Seated Cycling with Weight Vest"]["requiredAccessoryEquipmentIds"] == ["vest-id"]
    assert len(repair_calls) == 1
    repair_names = [
        item["candidate"]["name"]
        for item in json.loads(repair_calls[0][1]["content"])["candidates"]
    ]
    assert repair_names == ["Weighted Push-Up"]


def test_accessory_batch_excludes_equipment_free_bodyweight_exercises() -> None:
    from exercise_library_generator_pkg.generator import _parse_inventory

    equipment = {
        "equipments": [],
        "accessoryEquipments": [
            {"id": "pullup-bar-id", "type": "ACCESSORY", "name": "Pull-up bar"}
        ],
    }
    content = json.dumps(
        {
            "exercises": [
                {
                    "name": "Push-Up",
                    "exerciseType": "BODY_WEIGHT",
                    "equipmentId": None,
                    "bodyWeightPercentage": 100.0,
                    "requiredAccessoryEquipmentIds": [],
                },
                {
                    "name": "Pull-Up",
                    "exerciseType": "BODY_WEIGHT",
                    "equipmentId": None,
                    "bodyWeightPercentage": 100.0,
                    "requiredAccessoryEquipmentIds": ["pullup-bar-id"],
                },
            ]
        }
    )

    parsed = _parse_inventory(
        content,
        equipment,
        allowed_equipment_ids=set(),
        require_any_accessory=True,
    )

    assert [candidate["name"] for candidate in parsed] == ["Pull-Up"]


def test_scoped_inventory_batches_use_worker_concurrency() -> None:
    equipment = {
        "equipments": [
            {"id": "barbell-id", "type": "BARBELL", "name": "Barbell"},
            {"id": "cable-id", "type": "CABLE", "name": "Cable"},
        ],
        "accessoryEquipments": [],
    }
    lock = threading.Lock()
    active_calls = 0
    maximum_active_calls = 0

    def fake_inventory_call(_client, messages, _loading_message, show_loading=False):
        nonlocal active_calls, maximum_active_calls
        assert show_loading is False
        with lock:
            active_calls += 1
            maximum_active_calls = max(maximum_active_calls, active_calls)
        time.sleep(0.05)
        with lock:
            active_calls -= 1
        prompt = messages[-1]["content"]
        if "barbell-id" in prompt and "exact equipmentId barbell-id" in prompt:
            assert "cable-id" not in prompt
            candidate = {
                "name": "Barbell Row",
                "exerciseType": "WEIGHT",
                "equipmentId": "barbell-id",
                "bodyWeightPercentage": None,
                "requiredAccessoryEquipmentIds": [],
            }
            return json.dumps({"exercises": [candidate]})
        if "cable-id" in prompt and "exact equipmentId cable-id" in prompt:
            assert "barbell-id" not in prompt
            candidate = {
                "name": "Cable Row",
                "exerciseType": "WEIGHT",
                "equipmentId": "cable-id",
                "bodyWeightPercentage": None,
                "requiredAccessoryEquipmentIds": [],
            }
            return json.dumps({"exercises": [candidate]})
        return json.dumps({"exercises": []})

    def fake_definition_call(_client, messages, _loading_message, show_loading=False):
        return _definition_response(
            messages,
            lambda candidate: {
                **candidate,
                "instructions": "Use controlled technique.",
                "instructionEquipmentIds": [candidate["equipmentId"]],
                "muscleGroups": ["BACK_UPPER_BACK"],
                "secondaryMuscleGroups": [],
                "exerciseCategory": "MODERATE_COMPOUND",
            },
        )

    generated = generate_exercise_library(
        client=None,
        equipment=equipment,
        audit_passes=0,
        max_workers=3,
        inventory_call=fake_inventory_call,
        reasoner_call=_generator_review_response,
        chat_call=fake_definition_call,
    )

    assert maximum_active_calls >= 2
    assert {item["name"] for item in generated["exerciseDefinitions"]} == {
        "Barbell Row",
        "Cable Row",
    }


def test_inventory_logs_scope_and_uses_timed_example_for_cardio(capsys):
    equipment = {
        "equipments": [{"id": "bike", "type": "CARDIO_MACHINE", "name": "Spin Bike"}],
        "accessoryEquipments": [],
    }

    def inventory_call(_client, messages, _loading_message, show_loading=False):
        assert "\"exerciseType\": \"COUNTUP\"" in messages[-1]["content"]
        assert "\"executionMode\": \"OPEN_DURATION\"" in messages[-1]["content"]
        return '{"exercises": []}'

    _call_inventory(None, equipment, "", allowed_equipment_ids={"bike"},
                    call_json=inventory_call, show_loading=False, log_prefix="Inventory batch 7/7 (Spin Bike)")
    output = capsys.readouterr().out
    assert "Inventory batch 7/7 (Spin Bike) / Enumerating exercises: request started" in output
    assert "received 0 valid distinct candidate(s)" in output
    assert "\r" not in output


def test_future_wait_reports_progress_without_cancelling_work(monkeypatch, capsys):
    from concurrent.futures import Future
    from exercise_library_generator_pkg import generator

    future = Future()
    waits = []

    def wait_once(pending, **kwargs):
        waits.append(kwargs)
        if len(waits) == 1:
            return set(), pending
        future.set_result("complete")
        return pending, set()

    monkeypatch.setattr(generator, "wait", wait_once)
    assert list(_completed_futures([future], "Inventory")) == [future]
    assert future.result() == "complete"
    assert "Inventory: waiting; 0/1 complete, 1 remaining" in capsys.readouterr().out
    assert waits[0]["timeout"] == 30.0


def test_generator_rejects_a_severely_incomplete_library() -> None:
    candidates = [
        {
            "name": name,
            "exerciseType": "WEIGHT",
            "equipmentId": "barbell-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
        }
        for name in ("Barbell Deadlift", "Barbell Curl")
    ]
    equipment = {
        "equipments": [{"id": "barbell-id", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [
            {"id": "rack-id", "type": "ACCESSORY", "name": "Barbell Rack"}
        ],
    }

    def fake_inventory_call(_client, _messages, _loading_message):
        return json.dumps({"exercises": candidates})

    def failing_definition_call(_client, messages, _loading_message, show_loading=False):
        return _definition_response(
            messages,
            lambda candidate: {
                **candidate,
                "instructions": "Use controlled technique.",
                "instructionEquipmentIds": [candidate["equipmentId"]],
                "muscleGroups": [],
                "secondaryMuscleGroups": [],
                "exerciseCategory": "STRENGTH",
            },
        )

    with pytest.raises(ValueError, match="No incomplete library was saved"):
        generate_exercise_library(
            client=None,
            equipment=equipment,
            audit_passes=0,
            max_workers=1,
            scope_inventory_by_equipment=False,
            inventory_call=fake_inventory_call,
            chat_call=failing_definition_call,
        )


def test_candidate_semantics_are_derived_from_structured_modes() -> None:
    equipment = {
        "equipments": [{"id": "vest-id", "type": "WEIGHTVEST", "name": "Weight Vest"}],
        "accessoryEquipments": [],
    }
    base = {
        "exerciseType": "WEIGHT",
        "equipmentId": "vest-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
    }

    pull_up = _normalize_candidate_semantics(
        {
            **base,
            "name": "Movement A",
            "executionMode": "REPETITIONS",
            "resistanceMode": "BODY_WEIGHT_PLUS_LOAD",
            "bodyWeightPercentage": 85.0,
        },
        equipment,
    )
    carry = _normalize_candidate_semantics(
        {**base, "name": "Movement B", "executionMode": "OPEN_DURATION"},
        equipment,
    )
    plank = _normalize_candidate_semantics(
        {**base, "name": "Movement C", "executionMode": "TARGET_DURATION"},
        equipment,
    )

    assert (pull_up["exerciseType"], pull_up["bodyWeightPercentage"]) == (
        "BODY_WEIGHT",
        85.0,
    )
    assert carry["exerciseType"] == "COUNTUP"
    assert plank["exerciseType"] == "COUNTDOWN"


def test_semantic_filter_uses_movement_fingerprints_and_disambiguates_names() -> None:
    equipment = {
        "equipments": [
            {"id": "cable-id", "type": "PLATELOADEDCABLE", "name": "Cable"},
            {"id": "single-id", "type": "DUMBBELL", "name": "Dumbbell"},
            {"id": "pair-id", "type": "DUMBBELLS", "name": "Dumbbells"},
        ],
        "accessoryEquipments": [],
    }
    candidates = [
        *[
        {
            "name": "Cable Movement",
            "exerciseType": "WEIGHT",
            "equipmentId": "cable-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "executionMode": "REPETITIONS",
            "resistanceMode": "EXTERNAL_LOAD",
            "movementKey": "cable-movement",
        },
        {
            "name": "Cable Movement Alias",
            "exerciseType": "WEIGHT",
            "equipmentId": "cable-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "executionMode": "REPETITIONS",
            "resistanceMode": "EXTERNAL_LOAD",
            "movementKey": "cable-movement",
        },
        ],
        *[
            {
                "name": "Loaded Movement",
                "exerciseType": "WEIGHT",
                "equipmentId": equipment_id,
                "bodyWeightPercentage": None,
                "requiredAccessoryEquipmentIds": [],
                "executionMode": "REPETITIONS",
                "resistanceMode": "EXTERNAL_LOAD",
                "movementKey": "loaded-movement",
            }
            for equipment_id in ("single-id", "pair-id")
        ],
    ]

    retained, filtered = _normalize_and_filter_candidates(candidates, equipment)

    assert {(item["name"], item["equipmentId"]) for item in retained} == {
        ("Cable Movement", "cable-id"),
        ("Loaded Movement (Single Dumbbell)", "single-id"),
        ("Loaded Movement (Dumbbell Pair)", "pair-id"),
    }
    assert len(filtered) == 1


def test_independent_semantic_review_discards_infeasible_and_patches_metadata() -> None:
    equipment = {
        "equipments": [
            {"id": "cable-id", "type": "PLATELOADEDCABLE", "name": "Cable"},
            {"id": "dumbbell-id", "type": "DUMBBELL", "name": "Dumbbell"},
        ],
        "accessoryEquipments": [],
    }
    infeasible = {
        "id": "infeasible-id",
        "name": "Cable Leg Curl",
        "exerciseType": "WEIGHT",
        "equipmentId": "cable-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["BACK_HAMSTRING"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    }
    repairable = {
        "id": "repairable-id",
        "name": "Goblet Squat",
        "exerciseType": "WEIGHT",
        "equipmentId": "dumbbell-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_QUADRICEPS"],
        "secondaryMuscleGroups": ["BACK_GLUTEAL"],
        "exerciseCategory": "MODERATE_COMPOUND",
    }

    def fake_review(_client, _messages, loading_message, show_loading=False):
        if loading_message in (
            "Verifying physical requirements",
            "Adjudicating proposed infeasibility",
        ):
            return json.dumps({"patch": []})
        return json.dumps(
            {
                "reviews": [
                    {
                        "id": "infeasible-id",
                        "requiredEquipmentIds": ["cable-id"],
                        "requirementClauses": [{"anyOf": ["ANKLE_STRAP_ATTACHMENT"]}],
                        "missingEquipment": [],
                        "issues": ["Requires an ankle cuff that is not supplied"],
                        "patch": [],
                    },
                    {
                        "id": "repairable-id",
                        "requiredEquipmentIds": ["dumbbell-id"],
                        "requirementClauses": [],
                        "missingEquipment": [],
                        "issues": ["Secondary muscle is not materially trained"],
                        "patch": [
                            {
                                "op": "replace",
                                "path": "/secondaryMuscleGroups",
                                "value": [],
                            }
                        ],
                    },
                ]
            }
        )

    kept, discarded = _review_definition_batch(
        None,
        [infeasible, repairable],
        equipment,
        fake_review,
    )

    assert [item["name"] for item in kept] == ["Goblet Squat"]
    assert kept[0]["exerciseCategory"] == "MODERATE_COMPOUND"
    assert kept[0]["secondaryMuscleGroups"] == []
    assert kept[0]["id"] == build_exercise_definition_id(kept[0])
    assert len(discarded) == 1
    assert discarded[0].startswith("Cable Leg Curl: Requires an ankle cuff that is not supplied")
    assert "ANKLE_STRAP_ATTACHMENT" in discarded[0]


def test_semantic_review_retries_only_its_batch_after_invalid_muscle_patch() -> None:
    equipment = {
        "equipments": [{"id": "cable-id", "type": "PLATELOADEDCABLE", "name": "Cable"}],
        "accessoryEquipments": [],
    }
    definition = {
        "id": "definition-id",
        "name": "Cable Row",
        "instructions": "Pull the cable toward the torso under control.",
        "exerciseType": "WEIGHT",
        "equipmentId": "cable-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["BACK_UPPER_BACK"],
        "secondaryMuscleGroups": ["FRONT_BICEPS"],
        "exerciseCategory": "MODERATE_COMPOUND",
    }
    call_count = 0

    def fake_review(_client, _messages, loading_message, show_loading=False):
        nonlocal call_count
        call_count += 1
        if loading_message == "Verifying physical requirements":
            return json.dumps({"patch": []})
        if loading_message.startswith("Repairing"):
            return json.dumps({
                "patch": [{
                    "op": "replace",
                    "path": "/reviews/0/patch/0/value",
                    "value": ["BACK_UPPER_BACK"],
                }]
                })
            if loading_message == "Adjudicating proposed infeasibility":
                return json.dumps({"patch": []})
        return json.dumps(
            {
                "reviews": [
                    {
                        "id": "definition-id",
                        "requiredEquipmentIds": ["cable-id"],
                        "requirementClauses": [],
                        "missingEquipment": [],
                        "issues": [],
                        "patch": [
                            {
                                "op": "replace",
                                "path": "/muscleGroups",
                                "value": ["POSTERIOR_CHAIN"],
                            }
                        ],
                    }
                ]
            }
        )

    kept, discarded = _review_definition_batch(
        None,
        [definition],
        equipment,
        fake_review,
    )

    assert call_count == 3
    assert kept[0]["muscleGroups"] == ["BACK_UPPER_BACK"]
    assert discarded == []


def test_requirement_verifier_patches_before_feasibility_decision() -> None:
    equipment = {
        "equipments": [{"id": "bar-id", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [],
    }
    definition = {
        "id": "definition-id",
        "name": "Arbitrary Loaded Movement",
        "instructions": "Begin with the barbell across your upper back and perform the movement.",
        "exerciseType": "WEIGHT",
        "equipmentId": "bar-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_DELTOIDS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "MODERATE_COMPOUND",
    }
    call_count = 0

    def fake_review(_client, _messages, loading_message, show_loading=False):
        nonlocal call_count
        call_count += 1
        assert any("json" in message["content"].casefold() for message in _messages)
        if loading_message == "Verifying physical requirements":
            return json.dumps({
                "patch": [{
                    "op": "replace",
                    "path": "/reviews/0/requirementClauses",
                    "value": [{"anyOf": ["RACKED_BAR_SUPPORT", "HUMAN_HANDOFF_SUPPORT"]}],
                }]
            })
        if loading_message == "Adjudicating proposed infeasibility":
            return json.dumps({"patch": []})
        clauses = []
        review = {
            "id": "definition-id",
            "requiredEquipmentIds": ["bar-id"],
            "requirementClauses": clauses,
            "missingEquipment": [],
        }
        if loading_message == "Reviewing exercise semantics":
            review.update({"issues": [], "patch": []})
        return json.dumps({"reviews": [review]})

    kept, discarded = _review_definition_batch(None, [definition], equipment, fake_review)

    assert call_count == 3
    assert kept == []
    assert len(discarded) == 1
    assert "RACKED_BAR_SUPPORT" in discarded[0]


@pytest.mark.parametrize(
    ("name", "instructions", "unsupported_capability"),
    [
        (
            "Loaded Hinge",
            "Hold the barbell at arm's length and hinge at the hips.",
            "ADJUSTABLE_WEIGHT",
        ),
        (
            "Suspended Row",
            "Hold the rings and row your chest toward your hands.",
            "OVER_IMPLEMENT_TRANSITION_CLEARANCE",
        ),
    ],
)
def test_unsupported_non_execution_or_unevidenced_capability_does_not_discard(
    name: str, instructions: str, unsupported_capability: str
) -> None:
    equipment = {
        "equipments": [{"id": "bar-id", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [],
    }
    definition = {
        "id": "definition-id",
        "name": name,
        "instructions": instructions,
        "exerciseType": "WEIGHT",
        "equipmentId": "bar-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["BACK_UPPER_BACK"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "MODERATE_COMPOUND",
    }

    def fake_review(_client, _messages, loading_message, show_loading=False):
        if loading_message == "Verifying physical requirements":
            return json.dumps({"patch": []})
        if loading_message == "Adjudicating proposed infeasibility":
            return json.dumps({
                "patch": [{
                    "op": "replace",
                    "path": "/reviews/0/requirementClauses",
                    "value": [],
                }]
            })
        return json.dumps({
            "reviews": [{
                "id": "definition-id",
                "requiredEquipmentIds": ["bar-id"],
                "requirementClauses": [{"anyOf": [unsupported_capability]}],
                "missingEquipment": [],
                "issues": [],
                "patch": [],
            }]
        })

    kept, discarded = _review_definition_batch(None, [definition], equipment, fake_review)

    assert len(kept) == 1
    assert discarded == []


def test_semantic_requirement_error_is_repaired_with_scoped_json_patch() -> None:
    equipment = {
        "equipments": [{"id": "bar-id", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [],
    }
    definition = {
        "id": "definition-id",
        "name": "Generated Movement",
        "instructions": "Perform under control.",
        "exerciseType": "WEIGHT",
        "equipmentId": "bar-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_DELTOIDS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "MODERATE_COMPOUND",
    }
    calls = []

    def fake_review(_client, _messages, loading_message, show_loading=False):
        calls.append(loading_message)
        if loading_message.startswith("Repairing"):
            return json.dumps({
                "patch": [{
                    "op": "replace",
                    "path": "/reviews/0/requirementClauses",
                    "value": [],
                }]
            })
        if loading_message == "Verifying physical requirements":
            return json.dumps({"patch": []})
        capabilities = ["NOT_A_CAPABILITY"]
        return json.dumps({
            "reviews": [{
                "id": "definition-id",
                "requiredEquipmentIds": ["bar-id"],
                "requirementClauses": [{"anyOf": capabilities}] if capabilities else [],
                "missingEquipment": [],
                "issues": [],
                "patch": [],
            }]
        })

    kept, discarded = _review_definition_batch(None, [definition], equipment, fake_review)

    assert calls == [
        "Reviewing exercise semantics",
        "Repairing semantic review JSON",
        "Verifying physical requirements",
    ]
    assert len(kept) == 1
    assert discarded == []


def test_requirement_parser_recovers_wrapper_and_equipment_id_in_capability_clause() -> None:
    definition = {
        "id": "definition-id",
        "equipmentId": "equipment-id",
        "requiredAccessoryEquipmentIds": [],
    }
    payload = {
        "requirements": [
            {
                "id": "definition-id",
                "requiredEquipmentIds": [],
                "requirementClauses": [{"anyOf": ["equipment-id"]}],
                "missingEquipment": [],
            }
        ]
    }

    parsed = _reviews_by_id(payload, [definition], {"equipment-id"})

    assert parsed["definition-id"]["requiredEquipmentIds"] == ["equipment-id"]
    assert parsed["definition-id"]["requirementClauses"] == []


def test_review_uses_semantic_equipment_references_and_restores_real_ids() -> None:
    equipment = {
        "equipments": [{"id": "uuid-bar", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [
            {"id": "uuid-rack", "type": "ACCESSORY", "name": "Barbell Rack"}
        ],
    }
    context, references, reverse_references = _review_equipment_context(equipment)

    assert "uuid-bar" not in context
    assert "uuid-rack" not in context
    assert references["PRIMARY_BARBELL_1"] == "uuid-bar"
    assert references["ACCESSORY_BARBELL_RACK_1"] == "uuid-rack"
    assert reverse_references["uuid-bar"] == "PRIMARY_BARBELL_1"

    payload = {
        "reviews": [{
            "id": "definition-id",
            "requiredEquipmentIds": ["PRIMARY_BARBELL_1"],
            "requirementClauses": [],
            "missingEquipment": ["ACCESSORY_BARBELL_RACK_1", "ROPE_ATTACHMENT"],
        }]
    }
    parsed = _reviews_by_id(
        payload,
        [{"id": "definition-id"}],
        {"uuid-bar", "uuid-rack"},
        references,
    )

    assert parsed["definition-id"]["requiredEquipmentIds"] == ["uuid-bar", "uuid-rack"]
    assert parsed["definition-id"]["requirementClauses"] == [
        {"anyOf": ["ROPE_ATTACHMENT"]}
    ]
    assert parsed["definition-id"]["missingEquipment"] == []


def test_requirement_parser_reports_malformed_objects_without_type_error() -> None:
    payload = {
        "reviews": [{
            "id": "definition-id",
            "requiredEquipmentIds": [{"unexpected": "object"}],
            "requirementClauses": [],
            "missingEquipment": [],
        }]
    }

    with pytest.raises(ValueError, match="Invalid structured physical requirements"):
        _reviews_by_id(payload, [{"id": "definition-id"}], {"equipment-id"})


def test_verification_patch_accepts_definition_id_as_review_selector() -> None:
    payload = {
        "reviews": [{
            "id": "definition-id",
            "requiredEquipmentIds": ["equipment-id"],
            "requirementClauses": [],
            "missingEquipment": [],
            "issues": [],
            "patch": [],
        }]
    }
    patched = _apply_requirement_verification_patch(
        payload,
        {
            "patch": [{
                "op": "replace",
                "path": "/reviews/definition-id/requirementClauses",
                "value": [{"anyOf": ["BENCH"]}],
            }]
        },
        [{"id": "definition-id"}],
        {"equipment-id"},
        {},
    )

    assert patched["reviews"][0]["requirementClauses"] == [{"anyOf": ["BENCH"]}]


def test_global_consistency_audit_can_reverse_keep_and_discard_decisions() -> None:
    definitions = [
        {
            "id": definition_id,
            "name": name,
            "instructions": instructions,
            "exerciseType": "BODY_WEIGHT",
            "equipmentId": None,
            "bodyWeightPercentage": 100,
            "requiredAccessoryEquipmentIds": [],
            "muscleGroups": ["BACK_UPPER_BACK"],
            "secondaryMuscleGroups": [],
            "exerciseCategory": "MODERATE_COMPOUND",
        }
        for definition_id, name, instructions in (
            ("keep-id", "Initially Kept", "Perform the first movement."),
            ("discard-id", "Initially Discarded", "Perform the second movement."),
        )
    ]

    def fake_call(_client, _messages, loading_message, show_loading=False):
        if loading_message == "Verifying global requirement matrix":
            return json.dumps({"patch": []})
        assert loading_message.startswith("Global matrix batch ")
        return json.dumps({
            "groups": [
                {
                    "setup": "First setup requires unavailable support",
                    "memberIds": ["keep-id"],
                    "requirementClauses": [{"anyOf": ["RACKED_BAR_SUPPORT"]}],
                    "missingEquipment": [],
                    "rationale": "Missing mandatory support",
                },
                {
                    "setup": "Second setup requires no additional support",
                    "memberIds": ["discard-id"],
                    "requirementClauses": [],
                    "missingEquipment": [],
                    "rationale": "No support is mandatory",
                },
            ]
        })

    kept, discarded = _run_global_semantic_consistency_review(
        None,
        definitions,
        [definitions[0]],
        ["Initially Discarded: missing optional support"],
        {"equipments": [], "accessoryEquipments": []},
        fake_call,
    )

    assert [definition["id"] for definition in kept] == ["discard-id"]
    assert discarded == [
        "Initially Kept: Missing mandatory support; unsatisfied capability alternatives "
        "[['RACKED_BAR_SUPPORT']]"
    ]


def test_global_consistency_matrix_rejects_incomplete_definition_coverage() -> None:
    definitions = [
        {
            "id": definition_id,
            "name": definition_id,
            "instructions": "Perform under control.",
            "exerciseType": "BODY_WEIGHT",
            "equipmentId": None,
            "bodyWeightPercentage": 100,
            "requiredAccessoryEquipmentIds": [],
            "muscleGroups": ["FRONT_ABS"],
            "secondaryMuscleGroups": [],
            "exerciseCategory": "MODERATE_COMPOUND",
        }
        for definition_id in ("first-id", "second-id")
    ]

    def incomplete_call(_client, _messages, _loading_message, show_loading=False):
        return json.dumps({
            "groups": [{
                "setup": "Only one definition",
                "memberIds": ["first-id"],
                "requirementClauses": [],
                "missingEquipment": [],
                "rationale": "Incomplete on purpose",
            }]
        })

    with pytest.raises(ValueError, match="cover every definition exactly once"):
        _run_global_semantic_consistency_review(
            None,
            definitions,
            definitions,
            [],
            {"equipments": [], "accessoryEquipments": []},
            incomplete_call,
        )


def test_matrix_normalizes_capabilities_misplaced_as_missing_equipment() -> None:
    normalized = _normalize_matrix_group_requirements({
        "setup": "Cable handle setup",
        "memberIds": ["definition-id"],
        "requirementClauses": [],
        "missingEquipment": [
            "SINGLE_HANDLE_ATTACHMENT",
            "Cable single handle attachment",
            "second cable station",
            "portable power rack",
        ],
        "rationale": "A handle and second station are required.",
    })

    assert normalized["requirementClauses"] == [
        {"anyOf": ["SINGLE_HANDLE_ATTACHMENT"]},
        {"anyOf": ["SECOND_CABLE_STATION"]},
    ]
    assert normalized["missingEquipment"] == ["portable power rack"]


def test_failed_review_batch_adaptively_splits_before_stopping() -> None:
    equipment = {
        "equipments": [{"id": "cable-id", "type": "PLATELOADEDCABLE", "name": "Cable"}],
        "accessoryEquipments": [],
    }

    def definition(definition_id: str, name: str) -> dict:
        return {
            "id": definition_id,
            "name": name,
            "instructions": "Pull the cable under control.",
            "exerciseType": "WEIGHT",
            "equipmentId": "cable-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "muscleGroups": ["BACK_UPPER_BACK"],
            "secondaryMuscleGroups": ["FRONT_BICEPS"],
            "exerciseCategory": "MODERATE_COMPOUND",
        }

    first = definition("first-id", "First Cable Row")
    second = definition("second-id", "Second Cable Row")
    call_count = 0

    def fake_review(_client, _messages, _loading_message, show_loading=False):
        nonlocal call_count
        call_count += 1
        if call_count in {4, 5}:
            return json.dumps(
                {
                    "reviews": [
                        {
                            "id": "first-id",
                            "requiredEquipmentIds": ["cable-id"],
                            "requirementClauses": [],
                            "missingEquipment": [],
                            "issues": [],
                            "patch": [],
                        }
                    ]
                }
            )
        return json.dumps({"reviews": []})

    with pytest.raises(ValueError, match="Could not produce a valid semantic review"):
        _review_definition_batch_resilient(
            None,
            [first, second],
            equipment,
            fake_review,
        )

    assert call_count == 12


def test_inventory_contract_enforces_capabilities_quantity_and_trait_category() -> None:
    from exercise_library_generator_pkg.generator import _parse_inventory

    equipment = {
        "equipments": [
            {
                "id": "pair-id",
                "type": "DUMBBELLS",
                "name": "Dumbbells",
                "capabilities": ["PAIR_LOAD"],
            }
        ],
        "accessoryEquipments": [],
    }

    def candidate(name: str, quantity: int, capabilities: list[str]) -> dict:
        return {
            "name": name,
            "exerciseType": "WEIGHT",
            "equipmentId": "pair-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "executionMode": "REPETITIONS",
            "resistanceMode": "EXTERNAL_LOAD",
            "movementKey": name.casefold(),
            "exerciseCategory": "HEAVY_COMPOUND",
            "requiredCapabilities": capabilities,
            "implementUsage": [{"equipmentId": "pair-id", "quantity": quantity}],
            "jointDemand": "MULTI_JOINT",
            "loadingDemand": "MODERATE",
            "warmupDemand": "MODERATE",
        }

    parsed = _parse_inventory(
        json.dumps(
            {
                "exercises": [
                    candidate("Valid Pair Movement", 2, ["USE_EQUIPMENT:pair-id", "PAIR_LOAD"]),
                    candidate("Wrong Quantity", 1, ["USE_EQUIPMENT:pair-id", "PAIR_LOAD"]),
                    candidate("Missing Rack", 2, ["USE_EQUIPMENT:pair-id", "BARBELL_RACK"]),
                ]
            }
        ),
        equipment,
        allowed_equipment_ids={"pair-id"},
    )

    assert [item["name"] for item in parsed] == ["Valid Pair Movement"]
    assert parsed[0]["exerciseCategory"] == "MODERATE_COMPOUND"


def test_capability_sidecar_merges_only_known_equipment_ids(tmp_path) -> None:
    equipment = {
        "equipments": [{
            "id": "cable-id",
            "type": "PLATELOADEDCABLE",
            "name": "Cable",
            "capabilities": ["SUPPORTS_PLATES"],
        }],
        "accessoryEquipments": [{"id": "bench-id", "type": "ACCESSORY", "name": "Bench"}],
    }
    capability_file = tmp_path / "capabilities.json"
    capability_file.write_text(
        json.dumps(
            {
                "capabilitiesByEquipmentId": {
                    "cable-id": ["HIGH_PULLEY", "LOW_PULLEY"],
                    "bench-id": ["FLAT_BENCH"],
                }
            }
        ),
        encoding="utf-8",
    )

    merged = _apply_capability_file(equipment, str(capability_file))

    assert merged["equipments"][0]["capabilities"] == [
        "SUPPORTS_PLATES", "HIGH_PULLEY", "LOW_PULLEY"
    ]
    assert merged["accessoryEquipments"][0]["capabilities"] == ["FLAT_BENCH"]
    assert equipment["equipments"][0]["capabilities"] == ["SUPPORTS_PLATES"]


def test_generated_capabilities_are_repaired_validated_and_confirmed() -> None:
    equipment = {
        "equipments": [{"id": "cable-id", "type": "CABLE", "name": "Cable stack"}],
        "accessoryEquipments": [{"id": "bench-id", "type": "ACCESSORY", "name": "Bench"}],
    }
    responses = iter(
        [
            json.dumps({
                "suggestions": [{
                    "equipmentId": "invented-id",
                    "capability": "HIGH_PULLEY",
                    "reason": "Invented",
                    "confidence": "HIGH",
                }]
            }),
            json.dumps({
                "suggestions": [
                    {
                        "equipmentId": "cable-id",
                        "capability": "HIGH_PULLEY",
                        "reason": "The exported name identifies a cable stack.",
                        "confidence": "MEDIUM",
                    },
                    {
                        "equipmentId": "bench-id",
                        "capability": "ADJUSTABLE_BENCH",
                        "reason": "The generic name alone does not prove adjustability.",
                        "confidence": "LOW",
                    },
                ]
            }),
        ]
    )
    calls: list[list[dict[str, str]]] = []

    def fake_call(_client, messages, _loading_message):
        calls.append(messages.copy())
        return next(responses)

    suggestions = _generate_capability_suggestions(None, equipment, call_json=fake_call)
    answers = iter(["yes", "no"])
    displayed: list[str] = []
    confirmed = _confirm_capability_suggestions(
        equipment,
        suggestions,
        input_fn=lambda _prompt: next(answers),
        output_fn=displayed.append,
    )

    assert len(calls) == 2
    assert "unknown equipmentId" in calls[1][-1]["content"]
    assert confirmed == {"capabilitiesByEquipmentId": {"cable-id": ["HIGH_PULLEY"]}}
    assert any("Cable stack" in message and "MEDIUM" in message for message in displayed)
    assert any("Bench" in message and "LOW" in message for message in displayed)


def test_confirmation_questions_cover_unobservable_equipment_features() -> None:
    equipment = {
        "equipments": [{"id": "cable-id", "type": "PLATELOADEDCABLE", "name": "Cable"}],
        "accessoryEquipments": [
            {"id": "bench-id", "type": "ACCESSORY", "name": "Bench"},
            {"id": "rings-id", "type": "ACCESSORY", "name": "Rings"},
        ],
    }
    initial = [
        {"equipmentId": "bench-id", "capability": "BENCH", "reason": "Named bench", "confidence": "HIGH"},
        {"equipmentId": "rings-id", "capability": "GYMNASTIC_RINGS", "reason": "Named rings", "confidence": "HIGH"},
    ]

    expanded = _add_confirmation_only_capability_questions(equipment, initial)
    capabilities = {(value["equipmentId"], value["capability"]) for value in expanded}

    assert ("cable-id", "HIGH_PULLEY") in capabilities
    assert ("cable-id", "ROPE_ATTACHMENT") in capabilities
    assert ("bench-id", "FLAT_BENCH") in capabilities
    assert ("bench-id", "ADJUSTABLE_BENCH") in capabilities
    assert ("rings-id", "MUSCLE_UP_CLEARANCE") in capabilities
    assert all(
        value["confidence"] == "LOW"
        for value in expanded
        if (value["equipmentId"], value["capability"]) not in {
            ("bench-id", "BENCH"), ("rings-id", "GYMNASTIC_RINGS")
        }
    )


def test_cable_candidate_requires_linked_pulley_and_attachment_capabilities() -> None:
    equipment = {
        "equipments": [{
            "id": "cable-id",
            "type": "PLATELOADEDCABLE",
            "name": "Cable",
            "capabilities": ["LOADABLE_PLATES"],
        }],
        "accessoryEquipments": [{
            "id": "unrelated-id",
            "type": "ACCESSORY",
            "name": "Unrelated attachment",
            "capabilities": ["HIGH_PULLEY", "ROPE_ATTACHMENT"],
        }],
    }
    candidate = {
        "name": "Cable Pushdown",
        "exerciseType": "WEIGHT",
        "equipmentId": "cable-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "executionMode": "REPETITIONS",
        "resistanceMode": "EXTERNAL_LOAD",
        "movementKey": "cable-pushdown",
        "exerciseCategory": "ISOLATION",
        "requiredCapabilities": [
            "USE_EQUIPMENT:cable-id", "HIGH_PULLEY", "ROPE_ATTACHMENT"
        ],
        "implementUsage": [{"equipmentId": "cable-id", "quantity": 1}],
        "jointDemand": "SINGLE_JOINT",
        "loadingDemand": "MODERATE",
        "warmupDemand": "LOW",
    }

    with pytest.raises(ValueError, match="requires unavailable capabilities"):
        _validate_candidate(candidate, equipment)

    equipment["equipments"][0]["capabilities"].extend(["HIGH_PULLEY", "ROPE_ATTACHMENT"])
    assert _validate_candidate(candidate, equipment)["name"] == "Cable Pushdown"


def test_candidate_enforces_cardio_machine_exercise_type_compatibility() -> None:
    equipment = {
        "equipments": [
            {"id": "bike-id", "type": "CARDIO_MACHINE", "name": "Spin Bike"},
            {"id": "machine-id", "type": "MACHINE", "name": "Weight Machine"},
        ],
        "accessoryEquipments": [],
    }
    candidate = {
        "name": "Stationary Cycling",
        "exerciseType": "COUNTUP",
        "equipmentId": "bike-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "executionMode": "OPEN_DURATION",
        "resistanceMode": "EXTERNAL_LOAD",
        "movementKey": "stationary-cycling",
        "exerciseCategory": None,
        "requiredCapabilities": ["USE_EQUIPMENT:bike-id"],
        "implementUsage": [{"equipmentId": "bike-id", "quantity": 1}],
        "jointDemand": "MULTI_JOINT",
        "loadingDemand": "MODERATE",
        "warmupDemand": "LOW",
    }

    assert _validate_candidate(candidate, equipment)["equipmentId"] == "bike-id"

    weighted_with_cardio = dict(candidate, exerciseType="WEIGHT", executionMode="REPETITIONS")
    with pytest.raises(ValueError, match="CARDIO_MACHINE is incompatible with exerciseType WEIGHT"):
        _validate_candidate(weighted_with_cardio, equipment)

    timed_with_weights = dict(candidate, equipmentId="machine-id")
    timed_with_weights["requiredCapabilities"] = ["USE_EQUIPMENT:machine-id"]
    timed_with_weights["implementUsage"] = [{"equipmentId": "machine-id", "quantity": 1}]
    assert _validate_candidate(timed_with_weights, equipment)["equipmentId"] == "machine-id"


def test_definition_rejects_unknown_declared_equipment_ids() -> None:
    equipment = {
        "equipments": [{"id": "bar-id", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [{"id": "bench-id", "type": "ACCESSORY", "name": "Bench"}],
    }
    candidate = {
        "name": "Barbell Curl",
        "exerciseType": "WEIGHT",
        "equipmentId": "bar-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "exerciseCategory": "ISOLATION",
    }
    unknown_primary = {
        **candidate,
        "equipmentId": "ghost-id",
        "muscleGroups": ["FRONT_BICEPS"],
        "secondaryMuscleGroups": [],
    }
    errors = _structured_definition_errors(unknown_primary, equipment)
    assert any(error["code"] == "UNKNOWN_PRIMARY_EQUIPMENT" for error in errors)

    unknown_accessory = {
        **candidate,
        "requiredAccessoryEquipmentIds": ["ghost-accessory-id"],
        "muscleGroups": ["FRONT_BICEPS"],
        "secondaryMuscleGroups": [],
    }
    errors = _structured_definition_errors(unknown_accessory, equipment)
    assert any(error["code"] == "UNKNOWN_ACCESSORY_EQUIPMENT" for error in errors)

    cable_equipment = {
        "equipments": [{
            "id": "cable-id", "type": "PLATELOADEDCABLE", "name": "Cable",
            "capabilities": ["HIGH_PULLEY", "SINGLE_HANDLE_ATTACHMENT"],
        }],
        "accessoryEquipments": [],
    }
    cable_candidate = {
        **candidate,
        "name": "Cable Pushdown",
        "equipmentId": "cable-id",
    }
    cable_definition = {
        **cable_candidate,
        "muscleGroups": ["BACK_TRICEPS"],
        "secondaryMuscleGroups": [],
    }
    assert _structured_definition_errors(cable_definition, cable_equipment) == []


def test_llm_equipment_context_distinguishes_single_dumbbell_from_pair() -> None:
    equipment = {
        "equipments": [
            {"id": "pair-id", "type": "DUMBBELLS", "name": "Dumbbells"},
            {"id": "single-id", "type": "DUMBBELL", "name": "Dumbbell"},
        ],
        "accessoryEquipments": [],
    }

    context = _format_equipment_context(equipment)

    assert "Dumbbell Pair" in context
    assert "Single Dumbbell" in context
    assert equipment["equipments"][0]["name"] == "Dumbbells"
    assert equipment["equipments"][1]["name"] == "Dumbbell"


def test_capability_implications_satisfy_more_specific_requirements() -> None:
    equipment = {
        "equipments": [{
            "id": "cable-id",
            "type": "PLATELOADEDCABLE",
            "name": "Cable",
            "capabilities": ["ADJUSTABLE_PULLEY"],
        }],
        "accessoryEquipments": [{
            "id": "bench-id",
            "type": "ACCESSORY",
            "name": "Bench",
            "capabilities": ["ADJUSTABLE_BENCH"],
        }],
    }

    capabilities = _capabilities_for_equipment_ids(equipment, {"cable-id", "bench-id"})

    assert {"HIGH_PULLEY", "LOW_PULLEY", "FLAT_BENCH", "INCLINE_BENCH"} <= capabilities
    assert "DECLINE_BENCH" not in capabilities


@pytest.mark.parametrize("name", ["Decline Push-Up", "Incline Push-Up", "Ring Decline Plank", "Unfamiliar Movement"])
def test_candidate_validates_declared_requirements_independently_of_name(name):
    equipment = {
        "equipments": [],
        "accessoryEquipments": [{
            "id": "support-id", "type": "ACCESSORY", "name": "Flat Bench",
            "capabilities": ["BENCH", "FLAT_BENCH"],
        }],
    }
    candidate = {
        "name": name, "exerciseType": "BODY_WEIGHT", "equipmentId": None,
        "bodyWeightPercentage": 80.0, "requiredAccessoryEquipmentIds": ["support-id"],
        "executionMode": "REPETITIONS", "resistanceMode": "BODY_WEIGHT",
        "movementKey": "supported_movement", "exerciseCategory": "MODERATE_COMPOUND",
        "requiredCapabilities": ["USE_EQUIPMENT:support-id", "BENCH"],
        "implementUsage": [{"equipmentId": "support-id", "quantity": 1}],
        "jointDemand": "MULTI_JOINT", "loadingDemand": "MODERATE", "warmupDemand": "MODERATE",
    }
    assert _validate_candidate(candidate, equipment)["name"] == name
    candidate["requiredCapabilities"].append("DECLINE_BENCH")
    with pytest.raises(ValueError, match="unavailable capabilities"):
        _validate_candidate(candidate, equipment)
    equipment["accessoryEquipments"][0]["capabilities"].append("DECLINE_BENCH")
    assert _validate_candidate(candidate, equipment)["name"] == name


def test_review_checkpoint_normalizes_none_and_preserves_source_on_mass_rejection() -> None:
    definition = {
        "id": "definition-id",
        "name": "Generated Movement",
        "exerciseType": "WEIGHT",
        "equipmentId": "weight-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_DELTOIDS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "MODERATE_COMPOUND",
    }
    checkpoint = {
        "exerciseDefinitions": [definition],
        "equipments": [{"id": "weight-id", "type": "BARBELL", "name": "Weight"}],
        "accessoryEquipments": [],
        "generationFailures": [],
    }

    def response(missing_equipment: list[str]):
        def fake_call(_client, _messages, _loading_message, show_loading=False):
            return json.dumps({
                "reviews": [{
                    "id": "definition-id",
                    "requiredEquipmentIds": ["weight-id"],
                    "requirementClauses": [],
                    "missingEquipment": missing_equipment,
                    "issues": [],
                    "patch": [],
                }]
            })
        return fake_call

    completed_payload, completed = review_library_checkpoint(
        None, checkpoint, max_workers=1, semantic_review_call=response(["None"])
    )
    assert completed is True
    assert completed_payload["reviewStatus"] == "COMPLETE"

    failed_payload, completed = review_library_checkpoint(
        None, checkpoint, max_workers=1, semantic_review_call=response(["barbell rack"])
    )
    assert completed is False
    assert failed_payload["reviewStatus"] == "FAILED"
    assert failed_payload["exerciseDefinitions"] == [definition]
    assert "barbell rack" in failed_payload["semanticDiscards"][0]


def test_review_checkpoint_persists_and_resumes_completed_batches() -> None:
    definitions = [
        {
            "id": f"definition-{index}",
            "name": f"Generated Movement {index}",
            "exerciseType": "WEIGHT",
            "equipmentId": "weight-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "muscleGroups": ["FRONT_DELTOIDS"],
            "secondaryMuscleGroups": [],
            "exerciseCategory": "MODERATE_COMPOUND",
        }
        for index in range(21)
    ]
    checkpoint = {
        "exerciseDefinitions": definitions,
        "equipments": [{"id": "weight-id", "type": "BARBELL", "name": "Weight"}],
        "accessoryEquipments": [],
        "generationFailures": [],
    }
    call_count = 0

    def fake_call(_client, messages, loading_message, show_loading=False):
        nonlocal call_count
        call_count += 1
        if loading_message.startswith("Global matrix batch "):
            return json.dumps({
                "groups": [{
                    "setup": "No additional physical setup",
                    "memberIds": [definition["id"] for definition in definitions],
                    "requirementClauses": [],
                    "missingEquipment": [],
                    "rationale": "All supplied definitions use their declared equipment",
                }]
            })
        if loading_message == "Verifying global requirement matrix":
            return json.dumps({"patch": []})
        serialized = "\n".join(str(message.get("content", "")) for message in messages)
        ids = [
            definition["id"]
            for definition in definitions
            if f'"id": "{definition["id"]}"' in serialized
        ]
        return json.dumps({
            "reviews": [
                {
                    "id": definition_id,
                    "requiredEquipmentIds": ["weight-id"],
                    "requirementClauses": [],
                    "missingEquipment": [],
                    "issues": [],
                    "patch": [],
                }
                for definition_id in ids
            ]
        })

    snapshots = []
    result, completed = review_library_checkpoint(
        None,
        checkpoint,
        max_workers=1,
        semantic_review_call=fake_call,
        progress_callback=snapshots.append,
        batch_size=20,
    )
    assert completed is True
    assert len(result["exerciseDefinitions"]) == 21
    assert call_count == 6
    assert len(snapshots) == 2

    call_count = 0
    resumed_result, completed = review_library_checkpoint(
        None,
        snapshots[0],
        max_workers=1,
        semantic_review_call=fake_call,
        batch_size=20,
    )
    assert completed is True
    assert len(resumed_result["exerciseDefinitions"]) == 21
    assert call_count == 4


def test_review_pipeline_survives_definitions_without_instructions() -> None:
    definitions = [
        {
            "id": "definition-a",
            "name": "Overhead Press",
            "exerciseType": "WEIGHT",
            "equipmentId": "barbell-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "muscleGroups": ["FRONT_DELTOIDS"],
            "secondaryMuscleGroups": ["BACK_TRICEPS"],
            "exerciseCategory": "HEAVY_COMPOUND",
        },
        {
            "id": "definition-b",
            "name": "Barbell Row",
            "exerciseType": "WEIGHT",
            "equipmentId": "barbell-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "muscleGroups": ["BACK_UPPER_BACK"],
            "secondaryMuscleGroups": ["FRONT_BICEPS"],
            "exerciseCategory": "MODERATE_COMPOUND",
        },
    ]
    checkpoint = {
        "exerciseDefinitions": definitions,
        "equipments": [{"id": "barbell-id", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [],
        "generationFailures": [],
    }

    def fake_call(_client, messages, loading_message, show_loading=False):
        if loading_message.startswith("Global matrix batch "):
            return json.dumps({
                "groups": [{
                    "setup": "No additional physical setup",
                    "memberIds": [definition["id"] for definition in definitions],
                    "requirementClauses": [],
                    "missingEquipment": [],
                    "rationale": "All supplied definitions use their declared equipment",
                }]
            })
        if loading_message in (
            "Verifying global requirement matrix",
            "Verifying physical requirements",
            "Adjudicating proposed infeasibility",
        ):
            return json.dumps({"patch": []})
        serialized = "\n".join(str(message.get("content", "")) for message in messages)
        ids = [
            definition["id"]
            for definition in definitions
            if f'"id": "{definition["id"]}"' in serialized
        ]
        return json.dumps({
            "reviews": [
                {
                    "id": definition_id,
                    "requiredEquipmentIds": ["barbell-id"],
                    "requirementClauses": [],
                    "missingEquipment": [],
                    "issues": [],
                    "patch": [],
                }
                for definition_id in ids
            ]
        })

    result, completed = review_library_checkpoint(
        None,
        checkpoint,
        max_workers=1,
        semantic_review_call=fake_call,
    )

    assert completed is True
    assert result["reviewStatus"] == "COMPLETE"
    assert [item["name"] for item in result["exerciseDefinitions"]] == [
        "Overhead Press",
        "Barbell Row",
    ]
    assert all("instructions" not in item for item in result["exerciseDefinitions"])


def test_candidate_normalization_strips_redundant_name_qualifiers() -> None:
    normalized = _normalize_candidate_semantics(
        {
            "name": "Single-Arm Dumbbell One-Arm Row",
            "exerciseType": "WEIGHT",
            "equipmentId": "dumbbell",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
        },
        {"equipments": [], "accessoryEquipments": []},
    )

    assert normalized["name"] == "Single-Arm Dumbbell Row"
    # A single qualifier is preserved untouched.
    untouched = _normalize_candidate_semantics(
        {
            "name": "One-Arm Dumbbell Row",
            "exerciseType": "WEIGHT",
            "equipmentId": "dumbbell",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
        },
        {"equipments": [], "accessoryEquipments": []},
    )
    assert untouched["name"] == "One-Arm Dumbbell Row"


def test_max_definitions_caps_emitted_definitions() -> None:
    equipment = {
        "equipments": [{"id": "dumbbells", "type": "DUMBBELLS", "name": "Dumbbells"}],
        "accessoryEquipments": [],
    }
    candidates = [
        {
            "name": name,
            "exerciseType": "WEIGHT",
            "equipmentId": "dumbbells",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
        }
        for name in ("Dumbbell Row", "Dumbbell Press", "Dumbbell Curl")
    ]
    generated = generate_exercise_library(
        None,
        equipment,
        audit_passes=0,
        max_workers=1,
        scope_inventory_by_equipment=False,
        inventory_call=lambda *_args, **_kwargs: json.dumps({"exercises": candidates}),
        reasoner_call=_generator_review_response,
        chat_call=lambda _client, messages, _loading_message, show_loading=False: _definition_response(
            messages,
            lambda exercise: {
                **exercise,
                "muscleGroups": ["FRONT_CHEST"],
                "secondaryMuscleGroups": [],
                "exerciseCategory": "MODERATE_COMPOUND",
            },
        ),
        max_definitions=2,
    )

    # Candidates are sorted by name before emission, so the cap keeps the
    # alphabetically-first definitions deterministically.
    assert [d["name"] for d in generated["exerciseDefinitions"]] == [
        "Dumbbell Curl",
        "Dumbbell Press",
    ]
