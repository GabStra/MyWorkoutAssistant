"""Plan contract validation for generation stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


class ContractValidationError(ValueError):
    """Raised when stage artifacts violate the canonical plan contract."""


@dataclass(frozen=True)
class ContractIssue:
    code: str
    message: str


def _work_set_type_for_exercise_type(exercise_type: str) -> Optional[str]:
    mapping = {
        "WEIGHT": "WeightSet",
        "BODY_WEIGHT": "BodyWeightSet",
        "COUNTDOWN": "TimedDurationSet",
        "COUNTUP": "EnduranceSet",
    }
    return mapping.get(exercise_type)


def _collect_contract_issues_plan_index(plan_index: Dict[str, Any]) -> List[ContractIssue]:
    issues: List[ContractIssue] = []

    exercises = plan_index.get("exercises", []) or []
    workouts = plan_index.get("workouts", []) or []

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
        if not ex_type:
            issues.append(ContractIssue("missing_exercise_type", f"Exercise '{ex_name}' is missing exerciseType."))
        if not ex.get("name"):
            issues.append(ContractIssue("missing_exercise_name", f"Exercise '{ex_id or 'Unknown'}' is missing name."))

        min_reps = ex.get("minReps")
        max_reps = ex.get("maxReps")
        if min_reps is not None and max_reps is not None and min_reps > max_reps:
            issues.append(
                ContractIssue(
                    "invalid_rep_range",
                    f"Exercise '{ex_name}' has minReps={min_reps} greater than maxReps={max_reps}.",
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

        if not wo_id:
            issues.append(ContractIssue("missing_workout_id", f"Workout '{wo_name}' is missing id."))

        for ex_id in exercise_ids_in_workout:
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

    return issues


def validate_plan_index_contract(plan_index: Dict[str, Any]) -> None:
    issues = _collect_contract_issues_plan_index(plan_index)
    if issues:
        lines = [f"- [{it.code}] {it.message}" for it in issues]
        raise ContractValidationError("Plan contract validation failed at Step 1:\n" + "\n".join(lines))


def _count_work_sets(exercise: Dict[str, Any]) -> Tuple[int, List[int]]:
    exercise_type = exercise.get("exerciseType")
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

        if isinstance(expected_work_sets, int) and expected_work_sets >= 0:
            if actual_work_sets != expected_work_sets:
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
    }
    id_list_keys = {
        "requiredAccessoryEquipmentIds",
        "exerciseIds",
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
