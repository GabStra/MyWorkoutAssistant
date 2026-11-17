from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exercise_motion_pkg import source_frame_clock as clocks


def _write(path: Path, payload: bytes | dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _clock(*, source: Path, output: Path, source_sha: str, output_sha: str,
           crop_start: float, crop_end: float, frame_indices: list[int]) -> dict:
    fps = 2.0
    return {
        "schemaVersion": 2,
        "sourceVideoPath": str(source.resolve()),
        "sourceVideoSha256": source_sha,
        "sourceFps": fps,
        "sourceFrameCount": 20,
        "sourceOriginTimeSec": 0.0,
        "outputVideoPath": str(output.resolve()),
        "outputVideoSha256": output_sha,
        "outputFps": fps,
        "outputFrameCount": len(frame_indices),
        "cropStartSeconds": crop_start,
        "cropEndSeconds": crop_end,
        "sourcePtsVerification": {"timeBaseSec": 0.5},
        "outputPtsVerification": {"timeBaseSec": 0.5},
        "frames": [{
            "outputFrameIndex": index,
            "sourceFrameIndex": source_index,
            "sourceTimeSec": source_index / fps,
        } for index, source_index in enumerate(frame_indices)],
    }


def _workspace(tmp_path: Path, monkeypatch, *, wrong_review_parent: bool = False):
    workspace = tmp_path / "candidate"
    selected = workspace / "input" / "selected_segment.mp4"
    raw_source = tmp_path / "raw-source.mp4"
    selected_sha = _write(selected, b"selected cut bytes")
    raw_sha = _write(raw_source, b"raw source bytes")
    parent_clock = _clock(
        source=raw_source, output=selected, source_sha=raw_sha,
        output_sha=selected_sha, crop_start=1.0, crop_end=2.5,
        frame_indices=[2, 3, 4],
    )
    selected_clock_path = clocks.source_frame_clock_path_for_video(selected)
    selected_clock_sha = _write(selected_clock_path, parent_clock)
    manifest_clock = tmp_path / "original-cut.source_frame_clock.json"
    manifest_clock_sha = _write(manifest_clock, parent_clock)

    original_manifest = {
        "sourceIdentityVerified": True,
        "sourcePath": str(raw_source.resolve()),
        "sourceSha256": raw_sha,
        "sourceFramesHalfOpen": [2, 5],
        "sourceSeconds": [1.0, 2.5],
        "sourceFps": 2.0,
        "outputFrameCount": 3,
        "candidateVideo": str(selected.resolve()),
        "candidateVideoSha256": selected_sha,
        "clockPath": str(manifest_clock.resolve()),
        "clockSha256": manifest_clock_sha,
        "clockSourceSha256": raw_sha,
        "clockFirst": parent_clock["frames"][0],
        "clockLast": parent_clock["frames"][-1],
    }
    manifest_path = tmp_path / "original-candidate-window.json"
    manifest_sha = _write(manifest_path, original_manifest)
    review = {
        "selectedCutPath": str(selected.resolve()),
        "selectedCutSha256": selected_sha,
        "parentChunkPath": str(selected.resolve()),
        "parentChunkSha256": selected_sha,
        "rawSourcePath": str(raw_source.resolve()),
        "rawSourceSha256": "0" * 64 if wrong_review_parent else raw_sha,
        "sourceFrameClockPath": str(selected_clock_path.resolve()),
        "sourceFrameClockSha256": selected_clock_sha,
        "phasePassed": True,
        "selectedStart": 0.0,
        "selectedEnd": 1.5,
    }
    review_path = tmp_path / "current-review.json"
    review_sha = _write(review_path, review)
    selection = {
        "selectedSegmentPath": str(selected.resolve()),
        "selectedSegmentSha256": selected_sha,
        "sourceVideoPath": str(raw_source.resolve()),
        "selectedSpanInOriginalSource": {"startSeconds": 0.0, "endSeconds": 1.5},
        "sourceAttemptProvenance": {
            "originalManifestPath": str(manifest_path.resolve()),
            "originalManifestSha256": manifest_sha,
            "currentReviewReceipt": str(review_path.resolve()),
            "currentReviewReceiptSha256": review_sha,
        },
    }
    selection_path = workspace / "segment_detection" / "segment_selection.json"
    _write(selection_path, selection)
    reference_path = workspace / "segment_detection" / "exact_source_pose_reference.json"
    _write(reference_path, {"sourceVideoSha256": selected_sha})

    def verified_clock(path: Path, *, expected_video_path=None):
        resolved = path.resolve()
        if resolved == selected_clock_path.resolve():
            assert expected_video_path.resolve() == selected.resolve()
            return parent_clock
        if resolved == manifest_clock.resolve():
            assert expected_video_path.resolve() == selected.resolve()
            return parent_clock
        raise AssertionError(f"unexpected clock request: {resolved}")

    monkeypatch.setattr(clocks, "load_verified_source_frame_clock", verified_clock)
    return workspace, selected, raw_source, selected_sha, raw_sha, parent_clock, selected_clock_sha


def test_nested_materialized_cut_maps_local_review_to_verified_parent_clock(tmp_path, monkeypatch):
    (workspace, selected, _raw, selected_sha, raw_sha,
     parent_clock, _clock_sha) = _workspace(tmp_path, monkeypatch)
    mapping = clocks.verified_source_timeline_mapping(
        workspace=workspace,
        source_pose={
            "sourceTimeOriginSec": 0.0,
            "frames": [{"sourceTimeSec": 0.0}, {"sourceTimeSec": 0.5}],
        },
        clock_receipt=parent_clock,
        expected_motion_video_path=selected,
    )

    assert mapping is not None
    assert mapping["selectedStartSeconds"] == 1.0
    assert mapping["selectedEndSeconds"] == 2.5
    assert mapping["parentSourceSha256"] == raw_sha
    assert mapping["selectedSegmentSha256"] == selected_sha
    assert mapping["nestedMaterialization"]["localStartSeconds"] == 0.0
    assert mapping["nestedMaterialization"]["localEndSeconds"] == 1.5
    assert mapping["selectedFrameLineage"][0]["parentSourceFrameIndex"] == 2
    assert mapping["selectedFrameLineage"][-1]["parentSourceFrameIndex"] == 4


def test_nested_materialized_cut_rejects_review_bound_to_wrong_raw_parent(tmp_path, monkeypatch):
    workspace, selected, _raw, _selected_sha, _raw_sha, parent_clock, _clock_sha = _workspace(
        tmp_path, monkeypatch, wrong_review_parent=True)

    assert clocks.verified_source_timeline_mapping(
        workspace=workspace,
        source_pose={
            "sourceTimeOriginSec": 0.0,
            "frames": [{"sourceTimeSec": 0.0}],
        },
        clock_receipt=parent_clock,
        expected_motion_video_path=selected,
    ) is None
