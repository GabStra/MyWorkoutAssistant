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
SOFT_LEG_SYMMETRY_MIN_BLEND = 0.16
SOFT_LEG_SYMMETRY_MAX_BLEND = 0.34
SOFT_LEG_SYMMETRY_BLEND_SCALE = 0.45
SOFT_LEG_SYMMETRY_MAX_CORRECTION_METERS = 0.028
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
    bilateral_modes = _dominant_bilateral_motion_modes(clip, dominant_groups)
    if bilateral_modes:
        dominant_profile = {
            **dominant_profile,
            "bilateralModes": bilateral_modes,
        }
    if "torso" in dominant_groups:
        refined, refinement_metadata = _refine_torso_dominant_motion_conservatively(
            clip,
            active_threshold=active_threshold,
            strongest_chain_motion=strongest_chain_motion,
            dominant_profile=dominant_profile,
            non_dominant_radius_scale=non_dominant_radius_scale,
        )
    else:
        refined, refinement_metadata = _preserve_non_torso_dominant_motion(
            clip,
            dominant_profile=dominant_profile,
        )
    if "torso" not in dominant_groups:
        head_metadata = {
            "applied": False,
            "reason": "source_preserving_branch_skips_head_pose_reconstruction",
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
    angular_limited_samples = 0
    previous_target_offset: Point3 | None = None
    previous_time_sec: float | None = None
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
        if previous_target_offset is not None and previous_time_sec is not None:
            elapsed_seconds = max(frame.time_sec - previous_time_sec, 1.0 / max(clip.fps, 1.0))
            target_offset, angular_limited = _limit_vector_angular_change(
                previous_target_offset,
                target_offset,
                max_angle_radians=math.radians(180.0) * elapsed_seconds,
            )
            if angular_limited:
                angular_limited_samples += 1
        previous_target_offset = target_offset
        previous_time_sec = frame.time_sec
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
        "angularLimitedSamples": angular_limited_samples,
        "maximumAngularSpeedDegreesPerSecond": 180.0,
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
    maximum_off_axis = max(max(along_spine, 0.0) * 0.85, length * 0.45)
    if along_spine > 0.0 and off_axis <= maximum_off_axis:
        return reference_offset, False
    corrected_along_spine = max(along_spine, length * 0.45)
    if off_axis <= 1e-6:
        corrected_local = (0.0, corrected_along_spine, 0.0)
    else:
        off_axis_scale = min(1.0, maximum_off_axis / off_axis)
        corrected_local = (
            local[0] * off_axis_scale,
            corrected_along_spine,
            local[2] * off_axis_scale,
        )
    corrected_world = _add(
        _scale(body_frame.right, corrected_local[0]),
        _add(
            _scale(body_frame.up, corrected_local[1]),
            _scale(body_frame.forward, corrected_local[2]),
        ),
    )
    corrected_direction = _normalize(corrected_world)
    if corrected_direction is None:
        return _scale(body_frame.up, length), True
    return _scale(corrected_direction, length), True


def _limit_vector_angular_change(
    previous: Point3,
    target: Point3,
    *,
    max_angle_radians: float,
) -> tuple[Point3, bool]:
    previous_length = _length(previous)
    target_length = _length(target)
    if previous_length <= 1e-6 or target_length <= 1e-6:
        return target, False
    previous_direction = _scale(previous, 1.0 / previous_length)
    target_direction = _scale(target, 1.0 / target_length)
    cosine = max(-1.0, min(1.0, _dot(previous_direction, target_direction)))
    angle = math.acos(cosine)
    if angle <= max_angle_radians or angle <= 1e-6:
        return target, False
    blend = max_angle_radians / angle
    sin_angle = math.sin(angle)
    if abs(sin_angle) <= 1e-6:
        blended_direction = _normalize(
            _add(
                _scale(previous_direction, 1.0 - blend),
                _scale(target_direction, blend),
            )
        )
    else:
        blended_direction = _add(
            _scale(previous_direction, math.sin((1.0 - blend) * angle) / sin_angle),
            _scale(target_direction, math.sin(blend * angle) / sin_angle),
        )
    if blended_direction is None:
        return target, False
    return _scale(blended_direction, target_length), True










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


def _preserve_non_torso_dominant_motion(
    clip: MotionClip,
    *,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    return clip, {
        "strategy": "source_preserving_non_torso_motion",
        "applied": False,
        "reason": "canonical_reconstruction_can_distort_source_motion",
        "dominantGroups": list(dominant_profile.get("dominantGroups", [])),
        "maxJointDisplacement": 0.0,
        "steps": [],
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
    bilateral_modes = _bilateral_modes_from_dominant_profile(dominant_profile)
    refined, soft_bilateral_metadata = _apply_soft_same_phase_leg_symmetry(
        refined,
        bilateral_modes=bilateral_modes,
    )
    dynamic_bone_length_joints = _range_dominant_chain_child_joints(dominant_profile)
    refined, length_metadata = _preserve_reference_bone_lengths(
        refined,
        reference_clip=clip,
        dynamic_length_child_joints=dynamic_bone_length_joints,
    )
    return refined, {
        "strategy": "torso_dominant_conservative_cleanup",
        "bilateralModes": bilateral_modes,
        "lowMagnitudeSuppression": jitter_metadata,
        "temporalSpikes": spike_metadata,
        "stabilizedIkTargetConstraint": target_constraint_metadata,
        "distalLegSlidingStabilization": distal_leg_metadata,
        "footAxisLegAlignment": foot_axis_leg_metadata,
        "softBilateralSymmetry": soft_bilateral_metadata,
        "boneLengthProjection": length_metadata,
        "steps": [
            "torso_dominant_preserve_body_motion",
            "low_magnitude_motion_suppression",
            "isolated_temporal_spike_suppression",
            "stabilized_ik_target_constraint",
            "torso_dominant_distal_leg_sliding_stabilization",
            "foot_axis_leg_motion_alignment",
            "soft_same_phase_leg_symmetry",
            "reference_bone_length_projection",
        ],
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
    joint_group = _joint_motion_group(joint_name)
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    range_dominant_groups = set(dominant_profile.get("rangeDominantGroups", []))
    if joint_group is not None and joint_group in dominant_groups and joint_group in range_dominant_groups:
        return False
    if joint_motion <= active_threshold:
        return True
    if joint_group is None:
        return False
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


def _range_dominant_chain_child_joints(dominant_profile: dict[str, object]) -> set[str]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    range_dominant_groups = set(dominant_profile.get("rangeDominantGroups", []))
    joints: set[str] = set()
    if "arms" in dominant_groups and "arms" in range_dominant_groups:
        joints.update((
            "left_elbow",
            "right_elbow",
            "left_wrist",
            "right_wrist",
            "left_hand",
            "right_hand",
        ))
    if "legs" in dominant_groups and "legs" in range_dominant_groups:
        joints.update((
            "left_knee",
            "right_knee",
            "left_ankle",
            "right_ankle",
            "left_foot",
            "right_foot",
        ))
    return joints


def _never_suppress_anchor_joints() -> set[str]:
    return {
        "pelvis",
        "left_hip",
        "right_hip",
        "spine1",
        "spine2",
        "spine3",
    }
















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






def _apply_soft_same_phase_leg_symmetry(
    clip: MotionClip,
    *,
    bilateral_modes: dict[str, dict[str, object]],
) -> tuple[MotionClip, dict[str, object]]:
    legs_mode = bilateral_modes.get("legs")
    if not isinstance(legs_mode, dict) or legs_mode.get("mode") != "same_phase_symmetric":
        return clip, {
            "applied": False,
            "reason": "legs_not_same_phase_symmetric",
            "legsMode": legs_mode,
        }
    pairs = (
        ("left_knee", "right_knee"),
        ("left_ankle", "right_ankle"),
        ("left_foot", "right_foot"),
    )
    required = ("left_hip", "right_hip", *[joint for pair in pairs for joint in pair])
    if any(joint not in clip.joint_names for joint in required):
        return clip, {
            "applied": False,
            "reason": "missing_leg_joints",
            "legsMode": legs_mode,
        }
    mode_strength = _optional_float(legs_mode.get("symmetryStrength"))
    if mode_strength is None:
        mode_strength = 0.50
    blend = min(
        SOFT_LEG_SYMMETRY_MAX_BLEND,
        max(SOFT_LEG_SYMMETRY_MIN_BLEND, mode_strength * SOFT_LEG_SYMMETRY_BLEND_SCALE),
    )
    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        body_frame = _body_local_frame(frame)
        if body_frame is None:
            frames.append(frame)
            continue
        targets = _symmetric_pair_targets(
            frame,
            body_frame=body_frame,
            pairs=pairs,
        )
        if not targets:
            frames.append(frame)
            continue
        joints = dict(frame.joints)
        for joint_name, target in targets.items():
            current = joints.get(joint_name)
            if current is None:
                continue
            updated = _limited_lerp_point(
                current,
                target,
                blend,
                SOFT_LEG_SYMMETRY_MAX_CORRECTION_METERS,
            )
            displacement = _distance(current, updated)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[joint_name] = updated
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    if samples == 0:
        return clip, {
            "applied": False,
            "reason": "no_leg_symmetry_correction_needed",
            "legsMode": legs_mode,
            "blend": blend,
        }
    refined = replace(clip, frames=frames)
    displacement = _average_joint_displacement(
        clip,
        refined,
        [joint for pair in pairs for joint in pair],
    )
    return refined, {
        "applied": True,
        "groups": ["legs"],
        "target": "soft_body_local_mirrored_leg_pairs",
        "blend": blend,
        "maxCorrection": SOFT_LEG_SYMMETRY_MAX_CORRECTION_METERS,
        "averageDisplacement": displacement["average"],
        "maxDisplacement": displacement["max"],
        "sampleAverageDisplacement": total_displacement / samples,
        "sampleMaxDisplacement": max_displacement,
        "legsMode": legs_mode,
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














def _axis_angle_degrees(left: Point3, right: Point3) -> float:
    left_normalized = _normalize(left)
    right_normalized = _normalize(right)
    if left_normalized is None or right_normalized is None:
        return 0.0
    alignment = max(-1.0, min(1.0, _dot(left_normalized, right_normalized)))
    angle = math.degrees(math.acos(alignment))
    return min(angle, 180.0 - angle)
















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


def _bilateral_modes_from_dominant_profile(dominant_profile: dict[str, object]) -> dict[str, dict[str, object]]:
    modes = dominant_profile.get("bilateralModes")
    if not isinstance(modes, dict):
        return {}
    return {
        str(group_name): dict(mode)
        for group_name, mode in modes.items()
        if isinstance(mode, dict)
    }


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












def _preserve_reference_bone_lengths(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    dynamic_length_child_joints: set[str] | None = None,
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
    dynamic_joints = set(dynamic_length_child_joints or set())
    dynamic_samples = 0
    for frame_index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        reference_frame = reference_clip.frames[min(frame_index, reference_clip.frame_count - 1)]
        for (parent, child), target_length in reference_lengths.items():
            if parent not in joints or child not in joints:
                continue
            if (
                child in dynamic_joints
                and parent in reference_frame.joints
                and child in reference_frame.joints
            ):
                target_length = _distance(reference_frame.joints[parent], reference_frame.joints[child])
                dynamic_samples += 1
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
        "dynamicLengthChildJoints": sorted(dynamic_joints),
        "dynamicLengthSampleCount": dynamic_samples,
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
