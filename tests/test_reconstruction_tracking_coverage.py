from __future__ import annotations

from collections import defaultdict

import numpy as np

from exercise_motion_pkg.reconstruction_tracking_coverage import (
    best_compatible_chain,
    stitch_track_chain,
    tracking_coverage_report,
)


def _track(start: int, end: int, *, center_x: float = 100.0) -> defaultdict[str, list]:
    frame_ids = np.arange(start, end + 1)
    frame_count = len(frame_ids)
    bbox = np.tile(np.array([center_x, 100.0, 1.0, 1.0]), (frame_count, 1))
    keypoints = np.zeros((frame_count, 17, 3), dtype=np.float32)
    keypoints[:, :, 0] = center_x
    keypoints[:, :, 1] = 100.0
    keypoints[:, :, 2] = 1.0
    return defaultdict(list, {"frame_id": frame_ids, "bbox": bbox, "keypoints": keypoints})


def test_tracking_coverage_requires_both_movement_boundaries() -> None:
    report = tracking_coverage_report(
        {1: _track(0, 80)},
        fps=30.0,
        frame_count=120,
        required_start_seconds=0.5,
        required_end_seconds=3.5,
    )

    assert report["passed"] is False
    assert report["startCovered"] is True
    assert report["endCovered"] is False


def test_short_overlapping_duplicate_tracks_require_pose_evidence_and_unique_frames():
    tracks = {0: _track(0, 227), 2: _track(226, 274)}
    chain = best_compatible_chain(tracks, max_gap_frames=11)
    assert [key for key, _ in chain] == [0, 2]
    merged, interpolated = stitch_track_chain(tracks, chain)
    assert interpolated == 0
    np.testing.assert_array_equal(merged[0]['frame_id'], np.arange(275))
    assert len(merged[0]['keypoints']) == len(merged[0]['bbox']) == 275
    assert tracking_coverage_report(merged, fps=30., frame_count=285,
                                   required_start_seconds=1.25, required_end_seconds=8.25)['passed']
    for variant in ('other_person', 'missing_pose', 'one_disagreeing_overlap'):
        other = _track(226, 274)
        if variant == 'other_person':
            other['keypoints'][:, :, 0] += 60.
        elif variant == 'missing_pose':
            other['keypoints'][:, :, 2] = 0.
        else:
            other['keypoints'][1, :, 0] += 60.
        rejected = best_compatible_chain({0: tracks[0], 2: other}, max_gap_frames=11)
        assert len(rejected) == 1


def test_compatible_short_track_fragments_are_stitched_and_revalidated() -> None:
    tracks = {1: _track(0, 44), 2: _track(46, 89)}
    chain = best_compatible_chain(tracks, max_gap_frames=10)
    stitched, interpolated = stitch_track_chain(tracks, chain)

    report = tracking_coverage_report(
        stitched,
        fps=30.0,
        frame_count=90,
        required_start_seconds=0.0,
        required_end_seconds=3.0,
    )

    assert interpolated == 1
    assert report["passed"] is True
    assert report["coverageRatio"] == 1.0

