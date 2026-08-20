from __future__ import annotations

from dataclasses import dataclass, replace
import math
import statistics

import numpy as np

from exercise_motion_pkg.models import MotionClip, MotionFrame, Point3
from exercise_motion_pkg.render_geometry import (
    UNIFORM_CAPSULE_RADIUS,
    support_joint_height_for_surface,
    support_surface_height,
)


DEFAULT_FOOT_JOINTS = (
    "left_foot",
    "right_foot",
    "left_ankle",
    "right_ankle",
    "l_ankle",
    "r_ankle",
)
DEFAULT_HAND_JOINTS = (
    "left_hand",
    "right_hand",
    "left_wrist",
    "right_wrist",
)
DEFAULT_SUPPORT_JOINTS = DEFAULT_FOOT_JOINTS + DEFAULT_HAND_JOINTS
DEFAULT_ROOT_JOINTS = ("pelvis", "hips", "root")
FOOT_CONTACT_HEIGHT_TOLERANCE = 0.08
FOOT_CONTACT_RELEASE_HEIGHT_TOLERANCE = 0.11
FOOT_CONTACT_VERTICAL_SPEED_TOLERANCE = 0.08
HAND_CONTACT_HEIGHT_TOLERANCE = 0.10
HAND_CONTACT_RELEASE_HEIGHT_TOLERANCE = 0.13
HAND_CONTACT_VERTICAL_SPEED_TOLERANCE = 0.08
MAX_UNSUPPORTED_SUPPORT_CLEARANCE = 0.18
GROUND_PENETRATION_TOLERANCE = 0.012
MICRO_MOVEMENT_POSITION_TOLERANCE = 0.015
TORSO_MICRO_MOVEMENT_TOLERANCE = 0.03
ARM_MICRO_MOVEMENT_TOLERANCE = 0.02
LEG_MICRO_MOVEMENT_TOLERANCE = 0.018
SUPPORT_LOCK_BLEND = 0.75
SUPPORT_LOCK_XZ_BLEND = 0.7
SUPPORT_LOCK_Y_BLEND = 0.9
SUPPORT_GLOBAL_STABILIZATION_BLEND = 1.0
SEGMENT_ROOT_STABILIZATION_BLEND = 1.0
SEGMENT_ROOT_STABILIZATION_MIN_FRAMES = 3
ONE_EURO_MIN_CUTOFF = 0.6
ONE_EURO_BETA = 0.05
ONE_EURO_D_CUTOFF = 1.0
SUPPORT_GROUND_HEIGHT_QUANTILE = 0.30
FOOT_CONTACT_GROUND_QUANTILE = 0.20
KINEMATIC_OUTLIER_STEP_RATIO = 8.0
KINEMATIC_OUTLIER_BODY_RATIO = 0.08
KINEMATIC_OUTLIER_MAX_RUN_STEPS = 2
VERTICAL_GROUNDING_MEDIAN_WINDOW = 9

LEFT_FOOT_GROUP = ("left_foot", "left_ankle", "l_ankle")
RIGHT_FOOT_GROUP = ("right_foot", "right_ankle", "r_ankle")
LEFT_HAND_GROUP = ("left_hand", "left_wrist")
RIGHT_HAND_GROUP = ("right_hand", "right_wrist")
LEFT_KNEE_GROUP = ("left_knee",)
RIGHT_KNEE_GROUP = ("right_knee",)
LEFT_SHIN_DISTAL_GROUP = ("left_ankle", "l_ankle", "left_foot")
RIGHT_SHIN_DISTAL_GROUP = ("right_ankle", "r_ankle", "right_foot")
PROXIMAL_HIP_GROUP = ("left_hip", "right_hip", "pelvis")
KNEE_FLOOR_SUPPORT_MODES = frozenset({"quadruped", "kneeling"})
KNEELING_GRAVITY_SWAP_HEIGHT_MARGIN = 0.03
CONTACT_ALIGNMENT_DISTANCE_TOLERANCE = 0.14
CONTACT_ALIGNMENT_VERTICAL_SPEED_TOLERANCE = 0.12
CONTACT_ALIGNMENT_MINIMUM_CONFIDENCE = 0.25
CONTACT_HINGE_SEARCH_STEP_DEGREES = 3
NON_PENETRATION_CLEARANCE = 0.0

GENERIC_CONTACT_JOINT_GROUPS = (
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


def uses_knee_floor_support(support_mode: str | None) -> bool:
    return str(support_mode or "").strip().casefold() in KNEE_FLOOR_SUPPORT_MODES


def _median_joint_height(clip: MotionClip, joint_names: list[str]) -> float | None:
    samples = [
        frame.joints[name][1]
        for frame in clip.frames
        for name in joint_names
        if name in frame.joints
    ]
    return statistics.median(samples) if samples else None


def kneeling_shin_distal_joint_names(clip: MotionClip) -> list[str]:
    names: list[str] = []
    for group in (LEFT_SHIN_DISTAL_GROUP, RIGHT_SHIN_DISTAL_GROUP):
        joint_name = first_available_joint(clip, group)
        if joint_name is not None:
            names.append(joint_name)
    return names


def kneeling_hip_joint_names(clip: MotionClip) -> list[str]:
    return [name for name in PROXIMAL_HIP_GROUP if name in clip.joint_names]


def kneeling_reconstruction_gravity_is_swapped(clip: MotionClip) -> bool:
    distal_height = _median_joint_height(clip, kneeling_shin_distal_joint_names(clip))
    hip_height = _median_joint_height(clip, kneeling_hip_joint_names(clip))
    if distal_height is None or hip_height is None:
        return False
    return distal_height > hip_height + KNEELING_GRAVITY_SWAP_HEIGHT_MARGIN


def kneeling_support_pitch_joint_names(clip: MotionClip) -> list[str]:
    knees = [
        joint_name
        for joint_name in (*LEFT_KNEE_GROUP, *RIGHT_KNEE_GROUP)
        if joint_name in clip.joint_names
    ]
    if kneeling_reconstruction_gravity_is_swapped(clip):
        return knees + kneeling_shin_distal_joint_names(clip)
    return knees


def clip_preserves_video_floor_orientation(clip: MotionClip) -> bool:
    payload = clip.metadata.get("videoWorldAlignment") if isinstance(clip.metadata, dict) else None
    if not isinstance(payload, dict):
        return False
    policy = str(payload.get("policy") or "")
    if "floor_distance" not in policy:
        return False
    return bool(payload.get("applied", True))


def _median_spine_verticality(clip: MotionClip) -> float | None:
    """Median |dy|/length for pelvis->(neck/head/spine3) across frames."""
    verticalities: list[float] = []
    for frame in clip.frames:
        pelvis = frame.joints.get("pelvis")
        spine_top = frame.joints.get("neck") or frame.joints.get("head") or frame.joints.get("spine3")
        if pelvis is None or spine_top is None:
            continue
        dx = spine_top[0] - pelvis[0]
        dy = spine_top[1] - pelvis[1]
        dz = spine_top[2] - pelvis[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length <= 1e-5:
            continue
        verticalities.append(abs(dy) / length)
    if not verticalities:
        return None
    verticalities.sort()
    return verticalities[len(verticalities) // 2]


def _video_alignment_pitch_degrees(clip: MotionClip) -> float | None:
    payload = clip.metadata.get("videoWorldAlignment") if isinstance(clip.metadata, dict) else None
    if not isinstance(payload, dict):
        return None
    rotation = payload.get("rotationMatrix")
    if not (isinstance(rotation, list) and len(rotation) == 3 and all(isinstance(row, list) for row in rotation)):
        return None
    try:
        r00 = float(rotation[0][0])
        r01 = float(rotation[0][1])
        r02 = float(rotation[0][2])
        r10 = float(rotation[1][0])
        r11 = float(rotation[1][1])
        r12 = float(rotation[1][2])
        r20 = float(rotation[2][0])
        r21 = float(rotation[2][1])
        r22 = float(rotation[2][2])
    except (TypeError, ValueError):
        return None

    # Use the same pitch extraction that we used for debugging:
    # pitch ~ asin(-R[2,1]) (deg).
    try:
        v = max(-1.0, min(1.0, -r21))
        pitch = math.degrees(math.asin(v))
    except ValueError:
        return None
    if not math.isfinite(pitch):
        return None
    return pitch


def _estimate_torso_axis_average(clip: MotionClip) -> Point3 | None:
    """Average normalized pelvis->(neck|head|spine3) vector across frames."""
    axes: list[Point3] = []
    for frame in clip.frames:
        pelvis = frame.joints.get("pelvis")
        spine_top = frame.joints.get("neck") or frame.joints.get("head") or frame.joints.get("spine3")
        if pelvis is None or spine_top is None:
            continue
        dx = spine_top[0] - pelvis[0]
        dy = spine_top[1] - pelvis[1]
        dz = spine_top[2] - pelvis[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length <= 1e-5:
            continue
        axes.append((dx / length, dy / length, dz / length))
    if not axes:
        return None
    avg = (
        sum(v[0] for v in axes) / len(axes),
        sum(v[1] for v in axes) / len(axes),
        sum(v[2] for v in axes) / len(axes),
    )
    avg_len = math.sqrt(avg[0] * avg[0] + avg[1] * avg[1] + avg[2] * avg[2])
    if avg_len <= 1e-6:
        return None
    return (avg[0] / avg_len, avg[1] / avg_len, avg[2] / avg_len)


def _rotate_point_rodigues(point: Point3, *, pivot: Point3, axis: Point3, angle_radians: float) -> Point3:
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
                    name: _rotate_point_rodigues(pt, pivot=pivot, axis=axis, angle_radians=angle_radians)
                    for name, pt in frame.joints.items()
                },
            )
        )
    return replace(clip, frames=rotated_frames)


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
    normal = tuple(float(value) for value in raw_normal)
    coordinate_normalization = metadata.get("coordinateNormalization")
    if (
        isinstance(coordinate_normalization, dict)
        and coordinate_normalization.get("target") == "canonical_y_up_world"
    ):
        normal = (normal[0], -normal[1], -normal[2])
    length = math.sqrt(sum(value * value for value in normal))
    if length <= 1e-8:
        return None
    normalized = tuple(value / length for value in normal)
    if normalized[1] < 0.0:
        normalized = tuple(-value for value in normalized)
    return normalized


def _generic_contact_candidates(clip: MotionClip) -> list[str]:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    alignment = metadata.get("videoWorldAlignment")
    if isinstance(alignment, dict):
        inferred = alignment.get("inferredSupportJointNames")
        if isinstance(inferred, list):
            available_inferred = [
                str(name)
                for name in inferred
                if isinstance(name, str) and name in clip.joint_names
            ]
            if available_inferred:
                return available_inferred

    distances = _video_floor_distances(clip)
    representatives: list[tuple[str, float]] = []
    for group in GENERIC_CONTACT_JOINT_GROUPS:
        available = [name for name in group if name in clip.joint_names]
        if not available:
            continue
        with_distance = [name for name in available if name in distances]
        if with_distance:
            representative = min(with_distance, key=lambda name: abs(distances[name]))
            representatives.append((representative, abs(distances[representative])))

    if representatives:
        near_floor = [
            name
            for name, distance in representatives
            if distance <= CONTACT_ALIGNMENT_DISTANCE_TOLERANCE
        ]
        if near_floor:
            return near_floor
        return []

    # No video distances: use only joints occupying the lowest persistent
    # height band. This fallback is intentionally conservative.
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
    return [
        name
        for name, height in median_heights
        if height <= lowest_height + CONTACT_ALIGNMENT_DISTANCE_TOLERANCE
    ]


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

    floor_bands = {
        name: percentile(
            [
                support_surface_height(frame.joints[name][1])
                for frame in clip.frames
                if name in frame.joints
            ],
            0.15,
        )
        for name in candidate_names
        if any(name in frame.joints for frame in clip.frames)
    }
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
            vertical_speed = vertical_frame_speed(
                clip,
                frame_index=frame_index,
                joint_name=name,
            )
            if (
                height <= floor_bands[name] + CONTACT_ALIGNMENT_DISTANCE_TOLERANCE + release_margin
                and abs(vertical_speed) <= CONTACT_ALIGNMENT_VERTICAL_SPEED_TOLERANCE
            ):
                frame_contacts.append(name)
        contacts.append(frame_contacts)
        previous_contacts = set(frame_contacts)
    return contacts


def _level_frame_contacts(
    frame: MotionFrame,
    contact_names: list[str],
) -> tuple[MotionFrame, float]:
    points = [
        frame.joints[name]
        for name in contact_names
        if name in frame.joints
    ]
    if len(points) < 2:
        return frame, 0.0
    values = np.asarray(points, dtype=np.float64)
    pivot_array = np.mean(values, axis=0)
    source_normal: np.ndarray | None = None
    if len(points) >= 3:
        centered = values - pivot_array
        try:
            _u, singular_values, vh = np.linalg.svd(centered, full_matrices=False)
        except np.linalg.LinAlgError:
            return frame, 0.0
        if len(singular_values) >= 2 and float(singular_values[1]) > 1e-6:
            source_normal = vh[-1]
    if source_normal is None:
        source_axis = values[-1] - values[0]
        horizontal_axis = np.asarray([source_axis[0], 0.0, source_axis[2]])
        source_length = float(np.linalg.norm(source_axis))
        horizontal_length = float(np.linalg.norm(horizontal_axis))
        if source_length <= 1e-8 or horizontal_length <= 1e-8:
            return frame, 0.0
        source_normal = source_axis / source_length
        target = horizontal_axis / horizontal_length
    else:
        source_normal = source_normal / max(float(np.linalg.norm(source_normal)), 1e-8)
        if source_normal[1] < 0.0:
            source_normal = -source_normal
        target = np.asarray([0.0, 1.0, 0.0])

    axis = np.cross(source_normal, target)
    axis_length = float(np.linalg.norm(axis))
    alignment = float(np.clip(np.dot(source_normal, target), -1.0, 1.0))
    angle = math.acos(alignment)
    if axis_length <= 1e-8 or angle <= 1e-8:
        return frame, 0.0
    axis = axis / axis_length
    pivot = (float(pivot_array[0]), float(pivot_array[1]), float(pivot_array[2]))
    rotated_joints = {
        name: _rotate_point_rodigues(
            point,
            pivot=pivot,
            axis=(float(axis[0]), float(axis[1]), float(axis[2])),
            angle_radians=angle,
        )
        for name, point in frame.joints.items()
    }
    return (
        MotionFrame(time_sec=frame.time_sec, joints=rotated_joints),
        math.degrees(angle),
    )


def _dominant_contact_pair(
    frame_contacts: list[list[str]],
) -> tuple[str, str] | None:
    pair_counts: dict[tuple[str, str], int] = {}
    for names in frame_contacts:
        if len(names) != 2:
            continue
        pair = (names[0], names[1])
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
    if not pair_counts:
        return None
    pair = max(pair_counts, key=pair_counts.get)
    if pair_counts[pair] < max(2, int(len(frame_contacts) * 0.60)):
        return None
    return pair


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
    axis = (
        second[0] - first[0],
        0.0,
        second[2] - first[2],
    )
    axis_length = math.hypot(axis[0], axis[2])
    if axis_length <= 1e-8:
        return frame
    normalized_axis = (axis[0] / axis_length, 0.0, axis[2] / axis_length)
    pivot = (
        (first[0] + second[0]) * 0.5,
        (first[1] + second[1]) * 0.5,
        (first[2] + second[2]) * 0.5,
    )
    return MotionFrame(
        time_sec=frame.time_sec,
        joints={
            name: _rotate_point_rodigues(
                point,
                pivot=pivot,
                axis=normalized_axis,
                angle_radians=angle_radians,
            )
            for name, point in frame.joints.items()
        },
    )


def _contact_hinge_score(
    frames: list[MotionFrame],
    pair: tuple[str, str],
    *,
    angle_radians: float,
    target_distances: dict[str, float],
) -> float:
    penetration_squared = 0.0
    core_below_squared = 0.0
    measured_distances: dict[str, list[float]] = {}
    sample_count = 0
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
            support_surface_height(point[1])
            for point in contact_points
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
    target_error_squared = sum(
        (
            statistics.median(values) - target_distances[name]
        ) ** 2
        for name, values in measured_distances.items()
    ) / max(1, len(measured_distances))
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
    pair = _dominant_contact_pair(frame_contacts)
    if pair is None:
        return clip, 0.0
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
            constrained_distances = {
                name: distance
                for name, distance in target_distances.items()
                if name in constraint_names
            }
            if constrained_distances:
                target_distances = constrained_distances
    candidate_degrees = range(
        -180,
        181,
        CONTACT_HINGE_SEARCH_STEP_DEGREES,
    )
    best_degrees = min(
        candidate_degrees,
        key=lambda degrees: _contact_hinge_score(
            clip.frames,
            pair,
            angle_radians=math.radians(degrees),
            target_distances=target_distances,
        ),
    )
    if best_degrees == 0:
        return clip, 0.0
    angle_radians = math.radians(best_degrees)
    return (
        replace(
            clip,
            frames=[
                _rotate_frame_about_contact_pair(
                    frame,
                    pair,
                    angle_radians=angle_radians,
                )
                for frame in clip.frames
            ],
        ),
        float(best_degrees),
    )


def _level_dominant_contact_pair_consistently(
    clip: MotionClip,
    frame_contacts: list[list[str]],
) -> tuple[MotionClip, float]:
    pair = _dominant_contact_pair(frame_contacts)
    if pair is None:
        return clip, 0.0
    support_vectors: list[np.ndarray] = []
    support_points: list[Point3] = []
    for frame, names in zip(clip.frames, frame_contacts):
        if pair[0] not in names or pair[1] not in names:
            continue
        first = frame.joints.get(pair[0])
        second = frame.joints.get(pair[1])
        if first is None or second is None:
            continue
        vector = np.asarray(second, dtype=np.float64) - np.asarray(
            first,
            dtype=np.float64,
        )
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
    alignment = float(np.clip(np.dot(source_axis, target_axis), -1.0, 1.0))
    angle = math.acos(alignment)
    if rotation_axis_length <= 1e-8 or angle <= 1e-8:
        return clip, 0.0
    rotation_axis /= rotation_axis_length
    pivot_values = np.median(
        np.asarray(support_points, dtype=np.float64),
        axis=0,
    )
    return (
        _rotate_clip_about_axis(
            clip,
            pivot=(
                float(pivot_values[0]),
                float(pivot_values[1]),
                float(pivot_values[2]),
            ),
            axis=(
                float(rotation_axis[0]),
                float(rotation_axis[1]),
                float(rotation_axis[2]),
            ),
            angle_radians=angle,
        ),
        math.degrees(angle),
    )


def _best_fit_contact_plane_normal(
    clip: MotionClip,
    frame_contacts: list[list[str]],
) -> tuple[Point3, Point3] | None:
    if max((len(set(names)) for names in frame_contacts), default=0) < 3:
        return None
    points = [
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
    axis_length = math.sqrt(sum(value * value for value in axis))
    alignment = max(-1.0, min(1.0, normal[1]))
    angle = math.acos(alignment)
    if axis_length <= 1e-8 or angle <= 1e-8:
        return clip, 0.0
    normalized_axis = tuple(value / axis_length for value in axis)
    return (
        _rotate_clip_about_axis(
            clip,
            pivot=pivot,
            axis=normalized_axis,
            angle_radians=angle,
        ),
        math.degrees(angle),
    )


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


def solve_contact_aware_rigid_world_alignment(
    clip: MotionClip,
    *,
    ground_y: float = 0.0,
) -> tuple[MotionClip, dict[str, object]]:
    """Ground arbitrary motion using only rigid whole-body transforms."""
    from exercise_motion_pkg.temporal_contact_solver import (
        solve_temporal_contact_rigid_world_alignment,
    )

    # Temporal solver encapsulates contact inference (from timestamped video
    # observations) plus the clip-wide rigid alignment and collision clamping.
    # We keep this wrapper for backwards compatibility with the existing tests.
    return solve_temporal_contact_rigid_world_alignment(clip, ground_y=ground_y)

    candidate_names = _generic_contact_candidates(clip)
    if not candidate_names:
        return clip, {
            "applied": False,
            "solver": "contact_aware_rigid_world_alignment",
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
            "solver": "contact_aware_rigid_world_alignment",
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
        pivot_values = np.median(
            np.asarray(support_points, dtype=np.float64),
            axis=0,
        )
        aligned, rotation_degrees = _rotate_clip_normal_to_world_up(
            clip,
            normal=authoritative_normal,
            pivot=(
                float(pivot_values[0]),
                float(pivot_values[1]),
                float(pivot_values[2]),
            ),
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
        aligned, contact_pair_leveling_degrees = (
            _level_dominant_contact_pair_consistently(
                aligned,
                frame_contacts,
            )
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
        corrections.append(
            ground_y - min(heights)
            if heights
            else None
        )
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
                ground_y
                + NON_PENETRATION_CLEARANCE
                - support_surface_height(point[1]),
            )
            local_penetration_corrections.append(correction)
            projected_joints[name] = (
                point[0],
                point[1] + correction,
                point[2],
            )
        grounded_frames.append(
            MotionFrame(time_sec=frame.time_sec, joints=projected_joints)
        )
    grounded = replace(aligned, frames=grounded_frames)
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


def _strong_torso_to_floor_reorientation_for_kneeling(
    clip: MotionClip,
    *,
    ground_y: float,
    sagittal_pitch_degrees: float | None,
) -> MotionClip:
    """
    Rigidly orient a kneeling reconstruction so its torso is floor-parallel.

    The same transform is applied to every joint, preserving WHAM's articulated
    pose and all inter-joint distances.
    """
    median_vert = _median_spine_verticality(clip)
    torso_axis = _estimate_torso_axis_average(clip)
    if median_vert is None or torso_axis is None:
        return clip
    if sagittal_pitch_degrees is not None and abs(sagittal_pitch_degrees) >= 60.0:
        return clip
    if median_vert <= 0.35:
        return clip
    # Note: we intentionally do not gate on sagittalPitchDegrees here. In
    # some configurations the kneeling solver pitch can be applied in a
    # way that does not result in a horizontal rendered torso, so we use the
    # measured torso verticality instead.

    # Floor-aligned target: projection of torso axis onto Y=0 plane.
    target = (torso_axis[0], 0.0, torso_axis[2])
    target_len = math.sqrt(target[0] * target[0] + target[2] * target[2])
    if target_len <= 1e-6:
        return clip
    target = (target[0] / target_len, 0.0, target[2] / target_len)

    # Axis-angle rotation: rotate torso_axis -> target.
    axis = (
        torso_axis[1] * target[2] - torso_axis[2] * target[1],
        torso_axis[2] * target[0] - torso_axis[0] * target[2],
        torso_axis[0] * target[1] - torso_axis[1] * target[0],
    )
    axis_len = math.sqrt(axis[0] * axis[0] + axis[1] * axis[1] + axis[2] * axis[2])
    if axis_len <= 1e-6:
        return clip
    axis = (axis[0] / axis_len, axis[1] / axis_len, axis[2] / axis_len)
    dot = max(-1.0, min(1.0, torso_axis[0] * target[0] + torso_axis[1] * target[1] + torso_axis[2] * target[2]))
    angle = math.acos(dot)
    if not math.isfinite(angle) or angle <= 1e-6:
        return clip

    pelvis_points: list[Point3] = []
    for frame in clip.frames:
        p = frame.joints.get("pelvis")
        if p is not None:
            pelvis_points.append(p)
    if pelvis_points:
        pivot = (
            statistics.median(p[0] for p in pelvis_points),
            statistics.median(p[1] for p in pelvis_points),
            statistics.median(p[2] for p in pelvis_points),
        )
    else:
        knee_points: list[Point3] = []
        for frame in clip.frames:
            for joint_name in ("left_knee", "right_knee"):
                p = frame.joints.get(joint_name)
                if p is not None:
                    knee_points.append(p)
        if not knee_points:
            return clip
        pivot = (
            statistics.median(p[0] for p in knee_points),
            ground_y,
            statistics.median(p[2] for p in knee_points),
        )

    rotated = _rotate_clip_about_axis(
        clip,
        pivot=pivot,
        axis=axis,
        angle_radians=angle,
    )
    return place_support_joints_on_floor(
        rotated,
        [*LEFT_KNEE_GROUP, *RIGHT_KNEE_GROUP],
    )


@dataclass(frozen=True)
class CleanupStats:
    input_frames: int
    output_frames: int
    trimmed_start_frames: int
    trimmed_end_frames: int
    average_root_height_before: float
    average_root_height_after: float


def cleanup_motion_clip(
    clip: MotionClip,
    *,
    one_euro_min_cutoff: float = ONE_EURO_MIN_CUTOFF,
    one_euro_beta: float = ONE_EURO_BETA,
    one_euro_derivative_cutoff: float = ONE_EURO_D_CUTOFF,
    motion_threshold: float = 0.015,
    padding_frames: int = 3,
    ground_contact_mode: str = "unknown",
    support_mode_hint: str | None = None,
) -> tuple[MotionClip, CleanupStats]:
    repaired_clip, repaired_joint_outliers = repair_isolated_joint_position_outliers(clip)
    trimmed_clip, start_trim, end_trim = trim_static_edges(
        repaired_clip,
        motion_threshold=motion_threshold,
        padding_frames=padding_frames,
    )
    root_joint = find_first_joint(trimmed_clip, DEFAULT_ROOT_JOINTS)
    avg_root_before = average_joint_axis(trimmed_clip, root_joint, axis=1)
    support_mode = detect_support_mode(trimmed_clip, support_mode_hint=support_mode_hint)
    preserve_video_floor_orientation = clip_preserves_video_floor_orientation(trimmed_clip)
    preserve_horizontal_orientation = support_mode in {
        "horizontal_unspecified",
        "supine",
        "prone",
    }
    raw_support_states = detect_support_contact_states(trimmed_clip, support_mode=support_mode)
    grounded = (
        trimmed_clip
        if preserve_horizontal_orientation
        else ground_to_floor(
            trimmed_clip,
            support_states=raw_support_states,
            support_mode=support_mode,
        )
    )
    support_states = detect_support_contact_states(grounded, support_mode=support_mode)
    support_ground_y = estimate_support_ground_height(grounded, support_states)
    support_stabilized = (
        grounded
        if preserve_horizontal_orientation
        else stabilize_global_translation_from_support_contacts(
            grounded,
            contact_states=support_states,
            support_ground_y=support_ground_y,
        )
    )
    smoothed = smooth_root_translation(
        support_stabilized,
        root_joint=root_joint,
        min_cutoff=one_euro_min_cutoff,
        beta=one_euro_beta,
        derivative_cutoff=one_euro_derivative_cutoff,
    )
    if preserve_horizontal_orientation:
        vertically_grounded = smoothed
        vertical_grounding = {
            "applied": False,
            "groundContactMode": str(ground_contact_mode or "unknown").strip().casefold(),
            "reason": "horizontal_support_orientation_requires_explicit_solver",
        }
    else:
        vertically_grounded, vertical_grounding = stabilize_vertical_floor_contact(
            smoothed,
            ground_contact_mode=(
                "continuous" if uses_knee_floor_support(support_mode) else ground_contact_mode
            ),
        )
    if preserve_video_floor_orientation:
        support_constrained, support_constraint = solve_contact_aware_rigid_world_alignment(
            trimmed_clip,
            ground_y=0.0,
        )
        if support_mode == "kneeling":
            solved_ground_y = support_constraint.get("groundY")
            knee_ground_y = (
                float(solved_ground_y)
                if isinstance(solved_ground_y, (int, float))
                else 0.0
            )
            support_constrained, support_constraint = apply_kneeling_knee_lock(
                support_constrained,
                support_constraint,
                ground_y=knee_ground_y,
            )
    elif uses_knee_floor_support(support_mode):
        contact_states = detect_support_contact_states(
            vertically_grounded,
            support_mode=support_mode,
        )
        support_joint_names = None
        proximal_joint_names = None
        used_shin_plane = False
        if support_mode == "kneeling":
            used_shin_plane = kneeling_reconstruction_gravity_is_swapped(vertically_grounded)
            support_joint_names = kneeling_support_pitch_joint_names(vertically_grounded)
            proximal_joint_names = kneeling_hip_joint_names(vertically_grounded)
        support_constrained, support_constraint = solve_quadruped_support(
            vertically_grounded,
            contact_states=contact_states,
            support_joint_names=support_joint_names,
            proximal_joint_names=proximal_joint_names,
        )
        if support_mode == "kneeling":
            support_constraint = dict(support_constraint)
            support_constraint["solver"] = "kneeling_support"
            support_constraint["strategy"] = (
                "rigid_kneeling_knee_shin_gravity_plane_alignment"
                if used_shin_plane
                else "rigid_kneeling_knee_support_plane_alignment"
            )
            support_constraint["gravitySwapCorrection"] = used_shin_plane
            support_constrained = place_support_joints_on_floor(
                support_constrained,
                [*LEFT_KNEE_GROUP, *RIGHT_KNEE_GROUP],
            )
            support_constrained, support_constraint = apply_kneeling_knee_lock(
                support_constrained,
                support_constraint,
                ground_y=support_ground_y,
            )
            support_constrained = _strong_torso_to_floor_reorientation_for_kneeling(
                support_constrained,
                ground_y=support_ground_y,
                sagittal_pitch_degrees=support_constraint.get("sagittalPitchDegrees") if isinstance(support_constraint, dict) else None,
            )
    else:
        support_constrained = vertically_grounded
        support_constraint = {
            "applied": False,
            "reason": (
                "horizontal_support_orientation_requires_explicit_solver"
                if preserve_horizontal_orientation
                else "upright_support_uses_existing_grounding"
            ),
        }
    final_support_states = detect_support_contact_states(
        support_constrained,
        support_mode=support_mode,
    )
    final_support_ground_y = estimate_support_ground_height(
        support_constrained,
        final_support_states,
    )
    solved_ground_y = support_constraint.get("groundY")
    uses_authoritative_solved_ground = (
        support_mode == "quadruped"
        or support_constraint.get("strategy") == "generic_video_contact_rigid_alignment"
    )
    if uses_authoritative_solved_ground and isinstance(solved_ground_y, (int, float)):
        final_support_ground_y = float(solved_ground_y)
    avg_root_after = average_joint_axis(support_constrained, root_joint, axis=1)
    support_profile = _summarize_support_states(final_support_states)
    stats = CleanupStats(
        input_frames=clip.frame_count,
        output_frames=vertically_grounded.frame_count,
        trimmed_start_frames=start_trim,
        trimmed_end_frames=end_trim,
        average_root_height_before=avg_root_before,
        average_root_height_after=avg_root_after,
    )
    metadata = dict(vertically_grounded.metadata)
    metadata["cleanup"] = {
        "oneEuroMinCutoff": one_euro_min_cutoff,
        "oneEuroBeta": one_euro_beta,
        "oneEuroDerivativeCutoff": one_euro_derivative_cutoff,
        "motionThreshold": motion_threshold,
        "paddingFrames": padding_frames,
        "smoothingMethod": "support_stabilization_plus_one_euro_root_translation_xz",
        "trimmedStartFrames": start_trim,
        "trimmedEndFrames": end_trim,
        "rootJoint": root_joint,
        "supportGroundY": final_support_ground_y,
        "supportMode": support_mode,
        "appliedPostProcessingSteps": [
            "isolated_joint_position_outlier_repair",
            "ground_plane_fitting",
            "support_global_translation_stabilization",
            "root_translation_one_euro_xz",
            "contract_aware_vertical_grounding",
            "support_contact_detection",
        ],
        "supportProfile": support_profile,
        "repairedJointPositionOutliers": repaired_joint_outliers,
        "verticalGrounding": vertical_grounding,
        "supportSurfaceConstraint": support_constraint,
        "footContacts": final_support_states,
        "reviewStatus": "needs_manual_review",
    }
    return MotionClip(
        fps=support_constrained.fps,
        joint_names=support_constrained.joint_names,
        frames=support_constrained.frames,
        source=support_constrained.source,
        metadata=metadata,
    ), stats


def stabilize_vertical_floor_contact(
    clip: MotionClip,
    *,
    ground_contact_mode: str,
    median_window: int = VERTICAL_GROUNDING_MEDIAN_WINDOW,
) -> tuple[MotionClip, dict[str, object]]:
    """Remove vertical root drift without changing the articulated pose."""
    normalized_mode = str(ground_contact_mode or "unknown").strip().casefold()
    if normalized_mode not in {"continuous", "intermittent"} or clip.frame_count < 2:
        return clip, {
            "applied": False,
            "groundContactMode": normalized_mode,
            "reason": (
                "insufficient_frames"
                if clip.frame_count < 2
                else "ground_contact_mode_does_not_allow_grounding"
            ),
        }

    lower_envelope = [min(point[1] for point in frame.joints.values()) for frame in clip.frames]
    floor_height = percentile(lower_envelope, 0.10)
    smoothed_envelope = rolling_median(lower_envelope, window=median_window)
    if normalized_mode == "continuous":
        corrected_mask = [True] * clip.frame_count
        corrections = [height - floor_height for height in smoothed_envelope]
    else:
        contact_tolerance = max(0.06, median_motion_body_height(clip) * 0.05)
        corrected_mask = [height <= floor_height + contact_tolerance for height in smoothed_envelope]
        corrections = [
            height - floor_height if corrected else 0.0
            for height, corrected in zip(smoothed_envelope, corrected_mask)
        ]
    if not any(corrected_mask):
        return clip, {
            "applied": False,
            "groundContactMode": normalized_mode,
            "reason": "no_floor_contact_frames",
        }

    grounded_frames = [
        MotionFrame(
            time_sec=frame.time_sec,
            joints={
                name: (point[0], point[1] - correction, point[2])
                for name, point in frame.joints.items()
            },
        )
        for frame, correction in zip(clip.frames, corrections)
    ]
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=grounded_frames,
        source=clip.source,
        metadata=clip.metadata,
    ), {
        "applied": True,
        "groundContactMode": normalized_mode,
        "floorHeight": floor_height,
        "medianWindowFrames": median_window,
        "correctedFrameCount": sum(corrected_mask),
        "maxAbsCorrection": max(abs(value) for value in corrections),
    }


SUPPORT_CHAIN_CONSTRAINTS = {
    "left_hand": ("left_wrist", ()),
    "right_hand": ("right_wrist", ()),
    "left_knee": ("left_hip", ("left_ankle", "left_foot")),
    "right_knee": ("right_hip", ("right_ankle", "right_foot")),
    "left_foot": ("left_ankle", ()),
    "right_foot": ("right_ankle", ()),
}


def solve_quadruped_support(
    clip: MotionClip,
    *,
    contact_states: list[dict[str, object]],
    support_joint_names: list[str] | None = None,
    proximal_joint_names: list[str] | None = None,
) -> tuple[MotionClip, dict[str, object]]:
    forward_axis = _horizontal_torso_axis(clip)
    if forward_axis is None:
        return constrain_support_surfaces(clip, contact_states=contact_states)
    if support_joint_names is None:
        support_joint_names = sorted({
            joint_name
            for state in contact_states
            for joint_name in iter_contact_joint_names(state)
        })
    else:
        support_joint_names = [name for name in support_joint_names if name in clip.joint_names]
    proximal_joint_names = [
        name
        for name in (proximal_joint_names or [])
        if name in clip.joint_names
    ]
    centered_support_samples: list[tuple[float, float]] = []
    for frame in clip.frames:
        samples = [
            (
                frame.joints[joint_name][0] * forward_axis[0]
                + frame.joints[joint_name][2] * forward_axis[2],
                support_surface_height(frame.joints[joint_name][1]),
            )
            for joint_name in support_joint_names
            if joint_name in frame.joints
        ]
        if len(samples) < 2:
            continue
        mean_forward = sum(sample[0] for sample in samples) / len(samples)
        mean_height = sum(sample[1] for sample in samples) / len(samples)
        centered_support_samples.extend(
            (forward - mean_forward, height - mean_height)
            for forward, height in samples
        )
    if not centered_support_samples:
        return constrain_support_surfaces(clip, contact_states=contact_states)
    pitch_radians = _minimum_variance_support_plane_pitch(centered_support_samples)
    pivot_samples = [
        frame.joints[joint_name]
        for frame in clip.frames
        for joint_name in support_joint_names
        if joint_name in frame.joints
    ]
    if not pivot_samples:
        return constrain_support_surfaces(clip, contact_states=contact_states)
    pivot = (
        statistics.median(point[0] for point in pivot_samples),
        statistics.median(point[1] for point in pivot_samples),
        statistics.median(point[2] for point in pivot_samples),
    )
    lateral_axis = (forward_axis[2], 0.0, -forward_axis[0])
    if proximal_joint_names:
        pitch_radians = _support_plane_pitch_with_proximal_above(
            clip,
            axis=lateral_axis,
            pivot=pivot,
            pitch_radians=pitch_radians,
            proximal_joint_names=proximal_joint_names,
            support_joint_names=support_joint_names,
        )
    rotated_clip = _rotate_clip_about_axis(
        clip,
        axis=lateral_axis,
        angle_radians=pitch_radians,
        pivot=pivot,
    )
    surface_residuals = [
        support_surface_height(frame.joints[joint_name][1])
        for frame in rotated_clip.frames
        for joint_name in support_joint_names
        if joint_name in frame.joints
    ]
    ground_y = statistics.median(surface_residuals)
    centered_residuals = [value - ground_y for value in surface_residuals]
    return rotated_clip, {
        "applied": abs(pitch_radians) > 1e-8,
        "strategy": "rigid_quadruped_support_plane_alignment",
        "supportJoints": support_joint_names,
        "groundY": ground_y,
        "maximumCorrection": 0.0,
        "maximumAbsContactResidual": max(
            (abs(value) for value in centered_residuals),
            default=0.0,
        ),
        "medianAbsContactResidual": statistics.median(
            abs(value) for value in centered_residuals
        ),
        "solver": "quadruped_support",
        "sagittalPitchRadians": pitch_radians,
        "sagittalPitchDegrees": math.degrees(pitch_radians),
        "pitchSampleCount": len(centered_support_samples),
        "pitchSource": "analytic_minimum_variance_continuous_support_plane",
        "rotationPivot": list(pivot),
        "rotationAxis": list(lateral_axis),
    }


def _minimum_variance_support_plane_pitch(
    samples: list[tuple[float, float]],
) -> float:
    forward_variance = sum(forward * forward for forward, _height in samples)
    height_variance = sum(height * height for _forward, height in samples)
    covariance = sum(forward * height for forward, height in samples)
    base_angle = 0.5 * math.atan2(
        2.0 * covariance,
        forward_variance - height_variance,
    )
    candidates = (base_angle, base_angle + math.pi / 2.0)
    best_angle = min(
        candidates,
        key=lambda angle: sum(
            (height * math.cos(angle) - forward * math.sin(angle)) ** 2
            for forward, height in samples
        ),
    )
    while best_angle > math.pi / 2.0:
        best_angle -= math.pi
    while best_angle < -math.pi / 2.0:
        best_angle += math.pi
    return best_angle


def _support_plane_pitch_with_proximal_above(
    clip: MotionClip,
    *,
    axis: Point3,
    pivot: Point3,
    pitch_radians: float,
    proximal_joint_names: list[str],
    support_joint_names: list[str],
) -> float:
    def proximal_above_support(angle_radians: float) -> float:
        rotated = _rotate_clip_about_axis(
            clip,
            axis=axis,
            angle_radians=angle_radians,
            pivot=pivot,
        )
        proximal_height = _median_joint_height(rotated, proximal_joint_names)
        support_height = _median_joint_height(rotated, support_joint_names)
        if proximal_height is None or support_height is None:
            return float("-inf")
        return proximal_height - support_height

    return max((pitch_radians, -pitch_radians), key=proximal_above_support)


def _horizontal_torso_axis(clip: MotionClip) -> Point3 | None:
    samples = []
    for frame in clip.frames:
        pelvis = frame.joints.get("pelvis")
        neck = frame.joints.get("neck")
        if pelvis is None or neck is None:
            continue
        samples.append((neck[0] - pelvis[0], 0.0, neck[2] - pelvis[2]))
    if not samples:
        return None
    axis = (
        statistics.median(point[0] for point in samples),
        0.0,
        statistics.median(point[2] for point in samples),
    )
    length = math.hypot(axis[0], axis[2])
    if length <= 1e-6:
        return None
    return (axis[0] / length, 0.0, axis[2] / length)


def _rotate_clip_about_axis(
    clip: MotionClip,
    *,
    axis: Point3,
    angle_radians: float,
    pivot: Point3,
) -> MotionClip:
    cosine = math.cos(angle_radians)
    sine = math.sin(angle_radians)
    rotated_frames = []
    for frame in clip.frames:
        joints = {}
        for name, point in frame.joints.items():
            relative = (
                point[0] - pivot[0],
                point[1] - pivot[1],
                point[2] - pivot[2],
            )
            cross = (
                axis[1] * relative[2] - axis[2] * relative[1],
                axis[2] * relative[0] - axis[0] * relative[2],
                axis[0] * relative[1] - axis[1] * relative[0],
            )
            axis_dot = sum(axis[index] * relative[index] for index in range(3))
            rotated = tuple(
                relative[index] * cosine
                + cross[index] * sine
                + axis[index] * axis_dot * (1.0 - cosine)
                + pivot[index]
                for index in range(3)
            )
            joints[name] = rotated
        rotated_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=rotated_frames,
        source=clip.source,
        metadata=clip.metadata,
    )


def constrain_support_surfaces(
    clip: MotionClip,
    *,
    contact_states: list[dict[str, object]],
    minimum_contact_ratio: float = 0.60,
) -> tuple[MotionClip, dict[str, object]]:
    if clip.frame_count == 0 or not contact_states:
        return clip, {"applied": False, "reason": "no_contact_states"}
    contact_counts: dict[str, int] = {}
    for state in contact_states:
        for joint_name in iter_contact_joint_names(state):
            contact_counts[joint_name] = contact_counts.get(joint_name, 0) + 1
    continuous_joints = [
        joint_name
        for joint_name, count in contact_counts.items()
        if count / clip.frame_count >= minimum_contact_ratio
        and joint_name in SUPPORT_CHAIN_CONSTRAINTS
    ]
    if not continuous_joints:
        return clip, {"applied": False, "reason": "no_continuous_supported_chains"}
    surface_samples = [
        support_surface_height(frame.joints[joint_name][1])
        for frame in clip.frames
        for joint_name in continuous_joints
        if joint_name in frame.joints
    ]
    if not surface_samples:
        return clip, {"applied": False, "reason": "missing_support_joint_samples"}
    minimum_reachable_ground_heights = []
    for frame in clip.frames:
        for joint_name in continuous_joints:
            parent_name, _descendants = SUPPORT_CHAIN_CONSTRAINTS[joint_name]
            joint = frame.joints.get(joint_name)
            parent = frame.joints.get(parent_name)
            if joint is None or parent is None:
                continue
            minimum_reachable_ground_heights.append(
                parent[1] - math.dist(parent, joint) - UNIFORM_CAPSULE_RADIUS
            )
    ground_y = max(
        percentile(surface_samples, 0.10),
        max(minimum_reachable_ground_heights, default=float("-inf")),
    )
    target_joint_y = support_joint_height_for_surface(ground_y)
    corrected_frames: list[MotionFrame] = []
    maximum_correction = 0.0
    corrected_samples = 0
    for frame in clip.frames:
        joints = dict(frame.joints)
        for joint_name in continuous_joints:
            parent_name, descendants = SUPPORT_CHAIN_CONSTRAINTS[joint_name]
            joint = joints.get(joint_name)
            parent = joints.get(parent_name)
            if joint is None or parent is None:
                continue
            corrected_joint = _solve_supported_joint_height(
                parent=parent,
                joint=joint,
                target_y=target_joint_y,
            )
            correction = (
                corrected_joint[0] - joint[0],
                corrected_joint[1] - joint[1],
                corrected_joint[2] - joint[2],
            )
            correction_length = math.sqrt(sum(value * value for value in correction))
            if correction_length <= 1e-6:
                continue
            joints[joint_name] = corrected_joint
            for descendant_name in descendants:
                descendant = joints.get(descendant_name)
                if descendant is not None:
                    joints[descendant_name] = (
                        descendant[0] + correction[0],
                        descendant[1] + correction[1],
                        descendant[2] + correction[2],
                    )
            maximum_correction = max(maximum_correction, correction_length)
            corrected_samples += 1
        corrected_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=corrected_frames,
        source=clip.source,
        metadata=clip.metadata,
    ), {
        "applied": corrected_samples > 0,
        "strategy": "continuous_support_surface_bone_length_preserving_rotation",
        "supportJoints": continuous_joints,
        "groundY": ground_y,
        "correctedSamples": corrected_samples,
        "maximumCorrection": maximum_correction,
    }


def _solve_supported_joint_height(
    *,
    parent: Point3,
    joint: Point3,
    target_y: float,
) -> Point3:
    bone_length = math.dist(parent, joint)
    vertical = min(max(target_y - parent[1], -bone_length), bone_length)
    horizontal_length = math.sqrt(max(0.0, bone_length * bone_length - vertical * vertical))
    horizontal_x = joint[0] - parent[0]
    horizontal_z = joint[2] - parent[2]
    current_horizontal_length = math.hypot(horizontal_x, horizontal_z)
    if current_horizontal_length <= 1e-6:
        horizontal_direction = (1.0, 0.0)
    else:
        horizontal_direction = (
            horizontal_x / current_horizontal_length,
            horizontal_z / current_horizontal_length,
        )
    return (
        parent[0] + horizontal_direction[0] * horizontal_length,
        parent[1] + vertical,
        parent[2] + horizontal_direction[1] * horizontal_length,
    )


def rolling_median(values: list[float], *, window: int) -> list[float]:
    radius = max(0, int(window) // 2)
    return [
        statistics.median(values[max(0, index - radius) : min(len(values), index + radius + 1)])
        for index in range(len(values))
    ]


def repair_isolated_joint_position_outliers(
    clip: MotionClip,
    *,
    step_ratio_threshold: float = KINEMATIC_OUTLIER_STEP_RATIO,
    body_ratio_threshold: float = KINEMATIC_OUTLIER_BODY_RATIO,
    max_run_steps: int = KINEMATIC_OUTLIER_MAX_RUN_STEPS,
) -> tuple[MotionClip, list[dict[str, object]]]:
    """Interpolate only short joint-local jumps that return to the tracked path.

    Measurements are root-relative so legitimate whole-body translation is not
    altered. A run must have a stable sample on both sides; persistent tracking
    loss and boundary discontinuities are deliberately left for validation to
    reject.
    """
    if clip.frame_count < 4 or max_run_steps < 2:
        return clip, []
    root_joint = find_first_joint(clip, DEFAULT_ROOT_JOINTS)
    body_height = median_motion_body_height(clip)
    if body_height <= 1e-6:
        return clip, []

    frame_joints = [dict(frame.joints) for frame in clip.frames]
    repairs: list[dict[str, object]] = []
    for joint_name in clip.joint_names:
        if joint_name == root_joint:
            continue
        relative_points = [
            tuple(frame.joints[joint_name][axis] - frame.joints[root_joint][axis] for axis in range(3))
            for frame in clip.frames
        ]
        steps = [point_distance_3d(relative_points[index - 1], relative_points[index]) for index in range(1, len(relative_points))]
        positive_steps = [step for step in steps if step > 1e-7]
        if len(positive_steps) < 2:
            continue
        median_step = statistics.median(positive_steps)
        if median_step <= 1e-7:
            continue
        outlier_step_indices = [
            index
            for index, step in enumerate(steps, start=1)
            if step / median_step >= step_ratio_threshold and step / body_height >= body_ratio_threshold
        ]
        for run_start, run_end in consecutive_integer_runs(outlier_step_indices):
            run_steps = run_end - run_start + 1
            # Two consecutive jump steps identify an interior point (or short
            # span) that leaves and returns to the surrounding tracked path.
            if run_steps != 2 or run_steps > max_run_steps:
                continue
            first_repaired_frame = run_start
            last_repaired_frame = run_end - 1
            left_frame = first_repaired_frame - 1
            right_frame = last_repaired_frame + 1
            if left_frame < 0 or right_frame >= clip.frame_count:
                continue
            left_point = frame_joints[left_frame][joint_name]
            right_point = frame_joints[right_frame][joint_name]
            repaired_count = last_repaired_frame - first_repaired_frame + 1
            for offset, frame_index in enumerate(range(first_repaired_frame, last_repaired_frame + 1), start=1):
                weight = offset / (repaired_count + 1)
                frame_joints[frame_index][joint_name] = tuple(
                    left_point[axis] * (1.0 - weight) + right_point[axis] * weight
                    for axis in range(3)
                )
            repairs.append(
                {
                    "joint": joint_name,
                    "firstFrame": first_repaired_frame,
                    "lastFrame": last_repaired_frame,
                    "outlierStepCount": run_steps,
                }
            )
    if not repairs:
        return clip, []
    repaired_frames = [
        MotionFrame(time_sec=frame.time_sec, joints=frame_joints[index])
        for index, frame in enumerate(clip.frames)
    ]
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=repaired_frames,
        source=clip.source,
        metadata=clip.metadata,
    ), repairs


def consecutive_integer_runs(values: list[int]) -> list[tuple[int, int]]:
    if not values:
        return []
    runs: list[tuple[int, int]] = []
    run_start = previous = values[0]
    for value in values[1:]:
        if value != previous + 1:
            runs.append((run_start, previous))
            run_start = value
        previous = value
    runs.append((run_start, previous))
    return runs


def median_motion_body_height(clip: MotionClip) -> float:
    heights = []
    for frame in clip.frames:
        y_values = [point[1] for point in frame.joints.values()]
        if y_values:
            heights.append(max(y_values) - min(y_values))
    return statistics.median(heights) if heights else 0.0


def point_distance_3d(left: Point3, right: Point3) -> float:
    return math.sqrt(sum((left[axis] - right[axis]) ** 2 for axis in range(3)))


def smooth_root_translation(
    clip: MotionClip,
    *,
    root_joint: str,
    min_cutoff: float,
    beta: float,
    derivative_cutoff: float,
) -> MotionClip:
    if clip.frame_count < 2:
        return clip

    smoothed_frames: list[MotionFrame] = []
    previous_filtered_root = clip.frames[0].joints[root_joint]
    previous_filtered_derivative: Point3 = (0.0, 0.0, 0.0)

    smoothed_frames.append(clip.frames[0])
    for index, frame in enumerate(clip.frames[1:], start=1):
        delta_time = max(frame.time_sec - clip.frames[index - 1].time_sec, 1e-6)
        current_root = frame.joints[root_joint]
        filtered_root, filtered_derivative = one_euro_filter_point(
            current_point=current_root,
            previous_filtered_point=previous_filtered_root,
            previous_filtered_derivative=previous_filtered_derivative,
            delta_time=delta_time,
            min_cutoff=min_cutoff,
            beta=beta,
            derivative_cutoff=derivative_cutoff,
        )
        delta = (
            filtered_root[0] - current_root[0],
            0.0,
            filtered_root[2] - current_root[2],
        )
        smoothed_joints = {
            name: (coords[0] + delta[0], coords[1] + delta[1], coords[2] + delta[2])
            for name, coords in frame.joints.items()
        }
        smoothed_frames.append(MotionFrame(time_sec=frame.time_sec, joints=smoothed_joints))
        previous_filtered_root = filtered_root
        previous_filtered_derivative = filtered_derivative

    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=smoothed_frames,
        source=clip.source,
        metadata=clip.metadata,
    )


def trim_static_edges(
    clip: MotionClip,
    *,
    motion_threshold: float,
    padding_frames: int,
) -> tuple[MotionClip, int, int]:
    if clip.frame_count <= 2:
        return clip, 0, 0
    active_indices = find_active_motion_indices(clip, motion_threshold=motion_threshold)
    if not active_indices:
        return clip, 0, 0
    start_frame = max(0, active_indices[0] - padding_frames)
    end_frame = min(clip.frame_count - 1, active_indices[-1] + padding_frames)
    sliced_frames = clip.frames[start_frame : end_frame + 1]
    rebased = [
        MotionFrame(time_sec=index / clip.fps, joints=frame.joints)
        for index, frame in enumerate(sliced_frames)
    ]
    return (
        MotionClip(
            fps=clip.fps,
            joint_names=clip.joint_names,
            frames=rebased,
            source=clip.source,
            metadata=clip.metadata,
        ),
        start_frame,
        clip.frame_count - end_frame - 1,
    )


def find_active_motion_indices(clip: MotionClip, *, motion_threshold: float) -> list[int]:
    active_indices: list[int] = []
    reference_frame = clip.frames[0]
    for index in range(1, clip.frame_count):
        immediate_delta = frame_motion_delta(clip.frames[index - 1], clip.frames[index])
        cumulative_delta = frame_motion_delta(reference_frame, clip.frames[index])
        if immediate_delta >= motion_threshold or cumulative_delta >= motion_threshold:
            active_indices.append(index)
            reference_frame = clip.frames[index]
    return active_indices


def ground_to_floor(
    clip: MotionClip,
    *,
    floor_height: float | None = None,
    support_states: list[dict[str, object]] | None = None,
    support_mode: str = "upright",
) -> MotionClip:
    support_joint_names = support_joint_names_for_mode(clip, support_mode)
    if not support_joint_names:
        return clip
    if floor_height is None:
        lowest_support_height = min(
            support_surface_height(frame.joints[joint][1])
            for frame in clip.frames
            for joint in support_joint_names
        )
        candidates = estimate_support_floor_height(
            clip,
            support_states if support_states is not None else [],
            support_joint_names=support_joint_names,
        )
        if not math.isfinite(candidates):
            floor_height = lowest_support_height
        else:
            floor_height = min(candidates, lowest_support_height)
    grounded_frames = []
    for frame in clip.frames:
        grounded_joints = {
            name: (coords[0], coords[1] - floor_height, coords[2])
            for name, coords in frame.joints.items()
        }
        grounded_frames.append(MotionFrame(time_sec=frame.time_sec, joints=grounded_joints))
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=grounded_frames,
        source=clip.source,
        metadata=clip.metadata,
    )




def estimate_support_ground_height(
    clip: MotionClip,
    contact_states: list[dict[str, object]],
) -> float:
    support_heights: list[float] = []
    for index, state in enumerate(contact_states):
        if state.get("state") == "airborne":
            continue
        frame = clip.frames[index]
        for joint_name in iter_contact_joint_names(state):
            coords = frame.joints.get(joint_name)
            if coords is not None:
                # Support-ground height is represented in the same space as the
                # reconstructed joint Y coordinates.
                support_heights.append(float(coords[1]))
    if not support_heights:
        return 0.0
    return percentile(support_heights, SUPPORT_GROUND_HEIGHT_QUANTILE)


def estimate_support_floor_height(
    clip: MotionClip,
    contact_states: list[dict[str, object]],
    *,
    support_joint_names: list[str] | None = None,
) -> float:
    support_joint_names = support_joint_names or [
        joint for joint in DEFAULT_FOOT_JOINTS if joint in clip.joint_names
    ]
    candidate_heights: list[float] = []
    if support_joint_names:
        for frame_index, frame in enumerate(clip.frames):
            state = contact_states[frame_index] if frame_index < len(contact_states) else None
            if isinstance(state, dict):
                for joint_name in iter_contact_joint_names(state):
                    point = frame.joints.get(joint_name)
                    if point is not None:
                        candidate_heights.append(support_surface_height(point[1]))
            if not isinstance(state, dict) or not _support_state_has_ground_contact(state):
                for joint_name in support_joint_names:
                    point = frame.joints.get(joint_name)
                    if point is not None:
                        candidate_heights.append(support_surface_height(point[1]))
    if not candidate_heights:
        return float("nan")
    return percentile(candidate_heights, FOOT_CONTACT_GROUND_QUANTILE)


def place_support_joints_on_floor(
    clip: MotionClip,
    joint_names: list[str],
) -> MotionClip:
    support_names = [name for name in joint_names if name in clip.joint_names]
    heights = [
        support_surface_height(frame.joints[name][1])
        for frame in clip.frames
        for name in support_names
        if name in frame.joints
    ]
    if not heights:
        return clip
    delta = -statistics.median(heights)
    if abs(delta) <= 1e-8:
        return clip
    placed_frames = [
        MotionFrame(
            time_sec=frame.time_sec,
            joints={
                name: (point[0], point[1] + delta, point[2])
                for name, point in frame.joints.items()
            },
        )
        for frame in clip.frames
    ]
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=placed_frames,
        source=clip.source,
        metadata=clip.metadata,
    )


def apply_kneeling_knee_lock(
    clip: MotionClip,
    support_constraint: dict[str, object],
    *,
    ground_y: float,
) -> tuple[MotionClip, dict[str, object]]:
    locked_clip, lock_metadata = lock_planted_support_joints(
        clip,
        [*LEFT_KNEE_GROUP, *RIGHT_KNEE_GROUP],
        ground_y=ground_y,
        preserve_chain_lengths=True,
    )
    updated = dict(support_constraint)
    updated["kneeLock"] = lock_metadata
    if lock_metadata.get("applied"):
        updated["applied"] = True
    return locked_clip, updated


def lock_planted_support_joints(
    clip: MotionClip,
    joint_names: list[str],
    *,
    ground_y: float = 0.0,
    preserve_chain_lengths: bool = False,
) -> tuple[MotionClip, dict[str, object]]:
    """Pin support joints to a stable floor anchor without moving the whole body.

    Kneeling rollouts keep the knees planted while the torso travels. A global
    root correction would cancel that travel, so only the support joints and
    their distal chain are locked.
    """
    support_names = [name for name in joint_names if name in clip.joint_names]
    if not support_names or not clip.frames:
        return clip, {"applied": False, "reason": "no_support_joints"}
    target_y = support_joint_height_for_surface(ground_y)
    anchors: dict[str, Point3] = {}
    for joint_name in support_names:
        points = [
            frame.joints[joint_name]
            for frame in clip.frames
            if joint_name in frame.joints
        ]
        if not points:
            continue
        anchors[joint_name] = (
            statistics.median(point[0] for point in points),
            target_y,
            statistics.median(point[2] for point in points),
        )
    if not anchors:
        return clip, {"applied": False, "reason": "no_support_joint_samples"}
    reference_bone_lengths: dict[str, dict[str, float]] = {}
    for joint_name in anchors:
        parent_name = SUPPORT_CHAIN_CONSTRAINTS.get(joint_name, (None, ()))[0]
        if not isinstance(parent_name, str):
            continue
        parent_lengths = [
            math.dist(frame.joints[parent_name], frame.joints[joint_name])
            for frame in clip.frames
            if parent_name in frame.joints and joint_name in frame.joints
        ]
        pelvis_lengths = [
            math.dist(frame.joints["pelvis"], frame.joints[parent_name])
            for frame in clip.frames
            if "pelvis" in frame.joints and parent_name in frame.joints
        ]
        if parent_lengths and pelvis_lengths:
            reference_bone_lengths[joint_name] = {
                "pelvisToHip": statistics.median(pelvis_lengths),
                "hipToKnee": statistics.median(parent_lengths),
            }
    if preserve_chain_lengths:
        anchors = optimize_reachable_support_anchors(
            clip,
            anchors=anchors,
            reference_bone_lengths=reference_bone_lengths,
        )
    reference_hip_widths = [
        math.dist(frame.joints["left_hip"], frame.joints["right_hip"])
        for frame in clip.frames
        if "left_hip" in frame.joints and "right_hip" in frame.joints
    ]

    locked_frames: list[MotionFrame] = []
    resolved_anchor_frames: list[dict[str, list[float]]] = []
    maximum_correction = 0.0
    for frame in clip.frames:
        joints = dict(frame.joints)
        resolved_frame_anchors: dict[str, list[float]] = {}
        for joint_name, anchor in anchors.items():
            current = joints.get(joint_name)
            if current is None:
                continue
            resolved_anchor = anchor
            correction = (
                resolved_anchor[0] - current[0],
                resolved_anchor[1] - current[1],
                resolved_anchor[2] - current[2],
            )
            correction_length = math.sqrt(sum(value * value for value in correction))
            if correction_length <= 1e-8:
                resolved_frame_anchors[joint_name] = list(resolved_anchor)
                continue
            joints[joint_name] = resolved_anchor
            resolved_frame_anchors[joint_name] = list(resolved_anchor)
            _descendants = SUPPORT_CHAIN_CONSTRAINTS.get(joint_name, (None, ()))[1]
            for descendant_name in _descendants:
                descendant = joints.get(descendant_name)
                if descendant is None:
                    continue
                joints[descendant_name] = (
                    descendant[0] + correction[0],
                    descendant[1] + correction[1],
                    descendant[2] + correction[2],
                )
            maximum_correction = max(maximum_correction, correction_length)
        locked_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
        resolved_anchor_frames.append(resolved_frame_anchors)
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=locked_frames,
        source=clip.source,
        metadata=clip.metadata,
    ), {
        "applied": True,
        "strategy": "planted_support_joint_world_lock",
        "supportJoints": list(anchors),
        "groundY": ground_y,
        "anchors": {
            name: [anchor[0], anchor[1], anchor[2]]
            for name, anchor in anchors.items()
        },
        "referenceBoneLengths": reference_bone_lengths,
        "referenceHipWidth": (
            statistics.median(reference_hip_widths)
            if reference_hip_widths
            else None
        ),
        "anchorFrames": resolved_anchor_frames,
        "preserveChainLengths": preserve_chain_lengths,
        "maximumCorrection": maximum_correction,
    }


def optimize_reachable_support_anchors(
    clip: MotionClip,
    *,
    anchors: dict[str, Point3],
    reference_bone_lengths: dict[str, dict[str, float]],
) -> dict[str, Point3]:
    optimized: dict[str, Point3] = {}
    for joint_name, anchor in anchors.items():
        lengths = reference_bone_lengths.get(joint_name)
        if not isinstance(lengths, dict):
            optimized[joint_name] = anchor
            continue
        pelvis_to_hip = lengths.get("pelvisToHip")
        hip_to_knee = lengths.get("hipToKnee")
        if not isinstance(pelvis_to_hip, (int, float)) or not isinstance(
            hip_to_knee,
            (int, float),
        ):
            optimized[joint_name] = anchor
            continue
        maximum_reach = float(pelvis_to_hip) + float(hip_to_knee) - 1e-5
        anchor_x, anchor_y, anchor_z = anchor
        for iteration in range(64):
            frames = clip.frames if iteration % 2 == 0 else reversed(clip.frames)
            for frame in frames:
                pelvis = frame.joints.get("pelvis")
                if pelvis is None:
                    continue
                vertical = pelvis[1] - anchor_y
                horizontal_reach = math.sqrt(
                    max(0.0, maximum_reach * maximum_reach - vertical * vertical)
                )
                delta_x = anchor_x - pelvis[0]
                delta_z = anchor_z - pelvis[2]
                horizontal_distance = math.hypot(delta_x, delta_z)
                if horizontal_distance <= horizontal_reach or horizontal_distance <= 1e-8:
                    continue
                scale = horizontal_reach / horizontal_distance
                anchor_x = pelvis[0] + delta_x * scale
                anchor_z = pelvis[2] + delta_z * scale
        optimized[joint_name] = (anchor_x, anchor_y, anchor_z)
    return optimized


def lift_clip_above_support_ground(
    clip: MotionClip,
    *,
    support_ground_y: float,
    tolerance: float,
) -> MotionClip:
    if clip.frame_count == 0:
        return clip
    support_joint_names = [joint for joint in DEFAULT_SUPPORT_JOINTS if joint in clip.joint_names]
    if not support_joint_names:
        return clip

    corrected_frames: list[MotionFrame] = []
    for frame in clip.frames:
        support_heights = [
            support_surface_height(frame.joints[joint_name][1])
            for joint_name in support_joint_names
            if joint_name in frame.joints
        ]
        if not support_heights:
            corrected_frames.append(frame)
            continue
        penetration = (support_ground_y - min(support_heights)) + tolerance
        if penetration <= 0:
            corrected_frames.append(frame)
            continue
        corrected_joints = {
            name: (coords[0], coords[1] + penetration, coords[2])
            for name, coords in frame.joints.items()
        }
        corrected_frames.append(MotionFrame(time_sec=frame.time_sec, joints=corrected_joints))
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=corrected_frames,
        source=clip.source,
        metadata=clip.metadata,
    )


def stabilize_global_translation_from_support_contacts(
    clip: MotionClip,
    *,
    contact_states: list[dict[str, object]],
    support_ground_y: float,
    blend: float = SUPPORT_GLOBAL_STABILIZATION_BLEND,
) -> MotionClip:
    if clip.frame_count == 0 or not contact_states or blend <= 0.0:
        return clip

    blend = min(max(blend, 0.0), 1.0)
    stabilized_frames: list[MotionFrame] = []
    support_targets: dict[str, Point3] = {}
    previous_contacting_joints: set[str] = set()
    for frame_index, frame in enumerate(clip.frames):
        state = contact_states[frame_index] if frame_index < len(contact_states) else {}
        contacting_joints = [
            joint_name
            for joint_name in iter_contact_joint_names(state)
            if joint_name in frame.joints
        ]
        if not contacting_joints:
            previous_contacting_joints = set()
            stabilized_frames.append(frame)
            continue

        corrections: list[Point3] = []
        for joint_name in contacting_joints:
            current_point = frame.joints[joint_name]
            target = support_targets.get(joint_name)
            if target is None or joint_name not in previous_contacting_joints:
                target = (
                    current_point[0],
                    # `support_ground_y` is already in joint-center Y space.
                    float(support_ground_y),
                    current_point[2],
                )
                support_targets[joint_name] = target
            corrections.append(
                (
                    current_point[0] - target[0],
                    0.0,
                    current_point[2] - target[2],
                )
            )

        averaged_correction = (
            sum(item[0] for item in corrections) / len(corrections),
            sum(item[1] for item in corrections) / len(corrections),
            sum(item[2] for item in corrections) / len(corrections),
        )
        translated_joints = {
            name: (
                coords[0] - averaged_correction[0] * blend,
                coords[1] - averaged_correction[1] * blend,
                coords[2] - averaged_correction[2] * blend,
            )
            for name, coords in frame.joints.items()
        }
        stabilized_frames.append(MotionFrame(time_sec=frame.time_sec, joints=translated_joints))
        previous_contacting_joints = set(contacting_joints)

    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=stabilized_frames,
        source=clip.source,
        metadata=clip.metadata,
    )


def stabilize_multi_contact_support(
    clip: MotionClip,
    *,
    contact_states: list[dict[str, object]],
    support_ground_y: float,
    lock_blend: float = SUPPORT_LOCK_BLEND,
) -> MotionClip:
    if clip.frame_count == 0 or not contact_states:
        return clip

    stabilized_frames: list[MotionFrame] = []
    support_targets: dict[str, Point3] = {}
    previous_contacting_joints: set[str] = set()
    lock_blend = min(max(lock_blend, 0.0), 1.0)
    for frame_index, frame in enumerate(clip.frames):
        state = contact_states[frame_index] if frame_index < len(contact_states) else {}
        contacting_joints = [
            joint_name
            for joint_name in iter_contact_joint_names(state)
            if joint_name in frame.joints
        ]
        if not contacting_joints:
            previous_contacting_joints = set()
            stabilized_frames.append(frame)
            continue

        corrections: list[Point3] = []
        for joint_name in contacting_joints:
            current_point = frame.joints[joint_name]
            target = support_targets.get(joint_name)
            is_new_contact = joint_name not in previous_contacting_joints
            if target is None or is_new_contact:
                target = (
                    current_point[0],
                    # `support_ground_y` is the desired joint-center Y, not
                    # the support capsule surface height.
                    float(support_ground_y),
                    current_point[2],
                )
                support_targets[joint_name] = target
            corrections.append(
                (
                    current_point[0] - target[0],
                    current_point[1] - target[1],
                    current_point[2] - target[2],
                )
            )
        averaged_correction = (
            sum(item[0] for item in corrections) / len(corrections),
            sum(item[1] for item in corrections) / len(corrections),
            sum(item[2] for item in corrections) / len(corrections),
        )
        translated_joints = {
            name: (
                coords[0] - averaged_correction[0] * lock_blend,
                coords[1] - averaged_correction[1] * lock_blend,
                coords[2] - averaged_correction[2] * lock_blend,
            )
            for name, coords in frame.joints.items()
        }
        for joint_name in contacting_joints:
            target = support_targets[joint_name]
            translated_point = translated_joints[joint_name]
            translated_joints[joint_name] = (
                translated_point[0] * (1.0 - SUPPORT_LOCK_XZ_BLEND) + target[0] * SUPPORT_LOCK_XZ_BLEND,
                translated_point[1] * (1.0 - SUPPORT_LOCK_Y_BLEND) + target[1] * SUPPORT_LOCK_Y_BLEND,
                translated_point[2] * (1.0 - SUPPORT_LOCK_XZ_BLEND) + target[2] * SUPPORT_LOCK_XZ_BLEND,
            )
        stabilized_frames.append(MotionFrame(time_sec=frame.time_sec, joints=translated_joints))
        previous_contacting_joints = set(contacting_joints)

    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=stabilized_frames,
        source=clip.source,
        metadata=clip.metadata,
    )








def one_euro_filter_point(
    *,
    current_point: Point3,
    previous_filtered_point: Point3,
    previous_filtered_derivative: Point3,
    delta_time: float,
    min_cutoff: float,
    beta: float,
    derivative_cutoff: float,
) -> tuple[Point3, Point3]:
    raw_derivative = tuple(
        (current_point[axis] - previous_filtered_point[axis]) / delta_time
        for axis in range(3)
    )
    derivative_alpha = smoothing_alpha(derivative_cutoff, delta_time)
    filtered_derivative = tuple(
        exponential_smooth(
            current=raw_derivative[axis],
            previous=previous_filtered_derivative[axis],
            alpha=derivative_alpha,
        )
        for axis in range(3)
    )
    derivative_magnitude = math.sqrt(sum(value * value for value in filtered_derivative))
    adaptive_cutoff = min_cutoff + beta * derivative_magnitude
    point_alpha = smoothing_alpha(adaptive_cutoff, delta_time)
    filtered_point = tuple(
        exponential_smooth(
            current=current_point[axis],
            previous=previous_filtered_point[axis],
            alpha=point_alpha,
        )
        for axis in range(3)
    )
    return filtered_point, filtered_derivative




def smoothing_alpha(cutoff: float, delta_time: float) -> float:
    effective_cutoff = max(cutoff, 1e-5)
    tau = 1.0 / (2.0 * math.pi * effective_cutoff)
    return 1.0 / (1.0 + tau / delta_time)


def exponential_smooth(*, current: float, previous: float, alpha: float) -> float:
    return alpha * current + (1.0 - alpha) * previous


def suppress_micro_movements(
    clip: MotionClip,
    *,
    position_tolerance: float = MICRO_MOVEMENT_POSITION_TOLERANCE,
) -> MotionClip:
    if clip.frame_count <= 1 or position_tolerance <= 0:
        return clip

    stabilized_frames = [clip.frames[0]]
    for frame in clip.frames[1:]:
        previous_joints = stabilized_frames[-1].joints
        filtered_joints: dict[str, Point3] = {}
        for joint_name, coords in frame.joints.items():
            previous_coords = previous_joints[joint_name]
            dx = coords[0] - previous_coords[0]
            dy = coords[1] - previous_coords[1]
            dz = coords[2] - previous_coords[2]
            distance = (dx * dx + dy * dy + dz * dz) ** 0.5
            tolerance = micro_movement_tolerance_for_joint(joint_name, default=position_tolerance)
            if distance < tolerance and distance > 1e-8:
                damping = distance / tolerance
                filtered_joints[joint_name] = (
                    previous_coords[0] + dx * damping,
                    previous_coords[1] + dy * damping,
                    previous_coords[2] + dz * damping,
                )
            elif distance <= 1e-8:
                filtered_joints[joint_name] = previous_coords
            else:
                filtered_joints[joint_name] = coords
        stabilized_frames.append(MotionFrame(time_sec=frame.time_sec, joints=filtered_joints))

    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=stabilized_frames,
        source=clip.source,
        metadata=clip.metadata,
    )


def micro_movement_tolerance_for_joint(joint_name: str, *, default: float) -> float:
    normalized = joint_name.lower()
    if normalized in {
        "pelvis",
        "spine",
        "spine1",
        "spine2",
        "spine3",
        "neck",
        "head",
        "left_collar",
        "right_collar",
        "left_shoulder",
        "right_shoulder",
    }:
        return TORSO_MICRO_MOVEMENT_TOLERANCE
    if any(token in normalized for token in ("wrist", "hand", "elbow", "shoulder", "collar")):
        return ARM_MICRO_MOVEMENT_TOLERANCE
    if any(token in normalized for token in ("hip", "knee", "ankle", "foot", "toe")):
        return LEG_MICRO_MOVEMENT_TOLERANCE
    return default


def find_first_joint(clip: MotionClip, candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate in clip.joint_names:
            return candidate
    raise ValueError(f"Could not find any of the expected joints: {', '.join(candidates)}")


def average_joint_axis(clip: MotionClip, joint_name: str, *, axis: int) -> float:
    values = [frame.joints[joint_name][axis] for frame in clip.frames]
    return sum(values) / len(values)


def choose_anchor_foot(clip: MotionClip) -> str | None:
    foot_joint_names = [joint for joint in DEFAULT_FOOT_JOINTS if joint in clip.joint_names]
    if not foot_joint_names:
        return None
    movement_by_foot = {
        joint_name: sum(
            horizontal_joint_distance(clip.frames[index - 1], clip.frames[index], joint_name)
            for index in range(1, clip.frame_count)
        )
        for joint_name in foot_joint_names
    }
    return min(movement_by_foot, key=movement_by_foot.get)






def horizontal_frame_speed(clip: MotionClip, *, frame_index: int, joint_name: str) -> float:
    if clip.frame_count <= 1:
        return 0.0
    if frame_index <= 0:
        return horizontal_joint_distance(clip.frames[0], clip.frames[1], joint_name)
    return horizontal_joint_distance(clip.frames[frame_index - 1], clip.frames[frame_index], joint_name)


def detect_support_mode(
    clip: MotionClip,
    *,
    support_mode_hint: str | None = None,
) -> str:
    normalized_hint = str(support_mode_hint or "").strip().casefold()
    if normalized_hint in {"upright", "quadruped", "supine", "prone", "kneeling"}:
        return normalized_hint
    torso_samples: list[tuple[float, float]] = []
    for frame in clip.frames:
        pelvis = frame.joints.get("pelvis")
        neck = frame.joints.get("neck")
        if pelvis is None or neck is None:
            continue
        vertical = abs(neck[1] - pelvis[1])
        horizontal = math.hypot(neck[0] - pelvis[0], neck[2] - pelvis[2])
        torso_samples.append((vertical, horizontal))
    if not torso_samples:
        return "upright"
    vertical = statistics.median(sample[0] for sample in torso_samples)
    horizontal = statistics.median(sample[1] for sample in torso_samples)
    if horizontal > vertical:
        # A horizontal torso is shared by supine, prone, bench-supported, and
        # true hands-and-knees exercises.  Geometry alone cannot distinguish
        # them reliably, so destructive quadruped grounding must be opt-in.
        return "horizontal_unspecified"
    return "upright"


def support_joint_names_for_mode(clip: MotionClip, support_mode: str) -> list[str]:
    if support_mode == "quadruped":
        candidates = DEFAULT_HAND_JOINTS + LEFT_KNEE_GROUP + RIGHT_KNEE_GROUP
    elif support_mode == "kneeling":
        candidates = LEFT_KNEE_GROUP + RIGHT_KNEE_GROUP
    else:
        candidates = DEFAULT_FOOT_JOINTS + DEFAULT_HAND_JOINTS
    return [joint for joint in candidates if joint in clip.joint_names]


def detect_support_contact_states(
    clip: MotionClip,
    *,
    support_mode: str | None = None,
) -> list[dict[str, object]]:
    support_mode = support_mode or detect_support_mode(clip)
    states: list[dict[str, object]] = []
    knee_support = uses_knee_floor_support(support_mode)
    left_joint = first_available_joint(clip, LEFT_KNEE_GROUP if knee_support else LEFT_FOOT_GROUP)
    right_joint = first_available_joint(clip, RIGHT_KNEE_GROUP if knee_support else RIGHT_FOOT_GROUP)
    left_hand_joint = first_available_joint(clip, LEFT_HAND_GROUP)
    right_hand_joint = first_available_joint(clip, RIGHT_HAND_GROUP)
    gvhmr_static_joint_confidence = extract_gvhmr_static_joint_confidence(clip)
    previous_left = False
    previous_right = False
    previous_left_hand = False
    previous_right_hand = False
    for frame_index in range(clip.frame_count):
        left_contact = (
            support_contact_for_joint(
                clip,
                frame_index=frame_index,
                joint_name=left_joint,
                was_in_contact=previous_left,
                static_confidence=gvhmr_static_joint_confidence[frame_index].get(left_joint)
                if frame_index < len(gvhmr_static_joint_confidence)
                else None,
            )
            if left_joint is not None
            else False
        )
        right_contact = (
            support_contact_for_joint(
                clip,
                frame_index=frame_index,
                joint_name=right_joint,
                was_in_contact=previous_right,
                static_confidence=gvhmr_static_joint_confidence[frame_index].get(right_joint)
                if frame_index < len(gvhmr_static_joint_confidence)
                else None,
            )
            if right_joint is not None
            else False
        )
        left_hand_contact = (
            support_contact_for_joint(
                clip,
                frame_index=frame_index,
                joint_name=left_hand_joint,
                was_in_contact=previous_left_hand,
                static_confidence=gvhmr_static_joint_confidence[frame_index].get(left_hand_joint)
                if frame_index < len(gvhmr_static_joint_confidence)
                else None,
            )
            if left_hand_joint is not None
            else False
        )
        right_hand_contact = (
            support_contact_for_joint(
                clip,
                frame_index=frame_index,
                joint_name=right_hand_joint,
                was_in_contact=previous_right_hand,
                static_confidence=gvhmr_static_joint_confidence[frame_index].get(right_hand_joint)
                if frame_index < len(gvhmr_static_joint_confidence)
                else None,
            )
            if right_hand_joint is not None
            else False
        )
        support_joint: str | None = None
        state = "airborne"
        contact_candidates = (
            (
                (left_joint, left_contact),
                (right_joint, right_contact),
            )
            if support_mode == "kneeling"
            else (
                (left_joint, left_contact),
                (right_joint, right_contact),
                (left_hand_joint, left_hand_contact),
                (right_hand_joint, right_hand_contact),
            )
        )
        contacting_joints = [
            joint_name
            for joint_name, in_contact in contact_candidates
            if joint_name is not None and in_contact
        ]
        if contacting_joints:
            support_joint = min(
                contacting_joints,
                key=lambda joint_name: (
                    horizontal_frame_speed(clip, frame_index=frame_index, joint_name=joint_name),
                    clip.frames[frame_index].joints[joint_name][1],
                ),
            )
            foot_contacts = sum(1 for value in (left_contact, right_contact) if value)
            hand_contacts = (
                0
                if support_mode == "kneeling"
                else sum(1 for value in (left_hand_contact, right_hand_contact) if value)
            )
            if foot_contacts >= 2 and hand_contacts == 0:
                state = "double_support"
            elif foot_contacts == 1 and hand_contacts == 0:
                state = "left_planted" if left_contact else "right_planted"
            elif hand_contacts >= 2 and foot_contacts == 0:
                state = "double_hand_support"
            elif hand_contacts == 1 and foot_contacts == 0:
                state = "left_hand_planted" if left_hand_contact else "right_hand_planted"
            else:
                state = "mixed_support"

        states.append(
            {
                "frameIndex": frame_index,
                "timeSec": clip.frames[frame_index].time_sec,
                "leftFootJoint": left_joint,
                "rightFootJoint": right_joint,
                "leftKneeJoint": left_joint if knee_support else None,
                "rightKneeJoint": right_joint if knee_support else None,
                "leftHandJoint": left_hand_joint,
                "rightHandJoint": right_hand_joint,
                "leftInContact": left_contact if not knee_support else False,
                "rightInContact": right_contact if not knee_support else False,
                "leftKneeInContact": left_contact if knee_support else False,
                "rightKneeInContact": right_contact if knee_support else False,
                "leftHandInContact": left_hand_contact if support_mode != "kneeling" else False,
                "rightHandInContact": right_hand_contact if support_mode != "kneeling" else False,
                "supportJoint": support_joint,
                "supportFoot": support_joint,
                "state": state,
                "supportMode": support_mode,
                "contactJoints": contacting_joints,
            }
        )
        previous_left = left_contact
        previous_right = right_contact
        previous_left_hand = left_hand_contact
        previous_right_hand = right_hand_contact
    return states


def iter_contact_joint_names(state: dict[str, object]) -> list[str]:
    contact_joints = state.get("contactJoints")
    if isinstance(contact_joints, list):
        return [joint for joint in contact_joints if isinstance(joint, str)]
    joints: list[str] = []
    for flag_name, joint_name_field in (
        ("leftInContact", "leftFootJoint"),
        ("rightInContact", "rightFootJoint"),
        ("leftKneeInContact", "leftKneeJoint"),
        ("rightKneeInContact", "rightKneeJoint"),
        ("leftHandInContact", "leftHandJoint"),
        ("rightHandInContact", "rightHandJoint"),
    ):
        if state.get(flag_name):
            joint_name = state.get(joint_name_field)
            if isinstance(joint_name, str):
                joints.append(joint_name)
    return joints


def _support_state_has_ground_contact(state: dict[str, object]) -> bool:
    return any(
        bool(state.get(name))
        for name in ("leftInContact", "rightInContact", "leftKneeInContact", "rightKneeInContact")
    )


def _summarize_support_states(states: list[dict[str, object]]) -> dict[str, object]:
    state_counts: dict[str, int] = {}
    left_foot_contacts = 0
    right_foot_contacts = 0
    left_hand_contacts = 0
    right_hand_contacts = 0
    left_knee_contacts = 0
    right_knee_contacts = 0
    ground_contact_frames = 0

    for state in states:
        raw_state = state.get("state")
        state_name = raw_state if isinstance(raw_state, str) and raw_state else "unknown"
        state_counts[state_name] = state_counts.get(state_name, 0) + 1
        if bool(state.get("leftInContact")):
            left_foot_contacts += 1
        if bool(state.get("rightInContact")):
            right_foot_contacts += 1
        if bool(state.get("leftHandInContact")):
            left_hand_contacts += 1
        if bool(state.get("rightHandInContact")):
            right_hand_contacts += 1
        if bool(state.get("leftKneeInContact")):
            left_knee_contacts += 1
        if bool(state.get("rightKneeInContact")):
            right_knee_contacts += 1
        if _support_state_has_ground_contact(state):
            ground_contact_frames += 1

    total_frames = len(states)
    return {
        "totalFrames": total_frames,
        "stateCounts": state_counts,
        "leftFootContactFrames": left_foot_contacts,
        "rightFootContactFrames": right_foot_contacts,
        "leftHandContactFrames": left_hand_contacts,
        "rightHandContactFrames": right_hand_contacts,
        "leftKneeContactFrames": left_knee_contacts,
        "rightKneeContactFrames": right_knee_contacts,
        "groundContactFrames": ground_contact_frames,
        "handContactFrames": sum(
            1
            for state in states
            if bool(state.get("leftHandInContact")) or bool(state.get("rightHandInContact"))
        ),
    }


def support_contact_for_joint(
    clip: MotionClip,
    *,
    frame_index: int,
    joint_name: str,
    was_in_contact: bool,
    static_confidence: float | None = None,
) -> bool:
    if static_confidence is not None and static_confidence < static_confidence_threshold_for_joint(joint_name):
        return False
    support = clip.frames[frame_index].joints[joint_name]
    height_tolerance = contact_height_tolerance_for_joint(joint_name, was_in_contact=was_in_contact)
    if support_surface_height(support[1]) > height_tolerance:
        return False
    vertical_speed = vertical_frame_speed(clip, frame_index=frame_index, joint_name=joint_name)
    vertical_tolerance = contact_vertical_speed_tolerance_for_joint(joint_name, was_in_contact=was_in_contact)
    return abs(vertical_speed) <= vertical_tolerance


def contact_height_tolerance_for_joint(joint_name: str, *, was_in_contact: bool) -> float:
    normalized = joint_name.lower()
    if "hand" in normalized or "wrist" in normalized:
        return HAND_CONTACT_RELEASE_HEIGHT_TOLERANCE if was_in_contact else HAND_CONTACT_HEIGHT_TOLERANCE
    return FOOT_CONTACT_RELEASE_HEIGHT_TOLERANCE if was_in_contact else FOOT_CONTACT_HEIGHT_TOLERANCE


def contact_vertical_speed_tolerance_for_joint(joint_name: str, *, was_in_contact: bool) -> float:
    normalized = joint_name.lower()
    if "hand" in normalized or "wrist" in normalized:
        return HAND_CONTACT_VERTICAL_SPEED_TOLERANCE
    return FOOT_CONTACT_RELEASE_HEIGHT_TOLERANCE if was_in_contact else FOOT_CONTACT_VERTICAL_SPEED_TOLERANCE


def extract_gvhmr_static_joint_confidence(clip: MotionClip) -> list[dict[str, float]]:
    gvhmr_metadata = clip.metadata.get("gvhmr")
    if not isinstance(gvhmr_metadata, dict):
        return []
    static_joint_confidence = gvhmr_metadata.get("staticJointConfidence")
    if not isinstance(static_joint_confidence, list):
        return []
    normalized: list[dict[str, float]] = []
    for item in static_joint_confidence:
        if not isinstance(item, dict):
            normalized.append({})
            continue
        normalized.append(
            {str(key): float(value) for key, value in item.items() if isinstance(value, (int, float))}
        )
    return normalized


def static_confidence_threshold_for_joint(joint_name: str) -> float:
    normalized = joint_name.lower()
    if "hand" in normalized or "wrist" in normalized:
        return 0.55
    return 0.45


def vertical_frame_speed(clip: MotionClip, *, frame_index: int, joint_name: str) -> float:
    if clip.frame_count <= 1:
        return 0.0
    if frame_index <= 0:
        return clip.frames[1].joints[joint_name][1] - clip.frames[0].joints[joint_name][1]
    return clip.frames[frame_index].joints[joint_name][1] - clip.frames[frame_index - 1].joints[joint_name][1]


def first_available_joint(clip: MotionClip, candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in clip.joint_names:
            return candidate
    return None




def frame_motion_delta(previous_frame: MotionFrame, current_frame: MotionFrame) -> float:
    deltas = []
    for joint_name, previous_coords in previous_frame.joints.items():
        current_coords = current_frame.joints[joint_name]
        dx = current_coords[0] - previous_coords[0]
        dy = current_coords[1] - previous_coords[1]
        dz = current_coords[2] - previous_coords[2]
        deltas.append((dx * dx + dy * dy + dz * dz) ** 0.5)
    return sum(deltas) / len(deltas)


def horizontal_joint_distance(previous_frame: MotionFrame, current_frame: MotionFrame, joint_name: str) -> float:
    previous_coords = previous_frame.joints[joint_name]
    current_coords = current_frame.joints[joint_name]
    dx = current_coords[0] - previous_coords[0]
    dz = current_coords[2] - previous_coords[2]
    return (dx * dx + dz * dz) ** 0.5


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    clamped = min(max(quantile, 0.0), 1.0)
    if len(ordered) == 1:
        return float(ordered[0])
    position = clamped * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)
