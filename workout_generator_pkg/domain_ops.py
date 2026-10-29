"""Domain operations for workout generation."""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from itertools import zip_longest
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .constants import JSON_SCHEMA, MUSCLE_GROUP_FIXES
from .exercise_contracts import get_exercise_emission_profile
from .json_patching import build_allowed_patch_scope, collect_changed_json_paths, validate_changed_paths_scope

try:
    from jsonschema import validate
except Exception:
    validate = None


PLACEHOLDER_ID_PATTERN = (
    r"^(?:"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|(?:EQUIPMENT_|ACCESSORY_|EXERCISE_|SET_|WORKOUT_|COMPONENT_|REST_)[A-Za-z0-9_]+(?:_GLOBAL)?"
    r"|EXERCISE_WARMUP|SET_WARMUP"
    r")$"
)

CANONICAL_PLACEHOLDER_PATTERNS = {
    "EQUIPMENT": re.compile(r"^EQUIPMENT_\d+$"),
    "ACCESSORY": re.compile(r"^ACCESSORY_\d+$"),
    "EXERCISE": re.compile(r"^EXERCISE_\d+$"),
    "WORKOUT": re.compile(r"^WORKOUT_\d+$"),
    "SET": re.compile(r"^SET_\d+$"),
}


def format_exercise_library_catalog(definitions, provided_equipment):
    equipment_names = {
        item.get("id"): item.get("name", "")
        for item in (provided_equipment or {}).get("equipments", [])
    }
    rows = [[
        definition.get("id"), definition.get("name"), definition.get("exerciseType"),
        equipment_names.get(definition.get("equipmentId"), definition.get("equipmentId") or "none"),
        definition.get("bodyWeightPercentage"),
    ] for definition in definitions]
    return (
        "Exercise library compact selection catalog. Each row is "
        "[libraryDefinitionId,name,exerciseType,equipment,bodyWeightPercentage]:\n"
        + json.dumps(rows, separators=(",", ":")) + "\n"
    )


def superset_rest_map(workout_entry, group):
    """Prefer round rests; retain the legacy plan format for saved generations."""
    if "restSecondsByExercise" in group:
        return group["restSecondsByExercise"]
    rest_by_exercise = dict(zip(
        workout_entry.get("exerciseIds", []), workout_entry.get("restToNextSeconds") or [],
    ))
    return {exercise_id: rest_by_exercise[exercise_id] for exercise_id in group["exerciseIds"]}


def build_workout_structure(workout_entry):
    """Materialize ordered components directly from the validated plan."""
    exercise_ids = workout_entry.get("exerciseIds", [])
    rests = workout_entry.get("restToNextSeconds") or [0] * len(exercise_ids)
    if len(rests) != len(exercise_ids):
        raise ValueError("Workout transition rests must match its exercise order")
    groups = {group["exerciseIds"][0]: group for group in workout_entry.get("supersetGroups", []) or []}
    components = []
    index = 0
    while index < len(exercise_ids):
        group = groups.get(exercise_ids[index])
        if group:
            members = group["exerciseIds"]
            if exercise_ids[index:index + len(members)] != members:
                raise ValueError("Superset members must be contiguous in workout order")
            component = {
                "componentType": "Superset", "enabled": group.get("enabled", True),
                "exerciseIds": list(members), "restSecondsByExercise": copy.deepcopy(superset_rest_map(workout_entry, group)),
            }
            for field in ("timeCapSeconds", "roundDurationSeconds", "amrap"):
                if field in group:
                    component[field] = group[field]
            components.append(component)
            index += len(members)
            # Legacy plans store round recovery here, not a separate outer transition.
            rest = rests[index - 1] if "restSecondsByExercise" in group else 0
        else:
            components.append({"componentType": "Exercise", "exerciseId": exercise_ids[index], "enabled": True})
            rest = rests[index]
            index += 1
        if rest:
            components.append({"componentType": "Rest", "enabled": True, "timeInSeconds": rest})
    metadata = {
        "id": workout_entry["id"], "name": workout_entry["name"],
        "description": workout_entry.get("description", ""), "order": workout_entry.get("order", 0),
        "enabled": workout_entry.get("enabled", True), "usePolarDevice": workout_entry.get("usePolarDevice", False),
        "creationDate": date.today().isoformat(), "isActive": workout_entry.get("isActive", True),
        "timesCompletedInAWeek": workout_entry.get("timesCompletedInAWeek"), "type": workout_entry.get("type", 0),
        "workoutPlanId": workout_entry.get("workoutPlanId"),
    }
    return {"workoutMetadata": metadata, "workoutComponents": components}


def reviewable_workout_artifact(plan, guidance, workout_store=None, id_map=None):
    """Compare the user-visible execution fields, including exact emitted sets and order."""
    resource_ids = {item['id'] for key in ('equipments', 'accessoryEquipments') for item in plan.get(key, [])}
    reverse_ids = {value: key for key, value in (id_map or {}).items() if value not in resource_ids}
    def normalize(value):
        if isinstance(value, dict):
            return {reverse_ids.get(k, k): normalize(v) for k, v in value.items() if k != 'id'}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        return reverse_ids.get(value, value) if isinstance(value, str) else value
    def exercise_view(item):
        fields = ('name', 'enabled', 'exerciseType', 'equipmentId', 'requiredAccessoryEquipmentIds', 'bodyWeightPercentage', 'exerciseCategory',
            'notes', 'minReps', 'maxReps', 'generateWarmUpSets', 'requiresLoadCalibration',
            'progressionMode', 'intraSetRestInSeconds', 'runningPrescription', 'muscleGroups', 'secondaryMuscleGroups')
        view = {'type': 'Exercise', 'id': reverse_ids.get(item['id'], item['id']),
            **{key: normalize(item[key]) for key in fields if key in item}}
        set_fields = ('type', 'subCategory', 'reps', 'weight', 'additionalWeight', 'timeInSeconds',
            'timeInMillis', 'autoStart', 'autoStop', 'targetDistanceMeters', 'targetCalories')
        view['sets'] = [{key: value for key, value in target.items() if key in set_fields} for target in item['sets']]
        return view
    if workout_store is None:
        exercises = {item['id']: _materialize_exercise_definition(item) for item in plan['exercises']}
        structures = {day['id']: build_workout_structure(day) for day in plan['workouts']}
        workouts = assemble_placeholder_workout_store({}, {}, exercises, structures, plan)['workouts']
    else:
        workouts = workout_store['workouts']
    result = []
    for day in workouts:
        components = []
        for item in day['workoutComponents']:
            kind = item['type']
            if kind == 'Exercise':
                components.append({'type': kind, **exercise_view(item)})
            elif kind == 'Superset':
                components.append({'type': kind, 'enabled': item.get('enabled', True), **{key: normalize(item[key]) for key in (
                    'restSecondsByExercise', 'timeCapSeconds', 'roundDurationSeconds', 'amrap') if key in item},
                    'exercises': [exercise_view(e) for e in item['exercises']]})
            else:
                components.append({'type': kind, 'enabled': item.get('enabled', True), 'timeInSeconds': item['timeInSeconds']})
        result.append({'id': reverse_ids.get(day['id'], day['id']), 'name': day['name'], 'enabled': day.get('enabled', True),
            'description': day.get('description', ''), 'timesCompletedInAWeek': day.get('timesCompletedInAWeek', 1),
            'components': components})
    return {'workouts': result, 'programGuidance': guidance}


def _is_loadable_bodyweight_exercise(exercise: Dict[str, Any], accessory_subset=None) -> bool:
    """Detect BODY_WEIGHT exercises that are commonly externally loadable."""
    if not isinstance(exercise, dict):
        return False
    if exercise.get("exerciseType") != "BODY_WEIGHT":
        return False

    name = (exercise.get("name") or "").lower()
    if any(k in name for k in ("pull-up", "pull up", "chin-up", "chin up", "dip", "dips")):
        return True

    required_ids = set(exercise.get("requiredAccessoryEquipmentIds") or [])
    for acc in (accessory_subset or []):
        if not isinstance(acc, dict):
            continue
        if required_ids and acc.get("id") not in required_ids:
            continue
        acc_name = (acc.get("name") or "").lower()
        if any(k in acc_name for k in ("pull-up", "pull up", "ring", "rings", "dip")):
            return True
    return False


def infer_bodyweight_progression_equipment_id(
    exercise: Dict[str, Any],
    equipment_candidates=None,
    accessory_subset=None,
) -> Optional[str]:
    """
    Infer progression equipment for loadable BODY_WEIGHT exercises.

    Returns:
        equipment_id when a clear appropriate option exists, otherwise None.
    """
    if not isinstance(exercise, dict):
        return None
    if exercise.get("exerciseType") != "BODY_WEIGHT":
        return None
    if exercise.get("equipmentId"):
        return None
    if not _is_loadable_bodyweight_exercise(exercise, accessory_subset=accessory_subset):
        return None

    equipment_candidates = [
        eq for eq in (equipment_candidates or [])
        if isinstance(eq, dict) and eq.get("id")
    ]
    if not equipment_candidates:
        return None

    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for eq in equipment_candidates:
        eq_type = (eq.get("type") or "").upper()
        by_type.setdefault(eq_type, []).append(eq)

    # Clear, preferred progression option.
    weight_vests = by_type.get("WEIGHTVEST", [])
    if len(weight_vests) == 1:
        return weight_vests[0].get("id")

    # No appropriate progression equipment found: leave unassigned.
    return None


def validate_exercise_type_consistency(exercise):
    """
    Validate that exerciseType matches the set types in the sets array.
    
    Args:
        exercise: Exercise dictionary
        
    Returns:
        tuple: (is_valid, error_message)
    """
    exercise_type = exercise.get("exerciseType")
    sets = exercise.get("sets", [])
    
    if not exercise_type or not sets:
        return True, None
    
    # Expected set types for each exercise type
    expected_set_types = {
        "WEIGHT": ["WeightSet"],
        "BODY_WEIGHT": ["BodyWeightSet"],
        "COUNTUP": ["EnduranceSet"],
        "COUNTDOWN": ["TimedDurationSet"]
    }
    
    if exercise_type not in expected_set_types:
        return True, None  # Unknown exercise type, skip validation
    
    allowed_set_types = set(expected_set_types[exercise_type] + ["RestSet"])
    
    for set_item in sets:
        set_type = set_item.get("type")
        if set_type not in allowed_set_types:
            return False, f"Exercise '{exercise.get('name', 'Unknown')}' has exerciseType '{exercise_type}' but contains set type '{set_type}'. Expected only {expected_set_types[exercise_type]} (RestSet allowed between sets)."
    
    return True, None


def validate_reps_for_exercise_type(exercise):
    """
    Validate that minReps and maxReps are correct for the exercise type.
    
    Args:
        exercise: Exercise dictionary
        
    Returns:
        tuple: (is_valid, error_message)
    """
    exercise_type = exercise.get("exerciseType")
    min_reps = exercise.get("minReps", 0)
    max_reps = exercise.get("maxReps", 0)
    
    if not exercise_type:
        return True, None
    
    if exercise_type in ["WEIGHT", "BODY_WEIGHT"]:
        if min_reps is None or max_reps is None or min_reps <= 0 or max_reps <= 0:
            return False, f"Exercise '{exercise.get('name', 'Unknown')}' has exerciseType '{exercise_type}' but minReps={min_reps}, maxReps={max_reps}. WEIGHT/BODY_WEIGHT exercises must have minReps > 0 and maxReps > 0."
        if min_reps > max_reps:
            return False, f"Exercise '{exercise.get('name', 'Unknown')}' has minReps={min_reps} > maxReps={max_reps}. minReps must be <= maxReps."
    
    return True, None


def validate_muscle_groups(exercise):
    """
    Validate that exercise has at least one muscle group and all muscle group names are valid enum values.
    
    Args:
        exercise: Exercise dictionary
        
    Returns:
        tuple: (is_valid, error_message)
    """
    muscle_groups = exercise.get("muscleGroups", [])
    
    if not muscle_groups or len(muscle_groups) == 0:
        if exercise.get("id") == "EXERCISE_WARMUP":
            return True, None
        return False, f"Exercise '{exercise.get('name', 'Unknown')}' has empty muscleGroups array. Every non-warm-up exercise must have at least one primary muscle group."
    
    # Get valid enum values from schema
    valid_muscle_groups = set(JSON_SCHEMA["$defs"]["MuscleGroup"]["enum"])
    
    # Check for invalid enum values
    invalid_groups = []
    for mg in muscle_groups:
        if not isinstance(mg, str) or mg not in valid_muscle_groups:
            invalid_groups.append(str(mg))
    
    if invalid_groups:
        return False, f"Exercise '{exercise.get('name', 'Unknown')}' has invalid muscle group values: {', '.join(invalid_groups)}. Valid values are: {', '.join(sorted(valid_muscle_groups))}"
    
    # Also validate secondaryMuscleGroups if present
    secondary_muscle_groups = exercise.get("secondaryMuscleGroups", [])
    if secondary_muscle_groups:
        invalid_secondary = []
        for mg in secondary_muscle_groups:
            if not isinstance(mg, str) or mg not in valid_muscle_groups:
                invalid_secondary.append(str(mg))
        
        if invalid_secondary:
            return False, f"Exercise '{exercise.get('name', 'Unknown')}' has invalid secondaryMuscleGroups values: {', '.join(invalid_secondary)}. Valid values are: {', '.join(sorted(valid_muscle_groups))}"
    
    return True, None


def validate_equipment_references(exercise, equipment_ids, accessory_ids=None):
    """
    Validate that equipmentId and requiredAccessoryEquipmentIds references exist.
    
    Args:
        exercise: Exercise dictionary
        equipment_ids: Set of valid equipment IDs
        accessory_ids: Optional set of valid accessory equipment IDs
    
    Returns:
        tuple: (is_valid, error_message)
    """
    # Validate equipmentId
    equipment_id = exercise.get("equipmentId")
    
    if equipment_id is not None:
        if equipment_id not in equipment_ids:
            available = ", ".join(sorted(equipment_ids)) if equipment_ids else "none"
            return False, (
                f"Exercise '{exercise.get('name', 'Unknown')}' references equipmentId '{equipment_id}' "
                f"which does not exist in the equipments array. "
                f"Available equipment IDs: {available}"
            )
    
    # Validate requiredAccessoryEquipmentIds
    required_accessory_ids = exercise.get("requiredAccessoryEquipmentIds", [])
    if required_accessory_ids:
        if accessory_ids is None:
            accessory_ids = set()
        
        invalid_accessories = [acc_id for acc_id in required_accessory_ids if acc_id not in accessory_ids]
        if invalid_accessories:
            available = ", ".join(sorted(accessory_ids)) if accessory_ids else "none"
            return False, (
                f"Exercise '{exercise.get('name', 'Unknown')}' references requiredAccessoryEquipmentIds "
                f"{invalid_accessories} which do not exist in the accessoryEquipments array. "
                f"Available accessory IDs: {available}"
            )
    
    return True, None


def validate_equipment_exercise_type_compatibility(exercise, equipment_dict):
    """Validate the same primary-equipment compatibility enforced by the apps."""
    equipment_id = exercise.get("equipmentId")
    if equipment_id is None:
        return True, None

    equipment = equipment_dict.get(equipment_id) if isinstance(equipment_dict, dict) else None
    if not equipment:
        return True, None  # Missing references are reported separately.

    exercise_type = exercise.get("exerciseType")
    equipment_type = str(equipment.get("type", "")).upper()
    if equipment_type == "CARDIO_MACHINE":
        compatible = exercise_type in {"COUNTUP", "COUNTDOWN"}
    elif equipment_type == "ACCESSORY":
        compatible = False
    else:
        compatible = exercise_type in {"WEIGHT", "BODY_WEIGHT", "COUNTUP", "COUNTDOWN"}
    if compatible:
        return True, None

    return False, (
        f"Exercise '{exercise.get('name', 'Unknown')}' cannot use equipmentId "
        f"'{equipment_id}' of type '{equipment_type}' with exerciseType '{exercise_type}'."
    )


def _is_calibration_placeholder_load(exercise, set_item):
    if set_item.get("subCategory") == "CalibrationPendingSet":
        return True
    if not exercise.get("requiresLoadCalibration"):
        return False

    exercise_type = exercise.get("exerciseType")
    set_type = set_item.get("type")
    return (
        (exercise_type == "WEIGHT" and set_type == "WeightSet" and set_item.get("weight") == 0)
        or
        (exercise_type == "BODY_WEIGHT" and set_type == "BodyWeightSet" and set_item.get("additionalWeight") == 0)
    )


def validate_equipment_weight_combinations(exercise, equipment_dict):
    """
    Validate that WeightSet weights and BodyWeightSet additionalWeight values
    match valid equipment combinations.
    
    Args:
        exercise: Exercise dictionary
        equipment_dict: Dict mapping equipment_id -> equipment dict, or single equipment dict
    
    Returns:
        tuple: (is_valid, error_message, invalid_weights) where:
            - is_valid: bool
            - error_message: str or None
            - invalid_weights: list of (set_index, weight_value, set_type) tuples
    """
    equipment_id = exercise.get("equipmentId")
    exercise_type = exercise.get("exerciseType")
    
    # Skip validation if no equipment or not applicable exercise types
    if equipment_id is None:
        return True, None, []
    
    if exercise_type not in ["WEIGHT", "BODY_WEIGHT", "COUNTUP", "COUNTDOWN"]:
        return True, None, []
    
    # Get equipment
    if isinstance(equipment_dict, dict) and "type" in equipment_dict:
        # Single equipment dict
        equipment = equipment_dict
    elif isinstance(equipment_dict, dict):
        # Dict mapping equipment_id -> equipment
        equipment = equipment_dict.get(equipment_id)
    else:
        return True, None, []
    
    if not equipment:
        return True, None, []  # Equipment not found, skip validation (handled by reference validation)
    
    # Calculate valid selectable weights for this exact exercise/equipment pairing.
    valid_combinations = get_selectable_weights_for_exercise(exercise_type, equipment)

    if not valid_combinations:
        # No valid combinations (handle gracefully)
        return True, None, []

    eq_type = str(equipment.get("type", "")).upper()

    # Epsilon for floating point comparison
    EPSILON = 0.01
    
    invalid_weights = []
    sets = exercise.get("sets", [])
    
    for set_index, set_item in enumerate(sets):
        set_type = set_item.get("type")
        if _is_calibration_placeholder_load(exercise, set_item):
            continue
        
        if exercise_type == "WEIGHT" and set_type == "WeightSet":
            weight = set_item.get("weight", 0.0)
            # Check if weight matches any valid combination
            is_valid = any(abs(weight - valid_weight) < EPSILON for valid_weight in valid_combinations)
            if not is_valid:
                invalid_weights.append((set_index, weight, "WeightSet"))
        
        elif exercise_type == "BODY_WEIGHT" and set_type == "BodyWeightSet":
            additional_weight = set_item.get("additionalWeight", 0.0)
            # Check if additionalWeight matches any valid combination
            is_valid = any(abs(additional_weight - valid_weight) < EPSILON for valid_weight in valid_combinations)
            if not is_valid:
                invalid_weights.append((set_index, additional_weight, "BodyWeightSet"))

        elif exercise_type in {"COUNTUP", "COUNTDOWN"} and set_type in {"EnduranceSet", "TimedDurationSet"}:
            target_weight = set_item.get("targetWeight")
            if target_weight is None:
                continue
            is_valid = any(abs(target_weight - valid_weight) < EPSILON for valid_weight in valid_combinations)
            if not is_valid:
                invalid_weights.append((set_index, target_weight, set_type))
    
    if invalid_weights:
        # Build error message
        exercise_name = exercise.get("name", "Unknown")
        equipment_name = equipment.get("name", "Unknown")
        invalid_details = []
        sorted_valid = sorted(valid_combinations)

        def nearest_valid_weight(value):
            return min(sorted_valid, key=lambda valid_weight: abs(valid_weight - value))

        for set_idx, weight_val, set_type_name in invalid_weights:
            # Coach loads for pair-implement equipment name ONE implement; point
            # the repair at the doubled pair total instead of the nearest total.
            doubled = pair_implement_total_for(eq_type, weight_val, sorted_valid)
            if doubled is not None:
                invalid_details.append(
                    f"Set {set_idx} ({set_type_name}): {weight_val}kg is a per-implement weight; "
                    f"pair loads are PER-PAIR TOTALS - use {doubled}kg "
                    f"(the app displays it as '{_format_weight_value_for_prompt(weight_val)} x 2')"
                )
                continue
            nearest = nearest_valid_weight(weight_val)
            invalid_details.append(
                f"Set {set_idx} ({set_type_name}): {weight_val}kg; nearest selectable weight: {nearest}kg"
            )
        
        # Get sample valid weights for context
        sample_valid = sorted_valid[:5]  # Show first 5 valid weights
        valid_str = ", ".join(f"{w}kg" for w in sample_valid)
        if len(sorted_valid) > 5:
            valid_str += f", ... (total {len(sorted_valid)} valid combinations)"
        
        error_msg = (
            f"Exercise '{exercise_name}' with equipment '{equipment_name}' has invalid weights: "
            f"{'; '.join(invalid_details)}. "
            f"Valid weight combinations: {valid_str}"
        )
        return False, error_msg, invalid_weights
    
    return True, None, []


def fix_equipment_weights(exercise, equipment_dict):
    """
    Fix invalid weights in WeightSet and BodyWeightSet to nearest valid equipment combination.
    
    Args:
        exercise: Exercise dictionary (modified in place)
        equipment_dict: Dict mapping equipment_id -> equipment dict, or single equipment dict
    
    Returns:
        list: List of fix descriptions (strings) for logging
    """
    equipment_id = exercise.get("equipmentId")
    exercise_type = exercise.get("exerciseType")
    
    if equipment_id is None or exercise_type not in ["WEIGHT", "BODY_WEIGHT", "COUNTUP", "COUNTDOWN"]:
        return []
    
    # Get equipment
    if isinstance(equipment_dict, dict) and "type" in equipment_dict:
        equipment = equipment_dict
    elif isinstance(equipment_dict, dict):
        equipment = equipment_dict.get(equipment_id)
    else:
        return []
    
    if not equipment:
        return []
    
    # Calculate valid selectable weights for this exact exercise/equipment pairing.
    valid_combinations = get_selectable_weights_for_exercise(exercise_type, equipment)
    if not valid_combinations:
        return []

    eq_type = str(equipment.get("type", "")).upper()
    EPSILON = 0.01
    fixes_applied = []
    sets = exercise.get("sets", [])

    def find_closest_valid_weight(invalid_weight):
        """Find the closest valid weight combination."""
        closest = None
        min_diff = float('inf')
        for valid_weight in valid_combinations:
            diff = abs(invalid_weight - valid_weight)
            if diff < min_diff:
                min_diff = diff
                closest = valid_weight
        return closest

    def repair_weight(weight_val):
        # A per-implement weight on pair-implement equipment repairs to the
        # doubled pair total, never to the nearest unrelated total.
        doubled = pair_implement_total_for(eq_type, weight_val, valid_combinations)
        if doubled is not None:
            return doubled
        return find_closest_valid_weight(weight_val)

    for set_index, set_item in enumerate(sets):
        set_type = set_item.get("type")
        if _is_calibration_placeholder_load(exercise, set_item):
            continue
        
        if exercise_type == "WEIGHT" and set_type == "WeightSet":
            weight = set_item.get("weight", 0.0)
            # Check if weight is valid
            is_valid = any(abs(weight - valid_weight) < EPSILON for valid_weight in valid_combinations)
            if not is_valid:
                closest_valid = repair_weight(weight)
                if closest_valid is not None:
                    set_item["weight"] = closest_valid
                    exercise_name = exercise.get("name", "Unknown")
                    fixes_applied.append(
                        f"Exercise '{exercise_name}' Set {set_index}: Fixed weight from {weight}kg to {closest_valid}kg"
                    )

        elif exercise_type == "BODY_WEIGHT" and set_type == "BodyWeightSet":
            additional_weight = set_item.get("additionalWeight", 0.0)
            # Check if additionalWeight is valid
            is_valid = any(abs(additional_weight - valid_weight) < EPSILON for valid_weight in valid_combinations)
            if not is_valid:
                closest_valid = repair_weight(additional_weight)
                if closest_valid is not None:
                    set_item["additionalWeight"] = closest_valid
                    exercise_name = exercise.get("name", "Unknown")
                    fixes_applied.append(
                        f"Exercise '{exercise_name}' Set {set_index}: Fixed additionalWeight from {additional_weight}kg to {closest_valid}kg"
                    )

        elif exercise_type in {"COUNTUP", "COUNTDOWN"} and set_type in {"EnduranceSet", "TimedDurationSet"}:
            target_weight = set_item.get("targetWeight")
            if target_weight is None:
                continue
            is_valid = any(abs(target_weight - valid_weight) < EPSILON for valid_weight in valid_combinations)
            if not is_valid:
                closest_valid = repair_weight(target_weight)
                if closest_valid is not None:
                    set_item["targetWeight"] = closest_valid
                    exercise_name = exercise.get("name", "Unknown")
                    fixes_applied.append(
                        f"Exercise '{exercise_name}' Set {set_index}: Fixed targetWeight from {target_weight}kg to {closest_valid}kg"
                    )
    
    return fixes_applied


def _has_complete_explicit_work_set_loads(exercise):
    """Return True when every work set for a load-based exercise has an explicit load value."""
    if not isinstance(exercise, dict):
        return False

    exercise_type = exercise.get("exerciseType")
    if exercise_type == "WEIGHT":
        work_sets = [
            set_item for set_item in (exercise.get("sets") or [])
            if isinstance(set_item, dict) and set_item.get("type") == "WeightSet"
        ]
        return bool(work_sets) and all(isinstance(set_item.get("weight"), (int, float)) for set_item in work_sets)

    if exercise_type == "BODY_WEIGHT" and exercise.get("equipmentId") is not None:
        work_sets = [
            set_item for set_item in (exercise.get("sets") or [])
            if isinstance(set_item, dict) and set_item.get("type") == "BodyWeightSet"
        ]
        return bool(work_sets) and all(
            isinstance(set_item.get("additionalWeight"), (int, float)) for set_item in work_sets
        )

    return False


def apply_requires_load_calibration_policy(exercise, allow_educated_load_guesses=True):
    """Set requiresLoadCalibration deterministically from generator policy and exercise data."""
    if not isinstance(exercise, dict):
        return exercise

    exercise_type = exercise.get("exerciseType")
    equipment_id = exercise.get("equipmentId")

    if allow_educated_load_guesses:
        if exercise_type == "WEIGHT" or (exercise_type == "BODY_WEIGHT" and equipment_id is not None):
            exercise["requiresLoadCalibration"] = (
                exercise.get("requiresLoadCalibration") is not False
                or not _has_complete_explicit_work_set_loads(exercise)
            )
        else:
            exercise["requiresLoadCalibration"] = False
        return exercise

    if exercise_type == "WEIGHT" or (exercise_type == "BODY_WEIGHT" and equipment_id is not None):
        exercise["requiresLoadCalibration"] = True
    else:
        exercise["requiresLoadCalibration"] = False

    return exercise


def _is_positive_percentage_semantics(value: Any) -> bool:
    return isinstance(value, (int, float)) and value > 1.0


def validate_exercise_type_profile(
    exercise: Dict[str, Any],
    plan_entry: Optional[Dict[str, Any]] = None,
    require_full_shape: bool = False,
) -> List[str]:
    if not isinstance(exercise, dict):
        return ["Exercise definition must be a JSON object."]

    exercise_type = exercise.get("exerciseType")
    if not isinstance(exercise_type, str):
        return ["Exercise definition is missing exerciseType."]

    try:
        profile = get_exercise_emission_profile(exercise_type)
    except ValueError as exc:
        return [str(exc)]

    errors: List[str] = []
    exercise_name = exercise.get("name", "Unknown")

    if require_full_shape:
        for field in profile["required_top_level_fields"]:
            if field not in exercise:
                errors.append(
                    f"Exercise '{exercise_name}' is missing required top-level field '{field}' for {exercise_type}."
                )

    for field in profile["forbidden_top_level_fields"]:
        if field in exercise:
            errors.append(
                f"Exercise '{exercise_name}' must not include top-level field '{field}' for {exercise_type}."
            )

    if exercise_type == "BODY_WEIGHT":
        if not _is_positive_percentage_semantics(exercise.get("bodyWeightPercentage")):
            errors.append(
                f"Exercise '{exercise_name}' must include a positive numeric bodyWeightPercentage in percentage form for BODY_WEIGHT exercises."
            )
    elif exercise.get("bodyWeightPercentage") is not None:
        errors.append(
            f"Exercise '{exercise_name}' must set bodyWeightPercentage to null for non-BODY_WEIGHT exercises."
        )

    if exercise_type == "COUNTDOWN" and exercise.get("showCountDownTimer") is not True:
        errors.append(
            f"Exercise '{exercise_name}' must set showCountDownTimer=true for COUNTDOWN exercises."
        )

    if exercise_type in ("COUNTDOWN", "COUNTUP", "RUNNING"):
        if "minReps" in exercise or "maxReps" in exercise:
            errors.append(
                f"Exercise '{exercise_name}' must not emit minReps or maxReps for timed exercises."
            )
    elif require_full_shape:
        for rep_field in ("minReps", "maxReps"):
            if rep_field not in exercise:
                errors.append(
                    f"Exercise '{exercise_name}' is missing required top-level field '{rep_field}' for {exercise_type}."
                )

    allowed_work_set_type = profile["allowed_work_set_type"]
    sets = exercise.get("sets")
    if not isinstance(sets, list) or not sets:
        errors.append(f"Exercise '{exercise_name}' must include a non-empty sets array.")
        return errors

    work_set_count = 0
    rest_values: List[int] = []

    for idx, set_item in enumerate(sets):
        if not isinstance(set_item, dict):
            errors.append(f"Exercise '{exercise_name}' sets[{idx}] must be an object.")
            continue
        set_type = set_item.get("type")
        if set_type == allowed_work_set_type:
            work_set_count += 1
            if require_full_shape:
                for field in profile["required_set_level_fields"]:
                    if field not in set_item:
                        errors.append(
                            f"Exercise '{exercise_name}' {allowed_work_set_type} at sets[{idx}] is missing required field '{field}'."
                        )
            for field in profile["forbidden_set_level_fields"]:
                if field in set_item:
                    errors.append(
                        f"Exercise '{exercise_name}' {allowed_work_set_type} at sets[{idx}] must not include field '{field}'."
                    )
        elif set_type == "RestSet":
            if not profile["allowed_rest_set"]:
                errors.append(
                    f"Exercise '{exercise_name}' must not emit RestSet entries for {exercise_type} exercises."
                )
            if require_full_shape:
                for field in ("id", "type", "timeInSeconds", "subCategory"):
                    if field not in set_item:
                        errors.append(
                            f"Exercise '{exercise_name}' RestSet at sets[{idx}] is missing required field '{field}'."
                        )
            for field in ("reps", "weight", "additionalWeight", "timeInMillis", "autoStart", "autoStop"):
                if field in set_item:
                    errors.append(
                        f"Exercise '{exercise_name}' RestSet at sets[{idx}] must not include field '{field}'."
                    )
            time_in_seconds = set_item.get("timeInSeconds")
            if isinstance(time_in_seconds, int):
                rest_values.append(time_in_seconds)
            prev_type = sets[idx - 1].get("type") if idx > 0 and isinstance(sets[idx - 1], dict) else None
            next_type = sets[idx + 1].get("type") if idx + 1 < len(sets) and isinstance(sets[idx + 1], dict) else None
            if prev_type != allowed_work_set_type or next_type != allowed_work_set_type:
                errors.append(
                    f"Exercise '{exercise_name}' RestSet at sets[{idx}] must appear only between adjacent {allowed_work_set_type} work sets."
                )
        else:
            errors.append(
                f"Exercise '{exercise_name}' has exerciseType '{exercise_type}' but contains set type '{set_type}'. Expected only {allowed_work_set_type} and optional RestSet between work sets."
            )

    if work_set_count == 0:
        errors.append(
            f"Exercise '{exercise_name}' must include at least one {allowed_work_set_type} work set."
        )

    if plan_entry:
        expected_work_sets = plan_entry.get("numWorkSets")
        if isinstance(expected_work_sets, int) and expected_work_sets >= 0 and work_set_count != expected_work_sets:
            errors.append(
                f"Exercise '{exercise_name}' must emit exactly {expected_work_sets} work sets, got {work_set_count}."
            )

        expected_rest_between = plan_entry.get("restBetweenSetsSeconds")
        if isinstance(expected_rest_between, int) and work_set_count > 1:
            expected_rest_count = work_set_count - 1
            if len(rest_values) != expected_rest_count:
                errors.append(
                    f"Exercise '{exercise_name}' must emit exactly {expected_rest_count} RestSet entries between work sets when restBetweenSetsSeconds={expected_rest_between}."
                )
            elif any(rest_value != expected_rest_between for rest_value in rest_values):
                errors.append(
                    f"Exercise '{exercise_name}' must set every RestSet timeInSeconds to {expected_rest_between}, got {rest_values}."
                )

    return errors


def finalize_and_validate_exercise_definition(
    exercise_item,
    plan_entry=None,
    equipment_subset=None,
    accessory_subset=None,
    all_equipment_candidates=None,
    allow_educated_load_guesses=True,
):
    """
    Finalize one emitted exercise and validate it before adding it to exercise_definitions.
    """
    if not isinstance(exercise_item, dict):
        raise ValueError("Exercise definition must be a JSON object")

    normalized_list = fix_exercise_errors(
        [copy.deepcopy(exercise_item)],
        allow_educated_load_guesses=allow_educated_load_guesses,
    )
    exercise = normalized_list[0] if normalized_list else copy.deepcopy(exercise_item)

    if "sets" in exercise:
        exercise["sets"] = fix_set_errors(exercise["sets"])

    equipment_subset = equipment_subset or []
    accessory_subset = accessory_subset or []
    all_equipment_candidates = all_equipment_candidates or []

    merged_equipment = []
    seen_eq_ids = set()
    for eq in list(equipment_subset) + list(all_equipment_candidates):
        if not isinstance(eq, dict):
            continue
        eq_id = eq.get("id")
        if not eq_id or eq_id in seen_eq_ids:
            continue
        seen_eq_ids.add(eq_id)
        merged_equipment.append(eq)

    inferred_equipment_id = infer_bodyweight_progression_equipment_id(
        exercise,
        equipment_candidates=merged_equipment,
        accessory_subset=accessory_subset,
    )
    plan_explicitly_owns_equipment_id = isinstance(plan_entry, dict) and "equipmentId" in plan_entry
    if inferred_equipment_id and not exercise.get("equipmentId") and not plan_explicitly_owns_equipment_id:
        exercise["equipmentId"] = inferred_equipment_id

    sync_plan_owned_exercise_fields(exercise, plan_entry)
    # A history-derived plan flag must survive even when the plan includes a provisional load.
    load_field = "additionalWeight" if exercise.get("exerciseType") == "BODY_WEIGHT" else "weight"
    targets = (plan_entry or {}).get("targetSetPrescriptions") or []
    exercise["requiresLoadCalibration"] = (
        isinstance(plan_entry, dict) and plan_entry.get("requiresLoadCalibration") is True
    ) or not (
        targets and len(targets) == len([s for s in exercise.get("sets", []) if s.get("type") != "RestSet"])
        and all(isinstance(t.get(load_field), (int, float)) and not isinstance(t.get(load_field), bool) for t in targets)
    )
    apply_requires_load_calibration_policy(
        exercise,
        allow_educated_load_guesses=allow_educated_load_guesses,
    )

    equipment_ids = {eq.get("id") for eq in merged_equipment if eq.get("id")}
    accessory_ids = {acc.get("id") for acc in accessory_subset if isinstance(acc, dict) and acc.get("id")}
    equipment_by_id = {eq.get("id"): eq for eq in merged_equipment if eq.get("id")}

    validation_errors = validate_exercise_type_profile(
        exercise,
        plan_entry=plan_entry,
        require_full_shape=True,
    )

    checks = [
        validate_exercise_type_consistency(exercise),
        validate_reps_for_exercise_type(exercise),
        validate_muscle_groups(exercise),
        validate_equipment_references(exercise, equipment_ids, accessory_ids),
        validate_equipment_exercise_type_compatibility(exercise, equipment_by_id),
    ]
    for is_valid, error in checks:
        if not is_valid and error:
            validation_errors.append(error)

    if not validation_errors and allow_educated_load_guesses and not (plan_entry or {}).get("targetSetPrescriptions"):
        fix_equipment_weights(exercise, equipment_by_id)
    is_valid_weight_combo, weight_combo_error, _ = validate_equipment_weight_combinations(exercise, equipment_by_id)
    if not is_valid_weight_combo and weight_combo_error:
        validation_errors.append(weight_combo_error)

    if validation_errors:
        exercise_name = exercise.get("name", "Unknown")
        raise ValueError(
            f"Exercise '{exercise_name}' failed per-exercise validation: " + " | ".join(validation_errors)
        )

    return exercise


def generate_recursive_valid_subsets(available_weights, is_combination_valid=None, max_extra_per_point=None):
    """
    Generate all valid subsets of available weights using recursive combination.
    Matches Kotlin generateRecursiveValidSubsets logic.
    
    Args:
        available_weights: List of weight dicts (plates or base weights)
        is_combination_valid: Optional function to check if combination is valid (e.g., thickness constraint)
        max_extra_per_point: Optional max count for extra weights per loading point
    
    Returns:
        list: List of tuples, each tuple is a valid combination of weight dicts (deduplicated)
    """
    seen_combinations = set()  # Store hashable representations for deduplication
    combinations = []          # Store actual dict combinations
    
    def dict_to_hashable(weight_dict):
        """Convert a weight dict to a hashable tuple representation."""
        return (weight_dict.get("weight", 0), weight_dict.get("thickness", 0))
    
    def combine(weights, combination):
        """Recursive function to generate combinations."""
        # Add non-empty valid combinations
        if combination and (is_combination_valid is None or is_combination_valid(combination)):
            # Check max_extra_per_point constraint if provided
            if max_extra_per_point is None or len(combination) <= max_extra_per_point:
                # Create hashable representation: tuple of (weight, thickness) tuples
                sorted_combo = sorted(combination, key=lambda x: (x.get("weight", 0), x.get("thickness", 0)))
                hashable_repr = tuple(dict_to_hashable(w) for w in sorted_combo)
                
                # Only add if not already seen (avoid duplicates)
                if hashable_repr not in seen_combinations:
                    seen_combinations.add(hashable_repr)
                    combinations.append(tuple(sorted_combo))
        
        # Generate all possible combinations
        for i in range(len(weights)):
            combine(weights[i+1:], combination + [weights[i]])
    
    combine(available_weights, [])
    return combinations


def calculate_equipment_weight_combinations(equipment):
    """Return an independent set, reusing calculations for unchanged equipment data."""
    try:
        configuration = json.dumps(equipment, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError):
        return _calculate_equipment_weight_combinations(equipment)
    return set(_cached_equipment_weight_combinations(configuration))


@lru_cache(maxsize=64)
def _cached_equipment_weight_combinations(configuration):
    return frozenset(_calculate_equipment_weight_combinations(json.loads(configuration)))


def _calculate_equipment_weight_combinations(equipment):
    """
    Calculate all valid weight combinations for a given equipment.
    Matches Kotlin getWeightsCombinations() logic for each equipment type.
    
    Args:
        equipment: Equipment dictionary with type and relevant fields
    
    Returns:
        set: Set of valid weight values (floats) that can be achieved with this equipment
    """
    eq_type = equipment.get("type", "").upper()
    
    # Helper to check if plate combination is valid (thickness constraint)
    def is_plate_combination_valid(combination):
        """Check if plate combination fits within sleeveLength.
        
        Note: sleeveLength and thickness are in millimeters (mm).
        sleeveLength refers to the sleeve length (where plates are loaded), not the total barbell length.
        """
        if eq_type not in ["BARBELL", "PLATELOADEDCABLE"]:
            return True
        sleeve_length = equipment.get("sleeveLength", equipment.get("barLength", 0))
        if sleeve_length <= 0:
            return True  # No constraint if sleeveLength not specified
        total_thickness = sum(plate.get("thickness", 0) for plate in combination if isinstance(plate, dict))
        return total_thickness <= sleeve_length
    
    # Helper to calculate total weight from a combination
    def calculate_combination_weight(combination, loading_points=1):
        """Calculate total weight from a combination of weights.
        
        For barbells/dumbbells, loading_points=2 means weights are applied to both sides.
        The combination represents weights on one side, so total = sum(weights) * loading_points.
        """
        total = 0.0
        for weight_item in combination:
            if isinstance(weight_item, dict):
                total += weight_item.get("weight", 0.0)
        return total * loading_points
    
    # Generate base combinations
    base_combinations = set()
    
    if eq_type == "BARBELL":
        available_plates = equipment.get("availablePlates", [])
        bar_weight = equipment.get("barWeight", 0.0)
        loading_points = 2  # Two sides
        
        # Generate all plate combinations
        plate_combos = generate_recursive_valid_subsets(
            available_plates,
            is_combination_valid=is_plate_combination_valid
        )
        
        # Kotlin parity: totals are barWeight alone plus each valid plate total.
        result = {bar_weight}
        for combo in plate_combos:
            combo_weight = calculate_combination_weight(list(combo), loading_points)
            result.add(combo_weight + bar_weight)
        return result
    
    elif eq_type == "DUMBBELLS":
        available_dumbbells = equipment.get("dumbbells", [])
        extra_weights = equipment.get("extraWeights", [])
        max_extra_per_point = equipment.get("maxExtraWeightsPerLoadingPoint", 0)
        loading_points = 2  # Pair
        
        # Base combinations: each dumbbell weight Ã— 2 (pair)
        for db in available_dumbbells:
            if isinstance(db, dict):
                db_weight = db.get("weight", 0.0)
                base_combinations.add(db_weight * loading_points)
        
        # Generate extra weight combinations and combine with base dumbbells
        if extra_weights and max_extra_per_point > 0:
            extra_combos = generate_recursive_valid_subsets(
                extra_weights,
                max_extra_per_point=max_extra_per_point
            )
            
            # Combine each base dumbbell with extra weight combinations
            for db in available_dumbbells:
                if isinstance(db, dict):
                    db_weight = db.get("weight", 0.0)
                    base_total = db_weight * loading_points
                    
                    # Add combinations with extra weights
                    for extra_combo in extra_combos:
                        # Extra weights are added per loading point, so multiply by loading_points
                        extra_total = calculate_combination_weight(list(extra_combo), loading_points)
                        base_combinations.add(base_total + extra_total)
        
        result = {w for w in base_combinations if w > 0}
        return result
    
    elif eq_type == "DUMBBELL":
        available_dumbbells = equipment.get("dumbbells", [])
        extra_weights = equipment.get("extraWeights", [])
        max_extra_per_point = equipment.get("maxExtraWeightsPerLoadingPoint", 0)
        loading_points = 1  # Single
        
        # Base combinations: each dumbbell weight
        for db in available_dumbbells:
            if isinstance(db, dict):
                db_weight = db.get("weight", 0.0)
                base_combinations.add(db_weight * loading_points)
        
        # Generate extra weight combinations and combine with base dumbbells
        if extra_weights and max_extra_per_point > 0:
            extra_combos = generate_recursive_valid_subsets(
                extra_weights,
                max_extra_per_point=max_extra_per_point
            )
            
            # Combine each base dumbbell with extra weight combinations
            for db in available_dumbbells:
                if isinstance(db, dict):
                    db_weight = db.get("weight", 0.0)
                    base_total = db_weight * loading_points
                    
                    # Add combinations with extra weights
                    for extra_combo in extra_combos:
                        extra_total = calculate_combination_weight(list(extra_combo), loading_points)
                        base_combinations.add(base_total + extra_total)
        
        result = {w for w in base_combinations if w > 0}
        return result
    
    elif eq_type == "MACHINE":
        available_weights = equipment.get("availableWeights", [])
        extra_weights = equipment.get("extraWeights", [])
        max_extra_per_point = equipment.get("maxExtraWeightsPerLoadingPoint", 0)
        loading_points = 1
        
        # Base combinations: each available weight
        for weight_item in available_weights:
            if isinstance(weight_item, dict):
                weight_val = weight_item.get("weight", 0.0)
                base_combinations.add(weight_val * loading_points)
        
        # Generate extra weight combinations and combine with base weights
        if extra_weights and max_extra_per_point > 0:
            extra_combos = generate_recursive_valid_subsets(
                extra_weights,
                max_extra_per_point=max_extra_per_point
            )
            
            # Combine each base weight with extra weight combinations
            for base_weight_item in available_weights:
                if isinstance(base_weight_item, dict):
                    base_weight = base_weight_item.get("weight", 0.0)
                    base_total = base_weight * loading_points
                    
                    # Add combinations with extra weights
                    for extra_combo in extra_combos:
                        extra_total = calculate_combination_weight(list(extra_combo), loading_points)
                        base_combinations.add(base_total + extra_total)
        
        result = {w for w in base_combinations if w > 0}
        return result
    
    elif eq_type == "PLATELOADEDCABLE":
        available_plates = equipment.get("availablePlates", [])
        sleeve_length = equipment.get("sleeveLength", equipment.get("barLength", 0))
        loading_points = 1
        
        # Generate all plate combinations
        plate_combos = generate_recursive_valid_subsets(
            available_plates,
            is_combination_valid=is_plate_combination_valid
        )
        
        # Calculate weights
        for combo in plate_combos:
            combo_weight = calculate_combination_weight(list(combo), loading_points)
            base_combinations.add(combo_weight)
        
        result = {w for w in base_combinations if w > 0}
        return result
    
    elif eq_type == "WEIGHTVEST":
        available_weights = equipment.get("availableWeights", [])
        loading_points = 1
        
        # Each available weight is a valid combination
        for weight_item in available_weights:
            if isinstance(weight_item, dict):
                weight_val = weight_item.get("weight", 0.0)
                base_combinations.add(weight_val * loading_points)
        
        result = {w for w in base_combinations if w > 0}
        return result
    
    else:
        # Unknown equipment type
        return set()


def get_selectable_weights_for_exercise(exercise_type, equipment):
    """
    Return the weights selectable in the app for a specific exercise/equipment pair.

    Shared/mobile parity:
    - WEIGHT exercises use equipment.getWeightsCombinations().
    - BODY_WEIGHT exercises with equipment use the same set plus 0.0 additional load.
    - COUNTUP/COUNTDOWN externally loaded exercises use the equipment combinations.
    """
    valid_combinations = set(calculate_equipment_weight_combinations(equipment))
    if exercise_type == "BODY_WEIGHT":
        valid_combinations.add(0.0)
    return valid_combinations


# Equipment whose selectable loads are SUMS over a pair of implements while
# coach-authored loads name ONE implement (its stamped weight) â€” e.g. dumbbell
# pairs. Bilateral-ness alone is not the trigger: a barbell is also two-sided,
# but coaches program its total, which already matches the stored value. New
# pair-implement equipment types must be added here to get per-implement
# normalization.
PAIR_IMPLEMENT_EQUIPMENT_TYPES = {"DUMBBELLS"}


def pair_implement_total_for(eq_type, load_value, selectable_weights):
    """
    Pair total for a per-implement coach load on pair-implement equipment.

    Returns the selectable total equal to 2 x load_value, or None when the
    equipment type is not pair-implement or the doubled value is not selectable
    (leaving the value to the ordinary nearest/repair handling).
    """
    if eq_type not in PAIR_IMPLEMENT_EQUIPMENT_TYPES:
        return None
    return next(
        (valid for valid in selectable_weights if abs(valid - load_value * 2) < 0.01),
        None,
    )


def _format_weight_value_for_prompt(weight: float) -> str:
    """Format a numeric load compactly for planner/exercise prompts."""
    if isinstance(weight, int) or float(weight).is_integer():
        return str(int(weight))
    return f"{float(weight):g}"


def format_equipment_list_for_plan(equipment_list, accessory_list=None):
    """
    Format equipment for plan index: id, type, and name only (no weight combinations).
    Use this when the LLM only needs to know what equipment exists, not valid weights.
    
    Args:
        equipment_list: List of equipment dictionaries
        accessory_list: Optional list of accessory equipment dictionaries
    
    Returns:
        str: Short text, one line per equipment/accessory with id, type, name
    """
    lines = []
    lines.append("Available Equipment (MUST USE ONLY THESE):")
    lines.append("")
    for eq in equipment_list:
        eq_id = eq.get("id", "Unknown")
        eq_name = eq.get("name", "Unknown")
        eq_type = eq.get("type", "").upper()
        lines.append(f"{eq_id} ({eq_name}, {eq_type})")
    if accessory_list:
        for acc in accessory_list:
            acc_id = acc.get("id", "Unknown")
            acc_name = acc.get("name", "Unknown")
            acc_type = acc.get("type", "ACCESSORY").upper()
            lines.append(f"{acc_id} ({acc_name}, {acc_type})")
    return "\n".join(lines)


def format_planner_equipment_context(equipment_list, accessory_list=None):
    """
    Format provided equipment for Step 1 planning.

    This keeps primary equipment and accessories clearly separated and exposes the
    selectable app loads for primary equipment so exact target loads can be
    planned against the current equipment file.
    """
    lines = []
    lines.append("Primary Equipment (valid for equipmentId only):")
    lines.append("")

    if equipment_list:
        for eq in equipment_list:
            eq_id = eq.get("id", "Unknown")
            eq_name = eq.get("name", "Unknown")
            eq_type = eq.get("type", "").upper()
            lines.append(f"{eq_id} ({eq_name}, {eq_type})")
            lines.append("  - Use only as equipmentId, never as requiredAccessoryEquipmentIds.")
            if eq_type == "CARDIO_MACHINE":
                lines.append("  - Compatible exercise types: COUNTUP, COUNTDOWN only.")
            else:
                lines.append("  - Compatible exercise types: WEIGHT, BODY_WEIGHT only.")
            selectable_loads = calculate_equipment_weight_combinations(eq)
            if selectable_loads:
                sorted_loads = sorted(selectable_loads)
                loads_text = ", ".join(
                    f"{_format_weight_value_for_prompt(weight)}kg"
                    for weight in sorted_loads
                )
                lines.append(
                    f"  - Selectable app loads for exact targets: {loads_text}"
                )
            else:
                lines.append(
                    "  - Selectable app loads for exact targets: none/no external load calculation."
                )
            if eq_type == "DUMBBELLS":
                lines.append(
                    "  - These loads are PER-PAIR TOTALS (2 x the weight of ONE dumbbell), while"
                    " coach dumbbell loads are per implement. Transcribe the coach's dumbbell"
                    " load exactly as written ('@ 22.5' stays 22.5) â€” the pipeline normalizes it"
                    " to the pair total. Never round it or substitute a listed load for it."
                )
    else:
        lines.append("(none)")

    lines.append("")
    lines.append("Accessory Equipment (valid for requiredAccessoryEquipmentIds only):")
    lines.append("")

    if accessory_list:
        for acc in accessory_list:
            acc_id = acc.get("id", "Unknown")
            acc_name = acc.get("name", "Unknown")
            acc_type = acc.get("type", "ACCESSORY").upper()
            lines.append(f"{acc_id} ({acc_name}, {acc_type})")
            lines.append(
                "  - Accessory only: never use this ID as equipmentId; use it only in requiredAccessoryEquipmentIds."
            )
    else:
        lines.append("(none)")

    return "\n".join(lines)


def format_equipment_for_llm(equipment_list, accessory_list=None):
    """
    Format equipment data for LLM prompts showing total achievable weight combinations.
    Matches the format used in mobile app export (ExerciseHistoryExport.kt).
    
    Args:
        equipment_list: List of equipment dictionaries
        accessory_list: Optional list of accessory equipment dictionaries
    
    Returns:
        str: Formatted markdown/text representation showing equipment with total weight combinations
    """
    lines = []
    lines.append("Available Equipment (MUST USE ONLY THESE):")
    lines.append("")
    
    # Format weight-loaded equipment
    for eq in equipment_list:
        eq_id = eq.get("id", "Unknown")
        eq_name = eq.get("name", "Unknown")
        eq_type = eq.get("type", "").upper()
        
        lines.append(f"{eq_id} ({eq_name}, {eq_type}):")
        lines.append(f"  - Type: {eq_type}")
        
        # Calculate valid weight combinations
        valid_combinations = calculate_equipment_weight_combinations(eq)
        
        if valid_combinations:
            sorted_combos = sorted(valid_combinations)
            if eq_type == "DUMBBELLS":
                lines.append("  - Load meaning: COMBINED weight of TWO dumbbells; per-hand weight = total / 2. Never double these totals.")
                lines.append(f"  - Maximum load: {sorted_combos[-1]}kg combined = {sorted_combos[-1] / 2}kg per hand.")
            elif eq_type == "DUMBBELL":
                lines.append("  - Load meaning: weight of ONE dumbbell (one hand), not a pair.")
                lines.append(f"  - Maximum load: {sorted_combos[-1]}kg for one dumbbell.")
            elif eq_type == "BARBELL":
                lines.append("  - Load meaning: TOTAL barbell weight INCLUDING the bar; do not add bar weight again.")
                lines.append(f"  - Maximum load: {sorted_combos[-1]}kg including the bar.")
            # Format as comma-separated list (matching ExerciseHistoryExport.kt format)
            combo_str = ", ".join(f"{w}kg" for w in sorted_combos)
            total_count = len(sorted_combos)
            lines.append(f"  - Available Total Weights: {combo_str} (total {total_count} combinations)")
        else:
            lines.append(f"  - Available Total Weights: (none calculated)")
        
        # Add equipment-specific details
        if eq_type == "BARBELL":
            bar_weight = eq.get("barWeight", 0.0)
            if bar_weight > 0:
                lines.append(f"  - Bar Weight: {bar_weight}kg")
        elif eq_type in ["DUMBBELLS", "DUMBBELL"]:
            max_extra = eq.get("maxExtraWeightsPerLoadingPoint", 0)
            if max_extra > 0:
                lines.append(f"  - Max Extra Weights Per Loading Point: {max_extra}")
        elif eq_type == "MACHINE":
            max_extra = eq.get("maxExtraWeightsPerLoadingPoint", 0)
            if max_extra > 0:
                lines.append(f"  - Max Extra Weights Per Loading Point: {max_extra}")
        
        lines.append("")
    
    # Format accessory equipment
    if accessory_list:
        for acc in accessory_list:
            acc_id = acc.get("id", "Unknown")
            acc_name = acc.get("name", "Unknown")
            acc_type = acc.get("type", "ACCESSORY").upper()
            
            lines.append(f"{acc_id} ({acc_name}, {acc_type}):")
            lines.append(f"  - Type: {acc_type}")
            lines.append(f"  - Name: {acc_name}")
            lines.append("")
    
    return "\n".join(lines)


def format_equipment_for_conversation(provided_equipment):
    """
    Format equipment for adding to conversation context.
    
    Args:
        provided_equipment: Dict with 'equipments' and 'accessoryEquipments' keys
    
    Returns:
        str: Formatted equipment content with immutability instructions
    """
    formatted_equipment = format_equipment_for_llm(
        provided_equipment.get("equipments", []),
        provided_equipment.get("accessoryEquipments", [])
    )
    return (
        f"{formatted_equipment}\n\n"
        f"CRITICAL: Equipment from the provided file is IMMUTABLE - you CANNOT edit, modify, or change any equipment or accessories from the list above.\n"
        f"Use equipment and accessories from the list above when available (use their exact placeholder IDs).\n"
        f"During requirements discussion and exercise recommendations, respect these maximum loads. Compare loads on the same total/per-hand basis, and use only listed achievable loads for progression; do not assume uniform increments.\n"
        f"If necessary equipment or accessories are missing from the list above, you MAY create new equipment or accessory entries with new placeholder IDs."
    )


def has_equipment_in_messages(messages):
    """
    Check if equipment context is already present in messages.
    
    Args:
        messages: List of message dictionaries
    
    Returns:
        bool: True if equipment context is found in messages
    """
    for msg in messages:
        content = msg.get("content", "")
        if "Available Equipment (MUST USE ONLY THESE):" in content or "Equipment from the provided file is IMMUTABLE" in content:
            return True
    return False


def fix_timed_sets(exercise):
    """Use the shared value-preserving set normalization."""
    exercise['sets'] = fix_set_errors(exercise.get('sets', []))


def create_placeholder_schema():
    """
    Create a schema variant that allows placeholder IDs instead of strict UUIDs.
    This is identical to JSON_SCHEMA except the UUID pattern is relaxed to accept placeholders.
    
    Returns:
        dict: Schema with placeholder-tolerant UUID pattern
    """
    import copy
    placeholder_schema = copy.deepcopy(JSON_SCHEMA)
    
    # Update UUID pattern to accept placeholders.
    # Placeholder IDs are internal only and are converted to UUIDs in the final step,
    # so the placeholder phase accepts alphanumeric suffixes such as EXERCISE_D6.
    placeholder_schema["$defs"]["UUID"] = {
        "type": "string",
        "pattern": PLACEHOLDER_ID_PATTERN
    }
    
    return placeholder_schema








def ensure_unique_ids(workout_store):
    """
    Ensure all IDs are unique globally across the WorkoutStore.
    Checks: workout.id, workout.globalId, component.id, set.id
    Regenerates duplicates while preserving first occurrence.
    """
    seen_ids = set()

    # First pass: Check workout IDs and globalIds
    for workout in workout_store.get("workouts", []):
        if not isinstance(workout, dict):
            continue
            
        # Check workout.id
        workout_id = workout.get("id")
        if workout_id:
            if workout_id in seen_ids:
                workout["id"] = str(uuid.uuid4())
            seen_ids.add(workout["id"])
        
        # Check workout.globalId
        global_id = workout.get("globalId")
        if global_id:
            if global_id in seen_ids:
                workout["globalId"] = str(uuid.uuid4())
            seen_ids.add(workout["globalId"])

    # Second pass: Check component IDs (Exercise, Rest, Superset)
    for workout in workout_store.get("workouts", []):
        if not isinstance(workout, dict):
            continue
            
        for component in workout.get("workoutComponents", []):
            if not isinstance(component, dict):
                continue
                
            component_id = component.get("id")
            if component_id:
                if component_id in seen_ids:
                    component["id"] = str(uuid.uuid4())
                seen_ids.add(component["id"])

            if component.get("type") == "Superset":
                rewritten_rest_keys = {}
                rest_map = component.get("restSecondsByExercise") or {}
                for exercise in component.get("exercises", []):
                    if not isinstance(exercise, dict):
                        continue
                    old_id = exercise.get("id")
                    new_id = old_id
                    if not new_id or new_id in seen_ids:
                        new_id = str(uuid.uuid4())
                        exercise["id"] = new_id
                    seen_ids.add(new_id)
                    if old_id in rest_map:
                        rewritten_rest_keys[new_id] = rest_map[old_id]
                if rewritten_rest_keys:
                    component["restSecondsByExercise"] = rewritten_rest_keys

    # Third pass: Check set IDs within exercises (including exercises within supersets)
    for workout in workout_store.get("workouts", []):
        if not isinstance(workout, dict):
            continue
            
        for component in workout.get("workoutComponents", []):
            if not isinstance(component, dict):
                continue
                
            component_type = component.get("type")
            
            if component_type == "Exercise":
                _dedupe_sets_in_exercise(component, seen_ids)
            elif component_type == "Superset":
                for exercise in component.get("exercises", []):
                    if isinstance(exercise, dict):
                        _dedupe_sets_in_exercise(exercise, seen_ids)


def _dedupe_sets_in_exercise(exercise, seen_ids):
    """Helper function to deduplicate set IDs within an exercise."""
    sets = exercise.get("sets")
    if not isinstance(sets, list):
        return

    for set_item in sets:
        if not isinstance(set_item, dict):
            continue
        set_id = set_item.get("id")
        if not set_id or set_id in seen_ids:
            set_item["id"] = str(uuid.uuid4())
        seen_ids.add(set_item["id"])


DEFINITION_OWNED_FIELDS = (
    "name",
    "exerciseType",
    "equipmentId",
    "bodyWeightPercentage",
    "muscleGroups",
    "secondaryMuscleGroups",
    "trainingMuscles",
    "requiredAccessoryEquipmentIds",
    "exerciseCategory",
    "movementRef",
)


def build_exercise_definition_id(definition):
    """Return the deterministic schema-v2 ID for definition-owned content."""
    content = {
        key: copy.deepcopy(value)
        for key, value in definition.items()
        if key != "id"
    }
    stable_content = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"mwa-exercise-definition-v2:{stable_content}")
    )


def apply_exercise_library_schema_v2(
    workout_package,
    supplied_definitions=None,
    supplied_exercise_movements=None,
):
    """Materialize schema-v2 definitions and link every independent prescription.

    Exercise components remain fully materialized for legacy app readers. Definition identity is
    movement/name + exercise type + equipment; programming fields and component IDs remain local
    to each occurrence, which permits periodized prescriptions of one shared movement.
    """
    if not isinstance(workout_package, dict):
        raise ValueError("Workout package must be an object")

    supplied_by_id = {}
    for raw_definition in supplied_definitions or []:
        if not isinstance(raw_definition, dict) or not raw_definition.get("id"):
            raise ValueError("Every supplied exercise definition must have an id")
        definition = copy.deepcopy(raw_definition)
        definition.pop("instructions", None)
        definition.pop("instructionEquipmentIds", None)
        for key in ("programmingDemands", "anatomy", "reviewedExerciseFamily"):
            definition.pop(key, None)  # Generator evidence is not part of the app definition schema.
        existing = supplied_by_id.get(definition["id"])
        if existing is not None and existing != definition:
            raise ValueError(
                f"Conflicting content for exercise definition id {definition['id']}"
            )
        supplied_by_id[definition["id"]] = definition

    def identity_key(value):
        movement_ref = value.get("movementRef")
        movement_identity = (
            json.dumps(movement_ref, sort_keys=True, separators=(",", ":"))
            if movement_ref is not None
            else str(value.get("name") or "").strip().casefold()
        )
        return (
            movement_identity,
            value.get("exerciseType"),
            value.get("equipmentId"),
        )

    supplied_by_identity = {}
    for definition in supplied_by_id.values():
        key = identity_key(definition)
        existing = supplied_by_identity.get(key)
        if existing is not None and existing != definition:
            raise ValueError(
                "Exercise library contains multiple definitions for the same movement, type, "
                "and equipment"
            )
        supplied_by_identity[key] = definition

    canonical_by_identity = {}

    def generated_definition(exercise):
        definition = {
            "name": exercise.get("name", ""),
        }
        for field in DEFINITION_OWNED_FIELDS:
            if field != "name" and field in exercise:
                definition[field] = copy.deepcopy(exercise[field])
        definition["id"] = build_exercise_definition_id(definition)
        return definition

    def link_prescription(exercise):
        if not isinstance(exercise, dict) or exercise.get("type") != "Exercise":
            return
        key = identity_key(exercise)
        definition = canonical_by_identity.get(key)
        if definition is None:
            definition = copy.deepcopy(supplied_by_identity.get(key) or generated_definition(exercise))
            canonical_by_identity[key] = definition

        exercise["exerciseDefinitionId"] = definition["id"]
        exercise.pop("placementNotes", None)
        for field in DEFINITION_OWNED_FIELDS:
            if field in definition:
                exercise[field] = copy.deepcopy(definition[field])
            else:
                exercise.pop(field, None)

    for workout in workout_package.get("workouts", []) or []:
        for component in workout.get("workoutComponents", []) or []:
            if not isinstance(component, dict):
                continue
            if component.get("type") == "Exercise":
                link_prescription(component)
            elif component.get("type") == "Superset":
                for exercise in component.get("exercises", []) or []:
                    link_prescription(exercise)

    definitions = list(canonical_by_identity.values())
    referenced_ids = {
        exercise.get("exerciseDefinitionId")
        for exercise in _iter_exercise_components(workout_package)
    }
    if None in referenced_ids or referenced_ids != {definition["id"] for definition in definitions}:
        raise ValueError("Generated exercise definition references are incomplete")

    workout_package["schemaVersion"] = 2
    workout_package["exerciseDefinitions"] = definitions
    referenced_movement_refs = {
        json.dumps(definition.get("movementRef"), sort_keys=True, separators=(",", ":"))
        for definition in definitions
        if definition.get("movementRef") is not None
    }
    movement_backups = supplied_exercise_movements
    if movement_backups is None:
        movement_backups = workout_package.get("exerciseMovements", [])
    workout_package["exerciseMovements"] = [
        copy.deepcopy(backup)
        for backup in movement_backups or []
        if isinstance(backup, dict)
        and json.dumps(backup.get("movementRef"), sort_keys=True, separators=(",", ":"))
        in referenced_movement_refs
    ]
    return workout_package


def _iter_exercise_components(workout_package):
    for workout in workout_package.get("workouts", []) or []:
        for component in workout.get("workoutComponents", []) or []:
            if not isinstance(component, dict):
                continue
            if component.get("type") == "Exercise":
                yield component
            elif component.get("type") == "Superset":
                yield from (
                    exercise for exercise in component.get("exercises", []) or []
                    if isinstance(exercise, dict)
                )


def convert_placeholders_to_uuids(placeholder_workout_store, id_manager, validate_final=True, logger=None):
    """
    Convert all placeholder IDs to UUIDs in a validated placeholder WorkoutStore.
    This is the final step before output - converts placeholders to real UUIDs.
    
    Args:
        placeholder_workout_store: Validated placeholder-based WorkoutStore
        id_manager: PlaceholderIdManager instance
        validate_final: If True, validate against strict JSON_SCHEMA after conversion
        logger: Optional ConversationLogger for debug logging
    
    Returns:
        dict: UUID-based WorkoutStore, optionally validated against strict schema
    """
    def _out(msg):
        if logger:
            logger.log_print(msg)
        else:
            print(msg)
    # Extract and register all placeholders
    id_manager.extract_placeholders_from_json(placeholder_workout_store)
    
    # Replace all placeholders with UUIDs
    uuid_workout_store = id_manager.replace_placeholders(placeholder_workout_store)
    ensure_unique_ids(uuid_workout_store)
    
    # Optional final validation against strict schema
    if validate_final and validate is not None:
        try:
            validate(instance=uuid_workout_store, schema=JSON_SCHEMA)
            _out("Ã¢Å“â€œ Final UUID-based validation passed")
        except Exception as final_err:
            _out(f"Warning: Final UUID validation failed (this should be rare): {final_err}")
            # Don't raise - the placeholder validation should have caught structural issues
            # This is just a safety check
    
    return uuid_workout_store


def remove_none_from_workout_components(workout_store, logger=None):
    """
    Remove None values from workoutComponents arrays in all workouts.
    This can happen if JSON patch operations extend arrays with None values.

    Args:
        workout_store: WorkoutStore dict (may be modified in place)
        logger: Optional ConversationLogger for debug logging (log_print when set)

    Returns:
        dict: WorkoutStore with None values removed from workoutComponents
    """
    if "workouts" not in workout_store:
        return workout_store

    for workout in workout_store["workouts"]:
        if "workoutComponents" in workout and isinstance(workout["workoutComponents"], list):
            # Filter out None values
            original_length = len(workout["workoutComponents"])
            workout["workoutComponents"] = [comp for comp in workout["workoutComponents"] if comp is not None]
            removed_count = original_length - len(workout["workoutComponents"])
            if removed_count > 0:
                msg = f"  Removed {removed_count} None value(s) from workout '{workout.get('name', 'Unknown')}' workoutComponents"
                if logger:
                    logger.log_print(msg)
                else:
                    print(msg)

    return workout_store


def ensure_requiresLoadCalibration(workout_store, allow_educated_load_guesses=True):
    """
    Ensure all exercises have a boolean requiresLoadCalibration value.
    Preserve the plan-derived calibration decision; missing decisions or loads require calibration. Pass
    allow_educated_load_guesses=False to require strict calibration for every loaded exercise.
    
    Args:
        workout_store: WorkoutStore dict (may be modified in place)
    
    Returns:
        dict: WorkoutStore with requiresLoadCalibration set appropriately for all exercises
    """
    if "workouts" not in workout_store:
        return workout_store
    
    def process_exercise(exercise):
        """Process a single exercise to set requiresLoadCalibration."""
        if not isinstance(exercise, dict) or exercise.get("type") != "Exercise":
            return
        
        exercise_type = exercise.get("exerciseType")
        equipment_id = exercise.get("equipmentId")
        
        apply_requires_load_calibration_policy(
            exercise,
            allow_educated_load_guesses=allow_educated_load_guesses,
        )
    
    for workout in workout_store["workouts"]:
        if "workoutComponents" not in workout or not isinstance(workout["workoutComponents"], list):
            continue
        
        for component in workout["workoutComponents"]:
            if not isinstance(component, dict):
                continue
            
            component_type = component.get("type")
            
            if component_type == "Exercise":
                # Direct exercise in workoutComponents
                process_exercise(component)
            
            elif component_type == "Superset":
                # Process exercises within superset
                if "exercises" in component and isinstance(component["exercises"], list):
                    for exercise in component["exercises"]:
                        process_exercise(exercise)
    
    return workout_store


def sanitize_rep_range_fields_on_exercise_dict(exercise: Dict[str, Any]) -> None:
    """
    Make minReps/maxReps valid for JSON Schema: integers only, never null.

    - COUNTDOWN/COUNTUP: omit both (time-based; reps do not apply).
    - Other types: drop keys whose value is None so the field is omitted instead of null.
    """
    if not isinstance(exercise, dict):
        return
    et = exercise.get("exerciseType")
    if et in ("COUNTDOWN", "COUNTUP", "RUNNING"):
        exercise.pop("minReps", None)
        exercise.pop("maxReps", None)
        return
    if exercise.get("minReps") is None:
        exercise.pop("minReps", None)
    if exercise.get("maxReps") is None:
        exercise.pop("maxReps", None)


def strip_rep_range_fields_for_timed_exercises_in_workout_store(workout_store: Dict[str, Any]) -> Dict[str, Any]:
    """Walk workouts and sanitize rep-range fields on every exercise component."""
    if not isinstance(workout_store, dict):
        return workout_store
    for wo in workout_store.get("workouts", []) or []:
        if not isinstance(wo, dict):
            continue
        for comp in wo.get("workoutComponents", []) or []:
            if not isinstance(comp, dict):
                continue
            if comp.get("type") == "Exercise":
                sanitize_rep_range_fields_on_exercise_dict(comp)
            elif comp.get("type") == "Superset":
                for ex in comp.get("exercises", []) or []:
                    sanitize_rep_range_fields_on_exercise_dict(ex)
    return workout_store


# Backward-compatible name
strip_rep_range_fields_for_timed_exercises = sanitize_rep_range_fields_on_exercise_dict


def assemble_placeholder_workout_store(equipment_items, accessory_items, exercise_definitions, workout_structures, plan_index, user_data=None):
    """
    Assemble emitted objects into a placeholder-based workout plan package candidate.
    This assembles the normalized objects (EquipmentItem, AccessoryEquipment, ExerciseDefinition, WorkoutStructure)
    into a single workout plan package structure matching JSON_SCHEMA, all using placeholder IDs.
    
    Args:
        equipment_items: Dict mapping equipment_id -> EquipmentItem (weight-loaded equipment)
        accessory_items: Dict mapping accessory_id -> AccessoryEquipment
        exercise_definitions: Dict mapping exercise_id -> ExerciseDefinition
        workout_structures: Dict mapping workout_id -> WorkoutStructure
        plan_index: PlanIndex dict
    Returns:
        dict: Placeholder-based workout plan package matching JSON_SCHEMA shape
    """
    # Build equipments array from equipment_items (weight-loaded only)
    equipments = list(equipment_items.values())
    
    # Build accessoryEquipments array from accessory_items
    accessory_equipments = list(accessory_items.values())
    
    # Build workouts array: use plan_index workout order so order field matches user-provided order (0, 1, 2, ...)
    workouts = []
    plan_workouts = plan_index.get("workouts", [])

    # Deterministic CrossFit-mode carry-through: the planner encodes time caps, EMOM
    # cadence and cardio quantities on the plan index (supersetGroups / timed
    # prescriptions); copy them onto the assembled components here so emitter
    # compliance cannot silently drop them.
    plan_groups_by_members = {}
    for wo in plan_workouts:
        if not isinstance(wo, dict):
            continue
        for group in wo.get("supersetGroups", []) or []:
            if isinstance(group, dict) and group.get("exerciseIds"):
                plan_groups_by_members[frozenset(group["exerciseIds"])] = group
    plan_exercises_by_id = {
        ex.get("id"): ex
        for ex in plan_index.get("exercises", []) or []
        if isinstance(ex, dict) and ex.get("id")
    }

    def apply_plan_timed_targets(exercise, plan_exercise):
        """Copies plan-index targetDistanceMeters/targetCalories onto timed work sets
        and materializes RUNNING prescriptions deterministically."""
        if not isinstance(plan_exercise, dict):
            return
        if plan_exercise.get("exerciseType") == "RUNNING":
            distance = plan_exercise.get("targetDistanceMeters")
            if distance is not None and distance > 0:
                exercise["exerciseType"] = "RUNNING"
                if not isinstance(exercise.get("runningPrescription"), dict):
                    exercise["runningPrescription"] = {
                        "environment": "OUTDOOR",
                        "targetType": "DISTANCE",
                        "targetValue": distance,
                    }
                # Running exercises count up until the distance goal is reached.
                # The set id must satisfy the placeholder-ID pattern (no hyphens)
                # or the step-6 self-heal rewrites the whole set.
                safe_id = re.sub(r"[^A-Za-z0-9_]", "_", str(exercise.get("id")))
                exercise["sets"] = [
                    {
                        "id": f"SET_{safe_id}_RUN",
                        "type": "RunningSet",
                        "shouldReapplyHistoryToSet": False,
                    }
                ]
            return
        if plan_exercise.get("exerciseType") not in ("COUNTUP", "COUNTDOWN"):
            return
        target_fields = ("targetDistanceMeters", "targetCalories")
        if not any(plan_exercise.get(field) is not None for field in target_fields):
            return
        rebuilt_sets = []
        for set_data in exercise.get("sets") or []:
            if (
                isinstance(set_data, dict)
                and set_data.get("type") in ("TimedDurationSet", "EnduranceSet")
                and any(
                    plan_exercise.get(field) is not None and set_data.get(field) is None
                    for field in target_fields
                )
            ):
                # exercise_definitions entries are reused across workouts; copy before mutating
                set_data = dict(set_data)
                for field in target_fields:
                    value = plan_exercise.get(field)
                    if value is not None and set_data.get(field) is None:
                        set_data[field] = value
            rebuilt_sets.append(set_data)
        exercise["sets"] = rebuilt_sets

    if plan_workouts:
        items_to_process = [(i, wo.get("id"), workout_structures.get(wo.get("id"))) for i, wo in enumerate(plan_workouts)]
    else:
        items_to_process = [(i, wid, w) for i, (wid, w) in enumerate(workout_structures.items())]

    for order, workout_id, workout_structure in items_to_process:
        if workout_structure is None:
            print(f"  Warning: Workout structure for '{workout_id}' not found, skipping")
            continue
        metadata = workout_structure.get("workoutMetadata", {})
        components_spec = workout_structure.get("workoutComponents", [])

        # Resolve workoutComponents from the structure spec into actual components
        workout_components = []
        component_id_counter = 0

        for component_spec in components_spec:
            component_type = component_spec.get("componentType")

            if component_type == "Exercise":
                # Find the exercise by ID
                exercise_id = component_spec.get("exerciseId")
                if exercise_id in exercise_definitions:
                    exercise = exercise_definitions[exercise_id].copy()
                    fix_muscle_groups_in_exercise(exercise)
                    # Normalize sets (fixes TimedDurationSet/EnduranceSet timeInSeconds -> timeInMillis)
                    if "sets" in exercise:
                        exercise["sets"] = fix_set_errors(exercise["sets"])
                    strip_rep_range_fields_for_timed_exercises(exercise)
                    apply_plan_timed_targets(exercise, plan_exercises_by_id.get(exercise_id))
                    exercise["enabled"] = component_spec.get("enabled", True)
                    workout_components.append(exercise)
                else:
                    # Skip if exercise not found
                    print(f"  Warning: Exercise '{exercise_id}' not found in exercise definitions, skipping component")
                    continue

            elif component_type == "Rest":
                # Create Rest component
                rest_id = f"COMPONENT_{component_id_counter}"
                component_id_counter += 1
                rest_component = {
                    "id": rest_id,
                    "type": "Rest",
                    "enabled": component_spec.get("enabled", True),
                    "timeInSeconds": component_spec.get("timeInSeconds", 60)
                }
                workout_components.append(rest_component)

            elif component_type == "Superset":
                # Get exercises for the superset
                exercise_ids_placeholder = component_spec.get("exerciseIds", [])
                superset_exercises = []
                rest_seconds_by_exercise = {}
                emitted_rest_map = component_spec.get("restSecondsByExercise")
                if not isinstance(emitted_rest_map, dict) or set(emitted_rest_map) != set(exercise_ids_placeholder):
                    raise ValueError(
                        "Superset restSecondsByExercise must contain exactly one entry for every exerciseId"
                    )

                for ex_id_placeholder in exercise_ids_placeholder:
                    if ex_id_placeholder in exercise_definitions:
                        exercise = exercise_definitions[ex_id_placeholder].copy()
                        fix_muscle_groups_in_exercise(exercise)
                        # Normalize sets (fixes TimedDurationSet/EnduranceSet timeInSeconds -> timeInMillis)
                        if "sets" in exercise:
                            exercise["sets"] = fix_set_errors(exercise["sets"])
                        strip_rep_range_fields_for_timed_exercises(exercise)
                        apply_plan_timed_targets(exercise, plan_exercises_by_id.get(ex_id_placeholder))
                        superset_exercises.append(exercise)
                        # Map the placeholder ID to rest seconds
                        rest_seconds = emitted_rest_map[ex_id_placeholder]
                        if not isinstance(rest_seconds, int) or isinstance(rest_seconds, bool) or rest_seconds < 0:
                            raise ValueError(
                                f"Superset rest after {ex_id_placeholder} must be a non-negative integer"
                            )
                        rest_seconds_by_exercise[ex_id_placeholder] = rest_seconds

                # Only create Superset if it has at least one exercise
                if superset_exercises:
                    superset_id = f"COMPONENT_{component_id_counter}"
                    component_id_counter += 1
                    superset_component = {
                        "id": superset_id,
                        "type": "Superset",
                        "enabled": component_spec.get("enabled", True),
                        "exercises": superset_exercises,
                        "restSecondsByExercise": rest_seconds_by_exercise
                    }
                    plan_group = plan_groups_by_members.get(frozenset(exercise_ids_placeholder))
                    if plan_group:
                        if plan_group.get("timeCapSeconds") is not None:
                            superset_component["timeCapSeconds"] = plan_group["timeCapSeconds"]
                        if plan_group.get("roundDurationSeconds") is not None:
                            superset_component["roundDurationSeconds"] = plan_group["roundDurationSeconds"]
                        if plan_group.get("amrap"):
                            superset_component["amrap"] = True
                    workout_components.append(superset_component)
                else:
                    print(f"  Warning: Superset component has no valid exercises, skipping")
                    continue

            else:
                # Unknown component type - skip with warning
                print(f"  Warning: Unknown component type '{component_type}', skipping component")
                continue

        # Build the workout object; order from plan index (0, 1, 2, ...) or fallback enumerate
        creation_date = date.today().isoformat()
        workout_order = order if plan_workouts else metadata.get("order", order)
        workout = {
            "id": workout_id,
            "name": metadata.get("name", "Generated Workout"),
            "description": metadata.get("description", ""),
            "workoutComponents": workout_components,
            "order": workout_order,
            "enabled": metadata.get("enabled", True),
            "usePolarDevice": metadata.get("usePolarDevice", False),
            "creationDate": creation_date,
            "previousVersionId": None,
            "nextVersionId": None,
            "isActive": metadata.get("isActive", True),
            "timesCompletedInAWeek": metadata.get("timesCompletedInAWeek"),
            "globalId": f"{workout_id}_GLOBAL",
            "type": metadata.get("type", 0),
            "workoutPlanId": metadata.get("workoutPlanId"),
        }
        workouts.append(workout)
    
    plan_name = plan_index.get("planName") or "Generated Workout Plan"

    # Assemble final placeholder-based workout plan package
    placeholder_workout_store = {
        "name": plan_name,
        "workouts": workouts,
        "equipments": equipments,
        "accessoryEquipments": accessory_equipments,
    }
    
    # Remove any None values from workoutComponents arrays
    placeholder_workout_store = remove_none_from_workout_components(placeholder_workout_store)
    
    return placeholder_workout_store


def fix_muscle_groups(muscle_groups):
    """Fix invalid muscle group names."""
    if not isinstance(muscle_groups, list):
        return muscle_groups
    fixed = []
    valid_muscle_groups = {
        "FRONT_ABS", "FRONT_ADDUCTORS", "FRONT_ANKLES", "FRONT_BICEPS", "FRONT_CALVES",
        "FRONT_CHEST", "FRONT_DELTOIDS", "FRONT_FEET", "FRONT_FOREARM", "FRONT_HANDS",
        "FRONT_KNEES", "FRONT_NECK", "FRONT_OBLIQUES", "FRONT_QUADRICEPS", "FRONT_TIBIALIS",
        "FRONT_TRAPEZIUS", "FRONT_TRICEPS", "BACK_ADDUCTORS", "BACK_ANKLES", "BACK_CALVES",
        "BACK_DELTOIDS", "BACK_FEET", "BACK_FOREARM", "BACK_GLUTEAL", "BACK_HAMSTRING",
        "BACK_HANDS", "BACK_LOWER_BACK", "BACK_NECK", "BACK_TRAPEZIUS", "BACK_TRICEPS",
        "BACK_UPPER_BACK"
    }
    for mg in muscle_groups:
        if isinstance(mg, str):
            mg_upper = mg.upper()
            # First try to fix common errors
            fixed_mg = MUSCLE_GROUP_FIXES.get(mg_upper, mg_upper)
            # Only add if it's a valid enum value
            if fixed_mg in valid_muscle_groups:
                fixed.append(fixed_mg)
    return fixed


def infer_exercise_category(exercise):
    """
    Infer exerciseCategory from exercise name and muscle groups when missing.
    HEAVY_COMPOUND: squat, deadlift, bench, overhead press, row variations.
    MODERATE_COMPOUND: lunges, split squats, hip thrusts, machine presses, pull-ups.
    ISOLATION: curls, lateral raises, triceps, calf raises.
    """
    if not isinstance(exercise, dict):
        return None
    name = (exercise.get("name") or "").lower()
    if not name:
        return None
    isolation_keywords = ("curl", "lateral raise", "triceps extension", "calf raise", "fly", "kickback", "pushdown", "extension", "leg extension", "leg curl", "preacher", "concentration curl")
    heavy_keywords = ("squat", "deadlift", "bench press", "overhead press", "ohp", "barbell row", "pendlay", "power clean", "front squat", "back squat", "romanian deadlift", "rdl")
    moderate_keywords = ("lunge", "split squat", "hip thrust", "pull-up", "pullup", "chin-up", "machine press", "goblet", "step-up", "bulgarian")
    if any(k in name for k in isolation_keywords):
        return "ISOLATION"
    if any(k in name for k in heavy_keywords):
        return "HEAVY_COMPOUND"
    if any(k in name for k in moderate_keywords):
        return "MODERATE_COMPOUND"
    return "MODERATE_COMPOUND"  # safe default


def fix_muscle_groups_in_exercise(exercise):
    """
    Fix invalid muscle group names in both muscleGroups and secondaryMuscleGroups fields.
    Also infer exerciseCategory when missing for WEIGHT/BODY_WEIGHT exercises.
    
    Args:
        exercise: Exercise dictionary (modified in place)
    
    Returns:
        dict: The modified exercise dictionary
    """
    if not isinstance(exercise, dict):
        return exercise
    
    if "muscleGroups" in exercise:
        exercise["muscleGroups"] = fix_muscle_groups(exercise["muscleGroups"])
    
    if "secondaryMuscleGroups" in exercise:
        exercise["secondaryMuscleGroups"] = fix_muscle_groups(exercise["secondaryMuscleGroups"])
    
    # Infer exerciseCategory when missing for WEIGHT/BODY_WEIGHT (support legacy warmupCategory key)
    current = exercise.get("exerciseCategory") or exercise.get("warmupCategory")
    if current is None and exercise.get("exerciseType") in ("WEIGHT", "BODY_WEIGHT"):
        inferred = infer_exercise_category(exercise)
        if inferred:
            exercise["exerciseCategory"] = inferred
    
    return exercise


def fix_set_errors(sets):
    """Fix invalid set types and structures."""
    if not isinstance(sets, list):
        return sets
    fixed = []
    for s in sets:
        if not isinstance(s, dict):
            fixed.append(s)
            continue
        s_copy = s.copy()
        set_type = s_copy.get("type", "")

        if set_type == "RestSet" and "subCategory" not in s_copy:
            # Shared deserialization falls back to WorkSet for legacy RestSets.
            s_copy["subCategory"] = "WorkSet"
        
        if set_type in ('TimedDurationSet', 'EnduranceSet'):
            seconds = s_copy.get('timeInSeconds')
            if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
                milliseconds = Decimal(str(seconds)) * 1000
                if milliseconds.is_finite() and milliseconds == milliseconds.to_integral_value():
                    value = int(milliseconds)
                    if 'timeInMillis' not in s_copy or (type(s_copy['timeInMillis']) in (int, float)
                                                       and s_copy['timeInMillis'] == value):
                        s_copy['timeInMillis'] = value
                        s_copy.pop('timeInSeconds')
            # Manual tracking is the app default; no duration or effort target is inferred.
            s_copy.setdefault('autoStart', False)
            s_copy.setdefault('autoStop', False)

        if set_type == 'DistanceSet':
            distance = s_copy.get('distance')
            if (isinstance(distance, (int, float)) and not isinstance(distance, bool)
                    and Decimal(str(distance)).is_finite() and distance > 0
                    and not s_copy.get('autoStop')
                    and s_copy.get('targetDistanceMeters', distance) == distance):
                s_copy.pop('distance')
                s_copy.update(type='EnduranceSet', targetDistanceMeters=float(distance))
                s_copy.setdefault('timeInMillis', 0)
                s_copy.setdefault('autoStart', True)
                s_copy.setdefault('autoStop', False)

        fixed.append(s_copy)
    return fixed


def fix_exercise_errors(exercises, allow_educated_load_guesses=True):
    """Fix common exercise errors including muscle groups and sets."""
    if not isinstance(exercises, list):
        return exercises
    fixed = []
    for ex in exercises:
        if not isinstance(ex, dict):
            fixed.append(ex)
            continue
        ex_copy = ex.copy()
        
        # Fix invalid exercise types
        valid_exercise_types = ["COUNTUP", "BODY_WEIGHT", "COUNTDOWN", "WEIGHT", "RUNNING"]
        if "exerciseType" in ex_copy:
            ex_type = ex_copy["exerciseType"]
            if ex_type not in valid_exercise_types:
                # Default to WEIGHT for most cases, COUNTUP for distance-based
                if ex_type == "DISTANCE":
                    ex_copy["exerciseType"] = "COUNTUP"
                else:
                    ex_copy["exerciseType"] = "WEIGHT"
        
        # Normalize requiredAccessoryEquipmentIds to empty array if None
        if ex_copy.get("requiredAccessoryEquipmentIds") is None:
            ex_copy["requiredAccessoryEquipmentIds"] = []
        if ex_copy.get("secondaryMuscleGroups") is None:
            ex_copy["secondaryMuscleGroups"] = []
        if "intraSetRestInSeconds" not in ex_copy:
            ex_copy["intraSetRestInSeconds"] = None
        if "bodyWeightPercentage" not in ex_copy and ex_copy.get("exerciseType") != "BODY_WEIGHT":
            ex_copy["bodyWeightPercentage"] = None
        if "exerciseCategory" not in ex_copy and ex_copy.get("exerciseType") in ("COUNTDOWN", "COUNTUP"):
            ex_copy["exerciseCategory"] = None
        
        apply_requires_load_calibration_policy(
            ex_copy,
            allow_educated_load_guesses=allow_educated_load_guesses,
        )

        strip_rep_range_fields_for_timed_exercises(ex_copy)

        # Fix muscle groups
        if "muscleGroups" in ex_copy:
            ex_copy["muscleGroups"] = fix_muscle_groups(ex_copy["muscleGroups"])
        if "secondaryMuscleGroups" in ex_copy:
            ex_copy["secondaryMuscleGroups"] = fix_muscle_groups(ex_copy["secondaryMuscleGroups"])
        
        # Infer exerciseCategory when missing for WEIGHT/BODY_WEIGHT (support legacy warmupCategory key)
        current = ex_copy.get("exerciseCategory") or ex_copy.get("warmupCategory")
        if current is None and ex_copy.get("exerciseType") in ("WEIGHT", "BODY_WEIGHT"):
            inferred = infer_exercise_category(ex_copy)
            if inferred:
                ex_copy["exerciseCategory"] = inferred
        
        # Fix sets
        if "sets" in ex_copy:
            ex_copy["sets"] = fix_set_errors(ex_copy["sets"])
        
        fixed.append(ex_copy)
    return fixed


def sync_exercises_from_definitions(workout_store, exercise_definitions):
    """
    Synchronize selected exercise fields from canonical step-3 exercise definitions.
    This prevents loss of emitted values during later assembly/repair stages.
    """
    if not isinstance(workout_store, dict) or not isinstance(exercise_definitions, dict):
        return workout_store

    fields_to_sync = [
        "notes",
        "intraSetRestInSeconds",
        "exerciseCategory",
        "requiredAccessoryEquipmentIds",
        "exerciseType",
        "equipmentId",
        "bodyWeightPercentage",
        "generateWarmUpSets",
        "minReps",
        "maxReps",
        "progressionMode",
        "requiresLoadCalibration",
    ]

    def sync_one(exercise):
        if not isinstance(exercise, dict):
            return
        ex_id = exercise.get("id")
        if not ex_id or ex_id not in exercise_definitions:
            return
        source = exercise_definitions.get(ex_id)
        if not isinstance(source, dict):
            return
        for field in fields_to_sync:
            if field in ("minReps", "maxReps") and source.get("exerciseType") in ("COUNTDOWN", "COUNTUP"):
                continue
            if field in source:
                value = source[field]
                if field in ("minReps", "maxReps") and value is None:
                    continue
                exercise[field] = copy.deepcopy(value)

    for workout in workout_store.get("workouts", []):
        for component in workout.get("workoutComponents", []):
            ctype = component.get("type")
            if ctype == "Exercise":
                sync_one(component)
            elif ctype == "Superset":
                for ex in component.get("exercises", []):
                    sync_one(ex)

    return workout_store


def sync_exercises_from_plan_index(workout_store, plan_index):
    """
    Synchronize plan-owned exercise fields directly from the canonical PlanIndex.
    This prevents emitted exercise drift from changing structural progression metadata.
    """
    if not isinstance(workout_store, dict) or not isinstance(plan_index, dict):
        return workout_store

    plan_exercise_by_id = {}
    for exercise in plan_index.get("exercises", []):
        if not isinstance(exercise, dict):
            continue
        ex_id = exercise.get("id")
        if ex_id:
            plan_exercise_by_id[ex_id] = exercise

    def sync_one(exercise):
        if not isinstance(exercise, dict):
            return
        ex_id = exercise.get("id")
        if not ex_id:
            return
        source = plan_exercise_by_id.get(ex_id)
        sync_plan_owned_exercise_fields(exercise, source)

    for workout in workout_store.get("workouts", []):
        for component in workout.get("workoutComponents", []):
            ctype = component.get("type")
            if ctype == "Exercise":
                sync_one(component)
            elif ctype == "Superset":
                for ex in component.get("exercises", []):
                    sync_one(ex)

    return workout_store


def sync_plan_owned_exercise_fields(exercise, plan_entry):
    """
    Synchronize exercise fields that are structurally owned by the PlanIndex.

    Explicit plan values, including explicit nulls, must win over later
    normalization or inference passes.
    """
    if not isinstance(exercise, dict) or not isinstance(plan_entry, dict):
        return exercise

    fields_to_sync = [
        "name",
        "nameOverride",
        "notes",
        "generateWarmUpSets",
        "progressionMode",
        "exerciseType",
        "equipmentId",
        "bodyWeightPercentage",
        "muscleGroups",
        "secondaryMuscleGroups",
        "trainingMuscles",
        "intraSetRestInSeconds",
        "exerciseCategory",
        "requiredAccessoryEquipmentIds",
        "minReps",
        "maxReps",
    ]
    for field in fields_to_sync:
        if field in ("minReps", "maxReps") and plan_entry.get("exerciseType") in ("COUNTDOWN", "COUNTUP"):
            continue
        if field in plan_entry:
            value = plan_entry[field]
            if field in ("minReps", "maxReps") and value is None:
                continue
            exercise[field] = copy.deepcopy(value)
    return exercise


def fix_equipment_errors(equipments):
    """Normalize known representations without inventing specifications or removing equipment."""
    fixed = []
    weight_arrays = {
        'WEIGHTVEST': ('availableWeights',),
        'MACHINE': ('availableWeights', 'extraWeights'),
        'DUMBBELL': ('dumbbells', 'extraWeights'),
        'DUMBBELLS': ('dumbbells', 'extraWeights'),
        'BARBELL': ('availablePlates',),
        'PLATELOADEDCABLE': ('availablePlates',),
    }
    for equipment in equipments:
        item = copy.deepcopy(equipment)
        if item.get('type') == 'WEIGHTED_VEST':
            item['type'] = 'WEIGHTVEST'
        if item.get('type') == 'DUMBBELL' and 'dumbbellWeight' in item and 'dumbbells' not in item:
            item['dumbbells'] = [{'weight': item.pop('dumbbellWeight')}]
        for field in weight_arrays.get(item.get('type'), ()):
            if isinstance(item.get(field), list):
                item[field] = [{'weight': value} if isinstance(value, (int, float)) and not isinstance(value, bool)
                               else value for value in item[field]]
        fixed.append(item)
    return fixed


class SchemaRepairError(ValueError):
    """A repair exceeded its permissions or requires authoritative information."""


def validate_schema_repair(original, repaired, validation_errors):
    """Schema repair can change failing representations, never authoritative training facts."""
    if original == repaired:
        raise SchemaRepairError('Schema repair made no change. Required facts remain unresolved; no automatic retry was started.')
    if not isinstance(original, dict):
        raise SchemaRepairError('The source document cannot establish a permitted repair scope. Restore its structure from an authoritative source first.')
    for field in ('equipments', 'accessoryEquipments'):
        before = original.get(field, [])
        after = repaired.get(field, []) if isinstance(repaired, dict) else None
        before = fix_equipment_errors(before) if isinstance(before, list) else before
        after = fix_equipment_errors(after) if isinstance(after, list) else after
        if before != after:
            raise SchemaRepairError(f'Schema repair changed supplied equipment data at /{field}. Only value-preserving normalization is allowed; restore authoritative equipment specifications first.')
    allowed, descendants = build_allowed_patch_scope(validation_errors)
    try:
        validate_changed_paths_scope(collect_changed_json_paths(original, repaired), allowed, descendants)
    except ValueError as error:
        raise SchemaRepairError(str(error)) from error
    # Imported here because plan_contract also uses the domain operations.
    from .plan_contract import LIBRARY_DEFINITION_OWNED_FIELDS
    protected = set(LIBRARY_DEFINITION_OWNED_FIELDS) | {
        'id', 'globalId', 'type', 'libraryDefinitionId', 'exerciseDefinitionId', 'definition_id', 'superset',
        'previousVersionId', 'nextVersionId', 'exerciseIds', 'workoutIds',
        'requirements', 'requirementsId', 'auditTargets', 'workingSetRIR',
        'targetSetPrescriptions', 'workSetTemplate', 'allocationBounds',
    }
    ordered = {'workouts', 'workoutComponents', 'exercises', 'sets', 'exerciseDefinitions'}
    missing = object()

    def check(before, after, path='', field=None):
        if field in ('equipments', 'accessoryEquipments'):
            return  # Compared above using value-preserving equipment normalization.
        if field in protected and before != after:
            raise SchemaRepairError(f'Schema repair cannot change authoritative field {path}. Repair its source instead.')
        if field in ordered and (not isinstance(before, list) or not isinstance(after, list) or len(before) != len(after)):
            raise SchemaRepairError(f'Schema repair cannot add, remove or replace prescribed structure at {path}.')
        if isinstance(before, dict) or isinstance(after, dict):
            old = before if isinstance(before, dict) else {}
            new = after if isinstance(after, dict) else {}
            if (before is not missing and not isinstance(before, dict)) or (after is not missing and not isinstance(after, dict)):
                raise SchemaRepairError(f'Schema repair cannot replace source structure at {path}.')
            for key in old.keys() | new.keys():
                token = key.replace('~', '~0').replace('/', '~1')
                check(old.get(key, missing), new.get(key, missing), path + '/' + token, key)
        elif isinstance(before, list) or isinstance(after, list):
            old = before if isinstance(before, list) else []
            new = after if isinstance(after, list) else []
            if (before is not missing and not isinstance(before, list)) or (after is not missing and not isinstance(after, list)):
                raise SchemaRepairError(f'Schema repair cannot replace source structure at {path}.')
            for index, (old_item, new_item) in enumerate(zip_longest(old, new, fillvalue=missing)):
                check(old_item, new_item, path + '/' + str(index))
        elif isinstance(before, (int, float)) or isinstance(after, (int, float)):
            if type(before) is bool or type(after) is bool:
                same = type(before) is type(after) and before == after
            else:
                try:
                    old, new = Decimal(str(before)), Decimal(str(after))
                    same = old.is_finite() and new.is_finite() and old == new
                except InvalidOperation:
                    same = False
            if not same:
                raise SchemaRepairError(f'Schema repair cannot invent or change a prescribed value at {path}.')
    check(original, repaired)


def save_validation_error(error, workout_json, script_dir=None):
    """
    Save schema validation error and corresponding JSON to a file.
    
    Args:
        error: The validation error object or string
        workout_json: The workout JSON that failed validation
        script_dir: Directory where the script is located (defaults to current directory)
    
    Returns:
        str: Path to the saved error file, or None if saving failed
    """
    try:
        # Determine the base directory (where the script is located)
        if script_dir is None:
            try:
                script_dir = _default_script_dir()
            except (NameError, AttributeError):
                script_dir = os.getcwd()
        
        # Create errors directory if it doesn't exist
        errors_dir = os.path.join(script_dir, "errors")
        os.makedirs(errors_dir, exist_ok=True)
        
        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"validation_error_{timestamp}.json"
        filepath = os.path.join(errors_dir, filename)
        
        # Prepare error data
        error_data = {
            "timestamp": datetime.now().isoformat(),
            "error": str(error),
            "error_type": type(error).__name__,
            "invalid_json": workout_json
        }
        
        # Write error and JSON to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(error_data, f, indent=2, ensure_ascii=False)
        
        return filepath
    except Exception as e:
        print(f"Error saving validation error to file: {e}", file=sys.stderr)
        return None


def get_item_type_label(item_type, path_info, error_path=None):
    """
    Generate a descriptive label for item_type, handling None cases.
    
    Args:
        item_type: The item type (may be None)
        path_info: Parsed path information dict
        error_path: Optional string path for additional context
    
    Returns:
        str: Descriptive label for the item type
    """
    if item_type:
        return item_type
    
    # Handle None item_type with informative labels
    full_path = path_info.get("full_path_parts", [])
    top_level = path_info.get("top_level_array")
    
    if not full_path:
        return "root_level"
    
    # If path exists but doesn't match expected patterns
    if full_path:
        first_part = str(full_path[0]) if full_path else ""
        if first_part and first_part not in ["equipments", "workouts", "accessoryEquipments"]:
            return f"unexpected_path:{first_part}"
        elif top_level:
            return f"{top_level}_unparsed"
    
    # Fallback to path string if available
    if error_path:
        return f"path:{error_path[:50]}"  # Truncate long paths
    
    return "unknown"


def parse_error_path(error_path):
    """
    Parse a jsonschema error path to identify the specific failing item.
    
    Args:
        error_path: Path string (e.g., "equipments.0.name" or "workouts.0.workoutComponents.2.sets.1")
                   or list of path parts from absolute_path
    
    Returns:
        dict: Structured path information with:
            - top_level_array: "equipments", "workouts", "accessoryEquipments", or None
            - array_index: int index in the array, or None
            - nested_path: list of remaining path parts within the item
            - item_type: "equipment", "workout", "accessory", "exercise", "set", "rest", "superset", or None
            - full_path_parts: list of all path parts
    """
    if error_path is None:
        return {
            "top_level_array": None,
            "array_index": None,
            "nested_path": [],
            "item_type": None,
            "full_path_parts": []
        }
    
    # Convert to list if it's a string
    if isinstance(error_path, str):
        path_parts = error_path.split('.')
    else:
        path_parts = list(error_path) if hasattr(error_path, '__iter__') else [str(error_path)]
    
    # Convert numeric strings to integers
    parsed_parts = []
    for part in path_parts:
        if isinstance(part, int):
            parsed_parts.append(part)
        elif part.isdigit():
            parsed_parts.append(int(part))
        else:
            parsed_parts.append(part)
    
    result = {
        "top_level_array": None,
        "array_index": None,
        "nested_path": [],
        "item_type": None,
        "full_path_parts": parsed_parts
    }
    
    if not parsed_parts:
        return result
    
    # Check for equipments array
    if parsed_parts[0] == "equipments" and len(parsed_parts) > 1 and isinstance(parsed_parts[1], int):
        result["top_level_array"] = "equipments"
        result["array_index"] = parsed_parts[1]
        result["nested_path"] = parsed_parts[2:]
        result["item_type"] = "equipment"
        return result
    
    # Check for workouts array
    if parsed_parts[0] == "workouts" and len(parsed_parts) > 1 and isinstance(parsed_parts[1], int):
        result["top_level_array"] = "workouts"
        result["array_index"] = parsed_parts[1]
        result["nested_path"] = parsed_parts[2:]
        
        # Determine item type based on nested path
        if len(parsed_parts) > 2:
            if parsed_parts[2] == "workoutComponents":
                if len(parsed_parts) > 3 and isinstance(parsed_parts[3], int):
                    # Check the component type
                    result["item_type"] = "workout_component"
                    if len(parsed_parts) > 4:
                        if parsed_parts[4] == "exercises":
                            result["item_type"] = "superset_exercise"
                        elif parsed_parts[4] == "sets":
                            result["item_type"] = "set"
                        elif parsed_parts[4] == "type":
                            # We need to check the actual type value, but for now assume exercise
                            result["item_type"] = "exercise"
        else:
            result["item_type"] = "workout"
        
        return result
    
    # Check for accessoryEquipments array
    if parsed_parts[0] == "accessoryEquipments" and len(parsed_parts) > 1 and isinstance(parsed_parts[1], int):
        result["top_level_array"] = "accessoryEquipments"
        result["array_index"] = parsed_parts[1]
        result["nested_path"] = parsed_parts[2:]
        result["item_type"] = "accessory"
        return result
    
    return result


def extract_validation_error_details(validation_error):
    """
    Extract structured details from a jsonschema validation error.
    
    Args:
        validation_error: The validation error exception
        
    Returns:
        dict: Structured error details with message, path, expected, actual, path_info
    """
    error_str = str(validation_error)
    error_type = type(validation_error).__name__
    
    # Try to extract path from jsonschema error
    path = None
    path_parts = None
    expected = None
    actual = None
    
    # Check if it's a jsonschema ValidationError with path information
    if hasattr(validation_error, 'absolute_path'):
        path_parts = list(validation_error.absolute_path)
        if path_parts:
            path = '.'.join(str(p) for p in path_parts)
    
    # Parse the path to get structured information
    path_info = parse_error_path(path_parts if path_parts else path)
    
    # Try to extract constraint information
    if hasattr(validation_error, 'validator'):
        validator = validation_error.validator
        if validator == 'minItems':
            expected = f"array with at least {validation_error.validator_value} items"
        elif validator == 'maxItems':
            expected = f"array with at most {validation_error.validator_value} items"
        elif validator == 'required':
            expected = f"required field: {validation_error.validator_value}"
        elif validator == 'type':
            expected = f"type: {validation_error.validator_value}"
        elif validator == 'enum':
            expected = f"one of: {validation_error.validator_value}"
        elif validator == 'minLength':
            expected = f"string with at least {validation_error.validator_value} characters"
        elif validator == 'minimum':
            expected = f"value >= {validation_error.validator_value}"
        elif validator == 'maximum':
            expected = f"value <= {validation_error.validator_value}"
        else:
            expected = f"constraint: {validator}"
    
    # Try to extract actual value
    if hasattr(validation_error, 'instance'):
        actual = validation_error.instance
    
    return {
        "message": error_str,
        "error_type": error_type,
        "path": path,
        "path_info": path_info,
        "expected": expected,
        "actual": actual
    }


def analyze_and_log_validation_errors(validation_errors, attempt, script_dir=None):
    """
    Analyze validation errors, categorize them, and save detailed logs to file.
    
    Args:
        validation_errors: List of validation error objects or single error
        attempt: Current repair attempt number
        script_dir: Optional directory where script is located (for saving logs)
    
    Returns:
        dict: Analysis summary with categorized error counts and patterns
    """
    # Normalize to list
    if not isinstance(validation_errors, list):
        validation_errors = [validation_errors]
    
    # Extract detailed error information and map to original errors
    detailed_errors = []
    error_to_detail_map = []
    for error in validation_errors:
        error_details = extract_validation_error_details(error)
        # Add validator information if available
        if hasattr(error, 'validator'):
            error_details["validator"] = error.validator
        detailed_errors.append(error_details)
        error_to_detail_map.append((error, error_details))
    
    # Categorize errors by item type
    by_item_type = {}
    by_error_type = {}
    by_validator = {}
    by_field = {}
    
    for orig_error, error_detail in error_to_detail_map:
        # Item type categorization with informative labels
        path_info = error_detail.get("path_info", {})
        raw_item_type = path_info.get("item_type")
        item_type = get_item_type_label(
            raw_item_type, 
            path_info, 
            error_detail.get("path")
        )
        by_item_type[item_type] = by_item_type.get(item_type, 0) + 1
        
        # Error type categorization (from validator)
        validator = None
        if hasattr(orig_error, 'validator'):
            validator = orig_error.validator
        
        if validator:
            by_validator[validator] = by_validator.get(validator, 0) + 1
            # Map validator to error type category
            if validator in ['required']:
                error_category = "required"
            elif validator in ['type']:
                error_category = "type"
            elif validator in ['enum']:
                error_category = "enum"
            elif validator in ['minimum', 'maximum']:
                error_category = validator
            elif validator in ['minLength', 'maxLength']:
                error_category = "length"
            elif validator in ['minItems', 'maxItems']:
                error_category = "array_size"
            else:
                error_category = "other"
            by_error_type[error_category] = by_error_type.get(error_category, 0) + 1
        else:
            # Try to infer from expected field
            expected = str(error_detail.get("expected", "")).lower()
            if "required" in expected:
                error_category = "required"
            elif "type:" in expected:
                error_category = "type"
            elif "one of:" in expected or "enum" in expected:
                error_category = "enum"
            elif ">=" in expected or "minimum" in expected:
                error_category = "minimum"
            elif "<=" in expected or "maximum" in expected:
                error_category = "maximum"
            else:
                error_category = "unknown"
            by_error_type[error_category] = by_error_type.get(error_category, 0) + 1
        
        # Field-level categorization (extract field name from path)
        path = error_detail.get("path", "")
        if path:
            path_parts = path.split('.')
            if path_parts:
                field_name = path_parts[-1]
                by_field[field_name] = by_field.get(field_name, 0) + 1
    
    # Identify common patterns
    common_patterns = []
    
    # Pattern: Missing required fields
    required_errors = [e for e in detailed_errors if "required" in str(e.get("expected", "")).lower()]
    if required_errors:
        required_fields = {}
        for error in required_errors:
            expected = error.get("expected", "")
            if "required field:" in expected:
                field = expected.split("required field:")[-1].strip()
                required_fields[field] = required_fields.get(field, 0) + 1
        for field, count in sorted(required_fields.items(), key=lambda x: x[1], reverse=True)[:5]:
            common_patterns.append(f"{count} items missing '{field}' field")
    
    # Pattern: Invalid values (0, negative, etc.)
    min_errors = [e for e in detailed_errors if "minimum" in str(e.get("expected", "")).lower() or ">=" in str(e.get("expected", ""))]
    if min_errors:
        min_fields = {}
        for error in min_errors:
            path = error.get("path", "")
            if path:
                field = path.split('.')[-1]
                min_fields[field] = min_fields.get(field, 0) + 1
        for field, count in sorted(min_fields.items(), key=lambda x: x[1], reverse=True)[:3]:
            common_patterns.append(f"{count} items have invalid '{field}' value (below minimum)")
    
    # Pattern: Type mismatches
    type_errors = [e for e in detailed_errors if "type:" in str(e.get("expected", "")).lower()]
    if type_errors:
        type_fields = {}
        for error in type_errors:
            path = error.get("path", "")
            if path:
                field = path.split('.')[-1]
                type_fields[field] = type_fields.get(field, 0) + 1
        for field, count in sorted(type_fields.items(), key=lambda x: x[1], reverse=True)[:3]:
            common_patterns.append(f"{count} items have wrong type for '{field}' field")
    
    # Pattern: Enum violations
    enum_errors = [e for e in detailed_errors if "one of:" in str(e.get("expected", "")).lower() or "enum" in str(e.get("expected", "")).lower()]
    if enum_errors:
        enum_fields = {}
        for error in enum_errors:
            path = error.get("path", "")
            if path:
                field = path.split('.')[-1]
                enum_fields[field] = enum_fields.get(field, 0) + 1
        for field, count in sorted(enum_fields.items(), key=lambda x: x[1], reverse=True)[:3]:
            common_patterns.append(f"{count} items have invalid enum value for '{field}' field")
    
    # Build analysis summary
    analysis = {
        "attempt": attempt,
        "timestamp": datetime.now().isoformat(),
        "total_errors": len(detailed_errors),
        "error_summary": {
            "by_item_type": by_item_type,
            "by_error_type": by_error_type,
            "by_validator": by_validator,
            "by_field": dict(sorted(by_field.items(), key=lambda x: x[1], reverse=True)[:10])
        },
        "errors": detailed_errors,
        "common_patterns": common_patterns[:10]  # Top 10 patterns
    }
    
    # Save to file
    log_filepath = None
    if script_dir is not None:
        try:
            errors_dir = os.path.join(script_dir, "errors")
            os.makedirs(errors_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"validation_errors_attempt_{attempt}_{timestamp}.json"
            log_filepath = os.path.join(errors_dir, filename)
            
            with open(log_filepath, 'w', encoding='utf-8') as f:
                json.dump(analysis, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"  Warning: Failed to save error log: {e}", file=sys.stderr)
    
    return analysis, log_filepath


def extract_item_by_path(workout_json, path_info):
    """
    Extract only the specific item identified by the error path from the full workout JSON.
    
    Args:
        workout_json: The complete workout JSON structure
        path_info: Parsed path information from parse_error_path()
    
    Returns:
        dict: Minimal JSON structure containing:
            - item: The extracted item (equipment, exercise, set, etc.)
            - context: Minimal context needed for fixing (e.g., equipment list for exercise validation)
            - path_info: The path information for reassembly
            - item_type: Type of item extracted
    """
    top_level = path_info.get("top_level_array")
    array_index = path_info.get("array_index")
    nested_path = path_info.get("nested_path", [])
    item_type = path_info.get("item_type")
    
    if top_level is None or array_index is None:
        # Cannot extract specific item, return None to indicate fallback needed
        return None
    
    # Get the array
    if top_level not in workout_json:
        return None
    
    array = workout_json[top_level]
    if not isinstance(array, list) or array_index >= len(array):
        return None
    
    # Get the base item
    base_item = array[array_index]
    
    # Navigate nested path to get the actual failing item
    current_item = base_item
    for path_part in nested_path:
        if isinstance(path_part, int):
            if isinstance(current_item, list) and path_part < len(current_item):
                current_item = current_item[path_part]
            else:
                return None
        elif isinstance(path_part, str):
            if isinstance(current_item, dict) and path_part in current_item:
                current_item = current_item[path_part]
            else:
                return None
        else:
            return None
    
    # Build context based on item type
    context = {}
    
    # Determine what item to extract based on the path
    # If nested_path is empty, error is at top level of base_item
    # If nested_path exists, we've navigated to current_item which is the failing item or its parent
    
    if item_type == "equipment":
        # Equipment doesn't need much context
        # If no nested path, error is in the equipment itself
        # If nested path exists, extract the base equipment (the whole equipment object)
        extracted_item = base_item
    elif item_type == "set":
        # Set is nested within an exercise - extract the set itself (current_item after navigation)
        extracted_item = current_item
        context["equipments"] = workout_json.get("equipments", [])
        # Also include parent exercise context if available
        if len(nested_path) > 1:
            # Try to get the exercise that contains this set
            exercise_path = nested_path[:-1]  # Remove the set index
            exercise_item = base_item
            for path_part in exercise_path:
                if isinstance(path_part, int) and isinstance(exercise_item, list) and path_part < len(exercise_item):
                    exercise_item = exercise_item[path_part]
                elif isinstance(path_part, str) and isinstance(exercise_item, dict) and path_part in exercise_item:
                    exercise_item = exercise_item[path_part]
                else:
                    break
            if isinstance(exercise_item, dict):
                context["parent_exercise"] = {
                    "name": exercise_item.get("name"),
                    "exerciseType": exercise_item.get("exerciseType")
                }
    elif item_type == "exercise":
        # Exercise might be nested in workoutComponents or superset
        # Extract the exercise itself
        extracted_item = current_item if nested_path else base_item
        context["equipments"] = workout_json.get("equipments", [])
    elif item_type == "workout":
        # Workout needs equipment list for validating exercises
        extracted_item = base_item
        context["equipments"] = workout_json.get("equipments", [])
    elif item_type == "workout_component":
        # Component needs equipment list and parent workout info
        # If nested_path is empty, it's the component itself
        # If nested_path exists, navigate to get the component
        if nested_path:
            # Navigate to the component
            component_item = base_item
            for path_part in nested_path:
                if isinstance(path_part, int) and isinstance(component_item, list) and path_part < len(component_item):
                    component_item = component_item[path_part]
                elif isinstance(path_part, str) and isinstance(component_item, dict) and path_part in component_item:
                    component_item = component_item[path_part]
                else:
                    component_item = base_item
                    break
            extracted_item = component_item
        else:
            extracted_item = base_item
        context["equipments"] = workout_json.get("equipments", [])
        # Include parent workout metadata for context
        if isinstance(base_item, dict):
            context["workout_metadata"] = {
                "name": base_item.get("name"),
                "description": base_item.get("description")
            }
    elif item_type == "superset_exercise":
        # Superset exercise needs equipment list
        extracted_item = current_item
        context["equipments"] = workout_json.get("equipments", [])
    else:
        # Default: extract the item we found after navigation
        extracted_item = current_item if nested_path else base_item
    
    repair_path = dict(path_info)
    if extracted_item is base_item:
        repair_path['nested_path'] = []
        repair_path['full_path_parts'] = [top_level, array_index]
    return {
        "item": extracted_item,
        "context": context,
        "path_info": repair_path,
        "item_type": item_type,
        "base_item": base_item if item_type in ["workout", "workout_component"] else None
    }


def reassemble_item(workout_json, path_info, fixed_item):
    """
    Reassemble the fixed item back into the full workout JSON structure.
    
    Args:
        workout_json: The original workout JSON structure
        path_info: Parsed path information from parse_error_path()
        fixed_item: The fixed item (could be a full item or just a field value)
    
    Returns:
        dict: Updated workout JSON with the fixed item in place
    """
    import copy
    result = copy.deepcopy(workout_json)
    
    top_level = path_info.get("top_level_array")
    array_index = path_info.get("array_index")
    nested_path = path_info.get("nested_path", [])
    item_type = path_info.get("item_type")
    
    if top_level is None or array_index is None:
        return result
    
    if top_level not in result:
        return result
    
    array = result[top_level]
    if not isinstance(array, list) or array_index >= len(array):
        return result
    
    # Navigate to the item location
    if not nested_path:
        # Error is at the top level of the item - replace entire item
        array[array_index] = fixed_item
    else:
        # Error is nested within the item - need to update specific field
        base_item = array[array_index]
        
        # Build a path list for navigation
        path_parts = [base_item] + nested_path
        
        # Navigate to the parent container
        parent = base_item
        for i, path_part in enumerate(nested_path[:-1]):
            if isinstance(path_part, int):
                if isinstance(parent, list) and path_part < len(parent):
                    parent = parent[path_part]
                else:
                    return result
            elif isinstance(path_part, str):
                if isinstance(parent, dict) and path_part in parent:
                    parent = parent[path_part]
                else:
                    return result
            else:
                return result
        
        # Set the fixed value at the final path
        final_path = nested_path[-1]
        if isinstance(final_path, int):
            if isinstance(parent, list):
                if final_path < len(parent):
                    parent[final_path] = fixed_item
                else:
                    # Extend list if needed
                    while len(parent) <= final_path:
                        parent.append(None)
                    parent[final_path] = fixed_item
        elif isinstance(final_path, str):
            if isinstance(parent, dict):
                parent[final_path] = fixed_item
        else:
            # If the entire item was replaced (e.g., full exercise object), replace at base level
            if item_type in ["exercise", "set", "workout_component", "superset_exercise"]:
                if isinstance(fixed_item, dict):
                    # Replace the entire base item if it's a full object replacement
                    array[array_index] = fixed_item
    
    return result


def build_context_summary(messages, equipment_list, exercise_list):
    """
    Build a concise summary of the generation context for self-healing.
    
    Args:
        messages: Conversation messages
        equipment_list: List of equipment dictionaries
        exercise_list: List of exercise dictionaries
        
    Returns:
        str: Formatted context summary
    """
    summary_parts = []
    
    # Extract workout goals/preferences from conversation
    user_messages = [msg.get("content", "") for msg in messages if msg.get("role") == "user"]
    recent_context = " ".join(user_messages[-3:]) if user_messages else "No specific context"
    
    # Equipment summary
    equipment_types = [eq.get("type", "UNKNOWN") for eq in equipment_list] if equipment_list else []
    equipment_summary = f"Equipment types: {', '.join(set(equipment_types))}" if equipment_types else "No equipment"
    
    # Exercise summary
    exercise_types = [ex.get("exerciseType", "UNKNOWN") for ex in exercise_list] if exercise_list else []
    exercise_names = [ex.get("name", "Unknown") for ex in exercise_list[:5]] if exercise_list else []
    exercise_summary = f"Exercise types: {', '.join(set(exercise_types))}" if exercise_types else "No exercises"
    exercise_names_summary = f"Sample exercises: {', '.join(exercise_names)}" if exercise_names else ""
    
    summary_parts.append(f"Generation Context:")
    summary_parts.append(f"- {equipment_summary}")
    summary_parts.append(f"- {exercise_summary}")
    if exercise_names_summary:
        summary_parts.append(f"- {exercise_names_summary}")
    summary_parts.append(f"- Recent conversation: {recent_context[:200]}...")
    
    return "\n".join(summary_parts)


def EquipmentItem(equipment_dict):
    """
    Normalized EquipmentItem - one of the Equipment types from JSON_SCHEMA.
    Uses placeholder IDs only (EQUIPMENT_X).
    
    Args:
        equipment_dict: Dict matching one of $defs.Equipment* types
    
    Returns:
        dict: Equipment item with placeholder ID
    """
    # Validate it's one of the equipment types
    valid_types = ["BARBELL", "DUMBBELLS", "DUMBBELL", "PLATELOADEDCABLE", "WEIGHTVEST", "MACHINE", "CARDIO_MACHINE", "GENERIC", "ACCESSORY"]
    eq_type = equipment_dict.get("type", "")
    if eq_type not in valid_types:
        raise ValueError(f"Invalid equipment type: {eq_type}")
    
    # Ensure placeholder ID format
    eq_id = equipment_dict.get("id", "")
    if eq_id and not any(eq_id.startswith(prefix) for prefix in ["EQUIPMENT_", "ACCESSORY_", "aaaaaaaa-", "bbbbbbbb-"]):
        # Allow existing UUIDs for now, but new ones should be placeholders
        pass
    
    # Normalize equipment before returning (fixes array formats, type names, structure issues)
    normalized_list = fix_equipment_errors([equipment_dict])
    return normalized_list[0] if normalized_list else equipment_dict


def ExerciseDefinition(exercise_dict):
    """
    Normalized ExerciseDefinition - one $defs.Exercise object.
    Uses placeholder IDs only (EXERCISE_X, SET_X, EQUIPMENT_X).
    
    Args:
        exercise_dict: Dict matching $defs.Exercise
    
    Returns:
        dict: Exercise definition with placeholder IDs
    """
    # Validate it's an Exercise type
    if exercise_dict.get("type") != "Exercise":
        raise ValueError(f"Invalid exercise type: {exercise_dict.get('type')}")
    
    # Ensure placeholder ID format
    ex_id = exercise_dict.get("id", "")
    if ex_id and not any(ex_id.startswith(prefix) for prefix in ["EXERCISE_", "22222222-", "33333333-"]):
        # Allow existing UUIDs for now, but new ones should be placeholders
        pass
    
    # Normalize exercise before returning (fixes exercise types, muscle groups, sets)
    normalized_list = fix_exercise_errors([exercise_dict])
    return normalized_list[0] if normalized_list else exercise_dict


def WorkoutStructure(workout_structure_dict):
    """
    Normalized WorkoutStructure - metadata + workoutComponents.
    Uses placeholder IDs only (WORKOUT_X, EXERCISE_X, COMPONENT_X).
    
    Args:
        workout_structure_dict: Dict matching WORKOUT_STRUCTURE_EXAMPLE format
    
    Returns:
        dict: Workout structure with placeholder IDs
    """
    # Validate structure
    if "workoutMetadata" not in workout_structure_dict:
        raise ValueError("Missing 'workoutMetadata' in workout structure")
    if "workoutComponents" not in workout_structure_dict:
        raise ValueError("Missing 'workoutComponents' in workout structure")
    
    return workout_structure_dict


def _materialize_exercise_definition(exercise_entry):
    """Build an exercise object when its approved PlanIndex has enough data."""
    exercise_id = exercise_entry.get("id")
    exercise_type = exercise_entry.get("exerciseType")
    if exercise_type not in {"WEIGHT", "BODY_WEIGHT", "COUNTDOWN", "COUNTUP", "RUNNING"}:
        raise ValueError(f"Deterministic exercise materialization does not support {exercise_type!r}.")
    if not isinstance(exercise_id, str) or not re.fullmatch(r"EXERCISE_\d+", exercise_id):
        raise ValueError(f"Deterministic exercise materialization requires a canonical EXERCISE_N id; got {exercise_id!r}.")

    required_fields = (
        "name", "equipmentId", "bodyWeightPercentage", "requiredAccessoryEquipmentIds",
        "muscleGroups", "secondaryMuscleGroups", "generateWarmUpSets", "intraSetRestInSeconds",
        "exerciseCategory", "numWorkSets", "restBetweenSetsSeconds",
    )
    missing = [field for field in required_fields if field not in exercise_entry]
    if missing:
        raise ValueError(f"Deterministic exercise materialization for {exercise_id} is missing plan fields: {', '.join(missing)}.")
    count = exercise_entry["numWorkSets"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires positive numWorkSets.")
    rest = exercise_entry["restBetweenSetsSeconds"]
    if not isinstance(rest, int) or isinstance(rest, bool) or rest < 0:
        raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires non-negative restBetweenSetsSeconds.")
    if not isinstance(exercise_entry["generateWarmUpSets"], bool):
        raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires boolean generateWarmUpSets.")
    if not isinstance(exercise_entry["requiredAccessoryEquipmentIds"], list):
        raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires an accessory ID list.")
    if not isinstance(exercise_entry["muscleGroups"], list) or not exercise_entry["muscleGroups"]:
        raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires non-empty library muscle groups.")
    if not isinstance(exercise_entry["secondaryMuscleGroups"], list):
        raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires a secondary muscle group list.")

    set_number = int(exercise_id.removeprefix("EXERCISE_")) * 50
    sets = []

    def append_work_set(work_set):
        sets.append({"id": f"SET_{set_number + len(sets)}", **work_set})

    def append_rest_set():
        sets.append({"id": f"SET_{set_number + len(sets)}", "type": "RestSet", "timeInSeconds": rest, "subCategory": "WorkSet"})

    running_prescription = None
    if exercise_type in {"WEIGHT", "BODY_WEIGHT"}:
        min_reps, max_reps = exercise_entry.get("minReps"), exercise_entry.get("maxReps")
        if not isinstance(min_reps, int) or isinstance(min_reps, bool) or min_reps < 1:
            raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires positive minReps.")
        if not isinstance(max_reps, int) or isinstance(max_reps, bool) or max_reps < min_reps:
            raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires maxReps >= minReps.")
        load_field = "weight" if exercise_type == "WEIGHT" else "additionalWeight"
        prescriptions = exercise_entry.get("targetSetPrescriptions") or None
        if prescriptions is not None:
            if not isinstance(prescriptions, list) or len(prescriptions) != count:
                raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires one targetSetPrescriptions entry per work set.")
            prescriptions = sorted(prescriptions, key=lambda item: item.get("workSetIndex", -1) if isinstance(item, dict) else -1)
            missing_loads = [isinstance(target, dict) and load_field not in target for target in prescriptions]
            supports_load_calibration = exercise_type == "WEIGHT" or (
                exercise_type == "BODY_WEIGHT" and exercise_entry.get("equipmentId") is not None
            )
            if any(missing_loads) and (not all(missing_loads) or not supports_load_calibration
                    or exercise_entry.get("requiresLoadCalibration") is not True):
                raise ValueError(f"Deterministic exercise materialization for {exercise_id} may omit every target load only when native requiresLoadCalibration is enabled.")
            for index, target in enumerate(prescriptions):
                load = target.get(load_field) if isinstance(target, dict) else None
                reps = target.get("reps") if isinstance(target, dict) else None
                if (not isinstance(target, dict) or set(target) - {"workSetIndex", "reps", load_field}
                        or target.get("workSetIndex") != index
                        or not isinstance(reps, int) or isinstance(reps, bool) or not min_reps <= reps <= max_reps
                        or (load_field in target and (not isinstance(load, (int, float)) or isinstance(load, bool) or load < 0))):
                    raise ValueError(f"Deterministic exercise materialization for {exercise_id} has an invalid exact target at work set {index}.")
                append_work_set({"type": "WeightSet" if exercise_type == "WEIGHT" else "BodyWeightSet", "reps": reps, load_field: 0 if load is None else load, "subCategory": "WorkSet"})
                if index < count - 1:
                    append_rest_set()
        else:
            # A zero load is the app's explicit calibration placeholder, not a starting-load guess.
            for index in range(count):
                work_set = {"type": "WeightSet" if exercise_type == "WEIGHT" else "BodyWeightSet", "reps": min_reps, load_field: 0, "subCategory": "WorkSet"}
                append_work_set(work_set)
                if index < count - 1:
                    append_rest_set()
    elif exercise_type in {"COUNTDOWN", "COUNTUP"}:
        timed_targets = exercise_entry.get("timedSetPrescriptions")
        if timed_targets is None:
            duration = exercise_entry.get("timeInMillis")
            if duration is None and isinstance(exercise_entry.get("durationSeconds"), int):
                duration = exercise_entry["durationSeconds"] * 1000
            if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
                raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires timeInMillis or durationSeconds.")
            auto_start = exercise_entry.get("autoStart", True)
            auto_stop = exercise_entry.get("autoStop", duration > 0)
            timed_targets = [{"timeInMillis": duration, "autoStart": auto_start, "autoStop": auto_stop} for _ in range(count)]
        if not isinstance(timed_targets, list) or len(timed_targets) != count:
            raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires one timed prescription per work set.")
        for index, target in enumerate(timed_targets):
            if (not isinstance(target, dict) or not isinstance(target.get("timeInMillis"), int)
                    or set(target) - {"timeInMillis", "autoStart", "autoStop", "targetWeight", "targetDistanceMeters", "targetCalories"}
                    or isinstance(target.get("timeInMillis"), bool) or target["timeInMillis"] < 0
                    or not isinstance(target.get("autoStart"), bool) or not isinstance(target.get("autoStop"), bool)):
                raise ValueError(f"Deterministic exercise materialization for {exercise_id} has an invalid timed target at work set {index}.")
            if target["autoStop"] and target["timeInMillis"] <= 0:
                raise ValueError(f"Deterministic exercise materialization for {exercise_id} cannot auto-stop a zero-duration set.")
            target_weight_fields = ("targetWeight", "targetDistanceMeters", "targetCalories")
            append_work_set({
                "type": "TimedDurationSet" if exercise_type == "COUNTDOWN" else "EnduranceSet",
                **{field: target[field] for field in target_weight_fields if field in target},
                "timeInMillis": target["timeInMillis"],
                "autoStart": target["autoStart"],
                "autoStop": target["autoStop"],
            })
            if index < count - 1:
                append_rest_set()
    else:
        running_prescription = exercise_entry.get("runningPrescription")
        if running_prescription is None and isinstance(exercise_entry.get("targetDistanceMeters"), (int, float)):
            running_prescription = {
                "environment": exercise_entry.get("environment", "OUTDOOR"),
                "targetType": "DISTANCE",
                "targetValue": exercise_entry["targetDistanceMeters"],
            }
        if count != 1 or not isinstance(running_prescription, dict):
            raise ValueError(f"Deterministic exercise materialization for {exercise_id} requires one explicit runningPrescription.")
        append_work_set({"type": "RunningSet"})

    if exercise_entry.get("progressionMode") is not None:
        progression_mode = exercise_entry["progressionMode"]
    else:
        progression_mode = "AUTO_REGULATION" if exercise_type in {"WEIGHT", "BODY_WEIGHT"} else "OFF"
    supports_load_calibration = exercise_type == "WEIGHT" or (
        exercise_type == "BODY_WEIGHT" and exercise_entry.get("equipmentId") is not None
    )
    notes = exercise_entry.get("notes", "")
    item = {
        "id": exercise_id,
        "type": "Exercise",
        "enabled": True,
        "name": exercise_entry["name"],
        "notes": notes,
        "sets": sets,
        "exerciseType": exercise_type,
        "equipmentId": exercise_entry["equipmentId"],
        "bodyWeightPercentage": exercise_entry["bodyWeightPercentage"],
        "generateWarmUpSets": exercise_entry["generateWarmUpSets"],
        "progressionMode": progression_mode,
        "keepScreenOn": False,
        "showCountDownTimer": exercise_type == "COUNTDOWN",
        "intraSetRestInSeconds": exercise_entry["intraSetRestInSeconds"],
        "muscleGroups": copy.deepcopy(exercise_entry["muscleGroups"]),
        "secondaryMuscleGroups": copy.deepcopy(exercise_entry["secondaryMuscleGroups"]),
        "requiredAccessoryEquipmentIds": copy.deepcopy(exercise_entry["requiredAccessoryEquipmentIds"]),
        "requiresLoadCalibration": supports_load_calibration and (
            exercise_entry.get("requiresLoadCalibration") is True or not exercise_entry.get("targetSetPrescriptions")
        ),
        "exerciseCategory": exercise_entry["exerciseCategory"],
    }
    if exercise_type == "RUNNING":
        item["runningPrescription"] = copy.deepcopy(running_prescription)
    if exercise_type in {"WEIGHT", "BODY_WEIGHT"}:
        item["minReps"] = exercise_entry["minReps"]
        item["maxReps"] = exercise_entry["maxReps"]
    return item
