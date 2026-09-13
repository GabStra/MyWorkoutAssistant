from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from exercise_motion_pkg.bake_and_rank import (
    BakeAndRankRequest,
    LazyLlamaCppVisionSession,
    RankedCandidate,
    RawMotionRejected,
    IncompleteWhamTrackingError,
    require_current_source_contract,
    SourceCandidateRejected,
    ExerciseMotionContractRejected,
    SOURCE_SELECTION_POLICY_VERSION,
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
)
from exercise_motion_pkg.vlm_errors import critical_vlm_interaction_error
from exercise_motion_pkg.wham_runner import WhamTrackingPreflightRejected
from exercise_motion_pkg.source_outcomes import update_source_outcome_index
from exercise_motion_pkg.source_review_preflight import SourceReviewIncomplete, review_prepared_source
from exercise_motion_pkg.source_review_authority import retained_source_attempt_keys
from exercise_motion_pkg.storage import is_storage_failure, require_storage_reserve


STAGED_SOURCE_PORTFOLIO_MAX_SIZE = 3
STAGED_SOURCE_VALIDATION_MAX_WORKERS = 6
STAGED_GENERATION_CPU_WORKERS = 2


@dataclass(frozen=True)
class StagedWaveItem:
    exercise_id: str
    exercise_name: str
    request: BakeAndRankRequest


def generation_failure_status(error: Exception) -> str:
    if isinstance(error, IncompleteWhamTrackingError):
        return "rejected_incomplete_wham_tracking"
    if isinstance(error, RawMotionRejected):
        return "rejected_raw_wham_validation"
    if isinstance(error, WhamTrackingPreflightRejected):
        return "rejected_tracking_preflight"
    return "failed"


def wave_retry_disposition(state: dict[str, Any]) -> str:
    if state.get("status") == "completed":
        return "export_selected"
    if state.get("source", {}).get("failureReason") == "exercise_contract_invalid":
        return "repair_contract"
    if state.get("source", {}).get("failureReason") == "source_review_incomplete":
        return "retry_review"
    final = state.get("finalValidation", {})
    if final.get("status") == "no_selection":
        diagnostics = final.get("candidateDiagnostics", [])
        if any(item.get("status") == "needs_motion_processing" for item in diagnostics):
            return "retry_processing"
        if any(item.get("status") == "failed" for item in diagnostics):
            return "retry_infrastructure"
        if any(
            item.get("status") in {"needs_source_review", "needs_manual_review"} for item in diagnostics
        ):
            return "retry_review"
        return "next_source"
    attempts = state.get("wham", {}).get("attempts", [])
    if attempts and all(item.get("status") in {"rejected_raw_wham_validation", "rejected_tracking_preflight", "rejected_incomplete_wham_tracking"}
                        for item in attempts):
        return "next_source"
    if state.get("source", {}).get("failureReason") in {
        "no_source_passed_exact_window_validation", "source_turn_deferred",
    }:
        return "next_source"
    return "retry_infrastructure"


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


def final_processing_diagnostics(manifest: dict[str, Any]) -> dict[str, Any]:
    """Keep processing errors distinct from quality rejections in progress output."""
    candidates = []
    for result in manifest.get("candidateResults", []):
        status = result.get("status", "unknown")
        stage = result.get("failureStage") or {
            "rejected_raw_wham_validation": "raw_reconstruction_validation",
            "rejected_incomplete_wham_tracking": "raw_reconstruction_validation",
            "skipped_no_baked_clip": "baked_motion_validation",
            "failed": "processing_error",
            "ready_for_selection": "output_validation",
        }.get(status, status)
        candidates.append({
            "stage": stage,
            "status": status,
            "reasons": [failure.get("reason", "unknown") for failure in result.get("failures", [])],
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


def _candidate_key(candidate: RankedCandidate) -> str:
    return f"{candidate.exercise_id}:{candidate.workspace_slug}"


def source_attempt_log_context(candidate: RankedCandidate, number: int, total: int) -> str:
    """Identify the candidate window; the reviewer may choose a subinterval."""
    hint = candidate.source_chunk_hint
    window = (f"{hint.start_seconds:.2f}-{hint.end_seconds:.2f}s"
              if hint is not None else "automatic selection")
    return f"attempt {number}/{total} this turn | candidate window {window}"


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
            payload = json.loads((workspace / artifact_name).read_text(encoding="utf-8"))
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


def _stop_warm_wham_worker_before_vlm(items: list[StagedWaveItem]) -> dict[str, Any]:
    session_dirs = {
        item.request.wham_worker_session_dir.expanduser().resolve()
        for item in items
        if item.request.use_warm_wham_worker
        and item.request.wham_worker_session_dir is not None
    }
    if not session_dirs:
        return {"requested": False, "stopped": True}
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
                f"Warm WHAM worker did not release the GPU within 30 seconds: {session_dir}"
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
            if not isinstance(attempt, dict) or attempt.get("status") in {"prepared", "blocked_contract", "needs_source_review"}:
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
    authority = bake.pre_wham_source_interval_authority(
        candidate_workspace=workspace, exercise_motion_contract=contract)
    loops = bake.build_candidate_review_eligible_loops(bake.load_motion_json(cleaned), source_interval_authority=authority)
    support = bake.pre_wham_source_foot_support_evidence(workspace)
    from .body_support_observation import requires_body_support, observed_stationary_sole_contacts, observe_body_support
    if requires_body_support(contract) or observed_stationary_sole_contacts(support):
        observation = observe_body_support(workspace/'input/selected_segment.mp4', None,
                                           workspace/'segment_detection/body_support')
        if observation.get('status') != 'observed':
            return {'status': 'skipped', 'reason': 'source_contact_observation_unavailable'}
    artifacts = bake.bake_preview_loops_with_playwright(preview, loops, workspace, item.request.review_frames,
        rank_preview_variants=item.request.rank_preview_variants,
        adaptive_preview_settings=item.request.adaptive_preview_settings,
        max_adaptive_preview_settings=item.request.max_adaptive_preview_settings,
        caption_images=None, exercise_name=item.exercise_name, exercise_motion_contract=contract,
        source_foot_support_evidence=support)
    return {"status": "prepared", "artifactCount": len(artifacts),
            "startedAt": started_at, "finishedAt": _utc_now(),
            "elapsedSeconds": round(time.perf_counter() - started, 3)}


def run_staged_bake_wave(
    items: list[StagedWaveItem],
    *,
    workspace: Path,
    wave_id: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    # These workers only prepare CPU-rendered artifacts. Final VLM work remains
    # behind the WHAM-release boundary in the coordinator.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="motion-render-prefetch") as render_executor:
        return _run_staged_bake_wave(items, workspace=workspace, wave_id=wave_id,
            progress=progress, render_executor=render_executor)


def _run_staged_bake_wave(
    items: list[StagedWaveItem],
    *,
    workspace: Path,
    wave_id: str,
    progress: Callable[[str], None] | None = None,
    render_executor: ThreadPoolExecutor,
) -> dict[str, Any]:
    """Run one cache-first VLM -> WHAM -> VLM wave.

    Up to two candidates from different source videos are prepared per
    exercise. Unsuccessful items are reported for the normal deeper retry lane
    instead of stalling the wave.
    Re-running the same wave is resumable because source cuts, WHAM output, and
    selection manifests are all content-addressed or workspace-cached.
    """

    if not items:
        raise ValueError("A staged wave must contain at least one exercise.")
    # A staged wave deliberately releases the pose/VLM runtime before WHAM and
    # may start a different runtime for final review.  Capture the exact source
    # pose while the source-validation runtime is authoritative; otherwise the
    # final materialized-output gate has no source reference and can only fail
    # as an infrastructure error.  Keep this invariant in the staged API rather
    # than relying on every caller to remember the CLI flag.
    items = [
        replace(
            item,
            request=replace(item.request, pre_wham_source_validation=True),
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
        "sourceAttemptEvents": [],
        "acceleratorTransitions": [],
        "phaseTimings": {},
    }
    item_states: dict[str, dict[str, Any]] = {
        item.exercise_id: {
            "exerciseId": item.exercise_id,
            "exerciseName": item.exercise_name,
            "candidatesJson": str(item.request.candidates_json),
            "workspace": str(item.request.workspace),
            "status": "pending",
            "source": {"status": "pending", "attempts": []},
            "wham": {"status": "pending"},
            "finalValidation": {"status": "pending"},
        }
        for item in items
    }

    def announce(message: str) -> None:
        if progress is not None:
            progress(message)

    checkpoint_lock = threading.Lock()
    current_stage = "initializing"

    def checkpoint(stage: str, latest_exercise_name: str | None = None) -> None:
        nonlocal current_stage
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

    heartbeat_stop = threading.Event()

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
    prepared_contracts: dict[str, dict[str, Any] | None] = {}
    render_futures: dict[str, Any] = {}
    metrics["cpuRenderPrefetch"] = {}
    unavailable_source_ids: set[str] = set()
    source_session = LazyLlamaCppVisionSession(items[0].request)
    source_phase_started = time.perf_counter()
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
            with checkpoint_lock:
                item_states[item.exercise_id]["sourceActivity"] = {
                    "startedAt": _utc_now(),
                    "operation": "checking source candidates",
                }
            checkpoint("source_validation")
            attempts: list[dict[str, Any]] = []
            selected_sources: list[tuple[RankedCandidate, Path]] = []
            selected_source_identities: set[str] = set()
            requested_portfolio_size: int | None = None
            resolver = build_exercise_motion_contract_resolver(
                request=item.request,
                caption_images=source_session.caption_images,
                run_llama_exclusive=source_session.run_without_llama_overlap,
            )
            candidates = _prioritize_previously_prepared_sources(
                _wave_candidates_for_item(item),
                preferred_keys=previous_selected_candidate_keys.get(item.exercise_id, []),
            )
            resume_path = item.request.workspace / "source_turn_resume.json"
            prior_attempt_keys: list[str] = []
            try:
                resume = json.loads(resume_path.read_text(encoding="utf-8"))
                if resume.get("sourceSelectionPolicyVersion") == SOURCE_SELECTION_POLICY_VERSION:
                    prior_attempt_keys = [str(key) for key in resume.get("attemptedCandidateKeys", [])]
                    prior_attempt_keys = retained_source_attempt_keys(prior_attempt_keys, {
                        _candidate_key(candidate): item.request.workspace / candidate.workspace_slug
                        for candidate in candidates
                    })
                    candidates = _prioritize_previously_prepared_sources(
                        [candidate for candidate in candidates if _candidate_key(candidate) not in prior_attempt_keys],
                        preferred_keys=[str(resume.get("nextCandidateKey") or "")],
                    )
            except (OSError, ValueError):
                pass
            for candidate_number, candidate in enumerate(candidates, start=1):
                source_identity = _candidate_source_identity(candidate)
                if source_identity in selected_source_identities:
                    continue
                with checkpoint_lock:
                    # Failed/exhausted entries cannot help fill this wave.
                    # Still count queued and active entries, and always let an
                    # exercise finish its first attempt before yielding.
                    available_count = len(items) - len(unavailable_source_ids)
                    source_yield_threshold = max(1, (available_count + 1) // 2)
                    yield_source_turn = (
                        bool(attempts) and not selected_sources
                        and len(ready_source_ids) >= source_yield_threshold
                    )
                if yield_source_turn:
                    _write_json_atomic(resume_path, {
                        "sourceSelectionPolicyVersion": SOURCE_SELECTION_POLICY_VERSION,
                        "nextCandidateKey": _candidate_key(candidate),
                        "attemptedCandidateKeys": list(dict.fromkeys([
                            *prior_attempt_keys, *[attempt["candidateKey"] for attempt in attempts],
                        ])),
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
                if not bool(readiness.get("eligible")):
                    attempt["status"] = "rejected_first_attempt_readiness"
                    attempt["reasons"] = readiness.get("reasons", [])
                    continue
                source_gate = evaluate_source_candidate_gate(candidate, request=item.request)
                if not bool(source_gate.get("passed")):
                    attempt["status"] = "rejected_source_gate"
                    attempt["reasons"] = source_gate.get("reasons", [])
                    continue
                try:
                    contract = resolver(candidate) if resolver is not None else None
                    if resolver is not None:
                        require_current_source_contract(contract, candidate)
                    with checkpoint_lock:
                        item_states[item.exercise_id]["sourceActivity"] = {
                            "startedAt": _utc_now(),
                            "operation": "preparing and validating source video",
                            "videoId": candidate.video_id,
                        }
                    checkpoint("source_validation")
                    selected_video = prepare_candidate_input_video(
                        candidate,
                        request=item.request,
                        source_cut_caption_images=source_session.caption_images,
                        exercise_motion_contract_resolver=resolver,
                    )
                    review_prepared_source(candidate, request=item.request, selected_video=selected_video,
                        contract=contract, caption_images=source_session.caption_images)
                    # Contact semantics must be available before the CPU-only
                    # prefetch, otherwise it fits once without them and again
                    # after the final stage acquires its visual model.
                    from .body_support_observation import requires_body_support, observed_stationary_sole_contacts, observe_body_support
                    from .bake_and_rank import load_pre_wham_exact_source_phase_metrics
                    candidate_workspace = item.request.workspace / candidate.workspace_slug
                    phase_metrics = load_pre_wham_exact_source_phase_metrics(candidate_workspace) or {}
                    if requires_body_support(contract) or observed_stationary_sole_contacts(phase_metrics.get('sourceFootSupportEvidence')):
                        observe_body_support(selected_video, source_session.caption_images,
                                             candidate_workspace/'segment_detection/body_support')
                except Exception as exc:
                    if is_storage_failure(exc):
                        raise
                    if isinstance(exc, SourceReviewIncomplete):
                        attempt["status"] = "needs_source_review"
                        attempt["error"] = str(exc)
                        source_event(f"Source review: {item.exercise_name} | needs review: {exc}")
                        break
                    if isinstance(exc, ExerciseMotionContractRejected):
                        attempt["status"] = "blocked_contract"
                        attempt["error"] = str(exc)
                        source_event(f"Source review: {item.exercise_name} | blocked: {exc}")
                        break
                    vlm_error = critical_vlm_interaction_error(exc)
                    if isinstance(exc, SourceCandidateRejected):
                        attempt["status"] = (
                            "needs_source_review" if {"source_cut_review_required", "source_cut_boundary_review_required"}.intersection(exc.reason_tags)
                            else "rejected_source_validation"
                        )
                        attempt["reasonTags"] = list(exc.reason_tags)
                        attempt["error"] = f"{type(exc).__name__}: {exc}"
                    elif vlm_error is not None:
                        attempt["status"] = "rejected_vlm_timeout"
                        attempt["error"] = f"{type(vlm_error).__name__}: {vlm_error}"
                    else:
                        attempt["status"] = "source_processing_failed"
                        attempt["error"] = f"{type(exc).__name__}: {exc}"
                    event = (
                        f"Source attempt: {item.exercise_name} | video {candidate.video_id} | "
                        f"{source_attempt_log_context(candidate, candidate_number, len(candidates))} | "
                        f"{attempt['status']}: {attempt['error']}"
                    )
                    source_event(event)
                    continue
                finally:
                    with checkpoint_lock:
                        item_states[item.exercise_id].pop("sourceActivity", None)
                attempt["status"] = "prepared"
                prepared_contracts[_candidate_key(candidate)] = contract
                attempt["selectedVideoPath"] = str(selected_video)
                selected_sources.append((candidate, selected_video))
                with checkpoint_lock:
                    ready_source_ids.add(item.exercise_id)
                selected_source_identities.add(source_identity)
                if requested_portfolio_size is None:
                    first_pass_single_source = (
                        item.request.fallback_candidates <= 0
                        and item.request.max_final_output_rejections <= 0
                    )
                    requested_portfolio_size = (
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
                if item.request.max_reconstruction_candidate_attempts > 0:
                    requested_portfolio_size = min(requested_portfolio_size,
                                                   item.request.max_reconstruction_candidate_attempts)
                if len(selected_sources) >= requested_portfolio_size:
                    break
            if not item_states[item.exercise_id]["source"].get("deferred"):
                resume_path.unlink(missing_ok=True)
            for attempt in attempts:
                attempt.setdefault("requestedPortfolioSize", requested_portfolio_size)
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
                executor.submit(prepare_item_source, item): item for item in items
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
                    with checkpoint_lock:
                        unavailable_source_ids.add(submitted_item.exercise_id)
                    source_message = state["source"]["error"]
                    if isinstance(exc, ValueError) and str(exc) == (
                        "No fully identity-reviewed recommended YouTube candidate found."
                    ):
                        source_message = "No approved candidates in cached discovery results."
                    source_event(
                        f"Source review: {submitted_item.exercise_name} | unresolved: {source_message}"
                    )
                    checkpoint("source_validation", submitted_item.exercise_name)
                    continue
                state = item_states[item.exercise_id]
                state["source"]["attempts"] = attempts
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
                else:
                    state["source"]["status"] = "failed"
                    with checkpoint_lock:
                        unavailable_source_ids.add(item.exercise_id)
                    eligible_attempts = [
                        attempt
                        for attempt in attempts
                        if bool(
                            (attempt.get("firstAttemptReadiness") or {}).get("eligible")
                        )
                    ]
                    state["source"]["failureReason"] = (
                        "exercise_contract_invalid"
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
                    )
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
    finally:
        # WHAM owns the GPU in the next stage, so this must release the model
        # even when the configured llama.cpp server is normally kept alive.
        source_session.close(force_stop_server=True)
        metrics["sourceVisionSession"] = _session_timing_manifest(source_session)
        metrics["phaseTimings"]["sourceValidationSeconds"] = round(
            time.perf_counter() - source_phase_started,
            3,
        )

    metrics["acceleratorTransitions"].append({"stage": "wham", "at": _utc_now()})
    wham_phase_started = time.perf_counter()
    announce(f"Extracting motion for {len(prepared)} exercise(s).")
    checkpoint("wham_generation")

    def cached_source_only(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("A staged WHAM pass attempted an uncached source VLM request.")

    wham_ready: dict[str, tuple[StagedWaveItem, list[tuple[RankedCandidate, Path]]]] = {}

    generation_start_times: dict[str, float] = {}

    def generate_item_motion(
        exercise_id: str,
        item: StagedWaveItem,
        candidate: RankedCandidate,
        selected_video_path: Path,
    ) -> tuple[str, StagedWaveItem, Any, float]:
        wham_started = time.perf_counter()
        generation_start_times[_candidate_key(candidate)] = wham_started
        result = generate_candidate_motion(
            candidate,
            request=replace(item.request, wham_tracking_preflight=True),
            source_cut_caption_images=cached_source_only,
            prepared_video_path=selected_video_path,
        )
        return exercise_id, item, result, time.perf_counter() - wham_started

    prepared_candidates = [
        (exercise_id, item, candidate, selected_video_path)
        for exercise_id, (item, sources) in prepared.items()
        for candidate, selected_video_path in sources
    ]
    # GPU jobs remain serialized by the WHAM/global GPU locks. A second caller
    # overlaps video preparation and CPU postprocessing in a different workspace.
    wham_worker_count = min(STAGED_GENERATION_CPU_WORKERS, max(1, len(prepared_candidates)))
    metrics["generationCpuWorkers"] = wham_worker_count
    wham_completed_count = 0
    wham_attempts: dict[str, list[dict[str, Any]]] = {
        exercise_id: [] for exercise_id in prepared
    }
    with ThreadPoolExecutor(max_workers=wham_worker_count) as executor:
        future_items = {
            executor.submit(
                generate_item_motion,
                exercise_id,
                item,
                candidate,
                selected_video_path,
            ): (exercise_id, item, candidate, selected_video_path)
            for exercise_id, item, candidate, selected_video_path in prepared_candidates
        }
        for future in as_completed(future_items):
            exercise_id, item, candidate, selected_video_path = future_items[future]
            state = item_states[exercise_id]
            wham_started = generation_start_times.get(_candidate_key(candidate), time.perf_counter())
            try:
                _result_exercise_id, _result_item, result, generation_seconds = future.result()
                attempt = {
                    "status": "prepared",
                    "candidateKey": _candidate_key(candidate),
                    "selectedVideoPath": str(selected_video_path),
                    "elapsedSeconds": round(generation_seconds, 3),
                    "cacheStatus": result.wham_cache_status,
                    "resultsPath": str(result.wham_results_pkl) if result.wham_results_pkl else None,
                }
                wham_attempts[exercise_id].append(attempt)
                _ready_item, ready_sources = wham_ready.setdefault(exercise_id, (item, []))
                ready_sources.append((candidate, selected_video_path))
                render_futures[_candidate_key(candidate)] = render_executor.submit(
                    prepare_cpu_render_cache, item, candidate, result,
                    prepared_contracts.get(_candidate_key(candidate)))
            except Exception as exc:
                if is_storage_failure(exc):
                    raise
                failure_status = generation_failure_status(exc)
                attempt = {
                    "status": failure_status,
                    "candidateKey": _candidate_key(candidate),
                    "selectedVideoPath": str(selected_video_path),
                    "elapsedSeconds": round(time.perf_counter() - wham_started, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                if isinstance(exc, WhamTrackingPreflightRejected):
                    attempt["trackingPreflight"] = exc.report
                if isinstance(exc, RawMotionRejected):
                    attempt["rawWhamMotionGate"] = exc.gate
                    candidate_workspace = item.request.workspace / candidate.workspace_slug
                    attempt["artifactRetention"] = apply_artifact_retention_policy(
                        candidate_workspace,
                        {"candidateResults": [{"candidateWorkspace": str(candidate_workspace),
                                                "inputVideoPath": str(selected_video_path)}]},
                        mode=item.request.artifact_retention,
                    )
                wham_attempts[exercise_id].append(attempt)
            wham_completed_count += 1
            state["wham"] = {
                "status": generation_status(wham_attempts[exercise_id], len(prepared[exercise_id][1])),
                "attempts": wham_attempts[exercise_id],
            }
            checkpoint("wham_generation", item.exercise_name)
            announce(
                f"{'Extracted motion' if attempt['status'] == 'prepared' else 'Extraction failed'} for {item.exercise_name} "
                f"({wham_completed_count}/{len(prepared_candidates)}, {attempt['elapsedSeconds']:.1f}s)."
            )

    for exercise_id in prepared:
        state = item_states[exercise_id]
        if exercise_id in wham_ready:
            item, ready_sources = wham_ready[exercise_id]
            source_priority = {
                candidate.workspace_slug: index
                for index, (candidate, _path) in enumerate(prepared[exercise_id][1])
            }
            ready_sources.sort(
                key=lambda source: source_priority[source[0].workspace_slug]
            )
            state["wham"]["status"] = "prepared"
            state["wham"]["candidateKey"] = _candidate_key(ready_sources[0][0])
        else:
            state["wham"]["status"] = "failed"
            state["status"] = "retry_required"

    metrics["phaseTimings"]["whamGenerationSeconds"] = round(
        time.perf_counter() - wham_phase_started,
        3,
    )

    wham_release = _stop_warm_wham_worker_before_vlm(
        [item for item, _sources in prepared.values()]
    )
    for state in item_states.values():
        state["whamWorkerRelease"] = wham_release
    checkpoint("wham_released")

    announce(f"Reviewing {len(wham_ready)} generated movement(s).")
    checkpoint("final_validation")
    metrics["acceleratorTransitions"].append({"stage": "final_vlm", "at": _utc_now()})
    final_phase_started = time.perf_counter()
    final_session = LazyLlamaCppVisionSession(items[0].request)
    # Prepare independent workspaces while the shared session bounds GPU calls.
    final_worker_count = min(configured_parallelism, max(1, len(wham_ready)))
    metrics["finalValidationWorkers"] = final_worker_count
    validation_start_times: dict[str, float] = {}
    validation_queued_times: dict[str, float] = {}
    validation_scheduling_times: dict[str, dict[str, float]] = {}

    def finalize_item(
        exercise_id: str,
        item: StagedWaveItem,
        ready_sources: list[tuple[RankedCandidate, Path]],
    ) -> dict[str, Any]:
        validation_start_times[exercise_id] = time.perf_counter()

        def wait_for_prefetch():
            for candidate, _path in ready_sources:
                key = _candidate_key(candidate)
                future = render_futures.get(key)
                if future is not None:
                    try:
                        metrics["cpuRenderPrefetch"][key] = future.result()
                    except Exception as exc:
                        # A speculative render is never a quality decision. The
                        # owning candidate path will retry and classify a failure.
                        if is_storage_failure(exc):
                            raise
                        metrics["cpuRenderPrefetch"][key] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                        announce(f"CPU render preparation failed for {item.exercise_name}; normal bake will retry: {exc}")

        def process():
            return finalize_with_bounded_review_retry(lambda: run_bake_and_rank_pipeline(
                replace(
                    item.request,
                    require_wham_cache=True,
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
        timings = validation_scheduling_times[exercise_id]
        return run_timed_final_processing(
            queued_at=validation_queued_times[exercise_id],
            wait_for_prefetch=wait_for_prefetch, operation=process, timings=timings,
        )

    final_executor = ThreadPoolExecutor(max_workers=final_worker_count)
    try:
        final_futures = {}
        for exercise_id, (item, ready_sources) in wham_ready.items():
            validation_queued_times[exercise_id] = time.perf_counter()
            validation_scheduling_times[exercise_id] = {}
            future = final_executor.submit(finalize_item, exercise_id, item, ready_sources)
            final_futures[future] = (exercise_id, item, ready_sources)
        for future in as_completed(final_futures):
            exercise_id, item, ready_sources = final_futures[future]
            state = item_states[exercise_id]
            validation_started = validation_start_times[exercise_id]
            try:
                manifest = future.result()
                # Each wave may be resumed, and fallback rewrites the exercise's
                # selection manifest. Keep the decision itself in a unique file.
                decision_path = workspace / "final-decisions" / (
                    f"{item.exercise_id}-{time.time_ns()}.json"
                )
                decision_path.parent.mkdir(parents=True, exist_ok=True)
                _write_json_atomic(decision_path, manifest)
                selected = manifest.get("selected")
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
                state["finalValidation"] = {
                    **final_processing_diagnostics(manifest),
                    "reviewAttemptCount": manifest.get("reviewAttemptCount", 1),
                    "status": "selected" if selected else "no_selection",
                    "candidateKeys": [
                        _candidate_key(candidate) for candidate, _path in ready_sources
                    ],
                    "candidateKey": _candidate_key(selected_candidate),
                    "elapsedSeconds": round(time.perf_counter() - validation_started, 3),
                    "selectionManifestPath": str(decision_path),
                    "currentSelectionManifestPath": str(item.request.workspace / "selection_manifest.json"),
                    "selectedWearSkeletonPath": (
                        selected.get("selectedWearSkeletonPath")
                        if isinstance(selected, dict)
                        else None
                    ),
                }
                state["status"] = "completed" if selected else "retry_required"
            except Exception as exc:
                if is_storage_failure(exc):
                    raise
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
                    for attempt in state.get("wham", {}).get("attempts", [])), 3),
            }
            for entry in final_state.get("candidateDiagnostics", []):
                for key in ("generationSeconds", "rawWhamMotionGateSeconds", "previewBakeSeconds", "browser_bakeFailedSeconds"):
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
                    if key in {"generationSeconds", "rawWhamMotionGateSeconds", "previewBakeSeconds", "browser_bakeFailedSeconds",
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
        # Keep the VLM server hot only when the next useful stage is another
        # source wave. A retry needs WHAM again, so release VLM first.
        retry_pending = any(state["status"] != "completed" for state in item_states.values())
        final_session.close(force_stop_server=retry_pending)
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

    completed = [state for state in item_states.values() if state["status"] == "completed"]
    from exercise_motion_pkg.browser_workers import browser_worker_metrics
    from exercise_motion_pkg.review_questions import question_cache_metrics
    metrics["browserWorkers"] = browser_worker_metrics()
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
            "completedExerciseCount": len(completed),
            "retryExerciseCount": len(retry),
            "retryExerciseIds": [state["exerciseId"] for state in retry],
        }
    )
    attempts = [attempt for state in item_states.values()
                for attempt in state.get("wham", {}).get("attempts", [])]
    elapsed_minutes = float(report.get("elapsedSeconds") or 0.) / 60.
    report["generationEfficiency"] = {
        "acceptedMovementCount": len(completed),
        "candidateReconstructionAttempts": len(attempts),
        "reportedReconstructionCacheHits": sum(
            str(attempt.get("cacheStatus") or "").startswith("reused") for attempt in attempts),
        "acceptedPerElapsedMinute": len(completed) / elapsed_minutes if elapsed_minutes > 0 else None,
        "candidateAttemptsPerAcceptedMovement": len(attempts) / len(completed) if completed else None,
        "timingBasis": "wave_wall_clock_including_queue_and_validation",
    }
    heartbeat_stop.set()
    heartbeat_thread.join(timeout=1.0)
    _write_json_atomic(report_path, report)
    _write_json_atomic(checkpoint_path, report)
    announce(
        f"Batch finished: {len(completed)} kept, {len(retry)} need another try."
    )
    return report
