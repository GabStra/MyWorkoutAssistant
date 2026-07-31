from __future__ import annotations

from dataclasses import dataclass
import math
import statistics

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
) -> tuple[MotionClip, CleanupStats]:
    repaired_clip, repaired_joint_outliers = repair_isolated_joint_position_outliers(clip)
    trimmed_clip, start_trim, end_trim = trim_static_edges(
        repaired_clip,
        motion_threshold=motion_threshold,
        padding_frames=padding_frames,
    )
    root_joint = find_first_joint(trimmed_clip, DEFAULT_ROOT_JOINTS)
    avg_root_before = average_joint_axis(trimmed_clip, root_joint, axis=1)
    support_mode = detect_support_mode(trimmed_clip)
    raw_support_states = detect_support_contact_states(trimmed_clip, support_mode=support_mode)
    grounded = ground_to_floor(
        trimmed_clip,
        support_states=raw_support_states,
        support_mode=support_mode,
    )
    support_states = detect_support_contact_states(grounded, support_mode=support_mode)
    support_ground_y = estimate_support_ground_height(grounded, support_states)
    support_stabilized = stabilize_global_translation_from_support_contacts(
        grounded,
        contact_states=support_states,
        support_ground_y=support_ground_y,
    )
    smoothed = smooth_root_translation(
        support_stabilized,
        root_joint=root_joint,
        min_cutoff=one_euro_min_cutoff,
        beta=one_euro_beta,
        derivative_cutoff=one_euro_derivative_cutoff,
    )
    vertically_grounded, vertical_grounding = stabilize_vertical_floor_contact(
        smoothed,
        ground_contact_mode="continuous" if support_mode == "quadruped" else ground_contact_mode,
    )
    if support_mode == "quadruped":
        support_constrained, support_constraint = solve_quadruped_support(
            vertically_grounded,
            contact_states=detect_support_contact_states(
                vertically_grounded,
                support_mode=support_mode,
            ),
        )
    else:
        support_constrained = vertically_grounded
        support_constraint = {"applied": False, "reason": "upright_support_uses_existing_grounding"}
    final_support_states = detect_support_contact_states(
        support_constrained,
        support_mode=support_mode,
    )
    final_support_ground_y = estimate_support_ground_height(
        support_constrained,
        final_support_states,
    )
    solved_ground_y = support_constraint.get("groundY")
    if support_mode == "quadruped" and isinstance(solved_ground_y, (int, float)):
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
) -> tuple[MotionClip, dict[str, object]]:
    forward_axis = _horizontal_torso_axis(clip)
    if forward_axis is None:
        return constrain_support_surfaces(clip, contact_states=contact_states)
    support_joint_names = sorted({
        joint_name
        for state in contact_states
        for joint_name in iter_contact_joint_names(state)
    })
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
                support_heights.append(support_surface_height(coords[1]))
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
                    support_joint_height_for_surface(support_ground_y),
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
                    support_joint_height_for_surface(support_ground_y),
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


def detect_support_mode(clip: MotionClip) -> str:
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
    required_joints = ("left_hand", "right_hand", "left_knee", "right_knee")
    if horizontal > vertical and all(joint in clip.joint_names for joint in required_joints):
        return "quadruped"
    return "upright"


def support_joint_names_for_mode(clip: MotionClip, support_mode: str) -> list[str]:
    candidates = (
        DEFAULT_HAND_JOINTS + LEFT_KNEE_GROUP + RIGHT_KNEE_GROUP
        if support_mode == "quadruped"
        else DEFAULT_FOOT_JOINTS + DEFAULT_HAND_JOINTS
    )
    return [joint for joint in candidates if joint in clip.joint_names]


def detect_support_contact_states(
    clip: MotionClip,
    *,
    support_mode: str | None = None,
) -> list[dict[str, object]]:
    support_mode = support_mode or detect_support_mode(clip)
    states: list[dict[str, object]] = []
    quadruped = support_mode == "quadruped"
    left_joint = first_available_joint(clip, LEFT_KNEE_GROUP if quadruped else LEFT_FOOT_GROUP)
    right_joint = first_available_joint(clip, RIGHT_KNEE_GROUP if quadruped else RIGHT_FOOT_GROUP)
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
        contacting_joints = [
            joint_name
            for joint_name, in_contact in (
                (left_joint, left_contact),
                (right_joint, right_contact),
                (left_hand_joint, left_hand_contact),
                (right_hand_joint, right_hand_contact),
            )
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
            hand_contacts = sum(1 for value in (left_hand_contact, right_hand_contact) if value)
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
                "leftKneeJoint": left_joint if quadruped else None,
                "rightKneeJoint": right_joint if quadruped else None,
                "leftHandJoint": left_hand_joint,
                "rightHandJoint": right_hand_joint,
                "leftInContact": left_contact if not quadruped else False,
                "rightInContact": right_contact if not quadruped else False,
                "leftKneeInContact": left_contact if quadruped else False,
                "rightKneeInContact": right_contact if quadruped else False,
                "leftHandInContact": left_hand_contact,
                "rightHandInContact": right_hand_contact,
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
