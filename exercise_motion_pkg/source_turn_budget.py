"""Shared, lightweight source-review budget and admission helpers."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


SOURCE_TURN_BUDGET_POLICY_VERSION = 2


class _SourceTurnBudget:
    """One bounded source-review turn shared by every window for an exercise."""

    def __init__(
        self,
        request: Any,
        resume: dict[str, Any] | None = None,
        *,
        started_at: float | None = None,
        exercise_identity: str | None = None,
    ) -> None:
        self.started_at = time.perf_counter() if started_at is None else started_at
        resume = resume if isinstance(resume, dict) else {}
        identity_matches = (
            exercise_identity is None
            or resume.get("sourceTurnExerciseIdentity") == exercise_identity
        )
        if (
            resume.get("sourceTurnBudgetPolicyVersion") != SOURCE_TURN_BUDGET_POLICY_VERSION
            or not identity_matches
        ):
            resume = {}
        self.exercise_identity = exercise_identity
        try:
            self.elapsed_before = max(0.0, float(resume.get("sourceTurnElapsedSeconds") or 0.0))
        except (TypeError, ValueError):
            self.elapsed_before = 0.0
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
        if self.deadline is not None and now >= self.deadline:
            return "source_turn_deadline"
        if self.attempt_limit is not None and self.attempts_used >= self.attempt_limit:
            return "source_turn_attempt_budget"
        return None

    def begin_attempt(self) -> None:
        self.attempts_used += 1

    def elapsed(self, now: float | None = None) -> float:
        now = time.perf_counter() if now is None else now
        return self.elapsed_before + max(0.0, now - self.started_at)

    def resume_fields(self, now: float | None = None) -> dict[str, Any]:
        return {
            "sourceTurnBudgetPolicyVersion": SOURCE_TURN_BUDGET_POLICY_VERSION,
            "sourceTurnExerciseIdentity": self.exercise_identity,
            "sourceTurnElapsedSeconds": round(self.elapsed(now), 3),
            "sourceTurnAttemptsUsed": self.attempts_used,
            "sourceTurnTimeoutSeconds": self.timeout_seconds,
            "sourceTurnAttemptLimit": self.attempt_limit,
        }

    def report(self, now: float | None = None, *, stop_reason: str | None = None) -> dict[str, Any]:
        return {
            "elapsedSeconds": round(self.elapsed(now), 3),
            "deadlineSeconds": self.timeout_seconds,
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


def source_turn_budget_readiness(
    workspace: str | Path,
    exercise_id: str,
    exercise_name: str,
    authoritative_exercise_motion_context: dict[str, Any] | None,
    source_review_timeout_seconds: float,
    exercise_timeout_seconds: float,
    max_source_window_attempts: int,
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
    effective_ledger = ledger if identity_matches else {}
    request = SimpleNamespace(
        source_review_timeout_seconds=source_review_timeout_seconds,
        exercise_timeout_seconds=exercise_timeout_seconds,
        max_source_window_attempts=max_source_window_attempts,
    )
    budget = _SourceTurnBudget(request, effective_ledger, exercise_identity=identity)
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
    return {
        "ready": stop_reason is None,
        "stopReason": stop_reason,
        "elapsedSeconds": round(elapsed, 3),
        "attemptsUsed": budget.attempts_used,
        "remainingSeconds": remaining_seconds,
        "remainingAttempts": remaining_attempts,
        "identityMatches": identity_matches,
        "resetRequired": bool(ledger) and not identity_matches,
        "budgetPath": str(ledger_path),
    }
