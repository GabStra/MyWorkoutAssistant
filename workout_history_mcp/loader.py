from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_PATH = REPO_ROOT / "merged_workout_store_backup.json"


def backup_path_from_env() -> Path:
    configured = os.environ.get("MYWORKOUT_BACKUP_PATH")
    return Path(configured).expanduser() if configured else DEFAULT_BACKUP_PATH


def load_backup(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    backup_path = Path(path).expanduser() if path else backup_path_from_env()
    with backup_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _as_list(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def _component_exercises(component: dict[str, Any]) -> list[dict[str, Any]]:
    component_type = component.get("type")
    if component_type == "Exercise":
        return [component]
    if component_type == "Superset":
        return [ex for ex in _as_list(component.get("exercises")) if ex.get("type") == "Exercise"]
    return []


def _sort_key_for_session(session: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(session.get("date") or ""),
        str(session.get("time") or ""),
        str(session.get("startTime") or ""),
    )


def _sort_number(value: Any) -> int | float:
    if isinstance(value, dict):
        value = value.get("data")
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _exercise_definition_rank(workout: dict[str, Any], exercise: dict[str, Any]) -> tuple[int, int, int]:
    is_current_active_workout = bool(workout.get("isActive", True) and workout.get("enabled", True))
    is_terminal_version = workout.get("nextVersionId") is None
    is_enabled_exercise = bool(exercise.get("enabled", True))
    return (
        1 if is_current_active_workout else 0,
        1 if is_terminal_version else 0,
        1 if is_enabled_exercise else 0,
    )


@dataclass(frozen=True)
class WorkoutHistoryStore:
    backup: dict[str, Any]

    @property
    def workout_store(self) -> dict[str, Any]:
        return self.backup.get("WorkoutStore") or {}

    @property
    def workouts(self) -> list[dict[str, Any]]:
        return _as_list(self.workout_store.get("workouts"))

    @property
    def workout_histories(self) -> list[dict[str, Any]]:
        return _as_list(self.backup.get("WorkoutHistories"))

    @property
    def set_histories(self) -> list[dict[str, Any]]:
        return _as_list(self.backup.get("SetHistories"))

    @property
    def rest_histories(self) -> list[dict[str, Any]]:
        return _as_list(self.backup.get("RestHistories"))

    @property
    def progressions(self) -> list[dict[str, Any]]:
        return _as_list(self.backup.get("ExerciseSessionProgressions"))

    @property
    def equipment(self) -> list[dict[str, Any]]:
        return _as_list(self.workout_store.get("equipments"))

    @property
    def accessory_equipment(self) -> list[dict[str, Any]]:
        return _as_list(self.workout_store.get("accessoryEquipments"))

    def workouts_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(workout.get("id")): workout for workout in self.workouts}

    def workout_by_id(self, workout_id: str | None) -> dict[str, Any] | None:
        if workout_id is None:
            return None
        return self.workouts_by_id().get(str(workout_id))

    def exercises_by_id(self) -> dict[str, dict[str, Any]]:
        exercises: dict[str, dict[str, Any]] = {}
        ranks: dict[str, tuple[int, int, int]] = {}
        for workout in self.workouts:
            for component in _as_list(workout.get("workoutComponents")):
                for exercise in _component_exercises(component):
                    exercise_id = exercise.get("id")
                    if not exercise_id:
                        continue
                    key = str(exercise_id)
                    rank = _exercise_definition_rank(workout, exercise)
                    if key not in exercises or rank > ranks[key]:
                        exercises[key] = exercise
                        ranks[key] = rank
        return exercises

    def workout_names_for_exercise(self, exercise_id: str) -> list[str]:
        names: list[str] = []
        for workout in self.workouts:
            for component in _as_list(workout.get("workoutComponents")):
                if any(str(ex.get("id")) == exercise_id for ex in _component_exercises(component)):
                    name = workout.get("name")
                    if name and name not in names:
                        names.append(str(name))
        return names

    def equipment_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(item.get("id")): item for item in self.equipment}

    def accessory_equipment_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(item.get("id")): item for item in self.accessory_equipment}

    def equipment_or_accessory_by_id(self) -> dict[str, dict[str, Any]]:
        return {
            **self.equipment_by_id(),
            **self.accessory_equipment_by_id(),
        }

    def sessions_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(session.get("id")): session for session in self.workout_histories}

    def completed_sessions(self) -> list[dict[str, Any]]:
        return sorted(
            [session for session in self.workout_histories if session.get("isDone") is True],
            key=_sort_key_for_session,
        )

    def sets_for_session(self, workout_history_id: str) -> list[dict[str, Any]]:
        sets = [
            set_history for set_history in self.set_histories
            if str(set_history.get("workoutHistoryId")) == str(workout_history_id)
        ]
        return sorted(
            sets,
            key=lambda item: (
                item.get("executionSequence") is None,
                _sort_number(item.get("executionSequence")),
                _sort_number(item.get("order")),
                str(item.get("startTime") or ""),
            ),
        )

    def sets_for_exercise(self, exercise_id: str) -> list[dict[str, Any]]:
        return [
            set_history for set_history in self.set_histories
            if str(set_history.get("exerciseId")) == str(exercise_id)
        ]

    def rests_for_session(self, workout_history_id: str, exercise_id: str | None = None) -> list[dict[str, Any]]:
        rests = [
            rest for rest in self.rest_histories
            if str(rest.get("workoutHistoryId")) == str(workout_history_id)
        ]
        if exercise_id is not None:
            rests = [rest for rest in rests if str(rest.get("exerciseId")) == str(exercise_id)]
        return sorted(rests, key=lambda item: (_sort_number(item.get("order")), str(item.get("startTime") or "")))

    def rest_records_for_session(self, workout_history_id: str, exercise_id: str | None = None) -> list[dict[str, Any]]:
        rest_set_histories = [
            set_history for set_history in self.set_histories
            if (
                str(set_history.get("workoutHistoryId")) == str(workout_history_id)
                and (set_history.get("setData") or {}).get("type") == "RestSetData"
            )
        ]
        if exercise_id is not None:
            rest_set_histories = [
                rest for rest in rest_set_histories
                if str(rest.get("exerciseId")) == str(exercise_id)
            ]
        return sorted(
            [*self.rests_for_session(workout_history_id, exercise_id), *rest_set_histories],
            key=lambda item: (
                item.get("executionSequence") is None,
                _sort_number(item.get("executionSequence")),
                _sort_number(item.get("order")),
                str(item.get("startTime") or ""),
            ),
        )

    def progression_for(self, workout_history_id: str, exercise_id: str) -> dict[str, Any] | None:
        for progression in self.progressions:
            if (
                str(progression.get("workoutHistoryId")) == str(workout_history_id)
                and str(progression.get("exerciseId")) == str(exercise_id)
            ):
                return progression
        return None

    def training_date_range(self) -> tuple[str | None, str | None]:
        sessions = self.completed_sessions()
        if not sessions:
            return None, None
        return str(sessions[0].get("date")), str(sessions[-1].get("date"))

    def athlete_profile(self) -> dict[str, Any]:
        workout_store = self.workout_store
        birth_year = workout_store.get("birthDateYear")
        current_age = date.today().year - int(birth_year) if birth_year else None
        start_date, end_date = self.training_date_range()
        exercise_ids = {
            str(set_history.get("exerciseId"))
            for set_history in self.set_histories
            if set_history.get("exerciseId") is not None and _is_active_set(set_history)
        }
        completed_sessions = self.completed_sessions()
        return {
            "birth_year": birth_year,
            "age": current_age,
            "body_weight_kg": workout_store.get("weightKg"),
            "measured_max_heart_rate": workout_store.get("measuredMaxHeartRate"),
            "resting_heart_rate": workout_store.get("restingHeartRate"),
            "progression_percentage_amount": workout_store.get("progressionPercentageAmount"),
            "training_start_date": start_date,
            "training_end_date": end_date,
            "latest_workout_date": end_date,
            "completed_session_count": len(completed_sessions),
            "total_recorded_sets": len([item for item in self.set_histories if _is_active_set(item)]),
            "exercise_count": len(exercise_ids),
            "available_equipment": [item.get("name") for item in self.equipment if item.get("name")],
            "available_accessories": [item.get("name") for item in self.accessory_equipment if item.get("name")],
        }


def _is_active_set(set_history: dict[str, Any]) -> bool:
    if set_history.get("skipped") is True:
        return False
    set_data = set_history.get("setData") or {}
    set_type = set_data.get("type")
    if set_type in {"WeightSetData", "BodyWeightSetData"}:
        return set_data.get("subCategory", "WorkSet") not in {
            "WarmupSet",
            "CalibrationPendingSet",
            "CalibrationSet",
        }
    return set_type in {"TimedDurationSetData", "EnduranceSetData"}


def load_store(path: str | os.PathLike[str] | None = None) -> WorkoutHistoryStore:
    return WorkoutHistoryStore(load_backup(path))
