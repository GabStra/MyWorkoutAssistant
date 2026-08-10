from __future__ import annotations

import json
import threading
import time

import pytest
from workout_generator_pkg.domain_ops import build_exercise_definition_id

from exercise_library_generator_pkg.generator import (
    _confirm_capability_suggestions,
    _apply_requirement_verification_patch,
    _capabilities_for_equipment_ids,
    _canonicalize_instruction_requirement_shape,
    _emit_definition,
    _apply_capability_file,
    _add_confirmation_only_capability_questions,
    _format_equipment_context,
    _generate_capability_suggestions,
    _instruction_authority_issues,
    _normalize_and_filter_candidates,
    _normalize_candidate_semantics,
    _normalize_matrix_group_requirements,
    _repair_definition_muscles_with_json_patch,
    _review_definition_batch,
    _review_definition_batch_resilient,
    _review_equipment_context,
    _run_global_semantic_consistency_review,
    _run_instruction_authority_review,
    _run_instruction_completeness_review,
    _run_instruction_entailment_audit,
    _run_post_rewrite_semantic_fixed_point,
    _reviews_by_id,
    _save_library_atomic,
    _validate_candidate,
    _validate_definition,
    _validate_instruction_requirements,
    generate_exercise_library,
    review_library_checkpoint,
    review_library_instruction_entailment,
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

    def fake_inventory_call(_client, _messages, _loading_message):
        return json.dumps(next(inventory_responses))

    def fake_definition_call(_client, messages, _loading_message, show_loading=False):
        assert show_loading is False
        candidate = json.loads(messages[-1]["content"].split("Candidate:\n", 1)[1])
        return json.dumps(
            {
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
            }
        )

    generated = generate_exercise_library(
        client=None,
        equipment=equipment,
        request="Build a comprehensive strength exercise library.",
        audit_passes=1,
        max_workers=2,
        scope_inventory_by_equipment=False,
        inventory_call=fake_inventory_call,
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
        chat_call=fake_definition_call,
    )
    assert [item["id"] for item in repeated["exerciseDefinitions"]] == [
        item["id"] for item in definitions
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

    assert parsed["instructions"].startswith("Brace before descending.")
    assert len(parsed["instructions"]) <= 500
    assert parsed["muscleGroups"] == ["FRONT_QUADRICEPS", "BACK_GLUTEAL"]
    assert parsed["secondaryMuscleGroups"] == []
    assert "notes" not in parsed


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
    assert emitted["instructions"] == "Hinge at the hips and extend under control."


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


def test_definition_emitter_applies_multiple_scoped_repairs_without_regeneration() -> None:
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
            {
                "patch": [
                    {
                        "op": "replace",
                        "path": "/instructions",
                        "value": "Hinge forward and row the bar toward the torso.",
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

    assert call_count == 3
    assert emitted["equipmentId"] == "barbell-id"
    assert emitted["instructions"] == "Hinge forward and row the bar toward the torso."
    assert emitted["muscleGroups"] == ["BACK_UPPER_BACK"]


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
            candidate = {
                "name": "Barbell Row",
                "exerciseType": "WEIGHT",
                "equipmentId": "barbell-id",
                "bodyWeightPercentage": None,
                "requiredAccessoryEquipmentIds": [],
            }
            return json.dumps({"exercises": [candidate]})
        if "cable-id" in prompt and "exact equipmentId cable-id" in prompt:
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
        candidate = json.loads(messages[-1]["content"].split("Candidate:\n", 1)[1])
        return json.dumps(
            {
                **candidate,
                "instructions": "Use controlled technique.",
                "instructionEquipmentIds": [candidate["equipmentId"]],
                "muscleGroups": ["BACK_UPPER_BACK"],
                "secondaryMuscleGroups": [],
                "exerciseCategory": "MODERATE_COMPOUND",
            }
        )

    generated = generate_exercise_library(
        client=None,
        equipment=equipment,
        audit_passes=0,
        max_workers=3,
        inventory_call=fake_inventory_call,
        chat_call=fake_definition_call,
    )

    assert maximum_active_calls >= 2
    assert {item["name"] for item in generated["exerciseDefinitions"]} == {
        "Barbell Row",
        "Cable Row",
    }


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
        candidate = json.loads(messages[-1]["content"].split("Candidate:\n", 1)[1])
        return json.dumps(
            {
                **candidate,
                "instructions": "Use controlled technique.",
                "instructionEquipmentIds": [candidate["equipmentId"]],
                "muscleGroups": [],
                "secondaryMuscleGroups": [],
                "exerciseCategory": "STRENGTH",
            }
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
        100.0,
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


def test_instruction_equipment_hallucination_is_repaired_with_json_patch() -> None:
    candidate = {
        "name": "Weighted Squat",
        "exerciseType": "BODY_WEIGHT",
        "equipmentId": "vest-id",
        "bodyWeightPercentage": 100.0,
        "requiredAccessoryEquipmentIds": [],
        "exerciseCategory": "MODERATE_COMPOUND",
    }
    equipment = {
        "equipments": [{"id": "vest-id", "type": "WEIGHTVEST", "name": "Weight Vest"}],
        "accessoryEquipments": [],
    }
    responses = iter(
        [
            {
                **candidate,
                "instructions": "Place a barbell on your back and squat.",
                "instructionEquipmentIds": ["barbell-id"],
                "muscleGroups": ["FRONT_QUADRICEPS"],
                "secondaryMuscleGroups": ["BACK_GLUTEAL"],
                "exerciseCategory": "STRENGTH",
            },
            {
                "patch": [
                    {
                        "op": "replace",
                        "path": "/instructions",
                        "value": "Wear the vest, brace, and squat under control.",
                    },
                    {
                        "op": "replace",
                        "path": "/instructionEquipmentIds",
                        "value": ["vest-id"],
                    },
                ]
            },
        ]
    )

    def fake_call(_client, _messages, _loading_message, show_loading=False):
        return json.dumps(next(responses))

    emitted = _emit_definition(
        client=None,
        candidate=candidate,
        equipment=equipment,
        use_reasoner=False,
        call_reasoner=fake_call,
        call_chat=fake_call,
    )

    assert "barbell" not in emitted["instructions"].casefold()
    assert "vest" in emitted["instructions"].casefold()


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
        "instructions": "Attach an ankle cuff and curl the leg.",
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
        "instructions": "Hold the weight at the chest and squat.",
        "exerciseType": "WEIGHT",
        "equipmentId": "dumbbell-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_QUADRICEPS"],
        "secondaryMuscleGroups": ["BACK_GLUTEAL"],
        "exerciseCategory": "MODERATE_COMPOUND",
    }

    def fake_review(_client, _messages, loading_message, show_loading=False):
        if loading_message == "Verifying physical requirements":
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
                        "issues": ["Instructions should name the declared dumbbell"],
                        "patch": [
                            {
                                "op": "replace",
                                "path": "/instructions",
                                "value": "Hold the dumbbell at the chest and squat.",
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
    assert "dumbbell" in kept[0]["instructions"].casefold()
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
        ],
        "rationale": "A handle and second station are required.",
    })

    assert normalized["requirementClauses"] == [
        {"anyOf": ["SINGLE_HANDLE_ATTACHMENT"]}
    ]
    assert normalized["missingEquipment"] == ["second cable station"]


def test_instruction_entailment_uses_evidence_and_available_capability_alternatives() -> None:
    definitions = [
        {
            "id": definition_id,
            "name": name,
            "instructions": instructions,
            "exerciseType": "WEIGHT",
            "equipmentId": "cable-id",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "muscleGroups": ["BACK_UPPER_BACK"],
            "secondaryMuscleGroups": [],
            "exerciseCategory": "MODERATE_COMPOUND",
        }
        for definition_id, name, instructions in (
            ("wide-id", "Wide Attachment Movement", "Grasp the wide bar and pull down."),
            ("rope-id", "Alternative Movement", "Grasp the bar or rope and pull down."),
        )
    ]

    audit_by_id = {
        "wide-id": {
            "id": "wide-id",
            "requirements": [{
                "evidence": "wide bar",
                "anyOfEquipmentRefs": [],
                "anyOfCapabilities": ["WIDE_BAR_ATTACHMENT"],
                "mandatory": True,
            }, {
                "evidence": "pull down",
                "anyOfEquipmentRefs": ["PRIMARY_CABLE_1"],
                "anyOfCapabilities": [],
                "mandatory": True,
            }],
            "instructionPatch": [],
        },
        "rope-id": {
            "id": "rope-id",
            "requirements": [{
                "evidence": "bar or rope",
                "anyOfEquipmentRefs": [],
                "anyOfCapabilities": ["STRAIGHT_BAR_ATTACHMENT", "ROPE_ATTACHMENT"],
                "mandatory": True,
            }, {
                "evidence": "pull down",
                "anyOfEquipmentRefs": ["PRIMARY_CABLE_1"],
                "anyOfCapabilities": [],
                "mandatory": True,
            }],
            "instructionPatch": [],
        },
    }
    extraction_calls = 0

    def fake_call(_client, messages, loading_message, show_loading=False):
        nonlocal extraction_calls
        if loading_message.startswith("Verifying instruction entailment"):
            return json.dumps({"patch": []})
        extraction_calls += 1
        requested = json.loads(messages[-1]["content"])["definitions"]
        requested_ids = [definition["id"] for definition in requested]
        if extraction_calls == 1:
            requested_ids = requested_ids[:1]
        return json.dumps({"audits": [audit_by_id[value] for value in requested_ids]})

    kept, discarded = _run_instruction_entailment_audit(
        None,
        definitions,
        [],
        {
            "equipments": [{
                "id": "cable-id",
                "name": "Cable",
                "type": "PLATELOADEDCABLE",
                "capabilities": ["ROPE_ATTACHMENT"],
            }],
            "accessoryEquipments": [],
        },
        fake_call,
    )

    assert [definition["name"] for definition in kept] == ["Alternative Movement"]
    assert extraction_calls == 2
    assert discarded == [
        "Wide Attachment Movement: instructions require unavailable capability alternatives "
        "[{'equipmentRefs': [], 'capabilities': ['WIDE_BAR_ATTACHMENT']}]"
    ]


def test_instruction_entailment_repairs_invalid_verified_requirement() -> None:
    definition = {
        "id": "rope-id",
        "name": "Cable Rope Pushdown",
        "instructions": "Attach the rope to the high pulley and press down.",
        "exerciseType": "WEIGHT",
        "equipmentId": "cable-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["BACK_TRICEPS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    }
    loading_messages: list[str] = []
    repair_request = ""
    repair_call_count = 0
    saw_rejection_feedback = False

    def fake_call(_client, messages, loading_message, show_loading=False):
        nonlocal repair_call_count, repair_request, saw_rejection_feedback
        loading_messages.append(loading_message)
        if loading_message.startswith("Instruction entailment batch"):
            return json.dumps({
                "audits": [{
                    "id": "rope-id",
                    "requirements": [{
                        "evidence": "rope",
                        "anyOfEquipmentRefs": [],
                        "anyOfCapabilities": ["ROPE_ATTACHMENT"],
                        "mandatory": True,
                    }, {
                        "evidence": "high pulley",
                        "anyOfEquipmentRefs": [],
                        "anyOfCapabilities": ["HIGH_PULLEY"],
                        "mandatory": True,
                    }, {
                        "evidence": "press down",
                        "anyOfEquipmentRefs": ["PRIMARY_CABLE_1"],
                        "anyOfCapabilities": [],
                        "mandatory": True,
                    }],
                    "instructionPatch": [],
                }]
            })
        if loading_message.startswith("Verifying instruction entailment"):
            return json.dumps({
                "patch": [{
                    "op": "replace",
                    "path": "/audits/0/requirements/0/evidence",
                    "value": "a rope attachment",
                }, {
                    "op": "replace",
                    "path": "/audits/0/requirements/1/evidence",
                    "value": "an elevated pulley",
                }]
            })
        repair_request = str(messages[-1]["content"])
        saw_rejection_feedback = saw_rejection_feedback or (
            "previous repair response was rejected" in repair_request
        )
        repair_call_count += 1
        if repair_call_count == 1:
            return json.dumps({
                "patch": [{
                    "op": "replace",
                    "path": "/audits/0/requirements/0/evidence",
                    "value": "rope",
                }]
            })
        requirement_index = 0 if "a rope attachment" in repair_request else 1
        evidence = "rope" if requirement_index == 0 else "high pulley"
        return json.dumps({
            "patch": [{
                "op": "replace",
                "path": f"/audit/requirements/{requirement_index}/evidence",
                "value": evidence,
            }]
        })

    kept, discarded = _run_instruction_entailment_audit(
        None,
        [definition],
        [],
        {
            "equipments": [{
                "id": "cable-id",
                "name": "Cable",
                "type": "PLATELOADEDCABLE",
                "capabilities": ["ROPE_ATTACHMENT", "HIGH_PULLEY"],
            }],
            "accessoryEquipments": [],
        },
        fake_call,
    )

    assert [item["name"] for item in kept] == ["Cable Rope Pushdown"]
    assert discarded == []
    assert loading_messages == [
        "Instruction entailment batch 1/1",
        "Verifying instruction entailment 1/1",
        "Repairing instruction entailment 1/1 for Cable Rope Pushdown (pass 1/3)",
        "Repairing instruction entailment 1/1 for Cable Rope Pushdown (pass 2/3)",
        "Repairing instruction entailment 1/1 for Cable Rope Pushdown (pass 3/3)",
    ]
    assert "evidence is not an exact instruction substring" in repair_request
    assert saw_rejection_feedback is True


def test_instruction_entailment_satisfies_dumbbell_by_declared_equipment_reference() -> None:
    definition = {
        "id": "raise-id",
        "name": "Dumbbell Front Raise",
        "instructions": "Hold a dumbbell in each hand and raise them to shoulder height.",
        "exerciseType": "WEIGHT",
        "equipmentId": "dumbbells-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_DELTOIDS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    }

    def fake_call(_client, _messages, loading_message, show_loading=False):
        if loading_message.startswith("Verifying instruction entailment"):
            return json.dumps({
                "patch": [{
                    "op": "replace",
                    "path": "/audits/0/id",
                    "value": "unauthorized-id-change",
                }]
            })
        return json.dumps({
            "audits": [{
                "id": "raise-id",
                "requirements": [{
                    "evidence": "a dumbbell in each hand",
                    "equipmentRef": "PRIMARY_DUMBBELL_2",
                    "required": "true",
                    "reason": "The instructions explicitly use a dumbbell.",
                }, {
                    "evidence": "raise them to shoulder height",
                    "anyOfEquipmentRefs": [],
                    "anyOfCapabilities": [],
                    "mandatory": True,
                    "reason": "This is a movement cue, not an equipment requirement.",
                }],
                "instructionPatch": [],
            }]
        })

    kept, discarded = _run_instruction_entailment_audit(
        None,
        [definition],
        [],
        {
            "equipments": [{
                "id": "dumbbells-id",
                "name": "Dumbbells",
                "type": "DUMBBELLS",
                "capabilities": ["ADJUSTABLE_WEIGHT"],
            }, {
                "id": "single-dumbbell-id",
                "name": "Dumbbell",
                "type": "DUMBBELL",
                "capabilities": ["ADJUSTABLE_WEIGHT"],
            }],
            "accessoryEquipments": [],
        },
        fake_call,
    )

    assert [item["name"] for item in kept] == ["Dumbbell Front Raise"]
    assert discarded == []


def test_instruction_requirement_container_shapes_are_canonicalized() -> None:
    requirement = {
        "evidence": "rings",
        "equipmentRef": "ACCESSORY_RINGS_1",
        "required": True,
    }

    single = _canonicalize_instruction_requirement_shape({"requirements": requirement})
    wrapped = _canonicalize_instruction_requirement_shape({
        "requirements": {"items": [requirement]}
    })
    keyed = _canonicalize_instruction_requirement_shape({
        "requirements": {"primary": requirement}
    })
    empty = _canonicalize_instruction_requirement_shape({"requirements": None})

    for result in (single, wrapped, keyed):
        assert result["requirements"] == [{
            "evidence": "rings",
            "anyOfEquipmentRefs": ["ACCESSORY_RINGS_1"],
            "anyOfCapabilities": [],
            "mandatory": True,
        }]
    assert empty["requirements"] == []


def test_instruction_authority_allows_only_undeclared_equipment_to_be_optional() -> None:
    equipment = {
        "equipments": [{
            "id": "vest-id", "name": "Weight Vest", "type": "WEIGHTVEST"
        }],
        "accessoryEquipments": [{
            "id": "bench-id", "name": "Bench", "type": "ACCESSORY"
        }],
    }
    original = {"instructions": "Perform the movement with control."}
    definition = {
        "equipmentId": "vest-id",
        "requiredAccessoryEquipmentIds": [],
        "instructions": "Optional: wear a weight vest. You may use a bench for balance.",
    }

    issues = _instruction_authority_issues(original, definition, equipment)

    assert issues == [
        "instructions describe structurally declared equipment as optional"
    ]


def test_instruction_authority_rejects_internal_tokens_and_invented_loads() -> None:
    issues = _instruction_authority_issues(
        {"instructions": "Swing the dumbbell with control."},
        {
            "equipmentId": "dumbbell-id",
            "requiredAccessoryEquipmentIds": [],
            "instructions": "Swing PRIMARY_DUMBBELL_1, the primary dumbbell, at 5 lb.",
        },
        {
            "equipments": [{
                "id": "dumbbell-id", "name": "Dumbbell", "type": "DUMBBELL"
            }],
            "accessoryEquipments": [],
        },
    )

    assert issues == [
        "instructions expose an internal semantic equipment placeholder",
        "instructions expose internal primary/accessory role terminology",
        "instructions invented exact load values ['5 lb']",
    ]


def test_instruction_authority_requires_natural_declared_equipment_name() -> None:
    equipment = {
        "equipments": [{
            "id": "vest-id", "name": "Weight Vest", "type": "WEIGHTVEST"
        }],
        "accessoryEquipments": [],
    }
    issues = _instruction_authority_issues(
        {"instructions": "Perform the weighted movement with control."},
        {
            "equipmentId": "vest-id",
            "requiredAccessoryEquipmentIds": [],
            "instructions": "Hold weight securely and perform the movement with control.",
        },
        equipment,
    )

    assert issues == [
        "instructions do not explicitly name structurally declared equipment ['Weight Vest']"
    ]
    assert _instruction_authority_issues(
        {"instructions": "Perform the movement with control."},
        {
            "equipmentId": "vest-id",
            "requiredAccessoryEquipmentIds": [],
            "instructions": "Secure the vest and perform the movement with control.",
        },
        equipment,
    ) == []


def test_instruction_authority_escalates_from_patch_to_llm_rewrite() -> None:
    definition = {
        "id": "weighted-id",
        "name": "Weighted Hold",
        "instructions": "Hold the position with control.",
        "exerciseType": "WEIGHT",
        "equipmentId": "vest-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_ABS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    }
    loading_messages = []

    def fake_call(_client, _messages, loading_message, show_loading=False):
        loading_messages.append(loading_message)
        if loading_message.startswith("Rewriting instruction authority"):
            return json.dumps({
                "instructions": "Wear the weight vest and hold the position with control."
            })
        return json.dumps({"patch": []})

    reviewed = _run_instruction_authority_review(
        None,
        [definition],
        [definition],
        {
            "equipments": [{
                "id": "vest-id", "name": "Weight Vest", "type": "WEIGHTVEST"
            }],
            "accessoryEquipments": [],
        },
        fake_call,
    )

    assert reviewed[0]["instructions"].startswith("Wear the weight vest")
    assert len([
        value for value in loading_messages
        if value.startswith("Repairing instruction authority")
    ]) == 3
    assert len([
        value for value in loading_messages
        if value.startswith("Rewriting instruction authority")
    ]) == 1


def test_post_rewrite_semantic_cycle_discards_new_unavailable_attachment() -> None:
    definition = {
        "id": "pulldown-id",
        "name": "Cable Lat Pulldown",
        "instructions": "Sit at the cable on the bench, grasp the wide bar, and pull it to your chest.",
        "exerciseType": "WEIGHT",
        "equipmentId": "cable-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": ["bench-id"],
        "muscleGroups": ["BACK_LATS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "MODERATE_COMPOUND",
    }

    def fake_call(_client, _messages, loading_message, show_loading=False):
        if loading_message.startswith("Verifying instruction entailment"):
            return json.dumps({"patch": []})
        return json.dumps({
            "audits": [{
                "id": "pulldown-id",
                "requirements": [
                    {
                        "evidence": "wide bar",
                        "anyOfEquipmentRefs": [],
                        "anyOfCapabilities": ["WIDE_BAR_ATTACHMENT"],
                        "mandatory": True,
                    },
                    {
                        "evidence": "cable",
                        "anyOfEquipmentRefs": ["PRIMARY_CABLE_1"],
                        "anyOfCapabilities": [],
                        "mandatory": True,
                    },
                    {
                        "evidence": "bench",
                        "anyOfEquipmentRefs": ["ACCESSORY_BENCH_1"],
                        "anyOfCapabilities": [],
                        "mandatory": True,
                    },
                ],
                "instructionPatch": [],
            }]
        })

    reviewed, discards = _run_post_rewrite_semantic_fixed_point(
        None,
        [definition],
        [definition],
        [],
        {
            "equipments": [{
                "id": "cable-id",
                "name": "Cable",
                "type": "PLATELOADEDCABLE",
                "capabilities": ["ROPE_ATTACHMENT", "HIGH_PULLEY"],
            }],
            "accessoryEquipments": [{
                "id": "bench-id",
                "name": "Bench",
                "type": "ACCESSORY",
                "capabilities": ["BENCH"],
            }],
        },
        fake_call,
        {"Cable Lat Pulldown"},
    )

    assert reviewed == []
    assert "WIDE_BAR_ATTACHMENT" in discards[0]


def test_semantic_completeness_discards_implicit_unavailable_support() -> None:
    definition = {
        "id": "incline-id",
        "name": "Barbell Incline Bench Press",
        "instructions": "Lie on the incline bench and press the barbell from the upper chest.",
        "exerciseType": "WEIGHT",
        "equipmentId": "barbell-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": ["bench-id"],
        "muscleGroups": ["FRONT_CHEST"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "HEAVY_COMPOUND",
    }

    def fake_call(_client, _messages, _loading_message, show_loading=False):
        if _loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": []})
        if _loading_message.startswith("Adjudicating semantic completeness"):
            return json.dumps({"patch": []})
        return json.dumps({"reviews": [{
            "id": "incline-id",
            "requirements": [{
                "description": "The loaded bar must start above the athlete.",
                "supportingText": "press the barbell from the upper chest",
                "rationale": "A rack or human handoff is needed to reach the start position.",
                "anyOfEquipmentRefs": [],
                "anyOfCapabilities": ["RACKED_BAR_SUPPORT", "HUMAN_HANDOFF_SUPPORT"],
                "mandatory": True,
            }],
            "missingEquipment": [],
            "contradictions": [],
            "instructionPatch": [],
        }]})

    kept, discards, changed = _run_instruction_completeness_review(
        None,
        [definition],
        [],
        {
            "equipments": [{"id": "barbell-id", "name": "Barbell", "type": "BARBELL"}],
            "accessoryEquipments": [{
                "id": "bench-id", "name": "Bench", "type": "ACCESSORY",
                "capabilities": ["INCLINE_BENCH"],
            }],
        },
        fake_call,
    )

    assert kept == []
    assert changed == set()
    assert "RACKED_BAR_SUPPORT" in discards[0]


def test_semantic_completeness_challenger_adds_omitted_requirement() -> None:
    definition = {
        "id": "press-id", "name": "Incline Press",
        "instructions": "Lie on the incline bench and press the barbell from your chest.",
        "exerciseType": "WEIGHT", "equipmentId": "barbell-id",
        "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": ["bench-id"],
        "muscleGroups": ["FRONT_CHEST"], "secondaryMuscleGroups": [],
        "exerciseCategory": "HEAVY_COMPOUND",
    }

    def fake_call(_client, messages, loading_message, show_loading=False):
        if loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": [{
                "op": "add", "path": "/reviews/0/requirements/-",
                "value": {
                    "description": "The loaded bar needs elevated starting support.",
                    "supportingText": "press the barbell from your chest",
                    "rationale": "The athlete cannot safely receive a loaded bar there from the floor.",
                    "anyOfEquipmentRefs": [],
                    "anyOfCapabilities": ["RACKED_BAR_SUPPORT", "HUMAN_HANDOFF_SUPPORT"],
                    "mandatory": True,
                },
            }]})
        if loading_message.startswith("Adjudicating semantic completeness"):
            return json.dumps({"patch": []})
        requested = json.loads(messages[-1]["content"])["definitions"][0]
        return json.dumps({"reviews": [{
            "id": requested["id"], "requirements": [], "missingEquipment": [],
            "contradictions": [], "instructionPatch": [],
        }]})

    kept, discards, _ = _run_instruction_completeness_review(
        None, [definition], [],
        {"equipments": [{"id": "barbell-id", "name": "Barbell", "type": "BARBELL"}],
         "accessoryEquipments": [{"id": "bench-id", "name": "Bench", "type": "ACCESSORY",
                                    "capabilities": ["INCLINE_BENCH"]}]},
        fake_call,
    )

    assert kept == []
    assert "RACKED_BAR_SUPPORT" in discards[0]


def test_semantic_completeness_adjudicator_removes_capability_overreach() -> None:
    definition = {
        "id": "snatch-id", "name": "Dumbbell Snatch",
        "instructions": "Lift the dumbbell from the floor and lock it out overhead.",
        "exerciseType": "WEIGHT", "equipmentId": "dumbbell-id",
        "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["BACK_UPPER_BACK"], "secondaryMuscleGroups": [],
        "exerciseCategory": "HEAVY_COMPOUND",
    }

    def fake_call(_client, messages, loading_message, show_loading=False):
        if loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": []})
        if loading_message.startswith("Adjudicating semantic completeness"):
            return json.dumps({"patch": [{
                "op": "remove", "path": "/review/requirements/1",
            }]})
        requested = json.loads(messages[-1]["content"])["definitions"][0]
        return json.dumps({"reviews": [{
            "id": requested["id"],
            "requirements": [{
                "description": "The dumbbell supplies resistance.",
                "supportingText": "dumbbell",
                "rationale": "The instruction names the implement.",
                "anyOfEquipmentRefs": ["PRIMARY_DUMBBELL_1"],
                "anyOfCapabilities": [], "mandatory": True,
            }, {
                "description": "Overhead clearance is required.",
                "supportingText": "lock it out overhead",
                "rationale": "This incorrectly treats ordinary overhead motion as a transition.",
                "anyOfEquipmentRefs": [],
                "anyOfCapabilities": ["OVER_IMPLEMENT_TRANSITION_CLEARANCE"],
                "mandatory": True,
            }],
            "missingEquipment": [], "contradictions": [], "instructionPatch": [],
        }]})

    kept, discards, _ = _run_instruction_completeness_review(
        None, [definition], [],
        {"equipments": [{"id": "dumbbell-id", "name": "Dumbbell", "type": "DUMBBELL"}],
         "accessoryEquipments": []},
        fake_call,
    )

    assert len(kept) == 1
    assert discards == []


def test_semantic_completeness_invalid_verifier_isolates_every_definition() -> None:
    definition = {
        "id": "curl-id", "name": "Dumbbell Curl",
        "instructions": "Curl the dumbbell with control.",
        "exerciseType": "WEIGHT", "equipmentId": "dumbbell-id",
        "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_BICEPS"], "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    }
    adjudication_calls = 0

    def fake_call(_client, messages, loading_message, show_loading=False):
        nonlocal adjudication_calls
        if loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"reviews": []})
        if loading_message.startswith("Adjudicating semantic completeness"):
            adjudication_calls += 1
            return json.dumps({"patch": []})
        requested = json.loads(messages[-1]["content"])["definitions"][0]
        return json.dumps({"reviews": [{
            "id": requested["id"], "requirements": [{
                "description": "The dumbbell supplies resistance.",
                "supportingText": "dumbbell",
                "rationale": "The instruction explicitly names it.",
                "anyOfEquipmentRefs": ["PRIMARY_DUMBBELL_1"],
                "anyOfCapabilities": [], "mandatory": True,
            }], "missingEquipment": [], "contradictions": [], "instructionPatch": [],
        }]})

    kept, discards, _ = _run_instruction_completeness_review(
        None, [definition], [],
        {"equipments": [{"id": "dumbbell-id", "name": "Dumbbell", "type": "DUMBBELL"}],
         "accessoryEquipments": []},
        fake_call,
    )

    assert len(kept) == 1
    assert discards == []
    assert adjudication_calls == 1


def test_semantic_completeness_repairs_contradiction_and_keeps_optional_equipment() -> None:
    definition = {
        "id": "pullover-id",
        "name": "Cable Pullover",
        "instructions": "Lie on the bench, then step forward and hinge while pulling the rope.",
        "exerciseType": "WEIGHT",
        "equipmentId": "cable-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["BACK_UPPER_BACK"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    }
    call_count = 0

    def fake_call(_client, messages, _loading_message, show_loading=False):
        nonlocal call_count
        if _loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": []})
        if _loading_message.startswith("Adjudicating semantic completeness"):
            return json.dumps({"patch": []})
        call_count += 1
        requested_definition = json.loads(messages[-1]["content"])["definitions"][0]
        instructions = requested_definition["instructions"]
        contradiction = "Lie on the bench" in instructions
        return json.dumps({"reviews": [{
            "id": requested_definition["id"],
            "requirements": [{
                "description": "A rope attachment is used.",
                "supportingText": "rope",
                "rationale": "The rope is explicitly grasped for the movement.",
                "anyOfEquipmentRefs": [],
                "anyOfCapabilities": ["ROPE_ATTACHMENT"],
                "mandatory": True,
            }, {
                "description": "A bench may support a pullover variation.",
                "supportingText": "bench" if contradiction else "pullover",
                "rationale": "This support is optional and must not block feasibility.",
                "anyOfEquipmentRefs": [],
                "anyOfCapabilities": ["BENCH"],
                "mandatory": False,
            }],
            "missingEquipment": [],
            "contradictions": ([{
                "description": "Lying down is incompatible with stepping and hinging.",
                "supportingText": "Lie on the bench, then step forward and hinge",
            }] if contradiction else []),
            "instructionPatch": ([{
                "op": "replace",
                "path": "/instructions",
                "value": "Stand facing the cable, hinge slightly, and pull the rope toward your thighs in a pullover arc.",
            }] if contradiction else []),
        }]})

    kept, discards, changed = _run_instruction_completeness_review(
        None,
        [definition],
        [],
        {
            "equipments": [{
                "id": "cable-id", "name": "Cable", "type": "PLATELOADEDCABLE",
                "capabilities": ["ROPE_ATTACHMENT"],
            }],
            "accessoryEquipments": [],
        },
        fake_call,
    )

    assert discards == []
    assert call_count == 2
    assert changed == {"Cable Pullover"}
    assert kept[0]["instructions"].startswith("Stand facing the cable")


def test_semantic_completeness_json_patch_repairs_invalid_requirement() -> None:
    definition = {
        "id": "deadlift-id",
        "name": "Barbell Snatch Grip Deadlift",
        "instructions": "Grip the barbell wide and lift it from the floor.",
        "exerciseType": "WEIGHT",
        "equipmentId": "barbell-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["BACK_LOWER_BACK"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "HEAVY_COMPOUND",
    }
    repair_calls = 0

    def fake_call(_client, _messages, loading_message, show_loading=False):
        nonlocal repair_calls
        if loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": []})
        if " repair " in loading_message:
            repair_calls += 1
            return json.dumps({"patch": [{
                "op": "replace",
                "path": "/review/requirements/0/supportingText",
                "value": "barbell",
            }]})
        requested = json.loads(_messages[-1]["content"])["definitions"][0]
        return json.dumps({"reviews": [{
            "id": requested["id"],
            "requirements": [{
                "description": "The movement requires the barbell.",
                "supportingText": "a barbell",
                "rationale": "The named implement supplies the load.",
                "anyOfEquipmentRefs": ["PRIMARY_BARBELL_1"],
                "anyOfCapabilities": [],
                "mandatory": True,
            }],
            "missingEquipment": [],
            "contradictions": [],
            "instructionPatch": [],
        }]})

    kept, discards, changed = _run_instruction_completeness_review(
        None,
        [definition],
        [],
        {
            "equipments": [{"id": "barbell-id", "name": "Barbell", "type": "BARBELL"}],
            "accessoryEquipments": [],
        },
        fake_call,
    )

    assert len(kept) == 1
    assert discards == []
    assert changed == set()
    assert repair_calls == 1


def test_semantic_completeness_uses_isolated_rewrite_after_patch_repairs_fail() -> None:
    definition = {
        "id": "bridge-id", "name": "Single-Leg Glute Bridge on Bench",
        "instructions": "Place one foot on the bench and raise your hips.",
        "exerciseType": "BODY_WEIGHT", "equipmentId": None,
        "bodyWeightPercentage": 60.0,
        "requiredAccessoryEquipmentIds": ["bench-id"],
        "muscleGroups": ["BACK_GLUTES"], "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    }
    isolated_calls = 0

    def fake_call(_client, messages, loading_message, show_loading=False):
        nonlocal isolated_calls
        if loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": []})
        if " isolated rewrite " in loading_message:
            isolated_calls += 1
            request = json.loads(messages[-1]["content"])
            repaired = request["review"]
            repaired["requirements"][0]["supportingText"] = "bench"
            return json.dumps({"review": repaired})
        if " repair " in loading_message:
            return json.dumps({"patch": []})
        requested = json.loads(messages[-1]["content"])["definitions"][0]
        return json.dumps({"reviews": [{
            "id": requested["id"],
            "requirements": [{
                "description": "The foot is supported by a bench.",
                "supportingText": "a stable elevated bench",
                "rationale": "The elevated foot requires the declared bench.",
                "anyOfEquipmentRefs": ["ACCESSORY_BENCH_1"],
                "anyOfCapabilities": [], "mandatory": True,
            }],
            "missingEquipment": [], "contradictions": [], "instructionPatch": [],
        }]})

    kept, discards, _ = _run_instruction_completeness_review(
        None, [definition], [],
        {"equipments": [], "accessoryEquipments": [{
            "id": "bench-id", "name": "Bench", "type": "ACCESSORY",
            "capabilities": ["BENCH"],
        }]},
        fake_call,
    )

    assert len(kept) == 1
    assert discards == []
    assert isolated_calls == 1


def test_semantic_completeness_grounds_paraphrased_evidence_by_offsets() -> None:
    definition = {
        "id": "twist-id", "name": "Single Dumbbell Twist",
        "instructions": "Hold one dumbbell at your chest and rotate your torso.",
        "exerciseType": "WEIGHT", "equipmentId": "dumbbell-id",
        "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_ABS"], "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    }

    def malformed_review(review_id):
        return {
            "id": review_id,
            "requirements": [{
                "description": "One dumbbell supplies resistance.",
                "supportingText": "a single dumbbell held at the chest",
                "rationale": "The instruction names one dumbbell.",
                "anyOfEquipmentRefs": ["PRIMARY_DUMBBELL_1"],
                "anyOfCapabilities": [], "mandatory": True,
            }],
            "missingEquipment": [], "contradictions": [], "instructionPatch": [],
        }

    def fake_call(_client, messages, loading_message, show_loading=False):
        if loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": []})
        if " evidence grounding " in loading_message:
            instructions = definition["instructions"]
            start = instructions.index("one dumbbell")
            return json.dumps({
                "requirementSpans": [{"index": 0, "start": start, "end": start + len("one dumbbell")}],
                "contradictionSpans": [],
            })
        if " isolated rewrite " in loading_message:
            return json.dumps({"review": malformed_review(definition["id"])})
        if " repair " in loading_message:
            return json.dumps({"patch": []})
        requested = json.loads(messages[-1]["content"])["definitions"][0]
        return json.dumps({"reviews": [malformed_review(requested["id"])]})

    kept, discards, _ = _run_instruction_completeness_review(
        None, [definition], [],
        {"equipments": [{"id": "dumbbell-id", "name": "Dumbbell", "type": "DUMBBELL"}],
         "accessoryEquipments": []},
        fake_call,
    )

    assert len(kept) == 1
    assert discards == []


def test_semantic_completeness_falls_back_to_one_finding_evidence_span() -> None:
    definition = {
        "id": "fly-id", "name": "Single-Arm Incline Fly",
        "instructions": "Lie on the incline bench and arc one dumbbell over the chest.",
        "exerciseType": "WEIGHT", "equipmentId": "dumbbell-id",
        "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": ["bench-id"],
        "muscleGroups": ["FRONT_CHEST"], "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    }

    def malformed(review_id):
        return {"id": review_id, "requirements": [{
            "description": "One dumbbell supplies resistance.",
            "supportingText": "the single weight",
            "rationale": "The instruction names one dumbbell.",
            "anyOfEquipmentRefs": ["PRIMARY_DUMBBELL_1"],
            "anyOfCapabilities": [], "mandatory": True,
        }], "missingEquipment": [], "contradictions": [], "instructionPatch": []}

    def fake_call(_client, messages, loading_message, show_loading=False):
        if loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": []})
        if " isolated evidence " in loading_message:
            start = definition["instructions"].index("one dumbbell")
            return json.dumps({"start": start, "end": start + len("one dumbbell")})
        if " evidence grounding " in loading_message:
            return json.dumps({"requirementSpans": [], "contradictionSpans": []})
        if " isolated rewrite " in loading_message:
            return json.dumps({"review": malformed(definition["id"])})
        if " repair " in loading_message:
            return json.dumps({"patch": []})
        requested = json.loads(messages[-1]["content"])["definitions"][0]
        return json.dumps({"reviews": [malformed(requested["id"])]})

    kept, discards, _ = _run_instruction_completeness_review(
        None, [definition], [],
        {"equipments": [{"id": "dumbbell-id", "name": "Dumbbell", "type": "DUMBBELL"}],
         "accessoryEquipments": [{"id": "bench-id", "name": "Bench", "type": "ACCESSORY"}]},
        fake_call,
    )

    assert len(kept) == 1
    assert discards == []


def test_semantic_completeness_progress_resumes_after_completed_batch() -> None:
    definitions = [{
        "id": f"curl-{index}", "name": f"Dumbbell Curl {index}",
        "instructions": "Curl the dumbbell with control.",
        "exerciseType": "WEIGHT", "equipmentId": "dumbbell-id",
        "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_BICEPS"], "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    } for index in range(2)]
    snapshots = []

    def valid_review(requested):
        return {"reviews": [{
            "id": requested["id"],
            "requirements": [{
                "description": "The movement uses a dumbbell.",
                "supportingText": "dumbbell",
                "rationale": "The instruction explicitly names it.",
                "anyOfEquipmentRefs": ["PRIMARY_DUMBBELL_1"],
                "anyOfCapabilities": [], "mandatory": True,
            }],
            "missingEquipment": [], "contradictions": [], "instructionPatch": [],
        }]}

    def failing_second_call(_client, messages, _loading_message, show_loading=False):
        if _loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": []})
        requested = json.loads(messages[-1]["content"])["definitions"][0]
        if requested["id"] == "curl-1":
            return json.dumps({"reviews": []})
        return json.dumps(valid_review(requested))

    with pytest.raises(ValueError, match="batch 2 remained invalid"):
        _run_instruction_completeness_review(
            None, definitions, [],
            {"equipments": [{"id": "dumbbell-id", "name": "Dumbbell", "type": "DUMBBELL"}],
             "accessoryEquipments": []},
            failing_second_call, batch_size=1,
            batch_completed_callback=lambda current, discards, completed: snapshots.append(
                (current, discards, completed)
            ),
        )

    resumed_requests = []
    current, discards, completed = snapshots[-1]

    def resumed_call(_client, messages, _loading_message, show_loading=False):
        if _loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": []})
        requested = json.loads(messages[-1]["content"])["definitions"][0]
        resumed_requests.append(requested["id"])
        return json.dumps(valid_review(requested))

    kept, _, _ = _run_instruction_completeness_review(
        None, current, discards,
        {"equipments": [{"id": "dumbbell-id", "name": "Dumbbell", "type": "DUMBBELL"}],
         "accessoryEquipments": []},
        resumed_call, batch_size=1, completed_definition_ids=completed,
    )

    assert len(kept) == 2
    assert resumed_requests == ["curl-1"]


def test_instruction_entailment_repairs_instructions_for_omitted_declared_equipment() -> None:
    definition = {
        "id": "weighted-id",
        "name": "Weighted Bicycle Crunch",
        "instructions": "Alternate opposite elbow and knee with control.",
        "exerciseType": "WEIGHT",
        "equipmentId": "vest-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_ABS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "MODERATE_COMPOUND",
    }

    def fake_call(_client, _messages, loading_message, show_loading=False):
        if loading_message.startswith("Instruction entailment batch"):
            return json.dumps({
                "audits": [{
                    "id": "weighted-id",
                    "requirements": [],
                    "instructionPatch": [],
                }]
            })
        if loading_message.startswith("Verifying instruction entailment"):
            return json.dumps({"patch": []})
        return json.dumps({
            "patch": [
                {
                    "op": "replace",
                    "path": "/definition/instructions",
                    "value": "Wear the weight vest and alternate opposite elbow and knee with control.",
                },
                {
                    "op": "replace",
                    "path": "/audit/requirements",
                    "value": [{
                        "evidence": "weight vest",
                        "anyOfEquipmentRefs": ["PRIMARY_WEIGHT_VEST_1"],
                        "anyOfCapabilities": [],
                        "mandatory": True,
                    }],
                },
            ]
        })

    kept, discarded = _run_instruction_entailment_audit(
        None,
        [definition],
        [],
        {
            "equipments": [{
                "id": "vest-id",
                "name": "Weight Vest",
                "type": "WEIGHTVEST",
                "capabilities": ["ADJUSTABLE_WEIGHT"],
            }],
            "accessoryEquipments": [],
        },
        fake_call,
    )

    assert discarded == []
    assert kept[0]["instructions"].startswith("Wear the weight vest")


def test_instruction_entailment_rejects_legacy_reduced_baseline() -> None:
    with pytest.raises(ValueError, match="old instruction-entailment contract"):
        review_library_instruction_entailment(
            None,
            {
                "exerciseDefinitions": [{"id": "reduced-id"}],
                "preInstructionEntailmentDefinitions": [{"id": "reduced-id"}],
                "sourceExerciseDefinitions": [
                    {"id": "reduced-id"},
                    {"id": "falsely-discarded-id"},
                ],
                "equipments": [],
                "accessoryEquipments": [],
                "semanticDiscards": [
                    "Movement: instructions require unavailable capability alternatives []"
                ],
            },
        )


def test_instruction_entailment_persists_and_resumes_completed_batches() -> None:
    definition = {
        "id": "curl-id",
        "name": "Dumbbell Curl",
        "instructions": "Curl the dumbbell with control.",
        "exerciseType": "WEIGHT",
        "equipmentId": "dumbbell-id",
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_BICEPS"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "ISOLATION",
    }
    checkpoint = {
        "exerciseDefinitions": [definition],
        "equipments": [{
            "id": "dumbbell-id",
            "name": "Dumbbell",
            "type": "DUMBBELL",
            "capabilities": ["ADJUSTABLE_WEIGHT"],
        }],
        "accessoryEquipments": [],
        "semanticDiscards": [],
        "generationFailures": [],
    }
    call_count = 0

    def fake_call(_client, _messages, loading_message, show_loading=False):
        nonlocal call_count
        call_count += 1
        if loading_message.startswith("Verifying semantic completeness"):
            return json.dumps({"patch": []})
        if loading_message.startswith("Semantic completeness batch"):
            requested = json.loads(_messages[-1]["content"])["definitions"][0]
            return json.dumps({"reviews": [{
                "id": requested["id"],
                "requirements": [{
                    "description": "The movement uses a dumbbell.",
                    "supportingText": "dumbbell",
                    "rationale": "The instruction explicitly names the implement.",
                    "anyOfEquipmentRefs": ["PRIMARY_DUMBBELL_1"],
                    "anyOfCapabilities": [],
                    "mandatory": True,
                }],
                "missingEquipment": [],
                "contradictions": [],
                "instructionPatch": [],
            }]})
        if loading_message.startswith("Verifying instruction entailment"):
            return json.dumps({"patch": []})
        return json.dumps({
            "audits": [{
                "id": "curl-id",
                "requirements": [{
                    "evidence": "dumbbell",
                    "anyOfEquipmentRefs": ["PRIMARY_DUMBBELL_1"],
                    "anyOfCapabilities": [],
                    "mandatory": True,
                }],
                "instructionPatch": [],
            }]
        })

    snapshots = []
    result = review_library_instruction_entailment(
        None,
        checkpoint,
        instruction_entailment_call=fake_call,
        progress_callback=snapshots.append,
    )
    assert len(result["exerciseDefinitions"]) == 1
    assert len(snapshots) == 2
    assert call_count == 4

    call_count = 0
    resumed = review_library_instruction_entailment(
        None,
        snapshots[-1],
        instruction_entailment_call=fake_call,
    )
    assert len(resumed["exerciseDefinitions"]) == 1
    assert call_count == 0

    call_count = 0

    completed_rerun = review_library_instruction_entailment(
        None,
        result,
        instruction_entailment_call=fake_call,
    )
    assert len(completed_rerun["exerciseDefinitions"]) == 1
    assert call_count == 0


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


def test_definition_rejects_undeclared_equipment_and_capabilities_in_instructions() -> None:
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
    raw = {
        **candidate,
        "instructions": "Sit on a bench and curl the barbell.",
        "instructionEquipmentIds": ["bar-id"],
        "muscleGroups": ["FRONT_BICEPS"],
        "secondaryMuscleGroups": [],
    }
    with pytest.raises(ValueError, match="undeclared equipment: Bench"):
        _validate_definition(raw, candidate, equipment)

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
    cable_raw = {
        **cable_candidate,
        "instructions": "Attach a rope to the high pulley and press down.",
        "instructionEquipmentIds": ["cable-id"],
        "muscleGroups": ["BACK_TRICEPS"],
        "secondaryMuscleGroups": [],
    }
    with pytest.raises(ValueError, match="undeclared capabilities: rope attachment"):
        _validate_definition(cable_raw, cable_candidate, cable_equipment)


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


def test_instruction_setup_rules_catch_explicit_incline_capability_language() -> None:
    equipment = {
        "equipments": [{"id": "bar-id", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [
            {"id": "bench-id", "type": "ACCESSORY", "name": "Bench", "capabilities": ["BENCH"]},
        ],
    }
    linked = {
        "name": "Generic Press",
        "equipmentId": "bar-id",
        "requiredAccessoryEquipmentIds": ["bench-id"],
    }

    with pytest.raises(ValueError, match="incline bench"):
        _validate_instruction_requirements("Lie on an incline bench and press the barbell.", linked, equipment)


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

    assert {"HIGH_PULLEY", "LOW_PULLEY", "FLAT_BENCH", "INCLINE_BENCH", "DECLINE_BENCH"} <= capabilities


def test_review_checkpoint_normalizes_none_and_preserves_source_on_mass_rejection() -> None:
    definition = {
        "id": "definition-id",
        "name": "Generated Movement",
        "instructions": "Perform the movement under control.",
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
            "instructions": "Perform the movement under control.",
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
