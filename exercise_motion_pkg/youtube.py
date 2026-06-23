from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any, Callable, Iterable

import httpx
from exercise_motion_pkg.chunking import estimate_chunking, frames_for_chunk_seconds
from exercise_motion_pkg.llama_defaults import (
    DEFAULT_LLAMA_CPP_MMPROJ,
    DEFAULT_LLAMA_CPP_MODEL,
    DEFAULT_LLAMA_CPP_TEMPERATURE,
    DEFAULT_LLAMA_CPP_TOP_K,
    DEFAULT_LLAMA_CPP_TOP_P,
)
from exercise_motion_pkg.pose_prefilter import (
    PosePrefilterSettings,
    run_yolo_pose_prefilter,
)

LOW_RES_VIDEO_ONLY_FORMAT = (
    "bestvideo[height<=360][ext=mp4][protocol^=http][vcodec!=none]/"
    "bestvideo[height<=360][ext=mp4][protocol^=https][vcodec!=none]/"
    "bestvideo[height<=360][ext=mp4][vcodec!=none]/"
    "bestvideo[height<=360][vcodec!=none]/"
    "bestvideo[height<=480][ext=mp4][vcodec!=none]/"
    "bestvideo[height<=480][vcodec!=none]/"
    "worst[height<=480][ext=mp4][vcodec!=none]/"
    "worst[height<=480][vcodec!=none]/"
    "worst[ext=mp4][vcodec!=none]/"
    "worst[vcodec!=none]/worst"
)

LOW_RES_PROGRESSIVE_VIDEO_FORMAT = (
    "best[height<=360][ext=mp4][vcodec!=none]/"
    "best[height<=480][ext=mp4][vcodec!=none]/"
    "worst[height<=480][ext=mp4][vcodec!=none]/"
    "worst[ext=mp4][vcodec!=none]/"
    "worst[vcodec!=none]/worst"
)


def download_youtube(url: str, output_dir: Path, cookies_path: Path | None = None) -> Path:
    resolved_cookies_path: Path | None = None
    if cookies_path is not None:
        resolved_cookies_path = cookies_path.expanduser().resolve()
        if not resolved_cookies_path.exists():
            raise FileNotFoundError(f"YouTube cookies file not found: {resolved_cookies_path}")
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is required for YouTube downloads. Install with: pip install .[motion]"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    options = build_youtube_download_options(
        outtmpl=str(output_dir / "source.%(ext)s"),
        quiet=False,
        noprogress=False,
        retries=3,
        preview=False,
        cookies_path=resolved_cookies_path,
    )
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded = Path(ydl.prepare_filename(info))
    if downloaded.exists():
        return sanitize_downloaded_video(downloaded)
    for extension in (".mp4", ".mkv", ".webm", ".mov"):
        candidate = Path(os.path.splitext(str(downloaded))[0] + extension)
        if candidate.exists():
            return sanitize_downloaded_video(candidate)
    raise RuntimeError(f"Download finished but no video file was found in {output_dir}.")


def download_youtube_preview(
    url: str,
    output_dir: Path,
    cookies_path: Path | None = None,
    *,
    cache_dir: Path | None = None,
) -> Path:
    resolved_cookies_path: Path | None = None
    if cookies_path is not None:
        resolved_cookies_path = cookies_path.expanduser().resolve()
        if not resolved_cookies_path.exists():
            raise FileNotFoundError(f"YouTube cookies file not found: {resolved_cookies_path}")
    resolved_cache_dir = cache_dir.expanduser().resolve() if cache_dir is not None else None
    cache_stem = youtube_preview_cache_stem(url)
    if resolved_cache_dir is not None:
        cached = find_cached_youtube_preview(resolved_cache_dir, cache_stem)
        if cached is not None:
            return cached
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--format",
        LOW_RES_VIDEO_ONLY_FORMAT,
        "--output",
        str(output_dir / "candidate.%(ext)s"),
        "--no-playlist",
        "--retries",
        "1",
        "--fragment-retries",
        "1",
        "--socket-timeout",
        "15",
        "--no-progress",
        "--no-warnings",
        "--force-overwrites",
    ]
    if resolved_cookies_path is not None:
        command += ["--cookies", str(resolved_cookies_path)]
    command.append(url)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Preview download timed out for {url}.") from exc
    if completed.returncode != 0:
        message = truncate_text(completed.stderr or completed.stdout or "yt-dlp failed", 400)
        raise RuntimeError(f"Preview download failed for {url}: {message}")
    for candidate in sorted(output_dir.glob("candidate.*")):
        if candidate.is_file() and candidate.suffix.lower() != ".part":
            sanitized = sanitize_downloaded_video(candidate)
            if resolved_cache_dir is not None:
                return cache_youtube_preview(sanitized, resolved_cache_dir, cache_stem)
            return sanitized
    raise RuntimeError(f"Preview download finished but no video file was found in {output_dir}.")


def youtube_preview_cache_stem(url: str) -> str:
    parsed = urlparse(url)
    video_id = ""
    query_ids = parse_qs(parsed.query).get("v")
    if query_ids:
        video_id = str(query_ids[0])
    elif parsed.netloc.endswith("youtu.be"):
        video_id = parsed.path.strip("/")
    digest = hashlib.sha1(url.encode("utf-8", errors="replace")).hexdigest()[:12]
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", video_id).strip("-")[:64]
    return f"{safe_id}-{digest}" if safe_id else f"preview-{digest}"


def find_cached_youtube_preview(cache_dir: Path, cache_stem: str) -> Path | None:
    if not cache_dir.exists():
        return None
    for candidate in sorted(cache_dir.glob(f"{cache_stem}.*")):
        if (
            candidate.is_file()
            and candidate.suffix.lower() != ".part"
            and candidate.stat().st_size > 0
        ):
            return candidate
    return None


def cache_youtube_preview(video_path: Path, cache_dir: Path, cache_stem: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = video_path.suffix if video_path.suffix else ".mp4"
    target = cache_dir / f"{cache_stem}{suffix}"
    if target.exists() and target.stat().st_size > 0:
        return target
    temp_target = target.with_suffix(target.suffix + ".part")
    shutil.copy2(video_path, temp_target)
    temp_target.replace(target)
    return target


def sanitize_video_for_processing(video_path: Path) -> Path:
    """Re-encode/detox incoming video files to a clean local MP4 for downstream tooling."""
    return sanitize_downloaded_video(video_path)


def sanitize_downloaded_video(video_path: Path) -> Path:
    if not video_path.exists():
        raise FileNotFoundError(f"Input video not found: {video_path}")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return video_path

    sanitized_path = video_path.with_name(f"{video_path.stem}_sanitized.mp4")
    if sanitized_path.exists() and sanitized_path.stat().st_mtime >= video_path.stat().st_mtime:
        return sanitized_path

    temp_path = sanitized_path.with_suffix(".tmp.mp4")
    command_base = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-loglevel",
        "warning",
        "-i",
        str(video_path),
    ]
    copy_args = command_base + [
        "-fflags",
        "+discardcorrupt+genpts",
        "-an",
        "-c:v",
        "copy",
        "-movflags",
        "+faststart",
        str(temp_path),
    ]

    copy_exit_code, copy_stderr = _run_ffmpeg(copy_args)
    warning_text = copy_stderr.lower()
    copy_has_decode_warning = any(
        token in warning_text for token in (
            "co located pocs unavailable",
            "missing reference picture",
            "decode_slice_header error",
            "possible mpeg-ts",
            "malformed aac timestamps",
        )
    )

    if copy_exit_code == 0 and not copy_has_decode_warning:
        return _finalize_sanitized_video(temp_path, sanitized_path, video_path)

    reencode_args = command_base + [
        "-fflags",
        "+discardcorrupt+genpts",
        "-err_detect",
        "ignore_err",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-an",
        "-movflags",
        "+faststart",
        str(temp_path),
    ]
    _run_ffmpeg(reencode_args)
    return _finalize_sanitized_video(temp_path, sanitized_path, video_path)


def _run_ffmpeg(args: list[str]) -> tuple[int, str]:
    try:
        process = subprocess.run(
            args,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return 124, "ffmpeg timed out after 120 seconds."
    return process.returncode, process.stderr


def _finalize_sanitized_video(temp_path: Path, final_path: Path, fallback_path: Path) -> Path:
    if not temp_path.exists() or temp_path.stat().st_size == 0:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if final_path.exists():
            return final_path
        return fallback_path
    temp_path.replace(final_path)
    return final_path


def build_youtube_download_options(
    *,
    outtmpl: str,
    quiet: bool,
    noprogress: bool,
    retries: int,
    cookies_path: Path | None = None,
    preview: bool = False,
) -> dict[str, Any]:
    ffmpeg_available = shutil.which("ffmpeg") is not None
    remote_components = ["ejs:github"]
    if preview:
        if ffmpeg_available:
            options = {
                "format": LOW_RES_VIDEO_ONLY_FORMAT,
                "outtmpl": outtmpl,
                "quiet": quiet,
                "noprogress": noprogress,
                "noplaylist": True,
                "retries": retries,
                "remote_components": remote_components,
            }
        else:
            options = {
                "format": LOW_RES_PROGRESSIVE_VIDEO_FORMAT,
                "outtmpl": outtmpl,
                "quiet": quiet,
                "noprogress": noprogress,
                "noplaylist": True,
                "retries": retries,
                "remote_components": remote_components,
            }
    elif ffmpeg_available:
        options = {
            "format": LOW_RES_VIDEO_ONLY_FORMAT,
            "outtmpl": outtmpl,
            "quiet": quiet,
            "noprogress": noprogress,
            "noplaylist": True,
            "retries": retries,
            "merge_output_format": "mp4",
            "remote_components": remote_components,
        }
    else:
        options = {
            "format": LOW_RES_PROGRESSIVE_VIDEO_FORMAT,
            "outtmpl": outtmpl,
            "quiet": quiet,
            "noprogress": noprogress,
            "noplaylist": True,
            "retries": retries,
            "remote_components": remote_components,
        }
    if cookies_path is not None:
        options["cookiefile"] = str(cookies_path)
    return options


@dataclass(frozen=True)
class ExerciseEntry:
    exercise_id: str
    name: str
    slug: str


@dataclass(frozen=True)
class YouTubeCandidate:
    url: str
    video_id: str | None
    title: str
    channel: str | None
    duration_seconds: int | None
    view_count: int | None
    upload_date: str | None
    description_snippet: str | None
    thumbnail: str | None
    metadata_score: float = 0.0
    vision_score: float | None = None
    final_score: float = 0.0
    status: str = "candidate"
    score_reasons: list[str] = field(default_factory=list)
    vision_payload: dict[str, Any] | None = None

    def key(self) -> str:
        if self.video_id:
            return self.video_id
        return self.url

    def to_manifest_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "url": self.url,
            "videoId": self.video_id,
            "title": self.title,
            "channel": self.channel,
            "durationSeconds": self.duration_seconds,
            "viewCount": self.view_count,
            "uploadDate": self.upload_date,
            "descriptionSnippet": self.description_snippet,
            "thumbnail": self.thumbnail,
            "metadataScore": round(self.metadata_score, 4),
            "visionScore": None if self.vision_score is None else round(self.vision_score, 4),
            "finalScore": round(self.final_score, 4),
            "status": self.status,
            "scoreReasons": self.score_reasons,
        }
        if self.vision_payload is not None:
            payload["visionPayload"] = self.vision_payload
        return payload


@dataclass(frozen=True)
class YouTubeRankingSettings:
    results_per_query: int = 10
    youtube_search_empty_retries: int = 5
    youtube_cookies: Path | None = None
    youtube_preview_cache_dir: Path | None = None
    max_candidates: int = 8
    metadata_candidate_pool_size: int | None = None
    min_duration_seconds: int = 10
    max_duration_seconds: int = 120
    use_deepseek_query_planner: bool = False
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_max_queries: int = 4
    deepseek_timeout_seconds: float = 60.0
    use_llama_cpp_query_planner: bool = False
    rank_with_vision: bool = False
    semantic_gate_enabled: bool = False
    semantic_gate_candidates_per_exercise: int | None = None
    semantic_gate_min_score: float = 0.55
    pose_prefilter_enabled: bool = False
    pose_prefilter_model: str = "yolo26x-pose.pt"
    pose_prefilter_candidates_per_exercise: int | None = None
    pose_prefilter_sample_fps: float = 2.0
    pose_prefilter_max_seconds: float = 90.0
    pose_prefilter_scan_strategy: str = "spread"
    pose_prefilter_window_seconds: float = 8.0
    pose_prefilter_overlap_seconds: float = 4.0
    pose_prefilter_min_score: float = 0.45
    pose_prefilter_min_keypoint_confidence: float = 0.35
    pose_prefilter_min_body_scale: float = 0.18
    pose_prefilter_workers: int = 3
    vision_candidates_per_exercise: int = 8
    vision_frames_per_candidate: int | None = 6
    vision_chunk_seconds: float | None = None
    vision_chunk_overlap_seconds: float | None = None
    vision_max_chunks_per_candidate: int | None = 5
    vision_adaptive_chunk_review: bool = True
    vision_initial_chunks_per_candidate: int = 3
    vision_expand_chunks_per_candidate: int = 2
    vision_motion_scan_sample_fps: float = 0.5
    vision_motion_scan_max_seconds: float = 90.0
    vision_contact_sheet_columns: int = 4
    vision_contact_sheet_tile_width: int = 320
    vision_contact_sheet_frames_per_sheet: int = 8
    vision_contact_sheet_jpeg_quality: int = 82
    vision_download_workers: int = 3
    vision_llm_workers: int = 3
    vision_model: str = "gemma-4-E4B-it"
    llama_cpp_base_url: str | None = "http://127.0.0.1:8090"
    llama_cpp_model: str = DEFAULT_LLAMA_CPP_MODEL
    llama_cpp_command: str | None = None
    llama_cpp_server_command: str | None = None
    llama_cpp_mmproj: str | None = DEFAULT_LLAMA_CPP_MMPROJ
    llama_cpp_backend: str = "gpu"
    llama_cpp_n_predict: int = 512
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
    include_disabled: bool = False
    vision_early_stop_score: float = 0.95

    def resolved_metadata_candidate_pool_size(self) -> int:
        if self.metadata_candidate_pool_size is not None:
            return max(1, self.metadata_candidate_pool_size)
        if self.rank_with_vision:
            return max(24, self.max_candidates, self.vision_candidates_per_exercise)
        if self.pose_prefilter_enabled:
            return max(24, self.max_candidates, self.resolved_pose_prefilter_candidates_per_exercise())
        return max(1, self.max_candidates)

    def resolved_pose_prefilter_candidates_per_exercise(self) -> int:
        if self.pose_prefilter_candidates_per_exercise is not None:
            return max(1, self.pose_prefilter_candidates_per_exercise)
        return max(self.max_candidates, self.vision_candidates_per_exercise)

    def resolved_semantic_gate_candidates_per_exercise(self) -> int:
        if self.semantic_gate_candidates_per_exercise is not None:
            explicit = max(1, self.semantic_gate_candidates_per_exercise)
            if self.pose_prefilter_enabled:
                return max(explicit, self.resolved_metadata_candidate_pool_size())
            return explicit
        if self.pose_prefilter_enabled:
            return max(
                self.resolved_pose_prefilter_candidates_per_exercise(),
                self.resolved_metadata_candidate_pool_size(),
            )
        return max(self.max_candidates, self.vision_candidates_per_exercise)


@dataclass(frozen=True)
class PreparedReviewWindow:
    index: int
    start_seconds: float
    end_seconds: float
    source: str = "fallback_even"


@dataclass
class PreparedVisionReview:
    candidate: YouTubeCandidate
    temp_dir: tempfile.TemporaryDirectory[str]
    frame_paths: list[Path]
    frame_path_chunks: list[list[Path]]
    chunk_windows: list[tuple[float, float]]
    chunk_count: int
    prompt: str
    video_path: Path | None = None
    review_windows: list[PreparedReviewWindow] = field(default_factory=list)
    frames_per_chunk: int = 0
    preview_preparation_elapsed_seconds: float = 0.0
    preview_download_elapsed_seconds: float = 0.0
    motion_scan_elapsed_seconds: float = 0.0
    window_planning_elapsed_seconds: float = 0.0
    rendered_chunk_cache: dict[int, tuple[list[Path], float]] = field(default_factory=dict)

    def close(self) -> None:
        self.temp_dir.cleanup()


SearchFn = Callable[[str, int], list[YouTubeCandidate]]
QueryPlannerFn = Callable[[ExerciseEntry, list[str], YouTubeRankingSettings], list[str]]
VisionRankResult = tuple[float, list[str]] | tuple[float, list[str], dict[str, Any] | None]
VisionRankerFn = Callable[[ExerciseEntry, YouTubeCandidate, YouTubeRankingSettings], VisionRankResult]
PoseRankResult = tuple[float, list[str], dict[str, Any] | None]
PoseRankerFn = Callable[[ExerciseEntry, YouTubeCandidate, YouTubeRankingSettings], PoseRankResult]
SemanticGateResult = tuple[float, list[str], dict[str, Any] | None]
SemanticGateFn = Callable[[ExerciseEntry, YouTubeCandidate, YouTubeRankingSettings], SemanticGateResult]


DEMO_KEYWORDS = (
    "demo",
    "demonstration",
    "form",
    "proper",
    "technique",
    "full body",
    "execution",
    "same angle",
    "single camera",
)
PENALTY_KEYWORDS = (
    "shorts",
    "#shorts",
    "music",
    "challenge",
    "vlog",
    "reaction",
    "compilation",
    "fail",
    "funny",
    "motivation",
    "title card",
    "tutorial",
    "how to",
    "explained",
    "mistakes",
    "guide",
    "workout",
    "elite",
    "record",
    "personal record",
    "new personal record",
    "pr",
    "amrap",
    "rep max",
    "1rm",
    "one rep max",
    "max attempt",
    "competition",
    "meet",
    "combine",
    "crowd",
    "watches",
    "camera angles",
    "bad camera",
    "shaky camera",
    "sorry for the camera",
)

SEMANTIC_GATE_OTHER_EXERCISE_TERMS = (
    "squat",
    "deadlift",
    "power clean",
    "clean and jerk",
    "snatch",
    "step up",
    "tricep extension",
    "biceps curl",
    "curl",
    "row",
    "pull up",
    "chin up",
    "lunge",
    "shoulder press",
    "overhead press",
    "kettlebell",
    "dumbbell",
)

SEMANTIC_GATE_TITLE_ALIASES_BY_EXERCISE = {
    "barbell bench press": ("bench press", "barbell bench", "panca piana", "flat bench"),
    "bench press": ("bench press", "panca piana", "flat bench"),
    "bulgarian split squat": (
        "bulgarian split squat",
        "bulgarian squat",
        "rear foot elevated split squat",
        "rfess",
    ),
}
YOUTUBE_QUERY_EQUIPMENT_ALIASES = {
    "barbell": ("barbell", "bb"),
    "dumbbell": ("dumbbell", "dumbbells", "db"),
    "kettlebell": ("kettlebell", "kettlebells", "kb"),
}
YOUTUBE_QUERY_EQUIPMENT_PREFIXES = (
    "barbell",
    "dumbbell",
    "kettlebell",
    "cable",
    "machine",
    "smith machine",
)
EXERCISE_VARIANT_TERMS = (
    "incline",
    "decline",
    "close grip",
    "wide grip",
    "neutral grip",
    "mixed grip",
    "reverse grip",
    "underhand",
    "overhand",
    "smith machine",
    "machine",
    "cable",
    "floor",
    "seated",
    "standing",
    "kneeling",
    "bent over",
    "chest supported",
    "supported",
    "unsupported",
    "single arm",
    "one arm",
    "single leg",
    "one leg",
    "front foot elevated",
    "rear foot elevated",
    "deficit",
    "box",
    "sumo",
    "conventional",
    "romanian",
    "stiff leg",
    "paused",
    "tempo",
    "eccentric",
    "negative",
    "isometric",
    "assisted",
    "band assisted",
    "banded",
    "weighted",
    "jumping",
    "kipping",
    "butterfly",
    "chest to bar",
    "chin up",
    "commando",
    "pin press",
    "board press",
    "spoto",
    "triceps press",
)
SOURCE_ATTEMPT_REASON_CAPS = {
    "record_penalty": 0.67,
    "personal_record_penalty": 0.67,
    "new_personal_record_penalty": 0.67,
    "pr_penalty": 0.67,
    "amrap_penalty": 0.67,
    "rep_max_penalty": 0.67,
    "1rm_penalty": 0.67,
    "one_rep_max_penalty": 0.67,
    "max_attempt_penalty": 0.67,
    "competition_penalty": 0.67,
    "meet_penalty": 0.67,
    "combine_penalty": 0.67,
}
SOURCE_VARIANT_CAP = 0.34
POSE_QUALITY_REASON_CAPS = {
    "pose_cropped_body": 0.67,
}
SEMANTIC_POSE_BACKFILL_MIN_SCORE = 0.35
REST_COMPONENT_TYPES = {"rest", "recovery", "break"}
NON_MOTION_EXERCISE_TYPES = {"countdown"}


def load_workout_plan_exercises(plan_path: Path, *, include_disabled: bool = False) -> list[ExerciseEntry]:
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    return extract_workout_plan_exercises(payload, include_disabled=include_disabled)


def extract_workout_plan_exercises(payload: Any, *, include_disabled: bool = False) -> list[ExerciseEntry]:
    raw_entries: list[tuple[str | None, str]] = []

    def is_disabled(node: dict[str, Any]) -> bool:
        if include_disabled:
            return False
        if node.get("disabled") is True:
            return True
        if node.get("isDisabled") is True:
            return True
        if node.get("enabled") is False:
            return True
        if node.get("isEnabled") is False:
            return True
        return False

    def is_rest(node: dict[str, Any]) -> bool:
        component_type = str(
            node.get("type")
            or node.get("componentType")
            or node.get("kind")
            or node.get("exerciseType")
            or ""
        ).strip().lower()
        name = str(node.get("exerciseName") or node.get("name") or "").strip().lower()
        exercise_type = str(node.get("exerciseType") or "").strip().lower()
        return (
            component_type in REST_COMPONENT_TYPES
            or name in REST_COMPONENT_TYPES
            or exercise_type in NON_MOTION_EXERCISE_TYPES
        )

    def is_group_container(node: dict[str, Any]) -> bool:
        component_type = str(
            node.get("type")
            or node.get("componentType")
            or node.get("kind")
            or ""
        ).strip().lower()
        if component_type in {"superset", "circuit", "group", "round"}:
            return True
        return any(
            isinstance(node.get(key), list)
            for key in ("workoutComponents", "components", "children", "items", "supersetExercises")
        ) and "exerciseName" not in node and "exercise" not in node

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        if is_disabled(node) or is_rest(node):
            return

        name = None if is_group_container(node) else extract_exercise_name(node)
        if name:
            raw_entries.append((extract_exercise_id(node), name))

        for key in (
            "workoutComponents",
            "components",
            "children",
            "items",
            "supersetExercises",
            "exercises",
            "exerciseComponents",
        ):
            if key in node:
                visit(node[key])

    if isinstance(payload, dict) and isinstance(payload.get("WorkoutStore"), dict):
        visit(payload["WorkoutStore"].get("workouts", []))
    elif isinstance(payload, dict) and isinstance(payload.get("workouts"), list):
        for workout in payload["workouts"]:
            if isinstance(workout, dict):
                visit(workout.get("workoutComponents", []))
    elif isinstance(payload, dict) and isinstance(payload.get("exercises"), list):
        visit(payload["exercises"])
    else:
        visit(payload)

    entries: list[ExerciseEntry] = []
    seen: set[str] = set()
    for source_id, name in raw_entries:
        normalized = normalize_exercise_name(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        entries.append(
            ExerciseEntry(
                exercise_id=source_id or f"EXERCISE_{len(entries)}",
                name=name.strip(),
                slug=slugify(name),
            )
        )
    return entries


def extract_exercise_name(node: dict[str, Any]) -> str | None:
    for key in ("exerciseName", "name", "title"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exercise = node.get("exercise")
    if isinstance(exercise, dict):
        return extract_exercise_name(exercise)
    return None


def extract_exercise_id(node: dict[str, Any]) -> str | None:
    for key in ("exerciseId", "id", "uuid"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exercise = node.get("exercise")
    if isinstance(exercise, dict):
        return extract_exercise_id(exercise)
    return None


def normalize_exercise_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "exercise"


def build_youtube_queries(exercise_name: str) -> list[str]:
    base = exercise_name.strip()
    base_term = quote_youtube_search_term(base)
    exclusions = build_youtube_query_exclusion_suffix(base)
    queries = [
        f"{base_term} exercise demonstration{exclusions}",
        f"{base_term} exercise demo full rep{exclusions}",
        f"{base_term} proper form{exclusions}",
        f"{base_term} side view exercise{exclusions}",
        f"{base_term} single person exercise demo{exclusions}",
    ]
    for alias in generic_youtube_query_aliases(base):
        alias_term = quote_youtube_search_term(alias)
        queries.extend(
            [
                f"{alias_term} exercise demonstration{exclusions}",
                f"{alias_term} exercise demo full rep{exclusions}",
                f"{alias_term} side view exercise{exclusions}",
            ]
        )
    return merge_youtube_queries(queries)


def quote_youtube_search_term(term: str) -> str:
    normalized = re.sub(r"\s+", " ", str(term)).strip()
    if not normalized:
        return ""
    escaped = normalized.replace('"', "")
    return f'"{escaped}"'


def generic_youtube_query_aliases(exercise_name: str) -> list[str]:
    normalized = normalize_exercise_name(exercise_name)
    aliases: list[str] = []
    for prefix in YOUTUBE_QUERY_EQUIPMENT_PREFIXES:
        normalized_prefix = normalize_exercise_name(prefix)
        if normalized == normalized_prefix:
            continue
        if normalized.startswith(f"{normalized_prefix} "):
            stripped = normalized[len(normalized_prefix) + 1 :].strip()
            if stripped:
                aliases.append(stripped.title())
    return aliases


def build_youtube_query_exclusion_suffix(exercise_name: str) -> str:
    normalized_exercise = normalize_exercise_name(exercise_name)
    exclusions = [
        "-tutorial",
        "-shorts",
        "-record",
        "-competition",
        "-amrap",
        "-1rm",
        "-workout",
        "-program",
        "-music",
        "-audio",
        "-song",
        "-lyrics",
        "-dance",
    ]
    for term in ("incline", "decline", "machine"):
        normalized_term = normalize_exercise_name(term)
        if normalized_term not in normalized_exercise:
            exclusions.append(f'-"{term}"' if " " in term else f"-{term}")
    return " " + " ".join(exclusions)


def merge_youtube_queries(queries: Iterable[str], *, limit: int | None = None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = normalize_search_query(query)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
        if limit is not None and len(merged) >= limit:
            break
    return merged


def normalize_search_query(query: str) -> str:
    normalized = re.sub(r"\s+", " ", str(query)).strip()
    if normalized.startswith(("http://", "https://")):
        return ""
    if len(normalized) <= 180:
        return normalized
    parts = normalized.split()
    trimmed: list[str] = []
    for part in parts:
        candidate = " ".join([*trimmed, part])
        if len(candidate) > 180:
            break
        trimmed.append(part)
    return " ".join(trimmed).strip()


def normalize_generated_youtube_query(query: str, *, exercise_name: str) -> str:
    normalized = normalize_search_query(query)
    if not normalized:
        return ""
    exclusions = build_youtube_query_exclusion_suffix(exercise_name).split() if exercise_name else []
    existing = {part.casefold() for part in normalized.split()}
    missing = [item for item in exclusions if item.casefold() not in existing]
    return normalize_search_query(" ".join([normalized, *missing]))


def parse_youtube_query_planner_payload(
    raw: str,
    *,
    exercise_name: str,
    max_queries: int,
) -> list[str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        from exercise_motion_pkg.segment_detection import extract_json_object

        extracted = extract_json_object(raw)
        payload = extracted if isinstance(extracted, dict) else {}
    raw_queries = payload.get("queries") if isinstance(payload, dict) else None
    if not isinstance(raw_queries, list):
        return []
    return merge_youtube_queries(
        [
            normalize_generated_youtube_query(query, exercise_name=exercise_name)
            for query in raw_queries
            if isinstance(query, str)
        ],
        limit=max(0, max_queries),
    )


class LlamaCppYouTubeQueryPlanner:
    def __init__(
        self,
        settings: YouTubeRankingSettings,
        *,
        shared_ranker: Any | None = None,
    ) -> None:
        self.settings = settings
        self._shared_ranker = shared_ranker
        self._owned_ranker = None if shared_ranker is not None else LlamaCppVisionRanker(settings)

    @property
    def _ranker(self) -> Any:
        ranker = self._shared_ranker or self._owned_ranker
        if ranker is None:
            raise RuntimeError("llama.cpp query planner is not initialized.")
        return ranker

    def __call__(
        self,
        exercise: ExerciseEntry,
        base_queries: list[str],
        settings: YouTubeRankingSettings,
    ) -> list[str]:
        prompt = build_youtube_query_planner_prompt(
            exercise_name=exercise.name,
            base_queries=base_queries,
            max_queries=settings.deepseek_max_queries,
        )
        raw = self._ranker.client.caption_images(frame_paths=[], prompt=prompt)
        return parse_youtube_query_planner_payload(
            raw,
            exercise_name=exercise.name,
            max_queries=settings.deepseek_max_queries,
        )

    def close(self) -> None:
        if self._owned_ranker is not None:
            self._owned_ranker.close()


class DeepSeekYouTubeQueryPlanner:
    def __init__(
        self,
        settings: YouTubeRankingSettings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        api_key = settings.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DeepSeek query planning requires --deepseek-api-key or DEEPSEEK_API_KEY.")
        self.settings = settings
        self.api_key = api_key
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=settings.deepseek_timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __call__(
        self,
        exercise: ExerciseEntry,
        base_queries: list[str],
        settings: YouTubeRankingSettings,
    ) -> list[str]:
        prompt = build_deepseek_query_planner_prompt(
            exercise_name=exercise.name,
            base_queries=base_queries,
            max_queries=settings.deepseek_max_queries,
        )
        payload = {
            "model": settings.deepseek_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate YouTube search queries for finding clean exercise demo "
                        "source videos for motion extraction. You do not browse or return URLs."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return parse_youtube_query_planner_payload(
            content,
            exercise_name=exercise.name,
            max_queries=settings.deepseek_max_queries,
        )


def build_youtube_query_planner_prompt(
    *,
    exercise_name: str,
    base_queries: list[str],
    max_queries: int,
) -> str:
    return (
        f"Target exercise: {exercise_name}\n"
        f"Baseline queries already used: {json.dumps(base_queries)}\n"
        f"Return up to {max(1, max_queries)} additional YouTube search queries.\n"
        "Queries should favor videos that are good WHAM inputs: a single person, the whole relevant body "
        "or implement visible, static camera, continuous normal-speed repetitions, no camera cuts, and no "
        "nearby people or obstructions.\n"
        "Use YouTube search syntax when useful, including negative terms like -shorts, -tutorial, -workout, "
        "or -mistakes.\n"
        "Prefer exact quoted exercise names and exact common aliases. Avoid broad phrases that can match "
        "music, challenges, tutorials, commentary, or general workouts.\n"
        "If the target is a basic exercise name, generate queries for the basic/common version only. Do not add "
        "variant terms such as chest-to-bar, kipping, butterfly, banded, assisted, jumping, negative, weighted, "
        "chin-up, grip-specific, machine, incline, decline, seated, supported, single-arm, or single-leg unless "
        "the target exercise already includes that qualifier.\n"
        "Do not return URLs. Return JSON only: {\"queries\": [\"...\"]}."
    )


def build_deepseek_query_planner_prompt(
    *,
    exercise_name: str,
    base_queries: list[str],
    max_queries: int,
) -> str:
    return build_youtube_query_planner_prompt(
        exercise_name=exercise_name,
        base_queries=base_queries,
        max_queries=max_queries,
    )


def parse_deepseek_query_payload(raw: str, *, max_queries: int) -> list[str]:
    return parse_youtube_query_planner_payload(
        raw,
        exercise_name="",
        max_queries=max_queries,
    )


def search_youtube(query: str, results_per_query: int) -> list[YouTubeCandidate]:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--dump-single-json",
        "--flat-playlist",
        "--skip-download",
        "--ignore-errors",
        "--no-warnings",
        "--socket-timeout",
        "12",
        "--retries",
        "1",
        "--extractor-retries",
        "1",
        f"ytsearch{max(1, results_per_query)}:{query}",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=35,
        )
    except subprocess.TimeoutExpired:
        print(f"WARNING: YouTube search timed out for query {query!r}.", file=sys.stderr)
        return []
    if completed.returncode != 0:
        error = truncate_text(completed.stderr or completed.stdout or "yt-dlp failed", 240)
        print(f"WARNING: YouTube search failed for query {query!r}: {error}", file=sys.stderr)
        return []
    try:
        info = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        print(f"WARNING: YouTube search returned invalid JSON for query {query!r}: {exc}", file=sys.stderr)
        return []
    return parse_yt_dlp_search_results(info)


def parse_yt_dlp_search_results(info: dict[str, Any]) -> list[YouTubeCandidate]:
    entries = info.get("entries") if isinstance(info, dict) else None
    if not isinstance(entries, list):
        return []
    candidates: list[YouTubeCandidate] = []
    for entry in entries:
        if isinstance(entry, dict):
            candidates.append(candidate_from_yt_dlp_entry(entry))
    return candidates


def select_evenly_spaced_review_windows(windows: list[Any], max_windows: int | None) -> list[Any]:
    if max_windows is None or max_windows <= 0 or len(windows) <= max_windows:
        return windows
    if max_windows == 1:
        return [windows[len(windows) // 2]]
    indexes = {
        round(index * (len(windows) - 1) / (max_windows - 1))
        for index in range(max_windows)
    }
    return [windows[index] for index in sorted(indexes)]


def select_review_windows_by_budget(
    windows: list[PreparedReviewWindow],
    max_windows: int | None,
) -> list[PreparedReviewWindow]:
    if max_windows is None or max_windows <= 0 or len(windows) <= max_windows:
        return reindex_review_windows(windows)
    motion_windows = [window for window in windows if window.source == "motion_interval"]
    coverage_windows = [window for window in windows if window.source != "motion_interval"]
    selected = [*motion_windows[: max(0, max_windows - 1)], *coverage_windows[:1]]
    if len(selected) < max_windows:
        selected_keys = {(round(window.start_seconds, 3), round(window.end_seconds, 3)) for window in selected}
        selected.extend(
            window
            for window in windows
            if (round(window.start_seconds, 3), round(window.end_seconds, 3)) not in selected_keys
        )
    return reindex_review_windows(selected[:max_windows])


def add_coverage_review_window(
    windows: list[PreparedReviewWindow],
    *,
    duration_seconds: float,
    window_seconds: float,
) -> list[PreparedReviewWindow]:
    if duration_seconds <= 0.0 or window_seconds <= 0.0:
        return windows
    midpoint = duration_seconds / 2.0
    start = max(0.0, min(max(0.0, duration_seconds - window_seconds), midpoint - (window_seconds / 2.0)))
    end = min(duration_seconds, start + window_seconds)
    key = (round(start, 3), round(end, 3))
    existing = {
        (round(window.start_seconds, 3), round(window.end_seconds, 3))
        for window in windows
    }
    if key in existing or end <= start:
        return windows
    return [
        *windows,
        PreparedReviewWindow(
            index=len(windows),
            start_seconds=start,
            end_seconds=end,
            source="coverage_probe",
        ),
    ]


def reindex_review_windows(windows: list[PreparedReviewWindow]) -> list[PreparedReviewWindow]:
    return [
        PreparedReviewWindow(
            index=index,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
            source=window.source,
        )
        for index, window in enumerate(windows)
    ]


def candidate_from_yt_dlp_entry(entry: dict[str, Any]) -> YouTubeCandidate:
    video_id = as_optional_string(entry.get("id") or entry.get("display_id"))
    url = as_optional_string(entry.get("webpage_url") or entry.get("url"))
    if url and url.startswith("http"):
        resolved_url = url
    elif video_id:
        resolved_url = f"https://www.youtube.com/watch?v={video_id}"
    else:
        resolved_url = str(url or "")
    thumbnails = entry.get("thumbnails")
    thumbnail = None
    if isinstance(thumbnails, list) and thumbnails:
        last = thumbnails[-1]
        if isinstance(last, dict):
            thumbnail = as_optional_string(last.get("url"))
    return YouTubeCandidate(
        url=resolved_url,
        video_id=video_id,
        title=as_optional_string(entry.get("title")) or "",
        channel=as_optional_string(entry.get("channel") or entry.get("uploader")),
        duration_seconds=as_optional_int(entry.get("duration")),
        view_count=as_optional_int(entry.get("view_count")),
        upload_date=as_optional_string(entry.get("upload_date")),
        description_snippet=truncate_text(as_optional_string(entry.get("description")) or "", 260),
        thumbnail=thumbnail or as_optional_string(entry.get("thumbnail")),
    )


def as_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def truncate_text(value: str, limit: int) -> str | None:
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def score_candidate_metadata(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    *,
    min_duration_seconds: int,
    max_duration_seconds: int,
) -> YouTubeCandidate:
    text = f"{candidate.title} {candidate.description_snippet or ''}".lower()
    normalized_text = normalize_exercise_name(text)
    exercise_tokens = normalize_exercise_name(exercise.name).split()
    score = 0.20
    reasons: list[str] = []

    if exercise_tokens and all(token in normalized_text.split() for token in exercise_tokens):
        score += 0.30
        reasons.append("exercise_name_match")
    elif exercise_tokens and any(token in normalized_text.split() for token in exercise_tokens):
        score += 0.12
        reasons.append("partial_exercise_name_match")

    for keyword in DEMO_KEYWORDS:
        if keyword in text:
            score += 0.05
            reasons.append(f"{slugify(keyword).replace('-', '_')}_keyword")
    for keyword in PENALTY_KEYWORDS:
        if keyword_matches_text(keyword, text):
            score -= 0.12
            reasons.append(f"{slugify(keyword).replace('-', '_')}_penalty")
    for variant in unrequested_variant_terms(text, exercise.name):
        score -= 0.18
        reasons.append(f"unrequested_{slugify(variant).replace('-', '_')}_variant_penalty")

    duration = candidate.duration_seconds
    if duration is None:
        reasons.append("duration_unknown")
    elif min_duration_seconds <= duration <= max_duration_seconds:
        score += 0.18
        reasons.append("usable_duration")
    elif duration < min_duration_seconds:
        score -= 0.24
        reasons.append("too_short")
    else:
        score -= 0.10
        reasons.append("too_long")

    if candidate.view_count is not None:
        if candidate.view_count >= 100_000:
            score += 0.08
            reasons.append("popular_video")
        elif candidate.view_count < 1_000:
            score -= 0.04
            reasons.append("low_view_count")

    score = clamp_score(score)
    return replace_candidate(
        candidate,
        metadata_score=score,
        final_score=score,
        status=status_for_score(score),
        score_reasons=dedupe_reasons(reasons),
    )


def vision_review_priority_score(
    candidate: YouTubeCandidate,
    *,
    min_duration_seconds: int,
    max_duration_seconds: int,
) -> float:
    reasons = set(candidate.score_reasons)
    score = candidate.metadata_score * 0.20
    if "exercise_name_match" in reasons:
        score += 0.35
    elif "partial_exercise_name_match" in reasons:
        score += 0.12
    source_keyword_count = sum(
        1
        for reason in reasons
        if reason.endswith("_keyword") and reason.removesuffix("_keyword") in {
            slugify(keyword).replace("-", "_") for keyword in DEMO_KEYWORDS
        }
    )
    score += min(0.30, source_keyword_count * 0.12)
    duration = candidate.duration_seconds
    if duration is None:
        score -= 0.04
    elif duration < min_duration_seconds:
        score -= 0.45
    elif duration <= max_duration_seconds:
        score += 0.10
    elif duration <= max_duration_seconds * 2:
        score -= 0.02
    elif duration <= max_duration_seconds * 5:
        score -= 0.12
    else:
        score -= 0.30
    if has_source_quality_demoter(candidate.score_reasons):
        score -= 0.35
    if "low_view_count" in reasons:
        score -= 0.03
    return clamp_score(score)


def unrequested_variant_terms(candidate_text: str, exercise_name: str) -> list[str]:
    normalized_candidate = normalize_exercise_name(candidate_text)
    normalized_exercise = normalize_exercise_name(exercise_name)
    allowed_identity_text = " ".join(
        [
            normalized_exercise,
            *semantic_gate_title_aliases(normalized_exercise),
        ]
    )
    found: list[str] = []
    for term in EXERCISE_VARIANT_TERMS:
        normalized_term = normalize_exercise_name(term)
        if not normalized_phrase_in_text(normalized_term, normalized_candidate):
            continue
        if normalized_phrase_in_text(normalized_term, allowed_identity_text):
            continue
        if normalized_term not in found:
            found.append(term)
    return found


def keyword_matches_text(keyword: str, text: str) -> bool:
    if keyword.startswith("#"):
        return keyword in text
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def replace_candidate(candidate: YouTubeCandidate, **changes: Any) -> YouTubeCandidate:
    payload = {
        "url": candidate.url,
        "video_id": candidate.video_id,
        "title": candidate.title,
        "channel": candidate.channel,
        "duration_seconds": candidate.duration_seconds,
        "view_count": candidate.view_count,
        "upload_date": candidate.upload_date,
        "description_snippet": candidate.description_snippet,
        "thumbnail": candidate.thumbnail,
        "metadata_score": candidate.metadata_score,
        "vision_score": candidate.vision_score,
        "final_score": candidate.final_score,
        "status": candidate.status,
        "score_reasons": list(candidate.score_reasons),
        "vision_payload": candidate.vision_payload,
    }
    payload.update(changes)
    return YouTubeCandidate(**payload)


def dedupe_reasons(reasons: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            result.append(reason)
    return result


POSE_PREFILTER_HARD_REJECT_ISSUES = {
    "multiple_people",
    "no_person_detected",
    "low_keypoint_coverage",
    "cropped_body",
    "camera_or_track_instability",
    "weak_body_joint_motion",
    "low_active_chain_visibility",
}


def pose_prefilter_blocking_issues(pose_payload: dict[str, Any]) -> list[str]:
    value = pose_payload.get("blockingIssues")
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        return []
    issues: list[str] = []
    for item in raw_items:
        text = str(item).strip().lower()
        if text and text not in issues:
            issues.append(text)
    return issues


def pose_prefilter_has_hard_reject_issue(pose_payload: dict[str, Any]) -> bool:
    return any(issue in POSE_PREFILTER_HARD_REJECT_ISSUES for issue in pose_prefilter_blocking_issues(pose_payload))


def pose_prefilter_hard_reject_reasons(pose_payload: dict[str, Any]) -> list[str]:
    issues = [
        issue
        for issue in pose_prefilter_blocking_issues(pose_payload)
        if issue in POSE_PREFILTER_HARD_REJECT_ISSUES
    ]
    if not issues:
        return []
    return dedupe_reasons(
        [
            "pose_prefilter_hard_reject",
            *[f"pose_prefilter_{issue}_hard_reject" for issue in issues],
        ]
    )


def candidate_has_pose_prefilter_hard_reject(candidate: YouTubeCandidate) -> bool:
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    pose_payload = payload.get("posePrefilter") if isinstance(payload, dict) else None
    return isinstance(pose_payload, dict) and pose_prefilter_has_hard_reject_issue(pose_payload)


def candidate_pose_prefilter_hard_reject_reasons(candidate: YouTubeCandidate) -> list[str]:
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    pose_payload = payload.get("posePrefilter") if isinstance(payload, dict) else None
    if not isinstance(pose_payload, dict):
        return []
    return pose_prefilter_hard_reject_reasons(pose_payload)


def clamp_score(score: float) -> float:
    return max(0.0, min(1.0, score))


def round_elapsed(seconds: float) -> float:
    return round(max(0.0, seconds), 3)


def sum_candidate_vision_payload_number(exercise_payloads: list[dict[str, Any]], key: str) -> float:
    total = 0.0
    for exercise in exercise_payloads:
        candidates = exercise.get("candidates")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            payload = candidate.get("visionPayload")
            if not isinstance(payload, dict):
                continue
            value = payload.get(key)
            if isinstance(value, (int, float)):
                total += float(value)
    return total


def status_for_score(score: float) -> str:
    if score >= 0.68:
        return "recommended"
    if score >= 0.35:
        return "candidate"
    return "rejected"


def compose_final_score(metadata_score: float, vision_score: float | None) -> float:
    if vision_score is None:
        return clamp_score(metadata_score)
    return clamp_score(metadata_score * 0.10 + vision_score * 0.90)


def apply_source_quality_caps(score: float, reasons: list[str]) -> tuple[float, list[str]]:
    capped = clamp_score(score)
    cap_reasons: list[str] = []
    if any(is_unrequested_variant_reason(reason) for reason in reasons):
        capped = min(capped, SOURCE_VARIANT_CAP)
        cap_reasons.append("unrequested_variant_source_cap")
    for reason, cap in SOURCE_ATTEMPT_REASON_CAPS.items():
        if reason in reasons:
            capped = min(capped, cap)
            cap_reasons.append("max_or_competition_attempt_source_cap")
            break
    for reason, cap in POSE_QUALITY_REASON_CAPS.items():
        if reason in reasons:
            capped = min(capped, cap)
            cap_reasons.append("borderline_full_body_frame_source_cap")
            break
    return capped, cap_reasons


def is_unrequested_variant_reason(reason: str) -> bool:
    return reason.startswith("unrequested_") and reason.endswith("_variant_penalty")


def has_source_quality_demoter(reasons: list[str]) -> bool:
    return (
        any(is_unrequested_variant_reason(reason) for reason in reasons)
        or any(reason in SOURCE_ATTEMPT_REASON_CAPS for reason in reasons)
        or any(reason in POSE_QUALITY_REASON_CAPS for reason in reasons)
        or "unrequested_variant_source_cap" in reasons
        or "max_or_competition_attempt_source_cap" in reasons
        or "borderline_full_body_frame_source_cap" in reasons
    )


VISION_HARD_GATE_REASONS = {
    "correct_exercise",
    "usable_for_motion_extraction",
    "complete_repetition_visible",
    "exercise_only_chunk",
    "normal_speed_execution",
    "not_broken_into_steps",
    "continuous_motion",
    "athlete_fully_in_frame_throughout",
    "static_camera_throughout",
    "single_camera_angle",
    "no_step_breakdown",
    "no_camera_cuts",
    "unobstructed_motion",
    "key_joints_visible",
    "large_body_visible",
    "pose_friendly_camera_angle",
    "body_joint_motion_visible",
    "low_equipment_occlusion",
    "critical_moving_joints_visible",
    "low_critical_joint_occlusion",
    "reconstruction_suitable",
    "single_person_chunk",
    "real_human_subject",
    "movement_start_posture_visible",
    "primary_effort_phase_visible",
    "movement_action_path_visible",
    "movement_end_posture_visible",
    "no_setup_or_talking_frames",
}


def candidate_passes_vision_hard_gates(
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> bool:
    if candidate_has_pose_prefilter_hard_reject(candidate):
        return False
    if candidate.vision_score is None or candidate.vision_score < settings.vision_early_stop_score:
        return False
    if has_source_quality_demoter(candidate.score_reasons):
        return False
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    if bool(payload.get("chunkEvidenceCapApplied")):
        return False
    valid_chunk_count = as_optional_int(payload.get("validChunkCount"))
    if valid_chunk_count is not None and valid_chunk_count <= 0:
        return False
    return VISION_HARD_GATE_REASONS.issubset(set(candidate.score_reasons))


def normalize_vision_result(result: VisionRankResult) -> tuple[float, list[str], dict[str, Any] | None]:
    if len(result) >= 3:
        score, reasons, payload = result
        return score, reasons, payload
    score, reasons = result
    return score, reasons, None


def normalize_pose_result(result: PoseRankResult) -> tuple[float, list[str], dict[str, Any] | None]:
    score, reasons, payload = result
    return score, reasons, payload


def normalize_semantic_gate_result(result: SemanticGateResult) -> tuple[float, list[str], dict[str, Any] | None]:
    score, reasons, payload = result
    return score, reasons, payload


def rank_candidates_with_semantic_gate(
    *,
    exercise: ExerciseEntry,
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
    semantic_gate: SemanticGateFn | None = None,
) -> list[YouTubeCandidate]:
    if not ranked:
        return []
    limit = min(len(ranked), settings.resolved_semantic_gate_candidates_per_exercise())
    candidates_to_review = ranked[:limit]
    active_gate = semantic_gate or rank_candidate_with_llama_cpp_semantic_gate
    workers = max(1, min(settings.vision_llm_workers, len(candidates_to_review)))
    scored_by_key: dict[str, YouTubeCandidate] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(active_gate, exercise, candidate, settings): candidate
            for candidate in candidates_to_review
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                semantic_score, semantic_reasons, semantic_payload = normalize_semantic_gate_result(future.result())
                scored_by_key[candidate.key()] = apply_semantic_gate_score(
                    candidate,
                    exercise=exercise,
                    semantic_score=semantic_score,
                    semantic_reasons=semantic_reasons,
                    semantic_payload=semantic_payload,
                    settings=settings,
                )
            except Exception as exc:
                scored_by_key[candidate.key()] = apply_semantic_gate_score(
                    candidate,
                    exercise=exercise,
                    semantic_score=0.0,
                    semantic_reasons=["semantic_gate_failed"],
                    semantic_payload={
                        "enabled": True,
                        "passed": False,
                        "score": 0.0,
                        "error": str(exc),
                    },
                    settings=settings,
                )
    reviewed = [scored_by_key.get(candidate.key(), candidate) for candidate in candidates_to_review]
    if settings.pose_prefilter_enabled:
        narrowed = [
            candidate
            for candidate in reviewed
            if candidate_is_semantic_pose_candidate(candidate, settings=settings)
        ]
    else:
        narrowed = [
            candidate
            for candidate in reviewed
            if candidate_semantic_gate_passed(candidate)
        ]
    narrowed.sort(key=lambda item: (semantic_gate_score(item), item.metadata_score, item.final_score), reverse=True)
    return narrowed


def apply_semantic_gate_score(
    candidate: YouTubeCandidate,
    *,
    exercise: ExerciseEntry,
    semantic_score: float,
    semantic_reasons: list[str],
    semantic_payload: dict[str, Any] | None,
    settings: YouTubeRankingSettings,
) -> YouTubeCandidate:
    clamped_score = clamp_score(semantic_score)
    payload = dict(candidate.vision_payload) if isinstance(candidate.vision_payload, dict) else {}
    semantic_payload = dict(semantic_payload) if isinstance(semantic_payload, dict) else {}
    conflict_reasons = semantic_gate_text_conflict_reasons(exercise, candidate)
    deterministic_unrequested_variants = unrequested_variant_terms(candidate.title, exercise.name)
    model_unrequested_variants = semantic_payload_unrequested_variant_terms(semantic_payload)
    unrequested_variants = dedupe_reasons([*deterministic_unrequested_variants, *model_unrequested_variants])
    if unrequested_variants:
        semantic_payload["unrequestedVariantTerms"] = unrequested_variants
        conflict_reasons = dedupe_reasons(
            [
                *conflict_reasons,
                *[
                    f"semantic_unrequested_{slugify(variant).replace('-', '_')}_variant"
                    for variant in model_unrequested_variants
                    if slugify(variant)
                ],
            ]
        )
    if conflict_reasons:
        clamped_score = min(clamped_score, 0.20)
        existing_conflicts = semantic_payload.get("textConflictReasons")
        if isinstance(existing_conflicts, list):
            semantic_payload["textConflictReasons"] = dedupe_reasons(
                [str(item) for item in existing_conflicts] + conflict_reasons
            )
        else:
            semantic_payload["textConflictReasons"] = conflict_reasons
        semantic_reasons = dedupe_reasons([*semantic_reasons, *conflict_reasons])
    wrong_exercise = bool(semantic_payload.get("wrongExercise"))
    passed = clamped_score >= settings.semantic_gate_min_score and not wrong_exercise
    semantic_payload.setdefault("enabled", True)
    semantic_payload["passed"] = passed
    semantic_payload["score"] = clamped_score
    payload["semanticGate"] = semantic_payload
    score_reasons = dedupe_reasons(candidate.score_reasons + semantic_reasons)
    if passed:
        score_reasons = dedupe_reasons([*score_reasons, "semantic_gate_passed"])
    else:
        score_reasons = dedupe_reasons([*score_reasons, "semantic_gate_rejected"])
    final_score = 0.0 if conflict_reasons else clamp_score(candidate.metadata_score * 0.55 + clamped_score * 0.45)
    final_score, cap_reasons = apply_source_quality_caps(final_score, score_reasons)
    return replace_candidate(
        candidate,
        final_score=final_score,
        status=status_for_score(final_score),
        score_reasons=dedupe_reasons(score_reasons + cap_reasons),
        vision_payload=payload,
    )


def semantic_payload_unrequested_variant_terms(semantic_payload: dict[str, Any]) -> list[str]:
    raw = semantic_payload.get("unrequestedVariantTerms")
    if raw is None:
        raw = semantic_payload.get("unrequested_variant_terms")
    if raw is None:
        raw = semantic_payload.get("addedQualifiers")
    if isinstance(raw, str):
        raw_items: list[Any] = [raw]
    elif isinstance(raw, list):
        raw_items = raw
    else:
        return []
    terms: list[str] = []
    for item in raw_items:
        text = normalize_exercise_name(str(item))
        if text and text not in terms:
            terms.append(text)
    return terms


def semantic_gate_score(candidate: YouTubeCandidate) -> float:
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    semantic_payload = payload.get("semanticGate") if isinstance(payload, dict) else None
    if not isinstance(semantic_payload, dict):
        return 0.0
    value = semantic_payload.get("score")
    return clamp_score(float(value)) if isinstance(value, (int, float)) else 0.0


def candidate_semantic_gate_payload(candidate: YouTubeCandidate) -> dict[str, Any] | None:
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    semantic_payload = payload.get("semanticGate") if isinstance(payload, dict) else None
    return semantic_payload if isinstance(semantic_payload, dict) else None


def candidate_semantic_gate_passed(candidate: YouTubeCandidate) -> bool:
    payload = candidate_semantic_gate_payload(candidate)
    return bool(payload and payload.get("passed"))


def candidate_is_semantic_pose_candidate(candidate: YouTubeCandidate, *, settings: YouTubeRankingSettings) -> bool:
    payload = candidate_semantic_gate_payload(candidate)
    if payload is None:
        return False
    if bool(payload.get("passed")):
        return True
    if bool(payload.get("wrongExercise")) or bool(payload.get("wrongEquipment")):
        return False
    text_conflicts = payload.get("textConflictReasons")
    if isinstance(text_conflicts, list) and text_conflicts:
        return False
    return semantic_gate_score(candidate) >= min(settings.semantic_gate_min_score, SEMANTIC_POSE_BACKFILL_MIN_SCORE)


def rank_candidate_with_llama_cpp_semantic_gate(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> SemanticGateResult:
    gate = LlamaCppSemanticGate(settings)
    try:
        return gate(exercise, candidate, settings)
    finally:
        gate.close()


def semantic_gate_text_conflict_reasons(exercise: ExerciseEntry, candidate: YouTubeCandidate) -> list[str]:
    normalized_exercise = normalize_exercise_name(exercise.name)
    normalized_title = normalize_exercise_name(candidate.title)
    normalized_description = normalize_exercise_name(candidate.description_snippet or "")
    candidate_text = candidate.title
    reasons: list[str] = []
    unrequested_variants = unrequested_variant_terms(candidate_text, exercise.name)
    if unrequested_variants:
        reasons.extend(
            [
                f"semantic_unrequested_{slugify(variant).replace('-', '_')}_variant"
                for variant in unrequested_variants
            ]
        )
    title_has_target = semantic_gate_text_contains_target_identity(normalized_exercise, normalized_title)
    other_terms = [
        term
        for term in SEMANTIC_GATE_OTHER_EXERCISE_TERMS
        if normalize_exercise_name(term) not in normalized_exercise
        and normalize_exercise_name(term) in normalized_title
    ]
    if other_terms:
        reasons.append("semantic_title_mentions_other_exercise")
    if not title_has_target:
        reasons.append("semantic_title_missing_target_identity")
        target_in_description = semantic_gate_text_contains_target_identity(
            normalized_exercise,
            normalized_description,
        )
        if target_in_description:
            reasons.append("semantic_target_only_in_description")
    return reasons


def semantic_gate_text_contains_target_identity(normalized_exercise: str, normalized_text: str) -> bool:
    aliases = semantic_gate_title_aliases(normalized_exercise)
    if aliases and any(normalized_phrase_in_text(alias, normalized_text) for alias in aliases):
        return True
    equipment_prefix, base_exercise = split_equipment_prefix(normalized_exercise)
    if equipment_prefix and base_exercise:
        base_aliases = semantic_gate_title_aliases(base_exercise)
        equipment_aliases = YOUTUBE_QUERY_EQUIPMENT_ALIASES.get(equipment_prefix, (equipment_prefix,))
        has_equipment = any(
            normalized_phrase_in_text(normalize_exercise_name(alias), normalized_text)
            for alias in equipment_aliases
        )
        has_base = any(normalized_phrase_in_text(alias, normalized_text) for alias in base_aliases)
        if has_equipment and has_base:
            return True
    if aliases:
        return False
    target_tokens = normalized_exercise.split()
    text_tokens = set(normalized_text.split())
    return bool(target_tokens) and all(token in text_tokens for token in target_tokens)


def semantic_gate_title_aliases(normalized_exercise: str) -> tuple[str, ...]:
    aliases = [
        normalize_exercise_name(alias)
        for alias in SEMANTIC_GATE_TITLE_ALIASES_BY_EXERCISE.get(normalized_exercise, ())
    ]
    equipment_prefix, base_exercise = split_equipment_prefix(normalized_exercise)
    if equipment_prefix and base_exercise:
        base_aliases = SEMANTIC_GATE_TITLE_ALIASES_BY_EXERCISE.get(base_exercise, ())
        equipment_aliases = YOUTUBE_QUERY_EQUIPMENT_ALIASES.get(equipment_prefix, ())
        for base_alias in base_aliases:
            normalized_base_alias = normalize_exercise_name(base_alias)
            if not normalized_base_alias:
                continue
            for equipment_alias in equipment_aliases:
                normalized_equipment_alias = normalize_exercise_name(equipment_alias)
                if not normalized_equipment_alias:
                    continue
                aliases.append(f"{normalized_equipment_alias} {normalized_base_alias}")
                aliases.append(f"{normalized_base_alias} {normalized_equipment_alias}")
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        if alias and alias not in seen:
            seen.add(alias)
            deduped.append(alias)
    return tuple(deduped)


def split_equipment_prefix(normalized_exercise: str) -> tuple[str | None, str | None]:
    for equipment_prefix in YOUTUBE_QUERY_EQUIPMENT_PREFIXES:
        normalized_prefix = normalize_exercise_name(equipment_prefix)
        if normalized_exercise.startswith(f"{normalized_prefix} "):
            base_exercise = normalized_exercise[len(normalized_prefix) + 1 :].strip()
            if base_exercise:
                return normalized_prefix, base_exercise
    return None, None


def normalized_phrase_in_text(normalized_phrase: str, normalized_text: str) -> bool:
    if not normalized_phrase:
        return False
    return re.search(
        rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])",
        normalized_text,
    ) is not None


def build_candidate_semantic_gate_prompt(exercise: ExerciseEntry, candidate: YouTubeCandidate) -> str:
    description = truncate_text(candidate.description_snippet or "", 800) or ""
    return (
        "You are a fast text-only semantic gate for YouTube exercise source selection.\n"
        "Score whether the candidate title/description is the exact target exercise. "
        "Do not inspect video frames. Be strict about the actual movement and equipment. "
        "High scores are only for the exact target exercise or a true common alias that preserves all defining qualifiers, equipment, support, stance, body position, and movement path. "
        "If the target exercise is a basic movement name, treat it as the basic/common version only. Do not accept named variants unless the target exercise itself names that variant. "
        "Give low scores to related variants that share a base pattern but change stance, support, elevation, implement, grip, machine/free-weight setup, incline/decline angle, unilateral/bilateral setup, tempo emphasis, or movement purpose. "
        "Examples: chest-to-bar, kipping, butterfly, banded, assisted, jumping, negative, weighted, chin-up, grip-specific, front-foot-elevated, machine, smith-machine, incline, decline, seated, supported, single-arm, or single-leg variants are wrong unless requested. "
        "Give low scores to broader categories, workout compilations, videos where the target is only implied by a muscle group, videos where the target is only briefly mentioned, and unrelated exercises. "
        "Return every candidate-added qualifier or named variant that is not present in the target exercise in unrequestedVariantTerms. If that list is non-empty, wrongExercise must be true and passed must be false. "
        "Accept common language aliases and translations only when they clearly refer to the same exact exercise, such as panca piana for flat bench press.\n"
        "Return JSON only with this schema: "
        "{\"passed\": boolean, \"score\": number, \"wrongExercise\": boolean, \"wrongEquipment\": boolean, "
        "\"unrequestedVariantTerms\": [string], \"matchedExercise\": string, \"reason\": string}.\n"
        "Use score 0.0 to 1.0 for confidence that the candidate is the exact requested exercise, not for general similarity. "
        "passed should be true only when score >= 0.55 and wrongExercise is false.\n"
        f"Target exercise: {exercise.name}\n"
        f"Candidate title: {candidate.title}\n"
        f"Candidate channel: {candidate.channel or ''}\n"
        f"Candidate description: {description}\n"
    )


def rank_candidates_with_pose_prefilter(
    *,
    exercise: ExerciseEntry,
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
    pose_ranker: PoseRankerFn | None = None,
) -> list[YouTubeCandidate]:
    if not ranked:
        return []
    limit = min(len(ranked), settings.resolved_pose_prefilter_candidates_per_exercise())
    candidates_to_review = ranked[:limit]
    active_ranker = pose_ranker or rank_candidate_with_yolo_pose
    workers = max(1, min(settings.pose_prefilter_workers, len(candidates_to_review)))
    scored_by_key: dict[str, YouTubeCandidate] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(active_ranker, exercise, candidate, settings): candidate
            for candidate in candidates_to_review
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                pose_score, pose_reasons, pose_payload = normalize_pose_result(future.result())
                scored_by_key[candidate.key()] = apply_pose_prefilter_score(
                    candidate,
                    pose_score=pose_score,
                    pose_reasons=pose_reasons,
                    pose_payload=pose_payload,
                    settings=settings,
                )
            except Exception as exc:
                scored_by_key[candidate.key()] = apply_pose_prefilter_score(
                    candidate,
                    pose_score=0.0,
                    pose_reasons=["pose_prefilter_failed"],
                    pose_payload={
                        "enabled": True,
                        "passed": False,
                        "score": 0.0,
                        "error": str(exc),
                    },
                    settings=settings,
                )
    reviewed = [scored_by_key.get(candidate.key(), candidate) for candidate in candidates_to_review]
    passed = [
        candidate
        for candidate in reviewed
        if isinstance(candidate.vision_payload, dict)
        and isinstance(candidate.vision_payload.get("posePrefilter"), dict)
        and bool(candidate.vision_payload["posePrefilter"].get("passed"))
    ]
    narrowed = reviewed if settings.semantic_gate_enabled else (passed if passed else reviewed)
    narrowed.sort(key=lambda item: (pose_prefilter_score(item), item.final_score), reverse=True)
    return narrowed


def apply_pose_prefilter_score(
    candidate: YouTubeCandidate,
    *,
    pose_score: float,
    pose_reasons: list[str],
    pose_payload: dict[str, Any] | None,
    settings: YouTubeRankingSettings,
) -> YouTubeCandidate:
    clamped_pose_score = clamp_score(pose_score)
    payload = dict(candidate.vision_payload) if isinstance(candidate.vision_payload, dict) else {}
    pose_payload = dict(pose_payload) if isinstance(pose_payload, dict) else {}
    pose_payload.setdefault("enabled", True)
    pose_payload.setdefault("score", clamped_pose_score)
    existing_quality_issues = pose_payload.get("qualityIssues")
    quality_issues = [str(item) for item in existing_quality_issues] if isinstance(existing_quality_issues, list) else []
    blocking_issues = set(pose_prefilter_blocking_issues(pose_payload))
    for reason in pose_reasons:
        if not reason.startswith("pose_"):
            continue
        if reason.startswith("pose_prefilter_"):
            continue
        issue = reason[len("pose_") :].strip().lower()
        if issue and issue not in blocking_issues and issue not in quality_issues:
            quality_issues.append(issue)
    if quality_issues:
        pose_payload["qualityIssues"] = quality_issues
    payload_passed = bool(pose_payload.get("passed", clamped_pose_score >= settings.pose_prefilter_min_score))
    hard_reject = pose_prefilter_has_hard_reject_issue(pose_payload)
    passed = payload_passed and clamped_pose_score >= settings.pose_prefilter_min_score and not hard_reject
    pose_payload["passed"] = passed
    payload["posePrefilter"] = pose_payload
    if passed:
        start_seconds = pose_payload.get("bestChunkStartSeconds")
        end_seconds = pose_payload.get("bestChunkEndSeconds")
        if "bestChunkStartSeconds" not in payload and isinstance(start_seconds, (int, float)):
            payload["bestChunkStartSeconds"] = float(start_seconds)
        if "bestChunkEndSeconds" not in payload and isinstance(end_seconds, (int, float)):
            payload["bestChunkEndSeconds"] = float(end_seconds)
        if "bestChunkScore" not in payload:
            payload["bestChunkScore"] = clamped_pose_score
        payload.setdefault("bestChunkSource", "pose_prefilter")
    pose_quality_reasons = [f"pose_{issue}" for issue in quality_issues]
    score_reasons = dedupe_reasons(candidate.score_reasons + pose_reasons + pose_quality_reasons)
    if hard_reject:
        score_reasons = dedupe_reasons([*score_reasons, *pose_prefilter_hard_reject_reasons(pose_payload)])
    if not passed:
        score_reasons = dedupe_reasons([*score_reasons, "pose_prefilter_rejected", "pose_prefilter_below_threshold"])
    final_score = 0.0 if not passed else clamp_score(candidate.metadata_score * 0.25 + clamped_pose_score * 0.75)
    final_score, cap_reasons = apply_source_quality_caps(final_score, score_reasons)
    score_reasons = dedupe_reasons(score_reasons + cap_reasons)
    return replace_candidate(
        candidate,
        final_score=final_score,
        status=status_for_score(final_score),
        score_reasons=score_reasons,
        vision_payload=payload,
    )


def pose_prefilter_score(candidate: YouTubeCandidate) -> float:
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    pose_payload = payload.get("posePrefilter") if isinstance(payload, dict) else None
    if not isinstance(pose_payload, dict):
        return 0.0
    if not bool(pose_payload.get("passed")):
        return 0.0
    if pose_prefilter_has_hard_reject_issue(pose_payload):
        return 0.0
    value = pose_payload.get("score")
    return clamp_score(float(value)) if isinstance(value, (int, float)) else 0.0


def candidate_pose_prefilter_passed(candidate: YouTubeCandidate) -> bool:
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    pose_payload = payload.get("posePrefilter") if isinstance(payload, dict) else None
    return isinstance(pose_payload, dict) and bool(pose_payload.get("passed"))


def candidate_is_eligible_for_vision_review(candidate: YouTubeCandidate, settings: YouTubeRankingSettings) -> bool:
    if candidate.status == "rejected":
        return False
    if settings.pose_prefilter_enabled:
        return candidate_pose_prefilter_passed(candidate)
    return True


def rank_candidate_with_yolo_pose(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> PoseRankResult:
    del exercise
    temp_dir = tempfile.TemporaryDirectory(prefix="exercise-motion-yolo-pose-")
    try:
        video_path = download_youtube_preview(
            candidate.url,
            Path(temp_dir.name),
            settings.youtube_cookies,
            cache_dir=settings.youtube_preview_cache_dir,
        )
        result = run_yolo_pose_prefilter(
            video_path=video_path,
            settings=PosePrefilterSettings(
                model=settings.pose_prefilter_model,
                sample_fps=settings.pose_prefilter_sample_fps,
                max_seconds=settings.pose_prefilter_max_seconds,
                scan_strategy=settings.pose_prefilter_scan_strategy,
                window_seconds=settings.pose_prefilter_window_seconds,
                overlap_seconds=settings.pose_prefilter_overlap_seconds,
                min_score=settings.pose_prefilter_min_score,
                min_keypoint_confidence=settings.pose_prefilter_min_keypoint_confidence,
                min_body_scale=settings.pose_prefilter_min_body_scale,
                max_candidates=settings.resolved_pose_prefilter_candidates_per_exercise(),
            ),
        )
        return result.score, result.reasons, result.payload
    finally:
        temp_dir.cleanup()


def vision_backend_name(settings: YouTubeRankingSettings) -> str:
    if settings.llama_cpp_command:
        return "llama-cpp-cli"
    return "llama-cpp-server"


def default_llama_cpp_mmproj_path() -> str:
    return DEFAULT_LLAMA_CPP_MMPROJ


def default_llama_cpp_server_path() -> str:
    return "C:\\Users\\gabri\\Downloads\\llama-b9555-bin-win-cuda-13.3-x64\\llama-server.exe"


def resolve_llama_cpp_server_command(
    *,
    configured_command: str | None,
    primary_command: str | None,
) -> str:
    if configured_command:
        return configured_command
    if primary_command:
        inferred = Path(primary_command).with_name("llama-server.exe")
        if inferred.exists():
            return str(inferred)
    fallback = Path(default_llama_cpp_server_path())
    if fallback.exists():
        return str(fallback)
    found = shutil.which("llama-server")
    return found or "llama-server"


def parse_llama_cpp_base_url(base_url: str | None) -> dict[str, object]:
    if not base_url:
        raise ValueError("llama.cpp server mode requires a base URL.")
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8090
    return {"host": host, "port": port}


def llama_cpp_model_basename(model_id: str) -> str:
    return re.split(r"[\\/]", str(model_id).strip())[-1].casefold()


def extract_llama_cpp_server_model_ids(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    model_ids: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("model")
        if isinstance(model_id, str) and model_id.strip():
            model_ids.append(model_id.strip())
    return model_ids


def llama_cpp_server_models_match_expected(payload: dict[str, Any], expected_model: str) -> bool:
    expected_name = llama_cpp_model_basename(expected_model)
    if not expected_name:
        return False
    for model_id in extract_llama_cpp_server_model_ids(payload):
        model_name = llama_cpp_model_basename(model_id)
        if model_name == expected_name:
            return True
    return False


def discover_and_rank_youtube_candidates(
    *,
    workout_plan_json: Path,
    out_json: Path,
    settings: YouTubeRankingSettings,
    search_fn: SearchFn = search_youtube,
    query_planner: QueryPlannerFn | None = None,
    semantic_gate: SemanticGateFn | None = None,
    pose_ranker: PoseRankerFn | None = None,
    vision_ranker: VisionRankerFn | None = None,
) -> dict[str, Any]:
    run_started = time.monotonic()
    search_elapsed_total = 0.0
    metadata_elapsed_total = 0.0
    semantic_gate_elapsed_total = 0.0
    pose_elapsed_total = 0.0
    vision_elapsed_total = 0.0
    exercises = load_workout_plan_exercises(workout_plan_json, include_disabled=settings.include_disabled)
    metadata_candidate_pool_size = settings.resolved_metadata_candidate_pool_size()
    owns_query_planner = False
    query_planner_backend: str | None = None
    if settings.use_llama_cpp_query_planner and query_planner is None:
        query_planner = LlamaCppYouTubeQueryPlanner(settings)
        owns_query_planner = True
        query_planner_backend = "llama-cpp"
    elif settings.use_deepseek_query_planner and query_planner is None:
        query_planner = DeepSeekYouTubeQueryPlanner(settings)
        owns_query_planner = True
        query_planner_backend = "deepseek"
    elif query_planner is not None:
        query_planner_backend = "custom"
    vision_enabled = settings.rank_with_vision
    owns_vision_ranker = False
    if vision_enabled and vision_ranker is None:
        vision_ranker = LlamaCppVisionRanker(settings)
        owns_vision_ranker = True
    owns_semantic_gate = False
    semantic_gate_ranker: LlamaCppSemanticGate | None = None
    if settings.semantic_gate_enabled and semantic_gate is None:
        if isinstance(vision_ranker, LlamaCppVisionRanker):
            semantic_gate_ranker = LlamaCppSemanticGate(settings, shared_ranker=vision_ranker)
        else:
            semantic_gate_ranker = LlamaCppSemanticGate(settings)
            owns_semantic_gate = True
        semantic_gate = semantic_gate_ranker

    exercise_payloads: list[dict[str, Any]] = []
    try:
        for exercise in exercises:
            queries = build_youtube_queries(exercise.name)
            query_planning_payload: dict[str, Any] = {
                "enabled": query_planner is not None,
                "backend": query_planner_backend,
                "status": "skipped" if query_planner is None else "pending",
                "addedQueries": [],
            }
            if query_planner is not None:
                try:
                    planned_queries = query_planner(exercise, queries, settings)
                    added_queries = [
                        query
                        for query in merge_youtube_queries(planned_queries, limit=settings.deepseek_max_queries)
                        if query.casefold() not in {existing.casefold() for existing in queries}
                    ]
                    queries = merge_youtube_queries([*queries, *added_queries])
                    query_planning_payload.update(
                        {
                            "status": "completed",
                            "addedQueries": added_queries,
                        }
                    )
                except Exception as exc:
                    query_planning_payload.update(
                        {
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
            by_key: dict[str, YouTubeCandidate] = {}
            search_errors: list[dict[str, str]] = []
            search_attempts: list[dict[str, Any]] = []
            for query in queries:
                search_started = time.monotonic()
                try:
                    search_results, attempts = search_youtube_with_empty_retries(
                        query,
                        settings=settings,
                        search_fn=search_fn,
                    )
                    search_elapsed_total += time.monotonic() - search_started
                    search_attempts.append(
                        {
                            "query": query,
                            "attempts": attempts,
                            "resultCount": len(search_results),
                        }
                    )
                except Exception as exc:
                    search_elapsed_total += time.monotonic() - search_started
                    search_errors.append({"query": query, "error": str(exc)})
                    continue
                for candidate in search_results:
                    if not candidate.url:
                        continue
                    key = candidate.key()
                    if key not in by_key:
                        by_key[key] = candidate

            metadata_started = time.monotonic()
            ranked = [
                score_candidate_metadata(
                    exercise,
                    candidate,
                    min_duration_seconds=settings.min_duration_seconds,
                    max_duration_seconds=settings.max_duration_seconds,
                )
                for candidate in by_key.values()
            ]
            metadata_elapsed_total += time.monotonic() - metadata_started

            if settings.semantic_gate_enabled:
                semantic_gate_started = time.monotonic()
                ranked = rank_candidates_with_semantic_gate(
                    exercise=exercise,
                    ranked=ranked,
                    settings=settings,
                    semantic_gate=semantic_gate,
                )
                semantic_gate_elapsed_total += time.monotonic() - semantic_gate_started

            if settings.pose_prefilter_enabled:
                pose_started = time.monotonic()
                ranked = rank_candidates_with_pose_prefilter(
                    exercise=exercise,
                    ranked=ranked,
                    settings=settings,
                    pose_ranker=pose_ranker,
                )
                pose_elapsed_total += time.monotonic() - pose_started

            if vision_enabled and vision_ranker is not None:
                vision_started = time.monotonic()
                vision_candidates = [
                    candidate
                    for candidate in ranked
                    if candidate_is_eligible_for_vision_review(candidate, settings)
                ]
                if isinstance(vision_ranker, LlamaCppVisionRanker):
                    reranked = rank_candidates_with_prepared_vision_reviews(
                        exercise=exercise,
                        ranked=vision_candidates,
                        settings=settings,
                        vision_ranker=vision_ranker,
                    )
                else:
                    reranked = rank_candidates_with_vision_ranker(
                        exercise=exercise,
                        ranked=vision_candidates,
                        settings=settings,
                        vision_ranker=vision_ranker,
                    )
                reranked_by_key = {candidate.key(): candidate for candidate in reranked}
                ranked = [reranked_by_key.get(candidate.key(), candidate) for candidate in ranked]
                vision_elapsed_total += time.monotonic() - vision_started
                ranked.sort(key=lambda item: (item.vision_score is not None, item.final_score), reverse=True)
            else:
                ranked.sort(key=lambda item: item.final_score, reverse=True)

            ranked = ranked[: settings.max_candidates]

            exercise_payloads.append(
                {
                    "exerciseId": exercise.exercise_id,
                    "exerciseName": exercise.name,
                    "slug": exercise.slug,
                    "queries": queries,
                    "queryPlanning": query_planning_payload,
                    "searchErrors": search_errors,
                    "searchAttempts": search_attempts,
                    "candidates": [candidate.to_manifest_dict() for candidate in ranked],
                }
            )
    finally:
        if owns_query_planner and isinstance(query_planner, (DeepSeekYouTubeQueryPlanner, LlamaCppYouTubeQueryPlanner)):
            query_planner.close()
        if owns_semantic_gate and semantic_gate_ranker is not None:
            semantic_gate_ranker.close()
        if owns_vision_ranker and isinstance(vision_ranker, LlamaCppVisionRanker):
            vision_ranker.close()

    write_started = time.monotonic()
    timing_payload = {
        "searchElapsedSeconds": round_elapsed(search_elapsed_total),
        "metadataRankingElapsedSeconds": round_elapsed(metadata_elapsed_total),
        "semanticGateElapsedSeconds": round_elapsed(semantic_gate_elapsed_total),
        "posePrefilterElapsedSeconds": round_elapsed(pose_elapsed_total),
        "visionScoringElapsedSeconds": round_elapsed(vision_elapsed_total),
    }
    timing_payload["visionPreparationElapsedSeconds"] = round_elapsed(
        sum_candidate_vision_payload_number(exercise_payloads, "previewPreparationElapsedSeconds")
    )
    manifest = {
        "sourcePlanPath": str(workout_plan_json),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "ranking": {
            "metadataEnabled": True,
            "maxCandidates": settings.max_candidates,
            "metadataCandidatePoolSize": metadata_candidate_pool_size,
            "queryPlanningEnabled": settings.use_llama_cpp_query_planner or settings.use_deepseek_query_planner,
            "queryPlannerBackend": query_planner_backend,
            "youtubePreviewCacheDir": (
                str(settings.youtube_preview_cache_dir)
                if settings.youtube_preview_cache_dir is not None
                else None
            ),
            "visionEnabled": vision_enabled,
            "visionBackend": vision_backend_name(settings) if vision_enabled else None,
            "visionCandidatesPerExercise": settings.vision_candidates_per_exercise if vision_enabled else None,
            "semanticGateEnabled": settings.semantic_gate_enabled,
            "semanticGateBackend": "llama-cpp" if settings.semantic_gate_enabled else None,
            "semanticGateModel": settings.llama_cpp_model if settings.semantic_gate_enabled else None,
            "semanticGateCandidatesPerExercise": (
                settings.resolved_semantic_gate_candidates_per_exercise()
                if settings.semantic_gate_enabled
                else None
            ),
            "semanticGateMinScore": settings.semantic_gate_min_score if settings.semantic_gate_enabled else None,
            "posePrefilterEnabled": settings.pose_prefilter_enabled,
            "posePrefilterBackend": "yolo-pose" if settings.pose_prefilter_enabled else None,
            "posePrefilterModel": settings.pose_prefilter_model if settings.pose_prefilter_enabled else None,
            "posePrefilterScanStrategy": (
                settings.pose_prefilter_scan_strategy
                if settings.pose_prefilter_enabled
                else None
            ),
            "posePrefilterCandidatesPerExercise": (
                settings.resolved_pose_prefilter_candidates_per_exercise()
                if settings.pose_prefilter_enabled
                else None
            ),
            "timing": timing_payload,
        },
        "exercises": exercise_payloads,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["ranking"]["timing"]["writeManifestElapsedSeconds"] = round_elapsed(time.monotonic() - write_started)
    manifest["ranking"]["timing"]["totalElapsedSeconds"] = round_elapsed(time.monotonic() - run_started)
    out_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def search_youtube_with_empty_retries(
    query: str,
    *,
    settings: YouTubeRankingSettings,
    search_fn: SearchFn,
) -> tuple[list[YouTubeCandidate], int]:
    max_attempts = max(1, settings.youtube_search_empty_retries + 1)
    last_results: list[YouTubeCandidate] = []
    for attempt in range(1, max_attempts + 1):
        last_results = search_fn(query, settings.results_per_query)
        if last_results or attempt >= max_attempts:
            return last_results, attempt
        time.sleep(min(0.25 * attempt, 1.0))
    return last_results, max_attempts


class LlamaCppVisionRanker:
    def __init__(self, settings: YouTubeRankingSettings) -> None:
        from exercise_motion_pkg.segment_detection import LlamaCppVisionClient

        if settings.llama_cpp_command and not settings.llama_cpp_mmproj:
            raise ValueError("llama.cpp command mode requires --llama-cpp-mmproj.")
        self.settings = settings
        self.process: subprocess.Popen[str] | None = None
        if settings.llama_cpp_command is None and settings.llama_cpp_base_url is not None:
            self._ensure_server()
        self.client = LlamaCppVisionClient(
            base_url=None if settings.llama_cpp_command else settings.llama_cpp_base_url,
            model=settings.llama_cpp_model,
            command=settings.llama_cpp_command,
            mmproj=settings.llama_cpp_mmproj,
            backend=settings.llama_cpp_backend,
            n_predict=settings.llama_cpp_n_predict,
            temperature=settings.llama_cpp_temperature,
            top_p=settings.llama_cpp_top_p,
            top_k=settings.llama_cpp_top_k,
            disable_reasoning=settings.llama_cpp_disable_reasoning,
            image_min_tokens=settings.llama_cpp_image_min_tokens,
            image_max_tokens=settings.llama_cpp_image_max_tokens,
            request_timeout_seconds=settings.llama_cpp_request_timeout_seconds,
        )

    def close(self) -> None:
        self.client.client.close()
        if self.process is None or self.settings.keep_llama_cpp_server:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10.0)

    def _ensure_server(self) -> None:
        server_payload = self._server_models_payload()
        if server_payload is not None:
            self._raise_if_server_model_mismatch(server_payload)
            return
        if not self.settings.llama_cpp_auto_start_server:
            response = httpx.get(f"{self.settings.llama_cpp_base_url.rstrip('/')}/v1/models", timeout=5.0)
            response.raise_for_status()
            self._raise_if_server_model_mismatch(response.json())
            return
        command = resolve_llama_cpp_server_command(
            configured_command=self.settings.llama_cpp_server_command,
            primary_command=self.settings.llama_cpp_command,
        )
        model_path = Path(self.settings.llama_cpp_model)
        mmproj_path = Path(self.settings.llama_cpp_mmproj or default_llama_cpp_mmproj_path())
        if not model_path.exists():
            raise FileNotFoundError(f"Could not find llama.cpp model file: {model_path}")
        if not mmproj_path.exists():
            raise FileNotFoundError(f"Could not find llama.cpp mmproj file: {mmproj_path}")
        if shutil.which(command) is None and not Path(command).exists():
            raise FileNotFoundError(f"Could not find llama-server binary: {command}")
        parsed = parse_llama_cpp_base_url(self.settings.llama_cpp_base_url)
        args = [
            command,
            "-m",
            str(model_path),
            "--mmproj",
            str(mmproj_path),
            "--host",
            parsed["host"],
            "--port",
            str(parsed["port"]),
            "--parallel",
            str(max(1, self.settings.llama_cpp_parallel or self.settings.vision_llm_workers)),
        ]
        if self.settings.llama_cpp_ctx_size is not None:
            args.extend(["--ctx-size", str(max(1, self.settings.llama_cpp_ctx_size))])
        if self.settings.llama_cpp_batch_size is not None:
            args.extend(["--batch-size", str(max(1, self.settings.llama_cpp_batch_size))])
        if self.settings.llama_cpp_ubatch_size is not None:
            args.extend(["--ubatch-size", str(max(1, self.settings.llama_cpp_ubatch_size))])
        if self.settings.llama_cpp_flash_attn is not None:
            args.extend(["--flash-attn", self.settings.llama_cpp_flash_attn])
        if self.settings.llama_cpp_cache_type_k is not None:
            args.extend(["--cache-type-k", self.settings.llama_cpp_cache_type_k])
        if self.settings.llama_cpp_cache_type_v is not None:
            args.extend(["--cache-type-v", self.settings.llama_cpp_cache_type_v])
        if self.settings.llama_cpp_disable_reasoning:
            args.extend(["--reasoning", "off", "--reasoning-format", "none", "--reasoning-budget", "0"])
        if self.settings.llama_cpp_threads_http is not None:
            args.extend(["--threads-http", str(max(1, self.settings.llama_cpp_threads_http))])
        if self.settings.llama_cpp_cache_reuse is not None:
            args.extend(["--cache-reuse", str(max(0, self.settings.llama_cpp_cache_reuse))])
        if self.settings.llama_cpp_fit is not None:
            args.extend(["--fit", self.settings.llama_cpp_fit])
        if self.settings.llama_cpp_fit_ctx is not None:
            args.extend(["--fit-ctx", str(max(1, self.settings.llama_cpp_fit_ctx))])
        if self.settings.llama_cpp_fit_target is not None:
            args.extend(["--fit-target", str(max(0, self.settings.llama_cpp_fit_target))])
        if not self.settings.llama_cpp_mmap:
            args.append("--no-mmap")
        if self.settings.llama_cpp_mlock:
            args.append("--mlock")
        args.append("--mmproj-offload" if self.settings.llama_cpp_mmproj_offload else "--no-mmproj-offload")
        args.append("--cont-batching" if self.settings.llama_cpp_cont_batching else "--no-cont-batching")
        if self.settings.llama_cpp_backend == "gpu":
            args.extend(["--gpu-layers", "all"])
        else:
            args.extend(["--gpu-layers", "0"])
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=creationflags,
        )
        deadline = time.monotonic() + self.settings.llama_cpp_server_startup_timeout_seconds
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            if self._is_healthy():
                return
            time.sleep(1.0)
        raise RuntimeError(
            f"llama-server did not become healthy at {self.settings.llama_cpp_base_url} "
            f"within {self.settings.llama_cpp_server_startup_timeout_seconds:.0f} seconds."
        )

    def _is_healthy(self) -> bool:
        if self.settings.llama_cpp_base_url is None:
            return False
        try:
            response = httpx.get(f"{self.settings.llama_cpp_base_url.rstrip('/')}/v1/models", timeout=5.0)
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    def _server_models_payload(self) -> dict[str, Any] | None:
        if self.settings.llama_cpp_base_url is None:
            return None
        try:
            response = httpx.get(f"{self.settings.llama_cpp_base_url.rstrip('/')}/v1/models", timeout=5.0)
            if response.status_code >= 500:
                return None
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _raise_if_server_model_mismatch(self, payload: dict[str, Any]) -> None:
        if llama_cpp_server_models_match_expected(payload, self.settings.llama_cpp_model):
            return
        served_models = extract_llama_cpp_server_model_ids(payload)
        served = ", ".join(served_models) if served_models else "unknown model"
        expected = Path(self.settings.llama_cpp_model).name
        raise RuntimeError(
            f"Existing llama.cpp server at {self.settings.llama_cpp_base_url} is serving {served}, "
            f"but this run expects {expected}. Stop the existing server or use a different --llama-cpp-base-url."
        )

    def rank_prepared(
        self,
        prepared: PreparedVisionReview,
        settings: YouTubeRankingSettings,
    ) -> VisionRankResult:
        return score_prepared_vision_review(
            prepared=prepared,
            settings=settings,
            caption_images=self.client.caption_images,
        )


class LlamaCppSemanticGate:
    def __init__(
        self,
        settings: YouTubeRankingSettings,
        *,
        shared_ranker: LlamaCppVisionRanker | None = None,
    ) -> None:
        self.settings = settings
        self._shared_ranker = shared_ranker
        self._owned_ranker = None if shared_ranker is not None else LlamaCppVisionRanker(settings)

    @property
    def _ranker(self) -> LlamaCppVisionRanker:
        ranker = self._shared_ranker or self._owned_ranker
        if ranker is None:
            raise RuntimeError("llama.cpp semantic gate is not initialized.")
        return ranker

    def __call__(
        self,
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> SemanticGateResult:
        from exercise_motion_pkg.segment_detection import extract_json_object

        prompt = build_candidate_semantic_gate_prompt(exercise, candidate)
        raw = self._ranker.client.caption_images(frame_paths=[], prompt=prompt)
        payload = extract_json_object(raw)
        if not isinstance(payload, dict):
            raise RuntimeError("llama.cpp semantic gate returned no JSON object.")
        score = coerce_float(payload.get("score"))
        if score is None:
            score = coerce_float(payload.get("targetExerciseMatch"))
        if score is None:
            score = 0.0
        wrong_exercise = bool(payload.get("wrongExercise"))
        passed = score >= settings.semantic_gate_min_score and not wrong_exercise
        reasons = ["semantic_text_match" if passed else "semantic_text_mismatch"]
        conflict_reasons = semantic_gate_text_conflict_reasons(exercise, candidate)
        if conflict_reasons:
            passed = False
            score = min(score, 0.20)
            reasons.extend(conflict_reasons)
        if wrong_exercise:
            reasons.append("semantic_wrong_exercise")
        if bool(payload.get("wrongEquipment")):
            reasons.append("semantic_wrong_equipment")
        return clamp_score(score), reasons, {
            "enabled": True,
            "backend": "llama-cpp",
            "model": settings.llama_cpp_model,
            "passed": passed,
            "score": clamp_score(score),
            "wrongExercise": wrong_exercise,
            "wrongEquipment": bool(payload.get("wrongEquipment")),
            "textConflictReasons": conflict_reasons,
            "unrequestedVariantTerms": semantic_payload_unrequested_variant_terms(payload),
            "matchedExercise": truncate_text(str(payload.get("matchedExercise") or ""), 120),
            "reason": truncate_text(str(payload.get("reason") or ""), 240),
        }

    def close(self) -> None:
        if self._owned_ranker is not None:
            self._owned_ranker.close()


def rank_candidates_with_vision_ranker(
    *,
    exercise: ExerciseEntry,
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
    vision_ranker: VisionRankerFn,
) -> list[YouTubeCandidate]:
    reranked: list[YouTubeCandidate] = []
    vision_limit = max(0, settings.vision_candidates_per_exercise)
    for index, candidate in enumerate(ranked):
        if index < vision_limit:
            vision_score, vision_reasons, vision_payload = normalize_vision_result(
                vision_ranker(exercise, candidate, settings)
            )
            reviewed = apply_vision_score(candidate, vision_score, vision_reasons, vision_payload, settings=settings)
            reranked.append(reviewed)
            if candidate_passes_vision_hard_gates(reviewed, settings):
                reranked.extend(ranked[index + 1 :])
                break
        else:
            reranked.append(candidate)
    return reranked


def rank_candidates_with_prepared_vision_reviews(
    *,
    exercise: ExerciseEntry,
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
    vision_ranker: Any,
) -> list[YouTubeCandidate]:
    vision_limit = max(0, settings.vision_candidates_per_exercise)
    reranked: list[YouTubeCandidate] = []
    if settings.vision_llm_workers > 1:
        candidates_to_review = ranked[:vision_limit]
        prepared_by_key = prepare_vision_reviews_parallel(
            exercise=exercise,
            candidates=candidates_to_review,
            settings=settings,
        )
        try:
            vision_results_by_key = score_prepared_vision_reviews_parallel(
                prepared_reviews=list(prepared_by_key.values()),
                settings=settings,
                vision_ranker=vision_ranker,
            )
            for index, candidate in enumerate(ranked):
                if index < vision_limit:
                    vision_result = vision_results_by_key.get(candidate.key())
                    if vision_result is None:
                        reviewed = apply_vision_score(candidate, 0.0, ["vision_review_failed"], settings=settings)
                    else:
                        vision_score, vision_reasons, vision_payload = normalize_vision_result(vision_result)
                        reviewed = apply_vision_score(candidate, vision_score, vision_reasons, vision_payload, settings=settings)
                    reranked.append(reviewed)
                else:
                    reranked.append(candidate)
            return reranked
        finally:
            for prepared in prepared_by_key.values():
                prepared.close()

    index = 0
    batch_size = max(1, settings.vision_download_workers)
    while index < len(ranked):
        if index >= vision_limit:
            reranked.extend(ranked[index:])
            break
        batch_end = min(len(ranked), vision_limit, index + batch_size)
        prepared_by_key = prepare_vision_reviews_parallel(
            exercise=exercise,
            candidates=ranked[index:batch_end],
            settings=settings,
        )
        try:
            while index < batch_end:
                candidate = ranked[index]
                prepared = prepared_by_key.get(candidate.key())
                if prepared is None:
                    reviewed = apply_vision_score(candidate, 0.0, ["vision_review_failed"], settings=settings)
                else:
                    vision_score, vision_reasons, vision_payload = normalize_vision_result(
                        vision_ranker.rank_prepared(prepared, settings)
                    )
                    reviewed = apply_vision_score(candidate, vision_score, vision_reasons, vision_payload, settings=settings)
                reranked.append(reviewed)
                if candidate_passes_vision_hard_gates(reviewed, settings):
                    reranked.extend(ranked[index + 1 :])
                    return reranked
                index += 1
        finally:
            for prepared in prepared_by_key.values():
                prepared.close()
    return reranked


def score_prepared_vision_reviews_parallel(
    *,
    prepared_reviews: list[PreparedVisionReview],
    settings: YouTubeRankingSettings,
    vision_ranker: Any,
) -> dict[str, VisionRankResult]:
    if not prepared_reviews:
        return {}
    workers = max(1, min(settings.vision_llm_workers, len(prepared_reviews)))
    results: dict[str, VisionRankResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(vision_ranker.rank_prepared, prepared, settings): prepared
            for prepared in prepared_reviews
        }
        for future in as_completed(futures):
            prepared = futures[future]
            try:
                results[prepared.candidate.key()] = future.result()
            except Exception:
                results[prepared.candidate.key()] = (0.0, ["vision_review_failed"])
    return results


def apply_vision_score(
    candidate: YouTubeCandidate,
    vision_score: float,
    vision_reasons: list[str],
    vision_payload: dict[str, Any] | None = None,
    *,
    settings: YouTubeRankingSettings | None = None,
) -> YouTubeCandidate:
    hard_reject = candidate_has_pose_prefilter_hard_reject(candidate)
    effective_vision_score = clamp_score(vision_score)
    effective_vision_reasons = list(vision_reasons)
    effective_vision_payload = dict(vision_payload) if isinstance(vision_payload, dict) else {}
    if semantic_pose_short_demo_fallback_applies(candidate, settings=settings):
        duration_seconds = float(candidate.duration_seconds or 0.0)
        advisory_vlm_payload = dict(effective_vision_payload)
        effective_vision_score = max(effective_vision_score, 0.86)
        effective_vision_reasons = dedupe_reasons(
            [
                "vlm_source_review_advisory",
                "semantic_pose_short_demo_source_fallback",
                "source_score",
            ]
        )
        effective_vision_payload = {
            "advisoryVlmSourceReview": advisory_vlm_payload,
        }
        effective_vision_payload.update(
            {
                "deterministicSourceFallback": {
                    "type": "semantic_pose_short_demo",
                    "score": 0.86,
                    "reason": (
                        "Short exact-match source demo passed semantic gate and YOLO source integrity; "
                        "VLM source review was treated as advisory."
                    ),
                },
                "bestChunkStartSeconds": 0.0,
                "bestChunkEndSeconds": min(duration_seconds, 20.0),
                "bestChunkScore": max(coerce_float(effective_vision_payload.get("bestChunkScore")) or 0.0, 0.86),
                "validChunkCount": max(as_optional_int(effective_vision_payload.get("validChunkCount")) or 0, 1),
                "validChunkRatio": max(coerce_float(effective_vision_payload.get("validChunkRatio")) or 0.0, 1.0),
                "scoredChunkCount": max(as_optional_int(effective_vision_payload.get("scoredChunkCount")) or 0, 1),
                "chunkEvidenceCapApplied": False,
            }
        )
    score_reasons = dedupe_reasons(candidate.score_reasons + effective_vision_reasons)
    if hard_reject:
        score_reasons = dedupe_reasons([*score_reasons, *candidate_pose_prefilter_hard_reject_reasons(candidate)])
    final_score = 0.0 if hard_reject else compose_final_score(candidate.metadata_score, effective_vision_score)
    final_score, cap_reasons = apply_source_quality_caps(final_score, score_reasons)
    score_reasons = dedupe_reasons(score_reasons + cap_reasons)
    merged_payload = dict(candidate.vision_payload) if isinstance(candidate.vision_payload, dict) else {}
    if effective_vision_payload:
        merged_payload.update(effective_vision_payload)
    return replace_candidate(
        candidate,
        vision_score=effective_vision_score,
        final_score=final_score,
        status=status_for_score(final_score),
        score_reasons=score_reasons,
        vision_payload=merged_payload or None,
    )


def semantic_pose_short_demo_fallback_applies(
    candidate: YouTubeCandidate,
    *,
    settings: YouTubeRankingSettings | None,
) -> bool:
    if settings is None:
        return False
    duration_seconds = candidate.duration_seconds
    if duration_seconds is None:
        return False
    if duration_seconds < settings.min_duration_seconds or duration_seconds > 30:
        return False
    if "exercise_name_match" not in candidate.score_reasons:
        return False
    if has_source_quality_demoter(candidate.score_reasons):
        return False
    semantic_payload = candidate_semantic_gate_payload(candidate)
    if not semantic_payload or not bool(semantic_payload.get("passed")):
        return False
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    pose_payload = payload.get("posePrefilter") if isinstance(payload, dict) else None
    if not isinstance(pose_payload, dict):
        return False
    if not bool(pose_payload.get("passed")) or pose_prefilter_has_hard_reject_issue(pose_payload):
        return False
    pose_score = coerce_float(pose_payload.get("score")) or 0.0
    if pose_score < max(0.85, settings.pose_prefilter_min_score):
        return False
    integrity = pose_payload.get("sourceWindowIntegrity")
    if isinstance(integrity, dict) and not bool(integrity.get("passed")):
        return False
    single_person_ratio = coerce_float(pose_payload.get("singlePersonRatio"))
    if single_person_ratio is not None and single_person_ratio < 0.95:
        return False
    keypoint_coverage = coerce_float(pose_payload.get("keypointCoverage"))
    if keypoint_coverage is not None and keypoint_coverage < 0.85:
        return False
    active_chain_visibility = coerce_float(pose_payload.get("activeChainVisibility"))
    if active_chain_visibility is not None and active_chain_visibility < 0.80:
        return False
    return True


def prepare_vision_reviews_parallel(
    *,
    exercise: ExerciseEntry,
    candidates: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
) -> dict[str, PreparedVisionReview]:
    if not candidates:
        return {}
    workers = max(1, min(settings.vision_download_workers, len(candidates)))
    prepared_by_key: dict[str, PreparedVisionReview] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(prepare_vision_review, exercise, candidate, settings): candidate
            for candidate in candidates
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                prepared_by_key[candidate.key()] = future.result()
            except Exception:
                continue
    return prepared_by_key


def prepare_vision_review(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> PreparedVisionReview:
    from exercise_motion_pkg.segment_detection import (
        DetectionSettings,
        VideoMetadata,
        detect_motion_candidate_intervals,
        iter_detection_windows,
        iter_detection_windows_for_intervals,
    )
    from exercise_motion_pkg.video_utils import read_basic_video_metadata

    preparation_started = time.monotonic()
    temp_dir = tempfile.TemporaryDirectory(prefix="exercise-motion-youtube-")
    temp_path = Path(temp_dir.name)
    try:
        download_started = time.monotonic()
        video_path = download_youtube_preview(
            candidate.url,
            temp_path,
            settings.youtube_cookies,
            cache_dir=settings.youtube_preview_cache_dir,
        )
        preview_download_elapsed = time.monotonic() - download_started
        metadata = read_basic_video_metadata(video_path)
        duration = max(0.5, metadata.duration_seconds)
        chunk_estimate = estimate_chunking(
            exercise_name=exercise.name,
            use_llm=False,
        )
        chunk_seconds = settings.vision_chunk_seconds or chunk_estimate.chunk_seconds
        chunk_overlap_seconds = (
            settings.vision_chunk_overlap_seconds
            if settings.vision_chunk_overlap_seconds is not None
            else chunk_estimate.chunk_overlap_seconds
        )
        window_seconds = min(max(1.0, chunk_seconds), duration)
        overlap_seconds = max(0.0, chunk_overlap_seconds)
        motion_started = time.monotonic()
        scan_duration = min(duration, max(window_seconds, settings.vision_motion_scan_max_seconds))
        motion_intervals = detect_motion_candidate_intervals(
            video_path=video_path,
            metadata=VideoMetadata(
                duration_seconds=scan_duration,
                fps=metadata.fps,
                frame_count=metadata.frame_count,
                width=metadata.width,
                height=metadata.height,
            ),
            settings=DetectionSettings(
                window_seconds=window_seconds,
                overlap_seconds=overlap_seconds,
                frames_per_window=max(1, settings.vision_frames_per_candidate or frames_for_chunk_seconds(chunk_seconds)),
                max_frame_width=320,
                max_motion_candidates=max(1, settings.vision_max_chunks_per_candidate or 5),
                motion_sample_fps=settings.vision_motion_scan_sample_fps,
            ),
        )
        motion_scan_elapsed = time.monotonic() - motion_started
        planning_started = time.monotonic()
        if motion_intervals and not (
            len(motion_intervals) == 1
            and round(motion_intervals[0].start_seconds, 3) == 0.0
            and round(motion_intervals[0].end_seconds, 3) >= round(duration, 3)
        ):
            windows = iter_detection_windows_for_intervals(
                intervals=motion_intervals,
                duration_seconds=duration,
                window_seconds=window_seconds,
                overlap_seconds=overlap_seconds,
            )
            review_windows = [
                PreparedReviewWindow(
                    index=index,
                    start_seconds=window.start_seconds,
                    end_seconds=window.end_seconds,
                    source="motion_interval",
                )
                for index, window in enumerate(windows)
            ]
            review_windows = add_coverage_review_window(
                review_windows,
                duration_seconds=duration,
                window_seconds=window_seconds,
            )
        else:
            windows = iter_detection_windows(
                duration_seconds=duration,
                window_seconds=window_seconds,
                overlap_seconds=overlap_seconds,
            )
            review_windows = [
                PreparedReviewWindow(
                    index=index,
                    start_seconds=window.start_seconds,
                    end_seconds=window.end_seconds,
                    source="fallback_even",
                )
                for index, window in enumerate(windows)
            ]
        review_windows = select_review_windows_by_budget(review_windows, settings.vision_max_chunks_per_candidate)
        window_planning_elapsed = time.monotonic() - planning_started
        frames_per_chunk = max(1, settings.vision_frames_per_candidate or frames_for_chunk_seconds(chunk_seconds))
        return PreparedVisionReview(
            candidate=candidate,
            temp_dir=temp_dir,
            frame_paths=[],
            frame_path_chunks=[],
            chunk_windows=[(window.start_seconds, window.end_seconds) for window in review_windows],
            chunk_count=len(review_windows),
            prompt=build_candidate_vision_prompt(exercise.name, candidate),
            video_path=video_path,
            review_windows=review_windows,
            frames_per_chunk=frames_per_chunk,
            preview_preparation_elapsed_seconds=time.monotonic() - preparation_started,
            preview_download_elapsed_seconds=preview_download_elapsed,
            motion_scan_elapsed_seconds=motion_scan_elapsed,
            window_planning_elapsed_seconds=window_planning_elapsed,
        )
    except Exception:
        temp_dir.cleanup()
        raise


def rank_candidate_with_llama_cpp(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> VisionRankResult:
    ranker = LlamaCppVisionRanker(settings)
    try:
        return rank_candidate_with_vision_client(
            exercise=exercise,
            candidate=candidate,
            settings=settings,
            caption_images=ranker.client.caption_images,
        )
    finally:
        ranker.close()


def rank_candidate_with_vision_client(
    *,
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
    caption_images: Callable[..., str],
) -> VisionRankResult:
    try:
        prepared = prepare_vision_review(exercise, candidate, settings)
        try:
            return score_prepared_vision_review(
                prepared=prepared,
                settings=settings,
                caption_images=caption_images,
            )
        finally:
            prepared.close()
    except Exception:
        return 0.0, ["vision_review_failed"]


def score_prepared_vision_review(
    *,
    prepared: PreparedVisionReview,
    settings: YouTubeRankingSettings,
    caption_images: Callable[..., str],
) -> VisionRankResult:
    from exercise_motion_pkg.segment_detection import extract_json_object

    review_started = time.monotonic()
    chunk_scores: list[float] = []
    chunk_results: list[tuple[float, list[str], dict[str, Any], int]] = []
    reviewed_chunks: list[dict[str, Any]] = []
    invalid_json_count = 0
    failed_count = 0
    render_elapsed_total = 0.0
    vlm_elapsed_total = 0.0
    chunk_indexes = planned_adaptive_chunk_indexes(prepared, settings)
    early_stop_reason: str | None = None
    for review_order, chunk_index in enumerate(chunk_indexes):
        chunk_paths, render_elapsed = get_prepared_chunk_paths(prepared, chunk_index, settings)
        render_elapsed_total += render_elapsed
        if not chunk_paths:
            continue
        chunk_start, chunk_end = (
            prepared.chunk_windows[chunk_index]
            if chunk_index < len(prepared.chunk_windows)
            else (0.0, 0.0)
        )
        window_source = (
            prepared.review_windows[chunk_index].source
            if chunk_index < len(prepared.review_windows)
            else "pre_rendered"
        )
        chunk_prompt = (
            f"{prepared.prompt}\n"
            f"These contact-sheet images are from chunk {chunk_index + 1} of {prepared.chunk_count} "
            f"covering {chunk_start:.3f}s to {chunk_end:.3f}s in the preview video. "
            "Treat multiple attached contact sheets as consecutive context segments from the same chunk. "
            "Score only this chunk as evidence that the source video contains a usable target-exercise segment. "
            "The final single-rep trim will be found later by detect_exercise_segment."
        )
        vlm_started = time.monotonic()
        try:
            raw = caption_images(frame_paths=chunk_paths, prompt=chunk_prompt)
        except Exception:
            vlm_elapsed = time.monotonic() - vlm_started
            vlm_elapsed_total += vlm_elapsed
            failed_count += 1
            reviewed_chunks.append(
                build_reviewed_chunk_timing(
                    chunk_index=chunk_index,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                    window_source=window_source,
                    render_elapsed=render_elapsed,
                    vlm_elapsed=vlm_elapsed,
                    failure="vlm_exception",
                )
            )
            continue
        vlm_elapsed = time.monotonic() - vlm_started
        vlm_elapsed_total += vlm_elapsed
        payload = extract_json_object(raw)
        if not isinstance(payload, dict):
            invalid_json_count += 1
            reviewed_chunks.append(
                build_reviewed_chunk_timing(
                    chunk_index=chunk_index,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                    window_source=window_source,
                    render_elapsed=render_elapsed,
                    vlm_elapsed=vlm_elapsed,
                    failure="invalid_json",
                )
            )
            continue
        score, reasons = score_candidate_vision_payload(payload)
        chunk_scores.append(score)
        chunk_results.append((score, reasons, payload, chunk_index))
        reviewed_chunks.append(
            build_reviewed_chunk_timing(
                chunk_index=chunk_index,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                window_source=window_source,
                render_elapsed=render_elapsed,
                vlm_elapsed=vlm_elapsed,
                score=score,
                valid=score >= 0.50,
            )
        )
        early_stop_reason = adaptive_review_stop_reason(
            chunk_scores=chunk_scores,
            chunk_results=chunk_results,
            review_order=review_order,
            settings=settings,
        )
        if early_stop_reason is not None:
            break

    if not chunk_results:
        reasons = ["vision_review_failed"]
        if invalid_json_count:
            reasons.append("vision_invalid_json")
        payload = build_failed_vision_payload(
            prepared=prepared,
            settings=settings,
            reviewed_chunks=reviewed_chunks,
            failed_count=failed_count,
            invalid_json_count=invalid_json_count,
            render_elapsed_total=render_elapsed_total,
            vlm_elapsed_total=vlm_elapsed_total,
            review_elapsed=time.monotonic() - review_started,
            early_stop_reason=early_stop_reason or "no_valid_vlm_payload",
        )
        return 0.0, reasons, payload

    best_score, best_reasons, best_payload, best_chunk_index = max(chunk_results, key=lambda item: item[0])
    average_score = sum(chunk_scores) / len(chunk_scores)
    valid_chunk_count = sum(1 for score in chunk_scores if score >= 0.50)
    valid_chunk_ratio = valid_chunk_count / len(chunk_scores)
    final_score = clamp_score((best_score * 0.88) + (average_score * 0.07) + (valid_chunk_ratio * 0.05))
    final_score, evidence_reasons = apply_chunk_evidence_caps(
        final_score,
        scored_chunk_count=len(chunk_scores),
        valid_chunk_count=valid_chunk_count,
        valid_chunk_ratio=valid_chunk_ratio,
        best_chunk_score=best_score,
        candidate_duration_seconds=prepared.candidate.duration_seconds,
    )
    compact_payload = dict(best_payload)
    best_chunk_start, best_chunk_end = (
        prepared.chunk_windows[best_chunk_index]
        if best_chunk_index < len(prepared.chunk_windows)
        else (None, None)
    )
    compact_payload["selectionRole"] = "source_video_suitability_only"
    compact_payload["sampledFrameCount"] = len(prepared.frame_paths)
    compact_payload["sampledChunkCount"] = prepared.chunk_count
    compact_payload["scoredChunkCount"] = len(chunk_scores)
    compact_payload["validChunkCount"] = valid_chunk_count
    compact_payload["validChunkRatio"] = valid_chunk_ratio
    compact_payload["bestChunkIndex"] = best_chunk_index
    compact_payload["bestChunkStartSeconds"] = best_chunk_start
    compact_payload["bestChunkEndSeconds"] = best_chunk_end
    compact_payload["bestChunkScore"] = best_score
    compact_payload["bestChunkSource"] = "chunked_source_video_review"
    compact_payload["averageChunkScore"] = average_score
    compact_payload["chunkEvidenceCapApplied"] = final_score < clamp_score((best_score * 0.88) + (average_score * 0.07) + (valid_chunk_ratio * 0.05))
    compact_payload["failedChunkCount"] = failed_count
    compact_payload["invalidJsonChunkCount"] = invalid_json_count
    compact_payload.update(
        build_vision_timing_payload(
            prepared=prepared,
            settings=settings,
            reviewed_chunks=reviewed_chunks,
            render_elapsed_total=render_elapsed_total,
            vlm_elapsed_total=vlm_elapsed_total,
            review_elapsed=time.monotonic() - review_started,
            early_stop_reason=early_stop_reason or "max_budget_reached",
        )
    )
    return final_score, dedupe_reasons(best_reasons + evidence_reasons + ["chunked_source_video_review"]), compact_payload


def planned_adaptive_chunk_indexes(
    prepared: PreparedVisionReview,
    settings: YouTubeRankingSettings,
) -> list[int]:
    chunk_count = prepared.chunk_count or len(prepared.frame_path_chunks)
    if chunk_count <= 0:
        return []
    hard_limit = settings.vision_max_chunks_per_candidate or chunk_count
    hard_limit = max(1, min(hard_limit, chunk_count))
    if not settings.vision_adaptive_chunk_review:
        return list(range(hard_limit))
    initial_budget = max(1, min(settings.vision_initial_chunks_per_candidate, hard_limit))
    expansion_budget = max(0, settings.vision_expand_chunks_per_candidate)
    budget = min(hard_limit, initial_budget + expansion_budget)
    motion_indexes = [
        index
        for index, window in enumerate(prepared.review_windows)
        if window.source == "motion_interval"
    ]
    coverage_indexes = [
        index
        for index, window in enumerate(prepared.review_windows)
        if window.source != "motion_interval"
    ]
    ordered: list[int] = []
    for index in [*motion_indexes[:1], *coverage_indexes[:1], *motion_indexes[1:], *coverage_indexes[1:]]:
        if index not in ordered and index < chunk_count:
            ordered.append(index)
    for index in range(chunk_count):
        if index not in ordered:
            ordered.append(index)
    return ordered[:budget]


def get_prepared_chunk_paths(
    prepared: PreparedVisionReview,
    chunk_index: int,
    settings: YouTubeRankingSettings,
) -> tuple[list[Path], float]:
    if chunk_index in prepared.rendered_chunk_cache:
        return prepared.rendered_chunk_cache[chunk_index][0], 0.0
    if chunk_index < len(prepared.frame_path_chunks):
        paths = prepared.frame_path_chunks[chunk_index]
        prepared.rendered_chunk_cache[chunk_index] = (paths, 0.0)
        return paths, 0.0
    if prepared.video_path is None or chunk_index >= len(prepared.review_windows):
        return [], 0.0
    from exercise_motion_pkg.segment_detection import DetectionWindow, extract_window_frames

    window = prepared.review_windows[chunk_index]
    started = time.monotonic()
    frame_samples = extract_window_frames(
        video_path=prepared.video_path,
        window=DetectionWindow(
            index=window.index,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
        ),
        frames_per_window=max(1, prepared.frames_per_chunk or settings.vision_frames_per_candidate or 1),
        max_frame_width=640,
        contact_sheet_enabled=True,
        contact_sheet_columns=settings.vision_contact_sheet_columns,
        contact_sheet_tile_width=settings.vision_contact_sheet_tile_width,
        contact_sheet_frames_per_sheet=settings.vision_contact_sheet_frames_per_sheet,
        contact_sheet_jpeg_quality=settings.vision_contact_sheet_jpeg_quality,
        output_dir=Path(prepared.temp_dir.name) / "frames" / f"chunk_{chunk_index:04d}",
    )
    elapsed = time.monotonic() - started
    paths = [sample.path if hasattr(sample, "path") else sample for sample in frame_samples]
    prepared.rendered_chunk_cache[chunk_index] = (paths, elapsed)
    if chunk_index >= len(prepared.frame_path_chunks):
        prepared.frame_path_chunks.extend([[] for _ in range(chunk_index - len(prepared.frame_path_chunks) + 1)])
    prepared.frame_path_chunks[chunk_index] = paths
    prepared.frame_paths.extend(paths)
    return paths, elapsed


def adaptive_review_stop_reason(
    *,
    chunk_scores: list[float],
    chunk_results: list[tuple[float, list[str], dict[str, Any], int]],
    review_order: int,
    settings: YouTubeRankingSettings,
) -> str | None:
    if not settings.vision_adaptive_chunk_review:
        return None
    initial_budget = max(1, settings.vision_initial_chunks_per_candidate)
    if len(chunk_scores) >= initial_budget and max(chunk_scores, default=0.0) < 0.50:
        return "all_diagnostic_chunks_bad"
    best_score, best_reasons, _, _ = max(chunk_results, key=lambda item: item[0])
    if (
        len(chunk_scores) >= initial_budget
        and sum(1 for score in chunk_scores if score >= 0.50) >= 2
        and best_score >= settings.vision_early_stop_score
        and VISION_HARD_GATE_REASONS.issubset(set(best_reasons))
    ):
        return "strong_source_interval"
    return None


def build_reviewed_chunk_timing(
    *,
    chunk_index: int,
    chunk_start: float,
    chunk_end: float,
    window_source: str,
    render_elapsed: float,
    vlm_elapsed: float,
    score: float | None = None,
    valid: bool | None = None,
    failure: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chunkIndex": chunk_index,
        "startSeconds": round(chunk_start, 3),
        "endSeconds": round(chunk_end, 3),
        "windowSource": window_source,
        "renderElapsedSeconds": round_elapsed(render_elapsed),
        "vlmElapsedSeconds": round_elapsed(vlm_elapsed),
    }
    if score is not None:
        payload["score"] = round(score, 4)
    if valid is not None:
        payload["valid"] = valid
    if failure is not None:
        payload["failure"] = failure
    return payload


def build_vision_timing_payload(
    *,
    prepared: PreparedVisionReview,
    settings: YouTubeRankingSettings,
    reviewed_chunks: list[dict[str, Any]],
    render_elapsed_total: float,
    vlm_elapsed_total: float,
    review_elapsed: float,
    early_stop_reason: str,
) -> dict[str, Any]:
    return {
        "previewPreparationElapsedSeconds": round_elapsed(prepared.preview_preparation_elapsed_seconds),
        "previewDownloadElapsedSeconds": round_elapsed(prepared.preview_download_elapsed_seconds),
        "motionScanElapsedSeconds": round_elapsed(prepared.motion_scan_elapsed_seconds),
        "windowPlanningElapsedSeconds": round_elapsed(prepared.window_planning_elapsed_seconds),
        "totalVisionReviewElapsedSeconds": round_elapsed(review_elapsed),
        "totalChunkRenderElapsedSeconds": round_elapsed(render_elapsed_total),
        "totalChunkVlmElapsedSeconds": round_elapsed(vlm_elapsed_total),
        "reviewedChunks": reviewed_chunks,
        "adaptiveReviewPolicy": {
            "enabled": settings.vision_adaptive_chunk_review,
            "initialChunkBudget": max(1, settings.vision_initial_chunks_per_candidate),
            "expansionChunkBudget": max(0, settings.vision_expand_chunks_per_candidate),
            "maxChunkBudget": settings.vision_max_chunks_per_candidate,
            "earlyStopReason": early_stop_reason,
            "reviewedChunkCount": len(reviewed_chunks),
            "plannedChunkCount": prepared.chunk_count,
        },
    }


def build_failed_vision_payload(
    *,
    prepared: PreparedVisionReview,
    settings: YouTubeRankingSettings,
    reviewed_chunks: list[dict[str, Any]],
    failed_count: int,
    invalid_json_count: int,
    render_elapsed_total: float,
    vlm_elapsed_total: float,
    review_elapsed: float,
    early_stop_reason: str,
) -> dict[str, Any]:
    payload = {
        "selectionRole": "source_video_suitability_only",
        "sampledFrameCount": len(prepared.frame_paths),
        "sampledChunkCount": prepared.chunk_count,
        "scoredChunkCount": 0,
        "validChunkCount": 0,
        "validChunkRatio": 0.0,
        "failedChunkCount": failed_count,
        "invalidJsonChunkCount": invalid_json_count,
    }
    payload.update(
        build_vision_timing_payload(
            prepared=prepared,
            settings=settings,
            reviewed_chunks=reviewed_chunks,
            render_elapsed_total=render_elapsed_total,
            vlm_elapsed_total=vlm_elapsed_total,
            review_elapsed=review_elapsed,
            early_stop_reason=early_stop_reason,
        )
    )
    return payload


def apply_chunk_evidence_caps(
    score: float,
    *,
    scored_chunk_count: int,
    valid_chunk_count: int,
    valid_chunk_ratio: float,
    best_chunk_score: float | None = None,
    candidate_duration_seconds: int | float | None = None,
) -> tuple[float, list[str]]:
    if scored_chunk_count <= 0:
        return score, []
    if valid_chunk_count <= 0:
        return min(score, 0.34), ["no_valid_source_chunk_evidence"]
    if valid_chunk_count < 2 or valid_chunk_ratio < 0.25:
        if single_strong_chunk_is_enough(
            best_chunk_score=best_chunk_score,
            candidate_duration_seconds=candidate_duration_seconds,
            valid_chunk_count=valid_chunk_count,
            valid_chunk_ratio=valid_chunk_ratio,
        ):
            return score, []
        return min(score, 0.34), ["low_source_evidence_coverage"]
    return score, []


def single_strong_chunk_is_enough(
    *,
    best_chunk_score: float | None,
    candidate_duration_seconds: int | float | None,
    valid_chunk_count: int,
    valid_chunk_ratio: float,
) -> bool:
    if valid_chunk_count != 1:
        return False
    if valid_chunk_ratio < 0.5:
        return False
    if best_chunk_score is None or best_chunk_score < 0.80:
        return False
    if candidate_duration_seconds is None:
        return False
    return 0.0 < float(candidate_duration_seconds) <= 30.0


def score_candidate_vision_payload(payload: dict[str, Any]) -> tuple[float, list[str]]:
    explicit_gate_values = {
        gate: parse_payload_bool(payload, gate)
        for gate in VISION_HARD_GATE_REASONS
    }
    single_person_chunk = explicit_gate_values.get("single_person_chunk")
    real_human_subject = explicit_gate_values.get("real_human_subject")
    start_posture_visible = explicit_gate_values.get("movement_start_posture_visible")
    primary_effort_phase_visible = explicit_gate_values.get("primary_effort_phase_visible")
    action_path_visible = explicit_gate_values.get("movement_action_path_visible")
    end_posture_visible = explicit_gate_values.get("movement_end_posture_visible")
    no_setup_or_talking_frames = explicit_gate_values.get("no_setup_or_talking_frames")
    target_identity_match = parse_payload_bool(payload, "target_identity_match")
    target_match = parse_score_value(
        payload.get("target_match"),
        default=1.0 if explicit_gate_values.get("correct_exercise") is True and target_identity_match is not False else 0.0,
    )
    complete_movement = parse_score_value(
        payload.get("complete_movement"),
        default=1.0 if explicit_gate_values.get("complete_repetition_visible") is True else 0.0,
    )
    capture_quality = parse_score_value(
        payload.get("capture_quality"),
        default=default_capture_quality_from_payload(payload, explicit_gate_values),
    )
    execution_quality = parse_score_value(
        payload.get("execution_quality"),
        default=default_execution_quality_from_payload(explicit_gate_values),
    )
    source_score = parse_score_value(
        payload.get("source_score"),
        default=1.0 if explicit_gate_values.get("usable_for_motion_extraction") is True else 0.0,
    )
    blocking_issues = parse_blocking_issues(payload.get("blocking_issues", payload.get("blocking_issue")))
    confidence_score = parse_score_value(payload.get("confidence"), default=0.5)

    score = source_score
    reasons: list[str] = []
    for gate, value in explicit_gate_values.items():
        if value is True:
            reasons.append(gate)
        elif value is False:
            reasons.append(f"{gate}_failed")

    if explicit_gate_values.get("athlete_fully_in_frame_throughout") is False or parse_payload_bool(
        payload, "implement_path_visible"
    ) is False:
        reasons.append("athlete_or_implement_out_of_frame_penalty")
    if (
        explicit_gate_values.get("static_camera_throughout") is False
        or explicit_gate_values.get("single_camera_angle") is False
    ):
        reasons.append("moving_or_reframing_camera_penalty")
    if explicit_gate_values.get("large_body_visible") is False:
        reasons.append("small_body_pose_extraction_penalty")
    if explicit_gate_values.get("pose_friendly_camera_angle") is False:
        reasons.append("bad_pose_camera_angle_penalty")
    if explicit_gate_values.get("body_joint_motion_visible") is False:
        reasons.append("weak_body_joint_motion_penalty")
    if explicit_gate_values.get("low_equipment_occlusion") is False:
        reasons.append("equipment_occlusion_penalty")
    if explicit_gate_values.get("critical_moving_joints_visible") is False:
        reasons.append("critical_joint_visibility_penalty")
    if explicit_gate_values.get("low_critical_joint_occlusion") is False:
        reasons.append("critical_joint_occlusion_penalty")
    if explicit_gate_values.get("reconstruction_suitable") is False:
        reasons.append("poor_reconstruction_suitability_penalty")
    if real_human_subject is False:
        reasons.append("animation_or_synthetic_source_penalty")
    if start_posture_visible is False:
        reasons.append("missing_movement_start_posture_penalty")
    if primary_effort_phase_visible is False:
        reasons.append("missing_primary_effort_phase_penalty")
    if action_path_visible is False:
        reasons.append("missing_movement_action_path_penalty")
    if end_posture_visible is False:
        reasons.append("missing_movement_end_posture_penalty")
    if no_setup_or_talking_frames is False:
        reasons.append("setup_or_talking_penalty")

    for issue in blocking_issues:
        if issue != "none":
            reasons.append(f"{issue}_penalty")
    if target_identity_match is True:
        reasons.append("target_identity_match")
    elif target_identity_match is False:
        reasons.append("target_identity_mismatch_penalty")
        score = min(score, 0.20)
    if target_match >= 0.75:
        reasons.append("target_match")
        if explicit_gate_values.get("correct_exercise") is not False:
            reasons.append("correct_exercise")
    else:
        reasons.append("wrong_exercise_penalty")
    movement_phase_gates_pass = (
        start_posture_visible is True
        and primary_effort_phase_visible is True
        and action_path_visible is True
        and end_posture_visible is True
        and no_setup_or_talking_frames is True
    )
    if complete_movement >= 0.75 and movement_phase_gates_pass:
        reasons.append("complete_movement")
        if explicit_gate_values.get("complete_repetition_visible") is not False:
            reasons.append("complete_repetition_visible")
    else:
        reasons.append("partial_movement_penalty")
    if capture_quality >= 0.75:
        reasons.append("capture_quality")
    else:
        reasons.append("bad_capture_quality_penalty")
    if execution_quality >= 0.75:
        reasons.append("execution_quality")
        append_execution_gate_reasons(reasons, explicit_gate_values)
    else:
        reasons.append("bad_execution_quality_penalty")
    if source_score >= 0.75:
        reasons.append("source_score")
        if explicit_gate_values.get("usable_for_motion_extraction") is not False:
            reasons.append("usable_for_motion_extraction")
    else:
        reasons.append("weak_source_score_penalty")

    minimum_gate_score = min(
        target_match,
        complete_movement,
        capture_quality,
        execution_quality,
    )
    valid_motion_scene = (
        minimum_gate_score >= 0.75
        and single_person_chunk is True
        and real_human_subject is not False
        and start_posture_visible is True
        and primary_effort_phase_visible is True
        and action_path_visible is True
        and end_posture_visible is True
        and no_setup_or_talking_frames is True
    )
    if valid_motion_scene:
        reasons.append("valid_motion_scene")

    if single_person_chunk is False:
        score = 0.0
    else:
        if minimum_gate_score < 0.65:
            score = min(score, 0.49)
        else:
            score = min(score, minimum_gate_score)
        score = apply_explicit_gate_caps(score, explicit_gate_values)
        score = apply_blocking_issue_caps(score, blocking_issues)
        if single_person_chunk is not True:
            score = min(score, 0.49)
        score *= confidence_score
        if not valid_motion_scene:
            score = min(score, 0.49)
    return clamp_score(score), dedupe_reasons(reasons)


def default_capture_quality_from_payload(
    payload: dict[str, Any],
    explicit_gate_values: dict[str, bool | None],
) -> float:
    relevant = [
        explicit_gate_values.get("athlete_fully_in_frame_throughout"),
        explicit_gate_values.get("static_camera_throughout"),
        explicit_gate_values.get("single_camera_angle"),
        explicit_gate_values.get("unobstructed_motion"),
        explicit_gate_values.get("key_joints_visible"),
        explicit_gate_values.get("large_body_visible"),
        explicit_gate_values.get("pose_friendly_camera_angle"),
        explicit_gate_values.get("body_joint_motion_visible"),
        explicit_gate_values.get("low_equipment_occlusion"),
        explicit_gate_values.get("critical_moving_joints_visible"),
        explicit_gate_values.get("low_critical_joint_occlusion"),
        explicit_gate_values.get("reconstruction_suitable"),
        explicit_gate_values.get("single_person_chunk"),
        explicit_gate_values.get("real_human_subject"),
        parse_payload_bool(payload, "implement_path_visible"),
    ]
    known = [value for value in relevant if value is not None]
    if not known:
        return 0.0
    return sum(1 for value in known if value) / len(known)


def default_execution_quality_from_payload(explicit_gate_values: dict[str, bool | None]) -> float:
    relevant = [
        explicit_gate_values.get("normal_speed_execution"),
        explicit_gate_values.get("not_broken_into_steps"),
        explicit_gate_values.get("continuous_motion"),
        explicit_gate_values.get("no_step_breakdown"),
        explicit_gate_values.get("no_camera_cuts"),
        explicit_gate_values.get("exercise_only_chunk"),
        explicit_gate_values.get("movement_start_posture_visible"),
        explicit_gate_values.get("primary_effort_phase_visible"),
        explicit_gate_values.get("movement_action_path_visible"),
        explicit_gate_values.get("movement_end_posture_visible"),
        explicit_gate_values.get("no_setup_or_talking_frames"),
    ]
    known = [value for value in relevant if value is not None]
    if not known:
        return 0.0
    return sum(1 for value in known if value) / len(known)


def append_execution_gate_reasons(
    reasons: list[str],
    explicit_gate_values: dict[str, bool | None],
) -> None:
    for gate in (
        "exercise_only_chunk",
        "normal_speed_execution",
        "not_broken_into_steps",
        "continuous_motion",
        "movement_start_posture_visible",
        "primary_effort_phase_visible",
        "movement_action_path_visible",
        "movement_end_posture_visible",
        "no_setup_or_talking_frames",
        "single_camera_angle",
        "no_step_breakdown",
        "no_camera_cuts",
        "unobstructed_motion",
        "key_joints_visible",
        "large_body_visible",
        "pose_friendly_camera_angle",
        "body_joint_motion_visible",
        "low_equipment_occlusion",
        "critical_moving_joints_visible",
        "low_critical_joint_occlusion",
        "reconstruction_suitable",
    ):
        if explicit_gate_values.get(gate) is not False:
            reasons.append(gate)


def apply_explicit_gate_caps(score: float, explicit_gate_values: dict[str, bool | None]) -> float:
    caps = {
        "correct_exercise": 0.20,
        "usable_for_motion_extraction": 0.49,
        "complete_repetition_visible": 0.49,
        "exercise_only_chunk": 0.49,
        "movement_start_posture_visible": 0.34,
        "primary_effort_phase_visible": 0.34,
        "movement_action_path_visible": 0.34,
        "movement_end_posture_visible": 0.34,
        "no_setup_or_talking_frames": 0.34,
        "normal_speed_execution": 0.49,
        "not_broken_into_steps": 0.49,
        "continuous_motion": 0.49,
        "athlete_fully_in_frame_throughout": 0.34,
        "static_camera_throughout": 0.34,
        "single_camera_angle": 0.34,
        "no_step_breakdown": 0.49,
        "no_camera_cuts": 0.34,
        "unobstructed_motion": 0.49,
        "key_joints_visible": 0.49,
        "large_body_visible": 0.49,
        "pose_friendly_camera_angle": 0.49,
        "body_joint_motion_visible": 0.49,
        "low_equipment_occlusion": 0.49,
        "critical_moving_joints_visible": 0.34,
        "low_critical_joint_occlusion": 0.34,
        "reconstruction_suitable": 0.34,
        "real_human_subject": 0.20,
    }
    capped = score
    for gate, cap in caps.items():
        if explicit_gate_values.get(gate) is False:
            capped = min(capped, cap)
    return capped


def parse_payload_bool(payload: dict[str, Any], key: str) -> bool | None:
    if key in payload:
        return parse_optional_bool_value(payload.get(key))
    return None


def parse_bool_value(value: Any, *, default: bool) -> bool:
    parsed = parse_optional_bool_value(value)
    if parsed is not None:
        return parsed
    return default


def parse_optional_bool_value(value: Any) -> bool | None:
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


def parse_score_value(value: Any, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        score = float(value)
    elif isinstance(value, str):
        try:
            score = float(value.strip())
        except ValueError:
            return default
    else:
        return default
    if score > 1.0 and score <= 10.0:
        score /= 10.0
    return clamp_score(score)


def parse_blocking_issues(value: Any) -> list[str]:
    allowed = {
        "none",
        "wrong_exercise",
        "partial_movement",
        "camera_motion",
        "cropped_body",
        "multiple_people",
        "obstruction",
        "small_body",
        "bad_pose_angle",
        "weak_body_joint_motion",
        "equipment_occlusion",
        "critical_joint_occlusion",
        "poor_reconstruction_suitability",
        "slow_instruction",
        "setup_or_talking",
        "animation_or_synthetic",
    }
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        return ["none"]
    issues: list[str] = []
    for item in raw_items:
        text = str(item).strip().lower()
        if text in allowed and text not in issues:
            issues.append(text)
    if not issues:
        return ["none"]
    if len(issues) > 1 and "none" in issues:
        issues.remove("none")
    return issues


def apply_blocking_issue_caps(score: float, blocking_issues: list[str]) -> float:
    caps = {
        "wrong_exercise": 0.20,
        "partial_movement": 0.34,
        "camera_motion": 0.34,
        "cropped_body": 0.34,
        "multiple_people": 0.49,
        "obstruction": 0.49,
        "small_body": 0.49,
        "bad_pose_angle": 0.49,
        "weak_body_joint_motion": 0.49,
        "equipment_occlusion": 0.49,
        "critical_joint_occlusion": 0.34,
        "poor_reconstruction_suitability": 0.34,
        "slow_instruction": 0.49,
        "setup_or_talking": 0.34,
        "animation_or_synthetic": 0.20,
    }
    capped = score
    for issue in blocking_issues:
        if issue in caps:
            capped = min(capped, caps[issue])
    return capped


def build_candidate_vision_prompt(exercise_name: str, candidate: YouTubeCandidate) -> str:
    return (
        "Score this sampled video chunk for exercise motion extraction source suitability.\n"
        f"Target exercise: {exercise_name}.\n"
        f"Video title: {candidate.title}.\n"
        "Judge only the attached frames/contact sheets from this chunk. Do not infer missing phases from other chunks.\n"
        "The reviewed chunk itself must be usable as the source window for motion extraction. Do not pass a chunk merely because the broader video may contain a good segment elsewhere.\n"
        "Good chunks show continuous uninterrupted repetitions or at least one complete uninterrupted movement from the start posture, through the main action path, to the end posture.\n"
        "Reject chunks that only show setup, instruction, hanging/holding/standing/lying idle, walking into position, talking to camera, a title card, or only a partial phase of the movement.\n"
        "Do not treat a natural start or finish posture as setup/idle merely because the athlete is briefly hanging, standing, lying, holding, or paused there; if that posture is directly connected to the visible movement, it is part of the exercise boundary.\n"
        "Extra non-exercise frames before or after the movement are a blocking issue for source selection; include setup_or_talking and lower source_score even if a partial rep is visible.\n"
        "Any angle is acceptable if it stays the same.\n"
        "Treat the target exercise name as the exact movement identity, not just a loose keyword match. Adjacent variations that share words but visibly change the required stance, support, equipment path, body position, or movement pattern are wrong for this target.\n"
        "If the requested exercise name contains qualifiers such as single-leg, split, incline, decline, seated, bent-over, front, back, lateral, supported, unsupported, dumbbell, barbell, cable, machine, or similar variant terms, the visible movement must satisfy those qualifiers.\n"
        "If the source title or visible movement adds an exercise-changing qualifier that is not in the target name, mark target_identity_match false. Examples: incline, decline, seated, supported, machine, smith-machine, close-grip, wide-grip, single-arm, or triceps-focused variants are wrong unless requested by the target exercise name.\n"
        "The whole relevant body and implement visible through the entire rep is required.\n"
        "Judge whether this chunk is friendly for monocular human-pose extraction, not merely understandable to a human viewer.\n"
        "The athlete body should occupy enough of the frame that shoulders, elbows, wrists, hips, knees, and ankles are readable across the rep.\n"
        "Critical moving joints for the requested exercise must stay visible enough for 3D reconstruction. Penalize clips where a moving elbow, wrist, knee, ankle, shoulder, or hip is repeatedly hidden by the body, equipment, bench, rack, plates, camera angle, or crop even if a human can still recognize the exercise.\n"
        "Prefer side or three-quarter views where limb joint travel is visible. Penalize top-down, extreme front/back, very low, very far, or tiny-body views even if the exercise is clear.\n"
        "Visible motion must come from the athlete body joints, not only from an implement such as a barbell, dumbbell, cable handle, or machine arm.\n"
        "Penalize equipment, plates, bench pads, racks, machines, text overlays, or props that hide the torso, shoulders, elbows, wrists, hips, knees, or ankles during the rep.\n"
        "For source selection, prefer clean repeatable demo repetitions over records, personal records, max attempts, AMRAP tests, competitions, combines, meets, crowds, or event footage. Those event clips are lower-quality motion sources even when the exercise is technically correct.\n"
        "A usable chunk must be one continuous camera view: no cuts, no edits, no angle changes, no zoom/reframe during the movement, and no switch to a different shot.\n"
        "Set static_camera_throughout false for shaky handheld video, zooming, reframing, camera cuts, or angle changes.\n"
        "Set single_camera_angle false if any attached sheet shows a different viewpoint, shot, camera position, or edited cut within this chunk.\n"
        "Set no_camera_cuts false if the chunk appears edited or jumps between shots, even when each individual shot is clear.\n"
        "Set athlete_fully_in_frame_throughout false if the head, hands, torso, hips, knees, ankles, or feet needed for the movement leave the image or are cropped in any attached sheet.\n"
        "If static_camera_throughout, single_camera_angle, no_camera_cuts, or athlete_fully_in_frame_throughout is false, set source_score no higher than 0.34 and include camera_motion or cropped_body in blocking_issues.\n"
        "Reject step-by-step demonstrations, setup, talking, title cards, and slow instructional breakdowns.\n"
        "Set movement_start_posture_visible true only if the chunk visibly includes the beginning posture of a full movement or repetition. Set it false for mid-rep starts, idle setup, or a person only preparing to move.\n"
        "Set primary_effort_phase_visible true only if the chunk visibly includes the main intended action of the requested exercise, not just the return, lowering, eccentric, negative, reset, or recovery phase. If the target exercise name explicitly requests a negative/eccentric/return-only variation, judge that requested phase as the primary effort.\n"
        "Set movement_action_path_visible true only if the chunk visibly includes the main joint/body travel of the movement, not just the athlete holding the start/end position.\n"
        "Set movement_end_posture_visible true only if the chunk visibly reaches the natural end posture of that same movement or repetition. Set it false for clips that stop mid-rep or before the movement resolves.\n"
        "Set no_setup_or_talking_frames false when any attached sheet is primarily setup, talking, instruction, title-card, walking into position, idle hanging/standing/lying, or reset content rather than the exercise movement. Keep it true when brief boundary postures are directly attached to the full movement.\n"
        "A usable chunk must show exactly one visible human body/person across every attached contact sheet.\n"
        "Prefer videos where the only visible person in the frame is the athlete performing the exercise.\n"
        "Set single_person_chunk false if a trainer, coach, spotter, second athlete, bystander, reflection, picture-in-picture person, or partial extra human is visible in any sheet.\n"
        "When single_person_chunk is false, include multiple_people in blocking_issues and set source_score to 0.0.\n"
        "Do not return [\"none\"] for blocking_issues when any extra person is visible.\n"
        "Prefer real camera footage of real people. Penalize animations, cartoons, CGI, 3D renders, game footage, motion-capture previews, skeleton-only demos, mannequins, avatars, or synthetic exercise demos even if the motion is correct.\n"
        "Set real_human_subject false when the moving subject is animated, rendered, synthetic, mannequin-like, or not clearly a real person captured by a camera.\n"
        "When real_human_subject is false, include animation_or_synthetic in blocking_issues and set source_score no higher than 0.20.\n"
        "Return boolean values for gate fields and numeric scores from 0.0 to 1.0 for score fields.\n"
        "Use this scale: 1.0 excellent, 0.8 good, 0.6 flawed but maybe usable, 0.4 poor, 0.0 unusable.\n"
        "Score definitions:\n"
        "- target_match: how clearly this chunk shows the requested exercise.\n"
        "- complete_movement: how clearly this exact chunk contains a full movement cycle with visible start posture, main action path, and end posture, not just exercise context or a partial transition.\n"
        "- capture_quality: how suitable the capture is for motion extraction: fixed camera, whole relevant body/equipment visible, one person, no obstructions, readable body scale, pose-friendly angle, visible body-joint motion.\n"
        "- reconstruction_suitability: whether the visible frames are likely to reconstruct into a usable 3D skeleton, with critical moving joints readable rather than inferred through occlusion.\n"
        "- execution_quality: how naturally the exercise is performed: normal-speed, continuous, not paused, slow teaching, step-by-step, setup, talking, or title-card content.\n"
        "- source_score: overall usefulness of this exact chunk as the source segment likely to reconstruct into a usable body skeleton.\n"
        "Before scoring, list all visible blocking issues across every attached contact sheet. Use [] or [\"none\"] only if no blocking issue is visible. If any sheet shows camera zoom/reframing, body cropping, partial movement, obstruction, multiple people, slow instruction, setup, talking, wrong exercise, tiny body, bad pose angle, weak body-joint motion, equipment occlusion, critical joint occlusion, poor reconstruction suitability, or animated/synthetic rendered content, include the matching blocking issue.\n"
        "Return JSON only with these keys:\n"
        "{"
        '"correct_exercise": boolean, '
        '"usable_for_motion_extraction": boolean, '
        '"complete_repetition_visible": boolean, '
        '"loopable_repetition_cycle": boolean, '
        '"exercise_only_chunk": boolean, '
        '"normal_speed_execution": boolean, '
        '"not_broken_into_steps": boolean, '
        '"continuous_motion": boolean, '
        '"athlete_fully_in_frame_throughout": boolean, '
        '"static_camera_throughout": boolean, '
        '"single_camera_angle": boolean, '
        '"no_step_breakdown": boolean, '
        '"no_camera_cuts": boolean, '
        '"unobstructed_motion": boolean, '
        '"key_joints_visible": boolean, '
        '"large_body_visible": boolean, '
        '"pose_friendly_camera_angle": boolean, '
        '"body_joint_motion_visible": boolean, '
        '"low_equipment_occlusion": boolean, '
        '"critical_moving_joints_visible": boolean, '
        '"low_critical_joint_occlusion": boolean, '
        '"reconstruction_suitable": boolean, '
        '"single_person_chunk": boolean, '
        '"real_human_subject": boolean, '
        '"movement_start_posture_visible": boolean, '
        '"primary_effort_phase_visible": boolean, '
        '"movement_action_path_visible": boolean, '
        '"movement_end_posture_visible": boolean, '
        '"no_setup_or_talking_frames": boolean, '
        '"target_identity_match": boolean, '
        '"target_match": number, '
        '"complete_movement": number, '
        '"capture_quality": number, '
        '"execution_quality": number, '
        '"source_score": number, '
        '"blocking_issues": ["none|wrong_exercise|partial_movement|camera_motion|cropped_body|multiple_people|obstruction|small_body|bad_pose_angle|weak_body_joint_motion|equipment_occlusion|critical_joint_occlusion|poor_reconstruction_suitability|slow_instruction|setup_or_talking|animation_or_synthetic"], '
        '"confidence": number, '
        '"reason": string'
        "}"
    )
