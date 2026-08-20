from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess
from pathlib import Path

from exercise_motion_pkg.ffmpeg_utils import resolve_ffmpeg_path, resolve_ffprobe_path


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
    ffprobe = resolve_ffprobe_path()
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


def rotate_video_quarter_turn(*, source_path: Path, output_path: Path, counter_clockwise: bool) -> Path:
    """Rotate a video by exactly 90 degrees without changing its timeline."""
    ffmpeg_path = resolve_ffmpeg_path()
    if not ffmpeg_path:
        return _rotate_video_quarter_turn_with_opencv(
            source_path=source_path,
            output_path=output_path,
            counter_clockwise=counter_clockwise,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    transpose = "2" if counter_clockwise else "1"
    process = subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-i",
            str(source_path),
            "-vf",
            f"transpose={transpose}",
            "-an",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0 or not output_path.exists():
        raise RuntimeError(
            "Could not rotate WHAM input video.\n"
            f"stdout:\n{process.stdout}\n"
            f"stderr:\n{process.stderr}"
        )
    return output_path


def _rotate_video_quarter_turn_with_opencv(
    *, source_path: Path,
    output_path: Path,
    counter_clockwise: bool,
) -> Path:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "WHAM input orientation normalization requires either ffmpeg or opencv-python."
        ) from exc
    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video for orientation normalization: {source_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if source_width <= 0 or source_height <= 0:
        capture.release()
        raise RuntimeError(f"Could not read video dimensions for orientation normalization: {source_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (source_height, source_width),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not create rotated video: {output_path}")
    rotation_code = (
        cv2.ROTATE_90_COUNTERCLOCKWISE
        if counter_clockwise
        else cv2.ROTATE_90_CLOCKWISE
    )
    frame_count = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(cv2.rotate(frame, rotation_code))
            frame_count += 1
    finally:
        capture.release()
        writer.release()
    if frame_count <= 0 or not output_path.exists():
        raise RuntimeError(f"Rotated video contains no frames: {output_path}")
    return output_path


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
    target_fps: float | None = None,
) -> Path:
    ffmpeg_path = resolve_ffmpeg_path()
    if ffmpeg_path is not None:
        kwargs: dict[str, object] = {
            "source_path": source_path,
            "output_path": output_path,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "ffmpeg": ffmpeg_path,
        }
        if target_fps is not None:
            kwargs["target_fps"] = target_fps
        return _trim_video_with_ffmpeg(**kwargs)

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
    output_fps = float(target_fps) if target_fps is not None and target_fps > 0.0 else metadata.fps
    writer = cv2.VideoWriter(
        str(output_path),
        fourcc,
        output_fps,
        (metadata.width, metadata.height),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open video writer for output: {output_path}")

    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        current_frame = start_frame
        selected_frames = []
        while current_frame < end_frame_exclusive:
            ok, frame = capture.read()
            if not ok:
                break
            if target_fps is None:
                writer.write(frame)
            else:
                selected_frames.append(frame)
            current_frame += 1
        if target_fps is not None:
            if not selected_frames:
                raise RuntimeError(f"Trimmed video contains no frames: {source_path}")
            output_frame_count = max(1, int(round(len(selected_frames) * output_fps / metadata.fps)))
            for output_index in range(output_frame_count):
                source_index = min(
                    len(selected_frames) - 1,
                    int(round(output_index * metadata.fps / output_fps)),
                )
                writer.write(selected_frames[source_index])
    finally:
        capture.release()
        writer.release()

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Trimmed video was not created correctly: {output_path}")
    return output_path


def convert_video_to_webm(
    *,
    source_path: Path,
    output_path: Path,
) -> Path:
    ffmpeg_path = resolve_ffmpeg_path()
    if ffmpeg_path is not None:
        return _convert_video_to_webm_with_ffmpeg(
            source_path=source_path,
            output_path=output_path,
            ffmpeg=ffmpeg_path,
        )
    raise RuntimeError(
        "FFmpeg is required for reliable VP9/WebM conversion. "
        "Set MWA_FFMPEG_PATH or install imageio-ffmpeg."
    )


def _trim_video_with_ffmpeg(
    *,
    source_path: Path,
    output_path: Path,
    start_seconds: float,
    end_seconds: float,
    target_fps: float | None = None,
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
    ]
    if target_fps is not None and target_fps > 0.0:
        command.extend(["-vf", f"fps={float(target_fps):g}"])
    command.extend([
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
    ])
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


def _convert_video_to_webm_with_ffmpeg(
    *,
    source_path: Path,
    output_path: Path,
    ffmpeg: str,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-i",
        str(source_path),
        "-an",
        "-c:v",
        "libvpx-vp9",
        "-pix_fmt",
        "yuv420p",
        "-deadline",
        "good",
        "-cpu-used",
        "4",
        "-crf",
        "32",
        "-b:v",
        "0",
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
        raise RuntimeError(f"ffmpeg WebM conversion failed: {process.stderr}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"WebM video was not created correctly: {output_path}")
    return output_path
