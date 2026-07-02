from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


MOVEMENT_FORMAT = "wear_skeleton_json_v1"
MOVEMENT_COMPRESSION = "gzip+base64"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Attach generated wear skeleton movement JSON files to a workout-plan package "
            "using a workout_motion_generation_summary.json file."
        )
    )
    parser.add_argument(
        "--workout-plan-package-json",
        required=True,
        help="Source WorkoutPlanPackage JSON to enrich.",
    )
    parser.add_argument(
        "--motion-summary-json",
        required=True,
        help="workout_motion_generation_summary.json produced by run_exercise_motion_workout_plan.ps1.",
    )
    parser.add_argument(
        "--output-json",
        required=True,
        help="Destination WorkoutPlanPackage JSON with movement refs and movement backups.",
    )
    parser.add_argument(
        "--movement-id-prefix",
        default="exercise-motion",
        help="Prefix used when creating ExerciseMovementRef movementId values.",
    )
    parser.add_argument(
        "--strict-id-match",
        action="store_true",
        help="Do not fall back to normalized exercise-name matching when exercise ids do not match.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Write the package even when no generated movements can be attached.",
    )
    return parser


def load_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def read_text_file(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig") as handle:
        return handle.read()


def normalize_key(value: Any) -> str:
    return str(value).strip().lower()


def normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def movement_id_for(prefix: str, exercise_id: Any, exercise_name: Any) -> str:
    raw_key = str(exercise_id).strip() if exercise_id is not None and str(exercise_id).strip() else ""
    if not raw_key:
        raw_key = normalize_name(exercise_name) or "movement"
    return f"{prefix}:{raw_key}"


def gzip_base64(data: str) -> str:
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as gzip_file:
        gzip_file.write(data.encode("utf-8"))
    return base64.b64encode(output.getvalue()).decode("ascii")


def iter_package_exercises(workout_plan_package: dict[str, Any]):
    for workout_index, workout in enumerate(workout_plan_package.get("workouts") or []):
        if not isinstance(workout, dict):
            continue
        for component_index, component in enumerate(workout.get("workoutComponents") or []):
            yield from iter_component_exercises(
                component,
                f"workouts[{workout_index}].workoutComponents[{component_index}]",
            )


def iter_component_exercises(component: Any, location: str):
    if not isinstance(component, dict):
        return

    component_type = component.get("type")
    if component_type == "Exercise":
        yield component, location
        return

    if component_type == "Superset":
        for exercise_index, exercise in enumerate(component.get("exercises") or []):
            if isinstance(exercise, dict):
                yield exercise, f"{location}.exercises[{exercise_index}]"
        return

    if "sets" in component and "name" in component:
        yield component, location


def resolve_motion_path(path_value: Any, summary_path: Path, summary: dict[str, Any]) -> Path | None:
    if path_value is None:
        return None

    raw_path = str(path_value).strip()
    if not raw_path:
        return None

    path = Path(raw_path)
    candidates = [path]

    if not path.is_absolute():
        candidates.append(summary_path.parent / path)
        workspace_root = summary.get("workspaceRoot")
        if workspace_root:
            candidates.append(Path(str(workspace_root)) / path)

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return None


def existing_backups_by_key(workout_plan_package: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    backups: dict[tuple[str, str], dict[str, Any]] = {}
    for field_name in ("exerciseMovements", "ExerciseMovements"):
        for backup in workout_plan_package.get(field_name) or []:
            if not isinstance(backup, dict):
                continue
            movement_ref = backup.get("movementRef")
            if not isinstance(movement_ref, dict):
                continue
            movement_id = str(movement_ref.get("movementId") or "").strip()
            content_hash = str(movement_ref.get("contentHash") or "").strip().lower()
            if movement_id and content_hash:
                backups[(movement_id, content_hash)] = backup
    return backups


def main() -> int:
    args = build_parser().parse_args()

    package_path = Path(args.workout_plan_package_json).resolve()
    summary_path = Path(args.motion_summary_json).resolve()
    output_path = Path(args.output_json).resolve()

    workout_plan_package = load_json_file(package_path)
    if not isinstance(workout_plan_package, dict):
        raise ValueError("Workout-plan package JSON root must be an object.")

    summary = load_json_file(summary_path)
    if not isinstance(summary, dict):
        raise ValueError("Motion summary JSON root must be an object.")

    id_index: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    name_index: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for exercise, location in iter_package_exercises(workout_plan_package):
        exercise_id = exercise.get("id")
        if exercise_id is not None and str(exercise_id).strip():
            id_index[normalize_key(exercise_id)].append((exercise, location))

        exercise_name = exercise.get("name")
        normalized_name = normalize_name(exercise_name)
        if normalized_name:
            name_index[normalized_name].append((exercise, location))

    movement_backups = existing_backups_by_key(workout_plan_package)
    attached_count = 0
    warning_count = 0

    for summary_item in summary.get("exercises") or []:
        if not isinstance(summary_item, dict):
            continue

        exercise_id = summary_item.get("exerciseId")
        exercise_name = summary_item.get("exerciseName")
        selected_path = resolve_motion_path(summary_item.get("selectedWearSkeletonPath"), summary_path, summary)
        if selected_path is None:
            continue

        matches = []
        match_source = ""
        if exercise_id is not None and str(exercise_id).strip():
            matches = id_index.get(normalize_key(exercise_id), [])
            match_source = "id"

        if not matches and not args.strict_id_match:
            normalized_name = normalize_name(exercise_name)
            if normalized_name:
                matches = name_index.get(normalized_name, [])
                match_source = "name"

        if not matches:
            warning_count += 1
            print(
                f"warning: no package exercise matched summary exercise "
                f"id={exercise_id!r} name={exercise_name!r}",
                file=sys.stderr,
            )
            continue

        movement_json = read_text_file(selected_path)
        try:
            json.loads(movement_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Selected wear skeleton is not valid JSON: {selected_path}") from exc

        content_hash = hashlib.sha256(movement_json.encode("utf-8")).hexdigest()
        movement_id = movement_id_for(args.movement_id_prefix, exercise_id, exercise_name)
        movement_ref = {
            "movementId": movement_id,
            "contentHash": content_hash,
            "format": MOVEMENT_FORMAT,
            "version": 1,
        }

        for exercise, _location in matches:
            exercise["movementRef"] = movement_ref
            attached_count += 1

        movement_backups[(movement_id, content_hash)] = {
            "movementRef": movement_ref,
            "compressedJsonBase64": gzip_base64(movement_json),
            "compression": MOVEMENT_COMPRESSION,
        }

        print(
            f"attached {match_source}: {exercise_name or exercise_id} -> "
            f"{len(matches)} exercise(s), {selected_path}"
        )

    workout_plan_package["exerciseMovements"] = list(movement_backups.values())
    workout_plan_package.pop("ExerciseMovements", None)

    if attached_count == 0 and not args.allow_empty:
        raise RuntimeError(
            "No generated movements were attached. Check that the summary has selectedWearSkeletonPath "
            "entries and that exercise ids or names match the workout-plan package."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(workout_plan_package, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(
        f"wrote {output_path} with {attached_count} exercise movement ref attachment(s), "
        f"{len(movement_backups)} movement backup(s), {warning_count} warning(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
