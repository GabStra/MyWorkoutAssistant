from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import shutil
import time
from typing import Any, Iterable
from urllib.request import urlretrieve

from exercise_motion_pkg.video_utils import BasicVideoMetadata, read_basic_video_metadata


POSE_MODEL_CACHE_DIR = Path.home() / ".cache" / "myworkoutassistant" / "pose_models"
KNOWN_ULTRALYTICS_POSE_MODELS = {
    "yolo11s-pose.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s-pose.pt",
    "yolo26x-pose.pt": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26x-pose.pt",
}

COCO_KEYPOINT_NAMES = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)
REQUIRED_JOINTS = (
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)
SIDE_CHAINS = {
    "left_arm": ("left_shoulder", "left_elbow", "left_wrist"),
    "right_arm": ("right_shoulder", "right_elbow", "right_wrist"),
    "left_leg": ("left_hip", "left_knee", "left_ankle"),
    "right_leg": ("right_hip", "right_knee", "right_ankle"),
}
JOINT_CHAIN_BY_NAME = {
    joint: chain_name
    for chain_name, chain_joints in SIDE_CHAINS.items()
    for joint in chain_joints
}
FRONTAL_VIEW_SHOULDER_WIDTH_LOW = 0.14
FRONTAL_VIEW_SHOULDER_WIDTH_HIGH = 0.22
FRONTAL_VIEW_HIP_WIDTH_LOW = 0.08
FRONTAL_VIEW_HIP_WIDTH_HIGH = 0.15
FRONTAL_VIEW_QUALITY_ISSUE_THRESHOLD = 0.55
CLEAR_VALID_CHUNK_MIN_SCORE = 0.68
DEFAULT_YOLO_BATCH_SIZE = 16


class YoloDeviceUnavailableError(RuntimeError):
    """Raised when YOLO is configured for GPU execution but CUDA is unavailable."""


@dataclass(frozen=True)
class PosePrefilterSettings:
    model: str = "yolo26x-pose.pt"
    sample_fps: float = 0.0
    max_seconds: float = 0.0
    scan_strategy: str = "full"
    window_seconds: float = 8.0
    overlap_seconds: float = 4.0
    min_score: float = 0.45
    min_keypoint_confidence: float = 0.35
    min_body_scale: float = 0.18
    max_candidates: int = 8
    batch_size: int = DEFAULT_YOLO_BATCH_SIZE
    device: str | None = "cuda"


@dataclass(frozen=True)
class PoseDetection:
    keypoints: dict[str, tuple[float, float, float]]
    bbox: tuple[float, float, float, float]
    confidence: float = 1.0


@dataclass(frozen=True)
class PoseSample:
    time_seconds: float
    detections: list[PoseDetection]
    frame_signature: tuple[float, ...] | None = None


@dataclass(frozen=True)
class PosePrefilterResult:
    passed: bool
    score: float
    reasons: list[str]
    payload: dict[str, Any]


def run_yolo_pose_prefilter(
    *,
    video_path: Path,
    settings: PosePrefilterSettings,
) -> PosePrefilterResult:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python is required for YOLO pose prefiltering. Install with: pip install -e .[motion]"
        ) from exc
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "ultralytics is required for YOLO pose prefiltering. Install with: pip install -e .[motion]"
        ) from exc

    metadata = read_basic_video_metadata(video_path)
    if metadata.fps <= 0 or metadata.frame_count <= 0:
        return empty_pose_prefilter_result("pose_prefilter_no_video_metadata")
    model_path = resolve_pose_model_path(settings.model)
    model = YOLO(model_path)
    device = resolve_yolo_device(settings.device)
    samples: list[PoseSample] = []
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video for YOLO pose prefiltering: {video_path}")
    try:
        sample_frames, sampled_windows = build_pose_sample_plan(metadata, settings=settings)
        batch_indices: list[int] = []
        batch_frames: list[Any] = []
        for frame_index, frame in iter_sampled_video_frames(capture, sample_frames):
            batch_indices.append(frame_index)
            batch_frames.append(frame)
            if len(batch_frames) >= max(1, settings.batch_size):
                samples.extend(
                    pose_samples_from_yolo_batch(
                        model,
                        frame_indices=batch_indices,
                        frames=batch_frames,
                        metadata=metadata,
                        min_keypoint_confidence=settings.min_keypoint_confidence,
                        device=device,
                    )
                )
                batch_indices = []
                batch_frames = []
        if batch_frames:
            samples.extend(
                pose_samples_from_yolo_batch(
                    model,
                    frame_indices=batch_indices,
                    frames=batch_frames,
                    metadata=metadata,
                    min_keypoint_confidence=settings.min_keypoint_confidence,
                    device=device,
                )
            )
    finally:
        capture.release()
    result = score_pose_samples(samples, metadata=metadata, settings=settings)
    payload = dict(result.payload)
    payload["resolvedModelPath"] = model_path
    payload["scanStrategy"] = normalize_pose_scan_strategy(settings.scan_strategy)
    payload["sampledFrameCount"] = len(samples)
    payload["sampledWindows"] = sampled_windows
    payload["sampledWindowCount"] = len(sampled_windows)
    payload["device"] = device or "auto"
    payload["batchSize"] = settings.batch_size
    return PosePrefilterResult(
        passed=result.passed,
        score=result.score,
        reasons=result.reasons,
        payload=payload,
    )


def resolve_yolo_device(configured_device: str | None) -> str | None:
    if configured_device is not None and str(configured_device).strip():
        device = str(configured_device).strip()
        if device.lower() in {"cuda", "gpu", "0"} and not torch_cuda_available():
            raise YoloDeviceUnavailableError(
                "YOLO pose prefilter is configured for CUDA, but the selected Python environment "
                "has CPU-only Torch or cannot see the NVIDIA GPU. Use a CUDA Torch Python, or pass "
                "--pose-prefilter-device cpu only for an explicit slow debug run."
            )
        return "0" if device.lower() in {"cuda", "gpu"} else device
    if torch_cuda_available():
        return "0"
    raise YoloDeviceUnavailableError(
        "YOLO pose prefilter requires a CUDA-capable Torch environment by default. "
        "The selected Python environment cannot see CUDA. Use a CUDA Torch Python, or pass "
        "--pose-prefilter-device cpu only for an explicit slow debug run."
    )


def torch_cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def iter_sampled_video_frames(
    capture: Any,
    sample_frames: list[int],
) -> Iterable[tuple[int, Any]]:
    sorted_frames = sorted({int(frame) for frame in sample_frames if int(frame) >= 0})
    if not sorted_frames:
        return
    current_frame = sorted_frames[0]
    capture.set(1, current_frame)
    for target_frame in sorted_frames:
        if target_frame < current_frame:
            capture.set(1, target_frame)
            current_frame = target_frame
        while current_frame < target_frame:
            ok, _ = capture.read()
            if not ok:
                return
            current_frame += 1
        ok, frame = capture.read()
        if not ok:
            return
        yield target_frame, frame
        current_frame = target_frame + 1


def pose_samples_from_yolo_batch(
    model: Any,
    *,
    frame_indices: list[int],
    frames: list[Any],
    metadata: BasicVideoMetadata,
    min_keypoint_confidence: float,
    device: str | None,
) -> list[PoseSample]:
    predict_kwargs: dict[str, Any] = {"verbose": False}
    if device:
        predict_kwargs["device"] = device
    results = model(frames, **predict_kwargs)
    result_list = results if isinstance(results, list) else [results]
    samples: list[PoseSample] = []
    for frame_index, frame, result in zip(frame_indices, frames, result_list):
        detections = detections_from_yolo_result(
            result,
            metadata=metadata,
            min_keypoint_confidence=min_keypoint_confidence,
        )
        samples.append(
            PoseSample(
                time_seconds=frame_index / metadata.fps,
                detections=detections,
                frame_signature=compute_frame_signature(frame),
            )
        )
    return samples


def detections_from_yolo_result(
    result_value: Any,
    *,
    metadata: BasicVideoMetadata,
    min_keypoint_confidence: float,
) -> list[PoseDetection]:
    result = result_value[0] if isinstance(result_value, list) and result_value else result_value
    keypoints_obj = getattr(result, "keypoints", None)
    if keypoints_obj is None:
        return []
    xy_value = getattr(keypoints_obj, "xy", None)
    conf_value = getattr(keypoints_obj, "conf", None)
    boxes_obj = getattr(result, "boxes", None)
    boxes_xyxy = getattr(boxes_obj, "xyxy", None) if boxes_obj is not None else None
    boxes_conf = getattr(boxes_obj, "conf", None) if boxes_obj is not None else None
    xy = tensor_like_to_list(xy_value)
    conf = tensor_like_to_list(conf_value)
    boxes = tensor_like_to_list(boxes_xyxy)
    box_conf = tensor_like_to_list(boxes_conf)
    detections: list[PoseDetection] = []
    if not isinstance(xy, list):
        return detections
    for person_index, person_points in enumerate(xy):
        if not isinstance(person_points, list):
            continue
        person_conf = conf[person_index] if isinstance(conf, list) and person_index < len(conf) else []
        keypoints: dict[str, tuple[float, float, float]] = {}
        for index, name in enumerate(COCO_KEYPOINT_NAMES):
            if index >= len(person_points) or not isinstance(person_points[index], list) or len(person_points[index]) < 2:
                continue
            confidence = (
                float(person_conf[index])
                if isinstance(person_conf, list) and index < len(person_conf) and isinstance(person_conf[index], (int, float))
                else 1.0
            )
            if confidence < min_keypoint_confidence:
                continue
            keypoints[name] = (float(person_points[index][0]), float(person_points[index][1]), confidence)
        if not keypoints:
            continue
        bbox = bbox_from_keypoints(keypoints)
        if isinstance(boxes, list) and person_index < len(boxes) and isinstance(boxes[person_index], list) and len(boxes[person_index]) >= 4:
            bbox = (
                float(boxes[person_index][0]),
                float(boxes[person_index][1]),
                float(boxes[person_index][2]),
                float(boxes[person_index][3]),
            )
        confidence = (
            float(box_conf[person_index])
            if isinstance(box_conf, list) and person_index < len(box_conf) and isinstance(box_conf[person_index], (int, float))
            else average_keypoint_confidence(keypoints)
        )
        detections.append(PoseDetection(keypoints=keypoints, bbox=clamp_bbox(bbox, metadata), confidence=confidence))
    return detections


def tensor_like_to_list(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def score_pose_samples(
    samples: list[PoseSample],
    *,
    metadata: BasicVideoMetadata,
    settings: PosePrefilterSettings,
) -> PosePrefilterResult:
    if not samples:
        return empty_pose_prefilter_result("pose_prefilter_no_samples")
    windows = build_pose_windows(samples, settings=settings)
    scored = []
    for window_index, window in enumerate(windows):
        item = score_pose_window(window, metadata=metadata, settings=settings)
        item["windowIndex"] = window_index
        scored.append(item)
    scored = [item for item in scored if item["sampleCount"] > 0]
    if not scored:
        return empty_pose_prefilter_result("pose_prefilter_no_windows")
    eligible = [
        item
        for item in scored
        if float(item["score"]) >= settings.min_score and not item.get("blockingIssues")
    ]
    best = max(eligible or scored, key=lambda item: float(item["score"]))
    valid_chunk_score_threshold = max(settings.min_score, CLEAR_VALID_CHUNK_MIN_SCORE)
    valid_chunks = pose_valid_chunks_from_scored_windows(
        scored,
        min_score=valid_chunk_score_threshold,
        max_chunks=settings.max_candidates,
    )
    score = float(best["score"])
    blocking_issues = list(best.get("blockingIssues", []))
    quality_issues = list(best.get("qualityIssues", []))
    scan_strategy = normalize_pose_scan_strategy(settings.scan_strategy)
    timeline_integrity = source_window_integrity_metrics(
        [select_dominant_detection(sample, metadata=metadata) for sample in samples],
        samples=samples,
        metadata=metadata,
    )
    blocking_issues = dedupe_text(blocking_issues)
    quality_issues = dedupe_text(quality_issues)
    passed = score >= settings.min_score and not blocking_issues
    reasons = [f"pose_{issue}" for issue in [*blocking_issues, *quality_issues]] or list(best.get("reasons", []))
    reasons.append("pose_prefilter_passed" if passed else "pose_prefilter_below_threshold")
    payload = {
        "enabled": True,
        "passed": passed,
        "score": score,
        "bestChunkStartSeconds": best["startSeconds"],
        "bestChunkEndSeconds": best["endSeconds"],
        "validChunks": valid_chunks,
        "validChunkCount": len(valid_chunks),
        "validChunkScoreThreshold": valid_chunk_score_threshold,
        "blockingIssues": blocking_issues,
        "qualityIssues": quality_issues,
        "singlePersonRatio": best["singlePersonRatio"],
        "multiPersonRatio": best["multiPersonRatio"],
        "noPersonRatio": best["noPersonRatio"],
        "maxSignificantPersonCount": best["maxSignificantPersonCount"],
        "keypointCoverage": best["keypointCoverage"],
        "wholeMovementJointVisibility": best["wholeMovementJointVisibility"],
        "requiredJointAverageCoverage": best["requiredJointAverageCoverage"],
        "requiredJointMinCoverage": best["requiredJointMinCoverage"],
        "requiredJointP10Coverage": best["requiredJointP10Coverage"],
        "allRequiredJointsVisibleRatio": best["allRequiredJointsVisibleRatio"],
        "minRequiredJointsVisible": best["minRequiredJointsVisible"],
        "p10RequiredJointsVisible": best["p10RequiredJointsVisible"],
        "bodyScaleRatio": best["bodyScaleRatio"],
        "cropSafety": best["cropSafety"],
        "cameraStability": best["cameraStability"],
        "motionStrength": best["motionStrength"],
        "activeJointVisibility": best["activeJointVisibility"],
        "activeChainVisibility": best["activeChainVisibility"],
        "bilateralActiveChainBalance": best["bilateralActiveChainBalance"],
        "reconstructionViewQuality": best["reconstructionViewQuality"],
        "frontalOrBackViewEvidence": best["frontalOrBackViewEvidence"],
        "shoulderWidthBodyRatio": best["shoulderWidthBodyRatio"],
        "hipWidthBodyRatio": best["hipWidthBodyRatio"],
        "viewQualitySampleCount": best["viewQualitySampleCount"],
        "activeJoints": best["activeJoints"],
        "activeChains": best["activeChains"],
        "sourceWindowIntegrity": best["sourceWindowIntegrity"],
        "timelineSourceIntegrity": timeline_integrity,
        "timelineIntegrityRequired": False,
        "sourceWindowIntegrityRequired": True,
        "sampleCount": best["sampleCount"],
        "timelineSampleCount": len(samples),
        "windowCount": len(scored),
        "model": settings.model,
        "sampleFps": settings.sample_fps,
        "maxSeconds": settings.max_seconds,
        "minScore": settings.min_score,
        "scanStrategy": scan_strategy,
    }
    return PosePrefilterResult(passed=passed, score=score, reasons=dedupe_text(reasons), payload=payload)


def pose_valid_chunks_from_scored_windows(
    scored_windows: list[dict[str, Any]],
    *,
    min_score: float,
    max_chunks: int,
) -> list[dict[str, Any]]:
    valid = [
        window
        for window in scored_windows
        if float(window.get("score", 0.0)) >= min_score and not window.get("blockingIssues")
    ]
    valid.sort(
        key=lambda item: (
            float(item.get("score", 0.0)),
            float(item.get("wholeMovementJointVisibility", 0.0)),
            float(item.get("allRequiredJointsVisibleRatio", 0.0)),
        ),
        reverse=True,
    )
    chunks: list[dict[str, Any]] = []
    for window in valid[: max(0, max_chunks)]:
        chunks.append(
            {
                "index": int(window.get("windowIndex", len(chunks))),
                "startSeconds": float(window["startSeconds"]),
                "endSeconds": float(window["endSeconds"]),
                "score": float(window["score"]),
                "sampleCount": int(window.get("sampleCount", 0)),
                "wholeMovementJointVisibility": float(window.get("wholeMovementJointVisibility", 0.0)),
                "requiredJointAverageCoverage": float(window.get("requiredJointAverageCoverage", 0.0)),
                "requiredJointMinCoverage": float(window.get("requiredJointMinCoverage", 0.0)),
                "requiredJointP10Coverage": float(window.get("requiredJointP10Coverage", 0.0)),
                "allRequiredJointsVisibleRatio": float(window.get("allRequiredJointsVisibleRatio", 0.0)),
                "minRequiredJointsVisible": int(window.get("minRequiredJointsVisible", 0)),
                "p10RequiredJointsVisible": float(window.get("p10RequiredJointsVisible", 0.0)),
                "sourceWindowIntegrity": window.get("sourceWindowIntegrity"),
                "qualityIssues": list(window.get("qualityIssues", [])),
            }
        )
    return chunks


def normalize_pose_scan_strategy(value: str | None) -> str:
    strategy = str(value or "").strip().lower()
    if strategy in {"full", "all", "whole", "entire"}:
        return "full"
    if strategy in {"spread", "distributed", "coverage"}:
        return "spread"
    return "prefix"


def build_pose_sample_plan(
    metadata: BasicVideoMetadata,
    *,
    settings: PosePrefilterSettings,
) -> tuple[list[int], list[dict[str, float]]]:
    sample_step = pose_sample_frame_step(metadata, settings=settings)
    duration_seconds = max(0.0, metadata.duration_seconds)
    strategy = normalize_pose_scan_strategy(settings.scan_strategy)
    if strategy == "full":
        frames = list(range(0, max(0, metadata.frame_count), sample_step))
        return frames, [{"startSeconds": 0.0, "endSeconds": duration_seconds}]

    budget_seconds = (
        duration_seconds
        if float(settings.max_seconds) <= 0.0
        else max(0.1, min(duration_seconds, float(settings.max_seconds)))
    )
    if (
        strategy != "spread"
        or duration_seconds <= budget_seconds + 1e-6
    ):
        end_frame = min(metadata.frame_count, int(round(budget_seconds * metadata.fps)))
        frames = list(range(0, max(0, end_frame), sample_step))
        end_seconds = min(duration_seconds, budget_seconds)
        return frames, [{"startSeconds": 0.0, "endSeconds": end_seconds}]

    window_seconds = min(max(0.5, float(settings.window_seconds)), duration_seconds)
    window_count = max(1, int(math.floor(budget_seconds / window_seconds)))
    max_non_overlapping_windows = max(1, int(math.ceil(duration_seconds / window_seconds)))
    window_count = min(window_count, max_non_overlapping_windows)
    max_start = max(0.0, duration_seconds - window_seconds)
    if window_count <= 1:
        starts = [max_start * 0.5]
    else:
        starts = [max_start * index / (window_count - 1) for index in range(window_count)]

    frames_by_index: dict[int, None] = {}
    sampled_windows: list[dict[str, float]] = []
    for start_seconds in starts:
        end_seconds = min(duration_seconds, start_seconds + window_seconds)
        start_frame = max(0, min(metadata.frame_count - 1, int(round(start_seconds * metadata.fps))))
        end_frame = max(start_frame + 1, min(metadata.frame_count, int(round(end_seconds * metadata.fps))))
        for frame_index in range(start_frame, end_frame, sample_step):
            frames_by_index[frame_index] = None
        sampled_windows.append(
            {
                "startSeconds": round(float(start_seconds), 3),
                "endSeconds": round(float(end_seconds), 3),
            }
        )
    return sorted(frames_by_index), sampled_windows


def pose_sample_frame_step(
    metadata: BasicVideoMetadata,
    *,
    settings: PosePrefilterSettings,
) -> int:
    if settings.sample_fps <= 0.0:
        return 1
    return max(1, int(round(metadata.fps / max(settings.sample_fps, 0.1))))


def resolve_pose_model_path(model: str) -> str:
    model_value = str(model).strip()
    if not model_value:
        return model
    model_path = Path(model_value).expanduser()
    url = KNOWN_ULTRALYTICS_POSE_MODELS.get(model_value)
    if url is not None:
        return str(ensure_cached_pose_model(model_value, url=url, seed_path=model_path if model_path.exists() else None))
    if model_path.exists() or model_path.parent != Path("."):
        return str(model_path)
    return model_value


def ensure_cached_pose_model(
    model_name: str,
    *,
    url: str,
    seed_path: Path | None = None,
    timeout_seconds: float = 600.0,
) -> Path:
    POSE_MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target_path = POSE_MODEL_CACHE_DIR / model_name
    if target_path.exists() and target_path.stat().st_size > 0:
        return target_path

    lock_path = target_path.with_suffix(target_path.suffix + ".lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if target_path.exists() and target_path.stat().st_size > 0:
                return target_path
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for cached pose model: {target_path}")
            time.sleep(0.5)

    partial_path = target_path.with_suffix(target_path.suffix + ".part")
    try:
        if target_path.exists() and target_path.stat().st_size > 0:
            return target_path
        if seed_path is not None and seed_path.exists() and seed_path.stat().st_size > 0:
            shutil.copy2(seed_path, target_path)
            return target_path
        if partial_path.exists():
            partial_path.unlink()
        urlretrieve(url, partial_path)
        if not partial_path.exists() or partial_path.stat().st_size <= 0:
            raise RuntimeError(f"Downloaded empty pose model file: {partial_path}")
        partial_path.replace(target_path)
        return target_path
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def build_pose_windows(samples: list[PoseSample], *, settings: PosePrefilterSettings) -> list[list[PoseSample]]:
    if not samples:
        return []
    duration = max(sample.time_seconds for sample in samples)
    window_seconds = max(0.5, settings.window_seconds)
    overlap = min(max(0.0, settings.overlap_seconds), max(0.0, window_seconds - 0.1))
    step = max(0.1, window_seconds - overlap)
    starts: list[float] = []
    current = 0.0
    while current <= duration + 1e-6:
        starts.append(current)
        current += step
    if starts and starts[-1] + window_seconds < duration:
        starts.append(max(0.0, duration - window_seconds))
    windows: list[list[PoseSample]] = []
    seen: set[tuple[int, int]] = set()
    for start in starts:
        end = start + window_seconds
        window = [sample for sample in samples if start <= sample.time_seconds <= end]
        if not window:
            continue
        key = (int(round(window[0].time_seconds * 1000)), int(round(window[-1].time_seconds * 1000)))
        if key in seen:
            continue
        seen.add(key)
        windows.append(window)
    return windows


def score_pose_window(
    samples: list[PoseSample],
    *,
    metadata: BasicVideoMetadata,
    settings: PosePrefilterSettings,
) -> dict[str, Any]:
    dominant: list[PoseDetection | None] = [select_dominant_detection(sample, metadata=metadata) for sample in samples]
    present = [detection for detection in dominant if detection is not None]
    if not present:
        return {
            "score": 0.0,
            "sampleCount": len(samples),
            "startSeconds": samples[0].time_seconds if samples else 0.0,
            "endSeconds": samples[-1].time_seconds if samples else 0.0,
            "blockingIssues": ["no_person_detected"],
            "reasons": ["pose_no_person_detected"],
            "singlePersonRatio": 0.0,
            "keypointCoverage": 0.0,
            "wholeMovementJointVisibility": 0.0,
            "requiredJointAverageCoverage": 0.0,
            "requiredJointMinCoverage": 0.0,
            "requiredJointP10Coverage": 0.0,
            "allRequiredJointsVisibleRatio": 0.0,
            "minRequiredJointsVisible": 0,
            "p10RequiredJointsVisible": 0.0,
            "bodyScaleRatio": 0.0,
            "cropSafety": 0.0,
            "cameraStability": 0.0,
            "motionStrength": 0.0,
            "activeJointVisibility": 0.0,
            "activeChainVisibility": 0.0,
            "bilateralActiveChainBalance": 1.0,
            "reconstructionViewQuality": 0.0,
            "frontalOrBackViewEvidence": 0.0,
            "activeJoints": [],
            "activeChains": [],
        }
    significant_person_counts = [significant_person_count(sample, metadata=metadata) for sample in samples]
    single_person_ratio = sum(1 for count in significant_person_counts if count == 1) / len(samples)
    multi_person_ratio = sum(1 for count in significant_person_counts if count > 1) / len(samples)
    no_person_ratio = sum(1 for count in significant_person_counts if count == 0) / len(samples)
    max_significant_person_count = max(significant_person_counts) if significant_person_counts else 0
    keypoint_coverage = sum(required_keypoint_coverage(detection) for detection in present) / len(present)
    joint_visibility = required_joint_visibility_metrics(dominant)
    body_scale = median([body_scale_ratio(detection, metadata=metadata) for detection in present])
    crop_safety_scores = [crop_safety_score(detection, metadata=metadata) for detection in present]
    crop_safety = sum(crop_safety_scores) / len(crop_safety_scores)
    camera_stability = camera_stability_score(present, metadata=metadata)
    source_window_integrity = source_window_integrity_metrics(
        dominant,
        samples=samples,
        metadata=metadata,
    )
    motion_strength = pose_motion_strength(present, metadata=metadata)
    active_quality = active_motion_reconstruction_quality(present, metadata=metadata)
    view_quality = pose_reconstruction_view_quality(present, metadata=metadata)
    score = clamp_unit(
        single_person_ratio * 0.15
        + keypoint_coverage * 0.08
        + joint_visibility["wholeMovementJointVisibility"] * 0.14
        + clamp_unit(body_scale / max(settings.min_body_scale, 1e-6)) * 0.11
        + crop_safety * 0.11
        + camera_stability * 0.08
        + motion_strength * 0.12
        + active_quality["activeJointVisibility"] * 0.10
        + active_quality["activeChainVisibility"] * 0.07
        + active_quality["bilateralActiveChainBalance"] * 0.04
    )
    blocking_issues: list[str] = []
    if multi_person_ratio > 0.0:
        blocking_issues.append("multiple_people")
    elif single_person_ratio < 0.8:
        blocking_issues.append("no_person_detected")
    if keypoint_coverage < 0.65:
        blocking_issues.append("low_keypoint_coverage")
    if joint_visibility["wholeMovementJointVisibility"] < 0.60 or joint_visibility["requiredJointP10Coverage"] < 0.58:
        blocking_issues.append("low_required_joint_visibility")
    if body_scale < settings.min_body_scale:
        blocking_issues.append("small_body")
    if crop_safety < 0.65:
        blocking_issues.append("cropped_body")
    quality_issues: list[str] = []
    if not source_window_integrity["singlePersonContinuityPassed"]:
        if source_window_integrity.get("maxSignificantPersonCount", 0) > 1:
            blocking_issues.append("multiple_people")
        else:
            blocking_issues.append("no_person_detected")
    if not source_window_integrity["fullBodyContinuityPassed"]:
        blocking_issues.append("cropped_body")
    if camera_stability < 0.35 or not source_window_integrity["cameraContinuityPassed"]:
        blocking_issues.append("camera_or_track_instability")
    if motion_strength < 0.20:
        blocking_issues.append("weak_body_joint_motion")
    if active_quality["activeJointVisibility"] < 0.72:
        blocking_issues.append("low_active_joint_visibility")
    if active_quality["activeChainVisibility"] < 0.68:
        blocking_issues.append("low_active_chain_visibility")
    if active_quality["bilateralActiveChainBalance"] < 0.55:
        blocking_issues.append("asymmetric_bilateral_active_chain_visibility")
    if view_quality["frontalOrBackViewEvidence"] >= FRONTAL_VIEW_QUALITY_ISSUE_THRESHOLD:
        quality_issues.append("frontal_or_back_view")
    blocking_issues = dedupe_text(blocking_issues)
    quality_issues = dedupe_text(quality_issues)
    reasons = [f"pose_{issue}" for issue in [*blocking_issues, *quality_issues]] or ["pose_good_motion_source"]
    return {
        "score": score,
        "sampleCount": len(samples),
        "startSeconds": samples[0].time_seconds,
        "endSeconds": samples[-1].time_seconds,
        "blockingIssues": blocking_issues,
        "qualityIssues": quality_issues,
        "reasons": reasons,
        "singlePersonRatio": single_person_ratio,
        "multiPersonRatio": multi_person_ratio,
        "noPersonRatio": no_person_ratio,
        "maxSignificantPersonCount": max_significant_person_count,
        "keypointCoverage": keypoint_coverage,
        **joint_visibility,
        "bodyScaleRatio": body_scale,
        "cropSafety": crop_safety,
        "cameraStability": camera_stability,
        "motionStrength": motion_strength,
        "activeJointVisibility": active_quality["activeJointVisibility"],
        "activeChainVisibility": active_quality["activeChainVisibility"],
        "bilateralActiveChainBalance": active_quality["bilateralActiveChainBalance"],
        "reconstructionViewQuality": view_quality["reconstructionViewQuality"],
        "frontalOrBackViewEvidence": view_quality["frontalOrBackViewEvidence"],
        "shoulderWidthBodyRatio": view_quality["shoulderWidthBodyRatio"],
        "hipWidthBodyRatio": view_quality["hipWidthBodyRatio"],
        "viewQualitySampleCount": view_quality["viewQualitySampleCount"],
        "activeJoints": active_quality["activeJoints"],
        "activeChains": active_quality["activeChains"],
        "sourceWindowIntegrity": source_window_integrity,
    }


def select_dominant_detection(sample: PoseSample, *, metadata: BasicVideoMetadata) -> PoseDetection | None:
    if not sample.detections:
        return None
    return max(
        sample.detections,
        key=lambda detection: bbox_area(detection.bbox) * max(0.01, detection.confidence),
    )


def significant_person_count(sample: PoseSample, *, metadata: BasicVideoMetadata) -> int:
    if not sample.detections:
        return 0
    dominant_area = max(bbox_area(detection.bbox) for detection in sample.detections)
    # Source videos must be clean single-person clips. Count smaller background
    # bodies too; the old dominant-area-relative threshold ignored seated or
    # farther-away people that are still visible enough to confuse extraction.
    min_area = max(metadata.width * metadata.height * 0.01, dominant_area * 0.05)
    return sum(
        1
        for detection in sample.detections
        if bbox_area(detection.bbox) >= min_area and len(detection.keypoints) >= 6
    )


def required_keypoint_coverage(detection: PoseDetection) -> float:
    return sum(1 for joint in REQUIRED_JOINTS if joint in detection.keypoints) / len(REQUIRED_JOINTS)


def required_joint_visibility_metrics(dominant: list[PoseDetection | None]) -> dict[str, float]:
    if not dominant:
        return {
            "wholeMovementJointVisibility": 0.0,
            "requiredJointAverageCoverage": 0.0,
            "requiredJointMinCoverage": 0.0,
            "requiredJointP10Coverage": 0.0,
            "allRequiredJointsVisibleRatio": 0.0,
            "minRequiredJointsVisible": 0.0,
            "p10RequiredJointsVisible": 0.0,
        }
    required_count = len(REQUIRED_JOINTS)
    visible_counts = [
        sum(1 for joint in REQUIRED_JOINTS if detection is not None and joint in detection.keypoints)
        for detection in dominant
    ]
    coverages = [count / required_count for count in visible_counts]
    average_coverage = sum(coverages) / len(coverages)
    min_coverage = min(coverages)
    p10_coverage = percentile(coverages, 0.10)
    all_visible_ratio = sum(1 for coverage in coverages if coverage >= 0.999) / len(coverages)
    p10_visible_count = percentile([float(count) for count in visible_counts], 0.10)
    whole_movement_score = clamp_unit(
        average_coverage * 0.35
        + p10_coverage * 0.35
        + min_coverage * 0.15
        + all_visible_ratio * 0.15
    )
    return {
        "wholeMovementJointVisibility": whole_movement_score,
        "requiredJointAverageCoverage": average_coverage,
        "requiredJointMinCoverage": min_coverage,
        "requiredJointP10Coverage": p10_coverage,
        "allRequiredJointsVisibleRatio": all_visible_ratio,
        "minRequiredJointsVisible": float(min(visible_counts)),
        "p10RequiredJointsVisible": p10_visible_count,
    }


def body_scale_ratio(detection: PoseDetection, *, metadata: BasicVideoMetadata) -> float:
    x1, y1, x2, y2 = detection.bbox
    return max(0.0, min(1.0, (y2 - y1) / max(1.0, float(metadata.height))))


def crop_safety_score(detection: PoseDetection, *, metadata: BasicVideoMetadata) -> float:
    if not detection.keypoints:
        return 0.0
    margin = max(8.0, min(metadata.width, metadata.height) * 0.04)
    safe = 0
    total = 0
    for joint in REQUIRED_JOINTS:
        point = detection.keypoints.get(joint)
        if point is None:
            continue
        total += 1
        if margin <= point[0] <= metadata.width - margin and margin <= point[1] <= metadata.height - margin:
            safe += 1
    return safe / total if total else 0.0


def camera_stability_score(detections: list[PoseDetection], *, metadata: BasicVideoMetadata) -> float:
    if len(detections) < 3:
        return 0.5
    centers = [bbox_center(detection.bbox) for detection in detections]
    scales = [body_scale_ratio(detection, metadata=metadata) for detection in detections]
    diagonal = math.hypot(metadata.width, metadata.height)
    center_steps = [
        math.hypot(right[0] - left[0], right[1] - left[1]) / max(diagonal, 1.0)
        for left, right in zip(centers, centers[1:])
    ]
    median_step = median(center_steps)
    scale_variation = (max(scales) - min(scales)) / max(median(scales), 1e-6)
    return clamp_unit(1.0 - median_step / 0.12 - scale_variation / 1.25)


def source_window_integrity_metrics(
    dominant: list[PoseDetection | None],
    *,
    samples: list[PoseSample],
    metadata: BasicVideoMetadata,
) -> dict[str, Any]:
    present = [detection for detection in dominant if detection is not None]
    if not samples or not present:
        return {
            "passed": False,
            "singlePersonContinuityPassed": False,
            "fullBodyContinuityPassed": False,
            "jointVisibilityContinuityPassed": False,
            "cameraContinuityPassed": False,
            "singlePersonRatio": 0.0,
            "fullBodyVisibleRatio": 0.0,
            "wholeMovementJointVisibility": 0.0,
            "requiredJointAverageCoverage": 0.0,
            "requiredJointMinCoverage": 0.0,
            "requiredJointP10Coverage": 0.0,
            "allRequiredJointsVisibleRatio": 0.0,
            "minRequiredJointsVisible": 0,
            "p10RequiredJointsVisible": 0.0,
            "minCropSafety": 0.0,
            "p10CropSafety": 0.0,
            "maxCenterJumpRatio": 1.0,
            "maxScaleJumpRatio": 1.0,
            "sceneCutCount": 0,
            "maxFrameSignatureJump": 0.0,
            "sampleCount": len(samples),
            "presentSampleRatio": 0.0,
            "multiPersonRatio": 0.0,
            "noPersonRatio": 1.0 if samples else 0.0,
            "maxSignificantPersonCount": 0,
        }
    significant_counts = [significant_person_count(sample, metadata=metadata) for sample in samples]
    single_person_ratio = sum(1 for count in significant_counts if count == 1) / len(significant_counts)
    multi_person_ratio = sum(1 for count in significant_counts if count > 1) / len(significant_counts)
    no_person_ratio = sum(1 for count in significant_counts if count == 0) / len(significant_counts)
    max_significant_person_count = max(significant_counts) if significant_counts else 0
    crop_scores = [crop_safety_score(detection, metadata=metadata) for detection in present]
    joint_visibility = required_joint_visibility_metrics(dominant)
    full_body_visible_ratio = sum(1 for score in crop_scores if score >= 0.90) / len(crop_scores)
    min_crop_safety = min(crop_scores) if crop_scores else 0.0
    p10_crop_safety = percentile(crop_scores, 0.10)
    centers = [bbox_center(detection.bbox) for detection in present]
    scales = [body_scale_ratio(detection, metadata=metadata) for detection in present]
    diagonal = max(1.0, math.hypot(metadata.width, metadata.height))
    center_jumps = [
        math.hypot(right[0] - left[0], right[1] - left[1]) / diagonal
        for left, right in zip(centers, centers[1:])
    ]
    median_scale = max(median(scales), 1e-6)
    scale_jumps = [
        abs(right - left) / median_scale
        for left, right in zip(scales, scales[1:])
    ]
    max_center_jump = max(center_jumps) if center_jumps else 0.0
    max_scale_jump = max(scale_jumps) if scale_jumps else 0.0
    frame_signature_jumps = frame_signature_jump_distances(samples)
    scene_cut_count = sum(1 for value in frame_signature_jumps if value >= 0.34)
    max_frame_signature_jump = max(frame_signature_jumps) if frame_signature_jumps else 0.0
    single_person_passed = single_person_ratio >= 0.95
    full_body_passed = full_body_visible_ratio >= 0.85 and p10_crop_safety >= 0.85 and min_crop_safety >= 0.75
    joint_visibility_passed = (
        joint_visibility["wholeMovementJointVisibility"] >= 0.60
        and joint_visibility["requiredJointP10Coverage"] >= 0.58
    )
    camera_passed = max_center_jump <= 0.18 and max_scale_jump <= 0.45 and scene_cut_count == 0
    return {
        "passed": single_person_passed and full_body_passed and joint_visibility_passed and camera_passed,
        "singlePersonContinuityPassed": single_person_passed,
        "fullBodyContinuityPassed": full_body_passed,
        "jointVisibilityContinuityPassed": joint_visibility_passed,
        "cameraContinuityPassed": camera_passed,
        "singlePersonRatio": single_person_ratio,
        "fullBodyVisibleRatio": full_body_visible_ratio,
        **joint_visibility,
        "minCropSafety": min_crop_safety,
        "p10CropSafety": p10_crop_safety,
        "maxCenterJumpRatio": max_center_jump,
        "maxScaleJumpRatio": max_scale_jump,
        "sceneCutCount": scene_cut_count,
        "maxFrameSignatureJump": max_frame_signature_jump,
        "sampleCount": len(samples),
        "presentSampleRatio": len(present) / len(samples),
        "multiPersonRatio": multi_person_ratio,
        "noPersonRatio": no_person_ratio,
        "maxSignificantPersonCount": max_significant_person_count,
    }


def compute_frame_signature(frame: Any) -> tuple[float, ...] | None:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    try:
        resized = cv2.resize(frame, (8, 8), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256])
        values = hist.astype("float32").flatten()
        total = float(np.sum(values))
        if total <= 0:
            return None
        return tuple(float(value / total) for value in values)
    except Exception:
        return None


def frame_signature_jump_distances(samples: list[PoseSample]) -> list[float]:
    signatures = [sample.frame_signature for sample in samples]
    distances: list[float] = []
    for left, right in zip(signatures, signatures[1:]):
        if left is None or right is None or len(left) != len(right):
            continue
        distances.append(sum(abs(a - b) for a, b in zip(left, right)) * 0.5)
    return distances


def pose_motion_strength(detections: list[PoseDetection], *, metadata: BasicVideoMetadata) -> float:
    if len(detections) < 3:
        return 0.0
    tracks: dict[str, list[tuple[float, float]]] = {joint: [] for joint in REQUIRED_JOINTS}
    centers = [bbox_center(detection.bbox) for detection in detections]
    for detection, center in zip(detections, centers):
        for joint in REQUIRED_JOINTS:
            point = detection.keypoints.get(joint)
            if point is not None:
                tracks[joint].append((point[0] - center[0], point[1] - center[1]))
    body_height = max(1.0, median([(detection.bbox[3] - detection.bbox[1]) for detection in detections]))
    ranges = []
    for points in tracks.values():
        if len(points) < max(3, len(detections) // 2):
            continue
        x_range = max(point[0] for point in points) - min(point[0] for point in points)
        y_range = max(point[1] for point in points) - min(point[1] for point in points)
        ranges.append(math.hypot(x_range, y_range) / body_height)
    if not ranges:
        return 0.0
    return clamp_unit(max(ranges) / 0.35)


def active_motion_reconstruction_quality(
    detections: list[PoseDetection],
    *,
    metadata: BasicVideoMetadata,
) -> dict[str, Any]:
    if len(detections) < 3:
        return {
            "activeJointVisibility": 0.0,
            "activeChainVisibility": 0.0,
            "bilateralActiveChainBalance": 1.0,
            "activeJoints": [],
            "activeChains": [],
        }
    joint_tracks = normalized_joint_tracks(detections)
    body_height = max(1.0, median([(detection.bbox[3] - detection.bbox[1]) for detection in detections]))
    motion_by_joint = {
        joint: normalized_track_range(points) / body_height
        for joint, points in joint_tracks.items()
        if len(points) >= max(3, len(detections) // 2)
    }
    if not motion_by_joint:
        return {
            "activeJointVisibility": 0.0,
            "activeChainVisibility": 0.0,
            "bilateralActiveChainBalance": 1.0,
            "activeJoints": [],
            "activeChains": [],
        }
    strongest_motion = max(motion_by_joint.values())
    active_threshold = max(0.06, strongest_motion * 0.35)
    active_joints = [
        joint
        for joint, motion in sorted(motion_by_joint.items(), key=lambda item: item[1], reverse=True)
        if motion >= active_threshold
    ][:8]
    if not active_joints:
        active_joints = [max(motion_by_joint, key=motion_by_joint.get)]
    visibility_by_joint = joint_visibility_scores(detections)
    active_weights = [max(0.01, motion_by_joint.get(joint, 0.0)) for joint in active_joints]
    active_joint_visibility = weighted_average(
        [visibility_by_joint.get(joint, 0.0) for joint in active_joints],
        active_weights,
    )
    active_chain_names = dedupe_text(
        [
            JOINT_CHAIN_BY_NAME[joint]
            for joint in active_joints
            if joint in JOINT_CHAIN_BY_NAME
        ]
    )
    active_chain_scores = [
        chain_visibility_score(visibility_by_joint, SIDE_CHAINS[chain_name])
        for chain_name in active_chain_names
    ]
    active_chain_visibility = min(active_chain_scores) if active_chain_scores else active_joint_visibility
    bilateral_balance = bilateral_active_chain_balance(
        motion_by_joint=motion_by_joint,
        visibility_by_joint=visibility_by_joint,
        active_threshold=active_threshold,
    )
    return {
        "activeJointVisibility": clamp_unit(active_joint_visibility),
        "activeChainVisibility": clamp_unit(active_chain_visibility),
        "bilateralActiveChainBalance": clamp_unit(bilateral_balance),
        "activeJoints": active_joints,
        "activeChains": active_chain_names,
    }


def pose_reconstruction_view_quality(
    detections: list[PoseDetection],
    *,
    metadata: BasicVideoMetadata,
) -> dict[str, Any]:
    shoulder_widths: list[float] = []
    hip_widths: list[float] = []
    for detection in detections:
        body_height = max(1.0, detection.bbox[3] - detection.bbox[1])
        shoulder_width = normalized_joint_pair_distance(
            detection,
            "left_shoulder",
            "right_shoulder",
            body_height=body_height,
        )
        hip_width = normalized_joint_pair_distance(
            detection,
            "left_hip",
            "right_hip",
            body_height=body_height,
        )
        if shoulder_width is not None:
            shoulder_widths.append(shoulder_width)
        if hip_width is not None:
            hip_widths.append(hip_width)

    shoulder_width_body_ratio = median(shoulder_widths) if shoulder_widths else None
    hip_width_body_ratio = median(hip_widths) if hip_widths else None
    shoulder_evidence = ramp_unit(
        shoulder_width_body_ratio or 0.0,
        low=FRONTAL_VIEW_SHOULDER_WIDTH_LOW,
        high=FRONTAL_VIEW_SHOULDER_WIDTH_HIGH,
    )
    hip_evidence = ramp_unit(
        hip_width_body_ratio or 0.0,
        low=FRONTAL_VIEW_HIP_WIDTH_LOW,
        high=FRONTAL_VIEW_HIP_WIDTH_HIGH,
    )
    frontal_or_back_view_evidence = clamp_unit(shoulder_evidence * 0.55 + hip_evidence * 0.45)
    return {
        "reconstructionViewQuality": clamp_unit(1.0 - frontal_or_back_view_evidence),
        "frontalOrBackViewEvidence": frontal_or_back_view_evidence,
        "shoulderWidthBodyRatio": shoulder_width_body_ratio,
        "hipWidthBodyRatio": hip_width_body_ratio,
        "viewQualitySampleCount": max(len(shoulder_widths), len(hip_widths)),
    }


def normalized_joint_pair_distance(
    detection: PoseDetection,
    first_joint: str,
    second_joint: str,
    *,
    body_height: float,
) -> float | None:
    first = detection.keypoints.get(first_joint)
    second = detection.keypoints.get(second_joint)
    if first is None or second is None:
        return None
    return math.hypot(first[0] - second[0], first[1] - second[1]) / max(body_height, 1.0)


def ramp_unit(value: float, *, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return clamp_unit((value - low) / (high - low))


def normalized_joint_tracks(detections: list[PoseDetection]) -> dict[str, list[tuple[float, float]]]:
    tracks: dict[str, list[tuple[float, float]]] = {joint: [] for joint in REQUIRED_JOINTS}
    centers = [bbox_center(detection.bbox) for detection in detections]
    for detection, center in zip(detections, centers):
        for joint in REQUIRED_JOINTS:
            point = detection.keypoints.get(joint)
            if point is not None:
                tracks[joint].append((point[0] - center[0], point[1] - center[1]))
    return tracks


def normalized_track_range(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    x_range = max(point[0] for point in points) - min(point[0] for point in points)
    y_range = max(point[1] for point in points) - min(point[1] for point in points)
    return math.hypot(x_range, y_range)


def joint_visibility_scores(detections: list[PoseDetection]) -> dict[str, float]:
    scores: dict[str, float] = {}
    total = max(1, len(detections))
    for joint in REQUIRED_JOINTS:
        confidences = [
            detection.keypoints[joint][2]
            for detection in detections
            if joint in detection.keypoints
        ]
        if not confidences:
            scores[joint] = 0.0
            continue
        presence = len(confidences) / total
        scores[joint] = clamp_unit(presence * median(confidences))
    return scores


def chain_visibility_score(
    visibility_by_joint: dict[str, float],
    chain_joints: tuple[str, ...],
) -> float:
    values = [visibility_by_joint.get(joint, 0.0) for joint in chain_joints]
    if not values:
        return 0.0
    return clamp_unit(min(values) * 0.65 + (sum(values) / len(values)) * 0.35)


def bilateral_active_chain_balance(
    *,
    motion_by_joint: dict[str, float],
    visibility_by_joint: dict[str, float],
    active_threshold: float,
) -> float:
    balances: list[float] = []
    for left_name, right_name in (("left_arm", "right_arm"), ("left_leg", "right_leg")):
        left_motion = max(motion_by_joint.get(joint, 0.0) for joint in SIDE_CHAINS[left_name])
        right_motion = max(motion_by_joint.get(joint, 0.0) for joint in SIDE_CHAINS[right_name])
        if min(left_motion, right_motion) < active_threshold:
            continue
        left_visibility = chain_visibility_score(visibility_by_joint, SIDE_CHAINS[left_name])
        right_visibility = chain_visibility_score(visibility_by_joint, SIDE_CHAINS[right_name])
        balances.append(min(left_visibility, right_visibility) / max(left_visibility, right_visibility, 1e-6))
    return min(balances) if balances else 1.0


def weighted_average(values: list[float], weights: list[float]) -> float:
    if not values or not weights or len(values) != len(weights):
        return 0.0
    total_weight = sum(weights)
    if total_weight <= 0.0:
        return 0.0
    return sum(value * weight for value, weight in zip(values, weights)) / total_weight


def bbox_from_keypoints(keypoints: dict[str, tuple[float, float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in keypoints.values()]
    ys = [point[1] for point in keypoints.values()]
    return min(xs), min(ys), max(xs), max(ys)


def clamp_bbox(
    bbox: tuple[float, float, float, float],
    metadata: BasicVideoMetadata,
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = bbox
    return (
        max(0.0, min(float(metadata.width), x1)),
        max(0.0, min(float(metadata.height), y1)),
        max(0.0, min(float(metadata.width), x2)),
        max(0.0, min(float(metadata.height), y2)),
    )


def bbox_area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) * 0.5, (bbox[1] + bbox[3]) * 0.5


def average_keypoint_confidence(keypoints: dict[str, tuple[float, float, float]]) -> float:
    if not keypoints:
        return 0.0
    return sum(point[2] for point in keypoints.values()) / len(keypoints)


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[middle])
    return float((ordered[middle - 1] + ordered[middle]) * 0.5)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(math.floor((len(ordered) - 1) * fraction))))
    return float(ordered[index])


def clamp_unit(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def empty_pose_prefilter_result(reason: str) -> PosePrefilterResult:
    return PosePrefilterResult(
        passed=False,
        score=0.0,
        reasons=[reason],
        payload={
            "enabled": True,
            "passed": False,
            "score": 0.0,
            "blockingIssues": [reason],
            "bestChunkStartSeconds": None,
            "bestChunkEndSeconds": None,
        },
    )
