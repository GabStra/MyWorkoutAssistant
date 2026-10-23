"""Source-review evidence and bounded disagreement handling.

Generated target-action proposals may define conservative evidence obligations,
but they are not evidence of what the source physically shows. Missing or
uncertain action evidence remains unresolved until independently grounded.
Re-reviewing a rejection can establish agreement or uncertainty, never an
automatic approval over the original negative judgment.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Callable

# Version 2 removes contradictory dynamic-phase requirements for holds and
# ongoing actions. Reopen negative model judgments, preserving valid cuts.
SOURCE_REVIEW_AUTHORITY_VERSION = 2
SOURCE_REVIEW_REQUIRED = "source_cut_review_required"


def source_cut_pose_evidence_needs_review(
    metrics: dict[str, Any] | None,
    *,
    visual_integrity_passed: bool = True,
) -> bool:
    """Keep unresolved or contradictory pose evidence out of terminal rejection."""
    if not visual_integrity_passed or not isinstance(metrics, dict):
        return False
    required_regions = metrics.get("requiredRegionObservations")
    if (
        isinstance(required_regions, dict)
        and required_regions.get("required") is True
        and required_regions.get("available") is True
        and required_regions.get("passed") is False
    ):
        return False

    endpoints = metrics.get("sourcePoseEndpointContractValidation")
    if (
        isinstance(endpoints, dict)
        and endpoints.get("passed") is False
        and (endpoints.get("blockingMismatches") or endpoints.get("rawBlockingMismatches"))
    ):
        return False

    phase = metrics.get("candidateFullRepetitionPhaseCompletenessMetrics")
    phase_required = isinstance(phase, dict) and phase.get("required") is True
    phase_passed = isinstance(phase, dict) and phase.get("passed") is True
    if phase_required:
        reason = str(phase.get("reason") or "").casefold()
        signal = phase.get("phaseSignalEvidence")
        if "unavailable" in reason or "insufficient" in reason:
            return True
        if isinstance(signal, dict) and signal.get("resolved") is False:
            return True
        if not phase_passed:
            return False

    target_motion = metrics.get("targetMotionObservability")
    if isinstance(target_motion, dict) and target_motion.get("required") is True:
        if target_motion.get("available") is False or target_motion.get("passed") is None:
            return True
        if target_motion.get("passed") is False:
            if not (phase_required and phase_passed):
                return False
            return True
        if target_motion.get("passed") is not True:
            return True
    elif target_motion is None and phase_required and phase_passed:
        return True

    if not isinstance(endpoints, dict) or endpoints.get("available") is False:
        return True
    if endpoints.get("passed") is False:
        return not bool(endpoints.get("blockingMismatches") or endpoints.get("rawBlockingMismatches"))
    return endpoints.get("passed") is not True


def evidence_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def review_observation(payload: dict[str, Any] | None) -> dict[str, Any]:
    rows = payload.get("candidates", []) if isinstance(payload, dict) else []
    row = rows[0] if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) else {}
    tags = row.get("reject", [])
    valid_decision = all(type(row.get(key)) is bool for key in (
        "approved", "completeMovement", "startBoundaryClean", "finishBoundaryClean", "setupOrFiller"))
    return {
        "approved": row.get("approved") if valid_decision else None,
        "confidence": row.get("confidence"),
        "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
        "identityMatch": row.get("identityMatch"),
        "identityEvidence": evidence_text(row.get("identityEvidence")),
        "boundaryEvidence": evidence_text(row.get("boundaryEvidence")),
        "qualityEvidence": evidence_text(row.get("qualityEvidence")),
        "note": str(row.get("note") or ""),
    }


def agreed_rejection(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if first.get("approved") is not False or second.get("approved") is not False:
        return False
    for observation in (first, second):
        confidence = observation.get("confidence")
        if type(confidence) not in (int, float) or not 0.85 <= confidence <= 1.0:
            return False
    common = set(first["tags"]) & set(second["tags"])
    families = (
        ({"wrong_exercise", "wrong_variant"}, "identityEvidence"),
        ({"partial_movement", "bad_boundary", "setup_or_filler", "contact_changed"}, "boundaryEvidence"),
        ({"mechanics_inconsistent", "low_source_quality", "synthetic_subject"}, "qualityEvidence"),
    )
    return any(
        common & tags and first.get(field) and second.get(field)
        and (field != "identityEvidence" or
             first.get("identityMatch") == second.get("identityMatch") == "mismatch")
        for tags, field in families
    )


def assess_source_rejection(
    ranking: Any,
    observation: dict[str, Any],
    *,
    independent_review: Callable[[], tuple[dict[str, Any], str]],
) -> Any:
    """Exactly one independent request; a positive second answer is disagreement."""
    reviews = [observation]
    secondary_raw = None
    error = None
    try:
        second, secondary_raw = independent_review()
        reviews.append(second)
        confirmed = agreed_rejection(observation, second)
    except Exception as exc:
        confirmed = False
        error = f"{type(exc).__name__}: {exc}"
    assessment = {
        "policyVersion": SOURCE_REVIEW_AUTHORITY_VERSION,
        "status": "model_rejected" if confirmed else "needs_review",
        "basis": "two_model_observations" if confirmed else "unresolved_model_judgment",
        "reviewCount": 2,
        "reviews": reviews,
        "independentRawResponse": secondary_raw,
        "error": error,
    }
    return replace(
        ranking,
        reasons=list(dict.fromkeys([*ranking.reasons, *([] if confirmed else [SOURCE_REVIEW_REQUIRED])])),
        payload={**(ranking.payload or {}), "sourceReviewAssessment": assessment},
    )


def rejection_needs_authority_replay(payload: dict[str, Any]) -> bool:
    """Reopen legacy model-cut rejections; leave valid cuts and other failures intact."""
    ranking = payload.get("sourceCutRanking") or {}
    details = ranking.get("payload") or {}
    if details.get("sourceReviewAuthorityVersion") == SOURCE_REVIEW_AUTHORITY_VERSION:
        return False
    return (
        payload.get("selectedSpan") is None
        and "source_candidate_window_choice_failed" in ranking.get("reasons", [])
        and bool(details.get("sourceCutScorecardCandidates"))
    )


def candidate_needs_authority_replay(workspace: Path) -> bool:
    try:
        payload = json.loads((workspace / "segment_detection" / "segment_selection.json").read_text(encoding="utf-8"))
        return isinstance(payload, dict) and rejection_needs_authority_replay(payload)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def retained_source_attempt_keys(attempted_keys: list[str], candidate_workspaces: dict[str, Path]) -> list[str]:
    """Keep checkpoint exclusions except legacy model-cut judgments being replaced."""
    return [key for key in attempted_keys
            if key not in candidate_workspaces or not candidate_needs_authority_replay(candidate_workspaces[key])]


def source_authority_replay_plan(library_workspace: Path) -> list[dict[str, str]]:
    """Read-only inventory; the running generator and its selected files are untouched."""
    return [
        {"exercise": path.parents[3].name, "candidateWorkspace": str(path.parent.parent),
         "resumeStage": "source_review", "reason": "outdated_source_review_policy"}
        for path in sorted(library_workspace.glob("*/bake/*/segment_detection/segment_selection.json"))
        if candidate_needs_authority_replay(path.parent.parent)
        and not any((path.parents[3] / "selected").glob("*_wear_skeleton.json"))
    ]
