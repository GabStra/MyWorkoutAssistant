"""Benchmark + decision-identity harness for structural refinement hot loops.

Builds a synthetic source-guided clip (realistic frame count, joint set, and a
2D source pose payload with a known camera), runs the full refinement chain,
and records every accept/reject transaction plus timing. Run before and after
hot-path changes; the transaction JSON must be byte-identical.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.structural_refinement import (
    _motion_noise_metrics,
    refine_motion_clip_structurally,
)

JOINTS = [
    "pelvis", "spine1", "spine2", "spine3", "neck", "head",
    "left_hip", "left_knee", "left_ankle", "left_foot",
    "right_hip", "right_knee", "right_ankle", "right_foot",
    "left_collar", "left_shoulder", "left_elbow", "left_wrist",
    "right_collar", "right_shoulder", "right_elbow", "right_wrist",
]

FRAME_COUNT = 150
FPS = 30.0


def _bone_lengths(rng):
    scale = 1.7
    return {
        "spine1": 0.12 * scale, "spine2": 0.12 * scale, "spine3": 0.12 * scale,
        "neck": 0.10 * scale, "head": 0.12 * scale,
        "left_knee": 0.44 * scale, "left_ankle": 0.44 * scale, "left_foot": 0.12 * scale,
        "right_knee": 0.44 * scale, "right_ankle": 0.44 * scale, "right_foot": 0.12 * scale,
        "left_shoulder": 0.18 * scale, "left_elbow": 0.28 * scale, "left_wrist": 0.26 * scale,
        "right_shoulder": 0.18 * scale, "right_elbow": 0.28 * scale, "right_wrist": 0.26 * scale,
    }


def build_clip(seed: int) -> tuple[MotionClip, dict]:
    rng = np.random.default_rng(seed)
    lengths = _bone_lengths(rng)
    times = [i / FPS for i in range(FRAME_COUNT)]
    # Squat-ish root travel plus limb angles that vary over time.
    root_y = 0.9 - 0.25 * np.sin(np.linspace(0, 2 * np.pi, FRAME_COUNT)) ** 2
    root_z = 0.1 * np.sin(np.linspace(0, np.pi, FRAME_COUNT))
    noise_sigma = 0.004
    frames = []
    chains = {
        "left_knee": ("left_hip", (0.1, -1.0, 0.0)),
        "right_knee": ("right_hip", (-0.1, -1.0, 0.0)),
        "left_shoulder": ("spine3", (0.2, 0.3, 0.0)),
        "right_shoulder": ("spine3", (-0.2, 0.3, 0.0)),
    }
    for i, t in enumerate(times):
        joints = {"pelvis": (0.0, float(root_y[i]), float(root_z[i]))}
        spine_point = np.array(joints["pelvis"], dtype=float)
        for name in ("spine1", "spine2", "spine3", "neck", "head"):
            spine_point = spine_point + [0, lengths[name], 0]
            joints[name] = tuple(float(v) for v in spine_point)
        for side, sign in (("left", 1.0), ("right", -1.0)):
            joints[f"{side}_hip"] = (
                float(root_z[i]) * 0.0 + joints["pelvis"][0] + sign * 0.09,
                joints["pelvis"][1] - 0.02,
                joints["pelvis"][2],
            )
            joints[f"{side}_collar"] = (
                joints["spine3"][0] + sign * 0.05,
                joints["spine3"][1] + 0.05,
                joints["spine3"][2],
            )
        for name, (parent, direction) in chains.items():
            point = np.array(joints[parent], dtype=float)
            angle = 0.5 * math.sin(t * 2.0 + (1 if "left" in name else -1)) + 0.3
            axis = np.array(direction, dtype=float)
            bend = np.array([0.0, math.cos(angle), math.sin(angle)])
            for segment in (name, {
                "left_knee": "left_ankle", "right_knee": "right_ankle",
                "left_shoulder": "left_elbow", "right_shoulder": "right_elbow",
            }[name]):
                point = point + bend * lengths.get(segment, 0.3)
                joints[segment] = tuple(float(v) for v in point)
            if name.endswith("knee"):
                point = point + bend * lengths["left_foot"]
                joints[name.replace("knee", "foot")] = tuple(float(v) for v in point)
            elif name.endswith("shoulder"):
                point = point + bend * lengths["left_wrist"]
                joints[name.replace("shoulder", "wrist")] = tuple(float(v) for v in point)
        # Add per-frame noise so denoising/smoothing proposals have signal.
        joints = {
            name: tuple(float(v) + float(rng.normal(0, noise_sigma)) for v in point)
            for name, point in joints.items()
        }
        frames.append(MotionFrame(time_sec=t, joints=joints))
    clip = MotionClip(fps=FPS, joint_names=list(JOINTS), frames=frames)

    # 2D source payload: project the noise-free motion through a fixed camera.
    rotation = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 0.92387953, -0.38268319],
        [0.0, 0.38268319, 0.92387953],
    ])
    source_frames = []
    for i, frame in enumerate(clip.frames):
        payload_joints = {}
        for name, point in frame.joints.items():
            camera = rotation @ np.asarray(point)
            payload_joints[name] = [
                float(camera[0]) * 0.8 + 0.5,
                float(-camera[1]) * 0.8 + 0.6,
            ]
        source_frames.append({
            "sourceTimeSec": frame.time_sec,
            "joints": payload_joints,
        })
    source_payload = {
        "frames": source_frames,
        "coordinateSpace": "pixel_xy",
        "imageWidth": 1080,
        "imageHeight": 1920,
    }
    return clip, source_payload


def main() -> None:
    clip, source_payload = build_clip(seed=7)
    noise = _motion_noise_metrics(clip, body_height=1.7)

    started = time.perf_counter()
    refined = refine_motion_clip_structurally(
        clip, source_pose_payload=source_payload,
        rigid_paired_hands_required=False, horizontal_torso_required=False)
    elapsed = time.perf_counter() - started

    noise_after = _motion_noise_metrics(refined, body_height=1.7)
    result = {
        "elapsedSeconds": round(elapsed, 3),
        "noiseBefore": noise,
        "noiseAfter": noise_after,
        "metadata": json.loads(json.dumps(refined.metadata, default=str)),
        "framesHash": hash(tuple(
            (f.time_sec,) + tuple(sorted(f.joints.items())) for f in refined.frames
        )),
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
