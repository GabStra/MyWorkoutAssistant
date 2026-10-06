"""Conservative source evidence for paired arm constraints, independent of names."""
from __future__ import annotations

from typing import Any

import numpy as np


def _elbow_angle(joints: dict[str, Any], side: str) -> float:
    upper = np.asarray(joints[f"{side}_shoulder"]) - joints[f"{side}_elbow"]
    lower = np.asarray(joints[f"{side}_wrist"]) - joints[f"{side}_elbow"]
    denominator = float(np.linalg.norm(upper) * np.linalg.norm(lower))
    if denominator < 1e-10:
        raise ValueError("degenerate arm")
    return float(np.degrees(np.arccos(np.clip(upper @ lower / denominator, -1, 1))))


def source_arm_symmetry_evidence(payload: dict[str, Any] | None) -> dict[str, Any]:
    frames = (payload or {}).get("frames") or []
    errors: list[float] = []
    angle_differences: list[float] = []
    for frame in frames:
        try:
            joints = {name: np.asarray(point[:2], dtype=float)
                      for name, point in frame["joints"].items()}
            left, right = joints["left_shoulder"], joints["right_shoulder"]
            axis = right - left
            width = float(np.linalg.norm(axis))
            body_span = max(float(np.linalg.norm(left - joints["left_hip"])),
                            float(np.linalg.norm(right - joints["right_hip"])))
            # Near-side views cannot establish bilateral pose symmetry.
            if width < max(1e-6, body_span * 0.2):
                continue
            axis /= width
            center = (left + right) / 2
            pair_errors = []
            angles = []
            for part in ("elbow", "wrist"):
                point = joints[f"left_{part}"]
                mirrored = point - 2 * np.dot(point - center, axis) * axis
                pair_errors.append(float(np.linalg.norm(mirrored - joints[f"right_{part}"])) / width)
            for side in ("left", "right"):
                angles.append(_elbow_angle(joints, side))
            if not np.isfinite([*pair_errors, *angles]).all():
                continue
            errors.append(max(pair_errors))
            angle_differences.append(abs(angles[0] - angles[1]))
        except (KeyError, TypeError, ValueError):
            continue
    sufficient = len(errors) >= 6 and len(errors) >= 0.7 * len(frames)
    accepted = sufficient and float(np.median(errors)) <= 0.30 and float(np.quantile(errors, 0.9)) <= 0.5 and float(np.quantile(angle_differences, 0.9)) <= 12.0
    return {
        "accepted": bool(accepted), "source": "observed_bilateral_arm_geometry",
        "sampleCount": len(errors), "totalFrameCount": len(frames),
        "medianMirrorErrorShoulderWidthRatio": float(np.median(errors)) if errors else None,
        "p90ElbowDifferenceDegrees": float(np.quantile(angle_differences, 0.9)) if errors else None,
    }


def exported_arm_symmetry_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    differences = []
    for frame in payload.get("frames") or []:
        if not isinstance(frame, dict) or frame.get("syntheticLoopBridge"):
            continue
        try:
            joints = frame["joints"]
            angles = []
            for side in ("left", "right"):
                angles.append(_elbow_angle(joints, side))
            if np.isfinite(angles).all():
                differences.append(abs(angles[0] - angles[1]))
        except (KeyError, TypeError, ValueError):
            continue
    median = float(np.median(differences)) if differences else None
    return {"medianElbowDifferenceDegrees": median, "sampleCount": len(differences),
            "severe": len(differences) >= 6 and median is not None and median > 25.0}
