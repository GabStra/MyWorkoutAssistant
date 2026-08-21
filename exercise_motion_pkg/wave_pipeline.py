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
    SourceCandidateRejected,
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
)
from exercise_motion_pkg.vlm_errors import critical_vlm_interaction_error
from exercise_motion_pkg.wham_runner import WhamTrackingPreflightRejected


STAGED_SOURCE_PORTFOLIO_MAX_SIZE = 3
STAGED_SOURCE_VALIDATION_MAX_WORKERS = 4


@dataclass(frozen=True)
class StagedWaveItem:
    exercise_id: str
    exercise_name: str
    request: BakeAndRankRequest


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _candidate_key(candidate: RankedCandidate) -> str:
    return f"{candidate.exercise_id}:{candidate.workspace_slug}"


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


def run_staged_bake_wave(
    items: list[StagedWaveItem],
    *,
    workspace: Path,
    wave_id: str,
    progress: Callable[[str], None] | None = None,
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
    workspace = workspace.expanduser().resolve()
    checkpoint_path = workspace / "staged_wave_checkpoint.json"
    report_path = workspace / "staged_wave_report.json"
    started_at = time.perf_counter()
    metrics: dict[str, Any] = {
        "sourceValidationWorkers": 0,
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
            attempts: list[dict[str, Any]] = []
            selected_sources: list[tuple[RankedCandidate, Path]] = []
            selected_source_identities: set[str] = set()
            requested_portfolio_size: int | None = None
            resolver = build_exercise_motion_contract_resolver(
                request=item.request,
                caption_images=source_session.caption_images,
                run_llama_exclusive=source_session.run_without_llama_overlap,
            )
            for candidate in _wave_candidates(item.request):
                source_identity = _candidate_source_identity(candidate)
                if source_identity in selected_source_identities:
                    continue
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
                    selected_video = prepare_candidate_input_video(
                        candidate,
                        request=item.request,
                        source_cut_caption_images=source_session.caption_images,
                        exercise_motion_contract_resolver=resolver,
                    )
                except Exception as exc:
                    vlm_error = critical_vlm_interaction_error(exc)
                    if isinstance(exc, SourceCandidateRejected):
                        attempt["status"] = "rejected_source_validation"
                        attempt["error"] = f"{type(exc).__name__}: {exc}"
                    elif vlm_error is not None:
                        attempt["status"] = "rejected_vlm_timeout"
                        attempt["error"] = f"{type(vlm_error).__name__}: {vlm_error}"
                    else:
                        attempt["status"] = "rejected_source_validation"
                        attempt["error"] = f"{type(exc).__name__}: {exc}"
                    continue
                attempt["status"] = "prepared"
                attempt["selectedVideoPath"] = str(selected_video)
                selected_sources.append((candidate, selected_video))
                selected_source_identities.add(source_identity)
                if requested_portfolio_size is None:
                    requested_portfolio_size = max(
                        1,
                        min(
                            STAGED_SOURCE_PORTFOLIO_MAX_SIZE,
                            first_attempt_portfolio_size(readiness),
                        ),
                    )
                if len(selected_sources) >= requested_portfolio_size:
                    break
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
                try:
                    item, selected_sources, attempts = future.result()
                except Exception as exc:
                    state = item_states[submitted_item.exercise_id]
                    state["source"] = {
                        "status": "failed",
                        "attempts": [],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    state["status"] = "retry_required"
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
                    eligible_attempts = [
                        attempt
                        for attempt in attempts
                        if bool(
                            (attempt.get("firstAttemptReadiness") or {}).get("eligible")
                        )
                    ]
                    state["source"]["failureReason"] = (
                        "no_reconstruction_ready_source"
                        if not eligible_attempts
                        else "no_source_passed_exact_window_validation"
                    )
                    state["source"]["noNewWork"] = not attempts
                    state["status"] = "retry_required"
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

    def generate_item_motion(
        exercise_id: str,
        item: StagedWaveItem,
        candidate: RankedCandidate,
        selected_video_path: Path,
    ) -> tuple[str, StagedWaveItem, Any, float]:
        wham_started = time.perf_counter()
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
    # The warm WHAM worker owns one persistent CUDA model and consumes its job
    # queue serially. Multiple caller threads only contend on the same lock.
    wham_worker_count = 1
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
            wham_started = time.perf_counter()
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
            except Exception as exc:
                failure_status = (
                    "rejected_tracking_preflight"
                    if isinstance(exc, WhamTrackingPreflightRejected)
                    else "failed"
                )
                attempt = {
                    "status": failure_status,
                    "candidateKey": _candidate_key(candidate),
                    "selectedVideoPath": str(selected_video_path),
                    "elapsedSeconds": round(time.perf_counter() - wham_started, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                if isinstance(exc, WhamTrackingPreflightRejected):
                    attempt["trackingPreflight"] = exc.report
                wham_attempts[exercise_id].append(attempt)
            wham_completed_count += 1
            successful_attempts = [
                attempt for attempt in wham_attempts[exercise_id]
                if attempt["status"] == "prepared"
            ]
            state["wham"] = {
                "status": "prepared" if successful_attempts else "pending",
                "attempts": wham_attempts[exercise_id],
            }
            checkpoint("wham_generation", item.exercise_name)
            announce(
                f"Extracted motion for {item.exercise_name} "
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
    try:
        for exercise_id, (item, ready_sources) in wham_ready.items():
            state = item_states[exercise_id]
            validation_started = time.perf_counter()
            try:
                manifest = run_bake_and_rank_pipeline(
                    replace(
                        item.request,
                        require_wham_cache=True,
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
                )
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
                    "status": "selected" if selected else "no_selection",
                    "candidateKeys": [
                        _candidate_key(candidate) for candidate, _path in ready_sources
                    ],
                    "candidateKey": _candidate_key(selected_candidate),
                    "elapsedSeconds": round(time.perf_counter() - validation_started, 3),
                    "selectionManifestPath": str(item.request.workspace / "selection_manifest.json"),
                    "selectedWearSkeletonPath": (
                        selected.get("selectedWearSkeletonPath")
                        if isinstance(selected, dict)
                        else None
                    ),
                }
                state["status"] = "completed" if selected else "retry_required"
            except Exception as exc:
                state["finalValidation"] = {
                    "status": "failed",
                    "elapsedSeconds": round(time.perf_counter() - validation_started, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                state["status"] = "retry_required"
            checkpoint("final_validation", item.exercise_name)
    finally:
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
    retry = [state for state in item_states.values() if state["status"] != "completed"]
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
    heartbeat_stop.set()
    heartbeat_thread.join(timeout=1.0)
    _write_json_atomic(report_path, report)
    _write_json_atomic(checkpoint_path, report)
    announce(
        f"Batch finished: {len(completed)} kept, {len(retry)} need another try."
    )
    return report
