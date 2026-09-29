#!/usr/bin/env python3
"""Replay controlled-motion fitting on a retained baked-motion payload."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from exercise_motion_pkg import controlled_motion


def _captured_cycle_selection(payload: dict[str, Any]) -> dict[str, Any]:
    fit_report = payload.get("controlledMotionFit")
    attempts = fit_report.get("cycleSelectionAttempts") if isinstance(fit_report, dict) else None
    if not isinstance(attempts, list):
        raise ValueError("Payload has no captured controlledMotionFit.cycleSelectionAttempts")
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        selection = attempt.get("selection")
        if (
            isinstance(selection, dict)
            and selection.get("kind") != "retained_interval"
            and isinstance(selection.get("startFrame"), int)
            and isinstance(selection.get("stopFrameExclusive"), int)
        ):
            return copy.deepcopy(selection)
    raise ValueError("Captured fit report has no source-cycle selection to replay")


def _prepare_payload(payload: dict[str, Any], *, captured_cycle: bool) -> tuple[dict[str, Any], dict[str, Any] | None]:
    replay_payload = copy.deepcopy(payload)
    if not captured_cycle:
        return replay_payload, None
    if replay_payload.get("fixedRig"):
        raise ValueError("Cannot replay a source-cycle fit from a fixed-rig payload")
    selection = _captured_cycle_selection(replay_payload)
    frame_count = len(replay_payload.get("frames") or [])
    start = selection["startFrame"]
    stop = selection["stopFrameExclusive"]
    if not (0 <= start < stop <= frame_count) or stop - start < 7:
        raise ValueError("Captured cycle selection falls outside the retained motion payload")
    fps = float(replay_payload.get("fps") or 30.0)
    replay_payload["loop"] = {
        **(replay_payload.get("loop") if isinstance(replay_payload.get("loop"), dict) else {}),
        "enabled": True,
        "startFrame": 0,
        "endFrame": max(0, frame_count - 1),
        "durationSec": frame_count / fps,
        "transition": "continuous",
        "label": "Retained full input for captured source-cycle replay",
    }
    replay_payload["observedCycleProposals"] = [selection]
    replay_payload.pop("loopCycleSelection", None)
    return replay_payload, selection


def _attempt_summary(report: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = report.get("cycleSelectionAttempts")
    if not isinstance(attempts, list):
        return []
    return [
        {
            "selection": attempt.get("selection"),
            "reason": attempt.get("reason"),
            "elapsedSeconds": attempt.get("elapsedSeconds"),
            "reportedFitElapsedSeconds": attempt.get("reportedFitElapsedSeconds"),
            "applied": (attempt.get("fitReport") or {}).get("applied"),
            "checks": attempt.get("checks"),
        }
        for attempt in attempts
        if isinstance(attempt, dict)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path, help="Retained baked-motion JSON")
    parser.add_argument("--timeout-seconds", type=float, help="Hard cap for this candidate fit")
    parser.add_argument("--max-evaluations", type=int, help="Optional optimizer evaluation cap")
    parser.add_argument(
        "--repeat-captured-cycle",
        action="store_true",
        help="Replay the first source-cycle interval recorded in controlledMotionFit",
    )
    parser.add_argument("--output-payload", type=Path, help="Optional path for the fitted motion payload")
    parser.add_argument("--output-report", type=Path, help="Optional path for the JSON replay report")
    args = parser.parse_args()

    input_bytes = args.payload.read_bytes()
    payload = json.loads(input_bytes)
    if not isinstance(payload, dict) or not isinstance(payload.get("frames"), list):
        parser.error("payload must be a baked-motion JSON object with frames")
    try:
        replay_payload, captured_selection = _prepare_payload(
            payload,
            captured_cycle=args.repeat_captured_cycle,
        )
    except ValueError as error:
        parser.error(str(error))

    started = time.perf_counter()
    fitted_payload, fit_report = controlled_motion.fit_controlled_motion(
        replay_payload,
        max_evaluations=args.max_evaluations,
        timeout_seconds=args.timeout_seconds,
    )
    elapsed = time.perf_counter() - started
    if args.output_payload:
        args.output_payload.parent.mkdir(parents=True, exist_ok=True)
        args.output_payload.write_text(json.dumps(fitted_payload, indent=2) + "\n", encoding="utf-8")

    report = {
        "schema": "controlled_motion_fit_replay_v1",
        "input": str(args.payload.resolve()),
        "inputSha256": hashlib.sha256(input_bytes).hexdigest(),
        "outputPayload": str(args.output_payload.resolve()) if args.output_payload else None,
        "exerciseName": str(payload.get("title") or payload.get("exerciseName") or ""),
        "inputFrameCount": len(payload["frames"]),
        "outputFrameCount": len(fitted_payload.get("frames") or []),
        "inputSpineFoldFrameRatio": controlled_motion.source_spine_fold_frame_ratio(payload),
        "repeatedCapturedCycle": args.repeat_captured_cycle,
        "capturedCycleSelection": captured_selection,
        "timeoutSeconds": args.timeout_seconds,
        "maxEvaluations": args.max_evaluations,
        "elapsedSeconds": round(elapsed, 3),
        "modelCalls": 0,
        "reconstructionRuns": 0,
        "applied": fit_report.get("applied"),
        "reason": fit_report.get("reason"),
        "retainedIntervalFit": fit_report.get("retainedIntervalFit"),
        "cycleRetryStopReason": fit_report.get("cycleRetryStopReason"),
        "reusedFit": fit_report.get("reused") is True,
        "attempts": [] if fit_report.get("reused") is True else _attempt_summary(fit_report),
        "retainedFitReportAttempts": (
            _attempt_summary(fit_report) if fit_report.get("reused") is True else []
        ),
        "fitReport": fit_report,
    }
    serialized = json.dumps(report, indent=2)
    if args.output_report:
        args.output_report.parent.mkdir(parents=True, exist_ok=True)
        args.output_report.write_text(serialized + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "fitReport"}, indent=2))
    # A rejected fit is a successful replay result; only malformed inputs or
    # runtime exceptions should produce a failing process exit code.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
