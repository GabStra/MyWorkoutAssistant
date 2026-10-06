"""Replay the deterministic pre-render gate on one retained motion artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from exercise_motion_pkg.bake_and_rank import pre_render_deterministic_gate


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def validate_motion_payload(payload: dict[str, Any], path: Path) -> None:
    """Reject report wrappers and incomplete exports before evaluating the gate."""
    frames = payload.get("frames")
    if not isinstance(frames, list) or len(frames) < 2:
        raise ValueError(f"Expected motion payload with at least two frames in {path}")
    joint_frames = sum(
        isinstance(frame, dict)
        and isinstance(frame.get("joints"), dict)
        and bool(frame["joints"])
        for frame in frames
    )
    if joint_frames < 2:
        raise ValueError(f"Expected at least two frames with joint coordinates in {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay only the deterministic pre-render gate on a saved motion payload; "
            "does not run reconstruction, model review, or rendering."
        )
    )
    parser.add_argument("payload", type=Path, help="Saved baked skeleton or exported motion JSON")
    parser.add_argument("--workspace", type=Path, required=True, help="Retained candidate workspace")
    parser.add_argument("--skeleton", type=Path, help="Executable/materialized skeleton, if separate")
    parser.add_argument("--source-pose", type=Path, help="Optional exact source-pose reference JSON")
    parser.add_argument("--contract", type=Path, help="Optional exercise-motion contract JSON")
    parser.add_argument("--exercise-name", help="Exercise name when no contract file is supplied")
    parser.add_argument("--output", type=Path, help="Optional path for the JSON replay report")
    args = parser.parse_args()

    payload = load_json(args.payload)
    try:
        validate_motion_payload(payload, args.payload)
    except ValueError as error:
        parser.error(str(error))
    source_pose = load_json(args.source_pose) if args.source_pose else None
    if source_pose and isinstance(source_pose.get("pose"), dict):
        source_pose = source_pose["pose"]
    contract = load_json(args.contract) if args.contract else None
    if contract is None and args.exercise_name:
        contract = {"exerciseName": args.exercise_name}

    started = perf_counter()
    gate = pre_render_deterministic_gate(
        payload,
        source_pose,
        exercise_motion_contract=contract,
        candidate_workspace=args.workspace.resolve(),
        skeleton_path=(args.skeleton or args.payload).resolve(),
    )
    report = {
        "payload": str(args.payload.resolve()),
        "workspace": str(args.workspace.resolve()),
        "elapsedSeconds": round(perf_counter() - started, 3),
        "gate": gate,
    }
    serialized = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
