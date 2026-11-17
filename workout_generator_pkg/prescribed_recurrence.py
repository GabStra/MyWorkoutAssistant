"""Generic recurring-prescription identity and contract helpers.

Recurring identity belongs to a source-declared session family and exercise
slot, never to a shared exercise definition or a similar display name.  The
helpers below keep that boundary in one place so source-fact mapping, direct
PlanIndex import, contract validation and export all agree on the same IDs.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any


RECURRING_SESSION_KEY = "recurringSessionKey"
RECURRING_EXERCISE_KEY = "recurringExerciseKey"
RECURRING_PROGRAM_KEY = "recurringProgramKey"
RECURRING_SESSION_ID = "recurringSessionId"
RECURRING_EXERCISE_ID = "recurringExerciseId"
LOAD_HISTORY_POLICY = "loadHistoryPolicy"
PRESCRIPTION_ORDINAL = "prescriptionOrdinal"
PRESCRIPTION_LABEL = "prescriptionLabel"

LOAD_HISTORY_POLICIES = ("NONE", "LAST_WORKING_LOAD", "PRESCRIBED_WEIGHT")
LOAD_CAPABLE_EXERCISE_TYPES = ("WEIGHT", "BODY_WEIGHT")

_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True)
class RecurringPrescriptionIssue:
    code: str
    message: str
    exercise_id: str | None = None
    workout_id: str | None = None


def is_recurring_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(_UUID_PATTERN.match(value))


def canonical_recurring_key(value: Any) -> str | None:
    """Return the author-provided key in a deterministic, whitespace-stable form."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s+", " ", value.strip())
    return normalized or None


def _canonical_token(value: Any) -> str | None:
    key = canonical_recurring_key(value)
    return key.casefold() if key else None


def recurring_session_uuid(program_key: Any, session_key: Any) -> str:
    program_token = _canonical_token(program_key)
    token = _canonical_token(session_key)
    if program_token is None or token is None:
        raise ValueError("A recurring program key and session key are required to resolve its stable ID.")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "mwa-recurring-session:" + json.dumps(
        [program_token, token], ensure_ascii=False, separators=(",", ":"))))


def recurring_exercise_uuid(program_key: Any, session_key: Any, exercise_key: Any) -> str:
    program_token = _canonical_token(program_key)
    session_token = _canonical_token(session_key)
    exercise_token = _canonical_token(exercise_key)
    if program_token is None or session_token is None or exercise_token is None:
        raise ValueError("A recurring program key, session key and exercise key are required to resolve a track ID.")
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        "mwa-recurring-exercise:" + json.dumps(
            [program_token, session_token, exercise_token], ensure_ascii=False, separators=(",", ":")),
    ))


def _track_identity(exercise: dict[str, Any]) -> tuple[Any, Any, Any]:
    definition = (
        exercise.get("libraryDefinitionId")
        or exercise.get("exerciseDefinitionId")
        or exercise.get("name")
    )
    return definition, exercise.get("exerciseType"), exercise.get("equipmentId")


def _issue(code: str, message: str, *, exercise_id: str | None = None,
           workout_id: str | None = None) -> RecurringPrescriptionIssue:
    return RecurringPrescriptionIssue(code, message, exercise_id, workout_id)


def _resolve_recurring_fields(plan_index: dict[str, Any], *, apply: bool) -> list[RecurringPrescriptionIssue]:
    if not isinstance(plan_index, dict):
        return []
    target = plan_index if apply else copy.deepcopy(plan_index)
    issues: list[RecurringPrescriptionIssue] = []
    workouts = [workout for workout in target.get("workouts", []) or [] if isinstance(workout, dict)]
    exercises_by_id = {
        exercise.get("id"): exercise
        for exercise in target.get("exercises", []) or []
        if isinstance(exercise, dict) and exercise.get("id")
    }
    program_key = canonical_recurring_key(target.get(RECURRING_PROGRAM_KEY))
    recurring_keys_present = any(
        workout.get(RECURRING_SESSION_KEY) is not None
        or any(isinstance(exercises_by_id.get(exercise_id), dict)
               and exercises_by_id[exercise_id].get(RECURRING_EXERCISE_KEY) is not None
               for exercise_id in workout.get("exerciseIds", []) or [])
        for workout in workouts
    )
    if recurring_keys_present and program_key is None:
        issues.append(_issue("recurring_program_key_required",
            "PlanIndex recurringProgramKey must be non-empty text when recurring keys are used."))

    for workout in workouts:
        workout_id = workout.get("id")
        supplied_session_id = workout.get(RECURRING_SESSION_ID)
        raw_session_key = workout.get(RECURRING_SESSION_KEY)
        session_key = canonical_recurring_key(raw_session_key)
        if raw_session_key is not None and session_key is None:
            issues.append(_issue(
                "invalid_recurring_session_key",
                f"Workout '{workout_id}' recurringSessionKey must be non-empty text when present.",
                workout_id=workout_id,
            ))
        if supplied_session_id is not None and not is_recurring_uuid(supplied_session_id):
            issues.append(_issue(
                "invalid_recurring_session_id",
                f"Workout '{workout_id}' recurringSessionId must be a UUID or null.",
                workout_id=workout_id,
            ))
        if session_key is not None:
            if program_key is None:
                pass
            else:
                expected_session_id = recurring_session_uuid(program_key, session_key)
                if supplied_session_id is not None and supplied_session_id != expected_session_id:
                    issues.append(_issue(
                        "recurring_session_id_conflict",
                        f"Workout '{workout_id}' recurringSessionId does not match its source recurring session key.",
                        workout_id=workout_id,
                    ))
                if apply:
                    workout[RECURRING_SESSION_ID] = expected_session_id
        elif supplied_session_id is not None and apply:
            workout[RECURRING_SESSION_ID] = supplied_session_id
        ordinal = workout.get(PRESCRIPTION_ORDINAL)
        if ordinal is not None and (not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1):
            issues.append(_issue(
                "invalid_prescription_ordinal",
                f"Workout '{workout_id}' prescriptionOrdinal must be a positive integer when present.",
                workout_id=workout_id,
            ))
        label = workout.get(PRESCRIPTION_LABEL)
        if label is not None and not isinstance(label, str):
            issues.append(_issue(
                "invalid_prescription_label",
                f"Workout '{workout_id}' prescriptionLabel must be text when present.",
                workout_id=workout_id,
            ))

    # A recurring track is one slot in one source-declared session family.
    # Sharing IDs across families or definitions would silently mix history.
    track_owners: dict[str, tuple[Any, tuple[Any, Any, Any]]] = {}
    seen_session_slots: dict[tuple[str, str], str | None] = {}
    ordinals_by_session: dict[str, set[int]] = {}
    for workout in workouts:
        workout_id = workout.get("id")
        session_key = canonical_recurring_key(workout.get(RECURRING_SESSION_KEY))
        session_id = workout.get(RECURRING_SESSION_ID)
        if session_id is None and session_key is not None and program_key is not None:
            session_id = recurring_session_uuid(program_key, session_key)
        ordinal = workout.get(PRESCRIPTION_ORDINAL)
        if session_key is not None or session_id is not None:
            family = session_id or session_key
            if ordinal is None:
                ordinal = len(ordinals_by_session.setdefault(family, set())) + 1
                while ordinal in ordinals_by_session[family]:
                    ordinal += 1
                if apply:
                    workout[PRESCRIPTION_ORDINAL] = ordinal
            if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0:
                ordinals = ordinals_by_session.setdefault(family, set())
                if ordinal in ordinals:
                    issues.append(_issue(
                        "duplicate_prescription_ordinal",
                        f"Workout '{workout_id}' duplicates prescriptionOrdinal {ordinal} in its recurring session.",
                        workout_id=workout_id,
                    ))
                ordinals.add(ordinal)
        for exercise_id in workout.get("exerciseIds", []) or []:
            exercise = exercises_by_id.get(exercise_id)
            if not isinstance(exercise, dict):
                continue
            supplied_track_id = exercise.get(RECURRING_EXERCISE_ID)
            raw_track_key = exercise.get(RECURRING_EXERCISE_KEY)
            track_key = canonical_recurring_key(raw_track_key)
            policy = exercise.get(LOAD_HISTORY_POLICY)
            if raw_track_key is not None and track_key is None:
                issues.append(_issue(
                    "invalid_recurring_exercise_key",
                    f"Exercise '{exercise_id}' recurringExerciseKey must be non-empty text when present.",
                    exercise_id=exercise_id,
                ))
            if supplied_track_id is not None and not is_recurring_uuid(supplied_track_id):
                issues.append(_issue(
                    "invalid_recurring_exercise_id",
                    f"Exercise '{exercise_id}' recurringExerciseId must be a UUID or null.",
                    exercise_id=exercise_id,
                ))
            if policy is not None and policy not in LOAD_HISTORY_POLICIES:
                issues.append(_issue(
                    "invalid_load_history_policy",
                    f"Exercise '{exercise_id}' loadHistoryPolicy must be NONE, LAST_WORKING_LOAD or PRESCRIBED_WEIGHT.",
                    exercise_id=exercise_id,
                ))
            if track_key is not None:
                if session_key is None:
                    issues.append(_issue(
                        "recurring_session_key_required",
                        f"Exercise '{exercise_id}' declares a recurring track without a recurring session key.",
                        exercise_id=exercise_id,
                    ))
                elif program_key is not None:
                    expected_track_id = recurring_exercise_uuid(program_key, session_key, track_key)
                    if program_key is not None:
                        if supplied_track_id is not None and supplied_track_id != expected_track_id:
                            issues.append(_issue("recurring_exercise_id_conflict",
                                f"Exercise '{exercise_id}' recurringExerciseId does not match its recurring program, session and track keys.",
                                exercise_id=exercise_id))
                        slot = (session_key, track_key)
                        if slot in seen_session_slots and seen_session_slots[slot] == workout_id:
                            issues.append(_issue("duplicate_recurring_track_in_workout",
                                f"Workout '{workout_id}' uses recurring track '{track_key}' more than once.",
                                exercise_id=exercise_id, workout_id=workout_id))
                        else:
                            seen_session_slots[slot] = workout_id
                        if apply:
                            exercise[RECURRING_EXERCISE_ID] = expected_track_id
                            if exercise.get(LOAD_HISTORY_POLICY) is None:
                                exercise[LOAD_HISTORY_POLICY] = "NONE"
                            policy = exercise.get(LOAD_HISTORY_POLICY)
                        supplied_track_id = expected_track_id
                elif supplied_track_id is not None:
                    pass
            if policy == "LAST_WORKING_LOAD" and supplied_track_id is None:
                issues.append(_issue(
                    "recurring_track_required_for_load_history",
                    f"Exercise '{exercise_id}' requests LAST_WORKING_LOAD without a recurring exercise track.",
                    exercise_id=exercise_id,
                ))
            if supplied_track_id is None:
                continue
            if session_id is None:
                issues.append(_issue(
                    "recurring_session_required_for_track",
                    f"Exercise '{exercise_id}' declares a recurring track without a recurring session.",
                    exercise_id=exercise_id,
                ))
            if policy == "LAST_WORKING_LOAD" and exercise.get("exerciseType") not in LOAD_CAPABLE_EXERCISE_TYPES:
                issues.append(_issue(
                    "load_history_requires_load_exercise",
                    f"Exercise '{exercise_id}' requests LAST_WORKING_LOAD but is {exercise.get('exerciseType')!r}, not a load exercise.",
                    exercise_id=exercise_id,
                ))
            identity = _track_identity(exercise)
            previous = track_owners.get(supplied_track_id)
            if previous is not None:
                previous_session_id, previous_identity = previous
                if (previous_session_id is not None and session_id is not None
                        and previous_session_id != session_id):
                    issues.append(_issue(
                        "recurring_track_cross_session_conflict",
                        f"Exercise '{exercise_id}' reuses a recurring track ID in a different session family.",
                        exercise_id=exercise_id,
                    ))
                if previous_identity != identity:
                    issues.append(_issue(
                        "conflicting_recurring_exercise_track",
                        f"Recurring track '{exercise_id}' must keep the same definition, exercise type and equipment.",
                        exercise_id=exercise_id,
                    ))
            else:
                track_owners[supplied_track_id] = (session_id, identity)
    return issues


def normalize_recurring_prescription_fields(plan_index: dict[str, Any]) -> list[RecurringPrescriptionIssue]:
    """Resolve source recurrence keys into stable, code-owned UUIDs in place."""
    return _resolve_recurring_fields(plan_index, apply=True)


def recurring_prescription_issues(plan_index: dict[str, Any]) -> list[RecurringPrescriptionIssue]:
    """Validate recurrence contracts without mutating the caller's PlanIndex."""
    return _resolve_recurring_fields(plan_index, apply=False)
