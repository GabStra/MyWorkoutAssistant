from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from exercise_motion_pkg.models import MotionClip, MotionFrame, Point3


DEFAULT_EFFECTOR_JOINTS = (
    "left_foot",
    "right_foot",
    "left_hand",
    "right_hand",
    "left_knee",
    "right_knee",
    "left_elbow",
    "right_elbow",
    "head",
)
DEFAULT_ROOT_JOINT = "pelvis"
DEFAULT_SUPPORT_STATES_KEY = "footContacts"


@dataclass(frozen=True)
class PhysicsBundleConfig:
    root_joint: str = DEFAULT_ROOT_JOINT
    smoothing_window: int = 9
    root_smoothing_window: int = 13
    include_support_states: bool = True


@dataclass(frozen=True)
class PhysicsBundleResult:
    out_dir: Path
    reference_json_path: Path
    controller_config_path: Path
    summary_json_path: Path


def write_physics_bundle(
    *,
    clip: MotionClip,
    out_dir: Path,
    config: PhysicsBundleConfig = PhysicsBundleConfig(),
) -> PhysicsBundleResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    root_joint = config.root_joint if config.root_joint in clip.joint_names else _fallback_root_joint(clip)
    smoothed_clip = _smooth_reference_clip(
        clip,
        window=config.smoothing_window,
        root_joint=root_joint,
        root_window=config.root_smoothing_window,
    )
    reference_payload = _build_reference_payload(
        smoothed_clip,
        root_joint=root_joint,
        include_support_states=config.include_support_states,
        initial_pose=clip.frames[0].joints if clip.frames else {},
    )
    reference_json_path = out_dir / "reference_targets.json"
    reference_json_path.write_text(json.dumps(reference_payload, indent=2), encoding="utf-8")

    controller_config_path = out_dir / "controller_config.json"
    controller_config_path.write_text(json.dumps(_build_controller_config(), indent=2), encoding="utf-8")

    summary_json_path = out_dir / "summary.json"
    summary_json_path.write_text(
        json.dumps(
            {
                "rootJoint": root_joint,
                "frameCount": smoothed_clip.frame_count,
                "fps": smoothed_clip.fps,
                "durationSec": smoothed_clip.duration_sec,
                "effectors": _available_effectors(smoothed_clip),
                "supportStatesPresent": bool(_extract_support_states(smoothed_clip)),
                "notes": [
                    "This bundle is the bridge from cleaned recovered motion to deterministic kinematic refinement.",
                    "reference_targets.json is the smoothed target trajectory you should track first.",
                    "controller_config.json provides the deterministic kinematic refinement weights and support-policy hints.",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return PhysicsBundleResult(
        out_dir=out_dir,
        reference_json_path=reference_json_path,
        controller_config_path=controller_config_path,
        summary_json_path=summary_json_path,
    )


def _build_reference_payload(
    clip: MotionClip,
    *,
    root_joint: str,
    include_support_states: bool,
    initial_pose: dict[str, Point3] | None = None,
) -> dict[str, object]:
    joint_names = _ordered_unique_joint_names(clip.joint_names)
    support_states = _extract_support_states(clip) if include_support_states else []
    support_by_index = {int(item["frameIndex"]): item for item in support_states if isinstance(item, dict) and "frameIndex" in item}
    frames_payload: list[dict[str, object]] = []
    for frame_index, frame in enumerate(clip.frames):
        root_position = frame.joints.get(root_joint, (0.0, 0.0, 0.0))
        effectors = {
            joint_name: [coords[0], coords[1], coords[2]]
            for joint_name, coords in frame.joints.items()
            if joint_name in _available_effectors(clip)
        }
        frames_payload.append(
            {
                "frameIndex": frame_index,
                "timeSec": frame.time_sec,
                "rootPosition": [root_position[0], root_position[1], root_position[2]],
                "joints": {
                    joint_name: [coords[0], coords[1], coords[2]]
                    for joint_name, coords in frame.joints.items()
                    if joint_name in joint_names
                },
                "effectors": effectors,
                "supportState": support_by_index.get(frame_index),
            }
        )
    return {
        "schemaVersion": 1,
        "fps": clip.fps,
        "durationSec": clip.duration_sec,
        "rootJoint": root_joint,
        "jointNames": joint_names,
        "effectors": _available_effectors(clip),
        "initialPose": {
            joint_name: [coords[0], coords[1], coords[2]]
            for joint_name, coords in (initial_pose or {}).items()
            if joint_name in joint_names
        },
        "frames": frames_payload,
        "source": clip.source,
        "metadata": {
            "upstreamCleanupMetadata": clip.metadata.get("cleanup", {}) if isinstance(clip.metadata, dict) else {},
            "notes": [
                "Targets are intentionally smoothed to emphasize major motion over small jerk.",
                "Use supportState to decide whether feet or hands should be treated as planted during imitation.",
            ],
        },
    }


def _smooth_reference_clip(
    clip: MotionClip,
    *,
    window: int,
    root_joint: str,
    root_window: int,
) -> MotionClip:
    if clip.frame_count <= 1:
        return clip
    smoothed_frames: list[MotionFrame] = []
    root_window = max(window, root_window)
    for index, frame in enumerate(clip.frames):
        smoothed_joints: dict[str, Point3] = {}
        for joint_name in clip.joint_names:
            point = frame.joints.get(joint_name)
            if point is None:
                continue
            active_window = root_window if joint_name == root_joint else window
            smoothed_joints[joint_name] = _window_average(clip.frames, joint_name=joint_name, center_index=index, window=active_window)
        smoothed_frames.append(MotionFrame(time_sec=frame.time_sec, joints=smoothed_joints))
    metadata = dict(clip.metadata)
    metadata["physicsBundle"] = {
        "smoothingWindow": window,
        "rootSmoothingWindow": root_window,
        "intent": "major_motion_reference",
    }
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=smoothed_frames,
        source=clip.source,
        metadata=metadata,
    )


def _window_average(frames: list[MotionFrame], *, joint_name: str, center_index: int, window: int) -> Point3:
    radius = max(0, window // 2)
    start = max(0, center_index - radius)
    end = min(len(frames) - 1, center_index + radius)
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for index in range(start, end + 1):
        point = frames[index].joints.get(joint_name)
        if point is None:
            continue
        xs.append(point[0])
        ys.append(point[1])
        zs.append(point[2])
    if not xs:
        point = frames[center_index].joints[joint_name]
        return point
    count = float(len(xs))
    return (
        sum(xs) / count,
        sum(ys) / count,
        sum(zs) / count,
    )


def _extract_support_states(clip: MotionClip) -> list[dict[str, object]]:
    if not isinstance(clip.metadata, dict):
        return []
    cleanup = clip.metadata.get("cleanup")
    if not isinstance(cleanup, dict):
        return []
    states = cleanup.get(DEFAULT_SUPPORT_STATES_KEY)
    if not isinstance(states, list):
        return []
    return [item for item in states if isinstance(item, dict)]


def _available_effectors(clip: MotionClip) -> list[str]:
    return [joint_name for joint_name in DEFAULT_EFFECTOR_JOINTS if joint_name in clip.joint_names]


def _ordered_unique_joint_names(joint_names: list[str]) -> list[str]:
    return list(dict.fromkeys(joint_names))


def _fallback_root_joint(clip: MotionClip) -> str:
    for joint_name in ("pelvis", "hips", "root"):
        if joint_name in clip.joint_names:
            return joint_name
    raise ValueError("No supported root joint found in motion clip.")


def _build_controller_config() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "controllerType": "kinematic_constraint_refinement",
        "rootTracking": {
            "positionGain": 180.0,
            "velocityGain": 28.0,
        },
        "jointTracking": {
            "torso": {"kp": 240.0, "kd": 36.0, "weight": 1.0},
            "legs": {"kp": 220.0, "kd": 32.0, "weight": 0.95},
            "arms": {"kp": 160.0, "kd": 24.0, "weight": 0.7},
            "head": {"kp": 120.0, "kd": 18.0, "weight": 0.45},
        },
        "supportPolicy": {
            "useSupportStates": True,
            "doubleSupportMode": "support_centroid",
            "supportTransitionBlendFrames": 6,
        },
        "notes": [
            "Start by tracking root, torso, hands, and feet as soft targets rather than exact per-frame replication.",
            "Ignore tiny wrist and ankle jitter; the smoothed reference already suppresses that noise.",
            "Use supportState transitions to avoid anchor jumps when switching between hand and foot support.",
        ],
    }
