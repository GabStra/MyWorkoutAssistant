"""Apply exact, reviewed exercise definitions before motion discovery."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

from .definition_review import _exercise_nodes, _target_fingerprint
from .youtube import (
    ExerciseEntry,
    exercise_motion_context_action_definition,
    extract_workout_plan_exercises,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _has_trusted_explicit_definition(motion_context: dict[str, Any]) -> bool:
    definition = motion_context.get("exerciseDefinition")
    if not isinstance(definition, dict):
        return False
    review = definition.get("review")
    if exercise_motion_context_action_definition(motion_context) is None:
        return False
    source = str(definition.get("source") or "").strip().lower()
    if source not in {"", "approved", "library", "manual", "user"}:
        return False
    if isinstance(review, dict):
        return (
            review.get("status") == "approved"
            and bool(review.get("approvedAtUtc"))
            and bool(review.get("reviewArtifactSha256"))
            and bool(review.get("proposalContractSha256"))
        )
    return True


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _review_documents(registry_path: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Index sibling review artifacts by the exact bytes bound by an approval."""
    documents: dict[str, tuple[Path, dict[str, Any]]] = {}
    try:
        paths = registry_path.parent.glob("*.json")
        for path in paths:
            if path.resolve() == registry_path.resolve():
                continue
            try:
                raw = path.read_bytes()
                value = json.loads(raw.decode("utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                documents[_sha256(raw)] = (path, value)
    except OSError:
        return {}
    return documents


def _target_is_exactly_reviewed(
    *,
    source_plan_path: Path,
    source: ExerciseEntry,
    registry: ExerciseEntry,
    approved_definition: dict[str, Any],
    review_documents: dict[str, tuple[Path, dict[str, Any]]],
) -> tuple[bool, str, dict[str, Any] | None]:
    approval = approved_definition.get("review")
    if (not isinstance(approval, dict)
            or approval.get("status") != "approved"
            or not approval.get("approvedAtUtc")):
        return False, "registry_definition_not_approved", None
    review_hash = str(approval.get("reviewArtifactSha256") or "").lower()
    review_item = review_documents.get(review_hash)
    if not review_hash or review_item is None:
        return False, "approval_review_artifact_missing_or_hash_mismatch", None
    review_path, review = review_item
    if (review.get("schemaVersion") != 1
            or review.get("exerciseId") != source.exercise_id
            or review.get("exerciseName") != source.name
            or registry.exercise_id != source.exercise_id
            or registry.name != source.name):
        return False, "approved_definition_target_identity_mismatch", None
    try:
        source_fingerprint = _target_fingerprint(source_plan_path, source)
    except (OSError, ValueError, json.JSONDecodeError):
        return False, "source_target_fingerprint_unavailable", None
    if review.get("targetFingerprint") != source_fingerprint:
        return False, "approved_definition_target_fingerprint_mismatch", None
    if review.get("targetContext") != asdict(source):
        return False, "approved_definition_target_context_mismatch", None
    source_context = dict(source.motion_context)
    registry_context = dict(registry.motion_context)
    registry_context.pop("exerciseDefinition", None)
    if registry_context != source_context:
        return False, "approved_definition_base_context_mismatch", None
    reviewed_definition = review.get("definition")
    if not isinstance(reviewed_definition, dict):
        return False, "approved_definition_review_proposal_missing", None
    for key in ("definingAction", "completionMode", "variantQualifiers"):
        if reviewed_definition.get(key, [] if key == "variantQualifiers" else None) != approved_definition.get(
                key, [] if key == "variantQualifiers" else None):
            return False, "approved_definition_differs_from_reviewed_proposal", None
    if (review.get("proposalContractSha256")
            != approval.get("proposalContractSha256")):
        return False, "approval_proposal_fingerprint_mismatch", None
    if exercise_motion_context_action_definition({"exerciseDefinition": approved_definition}) is None:
        return False, "approved_definition_is_not_usable", None
    return True, "approved_definition_reused", {"path": str(review_path), "sha256": review_hash}


def _matching_pending_draft(
    *,
    source_plan_path: Path,
    source: ExerciseEntry,
    review_documents: dict[str, tuple[Path, dict[str, Any]]],
) -> dict[str, Any] | None:
    try:
        fingerprint = _target_fingerprint(source_plan_path, source)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    for path, review in review_documents.values():
        if (review.get("schemaVersion") != 1
                or review.get("status") != "pending"
                or review.get("exerciseId") != source.exercise_id
                or review.get("exerciseName") != source.name
                or review.get("targetFingerprint") != fingerprint
                or review.get("targetContext") != asdict(source)
                or not isinstance(review.get("definition"), dict)):
            continue
        return {
            "status": "pending_review",
            "path": str(path),
            "proposal": deepcopy(review["definition"]),
        }
    return None


def prepare_workout_plan_definition_readiness(
    *,
    plan_path: Path,
    approved_registry_path: Path | None = None,
    equipment_path: Path | None = None,
    include_disabled: bool = False,
    exercise_ids: set[str] | None = None,
) -> tuple[dict[str, Any], list[ExerciseEntry], dict[str, Any]]:
    """Return an in-memory enriched plan and exact per-target readiness report.

    Only definitions with an approved inline record, a matching sibling review
    artifact hash, and an exact current target fingerprint/context are applied.
    Pending proposal documents are exposed as review queue items only.
    """
    plan_path = Path(plan_path)
    plan = _load_json(plan_path)
    if not isinstance(plan, (dict, list)):
        raise ValueError("Workout plan must contain a JSON object or array")
    effective_plan = deepcopy(plan)
    equipment_payload = _load_json(Path(equipment_path)) if equipment_path else None
    source_entries = extract_workout_plan_exercises(
        plan,
        include_disabled=include_disabled,
        equipment_payload=equipment_payload,
    )
    registry_path = Path(approved_registry_path) if approved_registry_path else None
    registry_entries: dict[str, list[ExerciseEntry]] = {}
    review_documents = _review_documents(registry_path) if registry_path else {}
    if registry_path:
        registry_payload = _load_json(registry_path)
        registry_entries_list = extract_workout_plan_exercises(
            registry_payload,
            include_disabled=True,
            equipment_payload=equipment_payload,
        )
        for entry in registry_entries_list:
            registry_entries.setdefault(entry.exercise_id, []).append(entry)

    applied: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    readiness_by_id: dict[str, dict[str, Any]] = {}
    for source in source_entries:
        if exercise_ids and source.exercise_id not in exercise_ids:
            continue
        status = {
            "status": "ready" if _has_trusted_explicit_definition(source.motion_context) else "needs_definition_review",
            "reason": None,
            "definitionSource": "input_plan" if _has_trusted_explicit_definition(source.motion_context) else None,
        }
        candidates = registry_entries.get(source.exercise_id, [])
        matched = False
        mismatch_reason = None
        if status["status"] != "ready" and registry_path and len(candidates) == 1:
            approved = candidates[0].motion_context.get("exerciseDefinition")
            if isinstance(approved, dict):
                exact, reason, reviewed_from = _target_is_exactly_reviewed(
                    source_plan_path=plan_path,
                    source=source,
                    registry=candidates[0],
                    approved_definition=approved,
                    review_documents=review_documents,
                )
                if exact:
                    for node in _exercise_nodes(effective_plan, source):
                        context = node.get("motionContext")
                        node["motionContext"] = {
                            **(context if isinstance(context, dict) else {}),
                            "exerciseDefinition": deepcopy(approved),
                        }
                    status = {
                        "status": "ready",
                        "reason": None,
                        "definitionSource": "approved_registry",
                        "registryPath": str(registry_path),
                        "reviewArtifact": reviewed_from,
                    }
                    applied.append({
                        "exerciseId": source.exercise_id,
                        "exerciseName": source.name,
                        "definitionSource": "approved_registry",
                    })
                    matched = True
                else:
                    mismatch_reason = reason
            elif candidates:
                mismatch_reason = "registry_definition_missing"
        elif len(candidates) > 1:
            mismatch_reason = "registry_target_id_ambiguous"

        if status["status"] != "ready":
            status["reason"] = mismatch_reason or "missing_or_untrusted_explicit_action_definition"
            queue_item = {
                "exerciseId": source.exercise_id,
                "exerciseName": source.name,
                **status,
            }
            draft = _matching_pending_draft(
                source_plan_path=plan_path,
                source=source,
                review_documents=review_documents,
            )
            if draft is not None:
                queue_item["cachedDraft"] = draft
            unresolved.append(queue_item)
        readiness_by_id[source.exercise_id] = status

    if exercise_ids:
        observed_ids = {entry.exercise_id for entry in source_entries}
        for missing_id in sorted(exercise_ids - observed_ids):
            missing_status = {
                "status": "needs_definition_review",
                "reason": "selected_exercise_not_found_in_plan",
                "definitionSource": None,
            }
            readiness_by_id[missing_id] = missing_status
            unresolved.append({"exerciseId": missing_id, "exerciseName": None, **missing_status})

    effective_entries = extract_workout_plan_exercises(
        effective_plan,
        include_disabled=include_disabled,
        equipment_payload=equipment_payload,
    )
    for entry in effective_entries:
        if exercise_ids and entry.exercise_id not in exercise_ids:
            continue
        readiness = readiness_by_id.get(entry.exercise_id)
        if readiness is None:
            readiness = {
                "status": "ready" if _has_trusted_explicit_definition(entry.motion_context) else "needs_definition_review",
                "reason": None if _has_trusted_explicit_definition(entry.motion_context) else "missing_or_untrusted_explicit_action_definition",
                "definitionSource": "input_plan" if _has_trusted_explicit_definition(entry.motion_context) else None,
            }
            readiness_by_id[entry.exercise_id] = readiness
            if readiness["status"] != "ready":
                unresolved.append({
                    "exerciseId": entry.exercise_id,
                    "exerciseName": entry.name,
                    **readiness,
                })
    report = {
        "schemaVersion": 1,
        "sourcePlanPath": str(plan_path.resolve()),
        "sourcePlanSha256": _sha256(plan_path.read_bytes()),
        "approvedRegistryPath": str(registry_path.resolve()) if registry_path else None,
        "approvedRegistrySha256": _sha256(registry_path.read_bytes()) if registry_path else None,
        "selectedExerciseIds": sorted(exercise_ids) if exercise_ids else None,
        "exerciseCount": len(effective_entries),
        "readyCount": sum(item.get("status") == "ready" for item in readiness_by_id.values()),
        "unresolvedCount": len(unresolved),
        "approvedDefinitionsReused": applied,
        "unresolvedReviewQueue": unresolved,
        "readinessByExerciseId": readiness_by_id,
    }
    return effective_plan, effective_entries, report


def write_definition_readiness_report(path: Path, report: dict[str, Any]) -> None:
    """Atomically persist the concise, deterministic readiness report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_effective_workout_plan(path: Path, plan: dict[str, Any]) -> None:
    """Persist the plan after applying only exact, approved definitions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def require_definition_readiness(report: dict[str, Any]) -> None:
    """Stop selected work before discovery when any active target lacks authority."""
    unresolved = report.get("unresolvedReviewQueue")
    if not isinstance(unresolved, list) or not unresolved:
        return
    examples = ", ".join(
        str(item.get("exerciseName") or item.get("exerciseId") or "unknown")
        for item in unresolved[:5]
        if isinstance(item, dict)
    )
    remaining = max(0, len(unresolved) - 5)
    suffix = f" (+{remaining} more)" if remaining else ""
    raise ValueError(
        f"Exercise-definition preflight blocked discovery: {len(unresolved)} selected exercise(s) "
        f"need review: {examples}{suffix}. See definitionReadiness.unresolvedReviewQueue."
    )
