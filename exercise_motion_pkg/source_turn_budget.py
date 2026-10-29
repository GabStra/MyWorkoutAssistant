"""Shared, lightweight source-review budget and admission helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


SOURCE_TURN_BUDGET_POLICY_VERSION = 3
DEFAULT_SOURCE_TURN_WAIT_TIMEOUT_SECONDS = 180.0


class SourceTurnWaitBudgetExpired(TimeoutError):
    """A source turn spent its bounded allowance waiting for shared VLM access."""


class _SourceTurnBudget:
    """One bounded source-review turn shared by every window for an exercise."""

    def __init__(
        self,
        request: Any,
        resume: dict[str, Any] | None = None,
        *,
        started_at: float | None = None,
        exercise_identity: str | None = None,
        turn_identity: str | None = None,
    ) -> None:
        self.started_at = time.perf_counter() if started_at is None else started_at
        resume = resume if isinstance(resume, dict) else {}
        identity_matches = (
            exercise_identity is None
            or resume.get("sourceTurnExerciseIdentity") == exercise_identity
        )
        turn_matches = (
            turn_identity is None
            or resume.get("sourceTurnScopeIdentity") == turn_identity
        )
        if (
            resume.get("sourceTurnBudgetPolicyVersion") != SOURCE_TURN_BUDGET_POLICY_VERSION
            or not identity_matches
            or not turn_matches
        ):
            resume = {}
        self.exercise_identity = exercise_identity
        self.turn_identity = turn_identity
        try:
            self.elapsed_before = max(0.0, float(resume.get("sourceTurnElapsedSeconds") or 0.0))
        except (TypeError, ValueError):
            self.elapsed_before = 0.0
        try:
            self.excluded_wait_before = max(0.0, float(resume.get("sourceTurnExcludedWaitSeconds") or 0.0))
        except (TypeError, ValueError):
            self.excluded_wait_before = 0.0
        self.excluded_wait_added = 0.0
        try:
            self.attempts_before = max(0, int(resume.get("sourceTurnAttemptsUsed") or 0))
        except (TypeError, ValueError):
            self.attempts_before = 0
        previous_timeout = resume.get("sourceTurnTimeoutSeconds")
        previous_attempt_limit = resume.get("sourceTurnAttemptLimit")
        limits = [
            float(getattr(request, "source_review_timeout_seconds", 0.0) or 0.0),
            float(getattr(request, "exercise_timeout_seconds", 0.0) or 0.0),
        ]
        positive_limits = [limit for limit in limits if limit > 0.0]
        self.timeout_seconds = min(positive_limits) if positive_limits else None
        self.wait_timeout_seconds = (
            self.timeout_seconds
            if self.timeout_seconds is not None
            else DEFAULT_SOURCE_TURN_WAIT_TIMEOUT_SECONDS
        )
        self.wait_budget_expired = (
            self.excluded_wait_before >= self.wait_timeout_seconds
        )
        self.deadline = (
            self.started_at + max(0.0, self.timeout_seconds - self.elapsed_before)
            if self.timeout_seconds is not None
            else None
        )
        configured_attempts = max(0, int(getattr(request, "max_source_window_attempts", 0) or 0))
        self.attempt_limit = configured_attempts or None
        self.attempts_used = self.attempts_before
        try:
            timeout_extended = (
                self.timeout_seconds is not None
                and (previous_timeout is None or self.timeout_seconds > float(previous_timeout))
            )
        except (TypeError, ValueError):
            timeout_extended = self.timeout_seconds is not None
        try:
            attempt_limit_extended = (
                self.attempt_limit is not None
                and (previous_attempt_limit is None or self.attempt_limit > int(previous_attempt_limit))
            )
        except (TypeError, ValueError):
            attempt_limit_extended = self.attempt_limit is not None
        self.budget_extended_by_configuration = timeout_extended or attempt_limit_extended

    def stop_reason(self, now: float | None = None) -> str | None:
        now = time.perf_counter() if now is None else now
        if self.wait_budget_expired:
            return "source_turn_wait_budget"
        if self.deadline is not None and now >= self.deadline:
            return "source_turn_deadline"
        if self.attempt_limit is not None and self.attempts_used >= self.attempt_limit:
            return "source_turn_attempt_budget"
        return None

    def begin_attempt(self) -> None:
        self.attempts_used += 1

    def elapsed(self, now: float | None = None) -> float:
        now = time.perf_counter() if now is None else now
        return max(
            0.0,
            self.elapsed_before + max(0.0, now - self.started_at) - self.excluded_wait_added,
        )

    def exclude_wait(self, seconds: float) -> float | None:
        """Pause active review time while this worker waits for shared VLM admission/startup."""
        duration = max(0.0, float(seconds))
        remaining_wait = (
            max(
                0.0,
                self.wait_timeout_seconds - self.excluded_wait_before - self.excluded_wait_added,
            )
        )
        if remaining_wait <= 0.0:
            self.wait_budget_expired = True
            raise SourceTurnWaitBudgetExpired(
                "Source turn exhausted its bounded wait allowance for VLM admission/startup."
            )
        self.excluded_wait_added += duration
        if self.deadline is not None:
            self.deadline += min(duration, remaining_wait or 0.0)
        if duration > remaining_wait:
            self.wait_budget_expired = True
            raise SourceTurnWaitBudgetExpired(
                "Source turn exhausted its bounded wait allowance for VLM admission/startup."
            )
        return self.deadline

    def remaining_wait_seconds(self) -> float:
        return max(
            0.0,
            self.wait_timeout_seconds - self.excluded_wait_before - self.excluded_wait_added,
        )

    def resume_fields(self, now: float | None = None) -> dict[str, Any]:
        elapsed = self.elapsed(now)
        excluded_wait = self.excluded_wait_before + self.excluded_wait_added
        return {
            "sourceTurnBudgetPolicyVersion": SOURCE_TURN_BUDGET_POLICY_VERSION,
            "sourceTurnExerciseIdentity": self.exercise_identity,
            "sourceTurnScopeIdentity": self.turn_identity,
            "sourceTurnElapsedSeconds": round(elapsed, 3),
            "sourceTurnExcludedWaitSeconds": round(excluded_wait, 3),
            "sourceTurnWaitTimeoutSeconds": self.wait_timeout_seconds,
            "sourceTurnActivePlusWaitSeconds": round(elapsed + excluded_wait, 3),
            "sourceTurnAttemptsUsed": self.attempts_used,
            "sourceTurnTimeoutSeconds": self.timeout_seconds,
            "sourceTurnAttemptLimit": self.attempt_limit,
        }

    def report(self, now: float | None = None, *, stop_reason: str | None = None) -> dict[str, Any]:
        elapsed = self.elapsed(now)
        excluded_wait = self.excluded_wait_before + self.excluded_wait_added
        return {
            "elapsedSeconds": round(elapsed, 3),
            "excludedWaitSeconds": round(excluded_wait, 3),
            "activePlusWaitSeconds": round(elapsed + excluded_wait, 3),
            "deadlineSeconds": self.timeout_seconds,
            "waitBudgetSeconds": self.wait_timeout_seconds,
            "attemptBudget": self.attempt_limit,
            "attemptsUsed": self.attempts_used,
            "budgetExtendedByConfiguration": self.budget_extended_by_configuration,
            "stopReason": stop_reason,
        }


def _source_turn_exercise_identity(
    exercise_id: str,
    exercise_name: str,
    authoritative_exercise_motion_context: dict[str, Any] | None,
) -> str:
    """Stable identity excluding candidate pools and invocation IDs."""
    identity_payload = {
        "exerciseId": str(exercise_id or "").strip(),
        "exerciseName": str(exercise_name or "").strip(),
        "authoritativeExerciseMotionContext": (
            authoritative_exercise_motion_context
            if isinstance(authoritative_exercise_motion_context, dict)
            else {}
        ),
    }
    canonical = json.dumps(identity_payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_source_turn_cursor(
    path: str | Path,
    *,
    source_selection_policy_version: int,
    exercise_id: str,
    exercise_name: str,
    authoritative_exercise_motion_context: dict[str, Any] | None,
    source_review_turn_id: str | None,
) -> dict[str, Any] | None:
    """Load a cursor only when its policy, exercise contract and review turn match."""
    try:
        cursor = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cursor, dict):
        return None
    expected_identity = _source_turn_exercise_identity(
        exercise_id, exercise_name, authoritative_exercise_motion_context,
    )
    if (
        cursor.get("sourceSelectionPolicyVersion") != int(source_selection_policy_version)
        or cursor.get("sourceTurnExerciseIdentity") != expected_identity
        or cursor.get("sourceReviewTurnId") != (str(source_review_turn_id or "").strip() or None)
        or not isinstance(cursor.get("attemptedCandidateKeys"), list)
        or not isinstance(cursor.get("attemptedVideoIds"), list)
    ):
        return None
    return cursor


def _source_cursor_plan_context(plan_path: str | Path, exercise_id: str, exercise_name: str):
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    exercises = plan.get("exercises") if isinstance(plan, dict) else None
    if not isinstance(exercises, list):
        raise ValueError("Exercise plan has no authoritative exercises array.")
    matches = [
        exercise for exercise in exercises
        if isinstance(exercise, dict)
        and str(exercise.get("id") or "") == str(exercise_id or "")
        and str(exercise.get("name") or "") == str(exercise_name or "")
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("motionContext"), dict):
        raise ValueError("Exercise plan does not uniquely match the source cursor exercise and motion contract.")
    return matches[0]["motionContext"]


def _unique_nonblank(values: list[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def _list_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def write_source_turn_cursor_from_wave_state(
    path: str | Path,
    *,
    wave_state: dict[str, Any],
    exercise_plan_path: str | Path,
    source_review_turn_id: str,
    transition: str,
) -> dict[str, Any]:
    """Persist the canonical source cursor from a full staged-wave item receipt.

    The PowerShell runner hands off the complete item receipt; Python owns its
    interpretation, identity, exclusions, budget merge and persisted schema.
    """
    if transition not in {"next_source_candidate", "bounded_source_discovery"}:
        raise ValueError(f"Unsupported source cursor transition: {transition}")
    if not isinstance(wave_state, dict) or not isinstance(wave_state.get("source"), dict):
        raise ValueError("Staged-wave item receipt has no source state.")
    exercise_id = str(wave_state.get("exerciseId") or "").strip()
    exercise_name = str(wave_state.get("exerciseName") or "").strip()
    turn_id = str(source_review_turn_id or "").strip()
    if not exercise_id or not exercise_name or not turn_id:
        raise ValueError("Source cursor requires exact exercise and review-turn identity.")
    motion_context = _source_cursor_plan_context(exercise_plan_path, exercise_id, exercise_name)
    exercise_identity = _source_turn_exercise_identity(exercise_id, exercise_name, motion_context)
    source = wave_state["source"]
    try:
        selection_policy = int(source.get("sourceSelectionPolicyVersion"))
    except (TypeError, ValueError):
        raise ValueError("Staged-wave receipt has no valid source-selection policy version.") from None
    if selection_policy <= 0:
        raise ValueError("Staged-wave receipt has no valid source-selection policy version.")

    attempts = source.get("attempts") if isinstance(source.get("attempts"), list) else []
    attempted_keys = _unique_nonblank([
        *_list_values(source.get("priorAttemptedCandidateKeys")),
        *(attempt.get("candidateKey") for attempt in attempts if isinstance(attempt, dict)),
    ])
    attempted_video_ids = _unique_nonblank([
        *_list_values(source.get("priorAttemptedVideoIds")),
        *(attempt.get("videoId") for attempt in attempts if isinstance(attempt, dict)),
    ])
    next_candidate_key = None
    if transition == "next_source_candidate":
        next_candidate_key = str(source.get("nextCandidateKey") or "").strip() or None
        if next_candidate_key is None:
            raise ValueError("Next-source transition has no next candidate key.")

    cursor_path = Path(path)
    prior = load_source_turn_cursor(
        cursor_path,
        source_selection_policy_version=selection_policy,
        exercise_id=exercise_id,
        exercise_name=exercise_name,
        authoritative_exercise_motion_context=motion_context,
        source_review_turn_id=turn_id,
    ) or {}
    budget_path = cursor_path.with_name("source_turn_budget.json")
    try:
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        budget = {}
    if not isinstance(budget, dict):
        budget = {}
    budget_matches = (
        budget.get("sourceTurnExerciseIdentity") == exercise_identity
        and budget.get("sourceTurnScopeIdentity") == turn_id
        and budget.get("sourceTurnBudgetPolicyVersion") == SOURCE_TURN_BUDGET_POLICY_VERSION
    )
    previous_keys = prior.get("attemptedCandidateKeys", [])
    previous_videos = prior.get("attemptedVideoIds", [])
    cursor = {
        "sourceSelectionPolicyVersion": selection_policy,
        "sourceTurnExerciseIdentity": exercise_identity,
        "sourceReviewTurnId": turn_id,
        "nextCandidateKey": next_candidate_key,
        "attemptedCandidateKeys": _unique_nonblank([*previous_keys, *attempted_keys]),
        "attemptedVideoIds": _unique_nonblank([*previous_videos, *attempted_video_ids]),
        "cursorTransition": transition,
        "cursorExerciseId": exercise_id,
        "cursorExerciseName": exercise_name,
    }
    if budget_matches:
        cursor.update({key: value for key, value in budget.items() if key.startswith("sourceTurn")})
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=cursor_path.parent,
        prefix=f".{cursor_path.name}.", suffix=".tmp", delete=False,
    )
    temporary_path = Path(handle.name)
    try:
        with handle:
            json.dump(cursor, handle, indent=2)
            handle.write("\n")
        os.replace(temporary_path, cursor_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return cursor


def source_turn_budget_readiness(
    workspace: str | Path,
    exercise_id: str,
    exercise_name: str,
    authoritative_exercise_motion_context: dict[str, Any] | None,
    source_review_timeout_seconds: float,
    exercise_timeout_seconds: float,
    max_source_window_attempts: int,
    turn_identity: str | None = None,
) -> dict[str, Any]:
    """Read-only admission check for batched offline source preflight."""
    workspace_path = Path(workspace)
    ledger_path = workspace_path / "source_turn_budget.json"
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        if not isinstance(ledger, dict):
            ledger = {}
    except (OSError, ValueError):
        ledger = {}
    identity = _source_turn_exercise_identity(
        exercise_id, exercise_name, authoritative_exercise_motion_context
    )
    identity_matches = ledger.get("sourceTurnExerciseIdentity") == identity
    turn_matches = (
        turn_identity is None
        or ledger.get("sourceTurnScopeIdentity") == turn_identity
    )
    effective_ledger = ledger if identity_matches else {}
    request = SimpleNamespace(
        source_review_timeout_seconds=source_review_timeout_seconds,
        exercise_timeout_seconds=exercise_timeout_seconds,
        max_source_window_attempts=max_source_window_attempts,
    )
    budget = _SourceTurnBudget(
        request,
        effective_ledger,
        exercise_identity=identity,
        turn_identity=turn_identity,
    )
    stop_reason = budget.stop_reason()
    elapsed = budget.elapsed()
    remaining_seconds = (
        None if budget.timeout_seconds is None
        else max(0.0, budget.timeout_seconds - elapsed)
    )
    remaining_attempts = (
        None if budget.attempt_limit is None
        else max(0, budget.attempt_limit - budget.attempts_used)
    )
    excluded_wait = budget.excluded_wait_before
    return {
        "ready": stop_reason is None,
        "stopReason": stop_reason,
        "elapsedSeconds": round(elapsed, 3),
        "attemptsUsed": budget.attempts_used,
        "remainingSeconds": remaining_seconds,
        "excludedWaitSeconds": round(excluded_wait, 3),
        "remainingWaitSeconds": (
            max(0.0, budget.wait_timeout_seconds - excluded_wait)
        ),
        "remainingAttempts": remaining_attempts,
        "identityMatches": identity_matches,
        "turnScopeMatches": turn_matches,
        "resetRequired": bool(ledger) and not (identity_matches and turn_matches),
        "budgetPath": str(ledger_path),
    }
