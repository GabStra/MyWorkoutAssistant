from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
import subprocess
from pathlib import Path


@dataclass(frozen=True)
class BasicVideoMetadata:
    fps: float
    frame_count: int
    width: int
    height: int

    @property
    def duration_seconds(self) -> float:
        if self.fps <= 0:
            return 0.0
        return self.frame_count / self.fps


def read_basic_video_metadata(video_path: Path) -> BasicVideoMetadata:
    ffprobe_metadata = read_basic_video_metadata_with_ffprobe(video_path)
    if ffprobe_metadata is not None:
        return ffprobe_metadata

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python is required for video trimming. Install with: pip install -e .[motion]"
        ) from exc

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        capture.release()
    return BasicVideoMetadata(
        fps=fps,
        frame_count=frame_count,
        width=width,
        height=height,
    )


def read_basic_video_metadata_with_ffprobe(video_path: Path) -> BasicVideoMetadata | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,duration",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        return None
    stream = streams[0]
    fps = parse_frame_rate(str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"))
    width = int(float(stream.get("width") or 0))
    height = int(float(stream.get("height") or 0))
    frame_count = parse_int(stream.get("nb_frames"))
    duration = parse_float(stream.get("duration"))
    if frame_count <= 0 and duration > 0 and fps > 0:
        frame_count = max(1, int(round(duration * fps)))
    if fps <= 0 or frame_count <= 0:
        return None
    return BasicVideoMetadata(fps=fps, frame_count=frame_count, width=width, height=height)


def parse_frame_rate(value: str) -> float:
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = parse_float(denominator)
        if denominator_value == 0:
            return 0.0
        return parse_float(numerator) / denominator_value
    return parse_float(value)


def parse_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_int(value: object) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def trim_video(
    *,
    source_path: Path,
    output_path: Path,
    start_seconds: float,
    end_seconds: float,
) -> Path:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is not None:
        return _trim_video_with_ffmpeg(
            source_path=source_path,
            output_path=output_path,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            ffmpeg=ffmpeg_path,
        )

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python is required for video trimming. Install with: pip install -e .[motion]"
        ) from exc

    metadata = read_basic_video_metadata(source_path)
    if metadata.fps <= 0:
        raise RuntimeError(f"Could not determine FPS for video: {source_path}")

    safe_start = max(0.0, float(start_seconds))
    safe_end = max(safe_start, float(end_seconds))
    start_frame = max(0, int(round(safe_start * metadata.fps)))
    end_frame_exclusive = min(metadata.frame_count, max(start_frame + 1, int(round(safe_end * metadata.fps))))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {source_path}")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(
        str(output_path),
        fourcc,
        metadata.fps,
        (metadata.width, metadata.height),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open video writer for output: {output_path}")

    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        current_frame = start_frame
        while current_frame < end_frame_exclusive:
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(frame)
            current_frame += 1
    finally:
        capture.release()
        writer.release()

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Trimmed video was not created correctly: {output_path}")
    return output_path


def _trim_video_with_ffmpeg(
    *,
    source_path: Path,
    output_path: Path,
    start_seconds: float,
    end_seconds: float,
    ffmpeg: str,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    safe_start = max(0.0, float(start_seconds))
    safe_end = max(safe_start, float(end_seconds))
    if safe_end <= safe_start:
        raise ValueError("end_seconds must be greater than start_seconds.")

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-ss",
        str(safe_start),
        "-to",
        str(safe_end),
        "-i",
        str(source_path),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    process = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg trim failed: {process.stderr}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Trimmed video was not created correctly: {output_path}")
    return output_path
