from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


AUDIT_LABELS = {
    "Ab Wheel Kneeling Rollout": "pass",
    "Assisted Pistol Squat": "pass",
    "Barbell Back Squat": "reject",
    "Barbell Behind-the-Neck Press": "review",
    "Barbell Bench Press": "reject",
    "Barbell Bent-Over Row": "reject",
    "Barbell Biceps Curl": "reject",
    "Barbell Box Squat": "review",
    "Barbell Bulgarian Split Squat": "reject",
    "Barbell Calf Raise": "reject",
    "Barbell Clean": "reject",
    "Barbell Drag Curl": "reject",
    "Barbell Front Squat": "pass",
    "Barbell Good Morning": "reject",
    "Barbell Hack Squat": "review",
    "Barbell Hang Clean": "reject",
    "Barbell Incline Bench Press": "reject",
    "Barbell Lunge": "review",
    "Barbell Lying Triceps Extension": "pass",
    "Barbell Push Jerk": "reject",
    "Barbell Push Press": "reject",
    "Barbell Rack Pull": "review",
    "Barbell Reverse Curl": "reject",
    "Barbell Reverse Lunge": "review",
}

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

UPPER_BODY_JOINTS = frozenset(
    {
        "left_shoulder",
        "right_shoulder",
        "left_elbow",
        "right_elbow",
        "left_wrist",
        "right_wrist",
    }
)

LOWER_BODY_JOINTS = frozenset(
    {
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
    }
)

ANGLE_CHAINS = {
    "left_elbow": ("left_shoulder", "left_elbow", "left_wrist"),
    "right_elbow": ("right_shoulder", "right_elbow", "right_wrist"),
    "left_shoulder": ("left_hip", "left_shoulder", "left_elbow"),
    "right_shoulder": ("right_hip", "right_shoulder", "right_elbow"),
    "left_hip": ("left_shoulder", "left_hip", "left_knee"),
    "right_hip": ("right_shoulder", "right_hip", "right_knee"),
    "left_knee": ("left_hip", "left_knee", "left_ankle"),
    "right_knee": ("right_hip", "right_knee", "right_ankle"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate experimental generic motion-fidelity metrics on cached selections."
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path("build/exercise_motion/exercise-library"),
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--render-cut-audit-dir",
        type=Path,
        help="Optionally render current and proposed source-cut contact sheets.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected an object in {path}.")
    return payload


def optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def point(value: Any, dimensions: int) -> np.ndarray | None:
    if not isinstance(value, (list, tuple)) or len(value) < dimensions:
        return None
    try:
        result = np.asarray([float(value[index]) for index in range(dimensions)], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result).all() else None


def source_pose_candidate(
    workspace: Path,
    *,
    video_id: str,
) -> dict[str, Any] | None:
    candidates_path = workspace / "youtube_candidates.json"
    if not candidates_path.exists():
        return None
    payload = load_json(candidates_path)
    exercises = payload.get("exercises")
    if not isinstance(exercises, list) or not exercises:
        return None
    candidates = exercises[0].get("candidates") if isinstance(exercises[0], dict) else None
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if isinstance(candidate, dict) and str(candidate.get("videoId") or "") == video_id:
            return candidate
    return None


def selected_source_span(selected: dict[str, Any]) -> tuple[float, float] | None:
    candidate_workspace_value = selected.get("candidateWorkspace")
    if not candidate_workspace_value:
        return None
    manifest_path = Path(str(candidate_workspace_value)) / "segment_detection" / "segment_selection.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        span = manifest.get("selectedSpanInOriginalSource") or manifest.get("selectedSpan")
        if isinstance(span, dict):
            start = optional_float(span.get("startSeconds"))
            end = optional_float(span.get("endSeconds"))
            if start is not None and end is not None and end > start:
                return start, end
    source_window = selected.get("sourceWindow")
    if isinstance(source_window, dict):
        start = optional_float(source_window.get("startSeconds"))
        end = optional_float(source_window.get("endSeconds"))
        if start is not None and end is not None and end > start:
            return start, end
    return None


def source_pose_frames(
    candidate: dict[str, Any],
    *,
    start_seconds: float,
    end_seconds: float,
) -> list[dict[str, Any]]:
    vision_payload = candidate.get("visionPayload")
    pose_payload = vision_payload.get("posePrefilter") if isinstance(vision_payload, dict) else None
    samples = pose_payload.get("dominantPoseSamples") if isinstance(pose_payload, dict) else None
    if not isinstance(samples, list):
        return []
    frames: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        time_seconds = optional_float(sample.get("timeSeconds"))
        keypoints = sample.get("keypoints")
        if (
            time_seconds is None
            or time_seconds < start_seconds - 1e-6
            or time_seconds > end_seconds + 1e-6
            or not isinstance(keypoints, dict)
        ):
            continue
        joints: dict[str, tuple[np.ndarray, float]] = {}
        for name in POSE_JOINTS:
            value = keypoints.get(name)
            xy = point(value, 2)
            confidence = optional_float(value[2]) if isinstance(value, (list, tuple)) and len(value) >= 3 else None
            if xy is not None and confidence is not None:
                joints[name] = (xy, confidence)
        left_hip = joints.get("left_hip")
        right_hip = joints.get("right_hip")
        if left_hip is not None and right_hip is not None:
            joints["pelvis"] = ((left_hip[0] + right_hip[0]) * 0.5, min(left_hip[1], right_hip[1]))
        frames.append({"time": time_seconds - start_seconds, "joints": joints})
    return frames


def source_window_span(selected: dict[str, Any]) -> tuple[float, float] | None:
    candidate_workspace_value = selected.get("candidateWorkspace")
    if candidate_workspace_value:
        manifest_path = Path(str(candidate_workspace_value)) / "segment_detection" / "segment_selection.json"
        if manifest_path.exists():
            manifest = load_json(manifest_path)
            window = manifest.get("candidateSourceWindow")
            if isinstance(window, dict):
                start = optional_float(window.get("startSecondsInOriginalSource"))
                end = optional_float(window.get("endSecondsInOriginalSource"))
                if start is None or end is None:
                    start = optional_float(window.get("startSeconds"))
                    end = optional_float(window.get("endSeconds"))
                if start is not None and end is not None and end > start:
                    return start, end
    window = selected.get("sourceWindow")
    if isinstance(window, dict):
        start = optional_float(window.get("startSeconds"))
        end = optional_float(window.get("endSeconds"))
        if start is not None and end is not None and end > start:
            return start, end
    return None


def interpolate_missing(values: np.ndarray) -> np.ndarray | None:
    indices = np.arange(values.shape[0])
    available = np.flatnonzero(np.isfinite(values))
    if available.size < max(3, int(math.ceil(values.shape[0] * 0.60))):
        return None
    return np.interp(indices, available, values[available])


def normalized_pose_matrix(source_frames: list[dict[str, Any]]) -> tuple[np.ndarray, list[str]] | None:
    if len(source_frames) < 7:
        return None
    joint_names = [name for name in POSE_JOINTS if any(name in frame["joints"] for frame in source_frames)]
    columns: list[np.ndarray] = []
    retained_names: list[str] = []
    for name in joint_names:
        joint_columns: list[np.ndarray] = []
        for axis in range(2):
            values = np.asarray(
                [
                    frame["joints"][name][0][axis]
                    if name in frame["joints"] and frame["joints"][name][1] >= 0.50
                    else np.nan
                    for frame in source_frames
                ],
                dtype=np.float64,
            )
            interpolated = interpolate_missing(values)
            if interpolated is None:
                joint_columns = []
                break
            joint_columns.append(interpolated)
        if joint_columns:
            columns.extend(joint_columns)
            retained_names.append(name)
    if len(retained_names) < 6:
        return None
    matrix = np.stack(columns, axis=1)
    name_to_column = {name: index * 2 for index, name in enumerate(retained_names)}
    if "left_hip" not in name_to_column or "right_hip" not in name_to_column:
        return None
    left_hip_column = name_to_column["left_hip"]
    right_hip_column = name_to_column["right_hip"]
    pelvis = (
        matrix[:, left_hip_column : left_hip_column + 2]
        + matrix[:, right_hip_column : right_hip_column + 2]
    ) * 0.5
    reshaped = matrix.reshape(matrix.shape[0], len(retained_names), 2)
    centered = reshaped - pelvis[:, None, :]
    frame_spans = np.maximum(
        np.ptp(reshaped[:, :, 0], axis=1),
        np.ptp(reshaped[:, :, 1], axis=1),
    )
    positive_spans = frame_spans[frame_spans > 1e-6]
    if positive_spans.size == 0:
        return None
    scale = float(np.median(positive_spans))
    return centered.reshape(matrix.shape[0], -1) / scale, retained_names


def median_filter(values: np.ndarray) -> np.ndarray:
    if values.size < 5:
        return values.copy()
    return np.asarray(
        [
            statistics.median(values[max(0, index - 1) : min(values.size, index + 2)])
            for index in range(values.size)
        ],
        dtype=np.float64,
    )


def phase_visits(values: np.ndarray) -> list[dict[str, Any]]:
    minimum = float(values.min())
    value_range = float(values.max() - minimum)
    if value_range <= 1e-9:
        return []
    normalized = (values - minimum) / value_range
    visits: list[dict[str, Any]] = []
    active_phase: str | None = None
    active_indices: list[int] = []
    for index, value in enumerate(normalized):
        phase = "low" if value <= 0.30 else "high" if value >= 0.70 else None
        if phase is None:
            continue
        if phase != active_phase:
            if active_phase is not None:
                visits.append({"phase": active_phase, "indices": active_indices})
            active_phase = phase
            active_indices = [index]
        else:
            active_indices.append(index)
    if active_phase is not None:
        visits.append({"phase": active_phase, "indices": active_indices})
    return visits


def phase_anchor_index(
    visit: dict[str, Any],
    values: np.ndarray,
    *,
    boundary: str,
) -> int:
    indices = [int(index) for index in visit["indices"]]
    phase = str(visit["phase"])
    extreme = max(values[index] for index in indices) if phase == "high" else min(values[index] for index in indices)
    tolerance = max(1e-9, float(values.max() - values.min()) * 0.08)
    near_extreme = [
        index
        for index in indices
        if abs(float(values[index]) - float(extreme)) <= tolerance
    ]
    candidates = near_extreme or indices
    return max(candidates) if boundary == "start" else min(candidates)


def pose_cycle_candidates(source_frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = normalized_pose_matrix(source_frames)
    if normalized is None:
        return []
    matrix, retained_names = normalized
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    _, singular_values, right = np.linalg.svd(centered, full_matrices=False)
    candidates: list[dict[str, Any]] = []
    component_count = min(4, right.shape[0])
    for component_index in range(component_count):
        signal = median_filter(centered @ right[component_index])
        visits = phase_visits(signal)
        for visit_index in range(len(visits) - 2):
            first, middle, last = visits[visit_index : visit_index + 3]
            if first["phase"] != last["phase"] or first["phase"] == middle["phase"]:
                continue
            start_index = phase_anchor_index(first, signal, boundary="start")
            end_index = phase_anchor_index(last, signal, boundary="finish")
            if end_index - start_index < 3:
                continue
            start_index = max(0, start_index - 1)
            end_index = min(len(source_frames) - 1, end_index + 1)
            duration = float(source_frames[end_index]["time"] - source_frames[start_index]["time"])
            if duration < 0.50:
                continue
            pose_slice = matrix[start_index : end_index + 1]
            endpoint_error = float(
                np.linalg.norm(pose_slice[-1] - pose_slice[0])
                / math.sqrt(max(1, pose_slice.shape[1]))
            )
            excursion = float(
                max(np.linalg.norm(row - pose_slice[0]) for row in pose_slice)
                / math.sqrt(max(1, pose_slice.shape[1]))
            )
            start_velocity = float(np.linalg.norm(matrix[start_index + 1] - matrix[start_index]))
            end_velocity = float(np.linalg.norm(matrix[end_index] - matrix[end_index - 1]))
            velocity_scale = float(
                statistics.median(
                    np.linalg.norm(matrix[index] - matrix[index - 1])
                    for index in range(1, len(matrix))
                )
            )
            boundary_velocity_ratio = (
                (start_velocity + end_velocity) / (2.0 * velocity_scale)
                if velocity_scale > 1e-9
                else 0.0
            )
            excursion_score = min(1.0, excursion / 0.18)
            endpoint_score = max(0.0, 1.0 - endpoint_error / max(0.12, excursion))
            boundary_score = max(0.0, 1.0 - boundary_velocity_ratio / 3.0)
            variance_share = float(
                singular_values[component_index] ** 2
                / max(1e-9, float(np.sum(singular_values**2)))
            )
            score = 0.45 * endpoint_score + 0.35 * excursion_score + 0.15 * boundary_score + 0.05 * min(1.0, variance_share * 4.0)
            candidates.append(
                {
                    "startSeconds": float(source_frames[start_index]["time"]),
                    "endSeconds": float(source_frames[end_index]["time"]),
                    "durationSeconds": duration,
                    "score": score,
                    "endpointErrorBodyRatio": endpoint_error,
                    "excursionBodyRatio": excursion,
                    "boundaryVelocityRatio": boundary_velocity_ratio,
                    "componentIndex": component_index,
                    "componentVarianceShare": variance_share,
                    "phaseSequence": [first["phase"], middle["phase"], last["phase"]],
                    "retainedJointCount": len(retained_names),
                }
            )
    candidates.sort(key=lambda candidate: (-float(candidate["score"]), float(candidate["durationSeconds"])))
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        if any(
            abs(float(candidate["startSeconds"]) - float(existing["startSeconds"])) <= 0.20
            and abs(float(candidate["endSeconds"]) - float(existing["endSeconds"])) <= 0.20
            for existing in deduped
        ):
            continue
        deduped.append(candidate)
    return deduped[:8]


def motion_frames(payload: dict[str, Any]) -> list[dict[str, Any]]:
    frames = payload.get("frames")
    if not isinstance(frames, list):
        return []
    result: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict) or not isinstance(frame.get("joints"), dict):
            continue
        time_seconds = optional_float(frame.get("timeSec"))
        if time_seconds is None:
            fps = optional_float(payload.get("fps")) or 30.0
            time_seconds = index / fps
        joints = {
            str(name): coords
            for name, value in frame["joints"].items()
            if (coords := point(value, 3)) is not None
        }
        result.append({"time": time_seconds, "joints": joints})
    return result


def nearest_motion_frame(frames: list[dict[str, Any]], time_seconds: float) -> dict[str, Any] | None:
    if not frames:
        return None
    return min(frames, key=lambda frame: abs(float(frame["time"]) - time_seconds))


def body_span_2d(joints: dict[str, tuple[np.ndarray, float]]) -> float | None:
    usable = [coords for coords, confidence in joints.values() if confidence >= 0.50]
    if len(usable) < 4:
        return None
    values = np.asarray(usable)
    return float(max(np.ptp(values[:, 0]), np.ptp(values[:, 1])))


def similarity_align_2d(
    source: np.ndarray,
    target: np.ndarray,
) -> np.ndarray | None:
    if source.shape != target.shape or source.shape[0] < 3:
        return None
    source_center = source.mean(axis=0)
    target_center = target.mean(axis=0)
    source_zero = source - source_center
    target_zero = target - target_center
    source_norm = float(np.linalg.norm(source_zero))
    target_norm = float(np.linalg.norm(target_zero))
    if source_norm <= 1e-9 or target_norm <= 1e-9:
        return None
    covariance = source_zero.T @ target_zero
    left, _, right = np.linalg.svd(covariance)
    rotation = left @ right
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1
        rotation = left @ right
    scale = target_norm / source_norm
    return (source_zero @ rotation) * scale + target_center


def angle_degrees(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float | None:
    left = a - b
    right = c - b
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator <= 1e-9:
        return None
    cosine = float(np.clip(np.dot(left, right) / denominator, -1.0, 1.0))
    return math.degrees(math.acos(cosine))


def source_to_raw_metrics(
    source_frames: list[dict[str, Any]],
    raw_frames: list[dict[str, Any]],
) -> dict[str, Any]:
    joint_errors: dict[str, list[float]] = {name: [] for name in POSE_JOINTS}
    angle_errors: dict[str, list[float]] = {name: [] for name in ANGLE_CHAINS}
    comparable_frames = 0
    confident_joint_observations = 0
    expected_joint_observations = len(source_frames) * len(POSE_JOINTS)
    for source_frame in source_frames:
        raw_frame = nearest_motion_frame(raw_frames, float(source_frame["time"]))
        if raw_frame is None:
            continue
        source_joints = source_frame["joints"]
        raw_joints = raw_frame["joints"]
        fit_names = [
            name
            for name in (
                "left_shoulder",
                "right_shoulder",
                "left_hip",
                "right_hip",
                "left_knee",
                "right_knee",
            )
            if name in source_joints
            and source_joints[name][1] >= 0.50
            and name in raw_joints
        ]
        if len(fit_names) < 3:
            continue
        source_fit = np.asarray([source_joints[name][0] for name in fit_names])
        raw_fit = np.asarray([[raw_joints[name][0], -raw_joints[name][1]] for name in fit_names])
        raw_names = [name for name in POSE_JOINTS if name in raw_joints]
        raw_points = np.asarray([[raw_joints[name][0], -raw_joints[name][1]] for name in raw_names])
        aligned = similarity_align_2d(raw_points, np.asarray([
            source_joints[name][0] if name in source_joints else source_fit.mean(axis=0)
            for name in raw_names
        ]))
        # Use the stable torso/lower-body fit for scale/orientation, while
        # retaining every evaluated joint outside the fit so arm errors cannot
        # optimize themselves away.
        fit_aligned = similarity_align_2d(raw_fit, source_fit)
        if fit_aligned is None:
            continue
        raw_center = raw_fit.mean(axis=0)
        source_center = source_fit.mean(axis=0)
        raw_zero = raw_fit - raw_center
        source_zero = source_fit - source_center
        covariance = raw_zero.T @ source_zero
        left, _, right = np.linalg.svd(covariance)
        rotation = left @ right
        if np.linalg.det(rotation) < 0:
            left[:, -1] *= -1
            rotation = left @ right
        raw_norm = float(np.linalg.norm(raw_zero))
        source_norm = float(np.linalg.norm(source_zero))
        if raw_norm <= 1e-9 or source_norm <= 1e-9:
            continue
        scale = source_norm / raw_norm
        projected = {
            name: ((np.asarray([coords[0], -coords[1]]) - raw_center) @ rotation) * scale + source_center
            for name, coords in raw_joints.items()
        }
        body_span = body_span_2d(source_joints)
        if body_span is None or body_span <= 1e-9:
            continue
        comparable_frames += 1
        for name in POSE_JOINTS:
            source_value = source_joints.get(name)
            raw_value = projected.get(name)
            if source_value is None or source_value[1] < 0.50 or raw_value is None:
                continue
            confident_joint_observations += 1
            joint_errors[name].append(float(np.linalg.norm(source_value[0] - raw_value) / body_span))
        for chain_name, chain in ANGLE_CHAINS.items():
            if any(name not in source_joints or source_joints[name][1] < 0.50 for name in chain):
                continue
            if any(name not in projected for name in chain):
                continue
            source_angle = angle_degrees(*(source_joints[name][0] for name in chain))
            raw_angle = angle_degrees(*(projected[name] for name in chain))
            if source_angle is not None and raw_angle is not None:
                angle_errors[chain_name].append(abs(source_angle - raw_angle))
    all_joint_errors = [value for values in joint_errors.values() for value in values]
    upper_errors = [value for name in UPPER_BODY_JOINTS for value in joint_errors[name]]
    lower_errors = [value for name in LOWER_BODY_JOINTS for value in joint_errors[name]]
    all_angle_errors = [value for values in angle_errors.values() for value in values]
    return {
        "sourceFrameCount": len(source_frames),
        "comparableFrameCount": comparable_frames,
        "jointObservationCoverage": (
            confident_joint_observations / expected_joint_observations
            if expected_joint_observations
            else 0.0
        ),
        "medianJointErrorBodyRatio": median_or_none(all_joint_errors),
        "p90JointErrorBodyRatio": percentile_or_none(all_joint_errors, 90),
        "medianUpperJointErrorBodyRatio": median_or_none(upper_errors),
        "p90UpperJointErrorBodyRatio": percentile_or_none(upper_errors, 90),
        "medianLowerJointErrorBodyRatio": median_or_none(lower_errors),
        "p90LowerJointErrorBodyRatio": percentile_or_none(lower_errors, 90),
        "medianJointAngleErrorDegrees": median_or_none(all_angle_errors),
        "p90JointAngleErrorDegrees": percentile_or_none(all_angle_errors, 90),
        "perJointMedianErrorBodyRatio": {
            name: median_or_none(values) for name, values in joint_errors.items()
        },
        "perAngleMedianErrorDegrees": {
            name: median_or_none(values) for name, values in angle_errors.items()
        },
    }


def interpolate_motion_feature_series(
    frames: list[dict[str, Any]],
    *,
    sample_count: int = 64,
) -> dict[str, np.ndarray]:
    if len(frames) < 2:
        return {}
    times = np.asarray([float(frame["time"]) for frame in frames], dtype=np.float64)
    duration = float(times[-1] - times[0])
    if duration <= 1e-9:
        return {}
    normalized_times = (times - times[0]) / duration
    target_times = np.linspace(0.0, 1.0, sample_count)
    series: dict[str, list[float]] = {}
    for name, chain in ANGLE_CHAINS.items():
        values: list[float] = []
        valid = True
        for frame in frames:
            joints = frame["joints"]
            if any(joint not in joints for joint in chain):
                valid = False
                break
            angle = angle_degrees(*(joints[joint] for joint in chain))
            if angle is None:
                valid = False
                break
            values.append(angle)
        if valid:
            series[f"angle:{name}"] = values
    result: dict[str, np.ndarray] = {}
    for name, values in series.items():
        result[name] = np.interp(target_times, normalized_times, np.asarray(values, dtype=np.float64))
    return result


def raw_to_final_metrics(
    raw_frames: list[dict[str, Any]],
    final_frames: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_series = interpolate_motion_feature_series(raw_frames)
    final_series = interpolate_motion_feature_series(final_frames)
    feature_errors: dict[str, float] = {}
    for name in sorted(set(raw_series).intersection(final_series)):
        difference = raw_series[name] - final_series[name]
        feature_errors[name] = float(math.sqrt(float(np.mean(difference * difference))))
    values = list(feature_errors.values())
    return {
        "featureCount": len(values),
        "medianAngleTrajectoryRmseDegrees": median_or_none(values),
        "p90AngleTrajectoryRmseDegrees": percentile_or_none(values, 90),
        "maxAngleTrajectoryRmseDegrees": max(values) if values else None,
        "perFeatureAngleTrajectoryRmseDegrees": feature_errors,
    }


def median_or_none(values: Iterable[float]) -> float | None:
    numeric = list(values)
    return float(statistics.median(numeric)) if numeric else None


def percentile_or_none(values: Iterable[float], percentile: float) -> float | None:
    numeric = list(values)
    return float(np.percentile(np.asarray(numeric, dtype=np.float64), percentile)) if numeric else None


def cycle_count_from_segment_manifest(candidate_workspace: Path) -> dict[str, Any]:
    path = candidate_workspace / "segment_detection" / "segment_selection.json"
    if not path.exists():
        return {"available": False}
    payload = load_json(path)
    metrics = payload.get("exactSourcePhaseValidation")
    if not isinstance(metrics, dict):
        return {"available": False}
    sequence = metrics.get("majorPhaseSequence")
    sequence = [str(value) for value in sequence] if isinstance(sequence, list) else []
    cycle_count = max(0, (len(sequence) - 1) // 2) if len(sequence) >= 3 else 0
    return {
        "available": True,
        "passed": bool(payload.get("exactSourcePhaseValidationPassed")),
        "poseFailureOverriddenByVlm": bool(metrics.get("poseFailureOverriddenByVlm")),
        "reason": metrics.get("reason"),
        "majorPhaseSequence": sequence,
        "cycleCount": cycle_count,
        "singleCycle": cycle_count == 1 and len(sequence) == 3,
        "selectedSpan": payload.get("selectedSpanInOriginalSource") or payload.get("selectedSpan"),
        "detectionSourceVideoPath": payload.get("detectionSourceVideoPath"),
    }


def exact_cycle_pyramid_audit(
    *,
    candidate_workspace: Path,
    source_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    """Check whether today's geometric source-cut pyramid already contains a single cycle."""
    manifest_path = candidate_workspace / "segment_detection" / "segment_selection.json"
    if source_candidate is None or not manifest_path.exists():
        return {"available": False}
    manifest = load_json(manifest_path)
    source_window = manifest.get("candidateSourceWindow")
    chunk_payload = manifest.get("chunkEstimate")
    vision_payload = source_candidate.get("visionPayload")
    pose_payload = vision_payload.get("posePrefilter") if isinstance(vision_payload, dict) else None
    if not isinstance(source_window, dict) or not isinstance(chunk_payload, dict) or not isinstance(pose_payload, dict):
        return {"available": False}

    local_start = optional_float(source_window.get("startSeconds"))
    local_end = optional_float(source_window.get("endSeconds"))
    original_start = optional_float(source_window.get("startSecondsInOriginalSource"))
    if local_start is None or local_end is None or local_end <= local_start:
        return {"available": False}
    source_offset = (original_start - local_start) if original_start is not None else 0.0

    from exercise_motion_pkg.bake_and_rank import (
        DetectionWindow,
        build_source_video_pyramid_candidate_windows,
        source_cut_candidate_motion_coverage_metrics,
        source_cut_min_candidate_duration_seconds,
    )

    chunk_estimate = SimpleNamespace(
        rep_duration_min_sec=optional_float(chunk_payload.get("repDurationMinSec")),
        rep_duration_max_sec=optional_float(chunk_payload.get("repDurationMaxSec")),
        movement_complexity=str(chunk_payload.get("movementComplexity") or "compound"),
    )
    contract = manifest.get("exerciseMotionContract")
    contract = contract if isinstance(contract, dict) else None
    parent = DetectionWindow(index=0, start_seconds=local_start, end_seconds=local_end)
    minimum_duration = source_cut_min_candidate_duration_seconds(
        chunk_estimate=chunk_estimate,
        exercise_motion_contract=contract,
    )
    specs = build_source_video_pyramid_candidate_windows(
        window=parent,
        chunk_estimate=chunk_estimate,
        min_duration_floor_seconds=minimum_duration,
    )
    exact_candidates: list[dict[str, Any]] = []
    for spec in specs:
        coverage = source_cut_candidate_motion_coverage_metrics(
            candidate_window=spec.window,
            pose_payload=pose_payload,
            exercise_name=str(manifest.get("exerciseName") or ""),
            chunk_estimate=chunk_estimate,
            exercise_motion_contract=contract,
            source_offset_seconds=source_offset,
        )
        phase = coverage.get("candidateFullRepetitionPhaseCompletenessMetrics")
        if not isinstance(phase, dict) or not bool(phase.get("hasSingleMajorCycle")):
            continue
        exact_candidates.append(
            {
                "startSeconds": spec.window.start_seconds,
                "endSeconds": spec.window.end_seconds,
                "startSecondsInOriginalSource": source_offset + spec.window.start_seconds,
                "endSecondsInOriginalSource": source_offset + spec.window.end_seconds,
                "durationSeconds": spec.window.end_seconds - spec.window.start_seconds,
                "endpointPhaseDeltaRatio": phase.get("endpointPhaseDeltaRatio"),
                "majorPhaseSequence": phase.get("majorPhaseSequence"),
                "strategy": spec.chunking.get("strategy"),
            }
        )
    exact_candidates.sort(
        key=lambda candidate: (
            optional_float(candidate.get("endpointPhaseDeltaRatio")) or math.inf,
            optional_float(candidate.get("durationSeconds")) or math.inf,
        )
    )
    return {
        "available": True,
        "candidateCount": len(specs),
        "exactSingleCycleCandidateCount": len(exact_candidates),
        "bestExactSingleCycleCandidate": exact_candidates[0] if exact_candidates else None,
    }


def render_cut_audit(result: dict[str, Any], output_root: Path) -> None:
    from exercise_motion_pkg.bake_and_rank import DetectionWindow, render_video_window_contact_sheet

    cut = result.get("cut")
    if not isinstance(cut, dict):
        return
    video_path_value = cut.get("detectionSourceVideoPath")
    if not video_path_value:
        return
    video_path = Path(str(video_path_value))
    if not video_path.exists():
        return
    exercise_dir = output_root / result["exerciseName"].lower().replace(" ", "-").replace("'", "")
    selected_span = cut.get("selectedSpan")
    if isinstance(selected_span, dict):
        start = optional_float(selected_span.get("startSeconds"))
        end = optional_float(selected_span.get("endSeconds"))
        if start is not None and end is not None and end > start:
            render_video_window_contact_sheet(
                video_path=video_path,
                window=DetectionWindow(index=0, start_seconds=start, end_seconds=end),
                output_dir=exercise_dir / "current",
                frame_count=12,
                contact_sheet_frames_per_sheet_override=12,
            )
    candidates = result.get("poseCycleCandidates")
    if isinstance(candidates, list) and candidates:
        candidate = candidates[0]
        start = optional_float(candidate.get("startSecondsInOriginalSource"))
        end = optional_float(candidate.get("endSecondsInOriginalSource"))
        if start is not None and end is not None and end > start:
            render_video_window_contact_sheet(
                video_path=video_path,
                window=DetectionWindow(index=0, start_seconds=start, end_seconds=end),
                output_dir=exercise_dir / "proposed",
                frame_count=12,
                contact_sheet_frames_per_sheet_override=12,
            )
    pyramid = result.get("exactCyclePyramid")
    best_exact = pyramid.get("bestExactSingleCycleCandidate") if isinstance(pyramid, dict) else None
    if isinstance(best_exact, dict):
        start = optional_float(best_exact.get("startSeconds"))
        end = optional_float(best_exact.get("endSeconds"))
        if start is not None and end is not None and end > start:
            render_video_window_contact_sheet(
                video_path=video_path,
                window=DetectionWindow(index=0, start_seconds=start, end_seconds=end),
                output_dir=exercise_dir / "pyramid_exact",
                frame_count=12,
                contact_sheet_frames_per_sheet_override=12,
            )


def evaluate_selection(workspace: Path) -> dict[str, Any] | None:
    manifest_path = workspace / "selected" / "selection_manifest.json"
    if not manifest_path.exists():
        return None
    manifest = load_json(manifest_path)
    selected_results = manifest.get("selectedResults")
    if not isinstance(selected_results, list) or not selected_results or not isinstance(selected_results[0], dict):
        return None
    selected = selected_results[0]
    exercise_name = str(selected.get("exerciseName") or "")
    candidate = selected.get("candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    video_id = str(candidate.get("videoId") or "")
    source_candidate = source_pose_candidate(workspace, video_id=video_id)
    span = selected_source_span(selected)
    source_frames: list[dict[str, Any]] = []
    if source_candidate is not None and span is not None:
        source_frames = source_pose_frames(source_candidate, start_seconds=span[0], end_seconds=span[1])
    parent_span = source_window_span(selected)
    parent_source_frames: list[dict[str, Any]] = []
    if source_candidate is not None and parent_span is not None:
        parent_source_frames = source_pose_frames(
            source_candidate,
            start_seconds=parent_span[0],
            end_seconds=parent_span[1],
        )
    cycle_candidates = pose_cycle_candidates(parent_source_frames)
    if parent_span is not None:
        for cycle_candidate in cycle_candidates:
            cycle_candidate["startSecondsInOriginalSource"] = parent_span[0] + float(cycle_candidate["startSeconds"])
            cycle_candidate["endSecondsInOriginalSource"] = parent_span[0] + float(cycle_candidate["endSeconds"])
    candidate_workspace = Path(str(selected.get("candidateWorkspace") or ""))
    raw_path = candidate_workspace / "raw" / "motion.raw.json"
    raw_frames = motion_frames(load_json(raw_path)) if raw_path.exists() else []
    final_path_value = selected.get("selectedWearSkeletonPath") or selected.get("skeletonPath")
    final_path = Path(str(final_path_value)) if final_path_value else None
    final_frames = motion_frames(load_json(final_path)) if final_path is not None and final_path.exists() else []
    return {
        "exerciseName": exercise_name,
        "auditLabel": AUDIT_LABELS.get(exercise_name, "unlabeled"),
        "workspace": str(workspace),
        "sourceSpan": list(span) if span is not None else None,
        "sourceToRaw": source_to_raw_metrics(source_frames, raw_frames),
        "rawToFinal": raw_to_final_metrics(raw_frames, final_frames),
        "cut": cycle_count_from_segment_manifest(candidate_workspace),
        "exactCyclePyramid": exact_cycle_pyramid_audit(
            candidate_workspace=candidate_workspace,
            source_candidate=source_candidate,
        ),
        "poseCycleCandidates": cycle_candidates,
    }


def compact_float(value: Any) -> str:
    parsed = optional_float(value)
    return "-" if parsed is None else f"{parsed:.3f}"


def main() -> int:
    args = parse_args()
    workspace_root = args.workspace_root.resolve()
    results = [
        result
        for workspace in sorted(path for path in workspace_root.iterdir() if path.is_dir())
        if (result := evaluate_selection(workspace)) is not None
        and result["auditLabel"] != "unlabeled"
    ]
    if args.render_cut_audit_dir is not None:
        audit_root = args.render_cut_audit_dir.resolve()
        for result in results:
            render_cut_audit(result, audit_root)
    if args.json:
        print(json.dumps({"workspaceRoot": str(workspace_root), "results": results}, indent=2))
        return 0
    print(
        "exercise|label|srcCoverage|srcJointP90|srcAngleP90|postMedian|postP90|cutCycles|cutOverride|pyramidExact|poseCut"
    )
    for result in results:
        source = result["sourceToRaw"]
        final = result["rawToFinal"]
        cut = result["cut"]
        print(
            "|".join(
                [
                    result["exerciseName"],
                    result["auditLabel"],
                    compact_float(source.get("jointObservationCoverage")),
                    compact_float(source.get("p90JointErrorBodyRatio")),
                    compact_float(source.get("p90JointAngleErrorDegrees")),
                    compact_float(final.get("medianAngleTrajectoryRmseDegrees")),
                    compact_float(final.get("p90AngleTrajectoryRmseDegrees")),
                    str(cut.get("cycleCount", "-")),
                    str(bool(cut.get("poseFailureOverriddenByVlm", False))),
                    str(result["exactCyclePyramid"].get("exactSingleCycleCandidateCount", "-")),
                    (
                        f"{result['poseCycleCandidates'][0]['startSecondsInOriginalSource']:.2f}-"
                        f"{result['poseCycleCandidates'][0]['endSecondsInOriginalSource']:.2f}"
                        if result["poseCycleCandidates"]
                        else "-"
                    ),
                ]
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
