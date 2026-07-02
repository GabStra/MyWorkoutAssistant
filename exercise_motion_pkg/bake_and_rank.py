from __future__ import annotations

import base64
import copy
import hashlib
import html
import inspect
import json
import math
import os
import re
import shutil
import statistics
import threading
import traceback
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

from exercise_motion_pkg.contact_sheet_guidance import CONTACT_SHEET_READING_INSTRUCTIONS
from exercise_motion_pkg.motion_io import load_motion_json
from exercise_motion_pkg.llama_defaults import (
    DEFAULT_LLAMA_CPP_BATCH_SIZE,
    DEFAULT_LLAMA_CPP_CACHE_TYPE_K,
    DEFAULT_LLAMA_CPP_CACHE_TYPE_V,
    DEFAULT_LLAMA_CPP_CTX_SIZE,
    DEFAULT_LLAMA_CPP_FIT,
    DEFAULT_LLAMA_CPP_FIT_CTX,
    DEFAULT_LLAMA_CPP_FIT_TARGET,
    DEFAULT_LLAMA_CPP_FLASH_ATTN,
    DEFAULT_LLAMA_CPP_IMAGE_MAX_TOKENS,
    DEFAULT_LLAMA_CPP_MLOCK,
    DEFAULT_LLAMA_CPP_MMAP,
    DEFAULT_LLAMA_CPP_MMPROJ,
    DEFAULT_LLAMA_CPP_MODEL,
    DEFAULT_LLAMA_CPP_MTMD_BATCH_MAX_TOKENS,
    DEFAULT_LLAMA_CPP_PARALLEL,
    DEFAULT_LLAMA_CPP_REASONING_BUDGET,
    DEFAULT_LLAMA_CPP_REASONING_BUDGET_MESSAGE,
    DEFAULT_LLAMA_CPP_TEMPERATURE,
    DEFAULT_LLAMA_CPP_TOP_K,
    DEFAULT_LLAMA_CPP_TOP_P,
    DEFAULT_LLAMA_CPP_UBATCH_SIZE,
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
    draw_contact_sheet_tile_label,
    extract_json_object,
    extract_window_frames,
    iter_detection_windows,
    save_detection_result,
)
from exercise_motion_pkg.target_motion import (
    DISTAL_LEG_VERTICAL_RAISE_PROFILE_KEY,
    TARGET_MOTION_MATERIALIZED_REJECTION_REASON,
    observable_motion_spec_for_contract,
    observable_motion_spec_mentions_lower_body,
    observable_motion_spec_requires_return,
    target_motion_profile_for_exercise,
)
from exercise_motion_pkg.video_utils import read_basic_video_metadata, trim_video
from exercise_motion_pkg.youtube import (
    ExerciseEntry,
    MIN_MOVING_SUBJECT_REALISM_SCORE,
    POSE_PREFILTER_HARD_REJECT_ISSUES,
    LlamaCppVisionRanker,
    YouTubeRankingSettings,
    build_exercise_motion_contract_prompt,
    build_exercise_skeleton_contract_prompt,
    cleaned_contract_advisory_text,
    cleaned_contract_string,
    download_youtube,
    exercise_motion_contract_for_prompt,
    exercise_motion_contract_prompt_body,
    find_cached_youtube_preview,
    normalize_exercise_motion_contract_text,
    normalize_exercise_motion_contract,
    normalize_exercise_skeleton_contract_text,
    pose_prefilter_blocking_issues,
    slugify,
    truncate_text,
    youtube_preview_cache_stem,
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
ADAPTIVE_PREVIEW_SETTINGS_MIN_CONTACT_SHEET_FRAMES = 12
ADAPTIVE_PREVIEW_SETTINGS_MAX_CONTACT_SHEET_FRAMES = 20
MAX_DENSE_REVIEW_VIDEO_FRAMES = 360
SELECTED_SECTION_REVIEW_VIDEO_LOOP_REPEATS = 1
SELECTED_SECTION_BAKE_CACHE_VERSION = 7
FIXED_PREVIEW_CAMERA_YAW_DEGREES = 45.0
FIXED_PREVIEW_CAMERA_PITCH_DEGREES = 30.0
DEFAULT_RANK_FRAME_WIDTH = 640
DEFAULT_MIN_SELECTED_SCORE = 0.55
DEFAULT_FALLBACK_CANDIDATES = 12
DEFAULT_MAX_SOURCE_WINDOW_ATTEMPTS = 3
ARTIFACT_RETENTION_DEBUG = "debug"
ARTIFACT_RETENTION_FULL = "full"
ARTIFACT_RETENTION_MODES = frozenset((ARTIFACT_RETENTION_DEBUG, ARTIFACT_RETENTION_FULL))
ARTIFACT_RETENTION_PRUNE_DIR_NAMES = frozenset(("raw", "cleaned", "retarget", "source"))
ARTIFACT_RETENTION_PRUNE_FILE_PATTERNS = (
    "frame_*.jpg",
    "frame_*.jpeg",
    "frame_*.png",
    "*.pkl",
    "*.pth",
    "*.npy",
    "*.npz",
)
ARTIFACT_RETENTION_SAMPLE_LIMIT = 40
ARTIFACT_RETENTION_PROTECTED_PATH_KEYS = frozenset(
    (
        "inputVideoPath",
        "manifestPath",
        "previewHtmlPath",
        "rawPreviewHtmlPath",
        "reviewVideoPath",
        "selectedInputVideoPath",
        "selectedPreviewHtmlPath",
        "selectedReviewVideoPath",
        "selectedWearSkeletonPath",
        "selectedWearSkeletonPathNoFeetLock",
        "selectedWearSkeletonPathNoHandLock",
        "skeletonPath",
        "skeletonPathNoFeetLock",
        "skeletonPathNoHandLock",
        "sourceReviewVideoPath",
        "sourceSkeletonPath",
        "sourceContactSheetPath",
        "sourceContactSheetPaths",
        "previewContactSheetPath",
        "previewContactSheetPaths",
        "wearSkeletonJsonPath",
    )
)
DEFAULT_MAX_REVIEW_WINDOWS = 0
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
LOWER_BODY_CONTRACT_TERMS = (
    "hip",
    "hips",
    "knee",
    "knees",
    "ankle",
    "ankles",
    "leg",
    "legs",
    "thigh",
    "thighs",
    "foot",
    "feet",
    "heel",
    "heels",
    "toe",
    "toes",
    "glute",
    "glutes",
    "quad",
    "quads",
    "hamstring",
    "hamstrings",
    "calf",
    "calves",
    "lower body",
)
LOWER_BODY_MOTION_CONTRACT_PRIMARY_KEYS = ("primaryMotionRegions",)
LOWER_BODY_MOTION_CONTRACT_CONTEXT_KEYS = ("requiredPhases", "reviewNotes")
LOWER_BODY_MOTION_ACTION_TERMS = (
    "move",
    "moves",
    "moving",
    "motion",
    "travel",
    "travels",
    "traveling",
    "bend",
    "bends",
    "bending",
    "flex",
    "flexes",
    "flexion",
    "extend",
    "extends",
    "extension",
    "lower",
    "lowers",
    "lowering",
    "lift",
    "lifts",
    "lifting",
    "raise",
    "raises",
    "raising",
    "squat",
    "squats",
    "squatting",
    "lunge",
    "lunges",
    "lunging",
    "step",
    "steps",
    "stepping",
    "curl",
    "curls",
    "curling",
    "return",
    "returns",
    "returning",
)
LOWER_BODY_MOTION_ACTION_MAX_TOKEN_DISTANCE = 3
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
SOURCE_CUT_REFINEMENT_MIN_SECONDS = 0.75
SOURCE_CUT_REFINEMENT_MIN_ABSOLUTE_IMPROVEMENT_SECONDS = 0.10
SOURCE_CUT_REFINEMENT_MIN_RELATIVE_IMPROVEMENT = 0.05
SOURCE_CUT_PROGRESSIVE_SHRINK_FACTOR = 0.85
SOURCE_CUT_PROGRESSIVE_STRIDE_RATIO = 0.20
SOURCE_CUT_PROGRESSIVE_MAX_WINDOWS_PER_LEVEL = 9
SOURCE_CUT_PROGRESSIVE_MIN_CLUSTER_SIZE = 2
SOURCE_CUT_PROGRESSIVE_MIN_CLUSTER_OVERLAP_RATIO = 0.25
SOURCE_CUT_MIN_ESTIMATED_DURATION_RATIO = 1.0
SOURCE_CUT_ROBUST_MIN_SECONDS = 3.0
SOURCE_CUT_ROBUST_MIN_ESTIMATED_DURATION_RATIO = 1.5
SOURCE_CUT_POSE_PHASE_COMPLETENESS_MIN_FRAMES = 5
SOURCE_WINDOW_FULL_CYCLE_MIN_ESTIMATED_DURATION_RATIO = 2.0
SOURCE_WINDOW_FULL_CYCLE_MIN_SECONDS = 2.5
MOVEMENT_CUT_MIN_ESTIMATED_DURATION_RATIO = 0.60
MOVEMENT_CUT_MIN_SELECTED_ESTIMATED_DURATION_RATIO = 1.0
MOVEMENT_CUT_CANDIDATE_MAX_VLM_BATCH_SIZE = 1
SOURCE_CUT_CANDIDATE_MAX_VLM_BATCH_SIZE = 1
CUT_CANDIDATE_MAX_VLM_BATCH_SIZE = MOVEMENT_CUT_CANDIDATE_MAX_VLM_BATCH_SIZE
CUT_CANDIDATE_VLM_MAX_TOKENS = 384
CUT_CANDIDATE_VLM_TEMPERATURE = 0.0
CUT_CANDIDATE_VLM_TOP_P = 1.0
CUT_CANDIDATE_VLM_DISABLE_REASONING = True
CUT_CANDIDATE_VLM_REQUEST_TIMEOUT_SECONDS = 0.0
SOURCE_CUT_CANDIDATE_VLM_MAX_TOKENS = 256
SOURCE_CUT_CANDIDATE_VLM_REQUEST_TIMEOUT_SECONDS = CUT_CANDIDATE_VLM_REQUEST_TIMEOUT_SECONDS
SOURCE_CUT_MAX_VLM_WORKERS = 4
SEGMENT_DETECTION_VLM_MAX_TOKENS = 384
SEGMENT_DETECTION_VLM_TEMPERATURE = 0.0
SEGMENT_DETECTION_VLM_TOP_P = 1.0
SEGMENT_DETECTION_VLM_DISABLE_REASONING = True
CUT_CANDIDATE_DURATION_BUCKET_SECONDS = 0.05
DEFAULT_FINAL_OUTPUT_VALIDATION_MIN_SCORE = 0.90
FINAL_OUTPUT_VALIDATION_MIN_EXERCISE_MATCH_SCORE = 0.70
FINAL_OUTPUT_VALIDATION_MIN_FULL_MOVEMENT_SCORE = 0.65
FINAL_OUTPUT_VALIDATION_MIN_WEAR_READABILITY_SCORE = 0.55
FINAL_OUTPUT_VALIDATION_MIN_MOTION_QUALITY_SCORE = 0.55
FINAL_OUTPUT_VALIDATION_MIN_DETERMINISTIC_READABILITY_SCORE = 0.50
FINAL_OUTPUT_VALIDATION_REJECTION_SCORE_CAP = 0.49
FINAL_OUTPUT_VALIDATION_FRAME_COUNT = 8
FINAL_OUTPUT_HARD_DETERMINISTIC_REJECTION_REASONS = frozenset(
    (
        "materialized_incomplete_repetition_phase",
        "materialized_source_incomplete_repetition_phase",
    )
)
PARENT_SOURCE_WINDOW_FALLBACK_ATTEMPT_MODE = "parent_source_window_fallback"
PARENT_SOURCE_WINDOW_FALLBACK_REJECTION_REASONS = frozenset(
    (
        "wrong_exercise",
        "partial_movement",
        "final_output_low_exercise_match",
        "final_output_incomplete_movement",
        "final_output_needs_retry",
        "movement_cut_candidate_window_choice_failed",
        "materialized_incomplete_repetition_phase",
        "materialized_source_incomplete_repetition_phase",
    )
)
MOVEMENT_CUT_MIN_SOURCE_MOTION_COVERAGE_RATIO = 0.75
MOVEMENT_CUT_MIN_TARGET_REGION_MOTION_RANGE_RATIO = 0.08
MOVEMENT_CUT_DISTAL_DOMINANCE_MIN_RATIO = 1.35
MOVEMENT_CUT_DISTAL_DOMINANCE_MAX_TARGET_TO_DISTAL_RATIO = 0.55
MOVEMENT_CUT_HARD_MOTION_REJECTION_REASONS = {
    "movement_cut_low_target_region_motion",
    "movement_cut_distal_setup_motion_dominates",
}
FULL_REPETITION_PHASE_COMPLETENESS_MIN_RANGE_RATIO = 0.12
FULL_REPETITION_PHASE_COMPLETENESS_MAX_ENDPOINT_DELTA_RATIO = 0.55
FULL_REPETITION_PHASE_COMPLETENESS_EDGE_MARGIN_RATIO = 0.12
FULL_REPETITION_PHASE_COMPLETENESS_MIN_FRAMES = 6


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
        base_slug = f"{self.exercise_slug}-{self.candidate_rank + 1:03d}-{identity}"
        source_window_attempt = parse_optional_int(self.candidate.get("sourceWindowAttemptIndex"))
        if source_window_attempt is not None:
            hint = self.source_chunk_hint
            if hint is not None:
                base_slug = (
                    f"{base_slug}-window-{source_window_attempt + 1:02d}-"
                    f"{int(round(hint.start_seconds * 1000.0))}-"
                    f"{int(round(hint.end_seconds * 1000.0))}"
                )
            else:
                base_slug = f"{base_slug}-window-{source_window_attempt + 1:02d}"
        return slugify(base_slug)[:120]

    @property
    def source_chunk_hint(self) -> SourceChunkHint | None:
        explicit_hint = self.candidate.get("sourceWindowHint")
        if isinstance(explicit_hint, dict):
            start_seconds = parse_optional_float(explicit_hint.get("startSeconds"))
            end_seconds = parse_optional_float(explicit_hint.get("endSeconds"))
            if start_seconds is not None and end_seconds is not None and end_seconds > start_seconds:
                return SourceChunkHint(
                    start_seconds=max(0.0, start_seconds),
                    end_seconds=end_seconds,
                    score=parse_optional_float(explicit_hint.get("score")),
                )
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


TERMINAL_FINAL_SELECTION_STATUSES = {
    "not_reviewable",
    "rejected_after_materialized_review",
}

TERMINAL_CANDIDATE_STATUSES = {
    "skipped_source_gate",
    "skipped_pre_wham_source_validation",
}


def ranked_candidate_attempt_key(ranked_candidate: RankedCandidate) -> str:
    explicit_key = ranked_candidate.candidate.get("sourceWindowAttemptKey")
    if isinstance(explicit_key, str) and explicit_key.strip():
        return explicit_key.strip()
    identity = (
        ranked_candidate.video_id
        or ranked_candidate.url
        or str(ranked_candidate.video_path or "")
        or ranked_candidate.title
        or str(ranked_candidate.candidate_rank)
    )
    hint = ranked_candidate.source_chunk_hint
    if hint is None:
        chunk_key = "full"
    else:
        chunk_key = f"{hint.start_seconds:.3f}-{hint.end_seconds:.3f}"
    attempt_mode = str(ranked_candidate.candidate.get("sourceWindowAttemptMode") or "").strip()
    return "|".join(
        [part for part in [
            slugify(ranked_candidate.exercise_id or ranked_candidate.exercise_name),
            str(identity).strip().lower(),
            chunk_key,
            slugify(attempt_mode) if attempt_mode else "",
        ] if part]
    )


def candidate_result_attempt_key(result: dict[str, Any]) -> str | None:
    explicit_key = result.get("sourceWindowAttemptKey")
    if isinstance(explicit_key, str) and explicit_key.strip():
        return explicit_key.strip()
    candidate = result.get("candidate")
    if not isinstance(candidate, dict):
        return None
    ranked_candidate = RankedCandidate(
        exercise_index=parse_optional_int(result.get("exerciseIndex")) or 0,
        candidate_rank=parse_optional_int(result.get("candidateRank")) or 0,
        exercise_id=str(result.get("exerciseId") or result.get("exerciseName") or "exercise"),
        exercise_name=str(result.get("exerciseName") or result.get("exerciseId") or "exercise"),
        exercise_slug=slugify(str(result.get("exerciseId") or result.get("exerciseName") or "exercise")),
        candidate=candidate,
    )
    return ranked_candidate_attempt_key(ranked_candidate)


def candidate_result_has_terminal_quality_decision(result: dict[str, Any]) -> bool:
    status = str(result.get("status") or "").strip()
    if status == "failed":
        for failure in result.get("failures") or []:
            if not isinstance(failure, dict):
                continue
            reason = str(failure.get("reason") or "").strip()
            message = str(failure.get("message") or "").strip()
            if reason == "pre_wham_source_validation_rejected":
                return True
            if message.startswith("Source segment detection did not find a usable "):
                return True
        return False
    final_status = str(result.get("finalSelectionStatus") or "").strip()
    if final_status in TERMINAL_FINAL_SELECTION_STATUSES:
        return True
    if status in TERMINAL_CANDIDATE_STATUSES:
        return True
    return False


def load_previous_terminal_candidate_results(workspace: Path) -> dict[str, dict[str, Any]]:
    previous: dict[str, dict[str, Any]] = {}

    def add_result(result: dict[str, Any]) -> None:
        previous_terminal_result = result.get("previousTerminalResult")
        if str(result.get("status") or "").strip() == "skipped_previous_terminal_result":
            if isinstance(previous_terminal_result, dict):
                result = previous_terminal_result
            else:
                previous_status = str(result.get("previousStatus") or "").strip()
                previous_final_status = str(result.get("previousFinalSelectionStatus") or "").strip()
                if (
                    previous_status not in TERMINAL_CANDIDATE_STATUSES
                    and previous_final_status not in TERMINAL_FINAL_SELECTION_STATUSES
                ):
                    return
                key = candidate_result_attempt_key(result)
                if key:
                    previous.setdefault(key, result)
                return
        if not candidate_result_has_terminal_quality_decision(result):
            return
        key = candidate_result_attempt_key(result)
        if key:
            previous.setdefault(key, result)

    selection_path = workspace / "selection_manifest.json"
    if selection_path.exists():
        try:
            manifest = json.loads(selection_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        results = manifest.get("candidateResults") if isinstance(manifest, dict) else None
        if isinstance(results, list):
            for result in results:
                if isinstance(result, dict):
                    add_result(result)

    try:
        bake_manifest_paths = list(workspace.rglob("bake_manifest.json"))
    except OSError:
        bake_manifest_paths = []
    for manifest_path in bake_manifest_paths:
        try:
            result = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(result, dict):
            add_result(result)
    return previous


def build_skipped_previous_terminal_result(
    ranked_candidate: RankedCandidate,
    previous_result: dict[str, Any],
) -> dict[str, Any]:
    candidate_workspace = Path(str(previous_result.get("candidateWorkspace") or "")) if previous_result.get("candidateWorkspace") else None
    if candidate_workspace is None:
        candidate_workspace = Path()
    result = {
        "exerciseIndex": ranked_candidate.exercise_index,
        "candidateRank": ranked_candidate.candidate_rank,
        "exerciseId": ranked_candidate.exercise_id,
        "exerciseName": ranked_candidate.exercise_name,
        "candidate": ranked_candidate.candidate,
        "candidateWorkspace": str(candidate_workspace),
        "status": "skipped_previous_terminal_result",
        "finalSelectionStatus": "skipped_previous_terminal_result",
        "previousStatus": previous_result.get("status"),
        "previousFinalSelectionStatus": previous_result.get("finalSelectionStatus"),
        "previousTerminalResult": copy.deepcopy(previous_result),
        "previousAttemptKey": ranked_candidate_attempt_key(ranked_candidate),
        "reviewSourceClips": [],
        "rejectedSourceClips": [],
        "failures": [
            {
                "reason": "previous_terminal_quality_decision",
                "message": "Skipped because this exact source candidate/window already ended in a terminal quality decision.",
            }
        ],
        "timings": {"totalSeconds": 0.0},
    }
    result.update(source_window_attempt_manifest(ranked_candidate))
    return result


def ranked_candidates_to_process_with_previous_terminal_skips(
    candidates: list[RankedCandidate],
    *,
    request: BakeAndRankRequest,
    fallback_ready_target: int,
) -> tuple[list[tuple[int, RankedCandidate]], dict[int, dict[str, Any]]]:
    previous_terminal_results = load_previous_terminal_candidate_results(request.workspace)
    candidates_to_process: list[tuple[int, RankedCandidate]] = []
    skipped_by_original_index: dict[int, dict[str, Any]] = {}
    new_candidate_count = 0
    for original_index, ranked_candidate in enumerate(candidates):
        attempt_key = ranked_candidate_attempt_key(ranked_candidate)
        previous_terminal_result = previous_terminal_results.get(attempt_key)
        if previous_terminal_result is not None:
            skipped_by_original_index[original_index] = build_skipped_previous_terminal_result(
                ranked_candidate,
                previous_terminal_result,
            )
            continue
        if request.pre_wham_source_validation and new_candidate_count >= fallback_ready_target:
            break
        candidates_to_process.append((original_index, ranked_candidate))
        new_candidate_count += 1
    return candidates_to_process, skipped_by_original_index


@dataclass(frozen=True)
class SourceWindowVariant:
    hint: SourceChunkHint
    source: str
    original_index: int | None = None


def source_chunk_hint_manifest(hint: SourceChunkHint | None) -> dict[str, Any] | None:
    if hint is None:
        return None
    return {
        "startSeconds": hint.start_seconds,
        "endSeconds": hint.end_seconds,
        "durationSeconds": hint.duration_seconds,
        "score": hint.score,
    }


def source_window_attempt_manifest(ranked_candidate: RankedCandidate) -> dict[str, Any]:
    hint = ranked_candidate.source_chunk_hint
    return {
        "sourceWindowAttemptKey": ranked_candidate_attempt_key(ranked_candidate),
        "sourceWindowAttemptIndex": parse_optional_int(ranked_candidate.candidate.get("sourceWindowAttemptIndex")),
        "sourceWindowAttemptSource": ranked_candidate.candidate.get("sourceWindowAttemptSource"),
        "sourceWindowAttemptMode": ranked_candidate.candidate.get("sourceWindowAttemptMode"),
        "sourceWindowParentFallback": parse_optional_bool(
            ranked_candidate.candidate.get("sourceWindowParentFallback")
        ),
        "sourceWindowParentFallbackReason": ranked_candidate.candidate.get("sourceWindowParentFallbackReason"),
        "sourceWindow": source_chunk_hint_manifest(hint),
    }


def source_window_key(hint: SourceChunkHint) -> tuple[int, int]:
    return (
        int(round(hint.start_seconds * 1000.0)),
        int(round(hint.end_seconds * 1000.0)),
    )


def source_window_usable_for_attempt(
    hint: SourceChunkHint,
    request: BakeAndRankRequest,
    *,
    min_seconds_override: float | None = None,
) -> bool:
    if hint.end_seconds <= hint.start_seconds:
        return False
    min_seconds = max(0.5, min(float(request.segment_min_seconds), float(request.segment_max_seconds)))
    if min_seconds_override is not None:
        min_seconds = max(min_seconds, float(min_seconds_override))
    max_seconds = max(float(request.segment_max_seconds), min_seconds)
    return min_seconds <= hint.duration_seconds <= max_seconds


def source_window_min_seconds_for_candidate(
    ranked_candidate: RankedCandidate,
    request: BakeAndRankRequest,
) -> float:
    min_seconds = max(0.5, min(float(request.segment_min_seconds), float(request.segment_max_seconds)))
    contract = exercise_motion_contract_from_candidate(ranked_candidate.candidate)
    if not observable_motion_spec_requires_return(contract):
        return min_seconds
    chunk_estimate = estimate_chunking(exercise_name=ranked_candidate.exercise_name, use_llm=False)
    estimated_min = parse_optional_float(getattr(chunk_estimate, "rep_duration_min_sec", None))
    full_cycle_min = max(
        min_seconds,
        SOURCE_WINDOW_FULL_CYCLE_MIN_SECONDS,
        (estimated_min or min_seconds) * SOURCE_WINDOW_FULL_CYCLE_MIN_ESTIMATED_DURATION_RATIO,
    )
    max_seconds = max(float(request.segment_max_seconds), min_seconds)
    return min(full_cycle_min, max_seconds)


def parse_source_window_variant(
    payload: dict[str, Any],
    *,
    source: str,
    original_index: int | None = None,
) -> SourceWindowVariant | None:
    start_seconds = parse_optional_float(payload.get("startSeconds"))
    end_seconds = parse_optional_float(payload.get("endSeconds"))
    if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
        return None
    return SourceWindowVariant(
        hint=SourceChunkHint(
            start_seconds=max(0.0, start_seconds),
            end_seconds=end_seconds,
            score=parse_optional_float(payload.get("score")),
        ),
        source=source,
        original_index=original_index,
    )


def collect_source_window_variants(
    ranked_candidate: RankedCandidate,
    *,
    request: BakeAndRankRequest,
) -> list[SourceWindowVariant]:
    variants: list[SourceWindowVariant] = []
    seen: set[tuple[int, int]] = set()
    min_seconds = source_window_min_seconds_for_candidate(ranked_candidate, request)

    def add_variant(variant: SourceWindowVariant, *, allow_short_fallback: bool = False) -> bool:
        if not allow_short_fallback and not source_window_usable_for_attempt(
            variant.hint,
            request,
            min_seconds_override=min_seconds,
        ):
            return False
        key = source_window_key(variant.hint)
        if key in seen:
            return False
        seen.add(key)
        variants.append(variant)
        return True

    current_hint = ranked_candidate.source_chunk_hint
    current_variant = (
        SourceWindowVariant(current_hint, "ranked_best_chunk")
        if current_hint is not None
        else None
    )
    if current_variant is not None:
        add_variant(current_variant)

    vision_payload = ranked_candidate.candidate.get("visionPayload")
    if isinstance(vision_payload, dict):
        reviewed_chunks = vision_payload.get("reviewedChunks")
        reviewed_variant_count = 0
        if isinstance(reviewed_chunks, list):
            for index, chunk in enumerate(reviewed_chunks):
                if not isinstance(chunk, dict) or parse_optional_bool(chunk.get("valid")) is False:
                    continue
                variant = parse_source_window_variant(
                    chunk,
                    source=str(chunk.get("windowSource") or "chunked_source_video_review"),
                    original_index=index,
                )
                if variant is not None and (
                    variant.hint.score is None
                    or variant.hint.score >= SOURCE_GATE_MIN_BEST_CHUNK_SCORE
                ):
                    if add_variant(variant):
                        reviewed_variant_count += 1

        # If source-video semantic review produced usable windows, treat that
        # reviewed list as authoritative. Pose-only windows are just a fast
        # deterministic prefilter and can include good-looking sub-drills from
        # tutorial videos that are not the requested full movement.
        pose_payload = vision_payload.get("posePrefilter") if reviewed_variant_count == 0 else None
        if isinstance(pose_payload, dict):
            valid_chunks = pose_payload.get("validChunks")
            if isinstance(valid_chunks, list):
                for index, chunk in enumerate(valid_chunks):
                    if not isinstance(chunk, dict):
                        continue
                    variant = parse_source_window_variant(
                        chunk,
                        source="pose_prefilter",
                        original_index=index,
                    )
                    if variant is not None and (
                        variant.hint.score is None
                        or variant.hint.score >= SOURCE_GATE_STRONG_BEST_CHUNK_SCORE
                    ):
                        add_variant(variant)

    if variants:
        return variants
    if current_variant is not None:
        add_variant(current_variant, allow_short_fallback=True)
        if variants:
            return variants
    return []


def ranked_candidate_with_source_window_variant(
    ranked_candidate: RankedCandidate,
    variant: SourceWindowVariant,
    *,
    attempt_index: int,
    preserve_original: bool,
) -> RankedCandidate:
    if preserve_original:
        return ranked_candidate
    candidate = copy.deepcopy(ranked_candidate.candidate)
    candidate["sourceWindowAttemptIndex"] = attempt_index
    candidate["sourceWindowAttemptSource"] = variant.source
    candidate["sourceWindowAttemptOriginalIndex"] = variant.original_index
    candidate["sourceWindowHint"] = source_chunk_hint_manifest(variant.hint)
    vision_payload = candidate.get("visionPayload")
    if not isinstance(vision_payload, dict):
        vision_payload = {}
        candidate["visionPayload"] = vision_payload
    vision_payload["bestChunkStartSeconds"] = variant.hint.start_seconds
    vision_payload["bestChunkEndSeconds"] = variant.hint.end_seconds
    vision_payload["bestChunkScore"] = variant.hint.score
    vision_payload["bestChunkSource"] = variant.source
    updated = replace(ranked_candidate, candidate=candidate)
    candidate["sourceWindowAttemptKey"] = ranked_candidate_attempt_key(updated)
    return updated


def ranked_candidate_with_parent_source_window_fallback(
    ranked_candidate: RankedCandidate,
    *,
    reason: str,
) -> RankedCandidate | None:
    hint = ranked_candidate.source_chunk_hint
    if hint is None:
        return None
    if parse_optional_bool(ranked_candidate.candidate.get("sourceWindowParentFallback")) is True:
        return None
    candidate = copy.deepcopy(ranked_candidate.candidate)
    current_attempt_index = parse_optional_int(candidate.get("sourceWindowAttemptIndex"))
    candidate["sourceWindowAttemptIndex"] = 1 if current_attempt_index is None else current_attempt_index + 1
    candidate["sourceWindowAttemptSource"] = PARENT_SOURCE_WINDOW_FALLBACK_ATTEMPT_MODE
    candidate["sourceWindowAttemptMode"] = PARENT_SOURCE_WINDOW_FALLBACK_ATTEMPT_MODE
    candidate["sourceWindowParentFallback"] = True
    candidate["sourceWindowParentFallbackReason"] = reason
    candidate["sourceWindowHint"] = source_chunk_hint_manifest(hint)
    updated = replace(ranked_candidate, candidate=candidate)
    candidate["sourceWindowAttemptKey"] = ranked_candidate_attempt_key(updated)
    return updated


def expand_ranked_candidates_for_source_windows(
    candidates: list[RankedCandidate],
    *,
    request: BakeAndRankRequest,
) -> list[RankedCandidate]:
    variant_groups: list[list[RankedCandidate]] = []
    max_source_window_attempts = max(0, int(request.max_source_window_attempts or 0))
    for ranked_candidate in candidates:
        variants = collect_source_window_variants(ranked_candidate, request=request)
        if max_source_window_attempts > 0:
            variants = variants[:max_source_window_attempts]
        if not variants:
            variant_groups.append([ranked_candidate])
            continue
        current_hint = ranked_candidate.source_chunk_hint
        group: list[RankedCandidate] = []
        for attempt_index, variant in enumerate(variants):
            preserve_original = (
                attempt_index == 0
                and current_hint is not None
                and source_window_key(current_hint) == source_window_key(variant.hint)
            )
            group.append(
                ranked_candidate_with_source_window_variant(
                    ranked_candidate,
                    variant,
                    attempt_index=attempt_index,
                    preserve_original=preserve_original,
                )
            )
        variant_groups.append(group)

    expanded: list[RankedCandidate] = []
    max_group_size = max((len(group) for group in variant_groups), default=0)
    for variant_index in range(max_group_size):
        for group in variant_groups:
            if variant_index < len(group):
                expanded.append(group[variant_index])
    return expanded


def review_item_attempt_key(item: ReviewItem) -> str:
    explicit_key = item.candidate.get("sourceWindowAttemptKey")
    if isinstance(explicit_key, str) and explicit_key.strip():
        return explicit_key.strip()
    ranked_candidate = RankedCandidate(
        exercise_index=item.exercise_index,
        candidate_rank=item.candidate_rank,
        exercise_id=item.exercise_name,
        exercise_name=item.exercise_name,
        exercise_slug=slugify(item.exercise_name),
        candidate=item.candidate,
    )
    return ranked_candidate_attempt_key(ranked_candidate)


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
    export_payload: dict[str, Any] | None = None


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
    sample_frame_paths: list[Path] = field(default_factory=list)
    visual_integrity: dict[str, Any] = field(default_factory=dict)
    pose_prefilter: dict[str, Any] = field(default_factory=dict)
    motion_coverage: dict[str, Any] = field(default_factory=dict)
    chunking: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceWindowCandidateSpec:
    window: DetectionWindow
    chunking: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CutCandidateBatchChoice:
    ranking: LoopRanking | None
    raw_responses: list[str]
    errors: list[dict[str, Any]]
    reviewed_candidate_ids: list[str]
    reviewed_batch_count: int
    elapsed_seconds: float
    rankings: list[LoopRanking] = field(default_factory=list)


@dataclass(frozen=True)
class CutCandidateBatchResult:
    rankings: list[LoopRanking]
    raw_responses: list[str]
    errors: list[dict[str, Any]]
    reviewed_candidate_ids: list[str]


class SourceCandidateRejected(RuntimeError):
    """Raised when the source video is visually rejected before WHAM."""


@dataclass(frozen=True)
class BakeAndRankRequest:
    candidates_json: Path
    workspace: Path
    wham_repo_path: Path | None
    body_model_root: Path | None
    youtube_cookies: Path | None = None
    youtube_source_cache_dir: Path | None = None
    youtube_preview_cache_dir: Path | None = None
    fallback_candidates: int = DEFAULT_FALLBACK_CANDIDATES
    max_source_window_attempts: int = DEFAULT_MAX_SOURCE_WINDOW_ATTEMPTS
    max_selected_results: int = 1
    candidate_workers: int = 1
    wham_python_command: str = "python"
    reuse_wham_cache: bool = True
    use_wham_docker: bool = False
    wham_docker_image: str = DEFAULT_WHAM_DOCKER_IMAGE
    wham_docker_gpus: str = "all"
    wham_docker_shm_size: str = DEFAULT_WHAM_DOCKER_SHM_SIZE
    use_warm_wham_worker: bool = False
    wham_worker_session_dir: Path | None = None
    wham_worker_mount_root: Path | None = None
    wham_worker_timeout_seconds: float | None = None
    wham_timeout_seconds: float | None = None
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
    exercise_motion_contract_enabled: bool = True
    review_frames: int = DEFAULT_REVIEW_FRAMES
    review_llm_workers: int = 3
    max_llm_review_items: int = 4
    max_review_windows: int = DEFAULT_MAX_REVIEW_WINDOWS
    max_loop_seconds: float = DEFAULT_MAX_LOOP_SECONDS
    min_selected_score: float = DEFAULT_MIN_SELECTED_SCORE
    motion_tuning_enabled: bool = True
    export_wham_smpl_preview: bool = False
    select_preview_section: bool = False
    rank_preview_variants: bool = False
    adaptive_preview_settings: bool = False
    max_adaptive_preview_settings: int = 3
    classify_support_dominance: bool = True
    final_output_validation: bool = False
    final_output_validation_min_score: float = DEFAULT_FINAL_OUTPUT_VALIDATION_MIN_SCORE
    llama_cpp_base_url: str | None = "http://127.0.0.1:8090"
    llama_cpp_model: str = DEFAULT_LLAMA_CPP_MODEL
    llama_cpp_server_command: str | None = None
    llama_cpp_mmproj: str | None = DEFAULT_LLAMA_CPP_MMPROJ
    llama_cpp_backend: str = "gpu"
    llama_cpp_n_predict: int = 512
    llama_cpp_temperature: float = DEFAULT_LLAMA_CPP_TEMPERATURE
    llama_cpp_top_p: float | None = DEFAULT_LLAMA_CPP_TOP_P
    llama_cpp_top_k: int | None = DEFAULT_LLAMA_CPP_TOP_K
    llama_cpp_disable_reasoning: bool = False
    llama_cpp_reasoning_budget: int | None = DEFAULT_LLAMA_CPP_REASONING_BUDGET
    llama_cpp_reasoning_budget_message: str | None = DEFAULT_LLAMA_CPP_REASONING_BUDGET_MESSAGE
    llama_cpp_ctx_size: int | None = DEFAULT_LLAMA_CPP_CTX_SIZE
    llama_cpp_batch_size: int | None = DEFAULT_LLAMA_CPP_BATCH_SIZE
    llama_cpp_ubatch_size: int | None = DEFAULT_LLAMA_CPP_UBATCH_SIZE
    llama_cpp_flash_attn: str | None = DEFAULT_LLAMA_CPP_FLASH_ATTN
    llama_cpp_cache_type_k: str | None = DEFAULT_LLAMA_CPP_CACHE_TYPE_K
    llama_cpp_cache_type_v: str | None = DEFAULT_LLAMA_CPP_CACHE_TYPE_V
    llama_cpp_parallel: int | None = DEFAULT_LLAMA_CPP_PARALLEL
    llama_cpp_threads_http: int | None = None
    llama_cpp_cache_reuse: int | None = None
    llama_cpp_fit: str | None = DEFAULT_LLAMA_CPP_FIT
    llama_cpp_fit_ctx: int | None = DEFAULT_LLAMA_CPP_FIT_CTX
    llama_cpp_fit_target: int | None = DEFAULT_LLAMA_CPP_FIT_TARGET
    llama_cpp_mmap: bool = DEFAULT_LLAMA_CPP_MMAP
    llama_cpp_mlock: bool = DEFAULT_LLAMA_CPP_MLOCK
    llama_cpp_mmproj_offload: bool = True
    llama_cpp_cont_batching: bool = True
    llama_cpp_image_min_tokens: int | None = None
    llama_cpp_image_max_tokens: int | None = DEFAULT_LLAMA_CPP_IMAGE_MAX_TOKENS
    llama_cpp_mtmd_batch_max_tokens: int | None = DEFAULT_LLAMA_CPP_MTMD_BATCH_MAX_TOKENS
    llama_cpp_auto_start_server: bool = True
    keep_llama_cpp_server: bool = False
    llama_cpp_server_startup_timeout_seconds: float = 180.0
    llama_cpp_request_timeout_seconds: float = 90.0
    artifact_retention: str = ARTIFACT_RETENTION_DEBUG


PreviewBaker = Callable[..., list[BakedLoopArtifact]]
LoopRanker = Callable[[list[ReviewItem], BakeAndRankRequest], list[LoopRanking]]
ExerciseMotionContractResolver = Callable[[RankedCandidate], dict[str, Any] | None]
ExerciseSkeletonContractResolver = Callable[[RankedCandidate], dict[str, Any] | None]
SelectedArtifact = tuple[ReviewItem, LoopRanking | None]


def load_ranked_candidates_manifest(
    path: Path,
    *,
    include_fallback_candidates: bool = False,
) -> list[RankedCandidate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    all_candidates = parse_ranked_candidates_manifest(payload)
    parsed_candidates = [
        candidate
        for candidate in all_candidates
        if candidate_bake_status(candidate) != "rejected"
    ]
    candidates = parsed_candidates
    if is_youtube_candidates_manifest(payload):
        recommended_candidates = [
            candidate
            for candidate in all_candidates
            if candidate_bake_status(candidate) == "recommended"
        ]
        if include_fallback_candidates:
            fallback_candidates = [
                mark_ranked_candidate_as_bake_fallback(candidate)
                for candidate in all_candidates
                if candidate_bake_status(candidate) not in {"recommended", "disabled"}
            ]
            candidates = [*recommended_candidates, *fallback_candidates]
            if not candidates:
                raise ValueError("No YouTube candidate found in the candidates manifest.")
        elif not recommended_candidates:
            raise ValueError(
                "No recommended YouTube candidate found. Non-recommended YouTube candidates are not "
                "allowed to proceed to bake-and-rank; inspect the YouTube candidates JSON and fix "
                "source discovery instead."
            )
        else:
            candidates = recommended_candidates
    reviewed_candidates = [
        candidate
        for candidate in candidates
        if isinstance(candidate.candidate.get("visionPayload"), dict)
    ]
    if reviewed_candidates and not include_fallback_candidates:
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


def mark_ranked_candidate_as_bake_fallback(candidate: RankedCandidate) -> RankedCandidate:
    original_status = candidate_bake_status(candidate)
    payload = dict(candidate.candidate)
    payload["bakeFallbackCandidate"] = True
    if original_status:
        payload["sourceDiscoveryStatus"] = original_status
    return replace(candidate, candidate=payload)


def evaluate_source_candidate_gate(candidate: RankedCandidate) -> dict[str, Any]:
    status = candidate_bake_status(candidate)
    bake_fallback_candidate = parse_optional_bool(candidate.candidate.get("bakeFallbackCandidate")) is True
    reasons: list[str] = []
    if status == "disabled" or (status == "rejected" and not bake_fallback_candidate):
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
        "bakeFallbackCandidate": bake_fallback_candidate,
        "sourceDiscoveryStatus": candidate.candidate.get("sourceDiscoveryStatus"),
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


def choose_top_review_items(
    items: list[ReviewItem],
    rankings: list[LoopRanking],
    *,
    min_score: float = 0.0,
    max_results: int = 1,
) -> list[SelectedArtifact]:
    paired = [
        pair
        for pair in zip(items, rankings)
        if selected_artifact_score(pair) >= min_score
    ]
    paired.sort(key=selected_artifact_sort_key, reverse=True)
    return paired[:max(1, int(max_results or 1))]


def max_selected_results_for_request(request: BakeAndRankRequest) -> int:
    return max(1, int(request.max_selected_results or 1))


def ready_candidate_target_for_request(request: BakeAndRankRequest) -> int:
    return max(1, int(request.fallback_candidates), max_selected_results_for_request(request))


def candidate_attempt_budget_for_request(request: BakeAndRankRequest) -> int:
    base_target = ready_candidate_target_for_request(request)
    if not request.pre_wham_source_validation:
        return base_target
    source_window_attempts = max(1, int(request.max_source_window_attempts or 1))
    return max(base_target, base_target * source_window_attempts)


def selected_artifact_sort_key(selected: SelectedArtifact) -> tuple[float, int, int, int]:
    item, _ranking = selected
    return (
        selected_artifact_score(selected),
        -item.exercise_index,
        -item.candidate_rank,
        -item.loop_index,
    )


MATERIALIZATION_BLOCKING_RANKING_REASONS = {
    "movement_cut_target_motion_gate_failed",
}


def ranking_blocks_materialization(ranking: LoopRanking | None) -> bool:
    if ranking is None:
        return False
    ranking_reasons = {str(reason) for reason in ranking.reasons}
    if ranking_reasons.intersection(MATERIALIZATION_BLOCKING_RANKING_REASONS):
        return True
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    return parse_optional_bool(payload.get("movementCutTargetMotionGateFailed")) is True


def materialize_selection_candidate(
    original: SelectedArtifact,
    *,
    request: BakeAndRankRequest,
    materialized_quality_rescore_enabled: bool,
    final_output_caption_images: Callable[..., str] | None = None,
) -> tuple[SelectedArtifact | None, SelectedArtifact | None]:
    item, ranking = original
    if ranking is not None and ranking.score < request.min_selected_score and "llm_review_skipped_by_prefilter" in ranking.reasons:
        return None, original
    if ranking is not None and ranking.score < request.min_selected_score and ranking_blocks_materialization(ranking):
        return None, original

    materialized = refresh_materialized_selection_ranking(
        original=original,
        materialized=materialize_llm_selected_time_range(original, request=request),
    )
    if materialized_quality_rescore_enabled:
        materialized = rescore_materialized_deterministic_quality(materialized)
    materialized = apply_materialized_output_acceptance_gate(
        materialized,
        request=request,
        final_output_caption_images=final_output_caption_images,
    )
    if selected_artifact_score(materialized) >= request.min_selected_score:
        fallback = materialize_clean_subinterval_fallback(
            original=original,
            rejected=materialized,
            request=request,
        )
        if fallback is not None and recovered_artifact_is_better(materialized, fallback):
            fallback = apply_materialized_output_acceptance_gate(
                fallback,
                request=request,
                final_output_caption_images=final_output_caption_images,
            )
            return fallback, None
        return materialized, None

    parent_fallback = materialize_parent_review_item_fallback(
        original=original,
        rejected=materialized,
    )
    if parent_fallback is not None:
        if materialized_quality_rescore_enabled:
            parent_fallback = rescore_materialized_deterministic_quality(parent_fallback)
        parent_fallback = apply_materialized_output_acceptance_gate(
            parent_fallback,
            request=request,
            final_output_caption_images=final_output_caption_images,
        )
        if selected_artifact_score(parent_fallback) >= request.min_selected_score:
            return parent_fallback, None
        if selected_artifact_score(parent_fallback) > selected_artifact_score(materialized):
            materialized = parent_fallback

    fallback = materialize_clean_subinterval_fallback(
        original=original,
        rejected=materialized,
        request=request,
    )
    if fallback is not None:
        if materialized_quality_rescore_enabled:
            fallback = rescore_materialized_deterministic_quality(fallback)
        fallback = apply_materialized_output_acceptance_gate(
            fallback,
            request=request,
            final_output_caption_images=final_output_caption_images,
        )
        if selected_artifact_score(fallback) >= request.min_selected_score:
            return fallback, None
        if selected_artifact_score(fallback) > selected_artifact_score(materialized):
            return None, fallback
    return None, materialized


def materialize_parent_review_item_fallback(
    *,
    original: SelectedArtifact,
    rejected: SelectedArtifact,
) -> SelectedArtifact | None:
    original_item, original_ranking = original
    rejected_item, rejected_ranking = rejected
    if original_ranking is None or rejected_ranking is None:
        return None
    if not rejected_item.llm_time_range_cut_applied:
        return None
    if original_item == rejected_item:
        return None
    if not materialized_output_was_rejected(rejected):
        return None
    if not original_item.skeleton_path.exists() or not original_item.review_video_path.exists():
        return None

    original_score = clamp_unit(selected_artifact_score(original))
    rejected_payload = rejected_ranking.payload if isinstance(rejected_ranking.payload, dict) else {}
    payload = dict(original_ranking.payload or {})
    payload.update(
        {
            "llmSelectedSectionParentFallback": True,
            "llmSelectedSectionParentFallbackReason": "selected_section_failed_materialized_output_validation",
            "llmSelectedSectionParentFallbackRejectedChild": {
                "score": selected_artifact_score(rejected),
                "sectionStartSeconds": rejected_item.loop_start_seconds,
                "sectionEndSeconds": rejected_item.loop_end_seconds,
                "durationSeconds": rejected_item.duration_sec,
                "reasons": rejected_ranking.reasons,
                "materializedOutputRejectionReasons": rejected_payload.get("materializedOutputRejectionReasons"),
            },
        }
    )
    fallback_ranking = LoopRanking(
        score=original_score,
        reasons=dedupe_text(
            [
                *recomputed_materialized_reasons(original_ranking.reasons),
                "llm_selected_section_parent_fallback",
            ]
        ),
        raw_response=original_ranking.raw_response,
        payload=payload,
        model_score=original_score,
        continuity_score=original_ranking.continuity_score,
        continuity_metrics=original_ranking.continuity_metrics,
    )
    return (
        original_item,
        apply_loop_continuity_adjustment(original_item, fallback_ranking),
    )


def materialized_output_was_rejected(selected: SelectedArtifact) -> bool:
    _item, ranking = selected
    if ranking is None:
        return False
    if "materialized_output_rejected" in ranking.reasons:
        return True
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    return parse_optional_bool(payload.get("materializedOutputRejected")) is True


def choose_best_materialized_review_item(
    items: list[ReviewItem],
    rankings: list[LoopRanking],
    *,
    request: BakeAndRankRequest,
    final_output_caption_images: Callable[..., str] | None = None,
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
        materialize_kwargs: dict[str, Any] = {
            "request": request,
            "materialized_quality_rescore_enabled": materialized_quality_rescore_enabled,
        }
        if final_output_caption_images is not None:
            materialize_kwargs["final_output_caption_images"] = final_output_caption_images
        accepted, rejected = materialize_selection_candidate((item, ranking), **materialize_kwargs)
        if accepted is not None:
            if accepted_best is None or selected_artifact_sort_key(accepted) > selected_artifact_sort_key(accepted_best):
                accepted_best = accepted
            continue
        if rejected is not None and (
            rejected_best is None
            or selected_artifact_sort_key(rejected) > selected_artifact_sort_key(rejected_best)
        ):
            rejected_best = rejected
    if accepted_best is not None:
        return accepted_best, None
    return None, rejected_best


def choose_top_materialized_review_items(
    items: list[ReviewItem],
    rankings: list[LoopRanking],
    *,
    request: BakeAndRankRequest,
    max_results: int | None = None,
    final_output_caption_images: Callable[..., str] | None = None,
) -> tuple[list[SelectedArtifact], SelectedArtifact | None]:
    paired = sorted(
        zip(items, rankings),
        key=selected_artifact_sort_key,
        reverse=True,
    )
    if not paired:
        return [], None

    limit = max(1, int(max_results or max_selected_results_for_request(request)))
    materialized_quality_rescore_enabled = (
        len({(item.exercise_index, item.candidate_rank) for item, _ranking in paired}) > 1
    )
    accepted_by_source_window: dict[str, SelectedArtifact] = {}
    rejected_best: SelectedArtifact | None = None
    for item, ranking in paired:
        materialize_kwargs: dict[str, Any] = {
            "request": request,
            "materialized_quality_rescore_enabled": materialized_quality_rescore_enabled,
        }
        if final_output_caption_images is not None:
            materialize_kwargs["final_output_caption_images"] = final_output_caption_images
        accepted, rejected = materialize_selection_candidate((item, ranking), **materialize_kwargs)
        if accepted is not None:
            attempt_key = review_item_attempt_key(accepted[0])
            existing = accepted_by_source_window.get(attempt_key)
            if existing is None or selected_artifact_sort_key(accepted) > selected_artifact_sort_key(existing):
                accepted_by_source_window[attempt_key] = accepted
        if rejected is not None and (
            rejected_best is None
            or selected_artifact_sort_key(rejected) > selected_artifact_sort_key(rejected_best)
        ):
            rejected_best = rejected

    accepted = sorted(
        accepted_by_source_window.values(),
        key=selected_artifact_sort_key,
        reverse=True,
    )
    if accepted:
        return accepted[:limit], None
    return [], rejected_best


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
        camera_yaw_degrees=optional_float_or_default(
            item.settings_options.get("cameraYawDegrees"),
            FIXED_PREVIEW_CAMERA_YAW_DEGREES,
        ),
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


def apply_materialized_output_acceptance_gate(
    selected: SelectedArtifact,
    *,
    request: BakeAndRankRequest,
    final_output_caption_images: Callable[..., str] | None = None,
) -> SelectedArtifact:
    item, ranking = selected
    if ranking is None:
        return selected
    metrics = materialized_output_acceptance_metrics(item, ranking)
    final_validation = final_output_validation_metrics(
        item,
        ranking,
        request=request,
        deterministic_metrics=metrics,
        caption_images=final_output_caption_images,
    )
    payload = dict(ranking.payload or {})
    payload["materializedOutputAcceptanceGate"] = metrics
    payload["finalOutputValidation"] = final_validation
    final_validation_enabled = bool(final_validation.get("enabled", request.final_output_validation))
    accepted = (
        bool(final_validation.get("passed", True))
        if final_validation_enabled
        else bool(metrics.get("passed", True))
    )
    if accepted:
        payload["materializedOutputRejected"] = False
        return (
            item,
            LoopRanking(
                score=ranking.score,
                reasons=ranking.reasons,
                raw_response=ranking.raw_response,
                payload=payload,
                model_score=ranking.model_score,
                continuity_score=ranking.continuity_score,
                continuity_metrics=ranking.continuity_metrics,
            ),
        )

    rejection_reasons = [
        str(reason)
        for reason in [
            *list(metrics.get("rejectionReasons", []) if isinstance(metrics.get("rejectionReasons"), list) else []),
            *list(final_validation.get("rejectionReasons", []) if isinstance(final_validation.get("rejectionReasons"), list) else []),
        ]
        if str(reason)
    ]
    score_cap = max(
        0.0,
        min(
            LOOP_WEAK_FULL_REP_SCORE_CAP,
            FINAL_OUTPUT_VALIDATION_REJECTION_SCORE_CAP,
            request.min_selected_score - 0.01,
        ),
    )
    capped_score = min(ranking.score, score_cap)
    payload["materializedOutputRejected"] = True
    payload["materializedOutputRejectionReasons"] = rejection_reasons
    return (
        item,
        LoopRanking(
            score=capped_score,
            reasons=dedupe_text([*ranking.reasons, "materialized_output_rejected", *rejection_reasons]),
            raw_response=ranking.raw_response,
            payload=payload,
            model_score=capped_score,
            continuity_score=ranking.continuity_score,
            continuity_metrics=ranking.continuity_metrics,
        ),
    )


def final_output_validation_metrics(
    item: ReviewItem,
    ranking: LoopRanking,
    *,
    request: BakeAndRankRequest,
    deterministic_metrics: dict[str, Any],
    caption_images: Callable[..., str] | None,
) -> dict[str, Any]:
    if not request.final_output_validation:
        return {
            "enabled": False,
            "passed": True,
            "skippedReasons": ["final_output_validation_disabled"],
        }
    deterministic_passed = bool(deterministic_metrics.get("passed", True))
    deterministic_readability_metrics = (
        deterministic_metrics.get("previewReadabilityMetrics")
        if isinstance(deterministic_metrics.get("previewReadabilityMetrics"), dict)
        else {}
    )
    deterministic_readability_score = parse_optional_float(
        deterministic_readability_metrics.get("previewReadabilityScore")
    )
    deterministic_readability_low = (
        deterministic_readability_score is not None
        and deterministic_readability_score < FINAL_OUTPUT_VALIDATION_MIN_DETERMINISTIC_READABILITY_SCORE
    )
    deterministic_warnings: list[str] = []
    hard_deterministic_rejection_reasons = final_output_hard_deterministic_rejection_reasons(
        deterministic_metrics
    )
    if not deterministic_passed:
        deterministic_warnings.extend(
            [
                "final_output_deterministic_gate_failed",
                *[
                    str(reason)
                    for reason in deterministic_metrics.get("rejectionReasons", [])
                    if str(reason)
                ],
            ]
        )
    if deterministic_readability_low:
        deterministic_warnings.append("final_output_low_deterministic_readability")
    if hard_deterministic_rejection_reasons:
        return {
            "enabled": True,
            "backend": "deterministic_hard_gate",
            "passed": False,
            "score": FINAL_OUTPUT_VALIDATION_REJECTION_SCORE_CAP,
            "needsRetry": True,
            "rejectionReasons": dedupe_text(
                [
                    *deterministic_warnings,
                    "final_output_hard_deterministic_gate_failed",
                    *hard_deterministic_rejection_reasons,
                ]
            ),
            "deterministicHardRejectionReasons": hard_deterministic_rejection_reasons,
            "minDeterministicReadabilityScore": FINAL_OUTPUT_VALIDATION_MIN_DETERMINISTIC_READABILITY_SCORE,
            "deterministicReadabilityScore": deterministic_readability_score,
            "deterministicGate": deterministic_metrics,
            "deterministicGatePassed": False,
            "skippedReasons": ["final_output_vlm_skipped_hard_deterministic_gate"],
        }
    if caption_images is None:
        if deterministic_warnings:
            return {
                "enabled": True,
                "backend": "deterministic",
                "passed": False,
                "score": clamp_unit(deterministic_readability_score)
                if deterministic_readability_score is not None
                else 0.0,
                "rejectionReasons": dedupe_text(deterministic_warnings),
                "minDeterministicReadabilityScore": FINAL_OUTPUT_VALIDATION_MIN_DETERMINISTIC_READABILITY_SCORE,
                "deterministicReadabilityScore": deterministic_readability_score,
                "deterministicGate": deterministic_metrics,
                "deterministicGatePassed": deterministic_passed and not deterministic_readability_low,
            }
        return {
            "enabled": True,
            "backend": "deterministic",
            "passed": True,
            "skippedReasons": ["final_output_vlm_validator_unavailable"],
            "deterministicGate": deterministic_metrics,
            "deterministicGatePassed": True,
        }
    try:
        visual_metrics = validate_final_output_with_caption_images(
            item,
            ranking,
            request=request,
            caption_images=caption_images,
        )
    except Exception as exc:
        return {
            "enabled": True,
            "backend": "llama_cpp_vision",
            "passed": False,
            "score": 0.0,
            "rejectionReasons": ["final_output_validator_failed"],
            "error": f"{type(exc).__name__}: {exc}",
            "deterministicGate": deterministic_metrics,
            "deterministicGatePassed": deterministic_passed and not deterministic_readability_low,
            "deterministicWarnings": dedupe_text(deterministic_warnings),
        }
    visual_metrics["deterministicGate"] = deterministic_metrics
    visual_metrics["deterministicGatePassed"] = deterministic_passed and not deterministic_readability_low
    if deterministic_warnings:
        visual_metrics["deterministicWarnings"] = dedupe_text(deterministic_warnings)
        if deterministic_readability_score is not None:
            visual_metrics["deterministicReadabilityScore"] = deterministic_readability_score
        visual_metrics["minDeterministicReadabilityScore"] = FINAL_OUTPUT_VALIDATION_MIN_DETERMINISTIC_READABILITY_SCORE
    visual_metrics = maybe_accept_final_output_with_prior_motion_verification(
        item=item,
        ranking=ranking,
        deterministic_metrics=deterministic_metrics,
        visual_metrics=visual_metrics,
    )
    return visual_metrics


FINAL_OUTPUT_PRIOR_VERIFICATION_OVERRIDABLE_REASONS = frozenset(
    (
        "wrong_exercise",
        "partial_movement",
        "final_output_low_score",
        "final_output_low_exercise_match",
        "final_output_incomplete_movement",
        "final_output_needs_retry",
        "final_output_model_rejected",
    )
)


def maybe_accept_final_output_with_prior_motion_verification(
    *,
    item: ReviewItem,
    ranking: LoopRanking,
    deterministic_metrics: dict[str, Any],
    visual_metrics: dict[str, Any],
) -> dict[str, Any]:
    if bool(visual_metrics.get("passed", False)):
        return visual_metrics
    if not bool(deterministic_metrics.get("passed", True)):
        return visual_metrics
    ranking_reasons = {str(reason) for reason in ranking.reasons}
    if "movement_cut_binary_complete_movement_verified" not in ranking_reasons:
        return visual_metrics
    rejection_reasons = [
        str(reason)
        for reason in visual_metrics.get("rejectionReasons", [])
        if str(reason)
    ]
    if not rejection_reasons or any(
        reason not in FINAL_OUTPUT_PRIOR_VERIFICATION_OVERRIDABLE_REASONS
        for reason in rejection_reasons
    ):
        return visual_metrics
    phase_metrics = deterministic_metrics.get("fullRepetitionPhaseCompletenessMetrics")
    if isinstance(phase_metrics, dict) and bool(phase_metrics.get("required")) and not bool(phase_metrics.get("passed")):
        return visual_metrics
    partial_reasons = {"partial_movement", "final_output_incomplete_movement"}.intersection(rejection_reasons)
    if partial_reasons:
        ranking_payload = ranking.payload if isinstance(ranking.payload, dict) else {}
        min_selected_duration = parse_optional_float(ranking_payload.get("movementCutMinSelectedDurationSeconds"))
        selected_start = first_float(
            ranking_payload.get("selected_section_start_seconds"),
            ranking_payload.get("selectedSectionStartSeconds"),
        )
        selected_end = first_float(
            ranking_payload.get("selected_section_end_seconds"),
            ranking_payload.get("selectedSectionEndSeconds"),
        )
        selected_duration = (
            selected_end - selected_start
            if selected_start is not None and selected_end is not None and selected_end > selected_start
            else None
        )
        if min_selected_duration is None or selected_duration is None:
            return visual_metrics
        if selected_duration + 0.05 < min_selected_duration:
            return visual_metrics
    source_context_score = parse_optional_float(visual_metrics.get("sourceContextMatchScore"))
    if source_context_score is not None and source_context_score < 0.85:
        return visual_metrics
    wear_score = parse_optional_float(visual_metrics.get("wearReadabilityScore"))
    motion_score = parse_optional_float(visual_metrics.get("motionQualityScore"))
    if wear_score is not None and wear_score < 0.75:
        return visual_metrics
    if motion_score is not None and motion_score < 0.65:
        return visual_metrics

    accepted = dict(visual_metrics)
    accepted["passed"] = True
    accepted["needsRetry"] = False
    accepted["rejectionReasons"] = []
    accepted["priorMovementCutValidationOverride"] = True
    accepted["priorMovementCutValidationOverrideReason"] = (
        "final_output_vlm_rejected_identity_but_source_context_prior_movement_cut_and_deterministic_phase_passed"
    )
    accepted["overriddenRejectionReasons"] = dedupe_text(rejection_reasons)
    existing_warnings = accepted.get("validationWarnings")
    warning_reasons = (
        [str(reason) for reason in existing_warnings if str(reason)]
        if isinstance(existing_warnings, list)
        else []
    )
    warnings = [
        *warning_reasons,
        "final_output_vlm_rejection_overridden_by_prior_movement_cut",
    ]
    accepted["validationWarnings"] = dedupe_text(warnings)
    accepted["priorMovementCutValidationOverrideContext"] = {
        "exerciseName": item.exercise_name,
        "sourceContextMatchScore": source_context_score,
        "wearReadabilityScore": wear_score,
        "motionQualityScore": motion_score,
        "deterministicPhasePassed": None if not isinstance(phase_metrics, dict) else bool(phase_metrics.get("passed")),
    }
    return accepted


def final_output_hard_deterministic_rejection_reasons(
    deterministic_metrics: dict[str, Any],
) -> list[str]:
    reasons = deterministic_metrics.get("rejectionReasons")
    if not isinstance(reasons, list):
        return []
    return [
        text
        for text in dedupe_text(str(reason) for reason in reasons if str(reason))
        if text in FINAL_OUTPUT_HARD_DETERMINISTIC_REJECTION_REASONS
    ]


def cheap_final_output_preview_precheck(item: ReviewItem) -> dict[str, Any]:
    ranking = LoopRanking(
        score=1.0,
        reasons=["cheap_final_output_preview_precheck"],
        payload={"modelScore": 1.0},
        model_score=1.0,
    )
    deterministic_metrics = materialized_output_acceptance_metrics(item, ranking)
    hard_reasons = final_output_hard_deterministic_rejection_reasons(deterministic_metrics)
    return {
        "enabled": True,
        "passed": not hard_reasons,
        "deterministicGate": deterministic_metrics,
        "deterministicHardRejectionReasons": hard_reasons,
        "rejectionReasons": dedupe_text(
            [
                "final_output_hard_deterministic_gate_failed",
                *hard_reasons,
            ]
        )
        if hard_reasons
        else [],
    }


def validate_final_output_with_caption_images(
    item: ReviewItem,
    ranking: LoopRanking,
    *,
    request: BakeAndRankRequest,
    caption_images: Callable[..., str],
) -> dict[str, Any]:
    output_dir = (
        item.candidate_workspace
        / "review"
        / f"{final_output_validation_artifact_slug(item)}-final-output-validation"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    source_sheet_paths = final_output_source_contact_sheets(
        item,
        output_dir=output_dir / "source",
    )
    preview_sheet_paths = final_output_preview_contact_sheets(
        item,
        output_dir=output_dir / "preview",
    )
    has_source_context = bool(source_sheet_paths)
    frame_paths = [*source_sheet_paths, *preview_sheet_paths]
    if not preview_sheet_paths:
        return {
            "enabled": True,
            "backend": "llama_cpp_vision",
            "passed": False,
            "score": 0.0,
            "rejectionReasons": ["final_output_validation_no_frames"],
            "sourceContactSheetPaths": [str(path) for path in source_sheet_paths],
            "previewContactSheetPaths": [str(path) for path in preview_sheet_paths],
        }
    prompt_ranking = ranking
    exercise_skeleton_contract = exercise_skeleton_contract_for_review_item(item, ranking)
    if exercise_skeleton_contract is None and request.exercise_motion_contract_enabled:
        exercise_skeleton_contract = generate_exercise_skeleton_contract_for_review_item(
            item,
            request=request,
            caption_images=caption_images,
        )
        if exercise_skeleton_contract is not None:
            prompt_payload = dict(ranking.payload or {})
            prompt_payload["exerciseSkeletonContract"] = exercise_skeleton_contract
            prompt_ranking = replace(ranking, payload=prompt_payload)
    prompt = build_final_output_validation_prompt(
        item=item,
        ranking=prompt_ranking,
        has_source_context=has_source_context,
        min_score=request.final_output_validation_min_score,
    )
    started = time.perf_counter()
    raw = call_caption_images_json(
        caption_images,
        frame_paths=frame_paths,
        prompt=prompt,
        max_tokens=min(max(1, request.llama_cpp_n_predict), 512),
        request_timeout_seconds=request.llama_cpp_request_timeout_seconds,
        disable_reasoning=True,
        json_response=True,
        temperature=0.0,
        top_p=1.0,
    )
    parsed = parse_final_output_validation_response(
        raw,
        min_score=request.final_output_validation_min_score,
    )
    parsed.update(
        {
            "enabled": True,
            "backend": "llama_cpp_vision",
            "exerciseSkeletonContract": exercise_skeleton_contract,
            "rawResponse": raw,
            "sourceContactSheetPaths": [str(path) for path in source_sheet_paths],
            "previewContactSheetPaths": [str(path) for path in preview_sheet_paths],
            "sourceContextProvidedToValidator": has_source_context,
            "validatorImageOrder": (
                ["source_contact_sheets", "preview_contact_sheets"]
                if has_source_context
                else ["preview_contact_sheets"]
            ),
            "sourceContactSheetCount": len(source_sheet_paths),
            "previewContactSheetCount": len(preview_sheet_paths),
            "elapsedSeconds": elapsed_seconds(started),
        }
    )
    return parsed


def final_output_validation_artifact_slug(item: ReviewItem) -> str:
    artifact_label = "full-clip" if item.loop_index < 0 else f"loop-{item.loop_index + 1}"
    variant_label = slugify(item.settings_variant_id or "default")
    return f"{artifact_label}.{variant_label}"


def final_output_source_contact_sheets(item: ReviewItem, *, output_dir: Path) -> list[Path]:
    selected_input = selected_input_video_path_for_review_item(item)
    if selected_input is None:
        return []
    try:
        metadata = read_basic_video_metadata(selected_input)
    except Exception:
        return []
    duration = max(0.1, metadata.duration_seconds)
    return render_video_window_contact_sheet(
        video_path=selected_input,
        window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=duration),
        output_dir=output_dir,
        frame_count=FINAL_OUTPUT_VALIDATION_FRAME_COUNT,
    )


def final_output_preview_contact_sheets(item: ReviewItem, *, output_dir: Path) -> list[Path]:
    vlm_render_paths = final_output_vlm_preview_contact_sheets(
        item,
        output_dir=output_dir / "vlm-render",
    )
    if vlm_render_paths:
        return vlm_render_paths
    if not item.review_video_path.exists():
        return []
    try:
        metadata = read_basic_video_metadata(item.review_video_path)
    except Exception:
        duration = max(0.1, item.duration_sec)
    else:
        duration = max(0.1, metadata.duration_seconds)
    return render_video_window_contact_sheet(
        video_path=item.review_video_path,
        window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=duration),
        output_dir=output_dir,
        frame_count=FINAL_OUTPUT_VALIDATION_FRAME_COUNT,
    )


def final_output_vlm_preview_contact_sheets(item: ReviewItem, *, output_dir: Path) -> list[Path]:
    if not item.preview_html_path.exists():
        return []
    start_seconds = max(0.0, item.loop_start_seconds)
    end_seconds = item.loop_end_seconds
    if end_seconds <= start_seconds:
        end_seconds = start_seconds + max(0.1, item.duration_sec)
    try:
        return render_review_window_contact_sheet(
            item=item,
            window=DetectionWindow(index=0, start_seconds=start_seconds, end_seconds=end_seconds),
            output_dir=output_dir,
            frame_count=FINAL_OUTPUT_VALIDATION_FRAME_COUNT,
            vlm_review_style=True,
        )
    except Exception:
        return []


def selected_input_video_path_for_review_item(item: ReviewItem) -> Path | None:
    candidates = (
        item.candidate_workspace / "input" / "selected_segment.mp4",
        item.candidate_workspace / "input" / "source.mp4",
        item.candidate_workspace / "source" / "source.mp4",
    )
    return next((path for path in candidates if path.exists()), None)


def build_final_output_validation_prompt(
    *,
    item: ReviewItem,
    ranking: LoopRanking,
    has_source_context: bool,
    min_score: float,
) -> str:
    ranking_payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    model_score = parse_optional_float(ranking_payload.get("modelScore")) or ranking.score
    source_verified_context = ""
    if "movement_cut_binary_complete_movement_verified" in {str(reason) for reason in ranking.reasons}:
        selected_start = first_float(
            ranking_payload.get("selected_section_start_seconds"),
            ranking_payload.get("selectedSectionStartSeconds"),
        )
        selected_end = first_float(
            ranking_payload.get("selected_section_end_seconds"),
            ranking_payload.get("selectedSectionEndSeconds"),
        )
        if selected_start is not None and selected_end is not None and selected_end > selected_start:
            source_verified_context = (
                f"Prior source-cut review verified the selected source window as a complete target movement "
                f"from {selected_start:.2f}s to {selected_end:.2f}s; use that as source context, but still judge "
                "whether the generated skeleton preserves the visible body-motion sequence. "
            )
        else:
            source_verified_context = (
                "Prior source-cut review verified the selected source window as a complete target movement; "
                "use that as source context, but still judge whether the generated skeleton preserves the visible body-motion sequence. "
            )
    exercise_skeleton_contract = exercise_skeleton_contract_for_review_item(item, ranking)
    exercise_contract_context = build_final_output_skeleton_contract_prompt_section(exercise_skeleton_contract)
    attachment_description = (
        "Attached contact sheets are ordered as selected source-video evidence first, then final generated Wear skeleton preview evidence. "
        if has_source_context
        else "The attached contact sheet is the final generated Wear skeleton preview. "
    )
    return (
        "Validate the final generated exercise motion output.\n"
        f"Target exercise: {item.exercise_name}.\n"
        f"Candidate video title: {item.candidate_title}.\n"
        f"Previous selection score: {model_score:.3f}.\n"
        f"Minimum passing final-output score: {min_score:.2f}.\n"
        f"{attachment_description}"
        f"{CONTACT_SHEET_READING_INSTRUCTIONS}"
        f"{source_verified_context}"
        f"{exercise_contract_context}"
        "Use source sheets only to understand the intended exercise and movement phase. Do not pass the result because the source is good; judge pass/fail from the generated skeleton preview. "
        "The final preview intentionally omits external equipment, benches, bars, cables, wheels, machines, and props unless they are represented by body motion. "
        "Do not reject solely because non-body objects are invisible in the skeleton render, or because exact source endpoint criteria such as object clearance, contact, lockout, depth, or height are not obvious. "
        "Pass a generated skeleton when it looks like a reasonable body-only version of the target exercise: the broad body position, main direction of movement, and repeated phase order should make sense for the target. "
        "Still reject clearly wrong exercise mechanics, mostly setup, static motion, a partial one-way fragment when a full movement is required, unreadable watch output, tilted or awkward orientation that makes the motion hard to inspect, collapsed/broken body geometry, or boundaries that miss the useful movement. "
        "If the preview clearly resembles another common exercise more than the target, set exercise_match_score below 0.5, needs_retry true, and include wrong_exercise. "
        "Do not invent timestamps or exact start/end frames. Return only bounded scores and reason tags.\n"
        "Use these 0.0-1.0 scores: exercise_match_score, full_movement_score, wear_readability_score, motion_quality_score, source_context_match_score. "
        "Score 1.0 as excellent, 0.75 as usable, 0.5 as borderline, below 0.5 as bad. "
        "Set needs_retry true whenever another candidate/window should be tried. "
        "Allowed rejection reason tags: wrong_exercise, partial_movement, mostly_setup, too_static, unreadable_preview, tilted_preview, broken_skeleton, bad_boundary, source_context_mismatch, unclear.\n"
        "Return JSON only with keys: {\"passed\": boolean, \"score\": number, \"exercise_match_score\": number, \"full_movement_score\": number, \"wear_readability_score\": number, \"motion_quality_score\": number, \"source_context_match_score\": number|null, \"needs_retry\": boolean, \"rejection_reasons\": [string], \"reason\": string}."
    )


def parse_final_output_validation_response(raw: str, *, min_score: float) -> dict[str, Any]:
    payload = extract_json_object(raw)
    if not isinstance(payload, dict):
        return {
            "passed": False,
            "score": 0.0,
            "rejectionReasons": ["final_output_validator_invalid_json"],
            "modelPayload": None,
        }
    score = normalize_final_output_validator_score(payload.get("score"))
    exercise_match_score = normalize_final_output_validator_score(payload.get("exercise_match_score"))
    full_movement_score = normalize_final_output_validator_score(payload.get("full_movement_score"))
    wear_readability_score = normalize_final_output_validator_score(payload.get("wear_readability_score"))
    motion_quality_score = normalize_final_output_validator_score(payload.get("motion_quality_score"))
    source_context_match_score = normalize_final_output_validator_score(payload.get("source_context_match_score"))
    needs_retry = parse_optional_bool(payload.get("needs_retry")) is True
    model_passed = parse_optional_bool(payload.get("passed"))
    rejection_reasons = final_output_validator_rejection_reasons(payload)
    if score < min_score:
        rejection_reasons.append("final_output_low_score")
    if exercise_match_score < FINAL_OUTPUT_VALIDATION_MIN_EXERCISE_MATCH_SCORE:
        rejection_reasons.append("final_output_low_exercise_match")
    if full_movement_score < FINAL_OUTPUT_VALIDATION_MIN_FULL_MOVEMENT_SCORE:
        rejection_reasons.append("final_output_incomplete_movement")
    if wear_readability_score < FINAL_OUTPUT_VALIDATION_MIN_WEAR_READABILITY_SCORE:
        rejection_reasons.append("final_output_low_wear_readability")
    if motion_quality_score < FINAL_OUTPUT_VALIDATION_MIN_MOTION_QUALITY_SCORE:
        rejection_reasons.append("final_output_low_motion_quality")
    if needs_retry:
        rejection_reasons.append("final_output_needs_retry")
    if model_passed is False:
        rejection_reasons.append("final_output_model_rejected")
    reason_conflicts = final_output_validator_reason_conflict_reasons(payload)
    rejection_reasons.extend(reason_conflicts)
    passed = not rejection_reasons and (model_passed is not False)
    return {
        "passed": passed,
        "score": score,
        "exerciseMatchScore": exercise_match_score,
        "fullMovementScore": full_movement_score,
        "wearReadabilityScore": wear_readability_score,
        "motionQualityScore": motion_quality_score,
        "sourceContextMatchScore": source_context_match_score,
        "needsRetry": needs_retry,
        "rejectionReasons": dedupe_text(rejection_reasons),
        "reason": str(payload.get("reason") or "").strip(),
        "modelPayload": payload,
    }


def normalize_final_output_validator_score(value: Any) -> float:
    parsed = parse_optional_float(value)
    if parsed is None or not math.isfinite(parsed):
        return 0.0
    if parsed > 1.0:
        parsed = parsed / 100.0 if parsed <= 100.0 else 1.0
    return clamp_unit(parsed)


def final_output_validator_rejection_reasons(payload: dict[str, Any]) -> list[str]:
    reasons_value = payload.get("rejection_reasons") or payload.get("rejectionReasons") or []
    if isinstance(reasons_value, str):
        reasons = [reasons_value]
    elif isinstance(reasons_value, list):
        reasons = [str(reason) for reason in reasons_value]
    else:
        reasons = []
    normalized = []
    for reason in reasons:
        text = reason.strip()
        if not text or text == "none":
            continue
        normalized.append(text)
    return normalized


def final_output_validator_reason_conflict_reasons(payload: dict[str, Any]) -> list[str]:
    if parse_optional_bool(payload.get("passed")) is False:
        return []
    reason = str(payload.get("reason") or "").strip().lower()
    if not reason:
        return []
    conflict_phrases = (
        "more like",
        "rather than",
        "not a true",
        "not the target",
        "wrong exercise",
        "different exercise",
        "lacks the characteristic",
        "lacks the target",
        "does not resemble",
    )
    if any(phrase in reason for phrase in conflict_phrases):
        return ["final_output_reason_contradicts_pass"]
    return []


def materialized_output_acceptance_metrics(item: ReviewItem, ranking: LoopRanking) -> dict[str, Any]:
    if not item.skeleton_path.exists():
        return {
            "passed": True,
            "skippedReasons": ["materialized_output_skeleton_missing"],
        }
    rejection_reasons: list[str] = []
    skipped_reasons: list[str] = []
    try:
        motion_metrics = compute_motion_strength_metrics(item.skeleton_path)
    except Exception:
        motion_metrics = empty_motion_strength_metrics()
        skipped_reasons.append("materialized_motion_metrics_unavailable")
    try:
        readability_metrics = compute_preview_readability_metrics(
            item.skeleton_path,
            camera_yaw_degrees=optional_float_or_default(
                item.settings_options.get("cameraYawDegrees"),
                FIXED_PREVIEW_CAMERA_YAW_DEGREES,
            ),
        )
    except Exception:
        readability_metrics = {"previewReadabilityScore": None}
        skipped_reasons.append("materialized_preview_readability_metrics_unavailable")
    try:
        kinematic_metrics = compute_kinematic_plausibility_metrics(item.skeleton_path)
    except Exception:
        kinematic_metrics = {"kinematicPlausibilityScore": None, "severeArtifact": False}
        skipped_reasons.append("materialized_kinematic_metrics_unavailable")
    export_payload: dict[str, Any] | None = None
    try:
        export_payload = json.loads(item.skeleton_path.read_text(encoding="utf-8"))
        orientation_metrics = deterministic_scene_orientation_hint_from_payload(
            export_payload,
            options=item.settings_options,
        )
    except Exception:
        orientation_metrics = {"forceSceneInverted": False}
        skipped_reasons.append("materialized_scene_orientation_metrics_unavailable")
    try:
        phase_metrics = full_repetition_phase_completeness_metrics_from_payload(
            export_payload if export_payload is not None else {},
            exercise_name=item.exercise_name,
            ranking_payload=ranking.payload if isinstance(ranking.payload, dict) else None,
        )
    except Exception:
        phase_metrics = empty_full_repetition_phase_completeness_metrics(
            required=False,
            reason="materialized_phase_completeness_metrics_unavailable",
        )
        skipped_reasons.append("materialized_phase_completeness_metrics_unavailable")
    try:
        target_motion_metrics = materialized_target_motion_observability_metrics_from_payload(
            export_payload if export_payload is not None else {},
            exercise_name=item.exercise_name,
            ranking_payload=ranking.payload if isinstance(ranking.payload, dict) else None,
        )
    except Exception:
        target_motion_metrics = empty_materialized_target_motion_observability_metrics(
            required=False,
            reason="materialized_target_motion_observability_metrics_unavailable",
        )
        skipped_reasons.append("materialized_target_motion_observability_metrics_unavailable")

    motion_score = parse_optional_float(motion_metrics.get("motionStrengthScore"))
    selected_motion_range = parse_optional_float(motion_metrics.get("primaryMotionRangeRatio"))
    readability_score = parse_optional_float(readability_metrics.get("previewReadabilityScore"))
    source_motion_metrics: dict[str, Any] | None = None
    source_phase_metrics: dict[str, Any] | None = None
    source_capture_ratio: float | None = None
    source_range = materialized_source_motion_reference_range(item, ranking)
    if item.source_skeleton_path is not None and item.source_skeleton_path.exists():
        try:
            source_motion_metrics = compute_source_capture_motion_strength_metrics(
                item.source_skeleton_path,
                start_seconds=source_range[0] if source_range is not None else None,
                end_seconds=source_range[1] if source_range is not None else None,
            )
        except Exception:
            source_motion_metrics = None
            skipped_reasons.append("materialized_source_motion_metrics_unavailable")
        try:
            source_phase_metrics = full_repetition_phase_completeness_metrics_from_skeleton_path(
                item.source_skeleton_path,
                exercise_name=item.exercise_name,
                ranking_payload=ranking.payload if isinstance(ranking.payload, dict) else None,
                start_seconds=source_range[0] if source_range is not None else None,
                end_seconds=source_range[1] if source_range is not None else None,
                fallback_to_full=True,
            )
        except Exception:
            source_phase_metrics = None
            skipped_reasons.append("materialized_source_phase_completeness_metrics_unavailable")
    elif item.source_skeleton_path is not None:
        skipped_reasons.append("materialized_source_skeleton_missing")

    source_motion_range = (
        parse_optional_float(source_motion_metrics.get("primaryMotionRangeRatio"))
        if source_motion_metrics is not None
        else None
    )
    if (
        source_motion_range is not None
        and selected_motion_range is not None
        and source_motion_range > 1e-6
    ):
        source_capture_ratio = clamp_unit(selected_motion_range / source_motion_range)
        if (
            source_motion_range >= LOOP_SOURCE_STRONG_MOTION_RATIO_MIN
            and source_capture_ratio < LOOP_SOURCE_MOTION_CAPTURE_RATIO_MIN
        ):
            rejection_reasons.append("materialized_weak_source_motion_capture")

    severe_readability_failure = (
        readability_score is not None
        and readability_score < PREVIEW_READABILITY_LOW_THRESHOLD * 0.60
        and (
            motion_score is None
            or motion_score < BAKED_MOTION_MIN_STRENGTH_SCORE
            or (selected_motion_range is not None and selected_motion_range < BAKED_MOTION_MIN_PRIMARY_RANGE_RATIO)
        )
    )
    if severe_readability_failure:
        rejection_reasons.append("materialized_unreadable_low_motion_preview")

    if bool(kinematic_metrics.get("severeArtifact")):
        metric_reasons = kinematic_metrics.get("artifactReasons")
        if isinstance(metric_reasons, list):
            rejection_reasons.extend(
                str(reason)
                for reason in metric_reasons
                if str(reason) in KINEMATIC_ARTIFACT_REASON_CODES
            )
        if not any(reason in KINEMATIC_ARTIFACT_REASON_CODES for reason in rejection_reasons):
            rejection_reasons.append("materialized_kinematic_artifact")
    if bool(orientation_metrics.get("forceSceneInverted")):
        rejection_reasons.append("materialized_scene_orientation_inverted")
    if (
        bool(phase_metrics.get("required"))
        and not bool(phase_metrics.get("passed", True))
    ):
        rejection_reasons.append("materialized_incomplete_repetition_phase")
    if (
        source_phase_metrics is not None
        and bool(source_phase_metrics.get("required"))
        and not bool(source_phase_metrics.get("passed", True))
    ):
        rejection_reasons.append("materialized_source_incomplete_repetition_phase")
    if (
        bool(target_motion_metrics.get("required"))
        and not bool(target_motion_metrics.get("passed", True))
    ):
        rejection_reasons.append(TARGET_MOTION_MATERIALIZED_REJECTION_REASON)

    payload: dict[str, Any] = {
        "passed": not rejection_reasons,
        "rejectionReasons": dedupe_text(rejection_reasons),
        "skippedReasons": dedupe_text(skipped_reasons),
        "motionStrengthMetrics": motion_metrics,
        "previewReadabilityMetrics": readability_metrics,
        "kinematicPlausibilityMetrics": kinematic_metrics,
        "sceneOrientationMetrics": orientation_metrics,
        "fullRepetitionPhaseCompletenessMetrics": phase_metrics,
        "targetMotionObservabilityMetrics": target_motion_metrics,
        "sourceMotionReferenceRange": (
            {"startSeconds": source_range[0], "endSeconds": source_range[1]}
            if source_range is not None
            else None
        ),
        "sourceMotionCaptureRatio": source_capture_ratio,
        "minSourceMotionCaptureRatio": LOOP_SOURCE_MOTION_CAPTURE_RATIO_MIN,
        "strongSourceMotionRangeRatioMin": LOOP_SOURCE_STRONG_MOTION_RATIO_MIN,
    }
    if source_motion_metrics is not None:
        payload["sourceMotionStrengthMetrics"] = source_motion_metrics
    if source_phase_metrics is not None:
        payload["sourceFullRepetitionPhaseCompletenessMetrics"] = source_phase_metrics
    return payload


def materialized_target_motion_observability_metrics_from_payload(
    payload: dict[str, Any],
    *,
    exercise_name: str,
    ranking_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = target_motion_contract_from_ranking_payload(ranking_payload)
    profile = target_motion_profile_for_exercise(exercise_name, contract=contract)
    observable_spec = observable_motion_spec_for_contract(contract)
    if profile is None and observable_spec is None:
        return empty_materialized_target_motion_observability_metrics(
            required=False,
            reason="no_target_motion_profile",
        )
    frames = motion_frames_from_export_payload(payload)
    if len(frames) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT:
        return {
            "required": True,
            "passed": False,
            "profile": profile.get("profile") if isinstance(profile, dict) else None,
            "target": profile.get("target") if isinstance(profile, dict) else None,
            "observableMotionSpec": observable_spec,
            "failureReasons": ["too_few_skeleton_frames"],
            "frameCount": len(frames),
        }
    profile_key = str(profile.get("profile") or "") if isinstance(profile, dict) else ""
    if profile is not None and profile_key not in {"distal_leg_vertical_raise", "hinged_upper_limb_pull"}:
        return empty_materialized_target_motion_observability_metrics(
            required=False,
            reason="unsupported_target_motion_profile",
            profile=profile,
        )

    body_spans = [body_span_for_frame(frame) for frame in frames]
    body_spans = [value for value in body_spans if value > 1e-6]
    body_span = statistics.median(body_spans) if body_spans else 0.0
    if body_span <= 1e-6:
        return {
            "required": True,
            "passed": False,
            "profile": profile.get("profile") if isinstance(profile, dict) else None,
            "target": profile.get("target") if isinstance(profile, dict) else None,
            "observableMotionSpec": observable_spec,
            "failureReasons": ["invalid_body_span"],
            "frameCount": len(frames),
        }
    if profile is None:
        return materialized_observable_motion_spec_metrics(
            frames,
            spec=observable_spec or {},
            body_span=body_span,
        )
    if profile_key == "hinged_upper_limb_pull":
        return materialized_hinged_upper_limb_pull_observability_metrics(
            frames,
            profile=profile,
            body_span=body_span,
        )

    distal_vertical_range = max(
        representative_joint_y_motion_ratio(frames, names, body_span=body_span) or 0.0
        for names in (
            ("left_foot", "left_ankle"),
            ("right_foot", "right_ankle"),
            ("left_ankle",),
            ("right_ankle",),
        )
    )
    distal_articulation_range = max(
        representative_joint_relative_y_motion_ratio(frames, distal, anchor, body_span=body_span)
        for distal, anchor in (
            (("left_foot",), ("left_ankle",)),
            (("right_foot",), ("right_ankle",)),
            (("left_foot", "left_ankle"), ("left_knee",)),
            (("right_foot", "right_ankle"), ("right_knee",)),
            (("left_ankle",), ("left_knee",)),
            (("right_ankle",), ("right_knee",)),
        )
    )
    proximal_vertical_range = max(
        representative_joint_y_motion_ratio(frames, names, body_span=body_span) or 0.0
        for names in (
            ("left_knee",),
            ("right_knee",),
            ("left_hip",),
            ("right_hip",),
            ("pelvis",),
        )
    )
    motion_metrics = compute_motion_strength_metrics_from_payload(payload, frames_override=frames)
    lower_body_distal_root_relative_range = parse_optional_float(
        motion_metrics.get("lowerBodyDistalRootRelativeRangeRatio")
    ) or 0.0
    upper_body_root_relative_range = parse_optional_float(
        motion_metrics.get("upperBodyRootRelativeRangeRatio")
    ) or 0.0
    dominance_metric_values = {
        "distalVerticalRangeRatio": distal_vertical_range,
        "distalArticulationRangeRatio": distal_articulation_range,
        "proximalVerticalRangeRatio": proximal_vertical_range,
        "lowerBodyDistalRootRelativeRangeRatio": lower_body_distal_root_relative_range,
        "upperBodyRootRelativeRangeRatio": upper_body_root_relative_range,
    }
    target_motion_reference_range = max(
        (
            dominance_metric_values.get(str(metric_key), 0.0)
            for metric_key in profile.get("targetMotionDominanceMetricKeys", [])
        ),
        default=max(distal_vertical_range, distal_articulation_range),
    )
    min_distal_vertical = float(profile["minSkeletonDistalVerticalRangeRatio"])
    min_distal_articulation = float(profile["minSkeletonDistalArticulationRangeRatio"])
    failure_reasons: list[str] = []
    if distal_vertical_range < min_distal_vertical and distal_articulation_range < min_distal_articulation:
        failure_reasons.append("weak_target_distal_motion")
    failure_reasons.extend(
        non_target_motion_dominance_failure_reasons(
            profile,
            dominance_metric_values=dominance_metric_values,
            target_motion_reference_range=target_motion_reference_range,
        )
    )
    return {
        "required": True,
        "passed": not failure_reasons,
        "profile": profile["profile"],
        "target": profile["target"],
        "description": profile["description"],
        "failureReasons": failure_reasons,
        "frameCount": len(frames),
        "bodySpan": body_span,
        "distalVerticalRangeRatio": distal_vertical_range,
        "minDistalVerticalRangeRatio": min_distal_vertical,
        "distalArticulationRangeRatio": distal_articulation_range,
        "minDistalArticulationRangeRatio": min_distal_articulation,
        "proximalVerticalRangeRatio": proximal_vertical_range,
        "lowerBodyDistalRootRelativeRangeRatio": lower_body_distal_root_relative_range,
        "upperBodyRootRelativeRangeRatio": upper_body_root_relative_range,
        "targetMotionReferenceRangeRatio": target_motion_reference_range,
    }


GENERIC_OBSERVABLE_MOTION_MIN_RANGE_RATIO = 0.035
GENERIC_OBSERVABLE_MOTION_MIN_FLEXION_RANGE_RATIO = 0.08
GENERIC_OBSERVABLE_MOTION_REFERENCE_PATTERNS = {
    "body_toward_anchor",
    "body_away_from_anchor",
    "limb_toward_body",
    "limb_away_from_body",
}


def materialized_observable_motion_spec_metrics(
    frames: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    body_span: float,
) -> dict[str, Any]:
    primary_regions = [str(region) for region in spec.get("primaryMovingRegions", [])]
    reference_regions = [str(region) for region in spec.get("referenceRegions", [])]
    axis = str(spec.get("primaryAxis") or "any")
    pattern = str(spec.get("motionPattern") or "other")
    moving_groups = skeleton_joint_groups_for_observable_regions(primary_regions)
    reference_groups = skeleton_joint_groups_for_observable_regions(reference_regions)
    primary_motion_range = max(
        (
            representative_joint_axis_motion_ratio(
                frames,
                group,
                body_span=body_span,
                axis=axis,
            )
            for group in moving_groups
        ),
        default=0.0,
    )
    relative_motion_range = max(
        (
            representative_joint_relative_axis_motion_ratio(
                frames,
                moving_group,
                reference_group,
                body_span=body_span,
                axis=axis,
            )
            for moving_group in moving_groups
            for reference_group in reference_groups
        ),
        default=0.0,
    )
    flexion_range = observable_motion_flexion_range(frames, primary_regions)
    target_motion_range = max(primary_motion_range, relative_motion_range, flexion_range)
    min_motion_range = (
        GENERIC_OBSERVABLE_MOTION_MIN_FLEXION_RANGE_RATIO
        if pattern == "joint_flex_extend" and flexion_range >= primary_motion_range
        else GENERIC_OBSERVABLE_MOTION_MIN_RANGE_RATIO
    )
    failure_reasons: list[str] = []
    if not moving_groups:
        failure_reasons.append("missing_observable_primary_moving_region")
    if pattern in GENERIC_OBSERVABLE_MOTION_REFERENCE_PATTERNS and reference_regions and not reference_groups:
        failure_reasons.append("missing_observable_reference_region")
    if target_motion_range < min_motion_range:
        failure_reasons.append("weak_observable_target_motion")
    return {
        "required": True,
        "passed": not failure_reasons,
        "profile": None,
        "target": "observable_motion_spec",
        "observableMotionSpec": spec,
        "failureReasons": failure_reasons,
        "frameCount": len(frames),
        "bodySpan": body_span,
        "primaryMotionRegions": primary_regions,
        "referenceRegions": reference_regions,
        "primaryAxis": axis,
        "motionPattern": pattern,
        "primaryMotionRangeRatio": primary_motion_range,
        "relativeMotionRangeRatio": relative_motion_range,
        "flexionRangeRatio": flexion_range,
        "targetMotionReferenceRangeRatio": target_motion_range,
        "minTargetMotionRangeRatio": min_motion_range,
    }


def skeleton_joint_groups_for_observable_regions(regions: Iterable[str]) -> list[tuple[str, ...]]:
    groups: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for region in regions:
        for group in skeleton_joint_groups_for_observable_region(str(region)):
            if group not in seen:
                groups.append(group)
                seen.add(group)
    return groups


def skeleton_joint_groups_for_observable_region(region: str) -> list[tuple[str, ...]]:
    if region == "torso":
        return [
            ("spine3", "spine2", "chest", "neck", "left_shoulder", "right_shoulder"),
            ("pelvis", "root", "hips", "left_hip", "right_hip"),
        ]
    if region == "head":
        return [("head", "neck")]
    if region == "shoulders":
        return [("left_shoulder", "right_shoulder")]
    if region == "upper_limb":
        return [
            ("left_hand", "left_wrist", "left_elbow"),
            ("right_hand", "right_wrist", "right_elbow"),
        ]
    if region == "elbows":
        return [("left_elbow",), ("right_elbow",)]
    if region == "hands":
        return [("left_hand", "left_wrist"), ("right_hand", "right_wrist")]
    if region == "hips":
        return [("pelvis", "root", "hips", "left_hip", "right_hip")]
    if region == "lower_limb":
        return [
            ("left_foot", "left_ankle", "left_knee"),
            ("right_foot", "right_ankle", "right_knee"),
        ]
    if region == "knees":
        return [("left_knee",), ("right_knee",)]
    if region == "feet":
        return [("left_foot", "left_ankle"), ("right_foot", "right_ankle")]
    return []


def representative_joint_axis_motion_ratio(
    frames: list[dict[str, Any]],
    names: tuple[str, ...],
    *,
    body_span: float,
    axis: str,
) -> float:
    if axis == "vertical":
        return representative_joint_y_motion_ratio(frames, names, body_span=body_span) or 0.0
    points = representative_joint_points(frames, names)
    if len(points) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT or body_span <= 1e-6:
        return 0.0
    if axis == "horizontal":
        return (max(point[0] for point in points) - min(point[0] for point in points)) / body_span
    if axis == "depth":
        return (max(point[2] for point in points) - min(point[2] for point in points)) / body_span
    return representative_joint_motion_ratio(frames, names, body_span=body_span) or 0.0


def representative_joint_relative_axis_motion_ratio(
    frames: list[dict[str, Any]],
    names: tuple[str, ...],
    anchor_names: tuple[str, ...],
    *,
    body_span: float,
    axis: str,
) -> float:
    if body_span <= 1e-6:
        return 0.0
    values: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        point = representative_joint_center(joints, names)
        anchor = representative_joint_center(joints, anchor_names)
        if point is None or anchor is None:
            continue
        delta = [point[index] - anchor[index] for index in range(3)]
        if axis == "vertical":
            values.append(delta[1])
        elif axis == "horizontal":
            values.append(delta[0])
        elif axis == "depth":
            values.append(delta[2])
        else:
            values.append(vector3_length(delta))
    if len(values) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT:
        return 0.0
    return (max(values) - min(values)) / body_span


def observable_motion_flexion_range(frames: list[dict[str, Any]], regions: list[str]) -> float:
    ranges: list[float] = []
    if any(region in {"upper_limb", "elbows", "hands"} for region in regions):
        ranges.extend(elbow_flexion_range_ratio(frames, side=side) for side in ("left", "right"))
    if any(region in {"lower_limb", "knees", "feet"} for region in regions):
        ranges.extend(knee_flexion_range_ratio(frames, side=side) for side in ("left", "right"))
    return max(ranges, default=0.0)


def materialized_hinged_upper_limb_pull_observability_metrics(
    frames: list[dict[str, Any]],
    *,
    profile: dict[str, Any],
    body_span: float,
) -> dict[str, Any]:
    torso_lean_degrees = torso_lean_degrees_for_frames(frames)
    hand_torso_distance_range = max(
        hand_torso_distance_range_ratio(frames, side=side, body_span=body_span)
        for side in ("left", "right")
    )
    elbow_flexion_range = max(
        elbow_flexion_range_ratio(frames, side=side)
        for side in ("left", "right")
    )
    min_torso_lean_degrees = float(profile["minSkeletonTorsoLeanDegrees"])
    min_hand_torso_distance_range = float(profile["minSkeletonHandTorsoDistanceRangeRatio"])
    min_elbow_flexion_range = float(profile["minSkeletonElbowFlexionRangeRatio"])
    failure_reasons: list[str] = []
    if torso_lean_degrees < min_torso_lean_degrees:
        failure_reasons.append("weak_target_torso_hinge")
    if (
        hand_torso_distance_range < min_hand_torso_distance_range
        and elbow_flexion_range < min_elbow_flexion_range
    ):
        failure_reasons.append("weak_target_upper_limb_pull")
    target_motion_reference_range = max(hand_torso_distance_range, elbow_flexion_range)
    return {
        "required": True,
        "passed": not failure_reasons,
        "profile": profile["profile"],
        "target": profile["target"],
        "description": profile["description"],
        "failureReasons": failure_reasons,
        "frameCount": len(frames),
        "bodySpan": body_span,
        "torsoLeanDegrees": torso_lean_degrees,
        "minTorsoLeanDegrees": min_torso_lean_degrees,
        "handTorsoDistanceRangeRatio": hand_torso_distance_range,
        "minHandTorsoDistanceRangeRatio": min_hand_torso_distance_range,
        "elbowFlexionRangeRatio": elbow_flexion_range,
        "minElbowFlexionRangeRatio": min_elbow_flexion_range,
        "targetMotionReferenceRangeRatio": target_motion_reference_range,
    }


def torso_lean_degrees_for_frames(frames: list[dict[str, Any]]) -> float:
    lean_degrees: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        upper = representative_joint_center(
            joints,
            ("head", "neck", "spine3", "left_shoulder", "right_shoulder"),
        )
        lower = representative_joint_center(
            joints,
            ("pelvis", "root", "hips", "left_hip", "right_hip"),
        )
        if upper is None or lower is None:
            continue
        vector = [upper[axis] - lower[axis] for axis in range(3)]
        length = vector3_length(vector)
        if length <= 1e-6:
            continue
        vertical_cosine = max(-1.0, min(1.0, abs(vector[1]) / length))
        lean_degrees.append(math.degrees(math.acos(vertical_cosine)))
    if len(lean_degrees) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT:
        return 0.0
    return statistics.median(lean_degrees)


def hand_torso_distance_range_ratio(
    frames: list[dict[str, Any]],
    *,
    side: str,
    body_span: float,
) -> float:
    if body_span <= 1e-6:
        return 0.0
    distances: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        torso = representative_joint_center(
            joints,
            ("spine3", "spine2", "chest", "neck", "left_shoulder", "right_shoulder"),
        )
        hand = representative_joint_center(
            joints,
            (f"{side}_hand", f"{side}_wrist"),
        )
        if torso is None or hand is None:
            continue
        distances.append(vector3_length([hand[axis] - torso[axis] for axis in range(3)]))
    if len(distances) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT:
        return 0.0
    return (max(distances) - min(distances)) / body_span


def elbow_flexion_range_ratio(frames: list[dict[str, Any]], *, side: str) -> float:
    angles: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        angle = joint_angle_from_payload(
            joints,
            f"{side}_shoulder",
            f"{side}_elbow",
            f"{side}_wrist",
        )
        if angle is not None:
            angles.append(angle)
    if len(angles) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT:
        return 0.0
    return (max(angles) - min(angles)) / 180.0


def knee_flexion_range_ratio(frames: list[dict[str, Any]], *, side: str) -> float:
    angles: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        angle = joint_angle_from_payload(
            joints,
            f"{side}_hip",
            f"{side}_knee",
            f"{side}_ankle",
        )
        if angle is not None:
            angles.append(angle)
    if len(angles) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT:
        return 0.0
    return (max(angles) - min(angles)) / 180.0



def non_target_motion_dominance_failure_reasons(
    profile: dict[str, Any],
    *,
    dominance_metric_values: dict[str, float],
    target_motion_reference_range: float,
) -> list[str]:
    failures: list[str] = []
    if target_motion_reference_range <= 1e-6:
        return failures
    rules = profile.get("nonTargetMotionDominanceRules")
    if not isinstance(rules, list):
        return failures
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        metric_key = str(rule.get("metricKey") or "")
        if not metric_key:
            continue
        non_target_range = dominance_metric_values.get(metric_key, 0.0)
        min_range = parse_optional_float(rule.get("minRangeRatio")) or 0.0
        max_ratio = parse_optional_float(rule.get("maxRatioToTargetMotion")) or 0.0
        if max_ratio <= 0.0:
            continue
        if non_target_range < min_range:
            continue
        if non_target_range > target_motion_reference_range * max_ratio:
            failures.append(str(rule.get("failureReason") or "non_target_motion_dominates_target_motion"))
    return dedupe_text(failures)


def empty_materialized_target_motion_observability_metrics(
    *,
    required: bool,
    reason: str,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "required": required,
        "passed": True,
        "profile": profile.get("profile") if isinstance(profile, dict) else None,
        "target": profile.get("target") if isinstance(profile, dict) else None,
        "skippedReasons": [reason],
    }


def target_motion_contract_from_ranking_payload(ranking_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(ranking_payload, dict):
        return None
    value = ranking_payload.get("exerciseMotionContract")
    if isinstance(value, dict):
        return value
    return None


def representative_joint_relative_y_motion_ratio(
    frames: list[dict[str, Any]],
    names: tuple[str, ...],
    anchor_names: tuple[str, ...],
    *,
    body_span: float,
) -> float:
    if body_span <= 1e-6:
        return 0.0
    values: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        point = representative_joint_center(joints, names)
        anchor = representative_joint_center(joints, anchor_names)
        if point is None or anchor is None:
            continue
        values.append(point[1] - anchor[1])
    if len(values) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT:
        return 0.0
    return (max(values) - min(values)) / body_span


def materialized_source_motion_reference_range(
    item: ReviewItem,
    ranking: LoopRanking,
) -> tuple[float, float] | None:
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    start = parse_optional_float(payload.get("reviewChunkStartSeconds"))
    end = parse_optional_float(payload.get("reviewChunkEndSeconds"))
    if start is not None and end is not None and end > start:
        return start, end
    return source_capture_time_range_for_item(item)


def full_repetition_phase_completeness_metrics_from_skeleton_path(
    skeleton_path: Path,
    *,
    exercise_name: str,
    ranking_payload: dict[str, Any] | None = None,
    chunk_estimate: Any | None = None,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    fallback_to_full: bool = False,
) -> dict[str, Any]:
    payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    frames_value = payload.get("frames")
    frames = [
        frame
        for frame in frames_value
        if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))
    ] if isinstance(frames_value, list) else []
    phase_reference = "full_source"
    if (
        start_seconds is not None
        and end_seconds is not None
        and end_seconds > start_seconds
        and frames
    ):
        has_source_times = any(parse_optional_float(frame.get("sourceTimeSec")) is not None for frame in frames)
        ranged_frames = frames_in_seconds_range(
            frames,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            use_source_time=has_source_times,
            fps=parse_export_fps(payload),
        )
        if ranged_frames or not fallback_to_full:
            frames = ranged_frames
            phase_reference = "selected_source_time_range"
    scoped_payload = dict(payload)
    scoped_payload["frames"] = frames
    metrics = full_repetition_phase_completeness_metrics_from_payload(
        scoped_payload,
        exercise_name=exercise_name,
        ranking_payload=ranking_payload,
        chunk_estimate=chunk_estimate,
    )
    metrics = dict(metrics)
    metrics["phaseReference"] = phase_reference
    if phase_reference == "selected_source_time_range":
        metrics["phaseStartSeconds"] = start_seconds
        metrics["phaseEndSeconds"] = end_seconds
    return metrics


def full_repetition_phase_completeness_metrics_from_payload(
    payload: dict[str, Any],
    *,
    exercise_name: str,
    ranking_payload: dict[str, Any] | None = None,
    chunk_estimate: Any | None = None,
) -> dict[str, Any]:
    complexity = movement_complexity_for_validation(
        exercise_name,
        ranking_payload=ranking_payload,
        chunk_estimate=chunk_estimate,
    ).strip().lower()
    motion_contract = target_motion_contract_from_ranking_payload(ranking_payload)
    target_motion_profile = target_motion_profile_for_exercise(
        exercise_name,
        contract=motion_contract,
    )
    observable_spec = observable_motion_spec_for_contract(motion_contract)
    required = (
        complexity in {"simple", "compound"}
        or target_motion_profile is not None
        or observable_motion_spec_requires_return(motion_contract)
    )
    if not required:
        return empty_full_repetition_phase_completeness_metrics(
            required=False,
            reason="movement_complexity_does_not_require_repetition_phase_return",
            movement_complexity=complexity,
        )
    frames_value = payload.get("frames")
    joint_names_value = payload.get("jointNames")
    if not isinstance(frames_value, list) or not isinstance(joint_names_value, list):
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="missing_frames_or_joint_names",
            movement_complexity=complexity,
        )
    frames = [
        frame
        for frame in frames_value
        if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))
    ]
    if not frames:
        frames = [frame for frame in frames_value if isinstance(frame, dict)]
    if len(frames) < FULL_REPETITION_PHASE_COMPLETENESS_MIN_FRAMES:
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="insufficient_frames",
            frame_count=len(frames),
            movement_complexity=complexity,
        )
    joint_names = [str(name) for name in joint_names_value]
    root_joint = str(payload.get("rootJoint") or "")
    if root_joint not in joint_names:
        root_joint = next((name for name in ("pelvis", "hips", "root") if name in joint_names), "")
    if not root_joint:
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="missing_root_joint",
            frame_count=len(frames),
            movement_complexity=complexity,
        )

    body_height = body_height_from_payload_frames(frames)
    if body_height <= 1e-6:
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="invalid_body_height",
            frame_count=len(frames),
            movement_complexity=complexity,
        )
    preferred_joint_region = (
        "lower_body"
        if exercise_requires_lower_body_motion(exercise_name, contract=motion_contract)
        else None
    )
    dominant = dominant_root_relative_axis_track(
        frames,
        joint_names=joint_names,
        root_joint=root_joint,
        preferred_joint_predicate=is_lower_body_joint if preferred_joint_region == "lower_body" else None,
    )
    if dominant is None:
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="missing_dominant_motion_track",
            frame_count=len(frames),
            movement_complexity=complexity,
        )
    values = dominant["values"]
    if not isinstance(values, list) or len(values) < FULL_REPETITION_PHASE_COMPLETENESS_MIN_FRAMES:
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="insufficient_dominant_motion_samples",
            frame_count=len(frames),
            movement_complexity=complexity,
        )
    motion_range = float(dominant["range"])
    motion_range_ratio = motion_range / body_height
    if motion_range_ratio < FULL_REPETITION_PHASE_COMPLETENESS_MIN_RANGE_RATIO:
        return {
            "required": True,
            "passed": True,
            "reason": "dominant_motion_too_small_for_phase_gate",
            "movementComplexity": complexity,
            "targetMotionProfile": target_motion_profile.get("profile") if target_motion_profile is not None else None,
            "observableMotionSpec": observable_spec,
            "frameCount": len(frames),
            "sampleCount": len(values),
            "bodyHeight": body_height,
            "dominantJoint": dominant["joint"],
            "dominantJointSelection": dominant.get("selection"),
            "preferredJointRegion": preferred_joint_region,
            "dominantAxis": dominant["axis"],
            "dominantMotionRange": motion_range,
            "dominantMotionRangeRatio": motion_range_ratio,
            "minDominantMotionRangeRatio": FULL_REPETITION_PHASE_COMPLETENESS_MIN_RANGE_RATIO,
        }

    min_value = min(values)
    max_value = max(values)
    min_index = values.index(min_value)
    max_index = values.index(max_value)
    sample_count = len(values)
    edge_margin = max(1, int(round((sample_count - 1) * FULL_REPETITION_PHASE_COMPLETENESS_EDGE_MARGIN_RATIO)))
    interior_min = edge_margin <= min_index <= (sample_count - 1 - edge_margin)
    interior_max = edge_margin <= max_index <= (sample_count - 1 - edge_margin)
    endpoint_delta_ratio = abs(float(values[-1]) - float(values[0])) / max(motion_range, 1e-8)
    has_return_phase = endpoint_delta_ratio <= FULL_REPETITION_PHASE_COMPLETENESS_MAX_ENDPOINT_DELTA_RATIO
    has_interior_extreme = interior_min or interior_max
    passed = has_return_phase and has_interior_extreme
    return {
        "required": True,
        "passed": passed,
        "reason": "full_repetition_phase_return_detected" if passed else "one_way_partial_repetition_phase",
        "movementComplexity": complexity,
        "targetMotionProfile": target_motion_profile.get("profile") if target_motion_profile is not None else None,
        "observableMotionSpec": observable_spec,
        "frameCount": len(frames),
        "sampleCount": sample_count,
        "bodyHeight": body_height,
        "dominantJoint": dominant["joint"],
        "dominantJointSelection": dominant.get("selection"),
        "preferredJointRegion": preferred_joint_region,
        "dominantAxis": dominant["axis"],
        "dominantMotionRange": motion_range,
        "dominantMotionRangeRatio": motion_range_ratio,
        "minDominantMotionRangeRatio": FULL_REPETITION_PHASE_COMPLETENESS_MIN_RANGE_RATIO,
        "startValue": float(values[0]),
        "endValue": float(values[-1]),
        "minValue": float(min_value),
        "maxValue": float(max_value),
        "minFrameIndex": min_index,
        "maxFrameIndex": max_index,
        "edgeMarginFrameCount": edge_margin,
        "endpointPhaseDeltaRatio": endpoint_delta_ratio,
        "maxEndpointPhaseDeltaRatio": FULL_REPETITION_PHASE_COMPLETENESS_MAX_ENDPOINT_DELTA_RATIO,
        "hasReturnPhase": has_return_phase,
        "hasInteriorExtreme": has_interior_extreme,
        "interiorMin": interior_min,
        "interiorMax": interior_max,
    }


def empty_full_repetition_phase_completeness_metrics(
    *,
    required: bool,
    reason: str,
    frame_count: int = 0,
    movement_complexity: str | None = None,
) -> dict[str, Any]:
    return {
        "required": required,
        "passed": True,
        "reason": reason,
        "movementComplexity": movement_complexity,
        "frameCount": frame_count,
    }


def body_height_from_payload_frames(frames: list[dict[str, Any]]) -> float:
    heights: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        points = [point3_to_float_list(point) for point in joints.values() if is_point3(point)]
        if not points:
            continue
        y_values = [point[1] for point in points]
        heights.append(max(y_values) - min(y_values))
    return statistics.median(heights) if heights else 0.0


def dominant_root_relative_axis_track(
    frames: list[dict[str, Any]],
    *,
    joint_names: list[str],
    root_joint: str,
    preferred_joint_predicate: Callable[[str], bool] | None = None,
) -> dict[str, Any] | None:
    excluded = {root_joint, "pelvis", "hips", "root"}
    candidate_joints = [name for name in joint_names if name not in excluded]

    def best_for(joints_to_consider: list[str], *, selection: str) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        for joint_name in joints_to_consider:
            points: list[list[float]] = []
            for frame in frames:
                joints = frame.get("joints")
                if not isinstance(joints, dict):
                    continue
                point = joints.get(joint_name)
                root = joints.get(root_joint)
                if is_point3(point) and is_point3(root):
                    point3 = point3_to_float_list(point)
                    root3 = point3_to_float_list(root)
                    points.append([point3[axis] - root3[axis] for axis in range(3)])
            if len(points) < max(FULL_REPETITION_PHASE_COMPLETENESS_MIN_FRAMES, int(len(frames) * 0.75)):
                continue
            for axis in range(3):
                values = [point[axis] for point in points]
                value_range = max(values) - min(values)
                if best is None or value_range > float(best["range"]):
                    best = {
                        "joint": joint_name,
                        "axis": axis,
                        "range": value_range,
                        "values": values,
                        "selection": selection,
                    }
        return best

    if preferred_joint_predicate is not None:
        preferred_joints = [name for name in candidate_joints if preferred_joint_predicate(name)]
        preferred_best = best_for(preferred_joints, selection="preferred")
        if preferred_best is not None:
            return preferred_best
    return best_for(candidate_joints, selection="fallback_all_joints")


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


def exercise_motion_contract_mentions_lower_body(contract: dict[str, Any] | None) -> bool:
    if not isinstance(contract, dict):
        return False
    if observable_motion_spec_mentions_lower_body(contract):
        return True
    target_motion_profile = target_motion_profile_for_exercise(None, contract=contract)
    target_motion_profile_key = (
        str(target_motion_profile.get("profile"))
        if isinstance(target_motion_profile, dict) and target_motion_profile.get("profile")
        else None
    )
    if target_motion_profile_key == DISTAL_LEG_VERTICAL_RAISE_PROFILE_KEY:
        return True

    def contract_text_segments_for_keys(keys: Iterable[str]) -> list[str]:
        segments: list[str] = []
        for key in keys:
            value = contract.get(key)
            if isinstance(value, str):
                segments.append(value.casefold())
            elif isinstance(value, list):
                segments.extend(str(item).casefold() for item in value)
        return segments

    def text_mentions_lower_body(text: str) -> bool:
        tokens = set(re.findall(r"[a-z0-9]+", text))
        token_terms = {term for term in LOWER_BODY_CONTRACT_TERMS if " " not in term}
        return "lower body" in text or bool(tokens.intersection(token_terms))

    def text_mentions_lower_body_motion(text: str) -> bool:
        tokens = re.findall(r"[a-z0-9]+", text)
        token_terms = {term for term in LOWER_BODY_CONTRACT_TERMS if " " not in term}
        lower_body_indices = [
            index
            for index, token in enumerate(tokens)
            if token in token_terms
        ]
        if "lower body" in text:
            lower_body_indices.extend(
                index
                for index, token in enumerate(tokens)
                if token == "lower"
                and index + 1 < len(tokens)
                and tokens[index + 1] == "body"
            )
        action_indices = [
            index
            for index, token in enumerate(tokens)
            if token in LOWER_BODY_MOTION_ACTION_TERMS
        ]
        return any(
            abs(lower_body_index - action_index) <= LOWER_BODY_MOTION_ACTION_MAX_TOKEN_DISTANCE
            for lower_body_index in lower_body_indices
            for action_index in action_indices
        )

    primary_segments = contract_text_segments_for_keys(LOWER_BODY_MOTION_CONTRACT_PRIMARY_KEYS)
    if any(text_mentions_lower_body(segment) for segment in primary_segments):
        return True

    context_segments = contract_text_segments_for_keys(LOWER_BODY_MOTION_CONTRACT_CONTEXT_KEYS)
    return any(text_mentions_lower_body_motion(segment) for segment in context_segments)


def exercise_requires_lower_body_motion(
    exercise_name: str,
    *,
    contract: dict[str, Any] | None = None,
) -> bool:
    del exercise_name
    return exercise_motion_contract_mentions_lower_body(contract)


def focused_motion_adjustment_for_exercise(
    exercise_name: str,
    motion_metrics: dict[str, Any],
    *,
    base_motion_score: float,
    exercise_motion_contract: dict[str, Any] | None = None,
) -> tuple[float, list[str], dict[str, Any]]:
    if not exercise_requires_lower_body_motion(exercise_name, contract=exercise_motion_contract):
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
            exercise_motion_contract=target_motion_contract_from_ranking_payload(payload),
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
        camera_yaw_degrees=optional_float_or_default(
            item.settings_options.get("cameraYawDegrees"),
            FIXED_PREVIEW_CAMERA_YAW_DEGREES,
        ),
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
        exercise_motion_contract=target_motion_contract_from_ranking_payload(
            ranking.payload if isinstance(ranking.payload, dict) else None
        ),
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
    lower_body_proximal_root_relative_range_ratios: list[float] = []
    lower_body_distal_root_relative_range_ratios: list[float] = []
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
            if is_lower_body_proximal_joint(joint_name):
                lower_body_proximal_root_relative_range_ratios.append(root_relative_range_ratio)
            if is_lower_body_distal_joint(joint_name):
                lower_body_distal_root_relative_range_ratios.append(root_relative_range_ratio)
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
    lower_body_proximal_articulation_range_ratio = max(lower_body_proximal_root_relative_range_ratios, default=0.0)
    lower_body_distal_articulation_range_ratio = max(lower_body_distal_root_relative_range_ratios, default=0.0)
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
        "lowerBodyProximalRootRelativeRangeRatio": lower_body_proximal_articulation_range_ratio,
        "lowerBodyDistalRootRelativeRangeRatio": lower_body_distal_articulation_range_ratio,
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
        "lowerBodyProximalRootRelativeRangeRatio": 0.0,
        "lowerBodyDistalRootRelativeRangeRatio": 0.0,
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


def is_lower_body_proximal_joint(joint_name: str) -> bool:
    return any(
        token in joint_name
        for token in ("hip", "knee")
    )


def is_lower_body_distal_joint(joint_name: str) -> bool:
    return any(
        token in joint_name
        for token in ("ankle", "foot", "toe", "heel")
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
        "cameraYawDegrees": FIXED_PREVIEW_CAMERA_YAW_DEGREES,
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
            camera_yaw_degrees=optional_float_or_default(
                item.settings_options.get("cameraYawDegrees"),
                FIXED_PREVIEW_CAMERA_YAW_DEGREES,
            ),
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


def callable_accepts_keyword(callback: Callable[..., Any], keyword: str) -> bool:
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == keyword:
            return True
    return False


def call_caption_images_json(
    caption_images: Callable[..., str],
    *,
    frame_paths: list[Path],
    prompt: str,
    max_tokens: int | None = None,
    request_timeout_seconds: float | None = None,
    disable_reasoning: bool | None = None,
    json_response: bool | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
) -> str:
    kwargs: dict[str, Any] = {
        "frame_paths": frame_paths,
        "prompt": prompt,
    }
    if max_tokens is not None and callable_accepts_keyword(caption_images, "max_tokens"):
        kwargs["max_tokens"] = max(1, int(max_tokens))
    if (
        request_timeout_seconds is not None
        and callable_accepts_keyword(caption_images, "request_timeout_seconds")
    ):
        requested_timeout = float(request_timeout_seconds)
        kwargs["request_timeout_seconds"] = (
            0.0 if requested_timeout <= 0.0 else max(1.0, requested_timeout)
        )
    if disable_reasoning is not None and callable_accepts_keyword(caption_images, "disable_reasoning"):
        kwargs["disable_reasoning"] = bool(disable_reasoning)
    if json_response is not None and callable_accepts_keyword(caption_images, "json_response"):
        kwargs["json_response"] = bool(json_response)
    if temperature is not None and callable_accepts_keyword(caption_images, "temperature"):
        kwargs["temperature"] = max(0.0, float(temperature))
    if top_p is not None and callable_accepts_keyword(caption_images, "top_p"):
        kwargs["top_p"] = max(0.0, min(1.0, float(top_p)))
    if top_k is not None and callable_accepts_keyword(caption_images, "top_k"):
        kwargs["top_k"] = max(0, int(top_k))
    return caption_images(**kwargs)


def build_exercise_motion_contract_resolver(
    *,
    request: BakeAndRankRequest,
    caption_images: Callable[..., str] | None,
) -> ExerciseMotionContractResolver | None:
    if not request.pre_wham_source_validation or not request.exercise_motion_contract_enabled:
        return None
    cache: dict[str, dict[str, Any] | None] = {}
    cache_lock = threading.Lock()

    def resolve(ranked_candidate: RankedCandidate) -> dict[str, Any] | None:
        candidate_contract = exercise_motion_contract_from_candidate(ranked_candidate.candidate)
        if candidate_contract is not None:
            return {
                **candidate_contract,
                "exerciseMotionContractStatus": "reused_candidate_contract",
            }
        if caption_images is None:
            return None
        key = normalize_exercise_name(ranked_candidate.exercise_name)
        with cache_lock:
            if key not in cache:
                cache[key] = generate_exercise_motion_contract_for_bake(
                    ranked_candidate=ranked_candidate,
                    request=request,
                    caption_images=caption_images,
                )
            return cache[key]

    return resolve


def build_exercise_skeleton_contract_resolver(
    *,
    request: BakeAndRankRequest,
    caption_images: Callable[..., str] | None,
) -> ExerciseSkeletonContractResolver | None:
    if not request.exercise_motion_contract_enabled:
        return None
    cache: dict[str, dict[str, Any] | None] = {}
    cache_lock = threading.Lock()

    def resolve(ranked_candidate: RankedCandidate) -> dict[str, Any] | None:
        candidate_contract = exercise_skeleton_contract_from_candidate(ranked_candidate.candidate)
        if candidate_contract is not None:
            return {
                **candidate_contract,
                "exerciseSkeletonContractStatus": "reused_candidate_contract",
            }
        if caption_images is None:
            return None
        key = normalize_exercise_name(ranked_candidate.exercise_name)
        with cache_lock:
            if key not in cache:
                cache[key] = generate_exercise_skeleton_contract_for_bake(
                    ranked_candidate=ranked_candidate,
                    request=request,
                    caption_images=caption_images,
                )
            return cache[key]

    return resolve


def generate_exercise_motion_contract_for_bake(
    *,
    ranked_candidate: RankedCandidate,
    request: BakeAndRankRequest,
    caption_images: Callable[..., str],
) -> dict[str, Any]:
    exercise = ExerciseEntry(
        exercise_id=ranked_candidate.exercise_id,
        name=ranked_candidate.exercise_name,
        slug=ranked_candidate.exercise_slug,
    )
    started = time.perf_counter()
    try:
        raw = call_caption_images_json(
            caption_images,
            frame_paths=[],
            prompt=build_exercise_motion_contract_prompt(exercise),
            max_tokens=EXERCISE_MOTION_CONTRACT_MAX_TOKENS,
            request_timeout_seconds=min(
                EXERCISE_MOTION_CONTRACT_TIMEOUT_SECONDS,
                max(1.0, float(request.llama_cpp_request_timeout_seconds)),
            ),
            disable_reasoning=True,
            json_response=False,
        )
        contract = normalize_exercise_motion_contract_text(raw, exercise=exercise, source="bake_and_rank_llm")
        contract["model"] = request.llama_cpp_model
        contract["generationElapsedSeconds"] = elapsed_seconds(started)
        contract["exerciseMotionContractStatus"] = "generated_on_demand"
        return contract
    except Exception as exc:
        return {
            "schemaVersion": 1,
            "enabled": True,
            "status": "failed",
            "source": "bake_and_rank_llm",
            "exerciseName": ranked_candidate.exercise_name,
            "model": request.llama_cpp_model,
            "error": str(exc)[:240],
            "generationElapsedSeconds": elapsed_seconds(started),
            "exerciseMotionContractStatus": "generation_failed",
        }


def generate_exercise_skeleton_contract_for_bake(
    *,
    ranked_candidate: RankedCandidate,
    request: BakeAndRankRequest,
    caption_images: Callable[..., str],
) -> dict[str, Any]:
    exercise = ExerciseEntry(
        exercise_id=ranked_candidate.exercise_id,
        name=ranked_candidate.exercise_name,
        slug=ranked_candidate.exercise_slug,
    )
    started = time.perf_counter()
    try:
        raw = call_caption_images_json(
            caption_images,
            frame_paths=[],
            prompt=build_exercise_skeleton_contract_prompt(exercise),
            max_tokens=EXERCISE_MOTION_CONTRACT_MAX_TOKENS,
            request_timeout_seconds=min(
                EXERCISE_MOTION_CONTRACT_TIMEOUT_SECONDS,
                max(1.0, float(request.llama_cpp_request_timeout_seconds)),
            ),
            disable_reasoning=True,
            json_response=False,
        )
        contract = normalize_exercise_skeleton_contract_text(raw, exercise=exercise, source="bake_and_rank_llm")
        contract["model"] = request.llama_cpp_model
        contract["generationElapsedSeconds"] = elapsed_seconds(started)
        contract["exerciseSkeletonContractStatus"] = "generated_on_demand"
        return contract
    except Exception as exc:
        return {
            "schemaVersion": 1,
            "enabled": True,
            "status": "failed",
            "source": "bake_and_rank_llm",
            "exerciseName": ranked_candidate.exercise_name,
            "model": request.llama_cpp_model,
            "error": str(exc)[:240],
            "generationElapsedSeconds": elapsed_seconds(started),
            "exerciseSkeletonContractStatus": "generation_failed",
        }


def generate_exercise_skeleton_contract_for_review_item(
    item: ReviewItem,
    *,
    request: BakeAndRankRequest,
    caption_images: Callable[..., str],
) -> dict[str, Any]:
    ranked_candidate = RankedCandidate(
        exercise_index=item.exercise_index,
        candidate_rank=item.candidate_rank,
        exercise_id=str(item.candidate.get("exerciseId") or item.candidate.get("exercise_id") or item.exercise_name),
        exercise_name=item.exercise_name,
        exercise_slug=str(item.candidate.get("exerciseSlug") or item.candidate.get("exercise_slug") or slugify(item.exercise_name)),
        candidate=item.candidate,
    )
    return generate_exercise_skeleton_contract_for_bake(
        ranked_candidate=ranked_candidate,
        request=request,
        caption_images=caption_images,
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
        "maxSourceWindowAttempts": request.max_source_window_attempts,
        "maxSelectedResults": max_selected_results_for_request(request),
        "readyCandidateTarget": ready_candidate_target_for_request(request),
        "rankPreviewVariants": request.rank_preview_variants,
        "adaptivePreviewSettings": request.adaptive_preview_settings,
        "classifySupportDominance": request.classify_support_dominance,
        "whamRunSmplify": request.wham_run_smplify,
        "whamEstimateLocalOnly": request.wham_estimate_local_only,
        "useWhamDocker": request.use_wham_docker,
        "useWarmWhamWorker": request.use_warm_wham_worker,
        "whamWorkerSessionDir": str(request.wham_worker_session_dir) if request.wham_worker_session_dir is not None else None,
        "whamWorkerMountRoot": str(request.wham_worker_mount_root) if request.wham_worker_mount_root is not None else None,
        "whamTimeoutSeconds": request.wham_timeout_seconds,
    }
    candidates = load_ranked_candidates_manifest(
        request.candidates_json,
        include_fallback_candidates=True,
    )
    request.workspace.mkdir(parents=True, exist_ok=True)
    original_candidate_count = len(candidates)
    pipeline_timings["primaryCandidateCount"] = sum(
        1
        for candidate in candidates
        if parse_optional_bool(candidate.candidate.get("bakeFallbackCandidate")) is not True
    )
    pipeline_timings["fallbackBakeCandidateCount"] = sum(
        1
        for candidate in candidates
        if parse_optional_bool(candidate.candidate.get("bakeFallbackCandidate")) is True
    )
    candidates = expand_ranked_candidates_for_source_windows(candidates, request=request)
    pipeline_timings["sourceVideoCandidateCount"] = original_candidate_count
    pipeline_timings["sourceWindowCandidateCount"] = len(candidates)
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
            or request.final_output_validation
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
        rankings: list[LoopRanking] = []
        selected: SelectedArtifact | None = None
        selected_results: list[SelectedArtifact] = []
        rejected_best: SelectedArtifact | None = None
        source_cut_caption_images = (
            vision_ranker.client.caption_images
            if request.pre_wham_source_validation and vision_ranker is not None
            else None
        )
        final_output_caption_images = (
            vision_ranker.client.caption_images
            if request.final_output_validation and vision_ranker is not None
            else None
        )
        exercise_motion_contract_resolver = build_exercise_motion_contract_resolver(
            request=request,
            caption_images=source_cut_caption_images,
        )
        exercise_skeleton_contract_resolver = build_exercise_skeleton_contract_resolver(
            request=request,
            caption_images=vision_ranker.client.caption_images if vision_ranker is not None else None,
        )
        candidate_processing_started = time.perf_counter()
        if request.candidate_workers <= 1:
            (
                candidate_results,
                review_items,
                review_item_entries,
                rankings,
                selected,
                selected_results,
                rejected_best,
                selection_attempts,
                incremental_timings,
            ) = process_ranked_candidates_until_final_selection(
                candidates,
                request=request,
                preview_baker=preview_baker,
                effective_ranker=effective_ranker,
                support_dominance_classifier=support_dominance_classifier,
                source_cut_caption_images=source_cut_caption_images,
                exercise_motion_contract_resolver=exercise_motion_contract_resolver,
                exercise_skeleton_contract_resolver=exercise_skeleton_contract_resolver,
                final_output_caption_images=final_output_caption_images,
            )
            pipeline_timings["candidateSelectionMode"] = "incremental_queue_until_final_selection"
            pipeline_timings["candidateSelectionAttempts"] = selection_attempts
            pipeline_timings.update(incremental_timings)
        else:
            candidate_results, review_items, review_item_entries = process_ranked_candidates_for_selection(
                candidates,
                request=request,
                preview_baker=preview_baker,
                support_dominance_classifier=support_dominance_classifier,
                source_cut_caption_images=source_cut_caption_images,
                exercise_motion_contract_resolver=exercise_motion_contract_resolver,
                exercise_skeleton_contract_resolver=exercise_skeleton_contract_resolver,
            )
            pipeline_timings["candidateSelectionMode"] = "parallel_ready_candidate_batch_then_selection"
            if review_items:
                if effective_ranker is None:
                    rankings = [LoopRanking(score=1.0, reasons=["ranking_skipped"]) for _ in review_items]
                    selected = (review_items[0], None)
                else:
                    stage_started = time.perf_counter()
                    rankings = effective_ranker(review_items, request)
                    pipeline_timings["reviewRankingSeconds"] = elapsed_seconds(stage_started)
                stage_started = time.perf_counter()
                if max_selected_results_for_request(request) > 1:
                    choose_kwargs: dict[str, Any] = {"request": request}
                    if final_output_caption_images is not None:
                        choose_kwargs["final_output_caption_images"] = final_output_caption_images
                    selected_results, rejected_best = choose_top_materialized_review_items(
                        review_items,
                        rankings,
                        **choose_kwargs,
                    )
                    selected = selected_results[0] if selected_results else None
                else:
                    choose_kwargs = {"request": request}
                    if final_output_caption_images is not None:
                        choose_kwargs["final_output_caption_images"] = final_output_caption_images
                    selected, rejected_best = choose_best_materialized_review_item(
                        review_items,
                        rankings,
                        **choose_kwargs,
                    )
                    selected_results = [selected] if selected is not None else []
                pipeline_timings["selectionMaterializationSeconds"] = elapsed_seconds(stage_started)
                mark_parallel_candidate_final_selection_statuses(
                    candidate_results,
                    review_items,
                    selected=selected,
                    selected_results=selected_results,
                    rejected_best=rejected_best,
                )
        pipeline_timings["candidateProcessingSeconds"] = elapsed_seconds(candidate_processing_started)
        pipeline_timings["processedCandidateCount"] = len(candidate_results)
        pipeline_timings["readyCandidateCount"] = sum(
            1 for item in candidate_results if item.get("status") == "ready_for_selection"
        )
        pipeline_timings["reviewItemCount"] = len(review_items)
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
    selected_preview_paths = write_selected_result_preview_htmls(request.workspace, selected_results)

    selection_manifest = build_selection_manifest(
        request=request,
        candidate_results=candidate_results,
        review_entries=ranked_review_entries,
        selected=selected,
        selected_results=selected_results,
        rejected_best=rejected_best,
    )
    pipeline_timings["manifestBuildSeconds"] = elapsed_seconds(manifest_started)
    pipeline_timings["totalSeconds"] = elapsed_seconds(pipeline_started)
    selection_manifest["timings"] = pipeline_timings
    attach_selected_preview_paths_to_manifest(selection_manifest, selected_preview_paths)
    selection_path = request.workspace / "selection_manifest.json"
    selection_path.write_text(json.dumps(selection_manifest, indent=2), encoding="utf-8")
    retention_started = time.perf_counter()
    try:
        retention_summary = apply_artifact_retention_policy(
            request.workspace,
            selection_manifest,
            mode=request.artifact_retention,
        )
    except Exception as exc:  # pragma: no cover - best-effort final cleanup must not fail selection.
        retention_summary = {
            "mode": request.artifact_retention,
            "pruned": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    pipeline_timings["artifactRetentionSeconds"] = elapsed_seconds(retention_started)
    selection_manifest["timings"] = pipeline_timings
    selection_manifest["artifactRetention"] = retention_summary
    selection_path.write_text(json.dumps(selection_manifest, indent=2), encoding="utf-8")
    return selection_manifest


def mark_parallel_candidate_final_selection_statuses(
    candidate_results: list[dict[str, Any]],
    review_items: list[ReviewItem],
    *,
    selected: SelectedArtifact | None,
    selected_results: list[SelectedArtifact] | None = None,
    rejected_best: SelectedArtifact | None,
) -> None:
    review_attempt_keys = {review_item_attempt_key(item) for item in review_items}
    active_selected_results = selected_results if selected_results is not None else ([selected] if selected is not None else [])
    selected_key_by_attempt = {
        review_item_attempt_key(selected_item[0]): index
        for index, selected_item in enumerate(active_selected_results)
    }
    rejected_best_key = review_item_attempt_key(rejected_best[0]) if rejected_best is not None else None
    for result in candidate_results:
        if result.get("status") == "skipped_previous_terminal_result":
            continue
        attempt_key = candidate_result_attempt_key(result)
        if attempt_key is None:
            continue
        selected_index = selected_key_by_attempt.get(attempt_key)
        if selected_index is not None:
            selected_artifact = active_selected_results[selected_index]
            result["finalSelectionStatus"] = "selected" if selected_index == 0 else "selected_alternative"
            result["finalSelectionScore"] = selected_artifact_score(selected_artifact)
            result["selectedResultIndex"] = selected_index
            continue
        if not selected_key_by_attempt and attempt_key in review_attempt_keys:
            result["finalSelectionStatus"] = "rejected_after_materialized_review"
            if rejected_best_key == attempt_key and rejected_best is not None:
                result["finalRejectedBestScore"] = selected_artifact_score(rejected_best)
            continue
        if result.get("status") == "ready_for_selection" and attempt_key not in review_attempt_keys:
            result["finalSelectionStatus"] = "not_reviewable"


def candidate_result_segment_selection_manifest(result: dict[str, Any]) -> dict[str, Any] | None:
    workspace_value = result.get("candidateWorkspace")
    if not workspace_value:
        return None
    path = Path(str(workspace_value)) / "segment_detection" / "segment_selection.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def candidate_result_used_pre_wham_child_source_cut(result: dict[str, Any]) -> bool:
    payload = candidate_result_segment_selection_manifest(result)
    if not isinstance(payload, dict):
        return False
    if str(payload.get("sourcePrepReason") or "") != "pre_wham_source_window_choice":
        return False
    parent_payload = payload.get("candidateSourceWindow")
    selected_payload = payload.get("selectedSpan")
    if not isinstance(parent_payload, dict) or not isinstance(selected_payload, dict):
        return False
    parent_start = parse_optional_float(parent_payload.get("startSeconds"))
    parent_end = parse_optional_float(parent_payload.get("endSeconds"))
    selected_start = parse_optional_float(selected_payload.get("startSeconds"))
    selected_end = parse_optional_float(selected_payload.get("endSeconds"))
    if (
        parent_start is None
        or parent_end is None
        or selected_start is None
        or selected_end is None
        or parent_end <= parent_start
        or selected_end <= selected_start
    ):
        return False
    return selected_window_is_materially_shorter(
        parent_window=DetectionWindow(index=0, start_seconds=parent_start, end_seconds=parent_end),
        child_window=DetectionWindow(index=0, start_seconds=selected_start, end_seconds=selected_end),
    )


def materialized_rejection_reason_tags(rejected: SelectedArtifact | None) -> list[str]:
    if rejected is None:
        return []
    _item, ranking = rejected
    if ranking is None:
        return []
    reasons = [str(reason) for reason in ranking.reasons if str(reason)]
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    materialized_reasons = payload.get("materializedOutputRejectionReasons")
    if isinstance(materialized_reasons, list):
        reasons.extend(str(reason) for reason in materialized_reasons if str(reason))
    final_validation = payload.get("finalOutputValidation")
    if isinstance(final_validation, dict):
        final_reasons = final_validation.get("rejectionReasons")
        if isinstance(final_reasons, list):
            reasons.extend(str(reason) for reason in final_reasons if str(reason))
        if parse_optional_bool(final_validation.get("needsRetry")) is True:
            reasons.append("final_output_needs_retry")
    return dedupe_text(reasons)


def should_queue_parent_source_window_fallback(
    ranked_candidate: RankedCandidate,
    result: dict[str, Any],
    rejected: SelectedArtifact | None,
) -> tuple[bool, str | None]:
    if ranked_candidate.source_chunk_hint is None:
        return False, None
    if parse_optional_bool(ranked_candidate.candidate.get("sourceWindowParentFallback")) is True:
        return False, None
    if not candidate_result_used_pre_wham_child_source_cut(result):
        return False, None
    rejection_reasons = materialized_rejection_reason_tags(rejected)
    for reason in rejection_reasons:
        if reason in PARENT_SOURCE_WINDOW_FALLBACK_REJECTION_REASONS:
            return True, reason
    return False, None


def run_bake_and_rank_reselection(
    *,
    workspace: Path,
    min_selected_score: float | None = None,
    review_frames: int | None = None,
    max_review_windows: int | None = None,
    max_selected_results: int | None = None,
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
        max_selected_results=max_selected_results,
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
    selected_results = choose_top_review_items(
        review_items,
        adjusted_rankings,
        min_score=request.min_selected_score,
        max_results=max_selected_results_for_request(request),
    )
    selected = selected_results[0] if selected_results else None
    rejected_best = None
    if selected is None:
        rejected_best = choose_best_review_item(
            review_items,
            adjusted_rankings,
            min_score=0.0,
        )
    write_candidate_ranking_manifests(ranked_review_entries)
    selected_preview_paths = write_selected_result_preview_htmls(workspace, selected_results)
    reselection_manifest = build_selection_manifest(
        request=request,
        candidate_results=existing_manifest.get("candidateResults") if isinstance(existing_manifest.get("candidateResults"), list) else [],
        review_entries=ranked_review_entries,
        selected=selected,
        selected_results=selected_results,
        rejected_best=rejected_best,
    )
    reselection_manifest["reselectedFromManifest"] = str(selection_path)
    reselection_manifest["previousGeneratedAt"] = existing_manifest.get("generatedAt")
    attach_selected_preview_paths_to_manifest(reselection_manifest, selected_preview_paths)
    selection_path.write_text(json.dumps(reselection_manifest, indent=2), encoding="utf-8")
    return reselection_manifest


def bake_and_rank_request_from_selection_manifest(
    manifest: dict[str, Any],
    *,
    workspace: Path,
    min_selected_score: float | None,
    review_frames: int | None,
    max_review_windows: int | None,
    max_selected_results: int | None = None,
) -> BakeAndRankRequest:
    source_candidates = manifest.get("sourceCandidatesJson")
    candidates_json = Path(str(source_candidates)) if source_candidates else workspace / "youtube_candidates.json"
    manifest_max_source_window_attempts = parse_optional_int(manifest.get("maxSourceWindowAttempts"))
    return BakeAndRankRequest(
        candidates_json=candidates_json,
        workspace=workspace,
        wham_repo_path=None,
        body_model_root=None,
        youtube_preview_cache_dir=(
            Path(str(manifest["youtubePreviewCacheReadThroughDir"]))
            if manifest.get("youtubePreviewCacheReadThroughDir")
            else None
        ),
        review_frames=review_frames if review_frames is not None else DEFAULT_REVIEW_FRAMES,
        max_review_windows=max_review_windows
        if max_review_windows is not None
        else int(manifest.get("maxReviewWindows") or DEFAULT_MAX_REVIEW_WINDOWS),
        exercise_motion_contract_enabled=bool(
            manifest.get("exerciseMotionContractEnabled", True)
        ),
        max_loop_seconds=float(manifest.get("maxLoopSeconds") or DEFAULT_MAX_LOOP_SECONDS),
        max_source_window_attempts=(
            max(0, manifest_max_source_window_attempts)
            if manifest_max_source_window_attempts is not None
            else DEFAULT_MAX_SOURCE_WINDOW_ATTEMPTS
        ),
        min_selected_score=min_selected_score
        if min_selected_score is not None
        else float(manifest.get("minSelectedScore") or DEFAULT_MIN_SELECTED_SCORE),
        max_selected_results=max_selected_results
        if max_selected_results is not None
        else int(manifest.get("maxSelectedResults") or 1),
        motion_tuning_enabled=bool(manifest.get("motionTuningEnabled", True)),
        rank_preview_variants=bool(manifest.get("previewSettingsVariantRankingEnabled", True)),
        adaptive_preview_settings=bool(manifest.get("adaptivePreviewSettingsEnabled", False)),
        max_adaptive_preview_settings=int(manifest.get("maxAdaptivePreviewSettings") or 3),
        classify_support_dominance=False,
        final_output_validation=bool(manifest.get("finalOutputValidationEnabled", False)),
        final_output_validation_min_score=float(
            manifest.get("finalOutputValidationMinScore")
            or DEFAULT_FINAL_OUTPUT_VALIDATION_MIN_SCORE
        ),
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


def write_selected_result_preview_htmls(
    workspace: Path,
    selected_results: list[SelectedArtifact],
) -> list[Path]:
    preview_paths: list[Path] = []
    for index, selected in enumerate(selected_results):
        filename = "selected_section_preview.html" if index == 0 else f"selected_section_preview_{index + 1:02d}.html"
        preview_path = write_selected_section_preview_html(
            workspace,
            selected,
            filename=filename,
        )
        if preview_path is not None:
            preview_paths.append(preview_path)
    return preview_paths


def attach_selected_preview_paths_to_manifest(
    manifest: dict[str, Any],
    preview_paths: list[Path],
) -> None:
    if not preview_paths:
        return
    manifest["selectedPreviewHtmlPath"] = str(preview_paths[0])
    selected = manifest.get("selected")
    if isinstance(selected, dict):
        selected["selectedResultIndex"] = 0
        selected["manualSelectionLabel"] = "Option 1"
        selected["selectedPreviewHtmlPath"] = str(preview_paths[0])
    selected_results = manifest.get("selectedResults")
    if isinstance(selected_results, list):
        for index, preview_path in enumerate(preview_paths):
            if index >= len(selected_results) or not isinstance(selected_results[index], dict):
                continue
            selected_results[index]["selectedPreviewHtmlPath"] = str(preview_path)


def write_selected_section_preview_html(
    workspace: Path,
    selected: SelectedArtifact | None,
    *,
    filename: str = "selected_section_preview.html",
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
    preview_path = workspace / filename
    video_rel = relative_html_path(item.review_video_path, workspace)
    fallback_mp4 = item.review_video_path.with_suffix(".mp4")
    fallback_rel = relative_html_path(fallback_mp4, workspace) if fallback_mp4 != item.review_video_path else None
    interactive_rel = relative_html_path(item.candidate_workspace / "preview" / "motion_preview.html", workspace)
    interactive_query = urlencode(
        {
            "startSeconds": f"{item.loop_start_seconds:.6f}",
            "endSeconds": f"{item.loop_end_seconds:.6f}",
            "options": json.dumps(
                with_fixed_preview_camera_options(item.settings_options),
                separators=(",", ":"),
            ),
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


def normalize_artifact_retention_mode(mode: str | None) -> str:
    normalized = (mode or ARTIFACT_RETENTION_DEBUG).strip().lower()
    if normalized == "compact":
        normalized = ARTIFACT_RETENTION_DEBUG
    if normalized not in ARTIFACT_RETENTION_MODES:
        raise ValueError(
            f"Unsupported artifact retention mode {mode!r}; expected one of "
            f"{', '.join(sorted(ARTIFACT_RETENTION_MODES))}."
        )
    return normalized


def apply_artifact_retention_policy(
    workspace: Path,
    manifest: dict[str, Any],
    *,
    mode: str | None = ARTIFACT_RETENTION_DEBUG,
) -> dict[str, Any]:
    retention_mode = normalize_artifact_retention_mode(mode)
    summary: dict[str, Any] = {
        "mode": retention_mode,
        "pruned": retention_mode == ARTIFACT_RETENTION_DEBUG,
        "policy": (
            "keep_manifests_selected_input_selected_review_wear_json_preview_html_contact_sheets"
            if retention_mode == ARTIFACT_RETENTION_DEBUG
            else "keep_all_artifacts"
        ),
        "removedDirectoryCount": 0,
        "removedFileCount": 0,
        "removedBytes": 0,
        "removedPathSamples": [],
        "skippedProtectedPathSamples": [],
        "errors": [],
    }
    if retention_mode == ARTIFACT_RETENTION_FULL:
        return summary

    workspace = Path(workspace)
    if not workspace.exists():
        summary["errors"].append(f"workspace_not_found:{workspace}")
        return summary
    workspace_resolved = workspace.resolve()
    protected_paths = collect_artifact_retention_protected_paths(workspace, manifest)

    def add_sample(key: str, path: Path) -> None:
        samples = summary[key]
        if len(samples) < ARTIFACT_RETENTION_SAMPLE_LIMIT:
            samples.append(relative_path_for_manifest(path, workspace))

    def add_error(message: str) -> None:
        errors = summary["errors"]
        if len(errors) < ARTIFACT_RETENTION_SAMPLE_LIMIT:
            errors.append(message)

    directories = [
        path
        for path in workspace.rglob("*")
        if path.is_dir() and path.name in ARTIFACT_RETENTION_PRUNE_DIR_NAMES
    ]
    directories.sort(key=lambda path: len(path.parts), reverse=True)
    for directory in directories:
        if not directory.exists():
            continue
        try:
            directory_resolved = directory.resolve()
            if not path_is_relative_to(directory_resolved, workspace_resolved):
                add_error(f"skip_outside_workspace:{directory}")
                continue
            if any(path_is_relative_to(protected, directory_resolved) for protected in protected_paths):
                add_sample("skippedProtectedPathSamples", directory)
                continue
            removed_bytes = directory_size_bytes(directory)
            shutil.rmtree(directory)
            summary["removedDirectoryCount"] += 1
            summary["removedBytes"] += removed_bytes
            add_sample("removedPathSamples", directory)
        except Exception as exc:  # pragma: no cover - deletion failures are environment-specific.
            add_error(f"{relative_path_for_manifest(directory, workspace)}:{type(exc).__name__}:{exc}")

    for pattern in ARTIFACT_RETENTION_PRUNE_FILE_PATTERNS:
        for file_path in workspace.rglob(pattern):
            if not file_path.is_file():
                continue
            try:
                file_resolved = file_path.resolve()
                if not path_is_relative_to(file_resolved, workspace_resolved):
                    add_error(f"skip_outside_workspace:{file_path}")
                    continue
                if file_resolved in protected_paths:
                    add_sample("skippedProtectedPathSamples", file_path)
                    continue
                removed_bytes = file_path.stat().st_size
                file_path.unlink()
                summary["removedFileCount"] += 1
                summary["removedBytes"] += removed_bytes
                add_sample("removedPathSamples", file_path)
            except Exception as exc:  # pragma: no cover - deletion failures are environment-specific.
                add_error(f"{relative_path_for_manifest(file_path, workspace)}:{type(exc).__name__}:{exc}")

    return summary


def collect_artifact_retention_protected_paths(workspace: Path, manifest: dict[str, Any]) -> set[Path]:
    protected: set[Path] = set()
    for value in iter_manifest_artifact_paths(manifest):
        path = resolve_manifest_artifact_path(workspace, str(value))
        try:
            if path.exists():
                protected.add(path.resolve())
        except OSError:
            continue
    selection_manifest_path = workspace / "selection_manifest.json"
    if selection_manifest_path.exists():
        protected.add(selection_manifest_path.resolve())
    return protected


def resolve_manifest_artifact_path(workspace: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return workspace / path


def iter_manifest_artifact_paths(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and key in ARTIFACT_RETENTION_PROTECTED_PATH_KEYS:
                yield child
            elif isinstance(child, list) and key in ARTIFACT_RETENTION_PROTECTED_PATH_KEYS:
                for item in child:
                    if isinstance(item, str):
                        yield item
            else:
                yield from iter_manifest_artifact_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_manifest_artifact_paths(child)


def path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def directory_size_bytes(path: Path) -> int:
    total = 0
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            total += file_path.stat().st_size
        except OSError:
            continue
    return total


def relative_path_for_manifest(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


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


def process_ranked_candidates_until_final_selection(
    candidates: list[RankedCandidate],
    *,
    request: BakeAndRankRequest,
    preview_baker: PreviewBaker,
    effective_ranker: LoopRanker | None,
    support_dominance_classifier: Callable[[list[Path], str], str] | None,
    source_cut_caption_images: Callable[..., str] | None = None,
    exercise_motion_contract_resolver: ExerciseMotionContractResolver | None = None,
    exercise_skeleton_contract_resolver: ExerciseSkeletonContractResolver | None = None,
    final_output_caption_images: Callable[..., str] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[ReviewItem],
    list[dict[str, Any]],
    list[LoopRanking],
    SelectedArtifact | None,
    list[SelectedArtifact],
    SelectedArtifact | None,
    list[dict[str, Any]],
    dict[str, Any],
]:
    candidate_results: list[dict[str, Any]] = []
    review_items: list[ReviewItem] = []
    review_item_entries: list[dict[str, Any]] = []
    rankings: list[LoopRanking] = []
    selection_attempts: list[dict[str, Any]] = []
    accepted_best: SelectedArtifact | None = None
    accepted_results: list[SelectedArtifact] = []
    rejected_best: SelectedArtifact | None = None
    max_selected_results = max_selected_results_for_request(request)
    candidate_attempt_budget = candidate_attempt_budget_for_request(request)
    timings = {
        "reviewRankingSeconds": 0.0,
        "selectionMaterializationSeconds": 0.0,
        "skippedPreviouslyTerminalCandidateCount": 0,
        "parentSourceWindowFallbackQueuedCount": 0,
        "candidateAttemptBudget": candidate_attempt_budget,
    }
    previous_terminal_results = load_previous_terminal_candidate_results(request.workspace)

    processed_new_candidate_count = 0
    candidate_queue = list(candidates)
    queued_attempt_keys = {ranked_candidate_attempt_key(candidate) for candidate in candidate_queue}
    parent_source_window_fallback_budget = 0
    candidate_queue_index = 0
    while candidate_queue_index < len(candidate_queue):
        ranked_candidate = candidate_queue[candidate_queue_index]
        candidate_queue_index += 1
        attempt_key = ranked_candidate_attempt_key(ranked_candidate)
        previous_terminal_result = previous_terminal_results.get(attempt_key)
        if previous_terminal_result is not None:
            result = build_skipped_previous_terminal_result(ranked_candidate, previous_terminal_result)
            candidate_results.append(result)
            selection_attempts.append(
                {
                    "candidateRank": ranked_candidate.candidate_rank,
                    "exerciseName": ranked_candidate.exercise_name,
                    "candidateTitle": ranked_candidate.title,
                    "videoId": ranked_candidate.candidate.get("videoId"),
                    "status": "skipped_previous_terminal_result",
                    "previousStatus": previous_terminal_result.get("status"),
                    "previousFinalSelectionStatus": previous_terminal_result.get("finalSelectionStatus"),
                    "reviewItemCount": 0,
                    "accepted": False,
                    "selected": False,
                    **source_window_attempt_manifest(ranked_candidate),
                }
            )
            timings["skippedPreviouslyTerminalCandidateCount"] = int(
                timings["skippedPreviouslyTerminalCandidateCount"]
            ) + 1
            continue
        if processed_new_candidate_count >= candidate_attempt_budget + parent_source_window_fallback_budget:
            break
        processed_new_candidate_count += 1

        local_review_items: list[ReviewItem] = []
        local_review_item_entries: list[dict[str, Any]] = []
        process_kwargs: dict[str, Any] = {
            "request": request,
            "preview_baker": preview_baker,
            "review_items": local_review_items,
            "review_item_entries": local_review_item_entries,
            "support_dominance_classifier": support_dominance_classifier,
            "source_cut_caption_images": source_cut_caption_images,
        }
        if exercise_motion_contract_resolver is not None:
            process_kwargs["exercise_motion_contract_resolver"] = exercise_motion_contract_resolver
        if exercise_skeleton_contract_resolver is not None:
            process_kwargs["exercise_skeleton_contract_resolver"] = exercise_skeleton_contract_resolver
        result = process_ranked_candidate(ranked_candidate, **process_kwargs)
        result.setdefault("exerciseIndex", ranked_candidate.exercise_index)
        result.setdefault("candidateRank", ranked_candidate.candidate_rank)
        result.setdefault("exerciseId", ranked_candidate.exercise_id)
        result.setdefault("exerciseName", ranked_candidate.exercise_name)
        result.setdefault("candidate", ranked_candidate.candidate)
        for key, value in source_window_attempt_manifest(ranked_candidate).items():
            result.setdefault(key, value)
        candidate_results.append(result)
        review_items.extend(local_review_items)
        review_item_entries.extend(local_review_item_entries)

        attempt_payload: dict[str, Any] = {
            "candidateRank": ranked_candidate.candidate_rank,
            "exerciseName": ranked_candidate.exercise_name,
            "candidateTitle": ranked_candidate.title,
            "videoId": ranked_candidate.candidate.get("videoId"),
            "status": result.get("status"),
            "reviewItemCount": len(local_review_items),
            "accepted": False,
            "selected": False,
            **source_window_attempt_manifest(ranked_candidate),
        }
        selection_attempts.append(attempt_payload)
        if not local_review_items:
            if result.get("status") != "failed":
                result["finalSelectionStatus"] = "not_reviewable"
            continue

        if effective_ranker is None:
            local_rankings = [
                LoopRanking(score=1.0, reasons=["ranking_skipped"])
                for _ in local_review_items
            ]
        else:
            stage_started = time.perf_counter()
            local_rankings = effective_ranker(local_review_items, request)
            timings["reviewRankingSeconds"] = round(
                float(timings["reviewRankingSeconds"]) + elapsed_seconds(stage_started),
                3,
            )
        rankings.extend(local_rankings)

        stage_started = time.perf_counter()
        if max_selected_results > 1:
            remaining_result_slots = max(1, max_selected_results - len(accepted_results))
            choose_kwargs: dict[str, Any] = {
                "request": request,
                "max_results": remaining_result_slots,
            }
            if final_output_caption_images is not None:
                choose_kwargs["final_output_caption_images"] = final_output_caption_images
            local_selected_results, local_rejected_best = choose_top_materialized_review_items(
                local_review_items,
                local_rankings,
                **choose_kwargs,
            )
            selected = local_selected_results[0] if local_selected_results else None
        else:
            choose_kwargs = {"request": request}
            if final_output_caption_images is not None:
                choose_kwargs["final_output_caption_images"] = final_output_caption_images
            selected, local_rejected_best = choose_best_materialized_review_item(
                local_review_items,
                local_rankings,
                **choose_kwargs,
            )
            local_selected_results = [selected] if selected is not None else []
        timings["selectionMaterializationSeconds"] = round(
            float(timings["selectionMaterializationSeconds"]) + elapsed_seconds(stage_started),
            3,
        )
        if local_selected_results:
            attempt_payload["accepted"] = True
            attempt_payload["selectionScore"] = selected_artifact_score(local_selected_results[0])
            result["finalSelectionStatus"] = "accepted_after_materialized_review"
            result["finalSelectionScore"] = selected_artifact_score(local_selected_results[0])
            accepted_results.extend(local_selected_results)
            accepted_results = sorted(
                accepted_results,
                key=selected_artifact_sort_key,
                reverse=True,
            )[:max_selected_results]
            accepted_best = accepted_results[0]
            if len(accepted_results) >= max_selected_results:
                break
            continue

        result["finalSelectionStatus"] = "rejected_after_materialized_review"
        if local_rejected_best is not None:
            rejected_score = selected_artifact_score(local_rejected_best)
            attempt_payload["rejectedBestScore"] = rejected_score
            result["finalRejectedBestScore"] = rejected_score
            if (
                rejected_best is None
                or selected_artifact_score(local_rejected_best) > selected_artifact_score(rejected_best)
            ):
                rejected_best = local_rejected_best
        should_queue_parent, parent_fallback_reason = should_queue_parent_source_window_fallback(
            ranked_candidate,
            result,
            local_rejected_best,
        )
        if should_queue_parent and parent_fallback_reason is not None:
            parent_fallback_candidate = ranked_candidate_with_parent_source_window_fallback(
                ranked_candidate,
                reason=parent_fallback_reason,
            )
            if parent_fallback_candidate is not None:
                parent_fallback_key = ranked_candidate_attempt_key(parent_fallback_candidate)
                if parent_fallback_key not in queued_attempt_keys:
                    queued_attempt_keys.add(parent_fallback_key)
                    candidate_queue.append(parent_fallback_candidate)
                    parent_source_window_fallback_budget += 1
                    timings["parentSourceWindowFallbackQueuedCount"] = int(
                        timings["parentSourceWindowFallbackQueuedCount"]
                    ) + 1
                    result["parentSourceWindowFallbackQueued"] = True
                    result["parentSourceWindowFallbackReason"] = parent_fallback_reason
                    result["parentSourceWindowFallbackAttemptKey"] = parent_fallback_key
                    attempt_payload["parentSourceWindowFallbackQueued"] = True
                    attempt_payload["parentSourceWindowFallbackReason"] = parent_fallback_reason
                    attempt_payload["parentSourceWindowFallbackAttemptKey"] = parent_fallback_key

    timings["newCandidateAttemptCount"] = processed_new_candidate_count

    if accepted_results:
        selected_key_by_attempt = {
            review_item_attempt_key(selected_item): index
            for index, (selected_item, _selected_ranking) in enumerate(accepted_results)
        }
        for attempt in selection_attempts:
            selected_index = selected_key_by_attempt.get(str(attempt.get("sourceWindowAttemptKey")))
            if selected_index is not None:
                attempt["selected"] = True
                attempt["selectedResultIndex"] = selected_index
                if selected_index > 0:
                    attempt["selectedAlternative"] = True
        for result in candidate_results:
            attempt_key = candidate_result_attempt_key(result)
            selected_index = selected_key_by_attempt.get(attempt_key) if attempt_key is not None else None
            if selected_index is not None:
                selected_artifact = accepted_results[selected_index]
                result["finalSelectionStatus"] = "selected" if selected_index == 0 else "selected_alternative"
                result["finalSelectionScore"] = selected_artifact_score(selected_artifact)
                result["selectedResultIndex"] = selected_index
        return (
            candidate_results,
            review_items,
            review_item_entries,
            rankings,
            accepted_results[0],
            accepted_results,
            None,
            selection_attempts,
            timings,
        )
    if accepted_best is not None:
        accepted_item, _accepted_ranking = accepted_best
        accepted_attempt_key = review_item_attempt_key(accepted_item)
        for attempt in selection_attempts:
            if attempt.get("sourceWindowAttemptKey") == accepted_attempt_key:
                attempt["selected"] = True
                break
        for result in candidate_results:
            if candidate_result_attempt_key(result) == accepted_attempt_key:
                result["finalSelectionStatus"] = "selected"
                break
        return (
            candidate_results,
            review_items,
            review_item_entries,
            rankings,
            accepted_best,
            [accepted_best],
            None,
            selection_attempts,
            timings,
        )

    return (
        candidate_results,
        review_items,
        review_item_entries,
        rankings,
        None,
        [],
        rejected_best,
        selection_attempts,
        timings,
    )


def process_ranked_candidates_for_selection(
    candidates: list[RankedCandidate],
    *,
    request: BakeAndRankRequest,
    preview_baker: PreviewBaker,
    support_dominance_classifier: Callable[[list[Path], str], str] | None,
    source_cut_caption_images: Callable[..., str] | None = None,
    exercise_motion_contract_resolver: ExerciseMotionContractResolver | None = None,
    exercise_skeleton_contract_resolver: ExerciseSkeletonContractResolver | None = None,
) -> tuple[list[dict[str, Any]], list[ReviewItem], list[dict[str, Any]]]:
    fallback_ready_target = ready_candidate_target_for_request(request)
    candidate_attempt_limit = candidate_attempt_budget_for_request(request)
    candidates_to_process, skipped_by_original_index = ranked_candidates_to_process_with_previous_terminal_skips(
        candidates,
        request=request,
        fallback_ready_target=candidate_attempt_limit,
    )
    if not candidates_to_process:
        return (
            [
                skipped_by_original_index[index]
                for index in sorted(skipped_by_original_index)
            ],
            [],
            [],
        )
    workers = max(1, min(request.candidate_workers, len(candidates_to_process)))
    if workers == 1:
        processed_by_original_index: dict[int, tuple[dict[str, Any], list[ReviewItem], list[dict[str, Any]]]] = {}
        ready_candidate_count = 0
        for original_index, ranked_candidate in candidates_to_process:
            local_review_items: list[ReviewItem] = []
            local_review_item_entries: list[dict[str, Any]] = []
            process_kwargs = {
                "request": request,
                "preview_baker": preview_baker,
                "review_items": local_review_items,
                "review_item_entries": local_review_item_entries,
                "support_dominance_classifier": support_dominance_classifier,
                "source_cut_caption_images": source_cut_caption_images,
            }
            if exercise_motion_contract_resolver is not None:
                process_kwargs["exercise_motion_contract_resolver"] = exercise_motion_contract_resolver
            if exercise_skeleton_contract_resolver is not None:
                process_kwargs["exercise_skeleton_contract_resolver"] = exercise_skeleton_contract_resolver
            result = process_ranked_candidate(ranked_candidate, **process_kwargs)
            processed_by_original_index[original_index] = (result, local_review_items, local_review_item_entries)
            if result.get("status") == "ready_for_selection":
                ready_candidate_count += 1
            if not request.pre_wham_source_validation and ready_candidate_count >= fallback_ready_target:
                break
        return collect_candidate_processing_results_in_source_order(
            processed_by_original_index,
            skipped_by_original_index,
            request=request,
            fallback_ready_target=fallback_ready_target,
        )

    results_by_index: dict[int, tuple[dict[str, Any], list[ReviewItem], list[dict[str, Any]]]] = {}
    next_index = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        while (
            next_index < len(candidates_to_process)
            and len(futures) < workers
            and ready_candidate_capacity_in_launched_prefix(results_by_index, next_index) < fallback_ready_target
        ):
            _original_index, ranked_candidate = candidates_to_process[next_index]
            isolated_args = [
                ranked_candidate,
                request,
                preview_baker,
                support_dominance_classifier,
                source_cut_caption_images,
                exercise_motion_contract_resolver,
                exercise_skeleton_contract_resolver,
            ]
            futures[
                executor.submit(
                    process_ranked_candidate_isolated,
                    *isolated_args,
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
                    _original_index, ranked_candidate = candidates_to_process[next_index]
                    isolated_args = [
                        ranked_candidate,
                        request,
                        preview_baker,
                        support_dominance_classifier,
                        source_cut_caption_images,
                        exercise_motion_contract_resolver,
                        exercise_skeleton_contract_resolver,
                    ]
                    futures[
                        executor.submit(
                            process_ranked_candidate_isolated,
                            *isolated_args,
                        )
                    ] = next_index
                    next_index += 1
                break
    processed_by_original_index = {
        candidates_to_process[index][0]: result_tuple
        for index, result_tuple in results_by_index.items()
    }
    return collect_candidate_processing_results_in_source_order(
        processed_by_original_index,
        skipped_by_original_index,
        request=request,
        fallback_ready_target=fallback_ready_target,
    )


def collect_candidate_processing_results_in_source_order(
    processed_by_original_index: dict[int, tuple[dict[str, Any], list[ReviewItem], list[dict[str, Any]]]],
    skipped_by_original_index: dict[int, dict[str, Any]],
    *,
    request: BakeAndRankRequest,
    fallback_ready_target: int,
) -> tuple[list[dict[str, Any]], list[ReviewItem], list[dict[str, Any]]]:
    candidate_results: list[dict[str, Any]] = []
    review_items: list[ReviewItem] = []
    review_item_entries: list[dict[str, Any]] = []
    ready_count = 0
    for original_index in sorted({*processed_by_original_index.keys(), *skipped_by_original_index.keys()}):
        skipped_result = skipped_by_original_index.get(original_index)
        if skipped_result is not None:
            candidate_results.append(skipped_result)
            continue
        result_tuple = processed_by_original_index.get(original_index)
        if result_tuple is None:
            continue
        result, local_review_items, local_review_item_entries = result_tuple
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
    exercise_motion_contract_resolver: ExerciseMotionContractResolver | None = None,
    exercise_skeleton_contract_resolver: ExerciseSkeletonContractResolver | None = None,
) -> tuple[dict[str, Any], list[ReviewItem], list[dict[str, Any]]]:
    review_items: list[ReviewItem] = []
    review_item_entries: list[dict[str, Any]] = []
    process_kwargs = {
        "request": request,
        "preview_baker": preview_baker,
        "review_items": review_items,
        "review_item_entries": review_item_entries,
        "support_dominance_classifier": support_dominance_classifier,
        "source_cut_caption_images": source_cut_caption_images,
    }
    if exercise_motion_contract_resolver is not None:
        process_kwargs["exercise_motion_contract_resolver"] = exercise_motion_contract_resolver
    if exercise_skeleton_contract_resolver is not None:
        process_kwargs["exercise_skeleton_contract_resolver"] = exercise_skeleton_contract_resolver
    result = process_ranked_candidate(ranked_candidate, **process_kwargs)
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
    exercise_motion_contract_resolver: ExerciseMotionContractResolver | None = None,
    exercise_skeleton_contract_resolver: ExerciseSkeletonContractResolver | None = None,
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
    result_payload.update(source_window_attempt_manifest(ranked_candidate))
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
        generate_kwargs: dict[str, Any] = {
            "request": request,
            "source_cut_caption_images": source_cut_caption_images,
        }
        if exercise_motion_contract_resolver is not None:
            generate_kwargs["exercise_motion_contract_resolver"] = exercise_motion_contract_resolver
        if exercise_skeleton_contract_resolver is not None:
            generate_kwargs["exercise_skeleton_contract_resolver"] = exercise_skeleton_contract_resolver
        generate_result = generate_candidate_motion(ranked_candidate, **generate_kwargs)
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
                    export_payload=artifact.export_payload,
                )
                precheck_started = time.perf_counter()
                precheck = cheap_final_output_preview_precheck(review_item)
                result_payload.setdefault("cheapFinalOutputPrecheckSeconds", 0.0)
                result_payload["cheapFinalOutputPrecheckSeconds"] = round(
                    float(result_payload["cheapFinalOutputPrecheckSeconds"]) + elapsed_seconds(precheck_started),
                    3,
                )
                if not bool(precheck.get("passed", True)):
                    result_payload["rejectedSourceClips"].append(
                        {
                            "loopIndex": eligible_loop.loop_index,
                            "sourceClipIndex": eligible_loop.loop_index,
                            "durationSec": eligible_loop.duration_sec,
                            "reason": "cheap_final_output_preview_rejected",
                            "settingsVariantId": artifact.settings_variant_id,
                            "settingsVariantLabel": artifact.settings_variant_label,
                            "skeletonPath": str(artifact.skeleton_path),
                            "reviewVideoPath": str(artifact.review_video_path),
                            "cheapFinalOutputPreviewPrecheck": precheck,
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
                    if support_dominance_result is not None:
                        review_item = replace(
                            review_item,
                            support_dominance=support_dominance_result.support_dominance,
                            support_dominance_confidence=support_dominance_result.confidence,
                            support_dominance_reason=support_dominance_result.reason,
                            support_dominance_uncertain=support_dominance_result.uncertain,
                            support_dominance_model_output=support_dominance_result.model_output,
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
        elif any(
            item.get("reason") in {"baked_motion_too_static", "cheap_final_output_preview_rejected"}
            for item in result_payload["rejectedSourceClips"]
        ):
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
    exercise_motion_contract_resolver: ExerciseMotionContractResolver | None = None,
    exercise_skeleton_contract_resolver: ExerciseSkeletonContractResolver | None = None,
) -> GenerateResult:
    source_started = time.perf_counter()
    video_path = prepare_candidate_input_video(
        ranked_candidate,
        request=request,
        source_cut_caption_images=source_cut_caption_images,
        exercise_motion_contract_resolver=exercise_motion_contract_resolver,
        exercise_skeleton_contract_resolver=exercise_skeleton_contract_resolver,
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
            use_warm_wham_worker=request.use_warm_wham_worker,
            wham_worker_session_dir=request.wham_worker_session_dir,
            wham_worker_mount_root=request.wham_worker_mount_root,
            wham_worker_timeout_seconds=request.wham_worker_timeout_seconds,
            wham_timeout_seconds=request.wham_timeout_seconds,
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
            export_wham_smpl_preview=request.export_wham_smpl_preview,
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
            contact_sheet_sequence_labels=True,
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
    exercise_motion_contract_resolver: ExerciseMotionContractResolver | None = None,
    exercise_skeleton_contract_resolver: ExerciseSkeletonContractResolver | None = None,
) -> Path:
    candidate_workspace = request.workspace / ranked_candidate.workspace_slug
    source_dir = candidate_workspace / "source"
    source_video_path = copy_or_download_candidate_source(
        ranked_candidate,
        source_dir,
        youtube_cookies=request.youtube_cookies,
        youtube_source_cache_dir=resolved_youtube_source_cache_dir(request),
        youtube_preview_cache_dir=default_youtube_preview_cache_read_through_dir(request),
    )
    source_chunk_hint = ranked_candidate.source_chunk_hint
    use_parent_source_window_fallback = (
        parse_optional_bool(ranked_candidate.candidate.get("sourceWindowParentFallback")) is True
    )
    pre_wham_caption_images = source_cut_caption_images if request.pre_wham_source_validation else None
    exercise_motion_contract = (
        exercise_motion_contract_resolver(ranked_candidate)
        if pre_wham_caption_images is not None and exercise_motion_contract_resolver is not None
        else None
    )
    exercise_skeleton_contract = (
        exercise_skeleton_contract_resolver(ranked_candidate)
        if pre_wham_caption_images is not None and exercise_skeleton_contract_resolver is not None
        else None
    )
    if use_parent_source_window_fallback and source_chunk_hint is not None:
        return trim_ranked_source_chunk_hint(
            ranked_candidate=ranked_candidate,
            candidate_workspace=candidate_workspace,
            source_video_path=source_video_path,
            source_chunk_hint=source_chunk_hint,
            source_prep_reason=PARENT_SOURCE_WINDOW_FALLBACK_ATTEMPT_MODE,
            fallback_reason=str(ranked_candidate.candidate.get("sourceWindowParentFallbackReason") or ""),
        )
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
            exercise_motion_contract_enabled=request.exercise_motion_contract_enabled,
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
                exercise_motion_contract=exercise_motion_contract,
                exercise_skeleton_contract=exercise_skeleton_contract,
                max_vlm_workers=request.review_llm_workers,
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
        replace(
            build_llama_cpp_vision_settings(request),
            llama_cpp_base_url=segment_base_url,
            llama_cpp_model=segment_model,
            vision_llm_workers=max(1, request.segment_classification_workers),
            llama_cpp_n_predict=SEGMENT_DETECTION_VLM_MAX_TOKENS,
            llama_cpp_temperature=SEGMENT_DETECTION_VLM_TEMPERATURE,
            llama_cpp_top_p=SEGMENT_DETECTION_VLM_TOP_P,
            llama_cpp_disable_reasoning=SEGMENT_DETECTION_VLM_DISABLE_REASONING,
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
                    llama_cpp_n_predict=SEGMENT_DETECTION_VLM_MAX_TOKENS,
                    llama_cpp_temperature=SEGMENT_DETECTION_VLM_TEMPERATURE,
                    llama_cpp_top_p=SEGMENT_DETECTION_VLM_TOP_P,
                    llama_cpp_top_k=request.llama_cpp_top_k,
                    llama_cpp_disable_reasoning=SEGMENT_DETECTION_VLM_DISABLE_REASONING,
                    llama_cpp_image_min_tokens=request.llama_cpp_image_min_tokens,
                    llama_cpp_image_max_tokens=request.llama_cpp_image_max_tokens,
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
            exercise_motion_contract=exercise_motion_contract,
            exercise_skeleton_contract=exercise_skeleton_contract,
            source_detection_result=detection_result,
            source_chunk_estimate=chunk_estimate,
            max_vlm_workers=request.review_llm_workers,
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
    exercise_motion_contract_enabled: bool,
) -> bool:
    if not pre_wham_source_validation:
        return True
    try:
        payload = json.loads(segment_selection_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not (
        bool(payload.get("preWhamSourceValidationEnabled"))
        or str(payload.get("sourcePrepReason")) == "pre_wham_source_window_choice"
    ):
        return False
    if exercise_motion_contract_enabled:
        if not bool(payload.get("exerciseMotionContractEnabled")) and not payload.get("exerciseMotionContractStatus"):
            return False
        if not bool(payload.get("exerciseSkeletonContractEnabled")) and not payload.get("exerciseSkeletonContractStatus"):
            return False
    return True


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
    exercise_motion_contract: dict[str, Any] | None = None,
    exercise_skeleton_contract: dict[str, Any] | None = None,
    source_detection_result: Any | None = None,
    source_chunk_estimate: Any | None = None,
    max_vlm_workers: int = 1,
    segment_settings: dict[str, Any] | None = None,
) -> Path:
    chunk_estimate = source_chunk_estimate or estimate_chunking(
        exercise_name=ranked_candidate.exercise_name,
        use_llm=False,
    )
    segment_dir = candidate_workspace / "segment_detection"
    selection_dir = segment_dir / "pre_wham_source_candidates"
    vision_payload = ranked_candidate.candidate.get("visionPayload")
    source_pose_prefilter_payload = (
        vision_payload.get("posePrefilter")
        if isinstance(vision_payload, dict) and isinstance(vision_payload.get("posePrefilter"), dict)
        else None
    )
    source_choice = rank_source_video_cut_candidates_with_caption_images(
        video_path=detection_source_video_path,
        exercise_name=ranked_candidate.exercise_name,
        candidate_title=ranked_candidate.title,
        timeline_window=source_window,
        chunk_estimate=chunk_estimate,
        output_dir=selection_dir,
        frame_count=max(12, min(DEFAULT_LLM_REVIEW_FRAMES, frames_for_chunk_seconds(max(0.5, source_window.end_seconds - source_window.start_seconds)))),
        caption_images=caption_images,
        exercise_motion_contract=exercise_motion_contract,
        source_pose_prefilter_payload=source_pose_prefilter_payload,
        source_pose_offset_seconds=detection_source_offset_seconds,
        max_vlm_workers=max_vlm_workers,
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
            exercise_motion_contract=exercise_motion_contract,
            exercise_skeleton_contract=exercise_skeleton_contract,
            source_detection_result=source_detection_result,
            chunk_estimate=chunk_estimate,
            segment_settings=segment_settings,
        )
        raise SourceCandidateRejected("Pre-WHAM source validation found no source-window candidates.")
    ranking, render_seconds, vlm_seconds = source_choice
    parent_fallback_window = (
        pre_wham_parent_source_window_fallback(
            ranking=ranking,
            source_window=source_window,
            detection_source_offset_seconds=detection_source_offset_seconds,
            source_chunk_hint=source_chunk_hint,
        )
        if ranking.score < SOURCE_CUT_MIN_SELECTED_SCORE
        else None
    )
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
        exercise_motion_contract=exercise_motion_contract,
        exercise_skeleton_contract=exercise_skeleton_contract,
        source_detection_result=source_detection_result,
        chunk_estimate=chunk_estimate,
        segment_settings=segment_settings,
        parent_fallback_window=parent_fallback_window,
    )
    if ranking.score < SOURCE_CUT_MIN_SELECTED_SCORE:
        if parent_fallback_window is not None:
            selected_segment_path = candidate_workspace / "input" / "selected_segment.mp4"
            selected_segment_path.parent.mkdir(parents=True, exist_ok=True)
            trim_video(
                source_path=detection_source_video_path,
                output_path=selected_segment_path,
                start_seconds=parent_fallback_window.start_seconds,
                end_seconds=parent_fallback_window.end_seconds,
            )
            return selected_segment_path
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


def pre_wham_parent_source_window_fallback(
    *,
    ranking: LoopRanking,
    source_window: DetectionWindow,
    detection_source_offset_seconds: float,
    source_chunk_hint: SourceChunkHint | None,
) -> DetectionWindow | None:
    if source_chunk_hint is None or source_chunk_hint.score is None:
        return None
    if source_chunk_hint.score < SOURCE_GATE_STRONG_BEST_CHUNK_SCORE:
        return None
    if source_window.end_seconds <= source_window.start_seconds:
        return None
    reason_tags = {str(reason) for reason in ranking.reasons if str(reason)}
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    if parse_optional_bool(payload.get("sourceChoiceInvalidResponse")) is True:
        reason_tags.add("source_candidate_choice_invalid_response")
    if not reason_tags.intersection(
        {
            "source_candidate_scorecard_no_passing_candidate",
            "source_candidate_choice_invalid_response",
        }
    ):
        return None
    if detection_source_offset_seconds > 0.0:
        duration = max(0.0, source_chunk_hint.end_seconds - source_chunk_hint.start_seconds)
        if duration <= 0.0:
            return None
        return DetectionWindow(index=0, start_seconds=0.0, end_seconds=duration)
    return DetectionWindow(
        index=0,
        start_seconds=max(0.0, source_chunk_hint.start_seconds),
        end_seconds=source_chunk_hint.end_seconds,
    )


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
    exercise_motion_contract: dict[str, Any] | None,
    exercise_skeleton_contract: dict[str, Any] | None,
    source_detection_result: Any | None,
    chunk_estimate: Any,
    segment_settings: dict[str, Any] | None,
    parent_fallback_window: DetectionWindow | None = None,
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
    if selected_span is None and parent_fallback_window is not None:
        selected_span = {
            "startSeconds": parent_fallback_window.start_seconds,
            "endSeconds": parent_fallback_window.end_seconds,
            "confidence": ranking.score if ranking is not None else 0.0,
            "fallback": "parent_source_window",
        }
    selected_span_in_original_source = (
        {
            "startSeconds": detection_source_offset_seconds + start_seconds,
            "endSeconds": detection_source_offset_seconds + end_seconds,
            "confidence": ranking.score if ranking is not None else 0.0,
        }
        if start_seconds is not None and end_seconds is not None
        else None
    )
    if selected_span_in_original_source is None and parent_fallback_window is not None:
        selected_span_in_original_source = {
            "startSeconds": detection_source_offset_seconds + parent_fallback_window.start_seconds,
            "endSeconds": detection_source_offset_seconds + parent_fallback_window.end_seconds,
            "confidence": ranking.score if ranking is not None else 0.0,
            "fallback": "parent_source_window",
        }
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
    prompt_contract_present = exercise_motion_contract_for_prompt(exercise_motion_contract) is not None
    contract_status = None
    if isinstance(exercise_motion_contract, dict):
        contract_status = (
            exercise_motion_contract.get("exerciseMotionContractStatus")
            or exercise_motion_contract.get("status")
        )
    skeleton_contract_present = exercise_motion_contract_for_prompt(exercise_skeleton_contract) is not None
    skeleton_contract_status = None
    if isinstance(exercise_skeleton_contract, dict):
        skeleton_contract_status = (
            exercise_skeleton_contract.get("exerciseSkeletonContractStatus")
            or exercise_skeleton_contract.get("status")
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
        "preWhamParentSourceWindowFallback": parent_fallback_window is not None,
        "preWhamParentSourceWindowFallbackReason": (
            "source_scorecard_no_passing_child_candidate"
            if parent_fallback_window is not None
            else None
        ),
        "sourceCutRanking": None if ranking is None else ranking_to_manifest(ranking),
        "sourceCutRenderSeconds": render_seconds,
        "sourceCutVlmSeconds": vlm_seconds,
        "exerciseMotionContractEnabled": prompt_contract_present,
        "exerciseMotionContractStatus": contract_status,
        "exerciseMotionContract": exercise_motion_contract,
        "exerciseSkeletonContractEnabled": skeleton_contract_present,
        "exerciseSkeletonContractStatus": skeleton_contract_status,
        "exerciseSkeletonContract": exercise_skeleton_contract,
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
    source_prep_reason: str = "ranked_best_chunk",
    fallback_reason: str | None = None,
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
                "source": source_prep_reason,
                "sourcePrepReason": source_prep_reason,
                "fallbackReason": fallback_reason,
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
            if adaptive_preview_settings:
                variants = plan_adaptive_preview_settings_variants(
                    page=page,
                    eligible_loop=eligible_loop,
                    base_options=base_options,
                    review_dir=review_dir,
                    artifact_base_label=artifact_base_label,
                    review_frames=review_frames,
                    motion_tuning_enabled=motion_tuning_enabled,
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
                options = with_fixed_preview_camera_options(options)
                artifact_label = artifact_base_label if not (rank_preview_variants or adaptive_preview_settings) else f"{artifact_base_label}.{variant_id}"
                export_payload = page.evaluate(
                    """({ loopIndex, options }) => window.exerciseMotionAutomation.bakeLoop(loopIndex, options)""",
                    {"loopIndex": eligible_loop.loop_index, "options": options},
                )
                options, post_bake_orientation_hint, post_bake_orientation_applied = (
                    deterministic_post_bake_scene_orientation_correction(
                        export_payload,
                        options=options,
                    )
                )
                if post_bake_orientation_applied:
                    export_payload = page.evaluate(
                        """({ loopIndex, options }) => window.exerciseMotionAutomation.bakeLoop(loopIndex, options)""",
                        {"loopIndex": eligible_loop.loop_index, "options": options},
                    )
                annotate_export_payload_post_bake_scene_orientation(
                    export_payload,
                    orientation_hint=post_bake_orientation_hint,
                    applied=post_bake_orientation_applied,
                )
                adaptive_settings = (
                    dict(variant["adaptivePreviewSettings"])
                    if isinstance(variant.get("adaptivePreviewSettings"), dict)
                    else None
                )
                if post_bake_orientation_applied:
                    adaptive_settings = add_post_bake_scene_orientation_to_adaptive_settings(
                        adaptive_settings,
                        orientation_hint=post_bake_orientation_hint,
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
                        adaptive_preview_settings=adaptive_settings,
                    )
                )
        browser.close()
    return artifacts


def choose_deterministic_orientation_strategy(
    *,
    page: Any,
    eligible_loop: EligibleLoop,
    base_options: dict[str, Any],
    orientation_hint: dict[str, Any],
    preview_settings_hint: dict[str, Any],
) -> dict[str, Any]:
    if not bool(orientation_hint.get("forceSceneInverted")):
        return {
            **orientation_hint,
            "orientationStrategy": "none",
        }
    if bool(preview_settings_hint.get("forceAutoWorldAlignmentFalse")):
        return {
            **orientation_hint,
            "orientationStrategy": "scene_inversion",
            "autoWorldAlignmentProbeSkippedReason": "disabled_by_body_orientation_geometry",
        }

    auto_options = with_fixed_preview_camera_options(
        {
            **base_options,
            "autoWorldAlignment": True,
            "sceneInverted": False,
        }
    )
    try:
        auto_export = page.evaluate(
            """({ loopIndex, options }) => window.exerciseMotionAutomation.bakeLoop(loopIndex, options)""",
            {"loopIndex": eligible_loop.loop_index, "options": auto_options},
        )
        auto_orientation_hint = deterministic_scene_orientation_hint_from_payload(
            auto_export,
            options=auto_options,
        )
    except Exception as exc:
        return {
            **orientation_hint,
            "orientationStrategy": "scene_inversion",
            "autoWorldAlignmentProbeFailure": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }

    if not bool(auto_orientation_hint.get("forceSceneInverted")):
        return {
            **orientation_hint,
            "forceSceneInverted": False,
            "forceAutoWorldAlignment": True,
            "reason": "auto_world_alignment_resolves_scene_orientation",
            "orientationStrategy": "auto_world_alignment",
            "baselineSceneOrientation": orientation_hint,
            "autoWorldAlignmentSceneOrientation": auto_orientation_hint,
        }

    return {
        **orientation_hint,
        "orientationStrategy": "scene_inversion",
        "autoWorldAlignmentSceneOrientation": auto_orientation_hint,
    }


def plan_adaptive_preview_settings_variants(
    *,
    page: Any,
    eligible_loop: EligibleLoop,
    base_options: dict[str, Any],
    review_dir: Path,
    artifact_base_label: str,
    review_frames: int,
    motion_tuning_enabled: bool,
    max_variants: int,
    exercise_name: str | None = None,
) -> list[dict[str, Any]]:
    baseline_variant = {
        "id": "adaptive-baseline",
        "label": "Adaptive baseline",
        "options": {},
        "adaptivePreviewSettings": {
            "source": "deterministic_baseline",
            "reason": "baseline_measured_for_deterministic_postprocessing",
        },
    }
    try:
        baseline_export = page.evaluate(
            """({ loopIndex, options }) => window.exerciseMotionAutomation.bakeLoop(loopIndex, options)""",
            {"loopIndex": eligible_loop.loop_index, "options": base_options},
        )
        planning_frame_count = adaptive_preview_settings_contact_sheet_frame_count(review_frames)
        frame_indices = sample_review_frame_indices(baseline_export, planning_frame_count)
        frame_timestamps = frame_timestamps_for_indices(baseline_export, frame_indices)
        frame_data_urls = [
            page.evaluate(
                """({ frameIndex, options }) => window.exerciseMotionAutomation.renderFrame(frameIndex, options)""",
                {"frameIndex": frame_index, "options": base_options},
            )
            for frame_index in frame_indices
        ]
        planning_dir = review_dir / f"{artifact_base_label}.adaptive-settings-planning"
        contact_sheet_path = planning_dir / "baseline_contact_sheet.jpg"
        write_review_contact_sheet_from_data_urls(
            frame_data_urls,
            contact_sheet_path,
            timestamps=frame_timestamps,
            sequence_labels=True,
        )
        orientation_hint = deterministic_scene_orientation_hint_from_payload(
            baseline_export,
            options=base_options,
        )
        preview_settings_hint = deterministic_preview_settings_hint_from_payload(
            baseline_export,
            options=base_options,
        )
        orientation_hint = choose_deterministic_orientation_strategy(
            page=page,
            eligible_loop=eligible_loop,
            base_options=base_options,
            orientation_hint=orientation_hint,
            preview_settings_hint=preview_settings_hint,
        )
        baseline_variant = apply_deterministic_preview_settings_hints_to_variant(
            baseline_variant,
            base_options=base_options,
            orientation_hint=orientation_hint,
            preview_settings_hint=preview_settings_hint,
        )
        baseline_options = with_fixed_preview_camera_options(base_options)
        final_options = with_fixed_preview_camera_options(
            {
                **base_options,
                **dict(
                    baseline_variant.get("options")
                    if isinstance(baseline_variant.get("options"), dict)
                    else {}
                ),
            }
        )
        deterministic_rebake_required = preview_options_changed(
            baseline_options,
            final_options,
            motion_tuning_enabled=motion_tuning_enabled,
        )
        (planning_dir / "adaptive_settings_plan.json").write_text(
            json.dumps(
                {
                    "source": "deterministic_postprocessing",
                    "baseOptions": base_options,
                    "finalOptions": final_options,
                    "requestedReviewFrames": review_frames,
                    "planningFrameCount": planning_frame_count,
                    "contactSheetFrameCount": len(frame_indices),
                    "contactSheetFrameIndices": frame_indices,
                    "contactSheetFrameTimestamps": frame_timestamps,
                    "contactSheetPath": str(contact_sheet_path),
                    "deterministicSceneOrientation": orientation_hint,
                    "deterministicPreviewSettings": preview_settings_hint,
                    "deterministicRebakeRequired": deterministic_rebake_required,
                    "plannedVariants": [baseline_variant],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return [baseline_variant]
    except Exception as exc:
        return [
            {
                **baseline_variant,
                "adaptivePreviewSettings": {
                    "source": "baseline_fallback_after_deterministic_planning_failure",
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
    contact_sheet_frame_count: int | None = None,
) -> str:
    exercise_context = (exercise_name or "").strip() or "unknown"
    contact_sheet_context = (
        f"The contact sheet contains {contact_sheet_frame_count} evenly sampled rendered frames with timestamp labels. "
        if contact_sheet_frame_count is not None
        else "The contact sheet contains evenly sampled rendered frames. "
    )
    return (
        "You are reviewing a baseline rendered preview contact sheet for diagnostics only.\n"
        f"Target exercise: {exercise_context}.\n"
        "You are looking at the baseline rendered preview contact sheet for one exercise motion. "
        f"{contact_sheet_context}"
        f"{CONTACT_SHEET_READING_INSTRUCTIONS}"
        "The baseline already uses deterministic cleanup output, and preview/post-processing settings are chosen only by deterministic geometry code.\n"
        "Do not suggest renderer settings, post-processing settings, camera values, support locks, orientation flags, playback speed, or variants. "
        "If the render is upside down, sliding, unstable, or otherwise hard to read, describe the visible issue only; code owns the fix.\n"
        "Return JSON only with keys: "
        "{\"baseline_is_sufficient\": boolean, \"reasons\": [string]}."
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


SCENE_ORIENTATION_MIN_SAMPLE_COUNT = 5
SCENE_ORIENTATION_SCREEN_RATIO_THRESHOLD = 0.25
SCENE_ORIENTATION_MIN_IMPROVED_INVERTED_RATIO = 0.05
SCENE_ORIENTATION_MIN_INVERSION_IMPROVEMENT = 0.30
SCENE_ORIENTATION_HORIZONTAL_INVERTED_RATIO = 0.12
SCENE_ORIENTATION_HORIZONTAL_INVERSION_IMPROVEMENT = 0.15


def deterministic_scene_orientation_hint_from_payload(
    export_payload: dict[str, Any],
    *,
    options: dict[str, Any],
) -> dict[str, Any]:
    frames_value = export_payload.get("frames")
    if not isinstance(frames_value, list):
        return empty_deterministic_scene_orientation_hint(reason="missing_frames")
    frames = [
        frame
        for frame in frames_value
        if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))
    ]
    if not frames:
        frames = [frame for frame in frames_value if isinstance(frame, dict)]
    if not frames:
        return empty_deterministic_scene_orientation_hint(reason="missing_frames")

    selected_settings = export_payload.get("selectedPreviewSettings")
    selected_options = selected_settings if isinstance(selected_settings, dict) else {}
    scene_inverted = parse_optional_bool(
        selected_options.get("sceneInverted", options.get("sceneInverted"))
    )
    if scene_inverted:
        return empty_deterministic_scene_orientation_hint(reason="scene_already_inverted")

    yaw_degrees = first_float(selected_options.get("cameraYawDegrees"), options.get("cameraYawDegrees"))
    if yaw_degrees is None:
        yaw_degrees = FIXED_PREVIEW_CAMERA_YAW_DEGREES
    pitch_degrees = first_float(selected_options.get("cameraPitchDegrees"), options.get("cameraPitchDegrees"))
    if pitch_degrees is None:
        pitch_degrees = FIXED_PREVIEW_CAMERA_PITCH_DEGREES
    screen_up = preview_camera_screen_up_vector(
        yaw_degrees=yaw_degrees,
        pitch_degrees=pitch_degrees,
    )
    current_ratios = head_to_lower_body_screen_order_ratios(
        frames,
        screen_up=screen_up,
        invert_scene=False,
    )
    inverted_ratios = head_to_lower_body_screen_order_ratios(
        frames,
        screen_up=screen_up,
        invert_scene=True,
    )
    if len(current_ratios) < SCENE_ORIENTATION_MIN_SAMPLE_COUNT or len(inverted_ratios) < SCENE_ORIENTATION_MIN_SAMPLE_COUNT:
        return empty_deterministic_scene_orientation_hint(
            reason="insufficient_head_lower_body_samples",
            sample_count=min(len(current_ratios), len(inverted_ratios)),
        )

    current_median = statistics.median(current_ratios)
    inverted_median = statistics.median(inverted_ratios)
    strongly_upside_down = current_median <= -SCENE_ORIENTATION_SCREEN_RATIO_THRESHOLD
    strongly_upright_after_inversion = inverted_median >= SCENE_ORIENTATION_SCREEN_RATIO_THRESHOLD
    materially_better_after_inversion = (
        inverted_median >= SCENE_ORIENTATION_MIN_IMPROVED_INVERTED_RATIO
        and (inverted_median - current_median) >= SCENE_ORIENTATION_MIN_INVERSION_IMPROVEMENT
    )
    horizontally_better_after_inversion = (
        current_median <= 0.0
        and inverted_median >= SCENE_ORIENTATION_HORIZONTAL_INVERTED_RATIO
        and (inverted_median - current_median) >= SCENE_ORIENTATION_HORIZONTAL_INVERSION_IMPROVEMENT
    )
    should_force_inverted = strongly_upside_down and (
        strongly_upright_after_inversion or materially_better_after_inversion
    ) or horizontally_better_after_inversion
    horizontal_reason = (
        should_force_inverted
        and horizontally_better_after_inversion
        and not strongly_upright_after_inversion
        and not materially_better_after_inversion
    )
    reason = (
        "head_lower_body_order_flipped_by_scene_inversion"
        if should_force_inverted and strongly_upright_after_inversion
        else "head_lower_body_order_improved_by_scene_inversion"
        if should_force_inverted and not horizontal_reason
        else "horizontal_body_order_improved_by_scene_inversion"
        if should_force_inverted
        else "head_lower_body_order_not_strongly_inverted"
    )
    return {
        "source": "deterministic_render_geometry",
        "forceSceneInverted": should_force_inverted,
        "reason": reason,
        "sampleCount": min(len(current_ratios), len(inverted_ratios)),
        "currentHeadToLowerBodyScreenYBodySpanRatioMedian": current_median,
        "invertedHeadToLowerBodyScreenYBodySpanRatioMedian": inverted_median,
        "threshold": SCENE_ORIENTATION_SCREEN_RATIO_THRESHOLD,
        "minImprovedInvertedRatio": SCENE_ORIENTATION_MIN_IMPROVED_INVERTED_RATIO,
        "minInversionImprovement": SCENE_ORIENTATION_MIN_INVERSION_IMPROVEMENT,
        "horizontalInvertedRatio": SCENE_ORIENTATION_HORIZONTAL_INVERTED_RATIO,
        "horizontalInversionImprovement": SCENE_ORIENTATION_HORIZONTAL_INVERSION_IMPROVEMENT,
        "inversionImprovement": inverted_median - current_median,
        "stronglyUpsideDown": strongly_upside_down,
        "stronglyUprightAfterInversion": strongly_upright_after_inversion,
        "materiallyBetterAfterInversion": materially_better_after_inversion,
        "horizontallyBetterAfterInversion": horizontally_better_after_inversion,
        "cameraYawDegrees": yaw_degrees,
        "cameraPitchDegrees": pitch_degrees,
    }


def empty_deterministic_scene_orientation_hint(
    *,
    reason: str,
    sample_count: int = 0,
) -> dict[str, Any]:
    return {
        "source": "deterministic_render_geometry",
        "forceSceneInverted": False,
        "reason": reason,
        "sampleCount": sample_count,
        "threshold": SCENE_ORIENTATION_SCREEN_RATIO_THRESHOLD,
        "minImprovedInvertedRatio": SCENE_ORIENTATION_MIN_IMPROVED_INVERTED_RATIO,
        "minInversionImprovement": SCENE_ORIENTATION_MIN_INVERSION_IMPROVEMENT,
        "horizontalInvertedRatio": SCENE_ORIENTATION_HORIZONTAL_INVERTED_RATIO,
        "horizontalInversionImprovement": SCENE_ORIENTATION_HORIZONTAL_INVERSION_IMPROVEMENT,
    }


def preview_camera_screen_up_vector(
    *,
    yaw_degrees: float,
    pitch_degrees: float,
) -> list[float]:
    yaw = math.radians(yaw_degrees)
    pitch = math.radians(pitch_degrees)
    horizontal_distance = math.cos(pitch)
    camera_offset = [
        math.sin(yaw) * horizontal_distance,
        math.sin(pitch),
        math.cos(yaw) * horizontal_distance,
    ]
    forward = normalize_vector3([-camera_offset[0], -camera_offset[1], -camera_offset[2]])
    world_up = [0.0, 1.0, 0.0]
    right = normalize_vector3(cross_vector3(forward, world_up))
    screen_up = cross_vector3(right, forward)
    return normalize_vector3(screen_up) if vector3_length(screen_up) > 1e-8 else world_up


def head_to_lower_body_screen_order_ratios(
    frames: list[dict[str, Any]],
    *,
    screen_up: list[float],
    invert_scene: bool,
) -> list[float]:
    ratios: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        upper = representative_joint_center(
            joints,
            ("head", "neck", "spine3", "left_shoulder", "right_shoulder"),
        )
        lower = representative_joint_center(
            joints,
            ("left_foot", "right_foot", "left_ankle", "right_ankle"),
        )
        if upper is None or lower is None:
            continue
        transformed_points = [
            apply_scene_inversion_to_point(point3_to_float_list(point), invert_scene)
            for point in joints.values()
            if is_point3(point)
        ]
        if not transformed_points:
            continue
        body_span = body_span_for_points(transformed_points)
        if body_span <= 1e-6:
            continue
        transformed_upper = apply_scene_inversion_to_point(upper, invert_scene)
        transformed_lower = apply_scene_inversion_to_point(lower, invert_scene)
        ratios.append(
            (dot_vector3(transformed_upper, screen_up) - dot_vector3(transformed_lower, screen_up))
            / body_span
        )
    return ratios


def body_span_for_points(points: list[list[float]]) -> float:
    axis_ranges = [
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    ]
    return math.sqrt(sum(axis_range * axis_range for axis_range in axis_ranges))


def representative_joint_center(
    joints: dict[str, Any],
    names: tuple[str, ...],
) -> list[float] | None:
    points = [
        point3_to_float_list(point)
        for name in names
        if is_point3(point := joints.get(name))
    ]
    if not points:
        return None
    return [
        sum(point[axis] for point in points) / len(points)
        for axis in range(3)
    ]


def apply_scene_inversion_to_point(point: list[float], invert_scene: bool) -> list[float]:
    if not invert_scene:
        return point
    return [point[0], -point[1], -point[2]]


def normalize_vector3(vector: list[float]) -> list[float]:
    length = vector3_length(vector)
    if length <= 1e-8:
        return [0.0, 0.0, 0.0]
    return [value / length for value in vector]


def vector3_length(vector: list[float]) -> float:
    return math.sqrt(dot_vector3(vector, vector))


def dot_vector3(left: list[float], right: list[float]) -> float:
    return sum(left[axis] * right[axis] for axis in range(3))


def cross_vector3(left: list[float], right: list[float]) -> list[float]:
    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


def apply_deterministic_scene_orientation_to_variant(
    variant: dict[str, Any],
    *,
    base_options: dict[str, Any],
    orientation_hint: dict[str, Any],
) -> dict[str, Any]:
    if bool(orientation_hint.get("forceAutoWorldAlignment")):
        effective_options = {
            **base_options,
            **dict(variant.get("options") if isinstance(variant.get("options"), dict) else {}),
        }
        corrected = dict(variant)
        corrected_options = dict(variant.get("options") if isinstance(variant.get("options"), dict) else {})
        corrected_options["autoWorldAlignment"] = True
        corrected_options["sceneInverted"] = False
        corrected["options"] = corrected_options
        adaptive_settings = dict(
            variant.get("adaptivePreviewSettings")
            if isinstance(variant.get("adaptivePreviewSettings"), dict)
            else {}
        )
        existing_reason = str(adaptive_settings.get("reason") or "").strip()
        correction_reason = "deterministic scene orientation set autoWorldAlignment true"
        adaptive_settings["reason"] = (
            f"{existing_reason}; {correction_reason}"
            if existing_reason
            else correction_reason
        )
        adaptive_settings["deterministicSceneOrientation"] = orientation_hint
        corrected["adaptivePreviewSettings"] = adaptive_settings
        corrected["cleanupInterpretation"] = str(
            corrected_options.get("cleanupInterpretation")
            or effective_options.get("cleanupInterpretation")
            or corrected.get("cleanupInterpretation")
            or "support_lock"
        )
        return corrected
    if not bool(orientation_hint.get("forceSceneInverted")):
        return variant
    effective_options = {
        **base_options,
        **dict(variant.get("options") if isinstance(variant.get("options"), dict) else {}),
    }
    if parse_optional_bool(effective_options.get("sceneInverted")) is True:
        return variant
    corrected = dict(variant)
    corrected_options = dict(variant.get("options") if isinstance(variant.get("options"), dict) else {})
    corrected_options["sceneInverted"] = True
    corrected["options"] = corrected_options

    adaptive_settings = dict(
        variant.get("adaptivePreviewSettings")
        if isinstance(variant.get("adaptivePreviewSettings"), dict)
        else {}
    )
    existing_reason = str(adaptive_settings.get("reason") or "").strip()
    correction_reason = "deterministic scene orientation set sceneInverted true"
    adaptive_settings["reason"] = (
        f"{existing_reason}; {correction_reason}"
        if existing_reason
        else correction_reason
    )
    adaptive_settings["deterministicSceneOrientation"] = orientation_hint
    corrected["adaptivePreviewSettings"] = adaptive_settings
    corrected["cleanupInterpretation"] = str(
        corrected_options.get("cleanupInterpretation")
        or effective_options.get("cleanupInterpretation")
        or corrected.get("cleanupInterpretation")
        or "support_lock"
    )
    return corrected


def deterministic_post_bake_scene_orientation_correction(
    export_payload: dict[str, Any],
    *,
    options: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    orientation_hint = deterministic_scene_orientation_hint_from_payload(
        export_payload,
        options=options,
    )
    if (
        bool(orientation_hint.get("forceSceneInverted"))
        and parse_optional_bool(options.get("sceneInverted")) is not True
    ):
        corrected_options = dict(options)
        if parse_optional_bool(corrected_options.get("autoWorldAlignment")) is True:
            corrected_options["autoWorldAlignment"] = False
        corrected_options["sceneInverted"] = True
        return corrected_options, orientation_hint, True
    return options, orientation_hint, False


def annotate_export_payload_post_bake_scene_orientation(
    export_payload: dict[str, Any],
    *,
    orientation_hint: dict[str, Any],
    applied: bool,
) -> None:
    export_payload["deterministicPostBakeSceneOrientation"] = {
        "applied": applied,
        "preCorrectionHint": orientation_hint,
    }


def add_post_bake_scene_orientation_to_adaptive_settings(
    adaptive_settings: dict[str, Any] | None,
    *,
    orientation_hint: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(adaptive_settings or {})
    existing_reason = str(updated.get("reason") or "").strip()
    correction_reason = "deterministic post-bake scene orientation set sceneInverted true"
    updated["reason"] = (
        f"{existing_reason}; {correction_reason}"
        if existing_reason
        else correction_reason
    )
    updated["deterministicPostBakeSceneOrientation"] = orientation_hint
    return updated


DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT = 5
DETERMINISTIC_SUPPORT_STATIONARY_RATIO_THRESHOLD = 0.08
DETERMINISTIC_HORIZONTAL_BODY_UPRIGHT_RATIO_THRESHOLD = 0.20
DETERMINISTIC_ROOT_Y_MOTION_RATIO_THRESHOLD = 0.12


def deterministic_preview_settings_hint_from_payload(
    export_payload: dict[str, Any],
    *,
    options: dict[str, Any],
) -> dict[str, Any]:
    frames = motion_frames_from_export_payload(export_payload)
    if len(frames) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT:
        return empty_deterministic_preview_settings_hint(reason="insufficient_frames", sample_count=len(frames))
    body_spans = [body_span_for_frame(frame) for frame in frames]
    body_spans = [span for span in body_spans if span > 1e-6]
    if not body_spans:
        return empty_deterministic_preview_settings_hint(reason="missing_body_span", sample_count=len(frames))
    body_span = statistics.median(body_spans)
    if body_span <= 1e-6:
        return empty_deterministic_preview_settings_hint(reason="invalid_body_span", sample_count=len(frames))

    left_foot_motion = representative_joint_motion_ratio(
        frames,
        ("left_foot", "left_ankle"),
        body_span=body_span,
    )
    right_foot_motion = representative_joint_motion_ratio(
        frames,
        ("right_foot", "right_ankle"),
        body_span=body_span,
    )
    left_hand_motion = representative_joint_motion_ratio(
        frames,
        ("left_hand", "left_wrist"),
        body_span=body_span,
    )
    right_hand_motion = representative_joint_motion_ratio(
        frames,
        ("right_hand", "right_wrist"),
        body_span=body_span,
    )
    upright_ratio = torso_upright_ratio(frames, body_span=body_span)
    root_y_ratio = representative_joint_y_motion_ratio(
        frames,
        ("pelvis", "root", "hips"),
        body_span=body_span,
    )
    force_lock_feet = (
        left_foot_motion is not None
        and right_foot_motion is not None
        and max(left_foot_motion, right_foot_motion) <= DETERMINISTIC_SUPPORT_STATIONARY_RATIO_THRESHOLD
    )
    force_lock_hands = (
        left_hand_motion is not None
        and right_hand_motion is not None
        and max(left_hand_motion, right_hand_motion) <= DETERMINISTIC_SUPPORT_STATIONARY_RATIO_THRESHOLD
        and not force_lock_feet
    )
    force_disable_auto_alignment = (
        upright_ratio is not None
        and abs(upright_ratio) <= DETERMINISTIC_HORIZONTAL_BODY_UPRIGHT_RATIO_THRESHOLD
    )
    force_disable_lock_y_drift = (
        root_y_ratio is not None
        and root_y_ratio >= DETERMINISTIC_ROOT_Y_MOTION_RATIO_THRESHOLD
    )
    return {
        "source": "deterministic_render_geometry",
        "reason": "strong_geometry_hints" if any(
            (
                force_lock_feet,
                force_lock_hands,
                force_disable_auto_alignment,
                force_disable_lock_y_drift,
            )
        ) else "no_strong_geometry_hints",
        "sampleCount": len(frames),
        "bodySpan": body_span,
        "forceLockPlantedFeet": force_lock_feet,
        "forceLockPlantedHands": force_lock_hands,
        "forceAutoWorldAlignmentFalse": force_disable_auto_alignment,
        "forceLockYDriftFalse": force_disable_lock_y_drift,
        "leftFootMotionRatio": left_foot_motion,
        "rightFootMotionRatio": right_foot_motion,
        "leftHandMotionRatio": left_hand_motion,
        "rightHandMotionRatio": right_hand_motion,
        "torsoUprightRatio": upright_ratio,
        "rootYMotionRatio": root_y_ratio,
        "stationarySupportThreshold": DETERMINISTIC_SUPPORT_STATIONARY_RATIO_THRESHOLD,
        "horizontalBodyUprightThreshold": DETERMINISTIC_HORIZONTAL_BODY_UPRIGHT_RATIO_THRESHOLD,
        "rootYMotionThreshold": DETERMINISTIC_ROOT_Y_MOTION_RATIO_THRESHOLD,
    }


def empty_deterministic_preview_settings_hint(*, reason: str, sample_count: int = 0) -> dict[str, Any]:
    return {
        "source": "deterministic_render_geometry",
        "reason": reason,
        "sampleCount": sample_count,
        "forceLockPlantedFeet": False,
        "forceLockPlantedHands": False,
        "forceAutoWorldAlignmentFalse": False,
        "forceLockYDriftFalse": False,
    }


def motion_frames_from_export_payload(export_payload: dict[str, Any]) -> list[dict[str, Any]]:
    frames_value = export_payload.get("frames")
    if not isinstance(frames_value, list):
        return []
    frames = [
        frame
        for frame in frames_value
        if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))
    ]
    if frames:
        return frames
    return [frame for frame in frames_value if isinstance(frame, dict)]


def body_span_for_frame(frame: dict[str, Any]) -> float:
    joints = frame.get("joints")
    if not isinstance(joints, dict):
        return 0.0
    points = [
        point3_to_float_list(point)
        for point in joints.values()
        if is_point3(point)
    ]
    return body_span_for_points(points) if points else 0.0


def representative_joint_motion_ratio(
    frames: list[dict[str, Any]],
    names: tuple[str, ...],
    *,
    body_span: float,
) -> float | None:
    points = representative_joint_points(frames, names)
    if len(points) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT or body_span <= 1e-6:
        return None
    axis_ranges = [
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    ]
    return math.sqrt(sum(axis_range * axis_range for axis_range in axis_ranges)) / body_span


def representative_joint_y_motion_ratio(
    frames: list[dict[str, Any]],
    names: tuple[str, ...],
    *,
    body_span: float,
) -> float | None:
    points = representative_joint_points(frames, names)
    if len(points) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT or body_span <= 1e-6:
        return None
    return (max(point[1] for point in points) - min(point[1] for point in points)) / body_span


def representative_joint_points(frames: list[dict[str, Any]], names: tuple[str, ...]) -> list[list[float]]:
    points: list[list[float]] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        point = representative_joint_center(joints, names)
        if point is not None:
            points.append(point)
    return points


def torso_upright_ratio(frames: list[dict[str, Any]], *, body_span: float) -> float | None:
    ratios: list[float] = []
    if body_span <= 1e-6:
        return None
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        upper = representative_joint_center(
            joints,
            ("head", "neck", "spine3", "left_shoulder", "right_shoulder"),
        )
        lower = representative_joint_center(
            joints,
            ("pelvis", "root", "hips", "left_hip", "right_hip"),
        )
        if upper is None or lower is None:
            continue
        ratios.append((upper[1] - lower[1]) / body_span)
    if len(ratios) < DETERMINISTIC_SUPPORT_MIN_SAMPLE_COUNT:
        return None
    return statistics.median(ratios)


def apply_deterministic_preview_settings_hints_to_variant(
    variant: dict[str, Any],
    *,
    base_options: dict[str, Any],
    orientation_hint: dict[str, Any],
    preview_settings_hint: dict[str, Any],
) -> dict[str, Any]:
    corrected = apply_deterministic_scene_orientation_to_variant(
        variant,
        base_options=base_options,
        orientation_hint=orientation_hint,
    )
    effective_options = {
        **base_options,
        **dict(corrected.get("options") if isinstance(corrected.get("options"), dict) else {}),
    }
    corrected_options = dict(corrected.get("options") if isinstance(corrected.get("options"), dict) else {})
    correction_reasons: list[str] = []
    if bool(preview_settings_hint.get("forceLockPlantedFeet")) and not bool(effective_options.get("lockPlantedFeet")):
        corrected_options["lockPlantedFeet"] = True
        correction_reasons.append("deterministic support geometry set lockPlantedFeet true")
    if bool(preview_settings_hint.get("forceLockPlantedHands")) and not bool(effective_options.get("lockPlantedHands")):
        corrected_options["lockPlantedHands"] = True
        correction_reasons.append("deterministic support geometry set lockPlantedHands true")
    if bool(preview_settings_hint.get("forceAutoWorldAlignmentFalse")) and bool(effective_options.get("autoWorldAlignment")):
        corrected_options["autoWorldAlignment"] = False
        correction_reasons.append("deterministic body orientation set autoWorldAlignment false")
    if bool(preview_settings_hint.get("forceLockYDriftFalse")) and bool(effective_options.get("lockYDrift")):
        corrected_options["lockYDrift"] = False
        correction_reasons.append("deterministic root motion set lockYDrift false")
    if not correction_reasons:
        return corrected
    corrected = dict(corrected)
    corrected["options"] = corrected_options
    adaptive_settings = dict(
        corrected.get("adaptivePreviewSettings")
        if isinstance(corrected.get("adaptivePreviewSettings"), dict)
        else {}
    )
    existing_reason = str(adaptive_settings.get("reason") or "").strip()
    correction_reason = "; ".join(correction_reasons)
    adaptive_settings["reason"] = (
        f"{existing_reason}; {correction_reason}"
        if existing_reason
        else correction_reason
    )
    adaptive_settings["deterministicPreviewSettings"] = preview_settings_hint
    corrected["adaptivePreviewSettings"] = adaptive_settings
    corrected["cleanupInterpretation"] = str(
        corrected_options.get("cleanupInterpretation")
        or effective_options.get("cleanupInterpretation")
        or corrected.get("cleanupInterpretation")
        or "support_lock"
    )
    return corrected


def deduplicate_preview_setting_variants(
    variants: list[dict[str, Any]],
    *,
    base_options: dict[str, Any],
    motion_tuning_enabled: bool,
) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for variant in variants:
        effective_options = {
            **base_options,
            **dict(variant.get("options") if isinstance(variant.get("options"), dict) else {}),
        }
        signature = preview_options_signature(
            effective_options,
            motion_tuning_enabled=motion_tuning_enabled,
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(variant)
    return unique


def sanitize_preview_settings_options(
    settings: dict[str, Any],
    *,
    base_options: dict[str, Any],
    motion_tuning_enabled: bool,
) -> dict[str, Any]:
    options = with_fixed_preview_camera_options(base_options)
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
    return with_fixed_preview_camera_options(options)


def vlm_visible_preview_options(options: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in options.items()
        if key not in {"cameraYawDegrees", "cameraPitchDegrees", "showBoundsHelper", "vlmReviewStyle"}
    }


def vlm_review_render_options(options: dict[str, Any]) -> dict[str, Any]:
    render_options = with_fixed_preview_camera_options(options)
    render_options["showBoundsHelper"] = False
    render_options["vlmReviewStyle"] = True
    return render_options


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
        if selected_span_covers_review_item(item, span) and not has_settings_change:
            return selected
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
            export_payload=artifact.export_payload,
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
    return effective_review_item_preview_options(
        item,
        motion_tuning_enabled=motion_tuning_enabled,
    )


def effective_review_item_preview_options(
    item: ReviewItem,
    *,
    motion_tuning_enabled: bool,
) -> dict[str, Any]:
    options = {
        **build_preview_bake_base_options(motion_tuning_enabled=motion_tuning_enabled),
        **item.settings_options,
    }
    return with_fixed_preview_camera_options(options)


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
        if selected_section_wear_skeleton_cache_is_current(
            export_payload,
            options=options,
        ) and selected_section_review_video_cache_is_current(
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
        effective_options = with_fixed_preview_camera_options(options)
        export_payload = page.evaluate(
            """({ startSeconds, endSeconds, options }) => window.exerciseMotionAutomation.bakeTimeRange(startSeconds, endSeconds, options)""",
            {
                "startSeconds": start_seconds,
                "endSeconds": end_seconds,
                "options": effective_options,
            },
        )
        effective_options, post_bake_orientation_hint, post_bake_orientation_applied = (
            deterministic_post_bake_scene_orientation_correction(
                export_payload,
                options=effective_options,
            )
        )
        if post_bake_orientation_applied:
            export_payload = page.evaluate(
                """({ startSeconds, endSeconds, options }) => window.exerciseMotionAutomation.bakeTimeRange(startSeconds, endSeconds, options)""",
                {
                    "startSeconds": start_seconds,
                    "endSeconds": end_seconds,
                    "options": effective_options,
                },
            )
        annotate_export_payload_post_bake_scene_orientation(
            export_payload,
            orientation_hint=post_bake_orientation_hint,
            applied=post_bake_orientation_applied,
        )
        export_payload["selectedSectionBakeCacheVersion"] = SELECTED_SECTION_BAKE_CACHE_VERSION
        skeleton_path.write_text(json.dumps(export_payload, indent=2), encoding="utf-8")
        frame_indices = dense_loop_review_video_frame_indices(export_payload)
        frame_data_urls = [
            page.evaluate(
                """({ frameIndex, options }) => window.exerciseMotionAutomation.renderFrame(frameIndex, options)""",
                {"frameIndex": frame_index, "options": effective_options},
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
                    "exportPayloadSignature": selected_section_export_payload_signature(export_payload),
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
        settings_options=effective_options,
        cleanup_interpretation=str(effective_options.get("cleanupInterpretation") or "support_lock"),
    )


def wear_skeleton_preview_settings_contract(
    export_payload: dict[str, Any],
    *,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missing_fields: list[str] = []
    mismatches: list[dict[str, Any]] = []
    selected_settings = export_payload.get("selectedPreviewSettings")
    config = export_payload.get("bakedPreviewConfiguration")
    wear_display = export_payload.get("wearDisplay")
    if not isinstance(selected_settings, dict):
        missing_fields.append("selectedPreviewSettings")
        selected_settings = {}
    if not isinstance(config, dict):
        missing_fields.append("bakedPreviewConfiguration")
        config = {}
    if not isinstance(wear_display, dict):
        missing_fields.append("wearDisplay")
        wear_display = {}

    required_selected_fields = (
        "fixedRoot",
        "autoWorldAlignment",
        "lockYDrift",
        "lockPlantedFeet",
        "lockPlantedHands",
        "sceneInverted",
        "cameraYawDegrees",
        "cameraPitchDegrees",
        "playbackSpeed",
    )
    required_config_fields = (
        "lockGlobalRootDrift",
        "autoWorldAlignment",
        "lockYDrift",
        "lockPlantedFeet",
        "lockPlantedHands",
        "invertScene",
        "canonicalWorldUp",
        "cameraYawDegrees",
        "cameraPitchDegrees",
        "playbackSpeed",
    )
    required_display_fields = (
        "viewYawDegrees",
        "viewPitchDegrees",
    )
    for field_name in required_selected_fields:
        if field_name not in selected_settings:
            missing_fields.append(f"selectedPreviewSettings.{field_name}")
    for field_name in required_config_fields:
        if field_name not in config:
            missing_fields.append(f"bakedPreviewConfiguration.{field_name}")
    for field_name in required_display_fields:
        if field_name not in wear_display:
            missing_fields.append(f"wearDisplay.{field_name}")
    if parse_optional_bool(config.get("canonicalWorldUp")) is not True:
        mismatches.append(
            {
                "field": "bakedPreviewConfiguration.canonicalWorldUp",
                "expected": True,
                "actual": config.get("canonicalWorldUp"),
            }
        )

    option_values = options if isinstance(options, dict) else {}
    bool_option_fields = (
        ("selectedPreviewSettings.fixedRoot", selected_settings.get("fixedRoot"), "fixedRoot"),
        ("selectedPreviewSettings.autoWorldAlignment", selected_settings.get("autoWorldAlignment"), "autoWorldAlignment"),
        ("selectedPreviewSettings.lockYDrift", selected_settings.get("lockYDrift"), "lockYDrift"),
        ("selectedPreviewSettings.lockPlantedFeet", selected_settings.get("lockPlantedFeet"), "lockPlantedFeet"),
        ("selectedPreviewSettings.lockPlantedHands", selected_settings.get("lockPlantedHands"), "lockPlantedHands"),
        ("selectedPreviewSettings.sceneInverted", selected_settings.get("sceneInverted"), "sceneInverted"),
        ("bakedPreviewConfiguration.lockGlobalRootDrift", config.get("lockGlobalRootDrift"), "fixedRoot"),
        ("bakedPreviewConfiguration.autoWorldAlignment", config.get("autoWorldAlignment"), "autoWorldAlignment"),
        ("bakedPreviewConfiguration.lockYDrift", config.get("lockYDrift"), "lockYDrift"),
        ("bakedPreviewConfiguration.lockPlantedFeet", config.get("lockPlantedFeet"), "lockPlantedFeet"),
        ("bakedPreviewConfiguration.lockPlantedHands", config.get("lockPlantedHands"), "lockPlantedHands"),
        ("bakedPreviewConfiguration.invertScene", config.get("invertScene"), "sceneInverted"),
    )
    for payload_field, payload_value, option_key in bool_option_fields:
        if option_key not in option_values:
            continue
        if parse_optional_bool(payload_value) != parse_optional_bool(option_values.get(option_key)):
            mismatches.append(
                {
                    "field": payload_field,
                    "expectedOption": option_key,
                    "expected": option_values.get(option_key),
                    "actual": payload_value,
                }
            )

    numeric_option_fields = (
        ("selectedPreviewSettings.cameraYawDegrees", selected_settings.get("cameraYawDegrees"), "cameraYawDegrees"),
        ("selectedPreviewSettings.cameraPitchDegrees", selected_settings.get("cameraPitchDegrees"), "cameraPitchDegrees"),
        ("selectedPreviewSettings.playbackSpeed", selected_settings.get("playbackSpeed"), "playbackSpeed"),
        ("bakedPreviewConfiguration.cameraYawDegrees", config.get("cameraYawDegrees"), "cameraYawDegrees"),
        ("bakedPreviewConfiguration.cameraPitchDegrees", config.get("cameraPitchDegrees"), "cameraPitchDegrees"),
        ("bakedPreviewConfiguration.playbackSpeed", config.get("playbackSpeed"), "playbackSpeed"),
        ("wearDisplay.viewYawDegrees", wear_display.get("viewYawDegrees"), "cameraYawDegrees"),
        ("wearDisplay.viewPitchDegrees", wear_display.get("viewPitchDegrees"), "cameraPitchDegrees"),
    )
    for payload_field, payload_value, option_key in numeric_option_fields:
        if option_key not in option_values:
            continue
        if not floats_close(payload_value, option_values.get(option_key)):
            mismatches.append(
                {
                    "field": payload_field,
                    "expectedOption": option_key,
                    "expected": option_values.get(option_key),
                    "actual": payload_value,
                }
            )

    passed = not missing_fields and not mismatches
    return {
        "passed": passed,
        "source": "html_preview_export" if passed else "legacy_or_incomplete_export",
        "missingFields": missing_fields,
        "mismatches": mismatches,
        "selectedPreviewSettings": selected_settings if selected_settings else None,
        "bakedPreviewConfiguration": config if config else None,
        "wearDisplay": wear_display if wear_display else None,
    }


def selected_section_wear_skeleton_cache_is_current(
    export_payload: dict[str, Any],
    *,
    options: dict[str, Any],
) -> bool:
    if int(export_payload.get("selectedSectionBakeCacheVersion") or 0) != SELECTED_SECTION_BAKE_CACHE_VERSION:
        return False
    config = export_payload.get("bakedPreviewConfiguration")
    wear_display = export_payload.get("wearDisplay")
    selected_settings = export_payload.get("selectedPreviewSettings")
    if not isinstance(config, dict) or not isinstance(wear_display, dict) or not isinstance(selected_settings, dict):
        return False
    if parse_optional_bool(config.get("canonicalWorldUp")) is not True:
        return False

    bool_checks = {
        "autoWorldAlignment": "autoWorldAlignment",
        "lockYDrift": "lockYDrift",
        "lockPlantedFeet": "lockPlantedFeet",
        "lockPlantedHands": "lockPlantedHands",
    }
    selected_bool_checks = {
        "fixedRoot": "fixedRoot",
        "autoWorldAlignment": "autoWorldAlignment",
        "lockYDrift": "lockYDrift",
        "lockPlantedFeet": "lockPlantedFeet",
        "lockPlantedHands": "lockPlantedHands",
        "sceneInverted": "sceneInverted",
    }
    config_bool_checks = {
        "lockGlobalRootDrift": "fixedRoot",
        "invertScene": "sceneInverted",
    }
    for payload_key, option_key in bool_checks.items():
        if parse_optional_bool(config.get(payload_key)) != parse_optional_bool(options.get(option_key)):
            return False
    for payload_key, option_key in config_bool_checks.items():
        if parse_optional_bool(config.get(payload_key)) != parse_optional_bool(options.get(option_key)):
            return False
    for payload_key, option_key in selected_bool_checks.items():
        if parse_optional_bool(selected_settings.get(payload_key)) != parse_optional_bool(options.get(option_key)):
            return False

    number_checks = {
        "playbackSpeed": "playbackSpeed",
        "cameraYawDegrees": "cameraYawDegrees",
        "cameraPitchDegrees": "cameraPitchDegrees",
    }
    for payload_key, option_key in number_checks.items():
        if not floats_close(config.get(payload_key), options.get(option_key)):
            return False
        if not floats_close(selected_settings.get(payload_key), options.get(option_key)):
            return False

    return (
        floats_close(wear_display.get("viewYawDegrees"), options.get("cameraYawDegrees"))
        and floats_close(wear_display.get("viewPitchDegrees"), options.get("cameraPitchDegrees"))
    )


def floats_close(left: Any, right: Any, *, tolerance: float = 1e-4) -> bool:
    parsed_left = parse_optional_float(left)
    parsed_right = parse_optional_float(right)
    if parsed_left is None or parsed_right is None:
        return parsed_left is None and parsed_right is None
    return abs(parsed_left - parsed_right) <= tolerance


def selected_section_export_payload_signature(export_payload: dict[str, Any]) -> str:
    relevant_payload = {
        "selectedSectionBakeCacheVersion": export_payload.get("selectedSectionBakeCacheVersion"),
        "fps": export_payload.get("fps"),
        "frameCount": export_payload.get("frameCount"),
        "durationSec": export_payload.get("durationSec"),
        "source": export_payload.get("source"),
        "loop": export_payload.get("loop"),
        "selectedPreviewSettings": export_payload.get("selectedPreviewSettings"),
        "bakedPreviewConfiguration": export_payload.get("bakedPreviewConfiguration"),
        "wearDisplay": export_payload.get("wearDisplay"),
        "bounds": export_payload.get("bounds"),
    }
    encoded = json.dumps(relevant_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
        and metadata.get("exportPayloadSignature") == selected_section_export_payload_signature(export_payload)
    )


def first_float(*values: Any) -> float | None:
    for value in values:
        parsed = parse_optional_float(value)
        if parsed is not None:
            return parsed
    return None


def optional_float_or_default(value: Any, default: float) -> float:
    parsed = parse_optional_float(value)
    return default if parsed is None else parsed


def with_fixed_preview_camera_options(options: dict[str, Any]) -> dict[str, Any]:
    fixed = dict(options)
    fixed["cameraYawDegrees"] = FIXED_PREVIEW_CAMERA_YAW_DEGREES
    fixed["cameraPitchDegrees"] = FIXED_PREVIEW_CAMERA_PITCH_DEGREES
    return fixed


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
        "cameraYawDegrees": FIXED_PREVIEW_CAMERA_YAW_DEGREES,
        "cameraPitchDegrees": FIXED_PREVIEW_CAMERA_PITCH_DEGREES,
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


def adaptive_preview_settings_contact_sheet_frame_count(review_frames: int) -> int:
    try:
        requested = int(review_frames)
    except (TypeError, ValueError):
        requested = DEFAULT_REVIEW_FRAMES
    requested = max(1, requested)
    return max(
        ADAPTIVE_PREVIEW_SETTINGS_MIN_CONTACT_SHEET_FRAMES,
        min(ADAPTIVE_PREVIEW_SETTINGS_MAX_CONTACT_SHEET_FRAMES, requested),
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


def frame_timestamps_for_indices(export_payload: dict[str, Any], frame_indices: list[int]) -> list[float]:
    export_frames = export_payload.get("frames") if isinstance(export_payload, dict) else None
    if not isinstance(export_frames, list):
        return []
    fps = parse_export_fps(export_payload)
    timestamps: list[float] = []
    for frame_index in frame_indices:
        frame = (
            export_frames[frame_index]
            if 0 <= frame_index < len(export_frames) and isinstance(export_frames[frame_index], dict)
            else {}
        )
        timestamps.append(
            frame_time_seconds(
                frame,
                fallback_index=frame_index,
                fps=fps,
            )
        )
    return timestamps


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
    vlm_review_style: bool = False,
) -> list[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for dense LLM review rendering.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    options = (
        vlm_review_render_options(item.settings_options)
        if vlm_review_style
        else with_fixed_preview_camera_options(item.settings_options)
    )
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
            frame_timestamps = frame_timestamps_for_indices(
                export_payload if isinstance(export_payload, dict) else {},
                frame_indices,
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
    write_review_contact_sheet_from_data_urls(
        frame_data_urls,
        contact_sheet_path,
        timestamps=frame_timestamps,
        sequence_labels=True,
    )
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
    render_window = source_video_window_for_review_window(
        item=item,
        source_video_path=source_video_path,
        window=window,
    )
    return render_video_window_contact_sheet(
        video_path=source_video_path,
        window=render_window,
        output_dir=output_dir,
        frame_count=frame_count,
    )


def source_video_window_for_review_window(
    *,
    item: ReviewItem,
    source_video_path: Path,
    window: DetectionWindow,
) -> DetectionWindow:
    source_duration = source_video_duration_seconds(source_video_path)
    review_start = max(0.0, item.loop_start_seconds)
    review_end = item.loop_end_seconds if item.loop_end_seconds > review_start else review_start + item.duration_sec
    review_duration = max(0.0, review_end - review_start)
    if source_duration <= 0.0 or review_duration <= 0.0:
        return window
    duration_delta = abs(source_duration - review_duration) / max(source_duration, review_duration)
    if duration_delta < 0.08:
        return window
    scale = source_duration / review_duration
    relative_start = max(0.0, window.start_seconds - review_start)
    relative_end = max(relative_start, window.end_seconds - review_start)
    mapped_start = max(0.0, min(source_duration, relative_start * scale))
    mapped_end = max(mapped_start, min(source_duration, relative_end * scale))
    if mapped_end - mapped_start < 0.05:
        return window
    return DetectionWindow(
        index=window.index,
        start_seconds=mapped_start,
        end_seconds=mapped_end,
    )


def source_video_duration_seconds(source_video_path: Path) -> float:
    try:
        return max(0.0, float(read_basic_video_metadata(source_video_path).duration_seconds))
    except Exception:
        return 0.0


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
            contact_sheet_sequence_labels=True,
            output_dir=output_dir,
        )
    except Exception:
        return []


def write_review_contact_sheet_from_data_urls(
    data_urls: list[str],
    output_path: Path,
    *,
    timestamps: list[float] | None = None,
    sequence_labels: bool = False,
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
        timestamp = timestamps[len(frames)] if timestamps is not None and len(timestamps) > len(frames) else None
        if sequence_labels or timestamp is not None:
            draw_contact_sheet_tile_label(
                cv2,
                image,
                frame_number=len(frames) + 1,
                total_frames=len(data_urls),
                timestamp_seconds=timestamp if timestamp is not None else 0.0,
                sequence_labels=sequence_labels,
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


def frange_inclusive(start: float, stop: float, step: float) -> list[float]:
    if step <= 0:
        return [start]
    values: list[float] = []
    value = start
    while value <= stop + 1e-6:
        values.append(value)
        value += step
    if not values or abs(values[-1] - stop) > 1e-6:
        values.append(stop)
    return values


def source_cut_min_candidate_duration_seconds(
    *,
    chunk_estimate: Any,
    exercise_motion_contract: dict[str, Any] | None,
) -> float:
    estimated_min = parse_optional_float(getattr(chunk_estimate, "rep_duration_min_sec", None))
    estimated_max = parse_optional_float(getattr(chunk_estimate, "rep_duration_max_sec", None))
    floor = max(
        SOURCE_CUT_ROBUST_MIN_SECONDS,
        (estimated_min or SOURCE_CUT_ROBUST_MIN_SECONDS) * SOURCE_CUT_ROBUST_MIN_ESTIMATED_DURATION_RATIO,
    )
    if observable_motion_spec_requires_return(exercise_motion_contract):
        floor = max(
            floor,
            SOURCE_WINDOW_FULL_CYCLE_MIN_SECONDS,
            (estimated_min or SOURCE_WINDOW_FULL_CYCLE_MIN_SECONDS)
            * SOURCE_WINDOW_FULL_CYCLE_MIN_ESTIMATED_DURATION_RATIO,
        )
    if estimated_max is not None and estimated_max > 0:
        floor = min(floor, estimated_max)
    return max(SOURCE_CUT_REFINEMENT_MIN_SECONDS, floor)


def build_source_video_pyramid_candidate_windows(
    *,
    window: DetectionWindow,
    chunk_estimate: Any,
    min_duration_floor_seconds: float,
) -> list[SourceWindowCandidateSpec]:
    duration = max(0.0, window.end_seconds - window.start_seconds)
    if duration <= 0.5:
        return []
    if duration + 1e-6 < min_duration_floor_seconds:
        return []
    rep_min = parse_optional_float(getattr(chunk_estimate, "rep_duration_min_sec", None))
    rep_max = parse_optional_float(getattr(chunk_estimate, "rep_duration_max_sec", None))
    estimated_min = rep_min or min(duration, SOURCE_CUT_ROBUST_MIN_SECONDS)
    robust_floor = max(
        min_duration_floor_seconds,
        min(duration, estimated_min * SOURCE_CUT_ROBUST_MIN_ESTIMATED_DURATION_RATIO),
    )
    if rep_max is not None and rep_max > 0:
        robust_floor = min(duration, max(robust_floor, min(rep_max, duration) * 0.55))

    target_durations: list[float] = []
    candidate_duration = duration
    while candidate_duration > robust_floor + 0.10:
        target_durations.append(candidate_duration)
        next_duration = candidate_duration * SOURCE_CUT_PROGRESSIVE_SHRINK_FACTOR
        if next_duration >= candidate_duration - 0.05:
            break
        candidate_duration = next_duration
    target_durations.append(robust_floor)
    unique_durations: list[float] = []
    for candidate_duration in target_durations:
        rounded = round(min(duration, max(robust_floor, candidate_duration)), 2)
        if all(abs(rounded - existing) > 0.1 for existing in unique_durations):
            unique_durations.append(rounded)
    unique_durations.sort(reverse=True)

    specs: list[SourceWindowCandidateSpec] = []
    seen: set[tuple[float, float]] = set()

    def append_window(
        start: float,
        end: float,
        *,
        level_index: int,
        level_duration: float,
        level_ratio: float,
        stride_seconds: float,
        position_index: int,
        position_count: int,
    ) -> None:
        start = max(window.start_seconds, min(window.end_seconds, start))
        end = max(start, min(window.end_seconds, end))
        if end - start + 1e-6 < robust_floor:
            return
        key = (round(start, 2), round(end, 2))
        if key in seen:
            return
        seen.add(key)
        specs.append(
            SourceWindowCandidateSpec(
                window=DetectionWindow(index=len(specs), start_seconds=key[0], end_seconds=key[1]),
                chunking={
                    "strategy": "progressive_multiscale_sliding",
                    "levelIndex": level_index,
                    "levelDurationSeconds": round(level_duration, 3),
                    "levelRatio": round(level_ratio, 4),
                    "shrinkFactor": SOURCE_CUT_PROGRESSIVE_SHRINK_FACTOR,
                    "strideSeconds": round(stride_seconds, 3),
                    "strideRatio": SOURCE_CUT_PROGRESSIVE_STRIDE_RATIO,
                    "maxWindowsPerLevel": SOURCE_CUT_PROGRESSIVE_MAX_WINDOWS_PER_LEVEL,
                    "positionIndex": position_index,
                    "positionCount": position_count,
                    "parentStartSeconds": window.start_seconds,
                    "parentEndSeconds": window.end_seconds,
                    "parentDurationSeconds": round(duration, 3),
                    "minDurationFloorSeconds": round(robust_floor, 3),
                },
            )
        )

    for level_index, candidate_duration in enumerate(unique_durations):
        available = max(0.0, duration - candidate_duration)
        level_ratio = candidate_duration / duration if duration > 0.0 else 1.0
        if available <= 1e-6:
            offsets = [0.0]
            stride_seconds = 0.0
        else:
            requested_stride = max(0.25, candidate_duration * SOURCE_CUT_PROGRESSIVE_STRIDE_RATIO)
            capped_stride = max(
                requested_stride,
                available / max(1, SOURCE_CUT_PROGRESSIVE_MAX_WINDOWS_PER_LEVEL - 1),
            )
            stride_seconds = min(available, capped_stride)
            offsets = []
            offset = 0.0
            while offset < available - 1e-6:
                offsets.append(offset)
                offset += stride_seconds
            offsets.append(available)
        deduped_offsets: list[float] = []
        for offset in offsets:
            rounded_offset = round(max(0.0, min(available, offset)), 2)
            if rounded_offset not in deduped_offsets:
                deduped_offsets.append(rounded_offset)
        for position_index, offset in enumerate(deduped_offsets):
            start = window.start_seconds + offset
            append_window(
                start,
                start + candidate_duration,
                level_index=level_index,
                level_duration=candidate_duration,
                level_ratio=level_ratio,
                stride_seconds=stride_seconds,
                position_index=position_index,
                position_count=len(deduped_offsets),
            )

    return [
        SourceWindowCandidateSpec(
            window=DetectionWindow(
                index=index,
                start_seconds=spec.window.start_seconds,
                end_seconds=spec.window.end_seconds,
            ),
            chunking=spec.chunking,
        )
        for index, spec in enumerate(specs)
    ]


def build_source_cut_candidate_windows(
    *,
    window: DetectionWindow,
    chunk_estimate: Any,
    max_candidates: int | None = None,
    min_estimated_duration_ratio: float = MOVEMENT_CUT_MIN_ESTIMATED_DURATION_RATIO,
    min_duration_floor_seconds: float | None = None,
) -> list[DetectionWindow]:
    duration = max(0.0, window.end_seconds - window.start_seconds)
    if duration <= 0.5:
        return []
    if min_duration_floor_seconds is not None and duration + 1e-6 < min_duration_floor_seconds:
        return []
    candidate_limit = None if max_candidates is None or max_candidates <= 0 else max_candidates
    rep_min = parse_optional_float(getattr(chunk_estimate, "rep_duration_min_sec", None))
    rep_max = parse_optional_float(getattr(chunk_estimate, "rep_duration_max_sec", None))
    estimated_min_duration = rep_min or min(duration, 2.0)
    min_estimated_duration_ratio = max(0.0, float(min_estimated_duration_ratio))
    estimated_floor = estimated_min_duration * min_estimated_duration_ratio
    if min_estimated_duration_ratio >= 1.0:
        ratio_min_duration = max(SOURCE_CUT_REFINEMENT_MIN_SECONDS, estimated_floor)
    else:
        ratio_min_duration = max(
            SOURCE_CUT_REFINEMENT_MIN_SECONDS,
            min(estimated_min_duration, estimated_floor),
        )
    configured_floor = (
        SOURCE_CUT_REFINEMENT_MIN_SECONDS
        if min_duration_floor_seconds is None
        else max(SOURCE_CUT_REFINEMENT_MIN_SECONDS, float(min_duration_floor_seconds))
    )
    min_duration = min(duration, max(configured_floor, ratio_min_duration))
    max_duration = min(duration, max(min_duration, rep_max or duration))
    target_duration = min(max_duration, max(min_duration, (min_duration + max_duration) * 0.5))
    candidate_durations = [
        target_duration,
        min_duration,
        max(min_duration, estimated_min_duration * 0.75),
        max(min_duration, estimated_min_duration),
        max(min_duration, target_duration * 0.8),
        min(max_duration, target_duration * 1.2),
        max_duration,
    ]
    ladder_duration = min_duration
    while ladder_duration < duration:
        candidate_durations.append(ladder_duration)
        ladder_duration *= 1.25
    candidate_durations.append(duration)
    unique_durations: list[float] = []
    for candidate_duration in candidate_durations:
        rounded = round(min(duration, max(SOURCE_CUT_REFINEMENT_MIN_SECONDS, candidate_duration)), 2)
        if all(abs(rounded - existing) > 0.1 for existing in unique_durations):
            unique_durations.append(rounded)
    unique_durations.sort()

    windows: list[DetectionWindow] = []
    seen: set[tuple[float, float]] = set()
    short_window_limit = None if candidate_limit is None else max(0, candidate_limit - 1)

    def append_window(start: float, end: float) -> bool:
        if end - start < SOURCE_CUT_REFINEMENT_MIN_SECONDS:
            return False
        key = (round(start, 2), round(end, 2))
        if key in seen:
            return False
        seen.add(key)
        windows.append(DetectionWindow(index=len(windows), start_seconds=key[0], end_seconds=key[1]))
        return True

    for candidate_duration in unique_durations:
        if short_window_limit == 0 or (
            short_window_limit is not None and len(windows) >= short_window_limit
        ):
            break
        available = max(0.0, duration - candidate_duration)
        step = max(0.25, candidate_duration * 0.50)
        starts = [
            window.start_seconds + offset
            for offset in frange_inclusive(0.0, available, step)
        ]
        starts.append(window.end_seconds - candidate_duration)
        for start in starts:
            if short_window_limit is not None and len(windows) >= short_window_limit:
                break
            start = max(window.start_seconds, min(window.end_seconds - candidate_duration, start))
            end = min(window.end_seconds, start + candidate_duration)
            append_window(start, end)

    append_window(window.start_seconds, window.end_seconds)
    if candidate_limit is not None and len(windows) > candidate_limit:
        windows = windows[: max(0, candidate_limit - 1)] + [windows[-1]]
    return [
        DetectionWindow(index=index, start_seconds=candidate.start_seconds, end_seconds=candidate.end_seconds)
        for index, candidate in enumerate(windows)
    ]


def build_source_cut_candidate_choice_prompt(
    *,
    exercise_name: str,
    candidate_title: str,
    candidates: list[SourceCutCandidate],
    exercise_motion_contract: dict[str, Any] | None = None,
) -> str:
    candidate_lines = [
        f"- Candidate {candidate.candidate_id}: {candidate.window.start_seconds:.2f}s to {candidate.window.end_seconds:.2f}s."
        for candidate in candidates
    ]
    contract_section = build_source_cut_exercise_contract_prompt_section(exercise_motion_contract)
    return (
        "You are classifying candidate source-video cuts for an exercise animation.\n"
        f"Target exercise: {exercise_name}.\n"
        f"Candidate video title: {candidate_title}.\n"
        f"{contract_section}"
        "Each attached chronological contact sheet is one candidate source-video window. "
        f"{CONTACT_SHEET_READING_INSTRUCTIONS}"
        "Attachments are in this exact order:\n"
        + "\n".join(candidate_lines)
        + "\n\nScore each candidate independently. "
        "Use the candidate id exactly as shown in the attachment list, for example A, B, or C; do not write 'Candidate A'. "
        "The code owns candidate selection and will prefer a high-confidence padded candidate that passes all thresholds after every candidate in this set is scored. "
        "A candidate is suitable only if it contains the complete useful target movement with the start posture, full action path, finish/return posture, and no setup, reset, idle, title-card, talking, instruction, or filler content. "
        "Do not reward ultra-tight cuts; a slightly wider window with the full start, action, and return context is better than a brittle tiny fragment. "
        "First score whether the visible movement is the exact target exercise from the contact-sheet frames alone. "
        "Ignore written labels, captions, arrows, diagrams, and instruction text when deciding movement identity or completeness; use the visible human motion only. "
        "If the target exercise name combines actions with words such as 'and' or '/' or otherwise names multiple phases, the visible body must perform all named actions/phases in one continuous movement. A candidate showing only one named phase is partial_movement. "
        "If the generated contract mentions return-to-start, full cycle, or a loop-like return phase, interpret that as requiring both directions of the main loaded movement; do not require an extra repetition or extra return after the normal finish posture is already reached. "
        "The visible biomechanics must match the target: body path, primary joint action, support/stance/body position, grip or implement use, equipment interaction, and resistance direction. "
        "Do not accept a candidate just because the title names the exercise, the athlete touches similar equipment, the start posture looks similar, or the clip shows a related regression, assistance machine, station demo, hold, stretch, or variation. "
        "Score exercise_match from 0.0 to 1.0 for exact visible movement identity: 1.0 means exact target mechanics, 0.75 means clearly the target with minor ambiguity, 0.5 means related but not exact, and 0.0 means unrelated. "
        "Score full_movement from 0.0 to 1.0 for how completely one target movement/cycle is visible. For repeated gym movements, a one-way lowering-only, raising-only, static hold, lockout-only, setup-only, or reset-only fragment must score low. "
        "Score start_visible and finish_visible from 0.0 to 1.0 for whether the meaningful loaded start posture and finish/return posture are actually visible in this candidate. "
        "Score setup_or_filler from 0.0 to 1.0 where 0.0 means no visible setup/filler and 1.0 means mostly setup, talking, title-card, idle, reset, or unrelated material. "
        "Score source_quality from 0.0 to 1.0 for real source footage usefulness: a clearly real person, readable movement, little obstruction, and no synthetic/motion-preview subject should be high. Animated text, timers, captions, title graphics, logos, or overlays on real footage are not a source-quality failure by themselves. "
        "Use confidence from 0.0 to 1.0 for your certainty in the scorecard. "
        "Do not trust the video title when the contact sheet contradicts it; judge only the attached source-window frames. "
        "If every candidate is partial, unclear, mostly static, setup-only, reset-only, or only shows one phase of the movement, score every candidate accordingly; do not choose the least-bad candidate. "
        "Do not invent timestamps, frame numbers, selected candidate IDs, or chain-of-thought. "
        "reject must use only these fixed tags: wrong_exercise, partial_movement, start_not_visible, finish_not_visible, setup_or_filler, low_source_quality, low_confidence, synthetic_subject, unclear. Use [] when no tag applies. "
        "note must be one short sentence with at most 10 words.\n"
        "Return JSON only with this schema: {\"candidates\": [{\"id\": string, \"exercise_match\": number_0_to_1, \"full_movement\": number_0_to_1, \"start_visible\": number_0_to_1, \"finish_visible\": number_0_to_1, \"setup_or_filler\": number_0_to_1, \"source_quality\": number_0_to_1, \"confidence\": number_0_to_1, \"reject\": [string], \"note\": string}]}. "
        "Report the fields from visual evidence only; code applies thresholds, retries, and failure handling."
    )


def build_source_cut_exercise_contract_prompt_section(contract: dict[str, Any] | None) -> str:
    prompt_contract = exercise_motion_contract_for_prompt(contract)
    if prompt_contract is None:
        return ""
    return (
        "Exercise-specific source identity guidance. Use this only to judge whether visible movement is the requested exercise. "
        "Reject windows that show a wrong variant, setup-only content, or a partial movement according to this guidance. "
        "Do not add camera, crop, person-count, or exact timestamp duties.\n"
        f"{exercise_motion_contract_prompt_body(prompt_contract)}\n"
    )


def normalize_source_cut_candidate_id(value: object) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("CANDIDATE "):
        text = text[len("CANDIDATE ") :].strip()
    return re.sub(r"[^A-Z0-9_-]", "", text)


def source_cut_candidate_id_for_index(index: int) -> str:
    value = max(0, int(index))
    parts: list[str] = []
    while True:
        value, remainder = divmod(value, 26)
        parts.append(chr(ord("A") + remainder))
        if value == 0:
            break
        value -= 1
    return "".join(reversed(parts))


def build_movement_cut_candidate_choice_prompt(
    *,
    exercise_name: str,
    candidate_title: str,
    candidates: list[SourceCutCandidate],
    exercise_motion_contract: dict[str, Any] | None = None,
    minimum_complete_duration_seconds: float | None = None,
) -> str:
    candidate_lines = [
        f"- Candidate {candidate.candidate_id}: {candidate.window.start_seconds:.2f}s to {candidate.window.end_seconds:.2f}s."
        for candidate in candidates
    ]
    contract_section = build_movement_cut_exercise_motion_contract_prompt_section(exercise_motion_contract)
    duration_floor_section = (
        f"A complete movement should normally be at least {minimum_complete_duration_seconds:.2f}s for this exercise; "
        "treat shorter candidates as partial unless the full start, action path, and finish are unmistakably visible. "
        if minimum_complete_duration_seconds is not None and minimum_complete_duration_seconds > 0.0
        else ""
    )
    return (
        "Classify candidate movement cuts from the attached source-video contact sheets.\n"
        f"Target exercise: {exercise_name}.\n"
        f"Candidate video title: {candidate_title}.\n"
        + contract_section
        + duration_floor_section
        +
        "Each attachment is one chronological candidate window. "
        f"{CONTACT_SHEET_READING_INSTRUCTIONS}"
        "Attachments are in this exact order:\n"
        + "\n".join(candidate_lines)
        + "\n\nClassify each candidate independently. "
        "The code will choose the shortest passing candidate, so your job is only to say whether each candidate contains one complete clean target-exercise movement. "
        "A passing candidate must contain the meaningful start position, full action path, and controlled finish of one target movement. "
        "The visible movement must match the target exercise, not merely use related equipment or look athletic. "
        "If the generated contract mentions return-to-start, full cycle, or a loop-like return phase, interpret that as requiring both directions of the main loaded movement; do not require an extra repetition or extra return after the normal finish posture is already reached. "
        "If you would describe the visible motion as a different exercise, set target_exercise_match false and include wrong_exercise. "
        "Reject partial one-way fragments, setup-only/reset-only clips, and longer clips with unnecessary setup, idle frames, reset, or the start of another repetition. "
        "If any visible frames show preparation before the loaded start posture, such as walking in, sitting or lying into position, reaching for equipment, unracking/racking, adjusting stance or grip, waiting, or resetting after a rep, set includes_setup_or_reset true and clean_boundaries false. "
        "Do not require the first and last pose to match; this is a clean movement clip, not necessarily a loop. "
        "Do not invent timestamps or unshown frame numbers. "
        "Do not return selected_candidate_id; return per-candidate classifications only. "
        "If no candidate contains a complete clean movement, mark every candidate as not containing the complete target movement.\n"
        "Use confidence from 0.0 to 1.0: 0.90-1.00 excellent, 0.75-0.89 usable, 0.50-0.74 borderline, below 0.50 incomplete or poorly bounded. "
        "Keep reason to 8 words or fewer. "
        "Return JSON only with keys: {\"candidate_results\": [{\"candidate_id\": string, \"contains_complete_target_movement\": boolean, \"target_exercise_match\": boolean, \"target_exercise_match_score\": number_0_to_1, \"clean_boundaries\": boolean, \"includes_setup_or_reset\": boolean, \"confidence\": number_0_to_1, \"blocking_issues\": [\"none|wrong_exercise|partial_movement|setup_or_talking|setup_or_reset|mostly_setup|bad_boundary|unclear\"], \"reason\": string}]}."
    )


def build_movement_cut_exercise_motion_contract_prompt_section(contract: dict[str, Any] | None) -> str:
    prompt_contract = exercise_motion_contract_for_prompt(contract)
    if prompt_contract is None:
        return ""
    return (
        "Movement-cut exercise guidance. Use this exercise-specific guidance to decide whether a candidate window contains the actual full target movement. "
        "A valid cut should include the meaningful start, full action path, and natural finish/return described by the guidance. "
        "Reject windows that only show setup, only one phase, or a wrong variant. "
        "If no candidate window satisfies the guidance, choose null.\n"
        f"{exercise_motion_contract_prompt_body(prompt_contract)}\n"
    )


def build_final_output_skeleton_contract_prompt_section(contract: dict[str, Any] | None) -> str:
    prompt_contract = exercise_motion_contract_for_prompt(contract)
    if prompt_contract is None:
        return ""
    skeleton_guidance = final_output_skeleton_guidance_from_contract(prompt_contract)
    if not skeleton_guidance:
        return ""
    return (
        "Final-output skeleton guidance. Use only this skeleton-specific guidance. "
        "Use it to judge whether the body-only skeleton looks like a reasonable generated version of the target exercise, not whether it satisfies every possible coaching or biomechanics detail. "
        "Treat this guidance as a broad plausibility aid, not a strict checklist. "
        "External objects and scene geometry may be absent from the skeleton preview, so evaluate the visible body motion, broad phase order, and wrong-variant warnings without requiring exact equipment contact, object clearance, precise angles, or perfect end ranges. "
        "Do not apply source-video completeness or endpoint criteria to the generated skeleton.\n"
        f"Skeleton: {skeleton_guidance}\n"
    )


SKELETON_CONTRACT_SECTION_LABELS = ("skeleton", "source", "complete", "reject", "notes")


def final_output_skeleton_guidance_from_contract(prompt_contract: dict[str, Any]) -> str:
    advisory_text = cleaned_contract_advisory_text(prompt_contract.get("advisoryText"))
    skeleton_line = contract_labeled_section(advisory_text, "Skeleton", SKELETON_CONTRACT_SECTION_LABELS)
    if skeleton_line:
        return skeleton_line
    if advisory_text:
        return truncate_text(advisory_text, 500)
    structured_guidance = cleaned_contract_string(prompt_contract.get("skeletonGuidance"), 400)
    if structured_guidance:
        return structured_guidance
    return ""


def contract_labeled_section(text: str, label: str, labels: tuple[str, ...]) -> str:
    if not text:
        return ""
    alternatives = "|".join(re.escape(item) for item in labels)
    pattern = re.compile(
        rf"(?:^|\s){re.escape(label)}\s*:\s*(.*?)(?=(?:\s(?:{alternatives})\s*:)|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return ""
    return truncate_text(re.sub(r"\s+", " ", match.group(1)).strip(), 500) or ""


def exercise_motion_contract_for_review_item(item: ReviewItem, ranking: LoopRanking | None) -> dict[str, Any] | None:
    prompt_contract = exercise_motion_contract_from_candidate(item.candidate)
    if prompt_contract is not None:
        return prompt_contract
    ranking_payload = ranking.payload if ranking is not None and isinstance(ranking.payload, dict) else {}
    contract = ranking_payload.get("exerciseMotionContract")
    prompt_contract = exercise_motion_contract_for_prompt(contract if isinstance(contract, dict) else None)
    if prompt_contract is not None:
        return prompt_contract
    segment_selection_path = item.candidate_workspace / "segment_detection" / "segment_selection.json"
    if not segment_selection_path.exists():
        return None
    try:
        segment_payload = json.loads(segment_selection_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(segment_payload, dict):
        return None
    contract = segment_payload.get("exerciseMotionContract")
    prompt_contract = exercise_motion_contract_for_prompt(contract if isinstance(contract, dict) else None)
    if prompt_contract is not None:
        return prompt_contract
    for stage in segment_payload.get("preWhamSourceValidationStages") or []:
        if not isinstance(stage, dict):
            continue
        contract = stage.get("exerciseMotionContract")
        prompt_contract = exercise_motion_contract_for_prompt(contract if isinstance(contract, dict) else None)
        if prompt_contract is not None:
            return prompt_contract
    return None


def exercise_skeleton_contract_for_review_item(item: ReviewItem, ranking: LoopRanking | None) -> dict[str, Any] | None:
    prompt_contract = exercise_skeleton_contract_from_candidate(item.candidate)
    if prompt_contract is not None:
        return prompt_contract
    ranking_payload = ranking.payload if ranking is not None and isinstance(ranking.payload, dict) else {}
    contract = ranking_payload.get("exerciseSkeletonContract")
    prompt_contract = exercise_motion_contract_for_prompt(contract if isinstance(contract, dict) else None)
    if prompt_contract is not None:
        return prompt_contract
    segment_selection_path = item.candidate_workspace / "segment_detection" / "segment_selection.json"
    if not segment_selection_path.exists():
        return None
    try:
        segment_payload = json.loads(segment_selection_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(segment_payload, dict):
        return None
    contract = segment_payload.get("exerciseSkeletonContract")
    prompt_contract = exercise_motion_contract_for_prompt(contract if isinstance(contract, dict) else None)
    if prompt_contract is not None:
        return prompt_contract
    for stage in segment_payload.get("preWhamSourceValidationStages") or []:
        if not isinstance(stage, dict):
            continue
        contract = stage.get("exerciseSkeletonContract")
        prompt_contract = exercise_motion_contract_for_prompt(contract if isinstance(contract, dict) else None)
        if prompt_contract is not None:
            return prompt_contract
    return None


def exercise_motion_contract_from_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    candidate_contract = candidate.get("exerciseMotionContract")
    prompt_contract = exercise_motion_contract_for_prompt(candidate_contract if isinstance(candidate_contract, dict) else None)
    if prompt_contract is not None:
        return prompt_contract

    payload = candidate.get("visionPayload")
    if not isinstance(payload, dict):
        return None
    for key in ("exerciseMotionContract",):
        contract = payload.get(key)
        prompt_contract = exercise_motion_contract_for_prompt(contract if isinstance(contract, dict) else None)
        if prompt_contract is not None:
            return prompt_contract
    advisory_payload = payload.get("advisoryVlmSourceReview")
    if isinstance(advisory_payload, dict):
        contract = advisory_payload.get("exerciseMotionContract")
        prompt_contract = exercise_motion_contract_for_prompt(contract if isinstance(contract, dict) else None)
        if prompt_contract is not None:
            return prompt_contract
    return None


def exercise_skeleton_contract_from_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    candidate_contract = candidate.get("exerciseSkeletonContract")
    prompt_contract = exercise_motion_contract_for_prompt(candidate_contract if isinstance(candidate_contract, dict) else None)
    if prompt_contract is not None:
        return prompt_contract

    payload = candidate.get("visionPayload")
    if not isinstance(payload, dict):
        return None
    contract = payload.get("exerciseSkeletonContract")
    prompt_contract = exercise_motion_contract_for_prompt(contract if isinstance(contract, dict) else None)
    if prompt_contract is not None:
        return prompt_contract
    return None


def source_cut_candidates_payload(candidates: list[SourceCutCandidate]) -> list[dict[str, Any]]:
    return [
        {
            "candidateId": candidate.candidate_id,
            "startSeconds": candidate.window.start_seconds,
            "endSeconds": candidate.window.end_seconds,
            "framePaths": [str(path) for path in candidate.frame_paths],
            "sampleFramePaths": [str(path) for path in candidate.sample_frame_paths],
            "visualIntegrity": candidate.visual_integrity,
            "posePrefilter": candidate.pose_prefilter,
            "motionCoverage": candidate.motion_coverage,
            **({"chunking": candidate.chunking} if candidate.chunking else {}),
        }
        for candidate in candidates
    ]


def source_cut_sample_frame_paths(output_dir: Path) -> list[Path]:
    return sorted(path for path in output_dir.glob("frame_*.jpg") if path.is_file())


def source_cut_visual_integrity_metrics(frame_paths: list[Path]) -> dict[str, Any]:
    if not frame_paths:
        return {
            "passed": False,
            "rejectionReasons": ["source_cut_no_sample_frames"],
            "sampleFrameCount": 0,
        }
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return {
            "passed": False,
            "rejectionReasons": ["source_cut_visual_integrity_dependencies_missing"],
            "sampleFrameCount": len(frame_paths),
        }

    samples: list[dict[str, Any]] = []
    previous_image = None
    for index, frame_path in enumerate(frame_paths):
        image = cv2.imread(str(frame_path))
        if image is None:
            samples.append({"frameIndex": index, "path": str(frame_path), "readable": False})
            continue
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        frame_diff = None
        if previous_image is not None and previous_image.shape == image.shape:
            frame_diff = float(np.mean(cv2.absdiff(image, previous_image)) / 255.0)
        previous_image = image
        samples.append(
            {
                "frameIndex": index,
                "path": str(frame_path),
                "readable": True,
                "grayMean": float(np.mean(gray)),
                "grayStd": float(np.std(gray)),
                "nonWhiteRatio": float(np.mean(np.any(image < 245, axis=2))),
                "darkRatio": float(np.mean(gray < 80)),
                "saturatedRatio": float(np.mean(hsv[:, :, 1] > 30)),
                "edgeRatio": float(np.mean(edges > 0)),
                "previousFrameDiff": frame_diff,
            }
        )

    readable = [sample for sample in samples if sample.get("readable")]
    if len(readable) < max(3, min(4, len(frame_paths))):
        return {
            "passed": False,
            "rejectionReasons": ["source_cut_too_few_readable_frames"],
            "sampleFrameCount": len(frame_paths),
            "readableFrameCount": len(readable),
            "frames": samples,
        }

    def median_metric(key: str) -> float:
        values = [float(sample[key]) for sample in readable if isinstance(sample.get(key), (int, float))]
        return float(np.median(values)) if values else 0.0

    median_gray_std = median_metric("grayStd")
    median_dark_ratio = median_metric("darkRatio")
    median_saturated_ratio = median_metric("saturatedRatio")
    median_non_white_ratio = median_metric("nonWhiteRatio")
    median_edge_ratio = median_metric("edgeRatio")
    washed_out_frames: list[int] = []
    for sample in readable:
        gray_std = float(sample["grayStd"])
        dark_ratio = float(sample["darkRatio"])
        saturated_ratio = float(sample["saturatedRatio"])
        non_white_ratio = float(sample["nonWhiteRatio"])
        edge_ratio = float(sample["edgeRatio"])
        low_contrast_outlier = gray_std < median_gray_std * 0.82
        low_dark_outlier = dark_ratio < max(0.025, median_dark_ratio * 0.40)
        low_saturation_outlier = saturated_ratio < max(0.03, median_saturated_ratio * 0.40)
        low_foreground_outlier = non_white_ratio < max(0.10, median_non_white_ratio * 0.55)
        weak_edges_outlier = edge_ratio < max(0.035, median_edge_ratio * 0.70)
        if (low_contrast_outlier and (low_dark_outlier or low_saturation_outlier or low_foreground_outlier)) or (
            low_dark_outlier and low_saturation_outlier and weak_edges_outlier
        ):
            washed_out_frames.append(int(sample["frameIndex"]))

    frame_diffs = [
        float(sample["previousFrameDiff"])
        for sample in readable
        if isinstance(sample.get("previousFrameDiff"), (int, float))
    ]
    max_frame_diff = max(frame_diffs) if frame_diffs else 0.0
    rejection_reasons: list[str] = []
    if washed_out_frames:
        rejection_reasons.append("source_cut_washed_out_or_fade_frame")
    if max_frame_diff >= 0.18:
        rejection_reasons.append("source_cut_visual_jump")
    return {
        "passed": not rejection_reasons,
        "rejectionReasons": rejection_reasons,
        "sampleFrameCount": len(frame_paths),
        "readableFrameCount": len(readable),
        "washedOutFrameIndexes": washed_out_frames,
        "maxPreviousFrameDiff": max_frame_diff,
        "medianGrayStd": median_gray_std,
        "medianDarkRatio": median_dark_ratio,
        "medianSaturatedRatio": median_saturated_ratio,
        "medianNonWhiteRatio": median_non_white_ratio,
        "medianEdgeRatio": median_edge_ratio,
        "frames": samples,
    }


def build_source_cut_candidate(
    *,
    candidate_id: str,
    candidate_window: DetectionWindow,
    contact_sheet_paths: list[Path],
    output_dir: Path,
    pose_prefilter: dict[str, Any] | None = None,
    chunking: dict[str, Any] | None = None,
) -> SourceCutCandidate | None:
    if not contact_sheet_paths:
        return None
    sample_frame_paths = source_cut_sample_frame_paths(output_dir)
    visual_integrity = source_cut_visual_integrity_metrics(sample_frame_paths)
    return SourceCutCandidate(
        candidate_id=candidate_id,
        window=candidate_window,
        frame_paths=contact_sheet_paths,
        sample_frame_paths=sample_frame_paths,
        visual_integrity=visual_integrity,
        pose_prefilter=pose_prefilter or {},
        chunking=chunking or {},
    )


def source_cut_candidate_passes_visual_integrity(candidate: SourceCutCandidate) -> bool:
    return bool(candidate.visual_integrity.get("passed"))


def source_cut_pose_valid_chunks(pose_payload: dict[str, Any] | None) -> list[dict[str, float]]:
    if not isinstance(pose_payload, dict):
        return []
    valid_chunks = pose_payload.get("validChunks")
    if not isinstance(valid_chunks, list):
        return []
    chunks: list[dict[str, float]] = []
    for item in valid_chunks:
        if not isinstance(item, dict):
            continue
        start = parse_optional_float(item.get("startSeconds"))
        end = parse_optional_float(item.get("endSeconds"))
        if start is None or end is None or end <= start:
            continue
        chunks.append(
            {
                "startSeconds": start,
                "endSeconds": end,
                "score": parse_optional_float(item.get("score")) or 0.0,
            }
        )
    return chunks


def source_cut_candidate_pose_prefilter_metrics(
    *,
    candidate_window: DetectionWindow,
    pose_payload: dict[str, Any] | None,
    source_offset_seconds: float = 0.0,
) -> dict[str, Any]:
    valid_chunks = source_cut_pose_valid_chunks(pose_payload)
    candidate_start = max(0.0, source_offset_seconds + candidate_window.start_seconds)
    candidate_end = max(candidate_start, source_offset_seconds + candidate_window.end_seconds)
    candidate_duration = max(0.0, candidate_end - candidate_start)
    if not valid_chunks:
        return {
            "enabled": False,
            "passed": True,
            "skippedReasons": ["source_cut_pose_prefilter_payload_unavailable"],
            "sourceOffsetSeconds": source_offset_seconds,
            "candidateOriginalStartSeconds": candidate_start,
            "candidateOriginalEndSeconds": candidate_end,
        }
    best_overlap = 0.0
    best_chunk: dict[str, float] | None = None
    for chunk in valid_chunks:
        overlap_start = max(candidate_start, chunk["startSeconds"])
        overlap_end = min(candidate_end, chunk["endSeconds"])
        overlap = max(0.0, overlap_end - overlap_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_chunk = chunk
    overlap_ratio = best_overlap / max(candidate_duration, 1e-6)
    passed = overlap_ratio >= 0.20 or (
        best_chunk is not None
        and candidate_start >= best_chunk["startSeconds"] - 0.25
        and candidate_end <= best_chunk["endSeconds"] + 0.25
    )
    return {
        "enabled": True,
        "passed": passed,
        "rejectionReasons": [] if passed else ["source_cut_no_yolo_pose_motion_overlap"],
        "sourceOffsetSeconds": source_offset_seconds,
        "candidateOriginalStartSeconds": candidate_start,
        "candidateOriginalEndSeconds": candidate_end,
        "bestPoseOverlapSeconds": best_overlap,
        "bestPoseOverlapRatio": overlap_ratio,
        "bestPoseChunk": best_chunk,
        "validPoseChunkCount": len(valid_chunks),
    }


def source_cut_candidate_passes_pose_prefilter(candidate: SourceCutCandidate) -> bool:
    # The YOLO pose overlap is only diagnostic here. It is too brittle as a
    # hard source-cut gate because discovery may validate a different chunk
    # than the source window being refined.
    return True


def source_pose_sample_time_seconds(sample: dict[str, Any]) -> float | None:
    return first_float(
        sample.get("timeSeconds"),
        sample.get("timestampSeconds"),
        sample.get("time"),
        sample.get("timestamp"),
    )


def source_pose_keypoint_to_point3(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    x = parse_optional_float(value[0])
    y = parse_optional_float(value[1])
    if x is None or y is None:
        return None
    return [float(x), float(y), 0.0]


def source_pose_midpoint3(left: list[float] | None, right: list[float] | None) -> list[float] | None:
    if left is not None and right is not None:
        return [
            (left[0] + right[0]) * 0.5,
            (left[1] + right[1]) * 0.5,
            (left[2] + right[2]) * 0.5,
        ]
    return left or right


def source_pose_skeleton_payload_for_window(
    pose_payload: dict[str, Any] | None,
    *,
    candidate_window: DetectionWindow,
    source_offset_seconds: float = 0.0,
) -> dict[str, Any] | None:
    if not isinstance(pose_payload, dict):
        return None
    samples_value = pose_payload.get("dominantPoseSamples")
    if not isinstance(samples_value, list):
        return None
    candidate_start = max(0.0, source_offset_seconds + candidate_window.start_seconds)
    candidate_end = max(candidate_start, source_offset_seconds + candidate_window.end_seconds)
    sample_fps = parse_optional_float(pose_payload.get("sampleFps"))
    boundary_tolerance_seconds = (
        min(0.50, max(0.0, 0.50 / sample_fps))
        if sample_fps is not None and sample_fps > 1e-6
        else 0.25
    )
    frames: list[dict[str, Any]] = []
    joint_names: set[str] = set()
    for sample in samples_value:
        if not isinstance(sample, dict):
            continue
        time_seconds = source_pose_sample_time_seconds(sample)
        if (
            time_seconds is None
            or time_seconds < candidate_start - boundary_tolerance_seconds
            or time_seconds > candidate_end + boundary_tolerance_seconds
        ):
            continue
        keypoints = sample.get("keypoints")
        if not isinstance(keypoints, dict):
            continue
        joints: dict[str, list[float]] = {}
        for name, value in keypoints.items():
            point = source_pose_keypoint_to_point3(value)
            if point is None:
                continue
            joints[str(name)] = point
        pelvis = source_pose_midpoint3(joints.get("left_hip"), joints.get("right_hip"))
        if pelvis is None:
            continue
        joints["pelvis"] = pelvis
        joints["hips"] = pelvis
        shoulder_center = source_pose_midpoint3(joints.get("left_shoulder"), joints.get("right_shoulder"))
        if shoulder_center is not None:
            joints["shoulders"] = shoulder_center
        joint_names.update(joints)
        frames.append(
            {
                "sourceTimeSec": float(time_seconds),
                "joints": joints,
            }
        )
    if not frames:
        return None
    frames.sort(key=lambda frame: float(frame.get("sourceTimeSec", 0.0)))
    return {
        "jointNames": sorted(joint_names),
        "rootJoint": "pelvis",
        "frames": frames,
        "coordinateSpace": pose_payload.get("dominantPoseSampleCoordinateSpace", "normalized_image_xy"),
        "sourcePoseSampleBoundaryToleranceSeconds": boundary_tolerance_seconds,
    }


def source_pose_dominant_root_relative_axis_track(
    frames: list[dict[str, Any]],
    *,
    joint_names: list[str],
    root_joint: str,
    min_frames: int,
    preferred_joint_predicate: Callable[[str], bool] | None = None,
) -> dict[str, Any] | None:
    excluded = {root_joint, "pelvis", "hips", "root"}
    candidate_joints = [name for name in joint_names if name not in excluded]

    def best_for(joints_to_consider: list[str], *, selection: str) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        for joint_name in joints_to_consider:
            points: list[list[float]] = []
            for frame in frames:
                joints = frame.get("joints")
                if not isinstance(joints, dict):
                    continue
                point = joints.get(joint_name)
                root = joints.get(root_joint)
                if is_point3(point) and is_point3(root):
                    point3 = point3_to_float_list(point)
                    root3 = point3_to_float_list(root)
                    points.append([point3[axis] - root3[axis] for axis in range(3)])
            if len(points) < max(min_frames, int(len(frames) * 0.60)):
                continue
            for axis in range(3):
                values = [point[axis] for point in points]
                value_range = max(values) - min(values)
                if best is None or value_range > float(best["range"]):
                    best = {
                        "joint": joint_name,
                        "axis": axis,
                        "range": value_range,
                        "values": values,
                        "selection": selection,
                    }
        return best

    if preferred_joint_predicate is not None:
        preferred_joints = [name for name in candidate_joints if preferred_joint_predicate(name)]
        preferred_best = best_for(preferred_joints, selection="preferred")
        if preferred_best is not None:
            return preferred_best
    return best_for(candidate_joints, selection="fallback_all_joints")


def full_repetition_phase_completeness_metrics_from_source_pose_payload(
    payload: dict[str, Any],
    *,
    exercise_name: str,
    ranking_payload: dict[str, Any] | None = None,
    chunk_estimate: Any | None = None,
) -> dict[str, Any]:
    complexity = movement_complexity_for_validation(
        exercise_name,
        ranking_payload=ranking_payload,
        chunk_estimate=chunk_estimate,
    ).strip().lower()
    motion_contract = target_motion_contract_from_ranking_payload(ranking_payload)
    target_motion_profile = target_motion_profile_for_exercise(
        exercise_name,
        contract=motion_contract,
    )
    observable_spec = observable_motion_spec_for_contract(motion_contract)
    required = (
        complexity in {"simple", "compound"}
        or target_motion_profile is not None
        or observable_motion_spec_requires_return(motion_contract)
    )
    if not required:
        return empty_full_repetition_phase_completeness_metrics(
            required=False,
            reason="movement_complexity_does_not_require_repetition_phase_return",
            movement_complexity=complexity,
        )
    frames_value = payload.get("frames")
    joint_names_value = payload.get("jointNames")
    if not isinstance(frames_value, list) or not isinstance(joint_names_value, list):
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="missing_source_pose_frames_or_joint_names",
            movement_complexity=complexity,
        )
    frames = [frame for frame in frames_value if isinstance(frame, dict)]
    min_frames = SOURCE_CUT_POSE_PHASE_COMPLETENESS_MIN_FRAMES
    if len(frames) < min_frames:
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="insufficient_source_pose_samples",
            frame_count=len(frames),
            movement_complexity=complexity,
        )
    joint_names = [str(name) for name in joint_names_value]
    root_joint = str(payload.get("rootJoint") or "")
    if root_joint not in joint_names:
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="missing_source_pose_root_joint",
            frame_count=len(frames),
            movement_complexity=complexity,
        )
    body_height = body_height_from_payload_frames(frames)
    if body_height <= 1e-6:
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="invalid_source_pose_body_height",
            frame_count=len(frames),
            movement_complexity=complexity,
        )
    preferred_joint_region = (
        "lower_body"
        if exercise_requires_lower_body_motion(exercise_name, contract=motion_contract)
        else None
    )
    dominant = source_pose_dominant_root_relative_axis_track(
        frames,
        joint_names=joint_names,
        root_joint=root_joint,
        min_frames=min_frames,
        preferred_joint_predicate=is_lower_body_joint if preferred_joint_region == "lower_body" else None,
    )
    if dominant is None:
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="missing_source_pose_dominant_motion_track",
            frame_count=len(frames),
            movement_complexity=complexity,
        )
    values = dominant["values"]
    if not isinstance(values, list) or len(values) < min_frames:
        return empty_full_repetition_phase_completeness_metrics(
            required=True,
            reason="insufficient_source_pose_dominant_motion_samples",
            frame_count=len(frames),
            movement_complexity=complexity,
        )
    motion_range = float(dominant["range"])
    motion_range_ratio = motion_range / body_height
    if motion_range_ratio < FULL_REPETITION_PHASE_COMPLETENESS_MIN_RANGE_RATIO:
        return {
            "required": True,
            "passed": True,
            "reason": "source_pose_dominant_motion_too_small_for_phase_gate",
            "movementComplexity": complexity,
            "targetMotionProfile": target_motion_profile.get("profile") if target_motion_profile is not None else None,
            "observableMotionSpec": observable_spec,
            "frameCount": len(frames),
            "sampleCount": len(values),
            "bodyHeight": body_height,
            "dominantJoint": dominant["joint"],
            "dominantJointSelection": dominant.get("selection"),
            "preferredJointRegion": preferred_joint_region,
            "dominantAxis": dominant["axis"],
            "dominantMotionRange": motion_range,
            "dominantMotionRangeRatio": motion_range_ratio,
            "minDominantMotionRangeRatio": FULL_REPETITION_PHASE_COMPLETENESS_MIN_RANGE_RATIO,
        }

    min_value = min(values)
    max_value = max(values)
    min_index = values.index(min_value)
    max_index = values.index(max_value)
    sample_count = len(values)
    edge_margin = max(1, int(round((sample_count - 1) * FULL_REPETITION_PHASE_COMPLETENESS_EDGE_MARGIN_RATIO)))
    interior_min = edge_margin <= min_index <= (sample_count - 1 - edge_margin)
    interior_max = edge_margin <= max_index <= (sample_count - 1 - edge_margin)
    endpoint_delta_ratio = abs(float(values[-1]) - float(values[0])) / max(motion_range, 1e-8)
    has_return_phase = endpoint_delta_ratio <= FULL_REPETITION_PHASE_COMPLETENESS_MAX_ENDPOINT_DELTA_RATIO
    has_interior_extreme = interior_min or interior_max
    passed = has_return_phase and has_interior_extreme
    return {
        "required": True,
        "passed": passed,
        "reason": "source_pose_full_repetition_phase_return_detected" if passed else "source_pose_one_way_partial_repetition_phase",
        "movementComplexity": complexity,
        "targetMotionProfile": target_motion_profile.get("profile") if target_motion_profile is not None else None,
        "observableMotionSpec": observable_spec,
        "frameCount": len(frames),
        "sampleCount": sample_count,
        "bodyHeight": body_height,
        "dominantJoint": dominant["joint"],
        "dominantJointSelection": dominant.get("selection"),
        "preferredJointRegion": preferred_joint_region,
        "dominantAxis": dominant["axis"],
        "dominantMotionRange": motion_range,
        "dominantMotionRangeRatio": motion_range_ratio,
        "minDominantMotionRangeRatio": FULL_REPETITION_PHASE_COMPLETENESS_MIN_RANGE_RATIO,
        "startValue": float(values[0]),
        "endValue": float(values[-1]),
        "minValue": float(min_value),
        "maxValue": float(max_value),
        "minFrameIndex": min_index,
        "maxFrameIndex": max_index,
        "edgeMarginFrameCount": edge_margin,
        "endpointPhaseDeltaRatio": endpoint_delta_ratio,
        "maxEndpointPhaseDeltaRatio": FULL_REPETITION_PHASE_COMPLETENESS_MAX_ENDPOINT_DELTA_RATIO,
        "hasReturnPhase": has_return_phase,
        "hasInteriorExtreme": has_interior_extreme,
        "interiorMin": interior_min,
        "interiorMax": interior_max,
    }


def source_cut_candidate_motion_coverage_metrics(
    *,
    candidate_window: DetectionWindow,
    pose_payload: dict[str, Any] | None,
    exercise_name: str,
    chunk_estimate: Any | None = None,
    exercise_motion_contract: dict[str, Any] | None = None,
    source_offset_seconds: float = 0.0,
) -> dict[str, Any]:
    source_pose_payload = source_pose_skeleton_payload_for_window(
        pose_payload,
        candidate_window=candidate_window,
        source_offset_seconds=source_offset_seconds,
    )
    if source_pose_payload is None:
        return {
            "passed": True,
            "skippedReasons": ["source_cut_pose_samples_unavailable"],
        }
    candidate_phase_metrics = full_repetition_phase_completeness_metrics_from_source_pose_payload(
        source_pose_payload,
        exercise_name=exercise_name,
        ranking_payload={"exerciseMotionContract": exercise_motion_contract},
        chunk_estimate=chunk_estimate,
    )
    rejection_reasons: list[str] = []
    skipped_reasons: list[str] = []
    if bool(candidate_phase_metrics.get("required")):
        if not bool(candidate_phase_metrics.get("passed", True)):
            rejection_reasons.append("source_cut_incomplete_repetition_phase")
        elif str(candidate_phase_metrics.get("reason") or "").startswith("insufficient_"):
            rejection_reasons.append("source_cut_insufficient_repetition_phase_evidence")
        elif str(candidate_phase_metrics.get("reason") or "") == "source_pose_dominant_motion_too_small_for_phase_gate":
            rejection_reasons.append("source_cut_insufficient_repetition_phase_evidence")
        endpoint_delta_ratio = parse_optional_float(candidate_phase_metrics.get("endpointPhaseDeltaRatio"))
        if (
            endpoint_delta_ratio is not None
            and endpoint_delta_ratio > SOURCE_CUT_MAX_ENDPOINT_PHASE_DELTA_RATIO
        ):
            rejection_reasons.append("source_cut_weak_repetition_return_phase")
    else:
        skipped_reasons.append("source_cut_phase_gate_not_required_for_complexity")
    return {
        "passed": not rejection_reasons,
        "rejectionReasons": rejection_reasons,
        "skippedReasons": skipped_reasons,
        "sourceOffsetSeconds": source_offset_seconds,
        "candidateOriginalStartSeconds": max(0.0, source_offset_seconds + candidate_window.start_seconds),
        "candidateOriginalEndSeconds": max(0.0, source_offset_seconds + candidate_window.end_seconds),
        "sourcePoseSampleCount": len(source_pose_payload.get("frames", [])),
        "maxEndpointPhaseDeltaRatio": SOURCE_CUT_MAX_ENDPOINT_PHASE_DELTA_RATIO,
        "candidateFullRepetitionPhaseCompletenessMetrics": candidate_phase_metrics,
    }


def source_cut_candidate_passes_motion_coverage(candidate: SourceCutCandidate) -> bool:
    if not candidate.motion_coverage:
        return True
    return bool(candidate.motion_coverage.get("passed", True))


def movement_cut_target_motion_gate_metrics(
    *,
    exercise_name: str,
    candidate_metrics: dict[str, Any],
    candidate_phase_metrics: dict[str, Any] | None,
    chunk_estimate: Any | None = None,
    exercise_motion_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    complexity = movement_complexity_for_validation(
        exercise_name,
        chunk_estimate=chunk_estimate,
    ).strip().lower()
    target_motion_profile = target_motion_profile_for_exercise(
        exercise_name,
        contract=exercise_motion_contract,
    )
    target_profile_key = (
        str(target_motion_profile.get("profile"))
        if isinstance(target_motion_profile, dict) and target_motion_profile.get("profile")
        else None
    )
    observable_spec = observable_motion_spec_for_contract(exercise_motion_contract)
    required = (
        complexity in {"simple", "compound"}
        or target_motion_profile is not None
        or observable_spec is not None
    )
    lower_body_target = exercise_requires_lower_body_motion(
        exercise_name,
        contract=exercise_motion_contract,
    )
    root_vertical_range = parse_optional_float(candidate_metrics.get("rootVerticalRangeRatio"))
    lower_body_proximal_range = parse_optional_float(candidate_metrics.get("lowerBodyProximalRootRelativeRangeRatio"))
    lower_body_distal_range = parse_optional_float(candidate_metrics.get("lowerBodyDistalRootRelativeRangeRatio"))
    upper_body_range = parse_optional_float(candidate_metrics.get("upperBodyRootRelativeRangeRatio"))
    distal_allowed = target_profile_key == "distal_leg_vertical_raise"
    if distal_allowed:
        target_region = "lower_body_distal"
        target_range = lower_body_distal_range
    elif lower_body_target:
        target_region = "lower_body"
        distal_target_range = (lower_body_distal_range or 0.0) if distal_allowed else 0.0
        target_range = max(
            root_vertical_range or 0.0,
            lower_body_proximal_range or 0.0,
            distal_target_range,
        )
    else:
        target_region = "upper_body"
        target_range = upper_body_range

    dominant_joint = None
    if candidate_phase_metrics is not None:
        dominant_joint_value = candidate_phase_metrics.get("dominantJoint")
        dominant_joint = str(dominant_joint_value) if dominant_joint_value is not None else None
    distal_lower_body_dominant = (
        dominant_joint is not None
        and is_lower_body_distal_joint(dominant_joint)
        and not distal_allowed
    )
    target_to_distal_ratio = None
    if lower_body_distal_range is not None and lower_body_distal_range > 1e-6 and target_range is not None:
        target_to_distal_ratio = target_range / lower_body_distal_range
    distal_dominates_target = (
        distal_lower_body_dominant
        and lower_body_distal_range is not None
        and lower_body_distal_range >= MOVEMENT_CUT_MIN_TARGET_REGION_MOTION_RANGE_RATIO
        and target_range is not None
        and (
            lower_body_distal_range >= target_range * MOVEMENT_CUT_DISTAL_DOMINANCE_MIN_RATIO
            or target_to_distal_ratio <= MOVEMENT_CUT_DISTAL_DOMINANCE_MAX_TARGET_TO_DISTAL_RATIO
        )
    )

    rejection_reasons: list[str] = []
    skipped_reasons: list[str] = []
    if not required:
        skipped_reasons.append("movement_cut_target_motion_gate_not_required_for_complexity")
    elif target_range is None:
        skipped_reasons.append("movement_cut_target_motion_range_missing")
    else:
        if target_range < MOVEMENT_CUT_MIN_TARGET_REGION_MOTION_RANGE_RATIO:
            rejection_reasons.append("movement_cut_low_target_region_motion")
        if distal_dominates_target:
            rejection_reasons.append("movement_cut_distal_setup_motion_dominates")

    return {
        "required": required,
        "passed": not rejection_reasons,
        "rejectionReasons": rejection_reasons,
        "skippedReasons": skipped_reasons,
        "exerciseName": exercise_name,
        "movementComplexity": complexity,
        "targetMotionProfile": target_profile_key,
        "observableMotionSpec": observable_spec,
        "targetMotionRegion": target_region,
        "targetMotionRangeRatio": target_range,
        "minTargetMotionRangeRatio": MOVEMENT_CUT_MIN_TARGET_REGION_MOTION_RANGE_RATIO,
        "rootVerticalRangeRatio": root_vertical_range,
        "lowerBodyProximalRootRelativeRangeRatio": lower_body_proximal_range,
        "lowerBodyDistalRootRelativeRangeRatio": lower_body_distal_range,
        "upperBodyRootRelativeRangeRatio": upper_body_range,
        "dominantPhaseJoint": dominant_joint,
        "distalLowerBodyDominant": distal_lower_body_dominant,
        "distalLowerBodyTargetAllowed": distal_allowed,
        "targetToDistalMotionRatio": target_to_distal_ratio,
        "distalDominanceMinRatio": MOVEMENT_CUT_DISTAL_DOMINANCE_MIN_RATIO,
        "maxTargetToDistalMotionRatio": MOVEMENT_CUT_DISTAL_DOMINANCE_MAX_TARGET_TO_DISTAL_RATIO,
    }


def movement_cut_candidate_motion_coverage_metrics(
    *,
    item: ReviewItem,
    parent_window: DetectionWindow,
    candidate_window: DetectionWindow,
    chunk_estimate: Any | None = None,
    exercise_motion_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not item.skeleton_path.exists():
        return {
            "passed": True,
            "skippedReasons": ["movement_cut_motion_coverage_skeleton_missing"],
        }
    try:
        parent_metrics = compute_source_capture_motion_strength_metrics(
            item.skeleton_path,
            start_seconds=parent_window.start_seconds,
            end_seconds=parent_window.end_seconds,
        )
        candidate_metrics = compute_source_capture_motion_strength_metrics(
            item.skeleton_path,
            start_seconds=candidate_window.start_seconds,
            end_seconds=candidate_window.end_seconds,
        )
    except Exception:
        return {
            "passed": True,
            "skippedReasons": ["movement_cut_motion_coverage_metrics_unavailable"],
        }

    parent_range = parse_optional_float(parent_metrics.get("primaryMotionRangeRatio"))
    candidate_range = parse_optional_float(candidate_metrics.get("primaryMotionRangeRatio"))
    rejection_reasons: list[str] = []
    skipped_reasons: list[str] = []
    coverage_ratio: float | None = None
    if parent_range is None or candidate_range is None:
        skipped_reasons.append("movement_cut_motion_coverage_range_missing")
    elif parent_range <= 1e-6:
        skipped_reasons.append("movement_cut_parent_motion_range_zero")
    else:
        coverage_ratio = clamp_unit(candidate_range / parent_range)
        if (
            parent_range >= LOOP_SOURCE_STRONG_MOTION_RATIO_MIN
            and coverage_ratio < MOVEMENT_CUT_MIN_SOURCE_MOTION_COVERAGE_RATIO
        ):
            rejection_reasons.append("movement_cut_low_source_motion_coverage")

    parent_phase_metrics: dict[str, Any] | None = None
    candidate_phase_metrics: dict[str, Any] | None = None
    try:
        parent_phase_metrics = full_repetition_phase_completeness_metrics_from_skeleton_path(
            item.skeleton_path,
            exercise_name=item.exercise_name,
            ranking_payload={"exerciseMotionContract": exercise_motion_contract},
            chunk_estimate=chunk_estimate,
            start_seconds=parent_window.start_seconds,
            end_seconds=parent_window.end_seconds,
            fallback_to_full=False,
        )
        candidate_phase_metrics = full_repetition_phase_completeness_metrics_from_skeleton_path(
            item.skeleton_path,
            exercise_name=item.exercise_name,
            ranking_payload={"exerciseMotionContract": exercise_motion_contract},
            chunk_estimate=chunk_estimate,
            start_seconds=candidate_window.start_seconds,
            end_seconds=candidate_window.end_seconds,
            fallback_to_full=False,
        )
    except Exception:
        skipped_reasons.append("movement_cut_phase_completeness_metrics_unavailable")
    if (
        candidate_phase_metrics is not None
        and bool(candidate_phase_metrics.get("required"))
        and not bool(candidate_phase_metrics.get("passed", True))
    ):
        rejection_reasons.append("movement_cut_incomplete_repetition_phase")
    candidate_has_complete_repetition_phase = (
        candidate_phase_metrics is not None
        and bool(candidate_phase_metrics.get("required"))
        and bool(candidate_phase_metrics.get("passed"))
    )
    coverage_satisfied_by_complete_phase = False
    if (
        candidate_has_complete_repetition_phase
        and "movement_cut_low_source_motion_coverage" in rejection_reasons
    ):
        rejection_reasons = [
            reason
            for reason in rejection_reasons
            if reason != "movement_cut_low_source_motion_coverage"
        ]
        coverage_satisfied_by_complete_phase = True

    target_motion_gate = movement_cut_target_motion_gate_metrics(
        exercise_name=item.exercise_name,
        candidate_metrics=candidate_metrics,
        candidate_phase_metrics=candidate_phase_metrics,
        chunk_estimate=chunk_estimate,
        exercise_motion_contract=exercise_motion_contract,
    )
    rejection_reasons.extend(
        str(reason)
        for reason in target_motion_gate.get("rejectionReasons", [])
    )
    skipped_reasons.extend(
        str(reason)
        for reason in target_motion_gate.get("skippedReasons", [])
    )

    payload = {
        "passed": not rejection_reasons,
        "rejectionReasons": rejection_reasons,
        "skippedReasons": skipped_reasons,
        "sourceMotionCoverageRatio": coverage_ratio,
        "minSourceMotionCoverageRatio": MOVEMENT_CUT_MIN_SOURCE_MOTION_COVERAGE_RATIO,
        "strongParentMotionRangeRatioMin": LOOP_SOURCE_STRONG_MOTION_RATIO_MIN,
        "parentPrimaryMotionRangeRatio": parent_range,
        "candidatePrimaryMotionRangeRatio": candidate_range,
        "parentMotionStrengthScore": parse_optional_float(parent_metrics.get("motionStrengthScore")),
        "candidateMotionStrengthScore": parse_optional_float(candidate_metrics.get("motionStrengthScore")),
        "parentMotionStrengthMetrics": parent_metrics,
        "candidateMotionStrengthMetrics": candidate_metrics,
        "motionCoverageSatisfiedByCompleteRepetitionPhase": coverage_satisfied_by_complete_phase,
        "targetMotionGate": target_motion_gate,
    }
    if parent_phase_metrics is not None:
        payload["parentFullRepetitionPhaseCompletenessMetrics"] = parent_phase_metrics
    if candidate_phase_metrics is not None:
        payload["candidateFullRepetitionPhaseCompletenessMetrics"] = candidate_phase_metrics
    return payload


def movement_cut_candidate_passes_motion_coverage(candidate: SourceCutCandidate) -> bool:
    if not candidate.motion_coverage:
        return True
    return bool(candidate.motion_coverage.get("passed", True))


def movement_cut_candidate_hard_motion_rejection_reasons(candidate: SourceCutCandidate) -> list[str]:
    rejection_reasons = candidate.motion_coverage.get("rejectionReasons") if candidate.motion_coverage else None
    if not isinstance(rejection_reasons, list):
        return []
    return [
        str(reason)
        for reason in rejection_reasons
        if str(reason) in MOVEMENT_CUT_HARD_MOTION_REJECTION_REASONS
    ]


def movement_cut_candidate_has_hard_motion_rejection(candidate: SourceCutCandidate) -> bool:
    return bool(movement_cut_candidate_hard_motion_rejection_reasons(candidate))


SOURCE_CUT_REQUIRED_TRUE_FIELDS: dict[str, str] = {}

EXERCISE_MOTION_CONTRACT_MAX_TOKENS = 384
EXERCISE_MOTION_CONTRACT_TIMEOUT_SECONDS = 30.0
SOURCE_CUT_SCORECARD_MIN_EXERCISE_MATCH_WITH_CONTRACT = 0.85
SOURCE_CUT_SCORECARD_MIN_FULL_MOVEMENT_WITH_CONTRACT = 0.85
SOURCE_CUT_SCORECARD_MIN_START_VISIBLE_WITH_CONTRACT = 0.80
SOURCE_CUT_SCORECARD_MIN_FINISH_VISIBLE_WITH_CONTRACT = 0.80
SOURCE_CUT_SCORECARD_MAX_SETUP_OR_FILLER = 0.20
SOURCE_CUT_SCORECARD_MIN_SOURCE_QUALITY = 0.75
SOURCE_CUT_SCORECARD_MIN_CONFIDENCE = 0.75
SOURCE_CUT_SCORECARD_NO_CONTRACT_MIN_IDENTITY = 0.90
SOURCE_CUT_SCORECARD_REQUIRED_FIELDS = (
    "exercise_match",
    "full_movement",
    "start_visible",
    "finish_visible",
    "setup_or_filler",
    "source_quality",
    "confidence",
)
SOURCE_CUT_SCORECARD_ALLOWED_REJECT_TAGS = frozenset(
    (
        "wrong_exercise",
        "partial_movement",
        "start_not_visible",
        "finish_not_visible",
        "setup_or_filler",
        "low_source_quality",
        "low_confidence",
        "synthetic_subject",
        "unclear",
        "invalid_reject_tag",
    )
)
SOURCE_CUT_SCORECARD_REJECT_TAG_ALIASES = {
    "none": "",
    "bad_boundary": "setup_or_filler",
    "mostly_setup": "setup_or_filler",
    "mostly_setup_or_reset": "setup_or_filler",
    "setup_or_reset": "setup_or_filler",
    "setup_or_talking": "setup_or_filler",
    "slow_instruction": "setup_or_filler",
    "not_real_footage": "synthetic_subject",
    "animated_or_synthetic": "synthetic_subject",
    "animation_or_synthetic": "synthetic_subject",
    "synthetic": "synthetic_subject",
    "body_cropped": "low_source_quality",
    "cropped_body": "low_source_quality",
    "out_of_frame": "low_source_quality",
    "obstruction": "low_source_quality",
}

SOURCE_CUT_TARGET_EXERCISE_MATCH_MIN_SCORE = 0.75
SOURCE_CUT_MIN_SELECTED_SCORE = 0.50
SOURCE_CUT_MIN_MOVING_SUBJECT_REALISM_SCORE = MIN_MOVING_SUBJECT_REALISM_SCORE
SOURCE_CUT_MAX_ENDPOINT_PHASE_DELTA_RATIO = 0.45
MOVEMENT_CUT_DETERMINISTIC_DIRECT_MIN_COVERAGE_RATIO = 0.90
MOVEMENT_CUT_DETERMINISTIC_DIRECT_SCORE = 0.86
MOVEMENT_CUT_BOUNDARY_FALLBACK_SCORE_CAP = 0.65
MOVEMENT_CUT_BOUNDARY_FALLBACK_ALLOWED_REJECTION_REASONS = frozenset(
    (
        "source_cut_setup_or_talking",
        "source_cut_bad_boundary",
    )
)

SOURCE_CUT_OPTIONAL_FALSE_FIELDS: dict[str, str] = {}

SOURCE_CUT_BLOCKING_ISSUE_REASONS = {
    "wrong_exercise": "source_cut_wrong_exercise",
    "partial_movement": "source_cut_partial_movement",
    "setup_or_talking": "source_cut_setup_or_talking",
    "setup_or_reset": "source_cut_setup_or_talking",
    "mostly_setup": "source_cut_setup_or_talking",
    "mostly_setup_or_reset": "source_cut_setup_or_talking",
    "slow_instruction": "source_cut_setup_or_talking",
    "unclear": "source_cut_unclear",
    "bad_boundary": "source_cut_bad_boundary",
}

SOURCE_CUT_IGNORED_BLOCKING_ISSUES = {
    "animation_or_synthetic",
    "animated_or_synthetic",
    "synthetic",
    "animation",
    "camera_cut",
    "camera_cuts",
    "camera_motion",
    "angle_change",
    "shot_change",
    "cropped_body",
    "body_cropped",
    "out_of_frame",
    "multiple_people",
    "obstruction",
}


def parse_source_cut_blocking_issues(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items: list[Any]
    if isinstance(value, str):
        raw_items = re.split(r"[,;\n]+", value)
    elif isinstance(value, Iterable) and not isinstance(value, (dict, bytes, bytearray)):
        raw_items = list(value)
    else:
        raw_items = [value]
    issues: list[str] = []
    for item in raw_items:
        text = slugify(str(item or "")).replace("-", "_")
        if not text or text == "none":
            continue
        if text not in issues:
            issues.append(text)
    return issues


def source_cut_choice_rejection_reasons(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field, reason in SOURCE_CUT_REQUIRED_TRUE_FIELDS.items():
        if parse_optional_bool(payload.get(field)) is not True:
            reasons.append(reason)
    target_match_score = parse_source_cut_target_exercise_match_score(payload)
    if target_match_score is None:
        reasons.append("source_cut_target_match_score_missing")
    elif target_match_score < SOURCE_CUT_TARGET_EXERCISE_MATCH_MIN_SCORE:
        reasons.append("source_cut_wrong_exercise")
    if parse_source_cut_moving_subject_realism_score(payload) < SOURCE_CUT_MIN_MOVING_SUBJECT_REALISM_SCORE:
        reasons.append("source_cut_low_moving_subject_realism")
    for field, reason in SOURCE_CUT_OPTIONAL_FALSE_FIELDS.items():
        if parse_optional_bool(payload.get(field)) is False:
            reasons.append(reason)
    for issue in parse_source_cut_blocking_issues(payload.get("blocking_issues", payload.get("blockingIssues"))):
        if issue in SOURCE_CUT_IGNORED_BLOCKING_ISSUES:
            continue
        reasons.append(SOURCE_CUT_BLOCKING_ISSUE_REASONS.get(issue, f"source_cut_{issue}"))
    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


def parse_source_cut_target_exercise_match_score(payload: dict[str, Any]) -> float | None:
    score = parse_optional_float(payload.get("target_exercise_match_score"))
    if score is None:
        return None
    if score > 1.0:
        score = score / 100.0
    return clamp_unit(score)


def parse_source_cut_moving_subject_realism_score(payload: dict[str, Any]) -> float:
    score = first_float(
        payload.get("moving_subject_realism_score"),
        payload.get("subject_realism_score"),
        payload.get("realism_score"),
    )
    if score is None:
        legacy_real_human_subject = parse_optional_bool(payload.get("real_human_subject"))
        score = 0.20 if legacy_real_human_subject is False else 1.0
    if score > 1.0:
        score = score / 100.0
    return clamp_unit(score)


def extract_json_object_with_trailing_repair(raw: str) -> dict[str, Any] | None:
    try:
        payload = extract_json_object(raw)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        return payload
    text = str(raw or "").strip()
    start = text.find("{")
    if start < 0:
        return None
    candidate = text[start:].strip()
    repaired_candidate = repair_incomplete_json_object(candidate)
    if repaired_candidate is None:
        return None
    repaired_variants = [
        repaired_candidate,
        re.sub(r",(\s*[}\]])", r"\1", repaired_candidate),
    ]
    decoder = json.JSONDecoder()
    for repaired_text in dedupe_text(repaired_variants):
        try:
            repaired, _end = decoder.raw_decode(repaired_text)
        except json.JSONDecodeError:
            continue
        if isinstance(repaired, dict):
            return repaired
    return None


def repair_incomplete_json_object(text: str) -> str | None:
    stack: list[str] = []
    in_string = False
    escape = False
    for char in text:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in ("}", "]"):
            if not stack or stack[-1] != char:
                return None
            stack.pop()
    repaired = text
    if in_string:
        if escape and repaired.endswith("\\"):
            repaired = repaired[:-1]
        repaired += '"'
    return repaired + "".join(reversed(stack))


def source_cut_candidate_duration(candidate: SourceCutCandidate) -> float:
    return max(0.0, candidate.window.end_seconds - candidate.window.start_seconds)


def candidate_binary_result_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("candidate_results", "candidateResults", "candidate_classifications", "candidateClassifications"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def binary_result_candidate_id(payload: dict[str, Any]) -> str:
    return normalize_source_cut_candidate_id(
        payload.get("candidate_id")
        or payload.get("candidateId")
        or payload.get("selected_candidate_id")
        or payload.get("selectedCandidateId")
        or payload.get("id")
    )


def normalize_binary_candidate_result_payload(payload: dict[str, Any], *, movement_cut: bool) -> dict[str, Any]:
    normalized = dict(payload)
    complete = first_optional_bool(
        payload.get("contains_complete_target_movement"),
        payload.get("containsCompleteTargetMovement"),
        payload.get("complete_movement"),
        payload.get("completeMovement"),
        payload.get("valid_single_movement"),
        payload.get("validSingleMovement"),
        payload.get("valid_movement_cut"),
        payload.get("validMovementCut"),
    )
    target_match = first_optional_bool(
        payload.get("target_exercise_match"),
        payload.get("targetExerciseMatch"),
        payload.get("correct_exercise"),
        payload.get("correctExercise"),
        payload.get("target_identity_match"),
        payload.get("targetIdentityMatch"),
    )
    clean_boundaries = first_optional_bool(
        payload.get("clean_boundaries"),
        payload.get("cleanBoundaries"),
        payload.get("has_clean_boundaries"),
        payload.get("hasCleanBoundaries"),
    )
    includes_setup = first_optional_bool(
        payload.get("includes_setup_or_reset"),
        payload.get("includesSetupOrReset"),
        payload.get("mostly_setup"),
        payload.get("mostlySetup"),
        payload.get("mostly_setup_or_reset"),
        payload.get("mostlySetupOrReset"),
    )
    partial = first_optional_bool(payload.get("partial_movement"), payload.get("partialMovement"))
    wrong = first_optional_bool(payload.get("wrong_exercise"), payload.get("wrongExercise"))

    if complete is not None:
        normalized["valid_single_movement"] = complete
        normalized["valid_movement_cut"] = complete
        normalized["complete_movement"] = complete
    if complete is False and "partial_movement" not in parse_source_cut_blocking_issues(
        normalized.get("blocking_issues", normalized.get("blockingIssues"))
    ):
        normalized["blocking_issues"] = [
            *parse_source_cut_blocking_issues(normalized.get("blocking_issues", normalized.get("blockingIssues"))),
            "partial_movement",
        ]
    if target_match is not None and parse_source_cut_target_exercise_match_score(normalized) is None:
        normalized["target_exercise_match_score"] = 1.0 if target_match else 0.0
    if target_match is False:
        blocking_issues = parse_source_cut_blocking_issues(
            normalized.get("blocking_issues", normalized.get("blockingIssues"))
        )
        if "wrong_exercise" not in blocking_issues:
            normalized["blocking_issues"] = [*blocking_issues, "wrong_exercise"]
    if clean_boundaries is not None:
        normalized["clean_boundaries"] = clean_boundaries
        if clean_boundaries is False:
            blocking_issues = parse_source_cut_blocking_issues(
                normalized.get("blocking_issues", normalized.get("blockingIssues"))
            )
            if "bad_boundary" not in blocking_issues:
                normalized["blocking_issues"] = [*blocking_issues, "bad_boundary"]
    if includes_setup is not None:
        normalized["includes_setup_or_reset"] = includes_setup

    blocking_issues = parse_source_cut_blocking_issues(
        normalized.get("blocking_issues", normalized.get("blockingIssues"))
    )
    if partial is True and "partial_movement" not in blocking_issues:
        blocking_issues.append("partial_movement")
    if wrong is True and "wrong_exercise" not in blocking_issues:
        blocking_issues.append("wrong_exercise")
    if includes_setup is True and "setup_or_reset" not in blocking_issues:
        blocking_issues.append("setup_or_reset")
    normalized["blocking_issues"] = blocking_issues or ["none"]
    return normalized


def first_optional_bool(*values: object) -> bool | None:
    for value in values:
        parsed = parse_optional_bool(value)
        if parsed is not None:
            return parsed
    return None


def binary_candidate_confidence(payload: dict[str, Any]) -> float:
    score = first_float(
        payload.get("confidence"),
        payload.get("source_score"),
        payload.get("sourceScore"),
        payload.get("cut_quality"),
        payload.get("cutQuality"),
        payload.get("score"),
    )
    if score is None:
        score = 0.86
    if score > 1.0:
        score = score / 100.0
    return clamp_unit(score)


def source_cut_scorecard_thresholds(*, has_contract: bool) -> dict[str, float]:
    identity_min = (
        SOURCE_CUT_SCORECARD_MIN_EXERCISE_MATCH_WITH_CONTRACT
        if has_contract
        else SOURCE_CUT_SCORECARD_NO_CONTRACT_MIN_IDENTITY
    )
    return {
        "exercise_match": identity_min,
        "full_movement": (
            SOURCE_CUT_SCORECARD_MIN_FULL_MOVEMENT_WITH_CONTRACT
            if has_contract
            else SOURCE_CUT_SCORECARD_NO_CONTRACT_MIN_IDENTITY
        ),
        "start_visible": (
            SOURCE_CUT_SCORECARD_MIN_START_VISIBLE_WITH_CONTRACT
            if has_contract
            else SOURCE_CUT_SCORECARD_NO_CONTRACT_MIN_IDENTITY
        ),
        "finish_visible": (
            SOURCE_CUT_SCORECARD_MIN_FINISH_VISIBLE_WITH_CONTRACT
            if has_contract
            else SOURCE_CUT_SCORECARD_NO_CONTRACT_MIN_IDENTITY
        ),
        "setup_or_filler": SOURCE_CUT_SCORECARD_MAX_SETUP_OR_FILLER,
        "source_quality": SOURCE_CUT_SCORECARD_MIN_SOURCE_QUALITY,
        "confidence": SOURCE_CUT_SCORECARD_MIN_CONFIDENCE,
    }


def parse_source_cut_scorecard_score(value: Any) -> float | None:
    score = parse_optional_float(value)
    if score is None:
        return None
    if score > 1.0:
        score = score / 100.0
    return clamp_unit(score)


def source_cut_scorecard_candidate_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, dict)]


def normalize_source_cut_scorecard_reject_tags(value: Any) -> tuple[list[str], list[str]]:
    raw_items: list[Any]
    if value is None:
        raw_items = []
    elif isinstance(value, str):
        raw_items = re.split(r"[,;\n]+", value)
    elif isinstance(value, Iterable) and not isinstance(value, (dict, bytes, bytearray)):
        raw_items = list(value)
    else:
        raw_items = [value]

    tags: list[str] = []
    invalid_tags: list[str] = []
    for item in raw_items:
        raw_tag = slugify(str(item or "")).replace("-", "_")
        tag = SOURCE_CUT_SCORECARD_REJECT_TAG_ALIASES.get(raw_tag, raw_tag)
        if not tag:
            continue
        if tag not in SOURCE_CUT_SCORECARD_ALLOWED_REJECT_TAGS:
            invalid_tags.append(raw_tag)
            tag = "invalid_reject_tag"
        if tag not in tags:
            tags.append(tag)
    return tags, invalid_tags


def source_cut_scorecard_row(
    payload: dict[str, Any],
    *,
    candidates_by_id: dict[str, SourceCutCandidate],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    candidate_id = normalize_source_cut_candidate_id(
        payload.get("id")
        or payload.get("candidate_id")
        or payload.get("candidateId")
    )
    scores = {
        field: parse_source_cut_scorecard_score(payload.get(field))
        for field in SOURCE_CUT_SCORECARD_REQUIRED_FIELDS
    }
    missing_fields = [field for field, value in scores.items() if value is None]
    reject_tags, invalid_reject_tags = normalize_source_cut_scorecard_reject_tags(payload.get("reject"))
    note = str(payload.get("note") or payload.get("reason") or "").strip()
    if len(note) > 180:
        note = note[:180].rstrip() + "..."

    rejection_reasons: list[str] = []
    if candidate_id not in candidates_by_id:
        rejection_reasons.append("source_cut_scorecard_unknown_candidate_id")
    for field in missing_fields:
        rejection_reasons.append(f"source_cut_scorecard_missing_{field}")
    if invalid_reject_tags:
        rejection_reasons.append("source_cut_scorecard_invalid_reject_tag")
    for tag in reject_tags:
        rejection_reasons.append(f"source_cut_scorecard_reject_{tag}")

    exercise_match = scores["exercise_match"]
    full_movement = scores["full_movement"]
    start_visible = scores["start_visible"]
    finish_visible = scores["finish_visible"]
    setup_or_filler = scores["setup_or_filler"]
    source_quality = scores["source_quality"]
    confidence = scores["confidence"]
    if exercise_match is not None and exercise_match < thresholds["exercise_match"]:
        rejection_reasons.append("source_cut_wrong_exercise")
    if full_movement is not None and full_movement < thresholds["full_movement"]:
        rejection_reasons.append("source_cut_partial_movement")
    if start_visible is not None and start_visible < thresholds["start_visible"]:
        rejection_reasons.append("source_cut_start_not_visible")
    if finish_visible is not None and finish_visible < thresholds["finish_visible"]:
        rejection_reasons.append("source_cut_finish_not_visible")
    if setup_or_filler is not None and setup_or_filler > thresholds["setup_or_filler"]:
        rejection_reasons.append("source_cut_setup_or_filler")
    if source_quality is not None and source_quality < thresholds["source_quality"]:
        rejection_reasons.append("source_cut_low_source_quality")
    if confidence is not None and confidence < thresholds["confidence"]:
        rejection_reasons.append("source_cut_low_confidence")

    deduped_reasons: list[str] = []
    for reason in rejection_reasons:
        if reason not in deduped_reasons:
            deduped_reasons.append(reason)

    score_values = [
        exercise_match,
        full_movement,
        start_visible,
        finish_visible,
        None if setup_or_filler is None else 1.0 - setup_or_filler,
        source_quality,
        confidence,
    ]
    resolved_score_values = [float(value) for value in score_values if value is not None]
    model_score = min(resolved_score_values) if len(resolved_score_values) == len(score_values) else 0.0
    return {
        "id": candidate_id,
        "exercise_match": exercise_match,
        "full_movement": full_movement,
        "start_visible": start_visible,
        "finish_visible": finish_visible,
        "setup_or_filler": setup_or_filler,
        "source_quality": source_quality,
        "confidence": confidence,
        "reject": reject_tags,
        "invalidRejectTags": invalid_reject_tags,
        "note": note,
        "score": clamp_unit(model_score),
        "passed": not deduped_reasons,
        "rejectionReasons": deduped_reasons,
        "missingFields": missing_fields,
    }


def build_source_cut_scorecard_ranking(
    payload: dict[str, Any],
    candidates: list[SourceCutCandidate],
    *,
    has_contract: bool,
    raw: str,
) -> LoopRanking:
    thresholds = source_cut_scorecard_thresholds(has_contract=has_contract)
    candidates_by_id = {
        normalize_source_cut_candidate_id(candidate.candidate_id): candidate
        for candidate in candidates
    }
    rows = [
        source_cut_scorecard_row(
            item,
            candidates_by_id=candidates_by_id,
            thresholds=thresholds,
        )
        for item in source_cut_scorecard_candidate_payloads(payload)
    ]
    passing: list[tuple[float, float, float, SourceCutCandidate, dict[str, Any]]] = []
    for row in rows:
        candidate = candidates_by_id.get(str(row["id"]))
        if candidate is None or not bool(row["passed"]):
            continue
        score = float(row["score"])
        passing.append(
            (
                source_cut_candidate_duration(candidate),
                -score,
                -float(candidate.window.end_seconds),
                candidate,
                row,
            )
        )

    base_payload: dict[str, Any] = {
        "sourceCutScorecardSchemaVersion": 1,
        "sourceCutScorecardThresholds": thresholds,
        "sourceCutScorecardContractPresent": has_contract,
        "sourceCutScorecardCandidates": rows,
        "sourceCutSelectionPolicy": "progressive_multiscale_stable_level_then_score",
        "sourceCutCandidates": source_cut_candidates_payload(candidates),
    }
    if not passing:
        return LoopRanking(
            score=0.0,
            reasons=["source_candidate_scorecard_no_passing_candidate"],
            raw_response=raw,
            payload={
                **base_payload,
                "score": 0.0,
                "modelScore": 0.0,
            },
            model_score=0.0,
        )

    _duration, negative_score, _negative_end, selected, selected_row = min(passing)
    score = -negative_score
    note = str(selected_row.get("note") or "source_candidate_scorecard_passed")
    return LoopRanking(
        score=score,
        reasons=[note, "source_candidate_scorecard_passed", "source_candidate_window_choice"],
        raw_response=raw,
        payload={
            **base_payload,
            "score": score,
            "modelScore": score,
            "selectedCandidateId": selected.candidate_id,
            "selected_section_start_seconds": selected.window.start_seconds,
            "selected_section_end_seconds": selected.window.end_seconds,
            "selectedScorecard": selected_row,
        },
        model_score=score,
    )


def parse_binary_source_cut_candidate_choice(
    payload: dict[str, Any],
    candidates: list[SourceCutCandidate],
    *,
    movement_cut: bool,
    min_duration_seconds: float | None = None,
) -> tuple[SourceCutCandidate, dict[str, Any], float] | None:
    candidate_payloads = candidate_binary_result_payloads(payload)
    if not candidate_payloads:
        return None
    candidates_by_id = {
        normalize_source_cut_candidate_id(candidate.candidate_id): candidate
        for candidate in candidates
    }
    passing: list[tuple[float, float, float, int, SourceCutCandidate, dict[str, Any]]] = []
    boundary_fallbacks: list[tuple[float, float, int, SourceCutCandidate, dict[str, Any], list[str]]] = []
    for order, raw_candidate_payload in enumerate(candidate_payloads):
        candidate = candidates_by_id.get(binary_result_candidate_id(raw_candidate_payload))
        if candidate is None:
            continue
        candidate_payload = normalize_binary_candidate_result_payload(
            raw_candidate_payload,
            movement_cut=movement_cut,
        )
        complete = first_optional_bool(
            candidate_payload.get("valid_single_movement"),
            candidate_payload.get("valid_movement_cut"),
            candidate_payload.get("complete_movement"),
        )
        confidence = binary_candidate_confidence(candidate_payload)
        rejection_reasons = source_cut_choice_rejection_reasons(candidate_payload)
        if (
            movement_cut
            and min_duration_seconds is not None
            and source_cut_candidate_duration(candidate) + 1e-6 < min_duration_seconds
        ):
            continue
        if complete is not True:
            continue
        if first_optional_bool(
            candidate_payload.get("target_exercise_match"),
            candidate_payload.get("targetExerciseMatch"),
            candidate_payload.get("correct_exercise"),
            candidate_payload.get("correctExercise"),
            candidate_payload.get("target_identity_match"),
            candidate_payload.get("targetIdentityMatch"),
        ) is False:
            continue
        if movement_cut:
            clean_boundaries = parse_optional_bool(candidate_payload.get("clean_boundaries"))
            includes_setup = parse_optional_bool(candidate_payload.get("includes_setup_or_reset"))
            boundary_only_rejection = (
                bool(rejection_reasons)
                and all(
                    reason in MOVEMENT_CUT_BOUNDARY_FALLBACK_ALLOWED_REJECTION_REASONS
                    for reason in rejection_reasons
                )
            )
            if clean_boundaries is not True or includes_setup is not False:
                if (
                    confidence >= SOURCE_CUT_MIN_SELECTED_SCORE
                    and (
                        boundary_only_rejection
                        or clean_boundaries is False
                        or includes_setup is True
                    )
                ):
                    boundary_fallbacks.append(
                        (
                            source_cut_candidate_duration(candidate),
                            -confidence,
                            order,
                            candidate,
                            candidate_payload,
                            rejection_reasons,
                        )
                    )
                continue
        if rejection_reasons:
            continue
        if confidence < SOURCE_CUT_MIN_SELECTED_SCORE:
            continue
        source_tie_breaker = 0.0 if movement_cut else -float(candidate.window.end_seconds)
        passing.append(
            (
                source_cut_candidate_duration(candidate),
                -confidence,
                source_tie_breaker,
                order,
                candidate,
                candidate_payload,
            )
        )
    if not passing:
        if movement_cut and boundary_fallbacks:
            _duration, negative_confidence, _order, selected, selected_payload, rejection_reasons = min(boundary_fallbacks)
            selected_payload = dict(selected_payload)
            selected_payload["movementCutBoundaryFallback"] = True
            selected_payload["movementCutBoundaryFallbackRejectionReasons"] = rejection_reasons
            return selected, selected_payload, min(-negative_confidence, MOVEMENT_CUT_BOUNDARY_FALLBACK_SCORE_CAP)
        return None
    _duration, negative_confidence, _source_tie_breaker, _order, selected, selected_payload = min(passing)
    return selected, selected_payload, -negative_confidence


def parse_source_cut_candidate_choice(
    raw: str,
    candidates: list[SourceCutCandidate],
    *,
    has_contract: bool = True,
) -> LoopRanking | None:
    payload = extract_json_object_with_trailing_repair(raw)
    if not isinstance(payload, dict):
        return None
    if not source_cut_scorecard_candidate_payloads(payload):
        return None
    return build_source_cut_scorecard_ranking(
        payload,
        candidates,
        has_contract=has_contract,
        raw=raw,
    )


def parse_movement_cut_candidate_choice(
    raw: str,
    candidates: list[SourceCutCandidate],
    *,
    min_duration_seconds: float | None = None,
) -> LoopRanking | None:
    payload = extract_json_object_with_trailing_repair(raw)
    if not isinstance(payload, dict):
        return None
    binary_choice = parse_binary_source_cut_candidate_choice(
        payload,
        candidates,
        movement_cut=True,
        min_duration_seconds=min_duration_seconds,
    )
    if binary_choice is not None:
        selected, selected_payload, score = binary_choice
        reason = str(selected_payload.get("reason") or "movement_cut_binary_complete_movement_verified")
        ranking_payload = dict(selected_payload)
        ranking_payload["target_exercise_match_score"] = parse_source_cut_target_exercise_match_score(selected_payload)
        ranking_payload["movementCutRejectionReasons"] = source_cut_choice_rejection_reasons(selected_payload)
        ranking_payload["selectedCandidateId"] = selected.candidate_id
        ranking_payload["selected_section_start_seconds"] = selected.window.start_seconds
        ranking_payload["selected_section_end_seconds"] = selected.window.end_seconds
        ranking_payload["movementCutCandidates"] = source_cut_candidates_payload(candidates)
        ranking_payload["movementCutBinaryCandidateResults"] = candidate_binary_result_payloads(payload)
        ranking_payload["movementCutSelectionPolicy"] = "shortest_binary_complete_movement"
        if parse_optional_bool(ranking_payload.get("movementCutBoundaryFallback")) is True:
            ranking_payload["movementCutSelectionPolicy"] = "shortest_complete_boundary_fallback"
        ranking_payload["finalCutResponsibility"] = "movement_window_selection_only"
        reasons = [
            reason,
            "movement_cut_binary_complete_movement_verified",
            "movement_cut_candidate_window_choice",
        ]
        if parse_optional_bool(ranking_payload.get("movementCutBoundaryFallback")) is True:
            reasons.append("movement_cut_complete_boundary_fallback")
        return LoopRanking(
            score=score,
            reasons=dedupe_text(reasons),
            raw_response=raw,
            payload=ranking_payload,
            model_score=score,
        )
    if candidate_binary_result_payloads(payload):
        return None
    selected_id = normalize_source_cut_candidate_id(payload.get("selected_candidate_id"))
    candidates_by_id = {
        normalize_source_cut_candidate_id(candidate.candidate_id): candidate
        for candidate in candidates
    }
    selected = candidates_by_id.get(selected_id)
    if selected is None:
        return None
    validity_values = [
        parse_optional_bool(payload.get("valid_movement_cut")),
        parse_optional_bool(payload.get("complete_movement")),
        parse_optional_bool(payload.get("valid_single_movement")),
    ]
    if any(value is False for value in validity_values) or not any(value is True for value in validity_values):
        return None
    if parse_optional_bool(payload.get("clean_boundaries")) is False:
        return None
    if parse_optional_bool(payload.get("includes_setup_or_reset")) is True:
        return None
    rejection_reasons = source_cut_choice_rejection_reasons(payload)
    if rejection_reasons:
        return None
    score = parse_optional_float(payload.get("score"))
    if score is None:
        score = 0.0
    if score > 1.0:
        score = score / 100.0
    score = clamp_unit(score)
    reason = str(payload.get("reason") or "movement_cut_candidate_window_choice")
    reasons = [reason, "movement_cut_candidate_window_choice"]
    if parse_optional_bool(payload.get("includes_setup_or_reset")) is True:
        reasons.append("movement_cut_includes_setup_or_reset")
    if parse_optional_bool(payload.get("clean_boundaries")) is False:
        reasons.append("movement_cut_boundaries_not_clean")
    ranking_payload = dict(payload)
    ranking_payload["target_exercise_match_score"] = parse_source_cut_target_exercise_match_score(payload)
    ranking_payload["movementCutRejectionReasons"] = rejection_reasons
    ranking_payload["selectedCandidateId"] = selected.candidate_id
    ranking_payload["selected_section_start_seconds"] = selected.window.start_seconds
    ranking_payload["selected_section_end_seconds"] = selected.window.end_seconds
    ranking_payload["movementCutCandidates"] = source_cut_candidates_payload(candidates)
    ranking_payload["finalCutResponsibility"] = "movement_window_selection_only"
    return LoopRanking(
        score=score,
        reasons=reasons,
        raw_response=raw,
        payload=ranking_payload,
        model_score=score,
    )


def cut_candidate_error_payload(candidate_ids: list[str], exc: BaseException, *, split_attempted: bool) -> dict[str, Any]:
    message = str(exc)
    if len(message) > 1200:
        message = message[:1200] + "...[truncated]"
    return {
        "candidateIds": candidate_ids,
        "errorType": exc.__class__.__name__,
        "message": message,
        "splitAttempted": split_attempted,
    }


def cut_candidate_duration_groups(candidates: list[SourceCutCandidate]) -> list[list[SourceCutCandidate]]:
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            source_cut_candidate_duration(candidate),
            candidate.window.start_seconds,
            candidate.window.end_seconds,
            candidate.candidate_id,
        ),
    )
    groups: list[list[SourceCutCandidate]] = []
    current: list[SourceCutCandidate] = []
    current_duration: float | None = None
    for candidate in ordered:
        duration = source_cut_candidate_duration(candidate)
        if current and current_duration is not None and abs(duration - current_duration) > CUT_CANDIDATE_DURATION_BUCKET_SECONDS:
            groups.append(current)
            current = []
            current_duration = None
        if current_duration is None:
            current_duration = duration
        current.append(candidate)
    if current:
        groups.append(current)
    return groups


def chunk_cut_candidates(candidates: list[SourceCutCandidate], batch_size: int) -> list[list[SourceCutCandidate]]:
    size = max(1, int(batch_size))
    return [candidates[index : index + size] for index in range(0, len(candidates), size)]


def cut_candidates_with_ids(candidates: list[SourceCutCandidate], candidate_ids: list[str]) -> list[SourceCutCandidate]:
    wanted = set(candidate_ids)
    return [candidate for candidate in candidates if candidate.candidate_id in wanted]


def cut_candidate_vlm_caption_kwargs(
    *,
    max_tokens: int = CUT_CANDIDATE_VLM_MAX_TOKENS,
    request_timeout_seconds: float | None = CUT_CANDIDATE_VLM_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    kwargs = {
        "max_tokens": max(1, int(max_tokens)),
        "disable_reasoning": CUT_CANDIDATE_VLM_DISABLE_REASONING,
        "temperature": CUT_CANDIDATE_VLM_TEMPERATURE,
        "top_p": CUT_CANDIDATE_VLM_TOP_P,
        "json_response": True,
    }
    if request_timeout_seconds is not None:
        requested_timeout = float(request_timeout_seconds)
        kwargs["request_timeout_seconds"] = (
            0.0 if requested_timeout <= 0.0 else max(1.0, requested_timeout)
        )
    return kwargs


def source_cut_vlm_caption_kwargs() -> dict[str, Any]:
    return cut_candidate_vlm_caption_kwargs(
        max_tokens=SOURCE_CUT_CANDIDATE_VLM_MAX_TOKENS,
        request_timeout_seconds=SOURCE_CUT_CANDIDATE_VLM_REQUEST_TIMEOUT_SECONDS,
    )


def collect_ranking_payload_rows(rankings: Iterable[LoopRanking], key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for ranking in rankings:
        payload = ranking.payload if isinstance(ranking.payload, dict) else {}
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            row_id = str(item.get("id") or item.get("candidateId") or "")
            if row_id and row_id in seen_ids:
                continue
            if row_id:
                seen_ids.add(row_id)
            rows.append(item)
    return rows


def empty_cut_candidate_batch_result() -> CutCandidateBatchResult:
    return CutCandidateBatchResult(
        rankings=[],
        raw_responses=[],
        errors=[],
        reviewed_candidate_ids=[],
    )


def combine_cut_candidate_batch_results(results: Iterable[CutCandidateBatchResult]) -> CutCandidateBatchResult:
    rankings: list[LoopRanking] = []
    raw_responses: list[str] = []
    errors: list[dict[str, Any]] = []
    reviewed_candidate_ids: list[str] = []
    for result in results:
        rankings.extend(result.rankings)
        raw_responses.extend(result.raw_responses)
        errors.extend(result.errors)
        for candidate_id in result.reviewed_candidate_ids:
            if candidate_id not in reviewed_candidate_ids:
                reviewed_candidate_ids.append(candidate_id)
    return CutCandidateBatchResult(
        rankings=rankings,
        raw_responses=raw_responses,
        errors=errors,
        reviewed_candidate_ids=reviewed_candidate_ids,
    )


def rank_cut_candidate_batches_with_caption_images(
    *,
    candidates: list[SourceCutCandidate],
    caption_images: Callable[..., str],
    prompt_builder: Callable[[list[SourceCutCandidate]], str],
    parser: Callable[[str, list[SourceCutCandidate]], LoopRanking | None],
    max_candidates_per_request: int = CUT_CANDIDATE_MAX_VLM_BATCH_SIZE,
    max_workers: int = 1,
    caption_image_kwargs: dict[str, Any] | None = None,
) -> tuple[CutCandidateBatchResult, int]:
    batches = chunk_cut_candidates(candidates, max_candidates_per_request)
    if max(1, int(max_workers)) <= 1 or len(batches) <= 1:
        batch_results = [
            rank_cut_candidate_batch_with_caption_images(
                candidates=batch,
                caption_images=caption_images,
                prompt_builder=prompt_builder,
                parser=parser,
                caption_image_kwargs=caption_image_kwargs,
            )
            for batch in batches
        ]
    else:
        batch_results_by_index: list[CutCandidateBatchResult | None] = [None] * len(batches)
        with ThreadPoolExecutor(max_workers=min(max(1, int(max_workers)), len(batches))) as executor:
            futures = {
                executor.submit(
                    rank_cut_candidate_batch_with_caption_images,
                    candidates=batch,
                    caption_images=caption_images,
                    prompt_builder=prompt_builder,
                    parser=parser,
                    caption_image_kwargs=caption_image_kwargs,
                ): index
                for index, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                index = futures[future]
                batch = batches[index]
                try:
                    batch_results_by_index[index] = future.result()
                except Exception as exc:
                    batch_results_by_index[index] = CutCandidateBatchResult(
                        rankings=[],
                        raw_responses=[],
                        errors=[
                            cut_candidate_error_payload(
                                [candidate.candidate_id for candidate in batch],
                                exc,
                                split_attempted=False,
                            )
                        ],
                        reviewed_candidate_ids=[candidate.candidate_id for candidate in batch],
                    )
        batch_results = [
            result
            for result in batch_results_by_index
            if result is not None
        ]
    return combine_cut_candidate_batch_results(batch_results), len(batches)


def selected_candidate_id_from_cut_ranking(ranking: LoopRanking) -> str:
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    return normalize_source_cut_candidate_id(
        payload.get("selectedCandidateId")
        or payload.get("selected_candidate_id")
        or payload.get("candidateId")
        or payload.get("id")
    )


def candidate_for_cut_ranking(
    ranking: LoopRanking,
    candidates_by_id: dict[str, SourceCutCandidate],
    candidates: list[SourceCutCandidate],
) -> SourceCutCandidate | None:
    candidate_id = selected_candidate_id_from_cut_ranking(ranking)
    if candidate_id:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is not None:
            return candidate
    selected_window = selected_window_from_cut_ranking(ranking)
    if selected_window is None:
        return None
    for candidate in candidates:
        if (
            abs(candidate.window.start_seconds - selected_window.start_seconds) <= 0.02
            and abs(candidate.window.end_seconds - selected_window.end_seconds) <= 0.02
        ):
            return candidate
    return None


def source_cut_progressive_level_index(candidate: SourceCutCandidate) -> int:
    level_index = parse_optional_float(candidate.chunking.get("levelIndex")) if candidate.chunking else None
    if level_index is None:
        return 0
    return max(0, int(level_index))


def source_cut_progressive_level_stable_candidate_ids(
    *,
    level_candidates: list[SourceCutCandidate],
    passing_candidates: list[SourceCutCandidate],
) -> set[str]:
    if not passing_candidates:
        return set()
    passing_ids = {candidate.candidate_id for candidate in passing_candidates}
    if len(level_candidates) <= 2:
        return passing_ids

    passing_sorted = sorted(passing_candidates, key=lambda candidate: candidate.window.start_seconds)
    clusters: list[list[SourceCutCandidate]] = []
    current: list[SourceCutCandidate] = []
    previous: SourceCutCandidate | None = None
    for candidate in passing_sorted:
        if previous is None:
            current = [candidate]
        else:
            overlap = max(
                0.0,
                min(previous.window.end_seconds, candidate.window.end_seconds)
                - max(previous.window.start_seconds, candidate.window.start_seconds),
            )
            min_duration = max(
                1e-6,
                min(source_cut_candidate_duration(previous), source_cut_candidate_duration(candidate)),
            )
            if overlap / min_duration >= SOURCE_CUT_PROGRESSIVE_MIN_CLUSTER_OVERLAP_RATIO:
                current.append(candidate)
            else:
                if current:
                    clusters.append(current)
                current = [candidate]
        previous = candidate
    if current:
        clusters.append(current)

    stable_clusters = [
        cluster
        for cluster in clusters
        if len(cluster) >= SOURCE_CUT_PROGRESSIVE_MIN_CLUSTER_SIZE
    ]
    if not stable_clusters:
        return set()
    best_cluster = max(
        stable_clusters,
        key=lambda cluster: (
            len(cluster),
            -min(candidate.window.start_seconds for candidate in cluster),
        ),
    )
    return {candidate.candidate_id for candidate in best_cluster}


def progressive_source_cut_stable_levels(
    rankings: list[LoopRanking],
    candidates: list[SourceCutCandidate],
    *,
    stop_at_first_unstable_after_stable: bool = True,
) -> tuple[list[dict[str, Any]], int | None]:
    candidates_by_id = {
        normalize_source_cut_candidate_id(candidate.candidate_id): candidate
        for candidate in candidates
    }
    ranking_by_candidate_id: dict[str, LoopRanking] = {}
    for ranking in rankings:
        candidate = candidate_for_cut_ranking(ranking, candidates_by_id, candidates)
        if candidate is None or selected_window_from_cut_ranking(ranking) is None:
            continue
        ranking_by_candidate_id[candidate.candidate_id] = ranking

    if not ranking_by_candidate_id:
        return [], None

    candidates_by_level: dict[int, list[SourceCutCandidate]] = {}
    for candidate in candidates:
        candidates_by_level.setdefault(source_cut_progressive_level_index(candidate), []).append(candidate)

    stable_levels: list[dict[str, Any]] = []
    stopped_at_unstable_level: int | None = None
    for level_index in sorted(candidates_by_level):
        level_candidates = sorted(
            candidates_by_level[level_index],
            key=lambda candidate: (candidate.window.start_seconds, candidate.window.end_seconds),
        )
        passing_candidates = [
            candidate
            for candidate in level_candidates
            if candidate.candidate_id in ranking_by_candidate_id
        ]
        stable_candidate_ids = source_cut_progressive_level_stable_candidate_ids(
            level_candidates=level_candidates,
            passing_candidates=passing_candidates,
        )
        if not stable_candidate_ids:
            if stable_levels:
                if stopped_at_unstable_level is None:
                    stopped_at_unstable_level = level_index
                if stop_at_first_unstable_after_stable:
                    break
            continue

        eligible_rankings = [
            (ranking_by_candidate_id[candidate.candidate_id], candidate)
            for candidate in passing_candidates
            if candidate.candidate_id in stable_candidate_ids
        ]
        if not eligible_rankings:
            continue
        best_ranking, best_candidate = min(
            eligible_rankings,
            key=lambda item: (
                -item[0].score,
                item[1].window.start_seconds,
                item[1].window.end_seconds,
            ),
        )
        stable_levels.append(
            {
                "levelIndex": level_index,
                "candidateCount": len(level_candidates),
                "passingCandidateCount": len(passing_candidates),
                "stablePassingCandidateCount": len(stable_candidate_ids),
                "selectedCandidateId": best_candidate.candidate_id,
                "selectedStartSeconds": best_candidate.window.start_seconds,
                "selectedEndSeconds": best_candidate.window.end_seconds,
                "selectedDurationSeconds": source_cut_candidate_duration(best_candidate),
                "levelDurationSeconds": best_candidate.chunking.get("levelDurationSeconds")
                if best_candidate.chunking
                else source_cut_candidate_duration(best_candidate),
                "levelRatio": best_candidate.chunking.get("levelRatio") if best_candidate.chunking else None,
                "ranking": best_ranking,
            }
        )

    return stable_levels, stopped_at_unstable_level


def select_progressive_source_cut_ranking(
    rankings: list[LoopRanking],
    candidates: list[SourceCutCandidate],
    *,
    pad_one_stable_level: bool = True,
    stop_at_first_unstable_after_stable: bool = True,
) -> LoopRanking | None:
    stable_levels, stopped_at_unstable_level = progressive_source_cut_stable_levels(
        rankings,
        candidates,
        stop_at_first_unstable_after_stable=stop_at_first_unstable_after_stable,
    )
    if not stable_levels:
        return None

    all_stable_to_floor = stopped_at_unstable_level is None
    selected_level = (
        stable_levels[-2]
        if pad_one_stable_level and len(stable_levels) >= 2
        else stable_levels[-2]
        if all_stable_to_floor and len(stable_levels) >= 2
        else stable_levels[-1]
    )
    ranking = selected_level["ranking"]
    payload = dict(ranking.payload) if isinstance(ranking.payload, dict) else {}
    payload["sourceCutProgressiveSelection"] = {
        "strategy": "progressive_multiscale_sliding_stable_level",
        "selectedLevelIndex": selected_level["levelIndex"],
        "deepestStableLevelIndex": stable_levels[-1]["levelIndex"],
        "stoppedAtUnstableLevelIndex": stopped_at_unstable_level,
        "allStableToFloor": all_stable_to_floor,
        "stableLevels": [
            {
                key: value
                for key, value in level.items()
                if key != "ranking"
            }
            for level in stable_levels
        ],
    }
    payload["sourceCutSelectionPolicy"] = "progressive_multiscale_stable_level_then_score"
    return replace(
        ranking,
        payload=payload,
        reasons=dedupe_text([*ranking.reasons, "progressive_source_cut_stable_level_selection"]),
    )


def rank_cut_candidate_batch_with_caption_images(
    *,
    candidates: list[SourceCutCandidate],
    caption_images: Callable[..., str],
    prompt_builder: Callable[[list[SourceCutCandidate]], str],
    parser: Callable[[str, list[SourceCutCandidate]], LoopRanking | None],
    caption_image_kwargs: dict[str, Any] | None = None,
) -> CutCandidateBatchResult:
    if not candidates:
        return empty_cut_candidate_batch_result()
    if len(candidates) > 1:
        return combine_cut_candidate_batch_results(
            [
                rank_cut_candidate_batch_with_caption_images(
                    candidates=[candidate],
                    caption_images=caption_images,
                    prompt_builder=prompt_builder,
                    parser=parser,
                    caption_image_kwargs=caption_image_kwargs,
                )
                for candidate in candidates
            ]
        )
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    try:
        request_kwargs = dict(caption_image_kwargs or {})
        raw = caption_images(
            frame_paths=[path for candidate in candidates for path in candidate.frame_paths],
            prompt=prompt_builder(candidates),
            **request_kwargs,
        )
    except Exception as exc:
        return CutCandidateBatchResult(
            rankings=[],
            raw_responses=[],
            errors=[cut_candidate_error_payload(candidate_ids, exc, split_attempted=False)],
            reviewed_candidate_ids=candidate_ids,
        )
    ranking = parser(raw, candidates)
    return CutCandidateBatchResult(
        rankings=[ranking] if ranking is not None else [],
        raw_responses=[raw],
        errors=[],
        reviewed_candidate_ids=candidate_ids,
    )


def annotate_progressive_source_cut_review_payload(
    ranking: LoopRanking,
    *,
    all_level_indices: list[int],
    reviewed_level_indices: list[int],
    level_candidate_counts: dict[int, int],
    early_stopped: bool,
) -> LoopRanking:
    payload = dict(ranking.payload) if isinstance(ranking.payload, dict) else {}
    selection_payload = payload.get("sourceCutProgressiveSelection")
    selection = dict(selection_payload) if isinstance(selection_payload, dict) else {}
    reviewed_set = set(reviewed_level_indices)
    selection.update(
        {
            "reviewOrder": "smallest_windows_first",
            "stopRule": "first_stable_level_plus_next_wider_stable_level",
            "earlyStopped": bool(early_stopped),
            "reviewedLevelIndices": reviewed_level_indices,
            "unreviewedLevelIndices": [
                level_index
                for level_index in all_level_indices
                if level_index not in reviewed_set
            ],
            "levelCandidateCounts": {
                str(level_index): count
                for level_index, count in sorted(level_candidate_counts.items())
            },
        }
    )
    payload["sourceCutProgressiveSelection"] = selection
    reasons = [*ranking.reasons]
    reasons.append(
        "progressive_source_cut_early_stop"
        if early_stopped
        else "progressive_source_cut_exhausted_levels"
    )
    return replace(
        ranking,
        payload=payload,
        reasons=dedupe_text(reasons),
    )


def rank_progressive_source_cut_candidates_with_caption_images(
    *,
    candidates: list[SourceCutCandidate],
    caption_images: Callable[..., str],
    prompt_builder: Callable[[list[SourceCutCandidate]], str],
    parser: Callable[[str, list[SourceCutCandidate]], LoopRanking | None],
    max_candidates_per_request: int = SOURCE_CUT_CANDIDATE_MAX_VLM_BATCH_SIZE,
    max_workers: int = 1,
    caption_image_kwargs: dict[str, Any] | None = None,
) -> CutCandidateBatchChoice:
    started = time.perf_counter()
    if not candidates:
        return CutCandidateBatchChoice(
            ranking=None,
            raw_responses=[],
            errors=[],
            reviewed_candidate_ids=[],
            reviewed_batch_count=0,
            elapsed_seconds=elapsed_seconds(started),
            rankings=[],
        )

    candidates_by_level: dict[int, list[SourceCutCandidate]] = {}
    for candidate in candidates:
        candidates_by_level.setdefault(source_cut_progressive_level_index(candidate), []).append(candidate)
    all_level_indices = sorted(candidates_by_level)
    review_level_indices = sorted(candidates_by_level, reverse=True)
    level_candidate_counts = {
        level_index: len(level_candidates)
        for level_index, level_candidates in candidates_by_level.items()
    }

    reviewed_level_indices: list[int] = []
    partial_results: list[CutCandidateBatchResult] = []
    reviewed_batch_count = 0

    for level_index in review_level_indices:
        level_candidates = sorted(
            candidates_by_level[level_index],
            key=lambda candidate: (
                candidate.window.start_seconds,
                candidate.window.end_seconds,
                candidate.candidate_id,
            ),
        )
        result, batch_count = rank_cut_candidate_batches_with_caption_images(
            candidates=level_candidates,
            caption_images=caption_images,
            prompt_builder=prompt_builder,
            parser=parser,
            max_candidates_per_request=max_candidates_per_request,
            max_workers=max_workers,
            caption_image_kwargs=caption_image_kwargs,
        )
        partial_results.append(result)
        reviewed_batch_count += batch_count
        reviewed_level_indices.append(level_index)
        combined = combine_cut_candidate_batch_results(partial_results)
        stable_levels, _stopped_at_unstable_level = progressive_source_cut_stable_levels(
            combined.rankings,
            candidates,
            stop_at_first_unstable_after_stable=False,
        )
        if len(stable_levels) < 2:
            continue
        best_ranking = select_progressive_source_cut_ranking(
            combined.rankings,
            candidates,
            pad_one_stable_level=True,
            stop_at_first_unstable_after_stable=False,
        )
        if best_ranking is None:
            continue
        return CutCandidateBatchChoice(
            ranking=annotate_progressive_source_cut_review_payload(
                best_ranking,
                all_level_indices=all_level_indices,
                reviewed_level_indices=reviewed_level_indices,
                level_candidate_counts=level_candidate_counts,
                early_stopped=True,
            ),
            raw_responses=combined.raw_responses,
            errors=combined.errors,
            reviewed_candidate_ids=combined.reviewed_candidate_ids,
            reviewed_batch_count=max(
                reviewed_batch_count,
                len(combined.raw_responses) + len(combined.errors),
            ),
            elapsed_seconds=elapsed_seconds(started),
            rankings=combined.rankings,
        )

    combined = combine_cut_candidate_batch_results(partial_results)
    best_ranking = select_progressive_source_cut_ranking(
        combined.rankings,
        candidates,
        pad_one_stable_level=True,
        stop_at_first_unstable_after_stable=False,
    )
    if best_ranking is not None:
        best_ranking = annotate_progressive_source_cut_review_payload(
            best_ranking,
            all_level_indices=all_level_indices,
            reviewed_level_indices=reviewed_level_indices,
            level_candidate_counts=level_candidate_counts,
            early_stopped=False,
        )
    return CutCandidateBatchChoice(
        ranking=best_ranking,
        raw_responses=combined.raw_responses,
        errors=combined.errors,
        reviewed_candidate_ids=combined.reviewed_candidate_ids,
        reviewed_batch_count=max(
            reviewed_batch_count,
            len(combined.raw_responses) + len(combined.errors),
        ),
        elapsed_seconds=elapsed_seconds(started),
        rankings=combined.rankings,
    )


def rank_cut_candidates_shortest_first_with_caption_images(
    *,
    candidates: list[SourceCutCandidate],
    caption_images: Callable[..., str],
    prompt_builder: Callable[[list[SourceCutCandidate]], str],
    parser: Callable[[str, list[SourceCutCandidate]], LoopRanking | None],
    max_candidates_per_request: int = CUT_CANDIDATE_MAX_VLM_BATCH_SIZE,
    max_workers: int = 1,
    prefer_later_equal_duration: bool = False,
    prefer_largest_padded_candidate: bool = False,
    progressive_source_selection: bool = False,
    caption_image_kwargs: dict[str, Any] | None = None,
) -> CutCandidateBatchChoice:
    started = time.perf_counter()
    if progressive_source_selection:
        return rank_progressive_source_cut_candidates_with_caption_images(
            candidates=candidates,
            caption_images=caption_images,
            prompt_builder=prompt_builder,
            parser=parser,
            max_candidates_per_request=max_candidates_per_request,
            max_workers=max_workers,
            caption_image_kwargs=caption_image_kwargs,
        )
    ordered_candidates = [
        candidate
        for duration_group in cut_candidate_duration_groups(candidates)
        for candidate in duration_group
    ]
    combined, batch_count = rank_cut_candidate_batches_with_caption_images(
        candidates=ordered_candidates,
        caption_images=caption_images,
        prompt_builder=prompt_builder,
        parser=parser,
        max_candidates_per_request=max_candidates_per_request,
        max_workers=max_workers,
        caption_image_kwargs=caption_image_kwargs,
    )
    def ranking_selection_key(ranking: LoopRanking) -> tuple[float, float, float]:
        selected_window = selected_window_from_cut_ranking(ranking)
        duration = (
            window_duration_seconds(selected_window)
            if selected_window is not None
            else 0.0
        )
        if prefer_largest_padded_candidate:
            return (
                -ranking.score,
                -duration if selected_window is not None else math.inf,
                -selected_window.end_seconds if selected_window is not None else 0.0,
            )
        return (
            duration if selected_window is not None else math.inf,
            -ranking.score,
            -selected_window.end_seconds
            if prefer_later_equal_duration and selected_window is not None
            else 0.0,
        )

    best_ranking = (
        min(
            combined.rankings,
            key=ranking_selection_key,
        )
        if combined.rankings
        else None
    )
    return CutCandidateBatchChoice(
        ranking=best_ranking,
        raw_responses=combined.raw_responses,
        errors=combined.errors,
        reviewed_candidate_ids=combined.reviewed_candidate_ids,
        reviewed_batch_count=max(batch_count, len(combined.raw_responses) + len(combined.errors)),
        elapsed_seconds=elapsed_seconds(started),
        rankings=combined.rankings,
    )


def movement_cut_candidate_source_motion_coverage_ratio(candidate: SourceCutCandidate) -> float:
    if not candidate.motion_coverage:
        return 1.0
    value = parse_optional_float(candidate.motion_coverage.get("sourceMotionCoverageRatio"))
    return 1.0 if value is None else clamp_unit(value)


def movement_cut_candidate_has_complete_phase(candidate: SourceCutCandidate) -> bool:
    metrics = candidate.motion_coverage.get("candidateFullRepetitionPhaseCompletenessMetrics") if candidate.motion_coverage else None
    return isinstance(metrics, dict) and bool(metrics.get("required")) and bool(metrics.get("passed"))


def movement_cut_candidate_target_motion_score(candidate: SourceCutCandidate) -> float:
    metrics = candidate.motion_coverage.get("targetMotionGate") if candidate.motion_coverage else None
    if not isinstance(metrics, dict):
        return 1.0
    value = parse_optional_float(metrics.get("targetMotionRangeRatio"))
    minimum = parse_optional_float(metrics.get("minTargetMotionRangeRatio"))
    if value is None or minimum is None or minimum <= 1e-6:
        return 1.0
    return clamp_unit(value / minimum)


def movement_cut_candidate_confidence_key(candidate: SourceCutCandidate) -> tuple[int, float, float, float]:
    duration = max(0.0, candidate.window.end_seconds - candidate.window.start_seconds)
    return (
        1 if movement_cut_candidate_has_complete_phase(candidate) else 0,
        movement_cut_candidate_source_motion_coverage_ratio(candidate),
        movement_cut_candidate_target_motion_score(candidate),
        -duration,
    )


def deterministic_movement_cut_ranking_if_confident(
    *,
    candidates: list[SourceCutCandidate],
    all_candidates: list[SourceCutCandidate],
    visual_candidate_count: int,
    motion_coverage_fallback: bool,
    hard_motion_rejected_count: int,
    use_exercise_motion_contract: bool,
    exercise_motion_contract: dict[str, Any] | None,
) -> LoopRanking | None:
    if motion_coverage_fallback or not candidates:
        return None
    ranked = sorted(candidates, key=movement_cut_candidate_confidence_key, reverse=True)
    selected = ranked[0]
    selected_coverage = movement_cut_candidate_source_motion_coverage_ratio(selected)
    selected_complete_phase = movement_cut_candidate_has_complete_phase(selected)
    if len(ranked) > 1 and not (
        selected_complete_phase
        and selected_coverage >= MOVEMENT_CUT_DETERMINISTIC_DIRECT_MIN_COVERAGE_RATIO
    ):
        return None

    score = MOVEMENT_CUT_DETERMINISTIC_DIRECT_SCORE
    payload = {
        "score": score,
        "modelScore": score,
        "selectedCandidateId": selected.candidate_id,
        "selected_section_start_seconds": selected.window.start_seconds,
        "selected_section_end_seconds": selected.window.end_seconds,
        "movementCutCandidates": source_cut_candidates_payload(all_candidates),
        "movementCutVlmInputCandidates": [],
        "movementCutVisualIntegrityFilteredCount": len(all_candidates) - visual_candidate_count,
        "movementCutMotionCoverageFilteredCount": visual_candidate_count - len(candidates),
        "movementCutMotionCoverageFallback": False,
        "movementCutHardMotionRejectedCount": hard_motion_rejected_count,
        "exerciseMotionContractEnabled": use_exercise_motion_contract,
        "movementCutDeterministicDirectSelection": True,
        "movementCutSelectedCoverageRatio": selected_coverage,
        "movementCutSelectedCompletePhase": selected_complete_phase,
        "finalCutResponsibility": "deterministic_movement_window_selection",
    }
    if exercise_motion_contract is not None:
        payload["exerciseMotionContract"] = exercise_motion_contract
    return LoopRanking(
        score=score,
        reasons=[
            "movement_cut_deterministic_direct_selection",
            "movement_cut_candidate_window_choice",
        ],
        payload=payload,
        model_score=score,
    )


def selected_window_from_cut_ranking(ranking: LoopRanking) -> DetectionWindow | None:
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    start = first_float(
        payload.get("selected_section_start_seconds"),
        payload.get("selectedSectionStartSeconds"),
        payload.get("startSeconds"),
    )
    end = first_float(
        payload.get("selected_section_end_seconds"),
        payload.get("selectedSectionEndSeconds"),
        payload.get("endSeconds"),
    )
    if start is None or end is None or end <= start:
        return None
    return DetectionWindow(index=0, start_seconds=float(start), end_seconds=float(end))


def window_duration_seconds(window: DetectionWindow) -> float:
    return max(0.0, float(window.end_seconds) - float(window.start_seconds))


def selected_window_is_materially_shorter(
    *,
    parent_window: DetectionWindow,
    child_window: DetectionWindow,
) -> bool:
    parent_duration = window_duration_seconds(parent_window)
    child_duration = window_duration_seconds(child_window)
    if child_duration < SOURCE_CUT_REFINEMENT_MIN_SECONDS:
        return False
    required_improvement = max(
        SOURCE_CUT_REFINEMENT_MIN_ABSOLUTE_IMPROVEMENT_SECONDS,
        parent_duration * SOURCE_CUT_REFINEMENT_MIN_RELATIVE_IMPROVEMENT,
    )
    return child_duration <= parent_duration - required_improvement


def cut_refinement_stage_payload(
    *,
    ranking: LoopRanking,
    parent_window: DetectionWindow,
    selected_window: DetectionWindow,
    stage_index: int,
    candidates_key: str,
    vlm_candidates_key: str,
) -> dict[str, Any]:
    payload = ranking.payload if isinstance(ranking.payload, dict) else {}
    stage: dict[str, Any] = {
        "stageIndex": stage_index,
        "parentStartSeconds": parent_window.start_seconds,
        "parentEndSeconds": parent_window.end_seconds,
        "parentDurationSeconds": window_duration_seconds(parent_window),
        "selectedStartSeconds": selected_window.start_seconds,
        "selectedEndSeconds": selected_window.end_seconds,
        "selectedDurationSeconds": window_duration_seconds(selected_window),
        "selectedCandidateId": payload.get("selectedCandidateId"),
        "score": ranking.score,
        "selectionPolicy": payload.get("sourceCutSelectionPolicy")
        or payload.get("movementCutSelectionPolicy"),
    }
    if isinstance(payload.get(candidates_key), list):
        stage[candidates_key] = payload.get(candidates_key)
    if isinstance(payload.get(vlm_candidates_key), list):
        stage[vlm_candidates_key] = payload.get(vlm_candidates_key)
    return stage


def prepend_cut_refinement_stage(
    ranking: LoopRanking,
    *,
    stages_key: str,
    stage: dict[str, Any],
) -> LoopRanking:
    payload = dict(ranking.payload) if isinstance(ranking.payload, dict) else {}
    existing = payload.get(stages_key)
    stages = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    stages = [stage, *stages]
    payload[stages_key] = stages
    payload["cutRefinementApplied"] = True
    payload["cutRefinementStageCount"] = len(stages)
    return replace(
        ranking,
        payload=payload,
        reasons=dedupe_text([*ranking.reasons, "recursive_shortest_complete_movement_refinement"]),
    )


def rank_movement_cut_candidates_with_caption_images(
    *,
    item: ReviewItem,
    timeline_window: DetectionWindow,
    chunk_estimate: Any,
    output_dir: Path,
    frame_count: int,
    caption_images: Callable[..., str],
    use_exercise_motion_contract: bool = True,
    max_vlm_workers: int = 1,
    _refinement_depth: int = 0,
) -> tuple[LoopRanking, float, float] | None:
    candidate_windows = build_source_cut_candidate_windows(
        window=timeline_window,
        chunk_estimate=chunk_estimate,
        min_estimated_duration_ratio=MOVEMENT_CUT_MIN_ESTIMATED_DURATION_RATIO,
    )
    if not candidate_windows:
        return None
    estimated_min_duration = parse_optional_float(getattr(chunk_estimate, "rep_duration_min_sec", None))
    min_selected_duration_seconds = None
    if estimated_min_duration is not None and estimated_min_duration > 0.0:
        min_selected_duration_seconds = min(
            window_duration_seconds(timeline_window),
            estimated_min_duration * MOVEMENT_CUT_MIN_SELECTED_ESTIMATED_DURATION_RATIO,
        )
    exercise_motion_contract = (
        exercise_motion_contract_for_review_item(item, None)
        if use_exercise_motion_contract
        else None
    )
    render_started = time.perf_counter()
    candidates: list[SourceCutCandidate] = []
    all_candidates: list[SourceCutCandidate] = []
    for index, candidate_window in enumerate(candidate_windows):
        candidate_id = source_cut_candidate_id_for_index(index)
        candidate_output_dir = output_dir / f"movement_cut_candidate_{candidate_id}"
        frame_paths = render_source_review_window_contact_sheet(
            item=item,
            window=candidate_window,
            output_dir=candidate_output_dir,
            frame_count=min(max(8, frame_count // 2), 16),
        )
        candidate = build_source_cut_candidate(
            candidate_id=candidate_id,
            candidate_window=candidate_window,
            contact_sheet_paths=frame_paths,
            output_dir=candidate_output_dir,
        )
        if candidate is not None:
            candidate = replace(
                candidate,
                motion_coverage=movement_cut_candidate_motion_coverage_metrics(
                    item=item,
                    parent_window=timeline_window,
                    candidate_window=candidate_window,
                    chunk_estimate=chunk_estimate,
                    exercise_motion_contract=exercise_motion_contract,
                ),
            )
            all_candidates.append(candidate)
            if source_cut_candidate_passes_visual_integrity(candidate):
                candidates.append(candidate)
    render_seconds = elapsed_seconds(render_started)
    visual_integrity_fallback = not candidates and bool(all_candidates)
    if visual_integrity_fallback:
        candidates = list(all_candidates)
    if not candidates:
        return (
            LoopRanking(
                score=0.0,
                reasons=["movement_cut_candidate_window_choice_failed", "movement_cut_deterministic_visual_integrity_failed"],
                payload={
                    "score": 0.0,
                    "modelScore": 0.0,
                    "movementCutCandidates": source_cut_candidates_payload(all_candidates),
                    "movementCutDeterministicVisualIntegrityFailed": True,
                    "finalCutResponsibility": "movement_window_selection_only",
                },
                model_score=0.0,
            ),
            render_seconds,
            0.0,
        )
    coverage_candidates = [
        candidate
        for candidate in candidates
        if movement_cut_candidate_passes_motion_coverage(candidate)
    ]
    hard_motion_rejected_count = sum(
        1
        for candidate in candidates
        if movement_cut_candidate_has_hard_motion_rejection(candidate)
    )
    if coverage_candidates:
        vlm_candidates = coverage_candidates
    else:
        return (
            LoopRanking(
                score=0.0,
                reasons=["movement_cut_candidate_window_choice_failed", "movement_cut_target_motion_gate_failed"],
                payload={
                    "score": 0.0,
                    "modelScore": 0.0,
                    "movementCutCandidates": source_cut_candidates_payload(all_candidates),
                    "movementCutVlmInputCandidates": [],
                    "movementCutMotionCoverageFilteredCount": len(candidates),
                    "movementCutMotionCoverageFallback": False,
                    "movementCutHardMotionRejectedCount": hard_motion_rejected_count,
                    "movementCutTargetMotionGateFailed": True,
                    "exerciseMotionContractEnabled": use_exercise_motion_contract,
                    "finalCutResponsibility": "movement_window_selection_only",
                },
                model_score=0.0,
            ),
            render_seconds,
            0.0,
        )
    motion_coverage_fallback = False
    batch_choice = rank_cut_candidates_shortest_first_with_caption_images(
        candidates=vlm_candidates,
        caption_images=caption_images,
        prompt_builder=lambda batch_candidates: build_movement_cut_candidate_choice_prompt(
            exercise_name=item.exercise_name,
            candidate_title=item.candidate_title,
            candidates=batch_candidates,
            exercise_motion_contract=exercise_motion_contract,
            minimum_complete_duration_seconds=min_selected_duration_seconds,
        ),
        parser=lambda raw, batch_candidates: parse_movement_cut_candidate_choice(
            raw,
            batch_candidates,
            min_duration_seconds=min_selected_duration_seconds,
        ),
        max_workers=max_vlm_workers,
        caption_image_kwargs=cut_candidate_vlm_caption_kwargs(),
    )
    vlm_seconds = batch_choice.elapsed_seconds
    ranking = batch_choice.ranking
    reviewed_vlm_candidates = cut_candidates_with_ids(vlm_candidates, batch_choice.reviewed_candidate_ids)
    if ranking is None:
        return (
            LoopRanking(
                score=0.0,
                reasons=["movement_cut_candidate_window_choice_failed", "movement_cut_candidate_choice_invalid_response"],
                raw_response=batch_choice.raw_responses[-1] if batch_choice.raw_responses else None,
                payload={
                    "score": 0.0,
                    "modelScore": 0.0,
                    "movementCutCandidates": source_cut_candidates_payload(all_candidates),
                    "movementCutVlmInputCandidates": source_cut_candidates_payload(reviewed_vlm_candidates),
                    "movementCutMotionCoverageFilteredCount": len(candidates) - len(vlm_candidates),
                    "movementCutMotionCoverageFallback": motion_coverage_fallback,
                    "movementCutHardMotionRejectedCount": hard_motion_rejected_count,
                    "movementCutChoiceInvalidResponse": True,
                    "movementCutVlmReviewedCandidateCount": len(reviewed_vlm_candidates),
                    "movementCutVlmReviewedBatchCount": batch_choice.reviewed_batch_count,
                    "movementCutVlmBatchSize": CUT_CANDIDATE_MAX_VLM_BATCH_SIZE,
                    "movementCutVlmRequestTimeoutSeconds": CUT_CANDIDATE_VLM_REQUEST_TIMEOUT_SECONDS,
                    "movementCutMinSelectedDurationSeconds": min_selected_duration_seconds,
                    "movementCutVlmBatchErrors": batch_choice.errors,
                    "exerciseMotionContractEnabled": use_exercise_motion_contract,
                    **(
                        {"exerciseMotionContract": exercise_motion_contract}
                        if exercise_motion_contract is not None
                        else {}
                    ),
                    "finalCutResponsibility": "movement_window_selection_only",
                },
                model_score=0.0,
            ),
            render_seconds,
            vlm_seconds,
        )
    ranking_payload = dict(ranking.payload) if isinstance(ranking.payload, dict) else {}
    ranking_payload["movementCutCandidates"] = source_cut_candidates_payload(all_candidates)
    ranking_payload["movementCutVlmInputCandidates"] = source_cut_candidates_payload(reviewed_vlm_candidates)
    ranking_payload["movementCutVisualIntegrityFilteredCount"] = len(all_candidates) - len(candidates)
    ranking_payload["movementCutVisualIntegrityFallback"] = visual_integrity_fallback
    ranking_payload["movementCutMotionCoverageFilteredCount"] = len(candidates) - len(vlm_candidates)
    ranking_payload["movementCutMotionCoverageFallback"] = motion_coverage_fallback
    ranking_payload["movementCutHardMotionRejectedCount"] = hard_motion_rejected_count
    ranking_payload["movementCutVlmReviewedCandidateCount"] = len(reviewed_vlm_candidates)
    ranking_payload["movementCutVlmReviewedBatchCount"] = batch_choice.reviewed_batch_count
    ranking_payload["movementCutVlmBatchSize"] = CUT_CANDIDATE_MAX_VLM_BATCH_SIZE
    ranking_payload["movementCutVlmRequestTimeoutSeconds"] = CUT_CANDIDATE_VLM_REQUEST_TIMEOUT_SECONDS
    ranking_payload["movementCutMinSelectedDurationSeconds"] = min_selected_duration_seconds
    ranking_payload["movementCutVlmBatchErrors"] = batch_choice.errors
    ranking_payload["movementCutUnreviewedCandidateCount"] = max(0, len(vlm_candidates) - len(reviewed_vlm_candidates))
    ranking_payload["exerciseMotionContractEnabled"] = use_exercise_motion_contract
    if exercise_motion_contract is not None:
        ranking_payload["exerciseMotionContract"] = exercise_motion_contract
    ranking_payload["finalCutResponsibility"] = "movement_window_selection_only"
    ranking = replace(
        ranking,
        payload=ranking_payload,
    )
    selected_window = selected_window_from_cut_ranking(ranking)
    if selected_window is not None and selected_window_is_materially_shorter(
        parent_window=timeline_window,
        child_window=selected_window,
    ):
        refined = rank_movement_cut_candidates_with_caption_images(
            item=item,
            timeline_window=selected_window,
            chunk_estimate=chunk_estimate,
            output_dir=output_dir / f"refine_{_refinement_depth + 1:02d}",
            frame_count=frame_count,
            caption_images=caption_images,
            use_exercise_motion_contract=use_exercise_motion_contract,
            max_vlm_workers=max_vlm_workers,
            _refinement_depth=_refinement_depth + 1,
        )
        if refined is not None:
            refined_ranking, refined_render_seconds, refined_vlm_seconds = refined
            refined_selected_window = selected_window_from_cut_ranking(refined_ranking)
            if refined_selected_window is not None and selected_window_is_materially_shorter(
                parent_window=selected_window,
                child_window=refined_selected_window,
            ):
                stage = cut_refinement_stage_payload(
                    ranking=ranking,
                    parent_window=timeline_window,
                    selected_window=selected_window,
                    stage_index=_refinement_depth,
                    candidates_key="movementCutCandidates",
                    vlm_candidates_key="movementCutVlmInputCandidates",
                )
                return (
                    prepend_cut_refinement_stage(
                        refined_ranking,
                        stages_key="movementCutRefinementStages",
                        stage=stage,
                    ),
                    render_seconds + refined_render_seconds,
                    vlm_seconds + refined_vlm_seconds,
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
    exercise_motion_contract: dict[str, Any] | None = None,
    source_pose_prefilter_payload: dict[str, Any] | None = None,
    source_pose_offset_seconds: float = 0.0,
    max_vlm_workers: int = 1,
    _refinement_depth: int = 0,
) -> tuple[LoopRanking, float, float] | None:
    min_duration_floor_seconds = source_cut_min_candidate_duration_seconds(
        chunk_estimate=chunk_estimate,
        exercise_motion_contract=exercise_motion_contract,
    )
    candidate_window_specs = build_source_video_pyramid_candidate_windows(
        window=timeline_window,
        chunk_estimate=chunk_estimate,
        min_duration_floor_seconds=min_duration_floor_seconds,
    )
    if not candidate_window_specs:
        return None
    render_started = time.perf_counter()
    candidates: list[SourceCutCandidate] = []
    all_candidates: list[SourceCutCandidate] = []
    for index, candidate_spec in enumerate(candidate_window_specs):
        candidate_window = candidate_spec.window
        candidate_id = source_cut_candidate_id_for_index(index)
        candidate_output_dir = output_dir / f"source_candidate_{candidate_id}"
        frame_paths = render_video_window_contact_sheet(
            video_path=video_path,
            window=candidate_window,
            output_dir=candidate_output_dir,
            frame_count=min(max(8, frame_count // 2), 16),
        )
        candidate = build_source_cut_candidate(
            candidate_id=candidate_id,
            candidate_window=candidate_window,
            contact_sheet_paths=frame_paths,
            output_dir=candidate_output_dir,
            pose_prefilter=source_cut_candidate_pose_prefilter_metrics(
                candidate_window=candidate_window,
                pose_payload=source_pose_prefilter_payload,
                source_offset_seconds=source_pose_offset_seconds,
            ),
            chunking=candidate_spec.chunking,
        )
        if candidate is not None:
            candidate = replace(
                candidate,
                motion_coverage=source_cut_candidate_motion_coverage_metrics(
                    candidate_window=candidate_window,
                    pose_payload=source_pose_prefilter_payload,
                    exercise_name=exercise_name,
                    chunk_estimate=chunk_estimate,
                    exercise_motion_contract=exercise_motion_contract,
                    source_offset_seconds=source_pose_offset_seconds,
                ),
            )
            all_candidates.append(candidate)
            if (
                source_cut_candidate_passes_visual_integrity(candidate)
                and source_cut_candidate_passes_pose_prefilter(candidate)
                and source_cut_candidate_passes_motion_coverage(candidate)
            ):
                candidates.append(candidate)
    render_seconds = elapsed_seconds(render_started)
    if not candidates:
        visual_filtered_count = sum(
            1
            for candidate in all_candidates
            if not source_cut_candidate_passes_visual_integrity(candidate)
        )
        pose_filtered_count = sum(
            1
            for candidate in all_candidates
            if source_cut_candidate_passes_visual_integrity(candidate)
            and not source_cut_candidate_passes_pose_prefilter(candidate)
        )
        motion_filtered_count = sum(
            1
            for candidate in all_candidates
            if source_cut_candidate_passes_visual_integrity(candidate)
            and source_cut_candidate_passes_pose_prefilter(candidate)
            and not source_cut_candidate_passes_motion_coverage(candidate)
        )
        return (
            LoopRanking(
                score=0.0,
                reasons=[
                    "source_candidate_window_choice_failed",
                    "source_cut_deterministic_candidate_filter_failed",
                ],
                payload={
                    "score": 0.0,
                    "modelScore": 0.0,
                    "sourceCutCandidates": source_cut_candidates_payload(all_candidates),
                    "sourceCutDeterministicCandidateFilterFailed": True,
                    "sourceCutVisualIntegrityFilteredCount": visual_filtered_count,
                    "sourceCutPosePrefilterFilteredCount": pose_filtered_count,
                    "sourceCutMotionCoverageFilteredCount": motion_filtered_count,
                    "exerciseMotionContract": exercise_motion_contract,
                },
                model_score=0.0,
            ),
            render_seconds,
            0.0,
        )
    source_scorecard_has_contract = exercise_motion_contract_for_prompt(exercise_motion_contract) is not None
    effective_source_cut_vlm_workers = min(max(1, int(max_vlm_workers)), SOURCE_CUT_MAX_VLM_WORKERS)
    batch_choice = rank_cut_candidates_shortest_first_with_caption_images(
        candidates=candidates,
        caption_images=caption_images,
        prompt_builder=lambda batch_candidates: build_source_cut_candidate_choice_prompt(
            exercise_name=exercise_name,
            candidate_title=candidate_title,
            candidates=batch_candidates,
            exercise_motion_contract=exercise_motion_contract,
        ),
        parser=lambda raw, batch_candidates: parse_source_cut_candidate_choice(
            raw,
            batch_candidates,
            has_contract=source_scorecard_has_contract,
        ),
        max_candidates_per_request=SOURCE_CUT_CANDIDATE_MAX_VLM_BATCH_SIZE,
        max_workers=effective_source_cut_vlm_workers,
        prefer_largest_padded_candidate=False,
        progressive_source_selection=True,
        caption_image_kwargs=source_cut_vlm_caption_kwargs(),
    )
    vlm_seconds = batch_choice.elapsed_seconds
    ranking = batch_choice.ranking
    reviewed_vlm_candidates = cut_candidates_with_ids(candidates, batch_choice.reviewed_candidate_ids)
    source_cut_scorecard_rows = collect_ranking_payload_rows(batch_choice.rankings, "sourceCutScorecardCandidates")
    if ranking is None:
        return (
            LoopRanking(
                score=0.0,
                reasons=["source_candidate_window_choice_failed", "source_candidate_choice_invalid_response"],
                raw_response=batch_choice.raw_responses[-1] if batch_choice.raw_responses else None,
                payload={
                    "score": 0.0,
                    "modelScore": 0.0,
                    "sourceCutCandidates": source_cut_candidates_payload(all_candidates),
                    "sourceCutVlmInputCandidates": source_cut_candidates_payload(reviewed_vlm_candidates),
                    "sourceCutVisualIntegrityFilteredCount": sum(
                        1
                        for candidate in all_candidates
                        if not source_cut_candidate_passes_visual_integrity(candidate)
                    ),
                    "sourceCutPosePrefilterFilteredCount": sum(
                        1
                        for candidate in all_candidates
                        if source_cut_candidate_passes_visual_integrity(candidate)
                        and not source_cut_candidate_passes_pose_prefilter(candidate)
                    ),
                    "sourceCutMotionCoverageFilteredCount": sum(
                        1
                        for candidate in all_candidates
                        if source_cut_candidate_passes_visual_integrity(candidate)
                        and source_cut_candidate_passes_pose_prefilter(candidate)
                        and not source_cut_candidate_passes_motion_coverage(candidate)
                    ),
                    "sourceChoiceInvalidResponse": True,
                    "sourceCutVlmReviewedCandidateCount": len(reviewed_vlm_candidates),
                    "sourceCutVlmReviewedBatchCount": batch_choice.reviewed_batch_count,
                    "sourceCutVlmBatchSize": SOURCE_CUT_CANDIDATE_MAX_VLM_BATCH_SIZE,
                    "sourceCutVlmRequestTimeoutSeconds": SOURCE_CUT_CANDIDATE_VLM_REQUEST_TIMEOUT_SECONDS,
                    "sourceCutMaxVlmWorkers": SOURCE_CUT_MAX_VLM_WORKERS,
                    "sourceCutEffectiveVlmWorkers": effective_source_cut_vlm_workers,
                    "sourceCutVlmBatchErrors": batch_choice.errors,
                    "sourceCutScorecardCandidates": source_cut_scorecard_rows,
                    "sourceCutScorecardContractPresent": source_scorecard_has_contract,
                    "sourceCutScorecardThresholds": source_cut_scorecard_thresholds(
                        has_contract=source_scorecard_has_contract,
                    ),
                    "exerciseMotionContract": exercise_motion_contract,
                },
                model_score=0.0,
            ),
            render_seconds,
            vlm_seconds,
        )
    ranking_payload = dict(ranking.payload) if isinstance(ranking.payload, dict) else {}
    ranking_payload["sourceCutCandidates"] = source_cut_candidates_payload(all_candidates)
    ranking_payload["sourceCutVlmInputCandidates"] = source_cut_candidates_payload(reviewed_vlm_candidates)
    ranking_payload["sourceCutVisualIntegrityFilteredCount"] = sum(
        1
        for candidate in all_candidates
        if not source_cut_candidate_passes_visual_integrity(candidate)
    )
    ranking_payload["sourceCutPosePrefilterFilteredCount"] = sum(
        1
        for candidate in all_candidates
        if source_cut_candidate_passes_visual_integrity(candidate)
        and not source_cut_candidate_passes_pose_prefilter(candidate)
    )
    ranking_payload["sourceCutMotionCoverageFilteredCount"] = sum(
        1
        for candidate in all_candidates
        if source_cut_candidate_passes_visual_integrity(candidate)
        and source_cut_candidate_passes_pose_prefilter(candidate)
        and not source_cut_candidate_passes_motion_coverage(candidate)
    )
    ranking_payload["sourceCutVlmReviewedCandidateCount"] = len(reviewed_vlm_candidates)
    ranking_payload["sourceCutVlmReviewedBatchCount"] = batch_choice.reviewed_batch_count
    ranking_payload["sourceCutVlmBatchSize"] = SOURCE_CUT_CANDIDATE_MAX_VLM_BATCH_SIZE
    ranking_payload["sourceCutVlmRequestTimeoutSeconds"] = SOURCE_CUT_CANDIDATE_VLM_REQUEST_TIMEOUT_SECONDS
    ranking_payload["sourceCutMaxVlmWorkers"] = SOURCE_CUT_MAX_VLM_WORKERS
    ranking_payload["sourceCutEffectiveVlmWorkers"] = effective_source_cut_vlm_workers
    ranking_payload["sourceCutVlmBatchErrors"] = batch_choice.errors
    ranking_payload["sourceCutUnreviewedCandidateCount"] = max(0, len(candidates) - len(reviewed_vlm_candidates))
    ranking_payload["sourceCutScorecardCandidates"] = source_cut_scorecard_rows
    ranking_payload["sourceCutScorecardContractPresent"] = source_scorecard_has_contract
    ranking_payload["sourceCutScorecardThresholds"] = source_cut_scorecard_thresholds(
        has_contract=source_scorecard_has_contract,
    )
    ranking_payload["exerciseMotionContract"] = exercise_motion_contract
    ranking = replace(
        ranking,
        payload=ranking_payload,
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
        llama_cpp_server_command=request.llama_cpp_server_command,
        llama_cpp_mmproj=request.llama_cpp_mmproj,
        llama_cpp_backend=request.llama_cpp_backend,
        llama_cpp_n_predict=request.llama_cpp_n_predict,
        llama_cpp_temperature=request.llama_cpp_temperature,
        llama_cpp_top_p=request.llama_cpp_top_p,
        llama_cpp_top_k=request.llama_cpp_top_k,
        llama_cpp_disable_reasoning=request.llama_cpp_disable_reasoning,
        llama_cpp_reasoning_budget=request.llama_cpp_reasoning_budget,
        llama_cpp_reasoning_budget_message=request.llama_cpp_reasoning_budget_message,
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
        llama_cpp_mtmd_batch_max_tokens=request.llama_cpp_mtmd_batch_max_tokens,
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
            movement_cut_choice = rank_movement_cut_candidates_with_caption_images(
                item=item,
                timeline_window=timeline_window,
                chunk_estimate=chunk_estimate,
                output_dir=frames_dir / f"chunk_{video_window.index:04d}",
                frame_count=frames_per_chunk,
                caption_images=caption_images,
                use_exercise_motion_contract=request.exercise_motion_contract_enabled,
                max_vlm_workers=request.review_llm_workers,
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
                    review_frame_source="movement_cut_source_contact_sheets",
                    review_frame_count=frames_per_chunk,
                    error=exc,
                )
            )
            continue
        if movement_cut_choice is None:
            rankings.append(
                LoopRanking(
                    score=0.0,
                    reasons=["movement_cut_candidate_window_choice_failed", "movement_cut_candidate_windows_unavailable"],
                )
            )
            continue
        ranking, render_seconds, vlm_seconds = movement_cut_choice
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
                    review_frame_source="movement_cut_source_contact_sheets",
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
        active_motion_window=active_motion_window,
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
    current_settings_json = json.dumps(
        vlm_visible_preview_options(item.settings_options),
        sort_keys=True,
    )
    motion_tuning_enabled = item.settings_variant_id != "raw-wham"
    loop_continuity_required = False
    review_goal = "score this deterministically bounded exercise movement candidate for a Wear OS exercise animation"
    boundary_instruction = (
        "Score boundary_quality by whether this deterministic chunk is cut to the actual exercise movement, not merely to a broad preview span. For a rep-based lift, the chunk should start near the first frame where the loaded movement begins, include the full eccentric and concentric phases, and end shortly after the rep completes at the stable finish pose. For multi-phase lifts, it should include the complete phase sequence through controlled finish/stabilization. Penalize setup, unracking, walking in/out, long pauses before the first moving frame, long holds after completion, and reset footage. Treat the full chunk as good only when its first and last frames are already the true movement boundaries.\n"
    )
    movement_boundary_instruction = (
        "First judge whether the deterministic chunk boundaries already cover a tight complete exercise movement rather than setup, reset, or extra holds. Do not require the start and end poses to match; clean movement coverage is more important than loopability.\n"
    )
    section_cut_instruction = "Judge only the attached chunk frames. Do not invent or return exact start/end seconds; deterministic code owns timing and this review only scores the bounded one-shot exercise animation clip.\n"
    score_instruction = (
        "Score 0 to 1 for the proposed cut using these criteria: correct exercise, complete movement coverage, recognizability, smoothness, stable planted feet when appropriate, stable paired hand spacing for barbell/dumbbell press-like motion, no impossible joints, clear start/end boundaries, controlled finish, and readability on a small Wear display. Do not penalize a valid movement merely because the final pose differs from the starting pose.\n"
    )
    settings_instruction = (
        "Preview/post-processing settings, support locks, scene orientation, playback speed, camera yaw, and camera pitch have already been chosen by deterministic code and are not available in this decision. "
        "Do not recommend or change settings. If the render is upside down, head/feet reversed, sliding, distorted, or unreadable because of camera/alignment/post-processing, lower the score and explain the visible issue instead of proposing a fix.\n"
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
                f"The first attached image is a chronological contact sheet from the original selected source video for exercise identity and real-world context. The second attached image is the generated skeleton preview contact sheet with {review_frame_count} evenly sampled frames and visible preview timeline labels. {CONTACT_SHEET_READING_INSTRUCTIONS}Use the source sheet only for context; choose section timing from the generated preview timeline.\n"
            )
            if includes_source_context
            else f"The attached image is a chronological contact sheet rendered directly from the generated interactive preview with {review_frame_count} evenly sampled frames and visible preview timeline labels. {CONTACT_SHEET_READING_INSTRUCTIONS}"
        )
        + "Use the chunk boundaries as fixed deterministic input. Do not return selected section seconds.\n"
        f"Chunk sizing came from the shared estimate: {json.dumps({'repDurationMinSec': getattr(chunk_estimate, 'rep_duration_min_sec', None), 'repDurationMaxSec': getattr(chunk_estimate, 'rep_duration_max_sec', None), 'movementComplexity': getattr(chunk_estimate, 'movement_complexity', None), 'chunkSeconds': getattr(chunk_estimate, 'chunk_seconds', None), 'chunkOverlapSeconds': getattr(chunk_estimate, 'chunk_overlap_seconds', None), 'source': getattr(chunk_estimate, 'source', None)})}.\n"
        "Loop continuity required for final acceptance: false. Prefer a clean complete movement clip over a seamless loop.\n"
        f"Current preview option variant: {item.settings_variant_id} ({item.settings_variant_label}).\n"
        f"Current cleanup interpretation: {item.cleanup_interpretation}.\n"
        f"Current preview option values: {current_settings_json}.\n"
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
        "Return JSON only with keys: {\"score\": number, \"correctness\": number, \"full_rep_motion\": number, \"boundary_quality\": number, \"recognizability\": number, \"smoothness\": number, \"stable_feet\": number, \"joint_plausibility\": number, \"loop_continuity\": number, \"wear_readability\": number, \"needs_another_iteration\": boolean, \"reasons\": [string]}."
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
    selected_results: list[SelectedArtifact] | None = None,
    rejected_best: SelectedArtifact | None = None,
) -> dict[str, Any]:
    manifest_selected_results = selected_results if selected_results is not None else ([selected] if selected is not None else [])
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceCandidatesJson": str(request.candidates_json),
        "youtubeSourceCacheDir": str(resolved_youtube_source_cache_dir(request)),
        "youtubePreviewCacheReadThroughDir": str(default_youtube_preview_cache_read_through_dir(request)),
        "candidateSelectionPolicy": "ranked_source_video_budget_best_final_selection",
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
        "maxSourceWindowAttempts": request.max_source_window_attempts,
        "exerciseMotionContractEnabled": request.exercise_motion_contract_enabled,
        "exerciseSkeletonContractEnabled": request.exercise_motion_contract_enabled,
        "finalOutputValidationEnabled": request.final_output_validation,
        "finalOutputValidationMinScore": request.final_output_validation_min_score,
        "minSelectedScore": request.min_selected_score,
        "maxSelectedResults": max_selected_results_for_request(request),
        "motionTuningEnabled": request.motion_tuning_enabled,
        "spineposeEnabled": request.spinepose_enabled,
        "spineposeMergeMode": request.spinepose_merge_mode,
        "spineposeMode": request.spinepose_mode,
        "spineposeModelVersion": request.spinepose_model_version,
        "spineposeDevice": request.spinepose_device,
        "candidateResults": candidate_results,
        "reviewItems": review_entries,
        "selectedResultCount": len(manifest_selected_results),
        "selectedResults": selected_artifacts_to_manifest(manifest_selected_results),
        "selected": None if selected is None else selected_to_manifest(*selected),
        "rejectedBest": None if rejected_best is None else {
            **selected_to_manifest(*rejected_best),
            "rejectionReason": "best_score_below_minimum",
        },
    }


def selected_artifacts_to_manifest(selected_results: list[SelectedArtifact]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, selected in enumerate(selected_results):
        payload = selected_to_manifest(*selected)
        payload["selectedResultIndex"] = index
        payload["manualSelectionLabel"] = f"Option {index + 1}"
        results.append(payload)
    return results


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
    settings_contract = wear_skeleton_preview_settings_contract_for_review_item(item)
    payload["wearSkeletonSettingsBaked"] = bool(settings_contract.get("passed"))
    payload["wearSkeletonPreviewSettingsContract"] = settings_contract
    payload["selectedSectionStartSeconds"] = item.loop_start_seconds
    payload["selectedSectionEndSeconds"] = item.loop_end_seconds
    payload["selectedSectionDurationSeconds"] = item.duration_sec
    return payload


def wear_skeleton_preview_settings_contract_for_review_item(item: ReviewItem) -> dict[str, Any]:
    export_payload = item.export_payload
    if not isinstance(export_payload, dict):
        if not item.skeleton_path.exists():
            return {
                "passed": False,
                "source": "missing_wear_skeleton_json",
                "missingFields": ["wearSkeletonJson"],
                "mismatches": [],
                "selectedPreviewSettings": None,
                "bakedPreviewConfiguration": None,
                "wearDisplay": None,
            }
        try:
            export_payload = json.loads(item.skeleton_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {
                "passed": False,
                "source": "invalid_wear_skeleton_json",
                "error": str(exc),
                "missingFields": ["wearSkeletonJson"],
                "mismatches": [],
                "selectedPreviewSettings": None,
                "bakedPreviewConfiguration": None,
                "wearDisplay": None,
            }
    return wear_skeleton_preview_settings_contract(
        export_payload,
        options=item.settings_options,
    )


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
    selected_input_video_candidates = (
        item.candidate_workspace / "input" / "selected_segment.mp4",
        item.candidate_workspace / "input" / "source.mp4",
        item.candidate_workspace / "source" / "source.mp4",
    )
    selected_input_video_path = next(
        (path for path in selected_input_video_candidates if path.exists()),
        selected_input_video_candidates[0],
    )
    source_window_candidate = RankedCandidate(
        exercise_index=item.exercise_index,
        candidate_rank=item.candidate_rank,
        exercise_id=item.exercise_name,
        exercise_name=item.exercise_name,
        exercise_slug=slugify(item.exercise_name),
        candidate=item.candidate,
    )
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
        "selectedInputVideoPath": str(selected_input_video_path),
        "durationSec": item.duration_sec,
        "loopStartSeconds": item.loop_start_seconds,
        "loopEndSeconds": item.loop_end_seconds,
        "sectionStartSeconds": item.loop_start_seconds,
        "sectionEndSeconds": item.loop_end_seconds,
        "llmTimeRangeCutApplied": item.llm_time_range_cut_applied,
        "sourceReviewVideoPath": str(item.source_review_video_path) if item.source_review_video_path is not None else None,
        "sourceSkeletonPath": str(item.source_skeleton_path) if item.source_skeleton_path is not None else None,
        "candidate": item.candidate,
        **source_window_attempt_manifest(source_window_candidate),
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


def default_youtube_source_cache_dir(request: BakeAndRankRequest) -> Path:
    return request.candidates_json.expanduser().resolve().parent / "youtube-source-cache"


def default_youtube_preview_cache_read_through_dir(request: BakeAndRankRequest) -> Path:
    if request.youtube_preview_cache_dir is not None:
        return request.youtube_preview_cache_dir.expanduser().resolve()
    return request.candidates_json.expanduser().resolve().parent.parent / "youtube-preview-cache"


def resolved_youtube_source_cache_dir(request: BakeAndRankRequest) -> Path:
    if request.youtube_source_cache_dir is not None:
        return request.youtube_source_cache_dir.expanduser().resolve()
    return default_youtube_source_cache_dir(request)


def youtube_source_cache_stem(ranked_candidate: RankedCandidate) -> str:
    if ranked_candidate.url:
        return youtube_preview_cache_stem(ranked_candidate.url)
    identity = ranked_candidate.video_id or ranked_candidate.title or ranked_candidate.workspace_slug
    digest = hashlib.sha1(identity.encode("utf-8", errors="replace")).hexdigest()[:12]
    safe_identity = re.sub(r"[^A-Za-z0-9_.-]+", "-", identity).strip("-")[:64]
    return f"{safe_identity}-{digest}" if safe_identity else f"source-{digest}"


def cache_youtube_source(video_path: Path, cache_dir: Path, cache_stem: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = video_path.suffix if video_path.suffix else ".mp4"
    target = cache_dir / f"{cache_stem}{suffix}"
    if target.exists() and target.stat().st_size > 0:
        return target
    temp_target = cache_dir / f"{target.name}.{os.getpid()}.{threading.get_ident()}.part"
    shutil.copy2(video_path, temp_target)
    temp_target.replace(target)
    return target


def copy_cached_source_to_destination(source: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix if source.suffix else ".mp4"
    destination = destination_dir / f"source{suffix}"
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return destination


def copy_or_download_candidate_source(
    ranked_candidate: RankedCandidate,
    destination_dir: Path,
    *,
    youtube_cookies: Path | None = None,
    youtube_source_cache_dir: Path | None = None,
    youtube_preview_cache_dir: Path | None = None,
) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    cache_stem = youtube_source_cache_stem(ranked_candidate)
    read_through_dirs = [
        path
        for path in (youtube_source_cache_dir, youtube_preview_cache_dir)
        if path is not None
    ]
    seen_dirs: set[Path] = set()
    for cache_dir in read_through_dirs:
        resolved_cache_dir = cache_dir.expanduser().resolve()
        if resolved_cache_dir in seen_dirs:
            continue
        seen_dirs.add(resolved_cache_dir)
        cached = find_cached_youtube_preview(resolved_cache_dir, cache_stem)
        if cached is None:
            continue
        if youtube_source_cache_dir is not None and resolved_cache_dir != youtube_source_cache_dir.expanduser().resolve():
            cached = cache_youtube_source(cached, youtube_source_cache_dir.expanduser().resolve(), cache_stem)
        return copy_cached_source_to_destination(cached, destination_dir)

    video_path = ranked_candidate.video_path
    if video_path is not None:
        source = video_path.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Candidate video not found: {source}")
        destination = destination_dir / source.name
        if source != destination.resolve():
            shutil.copy2(source, destination)
        if youtube_source_cache_dir is not None:
            cache_youtube_source(destination, youtube_source_cache_dir.expanduser().resolve(), cache_stem)
        return destination
    if not ranked_candidate.url:
        raise ValueError("Candidate must provide url or videoPath.")
    downloaded = download_youtube(ranked_candidate.url, destination_dir, youtube_cookies)
    if youtube_source_cache_dir is not None:
        cache_youtube_source(downloaded, youtube_source_cache_dir.expanduser().resolve(), cache_stem)
    return downloaded
