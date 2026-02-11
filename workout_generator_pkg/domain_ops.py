"""Domain operations for workout generation."""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .constants import JSON_SCHEMA, MUSCLE_GROUP_FIXES

try:
    from jsonschema import validate
except Exception:
    validate = None


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
    
    if exercise_type in ["COUNTUP", "COUNTDOWN"]:
        if min_reps != 0 or max_reps != 0:
            return False, f"Exercise '{exercise.get('name', 'Unknown')}' has exerciseType '{exercise_type}' but minReps={min_reps}, maxReps={max_reps}. COUNTUP/COUNTDOWN exercises must have minReps=0 and maxReps=0."
    elif exercise_type in ["WEIGHT", "BODY_WEIGHT"]:
        if min_reps <= 0 or max_reps <= 0:
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
        return False, f"Exercise '{exercise.get('name', 'Unknown')}' has empty muscleGroups array. Every exercise must have at least one primary muscle group."
    
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
    
    if exercise_type not in ["WEIGHT", "BODY_WEIGHT"]:
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
    
    # Calculate valid weight combinations
    valid_combinations = calculate_equipment_weight_combinations(equipment)
    
    if not valid_combinations:
        # No valid combinations (handle gracefully)
        return True, None, []
    
    # Epsilon for floating point comparison
    EPSILON = 0.01
    
    invalid_weights = []
    sets = exercise.get("sets", [])
    
    for set_index, set_item in enumerate(sets):
        set_type = set_item.get("type")
        
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
    
    if invalid_weights:
        # Build error message
        exercise_name = exercise.get("name", "Unknown")
        equipment_name = equipment.get("name", "Unknown")
        invalid_details = []
        for set_idx, weight_val, set_type_name in invalid_weights:
            invalid_details.append(f"Set {set_idx} ({set_type_name}): {weight_val}kg")
        
        # Get sample valid weights for context
        sorted_valid = sorted(valid_combinations)
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
    
    if equipment_id is None or exercise_type not in ["WEIGHT", "BODY_WEIGHT"]:
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
    
    # Calculate valid combinations
    valid_combinations = calculate_equipment_weight_combinations(equipment)
    if not valid_combinations:
        return []
    
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
    
    for set_index, set_item in enumerate(sets):
        set_type = set_item.get("type")
        
        if exercise_type == "WEIGHT" and set_type == "WeightSet":
            weight = set_item.get("weight", 0.0)
            # Check if weight is valid
            is_valid = any(abs(weight - valid_weight) < EPSILON for valid_weight in valid_combinations)
            if not is_valid:
                closest_valid = find_closest_valid_weight(weight)
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
                closest_valid = find_closest_valid_weight(additional_weight)
                if closest_valid is not None:
                    set_item["additionalWeight"] = closest_valid
                    exercise_name = exercise.get("name", "Unknown")
                    fixes_applied.append(
                        f"Exercise '{exercise_name}' Set {set_index}: Fixed additionalWeight from {additional_weight}kg to {closest_valid}kg"
                    )
    
    return fixes_applied


def validate_load_percent_range(exercise):
    """
    Validate that minLoadPercent and maxLoadPercent are reasonable.
    
    Args:
        exercise: Exercise dictionary
        
    Returns:
        tuple: (is_valid, error_message, should_fix)
    """
    exercise_type = exercise.get("exerciseType")
    min_load = exercise.get("minLoadPercent", 0.0)
    max_load = exercise.get("maxLoadPercent", 0.0)
    enable_progression = exercise.get("enableProgression", False)
    
    if not exercise_type:
        return True, None, False
    
    if exercise_type in ["COUNTUP", "COUNTDOWN"]:
        # Can be 0.0 for time-based exercises
        return True, None, False
    
    if exercise_type in ["WEIGHT", "BODY_WEIGHT"]:
        if min_load == 0.0 and max_load == 0.0:
            if enable_progression:
                return False, f"Exercise '{exercise.get('name', 'Unknown')}' has enableProgression=true but minLoadPercent=0.0 and maxLoadPercent=0.0. These are required for double progression.", True
            else:
                # Warn but allow - should still be set correctly
                return True, f"Exercise '{exercise.get('name', 'Unknown')}' has minLoadPercent=0.0 and maxLoadPercent=0.0. Consider setting appropriate values (e.g., 65-85% for hypertrophy).", True
        
        if min_load <= 0 or max_load <= 0:
            return False, f"Exercise '{exercise.get('name', 'Unknown')}' has invalid load percentages: minLoadPercent={min_load}, maxLoadPercent={max_load}. Both must be > 0 for WEIGHT/BODY_WEIGHT exercises.", False
        
        if min_load >= max_load:
            return False, f"Exercise '{exercise.get('name', 'Unknown')}' has minLoadPercent={min_load} >= maxLoadPercent={max_load}. minLoadPercent must be < maxLoadPercent.", False
        
        if min_load < 0 or max_load < 0 or min_load > 100 or max_load > 100:
            return False, f"Exercise '{exercise.get('name', 'Unknown')}' has load percentages outside valid range (0-100): minLoadPercent={min_load}, maxLoadPercent={max_load}.", False
    
    return True, None, False


def finalize_and_validate_exercise_definition(
    exercise_item,
    equipment_subset=None,
    accessory_subset=None,
    all_equipment_candidates=None,
):
    """
    Finalize one emitted exercise and validate it before adding it to exercise_definitions.
    """
    if not isinstance(exercise_item, dict):
        raise ValueError("Exercise definition must be a JSON object")

    normalized_list = fix_exercise_errors([copy.deepcopy(exercise_item)])
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
    if inferred_equipment_id and not exercise.get("equipmentId"):
        exercise["equipmentId"] = inferred_equipment_id

    # Keep calibration flag consistent with effective equipment linkage.
    exercise_type = exercise.get("exerciseType")
    if exercise_type == "WEIGHT" or (exercise_type == "BODY_WEIGHT" and exercise.get("equipmentId") is not None):
        exercise["requiresLoadCalibration"] = True
    elif exercise_type in ("BODY_WEIGHT", "COUNTUP", "COUNTDOWN"):
        exercise["requiresLoadCalibration"] = False

    equipment_ids = {eq.get("id") for eq in merged_equipment if eq.get("id")}
    accessory_ids = {acc.get("id") for acc in accessory_subset if isinstance(acc, dict) and acc.get("id")}
    equipment_by_id = {eq.get("id"): eq for eq in merged_equipment if eq.get("id")}

    # Fix invalid set weights before validating combinations.
    if equipment_by_id:
        fix_equipment_weights(exercise, equipment_by_id)

    validation_errors = []

    checks = [
        validate_exercise_type_consistency(exercise),
        validate_reps_for_exercise_type(exercise),
        validate_muscle_groups(exercise),
        validate_equipment_references(exercise, equipment_ids, accessory_ids),
    ]
    for is_valid, error in checks:
        if not is_valid and error:
            validation_errors.append(error)

    is_valid_weight_combo, weight_combo_error, _ = validate_equipment_weight_combinations(exercise, equipment_by_id)
    if not is_valid_weight_combo and weight_combo_error:
        validation_errors.append(weight_combo_error)

    is_valid_load, load_error, _ = validate_load_percent_range(exercise)
    if not is_valid_load and load_error:
        validation_errors.append(load_error)

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
        sleeve_length = equipment.get("sleeveLength", equipment.get("barLength", 0))
        loading_points = 2  # Two sides
        
        # Generate all plate combinations
        plate_combos = generate_recursive_valid_subsets(
            available_plates,
            is_combination_valid=is_plate_combination_valid
        )
        
        # Calculate weights: each combo weight * loading_points + barWeight
        for combo in plate_combos:
            combo_weight = calculate_combination_weight(list(combo), loading_points)
            base_combinations.add(combo_weight)
        
        # Add barWeight to all combinations (including 0.0 for empty bar)
        base_combinations.add(0.0 + bar_weight)  # Empty bar
        result = {w + bar_weight for w in base_combinations if w > 0}
        result.add(bar_weight)  # Ensure bar weight alone is included
        return result
    
    elif eq_type == "DUMBBELLS":
        available_dumbbells = equipment.get("dumbbells", [])
        extra_weights = equipment.get("extraWeights", [])
        max_extra_per_point = equipment.get("maxExtraWeightsPerLoadingPoint", 0)
        loading_points = 2  # Pair
        
        # Base combinations: each dumbbell weight × 2 (pair)
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
    """
    Fix TimedDurationSet and EnduranceSet to have correct fields.
    These sets require: timeInMillis (not timeInSeconds), autoStart, autoStop
    They do NOT have subCategory.
    
    Args:
        exercise: Exercise dictionary (modified in place)
    """
    sets = exercise.get("sets", [])
    for set_item in sets:
        set_type = set_item.get("type")
        if set_type in ["TimedDurationSet", "EnduranceSet"]:
            # Convert timeInSeconds to timeInMillis if present
            if "timeInSeconds" in set_item:
                time_seconds = set_item.pop("timeInSeconds")
                set_item["timeInMillis"] = int(time_seconds * 1000)
            # Ensure timeInMillis exists (default to 60 seconds if not)
            if "timeInMillis" not in set_item:
                set_item["timeInMillis"] = 60000  # 60 seconds default
            
            # Add required autoStart and autoStop if missing
            if "autoStart" not in set_item:
                set_item["autoStart"] = False  # Default to manual start
            if "autoStop" not in set_item:
                set_item["autoStop"] = False  # Default to manual stop
            
            # Remove subCategory if present (not allowed for these set types)
            if "subCategory" in set_item:
                set_item.pop("subCategory")


def create_placeholder_schema():
    """
    Create a schema variant that allows placeholder IDs instead of strict UUIDs.
    This is identical to JSON_SCHEMA except the UUID pattern is relaxed to accept placeholders.
    
    Returns:
        dict: Schema with placeholder-tolerant UUID pattern
    """
    import copy
    placeholder_schema = copy.deepcopy(JSON_SCHEMA)
    
    # Update UUID pattern to accept placeholders
    # Pattern matches: UUID format OR placeholder format (EQUIPMENT_X, ACCESSORY_X, EXERCISE_X, etc.)
    # EXERCISE_WARMUP and SET_WARMUP are reserved placeholder IDs for the warm-up exercise/set.
    placeholder_schema["$defs"]["UUID"] = {
        "type": "string",
        "pattern": "^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|(?:EQUIPMENT_|ACCESSORY_|EXERCISE_|SET_|WORKOUT_|COMPONENT_|REST_)[0-9]+(?:_GLOBAL)?|EXERCISE_WARMUP|SET_WARMUP)$"
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
            _out("✓ Final UUID-based validation passed")
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


def ensure_requiresLoadCalibration(workout_store):
    """
    Ensure all applicable exercises have requiresLoadCalibration set to True.
    Only sets to True for WEIGHT exercises and BODY_WEIGHT exercises with equipment.
    Sets to False for COUNTUP, COUNTDOWN, and BODY_WEIGHT without equipment.
    
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
        
        if exercise_type == "WEIGHT" or (exercise_type == "BODY_WEIGHT" and equipment_id is not None):
            exercise["requiresLoadCalibration"] = True
        else:
            exercise["requiresLoadCalibration"] = False
    
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


def assemble_placeholder_workout_store(equipment_items, accessory_items, exercise_definitions, workout_structures, plan_index, user_data):
    """
    Assemble emitted objects into a placeholder-based WorkoutStore candidate.
    This assembles the normalized objects (EquipmentItem, AccessoryEquipment, ExerciseDefinition, WorkoutStructure)
    into a single WorkoutStore structure matching JSON_SCHEMA, all using placeholder IDs.
    
    Args:
        equipment_items: Dict mapping equipment_id -> EquipmentItem (weight-loaded equipment)
        accessory_items: Dict mapping accessory_id -> AccessoryEquipment
        exercise_definitions: Dict mapping exercise_id -> ExerciseDefinition
        workout_structures: Dict mapping workout_id -> WorkoutStructure
        plan_index: PlanIndex dict
        user_data: Dict with birthDateYear, weightKg, progressionPercentageAmount, polarDeviceId
    
    Returns:
        dict: Placeholder-based WorkoutStore matching JSON_SCHEMA shape
    """
    # Build equipments array from equipment_items (weight-loaded only)
    equipments = list(equipment_items.values())
    
    # Build accessoryEquipments array from accessory_items
    accessory_equipments = list(accessory_items.values())
    
    # Build workouts array: use plan_index workout order so order field matches user-provided order (0, 1, 2, ...)
    workouts = []
    plan_workouts = plan_index.get("workouts", [])
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

                for ex_id_placeholder in exercise_ids_placeholder:
                    if ex_id_placeholder in exercise_definitions:
                        exercise = exercise_definitions[ex_id_placeholder].copy()
                        fix_muscle_groups_in_exercise(exercise)
                        # Normalize sets (fixes TimedDurationSet/EnduranceSet timeInSeconds -> timeInMillis)
                        if "sets" in exercise:
                            exercise["sets"] = fix_set_errors(exercise["sets"])
                        superset_exercises.append(exercise)
                        # Map the placeholder ID to rest seconds
                        rest_seconds_by_exercise[ex_id_placeholder] = component_spec.get("restSecondsByExercise", {}).get(ex_id_placeholder, 60)

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
            "type": metadata.get("type", 0)
        }
        workouts.append(workout)
    
    # Assemble final placeholder-based WorkoutStore
    placeholder_workout_store = {
        "workouts": workouts,
        "equipments": equipments,
        "accessoryEquipments": accessory_equipments,
        "birthDateYear": user_data.get("birthDateYear", 1990),
        "weightKg": user_data.get("weightKg", 80.0),
        "progressionPercentageAmount": user_data.get("progressionPercentageAmount", 2.5),
        "polarDeviceId": user_data.get("polarDeviceId")
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
        
        # Fix TimedDurationSet and EnduranceSet
        if set_type in ["TimedDurationSet", "EnduranceSet"]:
            # Convert timeInSeconds to timeInMillis if present
            if "timeInSeconds" in s_copy:
                time_seconds = s_copy.pop("timeInSeconds")
                s_copy["timeInMillis"] = int(time_seconds * 1000)
            # Ensure timeInMillis exists (default to 60 seconds if not)
            if "timeInMillis" not in s_copy:
                s_copy["timeInMillis"] = 60000  # 60 seconds default
            
            # Add required autoStart and autoStop if missing
            if "autoStart" not in s_copy:
                s_copy["autoStart"] = False  # Default to manual start
            if "autoStop" not in s_copy:
                s_copy["autoStop"] = False  # Default to manual stop
            
            # Remove subCategory if present (not allowed for these set types)
            if "subCategory" in s_copy:
                s_copy.pop("subCategory")
        
        # Fix invalid set types
        if set_type == "DistanceSet":
            # Convert DistanceSet to EnduranceSet or TimedDurationSet
            # For now, convert to EnduranceSet with estimated time
            distance = s_copy.get("distance", 50.0)
            # Rough estimate: 1 meter per second walking pace
            estimated_time_ms = int(distance * 1000)  # Convert to milliseconds
            s_copy = {
                "id": s_copy.get("id"),
                "type": "EnduranceSet",
                "timeInMillis": estimated_time_ms,
                "autoStart": True,
                "autoStop": True
            }
        
        fixed.append(s_copy)
    return fixed


def fix_exercise_errors(exercises):
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
        valid_exercise_types = ["COUNTUP", "BODY_WEIGHT", "COUNTDOWN", "WEIGHT"]
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
        
        # Set requiresLoadCalibration to True for WEIGHT exercises and BODY_WEIGHT with equipment
        exercise_type = ex_copy.get("exerciseType")
        equipment_id = ex_copy.get("equipmentId")
        if exercise_type == "WEIGHT" or (exercise_type == "BODY_WEIGHT" and equipment_id is not None):
            ex_copy["requiresLoadCalibration"] = True
        else:
            ex_copy["requiresLoadCalibration"] = False
        
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
        "intraSetRestInSeconds",
        "exerciseCategory",
        "requiredAccessoryEquipmentIds",
        "exerciseType",
        "equipmentId",
        "bodyWeightPercentage",
        "minReps",
        "maxReps",
        "minLoadPercent",
        "maxLoadPercent",
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
            if field in source:
                exercise[field] = copy.deepcopy(source[field])

    for workout in workout_store.get("workouts", []):
        for component in workout.get("workoutComponents", []):
            ctype = component.get("type")
            if ctype == "Exercise":
                sync_one(component)
            elif ctype == "Superset":
                for ex in component.get("exercises", []):
                    sync_one(ex)

    return workout_store


def fix_equipment_errors(equipments):
    """
    Fix common equipment type errors and structure issues.
    
    Args:
        equipments: List of equipment dictionaries
    
    Returns:
        List of fixed equipment dictionaries
    """
    fixed = []
    for eq in equipments:
        eq_copy = eq.copy()
        eq_type = eq_copy.get("type", "").upper()
        
        # Fix common type name errors
        if eq_type == "WEIGHTED_VEST":
            eq_copy["type"] = "WEIGHTVEST"
        elif eq_type in ["BENCH", "PULL_UP_BAR", "PULLUP_BAR", "PULLUPBAR", "GENERIC"]:
            # Remove unsupported types (including GENERIC which is no longer supported)
            continue
        elif eq_type == "DUMBBELL":
            # Fix incorrect DUMBBELL structure - ensure all required fields
            if "dumbbellWeight" in eq_copy:
                weight = eq_copy.pop("dumbbellWeight", 5.0)
                if "dumbbells" not in eq_copy:
                    eq_copy["dumbbells"] = [{"weight": weight}]
            # Ensure required fields exist
            if "dumbbells" not in eq_copy:
                eq_copy["dumbbells"] = [{"weight": 5.0}]
            if "maxExtraWeightsPerLoadingPoint" not in eq_copy:
                eq_copy["maxExtraWeightsPerLoadingPoint"] = 0
            if "extraWeights" not in eq_copy:
                eq_copy["extraWeights"] = []
        
        # Fix WEIGHTVEST structure - convert maxWeight to availableWeights if needed
        if eq_copy.get("type") == "WEIGHTVEST":
            if "maxWeight" in eq_copy and "availableWeights" not in eq_copy:
                max_weight = eq_copy.pop("maxWeight")
                # Create available weights array (e.g., 5, 10, 15, 20 if maxWeight is 20)
                available_weights = []
                if max_weight > 0:
                    # Generate common weight increments
                    for w in [5.0, 10.0, 15.0, 20.0, 25.0]:
                        if w <= max_weight:
                            available_weights.append({"weight": w})
                    if not available_weights:
                        available_weights.append({"weight": max_weight})
                eq_copy["availableWeights"] = available_weights
        
        # Fix number arrays to object arrays for all equipment types
        # Helper function to convert number array to object array
        def fix_number_array_to_objects(arr, default_thickness=None):
            """Convert array of numbers to array of objects with weight property."""
            if not isinstance(arr, list) or len(arr) == 0:
                return arr
            # Check if first element is a number (not already an object)
            if len(arr) > 0 and isinstance(arr[0], (int, float)) and not isinstance(arr[0], dict):
                fixed_arr = []
                for item in arr:
                    if isinstance(item, (int, float)):
                        obj = {"weight": float(item)}
                        if default_thickness is not None:
                            obj["thickness"] = default_thickness
                        fixed_arr.append(obj)
                    else:
                        fixed_arr.append(item)
                return fixed_arr
            return arr
        
        # Fix arrays based on equipment type
        if eq_type == "WEIGHTVEST":
            if "availableWeights" in eq_copy:
                eq_copy["availableWeights"] = fix_number_array_to_objects(eq_copy["availableWeights"])
        elif eq_type == "MACHINE":
            if "availableWeights" in eq_copy:
                eq_copy["availableWeights"] = fix_number_array_to_objects(eq_copy["availableWeights"])
            if "extraWeights" in eq_copy:
                eq_copy["extraWeights"] = fix_number_array_to_objects(eq_copy["extraWeights"])
        elif eq_type in ["DUMBBELLS", "DUMBBELL"]:
            if "dumbbells" in eq_copy:
                eq_copy["dumbbells"] = fix_number_array_to_objects(eq_copy["dumbbells"])
            if "extraWeights" in eq_copy:
                eq_copy["extraWeights"] = fix_number_array_to_objects(eq_copy["extraWeights"])
        elif eq_type in ["BARBELL", "PLATELOADEDCABLE"]:
            if "availablePlates" in eq_copy:
                # For plates, we need weight and thickness, so use a default thickness if converting
                arr = eq_copy["availablePlates"]
                if isinstance(arr, list) and len(arr) > 0:
                    # Check if first element is just a number (needs both weight and thickness)
                    if isinstance(arr[0], (int, float)) and not isinstance(arr[0], dict):
                        fixed_arr = []
                        for item in arr:
                            if isinstance(item, (int, float)):
                                # Default thickness: 20mm for plates (reasonable default)
                                fixed_arr.append({"weight": float(item), "thickness": 20.0})
                            else:
                                fixed_arr.append(item)
                        eq_copy["availablePlates"] = fixed_arr
                    # Also check if objects are missing thickness
                    elif isinstance(arr[0], dict):
                        fixed_arr = []
                        for item in arr:
                            if isinstance(item, dict):
                                if "weight" in item and "thickness" not in item:
                                    # Add default thickness if missing
                                    item_copy = item.copy()
                                    item_copy["thickness"] = 20.0
                                    fixed_arr.append(item_copy)
                                else:
                                    fixed_arr.append(item)
                            else:
                                fixed_arr.append(item)
                        eq_copy["availablePlates"] = fixed_arr
        
        fixed.append(eq_copy)
    
    return fixed


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
    
    return {
        "item": extracted_item,
        "context": context,
        "path_info": path_info,
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
    valid_types = ["BARBELL", "DUMBBELLS", "DUMBBELL", "PLATELOADEDCABLE", "WEIGHTVEST", "MACHINE", "ACCESSORY"]
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


