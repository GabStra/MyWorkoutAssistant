from __future__ import annotations

from dataclasses import dataclass
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


def trim_video(
    *,
    source_path: Path,
    output_path: Path,
    start_seconds: float,
    end_seconds: float,
) -> Path:
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
