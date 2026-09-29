#!/usr/bin/env python3
"""Replay retained source-cut candidates with saved or production-style prompts."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from exercise_motion_pkg.bake_and_rank import (
    BakeAndRankRequest,
    LazyLlamaCppVisionSession,
    SourceCutCandidate,
    build_source_cut_candidate_batch_choice_prompt,
    build_llama_cpp_vision_settings,
    parse_source_cut_candidate_choice,
    two_scale_required_equipment_names,
)
from exercise_motion_pkg.segment_detection import DetectionWindow


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def cached_response_map(path: Path | None) -> dict[tuple[str, str], str]:
    if path is None:
        return {}
    report = load_json(path)
    result: dict[tuple[str, str], str] = {}
    cases = report.get("cases", [])
    if isinstance(cases, dict):
        cases = list(cases.values())
    for item in cases:
        if not isinstance(item, dict):
            continue
        video_id = str(item.get("videoId") or "").strip().casefold()
        candidate_id = str(item.get("candidateId") or "").strip().casefold()
        raw_response = item.get("rawResponse")
        if video_id and candidate_id and isinstance(raw_response, str):
            result[(video_id, candidate_id)] = raw_response
    return result


def selection_path_for_debug(path: Path) -> Path | None:
    """Find the selection manifest regardless of the retained debug nesting."""
    for parent in path.parents:
        selection_path = parent / "segment_selection.json"
        if selection_path.is_file():
            return selection_path
    return None


def debug_identity(path: Path, payload: dict[str, Any]) -> tuple[str, str]:
    candidate_id = str(payload.get("candidateId") or "").strip()
    workspace_name = ""
    selection_path = selection_path_for_debug(path)
    if selection_path is not None:
        selection = load_json(selection_path)
        source_video_path = selection.get("sourceVideoPath")
        if isinstance(source_video_path, str):
            workspace_name = Path(source_video_path).parent.parent.name
    match = re.search(r"-([A-Za-z0-9_-]{11})(?:-window(?:-\d+)?|$)", workspace_name, re.IGNORECASE)
    video_id = match.group(1) if match else path.parent.parent.name
    if not candidate_id or not video_id:
        raise ValueError(f"Cannot infer candidate/video identity from {path}")
    return video_id, candidate_id


def candidate_from_debug(payload: dict[str, Any], *, debug_path: Path) -> SourceCutCandidate:
    window = payload.get("window")
    if not isinstance(window, dict):
        raise ValueError(f"Missing source window in {debug_path}")
    start = float(window["startSeconds"])
    end = float(window["endSeconds"])
    if end <= start:
        raise ValueError(f"Invalid source window in {debug_path}")
    frame_paths = [Path(value) for value in payload.get("framePaths", [])]
    if not frame_paths or any(not path.is_file() for path in frame_paths):
        raise ValueError(f"Missing retained scorecard frames in {debug_path}")
    selection_path = selection_path_for_debug(debug_path)
    candidate_metadata: dict[str, Any] = {}
    if selection_path is not None:
        selection = load_json(selection_path)
        ranking = selection.get("sourceCutRanking")
        ranking_payload = ranking.get("payload") if isinstance(ranking, dict) else None
        source_candidates = (
            ranking_payload.get("sourceCutCandidates")
            if isinstance(ranking_payload, dict)
            else None
        )
        debug_candidate_id = str(payload.get("candidateId") or "").strip()
        candidate_metadata = next(
            (
                dict(row)
                for row in source_candidates or []
                if isinstance(row, dict)
                and str(row.get("candidateId") or "").strip() == debug_candidate_id
            ),
            {},
        )
    return SourceCutCandidate(
        candidate_id=str(payload["candidateId"]),
        window=DetectionWindow(0, start, end),
        frame_paths=frame_paths,
        boundary_audit_frame_paths=[Path(value) for value in payload.get("boundaryAuditFramePaths", [])],
        sample_frame_paths=[Path(value) for value in payload.get("sampleFramePaths", [])],
        visual_integrity=candidate_metadata.get("visualIntegrity") or {},
        pose_prefilter=candidate_metadata.get("posePrefilter") or {},
        motion_coverage=candidate_metadata.get("motionCoverage") or {},
        chunking=candidate_metadata.get("chunking") or {},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("debug", nargs="+", type=Path, help="Retained vlm_review_debug.json files")
    parser.add_argument("--contract", type=Path, required=True, help="Exercise motion contract JSON")
    parser.add_argument(
        "--cached-responses",
        type=Path,
        help="Reuse raw responses from a prior replay report; skips model startup and calls",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Review this many retained candidates in each production-style scorecard request",
    )
    parser.add_argument(
        "--simulate-exclusive-between-requests",
        action="store_true",
        help="Insert a no-op exclusive GPU boundary between live requests to measure ranker restart cost",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    if args.batch_size > 1 and args.cached_responses:
        parser.error("--cached-responses applies only to one-candidate parser replays")

    contract_wrapper = load_json(args.contract)
    contract = contract_wrapper.get("exerciseMotionContract", contract_wrapper)
    exercise_name = str(contract.get("exerciseName") or "").strip()
    if not exercise_name:
        parser.error("Contract is missing exerciseName")
    required_equipment = ", ".join(
        two_scale_required_equipment_names(exercise_name, contract)
    ) or "none"
    cached = cached_response_map(args.cached_responses)

    cases = []
    pending_live = []
    for debug_path in args.debug:
        payload = load_json(debug_path)
        video_id, candidate_id = debug_identity(debug_path, payload)
        candidate = candidate_from_debug(payload, debug_path=debug_path)
        cache_key = (video_id.casefold(), candidate_id.casefold())
        raw = cached.get(cache_key)
        if raw is None:
            pending_live.append((debug_path, payload, video_id, candidate_id, candidate))
            continue
        cases.append((debug_path, payload, video_id, candidate_id, candidate, raw, "cached"))

    settings = None
    vision_session = None
    if pending_live:
        settings_request = BakeAndRankRequest(
            candidates_json=args.contract.resolve(),
            workspace=REPOSITORY_ROOT / "build" / "exercise_motion",
            wham_repo_path=None,
            body_model_root=None,
        )
        settings = build_llama_cpp_vision_settings(settings_request)
        vision_session = LazyLlamaCppVisionSession(settings_request)

    live_calls = 0
    live_batches: list[list[tuple[Path, dict[str, Any], str, str, SourceCutCandidate]]] = []
    for start in range(0, len(pending_live), args.batch_size):
        batch = pending_live[start : start + args.batch_size]
        original_ids = [entry[3] for entry in batch]
        if args.batch_size > 1 and len(set(original_ids)) != len(original_ids):
            # Candidate letters repeat across retained videos. Assign unique
            # request-local ids while preserving the original ids in reports.
            batch = [
                (debug_path, payload, video_id, candidate_id,
                 replace(candidate, candidate_id=chr(ord("A") + index)))
                for index, (debug_path, payload, video_id, candidate_id, candidate)
                in enumerate(batch)
            ]
        live_batches.append(batch)
    try:
        for batch_index, batch in enumerate(live_batches):
            debug_path, payload, _, _, _ = batch[0]
            request_kwargs = payload.get("requestKwargs")
            if not isinstance(request_kwargs, dict):
                raise ValueError(f"Missing saved request options in {debug_path}")
            candidates = [entry[4] for entry in batch]
            if len(candidates) == 1:
                prompt_text = payload.get("prompt")
                if not isinstance(prompt_text, str):
                    raise ValueError(f"Missing saved prompt in {debug_path}")
            else:
                prompt_text = build_source_cut_candidate_batch_choice_prompt(
                    exercise_name=exercise_name,
                    candidate_title="retained source clips",
                    candidates=candidates,
                    exercise_motion_contract=contract,
                )
            request_started = time.perf_counter()
            raw = vision_session.caption_images(
                frame_paths=[path for candidate in candidates for path in candidate.frame_paths],
                prompt=prompt_text,
                **request_kwargs,
            )
            elapsed = time.perf_counter() - request_started
            live_calls += 1
            ranking = parse_source_cut_candidate_choice(
                raw,
                candidates,
                has_contract=True,
                exercise_motion_contract=contract,
                required_equipment=required_equipment,
                require_identity_evidence=True,
            )
            batch_scorecards = (
                (ranking.payload or {}).get("sourceCutScorecardCandidates", [])
                if ranking is not None
                else []
            )
            for case_debug_path, case_payload, video_id, original_candidate_id, candidate in batch:
                candidate_scorecard = next(
                    (
                        row for row in batch_scorecards
                        if isinstance(row, dict)
                        and str(row.get("id") or "").strip().casefold()
                        == candidate.candidate_id.casefold()
                    ),
                    None,
                )
                cases.append((
                    case_debug_path,
                    case_payload,
                    video_id,
                    original_candidate_id,
                    candidate,
                    raw,
                    "live_batch" if len(batch) > 1 else "live",
                    elapsed,
                    batch_index,
                    ranking,
                    candidate_scorecard,
                ))
            if (
                args.simulate_exclusive_between_requests
                and batch_index + 1 < len(live_batches)
            ):
                vision_session.run_without_llama_overlap(lambda: None)
    finally:
        if vision_session is not None:
            vision_session.close()

    vision_timing = vision_session.timing_manifest() if vision_session is not None else {}

    rows = []
    for case in cases:
        debug_path, payload, video_id, candidate_id, candidate, raw, response_source, *timing = case
        batch_index = timing[1] if len(timing) >= 4 else None
        ranking = timing[2] if len(timing) >= 4 else None
        scorecard = timing[3] if len(timing) >= 4 else None
        if ranking is None and response_source == "cached":
            ranking = parse_source_cut_candidate_choice(
                raw,
                [candidate],
                has_contract=True,
                exercise_motion_contract=contract,
                required_equipment=required_equipment,
                require_identity_evidence=True,
            )
            scorecard = next(
                iter((ranking.payload or {}).get("sourceCutScorecardCandidates", [])),
                None,
            ) if ranking is not None else None
        candidate_phase = candidate.motion_coverage.get(
            "candidateFullRepetitionPhaseCompletenessMetrics"
        )
        phase_evidence = None
        if isinstance(candidate_phase, dict):
            phase_evidence = {
                key: candidate_phase.get(key)
                for key in (
                    "passed",
                    "reason",
                    "majorPhaseSequence",
                    "dominantMotionRangeRatio",
                    "endpointPhaseDeltaRatio",
                )
                if candidate_phase.get(key) is not None
            }
        rows.append({
            "debugPath": str(debug_path.resolve()),
            "videoId": video_id,
            "candidateId": candidate_id,
            "phaseEvidence": phase_evidence,
            "requestCandidateId": candidate.candidate_id,
            "batchIndex": batch_index,
            "batchSize": sum(
                1 for entry in cases
                if len(entry) > 8 and entry[8] == batch_index
            ) if batch_index is not None else 1,
            "responseSource": response_source,
            "elapsedSeconds": round(float(timing[0]), 3) if timing else None,
            "parserAccepted": ranking is not None,
            "score": scorecard.get("score") if isinstance(scorecard, dict) else None,
            "batchScore": ranking.score if ranking is not None else None,
            "reasons": (
                scorecard.get("rejectionReasons") or []
                if isinstance(scorecard, dict)
                else ranking.reasons if ranking is not None
                else ["source_cut_scorecard_parse_failed"]
            ),
            "candidateVerdict": scorecard,
            "rawResponse": raw,
        })

    report = {
        "schema": "source_cut_scorecard_replay_v1",
        "exerciseName": exercise_name,
        "model": str(settings.llama_cpp_model) if settings is not None else None,
        "modelCalls": live_calls,
        "candidateCount": len(cases),
        "requestCount": live_calls,
        "batchSize": args.batch_size,
        "cachedResponses": sum(1 for case in cases if len(case) > 6 and case[6] == "cached"),
        "downloads": 0,
        "reconstructionRuns": 0,
        "serverStartupSeconds": vision_timing.get("visionRankerStartupSeconds", 0.0),
        "visionSessionTiming": vision_timing,
        "simulatedExclusiveBoundaries": (
            max(0, live_calls - 1) if args.simulate_exclusive_between_requests else 0
        ),
        "requiredEquipment": required_equipment,
        "cases": rows,
    }
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
