from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from exercise_motion_pkg import bake_and_rank as bake_module
from exercise_motion_pkg.bake_and_rank import (
    BakeAndRankRequest,
    RankedCandidate,
    copy_or_download_candidate_source,
    exercise_motion_contract_from_candidate,
    expand_ranked_candidates_for_source_windows,
    generate_exercise_motion_contract_for_bake,
    load_ranked_candidates_manifest,
    parse_optional_float,
    parse_ranked_candidates_manifest,
    rank_source_video_cut_candidates_with_caption_images,
    ranked_candidate_attempt_key,
)
from exercise_motion_pkg.chunking import estimate_chunking, frames_for_chunk_seconds
from exercise_motion_pkg.llama_defaults import (
    DEFAULT_LLAMA_CPP_MMPROJ,
    DEFAULT_LLAMA_CPP_MODEL,
    DEFAULT_LLAMA_CPP_REASONING_BUDGET,
    DEFAULT_LLAMA_CPP_REASONING_BUDGET_MESSAGE,
    DEFAULT_LLAMA_CPP_TEMPERATURE,
    DEFAULT_LLAMA_CPP_TOP_K,
    DEFAULT_LLAMA_CPP_TOP_P,
)
from exercise_motion_pkg.segment_detection import DetectionWindow, read_video_metadata
from exercise_motion_pkg.youtube import (
    ExerciseEntry,
    LlamaCppSemanticGate,
    LlamaCppVisionRanker,
    YouTubeCandidate,
    YouTubeRankingSettings,
    apply_semantic_gate_score,
    apply_vision_score,
    candidate_semantic_gate_payload,
    candidate_semantic_gate_passed,
    prepare_vision_reviews_parallel,
    round_elapsed,
    score_prepared_vision_reviews_parallel,
    semantic_gate_ranking_score,
    semantic_gate_score,
    slugify,
)


def utc_run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = optional_str(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def first_exercise_payload(manifest: dict[str, Any], exercise_index: int) -> dict[str, Any]:
    exercises = manifest.get("exercises")
    if not isinstance(exercises, list) or not exercises:
        raise ValueError("Candidate manifest must contain a non-empty exercises array.")
    if exercise_index < 0 or exercise_index >= len(exercises):
        raise IndexError(f"Exercise index {exercise_index} is outside manifest range 0..{len(exercises) - 1}.")
    exercise = exercises[exercise_index]
    if not isinstance(exercise, dict):
        raise ValueError(f"Exercise entry {exercise_index} is not an object.")
    return exercise


def exercise_entry_from_payload(exercise: dict[str, Any], *, fallback_name: str | None = None) -> ExerciseEntry:
    name = str(
        exercise.get("exerciseName")
        or exercise.get("name")
        or fallback_name
        or "Exercise"
    )
    exercise_id = str(exercise.get("exerciseId") or exercise.get("id") or slugify(name))
    return ExerciseEntry(
        exercise_id=exercise_id,
        name=name,
        slug=str(exercise.get("slug") or slugify(name)),
        source_name=optional_str(exercise.get("sourceExerciseName")),
        equipment_qualified_name=optional_str(exercise.get("equipmentQualifiedExerciseName")),
    )


def youtube_candidate_from_payload(candidate: dict[str, Any]) -> YouTubeCandidate:
    url = str(candidate.get("url") or candidate.get("webpageUrl") or candidate.get("videoUrl") or "")
    video_id = optional_str(candidate.get("videoId") or candidate.get("id"))
    score_reasons = candidate.get("scoreReasons")
    if not isinstance(score_reasons, list):
        score_reasons = []
    payload = candidate.get("visionPayload") if isinstance(candidate.get("visionPayload"), dict) else None
    return YouTubeCandidate(
        url=url,
        video_id=video_id,
        title=str(candidate.get("title") or candidate.get("name") or video_id or url or "candidate"),
        channel=optional_str(candidate.get("channel")),
        duration_seconds=optional_int(candidate.get("durationSeconds") or candidate.get("duration")),
        view_count=optional_int(candidate.get("viewCount") or candidate.get("view_count")),
        upload_date=optional_str(candidate.get("uploadDate") or candidate.get("upload_date")),
        description_snippet=optional_str(candidate.get("descriptionSnippet") or candidate.get("description")),
        thumbnail=optional_str(candidate.get("thumbnail")),
        vision_score=parse_optional_float(candidate.get("visionScore")),
        final_score=parse_optional_float(candidate.get("finalScore")) or 0.0,
        status=str(candidate.get("status") or "candidate"),
        score_reasons=[str(reason) for reason in score_reasons],
        vision_payload=payload,
    )


def load_youtube_candidates(
    manifest_path: Path,
    *,
    exercise_index: int,
    candidate_list: str,
    limit: int,
) -> tuple[ExerciseEntry, list[YouTubeCandidate]]:
    manifest = read_json(manifest_path)
    exercise_payload = first_exercise_payload(manifest, exercise_index)
    exercise = exercise_entry_from_payload(exercise_payload)
    raw_candidates = exercise_payload.get(candidate_list)
    if not isinstance(raw_candidates, list) and candidate_list == "debugCandidates":
        raw_candidates = exercise_payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError(f"Exercise entry has no {candidate_list!r} list.")
    candidates = [
        youtube_candidate_from_payload(candidate)
        for candidate in raw_candidates
        if isinstance(candidate, dict)
    ]
    if limit > 0:
        candidates = candidates[:limit]
    return exercise, candidates


def build_settings(args: argparse.Namespace, *, semantic: bool = False, vision: bool = False) -> YouTubeRankingSettings:
    return YouTubeRankingSettings(
        max_candidates=max(1, args.limit if args.limit > 0 else 9999),
        min_duration_seconds=args.min_duration_seconds,
        max_duration_seconds=args.max_duration_seconds,
        rank_with_vision=vision,
        semantic_gate_enabled=semantic,
        semantic_gate_candidates_per_exercise=max(1, args.limit if args.limit > 0 else 9999),
        semantic_gate_max_candidates_per_exercise=max(1, args.limit if args.limit > 0 else 9999),
        semantic_gate_min_score=args.semantic_gate_min_score,
        semantic_gate_duration_rank_weight=args.semantic_gate_duration_rank_weight,
        semantic_gate_llm_workers=args.semantic_gate_llm_workers,
        vision_candidates_per_exercise=max(1, args.limit if args.limit > 0 else 9999),
        vision_frames_per_candidate=args.vision_frames_per_candidate,
        vision_chunk_seconds=args.vision_chunk_seconds,
        vision_chunk_overlap_seconds=args.vision_chunk_overlap_seconds,
        vision_max_chunks_per_candidate=args.vision_max_chunks_per_candidate,
        vision_adaptive_chunk_review=not args.no_vision_adaptive_chunk_review,
        vision_initial_chunks_per_candidate=args.vision_initial_chunks_per_candidate,
        vision_expand_chunks_per_candidate=args.vision_expand_chunks_per_candidate,
        vision_motion_scan_sample_fps=args.vision_motion_scan_sample_fps,
        vision_motion_scan_max_seconds=args.vision_motion_scan_max_seconds,
        vision_download_workers=args.vision_download_workers,
        vision_llm_workers=args.vision_llm_workers,
        llama_cpp_base_url=args.llama_cpp_base_url,
        llama_cpp_model=args.llama_cpp_model,
        llama_cpp_server_command=args.llama_cpp_server_command,
        llama_cpp_mmproj=args.llama_cpp_mmproj,
        llama_cpp_backend=args.llama_cpp_backend,
        llama_cpp_n_predict=args.llama_cpp_n_predict,
        llama_cpp_temperature=args.llama_cpp_temperature,
        llama_cpp_top_p=args.llama_cpp_top_p,
        llama_cpp_top_k=args.llama_cpp_top_k,
        llama_cpp_disable_reasoning=args.llama_cpp_disable_reasoning,
        llama_cpp_reasoning_budget=args.llama_cpp_reasoning_budget,
        llama_cpp_reasoning_budget_message=args.llama_cpp_reasoning_budget_message,
        llama_cpp_ctx_size=args.llama_cpp_ctx_size,
        llama_cpp_batch_size=args.llama_cpp_batch_size,
        llama_cpp_ubatch_size=args.llama_cpp_ubatch_size,
        llama_cpp_flash_attn=args.llama_cpp_flash_attn,
        llama_cpp_cache_type_k=args.llama_cpp_cache_type_k,
        llama_cpp_cache_type_v=args.llama_cpp_cache_type_v,
        llama_cpp_parallel=args.llama_cpp_parallel,
        llama_cpp_threads_http=args.llama_cpp_threads_http,
        llama_cpp_cache_reuse=args.llama_cpp_cache_reuse,
        llama_cpp_fit=args.llama_cpp_fit,
        llama_cpp_fit_ctx=args.llama_cpp_fit_ctx,
        llama_cpp_fit_target=args.llama_cpp_fit_target,
        llama_cpp_mmap=not args.no_llama_cpp_mmap,
        llama_cpp_mlock=args.llama_cpp_mlock,
        llama_cpp_image_min_tokens=args.llama_cpp_image_min_tokens,
        llama_cpp_image_max_tokens=args.llama_cpp_image_max_tokens,
        llama_cpp_mtmd_batch_max_tokens=args.llama_cpp_mtmd_batch_max_tokens,
        llama_cpp_auto_start_server=not args.no_llama_cpp_auto_start_server,
        keep_llama_cpp_server=args.keep_llama_cpp_server,
        llama_cpp_server_startup_timeout_seconds=args.llama_cpp_server_startup_timeout_seconds,
        llama_cpp_request_timeout_seconds=args.llama_cpp_request_timeout_seconds,
    )


def run_semantic_stage(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    exercise, candidates = load_youtube_candidates(
        args.candidates_json,
        exercise_index=args.exercise_index,
        candidate_list=args.candidate_list,
        limit=args.limit,
    )
    settings = build_settings(args, semantic=True, vision=True)
    results_path = run_dir / "semantic_results.jsonl"
    started = time.perf_counter()
    ranker = LlamaCppSemanticGate(settings)
    rows: list[dict[str, Any]] = []
    try:
        workers = max(1, min(settings.resolved_semantic_gate_llm_workers(), len(candidates) or 1))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(ranker, exercise, candidate, settings): (index, candidate, time.perf_counter())
                for index, candidate in enumerate(candidates)
            }
            for future in as_completed(futures):
                index, candidate, row_started = futures[future]
                try:
                    score, reasons, payload = future.result()
                    scored = apply_semantic_gate_score(
                        candidate,
                        exercise=exercise,
                        semantic_score=score,
                        semantic_reasons=reasons,
                        semantic_payload=payload,
                        settings=settings,
                    )
                    semantic_payload = candidate_semantic_gate_payload(scored) or {}
                    row = {
                        "index": index,
                        "videoId": scored.video_id,
                        "url": scored.url,
                        "title": scored.title,
                        "elapsedSeconds": round_elapsed(time.perf_counter() - row_started),
                        "score": semantic_gate_score(scored),
                        "rankingScore": semantic_gate_ranking_score(scored, settings),
                        "passed": candidate_semantic_gate_passed(scored),
                        "status": scored.status,
                        "reasons": scored.score_reasons,
                        "semanticGate": semantic_payload,
                    }
                except Exception as exc:  # noqa: BLE001 - benchmark row
                    row = {
                        "index": index,
                        "videoId": candidate.video_id,
                        "url": candidate.url,
                        "title": candidate.title,
                        "elapsedSeconds": round_elapsed(time.perf_counter() - row_started),
                        "score": 0.0,
                        "passed": False,
                        "status": "failed",
                        "error": str(exc),
                    }
                rows.append(row)
                append_jsonl(results_path, row)
    finally:
        ranker.close()
    rows.sort(key=lambda item: int(item["index"]))
    pass_count = sum(1 for row in rows if row.get("passed") is True)
    summary = {
        "stage": "semantic",
        "exercise": exercise.name,
        "candidateCount": len(candidates),
        "passCount": pass_count,
        "workers": settings.resolved_semantic_gate_llm_workers(),
        "elapsedSeconds": round_elapsed(time.perf_counter() - started),
        "resultsJsonl": str(results_path),
    }
    write_json(run_dir / "summary.json", summary)
    return summary


def run_discovery_vlm_stage(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    exercise, candidates = load_youtube_candidates(
        args.candidates_json,
        exercise_index=args.exercise_index,
        candidate_list=args.candidate_list,
        limit=args.limit,
    )
    settings = build_settings(args, vision=True)
    results_path = run_dir / "discovery_vlm_results.jsonl"
    started = time.perf_counter()
    ranker = LlamaCppVisionRanker(settings)
    prepared_by_key = {}
    rows: list[dict[str, Any]] = []
    try:
        prepared_by_key = prepare_vision_reviews_parallel(
            exercise=exercise,
            candidates=candidates,
            settings=settings,
        )
        vision_results_by_key = score_prepared_vision_reviews_parallel(
            prepared_reviews=list(prepared_by_key.values()),
            settings=settings,
            vision_ranker=ranker,
        )
        for index, candidate in enumerate(candidates):
            row_started = time.perf_counter()
            vision_result = vision_results_by_key.get(candidate.key())
            if vision_result is None:
                row = {
                    "index": index,
                    "videoId": candidate.video_id,
                    "url": candidate.url,
                    "title": candidate.title,
                    "score": 0.0,
                    "status": "failed",
                    "reasons": ["vision_review_failed"],
                    "error": "No prepared vision result.",
                }
            else:
                vision_score, vision_reasons, vision_payload = vision_result
                scored = apply_vision_score(
                    candidate,
                    vision_score,
                    vision_reasons,
                    vision_payload if isinstance(vision_payload, dict) else None,
                    settings=settings,
                )
                payload = scored.vision_payload if isinstance(scored.vision_payload, dict) else {}
                row = {
                    "index": index,
                    "videoId": scored.video_id,
                    "url": scored.url,
                    "title": scored.title,
                    "score": scored.vision_score,
                    "finalScore": scored.final_score,
                    "status": scored.status,
                    "reasons": scored.score_reasons,
                    "bestChunkStartSeconds": payload.get("bestChunkStartSeconds"),
                    "bestChunkEndSeconds": payload.get("bestChunkEndSeconds"),
                    "bestChunkScore": payload.get("bestChunkScore"),
                    "validChunkCount": payload.get("validChunkCount"),
                    "scoredChunkCount": payload.get("scoredChunkCount"),
                    "totalVisionReviewElapsedSeconds": payload.get("totalVisionReviewElapsedSeconds"),
                    "totalChunkRenderElapsedSeconds": payload.get("totalChunkRenderElapsedSeconds"),
                    "totalChunkVlmElapsedSeconds": payload.get("totalChunkVlmElapsedSeconds"),
                    "reviewedChunks": payload.get("reviewedChunks"),
                }
            row["rowWriteElapsedSeconds"] = round_elapsed(time.perf_counter() - row_started)
            rows.append(row)
            append_jsonl(results_path, row)
    finally:
        for prepared in prepared_by_key.values():
            prepared.close()
        ranker.close()
    recommended_count = sum(1 for row in rows if row.get("status") == "recommended")
    summary = {
        "stage": "discovery-vlm",
        "exercise": exercise.name,
        "candidateCount": len(candidates),
        "preparedCandidateCount": len(prepared_by_key),
        "recommendedCount": recommended_count,
        "visionDownloadWorkers": settings.vision_download_workers,
        "visionLlmWorkers": settings.vision_llm_workers,
        "elapsedSeconds": round_elapsed(time.perf_counter() - started),
        "resultsJsonl": str(results_path),
    }
    write_json(run_dir / "summary.json", summary)
    return summary


def build_bake_request_for_pre_wham(args: argparse.Namespace, run_dir: Path) -> BakeAndRankRequest:
    return BakeAndRankRequest(
        candidates_json=args.candidates_json or (run_dir / "manual-candidate.json"),
        workspace=run_dir / "pre_wham_workspace",
        wham_repo_path=None,
        body_model_root=None,
        youtube_cookies=args.youtube_cookies,
        youtube_source_cache_dir=args.youtube_source_cache_dir,
        max_source_window_attempts=args.source_window_attempts,
        pre_wham_source_validation=True,
        exercise_motion_contract_enabled=args.contract_mode != "none",
        review_llm_workers=args.review_llm_workers,
        llama_cpp_base_url=args.llama_cpp_base_url,
        llama_cpp_model=args.llama_cpp_model,
        llama_cpp_server_command=args.llama_cpp_server_command,
        llama_cpp_mmproj=args.llama_cpp_mmproj,
        llama_cpp_backend=args.llama_cpp_backend,
        llama_cpp_n_predict=args.llama_cpp_n_predict,
        llama_cpp_temperature=args.llama_cpp_temperature,
        llama_cpp_top_p=args.llama_cpp_top_p,
        llama_cpp_top_k=args.llama_cpp_top_k,
        llama_cpp_disable_reasoning=args.llama_cpp_disable_reasoning,
        llama_cpp_reasoning_budget=args.llama_cpp_reasoning_budget,
        llama_cpp_reasoning_budget_message=args.llama_cpp_reasoning_budget_message,
        llama_cpp_ctx_size=args.llama_cpp_ctx_size,
        llama_cpp_batch_size=args.llama_cpp_batch_size,
        llama_cpp_ubatch_size=args.llama_cpp_ubatch_size,
        llama_cpp_flash_attn=args.llama_cpp_flash_attn,
        llama_cpp_cache_type_k=args.llama_cpp_cache_type_k,
        llama_cpp_cache_type_v=args.llama_cpp_cache_type_v,
        llama_cpp_parallel=args.llama_cpp_parallel,
        llama_cpp_threads_http=args.llama_cpp_threads_http,
        llama_cpp_cache_reuse=args.llama_cpp_cache_reuse,
        llama_cpp_fit=args.llama_cpp_fit,
        llama_cpp_fit_ctx=args.llama_cpp_fit_ctx,
        llama_cpp_fit_target=args.llama_cpp_fit_target,
        llama_cpp_mmap=not args.no_llama_cpp_mmap,
        llama_cpp_mlock=args.llama_cpp_mlock,
        llama_cpp_image_min_tokens=args.llama_cpp_image_min_tokens,
        llama_cpp_image_max_tokens=args.llama_cpp_image_max_tokens,
        llama_cpp_mtmd_batch_max_tokens=args.llama_cpp_mtmd_batch_max_tokens,
        llama_cpp_auto_start_server=not args.no_llama_cpp_auto_start_server,
        keep_llama_cpp_server=args.keep_llama_cpp_server,
        llama_cpp_server_startup_timeout_seconds=args.llama_cpp_server_startup_timeout_seconds,
        llama_cpp_request_timeout_seconds=args.llama_cpp_request_timeout_seconds,
    )


def manual_ranked_candidate(args: argparse.Namespace) -> RankedCandidate:
    if args.video_path is None:
        raise ValueError("--video-path is required for manual pre-wham runs.")
    if not args.exercise_name:
        raise ValueError("--exercise-name is required for manual pre-wham runs.")
    if args.start_seconds is None or args.end_seconds is None or args.end_seconds <= args.start_seconds:
        raise ValueError("--start-seconds and --end-seconds must define a valid manual source window.")
    exercise_slug = slugify(args.exercise_name)
    return RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id=exercise_slug,
        exercise_name=args.exercise_name,
        exercise_slug=exercise_slug,
        candidate={
            "videoPath": str(args.video_path),
            "title": args.title or args.video_path.stem,
            "status": "manual",
            "sourceWindowHint": {
                "startSeconds": args.start_seconds,
                "endSeconds": args.end_seconds,
                "score": 1.0,
            },
        },
    )


def load_ranked_candidates_for_pre_wham(args: argparse.Namespace, request: BakeAndRankRequest) -> list[RankedCandidate]:
    if args.video_path is not None:
        return [manual_ranked_candidate(args)]
    if args.candidates_json is None:
        raise ValueError("--candidates-json or --video-path is required for pre-wham-source.")
    if args.include_fallback_candidates:
        candidates = load_ranked_candidates_manifest(args.candidates_json, include_fallback_candidates=True)
    else:
        payload = read_json(args.candidates_json)
        candidates = [
            candidate
            for candidate in parse_ranked_candidates_manifest(payload)
            if str(candidate.candidate.get("status") or "").casefold() == "recommended"
        ]
        if not candidates:
            candidates = load_ranked_candidates_manifest(args.candidates_json, include_fallback_candidates=False)
    expanded = expand_ranked_candidates_for_source_windows(candidates, request=request)
    if args.limit > 0:
        expanded = expanded[: args.limit]
    return expanded


def contract_for_pre_wham_candidate(
    ranked_candidate: RankedCandidate,
    *,
    request: BakeAndRankRequest,
    ranker: LlamaCppVisionRanker,
    mode: str,
) -> dict[str, Any] | None:
    if mode == "none":
        return None
    candidate_contract = exercise_motion_contract_from_candidate(ranked_candidate.candidate)
    if candidate_contract is not None:
        return {**candidate_contract, "exerciseMotionContractStatus": "reused_candidate_contract"}
    if mode == "candidate":
        return None
    return generate_exercise_motion_contract_for_bake(
        ranked_candidate=ranked_candidate,
        request=request,
        caption_images=ranker.client.caption_images,
    )


def full_video_window(video_path: Path) -> DetectionWindow:
    metadata = read_video_metadata(video_path)
    return DetectionWindow(index=0, start_seconds=0.0, end_seconds=max(0.1, metadata.duration_seconds))


def window_for_ranked_candidate(ranked_candidate: RankedCandidate, source_video_path: Path) -> DetectionWindow:
    hint = ranked_candidate.source_chunk_hint
    if hint is None:
        return full_video_window(source_video_path)
    return DetectionWindow(index=0, start_seconds=hint.start_seconds, end_seconds=hint.end_seconds)


def run_pre_wham_source_stage(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    request = build_bake_request_for_pre_wham(args, run_dir)
    candidates = load_ranked_candidates_for_pre_wham(args, request)
    results_path = run_dir / "pre_wham_source_results.jsonl"
    started = time.perf_counter()
    vision_settings = replace(
        build_settings(args, vision=True),
        vision_llm_workers=max(1, args.review_llm_workers),
    )
    ranker = LlamaCppVisionRanker(vision_settings)
    rows: list[dict[str, Any]] = []
    try:
        source_cache_dir = args.youtube_source_cache_dir or bake_module.resolved_youtube_source_cache_dir(request)
        preview_cache_dir = args.youtube_preview_cache_dir or bake_module.default_youtube_preview_cache_read_through_dir(request)
        for index, ranked_candidate in enumerate(candidates):
            row_started = time.perf_counter()
            candidate_dir = run_dir / "pre_wham_candidates" / f"{index + 1:03d}-{ranked_candidate.workspace_slug}"
            source_dir = candidate_dir / "source"
            try:
                source_video_path = copy_or_download_candidate_source(
                    ranked_candidate,
                    source_dir,
                    youtube_cookies=args.youtube_cookies,
                    youtube_source_cache_dir=source_cache_dir,
                    youtube_preview_cache_dir=preview_cache_dir,
                )
                source_window = window_for_ranked_candidate(ranked_candidate, source_video_path)
                chunk_estimate = estimate_chunking(
                    exercise_name=ranked_candidate.exercise_name,
                    use_llm=False,
                )
                duration = max(0.5, source_window.end_seconds - source_window.start_seconds)
                frame_count = args.pre_wham_frame_count or max(12, min(args.review_frames, frames_for_chunk_seconds(duration)))
                contract = contract_for_pre_wham_candidate(
                    ranked_candidate,
                    request=request,
                    ranker=ranker,
                    mode=args.contract_mode,
                )
                vision_payload = ranked_candidate.candidate.get("visionPayload")
                pose_payload = (
                    vision_payload.get("posePrefilter")
                    if isinstance(vision_payload, dict) and isinstance(vision_payload.get("posePrefilter"), dict)
                    else None
                )
                source_choice = rank_source_video_cut_candidates_with_caption_images(
                    video_path=source_video_path,
                    exercise_name=ranked_candidate.exercise_name,
                    candidate_title=ranked_candidate.title,
                    timeline_window=source_window,
                    chunk_estimate=chunk_estimate,
                    output_dir=candidate_dir / "source_scorecard",
                    frame_count=frame_count,
                    caption_images=ranker.client.caption_images,
                    exercise_motion_contract=contract,
                    source_pose_prefilter_payload=pose_payload,
                    source_pose_offset_seconds=0.0,
                    max_vlm_workers=args.review_llm_workers,
                )
                if source_choice is None:
                    row = {
                        "index": index,
                        "attemptKey": ranked_candidate_attempt_key(ranked_candidate),
                        "videoId": ranked_candidate.video_id,
                        "title": ranked_candidate.title,
                        "status": "no_source_candidates",
                        "passed": False,
                        "score": 0.0,
                    }
                else:
                    ranking, render_seconds, vlm_seconds = source_choice
                    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
                    rows_payload = payload.get("sourceCutScorecardCandidates")
                    row = {
                        "index": index,
                        "attemptKey": ranked_candidate_attempt_key(ranked_candidate),
                        "videoId": ranked_candidate.video_id,
                        "title": ranked_candidate.title,
                        "sourceWindowStartSeconds": source_window.start_seconds,
                        "sourceWindowEndSeconds": source_window.end_seconds,
                        "score": ranking.score,
                        "passed": ranking.score >= bake_module.SOURCE_CUT_MIN_SELECTED_SCORE,
                        "reasons": ranking.reasons,
                        "selectedCandidateId": payload.get("selectedCandidateId"),
                        "selectedStartSeconds": payload.get("selected_section_start_seconds"),
                        "selectedEndSeconds": payload.get("selected_section_end_seconds"),
                        "renderSeconds": render_seconds,
                        "vlmSeconds": vlm_seconds,
                        "sourceCutCandidateCount": len(payload.get("sourceCutCandidates") or []),
                        "sourceCutCandidates": payload.get("sourceCutCandidates"),
                        "sourceCutVlmInputCandidateCount": len(payload.get("sourceCutVlmInputCandidates") or []),
                        "sourceCutVlmInputCandidates": payload.get("sourceCutVlmInputCandidates"),
                        "sourceCutProgressiveSelection": payload.get("sourceCutProgressiveSelection"),
                        "sourceCutScorecardRowCount": len(rows_payload) if isinstance(rows_payload, list) else 0,
                        "sourceCutScorecardRows": rows_payload,
                        "sourceCutScorecardContractPresent": payload.get("sourceCutScorecardContractPresent"),
                        "sourceCutScorecardThresholds": payload.get("sourceCutScorecardThresholds"),
                        "sourceCutMotionCoverageDiagnosticFailedCount": payload.get(
                            "sourceCutMotionCoverageDiagnosticFailedCount"
                        ),
                        "sourceChoiceInvalidResponse": payload.get("sourceChoiceInvalidResponse"),
                        "rawResponseLength": len(ranking.raw_response or ""),
                        "rawResponsePreview": (ranking.raw_response or "")[:1000],
                    }
            except Exception as exc:  # noqa: BLE001 - benchmark row
                row = {
                    "index": index,
                    "attemptKey": ranked_candidate_attempt_key(ranked_candidate),
                    "videoId": ranked_candidate.video_id,
                    "title": ranked_candidate.title,
                    "status": "failed",
                    "passed": False,
                    "score": 0.0,
                    "error": str(exc),
                }
            row["elapsedSeconds"] = round_elapsed(time.perf_counter() - row_started)
            rows.append(row)
            append_jsonl(results_path, row)
    finally:
        ranker.close()
    pass_count = sum(1 for row in rows if row.get("passed") is True)
    summary = {
        "stage": "pre-wham-source",
        "candidateWindowCount": len(candidates),
        "passCount": pass_count,
        "contractMode": args.contract_mode,
        "sourceScorecardRequestPolicy": "one_candidate_per_request",
        "reviewLlmWorkers": args.review_llm_workers,
        "elapsedSeconds": round_elapsed(time.perf_counter() - started),
        "resultsJsonl": str(results_path),
    }
    write_json(run_dir / "summary.json", summary)
    return summary


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidates-json", type=Path)
    parser.add_argument("--exercise-index", type=int, default=0)
    parser.add_argument("--candidate-list", choices=("candidates", "debugCandidates"), default="debugCandidates")
    parser.add_argument("--limit", type=int, default=0, help="Maximum candidates/windows to process. 0 means all.")
    parser.add_argument("--output-dir", type=Path, default=Path("build") / "exercise_motion_step_bench")
    parser.add_argument(
        "--min-duration-seconds",
        type=int,
        default=0,
        help="Minimum YouTube video duration in seconds. 0 disables the lower duration filter.",
    )
    parser.add_argument("--max-duration-seconds", type=int, default=120)
    parser.add_argument("--youtube-cookies", type=Path)
    parser.add_argument("--youtube-source-cache-dir", type=Path)
    parser.add_argument("--youtube-preview-cache-dir", type=Path)
    parser.add_argument("--semantic-gate-min-score", type=float, default=0.55)
    parser.add_argument("--semantic-gate-duration-rank-weight", type=float, default=0.15)
    parser.add_argument("--semantic-gate-llm-workers", type=int)
    parser.add_argument("--vision-download-workers", type=int, default=8)
    parser.add_argument("--vision-llm-workers", type=int, default=4)
    parser.add_argument("--vision-frames-per-candidate", type=int)
    parser.add_argument("--vision-chunk-seconds", type=float)
    parser.add_argument("--vision-chunk-overlap-seconds", type=float)
    parser.add_argument("--vision-max-chunks-per-candidate", type=int)
    parser.add_argument("--no-vision-adaptive-chunk-review", action="store_true")
    parser.add_argument("--vision-initial-chunks-per-candidate", type=int, default=3)
    parser.add_argument("--vision-expand-chunks-per-candidate", type=int, default=5)
    parser.add_argument("--vision-motion-scan-sample-fps", type=float, default=0.5)
    parser.add_argument("--vision-motion-scan-max-seconds", type=float, default=90.0)
    parser.add_argument("--review-frames", type=int, default=32)
    parser.add_argument("--review-llm-workers", type=int, default=4)
    parser.add_argument("--pre-wham-frame-count", type=int)
    parser.add_argument("--source-window-attempts", type=int, default=3)
    parser.add_argument("--include-fallback-candidates", action="store_true")
    parser.add_argument("--contract-mode", choices=("none", "candidate", "generate"), default="candidate")
    parser.add_argument("--video-path", type=Path)
    parser.add_argument("--exercise-name")
    parser.add_argument("--title")
    parser.add_argument("--start-seconds", type=float)
    parser.add_argument("--end-seconds", type=float)
    parser.add_argument("--llama-cpp-base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--llama-cpp-model", default=DEFAULT_LLAMA_CPP_MODEL)
    parser.add_argument("--llama-cpp-server-command")
    parser.add_argument("--llama-cpp-mmproj", default=DEFAULT_LLAMA_CPP_MMPROJ)
    parser.add_argument("--llama-cpp-backend", default="gpu")
    parser.add_argument("--llama-cpp-n-predict", type=int, default=512)
    parser.add_argument("--llama-cpp-temperature", type=float, default=DEFAULT_LLAMA_CPP_TEMPERATURE)
    parser.add_argument("--llama-cpp-top-p", type=float, default=DEFAULT_LLAMA_CPP_TOP_P)
    parser.add_argument("--llama-cpp-top-k", type=int, default=DEFAULT_LLAMA_CPP_TOP_K)
    parser.add_argument("--llama-cpp-disable-reasoning", action="store_true")
    parser.add_argument("--llama-cpp-reasoning-budget", type=int, default=DEFAULT_LLAMA_CPP_REASONING_BUDGET)
    parser.add_argument("--llama-cpp-reasoning-budget-message", default=DEFAULT_LLAMA_CPP_REASONING_BUDGET_MESSAGE)
    parser.add_argument("--llama-cpp-ctx-size", type=int)
    parser.add_argument("--llama-cpp-batch-size", type=int)
    parser.add_argument("--llama-cpp-ubatch-size", type=int)
    parser.add_argument("--llama-cpp-flash-attn", choices=("on", "off", "auto"))
    parser.add_argument("--llama-cpp-cache-type-k", choices=("f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"))
    parser.add_argument("--llama-cpp-cache-type-v", choices=("f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"))
    parser.add_argument("--llama-cpp-parallel", type=int)
    parser.add_argument("--llama-cpp-threads-http", type=int)
    parser.add_argument("--llama-cpp-cache-reuse", type=int)
    parser.add_argument("--llama-cpp-fit", choices=("on", "off"))
    parser.add_argument("--llama-cpp-fit-ctx", type=int)
    parser.add_argument("--llama-cpp-fit-target", type=int)
    parser.add_argument("--no-llama-cpp-mmap", action="store_true")
    parser.add_argument("--llama-cpp-mlock", action="store_true")
    parser.add_argument("--llama-cpp-image-min-tokens", type=int)
    parser.add_argument("--llama-cpp-image-max-tokens", type=int)
    parser.add_argument("--llama-cpp-mtmd-batch-max-tokens", type=int)
    parser.add_argument("--no-llama-cpp-auto-start-server", action="store_true")
    parser.add_argument("--keep-llama-cpp-server", action="store_true")
    parser.add_argument("--llama-cpp-server-startup-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--llama-cpp-request-timeout-seconds", type=float, default=240.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated exercise-motion pipeline stage benchmarks.")
    parser.add_argument(
        "--stage",
        required=True,
        choices=("semantic", "discovery-vlm", "pre-wham-source"),
    )
    add_common_args(parser)
    args = parser.parse_args()
    if args.stage in {"semantic", "discovery-vlm"} and args.candidates_json is None:
        parser.error(f"--candidates-json is required for stage {args.stage}.")
    run_dir = args.output_dir / f"{args.stage}-{utc_run_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(
        run_dir / "settings.json",
        {
            "stage": args.stage,
            "arguments": {
                key: str(value) if isinstance(value, Path) else value
                for key, value in vars(args).items()
            },
        },
    )
    if args.stage == "semantic":
        summary = run_semantic_stage(args, run_dir)
    elif args.stage == "discovery-vlm":
        summary = run_discovery_vlm_stage(args, run_dir)
    else:
        summary = run_pre_wham_source_stage(args, run_dir)
    print(json.dumps({"runDir": str(run_dir), **summary}, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
