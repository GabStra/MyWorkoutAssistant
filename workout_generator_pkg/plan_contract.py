"""Plan contract validation for generation stages."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Tuple

from .domain_ops import get_selectable_weights_for_exercise


class ContractValidationError(ValueError):
    """Raised when stage artifacts violate the canonical plan contract."""


@dataclass(frozen=True)
class ContractIssue:
    code: str
    message: str


CANONICAL_PLAN_ID_PATTERNS = {
    "equipment": re.compile(r"^EQUIPMENT_\d+$"),
    "accessory": re.compile(r"^ACCESSORY_\d+$"),
    "exercise": re.compile(r"^EXERCISE_\d+$"),
    "workout": re.compile(r"^WORKOUT_\d+$"),
    "set": re.compile(r"^SET_\d+$"),
}


def _is_canonical_plan_placeholder(value: Any, kind: str) -> bool:
    if not isinstance(value, str):
        return False
    if kind == "exercise" and value == "EXERCISE_WARMUP":
        return True
    if kind == "set" and value == "SET_WARMUP":
        return True
    pattern = CANONICAL_PLAN_ID_PATTERNS[kind]
    return bool(pattern.match(value))


def _has_percentage_semantics(body_weight_percentage: Any) -> bool:
    if not isinstance(body_weight_percentage, (int, float)):
        return False
    if body_weight_percentage <= 0:
        return False
    # The runtime consumes this field as a percent, not a unit fraction.
    # Values like 1.0 silently become 1% bodyweight instead of 100%.
    return body_weight_percentage > 1.0


def _work_set_type_for_exercise_type(exercise_type: str) -> Optional[str]:
    mapping = {
        "WEIGHT": "WeightSet",
        "BODY_WEIGHT": "BodyWeightSet",
        "COUNTDOWN": "TimedDurationSet",
        "COUNTUP": "EnduranceSet",
    }
    return mapping.get(exercise_type)


def _load_field_for_exercise_type(exercise_type: str) -> Optional[str]:
    mapping = {
        "WEIGHT": "weight",
        "BODY_WEIGHT": "additionalWeight",
    }
    return mapping.get(exercise_type)


def _equipment_ids_matching_bodyweight_targets(
    equipment_lookup: Dict[str, Dict[str, Any]],
    target_set_prescriptions: Any,
) -> List[str]:
    if not isinstance(target_set_prescriptions, list) or not target_set_prescriptions:
        return []
    positive_additional_loads = {
        float(item.get("additionalWeight"))
        for item in target_set_prescriptions
        if isinstance(item, dict)
        and isinstance(item.get("additionalWeight"), (int, float))
        and float(item.get("additionalWeight")) > 0
    }
    if not positive_additional_loads:
        return []

    matching_ids: List[str] = []
    for equipment_id, equipment in equipment_lookup.items():
        if not isinstance(equipment, dict):
            continue
        selectable = get_selectable_weights_for_exercise("BODY_WEIGHT", equipment)
        if positive_additional_loads.issubset(selectable):
            matching_ids.append(equipment_id)
    return sorted(matching_ids)


def _alternate_load_field(expected_load_field: str) -> Optional[str]:
    mapping = {
        "weight": "additionalWeight",
        "additionalWeight": "weight",
    }
    return mapping.get(expected_load_field)


def _normalize_target_set_prescriptions(
    target_set_prescriptions: Any,
    ex_name: str,
    expected_load_field: str,
) -> Tuple[List[Dict[str, Any]], List[ContractIssue]]:
    issues: List[ContractIssue] = []
    normalized_items: List[Dict[str, Any]] = []
    seen_indexes: set[int] = set()

    for idx, item in enumerate(target_set_prescriptions):
        if not isinstance(item, dict):
            issues.append(
                ContractIssue(
                    "invalid_target_set_prescription_item",
                    f"Exercise '{ex_name}' targetSetPrescriptions[{idx}] is not an object.",
                )
            )
            continue

        work_set_index = item.get("workSetIndex")
        reps = item.get("reps")
        load_value = item.get(expected_load_field)
        alternate_load_field = _alternate_load_field(expected_load_field)
        alternate_load_value = item.get(alternate_load_field) if alternate_load_field else None
        item_is_valid = True

        if not isinstance(work_set_index, int) or work_set_index < 0:
            issues.append(
                ContractIssue(
                    "invalid_target_set_prescription_work_set_index",
                    f"Exercise '{ex_name}' targetSetPrescriptions[{idx}] is missing non-negative integer workSetIndex.",
                )
            )
            item_is_valid = False
        elif work_set_index in seen_indexes:
            issues.append(
                ContractIssue(
                    "duplicate_target_set_prescription_work_set_index",
                    f"Exercise '{ex_name}' targetSetPrescriptions reuses workSetIndex={work_set_index}.",
                )
            )
            item_is_valid = False
        else:
            seen_indexes.add(work_set_index)

        if not isinstance(reps, int):
            issues.append(
                ContractIssue(
                    "invalid_target_set_prescription_reps",
                    f"Exercise '{ex_name}' targetSetPrescriptions[{idx}] is missing integer reps.",
                )
            )
            item_is_valid = False

        if not isinstance(load_value, (int, float)):
            if isinstance(alternate_load_value, (int, float)):
                issues.append(
                    ContractIssue(
                        "mismatched_target_set_prescription_load_field",
                        f"Exercise '{ex_name}' targetSetPrescriptions[{idx}] uses {alternate_load_field}, which does not match this exerciseType. Expected {expected_load_field} instead.",
                    )
                )
            else:
                issues.append(
                    ContractIssue(
                        "invalid_target_set_prescription_load",
                        f"Exercise '{ex_name}' targetSetPrescriptions[{idx}] is missing numeric {expected_load_field}.",
                    )
                )

            item_is_valid = False

        if item_is_valid:
            normalized_items.append(item)

    if normalized_items:
        sorted_indexes = sorted(item["workSetIndex"] for item in normalized_items)
        expected_indexes = list(range(len(normalized_items)))
        if sorted_indexes != expected_indexes:
            issues.append(
                ContractIssue(
                    "non_contiguous_target_set_prescription_work_set_indexes",
                    f"Exercise '{ex_name}' targetSetPrescriptions workSetIndex values must be contiguous 0-based indexes; got {sorted_indexes}.",
                )
            )

    return normalized_items, issues


def _format_contract_weight(value: float) -> str:
    if float(value).is_integer():
        return f"{float(value):.1f}"
    return f"{float(value):g}"


def _build_equipment_lookup(
    plan_index: Dict[str, Any],
    provided_equipment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    equipment_lookup: Dict[str, Dict[str, Any]] = {}

    if isinstance(provided_equipment, dict):
        for eq in provided_equipment.get("equipments", []) or []:
            if isinstance(eq, dict) and eq.get("id"):
                equipment_lookup[eq["id"]] = eq

    for eq in plan_index.get("equipments", []) or []:
        if isinstance(eq, dict) and eq.get("id") and eq["id"] not in equipment_lookup:
            equipment_lookup[eq["id"]] = eq

    return equipment_lookup


def _collect_contract_issues_plan_index(
    plan_index: Dict[str, Any],
    provided_equipment: Optional[Dict[str, Any]] = None,
) -> List[ContractIssue]:
    issues: List[ContractIssue] = []
    equipment_lookup = _build_equipment_lookup(plan_index, provided_equipment)

    plan_name = plan_index.get("planName")
    if not isinstance(plan_name, str) or not plan_name.strip():
        issues.append(ContractIssue("missing_plan_name", "PlanIndex is missing a non-empty planName."))

    exercises = plan_index.get("exercises", []) or []
    workouts = plan_index.get("workouts", []) or []

    for eq in plan_index.get("equipments", []) or []:
        if isinstance(eq, dict) and eq.get("id") and not _is_canonical_plan_placeholder(eq.get("id"), "equipment"):
            issues.append(
                ContractIssue("invalid_equipment_placeholder", f"Equipment id '{eq.get('id')}' is not a canonical EQUIPMENT_<number> placeholder.")
            )

    for acc in plan_index.get("accessoryEquipments", []) or []:
        if isinstance(acc, dict) and acc.get("id") and not _is_canonical_plan_placeholder(acc.get("id"), "accessory"):
            issues.append(
                ContractIssue("invalid_accessory_placeholder", f"Accessory id '{acc.get('id')}' is not a canonical ACCESSORY_<number> placeholder.")
            )

    exercise_ids: List[str] = [ex.get("id") for ex in exercises if isinstance(ex, dict) and ex.get("id")]
    if len(exercise_ids) != len(set(exercise_ids)):
        issues.append(ContractIssue("duplicate_exercise_ids", "PlanIndex has duplicate exercise IDs."))

    exercise_id_set = set(exercise_ids)

    for ex in exercises:
        if not isinstance(ex, dict):
            issues.append(ContractIssue("invalid_exercise_entry", "PlanIndex contains a non-object exercise entry."))
            continue

        ex_id = ex.get("id")
        ex_name = ex.get("name", "Unknown")
        ex_type = ex.get("exerciseType")
        if not ex_id:
            issues.append(ContractIssue("missing_exercise_id", f"Exercise '{ex_name}' is missing id."))
        elif not _is_canonical_plan_placeholder(ex_id, "exercise"):
            issues.append(
                ContractIssue("invalid_exercise_placeholder", f"Exercise id '{ex_id}' is not a canonical EXERCISE_<number> placeholder.")
            )
        if not ex_type:
            issues.append(ContractIssue("missing_exercise_type", f"Exercise '{ex_name}' is missing exerciseType."))
        if not ex.get("name"):
            issues.append(ContractIssue("missing_exercise_name", f"Exercise '{ex_id or 'Unknown'}' is missing name."))
        equipment_id = ex.get("equipmentId")
        if equipment_id is not None and not _is_canonical_plan_placeholder(equipment_id, "equipment"):
            issues.append(
                ContractIssue("invalid_equipment_reference", f"Exercise '{ex_id or ex_name}' references non-canonical equipmentId '{equipment_id}'.")
            )
        if ex_type == "BODY_WEIGHT":
            body_weight_percentage = ex.get("bodyWeightPercentage")
            if not _has_percentage_semantics(body_weight_percentage):
                issues.append(
                    ContractIssue(
                        "missing_plan_body_weight_percentage",
                        f"Exercise '{ex_name}' must include a positive numeric bodyWeightPercentage in percentage form in the PlanIndex for BODY_WEIGHT exercises (for example 100.0, not 1.0).",
                    )
                )
            matching_equipment_ids = _equipment_ids_matching_bodyweight_targets(
                equipment_lookup,
                ex.get("targetSetPrescriptions"),
            )
            if matching_equipment_ids and equipment_id is None:
                issues.append(
                    ContractIssue(
                        "missing_plan_bodyweight_equipment_id",
                        f"Exercise '{ex_name}' has positive BODY_WEIGHT additionalWeight targets that match load-bearing equipment {matching_equipment_ids}; set equipmentId to the correct primary load-bearing equipment instead of null.",
                    )
                )
            elif equipment_id is not None and matching_equipment_ids and equipment_id not in matching_equipment_ids:
                issues.append(
                    ContractIssue(
                        "bodyweight_equipment_id_target_mismatch",
                        f"Exercise '{ex_name}' equipmentId '{equipment_id}' does not match BODY_WEIGHT additionalWeight targets; expected one of {matching_equipment_ids}.",
                    )
                )
        elif ex_type in ("WEIGHT", "COUNTUP", "COUNTDOWN"):
            if ex.get("bodyWeightPercentage") is not None:
                issues.append(
                    ContractIssue(
                        "unexpected_plan_body_weight_percentage",
                        f"Exercise '{ex_name}' must set bodyWeightPercentage to null in the PlanIndex for non-BODY_WEIGHT exercises.",
                    )
                )
        for acc_id in ex.get("requiredAccessoryEquipmentIds") or []:
            if not _is_canonical_plan_placeholder(acc_id, "accessory"):
                issues.append(
                    ContractIssue("invalid_accessory_reference", f"Exercise '{ex_id or ex_name}' references non-canonical accessory id '{acc_id}'.")
                )

        if ex_type not in ("COUNTDOWN", "COUNTUP"):
            min_reps = ex.get("minReps")
            max_reps = ex.get("maxReps")
            if min_reps is not None and max_reps is not None and min_reps > max_reps:
                issues.append(
                    ContractIssue(
                        "invalid_rep_range",
                        f"Exercise '{ex_name}' has minReps={min_reps} greater than maxReps={max_reps}.",
                    )
                )

        target_set_prescriptions = ex.get("targetSetPrescriptions")
        expected_load_field = _load_field_for_exercise_type(ex_type)
        if target_set_prescriptions in (None, []):
            target_set_prescriptions = None
        if target_set_prescriptions is not None:
            if not isinstance(target_set_prescriptions, list):
                issues.append(
                    ContractIssue(
                        "invalid_target_set_prescriptions",
                        f"Exercise '{ex_name}' has invalid targetSetPrescriptions; expected a list of indexed work-set targets.",
                    )
                )
            elif expected_load_field is None:
                issues.append(
                    ContractIssue(
                        "unsupported_target_set_prescriptions",
                        f"Exercise '{ex_name}' uses targetSetPrescriptions but exerciseType '{ex_type}' does not support load targets.",
                    )
                )
            else:
                normalized_targets, target_issues = _normalize_target_set_prescriptions(
                    target_set_prescriptions,
                    ex_name,
                    expected_load_field,
                )
                issues.extend(target_issues)

                expected_work_sets = ex.get("numWorkSets")
                if isinstance(expected_work_sets, int) and len(target_set_prescriptions) != expected_work_sets:
                    issues.append(
                        ContractIssue(
                            "target_set_prescription_count_mismatch",
                            f"Exercise '{ex_name}' has {len(target_set_prescriptions)} targetSetPrescriptions but numWorkSets={expected_work_sets}.",
                        )
                    )

                equipment = equipment_lookup.get(equipment_id) if equipment_id else None
                if equipment and isinstance(equipment.get("type"), str):
                    selectable_weights = get_selectable_weights_for_exercise(ex_type, equipment)
                    if selectable_weights:
                        equipment_name = equipment.get("name", equipment_id)
                        equipment_type = equipment.get("type")
                        for idx, item in enumerate(normalized_targets):
                            target_load = float(item[expected_load_field])
                            if target_load in selectable_weights:
                                continue
                            nearest = min(selectable_weights, key=lambda val: abs(val - target_load))
                            issues.append(
                                ContractIssue(
                                    "unselectable_target_set_prescription_load",
                                    f"Exercise '{ex_name}' targetSetPrescriptions[{idx}] {expected_load_field}={_format_contract_weight(target_load)} "
                                    f"is not selectable for equipment '{equipment_name}' ({equipment_type}); nearest selectable "
                                    f"{expected_load_field} is {_format_contract_weight(nearest)}.",
                                )
                            )

    workout_ids: List[str] = [wo.get("id") for wo in workouts if isinstance(wo, dict) and wo.get("id")]
    if len(workout_ids) != len(set(workout_ids)):
        issues.append(ContractIssue("duplicate_workout_ids", "PlanIndex has duplicate workout IDs."))

    for wo in workouts:
        if not isinstance(wo, dict):
            issues.append(ContractIssue("invalid_workout_entry", "PlanIndex contains a non-object workout entry."))
            continue

        wo_name = wo.get("name", "Unknown")
        wo_id = wo.get("id")
        exercise_ids_in_workout = wo.get("exerciseIds", []) or []
        rest_to_next = wo.get("restToNextSeconds")
        superset_groups = wo.get("supersetGroups")

        if not wo_id:
            issues.append(ContractIssue("missing_workout_id", f"Workout '{wo_name}' is missing id."))
        elif not _is_canonical_plan_placeholder(wo_id, "workout"):
            issues.append(
                ContractIssue("invalid_workout_placeholder", f"Workout id '{wo_id}' is not a canonical WORKOUT_<number> placeholder.")
            )

        for ex_id in exercise_ids_in_workout:
            if not _is_canonical_plan_placeholder(ex_id, "exercise"):
                issues.append(
                    ContractIssue("invalid_workout_exercise_placeholder", f"Workout '{wo_name}' references non-canonical exercise id '{ex_id}'.")
                )
            if ex_id not in exercise_id_set:
                issues.append(
                    ContractIssue(
                        "workout_references_unknown_exercise",
                        f"Workout '{wo_name}' references unknown exercise id '{ex_id}'.",
                    )
                )

        if isinstance(rest_to_next, list) and len(rest_to_next) != len(exercise_ids_in_workout):
            issues.append(
                ContractIssue(
                    "rest_to_next_length_mismatch",
                    f"Workout '{wo_name}' has restToNextSeconds length {len(rest_to_next)} but exerciseIds length {len(exercise_ids_in_workout)}.",
                )
            )

        normalized_superset_groups, superset_issues = _normalize_superset_groups(
            superset_groups,
            wo_name,
            exercise_id_set,
        )
        issues.extend(superset_issues)
        for group in normalized_superset_groups:
            start_idx = _find_subsequence(exercise_ids_in_workout, group)
            if start_idx is None:
                issues.append(
                    ContractIssue(
                        "non_contiguous_superset_group",
                        f"Workout '{wo_name}' superset group {group} must appear as a contiguous subsequence of exerciseIds.",
                    )
                )

    return issues


def validate_plan_index_contract(
    plan_index: Dict[str, Any],
    provided_equipment: Optional[Dict[str, Any]] = None,
) -> None:
    issues = _collect_contract_issues_plan_index(plan_index, provided_equipment)
    if issues:
        lines = [f"- [{it.code}] {it.message}" for it in issues]
        raise ContractValidationError("Plan contract validation failed at Step 1:\n" + "\n".join(lines))


def _count_work_sets(exercise: Dict[str, Any]) -> Tuple[int, List[int]]:
    exercise_type = exercise.get("exerciseType")
    if exercise_type in ("COUNTDOWN", "COUNTUP"):
        return 0, []
    target_set_type = _work_set_type_for_exercise_type(exercise_type)
    sets = exercise.get("sets", []) or []

    if target_set_type is None:
        return 0, []

    work_count = 0
    rest_durations: List[int] = []

    for set_item in sets:
        if not isinstance(set_item, dict):
            continue
        set_type = set_item.get("type")
        if set_type == target_set_type:
            work_count += 1
        elif set_type == "RestSet":
            time_s = set_item.get("timeInSeconds")
            if isinstance(time_s, int):
                rest_durations.append(time_s)

    return work_count, rest_durations


def _normalize_superset_groups(
    superset_groups: Any,
    wo_name: str,
    exercise_id_set: set[str],
) -> Tuple[List[List[str]], List[ContractIssue]]:
    issues: List[ContractIssue] = []
    normalized_groups: List[List[str]] = []
    seen_members: set[str] = set()

    if superset_groups in (None, []):
        return normalized_groups, issues

    if not isinstance(superset_groups, list):
        issues.append(
            ContractIssue(
                "invalid_superset_groups",
                f"Workout '{wo_name}' supersetGroups must be a list when present.",
            )
        )
        return normalized_groups, issues

    for idx, group in enumerate(superset_groups):
        if not isinstance(group, dict):
            issues.append(
                ContractIssue(
                    "invalid_superset_group_entry",
                    f"Workout '{wo_name}' supersetGroups[{idx}] must be an object with exerciseIds.",
                )
            )
            continue
        exercise_ids = group.get("exerciseIds")
        if not isinstance(exercise_ids, list) or len(exercise_ids) < 2:
            issues.append(
                ContractIssue(
                    "invalid_superset_group_size",
                    f"Workout '{wo_name}' supersetGroups[{idx}] must contain at least two exerciseIds.",
                )
            )
            continue

        normalized_group: List[str] = []
        for member in exercise_ids:
            if not _is_canonical_plan_placeholder(member, "exercise"):
                issues.append(
                    ContractIssue(
                        "invalid_superset_group_exercise_placeholder",
                        f"Workout '{wo_name}' supersetGroups[{idx}] contains non-canonical exercise id '{member}'.",
                    )
                )
                continue
            if member not in exercise_id_set:
                issues.append(
                    ContractIssue(
                        "superset_group_references_unknown_exercise",
                        f"Workout '{wo_name}' supersetGroups[{idx}] references unknown exercise id '{member}'.",
                    )
                )
                continue
            if member in seen_members:
                issues.append(
                    ContractIssue(
                        "duplicate_superset_group_member",
                        f"Workout '{wo_name}' supersetGroups reuses exercise id '{member}' across groups.",
                    )
                )
                continue
            seen_members.add(member)
            normalized_group.append(member)

        if len(normalized_group) >= 2:
            normalized_groups.append(normalized_group)

    return normalized_groups, issues


def _find_subsequence(sequence: List[str], subsequence: List[str]) -> Optional[int]:
    if not subsequence or len(subsequence) > len(sequence):
        return None
    limit = len(sequence) - len(subsequence) + 1
    for start in range(limit):
        if sequence[start:start + len(subsequence)] == subsequence:
            return start
    return None


def validate_exercise_definitions_contract(plan_index: Dict[str, Any], exercise_definitions: Dict[str, Dict[str, Any]]) -> None:
    issues: List[ContractIssue] = []

    plan_exercises = [ex for ex in (plan_index.get("exercises", []) or []) if isinstance(ex, dict)]

    for plan_ex in plan_exercises:
        ex_id = plan_ex.get("id")
        if not ex_id:
            continue

        actual = exercise_definitions.get(ex_id)
        if not isinstance(actual, dict):
            issues.append(ContractIssue("missing_exercise_definition", f"Missing emitted exercise definition for '{ex_id}'."))
            continue

        issues.extend(_collect_contract_issues_for_exercise(plan_ex, actual))

    if issues:
        lines = [f"- [{it.code}] {it.message}" for it in issues]
        raise ContractValidationError("Plan contract validation failed at Step 3:\n" + "\n".join(lines))


def _collect_contract_issues_for_exercise(plan_ex: Dict[str, Any], actual: Dict[str, Any]) -> List[ContractIssue]:
    issues: List[ContractIssue] = []
    ex_id = plan_ex.get("id")
    if not ex_id:
        return issues

    actual_id = actual.get("id")
    if actual_id != ex_id:
        issues.append(
            ContractIssue(
                "exercise_id_mismatch",
                f"Exercise '{ex_id}' emitted object id '{actual_id}' instead of the required '{ex_id}'.",
            )
        )

    plan_name = plan_ex.get("name")
    actual_name = actual.get("name")

    plan_type = plan_ex.get("exerciseType")
    actual_type = actual.get("exerciseType")
    if plan_type and actual_type != plan_type:
        issues.append(
            ContractIssue(
                "exercise_type_mismatch",
                f"Exercise '{ex_id}' type mismatch: expected '{plan_type}', got '{actual_type}' (name: '{actual_name}').",
            )
        )

    progression_mode = actual.get("progressionMode")
    if progression_mode not in ("OFF", "AUTO_REGULATION"):
        issues.append(
            ContractIssue(
                "invalid_progression_mode",
                f"Exercise '{ex_id}' progressionMode must be OFF or AUTO_REGULATION, got '{progression_mode}' (name: '{actual_name}').",
            )
        )

    if plan_type == "BODY_WEIGHT":
        body_weight_percentage = actual.get("bodyWeightPercentage")
        if not _has_percentage_semantics(body_weight_percentage):
            issues.append(
                ContractIssue(
                    "missing_body_weight_percentage",
                    f"Exercise '{ex_id}' must include a positive numeric bodyWeightPercentage in percentage form for BODY_WEIGHT exercises, got {body_weight_percentage!r} (name: '{actual_name}'; use 100.0 for full bodyweight, not 1.0).",
                )
            )
    else:
        if actual.get("bodyWeightPercentage") is not None:
            issues.append(
                ContractIssue(
                    "unexpected_body_weight_percentage",
                    f"Exercise '{ex_id}' must set bodyWeightPercentage to null for non-BODY_WEIGHT exercises, got {actual.get('bodyWeightPercentage')!r} (name: '{actual_name}').",
                )
            )

    if plan_type not in ("COUNTDOWN", "COUNTUP"):
        plan_min = plan_ex.get("minReps")
        plan_max = plan_ex.get("maxReps")
        if plan_min is not None and actual.get("minReps") != plan_min:
            issues.append(
                ContractIssue(
                    "min_reps_mismatch",
                    f"Exercise '{ex_id}' minReps mismatch: expected {plan_min}, got {actual.get('minReps')} (name: '{actual_name}').",
                )
            )
        if plan_max is not None and actual.get("maxReps") != plan_max:
            issues.append(
                ContractIssue(
                    "max_reps_mismatch",
                    f"Exercise '{ex_id}' maxReps mismatch: expected {plan_max}, got {actual.get('maxReps')} (name: '{actual_name}').",
                )
            )

    plan_equipment_id = plan_ex.get("equipmentId")
    if "equipmentId" in plan_ex and actual.get("equipmentId") != plan_equipment_id:
        issues.append(
            ContractIssue(
                "equipment_id_mismatch",
                f"Exercise '{ex_id}' equipmentId mismatch: expected {plan_equipment_id!r}, got {actual.get('equipmentId')!r} (name: '{actual_name}').",
            )
        )

    plan_accessory = plan_ex.get("requiredAccessoryEquipmentIds")
    if isinstance(plan_accessory, list):
        actual_accessory = actual.get("requiredAccessoryEquipmentIds") or []
        if sorted(actual_accessory) != sorted(plan_accessory):
            issues.append(
                ContractIssue(
                    "required_accessory_mismatch",
                    f"Exercise '{ex_id}' requiredAccessoryEquipmentIds mismatch: expected {plan_accessory}, got {actual_accessory} (name: '{actual_name}').",
                )
            )

    expected_work_sets = plan_ex.get("numWorkSets")
    expected_rest_between = plan_ex.get("restBetweenSetsSeconds")
    actual_work_sets, actual_rest_sets = _count_work_sets(actual)
    expected_load_field = _load_field_for_exercise_type(plan_type)
    actual_sets = actual.get("sets", []) or []
    seen_set_ids_in_exercise: set[str] = set()
    for idx, set_item in enumerate(actual_sets):
        if not isinstance(set_item, dict):
            continue
        set_id = set_item.get("id")
        if not _is_canonical_plan_placeholder(set_id, "set"):
            issues.append(
                ContractIssue(
                    "invalid_set_placeholder",
                    f"Exercise '{ex_id}' has non-canonical set id '{set_id}' at sets[{idx}].",
                )
            )
        elif set_id in seen_set_ids_in_exercise:
            issues.append(
                ContractIssue(
                    "duplicate_set_placeholder",
                    f"Exercise '{ex_id}' reuses set id '{set_id}' within the same exercise.",
                )
            )
        else:
            seen_set_ids_in_exercise.add(set_id)

    if plan_type in ("COUNTDOWN", "COUNTUP"):
        timed_set_type = _work_set_type_for_exercise_type(plan_type)
        timed_sets = [
            set_item for set_item in actual_sets
            if isinstance(set_item, dict) and set_item.get("type") == timed_set_type
        ]
        rest_sets = [
            set_item for set_item in actual_sets
            if isinstance(set_item, dict) and set_item.get("type") == "RestSet"
        ]
        if len(timed_sets) != 1:
            issues.append(
                ContractIssue(
                    "timed_set_count_mismatch",
                    f"Exercise '{ex_id}' must emit exactly one {timed_set_type}, got {len(timed_sets)} (name: '{actual_name}').",
                )
            )
        if rest_sets:
            issues.append(
                ContractIssue(
                    "timed_exercise_has_rest_sets",
                    f"Exercise '{ex_id}' must not emit RestSet entries for {plan_type} exercises (name: '{actual_name}').",
                )
            )
        if plan_type == "COUNTDOWN" and actual.get("showCountDownTimer") is not True:
            issues.append(
                ContractIssue(
                    "countdown_timer_flag_mismatch",
                    f"Exercise '{ex_id}' must set showCountDownTimer=true for COUNTDOWN exercises (name: '{actual_name}').",
                )
            )

    target_set_prescriptions = plan_ex.get("targetSetPrescriptions")
    if isinstance(target_set_prescriptions, list) and expected_load_field is not None:
        target_set_type = _work_set_type_for_exercise_type(plan_type)
        normalized_targets, target_issues = _normalize_target_set_prescriptions(
            target_set_prescriptions,
            ex_id,
            expected_load_field,
        )
        issues.extend(target_issues)
        actual_work_set_items = [
            set_item for set_item in actual_sets
            if isinstance(set_item, dict) and set_item.get("type") == target_set_type
        ]
        if len(actual_work_set_items) != len(target_set_prescriptions):
            issues.append(
                ContractIssue(
                    "target_set_prescription_emit_count_mismatch",
                    f"Exercise '{ex_id}' emitted {len(actual_work_set_items)} work sets but plan targetSetPrescriptions has {len(target_set_prescriptions)} items.",
                )
            )
        elif not target_issues:
            actual_work_set_by_index = {
                idx: set_item for idx, set_item in enumerate(actual_work_set_items)
            }
            for target_item in sorted(normalized_targets, key=lambda item: item["workSetIndex"]):
                work_set_index = target_item["workSetIndex"]
                actual_set = actual_work_set_by_index.get(work_set_index)
                if actual_set is None:
                    issues.append(
                        ContractIssue(
                            "target_set_prescription_missing_work_set_index",
                            f"Exercise '{ex_id}' is missing emitted work set for workSetIndex {work_set_index}.",
                        )
                    )
                    continue
                if actual_set.get("reps") != target_item.get("reps"):
                    issues.append(
                        ContractIssue(
                            "target_set_prescription_reps_mismatch",
                            f"Exercise '{ex_id}' workSetIndex {work_set_index} reps mismatch: expected {target_item.get('reps')}, got {actual_set.get('reps')} (name: '{actual_name}').",
                        )
                    )
                actual_load = actual_set.get(expected_load_field)
                expected_load = target_item.get(expected_load_field)
                if actual_load != expected_load:
                    issues.append(
                        ContractIssue(
                            "target_set_prescription_load_mismatch",
                            f"Exercise '{ex_id}' workSetIndex {work_set_index} {expected_load_field} mismatch: expected {expected_load}, got {actual_load} (name: '{actual_name}').",
                        )
                    )

    # COUNTDOWN/COUNTUP use timed work sets (TimedDurationSet / EnduranceSet), not WeightSet/BodyWeightSet.
    # _count_work_sets intentionally returns 0 for those types; timed_set_count_mismatch covers them.
    if isinstance(expected_work_sets, int) and expected_work_sets >= 0:
        if plan_type not in ("COUNTDOWN", "COUNTUP") and actual_work_sets != expected_work_sets:
            issues.append(
                ContractIssue(
                    "work_set_count_mismatch",
                    f"Exercise '{ex_id}' work set count mismatch: expected {expected_work_sets}, got {actual_work_sets} (name: '{actual_name}').",
                )
            )

    if isinstance(expected_rest_between, int) and actual_work_sets > 1:
        if actual_rest_sets:
            invalid = [x for x in actual_rest_sets if x != expected_rest_between]
            if invalid:
                issues.append(
                    ContractIssue(
                        "rest_between_sets_mismatch",
                        f"Exercise '{ex_id}' has restSet values {actual_rest_sets}, expected all {expected_rest_between} (name: '{actual_name}').",
                    )
                )

    return issues


def validate_single_exercise_definition_contract(plan_entry: Dict[str, Any], exercise_definition: Dict[str, Any]) -> None:
    issues = _collect_contract_issues_for_exercise(plan_entry, exercise_definition)
    if issues:
        lines = [f"- [{it.code}] {it.message}" for it in issues]
        raise ContractValidationError("Plan contract validation failed at Step 3:\n" + "\n".join(lines))


def _collect_referenced_exercise_ids_from_structure(workout_structure: Dict[str, Any]) -> List[str]:
    refs: List[str] = []
    for component in (workout_structure.get("workoutComponents", []) or []):
        if not isinstance(component, dict):
            continue
        ctype = component.get("componentType")
        if ctype == "Exercise":
            ex_id = component.get("exerciseId")
            if ex_id:
                refs.append(ex_id)
        elif ctype == "Superset":
            for ex_id in (component.get("exerciseIds", []) or []):
                if ex_id:
                    refs.append(ex_id)
    return refs


def _extract_superset_groups_from_structure(workout_structure: Dict[str, Any]) -> List[List[str]]:
    groups: List[List[str]] = []
    for component in (workout_structure.get("workoutComponents", []) or []):
        if not isinstance(component, dict):
            continue
        if component.get("componentType") != "Superset":
            continue
        exercise_ids = [
            ex_id for ex_id in (component.get("exerciseIds", []) or [])
            if isinstance(ex_id, str) and ex_id
        ]
        if exercise_ids:
            groups.append(exercise_ids)
    return groups


def validate_workout_structures_contract(
    plan_index: Dict[str, Any],
    workout_structures: Dict[str, Dict[str, Any]],
    exercise_definitions: Dict[str, Dict[str, Any]],
) -> None:
    issues: List[ContractIssue] = []

    known_exercise_ids = set(exercise_definitions.keys())
    workouts = [wo for wo in (plan_index.get("workouts", []) or []) if isinstance(wo, dict)]

    for wo in workouts:
        wo_id = wo.get("id")
        wo_name = wo.get("name", wo_id or "Unknown")
        if not wo_id:
            continue

        structure = workout_structures.get(wo_id)
        if not isinstance(structure, dict):
            issues.append(
                ContractIssue(
                    "missing_workout_structure",
                    f"Missing emitted workout structure for workout '{wo_name}' ({wo_id}).",
                )
            )
            continue

        if "workoutMetadata" not in structure or "workoutComponents" not in structure:
            issues.append(
                ContractIssue(
                    "invalid_workout_structure_shape",
                    f"Workout '{wo_name}' ({wo_id}) must include workoutMetadata and workoutComponents.",
                )
            )
            continue
        metadata = structure.get("workoutMetadata", {})
        metadata_name = metadata.get("name") if isinstance(metadata, dict) else None
        if wo_name and metadata_name != wo_name:
            issues.append(
                ContractIssue(
                    "workout_name_mismatch",
                    f"Workout '{wo_name}' ({wo_id}) metadata name mismatch: expected '{wo_name}', got '{metadata_name}'.",
                )
            )

        refs = _collect_referenced_exercise_ids_from_structure(structure)
        expected = [x for x in (wo.get("exerciseIds", []) or []) if x]
        expected_superset_groups, superset_issues = _normalize_superset_groups(
            wo.get("supersetGroups"),
            wo_name,
            set(expected),
        )
        issues.extend(superset_issues)

        missing = sorted(set(expected) - set(refs))
        extra = sorted(set(refs) - set(expected))
        if missing:
            issues.append(
                ContractIssue(
                    "workout_structure_missing_exercise_refs",
                    f"Workout '{wo_name}' ({wo_id}) missing exercise refs: {missing}.",
                )
            )
        if extra:
            issues.append(
                ContractIssue(
                    "workout_structure_extra_exercise_refs",
                    f"Workout '{wo_name}' ({wo_id}) has unexpected exercise refs: {extra}.",
                )
            )

        ordered_refs = [x for x in refs if x in expected]
        if ordered_refs != expected:
            issues.append(
                ContractIssue(
                    "workout_exercise_order_mismatch",
                    f"Workout '{wo_name}' ({wo_id}) exercise order mismatch: expected {expected}, got {ordered_refs}.",
                )
            )

        actual_superset_groups = _extract_superset_groups_from_structure(structure)
        if actual_superset_groups != expected_superset_groups:
            issues.append(
                ContractIssue(
                    "workout_superset_group_mismatch",
                    f"Workout '{wo_name}' ({wo_id}) superset groups mismatch: expected {expected_superset_groups}, got {actual_superset_groups}.",
                )
            )

        for ex_id in refs:
            if ex_id not in known_exercise_ids:
                issues.append(
                    ContractIssue(
                        "workout_references_unknown_emitted_exercise",
                        f"Workout '{wo_name}' ({wo_id}) references unknown emitted exercise '{ex_id}'.",
                    )
                )

    if issues:
        lines = [f"- [{it.code}] {it.message}" for it in issues]
        raise ContractValidationError("Plan contract validation failed at Step 4:\n" + "\n".join(lines))


def _canonicalize_ids_for_parity(value: Any, key: Optional[str] = None) -> Any:
    id_keys = {
        "id",
        "equipmentId",
        "exerciseId",
        "previousVersionId",
        "nextVersionId",
        "polarDeviceId",
        "workoutPlanId",
    }
    id_list_keys = {
        "requiredAccessoryEquipmentIds",
        "exerciseIds",
        "workoutIds",
        "includedWorkoutGlobalIds",
    }

    if isinstance(value, dict):
        if key == "restSecondsByExercise":
            return {
                "__id_map_values__": sorted(
                    [_canonicalize_ids_for_parity(v) for _, v in value.items()],
                    key=lambda x: str(x),
                )
            }
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if k in id_keys:
                out[k] = "__ID__" if v is not None else None
            elif k == "globalId":
                out[k] = "__GLOBAL_ID__" if v is not None else None
            elif k in id_list_keys and isinstance(v, list):
                out[k] = ["__ID__" for _ in v]
            else:
                out[k] = _canonicalize_ids_for_parity(v, key=k)
        return out

    if isinstance(value, list):
        return [_canonicalize_ids_for_parity(v, key=key) for v in value]

    return value


def validate_uuid_conversion_parity(placeholder_store: Dict[str, Any], uuid_store: Dict[str, Any]) -> None:
    before = _canonicalize_ids_for_parity(placeholder_store)
    after = _canonicalize_ids_for_parity(uuid_store)
    if before != after:
        raise ContractValidationError(
            "Plan contract validation failed at Step 7:\n"
            "- [uuid_conversion_parity_mismatch] Non-ID fields changed during placeholder->UUID conversion."
        )
