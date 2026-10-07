from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import functools
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from exercise_motion_pkg.ffmpeg_utils import resolve_ffmpeg_path
from exercise_motion_pkg.stage_cache import cache_key, cached_paths
from exercise_motion_pkg.video_utils import read_basic_video_metadata


SOURCE_FRAME_CACHE_VERSION = 1
SOURCE_FRAME_CACHE_MAX_DECODED_FRAMES = 600
_SHOWINFO_PTS_RE = re.compile(r"\bn:\s*(\d+)\s+pts:\s*(-?\d+)")
_SHOWINFO_TIME_BASE_RE = re.compile(r"\bconfig in time_base:\s*(\d+)\s*/\s*(\d+)")


@dataclass(frozen=True)
class NativeFrameIndex:
    frame_paths: tuple[Path, ...]
    pts_ticks: tuple[int, ...]
    time_base: Fraction
    first_pts: int
    cache_key: str

    @property
    def normalized_pts(self) -> tuple[Fraction, ...]:
        return tuple((pts - self.first_pts) * self.time_base for pts in self.pts_ticks)


@dataclass(frozen=True)
class SourceFrameCacheBuild:
    index: NativeFrameIndex | None
    status: str
    reason: str | None
    estimated_frame_count: int | None
    decoded_frame_count: int
    cache_hit: bool
    elapsed_seconds: float


def frame_path_for_seek(index: NativeFrameIndex, seek_timestamp: str) -> Path | None:
    """Return the frame selected by the production three-decimal seek target."""
    try:
        target_seconds = Fraction(Decimal(seek_timestamp))
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return None
    frame_index = bisect_left(index.normalized_pts, target_seconds)
    if frame_index >= len(index.frame_paths):
        return None
    return index.frame_paths[frame_index]


def build_source_frame_index(
    *,
    video_path: Path,
    seek_timestamps: list[str],
    cache_dir: Path,
    max_frame_width: int,
    max_decoded_frames: int = SOURCE_FRAME_CACHE_MAX_DECODED_FRAMES,
) -> SourceFrameCacheBuild:
    """Decode a bounded short source once and index native JPEGs by normalized PTS.

    `seek_timestamps` must be the formatted values used by the existing per-window
    extractor. Unsupported or over-budget sources return a reason so callers can
    use that extractor unchanged.
    """
    import time

    started = time.perf_counter()
    ffmpeg = resolve_ffmpeg_path()
    if ffmpeg is None:
        return _fallback("ffmpeg_unavailable", None, started)
    unique_seeks = sorted(set(seek_timestamps))
    if not unique_seeks:
        return _fallback("no_requested_samples", None, started)
    try:
        metadata = read_basic_video_metadata(video_path)
        estimated_count = int(metadata.frame_count)
        if (
            metadata.fps <= 0
            or metadata.duration_seconds <= 0
            or estimated_count <= 0
        ):
            return _fallback("unknown_video_metadata", estimated_count or None, started)
        if estimated_count > min(len(unique_seeks), max_decoded_frames):
            return _fallback("source_exceeds_short_decode_budget", estimated_count, started)
        ffmpeg_version = _ffmpeg_version(ffmpeg)
        if not ffmpeg_version:
            return _fallback("ffmpeg_version_unavailable", estimated_count, started)
    except Exception as exc:
        return _fallback(f"metadata_error:{type(exc).__name__}", None, started)

    profile = {
        "cacheVersion": SOURCE_FRAME_CACHE_VERSION,
        "ffmpeg": str(Path(ffmpeg).resolve()),
        "ffmpegVersion": ffmpeg_version,
        "maxFrameWidth": int(max_frame_width),
        "filter": f"scale='min({int(max_frame_width)},iw)':-2,showinfo",
        "jpegQuality": 5,
        "passthrough": True,
        "ptsNormalization": "first-decoded-pts-integer-timebase-v1",
        "maxDecodedFrames": int(max_decoded_frames),
    }
    try:
        key = cache_key(
            profile,
            [
                video_path,
                Path(__file__),
                Path(__file__).with_name("segment_detection.py"),
                Path(__file__).with_name("ffmpeg_utils.py"),
            ],
        )
    except Exception as exc:
        return _fallback(f"cache_identity_error:{type(exc).__name__}", estimated_count, started)
    cache_root = cache_dir / key
    checkpoint = cache_root / "native_frame_index.json"
    pts_path = cache_root / "native_frame_pts.json"
    computed = [False]

    def compute() -> list[Path]:
        computed[0] = True
        cache_root.mkdir(parents=True, exist_ok=True)
        for stale_path in cache_root.glob("native_frame_*.jpg"):
            stale_path.unlink(missing_ok=True)
        pts_path.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="native-frame-decode-") as temporary:
            temporary_root = Path(temporary)
            frame_pattern = temporary_root / "frame_%06d.jpg"
            command = [
                ffmpeg,
                "-hide_banner", "-y", "-loglevel", "info",
                "-i", str(video_path),
                "-vf", f"scale='min({int(max_frame_width)},iw)':-2,showinfo",
                "-vsync", "0",
                "-q:v", "5",
                "-frames:v", str(max_decoded_frames + 1),
                "-start_number", "1",
                str(frame_pattern),
            ]
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=90,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg_exit_{result.returncode}")
            frame_paths = sorted(temporary_root.glob("frame_*.jpg"))
            if len(frame_paths) > max_decoded_frames:
                raise RuntimeError("runtime_frame_cap_exceeded")
            pts_ticks, time_base = _parse_showinfo_pts(result.stderr)
            if len(pts_ticks) != len(frame_paths) or not pts_ticks:
                raise RuntimeError("decoded_frame_pts_count_mismatch")
            if pts_ticks[0] != 0:
                raise RuntimeError("nonzero_first_pts_unsupported")
            if any(right <= left for left, right in zip(pts_ticks, pts_ticks[1:])):
                raise RuntimeError("nonmonotonic_or_duplicate_pts")
            if len(frame_paths) > len(unique_seeks):
                raise RuntimeError("runtime_frame_count_exceeds_unique_seeks")
            final_paths: list[Path] = []
            for frame_number, frame_path in enumerate(frame_paths, start=1):
                final_path = cache_root / f"native_frame_{frame_number:06d}.jpg"
                shutil.copyfile(frame_path, final_path)
                final_paths.append(final_path)
            pts_path.write_text(
                json.dumps(
                    {
                        "cacheVersion": SOURCE_FRAME_CACHE_VERSION,
                        "ptsTicks": pts_ticks,
                        "timeBaseNumerator": time_base.numerator,
                        "timeBaseDenominator": time_base.denominator,
                        "firstPts": pts_ticks[0],
                    },
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            return final_paths

    try:
        frame_paths = cached_paths(
            checkpoint,
            key,
            compute,
            supporting_outputs=lambda: [pts_path],
        )
        was_cached = not computed[0]
        record = json.loads(pts_path.read_text(encoding="utf-8"))
        pts_ticks = tuple(int(value) for value in record["ptsTicks"])
        time_base = Fraction(
            int(record["timeBaseNumerator"]),
            int(record["timeBaseDenominator"]),
        )
        first_pts = int(record["firstPts"])
        if len(frame_paths) != len(pts_ticks) or time_base <= 0:
            raise ValueError("invalid_cached_pts_index")
        index = NativeFrameIndex(tuple(frame_paths), pts_ticks, time_base, first_pts, key)
        if any(frame_path_for_seek(index, seek) is None for seek in unique_seeks):
            return _fallback("requested_sample_outside_decoded_pts", estimated_count, started)
        return SourceFrameCacheBuild(
            index=index,
            status="cache_hit" if was_cached else "decoded",
            reason=None,
            estimated_frame_count=estimated_count,
            decoded_frame_count=len(frame_paths),
            cache_hit=was_cached,
            elapsed_seconds=time.perf_counter() - started,
        )
    except Exception as exc:
        return _fallback(f"decode_or_cache_error:{type(exc).__name__}:{exc}", estimated_count, started)


def _parse_showinfo_pts(stderr: str) -> tuple[tuple[int, ...], Fraction]:
    time_bases = [
        (int(match.group(1)), int(match.group(2)))
        for match in _SHOWINFO_TIME_BASE_RE.finditer(stderr)
    ]
    if not time_bases:
        raise ValueError("showinfo_timebase_missing")
    time_base = Fraction(*time_bases[0])
    if time_base <= 0 or any(Fraction(*candidate) != time_base for candidate in time_bases):
        raise ValueError("showinfo_timebase_invalid")
    pts_ticks = tuple(int(match.group(2)) for match in _SHOWINFO_PTS_RE.finditer(stderr))
    if not pts_ticks:
        raise ValueError("showinfo_pts_missing")
    return pts_ticks, time_base


@functools.lru_cache(maxsize=4)
def _ffmpeg_version(ffmpeg: str) -> str | None:
    try:
        result = subprocess.run(
            [ffmpeg, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return result.stdout.splitlines()[0].strip()


def _fallback(reason: str, estimated_count: int | None, started: float) -> SourceFrameCacheBuild:
    import time

    return SourceFrameCacheBuild(
        index=None,
        status="fallback",
        reason=reason,
        estimated_frame_count=estimated_count,
        decoded_frame_count=0,
        cache_hit=False,
        elapsed_seconds=time.perf_counter() - started,
    )
