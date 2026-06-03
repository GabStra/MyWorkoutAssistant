from __future__ import annotations

import json
from dataclasses import dataclass
import math
from pathlib import Path

from exercise_motion_pkg.preview import _build_capsules
from exercise_motion_pkg.models import MotionClip, MotionFrame, Point3
from exercise_motion_pkg.motion_io import save_motion_json


@dataclass(frozen=True)
class PhysicsSimulationConfig:
    backend: str = "kinematic"
    root_alpha: float = 0.2
    torso_alpha: float = 0.24
    leg_alpha: float = 0.22
    arm_alpha: float = 0.14
    head_alpha: float = 0.12
    support_blend_frames: int = 6
    kinematic_iterations: int = 3
    playback_smoothing_window: int = 3
    loop_blend_frames: int = 6


@dataclass(frozen=True)
class PhysicsSimulationResult:
    simulated_motion_json_path: Path
    summary_json_path: Path
    preview_html_path: Path | None


def run_physics_simulation(
    *,
    bundle_dir: Path,
    output_motion_json: Path,
    config: PhysicsSimulationConfig = PhysicsSimulationConfig(),
) -> PhysicsSimulationResult:
    reference_payload = json.loads((bundle_dir / "reference_targets.json").read_text(encoding="utf-8"))
    controller_payload = json.loads((bundle_dir / "controller_config.json").read_text(encoding="utf-8"))
    if config.backend == "prototype":
        simulated_clip = _run_prototype_simulation(reference_payload, controller_payload, config=config)
        backend_note = "prototype"
    else:
        simulated_clip = _run_kinematic_simulation(reference_payload, controller_payload, config=config)
        backend_note = "kinematic"

    save_motion_json(output_motion_json, simulated_clip)
    summary_json_path = output_motion_json.with_name("sim_summary.json")
    summary_json_path.write_text(
        json.dumps(
            {
                "backend": backend_note,
                "frameCount": simulated_clip.frame_count,
                "fps": simulated_clip.fps,
                "durationSec": simulated_clip.duration_sec,
                "notes": [
                    "This consumes the physics bundle output and emits a deterministic refined motion clip.",
                    "The kinematic backend preserves major motion while enforcing bone-length and support constraints.",
                    "The previous MuJoCo path was removed because it did not produce a reliable result for this use case.",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return PhysicsSimulationResult(
        simulated_motion_json_path=output_motion_json,
        summary_json_path=summary_json_path,
        preview_html_path=None,
    )


def _run_prototype_simulation(
    reference_payload: dict[str, object],
    controller_payload: dict[str, object],
    *,
    config: PhysicsSimulationConfig,
) -> MotionClip:
    fps = float(reference_payload["fps"])
    root_joint = str(reference_payload["rootJoint"])
    joint_names = [str(name) for name in reference_payload["jointNames"]]
    source = {"physicsBundle": "prototype"}
    frames_payload = reference_payload["frames"]
    if not isinstance(frames_payload, list) or not frames_payload:
        raise ValueError("reference_targets.json does not contain any frames.")

    current_joints = {
        joint_name: _point3(frame0)
        for joint_name, frame0 in frames_payload[0]["effectors"].items()
    }
    current_joints[root_joint] = _point3(frames_payload[0]["rootPosition"])
    simulated_frames: list[MotionFrame] = []
    persistent_support_anchor: Point3 | None = None
    persistent_support_joint: str | None = None
    support_blend_remaining = 0

    for frame_payload in frames_payload:
        time_sec = float(frame_payload["timeSec"])
        target_root = _point3(frame_payload["rootPosition"])
        effectors = {
            str(joint_name): _point3(coords)
            for joint_name, coords in frame_payload["effectors"].items()
        }
        support_state = frame_payload.get("supportState") if isinstance(frame_payload, dict) else None

        next_joints = dict(current_joints)
        next_joints[root_joint] = _lerp_point(
            current_joints.get(root_joint, target_root),
            target_root,
            config.root_alpha,
        )
        for joint_name in joint_names:
            target = effectors.get(joint_name)
            if target is None and joint_name == root_joint:
                target = target_root
            if target is None:
                previous = next_joints.get(joint_name)
                if previous is not None:
                    next_joints[joint_name] = previous
                continue
            alpha = _joint_alpha(joint_name, controller_payload, config=config, root_joint=root_joint)
            next_joints[joint_name] = _lerp_point(next_joints.get(joint_name, target), target, alpha)

        support_joint = _support_joint_name(support_state)
        support_ground_y = _support_ground_y(reference_payload)
        if support_joint and support_joint in next_joints:
            support_target = next_joints[support_joint]
            if persistent_support_anchor is None or persistent_support_joint != support_joint:
                if persistent_support_anchor is None:
                    persistent_support_anchor = (support_target[0], support_ground_y, support_target[2])
                else:
                    support_blend_remaining = max(
                        config.support_blend_frames,
                        int(controller_payload.get("supportPolicy", {}).get("supportTransitionBlendFrames", config.support_blend_frames)),
                    )
                persistent_support_joint = support_joint
            if support_blend_remaining > 0 and persistent_support_anchor is not None:
                desired_anchor = (support_target[0], support_ground_y, support_target[2])
                persistent_support_anchor = _lerp_point(persistent_support_anchor, desired_anchor, 1.0 / support_blend_remaining)
                support_blend_remaining -= 1
            elif persistent_support_anchor is not None:
                persistent_support_anchor = (persistent_support_anchor[0], support_ground_y, persistent_support_anchor[2])

            if persistent_support_anchor is not None:
                correction = (
                    support_target[0] - persistent_support_anchor[0],
                    support_target[1] - persistent_support_anchor[1],
                    support_target[2] - persistent_support_anchor[2],
                )
                for joint_name, point in list(next_joints.items()):
                    next_joints[joint_name] = (
                        point[0] - correction[0],
                        point[1] - correction[1],
                        point[2] - correction[2],
                    )

        simulated_frames.append(MotionFrame(time_sec=time_sec, joints=next_joints))
        current_joints = next_joints

    metadata = {
        "physicsSim": {
            "backend": config.backend,
            "rootAlpha": config.root_alpha,
            "torsoAlpha": config.torso_alpha,
            "legAlpha": config.leg_alpha,
            "armAlpha": config.arm_alpha,
            "headAlpha": config.head_alpha,
            "supportBlendFrames": config.support_blend_frames,
        },
        "sourceReference": {
            "rootJoint": root_joint,
        },
    }
    return MotionClip(
        fps=fps,
        joint_names=joint_names,
        frames=simulated_frames,
        source=source,
        metadata=metadata,
    )


def _run_kinematic_simulation(
    reference_payload: dict[str, object],
    controller_payload: dict[str, object],
    *,
    config: PhysicsSimulationConfig,
) -> MotionClip:
    joint_names = [str(name) for name in reference_payload["jointNames"]]
    root_joint = str(reference_payload["rootJoint"])
    initial_pose_payload = reference_payload.get("initialPose", {})
    frames_payload = reference_payload.get("frames")
    if not isinstance(frames_payload, list) or not frames_payload:
        raise ValueError("reference_targets.json does not contain any frames.")
    initial_pose = {
        str(joint_name): _point3(coords)
        for joint_name, coords in initial_pose_payload.items()
    } if isinstance(initial_pose_payload, dict) else {}
    target_frames = [
        _reference_frame_to_joints(frame_payload, joint_names=joint_names, root_joint=root_joint)
        for frame_payload in frames_payload
    ]
    rest_pose = initial_pose or target_frames[0]
    target_clip = MotionClip(
        fps=float(reference_payload["fps"]),
        joint_names=joint_names,
        frames=[
            MotionFrame(time_sec=float(frame_payload["timeSec"]), joints=target_frames[index])
            for index, frame_payload in enumerate(frames_payload)
        ],
        source={"physicsBundle": "reference"},
        metadata={},
    )
    edges = _build_constraint_edges(target_clip)
    bone_lengths = _measure_bone_lengths(rest_pose=rest_pose, edges=edges)

    refined_frames: list[MotionFrame] = []
    current_joints = dict(rest_pose) if rest_pose else {}
    for frame_index, target_joints in enumerate(target_frames):
        time_sec = float(frames_payload[frame_index]["timeSec"])
        if frame_index == 0 and initial_pose:
            current_joints = dict(initial_pose)
            refined_frames.append(MotionFrame(time_sec=time_sec, joints=dict(current_joints)))
            continue
        blended = dict(current_joints)
        for joint_name, target in target_joints.items():
            if joint_name == root_joint:
                blended[joint_name] = target
                continue
            alpha = _kinematic_alpha_for_joint(
                joint_name,
                controller_payload=controller_payload,
                config=config,
                root_joint=root_joint,
            )
            blended[joint_name] = _lerp_point(blended.get(joint_name, target), target, alpha)
        refined_joints = _soft_enforce_bone_lengths(
            joints=blended,
            target_joints=target_joints,
            root_joint=root_joint,
            edges=edges,
            bone_lengths=bone_lengths,
            iterations=max(1, config.kinematic_iterations),
            blend=0.22,
        )
        current_joints = refined_joints
        refined_frames.append(MotionFrame(time_sec=time_sec, joints=dict(current_joints)))

    metadata = {
        "sourceReference": {
            "rootJoint": root_joint,
        }
    }
    physics_metadata = dict(metadata.get("physicsSim", {}))
    physics_metadata["backend"] = "kinematic"
    physics_metadata["kinematicIterations"] = config.kinematic_iterations
    physics_metadata["playbackSmoothingWindow"] = config.playback_smoothing_window
    physics_metadata["loopBlendFrames"] = config.loop_blend_frames
    metadata["physicsSim"] = physics_metadata
    refined_clip = MotionClip(
        fps=float(reference_payload["fps"]),
        joint_names=joint_names,
        frames=refined_frames,
        source={"physicsBundle": "kinematic"},
        metadata=metadata,
    )
    smoothed_clip = _postprocess_refined_clip(
        refined_clip,
        root_joint=root_joint,
        smoothing_window=config.playback_smoothing_window,
        loop_blend_frames=config.loop_blend_frames,
        support_states=[frame_payload.get("supportState") for frame_payload in frames_payload],
    )
    return smoothed_clip


def _joint_alpha(
    joint_name: str,
    controller_payload: dict[str, object],
    *,
    config: PhysicsSimulationConfig,
    root_joint: str,
) -> float:
    if joint_name == root_joint:
        return config.root_alpha
    if joint_name in {"spine1", "spine2", "spine3", "neck", "pelvis", "hips"}:
        return config.torso_alpha
    if joint_name in {"left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle", "left_foot", "right_foot"}:
        return config.leg_alpha
    if joint_name in {"left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hand", "right_hand"}:
        return config.arm_alpha
    if joint_name == "head":
        return config.head_alpha
    return config.torso_alpha


def _build_constraint_edges(clip: MotionClip) -> list[tuple[str, str]]:
    return [
        (str(capsule["start"]), str(capsule["end"]))
        for capsule in _build_capsules(clip)
    ]


def _measure_bone_lengths(
    *,
    rest_pose: dict[str, Point3],
    edges: list[tuple[str, str]],
) -> dict[tuple[str, str], float]:
    lengths: dict[tuple[str, str], float] = {}
    for start, end in edges:
        start_point = rest_pose.get(start)
        end_point = rest_pose.get(end)
        if start_point is None or end_point is None:
            continue
        lengths[(start, end)] = max(_point_distance(start_point, end_point), 1e-4)
    return lengths


def _enforce_bone_lengths(
    *,
    joints: dict[str, Point3],
    target_joints: dict[str, Point3],
    root_joint: str,
    edges: list[tuple[str, str]],
    bone_lengths: dict[tuple[str, str], float],
    iterations: int,
) -> dict[str, Point3]:
    adjusted = dict(joints)
    if root_joint in target_joints:
        adjusted[root_joint] = target_joints[root_joint]
    children_by_parent: dict[str, list[str]] = {}
    for parent, child in edges:
        children_by_parent.setdefault(parent, []).append(child)

    for _ in range(iterations):
        adjusted = _forward_length_pass(
            joints=adjusted,
            target_joints=target_joints,
            parent=root_joint,
            children_by_parent=children_by_parent,
            bone_lengths=bone_lengths,
        )
    return adjusted


def _reference_frame_to_joints(
    frame_payload: dict[str, object],
    *,
    joint_names: list[str],
    root_joint: str,
) -> dict[str, Point3]:
    joints_payload = frame_payload.get("joints")
    joints = {
        str(joint_name): _point3(coords)
        for joint_name, coords in joints_payload.items()
    } if isinstance(joints_payload, dict) else {}
    root_position = frame_payload.get("rootPosition")
    if root_joint not in joints and root_position is not None:
        joints[root_joint] = _point3(root_position)
    return {
        joint_name: joints[joint_name]
        for joint_name in joint_names
        if joint_name in joints
    }


def _kinematic_alpha_for_joint(
    joint_name: str,
    *,
    controller_payload: dict[str, object],
    config: PhysicsSimulationConfig,
    root_joint: str,
) -> float:
    if joint_name == root_joint:
        return 1.0
    base_alpha = _joint_alpha(joint_name, controller_payload, config=config, root_joint=root_joint)
    return min(max(base_alpha * 2.4, 0.0), 1.0)


def _soft_enforce_bone_lengths(
    *,
    joints: dict[str, Point3],
    target_joints: dict[str, Point3],
    root_joint: str,
    edges: list[tuple[str, str]],
    bone_lengths: dict[tuple[str, str], float],
    iterations: int,
    blend: float,
) -> dict[str, Point3]:
    adjusted = dict(joints)
    if root_joint in target_joints:
        adjusted[root_joint] = target_joints[root_joint]
    children_by_parent: dict[str, list[str]] = {}
    for parent, child in edges:
        children_by_parent.setdefault(parent, []).append(child)

    for _ in range(iterations):
        adjusted = _forward_soft_length_pass(
            joints=adjusted,
            target_joints=target_joints,
            parent=root_joint,
            children_by_parent=children_by_parent,
            bone_lengths=bone_lengths,
            blend=blend,
        )
    return adjusted


def _forward_soft_length_pass(
    *,
    joints: dict[str, Point3],
    target_joints: dict[str, Point3],
    parent: str,
    children_by_parent: dict[str, list[str]],
    bone_lengths: dict[tuple[str, str], float],
    blend: float,
) -> dict[str, Point3]:
    adjusted = dict(joints)
    parent_point = adjusted.get(parent)
    if parent_point is None:
        return adjusted
    for child in children_by_parent.get(parent, []):
        child_point = adjusted.get(child)
        target_point = target_joints.get(child)
        if child_point is None:
            child_point = target_point or parent_point
        target_direction_source = target_point or child_point
        direction = _normalize_vector((
            target_direction_source[0] - parent_point[0],
            target_direction_source[1] - parent_point[1],
            target_direction_source[2] - parent_point[2],
        ))
        if _vector_length(direction) < 1e-6:
            direction = _normalize_vector((
                child_point[0] - parent_point[0],
                child_point[1] - parent_point[1],
                child_point[2] - parent_point[2],
            ))
        if _vector_length(direction) < 1e-6:
            direction = (0.0, 1.0, 0.0)
        length = bone_lengths.get((parent, child))
        if length is None:
            continue
        projected_child = (
            parent_point[0] + direction[0] * length,
            parent_point[1] + direction[1] * length,
            parent_point[2] + direction[2] * length,
        )
        adjusted[child] = _lerp_point(child_point, projected_child, blend)
        adjusted = _forward_soft_length_pass(
            joints=adjusted,
            target_joints=target_joints,
            parent=child,
            children_by_parent=children_by_parent,
            bone_lengths=bone_lengths,
            blend=blend,
        )
    return adjusted


def _forward_length_pass(
    *,
    joints: dict[str, Point3],
    target_joints: dict[str, Point3],
    parent: str,
    children_by_parent: dict[str, list[str]],
    bone_lengths: dict[tuple[str, str], float],
) -> dict[str, Point3]:
    adjusted = dict(joints)
    parent_point = adjusted.get(parent)
    if parent_point is None:
        return adjusted
    for child in children_by_parent.get(parent, []):
        child_point = adjusted.get(child)
        target_point = target_joints.get(child)
        if child_point is None:
            child_point = target_point or parent_point
        target_direction_source = target_point or child_point
        direction = _normalize_vector((
            target_direction_source[0] - parent_point[0],
            target_direction_source[1] - parent_point[1],
            target_direction_source[2] - parent_point[2],
        ))
        if _vector_length(direction) < 1e-6:
            direction = _normalize_vector((
                child_point[0] - parent_point[0],
                child_point[1] - parent_point[1],
                child_point[2] - parent_point[2],
            ))
        if _vector_length(direction) < 1e-6:
            direction = (0.0, 1.0, 0.0)
        length = bone_lengths.get((parent, child))
        if length is None:
            continue
        adjusted[child] = (
            parent_point[0] + direction[0] * length,
            parent_point[1] + direction[1] * length,
            parent_point[2] + direction[2] * length,
        )
        adjusted = _forward_length_pass(
            joints=adjusted,
            target_joints=target_joints,
            parent=child,
            children_by_parent=children_by_parent,
            bone_lengths=bone_lengths,
        )
    return adjusted


def _support_ground_y(reference_payload: dict[str, object]) -> float:
    metadata = reference_payload.get("metadata", {})
    if not isinstance(metadata, dict):
        return 0.0
    cleanup = metadata.get("upstreamCleanupMetadata", {})
    if not isinstance(cleanup, dict):
        return 0.0
    raw = cleanup.get("supportGroundY", 0.0)
    return float(raw) if isinstance(raw, (int, float)) else 0.0


def _support_joint_name(support_state: object) -> str | None:
    if not isinstance(support_state, dict):
        return None
    raw = support_state.get("supportJoint")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw


def _postprocess_refined_clip(
    clip: MotionClip,
    *,
    root_joint: str,
    smoothing_window: int,
    loop_blend_frames: int,
    support_states: list[object] | None = None,
) -> MotionClip:
    first_frame = clip.frames[0] if clip.frames else None
    processed = clip
    if smoothing_window > 1:
        processed = _light_temporal_smooth(processed, root_joint=root_joint, window=smoothing_window)
    loop_seam = _detect_loop_seam(processed, root_joint=root_joint, support_states=support_states)
    if loop_seam is not None:
        processed = _trim_to_loop_seam(processed, start_index=loop_seam[0], end_index=loop_seam[1])
    if first_frame is not None and processed.frames and (loop_seam is None or loop_seam[0] == 0):
        frames = list(processed.frames)
        frames[0] = MotionFrame(time_sec=first_frame.time_sec, joints=dict(first_frame.joints))
        processed = MotionClip(
            fps=processed.fps,
            joint_names=processed.joint_names,
            frames=frames,
            source=processed.source,
            metadata=processed.metadata,
        )
    return processed


def _light_temporal_smooth(clip: MotionClip, *, root_joint: str, window: int) -> MotionClip:
    if clip.frame_count <= 2 or window <= 1:
        return clip
    radius = max(1, window // 2)
    smoothed_frames: list[MotionFrame] = []
    for frame_index, frame in enumerate(clip.frames):
        smoothed_joints: dict[str, Point3] = {}
        for joint_name in clip.joint_names:
            current = frame.joints.get(joint_name)
            if current is None:
                continue
            if joint_name == root_joint:
                smoothed_joints[joint_name] = current
                continue
            weighted_points: list[tuple[Point3, float]] = []
            for offset in range(-radius, radius + 1):
                neighbor_index = frame_index + offset
                if neighbor_index < 0 or neighbor_index >= clip.frame_count:
                    continue
                neighbor = clip.frames[neighbor_index].joints.get(joint_name)
                if neighbor is None:
                    continue
                weight = 1.0 / (1.0 + abs(offset))
                weighted_points.append((neighbor, weight))
            smoothed_joints[joint_name] = _weighted_average_point(weighted_points) if weighted_points else current
        smoothed_frames.append(MotionFrame(time_sec=frame.time_sec, joints=smoothed_joints))
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=smoothed_frames,
        source=clip.source,
        metadata=clip.metadata,
    )


def _detect_loop_seam(
    clip: MotionClip,
    *,
    root_joint: str,
    support_states: list[object] | None = None,
) -> tuple[int, int] | None:
    if clip.frame_count < 24:
        return None
    key_joints = [
        joint_name
        for joint_name in ("pelvis", "left_foot", "right_foot", "left_hand", "right_hand", "head")
        if joint_name in clip.joint_names
    ]
    if not key_joints:
        return None
    lag = _estimate_loop_period(
        clip,
        key_joints=key_joints,
        root_joint=root_joint,
        support_states=support_states,
    )
    if lag is None:
        return None
    lag_tolerance = max(2, min(8, lag // 8))
    best: tuple[float, int, int] | None = None
    for start_index in range(0, clip.frame_count - 1):
        for delta in range(-lag_tolerance, lag_tolerance + 1):
            end_index = start_index + lag + delta
            if end_index <= start_index or end_index >= clip.frame_count - 1:
                continue
            if not _loop_support_states_are_compatible(
                start_index=start_index,
                end_index=end_index,
                support_states=support_states,
            ):
                continue
            pose_mismatches = _loop_pose_mismatches(
                clip,
                start_index=start_index,
                end_index=end_index,
                key_joints=key_joints,
                root_joint=root_joint,
            )
            if not _loop_pose_mismatches_are_acceptable(pose_mismatches):
                continue
            pose_cost = _loop_pose_cost(
                pose_mismatches=pose_mismatches,
            )
            velocity_cost = _loop_velocity_cost(
                clip,
                start_index=start_index,
                end_index=end_index,
                key_joints=key_joints,
                root_joint=root_joint,
            )
            total_cost = pose_cost + velocity_cost * 0.75 + abs(delta) * 0.002
            if best is None or total_cost < best[0]:
                best = (total_cost, start_index, end_index)
    if best is None:
        return None
    _, start_index, end_index = best
    return (start_index, end_index)


def _estimate_loop_period(
    clip: MotionClip,
    *,
    key_joints: list[str],
    root_joint: str,
    support_states: list[object] | None = None,
) -> int | None:
    min_lag = max(12, int(round(clip.fps * 0.75)))
    max_lag = clip.frame_count - min_lag
    if max_lag <= min_lag:
        return None
    best: tuple[float, int] | None = None
    for lag in range(min_lag, max_lag + 1):
        local_costs: list[float] = []
        compatible_count = 0
        for start_index in range(0, clip.frame_count - lag):
            end_index = start_index + lag
            if not _loop_support_states_are_compatible(
                start_index=start_index,
                end_index=end_index,
                support_states=support_states,
            ):
                continue
            compatible_count += 1
            pose_mismatches = _loop_pose_mismatches(
                clip,
                start_index=start_index,
                end_index=end_index,
                key_joints=key_joints,
                root_joint=root_joint,
            )
            if not pose_mismatches:
                continue
            if not _loop_pose_mismatches_are_acceptable(
                pose_mismatches,
                mean_threshold=0.12,
                head_threshold=0.16,
                hand_threshold=0.18,
                foot_threshold=0.18,
            ):
                continue
            pose_cost = _loop_pose_cost(pose_mismatches=pose_mismatches)
            velocity_cost = _loop_velocity_cost(
                clip,
                start_index=start_index,
                end_index=end_index,
                key_joints=key_joints,
                root_joint=root_joint,
            )
            local_costs.append(pose_cost + velocity_cost * 0.75)
        total_candidates = max(1, clip.frame_count - lag)
        if compatible_count < max(6, total_candidates // 4):
            continue
        if len(local_costs) < max(4, compatible_count // 6):
            continue
        mean_cost = sum(local_costs) / len(local_costs)
        support_coverage = compatible_count / total_candidates
        score = mean_cost + (1.0 - support_coverage) * 0.1
        if best is None or score < best[0]:
            best = (score, lag)
    if best is None:
        return None
    score, lag = best
    if score > 0.08:
        return None
    return lag


def _loop_pose_cost(
    *,
    pose_mismatches: dict[str, float],
) -> float:
    distances = list(pose_mismatches.values())
    return sum(distances) / len(distances) if distances else float("inf")


def _loop_pose_mismatches(
    clip: MotionClip,
    *,
    start_index: int,
    end_index: int,
    key_joints: list[str],
    root_joint: str,
) -> dict[str, float]:
    start_frame = clip.frames[start_index]
    end_frame = clip.frames[end_index]
    start_root = start_frame.joints.get(root_joint)
    end_root = end_frame.joints.get(root_joint)
    if start_root is None or end_root is None:
        return {}
    mismatches: dict[str, float] = {}
    for joint_name in key_joints:
        if joint_name not in start_frame.joints or joint_name not in end_frame.joints:
            continue
        mismatches[joint_name] = _point_distance(
            _localize_point(start_frame.joints[joint_name], origin=start_root),
            _localize_point(end_frame.joints[joint_name], origin=end_root),
        )
    return mismatches


def _loop_pose_mismatches_are_acceptable(
    pose_mismatches: dict[str, float],
    *,
    mean_threshold: float = 0.18,
    head_threshold: float = 0.20,
    hand_threshold: float = 0.24,
    foot_threshold: float = 0.20,
) -> bool:
    if not pose_mismatches:
        return False
    mean_mismatch = sum(pose_mismatches.values()) / len(pose_mismatches)
    if mean_mismatch > mean_threshold:
        return False
    thresholds = {
        "head": head_threshold,
        "left_hand": hand_threshold,
        "right_hand": hand_threshold,
        "left_foot": foot_threshold,
        "right_foot": foot_threshold,
    }
    for joint_name, threshold in thresholds.items():
        value = pose_mismatches.get(joint_name)
        if value is not None and value > threshold:
            return False
    return True


def _loop_velocity_cost(
    clip: MotionClip,
    *,
    start_index: int,
    end_index: int,
    key_joints: list[str],
    root_joint: str,
) -> float:
    if start_index >= clip.frame_count - 1 or end_index <= 0:
        return float("inf")
    start_frame = clip.frames[start_index]
    next_start = clip.frames[start_index + 1]
    prev_end = clip.frames[end_index - 1]
    end_frame = clip.frames[end_index]
    start_root = start_frame.joints.get(root_joint)
    next_start_root = next_start.joints.get(root_joint)
    prev_end_root = prev_end.joints.get(root_joint)
    end_root = end_frame.joints.get(root_joint)
    if start_root is None or next_start_root is None or prev_end_root is None or end_root is None:
        return float("inf")
    distances = []
    for joint_name in key_joints:
        if (
            joint_name not in start_frame.joints
            or joint_name not in next_start.joints
            or joint_name not in prev_end.joints
            or joint_name not in end_frame.joints
        ):
            continue
        start_local = _localize_point(start_frame.joints[joint_name], origin=start_root)
        next_start_local = _localize_point(next_start.joints[joint_name], origin=next_start_root)
        prev_end_local = _localize_point(prev_end.joints[joint_name], origin=prev_end_root)
        end_local = _localize_point(end_frame.joints[joint_name], origin=end_root)
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
        distances.append(_vector_length((
            start_velocity[0] - end_velocity[0],
            start_velocity[1] - end_velocity[1],
            start_velocity[2] - end_velocity[2],
        )))
    return sum(distances) / len(distances) if distances else float("inf")


def _trim_to_loop_seam(clip: MotionClip, *, start_index: int, end_index: int) -> MotionClip:
    if start_index <= 0 and end_index >= clip.frame_count - 1:
        return clip
    sliced_frames = clip.frames[start_index:end_index + 1]
    rebased_frames = [
        MotionFrame(time_sec=index / clip.fps, joints=dict(frame.joints))
        for index, frame in enumerate(sliced_frames)
    ]
    metadata = dict(clip.metadata)
    physics_metadata = dict(metadata.get("physicsSim", {}))
    physics_metadata["loopSeamStartFrame"] = start_index
    physics_metadata["loopSeamEndFrame"] = end_index
    metadata["physicsSim"] = physics_metadata
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=rebased_frames,
        source=clip.source,
        metadata=metadata,
    )


def _localize_point(point: Point3, *, origin: Point3) -> Point3:
    return (
        point[0] - origin[0],
        point[1] - origin[1],
        point[2] - origin[2],
    )


def _loop_support_states_are_compatible(
    *,
    start_index: int,
    end_index: int,
    support_states: list[object] | None,
) -> bool:
    if not support_states:
        return True
    if start_index >= len(support_states) or end_index >= len(support_states):
        return True
    start_family = _support_state_family(support_states[start_index])
    end_family = _support_state_family(support_states[end_index])
    return start_family == end_family and start_family != "unknown"


def _support_state_family(support_state: object) -> str:
    if not isinstance(support_state, dict):
        return "unknown"
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
    if raw_state == "airborne":
        return "airborne"
    return "unknown"


def _apply_support_anchor_pass(
    frames: list[MotionFrame],
    *,
    support_states: list[object],
    support_ground_y: float,
    blend_frames: int,
) -> list[MotionFrame]:
    anchored_frames: list[MotionFrame] = []
    persistent_support_anchor: Point3 | None = None
    persistent_support_joint: str | None = None
    support_blend_remaining = 0

    for frame_index, frame in enumerate(frames):
        next_joints = dict(frame.joints)
        support_joint = _support_joint_name(support_states[frame_index] if frame_index < len(support_states) else None)
        if support_joint and support_joint in next_joints:
            support_target = next_joints[support_joint]
            if persistent_support_anchor is None or persistent_support_joint != support_joint:
                if persistent_support_anchor is None:
                    if frame_index == 0:
                        persistent_support_anchor = support_target
                    else:
                        persistent_support_anchor = (support_target[0], support_ground_y, support_target[2])
                else:
                    support_blend_remaining = max(1, blend_frames)
                persistent_support_joint = support_joint
            if support_blend_remaining > 0 and persistent_support_anchor is not None:
                desired_anchor = (support_target[0], support_ground_y, support_target[2])
                persistent_support_anchor = _lerp_point(
                    persistent_support_anchor,
                    desired_anchor,
                    1.0 / support_blend_remaining,
                )
                support_blend_remaining -= 1
            elif persistent_support_anchor is not None:
                persistent_support_anchor = (
                    persistent_support_anchor[0],
                    support_ground_y,
                    persistent_support_anchor[2],
                )

            if persistent_support_anchor is not None:
                correction = (
                    support_target[0] - persistent_support_anchor[0],
                    support_target[1] - persistent_support_anchor[1],
                    support_target[2] - persistent_support_anchor[2],
                )
                for joint_name, point in list(next_joints.items()):
                    next_joints[joint_name] = (
                        point[0] - correction[0],
                        point[1] - correction[1],
                        point[2] - correction[2],
                    )
        anchored_frames.append(MotionFrame(time_sec=frame.time_sec, joints=next_joints))
    return anchored_frames


def _lerp_point(start: Point3, end: Point3, alpha: float) -> Point3:
    clamped = min(max(alpha, 0.0), 1.0)
    return (
        start[0] * (1.0 - clamped) + end[0] * clamped,
        start[1] * (1.0 - clamped) + end[1] * clamped,
        start[2] * (1.0 - clamped) + end[2] * clamped,
    )


def _weighted_average_point(points: list[tuple[Point3, float]]) -> Point3:
    total_weight = sum(weight for _, weight in points)
    if total_weight <= 1e-8:
        return points[0][0]
    return (
        sum(point[0] * weight for point, weight in points) / total_weight,
        sum(point[1] * weight for point, weight in points) / total_weight,
        sum(point[2] * weight for point, weight in points) / total_weight,
    )


def _point3(value: object) -> Point3:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"Expected 3D point, got {value!r}")
    return (float(value[0]), float(value[1]), float(value[2]))


def _point_distance(a: Point3, b: Point3) -> float:
    return math.sqrt(
        (a[0] - b[0]) ** 2 +
        (a[1] - b[1]) ** 2 +
        (a[2] - b[2]) ** 2
    )


def _normalize_vector(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = _vector_length(vector)
    if length < 1e-6:
        return (0.0, 0.0, 0.0)
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _vector_length(vector: tuple[float, float, float]) -> float:
    return math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)
