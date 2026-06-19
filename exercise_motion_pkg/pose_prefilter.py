from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import shutil
import time
from typing import Any
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


@dataclass(frozen=True)
class PosePrefilterSettings:
    model: str = "yolo26x-pose.pt"
    sample_fps: float = 2.0
    max_seconds: float = 90.0
    window_seconds: float = 8.0
    overlap_seconds: float = 4.0
    min_score: float = 0.45
    min_keypoint_confidence: float = 0.35
    min_body_scale: float = 0.18
    max_candidates: int = 8


@dataclass(frozen=True)
class PoseDetection:
    keypoints: dict[str, tuple[float, float, float]]
    bbox: tuple[float, float, float, float]
    confidence: float = 1.0


@dataclass(frozen=True)
class PoseSample:
    time_seconds: float
    detections: list[PoseDetection]


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
    samples: list[PoseSample] = []
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video for YOLO pose prefiltering: {video_path}")
    try:
        sample_step = max(1, int(round(metadata.fps / max(settings.sample_fps, 0.1))))
        max_frame = min(metadata.frame_count, int(round(max(0.1, settings.max_seconds) * metadata.fps)))
        frame_index = 0
        while frame_index < max_frame:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                break
            detections = detections_from_yolo_result(
                model(frame, verbose=False),
                metadata=metadata,
                min_keypoint_confidence=settings.min_keypoint_confidence,
            )
            samples.append(PoseSample(time_seconds=frame_index / metadata.fps, detections=detections))
            frame_index += sample_step
    finally:
        capture.release()
    result = score_pose_samples(samples, metadata=metadata, settings=settings)
    payload = dict(result.payload)
    payload["resolvedModelPath"] = model_path
    return PosePrefilterResult(
        passed=result.passed,
        score=result.score,
        reasons=result.reasons,
        payload=payload,
    )


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
    scored = [score_pose_window(window, metadata=metadata, settings=settings) for window in windows]
    scored = [item for item in scored if item["sampleCount"] > 0]
    if not scored:
        return empty_pose_prefilter_result("pose_prefilter_no_windows")
    best = max(scored, key=lambda item: float(item["score"]))
    score = float(best["score"])
    blocking_issues = best.get("blockingIssues", [])
    passed = score >= settings.min_score and not blocking_issues
    reasons = list(best.get("reasons", []))
    reasons.append("pose_prefilter_passed" if passed else "pose_prefilter_below_threshold")
    payload = {
        "enabled": True,
        "passed": passed,
        "score": score,
        "bestChunkStartSeconds": best["startSeconds"],
        "bestChunkEndSeconds": best["endSeconds"],
        "blockingIssues": blocking_issues,
        "singlePersonRatio": best["singlePersonRatio"],
        "keypointCoverage": best["keypointCoverage"],
        "bodyScaleRatio": best["bodyScaleRatio"],
        "cropSafety": best["cropSafety"],
        "cameraStability": best["cameraStability"],
        "motionStrength": best["motionStrength"],
        "activeJointVisibility": best["activeJointVisibility"],
        "activeChainVisibility": best["activeChainVisibility"],
        "bilateralActiveChainBalance": best["bilateralActiveChainBalance"],
        "activeJoints": best["activeJoints"],
        "activeChains": best["activeChains"],
        "sampleCount": best["sampleCount"],
        "windowCount": len(scored),
        "model": settings.model,
        "sampleFps": settings.sample_fps,
        "maxSeconds": settings.max_seconds,
        "minScore": settings.min_score,
    }
    return PosePrefilterResult(passed=passed, score=score, reasons=dedupe_text(reasons), payload=payload)


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
            "bodyScaleRatio": 0.0,
            "cropSafety": 0.0,
            "cameraStability": 0.0,
            "motionStrength": 0.0,
            "activeJointVisibility": 0.0,
            "activeChainVisibility": 0.0,
            "bilateralActiveChainBalance": 1.0,
            "activeJoints": [],
            "activeChains": [],
        }
    single_person_ratio = sum(1 for sample in samples if significant_person_count(sample, metadata=metadata) <= 1) / len(samples)
    keypoint_coverage = sum(required_keypoint_coverage(detection) for detection in present) / len(present)
    body_scale = median([body_scale_ratio(detection, metadata=metadata) for detection in present])
    crop_safety = sum(crop_safety_score(detection, metadata=metadata) for detection in present) / len(present)
    camera_stability = camera_stability_score(present, metadata=metadata)
    motion_strength = pose_motion_strength(present, metadata=metadata)
    active_quality = active_motion_reconstruction_quality(present, metadata=metadata)
    score = clamp_unit(
        single_person_ratio * 0.16
        + keypoint_coverage * 0.17
        + clamp_unit(body_scale / max(settings.min_body_scale, 1e-6)) * 0.12
        + crop_safety * 0.12
        + camera_stability * 0.08
        + motion_strength * 0.12
        + active_quality["activeJointVisibility"] * 0.11
        + active_quality["activeChainVisibility"] * 0.08
        + active_quality["bilateralActiveChainBalance"] * 0.04
    )
    blocking_issues: list[str] = []
    if single_person_ratio < 0.8:
        blocking_issues.append("multiple_people")
    if keypoint_coverage < 0.65:
        blocking_issues.append("low_keypoint_coverage")
    if body_scale < settings.min_body_scale:
        blocking_issues.append("small_body")
    if crop_safety < 0.65:
        blocking_issues.append("cropped_body")
    if camera_stability < 0.35:
        blocking_issues.append("camera_or_track_instability")
    if motion_strength < 0.20:
        blocking_issues.append("weak_body_joint_motion")
    if active_quality["activeJointVisibility"] < 0.72:
        blocking_issues.append("low_active_joint_visibility")
    if active_quality["activeChainVisibility"] < 0.68:
        blocking_issues.append("low_active_chain_visibility")
    if active_quality["bilateralActiveChainBalance"] < 0.55:
        blocking_issues.append("asymmetric_bilateral_active_chain_visibility")
    reasons = [f"pose_{issue}" for issue in blocking_issues] or ["pose_good_motion_source"]
    return {
        "score": score,
        "sampleCount": len(samples),
        "startSeconds": samples[0].time_seconds,
        "endSeconds": samples[-1].time_seconds,
        "blockingIssues": blocking_issues,
        "reasons": reasons,
        "singlePersonRatio": single_person_ratio,
        "keypointCoverage": keypoint_coverage,
        "bodyScaleRatio": body_scale,
        "cropSafety": crop_safety,
        "cameraStability": camera_stability,
        "motionStrength": motion_strength,
        "activeJointVisibility": active_quality["activeJointVisibility"],
        "activeChainVisibility": active_quality["activeChainVisibility"],
        "bilateralActiveChainBalance": active_quality["bilateralActiveChainBalance"],
        "activeJoints": active_quality["activeJoints"],
        "activeChains": active_quality["activeChains"],
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
    min_area = max(metadata.width * metadata.height * 0.01, dominant_area * 0.35)
    return sum(1 for detection in sample.detections if bbox_area(detection.bbox) >= min_area)


def required_keypoint_coverage(detection: PoseDetection) -> float:
    return sum(1 for joint in REQUIRED_JOINTS if joint in detection.keypoints) / len(REQUIRED_JOINTS)


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
