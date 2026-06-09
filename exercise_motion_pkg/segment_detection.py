from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from exercise_motion_pkg.video_utils import read_basic_video_metadata


@dataclass(frozen=True)
class DetectionSettings:
    base_url: str = "http://127.0.0.1:8090"
    model: str = "local-vision"
    litert_command: str | None = None
    litert_backend: str = "gpu"
    llama_cpp_command: str | None = None
    llama_cpp_model: str | None = None
    llama_cpp_mmproj: str | None = None
    llama_cpp_backend: str = "gpu"
    llama_cpp_n_predict: int = 768
    llama_cpp_image_min_tokens: int | None = None
    llama_cpp_image_max_tokens: int | None = None
    window_seconds: float = 4.0
    overlap_seconds: float = 2.0
    frames_per_window: int = 6
    max_frame_width: int = 960
    merge_gap_seconds: float = 2.0
    confidence_threshold: float = 0.45
    min_segment_seconds: float = 2.0
    max_segment_seconds: float = 20.0
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
    executions: tuple["CandidateExecution", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CandidateExecution:
    start_seconds: float
    end_seconds: float
    complete: bool
    single_execution: bool
    contains_multiple_executions: bool
    contains_idle_or_reset: bool
    confidence: float
    quality: float = 0.0
    reason: str = ""
    source_window_index: int | None = None
    is_model_candidate: bool = True


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
    if settings.llama_cpp_command:
        if not settings.llama_cpp_model:
            raise ValueError("llama-cpp command mode requires --llama-cpp-model.")
        if not settings.llama_cpp_mmproj:
            raise ValueError("llama-cpp command mode requires --llama-cpp-mmproj.")
        client = LlamaCppVisionClient(
            base_url=None,
            model=settings.llama_cpp_model,
            command=settings.llama_cpp_command,
            mmproj=settings.llama_cpp_mmproj,
            backend=settings.llama_cpp_backend,
            n_predict=settings.llama_cpp_n_predict,
            image_min_tokens=settings.llama_cpp_image_min_tokens,
            image_max_tokens=settings.llama_cpp_image_max_tokens,
        )
    elif settings.litert_command:
        client = LiteRtCliVisionClient(
            command=settings.litert_command,
            model=settings.model,
            backend=settings.litert_backend,
        )
    else:
        client = LlamaCppVisionClient(
            settings.base_url,
            settings.model,
            n_predict=settings.llama_cpp_n_predict,
            image_min_tokens=settings.llama_cpp_image_min_tokens,
            image_max_tokens=settings.llama_cpp_image_max_tokens,
        )
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
        min_segment_seconds=settings.min_segment_seconds,
        max_segment_seconds=settings.max_segment_seconds,
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
    def __init__(
        self,
        base_url: str | None,
        model: str,
        *,
        command: str | None = None,
        mmproj: str | None = None,
        backend: str = "gpu",
        n_predict: int = 768,
        image_min_tokens: int | None = None,
        image_max_tokens: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url is not None else None
        self.model = model
        self.command = command
        self.mmproj = mmproj
        self.backend = backend
        self.n_predict = max(1, n_predict)
        self.image_min_tokens = image_min_tokens
        self.image_max_tokens = image_max_tokens
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
            executions=payload["executions"],
            frame_paths=[str(path) for path in frame_paths],
        )

    def caption_images(self, *, frame_paths: list[Path], prompt: str) -> str:
        if self.command is not None:
            return self._caption_images_via_cli(frame_paths=frame_paths, prompt=prompt)
        if self.base_url is None:
            raise RuntimeError("llama-cpp vision mode requires either a command path or base URL.")
        return self._caption_images_via_server(frame_paths=frame_paths, prompt=prompt)

    def _caption_images_via_cli(self, *, frame_paths: list[Path], prompt: str) -> str:
        command = [
            self.command,
            "-m",
            self.model,
        ]
        if self.mmproj:
            command.extend(["--mmproj", self.mmproj])
        command.extend(
            [
                "--prompt",
                prompt,
                "--temp",
                "0.2",
                "--n-predict",
                str(self.n_predict),
                "--json-schema",
                "{}",
            ]
        )
        if self.image_min_tokens is not None:
            command.extend(["--image-min-tokens", str(self.image_min_tokens)])
        if self.image_max_tokens is not None:
            command.extend(["--image-max-tokens", str(self.image_max_tokens)])
        if self.backend == "gpu":
            command.extend(["--gpu-layers", "all"])
        else:
            command.extend(["--gpu-layers", "0"])
        command.extend(["--image", ",".join(str(frame_path) for frame_path in frame_paths)])
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"llama-mtmd-cli failed with exit code {result.returncode}. "
                f"Command: {' '.join(command)}.\n"
                f"llama output:\n{message}"
            )
        return result.stdout.strip()

    def _caption_images_via_server(self, *, frame_paths: list[Path], prompt: str) -> str:
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
            "max_tokens": self.n_predict,
            "response_format": {"type": "json_object"},
        }
        if self.model == "local-vision":
            payload["reasoning_format"] = "none"
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if self.base_url is None:
            raise RuntimeError("llama-cpp server mode requires base URL.")
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
            executions=payload["executions"],
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


def build_window_prompt(
    *,
    exercise_name: str | None,
    start_seconds: float,
    end_seconds: float,
) -> str:
    exercise_clause = (
        f"Optional movement label: {exercise_name}.\n"
        if exercise_name and exercise_name.strip()
        else ""
    )
    exercise_value = exercise_name.strip() if exercise_name and exercise_name.strip() else "unknown"
    return (
        "You are classifying a short chunk from an exercise video.\n"
        "Goal: decide whether this window contains at least one complete target movement execution.\n"
        f"Window time range in source video: {start_seconds:.2f}s to {end_seconds:.2f}s.\n"
        f"{exercise_clause}"
        "Primary task:\n"
        "- Prefer classification. Decide if this is a full execution, not an estimate of exact boundaries.\n"
        "- movement_present is true only when the full execution is visibly complete in this window.\n"
        "- If there are only setup, recovery, or fragmentary frames, movement_present is false.\n"
        "Definitions:\n"
        "- setup: getting ready, walking, positioning, bracing, or idle before the movement.\n"
        "- movement: actively performing the target exercise movement.\n"
        "- finish: the execution reaches a stable end position.\n"
        "- recovery: after the execution, lowering, walking away, resetting, or idle.\n"
        "- idle: no meaningful exercise action.\n"
        "- unclear: not enough visual evidence.\n"
        "Rules:\n"
        "- Use only the visible frames.\n"
        "- If frames are packed into strips, read each strip left-to-right, and read strips in attachment order.\n"
        "- read them in frame-number order, left-to-right within each row and then top-to-bottom across rows.\n"
        "- Ignore instructional text, logos, title cards, and still demonstration poses unless movement is visible.\n"
        "- Output valid JSON only. No prose outside JSON.\n"
        "- movement_start_seconds and movement_end_seconds are coarse timing hints only (window-local seconds).\n"
        "- Use hints only to mark likely movement boundaries; do not be precise.\n"
        "- execution candidates, if provided, are optional and are hints, not hard boundaries.\n"
        "- quality and confidence must be between 0 and 1.\n"
        "Return this JSON schema exactly:\n"
        "{"
        f'"exercise": "{exercise_value}", '
        '"phase": "setup|movement|finish|recovery|idle|unclear", '
        '"movement_present": true, '
        '"contains_movement_start": true, '
        '"contains_movement_end": true, '
        '"movement_start_seconds": number|null, '
        '"movement_end_seconds": number|null, '
        '"confidence": 0.0, '
        '"reason": "short visual reason", '
        '"summary": "short summary", '
        '"executions": ['
        "{"
        '"start_seconds": 0.0, '
        '"end_seconds": 0.0, '
        '"complete": true, '
        '"single_execution": true, '
        '"contains_multiple_executions": false, '
        '"contains_idle_or_reset": false, '
        '"quality": 0.0, '
        '"confidence": 0.0, '
        '"start_reason": "short visual reason", '
        '"end_reason": "short visual reason"'
        "}]"
        "}\n"
    )


def parse_detection_payload(raw: str, *, window: DetectionWindow) -> dict[str, object]:
    payload = extract_json_object(raw)
    if payload is None:
        payload = extract_detection_payload_loose(raw)
    if payload is None:
        raise RuntimeError(f"Segment detector returned invalid JSON: {raw[:300]!r}")
    payload = canonicalize_detection_payload(payload)
    has_executions_field = "executions" in payload
    movement_present = bool(payload.get("movement_present", False))
    movement_start_seconds = normalize_window_relative_seconds(payload.get("movement_start_seconds"), window=window)
    movement_end_seconds = normalize_window_relative_seconds(payload.get("movement_end_seconds"), window=window)
    confidence = normalize_confidence(payload.get("confidence", 0.0))
    summary = str(payload.get("summary", "")).strip()
    reason = str(payload.get("reason", "")).strip()
    raw_executions = payload.get("executions")
    model_executions = parse_execution_payloads(raw_executions, window=window)
    if not model_executions and movement_present and not has_executions_field:
        model_executions = (
            CandidateExecution(
                start_seconds=(
                    window.start_seconds
                    if movement_start_seconds is None
                    else window.start_seconds + movement_start_seconds
                ),
                end_seconds=(
                    window.end_seconds
                    if movement_end_seconds is None
                    else window.start_seconds + movement_end_seconds
                ),
                complete=movement_start_seconds is not None and movement_end_seconds is not None,
                single_execution=movement_start_seconds is not None and movement_end_seconds is not None,
                contains_multiple_executions=False,
                contains_idle_or_reset=False,
                confidence=confidence,
                quality=0.0,
                reason=reason,
                source_window_index=window.index,
                is_model_candidate=False,
            ),
        )
    return {
        "movement_present": movement_present,
        "contains_movement_start": bool(payload.get("contains_movement_start", movement_start_seconds is not None)),
        "contains_movement_end": bool(payload.get("contains_movement_end", movement_end_seconds is not None)),
        "movement_start_seconds": movement_start_seconds if movement_present else None,
        "movement_end_seconds": movement_end_seconds if movement_present else None,
        "confidence": confidence,
        "summary": summary,
        "reason": reason,
        "executions": model_executions,
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


def canonicalize_execution_payload(payload: dict[str, object]) -> dict[str, object]:
    aliases = {
        "startseconds": "start_seconds",
        "endseconds": "end_seconds",
        "containsmultipleexecutions": "contains_multiple_executions",
        "containsidleorreset": "contains_idle_or_reset",
        "singleexecution": "single_execution",
    }
    canonical = dict(payload)
    for key, value in list(payload.items()):
        normalized_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
        target_key = aliases.get(normalized_key)
        if target_key:
            canonical[target_key] = value
    return canonical


def normalize_execution_timestamp(value: object, *, window: DetectionWindow) -> float | None:
    seconds = normalize_optional_seconds(value)
    if seconds is None:
        return None
    window_duration = max(0.0, window.end_seconds - window.start_seconds)
    if window.start_seconds - 1e-6 <= seconds <= window.end_seconds + 1e-6:
        if seconds <= window_duration + 1e-6:
            return window.start_seconds + seconds
        return seconds
    return None


def parse_execution_payloads(
    payload: object,
    *,
    window: DetectionWindow,
) -> tuple[CandidateExecution, ...]:
    if not isinstance(payload, list):
        return ()
    parsed: list[CandidateExecution] = []
    for raw_item in payload:
        if not isinstance(raw_item, dict):
            continue
        item = canonicalize_execution_payload(raw_item)
        start_seconds = normalize_execution_timestamp(item.get("start_seconds"), window=window)
        end_seconds = normalize_execution_timestamp(item.get("end_seconds"), window=window)
        if start_seconds is None or end_seconds is None:
            continue
        if end_seconds <= start_seconds:
            continue
        parsed.append(
            CandidateExecution(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                complete=bool(item.get("complete", False)),
                single_execution=bool(item.get("single_execution", False)),
                contains_multiple_executions=bool(item.get("contains_multiple_executions", False)),
                contains_idle_or_reset=bool(item.get("contains_idle_or_reset", False)),
                confidence=normalize_confidence(item.get("confidence", None)),
                quality=normalize_confidence(item.get("quality", 0.0)),
                reason=str(item.get("reason", "")).strip(),
                source_window_index=int(item.get("source_window_index", window.index)),
                is_model_candidate=False,
            )
        )
    return tuple(parsed)


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
            match = re.search(rf'"{key}"\s*:\s*(null|-?\d+(?:\.\d+)*)', text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).lower()
            if value == "null":
                return None
            if value.count(".") > 1:
                head, *tail = value.split(".")
                value = f"{head}.{''.join(tail)}"
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

    return {
        "movement_present": movement_present,
        "contains_movement_start": contains_start if contains_start is not None else False,
        "contains_movement_end": contains_end if contains_end is not None else False,
        "movement_start_seconds": start_seconds if movement_present and start_seconds is not ... else None,
        "movement_end_seconds": end_seconds if movement_present and end_seconds is not ... else None,
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
    min_segment_seconds: float = 2.0,
    max_segment_seconds: float = 20.0,
) -> DetectedSpan | None:
    min_segment_seconds = max(0.0, min_segment_seconds)
    max_segment_seconds = max(min_segment_seconds, max_segment_seconds)
    positive_indices = [
        index
        for index, item in enumerate(detections)
        if item.movement_present and item.confidence >= confidence_threshold
    ]
    if not positive_indices:
        return None

    interval_candidates = []
    for index in positive_indices:
        detection_window_interval = detection_to_interval(
            detections[index],
            confidence_threshold=confidence_threshold,
        )
        if detection_window_interval is not None:
            interval_candidates.append(
                _apply_boundary_hints_to_interval(
                    interval=detection_window_interval,
                    detection=detections[index],
                )
            )
    interval_candidates = [
        interval
        for interval in interval_candidates
        if _span_has_reasonable_length(
            interval,
            min_segment_seconds=min_segment_seconds,
            max_segment_seconds=max_segment_seconds,
        )
    ]
    if interval_candidates:
        merged_intervals = merge_detection_intervals(
            interval_candidates,
            merge_gap_seconds=merge_gap_seconds,
        )
        merged_intervals = [
            interval
            for interval in merged_intervals
            if _span_has_reasonable_length(
                interval,
                min_segment_seconds=min_segment_seconds,
                max_segment_seconds=max_segment_seconds,
            )
        ]
        if merged_intervals:
            return _select_best_single_execution_span(merged_intervals)

    interval_candidates = [
        interval
        for interval in _collect_cluster_boundaries_as_intervals(
            detections=detections,
            positive_indices=positive_indices,
            min_segment_seconds=min_segment_seconds,
            max_segment_seconds=max_segment_seconds,
        )
        if interval is not None
    ]
    if interval_candidates:
        return _select_best_single_execution_span(interval_candidates)

    clusters = cluster_positive_detections(detections, positive_indices=positive_indices)
    if not clusters:
        return None
    merged = [
        _collect_best_cluster_span(detections, cluster=cluster)
        for cluster in clusters
    ]
    merged = [
        item
        for item in merged
        if _span_has_reasonable_length(
            item,
            min_segment_seconds=min_segment_seconds,
            max_segment_seconds=max_segment_seconds,
        )
    ]
    if not merged:
        return None
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


def _apply_boundary_hints_to_interval(
    *,
    interval: DetectedSpan,
    detection: WindowDetection,
) -> DetectedSpan:
    if detection.movement_start_seconds is None and detection.movement_end_seconds is None:
        return interval
    hint_start = (
        detection.window.start_seconds + detection.movement_start_seconds
        if detection.movement_start_seconds is not None
        else interval.start_seconds
    )
    hint_end = (
        detection.window.start_seconds + detection.movement_end_seconds
        if detection.movement_end_seconds is not None and detection.movement_end_seconds >= 0.0
        else interval.end_seconds
    )
    hint_start = max(interval.start_seconds, min(hint_start, interval.end_seconds))
    hint_end = max(hint_start, min(hint_end, interval.end_seconds))
    return DetectedSpan(
        start_seconds=hint_start,
        end_seconds=hint_end,
        confidence=interval.confidence,
        average_camera_variation=interval.average_camera_variation,
        contributing_windows=list(interval.contributing_windows),
    )


def _collect_cluster_boundaries_as_intervals(
    *,
    detections: list[WindowDetection],
    positive_indices: list[int],
    min_segment_seconds: float,
    max_segment_seconds: float,
) -> list[DetectedSpan]:
    clusters = cluster_positive_detections(detections, positive_indices=positive_indices)
    if not clusters:
        return []
    interval_candidates: list[DetectedSpan] = []
    for cluster in clusters:
        cluster_intervals = _collect_cluster_boundary_candidates(
            detections=detections,
            cluster=cluster,
            min_segment_seconds=min_segment_seconds,
            max_segment_seconds=max_segment_seconds,
        )
        interval_candidates.extend(cluster_intervals)
    return interval_candidates


def _collect_cluster_boundary_candidates(
    *,
    detections: list[WindowDetection],
    cluster: list[int],
    min_segment_seconds: float,
    max_segment_seconds: float,
) -> list[DetectedSpan]:
    effective_cluster = trim_cluster_to_rep_boundaries(detections, cluster=cluster)
    if not effective_cluster:
        return []
    start_candidates = [
        index
        for index in effective_cluster
        if detections[index].contains_movement_start
        or detections[index].movement_start_seconds is not None
    ]
    end_candidates = [
        index
        for index in effective_cluster
        if detections[index].contains_movement_end
        or detections[index].movement_end_seconds is not None
    ]
    intervals: list[DetectedSpan] = []
    if start_candidates and end_candidates:
        for start_index in start_candidates:
            for end_index in end_candidates:
                if end_index < start_index:
                    continue
                span_indices = [index for index in effective_cluster if start_index <= index <= end_index]
                if not span_indices:
                    continue
                interval = _build_cluster_span_with_optional_hints(
                    detections=detections,
                    cluster=span_indices,
                )
                if interval is None or not _span_has_reasonable_length(
                    interval,
                    min_segment_seconds=min_segment_seconds,
                    max_segment_seconds=max_segment_seconds,
                ):
                    continue
                intervals.append(interval)
    return intervals


def _build_cluster_span_with_optional_hints(
    *,
    detections: list[WindowDetection],
    cluster: list[int],
) -> DetectedSpan | None:
    cluster_detections = [detections[index] for index in cluster]
    first = cluster_detections[0]
    last = cluster_detections[-1]
    start_seconds = first.window.start_seconds
    end_seconds = last.window.end_seconds
    if end_seconds <= start_seconds:
        return None
    return DetectedSpan(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        confidence=max(item.confidence for item in cluster_detections),
        average_camera_variation=(
            sum(item.camera_variation for item in cluster_detections) / len(cluster_detections)
        ),
        contributing_windows=[item.window.index for item in cluster_detections],
    )


def _collect_best_cluster_span(
    detections: list[WindowDetection],
    *,
    cluster: list[int],
) -> DetectedSpan:
    interval = _build_cluster_span_with_optional_hints(detections=detections, cluster=cluster)
    if interval is not None:
        return interval
    return build_cluster_span(detections=detections, cluster=cluster)


def _model_execution_candidates_present(detections: list[WindowDetection]) -> bool:
    return any(any(item.is_model_candidate for item in detection.executions) for detection in detections)


def _collect_model_execution_candidates(
    *,
    detections: list[WindowDetection],
    confidence_threshold: float,
    min_segment_seconds: float,
    max_segment_seconds: float,
) -> list[DetectedSpan]:
    candidates: list[DetectedSpan] = []
    for detection in detections:
        for execution in detection.executions:
            if not execution.is_model_candidate:
                continue
            if not execution.single_execution or not execution.complete:
                continue
            if execution.contains_multiple_executions or execution.contains_idle_or_reset:
                continue
            if execution.confidence < confidence_threshold:
                continue
            start_seconds = execution.start_seconds
            end_seconds = execution.end_seconds
            if end_seconds <= start_seconds:
                continue
            duration = end_seconds - start_seconds
            if not (min_segment_seconds <= duration <= max_segment_seconds):
                continue
            candidates.append(
                DetectedSpan(
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    confidence=max(execution.confidence, detection.confidence),
                    average_camera_variation=detection.camera_variation,
                    contributing_windows=[detection.window.index],
                )
            )
    return candidates


def _span_has_reasonable_length(
    span: DetectedSpan,
    *,
    min_segment_seconds: float,
    max_segment_seconds: float,
) -> bool:
    duration = span.end_seconds - span.start_seconds
    return min_segment_seconds <= duration <= max_segment_seconds


def _select_best_single_execution_span(candidates: list[DetectedSpan]) -> DetectedSpan:
    # Prefer the shortest plausible execution first so multi-attempt coverage does not
    # outrank a single complete movement when it fits the same quality threshold.
    return min(
        candidates,
        key=lambda item: (
            item.end_seconds - item.start_seconds,
            -item.confidence,
            item.average_camera_variation,
            item.contributing_windows[:1],
        ),
    )


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
    if detection.movement_start_seconds is None or detection.movement_end_seconds is None:
        return None
    start_seconds = detection.window.start_seconds + detection.movement_start_seconds
    relative_end = detection.movement_end_seconds
    if relative_end < detection.movement_start_seconds:
        return None
    end_seconds = detection.window.start_seconds + relative_end
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

