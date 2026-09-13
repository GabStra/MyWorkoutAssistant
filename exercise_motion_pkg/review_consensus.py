"""Bounded corroboration of visual rejections; disagreement never approves a clip."""
from __future__ import annotations

from typing import Any, Callable
from .visual_evidence import claims_agree, body_evidence_exclusion


def corroborate_rejection(
    first: dict[str, Any], review_once: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if first.get("passed") is True:
        return first
    try:
        second = review_once()
    except Exception as exc:
        second = {"passed": False, "failureOwner": "review", "error": type(exc).__name__}
    common = set(first.get("reject") or []) & set(second.get("reject") or [])
    # Agreement on a generic rejection or on unsupported evidence is insufficient.
    common -= {"unclear", "low_confidence", "needs_retry"}
    common = {tag for tag in common if claims_agree(first, second, tag)}
    for observation in (first, second):
        payload = observation.get("modelPayload") or {}
        evidence = payload.get("rejectionEvidence") or []
        supported = {row.get("tag") for row in evidence if isinstance(row, dict)
                     and body_evidence_exclusion(row) is None}
        common &= supported
    corroborated = bool(common) and all(
        result.get("passed") is False and result.get("failureOwner") != "review"
        and result.get("reviewStatus") != "needs_manual_review"
        for result in (first, second)
    )
    result = dict(first)
    result["boundedReview"] = {"additionalReviewCount": 0 if second.get("additionalEvidenceUnavailable") else 1,
                              "first": first, "second": second,
                              "corroborated": corroborated, "commonRejectionTags": sorted(common)}
    if not corroborated:
        result.update(passed=False, approved=False, retry=False, needsRetry=False,
                      failureOwner="review", underlyingMotionRejected=False,
                      reviewStatus="needs_manual_review",
                      hardRejectionReasons=["visual_review_unresolved"],
                      rejectionReasons=["visual_review_unresolved"])
    else:
        # Only corroborated observations remain blocking. Retain the full first
        # response above for diagnostics, not as an independent repair directive.
        result["reject"] = sorted(common)
        result["hardRejectionReasons"] = sorted(common)
        result["rejectionReasons"] = sorted(common)
    return result
