"""Export a provisional target for review and persist an explicitly approved definition."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .youtube import (
    exercise_motion_context_action_definition,
    extract_exercise_id,
    extract_exercise_name,
    load_workout_plan_exercises,
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _target(plan_path, exercise_id, equipment_path):
    matches = [item for item in load_workout_plan_exercises(
        plan_path, include_disabled=True, equipment_path=equipment_path,
    ) if item.exercise_id == exercise_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one exercise with id {exercise_id!r}; found {len(matches)}")
    return matches[0]


def _exercise_nodes(node, target):
    if isinstance(node, list):
        for child in node:
            yield from _exercise_nodes(child, target)
    elif isinstance(node, dict):
        if (extract_exercise_id(node) == target.exercise_id
                and extract_exercise_name(node) in {target.name, target.source_name, target.equipment_qualified_name}):
            yield node
            return
        for key in ("WorkoutStore", "workouts", "exerciseDefinitions", "workoutComponents", "components",
                    "children", "items", "supersetExercises", "exercises", "exerciseComponents"):
            if key in node:
                yield from _exercise_nodes(node[key], target)


def _target_fingerprint(plan_path, target):
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    nodes = list(_exercise_nodes(plan, target))
    if not nodes:
        raise ValueError("No writable exercise with this explicit id was found in the plan")
    return _digest({"exercise": asdict(target), "occurrences": nodes})


def export_definition_review(*, plan_path: Path, candidates_path: Path,
                             exercise_id: str, review_path: Path,
                             equipment_path: Path | None = None):
    from .bake_and_rank import write_json_atomic

    if review_path.exists():
        raise FileExistsError(f"Review already exists; edit it instead of overwriting: {review_path}")
    target = _target(plan_path, exercise_id, equipment_path)
    candidates = json.loads(candidates_path.read_text(encoding="utf-8-sig"))
    entries = [entry for entry in candidates.get("exercises", []) if entry.get("exerciseId") == exercise_id]
    if len(entries) != 1:
        raise ValueError("Expected one matching exercise in the discovery manifest")
    entry = entries[0]
    if entry.get("exerciseName") != target.name or entry.get("motionContext") != target.motion_context:
        raise ValueError("Discovery target differs from the current plan; use a current manifest")
    contract = entry.get("exerciseMotionContract") or {}
    action = contract.get("definingAction") or "; ".join(contract.get("requiredPhases") or [])
    review = {
        "schemaVersion": 1,
        "status": "pending",
        "exerciseId": exercise_id,
        "exerciseName": target.name,
        "targetFingerprint": _target_fingerprint(plan_path, target),
        "targetContext": asdict(target),
        "proposalContractSha256": _digest(contract),
        "proposalNotes": contract.get("advisoryText") or "",
        "sourceManifest": str(candidates_path.resolve()),
        "definition": {
            "definingAction": action,
            "completionMode": contract.get("completionMode") or "",
            "variantQualifiers": contract.get("variantQualifiers") or [],
        },
    }
    proposed_phases = contract.get("requiredPhases")
    if isinstance(proposed_phases, list) and proposed_phases:
        review["definition"]["requiredPhases"] = proposed_phases
    write_json_atomic(review_path, review)
    return review


def approve_definition_review(*, plan_path: Path, exercise_id: str,
                              review_path: Path, output_path: Path,
                              equipment_path: Path | None = None):
    from .bake_and_rank import write_json_atomic

    if output_path.resolve() == plan_path.resolve() or output_path.exists():
        raise FileExistsError("Choose a new output plan; the original plan is preserved")
    target = _target(plan_path, exercise_id, equipment_path)
    review = json.loads(review_path.read_text(encoding="utf-8-sig"))
    if (review.get("schemaVersion") != 1 or review.get("exerciseId") != exercise_id
            or review.get("exerciseName") != target.name
            or review.get("targetFingerprint") != _target_fingerprint(plan_path, target)):
        raise ValueError("Review does not match the current exercise configuration; export a fresh review")
    raw = review.get("definition")
    if not isinstance(raw, dict):
        raise ValueError("Review needs a definition object")
    if set(raw) - {"definingAction", "completionMode", "variantQualifiers", "requiredPhases"}:
        raise ValueError("Definition supports only definingAction, completionMode, variantQualifiers, and requiredPhases")
    action = raw.get("definingAction")
    qualifiers = raw.get("variantQualifiers", [])
    if not isinstance(action, str) or not action.strip() or len(action.strip()) > 512:
        raise ValueError("definingAction must contain 1 to 512 characters")
    if (not isinstance(qualifiers, list) or len(qualifiers) > 6
            or any(not isinstance(item, str) or not item.strip() or len(item.strip()) > 120 for item in qualifiers)):
        raise ValueError("variantQualifiers must contain at most six nonempty strings of at most 120 characters")
    phases = raw.get("requiredPhases")
    if phases is not None and (
        not isinstance(phases, list) or not 1 <= len(phases) <= 8
        or any(not isinstance(item, str) or not item.strip() or len(item.strip()) > 180 for item in phases)
    ):
        raise ValueError("requiredPhases must contain at most eight nonempty strings of at most 180 characters")
    normalized = exercise_motion_context_action_definition({"exerciseDefinition": raw})
    if normalized is None:
        raise ValueError("Definition needs a supported completionMode")
    definition = {key: normalized.get(key, []) for key in (
        "definingAction", "completionMode", "variantQualifiers",
    )}
    if phases is not None:
        definition["requiredPhases"] = normalized.get("requiredPhases", [])
    definition["review"] = {
        "status": "approved",
        "approvedAtUtc": datetime.now(timezone.utc).isoformat(),
        "reviewArtifactSha256": hashlib.sha256(review_path.read_bytes()).hexdigest(),
        "proposalContractSha256": review.get("proposalContractSha256"),
    }
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    nodes = list(_exercise_nodes(plan, target))
    if not nodes:
        raise ValueError("No writable exercise with this explicit id was found in the plan")
    for node in nodes:
        context = node.get("motionContext")
        node["motionContext"] = {**(context if isinstance(context, dict) else {}), "exerciseDefinition": definition}
    write_json_atomic(output_path, plan)
    return {"status": "approved", "exerciseId": exercise_id,
            "updatedOccurrences": len(nodes), "workoutPlanJson": str(output_path.resolve())}
