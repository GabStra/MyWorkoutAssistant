"""Translate-only WHAM input stabilization from persisted YOLO pose tracks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

YOLO_TRACK_STABILIZATION_POLICY_VERSION = 1
_CENTER_JOINTS = ("pelvis", "hips", "left_hip", "right_hip")
_MIN_POSE_FRAMES = 4
_CROP_PADDING_RATIO = 0.22
_MIN_CROP_FRAME_RATIO = 0.55
_MAX_CROP_FRAME_RATIO = 0.94
_MIN_CENTER_TRAVEL_RATIO = 0.015
_SMOOTH_WINDOW_SECONDS = 0.35


@dataclass(frozen=True)
class YoloTrackStabilizationPlan:
    applied: bool
    reason: str
    crop_width: int
    crop_height: int
    frame_width: int
    frame_height: int
    origins: tuple[tuple[int, int], ...]
    max_center_travel_ratio: float


def load_workspace_yolo_pose_track(candidate_workspace: Path) -> dict[str, Any] | None:
    selection_path = candidate_workspace / "segment_detection" / "segment_selection.json"
    try:
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        selection = {}
    validation = selection.get("exactSourcePhaseValidation")
    if isinstance(validation, dict):
        reference_path_value = validation.get("sourcePoseReferencePath")
        if isinstance(reference_path_value, str) and reference_path_value.strip():
            loaded = _load_pose_payload(Path(reference_path_value))
            if loaded is not None:
                return loaded
    confirmation_root = (
        candidate_workspace
        / "segment_detection"
        / "pre_wham_source_candidates"
        / "deterministic_confirmation"
    )
    if confirmation_root.exists():
        matches = sorted(confirmation_root.glob("*/exact_source_pose_reference.json"))
        for match in matches:
            loaded = _load_pose_payload(match)
            if loaded is not None:
                return loaded
    fallback = candidate_workspace / "segment_detection" / "exact_source_pose_reference.json"
    return _load_pose_payload(fallback)


def plan_yolo_track_stabilization(
    pose_payload: dict[str, Any] | None,
    *,
    frame_count: int,
    fps: float,
    width: int,
    height: int,
    selected_start_seconds: float = 0.0,
) -> YoloTrackStabilizationPlan:
    empty = YoloTrackStabilizationPlan(
        applied=False,
        reason="yolo_track_unavailable",
        crop_width=width,
        crop_height=height,
        frame_width=width,
        frame_height=height,
        origins=tuple(),
        max_center_travel_ratio=0.0,
    )
    if frame_count <= 1 or fps <= 0.0 or width <= 1 or height <= 1:
        return empty
    samples = _pose_track_samples(pose_payload, width=width, height=height)
    if len(samples) < _MIN_POSE_FRAMES:
        return empty
    times = [sample[0] + float(selected_start_seconds) for sample in samples]
    centers_x = _smooth_values([sample[1] for sample in samples], times)
    centers_y = _smooth_values([sample[2] for sample in samples], times)
    half_widths = [sample[3] for sample in samples]
    half_heights = [sample[4] for sample in samples]
    pad = 1.0 + (2.0 * _CROP_PADDING_RATIO)
    crop_width = _even_size(max(half_widths) * 2.0 * pad, width, _MIN_CROP_FRAME_RATIO)
    crop_height = _even_size(max(half_heights) * 2.0 * pad, height, _MIN_CROP_FRAME_RATIO)
    if (
        crop_width >= int(round(width * _MAX_CROP_FRAME_RATIO))
        and crop_height >= int(round(height * _MAX_CROP_FRAME_RATIO))
    ):
        return YoloTrackStabilizationPlan(
            applied=False,
            reason="yolo_track_crop_would_be_full_frame",
            crop_width=width,
            crop_height=height,
            frame_width=width,
            frame_height=height,
            origins=tuple(),
            max_center_travel_ratio=0.0,
        )
    video_times = [index / fps for index in range(frame_count)]
    interp_x = _interpolate_values(times, centers_x, video_times)
    interp_y = _interpolate_values(times, centers_y, video_times)
    travel = max(
        ((x - interp_x[0]) ** 2 + (y - interp_y[0]) ** 2) ** 0.5
        for x, y in zip(interp_x, interp_y)
    )
    travel_ratio = travel / float(min(width, height))
    if travel_ratio < _MIN_CENTER_TRAVEL_RATIO:
        return YoloTrackStabilizationPlan(
            applied=False,
            reason="yolo_track_already_stable",
            crop_width=crop_width,
            crop_height=crop_height,
            frame_width=width,
            frame_height=height,
            origins=tuple(),
            max_center_travel_ratio=travel_ratio,
        )
    origins = tuple(
        crop_origin_for_center(
            center_x,
            center_y,
            crop_width=crop_width,
            crop_height=crop_height,
            frame_width=width,
            frame_height=height,
        )
        for center_x, center_y in zip(interp_x, interp_y)
    )
    return YoloTrackStabilizationPlan(
        applied=True,
        reason="yolo_track_translation_crop",
        crop_width=crop_width,
        crop_height=crop_height,
        frame_width=width,
        frame_height=height,
        origins=origins,
        max_center_travel_ratio=travel_ratio,
    )


def crop_origin_for_center(
    center_x: float,
    center_y: float,
    *,
    crop_width: int,
    crop_height: int,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int]:
    max_x = max(0, frame_width - crop_width)
    max_y = max(0, frame_height - crop_height)
    origin_x = int(round(center_x - (crop_width * 0.5)))
    origin_y = int(round(center_y - (crop_height * 0.5)))
    return max(0, min(max_x, origin_x)), max(0, min(max_y, origin_y))


def apply_yolo_track_stabilization(
    *,
    source_path: Path,
    output_path: Path,
    plan: YoloTrackStabilizationPlan,
) -> Path:
    if not plan.applied or not plan.origins:
        return source_path
    try:
        import cv2  # type: ignore
    except ImportError:
        return source_path

    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        return source_path
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps if fps > 0.0 else 30.0,
        (plan.crop_width, plan.crop_height),
    )
    if not writer.isOpened():
        capture.release()
        return source_path
    try:
        frame_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            origin = plan.origins[min(frame_index, len(plan.origins) - 1)]
            cropped = frame[
                origin[1] : origin[1] + plan.crop_height,
                origin[0] : origin[0] + plan.crop_width,
            ]
            if cropped.shape[0] != plan.crop_height or cropped.shape[1] != plan.crop_width:
                capture.release()
                writer.release()
                return source_path
            writer.write(cropped)
            frame_index += 1
    finally:
        capture.release()
        writer.release()
    if not output_path.exists() or output_path.stat().st_size <= 0:
        return source_path
    return output_path


def _load_pose_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get("pose"), dict):
        return payload["pose"]
    if isinstance(payload, dict) and isinstance(payload.get("frames"), list):
        return payload
    return None


def _pose_track_samples(
    pose_payload: dict[str, Any] | None,
    *,
    width: int,
    height: int,
) -> list[tuple[float, float, float, float, float]]:
    if not isinstance(pose_payload, dict):
        return []
    frames_value = pose_payload.get("frames")
    if not isinstance(frames_value, list):
        return []
    samples: list[tuple[float, float, float, float, float]] = []
    for frame in frames_value:
        if not isinstance(frame, dict):
            continue
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        points = [_joint_xy(value) for value in joints.values()]
        points = [point for point in points if point is not None]
        if len(points) < 3:
            continue
        normalized = all(0.0 <= point[0] <= 1.5 and 0.0 <= point[1] <= 1.5 for point in points)
        scale_x = float(width) if normalized else 1.0
        scale_y = float(height) if normalized else 1.0
        pixel_points = [(point[0] * scale_x, point[1] * scale_y) for point in points]
        center = _track_center(joints, scale_x=scale_x, scale_y=scale_y)
        if center is None:
            xs = [point[0] for point in pixel_points]
            ys = [point[1] for point in pixel_points]
            center = ((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5)
        xs = [point[0] for point in pixel_points]
        ys = [point[1] for point in pixel_points]
        half_width = max(8.0, (max(xs) - min(xs)) * 0.5)
        half_height = max(8.0, (max(ys) - min(ys)) * 0.5)
        time_sec = frame.get("sourceTimeSec")
        if time_sec is None:
            time_sec = frame.get("timeSec")
        try:
            timestamp = float(time_sec)
        except (TypeError, ValueError):
            timestamp = float(len(samples))
        samples.append((timestamp, center[0], center[1], half_width, half_height))
    samples.sort(key=lambda item: item[0])
    return samples


def _track_center(
    joints: dict[str, Any],
    *,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float] | None:
    for name in _CENTER_JOINTS:
        point = _joint_xy(joints.get(name))
        if point is not None:
            return point[0] * scale_x, point[1] * scale_y
    left = _joint_xy(joints.get("left_hip"))
    right = _joint_xy(joints.get("right_hip"))
    if left is not None and right is not None:
        return (
            ((left[0] + right[0]) * 0.5) * scale_x,
            ((left[1] + right[1]) * 0.5) * scale_y,
        )
    return None


def _joint_xy(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict):
        try:
            return float(value["x"]), float(value["y"])
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _smooth_values(values: list[float], times: list[float]) -> list[float]:
    if len(values) <= 2:
        return list(values)
    smoothed: list[float] = []
    for index, time_sec in enumerate(times):
        total = 0.0
        weight = 0.0
        for other_index, other_time in enumerate(times):
            if abs(other_time - time_sec) <= _SMOOTH_WINDOW_SECONDS:
                total += values[other_index]
                weight += 1.0
        smoothed.append(total / weight if weight else values[index])
    return smoothed


def _interpolate_values(
    source_times: list[float],
    source_values: list[float],
    query_times: list[float],
) -> list[float]:
    if not source_times:
        return [0.0 for _ in query_times]
    interpolated: list[float] = []
    for query in query_times:
        if query <= source_times[0]:
            interpolated.append(source_values[0])
            continue
        if query >= source_times[-1]:
            interpolated.append(source_values[-1])
            continue
        end_index = 1
        while end_index < len(source_times) and source_times[end_index] < query:
            end_index += 1
        start_index = end_index - 1
        span = source_times[end_index] - source_times[start_index]
        if span <= 1e-8:
            interpolated.append(source_values[end_index])
            continue
        mix = (query - source_times[start_index]) / span
        interpolated.append(
            source_values[start_index] + (source_values[end_index] - source_values[start_index]) * mix
        )
    return interpolated


def _even_size(raw_size: float, limit: int, min_ratio: float) -> int:
    minimum = int(round(limit * min_ratio))
    sized = int(round(raw_size))
    sized = max(minimum, min(limit, sized))
    if sized % 2:
        sized -= 1
    return max(2, sized)
