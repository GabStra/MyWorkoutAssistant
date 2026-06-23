from __future__ import annotations

import base64
import html
import json
import math
import os
import re
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
from exercise_motion_pkg.llama_defaults import (
    DEFAULT_LLAMA_CPP_MMPROJ,
    DEFAULT_LLAMA_CPP_MODEL,
    DEFAULT_LLAMA_CPP_TEMPERATURE,
    DEFAULT_LLAMA_CPP_TOP_K,
    DEFAULT_LLAMA_CPP_TOP_P,
)
from exercise_motion_pkg.pipeline import GenerateRequest, GenerateResult, run_generation_pipeline
from exercise_motion_pkg.wham_runner import (
    DEFAULT_WHAM_DOCKER_IMAGE,
    DEFAULT_WHAM_DOCKER_SHM_SIZE,
    DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY,
)
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
from exercise_motion_pkg.youtube import (
    POSE_PREFILTER_HARD_REJECT_ISSUES,
    LlamaCppVisionRanker,
    YouTubeRankingSettings,
    download_youtube,
    pose_prefilter_blocking_issues,
    slugify,
)
from exercise_motion_pkg.chunking import (
    estimate_chunking,
    frames_for_chunk_seconds,
    known_duration_hint_for,
    normalize_exercise_name,
)


DEFAULT_MAX_LOOP_SECONDS = 10.0
DEFAULT_REVIEW_FRAMES = 6
DEFAULT_LLM_REVIEW_FRAMES = 32
DEFAULT_LLM_REVIEW_FRAMES_PER_SECOND = 4.0
DEFAULT_MAX_LLM_REVIEW_FRAMES = 48
DEFAULT_LLM_REVIEW_CONTACT_SHEET_CELL_WIDTH = 320
MAX_DENSE_REVIEW_VIDEO_FRAMES = 360
SELECTED_SECTION_REVIEW_VIDEO_LOOP_REPEATS = 1
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
LOOP_SOURCE_FULL_SPAN_COVERAGE_MIN = 0.9
LOOP_DETERMINISTIC_FALLBACK_SCORE_CAP = 0.49
LOOP_RIGID_ROOT_MOTION_SCORE_CAP = 0.52
LOOP_RIGID_ROOT_DOMINANT_RANGE_RATIO = 0.18
LOOP_RIGID_ROOT_MIN_ARTICULATION_RATIO = 0.08
LOOP_KINEMATIC_ARTIFACT_SCORE_CAP = 0.52
LOOP_HAND_LOCK_ARM_DISTORTION_SCORE_CAP = 0.34
LOOP_PAIRED_HANDS_DISTORTION_SCORE_CAP = 0.49
LOWER_BODY_MOTION_MIN_ARTICULATION_RATIO = 0.10
WEAK_FOCUSED_MOTION_SCORE_MULTIPLIER_FLOOR = 0.55
PAIRED_HANDS_MIN_SOURCE_CAPTURE_RATIO = 0.75
PAIRED_HANDS_MAX_SPACING_INSTABILITY_RATIO = 0.18
PAIRED_HANDS_MIN_SAME_PHASE_CORRELATION = 0.45
LOOP_BRIDGE_ARTIFACT_SCORE_CAP = 0.49
NON_LOOPING_MOVEMENT_COMPLEXITIES = {"multi_phase", "long_duration"}
LOWER_BODY_DOMINANT_EXERCISE_TERMS = (
    "squat",
    "lunge",
    "split squat",
    "step up",
    "deadlift",
    "hinge",
    "good morning",
    "hip thrust",
    "glute bridge",
    "leg press",
    "leg extension",
    "leg curl",
    "calf raise",
    "clean",
    "snatch",
    "jerk",
    "jump",
    "burpee",
    "kettlebell swing",
)
LOOP_BRIDGE_ENDPOINT_BODY_RATIO = 0.10
LOOP_BRIDGE_ENDPOINT_SEVERE_BODY_RATIO = 0.15
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
    "hand_lock_arm_distortion_penalty",
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
DETERMINISTIC_REVIEW_VALIDATION_ENABLED = False
KINEMATIC_DISTAL_STEP_SPIKE_RATIO = 8.0
KINEMATIC_DISTAL_STEP_BODY_RATIO = 0.08
KINEMATIC_ANGLE_STEP_DEGREES = 25.0
KINEMATIC_BONE_LENGTH_VARIATION_RATIO = 0.18
KINEMATIC_BONE_LENGTH_BODY_RATIO = 0.06
HAND_LOCK_ARM_BILATERAL_MEDIAN_DIFF_DEGREES = 35.0
HAND_LOCK_ARM_BILATERAL_MAX_DIFF_DEGREES = 55.0
HAND_LOCK_ARM_EXTREME_LOW_DEGREES = 35.0
HAND_LOCK_ARM_EXTREME_HIGH_DEGREES = 175.0
WINDOW_MOTION_SCORE_WEIGHT = 0.75
WINDOW_CONTINUITY_SCORE_WEIGHT = 0.25
SOURCE_GATE_MIN_BEST_CHUNK_SCORE = 0.35
SOURCE_GATE_STRONG_BEST_CHUNK_SCORE = 0.85
SOURCE_GATE_MAX_DIRECT_CHUNK_SECONDS = 20.0
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
        score = parse_optional_float(payload.get("bestChunkScore"))
        valid_chunk_count = parse_optional_int(payload.get("validChunkCount"))
        pose_payload = payload.get("posePrefilter")
        deterministic_source_fallback = isinstance(payload.get("deterministicSourceFallback"), dict)
        best_chunk_source = str(payload.get("bestChunkSource") or "").strip().lower()
        pose_score = None
        pose_start_seconds = None
        pose_end_seconds = None
        pose_hint_duration = None
        if isinstance(pose_payload, dict):
            pose_score = parse_optional_float(pose_payload.get("score"))
            pose_start_seconds = parse_optional_float(pose_payload.get("bestChunkStartSeconds"))
            pose_end_seconds = parse_optional_float(pose_payload.get("bestChunkEndSeconds"))
            if pose_start_seconds is not None and pose_end_seconds is not None:
                pose_hint_duration = max(0.0, pose_end_seconds - pose_start_seconds)
        pose_hint_valid = (
            isinstance(pose_payload, dict)
            and pose_start_seconds is not None
            and pose_end_seconds is not None
            and pose_end_seconds > pose_start_seconds
        )
        pose_hint_strong = (
            pose_hint_valid
            and pose_score is not None
            and pose_score >= SOURCE_GATE_STRONG_BEST_CHUNK_SCORE
            and pose_hint_duration is not None
            and pose_hint_duration <= SOURCE_GATE_MAX_DIRECT_CHUNK_SECONDS
        )
        use_pose_hint = (
            pose_hint_valid
            and (
                start_seconds is None
                or end_seconds is None
                or best_chunk_source == "pose_prefilter"
                or (
                    bool(pose_payload.get("passed"))
                    and pose_score is not None
                    and pose_hint_strong
                    and not deterministic_source_fallback
                    and (
                        score is None
                        or score < SOURCE_GATE_STRONG_BEST_CHUNK_SCORE
                        or best_chunk_source == "chunked_source_video_review"
                        or valid_chunk_count == 0
                    )
                )
            )
        )
        if use_pose_hint:
            start_seconds = pose_start_seconds
            end_seconds = pose_end_seconds
            score = pose_score
        if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
            return None
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
    cleanup_interpretation: str = "support_lock"
    adaptive_preview_settings: dict[str, Any] | None = None


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
    cleanup_interpretation: str = "support_lock"
    adaptive_preview_settings: dict[str, Any] | None = None
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
class ActiveMotionWindowProposal:
    window: DetectionWindow
    metrics: dict[str, Any]


@dataclass(frozen=True)
class SourceCutCandidate:
    candidate_id: str
    window: DetectionWindow
    frame_paths: list[Path]


class SourceCandidateRejected(RuntimeError):
    """Raised when the source video is visually rejected before WHAM."""


@dataclass(frozen=True)
class BakeAndRankRequest:
    candidates_json: Path
    workspace: Path
    wham_repo_path: Path | None
    body_model_root: Path | None
    youtube_cookies: Path | None = None
    fallback_candidates: int = DEFAULT_FALLBACK_CANDIDATES
    candidate_workers: int = 1
    wham_python_command: str = "python"
    reuse_wham_cache: bool = True
    use_wham_docker: bool = False
    wham_docker_image: str = DEFAULT_WHAM_DOCKER_IMAGE
    wham_docker_gpus: str = "all"
    wham_docker_shm_size: str = DEFAULT_WHAM_DOCKER_SHM_SIZE
    wham_estimate_local_only: bool = DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY
    wham_run_smplify: bool = True
    spinepose_enabled: bool = False
    spinepose_json_dir: Path | None = None
    spinepose_command: str | None = None
    spinepose_output_dir: Path | None = None
    spinepose_mode: str = "large"
    spinepose_model_version: str = "v2"
    spinepose_device: str = "cuda"
    spinepose_reuse_cache: bool = True
    spinepose_gain: float = 1.0
    spinepose_max_degrees: float = 35.0
    spinepose_axis: int = 0
    spinepose_invert: bool = False
    spinepose_smoothing_window: int = 9
    spinepose_arm_counter_rotation: float = 1.0
    spinepose_merge_mode: str = "motion"
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
    pre_wham_source_validation: bool = False
    review_frames: int = DEFAULT_REVIEW_FRAMES
    review_llm_workers: int = 3
    max_llm_review_items: int = 4
    max_review_windows: int = DEFAULT_MAX_REVIEW_WINDOWS
    max_loop_seconds: float = DEFAULT_MAX_LOOP_SECONDS
    min_selected_score: float = DEFAULT_MIN_SELECTED_SCORE
    motion_tuning_enabled: bool = True
    select_preview_section: bool = False
    rank_preview_variants: bool = False
    adaptive_preview_settings: bool = False
    max_adaptive_preview_settings: int = 3
    classify_support_dominance: bool = True
    llama_cpp_base_url: str | None = "http://127.0.0.1:8090"
    llama_cpp_model: str = DEFAULT_LLAMA_CPP_MODEL
    llama_cpp_command: str | None = None
    llama_cpp_server_command: str | None = None
    llama_cpp_mmproj: str | None = DEFAULT_LLAMA_CPP_MMPROJ
    llama_cpp_backend: str = "gpu"
    llama_cpp_n_predict: int = 768
    llama_cpp_temperature: float = DEFAULT_LLAMA_CPP_TEMPERATURE
    llama_cpp_top_p: float | None = DEFAULT_LLAMA_CPP_TOP_P
    llama_cpp_top_k: int | None = DEFAULT_LLAMA_CPP_TOP_K
    llama_cpp_disable_reasoning: bool = True
    llama_cpp_ctx_size: int | None = None
    llama_cpp_batch_size: int | None = None
    llama_cpp_ubatch_size: int | None = None
    llama_cpp_flash_attn: str | None = None
    llama_cpp_cache_type_k: str | None = None
    llama_cpp_cache_type_v: str | None = None
    llama_cpp_parallel: int | None = None
    llama_cpp_threads_http: int | None = None
    llama_cpp_cache_reuse: int | None = None
    llama_cpp_fit: str | None = None
    llama_cpp_fit_ctx: int | None = None
    llama_cpp_fit_target: int | None = None
    llama_cpp_mmap: bool = True
    llama_cpp_mlock: bool = False
    llama_cpp_mmproj_offload: bool = True
    llama_cpp_cont_batching: bool = True
    llama_cpp_image_min_tokens: int | None = None
    llama_cpp_image_max_tokens: int | None = None
    llama_cpp_auto_start_server: bool = True
    keep_llama_cpp_server: bool = False
    llama_cpp_server_startup_timeout_seconds: float = 180.0
    llama_cpp_request_timeout_seconds: float = 90.0
    require_recommended_youtube_candidate: bool = True


PreviewBaker = Callable[..., list[BakedLoopArtifact]]
LoopRanker = Callable[[list[ReviewItem], BakeAndRankRequest], list[LoopRanking]]
SelectedArtifact = tuple[ReviewItem, LoopRanking | None]


def load_ranked_candidates_manifest(
    path: Path,
    *,
    require_recommended_youtube_candidate: bool = True,
) -> list[RankedCandidate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    parsed_candidates = [
        candidate
        for candidate in parse_ranked_candidates_manifest(payload)
        if candidate_bake_status(candidate) != "rejected"
    ]
    candidates = parsed_candidates
    if require_recommended_youtube_candidate and is_youtube_candidates_manifest(payload):
        recommended_candidates = [
            candidate
            for candidate in parsed_candidates
            if candidate_bake_status(candidate) == "recommended"
        ]
        if not recommended_candidates:
            raise ValueError(
                "No recommended YouTube candidate found. Candidate fallback is disabled by default; "
                "inspect the YouTube candidates JSON or rerun with explicit candidate fallback enabled."
            )
        candidates = recommended_candidates
    reviewed_candidates = [
        candidate
        for candidate in candidates
        if isinstance(candidate.candidate.get("visionPayload"), dict)
    ]
    if reviewed_candidates:
        return reviewed_candidates
    return candidates


def is_youtube_candidates_manifest(payload: dict[str, Any]) -> bool:
    ranking = payload.get("ranking")
    if isinstance(ranking, dict):
        if any(key in ranking for key in ("searchElapsedSeconds", "posePrefilterEnabled", "semanticGateEnabled")):
            return True
        timing = ranking.get("timing")
        if isinstance(timing, dict) and "searchElapsedSeconds" in timing:
            return True
    for candidate in parse_ranked_candidates_manifest(payload):
        value = candidate.candidate.get("url") or candidate.candidate.get("webpageUrl")
        if isinstance(value, str) and ("youtube.com" in value or "youtu.be" in value):
            return True
    return False


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
    deterministic_source_fallback: dict[str, Any] | None = None
    if isinstance(payload, dict):
        fallback_payload = payload.get("deterministicSourceFallback")
        if isinstance(fallback_payload, dict):
            deterministic_source_fallback = fallback_payload
        best_chunk_score = parse_optional_float(payload.get("bestChunkScore"))
        if best_chunk_score is not None and best_chunk_score < SOURCE_GATE_MIN_BEST_CHUNK_SCORE:
            reasons.append("low_ranked_source_chunk_score")
        source_score = parse_optional_float(payload.get("source_score"))
        valid_chunk_ratio = parse_optional_float(payload.get("validChunkRatio"))
        valid_chunk_count = parse_optional_int(payload.get("validChunkCount"))
        scored_chunk_count = parse_optional_int(payload.get("scoredChunkCount"))
        incomplete_repetition_only = parse_optional_bool(payload.get("complete_repetition_visible")) is False
        strong_single_chunk_source = (
            best_chunk_score is not None
            and best_chunk_score >= SOURCE_GATE_STRONG_BEST_CHUNK_SCORE
            and valid_chunk_count is not None
            and valid_chunk_count >= 1
        )
        strong_incomplete_source = (
            incomplete_repetition_only
            and best_chunk_score is not None
            and best_chunk_score >= SOURCE_GATE_MIN_BEST_CHUNK_SCORE
            and source_score is not None
            and source_score >= 0.75
        )
        if (
            scored_chunk_count is not None
            and scored_chunk_count > 0
            and valid_chunk_count is not None
            and valid_chunk_count <= 0
            and not strong_incomplete_source
        ):
            reasons.append("no_valid_source_chunk_evidence")
        elif (
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
        pose_payload = payload.get("posePrefilter")
        if isinstance(pose_payload, dict):
            for issue in pose_prefilter_blocking_issues(pose_payload):
                if issue in POSE_PREFILTER_HARD_REJECT_ISSUES:
                    reasons.append(f"pose_{issue}")
        if deterministic_source_fallback is None:
            for field in (
                "correct_exercise",
                "usable_for_motion_extraction",
                "athlete_fully_in_frame_throughout",
                "static_camera_throughout",
                "single_person_chunk",
                "real_human_subject",
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
        "deterministicSourceFallback": deterministic_source_fallback,
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
            selected_artifact_score(pair),
            -pair[0].exercise_index,
            -pair[0].candidate_rank,
            -pair[0].loop_index,
        ),
    )
    if selected_artifact_score(selected) < min_score:
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
            selected_artifact_score(pair),
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
    materialized_quality_rescore_enabled = (
        len({(item.exercise_index, item.candidate_rank) for item, _ranking in paired}) > 1
    )
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
        if materialized_quality_rescore_enabled:
            materialized = rescore_materialized_deterministic_quality(materialized)
        if selected_artifact_score(materialized) >= request.min_selected_score:
            fallback = materialize_clean_subinterval_fallback(
                original=original,
                rejected=materialized,
                request=request,
            )
            if fallback is not None and recovered_artifact_is_better(materialized, fallback):
                chosen = (
                    fallback
                )
            else:
                chosen = materialized
            if accepted_best is None or selected_artifact_score(chosen) > selected_artifact_score(accepted_best):
                accepted_best = chosen
            continue
        fallback = materialize_clean_subinterval_fallback(
            original=original,
            rejected=materialized,
            request=request,
        )
        if fallback is not None:
            if materialized_quality_rescore_enabled:
                fallback = rescore_materialized_deterministic_quality(fallback)
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


def recovered_artifact_is_better(current: SelectedArtifact, recovered: SelectedArtifact) -> bool:
    if selected_artifact_has_kinematic_rejection(current) and not selected_artifact_has_kinematic_rejection(recovered):
        return True
    if selected_artifact_has_kinematic_rejection(recovered) and not selected_artifact_has_kinematic_rejection(current):
        return False
    return deterministic_artifact_score(recovered) > deterministic_artifact_score(current)


def deterministic_artifact_score(selected: SelectedArtifact) -> float:
    _item, ranking = selected
    if ranking is None:
        return 1.0
    return ranking.score


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
    if ranking.model_score is not None:
        return ranking.model_score
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    payload_model_score = parse_optional_float(payload.get("modelScore"))
    if payload_model_score is not None:
        return payload_model_score
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


def rescore_materialized_deterministic_quality(selected: SelectedArtifact) -> SelectedArtifact:
    item, ranking = selected
    if ranking is None or not item.skeleton_path.exists():
        return selected
    motion_metrics = compute_motion_strength_metrics(item.skeleton_path)
    readability_metrics = compute_preview_readability_metrics(
        item.skeleton_path,
        camera_yaw_degrees=parse_optional_float(item.settings_options.get("cameraYawDegrees")) or 45.0,
    )
    kinematic_metrics = compute_kinematic_plausibility_metrics(item.skeleton_path)
    motion_score = clamp_unit(parse_optional_float(motion_metrics.get("motionStrengthScore")) or 0.0)
    readability_score = clamp_unit(parse_optional_float(readability_metrics.get("previewReadabilityScore")) or 0.0)
    kinematic_score = clamp_unit(parse_optional_float(kinematic_metrics.get("kinematicPlausibilityScore")) or 0.0)
    materialized_quality_score = clamp_unit(
        0.35 * motion_score
        + 0.45 * readability_score
        + 0.20 * kinematic_score
    )
    base_score = selected_artifact_score(selected)
    combined_score = clamp_unit(base_score * 0.90 + materialized_quality_score * 0.10)
    payload = dict(ranking.payload or {})
    payload.update(
        {
            "materializedDeterministicQualityScore": materialized_quality_score,
            "materializedDeterministicCombinedScore": combined_score,
            "materializedMotionMetrics": motion_metrics,
            "materializedPreviewReadabilityMetrics": readability_metrics,
            "materializedKinematicMetrics": kinematic_metrics,
        }
    )
    return (
        item,
        LoopRanking(
            score=combined_score,
            reasons=dedupe_text(
                [
                    *ranking.reasons,
                    "materialized_deterministic_quality_score",
                ]
            ),
            raw_response=ranking.raw_response,
            payload=payload,
            model_score=combined_score,
            continuity_score=ranking.continuity_score,
            continuity_metrics=ranking.continuity_metrics,
        ),
    )


def recomputed_materialized_reasons(reasons: list[str]) -> list[str]:
    return [
        reason
        for reason in reasons
        if reason not in MATERIALIZED_REEVALUATION_REASON_CODES
    ]


def exercise_requires_loop_continuity(
    exercise_name: str,
    *,
    ranking_payload: dict[str, Any] | None = None,
    chunk_estimate: Any | None = None,
) -> bool:
    return False


def movement_complexity_for_validation(
    exercise_name: str,
    *,
    ranking_payload: dict[str, Any] | None = None,
    chunk_estimate: Any | None = None,
) -> str:
    if chunk_estimate is not None:
        complexity = getattr(chunk_estimate, "movement_complexity", None)
        if complexity:
            return str(complexity)
    if isinstance(ranking_payload, dict):
        payload_chunk_estimate = ranking_payload.get("chunkEstimate")
        if isinstance(payload_chunk_estimate, dict):
            complexity = payload_chunk_estimate.get("movementComplexity")
            if complexity:
                return str(complexity)
    known = known_duration_hint_for(normalize_exercise_name(exercise_name))
    if known is not None:
        return str(known[2])
    return "unknown"


def exercise_requires_lower_body_motion(exercise_name: str) -> bool:
    normalized = normalize_exercise_name(exercise_name)
    return any(term in normalized for term in LOWER_BODY_DOMINANT_EXERCISE_TERMS)


def focused_motion_adjustment_for_exercise(
    exercise_name: str,
    motion_metrics: dict[str, Any],
    *,
    base_motion_score: float,
) -> tuple[float, list[str], dict[str, Any]]:
    if not exercise_requires_lower_body_motion(exercise_name):
        return base_motion_score, [], {
            "requiresLowerBodyMotion": False,
        }
    lower_body_range = parse_optional_float(motion_metrics.get("lowerBodyRootRelativeRangeRatio")) or 0.0
    lower_body_score = clamp_unit(lower_body_range / LOWER_BODY_MOTION_MIN_ARTICULATION_RATIO)
    focused_score = min(base_motion_score, lower_body_score)
    payload = {
        "requiresLowerBodyMotion": True,
        "lowerBodyRootRelativeRangeRatio": lower_body_range,
        "lowerBodyMotionScore": lower_body_score,
        "minLowerBodyRootRelativeRangeRatio": LOWER_BODY_MOTION_MIN_ARTICULATION_RATIO,
    }
    reasons = ["weak_lower_body_motion_penalty"] if lower_body_score < 1.0 else []
    return focused_score, reasons, payload


def apply_loop_continuity_adjustment(item: ReviewItem, ranking: LoopRanking) -> LoopRanking:
    if not DETERMINISTIC_REVIEW_VALIDATION_ENABLED:
        reasons = list(ranking.reasons)
        payload = dict(ranking.payload or {})
        try:
            motion_metrics = compute_motion_strength_metrics(item.skeleton_path)
        except Exception:
            motion_metrics = empty_motion_strength_metrics()
            reasons.append("deterministic_motion_metrics_unavailable")
        base_motion_score = clamp_unit(parse_optional_float(motion_metrics.get("motionStrengthScore")) or 0.0)
        focused_motion_score, focused_reasons, focused_payload = focused_motion_adjustment_for_exercise(
            item.exercise_name,
            motion_metrics,
            base_motion_score=base_motion_score,
        )
        adjusted_score = ranking.score
        if focused_motion_score < base_motion_score:
            multiplier = WEAK_FOCUSED_MOTION_SCORE_MULTIPLIER_FLOOR + (
                (1.0 - WEAK_FOCUSED_MOTION_SCORE_MULTIPLIER_FLOOR) * focused_motion_score
            )
            adjusted_score = min(adjusted_score, ranking.score * multiplier)
            focused_payload["focusedMotionScoreMultiplier"] = multiplier
        else:
            focused_payload["focusedMotionScoreMultiplier"] = 1.0
        payload["deterministicReviewValidationEnabled"] = False
        payload["deterministicReviewValidationSkipped"] = True
        payload["motionStrengthScore"] = focused_motion_score
        payload["motionStrengthMetrics"] = motion_metrics
        payload["focusedMotionScore"] = focused_motion_score
        payload["focusedMotionMetrics"] = focused_payload
        return LoopRanking(
            score=clamp_unit(adjusted_score),
            reasons=dedupe_text([*reasons, *focused_reasons, "deterministic_review_validation_skipped"]),
            raw_response=ranking.raw_response,
            payload=payload,
            model_score=clamp_unit(adjusted_score),
            continuity_score=ranking.continuity_score,
            continuity_metrics=ranking.continuity_metrics,
        )
    continuity_metrics = compute_loop_continuity_metrics(item.skeleton_path)
    continuity_score = float(continuity_metrics["continuityScore"])
    loop_bridge_metrics = compute_loop_bridge_quality_metrics(item.skeleton_path)
    loop_bridge_score = float(loop_bridge_metrics["loopBridgeQualityScore"])
    loopability_score = min(continuity_score, loop_bridge_score)
    loop_continuity_required = False
    effective_loopability_score = 1.0
    preview_readability_metrics = compute_preview_readability_metrics(
        item.skeleton_path,
        camera_yaw_degrees=parse_optional_float(item.settings_options.get("cameraYawDegrees")) or 45.0,
    )
    preview_readability_score = float(preview_readability_metrics["previewReadabilityScore"])
    motion_metrics = compute_motion_strength_metrics(item.skeleton_path)
    motion_score = float(motion_metrics["motionStrengthScore"])
    kinematic_metrics = compute_kinematic_plausibility_metrics(item.skeleton_path)
    kinematic_score = float(kinematic_metrics["kinematicPlausibilityScore"])
    hand_lock_arm_metrics = compute_hand_lock_arm_distortion_metrics(item.skeleton_path)
    paired_hands_metrics = compute_paired_hands_preservation_metrics(item.skeleton_path)
    motion_score = min(motion_score, kinematic_score)
    focused_motion_score, focused_reasons, focused_payload = focused_motion_adjustment_for_exercise(
        item.exercise_name,
        motion_metrics,
        base_motion_score=motion_score,
    )
    motion_score = focused_motion_score
    model_full_rep_motion = parse_optional_float((ranking.payload or {}).get("full_rep_motion") if isinstance(ranking.payload, dict) else None)
    if model_full_rep_motion is not None:
        motion_score = min(motion_score, clamp_unit(model_full_rep_motion))
    source_motion_metrics = None
    source_capture_ratio = None
    source_capture_penalty_applied = False
    source_capture_penalty_reason = None
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
            source_capture_penalty_applied = True
            motion_score = min(motion_score, capture_score)
    adjusted_score = clamp_unit(
        ranking.score * LOOP_MODEL_SCORE_WEIGHT
        + effective_loopability_score * LOOP_CONTINUITY_SCORE_WEIGHT
        + motion_score * LOOP_MOTION_SCORE_WEIGHT
    )
    adjusted_score = clamp_unit(
        adjusted_score
        + (preview_readability_score - 0.5) * PREVIEW_READABILITY_SCORE_WEIGHT
    )
    reasons = list(ranking.reasons)
    reasons.append("loop_continuity_not_required")
    if (
        source_capture_ratio is not None
        and source_motion_metrics is not None
        and source_capture_penalty_applied
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
    if bool(item.settings_options.get("lockPlantedHands")) and bool(hand_lock_arm_metrics.get("severeArmDistortion")):
        adjusted_score = min(adjusted_score, LOOP_HAND_LOCK_ARM_DISTORTION_SCORE_CAP)
        reasons.append("hand_lock_arm_distortion_penalty")
    if (
        bool(paired_hands_metrics.get("severePairedHandsDistortion"))
    ):
        adjusted_score = min(adjusted_score, LOOP_PAIRED_HANDS_DISTORTION_SCORE_CAP)
        reasons.append("paired_hands_distortion_penalty")
    payload = dict(ranking.payload or {})
    payload["modelScore"] = ranking.score
    payload["continuityScore"] = continuity_score
    payload["continuityMetrics"] = continuity_metrics
    payload["loopabilityScore"] = loopability_score
    payload["effectiveLoopabilityScore"] = effective_loopability_score
    payload["loopContinuityRequired"] = loop_continuity_required
    payload["loopBridgeQualityScore"] = loop_bridge_score
    payload["loopBridgeQualityMetrics"] = loop_bridge_metrics
    payload["motionStrengthScore"] = motion_score
    payload["motionStrengthMetrics"] = motion_metrics
    payload["focusedMotionScore"] = motion_score
    payload["focusedMotionMetrics"] = focused_payload
    payload["previewReadabilityScore"] = preview_readability_score
    payload["previewReadabilityMetrics"] = preview_readability_metrics
    payload["kinematicPlausibilityScore"] = kinematic_score
    payload["kinematicPlausibilityMetrics"] = kinematic_metrics
    payload["handLockArmDistortionMetrics"] = hand_lock_arm_metrics
    payload["cleanupInterpretation"] = item.cleanup_interpretation
    payload["pairedHandsPreservationMetrics"] = paired_hands_metrics
    if source_motion_metrics is not None:
        payload["sourceMotionStrengthMetrics"] = source_motion_metrics
    if source_capture_ratio is not None:
        payload["sourceMotionCaptureRatio"] = source_capture_ratio
        payload["sourceMotionCapturePenaltyApplied"] = source_capture_penalty_applied
        if source_capture_penalty_reason is not None:
            payload["sourceMotionCapturePenaltySkippedReason"] = source_capture_penalty_reason
    return LoopRanking(
        score=adjusted_score,
        reasons=dedupe_text([*reasons, *focused_reasons]),
        raw_response=ranking.raw_response,
        payload=payload,
        model_score=adjusted_score,
        continuity_score=continuity_score,
        continuity_metrics=continuity_metrics,
    )


def source_capture_time_range_for_item(item: ReviewItem) -> tuple[float, float] | None:
    if not item.llm_time_range_cut_applied:
        return None
    if item.loop_end_seconds <= item.loop_start_seconds:
        return None
    return item.loop_start_seconds, item.loop_end_seconds


def should_apply_source_capture_penalty(
    item: ReviewItem,
    *,
    source_range: tuple[float, float] | None,
    model_full_rep_motion: float | None,
) -> bool:
    if source_range is None:
        return True
    if model_full_rep_motion is None or model_full_rep_motion < LOOP_MIN_STRONG_MODEL_FULL_REP_MOTION:
        return True
    if item.source_skeleton_path is None or not item.source_skeleton_path.exists():
        return True
    return not source_range_covers_skeleton_timeline(
        item.source_skeleton_path,
        source_range,
        minimum_coverage=LOOP_SOURCE_FULL_SPAN_COVERAGE_MIN,
    )


def source_range_covers_skeleton_timeline(
    skeleton_path: Path,
    source_range: tuple[float, float],
    *,
    minimum_coverage: float,
) -> bool:
    try:
        payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    timeline = skeleton_source_timeline_bounds(payload)
    if timeline is None:
        return False
    source_start, source_end = source_range
    timeline_start, timeline_end = timeline
    if source_end <= source_start or timeline_end <= timeline_start:
        return False
    overlap_start = max(source_start, timeline_start)
    overlap_end = min(source_end, timeline_end)
    coverage = max(0.0, overlap_end - overlap_start) / max(1e-6, timeline_end - timeline_start)
    tolerance = max(0.05, 1.0 / max(1.0, parse_export_fps(payload)))
    boundary_match = (
        source_start <= timeline_start + tolerance
        and source_end >= timeline_end - tolerance
    )
    return coverage >= minimum_coverage and boundary_match


def skeleton_source_timeline_bounds(payload: dict[str, Any]) -> tuple[float, float] | None:
    frames_value = payload.get("frames")
    if not isinstance(frames_value, list):
        return None
    frames = [
        frame
        for frame in frames_value
        if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))
    ]
    if len(frames) < 2:
        return None
    source_times = [
        parsed
        for frame in frames
        if (parsed := parse_optional_float(frame.get("sourceTimeSec"))) is not None
    ]
    if len(source_times) >= 2:
        return min(source_times), max(source_times)
    time_values = [
        parsed
        for frame in frames
        if (parsed := parse_optional_float(frame.get("timeSec"))) is not None
    ]
    if len(time_values) >= 2:
        return min(time_values), max(time_values)
    duration = parse_optional_float(payload.get("durationSec"))
    if duration is not None and duration > 0.0:
        return 0.0, duration
    fps = parse_export_fps(payload)
    frame_indices = [
        parsed
        for frame in frames
        if (parsed := parse_optional_float(frame.get("frameIndex"))) is not None
    ]
    if len(frame_indices) >= 2 and fps > 0.0:
        return min(frame_indices) / fps, max(frame_indices) / fps
    return 0.0, (len(frames) - 1) / max(1.0, fps)


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


def compute_hand_lock_arm_distortion_metrics(skeleton_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_hand_lock_arm_distortion_metrics()
    return compute_hand_lock_arm_distortion_metrics_from_payload(payload)


def compute_hand_lock_arm_distortion_metrics_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    frames_value = payload.get("frames")
    if not isinstance(frames_value, list):
        return empty_hand_lock_arm_distortion_metrics()
    left_angles: list[float] = []
    right_angles: list[float] = []
    bilateral_diffs: list[float] = []
    for frame in frames_value:
        if not isinstance(frame, dict) or bool(frame.get("syntheticLoopBridge")):
            continue
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        left = joint_angle_from_payload(joints, "left_shoulder", "left_elbow", "left_wrist")
        right = joint_angle_from_payload(joints, "right_shoulder", "right_elbow", "right_wrist")
        if left is not None:
            left_angles.append(left)
        if right is not None:
            right_angles.append(right)
        if left is not None and right is not None:
            bilateral_diffs.append(abs(left - right))
    if len(bilateral_diffs) < 3:
        return empty_hand_lock_arm_distortion_metrics(frame_count=len(bilateral_diffs))
    median_diff = statistics.median(bilateral_diffs)
    max_diff = max(bilateral_diffs)
    all_angles = [*left_angles, *right_angles]
    min_angle = min(all_angles) if all_angles else 180.0
    max_angle = max(all_angles) if all_angles else 0.0
    extreme_count = sum(
        1
        for angle in all_angles
        if angle <= HAND_LOCK_ARM_EXTREME_LOW_DEGREES or angle >= HAND_LOCK_ARM_EXTREME_HIGH_DEGREES
    )
    severe = (
        median_diff >= HAND_LOCK_ARM_BILATERAL_MEDIAN_DIFF_DEGREES
        and max_diff >= HAND_LOCK_ARM_BILATERAL_MAX_DIFF_DEGREES
        and extreme_count >= max(3, len(all_angles) // 5)
    )
    return {
        "severeArmDistortion": severe,
        "frameCount": len(bilateral_diffs),
        "medianBilateralElbowAngleDifferenceDegrees": median_diff,
        "maxBilateralElbowAngleDifferenceDegrees": max_diff,
        "minElbowAngleDegrees": min_angle,
        "maxElbowAngleDegrees": max_angle,
        "extremeElbowAngleFrameCount": extreme_count,
    }


def empty_hand_lock_arm_distortion_metrics(*, frame_count: int = 0) -> dict[str, Any]:
    return {
        "severeArmDistortion": False,
        "frameCount": frame_count,
        "medianBilateralElbowAngleDifferenceDegrees": 0.0,
        "maxBilateralElbowAngleDifferenceDegrees": 0.0,
        "minElbowAngleDegrees": None,
        "maxElbowAngleDegrees": None,
        "extremeElbowAngleFrameCount": 0,
    }


def compute_paired_hands_preservation_metrics(skeleton_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_paired_hands_preservation_metrics()
    return compute_paired_hands_preservation_metrics_from_payload(payload)


def compute_paired_hands_preservation_metrics_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    frames_value = payload.get("frames")
    joint_names_value = payload.get("jointNames")
    if not isinstance(frames_value, list) or not isinstance(joint_names_value, list):
        return empty_paired_hands_preservation_metrics()
    joint_names = {str(name) for name in joint_names_value}
    endpoint_pair = next(
        (
            (left, right)
            for left, right in (("left_hand", "right_hand"), ("left_wrist", "right_wrist"))
            if left in joint_names and right in joint_names
        ),
        None,
    )
    if endpoint_pair is None:
        return empty_paired_hands_preservation_metrics()
    left_endpoint, right_endpoint = endpoint_pair
    frames = [
        frame
        for frame in frames_value
        if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))
    ]
    endpoint_left: list[list[float]] = []
    endpoint_right: list[list[float]] = []
    elbow_left: list[float] = []
    elbow_right: list[float] = []
    source_endpoint_left: list[list[float]] = []
    source_endpoint_right: list[list[float]] = []
    source_elbow_left: list[float] = []
    source_elbow_right: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        left = joints.get(left_endpoint)
        right = joints.get(right_endpoint)
        if is_point3(left) and is_point3(right):
            endpoint_left.append(point3_to_float_list(left))
            endpoint_right.append(point3_to_float_list(right))
        left_angle = joint_angle_from_payload(joints, "left_shoulder", "left_elbow", "left_wrist")
        right_angle = joint_angle_from_payload(joints, "right_shoulder", "right_elbow", "right_wrist")
        if left_angle is not None:
            elbow_left.append(left_angle)
        if right_angle is not None:
            elbow_right.append(right_angle)
        source_joints = frame.get("sourceJoints")
        if isinstance(source_joints, dict):
            source_left = source_joints.get(left_endpoint)
            source_right = source_joints.get(right_endpoint)
            if is_point3(source_left) and is_point3(source_right):
                source_endpoint_left.append(point3_to_float_list(source_left))
                source_endpoint_right.append(point3_to_float_list(source_right))
            source_left_angle = joint_angle_from_payload(source_joints, "left_shoulder", "left_elbow", "left_wrist")
            source_right_angle = joint_angle_from_payload(source_joints, "right_shoulder", "right_elbow", "right_wrist")
            if source_left_angle is not None:
                source_elbow_left.append(source_left_angle)
            if source_right_angle is not None:
                source_elbow_right.append(source_right_angle)
    if len(endpoint_left) < 3 or len(endpoint_right) < 3:
        return empty_paired_hands_preservation_metrics(frame_count=min(len(endpoint_left), len(endpoint_right)))
    spacing_values = [
        point_distance(left, right)
        for left, right in zip(endpoint_left, endpoint_right)
    ]
    median_spacing = statistics.median(spacing_values)
    spacing_range = max(spacing_values) - min(spacing_values)
    spacing_instability_ratio = spacing_range / max(median_spacing, 1e-6)
    left_travel = point_track_range(endpoint_left)
    right_travel = point_track_range(endpoint_right)
    shared_points = [
        [
            (left[axis] + right[axis]) * 0.5
            for axis in range(3)
        ]
        for left, right in zip(endpoint_left, endpoint_right)
    ]
    shared_travel = point_track_range(shared_points)
    same_phase = paired_track_same_phase_correlation(endpoint_left, endpoint_right)
    source_shared_travel = None
    shared_travel_capture_ratio = None
    if len(source_endpoint_left) == len(endpoint_left) and len(source_endpoint_right) == len(endpoint_right):
        source_shared_points = [
            [
                (left[axis] + right[axis]) * 0.5
                for axis in range(3)
            ]
            for left, right in zip(source_endpoint_left, source_endpoint_right)
        ]
        source_shared_travel = point_track_range(source_shared_points)
        if source_shared_travel > 1e-6:
            shared_travel_capture_ratio = clamp_unit(shared_travel / source_shared_travel)
    elbow_range = max(
        max(elbow_left) - min(elbow_left) if len(elbow_left) >= 2 else 0.0,
        max(elbow_right) - min(elbow_right) if len(elbow_right) >= 2 else 0.0,
    )
    source_elbow_range = max(
        max(source_elbow_left) - min(source_elbow_left) if len(source_elbow_left) >= 2 else 0.0,
        max(source_elbow_right) - min(source_elbow_right) if len(source_elbow_right) >= 2 else 0.0,
    )
    elbow_range_capture_ratio = (
        clamp_unit(elbow_range / source_elbow_range)
        if source_elbow_range > 1e-6
        else None
    )
    severe = (
        spacing_instability_ratio > PAIRED_HANDS_MAX_SPACING_INSTABILITY_RATIO
        or (
            shared_travel_capture_ratio is not None
            and shared_travel_capture_ratio < PAIRED_HANDS_MIN_SOURCE_CAPTURE_RATIO
        )
        or (
            elbow_range_capture_ratio is not None
            and elbow_range_capture_ratio < PAIRED_HANDS_MIN_SOURCE_CAPTURE_RATIO
        )
        or same_phase < PAIRED_HANDS_MIN_SAME_PHASE_CORRELATION
    )
    return {
        "severePairedHandsDistortion": severe,
        "frameCount": len(endpoint_left),
        "endpointPair": [left_endpoint, right_endpoint],
        "medianHandSpacing": median_spacing,
        "handSpacingRange": spacing_range,
        "handSpacingInstabilityRatio": spacing_instability_ratio,
        "samePhaseCorrelation": same_phase,
        "leftEndpointTravel": left_travel,
        "rightEndpointTravel": right_travel,
        "sharedHandTravel": shared_travel,
        "sourceSharedHandTravel": source_shared_travel,
        "sharedHandTravelCaptureRatio": shared_travel_capture_ratio,
        "elbowFlexionRangeDegrees": elbow_range,
        "sourceElbowFlexionRangeDegrees": source_elbow_range if source_elbow_range > 0.0 else None,
        "elbowFlexionRangeCaptureRatio": elbow_range_capture_ratio,
        "spacingInstabilityThreshold": PAIRED_HANDS_MAX_SPACING_INSTABILITY_RATIO,
        "sourceCaptureRatioThreshold": PAIRED_HANDS_MIN_SOURCE_CAPTURE_RATIO,
        "samePhaseCorrelationThreshold": PAIRED_HANDS_MIN_SAME_PHASE_CORRELATION,
    }


def empty_paired_hands_preservation_metrics(*, frame_count: int = 0) -> dict[str, Any]:
    return {
        "severePairedHandsDistortion": False,
        "frameCount": frame_count,
        "endpointPair": None,
        "medianHandSpacing": None,
        "handSpacingRange": None,
        "handSpacingInstabilityRatio": None,
        "samePhaseCorrelation": None,
        "leftEndpointTravel": 0.0,
        "rightEndpointTravel": 0.0,
        "sharedHandTravel": 0.0,
        "sourceSharedHandTravel": None,
        "sharedHandTravelCaptureRatio": None,
        "elbowFlexionRangeDegrees": 0.0,
        "sourceElbowFlexionRangeDegrees": None,
        "elbowFlexionRangeCaptureRatio": None,
        "spacingInstabilityThreshold": PAIRED_HANDS_MAX_SPACING_INSTABILITY_RATIO,
        "sourceCaptureRatioThreshold": PAIRED_HANDS_MIN_SOURCE_CAPTURE_RATIO,
        "samePhaseCorrelationThreshold": PAIRED_HANDS_MIN_SAME_PHASE_CORRELATION,
    }


def paired_track_same_phase_correlation(left_points: list[list[float]], right_points: list[list[float]]) -> float:
    if len(left_points) != len(right_points) or len(left_points) < 3:
        return 0.0
    correlations: list[float] = []
    for axis in range(3):
        left_values = [point[axis] for point in left_points]
        right_values = [point[axis] for point in right_points]
        correlation = pearson_correlation(left_values, right_values)
        if correlation is not None:
            correlations.append(correlation)
    return sum(correlations) / len(correlations) if correlations else 0.0


def pearson_correlation(left_values: list[float], right_values: list[float]) -> float | None:
    if len(left_values) != len(right_values) or len(left_values) < 3:
        return None
    left_mean = sum(left_values) / len(left_values)
    right_mean = sum(right_values) / len(right_values)
    left_diffs = [value - left_mean for value in left_values]
    right_diffs = [value - right_mean for value in right_values]
    left_energy = sum(value * value for value in left_diffs)
    right_energy = sum(value * value for value in right_diffs)
    if left_energy <= 1e-12 or right_energy <= 1e-12:
        return None
    numerator = sum(left * right for left, right in zip(left_diffs, right_diffs))
    return max(-1.0, min(1.0, numerator / math.sqrt(left_energy * right_energy)))


def point3_to_float_list(point: Any) -> list[float]:
    return [float(point[0]), float(point[1]), float(point[2])]


def joint_angle_from_payload(
    joints: dict[str, Any],
    start_joint: str,
    mid_joint: str,
    end_joint: str,
) -> float | None:
    start = joints.get(start_joint)
    mid = joints.get(mid_joint)
    end = joints.get(end_joint)
    if not is_point3(start) or not is_point3(mid) or not is_point3(end):
        return None
    return joint_angle_degrees(
        [float(start[0]), float(start[1]), float(start[2])],
        [float(mid[0]), float(mid[1]), float(mid[2])],
        [float(end[0]), float(end[1]), float(end[2])],
    )


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

    endpoint_severity = endpoint_body_ratio / LOOP_BRIDGE_ENDPOINT_SEVERE_BODY_RATIO
    bridge_step_ratio_severity = (
        bridge_step_ratio / LOOP_BRIDGE_STEP_RATIO
        if (
            bridge_step_ratio is not None
            and bridge_step_body_ratio >= LOOP_BRIDGE_STEP_BODY_RATIO
        )
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
        "endpointSevereBodyRatioThreshold": LOOP_BRIDGE_ENDPOINT_SEVERE_BODY_RATIO,
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
    candidates = score_review_windows_by_skeleton_motion(
        item,
        windows,
    )
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
        effective_loopability_score = 1.0
        score = clamp_unit(
            motion_score * WINDOW_MOTION_SCORE_WEIGHT
            + effective_loopability_score * WINDOW_CONTINUITY_SCORE_WEIGHT
        )
        score = clamp_unit(
            score
            + (preview_readability_score - 0.5) * PREVIEW_READABILITY_SCORE_WEIGHT
        )
        score = min(score, kinematic_score)
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


def propose_tight_active_motion_window(
    item: ReviewItem,
    timeline_window: DetectionWindow,
    *,
    padding_seconds: float = 0.25,
) -> ActiveMotionWindowProposal | None:
    skeleton_proposal = propose_tight_skeleton_motion_window(
        item,
        timeline_window,
        padding_seconds=padding_seconds,
    )
    if skeleton_proposal is not None:
        return skeleton_proposal
    return propose_tight_source_pixel_motion_window(
        item,
        timeline_window,
        padding_seconds=padding_seconds,
    )


def propose_tight_skeleton_motion_window(
    item: ReviewItem,
    timeline_window: DetectionWindow,
    *,
    padding_seconds: float,
) -> ActiveMotionWindowProposal | None:
    try:
        payload = json.loads(item.skeleton_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    video_window = DetectionWindow(
        index=timeline_window.index,
        start_seconds=max(0.0, timeline_window.start_seconds - max(0.0, item.loop_start_seconds)),
        end_seconds=max(0.0, timeline_window.end_seconds - max(0.0, item.loop_start_seconds)),
    )
    frames = skeleton_frames_for_review_window(
        payload,
        video_window=video_window,
        timeline_window=timeline_window,
    )
    if len(frames) < 4:
        return None
    joint_names_value = payload.get("jointNames")
    if not isinstance(joint_names_value, list):
        return None
    joint_names = [str(name) for name in joint_names_value]
    joint_tracks, body_height = skeleton_joint_tracks_and_body_height(frames, joint_names)
    if body_height <= 1e-6 or not joint_tracks:
        return None
    frame_times = [
        frame_time_seconds(frame, fallback_index=index, fps=parse_export_fps(payload))
        for index, frame in enumerate(frames)
    ]
    motion_values: list[float] = [0.0]
    for index in range(1, len(frames)):
        displacements: list[float] = []
        for joint_name, points in joint_tracks.items():
            if joint_name in {"pelvis", "hips", "root"}:
                continue
            if index >= len(points):
                continue
            displacements.append(point_distance(points[index - 1], points[index]) / body_height)
        motion_values.append(statistics.median(displacements) if displacements else 0.0)
    smoothed = smooth_series(motion_values, radius=2)
    max_motion = max(smoothed) if smoothed else 0.0
    if max_motion <= 1e-6:
        return None
    threshold = max(0.003, max_motion * 0.20)
    active_indices = [index for index, value in enumerate(smoothed) if value >= threshold]
    if len(active_indices) < 2:
        return None
    active_group = strongest_merged_active_group(
        active_indices,
        smoothed,
        frame_times,
        max_internal_pause_seconds=1.75,
    )
    if len(active_group) < 2:
        return None
    start_index = max(0, active_group[0])
    end_index = min(len(frame_times) - 1, active_group[-1])
    start_seconds = max(timeline_window.start_seconds, frame_times[start_index] - padding_seconds)
    end_seconds = min(timeline_window.end_seconds, frame_times[end_index] + padding_seconds)
    min_duration = 0.75
    if end_seconds - start_seconds < min_duration:
        center = (start_seconds + end_seconds) * 0.5
        start_seconds = max(timeline_window.start_seconds, center - min_duration * 0.5)
        end_seconds = min(timeline_window.end_seconds, center + min_duration * 0.5)
    full_duration = max(1e-6, timeline_window.end_seconds - timeline_window.start_seconds)
    active_duration = max(0.0, end_seconds - start_seconds)
    if active_duration >= full_duration - 0.10:
        return None
    return ActiveMotionWindowProposal(
        window=DetectionWindow(
            index=timeline_window.index,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        ),
        metrics={
            "source": "skeleton_active_motion_threshold",
            "threshold": threshold,
            "maxMotion": max_motion,
            "activeFrameCount": len(active_indices),
            "selectedActiveFrameCount": len(active_group),
            "frameCount": len(frames),
            "paddingSeconds": padding_seconds,
            "fullDurationSeconds": full_duration,
            "activeDurationSeconds": active_duration,
        },
    )


def propose_tight_source_pixel_motion_window(
    item: ReviewItem,
    timeline_window: DetectionWindow,
    *,
    padding_seconds: float,
) -> ActiveMotionWindowProposal | None:
    source_video_path = item.candidate_workspace / "input" / "selected_segment.mp4"
    if not source_video_path.exists():
        source_video_path = item.candidate_workspace / "input" / "source.mp4"
    if not source_video_path.exists():
        return None
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return None
    capture = cv2.VideoCapture(str(source_video_path))
    if not capture.isOpened():
        return None
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or frame_count <= 2:
            return None
        duration = frame_count / fps
        start_seconds = max(0.0, timeline_window.start_seconds)
        end_seconds = min(duration, timeline_window.end_seconds)
        if end_seconds <= start_seconds:
            return None
        sample_fps = 4.0
        sample_count = max(4, int(math.ceil((end_seconds - start_seconds) * sample_fps)) + 1)
        times = [
            start_seconds + (end_seconds - start_seconds) * index / max(1, sample_count - 1)
            for index in range(sample_count)
        ]
        gray_frames = []
        for time_seconds in times:
            capture.set(cv2.CAP_PROP_POS_MSEC, time_seconds * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            resized = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            gray_frames.append(gray)
        if len(gray_frames) < 4:
            return None
        motion_values = [0.0]
        for previous, current in zip(gray_frames, gray_frames[1:]):
            diff = cv2.absdiff(previous, current)
            motion_values.append(float(np.mean(diff)) / 255.0)
        smoothed = smooth_series(motion_values, radius=1)
        max_motion = max(smoothed) if smoothed else 0.0
        if max_motion <= 1e-6:
            return None
        threshold = max(0.01, max_motion * 0.20)
        active_indices = [index for index, value in enumerate(smoothed) if value >= threshold]
        if len(active_indices) < 2:
            return None
        active_group = strongest_merged_active_group(
            active_indices,
            smoothed,
            times,
            max_internal_pause_seconds=1.75,
        )
        if len(active_group) < 2:
            return None
        active_start = max(0, active_group[0])
        active_end = min(len(times) - 1, active_group[-1])
        proposed_start = max(timeline_window.start_seconds, times[active_start] - padding_seconds)
        proposed_end = min(timeline_window.end_seconds, times[active_end] + padding_seconds)
        full_duration = max(1e-6, timeline_window.end_seconds - timeline_window.start_seconds)
        active_duration = max(0.0, proposed_end - proposed_start)
        if active_duration >= full_duration - 0.10:
            return None
        return ActiveMotionWindowProposal(
            window=DetectionWindow(
                index=timeline_window.index,
                start_seconds=proposed_start,
                end_seconds=proposed_end,
            ),
            metrics={
                "source": "source_pixel_motion_threshold",
                "threshold": threshold,
                "maxMotion": max_motion,
                "activeFrameCount": len(active_indices),
                "selectedActiveFrameCount": len(active_group),
                "frameCount": len(gray_frames),
                "paddingSeconds": padding_seconds,
                "fullDurationSeconds": full_duration,
                "activeDurationSeconds": active_duration,
            },
        )
    finally:
        capture.release()


def strongest_merged_active_group(
    active_indices: list[int],
    values: list[float],
    times: list[float],
    *,
    max_internal_pause_seconds: float,
) -> list[int]:
    if not active_indices:
        return []
    groups: list[list[int]] = [[active_indices[0]]]
    for index in active_indices[1:]:
        if index == groups[-1][-1] + 1:
            groups[-1].append(index)
        else:
            groups.append([index])
    merged_groups: list[list[int]] = []
    for group in groups:
        if not merged_groups:
            merged_groups.append(list(group))
            continue
        previous = merged_groups[-1]
        previous_time = times[previous[-1]] if previous[-1] < len(times) else float(previous[-1])
        current_time = times[group[0]] if group[0] < len(times) else float(group[0])
        if current_time - previous_time <= max_internal_pause_seconds:
            previous.extend(group)
        else:
            merged_groups.append(list(group))
    return max(
        merged_groups,
        key=lambda group: (
            sum(values[index] for index in group if 0 <= index < len(values)),
            len(group),
        ),
    )


def frame_time_seconds(frame: dict[str, Any], *, fallback_index: int, fps: float) -> float:
    source_time = parse_optional_float(frame.get("sourceTimeSec"))
    if source_time is not None:
        return source_time
    frame_index = parse_optional_float(frame.get("frameIndex"))
    effective_fps = fps if fps > 0 else 30.0
    return (frame_index if frame_index is not None else fallback_index) / effective_fps


def smooth_series(values: list[float], *, radius: int) -> list[float]:
    if radius <= 0 or len(values) <= 2:
        return list(values)
    smoothed: list[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        smoothed.append(sum(values[start:end]) / max(1, end - start))
    return smoothed


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
    pipeline_timings: dict[str, Any] = {
        "candidateWorkers": request.candidate_workers,
        "fallbackCandidates": request.fallback_candidates,
        "rankPreviewVariants": request.rank_preview_variants,
        "adaptivePreviewSettings": request.adaptive_preview_settings,
        "classifySupportDominance": request.classify_support_dominance,
        "whamRunSmplify": request.wham_run_smplify,
        "whamEstimateLocalOnly": request.wham_estimate_local_only,
        "useWhamDocker": request.use_wham_docker,
    }
    candidates = load_ranked_candidates_manifest(
        request.candidates_json,
        require_recommended_youtube_candidate=request.require_recommended_youtube_candidate,
    )
    request.workspace.mkdir(parents=True, exist_ok=True)
    candidate_results: list[dict[str, Any]] = []
    review_items: list[ReviewItem] = []
    review_item_entries: list[dict[str, Any]] = []
    effective_ranker = None
    if section_selection_enabled(request):
        effective_ranker = loop_ranker or rank_review_items_with_llama_cpp
    vision_ranker: LlamaCppVisionRanker | None = None
    support_dominance_classifier = None
    try:
        if loop_ranker is None and (
            request.classify_support_dominance
            or section_selection_enabled(request)
            or request.adaptive_preview_settings
            or request.pre_wham_source_validation
        ):
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
        if preview_baker is None:
            preview_baker = lambda preview_html_path, eligible_loops, candidate_workspace, review_frames, exercise_name=None: bake_preview_loops_with_playwright(
                preview_html_path,
                eligible_loops,
                candidate_workspace,
                review_frames,
                rank_preview_variants=request.rank_preview_variants,
                adaptive_preview_settings=request.adaptive_preview_settings,
                max_adaptive_preview_settings=request.max_adaptive_preview_settings,
                caption_images=vision_ranker.client.caption_images if vision_ranker is not None else None,
                exercise_name=exercise_name,
            )
        candidate_processing_started = time.perf_counter()
        candidate_results, review_items, review_item_entries = process_ranked_candidates_for_selection(
            candidates,
            request=request,
            preview_baker=preview_baker,
            support_dominance_classifier=support_dominance_classifier,
            source_cut_caption_images=(
                vision_ranker.client.caption_images
                if request.pre_wham_source_validation and vision_ranker is not None
                else None
            ),
        )
        pipeline_timings["candidateProcessingSeconds"] = elapsed_seconds(candidate_processing_started)
        pipeline_timings["processedCandidateCount"] = len(candidate_results)
        pipeline_timings["readyCandidateCount"] = sum(
            1 for item in candidate_results if item.get("status") == "ready_for_selection"
        )
        pipeline_timings["reviewItemCount"] = len(review_items)

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
        adaptive_preview_settings=bool(manifest.get("adaptivePreviewSettingsEnabled", False)),
        max_adaptive_preview_settings=int(manifest.get("maxAdaptivePreviewSettings") or 3),
        classify_support_dominance=False,
    )


def section_selection_enabled(request: BakeAndRankRequest) -> bool:
    return bool(request.select_preview_section or request.rank_preview_variants or request.adaptive_preview_settings)


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
    source_cut_caption_images: Callable[..., str] | None = None,
) -> tuple[list[dict[str, Any]], list[ReviewItem], list[dict[str, Any]]]:
    fallback_ready_target = max(1, request.fallback_candidates)
    candidates_to_process = candidates[:fallback_ready_target] if request.pre_wham_source_validation else candidates
    workers = max(1, min(request.candidate_workers, len(candidates_to_process)))
    if workers == 1:
        candidate_results: list[dict[str, Any]] = []
        review_items: list[ReviewItem] = []
        review_item_entries: list[dict[str, Any]] = []
        ready_candidate_count = 0
        for ranked_candidate in candidates_to_process:
            local_review_items: list[ReviewItem] = []
            local_review_item_entries: list[dict[str, Any]] = []
            result = process_ranked_candidate(
                ranked_candidate,
                request=request,
                preview_baker=preview_baker,
                review_items=local_review_items,
                review_item_entries=local_review_item_entries,
                support_dominance_classifier=support_dominance_classifier,
                source_cut_caption_images=source_cut_caption_images,
            )
            candidate_results.append(result)
            review_items.extend(local_review_items)
            review_item_entries.extend(local_review_item_entries)
            if result.get("status") == "ready_for_selection":
                ready_candidate_count += 1
            if not request.pre_wham_source_validation and ready_candidate_count >= fallback_ready_target:
                break
        return candidate_results, review_items, review_item_entries

    results_by_index: dict[int, tuple[dict[str, Any], list[ReviewItem], list[dict[str, Any]]]] = {}
    next_index = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        while (
            next_index < len(candidates_to_process)
            and len(futures) < workers
            and ready_candidate_capacity_in_launched_prefix(results_by_index, next_index) < fallback_ready_target
        ):
            ranked_candidate = candidates_to_process[next_index]
            futures[
                executor.submit(
                    process_ranked_candidate_isolated,
                    ranked_candidate,
                    request,
                    preview_baker,
                    support_dominance_classifier,
                    source_cut_caption_images,
                )
            ] = next_index
            next_index += 1
        while futures:
            for future in as_completed(list(futures)):
                index = futures.pop(future)
                results_by_index[index] = future.result()
                if (
                    not request.pre_wham_source_validation
                    and ready_candidate_count_in_prefix(results_by_index) >= fallback_ready_target
                ):
                    for pending in futures:
                        pending.cancel()
                    futures.clear()
                    break
                while (
                    next_index < len(candidates_to_process)
                    and len(futures) < workers
                    and (
                        request.pre_wham_source_validation
                        or ready_candidate_capacity_in_launched_prefix(results_by_index, next_index)
                        < fallback_ready_target
                    )
                ):
                    ranked_candidate = candidates_to_process[next_index]
                    futures[
                        executor.submit(
                            process_ranked_candidate_isolated,
                            ranked_candidate,
                            request,
                            preview_baker,
                            support_dominance_classifier,
                            source_cut_caption_images,
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
        if not request.pre_wham_source_validation and ready_count >= fallback_ready_target:
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
    source_cut_caption_images: Callable[..., str] | None,
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
        source_cut_caption_images=source_cut_caption_images,
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
    source_cut_caption_images: Callable[..., str] | None = None,
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
        generate_result = generate_candidate_motion(
            ranked_candidate,
            request=request,
            source_cut_caption_images=source_cut_caption_images,
        )
        record_timing_seconds(result_payload, "generationSeconds", stage_started)
        result_payload.update(generation_to_manifest(generate_result))
        if generate_result.timings is not None:
            result_payload["generationTimings"] = generate_result.timings
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
            exercise_name=ranked_candidate.exercise_name,
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
                    cleanup_interpretation=artifact.cleanup_interpretation,
                    adaptive_preview_settings=artifact.adaptive_preview_settings,
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
    except SourceCandidateRejected as exc:
        result_payload["status"] = "skipped_pre_wham_source_validation"
        result_payload["failures"].append(
            {
                "reason": "pre_wham_source_validation_rejected",
                "message": str(exc),
            }
        )
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


def generate_candidate_motion(
    ranked_candidate: RankedCandidate,
    *,
    request: BakeAndRankRequest,
    source_cut_caption_images: Callable[..., str] | None = None,
) -> GenerateResult:
    source_started = time.perf_counter()
    video_path = prepare_candidate_input_video(
        ranked_candidate,
        request=request,
        source_cut_caption_images=source_cut_caption_images,
    )
    source_preparation_seconds = elapsed_seconds(source_started)
    generation_started = time.perf_counter()
    result = run_generation_pipeline(
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
            spinepose_enabled=request.spinepose_enabled,
            spinepose_json_dir=request.spinepose_json_dir,
            spinepose_command=request.spinepose_command,
            spinepose_output_dir=request.spinepose_output_dir,
            spinepose_mode=request.spinepose_mode,
            spinepose_model_version=request.spinepose_model_version,
            spinepose_device=request.spinepose_device,
            spinepose_reuse_cache=request.spinepose_reuse_cache,
            spinepose_gain=request.spinepose_gain,
            spinepose_max_degrees=request.spinepose_max_degrees,
            spinepose_axis=request.spinepose_axis,
            spinepose_invert=request.spinepose_invert,
            spinepose_smoothing_window=request.spinepose_smoothing_window,
            spinepose_arm_counter_rotation=request.spinepose_arm_counter_rotation,
            spinepose_merge_mode=request.spinepose_merge_mode,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )
    )
    if result.timings is not None:
        result.timings["sourcePreparationSeconds"] = source_preparation_seconds
        result.timings["generationPipelineCallSeconds"] = elapsed_seconds(generation_started)
    return result


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


def prepare_candidate_input_video(
    ranked_candidate: RankedCandidate,
    *,
    request: BakeAndRankRequest,
    source_cut_caption_images: Callable[..., str] | None = None,
) -> Path:
    candidate_workspace = request.workspace / ranked_candidate.workspace_slug
    source_dir = candidate_workspace / "source"
    source_video_path = copy_or_download_candidate_source(
        ranked_candidate,
        source_dir,
        youtube_cookies=request.youtube_cookies,
    )
    source_chunk_hint = ranked_candidate.source_chunk_hint
    pre_wham_caption_images = source_cut_caption_images if request.pre_wham_source_validation else None
    if not request.detect_source_segment:
        if source_chunk_hint is not None:
            return trim_ranked_source_chunk_hint(
                ranked_candidate=ranked_candidate,
                candidate_workspace=candidate_workspace,
                source_video_path=source_video_path,
                source_chunk_hint=source_chunk_hint,
            )
        return source_video_path
    cached_selected_segment = candidate_workspace / "input" / "selected_segment.mp4"
    cached_segment_selection = candidate_workspace / "segment_detection" / "segment_selection.json"
    if (
        request.reuse_wham_cache
        and cached_selected_segment.exists()
        and cached_segment_selection.exists()
        and cached_source_selection_matches_validation_mode(
            cached_segment_selection,
            pre_wham_source_validation=pre_wham_caption_images is not None,
        )
    ):
        return cached_selected_segment
    if should_use_ranked_source_chunk_directly(source_chunk_hint, request=request):
        if pre_wham_caption_images is not None:
            return choose_pre_wham_source_cut_or_reject(
                ranked_candidate=ranked_candidate,
                candidate_workspace=candidate_workspace,
                source_video_path=source_video_path,
                detection_source_video_path=source_video_path,
                source_window=DetectionWindow(
                    index=0,
                    start_seconds=source_chunk_hint.start_seconds,
                    end_seconds=source_chunk_hint.end_seconds,
                ),
                detection_source_offset_seconds=0.0,
                source_chunk_hint=source_chunk_hint,
                caption_images=pre_wham_caption_images,
            )
        return trim_ranked_source_chunk_hint(
            ranked_candidate=ranked_candidate,
            candidate_workspace=candidate_workspace,
            source_video_path=source_video_path,
            source_chunk_hint=source_chunk_hint,
        )
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
        use_llm=False,
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
    segment_model = request.segment_model or request.llama_cpp_model
    segment_server = LlamaCppVisionRanker(
        YouTubeRankingSettings(
            llama_cpp_base_url=segment_base_url,
            llama_cpp_model=segment_model,
            vision_llm_workers=request.segment_classification_workers,
            llama_cpp_temperature=request.llama_cpp_temperature,
            llama_cpp_top_p=request.llama_cpp_top_p,
            llama_cpp_top_k=request.llama_cpp_top_k,
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
                    llama_cpp_temperature=request.llama_cpp_temperature,
                    llama_cpp_top_p=request.llama_cpp_top_p,
                    llama_cpp_top_k=request.llama_cpp_top_k,
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
    if pre_wham_caption_images is not None:
        return choose_pre_wham_source_cut_or_reject(
            ranked_candidate=ranked_candidate,
            candidate_workspace=candidate_workspace,
            source_video_path=source_video_path,
            detection_source_video_path=detection_source_video_path,
            source_window=DetectionWindow(
                index=0,
                start_seconds=selected_span.start_seconds,
                end_seconds=selected_span.end_seconds,
            ),
            detection_source_offset_seconds=detection_source_offset_seconds,
            source_chunk_hint=source_chunk_hint,
            caption_images=pre_wham_caption_images,
            source_detection_result=detection_result,
            source_chunk_estimate=chunk_estimate,
            segment_settings={
                "windowSeconds": segment_window_seconds,
                "overlapSeconds": segment_overlap_seconds,
                "framesPerWindow": segment_frames_per_window,
                "classificationWorkers": request.segment_classification_workers,
                "refinementFramesPerWindow": segment_refinement_frames_per_window,
            },
        )
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
                "source": "segment_detection",
                "sourcePrepReason": "segment_detection",
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


def cached_source_selection_matches_validation_mode(
    segment_selection_path: Path,
    *,
    pre_wham_source_validation: bool,
) -> bool:
    if not pre_wham_source_validation:
        return True
    try:
        payload = json.loads(segment_selection_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(payload.get("preWhamSourceValidationEnabled")) or str(payload.get("sourcePrepReason")) == "pre_wham_source_window_choice"


def choose_pre_wham_source_cut_or_reject(
    *,
    ranked_candidate: RankedCandidate,
    candidate_workspace: Path,
    source_video_path: Path,
    detection_source_video_path: Path,
    source_window: DetectionWindow,
    detection_source_offset_seconds: float,
    source_chunk_hint: SourceChunkHint | None,
    caption_images: Callable[..., str],
    source_detection_result: Any | None = None,
    source_chunk_estimate: Any | None = None,
    segment_settings: dict[str, Any] | None = None,
) -> Path:
    chunk_estimate = source_chunk_estimate or estimate_chunking(
        exercise_name=ranked_candidate.exercise_name,
        use_llm=False,
    )
    segment_dir = candidate_workspace / "segment_detection"
    selection_dir = segment_dir / "pre_wham_source_candidates"
    source_choice = rank_source_video_cut_candidates_with_caption_images(
        video_path=detection_source_video_path,
        exercise_name=ranked_candidate.exercise_name,
        candidate_title=ranked_candidate.title,
        timeline_window=source_window,
        chunk_estimate=chunk_estimate,
        output_dir=selection_dir,
        frame_count=max(12, min(DEFAULT_LLM_REVIEW_FRAMES, frames_for_chunk_seconds(max(0.5, source_window.end_seconds - source_window.start_seconds)))),
        caption_images=caption_images,
    )
    if source_choice is None:
        write_pre_wham_source_selection_manifest(
            ranked_candidate=ranked_candidate,
            candidate_workspace=candidate_workspace,
            source_video_path=source_video_path,
            detection_source_video_path=detection_source_video_path,
            source_window=source_window,
            detection_source_offset_seconds=detection_source_offset_seconds,
            source_chunk_hint=source_chunk_hint,
            ranking=None,
            render_seconds=0.0,
            vlm_seconds=0.0,
            source_detection_result=source_detection_result,
            chunk_estimate=chunk_estimate,
            segment_settings=segment_settings,
        )
        raise SourceCandidateRejected("Pre-WHAM source validation found no source-window candidates.")
    ranking, render_seconds, vlm_seconds = source_choice
    write_pre_wham_source_selection_manifest(
        ranked_candidate=ranked_candidate,
        candidate_workspace=candidate_workspace,
        source_video_path=source_video_path,
        detection_source_video_path=detection_source_video_path,
        source_window=source_window,
        detection_source_offset_seconds=detection_source_offset_seconds,
        source_chunk_hint=source_chunk_hint,
        ranking=ranking,
        render_seconds=render_seconds,
        vlm_seconds=vlm_seconds,
        source_detection_result=source_detection_result,
        chunk_estimate=chunk_estimate,
        segment_settings=segment_settings,
    )
    if ranking.score <= 0.0:
        raise SourceCandidateRejected("Pre-WHAM source validation rejected the source window.")
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    start_seconds = parse_optional_float(payload.get("selected_section_start_seconds"))
    end_seconds = parse_optional_float(payload.get("selected_section_end_seconds"))
    if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
        raise SourceCandidateRejected("Pre-WHAM source validation returned no valid source cut.")
    selected_segment_path = candidate_workspace / "input" / "selected_segment.mp4"
    selected_segment_path.parent.mkdir(parents=True, exist_ok=True)
    trim_video(
        source_path=detection_source_video_path,
        output_path=selected_segment_path,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    return selected_segment_path


def write_pre_wham_source_selection_manifest(
    *,
    ranked_candidate: RankedCandidate,
    candidate_workspace: Path,
    source_video_path: Path,
    detection_source_video_path: Path,
    source_window: DetectionWindow,
    detection_source_offset_seconds: float,
    source_chunk_hint: SourceChunkHint | None,
    ranking: LoopRanking | None,
    render_seconds: float,
    vlm_seconds: float,
    source_detection_result: Any | None,
    chunk_estimate: Any,
    segment_settings: dict[str, Any] | None,
) -> None:
    segment_dir = candidate_workspace / "segment_detection"
    segment_dir.mkdir(parents=True, exist_ok=True)
    payload = ranking.payload if ranking is not None and isinstance(ranking.payload, dict) else {}
    start_seconds = parse_optional_float(payload.get("selected_section_start_seconds"))
    end_seconds = parse_optional_float(payload.get("selected_section_end_seconds"))
    selected_span = (
        {
            "startSeconds": start_seconds,
            "endSeconds": end_seconds,
            "confidence": ranking.score if ranking is not None else 0.0,
        }
        if start_seconds is not None and end_seconds is not None
        else None
    )
    selected_span_in_original_source = (
        {
            "startSeconds": detection_source_offset_seconds + start_seconds,
            "endSeconds": detection_source_offset_seconds + end_seconds,
            "confidence": ranking.score if ranking is not None else 0.0,
        }
        if start_seconds is not None and end_seconds is not None
        else None
    )
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
    manifest = {
        "role": "pre_wham_validated_source_cut",
        "source": "pre_wham_source_window_choice",
        "sourcePrepReason": "pre_wham_source_window_choice",
        "preWhamSourceValidationEnabled": True,
        "sourceVideoPath": str(source_video_path),
        "detectionSourceVideoPath": str(detection_source_video_path),
        "selectedSegmentPath": str(candidate_workspace / "input" / "selected_segment.mp4"),
        "exerciseName": ranked_candidate.exercise_name,
        "sourceChunkHint": source_chunk_hint_payload,
        "candidateSourceWindow": {
            "startSeconds": source_window.start_seconds,
            "endSeconds": source_window.end_seconds,
            "startSecondsInOriginalSource": detection_source_offset_seconds + source_window.start_seconds,
            "endSecondsInOriginalSource": detection_source_offset_seconds + source_window.end_seconds,
        },
        "chunkEstimate": {
            "repDurationMinSec": getattr(chunk_estimate, "rep_duration_min_sec", None),
            "repDurationMaxSec": getattr(chunk_estimate, "rep_duration_max_sec", None),
            "movementComplexity": getattr(chunk_estimate, "movement_complexity", None),
            "chunkSeconds": getattr(chunk_estimate, "chunk_seconds", None),
            "chunkOverlapSeconds": getattr(chunk_estimate, "chunk_overlap_seconds", None),
            "source": getattr(chunk_estimate, "source", None),
            "reason": getattr(chunk_estimate, "reason", None),
        },
        "segmentSettings": segment_settings,
        "selectedSpan": selected_span,
        "selectedSpanInOriginalSource": selected_span_in_original_source,
        "sourceCutRanking": None if ranking is None else ranking_to_manifest(ranking),
        "sourceCutRenderSeconds": render_seconds,
        "sourceCutVlmSeconds": vlm_seconds,
    }
    if source_detection_result is not None:
        manifest["sourceDetectionSpan"] = {
            "startSeconds": source_window.start_seconds,
            "endSeconds": source_window.end_seconds,
        }
    (segment_dir / "segment_selection.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def should_use_ranked_source_chunk_directly(
    source_chunk_hint: SourceChunkHint | None,
    *,
    request: BakeAndRankRequest,
) -> bool:
    if source_chunk_hint is None or source_chunk_hint.score is None:
        return False
    max_direct_chunk_seconds = min(
        request.segment_max_seconds,
        SOURCE_GATE_MAX_DIRECT_CHUNK_SECONDS,
    )
    return (
        source_chunk_hint.score >= SOURCE_GATE_STRONG_BEST_CHUNK_SCORE
        and source_chunk_hint.duration_seconds >= request.segment_min_seconds
        and source_chunk_hint.duration_seconds <= max_direct_chunk_seconds
    )


def trim_ranked_source_chunk_hint(
    *,
    ranked_candidate: RankedCandidate,
    candidate_workspace: Path,
    source_video_path: Path,
    source_chunk_hint: SourceChunkHint,
) -> Path:
    selected_segment_path = candidate_workspace / "input" / "selected_segment.mp4"
    selected_segment_path.parent.mkdir(parents=True, exist_ok=True)
    if selected_segment_path.exists():
        return selected_segment_path
    trim_video(
        source_path=source_video_path,
        output_path=selected_segment_path,
        start_seconds=source_chunk_hint.start_seconds,
        end_seconds=source_chunk_hint.end_seconds,
    )
    segment_dir = candidate_workspace / "segment_detection"
    segment_dir.mkdir(parents=True, exist_ok=True)
    (segment_dir / "segment_selection.json").write_text(
        json.dumps(
            {
                "role": "ranked_source_chunk_segment",
                "source": "ranked_best_chunk",
                "sourcePrepReason": "ranked_best_chunk",
                "sourceVideoPath": str(source_video_path),
                "selectedSegmentPath": str(selected_segment_path),
                "exerciseName": ranked_candidate.exercise_name,
                "selectedSpanInOriginalSource": {
                    "startSeconds": source_chunk_hint.start_seconds,
                    "endSeconds": source_chunk_hint.end_seconds,
                    "durationSeconds": source_chunk_hint.duration_seconds,
                    "score": source_chunk_hint.score,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
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
        "source": "segment_detection_fallback",
        "sourcePrepReason": "segment_detection_fallback",
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
    adaptive_preview_settings: bool = False,
    max_adaptive_preview_settings: int = 3,
    caption_images: Callable[..., str] | None = None,
    exercise_name: str | None = None,
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
            if adaptive_preview_settings and caption_images is not None:
                variants = plan_adaptive_preview_settings_variants(
                    page=page,
                    eligible_loop=eligible_loop,
                    base_options=base_options,
                    review_dir=review_dir,
                    artifact_base_label=artifact_base_label,
                    review_frames=review_frames,
                    motion_tuning_enabled=motion_tuning_enabled,
                    caption_images=caption_images,
                    max_variants=max_adaptive_preview_settings,
                    exercise_name=exercise_name,
                )
            elif rank_preview_variants:
                variants = preview_settings_variants(motion_tuning_enabled=motion_tuning_enabled)
            else:
                variants = [
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
                artifact_label = artifact_base_label if not (rank_preview_variants or adaptive_preview_settings) else f"{artifact_base_label}.{variant_id}"
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
                        cleanup_interpretation=str(
                            variant.get("cleanupInterpretation")
                            or options.get("cleanupInterpretation")
                            or "support_lock"
                        ),
                        adaptive_preview_settings=(
                            dict(variant["adaptivePreviewSettings"])
                            if isinstance(variant.get("adaptivePreviewSettings"), dict)
                            else None
                        ),
                    )
                )
        browser.close()
    return artifacts


def plan_adaptive_preview_settings_variants(
    *,
    page: Any,
    eligible_loop: EligibleLoop,
    base_options: dict[str, Any],
    review_dir: Path,
    artifact_base_label: str,
    review_frames: int,
    motion_tuning_enabled: bool,
    caption_images: Callable[..., str],
    max_variants: int,
    exercise_name: str | None = None,
) -> list[dict[str, Any]]:
    baseline_variant = {
        "id": "adaptive-baseline",
        "label": "Adaptive baseline",
        "options": {},
        "adaptivePreviewSettings": {
            "source": "baseline_defaults",
            "reason": "baseline_always_included",
        },
    }
    max_suggestions = max(0, min(3, int(max_variants or 0)))
    if max_suggestions <= 0:
        return [baseline_variant]
    try:
        baseline_export = page.evaluate(
            """({ loopIndex, options }) => window.exerciseMotionAutomation.bakeLoop(loopIndex, options)""",
            {"loopIndex": eligible_loop.loop_index, "options": base_options},
        )
        frame_indices = sample_review_frame_indices(baseline_export, review_frames)
        frame_data_urls = [
            page.evaluate(
                """({ frameIndex, options }) => window.exerciseMotionAutomation.renderFrame(frameIndex, options)""",
                {"frameIndex": frame_index, "options": base_options},
            )
            for frame_index in frame_indices
        ]
        planning_dir = review_dir / f"{artifact_base_label}.adaptive-settings-planning"
        contact_sheet_path = planning_dir / "baseline_contact_sheet.jpg"
        write_review_contact_sheet_from_data_urls(frame_data_urls, contact_sheet_path)
        raw = caption_images(
            frame_paths=[contact_sheet_path],
            prompt=build_adaptive_preview_settings_prompt(
                base_options=base_options,
                motion_tuning_enabled=motion_tuning_enabled,
                max_variants=max_suggestions,
                exercise_name=exercise_name,
            ),
        )
        planned = parse_adaptive_preview_settings_response(
            raw,
            base_options=base_options,
            motion_tuning_enabled=motion_tuning_enabled,
            max_variants=max_suggestions,
        )
        baseline_is_sufficient = parse_adaptive_preview_baseline_is_sufficient(raw)
        (planning_dir / "adaptive_settings_plan.json").write_text(
            json.dumps(
                {
                    "rawResponse": raw,
                    "baseOptions": base_options,
                    "baselineIsSufficient": baseline_is_sufficient,
                    "plannedVariants": planned,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if planned and baseline_is_sufficient is False:
            return planned
        return [baseline_variant, *planned]
    except Exception as exc:
        return [
            {
                **baseline_variant,
                "adaptivePreviewSettings": {
                    "source": "baseline_fallback_after_planning_failure",
                    "failureType": type(exc).__name__,
                    "failure": str(exc)[:500],
                },
            }
        ]


def build_adaptive_preview_settings_prompt(
    *,
    base_options: dict[str, Any],
    motion_tuning_enabled: bool,
    max_variants: int,
    exercise_name: str | None = None,
) -> str:
    exercise_context = (exercise_name or "").strip() or "unknown"
    return (
        "You are choosing preview post-processing settings before expensive variant baking.\n"
        f"Target exercise: {exercise_context}.\n"
        "You are looking at the baseline rendered preview contact sheet for one exercise motion. "
        "The baseline already uses the deterministic cleanup output.\n"
        f"Current baseline options: {json.dumps(base_options, sort_keys=True)}.\n"
        "Available preview tuning options and what they do:\n"
        f"{format_preview_tuning_options_for_prompt(motion_tuning_enabled=motion_tuning_enabled)}\n"
        "Goal: minimize the number of settings variants to bake while preserving a high chance of a readable Wear OS animation.\n"
        "Prefer the baseline when it already looks correct. Only suggest alternatives that are likely to improve a visible issue.\n"
        "If the body appears upside down, head/feet reversed, viewed from an unreadable angle, or confusing because of scene orientation, suggest the smallest orientation/settings change likely to fix it, such as sceneInverted, autoWorldAlignment, cameraYawDegrees, or cameraPitchDegrees.\n"
        "When suggesting any orientation or camera variant, include the final intended values for sceneInverted, autoWorldAlignment, cameraYawDegrees, and cameraPitchDegrees. "
        "Do not rely on inheriting an existing orientation flag; explicitly set sceneInverted false when the scene should not be flipped.\n"
        "Do not propose exhaustive permutations. Do not change camera settings unless readability is poor. "
        "Enable planted hand/foot locks when the movement has intended fixed support anchors or visibly sliding supports. "
        "For hand-supported or hanging bodyweight movements where the hands are intended support anchors, such as pull-ups, chin-ups, dead hangs, dips, rows with planted hands, push-ups, planks, or handstand work, strongly consider lockPlantedHands so the hands remain fixed relative to the support. "
        "Do not require visible sliding before enabling lockPlantedHands for these hand-supported cases when the preview remains plausible. "
        "Do not use lockYDrift to remove real vertical exercise motion; for squats, lunges, split squats, step-ups, jumps, cleans, snatches, or other level-changing lifts, pelvis/root height changes are usually the movement and must remain visible. "
        "Use lockYDrift only for camera/reconstruction floating where the body should stay at a stable height. "
        "For free hand or barbell/dumbbell motion, planted hand lock is usually wrong.\n"
        f"Return at most {max_variants} suggested variants. Each variant must include only known option keys.\n"
        "Return JSON only with keys: "
        "{\"variants\": [{\"id\": string, \"label\": string, \"settings\": object, \"reason\": string}], "
        "\"baseline_is_sufficient\": boolean, \"reasons\": [string]}."
    )


def parse_adaptive_preview_settings_response(
    raw: str,
    *,
    base_options: dict[str, Any],
    motion_tuning_enabled: bool,
    max_variants: int,
) -> list[dict[str, Any]]:
    try:
        payload = extract_json_object(raw)
    except Exception:
        return []
    variants_payload = payload.get("variants")
    if not isinstance(variants_payload, list):
        return []
    variants: list[dict[str, Any]] = []
    seen_signatures = {preview_options_signature(base_options, motion_tuning_enabled=motion_tuning_enabled)}
    for index, entry in enumerate(variants_payload):
        if not isinstance(entry, dict):
            continue
        settings = entry.get("settings")
        if not isinstance(settings, dict):
            continue
        options = sanitize_preview_settings_options(
            settings,
            base_options=base_options,
            motion_tuning_enabled=motion_tuning_enabled,
        )
        signature = preview_options_signature(options, motion_tuning_enabled=motion_tuning_enabled)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        variant_id = slugify(str(entry.get("id") or entry.get("label") or f"adaptive-{index + 1}")) or f"adaptive-{index + 1}"
        variants.append(
            {
                "id": f"adaptive-{variant_id}",
                "label": str(entry.get("label") or f"Adaptive {index + 1}"),
                "options": options,
                "cleanupInterpretation": str(options.get("cleanupInterpretation") or "support_lock"),
                "adaptivePreviewSettings": {
                    "source": "vlm_baseline_planner",
                    "reason": str(entry.get("reason") or ""),
                },
            }
        )
        if len(variants) >= max_variants:
            break
    return variants


def parse_adaptive_preview_baseline_is_sufficient(raw: str) -> bool | None:
    try:
        payload = extract_json_object(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("baseline_is_sufficient")
    return value if isinstance(value, bool) else None


def sanitize_preview_settings_options(
    settings: dict[str, Any],
    *,
    base_options: dict[str, Any],
    motion_tuning_enabled: bool,
) -> dict[str, Any]:
    options = dict(base_options)
    option_specs = {
        str(option["id"]): option
        for option in preview_tuning_option_catalog(motion_tuning_enabled=motion_tuning_enabled)
    }
    for option_id, spec in option_specs.items():
        if option_id not in settings:
            continue
        value = settings[option_id]
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
    if "cleanupInterpretation" in settings:
        cleanup_interpretation = str(settings["cleanupInterpretation"]).strip()
        if cleanup_interpretation in {"support_lock", "paired_hands"}:
            options["cleanupInterpretation"] = cleanup_interpretation
    return options


def preview_options_signature(options: dict[str, Any], *, motion_tuning_enabled: bool) -> str:
    option_ids = [
        str(option["id"])
        for option in preview_tuning_option_catalog(motion_tuning_enabled=motion_tuning_enabled)
    ]
    option_ids.append("cleanupInterpretation")
    return json.dumps({option_id: options.get(option_id) for option_id in option_ids}, sort_keys=True)


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
    review_video_metadata_path = review_dir / f"{artifact_slug}.review_video.json"
    if skeleton_path.exists() and review_video_path.exists():
        export_payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
        if selected_section_review_video_cache_is_current(
            review_video_metadata_path,
            export_payload=export_payload,
        ):
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
                cleanup_interpretation=str(options.get("cleanupInterpretation") or "support_lock"),
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
        review_video_metadata_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "frameCount": len(frame_data_urls),
                    "fps": parse_export_fps(export_payload),
                    "repeats": SELECTED_SECTION_REVIEW_VIDEO_LOOP_REPEATS,
                    "sourceFrameCount": int(export_payload.get("frameCount") or 0),
                },
                indent=2,
            ),
            encoding="utf-8",
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
        cleanup_interpretation=str(options.get("cleanupInterpretation") or "support_lock"),
    )


def selected_section_review_video_cache_is_current(
    metadata_path: Path,
    *,
    export_payload: dict[str, Any],
) -> bool:
    if not metadata_path.exists():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    frame_indices = dense_loop_review_video_frame_indices(export_payload)
    return (
        int(metadata.get("schemaVersion") or 0) == 1
        and int(metadata.get("repeats") or 0) == SELECTED_SECTION_REVIEW_VIDEO_LOOP_REPEATS
        and int(metadata.get("frameCount") or 0) == len(frame_indices)
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
        "fixedRoot": True,
        "autoWorldAlignment": False,
        "lockYDrift": False,
        "lockPlantedFeet": False,
        "lockPlantedHands": False,
        "cleanupInterpretation": "support_lock",
        "sceneInverted": False,
        "showSmplMesh": False,
        "showBoundsHelper": False,
        "cameraYawDegrees": 45.0,
        "cameraPitchDegrees": 30.0,
        "playbackSpeed": 1.0,
    }


def preview_tuning_option_catalog(*, motion_tuning_enabled: bool) -> list[dict[str, Any]]:
    return [
        {
            "id": "fixedRoot",
            "label": "Lock global root drift",
            "type": "boolean",
            "default": False,
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
            "useWhen": "Use only when the pelvis slowly floats up or down because of camera/reconstruction drift and the intended exercise should stay at a stable height.",
            "risk": "Can flatten real vertical motion such as squat, lunge, split-squat, jump, or Olympic-lift depth if overused.",
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
            "default": False,
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
        {
            "id": "playbackSpeed",
            "label": "Playback speed",
            "type": "number",
            "default": 1.0,
            "range": [0.5, 1.5],
            "description": "Changes the exported animation timing without changing the pose geometry.",
            "useWhen": "Use below 1.0 when the rep looks rushed, or above 1.0 when the rep is too slow for a compact Wear animation.",
            "risk": "Too slow can feel sluggish; too fast can hide exercise range or make the loop hard to read.",
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
                    "sceneInverted": False,
                    "cleanupInterpretation": "support_lock",
                },
                "cleanupInterpretation": "support_lock",
            },
        ]
    support_presets = [
        (
            "lock-feet-hands",
            "Lock feet and hands",
            {
                "lockPlantedFeet": True,
                "lockPlantedHands": True,
                "cleanupInterpretation": "support_lock",
            },
        ),
        (
            "no-foot-lock",
            "No foot lock",
            {
                "lockPlantedFeet": False,
                "lockPlantedHands": True,
                "cleanupInterpretation": "support_lock",
            },
        ),
        (
            "no-hand-lock",
            "No hand lock",
            {
                "lockPlantedFeet": True,
                "lockPlantedHands": False,
                "cleanupInterpretation": "support_lock",
            },
        ),
        (
            "paired-hands",
            "Paired moving hands",
            {
                "lockPlantedFeet": True,
                "lockPlantedHands": False,
                "cleanupInterpretation": "paired_hands",
            },
        ),
        (
            "no-support-lock",
            "No support lock",
            {
                "lockPlantedFeet": False,
                "lockPlantedHands": False,
                "cleanupInterpretation": "support_lock",
            },
        ),
    ]
    transform_profiles = [
        (
            "",
            "",
            {
                "fixedRoot": True,
                "autoWorldAlignment": True,
                "sceneInverted": False,
            },
        ),
        (
            "inverted",
            "Inverted scene",
            {
                "fixedRoot": True,
                "autoWorldAlignment": True,
                "sceneInverted": True,
            },
        ),
        (
            "no-auto-alignment",
            "No auto alignment",
            {
                "fixedRoot": True,
                "autoWorldAlignment": False,
                "sceneInverted": False,
            },
        ),
        (
            "no-auto-alignment-inverted",
            "No auto alignment, inverted scene",
            {
                "fixedRoot": True,
                "autoWorldAlignment": False,
                "sceneInverted": True,
            },
        ),
        (
            "free-root",
            "Free global root drift",
            {
                "fixedRoot": False,
                "autoWorldAlignment": True,
                "sceneInverted": False,
            },
        ),
    ]
    variants: list[dict[str, Any]] = []
    for support_id, support_label, support_options in support_presets:
        for profile_id, profile_label, profile_options in transform_profiles:
            variant_id = support_id if not profile_id else f"{support_id}-{profile_id}"
            variant_label = support_label if not profile_label else f"{support_label}, {profile_label}"
            variants.append(
                {
                    "id": variant_id,
                    "label": variant_label,
                    "options": {
                        **support_options,
                        **profile_options,
                    },
                    "cleanupInterpretation": support_options.get("cleanupInterpretation", "support_lock"),
                }
            )
    return variants


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
    duration_scaled_frames = int(math.ceil(max(0.1, chunk_seconds) * DEFAULT_LLM_REVIEW_FRAMES_PER_SECOND))
    return max(
        DEFAULT_LLM_REVIEW_FRAMES,
        max(1, int(request.review_frames)),
        min(DEFAULT_MAX_LLM_REVIEW_FRAMES, duration_scaled_frames),
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
            export_frames = export_payload.get("frames") if isinstance(export_payload, dict) else None
            fps = parse_export_fps(export_payload if isinstance(export_payload, dict) else {})
            frame_timestamps = []
            if isinstance(export_frames, list):
                for frame_index in frame_indices:
                    frame = export_frames[frame_index] if 0 <= frame_index < len(export_frames) and isinstance(export_frames[frame_index], dict) else {}
                    frame_timestamps.append(
                        frame_time_seconds(
                            frame,
                            fallback_index=frame_index,
                            fps=fps,
                        )
                    )
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
    write_review_contact_sheet_from_data_urls(frame_data_urls, contact_sheet_path, timestamps=frame_timestamps)
    return [contact_sheet_path]


def render_source_review_window_contact_sheet(
    *,
    item: ReviewItem,
    window: DetectionWindow,
    output_dir: Path,
    frame_count: int,
) -> list[Path]:
    source_video_path = item.candidate_workspace / "input" / "selected_segment.mp4"
    if not source_video_path.exists():
        source_video_path = item.candidate_workspace / "input" / "source.mp4"
    if not source_video_path.exists():
        return []
    return render_video_window_contact_sheet(
        video_path=source_video_path,
        window=window,
        output_dir=output_dir,
        frame_count=frame_count,
    )


def render_video_window_contact_sheet(
    *,
    video_path: Path,
    window: DetectionWindow,
    output_dir: Path,
    frame_count: int,
) -> list[Path]:
    if not video_path.exists():
        return []
    try:
        return extract_window_frames(
            video_path=video_path,
            window=window,
            frames_per_window=max(1, frame_count),
            max_frame_width=DEFAULT_RANK_FRAME_WIDTH,
            contact_sheet_enabled=True,
            contact_sheet_columns=contact_sheet_columns(max(1, frame_count)),
            contact_sheet_tile_width=DEFAULT_LLM_REVIEW_CONTACT_SHEET_CELL_WIDTH,
            contact_sheet_frames_per_sheet=max(1, frame_count),
            output_dir=output_dir,
        )
    except Exception:
        return []


def write_review_contact_sheet_from_data_urls(
    data_urls: list[str],
    output_path: Path,
    *,
    timestamps: list[float] | None = None,
) -> None:
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
        if timestamps is not None and len(timestamps) > len(frames):
            label = f"t={timestamps[len(frames)]:.2f}s"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.55
            thickness = 2
            (text_width, text_height), baseline = cv2.getTextSize(label, font, font_scale, thickness)
            padding = 6
            cv2.rectangle(
                image,
                (0, 0),
                (text_width + padding * 2, text_height + baseline + padding * 2),
                (0, 0, 0),
                -1,
            )
            cv2.putText(
                image,
                label,
                (padding, padding + text_height),
                font,
                font_scale,
                (255, 255, 255),
                thickness,
                cv2.LINE_AA,
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


def build_source_cut_candidate_windows(
    *,
    window: DetectionWindow,
    chunk_estimate: Any,
    max_candidates: int = 6,
) -> list[DetectionWindow]:
    duration = max(0.0, window.end_seconds - window.start_seconds)
    if duration <= 0.5:
        return []
    rep_min = parse_optional_float(getattr(chunk_estimate, "rep_duration_min_sec", None))
    rep_max = parse_optional_float(getattr(chunk_estimate, "rep_duration_max_sec", None))
    min_duration = max(0.75, rep_min or min(duration, 2.0))
    max_duration = min(duration, max(min_duration, rep_max or duration))
    target_duration = min(max_duration, max(min_duration, (min_duration + max_duration) * 0.5))
    candidate_durations = [
        target_duration,
        max(min_duration, target_duration * 0.8),
        min(max_duration, target_duration * 1.2),
    ]
    unique_durations: list[float] = []
    for candidate_duration in candidate_durations:
        rounded = round(min(duration, max(0.75, candidate_duration)), 2)
        if all(abs(rounded - existing) > 0.1 for existing in unique_durations):
            unique_durations.append(rounded)

    windows: list[DetectionWindow] = []
    seen: set[tuple[float, float]] = set()
    for candidate_duration in unique_durations:
        available = max(0.0, duration - candidate_duration)
        starts = [
            window.start_seconds,
            window.start_seconds + available / 3.0,
            window.start_seconds + available * 2.0 / 3.0,
            window.end_seconds - candidate_duration,
        ]
        for start in starts:
            start = max(window.start_seconds, min(window.end_seconds - candidate_duration, start))
            end = min(window.end_seconds, start + candidate_duration)
            key = (round(start, 2), round(end, 2))
            if key in seen or end - start < 0.75:
                continue
            seen.add(key)
            windows.append(DetectionWindow(index=len(windows), start_seconds=key[0], end_seconds=key[1]))
            if len(windows) >= max_candidates:
                return windows
    return windows


def build_source_cut_candidate_choice_prompt(
    *,
    exercise_name: str,
    candidate_title: str,
    candidates: list[SourceCutCandidate],
) -> str:
    candidate_lines = [
        f"- Candidate {candidate.candidate_id}: {candidate.window.start_seconds:.2f}s to {candidate.window.end_seconds:.2f}s."
        for candidate in candidates
    ]
    return (
        "You are choosing a source-video cut for an exercise animation.\n"
        f"Target exercise: {exercise_name}.\n"
        f"Candidate video title: {candidate_title}.\n"
        "Each attached chronological contact sheet is one candidate source-video window. "
        "Attachments are in this exact order:\n"
        + "\n".join(candidate_lines)
        + "\n\nChoose a candidate only if it contains the complete useful exercise movement. "
        "Complete means the clip clearly shows the full intended action for the target exercise, including the meaningful start and finish positions and all required phases between them. "
        "For repeated gym movements, do not accept a one-way lowering-only, raising-only, static hold, lockout-only, setup-only, or reset-only fragment as a complete movement. "
        "Prefer the smallest candidate that contains the complete useful movement without setup, reset, idle, or the start of another movement. "
        "Reject any candidate where an extra visible person, coach, spotter, bystander, reflection, picture-in-picture person, or partial extra human appears in the contact sheet. "
        "If every candidate is partial, clipped, unclear, mostly static, or only shows one phase of the movement, return selected_candidate_id null, valid_single_movement false, and a score below 50. "
        "Do not choose the least-bad candidate just because it is in the list. "
        "Do not invent timestamps; choose one candidate id from the list or null.\n"
        "The score must be a 0-100 integer confidence score, not a 0-1, 1-5, or 1-10 rating. "
        "Use 90-100 for an excellent smallest complete movement, 75-89 for a usable complete movement with minor issues, 50-74 for borderline but complete, and below 50 for partial, unclear, wrong, or unusable windows. "
        "If valid_single_movement is true, the score should usually be 75 or higher unless the chosen window is only borderline. "
        "Return JSON only with keys: {\"selected_candidate_id\": string|null, \"score\": integer_0_to_100, \"valid_single_movement\": boolean, \"reason\": string}."
    )


def normalize_source_cut_candidate_id(value: object) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("CANDIDATE "):
        text = text[len("CANDIDATE ") :].strip()
    return re.sub(r"[^A-Z0-9_-]", "", text)


def source_cut_candidates_payload(candidates: list[SourceCutCandidate]) -> list[dict[str, Any]]:
    return [
        {
            "candidateId": candidate.candidate_id,
            "startSeconds": candidate.window.start_seconds,
            "endSeconds": candidate.window.end_seconds,
            "framePaths": [str(path) for path in candidate.frame_paths],
        }
        for candidate in candidates
    ]


def parse_source_cut_candidate_choice(raw: str, candidates: list[SourceCutCandidate]) -> LoopRanking | None:
    try:
        payload = extract_json_object(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    selected_id = normalize_source_cut_candidate_id(payload.get("selected_candidate_id"))
    candidates_by_id = {
        normalize_source_cut_candidate_id(candidate.candidate_id): candidate
        for candidate in candidates
    }
    selected = candidates_by_id.get(selected_id)
    if selected is None or not bool(payload.get("valid_single_movement", False)):
        return None
    score = parse_optional_float(payload.get("score"))
    if score is None:
        score = 0.0
    if score > 1.0:
        score = score / 100.0
    score = clamp_unit(score)
    reason = str(payload.get("reason") or "source_candidate_window_choice")
    ranking_payload = dict(payload)
    ranking_payload["selectedCandidateId"] = selected.candidate_id
    ranking_payload["selected_section_start_seconds"] = selected.window.start_seconds
    ranking_payload["selected_section_end_seconds"] = selected.window.end_seconds
    ranking_payload["sourceCutCandidates"] = source_cut_candidates_payload(candidates)
    return LoopRanking(
        score=score,
        reasons=[reason, "source_candidate_window_choice"],
        raw_response=raw,
        payload=ranking_payload,
        model_score=score,
    )


def rank_source_cut_candidates_with_caption_images(
    *,
    item: ReviewItem,
    timeline_window: DetectionWindow,
    chunk_estimate: Any,
    output_dir: Path,
    frame_count: int,
    caption_images: Callable[..., str],
) -> tuple[LoopRanking, float, float] | None:
    candidate_windows = build_source_cut_candidate_windows(
        window=timeline_window,
        chunk_estimate=chunk_estimate,
    )
    if not candidate_windows:
        return None
    render_started = time.perf_counter()
    candidates: list[SourceCutCandidate] = []
    for index, candidate_window in enumerate(candidate_windows):
        candidate_id = chr(ord("A") + index)
        frame_paths = render_source_review_window_contact_sheet(
            item=item,
            window=candidate_window,
            output_dir=output_dir / f"source_candidate_{candidate_id}",
            frame_count=min(max(8, frame_count // 2), 16),
        )
        if frame_paths:
            candidates.append(SourceCutCandidate(candidate_id=candidate_id, window=candidate_window, frame_paths=frame_paths))
    render_seconds = elapsed_seconds(render_started)
    if not candidates:
        return None
    vlm_started = time.perf_counter()
    raw = caption_images(
        frame_paths=[path for candidate in candidates for path in candidate.frame_paths],
        prompt=build_source_cut_candidate_choice_prompt(
            exercise_name=item.exercise_name,
            candidate_title=item.candidate_title,
            candidates=candidates,
        ),
    )
    vlm_seconds = elapsed_seconds(vlm_started)
    ranking = parse_source_cut_candidate_choice(raw, candidates)
    if ranking is None:
        return (
            LoopRanking(
                score=0.0,
                reasons=["source_candidate_window_choice_failed", "source_candidate_choice_invalid_response"],
                raw_response=raw,
                payload={
                    "score": 0.0,
                    "modelScore": 0.0,
                    "sourceCutCandidates": source_cut_candidates_payload(candidates),
                    "sourceChoiceInvalidResponse": True,
                },
                model_score=0.0,
            ),
            render_seconds,
            vlm_seconds,
        )
    return ranking, render_seconds, vlm_seconds


def rank_source_video_cut_candidates_with_caption_images(
    *,
    video_path: Path,
    exercise_name: str,
    candidate_title: str,
    timeline_window: DetectionWindow,
    chunk_estimate: Any,
    output_dir: Path,
    frame_count: int,
    caption_images: Callable[..., str],
) -> tuple[LoopRanking, float, float] | None:
    candidate_windows = build_source_cut_candidate_windows(
        window=timeline_window,
        chunk_estimate=chunk_estimate,
    )
    if not candidate_windows:
        return None
    render_started = time.perf_counter()
    candidates: list[SourceCutCandidate] = []
    for index, candidate_window in enumerate(candidate_windows):
        candidate_id = chr(ord("A") + index)
        frame_paths = render_video_window_contact_sheet(
            video_path=video_path,
            window=candidate_window,
            output_dir=output_dir / f"source_candidate_{candidate_id}",
            frame_count=min(max(8, frame_count // 2), 16),
        )
        if frame_paths:
            candidates.append(SourceCutCandidate(candidate_id=candidate_id, window=candidate_window, frame_paths=frame_paths))
    render_seconds = elapsed_seconds(render_started)
    if not candidates:
        return None
    vlm_started = time.perf_counter()
    raw = caption_images(
        frame_paths=[path for candidate in candidates for path in candidate.frame_paths],
        prompt=build_source_cut_candidate_choice_prompt(
            exercise_name=exercise_name,
            candidate_title=candidate_title,
            candidates=candidates,
        ),
    )
    vlm_seconds = elapsed_seconds(vlm_started)
    ranking = parse_source_cut_candidate_choice(raw, candidates)
    if ranking is None:
        return (
            LoopRanking(
                score=0.0,
                reasons=["source_candidate_window_choice_failed", "source_candidate_choice_invalid_response"],
                raw_response=raw,
                payload={
                    "score": 0.0,
                    "modelScore": 0.0,
                    "sourceCutCandidates": source_cut_candidates_payload(candidates),
                    "sourceChoiceInvalidResponse": True,
                },
                model_score=0.0,
            ),
            render_seconds,
            vlm_seconds,
        )
    return ranking, render_seconds, vlm_seconds


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
        use_llm=False,
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
        llama_cpp_top_p=request.llama_cpp_top_p,
        llama_cpp_top_k=request.llama_cpp_top_k,
        llama_cpp_disable_reasoning=request.llama_cpp_disable_reasoning,
        llama_cpp_ctx_size=request.llama_cpp_ctx_size,
        llama_cpp_batch_size=request.llama_cpp_batch_size,
        llama_cpp_ubatch_size=request.llama_cpp_ubatch_size,
        llama_cpp_flash_attn=request.llama_cpp_flash_attn,
        llama_cpp_cache_type_k=request.llama_cpp_cache_type_k,
        llama_cpp_cache_type_v=request.llama_cpp_cache_type_v,
        llama_cpp_parallel=request.llama_cpp_parallel,
        llama_cpp_threads_http=request.llama_cpp_threads_http,
        llama_cpp_cache_reuse=request.llama_cpp_cache_reuse,
        llama_cpp_fit=request.llama_cpp_fit,
        llama_cpp_fit_ctx=request.llama_cpp_fit_ctx,
        llama_cpp_fit_target=request.llama_cpp_fit_target,
        llama_cpp_mmap=request.llama_cpp_mmap,
        llama_cpp_mlock=request.llama_cpp_mlock,
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
        use_llm=False,
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
            source_choice = rank_source_cut_candidates_with_caption_images(
                item=item,
                timeline_window=timeline_window,
                chunk_estimate=chunk_estimate,
                output_dir=frames_dir / f"chunk_{video_window.index:04d}",
                frame_count=frames_per_chunk,
                caption_images=caption_images,
            )
        except Exception as exc:
            rankings.append(
                build_deterministic_section_fallback_ranking(
                    window=timeline_window,
                    video_window=video_window,
                    chunk_index=shortlist_index,
                    chunk_count=len(window_candidates),
                    original_chunk_count=len(windows),
                    deterministic_window=window_candidate,
                    active_motion_window=None,
                    chunk_estimate=chunk_estimate,
                    review_frame_source="source_candidate_window_contact_sheets",
                    review_frame_count=frames_per_chunk,
                    error=exc,
                )
            )
            continue
        if source_choice is None:
            rankings.append(
                LoopRanking(
                    score=0.0,
                    reasons=["source_candidate_window_choice_failed", "source_candidate_windows_unavailable"],
                )
            )
            continue
        ranking, render_seconds, vlm_seconds = source_choice
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
                    active_motion_window=None,
                    chunk_estimate=chunk_estimate,
                    review_frame_source="source_candidate_window_contact_sheets",
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
    active_motion_window: ActiveMotionWindowProposal | None,
    chunk_estimate: Any,
    review_frame_source: str,
    review_frame_count: int,
    error: Exception,
) -> LoopRanking:
    motion_score = clamp_unit(parse_optional_float(deterministic_window.motion_metrics.get("motionStrengthScore")) or 0.0)
    continuity_score = clamp_unit(parse_optional_float(deterministic_window.continuity_metrics.get("continuityScore")) or 0.0)
    loop_continuity_required = exercise_requires_loop_continuity(
        "",
        chunk_estimate=chunk_estimate,
    )
    effective_continuity_score = continuity_score if loop_continuity_required else 1.0
    model_score = clamp_unit(
        0.45 * clamp_unit(float(deterministic_window.score))
        + 0.35 * motion_score
        + 0.20 * effective_continuity_score
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
        "loopContinuityRequired": loop_continuity_required,
        "effectiveLoopabilityScore": effective_continuity_score,
        "wear_readability": None,
        "recommended_settings": {},
        "selected_section_start_seconds": window.start_seconds,
        "selected_section_end_seconds": window.end_seconds,
        "activeMotionWindowProposal": active_motion_window_to_payload(active_motion_window),
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
    active_motion_window: ActiveMotionWindowProposal | None,
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
            "activeMotionWindowProposal": active_motion_window_to_payload(active_motion_window),
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


def active_motion_window_to_payload(proposal: ActiveMotionWindowProposal | None) -> dict[str, Any] | None:
    if proposal is None:
        return None
    return {
        "startSeconds": proposal.window.start_seconds,
        "endSeconds": proposal.window.end_seconds,
        "durationSeconds": max(0.0, proposal.window.end_seconds - proposal.window.start_seconds),
        "metrics": proposal.metrics,
    }


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
    includes_source_context: bool = False,
    allow_settings_recommendations: bool = True,
) -> str:
    current_settings_json = json.dumps(item.settings_options, sort_keys=True)
    motion_tuning_enabled = item.settings_variant_id != "raw-wham"
    loop_continuity_required = False
    review_goal = "choose the cleanest complete exercise movement section inside this chunk for a Wear OS exercise animation"
    boundary_instruction = (
        "The selected section should be cut to the actual exercise movement, not merely to the whole reviewed chunk. For a rep-based lift, start near the first frame where the loaded movement begins, include the full eccentric and concentric phases, and end shortly after the rep completes at the stable finish pose. For multi-phase lifts, include the complete phase sequence through controlled finish/stabilization. Exclude setup, unracking, walking in/out, long pauses before the first moving frame, long holds after completion, and reset footage. Only select the entire chunk when its first and last frames are already the true movement boundaries.\n"
    )
    movement_boundary_instruction = (
        "First identify the movement start and movement end from the chronological frames. Prefer a tight cut around the complete exercise movement over a full-chunk cut that includes setup, reset, or extra holds. Do not require the start and end poses to match; clean movement coverage is more important than loopability.\n"
    )
    section_cut_instruction = "Judge only the attached chunk frames and pick exact start/end seconds for the complete movement section that should be cut as a one-shot exercise animation clip.\n"
    score_instruction = (
        "Score 0 to 1 for the proposed cut using these criteria: correct exercise, complete movement coverage, recognizability, smoothness, stable planted feet when appropriate, stable paired hand spacing for barbell/dumbbell press-like motion, no impossible joints, clear start/end boundaries, controlled finish, and readability on a small Wear display. Do not penalize a valid movement merely because the final pose differs from the starting pose.\n"
    )
    settings_instruction = (
        "If the render is upside down, head/feet reversed, or unreadable because of camera/alignment, do not give it a high score. Use recommended_settings for available orientation fixes such as sceneInverted, autoWorldAlignment, cameraYawDegrees, or cameraPitchDegrees when that would likely make the same motion readable.\n"
        "If a different available option set would likely improve the selected section, put those values in recommended_settings and explain why.\n"
        if allow_settings_recommendations
        else "Render settings have already been chosen by the adaptive settings planner. In this step, do not change preview settings; return recommended_settings as an empty object. If the render is upside down, head/feet reversed, or unreadable because of camera/alignment, lower the score instead of trying to fix settings here.\n"
    )
    tuning_catalog_instruction = (
        "Available preview tuning options and what they do:\n"
        f"{format_preview_tuning_options_for_prompt(motion_tuning_enabled=motion_tuning_enabled)}\n"
        if allow_settings_recommendations
        else ""
    )
    return (
        f"Review this bounded chunk from a full baked exercise motion preview and {review_goal}.\n"
        f"Target exercise: {item.exercise_name}.\n"
        f"Candidate video title: {item.candidate_title}.\n"
        f"Full selected input preview span: {item.loop_start_seconds:.3f}s to {item.loop_end_seconds:.3f}s "
        f"({item.duration_sec:.3f}s).\n"
        f"Review shortlisted chunk {chunk_index + 1} of {chunk_count}: {chunk_window.start_seconds:.3f}s to {chunk_window.end_seconds:.3f}s.\n"
        f"This was original temporal chunk {original_chunk_index + 1} of {original_chunk_count}, shortlisted by skeleton motion score {deterministic_window_score:.3f}.\n"
        + (
            (
                f"The first attached image is a chronological contact sheet from the original selected source video for exercise identity and real-world context. The second attached image is the generated skeleton preview contact sheet with {review_frame_count} evenly sampled frames and visible preview timeline labels; read each sheet left-to-right, top-to-bottom. Use the source sheet only for context; choose section timing from the generated preview timeline.\n"
            )
            if includes_source_context
            else f"The attached image is a chronological contact sheet rendered directly from the generated interactive preview with {review_frame_count} evenly sampled frames and visible preview timeline labels; read it left-to-right, top-to-bottom.\n"
        )
        + "Use the chunk boundaries as the search space. Return selected section seconds in the full preview timeline, and keep them inside this chunk.\n"
        f"Chunk sizing came from the shared estimate: {json.dumps({'repDurationMinSec': getattr(chunk_estimate, 'rep_duration_min_sec', None), 'repDurationMaxSec': getattr(chunk_estimate, 'rep_duration_max_sec', None), 'movementComplexity': getattr(chunk_estimate, 'movement_complexity', None), 'chunkSeconds': getattr(chunk_estimate, 'chunk_seconds', None), 'chunkOverlapSeconds': getattr(chunk_estimate, 'chunk_overlap_seconds', None), 'source': getattr(chunk_estimate, 'source', None)})}.\n"
        "Loop continuity required for final acceptance: false. Prefer a clean complete movement clip over a seamless loop.\n"
        f"Current preview option variant: {item.settings_variant_id} ({item.settings_variant_label}).\n"
        f"Current cleanup interpretation: {item.cleanup_interpretation}.\n"
        f"Current preview option values: {current_settings_json}.\n"
        f"{tuning_catalog_instruction}"
        "Important: the attached preview is a generated skeleton/body render only. External objects and scene context such as benches, barbells, dumbbells, cables, machines, boxes, racks, floors, and props are intentionally absent unless they are part of the generated body. "
        "Do not reject or relabel the movement because equipment or a bench is not visible in the skeleton render. For equipment exercises, judge whether the body and limb trajectories are plausible for the requested target exercise with the equipment implied but invisible. "
        "For horizontal pressing movements, do not call the clip a push-up or plank solely because the body is horizontal or the barbell/bench is not drawn; use the target exercise, candidate title, and body motion pattern.\n"
        f"Do not assume any hidden options exist. {section_cut_instruction}"
        f"{movement_boundary_instruction}"
        f"{boundary_instruction}"
        "Avoid setup, reset, walking in/out, bad boundary poses, and sections where the body is unclear. If no strong full rep is present in this chunk, lower the score and set full_rep_motion below 0.7.\n"
        f"{settings_instruction}"
        f"{score_instruction}"
        "Strongly penalize wrong or unclear movement, shallow or partial reps when a stronger full rep is visible, jitter, foot sliding, broken limbs, visible popping, arm distortion, lost elbow range, broken paired-hand spacing, bad section boundaries, and poses that would be confusing on a watch.\n"
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
            "llama_cpp_adaptive_preview_settings_then_section_selection"
            if request.adaptive_preview_settings
            else "llama_cpp_skeleton_prefiltered_preview_section_selection"
            if request.rank_preview_variants
            else "skipped_full_input_selected_without_llm_section_cut"
        ),
        "previewSettingsVariantRankingEnabled": request.rank_preview_variants,
        "adaptivePreviewSettingsEnabled": request.adaptive_preview_settings,
        "maxAdaptivePreviewSettings": request.max_adaptive_preview_settings,
        "previewTuningOptionCatalog": preview_tuning_option_catalog(
            motion_tuning_enabled=request.motion_tuning_enabled
        ),
        "maxLoopSeconds": request.max_loop_seconds,
        "maxReviewWindows": request.max_review_windows,
        "minSelectedScore": request.min_selected_score,
        "motionTuningEnabled": request.motion_tuning_enabled,
        "spineposeEnabled": request.spinepose_enabled,
        "spineposeMergeMode": request.spinepose_merge_mode,
        "spineposeMode": request.spinepose_mode,
        "spineposeModelVersion": request.spinepose_model_version,
        "spineposeDevice": request.spinepose_device,
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
        payload["selectionScore"] = selected_artifact_score((item, ranking))
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
        "spineposeSource": (
            result.timings.get("spineposeSource")
            if isinstance(result.timings, dict) and isinstance(result.timings.get("spineposeSource"), dict)
            else None
        ),
        "timings": result.timings,
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
        "cleanupInterpretation": item.cleanup_interpretation,
        "adaptivePreviewSettings": item.adaptive_preview_settings,
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
        cleanup_interpretation=str(payload.get("cleanupInterpretation") or "support_lock"),
        adaptive_preview_settings=payload.get("adaptivePreviewSettings") if isinstance(payload.get("adaptivePreviewSettings"), dict) else None,
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
        "cleanupInterpretation": payload.get("cleanupInterpretation"),
        "handLockArmDistortionMetrics": payload.get("handLockArmDistortionMetrics"),
        "pairedHandsPreservationMetrics": payload.get("pairedHandsPreservationMetrics"),
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


def copy_or_download_candidate_source(
    ranked_candidate: RankedCandidate,
    destination_dir: Path,
    *,
    youtube_cookies: Path | None = None,
) -> Path:
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
    return download_youtube(ranked_candidate.url, destination_dir, youtube_cookies)
