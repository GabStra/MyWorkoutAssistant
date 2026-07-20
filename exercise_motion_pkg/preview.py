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
PREVIEW_BONE_CHAINS_ROOT_OUTWARD = (
    ("pelvis", "spine1", "spine2", "spine3", "neck", "head"),
    ("neck", "left_collar", "left_shoulder", "left_elbow", "left_wrist", "left_hand"),
    ("neck", "right_collar", "right_shoulder", "right_elbow", "right_wrist", "right_hand"),
    ("pelvis", "left_hip", "left_knee", "left_ankle", "left_foot"),
    ("pelvis", "right_hip", "right_knee", "right_ankle", "right_foot"),
)

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
BILATERAL_SYMMETRY_FULL_BLEND_MAX_BODY_RATIO = 0.08
BILATERAL_SYMMETRY_REJECT_BODY_RATIO = 0.14
BILATERAL_SYMMETRY_MAX_FRAME_BODY_RATIO = 0.20
CENTERLINE_PROJECTION_FULL_BLEND_MAX_BODY_RATIO = 0.03
CENTERLINE_PROJECTION_REJECT_BODY_RATIO = 0.08
HINGE_LIMITS = (
    ("left_shoulder", "left_elbow", "left_wrist", math.radians(15.0), math.radians(175.0), ("left_wrist", "left_hand")),
    ("right_shoulder", "right_elbow", "right_wrist", math.radians(15.0), math.radians(175.0), ("right_wrist", "right_hand")),
    ("left_hip", "left_knee", "left_ankle", math.radians(20.0), math.radians(175.0), ("left_ankle", "left_foot")),
    ("right_hip", "right_knee", "right_ankle", math.radians(20.0), math.radians(175.0), ("right_ankle", "right_foot")),
)
MIN_LOOP_DURATION_SECONDS = 2.0
MAX_DETECTED_LOOPS = 8
MIN_PREVIEW_LOOP_MOTION_BODY_RATIO = 0.08
MAX_PREVIEW_LOOP_BOUNDARY_SAMPLES = 80
MAX_PREVIEW_LOOP_MOTION_SAMPLES = 24
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
BAKED_SAGITTAL_PLANE_TARGET_AXIS = "positive_x"
BAKED_SAGITTAL_PLANE_TARGET_FORWARD = (1.0, 0.0)
BAKED_SAGITTAL_PLANE_TARGET_NORMAL = (0.0, 1.0)
BAKED_SAGITTAL_PLANE_ALIGNMENT_MIN_DEGREES = 0.5
BAKED_SAGITTAL_PLANE_ALIGNMENT_PAIRS = (
    ("left_shoulder", "right_shoulder", 2.0),
    ("left_collar", "right_collar", 1.5),
    ("left_hip", "right_hip", 1.8),
)
MOVEMENT_PLANE_ALIGNMENT_MIN_RANGE_RATIO = 0.035
MOVEMENT_PLANE_ALIGNMENT_MIN_COHERENCE = 0.55
MOVEMENT_PLANE_ALIGNMENT_MIN_CONFIDENCE = 0.58
MOVEMENT_PLANE_ALIGNMENT_GROUPS = (
    ("shoulder_center", ("left_shoulder", "right_shoulder", "left_collar", "right_collar", "neck", "spine3"), False, 1.35),
    ("torso", ("pelvis", "spine1", "spine2", "spine3", "neck", "left_hip", "right_hip", "left_shoulder", "right_shoulder"), False, 1.25),
    ("hip_center", ("pelvis", "left_hip", "right_hip"), False, 1.10),
    ("upper_body_relative", ("left_shoulder", "right_shoulder", "left_collar", "right_collar", "neck", "spine3"), True, 1.05),
    ("left_arm_relative", ("left_shoulder", "left_elbow", "left_wrist", "left_hand"), True, 0.95),
    ("right_arm_relative", ("right_shoulder", "right_elbow", "right_wrist", "right_hand"), True, 0.95),
    ("left_leg_relative", ("left_hip", "left_knee", "left_ankle", "left_foot"), True, 0.92),
    ("right_leg_relative", ("right_hip", "right_knee", "right_ankle", "right_foot"), True, 0.92),
    ("hand_center_relative", ("left_hand", "right_hand", "left_wrist", "right_wrist"), True, 0.86),
    ("foot_center_relative", ("left_foot", "right_foot", "left_ankle", "right_ankle"), True, 0.80),
)
MOVEMENT_PLANE_ALIGNMENT_JOINTS = (
    ("left_shoulder", True, 0.90),
    ("right_shoulder", True, 0.90),
    ("left_elbow", True, 0.86),
    ("right_elbow", True, 0.86),
    ("left_wrist", True, 0.82),
    ("right_wrist", True, 0.82),
    ("left_hand", True, 0.82),
    ("right_hand", True, 0.82),
    ("left_knee", True, 0.84),
    ("right_knee", True, 0.84),
    ("left_ankle", True, 0.78),
    ("right_ankle", True, 0.78),
    ("left_foot", True, 0.76),
    ("right_foot", True, 0.76),
)
DOMINANT_MOVEMENT_AXIS_JOINTS = (
    "left_hand",
    "right_hand",
    "left_wrist",
    "right_wrist",
    "left_elbow",
    "right_elbow",
    "left_foot",
    "right_foot",
    "left_ankle",
    "right_ankle",
    "left_knee",
    "right_knee",
    "head",
    "neck",
    "spine3",
)
DOMINANT_MOVEMENT_AXIS_GROUPS = (
    ("shoulder_center", ("left_shoulder", "right_shoulder"), False, 1.15),
    ("upper_body", ("left_shoulder", "right_shoulder", "left_collar", "right_collar", "neck", "spine3"), False, 1.10),
    ("torso", ("pelvis", "spine1", "spine2", "spine3", "neck"), False, 1.00),
    ("hip_center", ("left_hip", "right_hip", "pelvis"), False, 0.95),
    ("arm_center", ("left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist"), False, 0.88),
    ("hand_center", ("left_hand", "right_hand", "left_wrist", "right_wrist"), False, 0.86),
    ("knee_center", ("left_knee", "right_knee"), False, 0.84),
    ("ankle_center", ("left_ankle", "right_ankle"), False, 0.80),
    ("foot_center", ("left_foot", "right_foot"), False, 0.78),
    ("left_arm_relative", ("left_shoulder", "left_elbow", "left_wrist", "left_hand"), True, 0.90),
    ("right_arm_relative", ("right_shoulder", "right_elbow", "right_wrist", "right_hand"), True, 0.90),
    ("hand_center_relative", ("left_hand", "right_hand", "left_wrist", "right_wrist"), True, 0.88),
    ("left_leg_relative", ("left_hip", "left_knee", "left_ankle", "left_foot"), True, 0.86),
    ("right_leg_relative", ("right_hip", "right_knee", "right_ankle", "right_foot"), True, 0.86),
    ("knee_center_relative", ("left_knee", "right_knee"), True, 0.84),
    ("ankle_center_relative", ("left_ankle", "right_ankle"), True, 0.82),
    ("foot_center_relative", ("left_foot", "right_foot"), True, 0.80),
)
DOMINANT_MOVEMENT_AXIS_MIN_RANGE = 0.035
DOMINANT_MOVEMENT_AXIS_VERTICAL_RATIO = 1.25
DOMINANT_MOVEMENT_AXIS_MIN_HORIZONTAL_RANGE = 0.025


def write_preview_html(
    path: Path,
    clip: MotionClip,
    *,
    title: str,
    debug_json_path: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_motion_review = _clip_requests_raw_motion_render(clip)
    preview_clip = _center_preview_clip_for_render(_prepare_preview_clip(clip))
    has_horizontal_torso_profile = _has_horizontal_torso_profile(preview_clip.frames)
    default_auto_alignment_rotations = _compute_preview_auto_alignment(preview_clip.frames)
    default_auto_alignment = _serialize_preview_rotations(default_auto_alignment_rotations)
    default_scene_inverted = _aligned_body_points_down(preview_clip.frames, default_auto_alignment_rotations)
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
        "defaultFixedRoot": not raw_motion_review,
        "rootTranslationToggleLabel": (
            "Show original camera-space translation"
            if preview_clip.metadata.get("upstream") == "gvhmr"
            else "Lock global root drift"
        ) if isinstance(preview_clip.metadata, dict) else "Lock global root drift",
        "defaultSceneInverted": default_scene_inverted,
        "defaultAutoWorldAlignment": not raw_motion_review,
        "defaultAutoAlignment": default_auto_alignment,
        "defaultCameraYawDegrees": 180.0 if has_horizontal_torso_profile else 0.0,
        "defaultCameraPitchDegrees": 0.0 if has_horizontal_torso_profile else 10.3,
        "horizontalTorsoProfile": has_horizontal_torso_profile,
        "previewMaxRenderFps": min(30.0, max(12.0, float(preview_clip.fps))),
        "motionTuningEnabled": not raw_motion_review,
        "rawWhamPassthrough": raw_motion_review,
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
        "groundVisualClearance": UNIFORM_CAPSULE_RADIUS,
        "spineposeMotionFusion": (
            clip.metadata.get("spineposeMotionFusion")
            if isinstance(clip.metadata, dict) and isinstance(clip.metadata.get("spineposeMotionFusion"), dict)
            else {}
        ),
        "comparisonFrames": _build_preview_comparison_frames(clip, preview_clip),
        "rawComparisonFrames": _build_preview_raw_comparison_frames(clip),
        "structuralRefinement": (
            clip.metadata.get("structuralRefinement")
            if isinstance(clip.metadata, dict) and isinstance(clip.metadata.get("structuralRefinement"), dict)
            else {}
        ),
    }
    html = _build_html(payload)
    path.write_text(html, encoding="utf-8")


def _build_preview_comparison_frames(source_clip: MotionClip, preview_clip: MotionClip) -> list[dict[str, object]]:
    metadata = source_clip.metadata if isinstance(source_clip.metadata, dict) else {}
    refinement = metadata.get("structuralRefinement")
    if not isinstance(refinement, dict):
        return []
    input_frames = refinement.get("inputFrames")
    if not isinstance(input_frames, list) or len(input_frames) != preview_clip.frame_count:
        return []
    frames: list[MotionFrame] = []
    for item in input_frames:
        if not isinstance(item, dict):
            return []
        joints_payload = item.get("joints")
        if not isinstance(joints_payload, dict):
            return []
        joints = {
            str(joint_name): (float(point[0]), float(point[1]), float(point[2]))
            for joint_name, point in joints_payload.items()
            if isinstance(point, list) and len(point) >= 3
        }
        frames.append(MotionFrame(time_sec=float(item.get("timeSec", 0.0)), joints=joints))
    frames = _stabilize_preview_comparison_frames(
        source_frames=frames,
        preview_clip=preview_clip,
        refinement=refinement,
    )
    comparison_clip = _center_preview_clip_for_render(refine_motion_clip_for_preview(
        MotionClip(
            fps=source_clip.fps,
            joint_names=source_clip.joint_names,
            frames=frames,
            source=source_clip.source,
            metadata={
                key: value
                for key, value in source_clip.metadata.items()
                if key != "structuralRefinement"
            },
        )
    ))
    return [
        {
            "frameIndex": index,
            "timeSec": frame.time_sec,
            "joints": frame.joints,
        }
        for index, frame in enumerate(comparison_clip.frames)
    ]


def _build_preview_raw_comparison_frames(source_clip: MotionClip) -> list[dict[str, object]]:
    metadata = source_clip.metadata if isinstance(source_clip.metadata, dict) else {}
    refinement = metadata.get("structuralRefinement")
    if not isinstance(refinement, dict):
        return []
    input_frames = refinement.get("inputFrames")
    if not isinstance(input_frames, list):
        return []
    raw_frames: list[dict[str, object]] = []
    for index, item in enumerate(input_frames):
        if not isinstance(item, dict):
            return []
        joints_payload = item.get("joints")
        if not isinstance(joints_payload, dict):
            return []
        raw_frames.append({
            "frameIndex": index,
            "timeSec": float(item.get("timeSec", 0.0)),
            "joints": {
                str(joint_name): (float(point[0]), float(point[1]), float(point[2]))
                for joint_name, point in joints_payload.items()
                if isinstance(point, list) and len(point) >= 3
            },
        })
    return raw_frames


def _stabilize_preview_comparison_frames(
    *,
    source_frames: list[MotionFrame],
    preview_clip: MotionClip,
    refinement: dict[str, object],
) -> list[MotionFrame]:
    dominant_profile = refinement.get("dominantProfile")
    dominant_groups_payload = dominant_profile.get("dominantGroups") if isinstance(dominant_profile, dict) else None
    dominant_groups = {
        str(group)
        for group in dominant_groups_payload
        if isinstance(group, str)
    } if isinstance(dominant_groups_payload, list) else set()
    specs = _comparison_dominant_local_motion_specs(dominant_groups)
    if not specs or len(source_frames) != preview_clip.frame_count:
        return source_frames

    stabilized_frames: list[MotionFrame] = []
    for source_frame, preview_frame in zip(source_frames, preview_clip.frames):
        joints = dict(preview_frame.joints)
        for anchor_joint, child_joints in specs:
            stable_anchor = preview_frame.joints.get(anchor_joint)
            source_anchor = source_frame.joints.get(anchor_joint)
            if stable_anchor is None or source_anchor is None:
                continue
            for child_joint in child_joints:
                source_child = source_frame.joints.get(child_joint)
                if source_child is None:
                    continue
                joints[child_joint] = (
                    stable_anchor[0] + source_child[0] - source_anchor[0],
                    stable_anchor[1] + source_child[1] - source_anchor[1],
                    stable_anchor[2] + source_child[2] - source_anchor[2],
                )
        stabilized_frames.append(MotionFrame(time_sec=source_frame.time_sec, joints=joints))
    return stabilized_frames


def _comparison_dominant_local_motion_specs(dominant_groups: set[str]) -> list[tuple[str, tuple[str, ...]]]:
    specs: list[tuple[str, tuple[str, ...]]] = []
    if "arms" in dominant_groups:
        specs.extend((
            ("left_shoulder", ("left_elbow", "left_wrist", "left_hand")),
            ("right_shoulder", ("right_elbow", "right_wrist", "right_hand")),
        ))
    if "legs" in dominant_groups:
        specs.extend((
            ("left_hip", ("left_knee", "left_ankle", "left_foot")),
            ("right_hip", ("right_knee", "right_ankle", "right_foot")),
        ))
    return specs


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
    raw_motion_review = _clip_requests_raw_motion_render(clip)
    preview_clip = _center_preview_clip_for_render(_prepare_preview_clip(clip))
    detected_loops = _detect_preview_loops(preview_clip)
    resolved_loop_index = (
        -1
        if selected_loop_index is None and raw_motion_review
        else 0
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
    active_root_anchor = None if raw_motion_review else _compute_stable_root_anchor(active_frames, root_joint)
    transformed_frames = _build_wear_transformed_frames(
        active_frames=active_frames,
        source_start_frame=active_start_frame,
        root_joint=root_joint,
        active_root_anchor=active_root_anchor,
        auto_alignment=auto_alignment,
        lock_y_drift=lock_y_drift,
        lock_root_translation=not raw_motion_review,
    )
    bounds = _compute_transformed_joint_bounds(transformed_frames)
    scene_origin = _bounds_center(bounds)
    centered_frames = _subtract_scene_origin_from_frames(transformed_frames, scene_origin)
    centered_frames, wear_coordinate_normalization = _normalize_wear_skeleton_export_coordinates(
        centered_frames,
        remove_scene_inversion=False,
    )
    centered_frames, baked_sagittal_plane_alignment = _align_baked_sagittal_plane_to_grid_axis(
        centered_frames,
    )
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
            "lockGlobalRootDrift": not raw_motion_review,
            "lockYDrift": lock_y_drift,
            "invertScene": False,
            "canonicalWorldUp": True,
            "wearCoordinateNormalization": wear_coordinate_normalization,
            "bakedSagittalPlaneAlignment": baked_sagittal_plane_alignment,
            "selectedLoopIndex": resolved_loop_index,
            "rawWhamPassthrough": raw_motion_review,
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
            "bakedSagittalPlaneAlignment": baked_sagittal_plane_alignment,
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
    preview_clip = _center_preview_clip_for_render(_prepare_preview_clip(clip))
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
    lock_root_translation: bool,
) -> list[dict[str, object]]:
    if not active_frames:
        return []
    active_start_time = active_frames[0].time_sec
    transformed_frames: list[dict[str, object]] = []
    for index, frame in enumerate(active_frames):
        translation = (
            _fixed_root_translation(frame, root_joint, active_root_anchor, lock_y_drift=lock_y_drift)
            if lock_root_translation
            else (0.0, 0.0, 0.0)
        )
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


def _compute_stable_root_anchor(
    frames: list[MotionFrame],
    root_joint: str | None,
) -> tuple[float, float, float] | None:
    root_points = [
        root_point
        for root_point in (_frame_stable_root_point(frame, root_joint) for frame in frames)
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
    root_point = _frame_stable_root_point(frame, root_joint)
    if root_point is None:
        return (0.0, 0.0, 0.0)
    root_translation = (
        root_point[0] - active_root_anchor[0],
        root_point[1] - active_root_anchor[1] if lock_y_drift else 0.0,
        root_point[2] - active_root_anchor[2],
    )
    if _is_horizontal_torso_frame(frame):
        return (
            _clamp_preview_root_translation(root_translation[0], 0.06),
            _clamp_preview_root_translation(root_translation[1], 0.018) if lock_y_drift else 0.0,
            _clamp_preview_root_translation(root_translation[2], 0.06),
        )
    return root_translation


def _clamp_preview_root_translation(value: float, limit: float) -> float:
    if value > limit:
        return limit
    if value < -limit:
        return -limit
    return value


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


def _normalize_wear_skeleton_export_coordinates(
    frames: list[dict[str, object]],
    *,
    remove_scene_inversion: bool,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if not remove_scene_inversion:
        return frames, {
            "canonicalWorldUp": True,
            "sceneInversionRemoved": False,
            "transform": "none",
        }

    normalized_frames: list[dict[str, object]] = []
    for frame in frames:
        joints = frame.get("joints")
        normalized_joints = {}
        if isinstance(joints, dict):
            normalized_joints = {
                joint_name: [
                    float(point[0]),
                    -float(point[1]),
                    -float(point[2]),
                ]
                for joint_name, point in joints.items()
                if _is_serialized_point(point)
            }
        normalized_frame = dict(frame)
        normalized_frame["joints"] = normalized_joints
        normalized_frames.append(normalized_frame)

    return normalized_frames, {
        "canonicalWorldUp": True,
        "sceneInversionRemoved": True,
        "transform": "rotate_x_pi",
        "reason": "removed_display_scene_inversion_from_wear_coordinates",
    }


def _align_baked_sagittal_plane_to_grid_axis(
    frames: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    alignment = _estimate_baked_sagittal_plane_alignment(frames)
    if not bool(alignment.get("applied")):
        return frames, alignment

    rotation_axis_value = alignment.get("rotationAxis")
    rotation_axis = (
        (float(rotation_axis_value[0]), float(rotation_axis_value[1]), float(rotation_axis_value[2]))
        if _is_serialized_point(rotation_axis_value)
        else (0.0, 1.0, 0.0)
    )
    rotation_radians = float(alignment.get("rotationRadians", alignment.get("yawRadians", 0.0)))
    pivot_value = alignment.get("pivot")
    pivot = (
        (
            float(pivot_value[0]),
            float(pivot_value[1]),
            float(pivot_value[2]),
        )
        if _is_serialized_point(pivot_value)
        else (0.0, 0.0, 0.0)
    )
    rotated_frames: list[dict[str, object]] = []
    for frame in frames:
        joints = frame.get("joints")
        rotated_joints = {}
        if isinstance(joints, dict):
            for joint_name, point in joints.items():
                if not _is_serialized_point(point):
                    continue
                centered = (
                    float(point[0]) - pivot[0],
                    float(point[1]) - pivot[1],
                    float(point[2]) - pivot[2],
                )
                rotated = _rotate_point(centered, axis=rotation_axis, angle=rotation_radians)
                rotated_joints[joint_name] = [
                    rotated[0] + pivot[0],
                    rotated[1] + pivot[1],
                    rotated[2] + pivot[2],
                ]
        rotated_frame = dict(frame)
        rotated_frame["joints"] = rotated_joints
        rotated_frames.append(rotated_frame)
    return rotated_frames, alignment


def _sagittal_plane_alignment_base_payload(
    *,
    sample_count: int,
    normal_source: str,
    status: str,
) -> dict[str, object]:
    return {
        "enabled": True,
        "targetAxis": BAKED_SAGITTAL_PLANE_TARGET_AXIS,
        "targetForward": [BAKED_SAGITTAL_PLANE_TARGET_FORWARD[0], 0.0, BAKED_SAGITTAL_PLANE_TARGET_FORWARD[1]],
        "targetNormal": [BAKED_SAGITTAL_PLANE_TARGET_NORMAL[0], 0.0, BAKED_SAGITTAL_PLANE_TARGET_NORMAL[1]],
        "targetAxisMeaning": "body_sagittal_forward_axis",
        "normalSource": normal_source,
        "applied": False,
        "status": status,
        "sampleCount": sample_count,
    }


def _build_horizontal_normal_alignment_payload(
    frames: list[dict[str, object]],
    *,
    base_payload: dict[str, object],
    normal_x: float,
    normal_z: float,
    coherence: float,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    normal_length = math.hypot(normal_x, normal_z)
    if normal_length <= 1e-5:
        return {
            **base_payload,
            "status": "ambiguous_alignment_normal",
            "coherence": coherence,
            **(extra or {}),
        }

    normal_x /= normal_length
    normal_z /= normal_length
    # WHAM/SMPL bilateral joints use the directed anatomical basis
    # forward = world-up x (right - left). Reversing this cross product
    # preserves the sagittal plane but makes the character face backward.
    forward_x = normal_z
    forward_z = -normal_x
    current_angle = math.atan2(forward_z, forward_x)
    target_angle = math.atan2(
        BAKED_SAGITTAL_PLANE_TARGET_FORWARD[1],
        BAKED_SAGITTAL_PLANE_TARGET_FORWARD[0],
    )
    yaw_radians = _normalize_signed_angle(current_angle - target_angle)
    target_direction = "+x"

    bounds = _compute_transformed_joint_bounds(frames)
    pivot = _bounds_center(bounds)
    applied = abs(math.degrees(yaw_radians)) >= BAKED_SAGITTAL_PLANE_ALIGNMENT_MIN_DEGREES
    return {
        **base_payload,
        "applied": applied,
        "status": "applied" if applied else "already_aligned",
        "targetDirection": target_direction,
        "yawRadians": yaw_radians if applied else 0.0,
        "yawDegrees": math.degrees(yaw_radians) if applied else 0.0,
        "horizontalNormalBefore": [normal_x, 0.0, normal_z],
        "horizontalForwardBefore": [forward_x, 0.0, forward_z],
        "horizontalNormalAfter": (
            [BAKED_SAGITTAL_PLANE_TARGET_NORMAL[0], 0.0, BAKED_SAGITTAL_PLANE_TARGET_NORMAL[1]]
            if applied
            else [normal_x, 0.0, normal_z]
        ),
        "horizontalForwardAfter": (
            [BAKED_SAGITTAL_PLANE_TARGET_FORWARD[0], 0.0, BAKED_SAGITTAL_PLANE_TARGET_FORWARD[1]]
            if applied
            else [forward_x, 0.0, forward_z]
        ),
        "pivot": _point_to_list(pivot),
        "coherence": coherence,
        **(extra or {}),
    }


def _build_full_normal_alignment_payload(
    frames: list[dict[str, object]],
    *,
    base_payload: dict[str, object],
    normal: tuple[float, float, float],
    coherence: float,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    resolved_normal = _normalize(normal)
    if _vector_length(resolved_normal) <= 1e-5:
        return {
            **base_payload,
            "status": "ambiguous_alignment_normal",
            "coherence": coherence,
            **(extra or {}),
        }
    positive_target_normal = (
        BAKED_SAGITTAL_PLANE_TARGET_NORMAL[0],
        0.0,
        BAKED_SAGITTAL_PLANE_TARGET_NORMAL[1],
    )
    # A plane normal is undirected: n and -n describe the same sagittal plane.
    # Pick the antipode requiring the smaller rotation.  Forcing every normal
    # to +Z can turn an upright skeleton onto its side when the estimator
    # happens to return the equivalent -Z normal.
    target_sign = 1.0 if _dot(resolved_normal, positive_target_normal) >= 0.0 else -1.0
    target_normal = tuple(component * target_sign for component in positive_target_normal)
    rotation = _rotation_between_vectors(
        resolved_normal,
        target_normal,
        minimum_degrees=BAKED_SAGITTAL_PLANE_ALIGNMENT_MIN_DEGREES,
    )
    bounds = _compute_transformed_joint_bounds(frames)
    pivot = _bounds_center(bounds)
    horizontal_length = math.hypot(resolved_normal[0], resolved_normal[2])
    horizontal_normal = (
        [resolved_normal[0] / horizontal_length, 0.0, resolved_normal[2] / horizontal_length]
        if horizontal_length > 1e-5
        else [0.0, 0.0, 0.0]
    )
    applied = rotation is not None
    rotation_axis, rotation_radians = rotation if rotation is not None else ((0.0, 1.0, 0.0), 0.0)
    horizontal_forward = [horizontal_normal[2], 0.0, -horizontal_normal[0]]
    yaw_radians = _normalize_signed_angle(math.atan2(horizontal_forward[2], horizontal_forward[0]))
    return {
        **base_payload,
        "applied": applied,
        "status": "applied" if applied else "already_aligned",
        "targetDirection": "+x" if target_sign > 0.0 else "-x",
        "resolvedTargetNormal": _point_to_list(target_normal),
        "targetNormalSign": int(target_sign),
        "rotationAxis": _point_to_list(rotation_axis),
        "rotationRadians": rotation_radians,
        "rotationDegrees": math.degrees(rotation_radians),
        "yawRadians": yaw_radians,
        "yawDegrees": math.degrees(yaw_radians),
        "normalBefore": _point_to_list(resolved_normal),
        "normalAfter": _point_to_list(target_normal if applied else resolved_normal),
        "horizontalNormalBefore": horizontal_normal,
        "horizontalForwardBefore": horizontal_forward,
        "horizontalNormalAfter": [target_normal[0], 0.0, target_normal[2]] if applied else horizontal_normal,
        "horizontalForwardAfter": [target_sign, 0.0, 0.0] if applied else horizontal_forward,
        "pivot": _point_to_list(pivot),
        "coherence": coherence,
        **(extra or {}),
    }


def _estimate_baked_movement_plane_alignment(
    frames: list[dict[str, object]],
) -> dict[str, object] | None:
    scale = _estimate_baked_skeleton_scale(frames)
    candidates: list[dict[str, object]] = []
    for label, joint_names, root_relative, priority in MOVEMENT_PLANE_ALIGNMENT_GROUPS:
        points = _baked_group_motion_track(frames, joint_names, root_relative=root_relative)
        candidate = _score_movement_plane_track(
            points,
            label=label,
            priority=priority,
            scale=scale,
        )
        if candidate is not None:
            candidates.append(candidate)
    for joint_name, root_relative, priority in MOVEMENT_PLANE_ALIGNMENT_JOINTS:
        points = _baked_joint_motion_track(frames, joint_name, root_relative=root_relative)
        candidate = _score_movement_plane_track(
            points,
            label=joint_name,
            priority=priority,
            scale=scale,
        )
        if candidate is not None:
            candidates.append(candidate)

    if not candidates:
        return None
    candidates.sort(key=lambda item: float(item["score"]), reverse=True)
    best = candidates[0]
    confidence = float(best["confidence"])
    if confidence < MOVEMENT_PLANE_ALIGNMENT_MIN_CONFIDENCE:
        return None

    direction = best["direction"]
    direction_x = float(direction[0])
    direction_z = float(direction[1])
    direction_length = math.hypot(direction_x, direction_z)
    if direction_length <= 1e-5:
        return None
    axis_x = direction_x / direction_length
    axis_z = direction_z / direction_length
    sample_count = int(best["sampleCount"])
    base_payload = _sagittal_plane_alignment_base_payload(
        sample_count=sample_count,
        normal_source="dominant_movement_plane",
        status="not_enough_movement_plane_evidence",
    )
    return _build_horizontal_normal_alignment_payload(
        frames,
        base_payload=base_payload,
        normal_x=axis_x,
        normal_z=axis_z,
        coherence=float(best["coherence"]),
        extra={
            "alignmentAxisSource": "dominant_movement_direction",
            "movementPlaneConfidence": confidence,
            "movementPlaneTrack": best["label"],
            "movementPlaneRangeRatio": float(best["rangeRatio"]),
            "movementPlaneHorizontalRange": float(best["horizontalRange"]),
            "movementPlaneDirection": [axis_x, 0.0, axis_z],
            "fallbackNormalSource": "robust_torso_bilateral_axis",
        },
    )


def _baked_group_motion_track(
    frames: list[dict[str, object]],
    joint_names: tuple[str, ...],
    *,
    root_relative: bool,
) -> list[tuple[float, float, float]]:
    raw_points: list[tuple[float, float, float] | None] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            raw_points.append(None)
            continue
        points = [
            (float(point[0]), float(point[1]), float(point[2]))
            for joint_name in joint_names
            if _is_serialized_point(point := joints.get(joint_name))
        ]
        if not points:
            raw_points.append(None)
            continue
        point = _average_preview_points(points)
        root = joints.get("pelvis") if root_relative else None
        if _is_serialized_point(root):
            point = _subtract_points(point, (float(root[0]), float(root[1]), float(root[2])))
        raw_points.append(point)
    return [point for point in _smooth_motion_line_path(raw_points) if point is not None]


def _baked_joint_motion_track(
    frames: list[dict[str, object]],
    joint_name: str,
    *,
    root_relative: bool,
) -> list[tuple[float, float, float]]:
    raw_points: list[tuple[float, float, float] | None] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            raw_points.append(None)
            continue
        point_value = joints.get(joint_name)
        if not _is_serialized_point(point_value):
            raw_points.append(None)
            continue
        point = (float(point_value[0]), float(point_value[1]), float(point_value[2]))
        root = joints.get("pelvis") if root_relative else None
        if _is_serialized_point(root):
            point = _subtract_points(point, (float(root[0]), float(root[1]), float(root[2])))
        raw_points.append(point)
    return [point for point in _smooth_motion_line_path(raw_points) if point is not None]


def _score_movement_plane_track(
    points: list[tuple[float, float, float]],
    *,
    label: str,
    priority: float,
    scale: float,
) -> dict[str, object] | None:
    if len(points) < 4:
        return None
    horizontal_samples = [(point[0], point[2]) for point in points]
    horizontal_direction = _principal_direction_2d(horizontal_samples)
    if horizontal_direction is None:
        return None
    horizontal_range = _point_track_range_2d(horizontal_samples)
    if horizontal_range <= 1e-6:
        return None
    range_ratio = horizontal_range / max(scale, 1e-6)
    if range_ratio < MOVEMENT_PLANE_ALIGNMENT_MIN_RANGE_RATIO:
        return None
    axis_range = _point_track_range_along_direction_2d(horizontal_samples, horizontal_direction)
    coherence = axis_range / max(horizontal_range, 1e-6)
    if coherence < MOVEMENT_PLANE_ALIGNMENT_MIN_COHERENCE:
        return None
    confidence = min(1.0, (range_ratio / 0.16) * 0.55 + coherence * 0.45)
    return {
        "label": label,
        "sampleCount": len(points),
        "direction": horizontal_direction,
        "horizontalRange": horizontal_range,
        "rangeRatio": range_ratio,
        "coherence": min(1.0, coherence),
        "confidence": min(1.0, confidence),
        "score": horizontal_range * coherence * max(0.0, priority),
    }


def _estimate_baked_skeleton_scale(frames: list[dict[str, object]]) -> float:
    lengths: list[float] = []
    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        for first_name, second_name in (
            ("left_shoulder", "right_shoulder"),
            ("left_hip", "right_hip"),
            ("pelvis", "neck"),
            ("pelvis", "spine3"),
            ("left_hip", "left_knee"),
            ("right_hip", "right_knee"),
            ("left_knee", "left_ankle"),
            ("right_knee", "right_ankle"),
        ):
            first = joints.get(first_name)
            second = joints.get(second_name)
            if not _is_serialized_point(first) or not _is_serialized_point(second):
                continue
            lengths.append(
                _vector_length(
                    _subtract_points(
                        (float(second[0]), float(second[1]), float(second[2])),
                        (float(first[0]), float(first[1]), float(first[2])),
                    )
                )
            )
    meaningful_lengths = [length for length in lengths if length > 1e-5]
    if not meaningful_lengths:
        return 1.0
    return max(0.25, _median(meaningful_lengths) * 4.0)


def _point_track_range_2d(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    center_x = sum(point[0] for point in points) / len(points)
    center_z = sum(point[1] for point in points) / len(points)
    return max(math.hypot(point[0] - center_x, point[1] - center_z) for point in points) * 2.0


def _point_track_range_along_direction_2d(
    points: list[tuple[float, float]],
    direction: tuple[float, float],
) -> float:
    length = math.hypot(direction[0], direction[1])
    if len(points) < 2 or length <= 1e-8:
        return 0.0
    normalized = (direction[0] / length, direction[1] / length)
    projections = [
        point[0] * normalized[0] + point[1] * normalized[1]
        for point in points
    ]
    return max(projections) - min(projections)


def _estimate_baked_sagittal_plane_alignment(
    frames: list[dict[str, object]],
) -> dict[str, object]:
    frame_normals: list[tuple[float, float, float]] = []
    pair_sample_count = 0

    for frame in frames:
        joints = frame.get("joints")
        if not isinstance(joints, dict):
            continue
        frame_x = 0.0
        frame_y = 0.0
        frame_z = 0.0
        frame_weight = 0.0
        for left_name, right_name, pair_weight in BAKED_SAGITTAL_PLANE_ALIGNMENT_PAIRS:
            left = joints.get(left_name)
            right = joints.get(right_name)
            if not _is_serialized_point(left) or not _is_serialized_point(right):
                continue
            dx = float(right[0]) - float(left[0])
            dy = float(right[1]) - float(left[1])
            dz = float(right[2]) - float(left[2])
            length = math.sqrt(dx * dx + dy * dy + dz * dz)
            if length <= 1e-5:
                continue
            weight = float(pair_weight)
            frame_x += dx / length * weight
            frame_y += dy / length * weight
            frame_z += dz / length * weight
            frame_weight += weight
            pair_sample_count += 1
        frame_length = math.sqrt(frame_x * frame_x + frame_y * frame_y + frame_z * frame_z)
        if frame_weight > 0.0 and frame_length > 1e-5:
            frame_normals.append((frame_x / frame_length, frame_y / frame_length, frame_z / frame_length))

    base_payload = _sagittal_plane_alignment_base_payload(
        sample_count=len(frame_normals),
        normal_source="robust_torso_bilateral_axis",
        status="not_enough_torso_bilateral_evidence",
    )
    if not frame_normals:
        return base_payload

    robust_normal = _normalize(
        (
            _median([normal[0] for normal in frame_normals]),
            _median([normal[1] for normal in frame_normals]),
            _median([normal[2] for normal in frame_normals]),
        )
    )
    coherence = max(
        0.0,
        min(
            1.0,
            sum(_dot(robust_normal, normal) for normal in frame_normals)
            / len(frame_normals),
        ),
    )

    return _build_full_normal_alignment_payload(
        frames,
        base_payload=base_payload,
        normal=robust_normal,
        coherence=coherence,
        extra={
            "estimator": "component_median_of_per_frame_3d_torso_axes",
            "pairSampleCount": pair_sample_count,
            "torsoPairs": [
                [left_name, right_name]
                for left_name, right_name, _ in BAKED_SAGITTAL_PLANE_ALIGNMENT_PAIRS
            ],
        },
    )


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
    if _clip_requests_raw_motion_render(clip):
        return clip
    return refine_motion_clip_for_preview(clip)


def _clip_requests_raw_motion_render(clip: MotionClip) -> bool:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    motion_tuning = metadata.get("motionTuning")
    return isinstance(motion_tuning, dict) and motion_tuning.get("enabled") is False


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
    ground = metadata.get("ground")
    if isinstance(ground, dict):
        metadata["ground"] = _translate_ground_payload(ground, translation=center)
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
    bone_length_reference_frames = frames
    frames = _suppress_preview_outlier_frames(frames)
    frames = _suppress_translation_bursts(frames)
    frames = _stabilize_unrealistic_segment_motion(frames)
    frames = _enforce_preview_joint_limits(frames)
    frames = _smooth_preview_frames(frames)
    frames, bilateral_symmetry = _stabilize_bilateral_joint_symmetry(frames)
    frames, horizontal_torso_stabilization = _stabilize_horizontal_rendered_torso_plane(frames)
    frames, bone_length_preservation = _preserve_preview_bone_lengths(
        frames,
        reference_frames=bone_length_reference_frames,
    )
    metadata = dict(clip.metadata)
    metadata[PREVIEW_REFINEMENT_METADATA_KEY] = {
        "prepared": True,
        "flipVerticalApplied": flip_vertical,
        "supportPlaneAligned": False,
        "motionLineAligned": False,
        "bilateralJointSymmetry": bilateral_symmetry,
        "horizontalRenderedTorsoPlaneStabilization": horizontal_torso_stabilization,
        "boneLengthPreservation": bone_length_preservation,
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


def _frame_stable_root_point(frame: MotionFrame, preferred_root_joint: str | None) -> tuple[float, float, float] | None:
    if _is_horizontal_torso_frame(frame):
        points = [
            point
            for joint_name in (
                "pelvis",
                "left_hip",
                "right_hip",
                "spine1",
                "spine2",
                "spine3",
                "left_shoulder",
                "right_shoulder",
            )
            if (point := frame.joints.get(joint_name)) is not None
        ]
        if points:
            return (
                sum(point[0] for point in points) / len(points),
                sum(point[1] for point in points) / len(points),
                sum(point[2] for point in points) / len(points),
            )
    return _frame_root_point(frame, preferred_root_joint)


def _is_horizontal_torso_frame(frame: MotionFrame) -> bool:
    pelvis = frame.joints.get("pelvis")
    neck = frame.joints.get("neck") or frame.joints.get("spine3") or frame.joints.get("head")
    if pelvis is None or neck is None:
        return False
    spine = _subtract_points(neck, pelvis)
    length = math.sqrt(spine[0] * spine[0] + spine[1] * spine[1] + spine[2] * spine[2])
    if length <= 1e-8:
        return False
    return abs(spine[1] / length) < 0.55


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
    span_y = max(point[1] for point in points) - min(point[1] for point in points)
    span_z = max(point[2] for point in points) - min(point[2] for point in points)
    axis_spans = sorted((span_x, span_y, span_z), reverse=True)
    return (span_x >= 0.08 and span_z >= 0.08) or (axis_spans[0] >= 0.08 and axis_spans[1] >= 0.08)


def _fit_support_plane_normal(
    support_points: list[tuple[float, float, float]],
) -> tuple[float, float, float]:
    normal_3d = _fit_support_plane_normal_3d(support_points)
    if normal_3d is not None:
        return normal_3d
    coefficients = _fit_support_plane_coefficients(support_points)
    if coefficients is None:
        return (0.0, 1.0, 0.0)
    slope_x, slope_z, _ = coefficients
    normal = _normalize((-slope_x, 1.0, -slope_z))
    return normal or (0.0, 1.0, 0.0)


def _fit_support_plane_normal_3d(
    support_points: list[tuple[float, float, float]],
) -> tuple[float, float, float] | None:
    if len(support_points) < 3:
        return None
    sampled_points = _sample_support_points_for_plane_fit(support_points, max_points=80)
    centroid = (
        sum(point[0] for point in sampled_points) / len(sampled_points),
        sum(point[1] for point in sampled_points) / len(sampled_points),
        sum(point[2] for point in sampled_points) / len(sampled_points),
    )
    centered = [_subtract_points(point, centroid) for point in sampled_points]
    weighted_normals: list[tuple[float, tuple[float, float, float]]] = []
    reference_normal: tuple[float, float, float] | None = None
    reference_area = 0.0
    for left_index in range(len(centered)):
        left = centered[left_index]
        if _vector_length(left) <= 1e-5:
            continue
        for right_index in range(left_index + 1, len(centered)):
            right = centered[right_index]
            if _vector_length(right) <= 1e-5:
                continue
            normal = _cross(left, right)
            area = _vector_length(normal)
            if area <= 1e-5:
                continue
            normalized = _normalize(normal)
            if area > reference_area:
                reference_area = area
                reference_normal = normalized
            weighted_normals.append((area, normalized))
    if reference_normal is None or reference_area <= 1e-5:
        return None

    min_area = reference_area * 0.10
    accumulated = (0.0, 0.0, 0.0)
    total_weight = 0.0
    for area, normal in weighted_normals:
        if area < min_area:
            continue
        oriented_normal = normal
        if _dot(oriented_normal, reference_normal) < 0.0:
            oriented_normal = (-oriented_normal[0], -oriented_normal[1], -oriented_normal[2])
        accumulated = (
            accumulated[0] + oriented_normal[0] * area,
            accumulated[1] + oriented_normal[1] * area,
            accumulated[2] + oriented_normal[2] * area,
        )
        total_weight += area
    if total_weight <= 1e-5:
        return None
    normal = _normalize(accumulated)
    if _vector_length(normal) <= 1e-6:
        return None
    return normal


def _sample_support_points_for_plane_fit(
    support_points: list[tuple[float, float, float]],
    *,
    max_points: int,
) -> list[tuple[float, float, float]]:
    if len(support_points) <= max_points:
        return support_points
    last_index = len(support_points) - 1
    return [
        support_points[round(index * last_index / (max_points - 1))]
        for index in range(max_points)
    ]


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


def _estimate_preview_movement_plane_yaw_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    alignment_frames = [
        {
            "joints": {
                joint_name: [point[0], point[1], point[2]]
                for joint_name, point in frame.joints.items()
            }
        }
        for frame in frames
    ]
    alignment = _estimate_baked_movement_plane_alignment(alignment_frames)
    if alignment is None or alignment.get("normalSource") != "dominant_movement_plane":
        return None
    yaw_radians = float(alignment.get("yawRadians") or 0.0)
    if abs(math.degrees(yaw_radians)) < BAKED_SAGITTAL_PLANE_ALIGNMENT_MIN_DEGREES:
        return None
    return ((0.0, 1.0, 0.0), yaw_radians)


def _compute_preview_auto_alignment(
    frames: list[MotionFrame],
) -> list[tuple[tuple[float, float, float], float]]:
    if not frames:
        return []
    if _classify_torso_alignment_mode(frames) == "horizontal_plane":
        rotations: list[tuple[tuple[float, float, float], float]] = []
        leveling_rotation = _estimate_horizontal_spine_leveling_rotation(frames)
        aligned_frames = frames
        if leveling_rotation is not None:
            rotations.append(leveling_rotation)
            aligned_frames = [_rotate_frame(frame, leveling_rotation) for frame in frames]
        movement_plane_yaw = _estimate_preview_movement_plane_yaw_rotation(aligned_frames)
        if movement_plane_yaw is not None:
            rotations.append(movement_plane_yaw)
            return rotations
        yaw_rotation = _estimate_support_profile_yaw_rotation(aligned_frames)
        if yaw_rotation is None:
            yaw_rotation = _estimate_horizontal_spine_yaw_rotation(aligned_frames)
        if yaw_rotation is not None:
            rotations.append(yaw_rotation)
        return rotations

    movement_plane_yaw = _estimate_preview_movement_plane_yaw_rotation(frames)
    if movement_plane_yaw is not None:
        return [movement_plane_yaw]

    support_profile_rotation = _estimate_support_profile_yaw_rotation(frames)
    return [support_profile_rotation] if support_profile_rotation is not None else []


def _is_large_non_yaw_rotation(
    rotation: tuple[tuple[float, float, float], float],
) -> bool:
    axis, angle = rotation
    normalized_axis = _normalize(axis)
    if _vector_length(normalized_axis) <= 1e-6:
        return False
    wrapped_angle = abs(math.atan2(math.sin(angle), math.cos(angle)))
    return abs(normalized_axis[1]) < 0.5 and wrapped_angle >= math.radians(45.0)


def _estimate_shoulder_floor_level_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    shoulder_axes: list[tuple[float, float, float]] = []
    for frame in frames:
        left = frame.joints.get("left_shoulder")
        right = frame.joints.get("right_shoulder")
        if left is None or right is None:
            continue
        axis = _normalize(_subtract_points(right, left))
        if _vector_length(axis) > 1e-6:
            shoulder_axes.append(axis)
    if len(shoulder_axes) < 3:
        return None
    shoulder_axis = _normalize(_average_preview_points(shoulder_axes))
    horizontal_axis = (shoulder_axis[0], 0.0, shoulder_axis[2])
    if _vector_length(horizontal_axis) <= 1e-6:
        return None
    return _rotation_between_vectors(shoulder_axis, horizontal_axis, minimum_degrees=1.0)


def _estimate_dominant_movement_to_nearest_world_axis_rotation(
    frames: list[MotionFrame],
    *,
    target_axis: tuple[float, float, float] | None = None,
) -> tuple[tuple[float, float, float], float] | None:
    points = _dominant_movement_axis_points(frames)
    if points is None:
        return None
    direction = _principal_direction_3d(points)
    if direction is None:
        direction = _subtract_points(points[-1], points[0])
    if _vector_length(direction) <= 1e-6:
        return None
    displacement = _subtract_points(points[-1], points[0])
    if _dot(direction, displacement) < 0.0:
        direction = _scale_vector(direction, -1.0)
    target = target_axis or _nearest_signed_world_axis(direction)
    return _rotation_between_vectors(direction, target, minimum_degrees=2.0)


def _dominant_movement_nearest_world_axis(
    frames: list[MotionFrame],
) -> tuple[float, float, float] | None:
    points = _dominant_movement_axis_points(frames)
    if points is None:
        return None
    direction = _principal_direction_3d(points)
    if direction is None:
        direction = _subtract_points(points[-1], points[0])
    if _vector_length(direction) <= 1e-6:
        return None
    displacement = _subtract_points(points[-1], points[0])
    if _dot(direction, displacement) < 0.0:
        direction = _scale_vector(direction, -1.0)
    return _nearest_signed_world_axis(direction)


def _rotation_preserves_dominant_movement_alignment(
    frames: list[MotionFrame],
    rotation: tuple[tuple[float, float, float], float],
    target_axis: tuple[float, float, float] | None,
) -> bool:
    if target_axis is None:
        return True
    before = _dominant_movement_alignment_score(frames, target_axis)
    if before is None or before < 0.70:
        return True
    rotated_frames = [_rotate_frame(frame, rotation) for frame in frames]
    after = _dominant_movement_alignment_score(rotated_frames, target_axis)
    if after is None:
        return True
    return after >= max(0.70, before - 0.12)


def _dominant_movement_alignment_score(
    frames: list[MotionFrame],
    target_axis: tuple[float, float, float],
) -> float | None:
    points = _dominant_movement_axis_points(frames)
    if points is None:
        return None
    direction = _principal_direction_3d(points)
    if direction is None:
        direction = _subtract_points(points[-1], points[0])
    if _vector_length(direction) <= 1e-6:
        return None
    return abs(_dot(_normalize(direction), _normalize(target_axis)))


def _dominant_movement_axis_points(
    frames: list[MotionFrame],
) -> list[tuple[float, float, float]] | None:
    candidates: list[tuple[float, list[tuple[float, float, float]]]] = []
    for group_name, joint_names, root_relative, priority in DOMINANT_MOVEMENT_AXIS_GROUPS:
        points = _group_motion_axis_points(frames, joint_names, root_relative=root_relative)
        score = _score_motion_axis_candidate(points, priority=priority)
        if score is not None:
            candidates.append((score, points))

    for joint_name in DOMINANT_MOVEMENT_AXIS_JOINTS:
        points = _joint_motion_axis_points(frames, joint_name, root_relative=True)
        _append_motion_axis_candidate(candidates, points, priority=_dominant_movement_joint_priority(joint_name))
    for joint_name in ("pelvis", "spine2", "spine1"):
        points = _joint_motion_axis_points(frames, joint_name, root_relative=False)
        _append_motion_axis_candidate(candidates, points, priority=0.55)
    body_points = [
        point
        for point in _smooth_motion_line_path([_frame_joint_center(frame) for frame in frames])
        if point is not None
    ]
    _append_motion_axis_candidate(candidates, body_points, priority=0.45)
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    return candidates[0][1]


def _joint_motion_axis_points(
    frames: list[MotionFrame],
    joint_name: str,
    *,
    root_relative: bool,
) -> list[tuple[float, float, float]]:
    raw_points: list[tuple[float, float, float] | None] = []
    for frame in frames:
        point = frame.joints.get(joint_name)
        if point is None:
            raw_points.append(None)
            continue
        root = frame.joints.get("pelvis") if root_relative else None
        raw_points.append(_subtract_points(point, root) if root is not None else point)
    return [point for point in _smooth_motion_line_path(raw_points) if point is not None]


def _group_motion_axis_points(
    frames: list[MotionFrame],
    joint_names: tuple[str, ...],
    *,
    root_relative: bool,
) -> list[tuple[float, float, float]]:
    raw_points: list[tuple[float, float, float] | None] = []
    for frame in frames:
        points = [frame.joints[joint_name] for joint_name in joint_names if joint_name in frame.joints]
        if not points:
            raw_points.append(None)
            continue
        point = _average_preview_points(points)
        root = frame.joints.get("pelvis") if root_relative else None
        raw_points.append(_subtract_points(point, root) if root is not None else point)
    return [point for point in _smooth_motion_line_path(raw_points) if point is not None]


def _append_motion_axis_candidate(
    candidates: list[tuple[float, list[tuple[float, float, float]]]],
    points: list[tuple[float, float, float]],
    *,
    priority: float,
) -> None:
    score = _score_motion_axis_candidate(points, priority=priority)
    if score is not None:
        candidates.append((score, points))


def _score_motion_axis_candidate(
    points: list[tuple[float, float, float]],
    *,
    priority: float,
) -> float | None:
    if len(points) < 3:
        return None
    track_range = _point_track_range(points)
    if track_range < DOMINANT_MOVEMENT_AXIS_MIN_RANGE:
        return None
    direction = _principal_direction_3d(points) or _subtract_points(points[-1], points[0])
    direction_length = _vector_length(direction)
    if direction_length <= 1e-6:
        return None
    axis_range = _point_track_range_along_direction(points, direction)
    residual_range = max(0.0, track_range - axis_range)
    coherence = axis_range / max(track_range, 1e-6)
    if coherence < 0.45 and residual_range > DOMINANT_MOVEMENT_AXIS_MIN_RANGE:
        return None
    return track_range * coherence * max(0.0, priority)


def _dominant_movement_joint_priority(joint_name: str) -> float:
    if joint_name in {"left_hand", "right_hand", "left_wrist", "right_wrist"}:
        return 1.6
    if joint_name in {"left_elbow", "right_elbow", "left_foot", "right_foot", "left_ankle", "right_ankle"}:
        return 1.25
    if joint_name in {"left_knee", "right_knee"}:
        return 1.0
    return 0.75


def _horizontal_point_track_range(points: list[tuple[float, float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    center_x = sum(point[0] for point in points) / len(points)
    center_z = sum(point[2] for point in points) / len(points)
    return (
        max(math.hypot(point[0] - center_x, point[2] - center_z) for point in points) *
        2.0
    )


def _preserve_preview_bone_lengths(
    frames: list[MotionFrame],
    *,
    reference_frames: list[MotionFrame],
) -> tuple[list[MotionFrame], dict[str, object]]:
    """Restore one stable reference length per bone after joint-wise cleanup."""
    if not frames or not reference_frames:
        return frames, {"applied": False, "reason": "no_frames", "boneCount": 0}

    joint_names = set().union(*(frame.joints.keys() for frame in reference_frames))
    edges = [
        (parent, child)
        for chain in PREVIEW_BONE_CHAINS_ROOT_OUTWARD
        for parent, child in zip(chain, chain[1:])
        if parent in joint_names and child in joint_names
    ]
    reference_lengths: dict[tuple[str, str], float] = {}
    for parent, child in edges:
        lengths = [
            _point_distance(frame.joints[parent], frame.joints[child])
            for frame in reference_frames
            if parent in frame.joints and child in frame.joints
        ]
        length = _median([value for value in lengths if value > 1e-7])
        if length > 1e-7:
            reference_lengths[(parent, child)] = length
    if not reference_lengths:
        return frames, {"applied": False, "reason": "no_resolved_bones", "boneCount": 0}

    projected_frames: list[MotionFrame] = []
    max_correction = 0.0
    corrected_joint_count = 0
    for frame_index, frame in enumerate(frames):
        joints = dict(frame.joints)
        reference_frame = reference_frames[min(frame_index, len(reference_frames) - 1)]
        for edge in edges:
            target_length = reference_lengths.get(edge)
            if target_length is None:
                continue
            parent_name, child_name = edge
            parent = joints.get(parent_name)
            child = joints.get(child_name)
            if parent is None or child is None:
                continue
            direction = _subtract_points(child, parent)
            direction_length = _vector_length(direction)
            if direction_length <= 1e-7:
                reference_parent = reference_frame.joints.get(parent_name)
                reference_child = reference_frame.joints.get(child_name)
                if reference_parent is None or reference_child is None:
                    continue
                direction = _subtract_points(reference_child, reference_parent)
                direction_length = _vector_length(direction)
            if direction_length <= 1e-7:
                continue
            scale = target_length / direction_length
            projected_child = (
                parent[0] + direction[0] * scale,
                parent[1] + direction[1] * scale,
                parent[2] + direction[2] * scale,
            )
            max_correction = max(max_correction, _point_distance(child, projected_child))
            joints[child_name] = projected_child
            corrected_joint_count += 1
        projected_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    return projected_frames, {
        "applied": True,
        "reason": "post_refinement_forward_kinematic_projection",
        "boneCount": len(reference_lengths),
        "correctedJointCount": corrected_joint_count,
        "maxCorrection": max_correction,
        "referenceLengths": {
            f"{parent}:{child}": length
            for (parent, child), length in reference_lengths.items()
        },
    }


def _stabilize_bilateral_joint_symmetry(
    frames: list[MotionFrame],
) -> tuple[list[MotionFrame], dict[str, object]]:
    if len(frames) < 3:
        return frames, {"applied": False, "reason": "insufficient_frames", "pairCount": 0}
    joint_names = set().union(*(frame.joints.keys() for frame in frames))
    joint_pairs = sorted(
        (joint_name, f"right_{joint_name[5:]}")
        for joint_name in joint_names
        if joint_name.startswith("left_") and f"right_{joint_name[5:]}" in joint_names
    )
    paired_joint_names = {joint_name for pair in joint_pairs for joint_name in pair}
    centerline_joint_names = sorted(joint_names - paired_joint_names)
    if not joint_pairs:
        return frames, {"applied": False, "reason": "no_bilateral_joint_pairs", "pairCount": 0}
    body_span = _median_motion_body_span(frames)
    if body_span <= 1e-6:
        return frames, {"applied": False, "reason": "invalid_body_span", "pairCount": len(joint_pairs)}

    frame_planes = [_frame_bilateral_symmetry_plane(frame) for frame in frames]
    pair_decisions: dict[tuple[str, str], dict[str, object]] = {}
    for left_name, right_name in joint_pairs:
        discrepancies: list[float] = []
        for frame, plane in zip(frames, frame_planes, strict=True):
            if plane is None:
                continue
            left = frame.joints.get(left_name)
            right = frame.joints.get(right_name)
            if left is None or right is None:
                continue
            plane_point, plane_normal = plane
            mirrored_right = _mirror_point_across_plane(right, plane_point, plane_normal)
            discrepancies.append(_point_distance(left, mirrored_right) / body_span)
        median_discrepancy = _median(discrepancies) if discrepancies else math.inf
        max_discrepancy = max(discrepancies, default=math.inf)
        if (
            not discrepancies
            or median_discrepancy >= BILATERAL_SYMMETRY_REJECT_BODY_RATIO
            or max_discrepancy >= BILATERAL_SYMMETRY_MAX_FRAME_BODY_RATIO
        ):
            blend = 0.0
        elif median_discrepancy <= BILATERAL_SYMMETRY_FULL_BLEND_MAX_BODY_RATIO:
            blend = 1.0
        else:
            blend = (
                BILATERAL_SYMMETRY_REJECT_BODY_RATIO - median_discrepancy
            ) / (
                BILATERAL_SYMMETRY_REJECT_BODY_RATIO
                - BILATERAL_SYMMETRY_FULL_BLEND_MAX_BODY_RATIO
            )
        pair_decisions[(left_name, right_name)] = {
            "leftJoint": left_name,
            "rightJoint": right_name,
            "medianMirroredDiscrepancyBodyRatio": median_discrepancy,
            "maxMirroredDiscrepancyBodyRatio": max_discrepancy,
            "blend": max(0.0, min(1.0, blend)),
        }

    centerline_decisions: dict[str, dict[str, object]] = {}
    for joint_name in centerline_joint_names:
        offsets: list[float] = []
        for frame, plane in zip(frames, frame_planes, strict=True):
            point = frame.joints.get(joint_name)
            if point is None or plane is None:
                continue
            plane_point, plane_normal = plane
            offsets.append(abs(_dot(_subtract_points(point, plane_point), plane_normal)) / body_span)
        median_offset = _median(offsets) if offsets else math.inf
        max_offset = max(offsets, default=math.inf)
        if not offsets or median_offset >= CENTERLINE_PROJECTION_REJECT_BODY_RATIO:
            blend = 0.0
        elif median_offset <= CENTERLINE_PROJECTION_FULL_BLEND_MAX_BODY_RATIO:
            blend = 1.0
        else:
            blend = (
                CENTERLINE_PROJECTION_REJECT_BODY_RATIO - median_offset
            ) / (
                CENTERLINE_PROJECTION_REJECT_BODY_RATIO
                - CENTERLINE_PROJECTION_FULL_BLEND_MAX_BODY_RATIO
            )
        centerline_decisions[joint_name] = {
            "joint": joint_name,
            "medianPlaneOffsetBodyRatio": median_offset,
            "maxPlaneOffsetBodyRatio": max_offset,
            "blend": max(0.0, min(1.0, blend)),
        }

    corrected_frames: list[MotionFrame] = []
    for frame, plane in zip(frames, frame_planes, strict=True):
        if plane is None:
            corrected_frames.append(frame)
            continue
        plane_point, plane_normal = plane
        joints = dict(frame.joints)
        for pair, decision in pair_decisions.items():
            blend = float(decision["blend"])
            if blend <= 0.0:
                continue
            left_name, right_name = pair
            left = joints.get(left_name)
            right = joints.get(right_name)
            if left is None or right is None:
                continue
            mirrored_right = _mirror_point_across_plane(right, plane_point, plane_normal)
            symmetric_left = _midpoint(left, mirrored_right)
            symmetric_right = _mirror_point_across_plane(symmetric_left, plane_point, plane_normal)
            joints[left_name] = _lerp_point(left, symmetric_left, blend)
            joints[right_name] = _lerp_point(right, symmetric_right, blend)
        for joint_name, decision in centerline_decisions.items():
            blend = float(decision["blend"])
            point = joints.get(joint_name)
            if point is None or blend <= 0.0:
                continue
            projected = _project_point_onto_plane(point, plane_point, plane_normal)
            joints[joint_name] = _lerp_point(point, projected, blend)
        corrected_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    corrected_pairs = [decision for decision in pair_decisions.values() if float(decision["blend"]) > 0.0]
    corrected_centerline = [
        decision
        for decision in centerline_decisions.values()
        if float(decision["blend"]) > 0.0
    ]
    return corrected_frames, {
        "applied": bool(corrected_pairs or corrected_centerline),
        "reason": "geometry_gated_paired_and_centerline_joint_projection",
        "pairCount": len(joint_pairs),
        "correctedPairCount": len(corrected_pairs),
        "centerlineJointCount": len(centerline_joint_names),
        "correctedCenterlineJointCount": len(corrected_centerline),
        "bodySpan": body_span,
        "fullBlendMaxBodyRatio": BILATERAL_SYMMETRY_FULL_BLEND_MAX_BODY_RATIO,
        "rejectBodyRatio": BILATERAL_SYMMETRY_REJECT_BODY_RATIO,
        "maxFrameBodyRatio": BILATERAL_SYMMETRY_MAX_FRAME_BODY_RATIO,
        "pairs": list(pair_decisions.values()),
        "centerlineJoints": list(centerline_decisions.values()),
    }


def _median_motion_body_span(frames: list[MotionFrame]) -> float:
    spans: list[float] = []
    for frame in frames:
        if not frame.joints:
            continue
        xs = [point[0] for point in frame.joints.values()]
        ys = [point[1] for point in frame.joints.values()]
        zs = [point[2] for point in frame.joints.values()]
        spans.append(math.sqrt(
            (max(xs) - min(xs)) ** 2
            + (max(ys) - min(ys)) ** 2
            + (max(zs) - min(zs)) ** 2
        ))
    return _median(spans) if spans else 0.0


def _frame_bilateral_symmetry_plane(
    frame: MotionFrame,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    vectors: list[tuple[float, float, float]] = []
    midpoints: list[tuple[float, float, float]] = []
    reference: tuple[float, float, float] | None = None
    for left_name, right_name in (
        ("left_shoulder", "right_shoulder"),
        ("left_hip", "right_hip"),
        ("left_collar", "right_collar"),
    ):
        left = frame.joints.get(left_name)
        right = frame.joints.get(right_name)
        if left is None or right is None:
            continue
        vector = _normalize(_subtract_points(right, left))
        if _vector_length(vector) <= 1e-6:
            continue
        if reference is None:
            reference = vector
        elif _dot(vector, reference) < 0.0:
            vector = _scale_vector(vector, -1.0)
        vectors.append(vector)
        midpoints.append(_midpoint(left, right))
    if not vectors or not midpoints:
        return None
    normal = _normalize(tuple(sum(vector[axis] for vector in vectors) for axis in range(3)))
    if _vector_length(normal) <= 1e-6:
        return None
    return _average_preview_points(midpoints), normal


def _mirror_point_across_plane(
    point: tuple[float, float, float],
    plane_point: tuple[float, float, float],
    plane_normal: tuple[float, float, float],
) -> tuple[float, float, float]:
    signed_distance = _dot(_subtract_points(point, plane_point), plane_normal)
    return _subtract_points(point, _scale_vector(plane_normal, 2.0 * signed_distance))


def _project_point_onto_plane(
    point: tuple[float, float, float],
    plane_point: tuple[float, float, float],
    plane_normal: tuple[float, float, float],
) -> tuple[float, float, float]:
    signed_distance = _dot(_subtract_points(point, plane_point), plane_normal)
    return _subtract_points(point, _scale_vector(plane_normal, signed_distance))


def _midpoint(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple((left[axis] + right[axis]) * 0.5 for axis in range(3))


def _lerp_point(
    source: tuple[float, float, float],
    target: tuple[float, float, float],
    blend: float,
) -> tuple[float, float, float]:
    return tuple(source[axis] + (target[axis] - source[axis]) * blend for axis in range(3))


def _stabilize_horizontal_rendered_torso_plane(
    frames: list[MotionFrame],
) -> tuple[list[MotionFrame], dict[str, object]]:
    if _classify_torso_alignment_mode(frames) != "horizontal_plane":
        return frames, {
            "applied": False,
            "reason": "torso_not_consistently_horizontal",
            "frameCount": len(frames),
        }

    stabilized_frames: list[MotionFrame] = []
    applied_angles_degrees: list[float] = []
    for frame in frames:
        plane_geometry = _rendered_torso_plane_normal_and_pivot(frame)
        axis_geometry = _rendered_torso_axis_and_pivot(frame)
        if plane_geometry is not None:
            torso_plane_normal, pivot = plane_geometry
            target_normal = (0.0, 1.0 if torso_plane_normal[1] >= 0.0 else -1.0, 0.0)
            rotation = _rotation_between_vectors(
                torso_plane_normal,
                target_normal,
                minimum_degrees=0.05,
            )
        elif axis_geometry is not None:
            torso_axis, pivot = axis_geometry
            horizontal_target = _normalize((torso_axis[0], 0.0, torso_axis[2]))
            rotation = _rotation_between_vectors(
                torso_axis,
                horizontal_target,
                minimum_degrees=0.05,
            )
        else:
            stabilized_frames.append(frame)
            continue
        if rotation is None:
            stabilized_frames.append(frame)
            continue
        axis, angle = rotation
        stabilized_frames.append(
            MotionFrame(
                time_sec=frame.time_sec,
                joints={
                    joint_name: _add_points(
                        _rotate_point(
                            _subtract_points(point, pivot),
                            axis=axis,
                            angle=angle,
                        ),
                        pivot,
                    )
                    for joint_name, point in frame.joints.items()
                },
            )
        )
        applied_angles_degrees.append(math.degrees(angle))

    return stabilized_frames, {
        "applied": bool(applied_angles_degrees),
        "reason": "stabilized_rendered_torso_plane_against_world_floor",
        "frameCount": len(frames),
        "correctedFrameCount": len(applied_angles_degrees),
        "medianCorrectionDegrees": (
            _median(applied_angles_degrees)
            if applied_angles_degrees
            else 0.0
        ),
        "maxCorrectionDegrees": max(applied_angles_degrees, default=0.0),
    }


def _point_track_range_along_direction(
    points: list[tuple[float, float, float]],
    direction: tuple[float, float, float],
) -> float:
    if len(points) < 2:
        return 0.0
    normalized = _normalize(direction)
    if _vector_length(normalized) <= 1e-6:
        return 0.0
    projections = [_dot(point, normalized) for point in points]
    return max(projections) - min(projections)


def _nearest_signed_world_axis(
    direction: tuple[float, float, float],
) -> tuple[float, float, float]:
    normalized = _normalize(direction)
    if _vector_length(normalized) <= 1e-8:
        return (0.0, 1.0, 0.0)
    axes = (
        (1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
    )
    return max(axes, key=lambda candidate: _dot(normalized, candidate))


def _nearest_signed_horizontal_world_axis(
    direction: tuple[float, float],
) -> tuple[float, float]:
    length = math.hypot(direction[0], direction[1])
    if length <= 1e-8:
        return (1.0, 0.0)
    normalized = (direction[0] / length, direction[1] / length)
    axes = (
        (1.0, 0.0),
        (-1.0, 0.0),
        (0.0, 1.0),
        (0.0, -1.0),
    )
    return max(
        axes,
        key=lambda candidate: normalized[0] * candidate[0] + normalized[1] * candidate[1],
    )


def _normalize_signed_angle(angle: float) -> float:
    while angle <= -math.pi:
        angle += math.tau
    while angle > math.pi:
        angle -= math.tau
    return angle


def _dominant_hand_motion_points(frames: list[MotionFrame]) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for frame in frames:
        hand_points = [
            frame.joints[joint_name]
            for joint_name in ("left_hand", "right_hand", "left_wrist", "right_wrist")
            if joint_name in frame.joints
        ]
        if hand_points:
            points.append(_average_preview_points(hand_points))
    return points


def _dominant_body_motion_points(frames: list[MotionFrame]) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for frame in frames:
        body_points = [
            frame.joints[joint_name]
            for joint_name in ("pelvis", "spine1", "spine2", "spine3", "neck", "head")
            if joint_name in frame.joints
        ]
        if body_points:
            points.append(_average_preview_points(body_points))
    return points


def _point_track_range(points: list[tuple[float, float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    center = _average_preview_points(points)
    return max(_vector_length(_subtract_points(point, center)) for point in points) * 2.0


def _nearest_signed_world_axis(
    direction: tuple[float, float, float],
) -> tuple[float, float, float]:
    normalized = _normalize(direction)
    axes = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    axis = max(axes, key=lambda candidate: abs(_dot(normalized, candidate)))
    return axis if _dot(normalized, axis) >= 0.0 else _scale_vector(axis, -1.0)


def _is_already_world_upright_with_vertical_motion(frames: list[MotionFrame]) -> bool:
    spine_angles: list[float] = []
    for frame in frames:
        pelvis = frame.joints.get("pelvis")
        neck = frame.joints.get("neck") or frame.joints.get("spine3") or frame.joints.get("head")
        if pelvis is None or neck is None:
            continue
        spine = _subtract_points(neck, pelvis)
        if _vector_length(spine) <= 1e-6:
            continue
        spine_angles.append(_axis_angle_degrees(spine, (0.0, 1.0, 0.0)))
    if len(spine_angles) < 3 or _median(spine_angles) > 25.0:
        return False

    hand_axis = _dominant_hand_motion_axis(frames)
    if hand_axis is not None and _axis_angle_degrees(hand_axis, (0.0, 1.0, 0.0)) <= 25.0:
        return True

    body_axis = _dominant_body_motion_axis(frames)
    return body_axis is not None and _axis_angle_degrees(body_axis, (0.0, 1.0, 0.0)) <= 25.0


def _dominant_hand_motion_axis(frames: list[MotionFrame]) -> tuple[float, float, float] | None:
    points: list[tuple[float, float, float]] = []
    for frame in frames:
        hand_points = [
            frame.joints[joint_name]
            for joint_name in ("left_hand", "right_hand", "left_wrist", "right_wrist")
            if joint_name in frame.joints
        ]
        if not hand_points:
            continue
        points.append(_average_preview_points(hand_points))
    if len(points) < 3:
        return None
    return _subtract_points(points[-1], points[0])


def _dominant_body_motion_axis(frames: list[MotionFrame]) -> tuple[float, float, float] | None:
    points: list[tuple[float, float, float]] = []
    for frame in frames:
        body_points = [
            frame.joints[joint_name]
            for joint_name in ("pelvis", "spine1", "spine2", "spine3", "neck", "head")
            if joint_name in frame.joints
        ]
        if not body_points:
            continue
        points.append(_average_preview_points(body_points))
    if len(points) < 3:
        return None
    return _subtract_points(points[-1], points[0])


def _average_preview_points(points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
        sum(point[2] for point in points) / len(points),
    )


def _axis_angle_degrees(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    normalized_left = _normalize(left)
    normalized_right = _normalize(right)
    if _vector_length(normalized_left) <= 1e-6 or _vector_length(normalized_right) <= 1e-6:
        return 90.0
    alignment = abs(max(-1.0, min(1.0, _dot(normalized_left, normalized_right))))
    return math.degrees(math.acos(alignment))


def _append_final_movement_axis_alignment(
    rotations: list[tuple[tuple[float, float, float], float]],
    aligned_frames: list[MotionFrame],
) -> list[tuple[tuple[float, float, float], float]]:
    final_rotation = _estimate_dominant_movement_axis_alignment_rotation(aligned_frames)
    if final_rotation is not None:
        rotations = [*rotations, final_rotation]
        aligned_frames = [_rotate_frame(frame, final_rotation) for frame in aligned_frames]
    upper_body_rotation = _estimate_upper_body_vertical_trend_alignment_rotation(aligned_frames)
    if upper_body_rotation is not None:
        rotations = [*rotations, upper_body_rotation]
        aligned_frames = [_rotate_frame(frame, upper_body_rotation) for frame in aligned_frames]
    all_joint_rotation = _estimate_all_joint_vertical_trend_alignment_rotation(aligned_frames)
    if all_joint_rotation is not None:
        rotations = [*rotations, all_joint_rotation]
        aligned_frames = [_rotate_frame(frame, all_joint_rotation) for frame in aligned_frames]
    bilateral_level_rotation = _estimate_global_bilateral_leveling_rotation(aligned_frames)
    if bilateral_level_rotation is not None:
        rotations = [*rotations, bilateral_level_rotation]
        aligned_frames = [_rotate_frame(frame, bilateral_level_rotation) for frame in aligned_frames]
    body_orientation_rotation = _estimate_global_body_orientation_alignment_rotation(aligned_frames)
    if body_orientation_rotation is None:
        return rotations
    return [*rotations, body_orientation_rotation]


def _estimate_dominant_movement_axis_alignment_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    if len(frames) < 3:
        return None
    path = _smooth_motion_line_path([_frame_motion_anchor(frame) for frame in frames])
    valid_points = [point for point in path if point is not None]
    if len(valid_points) < 3:
        return None
    direction = _principal_direction_3d(valid_points)
    if direction is None:
        return None
    displacement = _subtract_points(valid_points[-1], valid_points[0])
    if _dot(direction, displacement) < 0.0:
        direction = (-direction[0], -direction[1], -direction[2])
    horizontal_magnitude = math.hypot(direction[0], direction[2])
    vertical_magnitude = abs(direction[1])
    if vertical_magnitude >= horizontal_magnitude * 1.25:
        target = (0.0, 1.0 if direction[1] >= 0.0 else -1.0, 0.0)
    else:
        target = (0.0, 0.0, 1.0)
        if abs(direction[2]) > 1e-6 and direction[2] < 0.0:
            target = (0.0, 0.0, -1.0)
    return _rotation_between_vectors(direction, target, minimum_degrees=2.0)


def _principal_direction_3d(
    samples: list[tuple[float, float, float]],
) -> tuple[float, float, float] | None:
    if len(samples) < 2:
        return None
    mean = (
        sum(sample[0] for sample in samples) / len(samples),
        sum(sample[1] for sample in samples) / len(samples),
        sum(sample[2] for sample in samples) / len(samples),
    )
    centered = [
        (sample[0] - mean[0], sample[1] - mean[1], sample[2] - mean[2])
        for sample in samples
    ]
    vector = _normalize(_subtract_points(samples[-1], samples[0]))
    if _vector_length(vector) <= 1e-6:
        vector = (0.0, 1.0, 0.0)
    for _ in range(8):
        next_vector = (
            sum(item[0] * _dot(item, vector) for item in centered),
            sum(item[1] * _dot(item, vector) for item in centered),
            sum(item[2] * _dot(item, vector) for item in centered),
        )
        if _vector_length(next_vector) <= 1e-8:
            return None
        vector = _normalize(next_vector)
    return vector if _vector_length(vector) > 1e-6 else None


def _estimate_upper_body_vertical_trend_alignment_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    points = [_frame_upper_body_motion_anchor(frame) for frame in frames]
    points = [point for point in _smooth_motion_line_path(points) if point is not None]
    if len(points) < 3:
        return None
    mean_y = sum(point[1] for point in points) / len(points)
    variance_y = sum((point[1] - mean_y) ** 2 for point in points)
    if variance_y <= 1e-8:
        return None
    slopes = []
    for axis in (0, 2):
        mean_axis = sum(point[axis] for point in points) / len(points)
        slopes.append(sum((point[1] - mean_y) * (point[axis] - mean_axis) for point in points) / variance_y)
    trend = (slopes[0], 1.0, slopes[1])
    if _vector_length((trend[0], 0.0, trend[2])) <= math.tan(math.radians(1.0)):
        return None
    return _rotation_between_vectors(trend, (0.0, 1.0, 0.0), minimum_degrees=1.0)


def _estimate_dominant_vertical_body_trend_alignment_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    points = [point for point in _smooth_motion_line_path([
        _frame_upper_body_motion_anchor(frame)
        for frame in frames
    ]) if point is not None]
    if len(points) < 3:
        return None
    vertical_range = max(point[1] for point in points) - min(point[1] for point in points)
    horizontal_range = max(
        math.hypot(right[0] - left[0], right[2] - left[2])
        for left in points
        for right in points
    )
    if vertical_range < 0.05 or vertical_range < horizontal_range:
        return None
    return _estimate_upper_body_vertical_trend_alignment_rotation(frames)


def _estimate_all_joint_vertical_trend_alignment_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    excluded = {"left_wrist", "right_wrist", "left_hand", "right_hand"}
    slopes_by_joint: list[tuple[float, float, float]] = []
    for joint_name in frames[0].joints:
        if joint_name in excluded or any(token in joint_name for token in ("finger", "toe")):
            continue
        points = [frame.joints[joint_name] for frame in frames if joint_name in frame.joints]
        if len(points) < 3:
            continue
        mean_y = sum(point[1] for point in points) / len(points)
        variance_y = sum((point[1] - mean_y) ** 2 for point in points)
        if variance_y <= 1e-8:
            continue
        joint_slopes = []
        for axis in (0, 2):
            mean_axis = sum(point[axis] for point in points) / len(points)
            joint_slopes.append(sum((point[1] - mean_y) * (point[axis] - mean_axis) for point in points) / variance_y)
        vertical_range = max(point[1] for point in points) - min(point[1] for point in points)
        slopes_by_joint.append((joint_slopes[0], joint_slopes[1], vertical_range))
    if not slopes_by_joint:
        return None
    total_weight = sum(max(item[2], 1e-6) for item in slopes_by_joint)
    slopes = [
        sum(item[0] * max(item[2], 1e-6) for item in slopes_by_joint) / total_weight,
        sum(item[1] * max(item[2], 1e-6) for item in slopes_by_joint) / total_weight,
    ]
    trend = (slopes[0], 1.0, slopes[1])
    if _vector_length((trend[0], 0.0, trend[2])) <= math.tan(math.radians(1.0)):
        return None
    return _rotation_between_vectors(trend, (0.0, 1.0, 0.0), minimum_degrees=1.0)


def _estimate_global_bilateral_leveling_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    vectors: list[tuple[float, float, float]] = []
    for frame in frames:
        for left_joint, right_joint in (("left_shoulder", "right_shoulder"), ("left_hip", "right_hip")):
            left = frame.joints.get(left_joint)
            right = frame.joints.get(right_joint)
            if left is None or right is None:
                continue
            vector = _subtract_points(right, left)
            if _vector_length(vector) > 1e-5:
                vectors.append(vector)
    if not vectors:
        return None
    averaged = (
        sum(vector[0] for vector in vectors) / len(vectors),
        sum(vector[1] for vector in vectors) / len(vectors),
        sum(vector[2] for vector in vectors) / len(vectors),
    )
    horizontal = (averaged[0], 0.0, averaged[2])
    if _vector_length(horizontal) <= 1e-5:
        return None
    tilt_degrees = math.degrees(math.atan2(abs(averaged[1]), _vector_length(horizontal)))
    if tilt_degrees <= 1.0:
        return None
    return _rotation_between_vectors(averaged, horizontal, minimum_degrees=1.0)


def _estimate_global_body_orientation_alignment_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    body_axes: list[tuple[float, float, float]] = []
    for frame in frames:
        axis = _frame_median_bilateral_axis(frame)
        if axis is not None:
            body_axes.append(axis)
    if not body_axes:
        return None
    reference = body_axes[0]
    accumulated = (0.0, 0.0, 0.0)
    for axis in body_axes:
        oriented = axis if _dot(axis, reference) >= 0.0 else (-axis[0], -axis[1], -axis[2])
        accumulated = (
            accumulated[0] + oriented[0],
            accumulated[1] + oriented[1],
            accumulated[2] + oriented[2],
        )
    averaged = _normalize(accumulated)
    horizontal = (averaged[0], 0.0, averaged[2])
    if _vector_length(horizontal) <= 1e-5:
        return None
    tilt_degrees = math.degrees(math.atan2(abs(averaged[1]), _vector_length(horizontal)))
    if tilt_degrees <= 0.75:
        return None
    return _rotation_between_vectors(averaged, horizontal, minimum_degrees=0.75)


def _frame_median_bilateral_axis(frame: MotionFrame) -> tuple[float, float, float] | None:
    vectors = []
    for left_joint, right_joint in (("left_shoulder", "right_shoulder"), ("left_hip", "right_hip")):
        left = frame.joints.get(left_joint)
        right = frame.joints.get(right_joint)
        if left is None or right is None:
            continue
        vector = _subtract_points(right, left)
        if _vector_length(vector) > 1e-5:
            vectors.append(_normalize(vector))
    if not vectors:
        return None
    averaged = (
        sum(vector[0] for vector in vectors) / len(vectors),
        sum(vector[1] for vector in vectors) / len(vectors),
        sum(vector[2] for vector in vectors) / len(vectors),
    )
    if _vector_length(averaged) <= 1e-6:
        return None
    return _normalize(averaged)


def _frame_upper_body_motion_anchor(frame: MotionFrame) -> tuple[float, float, float] | None:
    joint_names = (
        "pelvis",
        "spine1",
        "spine2",
        "spine3",
        "neck",
        "left_collar",
        "right_collar",
        "left_shoulder",
        "right_shoulder",
    )
    points = [frame.joints[joint_name] for joint_name in joint_names if joint_name in frame.joints]
    if not points:
        return _frame_motion_anchor(frame)
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
        sum(point[2] for point in points) / len(points),
    )


def _classify_torso_alignment_mode(frames: list[MotionFrame]) -> str:
    spine_vectors = _collect_spine_vectors(frames)
    if len(spine_vectors) < 3:
        return "ambiguous"
    verticalities = sorted(abs(vector[1]) for vector in spine_vectors)
    median_verticality = verticalities[len(verticalities) // 2]
    horizontal_count = sum(1 for verticality in verticalities if verticality <= 0.35)
    upright_count = sum(1 for verticality in verticalities if verticality >= 0.65)
    if median_verticality <= 0.35 and horizontal_count >= max(3, int(len(verticalities) * 0.60)):
        return "horizontal_plane"
    if median_verticality >= 0.65 and upright_count >= max(3, int(len(verticalities) * 0.60)):
        return "upright_spine"
    return "ambiguous"


def _has_horizontal_torso_profile(frames: list[MotionFrame]) -> bool:
    return _classify_torso_alignment_mode(frames) == "horizontal_plane"


def _estimate_torso_plane_alignment_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    normals = _collect_torso_plane_normals(frames)
    if len(normals) < 3:
        return None
    reference = normals[0]
    accumulated = (0.0, 0.0, 0.0)
    for normal in normals:
        oriented = normal
        if _dot(oriented, reference) < 0.0:
            oriented = (-oriented[0], -oriented[1], -oriented[2])
        accumulated = (
            accumulated[0] + oriented[0],
            accumulated[1] + oriented[1],
            accumulated[2] + oriented[2],
        )
    averaged = _normalize(accumulated)
    if _vector_length(averaged) <= 1e-6:
        return None
    if averaged[1] < 0.0:
        averaged = (-averaged[0], -averaged[1], -averaged[2])
    return _rotation_between_vectors(averaged, (0.0, 1.0, 0.0), minimum_degrees=2.0)


def _estimate_horizontal_spine_yaw_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    projected_vectors: list[tuple[float, float, float]] = []
    for spine_vector in _collect_spine_vectors(frames):
        projected = (spine_vector[0], 0.0, spine_vector[2])
        if _vector_length(projected) <= 1e-5:
            continue
        normalized = _normalize(projected)
        if normalized[2] < 0.0:
            normalized = (-normalized[0], 0.0, -normalized[2])
        projected_vectors.append(normalized)
    if len(projected_vectors) < 3:
        return None
    averaged = _normalize((
        sum(vector[0] for vector in projected_vectors) / len(projected_vectors),
        0.0,
        sum(vector[2] for vector in projected_vectors) / len(projected_vectors),
    ))
    if _vector_length(averaged) <= 1e-6:
        return None
    return _rotation_between_vectors(averaged, (0.0, 0.0, 1.0), minimum_degrees=2.0)


def _estimate_horizontal_spine_leveling_rotation(
    frames: list[MotionFrame],
) -> tuple[tuple[float, float, float], float] | None:
    """Level a horizontal torso in world space while preserving its heading."""
    spine_vectors = [
        vector
        for vector in _collect_rendered_torso_axis_vectors(frames)
        if abs(vector[1]) <= 0.50
    ]
    if len(spine_vectors) < 3:
        return None
    reference = spine_vectors[0]
    oriented_vectors = [
        vector if _dot(vector, reference) >= 0.0 else _scale_vector(vector, -1.0)
        for vector in spine_vectors
    ]
    representative = _normalize((
        _median([vector[0] for vector in oriented_vectors]),
        _median([vector[1] for vector in oriented_vectors]),
        _median([vector[2] for vector in oriented_vectors]),
    ))
    horizontal_target = _normalize((representative[0], 0.0, representative[2]))
    if _vector_length(representative) <= 1e-6 or _vector_length(horizontal_target) <= 1e-6:
        return None
    return _rotation_between_vectors(
        representative,
        horizontal_target,
        minimum_degrees=0.5,
    )


def _collect_rendered_torso_axis_vectors(
    frames: list[MotionFrame],
) -> list[tuple[float, float, float]]:
    """Match the hip-center to shoulder-center axis used by the procedural torso mesh."""
    vectors: list[tuple[float, float, float]] = []
    for frame in frames:
        geometry = _rendered_torso_axis_and_pivot(frame)
        if geometry is None:
            continue
        torso_axis, _pivot = geometry
        vectors.append(torso_axis)
    return vectors


def _rendered_torso_axis_and_pivot(
    frame: MotionFrame,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    left_hip = frame.joints.get("left_hip")
    right_hip = frame.joints.get("right_hip")
    pelvis = frame.joints.get("pelvis")
    hip_center = (
        _average_preview_points([left_hip, right_hip])
        if left_hip is not None and right_hip is not None
        else pelvis
    )
    left_shoulder = frame.joints.get("left_shoulder")
    right_shoulder = frame.joints.get("right_shoulder")
    shoulder_center = (
        _average_preview_points([left_shoulder, right_shoulder])
        if left_shoulder is not None and right_shoulder is not None
        else frame.joints.get("neck") or frame.joints.get("spine3") or frame.joints.get("head")
    )
    if hip_center is None or shoulder_center is None:
        return None
    torso_axis = _subtract_points(shoulder_center, hip_center)
    if _vector_length(torso_axis) <= 1e-5:
        return None
    return _normalize(torso_axis), hip_center


def _rendered_torso_plane_normal_and_pivot(
    frame: MotionFrame,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    left_hip = frame.joints.get("left_hip")
    right_hip = frame.joints.get("right_hip")
    pelvis = frame.joints.get("pelvis")
    hip_center = (
        _average_preview_points([left_hip, right_hip])
        if left_hip is not None and right_hip is not None
        else pelvis
    )
    left_shoulder = frame.joints.get("left_shoulder")
    right_shoulder = frame.joints.get("right_shoulder")
    if hip_center is None or left_shoulder is None or right_shoulder is None:
        return None
    left_axis = _subtract_points(left_shoulder, hip_center)
    right_axis = _subtract_points(right_shoulder, hip_center)
    normal = _cross(left_axis, right_axis)
    if _vector_length(normal) <= 1e-5:
        return None
    return _normalize(normal), hip_center


def _collect_torso_plane_normals(frames: list[MotionFrame]) -> list[tuple[float, float, float]]:
    normals: list[tuple[float, float, float]] = []
    for frame in frames:
        pelvis = frame.joints.get("pelvis")
        left_shoulder = frame.joints.get("left_shoulder")
        right_shoulder = frame.joints.get("right_shoulder")
        if pelvis is None or left_shoulder is None or right_shoulder is None:
            continue
        left_vector = _subtract_points(left_shoulder, pelvis)
        right_vector = _subtract_points(right_shoulder, pelvis)
        normal = _cross(left_vector, right_vector)
        normal_length = _vector_length(normal)
        if normal_length <= 1e-5:
            continue
        normals.append((
            normal[0] / normal_length,
            normal[1] / normal_length,
            normal[2] / normal_length,
        ))
    return normals


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


def _rotation_preserves_body_orientation(
    frames: list[MotionFrame],
    rotation: tuple[tuple[float, float, float], float],
) -> bool:
    if _collect_upright_spine_vectors(frames):
        return _rotation_preserves_upright_spine(frames, rotation)
    if _classify_torso_alignment_mode(frames) == "horizontal_plane":
        return _rotation_preserves_horizontal_torso(frames, rotation)
    return True


def _rotation_preserves_body_orientation_or_pending_inversion(
    frames: list[MotionFrame],
    rotation: tuple[tuple[float, float, float], float],
) -> bool:
    if _aligned_body_points_down(frames, []):
        return _rotation_preserves_body_verticality(frames, rotation)
    return _rotation_preserves_body_orientation(frames, rotation)


def _rotation_preserves_body_verticality(
    frames: list[MotionFrame],
    rotation: tuple[tuple[float, float, float], float],
) -> bool:
    spine_vectors = _collect_spine_vectors(frames)
    if len(spine_vectors) < 3:
        return True
    before = _median([abs(vector[1]) for vector in spine_vectors])
    axis, angle = rotation
    rotated = [_rotate_point(vector, axis=axis, angle=angle) for vector in spine_vectors]
    after = _median([abs(vector[1]) for vector in rotated])
    return after >= max(0.65, before - 0.12)


def _rotation_preserves_horizontal_torso(
    frames: list[MotionFrame],
    rotation: tuple[tuple[float, float, float], float],
) -> bool:
    spine_vectors = _collect_spine_vectors(frames)
    if len(spine_vectors) < 3:
        return True
    before = _median([abs(vector[1]) for vector in spine_vectors])
    axis, angle = rotation
    rotated = [_rotate_point(vector, axis=axis, angle=angle) for vector in spine_vectors]
    after = _median([abs(vector[1]) for vector in rotated])
    return after <= max(0.18, before + 0.10)


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


def _estimate_upright_spine_leveling_rotation(
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
    target = (0.0, 1.0 if averaged[1] >= 0.0 else -1.0, 0.0)
    return _rotation_between_vectors(averaged, target, minimum_degrees=2.0)


def _collect_spine_vectors(frames: list[MotionFrame]) -> list[tuple[float, float, float]]:
    vectors: list[tuple[float, float, float]] = []
    for frame in frames:
        pelvis = frame.joints.get("pelvis")
        spine_top = frame.joints.get("neck") or frame.joints.get("head") or frame.joints.get("spine3")
        if pelvis is None or spine_top is None:
            continue
        spine_vector = _subtract_points(spine_top, pelvis)
        spine_length = _vector_length(spine_vector)
        if spine_length <= 1e-5:
            continue
        vectors.append((
            spine_vector[0] / spine_length,
            spine_vector[1] / spine_length,
            spine_vector[2] / spine_length,
        ))
    return vectors


def _collect_upright_spine_vectors(frames: list[MotionFrame]) -> list[tuple[float, float, float]]:
    candidates: list[tuple[float, tuple[float, float, float]]] = []
    for normalized in _collect_spine_vectors(frames):
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


def _aligned_body_points_down(
    frames: list[MotionFrame],
    rotations: list[tuple[tuple[float, float, float], float]],
) -> bool:
    y_values: list[float] = []
    for frame in frames:
        pelvis = frame.joints.get("pelvis")
        upper = (
            frame.joints.get("neck")
            or frame.joints.get("spine3")
            or frame.joints.get("head")
        )
        if pelvis is None or upper is None:
            continue
        aligned_pelvis = _apply_rotations_to_point(pelvis, rotations)
        aligned_upper = _apply_rotations_to_point(upper, rotations)
        y_values.append(aligned_upper[1] - aligned_pelvis[1])
    if not y_values:
        return False
    return _median(y_values) < -0.05


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


def _translate_ground_payload(
    ground_payload: dict[str, object],
    *,
    translation: tuple[float, float, float],
) -> dict[str, object]:
    translated = json.loads(json.dumps(ground_payload))
    for plane_key in ("renderGroundPlane", "motionGroundPlane"):
        plane = translated.get(plane_key)
        if not isinstance(plane, dict):
            continue
        normal = plane.get("normal")
        offset = plane.get("offset")
        if not isinstance(normal, list) or len(normal) != 3 or not isinstance(offset, (int, float)):
            continue
        plane["offset"] = float(offset) + sum(
            float(normal[axis]) * float(translation[axis])
            for axis in range(3)
        )
    for origin_key in ("renderGroundOrigin", "motionGroundOrigin"):
        origin = translated.get(origin_key)
        if not isinstance(origin, dict):
            continue
        point = origin.get("point")
        if isinstance(point, list) and len(point) == 3:
            origin["point"] = [
                float(point[axis]) - float(translation[axis])
                for axis in range(3)
            ]
    return translated


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


def _level_preview_bilateral_body_axes(frames: list[MotionFrame]) -> list[MotionFrame]:
    leveled: list[MotionFrame] = []
    for frame in frames:
        rotation = _estimate_frame_bilateral_leveling_rotation(frame)
        if rotation is None:
            leveled.append(frame)
            continue
        center = _frame_bilateral_leveling_center(frame)
        if center is None:
            leveled.append(frame)
            continue
        axis, angle = rotation
        joints = {}
        for joint_name, point in frame.joints.items():
            local = _subtract_points(point, center)
            rotated = _rotate_point(local, axis=axis, angle=angle)
            joints[joint_name] = (
                rotated[0] + center[0],
                rotated[1] + center[1],
                rotated[2] + center[2],
            )
        leveled.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return leveled


def _estimate_frame_bilateral_leveling_rotation(
    frame: MotionFrame,
) -> tuple[tuple[float, float, float], float] | None:
    vectors: list[tuple[float, float, float]] = []
    for left_joint, right_joint in (("left_shoulder", "right_shoulder"), ("left_hip", "right_hip")):
        left = frame.joints.get(left_joint)
        right = frame.joints.get(right_joint)
        if left is None or right is None:
            continue
        vector = _subtract_points(right, left)
        if _vector_length(vector) > 1e-5:
            vectors.append(vector)
    if not vectors:
        return None
    averaged = (
        sum(vector[0] for vector in vectors) / len(vectors),
        sum(vector[1] for vector in vectors) / len(vectors),
        sum(vector[2] for vector in vectors) / len(vectors),
    )
    horizontal = (averaged[0], 0.0, averaged[2])
    if _vector_length(horizontal) <= 1e-5:
        return None
    tilt_degrees = math.degrees(math.atan2(abs(averaged[1]), _vector_length(horizontal)))
    if tilt_degrees <= 1.0:
        return None
    return _rotation_between_vectors(averaged, horizontal, minimum_degrees=1.0)


def _frame_bilateral_leveling_center(frame: MotionFrame) -> tuple[float, float, float] | None:
    joint_names = (
        "pelvis",
        "spine1",
        "spine2",
        "spine3",
        "neck",
        "left_shoulder",
        "right_shoulder",
        "left_hip",
        "right_hip",
    )
    points = [frame.joints[joint_name] for joint_name in joint_names if joint_name in frame.joints]
    if not points:
        return _frame_joint_center(frame)
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
        sum(point[2] for point in points) / len(points),
    )


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


def _add_points(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[0] + right[0],
        left[1] + right[1],
        left[2] + right[2],
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
    minimum_frames = _preview_minimum_loop_frames(clip)
    if clip.frame_count <= minimum_frames:
        return []
    root_joint = _find_root_joint(clip)
    dominant_groups = _preview_dominant_motion_groups(clip)
    key_joints = _preview_loop_key_joints(clip, dominant_groups=dominant_groups)
    if not key_joints:
        return []
    support_states = _extract_preview_support_states(clip)
    use_support_state_veto = not dominant_groups
    candidates: list[dict[str, object]] = []
    boundary_indexes = _preview_loop_boundary_indexes(clip.frame_count)
    for start_index in boundary_indexes:
        for end_index in boundary_indexes:
            if end_index < start_index + minimum_frames:
                continue
            if not _preview_loop_motion_is_meaningful(
                clip,
                start_index=start_index,
                end_index=end_index,
                key_joints=key_joints,
                root_joint=root_joint,
            ):
                continue
            if use_support_state_veto and not _preview_loop_support_states_are_compatible(
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
                    "absoluteBoundaryCost": absolute_cost,
                    "localBoundaryCost": local_cost,
                    "velocityBoundaryCost": velocity_cost,
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


def _preview_loop_boundary_indexes(frame_count: int) -> list[int]:
    """Bound exhaustive loop search while retaining the full clip timeline."""
    if frame_count <= 0:
        return []
    if frame_count <= MAX_PREVIEW_LOOP_BOUNDARY_SAMPLES:
        return list(range(frame_count))
    stride = max(1, math.ceil((frame_count - 1) / (MAX_PREVIEW_LOOP_BOUNDARY_SAMPLES - 1)))
    indexes = list(range(0, frame_count, stride))
    if indexes[-1] != frame_count - 1:
        indexes.append(frame_count - 1)
    return indexes


def _preview_loop_motion_is_meaningful(
    clip: MotionClip,
    *,
    start_index: int,
    end_index: int,
    key_joints: list[str],
    root_joint: str | None,
) -> bool:
    frame_span = end_index - start_index + 1
    sample_stride = max(1, math.ceil(frame_span / MAX_PREVIEW_LOOP_MOTION_SAMPLES))
    frames = clip.frames[start_index:end_index + 1:sample_stride]
    if frames and frames[-1] is not clip.frames[end_index]:
        frames = [*frames, clip.frames[end_index]]
    if len(frames) < 2:
        return False
    points = [point for frame in frames for point in frame.joints.values()]
    if not points:
        return False
    body_span = max(
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    )
    if body_span <= 1e-8:
        return False
    max_range = 0.0
    for joint_name in key_joints:
        localized: list[tuple[float, float, float]] = []
        for frame in frames:
            point = frame.joints.get(joint_name)
            if point is None:
                continue
            root = frame.joints.get(root_joint) if root_joint else None
            localized.append(
                (
                    point[0] - (root[0] if root is not None else 0.0),
                    point[1] - (root[1] if root is not None else 0.0),
                    point[2] - (root[2] if root is not None else 0.0),
                )
            )
        if len(localized) < 2:
            continue
        joint_range = math.sqrt(
            sum(
                (max(point[axis] for point in localized) - min(point[axis] for point in localized)) ** 2
                for axis in range(3)
            )
        )
        max_range = max(max_range, joint_range)
    return max_range / body_span >= MIN_PREVIEW_LOOP_MOTION_BODY_RATIO


def _preview_minimum_loop_frames(clip: MotionClip) -> int:
    if clip.frame_count < 2:
        return 2
    duration_sec = max(0.0, clip.frames[-1].time_sec - clip.frames[0].time_sec)
    adaptive_min_seconds = min(
        MIN_LOOP_DURATION_SECONDS,
        max(0.75, duration_sec * 0.50),
    )
    return max(2, int(math.ceil(clip.fps * adaptive_min_seconds)))


def _preview_dominant_motion_groups(clip: MotionClip) -> set[str]:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    refinement = metadata.get("structuralRefinement") if isinstance(metadata, dict) else None
    dominant_profile = refinement.get("dominantProfile") if isinstance(refinement, dict) else None
    groups = dominant_profile.get("dominantGroups") if isinstance(dominant_profile, dict) else None
    if not isinstance(groups, list):
        return set()
    return {str(group) for group in groups if isinstance(group, str)}


def _preview_loop_key_joints(clip: MotionClip, *, dominant_groups: set[str]) -> list[str]:
    group_candidates = {
        "arms": ("left_elbow", "left_wrist", "left_hand", "right_elbow", "right_wrist", "right_hand"),
        "legs": ("left_knee", "left_ankle", "left_foot", "right_knee", "right_ankle", "right_foot"),
        "torso": ("pelvis", "spine1", "spine2", "spine3", "neck", "head"),
    }
    candidates: list[str] = []
    if not dominant_groups:
        candidates = ["pelvis", "left_foot", "right_foot", "left_hand", "right_hand", "head"]
    if dominant_groups:
        for group_name in ("torso", "arms", "legs"):
            if group_name in dominant_groups:
                candidates.extend(group_candidates[group_name])
    seen: set[str] = set()
    key_joints: list[str] = []
    for joint_name in candidates:
        if joint_name in seen or joint_name not in clip.joint_names:
            continue
        seen.add(joint_name)
        key_joints.append(joint_name)
    return key_joints


def _build_fallback_preview_loop_candidates(
    clip: MotionClip,
    *,
    minimum_frames: int,
) -> list[dict[str, object]]:
    if clip.frame_count <= minimum_frames:
        return []
    target_frames = min(
        clip.frame_count,
        max(minimum_frames, int(round(clip.fps * 3.0))),
    )
    if target_frames <= 1:
        return []
    step = max(1, target_frames // 2)
    candidates: list[dict[str, object]] = []
    start_index = 0
    while start_index < clip.frame_count - 1 and len(candidates) < MAX_DETECTED_LOOPS:
        end_index = min(clip.frame_count - 1, start_index + target_frames - 1)
        if end_index - start_index + 1 < minimum_frames:
            break
        start_time = clip.frames[start_index].time_sec
        end_time = clip.frames[end_index].time_sec
        candidates.append(
            {
                "startFrame": start_index,
                "endFrame": end_index,
                "startTimeSec": start_time,
                "endTimeSec": end_time,
                "durationSec": end_time - start_time,
                "score": 999.0 + len(candidates),
                "fallback": True,
                "label": (
                    f"Candidate {len(candidates) + 1}: "
                    f"{start_time:.2f}s -> {end_time:.2f}s "
                    f"({end_time - start_time:.2f}s)"
                ),
            }
        )
        if end_index >= clip.frame_count - 1:
            break
        start_index += step
    return candidates


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
    if _preview_loop_pose_cost(absolute_mismatches) > 0.055:
        return False
    if _preview_loop_pose_cost(local_mismatches) > 0.050:
        return False
    thresholds = {
        "pelvis": 0.065,
        "spine1": 0.065,
        "spine2": 0.065,
        "spine3": 0.065,
        "neck": 0.075,
        "head": 0.085,
        "left_knee": 0.075,
        "right_knee": 0.075,
        "left_ankle": 0.075,
        "right_ankle": 0.075,
        "left_foot": 0.080,
        "right_foot": 0.080,
        "left_elbow": 0.090,
        "right_elbow": 0.090,
        "left_wrist": 0.095,
        "right_wrist": 0.095,
        "left_hand": 0.100,
        "right_hand": 0.100,
    }
    for joint_name, threshold in thresholds.items():
        absolute_value = absolute_mismatches.get(joint_name)
        if absolute_value is not None and absolute_value > threshold:
            return False
        local_value = local_mismatches.get(joint_name)
        if local_value is not None and local_value > threshold:
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
    .range-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 8px;
    }}
    .button-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 8px;
    }}
    input[type="number"] {{
      width: 100%;
      min-height: 30px;
      box-sizing: border-box;
      color: var(--ink);
      background: rgba(0, 0, 0, 0.18);
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 6px;
      padding: 4px 6px;
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
        <div class="control-group">
          <div class="control-group-title">Model rotation</div>
          <label class="control">Pitch X
            <input id="modelRotationX" type="range" min="-90" max="90" step="1" value="0" />
            <span id="modelRotationXValue">0°</span>
          </label>
          <label class="control">Yaw Y
            <input id="modelRotationY" type="range" min="-180" max="180" step="1" value="0" />
            <span id="modelRotationYValue">0°</span>
          </label>
          <label class="control">Roll Z
            <input id="modelRotationZ" type="range" min="-90" max="90" step="1" value="0" />
            <span id="modelRotationZValue">0°</span>
          </label>
          <button id="resetModelRotation" type="button">Reset model rotation</button>
        </div>
        <label class="control-row" for="showComparisonOverlay">
          <span>Show stabilized source-motion overlay</span>
          <input id="showComparisonOverlay" type="checkbox" />
        </label>
        <label class="control-row" for="showRawComparisonOverlay">
          <span>Show raw WHAM overlay</span>
          <input id="showRawComparisonOverlay" type="checkbox" />
        </label>
        <div class="control-group">
          <div class="control-group-title">Motion tuning</div>
          <label class="control">Dominant cutoff
            <input id="previewDominantCutoff" type="range" min="0.10" max="1.00" step="0.01" value="0.65" />
            <span id="previewDominantCutoffValue">0.65</span>
          </label>
          <label class="control">Non-dominant damping
            <input id="previewNonDominantDamping" type="range" min="0.00" max="1.00" step="0.01" value="1.00" />
            <span id="previewNonDominantDampingValue">1.00</span>
          </label>
          <label class="control">Residual motion scale
            <input id="previewResidualScale" type="range" min="0.00" max="2.00" step="0.05" value="1.00" />
            <span id="previewResidualScaleValue">1.00</span>
          </label>
        </div>
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
          <label class="control-row" for="lockPlantedHands">
            <span>Lock planted hands</span>
            <input id="lockPlantedHands" type="checkbox" />
          </label>
        </div>
        <label class="control">Preview source
          <select id="loopSelect"></select>
        </label>
        <div class="control-group">
          <div class="control-group-title">Output section</div>
          <div class="range-grid">
            <label class="control">Start seconds
              <input id="sectionStartSeconds" type="number" min="0" step="0.01" value="0" />
            </label>
            <label class="control">End seconds
              <input id="sectionEndSeconds" type="number" min="0" step="0.01" value="0" />
            </label>
          </div>
          <div class="button-row">
            <button id="setSectionStartFromFrame" type="button">Set start</button>
            <button id="setSectionEndFromFrame" type="button">Set end</button>
          </div>
          <div class="button-row">
            <button id="applySectionRange" type="button">Preview section</button>
            <button id="resetSectionRange" type="button">Full clip</button>
          </div>
        </div>
        <button id="downloadWearSkeleton" type="button">Download baked Wear skeleton</button>
        <div class="stat">Source range: <span id="loopCount"></span></div>
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
    const modelRotationXInput = document.getElementById("modelRotationX");
    const modelRotationYInput = document.getElementById("modelRotationY");
    const modelRotationZInput = document.getElementById("modelRotationZ");
    const modelRotationXValue = document.getElementById("modelRotationXValue");
    const modelRotationYValue = document.getElementById("modelRotationYValue");
    const modelRotationZValue = document.getElementById("modelRotationZValue");
    const resetModelRotationButton = document.getElementById("resetModelRotation");
    const showComparisonOverlayInput = document.getElementById("showComparisonOverlay");
    const showRawComparisonOverlayInput = document.getElementById("showRawComparisonOverlay");
    const previewDominantCutoffInput = document.getElementById("previewDominantCutoff");
    const previewNonDominantDampingInput = document.getElementById("previewNonDominantDamping");
    const previewResidualScaleInput = document.getElementById("previewResidualScale");
    const previewDominantCutoffValue = document.getElementById("previewDominantCutoffValue");
    const previewNonDominantDampingValue = document.getElementById("previewNonDominantDampingValue");
    const previewResidualScaleValue = document.getElementById("previewResidualScaleValue");
    const fixedRootInput = document.getElementById("fixedRoot");
    const lockYRootInput = document.getElementById("lockYRoot");
    const lockPlantedFeetInput = document.getElementById("lockPlantedFeet");
    const lockPlantedHandsInput = document.getElementById("lockPlantedHands");
    const sectionStartSecondsInput = document.getElementById("sectionStartSeconds");
    const sectionEndSecondsInput = document.getElementById("sectionEndSeconds");
    const setSectionStartFromFrameButton = document.getElementById("setSectionStartFromFrame");
    const setSectionEndFromFrameButton = document.getElementById("setSectionEndFromFrame");
    const applySectionRangeButton = document.getElementById("applySectionRange");
    const resetSectionRangeButton = document.getElementById("resetSectionRange");
    const downloadWearSkeletonButton = document.getElementById("downloadWearSkeleton");
    const loopSelect = document.getElementById("loopSelect");
    const loopCountNode = document.getElementById("loopCount");
    const activeLoopNode = document.getElementById("activeLoop");
    const rootTranslationLabel = document.getElementById("rootTranslationLabel");
    const frameIndexNode = document.getElementById("frameIndex");
    document.getElementById("frameCount").textContent = String(payload.frameCount);
    document.getElementById("fps").textContent = String(payload.fps);

    let yaw = (Number(payload.defaultCameraYawDegrees) || 0.0) * Math.PI / 180;
    let pitch = (Number(payload.defaultCameraPitchDegrees) || 0.0) * Math.PI / 180;
    let zoom = parseFloat(zoomInput.value);
    let speed = parseFloat(speedInput.value);
    let fixedRoot = Boolean(payload.defaultFixedRoot);
    let paused = false;
    let frameCursor = 0;
    let playbackDirection = 1;
    const previewMaxRenderFps = Math.max(12, Math.min(30, Number(payload.previewMaxRenderFps) || Number(payload.fps) || 30));
    const previewMinRenderIntervalMs = 1000 / previewMaxRenderFps;
    let lastTimestamp = null;
    let lastDrawTimestamp = null;
    let forceNextDraw = true;
    let dragging = false;
    let cameraTouched = false;
    let dragX = 0;
    let dragY = 0;
    let pendingReframeHandle = null;
    let autoWorldAlignmentEnabled = Boolean(payload.defaultAutoWorldAlignment);
    let sceneInverted = Boolean(payload.defaultSceneInverted);
    let manualModelRotationXDegrees = 0.0;
    let manualModelRotationYDegrees = 0.0;
    let manualModelRotationZDegrees = 0.0;
    let showComparisonOverlay = false;
    let showRawComparisonOverlay = false;
    let previewDominantCutoff = Number(payload.structuralRefinement?.settings?.dominantChainRatio ?? 0.65);
    let previewNonDominantDamping = Number(payload.structuralRefinement?.settings?.nonDominantDamping ?? 1.0);
    let previewResidualScale = Number(payload.structuralRefinement?.settings?.nonDominantRadiusScale ?? 1.0);
    let showBoundsHelper = true;
    let lockYRoot = false;
    let lockPlantedFeet = false;
    let lockPlantedHands = false;
    let sourceFootSupportEvidence = null;
    let activeRenderFrame = null;
    let activeHandSupportAnchor = null;
    let activeVerticalMovementAnchor = null;
    let footLockCorrectionsKey = null;
    let footLockCorrections = new Map();
    let lockedJointFrameKey = null;
    let lockedJointPositions = new Map();
    let stableLegPoleVectorsKey = null;
    let stableLegPoleVectors = new Map();
    let frameShoulderLevelingKey = null;
    let frameShoulderLevelingTransform = null;
    let lockedHandMovementAlignmentKey = null;
    let lockedHandMovementAlignmentTransform = null;
    let lockedHandBodyDriftAnchorKey = null;
    let lockedHandBodyDriftAnchor = null;
    const cameraTarget = new THREE.Vector3();
    const defaultAutoAlignment = Array.isArray(payload.defaultAutoAlignment) ? payload.defaultAutoAlignment : [];
    const detectedLoops = Array.isArray(payload.detectedLoops) ? payload.detectedLoops : [];
    const comparisonFrames = Array.isArray(payload.comparisonFrames) ? payload.comparisonFrames : [];
    const rawComparisonFrames = Array.isArray(payload.rawComparisonFrames) ? payload.rawComparisonFrames : [];
    const horizontalTorsoProfile = Boolean(payload.horizontalTorsoProfile);
    const customModelUsesFusedSpine = Boolean(payload.spineposeMotionFusion && Number(payload.spineposeMotionFusion.appliedFrames) > 0);
    let selectedLoopIndex = -1;
    let customTimeRange = null;
    let currentLoop = null;
    let currentAutoAlignment = currentLoop?.autoAlignment ?? defaultAutoAlignment;
    let playbackState = buildPlaybackState(payload.frames, currentLoop);
    let renderingBakedWearPayload = false;
    let comparisonPlaybackState = buildPlaybackState(comparisonFrames, currentLoop);
    let rawComparisonPlaybackState = buildPlaybackState(rawComparisonFrames, currentLoop);
    let activeRootAnchor = null;
    let cachedSceneBoundsKey = null;
    let cachedSceneBounds = null;
    let vlmReviewStyle = false;
    fixedRootInput.checked = fixedRoot;
    lockYRootInput.checked = lockYRoot;
    lockPlantedFeetInput.checked = lockPlantedFeet;
    lockPlantedHandsInput.checked = lockPlantedHands;
    autoWorldAlignmentInput.checked = autoWorldAlignmentEnabled;
    sceneInvertedInput.checked = sceneInverted;
    syncManualModelRotationControls();
    showComparisonOverlayInput.checked = showComparisonOverlay;
    showComparisonOverlayInput.disabled = comparisonFrames.length === 0;
    showRawComparisonOverlayInput.checked = showRawComparisonOverlay;
    showRawComparisonOverlayInput.disabled = rawComparisonFrames.length === 0;
    rootTranslationLabel.textContent = payload.rootTranslationToggleLabel ?? "Lock global root drift";
    loopCountNode.textContent = "Full clip";
    populateLoopSelect();
    refreshActiveLoopLabel();
    syncSectionRangeControlsToActiveRange();

    const renderer = new THREE.WebGLRenderer({{
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
      preserveDrawingBuffer: true,
    }});
    renderer.setClearColor(0x101418, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    viewport.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const perspectiveCamera = new THREE.PerspectiveCamera(34, 1, 0.01, 100);
    const bakedWearCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 100);
    scene.add(perspectiveCamera);
    scene.add(bakedWearCamera);

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
    const bakedWearGrid = new THREE.GridHelper(1, 4, 0x1ed6e3, 0x1ed6e3);
    bakedWearGrid.visible = false;
    scene.add(bakedWearGrid);
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
    let suppressPreviewSagittalPlaneAlignment = false;
    let suppressManualModelRotation = false;
    let previewSagittalPlaneAlignmentKey = null;
    let previewSagittalPlaneAlignment = null;
    const sceneRotationQuaternion = new THREE.Quaternion();
    const sceneUp = new THREE.Vector3(0, 1, 0);
    const sceneRight = new THREE.Vector3(1, 0, 0);
    const sceneForward = new THREE.Vector3(0, 0, 1);
    let bakedWearReviewBounds = null;

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
    const spineMeshes = [0, 1, 2, 3].map(() => attachOutline(new THREE.Mesh(spineGeometry, torsoMaterial), torsoOutlineMaterial));
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
    function createTransparentOriginalMaterial(sourceMaterial) {{
      const material = sourceMaterial.clone();
      if (material.color) {{
        material.color.setHex(0xffb000);
      }}
      if (material.emissive) {{
        material.emissive.setHex(0xff5a00);
        material.emissiveIntensity = 1.15;
      }}
      material.transparent = true;
      material.opacity = 0.54;
      material.depthWrite = false;
      material.depthTest = false;
      material.polygonOffset = true;
      material.polygonOffsetFactor = -1.5;
      material.polygonOffsetUnits = -1.5;
      return material;
    }}
    const comparisonBodyMeshes = proceduralBodyMeshes.map((sourceMesh) => {{
      const mesh = new THREE.Mesh(
        sourceMesh.geometry.clone(),
        createTransparentOriginalMaterial(sourceMesh.material)
      );
      mesh.visible = false;
      mesh.renderOrder = 9;
      scene.add(mesh);
      return {{ sourceMesh, mesh }};
    }});
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
    const comparisonLineMaterial = new THREE.LineBasicMaterial({{
      color: 0xff6b4a,
      transparent: true,
      opacity: 0.0,
      depthTest: false,
    }});
    const comparisonNodeMaterial = new THREE.MeshBasicMaterial({{
      color: 0xff6b4a,
      transparent: true,
      opacity: 0.0,
      depthTest: false,
    }});
    const comparisonLines = skeletonChains.map((jointNames) => {{
      const geometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(0, 0, 0),
      ]);
      const line = new THREE.Line(geometry, comparisonLineMaterial);
      line.visible = false;
      line.renderOrder = 5;
      scene.add(line);
      return {{ jointNames, line }};
    }});
    const comparisonNodeMeshes = jointNodeNames.map((jointName) => {{
      const mesh = new THREE.Mesh(jointNodeGeometry, comparisonNodeMaterial);
      mesh.visible = false;
      mesh.renderOrder = 6;
      scene.add(mesh);
      return {{ jointName, mesh }};
    }});

    function setLitMaterial(material, color, emissive, emissiveIntensity, roughness, metalness) {{
      if (material.color) {{
        material.color.setHex(color);
      }}
      if (material.emissive) {{
        material.emissive.setHex(emissive);
        material.emissiveIntensity = emissiveIntensity;
      }}
      material.roughness = roughness;
      material.metalness = metalness;
      material.needsUpdate = true;
    }}

    function setLineMaterial(material, color, opacity) {{
      material.color.setHex(color);
      material.opacity = opacity;
      material.needsUpdate = true;
    }}

    function applyVlmReviewStyle() {{
      renderer.setClearColor(vlmReviewStyle ? 0xf8fafc : 0x101418, 1);
      renderer.toneMappingExposure = vlmReviewStyle ? 1.18 : 1.05;
      ambientLight.color.setHex(vlmReviewStyle ? 0xffffff : 0x29404b);
      ambientLight.intensity = vlmReviewStyle ? 1.25 : 0.5;
      hemiLight.color.setHex(vlmReviewStyle ? 0xffffff : 0x9ff7ff);
      hemiLight.groundColor.setHex(vlmReviewStyle ? 0xd6dde3 : 0x03070a);
      hemiLight.intensity = vlmReviewStyle ? 1.15 : 0.95;
      directionalLight.color.setHex(vlmReviewStyle ? 0xffffff : 0xeaffff);
      directionalLight.intensity = vlmReviewStyle ? 1.45 : 1.8;
      rimLight.color.setHex(vlmReviewStyle ? 0x35526f : 0x2df0ff);
      rimLight.intensity = vlmReviewStyle ? 0.55 : 1.35;
      grid.visible = !renderingBakedWearPayload && !vlmReviewStyle;
      bakedWearGrid.visible = renderingBakedWearPayload;

      if (vlmReviewStyle) {{
        setLitMaterial(limbMaterial, 0x2563eb, 0x000000, 0.0, 0.74, 0.0);
        setLitMaterial(torsoMaterial, 0x334155, 0x000000, 0.0, 0.78, 0.0);
        setLitMaterial(headMaterial, 0x7c3aed, 0x000000, 0.0, 0.72, 0.0);
        setLineMaterial(limbOutlineMaterial, 0x0f172a, 1.0);
        setLineMaterial(torsoOutlineMaterial, 0x0f172a, 1.0);
        setLineMaterial(headOutlineMaterial, 0x3b0764, 1.0);
        setLitMaterial(skeletonSurfaceMaterial, 0x2563eb, 0x000000, 0.0, 0.74, 0.0);
        setLitMaterial(jointNodeMaterial, 0xf97316, 0x000000, 0.0, 0.68, 0.0);
        setLineMaterial(skeletonLineMaterial, 0x0f172a, 0.72);
      }} else {{
        setLitMaterial(limbMaterial, 0x081317, 0x35f2ff, 0.62, 0.28, 0.2);
        setLitMaterial(torsoMaterial, 0x0a1519, 0x47f6ff, 0.78, 0.22, 0.24);
        setLitMaterial(headMaterial, 0x0d1a1f, 0x8afbff, 0.9, 0.16, 0.3);
        setLineMaterial(limbOutlineMaterial, 0x44f7ff, 0.95);
        setLineMaterial(torsoOutlineMaterial, 0x8bfdff, 0.98);
        setLineMaterial(headOutlineMaterial, 0xe9ffff, 1.0);
        setLitMaterial(skeletonSurfaceMaterial, 0x071014, 0x4ff7ff, 0.58, 0.18, 0.22);
        setLitMaterial(jointNodeMaterial, 0x0d171c, 0xc7ffff, 0.72, 0.14, 0.18);
        setLineMaterial(skeletonLineMaterial, 0x64f7ff, 0.22);
      }}
      refreshMergedBoundsHelper();
    }}

    const previewBoundsObjects = [
      ...proceduralBodyMeshes,
      ...skeletonLines.map((entry) => entry.line),
      ...skeletonSurfaces.map((entry) => entry.mesh),
      ...jointNodeMeshes.map((entry) => entry.mesh),
      ...comparisonLines.map((entry) => entry.line),
      ...comparisonNodeMeshes.map((entry) => entry.mesh),
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
          const worldPoint = toBaseWorldPoint(point, frameTranslation, false, jointName, currentFixedRoot);
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
      if (renderingBakedWearPayload && bakedWearReviewBounds?.sourceBounds) {{
        const bounds = bakedWearReviewBounds.sourceBounds;
        const height = Math.max(0.001, bounds.maxY - bounds.minY);
        const width = Math.max(0.001, bounds.maxX - bounds.minX);
        const depth = Math.max(0.001, bounds.maxZ - bounds.minZ);
        const floorSize = Math.max(width, depth) * 1.24;
        bakedWearGrid.position.set(
          (bounds.minX + bounds.maxX) * 0.5,
          bounds.minY - height * 0.014,
          (bounds.minZ + bounds.maxZ) * 0.5
        );
        bakedWearGrid.quaternion.identity();
        bakedWearGrid.scale.set(floorSize, 1.0, floorSize);
        bakedWearGrid.visible = true;
        grid.visible = false;
        return;
      }}
      bakedWearGrid.visible = false;
      const bounds = getCachedSceneBounds(fixedRoot);
      refreshSceneBasis();
      const renderGroundPlane = payload.ground?.renderGroundPlane;
      const groundNormal = renderGroundPlane?.normal;
      const groundOffset = Number(renderGroundPlane?.offset);
      const normalY = Array.isArray(groundNormal) && groundNormal.length >= 3
        ? Number(groundNormal[1])
        : Number.NaN;
      const authoritativeFloorY = Number.isFinite(groundOffset)
        && Number.isFinite(normalY)
        && Math.abs(normalY) >= 0.8
        ? -groundOffset / normalY
        : null;
      const visualClearance = Math.max(0, Number(payload.groundVisualClearance) || 0);
      const floorY = authoritativeFloorY == null
        ? bounds.minY + 0.08 - visualClearance
        : authoritativeFloorY - visualClearance;
      const localCenter = new THREE.Vector3(
        (bounds.minX + bounds.maxX) * 0.5,
        floorY,
        (bounds.minZ + bounds.maxZ) * 0.5
      );
      localCenter.sub(sceneOriginOffset);
      localCenter.applyQuaternion(sceneRotationQuaternion);
      grid.position.copy(localCenter);
      grid.quaternion.copy(sceneRotationQuaternion);
      grid.visible = !vlmReviewStyle;
    }}

    function refreshMergedBoundsHelper() {{
      if (vlmReviewStyle || !showBoundsHelper) {{
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

    function buildActiveRangeCacheKey() {{
      const frames = playbackState.frames ?? [];
      const firstFrame = frames[0] ?? null;
      const lastFrame = frames.length > 0 ? frames[frames.length - 1] : null;
      return [
        selectedLoopIndex,
        currentLoop?.startFrame ?? "",
        currentLoop?.endFrame ?? "",
        currentLoop?.startTimeSec ?? "",
        currentLoop?.endTimeSec ?? "",
        frames.length,
        frameFootLockKey(firstFrame),
        frameFootLockKey(lastFrame),
      ].join("|");
    }}

    function buildSceneBoundsCacheKey(currentFixedRoot) {{
      return `${{currentFixedRoot}}|${{lockYRoot}}|${{lockPlantedFeet}}|${{lockPlantedHands}}|${{autoWorldAlignmentEnabled}}|${{sceneInverted}}|${{manualModelRotationCacheKey()}}|${{buildActiveRangeCacheKey()}}|previewSagittalPlaneGridAlignment:v1`;
    }}

    function invalidateSceneBoundsCache() {{
      cachedSceneBoundsKey = null;
      cachedSceneBounds = null;
      previewSagittalPlaneAlignmentKey = null;
      previewSagittalPlaneAlignment = null;
      footLockCorrectionsKey = null;
      footLockCorrections = new Map();
      lockedJointFrameKey = null;
      lockedJointPositions = new Map();
      stableLegPoleVectorsKey = null;
      stableLegPoleVectors = new Map();
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
      requestPreviewRedraw();
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
      const activeFrames = frames.slice(
        Math.max(0, Math.min(frames.length - 1, startFrame)),
        Math.max(0, Math.min(frames.length, endFrame + 1))
      );
      if (activeFrames.length < 2) {{
        return activeFrames;
      }}
      return activeFrames;
    }}

    function buildPlaybackState(frames, loop) {{
      const activeFrames = buildPlaybackFrames(frames, loop);
      return {{
        frames: activeFrames,
        boundsFrames: activeFrames,
        loopable: Boolean(loop),
      }};
    }}

    function interpolateSyntheticLoopFrame(startFrame, endFrame, alpha, bridgeIndex) {{
      const joints = {{}};
      for (const jointName of payload.jointNames) {{
        const startPoint = startFrame?.joints?.[jointName];
        const endPoint = endFrame?.joints?.[jointName];
        if (!Array.isArray(startPoint) || startPoint.length < 3 || !Array.isArray(endPoint) || endPoint.length < 3) {{
          continue;
        }}
        joints[jointName] = [
          startPoint[0] * (1 - alpha) + endPoint[0] * alpha,
          startPoint[1] * (1 - alpha) + endPoint[1] * alpha,
          startPoint[2] * (1 - alpha) + endPoint[2] * alpha,
        ];
      }}
      const startTime = Number(startFrame?.timeSec) || 0;
      const endTime = Number(endFrame?.timeSec) || startTime;
      return {{
        ...startFrame,
        frameIndex: `bridge-${{bridgeIndex}}`,
        sourceIndexA: frameSourceIndexForMotionTuning(startFrame),
        sourceIndexB: frameSourceIndexForMotionTuning(endFrame),
        sourceAlpha: alpha,
        timeSec: startTime * (1 - alpha) + endTime * alpha,
        syntheticLoopBridge: true,
        joints,
      }};
    }}

    function frameSourceIndexForMotionTuning(frame) {{
      const value = frame?.sourceIndexA ?? frame?.frameIndex;
      return resolveSourceFrameIndex(value, 0);
    }}

    function computeActiveRootAnchor(frames) {{
      if (!frames || frames.length === 0) {{
        return null;
      }}
      const rootPoints = frames
        .map((frame) => getFrameStableRootPoint(frame))
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

    function getFrameStableRootPoint(frame) {{
      const jointNames = horizontalTorsoProfile
        ? ["pelvis", "left_hip", "right_hip", "spine1", "spine2", "spine3", "left_shoulder", "right_shoulder"]
        : [payload.rootJoint, "pelvis", "spine1"];
      const points = [];
      for (const jointName of jointNames) {{
        if (typeof jointName !== "string" || jointName.length === 0) {{
          continue;
        }}
        const point = frame.joints[jointName];
        if (Array.isArray(point) && point.length >= 3) {{
          points.push(new THREE.Vector3(point[0], point[1], point[2]));
        }}
      }}
      if (points.length === 0) {{
        return getFrameRootPoint(frame, payload.rootJoint);
      }}
      const center = new THREE.Vector3();
      points.forEach((point) => center.add(point));
      center.multiplyScalar(1 / points.length);
      return center;
    }}

    function isHorizontalTorsoFrame(frame) {{
      const pelvis = frame.joints.pelvis;
      const neck = frame.joints.neck ?? frame.joints.spine3 ?? frame.joints.head;
      if (!Array.isArray(pelvis) || !Array.isArray(neck)) {{
        return false;
      }}
      const spine = new THREE.Vector3(neck[0] - pelvis[0], neck[1] - pelvis[1], neck[2] - pelvis[2]);
      if (spine.lengthSq() <= 1e-8) {{
        return false;
      }}
      spine.normalize();
      return Math.abs(spine.y) < 0.55;
    }}

    function populateLoopSelect() {{
      loopSelect.innerHTML = "";
      const fullOption = document.createElement("option");
      fullOption.value = "-1";
      fullOption.textContent = "Full clip";
      loopSelect.appendChild(fullOption);
      loopSelect.value = String(selectedLoopIndex);
    }}

    function refreshActiveLoopLabel() {{
      activeLoopNode.textContent = currentLoop?.label ?? "Full clip";
    }}

    function sourceTimeBounds() {{
      const frames = Array.isArray(payload.frames) ? payload.frames : [];
      if (frames.length === 0) {{
        return {{ startSeconds: 0, endSeconds: 0 }};
      }}
      const first = frames.find((frame) => Number.isFinite(Number(frame?.timeSec)));
      const last = frames.slice().reverse().find((frame) => Number.isFinite(Number(frame?.timeSec)));
      const startSeconds = Number(first?.timeSec) || 0;
      const endSeconds = Number(last?.timeSec);
      return {{
        startSeconds,
        endSeconds: Number.isFinite(endSeconds) ? Math.max(startSeconds, endSeconds) : startSeconds,
      }};
    }}

    function formatSectionSeconds(value) {{
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed.toFixed(2) : "0.00";
    }}

    function activeRangeSeconds() {{
      if (currentLoop) {{
        return {{
          startSeconds: Number(currentLoop.startTimeSec) || 0,
          endSeconds: Number(currentLoop.endTimeSec) || 0,
        }};
      }}
      return sourceTimeBounds();
    }}

    function syncSectionRangeControlsToActiveRange() {{
      const bounds = sourceTimeBounds();
      const activeRange = activeRangeSeconds();
      sectionStartSecondsInput.min = formatSectionSeconds(bounds.startSeconds);
      sectionStartSecondsInput.max = formatSectionSeconds(bounds.endSeconds);
      sectionEndSecondsInput.min = formatSectionSeconds(bounds.startSeconds);
      sectionEndSecondsInput.max = formatSectionSeconds(bounds.endSeconds);
      sectionStartSecondsInput.value = formatSectionSeconds(activeRange.startSeconds);
      sectionEndSecondsInput.value = formatSectionSeconds(activeRange.endSeconds);
      sectionStartSecondsInput.setCustomValidity("");
      sectionEndSecondsInput.setCustomValidity("");
    }}

    function currentPlaybackFrame() {{
      const frames = playbackState.frames ?? [];
      if (frames.length === 0) {{
        return null;
      }}
      const index = playbackState.loopable
        ? ((Math.floor(frameCursor) % frames.length) + frames.length) % frames.length
        : Math.max(0, Math.min(frames.length - 1, Math.floor(frameCursor)));
      return frames[index] ?? null;
    }}

    function currentPlaybackSourceSeconds() {{
      const frame = currentPlaybackFrame();
      const value = Number(frame?.timeSec);
      return Number.isFinite(value) ? value : null;
    }}

    function setSectionBoundaryFromCurrentFrame(boundary) {{
      const seconds = currentPlaybackSourceSeconds();
      if (seconds == null) {{
        return;
      }}
      if (boundary === "start") {{
        sectionStartSecondsInput.value = formatSectionSeconds(seconds);
      }} else {{
        sectionEndSecondsInput.value = formatSectionSeconds(seconds);
      }}
      sectionStartSecondsInput.setCustomValidity("");
      sectionEndSecondsInput.setCustomValidity("");
    }}

    function applySectionRangeFromInputs() {{
      const start = Number(sectionStartSecondsInput.value);
      const end = Number(sectionEndSecondsInput.value);
      if (!Number.isFinite(start)) {{
        sectionStartSecondsInput.setCustomValidity("Invalid start seconds");
        sectionStartSecondsInput.reportValidity();
        return;
      }}
      if (!Number.isFinite(end) || end <= start) {{
        sectionEndSecondsInput.setCustomValidity("End must be after start");
        sectionEndSecondsInput.reportValidity();
        return;
      }}
      sectionStartSecondsInput.setCustomValidity("");
      sectionEndSecondsInput.setCustomValidity("");
      selectCustomTimeRange(start, end);
    }}

    function resetSectionRangeToFullClip() {{
      setSelectedLoop(-1);
    }}

    function setSelectedLoop(nextIndex) {{
      selectedLoopIndex = nextIndex;
      customTimeRange = null;
      currentLoop = selectedLoopIndex >= 0 && selectedLoopIndex < detectedLoops.length
        ? detectedLoops[selectedLoopIndex]
        : null;
      applyActiveRange();
    }}

    function selectCustomTimeRange(startSeconds, endSeconds) {{
      const start = Number(startSeconds);
      const end = Number(endSeconds);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {{
        throw new Error(`Invalid preview time range: ${{startSeconds}} -> ${{endSeconds}}`);
      }}
      customTimeRange = buildCustomTimeRange(start, end);
      selectedLoopIndex = -1;
      currentLoop = customTimeRange;
      loopSelect.value = "-1";
      applyActiveRange();
      return {{
        startSeconds: customTimeRange.startTimeSec,
        endSeconds: customTimeRange.endTimeSec,
        startFrame: customTimeRange.startFrame,
        endFrame: customTimeRange.endFrame,
        durationSec: customTimeRange.durationSec,
      }};
    }}

    function buildCustomTimeRange(startSeconds, endSeconds) {{
      const frames = Array.isArray(payload.frames) ? payload.frames : [];
      if (frames.length < 2) {{
        throw new Error("Cannot cut a preview time range without at least two frames.");
      }}
      let startFrame = frames.findIndex((frame) => Number(frame.timeSec) >= startSeconds);
      if (startFrame < 0) {{
        startFrame = frames.length - 2;
      }}
      let endFrame = -1;
      for (let index = frames.length - 1; index >= 0; index -= 1) {{
        if (Number(frames[index].timeSec) <= endSeconds) {{
          endFrame = index;
          break;
        }}
      }}
      if (endFrame <= startFrame) {{
        endFrame = Math.min(frames.length - 1, startFrame + 1);
      }}
      const resolvedStart = Number(frames[startFrame].timeSec) || 0;
      const resolvedEnd = Number(frames[endFrame].timeSec) || resolvedStart;
      return {{
        type: "llm_selected_time_range",
        startFrame,
        endFrame,
        startTimeSec: resolvedStart,
        endTimeSec: resolvedEnd,
        durationSec: Math.max(0, resolvedEnd - resolvedStart),
        label: `Selected section: ${{resolvedStart.toFixed(2)}}s -> ${{resolvedEnd.toFixed(2)}}s`,
      }};
    }}

    function applyActiveRange() {{
      currentAutoAlignment = currentLoop?.autoAlignment ?? defaultAutoAlignment;
      playbackState = buildPlaybackState(payload.frames, currentLoop);
      comparisonPlaybackState = buildPlaybackState(comparisonFrames, currentLoop);
      rawComparisonPlaybackState = buildPlaybackState(rawComparisonFrames, currentLoop);
      activeRootAnchor = computeActiveRootAnchor(playbackState.boundsFrames);
      activeHandSupportAnchor = computeActiveHandSupportAnchor(playbackState.boundsFrames);
      activeVerticalMovementAnchor = computeActiveVerticalMovementAnchor(playbackState.boundsFrames);
      invalidateSceneBoundsCache();
      frameCursor = findFrameCursorClosestToBoundsCenter();
      playbackDirection = 1;
      refreshActiveLoopLabel();
      syncSectionRangeControlsToActiveRange();
      applySceneReframe();
    }}

    function resize() {{
      const width = viewport.clientWidth;
      const height = viewport.clientHeight;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
      renderer.setSize(width, height, false);
      const aspect = width / Math.max(1, height);
      perspectiveCamera.aspect = aspect;
      perspectiveCamera.updateProjectionMatrix();
      refreshSceneFrame();
      updateCamera();
    }}

    function getFrameTranslation(frame, currentFixedRoot = fixedRoot) {{
      if (!currentFixedRoot) {{
        return [0, 0, 0];
      }}
      const rootPoint = getFrameStableRootPoint(frame);
      if (!rootPoint || !activeRootAnchor) {{
        return [0, 0, 0];
      }}
      const translation = [
        rootPoint.x - activeRootAnchor.x,
        lockYRoot ? rootPoint.y - activeRootAnchor.y : 0,
        rootPoint.z - activeRootAnchor.z,
      ];
      return clampFrameRootTranslation(frame, translation, lockYRoot);
    }}

    function computeActiveHandSupportAnchor(frames) {{
      if (!frames || frames.length === 0) {{
        return null;
      }}
      const points = frames
        .map((frame) => getFrameHandSupportPoint(frame))
        .filter((point) => point != null);
      if (points.length === 0) {{
        return null;
      }}
      return {{
        x: points.reduce((total, point) => total + point.x, 0) / points.length,
        y: points.reduce((total, point) => total + point.y, 0) / points.length,
        z: points.reduce((total, point) => total + point.z, 0) / points.length,
      }};
    }}

    function getFrameHandSupportPoint(frame) {{
      const points = [];
      for (const jointName of ["left_wrist", "right_wrist", "left_hand", "right_hand"]) {{
        const point = frame?.joints?.[jointName];
        if (Array.isArray(point) && point.length >= 3) {{
          points.push(new THREE.Vector3(point[0], point[1], point[2]));
        }}
      }}
      if (points.length === 0) {{
        return null;
      }}
      const center = new THREE.Vector3();
      points.forEach((point) => center.add(point));
      center.multiplyScalar(1 / points.length);
      return center;
    }}

    function computeActiveHandJointAnchors(frames) {{
      const anchors = new Map();
      if (!frames || frames.length === 0) {{
        return anchors;
      }}
      for (const jointName of availableHandJoints()) {{
        const xValues = [];
        const yValues = [];
        const zValues = [];
        for (const frame of frames) {{
          const point = frame?.joints?.[jointName];
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          const frameTranslation = fixedRoot ? getFrameTranslation(frame) : [0, 0, 0];
          const scenePoint = toUncorrectedWorldPoint(point, frameTranslation, frame);
          xValues.push(scenePoint.x);
          yValues.push(scenePoint.y);
          zValues.push(scenePoint.z);
        }}
        if (xValues.length >= 3) {{
          anchors.set(jointName, new THREE.Vector3(
            medianValue(xValues),
            medianValue(yValues),
            medianValue(zValues)
          ));
        }}
      }}
      return anchors;
    }}

    function getFrameMovementReferencePoint(frame) {{
      const preferredJoints = [
        "pelvis",
        "spine1",
        "spine2",
        "spine3",
        "neck",
        "head",
        "left_collar",
        "right_collar",
        "left_shoulder",
        "right_shoulder",
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
        "left_elbow",
        "right_elbow",
      ];
      const points = [];
      for (const jointName of preferredJoints) {{
        const point = frame?.joints?.[jointName];
        if (Array.isArray(point) && point.length >= 3) {{
          points.push(new THREE.Vector3(point[0], point[1], point[2]));
        }}
      }}
      if (points.length === 0) {{
        return getFrameStableRootPoint(frame);
      }}
      const center = new THREE.Vector3();
      points.forEach((point) => center.add(point));
      center.multiplyScalar(1 / points.length);
      return center;
    }}

    function computeActiveVerticalMovementAnchor(frames) {{
      if (!frames || frames.length < 3) {{
        return null;
      }}
      const points = [];
      for (const frame of frames) {{
        const point = getFrameMovementReferencePoint(frame);
        if (!point) {{
          continue;
        }}
        const frameTranslation = fixedRoot ? getFrameTranslation(frame) : [0, 0, 0];
        points.push(toUncorrectedWorldPoint([point.x, point.y, point.z], frameTranslation));
      }}
      if (points.length < 3) {{
        return null;
      }}
      const ranges = {{
        x: Math.max(...points.map((point) => point.x)) - Math.min(...points.map((point) => point.x)),
        y: Math.max(...points.map((point) => point.y)) - Math.min(...points.map((point) => point.y)),
        z: Math.max(...points.map((point) => point.z)) - Math.min(...points.map((point) => point.z)),
      }};
      if (ranges.y < Math.max(ranges.x, ranges.z) * 1.25) {{
        return null;
      }}
      return {{
        x: points.reduce((total, point) => total + point.x, 0) / points.length,
        z: points.reduce((total, point) => total + point.z, 0) / points.length,
      }};
    }}

    function verticalMovementCorrectionForFrame(frame, frameTranslation, jointName, includeSupportJoints = false) {{
      if (manualModelRotationOverridesAutoOrientation() || !autoWorldAlignmentEnabled || !activeVerticalMovementAnchor || !frame) {{
        return null;
      }}
      if (lockPlantedHands) {{
        return null;
      }}
      if (!includeSupportJoints && (
        (lockPlantedHands && isHandSupportJoint(jointName))
        || (lockPlantedFeet && isFootSupportJoint(jointName))
      )) {{
        return null;
      }}
      const point = getFrameMovementReferencePoint(frame);
      if (!point) {{
        return null;
      }}
      const worldPoint = toUncorrectedWorldPoint([point.x, point.y, point.z], frameTranslation);
      return new THREE.Vector3(
        worldPoint.x - activeVerticalMovementAnchor.x,
        0,
        worldPoint.z - activeVerticalMovementAnchor.z
      );
    }}

    function isHandSupportJoint(jointName) {{
      return typeof jointName === "string" && (
        jointName === "left_wrist"
        || jointName === "right_wrist"
        || jointName === "left_hand"
        || jointName === "right_hand"
      );
    }}

    function isFootSupportJoint(jointName) {{
      return typeof jointName === "string" && (
        jointName === "left_ankle"
        || jointName === "right_ankle"
        || jointName === "left_foot"
        || jointName === "right_foot"
      );
    }}

    function getFrameBakeTranslation(frame, lockYDrift) {{
      if (!fixedRoot) {{
        return [0, 0, 0];
      }}
      const rootPoint = getFrameStableRootPoint(frame);
      if (!rootPoint || !activeRootAnchor) {{
        return [0, 0, 0];
      }}
      const translation = [
        rootPoint.x - activeRootAnchor.x,
        lockYDrift ? rootPoint.y - activeRootAnchor.y : 0,
        rootPoint.z - activeRootAnchor.z,
      ];
      return clampFrameRootTranslation(frame, translation, lockYDrift);
    }}

    function clampFrameRootTranslation(frame, translation, lockYDrift) {{
      if (!horizontalTorsoProfile) {{
        return translation;
      }}
      return [
        clampRootTranslationValue(translation[0], 0.06),
        lockYDrift ? clampRootTranslationValue(translation[1], 0.018) : 0,
        clampRootTranslationValue(translation[2], 0.06),
      ];
    }}

    function clampRootTranslationValue(value, limit) {{
      if (!Number.isFinite(value)) {{
        return 0;
      }}
      return Math.max(-limit, Math.min(limit, value));
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
      if (
        manualModelRotationOverridesAutoOrientation()
        || !autoWorldAlignmentEnabled
        || !Array.isArray(currentAutoAlignment)
        || currentAutoAlignment.length === 0
      ) {{
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

    function toRootAdjustedPoint(point, frameTranslation) {{
      const tx = frameTranslation?.[0] ?? 0;
      const ty = frameTranslation?.[1] ?? 0;
      const tz = frameTranslation?.[2] ?? 0;
      return new THREE.Vector3(
        point[0] - tx,
        point[1] - ty,
        point[2] - tz
      );
    }}

    function applySceneTransform(point) {{
      const transformedPoint = applyAutoAlignment(point);
      if (sceneInverted) {{
        transformedPoint.applyAxisAngle(axisX, Math.PI);
      }}
      return transformedPoint;
    }}

    function sanitizeManualModelRotationDegrees(value, minDegrees, maxDegrees) {{
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) {{
        return 0.0;
      }}
      return Math.max(minDegrees, Math.min(maxDegrees, numeric));
    }}

    function manualModelRotationCacheKey() {{
      return [
        manualModelRotationXDegrees.toFixed(3),
        manualModelRotationYDegrees.toFixed(3),
        manualModelRotationZDegrees.toFixed(3),
      ].join(",");
    }}

    function manualModelRotationPayload() {{
      return {{
        x: manualModelRotationXDegrees,
        y: manualModelRotationYDegrees,
        z: manualModelRotationZDegrees,
      }};
    }}

    function manualModelRotationAxisSemanticsPayload() {{
      return {{
        x: "body_lateral_axis_sagittal_plane_normal",
        y: "world_y_axis",
        z: "body_sagittal_forward_axis",
      }};
    }}

    function manualModelRotationIsActive() {{
      return (
        Math.abs(manualModelRotationXDegrees) > 1e-6
        || Math.abs(manualModelRotationYDegrees) > 1e-6
        || Math.abs(manualModelRotationZDegrees) > 1e-6
      );
    }}

    function manualYawRotationIsActive() {{
      return Math.abs(manualModelRotationYDegrees) > 1e-6;
    }}

    function manualModelRotationOverridesAutoOrientation() {{
      return manualYawRotationIsActive() && !suppressManualModelRotation;
    }}

    function averageManualRotationVectors(vectors) {{
      const valid = vectors.filter((vector) => vector && vector.lengthSq() > 1e-8);
      if (valid.length === 0) {{
        return null;
      }}
      const averaged = new THREE.Vector3();
      for (const vector of valid) {{
        averaged.add(vector);
      }}
      averaged.multiplyScalar(1 / valid.length);
      return averaged.lengthSq() > 1e-8 ? averaged : null;
    }}

    function transformedManualRotationReferencePoint(frame, jointName, frameTranslation, currentFixedRoot = fixedRoot) {{
      const rawPoint = frame?.joints?.[jointName];
      if (!Array.isArray(rawPoint) || rawPoint.length < 3) {{
        return null;
      }}
      const transformed = toUncorrectedWorldPoint(rawPoint, frameTranslation, frame);
      if (!manualModelRotationOverridesAutoOrientation() && !suppressPreviewSagittalPlaneAlignment) {{
        applyPreviewSagittalPlaneAlignment(transformed, currentFixedRoot);
      }}
      return transformed;
    }}

    function bodyRelativeManualRotationAxes(frame, frameTranslation, currentFixedRoot = fixedRoot) {{
      if (!frame) {{
        return {{
          lateral: axisX.clone(),
          forward: axisZ.clone(),
        }};
      }}
      const transformedPoints = new Map();
      const pointForJoint = (jointName) => {{
        if (!transformedPoints.has(jointName)) {{
          transformedPoints.set(
            jointName,
            transformedManualRotationReferencePoint(frame, jointName, frameTranslation, currentFixedRoot)
          );
        }}
        return transformedPoints.get(jointName);
      }};
      const lateral = new THREE.Vector3();
      let lateralWeight = 0.0;
      for (const [leftName, rightName, pairWeight] of sagittalPlaneAlignmentPairs) {{
        const left = pointForJoint(leftName);
        const right = pointForJoint(rightName);
        if (!left || !right) {{
          continue;
        }}
        const direction = right.clone().sub(left);
        const length = direction.length();
        if (!Number.isFinite(length) || length <= 1e-5) {{
          continue;
        }}
        const weight = Number(pairWeight) * length;
        lateral.addScaledVector(direction.multiplyScalar(1 / length), weight);
        lateralWeight += weight;
      }}
      if (lateralWeight <= 1e-6 || lateral.lengthSq() <= 1e-8) {{
        lateral.copy(axisX);
      }} else {{
        lateral.normalize();
      }}

      const shoulderCenter = averageManualRotationVectors([
        pointForJoint("left_shoulder"),
        pointForJoint("right_shoulder"),
        pointForJoint("left_collar"),
        pointForJoint("right_collar"),
      ]);
      const hipCenter = averageManualRotationVectors([
        pointForJoint("left_hip"),
        pointForJoint("right_hip"),
        pointForJoint("pelvis"),
      ]);
      let bodyUp = null;
      if (shoulderCenter && hipCenter) {{
        bodyUp = shoulderCenter.clone().sub(hipCenter);
      }}
      if (!bodyUp || bodyUp.lengthSq() <= 1e-8) {{
        const neck = pointForJoint("neck") ?? pointForJoint("spine3") ?? pointForJoint("head");
        const pelvis = pointForJoint("pelvis");
        if (neck && pelvis) {{
          bodyUp = neck.clone().sub(pelvis);
        }}
      }}
      if (!bodyUp || bodyUp.lengthSq() <= 1e-8) {{
        bodyUp = axisY.clone();
      }}
      bodyUp.addScaledVector(lateral, -bodyUp.dot(lateral));
      if (bodyUp.lengthSq() <= 1e-8) {{
        bodyUp.copy(axisY).addScaledVector(lateral, -axisY.dot(lateral));
      }}
      if (bodyUp.lengthSq() <= 1e-8) {{
        bodyUp.copy(axisZ);
      }} else {{
        bodyUp.normalize();
      }}
      const forward = new THREE.Vector3().crossVectors(lateral, bodyUp);
      if (forward.lengthSq() <= 1e-8) {{
        forward.copy(axisZ);
      }} else {{
        forward.normalize();
      }}
      return {{
        lateral,
        forward,
      }};
    }}

    function applyManualModelRotation(point, frame = activeRenderFrame, frameTranslation = [0, 0, 0], currentFixedRoot = fixedRoot) {{
      if (suppressManualModelRotation || !manualModelRotationIsActive()) {{
        return point;
      }}
      const bodyAxes = (
        Math.abs(manualModelRotationXDegrees) > 1e-6
        || Math.abs(manualModelRotationZDegrees) > 1e-6
      )
        ? bodyRelativeManualRotationAxes(frame, frameTranslation, currentFixedRoot)
        : null;
      if (Math.abs(manualModelRotationXDegrees) > 1e-6) {{
        point.applyAxisAngle(bodyAxes?.lateral ?? axisX, manualModelRotationXDegrees * Math.PI / 180);
      }}
      if (Math.abs(manualModelRotationYDegrees) > 1e-6) {{
        point.applyAxisAngle(axisY, manualModelRotationYDegrees * Math.PI / 180);
      }}
      if (Math.abs(manualModelRotationZDegrees) > 1e-6) {{
        point.applyAxisAngle(bodyAxes?.forward ?? axisZ, manualModelRotationZDegrees * Math.PI / 180);
      }}
      return point;
    }}

    function syncManualModelRotationControls() {{
      manualModelRotationXDegrees = sanitizeManualModelRotationDegrees(manualModelRotationXDegrees, -90, 90);
      manualModelRotationYDegrees = sanitizeManualModelRotationDegrees(manualModelRotationYDegrees, -180, 180);
      manualModelRotationZDegrees = sanitizeManualModelRotationDegrees(manualModelRotationZDegrees, -90, 90);
      modelRotationXInput.value = String(manualModelRotationXDegrees);
      modelRotationYInput.value = String(manualModelRotationYDegrees);
      modelRotationZInput.value = String(manualModelRotationZDegrees);
      modelRotationXValue.textContent = `${{manualModelRotationXDegrees.toFixed(0)}}°`;
      modelRotationYValue.textContent = `${{manualModelRotationYDegrees.toFixed(0)}}°`;
      modelRotationZValue.textContent = `${{manualModelRotationZDegrees.toFixed(0)}}°`;
    }}

    function updateManualModelRotationFromControls() {{
      manualModelRotationXDegrees = sanitizeManualModelRotationDegrees(modelRotationXInput.value, -90, 90);
      manualModelRotationYDegrees = sanitizeManualModelRotationDegrees(modelRotationYInput.value, -180, 180);
      manualModelRotationZDegrees = sanitizeManualModelRotationDegrees(modelRotationZInput.value, -90, 90);
      syncManualModelRotationControls();
      activeVerticalMovementAnchor = computeActiveVerticalMovementAnchor(playbackState.boundsFrames);
      invalidateSceneBoundsCache();
      applySceneReframe();
    }}

    function toUncorrectedWorldPoint(point, frameTranslation, frame = activeRenderFrame) {{
      return applySceneTransform(toRootAdjustedPoint(point, frameTranslation));
    }}

    function computeLockedHandBodyDriftCorrection(frame) {{
      if (!lockPlantedHands || !frame) {{
        return null;
      }}
      const anchor = computeLockedHandBodyDriftAnchor();
      if (!anchor) {{
        return null;
      }}
      const bodyPoint = getFrameBodyMotionPointForHandLock(frame);
      const handSupportPoint = getFrameHandSupportPoint(frame);
      if (!bodyPoint || !handSupportPoint || !activeHandSupportAnchor) {{
        return null;
      }}
      const handLockedBodyPoint = new THREE.Vector3(
        bodyPoint.x - (handSupportPoint.x - activeHandSupportAnchor.x),
        bodyPoint.y - (handSupportPoint.y - activeHandSupportAnchor.y),
        bodyPoint.z - (handSupportPoint.z - activeHandSupportAnchor.z)
      );
      const alignedBodyPoint = applySceneTransform(handLockedBodyPoint);
      return {{
        x: alignedBodyPoint.x - anchor.x,
        z: alignedBodyPoint.z - anchor.z,
      }};
    }}

    function computeLockedHandBodyDriftAnchor() {{
      if (!lockPlantedHands || !activeHandSupportAnchor) {{
        return null;
      }}
      const cacheKey = `${{selectedLoopIndex}}|${{playbackState.frames?.length ?? 0}}|${{activeHandSupportAnchor.x}},${{activeHandSupportAnchor.y}},${{activeHandSupportAnchor.z}}|${{autoWorldAlignmentEnabled}}|${{sceneInverted}}|${{manualModelRotationCacheKey()}}`;
      if (lockedHandBodyDriftAnchorKey === cacheKey) {{
        return lockedHandBodyDriftAnchor;
      }}
      lockedHandBodyDriftAnchorKey = cacheKey;
      lockedHandBodyDriftAnchor = null;
      const xValues = [];
      const zValues = [];
      for (const frame of playbackState.frames ?? []) {{
        const bodyPoint = getFrameBodyMotionPointForHandLock(frame);
        const handSupportPoint = getFrameHandSupportPoint(frame);
        if (!bodyPoint || !handSupportPoint) {{
          continue;
        }}
        const handLockedBodyPoint = new THREE.Vector3(
          bodyPoint.x - (handSupportPoint.x - activeHandSupportAnchor.x),
          bodyPoint.y - (handSupportPoint.y - activeHandSupportAnchor.y),
          bodyPoint.z - (handSupportPoint.z - activeHandSupportAnchor.z)
        );
        const alignedBodyPoint = applySceneTransform(handLockedBodyPoint);
        xValues.push(alignedBodyPoint.x);
        zValues.push(alignedBodyPoint.z);
      }}
      if (xValues.length < 3 || zValues.length < 3) {{
        return null;
      }}
      lockedHandBodyDriftAnchor = {{
        x: medianValue(xValues),
        z: medianValue(zValues),
      }};
      return lockedHandBodyDriftAnchor;
    }}

    function applyLockedHandMovementAlignment(point) {{
      const transform = computeLockedHandMovementAlignmentTransform();
      if (!transform) {{
        return point;
      }}
      point.sub(transform.pivot);
      point.applyQuaternion(transform.quaternion);
      point.add(transform.pivot);
      return point;
    }}

    function computeLockedHandMovementAlignmentTransform() {{
      if (!lockPlantedHands || !activeHandSupportAnchor) {{
        return null;
      }}
      const cacheKey = `${{selectedLoopIndex}}|${{playbackState.frames?.length ?? 0}}|${{activeHandSupportAnchor.x}},${{activeHandSupportAnchor.y}},${{activeHandSupportAnchor.z}}|${{autoWorldAlignmentEnabled}}|${{sceneInverted}}|${{manualModelRotationCacheKey()}}`;
      if (lockedHandMovementAlignmentKey === cacheKey) {{
        return lockedHandMovementAlignmentTransform;
      }}
      lockedHandMovementAlignmentKey = cacheKey;
      lockedHandMovementAlignmentTransform = null;
      const points = [];
      for (const frame of playbackState.frames ?? []) {{
        const handSupportPoint = getFrameHandSupportPoint(frame);
        const bodyPoint = getFrameBodyMotionPointForHandLock(frame);
        if (!handSupportPoint || !bodyPoint) {{
          continue;
        }}
        points.push(applySceneTransform(new THREE.Vector3(
          bodyPoint.x - (handSupportPoint.x - activeHandSupportAnchor.x),
          bodyPoint.y - (handSupportPoint.y - activeHandSupportAnchor.y),
          bodyPoint.z - (handSupportPoint.z - activeHandSupportAnchor.z)
        )));
      }}
      if (points.length < 3) {{
        return null;
      }}
      const direction = visibleMovementDirectionFromPoints(points);
      if (!direction || direction.lengthSq() <= 1e-8) {{
        return null;
      }}
      direction.normalize();
      const target = direction.y >= 0 ? axisY.clone() : axisY.clone().multiplyScalar(-1);
      const rotationAxis = new THREE.Vector3().crossVectors(direction, target);
      rotationAxis.y = 0;
      if (rotationAxis.lengthSq() <= 1e-8) {{
        return null;
      }}
      rotationAxis.normalize();
      const horizontalError = Math.hypot(direction.x, direction.z);
      const angle = Math.atan2(horizontalError, Math.max(1e-8, Math.abs(direction.y)));
      if (!Number.isFinite(angle) || angle <= THREE.MathUtils.degToRad(0.5)) {{
        return null;
      }}
      lockedHandMovementAlignmentTransform = {{
        pivot: applySceneTransform(new THREE.Vector3(activeHandSupportAnchor.x, activeHandSupportAnchor.y, activeHandSupportAnchor.z)),
        quaternion: new THREE.Quaternion().setFromAxisAngle(rotationAxis, angle),
      }};
      return lockedHandMovementAlignmentTransform;
    }}

    function getFrameBodyMotionPointForHandLock(frame) {{
      const jointNames = [
        "pelvis",
        "spine1",
        "spine2",
        "spine3",
        "neck",
        "head",
        "left_hip",
        "right_hip",
        "left_shoulder",
        "right_shoulder",
      ];
      const points = [];
      for (const jointName of jointNames) {{
        const point = frame?.joints?.[jointName];
        if (Array.isArray(point) && point.length >= 3) {{
          points.push(new THREE.Vector3(point[0], point[1], point[2]));
        }}
      }}
      if (points.length === 0) {{
        return null;
      }}
      const center = new THREE.Vector3();
      points.forEach((point) => center.add(point));
      center.multiplyScalar(1 / points.length);
      return center;
    }}

    function principalDirectionFromPoints(points) {{
      if (!Array.isArray(points) || points.length < 3) {{
        return null;
      }}
      const center = new THREE.Vector3();
      points.forEach((point) => center.add(point));
      center.multiplyScalar(1 / points.length);
      let direction = points[points.length - 1].clone().sub(points[0]);
      if (direction.lengthSq() <= 1e-8) {{
        direction.set(0, 1, 0);
      }} else {{
        direction.normalize();
      }}
      for (let iteration = 0; iteration < 8; iteration += 1) {{
        const next = new THREE.Vector3();
        for (const point of points) {{
          const centered = point.clone().sub(center);
          next.addScaledVector(centered, centered.dot(direction));
        }}
        if (next.lengthSq() <= 1e-8) {{
          return null;
        }}
        direction.copy(next.normalize());
      }}
      const displacement = points[points.length - 1].clone().sub(points[0]);
      if (direction.dot(displacement) < 0) {{
        direction.multiplyScalar(-1);
      }}
      return direction;
    }}

    function visibleMovementDirectionFromPoints(points) {{
      if (!Array.isArray(points) || points.length < 2) {{
        return null;
      }}
      const displacement = points[points.length - 1].clone().sub(points[0]);
      if (displacement.lengthSq() > 1e-8) {{
        return displacement.normalize();
      }}
      return principalDirectionFromPoints(points);
    }}

    function applyFrameShoulderLeveling(point, frame, frameTranslation) {{
      const transform = computeFrameShoulderLevelingTransform(frame, frameTranslation);
      if (!transform) {{
        return point;
      }}
      point.sub(transform.pivot);
      point.applyQuaternion(transform.quaternion);
      point.add(transform.pivot);
      return point;
    }}

    function computeFrameShoulderLevelingTransform(frame, frameTranslation) {{
      if (manualModelRotationOverridesAutoOrientation() || lockPlantedHands || !autoWorldAlignmentEnabled || !frame) {{
        return null;
      }}
      const cacheKey = `${{frameFootLockKey(frame)}}|${{frameTranslation?.join(",") ?? ""}}|${{autoWorldAlignmentEnabled}}|${{sceneInverted}}|${{manualModelRotationCacheKey()}}`;
      if (frameShoulderLevelingKey === cacheKey) {{
        return frameShoulderLevelingTransform;
      }}
      frameShoulderLevelingKey = cacheKey;
      frameShoulderLevelingTransform = null;
      const left = frame.joints?.left_shoulder;
      const right = frame.joints?.right_shoulder;
      if (!Array.isArray(left) || left.length < 3 || !Array.isArray(right) || right.length < 3) {{
        return null;
      }}
      const tx = frameTranslation?.[0] ?? 0;
      const ty = frameTranslation?.[1] ?? 0;
      const tz = frameTranslation?.[2] ?? 0;
      const leftPoint = applySceneTransform(new THREE.Vector3(left[0] - tx, left[1] - ty, left[2] - tz));
      const rightPoint = applySceneTransform(new THREE.Vector3(right[0] - tx, right[1] - ty, right[2] - tz));
      const shoulderAxis = rightPoint.clone().sub(leftPoint);
      const horizontalAxis = new THREE.Vector3(shoulderAxis.x, 0, shoulderAxis.z);
      if (shoulderAxis.lengthSq() <= 1e-8 || horizontalAxis.lengthSq() <= 1e-8) {{
        return null;
      }}
      shoulderAxis.normalize();
      horizontalAxis.normalize();
      const angle = shoulderAxis.angleTo(horizontalAxis);
      if (!Number.isFinite(angle) || angle <= THREE.MathUtils.degToRad(0.25)) {{
        return null;
      }}
      const rotationAxis = new THREE.Vector3().crossVectors(shoulderAxis, horizontalAxis);
      if (rotationAxis.lengthSq() <= 1e-8) {{
        return null;
      }}
      rotationAxis.normalize();
      frameShoulderLevelingTransform = {{
        pivot: leftPoint.clone().add(rightPoint).multiplyScalar(0.5),
        quaternion: new THREE.Quaternion().setFromAxisAngle(rotationAxis, angle),
      }};
      return frameShoulderLevelingTransform;
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
      return ["left_ankle", "left_foot", "right_ankle", "right_foot"]
        .filter((jointName) => payload.jointNames.includes(jointName));
    }}

    function availableHandJoints() {{
      return ["left_wrist", "right_wrist", "left_hand", "right_hand"].filter((jointName) => payload.jointNames.includes(jointName));
    }}

    function isFootLockTarget(target) {{
      return lockPlantedFeet
        && typeof target?.jointName === "string"
        && (
          target.jointName === "left_ankle"
          || target.jointName === "left_foot"
          || target.jointName === "right_ankle"
          || target.jointName === "right_foot"
        );
    }}

    function computeLockedFootBodyTranslation(activeTargets, basePositions) {{
      if (!lockPlantedFeet || !Array.isArray(activeTargets) || activeTargets.length === 0) {{
        return null;
      }}
      const weightedTranslation = new THREE.Vector3();
      let totalWeight = 0;
      for (const target of activeTargets) {{
        if (
          !isFootLockTarget(target)
          || !String(target.jointName).endsWith("_ankle")
          || target.sourceConfirmedContinuousSupport
          || !basePositions.has(target.jointName)
        ) {{
          continue;
        }}
        const targetWeight = Math.max(0, Math.min(1, Number(target.weight) || 0));
        if (targetWeight <= 0) {{
          continue;
        }}
        const currentPoint = basePositions.get(target.jointName);
        const targetPoint = new THREE.Vector3(target.anchorX, target.anchorY, target.anchorZ);
        const desiredTranslation = targetPoint.sub(currentPoint);
        desiredTranslation.y = 0;
        weightedTranslation.addScaledVector(desiredTranslation, targetWeight);
        totalWeight += targetWeight;
      }}
      if (totalWeight <= 1e-6) {{
        return null;
      }}
      weightedTranslation.multiplyScalar(1 / totalWeight);
      if (weightedTranslation.lengthSq() <= 1e-10) {{
        return null;
      }}
      return weightedTranslation;
    }}

    function footSampleForFrame(frame, jointName) {{
      const point = frame?.joints?.[jointName];
      if (!Array.isArray(point) || point.length < 3) {{
        return null;
      }}
      const translation = fixedRoot ? getFrameTranslation(frame) : [0, 0, 0];
      const worldPoint = toUncorrectedWorldPoint(point, translation, frame);
      const verticalCorrection = verticalMovementCorrectionForFrame(
        frame,
        translation,
        jointName,
        true
      );
      if (verticalCorrection) {{
        worldPoint.sub(verticalCorrection);
      }}
      return worldPoint;
    }}

    function lockSampleForFrame(frame, jointName) {{
      return footSampleForFrame(frame, jointName);
    }}

    function sourceConfirmsContinuousFootSupport(jointName) {{
      if (!sourceFootSupportEvidence || typeof sourceFootSupportEvidence !== "object") {{
        return false;
      }}
      const side = String(jointName).startsWith("left_")
        ? "left"
        : (String(jointName).startsWith("right_") ? "right" : null);
      const evidence = side ? sourceFootSupportEvidence?.feet?.[side] : null;
      return Boolean(evidence?.continuousSupport);
    }}

    function buildLockTargetsForJoint(frames, jointName, targetsByFrameKey) {{
      const samples = frames.map((frame, index) => {{
        const point = lockSampleForFrame(frame, jointName);
        return point ? {{ frame, index, point }} : null;
      }});
      const validSamples = samples.filter((sample) => sample != null);
      if (validSamples.length === 0) {{
        return;
      }}
      const isHandJoint = jointName.includes("hand") || jointName.includes("wrist");
      const sourceConfirmedContinuousSupport = !isHandJoint
        && sourceConfirmsContinuousFootSupport(jointName);
      const contactSpeedMetersPerSecond = isHandJoint ? 0.25 : 0.32;
      const edgeSpeeds = samples.slice(0, -1).map((sample, index) => {{
        const next = samples[index + 1];
        if (!sample || !next) {{
          return null;
        }}
        const deltaSeconds = Math.max(
          Math.abs(Number(next.frame.timeSec) - Number(sample.frame.timeSec)),
          1 / Math.max(1, Number(payload.fps) || 30)
        );
        return next.point.distanceTo(sample.point) / deltaSeconds;
      }});
      const plantedSamples = sourceConfirmedContinuousSupport ? validSamples : samples.filter((sample, index) => {{
        if (!sample) {{
          return false;
        }}
        const localSpeeds = edgeSpeeds
          .slice(Math.max(0, index - 2), Math.min(edgeSpeeds.length, index + 2))
          .filter((speed) => Number.isFinite(speed));
        return localSpeeds.length > 0
          && medianValue(localSpeeds) <= contactSpeedMetersPerSecond;
      }});
      if (plantedSamples.length === 0) {{
        return;
      }}
      const plantedIndexes = new Set(plantedSamples.map((sample) => sample.index));
      const xRange = Math.max(...validSamples.map((sample) => sample.point.x))
        - Math.min(...validSamples.map((sample) => sample.point.x));
      const yRange = Math.max(...validSamples.map((sample) => sample.point.y))
        - Math.min(...validSamples.map((sample) => sample.point.y));
      const zRange = Math.max(...validSamples.map((sample) => sample.point.z))
        - Math.min(...validSamples.map((sample) => sample.point.z));
      const fullRangeRatio = Math.hypot(xRange, yRange, zRange)
        / Math.max(estimateAlignmentSkeletonScale(frames), 1e-6);
      const continuousSupport = sourceConfirmedContinuousSupport
        || plantedSamples.length / validSamples.length >= 0.8
        || fullRangeRatio <= 0.10;
      if (continuousSupport) {{
        for (const sample of validSamples) {{
          plantedIndexes.add(sample.index);
        }}
      }}
      const sortedPlantedIndexes = [...plantedIndexes].sort((left, right) => left - right);
      for (let index = 1; index < sortedPlantedIndexes.length; index += 1) {{
        const previous = sortedPlantedIndexes[index - 1];
        const next = sortedPlantedIndexes[index];
        if (next - previous <= 5) {{
          for (let fillIndex = previous + 1; fillIndex < next; fillIndex += 1) {{
            if (samples[fillIndex]) {{
              plantedIndexes.add(fillIndex);
            }}
          }}
        }}
      }}
      if (sortedPlantedIndexes.length > 0 && sortedPlantedIndexes[0] <= 4) {{
        for (let index = 0; index < sortedPlantedIndexes[0]; index += 1) {{
          if (samples[index]) {{
            plantedIndexes.add(index);
          }}
        }}
      }}
      const lastPlantedIndex = sortedPlantedIndexes[sortedPlantedIndexes.length - 1];
      if (Number.isInteger(lastPlantedIndex) && samples.length - 1 - lastPlantedIndex <= 4) {{
        for (let index = lastPlantedIndex + 1; index < samples.length; index += 1) {{
          if (samples[index]) {{
            plantedIndexes.add(index);
          }}
        }}
      }}
      const contactRuns = [];
      let currentRun = [];
      for (const sample of validSamples) {{
        if (plantedIndexes.has(sample.index)) {{
          if (currentRun.length > 0 && sample.index !== currentRun[currentRun.length - 1].index + 1) {{
            contactRuns.push(currentRun);
            currentRun = [];
          }}
          currentRun.push(sample);
        }} else if (currentRun.length > 0) {{
          contactRuns.push(currentRun);
          currentRun = [];
        }}
      }}
      if (currentRun.length > 0) {{
        contactRuns.push(currentRun);
      }}
      const minimumContactFrames = Math.max(2, Math.round((Number(payload.fps) || 30) * 0.12));
      for (const run of contactRuns) {{
        if (run.length < minimumContactFrames) {{
          continue;
        }}
        const anchorSamples = sourceConfirmedContinuousSupport
          ? run.slice(0, Math.max(3, Math.round((Number(payload.fps) || 30) * 0.15)))
          : run;
        const anchorPoint = new THREE.Vector3(
          medianValue(anchorSamples.map((sample) => sample.point.x)),
          medianValue(anchorSamples.map((sample) => sample.point.y)),
          medianValue(anchorSamples.map((sample) => sample.point.z))
        );
        const touchesStart = run[0].index === 0;
        const touchesEnd = run[run.length - 1].index === frames.length - 1;
        for (let runIndex = 0; runIndex < run.length; runIndex += 1) {{
          const sample = run[runIndex];
          const startWeight = touchesStart ? 1 : Math.min(1, (runIndex + 1) / 3);
          const endWeight = touchesEnd ? 1 : Math.min(1, (run.length - runIndex) / 3);
          const targets = targetsByFrameKey.get(frameFootLockKey(sample.frame));
          if (!targets) {{
            continue;
          }}
          targets.push({{
            jointName,
            anchorX: anchorPoint.x,
            anchorY: anchorPoint.y,
            anchorZ: anchorPoint.z,
            weight: Math.min(startWeight, endWeight),
            sourceConfirmedContinuousSupport,
          }});
        }}
      }}
    }}

    function computeFootLockCorrections() {{
      const key = buildSceneBoundsCacheKey(fixedRoot);
      if (footLockCorrectionsKey === key) {{
        return footLockCorrections;
      }}
      footLockCorrectionsKey = key;
      footLockCorrections = new Map();
      if (!lockPlantedFeet && !lockPlantedHands) {{
        return footLockCorrections;
      }}
      const frames = playbackState.frames ?? [];
      const lockJoints = [
        ...(lockPlantedFeet ? availableFootJoints() : []),
      ];
      if (frames.length === 0 || lockJoints.length === 0) {{
        return footLockCorrections;
      }}
      const loopTargets = [];
      const targetsByFrameKey = new Map(frames.map((frame) => {{
        const targets = [];
        loopTargets.push(targets);
        return [frameFootLockKey(frame), targets];
      }}));
      for (const jointName of lockJoints) {{
        buildLockTargetsForJoint(frames, jointName, targetsByFrameKey);
      }}
      if (lockPlantedHands) {{
        normalizeHandLockTargetHeights(targetsByFrameKey);
      }}
      for (const frame of frames) {{
        footLockCorrections.set(frameFootLockKey(frame), targetsByFrameKey.get(frameFootLockKey(frame)) ?? []);
      }}
      return footLockCorrections;
    }}

    function normalizeHandLockTargetHeights(targetsByFrameKey) {{
      const handTargets = [];
      for (const targets of targetsByFrameKey.values()) {{
        for (const target of targets) {{
          if (typeof target?.jointName === "string" && (target.jointName.includes("hand") || target.jointName.includes("wrist"))) {{
            handTargets.push(target);
          }}
        }}
      }}
      if (handTargets.length === 0) {{
        return;
      }}
      const sharedY = medianValue(handTargets.map((target) => Number(target.anchorY)).filter((value) => Number.isFinite(value)));
      for (const target of handTargets) {{
        target.anchorY = sharedY;
      }}
    }}

    function getFootLockTargets(frame) {{
      if ((!lockPlantedFeet && !lockPlantedHands) || !frame) {{
        return null;
      }}
      return computeFootLockCorrections().get(frameFootLockKey(frame)) ?? null;
    }}

    function computeStableLegPoleVectors() {{
      const cacheKey = `${{buildSceneBoundsCacheKey(fixedRoot)}}|stable-leg-bend|${{manualModelRotationCacheKey()}}`;
      if (stableLegPoleVectorsKey === cacheKey) {{
        return stableLegPoleVectors;
      }}
      stableLegPoleVectorsKey = cacheKey;
      stableLegPoleVectors = new Map();
      const frames = playbackState.boundsFrames ?? playbackState.frames ?? [];
      const bodyLateralSamples = [];
      let referenceBodyLateral = null;
      for (const frame of frames) {{
        for (const [leftName, rightName] of [
          ["left_hip", "right_hip"],
          ["left_shoulder", "right_shoulder"],
        ]) {{
          const left = lockSampleForFrame(frame, leftName);
          const right = lockSampleForFrame(frame, rightName);
          if (!left || !right) {{
            continue;
          }}
          const lateral = right.clone().sub(left);
          lateral.y = 0;
          if (lateral.lengthSq() <= 1e-8) {{
            continue;
          }}
          lateral.normalize();
          if (!referenceBodyLateral) {{
            referenceBodyLateral = lateral.clone();
          }} else if (lateral.dot(referenceBodyLateral) < 0) {{
            lateral.negate();
          }}
          bodyLateralSamples.push(lateral);
        }}
      }}
      let stableBodyLateral = null;
      if (bodyLateralSamples.length >= 3) {{
        stableBodyLateral = new THREE.Vector3(
          medianValue(bodyLateralSamples.map((axis) => axis.x)),
          medianValue(bodyLateralSamples.map((axis) => axis.y)),
          medianValue(bodyLateralSamples.map((axis) => axis.z))
        );
        if (stableBodyLateral.lengthSq() <= 1e-8) {{
          stableBodyLateral = null;
        }} else {{
          stableBodyLateral.normalize();
        }}
      }}
      stableBodyLateral = stableBodyLateral ?? sceneRight.clone();
      const stableBodyUp = axisY.clone();
      const stableBodyForward = new THREE.Vector3().crossVectors(
        stableBodyLateral,
        stableBodyUp
      ).normalize();
      for (const side of ["left", "right"]) {{
        const poleComponents = [];
        let referencePole = null;
        for (const frame of frames) {{
          const hip = lockSampleForFrame(frame, `${{side}}_hip`);
          const knee = lockSampleForFrame(frame, `${{side}}_knee`);
          const ankle = lockSampleForFrame(frame, `${{side}}_ankle`);
          if (!hip || !knee || !ankle) {{
            continue;
          }}
          const legAxis = ankle.clone().sub(hip);
          if (legAxis.lengthSq() <= 1e-8) {{
            continue;
          }}
          legAxis.normalize();
          const kneeOffset = knee.clone().sub(hip);
          const bendDirection = kneeOffset
            .clone()
            .sub(legAxis.clone().multiplyScalar(kneeOffset.dot(legAxis)));
          if (bendDirection.lengthSq() <= 1e-8) {{
            continue;
          }}
          bendDirection.normalize();
          if (!referencePole) {{
            referencePole = bendDirection.clone();
          }} else if (bendDirection.dot(referencePole) < 0) {{
            bendDirection.negate();
          }}
          poleComponents.push([
            bendDirection.dot(stableBodyLateral),
            bendDirection.dot(stableBodyUp),
            bendDirection.dot(stableBodyForward),
          ]);
        }}
        if (poleComponents.length < 3) {{
          continue;
        }}
        const stablePoleVector = new THREE.Vector3()
          .addScaledVector(
            stableBodyLateral,
            medianValue(poleComponents.map((components) => components[0]))
          )
          .addScaledVector(
            stableBodyUp,
            medianValue(poleComponents.map((components) => components[1]))
          )
          .addScaledVector(
            stableBodyForward,
            medianValue(poleComponents.map((components) => components[2]))
          );
        if (stablePoleVector.lengthSq() > 1e-8) {{
          stableLegPoleVectors.set(side, stablePoleVector.normalize());
        }}
      }}
      return stableLegPoleVectors;
    }}

    function computeLockedJointPositions(frame, frameTranslation) {{
      if ((!lockPlantedFeet && !lockPlantedHands) || !frame) {{
        lockedJointFrameKey = null;
        lockedJointPositions = new Map();
        return lockedJointPositions;
      }}
      const cacheKey = `${{frameFootLockKey(frame)}}|${{frameTranslation?.join(",") ?? ""}}|${{lockPlantedFeet}}|${{lockPlantedHands}}|${{autoWorldAlignmentEnabled}}|${{sceneInverted}}|${{manualModelRotationCacheKey()}}`;
      if (lockedJointFrameKey === cacheKey) {{
        return lockedJointPositions;
      }}
      lockedJointFrameKey = cacheKey;
      lockedJointPositions = new Map();
      const targets = getFootLockTargets(frame);
      const activeTargets = targets ? targets.slice() : [];
      if (lockPlantedHands) {{
        const handAnchors = computeActiveHandJointAnchors(playbackState.boundsFrames);
        for (const [jointName, anchor] of handAnchors.entries()) {{
          activeTargets.push({{
            jointName,
            anchorX: anchor.x,
            anchorY: anchor.y,
            anchorZ: anchor.z,
            weight: 1,
          }});
        }}
      }}
      if (activeTargets.length === 0) {{
        return lockedJointPositions;
      }}
      const basePositions = new Map();
      for (const jointName of payload.jointNames) {{
        const point = frame.joints[jointName];
        if (Array.isArray(point) && point.length >= 3) {{
          const worldPoint = toUncorrectedWorldPoint(point, frameTranslation, frame);
          const verticalCorrection = verticalMovementCorrectionForFrame(
            frame,
            frameTranslation,
            jointName,
            true
          );
          if (verticalCorrection) {{
            worldPoint.sub(verticalCorrection);
          }}
          basePositions.set(jointName, worldPoint);
        }}
      }}
      const bodyTranslation = computeLockedFootBodyTranslation(activeTargets, basePositions);
      if (bodyTranslation) {{
        for (const [jointName, point] of basePositions.entries()) {{
          const translatedPoint = point.clone().add(bodyTranslation);
          basePositions.set(jointName, translatedPoint);
          lockedJointPositions.set(jointName, translatedPoint.clone());
        }}
      }}
      const stablePoleVectors = computeStableLegPoleVectors();
      for (const side of ["left", "right"]) {{
        const ankleName = `${{side}}_ankle`;
        const footName = `${{side}}_foot`;
        const target = activeTargets.find((candidate) => candidate.jointName === ankleName);
        const footTarget = activeTargets.find((candidate) => candidate.jointName === footName);
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
        const originalHip = basePositions.get(`${{side}}_hip`);
        const originalKnee = basePositions.get(`${{side}}_knee`);
        let kneeLateralConstraint = null;
        if (
          originalHip
          && originalKnee
          && basePositions.has("left_hip")
          && basePositions.has("right_hip")
        ) {{
          const bodyLateralAxis = basePositions.get("right_hip")
            .clone()
            .sub(basePositions.get("left_hip"));
          bodyLateralAxis.y = 0;
          const originalLegAxis = originalAnkle.clone().sub(originalHip);
          const originalLegLengthSquared = originalLegAxis.lengthSq();
          if (
            bodyLateralAxis.lengthSq() > 1e-8
            && originalLegLengthSquared > 1e-8
          ) {{
            bodyLateralAxis.normalize();
            const hipToKnee = originalKnee.clone().sub(originalHip);
            const alongFraction = Math.max(0, Math.min(
              1,
              hipToKnee.dot(originalLegAxis) / originalLegLengthSquared
            ));
            const kneeFromLegLine = hipToKnee
              .clone()
              .sub(originalLegAxis.clone().multiplyScalar(alongFraction));
            kneeLateralConstraint = {{
              bodyLateralAxis,
              signedDeviation: kneeFromLegLine.dot(bodyLateralAxis),
            }};
          }}
        }}
        const ankleCorrection = new THREE.Vector3(target.anchorX, target.anchorY, target.anchorZ)
          .sub(originalAnkle)
          .multiplyScalar(targetWeight);
        const maxLocalCorrection = 0.025;
        if (target.sourceConfirmedContinuousSupport) {{
          const horizontalCorrection = new THREE.Vector3(
            ankleCorrection.x,
            0,
            ankleCorrection.z
          );
          if (horizontalCorrection.length() > maxLocalCorrection) {{
            horizontalCorrection.setLength(maxLocalCorrection);
          }}
          ankleCorrection.x = horizontalCorrection.x;
          ankleCorrection.z = horizontalCorrection.z;
        }} else if (ankleCorrection.length() > maxLocalCorrection) {{
          ankleCorrection.setLength(maxLocalCorrection);
        }}
        const blendedTarget = originalAnkle.clone().add(ankleCorrection);
        const solved = solveLegIkChain(
          chain.map((jointName) => basePositions.get(jointName).clone()),
          blendedTarget,
          stablePoleVectors.get(side) ?? null,
          kneeLateralConstraint
        );
        chain.forEach((jointName, index) => {{
          lockedJointPositions.set(jointName, solved[index]);
        }});
        if (basePositions.has(footName)) {{
          const originalAnkle = basePositions.get(ankleName);
          const originalFoot = basePositions.get(footName);
          const ankleToFoot = originalFoot.clone().sub(originalAnkle);
          if (footTarget && ankleToFoot.lengthSq() > 1e-10) {{
            const plantedFootDirection = new THREE.Vector3(
              footTarget.anchorX - target.anchorX,
              footTarget.anchorY - target.anchorY,
              footTarget.anchorZ - target.anchorZ
            );
            if (plantedFootDirection.lengthSq() > 1e-10) {{
              plantedFootDirection.setLength(ankleToFoot.length());
              lockedJointPositions.set(
                footName,
                solved[solved.length - 1].clone().add(plantedFootDirection)
              );
            }} else {{
              lockedJointPositions.set(footName, solved[solved.length - 1].clone().add(ankleToFoot));
            }}
          }} else {{
            lockedJointPositions.set(footName, solved[solved.length - 1].clone().add(ankleToFoot));
          }}
        }}
      }}
      for (const side of ["left", "right"]) {{
        const shoulderName = `${{side}}_shoulder`;
        const elbowName = `${{side}}_elbow`;
        const wristName = `${{side}}_wrist`;
        const handName = `${{side}}_hand`;
        const target = activeTargets.find((candidate) => candidate.jointName === wristName)
          ?? activeTargets.find((candidate) => candidate.jointName === handName);
        if (!target) {{
          continue;
        }}
        const targetWeight = Math.max(0, Math.min(1, Number(target.weight) || 0));
        if (targetWeight <= 0) {{
          continue;
        }}
        if ([shoulderName, elbowName, wristName].every((jointName) => basePositions.has(jointName))) {{
          const originalWrist = basePositions.get(wristName);
          let targetPoint = new THREE.Vector3(target.anchorX, target.anchorY, target.anchorZ);
          if (target.jointName === handName && basePositions.has(handName)) {{
            const wristToHand = basePositions.get(handName).clone().sub(originalWrist);
            targetPoint = targetPoint.clone().sub(wristToHand);
          }}
          const blendedTarget = originalWrist.clone().lerp(targetPoint, targetWeight);
          const solved = solveLegIkChain(
            [shoulderName, elbowName, wristName].map((jointName) => basePositions.get(jointName).clone()),
            blendedTarget
          );
          [shoulderName, elbowName, wristName].forEach((jointName, index) => {{
            lockedJointPositions.set(jointName, solved[index]);
          }});
          if (basePositions.has(handName)) {{
            const originalHand = basePositions.get(handName);
            const wristToHand = originalHand.clone().sub(originalWrist);
            lockedJointPositions.set(handName, solved[solved.length - 1].clone().add(wristToHand));
          }}
        }} else if (basePositions.has(target.jointName)) {{
          const originalPoint = basePositions.get(target.jointName);
          lockedJointPositions.set(
            target.jointName,
            originalPoint.clone().lerp(new THREE.Vector3(target.anchorX, target.anchorY, target.anchorZ), targetWeight)
          );
        }}
      }}
      return lockedJointPositions;
    }}

    function solveLegIkChain(
      points,
      target,
      stablePoleVector = null,
      kneeLateralConstraint = null
    ) {{
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
      const preferredBendDirection = stablePoleVector instanceof THREE.Vector3
        && stablePoleVector.lengthSq() > 1e-8
        ? stablePoleVector.clone()
        : sourceBendDirection.clone();
      let bendDirection = preferredBendDirection
        .clone()
        .sub(targetAxis.clone().multiplyScalar(preferredBendDirection.dot(targetAxis)));
      if (bendDirection.lengthSq() <= 1e-8) {{
        bendDirection = sourceBendDirection
          .clone()
          .sub(targetAxis.clone().multiplyScalar(sourceBendDirection.dot(targetAxis)));
      }}
      if (bendDirection.lengthSq() <= 1e-8) {{
        bendDirection = projectedAxis(sceneRight, targetAxis)
          ?? projectedAxis(sceneForward, targetAxis)
          ?? projectedAxis(axisY, targetAxis)
          ?? new THREE.Vector3(1, 0, 0);
      }}
      bendDirection.normalize();

      const kneeAlongAxis = (
        (upperLength * upperLength) - (lowerLength * lowerLength) + (solvedDistance * solvedDistance)
      ) / (2 * solvedDistance);
      const kneeBendDistance = Math.sqrt(Math.max(
        (upperLength * upperLength) - (kneeAlongAxis * kneeAlongAxis),
        0
      ));
      if (
        kneeBendDistance > 1e-6
        && kneeLateralConstraint?.bodyLateralAxis instanceof THREE.Vector3
        && Number.isFinite(Number(kneeLateralConstraint.signedDeviation))
      ) {{
        const lateralAxis = kneeLateralConstraint.bodyLateralAxis.clone().normalize();
        const lateralInBendPlane = lateralAxis
          .clone()
          .sub(targetAxis.clone().multiplyScalar(lateralAxis.dot(targetAxis)));
        const lateralProjectionMagnitude = lateralInBendPlane.length();
        if (lateralProjectionMagnitude > 1e-6) {{
          lateralInBendPlane.normalize();
          const desiredLateralCoefficient = Math.max(-0.98, Math.min(
            0.98,
            Number(kneeLateralConstraint.signedDeviation)
              / (kneeBendDistance * lateralProjectionMagnitude)
          ));
          const orthogonalBendDirection = new THREE.Vector3()
            .crossVectors(targetAxis, lateralInBendPlane)
            .normalize();
          if (orthogonalBendDirection.dot(bendDirection) < 0) {{
            orthogonalBendDirection.negate();
          }}
          bendDirection = lateralInBendPlane
            .clone()
            .multiplyScalar(desiredLateralCoefficient)
            .addScaledVector(
              orthogonalBendDirection,
              Math.sqrt(Math.max(0, 1 - desiredLateralCoefficient * desiredLateralCoefficient))
            )
            .normalize();
        }}
      }}
      const solvedKnee = root
        .clone()
        .addScaledVector(targetAxis, kneeAlongAxis)
        .addScaledVector(bendDirection, kneeBendDistance);
      return [root, solvedKnee, solvedAnkle];
    }}

    function previewSagittalPlaneAlignmentBasePayload(
      sampleCount,
      normalSource = "robust_torso_bilateral_axis",
      status = "not_enough_torso_bilateral_evidence"
    ) {{
      return {{
        enabled: true,
        targetAxis: "positive_x",
        targetForward: [1.0, 0.0, 0.0],
        targetNormal: [0.0, 0.0, 1.0],
        targetAxisMeaning: "body_sagittal_forward_axis",
        normalSource,
        applied: false,
        status,
        sampleCount,
      }};
    }}

    function manualModelRotationSkippedAlignmentPayload(sampleCount = 0) {{
      return {{
        ...previewSagittalPlaneAlignmentBasePayload(
          sampleCount,
          "manual_model_rotation",
          "skipped_manual_model_rotation"
        ),
        skippedReason: "manual_model_rotation_is_orientation_override",
        manualModelRotationDegrees: manualModelRotationPayload(),
      }};
    }}

    function sagittalAlignmentPayloadFromNormal(frames, basePayload, normalX, normalZ, coherence, extra = {{}}) {{
      const normalLength = Math.hypot(normalX, normalZ);
      if (!Number.isFinite(normalLength) || normalLength <= 1e-5) {{
        return {{
          ...basePayload,
          status: "ambiguous_alignment_normal",
          coherence,
          ...extra,
        }};
      }}
      const resolvedNormalX = normalX / normalLength;
      const resolvedNormalZ = normalZ / normalLength;
      // WHAM/SMPL facing is world-up x (right - left), not the inverse.
      const forwardX = resolvedNormalZ;
      const forwardZ = -resolvedNormalX;
      const currentAngle = Math.atan2(forwardZ, forwardX);
      const targetDirection = "+x";
      const yawRadians = normalizeSignedRadians(currentAngle);
      const yawDegrees = yawRadians * 180 / Math.PI;
      const applied = Math.abs(yawDegrees) >= 0.5;
      const bounds = computeBakedWearBounds(frames);
      const pivot = bounds.center ?? [0, 0, 0];
      return {{
        ...basePayload,
        applied,
        status: applied ? "applied" : "already_aligned",
        targetDirection,
        yawRadians: applied ? yawRadians : 0.0,
        yawDegrees: applied ? yawDegrees : 0.0,
        horizontalNormalBefore: [resolvedNormalX, 0.0, resolvedNormalZ],
        horizontalForwardBefore: [forwardX, 0.0, forwardZ],
        horizontalNormalAfter: applied
          ? [0.0, 0.0, 1.0]
          : [resolvedNormalX, 0.0, resolvedNormalZ],
        horizontalForwardAfter: applied
          ? [1.0, 0.0, 0.0]
          : [forwardX, 0.0, forwardZ],
        pivot,
        coherence,
        ...extra,
      }};
    }}

    function sagittalAlignmentPayloadFrom3dNormal(frames, basePayload, normal, coherence, extra = {{}}) {{
      const source = new THREE.Vector3(
        Number(normal?.[0]),
        Number(normal?.[1]),
        Number(normal?.[2])
      );
      if (![source.x, source.y, source.z].every(Number.isFinite) || source.length() <= 1e-5) {{
        return {{ ...basePayload, status: "ambiguous_alignment_normal", coherence, ...extra }};
      }}
      source.normalize();
      // A plane normal has no direction: n and -n identify the same plane.
      // Resolve to the nearest antipode so alignment cannot needlessly rotate
      // an upright athlete onto their side.
      const targetSign = source.z >= 0.0 ? 1.0 : -1.0;
      const target = new THREE.Vector3(0.0, 0.0, targetSign);
      const alignment = Math.max(-1.0, Math.min(1.0, source.dot(target)));
      const rotationRadians = Math.acos(alignment);
      const applied = Math.abs(rotationRadians * 180 / Math.PI) >= 0.5;
      const rotationAxis = new THREE.Vector3().crossVectors(source, target);
      if (rotationAxis.length() <= 1e-6) {{
        rotationAxis.set(0.0, 1.0, 0.0);
      }} else {{
        rotationAxis.normalize();
      }}
      const horizontalLength = Math.hypot(source.x, source.z);
      const horizontalNormal = horizontalLength > 1e-5
        ? [source.x / horizontalLength, 0.0, source.z / horizontalLength]
        : [0.0, 0.0, 0.0];
      const horizontalForward = [horizontalNormal[2], 0.0, -horizontalNormal[0]];
      const yawRadians = normalizeSignedRadians(Math.atan2(horizontalForward[2], horizontalForward[0]));
      const bounds = computeBakedWearBounds(frames);
      return {{
        ...basePayload,
        applied,
        status: applied ? "applied" : "already_aligned",
        targetDirection: targetSign > 0.0 ? "+x" : "-x",
        resolvedTargetNormal: [target.x, target.y, target.z],
        targetNormalSign: targetSign,
        rotationAxis: [rotationAxis.x, rotationAxis.y, rotationAxis.z],
        rotationRadians: applied ? rotationRadians : 0.0,
        rotationDegrees: applied ? rotationRadians * 180 / Math.PI : 0.0,
        yawRadians,
        yawDegrees: yawRadians * 180 / Math.PI,
        normalBefore: [source.x, source.y, source.z],
        normalAfter: applied ? [target.x, target.y, target.z] : [source.x, source.y, source.z],
        horizontalNormalBefore: horizontalNormal,
        horizontalForwardBefore: horizontalForward,
        horizontalNormalAfter: applied ? [target.x, 0.0, target.z] : horizontalNormal,
        horizontalForwardAfter: applied ? [targetSign, 0.0, 0.0] : horizontalForward,
        pivot: bounds.center ?? [0, 0, 0],
        coherence,
        ...extra,
      }};
    }}

    function medianNumber(values) {{
      const sorted = values.filter((value) => Number.isFinite(value)).sort((left, right) => left - right);
      if (sorted.length === 0) {{
        return 0.0;
      }}
      const middle = Math.floor(sorted.length / 2);
      return sorted.length % 2 === 1
        ? sorted[middle]
        : (sorted[middle - 1] + sorted[middle]) * 0.5;
    }}

    function averageSerializedPoints(points) {{
      if (!Array.isArray(points) || points.length === 0) {{
        return null;
      }}
      return [
        points.reduce((total, point) => total + Number(point[0]), 0) / points.length,
        points.reduce((total, point) => total + Number(point[1]), 0) / points.length,
        points.reduce((total, point) => total + Number(point[2]), 0) / points.length,
      ];
    }}

    function subtractSerializedPoints(left, right) {{
      return [
        Number(left[0]) - Number(right[0]),
        Number(left[1]) - Number(right[1]),
        Number(left[2]) - Number(right[2]),
      ];
    }}

    function smoothSerializedPointPath(points) {{
      if (!Array.isArray(points) || points.length < 3) {{
        return points;
      }}
      return points.map((point, index) => {{
        if (!point) {{
          return null;
        }}
        const window = [];
        for (let neighborIndex = Math.max(0, index - 2); neighborIndex < Math.min(points.length, index + 3); neighborIndex += 1) {{
          const neighbor = points[neighborIndex];
          if (neighbor) {{
            window.push(neighbor);
          }}
        }}
        return window.length > 0 ? averageSerializedPoints(window) : point;
      }});
    }}

    function principalDirection2dAlignment(samples) {{
      if (!Array.isArray(samples) || samples.length < 2) {{
        return null;
      }}
      const meanX = samples.reduce((total, sample) => total + Number(sample[0]), 0) / samples.length;
      const meanZ = samples.reduce((total, sample) => total + Number(sample[1]), 0) / samples.length;
      const centered = samples.map((sample) => [Number(sample[0]) - meanX, Number(sample[1]) - meanZ]);
      const covarianceXX = centered.reduce((total, sample) => total + sample[0] * sample[0], 0) / centered.length;
      const covarianceZZ = centered.reduce((total, sample) => total + sample[1] * sample[1], 0) / centered.length;
      const covarianceXZ = centered.reduce((total, sample) => total + sample[0] * sample[1], 0) / centered.length;
      const trace = covarianceXX + covarianceZZ;
      const determinant = covarianceXX * covarianceZZ - covarianceXZ * covarianceXZ;
      const discriminant = Math.max(0.0, trace * trace * 0.25 - determinant);
      const largestEigenvalue = trace * 0.5 + Math.sqrt(discriminant);
      let direction = [covarianceXZ, largestEigenvalue - covarianceXX];
      if (Math.abs(direction[0]) <= 1e-8 && Math.abs(direction[1]) <= 1e-8) {{
        direction = [largestEigenvalue - covarianceZZ, covarianceXZ];
      }}
      const length = Math.hypot(direction[0], direction[1]);
      if (!Number.isFinite(length) || length <= 1e-8) {{
        return null;
      }}
      return [direction[0] / length, direction[1] / length];
    }}

    function pointTrackRange2dAlignment(samples) {{
      if (!Array.isArray(samples) || samples.length < 2) {{
        return 0.0;
      }}
      const centerX = samples.reduce((total, sample) => total + Number(sample[0]), 0) / samples.length;
      const centerZ = samples.reduce((total, sample) => total + Number(sample[1]), 0) / samples.length;
      return Math.max(...samples.map((sample) => Math.hypot(Number(sample[0]) - centerX, Number(sample[1]) - centerZ))) * 2.0;
    }}

    function pointTrackRangeAlongDirection2dAlignment(samples, direction) {{
      const length = Math.hypot(Number(direction?.[0]), Number(direction?.[1]));
      if (!Array.isArray(samples) || samples.length < 2 || !Number.isFinite(length) || length <= 1e-8) {{
        return 0.0;
      }}
      const normalized = [Number(direction[0]) / length, Number(direction[1]) / length];
      const projections = samples.map((sample) => Number(sample[0]) * normalized[0] + Number(sample[1]) * normalized[1]);
      return Math.max(...projections) - Math.min(...projections);
    }}

    function movementPlaneGroupTrack(frames, jointNames, rootRelative) {{
      const rawPoints = [];
      for (const frame of frames) {{
        const points = [];
        for (const jointName of jointNames) {{
          const point = serializedJointPoint(frame, jointName);
          if (point) {{
            points.push(point);
          }}
        }}
        let averaged = averageSerializedPoints(points);
        const root = rootRelative ? serializedJointPoint(frame, "pelvis") : null;
        if (averaged && root) {{
          averaged = subtractSerializedPoints(averaged, root);
        }}
        rawPoints.push(averaged);
      }}
      return smoothSerializedPointPath(rawPoints).filter(Boolean);
    }}

    function movementPlaneJointTrack(frames, jointName, rootRelative) {{
      const rawPoints = [];
      for (const frame of frames) {{
        let point = serializedJointPoint(frame, jointName);
        const root = rootRelative ? serializedJointPoint(frame, "pelvis") : null;
        if (point && root) {{
          point = subtractSerializedPoints(point, root);
        }}
        rawPoints.push(point);
      }}
      return smoothSerializedPointPath(rawPoints).filter(Boolean);
    }}

    function estimateAlignmentSkeletonScale(frames) {{
      const lengths = [];
      const pairs = [
        ["left_shoulder", "right_shoulder"],
        ["left_hip", "right_hip"],
        ["pelvis", "neck"],
        ["pelvis", "spine3"],
        ["left_hip", "left_knee"],
        ["right_hip", "right_knee"],
        ["left_knee", "left_ankle"],
        ["right_knee", "right_ankle"],
      ];
      for (const frame of frames) {{
        for (const [firstName, secondName] of pairs) {{
          const first = serializedJointPoint(frame, firstName);
          const second = serializedJointPoint(frame, secondName);
          if (!first || !second) {{
            continue;
          }}
          const length = Math.hypot(
            Number(second[0]) - Number(first[0]),
            Number(second[1]) - Number(first[1]),
            Number(second[2]) - Number(first[2])
          );
          if (Number.isFinite(length) && length > 1e-5) {{
            lengths.push(length);
          }}
        }}
      }}
      return Math.max(0.25, medianNumber(lengths) * 4.0 || 1.0);
    }}

    function scoreMovementPlaneTrack(points, label, priority, scale) {{
      if (!Array.isArray(points) || points.length < 4) {{
        return null;
      }}
      const horizontalSamples = points.map((point) => [Number(point[0]), Number(point[2])]);
      const direction = principalDirection2dAlignment(horizontalSamples);
      if (!direction) {{
        return null;
      }}
      const horizontalRange = pointTrackRange2dAlignment(horizontalSamples);
      if (!Number.isFinite(horizontalRange) || horizontalRange <= 1e-6) {{
        return null;
      }}
      const rangeRatio = horizontalRange / Math.max(Number(scale) || 1.0, 1e-6);
      if (rangeRatio < movementPlaneAlignmentMinRangeRatio) {{
        return null;
      }}
      const axisRange = pointTrackRangeAlongDirection2dAlignment(horizontalSamples, direction);
      const coherence = axisRange / Math.max(horizontalRange, 1e-6);
      if (coherence < movementPlaneAlignmentMinCoherence) {{
        return null;
      }}
      const confidence = Math.min(1.0, (rangeRatio / 0.16) * 0.55 + coherence * 0.45);
      return {{
        label,
        sampleCount: points.length,
        direction,
        horizontalRange,
        rangeRatio,
        coherence: Math.min(1.0, coherence),
        confidence,
        score: horizontalRange * coherence * Math.max(0.0, Number(priority) || 0.0),
      }};
    }}

    function estimateMovementPlaneSagittalAlignment(frames) {{
      const scale = estimateAlignmentSkeletonScale(frames);
      const candidates = [];
      for (const [label, jointNames, rootRelative, priority] of movementPlaneAlignmentGroups) {{
        const candidate = scoreMovementPlaneTrack(
          movementPlaneGroupTrack(frames, jointNames, rootRelative),
          label,
          priority,
          scale
        );
        if (candidate) {{
          candidates.push(candidate);
        }}
      }}
      for (const [jointName, rootRelative, priority] of movementPlaneAlignmentJoints) {{
        const candidate = scoreMovementPlaneTrack(
          movementPlaneJointTrack(frames, jointName, rootRelative),
          jointName,
          priority,
          scale
        );
        if (candidate) {{
          candidates.push(candidate);
        }}
      }}
      candidates.sort((left, right) => right.score - left.score);
      const best = candidates[0];
      if (!best || best.confidence < movementPlaneAlignmentMinConfidence) {{
        return null;
      }}
      const directionX = Number(best.direction[0]);
      const directionZ = Number(best.direction[1]);
      const directionLength = Math.hypot(directionX, directionZ);
      if (!Number.isFinite(directionLength) || directionLength <= 1e-5) {{
        return null;
      }}
      const basePayload = previewSagittalPlaneAlignmentBasePayload(
        best.sampleCount,
        "dominant_movement_plane",
        "not_enough_movement_plane_evidence"
      );
      return sagittalAlignmentPayloadFromNormal(
        frames,
        basePayload,
        directionX / directionLength,
        directionZ / directionLength,
        best.coherence,
        {{
          alignmentAxisSource: "dominant_movement_direction",
          movementPlaneConfidence: best.confidence,
          movementPlaneTrack: best.label,
          movementPlaneRangeRatio: best.rangeRatio,
          movementPlaneHorizontalRange: best.horizontalRange,
          movementPlaneDirection: [directionX / directionLength, 0.0, directionZ / directionLength],
          fallbackNormalSource: "robust_torso_bilateral_axis",
        }}
      );
    }}

    function estimatePreviewSagittalPlaneAlignment(currentFixedRoot = fixedRoot) {{
      const frames = playbackState.boundsFrames ?? playbackState.frames ?? [];
      const alignmentFrames = [];
      const previousActiveFrame = activeRenderFrame;
      const previousSuppressPreviewSagittalPlaneAlignment = suppressPreviewSagittalPlaneAlignment;
      const previousSuppressManualModelRotation = suppressManualModelRotation;
      suppressPreviewSagittalPlaneAlignment = true;
      suppressManualModelRotation = true;
      try {{
        for (const frame of frames) {{
          activeRenderFrame = frame;
          const frameTranslation = currentFixedRoot ? getFrameTranslation(frame, currentFixedRoot) : [0, 0, 0];
          const transformedJoints = {{}};
          for (const jointName of payload.jointNames) {{
            const point = frame?.joints?.[jointName];
            if (!Array.isArray(point) || point.length < 3) {{
              continue;
            }}
            const worldPoint = toBaseWorldPoint(point, frameTranslation, false, jointName, currentFixedRoot);
            transformedJoints[jointName] = [worldPoint.x, worldPoint.y, worldPoint.z];
          }}
          if (Object.keys(transformedJoints).length > 0) {{
            alignmentFrames.push({{ joints: transformedJoints }});
          }}
        }}
      }} finally {{
        suppressPreviewSagittalPlaneAlignment = previousSuppressPreviewSagittalPlaneAlignment;
        suppressManualModelRotation = previousSuppressManualModelRotation;
        activeRenderFrame = previousActiveFrame;
      }}

      const estimate = estimateRobustTorsoBilateralNormal(alignmentFrames);
      const basePayload = previewSagittalPlaneAlignmentBasePayload(
        estimate.frameNormals.length,
        "robust_torso_bilateral_axis",
        "not_enough_torso_bilateral_evidence"
      );
      if (!estimate.normal) {{
        return basePayload;
      }}

      return sagittalAlignmentPayloadFrom3dNormal(
        alignmentFrames,
        basePayload,
        estimate.normal,
        estimate.coherence,
        {{
          estimator: "component_median_of_per_frame_3d_torso_axes",
          pairSampleCount: estimate.pairSampleCount,
          torsoPairs: sagittalPlaneAlignmentPairs.map(([leftName, rightName]) => [leftName, rightName]),
        }}
      );
    }}

    function getPreviewSagittalPlaneAlignment(currentFixedRoot = fixedRoot) {{
      if (manualModelRotationOverridesAutoOrientation()) {{
        return manualModelRotationSkippedAlignmentPayload(playbackState.boundsFrames?.length ?? 0);
      }}
      const key = buildSceneBoundsCacheKey(currentFixedRoot);
      if (previewSagittalPlaneAlignmentKey !== key || previewSagittalPlaneAlignment == null) {{
        previewSagittalPlaneAlignment = estimatePreviewSagittalPlaneAlignment(currentFixedRoot);
        previewSagittalPlaneAlignmentKey = key;
      }}
      return previewSagittalPlaneAlignment;
    }}

    function applyPreviewSagittalPlaneAlignment(point, currentFixedRoot = fixedRoot) {{
      const alignment = getPreviewSagittalPlaneAlignment(currentFixedRoot);
      if (!alignment?.applied) {{
        return point;
      }}
      const pivot = Array.isArray(alignment.pivot) && alignment.pivot.length >= 3
        ? alignment.pivot
        : [0.0, 0.0, 0.0];
      const axis = Array.isArray(alignment.rotationAxis) && alignment.rotationAxis.length >= 3
        ? new THREE.Vector3(...alignment.rotationAxis.map(Number)).normalize()
        : new THREE.Vector3(0.0, 1.0, 0.0);
      const angle = Number(alignment.rotationRadians ?? alignment.yawRadians) || 0.0;
      point.sub(new THREE.Vector3(...pivot.map(Number)));
      point.applyAxisAngle(axis, angle);
      point.add(new THREE.Vector3(...pivot.map(Number)));
      return point;
    }}

    function toBaseWorldPoint(point, frameTranslation, applySceneOriginOffset = true, jointName = null, currentFixedRoot = fixedRoot) {{
      if (renderingBakedWearPayload) {{
        return new THREE.Vector3(Number(point[0]), Number(point[1]), Number(point[2]));
      }}
      const lockedPositions = computeLockedJointPositions(activeRenderFrame, frameTranslation);
      const lockedPosition = typeof jointName === "string" && lockedPositions.has(jointName)
        ? lockedPositions.get(jointName)
        : null;
      const transformedPoint = lockedPosition
        ? lockedPosition.clone()
        : toUncorrectedWorldPoint(point, frameTranslation);
      const verticalCorrection = lockedPosition
        ? null
        : verticalMovementCorrectionForFrame(activeRenderFrame, frameTranslation, jointName);
      if (verticalCorrection) {{
        transformedPoint.sub(verticalCorrection);
      }}
      if (!manualModelRotationOverridesAutoOrientation() && !suppressPreviewSagittalPlaneAlignment) {{
        applyPreviewSagittalPlaneAlignment(transformedPoint, currentFixedRoot);
      }}
      applyManualModelRotation(transformedPoint, activeRenderFrame, frameTranslation, currentFixedRoot);
      if (applySceneOriginOffset && !suppressSceneOriginOffset) {{
        transformedPoint.sub(sceneOriginOffset);
      }}
      return transformedPoint;
    }}

    function toWorldPoint(point, frameTranslation, currentFixedRoot = fixedRoot, applySceneOriginOffset = true, jointName = null) {{
      return toBaseWorldPoint(point, frameTranslation, applySceneOriginOffset, jointName, currentFixedRoot);
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

    function stableWearReviewBounds(exportPayload, frames) {{
      const fallback = computeBakedWearBounds(frames);
      const exported = exportPayload?.bounds ?? {{}};
      const finiteOrFallback = (name) => {{
        const value = Number(exported[name]);
        return Number.isFinite(value) ? value : Number(fallback[name]);
      }};
      const minX = finiteOrFallback("minX");
      const maxX = finiteOrFallback("maxX");
      const minY = finiteOrFallback("minY");
      const maxY = finiteOrFallback("maxY");
      const minZ = finiteOrFallback("minZ");
      const maxZ = finiteOrFallback("maxZ");
      const height = Math.max(0.001, maxY - minY);
      const width = Math.max(0.001, maxX - minX);
      const depth = Math.max(0.001, maxZ - minZ);
      const horizontalPadding = Math.max(width, depth) * 0.28;
      const bottomPadding = height * 0.04;
      const topPadding = height * 0.20;
      const stable = {{
        minX: minX - horizontalPadding,
        maxX: maxX + horizontalPadding,
        minY: minY - bottomPadding,
        maxY: maxY + topPadding,
        minZ: minZ - horizontalPadding,
        maxZ: maxZ + horizontalPadding,
        sourceBounds: {{ minX, maxX, minY, maxY, minZ, maxZ }},
      }};
      stable.center = new THREE.Vector3(
        (stable.minX + stable.maxX) * 0.5,
        (stable.minY + stable.maxY) * 0.5,
        (stable.minZ + stable.maxZ) * 0.5
      );
      const halfWidth = Math.max(0.001, (stable.maxX - stable.minX) * 0.5);
      const halfHeight = Math.max(0.001, (stable.maxY - stable.minY) * 0.5);
      const halfDepth = Math.max(0.001, (stable.maxZ - stable.minZ) * 0.5);
      stable.radius = Math.max(
        0.001,
        Math.sqrt(halfWidth ** 2 + halfHeight ** 2 + halfDepth ** 2)
      );
      return stable;
    }}

    function sanitizedPlaybackSpeed(value) {{
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) {{
        return 1.0;
      }}
      return Math.max(0.5, Math.min(1.5, parsed));
    }}

    function normalizeBakedWearSkeletonCoordinates(frames, removeSceneInversion) {{
      if (!removeSceneInversion) {{
        return {{
          frames,
          metadata: {{
            canonicalWorldUp: true,
            sceneInversionRemoved: false,
            transform: "none",
          }},
        }};
      }}
      const normalizedFrames = frames.map((frame) => {{
        const joints = {{}};
        for (const [jointName, point] of Object.entries(frame.joints ?? {{}})) {{
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          joints[jointName] = [point[0], -point[1], -point[2]];
        }}
        return {{
          ...frame,
          joints,
        }};
      }});
      return {{
        frames: normalizedFrames,
        metadata: {{
          canonicalWorldUp: true,
          sceneInversionRemoved: true,
          transform: "rotate_x_pi",
          reason: "removed_display_scene_inversion_from_wear_coordinates",
        }},
      }};
    }}

    const sagittalPlaneAlignmentPairs = [
      ["left_shoulder", "right_shoulder", 2.0],
      ["left_collar", "right_collar", 1.5],
      ["left_hip", "right_hip", 1.8],
    ];

    const movementPlaneAlignmentMinRangeRatio = 0.035;
    const movementPlaneAlignmentMinCoherence = 0.55;
    const movementPlaneAlignmentMinConfidence = 0.58;
    const movementPlaneAlignmentGroups = [
      ["shoulder_center", ["left_shoulder", "right_shoulder", "left_collar", "right_collar", "neck", "spine3"], false, 1.35],
      ["torso", ["pelvis", "spine1", "spine2", "spine3", "neck", "left_hip", "right_hip", "left_shoulder", "right_shoulder"], false, 1.25],
      ["hip_center", ["pelvis", "left_hip", "right_hip"], false, 1.10],
      ["upper_body_relative", ["left_shoulder", "right_shoulder", "left_collar", "right_collar", "neck", "spine3"], true, 1.05],
      ["left_arm_relative", ["left_shoulder", "left_elbow", "left_wrist", "left_hand"], true, 0.95],
      ["right_arm_relative", ["right_shoulder", "right_elbow", "right_wrist", "right_hand"], true, 0.95],
      ["left_leg_relative", ["left_hip", "left_knee", "left_ankle", "left_foot"], true, 0.92],
      ["right_leg_relative", ["right_hip", "right_knee", "right_ankle", "right_foot"], true, 0.92],
      ["hand_center_relative", ["left_hand", "right_hand", "left_wrist", "right_wrist"], true, 0.86],
      ["foot_center_relative", ["left_foot", "right_foot", "left_ankle", "right_ankle"], true, 0.80],
    ];
    const movementPlaneAlignmentJoints = [
      ["left_shoulder", true, 0.90],
      ["right_shoulder", true, 0.90],
      ["left_elbow", true, 0.86],
      ["right_elbow", true, 0.86],
      ["left_wrist", true, 0.82],
      ["right_wrist", true, 0.82],
      ["left_hand", true, 0.82],
      ["right_hand", true, 0.82],
      ["left_knee", true, 0.84],
      ["right_knee", true, 0.84],
      ["left_ankle", true, 0.78],
      ["right_ankle", true, 0.78],
      ["left_foot", true, 0.76],
      ["right_foot", true, 0.76],
    ];

    function normalizeSignedRadians(angle) {{
      let normalized = Number(angle) || 0;
      while (normalized <= -Math.PI) {{
        normalized += Math.PI * 2;
      }}
      while (normalized > Math.PI) {{
        normalized -= Math.PI * 2;
      }}
      return normalized;
    }}

    function serializedJointPoint(frame, jointName) {{
      const point = frame?.joints?.[jointName];
      return Array.isArray(point) && point.length >= 3 ? point : null;
    }}

    function estimateRobustTorsoBilateralNormal(frames) {{
      const frameNormals = [];
      let pairSampleCount = 0;

      for (const frame of frames) {{
        let frameX = 0.0;
        let frameY = 0.0;
        let frameZ = 0.0;
        let frameWeight = 0.0;
        for (const [leftName, rightName, pairWeight] of sagittalPlaneAlignmentPairs) {{
          const left = serializedJointPoint(frame, leftName);
          const right = serializedJointPoint(frame, rightName);
          if (!left || !right) {{
            continue;
          }}
          const dx = Number(right[0]) - Number(left[0]);
          const dy = Number(right[1]) - Number(left[1]);
          const dz = Number(right[2]) - Number(left[2]);
          const length = Math.hypot(dx, dy, dz);
          if (!Number.isFinite(length) || length <= 1e-5) {{
            continue;
          }}
          const weight = Number(pairWeight);
          frameX += dx / length * weight;
          frameY += dy / length * weight;
          frameZ += dz / length * weight;
          frameWeight += weight;
          pairSampleCount += 1;
        }}
        const frameLength = Math.hypot(frameX, frameY, frameZ);
        if (frameWeight > 0.0 && Number.isFinite(frameLength) && frameLength > 1e-5) {{
          frameNormals.push([frameX / frameLength, frameY / frameLength, frameZ / frameLength]);
        }}
      }}

      if (frameNormals.length === 0) {{
        return {{ frameNormals, pairSampleCount, normal: null, coherence: 0.0 }};
      }}

      const robust = new THREE.Vector3(
        medianNumber(frameNormals.map((normal) => normal[0])),
        medianNumber(frameNormals.map((normal) => normal[1])),
        medianNumber(frameNormals.map((normal) => normal[2]))
      ).normalize();
      const coherence = Math.max(0.0, Math.min(
        1.0,
        frameNormals.reduce(
          (total, normal) => total + robust.x * normal[0] + robust.y * normal[1] + robust.z * normal[2],
          0.0
        ) / frameNormals.length
      ));
      return {{
        frameNormals,
        pairSampleCount,
        normal: [robust.x, robust.y, robust.z],
        coherence,
      }};
    }}

    function estimateBakedSagittalPlaneAlignment(frames) {{
      const estimate = estimateRobustTorsoBilateralNormal(frames);
      const basePayload = previewSagittalPlaneAlignmentBasePayload(
        estimate.frameNormals.length,
        "robust_torso_bilateral_axis",
        "not_enough_torso_bilateral_evidence"
      );
      if (!estimate.normal) {{
        return basePayload;
      }}

      return sagittalAlignmentPayloadFrom3dNormal(
        frames,
        basePayload,
        estimate.normal,
        estimate.coherence,
        {{
          estimator: "component_median_of_per_frame_3d_torso_axes",
          pairSampleCount: estimate.pairSampleCount,
          torsoPairs: sagittalPlaneAlignmentPairs.map(([leftName, rightName]) => [leftName, rightName]),
        }}
      );
    }}

    function rotateBakedWearFramesToSagittalPlane(frames, alignment) {{
      if (!alignment?.applied) {{
        return frames;
      }}
      const axis = Array.isArray(alignment.rotationAxis) && alignment.rotationAxis.length >= 3
        ? new THREE.Vector3(...alignment.rotationAxis.map(Number)).normalize()
        : new THREE.Vector3(0.0, 1.0, 0.0);
      const angle = Number(alignment.rotationRadians ?? alignment.yawRadians) || 0.0;
      const pivot = Array.isArray(alignment.pivot) && alignment.pivot.length >= 3
        ? alignment.pivot
        : [0.0, 0.0, 0.0];
      const pivotVector = new THREE.Vector3(...pivot.map(Number));
      return frames.map((frame) => {{
        const joints = {{}};
        for (const [jointName, point] of Object.entries(frame.joints ?? {{}})) {{
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          const rotated = new THREE.Vector3(...point.map(Number))
            .sub(pivotVector)
            .applyAxisAngle(axis, angle)
            .add(pivotVector);
          joints[jointName] = [rotated.x, rotated.y, rotated.z];
        }}
        return {{
          ...frame,
          joints,
        }};
      }});
    }}

    function normalizeViewYawDegrees(value) {{
      const degrees = Number(value) || 0.0;
      return ((degrees + 180.0) % 360.0 + 360.0) % 360.0 - 180.0;
    }}

    function alignBakedSagittalPlaneToGridAxis(frames) {{
      const alignment = estimateBakedSagittalPlaneAlignment(frames);
      if (manualModelRotationOverridesAutoOrientation()) {{
        return {{
          frames,
          alignment: {{
            ...alignment,
            applied: false,
            status: "skipped_manual_model_rotation",
            skippedReason: "manual_model_rotation_is_orientation_override",
            suggestedRotationAxis: alignment?.rotationAxis ?? null,
            suggestedRotationRadians: Number(alignment?.rotationRadians) || 0.0,
            suggestedRotationDegrees: Number(alignment?.rotationDegrees) || 0.0,
            suggestedYawRadians: Number(alignment?.yawRadians) || 0.0,
            suggestedYawDegrees: Number(alignment?.yawDegrees) || 0.0,
            rotationAxis: [0.0, 1.0, 0.0],
            rotationRadians: 0.0,
            rotationDegrees: 0.0,
            yawRadians: 0.0,
            yawDegrees: 0.0,
            horizontalNormalAfter: alignment?.horizontalNormalBefore ?? alignment?.horizontalNormalAfter,
            manualModelRotationDegrees: manualModelRotationPayload(),
          }},
        }};
      }}
      return {{
        frames: rotateBakedWearFramesToSagittalPlane(frames, alignment),
        alignment,
      }};
    }}

    function buildBakedWearSkeletonPayload() {{
      const activeFrames = playbackState.frames ?? [];
      const lockYDrift = Boolean(lockYRootInput.checked);
      const exportPlaybackSpeed = sanitizedPlaybackSpeed(speed);
      const exportFps = Math.max(1, Number(payload.fps) * exportPlaybackSpeed);
      const exportCameraYawDegrees = yaw * 180 / Math.PI;
      const exportCameraPitchDegrees = pitch * 180 / Math.PI;
      const selectedPreviewSettings = {{
        fixedRoot,
        autoWorldAlignment: autoWorldAlignmentEnabled,
        lockYDrift,
        lockPlantedFeet,
        lockPlantedHands,
        sourceFootSupportEvidence,
        sceneInverted,
        manualModelRotationDegrees: manualModelRotationPayload(),
        manualModelRotationAxisSemantics: manualModelRotationAxisSemanticsPayload(),
        cameraYawDegrees: exportCameraYawDegrees,
        cameraPitchDegrees: exportCameraPitchDegrees,
        playbackSpeed: exportPlaybackSpeed,
      }};
      getCachedSceneBounds(fixedRoot);
      const previewSagittalPlaneAlignmentForExport = getPreviewSagittalPlaneAlignment(selectedPreviewSettings.fixedRoot);
      const firstSourceTime = activeFrames.length > 0 ? activeFrames[0].timeSec : 0;
      let frames = activeFrames.map((frame, index) => {{
        activeRenderFrame = frame;
        const translation = getFrameBakeTranslation(frame, lockYDrift);
        const joints = {{}};
        for (const jointName of payload.jointNames) {{
          const point = frame.joints[jointName];
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          const transformed = toBaseWorldPoint(point, translation, true, jointName, selectedPreviewSettings.fixedRoot);
          joints[jointName] = [transformed.x, transformed.y, transformed.z];
        }}
        return {{
          frameIndex: index,
          sourceFrameIndex: Number.isInteger(frame.frameIndex) ? frame.frameIndex : index,
          timeSec: ((frame.timeSec ?? 0) - firstSourceTime) / exportPlaybackSpeed,
          sourceTimeSec: frame.timeSec ?? 0,
          syntheticLoopBridge: Boolean(frame.syntheticLoopBridge),
          rootTranslationApplied: translation,
          joints,
        }};
      }});
      const wearCoordinateNormalization = normalizeBakedWearSkeletonCoordinates(
        frames,
        selectedPreviewSettings.sceneInverted
      );
      frames = wearCoordinateNormalization.frames;
      const bakedSagittalPlaneAlignment = alignBakedSagittalPlaneToGridAxis(frames);
      frames = bakedSagittalPlaneAlignment.frames;
      const bakedSagittalYawDegrees = bakedSagittalPlaneAlignment.alignment?.applied
        ? Number(bakedSagittalPlaneAlignment.alignment.yawDegrees) || 0.0
        : 0.0;
      const wearViewYawDegrees = normalizeViewYawDegrees(
        selectedPreviewSettings.cameraYawDegrees + bakedSagittalYawDegrees
      );
      const sourceTimelineFrames = frames.filter((frame) => !frame.syntheticLoopBridge);
      const timelineFrames = sourceTimelineFrames.length > 0 ? sourceTimelineFrames : frames;
      const sourceStartFrame = timelineFrames.length > 0 ? timelineFrames[0].sourceFrameIndex : 0;
      const sourceEndFrame = timelineFrames.length > 0 ? timelineFrames[timelineFrames.length - 1].sourceFrameIndex : sourceStartFrame;
      const sourceStartTimeSec = timelineFrames.length > 0 ? Number(timelineFrames[0].sourceTimeSec) || 0 : 0;
      const sourceEndTimeSec = timelineFrames.length > 0 ? Number(timelineFrames[timelineFrames.length - 1].sourceTimeSec) || sourceStartTimeSec : sourceStartTimeSec;
      const sourceDurationSec = Math.max(0, sourceEndTimeSec - sourceStartTimeSec);
      const durationSec = sourceDurationSec / exportPlaybackSpeed;
      const bakedBounds = computeBakedWearBounds(frames);
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
        fps: exportFps,
        playbackSpeed: exportPlaybackSpeed,
        frameCount: frames.length,
        durationSec,
        jointNames: payload.jointNames,
        rootJoint: payload.rootJoint,
        selectedPreviewSettings,
        bakedPreviewConfiguration: {{
          autoWorldAlignment: selectedPreviewSettings.autoWorldAlignment,
          lockGlobalRootDrift: selectedPreviewSettings.fixedRoot,
          lockYDrift: selectedPreviewSettings.lockYDrift,
          lockPlantedFeet: selectedPreviewSettings.lockPlantedFeet,
          lockPlantedHands: selectedPreviewSettings.lockPlantedHands,
          sourceFootSupportEvidence: selectedPreviewSettings.sourceFootSupportEvidence,
          invertScene: selectedPreviewSettings.sceneInverted,
          manualModelRotationDegrees: selectedPreviewSettings.manualModelRotationDegrees,
          manualModelRotationAxisSemantics: selectedPreviewSettings.manualModelRotationAxisSemantics,
          canonicalWorldUp: true,
          wearCoordinateNormalization: wearCoordinateNormalization.metadata,
          previewSagittalPlaneAlignment: previewSagittalPlaneAlignmentForExport,
          bakedSagittalPlaneAlignment: bakedSagittalPlaneAlignment.alignment,
          cameraYawDegrees: selectedPreviewSettings.cameraYawDegrees,
          cameraPitchDegrees: selectedPreviewSettings.cameraPitchDegrees,
          playbackSpeed: selectedPreviewSettings.playbackSpeed,
          selectedLoopIndex,
          rawWhamPassthrough: Boolean(payload.rawWhamPassthrough),
        }},
        wearDisplay: {{
          viewYawDegrees: wearViewYawDegrees,
          viewPitchDegrees: selectedPreviewSettings.cameraPitchDegrees,
          source: "selected_preview_camera_compensated_for_baked_sagittal_alignment",
          selectedPreviewYawDegrees: selectedPreviewSettings.cameraYawDegrees,
          bakedSagittalYawDegrees,
        }},
        loop: {{
          enabled: currentLoop != null,
          startFrame: 0,
          endFrame: Math.max(0, frames.length - 1),
          sourceStartFrame,
          sourceEndFrame,
          sourceStartTimeSec,
          sourceEndTimeSec,
          sourceDurationSec,
          durationSec,
          label: currentLoop?.label ?? "Full clip",
        }},
        transforms: {{
          autoAlignment: autoWorldAlignmentEnabled ? currentAutoAlignment : [],
          manualModelRotationDegrees: selectedPreviewSettings.manualModelRotationDegrees,
          manualModelRotationAxisSemantics: selectedPreviewSettings.manualModelRotationAxisSemantics,
          rootAnchor: activeRootAnchor ? [activeRootAnchor.x, activeRootAnchor.y, activeRootAnchor.z] : null,
          sceneOriginOffset: [sceneOriginOffset.x, sceneOriginOffset.y, sceneOriginOffset.z],
          previewSagittalPlaneAlignment: previewSagittalPlaneAlignmentForExport,
          bakedSagittalPlaneAlignment: bakedSagittalPlaneAlignment.alignment,
        }},
        bounds: bakedBounds,
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

    function downloadBakedWearSkeleton() {{
      const exportPayload = buildBakedWearSkeletonPayload();
      const blob = new Blob([JSON.stringify(exportPayload, null, 2)], {{ type: "application/json" }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const loopLabel = customTimeRange
        ? `section-${{formatSectionSeconds(customTimeRange.startTimeSec).replace(".", "p")}}-${{formatSectionSeconds(customTimeRange.endTimeSec).replace(".", "p")}}`
        : (selectedLoopIndex >= 0 ? `loop-${{selectedLoopIndex + 1}}` : "full-clip");
      const yLabel = lockYRootInput.checked ? "-lock-y" : "";
      const footLabel = lockPlantedFeetInput.checked ? "-lock-feet" : "";
      const handLabel = lockPlantedHandsInput.checked ? "-lock-hands" : "";
      link.href = url;
      link.download = `${{payload.title}}-${{loopLabel}}${{yLabel}}${{footLabel}}${{handLabel}}.wear-skeleton.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }}

    function applyAutomationSettings(options = {{}}) {{
      if (renderingBakedWearPayload) {{
        renderingBakedWearPayload = false;
        bakedWearReviewBounds = null;
        applyActiveRange();
      }}
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
      if (Object.prototype.hasOwnProperty.call(options, "lockPlantedHands")) {{
        lockPlantedHands = Boolean(options.lockPlantedHands);
        lockPlantedHandsInput.checked = lockPlantedHands;
      }}
      if (Object.prototype.hasOwnProperty.call(options, "autoWorldAlignment")) {{
        autoWorldAlignmentEnabled = Boolean(options.autoWorldAlignment);
        autoWorldAlignmentInput.checked = autoWorldAlignmentEnabled;
      }}
      if (Object.prototype.hasOwnProperty.call(options, "sceneInverted")) {{
        sceneInverted = Boolean(options.sceneInverted);
        sceneInvertedInput.checked = sceneInverted;
      }}
      if (Object.prototype.hasOwnProperty.call(options, "sourceFootSupportEvidence")) {{
        sourceFootSupportEvidence = options.sourceFootSupportEvidence
          && typeof options.sourceFootSupportEvidence === "object"
          ? options.sourceFootSupportEvidence
          : null;
      }}
      const manualRotation = options.manualModelRotationDegrees;
      if (manualRotation && typeof manualRotation === "object") {{
        if (Number.isFinite(Number(manualRotation.x))) {{
          manualModelRotationXDegrees = sanitizeManualModelRotationDegrees(manualRotation.x, -90, 90);
        }}
        if (Number.isFinite(Number(manualRotation.y))) {{
          manualModelRotationYDegrees = sanitizeManualModelRotationDegrees(manualRotation.y, -180, 180);
        }}
        if (Number.isFinite(Number(manualRotation.z))) {{
          manualModelRotationZDegrees = sanitizeManualModelRotationDegrees(manualRotation.z, -90, 90);
        }}
      }}
      if (Number.isFinite(Number(options.modelRotationXDegrees))) {{
        manualModelRotationXDegrees = sanitizeManualModelRotationDegrees(options.modelRotationXDegrees, -90, 90);
      }}
      if (Number.isFinite(Number(options.modelRotationYDegrees))) {{
        manualModelRotationYDegrees = sanitizeManualModelRotationDegrees(options.modelRotationYDegrees, -180, 180);
      }}
      if (Number.isFinite(Number(options.modelRotationZDegrees))) {{
        manualModelRotationZDegrees = sanitizeManualModelRotationDegrees(options.modelRotationZDegrees, -90, 90);
      }}
      syncManualModelRotationControls();
      if (Object.prototype.hasOwnProperty.call(options, "showBoundsHelper")) {{
        showBoundsHelper = Boolean(options.showBoundsHelper);
      }}
      const nextVlmReviewStyle = Boolean(options.vlmReviewStyle);
      if (vlmReviewStyle !== nextVlmReviewStyle) {{
        vlmReviewStyle = nextVlmReviewStyle;
        applyVlmReviewStyle();
      }}
      if (Number.isFinite(Number(options.playbackSpeed))) {{
        speed = sanitizedPlaybackSpeed(options.playbackSpeed);
        speedInput.value = String(speed);
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

    function nextAnimationFrame() {{
      return new Promise((resolve) => requestAnimationFrame(resolve));
    }}

    async function renderDeterministicFrame(frameIndex) {{
      const frames = playbackState.frames ?? [];
      const boundedIndex = Math.max(0, Math.min(Math.max(0, frames.length - 1), Math.floor(Number(frameIndex) || 0)));
      paused = true;
      refreshPauseLabel();
      frameCursor = boundedIndex;
      draw();
      await nextAnimationFrame();
      draw();
      return renderer.domElement.toDataURL("image/png");
    }}

    function configureBakedWearPayloadForReview(exportPayload, options = {{}}) {{
      const frames = Array.isArray(exportPayload?.frames) ? exportPayload.frames : [];
      if (frames.length === 0) {{
        throw new Error("Cannot review an empty baked Wear payload.");
      }}
      renderingBakedWearPayload = true;
      playbackState = {{ frames, boundsFrames: frames, loopable: false }};
      bakedWearReviewBounds = stableWearReviewBounds(exportPayload, frames);
      fixedRoot = false;
      lockYRoot = false;
      lockPlantedFeet = false;
      lockPlantedHands = false;
      autoWorldAlignmentEnabled = false;
      sceneInverted = false;
      manualModelRotationXDegrees = 0.0;
      manualModelRotationYDegrees = 0.0;
      manualModelRotationZDegrees = 0.0;
      currentAutoAlignment = [];
      sceneOriginOffset.set(0.0, 0.0, 0.0);
      activeRootAnchor = null;
      activeHandSupportAnchor = null;
      activeVerticalMovementAnchor = null;
      const nextVlmReviewStyle = Boolean(options.vlmReviewStyle);
      if (vlmReviewStyle !== nextVlmReviewStyle) {{
        vlmReviewStyle = nextVlmReviewStyle;
        applyVlmReviewStyle();
      }}
      showBoundsHelper = Boolean(options.showBoundsHelper);
      const wearDisplay = exportPayload.wearDisplay ?? {{}};
      yaw = (Number(wearDisplay.viewYawDegrees) || 0.0) * Math.PI / 180.0;
      pitch = Math.max(
        -1.2,
        Math.min(1.2, (Number(wearDisplay.viewPitchDegrees) || 0.0) * Math.PI / 180.0)
      );
      cameraTouched = true;
      invalidateSceneBoundsCache();
      applySceneReframe();
    }}

    const automationBakeOptions = [
      {{
        id: "fixedRoot",
        label: rootTranslationLabel.textContent || "Lock global root drift",
        type: "boolean",
        defaultValue: Boolean(payload.defaultFixedRoot),
        description: "Keeps the rendered body centered by removing global root translation.",
        useWhen: "Use for most Wear animations when camera-space translation makes the character slide away.",
        risk: "Can hide real traveling movement and make lunges or carries look too anchored.",
      }},
      {{
        id: "lockYDrift",
        label: "Lock root Y drift",
        type: "boolean",
        defaultValue: false,
        description: "Suppresses vertical root drift while preserving other root handling.",
        useWhen: "Use when the pelvis slowly floats up or down across the loop.",
        risk: "Can flatten real vertical motion such as squat depth if overused.",
      }},
      {{
        id: "lockPlantedFeet",
        label: "Lock planted feet",
        type: "boolean",
        defaultValue: false,
        description: "Blends detected support-foot joints toward stable anchors during planted phases.",
        useWhen: "Use when the support foot visibly slides during a static or mostly static lower-body exercise.",
        risk: "Can distort the leg chain if WHAM contact timing is wrong.",
      }},
      {{
        id: "lockPlantedHands",
        label: "Lock planted hands",
        type: "boolean",
        defaultValue: false,
        description: "Blends detected support-hand joints toward stable anchors during planted phases.",
        useWhen: "Use for push-ups, planks, hand-supported rows, or clips where hands should stay fixed.",
        risk: "Can distort arm motion for free-hand exercises or barbell movements.",
      }},
      {{
        id: "autoWorldAlignment",
        label: "Auto world alignment",
        type: "boolean",
        defaultValue: Boolean(payload.defaultAutoWorldAlignment),
        description: "Rotates the preview into a stable readable orientation based on the active loop.",
        useWhen: "Use when the camera-space skeleton faces an awkward angle on the Wear preview.",
        risk: "Can choose a worse orientation if the pose estimate is noisy.",
      }},
      {{
        id: "sceneInverted",
        label: "Invert scene",
        type: "boolean",
        defaultValue: Boolean(payload.defaultSceneInverted),
        description: "Flips the rendered scene orientation.",
        useWhen: "Use only when the skeleton is clearly facing backward after alignment.",
        risk: "Can make an otherwise correct view backwards.",
      }},
      {{
        id: "modelRotationXDegrees",
        label: "Model pitch X degrees",
        type: "number",
        defaultValue: 0.0,
        range: [-90.0, 90.0],
        description: "Rotates the model around the body lateral axis, which is the sagittal-plane normal after alignment.",
        useWhen: "Use when the body/floor relationship is tilted forward or backward in the movement plane.",
        risk: "Can make a correct floor contact look wrong if overused.",
      }},
      {{
        id: "modelRotationYDegrees",
        label: "Model yaw Y degrees",
        type: "number",
        defaultValue: 0.0,
        range: [-180.0, 180.0],
        description: "Rotates the model around the world Y axis after automatic alignment.",
        useWhen: "Use when the body faces the wrong grid direction after alignment.",
        risk: "Can fight the automatic sagittal-plane grid alignment if overused.",
      }},
      {{
        id: "modelRotationZDegrees",
        label: "Model roll Z degrees",
        type: "number",
        defaultValue: 0.0,
        range: [-90.0, 90.0],
        description: "Rotates the model around the body sagittal-forward axis after alignment.",
        useWhen: "Use when the body/floor relationship is tilted sideways relative to the movement plane.",
        risk: "Can create visible leaning if overused.",
      }},
      {{
        id: "cameraYawDegrees",
        label: "Camera yaw degrees",
        type: "number",
        defaultValue: 45.0,
        range: [-180.0, 180.0],
        description: "Changes the review camera around the rendered skeleton.",
        useWhen: "Use to make the movement readable when the chosen viewing angle hides the limbs.",
        risk: "Only affects review/export framing, not the underlying motion.",
      }},
      {{
        id: "cameraPitchDegrees",
        label: "Camera pitch degrees",
        type: "number",
        defaultValue: 30.0,
        range: [-68.0, 68.0],
        description: "Tilts the review camera up or down.",
        useWhen: "Use to keep feet and head visible while preserving movement readability.",
        risk: "Only affects review/export framing, not the underlying motion.",
      }},
      {{
        id: "playbackSpeed",
        label: "Playback speed",
        type: "number",
        defaultValue: 1.0,
        range: [0.5, 1.5],
        description: "Changes the exported animation timing without changing the pose geometry.",
        useWhen: "Use below 1.0 when the rep looks rushed, or above 1.0 when the rep is too slow for a compact Wear animation.",
        risk: "Too slow can feel sluggish; too fast can hide exercise range or make the loop hard to read.",
      }},
    ];

    window.exerciseMotionAutomation = {{
      getAvailableBakeOptions() {{
        return automationBakeOptions.map((option) => ({{ ...option }}));
      }},
      getPayloadSummary() {{
        return {{
          title: payload.title,
          fps: payload.fps,
          frameCount: payload.frameCount,
          motionTuningEnabled: payload.motionTuningEnabled,
          rawWhamPassthrough: payload.rawWhamPassthrough,
          previewMode: "full_clip_source_with_optional_time_range_cut",
          sourceRange: sourceTimeBounds(),
          activeRange: currentLoop ? {{
            startSeconds: currentLoop.startTimeSec ?? 0,
            endSeconds: currentLoop.endTimeSec ?? 0,
            startFrame: currentLoop.startFrame ?? 0,
            endFrame: currentLoop.endFrame ?? Math.max(0, payload.frameCount - 1),
            label: currentLoop.label ?? "Selected section",
          }} : null,
          selectedLoopIndex,
          availableBakeOptions: automationBakeOptions.map((option) => ({{ ...option }})),
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
      selectTimeRange(startSeconds, endSeconds) {{
        return selectCustomTimeRange(startSeconds, endSeconds);
      }},
      exportWearSkeleton(options = {{}}) {{
        applyAutomationSettings(options);
        return buildBakedWearSkeletonPayload();
      }},
      bakeLoop(loopIndex, options = {{}}) {{
        this.selectLoop(loopIndex);
        return this.exportWearSkeleton(options);
      }},
      bakeTimeRange(startSeconds, endSeconds, options = {{}}) {{
        selectCustomTimeRange(startSeconds, endSeconds);
        return this.exportWearSkeleton(options);
      }},
      async renderFrame(frameIndex, options = {{}}) {{
        applyAutomationSettings(options);
        return await renderDeterministicFrame(frameIndex);
      }},
      async renderBakedWearFrame(exportPayload, frameIndex, options = {{}}) {{
        configureBakedWearPayloadForReview(exportPayload, options);
        return await renderDeterministicFrame(frameIndex);
      }},
    }};

    function applyUrlPreviewParameters() {{
      const params = new URLSearchParams(window.location.search);
      if ([...params.keys()].length === 0) {{
        return;
      }}
      const startSeconds = Number(params.get("startSeconds") ?? params.get("start"));
      const endSeconds = Number(params.get("endSeconds") ?? params.get("end"));
      if (Number.isFinite(startSeconds) && Number.isFinite(endSeconds) && endSeconds > startSeconds) {{
        selectCustomTimeRange(startSeconds, endSeconds);
      }}
      const options = {{}};
      const optionsJson = params.get("options");
      if (optionsJson) {{
        try {{
          const parsed = JSON.parse(optionsJson);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {{
            Object.assign(options, parsed);
          }}
        }} catch (_error) {{
          // Ignore malformed URL option payloads; direct option params below can still apply.
        }}
      }}
      for (const option of automationBakeOptions) {{
        if (!params.has(option.id)) {{
          continue;
        }}
        const parsedValue = parseUrlPreviewOption(params.get(option.id), option.type);
        if (parsedValue !== null) {{
          options[option.id] = parsedValue;
        }}
      }}
      if (Object.keys(options).length > 0) {{
        applyAutomationSettings(options);
      }}
      requestPreviewRedraw();
    }}

    function parseUrlPreviewOption(value, type) {{
      if (value == null) {{
        return null;
      }}
      if (type === "boolean") {{
        const normalized = String(value).trim().toLowerCase();
        if (["1", "true", "yes", "on"].includes(normalized)) {{
          return true;
        }}
        if (["0", "false", "no", "off"].includes(normalized)) {{
          return false;
        }}
        return null;
      }}
      if (type === "number") {{
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
      }}
      return value;
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

      let connectedSkeletonHidden = false;
      let comparisonOverlayHidden = false;

      function hideConnectedSkeleton() {{
        if (connectedSkeletonHidden) {{
          hideComparisonOverlay();
          return;
        }}
        for (const entry of skeletonLines) {{
          entry.line.visible = false;
        }}
        for (const entry of skeletonSurfaces) {{
          entry.mesh.visible = false;
        }}
        for (const entry of jointNodeMeshes) {{
          entry.mesh.visible = false;
        }}
        connectedSkeletonHidden = true;
        hideComparisonOverlay();
      }}

      function hideComparisonOverlay() {{
        if (comparisonOverlayHidden) {{
          return;
        }}
        for (const entry of comparisonLines) {{
          entry.line.visible = false;
        }}
        for (const entry of comparisonNodeMeshes) {{
          entry.mesh.visible = false;
        }}
        for (const entry of comparisonBodyMeshes) {{
          entry.mesh.visible = false;
        }}
        comparisonOverlayHidden = true;
      }}

      function updateConnectedSkeleton(frame, frameTranslation) {{
        connectedSkeletonHidden = false;
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

      function updateComparisonOverlay(frame, frameTranslation) {{
        if ((!showComparisonOverlay && !showRawComparisonOverlay) || !frame) {{
          hideComparisonOverlay();
          return;
        }}
        comparisonOverlayHidden = false;
        const savedShowComparisonOverlay = showComparisonOverlay;
        const savedShowRawComparisonOverlay = showRawComparisonOverlay;
        showComparisonOverlay = false;
        showRawComparisonOverlay = false;
        updateSceneForFrame(frame);
        for (const entry of comparisonBodyMeshes) {{
          const source = entry.sourceMesh;
          const target = entry.mesh;
          target.visible = source.visible;
          target.position.copy(source.position);
          target.quaternion.copy(source.quaternion);
          target.scale.copy(source.scale);
          if (target.geometry) {{
            target.geometry.dispose();
          }}
          target.geometry = source.geometry.clone();
        }}
        showComparisonOverlay = savedShowComparisonOverlay;
        showRawComparisonOverlay = savedShowRawComparisonOverlay;
        comparisonOverlayHidden = false;
        for (const entry of comparisonLines) {{
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
        for (const entry of comparisonNodeMeshes) {{
          const point = frame.joints[entry.jointName]
            ? toWorldPoint(frame.joints[entry.jointName], frameTranslation, fixedRoot, true, entry.jointName)
            : null;
          if (!point) {{
            entry.mesh.visible = false;
            continue;
          }}
          entry.mesh.visible = true;
          entry.mesh.position.copy(point);
          entry.mesh.scale.setScalar(entry.jointName === "head" ? 0.022 : 0.009);
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
      const boundingRadius = Math.sqrt(width * width + height * height + depth * depth) * 0.5;
      const fitHeightDistance = boundingRadius / Math.tan(verticalFov * 0.5);
      const fitWidthDistance = boundingRadius / Math.tan(horizontalFov * 0.5);
      return Math.max(0.7, fitHeightDistance, fitWidthDistance);
    }}

    function updateCamera() {{
      if (renderingBakedWearPayload && bakedWearReviewBounds) {{
        const bounds = bakedWearReviewBounds;
        const distance = bounds.radius * 4.2;
        const horizontalDistance = Math.cos(pitch) * distance;
        cameraTarget.copy(bounds.center);
        bakedWearCamera.position.copy(cameraTarget)
          .addScaledVector(axisX, Math.sin(yaw) * horizontalDistance)
          .addScaledVector(axisZ, Math.cos(yaw) * horizontalDistance)
          .addScaledVector(axisY, Math.sin(pitch) * distance);
        bakedWearCamera.up.copy(axisY);
        bakedWearCamera.lookAt(cameraTarget);
        const aspect = viewport.clientWidth / Math.max(1, viewport.clientHeight);
        let halfWidth = bounds.radius * 1.08;
        let halfHeight = bounds.radius * 1.08;
        if (aspect >= 1.0) {{
          halfWidth = halfHeight * aspect;
        }} else {{
          halfHeight = halfWidth / Math.max(0.001, aspect);
        }}
        bakedWearCamera.left = -halfWidth;
        bakedWearCamera.right = halfWidth;
        bakedWearCamera.bottom = -halfHeight;
        bakedWearCamera.top = halfHeight;
        bakedWearCamera.near = 0.01;
        bakedWearCamera.far = bounds.radius * 9.0;
        bakedWearCamera.updateProjectionMatrix();
        return;
      }}
      const zoomScale = 240 / Math.max(120, zoom);
      const framingMargin = vlmReviewStyle ? 1.05 : 1.28;
      const distance = getCameraFitDistance() * zoomScale * framingMargin;
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
        return applyPreviewMotionTuning(current);
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
      return applyPreviewMotionTuning({{
        frameIndex: current.frameIndex ?? baseIndex,
        ...interpolateFrameSourceMapping(current, next, baseIndex, nextIndex, alpha),
        timeSec: current.timeSec * (1 - alpha) + next.timeSec * alpha,
        joints,
      }});
    }}

    function interpolateFrameSourceMapping(current, next, baseIndex, nextIndex, alpha) {{
      const currentMapping = frameSourceMapping(current, baseIndex);
      const nextMapping = frameSourceMapping(next, nextIndex);
      if (
        currentMapping.sourceIndexA === nextMapping.sourceIndexA
        && currentMapping.sourceIndexB === nextMapping.sourceIndexB
      ) {{
        return {{
          sourceIndexA: currentMapping.sourceIndexA,
          sourceIndexB: currentMapping.sourceIndexB,
          sourceAlpha: currentMapping.sourceAlpha * (1 - alpha) + nextMapping.sourceAlpha * alpha,
        }};
      }}
      if (
        currentMapping.sourceIndexA === currentMapping.sourceIndexB
        && currentMapping.sourceIndexA === nextMapping.sourceIndexA
      ) {{
        return {{
          sourceIndexA: nextMapping.sourceIndexA,
          sourceIndexB: nextMapping.sourceIndexB,
          sourceAlpha: nextMapping.sourceAlpha * alpha,
        }};
      }}
      if (
        nextMapping.sourceIndexA === nextMapping.sourceIndexB
        && currentMapping.sourceIndexB === nextMapping.sourceIndexA
      ) {{
        return {{
          sourceIndexA: currentMapping.sourceIndexA,
          sourceIndexB: currentMapping.sourceIndexB,
          sourceAlpha: currentMapping.sourceAlpha * (1 - alpha) + alpha,
        }};
      }}
      return {{
        sourceIndexA: currentMapping.sourceIndexA,
        sourceIndexB: nextMapping.sourceIndexA,
        sourceAlpha: alpha,
      }};
    }}

    function frameSourceMapping(frame, fallbackIndex) {{
      if (
        Number.isFinite(Number(frame?.sourceIndexA))
        && Number.isFinite(Number(frame?.sourceIndexB))
      ) {{
        return {{
          sourceIndexA: resolveSourceFrameIndex(frame.sourceIndexA, fallbackIndex),
          sourceIndexB: resolveSourceFrameIndex(frame.sourceIndexB, fallbackIndex),
          sourceAlpha: Math.max(0, Math.min(1, Number(frame.sourceAlpha) || 0)),
        }};
      }}
      const sourceIndex = resolveSourceFrameIndex(frame?.frameIndex, fallbackIndex);
      return {{
        sourceIndexA: sourceIndex,
        sourceIndexB: sourceIndex,
        sourceAlpha: 0,
      }};
    }}

    function applyPreviewMotionTuning(frame) {{
      if (renderingBakedWearPayload) {{
        return frame;
      }}
      const sourceFrame = getInterpolatedSourceMotionFrame(frame);
      if (!sourceFrame) {{
        return frame;
      }}
      const dominantGroups = previewDominantGroups();
      const tunedJoints = {{}};
      let changed = false;
      for (const jointName of payload.jointNames) {{
        const cleaned = frame.joints?.[jointName];
        const source = sourceFrame.joints?.[jointName];
        if (!Array.isArray(cleaned) || cleaned.length < 3 || !Array.isArray(source) || source.length < 3) {{
          if (cleaned) {{
            tunedJoints[jointName] = cleaned;
          }}
          continue;
        }}
        const group = jointMotionGroup(jointName);
        const sourceBlend = dominantGroups.has(group)
          ? 0.0
          : Math.max(0.0, Math.min(1.0, (1.0 - previewNonDominantDamping) * previewResidualScale));
        if (sourceBlend <= 1e-6) {{
          tunedJoints[jointName] = cleaned;
          continue;
        }}
        tunedJoints[jointName] = [
          cleaned[0] * (1 - sourceBlend) + source[0] * sourceBlend,
          cleaned[1] * (1 - sourceBlend) + source[1] * sourceBlend,
          cleaned[2] * (1 - sourceBlend) + source[2] * sourceBlend,
        ];
        changed = true;
      }}
      return changed ? {{ ...frame, joints: tunedJoints, previewMotionTuned: true }} : frame;
    }}

    function getInterpolatedSourceMotionFrame(frame) {{
      const sourceFrames = payload.comparisonFrames ?? [];
      if (!Array.isArray(sourceFrames) || sourceFrames.length === 0) {{
        return null;
      }}
      const indexA = resolveSourceFrameIndex(frame.sourceIndexA ?? frame.frameIndex);
      const indexB = resolveSourceFrameIndex(frame.sourceIndexB ?? frame.frameIndex);
      const alpha = Number(frame.sourceAlpha) || 0;
      const current = sourceFrames[indexA];
      const next = sourceFrames[indexB] ?? current;
      if (!current) {{
        return null;
      }}
      if (!next || alpha <= 1e-6) {{
        return current;
      }}
      const joints = {{}};
      for (const jointName of payload.jointNames) {{
        const start = current.joints?.[jointName];
        const end = next.joints?.[jointName];
        if (!Array.isArray(start) || start.length < 3 || !Array.isArray(end) || end.length < 3) {{
          continue;
        }}
        joints[jointName] = [
          start[0] * (1 - alpha) + end[0] * alpha,
          start[1] * (1 - alpha) + end[1] * alpha,
          start[2] * (1 - alpha) + end[2] * alpha,
        ];
      }}
      return {{ ...current, joints }};
    }}

    function resolveSourceFrameIndex(value, fallbackIndex = 0) {{
      const sourceFrames = payload.comparisonFrames ?? [];
      const parsed = Number(value);
      const fallback = Number.isFinite(Number(fallbackIndex)) ? Number(fallbackIndex) : 0;
      const index = Number.isFinite(parsed) ? parsed : fallback;
      return Math.max(0, Math.min(Math.max(0, sourceFrames.length - 1), Math.floor(index)));
    }}

    function previewDominantGroups() {{
      const groupMotion = payload.structuralRefinement?.dominantProfile?.groupMotion ?? {{}};
      const values = Object.values(groupMotion).map(Number).filter((value) => Number.isFinite(value));
      const strongest = Math.max(0, ...values);
      const groups = new Set();
      if (strongest <= 1e-8) {{
        return groups;
      }}
      for (const [group, motion] of Object.entries(groupMotion)) {{
        if (Number(motion) >= strongest * previewDominantCutoff) {{
          groups.add(group);
        }}
      }}
      return groups;
    }}

    function jointMotionGroup(jointName) {{
      if (jointName.includes("shoulder") || jointName.includes("elbow") || jointName.includes("wrist") || jointName.includes("hand") || jointName.includes("collar")) {{
        return "arms";
      }}
      if (jointName.includes("hip") || jointName.includes("knee") || jointName.includes("ankle") || jointName.includes("foot")) {{
        return "legs";
      }}
      if (jointName === "pelvis" || jointName.includes("spine") || jointName === "neck" || jointName === "head") {{
        return "torso";
      }}
      return "other";
    }}

    function getInterpolatedComparisonFrame() {{
      const state = showRawComparisonOverlay ? rawComparisonPlaybackState : comparisonPlaybackState;
      const frames = state.frames;
      if ((!showComparisonOverlay && !showRawComparisonOverlay) || !frames || frames.length === 0) {{
        return null;
      }}
      const normalizedCursor = state.loopable
        ? ((frameCursor % frames.length) + frames.length) % frames.length
        : Math.max(0, Math.min(frames.length - 1, frameCursor));
      const baseIndex = Math.max(0, Math.min(frames.length - 1, Math.floor(normalizedCursor)));
      const nextIndex = state.loopable
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
        timeSec: current.timeSec * (1 - alpha) + next.timeSec * alpha,
        joints,
      }};
    }}

      function updateSceneForFrame(frame) {{
        activeRenderFrame = frame;
        const frameTranslation = getFrameTranslation(frame);
        hideConnectedSkeleton();
        proceduralBodyMeshes.forEach((mesh) => {{
          mesh.visible = true;
        }});
        updateComparisonOverlay(getInterpolatedComparisonFrame(), frameTranslation);
        activeRenderFrame = frame;
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
        if (!customModelUsesFusedSpine && pelvisJoint && spine1Joint && spine2Joint && neckJoint && hipAxis && shoulderAxis) {{
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
            const torsoCenter = hipCenter.clone().lerp(shoulderCenter, 0.54);
            const torsoHeight = Math.max(0.24, hipCenter.distanceTo(shoulderCenter));
            const torsoWidth = Math.max(0.18, Math.max(hipWidth * 0.92, shoulderWidth * 0.78));
            const torsoDepth = Math.max(0.1, Math.max(hipWidth * 0.58, shoulderWidth * 0.4));
            setOrientedFrameVolume(
              coreShellMesh,
              torsoCenter,
              shoulderAxis,
              spineAxis,
              torsoWidth,
              torsoHeight,
              torsoDepth
            );
            coreShellVisible = true;
          }}
        }}
        if (!coreShellVisible) {{
          coreShellMesh.visible = false;
        }}

          const spineSegments = [
            [pelvisJoint, spine1Joint],
            [spine1Joint, spine2Joint],
            [spine2Joint, spine3Joint ?? neckJoint],
            [spine3Joint, neckJoint],
          ].filter(([segmentStart, segmentEnd]) => segmentStart && segmentEnd && segmentStart !== segmentEnd);
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
      renderer.render(
        scene,
        renderingBakedWearPayload ? bakedWearCamera : perspectiveCamera
      );
    }}

    function requestPreviewRedraw() {{
      forceNextDraw = true;
    }}

    function animate(timestamp) {{
      if (lastTimestamp == null) {{
        lastTimestamp = timestamp;
      }}
      const deltaSeconds = Math.max(0, (timestamp - lastTimestamp) / 1000);
      lastTimestamp = timestamp;
      const cursorAdvanced = !paused && playbackState.frames.length > 0;
      if (cursorAdvanced) {{
        frameCursor += deltaSeconds * payload.fps * speed;
        if (playbackState.frames.length > 0) {{
          while (frameCursor >= playbackState.frames.length) {{
            frameCursor -= playbackState.frames.length;
          }}
        }}
      }}
      const timeSinceLastDraw = lastDrawTimestamp == null
        ? Number.POSITIVE_INFINITY
        : timestamp - lastDrawTimestamp;
      const shouldDraw = forceNextDraw
        || dragging
        || lastDrawTimestamp == null
        || (cursorAdvanced && timeSinceLastDraw >= previewMinRenderIntervalMs);
      if (shouldDraw) {{
        draw();
        lastDrawTimestamp = timestamp;
        forceNextDraw = false;
      }}
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
      requestPreviewRedraw();
    }});
    renderer.domElement.addEventListener("pointerup", () => {{
      dragging = false;
    }});
    speedInput.addEventListener("input", () => {{
      speed = parseFloat(speedInput.value);
      requestPreviewRedraw();
    }});
    function refreshPauseLabel() {{
      pauseToggleButton.textContent = paused ? "Resume" : "Pause";
    }}
    pauseToggleButton.addEventListener("click", () => {{
      paused = !paused;
      refreshPauseLabel();
      requestPreviewRedraw();
    }});
    fixedRootInput.addEventListener("change", () => {{
      fixedRoot = fixedRootInput.checked;
      activeVerticalMovementAnchor = computeActiveVerticalMovementAnchor(playbackState.boundsFrames);
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    lockYRootInput.addEventListener("change", () => {{
      lockYRoot = lockYRootInput.checked;
      activeVerticalMovementAnchor = computeActiveVerticalMovementAnchor(playbackState.boundsFrames);
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    lockPlantedFeetInput.addEventListener("change", () => {{
      lockPlantedFeet = lockPlantedFeetInput.checked;
      activeVerticalMovementAnchor = computeActiveVerticalMovementAnchor(playbackState.boundsFrames);
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    lockPlantedHandsInput.addEventListener("change", () => {{
      lockPlantedHands = lockPlantedHandsInput.checked;
      activeHandSupportAnchor = computeActiveHandSupportAnchor(playbackState.boundsFrames);
      activeVerticalMovementAnchor = computeActiveVerticalMovementAnchor(playbackState.boundsFrames);
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    autoWorldAlignmentInput.addEventListener("change", () => {{
      autoWorldAlignmentEnabled = autoWorldAlignmentInput.checked;
      activeVerticalMovementAnchor = computeActiveVerticalMovementAnchor(playbackState.boundsFrames);
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    sceneInvertedInput.addEventListener("change", () => {{
      sceneInverted = sceneInvertedInput.checked;
      activeVerticalMovementAnchor = computeActiveVerticalMovementAnchor(playbackState.boundsFrames);
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    modelRotationXInput.addEventListener("input", updateManualModelRotationFromControls);
    modelRotationYInput.addEventListener("input", updateManualModelRotationFromControls);
    modelRotationZInput.addEventListener("input", updateManualModelRotationFromControls);
    resetModelRotationButton.addEventListener("click", () => {{
      manualModelRotationXDegrees = 0.0;
      manualModelRotationYDegrees = 0.0;
      manualModelRotationZDegrees = 0.0;
      syncManualModelRotationControls();
      activeVerticalMovementAnchor = computeActiveVerticalMovementAnchor(playbackState.boundsFrames);
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    showComparisonOverlayInput.addEventListener("change", () => {{
      showComparisonOverlay = showComparisonOverlayInput.checked && comparisonFrames.length > 0;
      if (!showComparisonOverlay) {{
        hideComparisonOverlay();
      }}
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    showRawComparisonOverlayInput.addEventListener("change", () => {{
      showRawComparisonOverlay = showRawComparisonOverlayInput.checked && rawComparisonFrames.length > 0;
      if (!showRawComparisonOverlay) {{
        hideComparisonOverlay();
      }}
      invalidateSceneBoundsCache();
      applySceneReframe();
    }});
    function syncPreviewTuningControls() {{
      previewDominantCutoff = Math.max(0.1, Math.min(1.0, Number(previewDominantCutoffInput.value) || 0.65));
      previewNonDominantDamping = Math.max(0.0, Math.min(1.0, Number(previewNonDominantDampingInput.value) || 0.0));
      previewResidualScale = Math.max(0.0, Math.min(2.0, Number(previewResidualScaleInput.value) || 0.0));
      previewDominantCutoffValue.textContent = previewDominantCutoff.toFixed(2);
      previewNonDominantDampingValue.textContent = previewNonDominantDamping.toFixed(2);
      previewResidualScaleValue.textContent = previewResidualScale.toFixed(2);
      invalidateSceneBoundsCache();
      refreshSceneFrame();
    }}
    previewDominantCutoffInput.value = previewDominantCutoff.toFixed(2);
    previewNonDominantDampingInput.value = previewNonDominantDamping.toFixed(2);
    previewResidualScaleInput.value = previewResidualScale.toFixed(2);
    previewDominantCutoffInput.addEventListener("input", syncPreviewTuningControls);
    previewNonDominantDampingInput.addEventListener("input", syncPreviewTuningControls);
    previewResidualScaleInput.addEventListener("input", syncPreviewTuningControls);
    loopSelect.addEventListener("change", () => {{
      setSelectedLoop(parseInt(loopSelect.value, 10));
    }});
    setSectionStartFromFrameButton.addEventListener("click", () => {{
      setSectionBoundaryFromCurrentFrame("start");
    }});
    setSectionEndFromFrameButton.addEventListener("click", () => {{
      setSectionBoundaryFromCurrentFrame("end");
    }});
    applySectionRangeButton.addEventListener("click", () => {{
      applySectionRangeFromInputs();
    }});
    resetSectionRangeButton.addEventListener("click", () => {{
      resetSectionRangeToFullClip();
    }});
    downloadWearSkeletonButton.addEventListener("click", () => {{
      downloadBakedWearSkeleton();
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
      requestPreviewRedraw();
    }});
    window.addEventListener("resize", resize);
    refreshPauseLabel();
    activeRootAnchor = computeActiveRootAnchor(playbackState.boundsFrames);
    activeHandSupportAnchor = computeActiveHandSupportAnchor(playbackState.boundsFrames);
    activeVerticalMovementAnchor = computeActiveVerticalMovementAnchor(playbackState.boundsFrames);
    syncPreviewTuningControls();
    applyUrlPreviewParameters();
    frameCursor = findFrameCursorClosestToBoundsCenter();
    refreshSceneFrame();
    resize();
    draw();
    requestAnimationFrame(animate);
    </script>
</body>
</html>
"""
