from __future__ import annotations

import math
from dataclasses import replace
from statistics import median

from exercise_motion_pkg.models import MotionClip, MotionFrame, Point3

ARM_PAIRS = (
    ("left_elbow", "right_elbow"),
    ("left_wrist", "right_wrist"),
    ("left_hand", "right_hand"),
)
LEG_PAIRS = (
    ("left_knee", "right_knee"),
    ("left_ankle", "right_ankle"),
    ("left_foot", "right_foot"),
)
STRUCTURAL_BONES = (
    ("pelvis", "spine1"),
    ("spine1", "spine2"),
    ("spine2", "spine3"),
    ("spine3", "neck"),
    ("neck", "head"),
    ("neck", "left_collar"),
    ("left_collar", "left_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("left_wrist", "left_hand"),
    ("neck", "right_collar"),
    ("right_collar", "right_shoulder"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("right_wrist", "right_hand"),
    ("pelvis", "left_hip"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("left_ankle", "left_foot"),
    ("pelvis", "right_hip"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
    ("right_ankle", "right_foot"),
)
TORSO_STABILITY_JOINTS = (
    "spine1",
    "spine2",
    "spine3",
    "neck",
    "head",
    "left_collar",
    "right_collar",
    "left_shoulder",
    "right_shoulder",
)
LOW_MOTION_SMOOTHING_THRESHOLD_METERS = 0.018
DOMINANT_CHAIN_RATIO = 0.35
NON_DOMINANT_CHAIN_RATIO = 0.65
MAX_SUPPRESSION_CORRECTION_METERS = 0.035
MAX_TORSO_CORRECTION_METERS = 0.025
SYMMETRY_MIN_RATIO = 0.55
SYMMETRY_MIN_CORRELATION = 0.30
SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO = 0.08
SYMMETRY_MAX_POSE_ERROR_BODY_RATIO = 0.16
ARM_MOTION_DRIVEN_SYMMETRY_MIN_RATIO = 0.70
ARM_MOTION_DRIVEN_SYMMETRY_MIN_CORRELATION = 0.90
ARM_MOTION_DRIVEN_SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO = 0.20
ARM_MOTION_DRIVEN_SYMMETRY_MAX_POSE_ERROR_BODY_RATIO = 0.38
ROOT_VERTICAL_MOTION_PRESERVATION_MIN_RANGE_METERS = 0.04
ROOT_VERTICAL_MOTION_PRESERVATION_RANGE_RATIO = 0.85
ROOT_VERTICAL_MOTION_JOINTS = ("pelvis", "hips", "root")
DOMINANT_CHAIN_TOTAL_RANGE_RATIO = 0.45
DOMINANT_CHAIN_MIN_TOTAL_RANGE_BODY_RATIO = 0.08
DOMINANT_CHAIN_MIN_TOTAL_RANGE_METERS = 0.08


def refine_motion_clip_structurally(
    clip: MotionClip,
    *,
    dominant_chain_ratio: float = NON_DOMINANT_CHAIN_RATIO,
    non_dominant_damping: float = 1.0,
    non_dominant_radius_scale: float = 1.0,
) -> MotionClip:
    if clip.frame_count < 3:
        return clip
    dominant_chain_ratio = min(max(dominant_chain_ratio, 0.1), 1.0)
    non_dominant_damping = min(max(non_dominant_damping, 0.0), 1.0)
    non_dominant_radius_scale = max(0.1, non_dominant_radius_scale)

    chain_motion = _chain_motion_summary(clip)
    chain_range = _chain_range_summary(clip)
    body_height = _median_body_height(clip)
    strongest_chain_motion = max(chain_motion.values(), default=0.0)
    active_threshold = max(LOW_MOTION_SMOOTHING_THRESHOLD_METERS, strongest_chain_motion * DOMINANT_CHAIN_RATIO)

    dominant_profile = _dominant_motion_profile(
        chain_motion,
        strongest_chain_motion,
        chain_range=chain_range,
        body_height=body_height,
        active_threshold=active_threshold,
        dominant_chain_ratio=dominant_chain_ratio,
    )
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    if "torso" in dominant_groups:
        refined, refinement_metadata = _refine_torso_dominant_motion_conservatively(
            clip,
            active_threshold=active_threshold,
            strongest_chain_motion=strongest_chain_motion,
            dominant_profile=dominant_profile,
            non_dominant_radius_scale=non_dominant_radius_scale,
        )
    else:
        refined, refinement_metadata = _refine_non_torso_dominant_motion_by_transfer(
            clip,
            dominant_profile=dominant_profile,
        )
    if dominant_groups == {"arms"}:
        head_metadata = {
            "applied": False,
            "reason": "head_motion_not_part_of_arms_only_dominant_motion",
        }
    else:
        refined, head_metadata = _preserve_reference_head_pose(refined, reference_clip=clip)
    refinement_metadata = {
        **refinement_metadata,
        "headPosePreservation": head_metadata,
    }
    metadata = dict(refined.metadata)
    metadata["structuralRefinement"] = {
        "applied": True,
        "strategy": refinement_metadata.get("strategy", "structural_refinement"),
        "inputFrames": [
            {
                "frameIndex": index,
                "timeSec": frame.time_sec,
                "joints": {
                    joint_name: [float(point[0]), float(point[1]), float(point[2])]
                    for joint_name, point in frame.joints.items()
                },
            }
            for index, frame in enumerate(clip.frames)
        ],
        "strongestChainMotion": strongest_chain_motion,
        "activeThreshold": active_threshold,
        "chainMotion": chain_motion,
        "chainRange": chain_range,
        "bodyHeight": body_height,
        "dominantProfile": dominant_profile,
        "settings": {
            "dominantChainRatio": dominant_chain_ratio,
            "nonDominantDamping": non_dominant_damping,
            "nonDominantRadiusScale": non_dominant_radius_scale,
        },
        **refinement_metadata,
    }
    return replace(refined, metadata=metadata)


def _preserve_reference_head_pose(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    if "head" not in clip.joint_names or "neck" not in clip.joint_names:
        return clip, {"applied": False, "reason": "missing_head_or_neck"}
    frames: list[MotionFrame] = []
    total_correction = 0.0
    max_correction = 0.0
    samples = 0
    projected_samples = 0
    for frame, reference_frame in zip(clip.frames, reference_clip.frames):
        head = frame.joints.get("head")
        neck = frame.joints.get("neck")
        reference_head = reference_frame.joints.get("head")
        reference_neck = reference_frame.joints.get("neck")
        if head is None or neck is None or reference_head is None or reference_neck is None:
            frames.append(frame)
            continue
        reference_offset = _subtract(reference_head, reference_neck)
        target_offset, projected = _plausible_head_offset(frame, reference_offset)
        if projected:
            projected_samples += 1
        target_head = _add(neck, target_offset)
        correction = _distance(head, target_head)
        if correction > 1e-6:
            total_correction += correction
            max_correction = max(max_correction, correction)
            samples += 1
        joints = dict(frame.joints)
        joints["head"] = target_head
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": samples > 0,
        "strategy": "restore_reference_neck_to_head_vector_with_spine_axis_sanity",
        "averageCorrection": total_correction / samples if samples else 0.0,
        "maxCorrection": max_correction,
        "spineAxisProjectedSamples": projected_samples,
    }


def _plausible_head_offset(
    frame: MotionFrame,
    reference_offset: Point3,
) -> tuple[Point3, bool]:
    length = _length(reference_offset)
    if length <= 1e-6:
        return reference_offset, False
    body_frame = _body_local_frame(frame)
    if body_frame is None:
        return reference_offset, False
    local = (
        _dot(reference_offset, body_frame.right),
        _dot(reference_offset, body_frame.up),
        _dot(reference_offset, body_frame.forward),
    )
    off_axis = math.hypot(local[0], local[2])
    along_spine = local[1]
    if along_spine > 0.0 and off_axis <= max(abs(along_spine) * 0.85, length * 0.45):
        return reference_offset, False
    return _scale(body_frame.up, length), True


def _preserve_reference_root_vertical_motion(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    root_joint = next(
        (
            joint_name
            for joint_name in ROOT_VERTICAL_MOTION_JOINTS
            if joint_name in clip.joint_names and joint_name in reference_clip.joint_names
        ),
        None,
    )
    if root_joint is None:
        return clip, {"applied": False, "reason": "missing_root_joint"}

    reference_values = _joint_axis_values(reference_clip, root_joint, axis=1)
    current_values = _joint_axis_values(clip, root_joint, axis=1)
    reference_range = _value_range(reference_values)
    current_range = _value_range(current_values)
    if reference_range < ROOT_VERTICAL_MOTION_PRESERVATION_MIN_RANGE_METERS:
        return clip, {
            "applied": False,
            "reason": "reference_root_vertical_motion_below_threshold",
            "rootJoint": root_joint,
            "referenceRange": reference_range,
            "beforeRange": current_range,
            "minimumRange": ROOT_VERTICAL_MOTION_PRESERVATION_MIN_RANGE_METERS,
        }
    if current_range >= reference_range * ROOT_VERTICAL_MOTION_PRESERVATION_RANGE_RATIO:
        return clip, {
            "applied": False,
            "reason": "existing_root_vertical_motion_sufficient",
            "rootJoint": root_joint,
            "referenceRange": reference_range,
            "beforeRange": current_range,
            "minimumRangeRatio": ROOT_VERTICAL_MOTION_PRESERVATION_RANGE_RATIO,
        }

    frames: list[MotionFrame] = []
    total_correction = 0.0
    max_correction = 0.0
    samples = 0
    for frame_index, frame in enumerate(clip.frames):
        reference_frame = reference_clip.frames[frame_index] if frame_index < reference_clip.frame_count else None
        current_root = frame.joints.get(root_joint)
        reference_root = reference_frame.joints.get(root_joint) if reference_frame is not None else None
        if current_root is None or reference_root is None:
            frames.append(frame)
            continue
        correction_y = reference_root[1] - current_root[1]
        if abs(correction_y) > 1e-9:
            total_correction += abs(correction_y)
            max_correction = max(max_correction, abs(correction_y))
            samples += 1
        joints = {
            joint_name: (point[0], point[1] + correction_y, point[2])
            for joint_name, point in frame.joints.items()
        }
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    corrected = replace(clip, frames=frames)
    return corrected, {
        "applied": samples > 0,
        "strategy": "restore_reference_root_y_translation",
        "rootJoint": root_joint,
        "referenceRange": reference_range,
        "beforeRange": current_range,
        "afterRange": _value_range(_joint_axis_values(corrected, root_joint, axis=1)),
        "minimumRange": ROOT_VERTICAL_MOTION_PRESERVATION_MIN_RANGE_METERS,
        "minimumRangeRatio": ROOT_VERTICAL_MOTION_PRESERVATION_RANGE_RATIO,
        "averageCorrection": total_correction / samples if samples else 0.0,
        "maxCorrection": max_correction,
    }


def _align_dominant_chain_motion_to_world_y(
    clip: MotionClip,
    *,
    dominant_groups: set[str],
) -> tuple[MotionClip, dict[str, object]]:
    specs = _dominant_world_y_specs(dominant_groups)
    if not specs:
        return clip, {"applied": False, "reason": "no_supported_dominant_group"}
    spec_ranges = [
        (spec, _dominant_chain_range(clip, spec["anchors"], spec["ends"]))
        for spec in specs
    ]
    strongest_range = max((value for _, value in spec_ranges), default=0.0)
    if strongest_range <= 1e-5:
        return clip, {"applied": False, "reason": "no_dominant_chain_range"}
    specs = [
        spec
        for spec, value in spec_ranges
        if value >= strongest_range * 0.90
    ]
    frames = [MotionFrame(time_sec=frame.time_sec, joints=dict(frame.joints)) for frame in clip.frames]
    applied_specs: list[dict[str, object]] = []
    for spec in specs:
        axis = _dominant_chain_axis(clip, spec["anchors"], spec["ends"])
        if axis is None:
            applied_specs.append({"group": spec["group"], "applied": False, "reason": "missing_axis"})
            continue
        angle_to_y = _axis_angle_degrees(axis, (0.0, 1.0, 0.0))
        if angle_to_y <= 3.0:
            applied_specs.append({
                "group": spec["group"],
                "applied": False,
                "reason": "already_vertical",
                "angleToYDegrees": angle_to_y,
            })
            continue
        references = _median_anchor_relative_offsets(clip, spec["chains"])
        for frame_index, frame in enumerate(frames):
            joints = dict(frame.joints)
            for anchor_name, chain_joints in spec["chains"]:
                anchor = joints.get(anchor_name)
                if anchor is None:
                    continue
                for joint_name in chain_joints:
                    point = joints.get(joint_name)
                    reference = references.get((anchor_name, joint_name))
                    if point is None or reference is None:
                        continue
                    offset = _subtract(point, anchor)
                    delta = _subtract(offset, reference)
                    dominant_scalar = _dot(delta, axis)
                    perpendicular = _subtract(delta, _scale(axis, dominant_scalar))
                    target_delta = (
                        perpendicular[0] * 0.08,
                        dominant_scalar,
                        perpendicular[2] * 0.08,
                    )
                    joints[joint_name] = _add(anchor, _add(reference, target_delta))
            frames[frame_index] = MotionFrame(time_sec=frame.time_sec, joints=joints)
        applied_specs.append({
            "group": spec["group"],
            "applied": True,
            "axis": [float(axis[0]), float(axis[1]), float(axis[2])],
            "angleToYDegrees": angle_to_y,
            "perpendicularResidualScale": 0.08,
            "dominantRange": _dominant_chain_range(clip, spec["anchors"], spec["ends"]),
        })
    if not any(spec.get("applied") for spec in applied_specs):
        return clip, {"applied": False, "groups": applied_specs}
    return replace(clip, frames=frames), {
        "applied": True,
        "strategy": "anchor_relative_dominant_residual_remap_to_world_y",
        "groups": applied_specs,
    }


def _dominant_world_y_specs(dominant_groups: set[str]) -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    if "arms" in dominant_groups:
        specs.append({
            "group": "arms",
            "anchors": ("left_shoulder", "right_shoulder"),
            "ends": ("left_wrist", "right_wrist", "left_hand", "right_hand"),
            "chains": (
                ("left_shoulder", ("left_elbow", "left_wrist", "left_hand")),
                ("right_shoulder", ("right_elbow", "right_wrist", "right_hand")),
            ),
        })
    if "legs" in dominant_groups:
        specs.append({
            "group": "legs",
            "anchors": ("left_hip", "right_hip"),
            "ends": ("left_ankle", "right_ankle", "left_foot", "right_foot"),
            "chains": (
                ("left_hip", ("left_knee", "left_ankle", "left_foot")),
                ("right_hip", ("right_knee", "right_ankle", "right_foot")),
            ),
        })
    return specs


def _dominant_chain_axis(
    clip: MotionClip,
    anchors: tuple[str, ...],
    ends: tuple[str, ...],
) -> Point3 | None:
    samples: list[Point3] = []
    for frame in clip.frames:
        anchor_points = [frame.joints[name] for name in anchors if name in frame.joints]
        end_points = [frame.joints[name] for name in ends if name in frame.joints]
        if not anchor_points or not end_points:
            continue
        samples.append(_subtract(_average_points(end_points), _average_points(anchor_points)))
    if len(samples) < 3:
        return None
    axis = _principal_direction(samples)
    if axis is None:
        return None
    displacement = _subtract(samples[-1], samples[0])
    if _dot(axis, displacement) < 0.0:
        axis = _scale(axis, -1.0)
    return axis


def _dominant_chain_range(
    clip: MotionClip,
    anchors: tuple[str, ...],
    ends: tuple[str, ...],
) -> float:
    samples: list[Point3] = []
    for frame in clip.frames:
        anchor_points = [frame.joints[name] for name in anchors if name in frame.joints]
        end_points = [frame.joints[name] for name in ends if name in frame.joints]
        if not anchor_points or not end_points:
            continue
        samples.append(_subtract(_average_points(end_points), _average_points(anchor_points)))
    if len(samples) < 2:
        return 0.0
    center = _average_points(samples)
    return max(_distance(sample, center) for sample in samples) * 2.0


def _median_anchor_relative_offsets(
    clip: MotionClip,
    chains: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict[tuple[str, str], Point3]:
    references: dict[tuple[str, str], Point3] = {}
    for anchor_name, joint_names in chains:
        for joint_name in joint_names:
            offsets = [
                _subtract(frame.joints[joint_name], frame.joints[anchor_name])
                for frame in clip.frames
                if anchor_name in frame.joints and joint_name in frame.joints
            ]
            if offsets:
                references[(anchor_name, joint_name)] = _median_point(offsets)
    return references


def _chain_motion_summary(clip: MotionClip) -> dict[str, float]:
    return {
        "torso": _joint_group_motion(clip, [joint for joint in TORSO_STABILITY_JOINTS if joint in clip.joint_names]),
        "leftArm": _joint_group_motion(clip, ["left_elbow", "left_wrist", "left_hand"]),
        "rightArm": _joint_group_motion(clip, ["right_elbow", "right_wrist", "right_hand"]),
        "leftLeg": _joint_group_motion(clip, ["left_knee", "left_ankle", "left_foot"]),
        "rightLeg": _joint_group_motion(clip, ["right_knee", "right_ankle", "right_foot"]),
        "head": _joint_group_motion(clip, ["head", "neck"]),
    }


def _chain_range_summary(clip: MotionClip) -> dict[str, float]:
    return {
        "torso": _joint_group_root_relative_range(
            clip,
            [joint for joint in TORSO_STABILITY_JOINTS if joint in clip.joint_names],
        ),
        "arms": max(
            _dominant_chain_range(clip, ("left_shoulder",), ("left_elbow", "left_wrist", "left_hand")),
            _dominant_chain_range(clip, ("right_shoulder",), ("right_elbow", "right_wrist", "right_hand")),
            _dominant_chain_range(
                clip,
                ("left_shoulder", "right_shoulder"),
                ("left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hand", "right_hand"),
            ),
        ),
        "legs": max(
            _dominant_chain_range(clip, ("left_hip",), ("left_knee", "left_ankle", "left_foot")),
            _dominant_chain_range(clip, ("right_hip",), ("right_knee", "right_ankle", "right_foot")),
            _dominant_chain_range(
                clip,
                ("left_hip", "right_hip"),
                ("left_knee", "right_knee", "left_ankle", "right_ankle", "left_foot", "right_foot"),
            ),
        ),
    }


def _refine_non_torso_dominant_motion_by_transfer(
    clip: MotionClip,
    *,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    refined, transfer_metadata = _transfer_selected_motion_to_canonical_body(
        clip,
        dominant_profile=dominant_profile,
    )
    refined, length_metadata = _preserve_reference_bone_lengths(refined, reference_clip=clip)
    refined, exact_bilateral_metadata = _enforce_exact_same_phase_bilateral_symmetry(
        refined,
        transfer_metadata=transfer_metadata,
    )
    refined, reapplied_metadata = _reapply_dominant_local_motion(
        refined,
        reference_clip=clip,
        dominant_profile=dominant_profile,
    )
    refined, paired_hands_metadata = _preserve_same_phase_paired_hand_path(
        refined,
        reference_clip=clip,
        transfer_metadata=transfer_metadata,
    )
    if dominant_groups == {"arms"}:
        root_vertical_metadata = {
            "applied": False,
            "reason": "root_vertical_motion_not_part_of_arms_only_dominant_motion",
        }
    else:
        refined, root_vertical_metadata = _preserve_reference_root_vertical_motion(refined, reference_clip=clip)
    return refined, {
        "strategy": "canonical_body_selected_motion_transfer",
        "selectedMotionTransfer": transfer_metadata,
        "boneLengthProjection": length_metadata,
        "exactBilateralSymmetry": exact_bilateral_metadata,
        "dominantLocalMotionReapplication": reapplied_metadata,
        "pairedHandPathPreservation": paired_hands_metadata,
        "rootVerticalMotionPreservation": root_vertical_metadata,
        "steps": [
            "canonical_body_estimation",
            "selected_dominant_motion_transfer",
            "reference_bone_length_projection",
            "exact_same_phase_bilateral_symmetry",
            "dominant_local_motion_reapplication",
            "same_phase_paired_hand_path_preservation",
            "reference_root_vertical_motion_preservation",
        ],
    }


def _refine_torso_dominant_motion_conservatively(
    clip: MotionClip,
    *,
    active_threshold: float,
    strongest_chain_motion: float,
    dominant_profile: dict[str, object],
    non_dominant_radius_scale: float,
) -> tuple[MotionClip, dict[str, object]]:
    refined, jitter_metadata = _suppress_low_magnitude_motion(
        clip,
        active_threshold=active_threshold,
        strongest_chain_motion=strongest_chain_motion,
        dominant_profile=dominant_profile,
    )
    refined, spike_metadata = _suppress_temporal_spikes(refined, active_threshold=active_threshold)
    refined, target_constraint_metadata = _constrain_to_stabilized_ik_targets(
        refined,
        stabilized_target_clip=clip,
        dominant_profile=dominant_profile,
        non_dominant_radius_scale=non_dominant_radius_scale,
    )
    refined, distal_leg_metadata = _stabilize_torso_dominant_distal_leg_sliding(refined, reference_clip=clip)
    refined, foot_axis_leg_metadata = _align_leg_motion_to_foot_axis(refined, reference_clip=clip)
    refined, length_metadata = _preserve_reference_bone_lengths(refined, reference_clip=clip)
    return refined, {
        "strategy": "torso_dominant_conservative_cleanup",
        "lowMagnitudeSuppression": jitter_metadata,
        "temporalSpikes": spike_metadata,
        "stabilizedIkTargetConstraint": target_constraint_metadata,
        "distalLegSlidingStabilization": distal_leg_metadata,
        "footAxisLegAlignment": foot_axis_leg_metadata,
        "boneLengthProjection": length_metadata,
        "steps": [
            "torso_dominant_preserve_body_motion",
            "low_magnitude_motion_suppression",
            "isolated_temporal_spike_suppression",
            "stabilized_ik_target_constraint",
            "torso_dominant_distal_leg_sliding_stabilization",
            "foot_axis_leg_motion_alignment",
            "reference_bone_length_projection",
        ],
    }


def _transfer_selected_motion_to_canonical_body(
    clip: MotionClip,
    *,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    if "torso" not in dominant_groups:
        canonical_joints, canonical_metadata = _build_non_torso_dominant_scaffold(
            clip,
            dominant_groups=dominant_groups,
        )
    else:
        canonical_joints, canonical_metadata = _build_canonical_body_pose(
            clip,
            preserve_chain_offsets=True,
        )
    if not canonical_joints:
        return clip, {"applied": False, "reason": "canonical_body_unavailable"}
    bilateral_modes = _dominant_bilateral_motion_modes(clip, dominant_groups)
    transferred_joints: set[str] = set()
    frames: list[MotionFrame] = []
    for source_frame in clip.frames:
        joints = dict(canonical_joints)
        if "arms" in dominant_groups:
            for side in ("left", "right"):
                _transfer_dominant_chain(
                    source_frame,
                    joints,
                    root_joint=f"{side}_shoulder",
                    mid_joint=f"{side}_elbow",
                    end_joint=f"{side}_wrist",
                    extra_joint=f"{side}_hand",
                    bilateral_modes=bilateral_modes,
                    transferred_joints=transferred_joints,
                )
        if "legs" in dominant_groups:
            for side in ("left", "right"):
                _transfer_dominant_chain(
                    source_frame,
                    joints,
                    root_joint=f"{side}_hip",
                    mid_joint=f"{side}_knee",
                    end_joint=f"{side}_ankle",
                    extra_joint=f"{side}_foot",
                    bilateral_modes=bilateral_modes,
                    transferred_joints=transferred_joints,
                )
        frames.append(MotionFrame(time_sec=source_frame.time_sec, joints=joints))
    refined = replace(clip, frames=frames)
    return refined, {
        "applied": True,
        "dominantGroups": sorted(dominant_groups),
        "transferredJoints": sorted(transferred_joints),
        "canonicalBody": canonical_metadata,
        "bilateralModes": bilateral_modes,
        "target": "canonical_body_plus_selected_local_motion",
    }


def _stabilize_torso_dominant_distal_leg_sliding(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    side_configs: list[dict[str, object]] = []
    for side in ("left", "right"):
        hip = f"{side}_hip"
        knee = f"{side}_knee"
        ankle = f"{side}_ankle"
        foot = f"{side}_foot"
        required = (hip, knee, ankle)
        if any(joint not in clip.joint_names or joint not in reference_clip.joint_names for joint in required):
            continue
        knee_range = _joint_root_relative_vertical_range(reference_clip, knee, hip)
        ankle_range = _joint_root_relative_vertical_range(reference_clip, ankle, hip)
        foot_range = _joint_root_relative_vertical_range(reference_clip, foot, hip) if foot in reference_clip.joint_names else 0.0
        if knee_range > 0.08:
            continue
        if max(ankle_range, foot_range) < max(0.12, knee_range * 2.5):
            continue
        side_configs.append({
            "side": side,
            "hip": hip,
            "knee": knee,
            "ankle": ankle,
            "foot": foot if foot in clip.joint_names and foot in reference_clip.joint_names else None,
            "kneeRange": knee_range,
            "ankleRange": ankle_range,
            "footRange": foot_range,
            "hipToAnkle": _median_root_relative_offset(reference_clip, hip, ankle),
            "ankleToFoot": _median_root_relative_offset(reference_clip, ankle, foot) if foot in reference_clip.joint_names else None,
            "upperLen": _median_bone_length(reference_clip, hip, knee),
            "lowerLen": _median_bone_length(reference_clip, knee, ankle),
        })
    if not side_configs:
        return clip, {"applied": False, "reason": "no_distal_leg_sliding_detected"}

    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        joints = dict(frame.joints)
        body_frame = _body_local_frame(frame)
        fallback_axis = body_frame.forward if body_frame is not None else (0.0, 0.0, 1.0)
        for config in side_configs:
            hip = str(config["hip"])
            knee = str(config["knee"])
            ankle = str(config["ankle"])
            foot = config.get("foot")
            if hip not in joints or knee not in joints or ankle not in joints:
                continue
            target_ankle = _add(joints[hip], config["hipToAnkle"])  # type: ignore[arg-type]
            solved_knee, solved_ankle = _solve_two_bone(
                root=joints[hip],
                current_mid=joints[knee],
                target_end=target_ankle,
                upper_len=float(config["upperLen"]),
                lower_len=float(config["lowerLen"]),
                fallback_axis=fallback_axis,
            )
            for joint_name, target in ((knee, solved_knee), (ankle, solved_ankle)):
                displacement = _distance(joints[joint_name], target)
                if displacement > 1e-6:
                    total_displacement += displacement
                    max_displacement = max(max_displacement, displacement)
                    samples += 1
                joints[joint_name] = target
            if isinstance(foot, str) and foot in joints and config.get("ankleToFoot") is not None:
                target_foot = _add(joints[ankle], config["ankleToFoot"])  # type: ignore[arg-type]
                displacement = _distance(joints[foot], target_foot)
                if displacement > 1e-6:
                    total_displacement += displacement
                    max_displacement = max(max_displacement, displacement)
                    samples += 1
                joints[foot] = target_foot
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": True,
        "sides": side_configs,
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "target": "stable_hip_relative_ankle_foot_offsets_for_sliding_distal_leg",
    }


def _align_leg_motion_to_foot_axis(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    side_configs: list[dict[str, object]] = []
    for side in ("left", "right"):
        hip = f"{side}_hip"
        knee = f"{side}_knee"
        ankle = f"{side}_ankle"
        foot = f"{side}_foot"
        required = (hip, knee, ankle, foot)
        if any(joint not in clip.joint_names or joint not in reference_clip.joint_names for joint in required):
            continue
        leg_horizontal_range = max(
            _joint_root_relative_horizontal_range(reference_clip, knee, hip),
            _joint_root_relative_horizontal_range(reference_clip, ankle, hip),
            _joint_root_relative_horizontal_range(reference_clip, foot, hip),
        )
        if leg_horizontal_range > 0.09:
            continue
        foot_axis = _horizontal_axis(_median_root_relative_offset(reference_clip, ankle, foot))
        if foot_axis is None:
            continue
        side_configs.append({
            "side": side,
            "hip": hip,
            "knee": knee,
            "ankle": ankle,
            "foot": foot,
            "footAxis": foot_axis,
            "legHorizontalRange": leg_horizontal_range,
            "hipToKnee": _median_root_relative_offset(reference_clip, hip, knee),
            "hipToAnkle": _median_root_relative_offset(reference_clip, hip, ankle),
        })
    if not side_configs:
        return clip, {"applied": False, "reason": "no_valid_foot_axes"}

    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        joints = dict(frame.joints)
        for config in side_configs:
            hip = str(config["hip"])
            foot_axis = config["footAxis"]  # type: ignore[assignment]
            if hip not in joints:
                continue
            for joint_name, baseline_key in ((str(config["knee"]), "hipToKnee"), (str(config["ankle"]), "hipToAnkle")):
                if joint_name not in joints:
                    continue
                baseline = config[baseline_key]  # type: ignore[assignment]
                current_offset = _subtract(joints[joint_name], joints[hip])
                residual = _subtract(current_offset, baseline)  # type: ignore[arg-type]
                forward_amount = _dot((residual[0], 0.0, residual[2]), foot_axis)  # type: ignore[arg-type]
                aligned_residual = (
                    foot_axis[0] * forward_amount,  # type: ignore[index]
                    residual[1],
                    foot_axis[2] * forward_amount,  # type: ignore[index]
                )
                target = _add(joints[hip], _add(baseline, aligned_residual))  # type: ignore[arg-type]
                displacement = _distance(joints[joint_name], target)
                if displacement > 1e-6:
                    total_displacement += displacement
                    max_displacement = max(max_displacement, displacement)
                    samples += 1
                joints[joint_name] = target
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": samples > 0,
        "sides": side_configs,
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "target": "knee_ankle_horizontal_motion_projected_onto_foot_forward_axis",
    }


def _horizontal_axis(axis: Point3) -> Point3 | None:
    return _normalize((axis[0], 0.0, axis[2]))


def _joint_root_relative_vertical_range(clip: MotionClip, joint_name: str, root_joint: str) -> float:
    values = [
        frame.joints[joint_name][1] - frame.joints[root_joint][1]
        for frame in clip.frames
        if joint_name in frame.joints and root_joint in frame.joints
    ]
    return max(values) - min(values) if values else 0.0


def _joint_axis_values(clip: MotionClip, joint_name: str, *, axis: int) -> list[float]:
    return [
        frame.joints[joint_name][axis]
        for frame in clip.frames
        if joint_name in frame.joints
    ]


def _value_range(values: list[float]) -> float:
    if not values:
        return 0.0
    return max(values) - min(values)


def _joint_root_relative_horizontal_range(clip: MotionClip, joint_name: str, root_joint: str) -> float:
    offsets = [
        _subtract(frame.joints[joint_name], frame.joints[root_joint])
        for frame in clip.frames
        if joint_name in frame.joints and root_joint in frame.joints
    ]
    if not offsets:
        return 0.0
    return max(
        max(offset[0] for offset in offsets) - min(offset[0] for offset in offsets),
        max(offset[2] for offset in offsets) - min(offset[2] for offset in offsets),
    )


def _joint_group_root_relative_range(clip: MotionClip, joint_names: list[str]) -> float:
    root_joint = next((joint for joint in ROOT_VERTICAL_MOTION_JOINTS if joint in clip.joint_names), None)
    if root_joint is None:
        return 0.0
    max_range = 0.0
    for joint_name in joint_names:
        offsets = [
            _subtract(frame.joints[joint_name], frame.joints[root_joint])
            for frame in clip.frames
            if joint_name in frame.joints and root_joint in frame.joints
        ]
        if len(offsets) < 2:
            continue
        ranges = [
            max(offset[axis] for offset in offsets) - min(offset[axis] for offset in offsets)
            for axis in range(3)
        ]
        max_range = max(max_range, math.sqrt(sum(axis_range * axis_range for axis_range in ranges)))
    return max_range


def _median_root_relative_offset(clip: MotionClip, root_joint: str, joint_name: str) -> Point3:
    return _median_point([
        _subtract(frame.joints[joint_name], frame.joints[root_joint])
        for frame in clip.frames
        if root_joint in frame.joints and joint_name in frame.joints
    ])


def _build_canonical_body_pose(
    clip: MotionClip,
    *,
    preserve_chain_offsets: bool = False,
) -> tuple[dict[str, Point3], dict[str, object]]:
    stable, _stable_metadata = _build_stable_body_pose(clip)
    required = ("pelvis", "left_hip", "right_hip", "left_shoulder", "right_shoulder")
    if any(joint not in stable for joint in required):
        return stable, {"straightened": False, "reason": "missing_body_frame_joints"}
    spine_top_name = "neck" if "neck" in stable else "spine3" if "spine3" in stable else "head" if "head" in stable else None
    if spine_top_name is None:
        return stable, {"straightened": False, "reason": "missing_spine_top"}
    spine_axis = _normalize(_subtract(stable[spine_top_name], stable["pelvis"]))
    if spine_axis is None:
        return stable, {"straightened": False, "reason": "invalid_spine_axis"}
    shoulder_axis = _subtract(stable["right_shoulder"], stable["left_shoulder"])
    hip_axis = _subtract(stable["right_hip"], stable["left_hip"])
    shoulder_right = _project_axis_perpendicular_to(shoulder_axis, spine_axis)
    hip_right = _project_axis_perpendicular_to(hip_axis, spine_axis)
    canonical_right = shoulder_right or hip_right
    if shoulder_right is not None and hip_right is not None:
        canonical_right = _normalize(_add(shoulder_right, hip_right)) or shoulder_right
    if canonical_right is None:
        return stable, {"straightened": False, "reason": "invalid_lateral_axis"}

    canonical = dict(stable)
    spine_chain = [joint for joint in ("pelvis", "spine1", "spine2", "spine3", "neck") if joint in stable]
    for joint_name, distance_from_pelvis in _spine_chain_distances(stable, spine_chain).items():
        canonical[joint_name] = _add(stable["pelvis"], _scale(spine_axis, distance_from_pelvis))
    hip_center = _project_center_to_spine_level(_average_points([stable["left_hip"], stable["right_hip"]]), stable["pelvis"], spine_axis)
    shoulder_center = _project_center_to_spine_level(
        _average_points([stable["left_shoulder"], stable["right_shoulder"]]),
        stable["pelvis"],
        spine_axis,
    )
    hip_half_width = _length(hip_axis) * 0.5
    shoulder_half_width = _length(shoulder_axis) * 0.5
    canonical["left_hip"] = _add(hip_center, _scale(canonical_right, -hip_half_width))
    canonical["right_hip"] = _add(hip_center, _scale(canonical_right, hip_half_width))
    canonical["left_shoulder"] = _add(shoulder_center, _scale(canonical_right, -shoulder_half_width))
    canonical["right_shoulder"] = _add(shoulder_center, _scale(canonical_right, shoulder_half_width))
    for side in ("left", "right"):
        collar = f"{side}_collar"
        shoulder = f"{side}_shoulder"
        if collar in canonical:
            canonical[collar] = _add(stable[collar], _subtract(canonical[shoulder], stable[shoulder]))
    if "head" in canonical and spine_top_name in canonical:
        head_offset = max(0.0, _dot(_subtract(stable["head"], stable[spine_top_name]), spine_axis))
        canonical["head"] = _add(canonical[spine_top_name], _scale(spine_axis, head_offset))
    body_frame = _body_local_frame(MotionFrame(time_sec=0.0, joints=canonical))
    if body_frame is not None:
        chain_placer = _preserve_stable_chain_offsets if preserve_chain_offsets else _place_canonical_bilateral_rest_chains
        chain_placer(
            stable,
            canonical,
            body_frame=body_frame,
            group_name="legs",
            left_root="left_hip",
            right_root="right_hip",
            left_mid="left_knee",
            right_mid="right_knee",
            left_end="left_ankle",
            right_end="right_ankle",
            left_extra="left_foot",
            right_extra="right_foot",
        )
        chain_placer(
            stable,
            canonical,
            body_frame=body_frame,
            group_name="arms",
            left_root="left_shoulder",
            right_root="right_shoulder",
            left_mid="left_elbow",
            right_mid="right_elbow",
            left_end="left_wrist",
            right_end="right_wrist",
            left_extra="left_hand",
            right_extra="right_hand",
        )
    return canonical, {
        "straightened": True,
        "jointCount": len(canonical),
        "target": (
            "median_pose_straight_spine_parallel_hips_shoulders_preserve_chain_offsets"
            if preserve_chain_offsets
            else "median_pose_straight_spine_parallel_hips_shoulders"
        ),
    }


def _build_stable_body_pose(
    clip: MotionClip,
    *,
    stable_joints: set[str] | None = None,
    coherent_frame: bool = False,
) -> tuple[dict[str, Point3], dict[str, object]]:
    median_pose = {
        joint_name: _median_point([
            frame.joints[joint_name]
            for frame in clip.frames
            if joint_name in frame.joints
        ])
        for joint_name in clip.joint_names
    }
    if coherent_frame:
        representative = _representative_stable_frame_pose(
            clip,
            median_pose=median_pose,
            stable_joints=stable_joints or set(clip.joint_names),
        )
        if representative is not None:
            return representative, {
                "straightened": False,
                "jointCount": len(representative),
                "target": "representative_frame_pose_without_torso_or_chain_canonicalization",
            }
    return median_pose, {
        "straightened": False,
        "jointCount": len(median_pose),
        "target": "median_pose_without_torso_or_chain_canonicalization",
    }


def _build_non_torso_dominant_scaffold(
    clip: MotionClip,
    *,
    dominant_groups: set[str],
) -> tuple[dict[str, Point3], dict[str, object]]:
    representative, representative_metadata = _build_stable_body_pose(
        clip,
        stable_joints=_stable_scaffold_joints_for_dominant_groups(clip, dominant_groups),
        coherent_frame=True,
    )
    if "arms" in dominant_groups and "legs" not in dominant_groups:
        scaffold = _canonicalize_static_non_dominant_body(
            representative,
            canonicalize_legs=False,
        )
        if scaffold is not None:
            return scaffold, {
                "straightened": True,
                "jointCount": len(scaffold),
                "source": representative_metadata.get("target"),
                "target": "representative_frame_straight_torso_preserve_non_dominant_leg_pose",
            }
    return representative, representative_metadata


def _canonicalize_static_non_dominant_body(
    stable: dict[str, Point3],
    *,
    canonicalize_legs: bool,
) -> dict[str, Point3] | None:
    required = ("pelvis", "left_hip", "right_hip", "left_shoulder", "right_shoulder")
    if any(joint not in stable for joint in required):
        return None
    spine_top_name = "neck" if "neck" in stable else "spine3" if "spine3" in stable else "head" if "head" in stable else None
    if spine_top_name is None:
        return None
    spine_axis = _normalize(_subtract(stable[spine_top_name], stable["pelvis"]))
    if spine_axis is None:
        return None
    shoulder_axis = _subtract(stable["right_shoulder"], stable["left_shoulder"])
    hip_axis = _subtract(stable["right_hip"], stable["left_hip"])
    shoulder_right = _project_axis_perpendicular_to(shoulder_axis, spine_axis)
    hip_right = _project_axis_perpendicular_to(hip_axis, spine_axis)
    canonical_right = shoulder_right or hip_right
    if shoulder_right is not None and hip_right is not None:
        canonical_right = _normalize(_add(shoulder_right, hip_right)) or shoulder_right
    if canonical_right is None:
        return None

    canonical = dict(stable)
    spine_chain = [joint for joint in ("pelvis", "spine1", "spine2", "spine3", "neck") if joint in stable]
    for joint_name, distance_from_pelvis in _spine_chain_distances(stable, spine_chain).items():
        canonical[joint_name] = _add(stable["pelvis"], _scale(spine_axis, distance_from_pelvis))
    hip_center = _project_center_to_spine_level(
        _average_points([stable["left_hip"], stable["right_hip"]]),
        stable["pelvis"],
        spine_axis,
    )
    shoulder_center = _project_center_to_spine_level(
        _average_points([stable["left_shoulder"], stable["right_shoulder"]]),
        stable["pelvis"],
        spine_axis,
    )
    shoulder_half_width = _length(shoulder_axis) * 0.5
    hip_half_width = max(_length(hip_axis) * 0.5, shoulder_half_width * 0.45)
    canonical["left_hip"] = _add(hip_center, _scale(canonical_right, -hip_half_width))
    canonical["right_hip"] = _add(hip_center, _scale(canonical_right, hip_half_width))
    canonical["left_shoulder"] = _add(shoulder_center, _scale(canonical_right, -shoulder_half_width))
    canonical["right_shoulder"] = _add(shoulder_center, _scale(canonical_right, shoulder_half_width))
    for collar_name, shoulder_name in (("left_collar", "left_shoulder"), ("right_collar", "right_shoulder")):
        if collar_name in canonical:
            canonical[collar_name] = _add(stable[collar_name], _subtract(canonical[shoulder_name], stable[shoulder_name]))
    if "head" in canonical and spine_top_name in canonical:
        head_offset = max(0.0, _dot(_subtract(stable["head"], stable[spine_top_name]), spine_axis))
        canonical["head"] = _add(canonical[spine_top_name], _scale(spine_axis, head_offset))
    if canonicalize_legs:
        replacements = _straightened_non_dominant_leg_replacements(stable, canonical, canonical_right)
        canonical.update(replacements)
    else:
        body_frame = _body_local_frame(MotionFrame(time_sec=0.0, joints=canonical))
        if body_frame is not None:
            _preserve_stable_chain_offsets(
                stable,
                canonical,
                body_frame=body_frame,
                group_name="legs",
                left_root="left_hip",
                right_root="right_hip",
                left_mid="left_knee",
                right_mid="right_knee",
                left_end="left_ankle",
                right_end="right_ankle",
                left_extra="left_foot",
                right_extra="right_foot",
            )
    return canonical


def _stable_scaffold_joints_for_dominant_groups(clip: MotionClip, dominant_groups: set[str]) -> set[str]:
    joints = set(clip.joint_names)
    if "arms" in dominant_groups:
        joints.difference_update({
            "left_elbow",
            "right_elbow",
            "left_wrist",
            "right_wrist",
            "left_hand",
            "right_hand",
        })
    if "legs" in dominant_groups:
        joints.difference_update({
            "left_knee",
            "right_knee",
            "left_ankle",
            "right_ankle",
            "left_foot",
            "right_foot",
        })
    return joints


def _representative_stable_frame_pose(
    clip: MotionClip,
    *,
    median_pose: dict[str, Point3],
    stable_joints: set[str],
) -> dict[str, Point3] | None:
    scored_frames: list[tuple[float, int, MotionFrame]] = []
    for frame_index, frame in enumerate(clip.frames):
        score = 0.0
        samples = 0
        for joint_name in stable_joints:
            point = frame.joints.get(joint_name)
            median_point = median_pose.get(joint_name)
            if point is None or median_point is None:
                continue
            distance = _distance(point, median_point)
            score += distance * distance
            samples += 1
        if samples:
            scored_frames.append((score / samples, frame_index, frame))
    if not scored_frames:
        return None
    _score, frame_index, frame = min(scored_frames, key=lambda item: (item[0], abs(item[1] - clip.frame_count * 0.5)))
    return {
        joint_name: frame.joints.get(joint_name, median_pose[joint_name])
        for joint_name in clip.joint_names
        if joint_name in frame.joints or joint_name in median_pose
    }


def _preserve_stable_chain_offsets(
    stable: dict[str, Point3],
    canonical: dict[str, Point3],
    *,
    body_frame: "BodyFrame",
    group_name: str,
    left_root: str,
    right_root: str,
    left_mid: str,
    right_mid: str,
    left_end: str,
    right_end: str,
    left_extra: str | None,
    right_extra: str | None,
) -> None:
    if (
        left_root in stable
        and right_root in stable
        and left_root in canonical
        and right_root in canonical
    ):
        for left_joint, right_joint in ((left_mid, right_mid), (left_end, right_end)):
            if left_joint not in stable or right_joint not in stable:
                continue
            left_offset = _to_local(stable[left_joint], body_frame, stable[left_root])
            right_offset = _to_local(stable[right_joint], body_frame, stable[right_root])
            left_target, right_target = _canonical_mirrored_offsets(left_offset, right_offset, group_name=group_name)
            canonical[left_joint] = _from_local(left_target, body_frame, canonical[left_root])
            canonical[right_joint] = _from_local(right_target, body_frame, canonical[right_root])
        if left_extra and right_extra and left_extra in stable and right_extra in stable:
            left_offset = _to_local(stable[left_extra], body_frame, stable[left_root])
            right_offset = _to_local(stable[right_extra], body_frame, stable[right_root])
            left_target, right_target = _canonical_mirrored_offsets(left_offset, right_offset, group_name=group_name)
            canonical[left_extra] = _from_local(left_target, body_frame, canonical[left_root])
            canonical[right_extra] = _from_local(right_target, body_frame, canonical[right_root])
        return

    for root_joint, child_joints in (
        (left_root, (left_mid, left_end, left_extra)),
        (right_root, (right_mid, right_end, right_extra)),
    ):
        if root_joint not in stable or root_joint not in canonical:
            continue
        for child_joint in child_joints:
            if child_joint is None or child_joint not in stable:
                continue
            stable_offset = _to_local(stable[child_joint], body_frame, stable[root_joint])
            canonical[child_joint] = _from_local(stable_offset, body_frame, canonical[root_joint])


def _place_canonical_bilateral_rest_chains(
    stable: dict[str, Point3],
    canonical: dict[str, Point3],
    *,
    body_frame: "BodyFrame",
    group_name: str,
    left_root: str,
    right_root: str,
    left_mid: str,
    right_mid: str,
    left_end: str,
    right_end: str,
    left_extra: str | None,
    right_extra: str | None,
) -> None:
    required = (left_root, right_root, left_mid, right_mid, left_end, right_end)
    if any(joint not in stable or joint not in canonical for joint in (left_root, right_root)):
        return
    if any(joint not in stable for joint in required):
        return
    joint_pairs = ((left_mid, right_mid), (left_end, right_end))
    for left_joint, right_joint in joint_pairs:
        left_offset = _to_local(stable[left_joint], body_frame, stable[left_root])
        right_offset = _to_local(stable[right_joint], body_frame, stable[right_root])
        left_target, right_target = _canonical_mirrored_offsets(left_offset, right_offset, group_name=group_name)
        canonical[left_joint] = _from_local(left_target, body_frame, canonical[left_root])
        canonical[right_joint] = _from_local(right_target, body_frame, canonical[right_root])
    if left_extra and right_extra and left_extra in stable and right_extra in stable:
        left_offset = _to_local(stable[left_extra], body_frame, stable[left_root])
        right_offset = _to_local(stable[right_extra], body_frame, stable[right_root])
        left_target, right_target = _canonical_mirrored_offsets(left_offset, right_offset, group_name=group_name)
        canonical[left_extra] = _from_local(left_target, body_frame, canonical[left_root])
        canonical[right_extra] = _from_local(right_target, body_frame, canonical[right_root])


def _canonical_mirrored_offsets(left_offset: Point3, right_offset: Point3, *, group_name: str) -> tuple[Point3, Point3]:
    lateral = (abs(left_offset[0]) + abs(right_offset[0])) * 0.5
    shared_y = (left_offset[1] + right_offset[1]) * 0.5
    shared_z = (left_offset[2] + right_offset[2]) * 0.5
    if group_name == "legs":
        lateral = max(0.0, lateral * 0.35)
    return (-lateral, shared_y, shared_z), (lateral, shared_y, shared_z)


def _transfer_dominant_chain(
    source_frame: MotionFrame,
    joints: dict[str, Point3],
    *,
    root_joint: str,
    mid_joint: str,
    end_joint: str,
    extra_joint: str | None,
    bilateral_modes: dict[str, dict[str, object]],
    transferred_joints: set[str],
) -> None:
    required = (root_joint, mid_joint, end_joint)
    if any(joint not in source_frame.joints or joint not in joints for joint in required):
        return
    stable_frame = MotionFrame(time_sec=source_frame.time_sec, joints=joints)
    mid_offset = _dominant_local_target_offset(
        source_frame,
        stable_frame=stable_frame,
        anchor_joint=root_joint,
        child_joint=mid_joint,
        bilateral_modes=bilateral_modes,
    )
    end_offset = _dominant_local_target_offset(
        source_frame,
        stable_frame=stable_frame,
        anchor_joint=root_joint,
        child_joint=end_joint,
        bilateral_modes=bilateral_modes,
    )
    if mid_offset is None or end_offset is None:
        return
    root = joints[root_joint]
    target_mid = _add(root, mid_offset)
    target_end = _add(root, end_offset)
    upper_len = _distance(joints[root_joint], joints[mid_joint])
    lower_len = _distance(joints[mid_joint], joints[end_joint])
    length_mode = _same_phase_bilateral_group_for_chain(root_joint, bilateral_modes)
    if length_mode is not None:
        opposite_root, opposite_mid, opposite_end = _opposite_chain_joints(root_joint, mid_joint, end_joint)
        if (
            opposite_root in joints
            and opposite_mid in joints
            and opposite_end in joints
        ):
            upper_len = (upper_len + _distance(joints[opposite_root], joints[opposite_mid])) * 0.5
            lower_len = (lower_len + _distance(joints[opposite_mid], joints[opposite_end])) * 0.5
    body_frame = _body_local_frame(stable_frame)
    solved_mid, solved_end = _solve_two_bone(
        root=root,
        current_mid=target_mid,
        target_end=target_end,
        upper_len=upper_len,
        lower_len=lower_len,
        fallback_axis=body_frame.forward if body_frame is not None else (0.0, 0.0, 1.0),
    )
    joints[mid_joint] = solved_mid
    joints[end_joint] = solved_end
    transferred_joints.update((mid_joint, end_joint))
    if extra_joint and extra_joint in source_frame.joints and extra_joint in joints:
        extra_offset = _dominant_local_target_offset(
            source_frame,
            stable_frame=stable_frame,
            anchor_joint=root_joint,
            child_joint=extra_joint,
            bilateral_modes=bilateral_modes,
        )
        if extra_offset is not None:
            joints[extra_joint] = _add(root, extra_offset)
            transferred_joints.add(extra_joint)


def _enforce_exact_same_phase_bilateral_symmetry(
    clip: MotionClip,
    *,
    transfer_metadata: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    modes = transfer_metadata.get("bilateralModes") if isinstance(transfer_metadata, dict) else None
    if not isinstance(modes, dict):
        return clip, {"applied": False, "reason": "missing_bilateral_modes"}
    arms_mode = modes.get("arms")
    if not isinstance(arms_mode, dict) or arms_mode.get("mode") != "same_phase_symmetric":
        return clip, {"applied": False, "reason": "arms_not_same_phase_symmetric"}
    pairs = (
        ("left_elbow", "right_elbow"),
        ("left_wrist", "right_wrist"),
        ("left_hand", "right_hand"),
    )
    required = ("left_shoulder", "right_shoulder", *[joint for pair in pairs for joint in pair])
    if any(joint not in clip.joint_names for joint in required):
        return clip, {"applied": False, "reason": "missing_arm_joints"}

    frames: list[MotionFrame] = []
    max_displacement = 0.0
    total_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        body_frame = _body_local_frame(frame)
        if body_frame is None:
            frames.append(frame)
            continue
        joints = dict(frame.joints)
        for left_joint, right_joint in pairs:
            left_local = _to_local(joints[left_joint], body_frame, joints["left_shoulder"])
            right_local = _to_local(joints[right_joint], body_frame, joints["right_shoulder"])
            lateral = (abs(left_local[0]) + abs(right_local[0])) * 0.5
            shared_y = (left_local[1] + right_local[1]) * 0.5
            shared_z = (left_local[2] + right_local[2]) * 0.5
            left_target = _from_local((-lateral, shared_y, shared_z), body_frame, joints["left_shoulder"])
            right_target = _from_local((lateral, shared_y, shared_z), body_frame, joints["right_shoulder"])
            for joint_name, target in ((left_joint, left_target), (right_joint, right_target)):
                displacement = _distance(joints[joint_name], target)
                if displacement > 1e-6:
                    total_displacement += displacement
                    max_displacement = max(max_displacement, displacement)
                    samples += 1
                joints[joint_name] = target
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": True,
        "groups": ["arms"],
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "target": "exact_body_local_mirrored_arm_pairs",
    }


def _preserve_same_phase_paired_hand_path(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    transfer_metadata: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    modes = transfer_metadata.get("bilateralModes") if isinstance(transfer_metadata, dict) else None
    arms_mode = modes.get("arms") if isinstance(modes, dict) else None
    if not isinstance(arms_mode, dict) or arms_mode.get("mode") != "same_phase_symmetric":
        return clip, {"applied": False, "reason": "arms_not_same_phase_symmetric"}
    required = (
        "left_shoulder",
        "right_shoulder",
        "left_elbow",
        "right_elbow",
        "left_wrist",
        "right_wrist",
    )
    if any(joint not in clip.joint_names for joint in required):
        return clip, {"applied": False, "reason": "missing_arm_joints"}

    endpoint_pairs = [
        ("left_wrist", "right_wrist"),
    ]
    if "left_hand" in clip.joint_names and "right_hand" in clip.joint_names:
        endpoint_pairs.append(("left_hand", "right_hand"))
    path_constraints = _paired_endpoint_path_constraints(clip, endpoint_pairs)
    if path_constraints is None:
        return clip, {"applied": False, "reason": "missing_endpoint_widths"}
    half_widths = path_constraints["half_widths"]
    shared_axis_bounds = path_constraints["shared_axis_bounds"]
    elbow_axis_bounds = path_constraints["elbow_axis_bounds"]
    elbow_half_width = float(path_constraints["elbow_half_width"])

    left_upper_len = _median_bone_length(reference_clip, "left_shoulder", "left_elbow")
    left_lower_len = _median_bone_length(reference_clip, "left_elbow", "left_wrist")
    right_upper_len = _median_bone_length(reference_clip, "right_shoulder", "right_elbow")
    right_lower_len = _median_bone_length(reference_clip, "right_elbow", "right_wrist")
    if min(left_upper_len, left_lower_len, right_upper_len, right_lower_len) <= 1e-6:
        return clip, {"applied": False, "reason": "invalid_arm_lengths"}
    upper_len = (left_upper_len + right_upper_len) * 0.5
    lower_len = (left_lower_len + right_lower_len) * 0.5
    left_hand_len = _median_bone_length(reference_clip, "left_wrist", "left_hand") if "left_hand" in reference_clip.joint_names else 0.0
    right_hand_len = _median_bone_length(reference_clip, "right_wrist", "right_hand") if "right_hand" in reference_clip.joint_names else 0.0
    hand_len = (left_hand_len + right_hand_len) * 0.5 if min(left_hand_len, right_hand_len) > 1e-6 else 0.0

    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame, reference_frame in zip(clip.frames, reference_clip.frames):
        body_frame = _body_local_frame(frame)
        if body_frame is None:
            frames.append(frame)
            continue
        joints = dict(frame.joints)
        reference_joints = reference_frame.joints
        pair_origin = _paired_arm_origin(joints, fallback=body_frame.origin)
        desired_local_targets: dict[str, Point3] = {}
        for left_joint, right_joint in endpoint_pairs:
            if left_joint not in joints or right_joint not in joints:
                continue
            left_local = _to_local(joints[left_joint], body_frame, pair_origin)
            right_local = _to_local(joints[right_joint], body_frame, pair_origin)
            shared = [0.0, 0.0, 0.0]
            for axis in (1, 2):
                shared_value = (left_local[axis] + right_local[axis]) * 0.5
                axis_bounds = shared_axis_bounds.get((left_joint, right_joint), {}).get(axis)
                if axis_bounds is not None:
                    shared_value = min(max(shared_value, axis_bounds[0]), axis_bounds[1])
                shared[axis] = shared_value
            half_width = half_widths.get((left_joint, right_joint))
            if half_width is None:
                continue
            desired_local_targets[left_joint] = (-half_width, shared[1], shared[2])
            desired_local_targets[right_joint] = (half_width, shared[1], shared[2])

        left_elbow_local = _to_local(joints["left_elbow"], body_frame, pair_origin)
        right_elbow_local = _to_local(joints["right_elbow"], body_frame, pair_origin)
        elbow_hint = [0.0, 0.0, 0.0]
        for axis in (1, 2):
            elbow_value = (left_elbow_local[axis] + right_elbow_local[axis]) * 0.5
            axis_bounds = elbow_axis_bounds.get(axis)
            if axis_bounds is not None:
                elbow_value = min(max(elbow_value, axis_bounds[0]), axis_bounds[1])
            elbow_hint[axis] = elbow_value

        arm_targets = _solve_symmetric_same_phase_arm_pair(
            joints,
            body_frame,
            pair_origin=pair_origin,
            desired_local_targets=desired_local_targets,
            elbow_hint=(elbow_hint[0], elbow_hint[1], elbow_hint[2]),
            elbow_half_width=elbow_half_width,
            upper_len=upper_len,
            lower_len=lower_len,
            hand_len=hand_len,
            wrist_reach=_average_reference_wrist_reach(reference_joints),
        )
        for joint_name, target in arm_targets.items():
            displacement = _distance(joints[joint_name], target)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[joint_name] = target
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    return replace(clip, frames=frames), {
        "applied": True,
        "groups": ["arms"],
        "endpointPairs": [f"{left}:{right}" for left, right in endpoint_pairs],
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "target": "same_phase_paired_hand_plane_path_preservation",
        "movingBodyLocalAxis": "up_forward_plane",
        "fixedBodyLocalAxis": None,
        "armOrigin": "shoulder_center",
        "elbowSymmetry": "body_local_same_phase_mirrored_two_bone_solution",
        "boneLengthMode": "shared_reference_upper_lower_hand_lengths",
    }


def _paired_arm_origin(joints: dict[str, Point3], *, fallback: Point3) -> Point3:
    if "left_shoulder" in joints and "right_shoulder" in joints:
        return _average_points([joints["left_shoulder"], joints["right_shoulder"]])
    return fallback


def _solve_symmetric_same_phase_arm_pair(
    joints: dict[str, Point3],
    body_frame: BodyFrame,
    *,
    pair_origin: Point3,
    desired_local_targets: dict[str, Point3],
    elbow_hint: Point3,
    elbow_half_width: float,
    upper_len: float,
    lower_len: float,
    hand_len: float,
    wrist_reach: float | None,
) -> dict[str, Point3]:
    required = (
        "left_shoulder",
        "right_shoulder",
        "left_elbow",
        "right_elbow",
        "left_wrist",
        "right_wrist",
    )
    if any(joint_name not in joints for joint_name in required):
        return {}
    left_shoulder_local = _to_local(joints["left_shoulder"], body_frame, pair_origin)
    left_wrist_target = desired_local_targets.get("left_wrist")
    right_wrist_target = desired_local_targets.get("right_wrist")
    if left_wrist_target is None or right_wrist_target is None:
        return {}
    if wrist_reach is not None and wrist_reach > 1e-6:
        target_direction = _normalize(_subtract(left_wrist_target, left_shoulder_local))
        if target_direction is not None:
            max_reach = max(1e-6, upper_len + lower_len - 1e-5)
            min_reach = max(0.0, abs(upper_len - lower_len) + 1e-5)
            target_reach = min(max(wrist_reach, min_reach), max_reach)
            left_wrist_target = _add(left_shoulder_local, _scale(target_direction, target_reach))
            right_wrist_target = (-left_wrist_target[0], left_wrist_target[1], left_wrist_target[2])

    left_elbow_local, left_wrist_local = _solve_two_bone_local(
        root=left_shoulder_local,
        current_mid=(-elbow_half_width, elbow_hint[1], elbow_hint[2]),
        target_end=left_wrist_target,
        upper_len=upper_len,
        lower_len=lower_len,
        fallback_axis=(0.0, 0.0, 1.0),
    )
    right_elbow_local = (-left_elbow_local[0], left_elbow_local[1], left_elbow_local[2])
    right_wrist_local = (-left_wrist_local[0], left_wrist_local[1], left_wrist_local[2])
    targets = {
        "left_elbow": _from_local(left_elbow_local, body_frame, pair_origin),
        "right_elbow": _from_local(right_elbow_local, body_frame, pair_origin),
        "left_wrist": _from_local(left_wrist_local, body_frame, pair_origin),
        "right_wrist": _from_local(right_wrist_local, body_frame, pair_origin),
    }
    if hand_len > 1e-6 and "left_hand" in joints and "right_hand" in joints:
        left_hand_target = desired_local_targets.get("left_hand")
        if left_hand_target is not None:
            left_hand_local = _place_hand_from_wrist_local(
                wrist=left_wrist_local,
                desired_hand=left_hand_target,
                fallback_direction=_subtract(left_wrist_local, left_elbow_local),
                hand_len=hand_len,
            )
            right_hand_local = (-left_hand_local[0], left_hand_local[1], left_hand_local[2])
            targets["left_hand"] = _from_local(left_hand_local, body_frame, pair_origin)
            targets["right_hand"] = _from_local(right_hand_local, body_frame, pair_origin)
    return targets


def _average_reference_wrist_reach(joints: dict[str, Point3]) -> float | None:
    reaches: list[float] = []
    for side in ("left", "right"):
        shoulder = joints.get(f"{side}_shoulder")
        wrist = joints.get(f"{side}_wrist")
        if shoulder is not None and wrist is not None:
            reaches.append(_distance(shoulder, wrist))
    return sum(reaches) / len(reaches) if reaches else None


def _solve_two_bone_local(
    *,
    root: Point3,
    current_mid: Point3,
    target_end: Point3,
    upper_len: float,
    lower_len: float,
    fallback_axis: Point3,
) -> tuple[Point3, Point3]:
    return _solve_two_bone(
        root=root,
        current_mid=current_mid,
        target_end=target_end,
        upper_len=upper_len,
        lower_len=lower_len,
        fallback_axis=fallback_axis,
    )


def _place_hand_from_wrist_local(
    *,
    wrist: Point3,
    desired_hand: Point3,
    fallback_direction: Point3,
    hand_len: float,
) -> Point3:
    direction = _normalize(_subtract(desired_hand, wrist))
    if direction is None:
        direction = _normalize(fallback_direction)
    if direction is None:
        direction = (0.0, 0.0, 1.0)
    return _add(wrist, _scale(direction, hand_len))


def _paired_endpoint_path_constraints(
    clip: MotionClip,
    endpoint_pairs: list[tuple[str, str]],
) -> dict[str, object] | None:
    half_width_values: dict[tuple[str, str], list[float]] = {pair: [] for pair in endpoint_pairs}
    fixed_axis_values: dict[tuple[str, str], dict[int, list[float]]] = {
        pair: {1: [], 2: []}
        for pair in endpoint_pairs
    }
    shared_axis_values: dict[int, list[float]] = {1: [], 2: []}
    elbow_axis_values: dict[int, list[float]] = {1: [], 2: []}
    elbow_half_width_values: list[float] = []
    for frame in clip.frames:
        body_frame = _body_local_frame(frame)
        if body_frame is None:
            continue
        pair_origin = _paired_arm_origin(frame.joints, fallback=body_frame.origin)
        for left_joint, right_joint in endpoint_pairs:
            if left_joint not in frame.joints or right_joint not in frame.joints:
                continue
            left_local = _to_local(frame.joints[left_joint], body_frame, pair_origin)
            right_local = _to_local(frame.joints[right_joint], body_frame, pair_origin)
            shared_y = (left_local[1] + right_local[1]) * 0.5
            shared_z = (left_local[2] + right_local[2]) * 0.5
            half_width_values[(left_joint, right_joint)].append((abs(left_local[0]) + abs(right_local[0])) * 0.5)
            fixed_axis_values[(left_joint, right_joint)][1].append(shared_y)
            fixed_axis_values[(left_joint, right_joint)][2].append(shared_z)
            shared_axis_values[1].append(shared_y)
            shared_axis_values[2].append(shared_z)
        if "left_elbow" in frame.joints and "right_elbow" in frame.joints:
            left_elbow = _to_local(frame.joints["left_elbow"], body_frame, pair_origin)
            right_elbow = _to_local(frame.joints["right_elbow"], body_frame, pair_origin)
            elbow_axis_values[1].append((left_elbow[1] + right_elbow[1]) * 0.5)
            elbow_axis_values[2].append((left_elbow[2] + right_elbow[2]) * 0.5)
            elbow_half_width_values.append((abs(left_elbow[0]) + abs(right_elbow[0])) * 0.5)
    half_widths = {
        pair: median(pair_values)
        for pair, pair_values in half_width_values.items()
        if pair_values
    }
    if not half_widths:
        return None
    axis_ranges = {
        axis: _value_range(values)
        for axis, values in shared_axis_values.items()
        if values
    }
    moving_axis = max(axis_ranges, key=lambda axis: axis_ranges[axis]) if axis_ranges else 2
    fixed_axis = 1 if moving_axis == 2 else 2
    fixed_values = {
        pair: median(axis_values[fixed_axis])
        for pair, axis_values in fixed_axis_values.items()
        if axis_values[fixed_axis]
    }
    shared_axis_bounds = {
        pair: {
            axis: _central_value_bounds(axis_values[axis], lower=0.01, upper=0.99)
            for axis in (1, 2)
            if axis_values[axis]
        }
        for pair, axis_values in fixed_axis_values.items()
    }
    elbow_axis_bounds = {
        axis: _central_value_bounds(elbow_axis_values[axis], lower=0.01, upper=0.99)
        for axis in (1, 2)
        if elbow_axis_values[axis]
    }
    return {
        "half_widths": half_widths,
        "moving_axis": moving_axis,
        "shared_axis_bounds": shared_axis_bounds,
        "fixed_values": fixed_values,
        "elbow_axis_bounds": elbow_axis_bounds,
        "elbow_fixed_value": median(elbow_axis_values[fixed_axis]) if elbow_axis_values[fixed_axis] else 0.0,
        "elbow_half_width": median(elbow_half_width_values) if elbow_half_width_values else 0.0,
    }


def _central_value_bounds(values: list[float], *, lower: float, upper: float) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    sorted_values = sorted(values)
    lower_index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * lower)))
    upper_index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * upper)))
    return sorted_values[lower_index], sorted_values[upper_index]


def _same_phase_bilateral_group_for_chain(root_joint: str, bilateral_modes: dict[str, dict[str, object]]) -> str | None:
    if "shoulder" in root_joint and bilateral_modes.get("arms", {}).get("mode") == "same_phase_symmetric":
        return "arms"
    if "hip" in root_joint and bilateral_modes.get("legs", {}).get("mode") == "same_phase_symmetric":
        return "legs"
    return None


def _opposite_chain_joints(root_joint: str, mid_joint: str, end_joint: str) -> tuple[str, str, str]:
    if root_joint.startswith("left_"):
        return (
            root_joint.replace("left_", "right_", 1),
            mid_joint.replace("left_", "right_", 1),
            end_joint.replace("left_", "right_", 1),
        )
    if root_joint.startswith("right_"):
        return (
            root_joint.replace("right_", "left_", 1),
            mid_joint.replace("right_", "left_", 1),
            end_joint.replace("right_", "left_", 1),
        )
    return root_joint, mid_joint, end_joint


def _stabilize_whole_body_rigid_root(
    clip: MotionClip,
    *,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    anchor_joints = [
        joint
        for joint in (
            "pelvis",
            "left_hip",
            "right_hip",
            "spine1",
            "spine2",
            "spine3",
            "left_shoulder",
            "right_shoulder",
        )
        if joint in clip.joint_names
    ]
    if not anchor_joints:
        return clip, {"applied": False, "reason": "missing_anchor_joints"}
    anchors = [_average_points([frame.joints[joint] for joint in anchor_joints if joint in frame.joints]) for frame in clip.frames]
    stable_anchor = _median_point(anchors)
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    horizontal_only = "torso" not in dominant_groups
    max_horizontal_correction = 0.035
    max_vertical_correction = 0.018
    frames: list[MotionFrame] = []
    total_correction = 0.0
    max_correction = 0.0
    for frame, anchor in zip(clip.frames, anchors):
        correction = _subtract(anchor, stable_anchor)
        correction = (
            _clamp_scalar(correction[0], max_horizontal_correction),
            0.0 if horizontal_only else _clamp_scalar(correction[1], max_vertical_correction),
            _clamp_scalar(correction[2], max_horizontal_correction),
        )
        magnitude = _length(correction)
        total_correction += magnitude
        max_correction = max(max_correction, magnitude)
        joints = {
            joint_name: _subtract(point, correction)
            for joint_name, point in frame.joints.items()
        }
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": True,
        "anchorJoints": anchor_joints,
        "horizontalOnly": horizontal_only,
        "stableAnchor": [float(value) for value in stable_anchor],
        "averageCorrection": total_correction / len(frames) if frames else 0.0,
        "maxCorrection": max_correction,
        "maxHorizontalCorrection": max_horizontal_correction,
        "maxVerticalCorrection": 0.0 if horizontal_only else max_vertical_correction,
    }


def _joint_group_motion(clip: MotionClip, joint_names: list[str]) -> float:
    available = [joint for joint in joint_names if joint in clip.joint_names]
    if not available or clip.frame_count < 2:
        return 0.0
    total = 0.0
    samples = 0
    for frame_index in range(1, clip.frame_count):
        previous = clip.frames[frame_index - 1].joints
        current = clip.frames[frame_index].joints
        for joint in available:
            total += _distance(previous[joint], current[joint])
            samples += 1
    return total / samples if samples else 0.0


def _suppress_low_magnitude_motion(
    clip: MotionClip,
    *,
    active_threshold: float,
    strongest_chain_motion: float,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    joint_motion = {
        joint_name: _joint_group_motion(clip, [joint_name])
        for joint_name in clip.joint_names
    }
    non_dominant_threshold = max(active_threshold, strongest_chain_motion * NON_DOMINANT_CHAIN_RATIO)
    smoothable = {
        joint_name
        for joint_name, motion in joint_motion.items()
        if _should_suppress_joint_motion(
            joint_name,
            motion,
            active_threshold=active_threshold,
            non_dominant_threshold=non_dominant_threshold,
            dominant_profile=dominant_profile,
        )
    }
    smoothable -= _protected_dominant_chain_anchor_joints(dominant_profile)
    smoothable -= _never_suppress_anchor_joints()
    if not smoothable:
        return clip, {"applied": False, "reason": "no_low_magnitude_joints"}

    reference_offsets = _stable_joint_reference_offsets(clip, smoothable)
    reference_positions = _stable_joint_reference_positions(clip, smoothable)
    dominant_groups = set(dominant_profile.get("dominantGroups", []))

    frames: list[MotionFrame] = []
    for frame_index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        for joint_name in smoothable:
            points = [
                clip.frames[index].joints[joint_name]
                for index in range(max(0, frame_index - 2), min(clip.frame_count, frame_index + 3))
            ]
            averaged = _average_points(points)
            blend = _low_motion_suppression_blend(joint_motion[joint_name], active_threshold)
            stabilized = averaged
            joint_group = _joint_motion_group(joint_name)
            if joint_group is not None and joint_group not in dominant_groups and joint_name in reference_positions:
                stabilized = reference_positions[joint_name]
                blend = max(blend, 0.72)
            root_joint = _root_joint_for_stabilization(clip)
            if (
                (joint_group is None or joint_group in dominant_groups)
                and root_joint is not None
                and joint_name in reference_offsets
                and root_joint in frame.joints
            ):
                stabilized = _add(frame.joints[root_joint], reference_offsets[joint_name])
            joints[joint_name] = _limited_lerp_point(
                frame.joints[joint_name],
                stabilized,
                blend,
                MAX_SUPPRESSION_CORRECTION_METERS,
            )
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    refined = replace(clip, frames=frames)
    displacement = _average_joint_displacement(clip, refined, list(smoothable))
    return refined, {
        "applied": True,
        "suppressedJoints": sorted(smoothable),
        "jointMotion": joint_motion,
        "activeThreshold": active_threshold,
        "nonDominantThreshold": non_dominant_threshold,
        "averageDisplacement": displacement["average"],
        "maxDisplacement": displacement["max"],
    }


def _dominant_motion_profile(
    chain_motion: dict[str, float],
    strongest_chain_motion: float,
    *,
    chain_range: dict[str, float],
    body_height: float,
    active_threshold: float,
    dominant_chain_ratio: float,
) -> dict[str, object]:
    if strongest_chain_motion <= 1e-8:
        return {
            "dominantGroups": [],
            "groupMotion": {},
            "groupRange": chain_range,
            "rangeDominantGroups": [],
        }
    group_motion = {
        "torso": max(chain_motion.get("torso", 0.0), chain_motion.get("head", 0.0)),
        "arms": max(chain_motion.get("leftArm", 0.0), chain_motion.get("rightArm", 0.0)),
        "legs": max(chain_motion.get("leftLeg", 0.0), chain_motion.get("rightLeg", 0.0)),
    }
    motion_dominant_groups = {
        group_name
        for group_name, motion in group_motion.items()
        if (
            (motion >= active_threshold or motion >= strongest_chain_motion - 1e-9)
            and motion >= strongest_chain_motion * dominant_chain_ratio
        )
    }
    strongest_chain_range = max(chain_range.values(), default=0.0)
    range_threshold = max(
        DOMINANT_CHAIN_MIN_TOTAL_RANGE_METERS,
        body_height * DOMINANT_CHAIN_MIN_TOTAL_RANGE_BODY_RATIO if body_height > 1e-6 else 0.0,
        strongest_chain_range * DOMINANT_CHAIN_TOTAL_RANGE_RATIO,
    )
    range_dominant_groups = {
        group_name
        for group_name, total_range in chain_range.items()
        if total_range >= range_threshold
    }
    if (
        "arms" in motion_dominant_groups
        and "torso" not in motion_dominant_groups
        and group_motion["torso"] < active_threshold
        and chain_range.get("torso", 0.0) < chain_range.get("arms", 0.0) * 0.75
    ):
        range_dominant_groups.discard("torso")
    dominant_groups = sorted(motion_dominant_groups | range_dominant_groups)
    return {
        "dominantGroups": dominant_groups,
        "groupMotion": group_motion,
        "motionDominantGroups": sorted(motion_dominant_groups),
        "groupRange": chain_range,
        "rangeDominantGroups": sorted(range_dominant_groups),
        "rangeDominanceThreshold": range_threshold,
    }


def _should_suppress_joint_motion(
    joint_name: str,
    joint_motion: float,
    *,
    active_threshold: float,
    non_dominant_threshold: float,
    dominant_profile: dict[str, object],
) -> bool:
    if joint_motion <= active_threshold:
        return True
    joint_group = _joint_motion_group(joint_name)
    if joint_group is None:
        return False
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    if joint_group not in dominant_groups and joint_motion <= non_dominant_threshold:
        return True
    return False


def _joint_motion_group(joint_name: str) -> str | None:
    if joint_name.startswith("left_elbow") or joint_name.startswith("right_elbow"):
        return "arms"
    if joint_name.startswith("left_wrist") or joint_name.startswith("right_wrist"):
        return "arms"
    if joint_name.startswith("left_hand") or joint_name.startswith("right_hand"):
        return "arms"
    if joint_name.startswith("left_knee") or joint_name.startswith("right_knee"):
        return "legs"
    if joint_name.startswith("left_ankle") or joint_name.startswith("right_ankle"):
        return "legs"
    if joint_name.startswith("left_foot") or joint_name.startswith("right_foot"):
        return "legs"
    if joint_name in TORSO_STABILITY_JOINTS or joint_name in ("pelvis", "left_hip", "right_hip"):
        return "torso"
    return None


def _protected_dominant_chain_anchor_joints(dominant_profile: dict[str, object]) -> set[str]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    protected: set[str] = set()
    if "arms" in dominant_groups:
        protected.update((
            "neck",
            "left_collar",
            "right_collar",
            "left_shoulder",
            "right_shoulder",
        ))
    if "legs" in dominant_groups:
        protected.update((
            "pelvis",
            "left_hip",
            "right_hip",
        ))
    return protected


def _never_suppress_anchor_joints() -> set[str]:
    return {
        "pelvis",
        "left_hip",
        "right_hip",
        "spine1",
        "spine2",
        "spine3",
    }


def _build_stabilized_ik_target_clip(
    clip: MotionClip,
    *,
    active_threshold: float,
    strongest_chain_motion: float,
    dominant_profile: dict[str, object],
    non_dominant_damping: float,
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    non_dominant_threshold = max(active_threshold, strongest_chain_motion * NON_DOMINANT_CHAIN_RATIO)
    joint_motion = {
        joint_name: _joint_group_motion(clip, [joint_name])
        for joint_name in clip.joint_names
    }
    target_joints = [
        joint_name
        for joint_name, motion in joint_motion.items()
        if _should_stabilize_ik_target_joint(
            joint_name,
            motion,
            active_threshold=active_threshold,
            non_dominant_threshold=non_dominant_threshold,
            dominant_groups=dominant_groups,
        )
    ]
    stable_pose_joints = [
        joint_name
        for joint_name in clip.joint_names
        if _should_silence_to_stable_pose(joint_name, dominant_groups)
    ]
    if not target_joints:
        return clip, {"applied": False, "reason": "no_target_joints"}

    stable_pose = {
        joint_name: _median_point([
            frame.joints[joint_name]
            for frame in clip.frames
            if joint_name in frame.joints
        ])
        for joint_name in stable_pose_joints
    }
    stable_offsets = _stable_parent_offsets(clip, stable_pose_joints)
    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame_index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        start_index = max(0, frame_index - 3)
        end_index = min(clip.frame_count, frame_index + 4)
        for joint_name in target_joints:
            parent_joint = _parent_joint(joint_name)
            if joint_name in stable_offsets and parent_joint in joints:
                target = _add(joints[parent_joint], stable_offsets[joint_name])
                max_distance = _stable_pose_silencing_radius(joint_name)
            elif joint_name in stable_pose:
                target = stable_pose[joint_name]
                max_distance = _stable_pose_silencing_radius(joint_name)
            else:
                points = [
                    clip.frames[index].joints[joint_name]
                    for index in range(start_index, end_index)
                    if joint_name in clip.frames[index].joints
                ]
                if len(points) < 3:
                    continue
                target = _median_point(points)
                max_distance = _ik_target_smoothing_radius(joint_name)
            damping_alpha = 0.35 + non_dominant_damping * 0.60
            updated = _limited_lerp_point(frame.joints[joint_name], target, damping_alpha, max_distance)
            displacement = _distance(frame.joints[joint_name], updated)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[joint_name] = updated
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    return replace(clip, frames=frames), {
        "applied": True,
        "target": "temporally_stabilized_ik_target_derived_from_original",
        "targetJoints": sorted(target_joints),
        "stablePoseJoints": sorted(stable_pose_joints),
        "averageTargetDisplacement": total_displacement / samples if samples else 0.0,
        "maxTargetDisplacement": max_displacement,
        "windowFrames": 7,
        "dampingAlpha": 0.35 + non_dominant_damping * 0.60,
    }


def _should_stabilize_ik_target_joint(
    joint_name: str,
    joint_motion: float,
    *,
    active_threshold: float,
    non_dominant_threshold: float,
    dominant_groups: set[str],
) -> bool:
    joint_group = _joint_motion_group(joint_name)
    if joint_group in dominant_groups:
        return False
    if joint_name in _protected_dominant_chain_anchor_joints({"dominantGroups": list(dominant_groups)}):
        return False
    if joint_name in _never_suppress_anchor_joints() or joint_name in ("left_hip", "right_hip"):
        return False
    if joint_name in ("head", "neck"):
        return False
    if joint_name in TORSO_STABILITY_JOINTS and joint_name != "head":
        return False
    return joint_motion <= non_dominant_threshold


def _should_silence_to_stable_pose(joint_name: str, dominant_groups: set[str]) -> bool:
    joint_group = _joint_motion_group(joint_name)
    if joint_group is None or joint_group in dominant_groups:
        return False
    if joint_name in _protected_dominant_chain_anchor_joints({"dominantGroups": list(dominant_groups)}):
        return False
    if joint_name in _never_suppress_anchor_joints() or joint_name in ("left_hip", "right_hip"):
        return False
    if joint_name in ("head", "neck"):
        return False
    if joint_name in TORSO_STABILITY_JOINTS and joint_name != "head":
        return False
    return True


def _ik_target_smoothing_radius(joint_name: str) -> float:
    if joint_name in TORSO_STABILITY_JOINTS or joint_name in _never_suppress_anchor_joints():
        return 0.055
    return 0.05


def _stable_pose_silencing_radius(joint_name: str) -> float:
    if joint_name in _never_suppress_anchor_joints() or joint_name in TORSO_STABILITY_JOINTS:
        return 0.035
    return 0.085


def _stable_parent_offsets(clip: MotionClip, joint_names: list[str]) -> dict[str, Point3]:
    offsets: dict[str, Point3] = {}
    for joint_name in joint_names:
        parent_joint = _parent_joint(joint_name)
        if not parent_joint or parent_joint not in clip.joint_names:
            continue
        offsets[joint_name] = _median_point([
            _subtract(frame.joints[joint_name], frame.joints[parent_joint])
            for frame in clip.frames
            if joint_name in frame.joints and parent_joint in frame.joints
        ])
    return offsets


def _parent_joint(joint_name: str) -> str:
    parents = {
        "head": "neck",
        "neck": "spine3",
        "spine3": "spine2",
        "spine2": "spine1",
        "spine1": "pelvis",
        "left_collar": "neck",
        "right_collar": "neck",
        "left_shoulder": "left_collar",
        "right_shoulder": "right_collar",
        "left_elbow": "left_shoulder",
        "right_elbow": "right_shoulder",
        "left_wrist": "left_elbow",
        "right_wrist": "right_elbow",
        "left_hand": "left_wrist",
        "right_hand": "right_wrist",
        "left_hip": "pelvis",
        "right_hip": "pelvis",
        "left_knee": "left_hip",
        "right_knee": "right_hip",
        "left_ankle": "left_knee",
        "right_ankle": "right_knee",
        "left_foot": "left_ankle",
        "right_foot": "right_ankle",
    }
    return parents.get(joint_name, "")


def _stable_joint_reference_offsets(
    clip: MotionClip,
    joint_names: set[str],
) -> dict[str, Point3]:
    root_joint = _root_joint_for_stabilization(clip)
    if root_joint is None:
        return {}
    offsets: dict[str, Point3] = {}
    for joint_name in joint_names:
        if joint_name == root_joint:
            continue
        offsets[joint_name] = _median_point([
            _subtract(frame.joints[joint_name], frame.joints[root_joint])
            for frame in clip.frames
            if joint_name in frame.joints and root_joint in frame.joints
        ])
    return offsets


def _stable_joint_reference_positions(
    clip: MotionClip,
    joint_names: set[str],
) -> dict[str, Point3]:
    return {
        joint_name: _median_point([
            frame.joints[joint_name]
            for frame in clip.frames
            if joint_name in frame.joints
        ])
        for joint_name in joint_names
    }


def _root_joint_for_stabilization(clip: MotionClip) -> str | None:
    for candidate in ("pelvis", "hips", "root"):
        if candidate in clip.joint_names:
            return candidate
    return None


def _low_motion_suppression_blend(joint_motion: float, active_threshold: float) -> float:
    if active_threshold <= 1e-8:
        return 0.0
    ratio = min(max(joint_motion / active_threshold, 0.0), 1.0)
    return 0.85 - ratio * 0.45


def _stabilize_low_motion_torso(
    clip: MotionClip,
    *,
    active_threshold: float,
    protected_joints: set[str],
) -> tuple[MotionClip, dict[str, object]]:
    pelvis = "pelvis" if "pelvis" in clip.joint_names else None
    if pelvis is None:
        return clip, {"applied": False, "reason": "missing_pelvis"}

    torso_joints = [
        joint
        for joint in TORSO_STABILITY_JOINTS
        if joint in clip.joint_names and joint not in protected_joints
    ]
    if not torso_joints:
        return clip, {"applied": False, "reason": "missing_torso_joints"}

    torso_motion = _joint_group_motion(clip, torso_joints)
    if torso_motion > active_threshold * 1.75:
        return clip, {
            "applied": False,
            "reason": "torso_motion_active",
            "motion": torso_motion,
        }

    reference_offsets = {
        joint: _median_point([
            _subtract(frame.joints[joint], frame.joints[pelvis])
            for frame in clip.frames
        ])
        for joint in torso_joints
    }
    frames: list[MotionFrame] = []
    for frame in clip.frames:
        joints = dict(frame.joints)
        root = frame.joints[pelvis]
        for joint, offset in reference_offsets.items():
            target = _add(root, offset)
            joints[joint] = _limited_lerp_point(joints[joint], target, 0.45, MAX_TORSO_CORRECTION_METERS)
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": True,
        "motion": torso_motion,
        "blend": 0.45,
        "maxCorrection": MAX_TORSO_CORRECTION_METERS,
    }


def _refine_bilateral_chain_symmetry(
    clip: MotionClip,
    *,
    left_root: str,
    right_root: str,
    left_mid: str,
    right_mid: str,
    left_end: str,
    right_end: str,
    extra_pairs: tuple[tuple[str, str], ...],
    chain_name: str,
    active_threshold: float,
) -> tuple[MotionClip, dict[str, object]]:
    required = (left_root, right_root, left_mid, right_mid, left_end, right_end)
    if any(joint not in clip.joint_names for joint in required):
        return clip, {"applied": False, "reason": "missing_joints"}

    left_motion = _joint_group_motion(clip, [left_mid, left_end, *[pair[0] for pair in extra_pairs]])
    right_motion = _joint_group_motion(clip, [right_mid, right_end, *[pair[1] for pair in extra_pairs]])
    max_motion = max(left_motion, right_motion)
    min_motion = min(left_motion, right_motion)
    if max_motion < active_threshold:
        return clip, {
            "applied": False,
            "reason": "weak_motion",
            "leftMotion": left_motion,
            "rightMotion": right_motion,
        }
    if min_motion / max(max_motion, 1e-8) < SYMMETRY_MIN_RATIO:
        return clip, {
            "applied": False,
            "reason": "unilateral_or_unbalanced",
            "leftMotion": left_motion,
            "rightMotion": right_motion,
        }

    correlation = _mirrored_chain_motion_correlation(clip, left_end=left_end, right_end=right_end)
    if correlation < SYMMETRY_MIN_CORRELATION:
        return clip, {
            "applied": False,
            "reason": "alternating_or_uncorrelated",
            "leftMotion": left_motion,
            "rightMotion": right_motion,
            "correlation": correlation,
        }

    blend = min(0.46, max(0.18, correlation * 0.38))
    left_upper_len = _median_bone_length(clip, left_root, left_mid)
    left_lower_len = _median_bone_length(clip, left_mid, left_end)
    right_upper_len = _median_bone_length(clip, right_root, right_mid)
    right_lower_len = _median_bone_length(clip, right_mid, right_end)

    frames: list[MotionFrame] = []
    for frame in clip.frames:
        body_frame = _body_local_frame(frame)
        if body_frame is None:
            frames.append(frame)
            continue
        joints = dict(frame.joints)
        symmetric_targets = _symmetric_pair_targets(
            frame,
            body_frame=body_frame,
            pairs=((left_mid, right_mid), (left_end, right_end), *extra_pairs),
        )
        left_target = symmetric_targets[left_end]
        right_target = symmetric_targets[right_end]
        solved_left_mid, solved_left_end = _solve_two_bone(
            root=joints[left_root],
            current_mid=joints[left_mid],
            target_end=left_target,
            upper_len=left_upper_len,
            lower_len=left_lower_len,
            fallback_axis=body_frame.forward,
        )
        solved_right_mid, solved_right_end = _solve_two_bone(
            root=joints[right_root],
            current_mid=joints[right_mid],
            target_end=right_target,
            upper_len=right_upper_len,
            lower_len=right_lower_len,
            fallback_axis=body_frame.forward,
        )
        joints[left_mid] = _lerp_point(joints[left_mid], solved_left_mid, blend)
        joints[left_end] = _lerp_point(joints[left_end], solved_left_end, blend)
        joints[right_mid] = _lerp_point(joints[right_mid], solved_right_mid, blend)
        joints[right_end] = _lerp_point(joints[right_end], solved_right_end, blend)
        for left_extra, right_extra in extra_pairs:
            if left_extra not in joints or right_extra not in joints:
                continue
            joints[left_extra] = _lerp_point(joints[left_extra], symmetric_targets[left_extra], blend * 0.90)
            joints[right_extra] = _lerp_point(joints[right_extra], symmetric_targets[right_extra], blend * 0.90)
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    refined_clip = replace(clip, frames=frames)
    displacement = _average_joint_displacement(
        clip,
        refined_clip,
        [left_mid, left_end, right_mid, right_end, *[joint for pair in extra_pairs for joint in pair]],
    )
    return refined_clip, {
        "applied": True,
        "chain": chain_name,
        "leftMotion": left_motion,
        "rightMotion": right_motion,
        "correlation": correlation,
        "blend": blend,
        "averageDisplacement": displacement["average"],
        "maxDisplacement": displacement["max"],
    }


def _average_joint_displacement(
    before: MotionClip,
    after: MotionClip,
    joint_names: list[str],
) -> dict[str, float]:
    total = 0.0
    maximum = 0.0
    count = 0
    for before_frame, after_frame in zip(before.frames, after.frames):
        for joint_name in joint_names:
            if joint_name not in before_frame.joints or joint_name not in after_frame.joints:
                continue
            displacement = _distance(before_frame.joints[joint_name], after_frame.joints[joint_name])
            total += displacement
            maximum = max(maximum, displacement)
            count += 1
    return {
        "average": total / count if count else 0.0,
        "max": maximum,
    }


def _suppress_temporal_spikes(
    clip: MotionClip,
    *,
    active_threshold: float,
) -> tuple[MotionClip, dict[str, object]]:
    if clip.frame_count < 3:
        return clip, {"applied": False, "reason": "too_few_frames"}
    spike_threshold = max(0.055, active_threshold * 3.0)
    frames = [MotionFrame(time_sec=frame.time_sec, joints=dict(frame.joints)) for frame in clip.frames]
    corrections: list[dict[str, object]] = []
    for _ in range(3):
        pass_corrections = 0
        for frame_index in range(1, clip.frame_count - 1):
            previous = frames[frame_index - 1].joints
            current = frames[frame_index].joints
            following = frames[frame_index + 1].joints
            for joint_name in clip.joint_names:
                if joint_name not in previous or joint_name not in current or joint_name not in following:
                    continue
                midpoint = _average_points([previous[joint_name], following[joint_name]])
                deviation = _distance(current[joint_name], midpoint)
                if deviation <= spike_threshold:
                    continue
                current[joint_name] = _lerp_point(current[joint_name], midpoint, 0.86)
                pass_corrections += 1
                corrections.append({
                    "frameIndex": frame_index,
                    "jointName": joint_name,
                    "deviation": deviation,
                })
        if pass_corrections == 0:
            break
    if not corrections:
        return clip, {
            "applied": False,
            "reason": "no_isolated_spikes",
            "threshold": spike_threshold,
        }
    return replace(clip, frames=frames), {
        "applied": True,
        "threshold": spike_threshold,
        "correctionCount": len(corrections),
        "maxDeviation": max(float(item["deviation"]) for item in corrections),
        "correctedJoints": sorted({str(item["jointName"]) for item in corrections}),
    }


def _constrain_to_stabilized_ik_targets(
    clip: MotionClip,
    *,
    stabilized_target_clip: MotionClip,
    dominant_profile: dict[str, object],
    non_dominant_radius_scale: float,
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    frames: list[MotionFrame] = []
    constrained_joints: set[str] = set()
    total_pullback = 0.0
    max_pullback = 0.0
    samples = 0
    for frame, target_frame in zip(clip.frames, stabilized_target_clip.frames):
        joints = dict(frame.joints)
        for joint_name, point in frame.joints.items():
            target = target_frame.joints.get(joint_name)
            if target is None:
                continue
            max_distance = _original_target_radius(
                joint_name,
                dominant_groups,
                non_dominant_radius_scale=non_dominant_radius_scale,
            )
            delta = _subtract(point, target)
            distance = _length(delta)
            if distance <= max_distance or distance <= 1e-8:
                continue
            constrained = _add(target, _scale(delta, max_distance / distance))
            pullback = _distance(point, constrained)
            joints[joint_name] = constrained
            constrained_joints.add(joint_name)
            total_pullback += pullback
            max_pullback = max(max_pullback, pullback)
            samples += 1
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": bool(constrained_joints),
        "target": "stabilized_ik_target_skeleton",
        "constrainedJoints": sorted(constrained_joints),
        "averagePullback": total_pullback / samples if samples else 0.0,
        "maxPullback": max_pullback,
        "radii": {
            "anchor": 0.018,
            "dominant": 0.055,
            "nonDominant": 0.04,
        },
        "nonDominantRadiusScale": non_dominant_radius_scale,
    }


def _original_target_radius(
    joint_name: str,
    dominant_groups: set[str],
    *,
    non_dominant_radius_scale: float,
) -> float:
    if joint_name in _never_suppress_anchor_joints() or joint_name in TORSO_STABILITY_JOINTS:
        return 0.008 * non_dominant_radius_scale
    joint_group = _joint_motion_group(joint_name)
    if joint_group in dominant_groups:
        return 0.025
    return 0.012 * non_dominant_radius_scale


def _straighten_non_dominant_body_frame(
    clip: MotionClip,
    *,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    if "torso" in dominant_groups:
        return clip, {"applied": False, "reason": "torso_is_dominant"}
    required = ("pelvis", "left_hip", "right_hip", "left_shoulder", "right_shoulder")
    if any(joint not in clip.joint_names for joint in required):
        return clip, {"applied": False, "reason": "missing_body_frame_joints"}

    spine_chain = [joint for joint in ("pelvis", "spine1", "spine2", "spine3", "neck") if joint in clip.joint_names]
    if len(spine_chain) < 3:
        return clip, {"applied": False, "reason": "missing_spine_chain"}

    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        joints = dict(frame.joints)
        pelvis = joints["pelvis"]
        spine_top_name = "neck" if "neck" in joints else spine_chain[-1]
        spine_top = joints.get(spine_top_name)
        if spine_top is None:
            frames.append(frame)
            continue
        spine_axis = _normalize(_subtract(spine_top, pelvis))
        if spine_axis is None:
            frames.append(frame)
            continue
        shoulder_axis = _subtract(joints["right_shoulder"], joints["left_shoulder"])
        hip_axis = _subtract(joints["right_hip"], joints["left_hip"])
        shoulder_right = _project_axis_perpendicular_to(shoulder_axis, spine_axis)
        hip_right = _project_axis_perpendicular_to(hip_axis, spine_axis)
        if shoulder_right is None and hip_right is None:
            frames.append(frame)
            continue
        canonical_right = shoulder_right or hip_right
        if shoulder_right is not None and hip_right is not None:
            canonical_right = _normalize(_add(shoulder_right, hip_right)) or shoulder_right
        if canonical_right is None:
            frames.append(frame)
            continue

        replacements: dict[str, Point3] = {}
        for joint_name, distance_from_pelvis in _spine_chain_distances(joints, spine_chain).items():
            replacements[joint_name] = _add(pelvis, _scale(spine_axis, distance_from_pelvis))

        hip_center = _project_center_to_spine_level(
            _average_points([joints["left_hip"], joints["right_hip"]]),
            pelvis,
            spine_axis,
        )
        shoulder_center = _project_center_to_spine_level(
            _average_points([joints["left_shoulder"], joints["right_shoulder"]]),
            pelvis,
            spine_axis,
        )
        hip_half_width = _length(hip_axis) * 0.5
        shoulder_half_width = _length(shoulder_axis) * 0.5
        replacements["left_hip"] = _add(hip_center, _scale(canonical_right, -hip_half_width))
        replacements["right_hip"] = _add(hip_center, _scale(canonical_right, hip_half_width))
        replacements["left_shoulder"] = _add(shoulder_center, _scale(canonical_right, -shoulder_half_width))
        replacements["right_shoulder"] = _add(shoulder_center, _scale(canonical_right, shoulder_half_width))

        for collar_name, shoulder_name in (("left_collar", "left_shoulder"), ("right_collar", "right_shoulder")):
            if collar_name in joints:
                replacements[collar_name] = _add(
                    joints[collar_name],
                    _subtract(replacements[shoulder_name], joints[shoulder_name]),
                )
        if "head" in joints and spine_top_name in replacements:
            head_offset = _dot(_subtract(joints["head"], joints[spine_top_name]), spine_axis)
            replacements["head"] = _add(replacements[spine_top_name], _scale(spine_axis, max(0.0, head_offset)))
        if "legs" not in dominant_groups:
            replacements.update(_straightened_non_dominant_leg_replacements(joints, replacements, canonical_right))

        for joint_name, replacement in replacements.items():
            displacement = _distance(joints[joint_name], replacement)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[joint_name] = replacement
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    return replace(clip, frames=frames), {
        "applied": samples > 0,
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "target": "straight_spine_centerline_parallel_hips_shoulders",
    }


def _spine_chain_distances(joints: dict[str, Point3], spine_chain: list[str]) -> dict[str, float]:
    distances: dict[str, float] = {spine_chain[0]: 0.0}
    running = 0.0
    previous_joint = spine_chain[0]
    for joint_name in spine_chain[1:]:
        if previous_joint in joints and joint_name in joints:
            running += _distance(joints[previous_joint], joints[joint_name])
            distances[joint_name] = running
        previous_joint = joint_name
    return distances


def _project_center_to_spine_level(center: Point3, pelvis: Point3, spine_axis: Point3) -> Point3:
    return _add(pelvis, _scale(spine_axis, _dot(_subtract(center, pelvis), spine_axis)))


def _straightened_non_dominant_leg_replacements(
    joints: dict[str, Point3],
    replacements: dict[str, Point3],
    canonical_right: Point3,
) -> dict[str, Point3]:
    required = ("left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")
    if any(joint not in joints for joint in required):
        return {}
    left_hip = replacements.get("left_hip", joints["left_hip"])
    right_hip = replacements.get("right_hip", joints["right_hip"])
    left_hip_to_knee = _subtract(joints["left_knee"], joints["left_hip"])
    right_hip_to_knee = _subtract(joints["right_knee"], joints["right_hip"])
    left_knee_to_ankle = _subtract(joints["left_ankle"], joints["left_knee"])
    right_knee_to_ankle = _subtract(joints["right_ankle"], joints["right_knee"])
    left_leg_axis = _project_axis_perpendicular_to(left_hip_to_knee, canonical_right)
    right_leg_axis = _project_axis_perpendicular_to(right_hip_to_knee, canonical_right)
    if left_leg_axis is None and right_leg_axis is None:
        return {}
    if left_leg_axis is None:
        leg_axis = right_leg_axis
    elif right_leg_axis is None:
        leg_axis = left_leg_axis
    else:
        leg_axis = _normalize(_add(left_leg_axis, right_leg_axis)) or left_leg_axis
    if leg_axis is None:
        return {}
    if _dot(leg_axis, _add(left_hip_to_knee, right_hip_to_knee)) < 0.0:
        leg_axis = _scale(leg_axis, -1.0)

    left_upper = _length(left_hip_to_knee)
    right_upper = _length(right_hip_to_knee)
    left_lower = _length(left_knee_to_ankle)
    right_lower = _length(right_knee_to_ankle)
    left_knee = _add(left_hip, _scale(leg_axis, left_upper))
    right_knee = _add(right_hip, _scale(leg_axis, right_upper))
    left_ankle = _add(left_knee, _scale(leg_axis, left_lower))
    right_ankle = _add(right_knee, _scale(leg_axis, right_lower))
    leg_replacements = {
        "left_knee": left_knee,
        "right_knee": right_knee,
        "left_ankle": left_ankle,
        "right_ankle": right_ankle,
    }
    for side, ankle in (("left", left_ankle), ("right", right_ankle)):
        foot_name = f"{side}_foot"
        ankle_name = f"{side}_ankle"
        if foot_name in joints and ankle_name in joints:
            leg_replacements[foot_name] = _add(ankle, _subtract(joints[foot_name], joints[ankle_name]))
    return leg_replacements


def _untwist_non_dominant_torso(
    clip: MotionClip,
    *,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    if "torso" in dominant_groups:
        return clip, {"applied": False, "reason": "torso_is_dominant"}
    required = ("pelvis", "left_shoulder", "right_shoulder", "left_hip", "right_hip")
    if any(joint not in clip.joint_names for joint in required):
        return clip, {"applied": False, "reason": "missing_torso_joints"}

    frames: list[MotionFrame] = []
    corrections = 0
    total_twist_before = 0.0
    total_twist_after = 0.0
    max_displacement = 0.0
    for frame in clip.frames:
        joints = dict(frame.joints)
        spine_top = joints.get("neck") or joints.get("spine3") or joints.get("head")
        if spine_top is None:
            frames.append(frame)
            continue
        spine_axis = _normalize(_subtract(spine_top, joints["pelvis"]))
        if spine_axis is None:
            frames.append(frame)
            continue
        shoulder_axis = _subtract(joints["right_shoulder"], joints["left_shoulder"])
        hip_axis = _subtract(joints["right_hip"], joints["left_hip"])
        raw_twist_before = _axis_angle_degrees(shoulder_axis, hip_axis)
        shoulder_right = _project_axis_perpendicular_to(shoulder_axis, spine_axis)
        hip_right = _project_axis_perpendicular_to(hip_axis, spine_axis)
        if shoulder_right is None or hip_right is None:
            frames.append(frame)
            continue
        twist_before = _axis_angle_degrees(shoulder_right, hip_right)
        if raw_twist_before <= 1.0 and twist_before <= 1.0:
            frames.append(frame)
            continue

        canonical_right = _normalize(_add(shoulder_right, hip_right))
        if canonical_right is None:
            canonical_right = shoulder_right
        shoulder_center = _average_points([joints["left_shoulder"], joints["right_shoulder"]])
        hip_center = _average_points([joints["left_hip"], joints["right_hip"]])
        shoulder_half_width = _length(shoulder_axis) * 0.5
        hip_half_width = _length(hip_axis) * 0.5
        replacements = {
            "left_shoulder": _add(shoulder_center, _scale(canonical_right, -shoulder_half_width)),
            "right_shoulder": _add(shoulder_center, _scale(canonical_right, shoulder_half_width)),
            "left_hip": _add(hip_center, _scale(canonical_right, -hip_half_width)),
            "right_hip": _add(hip_center, _scale(canonical_right, hip_half_width)),
        }
        for collar_name, shoulder_name in (("left_collar", "left_shoulder"), ("right_collar", "right_shoulder")):
            if collar_name in joints:
                replacements[collar_name] = _add(
                    joints[collar_name],
                    _subtract(replacements[shoulder_name], joints[shoulder_name]),
                )
        for joint_name, replacement in replacements.items():
            displacement = _distance(joints[joint_name], replacement)
            max_displacement = max(max_displacement, displacement)
            joints[joint_name] = replacement

        corrected_shoulder_right = _project_axis_perpendicular_to(
            _subtract(joints["right_shoulder"], joints["left_shoulder"]),
            spine_axis,
        )
        corrected_hip_right = _project_axis_perpendicular_to(
            _subtract(joints["right_hip"], joints["left_hip"]),
            spine_axis,
        )
        twist_after = (
            _axis_angle_degrees(corrected_shoulder_right, corrected_hip_right)
            if corrected_shoulder_right is not None and corrected_hip_right is not None
            else twist_before
        )
        total_twist_before += raw_twist_before
        total_twist_after += twist_after
        corrections += 1
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    if corrections == 0:
        return clip, {"applied": False, "reason": "no_torso_twist_to_correct"}
    return replace(clip, frames=frames), {
        "applied": True,
        "correctedFrames": corrections,
        "averageTwistBeforeDegrees": total_twist_before / corrections,
        "averageTwistAfterDegrees": total_twist_after / corrections,
        "maxDisplacement": max_displacement,
        "target": "align_shoulder_and_hip_lateral_axes_around_spine",
    }


def _project_axis_perpendicular_to(axis: Point3, normal: Point3) -> Point3 | None:
    projected = _subtract(axis, _scale(normal, _dot(axis, normal)))
    return _normalize(projected)


def _axis_angle_degrees(left: Point3, right: Point3) -> float:
    left_normalized = _normalize(left)
    right_normalized = _normalize(right)
    if left_normalized is None or right_normalized is None:
        return 0.0
    alignment = max(-1.0, min(1.0, _dot(left_normalized, right_normalized)))
    angle = math.degrees(math.acos(alignment))
    return min(angle, 180.0 - angle)


def _stabilize_non_dominant_body_groups(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    frozen_joints = [
        joint_name
        for joint_name in clip.joint_names
        if _should_freeze_non_dominant_joint(joint_name, dominant_groups)
    ]
    if not frozen_joints:
        return clip, {"applied": False, "reason": "no_non_dominant_groups"}

    stable_pose = {
        joint_name: _median_point([
            frame.joints[joint_name]
            for frame in reference_clip.frames
            if joint_name in frame.joints
        ])
        for joint_name in frozen_joints
        if joint_name in reference_clip.joint_names
    }
    if not stable_pose:
        return clip, {"applied": False, "reason": "missing_reference_joints"}

    residual_tracks = _smoothed_non_dominant_residual_tracks(
        reference_clip,
        joint_names=sorted(stable_pose),
        stable_pose=stable_pose,
    )
    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame_index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        for joint_name, stable_point in stable_pose.items():
            if joint_name not in joints:
                continue
            residual = residual_tracks.get(joint_name, [(0.0, 0.0, 0.0)] * clip.frame_count)[frame_index]
            residual = _limit_vector_length(
                residual,
                _non_dominant_residual_radius(joint_name, dominant_groups),
            )
            target = _add(stable_point, residual)
            displacement = _distance(joints[joint_name], target)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[joint_name] = target
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    return replace(clip, frames=frames), {
        "applied": True,
        "stabilizedJoints": sorted(stable_pose),
        "dominantGroups": sorted(dominant_groups),
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "target": "median_reference_pose_plus_smoothed_capped_residual",
    }


def _smoothed_non_dominant_residual_tracks(
    clip: MotionClip,
    *,
    joint_names: list[str],
    stable_pose: dict[str, Point3],
) -> dict[str, list[Point3]]:
    tracks: dict[str, list[Point3]] = {}
    for joint_name in joint_names:
        stable_point = stable_pose.get(joint_name)
        if stable_point is None:
            continue
        raw_residuals = [
            _subtract(frame.joints[joint_name], stable_point)
            if joint_name in frame.joints else (0.0, 0.0, 0.0)
            for frame in clip.frames
        ]
        tracks[joint_name] = _smooth_residual_track(raw_residuals)
    return tracks


def _smooth_residual_track(values: list[Point3]) -> list[Point3]:
    if len(values) < 3:
        return values
    smoothed = values
    for _ in range(2):
        next_values = list(smoothed)
        for index in range(1, len(smoothed) - 1):
            next_values[index] = (
                smoothed[index - 1][0] * 0.25 + smoothed[index][0] * 0.50 + smoothed[index + 1][0] * 0.25,
                smoothed[index - 1][1] * 0.25 + smoothed[index][1] * 0.50 + smoothed[index + 1][1] * 0.25,
                smoothed[index - 1][2] * 0.25 + smoothed[index][2] * 0.50 + smoothed[index + 1][2] * 0.25,
            )
        smoothed = next_values
    return smoothed


def _non_dominant_residual_radius(joint_name: str, dominant_groups: set[str]) -> float:
    joint_group = _joint_motion_group(joint_name)
    if joint_group == "torso":
        if joint_name in ("left_shoulder", "right_shoulder", "left_collar", "right_collar") and "arms" in dominant_groups:
            return 0.035
        if joint_name in ("pelvis", "left_hip", "right_hip"):
            return 0.018
        if joint_name == "head":
            return 0.025
        return 0.024
    if joint_group == "legs":
        if joint_name.endswith("_foot") or joint_name.endswith("_ankle"):
            return 0.012
        return 0.018
    if joint_group == "arms":
        return 0.022
    return 0.015


def _limit_vector_length(value: Point3, limit: float) -> Point3:
    length = _length(value)
    if length <= limit or length <= 1e-8:
        return value
    return _scale(value, limit / length)


def _reapply_dominant_local_motion(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    specs = _dominant_local_motion_specs(dominant_groups)
    if not specs:
        return clip, {"applied": False, "reason": "no_dominant_local_groups"}
    bilateral_modes = _dominant_bilateral_motion_modes(reference_clip, dominant_groups)

    frames: list[MotionFrame] = []
    reapplied_joints: set[str] = set()
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame, reference_frame in zip(clip.frames, reference_clip.frames):
        joints = dict(frame.joints)
        stable_frame = MotionFrame(time_sec=frame.time_sec, joints=joints)
        for anchor_joint, child_joints in specs:
            stable_anchor = joints.get(anchor_joint)
            reference_anchor = reference_frame.joints.get(anchor_joint)
            if stable_anchor is None or reference_anchor is None:
                continue
            for child_joint in child_joints:
                target_offset = _dominant_local_target_offset(
                    reference_frame,
                    stable_frame=stable_frame,
                    anchor_joint=anchor_joint,
                    child_joint=child_joint,
                    bilateral_modes=bilateral_modes,
                )
                if target_offset is None or child_joint not in joints:
                    continue
                updated = _add(stable_anchor, target_offset)
                displacement = _distance(joints[child_joint], updated)
                if displacement > 1e-6:
                    total_displacement += displacement
                    max_displacement = max(max_displacement, displacement)
                    samples += 1
                joints[child_joint] = updated
                reapplied_joints.add(child_joint)
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    return replace(clip, frames=frames), {
        "applied": bool(reapplied_joints),
        "dominantGroups": sorted(dominant_groups),
        "reappliedJoints": sorted(reapplied_joints),
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "target": "dominant_local_offsets_on_stabilized_anchors",
        "bilateralModes": bilateral_modes,
    }


def _dominant_local_motion_specs(dominant_groups: set[str]) -> list[tuple[str, tuple[str, ...]]]:
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


def _dominant_bilateral_motion_modes(reference_clip: MotionClip, dominant_groups: set[str]) -> dict[str, dict[str, object]]:
    modes: dict[str, dict[str, object]] = {}
    if "arms" in dominant_groups:
        modes["arms"] = _bilateral_motion_mode(
            reference_clip,
            group_name="arms",
            left_anchor="left_shoulder",
            right_anchor="right_shoulder",
            left_end="left_wrist",
            right_end="right_wrist",
            left_joints=("left_elbow", "left_wrist", "left_hand"),
            right_joints=("right_elbow", "right_wrist", "right_hand"),
        )
    if "legs" in dominant_groups:
        modes["legs"] = _bilateral_motion_mode(
            reference_clip,
            group_name="legs",
            left_anchor="left_hip",
            right_anchor="right_hip",
            left_end="left_ankle",
            right_end="right_ankle",
            left_joints=("left_knee", "left_ankle", "left_foot"),
            right_joints=("right_knee", "right_ankle", "right_foot"),
        )
    return modes


def _bilateral_motion_mode(
    clip: MotionClip,
    *,
    group_name: str,
    left_anchor: str,
    right_anchor: str,
    left_end: str,
    right_end: str,
    left_joints: tuple[str, ...],
    right_joints: tuple[str, ...],
) -> dict[str, object]:
    required = (left_anchor, right_anchor, left_end, right_end, *left_joints, *right_joints)
    if any(joint not in clip.joint_names for joint in required):
        return {"group": group_name, "mode": "unavailable", "reason": "missing_joints"}
    left_motion = _joint_group_motion(clip, list(left_joints))
    right_motion = _joint_group_motion(clip, list(right_joints))
    ratio = min(left_motion, right_motion) / max(max(left_motion, right_motion), 1e-8)
    correlation = _mirrored_chain_motion_correlation(clip, left_end=left_end, right_end=right_end)
    pose_symmetry = _mirrored_pose_symmetry(
        clip,
        joint_pairs=tuple(zip(left_joints, right_joints)),
    )
    motion_driven_pose_acceptance = _motion_driven_pose_symmetry_acceptance(
        group_name=group_name,
        motion_ratio=ratio,
        correlation=correlation,
        pose_symmetry=pose_symmetry,
    )
    pose_symmetric = bool(pose_symmetry.get("eligible")) or bool(motion_driven_pose_acceptance.get("accepted"))
    motion_symmetric = ratio >= SYMMETRY_MIN_RATIO and correlation >= max(0.80, SYMMETRY_MIN_CORRELATION)
    same_phase = motion_symmetric and pose_symmetric
    if same_phase:
        mode = "same_phase_symmetric"
    elif ratio >= SYMMETRY_MIN_RATIO:
        mode = "balanced_unsymmetrized"
    else:
        mode = "unilateral_unsymmetrized"
    symmetry_strength = 0.0
    if same_phase:
        asymmetry = max(0.0, 1.0 - ratio)
        strength_floor = 1.0 if group_name == "arms" else 0.48
        strength_base = 1.0 if group_name == "arms" else 0.50
        strength_ceiling = 1.0 if group_name == "arms" else 0.72
        symmetry_strength = min(strength_ceiling, max(strength_floor, strength_base + asymmetry * 1.5))
    return {
        "group": group_name,
        "mode": mode,
        "samePhase": same_phase,
        "leftMotion": left_motion,
        "rightMotion": right_motion,
        "motionRatio": ratio,
        "correlation": correlation,
        "motionSymmetric": motion_symmetric,
        "poseSymmetry": pose_symmetry,
        "motionDrivenPoseSymmetryAcceptance": motion_driven_pose_acceptance,
        "symmetryStrength": symmetry_strength,
    }


def _motion_driven_pose_symmetry_acceptance(
    *,
    group_name: str,
    motion_ratio: float,
    correlation: float,
    pose_symmetry: dict[str, object],
) -> dict[str, object]:
    if group_name != "arms":
        return {"accepted": False, "reason": "only_applies_to_arms"}
    if motion_ratio < ARM_MOTION_DRIVEN_SYMMETRY_MIN_RATIO:
        return {
            "accepted": False,
            "reason": "arm_motion_ratio_too_low",
            "minMotionRatio": ARM_MOTION_DRIVEN_SYMMETRY_MIN_RATIO,
        }
    if correlation < ARM_MOTION_DRIVEN_SYMMETRY_MIN_CORRELATION:
        return {
            "accepted": False,
            "reason": "arm_motion_correlation_too_low",
            "minCorrelation": ARM_MOTION_DRIVEN_SYMMETRY_MIN_CORRELATION,
        }
    median_error = _optional_float(pose_symmetry.get("medianErrorBodyRatio"))
    max_error = _optional_float(pose_symmetry.get("maxErrorBodyRatio"))
    if median_error is None or max_error is None:
        return {"accepted": False, "reason": "missing_pose_error_metrics"}
    accepted = (
        median_error <= ARM_MOTION_DRIVEN_SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO
        and max_error <= ARM_MOTION_DRIVEN_SYMMETRY_MAX_POSE_ERROR_BODY_RATIO
    )
    return {
        "accepted": accepted,
        "reason": "same_phase_arm_motion_overrides_moderate_pose_asymmetry"
        if accepted
        else "arm_pose_asymmetry_too_large",
        "medianErrorBodyRatio": median_error,
        "maxErrorBodyRatio": max_error,
        "maxMedianErrorBodyRatio": ARM_MOTION_DRIVEN_SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO,
        "maxAllowedErrorBodyRatio": ARM_MOTION_DRIVEN_SYMMETRY_MAX_POSE_ERROR_BODY_RATIO,
        "minMotionRatio": ARM_MOTION_DRIVEN_SYMMETRY_MIN_RATIO,
        "minCorrelation": ARM_MOTION_DRIVEN_SYMMETRY_MIN_CORRELATION,
    }


def _mirrored_pose_symmetry(
    clip: MotionClip,
    *,
    joint_pairs: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    if clip.frame_count == 0:
        return {
            "eligible": False,
            "reason": "empty_clip",
            "sampleCount": 0,
        }
    body_height = _median_body_height(clip)
    if body_height <= 1e-6:
        return {
            "eligible": False,
            "reason": "invalid_body_height",
            "sampleCount": 0,
            "bodyHeight": body_height,
        }
    errors: list[float] = []
    per_pair_errors: dict[str, list[float]] = {
        f"{left}:{right}": []
        for left, right in joint_pairs
    }
    for frame in clip.frames:
        body_frame = _body_local_frame(frame)
        if body_frame is None:
            continue
        for left_joint, right_joint in joint_pairs:
            left_point = frame.joints.get(left_joint)
            right_point = frame.joints.get(right_joint)
            if left_point is None or right_point is None:
                continue
            left_local = _to_local(left_point, body_frame, body_frame.origin)
            right_local = _to_local(right_point, body_frame, body_frame.origin)
            mirrored_left = (-left_local[0], left_local[1], left_local[2])
            error_ratio = _distance(mirrored_left, right_local) / body_height
            errors.append(error_ratio)
            per_pair_errors[f"{left_joint}:{right_joint}"].append(error_ratio)
    if not errors:
        return {
            "eligible": False,
            "reason": "no_pose_samples",
            "sampleCount": 0,
            "bodyHeight": body_height,
        }
    median_error = median(errors)
    max_error = max(errors)
    eligible = (
        median_error <= SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO
        and max_error <= SYMMETRY_MAX_POSE_ERROR_BODY_RATIO
    )
    pair_payload = {
        pair_name: {
            "medianErrorBodyRatio": median(pair_errors),
            "maxErrorBodyRatio": max(pair_errors),
            "sampleCount": len(pair_errors),
        }
        for pair_name, pair_errors in per_pair_errors.items()
        if pair_errors
    }
    return {
        "eligible": eligible,
        "reason": "mirrored_pose_within_threshold" if eligible else "mirrored_pose_error_too_large",
        "bodyHeight": body_height,
        "sampleCount": len(errors),
        "medianErrorBodyRatio": median_error,
        "maxErrorBodyRatio": max_error,
        "maxMedianErrorBodyRatio": SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO,
        "maxAllowedErrorBodyRatio": SYMMETRY_MAX_POSE_ERROR_BODY_RATIO,
        "jointPairs": pair_payload,
    }


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _dominant_local_target_offset(
    frame: MotionFrame,
    *,
    stable_frame: MotionFrame,
    anchor_joint: str,
    child_joint: str,
    bilateral_modes: dict[str, dict[str, object]],
) -> Point3 | None:
    mirrored = _mirrored_bilateral_child(child_joint)
    if mirrored is not None:
        group_name, opposite_anchor, opposite_child, is_left = mirrored
        mode = bilateral_modes.get(group_name, {})
        if mode.get("mode") == "same_phase_symmetric":
            return _symmetric_dominant_local_offset(
                frame,
                stable_frame=stable_frame,
                anchor_joint=anchor_joint,
                child_joint=child_joint,
                opposite_anchor=opposite_anchor,
                opposite_child=opposite_child,
                is_left=is_left,
                symmetry_strength=float(mode.get("symmetryStrength", 0.58)),
            )
    anchor = frame.joints.get(anchor_joint)
    child = frame.joints.get(child_joint)
    if anchor is None or child is None:
        return None
    return _subtract(child, anchor)


def _mirrored_bilateral_child(child_joint: str) -> tuple[str, str, str, bool] | None:
    if child_joint.startswith("left_") and child_joint in {"left_elbow", "left_wrist", "left_hand"}:
        return ("arms", "right_shoulder", child_joint.replace("left_", "right_", 1), True)
    if child_joint.startswith("right_") and child_joint in {"right_elbow", "right_wrist", "right_hand"}:
        return ("arms", "left_shoulder", child_joint.replace("right_", "left_", 1), False)
    if child_joint.startswith("left_") and child_joint in {"left_knee", "left_ankle", "left_foot"}:
        return ("legs", "right_hip", child_joint.replace("left_", "right_", 1), True)
    if child_joint.startswith("right_") and child_joint in {"right_knee", "right_ankle", "right_foot"}:
        return ("legs", "left_hip", child_joint.replace("right_", "left_", 1), False)
    return None


def _symmetric_dominant_local_offset(
    frame: MotionFrame,
    *,
    stable_frame: MotionFrame,
    anchor_joint: str,
    child_joint: str,
    opposite_anchor: str,
    opposite_child: str,
    is_left: bool,
    symmetry_strength: float,
) -> Point3 | None:
    reference_body_frame = _body_local_frame(frame)
    stable_body_frame = _body_local_frame(stable_frame)
    if reference_body_frame is None or stable_body_frame is None:
        return None
    anchor = frame.joints.get(anchor_joint)
    child = frame.joints.get(child_joint)
    opposite_anchor_point = frame.joints.get(opposite_anchor)
    opposite_child_point = frame.joints.get(opposite_child)
    stable_anchor = stable_frame.joints.get(anchor_joint)
    if (
        anchor is None
        or child is None
        or opposite_anchor_point is None
        or opposite_child_point is None
        or stable_anchor is None
    ):
        return None
    local = _to_local(child, reference_body_frame, anchor)
    opposite_local = _to_local(opposite_child_point, reference_body_frame, opposite_anchor_point)
    canonical_x = (abs(local[0]) + abs(opposite_local[0])) * 0.5
    shared_y = (local[1] + opposite_local[1]) * 0.5
    shared_z = (local[2] + opposite_local[2]) * 0.5
    blend = min(max(symmetry_strength, 0.0), 1.0)
    if is_left:
        symmetric_local = (-canonical_x, shared_y, shared_z)
    else:
        symmetric_local = (canonical_x, shared_y, shared_z)
    blended_local = _lerp_point(local, symmetric_local, min(max(blend, 0.0), 1.0))
    stable_target = _from_local(blended_local, stable_body_frame, stable_anchor)
    return _subtract(stable_target, stable_anchor)


def _should_freeze_non_dominant_joint(joint_name: str, dominant_groups: set[str]) -> bool:
    joint_group = _joint_motion_group(joint_name)
    if joint_group is None or joint_group in dominant_groups:
        return False
    if joint_group == "torso":
        return "torso" not in dominant_groups
    if joint_group == "legs":
        return "legs" not in dominant_groups
    if joint_group == "arms":
        return "arms" not in dominant_groups
    return False


def _stabilize_non_dominant_contact_points(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    candidates = []
    if "legs" not in dominant_groups:
        candidates.extend(["left_foot", "right_foot"])
    if "arms" not in dominant_groups:
        candidates.extend(["left_hand", "right_hand"])
    contact_joints = [joint for joint in candidates if joint in clip.joint_names]
    if not contact_joints:
        return clip, {"applied": False, "reason": "no_non_dominant_contacts"}

    anchors = {
        joint: _median_point([
            frame.joints[joint]
            for frame in reference_clip.frames
            if joint in frame.joints
        ])
        for joint in contact_joints
    }
    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        joints = dict(frame.joints)
        for joint_name, anchor in anchors.items():
            if joint_name not in joints:
                continue
            updated = _limited_lerp_point(joints[joint_name], anchor, 0.68, 0.03)
            displacement = _distance(joints[joint_name], updated)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[joint_name] = updated
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": True,
        "contactJoints": sorted(contact_joints),
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "maxCorrection": 0.03,
    }


def _preserve_reference_bone_lengths(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    reference_lengths = {
        (parent, child): _median_bone_length(reference_clip, parent, child)
        for parent, child in STRUCTURAL_BONES
        if parent in reference_clip.joint_names and child in reference_clip.joint_names
    }
    if not reference_lengths:
        return clip, {"applied": False, "reason": "no_reference_bones"}

    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        joints = dict(frame.joints)
        for (parent, child), target_length in reference_lengths.items():
            if parent not in joints or child not in joints:
                continue
            direction = _subtract(joints[child], joints[parent])
            current_length = _length(direction)
            if current_length <= 1e-8:
                continue
            projected = _add(joints[parent], _scale(direction, target_length / current_length))
            displacement = _distance(joints[child], projected)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[child] = projected
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": True,
        "boneCount": len(reference_lengths),
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
    }


def _refine_non_dominant_chains_with_ik(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    dominant_profile: dict[str, object],
    damping: float,
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    chain_results: list[dict[str, object]] = []
    refined = clip
    if "arms" not in dominant_groups:
        refined, left_arm = _refine_non_dominant_two_bone_chain(
            refined,
            reference_clip=reference_clip,
            root_joint="left_shoulder",
            mid_joint="left_elbow",
            end_joint="left_wrist",
            extra_joint="left_hand",
            chain_name="leftArm",
            damping=damping,
        )
        refined, right_arm = _refine_non_dominant_two_bone_chain(
            refined,
            reference_clip=reference_clip,
            root_joint="right_shoulder",
            mid_joint="right_elbow",
            end_joint="right_wrist",
            extra_joint="right_hand",
            chain_name="rightArm",
            damping=damping,
        )
        chain_results.extend([left_arm, right_arm])
    if "legs" not in dominant_groups:
        refined, left_leg = _refine_non_dominant_two_bone_chain(
            refined,
            reference_clip=reference_clip,
            root_joint="left_hip",
            mid_joint="left_knee",
            end_joint="left_ankle",
            extra_joint="left_foot",
            chain_name="leftLeg",
            damping=damping,
        )
        refined, right_leg = _refine_non_dominant_two_bone_chain(
            refined,
            reference_clip=reference_clip,
            root_joint="right_hip",
            mid_joint="right_knee",
            end_joint="right_ankle",
            extra_joint="right_foot",
            chain_name="rightLeg",
            damping=damping,
        )
        chain_results.extend([left_leg, right_leg])
    applied_results = [result for result in chain_results if result.get("applied")]
    return refined, {
        "applied": bool(applied_results),
        "chains": chain_results,
        "damping": damping,
    }


def _refine_non_dominant_two_bone_chain(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    root_joint: str,
    mid_joint: str,
    end_joint: str,
    extra_joint: str | None,
    chain_name: str,
    damping: float,
) -> tuple[MotionClip, dict[str, object]]:
    required = (root_joint, mid_joint, end_joint)
    if any(joint not in clip.joint_names or joint not in reference_clip.joint_names for joint in required):
        return clip, {"applied": False, "chain": chain_name, "reason": "missing_required_joints"}

    root_to_end_reference = _median_point([
        _subtract(frame.joints[end_joint], frame.joints[root_joint])
        for frame in reference_clip.frames
        if root_joint in frame.joints and end_joint in frame.joints
    ])
    root_to_extra_reference = None
    if extra_joint and extra_joint in clip.joint_names and extra_joint in reference_clip.joint_names:
        root_to_extra_reference = _median_point([
            _subtract(frame.joints[extra_joint], frame.joints[root_joint])
            for frame in reference_clip.frames
            if root_joint in frame.joints and extra_joint in frame.joints
        ])
    upper_len = _median_bone_length(reference_clip, root_joint, mid_joint)
    lower_len = _median_bone_length(reference_clip, mid_joint, end_joint)
    damping = min(max(damping, 0.0), 1.0)
    target_alpha = 0.35 + damping * 0.55
    max_end_correction = 0.025 + damping * 0.075
    max_extra_correction = 0.02 + damping * 0.055

    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        joints = dict(frame.joints)
        root = joints[root_joint]
        stable_end_target = _add(root, root_to_end_reference)
        damped_end_target = _limited_lerp_point(
            joints[end_joint],
            stable_end_target,
            target_alpha,
            max_end_correction,
        )
        body_frame = _body_local_frame(frame)
        fallback_axis = body_frame.forward if body_frame is not None else (0.0, 0.0, 1.0)
        solved_mid, solved_end = _solve_two_bone(
            root=root,
            current_mid=joints[mid_joint],
            target_end=damped_end_target,
            upper_len=upper_len,
            lower_len=lower_len,
            fallback_axis=fallback_axis,
        )
        for joint_name, updated in ((mid_joint, solved_mid), (end_joint, solved_end)):
            displacement = _distance(joints[joint_name], updated)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[joint_name] = updated
        if extra_joint and root_to_extra_reference is not None and extra_joint in joints:
            stable_extra_target = _add(root, root_to_extra_reference)
            updated_extra = _limited_lerp_point(
                joints[extra_joint],
                stable_extra_target,
                target_alpha,
                max_extra_correction,
            )
            displacement = _distance(joints[extra_joint], updated_extra)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[extra_joint] = updated_extra
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    return replace(clip, frames=frames), {
        "applied": True,
        "chain": chain_name,
        "rootJoint": root_joint,
        "midJoint": mid_joint,
        "endJoint": end_joint,
        "extraJoint": extra_joint,
        "targetAlpha": target_alpha,
        "maxEndCorrection": max_end_correction,
        "maxExtraCorrection": max_extra_correction,
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
    }


def _limit_non_dominant_motion_amplification(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    dominant_profile: dict[str, object],
    non_dominant_damping: float,
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    limited_joints = [
        joint_name
        for joint_name in clip.joint_names
        if _joint_motion_group(joint_name) is not None
        and _joint_motion_group(joint_name) not in dominant_groups
    ]
    if clip.frame_count < 2 or not limited_joints:
        return clip, {"applied": False, "reason": "no_non_dominant_motion_to_limit"}

    frames = [MotionFrame(time_sec=clip.frames[0].time_sec, joints=dict(clip.frames[0].joints))]
    corrections = 0
    max_pullback = 0.0
    tolerance = 0.006 * (1.0 - non_dominant_damping)
    step_scale = 1.0 - non_dominant_damping * 0.75
    for frame_index in range(1, clip.frame_count):
        previous_refined = frames[-1].joints
        current = dict(clip.frames[frame_index].joints)
        previous_original = reference_clip.frames[frame_index - 1].joints
        current_original = reference_clip.frames[frame_index].joints
        for joint_name in limited_joints:
            if (
                joint_name not in previous_refined
                or joint_name not in current
                or joint_name not in previous_original
                or joint_name not in current_original
            ):
                continue
            original_step = _distance(previous_original[joint_name], current_original[joint_name])
            max_step = original_step * step_scale + tolerance
            refined_delta = _subtract(current[joint_name], previous_refined[joint_name])
            refined_step = _length(refined_delta)
            if refined_step <= max_step or refined_step <= 1e-8:
                continue
            capped = _add(previous_refined[joint_name], _scale(refined_delta, max_step / refined_step))
            pullback = _distance(current[joint_name], capped)
            current[joint_name] = capped
            corrections += 1
            max_pullback = max(max_pullback, pullback)
        frames.append(MotionFrame(time_sec=clip.frames[frame_index].time_sec, joints=current))
    return replace(clip, frames=frames), {
        "applied": corrections > 0,
        "limitedJoints": sorted(limited_joints),
        "correctionCount": corrections,
        "maxPullback": max_pullback,
        "tolerance": tolerance,
        "stepScale": step_scale,
    }


def _mirrored_chain_motion_correlation(clip: MotionClip, *, left_end: str, right_end: str) -> float:
    left_values: list[float] = []
    right_values: list[float] = []
    canonical_left: list[Point3] = []
    canonical_right: list[Point3] = []
    for frame in clip.frames:
        body_frame = _body_local_frame(frame)
        if body_frame is None:
            continue
        origin = body_frame.origin
        left_local = _to_local(frame.joints[left_end], body_frame, origin)
        right_local = _to_local(frame.joints[right_end], body_frame, origin)
        canonical_left.append((-left_local[0], left_local[1], left_local[2]))
        canonical_right.append((right_local[0], right_local[1], right_local[2]))
    if len(canonical_left) < 3:
        return 0.0
    left_center = _median_point(canonical_left)
    right_center = _median_point(canonical_right)
    for left, right in zip(canonical_left, canonical_right):
        left_delta = _subtract(left, left_center)
        right_delta = _subtract(right, right_center)
        left_values.extend((left_delta[1], left_delta[2]))
        right_values.extend((right_delta[1], right_delta[2]))
    return _pearson(left_values, right_values)


def _symmetric_pair_targets(
    frame: MotionFrame,
    *,
    body_frame: "BodyFrame",
    pairs: tuple[tuple[str, str], ...],
) -> dict[str, Point3]:
    targets: dict[str, Point3] = {}
    for left_joint, right_joint in pairs:
        if left_joint not in frame.joints or right_joint not in frame.joints:
            continue
        left_local = _to_local(frame.joints[left_joint], body_frame, body_frame.origin)
        right_local = _to_local(frame.joints[right_joint], body_frame, body_frame.origin)
        half_width = (abs(left_local[0]) + abs(right_local[0])) * 0.5
        shared_y = (left_local[1] + right_local[1]) * 0.5
        shared_z = (left_local[2] + right_local[2]) * 0.5
        targets[left_joint] = _from_local((-half_width, shared_y, shared_z), body_frame, body_frame.origin)
        targets[right_joint] = _from_local((half_width, shared_y, shared_z), body_frame, body_frame.origin)
    return targets


def _solve_two_bone(
    *,
    root: Point3,
    current_mid: Point3,
    target_end: Point3,
    upper_len: float,
    lower_len: float,
    fallback_axis: Point3,
) -> tuple[Point3, Point3]:
    root_to_target = _subtract(target_end, root)
    distance = _length(root_to_target)
    if distance <= 1e-6:
        return current_mid, target_end
    max_reach = max(1e-6, upper_len + lower_len - 1e-5)
    min_reach = max(0.0, abs(upper_len - lower_len) + 1e-5)
    clamped_distance = min(max(distance, min_reach), max_reach)
    direction = _scale(root_to_target, 1.0 / distance)
    solved_end = _add(root, _scale(direction, clamped_distance))
    projection_length = (
        (upper_len * upper_len - lower_len * lower_len + clamped_distance * clamped_distance)
        / max(2.0 * clamped_distance, 1e-6)
    )
    bend_height = math.sqrt(max(0.0, upper_len * upper_len - projection_length * projection_length))
    current_root_to_mid = _subtract(current_mid, root)
    projected_mid = _add(root, _scale(direction, _dot(current_root_to_mid, direction)))
    bend_direction = _subtract(current_mid, projected_mid)
    if _length(bend_direction) <= 1e-6:
        bend_direction = _cross(direction, fallback_axis)
    if _length(bend_direction) <= 1e-6:
        bend_direction = _cross(direction, (0.0, 1.0, 0.0))
    bend_direction = _normalize(bend_direction)
    solved_mid = _add(
        _add(root, _scale(direction, projection_length)),
        _scale(bend_direction, bend_height),
    )
    return solved_mid, solved_end


class BodyFrame:
    def __init__(self, *, origin: Point3, right: Point3, up: Point3, forward: Point3) -> None:
        self.origin = origin
        self.right = right
        self.up = up
        self.forward = forward


def _body_local_frame(frame: MotionFrame) -> BodyFrame | None:
    joints = frame.joints
    origin = joints.get("pelvis")
    if origin is None:
        return None
    right_axis = None
    if "left_shoulder" in joints and "right_shoulder" in joints:
        right_axis = _normalize(_subtract(joints["right_shoulder"], joints["left_shoulder"]))
    if right_axis is None and "left_hip" in joints and "right_hip" in joints:
        right_axis = _normalize(_subtract(joints["right_hip"], joints["left_hip"]))
    if right_axis is None:
        return None
    spine_top = joints.get("neck") or joints.get("head") or joints.get("spine3")
    if spine_top is None:
        return None
    spine_axis = _normalize(_subtract(spine_top, origin))
    if spine_axis is None:
        return None
    forward_axis = _normalize(_cross(right_axis, spine_axis))
    if forward_axis is None:
        forward_axis = _normalize(_cross(right_axis, (0.0, 1.0, 0.0)))
    if forward_axis is None:
        return None
    up_axis = _normalize(_cross(forward_axis, right_axis))
    if up_axis is None:
        return None
    return BodyFrame(origin=origin, right=right_axis, up=up_axis, forward=forward_axis)


def _median_bone_length(clip: MotionClip, start_joint: str, end_joint: str) -> float:
    return median([
        _distance(frame.joints[start_joint], frame.joints[end_joint])
        for frame in clip.frames
    ])


def _median_body_height(clip: MotionClip) -> float:
    frame_heights: list[float] = []
    for frame in clip.frames:
        points = list(frame.joints.values())
        if not points:
            continue
        y_values = [point[1] for point in points]
        frame_heights.append(max(y_values) - min(y_values))
    return median(frame_heights) if frame_heights else 0.0


def _to_local(point: Point3, frame: BodyFrame, origin: Point3) -> Point3:
    relative = _subtract(point, origin)
    return (_dot(relative, frame.right), _dot(relative, frame.up), _dot(relative, frame.forward))


def _from_local(point: Point3, frame: BodyFrame, origin: Point3) -> Point3:
    return _add(
        origin,
        _add(
            _scale(frame.right, point[0]),
            _add(_scale(frame.up, point[1]), _scale(frame.forward, point[2])),
        ),
    )


def _average_points(points: list[Point3]) -> Point3:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
        sum(point[2] for point in points) / len(points),
    )


def _median_point(points: list[Point3]) -> Point3:
    return (
        median(point[0] for point in points),
        median(point[1] for point in points),
        median(point[2] for point in points),
    )


def _principal_direction(samples: list[Point3]) -> Point3 | None:
    if len(samples) < 2:
        return None
    mean = _average_points(samples)
    centered = [_subtract(sample, mean) for sample in samples]
    vector = _normalize(_subtract(samples[-1], samples[0])) or (0.0, 1.0, 0.0)
    for _ in range(8):
        next_vector = (
            sum(item[0] * _dot(item, vector) for item in centered),
            sum(item[1] * _dot(item, vector) for item in centered),
            sum(item[2] * _dot(item, vector) for item in centered),
        )
        if _length(next_vector) <= 1e-8:
            return None
        vector = _normalize(next_vector) or vector
    return vector if _length(vector) > 1e-6 else None


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 3:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((left_value - left_mean) * (right_value - right_mean) for left_value, right_value in zip(left, right))
    left_denominator = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_denominator = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    denominator = left_denominator * right_denominator
    if denominator <= 1e-8:
        return 0.0
    return numerator / denominator


def _distance(left: Point3, right: Point3) -> float:
    return _length(_subtract(left, right))


def _subtract(left: Point3, right: Point3) -> Point3:
    return (left[0] - right[0], left[1] - right[1], left[2] - right[2])


def _add(left: Point3, right: Point3) -> Point3:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def _scale(point: Point3, scalar: float) -> Point3:
    return (point[0] * scalar, point[1] * scalar, point[2] * scalar)


def _lerp_point(left: Point3, right: Point3, alpha: float) -> Point3:
    return (
        left[0] * (1.0 - alpha) + right[0] * alpha,
        left[1] * (1.0 - alpha) + right[1] * alpha,
        left[2] * (1.0 - alpha) + right[2] * alpha,
    )


def _limited_lerp_point(left: Point3, right: Point3, alpha: float, max_distance: float) -> Point3:
    target = _lerp_point(left, right, alpha)
    delta = _subtract(target, left)
    distance = _length(delta)
    if distance <= max_distance or distance <= 1e-8:
        return target
    return _add(left, _scale(delta, max_distance / distance))


def _clamp_scalar(value: float, limit: float) -> float:
    return min(max(value, -limit), limit)


def _dot(left: Point3, right: Point3) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _cross(left: Point3, right: Point3) -> Point3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _length(point: Point3) -> float:
    return math.sqrt(_dot(point, point))


def _normalize(point: Point3) -> Point3 | None:
    length = _length(point)
    if length <= 1e-8:
        return None
    return _scale(point, 1.0 / length)
