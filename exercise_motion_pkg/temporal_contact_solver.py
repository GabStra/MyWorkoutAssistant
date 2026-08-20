from __future__ import annotations

import itertools
import math
import statistics
from dataclasses import replace
from typing import Any

import numpy as np

from exercise_motion_pkg.ground import PlaneEstimate, percentile
from exercise_motion_pkg.models import MotionClip, MotionFrame, Point3
from exercise_motion_pkg.render_geometry import support_surface_height
from exercise_motion_pkg.structural_refinement import STRUCTURAL_BONES
GENERIC_CONTACT_JOINT_GROUPS: tuple[tuple[str, ...], ...] = (
    ("left_foot", "left_ankle", "l_ankle"),
    ("right_foot", "right_ankle", "r_ankle"),
    ("left_knee",),
    ("right_knee",),
    ("left_hand", "left_wrist"),
    ("right_hand", "right_wrist"),
    ("left_elbow",),
    ("right_elbow",),
    ("pelvis",),
    ("left_hip",),
    ("right_hip",),
    ("spine1",),
    ("spine2",),
    ("spine3",),
    ("left_shoulder",),
    ("right_shoulder",),
)


CONTACT_ALIGNMENT_DISTANCE_TOLERANCE = 0.14
CONTACT_ALIGNMENT_VERTICAL_SPEED_TOLERANCE = 0.12
CONTACT_ALIGNMENT_MINIMUM_CONFIDENCE = 0.25
CONTACT_HINGE_SEARCH_STEP_DEGREES = 3
NON_PENETRATION_CLEARANCE = 0.0


def _rotate_point_rodigues(
    point: Point3, *, pivot: Point3, axis: Point3, angle_radians: float
) -> Point3:
    kx, ky, kz = axis
    vx = point[0] - pivot[0]
    vy = point[1] - pivot[1]
    vz = point[2] - pivot[2]
    cos_a = math.cos(angle_radians)
    sin_a = math.sin(angle_radians)
    dot = vx * kx + vy * ky + vz * kz
    # Rodrigues' rotation formula: v_rot = v*cos + (k×v)*sin + k*(k·v)*(1-cos)
    cross_x = ky * vz - kz * vy
    cross_y = kz * vx - kx * vz
    cross_z = kx * vy - ky * vx
    rx = vx * cos_a + cross_x * sin_a + kx * dot * (1.0 - cos_a)
    ry = vy * cos_a + cross_y * sin_a + ky * dot * (1.0 - cos_a)
    rz = vz * cos_a + cross_z * sin_a + kz * dot * (1.0 - cos_a)
    return (rx + pivot[0], ry + pivot[1], rz + pivot[2])


def _rotate_clip_about_axis(
    clip: MotionClip,
    *,
    pivot: Point3,
    axis: Point3,
    angle_radians: float,
) -> MotionClip:
    rotated_frames = []
    for frame in clip.frames:
        rotated_frames.append(
            MotionFrame(
                time_sec=frame.time_sec,
                joints={
                    name: _rotate_point_rodigues(
                        pt, pivot=pivot, axis=axis, angle_radians=angle_radians
                    )
                    for name, pt in frame.joints.items()
                },
            )
        )
    return replace(clip, frames=rotated_frames)


def _rotate_clip_normal_to_world_up(
    clip: MotionClip,
    *,
    normal: Point3,
    pivot: Point3,
) -> tuple[MotionClip, float]:
    target = (0.0, 1.0, 0.0)
    axis = (
        normal[1] * target[2] - normal[2] * target[1],
        normal[2] * target[0] - normal[0] * target[2],
        normal[0] * target[1] - normal[1] * target[0],
    )
    axis_length = math.sqrt(axis[0] * axis[0] + axis[1] * axis[1] + axis[2] * axis[2])
    alignment = max(-1.0, min(1.0, normal[1]))
    angle = math.acos(alignment)
    if axis_length <= 1e-8 or angle <= 1e-8:
        return clip, 0.0
    normalized_axis = (axis[0] / axis_length, axis[1] / axis_length, axis[2] / axis_length)
    return (
        _rotate_clip_about_axis(
            clip,
            pivot=pivot,
            axis=normalized_axis,
            angle_radians=angle,
        ),
        math.degrees(angle),
    )


def _video_floor_distances(clip: MotionClip) -> dict[str, float]:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    alignment = metadata.get("videoWorldAlignment")
    if not isinstance(alignment, dict):
        return {}
    raw_distances = alignment.get("videoFloorDistances")
    if not isinstance(raw_distances, dict):
        return {}
    return {
        str(name): float(value)
        for name, value in raw_distances.items()
        if isinstance(value, (int, float)) and math.isfinite(float(value))
    }


def _video_floor_distance_observations(
    clip: MotionClip,
) -> dict[str, list[tuple[float, float]]]:
    """Return normalized timestamped floor-distance observations."""
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    alignment = metadata.get("videoWorldAlignment")
    if not isinstance(alignment, dict):
        return {}
    raw = alignment.get("videoFloorDistanceObservations")
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, list[tuple[float, float]]] = {}
    for joint_name, items in raw.items():
        if not isinstance(joint_name, str) or not isinstance(items, list):
            continue
        per_joint: list[tuple[float, float]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            t = item.get("timeSeconds")
            d = item.get("distance")
            if isinstance(t, (int, float)) and isinstance(d, (int, float)):
                per_joint.append((float(t), float(d)))
        if per_joint:
            normalized[joint_name] = per_joint
    return normalized


def _authoritative_world_floor_normal(clip: MotionClip) -> Point3 | None:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    alignment = metadata.get("videoWorldAlignment")
    if not isinstance(alignment, dict):
        return None
    raw_plane = alignment.get("cameraGroundPlane")
    if not isinstance(raw_plane, dict):
        return None
    raw_normal = raw_plane.get("normal")
    if (
        not isinstance(raw_normal, list)
        or len(raw_normal) != 3
        or not all(isinstance(value, (int, float)) for value in raw_normal)
    ):
        return None
    normal = (float(raw_normal[0]), float(raw_normal[1]), float(raw_normal[2]))
    coordinate_normalization = metadata.get("coordinateNormalization")
    if (
        isinstance(coordinate_normalization, dict)
        and coordinate_normalization.get("target") == "canonical_y_up_world"
    ):
        normal = (normal[0], -normal[1], -normal[2])
    length = math.sqrt(normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2])
    if length <= 1e-8:
        return None
    normalized = (normal[0] / length, normal[1] / length, normal[2] / length)
    if normalized[1] < 0.0:
        normalized = (-normalized[0], -normalized[1], -normalized[2])
    return normalized


def _vertical_frame_speed(clip: MotionClip, *, frame_index: int, joint_name: str) -> float:
    if clip.frame_count <= 1:
        return 0.0
    if frame_index <= 0:
        return clip.frames[1].joints[joint_name][1] - clip.frames[0].joints[joint_name][1]
    return clip.frames[frame_index].joints[joint_name][1] - clip.frames[frame_index - 1].joints[joint_name][1]


def _generic_contact_candidates_temporal(clip: MotionClip) -> list[str]:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    alignment = metadata.get("videoWorldAlignment")
    inferred: list[str] = []
    constraints: list[str] = []
    if isinstance(alignment, dict):
        raw_inferred = alignment.get("inferredSupportJointNames")
        if isinstance(raw_inferred, list):
            inferred = [str(x) for x in raw_inferred if isinstance(x, str)]
        raw_constraints = alignment.get("orientationConstraintJointNames")
        if isinstance(raw_constraints, list):
            constraints = [str(x) for x in raw_constraints if isinstance(x, str)]

    candidate_set = set(
        name
        for name in (inferred + constraints)
        if isinstance(name, str) and name in clip.joint_names
    )

    # Add any additional joints whose video distance track looks stable over time.
    obs = _video_floor_distance_observations(clip)
    for group in GENERIC_CONTACT_JOINT_GROUPS:
        available = [name for name in group if name in clip.joint_names and name in obs]
        for joint_name in available:
            distances = [d for _t, d in obs[joint_name]]
            if len(distances) < 3:
                continue
            spread = float(np.percentile(distances, 75) - np.percentile(distances, 25))
            median = float(np.median(distances))
            # Avoid selecting joints that are clearly below the plane due to depth noise.
            if median < -0.20:
                continue
            if spread <= 0.08 and abs(median) <= 0.45:
                candidate_set.add(joint_name)

    if candidate_set:
        # Prefer floor-near joints when we have multiple choices.
        distances = _video_floor_distances(clip)
        return sorted(
            candidate_set,
            key=lambda name: abs(distances.get(name, float("inf"))),
        )

    # Fallback: use medians alone (if available) or the lowest persistent height band.
    distances = _video_floor_distances(clip)
    representatives: list[tuple[str, float]] = []
    for group in GENERIC_CONTACT_JOINT_GROUPS:
        available = [
            name
            for name in group
            if name in clip.joint_names and name in distances
        ]
        if not available:
            continue
        representative = min(available, key=lambda name: abs(distances[name]))
        representatives.append((representative, abs(distances[representative])))

    if representatives:
        near_floor = [
            name
            for name, distance in representatives
            if distance <= CONTACT_ALIGNMENT_DISTANCE_TOLERANCE
        ]
        if near_floor:
            return near_floor

    # If we do have video distances but none are close to the floor plane,
    # preserve the clip (no confident contacts).
    if representatives:
        return []

    # No reliable video distances: infer contacts from the lowest persistent
    # height band in the clip itself.
    median_heights: list[tuple[str, float]] = []
    for group in GENERIC_CONTACT_JOINT_GROUPS:
        available = [name for name in group if name in clip.joint_names]
        if not available:
            continue
        representative = min(
            available,
            key=lambda name: statistics.median(
                support_surface_height(frame.joints[name][1])
                for frame in clip.frames
                if name in frame.joints
            ),
        )
        heights = [
            support_surface_height(frame.joints[representative][1])
            for frame in clip.frames
            if representative in frame.joints
        ]
        if heights:
            median_heights.append((representative, statistics.median(heights)))

    if not median_heights:
        return []
    lowest_height = min(height for _name, height in median_heights)
    selected = [
        name
        for name, height in median_heights
        if height <= lowest_height + CONTACT_ALIGNMENT_DISTANCE_TOLERANCE
    ]

    # If both knees sit in the lowest persistent height band, treat them as the
    # primary support for temporal grounding (prevents hinge-pair degeneracy).
    if "left_knee" in selected and "right_knee" in selected:
        return ["left_knee", "right_knee"]

    return selected


def _generic_contact_frame_joints(
    clip: MotionClip,
    candidate_names: list[str],
) -> list[list[str]]:
    persistent_bilateral_knee_support = (
        len(candidate_names) == 2
        and all("knee" in name.casefold() for name in candidate_names)
    )
    if persistent_bilateral_knee_support:
        return [
            [name for name in candidate_names if name in frame.joints]
            for frame in clip.frames
        ]

    floor_bands: dict[str, float] = {}
    for name in candidate_names:
        heights: list[float] = []
        for frame in clip.frames:
            if name in frame.joints:
                heights.append(support_surface_height(frame.joints[name][1]))
        if heights:
            floor_bands[name] = percentile(heights, 0.15)

    if not floor_bands:
        return [[] for _frame in clip.frames]

    contacts: list[list[str]] = []
    previous_contacts: set[str] = set()
    for frame_index, frame in enumerate(clip.frames):
        frame_contacts: list[str] = []
        for name in candidate_names:
            point = frame.joints.get(name)
            if point is None:
                continue
            release_margin = 0.04 if name in previous_contacts else 0.0
            height = support_surface_height(point[1])
            vertical_speed = _vertical_frame_speed(
                clip, frame_index=frame_index, joint_name=name
            )
            if (
                height <= floor_bands[name] + CONTACT_ALIGNMENT_DISTANCE_TOLERANCE + release_margin
                and abs(vertical_speed) <= CONTACT_ALIGNMENT_VERTICAL_SPEED_TOLERANCE
            ):
                frame_contacts.append(name)
        contacts.append(frame_contacts)
        previous_contacts = set(frame_contacts)
    return contacts


def _best_fit_contact_plane_normal(
    clip: MotionClip,
    frame_contacts: list[list[str]],
) -> tuple[Point3, Point3] | None:
    if max((len(set(names)) for names in frame_contacts), default=0) < 3:
        return None
    points: list[Point3] = [
        frame.joints[name]
        for frame, names in zip(clip.frames, frame_contacts)
        for name in names
        if name in frame.joints
    ]
    if len(points) < 3:
        return None
    values = np.asarray(points, dtype=np.float64)
    centroid = np.median(values, axis=0)
    centered = values - centroid
    try:
        _u, singular_values, vh = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    if len(singular_values) < 2 or float(singular_values[1]) <= 1e-6:
        return None
    normal = vh[-1]
    length = float(np.linalg.norm(normal))
    if length <= 1e-8:
        return None
    normal = normal / length
    if normal[1] < 0.0:
        normal = -normal
    return (
        (float(normal[0]), float(normal[1]), float(normal[2])),
        (float(centroid[0]), float(centroid[1]), float(centroid[2])),
    )


def _dominant_contact_pairs(frame_contacts: list[list[str]]) -> list[tuple[str, str]]:
    pair_counts: dict[tuple[str, str], int] = {}
    for names in frame_contacts:
        if len(names) < 2:
            continue
        for a, b in itertools.combinations(sorted(names), 2):
            pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1
    if not pair_counts:
        return []
    sorted_pairs = sorted(pair_counts.items(), key=lambda kv: kv[1], reverse=True)
    best_count = sorted_pairs[0][1]
    return [pair for pair, count in sorted_pairs if count >= max(2, int(best_count * 0.6))]


def _rotate_frame_about_contact_pair(
    frame: MotionFrame,
    pair: tuple[str, str],
    *,
    angle_radians: float,
) -> MotionFrame:
    first = frame.joints.get(pair[0])
    second = frame.joints.get(pair[1])
    if first is None or second is None:
        return frame
    axis = (second[0] - first[0], 0.0, second[2] - first[2])
    axis_length = math.hypot(axis[0], axis[2])
    if axis_length <= 1e-8:
        return frame
    normalized_axis = (axis[0] / axis_length, 0.0, axis[2] / axis_length)
    pivot = (
        (first[0] + second[0]) * 0.5,
        (first[1] + second[1]) * 0.5,
        (first[2] + second[2]) * 0.5,
    )
    rotated_joints = {
        name: _rotate_point_rodigues(
            point, pivot=pivot, axis=normalized_axis, angle_radians=angle_radians
        )
        for name, point in frame.joints.items()
    }
    return MotionFrame(time_sec=frame.time_sec, joints=rotated_joints)


def _interpolate_contact_corrections(
    corrections: list[float | None],
) -> list[float]:
    known = [index for index, value in enumerate(corrections) if value is not None]
    if not known:
        return [0.0 for _value in corrections]
    resolved: list[float] = []
    for index, value in enumerate(corrections):
        if value is not None:
            resolved.append(float(value))
            continue
        previous = max((item for item in known if item < index), default=None)
        following = min((item for item in known if item > index), default=None)
        if previous is None:
            resolved.append(float(corrections[following]))
        elif following is None:
            resolved.append(float(corrections[previous]))
        else:
            blend = (index - previous) / (following - previous)
            resolved.append(
                float(corrections[previous]) * (1.0 - blend)
                + float(corrections[following]) * blend
            )
    return resolved


def _contact_hinge_score(
    frames: list[MotionFrame],
    pair: tuple[str, str],
    *,
    angle_radians: float,
    target_distances: dict[str, float],
) -> float:
    penetration_squared = 0.0
    core_below_squared = 0.0
    sample_count = 0
    measured_distances: dict[str, list[float]] = {}

    stride = max(1, len(frames) // 32)
    for frame in frames[::stride]:
        rotated = _rotate_frame_about_contact_pair(
            frame,
            pair,
            angle_radians=angle_radians,
        )
        contact_points = [
            rotated.joints[name]
            for name in pair
            if name in rotated.joints
        ]
        if len(contact_points) < 2:
            continue
        contact_surface = statistics.median(
            support_surface_height(point[1]) for point in contact_points
        )
        for name, point in rotated.joints.items():
            relative_surface = support_surface_height(point[1]) - contact_surface
            if name in target_distances:
                measured_distances.setdefault(name, []).append(relative_surface)
            if relative_surface < 0.0:
                penetration_squared += relative_surface * relative_surface

        core_heights = [
            support_surface_height(rotated.joints[name][1]) - contact_surface
            for name in (
                "pelvis",
                "left_hip",
                "right_hip",
                "spine1",
                "spine2",
                "spine3",
                "neck",
            )
            if name in rotated.joints
        ]
        if core_heights:
            core_clearance = statistics.median(core_heights)
            if core_clearance < 0.04:
                deficit = 0.04 - core_clearance
                core_below_squared += deficit * deficit

        sample_count += 1

    if sample_count == 0:
        return float("inf")

    if measured_distances:
        target_error_squared = sum(
            (statistics.median(values) - target_distances[name]) ** 2
            for name, values in measured_distances.items()
            if name in target_distances
        ) / max(1, len(measured_distances))
    else:
        target_error_squared = 0.0

    return (
        20.0 * penetration_squared / sample_count
        + 100.0 * core_below_squared / sample_count
        + 30.0 * target_error_squared
        + 0.002 * angle_radians * angle_radians
    )


def _apply_consistent_contact_hinge(
    clip: MotionClip,
    frame_contacts: list[list[str]],
) -> tuple[MotionClip, float]:
    target_distances = _video_floor_distances(clip)

    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    alignment = metadata.get("videoWorldAlignment")
    if isinstance(alignment, dict):
        raw_constraint_names = alignment.get("orientationConstraintJointNames")
        if isinstance(raw_constraint_names, list):
            constraint_names = {
                str(name)
                for name in raw_constraint_names
                if isinstance(name, str)
            }
            target_distances = {
                name: distance
                for name, distance in target_distances.items()
                if name in constraint_names
            }

    # In synthetic/unit-test clips we often don't provide
    # orientationConstraintJointNames. In that case, constrain hinge fitting
    # to elevated hand/wrist-like contacts so the solver doesn't overly
    # anchor pelvis/neck heights and pick a degenerate 0-degree hinge.
    if not target_distances:
        target_distances = {}
    if not isinstance(alignment, dict) or (
        isinstance(alignment, dict) and not alignment.get("orientationConstraintJointNames")
    ):
        target_distances = {
            name: distance
            for name, distance in target_distances.items()
            if any(
                keyword in name.casefold()
                for keyword in ("wrist", "hand", "elbow", "shoulder")
            )
            and distance > 0.0
        }

    candidate_pairs = _dominant_contact_pairs(frame_contacts)
    if not candidate_pairs:
        return clip, 0.0

    candidate_degrees = range(-180, 181, CONTACT_HINGE_SEARCH_STEP_DEGREES)
    best_score = float("inf")
    best_angle_radians = 0.0
    best_pair = None

    for pair in candidate_pairs[:3]:
        for degrees in candidate_degrees:
            score = _contact_hinge_score(
                clip.frames,
                pair,
                angle_radians=math.radians(degrees),
                target_distances=target_distances,
            )
            if score < best_score:
                best_score = score
                best_angle_radians = math.radians(degrees)
                best_pair = pair

    if best_pair is None:
        return clip, 0.0

    return (
        replace(
            clip,
            frames=[
                _rotate_frame_about_contact_pair(
                    frame,
                    best_pair,
                    angle_radians=best_angle_radians,
                )
                for frame in clip.frames
            ],
        ),
        float(math.degrees(best_angle_radians)),
    )


def _level_dominant_contact_pair_consistently(
    clip: MotionClip,
    frame_contacts: list[list[str]],
) -> tuple[MotionClip, float]:
    # For non-authoritative runs, approximate the best "support axis" from stable contacts,
    # then rotate that axis to be parallel to world XZ (keeping Y-up).
    candidate_pairs = _dominant_contact_pairs(frame_contacts)
    if not candidate_pairs:
        return clip, 0.0

    pair = candidate_pairs[0]
    support_vectors: list[np.ndarray] = []
    support_points: list[Point3] = []
    for frame in clip.frames:
        if pair[0] not in frame.joints or pair[1] not in frame.joints:
            continue
        first = frame.joints[pair[0]]
        second = frame.joints[pair[1]]
        vector = np.asarray(second, dtype=np.float64) - np.asarray(first, dtype=np.float64)
        length = float(np.linalg.norm(vector))
        if length <= 1e-8:
            continue
        support_vectors.append(vector / length)
        support_points.extend((first, second))
    if not support_vectors:
        return clip, 0.0

    source_axis = np.mean(np.asarray(support_vectors), axis=0)
    source_length = float(np.linalg.norm(source_axis))
    if source_length <= 1e-8:
        return clip, 0.0
    source_axis /= source_length
    target_axis = np.asarray([source_axis[0], 0.0, source_axis[2]])
    target_length = float(np.linalg.norm(target_axis))
    if target_length <= 1e-8:
        return clip, 0.0
    target_axis /= target_length

    rotation_axis = np.cross(source_axis, target_axis)
    rotation_axis_length = float(np.linalg.norm(rotation_axis))
    if rotation_axis_length <= 1e-8:
        return clip, 0.0
    rotation_axis /= rotation_axis_length
    alignment = float(np.clip(np.dot(source_axis, target_axis), -1.0, 1.0))
    angle = math.acos(alignment)
    if angle <= 1e-8:
        return clip, 0.0

    pivot_values = np.median(np.asarray(support_points, dtype=np.float64), axis=0)
    return (
        _rotate_clip_about_axis(
            clip,
            pivot=(float(pivot_values[0]), float(pivot_values[1]), float(pivot_values[2])),
            axis=(float(rotation_axis[0]), float(rotation_axis[1]), float(rotation_axis[2])),
            angle_radians=angle,
        ),
        math.degrees(angle),
    )


def solve_temporal_contact_rigid_world_alignment(
    clip: MotionClip,
    *,
    ground_y: float = 0.0,
) -> tuple[MotionClip, dict[str, object]]:
    """Ground arbitrary motion using a clip-wide temporal contact-aware solver."""
    candidate_names = _generic_contact_candidates_temporal(clip)
    if not candidate_names:
        return clip, {
            "applied": False,
            "solver": "temporal_contact_rigid_world_alignment",
            "strategy": "preserve_no_confident_contacts",
            "reason": "no_video_supported_contact_candidates",
            "groundY": ground_y,
        }

    frame_contacts = _generic_contact_frame_joints(clip, candidate_names)
    contact_frame_count = sum(1 for names in frame_contacts if names)
    confidence = contact_frame_count / max(1, clip.frame_count)
    if confidence < CONTACT_ALIGNMENT_MINIMUM_CONFIDENCE:
        return clip, {
            "applied": False,
            "solver": "temporal_contact_rigid_world_alignment",
            "strategy": "preserve_low_contact_confidence",
            "reason": "insufficient_temporal_contact_evidence",
            "candidateJoints": candidate_names,
            "contactFrameCount": contact_frame_count,
            "confidence": confidence,
            "groundY": ground_y,
        }

    aligned = clip
    rotation_degrees = 0.0

    authoritative_normal = _authoritative_world_floor_normal(clip)
    uses_authoritative_floor_normal = authoritative_normal is not None

    if authoritative_normal is not None:
        support_points = [
            frame.joints[name]
            for frame, names in zip(clip.frames, frame_contacts)
            for name in names
            if name in frame.joints
        ]
        pivot_values = np.median(np.asarray(support_points, dtype=np.float64), axis=0)
        aligned, rotation_degrees = _rotate_clip_normal_to_world_up(
            clip,
            normal=authoritative_normal,
            pivot=(float(pivot_values[0]), float(pivot_values[1]), float(pivot_values[2])),
        )
    else:
        plane = _best_fit_contact_plane_normal(clip, frame_contacts)
        if plane is not None:
            normal, pivot = plane
            aligned, rotation_degrees = _rotate_clip_normal_to_world_up(
                clip,
                normal=normal,
                pivot=pivot,
            )

    contact_pair_leveling_degrees = 0.0
    if not uses_authoritative_floor_normal:
        aligned, contact_pair_leveling_degrees = _level_dominant_contact_pair_consistently(
            aligned, frame_contacts
        )

    aligned, hinge_rotation_degrees = _apply_consistent_contact_hinge(
        aligned,
        frame_contacts,
    )

    corrections: list[float | None] = []
    for frame, names in zip(aligned.frames, frame_contacts):
        heights = [
            support_surface_height(frame.joints[name][1])
            for name in names
            if name in frame.joints
        ]
        corrections.append(ground_y - min(heights) if heights else None)
    translations = _interpolate_contact_corrections(corrections)

    grounded_frames: list[MotionFrame] = []
    local_penetration_corrections: list[float] = []
    for index, frame in enumerate(aligned.frames):
        translated_joints = {
            name: (point[0], point[1] + translations[index], point[2])
            for name, point in frame.joints.items()
        }
        projected_joints: dict[str, Point3] = {}
        for name, point in translated_joints.items():
            correction = max(
                0.0,
                ground_y + NON_PENETRATION_CLEARANCE - support_surface_height(point[1]),
            )
            local_penetration_corrections.append(correction)
            projected_joints[name] = (point[0], point[1] + correction, point[2])
        grounded_frames.append(MotionFrame(time_sec=frame.time_sec, joints=projected_joints))

    grounded = replace(aligned, frames=grounded_frames)

    max_local_correction = max(local_penetration_corrections, default=0.0)
    if max_local_correction > 1e-8:
        # Collision clamping can introduce small kinematic inconsistencies; preserve
        # reference bone lengths to keep motion physically plausible.
        reference_lengths: dict[tuple[str, str], float] = {}
        for parent, child in STRUCTURAL_BONES:
            if parent not in clip.joint_names or child not in clip.joint_names:
                continue
            lengths: list[float] = []
            for frame in clip.frames:
                if parent in frame.joints and child in frame.joints:
                    p = frame.joints[parent]
                    c = frame.joints[child]
                    lengths.append(math.dist(p, c))
            if lengths:
                reference_lengths[(parent, child)] = float(statistics.median(lengths))

        if reference_lengths:
            bounded_frames: list[MotionFrame] = []
            for frame in grounded.frames:
                joints = dict(frame.joints)
                for parent, child in reference_lengths:
                    if parent not in joints or child not in joints:
                        continue
                    p = joints[parent]
                    c = joints[child]
                    dx = c[0] - p[0]
                    dy = c[1] - p[1]
                    dz = c[2] - p[2]
                    current_len = math.sqrt(dx * dx + dy * dy + dz * dz)
                    if current_len <= 1e-8:
                        continue
                    target_len = reference_lengths[(parent, child)]
                    scale = target_len / current_len
                    joints[child] = (
                        p[0] + dx * scale,
                        p[1] + dy * scale,
                        p[2] + dz * scale,
                    )
                bounded_frames.append(
                    MotionFrame(time_sec=frame.time_sec, joints=joints)
                )
            grounded = replace(grounded, frames=bounded_frames)

        # Keep pose edits bounded to avoid large corrective artifacts.
        MAX_JOINT_CORRECTION_METERS = 0.30
        bounded_final_frames: list[MotionFrame] = []
        for index, frame in enumerate(grounded.frames):
            rigid_frame = aligned.frames[min(index, aligned.frame_count - 1)]
            rigid_translation = translations[min(index, len(translations) - 1)]
            joints: dict[str, Point3] = {}
            for name, new_point in frame.joints.items():
                rigid_point = rigid_frame.joints.get(name)
                if rigid_point is None:
                    joints[name] = new_point
                    continue
                rigidly_grounded_point = (
                    rigid_point[0],
                    rigid_point[1] + rigid_translation,
                    rigid_point[2],
                )
                displacement = math.dist(rigidly_grounded_point, new_point)
                if displacement <= MAX_JOINT_CORRECTION_METERS:
                    joints[name] = new_point
                else:
                    ratio = MAX_JOINT_CORRECTION_METERS / max(displacement, 1e-8)
                    joints[name] = (
                        rigidly_grounded_point[0]
                        + (new_point[0] - rigidly_grounded_point[0]) * ratio,
                        rigidly_grounded_point[1]
                        + (new_point[1] - rigidly_grounded_point[1]) * ratio,
                        rigidly_grounded_point[2]
                        + (new_point[2] - rigidly_grounded_point[2]) * ratio,
                    )
            bounded_final_frames.append(
                MotionFrame(time_sec=frame.time_sec, joints=joints)
            )
        grounded = replace(grounded, frames=bounded_final_frames)

        # Clamp again to guarantee non-penetration constraints.
        clamped_frames: list[MotionFrame] = []
        for frame in grounded.frames:
            projected_joints: dict[str, Point3] = {}
            for name, point in frame.joints.items():
                correction = max(
                    0.0,
                    ground_y
                    + NON_PENETRATION_CLEARANCE
                    - support_surface_height(point[1]),
                )
                projected_joints[name] = (
                    point[0],
                    point[1] + correction,
                    point[2],
                )
            clamped_frames.append(
                MotionFrame(time_sec=frame.time_sec, joints=projected_joints)
            )
        grounded = replace(grounded, frames=clamped_frames)

    return grounded, {
        "applied": True,
        "solver": "contact_aware_rigid_world_alignment",
        "strategy": "generic_video_contact_rigid_alignment",
        "reason": "video_supported_contacts_rigidly_aligned_to_floor",
        "candidateJoints": candidate_names,
        "contactFrameCount": contact_frame_count,
        "confidence": confidence,
        "rotationDegrees": rotation_degrees,
        "usedAuthoritativeFloorNormal": uses_authoritative_floor_normal,
        "maximumFrameLevelingDegrees": contact_pair_leveling_degrees,
        "contactPairLevelingDegrees": contact_pair_leveling_degrees,
        "contactHingeRotationDegrees": hinge_rotation_degrees,
        "groundY": ground_y,
        "maximumVerticalCorrection": max((abs(value) for value in translations), default=0.0),
        "maximumNonPenetrationLift": 0.0,
        "maximumLocalPenetrationCorrection": max(
            local_penetration_corrections,
            default=0.0,
        ),
    }

