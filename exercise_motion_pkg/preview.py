from __future__ import annotations

import base64
import json
import math
from pathlib import Path

from exercise_motion_pkg.models import MotionClip, MotionFrame


UNIFORM_CAPSULE_RADIUS = 0.046
CANONICAL_CAPSULES = [
    ("pelvis", "spine1", UNIFORM_CAPSULE_RADIUS),
    ("spine1", "spine2", UNIFORM_CAPSULE_RADIUS),
    ("spine2", "spine3", UNIFORM_CAPSULE_RADIUS),
    ("spine3", "neck", UNIFORM_CAPSULE_RADIUS),
    ("neck", "left_collar", UNIFORM_CAPSULE_RADIUS),
    ("left_collar", "left_shoulder", UNIFORM_CAPSULE_RADIUS),
    ("left_shoulder", "left_elbow", UNIFORM_CAPSULE_RADIUS),
    ("left_elbow", "left_wrist", UNIFORM_CAPSULE_RADIUS),
    ("neck", "right_collar", UNIFORM_CAPSULE_RADIUS),
    ("right_collar", "right_shoulder", UNIFORM_CAPSULE_RADIUS),
    ("right_shoulder", "right_elbow", UNIFORM_CAPSULE_RADIUS),
    ("right_elbow", "right_wrist", UNIFORM_CAPSULE_RADIUS),
    ("pelvis", "left_hip", UNIFORM_CAPSULE_RADIUS),
    ("left_hip", "left_knee", UNIFORM_CAPSULE_RADIUS),
    ("left_knee", "left_ankle", UNIFORM_CAPSULE_RADIUS),
    ("left_ankle", "left_foot", UNIFORM_CAPSULE_RADIUS),
    ("pelvis", "right_hip", UNIFORM_CAPSULE_RADIUS),
    ("right_hip", "right_knee", UNIFORM_CAPSULE_RADIUS),
    ("right_knee", "right_ankle", UNIFORM_CAPSULE_RADIUS),
    ("right_ankle", "right_foot", UNIFORM_CAPSULE_RADIUS),
]

JOINT_ALIASES = {
    "spine1": ("spine1", "spine"),
    "spine2": ("spine2",),
    "spine3": ("spine3", "chest", "upper_chest"),
    "left_collar": ("left_collar", "left_clavicle"),
    "right_collar": ("right_collar", "right_clavicle"),
    "left_hip": ("left_hip", "l_hip"),
    "left_knee": ("left_knee", "l_knee"),
    "left_ankle": ("left_ankle", "l_ankle"),
    "left_foot": ("left_foot", "l_foot", "left_toe", "l_toe"),
    "right_hip": ("right_hip", "r_hip"),
    "right_knee": ("right_knee", "r_knee"),
    "right_ankle": ("right_ankle", "r_ankle"),
    "right_foot": ("right_foot", "r_foot", "right_toe", "r_toe"),
}
PREVIEW_REFINEMENT_METADATA_KEY = "previewRefinement"
HINGE_LIMITS = (
    ("left_shoulder", "left_elbow", "left_wrist", math.radians(15.0), math.radians(175.0), ("left_wrist", "left_hand")),
    ("right_shoulder", "right_elbow", "right_wrist", math.radians(15.0), math.radians(175.0), ("right_wrist", "right_hand")),
    ("left_hip", "left_knee", "left_ankle", math.radians(20.0), math.radians(175.0), ("left_ankle", "left_foot")),
    ("right_hip", "right_knee", "right_ankle", math.radians(20.0), math.radians(175.0), ("right_ankle", "right_foot")),
)
MIN_LOOP_DURATION_SECONDS = 2.0
MAX_DETECTED_LOOPS = 8
ORIENTATION_SUPPORT_JOINTS = (
    "left_foot",
    "right_foot",
    "left_ankle",
    "right_ankle",
)
HAND_SUPPORT_JOINTS = (
    "left_hand",
    "right_hand",
    "left_wrist",
    "right_wrist",
)
YAW_ALIGNMENT_PAIRS = (
    ("left_foot", "right_foot"),
    ("left_ankle", "right_ankle"),
    ("left_hand", "right_hand"),
    ("left_wrist", "right_wrist"),
)
PREVIEW_MANNEQUIN_GLB = Path(__file__).with_name("assets") / "mannequin" / "Mannequin_Man.glb"


def write_preview_html(path: Path, clip: MotionClip, *, title: str, debug_json_path: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    preview_clip = refine_motion_clip_for_preview(clip)
    default_auto_alignment = _serialize_preview_rotations(_compute_preview_auto_alignment(preview_clip.frames))
    detected_loops = [
        {
            **loop,
            "autoAlignment": _serialize_preview_rotations(
                _compute_preview_auto_alignment(preview_clip.frames[loop["startFrame"]: loop["endFrame"] + 1])
            ),
        }
        for loop in _detect_preview_loops(preview_clip)
    ]
    if debug_json_path is not None:
        write_preview_debug_json(debug_json_path, preview_clip)
    ground_payload = (
        (preview_clip.metadata.get("ground") if isinstance(preview_clip.metadata, dict) else None) or {}
    )
    payload = {
        "title": title,
        "fps": preview_clip.fps,
        "frameCount": preview_clip.frame_count,
        "jointNames": preview_clip.joint_names,
        "rootJoint": _find_root_joint(preview_clip),
        "defaultFixedRoot": preview_clip.metadata.get("upstream") == "gvhmr" if isinstance(preview_clip.metadata, dict) else False,
        "rootTranslationToggleLabel": (
            "Show original camera-space translation"
            if preview_clip.metadata.get("upstream") == "gvhmr"
            else "Lock global root drift"
        ) if isinstance(preview_clip.metadata, dict) else "Lock global root drift",
        "defaultAutoWorldAlignment": False,
        "mannequinAssetDataUri": _load_preview_mannequin_data_uri(),
        "defaultAutoAlignment": default_auto_alignment,
        "loopable": bool(detected_loops),
        "detectedLoops": detected_loops,
        "capsules": _build_capsules(preview_clip),
        "frames": [
            {
                "frameIndex": index,
                "timeSec": frame.time_sec,
                "joints": frame.joints,
            }
            for index, frame in enumerate(preview_clip.frames)
        ],
        "ground": ground_payload,
    }
    html = _build_html(payload)
    path.write_text(html, encoding="utf-8")


def _load_preview_mannequin_data_uri() -> str | None:
    if not PREVIEW_MANNEQUIN_GLB.exists():
        return None
    encoded = base64.b64encode(PREVIEW_MANNEQUIN_GLB.read_bytes()).decode("ascii")
    return f"data:model/gltf-binary;base64,{encoded}"


def write_preview_debug_json(path: Path, clip: MotionClip) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fixed_root = bool(clip.metadata.get("upstream") == "gvhmr") if isinstance(clip.metadata, dict) else False
    translation_track = _build_preview_translation_track(clip.frames)
    frames_payload = []
    for index, frame in enumerate(clip.frames):
        translation = translation_track[index] if fixed_root and index < len(translation_track) else (0.0, 0.0, 0.0)
        rendered_joints = {
            joint_name: (
                point[0] - translation[0],
                point[1] - translation[1],
                point[2] - translation[2],
            )
            for joint_name, point in frame.joints.items()
        }
        frames_payload.append(
            {
                "frameIndex": index,
                "timeSec": frame.time_sec,
                "translationApplied": translation,
                "sourceJoints": frame.joints,
                "renderedJoints": rendered_joints,
            }
        )
    payload = {
        "fps": clip.fps,
        "frameCount": clip.frame_count,
        "fixedRootApplied": fixed_root,
        "jointNames": clip.joint_names,
        "frames": frames_payload,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def refine_motion_clip_for_preview(clip: MotionClip) -> MotionClip:
    if _clip_is_preview_refined(clip):
        return clip
    return _apply_preview_refinement(clip)


def _prepare_preview_clip(clip: MotionClip) -> MotionClip:
    return refine_motion_clip_for_preview(clip)


def _clip_is_preview_refined(clip: MotionClip) -> bool:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    refinement_metadata = metadata.get(PREVIEW_REFINEMENT_METADATA_KEY)
    return isinstance(refinement_metadata, dict) and bool(refinement_metadata.get("prepared"))


def _apply_preview_refinement(clip: MotionClip) -> MotionClip:
    flip_vertical = _preview_requires_vertical_flip(clip)
    frames = [_transform_frame_for_preview(frame, flip_vertical=flip_vertical) for frame in clip.frames]
    frames = _suppress_preview_outlier_frames(frames)
    frames = _suppress_translation_bursts(frames)
    frames = _stabilize_unrealistic_segment_motion(frames)
    frames = _enforce_preview_joint_limits(frames)
    frames = _smooth_preview_frames(frames)
    metadata = dict(clip.metadata)
    metadata[PREVIEW_REFINEMENT_METADATA_KEY] = {
        "prepared": True,
        "flipVerticalApplied": flip_vertical,
        "supportPlaneAligned": False,
        "motionLineAligned": False,
    }
    ground = metadata.get("ground")
    if isinstance(ground, dict):
        if flip_vertical:
            ground = _flip_ground_payload(ground)
        metadata["ground"] = ground
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=frames,
        source=clip.source,
        metadata=metadata,
    )


def _build_preview_translation_track(frames: list[MotionFrame]) -> list[tuple[float, float, float]]:
    if not frames:
        return []
    base_center = _frame_joint_center(frames[0])
    translations: list[tuple[float, float, float]] = []
    for frame in frames:
        center = _frame_joint_center(frame)
        translations.append((
            center[0] - base_center[0],
            center[1] - base_center[1],
            center[2] - base_center[2],
        ))
    return translations


def _preview_requires_vertical_flip(clip: MotionClip) -> bool:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    if metadata.get("upstream") != "gvhmr":
        return False
    pelvis_values = _joint_axis_values(clip, "pelvis", 1)
    if not pelvis_values:
        return False
    head_values = _joint_axis_values(clip, "head", 1) or _joint_axis_values(clip, "neck", 1)
    foot_values = (
        _joint_axis_values(clip, "left_foot", 1)
        + _joint_axis_values(clip, "right_foot", 1)
        + _joint_axis_values(clip, "left_ankle", 1)
        + _joint_axis_values(clip, "right_ankle", 1)
    )
    if not head_values or not foot_values:
        return False
    pelvis_median = _median(pelvis_values)
    head_median = _median(head_values)
    foot_median = _median(foot_values)
    return head_median < pelvis_median and foot_median > pelvis_median


def _joint_axis_values(clip: MotionClip, joint_name: str, axis: int) -> list[float]:
    values: list[float] = []
    for frame in clip.frames:
        point = frame.joints.get(joint_name)
        if point is None:
            continue
        values.append(float(point[axis]))
    return values


def _transform_frame_for_preview(frame: MotionFrame, *, flip_vertical: bool) -> MotionFrame:
    if not flip_vertical:
        return frame
    joints = {
        joint_name: (point[0], -point[1], point[2])
        for joint_name, point in frame.joints.items()
    }
    return MotionFrame(time_sec=frame.time_sec, joints=joints)


def _estimate_support_plane_alignment_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    support_points = _collect_floor_support_points(frames)
    if len(support_points) < 6:
        return None
    low_support_points = _select_low_support_points(support_points)
    if len(low_support_points) < 6:
        low_support_points = support_points
    averaged = _fit_support_plane_normal(low_support_points)
    if _vector_length(averaged) <= 1e-6:
        return None
    if averaged[1] < 0.0:
        averaged = (-averaged[0], -averaged[1], -averaged[2])
    up = (0.0, 1.0, 0.0)
    alignment = max(-1.0, min(1.0, _dot(averaged, up)))
    if alignment >= math.cos(math.radians(8.0)):
        return None
    axis = _cross(averaged, up)
    if _vector_length(axis) <= 1e-6:
        axis = (1.0, 0.0, 0.0)
    axis = _normalize(axis)
    angle = math.acos(alignment)
    return (axis, angle)


def _collect_floor_support_points(frames: list[MotionFrame]) -> list[tuple[float, float, float]]:
    preferred_points: list[tuple[float, float, float]] = []
    fallback_points: list[tuple[float, float, float]] = []
    for frame in frames:
        foot_points = [
            frame.joints[joint_name]
            for joint_name in ORIENTATION_SUPPORT_JOINTS
            if joint_name in frame.joints
        ]
        if not foot_points:
            continue
        fallback_points.extend(foot_points)
        if not _frame_looks_floor_supported(frame, foot_points):
            continue
        preferred_points.extend(foot_points)
    return preferred_points if len(preferred_points) >= 8 else fallback_points


def _frame_looks_floor_supported(
    frame: MotionFrame,
    foot_points: list[tuple[float, float, float]],
) -> bool:
    if len(foot_points) < 2:
        return False
    foot_heights = [point[1] for point in foot_points]
    foot_median_y = _median(foot_heights)
    foot_span_y = max(foot_heights) - min(foot_heights)
    if foot_span_y > 0.24:
        return False

    pelvis = frame.joints.get("pelvis")
    if pelvis is not None and pelvis[1] - foot_median_y < 0.35:
        return False

    hand_points = [
        frame.joints[joint_name]
        for joint_name in HAND_SUPPORT_JOINTS
        if joint_name in frame.joints
    ]
    if hand_points:
        hand_median_y = _median([point[1] for point in hand_points])
        if foot_median_y > hand_median_y - 0.06:
            return False

    return True


def _select_low_support_points(
    support_points: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    if len(support_points) < 6:
        return support_points
    sorted_points = sorted(support_points, key=lambda point: point[1])
    keep_count = max(6, int(len(sorted_points) * 0.35))
    threshold = sorted_points[min(len(sorted_points) - 1, keep_count - 1)][1]
    margin_threshold = sorted_points[0][1] + 0.16
    max_threshold = min(threshold, margin_threshold)
    selected = [point for point in sorted_points if point[1] <= max_threshold]
    return selected if len(selected) >= 6 else sorted_points[:keep_count]


def _fit_support_plane_normal(
    support_points: list[tuple[float, float, float]],
) -> tuple[float, float, float]:
    coefficients = _fit_support_plane_coefficients(support_points)
    if coefficients is None:
        return (0.0, 1.0, 0.0)
    slope_x, slope_z, _ = coefficients
    normal = _normalize((-slope_x, 1.0, -slope_z))
    return normal or (0.0, 1.0, 0.0)


def _fit_support_plane_coefficients(
    support_points: list[tuple[float, float, float]],
) -> tuple[float, float, float] | None:
    if len(support_points) < 3:
        return None
    filtered_points = list(support_points)
    for _ in range(2):
        solution = _solve_support_plane_regression(filtered_points)
        if solution is None:
            return None
        slope_x, slope_z, intercept = solution
        residuals = [
            abs((slope_x * point[0]) + (slope_z * point[2]) + intercept - point[1])
            for point in filtered_points
        ]
        if not residuals:
            return solution
        median_residual = _median(residuals)
        threshold = max(0.03, median_residual * 2.5)
        refined_points = [
            point
            for point, residual in zip(filtered_points, residuals)
            if residual <= threshold
        ]
        if len(refined_points) < 3 or len(refined_points) == len(filtered_points):
            return solution
        filtered_points = refined_points
    return _solve_support_plane_regression(filtered_points)


def _solve_support_plane_regression(
    support_points: list[tuple[float, float, float]],
) -> tuple[float, float, float] | None:
    count = float(len(support_points))
    sum_x = sum(point[0] for point in support_points)
    sum_z = sum(point[2] for point in support_points)
    sum_y = sum(point[1] for point in support_points)
    sum_xx = sum(point[0] * point[0] for point in support_points)
    sum_zz = sum(point[2] * point[2] for point in support_points)
    sum_xz = sum(point[0] * point[2] for point in support_points)
    sum_xy = sum(point[0] * point[1] for point in support_points)
    sum_zy = sum(point[2] * point[1] for point in support_points)
    matrix = [
        [sum_xx, sum_xz, sum_x, sum_xy],
        [sum_xz, sum_zz, sum_z, sum_zy],
        [sum_x, sum_z, count, sum_y],
    ]
    return _solve_3x3_augmented(matrix)


def _solve_3x3_augmented(
    matrix: list[list[float]],
) -> tuple[float, float, float] | None:
    rows = [row[:] for row in matrix]
    size = 3
    for pivot_index in range(size):
        pivot_row = max(range(pivot_index, size), key=lambda index: abs(rows[index][pivot_index]))
        if abs(rows[pivot_row][pivot_index]) <= 1e-8:
            return None
        if pivot_row != pivot_index:
            rows[pivot_index], rows[pivot_row] = rows[pivot_row], rows[pivot_index]
        pivot_value = rows[pivot_index][pivot_index]
        for column_index in range(pivot_index, size + 1):
            rows[pivot_index][column_index] /= pivot_value
        for row_index in range(size):
            if row_index == pivot_index:
                continue
            factor = rows[row_index][pivot_index]
            if abs(factor) <= 1e-10:
                continue
            for column_index in range(pivot_index, size + 1):
                rows[row_index][column_index] -= factor * rows[pivot_index][column_index]
    return (rows[0][3], rows[1][3], rows[2][3])


def _estimate_support_profile_yaw_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    if not frames:
        return None
    direction = _estimate_average_lateral_direction_2d(frames)
    if direction is None:
        return None
    if direction[0] < 0.0:
        direction = (-direction[0], -direction[1])
    angle = math.atan2(direction[1], direction[0])
    if abs(angle) <= math.radians(2.0):
        return None
    return ((0.0, 1.0, 0.0), -angle)


def _compute_preview_auto_alignment(
    frames: list[MotionFrame],
) -> list[tuple[tuple[float, float, float], float]]:
    if not frames:
        return []
    rotations: list[tuple[tuple[float, float, float], float]] = []
    support_plane_rotation = _estimate_support_plane_alignment_rotation(frames)
    aligned_frames = frames
    if support_plane_rotation is not None:
        rotations.append(support_plane_rotation)
        aligned_frames = [_rotate_frame(frame, support_plane_rotation) for frame in aligned_frames]
    support_profile_rotation = _estimate_support_profile_yaw_rotation(aligned_frames)
    if support_profile_rotation is not None:
        rotations.append(support_profile_rotation)
    return rotations


def _serialize_preview_rotations(
    rotations: list[tuple[tuple[float, float, float], float]],
) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for axis, angle in rotations:
        serialized.append({
            "axis": [float(axis[0]), float(axis[1]), float(axis[2])],
            "angle": float(angle),
        })
    return serialized


def _apply_rotations_to_point(
    point: tuple[float, float, float],
    rotations: list[tuple[tuple[float, float, float], float]],
) -> tuple[float, float, float]:
    rotated = point
    for axis, angle in rotations:
        rotated = _rotate_point(rotated, axis=axis, angle=angle)
    return rotated


def _extract_motion_line_samples(frames: list[MotionFrame]) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    smoothed = _smooth_motion_line_path([
        _frame_motion_anchor(frame)
        for frame in frames
    ])
    for point in smoothed:
        if point is None:
            continue
        samples.append((point[0], point[2]))
    return samples


def _estimate_average_lateral_direction_2d(
    frames: list[MotionFrame],
) -> tuple[float, float] | None:
    directions: list[tuple[float, float]] = []
    for frame in frames:
        for left_joint, right_joint in YAW_ALIGNMENT_PAIRS:
            left_point = frame.joints.get(left_joint)
            right_point = frame.joints.get(right_joint)
            if left_point is None or right_point is None:
                continue
            delta_x = right_point[0] - left_point[0]
            delta_z = right_point[2] - left_point[2]
            length = math.hypot(delta_x, delta_z)
            if length <= 1e-5:
                continue
            directions.append((delta_x / length, delta_z / length))
    if not directions:
        return None
    averaged = (
        sum(direction[0] for direction in directions) / len(directions),
        sum(direction[1] for direction in directions) / len(directions),
    )
    length = math.hypot(averaged[0], averaged[1])
    if length <= 1e-5:
        return None
    return (averaged[0] / length, averaged[1] / length)


def _frame_motion_anchor(frame: MotionFrame) -> tuple[float, float, float] | None:
    pelvis = frame.joints.get("pelvis")
    if pelvis is not None:
        return pelvis
    return _frame_joint_center(frame)


def _smooth_motion_line_path(
    points: list[tuple[float, float, float] | None],
) -> list[tuple[float, float, float] | None]:
    if len(points) < 3:
        return points
    smoothed: list[tuple[float, float, float] | None] = []
    for index, point in enumerate(points):
        if point is None:
            smoothed.append(None)
            continue
        window: list[tuple[float, float, float]] = []
        for neighbor_index in range(max(0, index - 2), min(len(points), index + 3)):
            neighbor = points[neighbor_index]
            if neighbor is not None:
                window.append(neighbor)
        if not window:
            smoothed.append(point)
            continue
        smoothed.append((
            sum(item[0] for item in window) / len(window),
            sum(item[1] for item in window) / len(window),
            sum(item[2] for item in window) / len(window),
        ))
    return smoothed


def _principal_direction_2d(samples: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(samples) < 2:
        return None
    mean_x = sum(sample[0] for sample in samples) / len(samples)
    mean_z = sum(sample[1] for sample in samples) / len(samples)
    centered = [(sample[0] - mean_x, sample[1] - mean_z) for sample in samples]
    covariance_xx = sum(item[0] * item[0] for item in centered) / len(centered)
    covariance_zz = sum(item[1] * item[1] for item in centered) / len(centered)
    covariance_xz = sum(item[0] * item[1] for item in centered) / len(centered)
    trace = covariance_xx + covariance_zz
    determinant = covariance_xx * covariance_zz - covariance_xz * covariance_xz
    discriminant = max(0.0, trace * trace * 0.25 - determinant)
    largest_eigenvalue = trace * 0.5 + math.sqrt(discriminant)
    direction = (covariance_xz, largest_eigenvalue - covariance_xx)
    if abs(direction[0]) <= 1e-8 and abs(direction[1]) <= 1e-8:
        direction = (largest_eigenvalue - covariance_zz, covariance_xz)
    length = math.hypot(direction[0], direction[1])
    if length <= 1e-8:
        return None
    return (direction[0] / length, direction[1] / length)


def _estimate_frame_support_normals(
    support_points: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    normals: list[tuple[float, float, float]] = []
    for first in range(len(support_points) - 2):
        for second in range(first + 1, len(support_points) - 1):
            for third in range(second + 1, len(support_points)):
                a = support_points[first]
                b = support_points[second]
                c = support_points[third]
                normal = _cross(
                    _subtract_points(b, a),
                    _subtract_points(c, a),
                )
                if _vector_length(normal) <= 1e-6:
                    continue
                normal = _normalize(normal)
                if normal[1] < 0.0:
                    normal = (-normal[0], -normal[1], -normal[2])
                normals.append(normal)
    return normals


def _rotate_frame(
    frame: MotionFrame,
    rotation: tuple[tuple[float, float, float], float],
) -> MotionFrame:
    axis, angle = rotation
    joints = {
        joint_name: _rotate_point(point, axis=axis, angle=angle)
        for joint_name, point in frame.joints.items()
    }
    return MotionFrame(time_sec=frame.time_sec, joints=joints)


def _rotate_ground_payload(
    ground_payload: dict[str, object],
    rotation: tuple[tuple[float, float, float], float],
) -> dict[str, object]:
    axis, angle = rotation
    rotated = json.loads(json.dumps(ground_payload))
    render_plane = rotated.get("renderGroundPlane")
    if isinstance(render_plane, dict):
        normal = render_plane.get("normal")
        if isinstance(normal, list) and len(normal) == 3:
            render_plane["normal"] = list(
                _rotate_point((float(normal[0]), float(normal[1]), float(normal[2])), axis=axis, angle=angle)
            )
    render_origin = rotated.get("renderGroundOrigin")
    if isinstance(render_origin, dict):
        point = render_origin.get("point")
        if isinstance(point, list) and len(point) == 3:
            render_origin["point"] = list(
                _rotate_point((float(point[0]), float(point[1]), float(point[2])), axis=axis, angle=angle)
            )
    return rotated


def _flip_ground_payload(ground_payload: dict[str, object]) -> dict[str, object]:
    flipped = json.loads(json.dumps(ground_payload))
    render_plane = flipped.get("renderGroundPlane")
    if isinstance(render_plane, dict):
        normal = render_plane.get("normal")
        if isinstance(normal, list) and len(normal) == 3:
            render_plane["normal"] = [normal[0], -normal[1], normal[2]]
        offset = render_plane.get("offset")
        if isinstance(offset, (int, float)):
            render_plane["offset"] = -float(offset)
    render_origin = flipped.get("renderGroundOrigin")
    if isinstance(render_origin, dict):
        point = render_origin.get("point")
        if isinstance(point, list) and len(point) == 3:
            render_origin["point"] = [point[0], -point[1], point[2]]
    return flipped


def _suppress_preview_outlier_frames(frames: list[MotionFrame]) -> list[MotionFrame]:
    if len(frames) < 3:
        return frames
    sanitized = list(frames)
    sanitized = _replace_local_temporal_outliers(sanitized)
    for index in range(1, len(frames) - 1):
        previous_frame = sanitized[index - 1]
        current_frame = sanitized[index]
        next_frame = frames[index + 1]
        midpoint_error = _average_midpoint_error(previous_frame, current_frame, next_frame)
        neighbor_delta = _average_frame_distance(previous_frame, next_frame)
        if midpoint_error <= 0:
            continue
        if midpoint_error <= 0.08:
            continue
        if midpoint_error <= neighbor_delta * 2.2:
            continue
        if neighbor_delta >= 0.18:
            continue
        sanitized[index] = _interpolate_frame(previous_frame, next_frame, current_frame.time_sec)
    return sanitized


def _suppress_translation_bursts(frames: list[MotionFrame]) -> list[MotionFrame]:
    if len(frames) < 5:
        return frames
    sanitized = list(frames)
    centers = [_frame_joint_center(frame) for frame in sanitized]
    index = 1
    while index < len(sanitized) - 2:
        replaced = False
        for burst_length in (3, 2, 1):
            end_index = index + burst_length - 1
            next_index = end_index + 1
            if next_index >= len(sanitized):
                continue
            before_center = centers[index - 1]
            after_center = centers[next_index]
            bridge_distance = _point_distance(before_center, after_center)
            if bridge_distance > 0.45:
                continue
            burst_distances = [
                min(
                    _point_distance(centers[burst_index], before_center),
                    _point_distance(centers[burst_index], after_center),
                )
                for burst_index in range(index, end_index + 1)
            ]
            if max(burst_distances) < 0.6:
                continue
            for offset, burst_index in enumerate(range(index, end_index + 1), start=1):
                alpha = offset / (burst_length + 1)
                sanitized[burst_index] = _interpolate_frame(
                    sanitized[index - 1],
                    sanitized[next_index],
                    sanitized[burst_index].time_sec,
                    alpha_override=alpha,
                )
                centers[burst_index] = _frame_joint_center(sanitized[burst_index])
            index = next_index
            replaced = True
            break
        if not replaced:
            index += 1
    return sanitized


def _smooth_preview_frames(frames: list[MotionFrame]) -> list[MotionFrame]:
    if len(frames) < 3:
        return frames
    smoothed = list(frames)
    for _ in range(3):
        smoothed = _smooth_preview_frames_once(smoothed)
    return smoothed


def _stabilize_unrealistic_segment_motion(frames: list[MotionFrame]) -> list[MotionFrame]:
    if len(frames) < 2:
        return frames
    segment_targets = _segment_target_lengths(frames)
    if not segment_targets:
        return frames
    stabilized = list(frames)
    for frame_index, frame in enumerate(frames):
        joints = dict(frame.joints)
        for start, end, _radius in CANONICAL_CAPSULES:
            start_point = joints.get(start)
            end_point = joints.get(end)
            target_length = segment_targets.get((start, end))
            if start_point is None or end_point is None or target_length is None:
                continue
            current_length = _point_distance(start_point, end_point)
            if current_length <= 1e-6:
                continue
            allowed_delta = max(0.04, target_length * 0.18)
            if abs(current_length - target_length) <= allowed_delta:
                continue
            if not _segment_motion_looks_implausible(
                frames,
                frame_index=frame_index,
                start=start,
                end=end,
                target_length=target_length,
            ):
                continue
            scale = target_length / current_length
            joints[end] = (
                start_point[0] + (end_point[0] - start_point[0]) * scale,
                start_point[1] + (end_point[1] - start_point[1]) * scale,
                start_point[2] + (end_point[2] - start_point[2]) * scale,
            )
        stabilized[frame_index] = MotionFrame(time_sec=frame.time_sec, joints=joints)
    return stabilized


def _enforce_preview_joint_limits(frames: list[MotionFrame]) -> list[MotionFrame]:
    if not frames:
        return frames
    constrained: list[MotionFrame] = []
    for frame in frames:
        joints = dict(frame.joints)
        for parent_name, joint_name, child_name, min_angle, max_angle, descendants in HINGE_LIMITS:
            parent = joints.get(parent_name)
            middle = joints.get(joint_name)
            child = joints.get(child_name)
            if parent is None or middle is None or child is None:
                continue
            corrected_child = _constrain_hinge_child(
                parent=parent,
                middle=middle,
                child=child,
                min_angle=min_angle,
                max_angle=max_angle,
            )
            if corrected_child is None:
                continue
            delta = (
                corrected_child[0] - child[0],
                corrected_child[1] - child[1],
                corrected_child[2] - child[2],
            )
            joints[child_name] = corrected_child
            for descendant_name in descendants:
                descendant = joints.get(descendant_name)
                if descendant is None or descendant_name == child_name:
                    continue
                joints[descendant_name] = (
                    descendant[0] + delta[0],
                    descendant[1] + delta[1],
                    descendant[2] + delta[2],
                )
        constrained.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return constrained


def _constrain_hinge_child(
    *,
    parent: tuple[float, float, float],
    middle: tuple[float, float, float],
    child: tuple[float, float, float],
    min_angle: float,
    max_angle: float,
) -> tuple[float, float, float] | None:
    parent_vec = _subtract_points(parent, middle)
    child_vec = _subtract_points(child, middle)
    parent_length = _vector_length(parent_vec)
    child_length = _vector_length(child_vec)
    if parent_length <= 1e-6 or child_length <= 1e-6:
        return None
    parent_dir = _normalize(parent_vec)
    child_dir = _normalize(child_vec)
    current_angle = math.acos(max(-1.0, min(1.0, _dot(parent_dir, child_dir))))
    target_angle = min(max(current_angle, min_angle), max_angle)
    if abs(target_angle - current_angle) <= math.radians(1.0):
        return None

    plane_normal = _cross(parent_dir, child_dir)
    if _vector_length(plane_normal) <= 1e-6:
        fallback = (0.0, 1.0, 0.0) if abs(parent_dir[1]) < 0.9 else (1.0, 0.0, 0.0)
        plane_normal = _cross(parent_dir, fallback)
    plane_normal = _normalize(plane_normal)
    plane_perpendicular = _normalize(_cross(plane_normal, parent_dir))
    sign = 1.0 if _dot(child_dir, plane_perpendicular) >= 0.0 else -1.0
    corrected_dir = (
        parent_dir[0] * math.cos(target_angle) + plane_perpendicular[0] * sign * math.sin(target_angle),
        parent_dir[1] * math.cos(target_angle) + plane_perpendicular[1] * sign * math.sin(target_angle),
        parent_dir[2] * math.cos(target_angle) + plane_perpendicular[2] * sign * math.sin(target_angle),
    )
    corrected_dir = _normalize(corrected_dir)
    return (
        middle[0] + corrected_dir[0] * child_length,
        middle[1] + corrected_dir[1] * child_length,
        middle[2] + corrected_dir[2] * child_length,
    )


def _segment_target_lengths(frames: list[MotionFrame]) -> dict[tuple[str, str], float]:
    targets: dict[tuple[str, str], float] = {}
    for start, end, _radius in CANONICAL_CAPSULES:
        lengths = []
        for frame in frames:
            start_point = frame.joints.get(start)
            end_point = frame.joints.get(end)
            if start_point is None or end_point is None:
                continue
            length = _point_distance(start_point, end_point)
            if length > 1e-6:
                lengths.append(length)
        if lengths:
            targets[(start, end)] = _median(lengths)
    return targets


def _segment_motion_looks_implausible(
    frames: list[MotionFrame],
    *,
    frame_index: int,
    start: str,
    end: str,
    target_length: float,
) -> bool:
    current = frames[frame_index].joints
    start_point = current.get(start)
    end_point = current.get(end)
    if start_point is None or end_point is None:
        return False
    current_length = _point_distance(start_point, end_point)
    if abs(current_length - target_length) <= max(0.04, target_length * 0.18):
        return False
    if frame_index <= 0 or frame_index >= len(frames) - 1:
        return True
    previous = frames[frame_index - 1].joints
    following = frames[frame_index + 1].joints
    previous_length = _segment_length(previous, start, end)
    following_length = _segment_length(following, start, end)
    if previous_length is None or following_length is None:
        return True
    midpoint_length = (previous_length + following_length) * 0.5
    return abs(current_length - midpoint_length) > max(0.03, target_length * 0.12)


def _segment_length(joints: dict[str, tuple[float, float, float]], start: str, end: str) -> float | None:
    start_point = joints.get(start)
    end_point = joints.get(end)
    if start_point is None or end_point is None:
        return None
    return _point_distance(start_point, end_point)
def _frame_joint_center(frame: MotionFrame) -> tuple[float, float, float]:
    if not frame.joints:
        return (0.0, 0.0, 0.0)
    xs = [point[0] for point in frame.joints.values()]
    ys = [point[1] for point in frame.joints.values()]
    zs = [point[2] for point in frame.joints.values()]
    return (_median(xs), _median(ys), _median(zs))


def _smooth_preview_frames_once(frames: list[MotionFrame]) -> list[MotionFrame]:
    smoothed = list(frames)
    weights = (1.0, 2.0, 3.0, 4.0, 3.0, 2.0, 1.0)
    radius = 3
    for index, current_frame in enumerate(frames):
        start = max(0, index - radius)
        end = min(len(frames), index + radius + 1)
        window = frames[start:end]
        if len(window) < 3:
            continue
        joints: dict[str, tuple[float, float, float]] = {}
        for joint_name in current_frame.joints.keys():
            weighted_points: list[tuple[float, tuple[float, float, float]]] = []
            for window_index, frame in enumerate(window):
                point = frame.joints.get(joint_name)
                if point is None:
                    continue
                absolute_index = start + window_index
                distance = abs(absolute_index - index)
                weight = weights[min(distance, radius)]
                weighted_points.append((weight, point))
            if len(weighted_points) < 3:
                joints[joint_name] = current_frame.joints[joint_name]
                continue
            total_weight = sum(weight for weight, _ in weighted_points)
            averaged_point = (
                sum(point[0] * weight for weight, point in weighted_points) / total_weight,
                sum(point[1] * weight for weight, point in weighted_points) / total_weight,
                sum(point[2] * weight for weight, point in weighted_points) / total_weight,
            )
            original_point = current_frame.joints[joint_name]
            displacement = _point_distance(original_point, averaged_point)
            if displacement > 0.22:
                joints[joint_name] = original_point
                continue
            alpha = _preview_smoothing_alpha(
                joint_name,
                displacement,
                _motion_preservation_factor(frames, index=index, joint_name=joint_name),
            )
            joints[joint_name] = (
                original_point[0] * (1 - alpha) + averaged_point[0] * alpha,
                original_point[1] * (1 - alpha) + averaged_point[1] * alpha,
                original_point[2] * (1 - alpha) + averaged_point[2] * alpha,
            )
        smoothed[index] = MotionFrame(time_sec=current_frame.time_sec, joints=joints)
    return smoothed


def _preview_smoothing_alpha(joint_name: str, displacement: float, preservation_factor: float) -> float:
    intensity_boost = 0.12 if displacement < 0.06 else 0.0
    if "wrist" in joint_name or "hand" in joint_name:
        alpha = 0.72 + intensity_boost
    elif "elbow" in joint_name:
        alpha = 0.68 + intensity_boost
    elif "ankle" in joint_name or "foot" in joint_name:
        alpha = 0.62 + intensity_boost
    elif "hip" in joint_name or joint_name in {"pelvis", "spine1", "spine2", "spine3"}:
        alpha = 0.6 + intensity_boost
    elif "shoulder" in joint_name or "collar" in joint_name or joint_name == "neck":
        alpha = 0.56 + intensity_boost
    elif joint_name == "head":
        alpha = 0.52 + intensity_boost
    else:
        alpha = 0.5 + intensity_boost
    return max(0.1, alpha * (1.0 - preservation_factor))


def _motion_preservation_factor(frames: list[MotionFrame], *, index: int, joint_name: str) -> float:
    if index <= 0 or index >= len(frames) - 1:
        return 0.0
    previous_point = frames[index - 1].joints.get(joint_name)
    current_point = frames[index].joints.get(joint_name)
    next_point = frames[index + 1].joints.get(joint_name)
    if previous_point is None or current_point is None or next_point is None:
        return 0.0

    velocity_in = (
        current_point[0] - previous_point[0],
        current_point[1] - previous_point[1],
        current_point[2] - previous_point[2],
    )
    velocity_out = (
        next_point[0] - current_point[0],
        next_point[1] - current_point[1],
        next_point[2] - current_point[2],
    )
    speed_in = _vector_length(velocity_in)
    speed_out = _vector_length(velocity_out)
    if speed_in < 1e-6 or speed_out < 1e-6:
        return 0.0

    alignment = (
        velocity_in[0] * velocity_out[0]
        + velocity_in[1] * velocity_out[1]
        + velocity_in[2] * velocity_out[2]
    ) / (speed_in * speed_out)
    if alignment < 0.45:
        return 0.0

    motion_scale = min(speed_in, speed_out)
    if motion_scale < 0.035:
        return 0.0
    if motion_scale >= 0.12:
        return 0.85
    return min(0.85, (motion_scale - 0.035) / 0.085 * 0.85)


def _vector_length(vector: tuple[float, float, float]) -> float:
    return math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)


def _replace_local_temporal_outliers(frames: list[MotionFrame]) -> list[MotionFrame]:
    if len(frames) < 4:
        return frames
    sanitized = list(frames)
    radius = 2
    for index, current_frame in enumerate(frames):
        neighbor_indices = [
            neighbor_index
            for neighbor_index in range(max(0, index - radius), min(len(frames), index + radius + 1))
            if neighbor_index != index
        ]
        if len(neighbor_indices) < 2:
            continue
        neighbors = [sanitized[neighbor_index] for neighbor_index in neighbor_indices]
        reference_frame = _average_reference_frame(neighbors, current_frame.time_sec)
        current_error = _average_frame_distance(current_frame, reference_frame)
        if current_error <= 0.06:
            continue
        neighbor_errors = [
            _average_frame_distance(neighbor, reference_frame)
            for neighbor in neighbors
        ]
        neighbor_error = sum(neighbor_errors) / len(neighbor_errors) if neighbor_errors else 0.0
        if current_error <= max(0.08, neighbor_error * 3.0):
            continue
        if neighbor_error >= 0.05:
            continue
        sanitized[index] = reference_frame
    return sanitized


def _average_reference_frame(frames: list[MotionFrame], time_sec: float) -> MotionFrame:
    if not frames:
        return MotionFrame(time_sec=time_sec, joints={})
    joint_names = set()
    for frame in frames:
        joint_names.update(frame.joints.keys())
    joints: dict[str, tuple[float, float, float]] = {}
    for joint_name in joint_names:
        points = [frame.joints[joint_name] for frame in frames if joint_name in frame.joints]
        if not points:
            continue
        joints[joint_name] = (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
            sum(point[2] for point in points) / len(points),
        )
    return MotionFrame(time_sec=time_sec, joints=joints)


def _interpolate_frame(
    previous_frame: MotionFrame,
    next_frame: MotionFrame,
    time_sec: float,
    *,
    alpha_override: float | None = None,
) -> MotionFrame:
    joints: dict[str, tuple[float, float, float]] = {}
    joint_names = set(previous_frame.joints.keys()) | set(next_frame.joints.keys())
    alpha = 0.5 if alpha_override is None else min(max(alpha_override, 0.0), 1.0)
    for joint_name in joint_names:
        previous_point = previous_frame.joints.get(joint_name)
        next_point = next_frame.joints.get(joint_name)
        if previous_point is not None and next_point is not None:
            joints[joint_name] = (
                previous_point[0] * (1.0 - alpha) + next_point[0] * alpha,
                previous_point[1] * (1.0 - alpha) + next_point[1] * alpha,
                previous_point[2] * (1.0 - alpha) + next_point[2] * alpha,
            )
        elif previous_point is not None:
            joints[joint_name] = previous_point
        elif next_point is not None:
            joints[joint_name] = next_point
    return MotionFrame(time_sec=time_sec, joints=joints)


def _average_frame_distance(left: MotionFrame, right: MotionFrame) -> float:
    shared = set(left.joints.keys()) & set(right.joints.keys())
    if not shared:
        return 0.0
    total = 0.0
    count = 0
    for joint_name in shared:
        total += _point_distance(left.joints[joint_name], right.joints[joint_name])
        count += 1
    return total / count if count > 0 else 0.0


def _average_midpoint_error(previous_frame: MotionFrame, current_frame: MotionFrame, next_frame: MotionFrame) -> float:
    shared = set(previous_frame.joints.keys()) & set(current_frame.joints.keys()) & set(next_frame.joints.keys())
    if not shared:
        return 0.0
    total = 0.0
    count = 0
    for joint_name in shared:
        previous_point = previous_frame.joints[joint_name]
        current_point = current_frame.joints[joint_name]
        next_point = next_frame.joints[joint_name]
        midpoint = (
            (previous_point[0] + next_point[0]) * 0.5,
            (previous_point[1] + next_point[1]) * 0.5,
            (previous_point[2] + next_point[2]) * 0.5,
        )
        total += _point_distance(current_point, midpoint)
        count += 1
    return total / count if count > 0 else 0.0


def _subtract_points(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[0] - right[0],
        left[1] - right[1],
        left[2] - right[2],
    )


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _cross(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = _vector_length(vector)
    if length <= 1e-8:
        return (0.0, 0.0, 0.0)
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _rotate_point(
    point: tuple[float, float, float],
    *,
    axis: tuple[float, float, float],
    angle: float,
) -> tuple[float, float, float]:
    axis = _normalize(axis)
    if _vector_length(axis) <= 1e-8 or abs(angle) <= 1e-8:
        return point
    cos_angle = math.cos(angle)
    sin_angle = math.sin(angle)
    axis_dot_point = _dot(axis, point)
    axis_cross_point = _cross(axis, point)
    return (
        point[0] * cos_angle
        + axis_cross_point[0] * sin_angle
        + axis[0] * axis_dot_point * (1.0 - cos_angle),
        point[1] * cos_angle
        + axis_cross_point[1] * sin_angle
        + axis[1] * axis_dot_point * (1.0 - cos_angle),
        point[2] * cos_angle
        + axis_cross_point[2] * sin_angle
        + axis[2] * axis_dot_point * (1.0 - cos_angle),
    )


def _point_distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return math.sqrt(
        (left[0] - right[0]) ** 2 +
        (left[1] - right[1]) ** 2 +
        (left[2] - right[2]) ** 2
    )


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return float(sorted_values[midpoint])
    return float((sorted_values[midpoint - 1] + sorted_values[midpoint]) * 0.5)


def _build_capsules(clip: MotionClip) -> list[dict[str, object]]:
    resolved = {
        canonical: next((name for name in JOINT_ALIASES.get(canonical, (canonical,)) if name in clip.joint_names), None)
        for canonical in {
            joint_name
            for capsule in CANONICAL_CAPSULES
            for joint_name in capsule[:2]
        }
    }
    capsules: list[dict[str, object]] = []
    for start, end, radius in CANONICAL_CAPSULES:
        resolved_start = resolved.get(start) or (start if start in clip.joint_names else None)
        resolved_end = resolved.get(end) or (end if end in clip.joint_names else None)
        if resolved_start is None or resolved_end is None:
            continue
        capsules.append(
            {
                "start": resolved_start,
                "end": resolved_end,
                "radius": radius,
            }
        )
    return capsules


def _find_root_joint(clip: MotionClip) -> str | None:
    for candidate in ("pelvis", "hips", "root"):
        if candidate in clip.joint_names:
            return candidate
    return None


def _is_loopable(clip: MotionClip) -> bool:
    return bool(_detect_preview_loops(clip))


def _detect_preview_loops(clip: MotionClip) -> list[dict[str, object]]:
    if clip.frame_count < 2:
        return []
    minimum_frames = max(2, int(math.ceil(clip.fps * MIN_LOOP_DURATION_SECONDS)))
    if clip.frame_count <= minimum_frames:
        return []
    root_joint = _find_root_joint(clip)
    key_joints = [
        joint_name
        for joint_name in ("pelvis", "left_foot", "right_foot", "left_hand", "right_hand", "head")
        if joint_name in clip.joint_names
    ]
    if not key_joints:
        return []
    support_states = _extract_preview_support_states(clip)
    candidates: list[dict[str, object]] = []
    for start_index in range(0, clip.frame_count - minimum_frames):
        for end_index in range(start_index + minimum_frames, clip.frame_count):
            if not _preview_loop_support_states_are_compatible(
                support_states=support_states,
                start_index=start_index,
                end_index=end_index,
            ):
                continue
            absolute_mismatches = _preview_loop_pose_mismatches(
                clip,
                start_index=start_index,
                end_index=end_index,
                key_joints=key_joints,
                root_joint=root_joint,
                localize=False,
            )
            local_mismatches = _preview_loop_pose_mismatches(
                clip,
                start_index=start_index,
                end_index=end_index,
                key_joints=key_joints,
                root_joint=root_joint,
                localize=True,
            )
            if not _preview_loop_pose_mismatches_are_acceptable(absolute_mismatches, local_mismatches):
                continue
            velocity_cost = _preview_loop_velocity_cost(
                clip,
                start_index=start_index,
                end_index=end_index,
                key_joints=key_joints,
                root_joint=root_joint,
            )
            absolute_cost = _preview_loop_pose_cost(absolute_mismatches)
            local_cost = _preview_loop_pose_cost(local_mismatches)
            score = absolute_cost * 0.65 + local_cost * 0.35 + velocity_cost * 0.4
            duration_sec = clip.frames[end_index].time_sec - clip.frames[start_index].time_sec
            candidates.append(
                {
                    "startFrame": start_index,
                    "endFrame": end_index,
                    "startTimeSec": clip.frames[start_index].time_sec,
                    "endTimeSec": clip.frames[end_index].time_sec,
                    "durationSec": duration_sec,
                    "score": score,
                }
            )
    if not candidates:
        return []
    candidates.sort(key=lambda item: (float(item["score"]), -float(item["durationSec"])))
    selected: list[dict[str, object]] = []
    for candidate in candidates:
        if any(_preview_loop_candidates_overlap(candidate, existing) for existing in selected):
            continue
        selected.append(
            {
                **candidate,
                "label": (
                    f"Loop {len(selected) + 1}: "
                    f"{float(candidate['startTimeSec']):.2f}s -> {float(candidate['endTimeSec']):.2f}s "
                    f"({float(candidate['durationSec']):.2f}s)"
                ),
            }
        )
        if len(selected) >= MAX_DETECTED_LOOPS:
            break
    return selected


def _extract_preview_support_states(clip: MotionClip) -> list[dict[str, object]]:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    cleanup = metadata.get("cleanup") if isinstance(metadata, dict) else None
    states = cleanup.get("footContacts") if isinstance(cleanup, dict) else None
    if not isinstance(states, list):
        return []
    return [item for item in states if isinstance(item, dict)]


def _preview_loop_candidates_overlap(left: dict[str, object], right: dict[str, object]) -> bool:
    left_start = int(left["startFrame"])
    left_end = int(left["endFrame"])
    right_start = int(right["startFrame"])
    right_end = int(right["endFrame"])
    return not (left_end < right_start or right_end < left_start)


def _preview_loop_support_states_are_compatible(
    *,
    support_states: list[dict[str, object]],
    start_index: int,
    end_index: int,
) -> bool:
    if not support_states:
        return True
    if start_index >= len(support_states) or end_index >= len(support_states):
        return False
    return _preview_support_state_family(support_states[start_index]) == _preview_support_state_family(support_states[end_index])


def _preview_support_state_family(support_state: dict[str, object]) -> str:
    if bool(support_state.get("leftHandInContact")) and bool(support_state.get("rightHandInContact")):
        return "double_hand_support"
    if bool(support_state.get("leftInContact")) and bool(support_state.get("rightInContact")):
        return "double_foot_support"
    if bool(support_state.get("leftHandInContact")) or bool(support_state.get("rightHandInContact")):
        if bool(support_state.get("leftInContact")) or bool(support_state.get("rightInContact")):
            return "mixed_support"
        return "hand_support"
    if bool(support_state.get("leftInContact")) or bool(support_state.get("rightInContact")):
        return "foot_support"
    raw_state = support_state.get("state")
    return str(raw_state) if isinstance(raw_state, str) and raw_state else "airborne"


def _preview_loop_pose_mismatches(
    clip: MotionClip,
    *,
    start_index: int,
    end_index: int,
    key_joints: list[str],
    root_joint: str | None,
    localize: bool,
) -> dict[str, float]:
    start_frame = clip.frames[start_index]
    end_frame = clip.frames[end_index]
    start_root = start_frame.joints.get(root_joint) if root_joint is not None else None
    end_root = end_frame.joints.get(root_joint) if root_joint is not None else None
    mismatches: dict[str, float] = {}
    for joint_name in key_joints:
        start_point = start_frame.joints.get(joint_name)
        end_point = end_frame.joints.get(joint_name)
        if start_point is None or end_point is None:
            continue
        if localize and start_root is not None and end_root is not None:
            start_point = _localize_point(start_point, origin=start_root)
            end_point = _localize_point(end_point, origin=end_root)
        mismatches[joint_name] = _point_distance(start_point, end_point)
    return mismatches


def _preview_loop_pose_cost(pose_mismatches: dict[str, float]) -> float:
    distances = list(pose_mismatches.values())
    return sum(distances) / len(distances) if distances else float("inf")


def _preview_loop_pose_mismatches_are_acceptable(
    absolute_mismatches: dict[str, float],
    local_mismatches: dict[str, float],
) -> bool:
    if not absolute_mismatches or not local_mismatches:
        return False
    if _preview_loop_pose_cost(absolute_mismatches) > 0.18:
        return False
    if _preview_loop_pose_cost(local_mismatches) > 0.16:
        return False
    thresholds = {
        "pelvis": 0.14,
        "head": 0.18,
        "left_hand": 0.20,
        "right_hand": 0.20,
        "left_foot": 0.18,
        "right_foot": 0.18,
    }
    for joint_name, threshold in thresholds.items():
        absolute_value = absolute_mismatches.get(joint_name)
        if absolute_value is not None and absolute_value > threshold:
            return False
    return True


def _preview_loop_velocity_cost(
    clip: MotionClip,
    *,
    start_index: int,
    end_index: int,
    key_joints: list[str],
    root_joint: str | None,
) -> float:
    if start_index <= 0 or end_index >= clip.frame_count - 1:
        return 0.0
    start_frame = clip.frames[start_index]
    next_start = clip.frames[start_index + 1]
    prev_end = clip.frames[end_index - 1]
    end_frame = clip.frames[end_index]
    start_root = start_frame.joints.get(root_joint) if root_joint is not None else None
    next_start_root = next_start.joints.get(root_joint) if root_joint is not None else None
    prev_end_root = prev_end.joints.get(root_joint) if root_joint is not None else None
    end_root = end_frame.joints.get(root_joint) if root_joint is not None else None
    distances: list[float] = []
    for joint_name in key_joints:
        if (
            joint_name not in start_frame.joints
            or joint_name not in next_start.joints
            or joint_name not in prev_end.joints
            or joint_name not in end_frame.joints
        ):
            continue
        start_local = start_frame.joints[joint_name]
        next_start_local = next_start.joints[joint_name]
        prev_end_local = prev_end.joints[joint_name]
        end_local = end_frame.joints[joint_name]
        if start_root is not None and next_start_root is not None and prev_end_root is not None and end_root is not None:
            start_local = _localize_point(start_local, origin=start_root)
            next_start_local = _localize_point(next_start_local, origin=next_start_root)
            prev_end_local = _localize_point(prev_end_local, origin=prev_end_root)
            end_local = _localize_point(end_local, origin=end_root)
        start_velocity = (
            next_start_local[0] - start_local[0],
            next_start_local[1] - start_local[1],
            next_start_local[2] - start_local[2],
        )
        end_velocity = (
            end_local[0] - prev_end_local[0],
            end_local[1] - prev_end_local[1],
            end_local[2] - prev_end_local[2],
        )
        distances.append(_point_distance(start_velocity, end_velocity))
    return sum(distances) / len(distances) if distances else 0.0


def _localize_point(point: tuple[float, float, float], *, origin: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        point[0] - origin[0],
        point[1] - origin[1],
        point[2] - origin[2],
    )


def _build_html(payload: dict[str, object]) -> str:
    payload_json = json.dumps(payload)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{payload["title"]}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #101418;
      --panel: #182028;
      --ink: #f3f7fa;
      --muted: #8fa3b5;
      --accent: #8ad7d1;
    }}
    body {{
      margin: 0;
      font-family: "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top, rgba(62, 96, 102, 0.26), transparent 34%),
        radial-gradient(circle at bottom right, rgba(17, 62, 78, 0.28), transparent 28%),
        linear-gradient(180deg, #0f1519 0%, #0b1014 100%);
      color: var(--ink);
      overflow: hidden;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(280px, 360px) 1fr;
      height: 100vh;
      min-height: 100vh;
      overflow: hidden;
    }}
    .panel {{
      padding: 24px;
      background: rgba(24, 32, 40, 0.94);
      border-right: 1px solid rgba(255, 255, 255, 0.08);
      height: 100vh;
      overflow-y: auto;
      box-sizing: border-box;
    }}
    h1 {{
      font-size: 1.4rem;
      margin: 0 0 12px;
    }}
    p, li {{
      color: var(--muted);
      line-height: 1.45;
    }}
    #viewport {{
      width: 100%;
      height: 100vh;
      display: block;
    }}
    .controls {{
      display: grid;
      gap: 12px;
      margin-top: 20px;
    }}
    label {{
      display: grid;
      gap: 6px;
      font-size: 0.95rem;
    }}
    input[type="range"] {{
      width: 100%;
    }}
    .stat {{
      font-variant-numeric: tabular-nums;
    }}
    @media (max-width: 860px) {{
      body {{
        overflow: auto;
      }}
      .layout {{
        grid-template-columns: 1fr;
        height: auto;
        overflow: visible;
      }}
      .panel {{
        border-right: 0;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        height: auto;
      }}
      #viewport {{
        height: 60vh;
      }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="panel">
      <h1>{payload["title"]}</h1>
      <p>Interactive skeleton preview for the recovered motion after cleanup. Drag to rotate. Use this as the manual review gate before retargeting to a final Wear model.</p>
      <div class="controls">
        <label>Playback speed
          <input id="speed" type="range" min="0.25" max="2" step="0.05" value="1" />
        </label>
        <button id="pauseToggle" type="button">Pause</button>
        <label>Zoom
          <input id="zoom" type="range" min="120" max="420" step="10" value="240" />
        </label>
        <label>Camera mode
          <select id="cameraMode">
            <option value="perspective">Perspective</option>
            <option value="orthographic">Orthographic</option>
          </select>
        </label>
        <label>Vertical tilt
          <input id="pitch" type="range" min="-1.2" max="1.2" step="0.05" value="0.35" />
        </label>
        <label>Use automatic world alignment
          <input id="autoWorldAlignment" type="checkbox" />
        </label>
        <label>World rotate X
          <input id="rotateX" type="range" min="-90" max="90" step="1" value="0" />
        </label>
        <label>World rotate Y
          <input id="rotateY" type="range" min="-180" max="180" step="1" value="0" />
        </label>
        <label>World rotate Z
          <input id="rotateZ" type="range" min="-90" max="90" step="1" value="0" />
        </label>
        <label>World translate X
          <input id="translateX" type="range" min="-2" max="2" step="0.01" value="0" />
        </label>
        <label>World translate Y
          <input id="translateY" type="range" min="-2" max="2" step="0.01" value="0" />
        </label>
        <label>World translate Z
          <input id="translateZ" type="range" min="-2" max="2" step="0.01" value="0" />
        </label>
        <div class="stat">World rotation: <span id="worldRotationReadout">0, 0, 0</span></div>
        <div class="stat">World translation: <span id="worldTranslationReadout">0, 0, 0</span></div>
        <button id="resetTransform" type="button">Reset world transform</button>
        <label>Root translation
          <input id="fixedRoot" type="checkbox" />
          <span id="rootTranslationLabel"></span>
        </label>
        <label>Loop preview
          <select id="loopSelect"></select>
        </label>
        <div class="stat">Detected loops: <span id="loopCount"></span></div>
        <div class="stat">Active span: <span id="activeLoop">Full clip</span></div>
        <div class="stat">Frames: <span id="frameCount"></span></div>
        <div class="stat">FPS: <span id="fps"></span></div>
        <div class="stat">Current frame: <span id="frameIndex">0</span></div>
      </div>
      <ul>
        <li>Expected next stage: retarget this cleaned motion to the low-poly humanoid rig.</li>
        <li>If wrists, feet, or loop boundaries still look wrong, reject and re-run with a better source clip.</li>
      </ul>
    </aside>
    <main>
      <div id="viewport"></div>
    </main>
  </div>
    <script type="importmap">
    {{
      "imports": {{
        "three": "https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js",
        "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/"
      }}
    }}
    </script>
    <script type="module">
    import * as THREE from "three";
    import {{ GLTFLoader }} from "three/addons/loaders/GLTFLoader.js";

    const payload = {payload_json};
    const viewport = document.getElementById("viewport");
    const speedInput = document.getElementById("speed");
    const pauseToggleButton = document.getElementById("pauseToggle");
    const zoomInput = document.getElementById("zoom");
    const cameraModeSelect = document.getElementById("cameraMode");
    const pitchInput = document.getElementById("pitch");
    const autoWorldAlignmentInput = document.getElementById("autoWorldAlignment");
    const rotateXInput = document.getElementById("rotateX");
    const rotateYInput = document.getElementById("rotateY");
    const rotateZInput = document.getElementById("rotateZ");
    const translateXInput = document.getElementById("translateX");
    const translateYInput = document.getElementById("translateY");
    const translateZInput = document.getElementById("translateZ");
    const resetTransformButton = document.getElementById("resetTransform");
    const fixedRootInput = document.getElementById("fixedRoot");
    const loopSelect = document.getElementById("loopSelect");
    const loopCountNode = document.getElementById("loopCount");
    const activeLoopNode = document.getElementById("activeLoop");
    const rootTranslationLabel = document.getElementById("rootTranslationLabel");
    const frameIndexNode = document.getElementById("frameIndex");
    const worldRotationReadoutNode = document.getElementById("worldRotationReadout");
    const worldTranslationReadoutNode = document.getElementById("worldTranslationReadout");
    document.getElementById("frameCount").textContent = String(payload.frameCount);
    document.getElementById("fps").textContent = String(payload.fps);

    let yaw = -0.55;
    let pitch = parseFloat(pitchInput.value);
    let zoom = parseFloat(zoomInput.value);
    let speed = parseFloat(speedInput.value);
    let cameraMode = cameraModeSelect.value;
    let fixedRoot = Boolean(payload.defaultFixedRoot);
    let paused = false;
    let frameCursor = 0;
    let playbackDirection = 1;
    let lastTimestamp = null;
    let dragging = false;
    let dragX = 0;
    let dragY = 0;
    let pendingReframeHandle = null;
    let autoWorldAlignmentEnabled = Boolean(payload.defaultAutoWorldAlignment);
    const translationTrack = buildTranslationTrack(payload.frames);
    const cameraTarget = new THREE.Vector3();
    const transformPivot = new THREE.Vector3();
    const manualRotation = new THREE.Euler(0, 0, 0, "XYZ");
    const manualTranslation = new THREE.Vector3(0, 0, 0);
    const defaultAutoAlignment = Array.isArray(payload.defaultAutoAlignment) ? payload.defaultAutoAlignment : [];
    const detectedLoops = Array.isArray(payload.detectedLoops) ? payload.detectedLoops : [];
    let selectedLoopIndex = detectedLoops.length > 0 ? 0 : -1;
    let currentLoop = selectedLoopIndex >= 0 ? detectedLoops[selectedLoopIndex] : null;
    let currentAutoAlignment = currentLoop?.autoAlignment ?? defaultAutoAlignment;
    let playbackState = buildPlaybackState(payload.frames, currentLoop);
    fixedRootInput.checked = fixedRoot;
    autoWorldAlignmentInput.checked = autoWorldAlignmentEnabled;
    rootTranslationLabel.textContent = payload.rootTranslationToggleLabel ?? "Lock global root drift";
    loopCountNode.textContent = String(detectedLoops.length);
    populateLoopSelect();
    refreshActiveLoopLabel();

    const renderer = new THREE.WebGLRenderer({{
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    }});
    renderer.setClearColor(0x101418, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    viewport.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const perspectiveCamera = new THREE.PerspectiveCamera(34, 1, 0.01, 100);
    const orthographicCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 100);
    let activeCamera = perspectiveCamera;
    scene.add(perspectiveCamera);
    scene.add(orthographicCamera);

    const ambientLight = new THREE.AmbientLight(0x6d7d88, 0.8);
    scene.add(ambientLight);
    const hemiLight = new THREE.HemisphereLight(0xc9ecf2, 0x0a0f12, 1.15);
    scene.add(hemiLight);
    const directionalLight = new THREE.DirectionalLight(0xf8f2df, 2.1);
    directionalLight.position.set(-4.6, 6.8, 3.2);
    scene.add(directionalLight);
    const rimLight = new THREE.DirectionalLight(0x87d3ff, 0.85);
    rimLight.position.set(3.6, 2.4, -5.2);
    scene.add(rimLight);

    const grid = new THREE.GridHelper(3.5, 10, 0x6ea2ae, 0x31444d);
    scene.add(grid);
    const mergedBoundsHelper = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
      new THREE.LineBasicMaterial({{ color: 0xe5bc62, transparent: true, opacity: 0.9 }})
    );
    scene.add(mergedBoundsHelper);

    const limbMaterial = new THREE.MeshStandardMaterial({{
        color: 0x9fc7c1,
        emissive: 0x0c1718,
        emissiveIntensity: 0.18,
        roughness: 0.46,
        metalness: 0.02,
        flatShading: true,
      }});
    const torsoMaterial = new THREE.MeshStandardMaterial({{
        color: 0xadc7ba,
        emissive: 0x101817,
        emissiveIntensity: 0.12,
        roughness: 0.5,
        metalness: 0.02,
        flatShading: true,
      }});
    const headMaterial = new THREE.MeshStandardMaterial({{
        color: 0xd7e2d5,
        emissive: 0x101514,
        emissiveIntensity: 0.12,
        roughness: 0.4,
        metalness: 0.02,
        flatShading: true,
      }});
    const cylinderGeometry = new THREE.CylinderGeometry(1, 1, 1, 8, 1, false);
    const taperedLimbGeometry = new THREE.CylinderGeometry(0.8, 1.0, 1, 6, 1, false);
    const pelvisGeometry = new THREE.CylinderGeometry(0.72, 1.0, 1, 7, 1, false);
    const ribcageGeometry = new THREE.CylinderGeometry(1.0, 0.74, 1, 7, 1, false);
    const clavicleGeometry = new THREE.BoxGeometry(1, 1, 1);
    const shoulderGeometry = new THREE.IcosahedronGeometry(1, 0);
    const headGeometry = new THREE.IcosahedronGeometry(1, 1);
    const axisX = new THREE.Vector3(1, 0, 0);
    const axisY = new THREE.Vector3(0, 1, 0);
    const axisZ = new THREE.Vector3(0, 0, 1);
    const tempVector = new THREE.Vector3();
    const tempMidpoint = new THREE.Vector3();
    const tempQuaternion = new THREE.Quaternion();
    const tempScale = new THREE.Vector3();
    const tempPivotedPoint = new THREE.Vector3();
    const tempMatrix = new THREE.Matrix4();
    const sceneRotationQuaternion = new THREE.Quaternion();
    const sceneUp = new THREE.Vector3(0, 1, 0);
    const sceneRight = new THREE.Vector3(1, 0, 0);
    const sceneForward = new THREE.Vector3(0, 0, 1);

    function isTorsoCapsule(capsule) {{
      const key = `${{capsule.start}}->${{capsule.end}}`;
      return key === "pelvis->spine1"
        || key === "spine1->spine2"
        || key === "spine2->spine3"
        || key === "spine3->neck"
        || key === "neck->left_collar"
        || key === "left_collar->left_shoulder"
        || key === "neck->right_collar"
        || key === "right_collar->right_shoulder";
    }}

    const limbNodes = payload.capsules
        .filter((capsule) => !isTorsoCapsule(capsule))
        .map((capsule) => {{
        const mesh = new THREE.Mesh(taperedLimbGeometry, limbMaterial);
        scene.add(mesh);
        return {{
          capsule,
          mesh,
        }};
      }});

    const pelvisMesh = new THREE.Mesh(pelvisGeometry, torsoMaterial);
    const abdomenMesh = new THREE.Mesh(cylinderGeometry, torsoMaterial);
    const chestMesh = new THREE.Mesh(ribcageGeometry, torsoMaterial);
    const upperChestMesh = new THREE.Mesh(cylinderGeometry, torsoMaterial);
    const leftShoulderMassMesh = new THREE.Mesh(shoulderGeometry, torsoMaterial);
    const rightShoulderMassMesh = new THREE.Mesh(shoulderGeometry, torsoMaterial);
    const clavicleMesh = new THREE.Mesh(clavicleGeometry, torsoMaterial);
    scene.add(pelvisMesh);
    scene.add(abdomenMesh);
    scene.add(chestMesh);
    scene.add(upperChestMesh);
    scene.add(leftShoulderMassMesh);
    scene.add(rightShoulderMassMesh);
    scene.add(clavicleMesh);

    const headMesh = new THREE.Mesh(headGeometry, headMaterial);
    scene.add(headMesh);

    const MANNEQUIN_BONE_MAP = {{
      "root.x": ["pelvis", "spine1"],
      "spine_01.x": ["pelvis", "spine1"],
      "spine_02.x": ["spine1", "spine2"],
      "spine_03.x": ["spine2", "neck"],
      "neck.x": ["neck", "head"],
      "head.x": ["neck", "head"],
      "shoulder.l": ["neck", "left_shoulder"],
      "arm_stretch.l": ["left_shoulder", "left_elbow"],
      "forearm_stretch.l": ["left_elbow", "left_wrist"],
      "hand.l": ["left_wrist", "left_hand"],
      "shoulder.r": ["neck", "right_shoulder"],
      "arm_stretch.r": ["right_shoulder", "right_elbow"],
      "forearm_stretch.r": ["right_elbow", "right_wrist"],
      "hand.r": ["right_wrist", "right_hand"],
      "thigh_stretch.l": ["left_hip", "left_knee"],
      "leg_stretch.l": ["left_knee", "left_ankle"],
      "foot.l": ["left_ankle", "left_foot"],
      "thigh_stretch.r": ["right_hip", "right_knee"],
      "leg_stretch.r": ["right_knee", "right_ankle"],
      "foot.r": ["right_ankle", "right_foot"],
    }};
    let mannequinRoot = null;
    let mannequinBones = new Map();
    let mannequinBoneStates = new Map();
    let mannequinSkinnedMeshes = [];
    let mannequinReady = false;
    let mannequinFailed = false;
    let mannequinScale = 1.0;
    let mannequinBasePelvis = null;
    let mannequinBaseRoot = null;

    function computeBaseSceneBounds(currentFixedRoot) {{
      const frames = playbackState.boundsFrames;
      if (frames.length === 0) {{
        return {{
          minX: -0.8,
          maxX: 0.8,
          minY: -0.2,
          maxY: 1.4,
          minZ: -0.8,
          maxZ: 0.8,
        }};
      }}
      let minX = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      let minZ = Number.POSITIVE_INFINITY;
      let maxZ = Number.NEGATIVE_INFINITY;
      for (const frame of frames) {{
        const frameTranslation = currentFixedRoot ? getFrameTranslation(frame) : [0, 0, 0];
        for (const jointName of payload.jointNames) {{
          const point = frame.joints[jointName];
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          const worldPoint = toBaseWorldPoint(point, frameTranslation);
          minX = Math.min(minX, worldPoint.x);
          maxX = Math.max(maxX, worldPoint.x);
          minY = Math.min(minY, worldPoint.y);
          maxY = Math.max(maxY, worldPoint.y);
          minZ = Math.min(minZ, worldPoint.z);
          maxZ = Math.max(maxZ, worldPoint.z);
        }}
      }}
      if (!Number.isFinite(minX) || !Number.isFinite(maxX)) {{
        return {{
          minX: -0.8,
          maxX: 0.8,
          minY: -0.2,
          maxY: 1.4,
          minZ: -0.8,
          maxZ: 0.8,
        }};
      }}
      return {{ minX, maxX, minY, maxY, minZ, maxZ }};
    }}

    function computeSceneBounds(currentFixedRoot) {{
      const frames = playbackState.boundsFrames;
      if (frames.length === 0) {{
        return computeBaseSceneBounds(currentFixedRoot);
      }}
      refreshTransformPivot(currentFixedRoot);
      let minX = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      let minZ = Number.POSITIVE_INFINITY;
      let maxZ = Number.NEGATIVE_INFINITY;
      for (const frame of frames) {{
        const frameTranslation = currentFixedRoot ? getFrameTranslation(frame) : [0, 0, 0];
        for (const jointName of payload.jointNames) {{
          const point = frame.joints[jointName];
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          const worldPoint = toWorldPoint(point, frameTranslation, currentFixedRoot);
          minX = Math.min(minX, worldPoint.x);
          maxX = Math.max(maxX, worldPoint.x);
          minY = Math.min(minY, worldPoint.y);
          maxY = Math.max(maxY, worldPoint.y);
          minZ = Math.min(minZ, worldPoint.z);
          maxZ = Math.max(maxZ, worldPoint.z);
        }}
      }}
      if (!Number.isFinite(minX) || !Number.isFinite(maxX)) {{
        return computeBaseSceneBounds(currentFixedRoot);
      }}
      return {{ minX, maxX, minY, maxY, minZ, maxZ }};
    }}

    function computeOrientedSceneBounds(currentFixedRoot) {{
      const frames = playbackState.boundsFrames;
      if (frames.length === 0) {{
        return computeSceneBounds(currentFixedRoot);
      }}
      refreshTransformPivot(currentFixedRoot);
      refreshSceneBasis();
      const inverseSceneRotation = sceneRotationQuaternion.clone().invert();
      let minX = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      let minZ = Number.POSITIVE_INFINITY;
      let maxZ = Number.NEGATIVE_INFINITY;
      for (const frame of frames) {{
        const frameTranslation = currentFixedRoot ? getFrameTranslation(frame) : [0, 0, 0];
        for (const jointName of payload.jointNames) {{
          const point = frame.joints[jointName];
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          const worldPoint = toWorldPoint(point, frameTranslation, currentFixedRoot);
          const localPoint = worldPoint.clone().applyQuaternion(inverseSceneRotation);
          minX = Math.min(minX, localPoint.x);
          maxX = Math.max(maxX, localPoint.x);
          minY = Math.min(minY, localPoint.y);
          maxY = Math.max(maxY, localPoint.y);
          minZ = Math.min(minZ, localPoint.z);
          maxZ = Math.max(maxZ, localPoint.z);
        }}
      }}
      if (!Number.isFinite(minX) || !Number.isFinite(maxX)) {{
        return computeSceneBounds(currentFixedRoot);
      }}
      return {{ minX, maxX, minY, maxY, minZ, maxZ }};
    }}

    function getFrameBounds(frame) {{
      let minX = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      let minZ = Number.POSITIVE_INFINITY;
      let maxZ = Number.NEGATIVE_INFINITY;
      for (const jointName of payload.jointNames) {{
        const point = frame.joints[jointName];
        if (!Array.isArray(point) || point.length < 3) {{
          continue;
        }}
        minX = Math.min(minX, point[0]);
        maxX = Math.max(maxX, point[0]);
        minY = Math.min(minY, point[1]);
        maxY = Math.max(maxY, point[1]);
        minZ = Math.min(minZ, point[2]);
        maxZ = Math.max(maxZ, point[2]);
      }}
      if (!Number.isFinite(minX) || !Number.isFinite(maxX)) {{
        return null;
      }}
      return {{ minX, maxX, minY, maxY, minZ, maxZ }};
    }}

    function buildTranslationTrack(frames) {{
      if (!frames || frames.length === 0) {{
        return [];
      }}
      const baseCenter = getFrameCenter(frames[0]);
      return frames.map((frame) => {{
        const center = getFrameCenter(frame);
        if (!center) {{
          return {{ x: 0, y: 0, z: 0 }};
        }}
        return {{
          x: center.x - baseCenter.x,
          y: center.y - baseCenter.y,
          z: center.z - baseCenter.z,
        }};
      }});
    }}

    function getFrameCenter(frame) {{
      const xs = [];
      const ys = [];
      const zs = [];
      for (const jointName of payload.jointNames) {{
        const point = frame.joints[jointName];
        if (!Array.isArray(point) || point.length < 3) {{
          continue;
        }}
        xs.push(point[0]);
        ys.push(point[1]);
        zs.push(point[2]);
      }}
      if (xs.length === 0 || ys.length === 0 || zs.length === 0) {{
        return null;
      }}
      return {{
        x: median(xs),
        y: median(ys),
        z: median(zs),
      }};
    }}

    function median(values) {{
      if (values.length === 0) {{
        return 0;
      }}
      const sorted = [...values].sort((left, right) => left - right);
      const midpoint = Math.floor(values.length / 2);
      if (sorted.length % 2 === 1) {{
        return sorted[midpoint];
      }}
      return (sorted[midpoint - 1] + sorted[midpoint]) * 0.5;
    }}

    function estimateSceneOrigin(currentFixedRoot) {{
      const bounds = computeOrientedSceneBounds(currentFixedRoot);
      const localOrigin = new THREE.Vector3(
        (bounds.minX + bounds.maxX) * 0.5,
        (bounds.minY + bounds.maxY) * 0.5,
        (bounds.minZ + bounds.maxZ) * 0.5
      );
      refreshSceneBasis();
      localOrigin.applyQuaternion(sceneRotationQuaternion);
      return [localOrigin.x, localOrigin.y, localOrigin.z];
    }}

    function refreshTransformPivot(currentFixedRoot) {{
      const bounds = computeBaseSceneBounds(currentFixedRoot);
      transformPivot.set(
        (bounds.minX + bounds.maxX) * 0.5,
        (bounds.minY + bounds.maxY) * 0.5,
        (bounds.minZ + bounds.maxZ) * 0.5
      );
    }}

    function refreshGroundPlacement() {{
      const bounds = computeOrientedSceneBounds(fixedRoot);
      refreshSceneBasis();
      const localCenter = new THREE.Vector3(
        (bounds.minX + bounds.maxX) * 0.5,
        bounds.minY - 0.06,
        (bounds.minZ + bounds.maxZ) * 0.5
      );
      localCenter.applyQuaternion(sceneRotationQuaternion);
      grid.position.copy(localCenter);
      grid.quaternion.copy(sceneRotationQuaternion);
    }}

    function refreshMergedBoundsHelper() {{
      const bounds = computeOrientedSceneBounds(fixedRoot);
      refreshSceneBasis();
      const center = new THREE.Vector3(
        (bounds.minX + bounds.maxX) * 0.5,
        (bounds.minY + bounds.maxY) * 0.5,
        (bounds.minZ + bounds.maxZ) * 0.5
      ).applyQuaternion(sceneRotationQuaternion);
      mergedBoundsHelper.position.copy(center);
      mergedBoundsHelper.quaternion.copy(sceneRotationQuaternion);
      mergedBoundsHelper.scale.set(
        Math.max(0.001, bounds.maxX - bounds.minX),
        Math.max(0.001, bounds.maxY - bounds.minY),
        Math.max(0.001, bounds.maxZ - bounds.minZ)
      );
    }}

    function refreshCameraTarget() {{
      const sceneOrigin = estimateSceneOrigin(fixedRoot);
      cameraTarget.set(sceneOrigin[0], sceneOrigin[1], sceneOrigin[2]);
    }}

    function refreshSceneFrame() {{
      refreshMergedBoundsHelper();
      refreshGroundPlacement();
      refreshCameraTarget();
    }}

    function scheduleSceneReframe() {{
      if (pendingReframeHandle != null) {{
        return;
      }}
      pendingReframeHandle = requestAnimationFrame(() => {{
        pendingReframeHandle = null;
        refreshSceneFrame();
      }});
    }}

    function buildPlaybackFrames(frames, loop) {{
      if (!loop) {{
        return frames;
      }}
      const startFrame = Number.isInteger(loop.startFrame) ? loop.startFrame : 0;
      const endFrame = Number.isInteger(loop.endFrame) ? loop.endFrame : (frames.length - 1);
      const clipped = frames.slice(
        Math.max(0, Math.min(frames.length - 1, startFrame)),
        Math.max(0, Math.min(frames.length, endFrame + 1))
      );
      if (clipped.length <= 1) {{
        return clipped;
      }}
      const transitionFrames = Math.min(10, Math.max(4, Math.floor(payload.fps * 0.25)));
      const loopStart = clipped[0];
      const loopEnd = clipped[clipped.length - 1];
      const appended = [];
      for (let index = 1; index <= transitionFrames; index += 1) {{
        const alpha = index / (transitionFrames + 1);
        const joints = {{}};
        for (const jointName of payload.jointNames) {{
          const start = loopStart.joints[jointName];
          const end = loopEnd.joints[jointName];
          if (!start || !end) {{
            continue;
          }}
          joints[jointName] = [
            end[0] * (1 - alpha) + start[0] * alpha,
            end[1] * (1 - alpha) + start[1] * alpha,
            end[2] * (1 - alpha) + start[2] * alpha,
          ];
        }}
        appended.push({{
          frameIndex: loopEnd.frameIndex ?? (frames.length - 1),
          timeSec: loopEnd.timeSec + index / payload.fps,
          joints,
        }});
      }}
      return [...clipped, ...appended];
    }}

    function buildPlaybackState(frames, loop) {{
      const activeFrames = buildPlaybackFrames(frames, loop);
      const boundsFrames = loop
        ? frames.slice(
            Math.max(0, Math.min(frames.length - 1, loop.startFrame ?? 0)),
            Math.max(0, Math.min(frames.length, (loop.endFrame ?? (frames.length - 1)) + 1))
          )
        : frames;
      return {{
        frames: activeFrames,
        boundsFrames,
        loopable: Boolean(loop),
      }};
    }}

    function populateLoopSelect() {{
      loopSelect.innerHTML = "";
      const fullOption = document.createElement("option");
      fullOption.value = "-1";
      fullOption.textContent = "Full clip";
      loopSelect.appendChild(fullOption);
      detectedLoops.forEach((loop, index) => {{
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = loop.label ?? `Loop ${{index + 1}}`;
        loopSelect.appendChild(option);
      }});
      loopSelect.value = String(selectedLoopIndex);
    }}

    function refreshActiveLoopLabel() {{
      activeLoopNode.textContent = currentLoop?.label ?? "Full clip";
    }}

    function setSelectedLoop(nextIndex) {{
      selectedLoopIndex = nextIndex;
      currentLoop = selectedLoopIndex >= 0 && selectedLoopIndex < detectedLoops.length
        ? detectedLoops[selectedLoopIndex]
        : null;
      currentAutoAlignment = currentLoop?.autoAlignment ?? defaultAutoAlignment;
      playbackState = buildPlaybackState(payload.frames, currentLoop);
      frameCursor = 0;
      playbackDirection = 1;
      refreshActiveLoopLabel();
      refreshSceneFrame();
    }}

    function resize() {{
      const width = viewport.clientWidth;
      const height = viewport.clientHeight;
      renderer.setPixelRatio(window.devicePixelRatio || 1);
      renderer.setSize(width, height, false);
      const aspect = width / Math.max(1, height);
      perspectiveCamera.aspect = aspect;
      perspectiveCamera.updateProjectionMatrix();
      const orthoSize = 240 / Math.max(120, zoom);
      orthographicCamera.left = -orthoSize * aspect;
      orthographicCamera.right = orthoSize * aspect;
      orthographicCamera.top = orthoSize;
      orthographicCamera.bottom = -orthoSize;
      orthographicCamera.updateProjectionMatrix();
      refreshSceneFrame();
      updateCamera();
    }}

    function getFrameTranslation(frame) {{
      if (!fixedRoot) {{
        return [0, 0, 0];
      }}
      const sourceIndexA = Number.isInteger(frame.sourceIndexA) ? frame.sourceIndexA : 0;
      const sourceIndexB = Number.isInteger(frame.sourceIndexB) ? frame.sourceIndexB : sourceIndexA;
      const blendAlpha = typeof frame.sourceAlpha === "number" ? frame.sourceAlpha : 0;
      const translationA = sourceIndexA >= 0 && sourceIndexA < translationTrack.length ? translationTrack[sourceIndexA] : null;
      const translationB = sourceIndexB >= 0 && sourceIndexB < translationTrack.length ? translationTrack[sourceIndexB] : translationA;
      const frameTranslation = translationA && translationB
        ? {{
            x: translationA.x * (1 - blendAlpha) + translationB.x * blendAlpha,
            z: translationA.z * (1 - blendAlpha) + translationB.z * blendAlpha,
          }}
        : {{ x: 0, z: 0 }};
      return [
        frameTranslation.x,
        frameTranslation.y,
        frameTranslation.z,
      ];
    }}

    function updateManualTransformState() {{
      manualRotation.set(
        THREE.MathUtils.degToRad(parseFloat(rotateXInput.value)),
        THREE.MathUtils.degToRad(parseFloat(rotateYInput.value)),
        THREE.MathUtils.degToRad(parseFloat(rotateZInput.value)),
        "XYZ"
      );
      manualTranslation.set(
        parseFloat(translateXInput.value),
        parseFloat(translateYInput.value),
        parseFloat(translateZInput.value)
      );
      worldRotationReadoutNode.textContent = `${{rotateXInput.value}}, ${{rotateYInput.value}}, ${{rotateZInput.value}}`;
      worldTranslationReadoutNode.textContent = `${{translateXInput.value}}, ${{translateYInput.value}}, ${{translateZInput.value}}`;
    }}

    function refreshSceneBasis() {{
      sceneRotationQuaternion.identity();
      const floorAlignment = Array.isArray(currentAutoAlignment) && currentAutoAlignment.length > 0
        ? currentAutoAlignment[0]
        : null;
      if (floorAlignment) {{
        const axis = floorAlignment?.axis;
        const angle = floorAlignment?.angle;
        if (Array.isArray(axis) && axis.length === 3 && typeof angle === "number") {{
          tempVector.set(axis[0], axis[1], axis[2]);
          if (tempVector.lengthSq() > 1e-8) {{
            tempVector.normalize();
            tempQuaternion.setFromAxisAngle(tempVector, angle);
            sceneRotationQuaternion.multiply(tempQuaternion);
          }}
        }}
      }}
      tempQuaternion.setFromEuler(manualRotation);
      sceneRotationQuaternion.multiply(tempQuaternion);
      sceneUp.copy(axisY).applyQuaternion(sceneRotationQuaternion).normalize();
      sceneRight.copy(axisX).applyQuaternion(sceneRotationQuaternion).normalize();
      sceneForward.copy(axisZ).applyQuaternion(sceneRotationQuaternion).normalize();
    }}

    function applyAutoAlignment(point) {{
      if (!autoWorldAlignmentEnabled || !Array.isArray(currentAutoAlignment) || currentAutoAlignment.length === 0) {{
        return point.clone();
      }}
      tempPivotedPoint.copy(point);
      for (const rotation of currentAutoAlignment) {{
        const axis = rotation?.axis;
        const angle = rotation?.angle;
        if (!Array.isArray(axis) || axis.length !== 3 || typeof angle !== "number") {{
          continue;
        }}
        tempVector.set(axis[0], axis[1], axis[2]);
        if (tempVector.lengthSq() <= 1e-8) {{
          continue;
        }}
        tempVector.normalize();
        tempQuaternion.setFromAxisAngle(tempVector, angle);
        tempPivotedPoint.applyQuaternion(tempQuaternion);
      }}
      return tempPivotedPoint.clone();
    }}

    function toBaseWorldPoint(point, frameTranslation) {{
      const tx = frameTranslation?.[0] ?? 0;
      const ty = frameTranslation?.[1] ?? 0;
      const tz = frameTranslation?.[2] ?? 0;
      return applyAutoAlignment(new THREE.Vector3(
        point[0] - tx,
        point[1] - ty,
        point[2] - tz
      ));
    }}

    function applyManualTransform(point) {{
      tempPivotedPoint.copy(point);
      tempPivotedPoint.sub(transformPivot);
      tempPivotedPoint.applyEuler(manualRotation);
      tempPivotedPoint.add(transformPivot);
      tempPivotedPoint.add(manualTranslation);
      return tempPivotedPoint.clone();
    }}

    function toWorldPoint(point, frameTranslation, currentFixedRoot = fixedRoot) {{
      refreshTransformPivot(currentFixedRoot);
      return applyManualTransform(toBaseWorldPoint(point, frameTranslation));
    }}

    function setOrientedEllipsoid(mesh, center, xAxis, yAxis, width, height, depth) {{
        if (!center || !xAxis || !yAxis) {{
          mesh.visible = false;
          return;
      }}
      const xDir = xAxis.clone().normalize();
      const yDir = yAxis.clone().normalize();
      const zDir = new THREE.Vector3().crossVectors(xDir, yDir);
      if (xDir.lengthSq() <= 1e-8 || yDir.lengthSq() <= 1e-8 || zDir.lengthSq() <= 1e-8) {{
        mesh.visible = false;
        return;
      }}
      zDir.normalize();
      yDir.copy(new THREE.Vector3().crossVectors(zDir, xDir)).normalize();
      tempMatrix.makeBasis(xDir, yDir, zDir);
      mesh.visible = true;
      mesh.position.copy(center);
      mesh.quaternion.setFromRotationMatrix(tempMatrix);
        mesh.scale.set(
          Math.max(0.001, width),
          Math.max(0.001, height),
          Math.max(0.001, depth)
        );
      }}

      function setOrientedCylinder(mesh, start, end, radius) {{
        if (!start || !end) {{
          mesh.visible = false;
          return;
        }}
        tempVector.subVectors(end, start);
        const length = tempVector.length();
        if (length <= 1e-6) {{
          mesh.visible = false;
          return;
        }}
        tempMidpoint.copy(start).add(end).multiplyScalar(0.5);
        mesh.visible = true;
        mesh.position.copy(tempMidpoint);
        tempQuaternion.setFromUnitVectors(axisY, tempVector.clone().normalize());
        mesh.quaternion.copy(tempQuaternion);
        mesh.scale.set(Math.max(0.001, radius), Math.max(0.001, length), Math.max(0.001, radius));
      }}

      function setOrientedFrameVolume(mesh, center, xAxis, yAxis, width, height, depth) {{
        if (!center || !xAxis || !yAxis) {{
          mesh.visible = false;
          return;
        }}
        const xDir = xAxis.clone().normalize();
        const yDir = yAxis.clone().normalize();
        const zDir = new THREE.Vector3().crossVectors(xDir, yDir);
        if (xDir.lengthSq() <= 1e-8 || yDir.lengthSq() <= 1e-8 || zDir.lengthSq() <= 1e-8) {{
          mesh.visible = false;
          return;
        }}
        zDir.normalize();
        yDir.copy(new THREE.Vector3().crossVectors(zDir, xDir)).normalize();
        tempMatrix.makeBasis(xDir, yDir, zDir);
        mesh.visible = true;
        mesh.position.copy(center);
        mesh.quaternion.setFromRotationMatrix(tempMatrix);
        mesh.scale.set(
          Math.max(0.001, width),
          Math.max(0.001, height),
          Math.max(0.001, depth)
        );
      }}

      function setOrientedBar(mesh, center, xAxis, yAxis, width, height, depth) {{
        if (!center || !xAxis || !yAxis) {{
          mesh.visible = false;
          return;
        }}
        const xDir = xAxis.clone().normalize();
        const yDir = yAxis.clone().normalize();
        const zDir = new THREE.Vector3().crossVectors(xDir, yDir);
        if (xDir.lengthSq() <= 1e-8 || yDir.lengthSq() <= 1e-8 || zDir.lengthSq() <= 1e-8) {{
          mesh.visible = false;
          return;
        }}
        zDir.normalize();
        yDir.copy(new THREE.Vector3().crossVectors(zDir, xDir)).normalize();
        tempMatrix.makeBasis(xDir, yDir, zDir);
        mesh.visible = true;
        mesh.position.copy(center);
        mesh.quaternion.setFromRotationMatrix(tempMatrix);
        mesh.scale.set(
          Math.max(0.001, width),
          Math.max(0.001, height),
          Math.max(0.001, depth)
        );
      }}

      function quaternionFromBodyAxes(xAxis, yAxis) {{
        const xDir = xAxis.clone().normalize();
        const yDir = yAxis.clone().normalize();
        const zDir = new THREE.Vector3().crossVectors(xDir, yDir);
        if (xDir.lengthSq() <= 1e-8 || yDir.lengthSq() <= 1e-8 || zDir.lengthSq() <= 1e-8) {{
          return null;
        }}
        zDir.normalize();
        yDir.copy(new THREE.Vector3().crossVectors(zDir, xDir)).normalize();
        tempMatrix.makeBasis(xDir, yDir, zDir);
        return new THREE.Quaternion().setFromRotationMatrix(tempMatrix);
      }}

      function hideProceduralBody() {{
        pelvisMesh.visible = false;
        abdomenMesh.visible = false;
        chestMesh.visible = false;
        upperChestMesh.visible = false;
        leftShoulderMassMesh.visible = false;
        rightShoulderMassMesh.visible = false;
        clavicleMesh.visible = false;
        headMesh.visible = false;
        for (const node of limbNodes) {{
          node.mesh.visible = false;
        }}
      }}

      function getFrameJointWorld(frame, frameTranslation, jointName) {{
        const point = frame.joints[jointName];
        return point ? toWorldPoint(point, frameTranslation, fixedRoot) : null;
      }}

      function findMannequinReferenceFrame() {{
        for (const frame of payload.frames) {{
          if (frame.joints.pelvis && frame.joints.neck && frame.joints.left_hip && frame.joints.right_hip) {{
            return frame;
          }}
        }}
        return payload.frames[0] ?? null;
      }}

      function initializeMannequinRig(gltf) {{
        mannequinRoot = gltf.scene;
        mannequinRoot.traverse((node) => {{
          if (node.name) {{
            mannequinBones.set(node.name, node);
          }}
          if (node.isSkinnedMesh) {{
            mannequinSkinnedMeshes.push(node);
            node.material = torsoMaterial.clone();
            node.material.flatShading = true;
            node.material.needsUpdate = true;
          }}
        }});
        if (mannequinBones.size === 0) {{
          return false;
        }}
        scene.add(mannequinRoot);
        mannequinRoot.updateMatrixWorld(true);
        const referenceFrame = findMannequinReferenceFrame();
        if (!referenceFrame) {{
          return false;
        }}
        const referenceTranslation = getFrameTranslation(referenceFrame);
        const pelvisRef = getFrameJointWorld(referenceFrame, referenceTranslation, "pelvis");
        const neckRef = getFrameJointWorld(referenceFrame, referenceTranslation, "neck");
        const leftHipRef = getFrameJointWorld(referenceFrame, referenceTranslation, "left_hip");
        const rightHipRef = getFrameJointWorld(referenceFrame, referenceTranslation, "right_hip");
        const mannequinPelvisBone = mannequinBones.get("root.x") ?? mannequinBones.get("spine_01.x") ?? mannequinBones.get("c_traj");
        const mannequinNeckBone = mannequinBones.get("neck.x");
        const mannequinLeftHipBone = mannequinBones.get("thigh_stretch.l");
        const mannequinRightHipBone = mannequinBones.get("thigh_stretch.r");
        if (!mannequinPelvisBone) {{
          return false;
        }}
        const restPelvis = new THREE.Vector3();
        const restNeck = new THREE.Vector3();
        const restLeftHip = new THREE.Vector3();
        const restRightHip = new THREE.Vector3();
        mannequinPelvisBone.getWorldPosition(restPelvis);
        let scaleCandidates = [];
        if (pelvisRef && neckRef && mannequinNeckBone) {{
          mannequinNeckBone.getWorldPosition(restNeck);
          const sourceHeight = pelvisRef.distanceTo(neckRef);
          const restHeight = restPelvis.distanceTo(restNeck);
          if (sourceHeight > 1e-6 && restHeight > 1e-6) {{
            scaleCandidates.push(sourceHeight / restHeight);
          }}
        }}
        if (leftHipRef && rightHipRef && mannequinLeftHipBone && mannequinRightHipBone) {{
          mannequinLeftHipBone.getWorldPosition(restLeftHip);
          mannequinRightHipBone.getWorldPosition(restRightHip);
          const sourceHipSpan = leftHipRef.distanceTo(rightHipRef);
          const restHipSpan = restLeftHip.distanceTo(restRightHip);
          if (sourceHipSpan > 1e-6 && restHipSpan > 1e-6) {{
            scaleCandidates.push(sourceHipSpan / restHipSpan);
          }}
        }}
        mannequinScale = scaleCandidates.length > 0
          ? scaleCandidates.reduce((sum, value) => sum + value, 0) / scaleCandidates.length
          : 1.0;
        mannequinRoot.scale.setScalar(mannequinScale);
        mannequinRoot.updateMatrixWorld(true);
        mannequinPelvisBone.getWorldPosition(restPelvis);
        mannequinBasePelvis = restPelvis.clone();
        mannequinBaseRoot = mannequinRoot.position.clone();
        for (const [boneName, pair] of Object.entries(MANNEQUIN_BONE_MAP)) {{
          const bone = mannequinBones.get(boneName);
          if (!bone) {{
            continue;
          }}
          const startWorld = new THREE.Vector3();
          bone.getWorldPosition(startWorld);
          let endWorld = null;
            if (bone.children && bone.children.length > 0) {{
              const childBone = bone.children.find((child) => child.name) ?? bone.children[0];
            endWorld = new THREE.Vector3();
            childBone.getWorldPosition(endWorld);
          }}
          if (!endWorld) {{
            const jointEnd = getFrameJointWorld(referenceFrame, referenceTranslation, pair[1]) ?? getFrameJointWorld(referenceFrame, referenceTranslation, pair[0]);
            if (!jointEnd) {{
              continue;
            }}
            endWorld = jointEnd.clone();
          }}
          const restDirection = endWorld.clone().sub(startWorld);
          if (restDirection.lengthSq() <= 1e-8) {{
            continue;
          }}
          const parentQuat = new THREE.Quaternion();
          if (bone.parent) {{
            bone.parent.getWorldQuaternion(parentQuat);
          }} else {{
            parentQuat.identity();
          }}
          const worldQuat = new THREE.Quaternion();
          bone.getWorldQuaternion(worldQuat);
          mannequinBoneStates.set(boneName, {{
            restDirection: restDirection.normalize(),
            restWorldQuaternion: worldQuat.clone(),
            parentWorldQuaternion: parentQuat.clone(),
          }});
        }}
        mannequinReady = true;
        return mannequinReady;
      }}

      async function tryLoadMannequin() {{
        if (!payload.mannequinAssetDataUri) {{
          mannequinFailed = true;
          return;
        }}
        try {{
          const loader = new GLTFLoader();
          const gltf = await loader.loadAsync(payload.mannequinAssetDataUri);
          if (initializeMannequinRig(gltf)) {{
            mannequinFailed = false;
            hideProceduralBody();
            draw();
          }} else {{
            mannequinFailed = true;
            console.warn("Mannequin rig initialization rejected the loaded asset");
          }}
        }} catch (error) {{
          mannequinFailed = true;
          console.warn("Failed to load mannequin asset", error);
        }}
      }}

      function updateMannequinForFrame(frame, frameTranslation) {{
        if (!mannequinReady || !mannequinRoot || !mannequinBasePelvis) {{
          return false;
        }}
        const pelvisWorld = getFrameJointWorld(frame, frameTranslation, "pelvis");
        if (!pelvisWorld) {{
          mannequinRoot.visible = false;
          return false;
        }}
        mannequinRoot.visible = true;
        mannequinRoot.position.copy(mannequinBaseRoot.clone().add(pelvisWorld.clone().sub(mannequinBasePelvis)));
        mannequinRoot.updateMatrixWorld(true);
        const leftHipWorld = getFrameJointWorld(frame, frameTranslation, "left_hip");
        const rightHipWorld = getFrameJointWorld(frame, frameTranslation, "right_hip");
        const spine1World = getFrameJointWorld(frame, frameTranslation, "spine1");
        const spine3World = getFrameJointWorld(frame, frameTranslation, "spine3");
        const neckWorld = getFrameJointWorld(frame, frameTranslation, "neck");
        for (const [boneName, pair] of Object.entries(MANNEQUIN_BONE_MAP)) {{
          const bone = mannequinBones.get(boneName);
          const state = mannequinBoneStates.get(boneName);
          if (!bone || !state) {{
            continue;
          }}
          if (boneName === "root.x" && leftHipWorld && rightHipWorld && spine1World) {{
            const hipAxis = rightHipWorld.clone().sub(leftHipWorld);
            const hipCenter = leftHipWorld.clone().add(rightHipWorld).multiplyScalar(0.5);
            const upAxis = spine1World.clone().sub(hipCenter);
            const desiredWorld = quaternionFromBodyAxes(hipAxis, upAxis);
            if (desiredWorld) {{
              const parentWorld = new THREE.Quaternion();
              if (bone.parent) {{
                bone.parent.getWorldQuaternion(parentWorld);
              }} else {{
                parentWorld.identity();
              }}
              bone.quaternion.copy(parentWorld.clone().invert().multiply(desiredWorld));
              bone.updateMatrixWorld(true);
            }}
            continue;
          }}
          if ((boneName === "spine_03.x" || boneName === "spine_02.x") && leftHipWorld && rightHipWorld && neckWorld && spine3World) {{
            const shoulderLeft = getFrameJointWorld(frame, frameTranslation, "left_shoulder");
            const shoulderRight = getFrameJointWorld(frame, frameTranslation, "right_shoulder");
            if (shoulderLeft && shoulderRight) {{
              const shoulderAxis = shoulderRight.clone().sub(shoulderLeft);
              const upAxis = neckWorld.clone().sub(spine3World);
              const desiredWorld = quaternionFromBodyAxes(shoulderAxis, upAxis);
              if (desiredWorld) {{
                const parentWorld = new THREE.Quaternion();
                if (bone.parent) {{
                  bone.parent.getWorldQuaternion(parentWorld);
                }} else {{
                  parentWorld.identity();
                }}
                bone.quaternion.copy(parentWorld.clone().invert().multiply(desiredWorld));
                bone.updateMatrixWorld(true);
              }}
              continue;
            }}
          }}
          const startWorld = getFrameJointWorld(frame, frameTranslation, pair[0]);
          const endWorld = getFrameJointWorld(frame, frameTranslation, pair[1]);
          if (!startWorld || !endWorld) {{
            continue;
          }}
          const targetDirection = endWorld.clone().sub(startWorld);
          if (targetDirection.lengthSq() <= 1e-8) {{
            continue;
          }}
          targetDirection.normalize();
          const delta = new THREE.Quaternion().setFromUnitVectors(state.restDirection, targetDirection);
          const desiredWorld = delta.multiply(state.restWorldQuaternion.clone());
          const parentWorld = new THREE.Quaternion();
          if (bone.parent) {{
            bone.parent.getWorldQuaternion(parentWorld);
          }} else {{
            parentWorld.identity();
          }}
          const localQuat = parentWorld.clone().invert().multiply(desiredWorld);
          bone.quaternion.copy(localQuat);
          bone.updateMatrixWorld(true);
        }}
        mannequinRoot.updateMatrixWorld(true);
        return true;
      }}

    function updateCamera() {{
      const distance = 1200 / Math.max(120, zoom);
      const horizontalDistance = Math.cos(pitch) * distance;
      refreshSceneBasis();
      activeCamera = cameraMode === "orthographic" ? orthographicCamera : perspectiveCamera;
      activeCamera.position.copy(cameraTarget)
        .addScaledVector(sceneRight, Math.sin(yaw) * horizontalDistance)
        .addScaledVector(sceneForward, Math.cos(yaw) * horizontalDistance)
        .addScaledVector(sceneUp, Math.sin(pitch) * distance);
      activeCamera.up.copy(sceneUp);
      if (cameraMode === "orthographic") {{
        const aspect = viewport.clientWidth / Math.max(1, viewport.clientHeight);
        const orthoSize = 240 / Math.max(120, zoom);
        orthographicCamera.left = -orthoSize * aspect;
        orthographicCamera.right = orthoSize * aspect;
        orthographicCamera.top = orthoSize;
        orthographicCamera.bottom = -orthoSize;
        orthographicCamera.updateProjectionMatrix();
      }}
      activeCamera.lookAt(cameraTarget);
    }}

    function getInterpolatedFrame() {{
      const frames = playbackState.frames;
      if (frames.length === 0) {{
        return null;
      }}
      const baseIndex = Math.max(0, Math.min(frames.length - 1, Math.floor(frameCursor)));
      const nextIndex = playbackState.loopable
        ? (baseIndex + 1) % frames.length
        : Math.max(0, Math.min(frames.length - 1, baseIndex + 1));
      const alpha = frameCursor - Math.floor(frameCursor);
      const current = frames[baseIndex];
      const next = frames[nextIndex];
      if (!next || alpha <= 1e-6) {{
        return current;
      }}
      const joints = {{}};
      for (const jointName of payload.jointNames) {{
        const start = current.joints[jointName];
        const end = next.joints[jointName];
        if (!start && !end) {{
          continue;
        }}
        if (!start) {{
          joints[jointName] = end;
          continue;
        }}
        if (!end) {{
          joints[jointName] = start;
          continue;
        }}
        joints[jointName] = [
          start[0] * (1 - alpha) + end[0] * alpha,
          start[1] * (1 - alpha) + end[1] * alpha,
          start[2] * (1 - alpha) + end[2] * alpha,
        ];
      }}
      return {{
        frameIndex: current.frameIndex ?? baseIndex,
        sourceIndexA: current.frameIndex ?? baseIndex,
        sourceIndexB: next.frameIndex ?? nextIndex,
        sourceAlpha: alpha,
        timeSec: current.timeSec * (1 - alpha) + next.timeSec * alpha,
        joints,
      }};
    }}

      function updateSceneForFrame(frame) {{
        const frameTranslation = getFrameTranslation(frame);
        if (mannequinReady) {{
          hideProceduralBody();
          updateMannequinForFrame(frame, frameTranslation);
          return;
        }}
        if (payload.mannequinAssetDataUri && !mannequinFailed) {{
          hideProceduralBody();
          return;
        }}
        const pelvisJoint = frame.joints.pelvis ? toWorldPoint(frame.joints.pelvis, frameTranslation, fixedRoot) : null;
      const spine1Joint = frame.joints.spine1 ? toWorldPoint(frame.joints.spine1, frameTranslation, fixedRoot) : null;
      const spine2Joint = frame.joints.spine2 ? toWorldPoint(frame.joints.spine2, frameTranslation, fixedRoot) : null;
      const spine3Joint = frame.joints.spine3 ? toWorldPoint(frame.joints.spine3, frameTranslation, fixedRoot) : null;
      const neckJoint = frame.joints.neck ? toWorldPoint(frame.joints.neck, frameTranslation, fixedRoot) : null;
      const leftHipJoint = frame.joints.left_hip ? toWorldPoint(frame.joints.left_hip, frameTranslation, fixedRoot) : null;
      const rightHipJoint = frame.joints.right_hip ? toWorldPoint(frame.joints.right_hip, frameTranslation, fixedRoot) : null;
      const leftShoulderJoint = frame.joints.left_shoulder ? toWorldPoint(frame.joints.left_shoulder, frameTranslation, fixedRoot) : null;
      const rightShoulderJoint = frame.joints.right_shoulder ? toWorldPoint(frame.joints.right_shoulder, frameTranslation, fixedRoot) : null;

      if (pelvisJoint && leftHipJoint && rightHipJoint && spine1Joint) {{
        const hipCenter = leftHipJoint.clone().add(rightHipJoint).multiplyScalar(0.5);
          const pelvisCenter = hipCenter.clone().lerp(pelvisJoint, 0.44);
          const hipAxis = rightHipJoint.clone().sub(leftHipJoint);
          const pelvisHeight = Math.max(0.105, pelvisJoint.distanceTo(hipCenter) * 1.48);
          const pelvisWidth = Math.max(0.16, hipAxis.length() * 1.08);
            setOrientedFrameVolume(
              pelvisMesh,
              pelvisCenter,
              hipAxis,
              spine1Joint.clone().sub(hipCenter),
              pelvisWidth,
              pelvisHeight,
              pelvisWidth * 0.76
            );
        }} else {{
          pelvisMesh.visible = false;
        }}

          if (spine1Joint && spine2Joint && leftShoulderJoint && rightShoulderJoint) {{
            const shoulderAxis = rightShoulderJoint.clone().sub(leftShoulderJoint);
            const abdomenRadius = Math.max(0.06, shoulderAxis.length() * 0.1);
          setOrientedCylinder(
            abdomenMesh,
            spine1Joint,
            spine2Joint.clone().lerp(spine1Joint, 0.12),
            abdomenRadius
          );
        }} else {{
          abdomenMesh.visible = false;
        }}
  
          if (spine2Joint && neckJoint && leftShoulderJoint && rightShoulderJoint) {{
            const shoulderCenter = leftShoulderJoint.clone().add(rightShoulderJoint).multiplyScalar(0.5);
            const chestCenter = shoulderCenter.clone().lerp(spine2Joint, 0.52);
            const shoulderAxis = rightShoulderJoint.clone().sub(leftShoulderJoint);
            const chestAxis = neckJoint.clone().sub(spine2Joint);
            const shoulderSpan = shoulderAxis.length();
            const chestWidth = Math.max(0.16, shoulderSpan * 0.62);
            const chestHeight = Math.max(0.17, chestAxis.length() * 1.04);
            const chestDepth = Math.max(0.1, chestWidth * 0.48);
          setOrientedFrameVolume(
            chestMesh,
            chestCenter,
            shoulderAxis,
            chestAxis,
            chestWidth,
            chestHeight,
            chestDepth
          );
          setOrientedCylinder(
            upperChestMesh,
            spine3Joint ? spine3Joint.clone().lerp(neckJoint, 0.35) : chestCenter.clone().lerp(neckJoint, 0.55),
            neckJoint,
              Math.max(0.04, chestWidth * 0.09)
            );
            setOrientedBar(
              clavicleMesh,
              shoulderCenter.clone().lerp(neckJoint, 0.08),
              shoulderAxis,
              chestAxis,
              Math.max(0.15, shoulderSpan * 0.72),
              Math.max(0.03, chestHeight * 0.09),
              Math.max(0.06, chestDepth * 0.38)
            );
            setOrientedEllipsoid(
              leftShoulderMassMesh,
              leftShoulderJoint.clone().lerp(neckJoint, 0.08),
              shoulderAxis,
              chestAxis,
              Math.max(0.075, shoulderSpan * 0.14),
              Math.max(0.07, chestHeight * 0.24),
              Math.max(0.07, chestDepth * 0.78)
            );
            setOrientedEllipsoid(
              rightShoulderMassMesh,
              rightShoulderJoint.clone().lerp(neckJoint, 0.08),
              shoulderAxis,
              chestAxis,
              Math.max(0.075, shoulderSpan * 0.14),
              Math.max(0.07, chestHeight * 0.24),
              Math.max(0.07, chestDepth * 0.78)
            );
          }} else {{
            chestMesh.visible = false;
            upperChestMesh.visible = false;
            leftShoulderMassMesh.visible = false;
            rightShoulderMassMesh.visible = false;
            clavicleMesh.visible = false;
          }}

      for (const node of limbNodes) {{
          const start = frame.joints[node.capsule.start];
          const end = frame.joints[node.capsule.end];
          if (!start || !end) {{
          node.mesh.visible = false;
            continue;
          }}
          const startVector = toWorldPoint(start, frameTranslation, fixedRoot);
          const endVector = toWorldPoint(end, frameTranslation, fixedRoot);
          tempVector.subVectors(endVector, startVector);
          const fullLength = tempVector.length();
          const direction = tempVector.clone().normalize();
          if (fullLength < 1e-4) {{
          node.mesh.visible = false;
            continue;
          }}
          const radius = node.capsule.radius;
        const jointInset = Math.min(radius * 0.35, fullLength * 0.08);
        const startInset = startVector.clone().addScaledVector(direction, jointInset);
        const endInset = endVector.clone().addScaledVector(direction, -jointInset);
          tempVector.subVectors(endInset, startInset);
          const length = tempVector.length();
          if (length < 1e-4) {{
          node.mesh.visible = false;
            continue;
          }}
        node.mesh.visible = true;
          tempMidpoint.addVectors(startInset, endInset).multiplyScalar(0.5);
        node.mesh.position.copy(tempMidpoint);
          tempQuaternion.setFromUnitVectors(axisY, tempVector.clone().normalize());
        node.mesh.quaternion.copy(tempQuaternion);
        node.mesh.scale.set(radius, length, radius);
        }}

      const headJoint = frame.joints.head ?? frame.joints.neck ?? null;
      if (headJoint) {{
        headMesh.visible = true;
        headMesh.position.copy(toWorldPoint(headJoint, frameTranslation, fixedRoot));
        const neckSourceJoint = frame.joints.neck ?? null;
          const headScale = neckSourceJoint
            ? Math.max(0.086, Math.min(0.116, toWorldPoint(headJoint, frameTranslation, fixedRoot).distanceTo(toWorldPoint(neckSourceJoint, frameTranslation, fixedRoot)) * 0.46))
            : 0.108;
          headMesh.scale.set(headScale * 0.88, headScale * 1.08, headScale * 0.86);
      }} else {{
        headMesh.visible = false;
      }}
    }}

    function draw() {{
      const frame = getInterpolatedFrame();
      if (!frame) {{
        return;
      }}
      updateCamera();
      updateSceneForFrame(frame);
      frameIndexNode.textContent = String(Math.max(0, Math.min(playbackState.frames.length - 1, Math.floor(frameCursor))));
      renderer.render(scene, activeCamera);
    }}

    function animate(timestamp) {{
      if (lastTimestamp == null) {{
        lastTimestamp = timestamp;
      }}
      const deltaSeconds = Math.max(0, (timestamp - lastTimestamp) / 1000);
      lastTimestamp = timestamp;
      if (!paused) {{
        if (playbackState.loopable) {{
          frameCursor += deltaSeconds * payload.fps * speed;
          if (playbackState.frames.length > 0) {{
            frameCursor %= playbackState.frames.length;
          }}
        }} else {{
          frameCursor += deltaSeconds * payload.fps * speed * playbackDirection;
          const maxCursor = Math.max(0, playbackState.frames.length - 1);
          if (frameCursor >= maxCursor) {{
            frameCursor = maxCursor;
            playbackDirection = -1;
          }} else if (frameCursor <= 0) {{
            frameCursor = 0;
            playbackDirection = 1;
          }}
        }}
      }}
      draw();
      requestAnimationFrame(animate);
    }}

    renderer.domElement.addEventListener("pointerdown", (event) => {{
      dragging = true;
      dragX = event.clientX;
      dragY = event.clientY;
      renderer.domElement.setPointerCapture(event.pointerId);
    }});
    renderer.domElement.addEventListener("pointermove", (event) => {{
      if (!dragging) {{
        return;
      }}
      const deltaX = event.clientX - dragX;
      const deltaY = event.clientY - dragY;
      dragX = event.clientX;
      dragY = event.clientY;
      yaw -= deltaX * 0.01;
      pitch = Math.max(-1.2, Math.min(1.2, pitch - deltaY * 0.01));
      pitchInput.value = String(pitch);
    }});
    renderer.domElement.addEventListener("pointerup", () => {{
      dragging = false;
    }});
    speedInput.addEventListener("input", () => {{
      speed = parseFloat(speedInput.value);
    }});
    function refreshPauseLabel() {{
      pauseToggleButton.textContent = paused ? "Resume" : "Pause";
    }}
    pauseToggleButton.addEventListener("click", () => {{
      paused = !paused;
      refreshPauseLabel();
    }});
    fixedRootInput.addEventListener("change", () => {{
      fixedRoot = fixedRootInput.checked;
      refreshSceneFrame();
    }});
    autoWorldAlignmentInput.addEventListener("change", () => {{
      autoWorldAlignmentEnabled = autoWorldAlignmentInput.checked;
      refreshSceneFrame();
    }});
    loopSelect.addEventListener("change", () => {{
      setSelectedLoop(parseInt(loopSelect.value, 10));
    }});
    zoomInput.addEventListener("input", () => {{
      zoom = parseFloat(zoomInput.value);
      resize();
    }});
    cameraModeSelect.addEventListener("change", () => {{
      cameraMode = cameraModeSelect.value;
      updateCamera();
      draw();
    }});
    pitchInput.addEventListener("input", () => {{
      pitch = parseFloat(pitchInput.value);
    }});
    function refreshManualTransform() {{
      updateManualTransformState();
      scheduleSceneReframe();
    }}
    [rotateXInput, rotateYInput, rotateZInput, translateXInput, translateYInput, translateZInput].forEach((input) => {{
      input.addEventListener("input", refreshManualTransform);
      input.addEventListener("change", refreshSceneFrame);
    }});
    resetTransformButton.addEventListener("click", () => {{
      rotateXInput.value = "0";
      rotateYInput.value = "0";
      rotateZInput.value = "0";
      translateXInput.value = "0";
      translateYInput.value = "0";
      translateZInput.value = "0";
      refreshManualTransform();
    }});
    window.addEventListener("keydown", (event) => {{
      if (event.code !== "Space") {{
        return;
      }}
      const tagName = document.activeElement?.tagName ?? "";
      if (tagName === "INPUT" || tagName === "SELECT" || tagName === "BUTTON") {{
        return;
      }}
      event.preventDefault();
      paused = !paused;
      refreshPauseLabel();
    }});
    window.addEventListener("resize", resize);
    updateManualTransformState();
    refreshPauseLabel();
      refreshSceneFrame();
      resize();
      draw();
      tryLoadMannequin();
      requestAnimationFrame(animate);
    </script>
</body>
</html>
"""
