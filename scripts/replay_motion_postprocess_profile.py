#!/usr/bin/env python3
"""Replay saved motion through current postprocessing with a bounded fit profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import exercise_motion_pkg.articulation_trajectory as articulation_trajectory
from exercise_motion_pkg.bake_and_rank import pre_render_deterministic_gate
from exercise_motion_pkg.pipeline import GenerateRequest, run_generation_pipeline
from exercise_motion_pkg.structural_refinement import (
    SOURCE_GUIDED_TRAJECTORY_FIT_TIMEOUT_SECONDS,
)
from exercise_motion_pkg.video_world_alignment import load_source_pose_payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_motion(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("frames"), list):
        raise ValueError(f"Expected a normalized motion payload with frames: {path}")
    return payload


def _record_profile_in_capture(capture_path: Path, timeout_seconds: float, x_scale: str) -> None:
    if not capture_path.is_file():
        return
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    options = payload.get("solver_options")
    if not isinstance(options, dict):
        return
    options["timeout_seconds"] = timeout_seconds
    options["x_scale"] = "jac" if x_scale == "jac" else 1.0
    capture_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exercise-slug", required=True)
    parser.add_argument("--exercise-name")
    parser.add_argument("--raw-motion", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--source-pose", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--fit-timeout-seconds",
        type=float,
        default=SOURCE_GUIDED_TRAJECTORY_FIT_TIMEOUT_SECONDS,
    )
    parser.add_argument("--x-scale", choices=("unit", "jac"), default="unit")
    parser.add_argument("--rigid-paired-hands", action="store_true")
    parser.add_argument("--horizontal-torso-required", action="store_true")
    parser.add_argument("--support-mode-hint")
    args = parser.parse_args()

    raw_motion = args.raw_motion.expanduser().resolve()
    video = args.video.expanduser().resolve()
    source_pose_path = args.source_pose.expanduser().resolve()
    workspace = args.workspace.expanduser().resolve()
    for path in (raw_motion, video, source_pose_path):
        if not path.is_file():
            parser.error(f"Input file does not exist: {path}")
    if args.fit_timeout_seconds <= 0:
        parser.error("--fit-timeout-seconds must be positive")
    raw_payload = _load_motion(raw_motion)
    source_pose = load_source_pose_payload(source_pose_path)
    capture_path = workspace / "trajectory_fit_input.json"
    report_path = workspace / "postprocess_profile_replay.json"
    workspace.mkdir(parents=True, exist_ok=True)

    original_fit = articulation_trajectory.fit_pose_and_temporal_trajectories

    def profiled_fit(*fit_args: Any, **fit_kwargs: Any) -> Any:
        if fit_kwargs.get("timeout_seconds") == SOURCE_GUIDED_TRAJECTORY_FIT_TIMEOUT_SECONDS:
            fit_kwargs["timeout_seconds"] = args.fit_timeout_seconds
            fit_kwargs["x_scale"] = "jac" if args.x_scale == "jac" else 1.0
            _record_profile_in_capture(
                capture_path, fit_kwargs["timeout_seconds"], args.x_scale
            )
        return original_fit(*fit_args, **fit_kwargs)

    previous_capture = os.environ.get("EXERCISE_MOTION_TRAJECTORY_FIT_CAPTURE")
    os.environ["EXERCISE_MOTION_TRAJECTORY_FIT_CAPTURE"] = str(capture_path)
    articulation_trajectory.fit_pose_and_temporal_trajectories = profiled_fit
    started = perf_counter()
    try:
        result = run_generation_pipeline(
            GenerateRequest(
                exercise_slug=args.exercise_slug,
                workspace=workspace / "pipeline",
                video_path=video,
                normalized_motion_json=raw_motion,
                motion_reconstruction_backend="gvhmr",
                motion_tuning_enabled=True,
                structural_refinement_enabled=True,
                source_pose_reference_path=source_pose_path,
                rigid_paired_hands_required=args.rigid_paired_hands,
                horizontal_torso_required=args.horizontal_torso_required,
                support_mode_hint=args.support_mode_hint,
            )
        )
    finally:
        articulation_trajectory.fit_pose_and_temporal_trajectories = original_fit
        if previous_capture is None:
            os.environ.pop("EXERCISE_MOTION_TRAJECTORY_FIT_CAPTURE", None)
        else:
            os.environ["EXERCISE_MOTION_TRAJECTORY_FIT_CAPTURE"] = previous_capture

    cleaned_payload = _load_motion(result.cleaned_motion_json_path)
    gate = pre_render_deterministic_gate(
        cleaned_payload,
        source_pose,
        exercise_motion_contract={"exerciseName": args.exercise_name or args.exercise_slug},
        candidate_workspace=(workspace / "pipeline").resolve(),
        skeleton_path=result.wear_skeleton_json_path.resolve(),
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    report = {
        "schema": "motion_postprocess_profile_replay_v1",
        "profile": {
            "fitTimeoutSeconds": args.fit_timeout_seconds,
            "xScale": args.x_scale,
        },
        "inputs": {
            "rawMotion": str(raw_motion),
            "rawMotionSha256": _sha256(raw_motion),
            "video": str(video),
            "sourcePose": str(source_pose_path),
            "rawFrameCount": len(raw_payload["frames"]),
        },
        "elapsedSeconds": round(perf_counter() - started, 3),
        "stageTimings": manifest.get("timings", {}),
        "outputs": {
            "manifest": str(result.manifest_path.resolve()),
            "cleanedMotion": str(result.cleaned_motion_json_path.resolve()),
            "wearSkeleton": str(result.wear_skeleton_json_path.resolve()),
            "trajectoryFitInput": str(capture_path.resolve()) if capture_path.is_file() else None,
        },
        "modelCalls": 0,
        "reconstructionRuns": 0,
        "downloads": 0,
        "preRenderGate": gate,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if gate.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
