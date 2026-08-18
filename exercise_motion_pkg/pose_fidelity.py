from __future__ import annotations

import math
import statistics
from typing import Any, Iterable


POSE_JOINTS = (
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
LOWER_BODY_JOINTS = frozenset(
    ("left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")
)
ANGLE_CHAINS = {
    "left_elbow": ("left_shoulder", "left_elbow", "left_wrist"),
    "right_elbow": ("right_shoulder", "right_elbow", "right_wrist"),
    "left_shoulder": ("left_elbow", "left_shoulder", "left_hip"),
    "right_shoulder": ("right_elbow", "right_shoulder", "right_hip"),
    "left_hip": ("left_shoulder", "left_hip", "left_knee"),
    "right_hip": ("right_shoulder", "right_hip", "right_knee"),
    "left_knee": ("left_hip", "left_knee", "left_ankle"),
    "right_knee": ("right_hip", "right_knee", "right_ankle"),
}
ALIGNMENT_JOINTS = (
    "left_shoulder",
    "right_shoulder",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
)


def source_to_motion_pose_fidelity_metrics(
    source_payload: dict[str, Any],
    motion_payload: dict[str, Any],
) -> dict[str, Any]:
    """Compare source 2D pose with raw WHAM without assuming camera scale or yaw.

    A similarity fit uses only the torso and proximal lower body. All limbs are
    then evaluated outside that fit, so a wrong support posture or asymmetric
    arm reconstruction cannot optimize its own error away. Both horizontal
    world axes and a mirrored source view are evaluated, but one projection is
    selected for the entire clip.
    """
    source_frames = _pose_frames(source_payload, source=True)
    motion_frames = _pose_frames(motion_payload, source=False)
    if len(source_frames) < 5 or len(motion_frames) < 5:
        return _unavailable_metrics(
            source_frame_count=len(source_frames),
            motion_frame_count=len(motion_frames),
            reason="insufficient_pose_frames",
        )

    mode_metrics = [
        _projection_metrics(source_frames, motion_frames, horizontal_axis=axis, mirror=mirror)
        for axis in (0, 2)
        for mirror in (False, True)
    ]
    usable = [metrics for metrics in mode_metrics if metrics.get("comparableFrameCount", 0) >= 5]
    if not usable:
        return _unavailable_metrics(
            source_frame_count=len(source_frames),
            motion_frame_count=len(motion_frames),
            reason="pose_alignment_unavailable",
        )
    selected = min(
        usable,
        key=lambda metrics: (
            _number_or_inf(metrics.get("medianJointErrorBodyRatio")),
            _number_or_inf(metrics.get("p90JointErrorBodyRatio")),
        ),
    )
    return {
        **selected,
        "available": True,
        "sourceFrameCount": len(source_frames),
        "motionFrameCount": len(motion_frames),
        "evaluatedProjectionCount": len(mode_metrics),
    }


def _projection_metrics(
    source_frames: list[dict[str, Any]],
    motion_frames: list[dict[str, Any]],
    *,
    horizontal_axis: int,
    mirror: bool,
) -> dict[str, Any]:
    joint_errors: dict[str, list[float]] = {name: [] for name in POSE_JOINTS}
    angle_errors: dict[str, list[float]] = {name: [] for name in ANGLE_CHAINS}
    comparable_frames = 0
    expected_observations = len(source_frames) * len(POSE_JOINTS)
    observed = 0

    for source_frame in source_frames:
        motion_frame = _nearest_normalized_frame(motion_frames, source_frame["normalizedTime"])
        source_joints = source_frame["joints"]
        motion_joints = motion_frame["joints"]
        fit_names = [
            name for name in ALIGNMENT_JOINTS if name in source_joints and name in motion_joints
        ]
        if len(fit_names) < 3:
            continue
        source_fit = [source_joints[name] for name in fit_names]
        motion_fit = [
            _project_motion_point(motion_joints[name], horizontal_axis=horizontal_axis, mirror=mirror)
            for name in fit_names
        ]
        transform = _similarity_transform(motion_fit, source_fit)
        if transform is None:
            continue
        body_span = _body_span(source_joints.values())
        if body_span <= 1e-9:
            continue
        comparable_frames += 1
        projected: dict[str, tuple[float, float]] = {}
        for name, point in motion_joints.items():
            projected[name] = _apply_similarity(
                _project_motion_point(point, horizontal_axis=horizontal_axis, mirror=mirror),
                transform,
            )
        for name in POSE_JOINTS:
            source_point = source_joints.get(name)
            motion_point = projected.get(name)
            if source_point is None or motion_point is None:
                continue
            observed += 1
            joint_errors[name].append(math.dist(source_point, motion_point) / body_span)
        for name, chain in ANGLE_CHAINS.items():
            if any(joint not in source_joints or joint not in projected for joint in chain):
                continue
            source_angle = _angle_degrees(*(source_joints[joint] for joint in chain))
            motion_angle = _angle_degrees(*(projected[joint] for joint in chain))
            if source_angle is not None and motion_angle is not None:
                angle_errors[name].append(abs(source_angle - motion_angle))

    all_joint_errors = [value for values in joint_errors.values() for value in values]
    lower_errors = [value for name in LOWER_BODY_JOINTS for value in joint_errors[name]]
    all_angle_errors = [value for values in angle_errors.values() for value in values]
    return {
        "projectionHorizontalAxis": "x" if horizontal_axis == 0 else "z",
        "mirrored": mirror,
        "comparableFrameCount": comparable_frames,
        "comparableFrameRatio": comparable_frames / len(source_frames) if source_frames else 0.0,
        "jointObservationCoverage": observed / expected_observations if expected_observations else 0.0,
        "medianJointErrorBodyRatio": _median(all_joint_errors),
        "p90JointErrorBodyRatio": _percentile(all_joint_errors, 0.90),
        "medianLowerJointErrorBodyRatio": _median(lower_errors),
        "p90JointAngleErrorDegrees": _percentile(all_angle_errors, 0.90),
        "perJointMedianErrorBodyRatio": {
            name: _median(values) for name, values in joint_errors.items()
        },
        "perAngleMedianErrorDegrees": {
            name: _median(values) for name, values in angle_errors.items()
        },
    }


def _pose_frames(payload: dict[str, Any], *, source: bool) -> list[dict[str, Any]]:
    frames_value = payload.get("frames")
    if not isinstance(frames_value, list):
        return []
    frames: list[dict[str, Any]] = []
    for index, frame in enumerate(frames_value):
        if not isinstance(frame, dict) or not isinstance(frame.get("joints"), dict):
            continue
        joints = {
            str(name): point
            for name, value in frame["joints"].items()
            if (point := _point(value, dimensions=2 if source else 3)) is not None
        }
        time_value = frame.get("sourceTimeSec") if source else frame.get("timeSec")
        try:
            time_seconds = float(time_value) if time_value is not None else float(index)
        except (TypeError, ValueError):
            time_seconds = float(index)
        frames.append({"time": time_seconds, "joints": joints})
    if not frames:
        return []
    start = frames[0]["time"]
    duration = frames[-1]["time"] - start
    for index, frame in enumerate(frames):
        frame["normalizedTime"] = (
            (frame["time"] - start) / duration
            if duration > 1e-9
            else index / max(1, len(frames) - 1)
        )
    return frames


def _nearest_normalized_frame(
    frames: list[dict[str, Any]],
    normalized_time: float,
) -> dict[str, Any]:
    return min(frames, key=lambda frame: abs(float(frame["normalizedTime"]) - normalized_time))


def _point(value: Any, *, dimensions: int) -> tuple[float, ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) < dimensions:
        return None
    try:
        point = tuple(float(value[index]) for index in range(dimensions))
    except (TypeError, ValueError):
        return None
    return point if all(math.isfinite(component) for component in point) else None


def _project_motion_point(
    point: tuple[float, ...],
    *,
    horizontal_axis: int,
    mirror: bool,
) -> tuple[float, float]:
    horizontal = point[horizontal_axis]
    return (-horizontal if mirror else horizontal, -point[1])


def _similarity_transform(
    source: list[tuple[float, float]],
    target: list[tuple[float, float]],
) -> tuple[float, float, float, float, float, float] | None:
    if len(source) != len(target) or len(source) < 3:
        return None
    source_center = (
        statistics.mean(point[0] for point in source),
        statistics.mean(point[1] for point in source),
    )
    target_center = (
        statistics.mean(point[0] for point in target),
        statistics.mean(point[1] for point in target),
    )
    source_zero = [
        (point[0] - source_center[0], point[1] - source_center[1]) for point in source
    ]
    target_zero = [
        (point[0] - target_center[0], point[1] - target_center[1]) for point in target
    ]
    denominator = sum(x * x + y * y for x, y in source_zero)
    if denominator <= 1e-12:
        return None
    scale_cos = sum(
        source_x * target_x + source_y * target_y
        for (source_x, source_y), (target_x, target_y) in zip(source_zero, target_zero)
    ) / denominator
    scale_sin = sum(
        source_x * target_y - source_y * target_x
        for (source_x, source_y), (target_x, target_y) in zip(source_zero, target_zero)
    ) / denominator
    if not math.isfinite(scale_cos) or not math.isfinite(scale_sin):
        return None
    return (
        scale_cos,
        scale_sin,
        source_center[0],
        source_center[1],
        target_center[0],
        target_center[1],
    )


def _apply_similarity(
    point: tuple[float, float],
    transform: tuple[float, float, float, float, float, float],
) -> tuple[float, float]:
    scale_cos, scale_sin, source_x, source_y, target_x, target_y = transform
    x = point[0] - source_x
    y = point[1] - source_y
    return (
        scale_cos * x - scale_sin * y + target_x,
        scale_sin * x + scale_cos * y + target_y,
    )


def _angle_degrees(
    first: tuple[float, float],
    middle: tuple[float, float],
    last: tuple[float, float],
) -> float | None:
    left = (first[0] - middle[0], first[1] - middle[1])
    right = (last[0] - middle[0], last[1] - middle[1])
    denominator = math.hypot(*left) * math.hypot(*right)
    if denominator <= 1e-12:
        return None
    cosine = max(-1.0, min(1.0, (left[0] * right[0] + left[1] * right[1]) / denominator))
    return math.degrees(math.acos(cosine))


def _body_span(points: Iterable[tuple[float, ...]]) -> float:
    points_list = list(points)
    if len(points_list) < 4:
        return 0.0
    return max(
        max(point[axis] for point in points_list) - min(point[axis] for point in points_list)
        for axis in (0, 1)
    )


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = max(0.0, min(1.0, quantile)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _number_or_inf(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return math.inf
    return parsed if math.isfinite(parsed) else math.inf


def _unavailable_metrics(
    *,
    source_frame_count: int,
    motion_frame_count: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "sourceFrameCount": source_frame_count,
        "motionFrameCount": motion_frame_count,
        "comparableFrameCount": 0,
        "comparableFrameRatio": 0.0,
    }
