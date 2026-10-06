#!/usr/bin/env python3
"""Replay source-cut pose eligibility from a retained exact-pose reference."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.chunking import ChunkEstimate
from exercise_motion_pkg.segment_detection import DetectionWindow


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def source_pose_prefilter_payload(reference: dict[str, Any]) -> dict[str, Any]:
    pose = reference.get("pose", reference)
    frames = pose.get("frames")
    if not isinstance(frames, list) or len(frames) < 2:
        raise ValueError("Exact source-pose reference needs at least two frames")
    samples = []
    times = []
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get("joints"), dict):
            continue
        time_seconds = frame.get("sourceTimeSec")
        if not isinstance(time_seconds, (int, float)):
            continue
        times.append(float(time_seconds))
        confidence = frame.get("jointConfidence") or {}
        keypoints = {
            name: [point[0], point[1], confidence.get(name, 1.0)]
            for name, point in frame["joints"].items()
            if isinstance(point, (list, tuple)) and len(point) >= 2
        }
        samples.append({"timeSeconds": float(time_seconds), "keypoints": keypoints})
    if len(samples) < 2:
        raise ValueError("Exact source-pose reference has fewer than two timestamped frames")
    intervals = [later - earlier for earlier, later in zip(times, times[1:]) if later > earlier]
    sample_fps = 1.0 / statistics.median(intervals) if intervals else None
    return {
        "sampleFps": sample_fps,
        "dominantPoseSampleCoordinateSpace": pose.get("coordinateSpace", "normalized_image_xy"),
        "imageWidth": pose.get("imageWidth"),
        "imageHeight": pose.get("imageHeight"),
        "dominantPoseSamples": samples,
    }


def candidate_pose_payload(manifest: dict[str, Any], video_id: str) -> dict[str, Any]:
    expected_video_id = video_id.strip().casefold()
    for exercise in manifest.get("exercises") or []:
        if not isinstance(exercise, dict):
            continue
        for candidate in exercise.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("videoId") or "").strip().casefold() != expected_video_id:
                continue
            vision_payload = candidate.get("visionPayload")
            pose_payload = (
                vision_payload.get("posePrefilter")
                if isinstance(vision_payload, dict)
                else None
            )
            if isinstance(pose_payload, dict) and len(pose_payload.get("dominantPoseSamples") or []) >= 2:
                return pose_payload
            raise ValueError(f"Candidate {video_id} has no retained dominant-pose samples")
    raise ValueError(f"Video {video_id} is not present in the candidate manifest")


def chunk_estimate_from_selection(selection: dict[str, Any], exercise_name: str) -> ChunkEstimate | None:
    value = selection.get("chunkEstimate")
    if not isinstance(value, dict):
        return None
    return ChunkEstimate(
        exercise=exercise_name,
        rep_duration_min_sec=float(value.get("repDurationMinSec", 3.0)),
        rep_duration_max_sec=float(value.get("repDurationMaxSec", 10.0)),
        movement_complexity=str(value.get("movementComplexity") or "unknown"),
        chunk_seconds=float(value.get("chunkSeconds", 14.0)),
        chunk_overlap_seconds=float(value.get("chunkOverlapSeconds", 3.0)),
        source=str(value.get("source") or "retained_selection"),
        reason=str(value.get("reason") or ""),
    )


def replay_retained_candidate_pool(
    selection: dict[str, Any],
    manifest: dict[str, Any],
    *,
    video_id: str,
) -> dict[str, Any]:
    ranking = selection.get("sourceCutRanking")
    ranking_payload = ranking.get("payload") if isinstance(ranking, dict) else None
    if not isinstance(ranking_payload, dict):
        raise ValueError("Segment selection has no sourceCutRanking.payload")
    contract = ranking_payload.get("exerciseMotionContract") or selection.get("exerciseMotionContract")
    if not isinstance(contract, dict):
        raise ValueError("Segment selection has no retained exercise motion contract")
    exercise_name = str(contract.get("exerciseName") or selection.get("exerciseName") or "").strip()
    if not exercise_name:
        raise ValueError("Retained exercise name is missing")
    pose_payload = candidate_pose_payload(manifest, video_id)
    chunk_estimate = chunk_estimate_from_selection(selection, exercise_name)
    source_candidates = ranking_payload.get("sourceCutCandidates") or []
    saved_vlm_candidates = ranking_payload.get("sourceCutVlmInputCandidates") or []
    saved_vlm_ids = {
        str(item.get("candidateId"))
        for item in saved_vlm_candidates
        if isinstance(item, dict) and item.get("candidateId") is not None
    }
    eligible_ids: list[str] = []
    filtered_ids: list[str] = []
    render_skipped_ids: list[str] = []
    candidate_rows: list[dict[str, Any]] = []
    for item in source_candidates:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidateId") or "")
        start_seconds = float(item.get("startSeconds", 0.0))
        end_seconds = float(item.get("endSeconds", start_seconds))
        window = DetectionWindow(
            index=0,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        )
        saved_prefilter = item.get("posePrefilter")
        source_offset_seconds = (
            float(saved_prefilter.get("sourceOffsetSeconds", 0.0))
            if isinstance(saved_prefilter, dict)
            else 0.0
        )
        coverage = bake.source_cut_candidate_motion_coverage_metrics(
            candidate_window=window,
            pose_payload=pose_payload,
            exercise_name=exercise_name,
            chunk_estimate=chunk_estimate,
            exercise_motion_contract=contract,
            source_offset_seconds=source_offset_seconds,
        )
        candidate = bake.SourceCutCandidate(
            candidate_id=candidate_id,
            window=window,
            frame_paths=[Path("retained-source-candidate.jpg")],
            visual_integrity=item.get("visualIntegrity") or {},
            pose_prefilter=saved_prefilter if isinstance(saved_prefilter, dict) else {},
            motion_coverage=coverage,
            chunking=item.get("chunking") if isinstance(item.get("chunking"), dict) else {},
        )
        eligible = bake.source_cut_candidate_eligible_for_vlm(candidate)
        (eligible_ids if eligible else filtered_ids).append(candidate_id)
        phase = coverage.get("candidateFullRepetitionPhaseCompletenessMetrics") or {}
        regions = coverage.get("requiredRegionObservations") or {}
        render_skip_reason = bake.source_cut_candidate_render_skip_reason(coverage)
        if render_skip_reason is not None:
            render_skipped_ids.append(candidate_id)
        candidate_rows.append({
            "candidateId": candidate_id,
            "window": {"startSeconds": start_seconds, "endSeconds": end_seconds},
            "savedVlmInput": candidate_id in saved_vlm_ids,
            "currentVlmEligible": eligible,
            "phaseReason": phase.get("reason"),
            "phasePassed": phase.get("passed"),
            "requiredRegionsPassed": regions.get("passed"),
            "missingRegions": regions.get("missingRegions"),
            "renderSkipReason": render_skip_reason,
        })
    return {
        "segmentSelection": str(selection.get("selectedSegmentPath") or ""),
        "videoId": video_id,
        "exerciseName": exercise_name,
        "modelCalls": 0,
        "reconstructionRuns": 0,
        "retainedPoseSampleCount": len(pose_payload.get("dominantPoseSamples") or []),
        "materializedCandidateCount": len(source_candidates),
        "savedVlmInputIds": sorted(saved_vlm_ids),
        "savedVlmReviewedCandidateCount": ranking_payload.get("sourceCutVlmReviewedCandidateCount"),
        "savedVlmRequestCount": ranking_payload.get("sourceCutVlmReviewedRequestCount"),
        "savedVlmRequestPolicy": ranking_payload.get("sourceCutVlmRequestPolicy"),
        "savedSourceCutRenderSeconds": selection.get("sourceCutRenderSeconds"),
        "savedSourceCutVlmSeconds": selection.get("sourceCutVlmSeconds"),
        "savedExactConfirmationSeconds": ranking_payload.get("sourceCutDeterministicConfirmationSeconds"),
        "currentVlmEligibleIds": sorted(eligible_ids),
        "currentFilteredIds": sorted(filtered_ids),
        "currentRenderSkippedIds": sorted(render_skipped_ids),
        "currentRenderSkippedCount": len(render_skipped_ids),
        "savedVlmInputsFilteredNow": sorted(saved_vlm_ids - set(eligible_ids)),
        "currentEligibleButNotSaved": sorted(set(eligible_ids) - saved_vlm_ids),
        "candidateRows": candidate_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_pose", type=Path, nargs="?", help="Retained exact source-pose reference JSON")
    parser.add_argument("--contract", type=Path, help="Exercise motion contract JSON")
    parser.add_argument("--exercise-name")
    parser.add_argument("--segment-selection", type=Path,
                        help="Saved segment_selection.json with sourceCutCandidates")
    parser.add_argument("--candidate-manifest", type=Path,
                        help="Saved youtube_candidates.json or youtube_candidates.full.json")
    parser.add_argument("--video-id", help="Video ID whose cached pre-confirmation pose samples to replay")
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--end-seconds", type=float, help="Defaults to the saved pose duration")
    parser.add_argument("--kinematic", action="store_true", help="Use kinematic source-cut eligibility")
    args = parser.parse_args()

    if args.segment_selection is not None:
        if args.source_pose is not None or args.contract is not None:
            parser.error("--segment-selection mode cannot be combined with source_pose or --contract")
        if args.candidate_manifest is None or not args.video_id:
            parser.error("--segment-selection mode requires --candidate-manifest and --video-id")
        report = replay_retained_candidate_pool(
            load_json(args.segment_selection),
            load_json(args.candidate_manifest),
            video_id=args.video_id,
        )
        print(json.dumps(report, indent=2))
        return 0

    if args.source_pose is None or args.contract is None or not args.exercise_name:
        parser.error("exact-pose mode requires source_pose, --contract, and --exercise-name")

    reference = load_json(args.source_pose)
    pose = reference.get("pose", reference)
    prefilter_payload = source_pose_prefilter_payload(reference)
    contract_wrapper = load_json(args.contract)
    contract = contract_wrapper.get("exerciseMotionContract", contract_wrapper)
    frames = pose["frames"]
    pose_start = float(frames[0]["sourceTimeSec"])
    pose_end = float(frames[-1]["sourceTimeSec"])
    duration = max(0.0, pose_end - pose_start)
    end_seconds = duration if args.end_seconds is None else args.end_seconds
    if args.start_seconds < 0 or end_seconds <= args.start_seconds:
        parser.error("source-cut interval must have positive duration")
    window = DetectionWindow(0, args.start_seconds, end_seconds)
    coverage = bake.source_cut_candidate_motion_coverage_metrics(
        candidate_window=window,
        pose_payload=prefilter_payload,
        exercise_name=args.exercise_name,
        chunk_estimate=None,
        exercise_motion_contract=contract,
    )
    candidate = bake.SourceCutCandidate(
        candidate_id="retained-replay",
        window=window,
        frame_paths=[args.source_pose],
        visual_integrity={"passed": True},
        pose_prefilter=bake.source_cut_candidate_pose_prefilter_metrics(
            candidate_window=window,
            pose_payload=prefilter_payload,
        ),
        motion_coverage=coverage,
        chunking={"strategy": "kinematic_cycle"} if args.kinematic else {},
    )
    phase = coverage.get("candidateFullRepetitionPhaseCompletenessMetrics") or {}
    print(json.dumps({
        "sourcePose": str(args.source_pose.resolve()),
        "exerciseName": args.exercise_name,
        "sourcePoseFrames": len(prefilter_payload["dominantPoseSamples"]),
        "window": {"startSeconds": args.start_seconds, "endSeconds": end_seconds},
        "posePrefilter": {
            key: candidate.pose_prefilter.get(key)
            for key in ("enabled", "passed", "rejectionReasons", "bestPoseOverlapRatio")
        },
        "requiredRegionObservations": coverage.get("requiredRegionObservations"),
        "candidateRejectionReasons": coverage.get("rejectionReasons"),
        "phase": {key: phase.get(key) for key in
                  ("required", "passed", "reason", "hasCompleteMajorCycle", "hasReturnPhase")},
        "vlmEligible": bake.source_cut_candidate_eligible_for_vlm(candidate),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
