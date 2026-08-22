"""Align WHAM camera-space motion to a video-derived floor plane and body pose."""

from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from exercise_motion_pkg.ground import PlaneEstimate
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.unidepth_runner import (
    DepthFrameSample,
    infer_depth_samples_for_video,
    is_unidepth_runtime_available,
)

VIDEO_WORLD_ALIGNMENT_ENV_VAR = "EXERCISE_MOTION_VIDEO_WORLD_ALIGNMENT"
ALIGNMENT_JOINTS = (
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_shoulder",
    "right_shoulder",
)
FLOOR_DISTANCE_JOINTS = (
    *ALIGNMENT_JOINTS,
    "pelvis",
    "left_wrist",
    "right_wrist",
    "left_hand",
    "right_hand",
)
MIN_CORRESPONDENCES = 4
MAX_ALIGNMENT_RMS_METERS = 0.35
MIN_PITCH_JOINTS = 2
MIN_PLANE_INLIERS = 40
PLANE_RANSAC_ITERATIONS = 128
PLANE_RANSAC_THRESHOLD_METERS = 0.04
FLOOR_BOTTOM_FRACTION = 0.30
SUPPORT_NEIGHBORHOOD_RADIUS = 2
GENERIC_SUPPORT_DISTANCE_TOLERANCE_METERS = 0.14
GENERIC_SUPPORT_JOINT_GROUPS = (
    ("left_ankle", "left_foot"),
    ("right_ankle", "right_foot"),
    ("left_knee",),
    ("right_knee",),
    ("left_wrist", "left_hand"),
    ("right_wrist", "right_hand"),
    ("left_hip",),
    ("right_hip",),
    ("pelvis",),
    ("left_shoulder",),
    ("right_shoulder",),
)
GENERIC_BILATERAL_SUPPORT_FAMILIES = (
    (("left_ankle", "left_foot"), ("right_ankle", "right_foot")),
    (("left_knee",), ("right_knee",)),
    (("left_wrist", "left_hand"), ("right_wrist", "right_hand")),
    (("left_hip",), ("right_hip",)),
    (("left_shoulder",), ("right_shoulder",)),
)


@dataclass(frozen=True)
class VideoWorldAlignmentResult:
    clip: MotionClip
    applied: bool
    reason: str
    confidence: float
    camera_ground_plane: PlaneEstimate | None
    correspondence_rms_error: float | None
    frames_used: int
    sample_frame_seconds: list[float]
    model_name: str | None
    metadata: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        payload = dict(self.metadata)
        payload.update(
            {
                "applied": self.applied,
                "reason": self.reason,
                "confidence": round(self.confidence, 4),
                "correspondenceRmsError": self.correspondence_rms_error,
                "framesUsed": self.frames_used,
                "sampleFrameSeconds": [round(value, 4) for value in self.sample_frame_seconds],
                "modelName": self.model_name,
            }
        )
        if self.camera_ground_plane is not None:
            payload["cameraGroundPlane"] = {
                "space": "camera",
                "normal": list(self.camera_ground_plane.normal),
                "offset": self.camera_ground_plane.offset,
                "rmsError": self.camera_ground_plane.rms_error,
            }
        return payload


def video_world_alignment_enabled() -> bool:
    raw = os.environ.get(VIDEO_WORLD_ALIGNMENT_ENV_VAR, "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def video_world_alignment_rms_is_acceptable(rms_error: float) -> bool:
    return math.isfinite(rms_error) and rms_error <= MAX_ALIGNMENT_RMS_METERS


def support_joint_names_for_mode(support_mode_hint: str | None) -> tuple[str, ...]:
    mode = str(support_mode_hint or "unknown").strip().casefold()
    if mode == "kneeling":
        return ("left_knee", "right_knee")
    if mode == "quadruped":
        return ("left_hand", "right_hand", "left_knee", "right_knee")
    return ("left_ankle", "right_ankle", "left_foot", "right_foot")


def discover_source_pose_reference_path(pipeline_root: Path) -> Path | None:
    direct = pipeline_root / "segment_detection" / "exact_source_pose_reference.json"
    if direct.is_file():
        return direct
    confirmation_root = (
        pipeline_root
        / "segment_detection"
        / "pre_wham_source_candidates"
        / "deterministic_confirmation"
    )
    if confirmation_root.is_dir():
        matches = sorted(confirmation_root.glob("*/exact_source_pose_reference.json"))
        if matches:
            return matches[-1]
    return None


def load_source_pose_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    pose = payload.get("pose")
    if isinstance(pose, dict):
        return pose
    if isinstance(payload.get("frames"), list):
        return payload
    samples = payload.get("dominantPoseSamples")
    if isinstance(samples, list):
        return {
            "frames": [
                {
                    "sourceTimeSec": float(sample.get("timeSeconds", 0.0)),
                    "joints": sample.get("keypoints", {}),
                }
                for sample in samples
                if isinstance(sample, dict)
            ],
            "coordinateSpace": payload.get(
                "dominantPoseSampleCoordinateSpace",
                "normalized_image_xy",
            ),
        }
    return None


def align_motion_clip_to_video(
    clip: MotionClip,
    *,
    video_path: Path,
    source_pose_payload: dict[str, Any] | None = None,
    support_mode_hint: str | None = None,
    max_depth_samples: int = 5,
) -> VideoWorldAlignmentResult:
    """Rotate and translate WHAM motion into a video-grounded camera frame."""
    if not video_world_alignment_enabled():
        return _empty_alignment_result(clip, reason="video_world_alignment_disabled")
    if not is_unidepth_runtime_available():
        return _empty_alignment_result(clip, reason="unidepth_runtime_unavailable")
    if not video_path.is_file():
        return _empty_alignment_result(clip, reason="source_video_missing")
    if not clip.frames:
        return _empty_alignment_result(clip, reason="empty_motion_clip")
    if source_pose_payload is None:
        return _empty_alignment_result(clip, reason="source_pose_reference_missing")

    depth_samples = infer_depth_samples_for_video(
        video_path=video_path,
        sample_times_seconds=_motion_aligned_sample_times(clip, max_samples=max_depth_samples),
        max_samples=max_depth_samples,
    )
    if not depth_samples:
        return _empty_alignment_result(clip, reason="unidepth_inference_failed")

    floor_planes = [
        estimate_camera_floor_plane(
            sample,
            support_mode_hint=support_mode_hint,
            pose_payload=source_pose_payload,
        )
        for sample in depth_samples
    ]
    floor_planes = [plane for plane in floor_planes if plane is not None]
    if not floor_planes:
        return _empty_alignment_result(clip, reason="camera_floor_plane_unavailable")

    camera_plane = _median_plane(floor_planes)
    video_distance_samples = _collect_video_floor_distance_samples(
        depth_samples,
        pose_payload=source_pose_payload,
        plane=camera_plane,
    )
    video_distance_observations = _collect_video_floor_distance_observations(
        depth_samples,
        pose_payload=source_pose_payload,
        plane=camera_plane,
    )
    video_distances = {
        name: float(np.median(values))
        for name, values in video_distance_samples.items()
        if values
    }
    if len(video_distances) < MIN_PITCH_JOINTS + 1:
        return _empty_alignment_result(clip, reason="insufficient_video_floor_distances")
    camera_plane, video_distances = _orient_plane_with_body_above(
        camera_plane,
        video_distances,
    )
    video_distances = regularize_impossible_bilateral_floor_distances(
        video_distances
    )

    alignment_time = depth_samples[len(depth_samples) // 2].time_seconds
    motion_frame = min(clip.frames, key=lambda frame: abs(frame.time_sec - alignment_time))
    inferred_support_joint_names = infer_support_joint_names_from_floor_distances(
        motion_frame.joints,
        video_distances=video_distances,
    )
    if len(inferred_support_joint_names) < 2:
        return _empty_alignment_result(
            clip,
            reason="insufficient_inferred_floor_contacts",
            extra={
                "videoFloorDistances": {
                    name: round(value, 4) for name, value in video_distances.items()
                },
            },
        )
    orientation_constraint_joint_names = infer_orientation_constraint_joint_names(
        motion_frame.joints,
        video_distances=video_distances,
        distance_samples=video_distance_samples,
        floor_contact_joint_names=inferred_support_joint_names,
    )
    support_offset = float(np.median([
        video_distances[name]
        for name in inferred_support_joint_names
        if name in video_distances
    ]))
    normalized_video_distances = {
        name: distance - support_offset
        for name, distance in video_distances.items()
    }
    normalized_video_distance_observations: dict[str, list[dict[str, float]]] = {}
    for joint_name, observations in video_distance_observations.items():
        normalized: list[dict[str, float]] = []
        for time_sec, distance in observations:
            normalized.append(
                {
                    "timeSeconds": float(time_sec),
                    "distance": float(distance - support_offset),
                }
            )
        if normalized:
            normalized_video_distance_observations[joint_name] = normalized
    solved = solve_floor_distance_rigid_transform(
        motion_frame.joints,
        video_distances=normalized_video_distances,
        plane=camera_plane,
        support_joint_names=orientation_constraint_joint_names,
    )
    if solved is None:
        return _empty_alignment_result(clip, reason="floor_distance_transform_unavailable")
    rotation, translation, rms_error = solved
    if not video_world_alignment_rms_is_acceptable(rms_error):
        return _empty_alignment_result(
            clip,
            reason="video_floor_distance_rms_too_high",
            extra={
                "correspondenceRmsError": round(rms_error, 4),
                "videoFloorDistances": {
                    name: round(value, 4) for name, value in normalized_video_distances.items()
                },
            },
        )

    aligned_clip = apply_rigid_transform_to_clip(clip, rotation=rotation, translation=translation)
    confidence = _alignment_confidence(
        correspondence_count=len(video_distances),
        rms_error=rms_error,
        plane=camera_plane,
        max_rms=MAX_ALIGNMENT_RMS_METERS,
    )
    metadata = {
        "policy": "tier2_unidepth_floor_distance_pitch",
        "alignmentTimeSeconds": round(alignment_time, 4),
        "correspondenceJointNames": sorted(video_distances),
        "videoFloorDistances": {
            name: round(value, 4) for name, value in sorted(normalized_video_distances.items())
        },
        "inferredSupportJointNames": list(inferred_support_joint_names),
        "orientationConstraintJointNames": list(
            orientation_constraint_joint_names
        ),
        "videoFloorDistanceObservations": normalized_video_distance_observations,
        "rotationMatrix": rotation.tolist(),
        "translation": translation.tolist(),
        "cameraGroundPlane": {
            "space": "camera",
            "normal": list(camera_plane.normal),
            "offset": camera_plane.offset,
            "rmsError": camera_plane.rms_error,
        },
        "supportModeHint": support_mode_hint,
        "applied": True,
    }
    aligned_clip = replace(
        aligned_clip,
        metadata={
            **aligned_clip.metadata,
            "videoWorldAlignment": metadata,
        },
    )
    return VideoWorldAlignmentResult(
        clip=aligned_clip,
        applied=True,
        reason="video_floor_distance_pitch_applied",
        confidence=confidence,
        camera_ground_plane=camera_plane,
        correspondence_rms_error=rms_error,
        frames_used=len(depth_samples),
        sample_frame_seconds=[sample.time_seconds for sample in depth_samples],
        model_name=depth_samples[0].model_name,
        metadata=metadata,
    )


def estimate_camera_floor_plane(
    depth_sample: DepthFrameSample,
    *,
    support_mode_hint: str | None,
    pose_payload: dict[str, Any],
) -> PlaneEstimate | None:
    points = depth_sample.points
    height, width = points.shape[:2]
    candidates = _collect_floor_candidate_points(points, height=height, width=width)
    support_points = _support_neighborhood_points(
        depth_sample,
        pose_payload=pose_payload,
        support_mode_hint=support_mode_hint,
    )
    merged = candidates + support_points
    if len(merged) < MIN_PLANE_INLIERS:
        return None
    return fit_plane_ransac(np.asarray(merged, dtype=np.float64))


def fit_plane_ransac(
    points: np.ndarray,
    *,
    iterations: int = PLANE_RANSAC_ITERATIONS,
    threshold: float = PLANE_RANSAC_THRESHOLD_METERS,
    rng_seed: int = 0,
) -> PlaneEstimate | None:
    if points.shape[0] < 3:
        return None
    rng = random.Random(rng_seed)
    best_inliers: list[np.ndarray] = []
    best_plane: tuple[np.ndarray, float] | None = None
    for _ in range(iterations):
        indices = rng.sample(range(points.shape[0]), 3)
        sample = points[indices, :]
        plane = _plane_from_three_points(sample[0], sample[1], sample[2])
        if plane is None:
            continue
        normal, offset = plane
        distances = np.abs(points @ normal + offset)
        inlier_mask = distances <= threshold
        inliers = points[inlier_mask]
        if len(inliers) > len(best_inliers):
            best_inliers = [row for row in inliers]
            best_plane = (normal, offset)
    if best_plane is None or len(best_inliers) < 3:
        return None
    refined = fit_plane_least_squares(np.asarray(best_inliers, dtype=np.float64))
    if refined is None:
        return None
    normal, offset = refined
    distances = np.abs(points @ normal + offset)
    inlier_distances = distances[distances <= threshold]
    rms = float(np.sqrt(np.mean(np.square(inlier_distances)))) if len(inlier_distances) else None
    return PlaneEstimate(
        normal=(float(normal[0]), float(normal[1]), float(normal[2])),
        offset=float(offset),
        rms_error=rms,
    )


def fit_plane_least_squares(points: np.ndarray) -> tuple[np.ndarray, float] | None:
    if points.shape[0] < 3:
        return None
    centroid = np.mean(points, axis=0)
    centered = points - centroid
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[-1, :]
    norm = np.linalg.norm(normal)
    if norm <= 1e-8:
        return None
    normal = normal / norm
    if normal[1] > 0.0:
        normal = -normal
    offset = -float(np.dot(normal, centroid))
    return normal, offset


def solve_rigid_transform_kabsch(
    source_points: list[tuple[float, float, float]],
    target_points: list[tuple[float, float, float]],
) -> tuple[np.ndarray, np.ndarray]:
    source = np.asarray(source_points, dtype=np.float64)
    target = np.asarray(target_points, dtype=np.float64)
    source_centroid = np.mean(source, axis=0)
    target_centroid = np.mean(target, axis=0)
    source_centered = source - source_centroid
    target_centered = target - target_centroid
    covariance = source_centered.T @ target_centered
    u, _, vt = np.linalg.svd(covariance)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0.0:
        vt[-1, :] *= -1.0
        rotation = vt.T @ u.T
    translation = target_centroid - rotation @ source_centroid
    return rotation, translation


def apply_rigid_transform_to_clip(
    clip: MotionClip,
    *,
    rotation: np.ndarray,
    translation: np.ndarray,
) -> MotionClip:
    transformed_frames: list[MotionFrame] = []
    for frame in clip.frames:
        transformed_joints = {}
        for joint_name, point in frame.joints.items():
            vector = np.asarray(point, dtype=np.float64)
            aligned = (rotation @ vector) + translation
            transformed_joints[joint_name] = (
                float(aligned[0]),
                float(aligned[1]),
                float(aligned[2]),
            )
        transformed_frames.append(
            MotionFrame(time_sec=frame.time_sec, joints=transformed_joints)
        )
    return replace(clip, frames=transformed_frames)


def plane_signed_distance(
    plane: PlaneEstimate,
    point: tuple[float, float, float] | np.ndarray,
) -> float:
    normal = np.asarray(plane.normal, dtype=np.float64)
    vector = np.asarray(point, dtype=np.float64)
    return float(np.dot(normal, vector) + plane.offset)


def collect_video_floor_distances(
    depth_samples: list[DepthFrameSample],
    *,
    pose_payload: dict[str, Any],
    plane: PlaneEstimate,
    support_mode_hint: str | None,
) -> dict[str, float]:
    collected = _collect_video_floor_distance_samples(
        depth_samples,
        pose_payload=pose_payload,
        plane=plane,
    )
    return {
        name: float(np.median(values))
        for name, values in collected.items()
        if values
    }


def _collect_video_floor_distance_samples(
    depth_samples: list[DepthFrameSample],
    *,
    pose_payload: dict[str, Any],
    plane: PlaneEstimate,
) -> dict[str, list[float]]:
    collected: dict[str, list[float]] = {}
    for sample in depth_samples:
        pose_frame = _nearest_pose_frame(pose_payload, sample.time_seconds)
        if pose_frame is None:
            continue
        joints = pose_frame.get("joints")
        if not isinstance(joints, dict):
            continue
        coordinate_space = str(
            pose_payload.get("coordinateSpace")
            or pose_payload.get("coordinate_space")
            or "normalized_image_xy"
        )
        for joint_name in FLOOR_DISTANCE_JOINTS:
            pixel = _normalized_keypoint_to_pixel(
                joints.get(joint_name),
                width=sample.width,
                height=sample.height,
                coordinate_space=coordinate_space,
                source_width=sample.source_width,
                source_height=sample.source_height,
            )
            if pixel is None:
                continue
            camera_point = _median_neighborhood_point(
                sample,
                pixel_x=pixel[0],
                pixel_y=pixel[1],
            )
            if camera_point is None:
                continue
            collected.setdefault(joint_name, []).append(
                plane_signed_distance(plane, camera_point)
            )
    return collected


def _collect_video_floor_distance_observations(
    depth_samples: list[DepthFrameSample],
    *,
    pose_payload: dict[str, Any],
    plane: PlaneEstimate,
) -> dict[str, list[tuple[float, float]]]:
    """Collect timestamped signed distances from joints to the camera floor plane."""
    collected: dict[str, list[tuple[float, float]]] = {}

    for sample in depth_samples:
        pose_frame = _nearest_pose_frame(pose_payload, sample.time_seconds)
        if pose_frame is None:
            continue
        joints = pose_frame.get("joints")
        if not isinstance(joints, dict):
            continue
        coordinate_space = str(
            pose_payload.get("coordinateSpace")
            or pose_payload.get("coordinate_space")
            or "normalized_image_xy"
        )
        for joint_name in FLOOR_DISTANCE_JOINTS:
            pixel = _normalized_keypoint_to_pixel(
                joints.get(joint_name),
                width=sample.width,
                height=sample.height,
                coordinate_space=coordinate_space,
                source_width=sample.source_width,
                source_height=sample.source_height,
            )
            if pixel is None:
                continue
            camera_point = _median_neighborhood_point(
                sample,
                pixel_x=pixel[0],
                pixel_y=pixel[1],
            )
            if camera_point is None:
                continue
            distance = plane_signed_distance(plane, camera_point)
            collected.setdefault(joint_name, []).append(
                (float(sample.time_seconds), float(distance))
            )

    # Robust outlier filtering per joint (depth noise can produce extreme values).
    for joint_name, observations in list(collected.items()):
        if len(observations) <= 2:
            continue
        distances = np.asarray([distance for _t, distance in observations], dtype=np.float64)
        median = float(np.median(distances))
        abs_dev = np.abs(distances - median)
        mad = float(np.median(abs_dev)) + 1e-8
        # Conservative: keep points within either 3.5*MAD or 0.05m.
        threshold = 3.5 * mad + 0.05
        collected[joint_name] = [
            (t, distance)
            for (t, distance) in observations
            if abs(distance - median) <= threshold
        ]

    return collected


def _orient_plane_with_body_above(
    plane: PlaneEstimate,
    distances: dict[str, float],
) -> tuple[PlaneEstimate, dict[str, float]]:
    torso_values = [
        distances[name]
        for name in (
            "pelvis",
            "left_hip",
            "right_hip",
            "left_shoulder",
            "right_shoulder",
        )
        if name in distances
    ]
    if not torso_values or float(np.median(torso_values)) >= 0.0:
        return plane, distances
    flipped = PlaneEstimate(
        normal=(-plane.normal[0], -plane.normal[1], -plane.normal[2]),
        offset=-plane.offset,
        rms_error=plane.rms_error,
    )
    return flipped, {name: -value for name, value in distances.items()}


def infer_support_joint_names_from_floor_distances(
    source_joints: dict[str, tuple[float, float, float]],
    *,
    video_distances: dict[str, float],
) -> tuple[str, ...]:
    """Infer physical contacts from measured floor proximity, not exercise type."""
    families: list[tuple[tuple[str, str], float]] = []
    for left_group, right_group in GENERIC_BILATERAL_SUPPORT_FAMILIES:
        left_available = [
            name for name in left_group if name in source_joints and name in video_distances
        ]
        right_available = [
            name for name in right_group if name in source_joints and name in video_distances
        ]
        if not left_available or not right_available:
            continue
        left = min(left_available, key=lambda name: abs(video_distances[name]))
        right = min(right_available, key=lambda name: abs(video_distances[name]))
        signed_distances = (video_distances[left], video_distances[right])
        bilateral_disagreement = abs(signed_distances[0] - signed_distances[1])
        score = float(np.median(signed_distances)) + bilateral_disagreement
        families.append(((left, right), score))

    if families:
        best_score = min(score for _names, score in families)
        selected = [
            names
            for names, score in families
            if score <= best_score + 0.05
        ]
        inferred = tuple(name for names in selected for name in names)
        if len(inferred) >= 2:
            return inferred

    representatives = [
        (
            min(available, key=lambda name: abs(video_distances[name])),
            min(abs(video_distances[name]) for name in available),
        )
        for group in GENERIC_SUPPORT_JOINT_GROUPS
        if (available := [
            name for name in group if name in source_joints and name in video_distances
        ])
    ]
    return tuple(name for name, _distance in sorted(representatives, key=lambda item: item[1])[:2])


def regularize_impossible_bilateral_floor_distances(
    video_distances: dict[str, float],
) -> dict[str, float]:
    regularized = dict(video_distances)
    for base_name in ("ankle", "knee", "hip", "wrist", "shoulder"):
        left_name = f"left_{base_name}"
        right_name = f"right_{base_name}"
        if left_name not in regularized or right_name not in regularized:
            continue
        left_distance = regularized[left_name]
        right_distance = regularized[right_name]
        lower_distance = min(left_distance, right_distance)
        higher_distance = max(left_distance, right_distance)
        if lower_distance >= -GENERIC_SUPPORT_DISTANCE_TOLERANCE_METERS:
            continue
        if higher_distance < 0.0:
            continue
        if abs(left_distance - right_distance) < 0.20:
            continue
        if left_distance < right_distance:
            regularized[left_name] = right_distance
        else:
            regularized[right_name] = left_distance
    return regularized


def infer_orientation_constraint_joint_names(
    source_joints: dict[str, tuple[float, float, float]],
    *,
    video_distances: dict[str, float],
    distance_samples: dict[str, list[float]],
    floor_contact_joint_names: tuple[str, ...],
) -> tuple[str, ...]:
    constraints = list(floor_contact_joint_names)
    elevated_support_pairs = (
        ("left_wrist", "right_wrist"),
        ("left_hand", "right_hand"),
    )
    for left_name, right_name in elevated_support_pairs:
        if left_name not in source_joints or right_name not in source_joints:
            continue
        if left_name not in video_distances or right_name not in video_distances:
            continue
        left_samples = distance_samples.get(left_name, [])
        right_samples = distance_samples.get(right_name, [])
        if len(left_samples) < 3 or len(right_samples) < 3:
            continue
        spreads = (
            float(np.percentile(left_samples, 75) - np.percentile(left_samples, 25)),
            float(np.percentile(right_samples, 75) - np.percentile(right_samples, 25)),
        )
        if max(spreads) > 0.08:
            continue
        heights = (video_distances[left_name], video_distances[right_name])
        if min(heights) < -GENERIC_SUPPORT_DISTANCE_TOLERANCE_METERS:
            continue
        if max(heights) > 0.35 or abs(heights[0] - heights[1]) > 0.08:
            continue
        constraints.extend((left_name, right_name))
        break
    return tuple(dict.fromkeys(constraints))


def solve_floor_distance_rigid_transform(
    source_joints: dict[str, tuple[float, float, float]],
    *,
    video_distances: dict[str, float],
    plane: PlaneEstimate,
    support_joint_names: tuple[str, ...],
) -> tuple[np.ndarray, np.ndarray, float] | None:
    correspondences = [
        (name, np.asarray(source_joints[name], dtype=np.float64), float(distance))
        for name, distance in video_distances.items()
        if name in source_joints
    ]
    if len(correspondences) < MIN_PITCH_JOINTS + 1:
        return None

    points = np.stack([point for _name, point, _distance in correspondences], axis=0)
    targets = np.asarray([distance for _name, _point, distance in correspondences], dtype=np.float64)
    weights = np.asarray([
        2.0 if name in support_joint_names else 1.0
        for name, _point, _distance in correspondences
    ], dtype=np.float64)
    weight_sum = float(np.sum(weights))
    centroid = np.sum(points * weights[:, None], axis=0) / max(weight_sum, 1e-8)
    target_center = float(np.sum(targets * weights) / max(weight_sum, 1e-8))
    design = (points - centroid) * np.sqrt(weights)[:, None]
    observed = (targets - target_center) * np.sqrt(weights)
    try:
        source_up, *_ = np.linalg.lstsq(design, observed, rcond=None)
    except np.linalg.LinAlgError:
        return None
    source_up = _unit(source_up)
    if source_up is None:
        return None

    normal = np.asarray(plane.normal, dtype=np.float64)
    rotation = rotation_between_vectors(source_up, normal)
    transformed_heights = np.asarray([
        plane_signed_distance(plane, rotation @ point)
        for _name, point, _distance in correspondences
    ])
    translation_along_normal = float(np.median(targets - transformed_heights))
    translation = normal * translation_along_normal

    residuals: list[float] = []
    for joint_name, target_distance in video_distances.items():
        point = source_joints.get(joint_name)
        if point is None:
            continue
        transformed = rotation @ np.asarray(point, dtype=np.float64) + translation
        residuals.append(plane_signed_distance(plane, transformed) - target_distance)
    if not residuals:
        return None
    rms_error = math.sqrt(sum(value * value for value in residuals) / len(residuals))
    return rotation, translation, rms_error


def rotation_between_vectors(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    source_unit = _unit(source)
    target_unit = _unit(target)
    if source_unit is None or target_unit is None:
        return np.eye(3)
    cosine = float(np.clip(np.dot(source_unit, target_unit), -1.0, 1.0))
    axis = np.cross(source_unit, target_unit)
    sine = float(np.linalg.norm(axis))
    if sine <= 1e-8:
        if cosine > 0.0:
            return np.eye(3)
        fallback = np.cross(source_unit, np.array([1.0, 0.0, 0.0], dtype=np.float64))
        if float(np.linalg.norm(fallback)) <= 1e-8:
            fallback = np.cross(source_unit, np.array([0.0, 0.0, 1.0], dtype=np.float64))
        return rotation_around_axis(_unit(fallback) or np.array([1.0, 0.0, 0.0]), math.pi)
    skew = _skew_symmetric(axis)
    return np.eye(3) + skew + (skew @ skew) * ((1.0 - cosine) / (sine * sine))


def rotation_around_axis(axis: np.ndarray, radians: float) -> np.ndarray:
    unit = _unit(axis)
    if unit is None:
        return np.eye(3)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    skew = _skew_symmetric(unit)
    return (cosine * np.eye(3)) + (sine * skew) + ((1.0 - cosine) * np.outer(unit, unit))


def _support_axis(points: list[np.ndarray]) -> np.ndarray | None:
    if len(points) >= 2:
        axis = points[-1] - points[0]
        unit = _unit(axis)
        if unit is not None:
            return unit
    stacked = np.stack(points, axis=0)
    centered = stacked - np.mean(stacked, axis=0)
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    return _unit(vh[0])


def _unit(vector: np.ndarray) -> np.ndarray | None:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-8:
        return None
    return vector / norm


def _skew_symmetric(vector: np.ndarray) -> np.ndarray:
    x, y, z = (float(vector[0]), float(vector[1]), float(vector[2]))
    return np.array(
        [
            [0.0, -z, y],
            [z, 0.0, -x],
            [-y, x, 0.0],
        ],
        dtype=np.float64,
    )


def _closest_plane_point_in_neighborhood(
    depth_sample: DepthFrameSample,
    *,
    plane: PlaneEstimate,
    pixel_x: float,
    pixel_y: float,
    radius: int = 2,
) -> tuple[float, float, float] | None:
    best_point = None
    best_distance = float("inf")
    for row_offset in range(-radius, radius + 1):
        for column_offset in range(-radius, radius + 1):
            point = _camera_point_from_depth_sample(
                depth_sample,
                pixel_x=pixel_x + column_offset,
                pixel_y=pixel_y + row_offset,
            )
            if point is None:
                continue
            distance = abs(plane_signed_distance(plane, point))
            if distance < best_distance:
                best_distance = distance
                best_point = point
    return best_point


def _median_neighborhood_point(
    depth_sample: DepthFrameSample,
    *,
    pixel_x: float,
    pixel_y: float,
    radius: int = 1,
) -> tuple[float, float, float] | None:
    points: list[tuple[float, float, float]] = []
    for row_offset in range(-radius, radius + 1):
        for column_offset in range(-radius, radius + 1):
            point = _camera_point_from_depth_sample(
                depth_sample,
                pixel_x=pixel_x + column_offset,
                pixel_y=pixel_y + row_offset,
            )
            if point is not None:
                points.append(point)
    if not points:
        return None
    stacked = np.asarray(points, dtype=np.float64)
    median = np.median(stacked, axis=0)
    return float(median[0]), float(median[1]), float(median[2])


def _empty_alignment_result(
    clip: MotionClip,
    *,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> VideoWorldAlignmentResult:
    metadata = {"policy": "tier2_unidepth_floor_distance_pitch", **(extra or {})}
    return VideoWorldAlignmentResult(
        clip=clip,
        applied=False,
        reason=reason,
        confidence=0.0,
        camera_ground_plane=None,
        correspondence_rms_error=None,
        frames_used=0,
        sample_frame_seconds=[],
        model_name=None,
        metadata=metadata,
    )


def _motion_aligned_sample_times(clip: MotionClip, *, max_samples: int) -> list[float]:
    if not clip.frames:
        return []
    start = clip.frames[0].time_sec
    end = clip.frames[-1].time_sec
    duration = max(0.0, end - start)
    if duration <= 1e-6:
        return [start]
    count = max(1, min(max_samples, 5))
    return [start + (duration * (index + 1) / (count + 1)) for index in range(count)]


def _nearest_pose_frame(pose_payload: dict[str, Any], time_seconds: float) -> dict[str, Any] | None:
    frames = pose_payload.get("frames")
    if not isinstance(frames, list) or not frames:
        return None
    best_frame = None
    best_delta = float("inf")
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        frame_time = frame.get("sourceTimeSec", frame.get("timeSeconds"))
        if not isinstance(frame_time, (int, float)):
            continue
        delta = abs(float(frame_time) - time_seconds)
        if delta < best_delta:
            best_delta = delta
            best_frame = frame
    return best_frame


def _nearest_depth_sample(samples: list[DepthFrameSample], time_seconds: float) -> DepthFrameSample | None:
    if not samples:
        return None
    return min(samples, key=lambda sample: abs(sample.time_seconds - time_seconds))


def _normalized_keypoint_to_pixel(
    value: Any,
    *,
    width: int,
    height: int,
    coordinate_space: str,
    source_width: int | None = None,
    source_height: int | None = None,
) -> tuple[float, float] | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    x = float(value[0])
    y = float(value[1])
    if coordinate_space == "normalized_image_xy":
        ref_width = max(1, (source_width or width) - 1)
        ref_height = max(1, (source_height or height) - 1)
        pixel_x = x * ref_width
        pixel_y = y * ref_height
        if source_width is not None and source_height is not None:
            pixel_x *= (width - 1) / max(1, source_width - 1)
            pixel_y *= (height - 1) / max(1, source_height - 1)
        return pixel_x, pixel_y
    return x, y


def _camera_point_from_depth_sample(
    depth_sample: DepthFrameSample,
    *,
    pixel_x: float,
    pixel_y: float,
) -> tuple[float, float, float] | None:
    width = depth_sample.width
    height = depth_sample.height
    column = int(round(min(max(pixel_x, 0.0), width - 1)))
    row = int(round(min(max(pixel_y, 0.0), height - 1)))
    point = depth_sample.points[row, column, :]
    if not np.all(np.isfinite(point)):
        return None
    depth = float(point[2])
    if depth <= 1e-4:
        return None
    return float(point[0]), float(point[1]), float(point[2])


def _video_reference_points(
    pose_frame: dict[str, Any],
    depth_sample: DepthFrameSample,
    *,
    pose_payload: dict[str, Any],
    support_mode_hint: str | None,
) -> tuple[list[tuple[float, float, float]], tuple[str, ...]]:
    joints = pose_frame.get("joints")
    if not isinstance(joints, dict):
        return [], ()
    coordinate_space = str(
        pose_payload.get("coordinateSpace")
        or pose_payload.get("coordinate_space")
        or "normalized_image_xy"
    )
    preferred = list(ALIGNMENT_JOINTS)
    for joint_name in support_joint_names_for_mode(support_mode_hint):
        if joint_name not in preferred:
            preferred.insert(0, joint_name)

    target_points: list[tuple[float, float, float]] = []
    used_names: list[str] = []
    for joint_name in preferred:
        pixel = _normalized_keypoint_to_pixel(
            joints.get(joint_name),
            width=depth_sample.width,
            height=depth_sample.height,
            coordinate_space=coordinate_space,
            source_width=depth_sample.source_width,
            source_height=depth_sample.source_height,
        )
        if pixel is None:
            continue
        camera_point = _camera_point_from_depth_sample(
            depth_sample,
            pixel_x=pixel[0],
            pixel_y=pixel[1],
        )
        if camera_point is None:
            continue
        target_points.append(camera_point)
        used_names.append(joint_name)
    return target_points, tuple(used_names)


def _motion_reference_points(
    clip: MotionClip,
    time_seconds: float,
    joint_names: Iterable[str],
) -> list[tuple[float, float, float]]:
    frame = min(clip.frames, key=lambda item: abs(item.time_sec - time_seconds))
    points: list[tuple[float, float, float]] = []
    for joint_name in joint_names:
        point = frame.joints.get(joint_name)
        if point is None:
            continue
        points.append((float(point[0]), float(point[1]), float(point[2])))
    return points


def _collect_floor_candidate_points(
    points: np.ndarray,
    *,
    height: int,
    width: int,
) -> list[tuple[float, float, float]]:
    start_row = int(height * (1.0 - FLOOR_BOTTOM_FRACTION))
    stride = max(4, width // 48)
    candidates: list[tuple[float, float, float]] = []
    for row in range(start_row, height, stride):
        for column in range(0, width, stride):
            point = points[row, column, :]
            if not np.all(np.isfinite(point)):
                continue
            depth = float(point[2])
            if depth <= 0.05 or depth > 12.0:
                continue
            candidates.append((float(point[0]), float(point[1]), float(point[2])))
    return candidates


def _support_neighborhood_points(
    depth_sample: DepthFrameSample,
    *,
    pose_payload: dict[str, Any],
    support_mode_hint: str | None,
) -> list[tuple[float, float, float]]:
    pose_frame = _nearest_pose_frame(pose_payload, depth_sample.time_seconds)
    if pose_frame is None:
        return []
    joints = pose_frame.get("joints")
    if not isinstance(joints, dict):
        return []
    coordinate_space = str(
        pose_payload.get("coordinateSpace")
        or pose_payload.get("coordinate_space")
        or "normalized_image_xy"
    )
    collected: list[tuple[float, float, float]] = []
    for joint_name in support_joint_names_for_mode(support_mode_hint):
        pixel = _normalized_keypoint_to_pixel(
            joints.get(joint_name),
            width=depth_sample.width,
            height=depth_sample.height,
            coordinate_space=coordinate_space,
            source_width=depth_sample.source_width,
            source_height=depth_sample.source_height,
        )
        if pixel is None:
            continue
        for row_offset in range(-SUPPORT_NEIGHBORHOOD_RADIUS, SUPPORT_NEIGHBORHOOD_RADIUS + 1):
            for column_offset in range(-SUPPORT_NEIGHBORHOOD_RADIUS, SUPPORT_NEIGHBORHOOD_RADIUS + 1):
                camera_point = _camera_point_from_depth_sample(
                    depth_sample,
                    pixel_x=pixel[0] + column_offset,
                    pixel_y=pixel[1] + row_offset,
                )
                if camera_point is not None:
                    collected.append(camera_point)
    return collected


def _plane_from_three_points(
    first: np.ndarray,
    second: np.ndarray,
    third: np.ndarray,
) -> tuple[np.ndarray, float] | None:
    normal = np.cross(second - first, third - first)
    norm = np.linalg.norm(normal)
    if norm <= 1e-8:
        return None
    normal = normal / norm
    if normal[1] > 0.0:
        normal = -normal
    offset = -float(np.dot(normal, first))
    return normal, offset


def _median_plane(planes: list[PlaneEstimate]) -> PlaneEstimate:
    normals = np.asarray([plane.normal for plane in planes], dtype=np.float64)
    offsets = [plane.offset for plane in planes]
    mean_normal = np.mean(normals, axis=0)
    norm = np.linalg.norm(mean_normal)
    if norm <= 1e-8:
        mean_normal = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    else:
        mean_normal = mean_normal / norm
        if mean_normal[1] > 0.0:
            mean_normal = -mean_normal
    rms_values = [plane.rms_error for plane in planes if plane.rms_error is not None]
    return PlaneEstimate(
        normal=(float(mean_normal[0]), float(mean_normal[1]), float(mean_normal[2])),
        offset=float(np.median(offsets)),
        rms_error=float(np.median(rms_values)) if rms_values else None,
    )


def _rms_error(
    source_points: list[tuple[float, float, float]],
    target_points: list[tuple[float, float, float]],
    rotation: np.ndarray,
    translation: np.ndarray,
) -> float:
    total = 0.0
    for source, target in zip(source_points, target_points):
        transformed = (rotation @ np.asarray(source, dtype=np.float64)) + translation
        delta = transformed - np.asarray(target, dtype=np.float64)
        total += float(np.dot(delta, delta))
    return math.sqrt(total / max(1, len(source_points)))


def _alignment_confidence(
    *,
    correspondence_count: int,
    rms_error: float,
    plane: PlaneEstimate,
    max_rms: float = MAX_ALIGNMENT_RMS_METERS,
) -> float:
    count_score = min(1.0, correspondence_count / 8.0)
    rms_score = max(0.0, 1.0 - (rms_error / max(max_rms, 1e-6)))
    plane_score = 0.0
    if plane.rms_error is not None:
        plane_score = max(0.0, 1.0 - (plane.rms_error / 0.08))
    return max(0.0, min(1.0, (count_score * 0.45) + (rms_score * 0.40) + (plane_score * 0.15)))
