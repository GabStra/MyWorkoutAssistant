from __future__ import annotations

import json
from pathlib import Path

from exercise_motion_pkg.models import MotionClip, MotionFrame


def load_motion_json(path: Path) -> MotionClip:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "frames" in data:
        metadata = dict(data.get("metadata") or {})
        if data.get("kind") == "wearPreviewSkeleton":
            metadata["bakedWearPayload"] = {
                "kind": "wearPreviewSkeleton",
                "selectedPreviewSettings": data.get("selectedPreviewSettings") or {},
                "wearDisplay": data.get("wearDisplay") or {},
            }
        frames = [
            MotionFrame(
                time_sec=float(frame["timeSec"]),
                joints={name: _tuple3(coords) for name, coords in frame["joints"].items()},
            )
            for frame in data["frames"]
        ]
        joint_names = list(data.get("jointNames") or _derive_joint_names(frames))
        return MotionClip(
            fps=float(data["fps"]),
            joint_names=joint_names,
            frames=frames,
            source={str(k): str(v) for k, v in (data.get("source") or {}).items()},
            metadata=metadata,
        )
    if "positions" in data and "jointNames" in data:
        joint_names = [str(name) for name in data["jointNames"]]
        fps = float(data["fps"])
        frames: list[MotionFrame] = []
        for index, joint_positions in enumerate(data["positions"]):
            joints = {
                joint_names[joint_index]: _tuple3(coords)
                for joint_index, coords in enumerate(joint_positions)
            }
            frames.append(MotionFrame(time_sec=index / fps, joints=joints))
        return MotionClip(
            fps=fps,
            joint_names=joint_names,
            frames=frames,
            source={str(k): str(v) for k, v in (data.get("source") or {}).items()},
            metadata=data.get("metadata") or {},
        )
    raise ValueError(f"Unsupported motion JSON schema in {path}.")


def save_motion_json(path: Path, clip: MotionClip) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "fps": clip.fps,
        "jointNames": clip.joint_names,
        "frames": [
            {
                "timeSec": frame.time_sec,
                "joints": {
                    joint_name: [coords[0], coords[1], coords[2]]
                    for joint_name, coords in frame.joints.items()
                },
            }
            for frame in clip.frames
        ],
        "source": clip.source,
        "metadata": clip.metadata,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _tuple3(coords: list[float] | tuple[float, float, float]) -> tuple[float, float, float]:
    if len(coords) != 3:
        raise ValueError(f"Expected 3 coordinates, got {len(coords)}")
    return (float(coords[0]), float(coords[1]), float(coords[2]))


def _derive_joint_names(frames: list[MotionFrame]) -> list[str]:
    if not frames:
        return []
    return list(frames[0].joints.keys())
