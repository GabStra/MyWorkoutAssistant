from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

import numpy as np
import pytest

from exercise_motion_pkg.ffmpeg_utils import h264_codec_args, resolve_ffmpeg_path
from exercise_motion_pkg.cleanup import trim_static_edges
from exercise_motion_pkg.bake_and_rank import (
    load_baked_source_camera_reference,
    materialize_source_video_interval,
    normalize_reconstruction_input_frame_rate,
    prepare_reconstruction_inference_video,
    rebind_existing_source_frame_clock_for_video_copy,
    source_frame_clock_path_for_video,
    verified_source_timeline_mapping,
)
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.motion_io import load_motion_json, save_motion_json
from exercise_motion_pkg.preview import _build_wear_transformed_frames
from exercise_motion_pkg.pipeline import (
    GenerateRequest,
    _source_pose_on_motion_clock,
    prepare_input_video,
)
from exercise_motion_pkg.paths import PipelinePaths
from exercise_motion_pkg.pose_fidelity import (
    _canonical_source_pose_sha256,
    materialized_camera_placement_transform,
    source_comparison_time,
    pose_frames_for_source_comparison,
    source_pose_reference_for_motion,
    source_timeline_mapping_identity,
)
from exercise_motion_pkg.structural_refinement import stabilize_distal_foot_heading
from exercise_motion_pkg.source_frame_clock import (
    SOURCE_FRAME_CLOCK_SCHEMA_VERSION,
    build_source_frame_clock,
    compose_source_frame_clocks,
    load_verified_source_frame_clock,
    rebind_source_frame_clock,
    rebind_source_frame_clock_for_exact_transcode,
    recover_materialized_cut_clock,
    source_exposure_crop_window,
    source_times_for_frame_ids,
    write_source_frame_clock,
)
from exercise_motion_pkg.video_utils import read_basic_video_metadata, trim_video
from exercise_motion_pkg.youtube import sanitize_downloaded_video


def _write_clock_test_video(path: Path, *, fps: float, frame_count: int = 120) -> None:
    cv2 = pytest.importorskip("cv2")
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 64),
    )
    assert writer.isOpened()
    for frame_index in range(frame_count):
        frame = np.full((64, 64, 3), frame_index % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_recover_materialized_cut_clock_requires_exact_selection_and_verifies_exposures(
    tmp_path: Path,
) -> None:
    source = tmp_path / "parent.mp4"
    selected = tmp_path / "selected_segment.mp4"
    cv2 = pytest.importorskip("cv2")
    writer = cv2.VideoWriter(
        str(source), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (128, 64),
    )
    assert writer.isOpened()
    for index in range(120):
        frame = np.zeros((64, 128, 3), dtype=np.uint8)
        cv2.putText(frame, str(index), (4, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                    (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    materialize_source_video_interval(
        source_path=source,
        output_path=selected,
        start_seconds=1.0,
        end_seconds=2.5,
    )
    clock_path = source_frame_clock_path_for_video(selected)
    clock_path.unlink()
    selection = {
        "selectedSegmentPath": str(selected.resolve()),
        "selectedSegmentSha256": hashlib.sha256(selected.read_bytes()).hexdigest(),
        "selectedSegmentMaterialization": "trimmed_source_window",
        "selectedSegmentSourceVideoPath": str(source.resolve()),
        "selectedSegmentSourceVideoSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "selectedSegmentCropStartSeconds": 1.0,
        "selectedSegmentCropEndSeconds": 2.5,
    }

    recovered = recover_materialized_cut_clock(
        selection=selection,
        selected_video_path=selected,
    )

    assert recovered["sourceVideoSha256"] == selection["selectedSegmentSourceVideoSha256"]
    assert recovered["frames"][0]["sourceFrameIndex"] == 30
    assert recovered["frames"][-1]["sourceFrameIndex"] == 74
    selection["selectedSegmentSha256"] = "0" * 64
    with pytest.raises(ValueError, match="selected cut bytes"):
        recover_materialized_cut_clock(selection=selection, selected_video_path=selected)


def test_source_exposure_crop_window_uses_selected_actual_exposures() -> None:
    identity = {
        "sourceVideoPath": "parent.mp4",
        "sourceVideoSha256": "a" * 64,
        "sourceFps": 30.0,
        "sourceOriginTimeSec": 0.0,
    }
    selected = {
        **identity,
        "outputFps": 30.0,
        "frames": [
            {"sourceTimeSec": frame / 30.0}
            for frame in range(60, 153)
        ],
    }
    inference = {
        **identity,
        "outputFps": 30.0,
        "frames": [
            {"sourceTimeSec": frame / 30.0}
            for frame in range(24, 192)
        ],
    }

    assert source_exposure_crop_window(selected, inference) == pytest.approx((1.2, 4.3))


@pytest.mark.parametrize("source_fps", [60.0, 59.94])
@pytest.mark.parametrize("selected_start_frame", [60, 61])
def test_source_exposure_crop_window_accounts_for_30fps_resampling(
    source_fps: float, selected_start_frame: int,
) -> None:
    identity = {
        "sourceVideoPath": "parent.mp4",
        "sourceVideoSha256": "b" * 64,
        "sourceFps": source_fps,
        "sourceOriginTimeSec": 0.0,
    }
    selected = {
        **identity,
        "outputFps": source_fps,
        "frames": [
            {"sourceTimeSec": frame / source_fps}
            for frame in range(selected_start_frame, selected_start_frame + 93)
        ],
    }
    inference_rows = []
    for index in range(180):
        ideal_time = 0.8 + index / 30.0
        source_index = int(math.floor(ideal_time * source_fps + 0.5))
        inference_rows.append({"sourceTimeSec": source_index / source_fps})
    inference = {**identity, "outputFps": 30.0, "frames": inference_rows}

    crop_start, crop_end = source_exposure_crop_window(selected, inference)
    selected_start = selected["frames"][0]["sourceTimeSec"]
    selected_end = selected["frames"][-1]["sourceTimeSec"]
    first_context_exposure = inference_rows[round(crop_start * 30)]["sourceTimeSec"]
    last_context_exposure = inference_rows[round(crop_end * 30) - 1]["sourceTimeSec"]
    tolerance = 0.51 / 30.0 + 0.51 / source_fps
    assert abs(first_context_exposure - selected_start) <= tolerance
    assert abs(last_context_exposure - selected_end) <= tolerance


def test_source_exposure_crop_window_rejects_interval_without_a_context_exposure() -> None:
    identity = {
        "sourceVideoPath": "parent.mp4",
        "sourceVideoSha256": "c" * 64,
        "sourceFps": 60.0,
        "sourceOriginTimeSec": 0.0,
    }
    selected = {
        **identity,
        "outputFps": 60.0,
        "frames": [{"sourceTimeSec": 1.01}, {"sourceTimeSec": 1.025}],
    }
    inference = {
        **identity,
        "outputFps": 30.0,
        "frames": [{"sourceTimeSec": 0.0}, {"sourceTimeSec": 1.0}, {"sourceTimeSec": 1.0333333333}],
    }

    with pytest.raises(ValueError, match="does not cover the selected source exposures"):
        source_exposure_crop_window(selected, inference)


def test_no_padding_path_recovers_parent_clock_before_normalization(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    workspace = tmp_path / "candidate"
    source = tmp_path / "parent.mp4"
    selected = workspace / "input/selected_segment.mp4"
    selection_path = workspace / "segment_detection/segment_selection.json"
    pose_reference = workspace / "segment_detection/exact_source_pose_reference.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    selected.parent.mkdir(parents=True)
    selection_path.parent.mkdir(parents=True)
    writer = cv2.VideoWriter(
        str(source), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (128, 64),
    )
    assert writer.isOpened()
    for index in range(120):
        frame = np.zeros((64, 128, 3), dtype=np.uint8)
        cv2.putText(frame, str(index), (4, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                    (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    materialize_source_video_interval(
        source_path=source,
        output_path=selected,
        start_seconds=1.0,
        end_seconds=2.5,
    )
    source_frame_clock_path_for_video(selected).unlink()
    selection = {
        "selectedSegmentPath": str(selected.resolve()),
        "selectedSegmentSha256": hashlib.sha256(selected.read_bytes()).hexdigest(),
        "selectedSegmentMaterialization": "trimmed_source_window",
        "selectedSegmentSourceVideoPath": str(source.resolve()),
        "selectedSegmentSourceVideoSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "selectedSegmentCropStartSeconds": 1.0,
        "selectedSegmentCropEndSeconds": 2.5,
        "selectedSpan": {"startSeconds": 1.0, "endSeconds": 2.5},
        "detectionSourceVideoPath": str(source.resolve()),
    }
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    pose_reference.write_text("{}", encoding="utf-8")

    prepared, crop_start, crop_end = prepare_reconstruction_inference_video(
        candidate_workspace=workspace,
        selected_video_path=selected,
        padding_seconds=0.0,
    )

    recovered = load_verified_source_frame_clock(
        source_frame_clock_path_for_video(prepared), expected_video_path=prepared,
    )
    assert prepared == selected
    assert (crop_start, crop_end) == (None, None)
    assert recovered["sourceVideoPath"] == str(source.resolve())
    assert recovered["frames"][0]["sourceFrameIndex"] == 30


def test_composed_clock_keeps_requested_bounds_separate_from_exact_exposures(
    tmp_path: Path,
) -> None:
    intermediate = tmp_path / "selected.mp4"
    normalized = tmp_path / "inference.mp4"
    upstream = {
        "schemaVersion": SOURCE_FRAME_CLOCK_SCHEMA_VERSION,
        "sourceVideoPath": str(tmp_path / "parent.mp4"),
        "sourceVideoSha256": "a" * 64,
        "sourceFps": 30.0,
        "sourceFrameCount": 1000,
        "sourceOriginTimeSec": 0.0,
        "outputVideoPath": str(intermediate),
        "outputVideoSha256": "b" * 64,
        "outputFps": 30.0,
        "outputFrameCount": 2,
        "cropStartSeconds": 7.01,
        "frames": [
            {"outputFrameIndex": 0, "sourceFrameIndex": 211, "sourceTimeSec": 7.04},
            {"outputFrameIndex": 1, "sourceFrameIndex": 212, "sourceTimeSec": 7.07},
        ],
    }
    downstream = {
        "schemaVersion": SOURCE_FRAME_CLOCK_SCHEMA_VERSION,
        "sourceVideoPath": str(intermediate),
        "sourceVideoSha256": "b" * 64,
        "sourceFps": 30.0,
        "sourceFrameCount": 2,
        "sourceOriginTimeSec": 0.0,
        "outputVideoPath": str(normalized),
        "outputVideoSha256": "c" * 64,
        "outputFps": 30.0,
        "outputFrameCount": 1,
        "cropStartSeconds": 0.25,
        "frames": [
            {"outputFrameIndex": 0, "sourceFrameIndex": 1, "sourceTimeSec": 0.25},
        ],
    }

    composed = compose_source_frame_clocks(upstream, downstream)

    assert composed["cropStartSeconds"] == pytest.approx(7.26)
    assert composed["frames"] == [
        {"outputFrameIndex": 0, "sourceFrameIndex": 212, "sourceTimeSec": 7.07},
    ]


def test_normalize_reconstruction_input_preserves_existing_parent_clock_on_noop(
    tmp_path: Path,
) -> None:
    source = tmp_path / "parent-30fps.mp4"
    selected = tmp_path / "candidate" / "input" / "selected_segment.mp4"
    selected.parent.mkdir(parents=True)
    _write_clock_test_video(source, fps=30.0)
    materialize_source_video_interval(
        source_path=source, output_path=selected,
        start_seconds=1.0, end_seconds=3.5,
    )
    clock_path = source_frame_clock_path_for_video(selected)
    clock_before = clock_path.read_bytes()
    before = load_verified_source_frame_clock(clock_path, expected_video_path=selected)
    assert before["sourceVideoPath"] == str(source.resolve())

    normalized = normalize_reconstruction_input_frame_rate(
        candidate_workspace=tmp_path / "candidate",
        selected_video_path=selected,
    )

    assert normalized == selected
    assert clock_path.read_bytes() == clock_before
    after = load_verified_source_frame_clock(clock_path, expected_video_path=selected)
    assert after["sourceVideoPath"] == str(source.resolve())
    assert after["frames"] == before["frames"]


@pytest.mark.parametrize("source_fps", [24.0, 25.0, 30000.0 / 1001.0])
def test_normalize_reconstruction_input_composes_transcode_clock_to_parent(
    tmp_path: Path, source_fps: float,
) -> None:
    source = tmp_path / f"parent-{source_fps}.mp4"
    selected = tmp_path / "candidate" / "input" / "selected_segment.mp4"
    selected.parent.mkdir(parents=True)
    _write_clock_test_video(source, fps=source_fps)
    materialize_source_video_interval(
        source_path=source, output_path=selected,
        start_seconds=0.8, end_seconds=3.6,
    )
    upstream = load_verified_source_frame_clock(
        source_frame_clock_path_for_video(selected), expected_video_path=selected,
    )
    assert abs(float(upstream["outputFps"]) - 30.0) > 0.01

    normalized = normalize_reconstruction_input_frame_rate(
        candidate_workspace=tmp_path / "candidate",
        selected_video_path=selected,
    )
    assert normalized != selected
    composed = load_verified_source_frame_clock(
        source_frame_clock_path_for_video(normalized), expected_video_path=normalized,
    )
    assert composed["sourceVideoPath"] == upstream["sourceVideoPath"]
    assert composed["sourceVideoSha256"] == upstream["sourceVideoSha256"]
    assert composed["outputVideoSha256"] != upstream["outputVideoSha256"]
    assert len(composed["frames"]) == read_basic_video_metadata(normalized).frame_count
    assert all(
        row["sourceTimeSec"] == pytest.approx(
            float(composed["sourceOriginTimeSec"])
            + int(row["sourceFrameIndex"]) / float(composed["sourceFps"]),
            abs=1e-6,
        )
        for row in composed["frames"]
    )
    if source_fps in {24.0, 25.0}:
        parent_indices = [row["sourceFrameIndex"] for row in composed["frames"]]
        assert len(set(parent_indices)) < len(parent_indices)

    direct = build_source_frame_clock(
        source_video_path=selected,
        output_video_path=normalized,
        crop_start_seconds=0.0,
        output_fps=30.0,
    )
    expected = compose_source_frame_clocks(upstream, direct)
    assert composed["frames"] == expected["frames"]


@pytest.mark.parametrize("source_fps", [24.0, 25.0, 29.97])
def test_source_clock_tracks_actual_ffmpeg_fps_filter_frames_with_trim_origin(
    tmp_path: Path, source_fps: float,
) -> None:
    cv2 = pytest.importorskip("cv2")
    ffmpeg = resolve_ffmpeg_path()
    if ffmpeg is None:
        pytest.skip("FFmpeg is required to verify the production fps filter")

    source = tmp_path / f"source-{source_fps}.mp4"
    output = tmp_path / f"output-{source_fps}.mp4"
    writer = cv2.VideoWriter(
        str(source), cv2.VideoWriter_fourcc(*"mp4v"), source_fps, (128, 64),
    )
    assert writer.isOpened()
    for index in range(120):
        frame = np.empty((64, 128, 3), dtype=np.uint8)
        frame[:] = ((index * 67) % 256, (index * 113) % 256, (index * 181) % 256)
        cv2.putText(frame, str(index), (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()

    # Same trim and fps filter used by reconstruction input preparation.
    start_seconds, end_seconds = 1.137, 3.977
    trim_video(
        source_path=source,
        output_path=output,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        target_fps=30.0,
    )
    receipt = build_source_frame_clock(
        source_video_path=source,
        output_video_path=output,
        crop_start_seconds=start_seconds,
        output_fps=30.0,
        source_origin_seconds=12.5,
    )

    def decoded_frames(path: Path) -> list[np.ndarray]:
        capture = cv2.VideoCapture(str(path))
        assert capture.isOpened()
        frames = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)
        capture.release()
        return frames

    source_frames = decoded_frames(source)
    output_frames = decoded_frames(output)
    assert len(output_frames) == receipt["outputFrameCount"]
    observed_indices = []
    for frame in output_frames:
        marker = frame[5:20, 5:20].mean(axis=(0, 1))
        source_markers = [candidate[5:20, 5:20].mean(axis=(0, 1)) for candidate in source_frames]
        distances = [float(np.linalg.norm(marker - candidate)) for candidate in source_markers]
        observed_indices.append(int(np.argmin(distances)))

    selected_indices = [frame["sourceFrameIndex"] for frame in receipt["frames"]]
    assert selected_indices == observed_indices
    assert selected_indices[0] == math.ceil(start_seconds * source_fps - 1e-7)
    assert receipt["frames"][0]["sourceTimeSec"] == pytest.approx(
        12.5 + selected_indices[0] / source_fps,
    )
    assert selected_indices == sorted(selected_indices)
    if source_fps in {24.0, 25.0}:
        assert any(left == right for left, right in zip(selected_indices, selected_indices[1:]))

    receipt_path = write_source_frame_clock(receipt, output_path=output.with_suffix(".clock.json"))
    verified = load_verified_source_frame_clock(receipt_path, expected_video_path=output)
    assert source_times_for_frame_ids(verified, [0, 1, len(selected_indices) - 1]) == pytest.approx([
        12.5 + selected_indices[0] / source_fps,
        12.5 + selected_indices[1] / source_fps,
        12.5 + selected_indices[-1] / source_fps,
    ])

    workspace = tmp_path / "candidate"
    cleaned_path = workspace / "cleaned" / "motion.cleaned.json"
    cleaned_path.parent.mkdir(parents=True)
    (workspace / "input").mkdir(parents=True)
    (workspace / "segment_detection").mkdir(parents=True)
    selected_video = workspace / "input" / "selected_segment.mp4"
    selected_video.write_bytes(output.read_bytes())
    write_source_frame_clock(receipt, output_path=output.with_suffix(".source_frame_clock.json"))
    selected_clock = build_source_frame_clock(
        source_video_path=source,
        output_video_path=selected_video,
        crop_start_seconds=start_seconds,
        output_fps=30.0,
        source_origin_seconds=12.5,
    )
    write_source_frame_clock(
        selected_clock,
        output_path=source_frame_clock_path_for_video(selected_video),
    )
    chosen_ids = [0, 1, len(selected_indices) - 1]
    retained_frames = [{
        "timeSec": frame_id / 30.0,
        "sourceTimeSec": frame_id / 30.0,
        "inferenceFrameIndex": frame_id,
        "joints": {"pelvis": [float(frame_id), 1.0, 0.0]},
    } for frame_id in chosen_ids]
    cleaned_path.write_text(json.dumps({
        "frames": retained_frames,
        "metadata": {
            "reconstruction": {"sourceFrameClock": {
                key: receipt[key] for key in (
                    "sourceVideoPath", "sourceVideoSha256", "outputVideoPath", "outputVideoSha256",
                )
            }},
            "structuralRefinement": {"sourceGuidedArticulation": {"cameraRegistration": {
                "available": True,
                "cameraImageTransform": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            }}},
        },
    }), encoding="utf-8")
    source_pose = {
        "coordinateSpace": "pixel_xy",
        "imageWidth": 640,
        "imageHeight": 480,
        "sourceTimeOriginSec": 0.0,
        "frames": [
            {"sourceTimeSec": time_sec, "joints": {"pelvis": [100.0, 200.0]}}
            for time_sec in (0.0, 1.0)
        ],
    }
    selected_sha = hashlib.sha256(selected_video.read_bytes()).hexdigest()
    source_video_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    (workspace / "segment_detection" / "segment_selection.json").write_text(json.dumps({
        "selectedSegmentPath": str(selected_video.resolve()),
        "selectedSegmentSha256": selected_sha,
        "sourceVideoPath": str(source.resolve()),
        "selectedSpanInOriginalSource": {
            "startSeconds": 12.5 + start_seconds,
            "endSeconds": 12.5 + start_seconds + len(selected_indices) / 30.0,
        },
    }), encoding="utf-8")
    (workspace / "segment_detection" / "exact_source_pose_reference.json").write_text(json.dumps({
        "sourceVideoSha256": selected_sha,
        "pose": source_pose,
    }), encoding="utf-8")
    camera_mapping = verified_source_timeline_mapping(
        workspace=workspace,
        source_pose=source_pose,
        clock_receipt=receipt,
    )
    assert camera_mapping is not None
    mapped_pose, pipeline_mapping, timeline_error = _source_pose_on_motion_clock(
        source_pose,
        source_pose_reference_path=workspace / "segment_detection" / "exact_source_pose_reference.json",
        source_frame_clock_path=source_frame_clock_path_for_video(output),
        input_video_path=output,
    )
    assert timeline_error is None
    assert pipeline_mapping is not None
    assert [frame["sourceTimeSec"] for frame in mapped_pose["frames"]] == pytest.approx([
        camera_mapping["selectedFrameLineage"][0]["parentSourceTimeSec"],
        camera_mapping["selectedFrameLineage"][30]["parentSourceTimeSec"],
    ])
    cleaned_payload = json.loads(cleaned_path.read_text(encoding="utf-8"))
    camera_payload = cleaned_payload["metadata"]["structuralRefinement"][
        "sourceGuidedArticulation"]["cameraRegistration"]
    camera_payload["sourceTimelineMappingIdentity"] = source_timeline_mapping_identity(camera_mapping)
    cleaned_path.write_text(json.dumps(cleaned_payload), encoding="utf-8")
    camera_reference = load_baked_source_camera_reference(workspace, source_pose)
    assert camera_reference is not None
    assert camera_reference["sourceTimelineMapping"]["parentSourceSha256"] == source_video_sha
    assert camera_reference["sourceTimelineMapping"]["selectedStartSeconds"] == pytest.approx(
        12.5 + start_seconds,
    )
    first_selected_lineage = camera_reference["sourceTimelineMapping"]["selectedFrameLineage"][0]
    assert first_selected_lineage["selectedFrameIndex"] == 0
    assert first_selected_lineage["parentSourceFrameIndex"] == selected_indices[0]
    assert first_selected_lineage["parentSourceTimeSec"] == pytest.approx(
        12.5 + selected_indices[0] / source_fps,
    )
    assert first_selected_lineage["parentSourceTimeSec"] != pytest.approx(
        camera_reference["sourceTimelineMapping"]["selectedStartSeconds"],
    )
    coordinate_frames = camera_reference["coordinateReference"]["frames"]
    assert [frame["sourceTimeSec"] for frame in coordinate_frames] == pytest.approx([
        receipt["frames"][frame_id]["sourceTimeSec"] for frame_id in chosen_ids
    ])
    assert [frame["timeSec"] for frame in coordinate_frames] == pytest.approx([
        frame_id / 30.0 for frame_id in chosen_ids
    ])
    assert [frame["joints"] for frame in coordinate_frames] == [frame["joints"] for frame in retained_frames]
    camera_payload["sourceTimelineMappingIdentity"]["sourcePosePayloadSha256"] = "0" * 64
    cleaned_path.write_text(json.dumps(cleaned_payload), encoding="utf-8")
    assert load_baked_source_camera_reference(workspace, source_pose) is None


def test_materialized_non_aligned_cut_clock_uses_first_decoded_exposure(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    if resolve_ffmpeg_path() is None:
        pytest.skip("FFmpeg is required to verify the production cut materializer")

    source = tmp_path / "source-ntsc.mp4"
    selected = tmp_path / "selected-segment.mp4"
    source_fps = 30000.0 / 1001.0
    writer = cv2.VideoWriter(
        str(source), cv2.VideoWriter_fourcc(*"mp4v"), source_fps, (64, 64),
    )
    assert writer.isOpened()
    for frame_index in range(400):
        frame = np.full((64, 64, 3), frame_index % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    requested_start, requested_end = 7.01, 10.11
    materialization = materialize_source_video_interval(
        source_path=source,
        output_path=selected,
        start_seconds=requested_start,
        end_seconds=requested_end,
    )
    assert materialization == "trimmed_source_window"
    receipt = load_verified_source_frame_clock(
        source_frame_clock_path_for_video(selected), expected_video_path=selected,
    )

    first = receipt["frames"][0]
    assert first["outputFrameIndex"] == 0
    assert first["sourceFrameIndex"] == 211
    assert first["sourceTimeSec"] == pytest.approx(
        211 / receipt["sourceFps"], abs=1e-7,
    )
    assert first["sourceTimeSec"] > requested_start
    assert len(receipt["frames"]) == read_basic_video_metadata(selected).frame_count
    assert receipt["frames"][-1]["sourceTimeSec"] > requested_end
    assert [row["sourceFrameIndex"] for row in receipt["frames"]] == list(
        range(211, 211 + len(receipt["frames"])),
    )

    copied_selected = tmp_path / "copied-selected-segment.mp4"
    shutil.copy2(selected, copied_selected)
    rebound_path = rebind_existing_source_frame_clock_for_video_copy(
        source_video_path=selected,
        output_video_path=copied_selected,
        transform="test_exact_video_copy",
    )
    assert rebound_path == source_frame_clock_path_for_video(copied_selected)
    rebound = load_verified_source_frame_clock(
        rebound_path,
        expected_video_path=copied_selected,
    )
    assert rebound["frames"] == receipt["frames"]

    changed_copy = tmp_path / "changed-selected-segment.mp4"
    shutil.copy2(selected, changed_copy)
    with changed_copy.open("ab") as stream:
        stream.write(b"changed")
    assert rebind_existing_source_frame_clock_for_video_copy(
        source_video_path=selected,
        output_video_path=changed_copy,
        transform="test_reject_nonidentical_video",
    ) is None
    assert not source_frame_clock_path_for_video(changed_copy).exists()


def test_source_clock_rejects_receipt_when_prepared_video_changes(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    receipt_path = tmp_path / "clock.json"
    receipt_path.write_text(json.dumps({
        "schemaVersion": SOURCE_FRAME_CLOCK_SCHEMA_VERSION,
        "sourceVideoPath": str(source),
        "sourceVideoSha256": "bad",
        "outputVideoPath": str(output),
        "outputVideoSha256": "bad",
        "outputFrameCount": 0,
        "frames": [],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="source identity"):
        load_verified_source_frame_clock(receipt_path)


def test_source_clock_rejects_variable_frame_rate_source(tmp_path: Path) -> None:
    ffmpeg = resolve_ffmpeg_path()
    if ffmpeg is None:
        pytest.skip("FFmpeg is required to construct the variable-frame-rate fixture")
    video = tmp_path / "variable-rate.mp4"
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=size=64x64:rate=30:duration=1", "-vf",
            "setpts='N/(30*TB)+if(mod(N,2),0.01/TB,0)'", "-fps_mode", "vfr",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            "-g", "1", "-y", str(video),
        ],
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    with pytest.raises(ValueError, match="variable-frame-rate|nominal FPS"):
        build_source_frame_clock(
            source_video_path=video,
            output_video_path=video,
            crop_start_seconds=0.0,
            output_fps=read_basic_video_metadata(video).fps,
        )


def test_source_clock_rejects_legacy_receipt_schema(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    receipt_path = tmp_path / "legacy-clock.json"
    receipt_path.write_text(json.dumps({
        "schemaVersion": 1,
        "sourceVideoPath": str(source),
        "sourceVideoSha256": "unused",
        "outputVideoPath": str(output),
        "outputVideoSha256": "unused",
        "outputFrameCount": 0,
        "frames": [],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported source frame clock"):
        load_verified_source_frame_clock(receipt_path)
    with pytest.raises(ValueError, match="unverified legacy"):
        rebind_source_frame_clock(
            {"schemaVersion": 1}, output_video_path=output, transform="test",
        )


def test_source_clock_survives_motion_io_cleanup_structural_repair_and_preview(tmp_path: Path) -> None:
    names = ["pelvis", "left_ankle", "left_foot", "right_ankle", "right_foot"]
    frames = []
    for index in range(5):
        frames.append(MotionFrame(
            time_sec=index / 30.0,
            source_time_sec=10.0 + index / 29.97,
            source_frame_index=300 + index,
            inference_frame_index=index,
            joints={
                "pelvis": (index * 0.1, 1.0, 0.0),
                "left_ankle": (0.0, 0.1, 0.0),
                "left_foot": (0.2, 0.1, 0.0),
                "right_ankle": (0.2, 0.1, 0.0),
                "right_foot": (0.4, 0.1, 0.0),
            },
        ))
    original = MotionClip(fps=30.0, joint_names=names, frames=frames)
    path = tmp_path / "motion.json"
    save_motion_json(path, original)
    loaded = load_motion_json(path)
    cleaned, start_trim, end_trim = trim_static_edges(loaded, motion_threshold=0.01, padding_frames=0)
    assert start_trim == 1 and end_trim == 0
    refined, _ = stabilize_distal_foot_heading(cleaned)
    assert [frame.inference_frame_index for frame in refined.frames] == [1, 2, 3, 4]

    baked = _build_wear_transformed_frames(
        active_frames=refined.frames,
        root_joint="pelvis",
        active_root_anchor=None,
        auto_alignment=[],
        lock_y_drift=False,
        lock_root_translation=False,
    )
    assert [frame["sourceFrameIndex"] for frame in baked] == [301, 302, 303, 304]
    assert [frame["sourceTimeSec"] for frame in baked] == pytest.approx([
        10.0 + index / 29.97 for index in range(1, 5)
    ])
    assert [frame["timeSec"] for frame in baked] == pytest.approx([0.0, 1 / 30, 2 / 30, 3 / 30])


def test_camera_placement_pairs_coordinate_reference_on_native_source_clock() -> None:
    joint_names = (
        "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
        "left_wrist", "right_wrist", "left_hip", "right_hip",
        "left_knee", "right_knee", "left_ankle", "right_ankle", "pelvis",
    )
    base = {
        "pelvis": (0.0, 0.0, 0.0),
        "left_shoulder": (-0.3, 0.6, 0.0), "right_shoulder": (0.3, 0.6, 0.0),
        "left_elbow": (-0.5, 0.4, 0.0), "right_elbow": (0.5, 0.4, 0.0),
        "left_wrist": (-0.6, 0.2, 0.0), "right_wrist": (0.6, 0.2, 0.0),
        "left_hip": (-0.2, -0.1, 0.0), "right_hip": (0.2, -0.1, 0.0),
        "left_knee": (-0.2, -0.5, 0.0), "right_knee": (0.2, -0.5, 0.0),
        "left_ankle": (-0.2, -0.9, 0.0), "right_ankle": (0.2, -0.9, 0.0),
    }
    source_frames = []
    coordinate_frames = []
    motion_frames = []
    native_indices = (0, 1, 1, 2)
    for index in range(4):
        source_time = 6.0 + native_indices[index] / 29.97
        joints = dict(base)
        joints["left_wrist"] = (-0.6, 0.2, index * 0.12)
        source_frames.append({
            "sourceTimeSec": source_time,
            "joints": {name: [point[0], point[1]] for name, point in joints.items()},
        })
        coordinate_frames.append({
            "timeSec": index / 30.0,
            "sourceTimeSec": source_time,
            "inferenceFrameIndex": index,
            "joints": {name: list(point) for name, point in joints.items()},
        })
        translation = (index * 0.03, 0.0, 0.0)
        placed = {name: [point[0] + translation[0], point[1], point[2]]
                  for name, point in joints.items()}
        motion_frames.append({
            "timeSec": index / 30.0,
            "sourceTimeSec": source_time,
            "inferenceFrameIndex": index,
            "cameraPlacementReferenceJoints": placed,
        })
    source = {
        "coordinateSpace": "pixel_xy", "imageWidth": 640, "imageHeight": 480,
        "frames": source_frames,
    }
    motion = {"frames": motion_frames, "sourcePoseCameraReference": {
        "sourcePose": source,
        "coordinateReference": {"frames": coordinate_frames},
    }}

    placement = materialized_camera_placement_transform(source, motion)
    assert placement["available"], placement
    assert placement["scale"] == pytest.approx(1.0)
    assert placement["maximumError"] < 1e-9

    source["sourceTimeOriginSec"] = 0.0
    for frame in source["frames"]:
        frame["sourceTimeSec"] -= 6.0
    parent_times = [frame["sourceTimeSec"] for frame in coordinate_frames]
    for index, frame in enumerate(source["frames"]):
        frame["sourceTimeSec"] = index / 30.0
    motion["sourcePoseCameraReference"]["sourceTimelineMapping"] = {
        "schemaVersion": 1,
        "verified": True,
        "mappingKind": "selected_segment_to_parent_source",
        "selectedSegmentSha256": "a" * 64,
        "parentSourceSha256": "b" * 64,
        "selectedStartSeconds": 6.0,
        "selectedFrameClockReceiptSha256": "c" * 64,
        "selectedOutputFps": 30.0,
        "selectedFrameCount": len(parent_times),
        "selectedFrameLineage": [{
            "selectedFrameIndex": index,
            "selectedFrameTimeSec": index / 30.0,
            "parentSourceFrameIndex": native_indices[index],
            "parentSourceTimeSec": parent_times[index],
        } for index in range(len(parent_times))],
        "sourcePosePayloadSha256": _canonical_source_pose_sha256(source),
    }
    cropped_motion = {**motion, "frames": motion_frames[1:]}
    selected = source_pose_reference_for_motion(source, cropped_motion)
    assert len(selected["frames"]) < len(source["frames"])
    assert materialized_camera_placement_transform(selected, cropped_motion)["available"]

    changed = deepcopy(selected)
    changed["frames"][0]["joints"]["left_wrist"][0] += 0.1
    rejected = materialized_camera_placement_transform(changed, cropped_motion)
    assert rejected["available"] is False
    assert rejected["reason"] == "source_camera_evidence_mismatch"


def test_camera_placement_reports_invalid_source_pose_identity_without_crashing() -> None:
    motion = {
        "frames": [{"timeSec": 0.0, "joints": {}}],
        "sourcePoseCameraReference": {
            "sourcePose": {"frames": []},
            "sourceTimelineMapping": {"schemaVersion": 1, "verified": True},
        },
    }

    placement = materialized_camera_placement_transform(None, motion)

    assert placement["available"] is False
    assert placement["reason"] == "source_timeline_mapping_or_pose_identity_mismatch"
    assert placement["sourceFrameCount"] == 0
    assert placement["motionFrameCount"] == 1


def test_selected_cut_pose_clock_rebases_only_with_hash_bound_parent_mapping() -> None:
    source = {
        "coordinateSpace": "pixel_xy",
        "imageWidth": 640,
        "imageHeight": 480,
        "sourceTimeOriginSec": 0.0,
        "frames": [
            {"sourceTimeSec": time, "joints": {"pelvis": [100.0 + time, 200.0]}}
            for time in (0.0, 0.5, 1.0)
        ],
    }
    mapping = {
        "schemaVersion": 1,
        "verified": True,
        "mappingKind": "selected_segment_to_parent_source",
        "selectedSegmentSha256": "a" * 64,
        "parentSourceSha256": "b" * 64,
        "selectedStartSeconds": 2.0,
        "selectedFrameClockReceiptSha256": "c" * 64,
        "selectedOutputFps": 2.0,
        "selectedFrameCount": 3,
        "selectedFrameLineage": [
            {"selectedFrameIndex": 0, "selectedFrameTimeSec": 0.0,
             "parentSourceFrameIndex": 50, "parentSourceTimeSec": 2.5},
            {"selectedFrameIndex": 1, "selectedFrameTimeSec": 0.5,
             "parentSourceFrameIndex": 60, "parentSourceTimeSec": 3.0},
            {"selectedFrameIndex": 2, "selectedFrameTimeSec": 1.0,
             "parentSourceFrameIndex": 70, "parentSourceTimeSec": 3.5},
        ],
        "sourcePosePayloadSha256": _canonical_source_pose_sha256(source),
    }
    motion = {
        "frames": [
            {"timeSec": 0.0, "sourceTimeSec": 2.5, "joints": {}},
            {"timeSec": 0.5, "sourceTimeSec": 3.0, "joints": {}},
        ],
        "sourcePoseCameraReference": {
            "sourceTimelineMapping": mapping,
            "sourcePose": source,
        },
    }

    selected = source_pose_reference_for_motion(source, motion)

    assert [frame["sourceTimeSec"] for frame in selected["frames"]] == [2.5, 3.0]
    assert selected["sourceTimeOriginSec"] == pytest.approx(2.5)
    assert source_comparison_time(selected, motion["frames"][0]) == pytest.approx(0.0)

    wrong_pose = {**source, "frames": [dict(source["frames"][0]), *source["frames"][1:]]}
    wrong_pose["frames"][0]["joints"] = {"pelvis": [999.0, 200.0]}
    rejected = source_pose_reference_for_motion(wrong_pose, motion)
    assert rejected["frames"] == []
    assert rejected["sourcePoseTimelineError"] == "source_timeline_pose_identity_mismatch"

    unverified_motion = {
        **motion,
        "sourcePoseCameraReference": {
            **motion["sourcePoseCameraReference"],
            "sourceTimelineMapping": {**mapping, "verified": False},
        },
    }
    unresolved = source_pose_reference_for_motion(source, unverified_motion)
    assert unresolved["frames"] == []
    assert unresolved["sourcePoseTimelineError"] == "source_timeline_mapping_unverified"


def test_browser_bake_preserves_native_clock_and_identity_for_cropped_duplicate_exposures(
    tmp_path: Path,
) -> None:
    playwright_module = pytest.importorskip("playwright.sync_api")
    from exercise_motion_pkg import bake_and_rank as bake_and_rank_module
    from exercise_motion_pkg import preview as preview_module

    native_indices = [62, 63, 63, 63, 64, 65]
    inference_indices = [38, 39, 40, 41, 42, 43]
    source_origin = 4.25
    joint_names = ["pelvis", "left_wrist"]
    frames = []
    wear_frames = []
    for index, (native_index, inference_index) in enumerate(zip(native_indices, inference_indices)):
        time_sec = index / 30.0
        source_time_sec = source_origin + native_index / 24.0
        wrist = [index * 0.1, 0.5, 0.0]
        joints = {"pelvis": [0.0, 1.0, 0.0], "left_wrist": wrist}
        frames.append(MotionFrame(
            time_sec=time_sec,
            source_time_sec=source_time_sec,
            source_frame_index=native_index,
            inference_frame_index=inference_index,
            joints={name: tuple(point) for name, point in joints.items()},
        ))
        wear_frame = {
            "frameIndex": index,
            "timeSec": time_sec,
            "sourceTimeSec": source_time_sec,
            "sourceFrameIndex": native_index,
            "inferenceFrameIndex": inference_index,
            "joints": joints,
            "sourceJoints": joints,
        }
        if index == 3:
            wear_frame["syntheticLoopBridge"] = True
        wear_frames.append(wear_frame)

    clip = MotionClip(
        fps=30.0,
        joint_names=joint_names,
        frames=frames,
        metadata={"bakedWearPayload": {
            "fps": 30.0,
            "frameCount": len(wear_frames),
            "jointNames": joint_names,
            "frames": wear_frames,
            "selectedPreviewSettings": {},
            "wearDisplay": {},
        }},
    )
    selected_start = source_origin + native_indices[0] / 24.0
    selected_video_sha = "a" * 64
    support_evidence = {
        "source": "exact_selected_source_video_yolo_pose",
        "sourceVideoSha256": selected_video_sha,
        "contacts": [
            {"jointName": "left_foot", "contactState": "full_sole", "startRatio": 0.2,
             "endRatio": 1.0, "supportKind": "observed_foot_patch"},
            {"jointName": "right_foot", "contactState": "full_sole", "startRatio": 0.0,
             "endRatio": 1.0, "supportKind": "observed_foot_patch"},
        ],
        "footPatchEvidence": {
            "sourceVideoSha256": selected_video_sha,
            "sourceTimeBasis": "absolute_source_video",
            "sourceTimeOriginSec": 0.0,
            "sourceStartTimeSec": 0.0,
                "sourceEndTimeSec": 5.0 / 30.0,
                "sourceTimesSec": [index / 30.0 for index in range(6)],
                "sourceFps": 30.0,
            "sourceFrameCount": 6,
            "contacts": [],
            "feet": {
                "left": {"states": ["unknown", "full_sole", "full_sole", "full_sole", "full_sole", "full_sole"]},
                "right": {"states": ["full_sole"] * 6},
            },
        },
    }
    timeline_mapping = {
        "schemaVersion": 1,
        "verified": True,
        "mappingKind": "selected_segment_to_parent_source",
        "selectedSegmentSha256": selected_video_sha,
        "parentSourceSha256": "b" * 64,
        "selectedFrameClockReceiptSha256": "d" * 64,
        "selectedStartSeconds": selected_start,
        "parentSourceFps": 24.0,
        "selectedOutputFps": 30.0,
        "selectedFrameCount": len(native_indices),
        "selectedFrameLineage": [{
            "selectedFrameIndex": index,
            "selectedFrameTimeSec": index / 30.0,
            "parentSourceFrameIndex": native_index,
            "parentSourceTimeSec": source_origin + native_index / 24.0,
        } for index, native_index in enumerate(native_indices)],
        "sourcePosePayloadSha256": "c" * 64,
    }
    clip.metadata["bakedWearPayload"]["sourcePoseCameraReference"] = {
        "sourceTimelineMapping": timeline_mapping,
    }
    html_path = tmp_path / "native-clock-preview.html"
    preview_module.write_preview_html(
        html_path,
        clip,
        title="native-clock-preview",
        three_module_path=preview_module.ensure_three_module_asset(),
    )

    with playwright_module.sync_playwright() as playwright:
        browser = bake_and_rank_module.launch_chromium_browser(playwright)
        page = browser.new_page(viewport={"width": 960, "height": 540})
        page.goto(html_path.resolve().as_uri())
        page.wait_for_function("() => window.exerciseMotionAutomation != null")
        baked = page.evaluate("""({ supportEvidence }) => window.exerciseMotionAutomation.bakeFrameRange(1, 5, {
            fixedRoot: false,
            autoWorldAlignment: false,
            lockYDrift: false,
            lockPlantedFeet: false,
            lockPlantedHands: false,
            playbackSpeed: 1,
            sourceFootSupportEvidence: supportEvidence,
        })""", {"supportEvidence": support_evidence})
        browser.close()

    expected_indices = [63, 63, None, 64, 65]
    expected_inference = [39, 40, None, 42, 43]
    expected_times = [source_origin + 63 / 24.0, source_origin + 63 / 24.0,
                      None, source_origin + 64 / 24.0, source_origin + 65 / 24.0]
    assert [frame.get("sourceFrameIndex") for frame in baked["frames"]] == expected_indices
    assert [frame.get("inferenceFrameIndex") for frame in baked["frames"]] == expected_inference
    for frame, expected_time in zip(baked["frames"], expected_times):
        if expected_time is None:
            assert "sourceTimeSec" not in frame
        else:
            assert frame["sourceTimeSec"] == pytest.approx(expected_time)
    assert [frame["timeSec"] for frame in baked["frames"]] == pytest.approx([0.0, 1 / 30, 2 / 30, 3 / 30, 4 / 30])
    assert baked["frames"][2]["syntheticLoopBridge"] is True
    assert baked["frames"][2]["sourceJoints"] is None
    assert baked["loop"]["sourceStartFrame"] == 63
    assert baked["loop"]["sourceEndFrame"] == 65
    assert baked["loop"]["sourceStartTimeSec"] == pytest.approx(expected_times[0])
    assert baked["loop"]["sourceEndTimeSec"] == pytest.approx(expected_times[-1])
    assert baked["frames"][0]["sourceJoints"]["left_wrist"] != baked["frames"][1]["sourceJoints"]["left_wrist"]
    support = baked["selectedPreviewSettings"]["sourceFootSupportEvidence"]
    assert support["previewCrop"]["sourceTimelineMapping"] == "verified_selected_cut_to_parent"
    assert [contact["startFrame"] for contact in support["contacts"]] == [0, 0]
    assert support["footPatchEvidence"]["sourceTimesSec"] == [index / 30.0 for index in range(6)]
    assert support["footPatchEvidence"]["feet"]["left"]["states"] == [
        "unknown", "full_sole", "full_sole", "full_sole", "full_sole", "full_sole",
    ]
    assert support["footPatchEvidence"]["feet"]["right"]["states"] == ["full_sole"] * 6


def test_source_comparison_uses_motion_frame_native_clock_not_playback_time():
    source_pose = {"sourceTimeOriginSec": 2.0}
    frame = MotionFrame(
        time_sec=0.5,
        joints={"pelvis": (0.0, 0.0, 0.0)},
        source_time_sec=2.7,
        source_frame_index=81,
    )
    assert source_comparison_time(source_pose, frame) == pytest.approx(0.7)
    mapped = {
        **source_pose,
        "_sourceTimelineMappingApplied": {
            "selectedSegmentSha256": "a" * 64,
            "parentSourceSha256": "b" * 64,
            "selectedFrameClockReceiptSha256": "c" * 64,
            "sourcePosePayloadSha256": "d" * 64,
        },
    }
    missing_native_time = MotionFrame(
        time_sec=0.5,
        joints={"pelvis": (0.0, 0.0, 0.0)},
    )
    assert math.isinf(source_comparison_time(mapped, missing_native_time))
    assert source_comparison_time(source_pose, missing_native_time) == pytest.approx(0.5)
    assert pose_frames_for_source_comparison(mapped, {
        "frames": [{"timeSec": 0.5, "joints": {"pelvis": [0.0, 0.0, 0.0]}}],
        "sourcePoseCameraReference": {"sourceTimelineMapping": {"verified": True}},
    }) == []
    assert len(pose_frames_for_source_comparison(source_pose, {
        "frames": [{"timeSec": 0.5, "joints": {"pelvis": [0.0, 0.0, 0.0]}}],
    })) == 1


def test_prepare_input_video_rebinds_clock_through_byte_identical_sanitizer_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if resolve_ffmpeg_path() is None:
        pytest.skip("FFmpeg is required to verify the prepared-video copy path")

    parent_video = tmp_path / "parent.mp4"
    _write_clock_test_video(parent_video, fps=30.0, frame_count=120)
    candidate = tmp_path / "candidate"
    selected_video = candidate / "input" / "selected_segment.mp4"
    selected_video.parent.mkdir(parents=True)
    materialize_source_video_interval(
        source_path=parent_video,
        output_path=selected_video,
        start_seconds=0.713,
        end_seconds=2.8,
    )
    source_clock_path = source_frame_clock_path_for_video(selected_video)
    selected_clock = load_verified_source_frame_clock(
        source_clock_path,
        expected_video_path=selected_video,
    )
    pose = {
        "coordinateSpace": "normalized_image_xy",
        "imageWidth": 64,
        "imageHeight": 64,
        "sourceTimeOriginSec": 0.0,
        "frames": [
            {"sourceTimeSec": time_sec, "joints": {"pelvis": [0.5, 0.5]}}
            for time_sec in (0.0, 0.5, 1.0, 1.5)
        ],
    }
    segment_dir = candidate / "segment_detection"
    segment_dir.mkdir(parents=True)
    (segment_dir / "segment_selection.json").write_text(json.dumps({
        "selectedSegmentPath": str(selected_video.resolve()),
        "selectedSegmentSha256": hashlib.sha256(selected_video.read_bytes()).hexdigest(),
        "sourceVideoPath": str(parent_video.resolve()),
        "selectedSpanInOriginalSource": {"startSeconds": 0.713, "endSeconds": 2.8},
    }), encoding="utf-8")
    source_pose_reference_path = segment_dir / "exact_source_pose_reference.json"
    source_pose_reference_path.write_text(json.dumps({
        "sourceVideoSha256": hashlib.sha256(selected_video.read_bytes()).hexdigest(),
        "pose": pose,
    }), encoding="utf-8")

    def byte_identical_sanitize(path: Path) -> Path:
        sanitized = path.with_name(f"{path.stem}_sanitized{path.suffix}")
        shutil.copy2(path, sanitized)
        return sanitized

    monkeypatch.setattr(
        "exercise_motion_pkg.pipeline.sanitize_video_for_processing",
        byte_identical_sanitize,
    )
    generation_workspace = tmp_path / "generation"
    paths = PipelinePaths.create(generation_workspace, "squat")
    prepared_video = prepare_input_video(
        GenerateRequest(
            exercise_slug="squat",
            workspace=generation_workspace,
            video_path=selected_video,
            source_frame_clock_path=source_clock_path,
        ),
        paths,
    )
    prepared_clock_path = source_frame_clock_path_for_video(prepared_video)
    prepared_clock = load_verified_source_frame_clock(
        prepared_clock_path,
        expected_video_path=prepared_video,
    )
    assert prepared_video != selected_video
    assert prepared_clock["frames"] == selected_clock["frames"]
    assert prepared_clock["sourceVideoSha256"] == selected_clock["sourceVideoSha256"]
    assert prepared_clock["outputVideoSha256"] == selected_clock["outputVideoSha256"]
    assert prepared_clock["timelinePreservingTransform"] == "prepare_input_video_sanitization_copy"

    mapped_pose, mapping, error = _source_pose_on_motion_clock(
        pose,
        source_pose_reference_path=source_pose_reference_path,
        source_frame_clock_path=prepared_clock_path,
        input_video_path=prepared_video,
    )
    assert error is None
    assert mapping is not None
    assert [frame["sourceTimeSec"] for frame in mapped_pose["frames"]] == pytest.approx([
        frame["parentSourceTimeSec"]
        for frame in mapping["selectedFrameLineage"]
        if frame["selectedFrameTimeSec"] in {0.0, 0.5, 1.0, 1.5}
    ])


def test_sanitizer_reencode_preserves_verified_source_clock_by_decoded_pts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if resolve_ffmpeg_path() is None:
        pytest.skip("FFmpeg is required to verify sanitizer transcode clock propagation")

    parent_video = tmp_path / "parent-2997.mp4"
    selected_video = tmp_path / "input" / "selected_segment.mp4"
    selected_video.parent.mkdir(parents=True)
    _write_clock_test_video(parent_video, fps=30000.0 / 1001.0, frame_count=120)
    materialize_source_video_interval(
        source_path=parent_video,
        output_path=selected_video,
        start_seconds=0.713,
        end_seconds=2.8,
    )
    selected_clock = load_verified_source_frame_clock(
        source_frame_clock_path_for_video(selected_video),
        expected_video_path=selected_video,
    )
    original_run_ffmpeg = __import__("exercise_motion_pkg.youtube", fromlist=["_run_ffmpeg"])._run_ffmpeg

    def require_reencode(args: list[str]) -> tuple[int, str]:
        if "copy" in args:
            return 1, "test forces the sanitizer re-encode path"
        return original_run_ffmpeg(args)

    monkeypatch.setattr("exercise_motion_pkg.youtube._run_ffmpeg", require_reencode)
    sanitized_video = sanitize_downloaded_video(selected_video)
    assert sanitized_video != selected_video
    assert sanitized_video.is_file()
    assert hashlib.sha256(sanitized_video.read_bytes()).hexdigest() != selected_clock["outputVideoSha256"]

    sanitized_clock = load_verified_source_frame_clock(
        source_frame_clock_path_for_video(sanitized_video),
        expected_video_path=sanitized_video,
    )
    assert sanitized_clock["sourceVideoPath"] == selected_clock["sourceVideoPath"]
    assert sanitized_clock["sourceVideoSha256"] == selected_clock["sourceVideoSha256"]
    assert sanitized_clock["frames"] == selected_clock["frames"]
    assert sanitized_clock["timelinePreservingTransform"] == (
        "sanitize_downloaded_video_reencode_exact_decoded_pts"
    )
    assert sanitized_clock["transcodePtsProof"]["method"] == "decoded_frame_pts_and_order"
    assert sanitized_clock["transcodePtsProof"]["maximumRelativePtsErrorSec"] <= (
        sanitized_clock["transcodePtsProof"]["toleranceSec"]
    )


def test_exact_transcode_clock_rejects_same_count_retimed_output(tmp_path: Path) -> None:
    ffmpeg = resolve_ffmpeg_path()
    if ffmpeg is None:
        pytest.skip("FFmpeg is required to verify transcode retiming rejection")

    parent_video = tmp_path / "parent.mp4"
    selected_video = tmp_path / "selected.mp4"
    retimed_video = tmp_path / "retimed.mp4"
    _write_clock_test_video(parent_video, fps=30.0, frame_count=120)
    materialize_source_video_interval(
        source_path=parent_video,
        output_path=selected_video,
        start_seconds=0.5,
        end_seconds=1.5,
    )
    frame_count = read_basic_video_metadata(selected_video).frame_count
    assert frame_count >= 13
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i",
            str(selected_video), "-vf",
            rf"setpts=PTS+if(between(N\,10\,{frame_count}-2)\,0.5*({frame_count}-2-N)/({frame_count}-12)/TB\,0)",
            "-fps_mode", "passthrough", "-an", "-c:v", "mpeg4", "-q:v", "3",
            str(retimed_video),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert read_basic_video_metadata(retimed_video).frame_count == (
        read_basic_video_metadata(selected_video).frame_count
    )

    assert rebind_source_frame_clock_for_exact_transcode(
        source_video_path=selected_video,
        output_video_path=retimed_video,
        transform="test_same_count_retime",
    ) is None
    assert not source_frame_clock_path_for_video(retimed_video).exists()
