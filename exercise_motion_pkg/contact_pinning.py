"""Deterministic foot-chain pinning for source-confirmed stationary contacts.

The whole-body contact translation correction removes common drift, but a
planted foot can still slide relative to the body because the residual error
lives in the limb, not the root. This module pins the leg chain of a
source-confirmed stationary contact to its anchor with closed-form two-bone
IK: bone lengths are preserved exactly, the hip stays where the reconstruction
put it, and the knee keeps its own bend plane. Only source-confirmed
stationary intervals that still exceed the planted-foot slide threshold after
the translation correction are touched, so genuine travel is never frozen.
Final validation gates still judge the result; nothing here is accepted on
trust.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

LEG_CHAIN_JOINTS = {
    "left": ("left_hip", "left_knee", "left_ankle", "left_foot"),
    "right": ("right_hip", "right_knee", "right_ankle", "right_foot"),
}

# Correction ramps over this many seconds at each interval boundary so the
# limb travels to its anchor instead of teleporting (velocity/angle spikes).
PINNING_BLEND_SECONDS = 0.25


def _chain_range_ratio(points: list[list[float]], body_span: float) -> float:
    if not points or body_span <= 1e-9:
        return 0.0
    axis_ranges = [
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    ]
    return math.sqrt(sum(value * value for value in axis_ranges)) / body_span


def _payload_fps(frames: list[dict[str, Any]]) -> float:
    times = [
        float(frame.get("timeSec")) for frame in frames
        if isinstance(frame.get("timeSec"), (int, float))
    ]
    steps = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not steps:
        return 30.0
    return 1.0 / statistics.median(steps)


def _solve_leg_chain(
    hip: list[float],
    knee: list[float],
    ankle: list[float],
    ankle_target: list[float],
) -> tuple[list[float], list[float]] | None:
    """Closed-form two-bone IK returning new knee/ankle positions.

    Preserves both bone lengths exactly and keeps the knee in its current
    bend plane. The target is clamped to the reachable annulus when the leg
    cannot reach it, so the correction degrades gracefully instead of
    stretching bones.
    """
    l1 = math.dist(hip, knee)
    l2 = math.dist(knee, ankle)
    if l1 <= 1e-9 or l2 <= 1e-9:
        return None
    distance = math.dist(hip, ankle_target)
    max_reach = l1 + l2 - 1e-9
    min_reach = abs(l1 - l2) + 1e-9
    if distance <= 1e-9 or distance > max_reach or distance < min_reach:
        clamped = min(max(distance, min_reach), max_reach)
        scale = clamped / distance
        ankle_target = [
            hip[i] + (ankle_target[i] - hip[i]) * scale for i in range(3)
        ]
        distance = clamped
    axis = [(ankle_target[i] - hip[i]) / distance for i in range(3)]
    a = (l1 * l1 - l2 * l2 + distance * distance) / (2 * distance)
    height_sq = max(0.0, l1 * l1 - a * a)
    height = math.sqrt(height_sq)
    # Bend plane pole: keep the current knee's offset from the hip-axis line.
    knee_offset = [knee[i] - hip[i] for i in range(3)]
    along = sum(knee_offset[i] * axis[i] for i in range(3))
    pole = [knee_offset[i] - along * axis[i] for i in range(3)]
    pole_length = math.sqrt(sum(value * value for value in pole))
    if pole_length <= 1e-9:
        # Straight leg: pick any axis perpendicular to the hip->target line
        # via a cross product with the least-aligned world axis.
        world = min(((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)),
                    key=lambda candidate: abs(sum(a * b for a, b in zip(axis, candidate))))
        pole = [
            axis[(i + 1) % 3] * world[(i + 2) % 3]
            - axis[(i + 2) % 3] * world[(i + 1) % 3]
            for i in range(3)
        ]
        pole_length = math.sqrt(sum(value * value for value in pole))
        if pole_length <= 1e-9:
            return None
    pole = [value / pole_length for value in pole]
    new_knee = [hip[i] + a * axis[i] + height * pole[i] for i in range(3)]
    return new_knee, list(ankle_target)


def pin_stationary_contact_chains(
    frames: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
    *,
    body_span: float,
    slide_threshold_ratio: float,
    joint_names: list[str] | tuple[str, ...] | None = None,
    support_plane_y: float | None = None,
    floor_threshold_ratio: float = 0.06,
) -> dict[str, Any]:
    """Pin still-sliding or floating source-confirmed feet to their anchors.

    ``frames`` are export-payload frames (mutated in place) after the
    whole-body translation correction. ``intervals`` are stationary contact
    intervals with ``startFrame``/``endFrame``/``anchor``/``evaluatedJointName``
    as produced by the contact correction. When ``support_plane_y`` is known,
    an anchor whose contact floats above or sinks below the plane is projected
    onto it, mirroring the stationarity gate's floor check. Returns a
    per-joint report for the correction metrics; frames without a full leg
    chain are left untouched.
    """
    report: dict[str, Any] = {}
    if body_span <= 1e-9 or not frames:
        return {"applied": False, "reason": "body_span_unavailable", "joints": {}}
    known_names = set(joint_names) if joint_names is not None else (
        set().union(*(set(frame.get("joints", {})) for frame in frames[:1]))
    )
    for interval in intervals:
        joint_name = str(
            interval.get("evaluatedJointName") or interval.get("jointName") or "")
        if not joint_name.endswith(("_foot", "_ankle")):
            continue
        side = joint_name.split("_", 1)[0]
        chain = LEG_CHAIN_JOINTS.get(side)
        if not chain or not all(name in known_names for name in chain):
            continue
        start = int(interval["startFrame"])
        end = int(interval["endFrame"])
        anchor = interval.get("anchor")
        if not isinstance(anchor, (list, tuple)) or len(anchor) != 3:
            continue
        anchor = [float(anchor[i]) for i in range(3)]
        interval_frames = [
            frame for frame in frames[start : end + 1]
            if isinstance(frame.get("joints"), dict)
            and all(name in frame["joints"] for name in chain)
        ]
        if len(interval_frames) < 3:
            report.setdefault(joint_name, []).append(
                {"applied": False, "reason": "insufficient_samples"})
            continue
        contact_joint = chain[3] if joint_name.endswith("_foot") else chain[2]
        before_points = [
            [float(frame["joints"][contact_joint][i]) for i in range(3)]
            for frame in interval_frames
        ]
        before_ratio = _chain_range_ratio(before_points, body_span)
        floor_error_ratio = None
        if (
            support_plane_y is not None
            and interval.get("isObservedGroundContact") is not False
        ):
            median_y = statistics.median(point[1] for point in before_points)
            floor_error_ratio = abs(median_y - support_plane_y) / body_span
            if floor_error_ratio > floor_threshold_ratio:
                # The source confirms this contact rests on the support plane;
                # anchor it there rather than at its floating observed height.
                anchor = [anchor[0], float(support_plane_y), anchor[2]]
        if (
            before_ratio <= slide_threshold_ratio
            and (floor_error_ratio is None or floor_error_ratio <= floor_threshold_ratio)
        ):
            report.setdefault(joint_name, []).append({
                "applied": False,
                "reason": "already_stationary",
                "rangeRatio": round(before_ratio, 4),
                "floorErrorBodyRatio": (
                    round(floor_error_ratio, 4) if floor_error_ratio is not None else None
                ),
            })
            continue
        corrected_count = 0
        fps = _payload_fps(frames)
        blend_frames = max(1, int(round(PINNING_BLEND_SECONDS * fps)))
        # Extend the correction window past the interval: the confirmed
        # contact frames are pinned exactly, and the transition to/from the
        # original trajectory happens in the neighboring non-contact frames
        # so the limb travels to the anchor instead of teleporting.
        window_start = max(0, start - blend_frames)
        window_end = min(len(frames) - 1, end + blend_frames)
        for frame_index in range(window_start, window_end + 1):
            frame = frames[frame_index]
            if not (
                isinstance(frame.get("joints"), dict)
                and all(name in frame["joints"] for name in chain)
            ):
                continue
            weight = min(
                (frame_index - window_start + 1) / (blend_frames + 1),
                (window_end - frame_index + 1) / (blend_frames + 1),
                1.0,
            )
            joints = frame["joints"]
            hip = [float(value) for value in joints[chain[0]]]
            knee = [float(value) for value in joints[chain[1]]]
            ankle = [float(value) for value in joints[chain[2]]]
            foot = [float(value) for value in joints[chain[3]]]
            # Keep the ankle->foot direction; pin the contact joint exactly,
            # ramped at the boundaries so the limb travels instead of jumps.
            foot_offset = [foot[i] - ankle[i] for i in range(3)]
            contact_point = foot if joint_name.endswith("_foot") else ankle
            target = [
                contact_point[i] + weight * (anchor[i] - contact_point[i])
                for i in range(3)
            ]
            if joint_name.endswith("_foot"):
                ankle_target = [target[i] - foot_offset[i] for i in range(3)]
            else:
                ankle_target = target
            solved = _solve_leg_chain(hip, knee, ankle, ankle_target)
            if solved is None:
                continue
            new_knee, new_ankle = solved
            new_foot = [new_ankle[i] + foot_offset[i] for i in range(3)]
            joints[chain[1]] = new_knee
            joints[chain[2]] = new_ankle
            joints[chain[3]] = new_foot
            corrected_count += 1
        after_points = [
            [float(frame["joints"][contact_joint][i]) for i in range(3)]
            for frame in interval_frames
        ]
        report.setdefault(joint_name, []).append({
            "applied": corrected_count > 0,
            "correctedFrameCount": corrected_count,
            "startFrame": start,
            "endFrame": end,
            "rangeRatioBefore": round(before_ratio, 4),
            "rangeRatioAfter": round(_chain_range_ratio(after_points, body_span), 6),
            "floorErrorBodyRatioBefore": (
                round(floor_error_ratio, 4) if floor_error_ratio is not None else None
            ),
        })
    return {
        "applied": any(
            entry.get("applied")
            for entries in report.values()
            for entry in entries
        ),
        "joints": report,
    }
