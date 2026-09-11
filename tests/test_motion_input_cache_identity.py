import json
import os
from pathlib import Path

from exercise_motion_pkg import bake_and_rank as bake, youtube
from exercise_motion_pkg.yolo_track_stabilize import load_workspace_yolo_pose_track
from exercise_motion_pkg.stage_cache import file_identity


def test_context_cache_tracks_content_and_interval_not_filename(tmp_path, monkeypatch):
    source, output = tmp_path / "source.mp4", tmp_path / "context.mp4"
    source.write_bytes(b"one")
    output.write_bytes(b"legacy interval")
    calls = []
    def trim(**kwargs):
        calls.append(kwargs)
        output.write_bytes(source.read_bytes() + str(kwargs['start_seconds']).encode())
    monkeypatch.setattr(bake, "trim_video", trim)
    def prepare(start=0):
        bake.prepare_cached_wham_video(source_path=source, output_path=output, start_seconds=start, end_seconds=4)
    prepare()
    prepare()
    assert len(calls) == 1
    prepare(1)
    assert len(calls) == 2
    stamp = source.stat().st_mtime_ns
    source.write_bytes(b"two")
    os.utime(source, ns=(stamp, stamp))
    prepare(1)
    assert len(calls) == 3
    output.write_bytes(b"corrupt")
    prepare(1)
    assert len(calls) == 4


def test_stabilization_does_not_reuse_another_interval(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"135 frames")
    output = tmp_path / "input" / "wham_inference_yolo_stabilized.mp4"
    output.parent.mkdir()
    output.write_bytes(b"169 legacy frames")
    metadata = output.parent / "wham_yolo_track_stabilization.json"
    metadata.write_text(json.dumps({"policyVersion": bake.YOLO_TRACK_STABILIZATION_POLICY_VERSION, "applied": True}))
    calls = []
    monkeypatch.setattr(bake, "load_workspace_yolo_pose_track", lambda _: {"frames": []})
    def stabilize(**kwargs):
        calls.append(kwargs)
        output.write_bytes(source.read_bytes())
        metadata.write_text(json.dumps({"applied": True, "reason": "tracked"}))
        return output
    monkeypatch.setattr(bake, "_stabilize_wham_inference_video_to_yolo_track_uncached", stabilize)
    def prepare(start=0):
        return bake.stabilize_wham_inference_video_to_yolo_track(candidate_workspace=tmp_path,
                    inference_video_path=source, selected_start_seconds=start)
    prepare()
    assert output.read_bytes() == b"135 frames"
    prepare()
    assert len(calls) == 1
    source.write_bytes(b"different same-length interval")
    prepare()
    prepare(1)
    assert len(calls) == 3


def test_sanitizer_does_not_trust_preserved_modification_time(tmp_path, monkeypatch):
    source = tmp_path / "video.mp4"
    output = tmp_path / "video_sanitized.mp4"
    source.write_bytes(b"first")
    calls = []
    def sanitize(path):
        calls.append(path)
        output.write_bytes(path.read_bytes())
        return output
    monkeypatch.setattr(youtube, "_sanitize_downloaded_video_uncached", sanitize)
    youtube.sanitize_downloaded_video(source)
    youtube.sanitize_downloaded_video(source)
    assert len(calls) == 1
    stamp = source.stat().st_mtime_ns
    source.write_bytes(b"other")
    os.utime(source, ns=(stamp, stamp))
    youtube.sanitize_downloaded_video(source)
    assert output.read_bytes() == b"other" and len(calls) == 2


def test_stabilization_track_must_belong_to_selected_video(tmp_path):
    video = tmp_path / "input" / "selected_segment.mp4"
    video.parent.mkdir()
    video.write_bytes(b"current interval")
    root = tmp_path / "segment_detection"
    root.mkdir()
    stale = root / "pre_wham_source_candidates" / "deterministic_confirmation" / "source_candidate_A" / "exact_source_pose_reference.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps({"sourceVideoSha256": "old", "pose": {"frames": ["wrong"]}}))
    assert load_workspace_yolo_pose_track(tmp_path) is None
    canonical = root / "exact_source_pose_reference.json"
    canonical.write_text(json.dumps({"sourceVideoSha256": file_identity(video)["sha256"],
                                    "pose": {"frames": ["current"]}}))
    assert load_workspace_yolo_pose_track(tmp_path) == {"frames": ["current"]}
