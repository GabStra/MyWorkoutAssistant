from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from exercise_motion_pkg.video_utils import read_basic_video_metadata


@dataclass(frozen=True)
class DetectionSettings:
    base_url: str = "http://127.0.0.1:8090"
    model: str = "local-vision"
    litert_command: str | None = None
    litert_backend: str = "gpu"
    window_seconds: float = 4.0
    overlap_seconds: float = 2.0
    frames_per_window: int = 6
    max_frame_width: int = 960
    merge_gap_seconds: float = 2.0
    confidence_threshold: float = 0.45
    health_timeout_seconds: float = 180.0


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float
    fps: float
    frame_count: int
    width: int
    height: int


@dataclass(frozen=True)
class DetectionWindow:
    index: int
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class WindowDetection:
    window: DetectionWindow
    movement_present: bool
    contains_movement_start: bool
    contains_movement_end: bool
    movement_start_seconds: float | None
    movement_end_seconds: float | None
    confidence: float
    summary: str
    reason: str
    camera_variation: float
    frame_paths: list[str]


@dataclass(frozen=True)
class DetectedSpan:
    start_seconds: float
    end_seconds: float
    confidence: float
    average_camera_variation: float
    contributing_windows: list[int]


@dataclass(frozen=True)
class DetectionResult:
    video_path: str
    exercise_name: str | None
    source_duration_seconds: float
    window_seconds: float
    overlap_seconds: float
    detected_span: DetectedSpan | None
    windows: list[WindowDetection]


def detect_exercise_segment(
    *,
    video_path: Path,
    output_dir: Path,
    settings: DetectionSettings,
    exercise_name: str | None = None,
) -> DetectionResult:
    metadata = read_video_metadata(video_path)
    windows = iter_detection_windows(
        duration_seconds=metadata.duration_seconds,
        window_seconds=settings.window_seconds,
        overlap_seconds=settings.overlap_seconds,
    )
    if settings.litert_command:
        client = LiteRtCliVisionClient(
            command=settings.litert_command,
            model=settings.model,
            backend=settings.litert_backend,
        )
    else:
        client = LlamaCppVisionClient(settings.base_url, settings.model)
    output_dir.mkdir(parents=True, exist_ok=True)

    detections: list[WindowDetection] = []
    for window in windows:
        frame_paths = extract_window_frames(
            video_path=video_path,
            window=window,
            frames_per_window=settings.frames_per_window,
            max_frame_width=settings.max_frame_width,
            output_dir=output_dir / f"window_{window.index:04d}",
        )
        detections.append(
            client.detect_window(
                frame_paths=frame_paths,
                window=window,
                exercise_name=exercise_name,
            )
        )

    detected_span = choose_detected_span(
        detections=detections,
        confidence_threshold=settings.confidence_threshold,
        merge_gap_seconds=settings.merge_gap_seconds,
    )
    return DetectionResult(
        video_path=str(video_path),
        exercise_name=exercise_name,
        source_duration_seconds=metadata.duration_seconds,
        window_seconds=settings.window_seconds,
        overlap_seconds=settings.overlap_seconds,
        detected_span=detected_span,
        windows=detections,
    )


def save_detection_result(path: Path, result: DetectionResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "videoPath": result.video_path,
        "exerciseName": result.exercise_name,
        "sourceDurationSeconds": result.source_duration_seconds,
        "windowSeconds": result.window_seconds,
        "overlapSeconds": result.overlap_seconds,
        "detectedSpan": None if result.detected_span is None else asdict(result.detected_span),
        "windows": [
            {
                "index": item.window.index,
                "startSeconds": item.window.start_seconds,
                "endSeconds": item.window.end_seconds,
                "movementPresent": item.movement_present,
                "containsMovementStart": item.contains_movement_start,
                "containsMovementEnd": item.contains_movement_end,
                "movementStartSeconds": item.movement_start_seconds,
                "movementEndSeconds": item.movement_end_seconds,
                "confidence": item.confidence,
                "summary": item.summary,
                "reason": item.reason,
                "cameraVariation": item.camera_variation,
                "framePaths": item.frame_paths,
            }
            for item in result.windows
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_video_metadata(video_path: Path) -> VideoMetadata:
    basic = read_basic_video_metadata(video_path)
    return VideoMetadata(
        duration_seconds=basic.duration_seconds,
        fps=basic.fps,
        frame_count=basic.frame_count,
        width=basic.width,
        height=basic.height,
    )


def iter_detection_windows(
    *,
    duration_seconds: float,
    window_seconds: float,
    overlap_seconds: float,
) -> list[DetectionWindow]:
    if duration_seconds <= 0:
        return []
    window_seconds = max(0.5, window_seconds)
    step_seconds = max(0.25, window_seconds - overlap_seconds)
    windows: list[DetectionWindow] = []
    start = 0.0
    index = 0
    while start < duration_seconds:
        end = min(duration_seconds, start + window_seconds)
        windows.append(DetectionWindow(index=index, start_seconds=start, end_seconds=end))
        index += 1
        if end >= duration_seconds:
            break
        start += step_seconds
    return windows


def extract_window_frames(
    *,
    video_path: Path,
    window: DetectionWindow,
    frames_per_window: int,
    max_frame_width: int,
    output_dir: Path,
) -> list[Path]:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python is required for exercise segment detection. Install with: pip install -e .[motion]"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    times = linspace_times(window.start_seconds, window.end_seconds, max(1, frames_per_window))
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    frame_paths: list[Path] = []
    try:
        for frame_index, timestamp_seconds in enumerate(times, start=1):
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_seconds * 1000.0)
            ok, frame = capture.read()
            if not ok:
                continue
            if max_frame_width > 0 and frame.shape[1] > max_frame_width:
                scale = max_frame_width / float(frame.shape[1])
                target_size = (max_frame_width, max(1, int(round(frame.shape[0] * scale))))
                frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
            frame_path = output_dir / f"frame_{frame_index:02d}.jpg"
            cv2.imwrite(str(frame_path), frame)
            frame_paths.append(frame_path)
    finally:
        capture.release()
    if not frame_paths:
        raise RuntimeError(
            f"No frames could be extracted for window {window.index} ({window.start_seconds:.2f}-{window.end_seconds:.2f}s)."
        )
    return frame_paths


def linspace_times(start_seconds: float, end_seconds: float, count: int) -> list[float]:
    if count <= 1:
        return [start_seconds]
    duration = max(0.0, end_seconds - start_seconds)
    if duration <= 0:
        return [start_seconds] * count
    usable_end = max(start_seconds, end_seconds - min(0.05, duration / 2.0))
    step = (usable_end - start_seconds) / float(count - 1)
    return [start_seconds + step * index for index in range(count)]


class LlamaCppVisionClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.Client(timeout=600.0)

    def detect_window(
        self,
        *,
        frame_paths: list[Path],
        window: DetectionWindow,
        exercise_name: str | None,
    ) -> WindowDetection:
        prompt = build_window_prompt(
            exercise_name=exercise_name,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
        )
        raw = self.caption_images(frame_paths=frame_paths, prompt=prompt)
        payload = parse_detection_payload(raw, window=window)
        return WindowDetection(
            window=window,
            movement_present=payload["movement_present"],
            contains_movement_start=payload["contains_movement_start"],
            contains_movement_end=payload["contains_movement_end"],
            movement_start_seconds=payload["movement_start_seconds"],
            movement_end_seconds=payload["movement_end_seconds"],
            confidence=payload["confidence"],
            summary=payload["summary"],
            reason=payload["reason"],
            camera_variation=compute_camera_variation(frame_paths),
            frame_paths=[str(path) for path in frame_paths],
        )

    def caption_images(self, *, frame_paths: list[Path], prompt: str) -> str:
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        for frame_path in frame_paths:
            encoded = base64.b64encode(frame_path.read_bytes()).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        if self.model == "local-vision":
            payload["reasoning_format"] = "none"
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        response = self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        if response.status_code >= 400:
            fallback_payload = dict(payload)
            fallback_payload.pop("response_format", None)
            fallback_payload.pop("reasoning_format", None)
            fallback_payload.pop("chat_template_kwargs", None)
            response = self.client.post(f"{self.base_url}/v1/chat/completions", json=fallback_payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


class VisionClient:
    def detect_window(
        self,
        *,
        frame_paths: list[Path],
        window: DetectionWindow,
        exercise_name: str | None,
    ) -> WindowDetection:
        raise NotImplementedError


class LiteRtCliVisionClient(VisionClient):
    def __init__(self, *, command: str, model: str, backend: str) -> None:
        self.command = command
        self.model = model
        self.backend = backend

    def detect_window(
        self,
        *,
        frame_paths: list[Path],
        window: DetectionWindow,
        exercise_name: str | None,
    ) -> WindowDetection:
        prompt = build_window_prompt(
            exercise_name=exercise_name,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
        )
        raw = self.caption_images(frame_paths=frame_paths, prompt=prompt)
        payload = parse_detection_payload(raw, window=window)
        return WindowDetection(
            window=window,
            movement_present=payload["movement_present"],
            contains_movement_start=payload["contains_movement_start"],
            contains_movement_end=payload["contains_movement_end"],
            movement_start_seconds=payload["movement_start_seconds"],
            movement_end_seconds=payload["movement_end_seconds"],
            confidence=payload["confidence"],
            summary=payload["summary"],
            reason=payload["reason"],
            camera_variation=compute_camera_variation(frame_paths),
            frame_paths=[str(path) for path in frame_paths],
        )

    def caption_images(self, *, frame_paths: list[Path], prompt: str) -> str:
        command = [
            self.command,
            "run",
            self.model,
            "--backend",
            self.backend,
            "--vision-backend",
            self.backend,
            "--prompt",
            prompt,
        ]
        for frame_path in frame_paths:
            command.extend(["--attachment", str(frame_path)])
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()


def build_window_prompt(*, exercise_name: str | None, start_seconds: float, end_seconds: float) -> str:
    exercise_clause = (
        f"Target exercise or movement: {exercise_name}.\n"
        if exercise_name and exercise_name.strip()
        else "Target exercise or movement: infer from the video and focus on the main deliberate exercise movement.\n"
    )
    return (
        "Analyze this exercise video window.\n"
        f"Window time range in source video: {start_seconds:.2f}s to {end_seconds:.2f}s.\n"
        f"{exercise_clause}"
        "You are given multiple sampled frames from the same time window. Judge the exercise from the sequence of frames together, not from any single frame alone.\n"
        "Determine whether this window contains the part where the exercise rep is actively being performed.\n"
        "We are specifically looking for the part where the exercise rep is actually done, not setup, explanation, or idle time.\n"
        "Return JSON only with these keys:\n"
        "{"
        '"movement_present": boolean, '
        '"confidence": number, '
        '"summary": string, '
        '"reason": string'
        "}\n"
        "Rules:\n"
        "- Count only the deliberate exercise repetition itself.\n"
        "- Treat setup, walking into position, unracking, bracing, idle preparation, and recovery after the rep as NOT movement.\n"
        "- movement_present should be true only if the athlete is actively performing the exercise rep in this window.\n"
        "- Do not mark movement_present true for preparation alone. If the person is only getting into position, holding, bouncing lightly, making small adjustments, or recovering after the rep, movement_present should be false.\n"
        "- Setup, title cards, explanation slides, still demonstration poses, and between-rep idle moments are not the target unless the rep is actively being performed.\n"
        "- Ignore on-screen instructional text, bullet points, titles, logos, or slide-like layout. If the athlete's body visibly changes pose across the sampled frames because they are performing the rep, that still counts as movement even if text is overlaid on screen.\n"
        "- Only call it a static instructional slide if the sampled frames show essentially the same still image or pose with no real exercise progression across the window.\n"
        "- When unsure between a preparation window and a window containing the actual rep, choose the actual rep window.\n"
        "- For cyclical exercises, prefer windows where one rep is actively being performed rather than rest between reps.\n"
        "- confidence must be between 0 and 1.\n"
        "- Use concise literal descriptions. No markdown. No extra keys."
    )


def parse_detection_payload(raw: str, *, window: DetectionWindow) -> dict[str, object]:
    payload = extract_json_object(raw)
    if payload is None:
        payload = extract_detection_payload_loose(raw)
    if payload is None:
        raise RuntimeError(f"Segment detector returned invalid JSON: {raw[:300]!r}")
    payload = canonicalize_detection_payload(payload)
    movement_present = bool(payload.get("movement_present", False))
    movement_start_seconds = normalize_window_relative_seconds(payload.get("movement_start_seconds"), window=window)
    movement_end_seconds = normalize_window_relative_seconds(payload.get("movement_end_seconds"), window=window)
    confidence = normalize_confidence(payload.get("confidence", 0.0))
    summary = str(payload.get("summary", "")).strip()
    reason = str(payload.get("reason", "")).strip()
    return {
        "movement_present": movement_present,
        "contains_movement_start": False,
        "contains_movement_end": False,
        "movement_start_seconds": movement_start_seconds if movement_present else None,
        "movement_end_seconds": movement_end_seconds if movement_present else None,
        "confidence": confidence,
        "summary": summary,
        "reason": reason,
    }


def canonicalize_detection_payload(payload: dict[str, object]) -> dict[str, object]:
    aliases = {
        "movementstartseconds": "movement_start_seconds",
        "movementendseconds": "movement_end_seconds",
        "containsmovementstart": "contains_movement_start",
        "containsmovementend": "contains_movement_end",
    }
    canonical = dict(payload)
    for key, value in list(payload.items()):
        normalized_key = re.sub(r"[^a-z0-9]+", "", key.lower())
        target_key = aliases.get(normalized_key)
        if target_key:
            canonical[target_key] = value
    return canonical


def extract_json_object(raw: str) -> dict | None:
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def extract_detection_payload_loose(raw: str) -> dict[str, object] | None:
    text = raw.strip()
    if not text:
        return None

    def extract_bool(keys: tuple[str, ...]) -> bool | None:
        for key in keys:
            match = re.search(rf'"{key}"\s*:\s*(true|false)', text, flags=re.IGNORECASE)
            if match:
                return match.group(1).lower() == "true"
        return None

    def extract_number_or_null(keys: tuple[str, ...]) -> float | None | object:
        for key in keys:
            match = re.search(rf'"{key}"\s*:\s*(null|-?\d+(?:\.\d+)?)', text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).lower()
            if value == "null":
                return None
            return float(value)
        return ...

    def extract_string(key: str) -> str | None:
        match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    movement_present = extract_bool(("movement_present",))
    contains_start = extract_bool(("contains_movement_start", "contains_movementstart"))
    contains_end = extract_bool(("contains_movement_end", "contains_movementend"))
    confidence = extract_number_or_null(("confidence",))
    if (
        movement_present is None
        or confidence is ...
    ):
        return None

    summary = extract_string("summary") or ""
    reason = extract_string("reason") or summary

    start_seconds = extract_number_or_null(("movement_start_seconds", "movement_startseconds"))
    end_seconds = extract_number_or_null(("movement_end_seconds", "movement_endseconds"))
    if start_seconds is ... or end_seconds is ...:
        return None

    return {
        "movement_present": movement_present,
        "contains_movement_start": contains_start if contains_start is not None else False,
        "contains_movement_end": contains_end if contains_end is not None else False,
        "movement_start_seconds": start_seconds if movement_present else None,
        "movement_end_seconds": end_seconds if movement_present else None,
        "confidence": confidence,
        "summary": summary,
        "reason": reason,
    }


def normalize_optional_seconds(value: object) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return 0.0
    return seconds


def normalize_window_relative_seconds(value: object, *, window: DetectionWindow) -> float | None:
    seconds = normalize_optional_seconds(value)
    if seconds is None:
        return None
    window_duration = max(0.0, window.end_seconds - window.start_seconds)
    if seconds <= window_duration + 1e-6:
        return min(seconds, window_duration)

    # Some model outputs use global source-video timestamps instead of window-relative ones.
    # If the value sits inside the global window bounds, convert it back to a relative offset.
    if window.start_seconds - 1e-6 <= seconds <= window.end_seconds + 1e-6:
        return min(max(0.0, seconds - window.start_seconds), window_duration)

    return window_duration


def normalize_confidence(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    return max(0.0, min(1.0, score))


def choose_detected_span(
    *,
    detections: list[WindowDetection],
    confidence_threshold: float,
    merge_gap_seconds: float,
) -> DetectedSpan | None:
    del merge_gap_seconds
    positive_indices = [
        index
        for index, item in enumerate(detections)
        if item.movement_present and item.confidence >= confidence_threshold
    ]
    if not positive_indices:
        return None
    clusters = cluster_positive_detections(detections, positive_indices=positive_indices)
    if not clusters:
        return None
    merged = [build_cluster_span(detections, cluster=cluster) for cluster in clusters]
    best = min(
        merged,
        key=lambda item: (
            -len(item.contributing_windows),
            -(item.end_seconds - item.start_seconds),
            -item.confidence,
            item.average_camera_variation,
        ),
    )
    return best


def cluster_has_complete_rep(detections: list[WindowDetection], *, cluster: list[int]) -> bool:
    cluster_detections = [detections[index] for index in cluster]
    has_start = any(
        item.contains_movement_start and item.movement_start_seconds is not None
        for item in cluster_detections
    )
    has_end = any(
        item.contains_movement_end and item.movement_end_seconds is not None
        for item in cluster_detections
    )
    return has_start and has_end


def cluster_positive_detections(
    detections: list[WindowDetection],
    *,
    positive_indices: list[int],
) -> list[list[int]]:
    if not detections or not positive_indices:
        return []
    clusters: list[list[int]] = [[positive_indices[0]]]
    for current_index in positive_indices[1:]:
        previous_index = clusters[-1][-1]
        previous_detection = detections[previous_index]
        current_detection = detections[current_index]
        if (
            current_index == previous_index + 1
            and current_detection.window.start_seconds <= previous_detection.window.end_seconds + 1e-6
        ):
            clusters[-1].append(current_index)
        else:
            clusters.append([current_index])
    return clusters


def build_cluster_span(detections: list[WindowDetection], *, cluster: list[int]) -> DetectedSpan:
    effective_cluster = trim_cluster_to_rep_boundaries(detections, cluster=cluster)
    cluster_detections = [detections[index] for index in effective_cluster]
    first = cluster_detections[0]
    last = cluster_detections[-1]
    start_seconds = first.window.start_seconds
    end_seconds = last.window.end_seconds

    return DetectedSpan(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        confidence=max(item.confidence for item in cluster_detections),
        average_camera_variation=(
            sum(item.camera_variation for item in cluster_detections) / len(cluster_detections)
        ),
        contributing_windows=[item.window.index for item in cluster_detections],
    )


def trim_cluster_to_rep_boundaries(detections: list[WindowDetection], *, cluster: list[int]) -> list[int]:
    start_position = 0
    for position, index in enumerate(cluster):
        if detection_looks_like_preparation(detections[index]):
            start_position = position + 1
            continue
        break
    end_position = len(cluster) - 1
    for reverse_position, index in enumerate(reversed(cluster)):
        if detection_looks_like_recovery(detections[index]):
            end_position = len(cluster) - reverse_position - 2
            continue
        break
    if end_position < start_position:
        return cluster
    return cluster[start_position : end_position + 1]


def detection_looks_like_preparation(detection: WindowDetection) -> bool:
    combined = f"{detection.summary} {detection.reason}".lower()
    return any(
        token in combined
        for token in (
            "setup",
            "preparation",
            "gets into position",
            "get into position",
            "static",
            "still pose",
            "instructional",
            "holding",
            "idle",
            "not started",
        )
    )


def detection_looks_like_recovery(detection: WindowDetection) -> bool:
    combined = f"{detection.summary} {detection.reason}".lower()
    return any(
        token in combined
        for token in (
            "recovery",
            "rest",
            "between reps",
            "between-rep",
            "idle",
            "standing still",
            "finished",
            "after the rep",
        )
    )


def detection_to_interval(
    detection: WindowDetection,
    *,
    confidence_threshold: float,
) -> DetectedSpan | None:
    if not detection.movement_present or detection.confidence < confidence_threshold:
        return None
    relative_start = (
        detection.movement_start_seconds
        if detection.movement_start_seconds is not None
        else 0.0
    )
    relative_end = (
        detection.movement_end_seconds
        if detection.movement_end_seconds is not None
        else detection.window.end_seconds - detection.window.start_seconds
    )
    start_seconds = detection.window.start_seconds + relative_start
    end_seconds = detection.window.start_seconds + relative_end
    if end_seconds < start_seconds:
        end_seconds = start_seconds
    return DetectedSpan(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        confidence=detection.confidence,
        average_camera_variation=detection.camera_variation,
        contributing_windows=[detection.window.index],
    )


def merge_detection_intervals(
    intervals: list[DetectedSpan],
    *,
    merge_gap_seconds: float,
) -> list[DetectedSpan]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: (item.start_seconds, item.end_seconds))
    merged: list[DetectedSpan] = [ordered[0]]
    for current in ordered[1:]:
        previous = merged[-1]
        if current.start_seconds <= previous.end_seconds + merge_gap_seconds:
            merged[-1] = DetectedSpan(
                start_seconds=min(previous.start_seconds, current.start_seconds),
                end_seconds=max(previous.end_seconds, current.end_seconds),
                confidence=max(previous.confidence, current.confidence),
                average_camera_variation=(
                    (
                        previous.average_camera_variation * len(previous.contributing_windows)
                        + current.average_camera_variation * len(current.contributing_windows)
                    )
                    / (len(previous.contributing_windows) + len(current.contributing_windows))
                ),
                contributing_windows=previous.contributing_windows + current.contributing_windows,
            )
        else:
            merged.append(current)
    return merged


def compute_camera_variation(frame_paths: list[Path]) -> float:
    if len(frame_paths) <= 1:
        return 0.0
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python is required for exercise segment detection. Install with: pip install -e .[motion]"
        ) from exc

    grayscale_frames = []
    for frame_path in frame_paths:
        frame = cv2.imread(str(frame_path), cv2.IMREAD_GRAYSCALE)
        if frame is None:
            continue
        frame = cv2.resize(frame, (160, 160), interpolation=cv2.INTER_AREA)
        grayscale_frames.append(frame)
    if len(grayscale_frames) <= 1:
        return 0.0

    deltas = []
    for previous, current in zip(grayscale_frames, grayscale_frames[1:]):
        difference = cv2.absdiff(previous, current)
        deltas.append(float(difference.mean()) / 255.0)
    return sum(deltas) / len(deltas)
