"""Source-projection-guided depth correction for misplaced distal chains.

Monocular reconstruction can place a whole limb in the wrong camera depth —
typical for supine bodies (bench press) where a lying person's pitch is
ambiguous: proximal joints project correctly while the leg/arm chain extends
into depth and its distal joints land far from their source-2D positions.
The signature is sharp and detectable under the retained camera: distal
error concentrated in one chain, flat over time, root joint clean.

This module detects that signature and re-solves the chain as a rigid
rotation about its root joint, minimizing projected 2D error against the
source pose. Bone lengths and every joint interior to the chain are
preserved exactly; only the chain's camera-depth orientation changes. The
rotation is bounded and the correction is accepted only when it reduces the
distal error decisively without degrading the root; all final gates still
judge the result independently.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import numpy as np

from .models import MotionClip, MotionFrame
from .pose_fidelity import (
    _apply_similarity,
    _bilateral_name,
    _motion_frame_at_time,
    _pose_frames,
)

# (label, root, distal joints)
DISTAL_CHAINS = (
    ("left_leg", "left_hip", ("left_knee", "left_ankle", "left_foot")),
    ("right_leg", "right_hip", ("right_knee", "right_ankle", "right_foot")),
    ("left_arm", "left_shoulder", ("left_elbow", "left_wrist", "left_hand")),
    ("right_arm", "right_shoulder", ("right_elbow", "right_wrist", "right_hand")),
)

# Detection and acceptance, in body-span ratios of projected error.
MIN_DISTAL_ERROR_RATIO = 0.20
DISTAL_OVER_ROOT_FACTOR = 2.0
MAX_ROOT_ERROR_RATIO = 0.20
MIN_RELATIVE_IMPROVEMENT = 0.4
MAX_ACCEPTED_DISTAL_ERROR_RATIO = 0.25

MAX_ROTATION_RADIANS = math.radians(75.0)
GRID_STEP_RADIANS = math.radians(15.0)
REFINEMENT_STEPS_RADIANS = (math.radians(3.0), math.radians(0.5))
# Monocular projection cannot see the chain's depth component, so several
# rotations fit the image equally well. Prefer the smallest correction: it is
# the least intervention and, for a single wrong pitch, the true one.
MINIMAL_ROTATION_PENALTY = 0.02


class _ProjectedSource:
    """Retained-camera projection plus per-frame source observations."""

    def __init__(self, rotation: np.ndarray, image_transform, swap: bool):
        self.rotation = rotation
        self.image_transform = tuple(image_transform)
        self.swap = swap

    def project(self, point: np.ndarray) -> np.ndarray:
        camera_point = (self.rotation @ point) * np.array([1.0, -1.0, -1.0])
        return np.asarray(_apply_similarity(
            (float(camera_point[0]), -float(camera_point[1])),
            self.image_transform,
        ))

    def frame_matches(self, clip: MotionClip, source_frames: list[dict[str, Any]]):
        """Pair each source observation with a motion frame and body span."""
        motion_frames = [
            {"time": frame.time_sec, "joints": dict(frame.joints)}
            for frame in clip.frames
        ]
        matches = []
        for source_frame in source_frames:
            motion_frame = _motion_frame_at_time(motion_frames, source_frame["time"])
            if motion_frame is None:
                continue
            span = _body_span_2d(source_frame["joints"])
            if span <= 1e-9:
                continue
            source_points = {}
            for name, point in source_frame["joints"].items():
                source_points[_bilateral_name(name, swap=self.swap)] = np.asarray(
                    point[:2], dtype=float
                )
            matches.append((motion_frame["joints"], source_points, span))
        return matches


def _body_span_2d(joints: dict[str, Any]) -> float:
    points = np.asarray(
        [point[:2] for point in joints.values()], dtype=float
    )
    if len(points) < 2:
        return 0.0
    return float(np.linalg.norm(np.ptp(points, axis=0)))


def _rotation_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
    x, y, z = axis
    cos, sin = math.cos(angle), math.sin(angle)
    cross = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return cos * np.eye(3) + sin * cross + (1.0 - cos) * np.outer(axis, axis)


def _collect_chain_errors(
    matches: list[tuple[dict, dict, float]],
    projection: _ProjectedSource,
    root: str,
    distal: tuple[str, ...],
    matrix: np.ndarray | None = None,
) -> tuple[list[float], list[float]]:
    distal_errors: list[float] = []
    root_errors: list[float] = []
    for joints, source_points, span in matches:
        root_point = joints.get(root)
        if root_point is None:
            continue
        root_point = np.asarray(root_point, dtype=float)
        root_target = source_points.get(root)
        if root_target is not None:
            root_errors.append(
                float(np.linalg.norm(projection.project(root_point) - root_target)) / span
            )
        for name in distal:
            point = joints.get(name)
            target = source_points.get(name)
            if point is None or target is None:
                continue
            point = np.asarray(point, dtype=float)
            if matrix is not None:
                point = root_point + matrix @ (point - root_point)
            distal_errors.append(
                float(np.linalg.norm(projection.project(point) - target)) / span
            )
    return distal_errors, root_errors


def _chain_errors(
    matches: list[tuple[dict, dict, float]],
    projection: _ProjectedSource,
    root: str,
    distal: tuple[str, ...],
    matrix: np.ndarray | None = None,
) -> tuple[float, float, int]:
    """(mean distal error ratio, mean root error ratio, sample count)."""
    distal_errors, root_errors = _collect_chain_errors(
        matches, projection, root, distal, matrix
    )
    if not distal_errors:
        return math.inf, math.inf, 0
    return (
        float(np.mean(distal_errors)),
        float(np.mean(root_errors)) if root_errors else math.inf,
        len(distal_errors),
    )


def _chain_objective(
    matches: list[tuple[dict, dict, float]],
    projection: _ProjectedSource,
    root: str,
    distal: tuple[str, ...],
    matrix: np.ndarray | None = None,
) -> float:
    """Mean squared distal error: emphasizes the worst joints so the bounded
    search cannot trade one very wrong distal joint against several mediocre
    ones."""
    distal_errors, _ = _collect_chain_errors(matches, projection, root, distal, matrix)
    if not distal_errors:
        return math.inf
    return float(np.mean(np.square(distal_errors)))


def _solve_chain_rotation(
    matches,
    projection: _ProjectedSource,
    root: str,
    distal: tuple[str, ...],
    axes: tuple[np.ndarray, np.ndarray],
) -> tuple[np.ndarray | None, float, float]:
    """Bounded deterministic 2-axis search minimizing distal projected error."""
    def evaluate(first: float, second: float):
        matrix = _rotation_matrix(axes[1], second) @ _rotation_matrix(axes[0], first)
        return _chain_objective(
            matches, projection, root, distal, matrix
        ) + MINIMAL_ROTATION_PENALTY * (first * first + second * second)

    best = (0.0, 0.0)
    best_error = evaluate(0.0, 0.0)
    for step in (GRID_STEP_RADIANS,) + REFINEMENT_STEPS_RADIANS:
        improved = True
        while improved:
            improved = False
            for index in (0, 1):
                candidates = []
                for offset in (-step, step):
                    angles = list(best)
                    angles[index] += offset
                    magnitude = math.hypot(*angles)
                    if magnitude > MAX_ROTATION_RADIANS:
                        scale = MAX_ROTATION_RADIANS / magnitude
                        angles = [value * scale for value in angles]
                    candidates.append(tuple(angles))
                for angles in candidates:
                    error = evaluate(*angles)
                    if error + 1e-12 < best_error:
                        best, best_error = angles, error
                        improved = True
    if best == (0.0, 0.0):
        return None, best_error, best_error
    matrix = _rotation_matrix(axes[1], best[1]) @ _rotation_matrix(axes[0], best[0])
    return matrix, best_error, _chain_errors(matches, projection, root, distal)[0]


def correct_distal_chain_depth(
    clip: MotionClip,
    source_pose_payload: dict[str, Any] | None,
) -> tuple[MotionClip, dict[str, Any]]:
    """Rotate depth-misplaced distal chains into source-2D agreement.

    Uses the camera registered during source-guided structural refinement;
    without an available registration the clip is returned unchanged.
    """
    report: dict[str, Any] = {"applied": False, "chains": {}}
    registration = (
        (clip.metadata.get("structuralRefinement") or {})
        .get("sourceGuidedArticulation", {})
        .get("cameraRegistration", {})
    )
    if not isinstance(source_pose_payload, dict) or not registration.get("available"):
        report["reason"] = "camera_registration_unavailable"
        return clip, report
    rotation = np.asarray(registration.get("cameraRotation", []), dtype=float)
    image_transform = registration.get("cameraImageTransform")
    if (
        rotation.shape != (3, 3)
        or not np.isfinite(rotation).all()
        or not isinstance(image_transform, (list, tuple))
        or len(image_transform) != 6
    ):
        report["reason"] = "camera_registration_incomplete"
        return clip, report
    source_frames = _pose_frames(source_pose_payload, source=True)
    if len(source_frames) < 5:
        report["reason"] = "source_pose_unavailable"
        return clip, report
    projection = _ProjectedSource(
        rotation,
        image_transform,
        swap=registration.get("bilateralAssignment") == "swapped",
    )
    matches = projection.frame_matches(clip, source_frames)
    if len(matches) < 5:
        report["reason"] = "matched_frames_insufficient"
        return clip, report
    # Rotation axes: the camera's right and up directions expressed in world
    # coordinates. Rotating about either moves distal joints between image
    # position and camera depth without spinning them in the image plane.
    axes = (
        rotation.T @ np.array([1.0, 0.0, 0.0]),
        rotation.T @ np.array([0.0, 1.0, 0.0]),
    )
    corrected_frames: list[MotionFrame] | None = None
    applied_chains = 0
    for label, root, distal in DISTAL_CHAINS:
        joint_names = set(clip.frames[0].joints) if clip.frames else set()
        if root not in joint_names or not all(name in joint_names for name in distal):
            continue
        distal_before, root_before, samples = _chain_errors(
            matches, projection, root, distal
        )
        chain_report: dict[str, Any] = {
            "distalErrorBodyRatioBefore": round(distal_before, 4),
            "rootErrorBodyRatio": round(root_before, 4),
            "sampleCount": samples,
        }
        detected = (
            distal_before >= MIN_DISTAL_ERROR_RATIO
            and root_before <= MAX_ROOT_ERROR_RATIO
            and distal_before >= root_before * DISTAL_OVER_ROOT_FACTOR
        )
        if not detected:
            chain_report["applied"] = False
            chain_report["reason"] = "signature_not_detected"
            report["chains"][label] = chain_report
            continue
        matrix, distal_after, _ = _solve_chain_rotation(
            matches, projection, root, distal, axes
        )
        chain_report["distalErrorBodyRatioAfter"] = round(distal_after, 4)
        # The rotation pivots on the root, so the root's own projected error
        # is unchanged by construction; no separate degradation check exists.
        accepted = (
            matrix is not None
            and distal_after <= (1.0 - MIN_RELATIVE_IMPROVEMENT) * distal_before
            and distal_after <= MAX_ACCEPTED_DISTAL_ERROR_RATIO
        )
        if not accepted:
            chain_report["applied"] = False
            chain_report["reason"] = "correction_not_decisive"
            report["chains"][label] = chain_report
            continue
        chain_report["applied"] = True
        report["chains"][label] = chain_report
        applied_chains += 1
        if corrected_frames is None:
            corrected_frames = list(clip.frames)
        for index, frame in enumerate(corrected_frames):
            joints = dict(frame.joints)
            if root not in joints:
                continue
            root_point = np.asarray(joints[root], dtype=float)
            for name in distal:
                point = joints.get(name)
                if point is None:
                    continue
                joints[name] = tuple(
                    root_point + matrix @ (np.asarray(point, dtype=float) - root_point)
                )
            corrected_frames[index] = replace(frame, joints=joints)
    report["applied"] = applied_chains > 0
    if applied_chains > 0:
        report["reason"] = "distal_chain_depth_corrected"
        clip = replace(clip, frames=corrected_frames)
    return clip, report
