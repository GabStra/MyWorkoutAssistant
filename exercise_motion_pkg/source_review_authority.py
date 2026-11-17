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
    """Resume unresolved cuts and legacy model judgments; preserve resolved decisions."""
    ranking = payload.get("sourceCutRanking") or {}
    details = ranking.get("payload") or {}
    if payload.get("selectedSpan") is None and (
        details.get("sourceReviewStatus") == "needs_review"
        or SOURCE_REVIEW_REQUIRED in ranking.get("reasons", [])
    ):
        return True
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


def _is_sha256_identity(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text.casefold())


def _semantic_source_review_value(value: Any) -> Any:
    """Remove relocatable bookkeeping while preserving decision evidence."""
    if isinstance(value, dict):
        return {
            str(key): _semantic_source_review_value(nested)
            for key, nested in value.items()
            if str(key).casefold() not in {"updatedat", "createdat", "timestamp", "mtime"}
            and "path" not in str(key).casefold()
            and "checkpoint" not in str(key).casefold()
        }
    if isinstance(value, list):
        return [_semantic_source_review_value(nested) for nested in value]
    return value


def candidate_source_review_replay_identity(workspace: Path) -> str | None:
    """Hash the expected inputs for an unresolved legacy review, not its answer."""
    try:
        payload = json.loads((workspace / "segment_detection" / "segment_selection.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not rejection_needs_authority_replay(payload):
        return None

    def digest_for(names: tuple[str, ...], path_names: tuple[str, ...]) -> str | None:
        import hashlib

        for name in names:
            value = payload.get(name)
            if _is_sha256_identity(value):
                return str(value).casefold()
        for name in path_names:
            path_text = payload.get(name)
            if not isinstance(path_text, str) or not path_text:
                continue
            path = Path(path_text).expanduser()
            if not path.is_file():
                continue
            digest = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
            except OSError:
                continue
            return digest.hexdigest()
        return None

    contract = payload.get("exerciseMotionContract")
    if not isinstance(contract, dict):
        ranking = payload.get("sourceCutRanking")
        details = ranking.get("payload") if isinstance(ranking, dict) else None
        contract = details.get("exerciseMotionContract") if isinstance(details, dict) else None
    contract_identity = None
    if isinstance(contract, dict):
        try:
            from exercise_motion_pkg.bake_and_rank import exercise_motion_contract_prompt_sha256
            contract_identity = {
                "policyVersion": contract.get("contractPolicyVersion"),
                "promptSha256": exercise_motion_contract_prompt_sha256(contract),
            }
        except (ImportError, TypeError, ValueError):
            contract_identity = {
                "policyVersion": contract.get("contractPolicyVersion"),
                "contract": _semantic_source_review_value(contract),
            }

    # These fields define the review request. Ranking responses, rejection prose,
    # citations, and timestamps are outputs and cannot create a new retry turn.
    identity = {
        "sourceReviewAuthorityPolicyVersion": SOURCE_REVIEW_AUTHORITY_VERSION,
        "sourceSelectionPolicyVersion": payload.get("sourceSelectionPolicyVersion"),
        "exerciseName": str(payload.get("exerciseName") or "").strip(),
        "sourceVideoSha256": digest_for(
            ("sourceVideoSha256", "sourceFileSha256"), ("sourceVideoPath",),
        ),
        "detectionVideoSha256": digest_for(
            ("detectionSourceVideoSha256", "detectionVideoSha256"), ("detectionSourceVideoPath",),
        ),
        "selectedSegmentSha256": digest_for(
            ("selectedSegmentSha256",), ("selectedSegmentPath",),
        ),
        "requestedWindow": _semantic_source_review_value({
            key: payload.get(key) for key in (
                "candidateSourceWindow", "sourceChunkHint", "sourceDetectionSpan",
                "selectedSpanInOriginalSource",
            ) if key in payload
        }),
        "chunkEstimate": _semantic_source_review_value(payload.get("chunkEstimate")),
        "segmentSettings": _semantic_source_review_value(payload.get("segmentSettings")),
        "exerciseMotionContract": contract_identity,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    import hashlib
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_review_evidence_reopens_attempt(
    candidate_key: str,
    current_validated_identities: dict[str, str] | None,
    acknowledged_identities: dict[str, str] | None,
) -> bool:
    """Allow one bounded retry only for a newly validated source-review decision.

    The current identity must come from the canonical source-review cache
    validator, not from a free-standing JSON ``passed`` field. A missing prior
    identity is the explicit legacy migration case: the old attempt predates
    evidence acknowledgement, so one current validated decision may resume it.
    """
    key = str(candidate_key or "")
    current = (current_validated_identities or {}).get(key)
    if not key or not _is_sha256_identity(current):
        return False
    acknowledged = (acknowledged_identities or {}).get(key)
    if key not in (acknowledged_identities or {}):
        return True
    return _is_sha256_identity(acknowledged) and str(current).casefold() != str(acknowledged).casefold()


def source_review_input_identity(inputs: dict[str, Any] | None) -> str | None:
    """Hash a complete, current source-review request before spending its turn.

    This is an admission identity, not a verdict. Its caller must obtain the
    contract/model/source identities from their normal validated owners.
    Response prose, citations, paths, and timestamps are deliberately absent.
    """
    return _source_review_input_identity(inputs, require_visual_spec=True)


def source_review_input_identity_before_visual_spec(inputs: dict[str, Any] | None) -> str | None:
    """Rebuild the old semantic fingerprint to verify one pre-spec reservation.

    This is only for matching a persisted hash from the prior request schema;
    it cannot admit a request by itself.
    """
    return _source_review_input_identity(inputs, require_visual_spec=False)


def _source_review_input_identity(
    inputs: dict[str, Any] | None,
    *,
    require_visual_spec: bool,
) -> str | None:
    if not isinstance(inputs, dict):
        return None
    required_sha256 = (
        "sourceVideoSha256", "currentContractSha256", "modelIdentitySha256",
        "sourceReferenceReviewContextSha256",
    )
    if require_visual_spec:
        required_sha256 += ("sourceReferenceVisualReviewSpecSha256",)
    if any(not _is_sha256_identity(inputs.get(field)) for field in required_sha256):
        return None
    if not isinstance(inputs.get("requestedWindow"), dict):
        return None
    if not isinstance(inputs.get("modelIdentity"), dict) or not inputs["modelIdentity"]:
        return None
    if not isinstance(inputs.get("sourceReferenceReviewContext"), dict):
        return None
    context = inputs["sourceReferenceReviewContext"]
    if (
        context.get("schemaVersion") != 1
        or context.get("approvalAuthority") != "explicit_user_approval"
        or context.get("allowedDifference") != "external_load_not_shown"
        or context.get("sourceExerciseId") == context.get("targetExerciseId")
        or not _is_sha256_identity(context.get("approvalSha256"))
        or not _is_sha256_identity(context.get("mappingSha256"))
        or not _is_sha256_identity(context.get("targetContractSha256"))
    ):
        return None
    if not isinstance(inputs.get("contractPolicyVersion"), int):
        return None
    if not isinstance(inputs.get("sourceSelectionPolicyVersion"), int):
        return None
    if not isinstance(inputs.get("sourceReviewPolicyVersion"), int):
        return None
    if require_visual_spec:
        if not isinstance(inputs.get("sourceReferenceVisualReviewSpecPolicyVersion"), int):
            return None
        try:
            from exercise_motion_pkg.source_evidence import SOURCE_REFERENCE_VISUAL_REVIEW_SPEC_POLICY_VERSION
        except ImportError:
            return None
        if inputs["sourceReferenceVisualReviewSpecPolicyVersion"] != SOURCE_REFERENCE_VISUAL_REVIEW_SPEC_POLICY_VERSION:
            return None
    if inputs.get("targetExerciseId") != context.get("targetExerciseId"):
        return None
    if context.get("targetContractPolicyVersion") != inputs.get("contractPolicyVersion"):
        return None
    if inputs.get("currentContractSha256", "").casefold() != context.get("targetContractSha256", "").casefold():
        return None
    context_canonical = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    model_canonical = json.dumps(
        _semantic_source_review_value(inputs["modelIdentity"]),
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
    ).encode("utf-8")
    import hashlib
    if (
        hashlib.sha256(context_canonical).hexdigest() != inputs["sourceReferenceReviewContextSha256"].casefold()
        or hashlib.sha256(model_canonical).hexdigest() != inputs["modelIdentitySha256"].casefold()
    ):
        return None
    excluded_fields = {"diagnostic", "response", "reviewText", "citations", "paths", "timestamps"}
    if not require_visual_spec:
        excluded_fields.update({
            "sourceReferenceVisualReviewSpecPolicyVersion",
            "sourceReferenceVisualReviewSpecSha256",
        })
    identity = {
        key: _semantic_source_review_value(value)
        for key, value in inputs.items()
        if key not in excluded_fields
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_review_input_reopens_attempt(
    candidate_key: str,
    current_input_identities: dict[str, str] | None,
    input_reservations: dict[str, str] | None,
    *,
    eligible_legacy_keys: set[str] | None = None,
    allow_visual_spec_upgrade_keys: set[str] | None = None,
    input_reservation_history: dict[str, list[str]] | None = None,
) -> bool:
    """Permit one legacy migration or one explicit visual-spec upgrade."""
    key = str(candidate_key or "")
    if not key or key not in (eligible_legacy_keys or set()):
        return False
    current = (current_input_identities or {}).get(key)
    if not _is_sha256_identity(current):
        return False
    history = (input_reservation_history or {}).get(key, [])
    if any(isinstance(value, str) and value.casefold() == current.casefold() for value in history):
        return False
    reserved = (input_reservations or {}).get(key)
    if reserved is None:
        return True
    if key not in (allow_visual_spec_upgrade_keys or set()):
        return False
    return _is_sha256_identity(reserved) and reserved.casefold() != current.casefold()


def source_review_attempt_reopen_reason(
    candidate_key: str,
    candidate_workspace: Path | None,
    current_validated_identities: dict[str, str] | None,
    acknowledged_identities: dict[str, str] | None,
    legacy_replay_reservations: dict[str, str] | None,
    source_review_input_reservations: dict[str, str] | None = None,
) -> str | None:
    """Return the one allowed evidence transition, or None when still consumed."""
    key = str(candidate_key or "")
    acknowledged = acknowledged_identities or {}
    if key in acknowledged:
        return (
            "new_validated_source_review"
            if source_review_evidence_reopens_attempt(key, current_validated_identities, acknowledged)
            else None
        )
    if source_review_evidence_reopens_attempt(key, current_validated_identities, acknowledged):
        return "new_validated_source_review"
    # Once a current-input migration was reserved before review, stale legacy
    # response metadata cannot reopen the same source key a second time.
    if key in (source_review_input_reservations or {}):
        return None
    current = candidate_source_review_replay_identity(candidate_workspace) if candidate_workspace else None
    if current is None:
        return None
    reserved = (legacy_replay_reservations or {}).get(key)
    if key not in (legacy_replay_reservations or {}) or not _is_sha256_identity(reserved):
        return "legacy_source_review_migration"
    if current.casefold() != str(reserved).casefold():
        return "changed_legacy_source_review_decision"
    return None


def source_review_evidence_blocks_attempt(
    candidate_key: str,
    current_validated_identities: dict[str, str] | None,
    acknowledged_identities: dict[str, str] | None,
    *,
    candidate_workspace: Path | None = None,
    legacy_replay_reservations: dict[str, str] | None = None,
) -> bool:
    """Block a consumed candidate unless a different validated decision arrived."""
    key = str(candidate_key or "")
    acknowledged = acknowledged_identities or {}
    reservations = legacy_replay_reservations or {}
    return (key in acknowledged or key in reservations) and source_review_attempt_reopen_reason(
        key, candidate_workspace, current_validated_identities, acknowledged, reservations,
    ) is None


def retained_source_attempt_keys(
    attempted_keys: list[str],
    candidate_workspaces: dict[str, Path],
    *,
    current_validated_review_identities: dict[str, str] | None = None,
    acknowledged_review_identities: dict[str, str] | None = None,
    legacy_replay_reservations: dict[str, str] | None = None,
    current_source_review_input_identities: dict[str, str] | None = None,
    source_review_input_reservations: dict[str, str] | None = None,
    source_review_input_reservation_history: dict[str, list[str]] | None = None,
    eligible_legacy_input_keys: set[str] | None = None,
    allow_visual_spec_upgrade_keys: set[str] | None = None,
) -> list[str]:
    """Exclude completed attempts unless newer authoritative evidence reopens one.

    Historical keys are never deleted from the persisted cursor. This return
    value only controls which candidate is eligible for the current bounded
    source turn; attempt counters and the original key list remain authoritative.
    """
    retained: list[str] = []
    for key in attempted_keys:
        workspace = candidate_workspaces.get(key)
        if source_review_input_reopens_attempt(
            key, current_source_review_input_identities, source_review_input_reservations,
            eligible_legacy_keys=eligible_legacy_input_keys,
            allow_visual_spec_upgrade_keys=allow_visual_spec_upgrade_keys,
            input_reservation_history=source_review_input_reservation_history,
        ):
            continue
        if source_review_attempt_reopen_reason(
            key, workspace, current_validated_review_identities,
            acknowledged_review_identities, legacy_replay_reservations,
            source_review_input_reservations,
        ) is not None:
            continue
        retained.append(key)
    return retained


def source_authority_replay_plan(library_workspace: Path) -> list[dict[str, str]]:
    """Read-only inventory; the running generator and its selected files are untouched."""
    return [
        {"exercise": path.parents[3].name, "candidateWorkspace": str(path.parent.parent),
         "resumeStage": "source_review", "reason": "outdated_source_review_policy"}
        for path in sorted(library_workspace.glob("*/bake/*/segment_detection/segment_selection.json"))
        if candidate_needs_authority_replay(path.parent.parent)
        and not any((path.parents[3] / "selected").glob("*_wear_skeleton.json"))
    ]
def exact_window_cycle_adjudication_clearance(
    receipt: dict[str, Any] | None,
    *,
    checkpoint: Path,
    current_cache_key: str,
    expected_binding: dict[str, Any],
    current_scorecard: dict[str, Any],
    exercise_motion_contract: dict[str, Any],
    equipment_requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify exact-window cycle review from the current content-checked cache.

    The caller supplies the current cache key and source/contract/phase binding
    computed from the selected source. The receipt alone is never authority.
    This evidence supplements the existing source-selection gates; it does not
    turn the source scorecard positive or clear support, phase, or identity gates.
    """
    import hashlib
    import math

    from exercise_motion_pkg.source_evidence import (
        POLICY_VERSION as SOURCE_EVIDENCE_POLICY_VERSION,
        aggregate_evidence,
        permits_cyclic_phase_order,
        source_requirements,
    )
    from exercise_motion_pkg.stage_cache import load_stage
    from exercise_motion_pkg.bake_and_rank import (
        SOURCE_CUT_CLASSIFIER_MIN_CONFIDENCE_WITH_CONTRACT,
        SOURCE_CUT_SCORECARD_COMPLETENESS_ONLY_REJECT_REASONS,
    )

    def reject(reason: str) -> dict[str, Any]:
        return {"passed": False, "reason": reason}

    if not isinstance(receipt, dict) or not isinstance(expected_binding, dict):
        return reject("exact_cycle_adjudication_receipt_missing")
    binding = receipt.get("binding")
    if not isinstance(binding, dict):
        return reject("exact_cycle_adjudication_binding_missing")
    binding_fields = (
        "candidateId", "sourceVideoSha256", "sourceIntervalSeconds",
        "candidateWindowSourceSeconds",
        "contractIdentitySha256", "contractPolicyVersion",
        "exactPhaseReceiptSha256", "exactPhasePolicyVersion", "exactPhasePassed",
        "sourceEvidencePolicyVersion", "sourceReviewCacheKey",
    )
    if any(binding.get(key) != expected_binding.get(key) for key in binding_fields):
        return reject("exact_cycle_adjudication_current_binding_mismatch")
    if (
        not str(binding.get("candidateId") or "").strip()
        or not _is_sha256_identity(binding.get("sourceVideoSha256"))
        or not _is_sha256_identity(binding.get("contractIdentitySha256"))
        or not _is_sha256_identity(binding.get("exactPhaseReceiptSha256"))
        or not _is_sha256_identity(binding.get("sourceReviewCacheKey"))
        or binding.get("sourceReviewCacheKey") != current_cache_key
        or type(binding.get("contractPolicyVersion")) is not int
        or binding.get("contractPolicyVersion") != exercise_motion_contract.get("contractPolicyVersion")
        or type(binding.get("exactPhasePolicyVersion")) is not int
        or binding.get("exactPhasePolicyVersion") <= 0
        or binding.get("exactPhasePassed") is not True
        or binding.get("sourceEvidencePolicyVersion") != SOURCE_EVIDENCE_POLICY_VERSION
    ):
        return reject("exact_cycle_adjudication_current_identity_invalid")
    if not isinstance(current_scorecard, dict):
        return reject("exact_cycle_adjudication_scorecard_missing")
    scorecard_reasons = {
        str(reason) for reason in current_scorecard.get("rejectionReasons") or []
    }
    cycle_boundary_reasons = set(SOURCE_CUT_SCORECARD_COMPLETENESS_ONLY_REJECT_REASONS) | {
        "source_cut_contract_phase_timing_unresolved",
        "source_cut_contract_phase_sequence_mismatch",
    }
    confidence = current_scorecard.get("confidence")
    scorecard_passed = current_scorecard.get("passed")
    if (
        current_scorecard.get("id") != binding.get("candidateId")
        or str(current_scorecard.get("identityMatch") or "").casefold() != "match"
        or type(confidence) not in (int, float)
        or not math.isfinite(confidence)
        or confidence < SOURCE_CUT_CLASSIFIER_MIN_CONFIDENCE_WITH_CONTRACT
        or scorecard_passed is True and bool(scorecard_reasons)
        or scorecard_passed is False and (not scorecard_reasons or not scorecard_reasons <= cycle_boundary_reasons)
        or scorecard_passed is False and not scorecard_reasons.intersection({
            "source_cut_contract_phase_timing_unresolved",
            "source_cut_contract_phase_sequence_mismatch",
        })
        or type(scorecard_passed) is not bool
    ):
        return reject("exact_cycle_adjudication_scorecard_hard_rejection")
    interval = binding.get("sourceIntervalSeconds")
    if (
        not isinstance(interval, list) or len(interval) != 2
        or any(type(value) not in (int, float) or not math.isfinite(value) for value in interval)
        or interval[0] < 0 or interval[1] <= interval[0]
    ):
        return reject("exact_cycle_adjudication_interval_invalid")
    expected_stage_digest = receipt.get("stagePayloadSha256")
    if not _is_sha256_identity(expected_stage_digest):
        return reject("exact_cycle_adjudication_stage_digest_missing")
    stage = load_stage(checkpoint, current_cache_key)
    if not isinstance(stage, dict):
        return reject("exact_cycle_adjudication_current_stage_missing_or_stale")
    encoded_stage = json.dumps(stage, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    if hashlib.sha256(encoded_stage.encode("utf-8")).hexdigest() != expected_stage_digest:
        return reject("exact_cycle_adjudication_stage_digest_mismatch")
    expected_stage_binding = {
        key: value for key, value in expected_binding.items()
        if key != "sourceReviewCacheKey"
    }
    if stage.get("sourceAuthorityBinding") != expected_stage_binding:
        return reject("exact_cycle_adjudication_stage_authority_binding_mismatch")
    cache_ref = stage.get("sourceReviewCache")
    if not isinstance(cache_ref, dict) or cache_ref.get("key") != current_cache_key:
        return reject("exact_cycle_adjudication_stage_key_mismatch")
    if (
        stage.get("passed") is not True or stage.get("reviewStatus") != "passed"
        or stage.get("missingEvidenceReasons") or stage.get("error")
        or stage.get("sourceEvidencePolicyVersion") != SOURCE_EVIDENCE_POLICY_VERSION
        or stage.get("sourceIntervalSeconds") != interval
        or stage.get("exerciseMotionContract") != exercise_motion_contract
        or not permits_cyclic_phase_order(exercise_motion_contract)
    ):
        return reject("exact_cycle_adjudication_stage_not_current_complete_pass")

    gates = stage.get("gates")
    structured = gates.get("structuredEvidence") if isinstance(gates, dict) else None
    endpoints = gates.get("deterministicPoseEndpoints") if isinstance(gates, dict) else None
    action_pose = gates.get("actionPoseEvidence") if isinstance(gates, dict) else None
    if (
        not isinstance(structured, dict) or structured.get("passed") is not True
        or not isinstance(endpoints, dict) or endpoints.get("passed") is not True
        or endpoints.get("returnCycleCorroborated") is not True
        or not isinstance(endpoints.get("returnEndpointConsistency"), dict)
        or endpoints["returnEndpointConsistency"].get("passed") is not True
        or not isinstance(action_pose, dict) or action_pose.get("passed") is not True
    ):
        return reject("exact_cycle_adjudication_required_gates_not_passed")
    cycle = stage.get("sourceCycleEvidenceChoices")
    if not isinstance(cycle, dict) or cycle.get("choiceId") != "verified_return_cycle":
        return reject("exact_cycle_adjudication_cycle_choice_missing")
    sequence = cycle.get("sequence")
    if sequence not in (["low", "high", "low"], ["high", "low", "high"]):
        return reject("exact_cycle_adjudication_cycle_sequence_invalid")
    role_ids = cycle.get("roleFrameIds")
    role_times = cycle.get("roleTimes")
    if (
        not isinstance(role_ids, dict) or set(role_ids) != {"start", "excursion", "return"}
        or any(not isinstance(value, str) or not value for value in role_ids.values())
        or len(set(role_ids.values())) != 3
        or not isinstance(role_times, dict) or set(role_times) != {"start", "excursion", "return"}
    ):
        return reject("exact_cycle_adjudication_cycle_roles_invalid")
    times = [role_times[key] for key in ("start", "excursion", "return")]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in times) or not times[0] < times[1] < times[2]:
        return reject("exact_cycle_adjudication_cycle_times_invalid")
    spans = cycle.get("spanChoices")
    if (
        not isinstance(spans, list) or len(spans) != 2
        or [row.get("frameIds") if isinstance(row, dict) else None for row in spans]
        != [[role_ids["start"], role_ids["excursion"]], [role_ids["excursion"], role_ids["return"]]]
    ):
        return reject("exact_cycle_adjudication_cycle_spans_invalid")
    frames = stage.get("frameInventory")
    if not isinstance(frames, list):
        return reject("exact_cycle_adjudication_frame_inventory_missing")
    response = structured.get("response")
    try:
        requirements = source_requirements(exercise_motion_contract, equipment_requirements)
        validated = aggregate_evidence(
            response,
            requirements,
            frames,
            allow_cyclic_phase_order=True,
            cycle_choices=cycle,
        )
    except (KeyError, TypeError, ValueError):
        return reject("exact_cycle_adjudication_full_requirements_invalid")
    if not validated.get("passed"):
        return reject("exact_cycle_adjudication_full_requirements_not_supported")
    return {
        "passed": True,
        "authority": "exact_window_cycle_adjudication",
        "candidateId": binding["candidateId"],
        "sourceVideoSha256": binding["sourceVideoSha256"],
        "sourceIntervalSeconds": list(interval),
        "sourceReviewCacheKey": current_cache_key,
        "stagePayloadSha256": expected_stage_digest,
        "sourceEvidencePolicyVersion": SOURCE_EVIDENCE_POLICY_VERSION,
        "supportedRequirementIds": [row["id"] for row in requirements],
        "cycleChoice": cycle,
    }
