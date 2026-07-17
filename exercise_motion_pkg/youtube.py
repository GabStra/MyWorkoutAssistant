from __future__ import annotations

import base64
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace as dataclass_replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any, Callable, Iterable

import httpx
from exercise_motion_pkg.chunking import estimate_chunking, frames_for_chunk_seconds
from exercise_motion_pkg.ffmpeg_utils import ffmpeg_location_for_ytdlp, resolve_ffmpeg_path
from exercise_motion_pkg.gpu_lock import GlobalGpuLock
from exercise_motion_pkg.llama_defaults import (
    DEFAULT_LLAMA_CPP_BATCH_SIZE,
    DEFAULT_LLAMA_CPP_CACHE_TYPE_K,
    DEFAULT_LLAMA_CPP_CACHE_TYPE_V,
    DEFAULT_LLAMA_CPP_CTX_SIZE,
    DEFAULT_LLAMA_CPP_FIT,
    DEFAULT_LLAMA_CPP_FIT_CTX,
    DEFAULT_LLAMA_CPP_FIT_TARGET,
    DEFAULT_LLAMA_CPP_FLASH_ATTN,
    DEFAULT_LLAMA_CPP_IMAGE_MIN_TOKENS,
    DEFAULT_LLAMA_CPP_IMAGE_MAX_TOKENS,
    DEFAULT_LLAMA_CPP_MLOCK,
    DEFAULT_LLAMA_CPP_MMAP,
    DEFAULT_LLAMA_CPP_MMPROJ,
    DEFAULT_LLAMA_CPP_MODEL,
    DEFAULT_LLAMA_CPP_MTP_MODEL,
    DEFAULT_LLAMA_CPP_MTMD_BATCH_MAX_TOKENS,
    DEFAULT_LLAMA_CPP_PARALLEL,
    DEFAULT_LLAMA_CPP_REASONING_BUDGET,
    DEFAULT_LLAMA_CPP_REASONING_BUDGET_MESSAGE,
    DEFAULT_LLAMA_CPP_SERVER_COMMAND,
    DEFAULT_LLAMA_CPP_SPEC_DRAFT_N_MAX,
    DEFAULT_LLAMA_CPP_TEMPERATURE,
    DEFAULT_LLAMA_CPP_TOP_K,
    DEFAULT_LLAMA_CPP_TOP_P,
    DEFAULT_LLAMA_CPP_UBATCH_SIZE,
    DEFAULT_TEXT_LLAMA_CPP_MMPROJ,
    DEFAULT_TEXT_LLAMA_CPP_MODEL,
)
from exercise_motion_pkg.pose_prefilter import (
    PosePrefilterSettings,
    YoloDeviceUnavailableError,
    normalize_yolo_cuda_device,
    run_yolo_pose_prefilter,
)
from exercise_motion_pkg.target_motion import (
    TARGET_MOTION_PREFILTER_BLOCKING_ISSUE,
    normalize_observable_motion_axis,
    normalize_observable_motion_pattern,
    normalize_observable_motion_regions,
    normalize_observable_motion_spec,
    parse_contract_bool,
)
from exercise_motion_pkg.vlm_errors import (
    add_vlm_context,
    is_critical_vlm_interaction_error,
    vlm_error_payload,
    wrap_vlm_infrastructure_error,
)

TEXT_ONLY_LLAMA_MAX_TOKENS = 192
QUERY_PLANNER_LLAMA_MAX_TOKENS = 256
EXERCISE_MOTION_CONTRACT_LLAMA_MAX_TOKENS = 768
EXERCISE_MOTION_CONTRACT_TEXT_LIMIT = 1400
SEMANTIC_GATE_LLAMA_MAX_TOKENS = 128
SEMANTIC_GATE_DURATION_RANK_DEFAULT_WEIGHT = 0.15
SEMANTIC_GATE_SHORT_DURATION_SECONDS = 20.0
SEMANTIC_GATE_DURATION_HORIZON_SECONDS = 120.0
LLAMA_CPP_CHAT_READY_PROBE_TIMEOUT_SECONDS = 5.0
YOUTUBE_PREVIEW_FRAGMENT_WORKERS = 4
YOUTUBE_FULL_DOWNLOAD_CLIENT_ATTEMPTS: tuple[str | None, ...] = ("android_vr", "tv", None)
SOURCE_REVIEW_NEAR_DUPLICATE_FRAME_DELTA = 0.005
SOURCE_REVIEW_NEAR_DUPLICATE_PAIR_RATIO = 0.80
SOURCE_REVIEW_MAX_STATIC_TEMPORAL_RANGE = 0.03
SOURCE_REVIEW_TEMPORAL_ANALYSIS_WIDTH = 160
SOURCE_REVIEW_TEMPORAL_ANALYSIS_HEIGHT = 90

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
        from yt_dlp.utils import DownloadError  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is required for YouTube downloads. Install with: pip install .[motion]"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for attempt_index, player_client in enumerate(YOUTUBE_FULL_DOWNLOAD_CLIENT_ATTEMPTS, start=1):
        remove_incomplete_youtube_downloads(output_dir)
        attempt_cookies = isolated_youtube_cookie_copy(
            resolved_cookies_path,
            output_dir=output_dir,
            attempt_index=attempt_index,
        )
        options = build_youtube_download_options(
            outtmpl=str(output_dir / "source.%(ext)s"),
            quiet=False,
            noprogress=False,
            retries=1,
            preview=False,
            cookies_path=attempt_cookies,
        )
        if player_client is not None:
            options["extractor_args"] = {"youtube": {"player_client": [player_client]}}
        attempt_label = player_client or "automatic"
        print(f"[youtube] full download attempt {attempt_index}: client={attempt_label}", flush=True)
        try:
            try:
                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
                    downloaded = Path(ydl.prepare_filename(info))
                resolved_download = find_completed_youtube_download(downloaded)
                if resolved_download is not None:
                    return sanitize_downloaded_video(resolved_download)
                failures.append(f"client={attempt_label}: download completed without an output file")
            except DownloadError as exc:
                failures.append(f"client={attempt_label}: {truncate_text(str(exc), 300)}")
                print(
                    f"[youtube] full download attempt {attempt_index} failed; re-extracting with another client",
                    flush=True,
                )
        finally:
            if attempt_cookies is not None:
                attempt_cookies.unlink(missing_ok=True)
    raise RuntimeError(
        "YouTube full download failed after fresh client fallbacks: " + " | ".join(failures)
    )


def isolated_youtube_cookie_copy(
    cookies_path: Path | None,
    *,
    output_dir: Path,
    attempt_index: int,
) -> Path | None:
    if cookies_path is None:
        return None
    isolated_path = output_dir / f".youtube-cookies-attempt-{attempt_index}.txt"
    shutil.copy2(cookies_path, isolated_path)
    return isolated_path


def remove_incomplete_youtube_downloads(output_dir: Path) -> None:
    for candidate in output_dir.glob("source.*"):
        if candidate.is_file():
            candidate.unlink(missing_ok=True)


def find_completed_youtube_download(downloaded: Path) -> Path | None:
    if downloaded.exists() and downloaded.stat().st_size > 0:
        return downloaded
    for extension in (".mp4", ".mkv", ".webm", ".mov"):
        candidate = Path(os.path.splitext(str(downloaded))[0] + extension)
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


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
        "--concurrent-fragments",
        str(YOUTUBE_PREVIEW_FRAGMENT_WORKERS),
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


def prefetch_youtube_previews_parallel(
    candidates: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
) -> None:
    if settings.youtube_preview_cache_dir is None or not candidates:
        return
    unique_candidates: list[YouTubeCandidate] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        if candidate.url in seen_urls:
            continue
        seen_urls.add(candidate.url)
        unique_candidates.append(candidate)
    workers = max(1, min(settings.vision_download_workers, len(unique_candidates)))

    def prefetch(candidate: YouTubeCandidate) -> None:
        with tempfile.TemporaryDirectory(prefix="exercise-motion-youtube-prefetch-") as temp_dir:
            download_youtube_preview(
                candidate.url,
                Path(temp_dir),
                settings.youtube_cookies,
                cache_dir=settings.youtube_preview_cache_dir,
            )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(prefetch, candidate) for candidate in unique_candidates]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                # The normal review path will retry and record the candidate-level failure.
                continue


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
    ffmpeg = resolve_ffmpeg_path()
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
    ffmpeg_location = ffmpeg_location_for_ytdlp()
    ffmpeg_available = ffmpeg_location is not None
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
    if ffmpeg_location is not None:
        options["ffmpeg_location"] = ffmpeg_location
    return options


@dataclass(frozen=True)
class ExerciseEntry:
    exercise_id: str
    name: str
    slug: str
    source_name: str | None = None
    equipment_qualified_name: str | None = None
    name_rewrite_reason: str | None = None

    @property
    def name_was_rewritten(self) -> bool:
        return bool(self.name_rewrite_reason)


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
            "visionScore": None if self.vision_score is None else round(self.vision_score, 4),
            "finalScore": round(self.final_score, 4),
            "status": self.status,
            "scoreReasons": self.score_reasons,
        }
        if self.vision_payload is not None:
            payload["visionPayload"] = self.vision_payload
        return payload


def youtube_video_id_from_url(url: str | None) -> str | None:
    if url is None:
        return None
    parsed = urlparse(str(url).strip())
    query_ids = parse_qs(parsed.query).get("v")
    if query_ids and str(query_ids[0]).strip():
        return str(query_ids[0]).strip()
    if parsed.netloc.endswith("youtu.be"):
        candidate = parsed.path.strip("/").split("/")[0]
        if candidate:
            return candidate
    return None


def youtube_candidate_exclusion_keys_from_values(
    *,
    video_id: Any = None,
    url: Any = None,
) -> set[str]:
    keys: set[str] = set()
    video_id_text = str(video_id or "").strip()
    if video_id_text:
        keys.add(f"video:{video_id_text}")
    url_text = str(url or "").strip()
    if url_text:
        keys.add(f"url:{url_text}")
        url_video_id = youtube_video_id_from_url(url_text)
        if url_video_id:
            keys.add(f"video:{url_video_id}")
    return keys


def youtube_candidate_exclusion_keys(candidate: YouTubeCandidate) -> set[str]:
    return youtube_candidate_exclusion_keys_from_values(
        video_id=candidate.video_id,
        url=candidate.url,
    )


def youtube_candidate_is_excluded(candidate: YouTubeCandidate, excluded_keys: set[str]) -> bool:
    return bool(excluded_keys.intersection(youtube_candidate_exclusion_keys(candidate)))


def youtube_candidate_exclusion_debug_payload(
    candidate: YouTubeCandidate,
    excluded_keys: set[str],
) -> dict[str, Any]:
    matched_keys = sorted(excluded_keys.intersection(youtube_candidate_exclusion_keys(candidate)))
    return {
        "videoId": candidate.video_id,
        "url": candidate.url,
        "title": candidate.title,
        "channel": candidate.channel,
        "durationSeconds": candidate.duration_seconds,
        "matchedExclusionKeys": matched_keys,
        "skipReason": "previously_processed_candidate",
    }


RETRYABLE_CANDIDATE_FAILURE_TEXT_MARKERS = (
    "preview download failed",
    "download failed",
    "sign in to confirm",
    "not a bot",
    "use --cookies",
    "use --cookies-from-browser",
    "yt-dlp timed out",
    "timed out",
    "timeout",
    "http error 429",
    "too many requests",
)


def youtube_candidate_payload_contains_text_marker(value: Any, markers: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        text = value.casefold()
        return any(marker in text for marker in markers)
    if isinstance(value, dict):
        return any(
            youtube_candidate_payload_contains_text_marker(item, markers)
            for item in value.values()
        )
    if isinstance(value, list):
        return any(
            youtube_candidate_payload_contains_text_marker(item, markers)
            for item in value
        )
    return False


def youtube_candidate_payload_has_retryable_failure(node: dict[str, Any]) -> bool:
    return youtube_candidate_payload_contains_text_marker(
        node,
        RETRYABLE_CANDIDATE_FAILURE_TEXT_MARKERS,
    )


def youtube_candidate_payload_identity_keys(node: dict[str, Any]) -> set[str]:
    return youtube_candidate_exclusion_keys_from_values(
        video_id=node.get("videoId") or node.get("video_id"),
        url=node.get("url"),
    )


def youtube_candidate_payload_should_contribute_exclusion(node: dict[str, Any]) -> bool:
    if str(node.get("skipReason") or "").strip().casefold() == "previously_processed_candidate":
        return False
    if youtube_candidate_payload_has_retryable_failure(node):
        return False
    return bool(youtube_candidate_payload_identity_keys(node))


def collect_youtube_candidate_exclusion_keys_from_payload(payload: Any) -> set[str]:
    keys: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            identity_keys = youtube_candidate_payload_identity_keys(node)
            if identity_keys and youtube_candidate_payload_should_contribute_exclusion(node):
                keys.update(identity_keys)
                return
            if identity_keys:
                return
            for key, value in node.items():
                if key == "debugCandidates":
                    continue
                visit(value)
            return
        if isinstance(node, list):
            for item in node:
                visit(item)

    visit(payload)
    return keys


def load_youtube_candidate_exclusion_keys(
    *,
    candidates_json_paths: Iterable[Path] = (),
    video_ids: Iterable[str] = (),
    urls: Iterable[str] = (),
) -> tuple[str, ...]:
    keys: set[str] = set()
    for video_id in video_ids:
        keys.update(youtube_candidate_exclusion_keys_from_values(video_id=video_id))
    for url in urls:
        keys.update(youtube_candidate_exclusion_keys_from_values(url=url))
    for path in candidates_json_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        keys.update(collect_youtube_candidate_exclusion_keys_from_payload(payload))
    return tuple(sorted(keys))


@dataclass(frozen=True)
class YouTubeRankingSettings:
    results_per_query: int = 100
    youtube_search_empty_retries: int = 5
    youtube_cookies: Path | None = None
    youtube_preview_cache_dir: Path | None = None
    excluded_candidate_keys: tuple[str, ...] = ()
    max_candidates: int = 8
    candidate_review_batch_size: int | None = 12
    candidate_review_target_suitable_count: int = 1
    min_duration_seconds: int = 0
    max_duration_seconds: int = 120
    single_exercise_name_query: bool = False
    use_deepseek_query_planner: bool = False
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_max_queries: int = 4
    deepseek_timeout_seconds: float = 60.0
    use_llama_cpp_query_planner: bool = False
    rank_with_vision: bool = False
    exercise_name_rewrite_enabled: bool = True
    exercise_motion_contract_enabled: bool = True
    semantic_gate_enabled: bool = False
    semantic_gate_candidates_per_exercise: int | None = 24
    semantic_gate_max_candidates_per_exercise: int | None = 24
    semantic_gate_min_score: float = 0.55
    semantic_gate_duration_rank_weight: float = SEMANTIC_GATE_DURATION_RANK_DEFAULT_WEIGHT
    semantic_gate_llm_workers: int | None = None
    pose_prefilter_enabled: bool = False
    pose_prefilter_model: str = "yolo26x-pose.pt"
    pose_prefilter_candidates_per_exercise: int | None = None
    pose_prefilter_sample_fps: float = 8.0
    pose_prefilter_max_seconds: float = 32.0
    pose_prefilter_scan_strategy: str = "spread"
    pose_prefilter_window_seconds: float = 8.0
    pose_prefilter_overlap_seconds: float = 4.0
    pose_prefilter_min_score: float = 0.45
    pose_prefilter_min_keypoint_confidence: float = 0.35
    pose_prefilter_min_body_scale: float = 0.18
    pose_prefilter_workers: int = 1
    pose_prefilter_device: str = "cuda"
    pose_prefilter_batch_size: int = 16
    vision_candidates_per_exercise: int = 8
    vision_frames_per_candidate: int | None = 6
    vision_chunk_seconds: float | None = None
    vision_chunk_overlap_seconds: float | None = None
    vision_max_chunks_per_candidate: int | None = None
    vision_adaptive_chunk_review: bool = True
    vision_initial_chunks_per_candidate: int = 3
    vision_expand_chunks_per_candidate: int = 5
    vision_motion_scan_sample_fps: float = 0.5
    vision_motion_scan_max_seconds: float = 90.0
    vision_contact_sheet_columns: int = 4
    vision_contact_sheet_tile_width: int = 320
    vision_contact_sheet_frames_per_sheet: int = 8
    vision_contact_sheet_jpeg_quality: int = 82
    vision_download_workers: int = 8
    vision_llm_workers: int = 4
    vision_model: str = "gemma-4-E4B-it"
    llama_cpp_base_url: str | None = "http://127.0.0.1:8090"
    llama_cpp_model: str = DEFAULT_LLAMA_CPP_MODEL
    llama_cpp_server_command: str | None = None
    llama_cpp_mmproj: str | None = DEFAULT_LLAMA_CPP_MMPROJ
    llama_cpp_mtp_model: str | None = DEFAULT_LLAMA_CPP_MTP_MODEL
    llama_cpp_spec_draft_n_max: int = DEFAULT_LLAMA_CPP_SPEC_DRAFT_N_MAX
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
    llama_cpp_image_min_tokens: int | None = DEFAULT_LLAMA_CPP_IMAGE_MIN_TOKENS
    llama_cpp_image_max_tokens: int | None = DEFAULT_LLAMA_CPP_IMAGE_MAX_TOKENS
    llama_cpp_mtmd_batch_max_tokens: int | None = DEFAULT_LLAMA_CPP_MTMD_BATCH_MAX_TOKENS
    llama_cpp_auto_start_server: bool = True
    keep_llama_cpp_server: bool = False
    llama_cpp_server_startup_timeout_seconds: float = 180.0
    llama_cpp_request_timeout_seconds: float = 240.0
    text_llama_cpp_model: str | None = DEFAULT_TEXT_LLAMA_CPP_MODEL
    text_llama_cpp_mmproj: str | None = DEFAULT_TEXT_LLAMA_CPP_MMPROJ
    exercise_contract_llama_cpp_model: str | None = None
    exercise_contract_llama_cpp_mmproj: str | None = None
    include_disabled: bool = False
    vision_early_stop_score: float = 0.95

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "semantic_gate_duration_rank_weight",
            clamp_score(self.semantic_gate_duration_rank_weight),
        )
        if self.pose_prefilter_enabled:
            object.__setattr__(
                self,
                "pose_prefilter_device",
                normalize_yolo_cuda_device(self.pose_prefilter_device),
            )

    def resolved_candidate_review_batch_size(self) -> int:
        if self.candidate_review_batch_size is not None:
            return max(1, self.candidate_review_batch_size)
        return max(1, self.max_candidates)

    def resolved_candidate_review_target_suitable_count(self) -> int:
        return max(1, self.candidate_review_target_suitable_count)

    def resolved_pose_prefilter_candidates_per_exercise(self) -> int:
        if self.pose_prefilter_candidates_per_exercise is not None:
            return max(1, self.pose_prefilter_candidates_per_exercise)
        return max(self.max_candidates, self.vision_candidates_per_exercise)

    def resolved_semantic_gate_candidates_per_exercise(self) -> int:
        if self.semantic_gate_candidates_per_exercise is not None:
            return max(1, self.semantic_gate_candidates_per_exercise)
        if self.pose_prefilter_enabled:
            return max(
                self.resolved_pose_prefilter_candidates_per_exercise(),
                self.max_candidates,
                self.vision_candidates_per_exercise,
            )
        return max(self.max_candidates, self.vision_candidates_per_exercise)

    def resolved_semantic_gate_max_candidates_per_exercise(self) -> int:
        batch_size = self.resolved_semantic_gate_candidates_per_exercise()
        if self.semantic_gate_max_candidates_per_exercise is not None:
            return max(batch_size, self.semantic_gate_max_candidates_per_exercise)
        return batch_size

    def resolved_semantic_gate_target_pass_count(self) -> int:
        review_target = self.resolved_candidate_review_target_suitable_count()
        if self.pose_prefilter_enabled:
            return max(1, min(self.resolved_pose_prefilter_candidates_per_exercise(), review_target))
        if self.rank_with_vision:
            return max(1, min(max(1, self.vision_candidates_per_exercise), review_target))
        return max(1, min(max(1, self.max_candidates), review_target))

    def resolved_semantic_gate_llm_workers(self) -> int:
        if self.semantic_gate_llm_workers is not None:
            return max(1, self.semantic_gate_llm_workers)
        return max(1, min(self.vision_llm_workers, 4))


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
    exercise_motion_contract: dict[str, Any] | None = None
    video_path: Path | None = None
    review_windows: list[PreparedReviewWindow] = field(default_factory=list)
    frames_per_chunk: int = 0
    preview_preparation_elapsed_seconds: float = 0.0
    preview_download_elapsed_seconds: float = 0.0
    motion_scan_elapsed_seconds: float = 0.0
    window_planning_elapsed_seconds: float = 0.0
    artifact_dir: Path | None = None
    rendered_chunk_cache: dict[int, tuple[list[Path], float]] = field(default_factory=dict)

    def close(self) -> None:
        self.temp_dir.cleanup()


def write_prepared_vision_critical_vlm_error(
    prepared: PreparedVisionReview,
    exc: BaseException,
    *,
    context: dict[str, Any] | None = None,
) -> Path | None:
    critical = add_vlm_context(exc, **(context or {}))
    if critical is None:
        return None
    output_dir = prepared.artifact_dir or Path(prepared.temp_dir.name)
    report_path = output_dir / "vlm_critical_error.json"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "error": vlm_error_payload(critical),
                    "context": context or {},
                    "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        critical.add_details(criticalErrorReportPath=str(report_path))
        return report_path
    except Exception as report_exc:
        critical.add_details(criticalErrorReportWriteError=str(report_exc))
        return None


def prepared_vision_review_artifact_dir(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> Path | None:
    if settings.youtube_preview_cache_dir is None:
        return None
    return (
        settings.youtube_preview_cache_dir.expanduser().resolve()
        / "vision-review"
        / slugify(exercise.name)
        / youtube_preview_cache_stem(candidate.url)
    )


SearchFn = Callable[[str, int], list[YouTubeCandidate]]
QueryPlannerFn = Callable[[ExerciseEntry, list[str], YouTubeRankingSettings], list[str]]
ExerciseNameRewriteFn = Callable[
    [ExerciseEntry, YouTubeRankingSettings, Any | None],
    tuple[ExerciseEntry, dict[str, Any]],
]
VisionRankResult = tuple[float, list[str]] | tuple[float, list[str], dict[str, Any] | None]
VisionRankerFn = Callable[[ExerciseEntry, YouTubeCandidate, YouTubeRankingSettings], VisionRankResult]
PoseRankResult = tuple[float, list[str], dict[str, Any] | None]
PoseRankerFn = Callable[[ExerciseEntry, YouTubeCandidate, YouTubeRankingSettings], PoseRankResult]
SemanticGateResult = tuple[float, list[str], dict[str, Any] | None]
SemanticGateFn = Callable[[ExerciseEntry, YouTubeCandidate, YouTubeRankingSettings], SemanticGateResult]
ExerciseMotionContractProviderFn = Callable[[ExerciseEntry, YouTubeRankingSettings], dict[str, Any] | str | None]


class YouTubeSearchError(RuntimeError):
    """A hard YouTube search failure that should not be treated as an empty result."""

    def __init__(self, query: str, message: str) -> None:
        self.query = query
        self.message = message
        super().__init__(f"YouTube search failed for query {query!r}: {message}")


@dataclass(frozen=True)
class CandidateReviewPassResult:
    ranked: list[YouTubeCandidate]
    debug_candidates_by_key: dict[str, YouTubeCandidate]
    semantic_elapsed_seconds: float = 0.0
    pose_elapsed_seconds: float = 0.0
    vision_elapsed_seconds: float = 0.0
    review_batches: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class YouTubeSearchPassResult:
    by_key: dict[str, YouTubeCandidate]
    search_errors: list[dict[str, Any]]
    search_attempts: list[dict[str, Any]]
    elapsed_seconds: float
    new_candidate_count: int
    excluded_candidate_count: int = 0


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

YOUTUBE_QUERY_EQUIPMENT_PREFIXES = (
    "barbell",
    "dumbbell",
    "kettlebell",
    "cable",
    "machine",
    "smith machine",
)
YOUTUBE_QUERY_LOAD_PREFIXES = (
    "weighted",
    "loaded",
    "bodyweight",
    "body weight",
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
    "pose_cropped_body": (0.67, "borderline_full_body_frame_source_cap"),
}
YOUTUBE_FAILURE_SEARCH_EXPANSION_MIN_INCREMENT = 10
YOUTUBE_FAILURE_SEARCH_EXPANSION_MULTIPLIER = 2
YOUTUBE_FAILURE_SEARCH_EXPANSION_MAX_RESULTS_PER_QUERY = 100
REST_COMPONENT_TYPES = {"rest", "recovery", "break"}
NON_MOTION_EXERCISE_TYPES = {"countdown"}
EQUIPMENT_COLLECTION_KEYS = {
    "equipment",
    "equipments",
    "availableequipment",
    "availableequipments",
    "equipmentlist",
}
EQUIPMENT_PREFIX_BY_TYPE = {
    "barbell": "Barbell",
    "olympicbarbell": "Barbell",
    "ezbar": "EZ Bar",
    "ezcurlbar": "EZ Bar",
    "dumbbell": "Dumbbell",
    "dumbbells": "Dumbbell",
    "kettlebell": "Kettlebell",
    "kettlebells": "Kettlebell",
    "cable": "Cable",
    "cables": "Cable",
    "plateloadedcable": "Cable",
    "machine": "Machine",
    "smithmachine": "Smith Machine",
    "trapbar": "Trap Bar",
    "hexbar": "Trap Bar",
    "resistanceband": "Band",
    "resistancebands": "Band",
    "band": "Band",
    "bands": "Band",
    "weightvest": "Weighted",
    "weightedvest": "Weighted",
}
BODYWEIGHT_EQUIPMENT_NAMES = {
    "bodyweight",
    "body weight",
    "none",
    "no equipment",
    "unloaded",
}
EXERCISE_NAME_REWRITE_RULES: dict[str, tuple[str, str]] = {}
EXERCISE_NAME_REWRITE_EQUIPMENT_PREFIXES = (
    *YOUTUBE_QUERY_EQUIPMENT_PREFIXES,
    "ez bar",
    "trap bar",
    "weighted",
)
EXERCISE_NAME_REWRITE_EQUIPMENT_DISPLAY = {
    "barbell": "Barbell",
    "dumbbell": "Dumbbell",
    "kettlebell": "Kettlebell",
    "cable": "Cable",
    "machine": "Machine",
    "smith machine": "Smith Machine",
    "ez bar": "EZ Bar",
    "trap bar": "Trap Bar",
    "weighted": "Weighted",
}


def load_workout_plan_exercises(
    plan_path: Path,
    *,
    include_disabled: bool = False,
    equipment_path: Path | None = None,
) -> list[ExerciseEntry]:
    payload = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    equipment_payload = (
        json.loads(equipment_path.read_text(encoding="utf-8-sig"))
        if equipment_path is not None
        else None
    )
    return extract_workout_plan_exercises(
        payload,
        include_disabled=include_disabled,
        equipment_payload=equipment_payload,
    )


def extract_workout_plan_exercises(
    payload: Any,
    *,
    include_disabled: bool = False,
    equipment_payload: Any | None = None,
) -> list[ExerciseEntry]:
    equipment_by_id = extract_equipment_lookup(payload)
    if equipment_payload is not None:
        equipment_by_id.update(extract_equipment_lookup(equipment_payload, include_root_records=True))
    raw_entries: list[tuple[str | None, str, str]] = []

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
            source_name = extract_source_exercise_name(node) or name
            equipment_qualified_name = (
                extract_equipment_qualified_exercise_name(node)
                or equipment_qualified_exercise_name(
                    name,
                    extract_exercise_equipment_name(node, equipment_by_id),
                )
            )
            raw_entries.append(
                (
                    extract_exercise_id(node),
                    source_name,
                    equipment_qualified_name,
                )
            )

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
    for source_id, source_name, equipment_qualified_name in raw_entries:
        name = equipment_qualified_name
        normalized = normalize_exercise_name(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        entries.append(
            ExerciseEntry(
                exercise_id=source_id or f"EXERCISE_{len(entries)}",
                name=name.strip(),
                slug=slugify(name),
                source_name=source_name.strip(),
                equipment_qualified_name=equipment_qualified_name.strip(),
                name_rewrite_reason=None,
            )
        )
    return entries


def extract_equipment_lookup(payload: Any, *, include_root_records: bool = False) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}

    def add_equipment_record(record: Any) -> None:
        if not isinstance(record, dict):
            return
        equipment_id = extract_equipment_record_id(record)
        if equipment_id is None:
            return
        lookup[equipment_id] = record

    def add_root_equipment_records(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                add_equipment_record(child)
            return
        if not isinstance(node, dict):
            return
        add_equipment_record(node)
        for key, child in node.items():
            if isinstance(child, dict):
                record = child
                if extract_equipment_record_id(record) is None:
                    record = {"id": str(key), **record}
                add_equipment_record(record)
            elif isinstance(child, list):
                for item in child:
                    add_equipment_record(item)

    def visit_container(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit_container(child)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            normalized_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
            if normalized_key in EQUIPMENT_COLLECTION_KEYS:
                if isinstance(value, dict):
                    add_equipment_record(value)
                    for child_key, child in value.items():
                        if isinstance(child, dict) and extract_equipment_record_id(child) is None:
                            child = {"id": str(child_key), **child}
                        add_equipment_record(child)
                elif isinstance(value, list):
                    for child in value:
                        add_equipment_record(child)
        for key in ("WorkoutStore", "workoutStore", "store", "data", "plan", "metadata"):
            if key in node:
                visit_container(node[key])

    if include_root_records:
        add_root_equipment_records(payload)
    visit_container(payload)
    return lookup


def extract_equipment_record_id(record: dict[str, Any]) -> str | None:
    for key in ("id", "equipmentId", "equipment_id", "uuid"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_exercise_equipment_name(
    node: dict[str, Any],
    equipment_by_id: dict[str, dict[str, Any]],
) -> str | None:
    for key in ("equipmentName", "equipment_name", "equipmentDisplayName", "primaryEquipmentName"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    equipment = node.get("equipment")
    if isinstance(equipment, dict):
        equipment_label = extract_equipment_record_search_label(equipment)
        if equipment_label:
            return equipment_label
    equipment_id = extract_exercise_equipment_id(node)
    if equipment_id is not None:
        equipment_record = equipment_by_id.get(equipment_id)
        if equipment_record is not None:
            equipment_label = extract_equipment_record_search_label(equipment_record)
            if equipment_label:
                return equipment_label
    exercise = node.get("exercise")
    if isinstance(exercise, dict):
        return extract_exercise_equipment_name(exercise, equipment_by_id)
    return None


def extract_exercise_equipment_id(node: dict[str, Any]) -> str | None:
    for key in ("equipmentId", "equipment_id", "primaryEquipmentId"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exercise = node.get("exercise")
    if isinstance(exercise, dict):
        return extract_exercise_equipment_id(exercise)
    return None


def extract_equipment_record_search_label(record: dict[str, Any]) -> str | None:
    for key in ("type", "equipmentType", "kind"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            label = normalize_equipment_type_search_prefix(value)
            if label:
                return label
    for key in ("name", "label", "displayName"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            label = normalize_equipment_search_prefix(value)
            if label:
                return label
    return None


def normalize_equipment_type_search_prefix(equipment_type: str | None) -> str | None:
    if equipment_type is None:
        return None
    cleaned = re.sub(r"[_-]+", " ", str(equipment_type)).strip()
    if not cleaned:
        return None
    normalized = normalize_exercise_name(cleaned)
    compact = re.sub(r"[^a-z0-9]+", "", cleaned.lower())
    if normalized in BODYWEIGHT_EQUIPMENT_NAMES or compact in {"bodyweight", "none", "noequipment"}:
        return None
    return EQUIPMENT_PREFIX_BY_TYPE.get(compact) or EQUIPMENT_PREFIX_BY_TYPE.get(normalized.replace(" ", ""))


def equipment_qualified_exercise_name(name: str, equipment_name: str | None) -> str:
    exercise_name = name.strip()
    equipment_prefix = normalize_equipment_search_prefix(equipment_name)
    if not exercise_name or not equipment_prefix:
        return exercise_name
    exercise_normalized = normalize_exercise_name(exercise_name)
    exercise_terms = set(exercise_normalized.split())
    if any(
        exercise_normalized.startswith(f"{prefix} ")
        or exercise_normalized == prefix
        or prefix in exercise_terms
        for prefix in equipment_prefix_normalized_variants(equipment_prefix)
    ):
        return exercise_name
    return f"{equipment_prefix} {exercise_name}"


def normalize_equipment_search_prefix(equipment_name: str | None) -> str | None:
    if equipment_name is None:
        return None
    cleaned = re.sub(r"[_-]+", " ", str(equipment_name)).strip()
    if not cleaned:
        return None
    normalized = normalize_exercise_name(cleaned)
    compact = re.sub(r"[^a-z0-9]+", "", cleaned.lower())
    if normalized in BODYWEIGHT_EQUIPMENT_NAMES or compact in {"bodyweight", "none", "noequipment"}:
        return None
    mapped = EQUIPMENT_PREFIX_BY_TYPE.get(compact)
    if mapped:
        return mapped
    mapped = EQUIPMENT_PREFIX_BY_TYPE.get(normalized.replace(" ", ""))
    if mapped:
        return mapped
    return " ".join(part.capitalize() for part in normalized.split())


def equipment_prefix_normalized_variants(equipment_prefix: str) -> set[str]:
    normalized = normalize_exercise_name(equipment_prefix)
    variants = {normalized}
    if normalized.endswith("s"):
        variants.add(normalized[:-1])
    else:
        variants.add(f"{normalized}s")
    if normalized == "dumbbell":
        variants.add("db")
    if normalized == "barbell":
        variants.add("bb")
    if normalized == "weighted":
        variants.update({"weight vest", "weighted vest", "weightvest"})
    return {variant for variant in variants if variant}


def rewrite_equipment_qualified_exercise_name(name: str) -> tuple[str, str | None]:
    exercise_name = re.sub(r"\s+", " ", str(name)).strip()
    if not exercise_name:
        return exercise_name, None
    normalized = normalize_exercise_name(exercise_name)
    replacement = EXERCISE_NAME_REWRITE_RULES.get(normalized)
    if replacement is not None:
        rewritten_name, reason = replacement
        return rewritten_name, reason
    for prefix in EXERCISE_NAME_REWRITE_EQUIPMENT_PREFIXES:
        normalized_prefix = normalize_exercise_name(prefix)
        if not normalized.startswith(f"{normalized_prefix} "):
            continue
        base_exercise = normalized[len(normalized_prefix) + 1 :].strip()
        replacement = EXERCISE_NAME_REWRITE_RULES.get(base_exercise)
        if replacement is None:
            continue
        rewritten_base, reason = replacement
        display_prefix = EXERCISE_NAME_REWRITE_EQUIPMENT_DISPLAY.get(
            normalized_prefix,
            " ".join(part.capitalize() for part in normalized_prefix.split()),
        )
        return f"{display_prefix} {rewritten_base}", reason
    return exercise_name, None


def resolve_exercise_name_rewrite(
    exercise: ExerciseEntry,
    settings: YouTubeRankingSettings,
    ranker: Any | None,
) -> tuple[ExerciseEntry, dict[str, Any]]:
    text_settings = text_llama_cpp_settings(settings)
    input_name = (exercise.equipment_qualified_name or exercise.name).strip()
    payload: dict[str, Any] = {
        "enabled": settings.exercise_name_rewrite_enabled,
        "backend": None,
        "status": "skipped" if not settings.exercise_name_rewrite_enabled else "pending",
        "sourceExerciseName": exercise.source_name,
        "equipmentQualifiedExerciseName": exercise.equipment_qualified_name,
        "inputExerciseName": input_name,
        "applied": False,
        "rewrittenExerciseName": exercise.name,
        "reason": None,
        "confidence": None,
    }
    if not settings.exercise_name_rewrite_enabled:
        return exercise, payload

    fallback_name, fallback_reason = rewrite_equipment_qualified_exercise_name(input_name)
    if isinstance(ranker, LlamaCppVisionRanker):
        payload["backend"] = "llama-cpp"
        payload["model"] = text_settings.llama_cpp_model
        try:
            from exercise_motion_pkg.segment_detection import extract_json_object

            caption_kwargs: dict[str, Any] = {
                "frame_paths": [],
                "prompt": build_exercise_name_rewrite_prompt(exercise),
                "max_tokens": capped_llama_cpp_text_tokens(text_settings),
            }
            if callable_accepts_keyword(ranker.client.caption_images, "disable_reasoning"):
                caption_kwargs["disable_reasoning"] = True
            if callable_accepts_keyword(ranker.client.caption_images, "request_timeout_seconds"):
                caption_kwargs["request_timeout_seconds"] = max(
                    1.0,
                    float(text_settings.llama_cpp_request_timeout_seconds),
                )
            raw = ranker.client.caption_images(**caption_kwargs)
            model_payload = extract_json_object(raw)
            if not isinstance(model_payload, dict):
                raise RuntimeError("exercise-name rewrite returned no JSON object.")
            rewritten_name, confidence, reason, rewrite_needed = normalize_exercise_name_rewrite_payload(
                model_payload,
                exercise=exercise,
            )
            payload.update(
                {
                    "status": "completed",
                    "modelPayload": {
                        "canonicalExerciseName": rewritten_name,
                        "rewriteNeeded": rewrite_needed,
                        "confidence": confidence,
                        "reason": reason,
                    },
                    "confidence": confidence,
                    "reason": reason,
                }
            )
            if rewrite_needed and confidence >= 0.70 and normalize_exercise_name(rewritten_name) != normalize_exercise_name(input_name):
                rewritten_name = preserve_rewrite_equipment_prefix(input_name, rewritten_name)
                return apply_exercise_name_rewrite(
                    exercise,
                    rewritten_name,
                    reason or "llm_canonical_movement_name",
                    payload,
                    source="llm",
                )
            payload["status"] = "kept"
            payload["rewrittenExerciseName"] = exercise.name
            payload["applied"] = False
            return exercise, payload
        except Exception as exc:
            if is_critical_vlm_interaction_error(exc):
                add_vlm_context(
                    exc,
                    stage="exercise_name_rewrite",
                    exerciseName=exercise.name,
                    inputExerciseName=input_name,
                    model=text_settings.llama_cpp_model,
                )
                raise
            payload.update(
                {
                    "status": "failed",
                    "error": truncate_text(str(exc), 240),
                }
            )
    else:
        payload["backend"] = "deterministic-fallback"
        payload["status"] = "llm_unavailable"

    if fallback_reason and normalize_exercise_name(fallback_name) != normalize_exercise_name(input_name):
        return apply_exercise_name_rewrite(
            exercise,
            fallback_name,
            fallback_reason,
            payload,
            source="deterministic_fallback",
        )
    payload["status"] = "kept" if payload.get("status") not in {"failed", "llm_unavailable"} else payload["status"]
    payload["rewrittenExerciseName"] = exercise.name
    return exercise, payload


def build_exercise_name_rewrite_prompt(exercise: ExerciseEntry) -> str:
    source_name = exercise.source_name or exercise.name
    equipment_qualified_name = exercise.equipment_qualified_name or exercise.name
    return (
        "Rewrite a workout-plan exercise target into the common English movement name used for YouTube exercise demos.\n"
        "Only rewrite when the target is ambiguous, muscle-group-only, shorthand, or not the common movement name.\n"
        "If the target is already a concrete exercise movement, keep it unchanged.\n"
        "Preserve all defining qualifiers: equipment, loaded/unloaded, stance, support, side, incline/decline, grip, and unilateral terms.\n"
        "Do not add a variant such as seated, machine, smith-machine, assisted, banded, single-leg, or grip-specific unless it is already implied by the input.\n"
        "If unsure, set rewriteNeeded false and return the input name.\n"
        "Muscle-group-only targets should be rewritten to a common movement name only when the movement identity is unambiguous in gym context.\n"
        "When the equipment-qualified name is a more precise version of the source name, prefer that precise name without adding unrelated qualifiers.\n"
        "Return JSON only with this schema: "
        "{\"canonicalExerciseName\": string, \"rewriteNeeded\": boolean, \"confidence\": number, \"reason\": string}.\n"
        f"sourceExerciseName: {source_name}\n"
        f"equipmentQualifiedExerciseName: {equipment_qualified_name}\n"
    )


def normalize_exercise_name_rewrite_payload(
    payload: dict[str, Any],
    *,
    exercise: ExerciseEntry,
) -> tuple[str, float, str | None, bool]:
    input_name = exercise.equipment_qualified_name or exercise.name
    canonical = payload.get("canonicalExerciseName")
    if not isinstance(canonical, str) or not canonical.strip():
        canonical = payload.get("canonicalName")
    if not isinstance(canonical, str) or not canonical.strip():
        canonical = input_name
    canonical = sanitize_rewritten_exercise_name(canonical) or input_name
    confidence = coerce_float(payload.get("confidence"))
    if confidence is None:
        confidence = coerce_float(payload.get("score"))
    confidence = clamp_score(0.0 if confidence is None else confidence)
    rewrite_needed = bool(payload.get("rewriteNeeded"))
    reason = cleaned_contract_string(payload.get("reason"), 180)
    return canonical, confidence, reason, rewrite_needed


def sanitize_rewritten_exercise_name(value: str) -> str | None:
    text = re.sub(r"\s+", " ", str(value)).strip().strip("'\"")
    if not text or len(text) > 90:
        return None
    if "http://" in text.lower() or "https://" in text.lower():
        return None
    normalized = normalize_exercise_name(text)
    if not normalized or normalized in {"unknown", "not sure", "n a", "none"}:
        return None
    return " ".join(part for part in text.split())


def apply_exercise_name_rewrite(
    exercise: ExerciseEntry,
    rewritten_name: str,
    reason: str,
    payload: dict[str, Any],
    *,
    source: str,
) -> tuple[ExerciseEntry, dict[str, Any]]:
    cleaned_name = sanitize_rewritten_exercise_name(rewritten_name) or exercise.name
    rewritten = dataclass_replace(
        exercise,
        name=cleaned_name,
        slug=slugify(cleaned_name),
        name_rewrite_reason=reason,
    )
    payload.update(
        {
            "status": "rewritten",
            "source": source,
            "applied": True,
            "rewrittenExerciseName": cleaned_name,
            "reason": reason,
        }
    )
    return rewritten, payload


def preserve_rewrite_equipment_prefix(input_name: str, rewritten_name: str) -> str:
    normalized_input = normalize_exercise_name(input_name)
    normalized_rewrite = normalize_exercise_name(rewritten_name)
    for prefix in EXERCISE_NAME_REWRITE_EQUIPMENT_PREFIXES:
        normalized_prefix = normalize_exercise_name(prefix)
        if not normalized_input.startswith(f"{normalized_prefix} "):
            continue
        variants = equipment_prefix_normalized_variants(normalized_prefix)
        variants.add(normalized_prefix)
        if any(
            normalized_rewrite == variant or normalized_rewrite.startswith(f"{variant} ") or f" {variant} " in f" {normalized_rewrite} "
            for variant in variants
        ):
            return rewritten_name
        display_prefix = EXERCISE_NAME_REWRITE_EQUIPMENT_DISPLAY.get(
            normalized_prefix,
            " ".join(part.capitalize() for part in normalized_prefix.split()),
        )
        return f"{display_prefix} {rewritten_name}"
    return rewritten_name


def extract_exercise_name(node: dict[str, Any]) -> str | None:
    for key in ("exerciseName", "name", "title"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exercise = node.get("exercise")
    if isinstance(exercise, dict):
        return extract_exercise_name(exercise)
    return None


def extract_source_exercise_name(node: dict[str, Any]) -> str | None:
    for key in ("sourceExerciseName", "originalExerciseName", "planExerciseName"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exercise = node.get("exercise")
    if isinstance(exercise, dict):
        return extract_source_exercise_name(exercise)
    return None


def extract_equipment_qualified_exercise_name(node: dict[str, Any]) -> str | None:
    for key in ("equipmentQualifiedExerciseName", "qualifiedExerciseName"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exercise = node.get("exercise")
    if isinstance(exercise, dict):
        return extract_equipment_qualified_exercise_name(exercise)
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
        f"{base_term} shorts{exclusions}",
        f"{base_term} #shorts{exclusions}",
        f"{base_term} full rep shorts{exclusions}",
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


def build_youtube_queries_with_contract_aliases(
    exercise_name: str,
    contract: dict[str, Any] | None,
) -> list[str]:
    aliases = youtube_query_aliases_from_contract(contract)
    if not aliases:
        return build_youtube_queries(exercise_name)
    queries = build_youtube_queries(exercise_name)
    for alias in aliases:
        alias_term = quote_youtube_search_term(alias)
        queries.extend(
            [
                f"{alias_term} exercise demonstration",
                f"{alias_term} exercise demo full rep",
                f"{alias_term} side view exercise",
            ]
        )
    return merge_youtube_queries(queries)


def build_youtube_search_expansion_queries(
    exercise_name: str,
    contract: dict[str, Any] | None,
    *,
    existing_queries: Iterable[str],
    limit: int = 12,
) -> list[str]:
    aliases = [exercise_name, *youtube_query_aliases_from_contract(contract), *generic_youtube_query_aliases(exercise_name)]
    queries: list[str] = []
    for alias in aliases:
        alias_term = quote_youtube_search_term(alias)
        queries.extend(
            [
                f"{alias_term} strict form full rep",
                f"{alias_term} full range of motion exercise",
                f"{alias_term} continuous reps side angle",
                f"{alias_term} full body exercise demo",
            ]
        )
    existing_keys = {
        normalize_search_query(strip_youtube_negative_search_terms(query)).casefold()
        for query in existing_queries
    }
    return [
        query
        for query in merge_youtube_queries(queries, limit=limit + len(existing_keys))
        if query.casefold() not in existing_keys
    ][:limit]


def youtube_query_aliases_from_contract(contract: dict[str, Any] | None) -> list[str]:
    if not exercise_motion_contract_is_usable(contract):
        return []
    return cleaned_contract_string_list(
        contract.get("youtubeQueryAliases"),
        limit=5,
        item_limit=80,
    )


def quote_youtube_search_term(term: str) -> str:
    normalized = re.sub(r"\s+", " ", str(term)).strip()
    if not normalized:
        return ""
    escaped = normalized.replace('"', "")
    return f'"{escaped}"'


def generic_youtube_query_aliases(exercise_name: str) -> list[str]:
    normalized = normalize_exercise_name(exercise_name)
    aliases: list[str] = []
    for prefix in (*YOUTUBE_QUERY_EQUIPMENT_PREFIXES, *YOUTUBE_QUERY_LOAD_PREFIXES):
        normalized_prefix = normalize_exercise_name(prefix)
        if normalized == normalized_prefix:
            continue
        if normalized.startswith(f"{normalized_prefix} "):
            stripped = normalized[len(normalized_prefix) + 1 :].strip()
            if stripped:
                aliases.append(stripped.title())
    aliases.extend(common_youtube_movement_aliases(normalized))
    return aliases


def common_youtube_movement_aliases(normalized_exercise_name: str) -> list[str]:
    aliases: list[str] = []
    tokens = normalized_exercise_name.split()
    token_set = set(tokens)
    if "cable" in token_set and "crunch" in token_set and ("ab" in token_set or "abs" in token_set):
        aliases.extend(["Cable Crunch", "Kneeling Cable Crunch", "Cable Rope Crunch"])
    if "ab" in token_set and "wheel" in token_set:
        aliases.extend(["Ab Wheel", "Ab Wheel Rollout"])
    if "nordic" in token_set and "curl" in token_set:
        aliases.append("Nordic Curl")
    if "bent" in token_set and "over" in token_set and ("raise" in token_set or "raises" in token_set):
        aliases.extend(
            [
                "Bent Over Rear Delt Raise",
                "Bent Over Reverse Fly",
                "Dumbbell Reverse Fly",
                "Rear Delt Fly",
            ]
        )
    return aliases


def build_youtube_query_exclusion_suffix(exercise_name: str) -> str:
    return ""


def merge_youtube_queries(queries: Iterable[str], *, limit: int | None = None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = normalize_search_query(strip_youtube_negative_search_terms(query))
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
    return normalize_search_query(strip_youtube_negative_search_terms(query))


def strip_youtube_negative_search_terms(query: str) -> str:
    without_quoted_negatives = re.sub(r'(?:(?<=\s)|^)-"[^"]+"', " ", str(query))
    without_negatives = re.sub(r"(?:(?<=\s)|^)-\S+", " ", without_quoted_negatives)
    return re.sub(r"\s+", " ", without_negatives).strip()


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
        self.settings = text_llama_cpp_settings(settings)
        self._shared_ranker = shared_ranker if shared_ranker_matches_settings(shared_ranker, self.settings) else None
        self._owned_ranker: LlamaCppVisionRanker | None = None
        self._ranker_lock = threading.Lock()

    @property
    def _ranker(self) -> Any:
        ranker = self._shared_ranker or self._owned_ranker
        if ranker is None and self._shared_ranker is None:
            with self._ranker_lock:
                if self._owned_ranker is None:
                    self._owned_ranker = LlamaCppVisionRanker(self.settings)
            ranker = self._owned_ranker
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
        caption_kwargs: dict[str, Any] = {
            "frame_paths": [],
            "prompt": prompt,
            "max_tokens": capped_llama_cpp_text_tokens(self.settings, cap=QUERY_PLANNER_LLAMA_MAX_TOKENS),
        }
        if callable_accepts_keyword(self._ranker.client.caption_images, "disable_reasoning"):
            caption_kwargs["disable_reasoning"] = True
        if callable_accepts_keyword(self._ranker.client.caption_images, "request_timeout_seconds"):
            caption_kwargs["request_timeout_seconds"] = max(
                1.0,
                float(self.settings.llama_cpp_request_timeout_seconds),
            )
        raw = self._ranker.client.caption_images(**caption_kwargs)
        return parse_youtube_query_planner_payload(
            raw,
            exercise_name=exercise.name,
            max_queries=settings.deepseek_max_queries,
        )

    def close(self) -> None:
        if self._owned_ranker is not None:
            self._owned_ranker.close()
            self._owned_ranker = None


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
        "Do not use '-' exclusion operators or any other negative YouTube search terms.\n"
        "Prefer exact quoted exercise names and exact common aliases. Avoid broad phrases that can match "
        "music, challenges, tutorials, commentary, or general workouts.\n"
        "If the target is a basic exercise name, generate queries for the basic/common version only. Do not add "
        "extra qualifier terms for grip, range, assistance, loading, machine/support style, angle, body position, "
        "side, limb count, tempo, or partial-only execution unless the target exercise already includes that qualifier.\n"
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
    query = normalize_search_query(strip_youtube_negative_search_terms(query))
    if not query:
        return []
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
    except subprocess.TimeoutExpired as exc:
        raise YouTubeSearchError(query, "yt-dlp timed out while searching YouTube.") from exc
    if completed.returncode != 0:
        error = truncate_text(completed.stderr or completed.stdout or "yt-dlp failed", 400)
        raise YouTubeSearchError(query, error)
    try:
        info = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise YouTubeSearchError(query, f"yt-dlp returned invalid JSON: {exc}") from exc
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
    pose_windows = [window for window in windows if window.source == "pose_prefilter"]
    motion_windows = [window for window in windows if window.source == "motion_interval"]
    coverage_windows = [
        window
        for window in windows
        if window.source not in {"pose_prefilter", "motion_interval"}
    ]
    selected = [*pose_windows[:max_windows]]
    remaining = max(0, max_windows - len(selected))
    selected.extend(motion_windows[:remaining])
    remaining = max(0, max_windows - len(selected))
    selected.extend(coverage_windows[:remaining])
    if len(selected) < max_windows:
        selected_keys = {(round(window.start_seconds, 3), round(window.end_seconds, 3)) for window in selected}
        selected.extend(
            window
            for window in windows
            if (round(window.start_seconds, 3), round(window.end_seconds, 3)) not in selected_keys
        )
    return reindex_review_windows(selected[:max_windows])


def resolved_vision_chunk_review_limit(settings: YouTubeRankingSettings) -> int | None:
    value = settings.vision_max_chunks_per_candidate
    if value is None or value <= 0:
        return None
    return max(1, value)


def review_window_source_for_motion_intervals(window: Any, motion_intervals: list[Any]) -> str:
    for interval in motion_intervals:
        overlap_start = max(float(window.start_seconds), float(interval.start_seconds))
        overlap_end = min(float(window.end_seconds), float(interval.end_seconds))
        if overlap_end > overlap_start:
            return "motion_interval"
    return "timeline_coverage"


def pose_prefilter_review_windows_for_candidate(
    candidate: YouTubeCandidate,
    *,
    duration_seconds: float,
) -> list[PreparedReviewWindow]:
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    pose_payload = payload.get("posePrefilter") if isinstance(payload, dict) else None
    if not isinstance(pose_payload, dict):
        return []
    valid_chunks = pose_payload.get("validChunks")
    if not isinstance(valid_chunks, list):
        return []
    windows: list[PreparedReviewWindow] = []
    seen: set[tuple[float, float]] = set()
    for item in valid_chunks:
        if not isinstance(item, dict):
            continue
        start = coerce_float(item.get("startSeconds"))
        end = coerce_float(item.get("endSeconds"))
        if start is None or end is None:
            continue
        start = max(0.0, min(duration_seconds, start))
        end = max(0.0, min(duration_seconds, end))
        if end <= start:
            continue
        key = (round(start, 3), round(end, 3))
        if key in seen:
            continue
        seen.add(key)
        windows.append(
            PreparedReviewWindow(
                index=len(windows),
                start_seconds=start,
                end_seconds=end,
                source="pose_prefilter",
            )
        )
    return windows


def prepend_preferred_review_windows(
    preferred: list[PreparedReviewWindow],
    windows: list[PreparedReviewWindow],
) -> list[PreparedReviewWindow]:
    if not preferred:
        return reindex_review_windows(windows)
    merged = list(preferred)
    for window in windows:
        if any(review_windows_substantially_overlap(window, existing) for existing in merged):
            continue
        merged.append(window)
    return reindex_review_windows(merged)


def review_windows_substantially_overlap(
    left: PreparedReviewWindow,
    right: PreparedReviewWindow,
    *,
    min_ratio: float = 0.85,
) -> bool:
    overlap_start = max(left.start_seconds, right.start_seconds)
    overlap_end = min(left.end_seconds, right.end_seconds)
    overlap = max(0.0, overlap_end - overlap_start)
    if overlap <= 0.0:
        return False
    shorter = max(1e-6, min(left.end_seconds - left.start_seconds, right.end_seconds - right.start_seconds))
    return overlap / shorter >= min_ratio


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


def prepare_candidate_for_review(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    *,
    min_duration_seconds: int,
    max_duration_seconds: int,
) -> YouTubeCandidate:
    del exercise
    duration_reason = candidate_duration_rejection_reason(
        candidate,
        min_duration_seconds=min_duration_seconds,
        max_duration_seconds=max_duration_seconds,
    )
    return replace_candidate(
        candidate,
        final_score=0.0,
        status="rejected",
        score_reasons=[] if duration_reason is None else [duration_reason],
    )


def candidate_duration_rejection_reason(
    candidate: YouTubeCandidate,
    *,
    min_duration_seconds: int,
    max_duration_seconds: int,
) -> str | None:
    duration = candidate.duration_seconds
    if duration is None:
        return None
    if min_duration_seconds > 0 and duration < min_duration_seconds:
        return "duration_too_short"
    # Long videos are more expensive to scan, but can still contain an ideal
    # short movement window. Duration remains a ranking signal below; it must
    # not prevent pose/vision window discovery entirely.
    return None


def candidate_is_duration_eligible_for_review(
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> bool:
    return (
        candidate_duration_rejection_reason(
            candidate,
            min_duration_seconds=settings.min_duration_seconds,
            max_duration_seconds=settings.max_duration_seconds,
        )
        is None
    )


def vision_review_priority_score(
    candidate: YouTubeCandidate,
    *,
    min_duration_seconds: int,
    max_duration_seconds: int,
) -> float:
    score = 0.5
    duration = candidate.duration_seconds
    if duration is None:
        score -= 0.04
    elif duration < min_duration_seconds:
        score -= 0.45
    elif duration <= 60:
        score += 0.22
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
    return clamp_score(score)


def candidate_title_identity_priority_score(exercise_name: str, candidate_title: str) -> float:
    """Prefer literal target titles before spending model time on nearby variants."""
    target = normalize_exercise_name(exercise_name)
    title = normalize_exercise_name(candidate_title)
    if not target or not title:
        return 0.0
    target_tokens = target.split()
    title_tokens = title.split()
    unrequested_partial_tokens = {"partial", "quarter"}.intersection(title_tokens).difference(target_tokens)
    if "half" in title_tokens and "half" not in target_tokens and "full" not in title_tokens:
        unrequested_partial_tokens.add("half")
    partial_execution_cap = 0.35 if unrequested_partial_tokens else 1.0
    if title == target:
        return partial_execution_cap
    if title.startswith(f"{target} "):
        return min(0.98, partial_execution_cap)
    phrase_match = re.search(rf"(?<![a-z0-9]){re.escape(target)}(?![a-z0-9])", title)
    if phrase_match is not None:
        leading_token_count = len(title[: phrase_match.start()].split())
        return min(
            max(0.80, 0.95 - min(0.15, leading_token_count * 0.03)),
            partial_execution_cap,
        )

    if not target_tokens or not title_tokens:
        return 0.0
    title_token_set = set(title_tokens)
    matched_count = sum(1 for token in target_tokens if token in title_token_set)
    coverage = matched_count / len(target_tokens)
    precision = matched_count / len(title_tokens)
    return min(
        clamp_score((coverage * 0.70) + (precision * 0.30)),
        partial_execution_cap,
    )
def rank_youtube_review_pool(
    exercise: ExerciseEntry,
    candidates: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
) -> list[YouTubeCandidate]:
    return sorted(
        select_review_candidate_pool(candidates, settings),
        key=lambda candidate: (
            candidate_title_identity_priority_score(exercise.name, candidate.title),
            vision_review_priority_score(
                candidate,
                min_duration_seconds=settings.min_duration_seconds,
                max_duration_seconds=settings.max_duration_seconds,
            ),
            candidate.view_count or 0,
        ),
        reverse=True,
    )


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
    "low_required_joint_visibility",
    "cropped_body",
    "camera_or_track_instability",
    "weak_body_joint_motion",
    "low_active_chain_visibility",
    TARGET_MOTION_PREFILTER_BLOCKING_ISSUE,
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


def capped_llama_cpp_text_tokens(settings: YouTubeRankingSettings, *, cap: int = TEXT_ONLY_LLAMA_MAX_TOKENS) -> int:
    return max(1, min(max(1, settings.llama_cpp_n_predict), max(1, cap)))


def append_youtube_discovery_progress(
    path: Path,
    *,
    event: str,
    started_at: float,
    exercise: ExerciseEntry | None = None,
    **payload: Any,
) -> None:
    row: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsedSeconds": round_elapsed(time.monotonic() - started_at),
        "event": event,
    }
    if exercise is not None:
        row.update(
            {
                "exerciseId": exercise.exercise_id,
                "exerciseName": exercise.name,
                "exerciseSlug": exercise.slug,
            }
        )
    row.update(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def select_review_candidate_pool(
    candidates: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
) -> list[YouTubeCandidate]:
    return [
        candidate
        for candidate in candidates
        if candidate_duration_rejection_reason(
            candidate,
            min_duration_seconds=settings.min_duration_seconds,
            max_duration_seconds=settings.max_duration_seconds,
        )
        is None
    ]


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


def compose_final_score(vision_score: float | None) -> float:
    if vision_score is None:
        return 0.0
    return clamp_score(vision_score)


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
    for reason, (cap, cap_reason) in POSE_QUALITY_REASON_CAPS.items():
        if reason in reasons:
            capped = min(capped, cap)
            cap_reasons.append(cap_reason)
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
    "no_step_breakdown",
    "movement_start_posture_visible",
    "primary_effort_phase_visible",
    "movement_action_path_visible",
    "movement_end_posture_visible",
    "no_setup_or_talking_frames",
}

VISION_DETERMINISTIC_SOURCE_GATES = {
    "athlete_fully_in_frame_throughout",
    "static_camera_throughout",
    "single_camera_angle",
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
}

MIN_MOVING_SUBJECT_REALISM_SCORE = 0.85
LOW_MOVING_SUBJECT_REALISM_SCORE_CAP = 0.34
VISION_SEMANTIC_BLOCKING_ISSUES = {
    "wrong_exercise",
    "wrong_variant",
    "partial_movement",
    "slow_instruction",
    "setup_or_talking",
    "unclear",
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
    if parse_moving_subject_realism_score(payload) < MIN_MOVING_SUBJECT_REALISM_SCORE:
        return False
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
    debug_scored_by_key: dict[str, YouTubeCandidate] | None = None,
) -> list[YouTubeCandidate]:
    if not ranked:
        return []
    review_eligible = [
        candidate
        for candidate in ranked
        if candidate_is_duration_eligible_for_review(candidate, settings)
    ]
    if not review_eligible:
        return []
    batch_size = settings.resolved_semantic_gate_candidates_per_exercise()
    max_review_limit = min(
        len(review_eligible),
        settings.resolved_semantic_gate_max_candidates_per_exercise(),
    )
    target_pass_count = min(
        max_review_limit,
        settings.resolved_semantic_gate_target_pass_count(),
    )
    stop_after_target_pass_count = not settings.pose_prefilter_enabled and not settings.rank_with_vision
    active_gate = semantic_gate or rank_candidate_with_llama_cpp_semantic_gate
    scored_by_key: dict[str, YouTubeCandidate] = {}

    def score_candidates(candidates_to_review: list[YouTubeCandidate]) -> None:
        pending = [
            candidate
            for candidate in candidates_to_review
            if candidate.key() not in scored_by_key
        ]
        if not pending:
            return
        workers = max(1, min(settings.resolved_semantic_gate_llm_workers(), len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(active_gate, exercise, candidate, settings): candidate
                for candidate in pending
            }
            for future in as_completed(futures):
                candidate = futures[future]
                try:
                    semantic_score, semantic_reasons, semantic_payload = normalize_semantic_gate_result(future.result())
                    scored = apply_semantic_gate_score(
                        candidate,
                        exercise=exercise,
                        semantic_score=semantic_score,
                        semantic_reasons=semantic_reasons,
                        semantic_payload=semantic_payload,
                        settings=settings,
                    )
                except Exception as exc:
                    if is_critical_vlm_interaction_error(exc):
                        add_vlm_context(
                            exc,
                            stage="semantic_gate_parallel",
                            exerciseName=exercise.name,
                            videoId=candidate.video_id,
                            title=candidate.title,
                        )
                        raise
                    scored = apply_semantic_gate_score(
                        candidate,
                        exercise=exercise,
                        semantic_score=0.0,
                        semantic_reasons=["semantic_gate_failed"],
                        semantic_payload={
                            "enabled": True,
                            "passed": False,
                            "score": 0.0,
                            "unresolved": True,
                            "error": str(exc),
                        },
                        settings=settings,
                    )
                scored_by_key[candidate.key()] = scored
                if debug_scored_by_key is not None:
                    debug_scored_by_key[candidate.key()] = scored

    try:
        reviewed: list[YouTubeCandidate] = []
        narrowed: list[YouTubeCandidate] = []
        reviewed_limit = 0
        while reviewed_limit < max_review_limit:
            next_limit = min(max_review_limit, reviewed_limit + batch_size)
            score_candidates(review_eligible[reviewed_limit:next_limit])
            reviewed_limit = next_limit
            reviewed_keys = [candidate.key() for candidate in review_eligible[:reviewed_limit]]
            reviewed = [scored_by_key.get(key) for key in reviewed_keys if scored_by_key.get(key) is not None]
            if settings.pose_prefilter_enabled or settings.rank_with_vision:
                narrowed = [
                    candidate
                    for candidate in reviewed
                    if candidate_is_semantic_visual_review_candidate(candidate, settings=settings)
                ]
            else:
                narrowed = [
                    candidate
                    for candidate in reviewed
                    if candidate_semantic_gate_passed(candidate)
                ]
            if stop_after_target_pass_count and len(narrowed) >= target_pass_count:
                break
        narrowed.sort(key=lambda item: semantic_gate_sort_key(item, settings), reverse=True)
        return narrowed
    finally:
        if isinstance(active_gate, LlamaCppSemanticGate):
            active_gate.close()


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
    model_unrequested_variants = semantic_payload_unrequested_variant_terms(semantic_payload)
    model_variant_reasons = [
        f"semantic_unrequested_{slugify(variant).replace('-', '_')}_variant"
        for variant in model_unrequested_variants
        if slugify(variant)
    ]
    if model_unrequested_variants:
        semantic_payload["unrequestedVariantTerms"] = model_unrequested_variants
    semantic_unresolved = semantic_gate_payload_is_unresolved(semantic_payload)
    if semantic_unresolved:
        semantic_payload["unresolved"] = True
        semantic_reasons = dedupe_reasons([*semantic_reasons, "semantic_gate_unresolved"])
        if not model_variant_reasons and (settings.pose_prefilter_enabled or settings.rank_with_vision):
            semantic_reasons = dedupe_reasons([*semantic_reasons, "semantic_gate_unresolved_visual_fallback"])
    if model_variant_reasons:
        clamped_score = min(clamped_score, 0.20)
        semantic_reasons = dedupe_reasons([*semantic_reasons, *model_variant_reasons])
    wrong_exercise = bool(semantic_payload.get("wrongExercise"))
    passed = clamped_score >= settings.semantic_gate_min_score and not wrong_exercise
    duration_preference_score = semantic_gate_duration_preference_score(candidate, settings)
    ranking_score = compose_semantic_gate_ranking_score(
        clamped_score,
        duration_preference_score,
        settings,
    )
    semantic_payload.setdefault("enabled", True)
    semantic_payload["passed"] = passed
    semantic_payload["score"] = clamped_score
    semantic_payload["rankingScore"] = round(ranking_score, 4)
    semantic_payload["durationSeconds"] = candidate.duration_seconds
    semantic_payload["durationPreferenceScore"] = round(duration_preference_score, 4)
    semantic_payload["durationRankWeight"] = round(clamp_score(settings.semantic_gate_duration_rank_weight), 4)
    payload["semanticGate"] = semantic_payload
    score_reasons = dedupe_reasons(candidate.score_reasons + semantic_reasons)
    if passed:
        score_reasons = dedupe_reasons([*score_reasons, "semantic_gate_passed"])
    else:
        score_reasons = dedupe_reasons([*score_reasons, "semantic_gate_rejected"])
    final_score = 0.0 if model_variant_reasons else clamped_score
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


def semantic_gate_duration_preference_score(
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> float:
    duration = candidate.duration_seconds
    if duration is None or duration <= 0:
        return 0.45
    horizon = (
        float(settings.max_duration_seconds)
        if settings.max_duration_seconds > 0
        else SEMANTIC_GATE_DURATION_HORIZON_SECONDS
    )
    horizon = max(SEMANTIC_GATE_SHORT_DURATION_SECONDS + 1.0, horizon)
    if duration <= SEMANTIC_GATE_SHORT_DURATION_SECONDS:
        return 1.0
    progress = min(
        1.0,
        max(
            0.0,
            (float(duration) - SEMANTIC_GATE_SHORT_DURATION_SECONDS)
            / (horizon - SEMANTIC_GATE_SHORT_DURATION_SECONDS),
        ),
    )
    return clamp_score(1.0 - (0.60 * progress))


def compose_semantic_gate_ranking_score(
    semantic_score: float,
    duration_preference_score: float,
    settings: YouTubeRankingSettings,
) -> float:
    clamped_semantic_score = clamp_score(semantic_score)
    if clamped_semantic_score <= 0.0:
        return 0.0
    duration_weight = clamp_score(settings.semantic_gate_duration_rank_weight)
    semantic_weight = 1.0 - duration_weight
    return clamp_score(
        (clamped_semantic_score * semantic_weight)
        + (clamp_score(duration_preference_score) * duration_weight)
    )


def semantic_gate_ranking_score(
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> float:
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    semantic_payload = payload.get("semanticGate") if isinstance(payload, dict) else None
    if isinstance(semantic_payload, dict):
        value = semantic_payload.get("rankingScore")
        if isinstance(value, (int, float)):
            return clamp_score(float(value))
    return compose_semantic_gate_ranking_score(
        semantic_gate_score(candidate),
        semantic_gate_duration_preference_score(candidate, settings),
        settings,
    )


def semantic_gate_duration_sort_value(candidate: YouTubeCandidate) -> float:
    duration = candidate.duration_seconds
    return -(float(duration) if duration is not None and duration > 0 else 1_000_000.0)


def semantic_gate_sort_key(candidate: YouTubeCandidate, settings: YouTubeRankingSettings) -> tuple[Any, ...]:
    return (
        candidate_semantic_gate_passed(candidate),
        semantic_gate_ranking_score(candidate, settings),
        semantic_gate_score(candidate),
        semantic_gate_duration_preference_score(candidate, settings),
        semantic_gate_duration_sort_value(candidate),
        candidate.final_score,
    )


def candidate_semantic_gate_payload(candidate: YouTubeCandidate) -> dict[str, Any] | None:
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    semantic_payload = payload.get("semanticGate") if isinstance(payload, dict) else None
    return semantic_payload if isinstance(semantic_payload, dict) else None


def candidate_semantic_gate_passed(candidate: YouTubeCandidate) -> bool:
    payload = candidate_semantic_gate_payload(candidate)
    return bool(payload and payload.get("passed"))


def semantic_gate_payload_is_unresolved(payload: dict[str, Any]) -> bool:
    return bool(payload.get("unresolved")) or bool(payload.get("error"))


def candidate_is_semantic_visual_review_candidate(
    candidate: YouTubeCandidate,
    *,
    settings: YouTubeRankingSettings,
) -> bool:
    payload = candidate_semantic_gate_payload(candidate)
    if payload is None:
        return False
    if bool(payload.get("passed")):
        return True
    if bool(payload.get("wrongExercise")) or bool(payload.get("wrongEquipment")):
        return False
    return semantic_gate_payload_is_unresolved(payload)


def candidate_is_semantic_pose_candidate(candidate: YouTubeCandidate, *, settings: YouTubeRankingSettings) -> bool:
    return candidate_is_semantic_visual_review_candidate(candidate, settings=settings)


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


def build_exercise_motion_contract_prompt(exercise: ExerciseEntry) -> str:
    return (
        "Describe one complete visible movement for the exact named exercise.\n"
        "Use the normal exercise definition. Do not guess mechanics from separate words in the name.\n"
        "For a repetition or cycle, validStartState is the posture before the first movement. "
        "requiredPhases lists every visible phase in time order until the body returns to that posture. "
        "Do not return only one direction such as lockout-to-bottom or bottom-to-lockout.\n"
        "For a hold, carry, or transition, describe the distinct validEndState.\n"
        "List setup and cleanup actions that must be outside the selected movement, such as approach, unrack, repositioning, rerack, release, or walking away.\n"
        "Only list body regions that must be visible to recognize the movement. Use generic observable language, not coaching advice.\n"
        "Return minified JSON only. No markdown table, code fence, timestamps, chain-of-thought, or explanation.\n"
        "Use exactly these keys: movementType, groundContactMode, validStartState, validEndState, requiredPhases, "
        "primaryMovingRegions, mustBeVisibleRegions, excludedSetupOrCleanup.\n"
        "movementType must be one of: repetition, cyclic, hold, carry, transition_sequence, unknown.\n"
        "groundContactMode must be continuous when at least one body support normally remains on the floor, "
        "intermittent when the movement intentionally contains airborne phases, or none when the body is hanging, suspended, swimming, or otherwise not floor-supported.\n"
        "primaryMovingRegions and mustBeVisibleRegions may only contain: hands, elbows, shoulders, torso, head, hips, knees, feet, upper_limb, lower_limb.\n"
        f"Target exercise: {exercise.name}\n"
    )


def generate_exercise_motion_contract_with_ranker(
    *,
    exercise: ExerciseEntry,
    settings: YouTubeRankingSettings,
    ranker: "LlamaCppVisionRanker",
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        caption_kwargs: dict[str, Any] = {
            "frame_paths": [],
            "prompt": build_exercise_motion_contract_prompt(exercise),
            "max_tokens": capped_llama_cpp_text_tokens(
                settings,
                cap=EXERCISE_MOTION_CONTRACT_LLAMA_MAX_TOKENS,
            ),
        }
        if callable_accepts_keyword(ranker.client.caption_images, "disable_reasoning"):
            caption_kwargs["disable_reasoning"] = False
        if callable_accepts_keyword(ranker.client.caption_images, "json_response"):
            caption_kwargs["json_response"] = True
        if callable_accepts_keyword(ranker.client.caption_images, "temperature"):
            caption_kwargs["temperature"] = 0.0
        if callable_accepts_keyword(ranker.client.caption_images, "top_p"):
            caption_kwargs["top_p"] = 1.0
        if callable_accepts_keyword(ranker.client.caption_images, "top_k"):
            caption_kwargs["top_k"] = 0
        if callable_accepts_keyword(ranker.client.caption_images, "request_timeout_seconds"):
            caption_kwargs["request_timeout_seconds"] = max(
                1.0,
                float(settings.llama_cpp_request_timeout_seconds),
            )
        raw = ranker.client.caption_images(**caption_kwargs)
        contract = normalize_exercise_motion_contract_response(raw, exercise=exercise, source="llm")
        contract["model"] = settings.llama_cpp_model
        contract["generationElapsedSeconds"] = round_elapsed(time.monotonic() - started)
        return contract
    except Exception as exc:
        if is_critical_vlm_interaction_error(exc):
            add_vlm_context(
                exc,
                stage="exercise_motion_contract_generation",
                exerciseName=exercise.name,
                model=settings.llama_cpp_model,
            )
            raise
        return {
            "schemaVersion": 1,
            "enabled": True,
            "status": "failed",
            "source": "llm",
            "exerciseName": exercise.name,
            "model": settings.llama_cpp_model,
            "error": truncate_text(str(exc), 240),
            "generationElapsedSeconds": round_elapsed(time.monotonic() - started),
        }


def text_llama_cpp_settings(settings: YouTubeRankingSettings) -> YouTubeRankingSettings:
    text_model = settings.text_llama_cpp_model or settings.llama_cpp_model
    text_mmproj = settings.text_llama_cpp_mmproj
    if text_model == settings.llama_cpp_model and text_mmproj == settings.llama_cpp_mmproj:
        return settings
    return dataclass_replace(
        settings,
        llama_cpp_model=text_model,
        llama_cpp_mmproj=text_mmproj,
        llama_cpp_disable_reasoning=False,
        keep_llama_cpp_server=False,
    )


def exercise_contract_llama_cpp_settings(settings: YouTubeRankingSettings) -> YouTubeRankingSettings:
    if settings.exercise_contract_llama_cpp_model is None and settings.exercise_contract_llama_cpp_mmproj is None:
        return text_llama_cpp_settings(settings)
    contract_model = settings.exercise_contract_llama_cpp_model or settings.text_llama_cpp_model or settings.llama_cpp_model
    contract_mmproj = (
        settings.exercise_contract_llama_cpp_mmproj
        if settings.exercise_contract_llama_cpp_mmproj is not None
        else settings.text_llama_cpp_mmproj
    )
    return text_llama_cpp_settings(
        dataclass_replace(
            settings,
            text_llama_cpp_model=contract_model,
            text_llama_cpp_mmproj=contract_mmproj,
        )
    )


def shared_ranker_matches_settings(ranker: Any | None, settings: YouTubeRankingSettings) -> bool:
    ranker_settings = getattr(ranker, "settings", None)
    if not isinstance(ranker_settings, YouTubeRankingSettings):
        return True
    return (
        ranker_settings.llama_cpp_model == settings.llama_cpp_model
        and ranker_settings.llama_cpp_mmproj == settings.llama_cpp_mmproj
    )


def normalize_exercise_motion_contract_text(
    payload: Any,
    *,
    exercise: ExerciseEntry,
    source: str,
) -> dict[str, Any]:
    advisory_text = cleaned_contract_advisory_text(payload)
    if not advisory_text:
        raise ValueError("exercise motion guidance generator returned empty text.")
    return {
        "schemaVersion": 1,
        "enabled": True,
        "status": "generated",
        "source": source,
        "exerciseName": exercise.name,
        "advisoryText": advisory_text,
    }


def extract_exercise_motion_contract_json_payload(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        return unpack_nested_exercise_motion_contract_payload(payload)
    if not isinstance(payload, str):
        return None
    try:
        from exercise_motion_pkg.segment_detection import extract_json_object
    except Exception:
        return None
    extracted = extract_json_object(payload)
    return unpack_nested_exercise_motion_contract_payload(extracted) if isinstance(extracted, dict) else None


def unpack_nested_exercise_motion_contract_payload(payload: dict[str, Any]) -> dict[str, Any]:
    nested = nested_exercise_motion_contract_payload(payload)
    if nested is None:
        return payload
    merged = dict(nested)
    for key, value in payload.items():
        if key == "advisoryText" and isinstance(value, str):
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        merged[key] = value
    return merged


def nested_exercise_motion_contract_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from exercise_motion_pkg.segment_detection import extract_json_object
    except Exception:
        return None
    for key in ("advisoryText", "guidance", "text", "contract", "plainText"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        extracted = extract_json_object(value)
        if isinstance(extracted, dict) and normalized_exercise_motion_contract_fields(extracted):
            return extracted
    return None


def normalize_exercise_motion_contract_response(
    payload: Any,
    *,
    exercise: ExerciseEntry,
    source: str,
) -> dict[str, Any]:
    structured_payload = extract_exercise_motion_contract_json_payload(payload)
    if structured_payload is not None:
        return normalize_exercise_motion_contract(structured_payload, exercise=exercise, source=source)
    return normalize_exercise_motion_contract_text(payload, exercise=exercise, source=source)


def normalize_exercise_motion_contract(
    payload: dict[str, Any] | None,
    *,
    exercise: ExerciseEntry,
    source: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("exercise motion contract payload must be a JSON object.")
    payload = unpack_nested_exercise_motion_contract_payload(payload)
    structured_fields = normalized_exercise_motion_contract_fields(payload)
    structured_fields = simplify_repetition_contract_for_visual_review(structured_fields)
    structured_advisory_text = synthesize_exercise_motion_advisory_text(structured_fields)
    advisory_text = ""
    for key in ("advisoryText", "guidance", "text", "contract", "plainText"):
        advisory_text = cleaned_contract_advisory_text(payload.get(key))
        if advisory_text:
            break
    if structured_fields and structured_advisory_text:
        advisory_text = structured_advisory_text
    elif not advisory_text:
        advisory_text = structured_advisory_text
    if not advisory_text:
        raise ValueError("exercise motion contract payload must include plain guidance text.")
    contract = normalize_exercise_motion_contract_text(advisory_text, exercise=exercise, source=source)
    contract.update(structured_fields)
    return contract


def simplify_repetition_contract_for_visual_review(fields: dict[str, Any]) -> dict[str, Any]:
    """Replace fragile model-authored phase mechanics with an observable cycle contract."""
    if (
        fields.get("movementType") not in {"repetition", "cyclic"}
        or fields.get("requiresReturnToStart") is not True
    ):
        return fields
    simplified = dict(fields)
    stable_posture = "a stable exercise posture immediately before one complete repetition"
    phases = [
        "move away from the start posture through the exercise action",
        "reach a clear turning point",
        "return through the exercise action to the start posture",
    ]
    simplified["validStartState"] = stable_posture
    simplified["validEndState"] = stable_posture
    simplified["requiredPhases"] = phases
    simplified["movementTopology"] = {
        "schemaVersion": 1,
        "completionMode": "return_to_start",
        "startState": {"id": "start_state", "label": stable_posture},
        "phases": [
            {"id": f"phase_{index + 1:02d}", "label": label}
            for index, label in enumerate(phases)
        ],
        "endState": {"id": "end_state", "label": stable_posture},
    }
    simplified["contractSimplification"] = "generic_observable_return_cycle"
    return simplified


def normalize_exercise_movement_type(value: Any) -> str | None:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    aliases = {
        "rep": "repetition",
        "reps": "repetition",
        "single_rep": "repetition",
        "full_rep": "repetition",
        "cycle": "cyclic",
        "full_cycle": "cyclic",
        "static_hold": "hold",
        "isometric": "hold",
        "loaded_carry": "carry",
        "transition": "transition_sequence",
        "transition_sequence": "transition_sequence",
        "sequence": "transition_sequence",
    }
    text = aliases.get(text, text)
    return text if text in {"repetition", "cyclic", "hold", "carry", "transition_sequence", "unknown"} else None


def normalize_ground_contact_mode(value: Any) -> str | None:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    aliases = {
        "always": "continuous",
        "always_supported": "continuous",
        "floor_supported": "continuous",
        "sometimes": "intermittent",
        "airborne": "intermittent",
        "flight": "intermittent",
        "hanging": "none",
        "suspended": "none",
        "unsupported": "none",
    }
    text = aliases.get(text, text)
    return text if text in {"continuous", "intermittent", "none"} else None


def normalize_exercise_completion_mode(value: Any) -> str | None:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    aliases = {
        "return": "return_to_start",
        "returns_to_start": "return_to_start",
        "full_return": "return_to_start",
        "loop": "return_to_start",
        "loopable": "return_to_start",
        "one_way": "distinct_end_state",
        "one_way_transition": "distinct_end_state",
        "distinct_finish": "distinct_end_state",
        "end_state": "distinct_end_state",
        "hold": "stable_hold",
        "static_hold": "stable_hold",
        "isometric": "stable_hold",
        "carry": "active_travel",
        "travel": "active_travel",
        "locomotion": "active_travel",
        "cycle": "representative_cycle",
        "cyclic": "representative_cycle",
        "representative_rep": "representative_cycle",
        "alternating": "alternating_pair",
        "left_right_pair": "alternating_pair",
    }
    text = aliases.get(text, text)
    allowed = {
        "return_to_start",
        "distinct_end_state",
        "stable_hold",
        "active_travel",
        "representative_cycle",
        "alternating_pair",
    }
    return text if text in allowed else None


def infer_exercise_completion_mode(
    *,
    movement_type: str | None,
    requires_return: bool | None,
    payload: dict[str, Any],
) -> str:
    phase_text = " ".join(
        cleaned_contract_string_list(
            first_contract_value(payload, "requiredPhases", "phases", "completePhases"),
            limit=8,
            item_limit=120,
        )
    ).casefold()
    if "alternat" in phase_text or "left and right" in phase_text or "right and left" in phase_text:
        return "alternating_pair"
    if movement_type == "hold":
        return "stable_hold"
    if movement_type == "carry":
        return "active_travel"
    if movement_type == "cyclic":
        return "representative_cycle"
    if movement_type == "transition_sequence":
        return "distinct_end_state"
    if requires_return is True:
        return "return_to_start"
    if requires_return is False:
        return "distinct_end_state"
    return "representative_cycle"


def first_contract_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        return value
    return None


def synthesize_exercise_motion_advisory_text(payload: dict[str, Any]) -> str:
    valid_start = cleaned_contract_string(
        first_contract_value(payload, "validStartState", "requiredStartPosture", "startState", "source"),
        220,
    )
    valid_end = cleaned_contract_string(
        first_contract_value(payload, "validEndState", "requiredEndPosture", "endState", "finishState"),
        220,
    )
    required_phases = cleaned_contract_string_list(
        first_contract_value(payload, "requiredPhases", "phases", "completePhases"),
        limit=6,
        item_limit=180,
    )
    boundary_rule = cleaned_contract_string(first_contract_value(payload, "boundaryRule", "boundary"), 260)
    excluded = cleaned_contract_string_list(
        first_contract_value(payload, "excludedSetupOrCleanup", "excludedSetupCleanup", "rejectSetupCleanup"),
        limit=8,
        item_limit=120,
    )
    wrong_variants = cleaned_contract_string_list(
        first_contract_value(payload, "commonWrongVariants", "wrongVariants", "rejectIf"),
        limit=8,
        item_limit=120,
    )
    notes = cleaned_contract_string_list(
        first_contract_value(payload, "reviewNotes", "notes"),
        limit=4,
        item_limit=160,
    )

    lines: list[str] = []
    if valid_start:
        lines.append(f"Source: {valid_start}")
    complete_parts = list(required_phases)
    if valid_end:
        complete_parts.append(f"finish/end state: {valid_end}")
    if complete_parts:
        lines.append(f"Complete: {'; '.join(complete_parts)}")
    if boundary_rule:
        lines.append(f"Boundary: {boundary_rule}")
    elif excluded:
        lines.append(f"Boundary: Exclude {'; '.join(excluded)} before or after the exercise action.")
    reject_parts = [*wrong_variants, *excluded]
    if reject_parts:
        lines.append(f"Reject: {'; '.join(reject_parts)}")
    if notes:
        lines.append(f"Notes: {'; '.join(notes)}")
    return cleaned_contract_advisory_text("\n".join(lines))


def normalized_exercise_motion_contract_fields(payload: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    movement_type = normalize_exercise_movement_type(first_contract_value(payload, "movementType", "movement_type"))
    if movement_type is not None:
        fields["movementType"] = movement_type

    ground_contact_mode = normalize_ground_contact_mode(
        first_contract_value(payload, "groundContactMode", "ground_contact_mode")
    )
    if ground_contact_mode is not None:
        fields["groundContactMode"] = ground_contact_mode

    requires_return = parse_contract_bool(first_contract_value(payload, "requiresReturnToStart", "requires_return_to_start"))
    if requires_return is None:
        if movement_type in {"repetition", "cyclic"}:
            requires_return = True
        elif movement_type in {"hold", "carry", "transition_sequence"}:
            requires_return = False
    if requires_return is not None:
        fields["requiresReturnToStart"] = requires_return

    completion_mode = normalize_exercise_completion_mode(
        first_contract_value(payload, "completionMode", "completion_mode", "movementCompletionMode")
    )
    if completion_mode is None:
        completion_mode = infer_exercise_completion_mode(
            movement_type=movement_type,
            requires_return=requires_return,
            payload=payload,
        )
    fields["completionMode"] = completion_mode

    string_fields = {
        "validStartState": ("validStartState", "requiredStartPosture", "startState"),
        "validEndState": ("validEndState", "requiredEndPosture", "endState", "finishState"),
        "boundaryRule": ("boundaryRule", "boundary"),
    }
    for output_key, aliases in string_fields.items():
        text = cleaned_contract_string(first_contract_value(payload, *aliases), 280)
        if text:
            fields[output_key] = text
    if requires_return is True and isinstance(fields.get("validStartState"), str):
        # A complete repetition/cycle ends at its observable start posture. Derive
        # this invariant in code instead of asking a small model to restate it.
        fields["validEndState"] = fields["validStartState"]

    list_fields = {
        "requiredPhases": ("requiredPhases", "phases", "completePhases"),
        "allowedExerciseTransitions": ("allowedExerciseTransitions", "allowedTransitions"),
        "excludedSetupOrCleanup": ("excludedSetupOrCleanup", "excludedSetupCleanup", "rejectSetupCleanup"),
        "commonWrongVariants": ("commonWrongVariants", "wrongVariants", "rejectIf"),
        "reviewNotes": ("reviewNotes", "notes"),
    }
    for output_key, aliases in list_fields.items():
        values = cleaned_contract_string_list(first_contract_value(payload, *aliases), limit=8, item_limit=180)
        if values:
            fields[output_key] = values

    primary_regions = normalize_observable_motion_regions(
        first_contract_value(payload, "primaryMovingRegions", "primaryMotionRegions"),
        limit=8,
    )
    reference_regions = normalize_observable_motion_regions(first_contract_value(payload, "referenceRegions"), limit=8)
    visible_regions = normalize_observable_motion_regions(
        first_contract_value(payload, "mustBeVisibleRegions", "mustBeVisible", "visibleRegions"),
        limit=8,
    )
    if primary_regions:
        fields["primaryMovingRegions"] = primary_regions
    if reference_regions:
        fields["referenceRegions"] = reference_regions
    if visible_regions:
        fields["mustBeVisibleRegions"] = visible_regions

    observable_spec = normalize_observable_motion_spec(payload.get("observableMotionSpec"))
    if observable_spec is None:
        spec_payload: dict[str, Any] = {}
        if primary_regions:
            spec_payload["primaryMovingRegions"] = primary_regions
        if reference_regions:
            spec_payload["referenceRegions"] = reference_regions
        if visible_regions:
            spec_payload["mustBeVisibleRegions"] = visible_regions
        axis = normalize_observable_motion_axis(first_contract_value(payload, "primaryAxis", "motionAxis"))
        pattern = normalize_observable_motion_pattern(first_contract_value(payload, "motionPattern"))
        if axis != "any":
            spec_payload["primaryAxis"] = axis
        if pattern != "other":
            spec_payload["motionPattern"] = pattern
        if requires_return is not None:
            spec_payload["requiresReturnToStart"] = requires_return
            spec_payload["oneWayPartialIsInvalid"] = requires_return
            spec_payload["mustShowFullCycle"] = requires_return
        observable_spec = normalize_observable_motion_spec(spec_payload)
    if observable_spec is not None:
        fields["observableMotionSpec"] = observable_spec
    required_phases = fields.get("requiredPhases")
    valid_start_state = fields.get("validStartState")
    valid_end_state = fields.get("validEndState")
    if (
        isinstance(required_phases, list)
        and required_phases
        and isinstance(valid_start_state, str)
        and valid_start_state
        and isinstance(valid_end_state, str)
        and valid_end_state
    ):
        fields["movementTopology"] = {
            "schemaVersion": 1,
            "completionMode": completion_mode,
            "startState": {"id": "start_state", "label": valid_start_state},
            "phases": [
                {"id": f"phase_{index + 1:02d}", "label": str(label)}
                for index, label in enumerate(required_phases)
            ],
            "endState": {"id": "end_state", "label": valid_end_state},
        }
    return fields


EXERCISE_MOTION_CONTRACT_PROMPT_FIELD_KEYS = (
    "movementType",
    "groundContactMode",
    "completionMode",
    "requiresReturnToStart",
    "validStartState",
    "validEndState",
    "requiredPhases",
    "primaryMovingRegions",
    "referenceRegions",
    "mustBeVisibleRegions",
    "allowedExerciseTransitions",
    "excludedSetupOrCleanup",
    "boundaryRule",
    "commonWrongVariants",
    "reviewNotes",
    "observableMotionSpec",
    "movementTopology",
)


def cleaned_contract_string(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return truncate_text(text, limit) or ""


def cleaned_contract_advisory_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    fence_match = re.match(
        r"^```(?:text|markdown|md)?\s*(.*?)\s*```$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fence_match:
        text = fence_match.group(1).strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<\|/?(?:channel|message|constrain|end)\|?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:channel|message|constrain|end)\|>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:analysis|thought|final)\s*<channel\|>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*(?:analysis|thought|final)\b[:\s-]*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line).strip()
    if not text:
        return ""
    if len(text) <= EXERCISE_MOTION_CONTRACT_TEXT_LIMIT:
        return text
    return text[: EXERCISE_MOTION_CONTRACT_TEXT_LIMIT - 1].rstrip() + "..."


def cleaned_contract_string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if isinstance(value, str):
        raw_items: Iterable[Any] = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = cleaned_contract_string(item, item_limit)
        key = text.casefold()
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
        if len(cleaned) >= limit:
            break
    return cleaned


def exercise_motion_contract_is_usable(contract: dict[str, Any] | None) -> bool:
    return (
        isinstance(contract, dict)
        and contract.get("status") == "generated"
        and bool(cleaned_contract_advisory_text(contract.get("advisoryText")))
    )


def exercise_motion_contract_for_prompt(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(contract, dict):
        return None
    advisory_text = cleaned_contract_advisory_text(contract.get("advisoryText"))
    if not advisory_text:
        return None
    prompt_contract: dict[str, Any] = {
        "exerciseName": contract.get("exerciseName"),
        "advisoryText": advisory_text,
    }
    for key in EXERCISE_MOTION_CONTRACT_PROMPT_FIELD_KEYS:
        value = contract.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        prompt_contract[key] = value
    return prompt_contract


def exercise_motion_contract_prompt_body(prompt_contract: dict[str, Any]) -> str:
    advisory_text = cleaned_contract_advisory_text(prompt_contract.get("advisoryText"))
    structured = {
        key: prompt_contract[key]
        for key in EXERCISE_MOTION_CONTRACT_PROMPT_FIELD_KEYS
        if key in prompt_contract
    }
    if not structured:
        return advisory_text
    return (
        f"{advisory_text}\n"
        "Structured movement contract: "
        + json.dumps(structured, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    )


def build_exercise_motion_contract_prompt_section(contract: dict[str, Any] | None) -> str:
    prompt_contract = exercise_motion_contract_for_prompt(contract)
    if prompt_contract is None:
        return ""
    return (
        "Exercise-specific movement guidance. Use this to judge visible movement identity, completeness, and clean movement-only boundaries. "
        "Do not add camera, crop, person-count, or timestamp duties. "
        "Do not invent variant requirements that are not present in the target name or guidance.\n"
        f"{exercise_motion_contract_prompt_body(prompt_contract)}\n"
    )


def build_candidate_semantic_gate_prompt(exercise: ExerciseEntry, candidate: YouTubeCandidate) -> str:
    description = truncate_text(candidate.description_snippet or "", 360) or ""
    duration_text = str(candidate.duration_seconds) if candidate.duration_seconds is not None else "unknown"
    return (
        "Text-only semantic gate. Classify whether the YouTube title/description is the exact target movement. "
        "Reject routines, compilations, briefly mentioned exercises, wrong base movements, and named variants not in the target. "
        "First identify every movement-changing qualifier expressed by the target and every qualifier expressed by the candidate. "
        "A qualifier changes how the movement is performed, including but not limited to range of motion, assistance, loading method, "
        "equipment, angle, grip, stance, limb count, body position, tempo, pause, support style, or a progression that combines variants. "
        "If the candidate contains any movement-changing qualifier that the target does not request, put each extra qualifier in "
        "unrequestedVariantTerms and set passed=false even when the title also contains the unqualified target words. "
        "Do not let one matching qualifier cancel a conflicting or additional qualifier; judge the complete candidate title as one movement identity. "
        "For generic weighted/loaded targets, vest/belt/plate/dumbbell/kettlebell are valid loading methods only when the base movement is unchanged. "
        "Duration is ranking context only: prefer short exact exercise clips over long tutorials when semantic confidence is similar, "
        "but do not mark wrongExercise only because a video is long or short. "
        "Return minified JSON only with keys: "
        "{\"passed\":bool,\"score\":number,\"wrongExercise\":bool,\"wrongEquipment\":bool,"
        "\"unrequestedVariantTerms\":[string],\"matchedExercise\":string,\"reason\":\"max 6 words\"}. "
        "Use score 0.0 to 1.0 for exact-target confidence; pass only when score >= 0.55 and wrongExercise is false.\n"
        f"Target exercise: {exercise.name}\n"
        f"Candidate title: {candidate.title}\n"
        f"Candidate channel: {candidate.channel or ''}\n"
        f"Candidate duration seconds: {duration_text}\n"
        f"Candidate description: {description}\n"
    )


def rank_candidates_with_pose_prefilter(
    *,
    exercise: ExerciseEntry,
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
    pose_ranker: PoseRankerFn | None = None,
    exercise_motion_contract: dict[str, Any] | None = None,
) -> list[YouTubeCandidate]:
    if not ranked:
        return []
    review_eligible = [
        candidate
        for candidate in ranked
        if candidate_is_duration_eligible_for_review(candidate, settings)
    ]
    if not review_eligible:
        return []
    limit = min(len(review_eligible), settings.resolved_pose_prefilter_candidates_per_exercise())
    candidates_to_review = review_eligible[:limit]
    active_ranker = pose_ranker or rank_candidate_with_yolo_pose
    if pose_ranker is None:
        prefetch_youtube_previews_parallel(candidates_to_review, settings)
    workers = max(1, min(settings.pose_prefilter_workers, len(candidates_to_review)))
    scored_by_key: dict[str, YouTubeCandidate] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        if pose_ranker is None:
            futures = {
                executor.submit(
                    rank_candidate_with_yolo_pose,
                    exercise,
                    candidate,
                    settings,
                    exercise_motion_contract,
                ): candidate
                for candidate in candidates_to_review
            }
        else:
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
            except YoloDeviceUnavailableError:
                raise
            except Exception as exc:
                if is_critical_vlm_interaction_error(exc):
                    add_vlm_context(
                        exc,
                        stage="pose_prefilter_parallel",
                        exerciseName=exercise.name,
                        videoId=candidate.video_id,
                        title=candidate.title,
                    )
                    raise
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
    quality_issues = [issue for issue in quality_issues if issue != "frontal_or_back_view"]
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
    else:
        pose_payload.pop("qualityIssues", None)
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
    final_score = 0.0 if not passed else clamped_pose_score
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


def reviewed_candidate_sort_key(candidate: YouTubeCandidate, settings: YouTubeRankingSettings) -> tuple[Any, ...]:
    semantic_rank = semantic_gate_ranking_score(candidate, settings)
    semantic_score = semantic_gate_score(candidate)
    duration_preference = semantic_gate_duration_preference_score(candidate, settings)
    duration_sort_value = semantic_gate_duration_sort_value(candidate)
    if settings.rank_with_vision:
        return (
            candidate.vision_score is not None,
            candidate.final_score,
            pose_prefilter_score(candidate),
            semantic_rank,
            semantic_score,
            duration_preference,
            duration_sort_value,
        )
    if settings.pose_prefilter_enabled:
        return (
            candidate.final_score,
            pose_prefilter_score(candidate),
            semantic_rank,
            semantic_score,
            duration_preference,
            duration_sort_value,
        )
    if settings.semantic_gate_enabled:
        return (
            semantic_rank,
            semantic_score,
            duration_preference,
            duration_sort_value,
            candidate.final_score,
        )
    return (
        candidate.final_score,
        pose_prefilter_score(candidate),
        semantic_score,
        duration_preference,
        duration_sort_value,
    )


def sort_youtube_reviewed_candidates(
    candidates: Iterable[YouTubeCandidate],
    settings: YouTubeRankingSettings,
) -> list[YouTubeCandidate]:
    return sorted(
        candidates,
        key=lambda item: reviewed_candidate_sort_key(item, settings),
        reverse=True,
    )


def candidate_is_eligible_for_vision_review(candidate: YouTubeCandidate, settings: YouTubeRankingSettings) -> bool:
    if not candidate_is_duration_eligible_for_review(candidate, settings):
        return False
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    if isinstance(payload.get("posePrefilter"), dict):
        return candidate.status != "rejected" and candidate_pose_prefilter_passed(candidate)
    if settings.pose_prefilter_enabled:
        return candidate_pose_prefilter_passed(candidate)
    if settings.semantic_gate_enabled:
        return candidate_semantic_gate_passed(candidate) and candidate.status != "rejected"
    return True


def run_youtube_candidate_review_pass(
    *,
    exercise: ExerciseEntry,
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
    debug_candidates_by_key: dict[str, YouTubeCandidate],
    semantic_gate: SemanticGateFn | None,
    pose_ranker: PoseRankerFn | None,
    vision_ranker: VisionRankerFn | None,
    exercise_motion_contract: dict[str, Any] | None = None,
) -> CandidateReviewPassResult:
    reviewed = list(ranked)
    debug_by_key = dict(debug_candidates_by_key)
    semantic_elapsed = 0.0
    pose_elapsed = 0.0
    vision_elapsed = 0.0

    if settings.semantic_gate_enabled:
        semantic_gate_started = time.monotonic()
        reviewed = rank_candidates_with_semantic_gate(
            exercise=exercise,
            ranked=reviewed,
            settings=settings,
            semantic_gate=semantic_gate,
            debug_scored_by_key=debug_by_key,
        )
        semantic_elapsed = time.monotonic() - semantic_gate_started

    if settings.pose_prefilter_enabled:
        pose_started = time.monotonic()
        reviewed = rank_candidates_with_pose_prefilter(
            exercise=exercise,
            ranked=reviewed,
            settings=settings,
            pose_ranker=pose_ranker,
            exercise_motion_contract=exercise_motion_contract,
        )
        debug_by_key.update({candidate.key(): candidate for candidate in reviewed})
        pose_elapsed = time.monotonic() - pose_started

    if settings.rank_with_vision:
        vision_started = time.monotonic()
        vision_candidates = [
            candidate
            for candidate in reviewed
            if candidate_is_eligible_for_vision_review(candidate, settings)
        ]
        active_vision_ranker = vision_ranker
        owned_vision_ranker: LlamaCppVisionRanker | None = None
        if active_vision_ranker is None:
            owned_vision_ranker = LlamaCppVisionRanker(settings)
            active_vision_ranker = owned_vision_ranker
        try:
            if isinstance(active_vision_ranker, LlamaCppVisionRanker):
                reranked = rank_candidates_with_prepared_vision_reviews(
                    exercise=exercise,
                    ranked=vision_candidates,
                    settings=settings,
                    vision_ranker=active_vision_ranker,
                    exercise_motion_contract=exercise_motion_contract,
                )
            else:
                reranked = rank_candidates_with_vision_ranker(
                    exercise=exercise,
                    ranked=vision_candidates,
                    settings=settings,
                    vision_ranker=active_vision_ranker,
                )
        finally:
            if owned_vision_ranker is not None:
                owned_vision_ranker.close()
        reranked_by_key = {candidate.key(): candidate for candidate in reranked}
        reviewed = [reranked_by_key.get(candidate.key(), candidate) for candidate in reviewed]
        debug_by_key.update({candidate.key(): candidate for candidate in reviewed})
        vision_elapsed = time.monotonic() - vision_started
        reviewed = sort_youtube_reviewed_candidates(reviewed, settings)
    else:
        reviewed = sort_youtube_reviewed_candidates(reviewed, settings)

    return CandidateReviewPassResult(
        ranked=reviewed,
        debug_candidates_by_key=debug_by_key,
        semantic_elapsed_seconds=semantic_elapsed,
        pose_elapsed_seconds=pose_elapsed,
        vision_elapsed_seconds=vision_elapsed,
    )


def youtube_candidate_is_suitable_after_review(
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> bool:
    if candidate.status != "recommended":
        return False
    if settings.pose_prefilter_enabled and not candidate_pose_prefilter_passed(candidate):
        return False
    if (
        settings.semantic_gate_enabled
        and not settings.pose_prefilter_enabled
        and not candidate_semantic_gate_passed(candidate)
    ):
        return False
    if settings.rank_with_vision and candidate.vision_score is None:
        return False
    return True


def youtube_suitable_candidate_count(
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
) -> int:
    return sum(1 for candidate in ranked if youtube_candidate_is_suitable_after_review(candidate, settings))


def demote_candidates_missing_required_review(
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
) -> list[YouTubeCandidate]:
    """Do not advertise pose-only candidates as fully recommended sources."""
    if not settings.rank_with_vision:
        return ranked
    return [
        replace_candidate(
            candidate,
            status="candidate",
            score_reasons=dedupe_reasons([*candidate.score_reasons, "vision_review_not_completed"]),
        )
        if candidate.status == "recommended" and candidate.vision_score is None
        else candidate
        for candidate in ranked
    ]


def run_youtube_candidate_review_batches(
    *,
    exercise: ExerciseEntry,
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
    debug_candidates_by_key: dict[str, YouTubeCandidate],
    semantic_gate: SemanticGateFn | None,
    pose_ranker: PoseRankerFn | None,
    vision_ranker: VisionRankerFn | None,
    exercise_motion_contract: dict[str, Any] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> CandidateReviewPassResult:
    if not ranked:
        return CandidateReviewPassResult(ranked=[], debug_candidates_by_key=dict(debug_candidates_by_key))

    batch_size = settings.resolved_candidate_review_batch_size()
    target_suitable_count = settings.resolved_candidate_review_target_suitable_count()
    reviewed_by_key: dict[str, YouTubeCandidate] = {}
    debug_by_key = dict(debug_candidates_by_key)
    review_batches: list[dict[str, Any]] = []
    semantic_elapsed = 0.0
    pose_elapsed = 0.0
    vision_elapsed = 0.0

    bounded_ranked = ranked[:youtube_candidate_review_hard_cap(settings)]
    for batch_index, start in enumerate(range(0, len(bounded_ranked), batch_size), start=1):
        batch = bounded_ranked[start : start + batch_size]
        if not batch:
            continue
        pass_result = run_youtube_candidate_review_pass(
            exercise=exercise,
            ranked=batch,
            settings=settings,
            debug_candidates_by_key=debug_by_key,
            semantic_gate=semantic_gate,
            pose_ranker=pose_ranker,
            vision_ranker=vision_ranker,
            exercise_motion_contract=exercise_motion_contract,
        )
        semantic_elapsed += pass_result.semantic_elapsed_seconds
        pose_elapsed += pass_result.pose_elapsed_seconds
        vision_elapsed += pass_result.vision_elapsed_seconds
        debug_by_key = pass_result.debug_candidates_by_key
        for candidate in pass_result.ranked:
            reviewed_by_key[candidate.key()] = candidate
            debug_by_key[candidate.key()] = candidate
        accumulated_ranked = sort_youtube_reviewed_candidates(reviewed_by_key.values(), settings)
        suitable_count = youtube_suitable_candidate_count(accumulated_ranked, settings)
        batch_payload = {
            "batchIndex": batch_index,
            "startIndex": start,
            "endIndexExclusive": start + len(batch),
            "inputCandidateCount": len(batch),
            "reviewedCandidateCount": len(reviewed_by_key),
            "suitableCandidateCount": suitable_count,
            "targetSuitableCandidateCount": target_suitable_count,
            "semanticGateElapsedSeconds": round_elapsed(pass_result.semantic_elapsed_seconds),
            "posePrefilterElapsedSeconds": round_elapsed(pass_result.pose_elapsed_seconds),
            "visionScoringElapsedSeconds": round_elapsed(pass_result.vision_elapsed_seconds),
            "stoppedAfterBatch": False,
        }
        if suitable_count >= target_suitable_count:
            batch_payload["stoppedAfterBatch"] = True
            batch_payload["stopReason"] = "target_suitable_candidate_count_reached"
        review_batches.append(batch_payload)
        if progress_callback is not None:
            progress_callback(dict(batch_payload))
        if suitable_count >= target_suitable_count:
            break

    ranked_reviewed = demote_candidates_missing_required_review(
        sort_youtube_reviewed_candidates(reviewed_by_key.values(), settings),
        settings,
    )
    if not ranked_reviewed:
        ranked_reviewed = sort_youtube_reviewed_candidates(ranked, settings)
    return CandidateReviewPassResult(
        ranked=ranked_reviewed,
        debug_candidates_by_key=debug_by_key,
        semantic_elapsed_seconds=semantic_elapsed,
        pose_elapsed_seconds=pose_elapsed,
        vision_elapsed_seconds=vision_elapsed,
        review_batches=review_batches,
    )


def youtube_candidate_review_can_expand(settings: YouTubeRankingSettings, available_count: int) -> bool:
    if available_count <= 0:
        return False
    limits: list[int] = []
    if settings.semantic_gate_enabled:
        limits.append(settings.resolved_semantic_gate_max_candidates_per_exercise())
    if settings.pose_prefilter_enabled:
        limits.append(settings.resolved_pose_prefilter_candidates_per_exercise())
    if settings.rank_with_vision:
        limits.append(max(0, settings.vision_candidates_per_exercise))
    return any(limit < available_count for limit in limits)


def youtube_candidate_review_hard_cap(settings: YouTubeRankingSettings) -> int:
    limits = [max(1, settings.max_candidates)]
    if settings.semantic_gate_enabled:
        limits.append(settings.resolved_semantic_gate_max_candidates_per_exercise())
    if settings.pose_prefilter_enabled:
        limits.append(settings.resolved_pose_prefilter_candidates_per_exercise())
    if settings.rank_with_vision:
        limits.append(max(1, settings.vision_candidates_per_exercise))
    return max(limits)


def youtube_candidate_search_can_expand(settings: YouTubeRankingSettings) -> bool:
    return settings.semantic_gate_enabled or settings.pose_prefilter_enabled or settings.rank_with_vision


def expanded_youtube_candidate_review_settings(
    settings: YouTubeRankingSettings,
    available_count: int,
) -> YouTubeRankingSettings:
    changes: dict[str, Any] = {}
    if settings.semantic_gate_enabled:
        changes["semantic_gate_max_candidates_per_exercise"] = min(
            available_count,
            settings.resolved_semantic_gate_max_candidates_per_exercise(),
        )
    if settings.pose_prefilter_enabled:
        changes["pose_prefilter_candidates_per_exercise"] = min(
            available_count,
            settings.resolved_pose_prefilter_candidates_per_exercise(),
        )
    if settings.rank_with_vision:
        changes["vision_candidates_per_exercise"] = min(available_count, settings.vision_candidates_per_exercise)
    return dataclass_replace(settings, **changes)


def build_youtube_candidate_expansion_payload(
    *,
    settings: YouTubeRankingSettings,
    available_count: int,
    initial_suitable_count: int,
) -> dict[str, Any]:
    return {
        "triggered": False,
        "reason": None,
        "reviewExpansionTriggered": False,
        "searchExpansionTriggered": False,
        "availableReviewCandidates": available_count,
        "initialSuitableCandidateCount": initial_suitable_count,
        "reviewBatchSize": settings.resolved_candidate_review_batch_size(),
        "reviewTargetSuitableCandidateCount": settings.resolved_candidate_review_target_suitable_count(),
        "reviewBatchingEnabled": settings.resolved_candidate_review_batch_size() < available_count,
        "initialSemanticGateCandidatesPerExercise": (
            settings.resolved_semantic_gate_candidates_per_exercise()
            if settings.semantic_gate_enabled
            else None
        ),
        "initialSemanticGateMaxCandidatesPerExercise": (
            settings.resolved_semantic_gate_max_candidates_per_exercise()
            if settings.semantic_gate_enabled
            else None
        ),
        "initialSemanticGateTargetPassCount": (
            settings.resolved_semantic_gate_target_pass_count()
            if settings.semantic_gate_enabled
            else None
        ),
        "initialPosePrefilterCandidatesPerExercise": (
            settings.resolved_pose_prefilter_candidates_per_exercise()
            if settings.pose_prefilter_enabled
            else None
        ),
        "initialVisionCandidatesPerExercise": (
            settings.vision_candidates_per_exercise
            if settings.rank_with_vision
            else None
        ),
    }


def expanded_youtube_search_results_per_query(settings: YouTubeRankingSettings) -> int | None:
    current = max(1, settings.results_per_query)
    expanded = max(
        current + YOUTUBE_FAILURE_SEARCH_EXPANSION_MIN_INCREMENT,
        current * YOUTUBE_FAILURE_SEARCH_EXPANSION_MULTIPLIER,
    )
    expanded = min(expanded, YOUTUBE_FAILURE_SEARCH_EXPANSION_MAX_RESULTS_PER_QUERY)
    if expanded <= current:
        return None
    return expanded


def collect_youtube_search_candidates(
    *,
    queries: list[str],
    settings: YouTubeRankingSettings,
    search_fn: SearchFn,
    existing_by_key: dict[str, YouTubeCandidate] | None = None,
    phase: str = "initial",
) -> YouTubeSearchPassResult:
    excluded_keys = set(settings.excluded_candidate_keys)
    by_key = {
        key: candidate
        for key, candidate in dict(existing_by_key or {}).items()
        if not youtube_candidate_is_excluded(candidate, excluded_keys)
    }
    initial_count = len(by_key)
    search_errors: list[dict[str, Any]] = []
    search_attempts: list[dict[str, Any]] = []
    elapsed_total = 0.0
    excluded_total = 0
    for query in queries:
        search_started = time.monotonic()
        try:
            search_results, attempts = search_youtube_with_empty_retries(
                query,
                settings=settings,
                search_fn=search_fn,
            )
            elapsed_total += time.monotonic() - search_started
            new_for_query = 0
            excluded_for_query = 0
            excluded_candidates_for_query: list[dict[str, Any]] = []
            for candidate in search_results:
                if not candidate.url:
                    continue
                if youtube_candidate_is_excluded(candidate, excluded_keys):
                    excluded_for_query += 1
                    excluded_candidates_for_query.append(
                        youtube_candidate_exclusion_debug_payload(candidate, excluded_keys)
                    )
                    continue
                key = candidate.key()
                if key not in by_key:
                    by_key[key] = candidate
                    new_for_query += 1
            excluded_total += excluded_for_query
            search_attempts.append(
                {
                    "query": query,
                    "phase": phase,
                    "resultsPerQuery": settings.results_per_query,
                    "attempts": attempts,
                    "resultCount": len(search_results),
                    "excludedCandidateCount": excluded_for_query,
                    "excludedCandidates": excluded_candidates_for_query,
                    "newCandidateCount": new_for_query,
                }
            )
        except YouTubeSearchError:
            elapsed_total += time.monotonic() - search_started
            raise
        except Exception as exc:
            elapsed_total += time.monotonic() - search_started
            search_errors.append(
                {
                    "query": query,
                    "phase": phase,
                    "resultsPerQuery": settings.results_per_query,
                    "error": str(exc),
                }
            )
            continue
    return YouTubeSearchPassResult(
        by_key=by_key,
        search_errors=search_errors,
        search_attempts=search_attempts,
        elapsed_seconds=elapsed_total,
        new_candidate_count=len(by_key) - initial_count,
        excluded_candidate_count=excluded_total,
    )


def rank_candidate_with_yolo_pose(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
    exercise_motion_contract: dict[str, Any] | None = None,
) -> PoseRankResult:
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
                device=settings.pose_prefilter_device,
                batch_size=settings.pose_prefilter_batch_size,
                target_exercise_name=exercise.name,
                target_motion_contract=exercise_motion_contract,
            ),
        )
        return result.score, result.reasons, result.payload
    finally:
        temp_dir.cleanup()


def vision_backend_name(settings: YouTubeRankingSettings) -> str:
    return "llama-cpp-server"


def default_llama_cpp_mmproj_path() -> str:
    return DEFAULT_LLAMA_CPP_MMPROJ


def default_llama_cpp_server_path() -> str:
    return DEFAULT_LLAMA_CPP_SERVER_COMMAND


def resolve_llama_cpp_server_command(
    *,
    configured_command: str | None,
) -> str:
    if configured_command:
        return configured_command
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


def _netstat_listener_pids_for_port(port: int) -> list[int]:
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    pids: list[int] = []
    listener_pattern = re.compile(
        rf"^\s*TCP\s+\S+:{re.escape(str(port))}\s+\S+\s+LISTENING\s+(\d+)\s*$",
        re.IGNORECASE,
    )
    for line in completed.stdout.splitlines():
        match = listener_pattern.match(line)
        if not match:
            continue
        try:
            pid = int(match.group(1))
        except ValueError:
            continue
        if pid not in pids:
            pids.append(pid)
    return pids


def _process_command_line_for_pid(pid: int) -> str | None:
    if pid <= 0:
        return None
    proc_cmdline = Path("/proc") / str(pid) / "cmdline"
    try:
        raw = proc_cmdline.read_bytes()
    except OSError:
        raw = b""
    if raw:
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    if os.name != "nt":
        return None
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return None
    command = (
        f"(Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\" "
        "| Select-Object -ExpandProperty CommandLine)"
    )
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    command_line = completed.stdout.strip()
    return command_line or None


def llama_cpp_server_command_lines_for_base_url(base_url: str | None) -> list[str]:
    try:
        port = int(parse_llama_cpp_base_url(base_url)["port"])
    except (TypeError, ValueError):
        return []
    command_lines: list[str] = []
    for pid in _netstat_listener_pids_for_port(port):
        command_line = _process_command_line_for_pid(pid)
        if command_line and command_line not in command_lines:
            command_lines.append(command_line)
    return command_lines


def _looks_like_llama_cpp_server_command(
    command_line: str | None,
    *,
    expected_command: str | None,
    expected_model: str | None,
) -> bool:
    if not command_line:
        return False
    normalized = re.sub(r"\s+", " ", command_line).casefold()
    expected_command_name = Path(expected_command).name.casefold() if expected_command else ""
    expected_model_name = Path(expected_model).name.casefold() if expected_model else ""
    if expected_model_name and expected_model_name in normalized:
        return True
    if expected_command_name and expected_command_name in normalized:
        return True
    return "llama-server" in normalized


def _terminate_process_for_gpu_exclusive_phase(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0
    try:
        os.kill(pid, 15)
    except OSError:
        return False
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.2)
    try:
        os.kill(pid, 9)
    except OSError:
        return True
    return True


def stop_llama_cpp_servers_for_base_url(
    base_url: str | None,
    *,
    expected_command: str | None = None,
    expected_model: str | None = None,
) -> list[int]:
    try:
        port = int(parse_llama_cpp_base_url(base_url)["port"])
    except (TypeError, ValueError):
        return []
    stopped: list[int] = []
    for pid in _netstat_listener_pids_for_port(port):
        command_line = _process_command_line_for_pid(pid)
        if not _looks_like_llama_cpp_server_command(
            command_line,
            expected_command=expected_command,
            expected_model=expected_model,
        ):
            continue
        if _terminate_process_for_gpu_exclusive_phase(pid):
            stopped.append(pid)
    return stopped


def llama_cpp_server_reasoning_flag_conflict(command_line: str, *, disable_reasoning: bool) -> str | None:
    normalized = re.sub(r"\s+", " ", command_line).casefold()
    reasoning_off = bool(
        re.search(r"(?:^|\s)--reasoning(?:\s+|=)off(?:\s|$)", normalized)
        or re.search(r"(?:^|\s)--reasoning-format(?:\s+|=)none(?:\s|$)", normalized)
    )
    reasoning_on = bool(
        re.search(r"(?:^|\s)--reasoning(?:\s+|=)on(?:\s|$)", normalized)
        or re.search(r"(?:^|\s)--reasoning-format(?:\s+|=)deepseek(?:\s|$)", normalized)
    )
    # llama.cpp accepts per-request reasoning_format=none on a server that was
    # started with reasoning enabled, so no-reasoning calls can safely reuse it.
    if not disable_reasoning and reasoning_off:
        return "started with reasoning disabled"
    return None


def llama_cpp_server_reasoning_budget(command_line: str) -> int | None:
    normalized = re.sub(r"\s+", " ", command_line).casefold()
    match = re.search(r"(?:^|\s)--reasoning-budget(?:\s+|=)(-?\d+)(?:\s|$)", normalized)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def llama_cpp_server_reasoning_budget_conflict(
    command_line: str,
    *,
    expected_budget: int | None,
    disable_reasoning: bool,
) -> str | None:
    if disable_reasoning or expected_budget is None:
        return None
    actual_budget = llama_cpp_server_reasoning_budget(command_line)
    if actual_budget == expected_budget:
        return None
    actual = "unrestricted or unspecified" if actual_budget is None else str(actual_budget)
    return f"started with reasoning budget {actual}"


def llama_cpp_server_parallel(command_line: str) -> int | None:
    normalized = re.sub(r"\s+", " ", command_line).casefold()
    match = re.search(r"(?:^|\s)--parallel(?:\s+|=)(\d+)(?:\s|$)", normalized)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def llama_cpp_server_mtp_conflict(command_line: str, *, expected_model: str | None) -> str | None:
    normalized = re.sub(r"\s+", " ", command_line).casefold()
    has_mtp = "--spec-type draft-mtp" in normalized and "--model-draft" in normalized
    if expected_model is None:
        return "started with MTP enabled" if has_mtp else None
    expected_name = Path(expected_model).name.casefold()
    if not has_mtp:
        return "started without MTP enabled"
    if expected_name not in normalized:
        return f"started with a different MTP model than {Path(expected_model).name}"
    return None


def discover_and_rank_youtube_candidates(
    *,
    workout_plan_json: Path,
    equipment_json: Path | None = None,
    out_json: Path,
    settings: YouTubeRankingSettings,
    search_fn: SearchFn = search_youtube,
    query_planner: QueryPlannerFn | None = None,
    semantic_gate: SemanticGateFn | None = None,
    pose_ranker: PoseRankerFn | None = None,
    vision_ranker: VisionRankerFn | None = None,
    exercise_name_rewriter: ExerciseNameRewriteFn | None = None,
    exercise_motion_contract_provider: ExerciseMotionContractProviderFn | None = None,
) -> dict[str, Any]:
    run_started = time.monotonic()
    progress_path = out_json.with_name("youtube_discovery_progress.jsonl")
    if progress_path.exists():
        progress_path.unlink()
    append_youtube_discovery_progress(
        progress_path,
        event="discovery_started",
        started_at=run_started,
        sourcePlanPath=str(workout_plan_json),
        maxCandidates=settings.max_candidates,
        candidateReviewBatchSize=settings.resolved_candidate_review_batch_size(),
        candidateReviewTargetSuitableCount=settings.resolved_candidate_review_target_suitable_count(),
        semanticGateEnabled=settings.semantic_gate_enabled,
        posePrefilterEnabled=settings.pose_prefilter_enabled,
        visionEnabled=settings.rank_with_vision,
    )
    search_elapsed_total = 0.0
    review_pool_elapsed_total = 0.0
    semantic_gate_elapsed_total = 0.0
    pose_elapsed_total = 0.0
    vision_elapsed_total = 0.0
    exercise_name_rewrite_elapsed_total = 0.0
    exercise_motion_contract_elapsed_total = 0.0
    excluded_candidate_total = 0
    exercises = load_workout_plan_exercises(
        workout_plan_json,
        include_disabled=settings.include_disabled,
        equipment_path=equipment_json,
    )
    vision_enabled = settings.rank_with_vision
    owns_vision_ranker = False
    owns_query_planner = False
    query_planner_backend: str | None = None
    if settings.use_llama_cpp_query_planner and query_planner is None:
        query_planner = LlamaCppYouTubeQueryPlanner(
            settings,
            shared_ranker=vision_ranker if isinstance(vision_ranker, LlamaCppVisionRanker) else None,
        )
        owns_query_planner = True
        query_planner_backend = "llama-cpp"
    elif settings.use_deepseek_query_planner and query_planner is None:
        query_planner = DeepSeekYouTubeQueryPlanner(settings)
        owns_query_planner = True
        query_planner_backend = "deepseek"
    elif query_planner is not None:
        query_planner_backend = "custom"
    exercise_motion_contract_backend: str | None = None
    if settings.exercise_motion_contract_enabled and vision_enabled:
        if exercise_motion_contract_provider is not None:
            exercise_motion_contract_backend = "custom"
        else:
            exercise_motion_contract_backend = "llama-cpp"
    owns_semantic_gate = False
    semantic_gate_ranker: LlamaCppSemanticGate | None = None
    if settings.semantic_gate_enabled and semantic_gate is None:
        semantic_gate_ranker = LlamaCppSemanticGate(
            settings,
            shared_ranker=vision_ranker if isinstance(vision_ranker, LlamaCppVisionRanker) else None,
        )
        owns_semantic_gate = True
        semantic_gate = semantic_gate_ranker
    exercise_payloads: list[dict[str, Any]] = []
    try:
        for source_exercise in exercises:
            append_youtube_discovery_progress(
                progress_path,
                event="exercise_started",
                started_at=run_started,
                exercise=source_exercise,
                sourceExerciseName=source_exercise.source_name,
                equipmentQualifiedExerciseName=source_exercise.equipment_qualified_name,
            )
            rewrite_started = time.monotonic()
            exercise_name_rewrite_ranker: LlamaCppVisionRanker | None = None
            if (
                exercise_name_rewriter is None
                and settings.exercise_name_rewrite_enabled
                and settings.llama_cpp_base_url is not None
            ):
                exercise_name_rewrite_ranker = LlamaCppVisionRanker(text_llama_cpp_settings(settings))
            if exercise_name_rewriter is not None:
                try:
                    exercise, exercise_name_rewrite_payload = exercise_name_rewriter(
                        source_exercise,
                        settings,
                        exercise_name_rewrite_ranker,
                    )
                finally:
                    if exercise_name_rewrite_ranker is not None:
                        exercise_name_rewrite_ranker.close()
            else:
                try:
                    exercise, exercise_name_rewrite_payload = resolve_exercise_name_rewrite(
                        source_exercise,
                        settings,
                        exercise_name_rewrite_ranker,
                    )
                finally:
                    if exercise_name_rewrite_ranker is not None:
                        exercise_name_rewrite_ranker.close()
            exercise_name_rewrite_elapsed_total += time.monotonic() - rewrite_started
            append_youtube_discovery_progress(
                progress_path,
                event="exercise_name_rewrite_completed",
                started_at=run_started,
                exercise=exercise,
                stageElapsedSeconds=round_elapsed(time.monotonic() - rewrite_started),
                status=exercise_name_rewrite_payload.get("status"),
                applied=exercise_name_rewrite_payload.get("applied"),
                rewrittenExerciseName=exercise_name_rewrite_payload.get("rewrittenExerciseName"),
            )

            exercise_motion_contract: dict[str, Any] | None = None
            if settings.exercise_motion_contract_enabled and vision_enabled:
                contract_started = time.monotonic()
                contract_ranker: LlamaCppVisionRanker | None = None
                if exercise_motion_contract_provider is not None:
                    try:
                        provider_payload = exercise_motion_contract_provider(exercise, settings)
                        if provider_payload is None:
                            exercise_motion_contract = {
                                "schemaVersion": 1,
                                "enabled": True,
                                "status": "skipped",
                                "source": "custom",
                                "exerciseName": exercise.name,
                                "reason": "provider_returned_none",
                            }
                        elif isinstance(provider_payload, str):
                            exercise_motion_contract = normalize_exercise_motion_contract_response(
                                provider_payload,
                                exercise=exercise,
                                source="custom",
                            )
                        else:
                            exercise_motion_contract = normalize_exercise_motion_contract(
                                provider_payload,
                                exercise=exercise,
                                source="custom",
                            )
                    except Exception as exc:
                        exercise_motion_contract = {
                            "schemaVersion": 1,
                            "enabled": True,
                            "status": "failed",
                            "source": "custom",
                            "exerciseName": exercise.name,
                            "error": truncate_text(str(exc), 240),
                        }
                elif settings.llama_cpp_base_url is not None:
                    contract_settings = exercise_contract_llama_cpp_settings(settings)
                    contract_ranker = LlamaCppVisionRanker(contract_settings)
                    try:
                        exercise_motion_contract = generate_exercise_motion_contract_with_ranker(
                            exercise=exercise,
                            settings=contract_settings,
                            ranker=contract_ranker,
                        )
                    finally:
                        contract_ranker.close()
                else:
                    exercise_motion_contract = {
                        "schemaVersion": 1,
                        "enabled": True,
                        "status": "skipped",
                        "source": "none",
                        "exerciseName": exercise.name,
                        "reason": "no_llama_cpp_vision_ranker",
                    }
                exercise_motion_contract_elapsed_total += time.monotonic() - contract_started
                append_youtube_discovery_progress(
                    progress_path,
                    event="exercise_motion_contract_completed",
                    started_at=run_started,
                    exercise=exercise,
                    stageElapsedSeconds=round_elapsed(time.monotonic() - contract_started),
                    status=exercise_motion_contract.get("status") if isinstance(exercise_motion_contract, dict) else None,
                    source=exercise_motion_contract.get("source") if isinstance(exercise_motion_contract, dict) else None,
                    targetMotionProfile=(
                        exercise_motion_contract.get("targetMotionProfile")
                        if isinstance(exercise_motion_contract, dict)
                        else None
                    ),
                    aliasCount=(
                        len(exercise_motion_contract.get("youtubeQueryAliases") or [])
                        if isinstance(exercise_motion_contract, dict)
                        else None
                    ),
                    error=(
                        exercise_motion_contract.get("error")
                        if isinstance(exercise_motion_contract, dict)
                        else None
                    ),
                    reason=(
                        exercise_motion_contract.get("reason")
                        if isinstance(exercise_motion_contract, dict)
                        else None
                    ),
                )
            review_motion_contract = exercise_motion_contract

            queries = (
                merge_youtube_queries([quote_youtube_search_term(exercise.name)], limit=1)
                if settings.single_exercise_name_query and exercise.name.strip()
                else build_youtube_queries_with_contract_aliases(exercise.name, exercise_motion_contract)
            )
            query_planning_payload: dict[str, Any] = {
                "enabled": query_planner is not None and not settings.single_exercise_name_query,
                "backend": None if settings.single_exercise_name_query else query_planner_backend,
                "status": (
                    "skipped_single_exercise_name_query"
                    if settings.single_exercise_name_query
                    else "skipped" if query_planner is None else "pending"
                ),
                "addedQueries": [],
            }
            if query_planner is not None and not settings.single_exercise_name_query:
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
                finally:
                    if owns_query_planner and isinstance(query_planner, LlamaCppYouTubeQueryPlanner):
                        query_planner.close()
            append_youtube_discovery_progress(
                progress_path,
                event="query_planning_completed",
                started_at=run_started,
                exercise=exercise,
                status=query_planning_payload.get("status"),
                queryCount=len(queries),
                addedQueryCount=len(query_planning_payload.get("addedQueries") or []),
                addedQueries=query_planning_payload.get("addedQueries") or [],
            )
            search_result = collect_youtube_search_candidates(
                queries=queries,
                settings=settings,
                search_fn=search_fn,
            )
            by_key = search_result.by_key
            search_errors = search_result.search_errors
            search_attempts = search_result.search_attempts
            search_elapsed_total += search_result.elapsed_seconds
            excluded_candidate_total += search_result.excluded_candidate_count
            append_youtube_discovery_progress(
                progress_path,
                event="search_completed",
                started_at=run_started,
                exercise=exercise,
                stageElapsedSeconds=round_elapsed(search_result.elapsed_seconds),
                queryCount=len(queries),
                totalCandidateCount=len(by_key),
                newCandidateCount=search_result.new_candidate_count,
                excludedCandidateCount=search_result.excluded_candidate_count,
                searchErrorCount=len(search_errors),
            )

            review_pool_started = time.monotonic()
            prepared_ranked = [
                prepare_candidate_for_review(
                    exercise,
                    candidate,
                    min_duration_seconds=settings.min_duration_seconds,
                    max_duration_seconds=settings.max_duration_seconds,
                )
                for candidate in by_key.values()
            ]
            ranked = rank_youtube_review_pool(exercise, prepared_ranked, settings)
            review_pool_elapsed_total += time.monotonic() - review_pool_started
            review_pool_ranked = ranked
            debug_candidates_by_key: dict[str, YouTubeCandidate] = {
                candidate.key(): candidate
                for candidate in prepared_ranked
            }
            append_youtube_discovery_progress(
                progress_path,
                event="review_pool_selected",
                started_at=run_started,
                exercise=exercise,
                stageElapsedSeconds=round_elapsed(time.monotonic() - review_pool_started),
                totalSearchCandidateCount=len(prepared_ranked),
                reviewCandidateCount=len(review_pool_ranked),
                skippedReviewCandidateCount=max(0, len(prepared_ranked) - len(review_pool_ranked)),
                durationEligibleCandidateCount=sum(
                    1 for candidate in prepared_ranked if candidate_is_duration_eligible_for_review(candidate, settings)
                ),
            )

            def log_review_batch(phase: str) -> Callable[[dict[str, Any]], None]:
                def _log(batch_payload: dict[str, Any]) -> None:
                    append_youtube_discovery_progress(
                        progress_path,
                        event="candidate_review_batch_completed",
                        started_at=run_started,
                        exercise=exercise,
                        phase=phase,
                        **batch_payload,
                    )

                return _log

            review_result = run_youtube_candidate_review_batches(
                exercise=exercise,
                ranked=review_pool_ranked,
                settings=settings,
                debug_candidates_by_key=debug_candidates_by_key,
                semantic_gate=semantic_gate,
                pose_ranker=pose_ranker,
                vision_ranker=vision_ranker,
                exercise_motion_contract=review_motion_contract,
                progress_callback=log_review_batch("initial"),
            )
            ranked = review_result.ranked
            debug_candidates_by_key = review_result.debug_candidates_by_key
            semantic_gate_elapsed_total += review_result.semantic_elapsed_seconds
            pose_elapsed_total += review_result.pose_elapsed_seconds
            vision_elapsed_total += review_result.vision_elapsed_seconds

            initial_suitable_count = youtube_suitable_candidate_count(ranked, settings)
            initial_review_hard_cap = youtube_candidate_review_hard_cap(settings)
            initial_review_hard_cap_exhausted = bool(
                review_result.review_batches
                and int(review_result.review_batches[-1].get("endIndexExclusive") or 0)
                >= min(len(review_pool_ranked), initial_review_hard_cap)
            )
            candidate_expansion_payload = build_youtube_candidate_expansion_payload(
                settings=settings,
                available_count=len(review_pool_ranked),
                initial_suitable_count=initial_suitable_count,
            )
            candidate_expansion_payload.update(
                {
                    "reviewedBatchCount": len(review_result.review_batches),
                    "reviewBatches": review_result.review_batches,
                    "initialReviewedCandidateCount": (
                        review_result.review_batches[-1]["reviewedCandidateCount"]
                        if review_result.review_batches
                        else len(ranked)
                    ),
                    "initialReviewHardCap": initial_review_hard_cap,
                    "initialReviewHardCapExhausted": initial_review_hard_cap_exhausted,
                }
            )
            current_review_settings = settings
            if (
                initial_suitable_count == 0
                and not initial_review_hard_cap_exhausted
                and youtube_candidate_review_can_expand(settings, len(review_pool_ranked))
            ):
                append_youtube_discovery_progress(
                    progress_path,
                    event="review_expansion_started",
                    started_at=run_started,
                    exercise=exercise,
                    reason="no_suitable_candidate_after_initial_review",
                    initialSuitableCandidateCount=initial_suitable_count,
                    reviewCandidateCount=len(review_pool_ranked),
                )
                expanded_settings = expanded_youtube_candidate_review_settings(settings, len(review_pool_ranked))
                current_review_settings = expanded_settings
                expanded_result = run_youtube_candidate_review_batches(
                    exercise=exercise,
                    ranked=review_pool_ranked[:youtube_candidate_review_hard_cap(expanded_settings)],
                    settings=expanded_settings,
                    debug_candidates_by_key=debug_candidates_by_key,
                    semantic_gate=semantic_gate,
                    pose_ranker=pose_ranker,
                    vision_ranker=vision_ranker,
                    exercise_motion_contract=review_motion_contract,
                    progress_callback=log_review_batch("expanded_review"),
                )
                ranked = expanded_result.ranked
                debug_candidates_by_key = expanded_result.debug_candidates_by_key
                semantic_gate_elapsed_total += expanded_result.semantic_elapsed_seconds
                pose_elapsed_total += expanded_result.pose_elapsed_seconds
                vision_elapsed_total += expanded_result.vision_elapsed_seconds
                candidate_expansion_payload.update(
                    {
                        "triggered": True,
                        "reason": "no_suitable_candidate_after_initial_review",
                        "reviewExpansionTriggered": True,
                        "expandedSuitableCandidateCount": youtube_suitable_candidate_count(
                            ranked,
                            expanded_settings,
                        ),
                        "expandedReviewedBatchCount": len(expanded_result.review_batches),
                        "expandedReviewBatches": expanded_result.review_batches,
                        "expandedSemanticGateCandidatesPerExercise": (
                            expanded_settings.resolved_semantic_gate_candidates_per_exercise()
                            if expanded_settings.semantic_gate_enabled
                            else None
                        ),
                        "expandedSemanticGateMaxCandidatesPerExercise": (
                            expanded_settings.resolved_semantic_gate_max_candidates_per_exercise()
                            if expanded_settings.semantic_gate_enabled
                            else None
                        ),
                        "expandedSemanticGateTargetPassCount": (
                            expanded_settings.resolved_semantic_gate_target_pass_count()
                            if expanded_settings.semantic_gate_enabled
                            else None
                        ),
                        "expandedPosePrefilterCandidatesPerExercise": (
                            expanded_settings.resolved_pose_prefilter_candidates_per_exercise()
                            if expanded_settings.pose_prefilter_enabled
                            else None
                        ),
                        "expandedVisionCandidatesPerExercise": (
                            expanded_settings.vision_candidates_per_exercise
                            if expanded_settings.rank_with_vision
                            else None
                        ),
                    }
                )
            else:
                candidate_expansion_payload["expandedSuitableCandidateCount"] = initial_suitable_count

            expanded_results_per_query = expanded_youtube_search_results_per_query(settings)
            search_expansion_queries = build_youtube_search_expansion_queries(
                exercise.name,
                review_motion_contract,
                existing_queries=queries,
            )
            if (
                youtube_suitable_candidate_count(ranked, current_review_settings) == 0
                and not initial_review_hard_cap_exhausted
                and not settings.single_exercise_name_query
                and youtube_candidate_search_can_expand(settings)
                and (expanded_results_per_query is not None or search_expansion_queries)
            ):
                search_expansion_results_per_query = expanded_results_per_query or settings.results_per_query
                search_expansion_query_list = merge_youtube_queries(
                    [
                        *(queries if expanded_results_per_query is not None else []),
                        *search_expansion_queries,
                    ]
                )
                search_expanded_settings = dataclass_replace(
                    settings,
                    results_per_query=search_expansion_results_per_query,
                )
                expanded_search_result = collect_youtube_search_candidates(
                    queries=search_expansion_query_list,
                    settings=search_expanded_settings,
                    search_fn=search_fn,
                    existing_by_key=by_key,
                    phase="expanded_after_no_suitable_candidate",
                )
                by_key = expanded_search_result.by_key
                search_errors.extend(expanded_search_result.search_errors)
                search_attempts.extend(expanded_search_result.search_attempts)
                search_elapsed_total += expanded_search_result.elapsed_seconds
                excluded_candidate_total += expanded_search_result.excluded_candidate_count
                append_youtube_discovery_progress(
                    progress_path,
                    event="search_expansion_completed",
                    started_at=run_started,
                    exercise=exercise,
                    stageElapsedSeconds=round_elapsed(expanded_search_result.elapsed_seconds),
                    queryCount=len(search_expansion_query_list),
                    totalCandidateCount=len(by_key),
                    newCandidateCount=expanded_search_result.new_candidate_count,
                    excludedCandidateCount=expanded_search_result.excluded_candidate_count,
                )

                if expanded_search_result.new_candidate_count > 0:
                    review_pool_started = time.monotonic()
                    prepared_ranked = [
                        prepare_candidate_for_review(
                            exercise,
                            candidate,
                            min_duration_seconds=settings.min_duration_seconds,
                            max_duration_seconds=settings.max_duration_seconds,
                        )
                        for candidate in by_key.values()
                    ]
                    ranked = rank_youtube_review_pool(exercise, prepared_ranked, search_expanded_settings)
                    review_pool_elapsed_total += time.monotonic() - review_pool_started
                    review_pool_ranked = ranked
                    debug_candidates_by_key = {
                        candidate.key(): candidate
                        for candidate in prepared_ranked
                    }
                    append_youtube_discovery_progress(
                        progress_path,
                        event="review_pool_selected",
                        started_at=run_started,
                        exercise=exercise,
                        phase="expanded_search",
                        stageElapsedSeconds=round_elapsed(time.monotonic() - review_pool_started),
                        totalSearchCandidateCount=len(prepared_ranked),
                        reviewCandidateCount=len(review_pool_ranked),
                        skippedReviewCandidateCount=max(0, len(prepared_ranked) - len(review_pool_ranked)),
                        durationEligibleCandidateCount=sum(
                            1
                            for candidate in prepared_ranked
                            if candidate_is_duration_eligible_for_review(candidate, search_expanded_settings)
                        ),
                    )
                    search_review_settings = expanded_youtube_candidate_review_settings(
                        search_expanded_settings,
                        len(review_pool_ranked),
                    )
                    search_review_result = run_youtube_candidate_review_batches(
                        exercise=exercise,
                        ranked=review_pool_ranked[:youtube_candidate_review_hard_cap(search_review_settings)],
                        settings=search_review_settings,
                        debug_candidates_by_key=debug_candidates_by_key,
                        semantic_gate=semantic_gate,
                        pose_ranker=pose_ranker,
                        vision_ranker=vision_ranker,
                        exercise_motion_contract=review_motion_contract,
                        progress_callback=log_review_batch("expanded_search"),
                    )
                    ranked = search_review_result.ranked
                    debug_candidates_by_key = search_review_result.debug_candidates_by_key
                    semantic_gate_elapsed_total += search_review_result.semantic_elapsed_seconds
                    pose_elapsed_total += search_review_result.pose_elapsed_seconds
                    vision_elapsed_total += search_review_result.vision_elapsed_seconds
                    search_expanded_suitable_count = youtube_suitable_candidate_count(
                        ranked,
                        search_review_settings,
                    )
                    candidate_expansion_payload.update(
                        {
                            "triggered": True,
                            "reason": candidate_expansion_payload.get("reason")
                            or "no_suitable_candidate_after_initial_review",
                            "searchExpansionTriggered": True,
                            "searchExpansionReason": "no_suitable_candidate_after_expanded_review",
                            "searchExpansionInitialResultsPerQuery": settings.results_per_query,
                            "searchExpansionResultsPerQuery": search_expansion_results_per_query,
                            "searchExpansionQueryCount": len(search_expansion_query_list),
                            "searchExpansionAddedQueries": search_expansion_queries,
                            "searchExpansionNewCandidateCount": expanded_search_result.new_candidate_count,
                            "searchExpandedAvailableReviewCandidates": len(review_pool_ranked),
                            "searchExpandedSuitableCandidateCount": search_expanded_suitable_count,
                            "searchExpandedReviewedBatchCount": len(search_review_result.review_batches),
                            "searchExpandedReviewBatches": search_review_result.review_batches,
                            "searchExpandedSemanticGateCandidatesPerExercise": (
                                search_review_settings.resolved_semantic_gate_candidates_per_exercise()
                                if search_review_settings.semantic_gate_enabled
                                else None
                            ),
                            "searchExpandedSemanticGateMaxCandidatesPerExercise": (
                                search_review_settings.resolved_semantic_gate_max_candidates_per_exercise()
                                if search_review_settings.semantic_gate_enabled
                                else None
                            ),
                            "searchExpandedSemanticGateTargetPassCount": (
                                search_review_settings.resolved_semantic_gate_target_pass_count()
                                if search_review_settings.semantic_gate_enabled
                                else None
                            ),
                            "searchExpandedPosePrefilterCandidatesPerExercise": (
                                search_review_settings.resolved_pose_prefilter_candidates_per_exercise()
                                if search_review_settings.pose_prefilter_enabled
                                else None
                            ),
                            "searchExpandedVisionCandidatesPerExercise": (
                                search_review_settings.vision_candidates_per_exercise
                                if search_review_settings.rank_with_vision
                                else None
                            ),
                        }
                    )
                else:
                    candidate_expansion_payload.update(
                        {
                            "triggered": True,
                            "reason": candidate_expansion_payload.get("reason")
                            or "no_suitable_candidate_after_initial_review",
                            "searchExpansionTriggered": True,
                            "searchExpansionReason": "no_suitable_candidate_after_expanded_review",
                            "searchExpansionInitialResultsPerQuery": settings.results_per_query,
                            "searchExpansionResultsPerQuery": search_expansion_results_per_query,
                            "searchExpansionQueryCount": len(search_expansion_query_list),
                            "searchExpansionAddedQueries": search_expansion_queries,
                            "searchExpansionNewCandidateCount": 0,
                            "searchExpandedAvailableReviewCandidates": len(review_pool_ranked),
                            "searchExpandedSuitableCandidateCount": youtube_suitable_candidate_count(
                                ranked,
                                current_review_settings,
                            ),
                        }
                    )

            ranked = ranked[: settings.max_candidates]
            debug_ranked = sorted(
                debug_candidates_by_key.values(),
                key=lambda item: (
                    candidate_has_debug_review_payload(item),
                    item.status == "recommended",
                    item.status == "candidate",
                    item.vision_score is not None,
                    semantic_gate_ranking_score(item, settings),
                    item.final_score,
                    semantic_gate_score(item),
                    semantic_gate_duration_preference_score(item, settings),
                    semantic_gate_duration_sort_value(item),
                ),
                reverse=True,
            )
            debug_limit = len(debug_ranked)

            exercise_payloads.append(
                {
                    "exerciseId": exercise.exercise_id,
                    "exerciseName": exercise.name,
                    "sourceExerciseName": exercise.source_name,
                    "equipmentQualifiedExerciseName": exercise.equipment_qualified_name,
                    "exerciseNameRewrite": exercise_name_rewrite_payload,
                    "slug": exercise.slug,
                    "queries": queries,
                    "queryPlanning": query_planning_payload,
                    "exerciseMotionContract": exercise_motion_contract,
                    "searchErrors": search_errors,
                    "searchAttempts": search_attempts,
                    "candidateExpansion": candidate_expansion_payload,
                    "candidates": [candidate.to_manifest_dict() for candidate in ranked],
                    "debugCandidates": [
                        candidate.to_manifest_dict()
                        for candidate in debug_ranked[:debug_limit]
                    ],
                }
            )
            append_youtube_discovery_progress(
                progress_path,
                event="exercise_completed",
                started_at=run_started,
                exercise=exercise,
                selectedCandidateCount=len(ranked[: settings.max_candidates]),
                suitableCandidateCount=youtube_suitable_candidate_count(ranked, current_review_settings),
                candidateExpansionTriggered=bool(candidate_expansion_payload.get("triggered")),
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
        "reviewPoolPreparationElapsedSeconds": round_elapsed(review_pool_elapsed_total),
        "semanticGateElapsedSeconds": round_elapsed(semantic_gate_elapsed_total),
        "posePrefilterElapsedSeconds": round_elapsed(pose_elapsed_total),
        "visionScoringElapsedSeconds": round_elapsed(vision_elapsed_total),
        "exerciseNameRewriteElapsedSeconds": round_elapsed(exercise_name_rewrite_elapsed_total),
        "exerciseMotionContractElapsedSeconds": round_elapsed(exercise_motion_contract_elapsed_total),
    }
    timing_payload["visionPreparationElapsedSeconds"] = round_elapsed(
        sum_candidate_vision_payload_number(exercise_payloads, "previewPreparationElapsedSeconds")
    )
    manifest = {
        "sourcePlanPath": str(workout_plan_json),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "ranking": {
            "maxCandidates": settings.max_candidates,
            "excludedCandidateCount": excluded_candidate_total,
            "excludedCandidateKeyCount": len(settings.excluded_candidate_keys),
            "candidateReviewBatchSize": settings.resolved_candidate_review_batch_size(),
            "candidateReviewTargetSuitableCount": settings.resolved_candidate_review_target_suitable_count(),
            "discoveryProgressJsonlPath": str(progress_path),
            "semanticGateDurationRankWeight": settings.semantic_gate_duration_rank_weight,
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
            "exerciseMotionContractEnabled": settings.exercise_motion_contract_enabled and vision_enabled,
            "exerciseMotionContractBackend": exercise_motion_contract_backend,
            "semanticGateEnabled": settings.semantic_gate_enabled,
            "semanticGateBackend": "llama-cpp" if settings.semantic_gate_enabled else None,
            "semanticGateModel": (
                text_llama_cpp_settings(settings).llama_cpp_model
                if settings.semantic_gate_enabled
                else None
            ),
            "semanticGateCandidatesPerExercise": (
                settings.resolved_semantic_gate_candidates_per_exercise()
                if settings.semantic_gate_enabled
                else None
            ),
            "semanticGateMaxCandidatesPerExercise": (
                settings.resolved_semantic_gate_max_candidates_per_exercise()
                if settings.semantic_gate_enabled
                else None
            ),
            "semanticGateTargetPassCount": (
                settings.resolved_semantic_gate_target_pass_count()
                if settings.semantic_gate_enabled
                else None
            ),
            "semanticGateLlmWorkers": (
                settings.resolved_semantic_gate_llm_workers()
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
            "posePrefilterSampleFps": (
                settings.pose_prefilter_sample_fps
                if settings.pose_prefilter_enabled
                else None
            ),
            "posePrefilterMaxSeconds": (
                settings.pose_prefilter_max_seconds
                if settings.pose_prefilter_enabled
                else None
            ),
            "posePrefilterDevice": (
                settings.pose_prefilter_device
                if settings.pose_prefilter_enabled
                else None
            ),
            "posePrefilterBatchSize": (
                settings.pose_prefilter_batch_size
                if settings.pose_prefilter_enabled
                else None
            ),
            "posePrefilterCandidatesPerExercise": (
                settings.resolved_pose_prefilter_candidates_per_exercise()
                if settings.pose_prefilter_enabled
                else None
            ),
            "equipmentJsonPath": str(equipment_json) if equipment_json is not None else None,
            "timing": timing_payload,
        },
        "exercises": exercise_payloads,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["ranking"]["timing"]["writeManifestElapsedSeconds"] = round_elapsed(time.monotonic() - write_started)
    manifest["ranking"]["timing"]["totalElapsedSeconds"] = round_elapsed(time.monotonic() - run_started)
    decisions_path = out_json.with_name("candidate_decisions.jsonl")
    write_candidate_decisions_jsonl(decisions_path, manifest)
    manifest["ranking"]["candidateDecisionsJsonlPath"] = str(decisions_path)
    out_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    append_youtube_discovery_progress(
        progress_path,
        event="manifest_written",
        started_at=run_started,
        outJson=str(out_json),
        candidateDecisionsJsonlPath=str(decisions_path),
        totalElapsedSeconds=manifest["ranking"]["timing"]["totalElapsedSeconds"],
    )
    return manifest


def candidate_has_debug_review_payload(candidate: YouTubeCandidate) -> bool:
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    return (
        "semanticGate" in payload
        or "posePrefilter" in payload
        or candidate.vision_score is not None
    )


def write_candidate_decisions_jsonl(path: Path, manifest: dict[str, Any]) -> None:
    rows: list[str] = []
    for exercise in manifest.get("exercises", []):
        if not isinstance(exercise, dict):
            continue
        final_candidates = exercise.get("candidates")
        final_candidate_keys = (
            {
                manifest_candidate_debug_key(candidate)
                for candidate in final_candidates
                if isinstance(candidate, dict)
            }
            if isinstance(final_candidates, list)
            else set()
        )
        candidates = exercise.get("debugCandidates")
        if not isinstance(candidates, list):
            candidates = exercise.get("candidates")
        if not isinstance(candidates, list):
            continue
        candidate_expansion = exercise.get("candidateExpansion")
        candidate_expansion_triggered = (
            bool(candidate_expansion.get("triggered"))
            if isinstance(candidate_expansion, dict)
            else False
        )
        search_expansion_triggered = (
            bool(candidate_expansion.get("searchExpansionTriggered"))
            if isinstance(candidate_expansion, dict)
            else False
        )
        for rank, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            payload = candidate.get("visionPayload") if isinstance(candidate.get("visionPayload"), dict) else {}
            semantic_payload = payload.get("semanticGate") if isinstance(payload, dict) else None
            pose_payload = payload.get("posePrefilter") if isinstance(payload, dict) else None
            semantic_reviewed = isinstance(semantic_payload, dict)
            pose_reviewed = isinstance(pose_payload, dict)
            rows.append(
                json.dumps(
                    {
                        "exerciseId": exercise.get("exerciseId"),
                        "exerciseName": exercise.get("exerciseName"),
                        "sourceExerciseName": exercise.get("sourceExerciseName"),
                        "equipmentQualifiedExerciseName": exercise.get("equipmentQualifiedExerciseName"),
                        "exerciseNameRewrite": exercise.get("exerciseNameRewrite"),
                        "exerciseSlug": exercise.get("slug"),
                        "debugRank": rank,
                        "videoId": candidate.get("videoId"),
                        "url": candidate.get("url"),
                        "title": candidate.get("title"),
                        "channel": candidate.get("channel"),
                        "durationSeconds": candidate.get("durationSeconds"),
                        "candidateExpansionTriggered": candidate_expansion_triggered,
                        "searchExpansionTriggered": search_expansion_triggered,
                        "survivedCandidateList": (
                            manifest_candidate_debug_key(candidate) in final_candidate_keys
                        ),
                        "semanticReviewed": semantic_reviewed,
                        "semanticScore": (
                            semantic_payload.get("score")
                            if semantic_reviewed
                            else None
                        ),
                        "semanticRankingScore": (
                            semantic_payload.get("rankingScore")
                            if semantic_reviewed
                            else None
                        ),
                        "semanticDurationPreferenceScore": (
                            semantic_payload.get("durationPreferenceScore")
                            if semantic_reviewed
                            else None
                        ),
                        "semanticPassed": (
                            semantic_payload.get("passed")
                            if semantic_reviewed
                            else None
                        ),
                        "semanticUnresolved": (
                            semantic_payload.get("unresolved")
                            if semantic_reviewed
                            else None
                        ),
                        "semanticSoftFallbackForPose": (
                            semantic_payload.get("softFallbackForPose")
                            if semantic_reviewed
                            else None
                        ),
                        "semanticWrongExercise": (
                            semantic_payload.get("wrongExercise")
                            if semantic_reviewed
                            else None
                        ),
                        "semanticWrongEquipment": (
                            semantic_payload.get("wrongEquipment")
                            if semantic_reviewed
                            else None
                        ),
                        "poseReviewed": pose_reviewed,
                        "poseScore": (
                            pose_payload.get("score")
                            if pose_reviewed
                            else None
                        ),
                        "posePassed": (
                            pose_payload.get("passed")
                            if pose_reviewed
                            else None
                        ),
                        "poseBlockingIssues": (
                            pose_payload.get("blockingIssues")
                            if pose_reviewed
                            else None
                        ),
                        "poseQualityIssues": (
                            pose_payload.get("qualityIssues")
                            if pose_reviewed
                            else None
                        ),
                        "visionScore": candidate.get("visionScore"),
                        "finalScore": candidate.get("finalScore"),
                        "status": candidate.get("status"),
                        "scoreReasons": candidate.get("scoreReasons"),
                        "visionPayload": payload,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
    path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def manifest_candidate_debug_key(candidate: dict[str, Any]) -> str:
    video_id = str(candidate.get("videoId") or "").strip()
    if video_id:
        return f"video:{video_id}"
    url = str(candidate.get("url") or "").strip()
    if url:
        return f"url:{url}"
    return ""


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

        self.settings = settings
        self.process: subprocess.Popen[str] | None = None
        self._server_recovery_lock = threading.Lock()
        self.gpu_lock: GlobalGpuLock | None = None
        self.gpu_lock_wait_seconds = 0.0
        try:
            if settings.llama_cpp_base_url is not None:
                if self._uses_gpu():
                    gpu_lock = GlobalGpuLock(stage="llama_cpp_server")
                    self.gpu_lock_wait_seconds = gpu_lock.__enter__()
                    self.gpu_lock = gpu_lock
                self._ensure_server()
            self.client = LlamaCppVisionClient(
                base_url=settings.llama_cpp_base_url,
                model=settings.llama_cpp_model,
                backend=settings.llama_cpp_backend,
                n_predict=settings.llama_cpp_n_predict,
                temperature=settings.llama_cpp_temperature,
                top_p=settings.llama_cpp_top_p,
                top_k=settings.llama_cpp_top_k,
                disable_reasoning=settings.llama_cpp_disable_reasoning,
                image_min_tokens=settings.llama_cpp_image_min_tokens,
                image_max_tokens=settings.llama_cpp_image_max_tokens,
                request_timeout_seconds=settings.llama_cpp_request_timeout_seconds,
                recovery_callback=self._recover_llama_cpp_server_after_vlm_failure,
            )
        except Exception:
            self._release_gpu_lock()
            raise

    def close(self, *, force_stop_server: bool = False) -> None:
        try:
            self.client.client.close()
        finally:
            try:
                self._stop_owned_llama_cpp_server(force=force_stop_server)
            finally:
                self._release_gpu_lock()

    def _uses_gpu(self) -> bool:
        return str(self.settings.llama_cpp_backend or "").strip().lower() != "cpu"

    def _release_gpu_lock(self) -> None:
        if self.gpu_lock is None:
            return
        gpu_lock = self.gpu_lock
        self.gpu_lock = None
        gpu_lock.__exit__(None, None, None)

    def _stop_owned_llama_cpp_server(self, *, force: bool = False) -> None:
        if self.process is None:
            if force and self.settings.llama_cpp_auto_start_server:
                stop_llama_cpp_servers_for_base_url(
                    self.settings.llama_cpp_base_url,
                    expected_command=self.settings.llama_cpp_server_command,
                    expected_model=self.settings.llama_cpp_model,
                )
            return
        if self.settings.keep_llama_cpp_server and not force:
            return
        process = self.process
        self.process = None
        process.terminate()
        try:
            process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10.0)

    def _recover_llama_cpp_server_after_vlm_failure(self) -> None:
        # Parallel VLM workers can fail together. Serialize stop/start so one
        # worker cannot clear self.process while another is polling its restart.
        with self._server_recovery_lock:
            if self.process is not None and not self.settings.keep_llama_cpp_server:
                self._stop_owned_llama_cpp_server()
                self._ensure_server()
                return
            self._wait_for_chat_completions_ready()

    def _ensure_server(self) -> None:
        server_payload = self._server_models_payload()
        if server_payload is not None:
            try:
                self._raise_if_server_model_mismatch(server_payload)
                self._raise_if_server_runtime_mismatch()
                self._wait_for_chat_completions_ready()
                return
            except RuntimeError:
                if not self.settings.llama_cpp_auto_start_server:
                    raise
                stopped = stop_llama_cpp_servers_for_base_url(
                    self.settings.llama_cpp_base_url,
                    expected_command=self.settings.llama_cpp_server_command,
                    expected_model=self.settings.llama_cpp_model,
                )
                if not stopped:
                    raise
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline and self._server_models_payload() is not None:
                    time.sleep(0.2)
        if not self.settings.llama_cpp_auto_start_server:
            response = httpx.get(f"{self.settings.llama_cpp_base_url.rstrip('/')}/v1/models", timeout=5.0)
            response.raise_for_status()
            self._raise_if_server_model_mismatch(response.json())
            self._raise_if_server_runtime_mismatch()
            self._wait_for_chat_completions_ready()
            return
        command = resolve_llama_cpp_server_command(
            configured_command=self.settings.llama_cpp_server_command,
        )
        model_path = Path(self.settings.llama_cpp_model)
        mmproj_path = Path(self.settings.llama_cpp_mmproj) if self.settings.llama_cpp_mmproj else None
        mtp_model_path = Path(self.settings.llama_cpp_mtp_model) if self.settings.llama_cpp_mtp_model else None
        if not model_path.exists():
            raise FileNotFoundError(f"Could not find llama.cpp model file: {model_path}")
        if mmproj_path is not None and not mmproj_path.exists():
            raise FileNotFoundError(f"Could not find llama.cpp mmproj file: {mmproj_path}")
        if mtp_model_path is not None and not mtp_model_path.exists():
            raise FileNotFoundError(f"Could not find llama.cpp MTP model file: {mtp_model_path}")
        if shutil.which(command) is None and not Path(command).exists():
            raise FileNotFoundError(f"Could not find llama-server binary: {command}")
        parsed = parse_llama_cpp_base_url(self.settings.llama_cpp_base_url)
        args = [
            command,
            "-m",
            str(model_path),
            "--host",
            parsed["host"],
            "--port",
            str(parsed["port"]),
            "--parallel",
            str(max(1, self.settings.llama_cpp_parallel or self.settings.vision_llm_workers)),
        ]
        if mmproj_path is not None:
            args.extend(["--mmproj", str(mmproj_path)])
        if mtp_model_path is not None:
            args.extend(
                [
                    "--model-draft",
                    str(mtp_model_path),
                    "--spec-type",
                    "draft-mtp",
                    "--spec-draft-n-max",
                    str(max(1, self.settings.llama_cpp_spec_draft_n_max)),
                    "--gpu-layers-draft",
                    "all" if self.settings.llama_cpp_backend == "gpu" else "0",
                ]
            )
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
        else:
            args.extend(["--reasoning", "on", "--reasoning-format", "deepseek"])
            if self.settings.llama_cpp_reasoning_budget is not None:
                args.extend(["--reasoning-budget", str(self.settings.llama_cpp_reasoning_budget)])
                if self.settings.llama_cpp_reasoning_budget >= 0 and self.settings.llama_cpp_reasoning_budget_message:
                    args.extend(
                        [
                            "--reasoning-budget-message",
                            self.settings.llama_cpp_reasoning_budget_message,
                        ]
                    )
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
        if mmproj_path is not None and self.settings.llama_cpp_image_min_tokens is not None:
            args.extend(["--image-min-tokens", str(max(1, self.settings.llama_cpp_image_min_tokens))])
        if mmproj_path is not None and self.settings.llama_cpp_image_max_tokens is not None:
            args.extend(["--image-max-tokens", str(max(1, self.settings.llama_cpp_image_max_tokens))])
        if mmproj_path is not None and self.settings.llama_cpp_mtmd_batch_max_tokens is not None:
            args.extend(["--mtmd-batch-max-tokens", str(max(1, self.settings.llama_cpp_mtmd_batch_max_tokens))])
        if not self.settings.llama_cpp_mmap:
            args.append("--no-mmap")
        if self.settings.llama_cpp_mlock:
            args.append("--mlock")
        if mmproj_path is not None:
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
        last_chat_error: str | None = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            if self._is_healthy():
                chat_ready, last_chat_error = self._chat_completions_ready()
                if chat_ready:
                    return
                if time.monotonic() >= deadline:
                    break
                time.sleep(1.0)
                continue
            if time.monotonic() >= deadline:
                break
            time.sleep(1.0)
        detail = f" Last chat readiness error: {last_chat_error}" if last_chat_error else ""
        raise RuntimeError(
            f"llama-server did not become healthy at {self.settings.llama_cpp_base_url} "
            f"within {self.settings.llama_cpp_server_startup_timeout_seconds:.0f} seconds.{detail}"
        )

    def _wait_for_chat_completions_ready(self) -> None:
        if self.settings.llama_cpp_base_url is None:
            return
        deadline = time.monotonic() + self.settings.llama_cpp_server_startup_timeout_seconds
        last_error: str | None = None
        while time.monotonic() < deadline:
            ready, last_error = self._chat_completions_ready()
            if ready:
                return
            time.sleep(1.0)
        detail = f" Last chat readiness error: {last_error}" if last_error else ""
        raise RuntimeError(
            f"llama-server chat completions endpoint at {self.settings.llama_cpp_base_url} "
            f"was not ready within {self.settings.llama_cpp_server_startup_timeout_seconds:.0f} seconds.{detail}"
        )

    def _chat_completions_ready(self) -> tuple[bool, str | None]:
        if self.settings.llama_cpp_base_url is None:
            return False, "llama.cpp base URL is not configured"
        timeout = min(
            LLAMA_CPP_CHAT_READY_PROBE_TIMEOUT_SECONDS,
            max(1.0, float(self.settings.llama_cpp_request_timeout_seconds)),
        )
        payload: dict[str, Any] = {
            "model": self.settings.llama_cpp_model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "temperature": 0,
            "max_tokens": 1,
            "reasoning_format": "none",
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            response = httpx.post(
                f"{self.settings.llama_cpp_base_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                timeout=timeout,
            )
            if response.status_code >= 500:
                return False, f"status={response.status_code}"
            if response.status_code >= 400:
                fallback_payload = dict(payload)
                fallback_payload.pop("reasoning_format", None)
                fallback_payload.pop("chat_template_kwargs", None)
                response = httpx.post(
                    f"{self.settings.llama_cpp_base_url.rstrip('/')}/v1/chat/completions",
                    json=fallback_payload,
                    timeout=timeout,
                )
            response.raise_for_status()
            return True, None
        except httpx.HTTPError as exc:
            return False, truncate_text(str(exc), 240)

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

    def _server_props_payload(self) -> dict[str, Any] | None:
        if self.settings.llama_cpp_base_url is None:
            return None
        try:
            response = httpx.get(f"{self.settings.llama_cpp_base_url.rstrip('/')}/props", timeout=5.0)
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

    def _raise_if_server_runtime_mismatch(self) -> None:
        expected_parallel = max(1, self.settings.llama_cpp_parallel or self.settings.vision_llm_workers)
        props_payload = self._server_props_payload()
        if props_payload is not None:
            total_slots = as_optional_int(props_payload.get("total_slots"))
            if total_slots is not None and total_slots != expected_parallel:
                raise RuntimeError(
                    f"Existing llama.cpp server at {self.settings.llama_cpp_base_url} exposes "
                    f"{total_slots} slots, but this run expects --parallel {expected_parallel}. "
                    "Stop the existing server or use a different --llama-cpp-base-url."
                )
        for command_line in llama_cpp_server_command_lines_for_base_url(self.settings.llama_cpp_base_url):
            actual_parallel = llama_cpp_server_parallel(command_line)
            if actual_parallel is not None and actual_parallel != expected_parallel:
                raise RuntimeError(
                    f"Existing llama.cpp server at {self.settings.llama_cpp_base_url} was started "
                    f"with --parallel {actual_parallel}, but this run expects --parallel {expected_parallel}. "
                    "Stop the existing server or use a different --llama-cpp-base-url."
                )
            mtp_conflict = llama_cpp_server_mtp_conflict(
                command_line,
                expected_model=self.settings.llama_cpp_mtp_model,
            )
            if mtp_conflict is not None:
                raise RuntimeError(
                    f"Existing llama.cpp server at {self.settings.llama_cpp_base_url} was {mtp_conflict}. "
                    "Stop the existing server or use a different --llama-cpp-base-url."
                )
            conflict = llama_cpp_server_reasoning_flag_conflict(
                command_line,
                disable_reasoning=self.settings.llama_cpp_disable_reasoning,
            )
            if conflict is None:
                continue
            expected = "disabled" if self.settings.llama_cpp_disable_reasoning else "enabled"
            raise RuntimeError(
                f"Existing llama.cpp server at {self.settings.llama_cpp_base_url} was {conflict}, "
                f"but this run expects reasoning {expected}. Stop the existing server or use a different "
                "--llama-cpp-base-url."
            )
        for command_line in llama_cpp_server_command_lines_for_base_url(self.settings.llama_cpp_base_url):
            budget_conflict = llama_cpp_server_reasoning_budget_conflict(
                command_line,
                expected_budget=self.settings.llama_cpp_reasoning_budget,
                disable_reasoning=self.settings.llama_cpp_disable_reasoning,
            )
            if budget_conflict is None:
                continue
            raise RuntimeError(
                f"Existing llama.cpp server at {self.settings.llama_cpp_base_url} was {budget_conflict}, "
                f"but this run expects reasoning budget {self.settings.llama_cpp_reasoning_budget}. "
                "Stop the existing server or use a different --llama-cpp-base-url."
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
        self.settings = text_llama_cpp_settings(settings)
        self._shared_ranker = shared_ranker if shared_ranker_matches_settings(shared_ranker, self.settings) else None
        self._owned_ranker: LlamaCppVisionRanker | None = None
        self._ranker_lock = threading.Lock()

    @property
    def _ranker(self) -> LlamaCppVisionRanker:
        ranker = self._shared_ranker or self._owned_ranker
        if ranker is None and self._shared_ranker is None:
            with self._ranker_lock:
                if self._owned_ranker is None:
                    self._owned_ranker = LlamaCppVisionRanker(self.settings)
            ranker = self._owned_ranker
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
        raw = self._ranker.client.caption_images(
            frame_paths=[],
            prompt=prompt,
            max_tokens=capped_llama_cpp_text_tokens(self.settings, cap=SEMANTIC_GATE_LLAMA_MAX_TOKENS),
            request_timeout_seconds=self.settings.llama_cpp_request_timeout_seconds,
            disable_reasoning=True,
        )
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
        if wrong_exercise:
            reasons.append("semantic_wrong_exercise")
        if bool(payload.get("wrongEquipment")):
            reasons.append("semantic_wrong_equipment")
        return clamp_score(score), reasons, {
            "enabled": True,
            "backend": "llama-cpp",
            "model": self.settings.llama_cpp_model,
            "passed": passed,
            "score": clamp_score(score),
            "wrongExercise": wrong_exercise,
            "wrongEquipment": bool(payload.get("wrongEquipment")),
            "unrequestedVariantTerms": semantic_payload_unrequested_variant_terms(payload),
            "matchedExercise": truncate_text(str(payload.get("matchedExercise") or ""), 120),
            "reason": truncate_text(str(payload.get("reason") or ""), 240),
        }

    def close(self) -> None:
        if self._owned_ranker is not None:
            self._owned_ranker.close()
            self._owned_ranker = None


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
    exercise_motion_contract: dict[str, Any] | None = None,
) -> list[YouTubeCandidate]:
    vision_limit = max(0, settings.vision_candidates_per_exercise)
    reranked: list[YouTubeCandidate] = []
    if settings.vision_llm_workers > 1:
        index = 0
        parallel_batch_size = max(
            1,
            min(
                settings.vision_llm_workers,
                settings.resolved_candidate_review_target_suitable_count(),
            ),
        )
        while index < len(ranked):
            if index >= vision_limit:
                reranked.extend(ranked[index:])
                break
            batch_end = min(len(ranked), vision_limit, index + parallel_batch_size)
            prepared_by_key = prepare_vision_reviews_parallel(
                exercise=exercise,
                candidates=ranked[index:batch_end],
                settings=settings,
                exercise_motion_contract=exercise_motion_contract,
            )
            try:
                vision_results_by_key = score_prepared_vision_reviews_parallel(
                    prepared_reviews=list(prepared_by_key.values()),
                    settings=settings,
                    vision_ranker=vision_ranker,
                )
                while index < batch_end:
                    candidate = ranked[index]
                    vision_result = vision_results_by_key.get(candidate.key())
                    if vision_result is None:
                        reviewed = apply_vision_score(candidate, 0.0, ["vision_review_failed"], settings=settings)
                    else:
                        vision_score, vision_reasons, vision_payload = normalize_vision_result(vision_result)
                        reviewed = apply_vision_score(candidate, vision_score, vision_reasons, vision_payload, settings=settings)
                    reranked.append(reviewed)
                    index += 1
                    if candidate_passes_vision_hard_gates(reviewed, settings):
                        reranked.extend(ranked[index:])
                        return reranked
            finally:
                for prepared in prepared_by_key.values():
                    prepared.close()
        return reranked

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
            exercise_motion_contract=exercise_motion_contract,
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
            except Exception as exc:
                if is_critical_vlm_interaction_error(exc):
                    write_prepared_vision_critical_vlm_error(
                        prepared,
                        exc,
                        context={
                            "stage": "source_video_suitability_parallel_review",
                            "videoId": prepared.candidate.video_id,
                            "title": prepared.candidate.title,
                        },
                    )
                    raise
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
    score_reasons = dedupe_reasons(candidate.score_reasons + effective_vision_reasons)
    if hard_reject:
        score_reasons = dedupe_reasons([*score_reasons, *candidate_pose_prefilter_hard_reject_reasons(candidate)])
    final_score = 0.0 if hard_reject else compose_final_score(effective_vision_score)
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


def prepare_vision_reviews_parallel(
    *,
    exercise: ExerciseEntry,
    candidates: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
    exercise_motion_contract: dict[str, Any] | None = None,
) -> dict[str, PreparedVisionReview]:
    if not candidates:
        return {}
    workers = max(1, min(settings.vision_download_workers, len(candidates)))
    prepared_by_key: dict[str, PreparedVisionReview] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                prepare_vision_review,
                exercise,
                candidate,
                settings,
                exercise_motion_contract=exercise_motion_contract,
            ): candidate
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
    *,
    exercise_motion_contract: dict[str, Any] | None = None,
) -> PreparedVisionReview:
    from exercise_motion_pkg.segment_detection import (
        DetectionSettings,
        VideoMetadata,
        detect_motion_candidate_intervals,
        iter_detection_windows,
    )
    from exercise_motion_pkg.video_utils import read_basic_video_metadata

    preparation_started = time.monotonic()
    temp_dir = tempfile.TemporaryDirectory(prefix="exercise-motion-youtube-")
    temp_path = Path(temp_dir.name)
    try:
        artifact_dir = prepared_vision_review_artifact_dir(exercise, candidate, settings)
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
        review_limit = resolved_vision_chunk_review_limit(settings)
        scan_duration = (
            duration
            if review_limit is None
            else min(duration, max(window_seconds, settings.vision_motion_scan_max_seconds))
        )
        scan_windows = iter_detection_windows(
            duration_seconds=scan_duration,
            window_seconds=window_seconds,
            overlap_seconds=overlap_seconds,
        )
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
                max_motion_candidates=review_limit or max(1, len(scan_windows)),
                motion_sample_fps=settings.vision_motion_scan_sample_fps,
            ),
        )
        motion_scan_elapsed = time.monotonic() - motion_started
        planning_started = time.monotonic()
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
                source=review_window_source_for_motion_intervals(window, motion_intervals),
            )
            for index, window in enumerate(windows)
        ]
        review_windows = prepend_preferred_review_windows(
            pose_prefilter_review_windows_for_candidate(
                candidate,
                duration_seconds=duration,
            ),
            review_windows,
        )
        # Adaptive review needs the fallback windows available even when its VLM
        # budget is small. Rendering remains lazy, so unused windows cost nothing.
        review_windows = select_review_windows_by_budget(
            review_windows,
            None if settings.vision_adaptive_chunk_review else review_limit,
        )
        window_planning_elapsed = time.monotonic() - planning_started
        frames_per_chunk = max(1, settings.vision_frames_per_candidate or frames_for_chunk_seconds(chunk_seconds))
        prompt_motion_contract = exercise_motion_contract_for_prompt(exercise_motion_contract)
        return PreparedVisionReview(
            candidate=candidate,
            temp_dir=temp_dir,
            frame_paths=[],
            frame_path_chunks=[],
            chunk_windows=[(window.start_seconds, window.end_seconds) for window in review_windows],
            chunk_count=len(review_windows),
            prompt=build_candidate_vision_prompt(exercise.name, candidate, prompt_motion_contract),
            exercise_motion_contract=prompt_motion_contract,
            video_path=video_path,
            review_windows=review_windows,
            frames_per_chunk=frames_per_chunk,
            preview_preparation_elapsed_seconds=time.monotonic() - preparation_started,
            preview_download_elapsed_seconds=preview_download_elapsed,
            motion_scan_elapsed_seconds=motion_scan_elapsed,
            window_planning_elapsed_seconds=window_planning_elapsed,
            artifact_dir=artifact_dir,
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
    except Exception as exc:
        if is_critical_vlm_interaction_error(exc):
            add_vlm_context(
                exc,
                stage="single_candidate_vision_review",
                exerciseName=exercise.name,
                videoId=candidate.video_id,
                title=candidate.title,
            )
            raise
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
        full_timeline_note = (
            "The full candidate timeline is being reviewed chunk by chunk; this is one chunk from that full scan. "
            if resolved_vision_chunk_review_limit(settings) is None
            else ""
        )
        chunk_prompt = (
            f"{prepared.prompt}\n"
            f"These contact-sheet images are from chunk {chunk_index + 1} of {prepared.chunk_count} "
            f"covering {chunk_start:.3f}s to {chunk_end:.3f}s in the preview video. "
            f"{full_timeline_note}"
            "Treat multiple attached contact sheets as consecutive context segments from the same chunk. "
            "Score only this chunk as evidence that the source video contains a usable target-exercise segment. "
            "The final single-rep trim will be found later by detect_exercise_segment."
        )
        pose_motion_evidence = source_review_pose_motion_evidence(
            prepared.candidate,
            start_seconds=chunk_start,
            end_seconds=chunk_end,
        )
        temporal_change = source_review_temporal_change_metrics(
            chunk_paths,
            pose_motion_evidence=pose_motion_evidence,
        )
        if bool(temporal_change.get("nearIdenticalFrames")):
            reasons = [
                "near_duplicate_source_frames",
                "deterministic_temporal_change_gate_failed",
            ]
            payload = static_source_chunk_vision_payload(temporal_change)
            debug_artifacts = write_prepared_vision_chunk_debug(
                prepared,
                chunk_index=chunk_index,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                window_source=window_source,
                frame_paths=chunk_paths,
                prompt=chunk_prompt,
                parsed_payload=payload,
                score=0.0,
                reasons=reasons,
                error={
                    "type": "near_duplicate_source_frames",
                    "message": "The sampled source frames contain no meaningful temporal visual change.",
                    "temporalChangeMetrics": temporal_change,
                },
            )
            chunk_scores.append(0.0)
            chunk_results.append((0.0, reasons, payload, chunk_index))
            reviewed_chunks.append(
                build_reviewed_chunk_timing(
                    chunk_index=chunk_index,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                    window_source=window_source,
                    render_elapsed=render_elapsed,
                    vlm_elapsed=0.0,
                    score=0.0,
                    valid=False,
                    failure="near_duplicate_source_frames",
                    debug_artifacts=debug_artifacts,
                    temporal_change_metrics=temporal_change,
                )
            )
            # A cheap frozen-frame diagnostic must not consume the candidate's
            # useful review budget. Try the next motion-ranked window.
            if review_order >= len(chunk_indexes) - 1:
                early_stop_reason = "all_planned_chunks_near_duplicate"
            continue
        vlm_started = time.monotonic()
        try:
            raw = caption_images(frame_paths=chunk_paths, prompt=chunk_prompt)
        except Exception as exc:
            vlm_elapsed = time.monotonic() - vlm_started
            critical = wrap_vlm_infrastructure_error(
                exc,
                interaction="source_video_suitability_chunk_review",
                timeout_seconds=settings.llama_cpp_request_timeout_seconds,
            )
            if critical is not None:
                critical.add_details(
                    stage="source_video_suitability_chunk_review",
                    videoId=prepared.candidate.video_id,
                    title=prepared.candidate.title,
                    chunkIndex=chunk_index,
                    chunkStartSeconds=chunk_start,
                    chunkEndSeconds=chunk_end,
                    windowSource=window_source,
                    framePaths=[str(path) for path in chunk_paths],
                    frameCount=len(chunk_paths),
                    promptChars=len(chunk_prompt),
                    elapsedSeconds=round(vlm_elapsed, 3),
                )
                write_prepared_vision_critical_vlm_error(
                    prepared,
                    critical,
                    context={
                        "stage": "source_video_suitability_chunk_review",
                        "videoId": prepared.candidate.video_id,
                        "title": prepared.candidate.title,
                        "chunkIndex": chunk_index,
                        "chunkStartSeconds": chunk_start,
                        "chunkEndSeconds": chunk_end,
                        "windowSource": window_source,
                        "framePaths": [str(path) for path in chunk_paths],
                        "frameCount": len(chunk_paths),
                        "promptChars": len(chunk_prompt),
                        "elapsedSeconds": round(vlm_elapsed, 3),
                    },
                )
                if critical is exc:
                    raise
                raise critical from exc
            vlm_elapsed_total += vlm_elapsed
            failed_count += 1
            debug_artifacts = write_prepared_vision_chunk_debug(
                prepared,
                chunk_index=chunk_index,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                window_source=window_source,
                frame_paths=chunk_paths,
                prompt=chunk_prompt,
                error={"type": type(exc).__name__, "message": str(exc)},
            )
            reviewed_chunks.append(
                build_reviewed_chunk_timing(
                    chunk_index=chunk_index,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                    window_source=window_source,
                    render_elapsed=render_elapsed,
                    vlm_elapsed=vlm_elapsed,
                    failure="vlm_exception",
                    debug_artifacts=debug_artifacts,
                )
            )
            continue
        vlm_elapsed = time.monotonic() - vlm_started
        vlm_elapsed_total += vlm_elapsed
        payload = extract_json_object(raw)
        if not isinstance(payload, dict):
            invalid_json_count += 1
            debug_artifacts = write_prepared_vision_chunk_debug(
                prepared,
                chunk_index=chunk_index,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                window_source=window_source,
                frame_paths=chunk_paths,
                prompt=chunk_prompt,
                raw_response=raw,
                error={"type": "invalid_json", "message": "VLM response did not contain a JSON object."},
            )
            reviewed_chunks.append(
                build_reviewed_chunk_timing(
                    chunk_index=chunk_index,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                    window_source=window_source,
                    render_elapsed=render_elapsed,
                    vlm_elapsed=vlm_elapsed,
                    failure="invalid_json",
                    debug_artifacts=debug_artifacts,
                )
            )
            continue
        score, reasons = score_candidate_vision_payload(payload)
        debug_artifacts = write_prepared_vision_chunk_debug(
            prepared,
            chunk_index=chunk_index,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
            window_source=window_source,
            frame_paths=chunk_paths,
            prompt=chunk_prompt,
            raw_response=raw,
            parsed_payload=payload,
            score=score,
            reasons=reasons,
        )
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
                debug_artifacts=debug_artifacts,
            )
        )
        early_stop_reason = adaptive_review_stop_reason(
            chunk_scores=chunk_scores,
            chunk_results=chunk_results,
            review_order=review_order,
            settings=settings,
            is_final_planned_chunk=review_order >= len(chunk_indexes) - 1,
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
        full_timeline_review=resolved_vision_chunk_review_limit(settings) is None,
    )
    compact_payload = dict(best_payload)
    if prepared.exercise_motion_contract is not None:
        compact_payload["exerciseMotionContract"] = prepared.exercise_motion_contract
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
            early_stop_reason=early_stop_reason
            or (
                "full_timeline_review_complete"
                if resolved_vision_chunk_review_limit(settings) is None
                else "max_budget_reached"
            ),
        )
    )
    return final_score, dedupe_reasons(best_reasons + evidence_reasons + ["chunked_source_video_review"]), compact_payload


def source_review_temporal_frame_paths(frame_paths: list[Path]) -> list[Path]:
    """Resolve the unlabeled frames behind source-review contact sheets."""
    resolved: list[Path] = []
    seen: set[Path] = set()
    for path in frame_paths:
        candidates = (
            sorted(path.parent.glob("frame_*.jpg"))
            if path.stem.startswith("contact_sheet")
            else [path]
        )
        for candidate in candidates:
            normalized = candidate.resolve()
            if normalized in seen:
                continue
            seen.add(normalized)
            resolved.append(candidate)
    return resolved


def source_review_pose_motion_evidence(
    candidate: YouTubeCandidate,
    *,
    start_seconds: float,
    end_seconds: float,
) -> dict[str, Any] | None:
    """Return trusted person-track motion evidence for one review window."""
    payload = candidate.vision_payload if isinstance(candidate.vision_payload, dict) else {}
    pose_payload = payload.get("posePrefilter") if isinstance(payload, dict) else None
    if not isinstance(pose_payload, dict) or not bool(pose_payload.get("passed")):
        return None

    best_chunk: dict[str, Any] | None = None
    best_overlap = 0.0
    for item in pose_payload.get("validChunks") or []:
        if not isinstance(item, dict):
            continue
        item_start = coerce_float(item.get("startSeconds"))
        item_end = coerce_float(item.get("endSeconds"))
        if item_start is None or item_end is None or item_end <= item_start:
            continue
        overlap = max(0.0, min(end_seconds, item_end) - max(start_seconds, item_start))
        if overlap > best_overlap:
            best_chunk = item
            best_overlap = overlap
    if best_chunk is None or best_overlap <= 0.0:
        return None

    observability = best_chunk.get("targetMotionObservability")
    source_integrity = best_chunk.get("sourceWindowIntegrity")
    if not isinstance(observability, dict) or not isinstance(source_integrity, dict):
        return None
    motion_range = coerce_float(observability.get("targetMotionRangeRatio"))
    min_motion_range = coerce_float(observability.get("minTargetMotionRangeRatio"))
    if motion_range is None or min_motion_range is None:
        return None
    strong_motion = (
        bool(observability.get("passed"))
        and bool(source_integrity.get("passed"))
        and motion_range >= max(0.02, min_motion_range * 2.0)
    )

    pose_samples = []
    for sample in pose_payload.get("dominantPoseSamples") or []:
        if not isinstance(sample, dict):
            continue
        timestamp = coerce_float(sample.get("timeSeconds"))
        bbox = sample.get("bbox")
        if timestamp is None or timestamp < start_seconds or timestamp > end_seconds:
            continue
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        coordinates = [coerce_float(value) for value in bbox]
        if any(value is None for value in coordinates):
            continue
        pose_samples.append([float(value) for value in coordinates if value is not None])

    normalized_roi: list[float] | None = None
    if len(pose_samples) >= 3:
        x1 = min(bbox[0] for bbox in pose_samples)
        y1 = min(bbox[1] for bbox in pose_samples)
        x2 = max(bbox[2] for bbox in pose_samples)
        y2 = max(bbox[3] for bbox in pose_samples)
        padding_x = max(0.02, (x2 - x1) * 0.12)
        padding_y = max(0.02, (y2 - y1) * 0.12)
        normalized_roi = [
            max(0.0, x1 - padding_x),
            max(0.0, y1 - padding_y),
            min(1.0, x2 + padding_x),
            min(1.0, y2 + padding_y),
        ]

    return {
        "available": True,
        "strongMotion": strong_motion,
        "targetMotionRangeRatio": motion_range,
        "minTargetMotionRangeRatio": min_motion_range,
        "sourceWindowIntegrityPassed": bool(source_integrity.get("passed")),
        "sampleCount": len(pose_samples),
        "normalizedPersonRoi": normalized_roi,
    }


def source_review_temporal_change_metrics(
    frame_paths: list[Path],
    *,
    pose_motion_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Conservatively reject only frozen or nearly frozen sampled sequences."""
    resolved_paths = source_review_temporal_frame_paths(frame_paths)
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {
            "available": False,
            "nearIdenticalFrames": False,
            "reason": "temporal_change_dependencies_missing",
            "frameCount": 0,
        }

    frames: list[Any] = []
    roi_frames: list[Any] = []
    normalized_roi = (
        pose_motion_evidence.get("normalizedPersonRoi")
        if isinstance(pose_motion_evidence, dict)
        else None
    )
    for path in resolved_paths:
        frame = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if frame is None:
            continue
        resized = cv2.resize(
            frame,
            (SOURCE_REVIEW_TEMPORAL_ANALYSIS_WIDTH, SOURCE_REVIEW_TEMPORAL_ANALYSIS_HEIGHT),
            interpolation=cv2.INTER_AREA,
        )
        frames.append(resized.astype(np.float32))
        if isinstance(normalized_roi, list) and len(normalized_roi) == 4:
            height, width = frame.shape[:2]
            x1 = max(0, min(width - 1, round(float(normalized_roi[0]) * width)))
            y1 = max(0, min(height - 1, round(float(normalized_roi[1]) * height)))
            x2 = max(x1 + 1, min(width, round(float(normalized_roi[2]) * width)))
            y2 = max(y1 + 1, min(height, round(float(normalized_roi[3]) * height)))
            crop = frame[y1:y2, x1:x2]
            if crop.size:
                roi_frames.append(
                    cv2.resize(
                        crop,
                        (SOURCE_REVIEW_TEMPORAL_ANALYSIS_WIDTH, SOURCE_REVIEW_TEMPORAL_ANALYSIS_HEIGHT),
                        interpolation=cv2.INTER_AREA,
                    ).astype(np.float32)
                )
    if len(frames) < 3:
        return {
            "available": False,
            "nearIdenticalFrames": False,
            "reason": "insufficient_decodable_frames",
            "frameCount": len(frames),
        }

    def summarize_temporal_change(samples: list[Any]) -> dict[str, float]:
        adjacent_deltas = [
            float(np.mean(np.abs(current - previous)) / 255.0)
            for previous, current in zip(samples, samples[1:])
        ]
        first_frame_deltas = [
            float(np.mean(np.abs(frame - samples[0])) / 255.0)
            for frame in samples[1:]
        ]
        return {
            "meanAdjacentDelta": float(np.mean(adjacent_deltas)),
            "medianAdjacentDelta": float(np.median(adjacent_deltas)),
            "maxAdjacentDelta": max(adjacent_deltas, default=0.0),
            "nearDuplicatePairRatio": sum(
                delta <= SOURCE_REVIEW_NEAR_DUPLICATE_FRAME_DELTA for delta in adjacent_deltas
            )
            / len(adjacent_deltas),
            "maxTemporalRangeFromFirst": max(first_frame_deltas, default=0.0),
        }

    global_change = summarize_temporal_change(frames)
    roi_change = summarize_temporal_change(roi_frames) if len(roi_frames) == len(frames) else None

    def is_near_identical(change: dict[str, float]) -> bool:
        return (
            change["nearDuplicatePairRatio"] >= SOURCE_REVIEW_NEAR_DUPLICATE_PAIR_RATIO
            and change["maxTemporalRangeFromFirst"] <= SOURCE_REVIEW_MAX_STATIC_TEMPORAL_RANGE
        )

    global_near_identical = is_near_identical(global_change)
    roi_near_identical = is_near_identical(roi_change) if roi_change is not None else True
    strong_pose_motion = bool(
        isinstance(pose_motion_evidence, dict) and pose_motion_evidence.get("strongMotion")
    )
    near_identical = global_near_identical and roi_near_identical and not strong_pose_motion
    return {
        "available": True,
        "nearIdenticalFrames": near_identical,
        "reason": "near_identical_sampled_frames" if near_identical else "meaningful_temporal_change_detected",
        "frameCount": len(frames),
        **global_change,
        "globalNearIdenticalFrames": global_near_identical,
        "personRoiTemporalChange": roi_change,
        "personRoiNearIdenticalFrames": roi_near_identical if roi_change is not None else None,
        "poseMotionEvidence": pose_motion_evidence,
        "nearDuplicateFrameDeltaThreshold": SOURCE_REVIEW_NEAR_DUPLICATE_FRAME_DELTA,
        "nearDuplicatePairRatioThreshold": SOURCE_REVIEW_NEAR_DUPLICATE_PAIR_RATIO,
        "maxStaticTemporalRangeThreshold": SOURCE_REVIEW_MAX_STATIC_TEMPORAL_RANGE,
    }


def static_source_chunk_vision_payload(temporal_change: dict[str, Any]) -> dict[str, Any]:
    return {
        "correct_exercise": False,
        "usable_for_motion_extraction": False,
        "complete_repetition_visible": False,
        "target_identity_match": False,
        "target_match": 0.0,
        "complete_movement": 0.0,
        "execution_quality": 0.0,
        "source_score": 0.0,
        "blocking_issues": ["static_or_near_duplicate_frames"],
        "confidence": 1.0,
        "reason": "The sampled frames are identical or nearly identical and cannot contain a visible movement.",
        "deterministicTemporalChange": temporal_change,
    }


def planned_adaptive_chunk_indexes(
    prepared: PreparedVisionReview,
    settings: YouTubeRankingSettings,
) -> list[int]:
    chunk_count = prepared.chunk_count or len(prepared.frame_path_chunks)
    if chunk_count <= 0:
        return []
    review_limit = resolved_vision_chunk_review_limit(settings)
    ordered = prioritized_review_chunk_indexes(prepared, chunk_count)
    if review_limit is None:
        return ordered
    if not settings.vision_adaptive_chunk_review:
        return ordered[: max(1, min(review_limit, chunk_count))]
    # The configured cap controls expensive initial VLM review. Keep fallback
    # windows available so deterministic rejects cannot hide a valid interval.
    hard_limit = min(
        chunk_count,
        max(1, review_limit) + max(0, settings.vision_expand_chunks_per_candidate),
    )
    initial_budget = max(1, min(settings.vision_initial_chunks_per_candidate, hard_limit))
    expansion_budget = max(0, settings.vision_expand_chunks_per_candidate)
    budget = min(hard_limit, initial_budget + expansion_budget)
    return ordered[:budget]


def prioritized_review_chunk_indexes(prepared: PreparedVisionReview, chunk_count: int) -> list[int]:
    pose_indexes = [
        index
        for index, window in enumerate(prepared.review_windows)
        if window.source == "pose_prefilter"
    ]
    motion_indexes = [
        index
        for index, window in enumerate(prepared.review_windows)
        if window.source == "motion_interval"
    ]
    coverage_indexes = [
        index
        for index, window in enumerate(prepared.review_windows)
        if window.source not in {"pose_prefilter", "motion_interval"}
    ]
    ordered: list[int] = []
    for index in [
        *pose_indexes,
        *motion_indexes[:1],
        *coverage_indexes[:1],
        *motion_indexes[1:],
        *coverage_indexes[1:],
    ]:
        if index not in ordered and index < chunk_count:
            ordered.append(index)
    for index in range(chunk_count):
        if index not in ordered:
            ordered.append(index)
    return ordered


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
        contact_sheet_sequence_labels=True,
        output_dir=(prepared.artifact_dir or Path(prepared.temp_dir.name)) / "frames" / f"chunk_{chunk_index:04d}",
    )
    elapsed = time.monotonic() - started
    paths = [sample.path if hasattr(sample, "path") else sample for sample in frame_samples]
    prepared.rendered_chunk_cache[chunk_index] = (paths, elapsed)
    if chunk_index >= len(prepared.frame_path_chunks):
        prepared.frame_path_chunks.extend([[] for _ in range(chunk_index - len(prepared.frame_path_chunks) + 1)])
    prepared.frame_path_chunks[chunk_index] = paths
    prepared.frame_paths.extend(paths)
    return paths, elapsed


def write_prepared_vision_chunk_debug(
    prepared: PreparedVisionReview,
    *,
    chunk_index: int,
    chunk_start: float,
    chunk_end: float,
    window_source: str,
    frame_paths: list[Path],
    prompt: str,
    raw_response: str | None = None,
    parsed_payload: dict[str, Any] | None = None,
    score: float | None = None,
    reasons: list[str] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if prepared.artifact_dir is None:
        return None
    chunk_dir = prepared.artifact_dir / "chunks" / f"chunk_{chunk_index:04d}"
    try:
        chunk_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = chunk_dir / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        raw_response_path: Path | None = None
        parsed_payload_path: Path | None = None
        if raw_response is not None:
            raw_response_path = chunk_dir / "raw_response.txt"
            raw_response_path.write_text(raw_response, encoding="utf-8")
        if parsed_payload is not None:
            parsed_payload_path = chunk_dir / "parsed_payload.json"
            parsed_payload_path.write_text(json.dumps(parsed_payload, indent=2), encoding="utf-8")
        debug_path = chunk_dir / "review_debug.json"
        debug_payload: dict[str, Any] = {
            "schemaVersion": 1,
            "videoId": prepared.candidate.video_id,
            "title": prepared.candidate.title,
            "url": prepared.candidate.url,
            "chunkIndex": chunk_index,
            "startSeconds": round(chunk_start, 3),
            "endSeconds": round(chunk_end, 3),
            "windowSource": window_source,
            "framePaths": [str(path) for path in frame_paths],
            "promptPath": str(prompt_path),
            "promptChars": len(prompt),
            "rawResponsePath": str(raw_response_path) if raw_response_path is not None else None,
            "rawResponseChars": len(raw_response) if raw_response is not None else 0,
            "parsedPayloadPath": str(parsed_payload_path) if parsed_payload_path is not None else None,
            "score": score,
            "reasons": reasons or [],
            "error": error,
        }
        debug_path.write_text(json.dumps(debug_payload, indent=2), encoding="utf-8")
        return {
            "artifactDir": str(chunk_dir),
            "promptPath": str(prompt_path),
            "rawResponsePath": str(raw_response_path) if raw_response_path is not None else None,
            "parsedPayloadPath": str(parsed_payload_path) if parsed_payload_path is not None else None,
            "debugPath": str(debug_path),
        }
    except Exception as exc:
        return {
            "artifactDir": str(chunk_dir),
            "debugWriteError": f"{type(exc).__name__}: {exc}",
        }


def adaptive_review_stop_reason(
    *,
    chunk_scores: list[float],
    chunk_results: list[tuple[float, list[str], dict[str, Any], int]],
    review_order: int,
    settings: YouTubeRankingSettings,
    is_final_planned_chunk: bool = False,
) -> str | None:
    if not settings.vision_adaptive_chunk_review:
        return None
    review_limit = resolved_vision_chunk_review_limit(settings)
    planned_budget = review_order + 1 if is_final_planned_chunk else None
    initial_budget = max(1, settings.vision_initial_chunks_per_candidate)
    if review_limit is not None:
        initial_budget = min(initial_budget, max(1, review_limit))
    if planned_budget is not None:
        initial_budget = min(initial_budget, planned_budget)
    if (
        review_limit is not None
        and is_final_planned_chunk
        and len(chunk_scores) >= initial_budget
        and max(chunk_scores, default=0.0) < 0.50
    ):
        return "all_diagnostic_chunks_bad"
    best_score, best_reasons, _, _ = max(chunk_results, key=lambda item: item[0])
    valid_chunk_ratio = sum(1 for score in chunk_scores if score >= 0.50) / max(1, len(chunk_scores))
    if (
        (review_limit is not None or not is_final_planned_chunk)
        and (review_limit is not None or len(chunk_scores) >= initial_budget)
        and valid_chunk_ratio >= 0.50
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
    debug_artifacts: dict[str, Any] | None = None,
    temporal_change_metrics: dict[str, Any] | None = None,
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
    if debug_artifacts is not None:
        payload["debugArtifacts"] = debug_artifacts
    if temporal_change_metrics is not None:
        payload["temporalChangeMetrics"] = temporal_change_metrics
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
    review_limit = resolved_vision_chunk_review_limit(settings)
    planned_chunk_budget = len(planned_adaptive_chunk_indexes(prepared, settings))
    payload: dict[str, Any] = {
        "previewPreparationElapsedSeconds": round_elapsed(prepared.preview_preparation_elapsed_seconds),
        "previewDownloadElapsedSeconds": round_elapsed(prepared.preview_download_elapsed_seconds),
        "motionScanElapsedSeconds": round_elapsed(prepared.motion_scan_elapsed_seconds),
        "windowPlanningElapsedSeconds": round_elapsed(prepared.window_planning_elapsed_seconds),
        "totalVisionReviewElapsedSeconds": round_elapsed(review_elapsed),
        "totalChunkRenderElapsedSeconds": round_elapsed(render_elapsed_total),
        "totalChunkVlmElapsedSeconds": round_elapsed(vlm_elapsed_total),
        "reviewedChunks": reviewed_chunks,
        "adaptiveReviewPolicy": {
            "enabled": settings.vision_adaptive_chunk_review and review_limit is not None,
            "configured": settings.vision_adaptive_chunk_review,
            "fullTimelineReview": review_limit is None,
            "initialChunkBudget": max(1, settings.vision_initial_chunks_per_candidate),
            "expansionChunkBudget": max(0, settings.vision_expand_chunks_per_candidate),
            "configuredChunkLimit": review_limit,
            "maxChunkBudget": planned_chunk_budget,
            "earlyStopReason": early_stop_reason,
            "reviewedChunkCount": len(reviewed_chunks),
            "plannedChunkCount": prepared.chunk_count,
        },
    }
    if prepared.artifact_dir is not None:
        payload["visionReviewArtifactDir"] = str(prepared.artifact_dir)
    return payload


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
    if prepared.exercise_motion_contract is not None:
        payload["exerciseMotionContract"] = prepared.exercise_motion_contract
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
    full_timeline_review: bool = False,
) -> tuple[float, list[str]]:
    if scored_chunk_count <= 0:
        return score, []
    if valid_chunk_count <= 0:
        return min(score, 0.34), ["no_valid_source_chunk_evidence"]
    if full_timeline_review and best_chunk_score is not None and best_chunk_score >= 0.70:
        return score, ["full_timeline_valid_source_chunk"]
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
    if best_chunk_score is None or best_chunk_score < 0.80:
        return False
    # We only need one complete extraction interval. The downstream selector
    # validates and trims that interval, so unrelated portions of a longer
    # source are not evidence that the known-good interval is unusable.
    return True


def score_candidate_vision_payload(payload: dict[str, Any]) -> tuple[float, list[str]]:
    explicit_gate_values = {
        gate: parse_payload_bool(payload, gate)
        for gate in VISION_HARD_GATE_REASONS | VISION_DETERMINISTIC_SOURCE_GATES
    }
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
    legacy_real_human_subject = parse_payload_bool(payload, "real_human_subject")
    subject_realism_score = parse_moving_subject_realism_score(payload)
    blocking_issues = parse_blocking_issues(payload.get("blocking_issues", payload.get("blocking_issue")))
    note_conflict_reasons = vision_payload_note_conflict_reasons(payload)
    semantic_blocking_issue_present = any(
        issue != "none" and issue in VISION_SEMANTIC_BLOCKING_ISSUES
        for issue in blocking_issues
    )
    confidence_score = parse_score_value(payload.get("confidence"), default=0.5)

    score = source_score
    reasons: list[str] = []
    for gate in VISION_HARD_GATE_REASONS:
        value = explicit_gate_values.get(gate)
        if value is True:
            reasons.append(gate)
        elif value is False:
            reasons.append(f"{gate}_failed")

    if legacy_real_human_subject is False:
        reasons.append("legacy_real_human_subject_false")
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
        if issue != "none" and issue in VISION_SEMANTIC_BLOCKING_ISSUES:
            reasons.append(f"{issue}_penalty")
        elif issue != "none":
            reasons.append(f"{issue}_ignored_by_vlm_score")
    reasons.extend(note_conflict_reasons)
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
    if capture_quality < 0.75:
        reasons.append("deterministic_capture_quality_ignored_by_vlm_score")
    if execution_quality >= 0.75:
        reasons.append("execution_quality")
        append_execution_gate_reasons(reasons, explicit_gate_values)
    else:
        reasons.append("bad_execution_quality_penalty")
    if subject_realism_score >= MIN_MOVING_SUBJECT_REALISM_SCORE:
        reasons.append("moving_subject_realism_score")
    else:
        reasons.append("low_subject_realism_penalty")
    if source_score >= 0.75:
        reasons.append("source_score")
        if explicit_gate_values.get("usable_for_motion_extraction") is not False:
            reasons.append("usable_for_motion_extraction")
    else:
        reasons.append("weak_source_score_penalty")

    minimum_gate_score = min(
        target_match,
        complete_movement,
        execution_quality,
        subject_realism_score,
    )
    valid_motion_scene = (
        minimum_gate_score >= 0.75
        and subject_realism_score >= MIN_MOVING_SUBJECT_REALISM_SCORE
        and start_posture_visible is True
        and primary_effort_phase_visible is True
        and action_path_visible is True
        and end_posture_visible is True
        and no_setup_or_talking_frames is True
        and not semantic_blocking_issue_present
        and not note_conflict_reasons
    )
    if valid_motion_scene:
        reasons.append("valid_motion_scene")

    if minimum_gate_score < 0.65:
        score = min(score, 0.49)
    else:
        score = min(score, minimum_gate_score)
    score = apply_explicit_gate_caps(score, explicit_gate_values)
    score = apply_blocking_issue_caps(score, blocking_issues)
    if note_conflict_reasons:
        score = min(score, 0.49)
    score = min(score, subject_realism_score)
    if subject_realism_score < MIN_MOVING_SUBJECT_REALISM_SCORE:
        score = min(score, LOW_MOVING_SUBJECT_REALISM_SCORE_CAP)
        reasons.append("low_moving_subject_realism_source_cap")
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
        parse_payload_bool(payload, "implement_path_visible"),
    ]
    known = [value for value in relevant if value is not None]
    if not known:
        return 1.0
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
        "no_step_breakdown",
    ):
        if explicit_gate_values.get(gate) is True:
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
        "no_step_breakdown": 0.49,
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


def parse_moving_subject_realism_score(payload: dict[str, Any]) -> float:
    legacy_real_human_subject = parse_payload_bool(payload, "real_human_subject")
    return parse_score_value(
        payload.get(
            "moving_subject_realism_score",
            payload.get("subject_realism_score", payload.get("realism_score")),
        ),
        default=0.20 if legacy_real_human_subject is False else 1.0,
    )


def vision_payload_note_conflict_reasons(payload: dict[str, Any]) -> list[str]:
    note_parts = [
        str(payload.get(key) or "").strip().lower()
        for key in ("reason", "note", "summary")
        if str(payload.get(key) or "").strip()
    ]
    note = " ".join(note_parts)
    if not note:
        return []
    conflict_phrases = (
        "wrong exercise",
        "wrong variant",
        "different variant",
        "different variation",
        "not the target",
        "not a clean",
        "cannot verify",
        "can't verify",
        "not visible",
        "not clearly visible",
        "not clearly shown",
        "unclear",
        "ambiguous",
        "missing required",
        "lacks required",
        "lacks the required",
        "no external weight",
        "external weight is not visible",
        "load is not visible",
        "weight is not visible",
        "not visibly weighted",
        "bodyweight only",
    )
    if any(phrase in note for phrase in conflict_phrases):
        return ["vision_reason_contradicts_high_score"]
    return []


def parse_blocking_issues(value: Any) -> list[str]:
    allowed = {
        "none",
        "wrong_exercise",
        "wrong_variant",
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
        "unclear",
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
        "wrong_variant": 0.20,
        "partial_movement": 0.34,
        "slow_instruction": 0.49,
        "setup_or_talking": 0.34,
        "unclear": 0.49,
    }
    capped = score
    for issue in blocking_issues:
        if issue in caps:
            capped = min(capped, caps[issue])
    return capped


def build_candidate_vision_prompt(
    exercise_name: str,
    candidate: YouTubeCandidate,
    exercise_motion_contract: dict[str, Any] | None = None,
) -> str:
    from exercise_motion_pkg.contact_sheet_guidance import CONTACT_SHEET_READING_INSTRUCTIONS

    contract_section = build_exercise_motion_contract_prompt_section(exercise_motion_contract)
    return (
        "Score this sampled video chunk for exercise motion extraction source suitability as part of a full-video scan.\n"
        f"Target exercise: {exercise_name}.\n"
        f"Video title: {candidate.title}.\n"
        f"{contract_section}"
        "Judge only the attached frames/contact sheets from this chunk. Do not infer missing phases from other chunks.\n"
        f"{CONTACT_SHEET_READING_INSTRUCTIONS}"
        "The broader candidate video may contain unrelated intro, instruction, or other material; that is acceptable only if this exact chunk contains a clean usable target-exercise movement.\n"
        "The reviewed chunk itself must be usable as the source window for motion extraction. Do not pass a chunk merely because the broader video may contain a good segment elsewhere.\n"
        "Ignore written labels, captions, arrows, diagrams, and instruction text when deciding whether the target movement is visible; use the visible human motion only.\n"
        "If the target exercise name combines actions with words such as 'and' or '/' or otherwise names multiple phases, this exact chunk must visibly include all named actions/phases in one continuous movement. A chunk showing only one named phase is partial_movement.\n"
        "Good chunks show continuous uninterrupted repetitions or at least one complete uninterrupted movement from the start posture, through the main action path, to the end posture.\n"
        "Reject chunks that only show setup, instruction, hanging/holding/standing/lying idle, walking into position, talking to camera, a title card, or only a partial phase of the movement.\n"
        "Do not treat a natural start or finish posture as setup/idle merely because the athlete is briefly hanging, standing, lying, holding, or paused there; if that posture is directly connected to the visible movement, it is part of the exercise boundary.\n"
        "Extra non-exercise frames before or after the movement are a blocking issue for source selection; include setup_or_talking and lower source_score even if a partial rep is visible.\n"
        "Treat the target exercise name as the exact movement identity, not just a loose keyword match. Adjacent variations that share words but visibly change the required stance, support, equipment path, body position, or movement pattern are wrong for this target.\n"
        "If the requested exercise name contains qualifiers such as single-leg, split, incline, decline, seated, bent-over, front, back, lateral, supported, unsupported, dumbbell, barbell, cable, machine, or similar variant terms, the visible movement must satisfy those qualifiers.\n"
        "If the target exercise name implies external loading or equipment, including words such as weighted, loaded, dumbbell, kettlebell, barbell, plate, vest, belt, cable, machine, smith-machine, band, medicine-ball, or sandbag, that load/equipment must be visibly used in the chunk. If the visible person performs the unloaded/bodyweight version or the required load is not visible, set target_identity_match false and include wrong_variant.\n"
        "If the source title or visible movement adds an exercise-changing qualifier that is not in the target name, mark target_identity_match false. Examples: incline, decline, seated, supported, machine, smith-machine, close-grip, wide-grip, single-arm, or triceps-focused variants are wrong unless requested by the target exercise name.\n"
        "Pose/camera suitability is handled by deterministic YOLO/pose filtering before and after this step. Do not return gates for camera cuts, camera stability, crop, body scale, joint visibility, obstruction, pose angle, or person count; those are not your responsibility.\n"
        "For source selection, prefer clean repeatable demo repetitions over records, personal records, max attempts, AMRAP tests, competitions, combines, meets, crowds, or event footage. Those event clips are lower-quality motion sources even when the exercise is technically correct.\n"
        "Reject step-by-step demonstrations, setup, talking, title cards, and slow instructional breakdowns.\n"
        "Set movement_start_posture_visible true only if the chunk visibly includes the beginning posture of a full movement or repetition. Set it false for mid-rep starts, idle setup, or a person only preparing to move.\n"
        "Set primary_effort_phase_visible true only if the chunk visibly includes the main intended action of the requested exercise, not just the return, lowering, eccentric, negative, reset, or recovery phase. If the target exercise name explicitly requests a negative/eccentric/return-only variation, judge that requested phase as the primary effort.\n"
        "Set movement_action_path_visible true only if the chunk visibly includes the main joint/body travel of the movement, not just the athlete holding the start/end position.\n"
        "Set movement_end_posture_visible true only if the chunk visibly reaches the natural end posture of that same movement or repetition. Set it false for clips that stop mid-rep or before the movement resolves.\n"
        "Set no_setup_or_talking_frames false when any attached sheet is primarily setup, talking, instruction, title-card, walking into position, idle hanging/standing/lying, or reset content rather than the exercise movement. Keep it true when brief boundary postures are directly attached to the full movement.\n"
        "Prefer real camera footage of real people. Score the moving exercise subject with moving_subject_realism_score: 1.0 means a clearly real person captured by camera, 0.85 means the lowest acceptable confidence for a real camera-captured human, 0.7 means probably real but visually ambiguous and not strong enough as a source, 0.4 means mannequin-like or heavily synthetic-looking, and 0.0 means animated, CGI, rendered, game footage, motion-capture preview, skeleton-only demo, avatar, anatomy illustration, or synthetic humanoid.\n"
        "Judge realism only for the moving athlete/body performing the exercise. Animated text, timers, captions, title graphics, logos, or other overlays on top of real footage are not a subject-realism failure.\n"
        "Report moving_subject_realism_score independently from the visual evidence. Do not compensate for a low realism score by raising source_score, and do not include animation_or_synthetic in blocking_issues; ranking code will handle realism as its own hard suitability signal.\n"
        "Return boolean values for gate fields and numeric scores from 0.0 to 1.0 for score fields.\n"
        "Use this scale: 1.0 excellent, 0.8 good, 0.6 flawed but maybe usable, 0.4 poor, 0.0 unusable.\n"
        "Score definitions:\n"
        "- target_match: how clearly this chunk shows the requested exercise.\n"
        "- complete_movement: how clearly this exact chunk contains a full movement cycle with visible start posture, main action path, and end posture, not just exercise context or a partial transition.\n"
        "- moving_subject_realism_score: how clearly the moving exercise subject is a real human body captured by a camera, ignoring text/graphics overlays that are not the subject.\n"
        "- execution_quality: how naturally the exercise is performed: normal-speed, continuous, not paused, slow teaching, step-by-step, setup, talking, or title-card content.\n"
        "- source_score: overall semantic usefulness of this exact chunk as a target-exercise motion source, assuming deterministic pose/camera gates are handled elsewhere.\n"
        "Before scoring, list semantic blocking issues only. Use [] or [\"none\"] only if no semantic blocking issue is visible. Allowed semantic issues are wrong_exercise, wrong_variant, partial_movement, slow_instruction, setup_or_talking, and unclear.\n"
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
        '"no_step_breakdown": boolean, '
        '"movement_start_posture_visible": boolean, '
        '"primary_effort_phase_visible": boolean, '
        '"movement_action_path_visible": boolean, '
        '"movement_end_posture_visible": boolean, '
        '"no_setup_or_talking_frames": boolean, '
        '"target_identity_match": boolean, '
        '"target_match": number, '
        '"complete_movement": number, '
        '"moving_subject_realism_score": number, '
        '"execution_quality": number, '
        '"source_score": number, '
        '"blocking_issues": ["none|wrong_exercise|wrong_variant|partial_movement|slow_instruction|setup_or_talking|unclear"], '
        '"confidence": number, '
        '"reason": string'
        "}"
    )
