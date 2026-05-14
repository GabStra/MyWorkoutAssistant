import copy
import json

import pytest
from jsonschema import validate
from jsonschema.exceptions import ValidationError

from workout_generator_pkg import cli
from workout_generator_pkg.constants import BASE_SYSTEM_PROMPT
from workout_generator_pkg.constants import JSON_SYSTEM_PROMPT
from workout_generator_pkg.constants import SUMMARIZATION_SYSTEM_PROMPT
from workout_generator_pkg.cli import PlaceholderIdManager
from workout_generator_pkg.domain_ops import calculate_equipment_weight_combinations
from workout_generator_pkg.domain_ops import create_placeholder_schema
from workout_generator_pkg.domain_ops import fix_set_errors
from workout_generator_pkg.domain_ops import format_planner_equipment_context
from workout_generator_pkg.domain_ops import get_selectable_weights_for_exercise
from workout_generator_pkg.domain_ops import sync_exercises_from_definitions
from workout_generator_pkg.domain_ops import sync_exercises_from_plan_index
from workout_generator_pkg.domain_ops import validate_equipment_weight_combinations
from workout_generator_pkg.generation_pipeline import _extract_structured_generation_facts
from workout_generator_pkg.generation_pipeline import _normalize_custom_prompt_equipment_ids
from workout_generator_pkg.json_patching import build_allowed_patch_scope
from workout_generator_pkg.json_patching import validate_patch_operations_scope
from workout_generator_pkg.exercise_contracts import (
    BODY_WEIGHT_EXERCISE_SCHEMA,
    COUNTDOWN_EXERCISE_SCHEMA,
    COUNTUP_EXERCISE_SCHEMA,
    WEIGHT_EXERCISE_SCHEMA,
)
from workout_generator_pkg.plan_contract import ContractValidationError
from workout_generator_pkg.plan_contract import validate_plan_index_contract
from workout_generator_pkg.plan_contract import validate_exercise_definitions_contract
from workout_generator_pkg.plan_contract import validate_workout_structures_contract
from workout_generator_pkg.stage_prompts import (
    EXERCISE_SYSTEM_PROMPT,
    PLAN_INDEX_SYSTEM_PROMPT,
    WORKOUT_STRUCTURE_SYSTEM_PROMPT,
)


def test_summarization_prompt_preserves_bodyweight_load_semantics():
    assert "BODY_WEIGHT movements" in SUMMARIZATION_SYSTEM_PROMPT
    assert "total effective load" in SUMMARIZATION_SYSTEM_PROMPT
    assert "partial-bodyweight" in SUMMARIZATION_SYSTEM_PROMPT
    assert "keep 'Weighted Ring Row +10 kg, 52.3 kg total' as both facts" in SUMMARIZATION_SYSTEM_PROMPT


def test_rest_prompts_require_exact_values_not_ranges():
    assert "always give one exact value" in BASE_SYSTEM_PROMPT
    assert "rest between sets and rest between exercises as separate, clearly labeled fields or columns" in BASE_SYSTEM_PROMPT
    assert "never ranges" in JSON_SYSTEM_PROMPT
    assert "restBetweenSetsSeconds and restToNextSeconds must always be exact integers in seconds" in PLAN_INDEX_SYSTEM_PROMPT
    assert "For timed exercises, numWorkSets counts timed work intervals and must be a positive integer when provided" in PLAN_INDEX_SYSTEM_PROMPT
    assert "Rest values in the summary must be expressed as one exact number" in SUMMARIZATION_SYSTEM_PROMPT


def test_superset_prompts_require_structured_group_preservation():
    assert "superset pairings" in SUMMARIZATION_SYSTEM_PROMPT
    assert "supersetGroups" in PLAN_INDEX_SYSTEM_PROMPT
    assert "Superset rules:" in WORKOUT_STRUCTURE_SYSTEM_PROMPT
    assert "exerciseIds and restSecondsByExercise mapping" in WORKOUT_STRUCTURE_SYSTEM_PROMPT


def test_exercise_prompt_includes_generate_warmup_sets_guidance():
    assert "Set generateWarmUpSets explicitly to true or false" in EXERCISE_SYSTEM_PROMPT
    assert "heavy or technically demanding compound lifts" in EXERCISE_SYSTEM_PROMPT
    assert "dedicated warm-up entry" in EXERCISE_SYSTEM_PROMPT


def test_sync_exercises_from_definitions_preserves_generate_warmup_sets():
    workout_store = {
        "workouts": [
            {
                "workoutComponents": [
                    {
                        "id": "EXERCISE_0",
                        "type": "Exercise",
                        "generateWarmUpSets": False,
                    }
                ]
            }
        ]
    }
    exercise_definitions = {
        "EXERCISE_0": {
            "id": "EXERCISE_0",
            "generateWarmUpSets": True,
        }
    }

    synced = sync_exercises_from_definitions(workout_store, exercise_definitions)

    assert synced["workouts"][0]["workoutComponents"][0]["generateWarmUpSets"] is True


def test_structured_generation_facts_preserve_partial_bodyweight_numeric_details():
    custom_prompt = (
        "DAY A - Full Body A:\n"
        "3. Weighted Pull-Up (Pull-Up Bar + Weight Vest +4 kg, total 69 kg) - 3 sets x 4-8 reps\n"
        "4. Weighted Ring Row (Rings + Weight Vest +10 kg, total 52.3 kg) - 3 sets x 8-12 reps\n"
        "\n"
        "DAY C - Full Body C:\n"
        "2. Ring Dip (Rings + Weight Vest +10 kg, total 75 kg) - 3 sets x 8-12 reps\n"
        "3. Weighted Ring Row (Rings + Weight Vest +8 kg, total 50.3 kg) - 3 sets x 8-12 reps\n"
    )

    facts = _extract_structured_generation_facts(custom_prompt)

    assert "Derived user bodyweight estimate from full-bodyweight totals: 65 kg" in facts
    assert "Weighted Ring Row" in facts
    assert "totalEffectiveLoad=52.3 kg" in facts
    assert "totalEffectiveLoad=50.3 kg" in facts
    assert "derivedBodyWeightPercentage=65.08" in facts
    assert "baselineHint=partial-bodyweight" in facts


def test_generate_index_includes_structured_generation_facts_with_priority(monkeypatch):
    captured = {}

    def fake_chat(client, messages, loading_text, show_loading=True, logger=None):
        captured["messages"] = messages
        return json.dumps(
            {
                "planName": "Test Plan",
                "equipments": [],
                "accessoryEquipments": [],
                "exercises": [],
                "workouts": [],
            }
        )

    monkeypatch.setattr(cli, "json_call_chat_max_with_loading", fake_chat)

    plan_index = cli.generate_index(
        client=None,
        context_summary="Summary says ring row uses +10 kg vest.",
        custom_request="Weighted Ring Row total 52.3 kg.",
        use_reasoner=False,
        provided_equipment=None,
        logger=None,
        structured_generation_facts=(
            "Structured generation facts (authoritative for exact numeric/bodyweight details):\n"
            "- Weighted Ring Row: additionalWeight=10 kg, totalEffectiveLoad=52.3 kg, derivedBodyWeightPercentage=65.08, baselineHint=partial-bodyweight"
        )
    )

    assert plan_index["planName"] == "Test Plan"
    user_message = captured["messages"][-1]["content"]
    assert "Structured generation facts above are authoritative" in user_message
    assert "derivedBodyWeightPercentage=65.08" in user_message


def test_barbell_totals_match_shared_logic_without_double_counting_bar_weight():
    equipment = {
        "id": "EQUIPMENT_0",
        "type": "BARBELL",
        "name": "Test Barbell",
        "availablePlates": [
            {"weight": 20.0, "thickness": 10.0},
            {"weight": 20.0, "thickness": 10.0},
        ],
        "sleeveLength": 100,
        "barWeight": 20.0,
    }

    totals = calculate_equipment_weight_combinations(equipment)

    assert 20.0 in totals
    assert 60.0 in totals
    assert 80.0 not in totals


def test_bodyweight_selectable_weights_include_zero_additional_load():
    equipment = {
        "id": "EQUIPMENT_0",
        "type": "WEIGHTVEST",
        "name": "Vest",
        "availableWeights": [
            {"weight": 5.0},
            {"weight": 10.0},
        ],
    }

    selectable = get_selectable_weights_for_exercise("BODY_WEIGHT", equipment)

    assert selectable == {0.0, 5.0, 10.0}


def test_planner_equipment_context_separates_primary_and_accessory_roles_and_lists_selectable_loads():
    equipment = [
        {
            "id": "EQUIPMENT_1",
            "type": "DUMBBELL",
            "name": "Single Dumbbell",
            "dumbbells": [{"weight": 5.0}, {"weight": 6.5}],
            "extraWeights": [],
            "maxExtraWeightsPerLoadingPoint": 0,
        }
    ]
    accessories = [
        {
            "id": "ACCESSORY_2",
            "type": "ACCESSORY",
            "name": "Bench",
        }
    ]

    formatted = format_planner_equipment_context(equipment, accessories)

    assert "Primary Equipment (valid for equipmentId only):" in formatted
    assert "Accessory Equipment (valid for requiredAccessoryEquipmentIds only):" in formatted
    assert "EQUIPMENT_1 (Single Dumbbell, DUMBBELL)" in formatted
    assert "Selectable app loads for exact targets: 5kg, 6.5kg" in formatted
    assert "ACCESSORY_2 (Bench, ACCESSORY)" in formatted
    assert "never use this ID as equipmentId" in formatted


def test_validate_equipment_weights_reports_nearest_selectable_total_without_mutating():
    equipment = {
        "id": "EQUIPMENT_0",
        "type": "BARBELL",
        "name": "Test Barbell",
        "availablePlates": [
            {"weight": 20.0, "thickness": 10.0},
            {"weight": 20.0, "thickness": 10.0},
        ],
        "sleeveLength": 100,
        "barWeight": 20.0,
    }
    exercise = {
        "id": "EXERCISE_0",
        "type": "Exercise",
        "name": "Bench Press",
        "exerciseType": "WEIGHT",
        "equipmentId": "EQUIPMENT_0",
        "sets": [
            {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 55.0, "subCategory": "WorkSet"},
        ],
    }

    is_valid, error_message, invalid_weights = validate_equipment_weight_combinations(
        exercise,
        {"EQUIPMENT_0": equipment},
    )

    assert is_valid is False
    assert invalid_weights == [(0, 55.0, "WeightSet")]
    assert exercise["sets"][0]["weight"] == 55.0
    assert "nearest selectable weight: 60.0kg" in error_message


def test_fix_set_errors_backfills_rest_set_subcategory_for_legacy_payloads():
    sets = [
        {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 40.0, "subCategory": "WorkSet"},
        {"id": "SET_1", "type": "RestSet", "timeInSeconds": 45},
    ]

    fixed = fix_set_errors(copy.deepcopy(sets))

    assert fixed[1]["subCategory"] == "WorkSet"
    assert "timeInSeconds" in fixed[1]


def test_placeholder_schema_accepts_alphanumeric_internal_placeholder_ids():
    placeholder_schema = create_placeholder_schema()
    workout_store = {
        "name": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "workouts": [
            {
                "id": "WORKOUT_D1",
                "name": "Day 1",
                "description": "",
                "workoutComponents": [
                    {
                        "id": "EXERCISE_D6",
                        "type": "Exercise",
                        "enabled": True,
                        "name": "Triceps Pushdown",
                        "notes": "",
                        "sets": [
                            {"id": "SET_A0", "type": "WeightSet", "reps": 12, "weight": 10.0, "subCategory": "WorkSet"},
                            {"id": "SET_A1", "type": "RestSet", "timeInSeconds": 45, "subCategory": "WorkSet"},
                            {"id": "SET_A2", "type": "WeightSet", "reps": 12, "weight": 10.0, "subCategory": "WorkSet"},
                        ],
                        "exerciseType": "WEIGHT",
                        "minReps": 10,
                        "maxReps": 15,
                        "equipmentId": None,
                        "bodyWeightPercentage": None,
                        "generateWarmUpSets": False,
                        "progressionMode": "DOUBLE_PROGRESSION",
                        "keepScreenOn": False,
                        "showCountDownTimer": False,
                        "intraSetRestInSeconds": None,
                        "muscleGroups": ["FRONT_TRICEPS"],
                        "secondaryMuscleGroups": [],
                        "requiredAccessoryEquipmentIds": [],
                        "requiresLoadCalibration": True,
                        "exerciseCategory": "ISOLATION",
                    }
                ],
                "order": 0,
                "enabled": True,
                "usePolarDevice": False,
                "creationDate": "2026-05-10",
                "previousVersionId": None,
                "nextVersionId": None,
                "isActive": True,
                "timesCompletedInAWeek": None,
                "globalId": "WORKOUT_D1_GLOBAL",
                "type": 0,
                "workoutPlanId": None,
            }
        ],
    }

    validate(instance=workout_store, schema=placeholder_schema)


class _FakeValidationError:
    def __init__(self, absolute_path, validator, message):
        self.absolute_path = absolute_path
        self.validator = validator
        self.message = message


def test_placeholder_schema_accepts_underscore_suffixes_in_set_ids():
    placeholder_schema = create_placeholder_schema()
    validate(
        instance={"id": "SET_D3_0"},
        schema={"type": "object", "properties": {"id": placeholder_schema["$defs"]["UUID"]}, "required": ["id"]},
    )


def test_patch_scope_allows_set_level_repairs_from_field_level_errors():
    errors = [
        _FakeValidationError(
            ["workouts", 3, "workoutComponents", 4, "sets", 1, "id"],
            "pattern",
            "'SET_D3_1' does not match placeholder pattern",
        ),
        _FakeValidationError(
            ["workouts", 3, "workoutComponents", 4, "sets", 1],
            "required",
            "'timeInSeconds' is a required property",
        ),
    ]

    allowed_paths, allowed_descendants = build_allowed_patch_scope(errors)

    validate_patch_operations_scope(
        [{"op": "replace", "path": "/workouts/3/workoutComponents/4/sets/1/id", "value": "SET_D3_1"}],
        allowed_paths,
        allowed_descendants,
    )


def test_contract_rejects_non_canonical_set_placeholder_ids():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Bench Press",
                "exerciseType": "WEIGHT",
                "requiredAccessoryEquipmentIds": [],
            }
        ],
        "workouts": [],
    }
    exercise_definitions = {
        "EXERCISE_0": {
            "id": "EXERCISE_0",
            "name": "Bench Press",
            "exerciseType": "WEIGHT",
            "minReps": 6,
            "maxReps": 8,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_D3_0", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"},
            ],
        }
    }

    try:
        validate_exercise_definitions_contract(plan_index, exercise_definitions)
        assert False, "Expected ContractValidationError"
    except ContractValidationError as exc:
        assert "non-canonical set id 'SET_D3_0'" in str(exc)


def test_contract_allows_reusing_set_placeholders_across_different_exercises():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Bench Press",
                "exerciseType": "WEIGHT",
                "requiredAccessoryEquipmentIds": [],
            },
            {
                "id": "EXERCISE_1",
                "name": "Row",
                "exerciseType": "WEIGHT",
                "requiredAccessoryEquipmentIds": [],
            },
        ],
        "workouts": [],
    }
    exercise_definitions = {
        "EXERCISE_0": {
            "id": "EXERCISE_0",
            "name": "Bench Press",
            "exerciseType": "WEIGHT",
            "minReps": 6,
            "maxReps": 8,
            "progressionMode": "OFF",
            "requiresLoadCalibration": False,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"},
            ],
        },
        "EXERCISE_1": {
            "id": "EXERCISE_1",
            "name": "Row",
            "exerciseType": "WEIGHT",
            "minReps": 8,
            "maxReps": 10,
            "progressionMode": "OFF",
            "requiresLoadCalibration": False,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_0", "type": "WeightSet", "reps": 10, "weight": 40.0, "subCategory": "WorkSet"},
            ],
        },
    }

    validate_exercise_definitions_contract(plan_index, exercise_definitions)


def test_emit_exercise_definition_retries_until_llm_matches_contract(monkeypatch) -> None:
    responses = iter([
        json.dumps(
            {
                "id": "EXERCISE_0",
                    "type": "Exercise",
                    "enabled": True,
                    "name": "Hip Thrust",
                    "notes": "",
                    "exerciseType": "WEIGHT",
                    "minReps": 8,
                    "maxReps": 10,
                "equipmentId": "EQUIPMENT_0",
                "muscleGroups": ["GLUTES"],
                "secondaryMuscleGroups": [],
                "bodyWeightPercentage": None,
                "generateWarmUpSets": False,
                "progressionMode": "OFF",
                "keepScreenOn": False,
                "showCountDownTimer": False,
                "intraSetRestInSeconds": None,
                "requiresLoadCalibration": False,
                "requiredAccessoryEquipmentIds": [],
                "exerciseCategory": "MODERATE_COMPOUND",
                "sets": [
                    {"id": "SET_0", "type": "WeightSet", "reps": 10, "weight": 20.0, "subCategory": "WorkSet"},
                ],
            }
        ),
        json.dumps(
            {
                "id": "EXERCISE_0",
                    "type": "Exercise",
                    "enabled": True,
                    "name": "Hip Thrust",
                    "notes": "",
                    "exerciseType": "WEIGHT",
                    "minReps": 8,
                    "maxReps": 12,
                "equipmentId": "EQUIPMENT_0",
                "muscleGroups": ["GLUTES"],
                "secondaryMuscleGroups": [],
                "bodyWeightPercentage": None,
                "generateWarmUpSets": False,
                "progressionMode": "OFF",
                "keepScreenOn": False,
                "showCountDownTimer": False,
                "intraSetRestInSeconds": None,
                "requiresLoadCalibration": False,
                "requiredAccessoryEquipmentIds": [],
                "exerciseCategory": "MODERATE_COMPOUND",
                "sets": [
                    {"id": "SET_0", "type": "WeightSet", "reps": 10, "weight": 20.0, "subCategory": "WorkSet"},
                ],
            }
        ),
    ])
    captured_messages = []

    def fake_reasoner(client, messages, custom_prompt, show_loading=False, logger=None):
        captured_messages.append(messages)
        return next(responses)

    monkeypatch.setattr(cli, "json_call_reasoner_only_with_loading", fake_reasoner)

    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Hip Thrust",
                "exerciseType": "WEIGHT",
                "minReps": 8,
                "maxReps": 12,
                "equipmentId": "EQUIPMENT_0",
                "requiredAccessoryEquipmentIds": [],
            }
        ],
        "workouts": [],
    }
    equipment_subset = [{"id": "EQUIPMENT_0", "type": "BARBELL", "barWeight": 20.0, "availablePlates": []}]

    result, _ = cli.emit_exercise_definition(
        "EXERCISE_0",
        client=None,
        context_summary="summary",
        plan_index=plan_index,
        equipment_subset=equipment_subset,
        accessory_subset=None,
        use_reasoner=True,
        provided_equipment=None,
        logger=None,
    )

    assert result["maxReps"] == 12
    assert len(captured_messages) == 1


def test_emit_exercise_definition_prompt_makes_unilateral_mapping_explicit(monkeypatch) -> None:
    captured_messages = []

    def fake_reasoner(client, messages, custom_prompt, show_loading=False, logger=None):
        captured_messages.append(messages)
        return json.dumps(
            {
                "id": "EXERCISE_0",
                "type": "Exercise",
                "enabled": True,
                "name": "Single Arm Press",
                "notes": "",
                "exerciseType": "WEIGHT",
                "minReps": 8,
                "maxReps": 12,
                "equipmentId": "EQUIPMENT_0",
                "muscleGroups": ["FRONT_DELTOIDS"],
                "secondaryMuscleGroups": [],
                "bodyWeightPercentage": None,
                "generateWarmUpSets": False,
                "progressionMode": "OFF",
                "keepScreenOn": False,
                "showCountDownTimer": False,
                "intraSetRestInSeconds": 15,
                "requiresLoadCalibration": False,
                "requiredAccessoryEquipmentIds": [],
                "sets": [
                    {"id": "SET_0", "type": "WeightSet", "reps": 10, "weight": 20.0, "subCategory": "WorkSet"},
                ],
            }
        )

    monkeypatch.setattr(cli, "json_call_reasoner_only_with_loading", fake_reasoner)

    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Single Arm Press",
                "exerciseType": "WEIGHT",
                "minReps": 8,
                "maxReps": 12,
                "equipmentId": "EQUIPMENT_0",
                "requiredAccessoryEquipmentIds": [],
            }
        ],
        "workouts": [],
    }
    equipment_subset = [{"id": "EQUIPMENT_0", "type": "DUMBBELL", "dumbbells": [{"weight": 20.0}], "maxExtraWeightsPerLoadingPoint": 0}]

    cli.emit_exercise_definition(
        "EXERCISE_0",
        client=None,
        context_summary="summary",
        plan_index=plan_index,
        equipment_subset=equipment_subset,
        accessory_subset=None,
        use_reasoner=True,
        provided_equipment=None,
        logger=None,
    )

    prompt = captured_messages[0][-1]["content"]
    assert "Set unilateral intent explicitly through intraSetRestInSeconds." in prompt
    assert "intraSetRestInSeconds means the rest in whole seconds between the two sides of one logical unilateral set" in prompt
    assert "If this is unilateral single-side work, set intraSetRestInSeconds to that positive integer side-to-side rest value." in prompt
    assert "If this is not unilateral, set intraSetRestInSeconds to null." in prompt


def test_emit_exercise_definition_prompt_explicitly_requires_null_equipment_id(monkeypatch) -> None:
    captured_messages = []

    def fake_reasoner(client, messages, custom_prompt, show_loading=False, logger=None):
        captured_messages.append(messages)
        return json.dumps(
            {
                "id": "EXERCISE_0",
                "type": "Exercise",
                "enabled": True,
                "name": "Row",
                "notes": "",
                "exerciseType": "BODY_WEIGHT",
                "minReps": 8,
                "maxReps": 12,
                "equipmentId": None,
                "muscleGroups": ["BACK_UPPER_BACK"],
                "secondaryMuscleGroups": [],
                "bodyWeightPercentage": 100.0,
                "generateWarmUpSets": False,
                "progressionMode": "OFF",
                "keepScreenOn": False,
                "showCountDownTimer": False,
                "intraSetRestInSeconds": None,
                "requiresLoadCalibration": False,
                "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
                "sets": [
                    {"id": "SET_0", "type": "BodyWeightSet", "reps": 10, "additionalWeight": 0.0, "subCategory": "WorkSet"},
                ],
            }
        )

    monkeypatch.setattr(cli, "json_call_reasoner_only_with_loading", fake_reasoner)

    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Row",
                "exerciseType": "BODY_WEIGHT",
                "minReps": 8,
                "maxReps": 12,
                "equipmentId": None,
                "bodyWeightPercentage": 100.0,
                "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
            }
        ],
        "workouts": [],
    }
    accessory_subset = [{"id": "ACCESSORY_0", "type": "ACCESSORY", "name": "Rings"}]

    cli.emit_exercise_definition(
        "EXERCISE_0",
        client=None,
        context_summary="summary",
        plan_index=plan_index,
        equipment_subset=[],
        accessory_subset=accessory_subset,
        use_reasoner=True,
        provided_equipment=None,
        logger=None,
    )

    prompt = captured_messages[0][-1]["content"]
    assert "Set equipmentId EXACTLY to null." in prompt
    assert "Do not infer or invent a primary equipmentId from accessories, movement name, or context." in prompt


def test_emit_exercise_definition_prompt_uses_weight_specific_schema(monkeypatch) -> None:
    captured_messages = []

    def fake_reasoner(client, messages, custom_prompt, show_loading=False, logger=None):
        captured_messages.append(messages)
        return json.dumps(
            {
                "id": "EXERCISE_0",
                "type": "Exercise",
                "enabled": True,
                "name": "Bench Press",
                "notes": "",
                "exerciseType": "WEIGHT",
                "minReps": 6,
                "maxReps": 8,
                "equipmentId": "EQUIPMENT_0",
                "bodyWeightPercentage": None,
                "generateWarmUpSets": True,
                "progressionMode": "AUTO_REGULATION",
                "keepScreenOn": False,
                "showCountDownTimer": False,
                "intraSetRestInSeconds": None,
                "muscleGroups": ["FRONT_CHEST"],
                "secondaryMuscleGroups": [],
                "requiredAccessoryEquipmentIds": [],
                "requiresLoadCalibration": False,
                "exerciseCategory": "HEAVY_COMPOUND",
                "sets": [
                    {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 20.0, "subCategory": "WorkSet"},
                ],
            }
        )

    monkeypatch.setattr(cli, "json_call_reasoner_only_with_loading", fake_reasoner)

    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Bench Press",
                "exerciseType": "WEIGHT",
                "minReps": 6,
                "maxReps": 8,
                "equipmentId": "EQUIPMENT_0",
                "requiredAccessoryEquipmentIds": [],
            }
        ],
        "workouts": [],
    }

    cli.emit_exercise_definition(
        "EXERCISE_0",
        client=None,
        context_summary="summary",
        plan_index=plan_index,
        equipment_subset=[{"id": "EQUIPMENT_0", "type": "BARBELL", "barWeight": 20.0, "availablePlates": []}],
        accessory_subset=None,
        use_reasoner=True,
        provided_equipment=None,
        logger=None,
    )

    prompt = captured_messages[0][-1]["content"]
    assert "WEIGHT contract:" in prompt
    assert "Allowed work-set type for this WEIGHT object: WeightSet." in prompt
    assert "Forbidden fields on each WeightSet: additionalWeight, timeInMillis, timeInSeconds, autoStart, autoStop." in prompt
    assert "\"exerciseType\": {" in prompt
    assert "\"const\": \"WEIGHT\"" in prompt


def test_weight_schema_rejects_bodyweight_fields():
    with pytest.raises(ValidationError):
        validate(
            instance={
                "id": "EXERCISE_0",
                "type": "Exercise",
                "enabled": True,
                "name": "Bench Press",
                "notes": "",
                "sets": [
                    {
                        "id": "SET_0",
                        "type": "WeightSet",
                        "reps": 8,
                        "weight": 60.0,
                        "additionalWeight": 5.0,
                        "subCategory": "WorkSet",
                    }
                ],
                "exerciseType": "WEIGHT",
                "minReps": 6,
                "maxReps": 8,
                "equipmentId": "EQUIPMENT_0",
                "bodyWeightPercentage": None,
                "generateWarmUpSets": True,
                "progressionMode": "AUTO_REGULATION",
                "keepScreenOn": False,
                "showCountDownTimer": False,
                "intraSetRestInSeconds": None,
                "muscleGroups": ["FRONT_CHEST"],
                "secondaryMuscleGroups": [],
                "requiredAccessoryEquipmentIds": [],
                "requiresLoadCalibration": False,
                "exerciseCategory": "HEAVY_COMPOUND",
            },
            schema=WEIGHT_EXERCISE_SCHEMA,
        )


def test_bodyweight_schema_requires_bodyweight_percentage():
    with pytest.raises(ValidationError):
        validate(
            instance={
                "id": "EXERCISE_0",
                "type": "Exercise",
                "enabled": True,
                "name": "Pull-Up",
                "notes": "",
                "sets": [
                    {"id": "SET_0", "type": "BodyWeightSet", "reps": 8, "additionalWeight": 5.0, "subCategory": "WorkSet"},
                ],
                "exerciseType": "BODY_WEIGHT",
                "minReps": 6,
                "maxReps": 8,
                "equipmentId": None,
                "bodyWeightPercentage": None,
                "generateWarmUpSets": False,
                "progressionMode": "AUTO_REGULATION",
                "keepScreenOn": False,
                "showCountDownTimer": False,
                "intraSetRestInSeconds": None,
                "muscleGroups": ["BACK_UPPER_BACK"],
                "secondaryMuscleGroups": [],
                "requiredAccessoryEquipmentIds": [],
                "requiresLoadCalibration": False,
                "exerciseCategory": "MODERATE_COMPOUND",
            },
            schema=BODY_WEIGHT_EXERCISE_SCHEMA,
        )


def test_countdown_schema_allows_multiple_timed_sets_with_rest():
    validate(
        instance={
            "id": "EXERCISE_WARMUP",
            "type": "Exercise",
            "enabled": True,
            "name": "Warm Up",
            "notes": "",
            "sets": [
                {"id": "SET_WARMUP", "type": "TimedDurationSet", "timeInMillis": 300000, "autoStart": True, "autoStop": True},
                {"id": "SET_1", "type": "RestSet", "timeInSeconds": 60, "subCategory": "WorkSet"},
                {"id": "SET_2", "type": "TimedDurationSet", "timeInMillis": 300000, "autoStart": True, "autoStop": True},
            ],
            "exerciseType": "COUNTDOWN",
            "equipmentId": None,
            "bodyWeightPercentage": None,
            "generateWarmUpSets": False,
            "progressionMode": "OFF",
            "keepScreenOn": False,
            "showCountDownTimer": True,
            "intraSetRestInSeconds": None,
            "muscleGroups": ["FRONT_QUADRICEPS"],
            "secondaryMuscleGroups": [],
            "requiredAccessoryEquipmentIds": [],
            "requiresLoadCalibration": False,
            "exerciseCategory": None,
        },
        schema=COUNTDOWN_EXERCISE_SCHEMA,
    )


def test_countup_schema_rejects_rep_fields():
    with pytest.raises(ValidationError):
        validate(
            instance={
                "id": "EXERCISE_2",
                "type": "Exercise",
                "enabled": True,
                "name": "Air Bike",
                "notes": "",
                "sets": [
                    {"id": "SET_0", "type": "EnduranceSet", "timeInMillis": 60000, "autoStart": True, "autoStop": True},
                ],
                "exerciseType": "COUNTUP",
                "minReps": 6,
                "equipmentId": None,
                "bodyWeightPercentage": None,
                "generateWarmUpSets": False,
                "progressionMode": "OFF",
                "keepScreenOn": False,
                "showCountDownTimer": False,
                "intraSetRestInSeconds": None,
                "muscleGroups": ["FRONT_QUADRICEPS"],
                "secondaryMuscleGroups": [],
                "requiredAccessoryEquipmentIds": [],
                "requiresLoadCalibration": False,
                "exerciseCategory": None,
            },
            schema=COUNTUP_EXERCISE_SCHEMA,
        )


def test_contract_rejects_duplicate_set_placeholders_within_same_exercise():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Bench Press",
                "exerciseType": "WEIGHT",
                "requiredAccessoryEquipmentIds": [],
            }
        ],
        "workouts": [],
    }
    exercise_definitions = {
        "EXERCISE_0": {
            "id": "EXERCISE_0",
            "name": "Bench Press",
            "exerciseType": "WEIGHT",
            "minReps": 6,
            "maxReps": 8,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"},
                {"id": "SET_0", "type": "RestSet", "timeInSeconds": 45, "subCategory": "WorkSet"},
            ],
        }
    }

    try:
        validate_exercise_definitions_contract(plan_index, exercise_definitions)
        assert False, "Expected ContractValidationError"
    except ContractValidationError as exc:
        assert "reuses set id 'SET_0' within the same exercise" in str(exc)


def test_plan_index_accepts_exact_weight_targets_for_weight_exercise():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_0"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Bench Press",
                "exerciseType": "WEIGHT",
                "equipmentId": "EQUIPMENT_0",
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 2,
                "targetSetPrescriptions": [
                    {"workSetIndex": 0, "reps": 8, "weight": 60.0},
                    {"workSetIndex": 1, "reps": 8, "weight": 60.0},
                ],
            }
        ],
        "workouts": [],
    }

    validate_plan_index_contract(plan_index)


def test_plan_index_rejects_exact_target_load_not_selectable_for_provided_equipment():
    provided_equipment = {
        "equipments": [
            {
                "id": "EQUIPMENT_1",
                "type": "DUMBBELLS",
                "name": "Dumbbells",
                "dumbbells": [
                    {"weight": 2.5},
                    {"weight": 2.75},
                    {"weight": 3.0},
                ],
                "extraWeights": [],
                "maxExtraWeightsPerLoadingPoint": 0,
            }
        ],
        "accessoryEquipments": [],
    }
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_1", "type": "DUMBBELLS", "name": "Dumbbells"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_17",
                "name": "DB Lateral Raises",
                "exerciseType": "WEIGHT",
                "equipmentId": "EQUIPMENT_1",
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 3,
                "targetSetPrescriptions": [
                    {"workSetIndex": 0, "reps": 15, "weight": 6.5},
                    {"workSetIndex": 1, "reps": 15, "weight": 6.5},
                    {"workSetIndex": 2, "reps": 15, "weight": 6.5},
                ],
            }
        ],
        "workouts": [],
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_plan_index_contract(plan_index, provided_equipment)

    assert "targetSetPrescriptions[0] weight=6.5 is not selectable for equipment 'Dumbbells' (DUMBBELLS)" in str(exc_info.value)


def test_plan_index_accepts_exact_target_load_for_matching_single_dumbbell_equipment():
    provided_equipment = {
        "equipments": [
            {
                "id": "EQUIPMENT_4",
                "type": "DUMBBELL",
                "name": "Dumbbell",
                "dumbbells": [
                    {"weight": 2.5},
                    {"weight": 2.75},
                    {"weight": 3.0},
                    {"weight": 6.5},
                ],
                "extraWeights": [],
                "maxExtraWeightsPerLoadingPoint": 0,
            }
        ],
        "accessoryEquipments": [],
    }
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_4", "type": "DUMBBELL", "name": "Dumbbell"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_17",
                "name": "DB Lateral Raises",
                "exerciseType": "WEIGHT",
                "equipmentId": "EQUIPMENT_4",
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 3,
                "targetSetPrescriptions": [
                    {"workSetIndex": 0, "reps": 15, "weight": 6.5},
                    {"workSetIndex": 1, "reps": 15, "weight": 6.5},
                    {"workSetIndex": 2, "reps": 15, "weight": 6.5},
                ],
            }
        ],
        "workouts": [],
    }

    validate_plan_index_contract(plan_index, provided_equipment)


def test_exercise_definition_must_match_exact_weight_targets():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_0"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Bench Press",
                "exerciseType": "WEIGHT",
                "equipmentId": "EQUIPMENT_0",
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 2,
                "targetSetPrescriptions": [
                    {"workSetIndex": 0, "reps": 8, "weight": 60.0},
                    {"workSetIndex": 1, "reps": 8, "weight": 60.0},
                ],
            }
        ],
        "workouts": [],
    }
    exercise_definitions = {
        "EXERCISE_0": {
            "id": "EXERCISE_0",
            "name": "Bench Press",
            "exerciseType": "WEIGHT",
            "minReps": 6,
            "maxReps": 8,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 55.0, "subCategory": "WorkSet"},
                {"id": "SET_1", "type": "RestSet", "timeInSeconds": 90, "subCategory": "WorkSet"},
                {"id": "SET_2", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"},
            ],
        }
    }

    try:
        validate_exercise_definitions_contract(plan_index, exercise_definitions)
        assert False, "Expected ContractValidationError"
    except ContractValidationError as exc:
        assert "workSetIndex 0 weight mismatch: expected 60.0, got 55.0" in str(exc)


def test_plan_index_rejects_non_contiguous_target_work_set_indexes():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_0"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Bench Press",
                "exerciseType": "WEIGHT",
                "equipmentId": "EQUIPMENT_0",
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 2,
                "targetSetPrescriptions": [
                    {"workSetIndex": 0, "reps": 8, "weight": 60.0},
                    {"workSetIndex": 2, "reps": 8, "weight": 60.0},
                ],
            }
        ],
        "workouts": [],
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_plan_index_contract(plan_index)

    assert "workSetIndex values must be contiguous 0-based indexes; got [0, 2]" in str(exc_info.value)


def test_plan_index_accepts_explicit_superset_groups_when_contiguous():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {"id": "EXERCISE_WARMUP", "name": "Warm Up", "exerciseType": "COUNTDOWN", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_0", "name": "Calf Raise", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_1", "name": "Lateral Raise", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_2", "name": "Crunch", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
        ],
        "workouts": [
            {
                "id": "WORKOUT_0",
                "name": "Day 1",
                "exerciseIds": ["EXERCISE_WARMUP", "EXERCISE_0", "EXERCISE_1", "EXERCISE_2"],
                "supersetGroups": [{"exerciseIds": ["EXERCISE_0", "EXERCISE_1"]}],
                "restToNextSeconds": [0, 0, 60, 0],
            }
        ],
    }

    validate_plan_index_contract(plan_index)


def test_plan_index_rejects_non_contiguous_superset_groups():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {"id": "EXERCISE_WARMUP", "name": "Warm Up", "exerciseType": "COUNTDOWN", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_0", "name": "Calf Raise", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_1", "name": "Crunch", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_2", "name": "Lateral Raise", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
        ],
        "workouts": [
            {
                "id": "WORKOUT_0",
                "name": "Day 1",
                "exerciseIds": ["EXERCISE_WARMUP", "EXERCISE_0", "EXERCISE_1", "EXERCISE_2"],
                "supersetGroups": [{"exerciseIds": ["EXERCISE_0", "EXERCISE_2"]}],
                "restToNextSeconds": [0, 60, 60, 0],
            }
        ],
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_plan_index_contract(plan_index)

    assert "must appear as a contiguous subsequence of exerciseIds" in str(exc_info.value)


def test_plan_index_rejects_weight_exercise_with_additional_weight_targets():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_2"}],
        "accessoryEquipments": [{"id": "ACCESSORY_4"}],
        "exercises": [
            {
                "id": "EXERCISE_2",
                "name": "Dips",
                "exerciseType": "WEIGHT",
                "equipmentId": "EQUIPMENT_2",
                "requiredAccessoryEquipmentIds": ["ACCESSORY_4"],
                "numWorkSets": 3,
                "targetSetPrescriptions": [
                    {"workSetIndex": 0, "reps": 12, "additionalWeight": 10.0},
                    {"workSetIndex": 1, "reps": 12, "additionalWeight": 10.0},
                    {"workSetIndex": 2, "reps": 12, "additionalWeight": 10.0},
                ],
            }
        ],
        "workouts": [],
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_plan_index_contract(plan_index)

    assert "uses additionalWeight, which does not match this exerciseType. Expected weight instead" in str(exc_info.value)


def test_plan_index_ignores_empty_target_set_prescriptions_for_warm_up():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_WARMUP",
                "name": "Warm Up",
                "exerciseType": "COUNTDOWN",
                "requiredAccessoryEquipmentIds": [],
                "targetSetPrescriptions": [],
            }
        ],
        "workouts": [],
    }

    validate_plan_index_contract(plan_index)


def test_plan_index_rejects_non_positive_num_work_sets_for_timed_exercises():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Bike Intervals",
                "exerciseType": "COUNTDOWN",
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 0,
            }
        ],
        "workouts": [],
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_plan_index_contract(plan_index)

    assert "positive integer numWorkSets" in str(exc_info.value)


def test_countdown_warm_up_with_single_timed_set_does_not_trigger_work_set_mismatch():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_WARMUP",
                "name": "Warm Up",
                "exerciseType": "COUNTDOWN",
                "requiredAccessoryEquipmentIds": [],
                # Plan index often uses numWorkSets=1 for the single timed block; Step 3 must not
                # mis-compare that to WeightSet-style counts (regression guard).
                "numWorkSets": 1,
            }
        ],
        "workouts": [],
    }
    exercise_definitions = {
        "EXERCISE_WARMUP": {
            "id": "EXERCISE_WARMUP",
            "name": "Warm Up",
            "exerciseType": "COUNTDOWN",
            "progressionMode": "OFF",
            "requiresLoadCalibration": False,
            "showCountDownTimer": True,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_WARMUP", "type": "TimedDurationSet", "timeInMillis": 300000},
            ],
        }
    }

    validate_exercise_definitions_contract(plan_index, exercise_definitions)


def test_countdown_warm_up_accepts_multiple_timed_sets_with_rest():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_WARMUP",
                "name": "Warm Up",
                "exerciseType": "COUNTDOWN",
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 2,
                "restBetweenSetsSeconds": 60,
            }
        ],
        "workouts": [],
    }
    exercise_definitions = {
        "EXERCISE_WARMUP": {
            "id": "EXERCISE_WARMUP",
            "name": "Warm Up",
            "exerciseType": "COUNTDOWN",
            "progressionMode": "OFF",
            "requiresLoadCalibration": False,
            "showCountDownTimer": True,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_0", "type": "TimedDurationSet", "timeInMillis": 300000, "autoStart": True, "autoStop": True},
                {"id": "SET_1", "type": "RestSet", "timeInSeconds": 60, "subCategory": "WorkSet"},
                {"id": "SET_2", "type": "TimedDurationSet", "timeInMillis": 300000, "autoStart": True, "autoStop": True},
            ],
        }
    }

    validate_exercise_definitions_contract(plan_index, exercise_definitions)


def test_countup_rejects_rep_range_fields_and_enforces_rest_values():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Air Bike",
                "exerciseType": "COUNTUP",
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 2,
                "restBetweenSetsSeconds": 30,
            }
        ],
        "workouts": [],
    }
    exercise_definitions = {
        "EXERCISE_0": {
            "id": "EXERCISE_0",
            "name": "Air Bike",
            "exerciseType": "COUNTUP",
            "minReps": 6,
            "progressionMode": "OFF",
            "requiresLoadCalibration": False,
            "showCountDownTimer": False,
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_0", "type": "EnduranceSet", "timeInMillis": 60000, "autoStart": True, "autoStop": True},
                {"id": "SET_1", "type": "RestSet", "timeInSeconds": 20, "subCategory": "WorkSet"},
                {"id": "SET_2", "type": "EnduranceSet", "timeInMillis": 60000, "autoStart": True, "autoStop": True},
            ],
        }
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_exercise_definitions_contract(plan_index, exercise_definitions)

    assert "must not emit minReps or maxReps for timed exercises" in str(exc_info.value)
    assert "expected all 30" in str(exc_info.value)


def test_exercise_definition_rejects_body_weight_without_percentage():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_0"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Push-Up",
                "exerciseType": "BODY_WEIGHT",
                "equipmentId": "EQUIPMENT_0",
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 2,
            }
        ],
        "workouts": [],
    }
    exercise_definitions = {
        "EXERCISE_0": {
            "id": "EXERCISE_0",
            "name": "Push-Up",
            "exerciseType": "BODY_WEIGHT",
            "minReps": 10,
            "maxReps": 15,
            "bodyWeightPercentage": None,
            "progressionMode": "AUTO_REGULATION",
            "requiresLoadCalibration": False,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_0", "type": "BodyWeightSet", "reps": 12, "additionalWeight": 5.0, "subCategory": "WorkSet"},
                {"id": "SET_1", "type": "RestSet", "timeInSeconds": 60, "subCategory": "WorkSet"},
                {"id": "SET_2", "type": "BodyWeightSet", "reps": 12, "additionalWeight": 5.0, "subCategory": "WorkSet"},
            ],
        }
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_exercise_definitions_contract(plan_index, exercise_definitions)

    assert "must include a positive numeric bodyWeightPercentage" in str(exc_info.value)


def test_plan_index_rejects_body_weight_without_percentage():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_0"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Push-Up",
                "exerciseType": "BODY_WEIGHT",
                "equipmentId": "EQUIPMENT_0",
                "bodyWeightPercentage": None,
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 2,
            }
        ],
        "workouts": [],
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_plan_index_contract(plan_index)

    assert "must include a positive numeric bodyWeightPercentage in percentage form in the PlanIndex" in str(exc_info.value)


def test_plan_index_rejects_fractional_body_weight_percentage():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_0"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Pull-Up",
                "exerciseType": "BODY_WEIGHT",
                "equipmentId": "EQUIPMENT_0",
                "bodyWeightPercentage": 1.0,
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 2,
            }
        ],
        "workouts": [],
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_plan_index_contract(plan_index)

    assert "100.0, not 1.0" in str(exc_info.value)


def test_plan_index_rejects_weighted_bodyweight_with_missing_primary_equipment_id():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [
            {
                "id": "EQUIPMENT_2",
                "type": "WEIGHTVEST",
                "name": "Weight Vest",
                "availableWeights": [{"weight": 5.0}, {"weight": 10.0}],
            }
        ],
        "accessoryEquipments": [{"id": "ACCESSORY_0", "type": "ACCESSORY", "name": "Pull-Up Bar"}],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Weighted Pull-Up",
                "exerciseType": "BODY_WEIGHT",
                "equipmentId": None,
                "bodyWeightPercentage": 100.0,
                "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
                "numWorkSets": 2,
                "minReps": 6,
                "maxReps": 8,
                "targetSetPrescriptions": [
                    {"workSetIndex": 0, "reps": 6, "additionalWeight": 10.0},
                    {"workSetIndex": 1, "reps": 6, "additionalWeight": 10.0},
                ],
            }
        ],
        "workouts": [],
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_plan_index_contract(plan_index)

    assert "missing_plan_bodyweight_equipment_id" in str(exc_info.value)
    assert "set equipmentId to the correct primary load-bearing equipment instead of null" in str(exc_info.value)


def test_plan_index_accepts_weighted_bodyweight_with_matching_primary_equipment_id():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [
            {
                "id": "EQUIPMENT_2",
                "type": "WEIGHTVEST",
                "name": "Weight Vest",
                "availableWeights": [{"weight": 5.0}, {"weight": 10.0}],
            }
        ],
        "accessoryEquipments": [{"id": "ACCESSORY_0", "type": "ACCESSORY", "name": "Dip Bars"}],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Weighted Dip",
                "exerciseType": "BODY_WEIGHT",
                "equipmentId": "EQUIPMENT_2",
                "bodyWeightPercentage": 100.0,
                "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
                "numWorkSets": 2,
                "minReps": 8,
                "maxReps": 12,
                "targetSetPrescriptions": [
                    {"workSetIndex": 0, "reps": 10, "additionalWeight": 10.0},
                    {"workSetIndex": 1, "reps": 10, "additionalWeight": 10.0},
                ],
            }
        ],
        "workouts": [],
    }

    validate_plan_index_contract(plan_index)


def test_plan_index_rejects_weighted_bodyweight_with_non_matching_primary_equipment_id():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [
            {
                "id": "EQUIPMENT_1",
                "type": "DUMBBELL",
                "name": "Single Dumbbell",
                "dumbbells": [{"weight": 7.0}],
                "extraWeights": [],
                "maxExtraWeightsPerLoadingPoint": 0,
            },
            {
                "id": "EQUIPMENT_2",
                "type": "WEIGHTVEST",
                "name": "Weight Vest",
                "availableWeights": [{"weight": 5.0}, {"weight": 10.0}],
            },
        ],
        "accessoryEquipments": [{"id": "ACCESSORY_0", "type": "ACCESSORY", "name": "Rings"}],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Weighted Ring Row",
                "exerciseType": "BODY_WEIGHT",
                "equipmentId": "EQUIPMENT_1",
                "bodyWeightPercentage": 65.0,
                "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
                "numWorkSets": 2,
                "minReps": 8,
                "maxReps": 12,
                "targetSetPrescriptions": [
                    {"workSetIndex": 0, "reps": 10, "additionalWeight": 10.0},
                    {"workSetIndex": 1, "reps": 10, "additionalWeight": 10.0},
                ],
            }
        ],
        "workouts": [],
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_plan_index_contract(plan_index)

    assert "bodyweight_equipment_id_target_mismatch" in str(exc_info.value)
    assert "expected one of ['EQUIPMENT_2']" in str(exc_info.value)


def test_exercise_definition_rejects_fractional_body_weight_percentage():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_0"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Push-Up",
                "exerciseType": "BODY_WEIGHT",
                "equipmentId": "EQUIPMENT_0",
                "bodyWeightPercentage": 100.0,
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 2,
            }
        ],
        "workouts": [],
    }
    exercise_definitions = {
        "EXERCISE_0": {
            "id": "EXERCISE_0",
            "name": "Push-Up",
            "exerciseType": "BODY_WEIGHT",
            "minReps": 10,
            "maxReps": 15,
            "bodyWeightPercentage": 1.0,
            "progressionMode": "AUTO_REGULATION",
            "requiresLoadCalibration": False,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_0", "type": "BodyWeightSet", "reps": 12, "additionalWeight": 5.0, "subCategory": "WorkSet"},
                {"id": "SET_1", "type": "RestSet", "timeInSeconds": 60, "subCategory": "WorkSet"},
                {"id": "SET_2", "type": "BodyWeightSet", "reps": 12, "additionalWeight": 5.0, "subCategory": "WorkSet"},
            ],
        }
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_exercise_definitions_contract(plan_index, exercise_definitions)

    assert "100.0 for full bodyweight, not 1.0" in str(exc_info.value)


def test_workout_structure_contract_rejects_missing_required_superset_group():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {"id": "EXERCISE_WARMUP", "name": "Warm Up", "exerciseType": "COUNTDOWN", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_0", "name": "Calf Raise", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_1", "name": "Lateral Raise", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_2", "name": "Crunch", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
        ],
        "workouts": [
            {
                "id": "WORKOUT_0",
                "name": "Day 1",
                "exerciseIds": ["EXERCISE_WARMUP", "EXERCISE_0", "EXERCISE_1", "EXERCISE_2"],
                "supersetGroups": [{"exerciseIds": ["EXERCISE_0", "EXERCISE_1"]}],
                "restToNextSeconds": [0, 0, 60, 0],
            }
        ],
    }
    exercise_definitions = {
        "EXERCISE_WARMUP": {"id": "EXERCISE_WARMUP"},
        "EXERCISE_0": {"id": "EXERCISE_0"},
        "EXERCISE_1": {"id": "EXERCISE_1"},
        "EXERCISE_2": {"id": "EXERCISE_2"},
    }
    workout_structures = {
        "WORKOUT_0": {
            "workoutMetadata": {"name": "Day 1"},
            "workoutComponents": [
                {"componentType": "Exercise", "exerciseId": "EXERCISE_WARMUP", "enabled": True},
                {"componentType": "Exercise", "exerciseId": "EXERCISE_0", "enabled": True},
                {"componentType": "Exercise", "exerciseId": "EXERCISE_1", "enabled": True},
                {"componentType": "Rest", "enabled": True, "timeInSeconds": 60},
                {"componentType": "Exercise", "exerciseId": "EXERCISE_2", "enabled": True},
            ],
        }
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_workout_structures_contract(plan_index, workout_structures, exercise_definitions)

    assert "superset groups mismatch" in str(exc_info.value)


def test_workout_structure_contract_accepts_matching_superset_group():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [],
        "accessoryEquipments": [],
        "exercises": [
            {"id": "EXERCISE_WARMUP", "name": "Warm Up", "exerciseType": "COUNTDOWN", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_0", "name": "Calf Raise", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_1", "name": "Lateral Raise", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
            {"id": "EXERCISE_2", "name": "Crunch", "exerciseType": "WEIGHT", "requiredAccessoryEquipmentIds": []},
        ],
        "workouts": [
            {
                "id": "WORKOUT_0",
                "name": "Day 1",
                "exerciseIds": ["EXERCISE_WARMUP", "EXERCISE_0", "EXERCISE_1", "EXERCISE_2"],
                "supersetGroups": [{"exerciseIds": ["EXERCISE_0", "EXERCISE_1"]}],
                "restToNextSeconds": [0, 0, 60, 0],
            }
        ],
    }
    exercise_definitions = {
        "EXERCISE_WARMUP": {"id": "EXERCISE_WARMUP"},
        "EXERCISE_0": {"id": "EXERCISE_0"},
        "EXERCISE_1": {"id": "EXERCISE_1"},
        "EXERCISE_2": {"id": "EXERCISE_2"},
    }
    workout_structures = {
        "WORKOUT_0": {
            "workoutMetadata": {"name": "Day 1"},
            "workoutComponents": [
                {"componentType": "Exercise", "exerciseId": "EXERCISE_WARMUP", "enabled": True},
                {
                    "componentType": "Superset",
                    "enabled": True,
                    "exerciseIds": ["EXERCISE_0", "EXERCISE_1"],
                    "restSecondsByExercise": {"EXERCISE_0": 0, "EXERCISE_1": 60},
                },
                {"componentType": "Exercise", "exerciseId": "EXERCISE_2", "enabled": True},
            ],
        }
    }

    validate_workout_structures_contract(plan_index, workout_structures, exercise_definitions)


def test_placeholder_id_manager_converts_rest_seconds_by_exercise_map_keys_to_uuids():
    id_manager = PlaceholderIdManager()
    id_manager.register_placeholder("WORKOUT_0")
    id_manager.register_placeholder("COMPONENT_0")
    ex0_uuid = id_manager.get_uuid("EXERCISE_0")
    ex1_uuid = id_manager.get_uuid("EXERCISE_1")

    placeholder_store = {
        "workouts": [
            {
                "id": "WORKOUT_0",
                "workoutComponents": [
                    {
                        "id": "COMPONENT_0",
                        "type": "Superset",
                        "enabled": True,
                        "exercises": [
                            {"id": "EXERCISE_0", "type": "Exercise", "enabled": True},
                            {"id": "EXERCISE_1", "type": "Exercise", "enabled": True},
                        ],
                        "restSecondsByExercise": {
                            "EXERCISE_0": 0,
                            "EXERCISE_1": 60,
                        },
                    }
                ],
            }
        ]
    }

    uuid_store = id_manager.replace_placeholders(placeholder_store)
    rest_map = uuid_store["workouts"][0]["workoutComponents"][0]["restSecondsByExercise"]

    assert ex0_uuid in rest_map
    assert ex1_uuid in rest_map
    assert "EXERCISE_0" not in rest_map
    assert "EXERCISE_1" not in rest_map
    assert rest_map[ex0_uuid] == 0
    assert rest_map[ex1_uuid] == 60


def test_normalize_custom_prompt_equipment_ids_rewrites_uuid_references_to_placeholders():
    custom_prompt = (
        "EQUIPMENT AVAILABLE (use these exact IDs):\n"
        "- Barbell - ID: a247d19d-e625-4c84-af6a-f643bb1d076c\n"
        "- Pull-Up Bar - ID: 49405aae-8e6d-4364-8bd5-cb551fb97631\n"
    )

    normalized = _normalize_custom_prompt_equipment_ids(
        custom_prompt,
        {
            "a247d19d-e625-4c84-af6a-f643bb1d076c": "EQUIPMENT_0",
            "49405aae-8e6d-4364-8bd5-cb551fb97631": "ACCESSORY_3",
        },
    )

    assert "use these exact placeholder IDs" in normalized
    assert "a247d19d-e625-4c84-af6a-f643bb1d076c" not in normalized
    assert "49405aae-8e6d-4364-8bd5-cb551fb97631" not in normalized
    assert "EQUIPMENT_0" in normalized
    assert "ACCESSORY_3" in normalized


def test_normalize_custom_prompt_equipment_ids_leaves_unrelated_prompts_unchanged():
    custom_prompt = "Generate a 3-day full body plan under 60 minutes."

    normalized = _normalize_custom_prompt_equipment_ids(custom_prompt, {})

    assert normalized == custom_prompt


def test_exercise_definition_rejects_double_progression_mode():
    plan_index = {
        "planName": "Test Plan",
        "equipments": [{"id": "EQUIPMENT_0"}],
        "accessoryEquipments": [],
        "exercises": [
            {
                "id": "EXERCISE_0",
                "name": "Bench Press",
                "exerciseType": "WEIGHT",
                "equipmentId": "EQUIPMENT_0",
                "requiredAccessoryEquipmentIds": [],
                "numWorkSets": 2,
            }
        ],
        "workouts": [],
    }
    exercise_definitions = {
        "EXERCISE_0": {
            "id": "EXERCISE_0",
            "name": "Bench Press",
            "exerciseType": "WEIGHT",
            "minReps": 6,
            "maxReps": 8,
            "progressionMode": "DOUBLE_PROGRESSION",
            "requiresLoadCalibration": False,
            "requiredAccessoryEquipmentIds": [],
            "sets": [
                {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"},
                {"id": "SET_1", "type": "RestSet", "timeInSeconds": 90, "subCategory": "WorkSet"},
                {"id": "SET_2", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"},
            ],
        }
    }

    with pytest.raises(ContractValidationError) as exc_info:
        validate_exercise_definitions_contract(plan_index, exercise_definitions)

    assert "progressionMode must be OFF or AUTO_REGULATION, got 'DOUBLE_PROGRESSION'" in str(exc_info.value)


def test_sync_exercises_from_plan_index_does_not_apply_reps_to_countdown():
    """COUNTDOWN/COUNTUP ignore minReps/maxReps in PlanIndex; sanitizer drops keys (including null)."""
    from workout_generator_pkg.domain_ops import strip_rep_range_fields_for_timed_exercises_in_workout_store

    workout_store = {
        "workouts": [
            {
                "workoutComponents": [
                    {
                        "id": "EXERCISE_WARMUP",
                        "type": "Exercise",
                        "exerciseType": "COUNTDOWN",
                    }
                ]
            }
        ]
    }
    plan_index = {
        "exercises": [
            {
                "id": "EXERCISE_WARMUP",
                "exerciseType": "COUNTDOWN",
                "minReps": None,
                "maxReps": None,
            }
        ]
    }
    out = sync_exercises_from_plan_index(copy.deepcopy(workout_store), plan_index)
    strip_rep_range_fields_for_timed_exercises_in_workout_store(out)
    ex = out["workouts"][0]["workoutComponents"][0]
    assert "minReps" not in ex
    assert "maxReps" not in ex


def test_sanitize_rep_range_removes_explicit_null_on_countdown():
    from workout_generator_pkg.domain_ops import sanitize_rep_range_fields_on_exercise_dict

    ex = {"exerciseType": "COUNTDOWN", "minReps": None, "maxReps": None}
    sanitize_rep_range_fields_on_exercise_dict(ex)
    assert "minReps" not in ex
    assert "maxReps" not in ex
