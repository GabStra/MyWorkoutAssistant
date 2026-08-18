from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from exercise_motion_pkg.wham_tracking_coverage import (
    best_compatible_chain,
    stitch_track_chain,
    tracking_coverage_report,
)
from exercise_motion_pkg.wham_warm_worker import process_job


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


def test_warm_worker_stops_before_reconstruction_when_preflight_rejects(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "jobs"
    results_dir = tmp_path / "results"
    logs_dir = tmp_path / "logs"
    for path in (jobs_dir, results_dir, logs_dir):
        path.mkdir()
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"video")
    output_root = tmp_path / "output"
    job_path = jobs_dir / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "jobId": "job",
                "video": str(video_path),
                "outputRoot": str(output_root),
                "trackingPreflight": True,
                "requiredStartSeconds": 1.0,
                "requiredEndSeconds": 3.0,
            }
        ),
        encoding="utf-8",
    )
    demo = SimpleNamespace(
        DetectionModel=object(),
        FeatureExtractor=object(),
        run=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("WHAM reconstruction should not run")
        ),
    )
    preflight_calls: list[dict] = []

    class FakePreflight:
        @staticmethod
        def run_tracking_preflight(**kwargs):
            preflight_calls.append(kwargs)
            return {"passed": False, "endCovered": False, "cacheStatus": "computed"}

    state = {
        "demo": demo,
        "cfg": object(),
        "network": object(),
        "trackingPreflight": FakePreflight,
        "loadSeconds": 1.0,
        "preprocessingLoadSeconds": lambda: 0.0,
    }

    process_job(job_path, results_dir, logs_dir, state)

    result = json.loads((results_dir / "job.json").read_text(encoding="utf-8"))
    assert result["status"] == "rejected_tracking_preflight"
    assert result["trackingPreflight"]["endCovered"] is False
    assert preflight_calls[0]["required_start_seconds"] == 1.0
    assert preflight_calls[0]["required_end_seconds"] == 3.0
