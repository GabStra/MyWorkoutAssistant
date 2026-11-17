from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import pipeline
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.pose_fidelity import source_timeline_mapping_identity


def test_passthrough_camera_calibration_is_metadata_only_and_loadable(monkeypatch, tmp_path: Path):
    joint_names = [
        "left_shoulder", "right_shoulder", "left_hip", "right_hip",
        "left_knee", "right_knee", "left_ankle", "right_ankle",
        "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    ]
    joints = {
        "left_shoulder": (-.2, -.8, .1), "right_shoulder": (.2, -.8, .05),
        "left_hip": (-.15, -.4, 0.), "right_hip": (.15, -.4, .03),
        "left_knee": (-.15, -.1, .1), "right_knee": (.15, -.1, .1),
        "left_ankle": (-.15, .3, .1), "right_ankle": (.15, .3, .1),
        "left_elbow": (-.3, -.6, .1), "right_elbow": (.3, -.6, .1),
        "left_wrist": (-.4, -.4, .1), "right_wrist": (.4, -.4, .1),
    }
    source_times = [12.5 + index / 10. for index in range(6)]
    frames = [MotionFrame(
        time_sec=index / 10.,
        joints=dict(joints),
        source_time_sec=source_times[index],
        source_frame_index=index,
        inference_frame_index=index,
    ) for index in range(6)]
    selected_video = tmp_path / "selected.mp4"
    selected_video.write_bytes(b"exact selected video bytes")
    selected_sha = hashlib.sha256(selected_video.read_bytes()).hexdigest()
    source_pose = {
        "sourceVideoSha256": selected_sha,
        "coordinateSpace": "pixel_xy",
        "imageWidth": 640,
        "imageHeight": 480,
        "sourceTimeOriginSec": source_times[0],
        "frames": [{
            "sourceTimeSec": source_times[index],
            "joints": {name: [point[0], point[1]] for name, point in joints.items()},
        } for index in range(6)],
    }
    pose_path = tmp_path / "exact_source_pose_reference.json"
    pose_path.write_text(json.dumps(source_pose), encoding="utf-8")
    pose_mapping_identity = {
        "selectedSegmentSha256": selected_sha,
        "parentSourceSha256": "1" * 64,
        "selectedFrameClockReceiptSha256": "2" * 64,
        "sourcePosePayloadSha256": "3" * 64,
    }
    mapping = {
        **pose_mapping_identity,
        "schemaVersion": 1,
        "verified": True,
        "mappingKind": "selected_segment_to_parent_source",
        "selectedOutputFps": 10.,
        "selectedFrameCount": 6,
        "selectedFrameLineage": [{
            "selectedFrameIndex": index,
            "parentSourceFrameIndex": index,
            "selectedFrameTimeSec": index / 10.,
            "parentSourceTimeSec": source_times[index],
        } for index in range(6)],
    }
    mapped_pose = {
        **source_pose,
        "_sourceTimelineMappingApplied": pose_mapping_identity,
    }
    monkeypatch.setattr(pipeline, "load_source_pose_payload", lambda _path: source_pose)
    monkeypatch.setattr(
        pipeline,
        "_source_pose_on_motion_clock",
        lambda *_args, **_kwargs: (mapped_pose, mapping, None),
    )
    from exercise_motion_pkg import source_pose_evidence
    monkeypatch.setattr(source_pose_evidence, "verify_source_pose", lambda pose, _video: pose)

    clock_fields = {
        "sourceVideoPath": str(selected_video),
        "sourceVideoSha256": selected_sha,
        "outputVideoPath": str(selected_video),
        "outputVideoSha256": selected_sha,
    }
    clip = MotionClip(
        fps=10.,
        joint_names=joint_names,
        frames=frames,
        source={"extractor": "RECONSTRUCTION"},
        metadata={"reconstruction": {
            "coordinateSpace": "camera",
            "sourceFrameClock": clock_fields,
        }},
    )
    calibrated, status = pipeline.retain_source_camera_for_passthrough(
        clip,
        source_pose_reference_path=pose_path,
        source_frame_clock_path=tmp_path / "selected.source_frame_clock.json",
        input_video_path=selected_video,
    )
    assert status["available"] is True, status
    assert calibrated.frames is clip.frames
    assert [frame.joints for frame in calibrated.frames] == [frame.joints for frame in clip.frames]
    registration = calibrated.metadata["sourcePoseRegistration"]
    camera = registration["camera"]
    assert registration["policy"] == "pre_cleanup_fixed_camera"
    assert camera["available"] is True
    assert len(camera["cameraImageTransform"]) == 6
    assert camera["sourceTimelineMappingIdentity"] == source_timeline_mapping_identity(pose_mapping_identity)

    workspace = tmp_path / "candidate"
    (workspace / "cleaned").mkdir(parents=True)
    (workspace / "input").mkdir()
    (workspace / "segment_detection").mkdir()
    workspace_video = workspace / "input" / "selected_segment.mp4"
    workspace_video.write_bytes(selected_video.read_bytes())
    cleaned = {
        "frames": [{
            "timeSec": frame.time_sec,
            "sourceTimeSec": frame.source_time_sec,
            "sourceFrameIndex": frame.source_frame_index,
            "inferenceFrameIndex": frame.inference_frame_index,
            "joints": {name: list(point) for name, point in frame.joints.items()},
        } for frame in calibrated.frames],
        "metadata": {
            **calibrated.metadata,
            "reconstruction": {
                **calibrated.metadata["reconstruction"],
                "sourceFrameClock": {
                    **clock_fields,
                    "outputVideoPath": str(workspace_video),
                    "outputVideoSha256": selected_sha,
                },
            },
        },
    }
    (workspace / "cleaned" / "motion.cleaned.json").write_text(
        json.dumps(cleaned), encoding="utf-8",
    )

    from exercise_motion_pkg import source_frame_clock
    clock_receipt = {
        "outputFrameCount": 6,
        "frames": [{"sourceFrameIndex": i, "sourceTimeSec": source_times[i]} for i in range(6)],
    }
    monkeypatch.setattr(
        source_frame_clock,
        "source_frame_clock_path_for_video",
        lambda _video: tmp_path / "synthetic-clock.json",
    )
    monkeypatch.setattr(
        source_frame_clock,
        "load_verified_source_frame_clock",
        lambda *_args, **_kwargs: clock_receipt,
    )
    monkeypatch.setattr(
        source_frame_clock,
        "source_references_for_frame_ids",
        lambda _receipt, ids: [{
            "sourceFrameIndex": i, "sourceTimeSec": source_times[i],
        } for i in ids],
    )
    mapping_matches = True
    monkeypatch.setattr(
        bake,
        "verified_source_timeline_mapping",
        lambda **_kwargs: mapping if mapping_matches else {
            **mapping, "sourcePosePayloadSha256": "4" * 64,
        },
    )

    camera_reference = bake.load_baked_source_camera_reference(workspace, source_pose)
    assert camera_reference is not None
    assert camera_reference["camera"]["cameraImageTransform"] == camera["cameraImageTransform"]
    mapping_matches = False
    assert bake.load_baked_source_camera_reference(workspace, source_pose) is None
