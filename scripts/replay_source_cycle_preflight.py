"""Replay source-confirmed cycle selection and optional bounded fitting offline."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from exercise_motion_pkg.bake_and_rank import (
    constrain_baked_payload_to_source_articulation,
    pre_render_deterministic_gate,
    source_validated_cycle_proposals,
)
from exercise_motion_pkg.controlled_motion import fit_controlled_motion
from exercise_motion_pkg.pose_fidelity import source_pose_reference_for_motion
from exercise_motion_pkg.sequence_stabilization import stabilize_exported_sequence


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def fit_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Keep the rejection evidence needed to compare bounded fit replays."""
    attempts = []
    for attempt in report.get("cycleSelectionAttempts", []):
        if not isinstance(attempt, dict):
            continue
        fit_report = attempt.get("fitReport")
        fit_report = fit_report if isinstance(fit_report, dict) else {}
        checks = fit_report.get("checks")
        checks = checks if isinstance(checks, dict) else {}
        attempts.append({
            "selection": attempt.get("selection"),
            "reason": attempt.get("reason"),
            "elapsedSeconds": attempt.get("elapsedSeconds"),
            "failedChecks": [name for name, passed in checks.items() if passed is False],
            "physicalReasons": fit_report.get("physicalReasons", []),
            "termination": fit_report.get("termination"),
            "optimizerTermination": fit_report.get("optimizerTermination"),
        })
    checks = report.get("checks")
    checks = checks if isinstance(checks, dict) else {}
    return {
        "applied": report.get("applied"),
        "reason": report.get("reason"),
        "failedChecks": [name for name, passed in checks.items() if passed is False],
        "physicalReasons": report.get("physicalReasons", []),
        "termination": report.get("termination"),
        "optimizerTermination": report.get("optimizerTermination"),
        "cycleRetryStopReason": report.get("cycleRetryStopReason"),
        "elapsedSeconds": report.get("elapsedSeconds"),
        "cycleSelectionAttempts": attempts,
    }


def run_production_constrained_fit(
    payload: dict[str, Any],
    source_pose: dict[str, Any],
    contract: dict[str, Any],
    *,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replay cycle fitting through the support-aware production constraint path."""
    started = perf_counter()
    fitted, articulation = constrain_baked_payload_to_source_articulation(
        deepcopy(payload),
        use_controlled_motion_fit=True,
        exercise_motion_contract=contract,
        source_pose_reference=source_pose,
        timeout_seconds=max(0.0, timeout_seconds),
    )
    elapsed = perf_counter() - started
    fit_report = fitted.get("controlledMotionFit")
    fit_report = fit_report if isinstance(fit_report, dict) else {}
    fitted_source_pose = source_pose_reference_for_motion(source_pose, fitted)
    gate = pre_render_deterministic_gate(
        fitted,
        fitted_source_pose,
        exercise_motion_contract=contract,
    )
    return fitted, {
        "fitWallSeconds": round(elapsed, 3),
        "fit": fit_report_summary(fit_report),
        "articulationConstraint": {
            "applied": articulation.get("applied"),
            "reason": articulation.get("reason"),
            "finalOwner": articulation.get("finalOwner"),
        },
        "preRenderGate": {
            "passed": gate.get("passed"),
            "rejectionReasons": gate.get("rejectionReasons"),
            "loopBridge": gate.get("loopBridge"),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description=(
            "Replay source-confirmed loop proposals from retained motion and source-pose "
            "artifacts; optional fitting is explicitly time-bounded. No VLM or reconstruction runs."
        )
    )
    parser.add_argument(
        "payload",
        type=Path,
        help=(
            "Cleaned motion JSON for selection or solver_only; production_constrained "
            "requires a baked skeleton with per-frame sourceJoints"
        ),
    )
    parser.add_argument("--source-pose", type=Path, required=True, help="Retained source-pose JSON")
    parser.add_argument("--contract", type=Path, required=True, help="Exercise motion contract JSON")
    parser.add_argument("--fit-timeout-seconds", type=float,
                        help="Optional hard wall-time cap for controlled fitting")
    parser.add_argument(
        "--fit-mode",
        choices=("solver_only", "production_constrained"),
        default="solver_only",
        help=(
            "solver_only runs the lower-level optimizer; production_constrained runs "
            "support/articulation setup and the production fit/gate path"
        ),
    )
    parser.add_argument("--output-clip", type=Path,
                        help="Optional path to save the fitted clip; requires --fit-timeout-seconds")
    parser.add_argument("--report", type=Path,
                        help="Optional path to save the replay report separately from --output-clip")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.output_clip and args.fit_timeout_seconds is None:
        parser.error("--output-clip requires --fit-timeout-seconds")
    if args.fit_mode == "production_constrained" and args.fit_timeout_seconds is None:
        parser.error("--fit-mode production_constrained requires --fit-timeout-seconds")

    payload = load_json(args.payload)
    if args.fit_mode == "production_constrained":
        frames = payload.get("frames")
        if not isinstance(frames, list) or not frames or any(
            not isinstance(frame, dict)
            or not isinstance(frame.get("sourceJoints"), dict)
            or not isinstance(frame.get("joints"), dict)
            for frame in frames
        ):
            parser.error(
                "production_constrained requires a baked skeleton with sourceJoints and joints on every frame"
            )
    source_wrapper = load_json(args.source_pose)
    source_pose = source_wrapper.get("pose", source_wrapper)
    if not isinstance(source_pose, dict):
        parser.error("Source-pose JSON must contain a pose object or pose fields directly")
    contract_wrapper = load_json(args.contract)
    contract = contract_wrapper.get("exerciseMotionContract", contract_wrapper)
    if not isinstance(contract, dict):
        parser.error("Contract JSON must contain an exercise motion contract object")

    started = perf_counter()
    proposals, preflight = source_validated_cycle_proposals(payload, source_pose, contract)
    report: dict[str, Any] = {
        "payload": str(args.payload.resolve()),
        "sourcePose": str(args.source_pose.resolve()),
        "exerciseName": contract.get("exerciseName"),
        "modelCalls": 0,
        "reconstructionRuns": 0,
        "proposalCount": len(proposals),
        "proposals": [
            {key: proposal.get(key) for key in
             ("startFrame", "stopFrameExclusive", "score", "endpointGapMeters")}
            for proposal in proposals
        ],
        "preflight": [
            {
                "passed": item.get("passed"),
                "selection": item.get("selection"),
                "sourceReason": (item.get("sourcePhase") or {}).get("reason"),
                "sourceSampleCount": (item.get("sourcePhase") or {}).get("sampleCount"),
                "outputReason": (item.get("outputPhase") or {}).get("reason"),
            }
            for item in preflight
        ],
    }

    if args.fit_mode == "production_constrained":
        fitted, production_report = run_production_constrained_fit(
            payload,
            source_pose,
            contract,
            timeout_seconds=args.fit_timeout_seconds,
        )
        report.update(production_report)
        if args.output_clip:
            args.output_clip.parent.mkdir(parents=True, exist_ok=True)
            args.output_clip.write_text(json.dumps(fitted, indent=2), encoding="utf-8")
            report["outputClip"] = str(args.output_clip.resolve())
    elif args.fit_timeout_seconds is not None:
        working = deepcopy(payload)
        working["loop"] = {**(working.get("loop") or {}), "enabled": True}
        working["observedCycleProposals"] = proposals
        working["sourceCyclePreflight"] = preflight
        fit_started = perf_counter()
        fitted, fit_report = fit_controlled_motion(
            working, timeout_seconds=max(0.0, args.fit_timeout_seconds)
        )
        report["fitWallSeconds"] = round(perf_counter() - fit_started, 3)
        report["fit"] = fit_report_summary(fit_report)
        if fit_report.get("applied"):
            fitted, stabilization = stabilize_exported_sequence(fitted)
            fitted["sequenceStabilization"] = stabilization
            fitted_source_pose = source_pose_reference_for_motion(source_pose, fitted)
            gate = pre_render_deterministic_gate(
                fitted, fitted_source_pose, exercise_motion_contract=contract
            )
            report["preRenderGate"] = {
                "passed": gate.get("passed"),
                "rejectionReasons": gate.get("rejectionReasons"),
                "loopBridge": gate.get("loopBridge"),
            }
            if args.output_clip:
                args.output_clip.parent.mkdir(parents=True, exist_ok=True)
                args.output_clip.write_text(json.dumps(fitted, indent=2), encoding="utf-8")
                report["outputClip"] = str(args.output_clip.resolve())

    report["elapsedSeconds"] = round(perf_counter() - started, 3)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
