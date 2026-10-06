"""Bound retained terminal results and logs for persistent warm workers."""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any


WARM_WORKER_RESULT_RETENTION_SECONDS = 14 * 24 * 60 * 60
MAX_RETAINED_WARM_WORKER_RESULTS = 512
PRUNABLE_TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "rejected_tracking_preflight"}
)


def _recorded_job_ids(directory: Path) -> set[str]:
    job_ids = {path.stem for path in directory.glob("*.json")}
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            recorded_job_id = str(payload.get("jobId") or "")
            if recorded_job_id:
                job_ids.add(recorded_job_id)
    return job_ids


def prune_terminal_warm_worker_artifacts(
    state_dir: Path,
    *,
    now_epoch: float | None = None,
    retention_seconds: int | None = None,
    max_results: int | None = None,
) -> int:
    """Prune old terminal results and their logs, preserving active/ambiguous work.

    The count limit keeps the newest terminal records after age-based expiry.
    Malformed results and results with non-prunable statuses are retained as
    evidence. Queued and running requests are only inspected to protect their
    job IDs; this function never removes or moves them.
    """
    state_dir = Path(state_dir)
    results_dir = state_dir / "results"
    job_logs_dir = state_dir / "job_logs"
    now = time.time() if now_epoch is None else float(now_epoch)
    max_age = (
        WARM_WORKER_RESULT_RETENTION_SECONDS
        if retention_seconds is None
        else max(0, int(retention_seconds))
    )
    result_limit = (
        MAX_RETAINED_WARM_WORKER_RESULTS
        if max_results is None
        else max(0, int(max_results))
    )
    protected_job_ids = set()
    for directory_name in ("jobs", "running", "ambiguous"):
        protected_job_ids.update(_recorded_job_ids(state_dir / directory_name))

    eligible: list[tuple[float, Path]] = []
    for result_path in results_dir.glob("*.json"):
        if result_path.stem in protected_job_ids:
            continue
        try:
            payload: Any = json.loads(result_path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("status") not in PRUNABLE_TERMINAL_STATUSES
            ):
                continue
            modified_at = result_path.stat().st_mtime
        except (OSError, ValueError):
            continue
        eligible.append((modified_at, result_path))

    eligible.sort(key=lambda record: (record[0], record[1].name))
    cutoff = now - max_age
    expired = {path for modified_at, path in eligible if modified_at < cutoff}
    retained = [(modified_at, path) for modified_at, path in eligible if path not in expired]
    excess_count = max(0, len(retained) - result_limit)
    expired.update(path for _, path in retained[:excess_count])

    removed_results = 0
    for result_path in sorted(expired):
        logs_removed = True
        for suffix in ("stdout.log", "stderr.log"):
            log_path = job_logs_dir / f"{result_path.stem}.{suffix}"
            try:
                log_path.unlink(missing_ok=True)
            except OSError:
                logs_removed = False
        if not logs_removed:
            continue
        try:
            result_path.unlink(missing_ok=True)
        except OSError:
            continue
        removed_results += 1
    return removed_results
