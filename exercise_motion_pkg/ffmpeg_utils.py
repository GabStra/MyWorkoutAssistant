from __future__ import annotations

import os
import shutil
from pathlib import Path


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
