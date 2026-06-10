from __future__ import annotations

from dataclasses import dataclass
import math

from exercise_motion_pkg.models import MotionClip, MotionFrame, Point3


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
SPINE_CHAIN_BLEND = 0.65
TORSO_MICRO_MOVEMENT_TOLERANCE = 0.03
ARM_MICRO_MOVEMENT_TOLERANCE = 0.02
LEG_MICRO_MOVEMENT_TOLERANCE = 0.018
SUPPORT_LOCK_BLEND = 0.75
SUPPORT_LOCK_XZ_BLEND = 0.7
SUPPORT_LOCK_Y_BLEND = 0.9
SEGMENT_ROOT_STABILIZATION_BLEND = 1.0
SEGMENT_ROOT_STABILIZATION_MIN_FRAMES = 3
ONE_EURO_MIN_CUTOFF = 0.6
ONE_EURO_BETA = 0.05
ONE_EURO_D_CUTOFF = 1.0
SUPPORT_GROUND_HEIGHT_QUANTILE = 0.30
FOOT_CONTACT_GROUND_QUANTILE = 0.20

LEFT_FOOT_GROUP = ("left_foot", "left_ankle", "l_ankle")
RIGHT_FOOT_GROUP = ("right_foot", "right_ankle", "r_ankle")
LEFT_HAND_GROUP = ("left_hand", "left_wrist")
RIGHT_HAND_GROUP = ("right_hand", "right_wrist")
SPINE_CHAIN_RATIOS = (
    ("spine1", 0.28),
    ("spine2", 0.52),
    ("spine3", 0.74),
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
) -> tuple[MotionClip, CleanupStats]:
    trimmed_clip, start_trim, end_trim = trim_static_edges(
        clip,
        motion_threshold=motion_threshold,
        padding_frames=padding_frames,
    )
    root_joint = find_first_joint(trimmed_clip, DEFAULT_ROOT_JOINTS)
    avg_root_before = average_joint_axis(trimmed_clip, root_joint, axis=1)
    raw_support_states = detect_support_contact_states(trimmed_clip)
    grounded = ground_to_floor(trimmed_clip, support_states=raw_support_states)
    support_states = detect_support_contact_states(grounded)
    smoothed = smooth_root_translation(
        grounded,
        root_joint=root_joint,
        min_cutoff=one_euro_min_cutoff,
        beta=one_euro_beta,
        derivative_cutoff=one_euro_derivative_cutoff,
    )
    polished = smoothed
    avg_root_after = average_joint_axis(polished, root_joint, axis=1)
    support_profile = _summarize_support_states(support_states)
    stats = CleanupStats(
        input_frames=clip.frame_count,
        output_frames=polished.frame_count,
        trimmed_start_frames=start_trim,
        trimmed_end_frames=end_trim,
        average_root_height_before=avg_root_before,
        average_root_height_after=avg_root_after,
    )
    metadata = dict(polished.metadata)
    metadata["cleanup"] = {
        "oneEuroMinCutoff": one_euro_min_cutoff,
        "oneEuroBeta": one_euro_beta,
        "oneEuroDerivativeCutoff": one_euro_derivative_cutoff,
        "motionThreshold": motion_threshold,
        "paddingFrames": padding_frames,
        "smoothingMethod": "one_euro_root_translation_xz",
        "trimmedStartFrames": start_trim,
        "trimmedEndFrames": end_trim,
        "rootJoint": root_joint,
        "appliedPostProcessingSteps": [
            "ground_plane_fitting",
            "root_translation_one_euro_xz",
            "support_contact_detection",
        ],
        "supportProfile": support_profile,
        "footContacts": support_states,
        "reviewStatus": "needs_manual_review",
    }
    return MotionClip(
        fps=polished.fps,
        joint_names=polished.joint_names,
        frames=polished.frames,
        source=polished.source,
        metadata=metadata,
    ), stats


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
    deltas = [frame_motion_delta(clip.frames[index - 1], clip.frames[index]) for index in range(1, clip.frame_count)]
    active_indices = [index for index, delta in enumerate(deltas, start=1) if delta >= motion_threshold]
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


def ground_to_floor(
    clip: MotionClip,
    *,
    floor_height: float | None = None,
    support_states: list[dict[str, object]] | None = None,
) -> MotionClip:
    foot_joint_names = [joint for joint in DEFAULT_FOOT_JOINTS if joint in clip.joint_names]
    if not foot_joint_names:
        return clip
    if floor_height is None:
        candidates = estimate_support_floor_height(
            clip,
            support_states if support_states is not None else [],
        )
        if not math.isfinite(candidates):
            floor_height = min(
                frame.joints[joint][1]
                for frame in clip.frames
                for joint in foot_joint_names
            )
        else:
            floor_height = candidates
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


def stabilize_floor_contact(
    clip: MotionClip,
    *,
    root_joint: str,
    contact_states: list[dict[str, object]] | None = None,
    support_ground_y: float = 0.0,
) -> MotionClip:
    if clip.frame_count == 0:
        return clip
    support_joint_names = [joint for joint in DEFAULT_SUPPORT_JOINTS if joint in clip.joint_names]
    if not support_joint_names:
        return center_root_translation(clip, root_joint=root_joint)

    support_targets: dict[str, Point3] = {}
    supported_root_target: tuple[float, float] | None = None
    correction_x = 0.0
    correction_y = 0.0
    correction_z = 0.0
    previous_support_joint: str | None = None
    stabilized_frames = []
    for index, frame in enumerate(clip.frames):
        support_joint = choose_support_joint(
            clip,
            frame_index=index,
            support_joint_names=support_joint_names,
            contact_state=contact_states[index] if contact_states is not None and index < len(contact_states) else None,
        )
        if support_joint is not None:
            current_anchor = frame.joints[support_joint]
            current_root = frame.joints[root_joint]
            target = support_targets.get(support_joint)
            if target is None or previous_support_joint != support_joint:
                target = (
                    current_anchor[0] - correction_x,
                    support_ground_y,
                    current_anchor[2] - correction_z,
                )
                support_targets[support_joint] = target
            desired_correction_x = current_anchor[0] - target[0]
            desired_correction_y = current_anchor[1] - target[1]
            desired_correction_z = current_anchor[2] - target[2]
            correction_x = desired_correction_x
            correction_y = desired_correction_y
            correction_z = desired_correction_z
            supported_root_target = (
                current_root[0] - correction_x,
                current_root[2] - correction_z,
            )
        else:
            if supported_root_target is not None:
                current_root = frame.joints[root_joint]
                correction_x = current_root[0] - supported_root_target[0]
                correction_z = current_root[2] - supported_root_target[1]
            support_heights = [frame.joints[joint_name][1] for joint_name in support_joint_names]
            if support_heights:
                lowest_support_height = min(support_heights)
                excess_clearance = lowest_support_height - MAX_UNSUPPORTED_SUPPORT_CLEARANCE
                if excess_clearance > 0.0:
                    correction_y = max(correction_y, excess_clearance)
        stabilized_joints = {
            name: (coords[0] - correction_x, coords[1] - correction_y, coords[2] - correction_z)
            for name, coords in frame.joints.items()
        }
        stabilized_frames.append(MotionFrame(time_sec=frame.time_sec, joints=stabilized_joints))
        previous_support_joint = support_joint
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=stabilized_frames,
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
                support_heights.append(float(coords[1]))
    if not support_heights:
        return 0.0
    return percentile(support_heights, SUPPORT_GROUND_HEIGHT_QUANTILE)


def estimate_support_floor_height(
    clip: MotionClip,
    contact_states: list[dict[str, object]],
) -> float:
    support_joint_names = [joint for joint in DEFAULT_FOOT_JOINTS if joint in clip.joint_names]
    candidate_heights: list[float] = []
    if support_joint_names:
        for frame_index, frame in enumerate(clip.frames):
            state = contact_states[frame_index] if frame_index < len(contact_states) else None
            if isinstance(state, dict):
                for joint_name in iter_contact_joint_names(state):
                    point = frame.joints.get(joint_name)
                    if point is not None:
                        candidate_heights.append(float(point[1]))
            if not isinstance(state, dict) or not _support_state_has_ground_contact(state):
                for joint_name in support_joint_names:
                    point = frame.joints.get(joint_name)
                    if point is not None:
                        candidate_heights.append(float(point[1]))
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
            frame.joints[joint_name][1]
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
                target = (current_point[0], support_ground_y, current_point[2])
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


def stabilize_root_drift_by_support_segments(
    clip: MotionClip,
    *,
    contact_states: list[dict[str, object]],
    blend: float = SEGMENT_ROOT_STABILIZATION_BLEND,
    min_segment_frames: int = SEGMENT_ROOT_STABILIZATION_MIN_FRAMES,
) -> MotionClip:
    if clip.frame_count == 0 or not contact_states or blend <= 0.0:
        return clip

    adjusted_frames: list[MotionFrame] = list(clip.frames)
    frame_index = 0
    while frame_index < clip.frame_count:
        state = contact_states[frame_index] if frame_index < len(contact_states) else {}
        support_joint = state.get("supportJoint")
        if not isinstance(support_joint, str) or support_joint not in clip.joint_names:
            frame_index += 1
            continue

        segment_start = frame_index
        segment_end = frame_index + 1
        while segment_end < clip.frame_count:
            next_state = contact_states[segment_end] if segment_end < len(contact_states) else {}
            if next_state.get("state") == "airborne":
                break
            if next_state.get("supportJoint") != support_joint:
                break
            segment_end += 1

        if segment_end - segment_start >= min_segment_frames:
            anchor = adjusted_frames[segment_start].joints[support_joint]
            for index in range(segment_start + 1, segment_end):
                current_support = adjusted_frames[index].joints[support_joint]
                dx = (current_support[0] - anchor[0]) * blend
                dz = (current_support[2] - anchor[2]) * blend
                adjusted_joints = {
                    name: (coords[0] - dx, coords[1], coords[2] - dz)
                    for name, coords in adjusted_frames[index].joints.items()
                }
                adjusted_frames[index] = MotionFrame(
                    time_sec=adjusted_frames[index].time_sec,
                    joints=adjusted_joints,
                )

        frame_index = segment_end

    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=adjusted_frames,
        source=clip.source,
        metadata=clip.metadata,
    )


def center_root_translation(clip: MotionClip, *, root_joint: str) -> MotionClip:
    first_root = clip.frames[0].joints[root_joint]
    centered_frames = []
    for frame in clip.frames:
        root = frame.joints[root_joint]
        dx = root[0] - first_root[0]
        dz = root[2] - first_root[2]
        centered_joints = {
            name: (coords[0] - dx, coords[1], coords[2] - dz)
            for name, coords in frame.joints.items()
        }
        centered_frames.append(MotionFrame(time_sec=frame.time_sec, joints=centered_joints))
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=centered_frames,
        source=clip.source,
        metadata=clip.metadata,
    )


def smooth_clip(
    clip: MotionClip,
    *,
    min_cutoff: float,
    beta: float,
    derivative_cutoff: float,
) -> MotionClip:
    if clip.frame_count < 3:
        return clip
    smoothed_frames: list[MotionFrame] = []
    filter_state_by_joint: dict[str, tuple[Point3, Point3]] = {}
    for index, frame in enumerate(clip.frames):
        smoothed_joints: dict[str, Point3] = {}
        if index == 0:
            for joint_name in clip.joint_names:
                coords = frame.joints[joint_name]
                filter_state_by_joint[joint_name] = ((0.0, 0.0, 0.0), coords)
                smoothed_joints[joint_name] = coords
            smoothed_frames.append(MotionFrame(time_sec=frame.time_sec, joints=smoothed_joints))
            continue

        previous_time = clip.frames[index - 1].time_sec
        delta_time = max(frame.time_sec - previous_time, 1e-6)
        for joint_name in clip.joint_names:
            previous_derivative, previous_filtered = filter_state_by_joint[joint_name]
            filtered_point, filtered_derivative = one_euro_filter_point(
                current_point=frame.joints[joint_name],
                previous_filtered_point=previous_filtered,
                previous_filtered_derivative=previous_derivative,
                delta_time=delta_time,
                min_cutoff=min_cutoff_for_joint(joint_name, base_cutoff=min_cutoff),
                beta=one_euro_beta_for_joint(joint_name, base_beta=beta),
                derivative_cutoff=derivative_cutoff,
            )
            filter_state_by_joint[joint_name] = (filtered_derivative, filtered_point)
            smoothed_joints[joint_name] = filtered_point
        smoothed_frames.append(MotionFrame(time_sec=frame.time_sec, joints=smoothed_joints))
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=smoothed_frames,
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
def min_cutoff_for_joint(joint_name: str, *, base_cutoff: float) -> float:
    normalized = joint_name.lower()
    if normalized in {
        "pelvis",
        "spine",
        "spine1",
        "spine2",
        "spine3",
        "neck",
        "head",
    }:
        return base_cutoff * 0.75
    if any(token in normalized for token in ("ankle", "foot", "toe", "wrist", "hand")):
        return base_cutoff * 20.0
    return max(base_cutoff, 1e-5)


def one_euro_beta_for_joint(joint_name: str, *, base_beta: float) -> float:
    normalized = joint_name.lower()
    if normalized in {"pelvis", "spine", "spine1", "spine2", "spine3"}:
        return base_beta * 1.6
    if any(token in normalized for token in ("ankle", "foot", "toe")):
        return base_beta * 8.0
    if any(token in normalized for token in ("wrist", "hand")):
        return base_beta * 6.0
    return base_beta


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


def stabilize_spine_chain(
    clip: MotionClip,
    *,
    blend: float = SPINE_CHAIN_BLEND,
) -> MotionClip:
    if clip.frame_count == 0 or blend <= 0:
        return clip
    if "pelvis" not in clip.joint_names or "neck" not in clip.joint_names:
        return clip

    blend = min(max(blend, 0.0), 1.0)
    stabilized_frames: list[MotionFrame] = []
    for frame in clip.frames:
        pelvis = frame.joints.get("pelvis")
        neck = frame.joints.get("neck")
        if pelvis is None or neck is None:
            stabilized_frames.append(frame)
            continue
        adjusted_joints = dict(frame.joints)
        for joint_name, ratio in SPINE_CHAIN_RATIOS:
            joint = adjusted_joints.get(joint_name)
            if joint is None:
                continue
            target = (
                pelvis[0] + (neck[0] - pelvis[0]) * ratio,
                pelvis[1] + (neck[1] - pelvis[1]) * ratio,
                pelvis[2] + (neck[2] - pelvis[2]) * ratio,
            )
            adjusted_joints[joint_name] = (
                joint[0] * (1.0 - blend) + target[0] * blend,
                joint[1] * (1.0 - blend) + target[1] * blend,
                joint[2] * (1.0 - blend) + target[2] * blend,
            )
        stabilized_frames.append(MotionFrame(time_sec=frame.time_sec, joints=adjusted_joints))

    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=stabilized_frames,
        source=clip.source,
        metadata=clip.metadata,
    )


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


def choose_support_joint(
    clip: MotionClip,
    *,
    frame_index: int,
    support_joint_names: list[str],
    contact_state: dict[str, object] | None = None,
) -> str | None:
    if contact_state is not None:
        support_joint = contact_state.get("supportJoint") or contact_state.get("supportFoot")
        if isinstance(support_joint, str) and support_joint in support_joint_names:
            return support_joint
        if contact_state.get("state") == "airborne":
            return None
    contacting_joints = [
        joint_name
        for joint_name in support_joint_names
        if is_support_joint_in_contact(clip, frame_index=frame_index, joint_name=joint_name)
    ]
    if not contacting_joints:
        return None
    return min(
        contacting_joints,
        key=lambda joint_name: (
            horizontal_frame_speed(clip, frame_index=frame_index, joint_name=joint_name),
            clip.frames[frame_index].joints[joint_name][1],
        ),
    )


def is_support_joint_in_contact(clip: MotionClip, *, frame_index: int, joint_name: str) -> bool:
    support = clip.frames[frame_index].joints[joint_name]
    return support[1] <= contact_height_tolerance_for_joint(joint_name, was_in_contact=False)


def horizontal_frame_speed(clip: MotionClip, *, frame_index: int, joint_name: str) -> float:
    if clip.frame_count <= 1:
        return 0.0
    if frame_index <= 0:
        return horizontal_joint_distance(clip.frames[0], clip.frames[1], joint_name)
    return horizontal_joint_distance(clip.frames[frame_index - 1], clip.frames[frame_index], joint_name)


def detect_support_contact_states(clip: MotionClip) -> list[dict[str, object]]:
    states: list[dict[str, object]] = []
    left_joint = first_available_joint(clip, LEFT_FOOT_GROUP)
    right_joint = first_available_joint(clip, RIGHT_FOOT_GROUP)
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
                "leftHandJoint": left_hand_joint,
                "rightHandJoint": right_hand_joint,
                "leftInContact": left_contact,
                "rightInContact": right_contact,
                "leftHandInContact": left_hand_contact,
                "rightHandInContact": right_hand_contact,
                "supportJoint": support_joint,
                "supportFoot": support_joint,
                "state": state,
            }
        )
        previous_left = left_contact
        previous_right = right_contact
        previous_left_hand = left_hand_contact
        previous_right_hand = right_hand_contact
    return states


def iter_contact_joint_names(state: dict[str, object]) -> list[str]:
    joints: list[str] = []
    for flag_name, joint_name_field in (
        ("leftInContact", "leftFootJoint"),
        ("rightInContact", "rightFootJoint"),
        ("leftHandInContact", "leftHandJoint"),
        ("rightHandInContact", "rightHandJoint"),
    ):
        if state.get(flag_name):
            joint_name = state.get(joint_name_field)
            if isinstance(joint_name, str):
                joints.append(joint_name)
    return joints


def _support_state_has_ground_contact(state: dict[str, object]) -> bool:
    return bool(state.get("leftInContact")) or bool(state.get("rightInContact"))


def _summarize_support_states(states: list[dict[str, object]]) -> dict[str, object]:
    state_counts: dict[str, int] = {}
    left_foot_contacts = 0
    right_foot_contacts = 0
    left_hand_contacts = 0
    right_hand_contacts = 0
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
    if support[1] > height_tolerance:
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
