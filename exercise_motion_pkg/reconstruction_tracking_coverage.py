from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np


MAX_TRACK_GAP_FRAMES = 2
MAX_STITCH_GAP_SECONDS = 0.35
MAX_BOUNDARY_CENTER_DISTANCE_SCALE = 1.25
MAX_BOUNDARY_KEYPOINT_DISTANCE_SCALE = 0.60
MAX_BOUNDARY_SCALE_RATIO = 1.75
MIN_REQUIRED_FRAME_COVERAGE = 0.95
MAX_DUPLICATE_POSE_DISTANCE_SCALE = 0.08


def overlapping_tracks_match(left, right, *, max_overlap_frames):
    """Require simultaneous identity evidence before joining duplicate track IDs."""
    left_frames, right_frames = track_frames(left), track_frames(right)
    if right_frames[0] <= left_frames[0] or right_frames[-1] <= left_frames[-1]:
        return False
    if left_frames[-1] - right_frames[0] + 1 > max_overlap_frames:
        return False
    common = sorted(set(left_frames) & set(right_frames))
    if len(common) < 2:
        return False
    left_pose = np.asarray(left.get('keypoints', []), dtype=float)
    right_pose = np.asarray(right.get('keypoints', []), dtype=float)
    left_boxes = np.asarray(left.get('bbox', []), dtype=float)
    right_boxes = np.asarray(right.get('bbox', []), dtype=float)
    if (left_pose.ndim != 3 or right_pose.ndim != 3
            or left_pose.shape[1:] != right_pose.shape[1:] or left_pose.shape[-1] < 3
            or left_pose.shape[0] != len(left_frames) or right_pose.shape[0] != len(right_frames)
            or left_boxes.ndim != 2 or right_boxes.ndim != 2
            or left_boxes.shape[1] < 3 or right_boxes.shape[1] < 3
            or len(left_boxes) != len(left_frames) or len(right_boxes) != len(right_frames)):
        return False
    left_indices, right_indices = ({frame: i for i, frame in enumerate(ids)}
                                   for ids in (left_frames, right_frames))
    for frame in common:
        li, ri = left_indices[frame], right_indices[frame]
        lb, rb = left_boxes[li, :3], right_boxes[ri, :3]
        if not np.isfinite(np.r_[lb, rb]).all() or min(lb[2], rb[2]) <= 0.:
            return False
        scale = min(lb[2], rb[2]) * 200.
        if max(lb[2], rb[2]) / min(lb[2], rb[2]) > 1.2:
            return False
        if np.linalg.norm(lb[:2] - rb[:2]) > scale * MAX_DUPLICATE_POSE_DISTANCE_SCALE:
            return False
        lp, rp = left_pose[li], right_pose[ri]
        visible = ((lp[:, 2] >= .3) & (rp[:, 2] >= .3)
                   & np.isfinite(lp[:, :3]).all(axis=1) & np.isfinite(rp[:, :3]).all(axis=1))
        if visible.sum() < 5:
            return False
        distances = np.linalg.norm(lp[visible, :2] - rp[visible, :2], axis=1)
        if np.percentile(distances, 90) > scale * MAX_DUPLICATE_POSE_DISTANCE_SCALE:
            return False
    return True


def track_frames(track: dict[str, Any]) -> list[int]:
    values = track.get("frame_id")
    if values is None:
        return []
    return [int(value) for value in values]


def track_boundary_bbox(track: dict[str, Any], *, first: bool) -> np.ndarray | None:
    values = track.get("bbox")
    if values is None or len(values) == 0:
        return None
    return np.asarray(values[0 if first else -1], dtype=np.float64)


def tracks_are_compatible(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    max_gap_frames: int,
) -> bool:
    left_frames = track_frames(left)
    right_frames = track_frames(right)
    if not left_frames or not right_frames:
        return False
    missing_frame_count = right_frames[0] - left_frames[-1] - 1
    if missing_frame_count < 0:
        return overlapping_tracks_match(left, right, max_overlap_frames=max(2, max_gap_frames))
    if missing_frame_count > max_gap_frames:
        return False
    left_bbox = track_boundary_bbox(left, first=False)
    right_bbox = track_boundary_bbox(right, first=True)
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


def best_compatible_chain(
    tracking_results: dict[Any, dict[str, Any]],
    *,
    max_gap_frames: int,
) -> list[tuple[Any, dict[str, Any]]]:
    ordered = sorted(
        ((track_id, track) for track_id, track in tracking_results.items() if track_frames(track)),
        key=lambda item: (track_frames(item[1])[0], -len(track_frames(item[1]))),
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
                if tracks_are_compatible(
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
                    abs(track_frames(item[1])[0] - track_frames(chain[-1][1])[-1]),
                    -track_frames(item[1])[-1],
                ),
            )
            chain.append(next_track)
            remaining = [item for item in remaining if item is not next_track]
        coverage = len({frame for _, track in chain for frame in track_frames(track)})
        if coverage > best_coverage:
            best = chain
            best_coverage = coverage
    return best


def stitch_track_chain(
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
            # Simultaneous duplicates were checked by the compatibility gate.
            # Keep each timestamp once; never stretch the output time axis.
            stitched[key] = np.concatenate((stitched[key], np.asarray(next_track[key])[right_frames > left_frame]), axis=0)

    merged_results = {
        track_id: track
        for track_id, track in tracking_results.items()
        if all(track_id != chained_id for chained_id, _track in chain[1:])
    }
    merged_results[chain[0][0]] = defaultdict(list, stitched)
    return merged_results, interpolated_frame_count


def tracking_coverage_report(
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
        required_end_frame = min(
            required_end_frame,
            max(required_start_frame, int(math.ceil(required_end_seconds * fps)) - 1),
        )
    required_frames = set(range(required_start_frame, required_end_frame + 1))
    chain = best_compatible_chain(
        tracking_results,
        max_gap_frames=MAX_TRACK_GAP_FRAMES,
    )
    covered_frames = {frame for _, track in chain for frame in track_frames(track)}
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
            if (frames := track_frames(track))
        ],
    }
