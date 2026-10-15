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
SOURCE_SELECTION_CLEARANCE_POLICY_VERSION = 2


def source_contract_clearance_sha256(contract: dict[str, Any] | None) -> str:
    from .youtube import exercise_motion_contract_prompt_sha256

    return exercise_motion_contract_prompt_sha256(contract)


def source_selection_clearance_is_current(
    manifest: dict[str, Any], *, source_policy_version: int | None = None,
    selected_source_path: Path | None = None,
    expected_exercise_name: str | None = None,
    expected_contract: dict[str, Any] | None = None,
) -> bool:
    """Require a source-stage clearance for normal and unknown lineages.

    Only a manifest that explicitly records source validation as disabled can
    use the diagnostic/raw path. A clearance attestation is tied to the source
    policy and source manifest identity so an older selected-output marker
    cannot stand in for a current source review.
    """
    selected = manifest.get("selected")
    if not isinstance(selected, dict):
        return False
    clearance = selected.get("sourceSelectionClearance")
    if not isinstance(clearance, dict):
        return False
    expected_status = (
        "not_required"
        if manifest.get("preReconstructionSourceValidationEnabled") is False
        else "cleared"
    )
    if clearance.get("status") != expected_status:
        return False
    if expected_status == "not_required" and manifest.get(
        "preReconstructionSourceValidationExplicitlyDisabled"
    ) is not True:
        return False
    if clearance.get("sourceSelectionClearancePolicyVersion") != SOURCE_SELECTION_CLEARANCE_POLICY_VERSION:
        return False
    source_version = clearance.get("sourceSelectionPolicyVersion")
    if source_policy_version is not None and source_version != source_policy_version:
        return False
    if source_policy_version is None and source_version != manifest.get("sourceSelectionPolicyVersion"):
        return False
    required_fields = (
        ("sourceManifestSha256", "selectedSegmentSha256", "sourcePrepReason", "sourceManifestPath", "selectedSegmentPath")
        if expected_status == "not_required"
        else (
            "sourceManifestSha256", "selectedSegmentSha256", "authorizedCandidateId",
            "sourceManifestPath", "selectedSegmentPath", "sourceCutReviewVideoPath",
            "sourceCutReviewVideoSha256", "sourceCutOriginalVideoPath",
            "sourceCutOriginalVideoSha256", "sourceCutReviewFrameEvidenceSha256",
            "reviewedExerciseName",
            "exerciseMotionContractSha256",
        )
    )
    if not all(
        isinstance(clearance.get(key), str) and bool(clearance[key])
        for key in required_fields
    ):
        return False
    if expected_status == "cleared":
        exercise_name = str(
            expected_exercise_name if expected_exercise_name is not None
            else selected.get("exerciseName") or ""
        ).strip()
        if (
            not exercise_name
            or str(clearance.get("reviewedExerciseName") or "").strip().casefold()
            != exercise_name.casefold()
        ):
            return False
        try:
            if expected_exercise_name is None:
                ranking = selected.get("ranking") if isinstance(selected.get("ranking"), dict) else {}
                ranking_payload = ranking.get("payload") if isinstance(ranking.get("payload"), dict) else {}
                candidate = selected.get("candidate") if isinstance(selected.get("candidate"), dict) else {}
                contract = ranking_payload.get("exerciseMotionContract") or candidate.get("exerciseMotionContract")
                expected_contract = contract if isinstance(contract, dict) else None
            contract_hash = source_contract_clearance_sha256(expected_contract)
        except (TypeError, ValueError):
            return False
        if clearance.get("exerciseMotionContractSha256") != contract_hash:
            return False
    try:
        # The display clip may be trimmed; clearance belongs to the retained reconstruction input.
        original_source = selected.get("selectedInputSourceVideoPath")
        if original_source:
            original_path = Path(str(original_source))
            if not original_path.is_absolute() and selected_source_path is not None:
                original_path = selected_source_path.parent / original_path
            selected_source_path = original_path
        source_manifest_path = Path(clearance["sourceManifestPath"])
        selected_segment_path = Path(clearance["selectedSegmentPath"])
        hashes_current = (
            content_hash(source_manifest_path) == clearance["sourceManifestSha256"]
            and content_hash(selected_segment_path) == clearance["selectedSegmentSha256"]
            and (
                selected_source_path is None
                or content_hash(selected_source_path) == clearance["selectedSegmentSha256"]
            )
        )
        if expected_status == "not_required":
            return hashes_current
        frame_evidence = clearance.get("sourceCutReviewFrameEvidence")
        if not isinstance(frame_evidence, dict):
            return False
        frame_evidence_sha256 = hashlib.sha256(json.dumps(
            frame_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        profile = frame_evidence.get("extractionProfile")
        if not isinstance(profile, dict):
            return False
        profile_sha256 = hashlib.sha256(json.dumps(
            profile, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        images = frame_evidence.get("images")
        if (
            frame_evidence_sha256 != clearance.get("sourceCutReviewFrameEvidenceSha256")
            or str(frame_evidence.get("candidateId") or "")
            != str(clearance.get("authorizedCandidateId") or "")
            or frame_evidence.get("extractionProfileSha256") != profile_sha256
            or profile.get("sourceSelectionPolicyVersion") != source_version
            or not isinstance(images, list)
            or not images
            or any(
                not isinstance(image, dict)
                or not isinstance(image.get("path"), str)
                or not isinstance(image.get("sha256"), str)
                or content_hash(Path(image["path"])) != image["sha256"]
                for image in images
            )
        ):
            return False
        return (
            hashes_current
            and content_hash(Path(clearance["sourceCutReviewVideoPath"]))
            == clearance["sourceCutReviewVideoSha256"]
            and content_hash(Path(clearance["sourceCutOriginalVideoPath"]))
            == clearance["sourceCutOriginalVideoSha256"]
        )
    except OSError:
        return False


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
    source_groups: dict[str, list[Path]] = {}
    for path in (
        *directory.glob("*_selected_input.mp4"),
        *directory.glob("*_selected_input.webm"),
    ):
        # The webm is a re-containered copy of the mp4 input, not a second
        # source: one retained stem is one source regardless of containers.
        source_groups.setdefault(path.stem, []).append(path)
    if len(source_groups) != 1:
        return None
    sources = [
        min(next(iter(source_groups.values())), key=lambda path: path.suffix != ".mp4")
    ]
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
    if not source_selection_clearance_is_current(
        manifest,
        source_policy_version=(
            policies.get("source") if isinstance(policies.get("source"), int) else None
        ),
        selected_source_path=sources[0],
        expected_exercise_name=str(selected.get("exerciseName") or ""),
        expected_contract=active_contract,
    ):
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
                "artifactClass", "artifactState", "sourceSelectionClearance",
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


def required_evidence_gaps(metrics: dict[str, Any]) -> list[str]:
    """One missing-evidence policy for review scheduling and final acceptance."""
    missing: list[str] = []
    required_metric_failures = {
        "materialized_motion_metrics_unavailable", "materialized_preview_readability_metrics_unavailable",
        "materialized_kinematic_metrics_unavailable", "materialized_hand_lock_arm_metrics_unavailable",
        "materialized_paired_hands_metrics_unavailable",
    }
    if metrics.get("loopContinuityRequired"):
        required_metric_failures.add("materialized_loop_bridge_metrics_unavailable")
    missing.extend(sorted(set(metrics.get("skippedReasons") or []) & required_metric_failures))
    if not metrics:
        missing.append("materialized_output_evidence_missing")
    for name, value in metrics.items():
        if not isinstance(value, dict) or value.get("required") is not True:
            continue
        if value.get("available") is False or value.get("evaluated") is False or value.get("passed") is None:
            missing.append(f"required_evidence_unavailable:{name}")
    if metrics.get("skippedReasons") and "materialized_output_skeleton_missing" in metrics["skippedReasons"]:
        missing.append("materialized_output_skeleton_missing")
    return list(dict.fromkeys(missing))


def decide_acceptance(
    metrics: dict[str, Any], review: dict[str, Any], *,
    deterministic_rejections: list[str], review_rejections: list[str],
    require_visual_review: bool = True,
) -> AcceptanceDecision:
    """Independent failures survive review uncertainty; missing evidence cannot approve."""
    # Old cached balance warnings no longer constitute an acceptance failure.
    deterministic_rejections = [reason for reason in deterministic_rejections
                                if reason != "physical_balance_requires_review"]
    missing = required_evidence_gaps(metrics)
    concrete = [reason for reason in deterministic_rejections
                if not any(word in reason for word in ("unavailable", "missing", "validator_failed"))]
    if concrete:
        if all(reason.startswith(("materialized_exported_preview_", "materialized_preview_video_", "final_render_"))
               for reason in concrete):
            return AcceptanceDecision("invalid", "rendering", tuple(dict.fromkeys(deterministic_rejections)), False)
        source_failure = any("source" in r and any(w in r for w in ("incomplete", "identity", "boundary", "variant")) for r in concrete)
        return AcceptanceDecision("invalid", "source" if source_failure else "motion_output",
                                  tuple(dict.fromkeys(deterministic_rejections)), not source_failure)
    if missing or deterministic_rejections:
        return AcceptanceDecision("needs_manual_review", "evidence", tuple(dict.fromkeys([*missing, *deterministic_rejections])))
    if review.get("advisoryOnly") is True:
        # A bare observer result cannot stand in for required render evidence.
        if require_visual_review:
            return AcceptanceDecision("needs_manual_review", "rendering", ("required_render_evidence_missing",))
        return AcceptanceDecision("valid", None, ())
    if review.get("failureOwner") == "review" or review.get("reviewStatus") == "needs_manual_review":
        return AcceptanceDecision("needs_manual_review", review.get("failureOwner") or "review", tuple(review_rejections or ["review_unresolved"]))
    if review_rejections:
        owner = review.get("failureOwner") or "motion_output"
        return AcceptanceDecision("invalid", owner, tuple(review_rejections), owner == "motion_output")
    if require_visual_review and review.get("passed") is not True:
        return AcceptanceDecision("needs_manual_review", "review", ("visual_review_not_approved",))
    return AcceptanceDecision("valid", None, ())
