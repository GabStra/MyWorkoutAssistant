from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import joblib
import numpy as np
import torch

sys.path.insert(0, str(Path.cwd()))

from configs.config import get_cfg_defaults
from lib.models.preproc.detector import DetectionModel
from lib.models.preproc.extractor import FeatureExtractor


MAX_TRACK_GAP_FRAMES = 2
MAX_STITCH_GAP_SECONDS = 0.35
MAX_BOUNDARY_CENTER_DISTANCE_SCALE = 1.25
MAX_BOUNDARY_KEYPOINT_DISTANCE_SCALE = 0.60
MAX_BOUNDARY_SCALE_RATIO = 1.75
MIN_REQUIRED_FRAME_COVERAGE = 0.95


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _track_frames(track: dict[str, Any]) -> list[int]:
    values = track.get("frame_id")
    if values is None:
        return []
    return [int(value) for value in values]


def _track_boundary_bbox(track: dict[str, Any], *, first: bool) -> np.ndarray | None:
    values = track.get("bbox")
    if values is None or len(values) == 0:
        return None
    return np.asarray(values[0 if first else -1], dtype=np.float64)


def _tracks_are_compatible(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    max_gap_frames: int,
) -> bool:
    left_frames = _track_frames(left)
    right_frames = _track_frames(right)
    if not left_frames or not right_frames:
        return False
    missing_frame_count = right_frames[0] - left_frames[-1] - 1
    if missing_frame_count < 0 or missing_frame_count > max_gap_frames:
        return False
    left_bbox = _track_boundary_bbox(left, first=False)
    right_bbox = _track_boundary_bbox(right, first=True)
    if left_bbox is None or right_bbox is None or len(left_bbox) < 3 or len(right_bbox) < 3:
        return False
    scale = max(float(left_bbox[2]), float(right_bbox[2]), 1e-6) * 200.0
    scale_ratio = max(float(left_bbox[2]), float(right_bbox[2])) / max(
        min(float(left_bbox[2]), float(right_bbox[2])),
        1e-6,
    )
    if scale_ratio > MAX_BOUNDARY_SCALE_RATIO:
        return False
    center_distance = math.hypot(float(left_bbox[0] - right_bbox[0]), float(left_bbox[1] - right_bbox[1]))
    if center_distance > scale * MAX_BOUNDARY_CENTER_DISTANCE_SCALE:
        return False
    left_keypoints = np.asarray(left.get("keypoints", []), dtype=np.float64)
    right_keypoints = np.asarray(right.get("keypoints", []), dtype=np.float64)
    if left_keypoints.ndim != 3 or right_keypoints.ndim != 3:
        return True
    left_boundary = left_keypoints[-1]
    right_boundary = right_keypoints[0]
    if left_boundary.shape != right_boundary.shape or left_boundary.shape[-1] < 3:
        return True
    visible = (left_boundary[:, 2] >= 0.3) & (right_boundary[:, 2] >= 0.3)
    if int(visible.sum()) < 5:
        return True
    keypoint_distance = float(
        np.median(np.linalg.norm(left_boundary[visible, :2] - right_boundary[visible, :2], axis=1))
    )
    return keypoint_distance <= scale * MAX_BOUNDARY_KEYPOINT_DISTANCE_SCALE


def _best_compatible_chain(
    tracking_results: dict[Any, dict[str, Any]],
    *,
    max_gap_frames: int,
) -> list[tuple[Any, dict[str, Any]]]:
    ordered = sorted(
        ((track_id, track) for track_id, track in tracking_results.items() if _track_frames(track)),
        key=lambda item: (_track_frames(item[1])[0], -len(_track_frames(item[1]))),
    )
    best: list[tuple[Any, dict[str, Any]]] = []
    best_coverage = -1
    for start_index, first in enumerate(ordered):
        chain = [first]
        remaining = ordered[start_index + 1 :]
        while True:
            candidates = [
                item
                for item in remaining
                if _tracks_are_compatible(
                    chain[-1][1],
                    item[1],
                    max_gap_frames=max_gap_frames,
                )
            ]
            if not candidates:
                break
            next_track = min(
                candidates,
                key=lambda item: (
                    abs(_track_frames(item[1])[0] - _track_frames(chain[-1][1])[-1]),
                    -_track_frames(item[1])[-1],
                ),
            )
            chain.append(next_track)
            remaining = [item for item in remaining if item is not next_track]
        coverage = len({frame for _, track in chain for frame in _track_frames(track)})
        if coverage > best_coverage:
            best = chain
            best_coverage = coverage
    return best


def _stitch_track_chain(
    tracking_results: dict[Any, dict[str, Any]],
    chain: list[tuple[Any, dict[str, Any]]],
) -> tuple[dict[Any, dict[str, Any]], int]:
    if len(chain) < 2:
        return tracking_results, 0
    stitched = {
        key: np.asarray(value).copy()
        for key, value in chain[0][1].items()
        if key in {"frame_id", "bbox", "keypoints"}
    }
    interpolated_frame_count = 0
    for _track_id, next_track in chain[1:]:
        left_frame = int(stitched["frame_id"][-1])
        right_frames = np.asarray(next_track["frame_id"])
        right_frame = int(right_frames[0])
        missing_frames = np.arange(left_frame + 1, right_frame, dtype=right_frames.dtype)
        if len(missing_frames):
            denominator = float(right_frame - left_frame)
            fractions = (missing_frames.astype(np.float64) - left_frame) / denominator
            for key in ("bbox", "keypoints"):
                left_value = np.asarray(stitched[key][-1], dtype=np.float64)
                right_value = np.asarray(next_track[key][0], dtype=np.float64)
                interpolated = np.stack(
                    [left_value + (right_value - left_value) * fraction for fraction in fractions]
                ).astype(np.asarray(stitched[key]).dtype, copy=False)
                stitched[key] = np.concatenate((stitched[key], interpolated), axis=0)
            stitched["frame_id"] = np.concatenate((stitched["frame_id"], missing_frames), axis=0)
            interpolated_frame_count += len(missing_frames)
        for key in ("frame_id", "bbox", "keypoints"):
            stitched[key] = np.concatenate((stitched[key], np.asarray(next_track[key])), axis=0)

    merged_results = {
        track_id: track
        for track_id, track in tracking_results.items()
        if all(track_id != chained_id for chained_id, _track in chain[1:])
    }
    merged_results[chain[0][0]] = defaultdict(list, stitched)
    return merged_results, interpolated_frame_count


def _coverage_report(
    tracking_results: dict[Any, dict[str, Any]],
    *,
    fps: float,
    frame_count: int,
    required_start_seconds: float | None,
    required_end_seconds: float | None,
) -> dict[str, Any]:
    required_start_frame = max(0, int(math.floor((required_start_seconds or 0.0) * fps)))
    required_end_frame = frame_count - 1
    if required_end_seconds is not None:
        required_end_frame = min(required_end_frame, max(required_start_frame, int(math.ceil(required_end_seconds * fps)) - 1))
    required_frames = set(range(required_start_frame, required_end_frame + 1))
    chain = _best_compatible_chain(
        tracking_results,
        max_gap_frames=MAX_TRACK_GAP_FRAMES,
    )
    covered_frames = {frame for _, track in chain for frame in _track_frames(track)}
    covered_required = required_frames & covered_frames
    missing_required = sorted(required_frames - covered_frames)
    coverage_ratio = len(covered_required) / max(1, len(required_frames))
    start_covered = any(abs(frame - required_start_frame) <= MAX_TRACK_GAP_FRAMES for frame in covered_frames)
    end_covered = any(abs(frame - required_end_frame) <= MAX_TRACK_GAP_FRAMES for frame in covered_frames)
    max_internal_gap = 0
    ordered_covered = sorted(covered_required)
    for left, right in zip(ordered_covered, ordered_covered[1:]):
        max_internal_gap = max(max_internal_gap, right - left - 1)
    passed = bool(
        chain
        and start_covered
        and end_covered
        and coverage_ratio >= MIN_REQUIRED_FRAME_COVERAGE
        and max_internal_gap <= MAX_TRACK_GAP_FRAMES
    )
    return {
        "schemaVersion": 1,
        "passed": passed,
        "fps": fps,
        "frameCount": frame_count,
        "requiredStartSeconds": required_start_seconds,
        "requiredEndSeconds": required_end_seconds,
        "requiredStartFrame": required_start_frame,
        "requiredEndFrame": required_end_frame,
        "requiredFrameCount": len(required_frames),
        "coveredRequiredFrameCount": len(covered_required),
        "coverageRatio": coverage_ratio,
        "startCovered": start_covered,
        "endCovered": end_covered,
        "maxInternalGapFrames": max_internal_gap,
        "missingRequiredFrameCount": len(missing_required),
        "firstMissingRequiredFrames": missing_required[:12],
        "selectedTrackIds": [str(track_id) for track_id, _ in chain],
        "tracks": [
            {
                "trackId": str(track_id),
                "startFrame": frames[0],
                "endFrame": frames[-1],
                "frameCount": len(frames),
            }
            for track_id, track in tracking_results.items()
            if (frames := _track_frames(track))
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--output-pth", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--required-start-seconds", type=float)
    parser.add_argument("--required-end-seconds", type=float)
    args = parser.parse_args()

    cfg = get_cfg_defaults()
    cfg.merge_from_file("configs/yamls/demo.yaml")
    video_path = Path(args.video)
    sequence_name = video_path.stem
    sequence_dir = Path(args.output_pth) / sequence_name
    sequence_dir.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    input_sha256 = _sha256(video_path)
    tracking_results_path = sequence_dir / "tracking_results.pth"
    slam_results_path = sequence_dir / "slam_results.pth"
    try:
        cached_report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cached_report = {}
    if (
        cached_report.get("passed") is True
        and cached_report.get("inputSha256") == input_sha256
        and cached_report.get("requiredStartSeconds") == args.required_start_seconds
        and cached_report.get("requiredEndSeconds") == args.required_end_seconds
        and tracking_results_path.is_file()
        and slam_results_path.is_file()
    ):
        return 0

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open preflight video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    detector = DetectionModel(cfg.DEVICE.lower())
    with torch.no_grad():
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                break
            detector.track(frame, fps, frame_count)
    cap.release()
    tracking_results = detector.process(fps)
    stitch_gap_frames = max(MAX_TRACK_GAP_FRAMES, int(math.ceil(fps * MAX_STITCH_GAP_SECONDS)))
    stitch_chain = _best_compatible_chain(
        tracking_results,
        max_gap_frames=stitch_gap_frames,
    )
    stitched_track_ids = [str(track_id) for track_id, _track in stitch_chain]
    tracking_results, interpolated_frame_count = _stitch_track_chain(
        tracking_results,
        stitch_chain,
    )
    report = _coverage_report(
        tracking_results,
        fps=fps,
        frame_count=frame_count,
        required_start_seconds=args.required_start_seconds,
        required_end_seconds=args.required_end_seconds,
    )
    report["stitchMaxGapFrames"] = stitch_gap_frames
    report["stitchedTrackIds"] = stitched_track_ids if len(stitched_track_ids) > 1 else []
    report["interpolatedTrackingFrameCount"] = interpolated_frame_count
    report["inputSha256"] = input_sha256
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        return 42

    with torch.no_grad():
        extractor = FeatureExtractor(cfg.DEVICE.lower(), cfg.FLIP_EVAL)
        tracking_results = extractor.run(str(video_path), tracking_results)
    slam_results = np.zeros((frame_count, 7))
    slam_results[:, 3] = 1.0
    joblib.dump(tracking_results, tracking_results_path)
    joblib.dump(slam_results, slam_results_path)
    report["reusablePreprocessingWritten"] = True
    report["trackingResultsPath"] = str(tracking_results_path)
    report["slamResultsPath"] = str(slam_results_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
