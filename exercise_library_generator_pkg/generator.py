from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import httpx
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as validate_json_schema
from openai import OpenAI

from workout_generator_pkg.api_client import (
    json_call_chat_max_with_loading,
    json_call_reasoner_only_with_loading,
)
from workout_generator_pkg.cli import load_equipment_from_file, test_connection
from workout_generator_pkg.constants import EXACT_GENERATION_CONFIRMATION
from workout_generator_pkg.domain_ops import (
    build_exercise_definition_id,
    fix_muscle_groups,
    format_equipment_for_llm,
)
from workout_generator_pkg.interactive_shell import _resolve_api_key
from workout_generator_pkg.json_patching import (
    apply_json_patch,
    collect_changed_json_paths,
    validate_changed_paths_scope,
    validate_patch_operations_scope,
)


EXERCISE_TYPES = {"WEIGHT", "BODY_WEIGHT", "COUNTDOWN", "COUNTUP"}
EXERCISE_CATEGORIES = {"HEAVY_COMPOUND", "MODERATE_COMPOUND", "ISOLATION"}
EXECUTION_MODES = {"REPETITIONS", "TARGET_DURATION", "OPEN_DURATION"}
RESISTANCE_MODES = {"BODY_WEIGHT", "EXTERNAL_LOAD", "BODY_WEIGHT_PLUS_LOAD"}
JOINT_DEMANDS = {"SINGLE_JOINT", "MULTI_JOINT", "STATIC_OR_CYCLIC"}
LOADING_DEMANDS = {"LOW", "MODERATE", "HIGH"}
INVENTORY_CANDIDATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "name",
        "exerciseType",
        "equipmentId",
        "bodyWeightPercentage",
        "requiredAccessoryEquipmentIds",
        "executionMode",
        "resistanceMode",
        "movementKey",
        "exerciseCategory",
        "requiredCapabilities",
        "implementUsage",
        "jointDemand",
        "loadingDemand",
        "warmupDemand",
    ],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "exerciseType": {"type": "string", "enum": sorted(EXERCISE_TYPES)},
        "equipmentId": {"type": ["string", "null"]},
        "bodyWeightPercentage": {
            "type": ["number", "null"],
            "exclusiveMinimum": 1,
            "maximum": 100,
        },
        "requiredAccessoryEquipmentIds": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "executionMode": {"type": "string", "enum": sorted(EXECUTION_MODES)},
        "resistanceMode": {"type": "string", "enum": sorted(RESISTANCE_MODES)},
        "movementKey": {"type": "string", "minLength": 1},
        "exerciseCategory": {
            "type": ["string", "null"],
            "enum": sorted(EXERCISE_CATEGORIES) + [None],
        },
        "requiredCapabilities": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "implementUsage": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["equipmentId", "quantity"],
                "properties": {
                    "equipmentId": {"type": "string", "minLength": 1},
                    "quantity": {"type": "integer", "minimum": 1},
                },
            },
        },
        "jointDemand": {"type": "string", "enum": sorted(JOINT_DEMANDS)},
        "loadingDemand": {"type": "string", "enum": sorted(LOADING_DEMANDS)},
        "warmupDemand": {"type": "string", "enum": sorted(LOADING_DEMANDS)},
    },
}
MUSCLE_GROUPS = {
    "FRONT_ABS", "FRONT_ADDUCTORS", "FRONT_ANKLES", "FRONT_BICEPS",
    "FRONT_CALVES", "FRONT_CHEST", "FRONT_DELTOIDS", "FRONT_FEET",
    "FRONT_FOREARM", "FRONT_HANDS", "FRONT_KNEES", "FRONT_NECK",
    "FRONT_OBLIQUES", "FRONT_QUADRICEPS", "FRONT_TIBIALIS",
    "FRONT_TRAPEZIUS", "FRONT_TRICEPS", "BACK_ADDUCTORS", "BACK_ANKLES",
    "BACK_CALVES", "BACK_DELTOIDS", "BACK_FEET", "BACK_FOREARM",
    "BACK_GLUTEAL", "BACK_HAMSTRING", "BACK_HANDS", "BACK_LOWER_BACK",
    "BACK_NECK", "BACK_TRAPEZIUS", "BACK_TRICEPS", "BACK_UPPER_BACK",
}

INVENTORY_SYSTEM_PROMPT = """You are the exercise-inventory planner used by MyWorkoutAssistant.
Enumerate a comprehensive library of distinct, practical exercises possible with the supplied
equipment and accessories. Do not include exercises that require none of the supplied equipment
or accessories. Do not invent equipment. Do not multiply entries for tempo, rep scheme, load,
stance width, minor grip changes,
or arbitrary renaming. Create a separate entry when the movement, exerciseType, or primary
equipment genuinely changes. Accessories belong in requiredAccessoryEquipmentIds, never in
equipmentId. Return JSON only as {"exercises": [...]}. Each entry must contain name,
exerciseType, equipmentId, bodyWeightPercentage, and requiredAccessoryEquipmentIds. Use exact
equipment IDs. WEIGHT uses bodyWeightPercentage null. BODY_WEIGHT uses a movement-specific
estimate from greater than 1 through 100 of the user's body mass that acts as effective resistance.
Do not default every movement to 100: use 100 only when substantially the entire body mass is
supported against gravity, and lower values when limbs or external supports bear part of the mass.
Estimate each distinct movement independently. BODY_WEIGHT normally uses null equipmentId unless
the equipment is the primary
load-bearing implement. `Dumbbell Pair` always means two dumbbells and `Single Dumbbell` always
means exactly one; never use the ambiguous equipment label `Dumbbells`. Also return executionMode
(REPETITIONS, TARGET_DURATION, or OPEN_DURATION),
resistanceMode (BODY_WEIGHT, EXTERNAL_LOAD, or BODY_WEIGHT_PLUS_LOAD), a stable descriptive
movementKey shared only by biomechanically equivalent movements, and exerciseCategory using the
allowed app enum or null for timed activities. Also declare requiredCapabilities, implementUsage
with exact equipment/accessory IDs and physical quantity, jointDemand, loadingDemand, and
warmupDemand using the supplied closed enums. Every physical implement or special capability
needed for safe execution must be declared. Omit an exercise if any requirement is unavailable.
COUNTDOWN and COUNTUP are only for genuinely time-based activities.
Inventory compatibility rule: CARDIO_MACHINE is primary equipment for COUNTUP/COUNTDOWN only.
All other primary equipment types are valid for WEIGHT/BODY_WEIGHT only. Cardio machines are not
accessories and must never appear in requiredAccessoryEquipmentIds."""

AUDIT_SYSTEM_PROMPT = """Audit an exercise inventory for material omissions. Return JSON only as
{"exercises": [...]}, containing only missing distinct exercises that are possible with the
supplied equipment. Follow the same structural fields and exact IDs. Do not return duplicates,
cosmetic variations, programming variants, or exercises requiring unavailable equipment."""

DEFINITION_SYSTEM_PROMPT = """Emit one canonical MyWorkoutAssistant ExerciseDefinition as JSON.
Preserve name, exerciseType, equipmentId, bodyWeightPercentage, and
requiredAccessoryEquipmentIds exactly from the candidate. Add a non-empty muscleGroups array.
Most exercises have one or two primary regions; use three only when three distinct prime movers
are genuinely central to producing the movement. Add at most three secondaryMuscleGroups, and use
an empty array when no additional region is materially trained. Core bracing, posture, grip, and
balance alone do not make a region primary or secondary. Do not list joints, hands, feet, or
generic contact points as muscles. FRONT_ and BACK_ identify regions on the app's front/back
anatomical maps; select only regions genuinely trained by the movement and never fill an array to
its maximum merely because space is available. Add
exerciseCategory. exerciseCategory must be exactly HEAVY_COMPOUND,
MODERATE_COMPOUND, or ISOLATION for WEIGHT/BODY_WEIGHT and null for COUNTUP/COUNTDOWN. The exact
primary-muscle property name is muscleGroups, not primaryMuscleGroups. Do not include instructions,
notes, sets, reps, loads, rests, progression, placement notes, or workout programming. Use only
valid muscle enum values supplied by the user. Return the definition object directly, without an
exerciseDefinition or exerciseDefinitions wrapper."""

MUSCLE_PATCH_PATHS = {"/muscleGroups", "/secondaryMuscleGroups"}
CONTENT_AUTHORITY_PATCH_PATHS = {
    "/instructions",
    "/muscleGroups",
    "/secondaryMuscleGroups",
    "/exerciseCategory",
}
CONTENT_AUTHORITY_VERSION = 9
CONTENT_AUTHORITY_BATCH_SIZE = 3
CONTENT_AUTHORITY_CHECKS = {
    "movementIdentity",
    "setupEquipment",
    "implementQuantity",
    "loadingMechanics",
    "instructionConsistency",
    "primaryMuscles",
    "secondaryMuscles",
    "exerciseCategory",
}
NON_MUSCLE_PRIMARY_GROUPS = {
    "FRONT_ANKLES", "BACK_ANKLES", "FRONT_FEET", "BACK_FEET",
    "FRONT_HANDS", "BACK_HANDS", "FRONT_KNEES",
}
INSTRUCTION_SUPPORT_TERMS = {
    "bench": re.compile(r"\bbench\b", re.I),
    "box": re.compile(r"\bbox\b", re.I),
    "chair": re.compile(r"\bchair\b", re.I),
    "step or raised edge": re.compile(
        r"\b(?:on|onto|atop) (?:a |the )?(?:step|raised(?:, stable)? "
        r"(?:surface|edge)|elevated surface|platform)\b",
        re.I,
    ),
    "stable support surface": re.compile(
        r"\b(?:balance|support) (?:on|against|with) (?:a |the )?stable surface\b",
        re.I,
    ),
    "wall": re.compile(r"\bwall\b", re.I),
}
SEMANTIC_REVIEW_PATCH_PATHS = {
    "/name",
    "/instructions",
    "/muscleGroups",
    "/secondaryMuscleGroups",
}
SEMANTIC_REVIEW_BATCH_SIZE = 20
MAX_SEMANTIC_DISCARD_FRACTION = 0.50
CAPABILITY_CONFIDENCE_LEVELS = {"HIGH", "MEDIUM", "LOW"}
CAPABILITY_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
EQUIPMENT_CAPABILITY_CATALOG = {
    "ADJUSTABLE_BENCH", "ADJUSTABLE_PULLEY", "ADJUSTABLE_WEIGHT",
    "ANKLE_STRAP_ATTACHMENT", "BENCH", "CARDIO_STATIONARY", "CORE_ROLLER",
    "DECLINE_BENCH", "DIP_HANDLES", "FLAT_BENCH", "GYMNASTIC_RINGS",
    "HIGH_PULLEY", "INCLINE_BENCH", "LOADABLE_BAR", "LOADABLE_PLATES",
    "LOW_PULLEY", "MUSCLE_UP_CLEARANCE", "NORDIC_CURL_SUPPORT", "PULL_UP_BAR",
    "RACKED_BAR_SUPPORT", "ROPE_ATTACHMENT", "ROW_FOOT_BRACE",
    "SINGLE_HANDLE_ATTACHMENT", "STRAIGHT_BAR_ATTACHMENT", "SUPPORTS_PLATES",
    "THIGH_HOLD_DOWN", "ANKLE_RESTRAINT", "HUMAN_HANDOFF_SUPPORT",
    "OVER_IMPLEMENT_TRANSITION_CLEARANCE", "WIDE_BAR_ATTACHMENT",
    "SECOND_CABLE_STATION", "DUAL_HANDLE_SUPPLY",
}
PULLEY_POSITION_CAPABILITIES = {"HIGH_PULLEY", "LOW_PULLEY", "ADJUSTABLE_PULLEY"}
CABLE_ATTACHMENT_CAPABILITIES = {
    "SINGLE_HANDLE_ATTACHMENT",
    "ROPE_ATTACHMENT",
    "STRAIGHT_BAR_ATTACHMENT",
    "WIDE_BAR_ATTACHMENT",
    "ANKLE_STRAP_ATTACHMENT",
}
INSTRUCTION_CAPABILITY_REQUIREMENTS = (
    (re.compile(r"\bhigh pulley\b", re.I), {"HIGH_PULLEY", "ADJUSTABLE_PULLEY"}, "high pulley"),
    (re.compile(r"\blow pulley\b", re.I), {"LOW_PULLEY", "ADJUSTABLE_PULLEY"}, "low pulley"),
    (re.compile(r"\b(?:d-?handle|single handle)\b", re.I), {"SINGLE_HANDLE_ATTACHMENT"}, "single handle attachment"),
    (re.compile(r"\brope\b", re.I), {"ROPE_ATTACHMENT"}, "rope attachment"),
    (re.compile(r"\bwide bar\b", re.I), {"WIDE_BAR_ATTACHMENT"}, "wide bar attachment"),
    (re.compile(r"\bstraight bar\b", re.I), {"STRAIGHT_BAR_ATTACHMENT"}, "straight bar attachment"),
    (re.compile(r"\b(?:ankle strap|ankle cuff)\b", re.I), {"ANKLE_STRAP_ATTACHMENT"}, "ankle attachment"),
    (re.compile(r"\bthighs? secured under (?:the )?pads?\b", re.I), {"THIGH_HOLD_DOWN"}, "thigh hold-down"),
    (re.compile(r"\bfeet braced\b", re.I), {"ROW_FOOT_BRACE"}, "row foot brace"),
    (
        re.compile(r"\bincline bench\b", re.I),
        {"INCLINE_BENCH", "ADJUSTABLE_BENCH"},
        "incline bench",
    ),
    (
        re.compile(r"\bdecline bench\b", re.I),
        {"DECLINE_BENCH", "ADJUSTABLE_BENCH"},
        "decline bench",
    ),
)

CAPABILITY_IMPLICATIONS = {
    "LOADABLE_BAR": {"ADJUSTABLE_WEIGHT"},
    "SUPPORTS_PLATES": {"ADJUSTABLE_WEIGHT"},
    "ADJUSTABLE_BENCH": {"FLAT_BENCH", "INCLINE_BENCH", "DECLINE_BENCH"},
    "ADJUSTABLE_PULLEY": {"HIGH_PULLEY", "LOW_PULLEY"},
    "NORDIC_CURL_SUPPORT": {"ANKLE_RESTRAINT", "THIGH_HOLD_DOWN"},
    "MUSCLE_UP_CLEARANCE": {"OVER_IMPLEMENT_TRANSITION_CLEARANCE"},
}

# These describe how resistance can be changed, not equipment required to execute
# one occurrence of an exercise. They must never make a definition infeasible.
PROGRAMMING_ONLY_CAPABILITIES = {
    "ADJUSTABLE_WEIGHT",
    "LOADABLE_BAR",
    "LOADABLE_PLATES",
    "SUPPORTS_PLATES",
}

CAPABILITY_SEMANTICS = {
    "ADJUSTABLE_WEIGHT": "Programming convenience only; never mandatory to execute one set.",
    "LOADABLE_BAR": "The implement accepts external load; never itself an execution prerequisite.",
    "LOADABLE_PLATES": "The implement can be plate-loaded; never itself an execution prerequisite.",
    "SUPPORTS_PLATES": "The implement accepts plates; never itself an execution prerequisite.",
    "RACKED_BAR_SUPPORT": "Supports a loaded bar at the required start/end height. Mandatory only when the movement cannot be safely set up from the floor or by the athlete without a rack.",
    "HUMAN_HANDOFF_SUPPORT": "A second person must hand the implement to or receive it from the athlete; do not require merely because a spotter could be useful.",
    "MUSCLE_UP_CLEARANCE": "Space above and around the support for an actual muscle-up transition; ordinary hanging, pulling, rowing, pushing, or support holds do not require it.",
    "OVER_IMPLEMENT_TRANSITION_CLEARANCE": "Space to move the torso from below to above an implement; do not require when the torso stays on one side.",
    "SINGLE_HANDLE_ATTACHMENT": "A cable-machine handle attachment, not a generic one-handed grip and never a dumbbell requirement.",
}

CAPABILITY_GENERATION_SYSTEM_PROMPT = """You identify physical exercise capabilities of supplied
equipment and accessories. Return JSON only as {"suggestions": [...]}. Each suggestion must have
exactly equipmentId, capability, reason, and confidence. equipmentId must be copied exactly from
the supplied list. capability must be a concise UPPER_SNAKE_CASE physical feature such as
ADJUSTABLE_BENCH, HIGH_PULLEY, PULL_UP_BAR, or SUPPORTS_PLATES. confidence must be HIGH, MEDIUM,
or LOW. Explain the visible data that supports the suggestion. Never assume an optional attachment
is present merely because equipment could support one. Do not emit USE_EQUIPMENT capabilities.
When evidence is uncertain, use LOW confidence rather than inventing certainty."""


class DefinitionValidationError(ValueError):
    def __init__(self, message: str, repair_paths: set[str] | None = None):
        super().__init__(message)
        self.repair_paths = repair_paths or set()


def _validate_primary_equipment_compatibility(
    exercise: dict[str, Any],
    equipment: dict[str, Any],
) -> None:
    equipment_id = exercise.get("equipmentId")
    if equipment_id is None:
        return
    equipment_item = _equipment_by_id(equipment).get(equipment_id)
    if equipment_item is None:
        return  # Unknown IDs are reported by the owning validation path.

    exercise_type = exercise.get("exerciseType")
    equipment_type = str(equipment_item.get("type", "")).upper()
    compatible = (
        exercise_type in {"COUNTUP", "COUNTDOWN"}
        if equipment_type == "CARDIO_MACHINE"
        else exercise_type in {"WEIGHT", "BODY_WEIGHT"}
    )
    if not compatible:
        raise ValueError(
            f"{exercise.get('name', 'Unknown')}: equipment type {equipment_type} "
            f"is incompatible with exerciseType {exercise_type}"
        )


def _validate_reviewed_definition(
    definition: dict[str, Any],
    equipment: dict[str, Any],
) -> dict[str, Any]:
    primary_ids, accessory_ids = _equipment_ids(equipment)
    if definition.get("exerciseType") not in EXERCISE_TYPES:
        raise ValueError("semantic review produced an invalid exerciseType")
    if definition.get("equipmentId") is not None and definition["equipmentId"] not in primary_ids:
        raise ValueError("semantic review introduced an unknown equipmentId")
    _validate_primary_equipment_compatibility(definition, equipment)
    accessories = definition.get("requiredAccessoryEquipmentIds")
    if not isinstance(accessories, list) or set(accessories) - accessory_ids:
        raise ValueError("semantic review introduced unknown accessory IDs")
    if definition["exerciseType"] == "BODY_WEIGHT":
        percentage = definition.get("bodyWeightPercentage")
        if (
            not isinstance(percentage, (int, float))
            or isinstance(percentage, bool)
            or not 1 < percentage <= 100
        ):
            raise ValueError("reviewed BODY_WEIGHT definition needs percentage semantics")
    elif definition.get("bodyWeightPercentage") is not None:
        raise ValueError("reviewed non-BODY_WEIGHT definition must have null bodyWeightPercentage")
    category = definition.get("exerciseCategory")
    if definition["exerciseType"] in {"COUNTUP", "COUNTDOWN"}:
        if category is not None:
            raise ValueError("reviewed timed definition must have null exerciseCategory")
    elif category not in EXERCISE_CATEGORIES:
        raise ValueError("reviewed repetition definition has an invalid exerciseCategory")
    for field in ("name",):
        if not isinstance(definition.get(field), str) or not definition[field].strip():
            raise ValueError(f"reviewed definition has invalid {field}")
    reviewed = copy.deepcopy(definition)
    reviewed.pop("instructions", None)
    reviewed.pop("instructionEquipmentIds", None)
    for field in ("muscleGroups", "secondaryMuscleGroups"):
        values = reviewed.get(field)
        if not isinstance(values, list) or (field == "muscleGroups" and not values):
            raise ValueError(f"reviewed definition has invalid {field}")
        if any(not isinstance(value, str) or not fix_muscle_groups([value]) for value in values):
            raise ValueError(f"reviewed definition has unknown values in {field}")
        normalized_values = list(dict.fromkeys(fix_muscle_groups(values)))
        reviewed[field] = normalized_values
    reviewed["secondaryMuscleGroups"] = [
        muscle
        for muscle in reviewed["secondaryMuscleGroups"]
        if muscle not in reviewed["muscleGroups"]
    ]
    reviewed.pop("id", None)
    reviewed["id"] = build_exercise_definition_id(reviewed)
    return reviewed


def _apply_semantic_review_payload(
    payload: dict[str, Any],
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise ValueError("Semantic review must contain a reviews array")
    definitions_by_id = {definition["id"]: definition for definition in definitions}
    reviewed_ids = [review.get("id") for review in reviews if isinstance(review, dict)]
    if len(reviews) != len(definitions) or set(reviewed_ids) != set(definitions_by_id):
        raise ValueError("Semantic review did not return exactly one result for every definition")
    kept = []
    discards = []
    known_equipment_ids = set(_all_equipment_items(equipment))
    for review in reviews:
        definition = definitions_by_id[review["id"]]
        issues = review.get("issues")
        patch_operations = review.get("patch")
        required_equipment_ids = review.get("requiredEquipmentIds")
        requirement_clauses = review.get("requirementClauses")
        missing_equipment = review.get("missingEquipment")
        if (
            not isinstance(issues, list)
            or not isinstance(required_equipment_ids, list)
            or any(not isinstance(value, str) for value in required_equipment_ids)
            or not isinstance(requirement_clauses, list)
            or any(
                not isinstance(clause, dict)
                or set(clause) != {"anyOf"}
                or not isinstance(clause["anyOf"], list)
                or not clause["anyOf"]
                or any(not isinstance(value, str) for value in clause["anyOf"])
                for clause in requirement_clauses
            )
            or not isinstance(missing_equipment, list)
            or any(not isinstance(value, str) or not value.strip() for value in missing_equipment)
        ):
            raise ValueError(f"Invalid semantic review for {definition['name']}")
        if set(required_equipment_ids) - known_equipment_ids:
            raise ValueError(f"Semantic review used unknown equipment IDs for {definition['name']}")
        required_capability_values = {
            value for clause in requirement_clauses for value in clause["anyOf"]
        }
        unknown_capabilities = required_capability_values - EQUIPMENT_CAPABILITY_CATALOG
        if unknown_capabilities:
            raise ValueError(
                f"Semantic review used unknown capabilities for {definition['name']}: "
                f"{sorted(unknown_capabilities)}"
            )
        requirement_clauses = [
            {"anyOf": [
                capability
                for capability in clause["anyOf"]
                if capability not in PROGRAMMING_ONLY_CAPABILITIES
            ]}
            for clause in requirement_clauses
        ]
        requirement_clauses = [clause for clause in requirement_clauses if clause["anyOf"]]
        declared_ids = {
            value for value in [
                definition.get("equipmentId"),
                *definition.get("requiredAccessoryEquipmentIds", []),
            ] if value is not None
        }
        undeclared_ids = set(required_equipment_ids) - declared_ids
        available_capabilities = _capabilities_for_equipment_ids(equipment, declared_ids)
        unsatisfied_clauses = [
            clause["anyOf"]
            for clause in requirement_clauses
            if not set(clause["anyOf"]).intersection(available_capabilities)
        ]
        computed_issues = list(map(str, issues))
        if undeclared_ids:
            computed_issues.append(f"requires unlinked equipment IDs {sorted(undeclared_ids)}")
        if unsatisfied_clauses:
            computed_issues.append(
                f"has unsatisfied capability alternatives {unsatisfied_clauses}"
            )
        if missing_equipment:
            computed_issues.append(
                "requires unavailable equipment "
                + ", ".join(value.strip() for value in missing_equipment)
            )
        if undeclared_ids or unsatisfied_clauses or missing_equipment:
            discards.append(
                f"{definition['name']}: " + ("; ".join(computed_issues) or "infeasible")
            )
            continue
        if not isinstance(patch_operations, list):
            raise ValueError(f"Semantic review lacks a patch array for {definition['name']}")
        validate_patch_operations_scope(
            patch_operations,
            SEMANTIC_REVIEW_PATCH_PATHS,
            SEMANTIC_REVIEW_PATCH_PATHS,
        )
        patched = apply_json_patch(definition, patch_operations)
        changed_paths = collect_changed_json_paths(definition, patched)
        validate_changed_paths_scope(
            changed_paths,
            SEMANTIC_REVIEW_PATCH_PATHS,
            SEMANTIC_REVIEW_PATCH_PATHS,
        )
        kept.append(_validate_reviewed_definition(patched, equipment))
    return kept, discards


def _requirement_signature(review: dict[str, Any]) -> tuple[Any, ...]:
    equipment_ids = review.get("requiredEquipmentIds")
    clauses = review.get("requirementClauses")
    missing = review.get("missingEquipment")
    if (
        not isinstance(equipment_ids, list)
        or any(not isinstance(value, str) for value in equipment_ids)
        or not isinstance(clauses, list)
        or any(
            not isinstance(clause, dict)
            or set(clause) != {"anyOf"}
            or not isinstance(clause["anyOf"], list)
            or not clause["anyOf"]
            or any(not isinstance(value, str) for value in clause["anyOf"])
            for clause in clauses
        )
        or not isinstance(missing, list)
        or any(not isinstance(value, str) or not value.strip() for value in missing)
    ):
        raise ValueError("Invalid structured physical requirements")
    normalized_clauses = tuple(
        sorted(tuple(sorted(set(clause["anyOf"]))) for clause in clauses)
    )
    return (
        tuple(sorted(set(equipment_ids))),
        normalized_clauses,
        tuple(sorted({value.strip().casefold() for value in missing})),
    )


def _reviews_by_id(
    payload: dict[str, Any],
    definitions: list[dict[str, Any]],
    known_equipment_ids: set[str] | None = None,
    equipment_reference_ids: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        list_candidates = [
            value
            for value in payload.values()
            if isinstance(value, list)
            and all(isinstance(item, dict) for item in value)
        ]
        object_candidates = [
            value
            for value in payload.values()
            if isinstance(value, dict) and isinstance(value.get("id"), str)
        ]
        if len(list_candidates) == 1:
            reviews = list_candidates[0]
        elif len(object_candidates) == 1:
            reviews = [object_candidates[0]]
        elif isinstance(payload.get("id"), str):
            reviews = [payload]
    if not isinstance(reviews, list) or any(not isinstance(review, dict) for review in reviews):
        raise ValueError("Requirement extraction must contain a reviews array")
    expected_ids = {definition["id"] for definition in definitions}
    relevant_reviews = [review for review in reviews if review.get("id") in expected_ids]
    reviewed_ids = [review.get("id") for review in relevant_reviews]
    by_id = {review["id"]: review for review in relevant_reviews}
    if len(reviewed_ids) != len(set(reviewed_ids)):
        raise ValueError("Requirement extraction duplicated a requested definition ID")
    if set(by_id) != expected_ids:
        raise ValueError("Requirement extraction did not cover every definition exactly once")
    equipment_reference_ids = equipment_reference_ids or {}
    for review in reviews:
        if known_equipment_ids:
            clauses = review.get("requirementClauses")
            required_ids = review.get("requiredEquipmentIds")
            if isinstance(clauses, list) and isinstance(required_ids, list):
                normalized_required_ids = []
                moved_capabilities = []
                for value in required_ids:
                    normalized_value = _normalize_equipment_reference_token(
                        value, equipment_reference_ids
                    )
                    if isinstance(normalized_value, str) and normalized_value in known_equipment_ids:
                        normalized_required_ids.append(normalized_value)
                    elif (
                        isinstance(normalized_value, str)
                        and normalized_value in EQUIPMENT_CAPABILITY_CATALOG
                    ):
                        moved_capabilities.append({"anyOf": [normalized_value]})
                    else:
                        normalized_required_ids.append(value)
                normalized_clauses = []
                for clause in clauses:
                    alternatives = clause.get("anyOf") if isinstance(clause, dict) else None
                    normalized_alternatives = [
                        _normalize_equipment_reference_token(value, equipment_reference_ids)
                        for value in alternatives
                    ] if isinstance(alternatives, list) else alternatives
                    equipment_alternatives = (
                        [
                            value
                            for value in normalized_alternatives
                            if isinstance(value, str) and value in known_equipment_ids
                        ]
                        if isinstance(normalized_alternatives, list)
                        else []
                    )
                    if equipment_alternatives:
                        # An equipment reference is never a capability. The supplied item is
                        # available, so recover the reference as a concrete requirement and
                        # discard the malformed mixed clause rather than aborting the batch.
                        normalized_required_ids.append(equipment_alternatives[0])
                    else:
                        normalized_clauses.append(
                            {"anyOf": normalized_alternatives}
                            if isinstance(normalized_alternatives, list)
                            else clause
                        )
                review["requiredEquipmentIds"] = (
                    list(dict.fromkeys(normalized_required_ids))
                    if all(isinstance(value, str) for value in normalized_required_ids)
                    else normalized_required_ids
                )
                review["requirementClauses"] = normalized_clauses + moved_capabilities
        missing = review.get("missingEquipment")
        if isinstance(missing, list):
            normalized_missing = []
            for value in missing:
                if not isinstance(value, str):
                    normalized_missing.append(value)
                    continue
                if value.strip().casefold() in {
                    "none", "n/a", "na", "not applicable", "nothing", "no missing equipment"
                }:
                    continue
                normalized_value = _normalize_equipment_reference_token(
                    value, equipment_reference_ids
                )
                if (
                    known_equipment_ids
                    and isinstance(normalized_value, str)
                    and normalized_value in known_equipment_ids
                ):
                    review.setdefault("requiredEquipmentIds", []).append(normalized_value)
                elif (
                    isinstance(normalized_value, str)
                    and normalized_value in EQUIPMENT_CAPABILITY_CATALOG
                ):
                    review.setdefault("requirementClauses", []).append(
                        {"anyOf": [normalized_value]}
                    )
                else:
                    normalized_missing.append(value)
            required_equipment_ids = review.get("requiredEquipmentIds", [])
            if all(isinstance(value, str) for value in required_equipment_ids):
                review["requiredEquipmentIds"] = list(dict.fromkeys(required_equipment_ids))
            review["missingEquipment"] = normalized_missing
        _requirement_signature(review)
        unknown_capabilities = {
            capability
            for clause in review["requirementClauses"]
            for capability in clause["anyOf"]
            if capability not in EQUIPMENT_CAPABILITY_CATALOG
        }
        if unknown_capabilities:
            raise ValueError(
                f"Requirement extraction used unknown capabilities: {sorted(unknown_capabilities)}"
            )
    return by_id


def _normalize_equipment_reference_token(
    value: Any,
    equipment_reference_ids: dict[str, str],
) -> Any:
    if not isinstance(value, str):
        return value
    normalized = re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")
    return equipment_reference_ids.get(normalized, value)


def _equipment_reference_ids(equipment: dict[str, Any]) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for equipment_id, item in _all_equipment_items(equipment).items():
        for value in (item.get("name"), item.get("type")):
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")
            candidates.setdefault(normalized, set()).add(equipment_id)
    return {
        token: next(iter(ids))
        for token, ids in candidates.items()
        if len(ids) == 1
    }


def _review_equipment_context(
    equipment: dict[str, Any],
) -> tuple[str, dict[str, str], dict[str, str]]:
    referenced_equipment = copy.deepcopy(equipment)
    reference_to_id: dict[str, str] = {}
    id_to_reference: dict[str, str] = {}
    for collection_name, prefix in (
        ("equipments", "PRIMARY"),
        ("accessoryEquipments", "ACCESSORY"),
    ):
        for index, item in enumerate(referenced_equipment.get(collection_name, []), start=1):
            equipment_id = item.get("id")
            if not isinstance(equipment_id, str):
                continue
            semantic_name = re.sub(
                r"[^A-Z0-9]+",
                "_",
                str(item.get("name") or item.get("type") or "ITEM").strip().upper(),
            ).strip("_")
            reference = f"{prefix}_{semantic_name}_{index}"
            reference_to_id[reference] = equipment_id
            id_to_reference[equipment_id] = reference
            item["id"] = reference
    return _format_equipment_context(referenced_equipment), reference_to_id, id_to_reference


def _definitions_with_equipment_references(
    definitions: list[dict[str, Any]], id_to_reference: dict[str, str]
) -> list[dict[str, Any]]:
    referenced = copy.deepcopy(definitions)
    for definition in referenced:
        equipment_id = definition.get("equipmentId")
        if equipment_id in id_to_reference:
            definition["equipmentId"] = id_to_reference[equipment_id]
        definition["requiredAccessoryEquipmentIds"] = [
            id_to_reference.get(value, value)
            for value in definition.get("requiredAccessoryEquipmentIds", [])
        ]
    return referenced


def _review_payload_with_equipment_references(
    payload: dict[str, Any], id_to_reference: dict[str, str]
) -> dict[str, Any]:
    referenced = copy.deepcopy(payload)
    reviews = referenced.get("reviews")
    if not isinstance(reviews, list):
        return referenced
    for review in reviews:
        if not isinstance(review, dict):
            continue
        review["requiredEquipmentIds"] = [
            id_to_reference.get(value, value)
            for value in review.get("requiredEquipmentIds", [])
        ]
        for clause in review.get("requirementClauses", []):
            if isinstance(clause, dict) and isinstance(clause.get("anyOf"), list):
                clause["anyOf"] = [
                    id_to_reference.get(value, value) for value in clause["anyOf"]
                ]
        review["missingEquipment"] = [
            id_to_reference.get(value, value)
            for value in review.get("missingEquipment", [])
        ]
    return referenced


def _repair_review_payload_with_json_patch(
    client: Any,
    payload: dict[str, Any],
    validation_error: Exception,
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    call_json: Callable[..., str | None],
    stage_label: str,
    equipment_reference_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "Return JSON only as {\"patch\":[RFC 6902 operations]}. Repair the structured "
                "exercise requirement review. Every operation path must be /reviews or a "
                "descendant of /reviews. Do not modify unrelated top-level data. The repaired "
                "reviews must contain exactly one entry per supplied definition ID, with "
                "requiredEquipmentIds, requirementClauses containing non-empty anyOf arrays, "
                "and missingEquipment. Semantic-review payloads must also retain issues and patch."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "stage": stage_label,
                    "validationError": str(validation_error),
                    "expectedDefinitionIds": [definition["id"] for definition in definitions],
                    "knownEquipmentReferences": sorted(
                        equipment_reference_ids or _all_equipment_items(equipment)
                    ),
                    "allowedCapabilities": sorted(EQUIPMENT_CAPABILITY_CATALOG),
                    "payload": payload,
                },
                ensure_ascii=False,
            ),
        },
    ]
    content = call_json(
        client,
        messages,
        f"Repairing {stage_label} JSON",
        show_loading=False,
    )
    patch_payload = _json_object(content, f"{stage_label} JSON Patch")
    operations = patch_payload.get("patch")
    if not isinstance(operations, list):
        raise ValueError(f"{stage_label} repair did not return a JSON Patch array")
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError(f"{stage_label} repair contains a non-object JSON Patch operation")
        path = operation.get("path")
        if not isinstance(path, str) or not (path == "/reviews" or path.startswith("/reviews/")):
            raise ValueError(f"{stage_label} repair attempted an out-of-scope path {path!r}")
    repaired = apply_json_patch(payload, operations)
    if not isinstance(repaired, dict):
        raise ValueError(f"{stage_label} JSON Patch produced a non-object")
    return repaired


def _parse_or_patch_requirement_reviews(
    client: Any,
    payload: dict[str, Any],
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    call_json: Callable[..., str | None],
    stage_label: str,
    additional_equipment_reference_ids: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    known_equipment_ids = set(_all_equipment_items(equipment))
    equipment_reference_ids = {
        **_equipment_reference_ids(equipment),
        **(additional_equipment_reference_ids or {}),
    }
    try:
        return payload, _reviews_by_id(
            payload, definitions, known_equipment_ids, equipment_reference_ids
        )
    except ValueError as error:
        repaired = _repair_review_payload_with_json_patch(
            client,
            payload,
            error,
            definitions,
            equipment,
            call_json,
            stage_label,
            equipment_reference_ids,
        )
        return repaired, _reviews_by_id(
            repaired, definitions, known_equipment_ids, equipment_reference_ids
        )


def _apply_requirement_verification_patch(
    payload: dict[str, Any],
    patch_payload: dict[str, Any],
    definitions: list[dict[str, Any]],
    known_equipment_ids: set[str],
    equipment_reference_ids: dict[str, str],
) -> dict[str, Any]:
    operations = patch_payload.get("patch")
    if not isinstance(operations, list):
        # Backward-compatible recovery: older or non-compliant model responses may
        # return a complete reviews envelope. Validate it, then deterministically
        # turn only its requirement fields into the scoped patch we requested.
        verification_reviews = _reviews_by_id(
            patch_payload, definitions, known_equipment_ids, equipment_reference_ids
        )
        primary_reviews = _reviews_by_id(
            payload, definitions, known_equipment_ids, equipment_reference_ids
        )
        operations = []
        for index, definition in enumerate(definitions):
            definition_id = definition["id"]
            for field in (
                "requiredEquipmentIds",
                "requirementClauses",
                "missingEquipment",
            ):
                verified_value = verification_reviews[definition_id][field]
                if primary_reviews[definition_id][field] != verified_value:
                    operations.append(
                        {
                            "op": "replace",
                            "path": f"/reviews/{index}/{field}",
                            "value": verified_value,
                        }
                    )
    if not isinstance(operations, list):
        raise ValueError("Requirement verification must return a JSON Patch array")
    allowed_field_pattern = re.compile(
        r"^/reviews/\d+/(?:requiredEquipmentIds|requirementClauses|missingEquipment)(?:/.*)?$"
    )
    definition_indexes = {
        definition["id"]: index for index, definition in enumerate(definitions)
    }
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Requirement verification contains a non-object JSON Patch operation")
        path = operation.get("path")
        if isinstance(path, str):
            path_parts = path.split("/")
            if (
                len(path_parts) >= 4
                and path_parts[1] == "reviews"
                and path_parts[2] in definition_indexes
            ):
                path_parts[2] = str(definition_indexes[path_parts[2]])
                path = "/".join(path_parts)
                operation["path"] = path
        if not isinstance(path, str) or not allowed_field_pattern.fullmatch(path):
            raise ValueError(f"Requirement verification attempted an out-of-scope path {path!r}")
    patched = apply_json_patch(payload, operations)
    if not isinstance(patched, dict):
        raise ValueError("Requirement verification JSON Patch produced a non-object")
    return patched


def _review_definition_batch(
    client: Any,
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    call_json: Callable[..., str | None],
    batch_label: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    equipment_context, review_reference_ids, id_to_review_reference = (
        _review_equipment_context(equipment)
    )
    referenced_definitions = _definitions_with_equipment_references(
        definitions, id_to_review_reference
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are an independent semantic verifier for ExerciseDefinitions. Do not trust "
                "the generator's equipment claims. Read each name and instruction literally, "
                "identify every physical implement and capability required to execute it, and "
                "report those requirements; application code decides feasibility. Infer the "
                "minimum conventional setup even when instructions incorrectly begin after "
                "setup. requiredEquipmentIds contains supplied semantic equipment references "
                "actually needed, "
                "requirementClauses contains all mandatory capability requirements as objects "
                "with anyOf alternatives selected only from the supplied catalog, and "
                "missingEquipment names required implements absent from the supplied list. Never "
                "place an equipment reference in requirementClauses, and never place a capability "
                "name in requiredEquipmentIds or missingEquipment. Do "
                "not report optional alternatives, skill, comfort, or ordinary floor/wall access "
                "as requirements. Wording changes must never hide a real requirement. Provide an RFC 6902 "
                "patch correcting only its name, muscles, or instructions. Structural type, "
                "category, equipment references, and body-weight semantics were derived and "
                "validated from a separate structured contract and must not be changed. Every "
                "muscle value must be one of these: "
                + ", ".join(sorted(MUSCLE_GROUPS))
                + ". Allowed capability values are: "
                + ", ".join(sorted(EQUIPMENT_CAPABILITY_CATALOG))
                + ". Capability semantics and limits: "
                + json.dumps(CAPABILITY_SEMANTICS, ensure_ascii=False)
                + ". Categories are HEAVY_COMPOUND, MODERATE_COMPOUND, or ISOLATION; timed "
                "activities use null. Return JSON only as {\"reviews\":[{\"id\":string,"
                "\"requiredEquipmentIds\":[string],"
                "\"requirementClauses\":[{\"anyOf\":[string]}],"
                "\"missingEquipment\":[string],\"issues\":[string],"
                "\"patch\":[RFC6902 operations]}]}. Return exactly one review for every "
                "supplied ID."
            ),
        },
        {
            "role": "user",
            "content": (
                equipment_context
                + "\n\nDefinitions to independently verify:\n"
                + json.dumps(referenced_definitions, indent=2, ensure_ascii=False)
            ),
        },
    ]
    verification_messages = [
        {
            "role": "system",
            "content": (
                "Return JSON only as {\"patch\":[RFC 6902 operations]}. Independently verify "
                "the physical requirements in the supplied semantic review against the definitions "
                "and equipment. Correct only requiredEquipmentIds, requirementClauses, and "
                "missingEquipment. Every path must be under /reviews/<index>/ followed by one of "
                "those fields. Return an empty patch when no correction is needed. Use exact "
                "supplied semantic equipment references, never UUIDs, and only these capabilities: "
                + ", ".join(sorted(EQUIPMENT_CAPABILITY_CATALOG))
                + ". Apply these capability meanings exactly: "
                + json.dumps(CAPABILITY_SEMANTICS, ensure_ascii=False)
                + ". Include setup requirements conventionally necessary even if instructions "
                "start after setup. Exclude optional alternatives and ordinary floor/wall access."
            ),
        },
    ]
    last_error = None
    for attempt in range(1, 4):
        content = call_json(client, messages, "Reviewing exercise semantics", show_loading=False)
        try:
            payload = _json_object(content, "semantic review")
            payload, _ = _parse_or_patch_requirement_reviews(
                client,
                payload,
                definitions,
                equipment,
                call_json,
                "semantic review",
                review_reference_ids,
            )
            verification_messages_with_payload = verification_messages + [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "equipment": equipment_context,
                            "definitions": referenced_definitions,
                            "semanticReview": _review_payload_with_equipment_references(
                                payload, id_to_review_reference
                            ),
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
            verification_content = call_json(
                client,
                verification_messages_with_payload,
                "Verifying physical requirements",
                show_loading=False,
            )
            verification_patch = _json_object(
                verification_content, "requirement verification JSON Patch"
            )
            known_equipment_ids = set(_all_equipment_items(equipment))
            equipment_reference_ids = {
                **_equipment_reference_ids(equipment),
                **review_reference_ids,
            }
            payload = _apply_requirement_verification_patch(
                payload,
                verification_patch,
                definitions,
                known_equipment_ids,
                equipment_reference_ids,
            )
            _reviews_by_id(
                payload, definitions, known_equipment_ids, equipment_reference_ids
            )
            try:
                reviewed_result = _apply_semantic_review_payload(
                    payload, definitions, equipment
                )
                if reviewed_result[1]:
                    adjudication_messages = [
                        {
                            "role": "system",
                            "content": (
                                "You are the final physical-feasibility adjudicator. Return JSON "
                                "only as {\"patch\":[RFC 6902 operations]}. Re-evaluate every "
                                "proposed discard from first principles: required start setup, the "
                                "complete movement, and safe finish/unloading. Correct only "
                                "requiredEquipmentIds, requirementClauses, and missingEquipment. "
                                "A requirement must be physically mandatory, not helpful, optional, "
                                "a programming convenience, or merely conventional. Never infer a "
                                "cable attachment from one-arm wording. Use semantic equipment "
                                "references and these capability meanings exactly: "
                                + json.dumps(CAPABILITY_SEMANTICS, ensure_ascii=False)
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "equipment": equipment_context,
                                    "definitions": referenced_definitions,
                                    "semanticReview": _review_payload_with_equipment_references(
                                        payload, id_to_review_reference
                                    ),
                                    "proposedDiscards": reviewed_result[1],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ]
                    adjudication_content = call_json(
                        client,
                        adjudication_messages,
                        "Adjudicating proposed infeasibility",
                        show_loading=False,
                    )
                    adjudication_patch = _json_object(
                        adjudication_content, "infeasibility adjudication JSON Patch"
                    )
                    payload = _apply_requirement_verification_patch(
                        payload,
                        adjudication_patch,
                        definitions,
                        known_equipment_ids,
                        equipment_reference_ids,
                    )
                    _reviews_by_id(
                        payload, definitions, known_equipment_ids, equipment_reference_ids
                    )
                    return _apply_semantic_review_payload(payload, definitions, equipment)
                return reviewed_result
            except ValueError as error:
                payload = _repair_review_payload_with_json_patch(
                    client,
                    payload,
                    error,
                    definitions,
                    equipment,
                    call_json,
                    "semantic review",
                    equipment_reference_ids,
                )
                return _apply_semantic_review_payload(payload, definitions, equipment)
        except (ValueError, json.JSONDecodeError) as error:
            last_error = error
            if attempt == 3:
                break
            prefix = f"{batch_label}: " if batch_label else ""
            print(
                f"{prefix}structured response could not be repaired ({str(error)[:160]}); "
                f"retrying batch ({attempt + 1}/3).",
                flush=True,
            )
            messages.append({"role": "assistant", "content": content or ""})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Review validation failed: {error}. Return a corrected complete reviews "
                        "object for the same definition IDs. Fix only the invalid review patches; "
                        "do not omit successful reviews."
                    ),
                }
            )
    raise ValueError(f"Could not produce a valid semantic review after 3 attempts: {last_error}")


def _review_definition_batch_resilient(
    client: Any,
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    call_json: Callable[..., str | None],
    batch_label: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        return _review_definition_batch(
            client, definitions, equipment, call_json, batch_label=batch_label
        )
    except ValueError as batch_error:
        if len(definitions) <= 1:
            raise
        midpoint = len(definitions) // 2
        print(
            f"{batch_label or 'Review batch'} remained structurally invalid; splitting "
            f"{len(definitions)} definitions into {midpoint} and {len(definitions) - midpoint}.",
            flush=True,
        )
        left_kept, left_discards = _review_definition_batch_resilient(
            client,
            definitions[:midpoint],
            equipment,
            call_json,
            batch_label=f"{batch_label}a" if batch_label else "Review split A",
        )
        right_kept, right_discards = _review_definition_batch_resilient(
            client,
            definitions[midpoint:],
            equipment,
            call_json,
            batch_label=f"{batch_label}b" if batch_label else "Review split B",
        )
        return left_kept + right_kept, left_discards + right_discards


def _deduplicate_reviewed_definitions(
    definitions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    kept = []
    discarded = []
    seen_ids = set()
    seen_names = set()
    for definition in definitions:
        definition_id = definition["id"]
        normalized_name = definition["name"].strip().casefold()
        if definition_id in seen_ids:
            discarded.append(
                f"{definition['name']}: semantic review produced duplicate definition content"
            )
            continue
        if normalized_name in seen_names:
            discarded.append(
                f"{definition['name']}: semantic review produced an ambiguous duplicate name"
            )
            continue
        seen_ids.add(definition_id)
        seen_names.add(normalized_name)
        kept.append(definition)
    return kept, discarded


def _equipment_by_id(equipment: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in equipment.get("equipments", [])
        if isinstance(item, dict) and item.get("id")
    }


def _all_equipment_items(equipment: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in (
            list(equipment.get("equipments", []))
            + list(equipment.get("accessoryEquipments", []))
        )
        if isinstance(item, dict) and item.get("id")
    }


def _canonical_equipment_name(item: dict[str, Any]) -> str:
    return {
        "DUMBBELLS": "Dumbbell Pair",
        "DUMBBELL": "Single Dumbbell",
    }.get(item.get("type"), str(item.get("name") or item.get("id") or "Equipment"))


def _equipment_context_lists(
    equipment: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    def canonicalized(items: list[Any]) -> list[dict[str, Any]]:
        result = []
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            item = copy.deepcopy(raw_item)
            item["name"] = _canonical_equipment_name(item)
            result.append(item)
        return result

    return (
        canonicalized(equipment.get("equipments", [])),
        canonicalized(equipment.get("accessoryEquipments", [])),
    )


def _format_equipment_context(equipment: dict[str, Any]) -> str:
    primary, accessories = _equipment_context_lists(equipment)
    return format_equipment_for_llm(primary, accessories)


def _available_capabilities(equipment: dict[str, Any]) -> set[str]:
    capabilities = set()
    for item_id, item in _all_equipment_items(equipment).items():
        capabilities.add(f"USE_EQUIPMENT:{item_id}")
        declared = item.get("capabilities", [])
        if isinstance(declared, list):
            capabilities.update(
                capability.strip()
                for capability in declared
                if isinstance(capability, str) and capability.strip()
            )
    return capabilities


def _capabilities_for_equipment_ids(
    equipment: dict[str, Any], equipment_ids: set[str]
) -> set[str]:
    items = _all_equipment_items(equipment)
    capabilities = {f"USE_EQUIPMENT:{item_id}" for item_id in equipment_ids}
    for item_id in equipment_ids:
        declared = items.get(item_id, {}).get("capabilities", [])
        if isinstance(declared, list):
            capabilities.update(
                value.strip()
                for value in declared
                if isinstance(value, str) and value.strip()
            )
    pending = list(capabilities)
    while pending:
        capability = pending.pop()
        for implied in CAPABILITY_IMPLICATIONS.get(capability, set()):
            if implied not in capabilities:
                capabilities.add(implied)
                pending.append(implied)
    return capabilities


def _validate_equipment_family_capabilities(
    candidate: dict[str, Any], equipment: dict[str, Any]
) -> None:
    equipment_id = candidate.get("equipmentId")
    item = _all_equipment_items(equipment).get(equipment_id, {})
    required = set(candidate.get("requiredCapabilities", []))
    if item.get("type") == "PLATELOADEDCABLE":
        if not required.intersection(PULLEY_POSITION_CAPABILITIES):
            raise ValueError(
                f"{candidate.get('name')}: cable exercise must declare an available pulley-position capability"
            )
        if not required.intersection(CABLE_ATTACHMENT_CAPABILITIES):
            raise ValueError(
                f"{candidate.get('name')}: cable exercise must declare an available attachment capability"
            )


def _validate_instruction_requirements(
    instructions: str,
    candidate: dict[str, Any],
    equipment: dict[str, Any],
) -> None:
    declared_ids = {
        value
        for value in [candidate.get("equipmentId"), *candidate.get("requiredAccessoryEquipmentIds", [])]
        if value is not None
    }
    items = _all_equipment_items(equipment)
    lowered = instructions.casefold()
    undeclared_names = []
    dumbbell_ids = {
        item_id for item_id, item in items.items() if item.get("type") in {"DUMBBELL", "DUMBBELLS"}
    }
    for item_id, item in items.items():
        name = str(item.get("name") or "").strip().casefold()
        if not name:
            continue
        mentioned = re.search(rf"\b{re.escape(name)}s?\b", lowered) is not None
        if item.get("type") in {"DUMBBELL", "DUMBBELLS"}:
            mentioned = re.search(r"\bdumbbells?\b", lowered) is not None
            if mentioned and declared_ids.intersection(dumbbell_ids):
                continue
        if mentioned and item_id not in declared_ids:
            undeclared_names.append(item.get("name", item_id))
    if undeclared_names:
        raise DefinitionValidationError(
            "Instructions require undeclared equipment: " + ", ".join(sorted(set(undeclared_names))),
            {"/instructions", "/instructionEquipmentIds"},
        )
    linked_capabilities = _capabilities_for_equipment_ids(equipment, declared_ids)
    missing_features = []
    for pattern, alternatives, label in INSTRUCTION_CAPABILITY_REQUIREMENTS:
        if pattern.search(instructions) and not linked_capabilities.intersection(alternatives):
            missing_features.append(label)
    if missing_features:
        raise DefinitionValidationError(
            "Instructions require undeclared capabilities: " + ", ".join(sorted(set(missing_features))),
            {"/instructions", "/instructionEquipmentIds"},
        )


def _derive_exercise_category(candidate: dict[str, Any]) -> str | None:
    if candidate["exerciseType"] in {"COUNTUP", "COUNTDOWN"}:
        return None
    if candidate.get("jointDemand") == "SINGLE_JOINT":
        return "ISOLATION"
    if (
        candidate.get("jointDemand") == "MULTI_JOINT"
        and candidate.get("loadingDemand") == "HIGH"
        and candidate.get("warmupDemand") == "HIGH"
    ):
        return "HEAVY_COMPOUND"
    return "MODERATE_COMPOUND"


def _normalize_candidate_semantics(
    candidate: dict[str, Any],
    equipment: dict[str, Any],
) -> dict[str, Any]:
    normalized = copy.deepcopy(candidate)
    execution_mode = candidate.get("executionMode")
    resistance_mode = candidate.get("resistanceMode")
    if execution_mode is None:
        execution_mode = {
            "COUNTDOWN": "TARGET_DURATION",
            "COUNTUP": "OPEN_DURATION",
        }.get(candidate.get("exerciseType"), "REPETITIONS")
    if resistance_mode is None:
        resistance_mode = (
            "BODY_WEIGHT"
            if candidate.get("exerciseType") == "BODY_WEIGHT"
            else "EXTERNAL_LOAD"
        )
    if execution_mode == "TARGET_DURATION":
        normalized["exerciseType"] = "COUNTDOWN"
        normalized["bodyWeightPercentage"] = None
    elif execution_mode == "OPEN_DURATION":
        normalized["exerciseType"] = "COUNTUP"
        normalized["bodyWeightPercentage"] = None
    elif resistance_mode in {"BODY_WEIGHT", "BODY_WEIGHT_PLUS_LOAD"}:
        normalized["exerciseType"] = "BODY_WEIGHT"
        normalized["bodyWeightPercentage"] = candidate.get("bodyWeightPercentage")
    else:
        normalized["exerciseType"] = "WEIGHT"
        normalized["bodyWeightPercentage"] = None
    normalized["executionMode"] = execution_mode
    normalized["resistanceMode"] = resistance_mode
    normalized["movementKey"] = (
        str(candidate.get("movementKey") or candidate["name"]).strip().casefold()
    )
    return normalized


def _normalize_and_filter_candidates(
    candidates: list[dict[str, Any]],
    equipment: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    filtered_reasons = []
    retained_by_fingerprint: dict[tuple[Any, ...], dict[str, Any]] = {}
    for candidate in candidates:
        normalized = _normalize_candidate_semantics(candidate, equipment)
        fingerprint = (
            normalized["movementKey"],
            normalized.get("equipmentId"),
            tuple(sorted(normalized.get("requiredAccessoryEquipmentIds", []))),
            normalized["executionMode"],
            normalized["resistanceMode"],
        )
        if fingerprint in retained_by_fingerprint:
            filtered_reasons.append(
                f"{normalized['name']}: duplicate semantic movement fingerprint"
            )
            continue
        retained_by_fingerprint[fingerprint] = normalized

    retained = list(retained_by_fingerprint.values())
    name_counts = Counter(item["name"].strip().casefold() for item in retained)
    equipment_items = _equipment_by_id(equipment)
    accessory_items = {
        item["id"]: item
        for item in equipment.get("accessoryEquipments", [])
        if isinstance(item, dict) and item.get("id")
    }
    for candidate in retained:
        if name_counts[candidate["name"].strip().casefold()] > 1:
            equipment_item = equipment_items.get(candidate.get("equipmentId"), {})
            equipment_name = _canonical_equipment_name(equipment_item) if equipment_item else None
            accessory_names = [
                accessory_items[item_id].get("name", item_id)
                for item_id in candidate.get("requiredAccessoryEquipmentIds", [])
                if item_id in accessory_items
            ]
            descriptor = equipment_name or ", ".join(accessory_names)
            if descriptor:
                candidate["name"] = f"{candidate['name']} ({descriptor})"
    return (
        sorted(retained, key=lambda item: item["name"].casefold()),
        filtered_reasons,
    )


def _validate_final_definition_semantics(
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
) -> None:
    names = [definition["name"].strip().casefold() for definition in definitions]
    duplicate_names = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicate_names:
        raise ValueError(
            "Generated library contains ambiguous duplicate names: "
            + ", ".join(duplicate_names[:10])
        )
    for definition in definitions:
        expected = _normalize_candidate_semantics(definition, equipment)
        if definition["exerciseType"] != expected["exerciseType"]:
            raise ValueError(
                f"{definition['name']}: exerciseType violates semantic normalization"
            )


def _json_object(content: str | None, label: str) -> dict[str, Any]:
    if not content:
        raise ValueError(f"Model returned empty {label} response")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(f"Model returned invalid JSON for {label}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Model returned a non-object for {label}")
    return payload


def _equipment_ids(equipment: dict[str, Any]) -> tuple[set[str], set[str]]:
    primary = {
        item.get("id") for item in equipment.get("equipments", [])
        if isinstance(item, dict) and item.get("id")
    }
    accessories = {
        item.get("id") for item in equipment.get("accessoryEquipments", [])
        if isinstance(item, dict) and item.get("id")
    }
    return primary, accessories


def _validate_candidate(
    candidate: Any,
    equipment: dict[str, Any],
    allowed_equipment_ids: set[str] | None = None,
    require_any_accessory: bool = False,
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValueError("Exercise candidate must be an object")
    candidate = copy.deepcopy(candidate)
    candidate.setdefault(
        "executionMode",
        {"COUNTDOWN": "TARGET_DURATION", "COUNTUP": "OPEN_DURATION"}.get(
            candidate.get("exerciseType"), "REPETITIONS"
        ),
    )
    candidate.setdefault(
        "resistanceMode",
        "BODY_WEIGHT" if candidate.get("exerciseType") == "BODY_WEIGHT" else "EXTERNAL_LOAD",
    )
    candidate.setdefault("movementKey", str(candidate.get("name") or "").strip().casefold())
    candidate.setdefault(
        "exerciseCategory",
        None
        if candidate.get("exerciseType") in {"COUNTUP", "COUNTDOWN"}
        else "MODERATE_COMPOUND",
    )
    declared_equipment_ids = [
        item
        for item in [
            candidate.get("equipmentId"),
            *candidate.get("requiredAccessoryEquipmentIds", []),
        ]
        if item is not None
    ]
    candidate.setdefault(
        "requiredCapabilities",
        [f"USE_EQUIPMENT:{item_id}" for item_id in declared_equipment_ids],
    )
    candidate.setdefault(
        "implementUsage",
        [
            {
                "equipmentId": item_id,
                "quantity": {
                    "DUMBBELL": 1,
                    "DUMBBELLS": 2,
                }.get(_all_equipment_items(equipment).get(item_id, {}).get("type"), 1),
            }
            for item_id in declared_equipment_ids
        ],
    )
    existing_category = candidate.get("exerciseCategory")
    candidate.setdefault(
        "jointDemand",
        "SINGLE_JOINT" if existing_category == "ISOLATION" else "MULTI_JOINT",
    )
    candidate.setdefault(
        "loadingDemand",
        "HIGH" if existing_category == "HEAVY_COMPOUND" else "MODERATE",
    )
    candidate.setdefault(
        "warmupDemand",
        "HIGH" if existing_category == "HEAVY_COMPOUND" else "MODERATE",
    )
    try:
        validate_json_schema(candidate, INVENTORY_CANDIDATE_SCHEMA)
    except JsonSchemaValidationError as error:
        raise ValueError(f"Candidate does not match the inventory schema: {error.message}") from error
    candidate = _normalize_candidate_semantics(candidate, equipment)
    primary_ids, accessory_ids = _equipment_ids(equipment)
    name = candidate.get("name")
    exercise_type = candidate.get("exerciseType")
    equipment_id = candidate.get("equipmentId")
    body_weight_percentage = candidate.get("bodyWeightPercentage")
    required_accessories = candidate.get("requiredAccessoryEquipmentIds")

    if not isinstance(name, str) or not name.strip():
        raise ValueError("Exercise candidate is missing a name")
    if exercise_type not in EXERCISE_TYPES:
        raise ValueError(f"{name}: invalid exerciseType {exercise_type!r}")
    if equipment_id is not None and equipment_id not in primary_ids:
        raise ValueError(f"{name}: unknown equipmentId {equipment_id!r}")
    _validate_primary_equipment_compatibility(candidate, equipment)
    equipment_is_outside_batch = (
        allowed_equipment_ids is not None
        and (
            (not allowed_equipment_ids and equipment_id is not None)
            or (bool(allowed_equipment_ids) and equipment_id not in allowed_equipment_ids)
        )
    )
    if equipment_is_outside_batch:
        allowed_text = sorted(allowed_equipment_ids) if allowed_equipment_ids else [None]
        raise ValueError(
            f"{name}: equipmentId {equipment_id!r} is outside this batch; allowed {allowed_text}"
        )
    if not isinstance(required_accessories, list):
        raise ValueError(f"{name}: requiredAccessoryEquipmentIds must be an array")
    if len(required_accessories) != len(set(required_accessories)):
        raise ValueError(f"{name}: duplicate accessory IDs")
    unknown_accessories = set(required_accessories) - accessory_ids
    if unknown_accessories:
        raise ValueError(f"{name}: unknown accessory IDs {sorted(unknown_accessories)}")
    if require_any_accessory and not required_accessories:
        raise ValueError(f"{name}: this batch requires at least one listed accessory")
    linked_ids = {
        item for item in [equipment_id, *required_accessories] if item is not None
    }
    unavailable_capabilities = set(candidate["requiredCapabilities"]) - _capabilities_for_equipment_ids(
        equipment, linked_ids
    )
    if unavailable_capabilities:
        raise ValueError(
            f"{name}: requires unavailable capabilities {sorted(unavailable_capabilities)}"
        )
    _validate_equipment_family_capabilities(candidate, equipment)
    all_items = _all_equipment_items(equipment)
    usage_ids = [usage["equipmentId"] for usage in candidate["implementUsage"]]
    declared_ids = {
        item for item in [equipment_id, *required_accessories] if item is not None
    }
    if set(usage_ids) != declared_ids or len(usage_ids) != len(set(usage_ids)):
        raise ValueError(
            f"{name}: implementUsage must declare every and only linked equipment ID once"
        )
    for usage in candidate["implementUsage"]:
        item = all_items.get(usage["equipmentId"])
        if item is None:
            raise ValueError(f"{name}: implementUsage contains an unknown equipment ID")
        expected_quantity = {"DUMBBELL": 1, "DUMBBELLS": 2}.get(item.get("type"))
        if expected_quantity is not None and usage["quantity"] != expected_quantity:
            raise ValueError(
                f"{name}: {item.get('name', item['id'])} requires quantity "
                f"{expected_quantity}, got {usage['quantity']}"
            )
    if exercise_type == "BODY_WEIGHT":
        if (
            not isinstance(body_weight_percentage, (int, float))
            or isinstance(body_weight_percentage, bool)
            or not 1 < body_weight_percentage <= 100
        ):
            raise ValueError(
                f"{name}: BODY_WEIGHT requires movement-specific percentage semantics in (1, 100]"
            )
    elif body_weight_percentage is not None:
        raise ValueError(f"{name}: non-BODY_WEIGHT bodyWeightPercentage must be null")

    return {
        "name": name.strip(),
        "exerciseType": exercise_type,
        "equipmentId": equipment_id,
        "bodyWeightPercentage": body_weight_percentage,
        "requiredAccessoryEquipmentIds": list(required_accessories),
        **(
            {"executionMode": candidate["executionMode"]}
            if candidate.get("executionMode") in EXECUTION_MODES
            else {}
        ),
        **(
            {"resistanceMode": candidate["resistanceMode"]}
            if candidate.get("resistanceMode") in RESISTANCE_MODES
            else {}
        ),
        **(
            {"movementKey": candidate["movementKey"].strip()}
            if isinstance(candidate.get("movementKey"), str)
            and candidate["movementKey"].strip()
            else {}
        ),
        "exerciseCategory": _derive_exercise_category(candidate),
        "requiredCapabilities": list(candidate["requiredCapabilities"]),
        "implementUsage": copy.deepcopy(candidate["implementUsage"]),
        "jointDemand": candidate["jointDemand"],
        "loadingDemand": candidate["loadingDemand"],
        "warmupDemand": candidate["warmupDemand"],
    }


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str, str | None]:
    return (
        candidate["name"].strip().casefold(),
        candidate["exerciseType"],
        candidate.get("equipmentId"),
    )


def _parse_inventory(
    content: str | None,
    equipment: dict[str, Any],
    allowed_equipment_ids: set[str] | None = None,
    recover_all_invalid: bool = False,
    require_any_accessory: bool = False,
) -> list[dict[str, Any]]:
    payload = _json_object(content, "exercise inventory")
    raw_exercises = payload.get("exercises")
    if not isinstance(raw_exercises, list):
        raise ValueError("Exercise inventory must contain an exercises array")
    exercises: list[dict[str, Any]] = []
    seen = set()
    rejected = []
    for raw_candidate in raw_exercises:
        try:
            candidate = _validate_candidate(
                raw_candidate,
                equipment,
                allowed_equipment_ids=allowed_equipment_ids,
                require_any_accessory=require_any_accessory,
            )
        except ValueError as error:
            rejected.append(str(error))
            continue
        key = _candidate_key(candidate)
        if key not in seen:
            seen.add(key)
            exercises.append(candidate)
    if rejected:
        print(
            f"Inventory validation recovered by rejecting {len(rejected)} invalid candidate(s).",
            flush=True,
        )
        for error in rejected[:5]:
            print(f"  - {error}", flush=True)
    if raw_exercises and not exercises and not recover_all_invalid:
        raise ValueError(
            "Every inventory candidate was invalid. First errors: " + "; ".join(rejected[:3])
        )
    body_weight_values = [
        float(exercise["bodyWeightPercentage"])
        for exercise in exercises
        if exercise["exerciseType"] == "BODY_WEIGHT"
    ]
    if len(body_weight_values) >= 8:
        most_common_count = Counter(body_weight_values).most_common(1)[0][1]
        if most_common_count / len(body_weight_values) >= 0.9:
            raise ValueError(
                "BODY_WEIGHT estimates are implausibly uniform; estimate the effective body-mass "
                "percentage independently for each movement instead of using one default"
            )
    return exercises


def _call_inventory(
    client: Any,
    equipment: dict[str, Any],
    request: str,
    *,
    audit_existing: list[dict[str, Any]] | None = None,
    scope_description: str | None = None,
    allowed_equipment_ids: set[str] | None = None,
    require_any_accessory: bool = False,
    show_loading: bool = True,
    call_json: Callable[..., str | None] = json_call_reasoner_only_with_loading,
) -> list[dict[str, Any]]:
    equipment_context = _format_equipment_context(equipment)
    system_prompt = AUDIT_SYSTEM_PROMPT if audit_existing is not None else INVENTORY_SYSTEM_PROMPT
    user_parts = [equipment_context, f"User scope request:\n{request.strip() or 'No additional restrictions.'}"]
    user_parts.append(
        "Available capability enum values (requiredCapabilities may contain only these):\n"
        + json.dumps(sorted(_available_capabilities(equipment)), ensure_ascii=False)
    )
    example_primary_id = (
        next(iter(allowed_equipment_ids), None)
        if allowed_equipment_ids is not None
        else None
    )
    example_accessory_ids = (
        [next(iter(sorted(_equipment_ids(equipment)[1])))]
        if require_any_accessory and _equipment_ids(equipment)[1]
        else []
    )
    example_usage_ids = [
        item_id for item_id in [example_primary_id, *example_accessory_ids] if item_id is not None
    ]
    user_parts.append(
        "Required JSON candidate schema (every item must match exactly; no extra properties):\n"
        + json.dumps(INVENTORY_CANDIDATE_SCHEMA, indent=2)
        + "\nExample JSON output:\n"
        + json.dumps(
            {
                "exercises": [
                    {
                        "name": "Example Exercise",
                        "exerciseType": (
                            "BODY_WEIGHT" if allowed_equipment_ids == set() else "WEIGHT"
                        ),
                        "equipmentId": example_primary_id,
                        "bodyWeightPercentage": (
                            100.0 if allowed_equipment_ids == set() else None
                        ),
                        "requiredAccessoryEquipmentIds": example_accessory_ids,
                        "executionMode": "REPETITIONS",
                        "resistanceMode": (
                            "BODY_WEIGHT" if allowed_equipment_ids == set() else "EXTERNAL_LOAD"
                        ),
                        "movementKey": "example-exercise",
                        "exerciseCategory": "MODERATE_COMPOUND",
                        "requiredCapabilities": [
                            f"USE_EQUIPMENT:{item_id}" for item_id in example_usage_ids
                        ],
                        "implementUsage": [
                            {
                                "equipmentId": item_id,
                                "quantity": {
                                    "DUMBBELL": 1,
                                    "DUMBBELLS": 2,
                                }.get(
                                    _all_equipment_items(equipment)
                                    .get(item_id, {})
                                    .get("type"),
                                    1,
                                ),
                            }
                            for item_id in example_usage_ids
                        ],
                        "jointDemand": "MULTI_JOINT",
                        "loadingDemand": "MODERATE",
                        "warmupDemand": "MODERATE",
                    }
                ]
            },
            indent=2,
        )
    )
    if scope_description:
        user_parts.append(
            "This request is one bounded inventory batch. Return exercises only for this scope:\n"
            + scope_description
        )
    if audit_existing is not None:
        user_parts.append(
            "Existing inventory to audit:\n" + json.dumps(audit_existing, ensure_ascii=False)
        )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
    loading_message = (
        "Auditing exercise coverage" if audit_existing is not None else "Enumerating exercises"
    )
    last_error = None
    for attempt in range(1, 4):
        if attempt > 1:
            print(f"{loading_message}: retrying ({attempt}/3).", flush=True)
        content = call_json(
            client,
            messages,
            loading_message,
            **({"show_loading": False} if not show_loading else {}),
        )
        try:
            parsed = _parse_inventory(
                content,
                equipment,
                allowed_equipment_ids=allowed_equipment_ids,
                recover_all_invalid=audit_existing is not None,
                require_any_accessory=require_any_accessory,
            )
            print(
                f"{loading_message}: received {len(parsed)} valid distinct candidate(s).",
                flush=True,
            )
            return parsed
        except ValueError as error:
            last_error = error
            messages.append({"role": "assistant", "content": content or ""})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Validation failed: {error}. Correct the inventory and return the "
                        "complete JSON object only."
                    ),
                }
            )
    raise ValueError(f"Could not produce a valid exercise inventory: {last_error}")


def _unwrap_definition_object(raw_definition: Any) -> dict[str, Any]:
    if not isinstance(raw_definition, dict):
        raise ValueError("Exercise definition must be an object")
    if isinstance(raw_definition.get("exerciseDefinition"), dict):
        return raw_definition["exerciseDefinition"]
    elif isinstance(raw_definition.get("definition"), dict):
        return raw_definition["definition"]
    elif (
        isinstance(raw_definition.get("exerciseDefinitions"), list)
        and len(raw_definition["exerciseDefinitions"]) == 1
        and isinstance(raw_definition["exerciseDefinitions"][0], dict)
    ):
        return raw_definition["exerciseDefinitions"][0]
    return raw_definition


def _validate_definition(
    raw_definition: Any,
    candidate: dict[str, Any],
    equipment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_definition = _unwrap_definition_object(raw_definition)

    definition = {
        field: copy.deepcopy(candidate.get(field))
        for field in (
            "name",
            "exerciseType",
            "equipmentId",
            "bodyWeightPercentage",
            "requiredAccessoryEquipmentIds",
        )
    }
    for field in (
        "name", "exerciseType", "equipmentId", "bodyWeightPercentage",
        "requiredAccessoryEquipmentIds",
    ):
        if raw_definition.get(field) != candidate.get(field):
            raise DefinitionValidationError(
                f"Definition changed candidate-owned field {field}",
                {f"/{field}"},
            )

    primary_muscles = raw_definition.get("muscleGroups")
    if primary_muscles is None:
        primary_muscles = raw_definition.get("primaryMuscleGroups")
    if primary_muscles is None:
        primary_muscles = raw_definition.get("primaryMuscles")
    secondary_muscles = raw_definition.get("secondaryMuscleGroups")
    if secondary_muscles is None:
        secondary_muscles = []
    category = raw_definition.get("exerciseCategory")
    if not isinstance(primary_muscles, list) or not primary_muscles:
        raise DefinitionValidationError(
            "Definition requires at least one primary muscle group",
            {"/muscleGroups"},
        )
    if not isinstance(secondary_muscles, list):
        raise DefinitionValidationError(
            "Definition secondaryMuscleGroups must be an array",
            {"/secondaryMuscleGroups"},
        )
    invalid_primary_muscles = [
        muscle
        for muscle in primary_muscles
        if not isinstance(muscle, str) or not fix_muscle_groups([muscle])
    ]
    invalid_secondary_muscles = [
        muscle
        for muscle in secondary_muscles
        if not isinstance(muscle, str) or not fix_muscle_groups([muscle])
    ]
    if invalid_primary_muscles or invalid_secondary_muscles:
        invalid_details = []
        if invalid_primary_muscles:
            invalid_details.append(f"/muscleGroups: {invalid_primary_muscles!r}")
        if invalid_secondary_muscles:
            invalid_details.append(
                f"/secondaryMuscleGroups: {invalid_secondary_muscles!r}"
            )
        repair_paths = set()
        if invalid_primary_muscles:
            repair_paths.add("/muscleGroups")
        if invalid_secondary_muscles:
            repair_paths.add("/secondaryMuscleGroups")
        raise DefinitionValidationError(
            "Definition contains muscle groups outside the allowed enum list at "
            + "; ".join(invalid_details),
            repair_paths,
        )

    primary_muscles = list(dict.fromkeys(fix_muscle_groups(primary_muscles)))
    secondary_muscles = list(dict.fromkeys(fix_muscle_groups(secondary_muscles)))
    secondary_muscles = [muscle for muscle in secondary_muscles if muscle not in primary_muscles]
    if not primary_muscles:
        raise DefinitionValidationError(
            "Definition requires at least one valid primary muscle group",
            {"/muscleGroups"},
        )
    invalid_primary_regions = [
        muscle for muscle in primary_muscles if muscle in NON_MUSCLE_PRIMARY_GROUPS
    ]
    if invalid_primary_regions:
        raise DefinitionValidationError(
            f"Definition primary muscles contain joints or contact regions: {invalid_primary_regions}",
            {"/muscleGroups"},
        )
    if len(primary_muscles) > 3:
        raise DefinitionValidationError(
            "Definition has more than three primary muscle regions; keep only actual prime movers",
            {"/muscleGroups"},
        )
    if len(secondary_muscles) > 3:
        raise DefinitionValidationError(
            "Definition has more than three secondary muscle regions; remove incidental regions",
            {"/secondaryMuscleGroups"},
        )

    if candidate["exerciseType"] in {"COUNTUP", "COUNTDOWN"}:
        category = None
    else:
        category = candidate.get("exerciseCategory") or category
        if category not in EXERCISE_CATEGORIES:
            raise DefinitionValidationError(
                "Definition exerciseCategory must use an allowed app enum",
                {"/exerciseCategory"},
            )

    definition.update(
        muscleGroups=primary_muscles,
        secondaryMuscleGroups=secondary_muscles,
        exerciseCategory=category,
    )
    definition["id"] = build_exercise_definition_id(definition)
    return definition


def _repair_definition_with_json_patch(
    client: Any,
    definition: dict[str, Any],
    candidate: dict[str, Any],
    validation_error: DefinitionValidationError,
    caller: Callable[..., str | None],
) -> dict[str, Any]:
    allowed_paths = validation_error.repair_paths
    if not allowed_paths:
        raise ValueError("Definition validation error has no patchable paths")
    messages = [
        {
            "role": "system",
            "content": (
                "You repair an ExerciseDefinition using JSON Patch (RFC 6902). Return JSON "
                "only as {\"patch\": [...]}. Change only the explicitly allowed paths. "
                "Every muscle value must be selected exactly from the supplied allowed enum "
                "list. Candidate-owned fields must exactly match the supplied candidate. "
                "Do not change any unrelated field."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Validation error:\n{validation_error}\n\n"
                "Allowed patch paths:\n"
                + ", ".join(sorted(allowed_paths))
                + "\n\nCandidate-owned values:\n"
                + json.dumps(candidate, indent=2, ensure_ascii=False)
                + "\n\n"
                "Allowed muscle enum values:\n"
                + ", ".join(sorted(MUSCLE_GROUPS))
                + "\n\nDefinition to patch:\n"
                + json.dumps(definition, indent=2, ensure_ascii=False)
            ),
        },
    ]
    content = caller(client, messages, "", show_loading=False)
    payload = json.loads(content or "")
    if isinstance(payload, list):
        patch_operations = payload
    elif isinstance(payload, dict) and isinstance(payload.get("patch"), list):
        patch_operations = payload["patch"]
    else:
        raise ValueError("Definition repair must return an RFC 6902 patch array")

    validate_patch_operations_scope(
        patch_operations,
        allowed_paths,
        allowed_paths,
    )
    repaired = apply_json_patch(definition, patch_operations)
    changed_paths = collect_changed_json_paths(definition, repaired)
    validate_changed_paths_scope(
        changed_paths,
        allowed_paths,
        allowed_paths,
    )
    return repaired


def _repair_definition_muscles_with_json_patch(
    client: Any,
    definition: dict[str, Any],
    validation_error: ValueError,
    caller: Callable[..., str | None],
) -> dict[str, Any]:
    """Compatibility wrapper for the focused muscle-repair entry point."""
    scoped_error = DefinitionValidationError(str(validation_error), MUSCLE_PATCH_PATHS)
    candidate = {
        field: definition.get(field)
        for field in (
            "name",
            "exerciseType",
            "equipmentId",
            "bodyWeightPercentage",
            "requiredAccessoryEquipmentIds",
        )
    }
    return _repair_definition_with_json_patch(
        client,
        definition,
        candidate,
        scoped_error,
        caller,
    )


def _emit_definition(
    client: Any,
    candidate: dict[str, Any],
    *,
    equipment: dict[str, Any] | None = None,
    use_reasoner: bool,
    call_reasoner: Callable[..., str | None],
    call_chat: Callable[..., str | None],
) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": DEFINITION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Valid muscle enum values:\n"
                + ", ".join(sorted(MUSCLE_GROUPS))
                + "\n\nValid exerciseCategory values for WEIGHT/BODY_WEIGHT:\n"
                + ", ".join(sorted(EXERCISE_CATEGORIES))
                + "\nUse null exerciseCategory for COUNTUP/COUNTDOWN."
                + (
                    "\n\nAvailable equipment context:\n"
                    + _format_equipment_context(equipment)
                    if equipment is not None
                    else ""
                )
                + "\n\nCandidate:\n"
                + json.dumps(candidate, indent=2, ensure_ascii=False)
            ),
        },
    ]
    caller = call_reasoner if use_reasoner else call_chat
    last_error = None
    for attempt in range(3):
        try:
            content = caller(client, messages, "", show_loading=False)
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(2.0 * (attempt + 1))
            continue
        try:
            raw_definition = _unwrap_definition_object(
                _json_object(content, "exercise definition")
            )
            for _repair_attempt in range(3):
                try:
                    return _validate_definition(raw_definition, candidate, equipment)
                except DefinitionValidationError as error:
                    last_error = error
                    if not error.repair_paths:
                        break
                    raw_definition = _repair_definition_with_json_patch(
                        client,
                        raw_definition,
                        candidate,
                        error,
                        caller,
                    )
            return _validate_definition(raw_definition, candidate, equipment)
        except ValueError as error:
            last_error = error
            messages.append({"role": "assistant", "content": content or ""})
            messages.append(
                {
                    "role": "user",
                    "content": f"Validation failed: {error}. Return a corrected definition object only.",
                }
            )
    raise ValueError(f"Could not emit {candidate['name']}: {last_error}")


def _run_semantic_review(
    client: Any,
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    *,
    max_workers: int,
    semantic_review_call: Callable[..., str | None],
    batch_size: int = SEMANTIC_REVIEW_BATCH_SIZE,
    completed_batch_results: dict[int, tuple[list[dict[str, Any]], list[str]]] | None = None,
    batch_completed_callback: Callable[[int, list[dict[str, Any]], list[str]], None] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    batches = [
        definitions[index:index + batch_size]
        for index in range(0, len(definitions), batch_size)
    ]
    print(
        f"Stage 4/4: Independently reviewing {len(definitions)} definition(s) in "
        f"{len(batches)} batch(es).",
        flush=True,
    )
    ordered_results = dict(completed_batch_results or {})
    invalid_completed_indexes = set(ordered_results) - set(range(len(batches)))
    if invalid_completed_indexes:
        raise ValueError(f"Review checkpoint has invalid completed batch indexes: {sorted(invalid_completed_indexes)}")
    if ordered_results:
        print(
            f"Resuming with {len(ordered_results)}/{len(batches)} semantic review batch(es) already complete.",
            flush=True,
        )
    review_worker_count = min(max(1, max_workers), len(batches))
    review_started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=review_worker_count) as executor:
        future_to_index = {
            executor.submit(
                _review_definition_batch_resilient,
                client,
                batch,
                equipment,
                semantic_review_call,
                f"Review batch {index + 1}/{len(batches)}",
            ): index
            for index, batch in enumerate(batches)
            if index not in ordered_results
        }
        pending = set(future_to_index)
        completed_count = len(ordered_results)
        batch_errors: list[str] = []
        stop_scheduling = False
        while pending:
            completed, pending = wait(pending, timeout=30.0, return_when=FIRST_COMPLETED)
            if not completed:
                elapsed = int(time.monotonic() - review_started_at)
                active_batches = sorted(
                    future_to_index[future] + 1 for future in pending if future.running()
                )
                queued_count = sum(1 for future in pending if not future.running())
                print(
                    f"Semantic review still running: {completed_count}/{len(batches)} complete, "
                    f"active batches {active_batches}, {queued_count} queued ({elapsed}s elapsed).",
                    flush=True,
                )
                continue
            for future in completed:
                batch_index = future_to_index[future]
                if future.cancelled():
                    continue
                try:
                    ordered_results[batch_index] = future.result()
                except Exception as error:
                    failure = f"Semantic review batch {batch_index + 1} failed: {error}"
                    batch_errors.append(failure)
                    print(failure, flush=True)
                    if not stop_scheduling:
                        stop_scheduling = True
                        cancelled_count = 0
                        for queued_future in list(pending):
                            if queued_future.cancel():
                                pending.remove(queued_future)
                                cancelled_count += 1
                        if cancelled_count:
                            print(
                                f"Cancelled {cancelled_count} queued batch(es); waiting only for "
                                "requests already in flight so their successful results can be saved.",
                                flush=True,
                            )
                    continue
                completed_count += 1
                if batch_completed_callback is not None:
                    kept, discarded = ordered_results[batch_index]
                    batch_completed_callback(batch_index, kept, discarded)
                print(
                    f"Semantic review batches complete: {completed_count}/{len(batches)}",
                    flush=True,
                )
        if batch_errors:
            raise RuntimeError(
                f"{len(batch_errors)} semantic review batch(es) failed. Completed batches were "
                f"saved and will be skipped on retry. First failure: {batch_errors[0]}"
            )
    reviewed_definitions = []
    semantic_discards = []
    for batch_index in range(len(batches)):
        kept, discarded = ordered_results[batch_index]
        reviewed_definitions.extend(kept)
        semantic_discards.extend(discarded)
    reviewed_definitions, collision_discards = _deduplicate_reviewed_definitions(
        reviewed_definitions
    )
    semantic_discards.extend(collision_discards)
    print(
        f"Semantic review kept {len(reviewed_definitions)} definition(s) and discarded "
        f"{len(semantic_discards)} infeasible definition(s).",
        flush=True,
    )
    return reviewed_definitions, semantic_discards


def _request_complete_requirement_groups(
    client: Any,
    equipment_context: str,
    decisions: list[dict[str, Any]],
    call_json: Callable[..., str | None],
    batch_label: str,
) -> list[dict[str, Any]]:
    valid_ids = {decision["id"] for decision in decisions}
    system_prompt = (
        "Build a semantic physical-requirement matrix for every supplied exercise. Compare "
        "physical setup, execution, transition, finish, and unloading requirements even when "
        "names differ. Return JSON only as {\"groups\":[{\"setup\":string,"
        "\"memberIds\":[string],\"requirementClauses\":[{\"anyOf\":[string]}],"
        "\"missingEquipment\":[string],\"rationale\":string}]}. Every supplied definition "
        "must appear exactly once. Group equivalent setups together. Empty requirements mean "
        "the setup is feasible with declared equipment. Requirements must be physically "
        "mandatory, never optional, conventional, or a programming convenience. Do not directly "
        "choose keep/discard. Apply these capability meanings: "
        + json.dumps(CAPABILITY_SEMANTICS, ensure_ascii=False)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                {"equipment": equipment_context, "decisions": decisions},
                ensure_ascii=False,
            ),
        },
    ]
    last_error: Exception | None = None
    for attempt in range(1, 4):
        content = call_json(client, messages, batch_label, show_loading=False)
        try:
            payload = _json_object(content, "global requirement matrix batch")
            groups = payload.get("groups")
            if not isinstance(groups, list):
                raise ValueError("Requirement matrix batch must contain a groups array")
            groups = [
                _normalize_matrix_group_requirements(group)
                if isinstance(group, dict)
                else group
                for group in groups
            ]
            grouped_ids = []
            for group in groups:
                if (
                    not isinstance(group, dict)
                    or set(group) != {
                        "setup", "memberIds", "requirementClauses",
                        "missingEquipment", "rationale",
                    }
                    or not isinstance(group.get("setup"), str)
                    or not group["setup"].strip()
                    or not isinstance(group.get("memberIds"), list)
                    or not group["memberIds"]
                    or any(member_id not in valid_ids for member_id in group["memberIds"])
                    or not isinstance(group.get("rationale"), str)
                    or not group["rationale"].strip()
                ):
                    raise ValueError("Requirement matrix batch contains an invalid group")
                _requirement_signature(
                    {
                        "requiredEquipmentIds": [],
                        "requirementClauses": group.get("requirementClauses"),
                        "missingEquipment": group.get("missingEquipment"),
                    }
                )
                _reject_contradictory_matrix_group(group)
                unknown = {
                    capability
                    for clause in group["requirementClauses"]
                    for capability in clause["anyOf"]
                    if capability not in EQUIPMENT_CAPABILITY_CATALOG
                }
                if unknown:
                    raise ValueError(f"Requirement matrix used unknown capabilities: {sorted(unknown)}")
                grouped_ids.extend(group["memberIds"])
            if len(grouped_ids) != len(set(grouped_ids)) or set(grouped_ids) != valid_ids:
                raise ValueError("Requirement matrix batch must cover every definition exactly once")
            return groups
        except (ValueError, json.JSONDecodeError) as error:
            last_error = error
            if attempt == 3:
                break
            messages.extend(
                [
                    {"role": "assistant", "content": content or ""},
                    {
                        "role": "user",
                        "content": f"Validation failed: {error}. Return a corrected object only.",
                    },
                ]
            )
    raise ValueError(
        f"Could not produce a complete {batch_label}: {last_error}"
    )


def _normalize_matrix_group_requirements(group: dict[str, Any]) -> dict[str, Any]:
    normalized_group = copy.deepcopy(group)
    clauses = normalized_group.get("requirementClauses")
    missing = normalized_group.get("missingEquipment")
    if not isinstance(clauses, list) or not isinstance(missing, list):
        return normalized_group
    normalized_missing = []
    for value in missing:
        if not isinstance(value, str):
            normalized_missing.append(value)
            continue
        token = re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")
        capability = None
        if token in EQUIPMENT_CAPABILITY_CATALOG:
            capability = token
        else:
            suffix_matches = [
                candidate
                for candidate in EQUIPMENT_CAPABILITY_CATALOG
                if token.endswith(candidate)
                or (
                    "_" in candidate
                    and token.endswith("_".join(candidate.split("_")[-2:]))
                )
            ]
            if len(suffix_matches) == 1:
                capability = suffix_matches[0]
        if capability is None:
            normalized_missing.append(value)
        else:
            clauses.append({"anyOf": [capability]})
    deduplicated_clauses = []
    seen_clauses = set()
    for clause in clauses:
        if not isinstance(clause, dict) or not isinstance(clause.get("anyOf"), list):
            deduplicated_clauses.append(clause)
            continue
        normalized_alternatives = tuple(sorted(set(clause["anyOf"])))
        if normalized_alternatives and normalized_alternatives not in seen_clauses:
            seen_clauses.add(normalized_alternatives)
            deduplicated_clauses.append({"anyOf": list(normalized_alternatives)})
    normalized_group["requirementClauses"] = deduplicated_clauses
    normalized_group["missingEquipment"] = normalized_missing
    return normalized_group


def _reject_contradictory_matrix_group(group: dict[str, Any]) -> None:
    has_requirements = bool(group.get("requirementClauses") or group.get("missingEquipment"))
    rationale = str(group.get("rationale") or "")
    claims_requirements_are_available = re.search(
        r"\b(?:already (?:present|available|provided)|are present|is present|"
        r"no additional (?:equipment|capability|support) (?:is )?required)\b",
        rationale,
        re.I,
    )
    if has_requirements and claims_requirements_are_available:
        raise ValueError(
            "Requirement matrix group contradicts itself by declaring a requirement missing "
            "while its rationale says that requirement is present or unnecessary"
        )


def _run_global_semantic_consistency_review(
    client: Any,
    source_definitions: list[dict[str, Any]],
    reviewed_definitions: list[dict[str, Any]],
    semantic_discards: list[str],
    equipment: dict[str, Any],
    call_json: Callable[..., str | None],
    completed_matrix_batches: dict[int, list[dict[str, Any]]] | None = None,
    matrix_batch_completed_callback: Callable[[int, list[dict[str, Any]]], None] | None = None,
    verified_matrix_callback: Callable[[list[dict[str, Any]]], None] | None = None,
    matrix_max_workers: int = 2,
    instruction_entailment_call: Callable[..., str | None] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if len(source_definitions) < 2:
        return reviewed_definitions, semantic_discards
    equipment_context, _, id_to_reference = _review_equipment_context(equipment)
    referenced_sources = _definitions_with_equipment_references(
        source_definitions, id_to_reference
    )
    reviewed_by_id = {definition["id"]: definition for definition in reviewed_definitions}
    reviewed_by_name = {
        definition["name"].strip().casefold(): definition
        for definition in reviewed_definitions
    }
    discard_by_name = {}
    for reason in semantic_discards:
        name, separator, _ = reason.partition(":")
        if separator:
            discard_by_name[name.strip().casefold()] = reason

    decisions = []
    for definition in referenced_sources:
        source_id = definition["id"]
        normalized_name = definition["name"].strip().casefold()
        discard_reason = discard_by_name.get(normalized_name)
        decisions.append(
            {
                "id": source_id,
                "name": definition["name"],
                "instructions": definition["instructions"],
                "equipmentId": definition.get("equipmentId"),
                "requiredAccessoryEquipmentIds": definition.get(
                    "requiredAccessoryEquipmentIds", []
                ),
                "currentDecision": "DISCARD" if discard_reason else "KEEP",
                "currentReason": discard_reason or "",
            }
        )

    valid_source_ids = {definition["id"] for definition in source_definitions}
    matrix_batch_size = 40
    decision_batches = [
        decisions[index:index + matrix_batch_size]
        for index in range(0, len(decisions), matrix_batch_size)
    ]
    completed_matrix_batches = dict(completed_matrix_batches or {})
    groups_by_batch = {
        index: copy.deepcopy(batch_groups)
        for index, batch_groups in completed_matrix_batches.items()
        if 0 <= index < len(decision_batches)
    }
    print(
        f"Building complete semantic requirement matrix in {len(decision_batches)} batch(es) "
        f"with up to {min(max(1, matrix_max_workers), len(decision_batches))} concurrent request(s).",
        flush=True,
    )
    pending_batches = [
        (index, decision_batch)
        for index, decision_batch in enumerate(decision_batches)
        if index not in groups_by_batch
    ]
    completed_count = len(groups_by_batch)
    if completed_count:
        print(
            f"Resuming with {completed_count}/{len(decision_batches)} global matrix batch(es) complete.",
            flush=True,
        )
    worker_count = min(max(1, matrix_max_workers), max(1, len(pending_batches)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _request_complete_requirement_groups,
                client,
                equipment_context,
                decision_batch,
                call_json,
                f"Global matrix batch {index + 1}/{len(decision_batches)}",
            ): index
            for index, decision_batch in pending_batches
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            batch_groups = future.result()
            groups_by_batch[index] = copy.deepcopy(batch_groups)
            completed_count += 1
            if matrix_batch_completed_callback is not None:
                matrix_batch_completed_callback(index, batch_groups)
            print(
                f"Global matrix batches complete: {completed_count}/{len(decision_batches)}",
                flush=True,
            )
    groups = [
        group
        for index in range(len(decision_batches))
        for group in groups_by_batch[index]
    ]

    verification_messages = [
        {
            "role": "system",
            "content": (
                "Verify the global physical-requirement matrix. Return JSON only as "
                "{\"patch\":[RFC 6902 operations]}. Correct omissions, wrongly grouped "
                "definitions, and requirements that are optional rather than mandatory. Preserve "
                "exactly-once coverage of every supplied definition ID. Every "
                "path must be /groups or below it. Do not directly choose keep/discard. Apply "
                "the supplied capability semantics and return an empty patch if correct."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "equipment": equipment_context,
                    "decisions": decisions,
                    "capabilitySemantics": CAPABILITY_SEMANTICS,
                    "matrix": {"groups": groups},
                },
                ensure_ascii=False,
            ),
        },
    ]
    print(
        "Matrix construction complete. Starting final cross-batch semantic verification.",
        flush=True,
    )
    verification_content = call_json(
        client,
        verification_messages,
        "Verifying global requirement matrix",
        show_loading=True,
    )
    verification_payload = _json_object(
        verification_content, "global requirement matrix verification"
    )
    operations = verification_payload.get("patch")
    if not isinstance(operations, list):
        raise ValueError("Global requirement matrix verification must contain a patch array")
    for operation in operations:
        path = operation.get("path") if isinstance(operation, dict) else None
        if not isinstance(path, str) or not (path == "/groups" or path.startswith("/groups/")):
            raise ValueError("Global requirement matrix verification used an out-of-scope path")
    verified_matrix = apply_json_patch({"groups": groups}, operations)
    if not isinstance(verified_matrix, dict) or not isinstance(verified_matrix.get("groups"), list):
        raise ValueError("Global requirement matrix verification produced an invalid matrix")
    groups = [
        _normalize_matrix_group_requirements(group)
        if isinstance(group, dict)
        else group
        for group in verified_matrix["groups"]
    ]
    if verified_matrix_callback is not None:
        verified_matrix_callback(groups)
    verified_member_ids = []
    for group in groups:
        if (
            not isinstance(group, dict)
            or set(group) != {
                "setup", "memberIds", "requirementClauses", "missingEquipment", "rationale"
            }
            or not isinstance(group.get("setup"), str)
            or not group["setup"].strip()
            or not isinstance(group.get("memberIds"), list)
            or not group["memberIds"]
            or any(member_id not in valid_source_ids for member_id in group["memberIds"])
            or not isinstance(group.get("rationale"), str)
            or not group["rationale"].strip()
        ):
            raise ValueError("Verified global requirement matrix contains an invalid group")
        _requirement_signature(
            {
                "requiredEquipmentIds": [],
                "requirementClauses": group.get("requirementClauses"),
                "missingEquipment": group.get("missingEquipment"),
            }
        )
        _reject_contradictory_matrix_group(group)
        unknown = {
            capability
            for clause in group["requirementClauses"]
            for capability in clause["anyOf"]
            if capability not in EQUIPMENT_CAPABILITY_CATALOG
        }
        if unknown:
            raise ValueError(
                f"Verified global matrix used unknown capabilities: {sorted(unknown)}"
            )
        verified_member_ids.extend(group["memberIds"])
    if len(verified_member_ids) != len(set(verified_member_ids)):
        raise ValueError("Verified global matrix assigned an ID to multiple groups")
    if set(verified_member_ids) != valid_source_ids:
        raise ValueError("Verified global matrix does not cover every definition exactly once")

    group_by_member = {
        member_id: group for group in groups for member_id in group.get("memberIds", [])
    }
    kept = []
    discarded = []
    for source in source_definitions:
        source_id = source["id"]
        normalized_name = source["name"].strip().casefold()
        existing = reviewed_by_id.get(source_id) or reviewed_by_name.get(normalized_name)
        was_feasible = existing is not None and normalized_name not in discard_by_name
        group = group_by_member[source_id]
        is_feasible = was_feasible
        reason = discard_by_name.get(normalized_name, "globally inconsistent or infeasible")
        declared_ids = {
            value
            for value in [
                source.get("equipmentId"),
                *source.get("requiredAccessoryEquipmentIds", []),
            ]
            if value is not None
        }
        available_capabilities = _capabilities_for_equipment_ids(equipment, declared_ids)
        unsatisfied = [
            clause["anyOf"]
            for clause in group["requirementClauses"]
            if not set(clause["anyOf"]).intersection(available_capabilities)
        ]
        missing = group["missingEquipment"]
        is_feasible = not unsatisfied and not missing
        reason = group["rationale"].strip()
        if unsatisfied:
            reason += f"; unsatisfied capability alternatives {unsatisfied}"
        if missing:
            reason += "; missing equipment " + ", ".join(missing)
        if is_feasible:
            kept.append(copy.deepcopy(existing or source))
        else:
            if reason.startswith(f"{source['name']}:"):
                discarded.append(reason)
            else:
                discarded.append(f"{source['name']}: {reason}")
    kept, collision_discards = _deduplicate_reviewed_definitions(kept)
    discarded.extend(collision_discards)
    print(
        f"Global consistency audit kept {len(kept)} definition(s) and discarded "
        f"{len(discarded)} definition(s).",
        flush=True,
    )
    if instruction_entailment_call is None:
        return kept, discarded
    return _run_instruction_entailment_audit(
        client,
        kept,
        discarded,
        equipment,
        instruction_entailment_call or call_json,
    )


def _validated_instruction_requirements(
    audit: dict[str, Any],
    patched_definition: dict[str, Any],
    declared_equipment_references: set[str],
) -> list[dict[str, list[str]]]:
    requirements = audit.get("requirements")
    if not isinstance(requirements, list):
        raise ValueError(f"{patched_definition['name']}: requirements must be an array")
    mandatory_clauses: list[dict[str, list[str]]] = []
    referenced_equipment: set[str] = set()
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict) or set(requirement) != {
            "evidence", "anyOfEquipmentRefs", "anyOfCapabilities", "mandatory"
        }:
            raise ValueError(
                f"{patched_definition['name']}: requirement {index} has invalid fields"
            )
        evidence = requirement.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(
                f"{patched_definition['name']}: requirement {index} has invalid evidence"
            )
        if evidence.casefold() not in patched_definition["instructions"].casefold():
            raise ValueError(
                f"{patched_definition['name']}: requirement {index} evidence is not an exact "
                f"instruction substring: {evidence!r}"
            )
        equipment_alternatives = requirement.get("anyOfEquipmentRefs")
        if not isinstance(equipment_alternatives, list):
            raise ValueError(
                f"{patched_definition['name']}: requirement {index} equipment alternatives "
                "must be an array"
            )
        unknown_equipment = [
            reference
            for reference in equipment_alternatives
            if reference not in declared_equipment_references
        ]
        if unknown_equipment:
            raise ValueError(
                f"{patched_definition['name']}: requirement {index} used undeclared equipment "
                f"references {unknown_equipment}"
            )
        capability_alternatives = requirement.get("anyOfCapabilities")
        if not isinstance(capability_alternatives, list):
            raise ValueError(
                f"{patched_definition['name']}: requirement {index} capability alternatives "
                "must be an array"
            )
        if not equipment_alternatives and not capability_alternatives:
            raise ValueError(
                f"{patched_definition['name']}: requirement {index} needs equipment or "
                "capability alternatives"
            )
        unknown = [
            capability
            for capability in capability_alternatives
            if capability not in EQUIPMENT_CAPABILITY_CATALOG
        ]
        if unknown:
            raise ValueError(
                f"{patched_definition['name']}: requirement {index} used unknown capabilities "
                f"{unknown}"
            )
        if not isinstance(requirement.get("mandatory"), bool):
            raise ValueError(
                f"{patched_definition['name']}: requirement {index} mandatory must be boolean"
            )
        if requirement["mandatory"]:
            mandatory_clauses.append({
                "equipmentRefs": list(dict.fromkeys(equipment_alternatives)),
                "capabilities": list(dict.fromkeys(capability_alternatives)),
            })
            referenced_equipment.update(equipment_alternatives)
    missing_declared_equipment = declared_equipment_references - referenced_equipment
    if missing_declared_equipment:
        raise ValueError(
            f"{patched_definition['name']}: instructions do not account for declared equipment "
            f"references {sorted(missing_declared_equipment)}"
        )
    return mandatory_clauses


def _semantic_equipment_reference_stem(reference: str) -> str:
    stem = re.sub(r"^(?:PRIMARY|ACCESSORY)_", "", reference.strip().upper())
    stem = re.sub(r"_\d+$", "", stem)
    return "_".join(
        token[:-1] if token.endswith("S") and len(token) > 3 else token
        for token in stem.split("_")
    )


def _canonicalize_instruction_requirement_shape(audit: dict[str, Any]) -> dict[str, Any]:
    canonical = copy.deepcopy(audit)
    requirements = canonical.get("requirements")
    if isinstance(requirements, dict):
        wrapped_requirements = requirements.get("requirements")
        if not isinstance(wrapped_requirements, list):
            wrapped_requirements = requirements.get("items")
        if isinstance(wrapped_requirements, list):
            requirements = wrapped_requirements
        elif any(
            field in requirements
            for field in (
                "evidence",
                "instructionEvidence",
                "quote",
                "anyOfEquipmentRefs",
                "equipmentRefs",
                "equipmentRef",
                "anyOfCapabilities",
                "capabilities",
                "capability",
            )
        ):
            requirements = [requirements]
        elif requirements and all(
            isinstance(value, dict) for value in requirements.values()
        ):
            requirements = list(requirements.values())
        else:
            requirements = []
        canonical["requirements"] = requirements
    elif requirements is None:
        requirements = []
        canonical["requirements"] = requirements
    if not isinstance(requirements, list):
        return canonical

    def first_present(requirement: dict[str, Any], names: tuple[str, ...], default: Any) -> Any:
        for name in names:
            if name in requirement:
                return requirement[name]
        return default

    def selector_list(value: Any) -> Any:
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return value

    canonical_requirements = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            canonical_requirements.append(requirement)
            continue
        mandatory = first_present(
            requirement, ("mandatory", "isMandatory", "required"), True
        )
        if isinstance(mandatory, str) and mandatory.strip().casefold() in {"true", "false"}:
            mandatory = mandatory.strip().casefold() == "true"
        canonical_requirement = {
            "evidence": first_present(
                requirement, ("evidence", "instructionEvidence", "quote"), None
            ),
            "anyOfEquipmentRefs": selector_list(first_present(
                requirement,
                (
                    "anyOfEquipmentRefs",
                    "equipmentRefs",
                    "requiredEquipmentRefs",
                    "equipmentRef",
                ),
                [],
            )),
            "anyOfCapabilities": selector_list(first_present(
                requirement,
                (
                    "anyOfCapabilities",
                    "capabilities",
                    "requiredCapabilities",
                    "capability",
                ),
                [],
            )),
            "mandatory": mandatory,
        }
        if (
            canonical_requirement["anyOfEquipmentRefs"] == []
            and canonical_requirement["anyOfCapabilities"] == []
        ):
            continue
        canonical_requirements.append(canonical_requirement)
    canonical["requirements"] = canonical_requirements
    return canonical


def _project_compatible_instruction_equipment_references(
    audit: dict[str, Any], declared_references: set[str]
) -> dict[str, Any]:
    projected = _canonicalize_instruction_requirement_shape(audit)
    requirements = projected.get("requirements")
    if not isinstance(requirements, list):
        return projected
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        alternatives = requirement.get("anyOfEquipmentRefs")
        if not isinstance(alternatives, list):
            continue
        normalized = []
        for reference in alternatives:
            replacement = reference
            if isinstance(reference, str) and reference not in declared_references:
                prefix = reference.split("_", 1)[0]
                reference_stem = _semantic_equipment_reference_stem(reference)
                compatible = [
                    declared
                    for declared in declared_references
                    if declared.startswith(prefix + "_")
                    and _semantic_equipment_reference_stem(declared) == reference_stem
                ]
                if len(compatible) == 1:
                    replacement = compatible[0]
            normalized.append(replacement)
        requirement["anyOfEquipmentRefs"] = list(dict.fromkeys(normalized))
    return projected


def _apply_instruction_entailment_repair(
    repair_content: str | None,
    definition: dict[str, Any],
    audit: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    repair_payload = _json_object(repair_content, "instruction entailment repair")
    repair_operations = repair_payload.get("patch")
    if not isinstance(repair_operations, list):
        raise ValueError("Instruction entailment repair must contain a patch array")
    for operation in repair_operations:
        path = operation.get("path") if isinstance(operation, dict) else None
        if not isinstance(path, str) or not (
            path == "/audit/requirements"
            or path.startswith("/audit/requirements/")
            or path == "/definition/instructions"
        ):
            raise ValueError("Instruction entailment repair used an out-of-scope path")
    repaired_payload = apply_json_patch(
        {"definition": definition, "audit": audit}, repair_operations
    )
    repaired_definition = (
        repaired_payload.get("definition")
        if isinstance(repaired_payload, dict)
        else None
    )
    repaired_audit = (
        repaired_payload.get("audit")
        if isinstance(repaired_payload, dict)
        else None
    )
    definition_id = definition.get("id")
    if (
        not isinstance(repaired_definition, dict)
        or repaired_definition.get("id") != definition_id
        or collect_changed_json_paths(definition, repaired_definition) - {"/instructions"}
    ):
        raise ValueError("Instruction entailment repair changed structural definition fields")
    if not isinstance(repaired_audit, dict) or repaired_audit.get("id") != definition_id:
        raise ValueError("Instruction entailment repair changed the audit identity")
    return repaired_definition, repaired_audit


def _run_instruction_entailment_audit(
    client: Any,
    definitions: list[dict[str, Any]],
    existing_discards: list[str],
    equipment: dict[str, Any],
    call_json: Callable[..., str | None],
    batch_size: int = 20,
    completed_batch_count: int = 0,
    resumed_kept: list[dict[str, Any]] | None = None,
    resumed_discards: list[str] | None = None,
    batch_completed_callback: Callable[
        [int, list[dict[str, Any]], list[str]], None
    ] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    equipment_context, reference_ids, id_to_reference = _review_equipment_context(equipment)
    kept = copy.deepcopy(resumed_kept) if resumed_kept is not None else []
    discarded = (
        list(resumed_discards)
        if resumed_discards is not None
        else list(existing_discards)
    )
    batches = [definitions[index:index + batch_size] for index in range(0, len(definitions), batch_size)]
    print(
        f"Auditing instruction-to-equipment entailment in {len(batches)} batch(es).",
        flush=True,
    )
    if completed_batch_count:
        print(
            f"Resuming with {completed_batch_count}/{len(batches)} instruction entailment "
            "batch(es) already complete.",
            flush=True,
        )
    for batch_index, batch in enumerate(batches, start=1):
        if batch_index <= completed_batch_count:
            continue
        referenced = _definitions_with_equipment_references(batch, id_to_reference)
        declared_references_by_id = {
            definition["id"]: {
                id_to_reference[equipment_id]
                for equipment_id in [
                    definition.get("equipmentId"),
                    *definition.get("requiredAccessoryEquipmentIds", []),
                ]
                if equipment_id in id_to_reference
            }
            for definition in batch
        }
        extraction_system_message = {
            "role": "system",
            "content": (
                    "Extract every mandatory physical implement or attachment explicitly entailed "
                    "by each ExerciseDefinition instruction. Resolve words in equipment context: "
                    "for example a bar on a cable is an attachment, while barbell identifies the "
                    "primary implement. A declared implement such as a dumbbell, barbell, cable, "
                    "vest, bench, or rings must use its semantic equipment reference, never a "
                    "similar-sounding capability. Capabilities are only additional physical "
                    "features or attachments. Optional alternatives form one anyOf clause. Return JSON "
                    "only as {\"audits\":[{\"id\":string,\"requirements\":[{\"evidence\":string,"
                    "\"anyOfEquipmentRefs\":[string],\"anyOfCapabilities\":[string],"
                    "\"mandatory\":boolean}],"
                    "\"instructionPatch\":[RFC6902 operations]}]}. Cover every ID exactly once. "
                    "Every declared equipmentId and requiredAccessoryEquipmentId must be accounted "
                    "for by a mandatory requirement. If the instructions omit declared equipment, "
                    "use instructionPatch to explain its use and extract evidence from the patched text. "
                    "Put simultaneously required items in separate requirement entries; combine values "
                    "within one entry only when either alternative independently satisfies that same "
                    "physical requirement. "
                    "Evidence must be an exact substring of the resulting instructions. An "
                    "instructionPatch may modify only /instructions and only to fix inconsistent "
                    "implement wording or substitute an available implement without changing the "
                    "movement identity. Never hide a mandatory requirement. Use only this capability "
                    "catalog: "
                    + ", ".join(sorted(EQUIPMENT_CAPABILITY_CATALOG))
                    + ". Capability meanings: "
                    + json.dumps(CAPABILITY_SEMANTICS, ensure_ascii=False)
            ),
        }
        expected_ids = {definition["id"] for definition in batch}
        referenced_by_id = {definition["id"]: definition for definition in referenced}
        audits_by_id: dict[str, dict[str, Any]] = {}

        def request_missing_audits(
            requested_ids: list[str], loading_message: str
        ) -> list[dict[str, Any]]:
            messages = [
                extraction_system_message,
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "equipment": equipment_context,
                            "definitions": [referenced_by_id[value] for value in requested_ids],
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            content = call_json(
                client,
                messages,
                loading_message,
                show_loading=False,
            )
            payload = _json_object(content, "instruction entailment audit")
            response_audits = payload.get("audits")
            if not isinstance(response_audits, list):
                raise ValueError("Instruction entailment audit must contain an audits array")
            response_ids = [
                audit.get("id") for audit in response_audits if isinstance(audit, dict)
            ]
            counts = Counter(response_ids)
            return [
                audit
                for audit in response_audits
                if isinstance(audit, dict)
                and audit.get("id") in requested_ids
                and counts[audit.get("id")] == 1
            ]

        for recovery_attempt in range(3):
            missing_ids = [
                definition["id"]
                for definition in batch
                if definition["id"] not in audits_by_id
            ]
            if not missing_ids:
                break
            try:
                recovered = request_missing_audits(
                    missing_ids,
                    f"Instruction entailment batch {batch_index}/{len(batches)}"
                    + (
                        ""
                        if recovery_attempt == 0
                        else f" missing-ID recovery {recovery_attempt}/2"
                    ),
                )
            except (TypeError, ValueError):
                recovered = []
            audits_by_id.update({audit["id"]: audit for audit in recovered})

        missing_ids = [
            definition["id"]
            for definition in batch
            if definition["id"] not in audits_by_id
        ]
        for missing_id in missing_ids:
            isolated_error: Exception | None = None
            for isolated_attempt in range(3):
                try:
                    recovered = request_missing_audits(
                        [missing_id],
                        f"Instruction entailment batch {batch_index}/{len(batches)} isolated "
                        f"{referenced_by_id[missing_id]['name']} "
                        f"({isolated_attempt + 1}/3)",
                    )
                    if recovered:
                        audits_by_id[missing_id] = recovered[0]
                        break
                except (TypeError, ValueError) as error:
                    isolated_error = error
            if missing_id not in audits_by_id:
                detail = f": {isolated_error}" if isolated_error is not None else ""
                raise ValueError(
                    f"Instruction entailment could not recover audit coverage for "
                    f"{referenced_by_id[missing_id]['name']}{detail}"
                )
        audits = [audits_by_id[definition["id"]] for definition in batch]

        patched_by_id: dict[str, dict[str, Any]] = {}
        for definition in batch:
            audit = next(item for item in audits if item.get("id") == definition["id"])
            patch_operations = audit.get("instructionPatch")
            if not isinstance(patch_operations, list):
                raise ValueError("Instruction entailment audit lacks an instructionPatch array")
            validate_patch_operations_scope(
                patch_operations, {"/instructions"}, {"/instructions"}
            )
            patched = apply_json_patch(definition, patch_operations)
            changed_paths = collect_changed_json_paths(definition, patched)
            validate_changed_paths_scope(changed_paths, {"/instructions"}, {"/instructions"})
            patched_by_id[definition["id"]] = patched

        verification_messages = [
            {
                "role": "system",
                "content": (
                    "Independently verify the instruction requirement extraction. Return JSON only "
                    "as {\"patch\":[RFC 6902 operations]}. Correct only the requirements subtree "
                    "of an existing indexed audit; never add, remove, reorder, or rename audits. Ensure every "
                    "mandatory implement or attachment explicitly required by the instructions is "
                    "represented, optional alternatives share one anyOf clause, evidence is an exact "
                    "instruction substring, declared implements use semantic equipment references, "
                    "and only additional features use supplied capability enums. Ensure every declared "
                    "equipment reference is accounted for."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "equipment": equipment_context,
                        "definitions": [
                            patched_by_id[definition["id"]] for definition in batch
                        ],
                        "audits": audits,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        verification_content = call_json(
            client,
            verification_messages,
            f"Verifying instruction entailment {batch_index}/{len(batches)}",
            show_loading=False,
        )
        rejected_verification_operations = 0
        try:
            verification_payload = _json_object(
                verification_content, "instruction entailment verification"
            )
            proposed_operations = verification_payload.get("patch")
            if not isinstance(proposed_operations, list):
                raise ValueError(
                    "Instruction entailment verification must contain a patch array"
                )
        except (IndexError, KeyError, TypeError, ValueError):
            proposed_operations = []
            rejected_verification_operations = 1
        operations = []
        allowed_verification_path = re.compile(
            r"/audits/\d+/requirements(?:/.*)?"
        )
        for operation in proposed_operations:
            path = operation.get("path") if isinstance(operation, dict) else None
            from_path = operation.get("from") if isinstance(operation, dict) else None
            path_allowed = isinstance(path, str) and allowed_verification_path.fullmatch(
                path
            ) is not None
            from_allowed = from_path is None or (
                isinstance(from_path, str)
                and allowed_verification_path.fullmatch(from_path) is not None
            )
            if path_allowed and from_allowed:
                operations.append(operation)
            else:
                rejected_verification_operations += 1
        try:
            verified = apply_json_patch({"audits": audits}, operations)
        except (IndexError, KeyError, TypeError, ValueError):
            verified = {"audits": audits}
            rejected_verification_operations += len(operations) or 1
        if rejected_verification_operations:
            print(
                f"Instruction entailment batch {batch_index}/{len(batches)} ignored "
                f"{rejected_verification_operations} invalid verifier patch operation(s).",
                flush=True,
            )
        verified_audits = verified.get("audits") if isinstance(verified, dict) else None
        if not isinstance(verified_audits, list):
            raise ValueError("Instruction entailment verification produced invalid audits")
        verified_by_id = {
            audit.get("id"): audit for audit in verified_audits if isinstance(audit, dict)
        }
        if set(verified_by_id) != expected_ids or len(verified_audits) != len(expected_ids):
            raise ValueError("Verified instruction entailment lost definition coverage")
        verified_by_id = {
            definition_id: _project_compatible_instruction_equipment_references(
                audit, declared_references_by_id[definition_id]
            )
            for definition_id, audit in verified_by_id.items()
        }

        for definition in batch:
            definition_id = definition["id"]
            repair_response_error: str | None = None
            for repair_attempt in range(4):
                try:
                    _validated_instruction_requirements(
                        verified_by_id[definition_id],
                        patched_by_id[definition_id],
                        declared_references_by_id[definition_id],
                    )
                    break
                except ValueError as validation_error:
                    if repair_attempt == 3:
                        isolated_error: Exception = validation_error
                        isolated_repaired = False
                        for isolated_attempt in range(3):
                            isolated_content = call_json(
                                client,
                                [
                                    {
                                        "role": "system",
                                        "content": (
                                            "Rewrite one malformed instruction-entailment result "
                                            "from scratch. Return JSON only as {\"instructions\":string,"
                                            "\"requirements\":[{\"evidence\":string,"
                                            "\"anyOfEquipmentRefs\":[string],"
                                            "\"anyOfCapabilities\":[string],"
                                            "\"mandatory\":boolean}]}. Preserve movement identity "
                                            "and change no structural definition fields. Evidence "
                                            "must be an exact substring of the returned instructions. "
                                            "Every declared equipment reference must be represented "
                                            "by a mandatory requirement. Use only declared semantic "
                                            "equipment references and allowed capability enums."
                                        ),
                                    },
                                    {
                                        "role": "user",
                                        "content": json.dumps(
                                            {
                                                "validationError": str(isolated_error),
                                                "allowedCapabilities": sorted(
                                                    EQUIPMENT_CAPABILITY_CATALOG
                                                ),
                                                "declaredEquipmentRefs": sorted(
                                                    declared_references_by_id[definition_id]
                                                ),
                                                "definition": patched_by_id[definition_id],
                                                "audit": verified_by_id[definition_id],
                                            },
                                            ensure_ascii=False,
                                        ),
                                    },
                                ],
                                f"Rewriting instruction entailment {batch_index}/{len(batches)} "
                                f"for {definition['name']} ({isolated_attempt + 1}/3)",
                                show_loading=False,
                            )
                            try:
                                isolated_payload = _json_object(
                                    isolated_content,
                                    "instruction entailment isolated rewrite",
                                )
                                rewritten_instructions = isolated_payload.get("instructions")
                                rewritten_requirements = isolated_payload.get("requirements")
                                if (
                                    not isinstance(rewritten_instructions, str)
                                    or not rewritten_instructions.strip()
                                    or len(rewritten_instructions) > 500
                                    or not isinstance(rewritten_requirements, list)
                                ):
                                    raise ValueError(
                                        "isolated rewrite has invalid instructions or requirements"
                                    )
                                candidate_definition = copy.deepcopy(
                                    patched_by_id[definition_id]
                                )
                                candidate_definition["instructions"] = (
                                    rewritten_instructions.strip()
                                )
                                candidate_audit = {
                                    "id": definition_id,
                                    "requirements": rewritten_requirements,
                                    "instructionPatch": [],
                                }
                                candidate_audit = (
                                    _project_compatible_instruction_equipment_references(
                                        candidate_audit,
                                        declared_references_by_id[definition_id],
                                    )
                                )
                                _validated_instruction_requirements(
                                    candidate_audit,
                                    candidate_definition,
                                    declared_references_by_id[definition_id],
                                )
                                patched_by_id[definition_id] = candidate_definition
                                verified_by_id[definition_id] = candidate_audit
                                isolated_repaired = True
                                break
                            except (KeyError, TypeError, ValueError) as error:
                                isolated_error = error
                        if isolated_repaired:
                            break
                        raise ValueError(
                            f"{definition['name']}: instruction entailment remained invalid "
                            f"after 3 JSON Patch repairs and 3 isolated rewrites: "
                            f"{isolated_error}"
                        ) from validation_error
                    validation_error_message = str(validation_error)
                    if repair_response_error is not None:
                        validation_error_message += (
                            "; previous repair response was rejected: "
                            + repair_response_error
                        )
                repair_messages = [
                    {
                        "role": "system",
                        "content": (
                            "Repair one verified instruction-entailment audit using RFC 6902 "
                            "JSON Patch. Return JSON only as {\"patch\":[...]}. Every path must "
                            "be /audit/requirements or below it, or exactly "
                            "/definition/instructions. Do not modify IDs or structural definition "
                            "fields. Evidence must be an exact substring of the resulting instructions. "
                            "Use declared semantic equipment references for implements and capability "
                            "enums only for additional features or attachments. Every declared "
                            "equipment reference must be accounted for by a mandatory requirement."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "validationError": validation_error_message,
                                "allowedCapabilities": sorted(EQUIPMENT_CAPABILITY_CATALOG),
                                "declaredEquipmentRefs": sorted(
                                    declared_references_by_id[definition_id]
                                ),
                                "definition": patched_by_id[definition_id],
                                "audit": verified_by_id[definition_id],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
                repair_content = call_json(
                    client,
                    repair_messages,
                    f"Repairing instruction entailment {batch_index}/{len(batches)} "
                    f"for {definition['name']} (pass {repair_attempt + 1}/3)",
                    show_loading=False,
                )
                try:
                    repaired_definition, repaired_audit = (
                        _apply_instruction_entailment_repair(
                            repair_content,
                            patched_by_id[definition_id],
                            verified_by_id[definition_id],
                        )
                    )
                except (TypeError, ValueError) as repair_error:
                    repair_response_error = str(repair_error)
                    continue
                repair_response_error = None
                patched_by_id[definition_id] = repaired_definition
                verified_by_id[definition_id] = (
                    _project_compatible_instruction_equipment_references(
                        repaired_audit, declared_references_by_id[definition_id]
                    )
                )

        for definition in batch:
            original_id = definition["id"]
            patched = patched_by_id[original_id]
            audit = verified_by_id[original_id]
            required_clauses = _validated_instruction_requirements(
                audit, patched, declared_references_by_id[original_id]
            )
            declared_ids = {
                value
                for value in [
                    patched.get("equipmentId"),
                    *patched.get("requiredAccessoryEquipmentIds", []),
                ]
                if value is not None
            }
            available = _capabilities_for_equipment_ids(equipment, declared_ids)
            unsupported = [
                clause
                for clause in required_clauses
                if not clause["equipmentRefs"]
                and not set(clause["capabilities"]).intersection(available)
            ]
            if unsupported:
                discarded.append(
                    f"{definition['name']}: instructions require unavailable capability "
                    f"alternatives {unsupported}"
                )
                continue
            kept.append(_validate_reviewed_definition(patched, equipment))
        print(
            f"Instruction entailment batches complete: {batch_index}/{len(batches)}",
            flush=True,
        )
        if batch_completed_callback is not None:
            batch_completed_callback(batch_index, kept, discarded)
    kept, collision_discards = _deduplicate_reviewed_definitions(kept)
    discarded.extend(collision_discards)
    return kept, discarded


def _library_payload(
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    generation_failures: list[str],
    semantic_discards: list[str],
    *,
    review_status: str | None = None,
) -> dict[str, Any]:
    canonical_definitions = []
    for definition in definitions:
        canonical = copy.deepcopy(definition)
        canonical.pop("instructions", None)
        canonical.pop("instructionEquipmentIds", None)
        canonical_definitions.append(canonical)
    payload = {
        "format": "myworkoutassistant.exercise-library",
        "schemaVersion": 2,
        "exerciseDefinitions": canonical_definitions,
        "exerciseMovements": [],
        "equipments": copy.deepcopy(equipment.get("equipments", [])),
        "accessoryEquipments": copy.deepcopy(equipment.get("accessoryEquipments", [])),
        "generationFailures": generation_failures,
        "semanticDiscards": semantic_discards,
    }
    if review_status is not None:
        payload["reviewStatus"] = review_status
    return payload


def _serialize_review_progress(
    definitions: list[dict[str, Any]],
    completed_results: dict[int, tuple[list[dict[str, Any]], list[str]]],
    batch_size: int = SEMANTIC_REVIEW_BATCH_SIZE,
) -> dict[str, Any]:
    return {
        "batchSize": batch_size,
        "sourceDefinitionIds": [definition["id"] for definition in definitions],
        "completedBatches": {
            str(index): {
                "keptDefinitions": copy.deepcopy(kept),
                "discards": list(discards),
            }
            for index, (kept, discards) in sorted(completed_results.items())
        },
    }


def _load_review_progress(
    checkpoint: dict[str, Any],
    definitions: list[dict[str, Any]],
    batch_size: int = SEMANTIC_REVIEW_BATCH_SIZE,
) -> dict[int, tuple[list[dict[str, Any]], list[str]]]:
    progress = checkpoint.get("reviewProgress")
    if progress is None:
        return {}
    if not isinstance(progress, dict):
        raise ValueError("Review checkpoint has invalid reviewProgress")
    if progress.get("batchSize") != batch_size:
        print(
            f"Review batch size changed from {progress.get('batchSize')} to {batch_size}; "
            "resetting only saved semantic-review progress.",
            flush=True,
        )
        return {}
    if progress.get("sourceDefinitionIds") != [definition["id"] for definition in definitions]:
        raise ValueError("Review checkpoint definitions changed after partial review")
    serialized_batches = progress.get("completedBatches")
    if not isinstance(serialized_batches, dict):
        raise ValueError("Review checkpoint has invalid completedBatches")
    completed = {}
    for raw_index, result in serialized_batches.items():
        if not str(raw_index).isdigit() or not isinstance(result, dict):
            raise ValueError("Review checkpoint contains an invalid completed batch")
        kept = result.get("keptDefinitions")
        discards = result.get("discards")
        if not isinstance(kept, list) or not isinstance(discards, list):
            raise ValueError("Review checkpoint contains invalid completed batch output")
        completed[int(raw_index)] = (copy.deepcopy(kept), list(map(str, discards)))
    return completed


def generate_exercise_library(
    client: Any,
    equipment: dict[str, Any],
    request: str = "",
    *,
    inventory_client: Any = None,
    use_reasoner_for_emitters: bool = False,
    audit_passes: int = 1,
    max_workers: int = 4,
    scope_inventory_by_equipment: bool = True,
    inventory_call: Callable[..., str | None] = json_call_reasoner_only_with_loading,
    reasoner_call: Callable[..., str | None] = json_call_reasoner_only_with_loading,
    chat_call: Callable[..., str | None] = json_call_chat_max_with_loading,
    semantic_review_call: Callable[..., str | None] | None = None,
    global_consistency_call: Callable[..., str | None] | None = None,
    instruction_entailment_call: Callable[..., str | None] | None = None,
    review_checkpoint_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    inventory_client = inventory_client or client
    if scope_inventory_by_equipment:
        inventory_scopes = [
            (
                "exercises that require at least one listed accessory and use no primary "
                "weight-loaded equipment; equipmentId must be null and "
                "requiredAccessoryEquipmentIds must be non-empty. Do not include exercises "
                "that can be performed without any supplied equipment or accessory",
                set(),
                True,
            )
        ]
        inventory_scopes.extend(
            (
                f"exercises whose primary equipment is {item.get('name', item['id'])} "
                f"with exact equipmentId {item['id']}",
                {item["id"]},
                False,
            )
            for item in equipment.get("equipments", [])
            if isinstance(item, dict) and item.get("id")
        )
    else:
        inventory_scopes = [(None, None, False)]

    candidate_by_key: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    generation_failures: list[str] = []
    print(
        f"Stage 1/3: Enumerating exercises in {len(inventory_scopes)} bounded batch(es) "
        f"with up to {min(max(1, max_workers), len(inventory_scopes))} concurrent request(s).",
        flush=True,
    )

    def generate_scope(
        scope_index: int,
        scope_description: str | None,
        allowed_equipment_ids: set[str] | None,
        require_any_accessory: bool,
        show_loading: bool,
    ) -> tuple[dict[tuple[str, str, str | None], dict[str, Any]], list[str]]:
        scope_failures: list[str] = []
        try:
            scoped_candidates = _call_inventory(
                inventory_client,
                equipment,
                request,
                scope_description=scope_description,
                allowed_equipment_ids=allowed_equipment_ids,
                require_any_accessory=require_any_accessory,
                show_loading=show_loading,
                call_json=inventory_call,
            )
        except Exception as error:
            failure = f"Inventory batch {scope_index} failed: {error}"
            return {}, [failure]
        scoped_by_key = {
            _candidate_key(candidate): candidate for candidate in scoped_candidates
        }
        for audit_index in range(max(0, audit_passes)):
            try:
                missing = _call_inventory(
                    inventory_client,
                    equipment,
                    request,
                    audit_existing=list(scoped_by_key.values()),
                    scope_description=scope_description,
                    allowed_equipment_ids=allowed_equipment_ids,
                    require_any_accessory=require_any_accessory,
                    show_loading=show_loading,
                    call_json=inventory_call,
                )
            except Exception as error:
                failure = f"Inventory batch {scope_index} audit {audit_index + 1} failed: {error}"
                scope_failures.append(failure)
                continue
            for candidate in missing:
                scoped_by_key.setdefault(_candidate_key(candidate), candidate)
        return scoped_by_key, scope_failures

    inventory_worker_count = min(max(1, max_workers), len(inventory_scopes))
    if inventory_worker_count == 1:
        scope_results = []
        for scope_index, scope in enumerate(inventory_scopes, start=1):
            print(
                f"Inventory batch {scope_index}/{len(inventory_scopes)}: "
                f"{scope[0] or 'all equipment'}",
                flush=True,
            )
            scope_results.append(
                (scope_index, generate_scope(scope_index, *scope, show_loading=True))
            )
    else:
        scope_results = []
        with ThreadPoolExecutor(max_workers=inventory_worker_count) as executor:
            future_to_scope = {
                executor.submit(generate_scope, scope_index, *scope, False): scope_index
                for scope_index, scope in enumerate(inventory_scopes, start=1)
            }
            for future in as_completed(future_to_scope):
                scope_index = future_to_scope[future]
                try:
                    result = future.result()
                except Exception as error:
                    result = ({}, [f"Inventory batch {scope_index} failed: {error}"])
                scope_results.append((scope_index, result))
                print(
                    f"Inventory batch {scope_index}/{len(inventory_scopes)} complete: "
                    f"{len(result[0])} distinct candidate(s).",
                    flush=True,
                )

    for _, (scoped_by_key, scope_failures) in sorted(scope_results):
        candidate_by_key.update(scoped_by_key)
        generation_failures.extend(scope_failures)
        for failure in scope_failures:
            print(f"Warning: {failure}. Keeping available results.", flush=True)
    candidates, semantic_filters = _normalize_and_filter_candidates(
        list(candidate_by_key.values()),
        equipment,
    )
    if semantic_filters:
        print(
            f"Semantic validation removed {len(semantic_filters)} impractical or redundant "
            "candidate(s).",
            flush=True,
        )
    if not candidates:
        raise ValueError("The model did not identify any exercises")

    print(
        f"Stage 3/3: Emitting {len(candidates)} canonical exercise definition(s) "
        f"with {max(1, max_workers)} worker(s).",
        flush=True,
    )
    definitions_by_index: dict[int, dict[str, Any]] = {}
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        future_to_index = {
            executor.submit(
                _emit_definition,
                client,
                candidate,
                equipment=equipment,
                use_reasoner=use_reasoner_for_emitters,
                call_reasoner=reasoner_call,
                call_chat=chat_call,
            ): index
            for index, candidate in enumerate(candidates)
        }
        for completed_count, future in enumerate(as_completed(future_to_index), start=1):
            index = future_to_index[future]
            try:
                definitions_by_index[index] = future.result()
            except Exception as error:
                errors.append(str(error))
            print(
                f"\rEmitting definitions: {completed_count}/{len(candidates)}",
                end="",
                flush=True,
            )
    print()
    if errors:
        generation_failures.extend(errors)
        print(
            f"Warning: {len(errors)} definition(s) exhausted retries; "
            "checking whether the result is complete enough to save.",
            flush=True,
        )

    maximum_failed_definitions = max(1, int(len(candidates) * 0.10))
    if len(errors) > maximum_failed_definitions:
        raise ValueError(
            f"Definition emission rejected: {len(errors)}/{len(candidates)} definitions failed "
            f"(maximum allowed: {maximum_failed_definitions}). No incomplete library was saved. "
            f"First failures: {'; '.join(errors[:3])}"
        )

    definitions = [
        definitions_by_index[index]
        for index in range(len(candidates))
        if index in definitions_by_index
    ]
    if not definitions:
        details = "\n".join(f"- {error}" for error in generation_failures[:10])
        raise ValueError(f"No valid exercise definitions were generated:\n{details}")
    muscle_review_payload = review_library_muscle_semantics(
        client,
        {
            "exerciseDefinitions": definitions,
            "equipments": copy.deepcopy(equipment.get("equipments", [])),
            "accessoryEquipments": copy.deepcopy(
                equipment.get("accessoryEquipments", [])
            ),
        },
        review_call=reasoner_call,
        max_workers=max_workers,
    )
    definitions = muscle_review_payload["exerciseDefinitions"]
    feasibility_payload = review_library_feasibility(
        client,
        {
            "exerciseDefinitions": definitions,
            "equipments": copy.deepcopy(equipment.get("equipments", [])),
            "accessoryEquipments": copy.deepcopy(
                equipment.get("accessoryEquipments", [])
            ),
        },
        review_call=reasoner_call,
        max_workers=max_workers,
    )
    definitions = feasibility_payload["exerciseDefinitions"]
    semantic_discards: list[str] = []
    if review_checkpoint_callback is not None:
        review_checkpoint_callback(
            _library_payload(
                definitions,
                equipment,
                generation_failures,
                [],
                review_status="PENDING",
            )
        )
    # Legacy subjective semantic review is intentionally disabled. Model judgments may propose
    # content, but only deterministic code validation may accept or exclude a definition.
    if False and semantic_review_call is not None:
        unreviewed_definitions = copy.deepcopy(definitions)
        original_definition_count = len(unreviewed_definitions)
        completed_review_batches: dict[int, tuple[list[dict[str, Any]], list[str]]] = {}

        def save_generated_review_batch(
            batch_index: int,
            kept: list[dict[str, Any]],
            discarded: list[str],
        ) -> None:
            completed_review_batches[batch_index] = (copy.deepcopy(kept), list(discarded))
            if review_checkpoint_callback is None:
                return
            snapshot = _library_payload(
                unreviewed_definitions,
                equipment,
                generation_failures,
                [
                    reason
                    for _, batch_discards in completed_review_batches.values()
                    for reason in batch_discards
                ],
                review_status="PENDING",
            )
            snapshot["reviewProgress"] = _serialize_review_progress(
                unreviewed_definitions, completed_review_batches
            )
            review_checkpoint_callback(snapshot)

        definitions, semantic_discards = _run_semantic_review(
            client,
            definitions,
            equipment,
            max_workers=max_workers,
            semantic_review_call=semantic_review_call,
            batch_completed_callback=save_generated_review_batch,
        )
        definitions, semantic_discards = _run_global_semantic_consistency_review(
            client,
            unreviewed_definitions,
            definitions,
            semantic_discards,
            equipment,
            global_consistency_call or semantic_review_call,
            matrix_max_workers=max_workers,
            instruction_entailment_call=instruction_entailment_call,
        )
        suspicious_rejection_rate = (
            len(definitions) / original_definition_count
            < 1.0 - MAX_SEMANTIC_DISCARD_FRACTION
        )
        if review_checkpoint_callback is not None:
            completed_snapshot = _library_payload(
                unreviewed_definitions if suspicious_rejection_rate else definitions,
                equipment,
                generation_failures,
                semantic_discards,
                review_status="FAILED" if suspicious_rejection_rate else "COMPLETE",
            )
            completed_snapshot["sourceExerciseDefinitions"] = copy.deepcopy(
                unreviewed_definitions
            )
            review_checkpoint_callback(completed_snapshot)
        if suspicious_rejection_rate:
            raise ValueError(
                f"Independent semantic review rejected {original_definition_count - len(definitions)}/"
                f"{original_definition_count} definitions, exceeding the "
                f"{int(MAX_SEMANTIC_DISCARD_FRACTION * 100)}% safety limit. The complete "
                "unreviewed definitions and diagnostic reasons were saved to the review checkpoint."
            )
    if semantic_review_call is not None:
        def save_generated_deterministic_progress(
            completed_count: int,
            kept_definitions: list[dict[str, Any]],
            current_discards: list[str],
        ) -> None:
            if review_checkpoint_callback is None:
                return
            snapshot = _library_payload(
                definitions,
                equipment,
                generation_failures,
                current_discards,
                review_status="PENDING",
            )
            snapshot["deterministicValidationProgress"] = {
                "validatorVersion": CONTENT_AUTHORITY_VERSION,
                "sourceDefinitionIds": [definition["id"] for definition in definitions],
                "completedDefinitionCount": completed_count,
                "keptDefinitions": copy.deepcopy(kept_definitions),
                "discards": list(current_discards),
            }
            review_checkpoint_callback(snapshot)

        definitions, semantic_discards = _run_deterministic_definition_validation(
            client,
            definitions,
            semantic_discards,
            equipment,
            chat_call,
            progress_callback=save_generated_deterministic_progress,
        )
        if review_checkpoint_callback is not None:
            completed_snapshot = _library_payload(
                definitions,
                equipment,
                generation_failures,
                semantic_discards,
                review_status="COMPLETE",
            )
            completed_snapshot["contentAuthorityVersion"] = CONTENT_AUTHORITY_VERSION
            review_checkpoint_callback(completed_snapshot)
    definition_ids = [definition["id"] for definition in definitions]
    if len(definition_ids) != len(set(definition_ids)):
        raise ValueError("Generated exercise definitions contain duplicate IDs")
    _validate_final_definition_semantics(definitions, equipment)
    return _library_payload(definitions, equipment, generation_failures, semantic_discards)


def review_library_checkpoint(
    client: Any,
    checkpoint: dict[str, Any],
    *,
    max_workers: int,
    semantic_review_call: Callable[..., str | None] = json_call_chat_max_with_loading,
    global_consistency_call: Callable[..., str | None] | None = None,
    instruction_entailment_call: Callable[..., str | None] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    batch_size: int = 5,
) -> tuple[dict[str, Any], bool]:
    definitions = checkpoint.get("sourceExerciseDefinitions", checkpoint.get("exerciseDefinitions"))
    equipments = checkpoint.get("equipments")
    accessories = checkpoint.get("accessoryEquipments")
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("Review checkpoint contains no exercise definitions")
    if not isinstance(equipments, list) or not isinstance(accessories, list):
        raise ValueError("Review checkpoint has invalid equipment collections")
    equipment = {"equipments": equipments, "accessoryEquipments": accessories}
    if batch_size <= 0:
        raise ValueError("Review batch size must be greater than zero")
    completed_results = _load_review_progress(checkpoint, definitions, batch_size)

    def save_batch_progress(
        batch_index: int,
        kept: list[dict[str, Any]],
        discards: list[str],
    ) -> None:
        completed_results[batch_index] = (copy.deepcopy(kept), list(discards))
        if progress_callback is None:
            return
        snapshot = _library_payload(
            copy.deepcopy(definitions),
            equipment,
            list(checkpoint.get("generationFailures", [])),
            [
                reason
                for _, batch_discards in completed_results.values()
                for reason in batch_discards
            ],
            review_status="PENDING",
        )
        snapshot["reviewProgress"] = _serialize_review_progress(
            definitions, completed_results, batch_size
        )
        progress_callback(snapshot)

    reviewed, discards = _run_semantic_review(
        client,
        definitions,
        equipment,
        max_workers=max_workers,
        semantic_review_call=semantic_review_call,
        batch_size=batch_size,
        completed_batch_results=completed_results,
        batch_completed_callback=save_batch_progress,
    )
    reviewed, discards = _run_global_semantic_consistency_review(
        client,
        definitions,
        reviewed,
        discards,
        equipment,
        global_consistency_call or semantic_review_call,
        matrix_max_workers=max_workers,
        instruction_entailment_call=instruction_entailment_call,
    )
    completed = (
        bool(reviewed)
        and len(reviewed) / len(definitions) >= 1.0 - MAX_SEMANTIC_DISCARD_FRACTION
    )
    payload = _library_payload(
        reviewed if completed else copy.deepcopy(definitions),
        equipment,
        list(checkpoint.get("generationFailures", [])),
        discards,
        review_status="COMPLETE" if completed else "FAILED",
    )
    payload["sourceExerciseDefinitions"] = copy.deepcopy(definitions)
    if completed:
        _validate_final_definition_semantics(reviewed, equipment)
    return payload, completed


def review_library_global_consistency(
    client: Any,
    checkpoint: dict[str, Any],
    *,
    semantic_review_call: Callable[..., str | None] = json_call_chat_max_with_loading,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    max_workers: int = 2,
    instruction_entailment_call: Callable[..., str | None] | None = None,
) -> dict[str, Any]:
    source_definitions = checkpoint.get("sourceExerciseDefinitions")
    reviewed_definitions = checkpoint.get("exerciseDefinitions")
    equipments = checkpoint.get("equipments")
    accessories = checkpoint.get("accessoryEquipments")
    if not isinstance(source_definitions, list) or not source_definitions:
        raise ValueError(
            "Checkpoint has no preserved sourceExerciseDefinitions; global-only review cannot "
            "restore discarded definitions"
        )
    if not isinstance(reviewed_definitions, list):
        raise ValueError("Checkpoint has invalid reviewed exerciseDefinitions")
    if not isinstance(equipments, list) or not isinstance(accessories, list):
        raise ValueError("Checkpoint has invalid equipment collections")
    equipment = {"equipments": equipments, "accessoryEquipments": accessories}
    progress = checkpoint.get("globalConsistencyProgress")
    completed_batches: dict[int, list[dict[str, Any]]] = {}
    if isinstance(progress, dict):
        if (
            progress.get("batchSize") == 40
            and progress.get("sourceDefinitionIds")
            == [definition["id"] for definition in source_definitions]
            and isinstance(progress.get("completedBatches"), dict)
        ):
            for raw_index, groups in progress["completedBatches"].items():
                if str(raw_index).isdigit() and isinstance(groups, list):
                    completed_batches[int(raw_index)] = copy.deepcopy(groups)

    def save_progress(
        batch_index: int | None = None,
        groups: list[dict[str, Any]] | None = None,
        verified_groups: list[dict[str, Any]] | None = None,
    ) -> None:
        if batch_index is not None and groups is not None:
            completed_batches[batch_index] = copy.deepcopy(groups)
        if progress_callback is None:
            return
        snapshot = copy.deepcopy(checkpoint)
        snapshot["globalConsistencyProgress"] = {
            "batchSize": 40,
            "sourceDefinitionIds": [definition["id"] for definition in source_definitions],
            "completedBatches": {
                str(index): copy.deepcopy(batch_groups)
                for index, batch_groups in sorted(completed_batches.items())
            },
            "verifiedMatrix": copy.deepcopy(verified_groups),
        }
        progress_callback(snapshot)

    reviewed, discards = _run_global_semantic_consistency_review(
        client,
        source_definitions,
        reviewed_definitions,
        list(checkpoint.get("semanticDiscards", [])),
        equipment,
        semantic_review_call,
        completed_matrix_batches=completed_batches,
        matrix_batch_completed_callback=lambda index, groups: save_progress(index, groups),
        verified_matrix_callback=lambda groups: save_progress(verified_groups=groups),
        matrix_max_workers=max_workers,
        instruction_entailment_call=instruction_entailment_call,
    )
    _validate_final_definition_semantics(reviewed, equipment)
    payload = _library_payload(
        reviewed,
        equipment,
        list(checkpoint.get("generationFailures", [])),
        discards,
        review_status="COMPLETE",
    )
    payload["sourceExerciseDefinitions"] = copy.deepcopy(source_definitions)
    payload["globalConsistencyProgress"] = {
        "batchSize": 40,
        "sourceDefinitionIds": [definition["id"] for definition in source_definitions],
        "completedBatches": {
            str(index): copy.deepcopy(groups)
            for index, groups in sorted(completed_batches.items())
        },
    }
    return payload


def _equipment_natural_aliases(
    item: dict[str, Any], all_items: list[dict[str, Any]] | None = None
) -> set[str]:
    aliases = set()
    for raw_name in (item.get("name"), _canonical_equipment_name(item)):
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        normalized = re.sub(r"\s+", " ", raw_name.strip().casefold())
        aliases.add(normalized)
        if normalized.endswith("s"):
            aliases.add(normalized[:-1])
        tokens = re.findall(r"[a-z0-9]+", normalized)
        terminal = tokens[-1] if tokens else ""
        if (
            all_items is not None
            and len(terminal) >= 4
            and terminal not in {"equipment", "machine", "pair", "single", "setup"}
        ):
            terminal_owners = sum(
                1
                for candidate in all_items
                if terminal in re.findall(
                    r"[a-z0-9]+",
                    str(candidate.get("name") or "").casefold(),
                )
            )
            if terminal_owners == 1:
                aliases.add(terminal)
    return aliases


def _instruction_mentions_equipment(
    instructions: str, aliases: set[str]
) -> bool:
    return any(
        re.search(
            r"(?<!\w)"
            + r"[-\s]+".join(re.escape(token) for token in re.split(r"[-\s]+", alias))
            + r"(?!\w)",
            instructions,
            re.IGNORECASE,
        )
        is not None
        for alias in aliases
    )


def _instruction_authority_issues(
    original: dict[str, Any],
    reviewed: dict[str, Any],
    equipment: dict[str, Any],
) -> list[str]:
    original_instructions = str(original.get("instructions") or "")
    instructions = str(reviewed.get("instructions") or "")
    issues = []
    if re.search(r"\b(?:PRIMARY|ACCESSORY)_[A-Z0-9_]+\b", instructions):
        issues.append("instructions expose an internal semantic equipment placeholder")

    internal_role_pattern = re.compile(
        r"\b(?:primary|accessory)\s+(?:dumbbells?|barbells?|weight\s+vest|"
        r"pull[- ]up\s+bar|bench|rings?|setup|equipment|implement)\b",
        re.IGNORECASE,
    )
    if internal_role_pattern.search(instructions) and not internal_role_pattern.search(
        original_instructions
    ):
        issues.append("instructions expose internal primary/accessory role terminology")

    load_pattern = re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:lb|lbs|kg|kilograms?|pounds?)\b",
        re.IGNORECASE,
    )
    original_loads = {value.casefold() for value in load_pattern.findall(original_instructions)}
    invented_loads = [
        value for value in load_pattern.findall(instructions)
        if value.casefold() not in original_loads
    ]
    if invented_loads:
        issues.append(f"instructions invented exact load values {invented_loads}")

    declared_ids = {
        value
        for value in [
            reviewed.get("equipmentId"),
            *reviewed.get("requiredAccessoryEquipmentIds", []),
        ]
        if value is not None
    }
    items = _all_equipment_items(equipment)
    all_items = list(items.values())
    declared_names: set[str] = set()
    missing_declared_equipment = []
    for equipment_id in declared_ids:
        item = items.get(equipment_id, {})
        aliases = _equipment_natural_aliases(item, all_items)
        declared_names.update(aliases)
        if aliases and not _instruction_mentions_equipment(instructions, aliases):
            missing_declared_equipment.append(
                str(item.get("name") or _canonical_equipment_name(item))
            )
    if missing_declared_equipment:
        issues.append(
            "instructions do not explicitly name structurally declared equipment "
            f"{sorted(missing_declared_equipment)}"
        )
    optional_marker = re.compile(
        r"\b(?:optional(?:ly)?|if\s+using|may\s+use|can\s+use)\b",
        re.IGNORECASE,
    )
    for sentence in re.split(r"(?<=[.!?])\s+", instructions):
        lowered_sentence = sentence.casefold()
        if optional_marker.search(sentence) and any(
            name in lowered_sentence for name in declared_names
        ):
            issues.append(
                "instructions describe structurally declared equipment as optional"
            )
            break
    return issues


def _run_instruction_authority_review(
    client: Any,
    definitions: list[dict[str, Any]],
    baseline_definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    call_json: Callable[..., str | None],
) -> list[dict[str, Any]]:
    baseline_by_name = {definition["name"]: definition for definition in baseline_definitions}
    reviewed_definitions = []
    repaired_count = 0
    for definition in definitions:
        original = baseline_by_name.get(definition["name"], definition)
        current = copy.deepcopy(definition)
        issues = _instruction_authority_issues(original, current, equipment)
        if not issues:
            reviewed_definitions.append(current)
            continue
        for attempt in range(3):
            declared_ids = [
                value
                for value in [
                    current.get("equipmentId"),
                    *current.get("requiredAccessoryEquipmentIds", []),
                ]
                if value is not None
            ]
            declared_items = [
                _all_equipment_items(equipment)[value]
                for value in declared_ids
                if value in _all_equipment_items(equipment)
            ]
            all_equipment_items = list(_all_equipment_items(equipment).values())
            declared_aliases = {
                str(item.get("name") or item.get("id")): sorted(
                    _equipment_natural_aliases(item, all_equipment_items)
                )
                for item in declared_items
            }
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Repair only the user-facing exercise instructions. Return JSON only as "
                        "{\"patch\":[RFC 6902 operations]}, with every path exactly /instructions. "
                        "Do not expose semantic placeholders or internal primary/accessory labels. "
                        "Do not invent exact loads. Structurally declared equipment is mandatory for "
                        "this definition and must not be described as optional. Equipment not declared "
                        "by the definition may still be presented as optional. Preserve movement "
                        "identity, technique, and all unrelated wording."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "issues": issues,
                            "originalInstructions": original.get("instructions"),
                            "definition": current,
                            "declaredEquipment": declared_items,
                            "acceptedNaturalAliases": declared_aliases,
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            content = call_json(
                client,
                messages,
                f"Repairing instruction authority for {definition['name']} "
                f"({attempt + 1}/3)",
                show_loading=False,
            )
            try:
                payload = _json_object(content, "instruction authority repair")
                operations = payload.get("patch")
                if not isinstance(operations, list):
                    raise ValueError("instruction authority repair needs a patch array")
                validate_patch_operations_scope(
                    operations, {"/instructions"}, {"/instructions"}
                )
                candidate = apply_json_patch(current, operations)
                validate_changed_paths_scope(
                    collect_changed_json_paths(current, candidate),
                    {"/instructions"},
                    {"/instructions"},
                )
                if not isinstance(candidate.get("instructions"), str) or not candidate[
                    "instructions"
                ].strip():
                    raise ValueError("instruction authority repair produced empty instructions")
                if len(candidate["instructions"]) > 500:
                    raise ValueError("instruction authority repair exceeded 500 characters")
                remaining_issues = _instruction_authority_issues(
                    original, candidate, equipment
                )
                if remaining_issues:
                    current = candidate
                    issues = remaining_issues
                    continue
                current = _validate_reviewed_definition(candidate, equipment)
                repaired_count += 1
                break
            except (IndexError, KeyError, TypeError, ValueError) as error:
                issues = [str(error)]
        else:
            for rewrite_attempt in range(3):
                rewrite_messages = [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite only the complete user-facing exercise instructions. Return "
                            "JSON only as {\"instructions\": string}. Resolve every listed issue. "
                            "Use a supplied natural alias for every structurally declared equipment "
                            "item and describe that equipment as mandatory. Optional equipment is "
                            "allowed only when it is not structurally declared. Do not expose internal "
                            "placeholders or primary/accessory role labels. Do not invent exact loads. "
                            "Preserve movement identity and technique, remain under 500 characters, "
                            "and change no definition field other than instructions."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "issues": issues,
                                "originalInstructions": original.get("instructions"),
                                "currentInstructions": current.get("instructions"),
                                "declaredEquipment": declared_items,
                                "acceptedNaturalAliases": declared_aliases,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
                rewrite_content = call_json(
                    client,
                    rewrite_messages,
                    f"Rewriting instruction authority for {definition['name']} "
                    f"({rewrite_attempt + 1}/3)",
                    show_loading=False,
                )
                try:
                    rewrite_payload = _json_object(
                        rewrite_content, "instruction authority rewrite"
                    )
                    rewritten_instructions = rewrite_payload.get("instructions")
                    if (
                        not isinstance(rewritten_instructions, str)
                        or not rewritten_instructions.strip()
                    ):
                        raise ValueError(
                            "instruction authority rewrite needs non-empty instructions"
                        )
                    if len(rewritten_instructions) > 500:
                        raise ValueError(
                            "instruction authority rewrite exceeded 500 characters"
                        )
                    candidate = copy.deepcopy(current)
                    candidate["instructions"] = rewritten_instructions.strip()
                    remaining_issues = _instruction_authority_issues(
                        original, candidate, equipment
                    )
                    current = candidate
                    if remaining_issues:
                        issues = remaining_issues
                        continue
                    current = _validate_reviewed_definition(candidate, equipment)
                    repaired_count += 1
                    break
                except (KeyError, TypeError, ValueError) as error:
                    issues = [str(error)]
            else:
                raise ValueError(
                    f"{definition['name']}: instruction authority remained invalid after "
                    "scoped LLM repairs and full LLM rewrites: " + "; ".join(issues)
                )
        reviewed_definitions.append(current)
    if repaired_count:
        print(
            f"Instruction authority repaired {repaired_count} definition(s).",
            flush=True,
        )
    return reviewed_definitions


def _run_post_rewrite_semantic_fixed_point(
    client: Any,
    definitions: list[dict[str, Any]],
    baseline_definitions: list[dict[str, Any]],
    existing_discards: list[str],
    equipment: dict[str, Any],
    call_json: Callable[..., str | None],
    initial_definition_names: set[str],
    max_cycles: int = 3,
) -> tuple[list[dict[str, Any]], list[str]]:
    current = copy.deepcopy(definitions)
    discards = list(existing_discards)
    pending_names = set(initial_definition_names)
    for cycle in range(1, max_cycles + 1):
        if not pending_names:
            return current, discards
        pending = [
            definition for definition in current if definition["name"] in pending_names
        ]
        print(
            f"Post-rewrite semantic cycle {cycle}/{max_cycles}: rechecking "
            f"{len(pending)} changed definition(s).",
            flush=True,
        )
        rechecked, cycle_discards = _run_instruction_entailment_audit(
            client,
            pending,
            [],
            equipment,
            call_json,
            batch_size=20,
        )
        discards.extend(cycle_discards)
        rechecked_by_name = {definition["name"]: definition for definition in rechecked}
        merged = []
        for definition in current:
            if definition["name"] not in pending_names:
                merged.append(definition)
            elif definition["name"] in rechecked_by_name:
                merged.append(rechecked_by_name[definition["name"]])

        before_authority = {
            definition["name"]: definition.get("instructions") for definition in merged
        }
        current = _run_instruction_authority_review(
            client,
            merged,
            baseline_definitions,
            equipment,
            call_json,
        )
        pending_names = {
            definition["name"]
            for definition in current
            if definition.get("instructions")
            != before_authority.get(definition["name"])
        }
    if pending_names:
        raise ValueError(
            "Post-rewrite semantic validation did not converge for: "
            + ", ".join(sorted(pending_names))
        )
    return current, discards


def _canonicalize_semantic_completeness_review(
    review: dict[str, Any],
) -> dict[str, Any]:
    canonical = copy.deepcopy(review)

    def first_present(source: dict[str, Any], names: tuple[str, ...], default: Any) -> Any:
        for name in names:
            if name in source:
                return source[name]
        return default

    requirements = first_present(canonical, ("requirements", "physicalRequirements"), [])
    if isinstance(requirements, dict):
        requirements = first_present(requirements, ("requirements", "items"), [])
    canonical_requirements = []
    if isinstance(requirements, list):
        for requirement in requirements:
            if not isinstance(requirement, dict):
                canonical_requirements.append(requirement)
                continue
            equipment_refs = first_present(
                requirement,
                ("anyOfEquipmentRefs", "equipmentRefs", "equipmentRef"),
                [],
            )
            capabilities = first_present(
                requirement,
                ("anyOfCapabilities", "capabilities", "capability"),
                [],
            )
            mandatory = first_present(
                requirement, ("mandatory", "required", "isMandatory"), True
            )
            if isinstance(mandatory, str) and mandatory.strip().casefold() in {"true", "false"}:
                mandatory = mandatory.strip().casefold() == "true"
            canonical_requirements.append({
                "description": first_present(
                    requirement, ("description", "requirement", "need"), ""
                ),
                "supportingText": first_present(
                    requirement, ("supportingText", "evidence", "quote"), ""
                ),
                "rationale": first_present(
                    requirement, ("rationale", "reason", "explanation"), ""
                ),
                "anyOfEquipmentRefs": (
                    [equipment_refs] if isinstance(equipment_refs, str) else equipment_refs
                ),
                "anyOfCapabilities": (
                    [capabilities] if isinstance(capabilities, str) else capabilities
                ),
                "mandatory": mandatory,
            })
    else:
        canonical_requirements = requirements

    contradictions = first_present(
        canonical, ("contradictions", "setupContradictions", "issues"), []
    )
    if isinstance(contradictions, dict):
        contradictions = first_present(contradictions, ("contradictions", "items"), [])
    canonical_contradictions = []
    if isinstance(contradictions, list):
        for contradiction in contradictions:
            if not isinstance(contradiction, dict):
                canonical_contradictions.append(contradiction)
                continue
            canonical_contradictions.append({
                "description": first_present(
                    contradiction, ("description", "issue", "contradiction", "reason"), ""
                ),
                "supportingText": first_present(
                    contradiction, ("supportingText", "evidence", "quote"), ""
                ),
            })
    else:
        canonical_contradictions = contradictions

    missing_equipment = first_present(
        canonical, ("missingEquipment", "missingImplements"), []
    )
    if isinstance(missing_equipment, str):
        missing_equipment = [missing_equipment]
    if isinstance(missing_equipment, dict):
        missing_equipment = first_present(
            missing_equipment, ("items", "missingEquipment", "requirements"), []
        )
    if isinstance(missing_equipment, list):
        normalized_missing_equipment = []
        for item in missing_equipment:
            value = item
            if isinstance(item, dict):
                value = first_present(
                    item,
                    ("name", "description", "equipment", "implement", "requirement"),
                    "",
                )
            if isinstance(value, str) and value.strip():
                normalized_missing_equipment.append(value.strip())
        missing_equipment = list(dict.fromkeys(normalized_missing_equipment))
    instruction_patch = first_present(
        canonical, ("instructionPatch", "instructionsPatch", "patch"), []
    )
    canonical = {
        "id": canonical.get("id"),
        "requirements": canonical_requirements,
        "missingEquipment": missing_equipment,
        "contradictions": canonical_contradictions,
        "instructionPatch": instruction_patch,
    }
    return canonical


def _validate_semantic_completeness_review(
    review: dict[str, Any],
    definition: dict[str, Any],
    declared_equipment_references: set[str],
) -> None:
    if review.get("id") != definition.get("id"):
        raise ValueError("semantic completeness repair changed the definition ID")
    requirements = review.get("requirements")
    missing_equipment = review.get("missingEquipment")
    contradictions = review.get("contradictions")
    instruction_patch = review.get("instructionPatch")
    if not isinstance(requirements, list):
        raise ValueError("requirements must be an array")
    if (
        not isinstance(missing_equipment, list)
        or any(not isinstance(value, str) or not value.strip() for value in missing_equipment)
    ):
        raise ValueError("missingEquipment must contain non-empty strings")
    if not isinstance(contradictions, list):
        raise ValueError("contradictions must be an array")
    if not isinstance(instruction_patch, list):
        raise ValueError("instructionPatch must be an array")
    validate_patch_operations_scope(
        instruction_patch, {"/instructions"}, {"/instructions"}
    )
    patched_definition = apply_json_patch(definition, instruction_patch)
    validate_changed_paths_scope(
        collect_changed_json_paths(definition, patched_definition),
        {"/instructions"},
        {"/instructions"},
    )
    patched_instructions = patched_definition.get("instructions")
    if (
        not isinstance(patched_instructions, str)
        or not patched_instructions.strip()
        or len(patched_instructions) > 500
    ):
        raise ValueError(
            "instructionPatch must produce non-empty instructions of at most 500 characters"
        )
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict) or set(requirement) != {
            "description", "supportingText", "rationale",
            "anyOfEquipmentRefs", "anyOfCapabilities", "mandatory",
        }:
            raise ValueError(f"requirement {index} has invalid fields")
        supporting_text = requirement["supportingText"]
        if not isinstance(requirement["description"], str) or not requirement["description"].strip():
            raise ValueError(f"requirement {index} has an invalid description")
        if (
            not isinstance(supporting_text, str)
            or not supporting_text.strip()
            or supporting_text.casefold() not in definition["instructions"].casefold()
        ):
            raise ValueError(
                f"requirement {index} supportingText is not an exact instruction substring"
            )
        if not isinstance(requirement["rationale"], str) or not requirement["rationale"].strip():
            raise ValueError(f"requirement {index} has an invalid rationale")
        if not isinstance(requirement["anyOfEquipmentRefs"], list):
            raise ValueError(f"requirement {index} anyOfEquipmentRefs must be an array")
        if not isinstance(requirement["anyOfCapabilities"], list):
            raise ValueError(f"requirement {index} anyOfCapabilities must be an array")
        unknown_refs = set(requirement["anyOfEquipmentRefs"]) - declared_equipment_references
        unknown_capabilities = (
            set(requirement["anyOfCapabilities"]) - EQUIPMENT_CAPABILITY_CATALOG
        )
        if unknown_refs:
            raise ValueError(f"requirement {index} uses unknown equipment refs {sorted(unknown_refs)}")
        if unknown_capabilities:
            raise ValueError(
                f"requirement {index} uses unknown capabilities {sorted(unknown_capabilities)}"
            )
        if not isinstance(requirement["mandatory"], bool):
            raise ValueError(f"requirement {index} mandatory must be boolean")
    for index, contradiction in enumerate(contradictions):
        if not isinstance(contradiction, dict) or set(contradiction) != {
            "description", "supportingText"
        }:
            raise ValueError(f"contradiction {index} has invalid fields")
        supporting_text = contradiction["supportingText"]
        if (
            not isinstance(contradiction["description"], str)
            or not contradiction["description"].strip()
            or not isinstance(supporting_text, str)
            or not supporting_text.strip()
            or supporting_text.casefold() not in definition["instructions"].casefold()
        ):
            raise ValueError(f"contradiction {index} is invalid")


def _repair_semantic_completeness_review(
    client: Any,
    review: dict[str, Any],
    definition: dict[str, Any],
    declared_equipment_references: set[str],
    call_json: Callable[..., str | None],
    loading_message: str,
) -> dict[str, Any]:
    current = _canonicalize_semantic_completeness_review(review)
    last_error: Exception | None = None
    for repair_pass in range(4):
        try:
            _validate_semantic_completeness_review(
                current, definition, declared_equipment_references
            )
            return current
        except (TypeError, ValueError) as error:
            last_error = error
            if repair_pass == 3:
                break
        content = call_json(
            client,
            [
                {
                    "role": "system",
                    "content": (
                        "Repair one malformed adversarial semantic-completeness review using "
                        "RFC 6902 JSON Patch. Return JSON only as {\"patch\":[...]}. Paths may "
                        "only be /review/requirements or below, /review/missingEquipment or "
                        "below, /review/contradictions or below, or /review/instructionPatch "
                        "or below. Never change /review/id. Preserve semantic findings; repair "
                        "their structure, exact supporting instruction substring, semantic "
                        "equipment reference, or supported capability enum. Optional equipment "
                        "must remain mandatory=false. Any /instructions replacement inside "
                        "instructionPatch must be non-empty and at most 500 characters."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "validationError": str(last_error),
                            "definition": definition,
                            "declaredEquipmentRefs": sorted(declared_equipment_references),
                            "allowedCapabilities": sorted(EQUIPMENT_CAPABILITY_CATALOG),
                            "review": current,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            f"{loading_message} repair {repair_pass + 1}/3",
            show_loading=False,
        )
        try:
            payload = _json_object(content, "semantic completeness repair")
            operations = payload.get("patch")
            if not isinstance(operations, list):
                raise ValueError("semantic completeness repair needs a patch array")
            allowed_path = re.compile(
                r"/review/(?:requirements|missingEquipment|contradictions|instructionPatch)(?:/.*)?"
            )
            for operation in operations:
                path = operation.get("path") if isinstance(operation, dict) else None
                from_path = operation.get("from") if isinstance(operation, dict) else None
                if (
                    not isinstance(path, str)
                    or allowed_path.fullmatch(path) is None
                    or (
                        from_path is not None
                        and (
                            not isinstance(from_path, str)
                            or allowed_path.fullmatch(from_path) is None
                        )
                    )
                ):
                    raise ValueError("semantic completeness repair used an out-of-scope path")
            repaired = apply_json_patch({"review": current}, operations)
            candidate = repaired.get("review") if isinstance(repaired, dict) else None
            if not isinstance(candidate, dict) or candidate.get("id") != definition.get("id"):
                raise ValueError("semantic completeness repair changed review identity")
            current = _canonicalize_semantic_completeness_review(candidate)
        except (IndexError, KeyError, TypeError, ValueError) as error:
            last_error = error
    patch_error = last_error
    for rewrite_pass in range(3):
        content = call_json(
            client,
            [
                {
                    "role": "system",
                    "content": (
                        "Rewrite one malformed adversarial semantic-completeness review. "
                        "Return JSON only as {\"review\":{...}} using the exact review schema "
                        "shown in the input. Preserve the review ID and all valid semantic "
                        "findings. Correct malformed fields and use exact substrings copied from "
                        "the supplied instructions for supportingText. Use only declared semantic "
                        "equipment references and allowed capabilities. Optional equipment must "
                        "remain mandatory=false. instructionPatch may only replace /instructions."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "validationError": str(last_error),
                            "definition": definition,
                            "declaredEquipmentRefs": sorted(declared_equipment_references),
                            "allowedCapabilities": sorted(EQUIPMENT_CAPABILITY_CATALOG),
                            "review": current,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            f"{loading_message} isolated rewrite {rewrite_pass + 1}/3",
            show_loading=False,
        )
        try:
            payload = _json_object(content, "semantic completeness isolated rewrite")
            candidate = payload.get("review")
            if not isinstance(candidate, dict):
                raise ValueError("isolated rewrite needs a review object")
            candidate = _canonicalize_semantic_completeness_review(candidate)
            _validate_semantic_completeness_review(
                candidate, definition, declared_equipment_references
            )
            return candidate
        except (IndexError, KeyError, TypeError, ValueError) as error:
            last_error = error
    if "supportingText" in str(last_error):
        for grounding_pass in range(3):
            content = call_json(
                client,
                [
                    {
                        "role": "system",
                        "content": (
                            "Ground semantic findings to exact character spans in the supplied "
                            "instructions. Return JSON only as {\"requirementSpans\":[{"
                            "\"index\":integer,\"start\":integer,\"end\":integer}],"
                            "\"contradictionSpans\":[{\"index\":integer,\"start\":integer,"
                            "\"end\":integer}]}. Cover every requirement and contradiction "
                            "exactly once. Offsets are zero-based Python slice offsets into the "
                            "instruction string; end is exclusive. Select the shortest non-empty "
                            "literal span that supports the semantic inference. Do not rewrite, "
                            "remove, or alter any semantic finding."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "instructions": definition["instructions"],
                                "requirements": current.get("requirements", []),
                                "contradictions": current.get("contradictions", []),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                f"{loading_message} evidence grounding {grounding_pass + 1}/3",
                show_loading=False,
            )
            try:
                payload = _json_object(content, "semantic completeness evidence grounding")
                requirement_spans = payload.get("requirementSpans")
                contradiction_spans = payload.get("contradictionSpans")
                requirements = current.get("requirements")
                contradictions = current.get("contradictions")
                if (
                    not isinstance(requirement_spans, list)
                    or not isinstance(contradiction_spans, list)
                    or not isinstance(requirements, list)
                    or not isinstance(contradictions, list)
                    or {item.get("index") for item in requirement_spans if isinstance(item, dict)}
                    != set(range(len(requirements)))
                    or {item.get("index") for item in contradiction_spans if isinstance(item, dict)}
                    != set(range(len(contradictions)))
                    or len(requirement_spans) != len(requirements)
                    or len(contradiction_spans) != len(contradictions)
                ):
                    raise ValueError("evidence grounding must cover every finding exactly once")
                instructions = definition["instructions"]

                def apply_spans(findings: list[dict[str, Any]], spans: list[dict[str, Any]]) -> None:
                    for span in spans:
                        if not isinstance(span, dict) or set(span) != {"index", "start", "end"}:
                            raise ValueError("evidence grounding span has invalid fields")
                        index = span["index"]
                        start = span["start"]
                        end = span["end"]
                        if (
                            not isinstance(index, int)
                            or not isinstance(start, int)
                            or not isinstance(end, int)
                            or start < 0
                            or end <= start
                            or end > len(instructions)
                        ):
                            raise ValueError("evidence grounding span is out of bounds")
                        findings[index]["supportingText"] = instructions[start:end]

                grounded = copy.deepcopy(current)
                apply_spans(grounded["requirements"], requirement_spans)
                apply_spans(grounded["contradictions"], contradiction_spans)
                _validate_semantic_completeness_review(
                    grounded, definition, declared_equipment_references
                )
                return grounded
            except (IndexError, KeyError, TypeError, ValueError) as error:
                last_error = error
        individually_grounded = copy.deepcopy(current)
        individual_grounding_failed = False
        for collection_name in ("requirements", "contradictions"):
            findings = individually_grounded.get(collection_name, [])
            if not isinstance(findings, list):
                individual_grounding_failed = True
                break
            for finding_index, finding in enumerate(findings):
                if not isinstance(finding, dict):
                    individual_grounding_failed = True
                    break
                supporting_text = finding.get("supportingText")
                if (
                    isinstance(supporting_text, str)
                    and supporting_text.strip()
                    and supporting_text.casefold() in definition["instructions"].casefold()
                ):
                    continue
                grounded_finding = False
                for grounding_pass in range(3):
                    content = call_json(
                        client,
                        [
                            {
                                "role": "system",
                                "content": (
                                    "Select one exact supporting character span for one semantic "
                                    "finding. Return JSON only as {\"start\":integer,"
                                    "\"end\":integer}. Offsets are zero-based Python slice "
                                    "offsets into instructions and end is exclusive. Select a "
                                    "short, non-empty literal span that supports the inference. "
                                    "Do not rewrite or alter the finding."
                                ),
                            },
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {
                                        "instructions": definition["instructions"],
                                        "finding": finding,
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                        f"{loading_message} isolated evidence {collection_name} "
                        f"{finding_index + 1} ({grounding_pass + 1}/3)",
                        show_loading=False,
                    )
                    try:
                        payload = _json_object(
                            content, "semantic completeness isolated evidence"
                        )
                        start = payload.get("start")
                        end = payload.get("end")
                        instructions = definition["instructions"]
                        if (
                            not isinstance(start, int)
                            or not isinstance(end, int)
                            or start < 0
                            or end <= start
                            or end > len(instructions)
                        ):
                            raise ValueError("isolated evidence span is out of bounds")
                        finding["supportingText"] = instructions[start:end]
                        grounded_finding = True
                        break
                    except (IndexError, KeyError, TypeError, ValueError) as error:
                        last_error = error
                if not grounded_finding:
                    individual_grounding_failed = True
                    break
            if individual_grounding_failed:
                break
        if not individual_grounding_failed:
            try:
                _validate_semantic_completeness_review(
                    individually_grounded, definition, declared_equipment_references
                )
                return individually_grounded
            except (TypeError, ValueError) as error:
                last_error = error
    raise ValueError(
        f"{definition['name']}: semantic completeness review remained invalid after "
        f"3 JSON Patch repairs, 3 isolated rewrites, and evidence grounding: {last_error}; "
        f"original patch failure: {patch_error}"
    )


def _run_instruction_completeness_review(
    client: Any,
    definitions: list[dict[str, Any]],
    existing_discards: list[str],
    equipment: dict[str, Any],
    call_json: Callable[..., str | None],
    *,
    batch_size: int = 5,
    max_cycles: int = 3,
    initial_definition_ids: set[str] | None = None,
    completed_definition_ids: set[str] | None = None,
    batch_completed_callback: Callable[
        [list[dict[str, Any]], list[str], set[str]], None
    ] | None = None,
) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    """Challenge instruction feasibility without trusting the entailment extraction."""
    equipment_context, _, id_to_reference = _review_equipment_context(equipment)
    current = copy.deepcopy(definitions)
    discards = list(existing_discards)
    changed_names: set[str] = set()
    completed_ids = set(completed_definition_ids or set())
    pending_ids = (
        {definition["id"] for definition in current} - completed_ids
        if initial_definition_ids is None
        else set(initial_definition_ids)
    )

    for cycle in range(1, max_cycles + 1):
        if not pending_ids:
            return current, discards, changed_names
        pending = [definition for definition in current if definition["id"] in pending_ids]
        batches = [
            pending[index:index + batch_size]
            for index in range(0, len(pending), batch_size)
        ]
        print(
            f"Adversarial semantic completeness cycle {cycle}/{max_cycles}: "
            f"reviewing {len(pending)} definition(s) in {len(batches)} batch(es).",
            flush=True,
        )
        next_pending_ids: set[str] = set()
        discarded_ids: set[str] = set()

        for batch_index, batch in enumerate(batches, start=1):
            batch_completed_ids: set[str] = set()
            referenced = _definitions_with_equipment_references(batch, id_to_reference)
            referenced_by_id = {definition["id"]: definition for definition in referenced}
            expected_ids = {definition["id"] for definition in batch}
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Act as an adversarial biomechanics and equipment-feasibility reviewer. "
                        "Reconstruct each movement's physical requirements from scratch; do not trust "
                        "or merely restate a previous extraction. First reason in ordinary physical "
                        "concepts about implements, attachments, quantities, independent stations, "
                        "support/rack/handoff, anchoring, clearance, starting position, and whether "
                        "the setup sequence is physically coherent. Then ground each implement need "
                        "to the supplied semantic equipment references or capability catalog. "
                        "Optional equipment must have mandatory=false and never makes an exercise "
                        "infeasible. Return JSON only as {\"reviews\":[{\"id\":string,"
                        "\"requirements\":[{\"description\":string,\"supportingText\":string,"
                        "\"rationale\":string,\"anyOfEquipmentRefs\":[string],"
                        "\"anyOfCapabilities\":[string],\"mandatory\":boolean}],"
                        "\"missingEquipment\":[string],\"contradictions\":[{"
                        "\"description\":string,\"supportingText\":string}],"
                        "\"instructionPatch\":[RFC6902 operations]}]}. Cover every ID exactly "
                        "once. supportingText must be an exact instruction substring that supports "
                        "the inference; rationale explains implicit needs such as a rack or a second "
                        "station. Put simultaneous needs in separate requirements and alternatives "
                        "in one requirement. Use missingEquipment only when no supplied reference or "
                        "capability can satisfy a mandatory physical need. Detect singular/plural and "
                        "quantity mismatches. A plural attachment or implement requires proof that "
                        "the available equipment supplies that quantity; one single-handle capability "
                        "does not satisfy two handles or two independent cable sides. A loaded barbell "
                        "press performed while lying or seated requires rack support or a human handoff "
                        "unless the instructions describe a physically viable self-setup. Treat body "
                        "positions as state transitions: lying or seated instructions cannot also "
                        "require stepping, walking, or hinging from standing without an explicit "
                        "transition that makes the sequence possible. instructionPatch may only replace /instructions, and "
                        "only when a coherent, identity-preserving rewrite can remove a contradiction "
                        "or substitute available equipment. Never erase a real requirement merely to "
                        "make the exercise pass. Allowed capabilities: "
                        + ", ".join(sorted(EQUIPMENT_CAPABILITY_CATALOG))
                        + ". Capability meanings: "
                        + json.dumps(CAPABILITY_SEMANTICS, ensure_ascii=False)
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"equipment": equipment_context, "definitions": referenced},
                        ensure_ascii=False,
                    ),
                },
            ]
            reviews: list[dict[str, Any]] | None = None
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    content = call_json(
                        client,
                        messages,
                        f"Semantic completeness batch {batch_index}/{len(batches)} "
                        f"cycle {cycle}/{max_cycles} ({attempt + 1}/3)",
                        show_loading=False,
                    )
                    payload = _json_object(content, "semantic completeness review")
                    candidate = payload.get("reviews")
                    if not isinstance(candidate, list):
                        raise ValueError("Semantic completeness response needs a reviews array")
                    ids = [item.get("id") for item in candidate if isinstance(item, dict)]
                    if len(candidate) != len(expected_ids) or set(ids) != expected_ids:
                        raise ValueError(
                            "Semantic completeness review must cover every definition exactly once"
                        )
                    reviews = candidate
                    break
                except (IndexError, KeyError, TypeError, ValueError) as error:
                    last_error = error
            if reviews is None:
                raise ValueError(
                    f"Semantic completeness batch {batch_index} remained invalid after 3 "
                    f"attempts: {last_error}"
                )

            verification_messages = [
                {
                    "role": "system",
                    "content": (
                        "Independently challenge an adversarial semantic-completeness review. "
                        "Do not defer to its findings. Detect omitted implicit requirements, "
                        "attachment or implement quantities, independent stations, rack/handoff, "
                        "anchors, clearance, and physically contradictory setup sequences. Also "
                        "remove false requirements and capability overreach: ordinary overhead "
                        "motion is not an over-implement transition, and optional conveniences are "
                        "not mandatory. Explicitly prove attachment quantities: a single handle or "
                        "single station cannot satisfy plural handles or bilateral independent cable "
                        "resistance. Explicitly prove how a loaded bar reaches the start of any lying "
                        "or seated barbell press; require rack support or handoff when no viable "
                        "self-setup exists. Reject body-position sequences that combine lying or "
                        "seated execution with unexplained standing actions such as stepping or "
                        "hinging. Return JSON only as {\"patch\":[RFC6902 operations]}. "
                        "Patch only requirements, missingEquipment, contradictions, or "
                        "instructionPatch below an existing /reviews/N object. Never change IDs, "
                        "add/remove/reorder reviews, or change definition fields. supportingText "
                        "must be an exact instruction substring. Use only supplied semantic "
                        "equipment references and capability enums."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "equipment": equipment_context,
                            "definitions": referenced,
                            "reviews": reviews,
                            "capabilityMeanings": CAPABILITY_SEMANTICS,
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            verified_reviews: list[dict[str, Any]] | None = None
            verification_fallback_ids: set[str] = set()
            verification_error: Exception | None = None
            for verification_attempt in range(3):
                try:
                    verification_content = call_json(
                        client,
                        verification_messages,
                        f"Verifying semantic completeness {batch_index}/{len(batches)} "
                        f"cycle {cycle}/{max_cycles} ({verification_attempt + 1}/3)",
                        show_loading=False,
                    )
                    verification_payload = _json_object(
                        verification_content, "semantic completeness verification"
                    )
                    operations = verification_payload.get("patch")
                    if not isinstance(operations, list):
                        raise ValueError(
                            "semantic completeness verification needs a patch array"
                        )
                    allowed_path = re.compile(
                        r"/reviews/\d+/(?:requirements|missingEquipment|contradictions|instructionPatch)(?:/.*)?"
                    )
                    for operation in operations:
                        path = operation.get("path") if isinstance(operation, dict) else None
                        from_path = operation.get("from") if isinstance(operation, dict) else None
                        if (
                            not isinstance(path, str)
                            or allowed_path.fullmatch(path) is None
                            or (
                                from_path is not None
                                and (
                                    not isinstance(from_path, str)
                                    or allowed_path.fullmatch(from_path) is None
                                )
                            )
                        ):
                            raise ValueError(
                                "semantic completeness verification used an out-of-scope path"
                            )
                    verified_payload = apply_json_patch(
                        {"reviews": reviews}, operations
                    )
                    candidate_reviews = verified_payload.get("reviews")
                    if not isinstance(candidate_reviews, list):
                        raise ValueError(
                            "semantic completeness verification produced invalid reviews"
                        )
                    candidate_ids = [
                        item.get("id") for item in candidate_reviews if isinstance(item, dict)
                    ]
                    if (
                        len(candidate_reviews) != len(expected_ids)
                        or set(candidate_ids) != expected_ids
                    ):
                        raise ValueError(
                            "semantic completeness verification changed review coverage"
                        )
                    verified_reviews = candidate_reviews
                    break
                except (IndexError, KeyError, TypeError, ValueError) as error:
                    verification_error = error
            if verified_reviews is None:
                verified_reviews = reviews
                verification_fallback_ids = set(expected_ids)
                print(
                    f"Semantic completeness verification batch {batch_index} remained "
                    "structurally invalid; isolating every definition for adjudication.",
                    flush=True,
                )
            reviews = verified_reviews

            definition_by_id = {definition["id"]: definition for definition in batch}
            for review in reviews:
                definition = definition_by_id[review["id"]]
                declared_refs = {
                    id_to_reference[equipment_id]
                    for equipment_id in [
                        definition.get("equipmentId"),
                        *definition.get("requiredAccessoryEquipmentIds", []),
                    ]
                    if equipment_id in id_to_reference
                }
                review = _repair_semantic_completeness_review(
                    client,
                    review,
                    definition,
                    declared_refs,
                    call_json,
                    f"Semantic completeness batch {batch_index}/{len(batches)} "
                    f"for {definition['name']}",
                )
                requirements = review.get("requirements")
                missing_equipment = review.get("missingEquipment")
                contradictions = review.get("contradictions")
                patch_operations = review.get("instructionPatch")
                if (
                    not isinstance(requirements, list)
                    or not isinstance(missing_equipment, list)
                    or any(not isinstance(value, str) or not value.strip() for value in missing_equipment)
                    or not isinstance(contradictions, list)
                    or not isinstance(patch_operations, list)
                ):
                    raise ValueError(
                        f"{definition['name']}: semantic completeness review has invalid fields"
                    )
                declared_ids = {
                    value
                    for value in [
                        definition.get("equipmentId"),
                        *definition.get("requiredAccessoryEquipmentIds", []),
                    ]
                    if value is not None
                }
                available_capabilities = _capabilities_for_equipment_ids(
                    equipment, declared_ids
                )
                unsupported: list[dict[str, Any]] = []
                for requirement_index, requirement in enumerate(requirements):
                    if not isinstance(requirement, dict) or set(requirement) != {
                        "description", "supportingText", "rationale",
                        "anyOfEquipmentRefs", "anyOfCapabilities", "mandatory",
                    }:
                        raise ValueError(
                            f"{definition['name']}: completeness requirement "
                            f"{requirement_index} has invalid fields"
                        )
                    supporting_text = requirement["supportingText"]
                    if (
                        not isinstance(requirement["description"], str)
                        or not requirement["description"].strip()
                        or not isinstance(supporting_text, str)
                        or not supporting_text.strip()
                        or supporting_text.casefold()
                        not in definition["instructions"].casefold()
                        or not isinstance(requirement["rationale"], str)
                        or not requirement["rationale"].strip()
                        or not isinstance(requirement["anyOfEquipmentRefs"], list)
                        or not isinstance(requirement["anyOfCapabilities"], list)
                        or not isinstance(requirement["mandatory"], bool)
                    ):
                        raise ValueError(
                            f"{definition['name']}: completeness requirement "
                            f"{requirement_index} is invalid"
                        )
                    unknown_refs = set(requirement["anyOfEquipmentRefs"]) - declared_refs
                    unknown_capabilities = (
                        set(requirement["anyOfCapabilities"])
                        - EQUIPMENT_CAPABILITY_CATALOG
                    )
                    if unknown_refs or unknown_capabilities:
                        raise ValueError(
                            f"{definition['name']}: completeness requirement uses unknown "
                            "equipment references or capabilities"
                        )
                    if requirement["mandatory"] and not (
                        set(requirement["anyOfEquipmentRefs"]).intersection(declared_refs)
                        or set(requirement["anyOfCapabilities"]).intersection(
                            available_capabilities
                        )
                    ):
                        unsupported.append(requirement)
                for contradiction in contradictions:
                    if (
                        not isinstance(contradiction, dict)
                        or set(contradiction) != {"description", "supportingText"}
                        or not isinstance(contradiction["description"], str)
                        or not contradiction["description"].strip()
                        or not isinstance(contradiction["supportingText"], str)
                        or not contradiction["supportingText"].strip()
                        or contradiction["supportingText"].casefold()
                        not in definition["instructions"].casefold()
                    ):
                        raise ValueError(
                            f"{definition['name']}: semantic contradiction is invalid"
                        )

                has_blocker = bool(unsupported or missing_equipment or contradictions)
                instructions_folded = definition["instructions"].casefold()
                semantic_risk = (
                    definition["id"] in verification_fallback_ids
                    or
                    (
                        "cable" in instructions_folded
                        and re.search(r"\b(?:handles|cables|attachments)\b", instructions_folded)
                        is not None
                    )
                    or (
                        "barbell" in instructions_folded
                        and "press" in instructions_folded
                        and re.search(r"\b(?:lie|lying|seated|bench)\b", instructions_folded)
                        is not None
                    )
                    or (
                        re.search(r"\b(?:lie|lying|seated)\b", instructions_folded)
                        is not None
                        and re.search(r"\b(?:step|walk|hinge)\b", instructions_folded)
                        is not None
                    )
                )
                if has_blocker or semantic_risk:
                    adjudicated_review: dict[str, Any] | None = None
                    adjudication_error: Exception | None = None
                    for adjudication_attempt in range(3):
                        try:
                            adjudication_content = call_json(
                                client,
                                [
                                    {
                                        "role": "system",
                                        "content": (
                                            "Isolated final adjudication of one exercise's physical "
                                            "requirements. Independently inspect the instructions, "
                                            "equipment, and proposed review. Return JSON only as "
                                            "{\"patch\":[RFC6902 operations]} correcting /review/"
                                            "requirements, /review/missingEquipment, /review/"
                                            "contradictions, or /review/instructionPatch. Remove false "
                                            "requirements and capability overreach. Ordinary floor "
                                            "space, overhead motion, hanging, pulling above a bar, "
                                            "cleaning to the shoulders, and squatting under a weight "
                                            "do not require OVER_IMPLEMENT_TRANSITION_CLEARANCE; that "
                                            "capability is only for the torso actually transitioning "
                                            "from one side of a support implement to the other. Check "
                                            "singular/plural quantities: a single cable handle or cable "
                                            "station does not satisfy two handles or two independent "
                                            "cable sides. A lying or seated loaded-bar press needs rack "
                                            "support or handoff unless a viable self-setup is explicit. "
                                            "A lying/seated setup cannot also require standing steps or "
                                            "hinging without a coherent transition. Optional equipment "
                                            "must remain non-blocking. If instructions can be coherently "
                                            "repaired without changing movement identity, patch only "
                                            "/review/instructionPatch with a /instructions replacement."
                                        ),
                                    },
                                    {
                                        "role": "user",
                                        "content": json.dumps(
                                            {
                                                "definition": referenced_by_id.get(
                                                    definition["id"], definition
                                                ),
                                                "equipment": equipment_context,
                                                "availableCapabilities": sorted(
                                                    available_capabilities
                                                ),
                                                "capabilityMeanings": CAPABILITY_SEMANTICS,
                                                "review": review,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    },
                                ],
                                f"Adjudicating semantic completeness {batch_index}/{len(batches)} "
                                f"for {definition['name']} ({adjudication_attempt + 1}/3)",
                                show_loading=False,
                            )
                            adjudication_payload = _json_object(
                                adjudication_content,
                                "semantic completeness adjudication",
                            )
                            operations = adjudication_payload.get("patch")
                            if not isinstance(operations, list):
                                raise ValueError("semantic adjudication needs a patch array")
                            allowed_path = re.compile(
                                r"/review/(?:requirements|missingEquipment|contradictions|instructionPatch)(?:/.*)?"
                            )
                            for operation in operations:
                                path = operation.get("path") if isinstance(operation, dict) else None
                                from_path = operation.get("from") if isinstance(operation, dict) else None
                                if (
                                    not isinstance(path, str)
                                    or allowed_path.fullmatch(path) is None
                                    or (
                                        from_path is not None
                                        and (
                                            not isinstance(from_path, str)
                                            or allowed_path.fullmatch(from_path) is None
                                        )
                                    )
                                ):
                                    raise ValueError(
                                        "semantic adjudication used an out-of-scope path"
                                    )
                            adjudicated_payload = apply_json_patch(
                                {"review": review}, operations
                            )
                            candidate_review = adjudicated_payload.get("review")
                            if not isinstance(candidate_review, dict):
                                raise ValueError("semantic adjudication produced invalid review")
                            adjudicated_review = _repair_semantic_completeness_review(
                                client,
                                candidate_review,
                                definition,
                                declared_refs,
                                call_json,
                                f"Semantic adjudication for {definition['name']}",
                            )
                            break
                        except (IndexError, KeyError, TypeError, ValueError) as error:
                            adjudication_error = error
                    if adjudicated_review is None:
                        raise ValueError(
                            f"{definition['name']}: semantic adjudication remained invalid "
                            f"after 3 attempts: {adjudication_error}"
                        )
                    review = adjudicated_review
                    requirements = review["requirements"]
                    missing_equipment = review["missingEquipment"]
                    contradictions = review["contradictions"]
                    patch_operations = review["instructionPatch"]
                    unsupported = []
                    for requirement in requirements:
                        if requirement["mandatory"] and not (
                            set(requirement["anyOfEquipmentRefs"]).intersection(declared_refs)
                            or set(requirement["anyOfCapabilities"]).intersection(
                                available_capabilities
                            )
                        ):
                            unsupported.append(requirement)
                    has_blocker = bool(
                        unsupported or missing_equipment or contradictions
                    )
                if has_blocker and patch_operations:
                    validate_patch_operations_scope(
                        patch_operations, {"/instructions"}, {"/instructions"}
                    )
                    patched = apply_json_patch(definition, patch_operations)
                    validate_changed_paths_scope(
                        collect_changed_json_paths(definition, patched),
                        {"/instructions"},
                        {"/instructions"},
                    )
                    patched = _validate_reviewed_definition(patched, equipment)
                    current = [
                        patched if item["id"] == definition["id"] else item
                        for item in current
                    ]
                    changed_names.add(definition["name"])
                    next_pending_ids.add(patched["id"])
                elif has_blocker:
                    reasons = []
                    if unsupported:
                        reasons.append(
                            "unsupported requirements "
                            + json.dumps(unsupported, ensure_ascii=False)
                        )
                    if missing_equipment:
                        reasons.append("missing equipment " + ", ".join(missing_equipment))
                    if contradictions:
                        reasons.append(
                            "contradictory setup "
                            + "; ".join(item["description"] for item in contradictions)
                        )
                    discards.append(
                        f"{definition['name']}: adversarial semantic completeness found "
                        + "; ".join(reasons)
                    )
                    discarded_ids.add(definition["id"])
                    batch_completed_ids.add(definition["id"])
                else:
                    batch_completed_ids.add(definition["id"])

            completed_ids.update(batch_completed_ids)
            current = [item for item in current if item["id"] not in discarded_ids]
            if batch_completed_callback is not None:
                batch_completed_callback(current, discards, completed_ids)

            print(
                f"Semantic completeness batches complete: {batch_index}/{len(batches)}",
                flush=True,
            )

        pending_ids = next_pending_ids

    if pending_ids:
        unresolved_names = [
            definition["name"] for definition in current if definition["id"] in pending_ids
        ]
        raise ValueError(
            "Adversarial semantic completeness repairs did not converge for: "
            + ", ".join(sorted(unresolved_names))
        )
    return current, discards, changed_names


def _apply_final_physical_invariants(
    definitions: list[dict[str, Any]],
    discards: list[str],
    equipment: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    all_items = _all_equipment_items(equipment)
    kept: list[dict[str, Any]] = []
    final_discards = list(discards)
    for definition in definitions:
        instructions = definition["instructions"]
        folded = instructions.casefold()
        declared_ids = {
            value
            for value in [
                definition.get("equipmentId"),
                *definition.get("requiredAccessoryEquipmentIds", []),
            ]
            if value is not None
        }
        declared_items = [all_items[value] for value in declared_ids if value in all_items]
        is_cable_movement = any(
            "CABLE" in str(item.get("type", "")).upper()
            or "cable" in str(item.get("name", "")).casefold()
            for item in declared_items
        )
        capabilities = _capabilities_for_equipment_ids(equipment, declared_ids)
        has_multi_handle_supply = any(
            token in capability
            for capability in capabilities
            for token in ("DUAL", "PAIR", "TWO_HANDLE", "SECOND_CABLE")
        )
        if (
            is_cable_movement
            and re.search(r"\b(?:two|both)\s+(?:cable\s+)?handles\b|\bhandles\b", folded)
            is not None
            and not has_multi_handle_supply
        ):
            final_discards.append(
                f"{definition['name']}: final physical invariant found plural cable handles "
                "without a declared dual-handle or second-cable capability"
            )
            continue
        has_lying_or_seated_state = re.search(
            r"\b(?:lie|lying|lies|seated)\b", folded
        ) is not None
        has_standing_action = re.search(
            r"\b(?:step|walk|hinge)\b", folded
        ) is not None
        has_explicit_standing_transition = re.search(
            r"\b(?:stand up|stands up|rise to standing|return to standing|then stand)\b",
            folded,
        ) is not None
        if (
            has_lying_or_seated_state
            and has_standing_action
            and not has_explicit_standing_transition
        ):
            final_discards.append(
                f"{definition['name']}: final physical invariant found incompatible "
                "lying/seated and standing-action instructions without an explicit transition"
            )
            continue
        kept.append(definition)
    return kept, final_discards


def _deterministic_definition_errors(
    definition: dict[str, Any], equipment: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return only errors whose predicates are fully decided by local data."""
    errors: list[dict[str, Any]] = []
    instructions = str(definition.get("instructions") or "")
    folded = instructions.casefold()
    all_items_by_id = _all_equipment_items(equipment)
    all_items = list(all_items_by_id.values())
    declared_ids = {
        value
        for value in [
            definition.get("equipmentId"),
            *definition.get("requiredAccessoryEquipmentIds", []),
        ]
        if isinstance(value, str)
    }
    declared_items = [all_items_by_id[value] for value in declared_ids if value in all_items_by_id]
    declared_aliases = {
        alias
        for item in declared_items
        for alias in _equipment_natural_aliases(item, all_items)
    }

    def add(path: str | None, code: str, message: str) -> None:
        errors.append({"path": path, "code": code, "message": message})

    if not instructions.strip():
        add("/instructions", "EMPTY_INSTRUCTIONS", "instructions must be non-empty")
    elif len(instructions) > 500:
        add("/instructions", "INSTRUCTIONS_TOO_LONG", "instructions must be at most 500 characters")
    if re.search(r"\b(?:PRIMARY|ACCESSORY)_[A-Z0-9_]+\b|\b[A-Z]+_\d+\b", instructions):
        add("/instructions", "INTERNAL_PLACEHOLDER", "instructions contain an internal placeholder")

    for equipment_id in sorted(declared_ids):
        item = all_items_by_id.get(equipment_id)
        if not item:
            add(None, "UNKNOWN_EQUIPMENT", f"declared equipment ID {equipment_id!r} is unknown")
            continue
        aliases = _equipment_natural_aliases(item, all_items)
        if aliases and not _instruction_mentions_equipment(instructions, aliases):
            add(
                "/instructions",
                "DECLARED_EQUIPMENT_NOT_USED",
                f"instructions must explicitly use declared equipment {item.get('name')!r}",
            )

    for equipment_id, item in all_items_by_id.items():
        if equipment_id in declared_ids:
            continue
        aliases = _equipment_natural_aliases(item, all_items)
        uniquely_undeclared_aliases = aliases - declared_aliases
        if (
            uniquely_undeclared_aliases
            and _instruction_mentions_equipment(instructions, uniquely_undeclared_aliases)
        ):
            add(
                "/instructions",
                "UNDECLARED_EQUIPMENT_REFERENCE",
                f"instructions reference undeclared supplied equipment {item.get('name')!r}",
            )

    for support_name, pattern in INSTRUCTION_SUPPORT_TERMS.items():
        if not pattern.search(instructions):
            continue
        if not any(
            pattern.search(str(item.get("name") or ""))
            or pattern.search(str(item.get("type") or ""))
            for item in declared_items
        ):
            add(
                "/instructions",
                "UNDECLARED_SETUP_SUPPORT",
                f"instructions require undeclared setup support: {support_name}",
            )

    primary_item = all_items_by_id.get(definition.get("equipmentId"), {})
    primary_name = str(primary_item.get("name") or "").casefold()
    definition_name = str(definition.get("name") or "")
    uses_pair = "pair" in primary_name or primary_name.endswith("s")
    is_single_definition = re.search(r"\bsingle(?:-arm)?\b", definition_name, re.I) is not None
    if uses_pair and is_single_definition:
        add(
            None,
            "STRUCTURAL_IMPLEMENT_QUANTITY",
            "single-implement movement is structurally linked to pair equipment",
        )
    singular_dumbbell_usage = re.search(
        r"\b(?:a|one|single) dumbbell\b", instructions, re.I
    ) is not None
    explicit_pair_usage = re.search(
        r"\b(?:two|both) dumbbells\b|\bdumbbells\b|"
        r"\b(?:a|one) dumbbell (?:in |with )?each hand\b",
        instructions,
        re.I,
    ) is not None
    if uses_pair and singular_dumbbell_usage and not explicit_pair_usage:
        add(
            "/instructions",
            "IMPLEMENT_QUANTITY_WORDING",
            "pair equipment instructions use exactly one dumbbell",
        )
    if "single" in primary_name and re.search(r"\bdumbbells\b|\btwo dumbbells\b", instructions, re.I):
        add(
            "/instructions",
            "IMPLEMENT_QUANTITY_WORDING",
            "single equipment instructions use multiple dumbbells",
        )

    if re.search(
        r"\blie\b[^.]{0,100}\bbarbell (?:at|on) (?:your |the )?chest\b",
        instructions,
        re.I,
    ):
        add(
            "/instructions",
            "UNEXPLAINED_LOADED_START",
            "instructions start lying with a loaded barbell at the chest without an executable setup",
        )

    wearable_declared = any(
        re.search(r"\b(?:vest|belt|pack)\b", str(item.get("name") or ""), re.I)
        for item in declared_items
    )
    if wearable_declared and re.search(
        r"\b(?:hold|holding|grasp|gripping|carry|carrying)\b[^.]{0,30}\b(?:vest|belt|pack)\b",
        instructions,
        re.I,
    ):
        add(
            "/instructions",
            "WEARABLE_NOT_WORN",
            "wearable resistance must be worn or secured, not held or carried",
        )

    if re.search(
        r"\b(?:underhand|supinated)\s+or\s+(?:overhand|pronated)\b|"
        r"\b(?:overhand|pronated)\s+or\s+(?:underhand|supinated)\b|"
        r"\b(?:rope|bar|handle)\s+or\s+(?:rope|bar|handle)\b",
        instructions,
        re.I,
    ):
        add(
            "/instructions",
            "MULTIPLE_MOVEMENT_VARIATIONS",
            "instructions combine alternative grip or attachment variations",
        )

    primary_muscles = definition.get("muscleGroups")
    secondary_muscles = definition.get("secondaryMuscleGroups")
    if not isinstance(primary_muscles, list) or not primary_muscles:
        add("/muscleGroups", "INVALID_PRIMARY_MUSCLES", "muscleGroups must be a non-empty array")
    else:
        invalid = [value for value in primary_muscles if value not in MUSCLE_GROUPS]
        joint_values = [value for value in primary_muscles if value in NON_MUSCLE_PRIMARY_GROUPS]
        if invalid:
            add("/muscleGroups", "UNKNOWN_PRIMARY_MUSCLE", f"unknown primary muscle values: {invalid}")
        if joint_values:
            add("/muscleGroups", "NON_MUSCLE_PRIMARY", f"joints/extremities cannot be primary muscles: {joint_values}")
        if len(primary_muscles) > 3:
            add("/muscleGroups", "TOO_MANY_PRIMARY_MUSCLES", "keep at most three actual prime-mover regions")
    if not isinstance(secondary_muscles, list):
        add("/secondaryMuscleGroups", "INVALID_SECONDARY_MUSCLES", "secondaryMuscleGroups must be an array")
    else:
        invalid = [value for value in secondary_muscles if value not in MUSCLE_GROUPS]
        duplicates = sorted(set(primary_muscles or []).intersection(secondary_muscles))
        if invalid:
            add("/secondaryMuscleGroups", "UNKNOWN_SECONDARY_MUSCLE", f"unknown secondary muscle values: {invalid}")
        if duplicates:
            add("/secondaryMuscleGroups", "DUPLICATE_MUSCLE_ROLE", f"muscles cannot be both primary and secondary: {duplicates}")
        if len(secondary_muscles) > 3:
            add("/secondaryMuscleGroups", "TOO_MANY_SECONDARY_MUSCLES", "keep at most three materially trained assistant regions")

    category = definition.get("exerciseCategory")
    if definition.get("exerciseType") in {"COUNTUP", "COUNTDOWN"}:
        if category is not None:
            add("/exerciseCategory", "TIMED_CATEGORY", "timed definitions require null exerciseCategory")
    elif category not in EXERCISE_CATEGORIES:
        add("/exerciseCategory", "INVALID_CATEGORY", "exerciseCategory is outside the closed enum")
    return errors


def _repair_deterministic_definition_errors(
    client: Any,
    definition: dict[str, Any],
    equipment: dict[str, Any],
    errors: list[dict[str, Any]],
    caller: Callable[..., str | None],
) -> dict[str, Any]:
    repairable_paths = {error["path"] for error in errors if error.get("path")}
    if any(error.get("path") is None for error in errors):
        raise ValueError("definition contains a non-repairable structural error")
    messages = [
        {
            "role": "system",
            "content": (
                "Repair an ExerciseDefinition using RFC 6902 JSON Patch. Return JSON only as "
                "{\"patch\":[...]}. Fix exactly the supplied deterministic validation errors. "
                "Change only the allowed paths. Never change structural identity fields. Use only "
                "the supplied muscle and category enums and only declared equipment."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "validationErrors": errors,
                    "allowedPatchPaths": sorted(repairable_paths),
                    "allowedMuscleGroups": sorted(MUSCLE_GROUPS),
                    "allowedExerciseCategories": sorted(EXERCISE_CATEGORIES),
                    "definition": definition,
                    "declaredEquipment": [
                        _all_equipment_items(equipment)[equipment_id]
                        for equipment_id in [
                            definition.get("equipmentId"),
                            *definition.get("requiredAccessoryEquipmentIds", []),
                        ]
                        if equipment_id in _all_equipment_items(equipment)
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]
    content = caller(client, messages, "", show_loading=False)
    payload = _json_object(content, "deterministic definition repair")
    operations = payload.get("patch")
    if not isinstance(operations, list):
        raise ValueError("deterministic definition repair must contain a patch array")
    validate_patch_operations_scope(operations, repairable_paths, repairable_paths)
    patched = apply_json_patch(definition, operations)
    validate_changed_paths_scope(
        collect_changed_json_paths(definition, patched), repairable_paths, repairable_paths
    )
    return _validate_reviewed_definition(patched, equipment)


def _structured_definition_errors(
    definition: dict[str, Any], equipment: dict[str, Any]
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []

    def add(path: str | None, code: str, message: str) -> None:
        errors.append({"path": path, "code": code, "message": message})

    if not isinstance(definition.get("name"), str) or not definition["name"].strip():
        add("/name", "INVALID_NAME", "name must be a non-empty string")
    if definition.get("exerciseType") not in EXERCISE_TYPES:
        add(None, "INVALID_EXERCISE_TYPE", "exerciseType is outside the closed enum")
    primary_ids, accessory_ids = _equipment_ids(equipment)
    equipment_id = definition.get("equipmentId")
    if equipment_id is not None and equipment_id not in primary_ids:
        add(None, "UNKNOWN_PRIMARY_EQUIPMENT", f"unknown equipmentId {equipment_id!r}")
    accessories = definition.get("requiredAccessoryEquipmentIds")
    if not isinstance(accessories, list) or set(accessories) - accessory_ids:
        add(None, "UNKNOWN_ACCESSORY_EQUIPMENT", "requiredAccessoryEquipmentIds contains unknown IDs")
    primary_muscles = definition.get("muscleGroups")
    secondary_muscles = definition.get("secondaryMuscleGroups")
    if not isinstance(primary_muscles, list) or not primary_muscles:
        add("/muscleGroups", "INVALID_PRIMARY_MUSCLES", "muscleGroups must be a non-empty array")
    else:
        invalid = [value for value in primary_muscles if value not in MUSCLE_GROUPS]
        joint_values = [value for value in primary_muscles if value in NON_MUSCLE_PRIMARY_GROUPS]
        if invalid:
            add("/muscleGroups", "UNKNOWN_PRIMARY_MUSCLE", f"unknown primary muscle values: {invalid}")
        if joint_values:
            add("/muscleGroups", "NON_MUSCLE_PRIMARY", f"joints/extremities cannot be primary muscles: {joint_values}")
        if len(primary_muscles) > 3:
            add("/muscleGroups", "TOO_MANY_PRIMARY_MUSCLES", "keep at most three actual prime-mover regions")
    if not isinstance(secondary_muscles, list):
        add("/secondaryMuscleGroups", "INVALID_SECONDARY_MUSCLES", "secondaryMuscleGroups must be an array")
    else:
        invalid = [value for value in secondary_muscles if value not in MUSCLE_GROUPS]
        duplicates = sorted(set(primary_muscles or []).intersection(secondary_muscles))
        if invalid:
            add("/secondaryMuscleGroups", "UNKNOWN_SECONDARY_MUSCLE", f"unknown secondary muscle values: {invalid}")
        if duplicates:
            add("/secondaryMuscleGroups", "DUPLICATE_MUSCLE_ROLE", f"muscles cannot be both primary and secondary: {duplicates}")
        if len(secondary_muscles) > 3:
            add("/secondaryMuscleGroups", "TOO_MANY_SECONDARY_MUSCLES", "keep at most three materially trained assistant regions")
    category = definition.get("exerciseCategory")
    if definition.get("exerciseType") in {"COUNTUP", "COUNTDOWN"}:
        if category is not None:
            add("/exerciseCategory", "TIMED_CATEGORY", "timed definitions require null exerciseCategory")
    elif category not in EXERCISE_CATEGORIES:
        add("/exerciseCategory", "INVALID_CATEGORY", "exerciseCategory is outside the closed enum")
    if "instructions" in definition or "instructionEquipmentIds" in definition:
        add(None, "OBSOLETE_INSTRUCTION_FIELD", "definition contains removed instruction fields")
    return errors


def _run_deterministic_definition_validation(
    client: Any,
    definitions: list[dict[str, Any]],
    discards: list[str],
    equipment: dict[str, Any],
    caller: Callable[..., str | None],
    progress_callback: Callable[[int, list[dict[str, Any]], list[str]], None] | None = None,
    completed_definition_count: int = 0,
    resumed_kept: list[dict[str, Any]] | None = None,
    resumed_discards: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    kept = copy.deepcopy(resumed_kept) if resumed_kept is not None else []
    current_discards = (
        list(resumed_discards) if resumed_discards is not None else list(discards)
    )
    repaired_count = 0
    if completed_definition_count:
        print(
            f"Resuming deterministic validation with {completed_definition_count}/"
            f"{len(definitions)} definition(s) complete.",
            flush=True,
        )
    for definition_index, definition in enumerate(
        definitions[completed_definition_count:], start=completed_definition_count + 1
    ):
        current = copy.deepcopy(definition)
        current.pop("instructions", None)
        current.pop("instructionEquipmentIds", None)
        errors = _structured_definition_errors(current, equipment)
        for _ in range(3):
            if not errors:
                break
            if any(error.get("path") is None for error in errors):
                break
            try:
                current = _repair_deterministic_definition_errors(
                    client, current, equipment, errors, caller
                )
                repaired_count += 1
            except (IndexError, KeyError, TypeError, ValueError):
                continue
            errors = _structured_definition_errors(current, equipment)
        if errors:
            current_discards.append(
                f"{definition['name']}: deterministic validation failed: "
                + "; ".join(error["message"] for error in errors)
            )
        else:
            kept.append(current)
        if progress_callback is not None:
            progress_callback(definition_index, kept, current_discards)
    if repaired_count:
        print(f"Deterministic validation repaired {repaired_count} definition(s).", flush=True)
    print(
        f"Deterministic validation kept {len(kept)} definition(s) and excluded "
        f"{len(definitions) - len(kept)} unresolved definition(s).",
        flush=True,
    )
    return kept, current_discards


def _content_authority_prompt(
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    *,
    adversarial: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    equipment_context, _, id_to_reference = _review_equipment_context(equipment)
    definition_references: dict[str, str] = {}
    referenced_definitions = _definitions_with_equipment_references(
        definitions, id_to_reference
    )
    for index, definition in enumerate(referenced_definitions, start=1):
        reference = f"DEFINITION_{index}"
        definition_references[reference] = definitions[index - 1]["id"]
        definition["id"] = reference
        definition.pop("instructionEquipmentIds", None)
    messages = [
        {
            "role": "system",
            "content": (
                "You are the final semantic authority for reusable exercise definitions. "
                "Return JSON only as {\"reviews\":[...]}, exactly one review per supplied "
                "definition. Each review has exactly id, decision, checks, issues, patch, and "
                "discardReason. checks is an object containing exactly movementIdentity, "
                "setupEquipment, implementQuantity, loadingMechanics, instructionConsistency, "
                "primaryMuscles, secondaryMuscles, and exerciseCategory. Every check contains "
                "exactly the string PASS or FAIL. Put concise explanations for failures in "
                "issues rather than repeating prose for passing checks. "
                "decision is KEEP, REPAIR, or DISCARD. KEEP is allowed only when every check is "
                "PASS. REPAIR must fix every failed check that is content-owned; DISCARD is "
                "required for any failed structural check. issues is an array of "
                "short strings. patch is RFC 6902 and may change only /instructions, "
                "/muscleGroups, /secondaryMuscleGroups, and /exerciseCategory. discardReason "
                "is null unless DISCARD. Never change name, exerciseType, equipmentId, "
                "accessory IDs, body-weight percentage, or id; if those structural fields do "
                "not describe the named movement or the movement needs undeclared equipment, "
                "DISCARD it so a new definition can be created. Judge the complete contract: "
                "the name and instructions must describe the same movement and variation; "
                "instructions must be executable, concise, at most 500 characters, use only "
                "declared equipment, contain no internal placeholders, invented quantities, "
                "contradictory positions, unrelated variations, or unexplained setup objects; "
                "singular and pair implements must agree with the structural equipment; "
                "muscleGroups contains only actual primary movers, never joints or mere "
                "stabilizers; secondaryMuscleGroups contains meaningful assistants and "
                "stabilizers without duplicating primary muscles; exerciseCategory must match "
                "the movement and must be null for COUNTUP or COUNTDOWN definitions. Optional "
                "equipment is valid only when the movement remains the "
                "same without it and the instructions clearly mark it optional. Correct every "
                "repairable content error in one patch. Do not preserve a bad value merely "
                "because it was supplied. Treat every support surface, balance aid, raised edge, "
                "rack, seat, attachment, and hand-held implement named by the setup as equipment "
                "that must be declared. Verify that wearable resistance is worn, that a pair "
                "definition actually uses two implements, that a single-implement movement is "
                "not stored under pair equipment, and that the declared load mechanically "
                "resists the named primary joint action rather than merely resting on an "
                "unrelated body segment. A position-qualified name such as rack, overhead, "
                "incline, pike, reverse, or single-arm must be expressed by the instructions. "
                "Do not make stylistic edits when the contract is already correct. Use only the "
                "allowed muscle and category enums."
                + (
                    " This is an independent adversarial verification of another review. Assume "
                    "it may have overlooked a subtle contradiction. Re-derive the movement and "
                    "equipment requirements from scratch and return KEEP only after actively "
                    "trying to falsify the complete contract."
                    if adversarial else ""
                )
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "equipment": equipment_context,
                    "allowedMuscleGroups": sorted(MUSCLE_GROUPS),
                    "allowedExerciseCategories": sorted(EXERCISE_CATEGORIES),
                    "definitions": referenced_definitions,
                },
                ensure_ascii=False,
            ),
        },
    ]
    return messages, definition_references


def _apply_content_authority_response(
    content: str | None,
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    definition_references: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    payload = _json_object(content, "content authority review")
    reviews = payload.get("reviews")
    if not isinstance(reviews, list) or any(not isinstance(item, dict) for item in reviews):
        raise ValueError("content authority response must contain a reviews array")
    reviews_by_id = {review.get("id"): review for review in reviews}
    if set(reviews_by_id) != set(definition_references) or len(reviews) != len(reviews_by_id):
        raise ValueError("content authority response must cover every definition exactly once")
    definitions_by_id = {definition["id"]: definition for definition in definitions}
    kept: list[dict[str, Any]] = []
    discards: list[str] = []
    for reference, definition_id in definition_references.items():
        definition = definitions_by_id[definition_id]
        review = reviews_by_id[reference]
        decision = review.get("decision")
        issues = review.get("issues")
        checks = review.get("checks")
        patch_operations = review.get("patch")
        discard_reason = review.get("discardReason")
        if decision not in {"KEEP", "REPAIR", "DISCARD"}:
            raise ValueError(f"{definition['name']}: invalid content authority decision")
        if not isinstance(checks, dict) or set(checks) != CONTENT_AUTHORITY_CHECKS:
            raise ValueError(f"{definition['name']}: content authority checks are incomplete")
        failed_checks = []
        for check_name, check in checks.items():
            if check not in {"PASS", "FAIL"}:
                raise ValueError(f"{definition['name']}: invalid {check_name} authority check")
            if check == "FAIL":
                failed_checks.append(check_name)
        if decision == "KEEP" and failed_checks:
            raise ValueError(
                f"{definition['name']}: KEEP has failed checks {sorted(failed_checks)}"
            )
        if decision == "DISCARD" and not failed_checks:
            raise ValueError(f"{definition['name']}: DISCARD requires a failed structural check")
        if not isinstance(issues, list) or any(not isinstance(item, str) for item in issues):
            raise ValueError(f"{definition['name']}: content authority issues must be strings")
        if not isinstance(patch_operations, list):
            raise ValueError(f"{definition['name']}: content authority patch must be an array")
        if decision == "DISCARD":
            if not isinstance(discard_reason, str) or not discard_reason.strip():
                raise ValueError(f"{definition['name']}: discard requires a reason")
            if patch_operations:
                raise ValueError(f"{definition['name']}: discarded definition cannot be patched")
            discards.append(f"{definition['name']}: content authority discarded: {discard_reason.strip()}")
            continue
        if discard_reason not in {None, ""}:
            raise ValueError(f"{definition['name']}: retained definition has discardReason")
        if decision == "KEEP" and patch_operations:
            raise ValueError(f"{definition['name']}: KEEP decision cannot contain a patch")
        if decision == "REPAIR" and not patch_operations:
            raise ValueError(f"{definition['name']}: REPAIR decision requires a patch")
        validate_patch_operations_scope(
            patch_operations, CONTENT_AUTHORITY_PATCH_PATHS, CONTENT_AUTHORITY_PATCH_PATHS
        )
        patched = apply_json_patch(definition, patch_operations)
        validate_changed_paths_scope(
            collect_changed_json_paths(definition, patched),
            CONTENT_AUTHORITY_PATCH_PATHS,
            CONTENT_AUTHORITY_PATCH_PATHS,
        )
        kept.append(_validate_reviewed_definition(patched, equipment))
    return kept, discards


def _run_content_authority_review(
    client: Any,
    definitions: list[dict[str, Any]],
    discards: list[str],
    equipment: dict[str, Any],
    caller: Callable[..., str | None],
    *,
    max_workers: int = 1,
    completed_batch_count: int = 0,
    resumed_kept: list[dict[str, Any]] | None = None,
    resumed_discards: list[str] | None = None,
    batch_completed_callback: Callable[[int, list[dict[str, Any]], list[str]], None] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    batches = [
        definitions[index:index + CONTENT_AUTHORITY_BATCH_SIZE]
        for index in range(0, len(definitions), CONTENT_AUTHORITY_BATCH_SIZE)
    ]
    kept = copy.deepcopy(resumed_kept) if resumed_kept is not None else []
    current_discards = list(resumed_discards) if resumed_discards is not None else list(discards)
    if completed_batch_count:
        print(
            f"Resuming final content authority with {completed_batch_count}/{len(batches)} "
            "batch(es) complete.", flush=True,
        )
    else:
        print(
            f"Auditing final definition field authority in {len(batches)} batch(es).",
            flush=True,
        )
    def review_batch(
        batch_index: int, batch: list[dict[str, Any]]
    ) -> tuple[int, list[dict[str, Any]], list[str]]:
        messages, references = _content_authority_prompt(batch, equipment)
        last_error: Exception | None = None
        for attempt in range(1, 4):
            content: str | None = None
            try:
                content = caller(client, messages, "", show_loading=False)
                batch_kept, batch_discards = _apply_content_authority_response(
                    content, batch, equipment, references
                )
                if batch_kept:
                    verifier_messages, verifier_references = _content_authority_prompt(
                        batch_kept, equipment, adversarial=True
                    )
                    verifier_content = caller(
                        client, verifier_messages, "", show_loading=False
                    )
                    batch_kept, verifier_discards = _apply_content_authority_response(
                        verifier_content, batch_kept, equipment, verifier_references
                    )
                    batch_discards.extend(verifier_discards)
                return batch_index, batch_kept, batch_discards
            except (ValueError, json.JSONDecodeError) as error:
                last_error = error
                if attempt < 3:
                    messages.append({"role": "assistant", "content": content or ""})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"The structured response was invalid: {error}. Return the complete "
                            "corrected reviews object covering every requested definition exactly once."
                        ),
                    })
        if len(batch) > 1:
            isolated_kept: list[dict[str, Any]] = []
            isolated_discards: list[str] = []
            for definition in batch:
                _, single_kept, single_discards = review_batch(
                    batch_index, [definition]
                )
                isolated_kept.extend(single_kept)
                isolated_discards.extend(single_discards)
            return batch_index, isolated_kept, isolated_discards
        raise ValueError(
            f"{batch[0]['name']}: content authority remained invalid after 3 attempts: "
            f"{last_error}"
        ) from last_error

    pending = list(enumerate(batches[completed_batch_count:], start=completed_batch_count + 1))
    worker_count = min(max(1, max_workers), max(1, len(pending)))
    buffered_results: dict[int, tuple[list[dict[str, Any]], list[str]]] = {}
    next_commit_index = completed_batch_count + 1
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(review_batch, batch_index, batch): batch_index
            for batch_index, batch in pending
        }
        for future in as_completed(futures):
            batch_index, batch_kept, batch_discards = future.result()
            buffered_results[batch_index] = (batch_kept, batch_discards)
            while next_commit_index in buffered_results:
                committed_kept, committed_discards = buffered_results.pop(next_commit_index)
                kept.extend(committed_kept)
                current_discards.extend(committed_discards)
                if batch_completed_callback is not None:
                    batch_completed_callback(next_commit_index, kept, current_discards)
                print(
                    f"Content authority batches complete: {next_commit_index}/{len(batches)}",
                    flush=True,
                )
                next_commit_index += 1
    return kept, current_discards


def review_library_instruction_entailment(
    client: Any,
    checkpoint: dict[str, Any],
    *,
    instruction_entailment_call: Callable[..., str | None] = json_call_chat_max_with_loading,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    max_workers: int = 1,
) -> dict[str, Any]:
    if (
        isinstance(checkpoint.get("preInstructionEntailmentDefinitions"), list)
        and checkpoint.get("instructionEntailmentBaselineVersion") != 2
        and any(
            "instructions require unavailable capability alternatives" in str(reason)
            for reason in checkpoint.get("semanticDiscards", [])
        )
    ):
        raise ValueError(
            "This checkpoint preserved a reduced result from the old instruction-entailment "
            "contract and cannot restore its falsely discarded definitions. Use the clean "
            "pre-entailment library as the checkpoint instead."
        )
    definitions = checkpoint.get(
        "preInstructionEntailmentDefinitions",
        checkpoint.get("exerciseDefinitions"),
    )
    equipments = checkpoint.get("equipments")
    accessories = checkpoint.get("accessoryEquipments")
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("Checkpoint contains no reviewed exerciseDefinitions")
    if not isinstance(equipments, list) or not isinstance(accessories, list):
        raise ValueError("Checkpoint has invalid equipment collections")
    equipment = {"equipments": equipments, "accessoryEquipments": accessories}
    completeness_upgrade_rebuild = (
        checkpoint.get("semanticCompletenessVersion") == 1
    )
    checkpoint_discards = list(map(str, checkpoint.get("semanticDiscards", [])))
    if completeness_upgrade_rebuild:
        checkpoint_discards = [
            reason
            for reason in checkpoint_discards
            if "adversarial semantic completeness found" not in reason
            and "instructions require unavailable capability alternatives" not in reason
        ]
        print(
            "Semantic completeness contract upgraded; rebuilding from the preserved "
            "pre-completeness definitions.",
            flush=True,
        )
    batch_size = 20
    progress = checkpoint.get("instructionEntailmentProgress")
    completed_batch_count = 0
    resumed_kept: list[dict[str, Any]] | None = None
    resumed_discards: list[str] | None = None
    if isinstance(progress, dict) and (
        progress.get("batchSize") == batch_size
        and progress.get("sourceDefinitionIds")
        == [definition["id"] for definition in definitions]
        and isinstance(progress.get("completedBatchCount"), int)
        and isinstance(progress.get("keptDefinitions"), list)
        and isinstance(progress.get("discards"), list)
    ):
        completed_batch_count = progress["completedBatchCount"]
        resumed_kept = copy.deepcopy(progress["keptDefinitions"])
        resumed_discards = list(map(str, progress["discards"]))

    def save_progress(
        completed_count: int,
        kept_definitions: list[dict[str, Any]],
        current_discards: list[str],
    ) -> None:
        if progress_callback is None:
            return
        snapshot = copy.deepcopy(checkpoint)
        snapshot["preInstructionEntailmentDefinitions"] = copy.deepcopy(definitions)
        snapshot["instructionEntailmentBaselineVersion"] = 2
        snapshot["instructionEntailmentProgress"] = {
            "batchSize": batch_size,
            "sourceDefinitionIds": [definition["id"] for definition in definitions],
            "completedBatchCount": completed_count,
            "keptDefinitions": copy.deepcopy(kept_definitions),
            "discards": list(current_discards),
        }
        progress_callback(snapshot)

    completed_entailment = (
        not completeness_upgrade_rebuild
        and
        checkpoint.get("instructionEntailmentBaselineVersion") == 2
        and isinstance(checkpoint.get("preInstructionEntailmentDefinitions"), list)
        and "instructionEntailmentProgress" not in checkpoint
        and isinstance(checkpoint.get("exerciseDefinitions"), list)
    )
    if completed_entailment:
        reviewed = copy.deepcopy(checkpoint["exerciseDefinitions"])
        discards = list(map(str, checkpoint.get("semanticDiscards", [])))
        print(
            f"Reusing {len(reviewed)} completed instruction-entailment definition(s).",
            flush=True,
        )
    else:
        reviewed, discards = _run_instruction_entailment_audit(
            client,
            definitions,
            checkpoint_discards,
            equipment,
            instruction_entailment_call,
            batch_size=batch_size,
            completed_batch_count=completed_batch_count,
            resumed_kept=resumed_kept,
            resumed_discards=resumed_discards,
            batch_completed_callback=save_progress,
        )
    before_authority = {
        definition["name"]: definition.get("instructions") for definition in reviewed
    }
    reviewed = _run_instruction_authority_review(
        client,
        reviewed,
        definitions,
        equipment,
        instruction_entailment_call,
    )
    authority_changed_names = {
        definition["name"]
        for definition in reviewed
        if definition.get("instructions") != before_authority.get(definition["name"])
    }
    if checkpoint.get("postRewriteSemanticVersion") != 1:
        baseline_by_name = {
            definition["name"]: definition.get("instructions")
            for definition in definitions
        }
        authority_changed_names.update(
            definition["name"]
            for definition in reviewed
            if definition.get("instructions")
            != baseline_by_name.get(definition["name"])
        )
    reviewed, discards = _run_post_rewrite_semantic_fixed_point(
        client,
        reviewed,
        definitions,
        discards,
        equipment,
        instruction_entailment_call,
        authority_changed_names,
    )
    if checkpoint.get("semanticCompletenessVersion") != 2:
        completeness_progress = checkpoint.get("semanticCompletenessProgress")
        completeness_completed_ids: set[str] = set()
        if (
            isinstance(completeness_progress, dict)
            and isinstance(completeness_progress.get("definitions"), list)
            and isinstance(completeness_progress.get("discards"), list)
            and isinstance(completeness_progress.get("completedDefinitionIds"), list)
        ):
            reviewed = copy.deepcopy(completeness_progress["definitions"])
            discards = list(map(str, completeness_progress["discards"]))
            completeness_completed_ids = set(
                map(str, completeness_progress["completedDefinitionIds"])
            )
            print(
                f"Resuming adversarial semantic completeness with "
                f"{len(completeness_completed_ids)} definition(s) already complete.",
                flush=True,
            )

        def save_completeness_progress(
            current_definitions: list[dict[str, Any]],
            current_discards: list[str],
            completed_ids: set[str],
        ) -> None:
            if progress_callback is None:
                return
            snapshot = copy.deepcopy(checkpoint)
            snapshot["exerciseDefinitions"] = copy.deepcopy(current_definitions)
            snapshot["semanticDiscards"] = list(current_discards)
            snapshot["preInstructionEntailmentDefinitions"] = copy.deepcopy(definitions)
            snapshot["instructionEntailmentBaselineVersion"] = 2
            snapshot["postRewriteSemanticVersion"] = 1
            snapshot.pop("instructionEntailmentProgress", None)
            snapshot["semanticCompletenessProgress"] = {
                "definitions": copy.deepcopy(current_definitions),
                "discards": list(current_discards),
                "completedDefinitionIds": sorted(completed_ids),
            }
            progress_callback(snapshot)

        completeness_pending_ids: set[str] | None = None
        for completeness_cycle in range(1, 4):
            reviewed, discards, completeness_changed_names = (
                _run_instruction_completeness_review(
                    client,
                    reviewed,
                    discards,
                    equipment,
                    instruction_entailment_call,
                    initial_definition_ids=completeness_pending_ids,
                    completed_definition_ids=(
                        completeness_completed_ids
                        if completeness_cycle == 1
                        else None
                    ),
                    batch_completed_callback=(
                        save_completeness_progress
                        if completeness_cycle == 1
                        else None
                    ),
                )
            )
            if not completeness_changed_names:
                break
            instructions_before_entailment = {
                definition["id"]: definition.get("instructions")
                for definition in reviewed
            }
            reviewed, discards = _run_post_rewrite_semantic_fixed_point(
                client,
                reviewed,
                definitions,
                discards,
                equipment,
                instruction_entailment_call,
                completeness_changed_names,
            )
            completeness_pending_ids = {
                definition["id"]
                for definition in reviewed
                if definition.get("instructions")
                != instructions_before_entailment.get(definition["id"])
            }
            if not completeness_pending_ids:
                break
        else:
            raise ValueError(
                "Instruction entailment and adversarial completeness did not converge "
                "after 3 cross-check cycles"
            )
    deterministic_source_definitions = copy.deepcopy(reviewed)
    deterministic_progress = checkpoint.get("deterministicValidationProgress")
    deterministic_completed_count = 0
    deterministic_resumed_kept: list[dict[str, Any]] | None = None
    deterministic_resumed_discards: list[str] | None = None
    if (
        checkpoint.get("contentAuthorityVersion") != CONTENT_AUTHORITY_VERSION
        and isinstance(deterministic_progress, dict)
        and deterministic_progress.get("validatorVersion") == CONTENT_AUTHORITY_VERSION
        and deterministic_progress.get("sourceDefinitionIds")
        == [item["id"] for item in deterministic_source_definitions]
        and isinstance(deterministic_progress.get("completedDefinitionCount"), int)
        and isinstance(deterministic_progress.get("keptDefinitions"), list)
        and isinstance(deterministic_progress.get("discards"), list)
    ):
        deterministic_completed_count = deterministic_progress["completedDefinitionCount"]
        deterministic_resumed_kept = copy.deepcopy(deterministic_progress["keptDefinitions"])
        deterministic_resumed_discards = list(map(str, deterministic_progress["discards"]))

    def save_deterministic_progress(
        completed_count: int,
        kept_definitions: list[dict[str, Any]],
        current_discards: list[str],
    ) -> None:
        if progress_callback is None:
            return
        snapshot = copy.deepcopy(checkpoint)
        snapshot["exerciseDefinitions"] = copy.deepcopy(deterministic_source_definitions)
        snapshot["semanticDiscards"] = list(discards)
        snapshot["semanticCompletenessVersion"] = 2
        snapshot.pop("semanticCompletenessProgress", None)
        snapshot["deterministicValidationProgress"] = {
            "validatorVersion": CONTENT_AUTHORITY_VERSION,
            "sourceDefinitionIds": [item["id"] for item in deterministic_source_definitions],
            "completedDefinitionCount": completed_count,
            "keptDefinitions": copy.deepcopy(kept_definitions),
            "discards": list(current_discards),
        }
        progress_callback(snapshot)

    if checkpoint.get("contentAuthorityVersion") == CONTENT_AUTHORITY_VERSION:
        reviewed = copy.deepcopy(checkpoint.get("exerciseDefinitions", reviewed))
        discards = list(map(str, checkpoint.get("semanticDiscards", discards)))
        print(f"Reusing {len(reviewed)} deterministically validated definition(s).", flush=True)
    else:
        reviewed, discards = _run_deterministic_definition_validation(
            client,
            deterministic_source_definitions,
            discards,
            equipment,
            instruction_entailment_call,
            progress_callback=save_deterministic_progress,
            completed_definition_count=deterministic_completed_count,
            resumed_kept=deterministic_resumed_kept,
            resumed_discards=deterministic_resumed_discards,
        )
    reviewed, discards = _apply_final_physical_invariants(
        reviewed, discards, equipment
    )
    _validate_final_definition_semantics(reviewed, equipment)
    payload = _library_payload(
        reviewed,
        equipment,
        list(checkpoint.get("generationFailures", [])),
        discards,
        review_status="COMPLETE",
    )
    payload["preInstructionEntailmentDefinitions"] = copy.deepcopy(definitions)
    payload["instructionEntailmentBaselineVersion"] = 2
    payload["postRewriteSemanticVersion"] = 1
    payload["semanticCompletenessVersion"] = 2
    payload.pop("semanticCompletenessProgress", None)
    payload["contentAuthorityVersion"] = CONTENT_AUTHORITY_VERSION
    payload.pop("contentAuthorityProgress", None)
    payload.pop("deterministicValidationProgress", None)
    if isinstance(checkpoint.get("sourceExerciseDefinitions"), list):
        payload["sourceExerciseDefinitions"] = copy.deepcopy(
            checkpoint["sourceExerciseDefinitions"]
        )
    if isinstance(checkpoint.get("globalConsistencyProgress"), dict):
        payload["globalConsistencyProgress"] = copy.deepcopy(
            checkpoint["globalConsistencyProgress"]
        )
    return payload


def review_library_deterministic_validation(
    client: Any,
    checkpoint: dict[str, Any],
    *,
    repair_call: Callable[..., str | None] = json_call_chat_max_with_loading,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    definitions = checkpoint.get("exerciseDefinitions")
    equipments = checkpoint.get("equipments")
    accessories = checkpoint.get("accessoryEquipments")
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("Checkpoint contains no exerciseDefinitions")
    if not isinstance(equipments, list) or not isinstance(accessories, list):
        raise ValueError("Checkpoint has invalid equipment collections")
    equipment = {"equipments": equipments, "accessoryEquipments": accessories}
    # A deterministic revalidation starts a new diagnostic epoch. Older semantic and
    # instruction-review failures must not contaminate the canonical import artifact.
    baseline_discards: list[str] = []
    progress = checkpoint.get("deterministicValidationProgress")
    completed_count = 0
    resumed_kept: list[dict[str, Any]] | None = None
    resumed_discards: list[str] | None = None
    source_ids = [definition["id"] for definition in definitions]
    if (
        isinstance(progress, dict)
        and progress.get("validatorVersion") == CONTENT_AUTHORITY_VERSION
        and progress.get("sourceDefinitionIds") == source_ids
        and isinstance(progress.get("completedDefinitionCount"), int)
        and isinstance(progress.get("keptDefinitions"), list)
        and isinstance(progress.get("discards"), list)
    ):
        completed_count = progress["completedDefinitionCount"]
        resumed_kept = copy.deepcopy(progress["keptDefinitions"])
        resumed_discards = list(map(str, progress["discards"]))

    def save_progress(
        completed_definition_count: int,
        kept_definitions: list[dict[str, Any]],
        current_discards: list[str],
    ) -> None:
        if progress_callback is None:
            return
        snapshot = copy.deepcopy(checkpoint)
        snapshot["deterministicValidationProgress"] = {
            "validatorVersion": CONTENT_AUTHORITY_VERSION,
            "sourceDefinitionIds": source_ids,
            "completedDefinitionCount": completed_definition_count,
            "keptDefinitions": copy.deepcopy(kept_definitions),
            "discards": list(current_discards),
        }
        progress_callback(snapshot)

    reviewed, discards = _run_deterministic_definition_validation(
        client,
        definitions,
        baseline_discards,
        equipment,
        repair_call,
        progress_callback=save_progress,
        completed_definition_count=completed_count,
        resumed_kept=resumed_kept,
        resumed_discards=resumed_discards,
    )
    _validate_final_definition_semantics(reviewed, equipment)
    payload = _library_payload(
        reviewed,
        equipment,
        [],
        discards,
        review_status="COMPLETE",
    )
    payload["contentAuthorityVersion"] = CONTENT_AUTHORITY_VERSION
    return payload


def _review_muscle_semantics_batch(
    client: Any,
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    caller: Callable[..., str | None],
) -> list[dict[str, Any]]:
    references = {f"DEFINITION_{index}": definition for index, definition in enumerate(definitions, 1)}
    review_input = [
        {
            "reference": reference,
            "name": definition["name"],
            "exerciseType": definition["exerciseType"],
            "equipment": _all_equipment_items(equipment).get(definition.get("equipmentId"), {}).get("name"),
            "accessories": [
                _all_equipment_items(equipment).get(item_id, {}).get("name", item_id)
                for item_id in definition.get("requiredAccessoryEquipmentIds", [])
            ],
            "currentMuscleGroups": definition.get("muscleGroups", []),
            "currentSecondaryMuscleGroups": definition.get("secondaryMuscleGroups", []),
        }
        for reference, definition in references.items()
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "Independently assign anatomical map regions for exercise definitions. Return JSON "
                "only as {\"reviews\":[...]}, exactly one review for every supplied reference. Each "
                "review contains exactly reference, muscleGroups, and secondaryMuscleGroups. Do not "
                "rubber-stamp or merely truncate the current arrays. muscleGroups contains only the "
                "prime movers that dynamically produce the defining action: normally one or two, "
                "and at most three only for a genuinely complex movement. secondaryMuscleGroups "
                "contains zero to three regions materially trained as assistants. Exclude regions "
                "used only for posture, bracing, balance, grip, or contact. Never include joints, "
                "hands, feet, or incidental stabilizers. Use only the supplied enum values."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"allowedMuscleGroups": sorted(MUSCLE_GROUPS), "definitions": review_input},
                ensure_ascii=False,
            ),
        },
    ]
    last_error: Exception | None = None
    for attempt in range(3):
        content = caller(client, messages, "", show_loading=False)
        try:
            payload = _json_object(content, "muscle semantic review")
            reviews = payload.get("reviews")
            if not isinstance(reviews, list) or len(reviews) != len(references):
                raise ValueError("muscle review must cover every definition exactly once")
            by_reference = {
                review.get("reference"): review for review in reviews if isinstance(review, dict)
            }
            if set(by_reference) != set(references):
                raise ValueError("muscle review returned unknown, duplicate, or missing references")
            reviewed: list[dict[str, Any]] = []
            for reference, definition in references.items():
                review = by_reference[reference]
                if set(review) != {"reference", "muscleGroups", "secondaryMuscleGroups"}:
                    raise ValueError(f"{reference} review has invalid fields")
                primary = review["muscleGroups"]
                secondary = review["secondaryMuscleGroups"]
                if not isinstance(primary, list) or not 1 <= len(primary) <= 3:
                    raise ValueError(f"{reference} needs one to three primary regions")
                if not isinstance(secondary, list) or len(secondary) > 3:
                    raise ValueError(f"{reference} needs zero to three secondary regions")
                if len(set(primary)) != len(primary) or len(set(secondary)) != len(secondary):
                    raise ValueError(f"{reference} contains duplicate muscle regions")
                if set(primary) & set(secondary):
                    raise ValueError(f"{reference} duplicates primary regions in secondary")
                unknown = (set(primary) | set(secondary)) - MUSCLE_GROUPS
                if unknown:
                    raise ValueError(f"{reference} used unknown muscle regions {sorted(unknown)}")
                invalid_primary = set(primary) & NON_MUSCLE_PRIMARY_GROUPS
                if invalid_primary:
                    raise ValueError(f"{reference} used non-muscle primary regions {sorted(invalid_primary)}")
                updated = copy.deepcopy(definition)
                updated["muscleGroups"] = primary
                updated["secondaryMuscleGroups"] = secondary
                reviewed.append(updated)
            return reviewed
        except (KeyError, TypeError, ValueError) as error:
            last_error = error
            messages.extend(
                [
                    {"role": "assistant", "content": content or ""},
                    {
                        "role": "user",
                        "content": f"Repair and return the complete response. Validation error: {error}",
                    },
                ]
            )
    raise ValueError(f"invalid muscle semantic review after 3 attempts: {last_error}")


def _review_muscle_semantics_resilient(
    client: Any,
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    caller: Callable[..., str | None],
) -> list[dict[str, Any]]:
    try:
        return _review_muscle_semantics_batch(client, definitions, equipment, caller)
    except Exception:
        if len(definitions) == 1:
            raise
        midpoint = len(definitions) // 2
        return [
            *_review_muscle_semantics_resilient(client, definitions[:midpoint], equipment, caller),
            *_review_muscle_semantics_resilient(client, definitions[midpoint:], equipment, caller),
        ]


def review_library_muscle_semantics(
    client: Any,
    checkpoint: dict[str, Any],
    *,
    review_call: Callable[..., str | None] = json_call_reasoner_only_with_loading,
    max_workers: int = 2,
) -> dict[str, Any]:
    definitions = checkpoint.get("exerciseDefinitions")
    equipments = checkpoint.get("equipments")
    accessories = checkpoint.get("accessoryEquipments")
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("Checkpoint contains no exerciseDefinitions")
    if not isinstance(equipments, list) or not isinstance(accessories, list):
        raise ValueError("Checkpoint has invalid equipment collections")
    equipment = {"equipments": equipments, "accessoryEquipments": accessories}
    batches = [definitions[index:index + 10] for index in range(0, len(definitions), 10)]
    reviewed_by_batch: dict[int, list[dict[str, Any]]] = {}
    print(
        f"Reviewing muscle semantics in {len(batches)} batch(es) with up to "
        f"{max(1, max_workers)} concurrent request(s).",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        future_to_index = {
            executor.submit(
                _review_muscle_semantics_resilient,
                client,
                batch,
                equipment,
                review_call,
            ): index
            for index, batch in enumerate(batches)
        }
        for completed, future in enumerate(as_completed(future_to_index), 1):
            reviewed_by_batch[future_to_index[future]] = future.result()
            print(f"Muscle semantic batches complete: {completed}/{len(batches)}", flush=True)
    reviewed = [
        definition
        for index in range(len(batches))
        for definition in reviewed_by_batch[index]
    ]
    _validate_final_definition_semantics(reviewed, equipment)
    return _library_payload(reviewed, equipment, [], [])


def _review_feasibility_batch(
    client: Any,
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    caller: Callable[..., str | None],
) -> tuple[list[dict[str, Any]], list[str]]:
    all_items = _all_equipment_items(equipment)
    references = {f"DEFINITION_{index}": definition for index, definition in enumerate(definitions, 1)}
    review_input = []
    for reference, definition in references.items():
        linked_ids = {
            item_id
            for item_id in [
                definition.get("equipmentId"),
                *definition.get("requiredAccessoryEquipmentIds", []),
            ]
            if item_id is not None
        }
        review_input.append(
            {
                "reference": reference,
                "name": definition["name"],
                "exerciseType": definition["exerciseType"],
                "declaredEquipment": [
                    all_items[item_id].get("name", item_id)
                    for item_id in linked_ids
                    if item_id in all_items
                ],
                "availableCapabilities": sorted(
                    _capabilities_for_equipment_ids(equipment, linked_ids)
                ),
            }
        )
    messages = [
        {
            "role": "system",
            "content": (
                "Judge whether each exercise is physically executable using only its declared "
                "equipment and available capabilities. Return JSON only as {\"reviews\":[...]}, "
                "exactly one review per reference. Each review contains exactly reference, "
                "decision, missingCapabilities, and reason. decision is KEEP or DISCARD. DISCARD "
                "only when a mandatory special physical feature is absent, and list every missing "
                "feature using only the supplied capability catalog. Treat supplied accessories "
                "as installed and usable for their ordinary purpose. Do not require ordinary floor "
                "space, room overhead, optional spotting, comfort, or programming conveniences. "
                "Require rack or handoff support when a loaded bar must begin or end at bench, back, "
                "or seated shoulder height and the named exercise does not include a clean or other "
                "self-setup. Require transition clearance for actual bar/ring muscle-ups. Require a "
                "second cable station or dual-handle supply when an unambiguously bilateral cable "
                "movement needs two independently opposed handles. KEEP whenever a normal safe "
                "self-setup is inherent in the named movement."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "capabilityCatalog": sorted(EQUIPMENT_CAPABILITY_CATALOG),
                    "definitions": review_input,
                },
                ensure_ascii=False,
            ),
        },
    ]
    last_error: Exception | None = None
    for _ in range(3):
        content = caller(client, messages, "", show_loading=False)
        try:
            payload = _json_object(content, "definition feasibility review")
            reviews = payload.get("reviews")
            if not isinstance(reviews, list) or len(reviews) != len(references):
                raise ValueError("feasibility review must cover every definition exactly once")
            by_reference = {
                review.get("reference"): review for review in reviews if isinstance(review, dict)
            }
            if set(by_reference) != set(references):
                raise ValueError("feasibility review returned unknown, duplicate, or missing references")
            kept: list[dict[str, Any]] = []
            discards: list[str] = []
            for reference, definition in references.items():
                review = by_reference[reference]
                if set(review) != {"reference", "decision", "missingCapabilities", "reason"}:
                    raise ValueError(f"{reference} feasibility review has invalid fields")
                decision = review["decision"]
                missing = review["missingCapabilities"]
                reason = review["reason"]
                if decision not in {"KEEP", "DISCARD"}:
                    raise ValueError(f"{reference} has invalid feasibility decision")
                if not isinstance(missing, list) or len(missing) != len(set(missing)):
                    raise ValueError(f"{reference} has invalid missingCapabilities")
                if set(missing) - EQUIPMENT_CAPABILITY_CATALOG:
                    raise ValueError(f"{reference} used unknown capabilities")
                if not isinstance(reason, str) or not reason.strip():
                    raise ValueError(f"{reference} needs a reason")
                if decision == "KEEP" and missing:
                    raise ValueError(f"{reference} cannot KEEP with missing capabilities")
                if decision == "DISCARD" and not missing:
                    raise ValueError(f"{reference} cannot DISCARD without a missing capability")
                if decision == "KEEP":
                    kept.append(copy.deepcopy(definition))
                else:
                    discards.append(
                        f"{definition['name']}: missing mandatory capabilities {missing}; {reason.strip()}"
                    )
            return kept, discards
        except (KeyError, TypeError, ValueError) as error:
            last_error = error
            messages.extend(
                [
                    {"role": "assistant", "content": content or ""},
                    {
                        "role": "user",
                        "content": f"Repair and return the complete response. Validation error: {error}",
                    },
                ]
            )
    raise ValueError(f"invalid feasibility review after 3 attempts: {last_error}")


def _review_feasibility_resilient(
    client: Any,
    definitions: list[dict[str, Any]],
    equipment: dict[str, Any],
    caller: Callable[..., str | None],
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        first_kept, first_discards = _review_feasibility_batch(
            client, definitions, equipment, caller
        )
        second_kept, second_discards = _review_feasibility_batch(
            client, definitions, equipment, caller
        )
        first_kept_ids = {definition["id"] for definition in first_kept}
        second_kept_ids = {definition["id"] for definition in second_kept}
        consensus_discard_ids = {
            definition["id"]
            for definition in definitions
            if definition["id"] not in first_kept_ids
            and definition["id"] not in second_kept_ids
        }
        kept = [
            copy.deepcopy(definition)
            for definition in definitions
            if definition["id"] not in consensus_discard_ids
        ]
        first_reasons = {
            reason.split(":", 1)[0]: reason for reason in first_discards
        }
        second_reasons = {
            reason.split(":", 1)[0]: reason for reason in second_discards
        }
        discards = []
        for definition in definitions:
            if definition["id"] not in consensus_discard_ids:
                continue
            name = definition["name"]
            reasons = [
                reason
                for reason in (first_reasons.get(name), second_reasons.get(name))
                if reason is not None
            ]
            discards.append(" | independently confirmed: ".join(reasons))
        return kept, discards
    except Exception:
        if len(definitions) == 1:
            raise
        midpoint = len(definitions) // 2
        left_kept, left_discards = _review_feasibility_resilient(
            client, definitions[:midpoint], equipment, caller
        )
        right_kept, right_discards = _review_feasibility_resilient(
            client, definitions[midpoint:], equipment, caller
        )
        return left_kept + right_kept, left_discards + right_discards


def review_library_feasibility(
    client: Any,
    checkpoint: dict[str, Any],
    *,
    review_call: Callable[..., str | None] = json_call_reasoner_only_with_loading,
    max_workers: int = 2,
) -> dict[str, Any]:
    definitions = checkpoint.get("exerciseDefinitions")
    equipments = checkpoint.get("equipments")
    accessories = checkpoint.get("accessoryEquipments")
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("Checkpoint contains no exerciseDefinitions")
    if not isinstance(equipments, list) or not isinstance(accessories, list):
        raise ValueError("Checkpoint has invalid equipment collections")
    equipment = {"equipments": equipments, "accessoryEquipments": accessories}
    batches = [definitions[index:index + 10] for index in range(0, len(definitions), 10)]
    results: dict[int, tuple[list[dict[str, Any]], list[str]]] = {}
    print(
        f"Reviewing physical feasibility by two-review consensus in {len(batches)} "
        f"batch(es) with up to {max(1, max_workers)} concurrent batch(es).",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        future_to_index = {
            executor.submit(
                _review_feasibility_resilient, client, batch, equipment, review_call
            ): index
            for index, batch in enumerate(batches)
        }
        for completed, future in enumerate(as_completed(future_to_index), 1):
            results[future_to_index[future]] = future.result()
            print(f"Feasibility batches complete: {completed}/{len(batches)}", flush=True)
    kept = [definition for index in range(len(batches)) for definition in results[index][0]]
    discards = [reason for index in range(len(batches)) for reason in results[index][1]]
    print(
        f"Physical feasibility kept {len(kept)} definition(s) and discarded "
        f"{len(definitions) - len(kept)} definition(s).",
        flush=True,
    )
    return _library_payload(kept, equipment, [], discards)


def _save_library_atomic(payload: dict[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def _parse_capability_suggestions(
    payload: str | dict[str, Any],
    equipment: dict[str, Any],
) -> list[dict[str, str]]:
    parsed = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(parsed, dict) or not isinstance(parsed.get("suggestions"), list):
        raise ValueError('Capability response must be an object containing a "suggestions" array')
    known_items = _all_equipment_items(equipment)
    suggestions: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, suggestion in enumerate(parsed["suggestions"]):
        if not isinstance(suggestion, dict) or set(suggestion) != {
            "equipmentId", "capability", "reason", "confidence"
        }:
            raise ValueError(f"Capability suggestion {index + 1} has invalid fields")
        equipment_id = suggestion.get("equipmentId")
        capability = suggestion.get("capability")
        reason = suggestion.get("reason")
        confidence = suggestion.get("confidence")
        if equipment_id not in known_items:
            raise ValueError(f"Capability suggestion has unknown equipmentId {equipment_id!r}")
        if not isinstance(capability, str) or not CAPABILITY_NAME_PATTERN.fullmatch(capability):
            raise ValueError(f"Capability {capability!r} must be UPPER_SNAKE_CASE")
        if capability.startswith("USE_EQUIPMENT"):
            raise ValueError("USE_EQUIPMENT capabilities are generated internally")
        if capability not in EQUIPMENT_CAPABILITY_CATALOG:
            raise ValueError(
                f"Capability {capability!r} is outside the supported capability catalog"
            )
        item = known_items[equipment_id]
        if capability in {"LOADABLE_PLATES", "SUPPORTS_PLATES"} and not isinstance(
            item.get("availablePlates"), list
        ):
            raise ValueError(
                f"Capability {capability!r} for {equipment_id!r} lacks availablePlates evidence"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"Capability {capability} requires a non-empty reason")
        if confidence not in CAPABILITY_CONFIDENCE_LEVELS:
            raise ValueError(f"Capability {capability} has invalid confidence {confidence!r}")
        key = (equipment_id, capability)
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(
            {
                "equipmentId": equipment_id,
                "capability": capability,
                "reason": reason.strip(),
                "confidence": confidence,
            }
        )
    return suggestions


def _add_confirmation_only_capability_questions(
    equipment: dict[str, Any],
    suggestions: list[dict[str, str]],
) -> list[dict[str, str]]:
    expanded = list(suggestions)
    seen = {(value["equipmentId"], value["capability"]) for value in expanded}
    for item_id, item in _all_equipment_items(equipment).items():
        proposed_for_item = {
            value["capability"] for value in expanded if value["equipmentId"] == item_id
        }
        questions = set()
        if item.get("type") == "PLATELOADEDCABLE":
            questions.update(
                PULLEY_POSITION_CAPABILITIES
                | CABLE_ATTACHMENT_CAPABILITIES
                | {"ROW_FOOT_BRACE", "THIGH_HOLD_DOWN"}
            )
        if "BENCH" in proposed_for_item:
            questions.update({"FLAT_BENCH", "ADJUSTABLE_BENCH", "INCLINE_BENCH", "DECLINE_BENCH"})
        if proposed_for_item.intersection({"GYMNASTIC_RINGS", "PULL_UP_BAR"}):
            questions.add("MUSCLE_UP_CLEARANCE")
        for capability in sorted(questions):
            key = (item_id, capability)
            if key in seen:
                continue
            seen.add(key)
            expanded.append(
                {
                    "equipmentId": item_id,
                    "capability": capability,
                    "reason": "This physical feature cannot be proven from the equipment file; confirm it only if present.",
                    "confidence": "LOW",
                }
            )
    return expanded


def _generate_capability_suggestions(
    client: OpenAI,
    equipment: dict[str, Any],
    call_json: Callable[..., str | None] = json_call_chat_max_with_loading,
) -> list[dict[str, str]]:
    primary_context, accessory_context = _equipment_context_lists(equipment)
    equipment_context = [
        {key: value for key, value in item.items() if key != "capabilities"}
        for item in [*primary_context, *accessory_context]
    ]
    messages = [
        {"role": "system", "content": CAPABILITY_GENERATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "allowedCapabilities": sorted(EQUIPMENT_CAPABILITY_CATALOG),
                    "equipment": equipment_context,
                },
                ensure_ascii=False,
            ),
        },
    ]
    last_error: Exception | None = None
    for attempt in range(1, 4):
        response = call_json(
            client,
            messages,
            f"Generating equipment capabilities (attempt {attempt}/3)",
        )
        if response is None:
            raise ValueError("Capability generation was cancelled")
        try:
            return _parse_capability_suggestions(response, equipment)
        except (ValueError, json.JSONDecodeError) as error:
            last_error = error
            messages.extend(
                [
                    {"role": "assistant", "content": response},
                    {
                        "role": "user",
                        "content": f"Repair the complete JSON response. Validation error: {error}",
                    },
                ]
            )
    raise ValueError(f"Could not generate valid equipment capabilities: {last_error}")


def _confirm_capability_suggestions(
    equipment: dict[str, Any],
    suggestions: list[dict[str, str]],
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> dict[str, dict[str, list[str]]]:
    items = _all_equipment_items(equipment)
    accepted: dict[str, list[str]] = {}
    if not suggestions:
        output_fn("The model suggested no additional capabilities.")
    for index, suggestion in enumerate(suggestions, start=1):
        item = items[suggestion["equipmentId"]]
        output_fn(
            f"\nCapability {index}/{len(suggestions)}: {item.get('name', item['id'])}\n"
            f"  {suggestion['capability']} [{suggestion['confidence']}]\n"
            f"  Reason: {suggestion['reason']}"
        )
        if input_fn("Accept this capability? [y/N]: ").strip().lower() in {"y", "yes"}:
            accepted.setdefault(suggestion["equipmentId"], []).append(suggestion["capability"])
    return {"capabilitiesByEquipmentId": accepted}


def _apply_capability_file(
    equipment: dict[str, Any],
    capability_file: str | None,
) -> dict[str, Any]:
    if not capability_file:
        return equipment
    path = Path(capability_file).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("capabilitiesByEquipmentId"), dict):
        capability_mapping = payload["capabilitiesByEquipmentId"]
    elif isinstance(payload, dict):
        capability_mapping = payload
    else:
        raise ValueError("Capability file must be an object keyed by equipment ID")
    merged = copy.deepcopy(equipment)
    items = _all_equipment_items(merged)
    unknown_ids = set(capability_mapping) - set(items)
    if unknown_ids:
        raise ValueError(f"Capability file contains unknown equipment IDs: {sorted(unknown_ids)}")
    for item_id, capabilities in capability_mapping.items():
        if (
            not isinstance(capabilities, list)
            or any(not isinstance(capability, str) or not capability.strip() for capability in capabilities)
        ):
            raise ValueError(f"Capabilities for {item_id} must be a non-empty-string array")
        existing = items[item_id].get("capabilities", [])
        if not isinstance(existing, list):
            raise ValueError(f"Existing capabilities for {item_id} must be an array")
        items[item_id]["capabilities"] = list(
            dict.fromkeys(
                [capability.strip() for capability in existing]
                + [capability.strip() for capability in capabilities]
            )
        )
    return merged


def _default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return Path(__file__).resolve().parents[1] / "exercise_libraries" / f"exercise_library_{timestamp}.json"


def _default_capabilities_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return (
        Path(__file__).resolve().parents[1]
        / "equipment_capabilities"
        / f"equipment_capabilities_{timestamp}.json"
    )


def _default_review_checkpoint_path() -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return (
        Path(__file__).resolve().parents[1]
        / "exercise_libraries"
        / "review_checkpoints"
        / f"exercise_library_review_{timestamp}.json"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise Library Generator")
    parser.add_argument("--equipment-file", required=True, help="Equipment JSON used by workout_generator.py")
    parser.add_argument(
        "--capabilities-file",
        help=(
            "Optional JSON object mapping equipment IDs to explicit capability strings "
            "(rack, bench positions, cable attachments, etc.)"
        ),
    )
    parser.add_argument(
        "--generate-capabilities",
        action="store_true",
        help="Ask the LLM for equipment capabilities and approve each suggestion interactively",
    )
    parser.add_argument(
        "--capabilities-output-file",
        help="Destination for approved generated capabilities (default: equipment_capabilities/<timestamp>.json)",
    )
    parser.add_argument("--output-file", help="Destination JSON path (default: exercise_libraries/<timestamp>.json)")
    parser.add_argument(
        "--review-checkpoint-file",
        help="Pre-review checkpoint path (default: exercise_libraries/review_checkpoints/<timestamp>.json)",
    )
    parser.add_argument("--request", default="", help="Optional inclusion/exclusion or training-scope guidance")
    parser.add_argument("--audit-passes", type=int, default=1, help="LLM missing-exercise audit passes (default: 1)")
    parser.add_argument("--max-workers", type=int, default=4, help="Concurrent definition emitters (default: 4)")
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=180.0,
        help="Maximum wait for one definition-emitter request (default: 180)",
    )
    parser.add_argument(
        "--inventory-timeout-seconds",
        type=float,
        default=900.0,
        help="Maximum wait for an inventory/audit reasoner request (default: 900)",
    )
    model_group = parser.add_mutually_exclusive_group()
    model_group.add_argument("--use-reasoner", action="store_true", help="Use reasoner for inventory and definitions")
    model_group.add_argument("--hybrid-fast", action="store_true", help="Use reasoner inventory and chat definition emitters (default)")
    args = parser.parse_args()

    if args.capabilities_file and args.generate_capabilities:
        parser.error("--capabilities-file and --generate-capabilities cannot be used together")
    if args.capabilities_output_file and not args.generate_capabilities:
        parser.error("--capabilities-output-file requires --generate-capabilities")

    try:
        equipment = _apply_capability_file(
            load_equipment_from_file(args.equipment_file),
            args.capabilities_file,
        )
        api_key = _resolve_api_key()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(f"Loaded {len(equipment['equipments'])} equipment item(s) and "
          f"{len(equipment['accessoryEquipments'])} accessory item(s).")
    explicit_capability_count = sum(
        len(item.get("capabilities", []))
        for item in _all_equipment_items(equipment).values()
        if isinstance(item.get("capabilities", []), list)
    )
    print(
        f"Loaded {explicit_capability_count} explicit equipment capability declaration(s)."
    )
    print("The reasoner will enumerate practical distinct exercises and audit for omissions.")
    confirmation = input(f"Type {EXACT_GENERATION_CONFIRMATION} to continue: ").strip()
    if confirmation != EXACT_GENERATION_CONFIRMATION:
        print("Generation cancelled: exact confirmation was not provided.")
        return

    if args.request_timeout_seconds <= 0:
        parser.error("--request-timeout-seconds must be greater than zero")
    if args.inventory_timeout_seconds <= 0:
        parser.error("--inventory-timeout-seconds must be greater than zero")
    definition_timeout = httpx.Timeout(args.request_timeout_seconds, connect=60.0)
    inventory_timeout = httpx.Timeout(args.inventory_timeout_seconds, connect=60.0)
    with httpx.Client(timeout=definition_timeout) as definition_http_client, httpx.Client(
        timeout=inventory_timeout
    ) as inventory_http_client:
        definition_client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            http_client=definition_http_client,
        )
        inventory_client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            http_client=inventory_http_client,
        )
        success, error_message = test_connection(definition_client, show_message=True)
        if not success:
            print(f"Connection test failed: {error_message}", file=sys.stderr)
            raise SystemExit(1)
        try:
            if args.generate_capabilities:
                suggestions = _add_confirmation_only_capability_questions(
                    equipment,
                    _generate_capability_suggestions(definition_client, equipment),
                )
                print(f"The model proposed {len(suggestions)} capability declaration(s).")
                capability_payload = _confirm_capability_suggestions(equipment, suggestions)
                capability_destination = (
                    Path(args.capabilities_output_file)
                    if args.capabilities_output_file
                    else _default_capabilities_output_path()
                )
                saved_capabilities = _save_library_atomic(
                    capability_payload,
                    capability_destination.expanduser().resolve(),
                )
                equipment = _apply_capability_file(equipment, str(saved_capabilities))
                accepted_count = sum(
                    len(values)
                    for values in capability_payload["capabilitiesByEquipmentId"].values()
                )
                print(f"Accepted {accepted_count} capability declaration(s).")
                print(f"Saved equipment capabilities to: {saved_capabilities}")
            checkpoint_destination = (
                Path(args.review_checkpoint_file)
                if args.review_checkpoint_file
                else _default_review_checkpoint_path()
            ).expanduser().resolve()
            checkpoint_announced = False

            def save_review_checkpoint(payload: dict[str, Any]) -> None:
                nonlocal checkpoint_announced
                saved_checkpoint = _save_library_atomic(payload, checkpoint_destination)
                if not checkpoint_announced:
                    print(f"Saved pre-review checkpoint to: {saved_checkpoint}")
                    checkpoint_announced = True

            library = generate_exercise_library(
                definition_client,
                equipment,
                args.request,
                inventory_client=inventory_client,
                use_reasoner_for_emitters=args.use_reasoner,
                audit_passes=args.audit_passes,
                max_workers=args.max_workers,
                semantic_review_call=json_call_chat_max_with_loading,
                global_consistency_call=json_call_reasoner_only_with_loading,
                instruction_entailment_call=json_call_chat_max_with_loading,
                review_checkpoint_callback=save_review_checkpoint,
            )
        except Exception as error:
            print(f"Generation failed: {error}", file=sys.stderr)
            raise SystemExit(1) from error

    canonical_library = copy.deepcopy(library)
    canonical_library.pop("generationFailures", None)
    canonical_library.pop("semanticDiscards", None)
    destination = Path(args.output_file) if args.output_file else _default_output_path()
    saved_path = _save_library_atomic(canonical_library, destination.resolve())
    print(f"Generated {len(canonical_library['exerciseDefinitions'])} exercise definition(s).")
    print(f"Saved schema-v2 exercise library to: {saved_path}")
    print("Use it with: python workout_generator.py --exercise-library-file <that-file>")


if __name__ == "__main__":
    main()
