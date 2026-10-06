from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable

from exercise_motion_pkg.process_lock import InterProcessFileLock


SOURCE_OUTCOME_INDEX_SCHEMA_VERSION = 2
SOURCE_OUTCOME_INDEX_LOCK_TIMEOUT_SECONDS = 30.0
SOURCE_OUTCOME_INDEX_LOCK_STALE_SECONDS = 5 * 60.0
UNRESOLVED_OUTCOME_STATUSES = frozenset({
    "needs_source_review", "needs_motion_processing", "needs_manual_review",
    "source_processing_failed", "rejected_vlm_timeout", "failed", "blocked_contract",
    "skipped_previous_terminal_result",
})
QUALITY_HISTORY_FIELDS = ("attempts", "sourcePasses", "accepts")


def source_quality_history(stats: dict[str, Any]) -> dict[str, Any]:
    """Keep mixed legacy execution counts out of source-quality ranking.

    Rejection tags overlap within an observation, so subtracting them cannot
    reconstruct a reliable denominator. Retain the old totals for inspection
    and learn a fresh prior from resolved observations for affected records.
    """
    history = stats.get("qualityHistory")
    if isinstance(history, dict):
        return history
    tags = stats.get("rejectionCounts") or {}
    if any(int(tags.get(f"status:{status}") or 0) > 0 for status in UNRESOLVED_OUTCOME_STATUSES):
        return {}
    return stats


def normalize_source_channel(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip()).casefold()
    return text or None


def source_identity(video_id: Any, url: Any) -> str | None:
    normalized_video_id = str(video_id or "").strip()
    if normalized_video_id:
        return f"video:{normalized_video_id}"
    normalized_url = str(url or "").strip()
    return f"url:{normalized_url}" if normalized_url else None


def empty_source_outcome_index() -> dict[str, Any]:
    return {
        "schemaVersion": SOURCE_OUTCOME_INDEX_SCHEMA_VERSION,
        "updatedAt": None,
        "sources": {},
        "channels": {},
    }


def load_source_outcome_index(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return empty_source_outcome_index()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_source_outcome_index()
    if not isinstance(payload, dict):
        return empty_source_outcome_index()
    payload.setdefault("sources", {})
    payload.setdefault("channels", {})
    return payload


def _posterior_success_rate(stats: dict[str, Any], success_key: str) -> float:
    attempts = max(0, int(stats.get("attempts") or 0))
    successes = max(0, min(attempts, int(stats.get(success_key) or 0)))
    # Two neutral pseudo-observations keep sparse history from dominating fresh evidence.
    return (successes + 1.0) / (attempts + 2.0)


def _stats_prior(stats: dict[str, Any]) -> float:
    acceptance = _posterior_success_rate(stats, "accepts")
    source_pass = _posterior_success_rate(stats, "sourcePasses")
    return max(-1.0, min(1.0, ((acceptance * 0.70 + source_pass * 0.30) - 0.5) * 2.0))


def source_outcome_prior(
    index: dict[str, Any],
    *,
    video_id: Any = None,
    url: Any = None,
    channel: Any = None,
) -> dict[str, Any]:
    identity = source_identity(video_id, url)
    source_stats = (index.get("sources") or {}).get(identity) if identity else None
    channel_key = normalize_source_channel(channel)
    channel_stats = (index.get("channels") or {}).get(channel_key) if channel_key else None
    source_stats = source_stats if isinstance(source_stats, dict) else None
    channel_stats = channel_stats if isinstance(channel_stats, dict) else None
    source_stats = source_quality_history(source_stats) if source_stats is not None else None
    channel_stats = source_quality_history(channel_stats) if channel_stats is not None else None

    weighted_scores: list[tuple[float, float]] = []
    if source_stats is not None:
        attempts = max(0, int(source_stats.get("attempts") or 0))
        weighted_scores.append((_stats_prior(source_stats), min(1.0, attempts / 2.0)))
    if channel_stats is not None:
        attempts = max(0, int(channel_stats.get("attempts") or 0))
        # Channel history is useful only after repeated independent observations.
        weighted_scores.append((_stats_prior(channel_stats), min(0.60, attempts / 10.0)))
    total_weight = sum(weight for _score, weight in weighted_scores)
    score = (
        sum(score * weight for score, weight in weighted_scores) / total_weight
        if total_weight > 0.0
        else 0.0
    )
    return {
        "schemaVersion": SOURCE_OUTCOME_INDEX_SCHEMA_VERSION,
        "score": round(score, 4),
        "sourceIdentity": identity,
        "sourceAttempts": int(source_stats.get("attempts") or 0) if source_stats else 0,
        "sourceAccepts": int(source_stats.get("accepts") or 0) if source_stats else 0,
        "channelKey": channel_key,
        "channelAttempts": int(channel_stats.get("attempts") or 0) if channel_stats else 0,
        "channelAccepts": int(channel_stats.get("accepts") or 0) if channel_stats else 0,
    }


def rejection_tags_from_candidate_result(result: dict[str, Any]) -> list[str]:
    tags: set[str] = set()
    status = str(result.get("status") or "").strip()
    if status and status not in {"ready_for_selection", "selected", "selected_alternative"}:
        tags.add(f"status:{status}")

    ignored_subtrees = {
        "candidate",
        "exercisemotioncontract",
        "generationtimings",
        "timings",
    }

    def visit(key: str, value: Any) -> None:
        normalized_key = key.casefold()
        if normalized_key in ignored_subtrees:
            return
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(str(child_key), child_value)
        elif isinstance(value, list) and (
            any(token in normalized_key for token in ("reject", "issue", "failure", "block"))
            or normalized_key == "reasontags"
        ):
            for item in value:
                if isinstance(item, str) and item.strip().casefold() not in {"", "none"}:
                    tags.add(item.strip()[:160])
        elif isinstance(value, str) and any(
            token in normalized_key for token in ("reject", "failure", "blockreason")
        ):
            if value.strip().casefold() not in {"", "none"}:
                tags.add(value.strip()[:160])

    visit("result", result)
    return sorted(tags)[:64]


def candidate_result_is_accepted(result: dict[str, Any]) -> bool:
    status = str(result.get("finalSelectionStatus") or "").strip().casefold()
    return status in {"selected", "selected_alternative", "accepted_after_materialized_review"}


def _increment_stats(
    stats: dict[str, Any],
    *,
    source_passed: bool,
    reconstruction_attempted: bool,
    accepted: bool,
    rejection_tags: Iterable[str],
    observed_at: str,
) -> None:
    if not isinstance(stats.get("qualityHistory"), dict):
        history = source_quality_history(stats)
        stats["qualityHistory"] = {key: int(history.get(key) or 0) for key in QUALITY_HISTORY_FIELDS}
    history = stats["qualityHistory"]
    history["attempts"] += 1
    history["sourcePasses"] += int(source_passed)
    history["accepts"] += int(accepted)
    stats["attempts"] = int(stats.get("attempts") or 0) + 1
    stats["sourcePasses"] = int(stats.get("sourcePasses") or 0) + int(source_passed)
    stats["reconstructionAttempts"] = int(stats.get("reconstructionAttempts") or 0) + int(reconstruction_attempted)
    stats["accepts"] = int(stats.get("accepts") or 0) + int(accepted)
    rejection_counts = Counter(stats.get("rejectionCounts") or {})
    rejection_counts.update(str(tag) for tag in rejection_tags if str(tag).strip())
    stats["rejectionCounts"] = dict(sorted(rejection_counts.items()))
    stats["lastObservedAt"] = observed_at


def update_source_outcome_index(
    path: Path | None,
    candidate_results: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved_path = path.expanduser().resolve()
    observations: dict[str, dict[str, Any]] = {}
    for result in candidate_results:
        # An unresolved observation or contract is not evidence against a source.
        # Other, resolved windows from that same video still update its history.
        if (result.get("status") in UNRESOLVED_OUTCOME_STATUSES
                or result.get("finalSelectionStatus") in {"processing_incomplete", "review_incomplete"}):
            continue
        candidate = result.get("candidate") if isinstance(result.get("candidate"), dict) else {}
        identity = source_identity(candidate.get("videoId"), candidate.get("url"))
        if identity is None:
            continue
        observation = observations.setdefault(
            identity,
            {
                "videoId": candidate.get("videoId"),
                "url": candidate.get("url"),
                "channel": candidate.get("channel"),
                "sourcePassed": False,
                "reconstructionAttempted": False,
                "accepted": False,
                "rejectionTags": set(),
            },
        )
        reconstruction_attempted = result.get("reconstructionAttempted") is True
        observation["reconstructionAttempted"] |= reconstruction_attempted
        accepted = candidate_result_is_accepted(result)
        observation["sourcePassed"] |= (
            reconstruction_attempted
            or result.get("status") == "ready_for_selection"
            or accepted
        )
        observation["accepted"] |= accepted
        observation["rejectionTags"].update(rejection_tags_from_candidate_result(result))

    if not observations:
        return None
    lock_path = resolved_path.with_suffix(f"{resolved_path.suffix}.lock")
    with InterProcessFileLock(
        lock_path,
        stage="source_outcome_index_update",
        timeout_seconds=SOURCE_OUTCOME_INDEX_LOCK_TIMEOUT_SECONDS,
        stale_after_seconds=SOURCE_OUTCOME_INDEX_LOCK_STALE_SECONDS,
    ):
        index = load_source_outcome_index(resolved_path)
        sources = index.setdefault("sources", {})
        channels = index.setdefault("channels", {})
        observed_at = datetime.now(timezone.utc).isoformat()
        for identity, observation in observations.items():
            source_stats = sources.setdefault(identity, {})
            source_stats.update(
                {
                    "videoId": observation["videoId"],
                    "url": observation["url"],
                    "channel": observation["channel"],
                }
            )
            update_kwargs = {
                "source_passed": bool(observation["sourcePassed"]),
                "reconstruction_attempted": bool(observation["reconstructionAttempted"]),
                "accepted": bool(observation["accepted"]),
                "rejection_tags": observation["rejectionTags"],
                "observed_at": observed_at,
            }
            _increment_stats(source_stats, **update_kwargs)
            channel_key = normalize_source_channel(observation["channel"])
            if channel_key is not None:
                channel_stats = channels.setdefault(channel_key, {"channel": observation["channel"]})
                _increment_stats(channel_stats, **update_kwargs)
        index["schemaVersion"] = SOURCE_OUTCOME_INDEX_SCHEMA_VERSION
        index["updatedAt"] = observed_at
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = resolved_path.with_suffix(f"{resolved_path.suffix}.tmp")
        temporary_path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
        temporary_path.replace(resolved_path)
    return {
        "path": str(resolved_path),
        "observedSourceCount": len(observations),
        "updatedAt": observed_at,
    }
