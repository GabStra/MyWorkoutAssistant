from __future__ import annotations

import base64
import html
import json
import math
import os
import shutil
import statistics
import traceback
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

from exercise_motion_pkg.motion_io import load_motion_json
from exercise_motion_pkg.pipeline import GenerateRequest, GenerateResult, run_generation_pipeline
from exercise_motion_pkg.segment_detection import (
    DetectionSettings,
    DetectionWindow,
    SupportDominanceResult,
    classify_support_dominance_from_frames,
    detect_exercise_segment,
    extract_json_object,
    extract_window_frames,
    iter_detection_windows,
    save_detection_result,
)
from exercise_motion_pkg.video_utils import read_basic_video_metadata, trim_video
from exercise_motion_pkg.youtube import LlamaCppVisionRanker, YouTubeRankingSettings, download_youtube, slugify
from exercise_motion_pkg.chunking import estimate_chunking, find_default_litert_command, frames_for_chunk_seconds


DEFAULT_MAX_LOOP_SECONDS = 10.0
DEFAULT_REVIEW_FRAMES = 6
DEFAULT_LLM_REVIEW_FRAMES = 16
DEFAULT_LLM_REVIEW_CONTACT_SHEET_CELL_WIDTH = 320
MAX_DENSE_REVIEW_VIDEO_FRAMES = 360
SELECTED_SECTION_REVIEW_VIDEO_LOOP_REPEATS = 3
DEFAULT_RANK_FRAME_WIDTH = 640
DEFAULT_MIN_SELECTED_SCORE = 0.55
DEFAULT_FALLBACK_CANDIDATES = 3
DEFAULT_MAX_REVIEW_WINDOWS = 3
LOOP_MODEL_SCORE_WEIGHT = 0.35
LOOP_CONTINUITY_SCORE_WEIGHT = 0.35
LOOP_MOTION_SCORE_WEIGHT = 0.3
LOOP_SOURCE_MOTION_CAPTURE_RATIO_MIN = 0.8
LOOP_SOURCE_STRONG_MOTION_RATIO_MIN = 0.22
LOOP_WEAK_FULL_REP_SCORE_CAP = 0.52
LOOP_MIN_STRONG_MODEL_FULL_REP_MOTION = 0.7
LOOP_DETERMINISTIC_FALLBACK_SCORE_CAP = 0.49
LOOP_RIGID_ROOT_MOTION_SCORE_CAP = 0.52
LOOP_RIGID_ROOT_DOMINANT_RANGE_RATIO = 0.18
LOOP_RIGID_ROOT_MIN_ARTICULATION_RATIO = 0.08
LOOP_KINEMATIC_ARTIFACT_SCORE_CAP = 0.52
LOOP_BRIDGE_ARTIFACT_SCORE_CAP = 0.52
LOOP_BRIDGE_ENDPOINT_BODY_RATIO = 0.10
LOOP_BRIDGE_STEP_RATIO = 2.5
LOOP_BRIDGE_STEP_BODY_RATIO = 0.03
WINDOW_LOW_LOOPABILITY_SCORE_CAP = 0.52
WINDOW_MIN_LOOPABILITY_SCORE = 0.35
PREVIEW_READABILITY_SCORE_WEIGHT = 0.08
PREVIEW_READABILITY_LOW_SCORE_CAP = 0.58
PREVIEW_READABILITY_LOW_THRESHOLD = 0.35
KINEMATIC_CLEAN_SUBINTERVAL_FALLBACK_MAX_WINDOWS = 5
KINEMATIC_CLEAN_SUBINTERVAL_MIN_SECONDS = 1.0
KINEMATIC_CLEAN_SUBINTERVAL_STEP_SECONDS = 0.35
KINEMATIC_SOURCE_CAPTURE_EXCLUSION_RADIUS_FRAMES = 1
KINEMATIC_ARTIFACT_REASON_CODES = {
    "limb_velocity_spike_penalty",
    "joint_angle_spike_penalty",
    "bone_length_instability_penalty",
}
MATERIALIZED_REEVALUATION_REASON_CODES = {
    *KINEMATIC_ARTIFACT_REASON_CODES,
    "loop_restart_discontinuity_penalty",
    "weak_full_rep_motion_penalty",
    "llm_weak_full_rep_motion_penalty",
    "rigid_root_motion_penalty",
    "deterministic_fallback_selection_cap",
    "loop_bridge_pose_mismatch_penalty",
}
KINEMATIC_DISTAL_STEP_SPIKE_RATIO = 8.0
KINEMATIC_DISTAL_STEP_BODY_RATIO = 0.08
KINEMATIC_ANGLE_STEP_DEGREES = 25.0
KINEMATIC_BONE_LENGTH_VARIATION_RATIO = 0.18
KINEMATIC_BONE_LENGTH_BODY_RATIO = 0.06
WINDOW_MOTION_SCORE_WEIGHT = 0.75
WINDOW_CONTINUITY_SCORE_WEIGHT = 0.25
SOURCE_GATE_MIN_BEST_CHUNK_SCORE = 0.35
SOURCE_GATE_STRONG_BEST_CHUNK_SCORE = 0.85
SOURCE_GATE_MIN_VALID_CHUNK_RATIO = 0.25
SOURCE_GATE_MIN_VALID_CHUNK_COUNT = 2
SOURCE_GATE_MIN_SCORED_CHUNKS_FOR_COVERAGE = 3
BAKED_MOTION_MIN_STRENGTH_SCORE = 0.15
BAKED_MOTION_MIN_PRIMARY_RANGE_RATIO = 0.06


def launch_chromium_browser(
    playwright: Any,
    *,
    fallback_executables: Iterable[Path] | None = None,
) -> Any:
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as primary_exc:
        fallback_errors: list[str] = []
        for executable_path in fallback_executables or default_chromium_executable_candidates():
            if not executable_path.exists():
                continue
            try:
                return playwright.chromium.launch(
                    headless=True,
                    executable_path=str(executable_path),
                )
            except Exception as fallback_exc:
                fallback_errors.append(f"{executable_path}: {fallback_exc}")
        detail = f" Fallback launch failures: {'; '.join(fallback_errors)}" if fallback_errors else ""
        raise RuntimeError(
            "Playwright could not launch Chromium. Install the bundled browser with "
            "`python -m playwright install chromium`, or install Chrome/Edge so the "
            f"pipeline can use a system browser.{detail}"
        ) from primary_exc


def default_chromium_executable_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or os.environ.get("CHROME_EXECUTABLE")
    if env_path:
        candidates.append(Path(env_path))
    for command in ("chrome", "chrome.exe", "msedge", "msedge.exe", "chromium", "chromium.exe"):
        resolved = shutil.which(command)
        if resolved:
            candidates.append(Path(resolved))
    candidates.extend(
        [
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
            Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


@dataclass(frozen=True)
class SourceChunkHint:
    start_seconds: float
    end_seconds: float
    score: float | None = None

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


@dataclass(frozen=True)
class RankedCandidate:
    exercise_index: int
    candidate_rank: int
    exercise_id: str
    exercise_name: str
    exercise_slug: str
    candidate: dict[str, Any]

    @property
    def url(self) -> str | None:
        value = self.candidate.get("url") or self.candidate.get("videoUrl") or self.candidate.get("webpageUrl")
        return str(value).strip() if value else None

    @property
    def video_path(self) -> Path | None:
        value = self.candidate.get("videoPath") or self.candidate.get("sourceVideoPath")
        return Path(str(value)) if value else None

    @property
    def video_id(self) -> str | None:
        value = self.candidate.get("videoId") or self.candidate.get("id")
        return str(value).strip() if value else None

    @property
    def title(self) -> str:
        value = self.candidate.get("title")
        return str(value).strip() if value else f"candidate-{self.candidate_rank + 1}"

    @property
    def workspace_slug(self) -> str:
        identity = self.video_id or self.title or str(self.candidate_rank + 1)
        return slugify(f"{self.exercise_slug}-{self.candidate_rank + 1:03d}-{identity}")[:120]

    @property
    def source_chunk_hint(self) -> SourceChunkHint | None:
        payload = self.candidate.get("visionPayload")
        if not isinstance(payload, dict):
            return None
        start_seconds = parse_optional_float(payload.get("bestChunkStartSeconds"))
        end_seconds = parse_optional_float(payload.get("bestChunkEndSeconds"))
        if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
            return None
        score = parse_optional_float(payload.get("bestChunkScore"))
        return SourceChunkHint(
            start_seconds=max(0.0, start_seconds),
            end_seconds=end_seconds,
            score=score,
        )


@dataclass(frozen=True)
class EligibleLoop:
    loop_index: int
    loop: dict[str, Any]
    duration_sec: float
    start_seconds: float = 0.0
    end_seconds: float = 0.0


@dataclass(frozen=True)
class RejectedLoop:
    loop_index: int
    loop: dict[str, Any]
    duration_sec: float
    reason: str


@dataclass(frozen=True)
class BakedLoopArtifact:
    loop_index: int
    skeleton_path: Path
    review_video_path: Path
    export_payload: dict[str, Any]
    skeleton_path_no_feet_lock: Path | None = None
    skeleton_path_no_hand_lock: Path | None = None
    settings_variant_id: str = "full-preview"
    settings_variant_label: str = "Full preview"
    settings_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KinematicSafeBakeResult:
    artifact: BakedLoopArtifact
    selected_kinematic_metrics: dict[str, Any] | None = None
    selected_loop_bridge_metrics: dict[str, Any] | None = None
    original_kinematic_metrics: dict[str, Any] | None = None
    original_loop_bridge_metrics: dict[str, Any] | None = None
    support_lock_rebake_attempted: bool = False
    support_lock_rebake_applied: bool = False
    support_lock_rebake_options: dict[str, Any] | None = None
    support_lock_rebake_metrics: dict[str, Any] | None = None
    support_lock_rebake_loop_bridge_metrics: dict[str, Any] | None = None


@dataclass(frozen=True)
class LoopRanking:
    score: float
    reasons: list[str]
    raw_response: str | None = None
    payload: dict[str, Any] | None = None
    model_score: float | None = None
    continuity_score: float | None = None
    continuity_metrics: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReviewItem:
    exercise_index: int
    candidate_rank: int
    loop_index: int
    exercise_name: str
    candidate_title: str
    candidate_workspace: Path
    preview_html_path: Path
    skeleton_path: Path
    review_video_path: Path
    duration_sec: float
    loop_start_seconds: float
    loop_end_seconds: float
    candidate: dict[str, Any]
    support_dominance: str | None = None
    support_dominance_confidence: float | None = None
    support_dominance_reason: str | None = None
    support_dominance_uncertain: bool | None = None
    support_dominance_model_output: dict[str, object] | None = None
    skeleton_path_no_feet_lock: Path | None = None
    skeleton_path_no_hand_lock: Path | None = None
    settings_variant_id: str = "lock-feet-hands"
    settings_variant_label: str = "Lock feet and hands"
    settings_options: dict[str, Any] = field(default_factory=dict)
    llm_time_range_cut_applied: bool = False
    source_review_video_path: Path | None = None
    source_skeleton_path: Path | None = None


@dataclass(frozen=True)
class ReviewWindowCandidate:
    video_window: DetectionWindow
    timeline_window: DetectionWindow
    score: float
    motion_metrics: dict[str, Any]
    continuity_metrics: dict[str, Any]
    kinematic_metrics: dict[str, Any]
    loop_bridge_quality_metrics: dict[str, Any] = field(default_factory=dict)
    preview_readability_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BakeAndRankRequest:
    candidates_json: Path
    workspace: Path
    wham_repo_path: Path | None
    body_model_root: Path | None
    fallback_candidates: int = DEFAULT_FALLBACK_CANDIDATES
    candidate_workers: int = 1
    wham_python_command: str = "python"
    reuse_wham_cache: bool = True
    use_wham_docker: bool = False
    wham_docker_image: str = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest"
    wham_docker_gpus: str = "all"
    wham_docker_shm_size: str = "8g"
    wham_estimate_local_only: bool = False
    wham_run_smplify: bool = True
    detect_source_segment: bool = True
    segment_base_url: str | None = None
    segment_model: str | None = None
    segment_window_seconds: float | None = None
    segment_overlap_seconds: float | None = None
    segment_frames_per_window: int | None = None
    segment_confidence_threshold: float = 0.45
    segment_padding_seconds: float = 0.35
    segment_end_padding_seconds: float = 0.35
    segment_min_seconds: float = 2.0
    segment_max_seconds: float = 20.0
    segment_refinement_window_seconds: float = 2.0
    segment_refinement_overlap_seconds: float = 1.0
    segment_refinement_frames_per_window: int = 0
    segment_refinement_padding_seconds: float = 1.0
    segment_classification_workers: int = 3
    review_frames: int = DEFAULT_REVIEW_FRAMES
    review_llm_workers: int = 3
    max_llm_review_items: int = 4
    max_review_windows: int = DEFAULT_MAX_REVIEW_WINDOWS
    max_loop_seconds: float = DEFAULT_MAX_LOOP_SECONDS
    min_selected_score: float = DEFAULT_MIN_SELECTED_SCORE
    motion_tuning_enabled: bool = True
    select_preview_section: bool = False
    rank_preview_variants: bool = False
    classify_support_dominance: bool = True
    llama_cpp_base_url: str | None = "http://127.0.0.1:8090"
    llama_cpp_model: str = "C:\\Users\\gabri\\Downloads\\Qwen3VL-8B-Instruct-Q4_K_M.gguf"
    llama_cpp_command: str | None = None
    llama_cpp_server_command: str | None = None
    llama_cpp_mmproj: str | None = "C:\\Users\\gabri\\Downloads\\mmproj-Qwen3VL-8B-Instruct-F16.gguf"
    llama_cpp_backend: str = "gpu"
    llama_cpp_n_predict: int = 768
    llama_cpp_temperature: float = 0.0
    llama_cpp_disable_reasoning: bool = True
    llama_cpp_ctx_size: int | None = None
    llama_cpp_batch_size: int | None = None
    llama_cpp_ubatch_size: int | None = None
    llama_cpp_flash_attn: str | None = None
    llama_cpp_threads_http: int | None = None
    llama_cpp_cache_reuse: int | None = None
    llama_cpp_mmproj_offload: bool = True
    llama_cpp_cont_batching: bool = True
    llama_cpp_image_min_tokens: int | None = None
    llama_cpp_image_max_tokens: int | None = None
    llama_cpp_auto_start_server: bool = True
    keep_llama_cpp_server: bool = False
    llama_cpp_server_startup_timeout_seconds: float = 180.0
    llama_cpp_request_timeout_seconds: float = 90.0


PreviewBaker = Callable[[Path, list[EligibleLoop], Path, int], list[BakedLoopArtifact]]
LoopRanker = Callable[[list[ReviewItem], BakeAndRankRequest], list[LoopRanking]]
SelectedArtifact = tuple[ReviewItem, LoopRanking | None]


def load_ranked_candidates_manifest(path: Path) -> list[RankedCandidate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        candidate
        for candidate in parse_ranked_candidates_manifest(payload)
        if candidate_bake_status(candidate) != "rejected"
    ]


def candidate_bake_status(candidate: RankedCandidate) -> str:
    value = candidate.candidate.get("status")
    return str(value).strip().casefold() if value is not None else ""


def evaluate_source_candidate_gate(candidate: RankedCandidate) -> dict[str, Any]:
    status = candidate_bake_status(candidate)
    reasons: list[str] = []
    if status in {"rejected", "disabled"}:
        reasons.append(f"candidate_status_{status}")

    payload = candidate.candidate.get("visionPayload")
    best_chunk_score = None
    hard_gate_failures: list[str] = []
    if isinstance(payload, dict):
        best_chunk_score = parse_optional_float(payload.get("bestChunkScore"))
        if best_chunk_score is not None and best_chunk_score < SOURCE_GATE_MIN_BEST_CHUNK_SCORE:
            reasons.append("low_ranked_source_chunk_score")
        valid_chunk_ratio = parse_optional_float(payload.get("validChunkRatio"))
        valid_chunk_count = parse_optional_int(payload.get("validChunkCount"))
        scored_chunk_count = parse_optional_int(payload.get("scoredChunkCount"))
        strong_single_chunk_source = (
            best_chunk_score is not None
            and best_chunk_score >= SOURCE_GATE_STRONG_BEST_CHUNK_SCORE
            and valid_chunk_count is not None
            and valid_chunk_count >= 1
        )
        if (
            scored_chunk_count is not None
            and scored_chunk_count >= SOURCE_GATE_MIN_SCORED_CHUNKS_FOR_COVERAGE
            and not strong_single_chunk_source
            and (
                (valid_chunk_count is not None and valid_chunk_count < SOURCE_GATE_MIN_VALID_CHUNK_COUNT)
                or (valid_chunk_ratio is not None and valid_chunk_ratio < SOURCE_GATE_MIN_VALID_CHUNK_RATIO)
            )
        ):
            reasons.append("low_source_evidence_coverage")
        if parse_optional_bool(payload.get("target_identity_match")) is False:
            reasons.append("target_identity_mismatch")
        for field in (
            "correct_exercise",
            "usable_for_motion_extraction",
            "complete_repetition_visible",
            "athlete_fully_in_frame_throughout",
            "static_camera_throughout",
            "single_person_chunk",
            "continuous_motion",
        ):
            if parse_optional_bool(payload.get(field)) is False:
                hard_gate_failures.append(field)
        if hard_gate_failures:
            reasons.append("source_vision_hard_gate_failed")

    return {
        "passed": not reasons,
        "reasons": reasons,
        "status": status or None,
        "bestChunkScore": best_chunk_score,
        "validChunkRatio": parse_optional_float(payload.get("validChunkRatio")) if isinstance(payload, dict) else None,
        "validChunkCount": parse_optional_int(payload.get("validChunkCount")) if isinstance(payload, dict) else None,
        "scoredChunkCount": parse_optional_int(payload.get("scoredChunkCount")) if isinstance(payload, dict) else None,
        "hardGateFailures": hard_gate_failures,
    }


def parse_ranked_candidates_manifest(payload: dict[str, Any]) -> list[RankedCandidate]:
    exercises = payload.get("exercises")
    if not isinstance(exercises, list):
        raise ValueError("Candidate manifest must contain an exercises array.")
    ranked: list[RankedCandidate] = []
    for exercise_index, exercise in enumerate(exercises):
        if not isinstance(exercise, dict):
            continue
        candidates = exercise.get("candidates")
        if not isinstance(candidates, list):
            continue
        exercise_name = str(exercise.get("exerciseName") or exercise.get("name") or f"Exercise {exercise_index + 1}")
        exercise_slug = str(exercise.get("slug") or slugify(exercise_name))
        exercise_id = str(exercise.get("exerciseId") or exercise.get("id") or exercise_slug)
        for candidate_rank, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                continue
            ranked.append(
                RankedCandidate(
                    exercise_index=exercise_index,
                    candidate_rank=candidate_rank,
                    exercise_id=exercise_id,
                    exercise_name=exercise_name,
                    exercise_slug=exercise_slug,
                    candidate=candidate,
                )
            )
    return ranked


def parse_top_ranked_candidates_manifest(payload: dict[str, Any]) -> list[RankedCandidate]:
    ranked = parse_ranked_candidates_manifest(payload)
    top_by_exercise: dict[int, RankedCandidate] = {}
    for candidate in ranked:
        existing = top_by_exercise.get(candidate.exercise_index)
        if existing is None or candidate.candidate_rank < existing.candidate_rank:
            top_by_exercise[candidate.exercise_index] = candidate
    return [top_by_exercise[index] for index in sorted(top_by_exercise)]


def split_loops_by_duration(
    loops: Iterable[dict[str, Any]],
    *,
    max_loop_seconds: float,
) -> tuple[list[EligibleLoop], list[RejectedLoop]]:
    eligible: list[EligibleLoop] = []
    rejected: list[RejectedLoop] = []
    for loop_index, loop in enumerate(loops):
        duration_sec = parse_loop_duration(loop)
        start_seconds, end_seconds = parse_loop_time_bounds(loop, fallback_duration_sec=duration_sec)
        if duration_sec <= max_loop_seconds:
            eligible.append(
                EligibleLoop(
                    loop_index=loop_index,
                    loop=loop,
                    duration_sec=duration_sec,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                )
            )
        else:
            rejected.append(
                RejectedLoop(
                    loop_index=loop_index,
                    loop=loop,
                    duration_sec=duration_sec,
                    reason="loop_too_long",
                )
            )
    return eligible, rejected


def parse_loop_duration(loop: dict[str, Any]) -> float:
    value = loop.get("durationSec")
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return max(0.0, float(value))
    return 0.0


def parse_loop_time_bounds(loop: dict[str, Any], *, fallback_duration_sec: float) -> tuple[float, float]:
    start = parse_optional_float(loop.get("startTimeSec"))
    end = parse_optional_float(loop.get("endTimeSec"))
    if start is None:
        start = 0.0
    if end is None:
        end = start + max(0.0, fallback_duration_sec)
    if end < start:
        end = start
    return start, end


def parse_optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        if math.isfinite(parsed):
            return parsed
    return None


def parse_optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        if math.isfinite(parsed) and parsed.is_integer():
            return int(parsed)
    return None


def parse_loop_ranking_response(raw: str) -> LoopRanking:
    payload = extract_json_object(raw)
    if payload is None:
        return LoopRanking(score=0.0, reasons=["ranking_invalid_json"], raw_response=raw)
    score = payload.get("score")
    if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
        return LoopRanking(score=0.0, reasons=["ranking_missing_score"], raw_response=raw, payload=payload)
    reasons_value = payload.get("reasons") or payload.get("reason")
    if isinstance(reasons_value, list):
        reasons = [str(item) for item in reasons_value if str(item).strip()]
    elif isinstance(reasons_value, str) and reasons_value.strip():
        reasons = [reasons_value.strip()]
    else:
        reasons = []
    return LoopRanking(score=max(0.0, min(1.0, float(score))), reasons=reasons, raw_response=raw, payload=payload)


def choose_best_review_item(
    items: list[ReviewItem],
    rankings: list[LoopRanking],
    *,
    min_score: float = 0.0,
) -> tuple[ReviewItem, LoopRanking] | None:
    paired = list(zip(items, rankings))
    if not paired:
        return None
    selected = max(
        paired,
        key=lambda pair: (
            pair[1].score,
            -pair[0].exercise_index,
            -pair[0].candidate_rank,
            -pair[0].loop_index,
        ),
    )
    if selected[1].score < min_score:
        return None
    return selected


def choose_best_materialized_review_item(
    items: list[ReviewItem],
    rankings: list[LoopRanking],
    *,
    request: BakeAndRankRequest,
) -> tuple[SelectedArtifact | None, SelectedArtifact | None]:
    paired = sorted(
        zip(items, rankings),
        key=lambda pair: (
            pair[1].score,
            -pair[0].exercise_index,
            -pair[0].candidate_rank,
            -pair[0].loop_index,
        ),
        reverse=True,
    )
    if not paired:
        return None, None

    accepted_best: SelectedArtifact | None = None
    rejected_best: SelectedArtifact | None = None
    for item, ranking in paired:
        if ranking.score < request.min_selected_score and "llm_review_skipped_by_prefilter" in ranking.reasons:
            skipped = (item, ranking)
            if rejected_best is None or selected_artifact_score(skipped) > selected_artifact_score(rejected_best):
                rejected_best = skipped
            continue
        original = (item, ranking)
        materialized = refresh_materialized_selection_ranking(
            original=original,
            materialized=materialize_llm_selected_time_range(original, request=request),
        )
        if selected_artifact_score(materialized) >= request.min_selected_score:
            if accepted_best is None or selected_artifact_score(materialized) > selected_artifact_score(accepted_best):
                accepted_best = materialized
            continue
        fallback = materialize_clean_subinterval_fallback(
            original=original,
            rejected=materialized,
            request=request,
        )
        if fallback is not None:
            if selected_artifact_score(fallback) >= request.min_selected_score:
                if accepted_best is None or selected_artifact_score(fallback) > selected_artifact_score(accepted_best):
                    accepted_best = fallback
                continue
            if rejected_best is None or selected_artifact_score(fallback) > selected_artifact_score(rejected_best):
                rejected_best = fallback
        if rejected_best is None or selected_artifact_score(materialized) > selected_artifact_score(rejected_best):
            rejected_best = materialized
    if accepted_best is not None:
        return accepted_best, None
    return None, rejected_best


def materialize_clean_subinterval_fallback(
    *,
    original: SelectedArtifact,
    rejected: SelectedArtifact,
    request: BakeAndRankRequest,
) -> SelectedArtifact | None:
    if not selected_artifact_has_kinematic_rejection(rejected):
        return None
    original_item, original_ranking = original
    if original_ranking is None:
        return None
    windows = build_kinematic_clean_subinterval_windows(original_item, request=request)
    if not windows:
        return None
    window_candidates = [
        candidate
        for candidate in score_review_windows_by_skeleton_motion(original_item, windows)
        if not bool(candidate.kinematic_metrics.get("severeArtifact"))
    ][:KINEMATIC_CLEAN_SUBINTERVAL_FALLBACK_MAX_WINDOWS]
    best: SelectedArtifact | None = None
    for window_candidate in window_candidates:
        fallback_ranking = build_kinematic_clean_subinterval_ranking(
            original_ranking,
            window_candidate=window_candidate,
        )
        materialized_item, materialized_ranking = materialize_review_item_time_range(
            original_item,
            fallback_ranking,
            request=request,
            start_seconds=window_candidate.timeline_window.start_seconds,
            end_seconds=window_candidate.timeline_window.end_seconds,
            artifact_id="kinematic-clean-subinterval",
            artifact_label="Kinematic clean sub-interval",
            cut_applied=True,
        )
        adjusted = (
            materialized_item,
            apply_loop_continuity_adjustment(materialized_item, materialized_ranking or fallback_ranking),
        )
        if best is None or selected_artifact_score(adjusted) > selected_artifact_score(best):
            best = adjusted
    return best


def selected_artifact_has_kinematic_rejection(selected: SelectedArtifact) -> bool:
    _item, ranking = selected
    if ranking is None:
        return False
    return bool(kinematic_artifact_reasons_from_ranking(ranking))


def kinematic_artifact_reasons_from_ranking(ranking: LoopRanking) -> list[str]:
    reasons = [
        reason
        for reason in ranking.reasons
        if reason in KINEMATIC_ARTIFACT_REASON_CODES
    ]
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    metrics = payload.get("kinematicPlausibilityMetrics")
    if isinstance(metrics, dict) and bool(metrics.get("severeArtifact")):
        metric_reasons = metrics.get("artifactReasons")
        if isinstance(metric_reasons, list):
            reasons.extend(
                str(reason)
                for reason in metric_reasons
                if str(reason) in KINEMATIC_ARTIFACT_REASON_CODES
            )
    return dedupe_text(reasons)


def build_kinematic_clean_subinterval_windows(
    item: ReviewItem,
    *,
    request: BakeAndRankRequest,
) -> list[DetectionWindow]:
    source_start = max(0.0, item.loop_start_seconds)
    source_end = item.loop_end_seconds if item.loop_end_seconds > source_start else source_start + item.duration_sec
    if source_end <= source_start:
        return []
    source_duration = source_end - source_start
    max_duration = min(
        source_duration,
        request.max_loop_seconds if request.max_loop_seconds > 0 else source_duration,
    )
    durations = build_kinematic_clean_subinterval_durations(source_duration, max_duration=max_duration)
    windows: list[DetectionWindow] = []
    seen: set[tuple[int, int]] = set()
    for duration in durations:
        max_start = source_end - duration
        starts = float_range(source_start, max_start, KINEMATIC_CLEAN_SUBINTERVAL_STEP_SECONDS)
        if not starts or abs(starts[-1] - max_start) > 1e-6:
            starts.append(max_start)
        for start_seconds in starts:
            end_seconds = min(source_end, start_seconds + duration)
            key = (int(round(start_seconds * 1000)), int(round(end_seconds * 1000)))
            if key in seen or end_seconds - start_seconds < KINEMATIC_CLEAN_SUBINTERVAL_MIN_SECONDS:
                continue
            seen.add(key)
            windows.append(
                DetectionWindow(
                    index=len(windows),
                    start_seconds=max(0.0, start_seconds - source_start),
                    end_seconds=max(0.0, end_seconds - source_start),
                )
            )
    return windows


def build_kinematic_clean_subinterval_durations(
    source_duration: float,
    *,
    max_duration: float,
) -> list[float]:
    min_duration = min(max_duration, KINEMATIC_CLEAN_SUBINTERVAL_MIN_SECONDS)
    raw_durations = [
        max_duration * ratio
        for ratio in (0.85, 0.75, 0.66, 0.5)
    ]
    raw_durations.extend(min(value, max_duration) for value in (5.0, 4.0, 3.0, 2.0))
    durations = sorted(
        {
            round(duration, 3)
            for duration in raw_durations
            if min_duration <= duration < source_duration - 0.05
        },
        reverse=True,
    )
    return durations


def float_range(start: float, end: float, step: float) -> list[float]:
    if end < start:
        return []
    values: list[float] = []
    current = start
    effective_step = max(step, 1e-3)
    while current <= end + 1e-6:
        values.append(current)
        current += effective_step
    return values


def build_kinematic_clean_subinterval_ranking(
    ranking: LoopRanking,
    *,
    window_candidate: ReviewWindowCandidate,
) -> LoopRanking:
    base_score = ranking.model_score
    if base_score is None and isinstance(ranking.payload, dict):
        base_score = parse_optional_float(ranking.payload.get("modelScore"))
    if base_score is None:
        base_score = ranking.score
    score = min(clamp_unit(base_score), clamp_unit(window_candidate.score))
    payload = dict(ranking.payload) if isinstance(ranking.payload, dict) else {}
    payload.update(
        {
            "selected_section_start_seconds": window_candidate.timeline_window.start_seconds,
            "selected_section_end_seconds": window_candidate.timeline_window.end_seconds,
            "kinematicCleanSubintervalFallback": True,
            "kinematicCleanSubintervalWindowScore": window_candidate.score,
            "kinematicCleanSubintervalMotionMetrics": window_candidate.motion_metrics,
            "kinematicCleanSubintervalContinuityMetrics": window_candidate.continuity_metrics,
            "kinematicCleanSubintervalKinematicMetrics": window_candidate.kinematic_metrics,
            "kinematicCleanSubintervalLoopBridgeQualityMetrics": window_candidate.loop_bridge_quality_metrics,
            "kinematicCleanSubintervalPreviewReadabilityMetrics": window_candidate.preview_readability_metrics,
        }
    )
    return LoopRanking(
        score=score,
        reasons=dedupe_text([*recomputed_materialized_reasons(ranking.reasons), "kinematic_clean_subinterval_fallback"]),
        raw_response=ranking.raw_response,
        payload=payload,
        model_score=score,
    )


def selected_artifact_score(selected: SelectedArtifact) -> float:
    _item, ranking = selected
    if ranking is None:
        return 1.0
    return ranking.score


def refresh_materialized_selection_ranking(
    *,
    original: SelectedArtifact,
    materialized: SelectedArtifact,
) -> SelectedArtifact:
    original_item, _original_ranking = original
    materialized_item, ranking = materialized
    if ranking is None or materialized_item == original_item:
        return materialized
    base_score = ranking.model_score
    if base_score is None and isinstance(ranking.payload, dict):
        base_score = parse_optional_float(ranking.payload.get("modelScore"))
    if base_score is None:
        base_score = ranking.score
    base_payload = dict(ranking.payload or {})
    reasons = recomputed_materialized_reasons(ranking.reasons)
    base_ranking = LoopRanking(
        score=clamp_unit(base_score),
        reasons=dedupe_text([*reasons, "llm_materialized_before_threshold"]),
        raw_response=ranking.raw_response,
        payload=base_payload,
    )
    return (
        materialized_item,
        apply_loop_continuity_adjustment(materialized_item, base_ranking),
    )


def recomputed_materialized_reasons(reasons: list[str]) -> list[str]:
    return [
        reason
        for reason in reasons
        if reason not in MATERIALIZED_REEVALUATION_REASON_CODES
    ]


def apply_loop_continuity_adjustment(item: ReviewItem, ranking: LoopRanking) -> LoopRanking:
    continuity_metrics = compute_loop_continuity_metrics(item.skeleton_path)
    continuity_score = float(continuity_metrics["continuityScore"])
    loop_bridge_metrics = compute_loop_bridge_quality_metrics(item.skeleton_path)
    loop_bridge_score = float(loop_bridge_metrics["loopBridgeQualityScore"])
    loopability_score = min(continuity_score, loop_bridge_score)
    preview_readability_metrics = compute_preview_readability_metrics(
        item.skeleton_path,
        camera_yaw_degrees=parse_optional_float(item.settings_options.get("cameraYawDegrees")) or 45.0,
    )
    preview_readability_score = float(preview_readability_metrics["previewReadabilityScore"])
    motion_metrics = compute_motion_strength_metrics(item.skeleton_path)
    motion_score = float(motion_metrics["motionStrengthScore"])
    kinematic_metrics = compute_kinematic_plausibility_metrics(item.skeleton_path)
    kinematic_score = float(kinematic_metrics["kinematicPlausibilityScore"])
    motion_score = min(motion_score, kinematic_score)
    model_full_rep_motion = parse_optional_float((ranking.payload or {}).get("full_rep_motion") if isinstance(ranking.payload, dict) else None)
    if model_full_rep_motion is not None:
        motion_score = min(motion_score, clamp_unit(model_full_rep_motion))
    source_motion_metrics = None
    source_capture_ratio = None
    if item.source_skeleton_path is not None and item.source_skeleton_path.exists():
        source_range = source_capture_time_range_for_item(item)
        source_motion_metrics = compute_source_capture_motion_strength_metrics(
            item.source_skeleton_path,
            start_seconds=source_range[0] if source_range is not None else None,
            end_seconds=source_range[1] if source_range is not None else None,
        )
        source_motion_range = parse_optional_float(source_motion_metrics.get("primaryMotionRangeRatio"))
        selected_motion_range = parse_optional_float(motion_metrics.get("primaryMotionRangeRatio"))
        if source_motion_range is not None and selected_motion_range is not None and source_motion_range > 1e-6:
            source_capture_ratio = clamp_unit(selected_motion_range / source_motion_range)
            capture_score = clamp_unit((source_capture_ratio - 0.55) / 0.35)
            motion_score = min(motion_score, capture_score)
    adjusted_score = clamp_unit(
        ranking.score * LOOP_MODEL_SCORE_WEIGHT
        + loopability_score * LOOP_CONTINUITY_SCORE_WEIGHT
        + motion_score * LOOP_MOTION_SCORE_WEIGHT
    )
    adjusted_score = clamp_unit(
        adjusted_score
        + (preview_readability_score - 0.5) * PREVIEW_READABILITY_SCORE_WEIGHT
    )
    reasons = list(ranking.reasons)
    if continuity_score < 0.65:
        reasons.append("loop_restart_discontinuity_penalty")
    if bool(loop_bridge_metrics.get("severeLoopMismatch")):
        adjusted_score = min(adjusted_score, LOOP_BRIDGE_ARTIFACT_SCORE_CAP)
        reasons.append("loop_bridge_pose_mismatch_penalty")
    if (
        source_capture_ratio is not None
        and source_motion_metrics is not None
        and float(source_motion_metrics["primaryMotionRangeRatio"]) >= LOOP_SOURCE_STRONG_MOTION_RATIO_MIN
        and source_capture_ratio < LOOP_SOURCE_MOTION_CAPTURE_RATIO_MIN
    ):
        adjusted_score = min(adjusted_score, LOOP_WEAK_FULL_REP_SCORE_CAP)
        reasons.append("weak_full_rep_motion_penalty")
    if model_full_rep_motion is not None and model_full_rep_motion < LOOP_MIN_STRONG_MODEL_FULL_REP_MOTION:
        adjusted_score = min(adjusted_score, LOOP_WEAK_FULL_REP_SCORE_CAP)
        reasons.append("llm_weak_full_rep_motion_penalty")
    if "deterministic_section_fallback" in reasons:
        adjusted_score = min(adjusted_score, LOOP_DETERMINISTIC_FALLBACK_SCORE_CAP)
        reasons.append("deterministic_fallback_selection_cap")
    if preview_readability_score < PREVIEW_READABILITY_LOW_THRESHOLD:
        adjusted_score = min(adjusted_score, PREVIEW_READABILITY_LOW_SCORE_CAP)
        reasons.append("low_preview_readability_penalty")
    root_relative_articulation = parse_optional_float(motion_metrics.get("rootRelativeArticulationRangeRatio")) or 0.0
    root_dominant_range = max(
        parse_optional_float(motion_metrics.get("rootVerticalRangeRatio")) or 0.0,
        parse_optional_float(motion_metrics.get("rootTravelRangeRatio")) or 0.0,
    )
    if (
        root_dominant_range >= LOOP_RIGID_ROOT_DOMINANT_RANGE_RATIO
        and root_relative_articulation < LOOP_RIGID_ROOT_MIN_ARTICULATION_RATIO
    ):
        adjusted_score = min(adjusted_score, LOOP_RIGID_ROOT_MOTION_SCORE_CAP)
        motion_score = min(motion_score, clamp_unit(root_relative_articulation / LOOP_RIGID_ROOT_MIN_ARTICULATION_RATIO))
        reasons.append("rigid_root_motion_penalty")
    for reason in kinematic_metrics.get("artifactReasons", []):
        adjusted_score = min(adjusted_score, LOOP_KINEMATIC_ARTIFACT_SCORE_CAP)
        reasons.append(str(reason))
    payload = dict(ranking.payload or {})
    payload["modelScore"] = ranking.score
    payload["continuityScore"] = continuity_score
    payload["continuityMetrics"] = continuity_metrics
    payload["loopabilityScore"] = loopability_score
    payload["loopBridgeQualityScore"] = loop_bridge_score
    payload["loopBridgeQualityMetrics"] = loop_bridge_metrics
    payload["motionStrengthScore"] = motion_score
    payload["motionStrengthMetrics"] = motion_metrics
    payload["previewReadabilityScore"] = preview_readability_score
    payload["previewReadabilityMetrics"] = preview_readability_metrics
    payload["kinematicPlausibilityScore"] = kinematic_score
    payload["kinematicPlausibilityMetrics"] = kinematic_metrics
    if source_motion_metrics is not None:
        payload["sourceMotionStrengthMetrics"] = source_motion_metrics
    if source_capture_ratio is not None:
        payload["sourceMotionCaptureRatio"] = source_capture_ratio
    return LoopRanking(
        score=adjusted_score,
        reasons=dedupe_text(reasons),
        raw_response=ranking.raw_response,
        payload=payload,
        model_score=ranking.score,
        continuity_score=continuity_score,
        continuity_metrics=continuity_metrics,
    )


def source_capture_time_range_for_item(item: ReviewItem) -> tuple[float, float] | None:
    if not item.llm_time_range_cut_applied:
        return None
    if item.loop_end_seconds <= item.loop_start_seconds:
        return None
    return item.loop_start_seconds, item.loop_end_seconds


def compute_motion_strength_metrics(skeleton_path: Path) -> dict[str, Any]:
    payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    return compute_motion_strength_metrics_from_payload(payload)


def compute_motion_strength_metrics_from_payload(
    payload: dict[str, Any],
    *,
    frames_override: list[Any] | None = None,
) -> dict[str, Any]:
    frames_value = frames_override if frames_override is not None else payload.get("frames")
    joint_names_value = payload.get("jointNames")
    if not isinstance(frames_value, list) or not isinstance(joint_names_value, list):
        return empty_motion_strength_metrics()
    frames = [frame for frame in frames_value if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))]
    if not frames:
        frames = [frame for frame in frames_value if isinstance(frame, dict)]
    joint_names = [str(name) for name in joint_names_value]
    if len(frames) < 2 or not joint_names:
        return empty_motion_strength_metrics()

    joint_tracks: dict[str, list[list[float]]] = {joint_name: [] for joint_name in joint_names}
    frame_heights: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        frame_points: list[list[float]] = []
        if isinstance(joints, dict):
            for joint_name in joint_names:
                point = joints.get(joint_name)
                if is_point3(point):
                    point3 = [float(point[0]), float(point[1]), float(point[2])]
                    joint_tracks[joint_name].append(point3)
                    frame_points.append(point3)
        if frame_points:
            y_values = [point[1] for point in frame_points]
            frame_heights.append(max(y_values) - min(y_values))

    body_height = statistics.median(frame_heights) if frame_heights else 0.0
    if body_height <= 1e-6:
        return empty_motion_strength_metrics()

    root_joint = str(payload.get("rootJoint") or "")
    if root_joint not in joint_tracks:
        root_joint = next((joint for joint in ("pelvis", "hips", "root") if joint in joint_tracks), "")

    joint_range_ratios: list[float] = []
    joint_vertical_range_ratios: list[float] = []
    root_relative_joint_range_ratios: list[float] = []
    lower_body_root_relative_range_ratios: list[float] = []
    upper_body_root_relative_range_ratios: list[float] = []
    root_vertical_range_ratio = 0.0
    root_travel_range_ratio = 0.0
    root_points = joint_tracks.get(root_joint, [])
    for joint_name, points in joint_tracks.items():
        if len(points) < 2:
            continue
        ranges = [
            max(point[axis] for point in points) - min(point[axis] for point in points)
            for axis in range(3)
        ]
        range_ratio = math.sqrt(sum(axis_range * axis_range for axis_range in ranges)) / body_height
        vertical_range_ratio = ranges[1] / body_height
        joint_range_ratios.append(range_ratio)
        joint_vertical_range_ratios.append(vertical_range_ratio)
        if joint_name == root_joint:
            root_vertical_range_ratio = vertical_range_ratio
            root_travel_range_ratio = range_ratio
        elif len(root_points) == len(points):
            relative_points = [
                [
                    point[axis] - root_point[axis]
                    for axis in range(3)
                ]
                for point, root_point in zip(points, root_points)
            ]
            relative_ranges = [
                max(point[axis] for point in relative_points) - min(point[axis] for point in relative_points)
                for axis in range(3)
            ]
            root_relative_range_ratio = math.sqrt(sum(axis_range * axis_range for axis_range in relative_ranges)) / body_height
            root_relative_joint_range_ratios.append(root_relative_range_ratio)
            if is_lower_body_joint(joint_name):
                lower_body_root_relative_range_ratios.append(root_relative_range_ratio)
            if is_upper_body_joint(joint_name):
                upper_body_root_relative_range_ratios.append(root_relative_range_ratio)

    if not joint_range_ratios:
        return empty_motion_strength_metrics(body_height=body_height)
    sorted_joint_ranges = sorted(joint_range_ratios)
    upper_count = max(1, len(sorted_joint_ranges) // 4)
    upper_joint_range_ratio = sum(sorted_joint_ranges[-upper_count:]) / upper_count
    max_joint_range_ratio = max(joint_range_ratios)
    max_joint_vertical_range_ratio = max(joint_vertical_range_ratios) if joint_vertical_range_ratios else 0.0
    primary_motion_range_ratio = max(
        root_vertical_range_ratio,
        root_travel_range_ratio,
        max_joint_range_ratio,
        max_joint_vertical_range_ratio,
    )
    root_relative_articulation_range_ratio = max(root_relative_joint_range_ratios, default=0.0)
    lower_body_articulation_range_ratio = max(lower_body_root_relative_range_ratios, default=0.0)
    upper_body_articulation_range_ratio = max(upper_body_root_relative_range_ratios, default=0.0)
    motion_strength_score = clamp_unit(
        max(
            root_vertical_range_ratio / 0.22,
            root_travel_range_ratio / 0.26,
            max_joint_range_ratio / 0.30,
            upper_joint_range_ratio / 0.24,
            max_joint_vertical_range_ratio / 0.24,
            root_relative_articulation_range_ratio / 0.18,
        )
    )
    return {
        "motionStrengthScore": motion_strength_score,
        "bodyHeight": body_height,
        "rootJoint": root_joint or None,
        "rootVerticalRangeRatio": root_vertical_range_ratio,
        "rootTravelRangeRatio": root_travel_range_ratio,
        "maxJointRangeRatio": max_joint_range_ratio,
        "maxJointVerticalRangeRatio": max_joint_vertical_range_ratio,
        "upperJointRangeRatio": upper_joint_range_ratio,
        "primaryMotionRangeRatio": primary_motion_range_ratio,
        "rootRelativeArticulationRangeRatio": root_relative_articulation_range_ratio,
        "lowerBodyRootRelativeRangeRatio": lower_body_articulation_range_ratio,
        "upperBodyRootRelativeRangeRatio": upper_body_articulation_range_ratio,
        "frameCount": len(frames),
    }


def empty_motion_strength_metrics(*, body_height: float = 0.0) -> dict[str, Any]:
    return {
        "motionStrengthScore": 0.0,
        "bodyHeight": body_height,
        "rootJoint": None,
        "rootVerticalRangeRatio": 0.0,
        "rootTravelRangeRatio": 0.0,
        "maxJointRangeRatio": 0.0,
        "maxJointVerticalRangeRatio": 0.0,
        "upperJointRangeRatio": 0.0,
        "primaryMotionRangeRatio": 0.0,
        "rootRelativeArticulationRangeRatio": 0.0,
        "lowerBodyRootRelativeRangeRatio": 0.0,
        "upperBodyRootRelativeRangeRatio": 0.0,
        "frameCount": 0,
    }


def compute_source_capture_motion_strength_metrics(
    skeleton_path: Path,
    *,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> dict[str, Any]:
    payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    reference_frames = source_capture_reference_frames(
        payload,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    raw_metrics = compute_motion_strength_metrics_from_payload(payload, frames_override=reference_frames)
    kinematic_metrics = compute_kinematic_plausibility_metrics_from_payload(payload, frames_override=reference_frames)
    excluded_indices = kinematic_artifact_frame_indices(kinematic_metrics)
    if not excluded_indices:
        raw_metrics = dict(raw_metrics)
        add_source_capture_window_metadata(
            raw_metrics,
            reference_frames=reference_frames,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        )
        return raw_metrics
    if len(reference_frames) < 3:
        return raw_metrics
    filtered_frames = [
        frame
        for index, frame in enumerate(reference_frames)
        if index not in excluded_indices
    ]
    if len(filtered_frames) < 3:
        return raw_metrics
    robust_metrics = compute_motion_strength_metrics_from_payload(payload, frames_override=filtered_frames)
    if parse_optional_float(robust_metrics.get("primaryMotionRangeRatio")) is None:
        return raw_metrics
    robust_metrics = dict(robust_metrics)
    robust_metrics["sourceCaptureRawMotionStrengthMetrics"] = raw_metrics
    robust_metrics["sourceCaptureKinematicMetrics"] = kinematic_metrics
    robust_metrics["sourceCaptureExcludedFrameIndices"] = sorted(excluded_indices)
    add_source_capture_window_metadata(
        robust_metrics,
        reference_frames=reference_frames,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    return robust_metrics


def source_capture_reference_frames(
    payload: dict[str, Any],
    *,
    start_seconds: float | None,
    end_seconds: float | None,
) -> list[dict[str, Any]]:
    frames_value = payload.get("frames")
    if not isinstance(frames_value, list):
        return []
    frames = [frame for frame in frames_value if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))]
    if (
        start_seconds is None
        or end_seconds is None
        or end_seconds <= start_seconds
        or len(frames) < 3
    ):
        return frames
    has_source_times = any(parse_optional_float(frame.get("sourceTimeSec")) is not None for frame in frames)
    ranged_frames = frames_in_seconds_range(
        frames,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        use_source_time=has_source_times,
        fps=parse_export_fps(payload),
    )
    return ranged_frames if len(ranged_frames) >= 3 else frames


def add_source_capture_window_metadata(
    metrics: dict[str, Any],
    *,
    reference_frames: list[dict[str, Any]],
    start_seconds: float | None,
    end_seconds: float | None,
) -> None:
    if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
        metrics["sourceCaptureReference"] = "full_source"
        return
    metrics["sourceCaptureReference"] = "selected_source_time_range"
    metrics["sourceCaptureStartSeconds"] = start_seconds
    metrics["sourceCaptureEndSeconds"] = end_seconds
    metrics["sourceCaptureFrameCount"] = len(reference_frames)


def kinematic_artifact_frame_indices(metrics: dict[str, Any]) -> set[int]:
    if not bool(metrics.get("severeArtifact")):
        return set()
    indices: set[int] = set()
    for key in ("distalStep", "jointAngleStep"):
        section = metrics.get(key)
        if not isinstance(section, dict) or not bool(section.get("severe")):
            continue
        frame_index = parse_optional_int(section.get("frameIndex"))
        if frame_index is None:
            continue
        for offset in range(
            -KINEMATIC_SOURCE_CAPTURE_EXCLUSION_RADIUS_FRAMES,
            KINEMATIC_SOURCE_CAPTURE_EXCLUSION_RADIUS_FRAMES + 1,
        ):
            if frame_index + offset >= 0:
                indices.add(frame_index + offset)
        if frame_index > 0:
            indices.add(frame_index - 1)
    return indices


def is_lower_body_joint(joint_name: str) -> bool:
    return any(
        token in joint_name
        for token in ("hip", "knee", "ankle", "foot")
    )


def is_upper_body_joint(joint_name: str) -> bool:
    return any(
        token in joint_name
        for token in ("shoulder", "collar", "elbow", "wrist", "hand")
    )


def compute_kinematic_plausibility_metrics(skeleton_path: Path) -> dict[str, Any]:
    payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    return compute_kinematic_plausibility_metrics_from_payload(payload)


def compute_kinematic_plausibility_metrics_from_payload(
    payload: dict[str, Any],
    *,
    frames_override: list[Any] | None = None,
) -> dict[str, Any]:
    frames_value = frames_override if frames_override is not None else payload.get("frames")
    joint_names_value = payload.get("jointNames")
    if not isinstance(frames_value, list) or not isinstance(joint_names_value, list):
        return empty_kinematic_plausibility_metrics()
    frames = [frame for frame in frames_value if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))]
    if not frames:
        frames = [frame for frame in frames_value if isinstance(frame, dict)]
    joint_names = [str(name) for name in joint_names_value]
    if len(frames) < 3 or not joint_names:
        return empty_kinematic_plausibility_metrics(frame_count=len(frames))

    joint_tracks, body_height = skeleton_joint_tracks_and_body_height(frames, joint_names)
    if body_height <= 1e-6:
        return empty_kinematic_plausibility_metrics(frame_count=len(frames))

    root_joint = str(payload.get("rootJoint") or "")
    if root_joint not in joint_tracks:
        root_joint = next((joint for joint in ("pelvis", "hips", "root") if joint in joint_tracks), "")

    distal_step = compute_distal_step_spike_metrics(joint_tracks, root_joint=root_joint, body_height=body_height)
    angle_step = compute_joint_angle_step_metrics(joint_tracks)
    bone_length = compute_bone_length_instability_metrics(joint_tracks, body_height=body_height)
    reasons: list[str] = []
    if distal_step["severe"]:
        reasons.append("limb_velocity_spike_penalty")
    if angle_step["severe"]:
        reasons.append("joint_angle_spike_penalty")
    if bone_length["severe"]:
        reasons.append("bone_length_instability_penalty")

    score = min(
        float(distal_step["score"]),
        float(angle_step["score"]),
        float(bone_length["score"]),
    )
    return {
        "kinematicPlausibilityScore": score,
        "severeArtifact": bool(reasons),
        "artifactReasons": reasons,
        "bodyHeight": body_height,
        "rootJoint": root_joint or None,
        "frameCount": len(frames),
        "distalStep": distal_step,
        "jointAngleStep": angle_step,
        "boneLength": bone_length,
    }


def empty_kinematic_plausibility_metrics(*, frame_count: int = 0) -> dict[str, Any]:
    return {
        "kinematicPlausibilityScore": 1.0,
        "severeArtifact": False,
        "artifactReasons": [],
        "bodyHeight": 0.0,
        "rootJoint": None,
        "frameCount": frame_count,
        "distalStep": {
            "severe": False,
            "score": 1.0,
            "maxSeverity": 0.0,
            "maxStepRatio": 0.0,
            "maxStepBodyRatio": 0.0,
            "joint": None,
            "frameIndex": None,
        },
        "jointAngleStep": {
            "severe": False,
            "score": 1.0,
            "maxAngleStepDegrees": 0.0,
            "angle": None,
            "frameIndex": None,
        },
        "boneLength": {
            "severe": False,
            "score": 1.0,
            "maxSeverity": 0.0,
            "maxLengthVariationRatio": 0.0,
            "maxLengthVariationBodyRatio": 0.0,
            "bone": None,
        },
    }


def skeleton_joint_tracks_and_body_height(
    frames: list[dict[str, Any]],
    joint_names: list[str],
) -> tuple[dict[str, list[list[float]]], float]:
    joint_tracks: dict[str, list[list[float]]] = {joint_name: [] for joint_name in joint_names}
    frame_heights: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        frame_points: list[list[float]] = []
        if isinstance(joints, dict):
            for joint_name in joint_names:
                point = joints.get(joint_name)
                if is_point3(point):
                    point3 = [float(point[0]), float(point[1]), float(point[2])]
                    joint_tracks[joint_name].append(point3)
                    frame_points.append(point3)
        if frame_points:
            y_values = [point[1] for point in frame_points]
            frame_heights.append(max(y_values) - min(y_values))
    return joint_tracks, statistics.median(frame_heights) if frame_heights else 0.0


def compute_distal_step_spike_metrics(
    joint_tracks: dict[str, list[list[float]]],
    *,
    root_joint: str,
    body_height: float,
) -> dict[str, Any]:
    root_points = joint_tracks.get(root_joint, [])
    if not root_points:
        return {
            "severe": False,
            "score": 1.0,
            "maxStepRatio": 0.0,
            "maxStepBodyRatio": 0.0,
            "joint": None,
            "frameIndex": None,
        }
    candidates = [
        joint_name
        for joint_name in joint_tracks
        if is_distal_plausibility_joint(joint_name)
    ]
    max_step_ratio = 0.0
    max_step_body_ratio = 0.0
    max_severity = 0.0
    max_joint = None
    max_frame_index = None
    for joint_name in candidates:
        points = joint_tracks[joint_name]
        if len(points) != len(root_points) or len(points) < 3:
            continue
        relative_points = [
            [point[axis] - root_point[axis] for axis in range(3)]
            for point, root_point in zip(points, root_points)
        ]
        steps = [
            point_distance(relative_points[index], relative_points[index - 1])
            for index in range(1, len(relative_points))
        ]
        positive_steps = [step for step in steps if step > 1e-7]
        if len(positive_steps) < 2:
            continue
        median_step = statistics.median(positive_steps)
        if median_step <= 1e-7:
            continue
        for index, step in enumerate(steps, start=1):
            step_ratio = step / median_step
            step_body_ratio = step / body_height
            severity = min(
                step_ratio / KINEMATIC_DISTAL_STEP_SPIKE_RATIO,
                step_body_ratio / KINEMATIC_DISTAL_STEP_BODY_RATIO,
            )
            if severity > max_severity:
                max_severity = severity
                max_step_ratio = step_ratio
                max_step_body_ratio = step_body_ratio
                max_joint = joint_name
                max_frame_index = index
    severe = max_severity >= 1.0
    score = clamp_unit(1.0 / max(max_severity, 1.0))
    return {
        "severe": severe,
        "score": score,
        "maxSeverity": max_severity,
        "maxStepRatio": max_step_ratio,
        "maxStepBodyRatio": max_step_body_ratio,
        "joint": max_joint,
        "frameIndex": max_frame_index,
        "ratioThreshold": KINEMATIC_DISTAL_STEP_SPIKE_RATIO,
        "bodyRatioThreshold": KINEMATIC_DISTAL_STEP_BODY_RATIO,
    }


def compute_joint_angle_step_metrics(joint_tracks: dict[str, list[list[float]]]) -> dict[str, Any]:
    max_angle_step = 0.0
    max_angle_name = None
    max_frame_index = None
    for angle_name, start_joint, mid_joint, end_joint in kinematic_angle_specs():
        start_points = joint_tracks.get(start_joint, [])
        mid_points = joint_tracks.get(mid_joint, [])
        end_points = joint_tracks.get(end_joint, [])
        if not (len(start_points) == len(mid_points) == len(end_points)) or len(mid_points) < 3:
            continue
        angles = [
            joint_angle_degrees(start, mid, end)
            for start, mid, end in zip(start_points, mid_points, end_points)
        ]
        for index in range(1, len(angles)):
            if angles[index] is None or angles[index - 1] is None:
                continue
            angle_step = abs(float(angles[index]) - float(angles[index - 1]))
            if angle_step > max_angle_step:
                max_angle_step = angle_step
                max_angle_name = angle_name
                max_frame_index = index
    severe = max_angle_step >= KINEMATIC_ANGLE_STEP_DEGREES
    score = clamp_unit(KINEMATIC_ANGLE_STEP_DEGREES / max(max_angle_step, KINEMATIC_ANGLE_STEP_DEGREES))
    return {
        "severe": severe,
        "score": score,
        "maxAngleStepDegrees": max_angle_step,
        "angle": max_angle_name,
        "frameIndex": max_frame_index,
        "thresholdDegrees": KINEMATIC_ANGLE_STEP_DEGREES,
    }


def compute_bone_length_instability_metrics(
    joint_tracks: dict[str, list[list[float]]],
    *,
    body_height: float,
) -> dict[str, Any]:
    max_variation_ratio = 0.0
    max_variation_body_ratio = 0.0
    max_severity = 0.0
    max_bone = None
    for start_joint, end_joint in kinematic_bone_specs():
        start_points = joint_tracks.get(start_joint, [])
        end_points = joint_tracks.get(end_joint, [])
        if len(start_points) != len(end_points) or len(start_points) < 2:
            continue
        lengths = [
            point_distance(start, end)
            for start, end in zip(start_points, end_points)
        ]
        median_length = statistics.median(lengths)
        if median_length <= 1e-7:
            continue
        length_variation = max(lengths) - min(lengths)
        variation_ratio = length_variation / median_length
        variation_body_ratio = length_variation / body_height
        severity = min(
            variation_ratio / KINEMATIC_BONE_LENGTH_VARIATION_RATIO,
            variation_body_ratio / KINEMATIC_BONE_LENGTH_BODY_RATIO,
        )
        if severity > max_severity:
            max_severity = severity
            max_variation_ratio = variation_ratio
            max_variation_body_ratio = variation_body_ratio
            max_bone = f"{start_joint}:{end_joint}"
    severe = max_severity >= 1.0
    score = clamp_unit(1.0 / max(max_severity, 1.0))
    return {
        "severe": severe,
        "score": score,
        "maxSeverity": max_severity,
        "maxLengthVariationRatio": max_variation_ratio,
        "maxLengthVariationBodyRatio": max_variation_body_ratio,
        "bone": max_bone,
        "ratioThreshold": KINEMATIC_BONE_LENGTH_VARIATION_RATIO,
        "bodyRatioThreshold": KINEMATIC_BONE_LENGTH_BODY_RATIO,
    }


def is_distal_plausibility_joint(joint_name: str) -> bool:
    return any(
        joint_name.endswith(suffix)
        for suffix in ("_knee", "_ankle", "_foot", "_elbow", "_wrist", "_hand")
    )


def kinematic_angle_specs() -> tuple[tuple[str, str, str, str], ...]:
    return (
        ("left_knee", "left_hip", "left_knee", "left_ankle"),
        ("right_knee", "right_hip", "right_knee", "right_ankle"),
        ("left_ankle", "left_knee", "left_ankle", "left_foot"),
        ("right_ankle", "right_knee", "right_ankle", "right_foot"),
        ("left_elbow", "left_shoulder", "left_elbow", "left_wrist"),
        ("right_elbow", "right_shoulder", "right_elbow", "right_wrist"),
    )


def kinematic_bone_specs() -> tuple[tuple[str, str], ...]:
    return (
        ("left_hip", "left_knee"),
        ("left_knee", "left_ankle"),
        ("left_ankle", "left_foot"),
        ("right_hip", "right_knee"),
        ("right_knee", "right_ankle"),
        ("right_ankle", "right_foot"),
        ("left_shoulder", "left_elbow"),
        ("left_elbow", "left_wrist"),
        ("left_wrist", "left_hand"),
        ("right_shoulder", "right_elbow"),
        ("right_elbow", "right_wrist"),
        ("right_wrist", "right_hand"),
    )


def joint_angle_degrees(
    start: list[float],
    mid: list[float],
    end: list[float],
) -> float | None:
    start_vector = [start[axis] - mid[axis] for axis in range(3)]
    end_vector = [end[axis] - mid[axis] for axis in range(3)]
    start_length = point_length(start_vector)
    end_length = point_length(end_vector)
    if start_length <= 1e-9 or end_length <= 1e-9:
        return None
    alignment = sum(start_vector[axis] * end_vector[axis] for axis in range(3)) / (start_length * end_length)
    return math.degrees(math.acos(max(-1.0, min(1.0, alignment))))


def point_distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((left[axis] - right[axis]) ** 2 for axis in range(3)))


def point_length(point: list[float]) -> float:
    return math.sqrt(sum(component * component for component in point))


def point_track_range(points: list[list[float]]) -> float:
    if len(points) < 2:
        return 0.0
    ranges = [
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    ]
    return math.sqrt(sum(axis_range * axis_range for axis_range in ranges))


def horizontal_track_range(points: list[list[float]]) -> float:
    if len(points) < 2:
        return 0.0
    range_x = max(point[0] for point in points) - min(point[0] for point in points)
    range_z = max(point[2] for point in points) - min(point[2] for point in points)
    return math.hypot(range_x, range_z)


def principal_horizontal_direction(points: list[list[float]]) -> tuple[float, float] | None:
    if len(points) < 3:
        return None
    mean_x = sum(point[0] for point in points) / len(points)
    mean_z = sum(point[2] for point in points) / len(points)
    xx = sum((point[0] - mean_x) ** 2 for point in points)
    zz = sum((point[2] - mean_z) ** 2 for point in points)
    xz = sum((point[0] - mean_x) * (point[2] - mean_z) for point in points)
    if xx + zz <= 1e-9:
        return None
    angle = 0.5 * math.atan2(2.0 * xz, xx - zz)
    axis = (math.cos(angle), math.sin(angle))
    displacement = (points[-1][0] - points[0][0], points[-1][2] - points[0][2])
    if axis[0] * displacement[0] + axis[1] * displacement[1] < 0.0:
        axis = (-axis[0], -axis[1])
    return axis


def camera_projected_horizontal_ranges(
    points: list[list[float]],
    *,
    camera_yaw_degrees: float,
) -> tuple[float, float]:
    if len(points) < 2:
        return 0.0, 0.0
    yaw = math.radians(camera_yaw_degrees)
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    screen_values = [
        point[0] * cos_yaw - point[2] * sin_yaw
        for point in points
    ]
    depth_values = [
        point[0] * sin_yaw + point[2] * cos_yaw
        for point in points
    ]
    return (
        max(screen_values) - min(screen_values),
        max(depth_values) - min(depth_values),
    )


def evaluate_baked_motion_gate(skeleton_path: Path) -> dict[str, Any]:
    metrics = compute_motion_strength_metrics(skeleton_path)
    if int(metrics.get("frameCount") or 0) < 2:
        return {
            "passed": True,
            "reasons": ["baked_motion_gate_skipped_no_frame_metrics"],
            "motionStrengthScore": float(metrics["motionStrengthScore"]),
            "primaryMotionRangeRatio": float(metrics["primaryMotionRangeRatio"]),
            "metrics": metrics,
        }
    motion_score = float(metrics["motionStrengthScore"])
    primary_range = float(metrics["primaryMotionRangeRatio"])
    passed = (
        motion_score >= BAKED_MOTION_MIN_STRENGTH_SCORE
        or primary_range >= BAKED_MOTION_MIN_PRIMARY_RANGE_RATIO
    )
    reasons = [] if passed else ["baked_motion_too_static"]
    return {
        "passed": passed,
        "reasons": reasons,
        "motionStrengthScore": motion_score,
        "primaryMotionRangeRatio": primary_range,
        "metrics": metrics,
    }


def compute_loop_continuity_metrics(skeleton_path: Path) -> dict[str, Any]:
    payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    return compute_loop_continuity_metrics_from_payload(payload)


def compute_loop_continuity_metrics_from_payload(
    payload: dict[str, Any],
    *,
    frames_override: list[Any] | None = None,
) -> dict[str, Any]:
    frames = frames_override if frames_override is not None else payload.get("frames")
    joint_names = payload.get("jointNames")
    if not isinstance(frames, list) or len(frames) < 2 or not isinstance(joint_names, list):
        return {
            "continuityScore": 0.0,
            "seamAverageDistance": None,
            "seamMaxDistance": None,
            "medianFrameStepDistance": None,
            "seamToMedianStepRatio": None,
        }

    seam_distances = joint_distances_between_frames(frames[-1], frames[0], joint_names)
    frame_step_averages = [
        sum(distances) / len(distances)
        for distances in (
            joint_distances_between_frames(left, right, joint_names)
            for left, right in zip(frames, frames[1:])
        )
        if distances
    ]
    if not seam_distances or not frame_step_averages:
        return {
            "continuityScore": 0.0,
            "seamAverageDistance": None,
            "seamMaxDistance": None,
            "medianFrameStepDistance": None,
            "seamToMedianStepRatio": None,
        }
    seam_average = sum(seam_distances) / len(seam_distances)
    seam_max = max(seam_distances)
    median_step = statistics.median(frame_step_averages)
    seam_ratio = seam_average / max(1e-6, median_step)
    average_score = clamp_unit(1.0 - seam_ratio / 1.2)
    max_score = clamp_unit(1.0 - max(0.0, seam_max - 0.02) / 0.06)
    continuity_score = clamp_unit(max_score * 0.65 + average_score * 0.35)
    return {
        "continuityScore": continuity_score,
        "seamAverageDistance": seam_average,
        "seamMaxDistance": seam_max,
        "medianFrameStepDistance": median_step,
        "seamToMedianStepRatio": seam_ratio,
    }


def compute_loop_bridge_quality_metrics(skeleton_path: Path) -> dict[str, Any]:
    payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    return compute_loop_bridge_quality_metrics_from_payload(payload)


def compute_loop_bridge_quality_metrics_from_payload(
    payload: dict[str, Any],
    *,
    frames_override: list[Any] | None = None,
) -> dict[str, Any]:
    frames_value = frames_override if frames_override is not None else payload.get("frames")
    joint_names_value = payload.get("jointNames")
    if not isinstance(frames_value, list) or not isinstance(joint_names_value, list):
        return empty_loop_bridge_quality_metrics()
    frames = [frame for frame in frames_value if isinstance(frame, dict)]
    joint_names = [str(name) for name in joint_names_value]
    if len(frames) < 2 or not joint_names:
        return empty_loop_bridge_quality_metrics(frame_count=len(frames))

    real_entries = [
        (index, frame)
        for index, frame in enumerate(frames)
        if not bool(frame.get("syntheticLoopBridge"))
    ]
    if len(real_entries) < 2:
        return empty_loop_bridge_quality_metrics(frame_count=len(frames))

    real_frames = [frame for _index, frame in real_entries]
    _joint_tracks, body_height = skeleton_joint_tracks_and_body_height(real_frames, joint_names)
    if body_height <= 1e-6:
        return empty_loop_bridge_quality_metrics(frame_count=len(frames))

    first_real = real_entries[0][1]
    last_real_index, last_real = real_entries[-1]
    endpoint_pairs = joint_distance_pairs_between_frames(last_real, first_real, joint_names)
    if not endpoint_pairs:
        return empty_loop_bridge_quality_metrics(frame_count=len(frames))

    endpoint_average = sum(distance for _joint, distance in endpoint_pairs) / len(endpoint_pairs)
    endpoint_joint, endpoint_max = max(endpoint_pairs, key=lambda item: item[1])
    endpoint_body_ratio = endpoint_max / body_height

    real_step_max_distances = [
        max(distances) if distances else 0.0
        for distances in (
            joint_distances_between_frames(left, right, joint_names)
            for left, right in zip(real_frames, real_frames[1:])
        )
    ]
    positive_real_step_max_distances = [
        distance for distance in real_step_max_distances if distance > 1e-7
    ]
    median_real_max_step = (
        statistics.median(positive_real_step_max_distances)
        if positive_real_step_max_distances
        else None
    )

    trailing_bridge_frames = [
        frame
        for frame in frames[last_real_index + 1 :]
        if bool(frame.get("syntheticLoopBridge"))
    ]
    bridge_path = [last_real, *trailing_bridge_frames, first_real]
    bridge_max_step = 0.0
    bridge_joint = None
    bridge_step_index = None
    for index, (left, right) in enumerate(zip(bridge_path, bridge_path[1:]), start=1):
        step_pairs = joint_distance_pairs_between_frames(left, right, joint_names)
        if not step_pairs:
            continue
        joint_name, distance = max(step_pairs, key=lambda item: item[1])
        if distance > bridge_max_step:
            bridge_max_step = distance
            bridge_joint = joint_name
            bridge_step_index = index
    bridge_step_body_ratio = bridge_max_step / body_height
    bridge_step_ratio = (
        bridge_max_step / median_real_max_step
        if median_real_max_step is not None and median_real_max_step > 1e-7
        else None
    )

    endpoint_severity = endpoint_body_ratio / LOOP_BRIDGE_ENDPOINT_BODY_RATIO
    bridge_step_ratio_severity = (
        bridge_step_ratio / LOOP_BRIDGE_STEP_RATIO
        if bridge_step_ratio is not None
        else 0.0
    )
    bridge_step_body_severity = (
        bridge_step_body_ratio / LOOP_BRIDGE_STEP_BODY_RATIO
        if trailing_bridge_frames
        else 0.0
    )
    max_severity = max(endpoint_severity, bridge_step_ratio_severity, bridge_step_body_severity)
    severe = max_severity >= 1.0
    return {
        "loopBridgeQualityScore": clamp_unit(1.0 / max(max_severity, 1.0)),
        "severeLoopMismatch": severe,
        "frameCount": len(frames),
        "realFrameCount": len(real_frames),
        "bridgeFrameCount": len(trailing_bridge_frames),
        "bodyHeight": body_height,
        "endpointAverageDistance": endpoint_average,
        "endpointMaxDistance": endpoint_max,
        "endpointMaxDistanceBodyRatio": endpoint_body_ratio,
        "endpointJoint": endpoint_joint,
        "endpointBodyRatioThreshold": LOOP_BRIDGE_ENDPOINT_BODY_RATIO,
        "medianRealMaxStepDistance": median_real_max_step,
        "bridgeMaxStepDistance": bridge_max_step,
        "bridgeMaxStepBodyRatio": bridge_step_body_ratio,
        "bridgeMaxStepRatio": bridge_step_ratio,
        "bridgeJoint": bridge_joint,
        "bridgeStepIndex": bridge_step_index,
        "bridgeStepRatioThreshold": LOOP_BRIDGE_STEP_RATIO,
        "bridgeStepBodyRatioThreshold": LOOP_BRIDGE_STEP_BODY_RATIO,
        "maxSeverity": max_severity,
    }


def compute_preview_readability_metrics(
    skeleton_path: Path,
    *,
    camera_yaw_degrees: float = 45.0,
) -> dict[str, Any]:
    payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    return compute_preview_readability_metrics_from_payload(
        payload,
        camera_yaw_degrees=camera_yaw_degrees,
    )


def compute_preview_readability_metrics_from_payload(
    payload: dict[str, Any],
    *,
    frames_override: list[Any] | None = None,
    camera_yaw_degrees: float = 45.0,
) -> dict[str, Any]:
    frames_value = frames_override if frames_override is not None else payload.get("frames")
    joint_names_value = payload.get("jointNames")
    if not isinstance(frames_value, list) or not isinstance(joint_names_value, list):
        return empty_preview_readability_metrics()
    frames = [
        frame
        for frame in frames_value
        if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))
    ]
    joint_names = [str(name) for name in joint_names_value]
    if len(frames) < 3 or not joint_names:
        return empty_preview_readability_metrics(frame_count=len(frames))
    joint_tracks, body_height = skeleton_joint_tracks_and_body_height(frames, joint_names)
    if body_height <= 1e-6:
        return empty_preview_readability_metrics(frame_count=len(frames))
    root_points = joint_tracks.get("pelvis", [])
    candidates: list[tuple[float, str, list[list[float]]]] = []
    for joint_name, points in joint_tracks.items():
        if len(points) < 3:
            continue
        if len(root_points) == len(points) and joint_name != "pelvis":
            relative_points = [
                [point[axis] - root_point[axis] for axis in range(3)]
                for point, root_point in zip(points, root_points)
            ]
        else:
            relative_points = points
        horizontal_range = horizontal_track_range(relative_points)
        total_range = point_track_range(relative_points)
        if horizontal_range <= 1e-7 and total_range <= 1e-7:
            continue
        candidates.append((max(horizontal_range, total_range), joint_name, relative_points))
    if not candidates:
        return empty_preview_readability_metrics(frame_count=len(frames), body_height=body_height)
    _range, joint_name, points = max(candidates, key=lambda item: item[0])
    horizontal_range = horizontal_track_range(points)
    total_range = point_track_range(points)
    axis = principal_horizontal_direction(points)
    axis_alignment = max(abs(axis[0]), abs(axis[1])) if axis is not None else 0.0
    screen_range, depth_range = camera_projected_horizontal_ranges(
        points,
        camera_yaw_degrees=camera_yaw_degrees,
    )
    projected_total = screen_range + depth_range
    screen_motion_share = screen_range / projected_total if projected_total > 1e-7 else 0.0
    screen_motion_score = clamp_unit((screen_motion_share - 0.42) / 0.23)
    horizontal_motion_ratio = horizontal_range / body_height
    horizontal_motion_score = clamp_unit(horizontal_motion_ratio / 0.18)
    preview_readability_score = clamp_unit(
        0.50 * screen_motion_score
        + 0.30 * axis_alignment
        + 0.20 * horizontal_motion_score
    )
    return {
        "previewReadabilityScore": preview_readability_score,
        "frameCount": len(frames),
        "bodyHeight": body_height,
        "dominantJoint": joint_name,
        "horizontalRange": horizontal_range,
        "horizontalRangeBodyRatio": horizontal_motion_ratio,
        "totalRange": total_range,
        "totalRangeBodyRatio": total_range / body_height,
        "axisAlignmentScore": axis_alignment,
        "dominantHorizontalAxis": None if axis is None else [axis[0], axis[1]],
        "screenMotionRange": screen_range,
        "depthMotionRange": depth_range,
        "screenMotionShare": screen_motion_share,
        "screenMotionScore": screen_motion_score,
        "cameraYawDegrees": camera_yaw_degrees,
    }


def empty_preview_readability_metrics(*, frame_count: int = 0, body_height: float = 0.0) -> dict[str, Any]:
    return {
        "previewReadabilityScore": 0.5,
        "frameCount": frame_count,
        "bodyHeight": body_height,
        "dominantJoint": None,
        "horizontalRange": 0.0,
        "horizontalRangeBodyRatio": 0.0,
        "totalRange": 0.0,
        "totalRangeBodyRatio": 0.0,
        "axisAlignmentScore": 0.0,
        "dominantHorizontalAxis": None,
        "screenMotionRange": 0.0,
        "depthMotionRange": 0.0,
        "screenMotionShare": 0.0,
        "screenMotionScore": 0.0,
        "cameraYawDegrees": 45.0,
    }


def select_review_windows_by_skeleton_motion(
    item: ReviewItem,
    windows: list[DetectionWindow],
    *,
    max_windows: int,
) -> list[ReviewWindowCandidate]:
    if not windows:
        return []
    candidates = score_review_windows_by_skeleton_motion(item, windows)
    if max_windows > 0:
        candidates = candidates[:max_windows]
    if not candidates:
        return [
            ReviewWindowCandidate(
                video_window=window,
                timeline_window=timeline_window_for_video_window(item, window),
                score=0.0,
                motion_metrics=empty_motion_strength_metrics(),
                continuity_metrics=empty_loop_continuity_metrics(),
                kinematic_metrics=empty_kinematic_plausibility_metrics(),
            )
            for window in windows[:max(1, max_windows)]
        ]
    return candidates


def score_review_windows_by_skeleton_motion(
    item: ReviewItem,
    windows: list[DetectionWindow],
) -> list[ReviewWindowCandidate]:
    try:
        payload = json.loads(item.skeleton_path.read_text(encoding="utf-8"))
    except Exception:
        return [
            ReviewWindowCandidate(
                video_window=window,
                timeline_window=timeline_window_for_video_window(item, window),
                score=0.0,
                motion_metrics=empty_motion_strength_metrics(),
                continuity_metrics=empty_loop_continuity_metrics(),
                kinematic_metrics=empty_kinematic_plausibility_metrics(),
            )
            for window in windows
        ]

    scored: list[ReviewWindowCandidate] = []
    for window in windows:
        timeline_window = timeline_window_for_video_window(item, window)
        frames = skeleton_frames_for_review_window(
            payload,
            video_window=window,
            timeline_window=timeline_window,
        )
        motion_metrics = compute_motion_strength_metrics_from_payload(payload, frames_override=frames)
        continuity_metrics = compute_loop_continuity_metrics_from_payload(payload, frames_override=frames)
        kinematic_metrics = compute_kinematic_plausibility_metrics_from_payload(payload, frames_override=frames)
        loop_bridge_metrics = compute_loop_bridge_quality_metrics_from_payload(payload, frames_override=frames)
        preview_readability_metrics = compute_preview_readability_metrics_from_payload(
            payload,
            frames_override=frames,
            camera_yaw_degrees=parse_optional_float(item.settings_options.get("cameraYawDegrees")) or 45.0,
        )
        motion_score = float(motion_metrics["motionStrengthScore"])
        continuity_score = float(continuity_metrics["continuityScore"])
        kinematic_score = float(kinematic_metrics["kinematicPlausibilityScore"])
        preview_readability_score = float(preview_readability_metrics["previewReadabilityScore"])
        loopability_score = min(
            continuity_score,
            float(loop_bridge_metrics["loopBridgeQualityScore"]),
        )
        score = clamp_unit(
            motion_score * WINDOW_MOTION_SCORE_WEIGHT
            + loopability_score * WINDOW_CONTINUITY_SCORE_WEIGHT
        )
        score = clamp_unit(
            score
            + (preview_readability_score - 0.5) * PREVIEW_READABILITY_SCORE_WEIGHT
        )
        score = min(score, kinematic_score)
        if loopability_score < WINDOW_MIN_LOOPABILITY_SCORE or bool(loop_bridge_metrics.get("severeLoopMismatch")):
            score = min(score, WINDOW_LOW_LOOPABILITY_SCORE_CAP)
        scored.append(
            ReviewWindowCandidate(
                video_window=window,
                timeline_window=timeline_window,
                score=score,
                motion_metrics=motion_metrics,
                continuity_metrics=continuity_metrics,
                kinematic_metrics=kinematic_metrics,
                loop_bridge_quality_metrics=loop_bridge_metrics,
                preview_readability_metrics=preview_readability_metrics,
            )
        )
    return sorted(
        scored,
        key=lambda candidate: (
            candidate.score,
            float(candidate.motion_metrics["primaryMotionRangeRatio"]),
            -candidate.video_window.index,
        ),
        reverse=True,
    )


def timeline_window_for_video_window(item: ReviewItem, window: DetectionWindow) -> DetectionWindow:
    source_start = max(0.0, item.loop_start_seconds)
    return DetectionWindow(
        index=window.index,
        start_seconds=source_start + window.start_seconds,
        end_seconds=source_start + window.end_seconds,
    )


def skeleton_frames_for_review_window(
    payload: dict[str, Any],
    *,
    video_window: DetectionWindow,
    timeline_window: DetectionWindow,
) -> list[Any]:
    frames_value = payload.get("frames")
    if not isinstance(frames_value, list):
        return []
    frames = [frame for frame in frames_value if isinstance(frame, dict)]
    if not frames:
        return []

    has_source_times = any(parse_optional_float(frame.get("sourceTimeSec")) is not None for frame in frames)
    if has_source_times:
        timeline_frames = frames_in_seconds_range(
            frames,
            start_seconds=timeline_window.start_seconds,
            end_seconds=timeline_window.end_seconds,
            use_source_time=True,
            fps=parse_export_fps(payload),
        )
        if len(timeline_frames) >= 2:
            return timeline_frames

    video_frames = frames_in_seconds_range(
        frames,
        start_seconds=video_window.start_seconds,
        end_seconds=video_window.end_seconds,
        use_source_time=has_source_times,
        fps=parse_export_fps(payload),
    )
    return video_frames if len(video_frames) >= 2 else frames


def frames_in_seconds_range(
    frames: list[dict[str, Any]],
    *,
    start_seconds: float,
    end_seconds: float,
    use_source_time: bool,
    fps: float,
) -> list[Any]:
    selected: list[Any] = []
    effective_fps = fps if fps > 0 else 30.0
    for fallback_index, frame in enumerate(frames):
        if bool(frame.get("syntheticLoopBridge")):
            continue
        frame_seconds = (
            parse_optional_float(frame.get("sourceTimeSec"))
            if use_source_time
            else None
        )
        if frame_seconds is None:
            frame_index = parse_optional_float(frame.get("frameIndex"))
            frame_seconds = (frame_index if frame_index is not None else fallback_index) / effective_fps
        if start_seconds - 1e-6 <= frame_seconds <= end_seconds + 1e-6:
            selected.append(frame)
    return selected


def empty_loop_continuity_metrics() -> dict[str, Any]:
    return {
        "continuityScore": 0.0,
        "seamAverageDistance": None,
        "seamMaxDistance": None,
        "medianFrameStepDistance": None,
        "seamToMedianStepRatio": None,
    }


def empty_loop_bridge_quality_metrics(*, frame_count: int = 0) -> dict[str, Any]:
    return {
        "loopBridgeQualityScore": 1.0,
        "severeLoopMismatch": False,
        "frameCount": frame_count,
        "realFrameCount": 0,
        "bridgeFrameCount": 0,
        "bodyHeight": 0.0,
        "endpointAverageDistance": None,
        "endpointMaxDistance": None,
        "endpointMaxDistanceBodyRatio": None,
        "endpointJoint": None,
        "endpointBodyRatioThreshold": LOOP_BRIDGE_ENDPOINT_BODY_RATIO,
        "medianRealMaxStepDistance": None,
        "bridgeMaxStepDistance": None,
        "bridgeMaxStepBodyRatio": None,
        "bridgeMaxStepRatio": None,
        "bridgeJoint": None,
        "bridgeStepIndex": None,
        "bridgeStepRatioThreshold": LOOP_BRIDGE_STEP_RATIO,
        "bridgeStepBodyRatioThreshold": LOOP_BRIDGE_STEP_BODY_RATIO,
        "maxSeverity": 0.0,
    }


def joint_distances_between_frames(left: dict[str, Any], right: dict[str, Any], joint_names: list[Any]) -> list[float]:
    return [
        distance
        for _joint_name, distance in joint_distance_pairs_between_frames(left, right, joint_names)
    ]


def joint_distance_pairs_between_frames(left: dict[str, Any], right: dict[str, Any], joint_names: list[Any]) -> list[tuple[str, float]]:
    left_joints = left.get("joints") if isinstance(left, dict) else None
    right_joints = right.get("joints") if isinstance(right, dict) else None
    if not isinstance(left_joints, dict) or not isinstance(right_joints, dict):
        return []
    distances: list[tuple[str, float]] = []
    for joint_name_value in joint_names:
        joint_name = str(joint_name_value)
        left_point = left_joints.get(joint_name)
        right_point = right_joints.get(joint_name)
        if not is_point3(left_point) or not is_point3(right_point):
            continue
        distances.append((joint_name, math.dist(left_point[:3], right_point[:3])))
    return distances


def is_point3(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 3 and all(isinstance(item, (int, float)) for item in value[:3])


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def elapsed_seconds(start_time: float) -> float:
    return round(time.perf_counter() - start_time, 3)


def record_timing_seconds(payload: dict[str, Any], name: str, start_time: float) -> None:
    timings = payload.setdefault("timings", {})
    if isinstance(timings, dict):
        timings[name] = elapsed_seconds(start_time)


def build_vision_client_settings(request: BakeAndRankRequest) -> YouTubeRankingSettings:
    return YouTubeRankingSettings(
    )


def run_bake_and_rank_pipeline(
    request: BakeAndRankRequest,
    *,
    preview_baker: PreviewBaker | None = None,
    loop_ranker: LoopRanker | None = None,
) -> dict[str, Any]:
    pipeline_started = time.perf_counter()
    pipeline_timings: dict[str, Any] = {}
    candidates = load_ranked_candidates_manifest(request.candidates_json)
    request.workspace.mkdir(parents=True, exist_ok=True)
    candidate_results: list[dict[str, Any]] = []
    review_items: list[ReviewItem] = []
    review_item_entries: list[dict[str, Any]] = []
    if preview_baker is None:
        preview_baker = lambda preview_html_path, eligible_loops, candidate_workspace, review_frames: bake_preview_loops_with_playwright(
            preview_html_path,
            eligible_loops,
            candidate_workspace,
            review_frames,
            rank_preview_variants=request.rank_preview_variants,
        )
    effective_ranker = None
    if section_selection_enabled(request):
        effective_ranker = loop_ranker or rank_review_items_with_llama_cpp
    vision_ranker: LlamaCppVisionRanker | None = None
    support_dominance_classifier = None
    try:
        if loop_ranker is None and (request.classify_support_dominance or section_selection_enabled(request)):
            stage_started = time.perf_counter()
            vision_ranker = LlamaCppVisionRanker(build_llama_cpp_vision_settings(request))
            pipeline_timings["visionRankerStartupSeconds"] = elapsed_seconds(stage_started)
        if request.classify_support_dominance and vision_ranker is not None:
            support_dominance_classifier = vision_ranker.client.caption_images
        if section_selection_enabled(request) and loop_ranker is None and vision_ranker is not None:
            effective_ranker = lambda items, active_request: rank_review_items_with_llama_cpp(
                items,
                active_request,
                caption_images=vision_ranker.client.caption_images,
            )
        candidate_processing_started = time.perf_counter()
        candidate_results, review_items, review_item_entries = process_ranked_candidates_for_selection(
            candidates,
            request=request,
            preview_baker=preview_baker,
            support_dominance_classifier=support_dominance_classifier,
        )
        pipeline_timings["candidateProcessingSeconds"] = elapsed_seconds(candidate_processing_started)

        rankings: list[LoopRanking] = []
        selected: SelectedArtifact | None = None
        rejected_best: SelectedArtifact | None = None
        if review_items:
            if effective_ranker is None:
                rankings = [LoopRanking(score=1.0, reasons=["ranking_skipped"]) for _ in review_items]
                selected = (review_items[0], None)
            else:
                stage_started = time.perf_counter()
                rankings = effective_ranker(review_items, request)
                pipeline_timings["reviewRankingSeconds"] = elapsed_seconds(stage_started)
            stage_started = time.perf_counter()
            selected, rejected_best = choose_best_materialized_review_item(
                review_items,
                rankings,
                request=request,
            )
            pipeline_timings["selectionMaterializationSeconds"] = elapsed_seconds(stage_started)
    finally:
        if vision_ranker is not None:
            stage_started = time.perf_counter()
            vision_ranker.close()
            pipeline_timings["visionRankerCloseSeconds"] = elapsed_seconds(stage_started)

    manifest_started = time.perf_counter()
    ranked_review_entries = []
    for index, entry in enumerate(review_item_entries):
        ranking = rankings[index] if index < len(rankings) else None
        ranked_review_entries.append(
            {
                **entry,
                "ranking": None if ranking is None else ranking_to_manifest(ranking),
            }
        )
    write_candidate_ranking_manifests(ranked_review_entries)
    selected_preview_path = write_selected_section_preview_html(request.workspace, selected)

    selection_manifest = build_selection_manifest(
        request=request,
        candidate_results=candidate_results,
        review_entries=ranked_review_entries,
        selected=selected,
        rejected_best=rejected_best,
    )
    pipeline_timings["manifestBuildSeconds"] = elapsed_seconds(manifest_started)
    pipeline_timings["totalSeconds"] = elapsed_seconds(pipeline_started)
    selection_manifest["timings"] = pipeline_timings
    if selected_preview_path is not None:
        selection_manifest["selectedPreviewHtmlPath"] = str(selected_preview_path)
    selection_path = request.workspace / "selection_manifest.json"
    selection_path.write_text(json.dumps(selection_manifest, indent=2), encoding="utf-8")
    return selection_manifest


def run_bake_and_rank_reselection(
    *,
    workspace: Path,
    min_selected_score: float | None = None,
    review_frames: int | None = None,
    max_review_windows: int | None = None,
) -> dict[str, Any]:
    selection_path = workspace / "selection_manifest.json"
    if not selection_path.exists():
        raise FileNotFoundError(f"Selection manifest not found: {selection_path}")
    existing_manifest = json.loads(selection_path.read_text(encoding="utf-8"))
    request = bake_and_rank_request_from_selection_manifest(
        existing_manifest,
        workspace=workspace,
        min_selected_score=min_selected_score,
        review_frames=review_frames,
        max_review_windows=max_review_windows,
    )
    review_entries = existing_manifest.get("reviewItems")
    if not isinstance(review_entries, list):
        raise ValueError(f"Selection manifest has no reviewItems list: {selection_path}")

    review_items: list[ReviewItem] = []
    rankings: list[LoopRanking] = []
    ranked_review_entries: list[dict[str, Any]] = []
    for entry in review_entries:
        if not isinstance(entry, dict):
            continue
        ranking_payload = entry.get("ranking")
        ranking = ranking_from_manifest(ranking_payload) if isinstance(ranking_payload, dict) else None
        if ranking is None:
            ranked_review_entries.append(entry)
            continue
        item = review_item_from_manifest(entry)
        review_items.append(item)
        rankings.append(ranking)
        ranked_review_entries.append({**entry, "ranking": ranking_to_manifest(ranking)})

    for selected_key in ("selected", "rejectedBest"):
        selected_payload = existing_manifest.get(selected_key)
        if not isinstance(selected_payload, dict):
            continue
        ranking_payload = selected_payload.get("ranking")
        if not isinstance(ranking_payload, dict):
            continue
        ranking = ranking_from_manifest(ranking_payload)
        review_items.append(review_item_from_manifest(selected_payload))
        rankings.append(ranking)

    if not review_items:
        raise ValueError(f"Selection manifest has no ranked review items to reselect: {selection_path}")

    adjusted_rankings = [
        apply_loop_continuity_adjustment(item, ranking)
        for item, ranking in zip(review_items, rankings)
    ]
    selected = choose_best_review_item(
        review_items,
        adjusted_rankings,
        min_score=request.min_selected_score,
    )
    rejected_best = None
    if selected is None:
        rejected_best = choose_best_review_item(
            review_items,
            adjusted_rankings,
            min_score=0.0,
        )
    write_candidate_ranking_manifests(ranked_review_entries)
    selected_preview_path = write_selected_section_preview_html(workspace, selected)
    reselection_manifest = build_selection_manifest(
        request=request,
        candidate_results=existing_manifest.get("candidateResults") if isinstance(existing_manifest.get("candidateResults"), list) else [],
        review_entries=ranked_review_entries,
        selected=selected,
        rejected_best=rejected_best,
    )
    reselection_manifest["reselectedFromManifest"] = str(selection_path)
    reselection_manifest["previousGeneratedAt"] = existing_manifest.get("generatedAt")
    if selected_preview_path is not None:
        reselection_manifest["selectedPreviewHtmlPath"] = str(selected_preview_path)
    selection_path.write_text(json.dumps(reselection_manifest, indent=2), encoding="utf-8")
    return reselection_manifest


def bake_and_rank_request_from_selection_manifest(
    manifest: dict[str, Any],
    *,
    workspace: Path,
    min_selected_score: float | None,
    review_frames: int | None,
    max_review_windows: int | None,
) -> BakeAndRankRequest:
    source_candidates = manifest.get("sourceCandidatesJson")
    candidates_json = Path(str(source_candidates)) if source_candidates else workspace / "youtube_candidates.json"
    return BakeAndRankRequest(
        candidates_json=candidates_json,
        workspace=workspace,
        wham_repo_path=None,
        body_model_root=None,
        review_frames=review_frames if review_frames is not None else DEFAULT_REVIEW_FRAMES,
        max_review_windows=max_review_windows
        if max_review_windows is not None
        else int(manifest.get("maxReviewWindows") or DEFAULT_MAX_REVIEW_WINDOWS),
        max_loop_seconds=float(manifest.get("maxLoopSeconds") or DEFAULT_MAX_LOOP_SECONDS),
        min_selected_score=min_selected_score
        if min_selected_score is not None
        else float(manifest.get("minSelectedScore") or DEFAULT_MIN_SELECTED_SCORE),
        motion_tuning_enabled=bool(manifest.get("motionTuningEnabled", True)),
        rank_preview_variants=bool(manifest.get("previewSettingsVariantRankingEnabled", True)),
        classify_support_dominance=False,
    )


def section_selection_enabled(request: BakeAndRankRequest) -> bool:
    return bool(request.select_preview_section or request.rank_preview_variants)


def write_candidate_ranking_manifests(review_item_entries: list[dict[str, Any]]) -> None:
    entries_by_workspace: dict[str, list[dict[str, Any]]] = {}
    for entry in review_item_entries:
        entries_by_workspace.setdefault(str(entry["candidateWorkspace"]), []).append(entry)
    for candidate_workspace, entries in entries_by_workspace.items():
        ranking_path = Path(candidate_workspace) / "review" / "ranking.json"
        ranking_path.write_text(
            json.dumps({"rankings": entries}, indent=2),
            encoding="utf-8",
        )


def write_selected_section_preview_html(
    workspace: Path,
    selected: SelectedArtifact | None,
) -> Path | None:
    if selected is None:
        return None
    item, _ranking = selected
    loop_label = (
        f"Section {item.loop_start_seconds:.2f}s-{item.loop_end_seconds:.2f}s"
        if item.llm_time_range_cut_applied
        else "Full Clip"
        if item.loop_index < 0
        else f"Loop {item.loop_index + 1}"
    )
    preview_path = workspace / "selected_section_preview.html"
    video_rel = relative_html_path(item.review_video_path, workspace)
    fallback_mp4 = item.review_video_path.with_suffix(".mp4")
    fallback_rel = relative_html_path(fallback_mp4, workspace) if fallback_mp4 != item.review_video_path else None
    interactive_rel = relative_html_path(item.candidate_workspace / "preview" / "motion_preview.html", workspace)
    interactive_query = urlencode(
        {
            "startSeconds": f"{item.loop_start_seconds:.6f}",
            "endSeconds": f"{item.loop_end_seconds:.6f}",
            "options": json.dumps(item.settings_options, separators=(",", ":")),
        }
    )
    interactive_preview_rel = f"{interactive_rel}?{interactive_query}"
    skeleton_rel = relative_html_path(item.skeleton_path, workspace)
    skeleton_no_lock_rel = (
        relative_html_path(item.skeleton_path_no_feet_lock, workspace)
        if item.skeleton_path_no_feet_lock is not None
        else None
    )
    skeleton_no_hand_lock_rel = (
        relative_html_path(item.skeleton_path_no_hand_lock, workspace)
        if item.skeleton_path_no_hand_lock is not None
        else None
    )
    title = html.escape(f"{item.exercise_name} - Selected {loop_label}")
    source_elements = [
        f'      <source src="{html.escape(video_rel)}" type="{mime_type_for_video_path(item.review_video_path)}">'
    ]
    if fallback_rel is not None and fallback_mp4.exists():
        source_elements.append(
            f'      <source src="{html.escape(fallback_rel)}" type="{mime_type_for_video_path(fallback_mp4)}">'
        )
    preview_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #111;
      color: #eee;
      display: grid;
      min-height: 100vh;
      place-items: center;
    }}
    main {{
      width: min(960px, calc(100vw - 32px));
    }}
    video {{
      width: 100%;
      background: #000;
      border: 1px solid #333;
    }}
    iframe {{
      width: 100%;
      height: min(72vh, 760px);
      min-height: 520px;
      background: #000;
      border: 1px solid #333;
    }}
    details {{
      margin-top: 14px;
    }}
    summary {{
      cursor: pointer;
      color: #c7dcf5;
      margin-bottom: 8px;
    }}
    details video {{
      max-height: 260px;
      object-fit: contain;
    }}
    a {{
      color: #9cc9ff;
    }}
    .links {{
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin-top: 12px;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <iframe src="{html.escape(interactive_preview_rel)}" title="{title}"></iframe>
    <details>
      <summary>Review sample</summary>
      <video controls loop muted>
{chr(10).join(source_elements)}
      </video>
    </details>
    <div class="links">
      <a href="{html.escape(video_rel)}">Open review video</a>
      <a href="{html.escape(interactive_preview_rel)}">Open interactive preview</a>
      <a href="{html.escape(skeleton_rel)}">Open selected skeleton JSON</a>
{f'      <a href="{html.escape(skeleton_no_lock_rel)}">Open selected skeleton JSON (no feet lock)</a>' if skeleton_no_lock_rel is not None else ""}
{f'      <a href="{html.escape(skeleton_no_hand_lock_rel)}">Open selected skeleton JSON (no hand lock)</a>' if skeleton_no_hand_lock_rel is not None else ""}
    </div>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return preview_path


def build_skeleton_selection_manifest(
    *,
    request: BakeAndRankRequest,
    candidate_results: list[dict[str, Any]],
    selected_result: GenerateResult | None,
    selected_candidate: RankedCandidate | None,
) -> dict[str, Any]:
    selected = None
    if selected_result is not None and selected_candidate is not None:
        selected = {
            "exerciseName": selected_candidate.exercise_name,
            "candidateRank": selected_candidate.candidate_rank,
            "candidate": selected_candidate.candidate,
            "manifestPath": str(selected_result.manifest_path),
            "previewHtmlPath": str(selected_result.preview_html_path),
            "rawPreviewHtmlPath": str(selected_result.raw_preview_html_path),
            "wearSkeletonJsonPath": str(selected_result.wear_skeleton_json_path),
            "cleanedMotionJsonPath": str(selected_result.cleaned_motion_json_path),
            "rawMotionJsonPath": str(selected_result.raw_motion_json_path),
            "copiedInputVideoPath": str(selected_result.copied_input_video_path),
            "motionTuningEnabled": selected_result.motion_tuning_enabled,
        }
    return {
        "schemaVersion": 2,
        "pipeline": "source_video_to_single_rep_skeleton",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "candidatesJson": str(request.candidates_json),
        "workspace": str(request.workspace),
        "fallbackCandidates": max(1, request.fallback_candidates),
        "motionTuningEnabled": request.motion_tuning_enabled,
        "candidateResults": candidate_results,
        "selected": selected,
    }


def relative_html_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def mime_type_for_video_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".webm":
        return "video/webm"
    if suffix == ".mp4":
        return "video/mp4"
    return "video/mp4"


def process_ranked_candidates_for_selection(
    candidates: list[RankedCandidate],
    *,
    request: BakeAndRankRequest,
    preview_baker: PreviewBaker,
    support_dominance_classifier: Callable[[list[Path], str], str] | None,
) -> tuple[list[dict[str, Any]], list[ReviewItem], list[dict[str, Any]]]:
    fallback_ready_target = max(1, request.fallback_candidates)
    workers = max(1, min(request.candidate_workers, len(candidates)))
    if workers == 1:
        candidate_results: list[dict[str, Any]] = []
        review_items: list[ReviewItem] = []
        review_item_entries: list[dict[str, Any]] = []
        ready_candidate_count = 0
        for ranked_candidate in candidates:
            local_review_items: list[ReviewItem] = []
            local_review_item_entries: list[dict[str, Any]] = []
            result = process_ranked_candidate(
                ranked_candidate,
                request=request,
                preview_baker=preview_baker,
                review_items=local_review_items,
                review_item_entries=local_review_item_entries,
                support_dominance_classifier=support_dominance_classifier,
            )
            candidate_results.append(result)
            review_items.extend(local_review_items)
            review_item_entries.extend(local_review_item_entries)
            if result.get("status") == "ready_for_selection":
                ready_candidate_count += 1
            if ready_candidate_count >= fallback_ready_target:
                break
        return candidate_results, review_items, review_item_entries

    results_by_index: dict[int, tuple[dict[str, Any], list[ReviewItem], list[dict[str, Any]]]] = {}
    next_index = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        while (
            next_index < len(candidates)
            and len(futures) < workers
            and ready_candidate_capacity_in_launched_prefix(results_by_index, next_index) < fallback_ready_target
        ):
            ranked_candidate = candidates[next_index]
            futures[
                executor.submit(
                    process_ranked_candidate_isolated,
                    ranked_candidate,
                    request,
                    preview_baker,
                    support_dominance_classifier,
                )
            ] = next_index
            next_index += 1
        while futures:
            for future in as_completed(list(futures)):
                index = futures.pop(future)
                results_by_index[index] = future.result()
                if ready_candidate_count_in_prefix(results_by_index) >= fallback_ready_target:
                    for pending in futures:
                        pending.cancel()
                    futures.clear()
                    break
                while (
                    next_index < len(candidates)
                    and len(futures) < workers
                    and ready_candidate_capacity_in_launched_prefix(results_by_index, next_index)
                    < fallback_ready_target
                ):
                    ranked_candidate = candidates[next_index]
                    futures[
                        executor.submit(
                            process_ranked_candidate_isolated,
                            ranked_candidate,
                            request,
                            preview_baker,
                            support_dominance_classifier,
                        )
                    ] = next_index
                    next_index += 1
                break
    candidate_results = []
    review_items = []
    review_item_entries = []
    ready_count = 0
    for index in sorted(results_by_index):
        result, local_review_items, local_review_item_entries = results_by_index[index]
        candidate_results.append(result)
        review_items.extend(local_review_items)
        review_item_entries.extend(local_review_item_entries)
        if result.get("status") == "ready_for_selection":
            ready_count += 1
        if ready_count >= fallback_ready_target:
            break
    return candidate_results, review_items, review_item_entries


def ready_candidate_count_in_prefix(
    results_by_index: dict[int, tuple[dict[str, Any], list[ReviewItem], list[dict[str, Any]]]]
) -> int:
    ready_count = 0
    index = 0
    while index in results_by_index:
        result, _review_items, _review_entries = results_by_index[index]
        if result.get("status") == "ready_for_selection":
            ready_count += 1
        index += 1
    return ready_count


def ready_candidate_capacity_in_launched_prefix(
    results_by_index: dict[int, tuple[dict[str, Any], list[ReviewItem], list[dict[str, Any]]]],
    launched_count: int,
) -> int:
    ready_or_pending_count = 0
    for index in range(launched_count):
        result_tuple = results_by_index.get(index)
        if result_tuple is None:
            ready_or_pending_count += 1
            continue
        result, _review_items, _review_entries = result_tuple
        if result.get("status") == "ready_for_selection":
            ready_or_pending_count += 1
    return ready_or_pending_count


def process_ranked_candidate_isolated(
    ranked_candidate: RankedCandidate,
    request: BakeAndRankRequest,
    preview_baker: PreviewBaker,
    support_dominance_classifier: Callable[[list[Path], str], str] | None,
) -> tuple[dict[str, Any], list[ReviewItem], list[dict[str, Any]]]:
    review_items: list[ReviewItem] = []
    review_item_entries: list[dict[str, Any]] = []
    result = process_ranked_candidate(
        ranked_candidate,
        request=request,
        preview_baker=preview_baker,
        review_items=review_items,
        review_item_entries=review_item_entries,
        support_dominance_classifier=support_dominance_classifier,
    )
    return result, review_items, review_item_entries


def process_ranked_candidate(
    ranked_candidate: RankedCandidate,
    *,
    request: BakeAndRankRequest,
    preview_baker: PreviewBaker,
    review_items: list[ReviewItem],
    review_item_entries: list[dict[str, Any]],
    support_dominance_classifier: Callable[[list[Path], str], str] | None,
) -> dict[str, Any]:
    candidate_started = time.perf_counter()
    candidate_workspace = request.workspace / ranked_candidate.workspace_slug
    result_payload: dict[str, Any] = {
        "exerciseIndex": ranked_candidate.exercise_index,
        "candidateRank": ranked_candidate.candidate_rank,
        "exerciseId": ranked_candidate.exercise_id,
        "exerciseName": ranked_candidate.exercise_name,
        "candidate": ranked_candidate.candidate,
        "candidateWorkspace": str(candidate_workspace),
        "status": "pending",
        "reviewSourceClips": [],
        "rejectedSourceClips": [],
        "failures": [],
        "timings": {},
    }
    try:
        stage_started = time.perf_counter()
        source_gate = evaluate_source_candidate_gate(ranked_candidate)
        record_timing_seconds(result_payload, "sourceGateSeconds", stage_started)
        result_payload["sourceGate"] = source_gate
        if not bool(source_gate["passed"]):
            result_payload["status"] = "skipped_source_gate"
            record_timing_seconds(result_payload, "totalSeconds", candidate_started)
            write_candidate_bake_manifest(candidate_workspace, result_payload)
            return result_payload
        stage_started = time.perf_counter()
        generate_result = generate_candidate_motion(ranked_candidate, request=request)
        record_timing_seconds(result_payload, "generationSeconds", stage_started)
        result_payload.update(generation_to_manifest(generate_result))
        stage_started = time.perf_counter()
        cleaned_clip = load_motion_json(generate_result.cleaned_motion_json_path)
        record_timing_seconds(result_payload, "loadCleanedMotionSeconds", stage_started)
        eligible = [build_full_clip_eligible_loop(cleaned_clip)]
        rejected: list[RejectedLoop] = []
        result_payload["reviewSourceClips"] = [eligible_loop_to_manifest(item) for item in eligible]
        result_payload["rejectedSourceClips"] = [rejected_loop_to_manifest(item) for item in rejected]
        result_payload["processedFullClip"] = True
        stage_started = time.perf_counter()
        baked_artifacts = preview_baker(
            generate_result.preview_html_path,
            eligible,
            candidate_workspace,
            request.review_frames,
        )
        record_timing_seconds(result_payload, "previewBakeSeconds", stage_started)
        review_item_started = time.perf_counter()
        for eligible_loop in eligible:
            loop_artifacts = [
                artifact
                for artifact in baked_artifacts
                if artifact.loop_index == eligible_loop.loop_index
            ]
            if not loop_artifacts:
                result_payload["failures"].append(
                    {
                        "loopIndex": eligible_loop.loop_index,
                        "sourceClipIndex": eligible_loop.loop_index,
                        "reason": "bake_missing_artifact",
                    }
                )
                continue
            support_dominance_result: SupportDominanceResult | None = None
            for artifact in loop_artifacts:
                artifact_started = time.perf_counter()
                loop_start_seconds, loop_end_seconds = loop_time_bounds_from_export(
                    artifact.export_payload,
                    fallback=eligible_loop,
                )
                gate_started = time.perf_counter()
                baked_motion_gate = evaluate_baked_motion_gate(artifact.skeleton_path)
                result_payload.setdefault("bakedMotionGateSeconds", 0.0)
                result_payload["bakedMotionGateSeconds"] = round(
                    float(result_payload["bakedMotionGateSeconds"]) + elapsed_seconds(gate_started),
                    3,
                )
                if not bool(baked_motion_gate["passed"]):
                    result_payload["rejectedSourceClips"].append(
                        {
                            "loopIndex": eligible_loop.loop_index,
                            "sourceClipIndex": eligible_loop.loop_index,
                            "durationSec": eligible_loop.duration_sec,
                            "reason": "baked_motion_too_static",
                            "settingsVariantId": artifact.settings_variant_id,
                            "settingsVariantLabel": artifact.settings_variant_label,
                            "skeletonPath": str(artifact.skeleton_path),
                            "reviewVideoPath": str(artifact.review_video_path),
                            "bakedMotionGate": baked_motion_gate,
                        }
                    )
                    continue
                if support_dominance_result is None:
                    support_started = time.perf_counter()
                    support_dominance_result = classify_support_dominance_for_review_loop(
                        review_video_path=artifact.review_video_path,
                        exercise_name=ranked_candidate.exercise_name,
                        classifier=support_dominance_classifier,
                        candidate_workspace=candidate_workspace,
                        loop_index=eligible_loop.loop_index,
                        sample_frames=request.review_frames,
                    )
                    record_timing_seconds(result_payload, "supportDominanceSeconds", support_started)
                review_item = ReviewItem(
                    exercise_index=ranked_candidate.exercise_index,
                    candidate_rank=ranked_candidate.candidate_rank,
                    loop_index=eligible_loop.loop_index,
                    exercise_name=ranked_candidate.exercise_name,
                    candidate_title=ranked_candidate.title,
                    candidate_workspace=candidate_workspace,
                    preview_html_path=generate_result.preview_html_path,
                    skeleton_path=artifact.skeleton_path,
                    skeleton_path_no_feet_lock=artifact.skeleton_path_no_feet_lock,
                    skeleton_path_no_hand_lock=artifact.skeleton_path_no_hand_lock,
                    review_video_path=artifact.review_video_path,
                    duration_sec=eligible_loop.duration_sec,
                    loop_start_seconds=loop_start_seconds,
                    loop_end_seconds=loop_end_seconds,
                    candidate=ranked_candidate.candidate,
                    settings_variant_id=artifact.settings_variant_id,
                    settings_variant_label=artifact.settings_variant_label,
                    settings_options=artifact.settings_options,
                    support_dominance=support_dominance_result.support_dominance if support_dominance_result else None,
                    support_dominance_confidence=(
                        support_dominance_result.confidence if support_dominance_result else None
                    ),
                    support_dominance_reason=(
                        support_dominance_result.reason if support_dominance_result else None
                    ),
                    support_dominance_uncertain=(
                        support_dominance_result.uncertain if support_dominance_result else None
                    ),
                    support_dominance_model_output=(
                        support_dominance_result.model_output if support_dominance_result else None
                    ),
                )
                review_items.append(review_item)
                review_item_entries.append(review_item_to_manifest(review_item))
                result_payload.setdefault("reviewItemAssemblySeconds", 0.0)
                result_payload["reviewItemAssemblySeconds"] = round(
                    float(result_payload["reviewItemAssemblySeconds"]) + elapsed_seconds(artifact_started),
                    3,
                )
        record_timing_seconds(result_payload, "reviewItemsSeconds", review_item_started)
        has_review_item = any(item.candidate_workspace == candidate_workspace for item in review_items)
        if has_review_item:
            result_payload["status"] = "ready_for_selection"
        elif any(item.get("reason") == "baked_motion_too_static" for item in result_payload["rejectedSourceClips"]):
            result_payload["status"] = "skipped_no_usable_baked_motion"
        else:
            result_payload["status"] = "skipped_no_baked_clip"
        record_timing_seconds(result_payload, "totalSeconds", candidate_started)
        write_candidate_bake_manifest(candidate_workspace, result_payload)
        return result_payload
    except Exception as exc:
        result_payload["status"] = "failed"
        result_payload["failures"].append(
            {
                "reason": "candidate_failed",
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        record_timing_seconds(result_payload, "totalSeconds", candidate_started)
        write_candidate_bake_manifest(candidate_workspace, result_payload)
        return result_payload


def generate_candidate_motion(ranked_candidate: RankedCandidate, *, request: BakeAndRankRequest) -> GenerateResult:
    video_path = prepare_candidate_input_video(ranked_candidate, request=request)
    return run_generation_pipeline(
        GenerateRequest(
            exercise_slug=ranked_candidate.workspace_slug,
            workspace=request.workspace,
            video_path=video_path,
            wham_repo_path=request.wham_repo_path,
            body_model_root=request.body_model_root,
            wham_python_command=request.wham_python_command,
            reuse_wham_cache=request.reuse_wham_cache,
            use_wham_docker=request.use_wham_docker,
            wham_docker_image=request.wham_docker_image,
            wham_docker_gpus=request.wham_docker_gpus,
            wham_docker_shm_size=request.wham_docker_shm_size,
            wham_estimate_local_only=request.wham_estimate_local_only,
            wham_run_smplify=request.wham_run_smplify,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )
    )


def build_full_clip_eligible_loop(cleaned_clip: Any) -> EligibleLoop:
    frame_count = int(getattr(cleaned_clip, "frame_count", 0) or 0)
    fps = float(getattr(cleaned_clip, "fps", 30.0) or 30.0)
    duration_sec = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
    return EligibleLoop(
        loop_index=-1,
        loop={
            "type": "full_clip",
            "startFrame": 0,
            "endFrame": max(0, frame_count - 1),
            "startTimeSec": 0.0,
            "endTimeSec": duration_sec,
            "durationSec": duration_sec,
        },
        duration_sec=duration_sec,
        start_seconds=0.0,
        end_seconds=duration_sec,
    )


def classify_support_dominance_for_review_loop(
    *,
    review_video_path: Path,
    exercise_name: str,
    classifier: Callable[[list[Path], str], str] | None,
    candidate_workspace: Path,
    loop_index: int,
    sample_frames: int,
) -> SupportDominanceResult | None:
    if classifier is None:
        return None
    if not review_video_path.exists():
        return SupportDominanceResult(
            support_dominance="mixed_support",
            confidence=0.0,
            reason="Review loop video is missing.",
            exercise_name=exercise_name,
            uncertain=True,
            model_output={"error": "missing_review_video"},
        )

    metadata = read_basic_video_metadata(review_video_path)
    duration_seconds = metadata.duration_seconds
    if duration_seconds <= 0.0:
        duration_seconds = 0.1

    output_dir = candidate_workspace / "support_dominance_frames" / f"loop_{loop_index + 1:04d}"
    window = DetectionWindow(
        index=0,
        start_seconds=0.0,
        end_seconds=duration_seconds,
    )
    try:
        frame_paths = extract_window_frames(
            video_path=review_video_path,
            window=window,
            frames_per_window=max(1, sample_frames),
            max_frame_width=DEFAULT_RANK_FRAME_WIDTH,
            output_dir=output_dir,
        )
        return classify_support_dominance_from_frames(
            frame_paths=frame_paths,
            exercise_name=exercise_name,
            caption_images=classifier,
        )
    except Exception as exc:
        return SupportDominanceResult(
            support_dominance="mixed_support",
            confidence=0.0,
            reason=f"Support dominance classification failed: {exc}",
            exercise_name=exercise_name,
            uncertain=True,
            model_output={"error": str(exc)},
        )


def prepare_candidate_input_video(ranked_candidate: RankedCandidate, *, request: BakeAndRankRequest) -> Path:
    candidate_workspace = request.workspace / ranked_candidate.workspace_slug
    source_dir = candidate_workspace / "source"
    source_video_path = copy_or_download_candidate_source(ranked_candidate, source_dir)
    if not request.detect_source_segment:
        return source_video_path
    source_chunk_hint = ranked_candidate.source_chunk_hint
    detection_source_video_path = source_video_path
    detection_source_offset_seconds = 0.0
    if source_chunk_hint is not None:
        detection_source_video_path = source_dir / "source_ranked_best_chunk.mp4"
        trim_video(
            source_path=source_video_path,
            output_path=detection_source_video_path,
            start_seconds=source_chunk_hint.start_seconds,
            end_seconds=source_chunk_hint.end_seconds,
        )
        detection_source_offset_seconds = source_chunk_hint.start_seconds
    segment_dir = candidate_workspace / "segment_detection"
    chunk_estimate = estimate_chunking(
        exercise_name=ranked_candidate.exercise_name,
        litert_command=find_default_litert_command(),
        use_llm=True,
    )
    segment_window_seconds = request.segment_window_seconds or chunk_estimate.chunk_seconds
    segment_overlap_seconds = (
        request.segment_overlap_seconds
        if request.segment_overlap_seconds is not None
        else chunk_estimate.chunk_overlap_seconds
    )
    segment_frames_per_window = request.segment_frames_per_window or frames_for_chunk_seconds(segment_window_seconds)
    segment_refinement_frames_per_window = request.segment_refinement_frames_per_window or max(
        24,
        segment_frames_per_window * 2,
    )
    segment_base_url = request.segment_base_url or "http://127.0.0.1:8090"
    segment_model = request.segment_model or "C:\\Users\\gabri\\Downloads\\Qwen3VL-8B-Instruct-Q4_K_M.gguf"
    segment_server = LlamaCppVisionRanker(
        YouTubeRankingSettings(
            llama_cpp_base_url=segment_base_url,
            llama_cpp_model=segment_model,
            vision_llm_workers=request.segment_classification_workers,
            llama_cpp_request_timeout_seconds=request.llama_cpp_request_timeout_seconds,
        )
    )
    try:
        try:
            detection_result = detect_exercise_segment(
                video_path=detection_source_video_path,
                output_dir=segment_dir / "frames",
                exercise_name=ranked_candidate.exercise_name,
                settings=DetectionSettings(
                    base_url=segment_base_url,
                    model=segment_model,
                    window_seconds=segment_window_seconds,
                    overlap_seconds=segment_overlap_seconds,
                    frames_per_window=segment_frames_per_window,
                    confidence_threshold=request.segment_confidence_threshold,
                    min_segment_seconds=request.segment_min_seconds,
                    max_segment_seconds=request.segment_max_seconds,
                    refinement_window_seconds=request.segment_refinement_window_seconds,
                    refinement_overlap_seconds=request.segment_refinement_overlap_seconds,
                    refinement_frames_per_window=segment_refinement_frames_per_window,
                    refinement_padding_seconds=request.segment_refinement_padding_seconds,
                    classification_workers=request.segment_classification_workers,
                    request_timeout_seconds=request.llama_cpp_request_timeout_seconds,
                ),
            )
        except Exception as exc:
            if (
                source_chunk_hint is None
                or source_chunk_hint.score is None
                or source_chunk_hint.score < SOURCE_GATE_STRONG_BEST_CHUNK_SCORE
            ):
                raise
            return write_source_chunk_hint_segment_fallback(
                ranked_candidate=ranked_candidate,
                candidate_workspace=candidate_workspace,
                source_video_path=source_video_path,
                detection_source_video_path=detection_source_video_path,
                source_chunk_hint=source_chunk_hint,
                chunk_estimate=chunk_estimate,
                segment_dir=segment_dir,
                segment_window_seconds=segment_window_seconds,
                segment_overlap_seconds=segment_overlap_seconds,
                segment_frames_per_window=segment_frames_per_window,
                segment_refinement_frames_per_window=segment_refinement_frames_per_window,
                error=exc,
            )
    finally:
        segment_server.close()
    detection_json_path = segment_dir / "segment_detection.json"
    save_detection_result(detection_json_path, detection_result)
    if detection_result.detected_span is None:
        raise RuntimeError(f"Source segment detection did not find a usable {ranked_candidate.exercise_name} span.")
    selected_span = detection_result.detected_span
    source_selected_start_seconds = detection_source_offset_seconds + selected_span.start_seconds
    source_selected_end_seconds = detection_source_offset_seconds + selected_span.end_seconds
    source_chunk_hint_payload = (
        {
            "source": "visionPayload.bestChunk",
            "startSeconds": source_chunk_hint.start_seconds,
            "endSeconds": source_chunk_hint.end_seconds,
            "durationSeconds": source_chunk_hint.duration_seconds,
            "score": source_chunk_hint.score,
        }
        if source_chunk_hint is not None
        else None
    )
    segment_selection_path = segment_dir / "segment_selection.json"
    segment_selection_path.write_text(
        json.dumps(
            {
                "role": "final_single_rep_segment",
                "source": "detect_exercise_segment",
                "sourceVideoPath": str(source_video_path),
                "detectionSourceVideoPath": str(detection_source_video_path),
                "sourceChunkHint": source_chunk_hint_payload,
                "exerciseName": ranked_candidate.exercise_name,
                "chunkEstimate": {
                    "repDurationMinSec": chunk_estimate.rep_duration_min_sec,
                    "repDurationMaxSec": chunk_estimate.rep_duration_max_sec,
                    "movementComplexity": chunk_estimate.movement_complexity,
                    "chunkSeconds": chunk_estimate.chunk_seconds,
                    "chunkOverlapSeconds": chunk_estimate.chunk_overlap_seconds,
                    "source": chunk_estimate.source,
                    "reason": chunk_estimate.reason,
                },
                "segmentSettings": {
                    "windowSeconds": segment_window_seconds,
                    "overlapSeconds": segment_overlap_seconds,
                    "framesPerWindow": segment_frames_per_window,
                    "classificationWorkers": request.segment_classification_workers,
                    "refinementFramesPerWindow": segment_refinement_frames_per_window,
                },
                "selectedSpan": {
                    "startSeconds": selected_span.start_seconds,
                    "endSeconds": selected_span.end_seconds,
                    "confidence": selected_span.confidence,
                    "contributingWindows": selected_span.contributing_windows,
                },
                "selectedSpanInOriginalSource": {
                    "startSeconds": source_selected_start_seconds,
                    "endSeconds": source_selected_end_seconds,
                    "confidence": selected_span.confidence,
                    "contributingWindows": selected_span.contributing_windows,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    selected_segment_path = candidate_workspace / "input" / "selected_segment.mp4"
    trim_video(
        source_path=detection_source_video_path,
        output_path=selected_segment_path,
        start_seconds=max(0.0, selected_span.start_seconds - request.segment_padding_seconds),
        end_seconds=selected_span.end_seconds + request.segment_end_padding_seconds,
    )
    return selected_segment_path


def write_source_chunk_hint_segment_fallback(
    *,
    ranked_candidate: RankedCandidate,
    candidate_workspace: Path,
    source_video_path: Path,
    detection_source_video_path: Path,
    source_chunk_hint: SourceChunkHint,
    chunk_estimate: Any,
    segment_dir: Path,
    segment_window_seconds: float,
    segment_overlap_seconds: float,
    segment_frames_per_window: int,
    segment_refinement_frames_per_window: int,
    error: Exception,
) -> Path:
    segment_dir.mkdir(parents=True, exist_ok=True)
    selected_segment_path = candidate_workspace / "input" / "selected_segment.mp4"
    selected_segment_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(detection_source_video_path, selected_segment_path)
    payload = {
        "role": "final_single_rep_segment",
        "source": "visionPayload.bestChunkFallbackAfterDetectionFailure",
        "sourceVideoPath": str(source_video_path),
        "detectionSourceVideoPath": str(detection_source_video_path),
        "selectedSegmentPath": str(selected_segment_path),
        "exerciseName": ranked_candidate.exercise_name,
        "fallbackReason": "source_segment_detection_failed_inside_strong_source_chunk",
        "fallbackErrorType": type(error).__name__,
        "fallbackError": str(error)[:500],
        "sourceChunkHint": {
            "source": "visionPayload.bestChunk",
            "startSeconds": source_chunk_hint.start_seconds,
            "endSeconds": source_chunk_hint.end_seconds,
            "durationSeconds": source_chunk_hint.duration_seconds,
            "score": source_chunk_hint.score,
        },
        "chunkEstimate": {
            "repDurationMinSec": chunk_estimate.rep_duration_min_sec,
            "repDurationMaxSec": chunk_estimate.rep_duration_max_sec,
            "movementComplexity": chunk_estimate.movement_complexity,
            "chunkSeconds": chunk_estimate.chunk_seconds,
            "chunkOverlapSeconds": chunk_estimate.chunk_overlap_seconds,
            "source": chunk_estimate.source,
            "reason": chunk_estimate.reason,
        },
        "segmentSettings": {
            "windowSeconds": segment_window_seconds,
            "overlapSeconds": segment_overlap_seconds,
            "framesPerWindow": segment_frames_per_window,
            "refinementFramesPerWindow": segment_refinement_frames_per_window,
        },
        "selectedSpan": {
            "startSeconds": 0.0,
            "endSeconds": source_chunk_hint.duration_seconds,
            "confidence": source_chunk_hint.score,
            "contributingWindows": [],
        },
        "selectedSpanInOriginalSource": {
            "startSeconds": source_chunk_hint.start_seconds,
            "endSeconds": source_chunk_hint.end_seconds,
            "confidence": source_chunk_hint.score,
            "contributingWindows": [],
        },
    }
    (segment_dir / "segment_selection.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return selected_segment_path


def bake_preview_loops_with_playwright(
    preview_html_path: Path,
    eligible_loops: list[EligibleLoop],
    candidate_workspace: Path,
    review_frames: int,
    *,
    rank_preview_variants: bool = False,
) -> list[BakedLoopArtifact]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for bake-and-rank. Install with: pip install playwright && playwright install chromium") from exc

    wear_dir = candidate_workspace / "wear"
    review_dir = candidate_workspace / "review"
    wear_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[BakedLoopArtifact] = []
    with sync_playwright() as playwright:
        browser = launch_chromium_browser(playwright)
        page = browser.new_page(viewport={"width": 960, "height": 720}, device_scale_factor=1)
        page.goto(preview_html_path.resolve().as_uri(), wait_until="networkidle")
        page.wait_for_function("() => window.exerciseMotionAutomation != null")
        payload_summary = page.evaluate("() => window.exerciseMotionAutomation.getPayloadSummary()")
        motion_tuning_enabled = bool(
            payload_summary.get("motionTuningEnabled", True)
            if isinstance(payload_summary, dict)
            else True
        )
        for eligible_loop in eligible_loops:
            base_options = build_preview_bake_base_options(motion_tuning_enabled=motion_tuning_enabled)
            artifact_base_label = "full-input" if eligible_loop.loop_index < 0 else f"source-{eligible_loop.loop_index + 1}"
            variants = preview_settings_variants(motion_tuning_enabled=motion_tuning_enabled) if rank_preview_variants else [
                {
                    "id": "full-preview",
                    "label": "Full preview",
                    "options": {},
                }
            ]
            for variant in variants:
                variant_id = str(variant["id"])
                variant_label = str(variant["label"])
                options = {
                    **base_options,
                    **dict(variant.get("options") if isinstance(variant.get("options"), dict) else {}),
                }
                artifact_label = artifact_base_label if not rank_preview_variants else f"{artifact_base_label}.{variant_id}"
                export_payload = page.evaluate(
                    """({ loopIndex, options }) => window.exerciseMotionAutomation.bakeLoop(loopIndex, options)""",
                    {"loopIndex": eligible_loop.loop_index, "options": options},
                )
                skeleton_path = wear_dir / f"skeleton.baked.{artifact_label}.json"
                skeleton_path.write_text(json.dumps(export_payload, indent=2), encoding="utf-8")
                review_video_path = review_dir / f"{artifact_label}.webm"
                frame_indices = sample_review_frame_indices(export_payload, review_frames)
                frame_data_urls = [
                    page.evaluate(
                        """({ frameIndex, options }) => window.exerciseMotionAutomation.renderFrame(frameIndex, options)""",
                        {"frameIndex": frame_index, "options": options},
                    )
                    for frame_index in frame_indices
                ]
                write_review_video_from_data_urls(
                    frame_data_urls,
                    review_video_path,
                    fps=parse_review_video_fps(export_payload, frame_count=len(frame_data_urls)),
                )
                artifacts.append(
                    BakedLoopArtifact(
                        loop_index=eligible_loop.loop_index,
                        skeleton_path=skeleton_path,
                        review_video_path=review_video_path,
                        export_payload=export_payload,
                        settings_variant_id=variant_id,
                        settings_variant_label=variant_label,
                        settings_options=options,
                    )
                )
        browser.close()
    return artifacts


def materialize_llm_selected_time_range(
    selected: SelectedArtifact,
    *,
    request: BakeAndRankRequest,
) -> SelectedArtifact:
    item, ranking = selected
    span = extract_llm_selected_time_range(
        item,
        ranking,
        max_duration_seconds=request.max_loop_seconds,
    )
    options = extract_llm_recommended_settings(
        item,
        ranking,
        motion_tuning_enabled=request.motion_tuning_enabled,
    )
    current_options = effective_review_item_preview_options(
        item,
        motion_tuning_enabled=request.motion_tuning_enabled,
    )
    has_settings_change = preview_options_changed(
        current_options,
        options,
        motion_tuning_enabled=request.motion_tuning_enabled,
    )
    if span is None and not has_settings_change:
        return selected
    if span is not None and not has_settings_change and selected_span_covers_review_item(item, span):
        return selected
    if span is None:
        start_seconds = max(0.0, item.loop_start_seconds)
        end_seconds = item.loop_end_seconds if item.loop_end_seconds > start_seconds else start_seconds + item.duration_sec
        if end_seconds <= start_seconds:
            return selected
        artifact_id = "llm-recommended-settings"
        artifact_label = "LLM recommended settings"
        cut_applied = False
    else:
        start_seconds, end_seconds = span
        artifact_id = "llm-selected-section"
        artifact_label = "LLM selected section"
        cut_applied = True
    return materialize_review_item_time_range(
        item,
        ranking,
        request=request,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        artifact_id=artifact_id,
        artifact_label=artifact_label,
        cut_applied=cut_applied,
    )


def selected_span_covers_review_item(item: ReviewItem, span: tuple[float, float]) -> bool:
    start_seconds, end_seconds = span
    item_start = max(0.0, item.loop_start_seconds)
    item_end = item.loop_end_seconds if item.loop_end_seconds > item_start else item_start + item.duration_sec
    tolerance = max(0.05, 1.0 / 24.0)
    return abs(start_seconds - item_start) <= tolerance and abs(end_seconds - item_end) <= tolerance


def materialize_review_item_time_range(
    item: ReviewItem,
    ranking: LoopRanking | None,
    *,
    request: BakeAndRankRequest,
    start_seconds: float,
    end_seconds: float,
    artifact_id: str,
    artifact_label: str,
    cut_applied: bool,
) -> SelectedArtifact:
    options = extract_llm_recommended_settings(
        item,
        ranking,
        motion_tuning_enabled=request.motion_tuning_enabled,
    )
    bake_result = bake_kinematically_safe_preview_time_range(
        preview_html_path=item.preview_html_path,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        options=options,
        candidate_workspace=item.candidate_workspace,
        review_frames=request.review_frames,
        artifact_id=artifact_id,
        artifact_label=artifact_label,
    )
    artifact = bake_result.artifact
    cut_start_seconds, cut_end_seconds = loop_time_bounds_from_export(
        artifact.export_payload,
        fallback=EligibleLoop(
            loop_index=-1,
            loop={},
            duration_sec=max(0.0, end_seconds - start_seconds),
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        ),
    )
    return (
        replace(
            item,
            skeleton_path=artifact.skeleton_path,
            review_video_path=artifact.review_video_path,
            duration_sec=max(0.0, cut_end_seconds - cut_start_seconds),
            loop_start_seconds=cut_start_seconds,
            loop_end_seconds=cut_end_seconds,
            settings_variant_id=artifact.settings_variant_id,
            settings_variant_label=artifact.settings_variant_label,
            settings_options=artifact.settings_options,
            llm_time_range_cut_applied=cut_applied,
            source_review_video_path=item.review_video_path,
            source_skeleton_path=item.skeleton_path,
        ),
        annotate_ranking_with_kinematic_safe_bake(ranking, bake_result),
    )


def bake_kinematically_safe_preview_time_range(
    *,
    preview_html_path: Path,
    start_seconds: float,
    end_seconds: float,
    options: dict[str, Any],
    candidate_workspace: Path,
    review_frames: int,
    artifact_id: str,
    artifact_label: str,
) -> KinematicSafeBakeResult:
    artifact = bake_preview_time_range_with_playwright(
        preview_html_path=preview_html_path,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        options=options,
        candidate_workspace=candidate_workspace,
        review_frames=review_frames,
        artifact_id=artifact_id,
        artifact_label=artifact_label,
    )
    original_metrics = optional_kinematic_plausibility_metrics(artifact.skeleton_path)
    original_loop_bridge_metrics = optional_loop_bridge_quality_metrics(artifact.skeleton_path)
    if not should_rebake_without_support_locks(options, original_metrics, original_loop_bridge_metrics):
        return KinematicSafeBakeResult(
            artifact=artifact,
            selected_kinematic_metrics=original_metrics,
            selected_loop_bridge_metrics=original_loop_bridge_metrics,
            original_kinematic_metrics=original_metrics,
            original_loop_bridge_metrics=original_loop_bridge_metrics,
        )

    safe_options = support_lock_disabled_options(options)
    safe_artifact = bake_preview_time_range_with_playwright(
        preview_html_path=preview_html_path,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        options=safe_options,
        candidate_workspace=candidate_workspace,
        review_frames=review_frames,
        artifact_id=f"{artifact_id}-no-support-lock",
        artifact_label=f"{artifact_label} without support locks",
    )
    safe_metrics = optional_kinematic_plausibility_metrics(safe_artifact.skeleton_path)
    safe_loop_bridge_metrics = optional_loop_bridge_quality_metrics(safe_artifact.skeleton_path)
    if safe_metrics is not None and is_support_lock_rebake_better(
        original_metrics=original_metrics,
        safe_metrics=safe_metrics,
        original_loop_bridge_metrics=original_loop_bridge_metrics,
        safe_loop_bridge_metrics=safe_loop_bridge_metrics,
    ):
        return KinematicSafeBakeResult(
            artifact=safe_artifact,
            selected_kinematic_metrics=safe_metrics,
            selected_loop_bridge_metrics=safe_loop_bridge_metrics,
            original_kinematic_metrics=original_metrics,
            original_loop_bridge_metrics=original_loop_bridge_metrics,
            support_lock_rebake_attempted=True,
            support_lock_rebake_applied=True,
            support_lock_rebake_options=safe_options,
            support_lock_rebake_metrics=safe_metrics,
            support_lock_rebake_loop_bridge_metrics=safe_loop_bridge_metrics,
        )
    return KinematicSafeBakeResult(
        artifact=artifact,
        selected_kinematic_metrics=original_metrics,
        selected_loop_bridge_metrics=original_loop_bridge_metrics,
        original_kinematic_metrics=original_metrics,
        original_loop_bridge_metrics=original_loop_bridge_metrics,
        support_lock_rebake_attempted=True,
        support_lock_rebake_applied=False,
        support_lock_rebake_options=safe_options,
        support_lock_rebake_metrics=safe_metrics,
        support_lock_rebake_loop_bridge_metrics=safe_loop_bridge_metrics,
    )


def optional_kinematic_plausibility_metrics(skeleton_path: Path) -> dict[str, Any] | None:
    if not skeleton_path.exists():
        return None
    try:
        return compute_kinematic_plausibility_metrics(skeleton_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def optional_loop_bridge_quality_metrics(skeleton_path: Path) -> dict[str, Any] | None:
    if not skeleton_path.exists():
        return None
    try:
        return compute_loop_bridge_quality_metrics(skeleton_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def should_rebake_without_support_locks(
    options: dict[str, Any],
    metrics: dict[str, Any] | None,
    loop_bridge_metrics: dict[str, Any] | None,
) -> bool:
    if not bool(options.get("lockPlantedFeet")) and not bool(options.get("lockPlantedHands")):
        return False
    return bool(
        (metrics and metrics.get("severeArtifact"))
        or (loop_bridge_metrics and loop_bridge_metrics.get("severeLoopMismatch"))
    )


def support_lock_disabled_options(options: dict[str, Any]) -> dict[str, Any]:
    safe_options = dict(options)
    safe_options["lockPlantedFeet"] = False
    safe_options["lockPlantedHands"] = False
    return safe_options


def is_support_lock_rebake_better(
    *,
    original_metrics: dict[str, Any] | None,
    safe_metrics: dict[str, Any],
    original_loop_bridge_metrics: dict[str, Any] | None,
    safe_loop_bridge_metrics: dict[str, Any] | None,
) -> bool:
    if original_metrics is None:
        return False
    original_score = parse_optional_float(original_metrics.get("kinematicPlausibilityScore")) or 0.0
    safe_score = parse_optional_float(safe_metrics.get("kinematicPlausibilityScore")) or 0.0
    original_severe = bool(original_metrics.get("severeArtifact"))
    safe_severe = bool(safe_metrics.get("severeArtifact"))
    kinematic_improved = original_severe and not safe_severe and safe_score > original_score
    if kinematic_improved:
        return True

    if safe_severe and not original_severe:
        return False
    if safe_score + 0.05 < original_score:
        return False
    if original_loop_bridge_metrics is None or safe_loop_bridge_metrics is None:
        return False
    original_loop_score = parse_optional_float(original_loop_bridge_metrics.get("loopBridgeQualityScore")) or 0.0
    safe_loop_score = parse_optional_float(safe_loop_bridge_metrics.get("loopBridgeQualityScore")) or 0.0
    original_loop_severe = bool(original_loop_bridge_metrics.get("severeLoopMismatch"))
    safe_loop_severe = bool(safe_loop_bridge_metrics.get("severeLoopMismatch"))
    if original_loop_severe and not safe_loop_severe and safe_loop_score > original_loop_score:
        return True
    return original_loop_severe and safe_loop_score >= original_loop_score + 0.15


def annotate_ranking_with_kinematic_safe_bake(
    ranking: LoopRanking | None,
    bake_result: KinematicSafeBakeResult,
) -> LoopRanking | None:
    if ranking is None or not bake_result.support_lock_rebake_attempted:
        return ranking
    payload = dict(ranking.payload or {})
    payload.update(
        {
            "supportLockSafeRebakeAttempted": bake_result.support_lock_rebake_attempted,
            "supportLockSafeRebakeApplied": bake_result.support_lock_rebake_applied,
            "supportLockSafeRebakeOriginalKinematicMetrics": bake_result.original_kinematic_metrics,
            "supportLockSafeRebakeKinematicMetrics": bake_result.support_lock_rebake_metrics,
            "supportLockSafeRebakeOriginalLoopBridgeQualityMetrics": bake_result.original_loop_bridge_metrics,
            "supportLockSafeRebakeLoopBridgeQualityMetrics": bake_result.support_lock_rebake_loop_bridge_metrics,
            "supportLockSafeRebakeOptions": bake_result.support_lock_rebake_options,
        }
    )
    reasons = list(ranking.reasons)
    if bake_result.support_lock_rebake_applied:
        reasons.append("support_lock_safe_rebake")
        if (
            bake_result.original_loop_bridge_metrics is not None
            and bool(bake_result.original_loop_bridge_metrics.get("severeLoopMismatch"))
        ):
            reasons.append("support_lock_loop_bridge_rebake")
    return replace(
        ranking,
        reasons=dedupe_text(reasons),
        payload=payload,
    )


def extract_llm_selected_time_range(
    item: ReviewItem,
    ranking: LoopRanking | None,
    *,
    max_duration_seconds: float,
) -> tuple[float, float] | None:
    if ranking is None or not isinstance(ranking.payload, dict):
        return None
    payload = ranking.payload
    start = first_float(
        payload.get("selected_section_start_seconds"),
        payload.get("suggested_section_start_seconds"),
        payload.get("suggested_loop_start_seconds"),
    )
    end = first_float(
        payload.get("selected_section_end_seconds"),
        payload.get("suggested_section_end_seconds"),
        payload.get("suggested_loop_end_seconds"),
    )
    if start is None or end is None:
        return None
    source_start = max(0.0, item.loop_start_seconds)
    source_end = item.loop_end_seconds if item.loop_end_seconds > source_start else item.duration_sec
    chunk_start = parse_optional_float(payload.get("reviewChunkStartSeconds"))
    chunk_end = parse_optional_float(payload.get("reviewChunkEndSeconds"))
    if chunk_start is not None and chunk_end is not None and chunk_end > chunk_start:
        source_start = max(source_start, chunk_start)
        source_end = min(source_end, chunk_end)
    if source_end <= source_start:
        return None
    start = max(source_start, min(source_end, start))
    end = max(source_start, min(source_end, end))
    if end <= start:
        return None
    if max_duration_seconds > 0 and end - start > max_duration_seconds:
        end = min(source_end, start + max_duration_seconds)
    if end - start < 0.5:
        return None
    return start, end


def extract_llm_recommended_settings(
    item: ReviewItem,
    ranking: LoopRanking | None,
    *,
    motion_tuning_enabled: bool,
) -> dict[str, Any]:
    options = effective_review_item_preview_options(
        item,
        motion_tuning_enabled=motion_tuning_enabled,
    )
    if ranking is None or not isinstance(ranking.payload, dict):
        return options
    recommended = ranking.payload.get("recommended_settings")
    if not isinstance(recommended, dict):
        return options
    option_specs = {
        str(option["id"]): option
        for option in preview_tuning_option_catalog(motion_tuning_enabled=motion_tuning_enabled)
    }
    for option_id, spec in option_specs.items():
        if option_id not in recommended:
            continue
        value = recommended[option_id]
        if spec.get("type") == "boolean":
            parsed = parse_optional_bool(value)
            if parsed is not None:
                options[option_id] = parsed
        elif spec.get("type") == "number":
            parsed_float = parse_optional_float(value)
            if parsed_float is None:
                continue
            option_range = spec.get("range")
            if (
                isinstance(option_range, list)
                and len(option_range) == 2
                and all(isinstance(item, (int, float)) for item in option_range)
            ):
                parsed_float = max(float(option_range[0]), min(float(option_range[1]), parsed_float))
            options[option_id] = parsed_float
    return options


def effective_review_item_preview_options(
    item: ReviewItem,
    *,
    motion_tuning_enabled: bool,
) -> dict[str, Any]:
    return {
        **build_preview_bake_base_options(motion_tuning_enabled=motion_tuning_enabled),
        **item.settings_options,
    }


def preview_options_changed(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    motion_tuning_enabled: bool,
) -> bool:
    option_ids = {
        str(option["id"])
        for option in preview_tuning_option_catalog(motion_tuning_enabled=motion_tuning_enabled)
    }
    return any(before.get(option_id) != after.get(option_id) for option_id in option_ids)


def bake_preview_time_range_with_playwright(
    *,
    preview_html_path: Path,
    start_seconds: float,
    end_seconds: float,
    options: dict[str, Any],
    candidate_workspace: Path,
    review_frames: int,
    artifact_id: str = "llm-selected-section",
    artifact_label: str = "LLM selected section",
) -> BakedLoopArtifact:
    wear_dir = candidate_workspace / "wear"
    review_dir = candidate_workspace / "review"
    wear_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    start_ms = int(round(start_seconds * 1000))
    end_ms = int(round(end_seconds * 1000))
    artifact_slug = f"{artifact_id}-{start_ms:06d}-{end_ms:06d}"
    skeleton_path = wear_dir / f"skeleton.baked.{artifact_slug}.json"
    review_video_path = review_dir / f"{artifact_slug}.webm"
    if skeleton_path.exists() and review_video_path.exists():
        return BakedLoopArtifact(
            loop_index=-1,
            skeleton_path=skeleton_path,
            skeleton_path_no_feet_lock=skeleton_path,
            skeleton_path_no_hand_lock=None,
            review_video_path=review_video_path,
            export_payload=json.loads(skeleton_path.read_text(encoding="utf-8")),
            settings_variant_id=artifact_id,
            settings_variant_label=artifact_label,
            settings_options=options,
        )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for LLM-selected section baking. Install with: pip install playwright && playwright install chromium") from exc

    with sync_playwright() as playwright:
        browser = launch_chromium_browser(playwright)
        page = browser.new_page(viewport={"width": 960, "height": 720}, device_scale_factor=1)
        page.goto(preview_html_path.resolve().as_uri(), wait_until="networkidle")
        page.wait_for_function("() => window.exerciseMotionAutomation != null")
        export_payload = page.evaluate(
            """({ startSeconds, endSeconds, options }) => window.exerciseMotionAutomation.bakeTimeRange(startSeconds, endSeconds, options)""",
            {
                "startSeconds": start_seconds,
                "endSeconds": end_seconds,
                "options": options,
            },
        )
        skeleton_path.write_text(json.dumps(export_payload, indent=2), encoding="utf-8")
        frame_indices = dense_loop_review_video_frame_indices(export_payload)
        frame_data_urls = [
            page.evaluate(
                """({ frameIndex, options }) => window.exerciseMotionAutomation.renderFrame(frameIndex, options)""",
                {"frameIndex": frame_index, "options": options},
            )
            for frame_index in frame_indices
        ]
        write_review_video_from_data_urls(
            repeated_review_frame_data_urls(
                frame_data_urls,
                repeats=SELECTED_SECTION_REVIEW_VIDEO_LOOP_REPEATS,
            ),
            review_video_path,
            fps=parse_export_fps(export_payload),
        )
        browser.close()
    return BakedLoopArtifact(
        loop_index=-1,
        skeleton_path=skeleton_path,
        skeleton_path_no_feet_lock=skeleton_path,
        skeleton_path_no_hand_lock=None,
        review_video_path=review_video_path,
        export_payload=export_payload,
        settings_variant_id=artifact_id,
        settings_variant_label=artifact_label,
        settings_options=options,
    )


def first_float(*values: Any) -> float | None:
    for value in values:
        parsed = parse_optional_float(value)
        if parsed is not None:
            return parsed
    return None


def parse_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "1"}:
            return True
        if text in {"false", "no", "0"}:
            return False
    return None


def build_preview_bake_base_options(*, motion_tuning_enabled: bool) -> dict[str, Any]:
    return {
        "fixedRoot": motion_tuning_enabled,
        "autoWorldAlignment": True,
        "lockYDrift": False,
        "lockPlantedFeet": False,
        "lockPlantedHands": False,
        "sceneInverted": False,
        "showSmplMesh": False,
        "showBoundsHelper": False,
        "cameraYawDegrees": 45.0,
        "cameraPitchDegrees": 30.0,
    }


def preview_tuning_option_catalog(*, motion_tuning_enabled: bool) -> list[dict[str, Any]]:
    return [
        {
            "id": "fixedRoot",
            "label": "Lock global root drift",
            "type": "boolean",
            "default": motion_tuning_enabled,
            "description": "Keeps the rendered body centered by removing global root translation.",
            "useWhen": "Use for most Wear animations when camera-space translation makes the character slide away.",
            "risk": "Can hide real traveling movement and make lunges or carries look too anchored.",
        },
        {
            "id": "lockYDrift",
            "label": "Lock root Y drift",
            "type": "boolean",
            "default": False,
            "description": "Suppresses vertical root drift while preserving other root handling.",
            "useWhen": "Use when the pelvis slowly floats up or down across the loop.",
            "risk": "Can flatten real vertical motion such as squat depth if overused.",
        },
        {
            "id": "lockPlantedFeet",
            "label": "Lock planted feet",
            "type": "boolean",
            "default": False,
            "description": "Blends detected support-foot joints toward stable anchors during planted phases.",
            "useWhen": "Use when the support foot visibly slides during a static or mostly static lower-body exercise.",
            "risk": "Can distort the leg chain if WHAM contact timing is wrong.",
        },
        {
            "id": "lockPlantedHands",
            "label": "Lock planted hands",
            "type": "boolean",
            "default": False,
            "description": "Blends detected support-hand joints toward stable anchors during planted phases.",
            "useWhen": "Use for push-ups, planks, hand-supported rows, or clips where hands should stay fixed.",
            "risk": "Can distort arm motion for free-hand exercises or barbell movements.",
        },
        {
            "id": "autoWorldAlignment",
            "label": "Auto world alignment",
            "type": "boolean",
            "default": True,
            "description": "Rotates the preview into a stable readable orientation based on the active loop.",
            "useWhen": "Use when the camera-space skeleton faces an awkward angle on the Wear preview.",
            "risk": "Can choose a worse orientation if the pose estimate is noisy.",
        },
        {
            "id": "sceneInverted",
            "label": "Invert scene",
            "type": "boolean",
            "default": False,
            "description": "Flips the rendered scene orientation.",
            "useWhen": "Use only when the skeleton is clearly facing backward after alignment.",
            "risk": "Can make an otherwise correct view backwards.",
        },
        {
            "id": "cameraYawDegrees",
            "label": "Camera yaw degrees",
            "type": "number",
            "default": 45.0,
            "range": [-180.0, 180.0],
            "description": "Changes the review camera around the rendered skeleton.",
            "useWhen": "Use to make the movement readable when the chosen viewing angle hides the limbs.",
            "risk": "Only affects review/export framing, not the underlying motion.",
        },
        {
            "id": "cameraPitchDegrees",
            "label": "Camera pitch degrees",
            "type": "number",
            "default": 30.0,
            "range": [-68.0, 68.0],
            "description": "Tilts the review camera up or down.",
            "useWhen": "Use to keep feet and head visible while preserving movement readability.",
            "risk": "Only affects review/export framing, not the underlying motion.",
        },
    ]


def format_preview_tuning_options_for_prompt(*, motion_tuning_enabled: bool) -> str:
    lines: list[str] = []
    for option in preview_tuning_option_catalog(motion_tuning_enabled=motion_tuning_enabled):
        range_text = f", range={option['range']}" if "range" in option else ""
        lines.append(
            "- "
            f"{option['id']} ({option['type']}, default={option['default']}{range_text}): "
            f"{option['description']} Use when: {option['useWhen']} Risk: {option['risk']}"
        )
    return "\n".join(lines)


def preview_settings_variants(*, motion_tuning_enabled: bool = True) -> list[dict[str, Any]]:
    if not motion_tuning_enabled:
        return [
            {
                "id": "raw-wham",
                "label": "Raw WHAM camera-space",
                "options": {
                    "fixedRoot": False,
                    "lockPlantedFeet": False,
                    "lockPlantedHands": False,
                    "autoWorldAlignment": True,
                },
            },
        ]
    return [
        {
            "id": "lock-feet-hands",
            "label": "Lock feet and hands",
            "options": {
                "lockPlantedFeet": True,
                "lockPlantedHands": True,
                "autoWorldAlignment": True,
            },
        },
        {
            "id": "no-foot-lock",
            "label": "No foot lock",
            "options": {
                "lockPlantedFeet": False,
                "lockPlantedHands": True,
                "autoWorldAlignment": True,
            },
        },
        {
            "id": "no-hand-lock",
            "label": "No hand lock",
            "options": {
                "lockPlantedFeet": True,
                "lockPlantedHands": False,
                "autoWorldAlignment": True,
            },
        },
        {
            "id": "no-support-lock",
            "label": "No support lock",
            "options": {
                "lockPlantedFeet": False,
                "lockPlantedHands": False,
                "autoWorldAlignment": True,
            },
        },
        {
            "id": "no-auto-alignment",
            "label": "No auto alignment",
            "options": {
                "lockPlantedFeet": True,
                "lockPlantedHands": True,
                "autoWorldAlignment": False,
            },
        },
        {
            "id": "no-support-lock-no-auto-alignment",
            "label": "No support lock, no auto alignment",
            "options": {
                "lockPlantedFeet": False,
                "lockPlantedHands": False,
                "autoWorldAlignment": False,
            },
        },
        {
            "id": "no-foot-lock-no-auto-alignment",
            "label": "No foot lock, no auto alignment",
            "options": {
                "lockPlantedFeet": False,
                "lockPlantedHands": True,
                "autoWorldAlignment": False,
            },
        },
        {
            "id": "no-hand-lock-no-auto-alignment",
            "label": "No hand lock, no auto alignment",
            "options": {
                "lockPlantedFeet": True,
                "lockPlantedHands": False,
                "autoWorldAlignment": False,
            },
        },
    ]


def sample_review_frame_indices(export_payload: dict[str, Any], count: int) -> list[int]:
    frame_count = int(export_payload.get("frameCount") or 0)
    if frame_count <= 0:
        return [0]
    sample_count = max(1, min(int(count), frame_count))
    if sample_count == frame_count:
        return list(range(frame_count))
    if sample_count == 1:
        return [frame_count // 2]
    return sorted(
        {
            round(index * (frame_count - 1) / (sample_count - 1))
            for index in range(sample_count)
        }
    )


def dense_loop_review_video_frame_indices(export_payload: dict[str, Any]) -> list[int]:
    frame_count = int(export_payload.get("frameCount") or 0)
    if frame_count <= 0:
        return [0]
    if frame_count <= MAX_DENSE_REVIEW_VIDEO_FRAMES:
        return list(range(frame_count))
    return sample_review_frame_indices(export_payload, MAX_DENSE_REVIEW_VIDEO_FRAMES)


def repeated_review_frame_data_urls(data_urls: list[str], *, repeats: int) -> list[str]:
    if repeats <= 1 or len(data_urls) < 2:
        return list(data_urls)
    repeated: list[str] = []
    for repeat_index in range(repeats):
        if repeat_index == 0:
            repeated.extend(data_urls)
        else:
            repeated.extend(data_urls[1:])
    return repeated


def parse_export_fps(export_payload: dict[str, Any]) -> float:
    value = export_payload.get("fps")
    if isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0:
        return float(value)
    return 30.0


def parse_review_video_fps(export_payload: dict[str, Any], *, frame_count: int) -> float:
    duration = export_payload.get("durationSec")
    if (
        frame_count > 1
        and isinstance(duration, (int, float))
        and math.isfinite(float(duration))
        and float(duration) > 0.0
    ):
        return max(0.1, frame_count / float(duration))
    return parse_export_fps(export_payload)


def llm_review_frame_count_for_chunk(chunk_seconds: float, request: BakeAndRankRequest) -> int:
    return max(
        DEFAULT_LLM_REVIEW_FRAMES,
        max(1, int(request.review_frames)),
        frames_for_chunk_seconds(chunk_seconds),
    )


def loop_time_bounds_from_export(
    export_payload: dict[str, Any],
    *,
    fallback: EligibleLoop,
) -> tuple[float, float]:
    loop_payload = export_payload.get("loop")
    if isinstance(loop_payload, dict):
        start = parse_optional_float(loop_payload.get("sourceStartTimeSec"))
        end = parse_optional_float(loop_payload.get("sourceEndTimeSec"))
        if start is not None and end is not None:
            return start, max(start, end)
    frames = export_payload.get("frames")
    if isinstance(frames, list) and frames:
        timeline_frames = [
            frame
            for frame in frames
            if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))
        ]
        if not timeline_frames:
            timeline_frames = [frame for frame in frames if isinstance(frame, dict)]
        start = parse_optional_float(timeline_frames[0].get("sourceTimeSec") if timeline_frames else None)
        end = parse_optional_float(timeline_frames[-1].get("sourceTimeSec") if timeline_frames else None)
        if start is not None and end is not None:
            return start, max(start, end)
    if isinstance(loop_payload, dict):
        start_frame = parse_optional_float(loop_payload.get("sourceStartFrame"))
        end_frame = parse_optional_float(loop_payload.get("sourceEndFrame"))
        fps = parse_export_fps(export_payload)
        if start_frame is not None and end_frame is not None and fps > 0:
            return start_frame / fps, max(start_frame, end_frame) / fps
    return fallback.start_seconds, fallback.end_seconds


def write_review_video_from_data_urls(data_urls: list[str], output_path: Path, *, fps: float) -> None:
    if not data_urls:
        raise ValueError("At least one rendered frame is required to write a review video.")
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError("opencv-python and numpy are required to write review videos.") from exc

    frames = []
    for data_url in data_urls:
        _, _, encoded = data_url.partition(",")
        image_bytes = base64.b64decode(encoded)
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("Failed to decode rendered preview frame.")
        frames.append(image)
    height, width = frames[0].shape[:2]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    codec = "VP90" if output_path.suffix.lower() == ".webm" else "mp4v"
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*codec), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer for {output_path}.")
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()


def render_review_window_contact_sheet(
    *,
    item: ReviewItem,
    window: DetectionWindow,
    output_dir: Path,
    frame_count: int,
) -> list[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for dense LLM review rendering.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    options = dict(item.settings_options)
    with sync_playwright() as playwright:
        browser = launch_chromium_browser(playwright)
        try:
            page = browser.new_page(viewport={"width": 960, "height": 720}, device_scale_factor=1)
            page.goto(item.preview_html_path.resolve().as_uri(), wait_until="networkidle")
            page.wait_for_function("() => window.exerciseMotionAutomation != null")
            export_payload = page.evaluate(
                """({ startSeconds, endSeconds, options }) => window.exerciseMotionAutomation.bakeTimeRange(startSeconds, endSeconds, options)""",
                {
                    "startSeconds": window.start_seconds,
                    "endSeconds": window.end_seconds,
                    "options": options,
                },
            )
            frame_indices = sample_review_frame_indices(export_payload, frame_count)
            frame_data_urls = [
                page.evaluate(
                    """({ frameIndex, options }) => window.exerciseMotionAutomation.renderFrame(frameIndex, options)""",
                    {"frameIndex": frame_index, "options": options},
                )
                for frame_index in frame_indices
            ]
        finally:
            browser.close()
    contact_sheet_path = output_dir / "contact_sheet.jpg"
    write_review_contact_sheet_from_data_urls(frame_data_urls, contact_sheet_path)
    return [contact_sheet_path]


def write_review_contact_sheet_from_data_urls(data_urls: list[str], output_path: Path) -> None:
    if not data_urls:
        raise ValueError("At least one rendered frame is required to write a review contact sheet.")
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError("opencv-python and numpy are required to write review contact sheets.") from exc

    frames = []
    for data_url in data_urls:
        _, _, encoded = str(data_url).partition(",")
        image_bytes = base64.b64decode(encoded)
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("Failed to decode rendered preview frame.")
        height, width = image.shape[:2]
        if width > DEFAULT_LLM_REVIEW_CONTACT_SHEET_CELL_WIDTH:
            scale = DEFAULT_LLM_REVIEW_CONTACT_SHEET_CELL_WIDTH / width
            image = cv2.resize(
                image,
                (DEFAULT_LLM_REVIEW_CONTACT_SHEET_CELL_WIDTH, max(1, int(round(height * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        frames.append(image)

    cell_height = max(frame.shape[0] for frame in frames)
    cell_width = max(frame.shape[1] for frame in frames)
    columns = contact_sheet_columns(len(frames))
    rows = math.ceil(len(frames) / columns)
    sheet = np.zeros((rows * cell_height, columns * cell_width, 3), dtype=np.uint8)
    for index, frame in enumerate(frames):
        row = index // columns
        column = index % columns
        y = row * cell_height
        x = column * cell_width
        sheet[y : y + frame.shape[0], x : x + frame.shape[1]] = frame
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), sheet):
        raise RuntimeError(f"Failed to write review contact sheet to {output_path}.")


def contact_sheet_columns(frame_count: int) -> int:
    if frame_count <= 4:
        return max(1, frame_count)
    if frame_count <= 16:
        return 4
    if frame_count <= 30:
        return 5
    return 6


def rank_review_items_with_llama_cpp(
    items: list[ReviewItem],
    request: BakeAndRankRequest,
    *,
    caption_images: Callable[..., str] | None = None,
) -> list[LoopRanking]:
    ranker = None if caption_images is not None else LlamaCppVisionRanker(build_llama_cpp_vision_settings(request))
    active_caption_images = caption_images if caption_images is not None else ranker.client.caption_images
    try:
        llm_indices = select_llm_review_item_indices(items, request)
        rankings: list[LoopRanking | None] = [
            None if index in llm_indices else build_prefilter_skipped_ranking(item, request)
            for index, item in enumerate(items)
        ]
        if not llm_indices:
            return [
                ranking if ranking is not None else LoopRanking(score=0.0, reasons=["review_item_ranking_missing"])
                for ranking in rankings
            ]
        workers = max(1, min(request.review_llm_workers, len(llm_indices)))
        if workers == 1:
            for index in llm_indices:
                item = items[index]
                rankings[index] = (
                    apply_loop_continuity_adjustment(
                        item,
                        rank_review_item_with_caption_images(item, request, active_caption_images),
                    )
                )
            return [
                ranking if ranking is not None else LoopRanking(score=0.0, reasons=["review_item_ranking_missing"])
                for ranking in rankings
            ]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(rank_review_item_with_caption_images, item, request, active_caption_images): index
                for index, item in enumerate(items)
                if index in llm_indices
            }
            for future in as_completed(futures):
                index = futures[future]
                item = items[index]
                try:
                    ranking = future.result()
                except Exception as exc:
                    ranking = LoopRanking(
                        score=0.0,
                        reasons=["review_item_ranking_failed", str(exc)],
                    )
                rankings[index] = apply_loop_continuity_adjustment(item, ranking)
        return [
            ranking if ranking is not None else LoopRanking(score=0.0, reasons=["review_item_ranking_missing"])
            for ranking in rankings
        ]
    finally:
        if ranker is not None:
            ranker.close()


def select_llm_review_item_indices(items: list[ReviewItem], request: BakeAndRankRequest) -> set[int]:
    max_items = int(request.max_llm_review_items or 0)
    if max_items <= 0 or len(items) <= max_items:
        return set(range(len(items)))
    scored = [
        (review_item_prefilter_score(item, request), index)
        for index, item in enumerate(items)
    ]
    scored.sort(key=lambda item: (item[0], -items[item[1]].exercise_index, -items[item[1]].candidate_rank), reverse=True)
    selected: set[int] = set()
    seen_candidates: set[tuple[int, int]] = set()
    for _score, index in scored:
        candidate_key = (items[index].exercise_index, items[index].candidate_rank)
        if candidate_key in seen_candidates:
            continue
        selected.add(index)
        seen_candidates.add(candidate_key)
        if len(selected) >= max_items:
            return selected
    for _score, index in scored:
        selected.add(index)
        if len(selected) >= max_items:
            break
    return selected


def review_item_prefilter_score(item: ReviewItem, request: BakeAndRankRequest) -> float:
    duration_seconds = max(0.1, item.duration_sec)
    chunk_estimate = estimate_chunking(
        exercise_name=item.exercise_name,
        litert_command=find_default_litert_command(),
        use_llm=True,
    )
    chunk_seconds = min(max(0.5, chunk_estimate.chunk_seconds), duration_seconds)
    chunk_overlap_seconds = min(max(0.0, chunk_estimate.chunk_overlap_seconds), max(0.0, chunk_seconds - 0.25))
    windows = iter_detection_windows(
        duration_seconds=duration_seconds,
        window_seconds=chunk_seconds,
        overlap_seconds=chunk_overlap_seconds,
    )
    candidates = select_review_windows_by_skeleton_motion(
        item,
        windows,
        max_windows=1,
    )
    if not candidates:
        return 0.0
    return float(candidates[0].score)


def build_prefilter_skipped_ranking(item: ReviewItem, request: BakeAndRankRequest) -> LoopRanking:
    score = min(LOOP_DETERMINISTIC_FALLBACK_SCORE_CAP, review_item_prefilter_score(item, request))
    return LoopRanking(
        score=score,
        reasons=["llm_review_skipped_by_prefilter"],
        payload={
            "score": score,
            "modelScore": score,
            "prefilterScore": score,
            "maxLlmReviewItems": request.max_llm_review_items,
        },
        model_score=score,
    )


def build_llama_cpp_vision_settings(request: BakeAndRankRequest) -> YouTubeRankingSettings:
    return YouTubeRankingSettings(
        vision_llm_workers=max(1, request.review_llm_workers),
        llama_cpp_base_url=request.llama_cpp_base_url,
        llama_cpp_model=request.llama_cpp_model,
        llama_cpp_command=request.llama_cpp_command,
        llama_cpp_server_command=request.llama_cpp_server_command,
        llama_cpp_mmproj=request.llama_cpp_mmproj,
        llama_cpp_backend=request.llama_cpp_backend,
        llama_cpp_n_predict=request.llama_cpp_n_predict,
        llama_cpp_temperature=request.llama_cpp_temperature,
        llama_cpp_disable_reasoning=request.llama_cpp_disable_reasoning,
        llama_cpp_ctx_size=request.llama_cpp_ctx_size,
        llama_cpp_batch_size=request.llama_cpp_batch_size,
        llama_cpp_ubatch_size=request.llama_cpp_ubatch_size,
        llama_cpp_flash_attn=request.llama_cpp_flash_attn,
        llama_cpp_threads_http=request.llama_cpp_threads_http,
        llama_cpp_cache_reuse=request.llama_cpp_cache_reuse,
        llama_cpp_mmproj_offload=request.llama_cpp_mmproj_offload,
        llama_cpp_cont_batching=request.llama_cpp_cont_batching,
        llama_cpp_image_min_tokens=request.llama_cpp_image_min_tokens,
        llama_cpp_image_max_tokens=request.llama_cpp_image_max_tokens,
        llama_cpp_auto_start_server=request.llama_cpp_auto_start_server,
        keep_llama_cpp_server=request.keep_llama_cpp_server,
        llama_cpp_server_startup_timeout_seconds=request.llama_cpp_server_startup_timeout_seconds,
        llama_cpp_request_timeout_seconds=request.llama_cpp_request_timeout_seconds,
    )


def rank_review_item_with_caption_images(
    item: ReviewItem,
    request: BakeAndRankRequest,
    caption_images: Callable[..., str],
) -> LoopRanking:
    item_started = time.perf_counter()
    artifact_label = "full-clip" if item.loop_index < 0 else f"loop-{item.loop_index + 1}"
    variant_label = slugify(item.settings_variant_id or "default")
    frames_dir = item.candidate_workspace / "review" / f"{artifact_label}.{variant_label}-section-rank-frames"
    duration_seconds = max(0.1, item.duration_sec)
    chunk_estimate = estimate_chunking(
        exercise_name=item.exercise_name,
        litert_command=find_default_litert_command(),
        use_llm=True,
    )
    chunk_seconds = min(max(0.5, chunk_estimate.chunk_seconds), duration_seconds)
    chunk_overlap_seconds = min(max(0.0, chunk_estimate.chunk_overlap_seconds), max(0.0, chunk_seconds - 0.25))
    windows = iter_detection_windows(
        duration_seconds=duration_seconds,
        window_seconds=chunk_seconds,
        overlap_seconds=chunk_overlap_seconds,
    )
    window_candidates = select_review_windows_by_skeleton_motion(
        item,
        windows,
        max_windows=request.max_review_windows,
    )
    frames_per_chunk = llm_review_frame_count_for_chunk(chunk_seconds, request)
    rankings: list[LoopRanking] = []
    for shortlist_index, window_candidate in enumerate(window_candidates):
        video_window = window_candidate.video_window
        timeline_window = window_candidate.timeline_window
        try:
            render_started = time.perf_counter()
            frame_paths = render_review_window_contact_sheet(
                item=item,
                window=timeline_window,
                output_dir=frames_dir / f"chunk_{video_window.index:04d}",
                frame_count=frames_per_chunk,
            )
            render_seconds = elapsed_seconds(render_started)
        except Exception as exc:
            rankings.append(
                LoopRanking(
                    score=0.0,
                    reasons=["section_chunk_dense_preview_render_failed", str(exc)],
                )
            )
            continue
        try:
            vlm_started = time.perf_counter()
            raw = caption_images(
                frame_paths=frame_paths,
                prompt=build_loop_ranking_prompt(
                    item,
                    chunk_window=timeline_window,
                    chunk_index=shortlist_index,
                    chunk_count=len(window_candidates),
                    chunk_estimate=chunk_estimate,
                    original_chunk_index=video_window.index,
                    original_chunk_count=len(windows),
                    deterministic_window_score=window_candidate.score,
                    review_frame_count=frames_per_chunk,
                ),
            )
            vlm_seconds = elapsed_seconds(vlm_started)
            ranking = parse_loop_ranking_response(raw)
        except Exception as exc:
            rankings.append(
                build_deterministic_section_fallback_ranking(
                    window=timeline_window,
                    video_window=video_window,
                    chunk_index=shortlist_index,
                    chunk_count=len(window_candidates),
                    original_chunk_count=len(windows),
                    deterministic_window=window_candidate,
                    chunk_estimate=chunk_estimate,
                    review_frame_source="interactive_preview_dense_contact_sheet",
                    review_frame_count=frames_per_chunk,
                    error=exc,
                )
            )
            continue
        rankings.append(
            ranking_with_timing_metadata(
                ranking_with_chunk_metadata(
                    ranking,
                    window=timeline_window,
                    video_window=video_window,
                    chunk_index=shortlist_index,
                    chunk_count=len(window_candidates),
                    original_chunk_count=len(windows),
                    deterministic_window=window_candidate,
                    chunk_estimate=chunk_estimate,
                    review_frame_source="interactive_preview_dense_contact_sheet",
                    review_frame_count=frames_per_chunk,
                ),
                render_seconds=render_seconds,
                vlm_seconds=vlm_seconds,
                item_total_seconds=elapsed_seconds(item_started),
            )
        )
    if not rankings:
        return LoopRanking(score=0.0, reasons=["section_chunk_review_failed"])
    return max(rankings, key=lambda ranking: ranking.score)


def ranking_with_timing_metadata(
    ranking: LoopRanking,
    *,
    render_seconds: float,
    vlm_seconds: float,
    item_total_seconds: float,
) -> LoopRanking:
    payload = dict(ranking.payload) if isinstance(ranking.payload, dict) else {}
    payload["reviewRenderSeconds"] = render_seconds
    payload["reviewVlmSeconds"] = vlm_seconds
    payload["reviewItemTotalSeconds"] = item_total_seconds
    return LoopRanking(
        score=ranking.score,
        reasons=ranking.reasons,
        raw_response=ranking.raw_response,
        payload=payload,
        model_score=ranking.model_score,
        continuity_score=ranking.continuity_score,
        continuity_metrics=ranking.continuity_metrics,
    )


def build_deterministic_section_fallback_ranking(
    *,
    window: DetectionWindow,
    video_window: DetectionWindow,
    chunk_index: int,
    chunk_count: int,
    original_chunk_count: int,
    deterministic_window: ReviewWindowCandidate,
    chunk_estimate: Any,
    review_frame_source: str,
    review_frame_count: int,
    error: Exception,
) -> LoopRanking:
    motion_score = clamp_unit(parse_optional_float(deterministic_window.motion_metrics.get("motionStrengthScore")) or 0.0)
    continuity_score = clamp_unit(parse_optional_float(deterministic_window.continuity_metrics.get("continuityScore")) or 0.0)
    model_score = clamp_unit(
        0.45 * clamp_unit(float(deterministic_window.score))
        + 0.35 * motion_score
        + 0.20 * continuity_score
    )
    model_score = min(model_score, LOOP_DETERMINISTIC_FALLBACK_SCORE_CAP)
    payload = {
        "score": model_score,
        "modelScore": model_score,
        "correctness": None,
        "full_rep_motion": motion_score,
        "recognizability": None,
        "smoothness": continuity_score,
        "stable_feet": None,
        "joint_plausibility": None,
        "loop_continuity": continuity_score,
        "wear_readability": None,
        "recommended_settings": {},
        "selected_section_start_seconds": window.start_seconds,
        "selected_section_end_seconds": window.end_seconds,
        "needs_another_iteration": False,
        "fallbackErrorType": type(error).__name__,
        "fallbackError": str(error)[:500],
    }
    base = LoopRanking(
        score=model_score,
        reasons=[
            "llm_section_review_failed",
            "deterministic_section_fallback",
            type(error).__name__,
        ],
        payload=payload,
        model_score=model_score,
        continuity_score=continuity_score,
        continuity_metrics=deterministic_window.continuity_metrics,
    )
    return ranking_with_chunk_metadata(
        base,
        window=window,
        video_window=video_window,
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        original_chunk_count=original_chunk_count,
        deterministic_window=deterministic_window,
        chunk_estimate=chunk_estimate,
        review_frame_source=review_frame_source,
        review_frame_count=review_frame_count,
    )


def ranking_with_chunk_metadata(
    ranking: LoopRanking,
    *,
    window: DetectionWindow,
    video_window: DetectionWindow,
    chunk_index: int,
    chunk_count: int,
    original_chunk_count: int,
    deterministic_window: ReviewWindowCandidate,
    chunk_estimate: Any,
    review_frame_source: str,
    review_frame_count: int,
) -> LoopRanking:
    payload = dict(ranking.payload) if isinstance(ranking.payload, dict) else {}
    payload.update(
        {
            "reviewChunkIndex": chunk_index,
            "reviewChunkCount": chunk_count,
            "reviewOriginalChunkIndex": video_window.index,
            "reviewOriginalChunkCount": original_chunk_count,
            "reviewChunkStartSeconds": window.start_seconds,
            "reviewChunkEndSeconds": window.end_seconds,
            "reviewVideoChunkStartSeconds": video_window.start_seconds,
            "reviewVideoChunkEndSeconds": video_window.end_seconds,
            "reviewFrameSource": review_frame_source,
            "reviewFrameCount": review_frame_count,
            "deterministicWindowScore": deterministic_window.score,
            "deterministicWindowMotionMetrics": deterministic_window.motion_metrics,
            "deterministicWindowContinuityMetrics": deterministic_window.continuity_metrics,
            "deterministicWindowKinematicMetrics": deterministic_window.kinematic_metrics,
            "deterministicWindowLoopBridgeQualityMetrics": deterministic_window.loop_bridge_quality_metrics,
            "deterministicWindowPreviewReadabilityMetrics": deterministic_window.preview_readability_metrics,
            "chunkEstimate": {
                "repDurationMinSec": getattr(chunk_estimate, "rep_duration_min_sec", None),
                "repDurationMaxSec": getattr(chunk_estimate, "rep_duration_max_sec", None),
                "movementComplexity": getattr(chunk_estimate, "movement_complexity", None),
                "chunkSeconds": getattr(chunk_estimate, "chunk_seconds", None),
                "chunkOverlapSeconds": getattr(chunk_estimate, "chunk_overlap_seconds", None),
                "source": getattr(chunk_estimate, "source", None),
                "reason": getattr(chunk_estimate, "reason", None),
            },
        }
    )
    return replace(
        ranking,
        payload=payload,
        reasons=dedupe_text([*ranking.reasons, "chunked_preview_section_review"]),
    )


def dedupe_text(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def build_loop_ranking_prompt(
    item: ReviewItem,
    *,
    chunk_window: DetectionWindow,
    chunk_index: int,
    chunk_count: int,
    chunk_estimate: Any,
    original_chunk_index: int,
    original_chunk_count: int,
    deterministic_window_score: float,
    review_frame_count: int,
) -> str:
    current_settings_json = json.dumps(item.settings_options, sort_keys=True)
    motion_tuning_enabled = item.settings_variant_id != "raw-wham"
    return (
        "Review this bounded chunk from a full baked exercise motion preview and choose the best loopable section inside this chunk for a Wear OS exercise animation.\n"
        f"Target exercise: {item.exercise_name}.\n"
        f"Candidate video title: {item.candidate_title}.\n"
        f"Full selected input preview span: {item.loop_start_seconds:.3f}s to {item.loop_end_seconds:.3f}s "
        f"({item.duration_sec:.3f}s).\n"
        f"Review shortlisted chunk {chunk_index + 1} of {chunk_count}: {chunk_window.start_seconds:.3f}s to {chunk_window.end_seconds:.3f}s.\n"
        f"This was original temporal chunk {original_chunk_index + 1} of {original_chunk_count}, shortlisted by skeleton motion score {deterministic_window_score:.3f}.\n"
        f"The attached image is a chronological contact sheet rendered directly from the interactive preview with {review_frame_count} evenly sampled frames; read it left-to-right, top-to-bottom.\n"
        "Use the chunk boundaries as the search space. Return selected section seconds in the full preview timeline, and keep them inside this chunk.\n"
        f"Chunk sizing came from the shared estimate: {json.dumps({'repDurationMinSec': getattr(chunk_estimate, 'rep_duration_min_sec', None), 'repDurationMaxSec': getattr(chunk_estimate, 'rep_duration_max_sec', None), 'movementComplexity': getattr(chunk_estimate, 'movement_complexity', None), 'chunkSeconds': getattr(chunk_estimate, 'chunk_seconds', None), 'chunkOverlapSeconds': getattr(chunk_estimate, 'chunk_overlap_seconds', None), 'source': getattr(chunk_estimate, 'source', None)})}.\n"
        f"Current preview option variant: {item.settings_variant_id} ({item.settings_variant_label}).\n"
        f"Current preview option values: {current_settings_json}.\n"
        "Available preview tuning options and what they do:\n"
        f"{format_preview_tuning_options_for_prompt(motion_tuning_enabled=motion_tuning_enabled)}\n"
        "Do not assume any hidden options exist. Judge only the attached chunk frames and pick exact start/end seconds for the section that should be cut and looped.\n"
        "The selected section should contain one strong full visible rep whenever the source provides one: include the clear eccentric and concentric phases, enough depth/range to recognize the exercise, and boundaries near similar poses for looping. Do not select a shallow hold or near-static balance pose just because it is stable.\n"
        "Avoid setup, reset, walking in/out, bad boundary poses, and sections where the body is unclear. If no strong full rep is present in this chunk, lower the score and set full_rep_motion below 0.7.\n"
        "If a different available option set would likely improve the selected section, put those values in recommended_settings and explain why.\n"
        "Score 0 to 1 for the proposed cut using these criteria: correct exercise, full-rep motion strength/range, recognizability, smoothness, stable planted feet when appropriate, no impossible joints, clean section boundaries for looping, and readability on a small Wear display.\n"
        "Strongly penalize wrong or unclear movement, shallow or partial reps when a stronger full rep is visible, jitter, foot sliding, broken limbs, visible popping, bad section boundaries, and poses that would be confusing on a watch.\n"
        "Return JSON only with keys: {\"score\": number, \"correctness\": number, \"full_rep_motion\": number, \"recognizability\": number, \"smoothness\": number, \"stable_feet\": number, \"joint_plausibility\": number, \"loop_continuity\": number, \"wear_readability\": number, \"recommended_settings\": object, \"selected_section_start_seconds\": number|null, \"selected_section_end_seconds\": number|null, \"needs_another_iteration\": boolean, \"reasons\": [string]}."
    )


def write_candidate_bake_manifest(candidate_workspace: Path, payload: dict[str, Any]) -> None:
    review_dir = candidate_workspace / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "bake_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_selection_manifest(
    *,
    request: BakeAndRankRequest,
    candidate_results: list[dict[str, Any]],
    review_entries: list[dict[str, Any]],
    selected: SelectedArtifact | None,
    rejected_best: SelectedArtifact | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceCandidatesJson": str(request.candidates_json),
        "candidateSelectionPolicy": "ranked_source_video_fallback_then_materialized_section_validation",
        "sectionSelectionPolicy": (
            "llama_cpp_skeleton_prefiltered_preview_section_selection"
            if request.rank_preview_variants
            else "skipped_full_input_selected_without_llm_section_cut"
        ),
        "previewSettingsVariantRankingEnabled": request.rank_preview_variants,
        "previewTuningOptionCatalog": preview_tuning_option_catalog(
            motion_tuning_enabled=request.motion_tuning_enabled
        ),
        "maxLoopSeconds": request.max_loop_seconds,
        "maxReviewWindows": request.max_review_windows,
        "minSelectedScore": request.min_selected_score,
        "motionTuningEnabled": request.motion_tuning_enabled,
        "candidateResults": candidate_results,
        "reviewItems": review_entries,
        "selected": None if selected is None else selected_to_manifest(*selected),
        "rejectedBest": None if rejected_best is None else {
            **selected_to_manifest(*rejected_best),
            "rejectionReason": "best_score_below_minimum",
        },
    }


def selected_to_manifest(item: ReviewItem, ranking: LoopRanking | None) -> dict[str, Any]:
    payload = review_item_to_manifest(item)
    if ranking is None:
        payload["selectionReason"] = "top_ranked_video_cropped_clip"
        payload["rankingSkipped"] = "no_loop_choice_required"
    else:
        payload["ranking"] = ranking_to_manifest(ranking)
    payload["selectedWearSkeletonPath"] = str(item.skeleton_path)
    if item.skeleton_path_no_feet_lock is not None:
        payload["selectedWearSkeletonPathNoFeetLock"] = str(item.skeleton_path_no_feet_lock)
    if item.skeleton_path_no_hand_lock is not None:
        payload["selectedWearSkeletonPathNoHandLock"] = str(item.skeleton_path_no_hand_lock)
    payload["selectedReviewVideoPath"] = str(item.review_video_path)
    payload["selectedSectionStartSeconds"] = item.loop_start_seconds
    payload["selectedSectionEndSeconds"] = item.loop_end_seconds
    payload["selectedSectionDurationSeconds"] = item.duration_sec
    return payload


def generation_to_manifest(result: GenerateResult) -> dict[str, Any]:
    return {
        "manifestPath": str(result.manifest_path),
        "previewHtmlPath": str(result.preview_html_path),
        "rawPreviewHtmlPath": str(result.raw_preview_html_path),
        "wearSkeletonJsonPath": str(result.wear_skeleton_json_path),
        "cleanedMotionJsonPath": str(result.cleaned_motion_json_path),
        "rawMotionJsonPath": str(result.raw_motion_json_path),
        "targetRigContractPath": str(result.target_rig_contract_path),
        "retargetSourcePath": str(result.retarget_source_path) if result.retarget_source_path is not None else None,
        "whamSmplPreviewJsonPath": str(result.smpl_preview_json_path) if result.smpl_preview_json_path is not None else None,
        "whamResultsPkl": str(result.wham_results_pkl) if result.wham_results_pkl is not None else None,
        "whamCacheStatus": result.wham_cache_status,
        "inputVideoPath": str(result.copied_input_video_path),
        "groundMetadataPath": str(result.ground_metadata_path) if result.ground_metadata_path is not None else None,
        "motionTuningEnabled": result.motion_tuning_enabled,
    }


def eligible_loop_to_manifest(item: EligibleLoop) -> dict[str, Any]:
    return {
        "loopIndex": item.loop_index,
        "sourceClipIndex": item.loop_index,
        "startSeconds": item.start_seconds,
        "endSeconds": item.end_seconds,
        "durationSec": item.duration_sec,
        "loop": item.loop,
    }


def rejected_loop_to_manifest(item: RejectedLoop) -> dict[str, Any]:
    return {
        "loopIndex": item.loop_index,
        "sourceClipIndex": item.loop_index,
        "durationSec": item.duration_sec,
        "reason": item.reason,
        "loop": item.loop,
    }


def review_item_to_manifest(item: ReviewItem) -> dict[str, Any]:
    return {
        "exerciseIndex": item.exercise_index,
        "candidateRank": item.candidate_rank,
        "loopIndex": item.loop_index,
        "exerciseName": item.exercise_name,
        "candidateTitle": item.candidate_title,
        "candidateWorkspace": str(item.candidate_workspace),
        "previewHtmlPath": str(item.preview_html_path),
        "skeletonPath": str(item.skeleton_path),
        "skeletonPathNoFeetLock": str(item.skeleton_path_no_feet_lock) if item.skeleton_path_no_feet_lock is not None else None,
        "skeletonPathNoHandLock": str(item.skeleton_path_no_hand_lock) if item.skeleton_path_no_hand_lock is not None else None,
        "reviewVideoPath": str(item.review_video_path),
        "durationSec": item.duration_sec,
        "loopStartSeconds": item.loop_start_seconds,
        "loopEndSeconds": item.loop_end_seconds,
        "sectionStartSeconds": item.loop_start_seconds,
        "sectionEndSeconds": item.loop_end_seconds,
        "llmTimeRangeCutApplied": item.llm_time_range_cut_applied,
        "sourceReviewVideoPath": str(item.source_review_video_path) if item.source_review_video_path is not None else None,
        "sourceSkeletonPath": str(item.source_skeleton_path) if item.source_skeleton_path is not None else None,
        "candidate": item.candidate,
        "settingsVariantId": item.settings_variant_id,
        "settingsVariantLabel": item.settings_variant_label,
        "settingsOptions": item.settings_options,
        "supportDominance": item.support_dominance,
        "supportDominanceConfidence": item.support_dominance_confidence,
        "supportDominanceReason": item.support_dominance_reason,
        "supportDominanceUncertain": item.support_dominance_uncertain,
        "supportDominanceModelOutput": item.support_dominance_model_output,
    }


def review_item_from_manifest(payload: dict[str, Any]) -> ReviewItem:
    return ReviewItem(
        exercise_index=int(payload.get("exerciseIndex") or 0),
        candidate_rank=int(payload.get("candidateRank") or 0),
        loop_index=int(payload.get("loopIndex") if payload.get("loopIndex") is not None else -1),
        exercise_name=str(payload.get("exerciseName") or ""),
        candidate_title=str(payload.get("candidateTitle") or ""),
        candidate_workspace=Path(str(payload.get("candidateWorkspace") or ".")),
        preview_html_path=Path(str(payload.get("previewHtmlPath") or ".")),
        skeleton_path=Path(str(payload.get("skeletonPath") or payload.get("selectedWearSkeletonPath") or ".")),
        skeleton_path_no_feet_lock=optional_path_from_manifest(payload.get("skeletonPathNoFeetLock") or payload.get("selectedWearSkeletonPathNoFeetLock")),
        skeleton_path_no_hand_lock=optional_path_from_manifest(payload.get("skeletonPathNoHandLock") or payload.get("selectedWearSkeletonPathNoHandLock")),
        review_video_path=Path(str(payload.get("reviewVideoPath") or payload.get("selectedReviewVideoPath") or ".")),
        duration_sec=float(payload.get("durationSec") or payload.get("selectedSectionDurationSeconds") or 0.0),
        loop_start_seconds=float(payload.get("loopStartSeconds") or payload.get("sectionStartSeconds") or payload.get("selectedSectionStartSeconds") or 0.0),
        loop_end_seconds=float(payload.get("loopEndSeconds") or payload.get("sectionEndSeconds") or payload.get("selectedSectionEndSeconds") or 0.0),
        candidate=payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {},
        support_dominance=str(payload["supportDominance"]) if payload.get("supportDominance") is not None else None,
        support_dominance_confidence=parse_optional_float(payload.get("supportDominanceConfidence")),
        support_dominance_reason=str(payload["supportDominanceReason"]) if payload.get("supportDominanceReason") is not None else None,
        support_dominance_uncertain=parse_optional_bool(payload.get("supportDominanceUncertain")),
        support_dominance_model_output=payload.get("supportDominanceModelOutput") if isinstance(payload.get("supportDominanceModelOutput"), dict) else None,
        settings_variant_id=str(payload.get("settingsVariantId") or "full-preview"),
        settings_variant_label=str(payload.get("settingsVariantLabel") or "Full preview"),
        settings_options=payload.get("settingsOptions") if isinstance(payload.get("settingsOptions"), dict) else {},
        llm_time_range_cut_applied=bool(payload.get("llmTimeRangeCutApplied", False)),
        source_review_video_path=optional_path_from_manifest(payload.get("sourceReviewVideoPath")),
        source_skeleton_path=optional_path_from_manifest(payload.get("sourceSkeletonPath")),
    )


def optional_path_from_manifest(value: Any) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    return Path(text) if text else None


def ranking_to_manifest(ranking: LoopRanking) -> dict[str, Any]:
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    return {
        "score": ranking.score,
        "reasons": ranking.reasons,
        "payload": ranking.payload,
        "rawResponse": ranking.raw_response,
        "modelScore": ranking.model_score,
        "continuityScore": ranking.continuity_score,
        "continuityMetrics": ranking.continuity_metrics,
        "motionStrengthScore": payload.get("motionStrengthScore"),
        "motionStrengthMetrics": payload.get("motionStrengthMetrics"),
        "kinematicPlausibilityScore": payload.get("kinematicPlausibilityScore"),
        "kinematicPlausibilityMetrics": payload.get("kinematicPlausibilityMetrics"),
        "sourceMotionCaptureRatio": payload.get("sourceMotionCaptureRatio"),
    }


def ranking_from_manifest(payload: dict[str, Any]) -> LoopRanking:
    reasons = payload.get("reasons")
    return LoopRanking(
        score=float(payload.get("score") or 0.0),
        reasons=[str(reason) for reason in reasons] if isinstance(reasons, list) else [],
        raw_response=str(payload["rawResponse"]) if payload.get("rawResponse") is not None else None,
        payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else None,
        model_score=parse_optional_float(payload.get("modelScore")),
        continuity_score=parse_optional_float(payload.get("continuityScore")),
        continuity_metrics=payload.get("continuityMetrics") if isinstance(payload.get("continuityMetrics"), dict) else None,
    )


def copy_or_download_candidate_source(ranked_candidate: RankedCandidate, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    video_path = ranked_candidate.video_path
    if video_path is not None:
        source = video_path.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Candidate video not found: {source}")
        destination = destination_dir / source.name
        if source != destination.resolve():
            shutil.copy2(source, destination)
        return destination
    if not ranked_candidate.url:
        raise ValueError("Candidate must provide url or videoPath.")
    return download_youtube(ranked_candidate.url, destination_dir)
