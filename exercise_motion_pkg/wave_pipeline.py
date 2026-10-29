from __future__ import annotations

from exercise_motion_pkg.reconstruction_compat import loads_reconstruction_metadata

import json
import hashlib
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from collections import deque
from contextlib import nullcontext
from contextvars import copy_context
from queue import Empty, Queue
from types import MethodType
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from exercise_motion_pkg.fit_runtime import abandon_speculative_workspace, prioritize_fit_workspaces

from exercise_motion_pkg.bake_and_rank import (
    BakeAndRankRequest,
    LazyLlamaCppVisionSession,
    RankedCandidate,
    RawMotionRejected,
    IncompleteReconstructionTrackingError,
    require_current_source_contract,
    SourceCandidateRejected,
    ExerciseMotionContractRejected,
    ExerciseDefinitionReviewRequired,
    SOURCE_SELECTION_POLICY_VERSION,
    candidate_decision_identity,
    bake_progress_activity,
    build_exercise_motion_contract_resolver,
    evaluate_source_candidate_gate,
    expand_ranked_candidates_for_source_windows,
    first_attempt_portfolio_size,
    first_attempt_readiness_assessment,
    generate_candidate_motion,
    limit_bake_fallback_candidates,
    load_ranked_candidates_manifest,
    prepare_candidate_input_video,
    prioritize_ranked_candidates_for_reconstruction,
    run_bake_and_rank_pipeline,
    apply_artifact_retention_policy,
    callable_accepts_keyword,
)
from exercise_motion_pkg.vlm_errors import critical_vlm_interaction_error
from exercise_motion_pkg.gvhmr_runner import GvhmrWarmWorkerInterruptedAmbiguous
from exercise_motion_pkg.shared_llama_server import (
    clear_generation_holder_marker,
    live_foreign_generation_holders,
    resolve_shared_llama_session_dir,
    write_generation_holder_marker,
)
from exercise_motion_pkg.source_outcomes import update_source_outcome_index
from exercise_motion_pkg.source_review_preflight import SourceReviewIncomplete, review_prepared_source
from exercise_motion_pkg.source_review_authority import retained_source_attempt_keys
from exercise_motion_pkg.process_lock import exclusive_workspace_lease
from exercise_motion_pkg.storage import is_storage_failure, require_storage_reserve
from exercise_motion_pkg.gpu_lock import exclusive_gpu_device
from exercise_motion_pkg.source_turn_budget import (
    _SourceTurnBudget,
    _source_turn_exercise_identity,
    load_source_turn_cursor,
    source_turn_budget_readiness,
)


STAGED_SOURCE_PORTFOLIO_MAX_SIZE = 3
STAGED_SOURCE_VALIDATION_MAX_WORKERS = 6
ARTIFACT_LIFECYCLE_TRANSITIONS = {
    "awaiting_final_validation": {
        "accepted", "manual_review", "processing_incomplete", "rejected", "retryable",
    },
    # A retry is a nonterminal result. The next validation attempt may resolve
    # to any terminal outcome, including a completed acceptance.
    "retryable": {
        "accepted", "manual_review", "processing_incomplete", "rejected", "retryable",
    },
    "processing_incomplete": {
        "accepted", "manual_review", "processing_incomplete", "rejected", "retryable",
    },
    "accepted": {"accepted"},
    "manual_review": {"manual_review"},
    "rejected": {"rejected"},
}


def _record_source_attempt_processing_failure(
    attempt: dict[str, Any],
    exc: Exception,
    *,
    event_prefix: str,
    attempts: list[dict[str, Any]],
    source_state: dict[str, Any],
) -> str:
    error = f"{type(exc).__name__}: {exc}"
    formatted_traceback = "".join(traceback.format_exception(exc)).rstrip()
    attempt.update({
        "status": "source_processing_failed",
        "error": error,
        "traceback": formatted_traceback,
    })
    source_state["attempts"] = [dict(source_attempt) for source_attempt in attempts]
    event = f"{event_prefix} | source_processing_failed: {error}"
    return f"{event}\n{formatted_traceback}" if formatted_traceback else event


def staged_source_portfolio_size(request: BakeAndRankRequest, readiness: dict[str, Any]) -> int:
    """How many validated sources to prepare in one staged wave.

    Discovery-defer paths keep fallback/final-rejection budgets at zero. When
    reconstruction attempts are also capped at one, prepare a single source.
    With recon budget >= 2, keep the orientation-diverse first-attempt portfolio
    so a raw/baked failure can advance in-wave.
    """
    recon_budget = int(getattr(request, "max_reconstruction_candidate_attempts", 0) or 0)
    first_pass_single_source = (
        int(getattr(request, "fallback_candidates", 0) or 0) <= 0
        and int(getattr(request, "max_final_output_rejections", 0) or 0) <= 0
        and recon_budget == 1
    )
    size = (
        1
        if first_pass_single_source
        else max(
            1,
            min(
                STAGED_SOURCE_PORTFOLIO_MAX_SIZE,
                first_attempt_portfolio_size(readiness),
            ),
        )
    )
    if recon_budget > 0:
        size = min(size, recon_budget)
    return size


@dataclass(frozen=True)
class StagedWaveItem:
    exercise_id: str
    exercise_name: str
    request: BakeAndRankRequest
    run_id: str | None = None
    source_review_turn_id: str | None = None


def generation_failure_status(error: Exception) -> str:
    if isinstance(error, IncompleteReconstructionTrackingError):
        return "rejected_incomplete_reconstruction_tracking"
    if isinstance(error, RawMotionRejected):
        return "rejected_raw_reconstruction_validation"
    if isinstance(error, GvhmrWarmWorkerInterruptedAmbiguous):
        return GvhmrWarmWorkerInterruptedAmbiguous.status
    return "failed"


def candidate_generation_failure_details(error: Exception) -> dict[str, Any] | None:
    if isinstance(error, GvhmrWarmWorkerInterruptedAmbiguous):
        return error.diagnostic_payload()
    return None


def initial_artifact_lifecycle() -> dict[str, Any]:
    timestamp = _utc_now()
    return {
        "schemaVersion": 1,
        "state": "awaiting_final_validation",
        "terminal": False,
        "history": [{"state": "awaiting_final_validation", "at": timestamp}],
    }


def transition_artifact_lifecycle(
    current: dict[str, Any], target: str, *, at: str | None = None,
) -> dict[str, Any]:
    """Record one allowed artifact outcome transition in the durable wave state."""
    previous = str(current.get("state") or "")
    if target not in ARTIFACT_LIFECYCLE_TRANSITIONS.get(previous, set()):
        raise ValueError(f"Invalid artifact lifecycle transition: {previous!r} -> {target!r}")
    history = list(current.get("history") or [])
    timestamp = at or _utc_now()
    history.append({"state": target, "at": timestamp})
    return {
        "schemaVersion": 1,
        "state": target,
        "terminal": target in {"accepted", "manual_review", "rejected"},
        "history": history,
    }


def _item_artifact_state(state: dict[str, Any]) -> str:
    lifecycle = state.get("artifactLifecycle")
    return str(lifecycle.get("state") or "") if isinstance(lifecycle, dict) else ""


def wave_manifest_is_exportable(manifest: dict[str, Any]) -> bool:
    """True when staged-wave completion should keep the baked artifact.

    Automatic selection and a safe manual-review fallback are both exportable.
    The latter is still labeled needs_manual_review by the workout-plan wrapper.
    """
    return artifact_disposition(manifest) in {"accepted", "manual_review"}


def artifact_disposition(manifest: dict[str, Any]) -> str:
    """Classify the terminal artifact outcome separately from pipeline completion."""
    if manifest.get("selected"):
        return "accepted"
    if (
        manifest.get("selectionStatus") == "needs_manual_review"
        and isinstance(manifest.get("manualReviewFallback"), dict)
    ):
        return "manual_review"
    diagnostics = final_processing_diagnostics(manifest).get("candidateDiagnostics", [])
    if any(item.get("status") == "needs_definition_review" for item in diagnostics):
        return "retryable"
    if any(item.get("status") == "needs_motion_processing" for item in diagnostics):
        return "processing_incomplete"
    if any(
        item.get("status") in {"failed", "needs_source_review", "needs_definition_review", "needs_manual_review"}
        for item in diagnostics
    ):
        return "retryable"
    return "rejected"


def final_validation_outcome_status(manifest: dict[str, Any]) -> str:
    """Separate unfinished fits from finished quality rejects for Progress/logs."""
    disposition = artifact_disposition(manifest)
    if disposition == "accepted":
        return "selected"
    if disposition == "manual_review":
        return "needs_manual_review"
    if disposition == "processing_incomplete":
        return "incomplete_processing"
    if any(
        item.get("status") == "needs_definition_review"
        for item in final_processing_diagnostics(manifest).get("candidateDiagnostics", [])
    ):
        return "needs_definition_review"
    return "no_selection"


def wave_retry_disposition(state: dict[str, Any]) -> str:
    if state.get("status") == "completed":
        return "export_manual_review" if _item_artifact_state(state) == "manual_review" else "export_selected"
    if state.get("source", {}).get("failureReason") == "exercise_contract_invalid":
        return "repair_contract"
    if state.get("source", {}).get("failureReason") == "needs_definition_review":
        return "needs_definition_review"
    if state.get("source", {}).get("failureReason") == "source_review_incomplete":
        return "retry_review"
    if state.get("source", {}).get("failureReason") == "source_turn_deferred":
        return "continue_source"
    final = state.get("finalValidation", {})
    diagnostics = final.get("candidateDiagnostics", [])
    if final.get("status") == "needs_definition_review" or any(
        item.get("status") == "needs_definition_review" for item in diagnostics
    ):
        return "needs_definition_review"
    if final.get("status") in {"no_selection", "incomplete_processing"}:
        reasons = {
            reason
            for item in diagnostics
            for reason in item.get("reasons", [])
        }
        # These two codes mean the motion output needs local evidence/processing
        # repair. Keep them in the approved-source lane only when the candidate
        # diagnostics preserve that explicit ownership; a same-named source or
        # review failure must retain its own route.
        evidence_gap_reasons = {
            "materialized_source_pose_fidelity_unavailable",
            "supported_material_sole_pitch_unavailable",
        }
        if any(
            any(
                owner == "motion_output" and reason in evidence_gap_reasons
                for reason, owners in (item.get("failureOwnersByReason") or {}).items()
                for owner in (owners if isinstance(owners, list) else [owners])
            )
            for item in diagnostics
        ):
            return "repair_evidence"
        if reasons.intersection({
            "source_support_contact_evidence_unavailable",
            "source_support_contact_evidence_incomplete",
            "source_support_observation_invalid",
        }):
            return "retry_review"
        if "source_support_contact_evidence_conflict" in reasons:
            # Disagreement between contact evidence producers is unresolved
            # evidence, not proof that the source itself is unsuitable.
            return "retry_review"
        if reasons.intersection({
            "source_confirmed_support_unrepaired",
            "source_confirmed_baseline_support_drift",
            "support_lock_baseline_safety_failed",
        }):
            return "retry_processing"
        if any(item.get("status") == "needs_motion_processing" for item in diagnostics):
            return "retry_processing"
        if any(
            item.get("status") == "failed"
            and item.get("failureOwner") == "source"
            for item in diagnostics
        ):
            return "next_source"
        if any(
            item.get("status") == "failed"
            and item.get("failureOwner") == "review"
            for item in diagnostics
        ):
            return "retry_review"
        if any(
            item.get("status") == "failed"
            and item.get("stage") == "browser_bake"
            and item.get("failureOwner") == "motion_output"
            and item.get("processingRetryPolicy") in {
                "terminal_deterministic", "retry_transient",
            }
            and any(
                owner == "motion_output" and reason == "candidate_failed"
                for reason, owners in (item.get("failureOwnersByReason") or {}).items()
                for owner in (owners if isinstance(owners, list) else [owners])
            )
            for item in diagnostics
        ):
            return "retry_processing"
        if any(item.get("status") == "failed" for item in diagnostics):
            return "retry_infrastructure"
        if any(
            item.get("status") in {"needs_source_review", "needs_manual_review"} for item in diagnostics
        ):
            return "retry_review"
        return "next_source"
    attempts = state.get("reconstruction", {}).get("attempts", [])
    if attempts and all(item.get("status") in {"rejected_tracking_preflight", "rejected_incomplete_reconstruction_tracking"}
                        for item in attempts):
        return "next_source"
    if attempts and all(item.get("status") == "rejected_raw_reconstruction_validation" for item in attempts):
        # The source passed approval; keep this in the local motion-processing lane.
        return "retry_processing"
    if state.get("source", {}).get("failureReason") in {
        "no_source_passed_exact_window_validation", "source_turn_deferred",
        "no_reconstruction_ready_source", "no_approved_discovery_candidates",
    }:
        return "next_source"
    return "retry_infrastructure"


def source_support_readiness_route(readiness: dict[str, Any]) -> tuple[str, list[str]]:
    """Route contact-evidence gaps to retained-source review.

    Even a same-time disagreement between contact observers is a conflict in
    evidence, not a verified contract violation. Source rejection remains owned
    by the independent source/contract gates. Older payloads are unresolved.
    """
    reasons_value = readiness.get("rejectionReasons") if isinstance(readiness, dict) else None
    reasons = [str(reason) for reason in reasons_value or [] if str(reason).strip()]
    status = str(readiness.get("status") or "").strip().casefold() if isinstance(readiness, dict) else ""
    if status == "ready" or (isinstance(readiness, dict) and readiness.get("passed") is True):
        return "ready", reasons
    if not reasons:
        reasons = ["source_support_contact_evidence_incomplete"]
    return "incomplete", reasons


def finalize_with_bounded_review_retry(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Retry missing review evidence once, using the same cached candidate work."""
    for attempt in range(2):
        manifest = operation()
        manifest["reviewAttemptCount"] = attempt + 1
        # The candidate reviewer owns its independent second opinion. Do not
        # multiply that budget at the outer pipeline layer (which can also
        # rebake the same motion). Missing evidence without a completed review
        # remains eligible for the existing single recovery attempt below.
        review_entries = [manifest.get("rejectedBest"), manifest.get("manualReviewFallback")]
        for entry in review_entries:
            if not isinstance(entry, dict):
                continue
            review = ((entry.get("ranking") or {}).get("payload") or {}).get("finalOutputValidation") or {}
            bounded = review.get("boundedReview") or {}
            if review.get("failureOwner") == "review" and bounded.get("additionalReviewCount", 0) >= 1:
                manifest["reviewRetrySkippedReason"] = "candidate_review_budget_exhausted"
                return manifest
        state = {"finalValidation": {
            "status": "selected" if manifest.get("selected") else "no_selection",
            **final_processing_diagnostics(manifest),
        }}
        if wave_retry_disposition(state) != "retry_review":
            break
    return manifest


def _candidate_fit_budget_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
    budget = result.get("candidateFitBudget")
    if isinstance(budget, dict):
        return budget
    controlled = result.get("controlledMotionFit")
    if isinstance(controlled, dict):
        budget = controlled.get("candidateFitBudget")
        if isinstance(budget, dict):
            return budget
    return None


def _controlled_motion_report_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
    controlled = result.get("controlledMotionFit")
    return controlled if isinstance(controlled, dict) else None


# Leftover below a real support-init / solve floor cannot finish another fit.
MIN_USEFUL_CANDIDATE_FIT_REMAINING_SECONDS = 30.0
# Final bake may run two processing attempts, each with fit + browser + review.


def exhausted_candidate_fit_session(manifest: dict[str, Any]) -> bool:
    """True when incomplete processing already spent the full candidate fit budget."""
    from .controlled_motion import controlled_fit_processing_incomplete

    for result in manifest.get("candidateResults") or []:
        if not isinstance(result, dict) or result.get("status") != "needs_motion_processing":
            continue
        budget = _candidate_fit_budget_from_result(result)
        if budget is None:
            continue
        remaining = budget.get("remainingSeconds")
        if not isinstance(remaining, (int, float)):
            continue
        budget_seconds = budget.get("seconds")
        useful_floor = MIN_USEFUL_CANDIDATE_FIT_REMAINING_SECONDS
        if isinstance(budget_seconds, (int, float)) and budget_seconds > 0:
            useful_floor = min(useful_floor, max(1.0, 0.1 * float(budget_seconds)))
        if remaining > useful_floor:
            continue
        controlled = _controlled_motion_report_from_result(result)
        if controlled is None:
            # Budget exhausted and disposition is needs_motion_processing.
            return True
        if controlled_fit_processing_incomplete(controlled):
            return True
    return False


def _processing_attempt_diagnostics(manifest: dict[str, Any], *, attempt_number: int) -> dict[str, Any]:
    """Keep the small set of fit and timing evidence needed to audit a retry."""
    from .stage_cache import PROCESSING_ATTEMPT_ID

    candidate_attempts = []
    for candidate_result in manifest.get("candidateResults") or []:
        if not isinstance(candidate_result, dict):
            continue
        controlled = _controlled_motion_report_from_result(candidate_result) or {}
        timings = candidate_result.get("timings")
        timings = {
            key: value
            for key, value in (timings.items() if isinstance(timings, dict) else [])
            if key.endswith("Seconds") and isinstance(value, (int, float))
        }
        cycle_attempts = []
        for cycle_attempt in controlled.get("cycleSelectionAttempts") or []:
            if not isinstance(cycle_attempt, dict):
                continue
            fit_report = cycle_attempt.get("fitReport")
            cycle_attempts.append({
                "selection": cycle_attempt.get("selection"),
                "reason": cycle_attempt.get("reason"),
                "elapsedSeconds": cycle_attempt.get("elapsedSeconds"),
                "failedChecks": cycle_attempt.get("failedChecks"),
                "termination": cycle_attempt.get("termination"),
                "optimizerTermination": cycle_attempt.get("optimizerTermination"),
                "fitCandidateBudget": (
                    fit_report.get("candidateFitBudget")
                    if isinstance(fit_report, dict)
                    else None
                ),
            })
        candidate_attempts.append({
            "candidateKey": candidate_result.get("candidateKey"),
            "candidateWorkspace": candidate_result.get("candidateWorkspace"),
            "videoId": (candidate_result.get("candidate") or {}).get("videoId")
            if isinstance(candidate_result.get("candidate"), dict)
            else candidate_result.get("videoId"),
            "status": candidate_result.get("status"),
            "timings": timings,
            "candidateFitBudget": (
                _candidate_fit_budget_from_result(candidate_result)
            ),
            "controlledMotionFit": {
                key: controlled.get(key)
                for key in (
                    "applied",
                    "reason",
                    "elapsedSeconds",
                    "availableBudgetSeconds",
                    "requiredBudgetSeconds",
                    "optimizerTermination",
                    "cycleRetryStopReason",
                )
                if key in controlled
            },
            "cycleSelectionAttempts": cycle_attempts,
            "rejectionReasons": [
                reason
                for failure in candidate_result.get("failures") or []
                if isinstance(failure, dict)
                for reason in (
                    failure.get("rejectionReasons")
                    or ([failure["reason"]] if failure.get("reason") else [])
                )
                if isinstance(reason, str)
            ],
        })

    disposition_state = {
        "finalValidation": {
            "status": "selected" if manifest.get("selected") else "no_selection",
            **final_processing_diagnostics(manifest),
        }
    }
    return {
        "attemptNumber": attempt_number,
        "processingAttemptId": PROCESSING_ATTEMPT_ID,
        "processingSeconds": (manifest.get("timings") or {}).get("totalSeconds"),
        "reviewAttemptCount": manifest.get("reviewAttemptCount"),
        "status": final_validation_outcome_status(manifest),
        "retryDisposition": wave_retry_disposition(disposition_state),
        "candidateResults": candidate_attempts,
    }


def finalize_with_bounded_processing_retry(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Refit incomplete controlled-motion once on retained source/RECONSTRUCTION inputs.

    Prefetch may hand final processing a one-shot incomplete bake. Invalidate that
    attempt and retry once so deferred library work is not required for a finished
    pass/fail verdict. Skip the second burn when the candidate session was already
    fully exhausted on timeout-style incompleteness. Deterministic browser-bake
    ValueErrors are terminal for this processing turn; library resume keeps the source.
    """
    from .stage_cache import advance_processing_attempt

    processing_attempts: list[dict[str, Any]] = []
    for attempt in range(2):
        if attempt > 0:
            advance_processing_attempt()
        manifest = finalize_with_bounded_review_retry(operation)
        manifest["processingAttemptCount"] = attempt + 1
        state = {
            "finalValidation": {
                "status": "selected" if manifest.get("selected") else "no_selection",
                **final_processing_diagnostics(manifest),
            }
        }
        retry_disposition = wave_retry_disposition(state)
        deterministic_browser_failure = any(
            isinstance(result, dict)
            and result.get("status") == "failed"
            and result.get("failureStage") == "browser_bake"
            and result.get("failureOwner") == "motion_output"
            and result.get("failureExceptionType") == "ValueError"
            and result.get("processingRetryPolicy") == "terminal_deterministic"
            for result in manifest.get("candidateResults") or []
        )
        if deterministic_browser_failure:
            manifest["processingRetrySkippedReason"] = (
                "deterministic_browser_bake_failure"
            )
            for result in manifest.get("candidateResults") or []:
                if (isinstance(result, dict)
                        and result.get("status") == "failed"
                        and result.get("failureStage") == "browser_bake"
                        and result.get("failureOwner") == "motion_output"
                        and result.get("failureExceptionType") == "ValueError"
                        and result.get("processingRetryPolicy") == "terminal_deterministic"):
                    result["status"] = "needs_motion_processing"
        processing_attempts.append(_processing_attempt_diagnostics(
            manifest,
            attempt_number=attempt + 1,
        ))
        if deterministic_browser_failure:
            break
        if retry_disposition != "retry_processing":
            break
        if exhausted_candidate_fit_session(manifest):
            manifest["processingRetrySkippedReason"] = "candidate_fit_session_exhausted"
            break
    manifest["processingAttempts"] = processing_attempts
    return manifest


def _rejection_codes_from_candidate_result(result: dict[str, Any]) -> list[str]:
    """Prefer concrete gate codes over coarse status labels for progress output."""
    codes: list[str] = []
    for failure in result.get("failures") or []:
        if not isinstance(failure, dict):
            continue
        reason = failure.get("reason")
        if isinstance(reason, str) and reason:
            codes.append(reason)
        for nested in failure.get("rejectionReasons") or []:
            if isinstance(nested, str) and nested:
                codes.append(nested)
    for clip in result.get("rejectedSourceClips") or []:
        if not isinstance(clip, dict):
            continue
        clip_reason = clip.get("reason")
        if isinstance(clip_reason, str) and clip_reason:
            codes.append(clip_reason)
        for nested in clip.get("rejectionReasons") or []:
            if isinstance(nested, str) and nested:
                codes.append(nested)
    controlled = result.get("controlledMotionFit")
    if isinstance(controlled, dict):
        fit_reason = controlled.get("reason")
        if isinstance(fit_reason, str) and fit_reason:
            codes.append(fit_reason)
    return list(dict.fromkeys(codes))


def _candidate_result_failure_owner(result: dict[str, Any]) -> str | None:
    """Preserve the owning stage from the current or retained candidate receipt."""
    explicit = result.get("failureOwner")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    failures = result.get("failures") or []
    if isinstance(failures, dict):
        failures = [failures]
    owners = {
        str(failure.get("failureOwner")).strip()
        for failure in failures
        if isinstance(failure, dict)
        and isinstance(failure.get("failureOwner"), str)
        and failure.get("failureOwner").strip()
    }
    # Conflicting nested owners are ambiguous and should not be promoted to a
    # local motion repair.
    return next(iter(owners)) if len(owners) == 1 else None


def _candidate_result_failure_owners_by_reason(result: dict[str, Any]) -> dict[str, list[str]]:
    """Bind each concrete reason to its explicit owner instead of cross-promoting."""
    owner_by_reason: dict[str, set[str]] = {}
    default_owner = _candidate_result_failure_owner(result)

    def add(reason: Any, owner: Any) -> None:
        if not isinstance(reason, str) or not reason:
            return
        resolved_owner = owner.strip() if isinstance(owner, str) else default_owner
        if resolved_owner:
            owner_by_reason.setdefault(reason, set()).add(resolved_owner)

    for reason in result.get("rejectionReasons") or []:
        add(reason, result.get("failureOwner"))
    failures = result.get("failures") or []
    if isinstance(failures, dict):
        failures = [failures]
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        owner = failure.get("failureOwner") or result.get("failureOwner")
        add(failure.get("reason"), owner)
        for reason in failure.get("rejectionReasons") or []:
            add(reason, owner)
    for clip in result.get("rejectedSourceClips") or []:
        if not isinstance(clip, dict):
            continue
        owner = clip.get("failureOwner") or result.get("failureOwner")
        add(clip.get("reason"), owner)
        for reason in clip.get("rejectionReasons") or []:
            add(reason, owner)
    controlled = result.get("controlledMotionFit")
    if isinstance(controlled, dict):
        add(controlled.get("reason"), controlled.get("failureOwner") or result.get("failureOwner"))
    return {reason: sorted(owners) for reason, owners in owner_by_reason.items()}


def final_processing_diagnostics(manifest: dict[str, Any]) -> dict[str, Any]:
    """Keep processing errors distinct from quality rejections in progress output."""
    candidates = []
    for result in manifest.get("candidateResults", []):
        status = result.get("status", "unknown")
        stage = result.get("failureStage") or {
            "rejected_raw_reconstruction_validation": "raw_reconstruction_validation",
            "rejected_incomplete_reconstruction_tracking": "raw_reconstruction_validation",
            "rejected_baked_motion_validation": "baked_motion_validation",
            "skipped_no_baked_clip": "baked_motion_validation",
            "skipped_no_usable_baked_motion": "baked_motion_validation",
            "needs_motion_processing": "controlled_motion_processing",
            "failed": "processing_error",
            "ready_for_selection": "output_validation",
        }.get(status, status)
        candidates.append({
            "stage": stage,
            "status": status,
            "failureOwner": _candidate_result_failure_owner(result),
            "exceptionType": result.get("failureExceptionType"),
            "processingRetryPolicy": result.get("processingRetryPolicy"),
            "reasons": _rejection_codes_from_candidate_result(result),
            "failureOwnersByReason": _candidate_result_failure_owners_by_reason(result),
            "timings": {key: value for key, value in result.get("timings", {}).items()
                        if key.endswith("Seconds") and isinstance(value, (int, float))},
        })
    attempts = manifest.get("timings", {}).get("candidateSelectionAttempts", [])
    reasons = list(dict.fromkeys(reason for attempt in attempts
                                for reason in attempt.get("rejectionReasons", [])))
    for candidate in candidates:
        if candidate["stage"] == "output_validation" and "final_output_model_rejected" in reasons:
            candidate["stage"] = "model_review"
    return {
        "selectionStatus": manifest.get("selectionStatus"),
        "candidateDiagnostics": candidates,
        "rejectionReasons": reasons,
        "reviewTimings": {key: value for key, value in manifest.get("timings", {}).items()
                          if key.endswith("Seconds") and isinstance(value, (int, float))},
    }



def run_timed_final_processing(*, queued_at: float, wait_for_prefetch: Callable[[], None],
                               operation: Callable[[], dict[str, Any]],
                               timings: dict[str, float]) -> dict[str, Any]:
    """Separate executor delay, unfinished prefetch, and processing (including retries).

    These intervals do not overlap. Candidate/model timings are nested within
    processing, so must not be added to these intervals to estimate elapsed time.
    Preserve measurements even when preparation or processing fails.
    """
    started = time.perf_counter()
    timings["executorQueueWaitSeconds"] = max(0.0, started - queued_at)
    try:
        wait_for_prefetch()
    finally:
        timings["renderPrefetchWaitSeconds"] = time.perf_counter() - started
    processing_started = time.perf_counter()
    try:
        return operation()
    finally:
        timings["pipelineProcessingSeconds"] = time.perf_counter() - processing_started


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    require_storage_reserve(path, reserve_bytes=64 * 1024**2)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            # Windows readers can briefly deny replacement of the checkpoint.
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _contact_timeline_repair_key(source_video_sha256: str, source_pose: Any,
                                 support_evidence: dict[str, Any]) -> str:
    """Stable identity for one bounded contact-timeline repair attempt."""
    from .body_support_observation import (
        CONTACT_TIMELINE_CROP_POLICY,
        CONTACT_TIMELINE_POLICY_VERSION,
    )

    evidence_identity = {
        key: value for key, value in support_evidence.items()
        if key != "bodySupportObservation"
    }
    body_observation = support_evidence.get("bodySupportObservation")
    if isinstance(body_observation, dict):
        evidence_identity["bodySupportObservation"] = {
            key: value for key, value in body_observation.items()
            if key not in {"contactTimeline", "contactTimelineRepairEvidenceKey",
                           "contactTimelineAttempt"}
        }
    payload = {
        "policyVersion": CONTACT_TIMELINE_POLICY_VERSION,
        "cropPolicy": CONTACT_TIMELINE_CROP_POLICY,
        "sourceVideoSha256": source_video_sha256,
        "sourcePose": source_pose,
        "sourceFootSupportEvidence": evidence_identity,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _persist_exact_source_support_evidence(candidate_workspace: Path, source_video_sha256: str,
                                           support_evidence: dict[str, Any]) -> bool:
    """Persist refreshed evidence only into artifacts bound to the exact cut."""
    segment_detection = candidate_workspace / "segment_detection"
    validation_path = segment_detection / "exact_source_phase_validation.json"
    try:
        validation = loads_reconstruction_metadata(validation_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    metrics = validation.get("metrics") if isinstance(validation, dict) else None
    if (not isinstance(metrics, dict)
            or str(metrics.get("sourceVideoSha256") or "").casefold() != source_video_sha256.casefold()
            or str(support_evidence.get("sourceVideoSha256") or "").casefold() != source_video_sha256.casefold()):
        return False

    selection_path = segment_detection / "segment_selection.json"
    try:
        selection = loads_reconstruction_metadata(selection_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        selection = None
    selected_metrics = (selection.get("exactSourcePhaseValidation")
                        if isinstance(selection, dict) else None)
    if (isinstance(selected_metrics, dict)
            and str(selected_metrics.get("sourceVideoSha256") or "").casefold()
            != source_video_sha256.casefold()):
        # The loader may prefer this newer receipt over exact validation. Never
        # persist to only one side and then let the downstream loader select a
        # different cut's metrics.
        return False

    metrics["sourceFootSupportEvidence"] = support_evidence
    if (isinstance(selected_metrics, dict)
            and str(selected_metrics.get("sourceVideoSha256") or "").casefold()
            == source_video_sha256.casefold()):
        selected_metrics["sourceFootSupportEvidence"] = support_evidence
        # This artifact can outrank exact validation in the loader, so update it
        # first. A later validation-write failure still leaves one reusable,
        # exact-hash-bound copy for downstream stages.
        _write_json_atomic(selection_path, selection)
    _write_json_atomic(validation_path, validation)
    return True


def _candidate_key(candidate: RankedCandidate) -> str:
    return f"{candidate.exercise_id}:{candidate.workspace_slug}"


def _reconstruction_timing_snapshot(result: Any) -> dict[str, Any] | None:
    """Keep compact reconstruction timings in the wave checkpoint.

    Candidate workspaces may be pruned after selection, so the harness cannot
    rely on a candidate manifest remaining on disk to measure this stage.
    """
    timings = getattr(result, "timings", None)
    if not isinstance(timings, dict):
        return None
    runner = timings.get("reconstruction")
    if not isinstance(runner, dict):
        return None
    snapshot: dict[str, Any] = {}
    stage_seconds = timings.get("reconstructionRunSeconds")
    if isinstance(stage_seconds, (int, float)):
        snapshot["reconstructionRunSeconds"] = stage_seconds
    runner_snapshot: dict[str, Any] = {}
    for key in ("backend", "elapsedSeconds"):
        value = runner.get(key)
        if isinstance(value, (str, int, float)):
            runner_snapshot[key] = value
    phase_timings = runner.get("phaseTimings")
    inference = phase_timings.get("inference") if isinstance(phase_timings, dict) else None
    prediction_seconds = (
        inference.get("predictionSeconds") if isinstance(inference, dict) else None
    )
    if isinstance(prediction_seconds, (int, float)):
        runner_snapshot["phaseTimings"] = {
            "inference": {"predictionSeconds": prediction_seconds}
        }
    if runner_snapshot:
        snapshot["reconstruction"] = runner_snapshot
    return snapshot or None


def source_attempt_log_context(candidate: RankedCandidate, number: int, total: int) -> str:
    """Identify the candidate window; the reviewer may choose a subinterval."""
    hint = candidate.source_chunk_hint
    window = (f"{hint.start_seconds:.2f}-{hint.end_seconds:.2f}s"
              if hint is not None else "automatic selection")
    return f"attempt {number}/{total} this turn | candidate window {window}"


def _set_source_turn_deadline(session: object, budget: _SourceTurnBudget | None) -> None:
    setter = getattr(session, "set_candidate_deadline", None)
    if callable(setter):
        if budget is None:
            setter(None)
        else:
            setter(
                budget.deadline,
                on_wait=budget.exclude_wait,
                wait_remaining=budget.remaining_wait_seconds,
            )


def generation_status(attempts: list[dict[str, Any]], expected_count: int) -> str:
    if len(attempts) < expected_count:
        return "pending"
    return "prepared" if any(attempt.get("status") == "prepared" for attempt in attempts) else "failed"


def _candidate_source_identity(candidate: RankedCandidate) -> str:
    if candidate.video_id:
        return f"video:{candidate.video_id}"
    if candidate.url:
        return f"url:{candidate.url}"
    return f"workspace:{candidate.workspace_slug}"


WAVE_PROGRESS_SCHEMA_VERSION = 1
WAVE_PROGRESS_TRANSIENT_ATTEMPT_LIMIT = 2


def _load_wave_progress(path: Path, *, exercise_id: str, turn_identity: str) -> dict[str, Any]:
    """Load per-exercise progress only for the same library review turn."""
    try:
        payload = loads_reconstruction_metadata(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != WAVE_PROGRESS_SCHEMA_VERSION
        or payload.get("exerciseId") != exercise_id
        or payload.get("turnIdentity") != turn_identity
    ):
        return {
            "schemaVersion": WAVE_PROGRESS_SCHEMA_VERSION,
            "exerciseId": exercise_id,
            "turnIdentity": turn_identity,
            "elapsedSeconds": 0.0,
            "work": {},
            "waves": {},
        }
    work = payload.get("work")
    waves = payload.get("waves")
    payload["work"] = work if isinstance(work, dict) else {}
    payload["waves"] = waves if isinstance(waves, dict) else {}
    try:
        payload["elapsedSeconds"] = max(0.0, float(payload.get("elapsedSeconds") or 0.0))
    except (TypeError, ValueError):
        payload["elapsedSeconds"] = 0.0
    return payload


def wave_progress_admission(
    progress: dict[str, Any],
    decision_identity: str,
    *,
    exercise_timeout_seconds: float,
    transient_attempt_limit: int = WAVE_PROGRESS_TRANSIENT_ATTEMPT_LIMIT,
) -> tuple[bool, str | None]:
    """Stop unchanged terminal work and enforce one cumulative exercise allowance."""
    try:
        elapsed = max(0.0, float(progress.get("elapsedSeconds") or 0.0))
    except (TypeError, ValueError):
        elapsed = 0.0
    if exercise_timeout_seconds > 0 and elapsed >= exercise_timeout_seconds:
        return False, "exercise_turn_budget_exhausted"
    entry = (progress.get("work") or {}).get(decision_identity)
    if not isinstance(entry, dict):
        return True, None
    if entry.get("terminal") is True:
        return False, "same_input_terminal_decision"
    try:
        attempts = max(0, int(entry.get("attempts") or 0))
    except (TypeError, ValueError):
        attempts = 0
    if attempts >= max(1, int(transient_attempt_limit)):
        return False, "same_input_transient_retry_budget_exhausted"
    return True, None


def _request_with_remaining_exercise_budget(
    item: StagedWaveItem,
    progress: dict[str, Any],
    *,
    configured_limit_seconds: float | None = None,
) -> StagedWaveItem:
    limit = float(
        configured_limit_seconds
        if configured_limit_seconds is not None
        else (getattr(item.request, "exercise_timeout_seconds", 0.0) or 0.0)
    )
    if limit <= 0.0:
        return item
    try:
        elapsed = max(0.0, float(progress.get("elapsedSeconds") or 0.0))
    except (TypeError, ValueError):
        elapsed = 0.0
    remaining = max(0.001, limit - elapsed)
    return replace(item, request=replace(item.request, exercise_timeout_seconds=remaining))


def _progress_outcome_is_terminal(status: str, retry_disposition: str) -> bool:
    if retry_disposition in {"retry_infrastructure", "retry_review", "continue_source"}:
        return False
    if retry_disposition in {
        "repair_evidence",
        "retry_processing",
        "next_source",
        "export_selected",
        "export_manual_review",
        "needs_definition_review",
        "repair_contract",
    }:
        return True
    if status in {"selected", "needs_manual_review", "no_selection"}:
        return True
    # A local motion/evidence repair already receives its bounded in-wave retry.
    # An unchanged second result needs changed evidence or processing identity.
    return retry_disposition in {"retry_processing", "repair_evidence", "next_source"}


def _record_wave_progress_work(
    progress: dict[str, Any],
    *,
    decision_identity: str,
    status: str,
    retry_disposition: str,
    selection_manifest_path: str | None = None,
) -> None:
    work = progress.setdefault("work", {})
    previous = work.get(decision_identity)
    attempts = int(previous.get("attempts") or 0) if isinstance(previous, dict) else 0
    work[decision_identity] = {
        "attempts": attempts + 1,
        "status": status,
        "retryDisposition": retry_disposition,
        "terminal": _progress_outcome_is_terminal(status, retry_disposition),
        "selectionManifestPath": selection_manifest_path,
    }


def _refresh_wave_progress_elapsed(progress: dict[str, Any]) -> float:
    try:
        source_seconds = max(0.0, float(progress.get("sourceSeconds") or 0.0))
    except (TypeError, ValueError):
        source_seconds = 0.0
    processing_seconds = 0.0
    for row in (progress.get("waves") or {}).values():
        if isinstance(row, dict):
            try:
                processing_seconds += max(0.0, float(row.get("processingSeconds") or 0.0))
            except (TypeError, ValueError):
                continue
    progress["elapsedSeconds"] = round(source_seconds + processing_seconds, 3)
    return progress["elapsedSeconds"]


def _interval_union_seconds(intervals: list[tuple[float, float]]) -> float:
    valid = sorted((start, end) for start, end in intervals if end > start)
    total = 0.0
    if not valid:
        return total
    start, end = valid[0]
    for next_start, next_end in valid[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def _interval_overlap_seconds(
    interval: tuple[float, float],
    other_intervals: list[tuple[float, float]],
) -> float:
    start, end = interval
    clipped = [
        (max(start, other_start), min(end, other_end))
        for other_start, other_end in other_intervals
        if min(end, other_end) > max(start, other_start)
    ]
    return _interval_union_seconds(clipped)


def _source_turn_wave_deltas(
    *,
    active_seconds: float,
    prior_active_seconds: float,
    excluded_wait_seconds: float,
    prior_excluded_wait_seconds: float,
) -> tuple[float, float]:
    """Return this wave's source activity/wait, excluding prior-turn totals."""
    return (
        max(0.0, float(active_seconds) - float(prior_active_seconds)),
        max(0.0, float(excluded_wait_seconds) - float(prior_excluded_wait_seconds)),
    )


def _cap_source_turn_budget_to_exercise(
    source_turn_budget: _SourceTurnBudget,
    *,
    started_at: float,
    configured_exercise_limit_seconds: float,
    exercise_elapsed_seconds: float,
) -> None:
    """Apply the global exercise deadline without shrinking the source budget twice."""
    if configured_exercise_limit_seconds <= 0.0:
        return
    exercise_deadline = started_at + max(
        0.0,
        configured_exercise_limit_seconds - max(0.0, exercise_elapsed_seconds),
    )
    if source_turn_budget.deadline is None:
        source_turn_budget.deadline = exercise_deadline
    else:
        source_turn_budget.deadline = min(source_turn_budget.deadline, exercise_deadline)


def _session_timing_manifest(session: object) -> dict[str, Any]:
    timing_manifest = getattr(session, "timing_manifest", None)
    if not callable(timing_manifest):
        return {}
    payload = timing_manifest()
    return dict(payload) if isinstance(payload, dict) else {}


def _wave_candidates(request: BakeAndRankRequest) -> list[RankedCandidate]:
    candidates = load_ranked_candidates_manifest(
        request.candidates_json,
        include_fallback_candidates=True,
        source_outcome_index=request.source_outcome_index,
    )
    candidates = limit_bake_fallback_candidates(candidates, request.fallback_candidates)
    candidates = prioritize_ranked_candidates_for_reconstruction(candidates)
    return expand_ranked_candidates_for_source_windows(candidates, request=request)


def _wave_candidates_for_item(item: StagedWaveItem) -> list[RankedCandidate]:
    candidates = _wave_candidates(item.request)
    normalized_name = item.exercise_name.strip().casefold()
    return [
        candidate
        for candidate in candidates
        if candidate.exercise_id == item.exercise_id
        or (
            bool(normalized_name)
            and candidate.exercise_name.strip().casefold() == normalized_name
        )
    ]


def _previous_selected_candidate_keys(
    workspace: Path,
    *,
    exercise_id: str,
) -> list[str]:
    """Recover the last prepared source order without trusting its validation."""
    for artifact_name in ("staged_wave_checkpoint.json", "staged_wave_report.json"):
        try:
            payload = loads_reconstruction_metadata((workspace / artifact_name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in payload.get("items") or []:
            if not isinstance(item, dict) or item.get("exerciseId") != exercise_id:
                continue
            source = item.get("source")
            if not isinstance(source, dict):
                continue
            keys = source.get("selectedCandidateKeys")
            if isinstance(keys, list):
                return [str(key) for key in keys if str(key)]
            key = source.get("selectedCandidateKey")
            if key:
                return [str(key)]
    return []


def _prioritize_previously_prepared_sources(
    candidates: list[RankedCandidate],
    *,
    preferred_keys: list[str],
) -> list[RankedCandidate]:
    if not preferred_keys:
        return candidates
    priority = {key: index for index, key in enumerate(preferred_keys)}
    return sorted(
        candidates,
        key=lambda candidate: priority.get(_candidate_key(candidate), len(priority)),
    )


def _checkpoint_payload(
    *,
    wave_id: str,
    stage: str,
    item_states: dict[str, dict[str, Any]],
    started_at: float,
    latest_exercise_name: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schemaVersion": 2,
        "waveId": wave_id,
        "stage": stage,
        "updatedAt": _utc_now(),
        "elapsedSeconds": round(time.perf_counter() - started_at, 3),
        "items": list(item_states.values()),
    }
    if metrics:
        payload["metrics"] = metrics
    if latest_exercise_name:
        payload["latestExerciseName"] = latest_exercise_name
    return payload


def effective_wave_final_output_rejection_limit(
    configured_limit: int,
    ready_source_count: int,
) -> int:
    """Preserve zero as unlimited while covering an explicitly bounded portfolio."""
    if configured_limit <= 0:
        return 0
    return max(configured_limit, ready_source_count)


def _wave_uses_separate_gpu_residency(items: list[StagedWaveItem]) -> bool:
    """Keep the supervised vision server warm only for the explicit split lane."""
    if not exclusive_gpu_device():
        return False
    return bool(items) and all(
        getattr(item.request, "shared_llama_server", False)
        for item in items
    )


def _stop_warm_reconstruction_worker_before_vlm(items: list[StagedWaveItem]) -> dict[str, Any]:
    if _wave_uses_separate_gpu_residency(items):
        return {
            "requested": False,
            "stopped": False,
            "skippedForSeparateGpuResidency": True,
        }
    session_dirs = set()
    shared_session_dir: Path | None = None
    for item in items:
        request = item.request
        # getattr: request fakes in tests (SimpleNamespace) may predate this field.
        if getattr(request, "use_warm_gvhmr_worker", False) and request.gvhmr_worker_session_dir is not None:
            session_dirs.add(request.gvhmr_worker_session_dir.expanduser().resolve())
        if getattr(request, "shared_llama_server", False):
            shared_session_dir = resolve_shared_llama_session_dir(
                getattr(request, "shared_llama_server_session_dir", None),
                base_url=request.llama_cpp_base_url,
            )
    if not session_dirs:
        return {"requested": False, "stopped": True}
    if shared_session_dir is not None:
        foreign_holders = live_foreign_generation_holders(shared_session_dir)
        if foreign_holders:
            # An overlapping wave is mid-generation with the warm worker; its
            # own release pass stops the worker when it finishes. Stopping it
            # here would stall that wave's jobs for a full worker restart, and
            # this wave's final VLM cannot start before the shared server
            # restarts anyway (the generating wave quiesced it).
            return {
                "requested": True,
                "stopped": False,
                "skippedForForeignGeneration": True,
                "foreignHolders": [str(h.get("holder")) for h in foreign_holders],
            }
    started = time.perf_counter()
    stopped_dirs: list[str] = []
    for session_dir in session_dirs:
        session_dir.mkdir(parents=True, exist_ok=True)
        if not (session_dir / "ready.json").exists() or (session_dir / "stopped.json").exists():
            # A cache-only wave never starts the lazy worker.
            continue
        (session_dir / "stop").write_text("stop\n", encoding="utf-8")
        deadline = time.monotonic() + 30.0
        stopped_path = session_dir / "stopped.json"
        while time.monotonic() < deadline:
            if stopped_path.exists():
                stopped_dirs.append(str(session_dir))
                break
            time.sleep(0.25)
        else:
            raise TimeoutError(
                f"Warm motion-extraction worker did not release the GPU within 30 seconds: {session_dir}"
            )
    return {
        "requested": True,
        "stopped": True,
        "sessionDirs": stopped_dirs,
        "elapsedSeconds": round(time.perf_counter() - started, 3),
    }


def _record_wave_source_rejections(
    items: list[StagedWaveItem],
    item_states: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for item in items:
        index_path = item.request.source_outcome_index
        if index_path is None:
            continue
        candidate_by_key = {
            _candidate_key(candidate): candidate
            for candidate in _wave_candidates_for_item(item)
        }
        state = item_states.get(item.exercise_id) or {}
        source = state.get("source") if isinstance(state.get("source"), dict) else {}
        rejected_results: list[dict[str, Any]] = []
        for attempt in source.get("attempts") or []:
            if not isinstance(attempt, dict) or attempt.get("status") in {
                "prepared", "blocked_contract", "needs_definition_review", "needs_source_review",
            }:
                continue
            candidate = candidate_by_key.get(str(attempt.get("candidateKey") or ""))
            candidate_payload = dict(candidate.candidate) if candidate is not None else {
                "videoId": attempt.get("videoId")
            }
            rejected_results.append(
                {
                    "candidate": candidate_payload,
                    "status": attempt.get("status"),
                    "sourceFailureReason": attempt.get("failureReason") or attempt.get("error"),
                    "sourceRejectionReasons": attempt.get("reasons") or [],
                    "reconstructionAttempted": False,
                }
            )
        if rejected_results:
            update = update_source_outcome_index(index_path, rejected_results)
            if update is not None:
                updates.append(update)
    return updates


def prepare_cpu_render_cache(item: StagedWaveItem, candidate: RankedCandidate, result: Any,
                             contract: dict[str, Any] | None) -> dict[str, Any]:
    """Warm the production browser-bake cache without using a CUDA model."""
    from exercise_motion_pkg import bake_and_rank as bake
    preview = getattr(result, "preview_html_path", None)
    cleaned = getattr(result, "cleaned_motion_json_path", None)
    if not isinstance(preview, Path) or not preview.is_file() or not isinstance(cleaned, Path) or not cleaned.is_file():
        return {"status": "skipped", "reason": "generated_preview_unavailable"}
    started = time.perf_counter()
    started_at = _utc_now()
    workspace = item.request.workspace / candidate.workspace_slug
    raw = getattr(result, "raw_motion_json_path", None)
    if isinstance(raw, Path) and raw.is_file():
        raw_gate = bake.evaluate_generated_motion_recovery_gate(
            raw_motion_path=raw, cleaned_motion_path=cleaned,
            source_pose_reference_path=workspace / "segment_detection/exact_source_pose_reference.json",
            exercise_motion_contract=contract, exercise_name=item.exercise_name)
        if not raw_gate.get("passed"):
            return {"status": "skipped", "reason": "generated_motion_recovery_gate_failed", "recoveryGate": raw_gate}
    authority = bake.pre_reconstruction_source_interval_authority(
        candidate_workspace=workspace, exercise_motion_contract=contract)
    loops = bake.build_candidate_review_eligible_loops(bake.load_motion_json(cleaned), source_interval_authority=authority)
    support = bake.pre_reconstruction_source_foot_support_evidence(
        workspace, exercise_motion_contract=contract,
    )
    from .body_support_observation import source_support_observation_needed, observe_body_support
    source_pose = bake.load_verified_source_pose_reference(
        workspace/'segment_detection/exact_source_pose_reference.json', workspace/'input/selected_segment.mp4')
    if source_support_observation_needed(source_pose, support):
        observation = observe_body_support(workspace/'input/selected_segment.mp4', None,
                                           workspace/'segment_detection/body_support')
        if observation.get('status') != 'observed':
            return {'status': 'skipped', 'reason': 'source_contact_observation_unavailable'}
    from .fit_runtime import SpeculativePrefetchAbandoned, speculative_fit_context, speculative_workspace
    try:
        with speculative_workspace(workspace), speculative_fit_context():
            artifacts = bake.bake_preview_loops_with_playwright(
                preview, loops, workspace, item.request.review_frames,
                rank_preview_variants=item.request.rank_preview_variants,
                adaptive_preview_settings=item.request.adaptive_preview_settings,
                max_adaptive_preview_settings=item.request.max_adaptive_preview_settings,
                caption_images=None, exercise_name=item.exercise_name, exercise_motion_contract=contract,
                source_foot_support_evidence=support, speculative_prefetch=True)
    except SpeculativePrefetchAbandoned:
        return {
            "status": "abandoned_for_finalization",
            "reason": "yielded_for_finalization",
            "startedAt": started_at,
            "finishedAt": _utc_now(),
            "elapsedSeconds": round(time.perf_counter() - started, 3),
        }
    return {"status": "prepared", "artifactCount": len(artifacts),
            "startedAt": started_at, "finishedAt": _utc_now(),
            "elapsedSeconds": round(time.perf_counter() - started, 3)}


def prepare_primary_cpu_render_cache(
    item: StagedWaveItem, candidate: RankedCandidate, result: Any, contract: dict[str, Any] | None,
) -> dict[str, Any]:
    with prioritize_fit_workspaces([item.request.workspace / candidate.workspace_slug]):
        return prepare_cpu_render_cache(item, candidate, result, contract)


@exclusive_workspace_lease(lambda _items, **kwargs: kwargs["workspace"])
def run_staged_bake_wave(
    items: list[StagedWaveItem],
    *,
    workspace: Path,
    wave_id: str,
    progress: Callable[[str], None] | None = None,
    render_executor: ThreadPoolExecutor | None = None,
    accelerator_phase: Callable | None = None,
) -> dict[str, Any]:
    wave_started = time.perf_counter()
    if accelerator_phase is None:
        from .staged_wave_service import WaveGpuGate
        accelerator_phase = WaveGpuGate().phase
    # Speculative post-RECONSTRUCTION bake/fit must not oversubscribe the shared CPU fit.
    from .resource_budget import render_prefetch_enabled as is_render_prefetch_enabled
    from .resource_budget import render_prefetch_worker_limit
    render_prefetch_enabled = is_render_prefetch_enabled()
    render_prefetch_worker_count = render_prefetch_worker_limit(len(items))
    active_render_prefetch_workers = render_prefetch_worker_count if render_prefetch_enabled else 0
    render_futures: dict[str, Any] = {}
    render_workspaces: dict[str, Path] = {}
    heartbeat_stop = threading.Event()
    try:
        if render_executor is not None:
            report = _run_staged_bake_wave(
                items,
                workspace=workspace,
                wave_id=wave_id,
                progress=progress,
                render_executor=render_executor,
                accelerator_phase=accelerator_phase,
                render_prefetch_workers=active_render_prefetch_workers,
                render_prefetch_enabled=render_prefetch_enabled,
                render_futures=render_futures,
                render_workspaces=render_workspaces,
                heartbeat_stop=heartbeat_stop,
            )
        else:
            with ThreadPoolExecutor(
                max_workers=render_prefetch_worker_count,
                thread_name_prefix="motion-render-prefetch",
            ) as owned_render_executor:
                report = _run_staged_bake_wave(
                    items,
                    workspace=workspace,
                    wave_id=wave_id,
                    progress=progress,
                    render_executor=owned_render_executor,
                    accelerator_phase=accelerator_phase,
                    render_prefetch_workers=active_render_prefetch_workers,
                    render_prefetch_enabled=render_prefetch_enabled,
                    render_futures=render_futures,
                    render_workspaces=render_workspaces,
                    heartbeat_stop=heartbeat_stop,
                )
    except BaseException:
        _drain_render_prefetch_futures(
            render_futures,
            render_workspaces,
            preserve_active_exception=True,
        )
        raise
    finally:
        heartbeat_stop.set()
    if render_futures:
        drain_started = time.perf_counter()
        drained_prefetch = _drain_render_prefetch_futures(
            render_futures,
            render_workspaces,
            preserve_active_exception=False,
        )
        drain_seconds = time.perf_counter() - drain_started
        _record_render_prefetch_drain(
            report,
            drained_prefetch,
            drain_seconds=drain_seconds,
            elapsed_seconds=time.perf_counter() - wave_started,
            workspace=workspace,
        )
    return report


def _drain_render_prefetch_futures(
    render_futures: dict[str, Any],
    render_workspaces: dict[str, Path],
    *,
    preserve_active_exception: bool,
) -> dict[str, dict[str, Any]]:
    """Stop and join this request's speculative work before its lease ends."""
    if not render_futures:
        return {}
    from concurrent.futures import CancelledError
    from .fit_runtime import (
        abandon_speculative_workspace,
        clear_speculative_workspace_state,
    )

    storage_failure: BaseException | None = None
    results: dict[str, dict[str, Any]] = {}
    for key, future in render_futures.items():
        candidate_workspace = render_workspaces.get(key)
        cancelled_before_start = not future.done() and future.cancel()
        if not future.done() and not cancelled_before_start and candidate_workspace is not None:
            abandon_speculative_workspace(candidate_workspace)
        try:
            result = future.result()
            results[key] = {
                "workerDrainStatus": "completed",
                "workerResult": result if isinstance(result, dict) else None,
            }
        except CancelledError:
            results[key] = {"workerDrainStatus": "cancelled_before_start"}
        except BaseException as exc:
            results[key] = {
                "workerDrainStatus": "failed",
                "workerError": f"{type(exc).__name__}: {exc}",
            }
            if not preserve_active_exception and is_storage_failure(exc):
                storage_failure = storage_failure or exc
        finally:
            clear_speculative_workspace_state(candidate_workspace)
    if storage_failure is not None:
        raise storage_failure
    return results


def _record_render_prefetch_drain(
    report: dict[str, Any],
    drained_prefetch: dict[str, dict[str, Any]],
    *,
    drain_seconds: float,
    elapsed_seconds: float,
    workspace: Path,
) -> None:
    """Persist what abandoned prefetch workers did while finalization ran."""
    metrics = report.setdefault("metrics", {})
    prefetch_metrics = metrics.get("cpuRenderPrefetch")
    if isinstance(prefetch_metrics, dict):
        for key, drained in drained_prefetch.items():
            entry = prefetch_metrics.get(key)
            if not isinstance(entry, dict) or entry.get("status") != "abandoned_for_finalization":
                continue
            entry["workerDrainStatus"] = drained.get("workerDrainStatus")
            worker_result = drained.get("workerResult")
            if isinstance(worker_result, dict):
                entry["workerResultStatus"] = worker_result.get("status")
                entry["workerElapsedSeconds"] = worker_result.get("elapsedSeconds")
                entry["workerStartedAt"] = worker_result.get("startedAt")
                entry["workerFinishedAt"] = worker_result.get("finishedAt")
            if drained.get("workerError"):
                entry["workerError"] = drained["workerError"]
    metrics["renderPrefetchDrainSeconds"] = round(drain_seconds, 3)

    report["elapsedSeconds"] = round(elapsed_seconds, 3)
    efficiency = report.get("generationEfficiency")
    if isinstance(efficiency, dict):
        elapsed_minutes = elapsed_seconds / 60.0
        accepted_count = int(efficiency.get("acceptedMovementCount") or 0)
        efficiency["acceptedPerElapsedMinute"] = (
            accepted_count / elapsed_minutes if elapsed_minutes > 0.0 else None
        )
        efficiency["timingBasis"] = "wave_wall_clock_including_queue_validation_and_prefetch_drain"

    checkpoint_path = workspace.expanduser().resolve() / "staged_wave_checkpoint.json"
    report_path = checkpoint_path.with_name("staged_wave_report.json")
    _write_json_atomic(report_path, report)
    _write_json_atomic(checkpoint_path, report)


def _run_staged_bake_wave(
    items: list[StagedWaveItem],
    *,
    workspace: Path,
    wave_id: str,
    progress: Callable[[str], None] | None = None,
    render_executor: ThreadPoolExecutor,
    render_futures: dict[str, Any],
    render_workspaces: dict[str, Path],
    heartbeat_stop: threading.Event,
    render_prefetch_workers: int | None = None,
    render_prefetch_enabled: bool = True,
    accelerator_phase: Callable | None = None,
) -> dict[str, Any]:
    """Run one cache-first VLM -> RECONSTRUCTION -> VLM wave.

    Up to two candidates from different source videos are prepared per
    exercise. Unsuccessful items are reported for the normal deeper retry lane
    instead of stalling the wave.
    Re-running the same wave is resumable because source cuts, RECONSTRUCTION output, and
    selection manifests are all content-addressed or workspace-cached.
    """

    if not items:
        raise ValueError("A staged wave must contain at least one exercise.")
    # A staged wave deliberately releases the pose/VLM runtime before RECONSTRUCTION and
    # may start a different runtime for final review.  Capture the exact source
    # pose while the source-validation runtime is authoritative; otherwise the
    # final materialized-output gate has no source reference and can only fail
    # as an infrastructure error.  Keep this invariant in the staged API rather
    # than relying on every caller to remember the CLI flag.
    items = [
        replace(
            item,
            request=replace(item.request, pre_reconstruction_source_validation=True),
        )
        for item in items
    ]
    workspace = workspace.expanduser().resolve()
    require_storage_reserve(workspace)
    checkpoint_path = workspace / "staged_wave_checkpoint.json"
    report_path = workspace / "staged_wave_report.json"
    previous_selected_candidate_keys = {
        item.exercise_id: _previous_selected_candidate_keys(
            workspace,
            exercise_id=item.exercise_id,
        )
        for item in items
    }
    started_at = time.perf_counter()
    metrics: dict[str, Any] = {
        "sourceValidationWorkers": 0,
        "renderPrefetchWorkers": max(
            0,
            int(1 if render_prefetch_workers is None else render_prefetch_workers),
        ),
        "renderPrefetchEnabled": render_prefetch_enabled,
        "sourceAttemptEvents": [],
        "acceleratorTransitions": [],
        "phaseTimings": {},
        "generationAndFinalValidationOverlap": True,
    }
    item_states: dict[str, dict[str, Any]] = {
        item.exercise_id: {
            "exerciseId": item.exercise_id,
            "exerciseName": item.exercise_name,
            "candidatesJson": str(item.request.candidates_json),
            "workspace": str(item.request.workspace),
            "status": "pending",
            "artifactLifecycle": initial_artifact_lifecycle(),
            "source": {"status": "pending", "attempts": []},
            "reconstruction": {"status": "pending"},
            "finalValidation": {"status": "pending"},
        }
        for item in items
    }
    wave_progress_by_exercise: dict[str, tuple[Path, dict[str, Any], str | None]] = {}
    configured_exercise_timeouts = {
        item.exercise_id: max(0.0, float(item.request.exercise_timeout_seconds or 0.0))
        for item in items
    }
    for item in items:
        turn_identity = str(item.source_review_turn_id or item.run_id or "").strip() or None
        progress_path = item.request.workspace / "wave_progress.json"
        progress_state = (
            _load_wave_progress(
                progress_path,
                exercise_id=item.exercise_id,
                turn_identity=turn_identity,
            )
            if turn_identity is not None
            else {}
        )
        wave_progress_by_exercise[item.exercise_id] = (
            progress_path, progress_state, turn_identity,
        )

    def announce(message: str) -> None:
        if progress is not None:
            progress(message)

    checkpoint_lock = threading.Lock()
    current_stage = "initializing"

    def checkpoint(stage: str, latest_exercise_name: str | None = None) -> None:
        nonlocal current_stage
        if stage in {"reconstruction_generation", "final_validation", "reconstruction_released"}:
            stage = "generation_and_validation"
        current_stage = stage
        with checkpoint_lock:
            for state in item_states.values():
                state["retryDisposition"] = wave_retry_disposition(state)
            _write_json_atomic(
                checkpoint_path,
                _checkpoint_payload(
                    wave_id=wave_id,
                    stage=stage,
                    item_states=item_states,
                    started_at=started_at,
                    latest_exercise_name=latest_exercise_name,
                    metrics=metrics,
                ),
            )

    def source_event(message: str) -> None:
        with checkpoint_lock:
            metrics["sourceAttemptEvents"].append(message)
        checkpoint("source_validation")
        announce(message)

    def checkpoint_heartbeat() -> None:
        while not heartbeat_stop.wait(30.0):
            try:
                checkpoint(current_stage)
            except Exception:
                # A heartbeat must never fail the owning generation wave.
                continue

    heartbeat_thread = threading.Thread(
        target=checkpoint_heartbeat,
        name=f"{wave_id}-checkpoint-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()

    prepared: dict[
        str,
        tuple[StagedWaveItem, list[tuple[RankedCandidate, Path]]],
    ] = {}
    ready_source_ids: set[str] = set()
    source_candidates_by_exercise = {
        item.exercise_id: _wave_candidates_for_item(item) for item in items
    }
    # One approved source is enough to start downstream work. Requiring a
    # second ready exercise lets queued source reviews start another decision
    # solely because of thread completion order.
    source_yield_threshold = 1
    prepared_contracts: dict[str, dict[str, Any] | None] = {}
    separate_gpu_residency = _wave_uses_separate_gpu_residency(items)
    stage_split_flags = {bool(getattr(item.request, "gvhmr_stage_split", False)) for item in items}
    if len(stage_split_flags) > 1:
        raise ValueError("A staged wave cannot mix split and combined GVHMR requests.")
    gvhmr_stage_split = stage_split_flags == {True}
    if gvhmr_stage_split and not separate_gpu_residency:
        raise ValueError(
            "GVHMR stage split requires a warm GVHMR worker, shared llama server, and verified separate GPU placement."
        )
    if gvhmr_stage_split and not all(
        getattr(item.request, "use_warm_gvhmr_worker", False) for item in items
    ):
        raise ValueError("GVHMR stage split requires the supervised warm-worker service.")
    metrics["gvhmrStageSplit"] = {
        "enabled": gvhmr_stage_split,
        "candidateQueueLimit": 2 if gvhmr_stage_split else 1,
        "preprocessGpuDevice": exclusive_gpu_device() if gvhmr_stage_split else None,
        "predictionGpuDevice": "0" if gvhmr_stage_split else None,
    }
    metrics["cpuRenderPrefetch"] = {}
    source_lane_kwargs = (
        {"gpu_lane": "llama"}
        if separate_gpu_residency
        and not gvhmr_stage_split
        and accelerator_phase is not None
        and callable_accepts_keyword(accelerator_phase, "gpu_lane")
        else {}
    )
    stream_source_handoffs = gvhmr_stage_split
    early_reconstruction_executor = (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="motion-early-reconstruction")
        if source_lane_kwargs and not stream_source_handoffs else None
    )
    early_reconstruction_results: dict[tuple[str, str], tuple[Any, float] | BaseException] = {}
    early_reconstruction_metrics: dict[str, dict[str, Any]] = {}
    source_intervals: dict[str, tuple[float, float, float, float]] = {}
    generation_intervals: dict[str, tuple[float, float]] = {}

    def early_metric_key(exercise_id: str, candidate_key: str) -> str:
        return json.dumps([exercise_id, candidate_key], separators=(",", ":"))

    def uncached_source_only(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("An early RECONSTRUCTION pass attempted an uncached source VLM request.")

    def early_reconstruction(candidate: RankedCandidate, item: StagedWaveItem, video_path: Path):
        started = time.perf_counter()
        candidate_identity = (item.exercise_id, _candidate_key(candidate))
        generation_intervals[_candidate_key(candidate)] = (started, started)
        metric_key = early_metric_key(*candidate_identity)
        early_reconstruction_metrics[metric_key] = {"status": "running", "startedAt": _utc_now()}
        stage_identity = {
            "schemaVersion": 1,
            "runId": str(item.run_id or str(wave_id).partition("-wave-")[0] or wave_id),
            "waveId": str(wave_id),
            "exerciseId": str(item.exercise_id),
            "candidateId": str(_candidate_key(candidate)),
        }

        def run_gpu(operation):
            with accelerator_phase(wave_id, "reconstruction", gpu_lane="reconstruction"):
                return source_session.run_without_llama_overlap(operation)

        kwargs: dict[str, Any] = {
            "request": item.request,
            "source_cut_caption_images": uncached_source_only,
            "prepared_video_path": video_path,
            "run_reconstruction_exclusive": run_gpu,
        }
        if callable_accepts_keyword(generate_candidate_motion, "stage_identity"):
            kwargs["stage_identity"] = stage_identity
        try:
            result = generate_candidate_motion(candidate, **kwargs)
        except BaseException as exc:
            elapsed = time.perf_counter() - started
            generation_intervals[_candidate_key(candidate)] = (started, time.perf_counter())
            early_reconstruction_results[candidate_identity] = exc
            early_reconstruction_metrics[metric_key] = {
                "status": "failed",
                "startedAt": early_reconstruction_metrics[metric_key]["startedAt"],
                "finishedAt": _utc_now(),
                "elapsedSeconds": round(elapsed, 3),
                "error": f"{type(exc).__name__}: {exc}",
            }
            return
        elapsed = time.perf_counter() - started
        generation_intervals[_candidate_key(candidate)] = (started, time.perf_counter())
        early_reconstruction_results[candidate_identity] = (result, elapsed)
        early_reconstruction_metrics[metric_key] = {
            "status": "prepared",
            "startedAt": early_reconstruction_metrics[metric_key]["startedAt"],
            "finishedAt": _utc_now(),
            "elapsedSeconds": round(elapsed, 3),
        }

    def submit_early_reconstruction(candidate: RankedCandidate, item: StagedWaveItem, video_path: Path) -> None:
        if early_reconstruction_executor is None:
            return
        metric_key = early_metric_key(item.exercise_id, _candidate_key(candidate))
        early_reconstruction_metrics[metric_key] = {"status": "queued", "queuedAt": _utc_now()}
        early_reconstruction_executor.submit(
            copy_context().run,
            early_reconstruction,
            candidate,
            item,
            video_path,
        )
    if gvhmr_stage_split or accelerator_phase is None:
        source_phase_gate = nullcontext()
    else:
        source_phase_gate = accelerator_phase(wave_id, "source_and_generation", **source_lane_kwargs)
    source_ready_queue = Queue(maxsize=len(items) + 1)
    source_phase_completed = False
    source_phase_started = 0.0
    source_session = None
    source_session_retained_for_empty_handoff = False
    source_sentinel_emitted = False

    def run_source_phase() -> None:
        nonlocal source_phase_completed, source_phase_started, source_session
        nonlocal source_session_retained_for_empty_handoff, source_sentinel_emitted
        with source_phase_gate:
            _stop_warm_reconstruction_worker_before_vlm(items)
            if getattr(items[0].request, "shared_llama_server", False) and not separate_gpu_residency:
                clear_generation_holder_marker(resolve_shared_llama_session_dir(
                    getattr(items[0].request, "shared_llama_server_session_dir", None),
                    base_url=items[0].request.llama_cpp_base_url,
                ))
            source_session = LazyLlamaCppVisionSession(items[0].request)
            source_phase_started = time.perf_counter()
            source_phase_completed = False
            source_session_retained_for_empty_handoff = False
            metrics["acceleratorTransitions"].append(
                {"stage": "source_vlm_and_exact_validation", "at": _utc_now()}
            )
            try:
                announce(f"Checking source videos for {len(items)} exercise(s).")
                checkpoint("source_validation")

                def prepare_item_source(
                    item: StagedWaveItem,
                ) -> tuple[
                    StagedWaveItem,
                    list[tuple[RankedCandidate, Path]],
                    list[dict[str, Any]],
                ]:
                    item_source_started_at = time.perf_counter()
                    with checkpoint_lock:
                        item_states[item.exercise_id]["sourceActivity"] = {
                            "startedAt": _utc_now(),
                            "operation": "checking source candidates",
                            "threadId": threading.get_ident(),
                        }
                    checkpoint("source_validation")
                    attempts: list[dict[str, Any]] = []
                    selected_sources: list[tuple[RankedCandidate, Path]] = []
                    selected_source_identities: set[str] = set()
                    progress_path, progress_state, progress_turn = wave_progress_by_exercise[item.exercise_id]
                    exercise_limit = configured_exercise_timeouts[item.exercise_id]
                    if progress_turn is not None:
                        allowed, stop_reason = wave_progress_admission(
                            progress_state,
                            "",
                            exercise_timeout_seconds=exercise_limit,
                        )
                        if not allowed:
                            item_states[item.exercise_id]["source"].update({
                                "status": "deferred",
                                "failureReason": stop_reason,
                                "noNewWork": True,
                                "progressElapsedSeconds": progress_state.get("elapsedSeconds", 0.0),
                            })
                            return item, [], attempts
                        item = _request_with_remaining_exercise_budget(
                            item,
                            progress_state,
                            configured_limit_seconds=exercise_limit,
                        )
                    requested_portfolio_size: int | None = None
                    resolver = build_exercise_motion_contract_resolver(
                        request=item.request,
                        caption_images=source_session.caption_images,
                        run_llama_exclusive=source_session.run_without_llama_overlap,
                    )
                    candidates = _prioritize_previously_prepared_sources(
                        list(source_candidates_by_exercise[item.exercise_id]),
                        preferred_keys=previous_selected_candidate_keys.get(item.exercise_id, []),
                    )
                    # When an exact cut is already materialized, use the same
                    # content-bound decision identity as bake terminal reuse to
                    # avoid repeating unchanged terminal work across waves.
                    if progress_turn is not None:
                        reusable_candidates = []
                        for candidate in candidates:
                            candidate_workspace = item.request.workspace / candidate.workspace_slug
                            prepared_video = candidate_workspace / "input" / "selected_segment.mp4"
                            identity = candidate_decision_identity(
                                candidate,
                                item.request,
                                prepared_video if prepared_video.is_file() else None,
                            )
                            allowed, _reason = (
                                wave_progress_admission(
                                    progress_state,
                                    identity,
                                    exercise_timeout_seconds=exercise_limit,
                                )
                                if identity
                                else (True, None)
                            )
                            if allowed:
                                reusable_candidates.append(candidate)
                        candidates = reusable_candidates
                    resume_path = item.request.workspace / "source_turn_resume.json"
                    budget_path = item.request.workspace / "source_turn_budget.json"
                    exercise_identity = _source_turn_exercise_identity(
                        item.exercise_id,
                        item.exercise_name,
                        item.request.authoritative_exercise_motion_context,
                    )
                    source_review_turn_id = str(item.source_review_turn_id or item.run_id or "").strip() or None
                    prior_attempt_keys: list[str] = []
                    prior_attempt_video_ids_from_resume: list[str] = []
                    resume: dict[str, Any] = {}
                    budget_ledger: dict[str, Any] = {}
                    try:
                        budget_ledger = loads_reconstruction_metadata(
                            budget_path.read_text(encoding="utf-8")
                        )
                    except (OSError, ValueError):
                        pass
                    resume = load_source_turn_cursor(
                        resume_path,
                        source_selection_policy_version=SOURCE_SELECTION_POLICY_VERSION,
                        exercise_id=item.exercise_id,
                        exercise_name=item.exercise_name,
                        authoritative_exercise_motion_context=(
                            item.request.authoritative_exercise_motion_context
                        ),
                        source_review_turn_id=source_review_turn_id,
                    ) or {}
                    prior_attempt_keys = [
                        str(key) for key in resume.get("attemptedCandidateKeys", [])
                    ]
                    prior_attempt_video_ids_from_resume = [
                        str(video_id) for video_id in resume.get("attemptedVideoIds", [])
                        if str(video_id).strip()
                    ]
                    prior_attempt_keys = retained_source_attempt_keys(prior_attempt_keys, {
                        _candidate_key(candidate): item.request.workspace / candidate.workspace_slug
                        for candidate in candidates
                    })
                    candidates = _prioritize_previously_prepared_sources(
                        [candidate for candidate in candidates if _candidate_key(candidate) not in prior_attempt_keys],
                        preferred_keys=[str(resume.get("nextCandidateKey") or "")],
                    )
                    retained_candidate_by_key = {
                        _candidate_key(candidate): candidate for candidate in candidates
                    }
                    prior_attempt_video_ids = list(dict.fromkeys([
                        *prior_attempt_video_ids_from_resume,
                        *(
                            candidate.video_id
                            for key in prior_attempt_keys
                            if (candidate := retained_candidate_by_key.get(key)) is not None
                            and candidate.video_id
                        ),
                    ]))
                    source_budget_request = replace(
                        item.request,
                        exercise_timeout_seconds=exercise_limit,
                    )
                    source_turn_budget = _SourceTurnBudget(
                        source_budget_request,
                        budget_ledger or resume,
                        started_at=item_source_started_at,
                        exercise_identity=exercise_identity,
                        turn_identity=source_review_turn_id,
                    )
                    try:
                        elapsed_before_exercise = max(
                            0.0,
                            float(progress_state.get("elapsedSeconds") or 0.0),
                        )
                    except (TypeError, ValueError):
                        elapsed_before_exercise = 0.0
                    _cap_source_turn_budget_to_exercise(
                        source_turn_budget,
                        started_at=item_source_started_at,
                        configured_exercise_limit_seconds=exercise_limit,
                        exercise_elapsed_seconds=elapsed_before_exercise,
                    )
                    source_turn_budget.attempts_used = max(
                        source_turn_budget.attempts_used,
                        len(prior_attempt_keys),
                    )
                    source_turn_incomplete = False
                    source_turn_stop_reason: str | None = None
                    resume_candidate_key: str | None = None
                    with checkpoint_lock:
                        item_states[item.exercise_id]["source"]["sourceSelectionPolicyVersion"] = SOURCE_SELECTION_POLICY_VERSION
                        item_states[item.exercise_id]["source"]["priorAttemptedCandidateKeys"] = list(prior_attempt_keys)
                        item_states[item.exercise_id]["source"]["priorAttemptedVideoIds"] = prior_attempt_video_ids
                    for candidate_number, candidate in enumerate(candidates, start=1):
                        resume_candidate_key = _candidate_key(candidate)
                        stop_reason = source_turn_budget.stop_reason()
                        if stop_reason is not None:
                            source_turn_incomplete = True
                            source_turn_stop_reason = stop_reason
                            source_event(
                                f"Source review: {item.exercise_name} | needs review: "
                                f"{stop_reason}; retaining source evidence for continuation."
                            )
                            break
                        source_identity = _candidate_source_identity(candidate)
                        if source_identity in selected_source_identities:
                            continue
                        with checkpoint_lock:
                            # A single approved source is enough to hand off to the
                            # GPU stage. Active workers finish their current attempt;
                            # queued source turns yield before spending another VLM
                            # decision, including when they have not started yet.
                            yield_source_turn = (
                                not selected_sources
                                and len(ready_source_ids) >= source_yield_threshold
                            )
                        if yield_source_turn:
                            _write_json_atomic(resume_path, {
                                "sourceSelectionPolicyVersion": SOURCE_SELECTION_POLICY_VERSION,
                                "sourceTurnExerciseIdentity": exercise_identity,
                                "sourceReviewTurnId": source_review_turn_id,
                                "nextCandidateKey": _candidate_key(candidate),
                                "attemptedCandidateKeys": list(dict.fromkeys([
                                    *prior_attempt_keys, *[attempt["candidateKey"] for attempt in attempts],
                                ])),
                                "attemptedVideoIds": list(dict.fromkeys([
                                    *prior_attempt_video_ids, *[attempt["videoId"] for attempt in attempts if attempt.get("videoId")],
                                ])),
                                **source_turn_budget.resume_fields(),
                            })
                            with checkpoint_lock:
                                item_states[item.exercise_id]["source"]["deferred"] = True
                            source_event(f"Source review: {item.exercise_name} | deferred remaining attempts; ready movements take priority.")
                            break
                        readiness = first_attempt_readiness_assessment(
                            candidate,
                            request=item.request,
                        )
                        attempt = {
                            "candidateKey": _candidate_key(candidate),
                            "videoId": candidate.video_id,
                            "workspaceSlug": candidate.workspace_slug,
                            "status": "pending",
                            "firstAttemptReadiness": readiness,
                        }
                        attempts.append(attempt)
                        source_turn_budget.begin_attempt()
                        if not bool(readiness.get("eligible")):
                            attempt["status"] = "rejected_first_attempt_readiness"
                            attempt["reasons"] = readiness.get("reasons", [])
                            continue
                        source_gate = evaluate_source_candidate_gate(candidate, request=item.request)
                        if not bool(source_gate.get("passed")):
                            attempt["status"] = "rejected_source_gate"
                            attempt["reasons"] = source_gate.get("reasons", [])
                            continue
                        with checkpoint_lock:
                            item_states[item.exercise_id]["sourceActivity"] = {
                                "startedAt": datetime.fromtimestamp(
                                    time.time() - max(
                                        0.0,
                                        time.perf_counter() - source_turn_budget.started_at,
                                    ),
                                    timezone.utc,
                                ).isoformat(),
                                "operation": "preparing and validating source video",
                                "videoId": candidate.video_id,
                                "candidateKey": _candidate_key(candidate),
                                "threadId": threading.get_ident(),
                                "operationDeadlineEpoch": (
                                    time.time() + max(
                                        0.0,
                                        source_turn_budget.deadline
                                        + source_turn_budget.remaining_wait_seconds()
                                        - time.perf_counter(),
                                    )
                                    if source_turn_budget.deadline is not None
                                    else None
                                ),
                            }
                        checkpoint("source_validation")
                        _set_source_turn_deadline(source_session, source_turn_budget)
                        try:
                            contract = resolver(candidate) if resolver is not None else None
                            if resolver is not None:
                                require_current_source_contract(contract, candidate)
                            selected_video = prepare_candidate_input_video(
                                candidate,
                                request=item.request,
                                source_cut_caption_images=source_session.caption_images,
                                exercise_motion_contract_resolver=resolver,
                            )
                            # Contact semantics must be available before the CPU-only
                            # semantic review and CPU-only prefetch. A candidate that
                            # cannot provide required independent support evidence
                            # should not spend an equivalent source-review decision.
                            from .body_support_observation import (
                                POLICY_VERSION as BODY_SUPPORT_POLICY_VERSION,
                                CONTACT_TIMELINE_POLICY_VERSION,
                                _contact_timeline_candidates,
                                source_support_observation_needed,
                                observe_body_support,
                                observe_foot_contact_timeline,
                                validated_body_support_contact_timeline,
                                validated_body_support_answer,
                            )
                            from .bake_and_rank import load_pre_reconstruction_exact_source_phase_metrics, load_verified_source_pose_reference
                            candidate_workspace = item.request.workspace / candidate.workspace_slug
                            phase_metrics = load_pre_reconstruction_exact_source_phase_metrics(candidate_workspace) or {}
                            source_pose = load_verified_source_pose_reference(
                                candidate_workspace/'segment_detection/exact_source_pose_reference.json', selected_video)
                            source_support_evidence = phase_metrics.get('sourceFootSupportEvidence')
                            if isinstance(source_support_evidence, dict):
                                source_support_evidence = dict(source_support_evidence)
                                support_evidence_refreshed = False
                                support_evidence_persisted = False
                                source_digest = hashlib.sha256(selected_video.read_bytes()).hexdigest()
                                pose_payload = (source_pose.get('pose')
                                    if isinstance(source_pose, dict) and isinstance(source_pose.get('pose'), dict)
                                    else source_pose)
                                source_pose_reference = ({
                                    'sourceVideoSha256': source_digest,
                                    'pose': pose_payload,
                                } if isinstance(pose_payload, dict) else None)
                                existing_observation = source_support_evidence.get('bodySupportObservation')
                                if (source_support_observation_needed(source_pose, source_support_evidence)
                                        or isinstance(existing_observation, dict)):
                                    if not (
                                        isinstance(existing_observation, dict)
                                        and existing_observation.get('sourceVideoSha256') == source_digest
                                        and existing_observation.get('policyVersion') == BODY_SUPPORT_POLICY_VERSION
                                        and validated_body_support_answer(existing_observation) is not None
                                    ):
                                        existing_observation = observe_body_support(
                                            selected_video, source_session.caption_images,
                                            candidate_workspace/'segment_detection/body_support')
                                        support_evidence_refreshed = True
                                    source_support_evidence['bodySupportObservation'] = existing_observation
                                from .support_geometry import pre_reconstruction_source_support_readiness
                                readiness = pre_reconstruction_source_support_readiness(source_support_evidence)
                                if not readiness.get('passed') and source_pose is not None:
                                    # The retained phase cache may have been classified
                                    # with an older foot-patch policy. Reclassify the
                                    # exact selected cut once with the active CPU model
                                    # before spending a GPU reconstruction attempt.
                                    from .foot_contact_observation import (
                                        POLICY_VERSION as FOOT_PATCH_POLICY_VERSION,
                                        add_observed_foot_contacts,
                                        observe_foot_landmarks,
                                    )
                                    patch = source_support_evidence.get('footPatchEvidence') or {}
                                    if patch.get('policyVersion') != FOOT_PATCH_POLICY_VERSION:
                                        landmarks = observe_foot_landmarks(
                                            selected_video,
                                        )
                                        source_support_evidence = add_observed_foot_contacts(
                                            source_support_evidence, landmarks, source_pose,
                                            source_video_path=selected_video)
                                        support_evidence_refreshed = True
                                        readiness = pre_reconstruction_source_support_readiness(
                                            source_support_evidence)
                                existing_timeline = (existing_observation.get('contactTimeline')
                                    if isinstance(existing_observation, dict) else None)
                                validated_timeline_rows = validated_body_support_contact_timeline(
                                    existing_timeline, expected_video_sha256=source_digest)
                                observed_timeline_samples = ({
                                    (row.get('sampleId'), row.get('side'))
                                    for row in (validated_timeline_rows or [])
                                })
                                unresolved_timeline_candidates = [
                                    row for row in _contact_timeline_candidates(
                                        source_pose, source_support_evidence)
                                    if (row.get('sampleId'), row.get('side'))
                                    not in observed_timeline_samples
                                ]
                                if unresolved_timeline_candidates and source_pose is not None:
                                    # A single exact-cut timeline can resolve patch
                                    # ambiguity even when coarse, clip-level support
                                    # readiness passes. The observer owns labels only;
                                    # source pose timestamps and stationary intervals
                                    # remain code-owned. Persist its receipt before any
                                    # later bake reloads the retained source metrics.
                                    evidence_key = _contact_timeline_repair_key(
                                        source_digest, source_pose_reference, source_support_evidence)
                                    repair_marker_path = (candidate_workspace / 'segment_detection'
                                        / 'source_foot_contact_timeline_repair.json')
                                    try:
                                        repair_marker = loads_reconstruction_metadata(
                                            repair_marker_path.read_text(encoding='utf-8'))
                                    except (OSError, ValueError):
                                        repair_marker = None
                                    previous_attempt = (repair_marker.get('evidenceKey') == evidence_key
                                        if isinstance(repair_marker, dict) else False)
                                    if not previous_attempt:
                                        timeline_status = 'observer_error'
                                        timeline_error = None
                                        try:
                                            timeline = observe_foot_contact_timeline(
                                                selected_video, source_pose_reference, source_support_evidence,
                                                source_session.caption_images,
                                                candidate_workspace/'segment_detection/body_support')
                                            if isinstance(timeline, dict):
                                                if not isinstance(existing_observation, dict):
                                                    existing_observation = {
                                                        'status': 'unknown',
                                                        'reason': 'coarse_support_observation_unavailable',
                                                        'sourceVideoSha256': source_digest,
                                                    }
                                                existing_observation = dict(existing_observation)
                                                existing_observation['contactTimeline'] = timeline
                                                source_support_evidence['bodySupportObservation'] = existing_observation
                                                support_evidence_refreshed = True
                                                timeline_status = str(timeline.get('status') or 'unknown')
                                                if _persist_exact_source_support_evidence(
                                                        candidate_workspace, source_digest,
                                                        source_support_evidence):
                                                    support_evidence_persisted = True
                                                    readiness = pre_reconstruction_source_support_readiness(
                                                        source_support_evidence)
                                                else:
                                                    timeline_status = 'persistence_unavailable'
                                        except Exception as exc:
                                            if is_storage_failure(exc):
                                                raise
                                            timeline_error = exc
                                        repair_marker = {
                                            'schemaVersion': 1,
                                            'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                                            'sourceVideoSha256': source_digest,
                                            'evidenceKey': evidence_key,
                                            'status': timeline_status,
                                            'attemptedAt': _utc_now(),
                                        }
                                        if timeline_error is not None:
                                            repair_marker['errorType'] = type(timeline_error).__name__
                                            repair_marker['error'] = str(timeline_error)[:1000]
                                        _write_json_atomic(repair_marker_path, repair_marker)
                                        if timeline_error is not None:
                                            # Let the source-stage owner classify VLM,
                                            # decoder, or tool failures. They are not
                                            # source-quality evidence.
                                            raise timeline_error
                                if (support_evidence_refreshed and readiness.get('passed')
                                        and not support_evidence_persisted):
                                    if not _persist_exact_source_support_evidence(
                                            candidate_workspace, source_digest,
                                            source_support_evidence):
                                        readiness = dict(readiness)
                                        readiness['status'] = 'incomplete'
                                        readiness['passed'] = False
                                        readiness['rejectionReasons'] = list(dict.fromkeys([
                                            *(readiness.get('rejectionReasons') or []),
                                            'source_support_evidence_persistence_unavailable',
                                        ]))
                                    else:
                                        support_evidence_persisted = True
                                if not readiness.get('passed'):
                                    _, rejection_reasons = source_support_readiness_route(readiness)
                                    attempt['status'] = 'needs_source_review'
                                    attempt['error'] = 'Source support evidence remains unresolved after one bounded exact-cut observation.'
                                    attempt['failureOwner'] = 'source_evidence'
                                    attempt['reasonTags'] = rejection_reasons
                                    attempt['sourceContactReadiness'] = readiness
                                    source_turn_incomplete = True
                                    source_turn_stop_reason = 'source_support_readiness_incomplete'
                                    source_event(
                                        f"Source attempt: {item.exercise_name} | video {candidate.video_id} | "
                                        "support evidence remains unresolved after the bounded exact-cut observation; "
                                        f"retaining source for review: {attempt['reasonTags']}"
                                    )
                                    break
                            review_prepared_source(candidate, request=item.request, selected_video=selected_video,
                                contract=contract, caption_images=source_session.caption_images)
                        except Exception as exc:
                            if is_storage_failure(exc):
                                raise
                            if isinstance(exc, SourceReviewIncomplete):
                                attempt["status"] = "needs_source_review"
                                attempt["error"] = str(exc)
                                source_turn_incomplete = True
                                source_turn_stop_reason = "source_review_incomplete"
                                source_event(f"Source review: {item.exercise_name} | needs review: {exc}")
                                break
                            if isinstance(exc, ExerciseDefinitionReviewRequired):
                                attempt["status"] = "needs_definition_review"
                                attempt["reason"] = str(exc)
                                attempt["failureOwner"] = "definition"
                                contract = getattr(exc, "contract", None)
                                if isinstance(contract, dict):
                                    attempt["actionDefinition"] = {
                                        key: contract.get(key)
                                        for key in (
                                            "actionDefinitionStatus",
                                            "actionDefinitionAuthority",
                                            "definingAction",
                                            "requiredPhases",
                                            "completionMode",
                                        )
                                        if contract.get(key) is not None
                                    }
                                source_event(
                                    f"Definition review: {item.exercise_name} | target action needs clarification: {exc}"
                                )
                                break
                            if isinstance(exc, ExerciseMotionContractRejected):
                                attempt["status"] = "blocked_contract"
                                attempt["error"] = str(exc)
                                source_event(f"Source review: {item.exercise_name} | blocked: {exc}")
                                break
                            vlm_error = critical_vlm_interaction_error(exc)
                            stop_reason = source_turn_budget.stop_reason()
                            if stop_reason in {"source_turn_deadline", "source_turn_wait_budget"}:
                                attempt["status"] = "needs_source_review"
                                attempt["error"] = f"{type(exc).__name__}: {exc}"
                                source_turn_incomplete = True
                                source_turn_stop_reason = stop_reason
                                source_event(
                                    f"Source review: {item.exercise_name} | needs review: "
                                    f"{stop_reason}; source retained."
                                )
                                break
                            if vlm_error is not None:
                                attempt["status"] = "needs_source_review"
                                attempt["error"] = f"{type(vlm_error).__name__}: {vlm_error}"
                                source_turn_incomplete = True
                                source_turn_stop_reason = "source_review_vlm_timeout"
                                source_event(
                                    f"Source review: {item.exercise_name} | needs review: "
                                    f"model request was inconclusive ({type(vlm_error).__name__}); source retained."
                                )
                                break
                            if isinstance(exc, SourceCandidateRejected):
                                attempt["status"] = (
                                    "needs_source_review" if {"source_cut_review_required", "source_cut_boundary_review_required"}.intersection(exc.reason_tags)
                                    else "rejected_source_validation"
                                )
                                attempt["reasonTags"] = list(exc.reason_tags)
                                attempt["error"] = f"{type(exc).__name__}: {exc}"
                            event_prefix = (
                                f"Source attempt: {item.exercise_name} | video {candidate.video_id} | "
                                f"{source_attempt_log_context(candidate, candidate_number, len(candidates))}"
                            )
                            if vlm_error is None and not isinstance(exc, SourceCandidateRejected):
                                with checkpoint_lock:
                                    event = _record_source_attempt_processing_failure(
                                        attempt,
                                        exc,
                                        event_prefix=event_prefix,
                                        attempts=attempts,
                                        source_state=item_states[item.exercise_id]["source"],
                                    )
                            else:
                                event = f"{event_prefix} | {attempt['status']}: {attempt['error']}"
                            source_event(event)
                            continue
                        finally:
                            _set_source_turn_deadline(source_session, None)
                            _write_json_atomic(budget_path, source_turn_budget.resume_fields())
                            with checkpoint_lock:
                                item_states[item.exercise_id].pop("sourceActivity", None)
                        if progress_turn is not None:
                            decision_identity = candidate_decision_identity(
                                candidate,
                                item.request,
                                selected_video,
                            )
                            if decision_identity is not None:
                                allowed, stop_reason = wave_progress_admission(
                                    progress_state,
                                    decision_identity,
                                    exercise_timeout_seconds=exercise_limit,
                                )
                                if not allowed:
                                    attempt.update({
                                        "status": "skipped_progress_guard",
                                        "decisionIdentity": decision_identity,
                                        "reason": stop_reason,
                                    })
                                    source_event(
                                        f"Source attempt: {item.exercise_name} | video {candidate.video_id} | "
                                        f"skipped unchanged work: {stop_reason}."
                                    )
                                    continue
                        attempt["status"] = "prepared"
                        prepared_contracts[_candidate_key(candidate)] = contract
                        attempt["selectedVideoPath"] = str(selected_video)
                        selected_sources.append((candidate, selected_video))
                        next_candidate = next(
                            (
                                remaining
                                for remaining in candidates[candidate_number:]
                                if _candidate_source_identity(remaining) not in selected_source_identities
                            ),
                            None,
                        )
                        with checkpoint_lock:
                            ready_source_ids.add(item.exercise_id)
                            item_states[item.exercise_id]["source"]["nextCandidateKey"] = (
                                _candidate_key(next_candidate) if next_candidate is not None else None
                            )
                        selected_source_identities.add(source_identity)
                        if requested_portfolio_size is None:
                            requested_portfolio_size = staged_source_portfolio_size(
                                item.request, readiness
                            )
                        # Keep the validated source as this handoff's candidate;
                        # do not wait for optional portfolio members before GPU work.
                        break
                    if (
                        not selected_sources
                        and not source_turn_incomplete
                    ):
                        source_turn_stop_reason = source_turn_budget.stop_reason()
                        if source_turn_stop_reason is not None:
                            source_turn_incomplete = True
                    if source_turn_incomplete:
                        attempted_keys = [
                            attempt["candidateKey"] for attempt in attempts
                            if attempt.get("status") != "needs_source_review"
                        ]
                        attempted_video_ids = [
                            attempt["videoId"] for attempt in attempts
                            if attempt.get("status") != "needs_source_review" and attempt.get("videoId")
                        ]
                        _write_json_atomic(resume_path, {
                            "sourceSelectionPolicyVersion": SOURCE_SELECTION_POLICY_VERSION,
                            "sourceTurnExerciseIdentity": exercise_identity,
                            "sourceReviewTurnId": source_review_turn_id,
                            "nextCandidateKey": resume_candidate_key,
                            "attemptedCandidateKeys": list(dict.fromkeys([*prior_attempt_keys, *attempted_keys])),
                            "attemptedVideoIds": list(dict.fromkeys([*prior_attempt_video_ids, *attempted_video_ids])),
                            **source_turn_budget.resume_fields(),
                        })
                        with checkpoint_lock:
                            source_state = item_states[item.exercise_id]["source"]
                            source_state["turn"] = source_turn_budget.report(stop_reason=source_turn_stop_reason)
                            source_state["status"] = "needs_source_review"
                            source_state["failureReason"] = "source_review_incomplete"
                    elif not selected_sources and not item_states[item.exercise_id]["source"].get("deferred"):
                        attempted_keys = [attempt["candidateKey"] for attempt in attempts]
                        attempted_video_ids = [
                            attempt["videoId"] for attempt in attempts if attempt.get("videoId")
                        ]
                        _write_json_atomic(resume_path, {
                            "sourceSelectionPolicyVersion": SOURCE_SELECTION_POLICY_VERSION,
                            "sourceTurnExerciseIdentity": exercise_identity,
                            "sourceReviewTurnId": source_review_turn_id,
                            "nextCandidateKey": None,
                            "attemptedCandidateKeys": list(dict.fromkeys([*prior_attempt_keys, *attempted_keys])),
                            "attemptedVideoIds": list(dict.fromkeys([*prior_attempt_video_ids, *attempted_video_ids])),
                            **source_turn_budget.resume_fields(),
                        })
                    elif selected_sources:
                        resume_path.unlink(missing_ok=True)
                    for attempt in attempts:
                        attempt.setdefault("requestedPortfolioSize", requested_portfolio_size)
                    if not selected_sources and not attempts and progress_turn is not None:
                        item_states[item.exercise_id]["source"].update({
                            "status": "deferred",
                            "failureReason": "same_input_progress_budget_exhausted",
                            "noNewWork": True,
                        })
                    with checkpoint_lock:
                        source_state = item_states[item.exercise_id]["source"]
                        source_state.setdefault(
                            "turn",
                            source_turn_budget.report(
                                stop_reason=(
                                    source_turn_stop_reason
                                    or ("source_turn_deferred" if source_state.get("deferred") else None)
                                )
                            ),
                        )
                        source_state["turn"]["budgetLedgerPath"] = str(budget_path)
                    _write_json_atomic(budget_path, source_turn_budget.resume_fields())
                    source_finished_at = time.perf_counter()
                    source_active_seconds = source_turn_budget.elapsed(source_finished_at)
                    source_wait_seconds = source_turn_budget.report(source_finished_at).get(
                        "excludedWaitSeconds", 0.0,
                    )
                    source_active_delta, source_wait_delta = _source_turn_wave_deltas(
                        active_seconds=source_active_seconds,
                        prior_active_seconds=source_turn_budget.elapsed_before,
                        excluded_wait_seconds=float(source_wait_seconds or 0.0),
                        prior_excluded_wait_seconds=source_turn_budget.excluded_wait_before,
                    )
                    source_intervals[item.exercise_id] = (
                        item_source_started_at,
                        source_finished_at,
                        source_active_delta,
                        source_wait_delta,
                    )
                    if progress_turn is not None:
                        progress_state["sourceSeconds"] = max(
                            float(progress_state.get("sourceSeconds") or 0.0),
                            source_active_seconds,
                        )
                        _refresh_wave_progress_elapsed(progress_state)
                        _write_json_atomic(progress_path, progress_state)
                    return item, selected_sources, attempts

                configured_parallelism = max(
                    1,
                    int(
                        items[0].request.llama_cpp_parallel
                        or items[0].request.review_llm_workers
                        or 1
                    ),
                )
                source_worker_count = min(
                    STAGED_SOURCE_VALIDATION_MAX_WORKERS,
                    configured_parallelism,
                    len(items),
                )
                metrics["sourceValidationWorkers"] = source_worker_count
                with ThreadPoolExecutor(max_workers=source_worker_count) as executor:
                    future_items = {
                        executor.submit(copy_context().run, prepare_item_source, item): item for item in items
                    }
                    for future in as_completed(future_items):
                        submitted_item = future_items[future]
                        with checkpoint_lock:
                            item_states[submitted_item.exercise_id].pop("sourceActivity", None)
                        try:
                            item, selected_sources, attempts = future.result()
                        except Exception as exc:
                            if is_storage_failure(exc):
                                raise
                            state = item_states[submitted_item.exercise_id]
                            state["source"] = {
                                "status": "failed",
                                "attempts": [],
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                            state["status"] = "retry_required"
                            source_message = state["source"]["error"]
                            if isinstance(exc, ValueError) and str(exc) == (
                                "No fully identity-reviewed recommended YouTube candidate found."
                            ):
                                state["source"]["failureReason"] = "no_approved_discovery_candidates"
                                state["source"]["noNewWork"] = True
                                source_message = "No approved candidates in cached discovery results."
                            source_event(
                                f"Source review: {submitted_item.exercise_name} | unresolved: {source_message}"
                            )
                            checkpoint("source_validation", submitted_item.exercise_name)
                            continue
                        state = item_states[item.exercise_id]
                        state["source"]["attempts"] = attempts
                        exercise_limit = configured_exercise_timeouts[item.exercise_id]
                        if (
                            selected_sources
                            and exercise_limit > 0.0
                            and float(wave_progress_by_exercise[item.exercise_id][1].get("elapsedSeconds") or 0.0)
                            >= exercise_limit
                        ):
                            state["source"].update({
                                "status": "deferred",
                                "failureReason": "exercise_turn_budget_exhausted",
                                "noNewWork": True,
                            })
                            selected_sources = []
                        if selected_sources:
                            state["source"]["status"] = "prepared"
                            state["source"]["selectedCandidateKeys"] = [
                                _candidate_key(candidate) for candidate, _path in selected_sources
                            ]
                            state["source"]["selectedCandidateKey"] = state["source"][
                                "selectedCandidateKeys"
                            ][0]
                            selected_attempts = [
                                attempt for attempt in attempts if attempt.get("status") == "prepared"
                            ]
                            state["source"]["requestedPortfolioSize"] = (
                                selected_attempts[0].get("requestedPortfolioSize")
                                if selected_attempts
                                else None
                            )
                            state["source"]["actualPortfolioSize"] = len(selected_sources)
                            prepared[item.exercise_id] = (item, selected_sources)
                        if stream_source_handoffs and selected_sources:
                            source_ready_queue.put((item.exercise_id, item, selected_sources))
                        if selected_sources and early_reconstruction_executor is not None:
                            candidate, video_path = selected_sources[0]
                            key = _candidate_key(candidate)
                            early_reconstruction_metrics[early_metric_key(item.exercise_id, key)] = {
                                "status": "queued",
                                "queuedAt": _utc_now(),
                            }
                            submit_early_reconstruction(candidate, item, video_path)
                        if not selected_sources:
                            if state["source"].get("status") != "needs_source_review":
                                state["source"]["status"] = "failed"
                            eligible_attempts = [
                                attempt
                                for attempt in attempts
                                if bool(
                                    (attempt.get("firstAttemptReadiness") or {}).get("eligible")
                                )
                            ]
                            state["source"].setdefault("failureReason", (
                                "needs_definition_review"
                                if any(attempt.get("status") == "needs_definition_review" for attempt in attempts)
                                else "exercise_contract_invalid"
                                if any(attempt.get("status") == "blocked_contract" for attempt in attempts)
                                else "source_review_incomplete"
                                if any(attempt.get("status") == "needs_source_review" for attempt in attempts)
                                else "source_processing_failed"
                                if any(attempt.get("status") in {"source_processing_failed", "rejected_vlm_timeout"} for attempt in attempts)
                                else "source_turn_deferred"
                                if state["source"].get("deferred")
                                else "no_reconstruction_ready_source"
                                if not eligible_attempts
                                else "no_source_passed_exact_window_validation"
                            ))
                            state["source"]["noNewWork"] = not attempts
                            state["status"] = "retry_required"
                        outcome = (
                            f"{len(selected_sources)} usable source(s)"
                            if selected_sources
                            else f"unresolved: {state['source']['failureReason']}"
                        )
                        source_event(f"Source review: {item.exercise_name} | {outcome}")
                        checkpoint("source_validation", item.exercise_name)
                for item in items:
                    if item.exercise_id not in prepared and item_states[item.exercise_id]["status"] == "pending":
                        state = item_states[item.exercise_id]
                        state["source"]["status"] = "failed"
                        state["status"] = "retry_required"
                source_phase_completed = True
            finally:
                if early_reconstruction_executor is not None:
                    early_reconstruction_executor.shutdown(wait=True)
                    metrics["earlyReconstructionOverlap"] = early_reconstruction_metrics
                # Only a nonempty reconstruction stage conflicts with this model's GPU
                # residency. Keep one owner through empty reconstruction/final phases;
                # exceptions and real reconstruction still release it here.
                source_session_retained_for_empty_handoff = (
                    source_phase_completed and not prepared
                )
                if not source_session_retained_for_empty_handoff or stream_source_handoffs:
                    source_session.close(force_stop_server=(
                        not separate_gpu_residency and not stream_source_handoffs
                    ))
                metrics["sourceVisionSession"] = _session_timing_manifest(source_session)
                metrics["phaseTimings"]["sourceValidationSeconds"] = round(
                    time.perf_counter() - source_phase_started,
                    3,
                )
                if stream_source_handoffs:
                    source_ready_queue.put(None)
                    source_sentinel_emitted = True

    if not stream_source_handoffs:
        run_source_phase()
    metrics["acceleratorTransitions"].append({"stage": "reconstruction", "at": _utc_now()})
    reconstruction_phase_started = time.perf_counter()
    announce(
        "Extracting motion as approved sources arrive."
        if stream_source_handoffs
        else f"Extracting motion for {len(prepared)} exercise(s)."
    )
    checkpoint("reconstruction_generation")
    # Residency markers prevent supervisor startup until a review releases the warm worker.
    shared_llama_session_dir = (
        resolve_shared_llama_session_dir(
            getattr(items[0].request, "shared_llama_server_session_dir", None),
            base_url=items[0].request.llama_cpp_base_url,
        )
        if getattr(items[0].request, "shared_llama_server", False)
        else None
    )
    generation_session = (
        LazyLlamaCppVisionSession(items[0].request)
        if stream_source_handoffs
        else source_session
        if source_session_retained_for_empty_handoff
        else LazyLlamaCppVisionSession(items[0].request)
    )

    def cached_source_only(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("A staged RECONSTRUCTION pass attempted an uncached source VLM request.")

    reconstruction_ready: dict[str, tuple[StagedWaveItem, list[tuple[RankedCandidate, Path]]]] = {}

    final_ready = Queue()
    warm_worker_handoff_lock = threading.Lock()
    generation_gpu_operation = generation_session.run_without_llama_overlap
    generation_gpu_operation_count = 0

    def run_reconstruction_gpu(operation):
        nonlocal generation_gpu_operation_count
        with accelerator_phase(wave_id, "reconstruction") if accelerator_phase else nullcontext():
            if shared_llama_session_dir is not None:
                if not separate_gpu_residency:
                    write_generation_holder_marker(shared_llama_session_dir, holder=wave_id)
            generation_gpu_operation_count += 1
            return generation_gpu_operation(operation)

    def configure_final_session(session):
        if accelerator_phase is None:
            return
        # Preserve bound-method ownership for candidate deadlines and exact GPU observations.
        for method_name, stage in (("caption_images", "final_review"),
                                   ("run_without_llama_overlap", "reconstruction")):
            original = getattr(session, method_name)

            def guarded(_session, *args, _original=original, _stage=stage, **kwargs):
                deadlines = getattr(_session, "_candidate_deadlines", None)
                deadline_kwargs = ({"deadline": deadlines.get()}
                                   if deadlines is not None and callable_accepts_keyword(accelerator_phase, "deadline")
                                   else {})
                with accelerator_phase(wave_id, _stage, **deadline_kwargs):
                    with warm_worker_handoff_lock:
                        _stop_warm_reconstruction_worker_before_vlm(items)
                        if shared_llama_session_dir is not None and not separate_gpu_residency:
                            clear_generation_holder_marker(shared_llama_session_dir)
                    return _original(*args, **kwargs)

            setattr(session, method_name, MethodType(guarded, session))

    generation_start_times: dict[str, float] = {}

    def generate_item_motion(
        exercise_id: str,
        item: StagedWaveItem,
        candidate: RankedCandidate,
        selected_video_path: Path,
    ) -> tuple[str, StagedWaveItem, Any, float]:
        item = _request_with_remaining_exercise_budget(
            item,
            wave_progress_by_exercise[exercise_id][1],
            configured_limit_seconds=configured_exercise_timeouts[exercise_id],
        )
        reconstruction_started = time.perf_counter()
        candidate_identity = _candidate_key(candidate)
        generation_start_times[_candidate_key(candidate)] = reconstruction_started
        early_result = early_reconstruction_results.get((exercise_id, _candidate_key(candidate)))
        if isinstance(early_result, BaseException):
            raise early_result
        if early_result is not None:
            result, generation_seconds = early_result
            if candidate_identity not in generation_intervals or generation_intervals[candidate_identity][1] <= generation_intervals[candidate_identity][0]:
                generation_intervals[candidate_identity] = (
                    reconstruction_started,
                    reconstruction_started + generation_seconds,
                )
            return exercise_id, item, result, generation_seconds
        generate_kwargs: dict[str, Any] = {
            "request": item.request,
            "source_cut_caption_images": cached_source_only,
            "prepared_video_path": selected_video_path,
        }
        stage_identity = {
            "schemaVersion": 1,
            "runId": str(item.run_id or str(wave_id).partition("-wave-")[0] or wave_id),
            "waveId": str(wave_id),
            "exerciseId": str(exercise_id),
            "candidateId": str(_candidate_key(candidate)),
        }
        if callable_accepts_keyword(generate_candidate_motion, "stage_identity"):
            generate_kwargs["stage_identity"] = stage_identity
        if (
            (generation_session is not None or accelerator_phase is not None)
            and callable_accepts_keyword(generate_candidate_motion, "run_reconstruction_exclusive")
        ):
            generate_kwargs["run_reconstruction_exclusive"] = run_reconstruction_gpu
        try:
            result = generate_candidate_motion(candidate, **generate_kwargs)
            return exercise_id, item, result, time.perf_counter() - reconstruction_started
        finally:
            generation_intervals[candidate_identity] = (
                reconstruction_started,
                time.perf_counter(),
            )

    prepared_candidates = [
        (exercise_id, item, candidate, selected_video_path)
        for exercise_id, (item, sources) in prepared.items()
        for candidate, selected_video_path in sources
    ]
    # GPU jobs remain serialized by the RECONSTRUCTION/global GPU locks. Extra callers
    # overlap video preparation and CPU postprocessing in different workspaces.
    from .resource_budget import staged_generation_cpu_workers
    reconstruction_worker_count = min(
        2 if gvhmr_stage_split else staged_generation_cpu_workers(),
        max(1, len(items) if stream_source_handoffs else len(prepared_candidates)),
    )
    metrics["generationCpuWorkers"] = reconstruction_worker_count
    reconstruction_completed_count = 0
    reconstruction_attempts: dict[str, list[dict[str, Any]]] = {
        item.exercise_id: [] for item in items
    }
    def run_generation_jobs() -> None:
        nonlocal reconstruction_completed_count
        with ThreadPoolExecutor(max_workers=reconstruction_worker_count) as executor:
            pending_candidates = deque(prepared_candidates)
            future_items = {}
            source_finished = not stream_source_handoffs
            total_candidate_count = len(prepared_candidates)

            def receive_source_ready(*, block: bool) -> None:
                nonlocal source_finished, total_candidate_count
                while not source_finished:
                    try:
                        ready = source_ready_queue.get(timeout=0.1 if block else 0)
                    except Empty:
                        if block:
                            continue
                        return
                    if ready is None:
                        source_finished = True
                        return
                    exercise_id, item, sources = ready
                    for candidate, selected_video_path in sources:
                        pending_candidates.append((
                            exercise_id, item, candidate, selected_video_path,
                        ))
                        prepared_candidates.append((
                            exercise_id, item, candidate, selected_video_path,
                        ))
                        total_candidate_count += 1
                    return

            def submit_ready_candidates() -> None:
                while len(future_items) < reconstruction_worker_count:
                    if not pending_candidates:
                        receive_source_ready(block=not future_items)
                    if not pending_candidates:
                        return
                    candidate_job = pending_candidates.popleft()
                    future_items[executor.submit(
                        copy_context().run, generate_item_motion, *candidate_job
                    )] = candidate_job

            submit_ready_candidates()
            while future_items or not source_finished:
                if not future_items:
                    receive_source_ready(block=True)
                    submit_ready_candidates()
                    if not future_items and source_finished:
                        break
                    continue
                completed, _pending = wait(
                    future_items,
                    timeout=0.1 if stream_source_handoffs and not source_finished else None,
                    return_when=FIRST_COMPLETED,
                )
                if not completed:
                    receive_source_ready(block=False)
                    submit_ready_candidates()
                    continue
                for future in completed:
                    if final_job.done():
                        for pending in future_items:
                            pending.cancel()
                        final_job.result()
                    exercise_id, item, candidate, selected_video_path = future_items[future]
                    state = item_states[exercise_id]
                    reconstruction_started = generation_start_times.get(_candidate_key(candidate), time.perf_counter())
                    try:
                        _result_exercise_id, _result_item, result, generation_seconds = future.result()
                        attempt = {
                            "status": "prepared",
                            "candidateKey": _candidate_key(candidate),
                            "selectedVideoPath": str(selected_video_path),
                            "elapsedSeconds": round(generation_seconds, 3),
                            "cacheStatus": result.reconstruction_cache_status,
                            "resultsPath": str(result.reconstruction_results_pkl) if result.reconstruction_results_pkl else None,
                        }
                        reconstruction_timings = _reconstruction_timing_snapshot(result)
                        if reconstruction_timings is not None:
                            attempt["reconstructionTimings"] = reconstruction_timings
                        reconstruction_attempts[exercise_id].append(attempt)
                        _ready_item, ready_sources = reconstruction_ready.setdefault(exercise_id, (item, []))
                        ready_sources.append((candidate, selected_video_path))
                        # Speculative CPU bake/fit only for the first ready source. Later
                        # sources bake during final processing if the primary fails, so
                        # unfinished secondary fits cannot stall the kept path.
                        if render_prefetch_enabled and len(ready_sources) == 1 and any(
                            not pending.done() for pending in future_items
                        ):
                            candidate_key = _candidate_key(candidate)
                            render_futures[candidate_key] = render_executor.submit(
                                copy_context().run, prepare_primary_cpu_render_cache, item, candidate, result,
                                prepared_contracts.get(_candidate_key(candidate)))
                            render_workspaces[candidate_key] = (
                                item.request.workspace / candidate.workspace_slug
                            )
                    except Exception as exc:
                        if is_storage_failure(exc):
                            raise
                        failure_status = generation_failure_status(exc)
                        attempt = {
                            "status": failure_status,
                            "candidateKey": _candidate_key(candidate),
                            "selectedVideoPath": str(selected_video_path),
                            "elapsedSeconds": round(time.perf_counter() - reconstruction_started, 3),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                        failure_details = candidate_generation_failure_details(exc)
                        if failure_details is not None:
                            attempt["reconstructionFailure"] = failure_details
                        if isinstance(exc, RawMotionRejected):
                            attempt["rawReconstructionMotionGate"] = exc.gate
                            candidate_workspace = item.request.workspace / candidate.workspace_slug
                            attempt["artifactRetention"] = apply_artifact_retention_policy(
                                candidate_workspace,
                                {"candidateResults": [{"candidateWorkspace": str(candidate_workspace),
                                                        "inputVideoPath": str(selected_video_path)}]},
                                mode=item.request.artifact_retention,
                            )
                        reconstruction_attempts[exercise_id].append(attempt)
                    reconstruction_completed_count += 1
                    state["reconstruction"] = {
                        "status": generation_status(reconstruction_attempts[exercise_id], len(prepared[exercise_id][1])),
                        "attempts": reconstruction_attempts[exercise_id],
                    }
                    if attempt["status"] != "prepared":
                        progress_path, progress_state, progress_turn = wave_progress_by_exercise[exercise_id]
                        if progress_turn is not None:
                            decision_identity = candidate_decision_identity(
                                candidate,
                                item.request,
                                selected_video_path,
                            )
                            if decision_identity is not None:
                                retry_disposition = wave_retry_disposition({
                                    "reconstruction": {"attempts": [attempt]},
                                })
                                _record_wave_progress_work(
                                    progress_state,
                                    decision_identity=decision_identity,
                                    status=attempt["status"],
                                    retry_disposition=retry_disposition,
                                )
                            generation_runs = [
                                generation_intervals[_candidate_key(candidate)]
                                for candidate in prepared[exercise_id][1]
                                if _candidate_key(candidate) in generation_intervals
                            ]
                            generation_seconds = _interval_union_seconds(generation_runs)
                            source_interval_row = source_intervals.get(exercise_id)
                            overlap_seconds = 0.0
                            if source_interval_row:
                                wall_overlap = _interval_overlap_seconds(
                                    (source_interval_row[0], source_interval_row[1]),
                                    generation_runs,
                                )
                                overlap_seconds = min(
                                    max(0.0, wall_overlap - source_interval_row[3]),
                                    source_interval_row[2],
                                )
                            progress_state.setdefault("waves", {})[str(wave_id)] = {
                                "generationSeconds": round(max(0.0, generation_seconds - overlap_seconds), 3),
                                "finalProcessingSeconds": 0.0,
                                "sourceGenerationOverlapSeconds": round(overlap_seconds, 3),
                                "processingSeconds": round(max(0.0, generation_seconds - overlap_seconds), 3),
                            }
                            _refresh_wave_progress_elapsed(progress_state)
                            _write_json_atomic(progress_path, progress_state)
                    if state["reconstruction"]["status"] != "pending" and exercise_id in reconstruction_ready:
                        ready_item, ready_sources = reconstruction_ready[exercise_id]
                        priority = {candidate.workspace_slug: index
                                    for index, (candidate, _path) in enumerate(prepared[exercise_id][1])}
                        ready_sources.sort(key=lambda source: priority[source[0].workspace_slug])
                        final_ready.put((exercise_id, ready_item, list(ready_sources)))
                    checkpoint("reconstruction_generation", item.exercise_name)
                    announce(
                        f"{'Extracted motion' if attempt['status'] == 'prepared' else 'Extraction failed'} for {item.exercise_name} "
                        f"({reconstruction_completed_count}/{total_candidate_count if source_finished else '…'}, "
                        f"{attempt['elapsedSeconds']:.1f}s)."
                    )
                for completed_future in completed:
                    future_items.pop(completed_future, None)
                submit_ready_candidates()


    def run_final_jobs():
        announce("Reviewing movements as their reconstruction finishes.")
        checkpoint("final_validation")
        metrics["acceleratorTransitions"].append({"stage": "final_vlm", "at": _utc_now()})
        final_phase_started = time.perf_counter()
        final_session = generation_session
        configure_final_session(final_session)
        # Do not oversubscribe the shared CPU fit: each final needs a real shot at
        # the candidate budget. Extra ready exercises wait in the executor queue.
        from .resource_budget import cpu_fit_slot_limit, final_validation_worker_limit
        final_worker_count = final_validation_worker_limit(
            len(items) if stream_source_handoffs else len(prepared)
        )
        metrics["finalValidationWorkers"] = final_worker_count
        metrics["finalValidationFitSlots"] = max(1, int(cpu_fit_slot_limit()))
        validation_start_times: dict[str, float] = {}
        validation_queued_times: dict[str, float] = {}
        validation_scheduling_times: dict[str, dict[str, float]] = {}

        def finalize_item(
            exercise_id: str,
            item: StagedWaveItem,
            ready_sources: list[tuple[RankedCandidate, Path]],
        ) -> dict[str, Any]:
            progress_state = wave_progress_by_exercise[exercise_id][1]
            generation_runs = [
                generation_intervals[_candidate_key(candidate)]
                for candidate, _video_path in ready_sources
                if _candidate_key(candidate) in generation_intervals
            ]
            source_interval_row = source_intervals.get(exercise_id)
            current_generation_seconds = _interval_union_seconds(generation_runs)
            if source_interval_row:
                wall_overlap = _interval_overlap_seconds(
                    (source_interval_row[0], source_interval_row[1]),
                    generation_runs,
                )
                current_generation_seconds = max(
                    0.0,
                    current_generation_seconds - min(
                        max(0.0, wall_overlap - source_interval_row[3]),
                        source_interval_row[2],
                    ),
                )
            remaining_budget_progress = {
                **progress_state,
                "elapsedSeconds": (
                    float(progress_state.get("elapsedSeconds") or 0.0)
                    + current_generation_seconds
                ),
            }
            item = _request_with_remaining_exercise_budget(
                item,
                remaining_budget_progress,
                configured_limit_seconds=configured_exercise_timeouts[exercise_id],
            )
            final_exercise_deadline = (
                time.perf_counter() + float(item.request.exercise_timeout_seconds)
                if float(item.request.exercise_timeout_seconds or 0.0) > 0.0
                else None
            )
            validation_start_times[exercise_id] = time.perf_counter()
            with checkpoint_lock:
                existing = item_states[exercise_id].get("finalValidationActivity")
            activity_started_at = (
                str(existing.get("startedAt"))
                if isinstance(existing, dict) and existing.get("startedAt")
                else _utc_now()
            )
            from .fit_runtime import abandon_speculative_workspace, prioritize_fit_workspaces
            # Prioritize every ready candidate for this exercise. Listing only the
            # first deadlocks later candidates: cpu_fit_slot blocks non-priority
            # non-speculative fits while this context stays open for the whole
            # finalize_item call (seen as "candidate 2/2 … starting" with no
            # further bake progress).
            primary_workspaces = [
                item.request.workspace / candidate.workspace_slug
                for candidate, _path in ready_sources
            ]

            def set_final_activity(operation: str, **extra: Any) -> None:
                payload = {
                    "startedAt": activity_started_at,
                    "updatedAt": _utc_now(),
                    "operation": operation,
                    **extra,
                }
                with checkpoint_lock:
                    item_states[exercise_id]["finalValidationActivity"] = payload

            def clear_final_activity() -> None:
                with checkpoint_lock:
                    item_states[exercise_id].pop("finalValidationActivity", None)

            def on_bake_progress(message: str) -> None:
                text = " ".join(str(message).split())
                if len(text) > 140:
                    text = text[:137] + "..."
                lower = text.lower()
                if "starting" in lower:
                    phase = "bake/fit"
                elif "needs_motion_processing" in lower:
                    phase = "fit incomplete→next"
                elif "status=" in lower:
                    phase = "next step"
                elif "model" in lower or "review" in lower:
                    phase = "review"
                else:
                    phase = "bake/fit/review"
                set_final_activity(phase, detail=text)

            set_final_activity(
                "start",
                candidateCount=len(ready_sources),
            )

            def collect_prefetch_result(candidate):
                key = _candidate_key(candidate)
                future = render_futures.get(key)
                if future is None:
                    return
                try:
                    metrics["cpuRenderPrefetch"][key] = future.result()
                except Exception as exc:
                    # A speculative render is never a quality decision. The
                    # owning candidate path will retry and classify a failure.
                    if is_storage_failure(exc):
                        raise
                    metrics["cpuRenderPrefetch"][key] = {
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    announce(
                        f"CPU render preparation failed for {item.exercise_name}; "
                        f"normal bake will retry: {exc}"
                    )

            def join_or_abandon_prefetch():
                """Reuse an active primary preparation before normal final validation."""
                set_final_activity("waiting for preparation")
                for candidate, _path in ready_sources:
                    key = _candidate_key(candidate)
                    future = render_futures.get(key)
                    if future is None:
                        continue
                    if future.done():
                        collect_prefetch_result(candidate)
                        continue
                    if future.cancel():
                        metrics["cpuRenderPrefetch"][key] = {"status": "cancelled_for_finalization", "cancelledBeforeStart": True}
                        continue
                    with prioritize_fit_workspaces([item.request.workspace / candidate.workspace_slug]):
                        try:
                            with accelerator_phase(wave_id, "cpu_preparation") as cancelled:
                                while not future.done():
                                    if callable(cancelled) and cancelled():
                                        raise KeyboardInterrupt("Motion run cancelled during CPU preparation")
                                    try:
                                        # The active fit owns its budget and must finish saving its cache.
                                        future.result(timeout=0.25)
                                    except TimeoutError:
                                        if future.done():
                                            raise
                                        continue
                                future.result()
                        except KeyboardInterrupt:
                            abandon_speculative_workspace(item.request.workspace / candidate.workspace_slug)
                            raise
                        except Exception:
                            collect_prefetch_result(candidate)
                            continue
                        else:
                            collect_prefetch_result(candidate)
                            continue
            def process():
                set_final_activity(
                    "bake/fit/review",
                    candidateCount=len(ready_sources),
                )
                with bake_progress_activity(on_bake_progress):
                    request = item.request
                    if final_exercise_deadline is not None:
                        request = replace(
                            request,
                            exercise_timeout_seconds=max(
                                0.001,
                                final_exercise_deadline - time.perf_counter(),
                            ),
                        )
                    return finalize_with_bounded_processing_retry(lambda: run_bake_and_rank_pipeline(
                        replace(
                            request,
                            require_reconstruction_cache=True,
                            reuse_previous_terminal_results=False,
                            fallback_candidates=0,
                            max_final_output_rejections=effective_wave_final_output_rejection_limit(
                                item.request.max_final_output_rejections,
                                len(ready_sources),
                            ),
                        ),
                        shared_vision_session=final_session,
                        prepared_candidates=[candidate for candidate, _path in ready_sources],
                        prepared_candidate_video_paths={
                            candidate.workspace_slug: selected_video_path
                            for candidate, selected_video_path in ready_sources
                        },
                    ))

            def process_with_priority():
                with prioritize_fit_workspaces(primary_workspaces):
                    return process()

            timings = validation_scheduling_times[exercise_id]
            try:
                return run_timed_final_processing(
                    queued_at=validation_queued_times[exercise_id],
                    wait_for_prefetch=join_or_abandon_prefetch,
                    operation=process_with_priority,
                    timings=timings,
                )
            finally:
                clear_final_activity()

        final_executor = ThreadPoolExecutor(max_workers=final_worker_count)
        try:
            final_futures = {}

            def submit_ready(exercise_id, item, ready_sources):
                validation_queued_times[exercise_id] = time.perf_counter()
                validation_scheduling_times[exercise_id] = {}
                with checkpoint_lock:
                    item_states[exercise_id]["finalValidationActivity"] = {
                        "startedAt": _utc_now(),
                        "updatedAt": _utc_now(),
                        "operation": "wait lane",
                        "candidateCount": len(ready_sources),
                    }
                future = final_executor.submit(copy_context().run, finalize_item, exercise_id, item, ready_sources)
                final_futures[future] = (exercise_id, item, ready_sources)

            def completed_futures():
                generation_finished = False
                while not generation_finished or final_futures:
                    try:
                        ready = final_ready.get(timeout=0.05 if not generation_finished else 0)
                    except Empty:
                        pass
                    else:
                        if ready is None:
                            generation_finished = True
                        else:
                            submit_ready(*ready)
                    if final_futures:
                        done, _pending = wait(final_futures, timeout=0.05, return_when=FIRST_COMPLETED)
                        for future in done:
                            yield future
                            del final_futures[future]

            for future in completed_futures():
                exercise_id, item, ready_sources = final_futures[future]
                state = item_states[exercise_id]
                validation_started = validation_start_times[exercise_id]
                try:
                    manifest = future.result()
                    disposition = artifact_disposition(manifest)
                    lifecycle = transition_artifact_lifecycle(
                        state["artifactLifecycle"], disposition,
                    )
                    manifest["artifactLifecycle"] = lifecycle
                    # Each wave may be resumed, and fallback rewrites the exercise's
                    # selection manifest. Keep the decision itself in a unique file.
                    decision_path = workspace / "final-decisions" / (
                        f"{item.exercise_id}-{time.time_ns()}.json"
                    )
                    decision_path.parent.mkdir(parents=True, exist_ok=True)
                    _write_json_atomic(decision_path, manifest)
                    selected = manifest.get("selected")
                    fallback = manifest.get("manualReviewFallback")
                    exportable = wave_manifest_is_exportable(manifest)
                    selected_candidate_payload = (
                        selected.get("candidate")
                        if isinstance(selected, dict)
                        and isinstance(selected.get("candidate"), dict)
                        else {}
                    )
                    selected_video_id = str(
                        selected_candidate_payload.get("videoId") or ""
                    )
                    selected_candidate = next(
                        (
                            candidate
                            for candidate, _path in ready_sources
                            if candidate.video_id == selected_video_id
                        ),
                        ready_sources[0][0],
                    )
                    exported_skeleton = None
                    if isinstance(selected, dict):
                        exported_skeleton = selected.get("selectedWearSkeletonPath")
                    elif isinstance(fallback, dict):
                        exported_skeleton = fallback.get("selectedWearSkeletonPath")
                    state["finalValidation"] = {
                        **final_processing_diagnostics(manifest),
                        "reviewAttemptCount": manifest.get("reviewAttemptCount", 1),
                        "status": final_validation_outcome_status(manifest),
                        "artifactDisposition": disposition,
                        "candidateKeys": [
                            _candidate_key(candidate) for candidate, _path in ready_sources
                        ],
                        "candidateKey": _candidate_key(selected_candidate),
                        "elapsedSeconds": round(time.perf_counter() - validation_started, 3),
                        "selectionManifestPath": str(decision_path),
                        "currentSelectionManifestPath": str(item.request.workspace / "selection_manifest.json"),
                        "selectedWearSkeletonPath": exported_skeleton,
                    }
                    state["artifactLifecycle"] = lifecycle
                    state["status"] = "completed" if exportable else "retry_required"
                except Exception as exc:
                    if is_storage_failure(exc):
                        raise
                    state["artifactLifecycle"] = transition_artifact_lifecycle(
                        state["artifactLifecycle"], "retryable",
                    )
                    state["finalValidation"] = {
                        "status": "failed",
                        "elapsedSeconds": round(time.perf_counter() - validation_started, 3),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    state["status"] = "retry_required"
                final_state = state["finalValidation"]
                final_state["schedulingTimings"] = {
                    key: round(value, 3)
                    for key, value in validation_scheduling_times[exercise_id].items()
                }
                # Completion handling and manifest writes are outside the worker.
                # Report its actual queue + wait + processing intervals, not the
                # time at which the coordinator happened to collect the result.
                final_state["elapsedSeconds"] = round(sum(
                    validation_scheduling_times[exercise_id].values()
                ), 3)
                progress_path, progress_state, progress_turn = wave_progress_by_exercise[exercise_id]
                if progress_turn is not None:
                    generation_runs = [
                        generation_intervals[_candidate_key(candidate)]
                        for candidate, _video_path in ready_sources
                        if _candidate_key(candidate) in generation_intervals
                    ]
                    generation_seconds = _interval_union_seconds(generation_runs)
                    source_interval_row = source_intervals.get(exercise_id)
                    source_active_seconds = source_interval_row[2] if source_interval_row else 0.0
                    source_overlap_seconds = (
                        _interval_overlap_seconds(
                            (source_interval_row[0], source_interval_row[1]),
                            generation_runs,
                        )
                        if source_interval_row
                        else 0.0
                    )
                    source_active_overlap_seconds = (
                        min(
                            max(0.0, source_overlap_seconds - source_interval_row[3]),
                            source_interval_row[2],
                        )
                        if source_interval_row
                        else 0.0
                    )
                    generation_seconds = max(
                        0.0,
                        generation_seconds - source_active_overlap_seconds,
                    )
                    final_processing_seconds = max(0.0, sum(
                        float(validation_scheduling_times[exercise_id].get(key, 0.0))
                        for key in (
                            "renderPrefetchWaitSeconds",
                            "pipelineProcessingSeconds",
                        )
                    ))
                    waves = progress_state.setdefault("waves", {})
                    waves[str(wave_id)] = {
                        "generationSeconds": round(generation_seconds, 3),
                        "finalProcessingSeconds": round(final_processing_seconds, 3),
                        "sourceGenerationOverlapSeconds": round(
                            source_active_overlap_seconds, 3,
                        ),
                        "processingSeconds": round(
                            generation_seconds + final_processing_seconds, 3,
                        ),
                    }
                    retry_disposition = wave_retry_disposition(state)
                    for candidate, video_path in ready_sources:
                        identity = candidate_decision_identity(
                            candidate,
                            item.request,
                            video_path,
                        )
                        if identity is not None:
                            _record_wave_progress_work(
                                progress_state,
                                decision_identity=identity,
                                status=str(final_state.get("status") or "unknown"),
                                retry_disposition=retry_disposition,
                                selection_manifest_path=final_state.get("selectionManifestPath"),
                            )
                    _refresh_wave_progress_elapsed(progress_state)
                    _write_json_atomic(progress_path, progress_state)
                stages = sorted({entry["stage"] for entry in final_state.get("candidateDiagnostics", [])})
                reasons = final_state.get("rejectionReasons", []) or [
                    reason for entry in final_state.get("candidateDiagnostics", []) for reason in entry["reasons"]
                ]
                message = (
                    f"Movement result: {item.exercise_name} | {final_state['status']} | "
                    f"{final_state['elapsedSeconds']:.1f}s final processing | "
                    f"stage(s): {', '.join(stages) or 'processing_error'}"
                )
                phase_totals = {
                    "extractionSeconds": round(sum(attempt.get("elapsedSeconds", 0.0)
                        for attempt in state.get("reconstruction", {}).get("attempts", [])), 3),
                }
                for entry in final_state.get("candidateDiagnostics", []):
                    for key in ("generationSeconds", "rawReconstructionMotionGateSeconds", "previewBakeSeconds", "browser_bakeFailedSeconds"):
                        if key in entry["timings"]:
                            display_key = "finalGenerationReuseSeconds" if key == "generationSeconds" else key
                            phase_totals[display_key] = phase_totals.get(display_key, 0.0) + entry["timings"][key]
                phase_totals.update(final_state.get("reviewTimings", {}))
                scheduling = final_state["schedulingTimings"]
                message += " | elapsed breakdown: " + ", ".join(
                    f"{label}={scheduling[key]:.1f}s" for key, label in (
                        ("executorQueueWaitSeconds", "executor queue"),
                        ("renderPrefetchWaitSeconds", "waiting for render prefetch"),
                        ("pipelineProcessingSeconds", "pipeline including retries"),
                    ) if key in scheduling
                )
                if phase_totals:
                    message += " | timings: " + ", ".join(
                        f"{key}={value:.1f}s" for key, value in phase_totals.items()
                        if key in {"generationSeconds", "rawReconstructionMotionGateSeconds", "previewBakeSeconds", "browser_bakeFailedSeconds",
                                   "reviewRankingSeconds", "selectionMaterializationSeconds"}
                    )
                if reasons:
                    message += f" | reasons: {', '.join(reasons)}"
                if final_state.get("error"):
                    message += f" | {final_state['error']}"
                with checkpoint_lock:
                    metrics["sourceAttemptEvents"].append(message)
                announce(message)
                checkpoint("final_validation", item.exercise_name)
        finally:
            final_executor.shutdown(wait=True)
            # A source-only retry stays in VLM work; it is not a reason to evict
            # a keepalive server. Force-stop only after reconstruction actually
            # ran and a retry may need that GPU again.
            retry_pending = any(state["status"] != "completed" for state in item_states.values())
            reconstruction_conflicted = generation_gpu_operation_count > 0
            final_session.close(force_stop_server=(
                reconstruction_conflicted and retry_pending and accelerator_phase is None
            ))
            metrics["finalVisionSession"] = _session_timing_manifest(final_session)
            metrics["phaseTimings"]["finalValidationSeconds"] = round(
                time.perf_counter() - final_phase_started,
                3,
            )
            try:
                from exercise_motion_pkg.unidepth_runner import unidepth_model_cache_metrics

                metrics["unidepthModelCache"] = unidepth_model_cache_metrics()
            except Exception:
                pass

    source_phase_errors: list[BaseException] = []
    source_thread = None
    if stream_source_handoffs:
        def run_source_phase_thread() -> None:
            nonlocal source_sentinel_emitted
            try:
                source_context.run(run_source_phase)
            except BaseException as exc:
                source_phase_errors.append(exc)
                if not source_sentinel_emitted:
                    source_ready_queue.put(None)
                    source_sentinel_emitted = True

        source_context = copy_context()
        source_thread = threading.Thread(
            target=run_source_phase_thread,
            name=f"{wave_id}-source-producer",
        )
        source_thread.start()

    final_coordinator = ThreadPoolExecutor(max_workers=1, thread_name_prefix="motion-wave-final")
    final_job = final_coordinator.submit(copy_context().run, run_final_jobs)
    try:
        # Only cache misses enter the extraction lease; validation and fitting remain CPU work.
        run_generation_jobs()
        if source_phase_errors:
            raise source_phase_errors[0]
        metrics["phaseTimings"]["reconstructionGenerationSeconds"] = round(
            time.perf_counter() - reconstruction_phase_started, 3,
        )
    finally:
        if source_thread is not None:
            source_thread.join()
        final_ready.put(None)
        final_coordinator.shutdown(wait=True)
        if generation_session is not None:
            metrics["generationVisionSession"] = {
                "exclusiveGpuOperationCount": generation_gpu_operation_count,
                "sessionSharedWithFinalValidation": True,
            }
    final_job.result()

    for exercise_id in prepared:
        state = item_states[exercise_id]
        if exercise_id in reconstruction_ready:
            item, ready_sources = reconstruction_ready[exercise_id]
            source_priority = {
                candidate.workspace_slug: index
                for index, (candidate, _path) in enumerate(prepared[exercise_id][1])
            }
            ready_sources.sort(
                key=lambda source: source_priority[source[0].workspace_slug]
            )
            state["reconstruction"]["status"] = "prepared"
            state["reconstruction"]["candidateKey"] = _candidate_key(ready_sources[0][0])
        else:
            state["reconstruction"]["status"] = "failed"
            state["status"] = "retry_required"

    with accelerator_phase(wave_id, "reconstruction") if accelerator_phase else nullcontext():
        reconstruction_release = _stop_warm_reconstruction_worker_before_vlm(
            [item for item, _sources in prepared.values()]
        )
        if shared_llama_session_dir is not None and not separate_gpu_residency:
            clear_generation_holder_marker(shared_llama_session_dir)
    for state in item_states.values():
        state["reconstructionWorkerRelease"] = reconstruction_release
    checkpoint("reconstruction_released")

    exportable = [state for state in item_states.values() if state["status"] == "completed"]
    accepted = [state for state in exportable if _item_artifact_state(state) == "accepted"]
    manual_review = [state for state in exportable if _item_artifact_state(state) == "manual_review"]
    from exercise_motion_pkg.browser_workers import browser_worker_metrics
    from exercise_motion_pkg.resource_budget import (
        CODING_HEADROOM_LOGICAL_CORES,
        browser_worker_limit,
        cpu_fit_slot_limit,
        logical_core_count,
        staged_generation_cpu_workers,
        usable_logical_cores,
    )
    from exercise_motion_pkg.review_questions import question_cache_metrics
    metrics["browserWorkers"] = browser_worker_metrics()
    metrics["resourceBudget"] = {
        "logicalCores": logical_core_count(),
        "codingHeadroomLogicalCores": CODING_HEADROOM_LOGICAL_CORES,
        "usableLogicalCores": usable_logical_cores(),
        "cpuFitSlots": cpu_fit_slot_limit(),
        "browserWorkerLimit": browser_worker_limit(),
        "generationCpuWorkers": staged_generation_cpu_workers(),
    }
    metrics["reviewQuestionCache"] = question_cache_metrics()
    retry = [state for state in item_states.values() if state["status"] != "completed"]
    try:
        metrics["rejectedSourceOutcomeUpdates"] = _record_wave_source_rejections(
            items,
            item_states,
        )
    except Exception as exc:
        metrics["rejectedSourceOutcomeUpdates"] = [
            {"error": f"{type(exc).__name__}: {exc}"}
        ]
    report = _checkpoint_payload(
        wave_id=wave_id,
        stage="completed",
        item_states=item_states,
        started_at=started_at,
        metrics=metrics,
    )
    report.update(
        {
            "checkpointPath": str(checkpoint_path),
            "completedExerciseCount": len(accepted),
            "exportableExerciseCount": len(exportable),
            "manualReviewExerciseCount": len(manual_review),
            "retryExerciseCount": len(retry),
            "retryExerciseIds": [state["exerciseId"] for state in retry],
        }
    )
    attempts = [attempt for state in item_states.values()
                for attempt in state.get("reconstruction", {}).get("attempts", [])]
    elapsed_minutes = float(report.get("elapsedSeconds") or 0.) / 60.
    report["generationEfficiency"] = {
        "acceptedMovementCount": len(accepted),
        "manualReviewArtifactCount": len(manual_review),
        "exportableArtifactCount": len(exportable),
        "candidateReconstructionAttempts": len(attempts),
        "reportedReconstructionCacheHits": sum(
            str(attempt.get("cacheStatus") or "").startswith("reused") for attempt in attempts),
        "acceptedPerElapsedMinute": len(accepted) / elapsed_minutes if elapsed_minutes > 0 else None,
        "candidateAttemptsPerAcceptedMovement": len(attempts) / len(accepted) if accepted else None,
        "timingBasis": "wave_wall_clock_including_queue_and_validation",
    }
    heartbeat_stop.set()
    heartbeat_thread.join(timeout=1.0)
    _write_json_atomic(report_path, report)
    _write_json_atomic(checkpoint_path, report)
    announce(
        f"Batch finished: {len(accepted)} accepted, {len(manual_review)} need manual review, "
        f"{len(retry)} need another try."
    )
    return report
