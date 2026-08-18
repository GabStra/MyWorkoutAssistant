from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from exercise_motion_pkg.segment_detection import DetectionWindow


CAMERA_STABILITY_POLICY_VERSION = 2
CAMERA_STABILITY_SAMPLE_FPS = 4.0
CAMERA_STABILITY_MAX_SAMPLES_PER_SCENE = 48
CAMERA_STABILITY_MIN_FEATURES = 16
CAMERA_STABILITY_MIN_VALID_PAIRS = 3
CAMERA_STABILITY_MIN_INLIER_RATIO = 0.35
CAMERA_STABILITY_MIN_INLIER_HULL_AREA_RATIO = 0.08
CAMERA_STABILITY_MIN_INLIER_GRID_CELLS = 6
CAMERA_STABILITY_STRONG_STEP_MIN_INLIER_RATIO = 0.75
CAMERA_STABILITY_PERSON_MASK_PADDING_RATIO = 0.12


def analyze_video_scene_camera_stability(
    video_path: Path,
    *,
    scene_windows: list[DetectionWindow],
    pose_payload: dict[str, Any] | None = None,
    source_offset_seconds: float = 0.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        return {
            "policyVersion": CAMERA_STABILITY_POLICY_VERSION,
            "status": "dependency_unavailable",
            "scenes": [unknown_scene_metrics(scene, reason="opencv_unavailable") for scene in scene_windows],
            "error": str(exc)[:500],
            "elapsedSeconds": round(time.perf_counter() - started, 3),
        }

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return {
            "policyVersion": CAMERA_STABILITY_POLICY_VERSION,
            "status": "video_unreadable",
            "scenes": [unknown_scene_metrics(scene, reason="video_unreadable") for scene in scene_windows],
            "elapsedSeconds": round(time.perf_counter() - started, 3),
        }
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0.0 or frame_count <= 0:
            return {
                "policyVersion": CAMERA_STABILITY_POLICY_VERSION,
                "status": "metadata_unavailable",
                "scenes": [unknown_scene_metrics(scene, reason="metadata_unavailable") for scene in scene_windows],
                "elapsedSeconds": round(time.perf_counter() - started, 3),
            }
        scene_metrics = [
            analyze_scene_camera_stability(
                capture,
                scene_window=scene,
                fps=fps,
                frame_count=frame_count,
                pose_payload=pose_payload,
                source_offset_seconds=source_offset_seconds,
                cv2_module=cv2,
            )
            for scene in scene_windows
        ]
    finally:
        capture.release()
    return {
        "policyVersion": CAMERA_STABILITY_POLICY_VERSION,
        "status": "ok",
        "sampleFps": CAMERA_STABILITY_SAMPLE_FPS,
        "scenes": scene_metrics,
        "unstableSceneIndexes": [
            int(item["sceneIndex"])
            for item in scene_metrics
            if item.get("classification") == "unstable"
        ],
        "elapsedSeconds": round(time.perf_counter() - started, 3),
    }


def analyze_scene_camera_stability(
    capture: Any,
    *,
    scene_window: DetectionWindow,
    fps: float,
    frame_count: int,
    pose_payload: dict[str, Any] | None,
    source_offset_seconds: float,
    cv2_module: Any,
) -> dict[str, Any]:
    sample_indexes = scene_sample_frame_indexes(
        scene_window,
        fps=fps,
        frame_count=frame_count,
    )
    if len(sample_indexes) < 2:
        return unknown_scene_metrics(scene_window, reason="insufficient_scene_frames")

    sampled: list[tuple[int, float, np.ndarray, np.ndarray]] = []
    for frame_index in sample_indexes:
        capture.set(cv2_module.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok or frame is None:
            continue
        gray = cv2_module.cvtColor(frame, cv2_module.COLOR_BGR2GRAY)
        height, width = gray.shape[:2]
        mask = camera_background_feature_mask(
            width=width,
            height=height,
            source_time_seconds=(frame_index / fps) + source_offset_seconds,
            pose_payload=pose_payload,
            cv2_module=cv2_module,
        )
        sampled.append((frame_index, frame_index / fps, gray, mask))
    if len(sampled) < 2:
        return unknown_scene_metrics(scene_window, reason="insufficient_readable_frames")

    pair_metrics: list[dict[str, Any]] = []
    for previous, current in zip(sampled, sampled[1:]):
        pair = estimate_background_camera_transform(
            previous_gray=previous[2],
            current_gray=current[2],
            previous_mask=previous[3],
            current_mask=current[3],
            cv2_module=cv2_module,
        )
        pair.update(
            {
                "startFrameIndex": previous[0],
                "endFrameIndex": current[0],
                "startSeconds": round(previous[1], 3),
                "endSeconds": round(current[1], 3),
            }
        )
        pair_metrics.append(pair)
    valid_pairs = [item for item in pair_metrics if item.get("status") == "ok"]
    if len(valid_pairs) < CAMERA_STABILITY_MIN_VALID_PAIRS:
        return {
            **unknown_scene_metrics(scene_window, reason="insufficient_background_tracks"),
            "sampledFrameCount": len(sampled),
            "pairCount": len(pair_metrics),
            "validPairCount": len(valid_pairs),
            "pairs": pair_metrics,
        }

    translations = [float(item["translationRatio"]) for item in valid_pairs]
    rotations = [abs(float(item["rotationDegrees"])) for item in valid_pairs]
    signed_rotations = [float(item["rotationDegrees"]) for item in valid_pairs]
    zoom_changes = [abs(float(item["logScaleChange"])) for item in valid_pairs]
    signed_zoom_changes = [float(item["logScaleChange"]) for item in valid_pairs]
    dx_values = [float(item["translationXRatio"]) for item in valid_pairs]
    dy_values = [float(item["translationYRatio"]) for item in valid_pairs]
    cumulative_translation = float(sum(translations))
    net_translation = math.hypot(sum(dx_values), sum(dy_values))
    directional_coherence = (
        net_translation / cumulative_translation
        if cumulative_translation > 1e-9
        else 0.0
    )
    median_translation = percentile(translations, 50)
    p90_translation = percentile(translations, 90)
    median_rotation = percentile(rotations, 50)
    p90_rotation = percentile(rotations, 90)
    median_zoom = percentile(zoom_changes, 50)
    p90_zoom = percentile(zoom_changes, 90)
    net_rotation = abs(sum(signed_rotations))
    net_zoom = abs(sum(signed_zoom_changes))
    sustained_pan = (
        median_translation >= 0.004
        and net_translation >= 0.035
        and directional_coherence >= 0.55
    )
    sustained_rotation = median_rotation >= 0.15 and net_rotation >= 1.5
    sustained_zoom = median_zoom >= 0.003 and net_zoom >= 0.04
    strong_step_motion = any(is_confident_strong_camera_motion_step(item) for item in valid_pairs)
    unstable = sustained_pan or sustained_rotation or sustained_zoom or strong_step_motion
    moderate = not unstable and (
        p90_translation >= 0.012
        or net_translation >= 0.02
        or p90_rotation >= 0.60
        or net_rotation >= 0.75
        or p90_zoom >= 0.01
        or net_zoom >= 0.02
    )
    classification = "unstable" if unstable else "moderate" if moderate else "stable"
    reasons: list[str] = []
    if sustained_pan:
        reasons.append("sustained_camera_translation")
    if sustained_rotation:
        reasons.append("sustained_camera_rotation")
    if sustained_zoom:
        reasons.append("sustained_camera_zoom")
    if strong_step_motion:
        reasons.append("strong_camera_motion_step")
    return {
        "sceneIndex": scene_window.index,
        "startSeconds": round(scene_window.start_seconds, 3),
        "endSeconds": round(scene_window.end_seconds, 3),
        "status": "analyzed",
        "classification": classification,
        "passed": classification != "unstable",
        "rejectionReasons": ["source_scene_unstable_camera"] if unstable else [],
        "classificationReasons": reasons,
        "sampledFrameCount": len(sampled),
        "pairCount": len(pair_metrics),
        "validPairCount": len(valid_pairs),
        "validPairRatio": round(len(valid_pairs) / max(1, len(pair_metrics)), 4),
        "medianFeatureCount": round(percentile([float(item["featureCount"]) for item in valid_pairs], 50), 3),
        "medianInlierCount": round(percentile([float(item["inlierCount"]) for item in valid_pairs], 50), 3),
        "medianInlierRatio": round(percentile([float(item["inlierRatio"]) for item in valid_pairs], 50), 4),
        "medianTranslationRatio": round(median_translation, 6),
        "p90TranslationRatio": round(p90_translation, 6),
        "cumulativeTranslationRatio": round(cumulative_translation, 6),
        "netTranslationRatio": round(net_translation, 6),
        "directionalCoherence": round(directional_coherence, 4),
        "medianRotationDegrees": round(median_rotation, 4),
        "p90RotationDegrees": round(p90_rotation, 4),
        "netRotationDegrees": round(net_rotation, 4),
        "medianLogScaleChange": round(median_zoom, 6),
        "p90LogScaleChange": round(p90_zoom, 6),
        "netLogScaleChange": round(net_zoom, 6),
        "pairs": pair_metrics,
    }


def scene_sample_frame_indexes(
    scene_window: DetectionWindow,
    *,
    fps: float,
    frame_count: int,
) -> list[int]:
    start = max(0, min(frame_count - 1, int(math.ceil(scene_window.start_seconds * fps))))
    end = max(start, min(frame_count - 1, int(math.floor(scene_window.end_seconds * fps)) - 1))
    step = max(1, int(round(fps / CAMERA_STABILITY_SAMPLE_FPS)))
    indexes = list(range(start, end + 1, step))
    if indexes and indexes[-1] != end:
        indexes.append(end)
    if len(indexes) > CAMERA_STABILITY_MAX_SAMPLES_PER_SCENE:
        selected_positions = np.linspace(
            0,
            len(indexes) - 1,
            CAMERA_STABILITY_MAX_SAMPLES_PER_SCENE,
            dtype=int,
        )
        indexes = [indexes[int(position)] for position in selected_positions]
    return list(dict.fromkeys(indexes))


def camera_background_feature_mask(
    *,
    width: int,
    height: int,
    source_time_seconds: float,
    pose_payload: dict[str, Any] | None,
    cv2_module: Any,
) -> np.ndarray:
    mask = np.full((height, width), 255, dtype=np.uint8)
    bbox = nearest_pose_bbox(pose_payload, source_time_seconds=source_time_seconds)
    if bbox is None:
        return mask
    x1, y1, x2, y2 = bbox
    if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 2.0:
        x1, x2 = x1 * width, x2 * width
        y1, y2 = y1 * height, y2 * height
    padding_x = max(4.0, (x2 - x1) * CAMERA_STABILITY_PERSON_MASK_PADDING_RATIO)
    padding_y = max(4.0, (y2 - y1) * CAMERA_STABILITY_PERSON_MASK_PADDING_RATIO)
    left = max(0, min(width - 1, int(math.floor(x1 - padding_x))))
    top = max(0, min(height - 1, int(math.floor(y1 - padding_y))))
    right = max(left + 1, min(width, int(math.ceil(x2 + padding_x))))
    bottom = max(top + 1, min(height, int(math.ceil(y2 + padding_y))))
    cv2_module.rectangle(mask, (left, top), (right, bottom), 0, -1)
    return mask


def nearest_pose_bbox(
    pose_payload: dict[str, Any] | None,
    *,
    source_time_seconds: float,
) -> tuple[float, float, float, float] | None:
    if not isinstance(pose_payload, dict):
        return None
    samples = pose_payload.get("dominantPoseSamples")
    if not isinstance(samples, list):
        return None
    best: tuple[float, tuple[float, float, float, float]] | None = None
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        sample_time = first_float(
            sample.get("timeSeconds"),
            sample.get("timestampSeconds"),
            sample.get("time"),
            sample.get("timestamp"),
        )
        bbox_value = sample.get("bbox") or sample.get("boundingBox")
        if sample_time is None or not isinstance(bbox_value, (list, tuple)) or len(bbox_value) < 4:
            continue
        try:
            bbox = tuple(float(value) for value in bbox_value[:4])
        except (TypeError, ValueError):
            continue
        distance = abs(sample_time - source_time_seconds)
        if best is None or distance < best[0]:
            best = (distance, bbox)
    return best[1] if best is not None else None


def estimate_background_camera_transform(
    *,
    previous_gray: np.ndarray,
    current_gray: np.ndarray,
    previous_mask: np.ndarray,
    current_mask: np.ndarray,
    cv2_module: Any,
) -> dict[str, Any]:
    points = cv2_module.goodFeaturesToTrack(
        previous_gray,
        maxCorners=300,
        qualityLevel=0.01,
        minDistance=7,
        blockSize=7,
        mask=previous_mask,
    )
    if points is None or len(points) < CAMERA_STABILITY_MIN_FEATURES:
        return {"status": "insufficient_features", "featureCount": 0 if points is None else len(points)}
    next_points, tracking_status, _errors = cv2_module.calcOpticalFlowPyrLK(
        previous_gray,
        current_gray,
        points,
        None,
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2_module.TERM_CRITERIA_EPS | cv2_module.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if next_points is None or tracking_status is None:
        return {"status": "tracking_failed", "featureCount": len(points)}
    previous_points = points.reshape(-1, 2)
    current_points = next_points.reshape(-1, 2)
    tracked = tracking_status.reshape(-1).astype(bool)
    height, width = current_gray.shape[:2]
    current_x = np.clip(np.round(current_points[:, 0]).astype(int), 0, width - 1)
    current_y = np.clip(np.round(current_points[:, 1]).astype(int), 0, height - 1)
    tracked &= current_mask[current_y, current_x] > 0
    previous_points = previous_points[tracked]
    current_points = current_points[tracked]
    if len(previous_points) < CAMERA_STABILITY_MIN_FEATURES:
        return {"status": "insufficient_tracks", "featureCount": len(points), "trackedCount": len(previous_points)}
    transform, inlier_mask = cv2_module.estimateAffinePartial2D(
        previous_points,
        current_points,
        method=cv2_module.RANSAC,
        ransacReprojThreshold=2.0,
        maxIters=2000,
        confidence=0.99,
        refineIters=10,
    )
    if transform is None or inlier_mask is None:
        return {"status": "transform_unavailable", "featureCount": len(points), "trackedCount": len(previous_points)}
    inlier_count = int(np.count_nonzero(inlier_mask))
    inlier_ratio = inlier_count / max(1, len(previous_points))
    if inlier_count < CAMERA_STABILITY_MIN_FEATURES or inlier_ratio < CAMERA_STABILITY_MIN_INLIER_RATIO:
        return {
            "status": "low_transform_confidence",
            "featureCount": len(points),
            "trackedCount": len(previous_points),
            "inlierCount": inlier_count,
            "inlierRatio": round(inlier_ratio, 4),
        }
    inlier_points = previous_points[inlier_mask.reshape(-1).astype(bool)]
    inlier_hull = cv2_module.convexHull(inlier_points.astype(np.float32))
    inlier_hull_area_ratio = (
        float(cv2_module.contourArea(inlier_hull)) / max(1.0, float(width * height))
        if len(inlier_points) >= 3
        else 0.0
    )
    inlier_grid_cell_count = len(
        {
            (
                min(3, max(0, int(float(point[0]) / max(1, width) * 4))),
                min(3, max(0, int(float(point[1]) / max(1, height) * 4))),
            )
            for point in inlier_points
        }
    )
    spatially_distributed = (
        inlier_hull_area_ratio >= CAMERA_STABILITY_MIN_INLIER_HULL_AREA_RATIO
        or inlier_grid_cell_count >= CAMERA_STABILITY_MIN_INLIER_GRID_CELLS
    )
    if not spatially_distributed:
        return {
            "status": "localized_transform_evidence",
            "featureCount": len(points),
            "trackedCount": len(previous_points),
            "inlierCount": inlier_count,
            "inlierRatio": round(inlier_ratio, 4),
            "inlierHullAreaRatio": round(inlier_hull_area_ratio, 4),
            "inlierGridCellCount": inlier_grid_cell_count,
        }
    a = float(transform[0, 0])
    b = float(transform[1, 0])
    translation_x = float(transform[0, 2])
    translation_y = float(transform[1, 2])
    scale = max(1e-9, math.hypot(a, b))
    diagonal = max(1.0, math.hypot(width, height))
    return {
        "status": "ok",
        "featureCount": len(points),
        "trackedCount": len(previous_points),
        "inlierCount": inlier_count,
        "inlierRatio": round(inlier_ratio, 4),
        "inlierHullAreaRatio": round(inlier_hull_area_ratio, 4),
        "inlierGridCellCount": inlier_grid_cell_count,
        "translationXRatio": translation_x / diagonal,
        "translationYRatio": translation_y / diagonal,
        "translationRatio": math.hypot(translation_x, translation_y) / diagonal,
        "rotationDegrees": math.degrees(math.atan2(b, a)),
        "logScaleChange": math.log(scale),
    }


def unknown_scene_metrics(scene_window: DetectionWindow, *, reason: str) -> dict[str, Any]:
    return {
        "sceneIndex": scene_window.index,
        "startSeconds": round(scene_window.start_seconds, 3),
        "endSeconds": round(scene_window.end_seconds, 3),
        "status": "unknown",
        "classification": "unknown",
        "passed": True,
        "rejectionReasons": [],
        "reason": reason,
    }


def is_confident_strong_camera_motion_step(pair_metrics: dict[str, Any]) -> bool:
    if float(pair_metrics.get("inlierRatio") or 0.0) < CAMERA_STABILITY_STRONG_STEP_MIN_INLIER_RATIO:
        return False
    return (
        float(pair_metrics.get("translationRatio") or 0.0) >= 0.025
        or abs(float(pair_metrics.get("rotationDegrees") or 0.0)) >= 1.25
        or abs(float(pair_metrics.get("logScaleChange") or 0.0)) >= 0.02
    )


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile_value))


def first_float(*values: Any) -> float | None:
    for value in values:
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None
