from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import floor
import re
from typing import Any

from .loader import WorkoutHistoryStore


def format_number(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    suffixes = ["", "K", "M", "B", "T"]
    suffix_index = 0
    while number >= 1000 and suffix_index < len(suffixes) - 1:
        number /= 1000
        suffix_index += 1
    if number == 0:
        return "0"
    if number >= 100:
        return f"{number:.0f}{suffixes[suffix_index]}"
    if number >= 10:
        return strip_trailing_zero_decimal(f"{number:.1f}{suffixes[suffix_index]}")
    return strip_trailing_zero_decimal(f"{number:.2f}{suffixes[suffix_index]}")


def strip_trailing_zero_decimal(text: str) -> str:
    return re.sub(r"\.0+$", "", text)


def format_duration(seconds: Any) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "unknown"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def compact_duration(seconds: int) -> str:
    hours, rem = divmod(max(seconds, 0), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def athlete_context_markdown(store: WorkoutHistoryStore) -> str:
    profile = store.athlete_profile()
    lines = [
        "#### Athlete Context",
        f"- Age: {profile['age'] or 'unknown'} (birth year: {profile['birth_year'] or 'unknown'})",
        f"- Body weight: {format_number(profile['body_weight_kg'])} kg",
        f"- Measured max HR: {profile['measured_max_heart_rate'] or 'unknown'} bpm",
        f"- Resting HR: {profile['resting_heart_rate'] or 'unknown'} bpm",
        f"- Progression amount: {format_number(profile['progression_percentage_amount'])}%",
        (
            "- Training history: "
            f"{profile['completed_session_count']} completed sessions, "
            f"{profile['total_recorded_sets']} recorded sets, "
            f"{profile['exercise_count']} exercises"
        ),
        f"- Date range: {profile['training_start_date'] or 'unknown'} to {profile['training_end_date'] or 'unknown'}",
    ]
    equipment = ", ".join(profile["available_equipment"]) or "none"
    accessories = ", ".join(profile["available_accessories"]) or "none"
    lines.append(f"- Available equipment: {equipment}")
    lines.append(f"- Available accessories: {accessories}")
    return "\n".join(lines) + "\n\n"


def equipment_details_data(store: WorkoutHistoryStore) -> dict[str, list[dict[str, Any]]]:
    return {
        "equipment": [equipment_data(item) for item in store.equipment],
        "accessories": [equipment_data(item) for item in store.accessory_equipment],
    }


def equipment_data(item: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": item.get("id"),
        "name": item.get("name"),
        "type": item.get("type"),
    }
    if item.get("barWeight") is not None:
        data["bar_weight_kg"] = item.get("barWeight")
    for source_key, target_key in (
        ("availablePlates", "available_plates_kg"),
        ("availableWeights", "available_weights_kg"),
        ("availableDumbbells", "available_dumbbells_kg"),
        ("extraWeights", "extra_weights_kg"),
    ):
        weights = [
            weight.get("weight")
            for weight in item.get(source_key) or []
            if isinstance(weight, dict) and weight.get("weight") is not None
        ]
        if weights:
            data[target_key] = sorted(weights)
    return data


def exercise_index_markdown(store: WorkoutHistoryStore) -> str:
    exercises = sorted(store.exercises_by_id().values(), key=lambda item: str(item.get("name", "")).lower())
    lines = ["# Exercise Index", ""]
    for exercise in exercises:
        exercise_id = str(exercise.get("id"))
        names = ", ".join(store.workout_names_for_exercise(exercise_id))
        exercise_type = exercise.get("exerciseType") or "unknown"
        lines.append(f"- {exercise.get('name', 'Unknown')} (`{exercise_id}`): {exercise_type}; workouts: {names or 'none'}")
    return "\n".join(lines) + "\n"


def current_training_plan_data(store: WorkoutHistoryStore, active_only: bool = True) -> dict[str, Any]:
    workouts = sorted(store.workouts, key=lambda item: (item.get("order") or 0, str(item.get("name") or "")))
    if active_only:
        workouts = [
            workout for workout in workouts
            if workout.get("isActive", True) and workout.get("enabled", True)
        ]
    return {
        "athlete": store.athlete_profile(),
        "equipment": equipment_details_data(store),
        "workouts": [workout_plan_data(store, workout) for workout in workouts],
    }


def workout_plan_data(store: WorkoutHistoryStore, workout: dict[str, Any]) -> dict[str, Any]:
    return {
        "workout_id": workout.get("id"),
        "name": workout.get("name"),
        "description": workout.get("description") or "",
        "order": workout.get("order"),
        "enabled": workout.get("enabled", True),
        "is_active": workout.get("isActive", True),
        "times_completed_in_a_week": workout.get("timesCompletedInAWeek"),
        "uses_polar_device": workout.get("usePolarDevice", False),
        "components": [
            component_plan_data(store, component)
            for component in workout.get("workoutComponents") or []
            if component.get("enabled", True)
        ],
    }


def component_plan_data(store: WorkoutHistoryStore, component: dict[str, Any]) -> dict[str, Any]:
    component_type = component.get("type")
    if component_type == "Superset":
        return {
            "type": "Superset",
            "id": component.get("id"),
            "enabled": component.get("enabled", True),
            "rest_seconds_by_exercise": component.get("restSecondsByExercise") or {},
            "exercises": [
                exercise_config_data(store, exercise)
                for exercise in component.get("exercises") or []
                if exercise.get("enabled", True)
            ],
        }
    if component_type == "Rest":
        return {
            "type": "Rest",
            "id": component.get("id"),
            "enabled": component.get("enabled", True),
            "time_seconds": component.get("timeInSeconds"),
        }
    return exercise_config_data(store, component)


def exercise_config_data(store: WorkoutHistoryStore, exercise: dict[str, Any]) -> dict[str, Any]:
    equipment_id = exercise.get("equipmentId")
    equipment = store.equipment_or_accessory_by_id().get(str(equipment_id)) if equipment_id else None
    data: dict[str, Any] = {
        "type": "Exercise",
        "exercise_id": exercise.get("id"),
        "name": exercise.get("name"),
        "enabled": exercise.get("enabled", True),
        "do_not_store_history": exercise.get("doNotStoreHistory", False),
        "exercise_type": exercise.get("exerciseType"),
        "exercise_category": exercise.get("exerciseCategory"),
        "notes": exercise.get("notes") or "",
        "equipment_id": equipment_id,
        "equipment_name": equipment.get("name") if equipment else None,
        "required_accessory_equipment_ids": exercise.get("requiredAccessoryEquipmentIds") or [],
        "progression_mode": exercise.get("progressionMode"),
        "min_reps": exercise.get("minReps"),
        "max_reps": exercise.get("maxReps"),
        "min_load_percent": exercise.get("minLoadPercent"),
        "max_load_percent": exercise.get("maxLoadPercent"),
        "body_weight_percentage": exercise.get("bodyWeightPercentage"),
        "generate_warmup_sets": exercise.get("generateWarmUpSets", False),
        "intra_set_rest_seconds": exercise.get("intraSetRestInSeconds"),
        "show_countdown_timer": exercise.get("showCountDownTimer", False),
        "requires_load_calibration": exercise.get("requiresLoadCalibration", False),
        "muscle_groups": exercise.get("muscleGroups") or [],
        "secondary_muscle_groups": exercise.get("secondaryMuscleGroups") or [],
        "heart_rate_zone_percent": heart_rate_zone_percent(exercise),
        "planned_sets": [planned_set_data(item) for item in exercise.get("sets") or []],
    }
    return data


def planned_set_data(set_item: dict[str, Any]) -> dict[str, Any]:
    set_type = set_item.get("type")
    data: dict[str, Any] = {
        "id": set_item.get("id"),
        "type": set_type,
        "sub_category": set_item.get("subCategory"),
    }
    if set_type == "WeightSet":
        data.update({"weight_kg": set_item.get("weight"), "reps": set_item.get("reps")})
    elif set_type == "BodyWeightSet":
        data.update({"additional_weight_kg": set_item.get("additionalWeight"), "reps": set_item.get("reps")})
    elif set_type == "RestSet":
        data["time_seconds"] = set_item.get("timeInSeconds")
    elif set_type in {"TimedDurationSet", "EnduranceSet"}:
        data["time_seconds"] = int(set_item.get("timeInMillis") or 0) // 1000
        data["auto_start"] = set_item.get("autoStart")
        data["auto_stop"] = set_item.get("autoStop")
    return data


def heart_rate_zone_percent(exercise: dict[str, Any]) -> dict[str, Any] | None:
    lower = exercise.get("lowerBoundMaxHRPercent")
    upper = exercise.get("upperBoundMaxHRPercent")
    if lower is None or upper is None:
        return None
    return {"lower": float(lower) * 100, "upper": float(upper) * 100}


def summary_markdown(store: WorkoutHistoryStore) -> str:
    profile = store.athlete_profile()
    workouts = sorted(store.workouts, key=lambda item: (item.get("order") or 0, str(item.get("name") or "")))
    lines = [
        "# Workout History Summary",
        "",
        athlete_context_markdown(store).rstrip(),
        "## Workouts",
    ]
    for workout in workouts:
        status = "active" if workout.get("isActive", True) and workout.get("enabled", True) else "inactive"
        count = len([
            session for session in store.completed_sessions()
            if str(session.get("workoutId")) == str(workout.get("id"))
        ])
        lines.append(f"- {workout.get('name', 'Unknown')} (`{workout.get('id')}`): {status}, {count} completed sessions")
    lines.extend([
        "",
        "## Counts",
        f"- Completed sessions: {profile['completed_session_count']}",
        f"- Recorded sets: {profile['total_recorded_sets']}",
        f"- Exercises trained: {profile['exercise_count']}",
        "",
        exercise_index_markdown(store).rstrip(),
    ])
    return "\n".join(lines) + "\n"


def session_list(store: WorkoutHistoryStore, limit: int = 50, offset: int = 0, workout_name: str | None = None, exercise_name: str | None = None) -> dict[str, Any]:
    sessions = list(reversed(store.completed_sessions()))
    workouts = store.workouts_by_id()
    exercise_matches: set[str] | None = None
    if exercise_name:
        needle = exercise_name.lower()
        exercise_matches = {
            exercise_id for exercise_id, exercise in store.exercises_by_id().items()
            if needle in str(exercise.get("name") or "").lower()
        }
    filtered = []
    for session in sessions:
        workout = workouts.get(str(session.get("workoutId"))) or {}
        if workout_name and workout_name.lower() not in str(workout.get("name") or "").lower():
            continue
        sets = store.sets_for_session(str(session.get("id")))
        if exercise_matches is not None and not any(str(item.get("exerciseId")) in exercise_matches for item in sets):
            continue
        filtered.append({
            "workout_history_id": session.get("id"),
            "workout_id": session.get("workoutId"),
            "workout_name": workout.get("name") or "Unknown Workout",
            "date": session.get("date"),
            "time": session.get("time"),
            "duration": format_duration(session.get("duration")),
            "duration_seconds": session.get("duration"),
            "recorded_set_count": len([item for item in sets if is_insight_comparison_set(item)]),
            "heart_rate": heart_rate_summary_data(store, session),
        })
    safe_offset = max(offset, 0)
    safe_limit = max(limit, 0)
    return {
        "total": len(filtered),
        "limit": safe_limit,
        "offset": safe_offset,
        "has_more": safe_offset + safe_limit < len(filtered),
        "items": filtered[safe_offset:safe_offset + safe_limit],
    }


def list_exercises_data(store: WorkoutHistoryStore, query: str | None = None) -> list[dict[str, Any]]:
    exercises = store.exercises_by_id()
    query_lc = query.lower() if query else None
    rows = []
    for exercise_id, exercise in exercises.items():
        if query_lc and query_lc not in str(exercise.get("name") or "").lower():
            continue
        active_sets = [item for item in store.sets_for_exercise(exercise_id) if is_insight_comparison_set(item)]
        sessions = {str(item.get("workoutHistoryId")) for item in active_sets if item.get("workoutHistoryId")}
        rows.append({
            "exercise_id": exercise_id,
            "name": exercise.get("name"),
            "type": exercise.get("exerciseType"),
            "enabled": exercise.get("enabled", True),
            "do_not_store_history": exercise.get("doNotStoreHistory", False),
            "notes": exercise.get("notes") or "",
            "equipment_name": (store.equipment_or_accessory_by_id().get(str(exercise.get("equipmentId"))) or {}).get("name"),
            "progression_mode": exercise.get("progressionMode"),
            "min_reps": exercise.get("minReps"),
            "max_reps": exercise.get("maxReps"),
            "min_load_percent": exercise.get("minLoadPercent"),
            "max_load_percent": exercise.get("maxLoadPercent"),
            "body_weight_percentage": exercise.get("bodyWeightPercentage"),
            "generate_warmup_sets": exercise.get("generateWarmUpSets", False),
            "muscle_groups": exercise.get("muscleGroups") or [],
            "secondary_muscle_groups": exercise.get("secondaryMuscleGroups") or [],
            "planned_sets": [planned_set_data(item) for item in exercise.get("sets") or []],
            "session_count": len(sessions),
            "recorded_set_count": len(active_sets),
            "workouts": store.workout_names_for_exercise(exercise_id),
        })
    return sorted(rows, key=lambda item: str(item["name"]).lower())


def heart_rate_summary_data(store: WorkoutHistoryStore, session: dict[str, Any]) -> dict[str, Any] | None:
    samples = [int(item) for item in session.get("heartBeatRecords") or [] if isinstance(item, int)]
    valid = [item for item in samples if item > 0]
    if not valid:
        return None
    birth_year = store.workout_store.get("birthDateYear")
    age = datetime.today().year - int(birth_year) if birth_year else None
    max_hr = effective_max_heart_rate(age, store.workout_store.get("measuredMaxHeartRate"))
    resting_hr = effective_resting_heart_rate(store.workout_store.get("restingHeartRate"))
    zones = heart_rate_zone_counts(valid, max_hr, resting_hr) if max_hr else {}
    return {
        "valid_sample_count": len(valid),
        "invalid_sample_count": len(samples) - len(valid),
        "duration": compact_duration(len(valid)),
        "average_bpm": int(sum(valid) / len(valid)),
        "min_bpm": min(valid),
        "max_bpm": max(valid),
        "max_hr_basis_bpm": max_hr,
        "resting_hr_basis_bpm": resting_hr,
        "zone_time": zones,
    }


def effective_max_heart_rate(age: int | None, measured_max_heart_rate: Any) -> int | None:
    if measured_max_heart_rate is not None:
        return int(measured_max_heart_rate)
    if age is None:
        return None
    return 211 - round_half_up(0.64 * age)


def effective_resting_heart_rate(resting_heart_rate: Any) -> int:
    return int(resting_heart_rate) if resting_heart_rate is not None else 60


def round_half_up(value: float) -> int:
    return int(floor(value + 0.5))


def heart_rate_from_percentage(percentage: float, max_hr: int, resting_hr: int) -> int:
    reserve = max(max_hr - resting_hr, 1)
    return round_half_up(resting_hr + (percentage / 100) * reserve)


def heart_rate_zone_bounds_bpm(max_hr: int, resting_hr: int) -> list[tuple[int, int]]:
    zone_ranges = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 100)]
    zone_starts = [heart_rate_from_percentage(lower, max_hr, resting_hr) for lower, _ in zone_ranges]
    absolute_max = heart_rate_from_percentage(zone_ranges[-1][1], max_hr, resting_hr)
    bounds: list[tuple[int, int]] = []
    for index, lower in enumerate(zone_starts):
        upper = zone_starts[index + 1] - 1 if index < len(zone_starts) - 1 else absolute_max
        bounds.append((lower, max(lower, upper)))
    return bounds


def zone_index_for_bpm(heart_rate: int, zone_bounds: list[tuple[int, int]]) -> int:
    for index in range(len(zone_bounds) - 1, -1, -1):
        lower, upper = zone_bounds[index]
        if lower <= heart_rate <= upper:
            return index
    if heart_rate < zone_bounds[0][0]:
        return 0
    if heart_rate > zone_bounds[-1][1]:
        return len(zone_bounds) - 1
    return 0


def heart_rate_zone_counts(samples: list[int], max_hr: int, resting_hr: int) -> dict[str, str]:
    if max_hr <= 0:
        return {}
    zone_bounds = heart_rate_zone_bounds_bpm(max_hr, resting_hr)
    counts = [0 for _ in zone_bounds]
    for sample in samples:
        zone_index = zone_index_for_bpm(sample, zone_bounds)
        counts[zone_index] += 1
    return {f"Z{index}": compact_duration(count) for index, count in enumerate(counts) if count > 0}


def session_markdown(store: WorkoutHistoryStore, workout_history_id: str) -> str:
    session = store.sessions_by_id().get(str(workout_history_id))
    if not session:
        raise ValueError(f"Workout session not found: {workout_history_id}")
    workout = store.workout_by_id(str(session.get("workoutId"))) or {}
    exercises = store.exercises_by_id()
    sets = store.sets_for_session(str(workout_history_id))
    sets_by_exercise: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for set_history in sets:
        exercise_id = set_history.get("exerciseId")
        if exercise_id:
            sets_by_exercise[str(exercise_id)].append(set_history)

    lines = [
        f"# {workout.get('name') or 'Unknown Workout'}",
        f"{session.get('date')} {session.get('time')} | Dur: {format_duration(session.get('duration'))}",
        "",
        athlete_context_markdown(store).rstrip(),
        "## Session Summary",
        f"- Workout history id: `{session.get('id')}`",
        f"- Completed: {session.get('isDone')}",
        f"- Recorded sets: {len([item for item in sets if is_insight_comparison_set(item)])}",
        f"- Heart rate samples: {len(session.get('heartBeatRecords') or [])}",
        "",
    ]
    hr_summary = heart_rate_summary_data(store, session)
    if hr_summary:
        zone_time = " | ".join(f"{zone} {duration}" for zone, duration in hr_summary["zone_time"].items())
        lines.extend([
            "#### Session Heart Rate",
            f"- Duration: {hr_summary['duration']}",
            f"- Average: {hr_summary['average_bpm']} bpm",
            f"- Range: {hr_summary['min_bpm']}-{hr_summary['max_bpm']} bpm",
            f"- Zone time: {zone_time or 'none'}",
            "",
        ])
    for exercise_id, exercise_sets in sets_by_exercise.items():
        active_sets = [item for item in exercise_sets if is_insight_comparison_set(item)]
        if not active_sets:
            continue
        exercise = exercises.get(exercise_id) or {"name": "Unknown Exercise"}
        progression = store.progression_for(str(workout_history_id), exercise_id)
        lines.extend([
            f"### {exercise.get('name')}",
            f"- Type: {exercise.get('exerciseType') or 'unknown'}",
            f"- Sets: {', '.join(set_token(item, exercise, store) for item in active_sets)}",
            f"- Total reps: {sum(reps_for_set(item) for item in active_sets)}",
            f"- Total volume: {format_number(sum(volume_for_set(item, exercise) for item in active_sets))} kg",
        ])
        rest_line = compact_rest_summary(store.rest_records_for_session(str(workout_history_id), exercise_id))
        if rest_line:
            lines.append(f"- Rest: {rest_line}")
        if progression:
            lines.append(
                "- Progression: "
                f"{progression.get('progressionState', 'unknown')} "
                f"(vs expected: {progression.get('vsExpected', 'unknown')}, "
                f"vs previous: {progression.get('vsPrevious', 'unknown')})"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def exercise_history_markdown(store: WorkoutHistoryStore, exercise_id: str) -> str:
    exercise = store.exercises_by_id().get(str(exercise_id))
    if not exercise:
        raise ValueError(f"Exercise not found: {exercise_id}")
    all_sets = [item for item in store.sets_for_exercise(str(exercise_id)) if is_insight_comparison_set(item)]
    sessions_by_id = store.sessions_by_id()
    session_ids = sorted(
        {str(item.get("workoutHistoryId")) for item in all_sets if item.get("workoutHistoryId")},
        key=lambda sid: (
            str(sessions_by_id.get(sid, {}).get("date") or ""),
            str(sessions_by_id.get(sid, {}).get("time") or ""),
        ),
    )
    lines = [
        f"# {exercise.get('name')}",
        f"Type: {exercise.get('exerciseType') or 'unknown'}",
        "",
    ]
    config = exercise_config_data(store, exercise)
    lines.extend([
        "#### Exercise Config",
        f"- Progression mode: {config.get('progression_mode') or 'unknown'}",
        f"- Rep range: {config.get('min_reps') or 0}-{config.get('max_reps') or 0}",
        f"- Load range: {format_number(config.get('min_load_percent'))}-{format_number(config.get('max_load_percent'))}%",
        f"- Muscles: {', '.join(config.get('muscle_groups') or []) or 'none'}",
        f"- Notes: {config.get('notes') or 'none'}",
        "",
    ])
    equipment = describe_exercise_equipment(exercise, store)
    if equipment:
        lines.extend(["#### Equipment", equipment, ""])
    if exercise.get("exerciseType") == "BODY_WEIGHT":
        pct = exercise.get("bodyWeightPercentage")
        lines.extend([
            "#### Body Weight Load",
            f"- Relative BW = session BW x {format_number(pct)}%",
            "- Set load = relative BW +/- equipment weight",
            "",
        ])
    lines.append(athlete_context_markdown(store).rstrip())
    if session_ids:
        first = sessions_by_id.get(session_ids[0], {})
        last = sessions_by_id.get(session_ids[-1], {})
        lines.append(f"Sessions: {len(session_ids)} | Range: {first.get('date')} to {last.get('date')}")
        lines.append("")

    workouts = store.workouts_by_id()
    for index, session_id in enumerate(session_ids, start=1):
        session = sessions_by_id.get(session_id) or {}
        workout = workouts.get(str(session.get("workoutId"))) or {}
        active_sets = [
            item for item in all_sets
            if str(item.get("workoutHistoryId")) == session_id
        ]
        progression = store.progression_for(session_id, str(exercise_id))
        lines.extend([
            f"## S{index} ({session.get('date')})",
            "### Performance",
            f"- Sets: {', '.join(set_token(item, exercise, store) for item in active_sets)}",
            f"- Top set: {top_set_token(active_sets, exercise, store)}",
            f"- Total reps: {sum(reps_for_set(item) for item in active_sets)}",
            f"- Total volume: {format_number(sum(volume_for_set(item, exercise) for item in active_sets))} kg",
            f"- Rest: {compact_rest_summary(store.rest_records_for_session(session_id, str(exercise_id))) or 'none'}",
            "",
            "### Context",
            f"- Workout: {workout.get('name') or 'Unknown Workout'}",
            f"- Session duration: {format_duration(session.get('duration'))}",
        ])
        if progression:
            expected = progression.get("expectedSets") or []
            expected_line = ", ".join(f"{format_number(item.get('weight'))}x{item.get('reps')}" for item in expected)
            lines.extend([
                "",
                "### Target",
                f"- Planned sets: {expected_line or 'none'}",
                (
                    "- Outcome: "
                    f"{progression.get('progressionState', 'unknown')} "
                    f"(vs expected: {progression.get('vsExpected', 'unknown')}, "
                    f"vs previous: {progression.get('vsPrevious', 'unknown')})"
                ),
            ])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def is_active_set(set_history: dict[str, Any]) -> bool:
    if set_history.get("skipped") is True:
        return False
    return (set_history.get("setData") or {}).get("type") in {
        "WeightSetData",
        "BodyWeightSetData",
        "TimedDurationSetData",
        "EnduranceSetData",
    }


def is_insight_comparison_set(set_history: dict[str, Any]) -> bool:
    if set_history.get("skipped") is True:
        return False
    set_data = set_history.get("setData") or {}
    set_type = set_data.get("type")
    if set_type == "RestSetData":
        return False
    if set_type in {"WeightSetData", "BodyWeightSetData"}:
        return set_data.get("subCategory", "WorkSet") not in {
            "WarmupSet",
            "CalibrationPendingSet",
            "CalibrationSet",
        }
    return set_type in {"TimedDurationSetData", "EnduranceSetData"}


def reps_for_set(set_history: dict[str, Any]) -> int:
    set_data = set_history.get("setData") or {}
    return int(set_data.get("actualReps") or 0)


def load_for_set(set_history: dict[str, Any], exercise: dict[str, Any]) -> float:
    set_data = set_history.get("setData") or {}
    set_type = set_data.get("type")
    if set_type == "WeightSetData":
        return float(set_data.get("actualWeight") or 0)
    if set_type == "BodyWeightSetData":
        if set_data.get("relativeBodyWeightInKg") is not None:
            return float(set_data.get("relativeBodyWeightInKg") or 0) + float(set_data.get("additionalWeight") or 0)
        body_weight_pct = float(exercise.get("bodyWeightPercentage") or 100)
        return float(set_data.get("additionalWeight") or 0) + body_weight_pct
    return 0.0


def volume_for_set(set_history: dict[str, Any], exercise: dict[str, Any]) -> float:
    set_data = set_history.get("setData") or {}
    if set_data.get("volume") is not None:
        return float(set_data.get("volume") or 0)
    return load_for_set(set_history, exercise) * reps_for_set(set_history)


def set_token(set_history: dict[str, Any], exercise: dict[str, Any], store: WorkoutHistoryStore) -> str:
    set_data = set_history.get("setData") or {}
    set_type = set_data.get("type")
    if set_type == "WeightSetData":
        return f"{format_number(set_data.get('actualWeight'))}x{set_data.get('actualReps', 0)}"
    if set_type == "BodyWeightSetData":
        additional = float(set_data.get("additionalWeight") or 0)
        effective = set_data.get("relativeBodyWeightInKg")
        pct = set_data.get("bodyWeightPercentageSnapshot") or exercise.get("bodyWeightPercentage")
        total = float(effective or 0) + additional
        if pct and effective:
            session_bw = float(effective) / (float(pct) / 100)
            base = f"{format_number(effective)} kg relative BW ({format_number(session_bw)} kg x {format_number(pct)}%)"
        else:
            base = f"{format_number(effective)} kg relative BW"
        if additional:
            op = "+" if additional > 0 else "-"
            base += f" {op} {format_number(abs(additional))} kg equipment"
        return f"{base} = {format_number(total)} kg x {set_data.get('actualReps', 0)}"
    if set_type in {"TimedDurationSetData", "EnduranceSetData"}:
        start_ms = int(set_data.get("startTimer") or 0)
        end_ms = int(set_data.get("endTimer") or 0)
        elapsed = abs(start_ms - end_ms) // 1000
        return format_duration(elapsed)
    return set_type or "unknown"


def top_set_token(sets: list[dict[str, Any]], exercise: dict[str, Any], store: WorkoutHistoryStore) -> str:
    if not sets:
        return "none"
    top = max(sets, key=lambda item: (load_for_set(item, exercise), reps_for_set(item)))
    return set_token(top, exercise, store)


def compact_rest_summary(rests: list[dict[str, Any]]) -> str:
    if not rests:
        return ""
    tokens = []
    for rest in rests:
        set_data = rest.get("setData") or {}
        if set_data.get("type") == "RestSetData":
            planned = max(int(set_data.get("startTimer") or 0), 0)
            elapsed = elapsed_seconds_from_bounds(rest.get("startTime"), rest.get("endTime"))
            if elapsed is not None:
                elapsed = min(max(elapsed, 0), planned)
        else:
            elapsed = rest.get("elapsedSeconds") or rest.get("durationSeconds") or rest.get("timeInSeconds")
            planned = rest.get("plannedSeconds") or rest.get("plannedTimeInSeconds")
        if elapsed and planned and elapsed != planned:
            tokens.append(f"{format_duration_for_markdown(elapsed)} elapsed ({format_duration_for_markdown(planned)} planned)")
        elif elapsed is not None:
            tokens.append(f"{format_duration_for_markdown(elapsed)} elapsed")
        elif planned:
            tokens.append(f"{format_duration_for_markdown(planned)} planned")
    return ", ".join(tokens) if tokens else f"{len(rests)} rest records"


def elapsed_seconds_from_bounds(start_time: Any, end_time: Any) -> int | None:
    if not start_time or not end_time:
        return None
    try:
        start = datetime.fromisoformat(str(start_time))
        end = datetime.fromisoformat(str(end_time))
    except ValueError:
        return None
    seconds = int((end - start).total_seconds())
    return seconds if seconds >= 0 else None


def format_duration_for_markdown(seconds: int) -> str:
    total = max(int(seconds), 0)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def describe_exercise_equipment(exercise: dict[str, Any], store: WorkoutHistoryStore) -> str:
    equipment_id = exercise.get("equipmentId")
    if not equipment_id:
        return ""
    equipment = store.equipment_by_id().get(str(equipment_id)) or store.accessory_equipment_by_id().get(str(equipment_id))
    if not equipment:
        return f"- Equipment id: `{equipment_id}`"
    details = [f"- Equipment: {equipment.get('name')} ({equipment.get('type', 'unknown')})"]
    if equipment.get("barWeight") is not None:
        details.append(f"- Bar weight: {format_number(equipment.get('barWeight'))} kg")
    plates = equipment.get("availablePlates") or []
    if plates:
        weights = ", ".join(format_number(plate.get("weight")) for plate in plates)
        details.append(f"- Plates: {weights} kg")
    return "\n".join(details)
