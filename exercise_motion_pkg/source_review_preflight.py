"""Run source-only semantic checks before committing GPU time to reconstruction."""
from pathlib import Path
from typing import Any, Callable

from exercise_motion_pkg import bake_and_rank as bake


class SourceReviewIncomplete(RuntimeError):
    """The bounded source review did not establish a usable verdict."""


def review_prepared_source(candidate: bake.RankedCandidate, *, request: bake.BakeAndRankRequest,
                           selected_video: Path, contract: dict[str, Any] | None,
                           caption_images: Callable[..., str]) -> None:
    if not request.two_scale_source_validation:
        return
    workspace = request.workspace / candidate.workspace_slug
    duration = bake.read_basic_video_metadata(selected_video).duration_seconds
    item = bake.ReviewItem(candidate.exercise_index, candidate.candidate_rank, -1,
        candidate.exercise_name, candidate.title, workspace, workspace / "preview.html",
        workspace / "wear/skeleton.json", workspace / "review.webm", duration, 0.0, duration,
        candidate.candidate, source_review_video_path=selected_video)
    output = workspace / "review" / "source-preflight"
    sheets = bake.final_output_source_contact_sheets(item, output_dir=output / "source")
    phase = bake.pre_wham_exact_source_phase_reference_metrics(item) or {}
    endpoints = phase.get("sourcePoseEndpointFeatures")
    deterministic = {
        "sourceVideoFullRepetitionPhaseCompletenessMetrics": phase,
        "sourcePoseEndpointContractValidation": bake.validate_source_pose_endpoints_against_contract(
            endpoints, contract, phase_metrics=phase),
        "sourceTargetMotionObservabilityMetrics": phase.get("targetMotionObservabilityMetrics"),
    }
    for attempt in range(2):
        validation = bake.validate_two_scale_source_with_caption_images(item,
            uniform_sheet_paths=sheets, output_dir=output, caption_images=caption_images,
            exercise_motion_contract=contract, source_pose_endpoint_features=endpoints,
            source_phase_metrics=phase)
        if validation.get("passed") is True:
            return
        reasons = validation.get("rejectionReasons", [])
        # Preserve the existing source-evidence exceptions. These do not approve
        # the reconstructed output; its independent checks still run later.
        common = dict(item=item, rejection_reasons=reasons, deterministic_metrics=deterministic)
        if (bake.two_scale_small_motion_failure_is_independent_outlier(validation=validation, **common)
            or bake.two_scale_completeness_failure_is_independent_outlier(validation=validation, **common)
            or bake.two_scale_identity_failure_is_independent_outlier(**common)
            or bake.two_scale_topology_failure_is_independent_outlier(validation=validation, **common)):
            return
        if bake.two_scale_source_validation_needs_repair(validation):
            repair = bake.repair_two_scale_source_disagreement(validation, item=item,
                caption_images=caption_images, output_dir=output)
            if repair.get("resolved") is True:
                bake.cache_repaired_source_review(validation, repair)
                return
            if repair.get("valid") is True:
                # A complete repair can resolve the disagreement negatively as
                # well as positively. A categorical refutation of any required
                # source claim is sufficient to reject this window; repeating
                # the full multi-gate review cannot make that window usable.
                refuted_reasons = []
                origin_groups = repair.get("evidenceOriginGroups")
                for claim in repair.get("evidenceClaims") or []:
                    if not isinstance(claim, dict) or claim.get("valid") is not True:
                        continue
                    if str(claim.get("result") or "").casefold() != "refuted":
                        continue
                    claim_id = str(claim.get("id") or "")
                    reasons = origin_groups.get(claim_id) if isinstance(origin_groups, dict) else None
                    if isinstance(reasons, list):
                        refuted_reasons.extend(str(reason) for reason in reasons if str(reason))
                refuted_reasons = bake.dedupe_text(refuted_reasons)
                if refuted_reasons:
                    raise bake.SourceCandidateRejected(
                        "Source disagreement review confirmed rejection: "
                        + ", ".join(refuted_reasons),
                        reason_tags=refuted_reasons,
                        evidence={"validation": validation, "repair": repair},
                    )
        incomplete = validation.get("reviewStatus") == "incomplete" or any(
            reason in {"two_scale_source_frame_generation_failed", "two_scale_source_frames_missing"}
            for reason in reasons)
        if not incomplete:
            raise bake.SourceCandidateRejected("Source semantic review rejected before reconstruction: " + ", ".join(reasons),
                reason_tags=reasons, evidence=validation)
    raise SourceReviewIncomplete("Source evidence incomplete after two reviews: " + ", ".join(reasons))
