from __future__ import annotations

import json
import math

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
PREVIEW_SKELETON_CHAINS = [
    ["left_foot", "left_ankle", "left_knee", "left_hip", "pelvis", "right_hip", "right_knee", "right_ankle", "right_foot"],
    ["pelvis", "spine1", "spine2", "spine3", "neck", "head"],
    ["neck", "left_collar", "left_shoulder", "left_elbow", "left_wrist", "left_hand"],
    ["neck", "right_collar", "right_shoulder", "right_elbow", "right_wrist", "right_hand"],
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
ORIENTATION_PRIMARY_SUPPORT_JOINTS = (
    "left_foot",
    "right_foot",
    "left_hand",
    "right_hand",
)
ORIENTATION_FALLBACK_SUPPORT_JOINTS = (
    "left_ankle",
    "right_ankle",
    "left_wrist",
    "right_wrist",
)
YAW_ALIGNMENT_PAIRS = (
    ("left_foot", "right_foot"),
    ("left_ankle", "right_ankle"),
    ("left_hand", "right_hand"),
    ("left_wrist", "right_wrist"),
)


def write_preview_html(
    path: Path,
    clip: MotionClip,
    *,
    title: str,
    debug_json_path: Path | None = None,
    smpl_mesh_payload: dict[str, object] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    preview_clip = _center_preview_clip_for_render(refine_motion_clip_for_preview(clip))
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
        "defaultFixedRoot": True,
        "rootTranslationToggleLabel": (
            "Show original camera-space translation"
            if preview_clip.metadata.get("upstream") == "gvhmr"
            else "Lock global root drift"
        ) if isinstance(preview_clip.metadata, dict) else "Lock global root drift",
        "defaultSceneInverted": False,
        "defaultAutoWorldAlignment": True,
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
        "smplMesh": smpl_mesh_payload,
    }
    html = _build_html(payload)
    path.write_text(html, encoding="utf-8")


def write_preview_debug_json(path: Path, clip: MotionClip) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fixed_root = bool(clip.metadata.get("upstream") == "gvhmr") if isinstance(clip.metadata, dict) else False
    translation_track = _build_preview_translation_track(clip.frames, _find_root_joint(clip))
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


def write_wear_skeleton_json(
    path: Path,
    clip: MotionClip,
    *,
    title: str,
    selected_loop_index: int | None = None,
    lock_y_drift: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_wear_skeleton_payload(
        clip,
        title=title,
        selected_loop_index=selected_loop_index,
        lock_y_drift=lock_y_drift,
    )
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_wear_skeleton_payload(
    clip: MotionClip,
    *,
    title: str,
    selected_loop_index: int | None = None,
    lock_y_drift: bool = False,
) -> dict[str, object]:
    preview_clip = _center_preview_clip_for_render(refine_motion_clip_for_preview(clip))
    detected_loops = _detect_preview_loops(preview_clip)
    resolved_loop_index = (
        0
        if selected_loop_index is None and detected_loops
        else -1
        if selected_loop_index is None
        else selected_loop_index
    )
    if resolved_loop_index < -1 or resolved_loop_index >= len(detected_loops):
        raise ValueError(
            f"selected_loop_index must be -1 or between 0 and {len(detected_loops) - 1}; got {resolved_loop_index}"
        )
    selected_loop = detected_loops[resolved_loop_index] if resolved_loop_index >= 0 else None
    active_start_frame = int(selected_loop["startFrame"]) if selected_loop is not None else 0
    active_end_frame = int(selected_loop["endFrame"]) if selected_loop is not None else max(0, preview_clip.frame_count - 1)
    active_frames = preview_clip.frames[active_start_frame:active_end_frame + 1]
    auto_alignment = _compute_preview_auto_alignment(active_frames)
    root_joint = _find_root_joint(preview_clip)
    active_root_anchor = _compute_root_anchor(active_frames, root_joint)
    transformed_frames = _build_wear_transformed_frames(
        active_frames=active_frames,
        source_start_frame=active_start_frame,
        root_joint=root_joint,
        active_root_anchor=active_root_anchor,
        auto_alignment=auto_alignment,
        lock_y_drift=lock_y_drift,
    )
    bounds = _compute_transformed_joint_bounds(transformed_frames)
    scene_origin = _bounds_center(bounds)
    centered_frames = _subtract_scene_origin_from_frames(transformed_frames, scene_origin)
    centered_bounds = _compute_transformed_joint_bounds(centered_frames)
    active_duration = (
        active_frames[-1].time_sec - active_frames[0].time_sec
        if len(active_frames) >= 2
        else 0.0
    )

    return {
        "schemaVersion": 1,
        "kind": "wearPreviewSkeleton",
        "title": title,
        "source": {
            "fps": preview_clip.fps,
            "frameCount": preview_clip.frame_count,
            "activeStartFrame": active_start_frame,
            "activeEndFrame": active_end_frame,
        },
        "fps": preview_clip.fps,
        "frameCount": len(centered_frames),
        "durationSec": active_duration,
        "jointNames": preview_clip.joint_names,
        "rootJoint": root_joint,
        "bakedPreviewConfiguration": {
            "autoWorldAlignment": True,
            "lockGlobalRootDrift": True,
            "lockYDrift": lock_y_drift,
            "invertScene": False,
            "selectedLoopIndex": resolved_loop_index,
        },
        "loop": {
            "enabled": selected_loop is not None,
            "startFrame": 0,
            "endFrame": max(0, len(centered_frames) - 1),
            "sourceStartFrame": active_start_frame,
            "sourceEndFrame": active_end_frame,
            "durationSec": active_duration,
            "label": selected_loop.get("label") if selected_loop is not None else "Full clip",
        },
        "transforms": {
            "autoAlignment": _serialize_preview_rotations(auto_alignment),
            "rootAnchor": _point_to_list(active_root_anchor) if active_root_anchor is not None else None,
            "sceneOriginOffset": _point_to_list(scene_origin),
        },
        "bounds": _serialize_bounds(centered_bounds),
        "topology": {
            "skeletonChains": PREVIEW_SKELETON_CHAINS,
            "capsules": _build_capsules(preview_clip),
        },
        "geometry": {
            "style": "low_poly_block_humanoid",
            "limb": {
                "legWidth": 0.105,
                "legDepth": 0.075,
                "armWidth": 0.086,
                "armDepth": 0.061,
            },
            "chainProfiles": [
                {"match": "leg_bridge", "minJointCount": 8, "width": 0.14, "depth": 0.09},
                {"match": "spine_head", "includesJoint": "head", "width": 0.1, "depth": 0.08},
                {"match": "default", "width": 0.08, "depth": 0.055},
            ],
            "head": {
                "minScale": 0.086,
                "maxScale": 0.116,
                "scale": [0.88, 1.08, 0.86],
            },
        },
        "frames": centered_frames,
    }


def detect_preview_loops_for_clip(clip: MotionClip) -> list[dict[str, object]]:
    preview_clip = _center_preview_clip_for_render(refine_motion_clip_for_preview(clip))
    return [
        {
            **loop,
            "autoAlignment": _serialize_preview_rotations(
                _compute_preview_auto_alignment(preview_clip.frames[loop["startFrame"]: loop["endFrame"] + 1])
            ),
        }
        for loop in _detect_preview_loops(preview_clip)
    ]


def _build_wear_transformed_frames(
    *,
    active_frames: list[MotionFrame],
    source_start_frame: int,
    root_joint: str | None,
    active_root_anchor: tuple[float, float, float] | None,
    auto_alignment: list[tuple[tuple[float, float, float], float]],
    lock_y_drift: bool,
) -> list[dict[str, object]]:
    if not active_frames:
        return []
    active_start_time = active_frames[0].time_sec
    transformed_frames: list[dict[str, object]] = []
    for index, frame in enumerate(active_frames):
        translation = _fixed_root_translation(frame, root_joint, active_root_anchor, lock_y_drift=lock_y_drift)
        transformed_joints = {}
        for joint_name, point in frame.joints.items():
            translated = (
                point[0] - translation[0],
                point[1] - translation[1],
                point[2] - translation[2],
            )
            transformed = _apply_rotations_to_point(translated, auto_alignment)
            transformed_joints[joint_name] = _point_to_list(transformed)
        transformed_frames.append(
            {
                "frameIndex": index,
                "sourceFrameIndex": source_start_frame + index,
                "timeSec": frame.time_sec - active_start_time,
                "sourceTimeSec": frame.time_sec,
                "rootTranslationApplied": _point_to_list(translation),
                "joints": transformed_joints,
            }
        )
    return transformed_frames


def _compute_root_anchor(
    frames: list[MotionFrame],
    root_joint: str | None,
) -> tuple[float, float, float] | None:
    root_points = [
        root_point
        for root_point in (_frame_root_point(frame, root_joint) for frame in frames)
        if root_point is not None
    ]
    if not root_points:
        return None
    return (
        sum(point[0] for point in root_points) / len(root_points),
        sum(point[1] for point in root_points) / len(root_points),
        sum(point[2] for point in root_points) / len(root_points),
    )


def _fixed_root_translation(
    frame: MotionFrame,
    root_joint: str | None,
    active_root_anchor: tuple[float, float, float] | None,
    *,
    lock_y_drift: bool,
) -> tuple[float, float, float]:
    if active_root_anchor is None:
        return (0.0, 0.0, 0.0)
    root_point = _frame_root_point(frame, root_joint)
    if root_point is None:
        return (0.0, 0.0, 0.0)
    return (
        root_point[0] - active_root_anchor[0],
        root_point[1] - active_root_anchor[1] if lock_y_drift else 0.0,
        root_point[2] - active_root_anchor[2],
    )


def _compute_transformed_joint_bounds(frames: list[dict[str, object]]) -> dict[str, float]:
    min_x = math.inf
    min_y = math.inf
    min_z = math.inf
    max_x = -math.inf
    max_y = -math.inf
    max_z = -math.inf
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        for point in joints.values():
            if not _is_serialized_point(point):
                continue
            x, y, z = float(point[0]), float(point[1]), float(point[2])
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            min_z = min(min_z, z)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            max_z = max(max_z, z)
    if not all(math.isfinite(value) for value in (min_x, min_y, min_z, max_x, max_y, max_z)):
        return {
            "minX": -0.5,
            "maxX": 0.5,
            "minY": -0.5,
            "maxY": 0.5,
            "minZ": -0.5,
            "maxZ": 0.5,
        }
    return {
        "minX": min_x,
        "maxX": max_x,
        "minY": min_y,
        "maxY": max_y,
        "minZ": min_z,
        "maxZ": max_z,
    }


def _bounds_center(bounds: dict[str, float]) -> tuple[float, float, float]:
    return (
        (bounds["minX"] + bounds["maxX"]) * 0.5,
        (bounds["minY"] + bounds["maxY"]) * 0.5,
        (bounds["minZ"] + bounds["maxZ"]) * 0.5,
    )


def _subtract_scene_origin_from_frames(
    frames: list[dict[str, object]],
    scene_origin: tuple[float, float, float],
) -> list[dict[str, object]]:
    centered_frames: list[dict[str, object]] = []
    for frame in frames:
        joints = frame.get("joints")
        centered_joints = {}
        if isinstance(joints, dict):
            centered_joints = {
                joint_name: [
                    float(point[0]) - scene_origin[0],
                    float(point[1]) - scene_origin[1],
                    float(point[2]) - scene_origin[2],
                ]
                for joint_name, point in joints.items()
                if _is_serialized_point(point)
            }
        centered_frame = dict(frame)
        centered_frame["joints"] = centered_joints
        centered_frames.append(centered_frame)
    return centered_frames


def _serialize_bounds(bounds: dict[str, float]) -> dict[str, object]:
    return {
        **{key: float(value) for key, value in bounds.items()},
        "center": _point_to_list(_bounds_center(bounds)),
        "size": [
            float(bounds["maxX"] - bounds["minX"]),
            float(bounds["maxY"] - bounds["minY"]),
            float(bounds["maxZ"] - bounds["minZ"]),
        ],
    }


def _point_to_list(point: tuple[float, float, float]) -> list[float]:
    return [float(point[0]), float(point[1]), float(point[2])]


def _is_serialized_point(value: object) -> bool:
    return isinstance(value, (list, tuple)) and len(value) >= 3


def refine_motion_clip_for_preview(clip: MotionClip) -> MotionClip:
    if _clip_is_preview_refined(clip):
        return clip
    return _apply_preview_refinement(clip)


def _prepare_preview_clip(clip: MotionClip) -> MotionClip:
    return refine_motion_clip_for_preview(clip)


def _center_preview_clip_for_render(clip: MotionClip) -> MotionClip:
    if not clip.frames:
        return clip

    root_joint = _find_root_joint(clip)
    translation_track = _build_preview_translation_track(clip.frames, root_joint)
    min_x = math.inf
    min_y = math.inf
    min_z = math.inf
    max_x = -math.inf
    max_y = -math.inf
    max_z = -math.inf
    for frame_index, frame in enumerate(clip.frames):
        translation = translation_track[frame_index] if frame_index < len(translation_track) else (0.0, 0.0, 0.0)
        for point in frame.joints.values():
            x = point[0] - translation[0]
            y = point[1] - translation[1]
            z = point[2] - translation[2]
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            min_z = min(min_z, z)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            max_z = max(max_z, z)

    if not all(math.isfinite(value) for value in (min_x, min_y, min_z, max_x, max_y, max_z)):
        return clip

    center = (
        (min_x + max_x) * 0.5,
        (min_y + max_y) * 0.5,
        (min_z + max_z) * 0.5,
    )
    centered_frames = [
        MotionFrame(
            time_sec=frame.time_sec,
            joints={
                joint_name: (
                    point[0] - center[0],
                    point[1] - center[1],
                    point[2] - center[2],
                )
                for joint_name, point in frame.joints.items()
            },
        )
        for frame in clip.frames
    ]
    metadata = dict(clip.metadata)
    metadata["previewCenterOffset"] = {
        "space": "fixed_root_motion_bounds",
        "point": list(center),
    }
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=centered_frames,
        source=clip.source,
        metadata=metadata,
    )


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


def _frame_root_point(frame: MotionFrame, preferred_root_joint: str | None) -> tuple[float, float, float] | None:
    for candidate in (preferred_root_joint, "pelvis", "spine1"):
        if candidate is None:
            continue
        point = frame.joints.get(candidate)
        if point is not None:
            return point
    return None


def _build_preview_translation_track(
    frames: list[MotionFrame],
    preferred_root_joint: str | None = None,
) -> list[tuple[float, float, float]]:
    if not frames:
        return []
    base_root_point = _frame_root_point(frames[0], preferred_root_joint)
    if base_root_point is None:
        return [(0.0, 0.0, 0.0) for _ in frames]
    translations: list[tuple[float, float, float]] = []
    for frame in frames:
        root_point = _frame_root_point(frame, preferred_root_joint)
        if root_point is None:
            translations.append((0.0, 0.0, 0.0))
            continue
        translations.append((
            root_point[0] - base_root_point[0],
            0.0,
            root_point[2] - base_root_point[2],
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
    averaged = _fit_support_plane_normal(support_points)
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
    primary_points: list[tuple[float, float, float]] = []
    fallback_points: list[tuple[float, float, float]] = []
    for frame in frames:
        primary_points.extend(
            frame.joints[joint_name]
            for joint_name in ORIENTATION_PRIMARY_SUPPORT_JOINTS
            if joint_name in frame.joints
        )
        fallback_points.extend(
            frame.joints[joint_name]
            for joint_name in ORIENTATION_FALLBACK_SUPPORT_JOINTS
            if joint_name in frame.joints
        )
    combined_points = primary_points + fallback_points
    if len(primary_points) >= 6 and _support_points_have_plane_span(primary_points):
        return primary_points
    if len(combined_points) >= 6 and _support_points_have_plane_span(combined_points):
        return combined_points
    return primary_points if len(primary_points) >= 6 else fallback_points


def _support_points_have_plane_span(points: list[tuple[float, float, float]]) -> bool:
    if len(points) < 3:
        return False
    span_x = max(point[0] for point in points) - min(point[0] for point in points)
    span_z = max(point[2] for point in points) - min(point[2] for point in points)
    return span_x >= 0.08 and span_z >= 0.08


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
    return ((0.0, 1.0, 0.0), angle)


def _compute_preview_auto_alignment(
    frames: list[MotionFrame],
) -> list[tuple[tuple[float, float, float], float]]:
    if not frames:
        return []
    rotations: list[tuple[tuple[float, float, float], float]] = []
    aligned_frames = frames
    spine_rotation = _estimate_upright_spine_alignment_rotation(aligned_frames)
    if spine_rotation is not None:
        rotations.append(spine_rotation)
        aligned_frames = [_rotate_frame(frame, spine_rotation) for frame in aligned_frames]
    support_plane_rotation = _estimate_support_plane_alignment_rotation(aligned_frames)
    if support_plane_rotation is not None and _rotation_preserves_upright_spine(aligned_frames, support_plane_rotation):
        rotations.append(support_plane_rotation)
        aligned_frames = [_rotate_frame(frame, support_plane_rotation) for frame in aligned_frames]
    support_profile_rotation = _estimate_support_profile_yaw_rotation(aligned_frames)
    if support_profile_rotation is not None:
        rotations.append(support_profile_rotation)
    return rotations


def _rotation_preserves_upright_spine(
    frames: list[MotionFrame],
    rotation: tuple[tuple[float, float, float], float],
) -> bool:
    upright_vectors = _collect_upright_spine_vectors(frames)
    if len(upright_vectors) < 3:
        return True
    axis, angle = rotation
    rotated_vectors = [
        _rotate_point(vector, axis=axis, angle=angle)
        for vector in upright_vectors
    ]
    average_verticality = sum(vector[1] for vector in rotated_vectors) / len(rotated_vectors)
    return average_verticality >= math.cos(math.radians(8.0))


def _estimate_upright_spine_alignment_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    upright_vectors = _collect_upright_spine_vectors(frames)
    if len(upright_vectors) < 3:
        return None
    averaged = _normalize((
        sum(vector[0] for vector in upright_vectors) / len(upright_vectors),
        sum(vector[1] for vector in upright_vectors) / len(upright_vectors),
        sum(vector[2] for vector in upright_vectors) / len(upright_vectors),
    ))
    if _vector_length(averaged) <= 1e-6:
        return None
    return _rotation_between_vectors(averaged, (0.0, 1.0, 0.0), minimum_degrees=2.0)


def _collect_upright_spine_vectors(frames: list[MotionFrame]) -> list[tuple[float, float, float]]:
    candidates: list[tuple[float, tuple[float, float, float]]] = []
    for frame in frames:
        pelvis = frame.joints.get("pelvis")
        spine_top = frame.joints.get("neck") or frame.joints.get("head") or frame.joints.get("spine3")
        if pelvis is None or spine_top is None:
            continue
        spine_vector = _subtract_points(spine_top, pelvis)
        spine_length = _vector_length(spine_vector)
        if spine_length <= 1e-5:
            continue
        normalized = (
            spine_vector[0] / spine_length,
            spine_vector[1] / spine_length,
            spine_vector[2] / spine_length,
        )
        verticality = abs(normalized[1])
        if verticality < 0.65:
            continue
        candidates.append((verticality, normalized))
    if not candidates:
        return []
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    keep_count = min(len(candidates), max(3, int(math.ceil(len(candidates) * 0.20))))
    return [vector for _, vector in candidates[:keep_count]]


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


def _scale_vector(vector: tuple[float, float, float], scalar: float) -> tuple[float, float, float]:
    return (
        vector[0] * scalar,
        vector[1] * scalar,
        vector[2] * scalar,
    )


def _rotation_between_vectors(
    source: tuple[float, float, float],
    target: tuple[float, float, float],
    *,
    minimum_degrees: float,
) -> tuple[tuple[float, float, float], float] | None:
    normalized_source = _normalize(source)
    normalized_target = _normalize(target)
    if _vector_length(normalized_source) <= 1e-6 or _vector_length(normalized_target) <= 1e-6:
        return None
    alignment = max(-1.0, min(1.0, _dot(normalized_source, normalized_target)))
    if alignment >= math.cos(math.radians(minimum_degrees)):
        return None
    axis = _cross(normalized_source, normalized_target)
    if _vector_length(axis) <= 1e-6:
        axis = (1.0, 0.0, 0.0)
    return (_normalize(axis), math.acos(alignment))


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
    .control {{
      display: grid;
      gap: 6px;
      font-size: 0.95rem;
    }}
    .control-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 28px;
      font-size: 0.95rem;
    }}
    .control-row input[type="checkbox"] {{
      flex: 0 0 auto;
    }}
    .control-group {{
      display: grid;
      gap: 8px;
      padding: 10px 12px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.03);
    }}
    .control-group-title {{
      color: var(--muted);
      font-size: 0.82rem;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }}
    .control-inline {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      font-size: 0.88rem;
      color: var(--muted);
    }}
    .control-inline output {{
      min-width: 48px;
      text-align: right;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
    }}
    .control-inline input[type="range"] {{
      grid-column: 1 / -1;
    }}
    input[type="range"] {{
      width: 100%;
    }}
    select,
    button {{
      width: 100%;
      min-height: 30px;
      box-sizing: border-box;
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
        <label class="control">Playback speed
          <input id="speed" type="range" min="0.25" max="2" step="0.05" value="1" />
        </label>
        <button id="pauseToggle" type="button">Pause</button>
        <label class="control">Zoom
          <input id="zoom" type="range" min="120" max="420" step="10" value="240" />
        </label>
        <label class="control-row" for="autoWorldAlignment">
          <span>Use automatic world alignment</span>
          <input id="autoWorldAlignment" type="checkbox" />
        </label>
        <label class="control-row" for="sceneInverted">
          <span>Invert scene</span>
          <input id="sceneInverted" type="checkbox" />
        </label>
        <label class="control-row" for="showSmplMesh">
          <span>Show WHAM SMPL mesh</span>
          <input id="showSmplMesh" type="checkbox" />
        </label>
        <div class="control-group">
          <div class="control-group-title">Root lock</div>
          <label class="control-row" for="fixedRoot">
            <span id="rootTranslationLabel"></span>
            <input id="fixedRoot" type="checkbox" />
          </label>
          <label class="control-row" for="lockYRoot">
            <span>Lock root Y drift</span>
            <input id="lockYRoot" type="checkbox" />
          </label>
          <label class="control-row" for="lockPlantedFeet">
            <span>Lock planted feet</span>
            <input id="lockPlantedFeet" type="checkbox" />
          </label>
          <div class="control-group-title">Ankle lock target offset</div>
          <label class="control-inline" for="ankleOffsetForward">
            <span>Forward</span>
            <output id="ankleOffsetForwardValue">0.0 cm</output>
            <input id="ankleOffsetForward" type="range" min="-0.25" max="0.25" step="0.005" value="0" />
          </label>
          <label class="control-inline" for="ankleOffsetLateral">
            <span>Lateral</span>
            <output id="ankleOffsetLateralValue">0.0 cm</output>
            <input id="ankleOffsetLateral" type="range" min="-0.25" max="0.25" step="0.005" value="0" />
          </label>
          <label class="control-inline" for="ankleOffsetUp">
            <span>Vertical</span>
            <output id="ankleOffsetUpValue">0.0 cm</output>
            <input id="ankleOffsetUp" type="range" min="-0.12" max="0.12" step="0.005" value="0" />
          </label>
        </div>
        <label class="control">Loop preview
          <select id="loopSelect"></select>
        </label>
        <button id="downloadWearSkeleton" type="button">Download baked Wear skeleton</button>
        <button id="downloadSmplMesh" type="button">Download baked WHAM SMPL mesh</button>
        <div class="stat">Detected loops: <span id="loopCount"></span></div>
        <div class="stat">Active span: <span id="activeLoop">Full clip</span></div>
        <div class="stat">Frames: <span id="frameCount"></span></div>
        <div class="stat">FPS: <span id="fps"></span></div>
        <div class="stat">Current frame: <span id="frameIndex">0</span></div>
      </div>
      <ul>
        <li>This preview is the motion review gate before offline humanoid retargeting.</li>
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

    const payload = {payload_json};
    const viewport = document.getElementById("viewport");
    const speedInput = document.getElementById("speed");
    const pauseToggleButton = document.getElementById("pauseToggle");
    const zoomInput = document.getElementById("zoom");
    const autoWorldAlignmentInput = document.getElementById("autoWorldAlignment");
    const sceneInvertedInput = document.getElementById("sceneInverted");
    const showSmplMeshInput = document.getElementById("showSmplMesh");
    const fixedRootInput = document.getElementById("fixedRoot");
    const lockYRootInput = document.getElementById("lockYRoot");
    const lockPlantedFeetInput = document.getElementById("lockPlantedFeet");
    const ankleOffsetForwardInput = document.getElementById("ankleOffsetForward");
    const ankleOffsetLateralInput = document.getElementById("ankleOffsetLateral");
    const ankleOffsetUpInput = document.getElementById("ankleOffsetUp");
    const ankleOffsetForwardValue = document.getElementById("ankleOffsetForwardValue");
    const ankleOffsetLateralValue = document.getElementById("ankleOffsetLateralValue");
    const ankleOffsetUpValue = document.getElementById("ankleOffsetUpValue");
    const downloadWearSkeletonButton = document.getElementById("downloadWearSkeleton");
    const downloadSmplMeshButton = document.getElementById("downloadSmplMesh");
    const loopSelect = document.getElementById("loopSelect");
    const loopCountNode = document.getElementById("loopCount");
    const activeLoopNode = document.getElementById("activeLoop");
    const rootTranslationLabel = document.getElementById("rootTranslationLabel");
    const frameIndexNode = document.getElementById("frameIndex");
    document.getElementById("frameCount").textContent = String(payload.frameCount);
    document.getElementById("fps").textContent = String(payload.fps);

    let yaw = 0.0;
    let pitch = 0.18;
    let zoom = parseFloat(zoomInput.value);
    let speed = parseFloat(speedInput.value);
    let fixedRoot = Boolean(payload.defaultFixedRoot);
    let paused = false;
    let frameCursor = 0;
    let playbackDirection = 1;
    let lastTimestamp = null;
    let dragging = false;
    let cameraTouched = false;
    let dragX = 0;
    let dragY = 0;
    let pendingReframeHandle = null;
    let autoWorldAlignmentEnabled = Boolean(payload.defaultAutoWorldAlignment);
    let sceneInverted = Boolean(payload.defaultSceneInverted);
    let showSmplMesh = Boolean(payload.smplMesh);
    let showBoundsHelper = true;
    let lockYRoot = false;
    let lockPlantedFeet = false;
    let ankleLockOffsetForward = parseFloat(ankleOffsetForwardInput.value);
    let ankleLockOffsetLateral = parseFloat(ankleOffsetLateralInput.value);
    let ankleLockOffsetUp = parseFloat(ankleOffsetUpInput.value);
    let activeRenderFrame = null;
    let footLockCorrectionsKey = null;
    let footLockCorrections = new Map();
    let lockedJointFrameKey = null;
    let lockedJointPositions = new Map();
    const cameraTarget = new THREE.Vector3();
    const defaultAutoAlignment = Array.isArray(payload.defaultAutoAlignment) ? payload.defaultAutoAlignment : [];
    const detectedLoops = Array.isArray(payload.detectedLoops) ? payload.detectedLoops : [];
    let selectedLoopIndex = detectedLoops.length > 0 ? 0 : -1;
    let currentLoop = selectedLoopIndex >= 0 ? detectedLoops[selectedLoopIndex] : null;
    let currentAutoAlignment = currentLoop?.autoAlignment ?? defaultAutoAlignment;
    let playbackState = buildPlaybackState(payload.frames, currentLoop);
    let activeRootAnchor = null;
    let cachedSceneBoundsKey = null;
    let cachedSceneBounds = null;
    fixedRootInput.checked = fixedRoot;
    lockYRootInput.checked = lockYRoot;
    lockPlantedFeetInput.checked = lockPlantedFeet;
    autoWorldAlignmentInput.checked = autoWorldAlignmentEnabled;
    sceneInvertedInput.checked = sceneInverted;
    showSmplMeshInput.checked = showSmplMesh;
    showSmplMeshInput.disabled = !payload.smplMesh;
    downloadSmplMeshButton.disabled = !payload.smplMesh;
    rootTranslationLabel.textContent = payload.rootTranslationToggleLabel ?? "Lock global root drift";
    loopCountNode.textContent = String(detectedLoops.length);
    refreshAnkleLockOffsetLabels();
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
    scene.add(perspectiveCamera);

    const ambientLight = new THREE.AmbientLight(0x29404b, 0.5);
    scene.add(ambientLight);
    const hemiLight = new THREE.HemisphereLight(0x9ff7ff, 0x03070a, 0.95);
    scene.add(hemiLight);
    const directionalLight = new THREE.DirectionalLight(0xeaffff, 1.8);
    directionalLight.position.set(-4.6, 6.8, 3.2);
    scene.add(directionalLight);
    const rimLight = new THREE.DirectionalLight(0x2df0ff, 1.35);
    rimLight.position.set(3.6, 2.4, -5.2);
    scene.add(rimLight);

    const grid = new THREE.GridHelper(3.5, 10, 0x1ed6e3, 0x15242c);
    scene.add(grid);
    const mergedBoundsHelper = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
      new THREE.LineBasicMaterial({{ color: 0x38f7ff, transparent: true, opacity: 0.82 }})
    );
    scene.add(mergedBoundsHelper);

    const limbMaterial = new THREE.MeshStandardMaterial({{
        color: 0x081317,
        emissive: 0x35f2ff,
        emissiveIntensity: 0.62,
        roughness: 0.28,
        metalness: 0.2,
        polygonOffset: true,
        polygonOffsetFactor: 1,
        polygonOffsetUnits: 1,
        flatShading: true,
      }});
    const torsoMaterial = new THREE.MeshStandardMaterial({{
        color: 0x0a1519,
        emissive: 0x47f6ff,
        emissiveIntensity: 0.78,
        roughness: 0.22,
        metalness: 0.24,
        polygonOffset: true,
        polygonOffsetFactor: 1,
        polygonOffsetUnits: 1,
        flatShading: true,
      }});
    const headMaterial = new THREE.MeshStandardMaterial({{
        color: 0x0d1a1f,
        emissive: 0x8afbff,
        emissiveIntensity: 0.9,
        roughness: 0.16,
        metalness: 0.3,
        polygonOffset: true,
        polygonOffsetFactor: 1,
        polygonOffsetUnits: 1,
        flatShading: true,
      }});
    const limbOutlineMaterial = new THREE.LineBasicMaterial({{
        color: 0x44f7ff,
        transparent: true,
        opacity: 0.95,
      }});
    const torsoOutlineMaterial = new THREE.LineBasicMaterial({{
        color: 0x8bfdff,
        transparent: true,
        opacity: 0.98,
      }});
    const headOutlineMaterial = new THREE.LineBasicMaterial({{
        color: 0xe9ffff,
        transparent: true,
        opacity: 1.0,
      }});
    function createStackedPrismGeometry(levels) {{
      const vertices = [];
      const indices = [];
      for (const level of levels) {{
        const halfWidth = level.width * 0.5;
        const halfDepth = level.depth * 0.5;
        const bevelWidth = halfWidth * 0.72;
        const bevelDepth = halfDepth * 0.72;
        vertices.push(
          -bevelWidth, level.y, -halfDepth,
          bevelWidth, level.y, -halfDepth,
          halfWidth, level.y, -bevelDepth,
          halfWidth, level.y, bevelDepth,
          bevelWidth, level.y, halfDepth,
          -bevelWidth, level.y, halfDepth,
          -halfWidth, level.y, bevelDepth,
          -halfWidth, level.y, -bevelDepth
        );
      }}
      for (let index = 0; index < levels.length - 1; index += 1) {{
        const base = index * 8;
        const next = base + 8;
        for (let side = 0; side < 8; side += 1) {{
          const sideNext = (side + 1) % 8;
          indices.push(base + side, base + sideNext, next + sideNext, base + side, next + sideNext, next + side);
        }}
      }}
      const top = (levels.length - 1) * 8;
      for (let side = 1; side < 7; side += 1) {{
        indices.push(0, side + 1, side);
        indices.push(top, top + side, top + side + 1);
      }}
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
      geometry.setIndex(indices);
      geometry.computeVertexNormals();
      return geometry;
    }}

    function createFacetedHeadGeometry() {{
      const levels = [
        {{ y: -0.5, width: 0.68, depth: 0.58 }},
        {{ y: -0.18, width: 0.9, depth: 0.78 }},
        {{ y: 0.28, width: 0.84, depth: 0.72 }},
        {{ y: 0.5, width: 0.58, depth: 0.54 }},
      ];
      return createStackedPrismGeometry(levels);
    }}

    function createCoreShellGeometry(rings) {{
      const validRings = rings.filter((ring) => ring?.center && ring?.xAxis && ring?.zAxis);
      if (validRings.length < 2) {{
        return null;
      }}
      const vertices = [];
      const indices = [];
      for (const ring of validRings) {{
        const center = ring.center;
        const xAxis = ring.xAxis.clone().normalize();
        const zAxis = ring.zAxis.clone().normalize();
        const xHalf = ring.width * 0.5;
        const zHalf = ring.depth * 0.5;
        const bevelX = xHalf * 0.72;
        const bevelZ = zHalf * 0.72;
        const offsets = [
          xAxis.clone().multiplyScalar(-bevelX).addScaledVector(zAxis, -zHalf),
          xAxis.clone().multiplyScalar(bevelX).addScaledVector(zAxis, -zHalf),
          xAxis.clone().multiplyScalar(xHalf).addScaledVector(zAxis, -bevelZ),
          xAxis.clone().multiplyScalar(xHalf).addScaledVector(zAxis, bevelZ),
          xAxis.clone().multiplyScalar(bevelX).addScaledVector(zAxis, zHalf),
          xAxis.clone().multiplyScalar(-bevelX).addScaledVector(zAxis, zHalf),
          xAxis.clone().multiplyScalar(-xHalf).addScaledVector(zAxis, bevelZ),
          xAxis.clone().multiplyScalar(-xHalf).addScaledVector(zAxis, -bevelZ),
        ];
        for (const offset of offsets) {{
          const point = center.clone().add(offset);
          vertices.push(point.x, point.y, point.z);
        }}
      }}
      for (let index = 0; index < validRings.length - 1; index += 1) {{
        const base = index * 8;
        const next = base + 8;
        for (let side = 0; side < 8; side += 1) {{
          const sideNext = (side + 1) % 8;
          indices.push(base + side, base + sideNext, next + sideNext, base + side, next + sideNext, next + side);
        }}
      }}
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
      geometry.setIndex(indices);
      geometry.computeVertexNormals();
      return geometry;
    }}

    const limbGeometry = createStackedPrismGeometry([
      {{ y: -0.5, width: 0.74, depth: 0.68 }},
      {{ y: -0.12, width: 0.96, depth: 0.82 }},
      {{ y: 0.24, width: 0.84, depth: 0.74 }},
      {{ y: 0.5, width: 0.62, depth: 0.58 }},
    ]);
    const torsoSegmentGeometry = createStackedPrismGeometry([
      {{ y: -0.5, width: 0.7, depth: 0.76 }},
      {{ y: 0.05, width: 0.52, depth: 0.6 }},
      {{ y: 0.5, width: 0.64, depth: 0.66 }},
    ]);
    const pelvisGeometry = createStackedPrismGeometry([
      {{ y: -0.5, width: 0.88, depth: 0.72 }},
      {{ y: -0.08, width: 1.0, depth: 0.84 }},
      {{ y: 0.5, width: 0.62, depth: 0.64 }},
    ]);
    const ribcageGeometry = createStackedPrismGeometry([
      {{ y: -0.5, width: 0.58, depth: 0.64 }},
      {{ y: -0.08, width: 0.78, depth: 0.82 }},
      {{ y: 0.32, width: 1.0, depth: 0.94 }},
      {{ y: 0.5, width: 0.84, depth: 0.76 }},
    ]);
    const clavicleGeometry = createStackedPrismGeometry([
      {{ y: -0.5, width: 1.0, depth: 0.7 }},
      {{ y: 0.5, width: 0.86, depth: 0.58 }},
    ]);
    const shoulderGeometry = createStackedPrismGeometry([
      {{ y: -0.5, width: 0.72, depth: 0.7 }},
      {{ y: 0.0, width: 1.0, depth: 1.0 }},
      {{ y: 0.5, width: 0.72, depth: 0.7 }},
    ]);
    const spineGeometry = createStackedPrismGeometry([
      {{ y: -0.5, width: 0.42, depth: 0.52 }},
      {{ y: 0.0, width: 0.32, depth: 0.4 }},
      {{ y: 0.5, width: 0.38, depth: 0.46 }},
    ]);
    const headGeometry = createFacetedHeadGeometry();
    const axisX = new THREE.Vector3(1, 0, 0);
    const axisY = new THREE.Vector3(0, 1, 0);
    const axisZ = new THREE.Vector3(0, 0, 1);
    const tempVector = new THREE.Vector3();
    const tempMidpoint = new THREE.Vector3();
    const tempQuaternion = new THREE.Quaternion();
    const tempScale = new THREE.Vector3();
    const tempPivotedPoint = new THREE.Vector3();
    const tempMatrix = new THREE.Matrix4();
    const tempBoundsBox = new THREE.Box3();
    const tempUnionBox = new THREE.Box3();
    const tempBoundsCorner = new THREE.Vector3();
    const sceneOriginOffset = new THREE.Vector3();
    let suppressSceneOriginOffset = false;
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

    function isLegCapsule(capsule) {{
      const key = `${{capsule.start}}->${{capsule.end}}`;
      return key === "left_hip->left_knee"
        || key === "left_knee->left_ankle"
        || key === "left_ankle->left_foot"
        || key === "right_hip->right_knee"
        || key === "right_knee->right_ankle"
        || key === "right_ankle->right_foot";
    }}

    function isArmCapsule(capsule) {{
      const key = `${{capsule.start}}->${{capsule.end}}`;
      return key === "left_shoulder->left_elbow"
        || key === "left_elbow->left_wrist"
        || key === "right_shoulder->right_elbow"
        || key === "right_elbow->right_wrist";
    }}

    function limbProfileForCapsule(capsule, radius) {{
      const key = `${{capsule.start}}->${{capsule.end}}`;
      if (key.includes("hip->") && key.includes("knee")) {{
        return {{ width: radius * 1.95, depth: radius * 1.42 }};
      }}
      if (key.includes("knee->") && key.includes("ankle")) {{
        return {{ width: radius * 1.55, depth: radius * 1.12 }};
      }}
      if (key.includes("ankle->") && key.includes("foot")) {{
        return {{ width: radius * 1.28, depth: radius * 0.82 }};
      }}
      if (key.includes("shoulder->") && key.includes("elbow")) {{
        return {{ width: radius * 1.62, depth: radius * 1.08 }};
      }}
      if (key.includes("elbow->") && key.includes("wrist")) {{
        return {{ width: radius * 1.28, depth: radius * 0.88 }};
      }}
      if (key.includes("collar->") && key.includes("shoulder")) {{
        return {{ width: radius * 1.18, depth: radius * 0.82 }};
      }}
      return {{ width: radius * 1.18, depth: radius * 0.9 }};
    }}

    function projectedAxis(axis, planeNormal) {{
      if (!axis || !planeNormal) {{
        return null;
      }}
      const projected = axis.clone().sub(
        planeNormal.clone().multiplyScalar(axis.dot(planeNormal))
      );
      if (projected.lengthSq() <= 1e-8) {{
        return null;
      }}
      return projected.normalize();
    }}

    function attachOutline(mesh, outlineMaterial) {{
      const outline = new THREE.LineSegments(
        new THREE.EdgesGeometry(mesh.geometry),
        outlineMaterial
      );
      outline.renderOrder = 2;
      mesh.userData.outline = outline;
      mesh.userData.outlineMaterial = outlineMaterial;
      mesh.add(outline);
      return mesh;
    }}

    function replaceOutlinedGeometry(mesh, nextGeometry) {{
      mesh.geometry.dispose();
      mesh.geometry = nextGeometry;
      const outline = mesh.userData.outline;
      if (outline) {{
        outline.geometry.dispose();
        outline.geometry = new THREE.EdgesGeometry(nextGeometry);
      }}
    }}

    const limbNodes = payload.capsules
        .filter((capsule) => !isTorsoCapsule(capsule))
        .map((capsule) => {{
        const mesh = attachOutline(new THREE.Mesh(limbGeometry, limbMaterial), limbOutlineMaterial);
        scene.add(mesh);
        return {{
          capsule,
          mesh,
        }};
      }});

    const pelvisMesh = attachOutline(new THREE.Mesh(pelvisGeometry, torsoMaterial), torsoOutlineMaterial);
    const coreShellMesh = attachOutline(new THREE.Mesh(torsoSegmentGeometry.clone(), torsoMaterial), torsoOutlineMaterial);
    coreShellMesh.visible = false;
    const spineMeshes = [0, 1, 2].map(() => attachOutline(new THREE.Mesh(spineGeometry, torsoMaterial), torsoOutlineMaterial));
    const abdomenMesh = attachOutline(new THREE.Mesh(torsoSegmentGeometry, torsoMaterial), torsoOutlineMaterial);
    const chestMesh = attachOutline(new THREE.Mesh(ribcageGeometry, torsoMaterial), torsoOutlineMaterial);
    const upperChestMesh = attachOutline(new THREE.Mesh(spineGeometry, torsoMaterial), torsoOutlineMaterial);
    const leftShoulderMassMesh = attachOutline(new THREE.Mesh(shoulderGeometry, torsoMaterial), torsoOutlineMaterial);
    const rightShoulderMassMesh = attachOutline(new THREE.Mesh(shoulderGeometry, torsoMaterial), torsoOutlineMaterial);
    const clavicleMesh = attachOutline(new THREE.Mesh(clavicleGeometry, torsoMaterial), torsoOutlineMaterial);
    scene.add(pelvisMesh);
    scene.add(coreShellMesh);
    for (const mesh of spineMeshes) {{
      scene.add(mesh);
    }}
    scene.add(abdomenMesh);
    scene.add(chestMesh);
    scene.add(upperChestMesh);
    scene.add(leftShoulderMassMesh);
    scene.add(rightShoulderMassMesh);
    scene.add(clavicleMesh);

    const headMesh = attachOutline(new THREE.Mesh(headGeometry, headMaterial), headOutlineMaterial);
    scene.add(headMesh);
    const proceduralBodyMeshes = [
      pelvisMesh,
      coreShellMesh,
      ...spineMeshes,
      abdomenMesh,
      chestMesh,
      upperChestMesh,
      leftShoulderMassMesh,
      rightShoulderMassMesh,
      clavicleMesh,
      headMesh,
      ...limbNodes.map((node) => node.mesh),
    ];
    const smplMeshMaterial = new THREE.MeshStandardMaterial({{
      color: 0x102028,
      emissive: 0x2cecff,
      emissiveIntensity: 0.36,
      roughness: 0.42,
      metalness: 0.06,
      flatShading: true,
      side: THREE.DoubleSide,
    }});
    const smplMeshObject = new THREE.Mesh(new THREE.BufferGeometry(), smplMeshMaterial);
    smplMeshObject.visible = false;
    scene.add(smplMeshObject);
    let smplMeshGeometry = null;
    const skeletonLineMaterial = new THREE.LineBasicMaterial({{
      color: 0x64f7ff,
      transparent: true,
      opacity: 0.22,
    }});
    const skeletonSurfaceMaterial = new THREE.MeshStandardMaterial({{
      color: 0x071014,
      emissive: 0x4ff7ff,
      emissiveIntensity: 0.58,
      roughness: 0.18,
      metalness: 0.22,
      flatShading: true,
    }});
    const jointNodeMaterial = new THREE.MeshStandardMaterial({{
      color: 0x0d171c,
      emissive: 0xc7ffff,
      emissiveIntensity: 0.72,
      roughness: 0.14,
      metalness: 0.18,
      flatShading: true,
    }});
    const jointNodeGeometry = new THREE.SphereGeometry(1, 7, 6);
    const skeletonChains = [
      ["left_foot", "left_ankle", "left_knee", "left_hip", "pelvis", "right_hip", "right_knee", "right_ankle", "right_foot"],
      ["pelvis", "spine1", "spine2", "spine3", "neck", "head"],
      ["neck", "left_collar", "left_shoulder", "left_elbow", "left_wrist", "left_hand"],
      ["neck", "right_collar", "right_shoulder", "right_elbow", "right_wrist", "right_hand"],
    ];
    const skeletonLines = skeletonChains.map((jointNames) => {{
      const geometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(0, 0, 0),
      ]);
      const line = new THREE.Line(geometry, skeletonLineMaterial);
      scene.add(line);
      return {{ jointNames, line }};
    }});
    const skeletonSurfaces = skeletonChains.map((jointNames) => {{
      const curve = new THREE.CatmullRomCurve3([
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(0, 1, 0),
      ]);
      const mesh = new THREE.Mesh(
        new THREE.ExtrudeGeometry(new THREE.Shape(), {{ steps: 1, depth: 0.01, bevelEnabled: false }}),
        skeletonSurfaceMaterial
      );
      scene.add(mesh);
      return {{ jointNames, mesh }};
    }});
    const jointNodeNames = Array.from(new Set(skeletonChains.flat()));
    const jointNodeMeshes = jointNodeNames.map((jointName) => {{
      const mesh = new THREE.Mesh(jointNodeGeometry, jointNodeMaterial);
      scene.add(mesh);
      return {{ jointName, mesh }};
    }});
    const previewBoundsObjects = [
      ...proceduralBodyMeshes,
      ...skeletonLines.map((entry) => entry.line),
      ...skeletonSurfaces.map((entry) => entry.mesh),
      ...jointNodeMeshes.map((entry) => entry.mesh),
    ];

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
        activeRenderFrame = frame;
        const frameTranslation = currentFixedRoot ? getFrameTranslation(frame) : [0, 0, 0];
        for (const jointName of payload.jointNames) {{
          const point = frame.joints[jointName];
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          const worldPoint = toBaseWorldPoint(point, frameTranslation, false);
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

    function buildProfileShape(width, depth) {{
      const shape = new THREE.Shape();
      const halfWidth = width * 0.5;
      const halfDepth = depth * 0.5;
      shape.moveTo(-halfWidth, -halfDepth);
      shape.lineTo(halfWidth, -halfDepth);
      shape.quadraticCurveTo(halfWidth * 1.08, 0, halfWidth, halfDepth);
      shape.lineTo(-halfWidth, halfDepth);
      shape.quadraticCurveTo(-halfWidth * 1.08, 0, -halfWidth, -halfDepth);
      return shape;
    }}

    function chainProfileDimensions(jointNames) {{
      if (jointNames.length >= 8) {{
        return {{ width: 0.14, depth: 0.09 }};
      }}
      if (jointNames.includes("head")) {{
        return {{ width: 0.1, depth: 0.08 }};
      }}
      return {{ width: 0.08, depth: 0.055 }};
    }}

    function computeSceneBounds(currentFixedRoot) {{
      const frames = playbackState.boundsFrames;
      if (frames.length === 0) {{
        return computeBaseSceneBounds(currentFixedRoot);
      }}
      let minX = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      let minZ = Number.POSITIVE_INFINITY;
      let maxZ = Number.NEGATIVE_INFINITY;
      for (const frame of frames) {{
        activeRenderFrame = frame;
        const frameTranslation = currentFixedRoot ? getFrameTranslation(frame) : [0, 0, 0];
        for (const jointName of payload.jointNames) {{
          const point = frame.joints[jointName];
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          const worldPoint = toWorldPoint(point, frameTranslation, currentFixedRoot, false, jointName);
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
      refreshSceneBasis();
      const inverseSceneRotation = sceneRotationQuaternion.clone().invert();
      let minX = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      let minZ = Number.POSITIVE_INFINITY;
      let maxZ = Number.NEGATIVE_INFINITY;
      suppressSceneOriginOffset = true;
      for (const frame of frames) {{
        updateSceneForFrame(frame);
        scene.updateMatrixWorld(true);
        tempUnionBox.makeEmpty();
        for (const object of previewBoundsObjects) {{
          if (!object.visible) {{
            continue;
          }}
          tempBoundsBox.setFromObject(object);
          if (tempBoundsBox.isEmpty()) {{
            continue;
          }}
          tempUnionBox.union(tempBoundsBox);
        }}
        if (tempUnionBox.isEmpty()) {{
          continue;
        }}
        for (const x of [tempUnionBox.min.x, tempUnionBox.max.x]) {{
          for (const y of [tempUnionBox.min.y, tempUnionBox.max.y]) {{
            for (const z of [tempUnionBox.min.z, tempUnionBox.max.z]) {{
              tempBoundsCorner.set(x, y, z).applyQuaternion(inverseSceneRotation);
              minX = Math.min(minX, tempBoundsCorner.x);
              maxX = Math.max(maxX, tempBoundsCorner.x);
              minY = Math.min(minY, tempBoundsCorner.y);
              maxY = Math.max(maxY, tempBoundsCorner.y);
              minZ = Math.min(minZ, tempBoundsCorner.z);
              maxZ = Math.max(maxZ, tempBoundsCorner.z);
            }}
          }}
        }}
      }}
      suppressSceneOriginOffset = false;
      if (!Number.isFinite(minX) || !Number.isFinite(maxX) || !Number.isFinite(minY) || !Number.isFinite(maxY)) {{
        return computeSceneBounds(currentFixedRoot);
      }}
      const horizontalPadding = 0.08;
      const verticalPadding = 0.08;
      const bounds = {{
        minX: minX - horizontalPadding,
        maxX: maxX + horizontalPadding,
        minY: minY - verticalPadding,
        maxY: maxY + verticalPadding,
        minZ: minZ - horizontalPadding,
        maxZ: maxZ + horizontalPadding,
      }};
      return bounds;
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

    function getFrameRootPoint(frame, preferredRootJoint) {{
      const rootCandidates = [
        preferredRootJoint,
        "pelvis",
        "spine1",
      ];
      for (const jointName of rootCandidates) {{
        if (typeof jointName !== "string" || jointName.length === 0) {{
          continue;
        }}
        const point = frame.joints[jointName];
        if (Array.isArray(point) && point.length >= 3) {{
          return {{
            x: point[0],
            y: point[1],
            z: point[2],
          }};
        }}
      }}
      return null;
    }}

    function boundsCenterToWorld(bounds) {{
      const localCenter = new THREE.Vector3(
        (bounds.minX + bounds.maxX) * 0.5,
        (bounds.minY + bounds.maxY) * 0.5,
        (bounds.minZ + bounds.maxZ) * 0.5
      );
      localCenter.sub(sceneOriginOffset);
      refreshSceneBasis();
      localCenter.applyQuaternion(sceneRotationQuaternion);
      return localCenter;
    }}

    function estimateSceneOrigin(currentFixedRoot) {{
      const bounds = getCachedSceneBounds(currentFixedRoot);
      const worldCenter = boundsCenterToWorld(bounds);
      return [worldCenter.x, worldCenter.y, worldCenter.z];
    }}

    function refreshGroundPlacement() {{
      const bounds = getCachedSceneBounds(fixedRoot);
      refreshSceneBasis();
      const localCenter = new THREE.Vector3(
        (bounds.minX + bounds.maxX) * 0.5,
        bounds.minY - 0.06,
        (bounds.minZ + bounds.maxZ) * 0.5
      );
      localCenter.sub(sceneOriginOffset);
      localCenter.applyQuaternion(sceneRotationQuaternion);
      grid.position.copy(localCenter);
      grid.quaternion.copy(sceneRotationQuaternion);
    }}

    function refreshMergedBoundsHelper() {{
      if (!showBoundsHelper) {{
        mergedBoundsHelper.visible = false;
        return;
      }}
      const bounds = getCachedSceneBounds(fixedRoot);
      if (!bounds) {{
        mergedBoundsHelper.visible = false;
        return;
      }}
      refreshSceneBasis();
      mergedBoundsHelper.visible = true;
      mergedBoundsHelper.position.set(
        (bounds.minX + bounds.maxX) * 0.5,
        (bounds.minY + bounds.maxY) * 0.5,
        (bounds.minZ + bounds.maxZ) * 0.5
      ).sub(sceneOriginOffset).applyQuaternion(sceneRotationQuaternion);
      mergedBoundsHelper.quaternion.copy(sceneRotationQuaternion);
      mergedBoundsHelper.scale.set(
        Math.max(0.001, bounds.maxX - bounds.minX),
        Math.max(0.001, bounds.maxY - bounds.minY),
        Math.max(0.001, bounds.maxZ - bounds.minZ)
      );
    }}

    function buildSceneBoundsCacheKey(currentFixedRoot) {{
      return `${{currentFixedRoot}}|${{lockYRoot}}|${{lockPlantedFeet}}|${{ankleLockOffsetForward}}|${{ankleLockOffsetLateral}}|${{ankleLockOffsetUp}}|${{autoWorldAlignmentEnabled}}|${{sceneInverted}}|${{selectedLoopIndex}}`;
    }}

    function invalidateSceneBoundsCache() {{
      cachedSceneBoundsKey = null;
      cachedSceneBounds = null;
      footLockCorrectionsKey = null;
      footLockCorrections = new Map();
      lockedJointFrameKey = null;
      lockedJointPositions = new Map();
    }}

    function getCachedSceneBounds(currentFixedRoot) {{
      const key = buildSceneBoundsCacheKey(currentFixedRoot);
      if (cachedSceneBoundsKey !== key || cachedSceneBounds == null) {{
        cachedSceneBounds = computeOrientedSceneBounds(currentFixedRoot);
        cachedSceneBoundsKey = key;
        sceneOriginOffset.set(
          (cachedSceneBounds.minX + cachedSceneBounds.maxX) * 0.5,
          (cachedSceneBounds.minY + cachedSceneBounds.maxY) * 0.5,
          (cachedSceneBounds.minZ + cachedSceneBounds.maxZ) * 0.5
        );
      }}
      return cachedSceneBounds;
    }}

    function findFrameCursorClosestToBoundsCenter() {{
      const frames = playbackState.frames;
      if (!frames || frames.length === 0) {{
        return 0;
      }}
      const bounds = getCachedSceneBounds(fixedRoot);
      const targetX = (bounds.minX + bounds.maxX) * 0.5;
      const targetY = (bounds.minY + bounds.maxY) * 0.5;
      const targetZ = (bounds.minZ + bounds.maxZ) * 0.5;
      refreshSceneBasis();
      const inverseSceneRotation = sceneRotationQuaternion.clone().invert();
      let bestIndex = 0;
      let bestDistance = Number.POSITIVE_INFINITY;
      frames.forEach((frame, index) => {{
        activeRenderFrame = frame;
        const frameTranslation = fixedRoot ? getFrameTranslation(frame) : [0, 0, 0];
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
          tempBoundsCorner.copy(toWorldPoint(point, frameTranslation, fixedRoot, false, jointName)).applyQuaternion(inverseSceneRotation);
          minX = Math.min(minX, tempBoundsCorner.x);
          maxX = Math.max(maxX, tempBoundsCorner.x);
          minY = Math.min(minY, tempBoundsCorner.y);
          maxY = Math.max(maxY, tempBoundsCorner.y);
          minZ = Math.min(minZ, tempBoundsCorner.z);
          maxZ = Math.max(maxZ, tempBoundsCorner.z);
        }}
        if (!Number.isFinite(minX) || !Number.isFinite(maxX)) {{
          return;
        }}
        const centerX = (minX + maxX) * 0.5;
        const centerY = (minY + maxY) * 0.5;
        const centerZ = (minZ + maxZ) * 0.5;
        const distance =
          (centerX - targetX) ** 2
          + (centerY - targetY) ** 2
          + (centerZ - targetZ) ** 2;
        if (distance < bestDistance) {{
          bestDistance = distance;
          bestIndex = index;
        }}
      }});
      return bestIndex;
    }}

    function refreshCameraTarget() {{
      cameraTarget.copy(boundsCenterToWorld(getCachedSceneBounds(fixedRoot)));
    }}

    function resetCameraOrbitFromBounds() {{
      const bounds = getCachedSceneBounds(fixedRoot);
      const width = Math.max(0.001, bounds.maxX - bounds.minX);
      const height = Math.max(0.001, bounds.maxY - bounds.minY);
      const depth = Math.max(0.001, bounds.maxZ - bounds.minZ);
      const horizontalAspect = width / Math.max(0.001, depth);
      yaw = horizontalAspect >= 1.15 ? 0.0 : 0.22;
      pitch = height >= Math.max(width, depth) * 0.95 ? 0.16 : 0.22;
      cameraTarget.copy(boundsCenterToWorld(bounds));
    }}

    function refreshSceneFrame() {{
      refreshMergedBoundsHelper();
      refreshGroundPlacement();
      refreshCameraTarget();
    }}

    function recalculateSceneBoundsAndFrame() {{
      invalidateSceneBoundsCache();
      refreshSceneFrame();
    }}

    function applySceneReframe() {{
      if (pendingReframeHandle != null) {{
        cancelAnimationFrame(pendingReframeHandle);
        pendingReframeHandle = null;
      }}
      recalculateSceneBoundsAndFrame();
      if (!cameraTouched) {{
        resetCameraOrbitFromBounds();
      }}
      updateCamera();
    }}

    function scheduleSceneReframe() {{
      if (pendingReframeHandle != null) {{
        return;
      }}
      pendingReframeHandle = requestAnimationFrame(() => {{
        pendingReframeHandle = null;
        applySceneReframe();
      }});
    }}

    function buildPlaybackFrames(frames, loop) {{
      if (!loop) {{
        return frames;
      }}
      const startFrame = Number.isInteger(loop.startFrame) ? loop.startFrame : 0;
      const endFrame = Number.isInteger(loop.endFrame) ? loop.endFrame : (frames.length - 1);
      return frames.slice(
        Math.max(0, Math.min(frames.length - 1, startFrame)),
        Math.max(0, Math.min(frames.length, endFrame + 1))
      );
    }}

    function buildPlaybackState(frames, loop) {{
      const activeFrames = buildPlaybackFrames(frames, loop);
      return {{
        frames: activeFrames,
        boundsFrames: activeFrames,
        loopable: Boolean(loop),
      }};
    }}

    function computeActiveRootAnchor(frames) {{
      if (!frames || frames.length === 0) {{
        return null;
      }}
      const rootPoints = frames
        .map((frame) => getFrameRootPoint(frame, payload.rootJoint))
        .filter((point) => point != null);
      if (rootPoints.length === 0) {{
        return null;
      }}
      return {{
        x: rootPoints.reduce((total, point) => total + point.x, 0) / rootPoints.length,
        y: rootPoints.reduce((total, point) => total + point.y, 0) / rootPoints.length,
        z: rootPoints.reduce((total, point) => total + point.z, 0) / rootPoints.length,
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
      activeRootAnchor = computeActiveRootAnchor(playbackState.boundsFrames);
      invalidateSceneBoundsCache();
      frameCursor = findFrameCursorClosestToBoundsCenter();
      playbackDirection = 1;
      refreshActiveLoopLabel();
      applySceneReframe();
    }}

    function resize() {{
      const width = viewport.clientWidth;
      const height = viewport.clientHeight;
      renderer.setPixelRatio(window.devicePixelRatio || 1);
      renderer.setSize(width, height, false);
      const aspect = width / Math.max(1, height);
      perspectiveCamera.aspect = aspect;
      perspectiveCamera.updateProjectionMatrix();
      refreshSceneFrame();
      updateCamera();
    }}

    function getFrameTranslation(frame) {{
      if (!fixedRoot) {{
        return [0, 0, 0];
      }}
      const rootPoint = getFrameRootPoint(frame, payload.rootJoint);
      if (!rootPoint || !activeRootAnchor) {{
        return [0, 0, 0];
      }}
      return [
        rootPoint.x - activeRootAnchor.x,
        lockYRoot ? rootPoint.y - activeRootAnchor.y : 0,
        rootPoint.z - activeRootAnchor.z,
      ];
    }}

    function getFrameBakeTranslation(frame, lockYDrift) {{
      if (!fixedRoot) {{
        return [0, 0, 0];
      }}
      const rootPoint = getFrameRootPoint(frame, payload.rootJoint);
      if (!rootPoint || !activeRootAnchor) {{
        return [0, 0, 0];
      }}
      return [
        rootPoint.x - activeRootAnchor.x,
        lockYDrift ? rootPoint.y - activeRootAnchor.y : 0,
        rootPoint.z - activeRootAnchor.z,
      ];
    }}

    function getFrameFloorMotionPoint(frame) {{
      const primarySupportJointNames = ["left_foot", "right_foot", "left_hand", "right_hand"];
      const fallbackSupportJointNames = ["left_ankle", "right_ankle", "left_wrist", "right_wrist"];
      const collectPoints = (jointNames) => {{
        const collected = [];
        for (const jointName of jointNames) {{
          const point = frame.joints[jointName];
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          collected.push(toBaseWorldPoint(point, [0, 0, 0], false));
        }}
        return collected;
      }};
      let points = collectPoints(primarySupportJointNames);
      if (points.length === 0) {{
        points = collectPoints(fallbackSupportJointNames);
      }}
      if (points.length === 0) {{
        const rootPoint = getFrameRootPoint(frame, payload.rootJoint);
        if (!rootPoint) {{
          return null;
        }}
        const worldPoint = toBaseWorldPoint([rootPoint.x, rootPoint.y, rootPoint.z], [0, 0, 0], false);
        return {{ x: worldPoint.x, z: worldPoint.z }};
      }}
      return {{
        x: points.reduce((total, point) => total + point.x, 0) / points.length,
        z: points.reduce((total, point) => total + point.z, 0) / points.length,
      }};
    }}

    function refreshSceneBasis() {{
      sceneRotationQuaternion.identity();
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

    function toUncorrectedWorldPoint(point, frameTranslation) {{
      const tx = frameTranslation?.[0] ?? 0;
      const ty = frameTranslation?.[1] ?? 0;
      const tz = frameTranslation?.[2] ?? 0;
      const transformedPoint = applyAutoAlignment(new THREE.Vector3(
        point[0] - tx,
        point[1] - ty,
        point[2] - tz
      ));
      if (sceneInverted) {{
        transformedPoint.applyAxisAngle(axisX, Math.PI);
      }}
      return transformedPoint;
    }}

    function frameFootLockKey(frame) {{
      return Number.isInteger(frame?.frameIndex) ? `frame:${{frame.frameIndex}}` : `time:${{frame?.timeSec ?? 0}}`;
    }}

    function medianValue(values) {{
      if (values.length === 0) {{
        return 0;
      }}
      const sorted = values.slice().sort((left, right) => left - right);
      const mid = Math.floor(sorted.length / 2);
      return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) * 0.5;
    }}

    function availableFootJoints() {{
      return ["left_ankle", "right_ankle"].filter((jointName) => payload.jointNames.includes(jointName));
    }}

    function formatCentimeters(value) {{
      return `${{(value * 100).toFixed(1)}} cm`;
    }}

    function refreshAnkleLockOffsetLabels() {{
      ankleOffsetForwardValue.textContent = formatCentimeters(ankleLockOffsetForward);
      ankleOffsetLateralValue.textContent = formatCentimeters(ankleLockOffsetLateral);
      ankleOffsetUpValue.textContent = formatCentimeters(ankleLockOffsetUp);
    }}

    function ankleLockTargetOffsetVector() {{
      refreshSceneBasis();
      return sceneForward
        .clone()
        .multiplyScalar(ankleLockOffsetForward)
        .addScaledVector(sceneRight, ankleLockOffsetLateral)
        .addScaledVector(sceneUp, ankleLockOffsetUp);
    }}

    function footSampleForFrame(frame, jointName) {{
      const point = frame?.joints?.[jointName];
      if (!Array.isArray(point) || point.length < 3) {{
        return null;
      }}
      const translation = fixedRoot ? getFrameTranslation(frame) : [0, 0, 0];
      return toUncorrectedWorldPoint(point, translation);
    }}

    function computeFootLockCorrections() {{
      const key = buildSceneBoundsCacheKey(fixedRoot);
      if (footLockCorrectionsKey === key) {{
        return footLockCorrections;
      }}
      footLockCorrectionsKey = key;
      footLockCorrections = new Map();
      if (!lockPlantedFeet) {{
        return footLockCorrections;
      }}
      const frames = playbackState.frames ?? [];
      const footJoints = availableFootJoints();
      if (frames.length === 0 || footJoints.length === 0) {{
        return footLockCorrections;
      }}
      const loopTargets = [];
      const targetsByFrameKey = new Map(frames.map((frame) => {{
        const targets = [];
        loopTargets.push(targets);
        return [frameFootLockKey(frame), targets];
      }}));
      const targetOffset = ankleLockTargetOffsetVector();
      const contactHeight = 0.075;
      const contactSpeed = 0.028;
      for (const jointName of footJoints) {{
        const samples = frames.map((frame, index) => {{
          const point = footSampleForFrame(frame, jointName);
          return point ? {{ frame, index, point }} : null;
        }});
        const validSamples = samples.filter((sample) => sample != null);
        if (validSamples.length === 0) {{
          continue;
        }}
        const floorY = Math.min(...validSamples.map((sample) => sample.point.y));
        const plantedSamples = samples.filter((sample, index) => {{
          if (!sample || sample.point.y > floorY + contactHeight) {{
            return false;
          }}
          const previous = index > 0 ? samples[index - 1] : null;
          const next = index + 1 < samples.length ? samples[index + 1] : null;
          const speedPrev = previous ? Math.hypot(sample.point.x - previous.point.x, sample.point.z - previous.point.z) : 0;
          const speedNext = next ? Math.hypot(next.point.x - sample.point.x, next.point.z - sample.point.z) : 0;
          return Math.min(speedPrev, speedNext) <= contactSpeed;
        }});
        if (plantedSamples.length === 0) {{
          continue;
        }}
        const anchorSamples = plantedSamples;
        const anchorPoint = new THREE.Vector3(
          medianValue(anchorSamples.map((sample) => sample.point.x)),
          medianValue(anchorSamples.map((sample) => sample.point.y)),
          medianValue(anchorSamples.map((sample) => sample.point.z))
        ).add(targetOffset);
        const plantedIndexes = new Set(plantedSamples.map((sample) => sample.index));
        for (const sample of validSamples) {{
          let weight = plantedIndexes.has(sample.index) ? 1 : 0;
          for (const plantedSample of plantedSamples) {{
            const distance = Math.abs(sample.index - plantedSample.index);
            if (distance <= 4) {{
              weight = Math.max(weight, 1 - distance / 5);
            }}
          }}
          if (weight <= 0) {{
            continue;
          }}
          const targets = targetsByFrameKey.get(frameFootLockKey(sample.frame));
          if (!targets) {{
            continue;
          }}
          targets.push({{
            jointName,
            anchorX: anchorPoint.x,
            anchorY: anchorPoint.y,
            anchorZ: anchorPoint.z,
            weight,
          }});
        }}
      }}
      for (const frame of frames) {{
        footLockCorrections.set(frameFootLockKey(frame), targetsByFrameKey.get(frameFootLockKey(frame)) ?? []);
      }}
      return footLockCorrections;
    }}

    function getFootLockTargets(frame) {{
      if (!lockPlantedFeet || !frame) {{
        return null;
      }}
      return computeFootLockCorrections().get(frameFootLockKey(frame)) ?? null;
    }}

    function computeLockedJointPositions(frame, frameTranslation) {{
      if (!lockPlantedFeet || !frame) {{
        lockedJointFrameKey = null;
        lockedJointPositions = new Map();
        return lockedJointPositions;
      }}
      const cacheKey = `${{frameFootLockKey(frame)}}|${{frameTranslation?.join(",") ?? ""}}|${{lockPlantedFeet}}`;
      if (lockedJointFrameKey === cacheKey) {{
        return lockedJointPositions;
      }}
      lockedJointFrameKey = cacheKey;
      lockedJointPositions = new Map();
      const targets = getFootLockTargets(frame);
      if (!targets || targets.length === 0) {{
        return lockedJointPositions;
      }}
      const basePositions = new Map();
      for (const jointName of payload.jointNames) {{
        const point = frame.joints[jointName];
        if (Array.isArray(point) && point.length >= 3) {{
          basePositions.set(jointName, toUncorrectedWorldPoint(point, frameTranslation));
        }}
      }}
      for (const side of ["left", "right"]) {{
        const ankleName = `${{side}}_ankle`;
        const footName = `${{side}}_foot`;
        const target = targets.find((candidate) => candidate.jointName === ankleName);
        if (!target) {{
          continue;
        }}
        const chain = [`${{side}}_hip`, `${{side}}_knee`, ankleName];
        if (chain.some((jointName) => !basePositions.has(jointName))) {{
          continue;
        }}
        const targetWeight = Math.max(0, Math.min(1, Number(target.weight) || 0));
        if (targetWeight <= 0) {{
          continue;
        }}
        const originalAnkle = basePositions.get(ankleName);
        const blendedTarget = originalAnkle.clone().lerp(
          new THREE.Vector3(target.anchorX, target.anchorY, target.anchorZ),
          targetWeight
        );
        const solved = solveLegIkChain(
          chain.map((jointName) => basePositions.get(jointName).clone()),
          blendedTarget
        );
        chain.forEach((jointName, index) => {{
          lockedJointPositions.set(jointName, solved[index]);
        }});
        if (basePositions.has(footName)) {{
          const originalAnkle = basePositions.get(ankleName);
          const originalFoot = basePositions.get(footName);
          const ankleToFoot = originalFoot.clone().sub(originalAnkle);
          lockedJointPositions.set(footName, solved[solved.length - 1].clone().add(ankleToFoot));
        }}
      }}
      return lockedJointPositions;
    }}

    function solveLegIkChain(points, target) {{
      if (points.length < 3) {{
        return points.map((point) => point.clone());
      }}
      const root = points[0].clone();
      const originalKnee = points[1].clone();
      const originalAnkle = points[2].clone();
      const upperLength = Math.max(root.distanceTo(originalKnee), 1e-6);
      const lowerLength = Math.max(originalKnee.distanceTo(originalAnkle), 1e-6);
      const rootToTarget = target.clone().sub(root);
      let targetDistance = rootToTarget.length();
      if (targetDistance <= 1e-6) {{
        rootToTarget.copy(originalAnkle).sub(root);
        targetDistance = rootToTarget.length();
      }}
      if (targetDistance <= 1e-6) {{
        rootToTarget.copy(sceneForward);
        targetDistance = 1;
      }}
      const targetAxis = rootToTarget.normalize();
      const maxReach = Math.max(upperLength + lowerLength - 1e-4, 1e-6);
      const minReach = Math.max(Math.abs(upperLength - lowerLength) + 1e-4, 1e-6);
      const solvedDistance = Math.min(Math.max(targetDistance, minReach), maxReach);
      const solvedAnkle = root.clone().addScaledVector(targetAxis, solvedDistance);

      const originalAxis = originalAnkle.clone().sub(root);
      if (originalAxis.lengthSq() > 1e-8) {{
        originalAxis.normalize();
      }} else {{
        originalAxis.copy(targetAxis);
      }}
      const sourceKneeOffset = originalKnee.clone().sub(root);
      const sourceBendDirection = sourceKneeOffset
        .clone()
        .sub(originalAxis.clone().multiplyScalar(sourceKneeOffset.dot(originalAxis)));
      let bendDirection = sourceBendDirection
        .clone()
        .sub(targetAxis.clone().multiplyScalar(sourceBendDirection.dot(targetAxis)));
      if (bendDirection.lengthSq() <= 1e-8) {{
        bendDirection = projectedAxis(sceneRight, targetAxis)
          ?? projectedAxis(sceneForward, targetAxis)
          ?? projectedAxis(axisY, targetAxis)
          ?? new THREE.Vector3(1, 0, 0);
      }} else {{
        bendDirection.normalize();
      }}

      const kneeAlongAxis = (
        (upperLength * upperLength) - (lowerLength * lowerLength) + (solvedDistance * solvedDistance)
      ) / (2 * solvedDistance);
      const kneeBendDistance = Math.sqrt(Math.max(
        (upperLength * upperLength) - (kneeAlongAxis * kneeAlongAxis),
        0
      ));
      const solvedKnee = root
        .clone()
        .addScaledVector(targetAxis, kneeAlongAxis)
        .addScaledVector(bendDirection, kneeBendDistance);
      return [root, solvedKnee, solvedAnkle];
    }}

    function toBaseWorldPoint(point, frameTranslation, applySceneOriginOffset = true, jointName = null) {{
      const lockedPositions = computeLockedJointPositions(activeRenderFrame, frameTranslation);
      const transformedPoint = typeof jointName === "string" && lockedPositions.has(jointName)
        ? lockedPositions.get(jointName).clone()
        : toUncorrectedWorldPoint(point, frameTranslation);
      if (applySceneOriginOffset && !suppressSceneOriginOffset) {{
        transformedPoint.sub(sceneOriginOffset);
      }}
      return transformedPoint;
    }}

    function toWorldPoint(point, frameTranslation, currentFixedRoot = fixedRoot, applySceneOriginOffset = true, jointName = null) {{
      return toBaseWorldPoint(point, frameTranslation, applySceneOriginOffset, jointName);
    }}

    function computeBakedWearBounds(frames) {{
      let minX = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      let minZ = Number.POSITIVE_INFINITY;
      let maxZ = Number.NEGATIVE_INFINITY;
      for (const frame of frames) {{
        for (const point of Object.values(frame.joints ?? {{}})) {{
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
      }}
      if (!Number.isFinite(minX) || !Number.isFinite(maxX)) {{
        minX = -0.5;
        maxX = 0.5;
        minY = -0.5;
        maxY = 0.5;
        minZ = -0.5;
        maxZ = 0.5;
      }}
      return {{
        minX,
        maxX,
        minY,
        maxY,
        minZ,
        maxZ,
        center: [
          (minX + maxX) * 0.5,
          (minY + maxY) * 0.5,
          (minZ + maxZ) * 0.5,
        ],
        size: [
          maxX - minX,
          maxY - minY,
          maxZ - minZ,
        ],
      }};
    }}

    function buildBakedWearSkeletonPayload() {{
      const activeFrames = playbackState.frames ?? [];
      const lockYDrift = Boolean(lockYRootInput.checked);
      getCachedSceneBounds(fixedRoot);
      const firstSourceTime = activeFrames.length > 0 ? activeFrames[0].timeSec : 0;
      const frames = activeFrames.map((frame, index) => {{
        activeRenderFrame = frame;
        const translation = getFrameBakeTranslation(frame, lockYDrift);
        const joints = {{}};
        for (const jointName of payload.jointNames) {{
          const point = frame.joints[jointName];
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          const transformed = toBaseWorldPoint(point, translation, true, jointName);
          joints[jointName] = [transformed.x, transformed.y, transformed.z];
        }}
        return {{
          frameIndex: index,
          sourceFrameIndex: Number.isInteger(frame.frameIndex) ? frame.frameIndex : index,
          timeSec: (frame.timeSec ?? 0) - firstSourceTime,
          sourceTimeSec: frame.timeSec ?? 0,
          rootTranslationApplied: translation,
          joints,
        }};
      }});
      const sourceStartFrame = frames.length > 0 ? frames[0].sourceFrameIndex : 0;
      const sourceEndFrame = frames.length > 0 ? frames[frames.length - 1].sourceFrameIndex : sourceStartFrame;
      const durationSec = frames.length > 1 ? frames[frames.length - 1].timeSec - frames[0].timeSec : 0;
      return {{
        schemaVersion: 1,
        kind: "wearPreviewSkeleton",
        title: payload.title,
        source: {{
          fps: payload.fps,
          frameCount: payload.frameCount,
          activeStartFrame: sourceStartFrame,
          activeEndFrame: sourceEndFrame,
        }},
        fps: payload.fps,
        frameCount: frames.length,
        durationSec,
        jointNames: payload.jointNames,
        rootJoint: payload.rootJoint,
        bakedPreviewConfiguration: {{
          autoWorldAlignment: autoWorldAlignmentEnabled,
          lockGlobalRootDrift: fixedRoot,
          lockYDrift,
          lockPlantedFeet,
          ankleLockTargetOffset: {{
            forward: ankleLockOffsetForward,
            lateral: ankleLockOffsetLateral,
            up: ankleLockOffsetUp,
          }},
          invertScene: sceneInverted,
          selectedLoopIndex,
        }},
        loop: {{
          enabled: currentLoop != null,
          startFrame: 0,
          endFrame: Math.max(0, frames.length - 1),
          sourceStartFrame,
          sourceEndFrame,
          durationSec,
          label: currentLoop?.label ?? "Full clip",
        }},
        transforms: {{
          autoAlignment: autoWorldAlignmentEnabled ? currentAutoAlignment : [],
          rootAnchor: activeRootAnchor ? [activeRootAnchor.x, activeRootAnchor.y, activeRootAnchor.z] : null,
          ankleLockTargetOffset: {{
            forward: ankleLockOffsetForward,
            lateral: ankleLockOffsetLateral,
            up: ankleLockOffsetUp,
          }},
          sceneOriginOffset: [sceneOriginOffset.x, sceneOriginOffset.y, sceneOriginOffset.z],
        }},
        bounds: computeBakedWearBounds(frames),
        topology: {{
          skeletonChains,
          capsules: payload.capsules,
        }},
        geometry: {{
          style: "low_poly_block_humanoid",
          limb: {{
            legWidth: 0.105,
            legDepth: 0.075,
            armWidth: 0.086,
            armDepth: 0.061,
          }},
          chainProfiles: [
            {{ match: "leg_bridge", minJointCount: 8, width: 0.14, depth: 0.09 }},
            {{ match: "spine_head", includesJoint: "head", width: 0.1, depth: 0.08 }},
            {{ match: "default", width: 0.08, depth: 0.055 }},
          ],
          head: {{
            minScale: 0.086,
            maxScale: 0.116,
            scale: [0.88, 1.08, 0.86],
          }},
        }},
        frames,
      }};
    }}

    function buildBakedSmplMeshPayload() {{
      const meshPayload = payload.smplMesh;
      if (!meshPayload || !Array.isArray(meshPayload.frames) || !Array.isArray(meshPayload.faces)) {{
        return null;
      }}
      const activeFrames = playbackState.frames ?? [];
      const lockYDrift = Boolean(lockYRootInput.checked);
      getCachedSceneBounds(fixedRoot);
      const firstSourceTime = activeFrames.length > 0 ? activeFrames[0].timeSec : 0;
      const frames = [];
      activeFrames.forEach((frame, index) => {{
        const meshFrame = findSmplMeshFrame(frame);
        if (!meshFrame || !Array.isArray(meshFrame.vertices)) {{
          return;
        }}
        activeRenderFrame = frame;
        const translation = getFrameBakeTranslation(frame, lockYDrift);
        const vertices = meshFrame.vertices.map((vertex) => {{
          const transformed = transformSmplVertex(vertex, frame, translation);
          return [transformed.x, transformed.y, transformed.z];
        }});
        frames.push({{
          frameIndex: frames.length,
          sourceFrameIndex: Number.isInteger(frame.frameIndex) ? frame.frameIndex : index,
          timeSec: (frame.timeSec ?? 0) - firstSourceTime,
          sourceTimeSec: frame.timeSec ?? 0,
          rootTranslationApplied: translation,
          vertices,
        }});
      }});
      smoothBakedSmplFrames(frames);
      const sourceStartFrame = frames.length > 0 ? frames[0].sourceFrameIndex : 0;
      const sourceEndFrame = frames.length > 0 ? frames[frames.length - 1].sourceFrameIndex : sourceStartFrame;
      const durationSec = frames.length > 1 ? frames[frames.length - 1].timeSec - frames[0].timeSec : 0;
      return {{
        schemaVersion: 1,
        kind: "whamBakedSmplMeshPreview",
        title: payload.title,
        bodyModel: meshPayload.bodyModel ?? "smpl",
        fps: payload.fps,
        frameCount: frames.length,
        durationSec,
        faces: meshPayload.faces,
        bakedPreviewConfiguration: {{
          autoWorldAlignment: autoWorldAlignmentEnabled,
          lockGlobalRootDrift: fixedRoot,
          lockYDrift,
          lockPlantedFeet,
          ankleLockTargetOffset: {{
            forward: ankleLockOffsetForward,
            lateral: ankleLockOffsetLateral,
            up: ankleLockOffsetUp,
          }},
          invertScene: sceneInverted,
          selectedLoopIndex,
          runtimeBaked: true,
          postProcessingApplied: [
            "cleanup_trim",
            "cleanup_global_translation_delta",
            "preview_refinement_alignment",
            "preview_root_lock",
            "preview_loop_selection",
            "preview_scene_centering",
            ...(lockPlantedFeet ? ["preview_leg_ik_vertex_blend"] : []),
          ],
        }},
        loop: {{
          enabled: currentLoop != null,
          startFrame: 0,
          endFrame: Math.max(0, frames.length - 1),
          sourceStartFrame,
          sourceEndFrame,
          durationSec,
          label: currentLoop?.label ?? "Full clip",
        }},
        transforms: {{
          autoAlignment: autoWorldAlignmentEnabled ? currentAutoAlignment : [],
          rootAnchor: activeRootAnchor ? [activeRootAnchor.x, activeRootAnchor.y, activeRootAnchor.z] : null,
          sceneOriginOffset: [sceneOriginOffset.x, sceneOriginOffset.y, sceneOriginOffset.z],
        }},
        bounds: computeBakedSmplBounds(frames),
        frames,
      }};
    }}

    function smoothBakedSmplFrames(frames) {{
      if (!Array.isArray(frames) || frames.length < 3) {{
        return;
      }}
      const sourceVertices = frames.map((frame) => frame.vertices ?? []);
      const weights = [1, 2, 3, 2, 1];
      const radius = 2;
      for (let frameIndex = 0; frameIndex < frames.length; frameIndex += 1) {{
        const vertices = sourceVertices[frameIndex];
        if (!Array.isArray(vertices) || vertices.length === 0) {{
          continue;
        }}
        const smoothedVertices = vertices.map((vertex, vertexIndex) => {{
          let totalWeight = 0;
          const smoothed = [0, 0, 0];
          for (let offset = -radius; offset <= radius; offset += 1) {{
            const neighborIndex = frameIndex + offset;
            if (neighborIndex < 0 || neighborIndex >= sourceVertices.length) {{
              continue;
            }}
            const neighbor = sourceVertices[neighborIndex]?.[vertexIndex];
            if (!Array.isArray(neighbor) || neighbor.length < 3) {{
              continue;
            }}
            const weight = weights[offset + radius];
            smoothed[0] += neighbor[0] * weight;
            smoothed[1] += neighbor[1] * weight;
            smoothed[2] += neighbor[2] * weight;
            totalWeight += weight;
          }}
          if (totalWeight <= 0) {{
            return vertex;
          }}
          return [
            smoothed[0] / totalWeight,
            smoothed[1] / totalWeight,
            smoothed[2] / totalWeight,
          ];
        }});
        frames[frameIndex] = {{
          ...frames[frameIndex],
          vertices: smoothedVertices,
        }};
      }}
    }}

    function computeBakedSmplBounds(frames) {{
      let minX = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      let minZ = Number.POSITIVE_INFINITY;
      let maxZ = Number.NEGATIVE_INFINITY;
      for (const frame of frames) {{
        for (const vertex of frame.vertices ?? []) {{
          if (!Array.isArray(vertex) || vertex.length < 3) {{
            continue;
          }}
          minX = Math.min(minX, vertex[0]);
          maxX = Math.max(maxX, vertex[0]);
          minY = Math.min(minY, vertex[1]);
          maxY = Math.max(maxY, vertex[1]);
          minZ = Math.min(minZ, vertex[2]);
          maxZ = Math.max(maxZ, vertex[2]);
        }}
      }}
      if (!Number.isFinite(minX) || !Number.isFinite(maxX)) {{
        minX = -0.5;
        maxX = 0.5;
        minY = -0.5;
        maxY = 0.5;
        minZ = -0.5;
        maxZ = 0.5;
      }}
      return {{
        minX,
        maxX,
        minY,
        maxY,
        minZ,
        maxZ,
        center: [
          (minX + maxX) * 0.5,
          (minY + maxY) * 0.5,
          (minZ + maxZ) * 0.5,
        ],
        size: [
          maxX - minX,
          maxY - minY,
          maxZ - minZ,
        ],
      }};
    }}

    function updateSmplMeshForFrame(frame) {{
      const meshPayload = payload.smplMesh;
      if (!meshPayload || !Array.isArray(meshPayload.frames) || !Array.isArray(meshPayload.faces)) {{
        smplMeshObject.visible = false;
        return;
      }}
      if (!showSmplMesh) {{
        smplMeshObject.visible = false;
        return;
      }}
      const meshFrame = findSmplMeshFrame(frame);
      if (!meshFrame || !Array.isArray(meshFrame.vertices)) {{
        smplMeshObject.visible = false;
        return;
      }}
      const frameTranslation = getFrameTranslation(frame);
      const positions = new Float32Array(meshFrame.vertices.length * 3);
      meshFrame.vertices.forEach((vertex, index) => {{
        const transformed = transformSmplVertex(vertex, frame, frameTranslation);
        positions[index * 3] = transformed.x;
        positions[index * 3 + 1] = transformed.y;
        positions[index * 3 + 2] = transformed.z;
      }});
      const indices = new Uint32Array(meshPayload.faces.length * 3);
      meshPayload.faces.forEach((face, index) => {{
        indices[index * 3] = Number(face[0]) || 0;
        indices[index * 3 + 1] = Number(face[1]) || 0;
        indices[index * 3 + 2] = Number(face[2]) || 0;
      }});
      const nextGeometry = new THREE.BufferGeometry();
      nextGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      nextGeometry.setIndex(new THREE.BufferAttribute(indices, 1));
      nextGeometry.computeVertexNormals();
      if (smplMeshGeometry) {{
        smplMeshGeometry.dispose();
      }}
      smplMeshGeometry = nextGeometry;
      smplMeshObject.geometry = nextGeometry;
      smplMeshObject.visible = true;
    }}

    function findSmplMeshFrame(frame) {{
      const frames = payload.smplMesh?.frames ?? [];
      if (frames.length === 0) {{
        return null;
      }}
      const sourceFrameIndex = Number.isInteger(frame.sourceFrameIndex)
        ? frame.sourceFrameIndex
        : Number.isInteger(frame.frameIndex)
        ? frame.frameIndex
        : null;
      if (sourceFrameIndex != null) {{
        const match = frames.find((candidate) => candidate.sourceFrameIndex === sourceFrameIndex);
        if (match) {{
          return match;
        }}
      }}
      const localIndex = Math.max(0, Math.min(frames.length - 1, Math.floor(frameCursor)));
      return frames[localIndex];
    }}

    function transformSmplVertex(vertex, frame, frameTranslation) {{
      const worldPoint = toUncorrectedWorldPoint(vertex, frameTranslation);
      if (lockPlantedFeet) {{
        worldPoint.add(computeSmplFootLockCorrection(worldPoint, frame, frameTranslation));
      }}
      if (!suppressSceneOriginOffset) {{
        worldPoint.sub(sceneOriginOffset);
      }}
      return worldPoint;
    }}

    function computeSmplFootLockCorrection(worldPoint, frame, frameTranslation) {{
      const lockedPositions = computeLockedJointPositions(frame, frameTranslation);
      if (!lockedPositions || lockedPositions.size === 0) {{
        return new THREE.Vector3();
      }}
      const weightedDelta = new THREE.Vector3();
      let totalWeight = 0;
      for (const side of ["left", "right"]) {{
        const chain = [`${{side}}_hip`, `${{side}}_knee`, `${{side}}_ankle`, `${{side}}_foot`];
        const points = chain
          .map((jointName) => {{
            const source = frame?.joints?.[jointName];
            if (!Array.isArray(source) || source.length < 3) {{
              return null;
            }}
            return {{
              jointName,
              original: toUncorrectedWorldPoint(source, frameTranslation),
              locked: lockedPositions.get(jointName) ?? null,
            }};
          }})
          .filter((entry) => entry != null && entry.locked != null);
        for (let index = 0; index < points.length - 1; index += 1) {{
          const start = points[index];
          const end = points[index + 1];
          const distance = pointToSegmentDistance(worldPoint, start.original, end.original);
          const radius = index === 0 ? 0.18 : 0.16;
          const normalizedDistance = Math.max(0, Math.min(1, distance / radius));
          const smoothFalloff = 1 - (normalizedDistance * normalizedDistance * (3 - 2 * normalizedDistance));
          const weight = smoothFalloff * smoothFalloff;
          if (weight <= 0) {{
            continue;
          }}
          const startDelta = start.locked.clone().sub(start.original);
          const endDelta = end.locked.clone().sub(end.original);
          const segmentDelta = startDelta.add(endDelta).multiplyScalar(0.5);
          weightedDelta.addScaledVector(segmentDelta, weight);
          totalWeight += weight;
        }}
      }}
      if (totalWeight <= 1e-8) {{
        return new THREE.Vector3();
      }}
      const averageDelta = weightedDelta.multiplyScalar(1 / totalWeight);
      const correction = averageDelta.multiplyScalar(Math.min(1, totalWeight));
      const maxCorrection = 0.075;
      if (correction.length() > maxCorrection) {{
        correction.setLength(maxCorrection);
      }}
      return correction;
    }}

    function pointToSegmentDistance(point, start, end) {{
      const segment = end.clone().sub(start);
      const lengthSq = segment.lengthSq();
      if (lengthSq <= 1e-8) {{
        return point.distanceTo(start);
      }}
      const t = Math.max(0, Math.min(1, point.clone().sub(start).dot(segment) / lengthSq));
      const projection = start.clone().addScaledVector(segment, t);
      return point.distanceTo(projection);
    }}

    function downloadBakedWearSkeleton() {{
      const exportPayload = buildBakedWearSkeletonPayload();
      const blob = new Blob([JSON.stringify(exportPayload, null, 2)], {{ type: "application/json" }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const loopLabel = selectedLoopIndex >= 0 ? `loop-${{selectedLoopIndex + 1}}` : "full-clip";
      const yLabel = lockYRootInput.checked ? "-lock-y" : "";
      const footLabel = lockPlantedFeetInput.checked ? "-lock-feet" : "";
      link.href = url;
      link.download = `${{payload.title}}-${{loopLabel}}${{yLabel}}${{footLabel}}.wear-skeleton.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }}

    function downloadBakedSmplMesh() {{
      const exportPayload = buildBakedSmplMeshPayload();
      if (!exportPayload) {{
        return;
      }}
      const blob = new Blob([JSON.stringify(exportPayload, null, 2)], {{ type: "application/json" }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const loopLabel = selectedLoopIndex >= 0 ? `loop-${{selectedLoopIndex + 1}}` : "full-clip";
      const yLabel = lockYRootInput.checked ? "-lock-y" : "";
      const footLabel = lockPlantedFeetInput.checked ? "-lock-feet" : "";
      link.href = url;
      link.download = `${{payload.title}}-${{loopLabel}}${{yLabel}}${{footLabel}}.wham-smpl-mesh.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }}

    function applyAutomationSettings(options = {{}}) {{
      if (Object.prototype.hasOwnProperty.call(options, "fixedRoot")) {{
        fixedRoot = Boolean(options.fixedRoot);
        fixedRootInput.checked = fixedRoot;
      }}
      if (Object.prototype.hasOwnProperty.call(options, "lockYDrift")) {{
        lockYRoot = Boolean(options.lockYDrift);
        lockYRootInput.checked = lockYRoot;
      }}
      if (Object.prototype.hasOwnProperty.call(options, "lockPlantedFeet")) {{
        lockPlantedFeet = Boolean(options.lockPlantedFeet);
        lockPlantedFeetInput.checked = lockPlantedFeet;
      }}
      if (Object.prototype.hasOwnProperty.call(options, "autoWorldAlignment")) {{
        autoWorldAlignmentEnabled = Boolean(options.autoWorldAlignment);
        autoWorldAlignmentInput.checked = autoWorldAlignmentEnabled;
      }}
      if (Object.prototype.hasOwnProperty.call(options, "sceneInverted")) {{
        sceneInverted = Boolean(options.sceneInverted);
        sceneInvertedInput.checked = sceneInverted;
      }}
      if (Object.prototype.hasOwnProperty.call(options, "showSmplMesh")) {{
        showSmplMesh = Boolean(options.showSmplMesh) && Boolean(payload.smplMesh);
        showSmplMeshInput.checked = showSmplMesh;
      }}
      if (Object.prototype.hasOwnProperty.call(options, "showBoundsHelper")) {{
        showBoundsHelper = Boolean(options.showBoundsHelper);
      }}
      if (options.ankleLockTargetOffset) {{
        const offset = options.ankleLockTargetOffset;
        if (Number.isFinite(Number(offset.forward))) {{
          ankleLockOffsetForward = Number(offset.forward);
          ankleOffsetForwardInput.value = String(ankleLockOffsetForward);
        }}
        if (Number.isFinite(Number(offset.lateral))) {{
          ankleLockOffsetLateral = Number(offset.lateral);
          ankleOffsetLateralInput.value = String(ankleLockOffsetLateral);
        }}
        if (Number.isFinite(Number(offset.up))) {{
          ankleLockOffsetUp = Number(offset.up);
          ankleOffsetUpInput.value = String(ankleLockOffsetUp);
        }}
        refreshAnkleLockOffsetLabels();
      }}
      invalidateSceneBoundsCache();
      activeRootAnchor = computeActiveRootAnchor(playbackState.boundsFrames);
      applySceneReframe();
      if (Number.isFinite(Number(options.cameraYawDegrees))) {{
        yaw = Number(options.cameraYawDegrees) * Math.PI / 180;
        cameraTouched = true;
      }}
      if (Number.isFinite(Number(options.cameraPitchDegrees))) {{
        pitch = Math.max(-1.2, Math.min(1.2, Number(options.cameraPitchDegrees) * Math.PI / 180));
        cameraTouched = true;
      }}
      refreshMergedBoundsHelper();
      updateCamera();
    }}

    function renderDeterministicFrame(frameIndex) {{
      const frames = playbackState.frames ?? [];
      const boundedIndex = Math.max(0, Math.min(Math.max(0, frames.length - 1), Math.floor(Number(frameIndex) || 0)));
      paused = true;
      refreshPauseLabel();
      frameCursor = boundedIndex;
      draw();
      return renderer.domElement.toDataURL("image/png");
    }}

    window.exerciseMotionAutomation = {{
      getPayloadSummary() {{
        return {{
          title: payload.title,
          fps: payload.fps,
          frameCount: payload.frameCount,
          detectedLoops,
          selectedLoopIndex,
        }};
      }},
      configure(options = {{}}) {{
        applyAutomationSettings(options);
        return this.getPayloadSummary();
      }},
      selectLoop(loopIndex) {{
        const nextIndex = Number(loopIndex);
        if (!Number.isInteger(nextIndex) || nextIndex < -1 || nextIndex >= detectedLoops.length) {{
          throw new Error(`Invalid loop index: ${{loopIndex}}`);
        }}
        setSelectedLoop(nextIndex);
        loopSelect.value = String(selectedLoopIndex);
        return this.getPayloadSummary();
      }},
      exportWearSkeleton(options = {{}}) {{
        applyAutomationSettings(options);
        return buildBakedWearSkeletonPayload();
      }},
      bakeLoop(loopIndex, options = {{}}) {{
        this.selectLoop(loopIndex);
        return this.exportWearSkeleton(options);
      }},
      renderFrame(frameIndex, options = {{}}) {{
        applyAutomationSettings(options);
        return renderDeterministicFrame(frameIndex);
      }},
    }};

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
      mesh.visible = true;
      mesh.position.copy(center);
      applyStableMeshOrientation(mesh, xDir, yDir, zDir);
        mesh.scale.set(
          Math.max(0.001, width),
          Math.max(0.001, height),
          Math.max(0.001, depth)
        );
      }}

      function setOrientedCylinder(mesh, start, end, radius, lateralAxis = null) {{
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
        const yDir = tempVector.clone().normalize();
        let xDir = lateralAxis
          ? projectedAxis(lateralAxis, yDir)
          : null;
        if (!xDir) {{
          xDir = projectedAxis(sceneRight, yDir) ?? projectedAxis(sceneForward, yDir);
        }}
        if (!xDir) {{
          mesh.visible = false;
          return;
        }}
        const zDir = new THREE.Vector3().crossVectors(xDir, yDir).normalize();
        if (zDir.lengthSq() <= 1e-8) {{
          mesh.visible = false;
          return;
        }}
        xDir = new THREE.Vector3().crossVectors(yDir, zDir).normalize();
        tempMidpoint.copy(start).add(end).multiplyScalar(0.5);
        mesh.visible = true;
        mesh.position.copy(tempMidpoint);
        applyStableMeshOrientation(mesh, xDir, yDir, zDir);
        mesh.scale.set(Math.max(0.001, radius), Math.max(0.001, length), Math.max(0.001, radius));
      }}

      function chooseRollStableQuaternion(previousQuaternion, xDir, yDir, zDir) {{
        const candidateMatrixA = new THREE.Matrix4().makeBasis(xDir, yDir, zDir);
        const candidateMatrixB = new THREE.Matrix4().makeBasis(
          xDir.clone().multiplyScalar(-1),
          yDir,
          zDir.clone().multiplyScalar(-1)
        );
        const candidateA = new THREE.Quaternion().setFromRotationMatrix(candidateMatrixA);
        const candidateB = new THREE.Quaternion().setFromRotationMatrix(candidateMatrixB);
        if (!previousQuaternion) {{
          return candidateA;
        }}
        const dotA = Math.abs(candidateA.dot(previousQuaternion));
        const dotB = Math.abs(candidateB.dot(previousQuaternion));
        return dotB > dotA ? candidateB : candidateA;
      }}

      function applyStableMeshOrientation(mesh, xDir, yDir, zDir) {{
        const previousQuaternion = mesh.userData.previousQuaternion ?? null;
        const resolvedQuaternion = chooseRollStableQuaternion(previousQuaternion, xDir, yDir, zDir);
        mesh.quaternion.copy(resolvedQuaternion);
        mesh.userData.previousQuaternion = resolvedQuaternion.clone();
      }}

      function setOrientedLimbBox(mesh, start, end, lateralAxis, width, depth) {{
        if (!start || !end) {{
          mesh.visible = false;
          return;
        }}
        const yDir = end.clone().sub(start);
        const length = yDir.length();
        if (length <= 1e-6) {{
          mesh.visible = false;
          return;
        }}
        yDir.normalize();
        let xDir = projectedAxis(lateralAxis, yDir);
        if (!xDir) {{
          xDir = projectedAxis(sceneRight, yDir) ?? projectedAxis(sceneForward, yDir);
        }}
        if (!xDir) {{
          mesh.visible = false;
          return;
        }}
        const zDir = new THREE.Vector3().crossVectors(xDir, yDir).normalize();
        if (zDir.lengthSq() <= 1e-8) {{
          mesh.visible = false;
          return;
        }}
        xDir = new THREE.Vector3().crossVectors(yDir, zDir).normalize();
        tempMidpoint.copy(start).add(end).multiplyScalar(0.5);
        mesh.visible = true;
        mesh.position.copy(tempMidpoint);
        applyStableMeshOrientation(mesh, xDir, yDir, zDir);
        mesh.scale.set(
          Math.max(0.001, width),
          Math.max(0.001, length),
          Math.max(0.001, depth)
        );
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
        mesh.visible = true;
        mesh.position.copy(center);
        applyStableMeshOrientation(mesh, xDir, yDir, zDir);
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
        mesh.visible = true;
        mesh.position.copy(center);
        applyStableMeshOrientation(mesh, xDir, yDir, zDir);
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
        coreShellMesh.visible = false;
        for (const mesh of spineMeshes) {{
          mesh.visible = false;
        }}
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

      function hideConnectedSkeleton() {{
        for (const entry of skeletonLines) {{
          entry.line.visible = false;
        }}
        for (const entry of skeletonSurfaces) {{
          entry.mesh.visible = false;
        }}
        for (const entry of jointNodeMeshes) {{
          entry.mesh.visible = false;
        }}
      }}

      function updateConnectedSkeleton(frame, frameTranslation) {{
        for (const entry of skeletonLines) {{
          const points = entry.jointNames
            .map((jointName) => frame.joints[jointName]
              ? toWorldPoint(frame.joints[jointName], frameTranslation, fixedRoot, true, jointName)
              : null)
            .filter((point) => point != null);
          if (points.length < 2) {{
            entry.line.visible = false;
            continue;
          }}
          entry.line.visible = true;
          entry.line.geometry.setFromPoints(points);
          entry.line.geometry.computeBoundingSphere();
        }}
        for (const entry of skeletonSurfaces) {{
          const points = entry.jointNames
            .map((jointName) => frame.joints[jointName]
              ? toWorldPoint(frame.joints[jointName], frameTranslation, fixedRoot, true, jointName)
              : null)
            .filter((point) => point != null);
          if (points.length < 2) {{
            entry.mesh.visible = false;
            continue;
          }}
          const curve = new THREE.CatmullRomCurve3(points);
          const profile = chainProfileDimensions(entry.jointNames);
          const nextGeometry = new THREE.ExtrudeGeometry(
            buildProfileShape(profile.width, profile.depth),
            {{
              steps: Math.max(8, points.length * 4),
              bevelEnabled: false,
              extrudePath: curve,
            }}
          );
          entry.mesh.visible = true;
          entry.mesh.geometry.dispose();
          entry.mesh.geometry = nextGeometry;
        }}
        for (const entry of jointNodeMeshes) {{
          const point = frame.joints[entry.jointName]
            ? toWorldPoint(frame.joints[entry.jointName], frameTranslation, fixedRoot, true, entry.jointName)
            : null;
          if (!point) {{
            entry.mesh.visible = false;
            continue;
          }}
          entry.mesh.visible = true;
          entry.mesh.position.copy(point);
          const scale = entry.jointName === "head"
            ? 0.028
            : entry.jointName === "pelvis"
              ? 0.022
              : 0.011;
          entry.mesh.scale.setScalar(scale);
        }}
      }}

    function getFrameJointWorld(frame, frameTranslation, jointName) {{
      const point = frame.joints[jointName];
      return point ? toWorldPoint(point, frameTranslation, fixedRoot, true, jointName) : null;
    }}

    function getCameraFitDistance() {{
      const bounds = getCachedSceneBounds(fixedRoot);
      const width = Math.max(0.001, bounds.maxX - bounds.minX);
      const height = Math.max(0.001, bounds.maxY - bounds.minY);
      const depth = Math.max(0.001, bounds.maxZ - bounds.minZ);
      const verticalFov = THREE.MathUtils.degToRad(perspectiveCamera.fov);
      const horizontalFov = 2 * Math.atan(Math.tan(verticalFov * 0.5) * perspectiveCamera.aspect);
      const fitHeightDistance = height * 0.5 / Math.tan(verticalFov * 0.5);
      const fitWidthDistance = width * 0.5 / Math.tan(horizontalFov * 0.5);
      return Math.max(0.7, fitHeightDistance, fitWidthDistance, depth * 1.1);
    }}

    function updateCamera() {{
      const zoomScale = 240 / Math.max(120, zoom);
      const distance = getCameraFitDistance() * zoomScale * 1.18;
      const horizontalDistance = Math.cos(pitch) * distance;
      refreshSceneBasis();
      perspectiveCamera.position.copy(cameraTarget)
        .addScaledVector(sceneRight, Math.sin(yaw) * horizontalDistance)
        .addScaledVector(sceneForward, Math.cos(yaw) * horizontalDistance)
        .addScaledVector(sceneUp, Math.sin(pitch) * distance);
      perspectiveCamera.up.copy(sceneUp);
      perspectiveCamera.lookAt(cameraTarget);
    }}

    function getInterpolatedFrame() {{
      const frames = playbackState.frames;
      if (frames.length === 0) {{
        return null;
      }}
      const normalizedCursor = playbackState.loopable
        ? ((frameCursor % frames.length) + frames.length) % frames.length
        : Math.max(0, Math.min(frames.length - 1, frameCursor));
      const baseIndex = Math.max(0, Math.min(frames.length - 1, Math.floor(normalizedCursor)));
      const nextIndex = playbackState.loopable
        ? (baseIndex + 1) % frames.length
        : Math.max(0, Math.min(frames.length - 1, baseIndex + 1));
      const alpha = normalizedCursor - Math.floor(normalizedCursor);
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
        activeRenderFrame = frame;
        const frameTranslation = getFrameTranslation(frame);
        hideConnectedSkeleton();
        proceduralBodyMeshes.forEach((mesh) => {{
          mesh.visible = !showSmplMesh;
        }});
        updateSmplMeshForFrame(frame);
        if (showSmplMesh && smplMeshObject.visible) {{
          return;
        }}
      const pelvisJoint = getFrameJointWorld(frame, frameTranslation, "pelvis");
      const spine1Joint = getFrameJointWorld(frame, frameTranslation, "spine1");
      const spine2Joint = getFrameJointWorld(frame, frameTranslation, "spine2");
      const spine3Joint = getFrameJointWorld(frame, frameTranslation, "spine3");
      const neckJoint = getFrameJointWorld(frame, frameTranslation, "neck");
      const leftHipJoint = getFrameJointWorld(frame, frameTranslation, "left_hip");
      const rightHipJoint = getFrameJointWorld(frame, frameTranslation, "right_hip");
      const leftShoulderJoint = getFrameJointWorld(frame, frameTranslation, "left_shoulder");
      const rightShoulderJoint = getFrameJointWorld(frame, frameTranslation, "right_shoulder");
      const hipAxis = leftHipJoint && rightHipJoint
        ? rightHipJoint.clone().sub(leftHipJoint)
        : null;
      const shoulderAxis = leftShoulderJoint && rightShoulderJoint
        ? rightShoulderJoint.clone().sub(leftShoulderJoint)
        : null;

      if (pelvisJoint && leftHipJoint && rightHipJoint && spine1Joint) {{
        const hipCenter = leftHipJoint.clone().add(rightHipJoint).multiplyScalar(0.5);
          const pelvisCenter = hipCenter.clone().lerp(pelvisJoint, 0.44);
          const hipAxis = rightHipJoint.clone().sub(leftHipJoint);
          const pelvisHeight = Math.max(0.105, pelvisJoint.distanceTo(hipCenter) * 1.32);
          const pelvisWidth = Math.max(0.165, hipAxis.length() * 1.08);
            setOrientedFrameVolume(
              pelvisMesh,
              pelvisCenter,
              hipAxis,
              spine1Joint.clone().sub(hipCenter),
              pelvisWidth,
              pelvisHeight,
              pelvisWidth * 0.78
            );
        }} else {{
          pelvisMesh.visible = false;
        }}

        let coreShellVisible = false;
        if (pelvisJoint && spine1Joint && spine2Joint && neckJoint && hipAxis && shoulderAxis) {{
          const hipCenter = leftHipJoint && rightHipJoint
            ? leftHipJoint.clone().add(rightHipJoint).multiplyScalar(0.5)
            : pelvisJoint;
          const shoulderCenter = leftShoulderJoint.clone().add(rightShoulderJoint).multiplyScalar(0.5);
          const spineAxis = neckJoint.clone().sub(pelvisJoint);
          const shellForwardAxis = new THREE.Vector3().crossVectors(shoulderAxis, spineAxis);
          if (shellForwardAxis.lengthSq() > 1e-8) {{
            shellForwardAxis.normalize();
            const hipWidth = hipAxis.length();
            const shoulderWidth = shoulderAxis.length();
            const rings = [
              {{
                center: hipCenter.clone().lerp(pelvisJoint, 0.42),
                xAxis: hipAxis,
                zAxis: shellForwardAxis,
                width: Math.max(0.15, hipWidth * 0.96),
                depth: Math.max(0.11, hipWidth * 0.62),
              }},
              {{
                center: spine1Joint.clone().lerp(spine2Joint, 0.18),
                xAxis: shoulderAxis,
                zAxis: shellForwardAxis,
                width: Math.max(0.12, shoulderWidth * 0.42),
                depth: Math.max(0.1, shoulderWidth * 0.34),
              }},
              {{
                center: spine2Joint.clone().lerp(shoulderCenter, 0.38),
                xAxis: shoulderAxis,
                zAxis: shellForwardAxis,
                width: Math.max(0.17, shoulderWidth * 0.72),
                depth: Math.max(0.12, shoulderWidth * 0.42),
              }},
              {{
                center: shoulderCenter.clone().lerp(neckJoint, 0.1),
                xAxis: shoulderAxis,
                zAxis: shellForwardAxis,
                width: Math.max(0.2, shoulderWidth * 0.88),
                depth: Math.max(0.12, shoulderWidth * 0.38),
              }},
            ];
            const nextCoreGeometry = createCoreShellGeometry(rings);
            if (nextCoreGeometry) {{
              coreShellMesh.visible = true;
              replaceOutlinedGeometry(coreShellMesh, nextCoreGeometry);
              coreShellVisible = true;
            }}
          }}
        }}
        if (!coreShellVisible) {{
          coreShellMesh.visible = false;
        }}

          const spineSegments = [
            [pelvisJoint, spine1Joint],
            [spine1Joint, spine2Joint],
            [spine2Joint, spine3Joint ?? neckJoint],
          ];
        const spineLateralAxis = shoulderAxis ?? hipAxis;
        spineSegments.forEach((segment, index) => {{
          const [segmentStart, segmentEnd] = segment;
          const mesh = spineMeshes[index];
          if (coreShellVisible) {{
            mesh.visible = false;
            return;
          }}
          if (!segmentStart || !segmentEnd || !spineLateralAxis) {{
            mesh.visible = false;
            return;
          }}
          const segmentAxis = segmentEnd.clone().sub(segmentStart);
          const segmentLength = segmentAxis.length();
          if (segmentLength < 1e-4) {{
            mesh.visible = false;
            return;
          }}
          const spineWidth = Math.max(0.055, (index === 0 ? hipAxis?.length() ?? 0 : shoulderAxis?.length() ?? 0) * 0.2);
          setOrientedFrameVolume(
            mesh,
            segmentStart.clone().lerp(segmentEnd, 0.5),
            spineLateralAxis,
            segmentAxis,
            spineWidth,
            Math.max(0.055, segmentLength * 0.82),
            spineWidth * 0.84
          );
        }});
        if (spineSegments.length < spineMeshes.length) {{
          spineMeshes.slice(spineSegments.length).forEach((mesh) => {{
            mesh.visible = false;
          }});
        }}

          if (spine1Joint && spine2Joint && leftShoulderJoint && rightShoulderJoint) {{
            const shoulderAxis = rightShoulderJoint.clone().sub(leftShoulderJoint);
            const abdomenHeight = spine1Joint.distanceTo(spine2Joint);
            const abdomenWidth = Math.max(0.11, shoulderAxis.length() * 0.28);
          if (coreShellVisible) {{
            abdomenMesh.visible = false;
          }} else {{
          setOrientedFrameVolume(
            abdomenMesh,
            spine1Joint.clone().lerp(spine2Joint, 0.42),
            shoulderAxis,
            spine2Joint.clone().sub(spine1Joint),
            abdomenWidth,
            Math.max(0.12, abdomenHeight * 0.86),
            abdomenWidth * 0.84
          );
          }}
        }} else {{
          abdomenMesh.visible = false;
        }}
  
          if (spine2Joint && neckJoint && leftShoulderJoint && rightShoulderJoint) {{
            const shoulderCenter = leftShoulderJoint.clone().add(rightShoulderJoint).multiplyScalar(0.5);
            const chestCenter = shoulderCenter.clone().lerp(spine2Joint, 0.52);
            const shoulderAxis = rightShoulderJoint.clone().sub(leftShoulderJoint);
            const chestAxis = neckJoint.clone().sub(spine2Joint);
            const shoulderSpan = shoulderAxis.length();
            const chestWidth = Math.max(0.18, shoulderSpan * 0.76);
            const chestHeight = Math.max(0.18, chestAxis.length() * 0.96);
            const chestDepth = Math.max(0.105, chestWidth * 0.56);
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
              Math.max(0.045, chestWidth * 0.11),
              shoulderAxis
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
          const startVector = toWorldPoint(start, frameTranslation, fixedRoot, true, node.capsule.start);
          const endVector = toWorldPoint(end, frameTranslation, fixedRoot, true, node.capsule.end);
          tempVector.subVectors(endVector, startVector);
          const fullLength = tempVector.length();
          const direction = tempVector.clone().normalize();
          if (fullLength < 1e-4) {{
          node.mesh.visible = false;
            continue;
          }}
          const radius = node.capsule.radius;
        const limbProfile = limbProfileForCapsule(node.capsule, radius);
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
        if (isLegCapsule(node.capsule) && hipAxis) {{
          setOrientedLimbBox(
            node.mesh,
            startInset,
            endInset,
            hipAxis,
            limbProfile.width,
            limbProfile.depth
          );
          continue;
        }}
        if (shoulderAxis && isArmCapsule(node.capsule)) {{
          setOrientedLimbBox(
            node.mesh,
            startInset,
            endInset,
            shoulderAxis,
            limbProfile.width,
            limbProfile.depth
          );
          continue;
        }}
        setOrientedCylinder(
          node.mesh,
          startInset,
          endInset,
          Math.max(limbProfile.width, limbProfile.depth) * 0.5,
          shoulderAxis ?? hipAxis ?? sceneRight
        );
        }}

      const headJointName = frame.joints.head ? "head" : frame.joints.neck ? "neck" : null;
      const headJoint = headJointName ? getFrameJointWorld(frame, frameTranslation, headJointName) : null;
      if (headJoint) {{
        headMesh.visible = true;
        const neckSourceJoint = getFrameJointWorld(frame, frameTranslation, "neck");
        const headAxis = neckSourceJoint ? headJoint.clone().sub(neckSourceJoint) : axisY.clone();
        const headCenter = neckSourceJoint
          ? neckSourceJoint.clone().lerp(headJoint, 0.82)
          : headJoint.clone();
        const headScale = neckSourceJoint
            ? Math.max(0.115, Math.min(0.165, headJoint.distanceTo(neckSourceJoint) * 0.68))
            : 0.135;
        setOrientedFrameVolume(
          headMesh,
          headCenter,
          shoulderAxis ?? hipAxis ?? sceneRight,
          headAxis.lengthSq() > 1e-8 ? headAxis : axisY,
          headScale * 0.86,
          headScale * 1.16,
          headScale * 0.78
        );
      }} else {{
        headMesh.visible = false;
      }}
    }}

    function draw() {{
      const frame = getInterpolatedFrame();
      if (!frame) {{
        return;
      }}
      updateSceneForFrame(frame);
      updateCamera();
      frameIndexNode.textContent = String(Math.max(0, Math.min(playbackState.frames.length - 1, Math.floor(frameCursor))));
      renderer.render(scene, perspectiveCamera);
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
            while (frameCursor >= playbackState.frames.length) {{
              frameCursor -= playbackState.frames.length;
            }}
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
      cameraTouched = true;
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
      cameraTouched = true;
      yaw -= deltaX * 0.01;
      pitch = Math.max(-1.2, Math.min(1.2, pitch - deltaY * 0.01));
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
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    lockYRootInput.addEventListener("change", () => {{
      lockYRoot = lockYRootInput.checked;
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    lockPlantedFeetInput.addEventListener("change", () => {{
      lockPlantedFeet = lockPlantedFeetInput.checked;
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    function updateAnkleLockOffset() {{
      ankleLockOffsetForward = parseFloat(ankleOffsetForwardInput.value);
      ankleLockOffsetLateral = parseFloat(ankleOffsetLateralInput.value);
      ankleLockOffsetUp = parseFloat(ankleOffsetUpInput.value);
      refreshAnkleLockOffsetLabels();
      if (lockPlantedFeet) {{
        invalidateSceneBoundsCache();
        applySceneReframe();
      }}
    }}
    ankleOffsetForwardInput.addEventListener("input", updateAnkleLockOffset);
    ankleOffsetLateralInput.addEventListener("input", updateAnkleLockOffset);
    ankleOffsetUpInput.addEventListener("input", updateAnkleLockOffset);
    autoWorldAlignmentInput.addEventListener("change", () => {{
      autoWorldAlignmentEnabled = autoWorldAlignmentInput.checked;
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    sceneInvertedInput.addEventListener("change", () => {{
      sceneInverted = sceneInvertedInput.checked;
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    showSmplMeshInput.addEventListener("change", () => {{
      showSmplMesh = showSmplMeshInput.checked && Boolean(payload.smplMesh);
      refreshSceneFrame();
    }});
    loopSelect.addEventListener("change", () => {{
      setSelectedLoop(parseInt(loopSelect.value, 10));
    }});
    downloadWearSkeletonButton.addEventListener("click", () => {{
      downloadBakedWearSkeleton();
    }});
    downloadSmplMeshButton.addEventListener("click", () => {{
      downloadBakedSmplMesh();
    }});
    zoomInput.addEventListener("input", () => {{
      cameraTouched = true;
      zoom = parseFloat(zoomInput.value);
      resize();
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
    refreshPauseLabel();
    activeRootAnchor = computeActiveRootAnchor(playbackState.boundsFrames);
    frameCursor = findFrameCursorClosestToBoundsCenter();
    refreshSceneFrame();
    resize();
    draw();
    requestAnimationFrame(animate);
    </script>
</body>
</html>
"""
