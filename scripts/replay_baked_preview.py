#!/usr/bin/env python3
"""Replay the retained browser-bake/fitting stage without rediscovery or reconstruction."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from time import perf_counter
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from exercise_motion_pkg.bake_and_rank import EligibleLoop, bake_preview_loops_with_playwright


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _exercise_contract(candidates_json: Path, exercise_id: str) -> dict[str, Any]:
    payload = _read_json(candidates_json)
    for exercise in payload.get("exercises", []):
        if isinstance(exercise, dict) and str(exercise.get("exerciseId")) == exercise_id:
            contract = exercise.get("exerciseMotionContract")
            if isinstance(contract, dict):
                return contract
    raise ValueError(f"No exercise-motion contract for exercise id {exercise_id} in {candidates_json}")


def _eligible_loops(manifest: dict[str, Any]) -> list[EligibleLoop]:
    loops = []
    for item in manifest.get("reviewSourceClips", []):
        if not isinstance(item, dict) or not isinstance(item.get("loop"), dict):
            continue
        loops.append(
            EligibleLoop(
                loop_index=int(item.get("loopIndex", -1)),
                loop=item["loop"],
                duration_sec=float(item.get("durationSec", 0.0)),
                start_seconds=float(item.get("startSeconds", 0.0)),
                end_seconds=float(item.get("endSeconds", 0.0)),
            )
        )
    if not loops:
        raise ValueError("Bake manifest has no retained eligible loops")
    return loops


def _copy_retained_inputs(source_workspace: Path, output_workspace: Path) -> None:
    selected_video = source_workspace / "input" / "selected_segment.mp4"
    source_pose = source_workspace / "segment_detection" / "exact_source_pose_reference.json"
    cleaned_motion = source_workspace / "cleaned" / "motion.cleaned.json"
    for path in (selected_video, source_pose, cleaned_motion):
        if not path.is_file():
            raise FileNotFoundError(f"Required retained bake input is missing: {path}")

    digest = hashlib.sha256(selected_video.read_bytes()).hexdigest()
    support_cache = (
        source_workspace
        / "segment_detection"
        / "body_support"
        / f"body-support-{digest}-v3.json"
    )
    if not support_cache.is_file():
        raise FileNotFoundError(
            "A matching body-support observation cache is required for a no-model replay: "
            f"{support_cache}"
        )

    for path in (selected_video, source_pose, cleaned_motion, support_cache):
        relative = path.relative_to(source_workspace)
        destination = output_workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _artifact_summary(artifact: Any) -> dict[str, Any]:
    payload = artifact.export_payload
    controlled = payload.get("controlledMotionFit") or {}
    budget = controlled.get("candidateFitBudget") or {}
    attempts = []
    for attempt in controlled.get("cycleSelectionAttempts", []):
        selection = attempt.get("selection") or {}
        fit_report = attempt.get("fitReport") or {}
        checks = fit_report.get("checks") or attempt.get("checks") or {}
        attempts.append(
            {
                "interval": [selection.get("startFrame"), selection.get("stopFrameExclusive")],
                "reason": attempt.get("reason"),
                "elapsedSeconds": attempt.get("elapsedSeconds"),
                "failedChecks": [name for name, passed in checks.items() if passed is False],
            }
        )
    gate = payload.get("preRenderDeterministicGate") or {}
    return {
        "loopIndex": artifact.loop_index,
        "settingsVariantId": artifact.settings_variant_id,
        "frameCount": len(payload.get("frames") or []),
        "controlledMotionApplied": controlled.get("applied"),
        "controlledMotionReason": controlled.get("reason"),
        "controlledMotionElapsedSeconds": controlled.get("elapsedSeconds"),
        "fitCalls": budget.get("fitCalls"),
        "cycleAttempts": attempts,
        "preRenderGatePassed": gate.get("passed"),
        "preRenderRejectionReasons": gate.get("rejectionReasons", []),
        "skeletonPath": str(artifact.skeleton_path.resolve()),
        "reviewVideoPath": str(artifact.review_video_path.resolve()),
        "reviewVideoExists": artifact.review_video_path.is_file(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bake_manifest", type=Path)
    parser.add_argument("candidates_json", type=Path)
    parser.add_argument("--workspace", type=Path, required=True, help="New isolated replay output workspace")
    parser.add_argument("--review-frames", type=int, default=12)
    parser.add_argument("--timeout-seconds", type=float, default=360.0)
    args = parser.parse_args()

    manifest_path = args.bake_manifest.expanduser().resolve()
    candidates_path = args.candidates_json.expanduser().resolve()
    output_workspace = args.workspace.expanduser().resolve()
    manifest = _read_json(manifest_path)
    source_workspace = Path(manifest["candidateWorkspace"]).expanduser().resolve()
    preview_html = Path(manifest["previewHtmlPath"]).expanduser().resolve()
    if not preview_html.is_file():
        parser.error(f"Retained preview HTML does not exist: {preview_html}")
    if output_workspace.exists() and any(output_workspace.iterdir()):
        parser.error(f"Replay workspace must be new or empty: {output_workspace}")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    _copy_retained_inputs(source_workspace, output_workspace)
    exercise_id = str(manifest.get("exerciseId") or "")
    contract = _exercise_contract(candidates_path, exercise_id)
    started = perf_counter()
    deadline = started + args.timeout_seconds
    artifacts = bake_preview_loops_with_playwright(
        preview_html,
        _eligible_loops(manifest),
        output_workspace,
        args.review_frames,
        adaptive_preview_settings=True,
        max_adaptive_preview_settings=1,
        exercise_name=str(manifest.get("exerciseName") or contract.get("exerciseName") or ""),
        exercise_motion_contract=contract,
        source_foot_support_evidence=manifest.get("sourceFootSupportEvidence"),
        deadline=deadline,
    )
    report = {
        "schema": "retained_baked_preview_replay_v1",
        "sourceBakeManifest": str(manifest_path),
        "sourceCandidateWorkspace": str(source_workspace),
        "previewHtml": str(preview_html),
        "outputWorkspace": str(output_workspace),
        "elapsedSeconds": round(perf_counter() - started, 3),
        "modelCalls": 0,
        "reconstructionRuns": 0,
        "downloads": 0,
        "artifacts": [_artifact_summary(artifact) for artifact in artifacts],
    }
    report_path = output_workspace / "baked_preview_replay.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
