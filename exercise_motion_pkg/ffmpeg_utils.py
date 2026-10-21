from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_NVENC_H264_PROBE: tuple[bool, bool] | None = None
LIBX264_CODEC_ARGS = ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]


def h264_codec_args(*, fallback: bool = False) -> list[str]:
    """H.264 encode args: NVENC when the resolved ffmpeg supports it, else libx264.

    NVENC runs on the GPU's dedicated encoder block, keeping encodes off the
    CPU fit lanes. fallback=True forces libx264 for runtime retries (NVENC
    sessions can be exhausted even when the encoder exists).
    """
    if fallback:
        return list(LIBX264_CODEC_ARGS)
    global _NVENC_H264_PROBE
    if _NVENC_H264_PROBE is None:
        available = False
        ffmpeg = resolve_ffmpeg_path()
        if ffmpeg:
            try:
                result = subprocess.run(
                    [ffmpeg, "-hide_banner", "-encoders"],
                    capture_output=True,
                    text=True,
                    timeout=15.0,
                )
                available = " h264_nvenc" in result.stdout
            except (OSError, subprocess.SubprocessError):
                available = False
        _NVENC_H264_PROBE = (True, available)
    if _NVENC_H264_PROBE[1]:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "20", "-b:v", "0"]
    return list(LIBX264_CODEC_ARGS)


def retry_h264_codec_args(command: list[str], codec_args: list[str]) -> list[str] | None:
    """Replace a failed NVENC codec section with libx264 args, or None if n/a."""
    if codec_args[1] != "h264_nvenc":
        return None
    start = command.index(codec_args[0])
    command[start:start + len(codec_args)] = h264_codec_args(fallback=True)
    return command


def resolve_ffmpeg_path() -> str | None:
    return (
        _resolve_explicit_binary("ffmpeg", "MWA_FFMPEG_PATH", "FFMPEG_BINARY", "IMAGEIO_FFMPEG_EXE")
        or shutil.which("ffmpeg")
        or _resolve_imageio_ffmpeg()
    )


def resolve_ffprobe_path() -> str | None:
    explicit = _resolve_explicit_binary("ffprobe", "MWA_FFPROBE_PATH", "FFPROBE_BINARY")
    if explicit:
        return explicit
    found = shutil.which("ffprobe")
    if found:
        return found
    ffmpeg = resolve_ffmpeg_path()
    if not ffmpeg:
        return None
    ffmpeg_path = Path(ffmpeg)
    suffix = ".exe" if os.name == "nt" else ""
    for candidate in (
        ffmpeg_path.with_name(f"ffprobe{suffix}"),
        ffmpeg_path.parent / f"ffprobe{suffix}",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def ffmpeg_location_for_ytdlp() -> str | None:
    ffmpeg = resolve_ffmpeg_path()
    return str(ffmpeg) if ffmpeg else None


def _resolve_explicit_binary(binary_name: str, *env_names: str) -> str | None:
    for env_name in env_names:
        raw_value = os.environ.get(env_name)
        if not raw_value:
            continue
        value = raw_value.strip().strip('"')
        if not value:
            continue
        path = Path(value).expanduser()
        resolved_path = _resolve_path_value(path, binary_name)
        if resolved_path is not None:
            return resolved_path
        found = shutil.which(value)
        if found:
            return found
    return None


def _resolve_path_value(path: Path, binary_name: str) -> str | None:
    suffix = ".exe" if os.name == "nt" else ""
    if path.is_file():
        return str(path)
    if path.is_dir():
        for candidate in (
            path / f"{binary_name}{suffix}",
            path / "bin" / f"{binary_name}{suffix}",
        ):
            if candidate.is_file():
                return str(candidate)
    return None


def _resolve_imageio_ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore
    except Exception:
        return None
    try:
        executable = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    if not executable:
        return None
    path = Path(str(executable))
    return str(path) if path.exists() else None
