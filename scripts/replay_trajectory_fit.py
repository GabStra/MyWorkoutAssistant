#!/usr/bin/env python3
"""Replay one captured source-guided trajectory fit without pipeline stages."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exercise_motion_pkg.articulation_trajectory import fit_pose_and_temporal_trajectories
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.motion_io import save_motion_json


def _clip(payload: dict) -> MotionClip:
    return MotionClip(
        fps=float(payload["fps"]),
        joint_names=list(payload["joint_names"]),
        frames=[
            MotionFrame(
                float(frame["time_sec"]),
                {name: tuple(float(value) for value in point)
                 for name, point in frame["joints"].items()},
            )
            for frame in payload["frames"]
        ],
        source=dict(payload.get("source", {})),
        metadata=dict(payload.get("metadata", {})),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path, help="trajectory_fit_replay_v1 JSON")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        help="Override the captured fit budget for a short diagnostic replay",
    )
    parser.add_argument(
        "--max-evaluations",
        type=int,
        help="Override the captured maximum solver evaluations",
    )
    parser.add_argument(
        "--lsmr-max-iterations",
        type=int,
        help="Override the per-step LSMR iteration cap for a solver experiment",
    )
    parser.add_argument(
        "--lsmr-tolerance",
        type=float,
        help="Set the LSMR absolute and relative tolerances for a solver experiment",
    )
    parser.add_argument(
        "--x-scale",
        choices=("unit", "jac"),
        help="Override SciPy variable scaling for a solver experiment",
    )
    parser.add_argument(
        "--output-clip",
        type=Path,
        help="Optional path to save the fitted clip for downstream quality inspection",
    )
    args = parser.parse_args()
    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    if payload.get("schema") != "trajectory_fit_replay_v1":
        parser.error("unsupported replay artifact schema")
    options = dict(payload["solver_options"])
    if args.timeout_seconds is not None:
        options["timeout_seconds"] = args.timeout_seconds
    if args.max_evaluations is not None:
        options["max_evaluations"] = args.max_evaluations
    if args.lsmr_max_iterations is not None:
        options["lsmr_max_iterations"] = args.lsmr_max_iterations
    if args.lsmr_tolerance is not None:
        options["lsmr_tolerance"] = args.lsmr_tolerance
    if args.x_scale is not None:
        options["x_scale"] = "jac" if args.x_scale == "jac" else 1.0
    tuple_options = ("rigid_pair", "rigid_pair_reference", "rigid_distances", "projection_segments")
    for name in tuple_options:
        if options.get(name) is not None:
            options[name] = tuple(tuple(value) if isinstance(value, list) else value
                                  for value in options[name]) if name in {
                                      "rigid_distances", "projection_segments"
                                  } else tuple(options[name])
    started = time.perf_counter()
    fitted, report = fit_pose_and_temporal_trajectories(
        _clip(payload["source"]),
        _clip(payload["proposal"]),
        tuple(tuple(chain) for chain in payload["chains"]),
        **options,
    )
    if args.output_clip is not None:
        save_motion_json(args.output_clip, fitted)
    print(json.dumps({
        "elapsedSeconds": time.perf_counter() - started,
        "outputClip": str(args.output_clip.resolve()) if args.output_clip else None,
        "solverOptions": {
            "timeoutSeconds": options.get("timeout_seconds"),
            "maxEvaluations": options.get("max_evaluations"),
            "lsmrMaxIterations": options.get("lsmr_max_iterations", 100),
            "lsmrTolerance": options.get("lsmr_tolerance"),
            "xScale": options.get("x_scale", 1.0),
        },
        "report": report,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
