"""Shared acceptance decisions and content identity for retained motion artifacts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shutil
import uuid
from typing import Any, Literal


AcceptanceStatus = Literal["valid", "invalid", "needs_manual_review"]


def invalidate_retained_acceptance(directory: Path, reason: str) -> None:
    """Invalidate before modifying a retained artifact, including copied manifests."""
    marker = {"status": "needs_manual_review", "reasons": [reason], "artifactIdentity": None}
    (directory / "revalidation.json").write_text(json.dumps(marker, indent=2), encoding="utf-8")
    path = directory / "selection_manifest.json"
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        selected = manifest.get("selected") or {}
        ranking = selected.get("ranking") or {}
        payload = ranking.setdefault("payload", {})
        payload.update(materializedOutputRejected=True,
                       acceptanceDecision=AcceptanceDecision("needs_manual_review", "evidence", (reason,)).to_dict(),
                       finalOutputValidation={"passed": False, "failureOwner": "review", "rejectionReasons": [reason]})
        selected["ranking"] = ranking
        manifest["selected"] = selected
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def promote_verified_artifact(source: Path, destination: Path, *, policies: dict[str, Any],
                              context: dict[str, Any] | None = None,
                              contract: dict[str, Any] | None = None) -> Path | None:
    """Copy and verify before replacing selection; preserve the previous selection."""
    source, destination = source.resolve(), destination.resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Promotion source and destination must be separate directories")

    def verify(directory: Path) -> dict[str, Any]:
        marker = json.loads((directory / "revalidation.json").read_text(encoding="utf-8"))
        manifest = json.loads((directory / "selection_manifest.json").read_text(encoding="utf-8"))
        identity = selected_artifact_identity(directory, manifest, policies=policies, context=context, contract=contract)
        if marker.get("status") != "valid" or identity is None or marker.get("artifactIdentity") != identity:
            raise ValueError("Promotion requires a current valid verdict for these exact artifacts")
        return identity

    identity = verify(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(destination.name + ".staged-" + uuid.uuid4().hex)
    backup = destination.with_name(destination.name + ".backup-" + uuid.uuid4().hex) if destination.exists() else None
    shutil.copytree(source, staged)
    if verify(staged) != identity or verify(source) != identity:
        raise ValueError(f"Artifacts changed during promotion; staged copy retained at {staged}")
    if backup is not None:
        destination.rename(backup)
    try:
        staged.rename(destination)
    except OSError:
        if backup is not None:
            backup.rename(destination)
        raise
    return backup


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def selected_artifact_identity(
    directory: Path, manifest: dict[str, Any], *, policies: dict[str, Any],
    context: dict[str, Any] | None = None, contract: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Paths are not identity; exactly one retained source and skeleton are."""
    sources = [*directory.glob("*_selected_input.mp4"), *directory.glob("*_selected_input.webm")]
    skeletons = list(directory.glob("*_wear_skeleton.json"))
    selected = manifest.get("selected")
    if len(sources) != 1 or len(skeletons) != 1 or not isinstance(selected, dict):
        return None
    ranking = selected.get("ranking") or {}
    if not isinstance(ranking, dict):
        return None
    payload = ranking.get("payload") or {}
    candidate = selected.get("candidate") or {}
    if not isinstance(payload, dict) or not isinstance(candidate, dict):
        return None
    active_contract = contract if contract is not None else payload.get("exerciseMotionContract") or candidate.get("exerciseMotionContract")
    if active_contract is not None and not isinstance(active_contract, dict):
        return None
    # Cache location and elapsed timings are bookkeeping, not requirements.
    active_contract = {k: v for k, v in (active_contract or {}).items()
                       if k not in {"cachePath", "cacheStatus", "generatedAt", "elapsedSeconds"}}
    try:
        return {
            "schemaVersion": 1,
            "sourceSha256": content_hash(sources[0]),
            "skeletonSha256": content_hash(skeletons[0]),
            "contractSha256": semantic_hash({"contract": active_contract, "context": context or {}}),
            "selectionSha256": semantic_hash({k: selected.get(k) for k in (
                "loopIndex", "loopStartSeconds", "loopEndSeconds", "durationSec",
                "selectedSectionStartSeconds", "selectedSectionEndSeconds", "settingsOptions",
                "llmTimeRangeCutApplied", "sourceReviewStartSeconds", "sourceReviewEndSeconds",
            )}),
            "policies": policies,
        }
    except (OSError, ValueError, TypeError):
        return None


@dataclass(frozen=True)
class AcceptanceDecision:
    status: AcceptanceStatus
    failure_owner: str | None
    reasons: tuple[str, ...]
    can_regenerate_motion: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decide_acceptance(
    metrics: dict[str, Any], review: dict[str, Any], *,
    deterministic_rejections: list[str], review_rejections: list[str],
    require_visual_review: bool = True,
) -> AcceptanceDecision:
    """Independent failures survive review uncertainty; missing evidence cannot approve."""
    # Old cached balance warnings no longer constitute an acceptance failure.
    deterministic_rejections = [reason for reason in deterministic_rejections
                                if reason != "physical_balance_requires_review"]
    missing: list[str] = []
    if not metrics:
        missing.append("materialized_output_evidence_missing")
    for name, value in metrics.items():
        if not isinstance(value, dict) or value.get("required") is not True:
            continue
        if value.get("available") is False or value.get("evaluated") is False or value.get("passed") is None:
            missing.append(f"required_evidence_unavailable:{name}")
    if metrics.get("skippedReasons") and "materialized_output_skeleton_missing" in metrics["skippedReasons"]:
        missing.append("materialized_output_skeleton_missing")
    concrete = [reason for reason in deterministic_rejections
                if not any(word in reason for word in ("unavailable", "missing", "validator_failed"))]
    if concrete:
        source_failure = any("source" in r and any(w in r for w in ("incomplete", "identity", "boundary", "variant")) for r in concrete)
        return AcceptanceDecision("invalid", "source" if source_failure else "motion_output",
                                  tuple(dict.fromkeys(deterministic_rejections)), not source_failure)
    if missing or deterministic_rejections:
        return AcceptanceDecision("needs_manual_review", "evidence", tuple(dict.fromkeys([*missing, *deterministic_rejections])))
    if review.get("failureOwner") == "review" or review.get("reviewStatus") == "needs_manual_review":
        return AcceptanceDecision("needs_manual_review", "review", tuple(review_rejections or ["review_unresolved"]))
    if review_rejections:
        owner = review.get("failureOwner") or "motion_output"
        return AcceptanceDecision("invalid", owner, tuple(review_rejections), owner == "motion_output")
    if require_visual_review and review.get("passed") is not True:
        return AcceptanceDecision("needs_manual_review", "review", ("visual_review_not_approved",))
    return AcceptanceDecision("valid", None, ())
