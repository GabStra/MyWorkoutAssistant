#!/usr/bin/env python3
"""Merge MyWorkoutAssistant AppBackup JSON files into one unified backup.

The script scans one or more files/directories, loads every valid AppBackup JSON,
orders them from oldest to newest, and merges entities while preferring the latest
revision of each record. It is intended for recovery scenarios where some workout
histories were deleted in newer backups and need to be restored from older ones.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


JSONDict = dict[str, Any]
JSONList = list[Any]

BACKUP_TIMESTAMP_PATTERNS = (
    re.compile(r"workout_store_(\d{8}_\d{6})\.json$", re.IGNORECASE),
    re.compile(r"workout_store_(\d{8}_\d{6})_\d+\.json$", re.IGNORECASE),
)


@dataclass(frozen=True)
class LoadedBackup:
    path: Path
    sort_key: tuple[float, str]
    data: JSONDict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge MyWorkoutAssistant AppBackup JSON files and restore the latest "
            "unified set of workout histories."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=["."],
        help="Backup files or directories to scan. Defaults to the current directory.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="merged_workout_store_backup.json",
        help="Output file path for the merged AppBackup JSON.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan input directories recursively.",
    )
    parser.add_argument(
        "--include-workout-store-only",
        action="store_true",
        help=(
            "Also accept WorkoutStore-only JSON files as sources for WorkoutStore "
            "metadata. They do not contribute histories."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-file diagnostics while loading and merging.",
    )
    return parser.parse_args()


def extract_backup_timestamp(path: Path) -> float | None:
    for pattern in BACKUP_TIMESTAMP_PATTERNS:
        match = pattern.search(path.name)
        if match:
            parsed = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
            return parsed.timestamp()
    return None


def build_sort_key(path: Path) -> tuple[float, str]:
    timestamp = extract_backup_timestamp(path)
    if timestamp is None:
        timestamp = path.stat().st_mtime
    return (timestamp, str(path).lower())


def discover_input_files(inputs: list[str], recursive: bool) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()

    for raw_input in inputs:
        path = Path(raw_input).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Input path does not exist: {path}")

        if path.is_file():
            resolved = path.resolve()
            if resolved not in seen:
                discovered.append(resolved)
                seen.add(resolved)
            continue

        iterator = path.rglob("*.json") if recursive else path.glob("*.json")
        for candidate in iterator:
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if resolved not in seen:
                discovered.append(resolved)
                seen.add(resolved)

    return sorted(discovered, key=build_sort_key)


def read_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def classify_backup(document: Any) -> str:
    if not isinstance(document, dict):
        return "unknown"
    if "WorkoutStore" in document:
        return "app_backup"
    if "workouts" in document:
        return "workout_store"
    return "unknown"


def safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.endswith("u"):
            stripped = stripped[:-1]
        if stripped.isdigit():
            return int(stripped)
    return None


def compare_optional_datetimes(left: Any, right: Any) -> int:
    if left == right:
        return 0
    if left is None:
        return -1
    if right is None:
        return 1
    left_text = str(left)
    right_text = str(right)
    if left_text < right_text:
        return -1
    if left_text > right_text:
        return 1
    return 0


def choose_latest_record(current: JSONDict, candidate: JSONDict) -> JSONDict:
    current_version = safe_int(current.get("version"))
    candidate_version = safe_int(candidate.get("version"))

    if current_version is not None or candidate_version is not None:
        current_version = -1 if current_version is None else current_version
        candidate_version = -1 if candidate_version is None else candidate_version
        if candidate_version > current_version:
            return candidate
        if candidate_version < current_version:
            return current

    for timestamp_field in ("updatedAt", "modifiedAt", "endTime", "startTime", "timestamp"):
        comparison = compare_optional_datetimes(
            current.get(timestamp_field),
            candidate.get(timestamp_field),
        )
        if comparison < 0:
            return candidate
        if comparison > 0:
            return current

    return candidate


def merge_list_by_id(existing: JSONList, incoming: JSONList) -> JSONList:
    merged: dict[str, JSONDict] = {}
    order: list[str] = []

    for item in existing + incoming:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if item_id is None:
            continue
        item_id_text = str(item_id)
        if item_id_text not in merged:
            merged[item_id_text] = deepcopy(item)
            order.append(item_id_text)
            continue
        merged[item_id_text] = deepcopy(choose_latest_record(merged[item_id_text], item))

    return [merged[item_id] for item_id in order]


def merge_workout_store(current: JSONDict | None, candidate: JSONDict) -> JSONDict:
    if current is None:
        return deepcopy(candidate)

    merged = deepcopy(current)
    list_fields = ("workouts", "equipments", "accessoryEquipments", "workoutPlans")

    for field in list_fields:
        merged[field] = merge_list_by_id(
            current.get(field, []) or [],
            candidate.get(field, []) or [],
        )

    for field, value in candidate.items():
        if field in list_fields:
            continue
        merged[field] = deepcopy(value)

    return merged


def merge_top_level_records(backups: list[LoadedBackup]) -> JSONDict:
    workout_store: JSONDict | None = None
    workout_histories: dict[str, JSONDict] = {}
    set_histories: dict[str, JSONDict] = {}
    exercise_infos: dict[str, JSONDict] = {}
    workout_schedules: dict[str, JSONDict] = {}
    workout_records: dict[str, JSONDict] = {}
    exercise_session_progressions: dict[str, JSONDict] = {}
    error_logs: dict[str, JSONDict] = {}

    for loaded in backups:
        backup = loaded.data
        workout_store_data = backup.get("WorkoutStore")
        if isinstance(workout_store_data, dict):
            workout_store = merge_workout_store(workout_store, workout_store_data)

        merge_record_map(workout_histories, backup.get("WorkoutHistories", []) or [])
        merge_record_map(set_histories, backup.get("SetHistories", []) or [])
        merge_record_map(exercise_infos, backup.get("ExerciseInfos", []) or [])
        merge_record_map(workout_schedules, backup.get("WorkoutSchedules", []) or [])
        merge_record_map(workout_records, backup.get("WorkoutRecords", []) or [])
        merge_record_map(
            exercise_session_progressions,
            backup.get("ExerciseSessionProgressions", []) or [],
        )
        merge_record_map(error_logs, backup.get("ErrorLogs", []) or [])

    if workout_store is None:
        raise ValueError("No AppBackup WorkoutStore content was found in the provided files.")

    canonical_set_histories = canonicalize_set_histories(set_histories)
    valid_workout_history_ids = set(workout_histories)

    filtered_set_histories = {
        item_id: item
        for item_id, item in canonical_set_histories.items()
        if str(item.get("workoutHistoryId")) in valid_workout_history_ids
    }
    filtered_workout_records = {
        item_id: item
        for item_id, item in workout_records.items()
        if str(item.get("workoutHistoryId")) in valid_workout_history_ids
    }
    filtered_progressions = {
        item_id: item
        for item_id, item in exercise_session_progressions.items()
        if str(item.get("workoutHistoryId")) in valid_workout_history_ids
    }
    filtered_exercise_infos = {
        item_id: canonicalize_exercise_info(item, filtered_set_histories, valid_workout_history_ids)
        for item_id, item in exercise_infos.items()
    }

    return {
        "WorkoutStore": workout_store,
        "WorkoutHistories": sort_workout_histories(list(workout_histories.values())),
        "SetHistories": sort_set_histories(list(filtered_set_histories.values())),
        "ExerciseInfos": sort_by_id(list(filtered_exercise_infos.values())),
        "WorkoutSchedules": sort_by_id(list(workout_schedules.values())),
        "WorkoutRecords": sort_workout_records(list(filtered_workout_records.values())),
        "ExerciseSessionProgressions": sort_progressions(list(filtered_progressions.values())),
        "ErrorLogs": sort_error_logs(list(error_logs.values())) or None,
    }


def merge_record_map(target: dict[str, JSONDict], items: Any) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if item_id is None:
            continue
        item_id_text = str(item_id)
        if item_id_text in target:
            target[item_id_text] = deepcopy(choose_latest_record(target[item_id_text], item))
        else:
            target[item_id_text] = deepcopy(item)


def canonicalize_set_histories(set_histories: dict[str, JSONDict]) -> dict[str, JSONDict]:
    canonical: dict[str, JSONDict] = {}
    for item_id, item in set_histories.items():
        canonical[item_id] = deepcopy(item)
    return canonical


def canonicalize_exercise_info(
    exercise_info: JSONDict,
    set_histories: dict[str, JSONDict],
    valid_workout_history_ids: set[str],
) -> JSONDict:
    canonical = deepcopy(exercise_info)
    for field in ("bestSession", "lastSuccessfulSession"):
        session = canonical.get(field)
        if not isinstance(session, list):
            canonical[field] = []
            continue

        canonical_session: list[JSONDict] = []
        for item in session:
            if not isinstance(item, dict):
                continue
            set_id = item.get("id")
            set_id_text = str(set_id) if set_id is not None else None
            if set_id_text and set_id_text in set_histories:
                resolved = deepcopy(set_histories[set_id_text])
            else:
                resolved = deepcopy(item)

            workout_history_id = resolved.get("workoutHistoryId")
            if str(workout_history_id) not in valid_workout_history_ids:
                continue
            canonical_session.append(resolved)

        canonical[field] = sort_set_histories(canonical_session)

    return canonical


def sort_by_id(items: list[JSONDict]) -> list[JSONDict]:
    return sorted(items, key=lambda item: str(item.get("id", "")))


def sort_workout_histories(items: list[JSONDict]) -> list[JSONDict]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("startTime", "")),
            str(item.get("date", "")),
            str(item.get("time", "")),
            str(item.get("id", "")),
        ),
    )


def sort_set_histories(items: list[JSONDict]) -> list[JSONDict]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("workoutHistoryId", "")),
            safe_int(item.get("executionSequence")) if safe_int(item.get("executionSequence")) is not None else sys.maxsize,
            safe_int(item.get("order")) if safe_int(item.get("order")) is not None else sys.maxsize,
            str(item.get("id", "")),
        ),
    )


def sort_workout_records(items: list[JSONDict]) -> list[JSONDict]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("workoutHistoryId", "")),
            safe_int(item.get("setIndex")) if safe_int(item.get("setIndex")) is not None else sys.maxsize,
            str(item.get("id", "")),
        ),
    )


def sort_progressions(items: list[JSONDict]) -> list[JSONDict]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("workoutHistoryId", "")),
            str(item.get("exerciseId", "")),
            str(item.get("id", "")),
        ),
    )


def sort_error_logs(items: list[JSONDict]) -> list[JSONDict]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("timestamp", "")),
            str(item.get("id", "")),
        ),
    )


def maybe_load_backup(
    path: Path,
    include_workout_store_only: bool,
    verbose: bool,
) -> LoadedBackup | None:
    try:
        document = read_json_file(path)
    except Exception as exc:
        if verbose:
            print(f"Skipping unreadable JSON: {path} ({exc})", file=sys.stderr)
        return None

    file_type = classify_backup(document)
    if file_type == "app_backup":
        if verbose:
            print(f"Loaded AppBackup: {path}", file=sys.stderr)
        return LoadedBackup(path=path, sort_key=build_sort_key(path), data=document)

    if file_type == "workout_store" and include_workout_store_only:
        wrapped = {
            "WorkoutStore": document,
            "WorkoutHistories": [],
            "SetHistories": [],
            "ExerciseInfos": [],
            "WorkoutSchedules": [],
            "WorkoutRecords": [],
            "ExerciseSessionProgressions": [],
            "ErrorLogs": None,
        }
        if verbose:
            print(f"Loaded WorkoutStore-only file: {path}", file=sys.stderr)
        return LoadedBackup(path=path, sort_key=build_sort_key(path), data=wrapped)

    if verbose:
        print(f"Skipping non-backup JSON: {path}", file=sys.stderr)
    return None


def write_output(path: Path, data: JSONDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def print_summary(output_path: Path, merged: JSONDict, backups: list[LoadedBackup]) -> None:
    print(f"Merged {len(backups)} backup file(s) into {output_path}")
    print(f"  WorkoutHistories: {len(merged['WorkoutHistories'])}")
    print(f"  SetHistories: {len(merged['SetHistories'])}")
    print(f"  ExerciseInfos: {len(merged['ExerciseInfos'])}")
    print(f"  WorkoutSchedules: {len(merged['WorkoutSchedules'])}")
    print(f"  WorkoutRecords: {len(merged['WorkoutRecords'])}")
    print(f"  ExerciseSessionProgressions: {len(merged['ExerciseSessionProgressions'])}")
    error_logs = merged.get("ErrorLogs") or []
    print(f"  ErrorLogs: {len(error_logs)}")


def main() -> int:
    args = parse_args()
    try:
        candidate_files = discover_input_files(args.inputs, args.recursive)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    loaded_backups = [
        loaded
        for path in candidate_files
        if (loaded := maybe_load_backup(path, args.include_workout_store_only, args.verbose)) is not None
    ]
    loaded_backups.sort(key=lambda loaded: loaded.sort_key)

    if not loaded_backups:
        print("No valid AppBackup JSON files were found.", file=sys.stderr)
        return 1

    merged = merge_top_level_records(loaded_backups)
    output_path = Path(args.output).expanduser().resolve()
    write_output(output_path, merged)
    print_summary(output_path, merged, loaded_backups)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
