from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from exercise_motion_pkg.wham_results import load_wham_results, select_wham_subject


SPINEPOSE_SPINE_COUNT = 9
SMPL_SPINE_JOINTS = (3, 6, 9)
SMPL_ARM_ANCHOR_JOINTS = (13, 14)
DEFAULT_SPINE_WEIGHTS = (0.50, 0.30, 0.20)
DEFAULT_ARM_COUNTER_ROTATION = 1.0


@dataclass(frozen=True)
class SpinePoseWhamCorrectionStats:
    frame_count: int
    source_frame_count: int
    applied_frame_count: int
    max_delta_degrees: float
    mean_abs_delta_degrees: float
    pose_keys: tuple[str, ...]
    arm_counter_rotation: float


def apply_spinepose_to_wham_pkl(
    *,
    wham_results_pkl: Path,
    spinepose_json_dir: Path,
    output_pkl: Path,
    subject_id: int | str | None = None,
    gain: float = 1.0,
    max_degrees: float = 35.0,
    axis: int = 0,
    invert: bool = False,
    smoothing_window: int = 9,
    arm_counter_rotation: float = DEFAULT_ARM_COUNTER_ROTATION,
) -> SpinePoseWhamCorrectionStats:
    try:
        import joblib  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError("SpinePose/WHAM correction requires joblib and numpy.") from exc

    raw_results = load_wham_results(wham_results_pkl)
    selected_subject_id, payload = select_wham_subject(raw_results, subject_id=subject_id)
    corrected_results = deepcopy(raw_results)
    corrected_payload = corrected_results[selected_subject_id]

    pose = payload.get("pose")
    if not hasattr(pose, "shape") or len(pose.shape) != 2 or pose.shape[1] != 72:  # type: ignore[attr-defined]
        raise ValueError("WHAM camera pose must be shaped like [frames, 72].")
    frame_count = int(pose.shape[0])  # type: ignore[index]

    flexion = _load_spinepose_flexion_signal(spinepose_json_dir, frame_count=frame_count)
    flexion = _median_center(flexion)
    flexion = _moving_average(flexion, window=smoothing_window)
    if invert:
        flexion = [-value for value in flexion]
    max_radians = math.radians(max_degrees)
    deltas = [max(-max_radians, min(max_radians, value * gain)) for value in flexion]

    pose_keys = [key for key in ("pose", "pose_world") if key in corrected_payload]
    total_spine_weight = sum(DEFAULT_SPINE_WEIGHTS)
    arm_counter_rotation = max(0.0, min(1.0, arm_counter_rotation))
    for key in pose_keys:
        corrected_pose = np.array(corrected_payload[key], dtype=np.float32, copy=True)
        if corrected_pose.shape[0] != frame_count or corrected_pose.shape[1] != 72:
            continue
        for frame_index, delta in enumerate(deltas):
            for joint_index, weight in zip(SMPL_SPINE_JOINTS, DEFAULT_SPINE_WEIGHTS, strict=True):
                corrected_pose[frame_index, joint_index * 3 + axis] += float(delta * weight)
            arm_counter_delta = float(-delta * total_spine_weight * arm_counter_rotation)
            for joint_index in SMPL_ARM_ANCHOR_JOINTS:
                corrected_pose[frame_index, joint_index * 3 + axis] += arm_counter_delta
        corrected_payload[key] = corrected_pose

    metadata = dict(corrected_payload.get("spinepose_correction", {}))
    metadata.update(
        {
            "source": "spinepose",
            "spineposeJsonDir": str(spinepose_json_dir),
            "gain": gain,
            "maxDegrees": max_degrees,
            "axis": axis,
            "invert": invert,
            "smoothingWindow": smoothing_window,
            "armCounterRotation": arm_counter_rotation,
            "weights": {
                "spine1": DEFAULT_SPINE_WEIGHTS[0],
                "spine2": DEFAULT_SPINE_WEIGHTS[1],
                "spine3": DEFAULT_SPINE_WEIGHTS[2],
            },
        }
    )
    corrected_payload["spinepose_correction"] = metadata

    output_pkl.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(corrected_results, output_pkl)

    abs_deltas = [abs(value) for value in deltas]
    return SpinePoseWhamCorrectionStats(
        frame_count=frame_count,
        source_frame_count=len(list(spinepose_json_dir.glob("*.json"))),
        applied_frame_count=len(deltas),
        max_delta_degrees=math.degrees(max(abs_deltas) if abs_deltas else 0.0),
        mean_abs_delta_degrees=math.degrees(sum(abs_deltas) / len(abs_deltas)) if abs_deltas else 0.0,
        pose_keys=tuple(pose_keys),
        arm_counter_rotation=arm_counter_rotation,
    )


def _load_spinepose_flexion_signal(spinepose_json_dir: Path, *, frame_count: int) -> list[float]:
    files = sorted(spinepose_json_dir.glob("*.json"))
    if not files:
        raise ValueError(f"No SpinePose JSON frames found in {spinepose_json_dir}.")

    values: list[float] = []
    previous_value = 0.0
    for file in files[:frame_count]:
        frame = json.loads(file.read_text(encoding="utf-8"))
        people = frame.get("people") or []
        if not people:
            values.append(previous_value)
            continue
        raw_points = people[0].get("pose_keypoints_3d") or people[0].get("pose_keypoints_2d")
        if not raw_points:
            values.append(previous_value)
            continue
        stride = 4 if len(raw_points) >= SPINEPOSE_SPINE_COUNT * 4 else 3
        points = [
            tuple(float(v) for v in raw_points[index : index + stride - 1])
            for index in range(0, min(len(raw_points), SPINEPOSE_SPINE_COUNT * stride), stride)
        ]
        if len(points) < SPINEPOSE_SPINE_COUNT:
            values.append(previous_value)
            continue
        value = _spine_curve_angle(points)
        previous_value = value
        values.append(value)

    if len(values) < frame_count:
        values.extend([previous_value] * (frame_count - len(values)))
    return values[:frame_count]


def _spine_curve_angle(points: list[tuple[float, ...]]) -> float:
    base = points[0]
    mid = points[len(points) // 2]
    top = points[-1]
    lower = _subtract(mid, base)
    upper = _subtract(top, mid)
    horizontal_axis = 2 if len(base) >= 3 and len(mid) >= 3 and len(top) >= 3 else 0
    lower_angle = math.atan2(lower[horizontal_axis], max(abs(lower[1]), 1e-6))
    upper_angle = math.atan2(upper[horizontal_axis], max(abs(upper[1]), 1e-6))
    return upper_angle - lower_angle


def _subtract(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(float(a[index]) - float(b[index]) for index in range(min(len(a), len(b))))


def _median_center(values: list[float]) -> list[float]:
    sorted_values = sorted(values)
    median = sorted_values[len(sorted_values) // 2] if sorted_values else 0.0
    return [value - median for value in values]


def _moving_average(values: list[float], *, window: int) -> list[float]:
    if window <= 1 or len(values) <= 2:
        return values
    radius = max(1, window // 2)
    smoothed: list[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        smoothed.append(sum(values[start:end]) / (end - start))
    return smoothed
