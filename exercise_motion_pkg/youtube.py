from __future__ import annotations

import os
from pathlib import Path


def download_youtube(url: str, output_dir: Path) -> Path:
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is required for YouTube downloads. Install with: pip install .[motion]"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "source.%(ext)s")
    options = {
        "format": "best[ext=mp4]/bestvideo[ext=mp4]/bestvideo/best",
        "outtmpl": template,
        "quiet": False,
        "noprogress": False,
        "noplaylist": True,
        "retries": 3,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded = Path(ydl.prepare_filename(info))
    if downloaded.exists():
        return downloaded
    for extension in (".mp4", ".mkv", ".webm", ".mov"):
        candidate = Path(os.path.splitext(str(downloaded))[0] + extension)
        if candidate.exists():
            return candidate
    raise RuntimeError(f"Download finished but no video file was found in {output_dir}.")
