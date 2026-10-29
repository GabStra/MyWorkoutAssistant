from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from fractions import Fraction
from typing import Any

from .ffmpeg_utils import resolve_ffmpeg_path, resolve_ffprobe_path
from .video_utils import read_basic_video_metadata


SOURCE_FRAME_CLOCK_SCHEMA_VERSION = 2


def source_frame_clock_path_for_video(video_path: Path) -> Path:
    return video_path.with_suffix(".source_frame_clock.json")


def build_source_frame_clock(
    *,
    source_video_path: Path,
    output_video_path: Path,
    crop_start_seconds: float,
    output_fps: float,
    source_origin_seconds: float = 0.0,
) -> dict[str, Any]:
    """Describe the source exposures selected by the pipeline's CFR fps filter."""
    source_video_path = source_video_path.expanduser().resolve()
    output_video_path = output_video_path.expanduser().resolve()
    start = float(crop_start_seconds)
    source_origin = float(source_origin_seconds)
    target_fps = float(output_fps)
    if not math.isfinite(start) or start < 0.0:
        raise ValueError("crop_start_seconds must be finite and nonnegative")
    if not math.isfinite(source_origin):
        raise ValueError("source_origin_seconds must be finite")
    if not math.isfinite(target_fps) or target_fps <= 0.0:
        raise ValueError("output_fps must be finite and positive")

    source_metadata = read_basic_video_metadata(source_video_path)
    output_metadata = read_basic_video_metadata(output_video_path)
    source_fps = float(source_metadata.fps)
    if source_fps <= 0.0 or source_metadata.frame_count <= 0:
        raise ValueError("source video must have a positive CFR frame rate and at least one frame")
    if output_metadata.frame_count <= 0 or abs(output_metadata.fps - target_fps) > 0.02:
        raise ValueError("output video frame rate/count does not match its requested CFR timeline")
    source_pts_verification = _verify_constant_frame_rate_timestamps(
        source_video_path, expected_fps=source_fps,
        expected_frame_count=source_metadata.frame_count, video_role="source",
    )
    output_pts_verification = (
        source_pts_verification
        if source_video_path == output_video_path
        else _verify_constant_frame_rate_timestamps(
            output_video_path, expected_fps=target_fps,
            expected_frame_count=output_metadata.frame_count, video_role="prepared output",
        )
    )

    # Input-side -ss with accurate seeking keeps the first source frame at or
    # after the crop boundary. FFmpeg's fps filter then rounds that frame's
    # relative PTS to the nearest output tick; later frames are selected at
    # those quantized ticks. Consequently output frame n does not map to simply
    # round(n * source_fps / output_fps).
    first_source_index = max(0, math.ceil(start * source_fps - 1e-7))
    if first_source_index >= source_metadata.frame_count:
        raise ValueError("crop begins after the last decodable source frame")
    first_source_relative_time = first_source_index / source_fps - start
    first_output_tick = int(math.floor(first_source_relative_time * target_fps + 0.5 + 1e-7))
    frame_mappings = []
    for output_index in range(output_metadata.frame_count):
        source_time = start + (first_output_tick + output_index) / target_fps
        source_index = int(math.floor(source_time * source_fps + 0.5 + 1e-7))
        source_index = min(max(source_index, first_source_index), source_metadata.frame_count - 1)
        frame_mappings.append({
            "outputFrameIndex": output_index,
            "sourceFrameIndex": source_index,
            "sourceTimeSec": source_origin + source_index / source_fps,
        })

    return {
        "schemaVersion": SOURCE_FRAME_CLOCK_SCHEMA_VERSION,
        "sourceVideoPath": str(source_video_path),
        "sourceVideoSha256": sha256_file(source_video_path),
        "sourceFps": source_fps,
        "sourceFrameCount": source_metadata.frame_count,
        "sourceOriginTimeSec": source_origin,
        "outputVideoPath": str(output_video_path),
        "outputVideoSha256": sha256_file(output_video_path),
        "outputFps": float(output_metadata.fps),
        "outputFrameCount": output_metadata.frame_count,
        "cropStartSeconds": start,
        "sourcePtsVerification": source_pts_verification,
        "outputPtsVerification": output_pts_verification,
        "frames": frame_mappings,
    }


def write_source_frame_clock(receipt: dict[str, Any], *, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return output_path


def load_verified_source_frame_clock(
    receipt_path: Path,
    *,
    expected_video_path: Path | None = None,
) -> dict[str, Any]:
    receipt_path = receipt_path.expanduser().resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or receipt.get("schemaVersion") != SOURCE_FRAME_CLOCK_SCHEMA_VERSION:
        raise ValueError("unsupported source frame clock receipt")
    source_path = Path(str(receipt.get("sourceVideoPath", ""))).expanduser().resolve()
    output_path = Path(str(receipt.get("outputVideoPath", ""))).expanduser().resolve()
    if not source_path.is_file() or sha256_file(source_path) != receipt.get("sourceVideoSha256"):
        raise ValueError("source frame clock source identity does not match the retained video")
    if not output_path.is_file() or sha256_file(output_path) != receipt.get("outputVideoSha256"):
        raise ValueError("source frame clock output identity does not match the prepared video")
    if expected_video_path is not None and output_path != expected_video_path.expanduser().resolve():
        raise ValueError("source frame clock is bound to a different prepared video")
    frames = receipt.get("frames")
    if not isinstance(frames, list) or len(frames) != int(receipt.get("outputFrameCount", -1)):
        raise ValueError("source frame clock mapping count is invalid")
    source_fps = float(receipt.get("sourceFps", 0.0))
    source_count = int(receipt.get("sourceFrameCount", -1))
    source_origin = float(receipt.get("sourceOriginTimeSec", 0.0))
    if not math.isfinite(source_fps) or source_fps <= 0.0 or source_count <= 0 or not math.isfinite(source_origin):
        raise ValueError("source frame clock source timeline is invalid")
    source_metadata = read_basic_video_metadata(source_path)
    output_metadata = read_basic_video_metadata(output_path)
    if (source_metadata.frame_count != source_count
            or abs(source_metadata.fps - source_fps) > 0.02):
        raise ValueError("source frame clock source metadata no longer matches the retained video")
    if (output_metadata.frame_count != len(frames)
            or abs(output_metadata.fps - float(receipt.get("outputFps", 0.0))) > 0.02):
        raise ValueError("source frame clock output metadata no longer matches the prepared video")
    _verify_constant_frame_rate_timestamps(
        source_path, expected_fps=source_fps, expected_frame_count=source_count,
        video_role="source",
    )
    _verify_constant_frame_rate_timestamps(
        output_path, expected_fps=float(receipt["outputFps"]),
        expected_frame_count=len(frames), video_role="prepared output",
    )
    for index, item in enumerate(frames):
        if not isinstance(item, dict) or item.get("outputFrameIndex") != index:
            raise ValueError("source frame clock mapping is not a complete ordered timeline")
        source_index = item.get("sourceFrameIndex")
        source_time = item.get("sourceTimeSec")
        if type(source_index) is not int or not 0 <= source_index < source_count:
            raise ValueError("source frame clock mapping has an invalid source frame index")
        if not isinstance(source_time, (int, float)) or not math.isfinite(float(source_time)):
            raise ValueError("source frame clock mapping lacks a numeric exposure time")
        expected_time = source_origin + source_index / source_fps
        if abs(float(source_time) - expected_time) > 1e-6:
            raise ValueError("source frame clock exposure time does not match its source frame index")
        if index and float(source_time) < float(frames[index - 1]["sourceTimeSec"]):
            raise ValueError("source frame clock exposure times must be nondecreasing")
    return receipt


def source_times_for_frame_ids(receipt: dict[str, Any], frame_ids: list[int]) -> list[float]:
    return [reference["sourceTimeSec"] for reference in source_references_for_frame_ids(receipt, frame_ids)]


def source_references_for_frame_ids(
    receipt: dict[str, Any], frame_ids: list[int],
) -> list[dict[str, int | float]]:
    frames = receipt.get("frames")
    if not isinstance(frames, list):
        raise ValueError("source frame clock has no frame mapping")
    references: list[dict[str, int | float]] = []
    for frame_id in frame_ids:
        if frame_id < 0 or frame_id >= len(frames):
            raise ValueError(f"reconstruction frame id {frame_id} is outside the verified source clock")
        item = frames[frame_id]
        references.append({
            "sourceFrameIndex": int(item["sourceFrameIndex"]),
            "sourceTimeSec": float(item["sourceTimeSec"]),
        })
    return references


def source_exposure_crop_window(
    selected_receipt: dict[str, Any],
    inference_receipt: dict[str, Any],
) -> tuple[float, float]:
    """Return inference-local bounds for the selected cut's actual exposures.

    The selected interval's requested seek time can differ from the first
    decoded source exposure. Crop model output by the verified exposure clocks,
    not by subtracting requested trim timestamps.
    """
    for key in ("sourceVideoPath", "sourceVideoSha256", "sourceFps", "sourceOriginTimeSec"):
        if selected_receipt.get(key) != inference_receipt.get(key):
            raise ValueError("selected and inference clocks do not share one verified source timeline")
    selected_frames = selected_receipt.get("frames")
    inference_frames = inference_receipt.get("frames")
    try:
        inference_fps = float(inference_receipt["outputFps"])
        source_fps = float(selected_receipt["sourceFps"])
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError("source frame clocks lack valid frame rates") from error
    if (
        not isinstance(selected_frames, list) or not selected_frames
        or not isinstance(inference_frames, list) or not inference_frames
        or not math.isfinite(inference_fps) or inference_fps <= 0.0
        or not math.isfinite(source_fps) or source_fps <= 0.0
    ):
        raise ValueError("source frame clocks lack usable exposure rows")
    try:
        selected_times = [float(row["sourceTimeSec"]) for row in selected_frames]
        inference_times = [float(row["sourceTimeSec"]) for row in inference_frames]
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError("source frame clocks contain an invalid exposure time") from error
    if (
        not all(math.isfinite(value) for value in (*selected_times, *inference_times))
        or any(right < left for left, right in zip(selected_times, selected_times[1:]))
        or any(right < left for left, right in zip(inference_times, inference_times[1:]))
    ):
        raise ValueError("source frame clocks are not ordered exposure timelines")

    selected_start, selected_end = selected_times[0], selected_times[-1]
    # The selected cut can retain native-rate exposures while RECONSTRUCTION
    # runs at 30 fps. At a downsampled boundary, the nearest retained context
    # exposure may be one source tick away; include half a context tick plus
    # half a source tick for the two verified frame lattices' quantization.
    tolerance = max(1e-6, 0.51 / inference_fps + 0.51 / source_fps)
    selected_indices = [
        index for index, source_time in enumerate(inference_times)
        if selected_start - 1e-6 <= source_time <= selected_end + 1e-6
    ]
    if (
        not selected_indices
        or abs(inference_times[selected_indices[0]] - selected_start) > tolerance
        or abs(inference_times[selected_indices[-1]] - selected_end) > tolerance
    ):
        raise ValueError("inference context does not cover the selected source exposures")
    first_index, last_index = selected_indices[0], selected_indices[-1]
    return first_index / inference_fps, (last_index + 1) / inference_fps


def recover_materialized_cut_clock(
    *,
    selection: dict[str, Any],
    selected_video_path: Path,
    expected_parent_sha256: str | None = None,
) -> dict[str, Any]:
    """Rebuild a cut clock only from a hash-bound, directly materialized cut.

    The retained selection must identify the exact cut bytes, their parent video,
    and the crop interval. For older selection receipts that lack the explicit
    parent fields, recovery is limited to a direct source cut whose source and
    original-source spans agree. Decoded-frame matching then verifies that every
    cut exposure corresponds to its claimed parent exposure.
    """
    selected_video_path = selected_video_path.expanduser().resolve()
    if not selected_video_path.is_file():
        raise ValueError("selected cut is unavailable for source-clock recovery")
    if Path(str(selection.get("selectedSegmentPath") or "")).expanduser().resolve() != selected_video_path:
        raise ValueError("selection receipt is not bound to the selected cut path")
    selected_sha = sha256_file(selected_video_path)
    if str(selection.get("selectedSegmentSha256") or "").casefold() != selected_sha:
        raise ValueError("selection receipt is not bound to the selected cut bytes")
    materialization = str(selection.get("selectedSegmentMaterialization") or "")
    if materialization not in {"trimmed_source_window", "trimmed_ranked_window", "source_copy_full_range"}:
        raise ValueError("selected cut does not have a recoverable direct-materialization marker")

    parent_value = selection.get("selectedSegmentSourceVideoPath")
    crop_start_value = selection.get("selectedSegmentCropStartSeconds")
    crop_end_value = selection.get("selectedSegmentCropEndSeconds")
    parent_sha_value = selection.get("selectedSegmentSourceVideoSha256")
    if not parent_value:
        # Compatibility with retained receipts produced before the explicit
        # materialization lineage fields were added. Do not infer through a
        # detection proxy or an interval expressed in another video's clock.
        source_path_value = selection.get("sourceVideoPath")
        detection_path_value = selection.get("detectionSourceVideoPath")
        span = selection.get("selectedSpanInOriginalSource")
        if (
            not source_path_value
            or (detection_path_value and Path(str(detection_path_value)).expanduser().resolve()
                != Path(str(source_path_value)).expanduser().resolve())
            or not isinstance(span, dict)
        ):
            raise ValueError("selected cut parent source is not unambiguously recorded")
        parent_value = source_path_value
        crop_start_value = span.get("startSeconds")
        crop_end_value = span.get("endSeconds")
    parent_path = Path(str(parent_value)).expanduser().resolve()
    if not parent_path.is_file():
        raise ValueError("selected cut parent source is unavailable")
    recorded_parent_hash = (
        parent_sha_value
        or selection.get("sourceVideoSha256")
        or selection.get("originalSourceVideoSha256")
    )
    actual_parent_sha = sha256_file(parent_path)
    if recorded_parent_hash and actual_parent_sha != str(recorded_parent_hash).casefold():
        raise ValueError("selected cut parent source bytes changed since materialization")
    if expected_parent_sha256 and actual_parent_sha != str(expected_parent_sha256).casefold():
        raise ValueError("selected cut parent source hash conflicts with inference context clock")
    try:
        crop_start = float(crop_start_value)
        crop_end = float(crop_end_value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("selected cut materialization interval is unavailable") from error
    if not math.isfinite(crop_start) or not math.isfinite(crop_end) or crop_start < 0.0 or crop_end <= crop_start:
        raise ValueError("selected cut materialization interval is invalid")

    if materialization == "source_copy_full_range":
        if crop_start != 0.0 or sha256_file(parent_path) != selected_sha:
            raise ValueError("full-source cut copy identity could not be verified")
    elif materialization == "trimmed_ranked_window" and not selection.get("selectedSegmentSourceVideoPath"):
        # This marker can refer to a ranker proxy in historical manifests, so
        # only accept it when the exact parent is named explicitly.
        raise ValueError("ranked cut parent source is not explicitly recorded")

    selected_metadata = read_basic_video_metadata(selected_video_path)
    receipt = build_source_frame_clock(
        source_video_path=parent_path,
        output_video_path=selected_video_path,
        crop_start_seconds=crop_start,
        output_fps=float(selected_metadata.fps),
    )
    if recorded_parent_hash and receipt.get("sourceVideoSha256") != str(recorded_parent_hash).casefold():
        raise ValueError("selected cut recovered clock source hash does not match its receipt")
    first_exposure = float(receipt["frames"][0]["sourceTimeSec"])
    last_exposure = float(receipt["frames"][-1]["sourceTimeSec"])
    exposure_tolerance = max(1e-6, 0.51 / float(receipt["sourceFps"]))
    if first_exposure < crop_start - exposure_tolerance or last_exposure >= crop_end + exposure_tolerance:
        raise ValueError("selected cut clock exposures extend outside the approved materialization interval")
    if materialization != "source_copy_full_range":
        _verify_decoded_cut_exposures(
            parent_path,
            selected_video_path,
            receipt,
            require_unique=not bool(recorded_parent_hash or expected_parent_sha256),
        )
    upstream_clock_path = source_frame_clock_path_for_video(parent_path)
    if upstream_clock_path.is_file():
        upstream = load_verified_source_frame_clock(
            upstream_clock_path,
            expected_video_path=parent_path,
        )
        receipt = compose_source_frame_clocks(upstream, receipt)
    return receipt


def _verify_decoded_cut_exposures(
    parent_video_path: Path,
    cut_video_path: Path,
    receipt: dict[str, Any],
    *,
    require_unique: bool,
) -> None:
    """Verify cut frames against their mapped parent exposures after transcoding."""
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise ValueError("decoded-frame verification is unavailable") from error
    parent = cv2.VideoCapture(str(parent_video_path))
    cut = cv2.VideoCapture(str(cut_video_path))
    if not parent.isOpened() or not cut.isOpened():
        parent.release()
        cut.release()
        raise ValueError("could not decode selected cut and its parent source")
    rows = receipt.get("frames")
    if not isinstance(rows, list) or not rows:
        parent.release()
        cut.release()
        raise ValueError("selected cut clock has no exposure rows")
    try:
        source_count = int(receipt["sourceFrameCount"])
        expected_indices = [int(row["sourceFrameIndex"]) for row in rows]
        window_start = max(0, min(expected_indices) - 2)
        window_end = min(source_count, max(expected_indices) + 3)
        parent.set(cv2.CAP_PROP_POS_FRAMES, window_start)
        source_frames = {}
        for source_index in range(window_start, window_end):
            ok, frame = parent.read()
            if not ok:
                raise ValueError("parent source ended before its verified clock exposures")
            frame = cv2.resize(frame, (64, 64), interpolation=cv2.INTER_AREA)
            source_frames[source_index] = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        for row in rows:
            ok, frame = cut.read()
            if not ok:
                raise ValueError("selected cut ended before its verified clock")
            frame = cv2.resize(frame, (64, 64), interpolation=cv2.INTER_AREA)
            cut_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
            expected = int(row["sourceFrameIndex"])
            # Reject ambiguous/reordered matches. Exact encoding differs after
            # the cut transcode, so compare the claimed exposure with its nearby
            # competing frames. The retained interval/hash/producer receipt bound
            # the search to this part of the parent rather than scanning the clip.
            competitors = range(max(0, expected - 2), min(source_count, expected + 3))
            errors = {
                index: float(np.mean(np.abs(cut_gray - source_frames[index])))
                for index in competitors
            }
            if expected not in errors or min(errors, key=errors.get) != expected:
                raise ValueError("selected cut exposure does not match its claimed parent frame")
            runner_up = min(value for index, value in errors.items() if index != expected)
            if require_unique and not runner_up > errors[expected] + 1e-6:
                raise ValueError("selected cut exposure is ambiguous in the parent source")
        if cut.read()[0]:
            raise ValueError("selected cut has more frames than its verified clock")
    finally:
        parent.release()
        cut.release()


def verified_source_timeline_mapping(
    *,
    workspace: Path,
    source_pose: dict[str, Any],
    clock_receipt: dict[str, Any],
    expected_motion_video_path: Path | None = None,
) -> dict[str, Any] | None:
    """Prove exact selected-cut pose exposure lineage against a parent clock.

    The selected interval start is request metadata, not the first decoded
    exposure. This mapping binds the selected video, source-pose payload,
    selected-cut clock, and motion-input clock before exposing frame lineage.
    """
    from .reconstruction_compat import loads_reconstruction_metadata

    if not isinstance(source_pose, dict) or not isinstance(clock_receipt, dict):
        return None
    workspace = workspace.expanduser().resolve()
    selection_path = workspace / "segment_detection" / "segment_selection.json"
    selected_video_path = workspace / "input" / "selected_segment.mp4"
    reference_path = workspace / "segment_detection" / "exact_source_pose_reference.json"

    def optional_float(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def optional_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if number == value else None

    try:
        selection_bytes = selection_path.read_bytes()
        selection = loads_reconstruction_metadata(selection_bytes.decode("utf-8-sig"))
        reference = loads_reconstruction_metadata(reference_path.read_text(encoding="utf-8"))
        selected_video_sha = sha256_file(selected_video_path)
        selected_path_receipt = Path(str(selection.get("selectedSegmentPath") or "")).expanduser().resolve()
        selected_sha_receipt = str(selection.get("selectedSegmentSha256") or "").casefold()
        span = selection.get("selectedSpanInOriginalSource")
        parent_video_path = Path(str(selection.get("sourceVideoPath") or "")).expanduser().resolve()
        origin = optional_float(span.get("startSeconds")) if isinstance(span, dict) else None
        source_pose_video_sha = str(reference.get("sourceVideoSha256") or "").casefold()
        source_pose_reference_sha = sha256_file(reference_path)

        parent_output_path = Path(str(clock_receipt.get("outputVideoPath") or "")).expanduser().resolve()
        if expected_motion_video_path is not None and parent_output_path != expected_motion_video_path.expanduser().resolve():
            return None
        parent_clock_path = source_frame_clock_path_for_video(parent_output_path)
        parent_clock = load_verified_source_frame_clock(
            parent_clock_path,
            expected_video_path=parent_output_path,
        )
        # The argument is a caller-provided handoff; the on-disk, hash-verified
        # receipt remains authoritative and must agree on its source identity.
        for key in ("sourceVideoPath", "sourceVideoSha256", "outputVideoPath", "outputVideoSha256"):
            if clock_receipt.get(key) != parent_clock.get(key):
                return None
        parent_clock_sha = str(parent_clock.get("sourceVideoSha256") or "").casefold()
        parent_video_sha = sha256_file(parent_video_path)
        parent_clock_receipt_sha = sha256_file(parent_clock_path)
        selected_clock_path = source_frame_clock_path_for_video(selected_video_path)
        selected_clock = load_verified_source_frame_clock(
            selected_clock_path,
            expected_video_path=selected_video_path,
        )
        selected_clock_sha = sha256_file(selected_clock_path)
    except (OSError, ValueError, TypeError, AttributeError):
        return None

    if (
        selected_path_receipt != selected_video_path.resolve()
        or not selected_sha_receipt
        or selected_sha_receipt != selected_video_sha
        or not parent_video_path.is_file()
        or Path(str(parent_clock.get("sourceVideoPath") or "")).expanduser().resolve() != parent_video_path
        or parent_clock_sha != parent_video_sha
        or Path(str(selected_clock.get("sourceVideoPath") or "")).expanduser().resolve() != parent_video_path
        or str(selected_clock.get("sourceVideoSha256") or "").casefold() != parent_video_sha
        or source_pose_video_sha != selected_video_sha
        or origin is None
        or origin < 0.0
    ):
        return None

    frames = source_pose.get("frames")
    if (
        optional_float(source_pose.get("sourceTimeOriginSec")) is None
        or not isinstance(frames, list)
        or not frames
        or any(optional_float(frame.get("sourceTimeSec")) is None for frame in frames if isinstance(frame, dict))
        or any(not isinstance(frame, dict) for frame in frames)
    ):
        return None
    selected_clock_frames = selected_clock.get("frames")
    parent_clock_origin = optional_float(parent_clock.get("sourceOriginTimeSec"))
    selected_clock_origin = optional_float(selected_clock.get("sourceOriginTimeSec"))
    selected_clock_crop_start = optional_float(selected_clock.get("cropStartSeconds"))
    if (
        not isinstance(selected_clock_frames, list)
        or len(selected_clock_frames) != optional_int(selected_clock.get("outputFrameCount"))
        or parent_clock_origin is None
        or selected_clock_origin is None
        or selected_clock_crop_start is None
        or abs(parent_clock_origin - selected_clock_origin) > 1e-6
        or abs(selected_clock_crop_start + selected_clock_origin - origin) > 1e-6
    ):
        return None

    try:
        pose_text = json.dumps(
            source_pose,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    selected_output_fps = optional_float(selected_clock.get("outputFps"))
    parent_source_fps = optional_float(selected_clock.get("sourceFps"))
    if selected_output_fps is None or selected_output_fps <= 0.0 or parent_source_fps is None or parent_source_fps <= 0.0:
        return None
    selected_frame_lineage = [{
        "selectedFrameIndex": int(frame["outputFrameIndex"]),
        "selectedFrameTimeSec": int(frame["outputFrameIndex"]) / selected_output_fps,
        "parentSourceFrameIndex": int(frame["sourceFrameIndex"]),
        "parentSourceTimeSec": float(frame["sourceTimeSec"]),
    } for frame in selected_clock_frames]
    return {
        "schemaVersion": 1,
        "verified": True,
        "mappingKind": "selected_segment_to_parent_source",
        "selectedStartSeconds": origin,
        "originSeconds": origin,
        "selectedPoseLocalOriginSeconds": optional_float(source_pose.get("sourceTimeOriginSec")),
        "selectedFrameClockReceiptPath": str(selected_clock_path.resolve()),
        "selectedFrameClockReceiptSha256": selected_clock_sha,
        "parentSourceFps": parent_source_fps,
        "selectedOutputFps": selected_output_fps,
        "selectedFrameCount": len(selected_frame_lineage),
        "selectedFrameLineage": selected_frame_lineage,
        "selectedSegmentPath": str(selected_video_path.resolve()),
        "selectedSegmentSha256": selected_video_sha,
        "parentSourceVideoPath": str(parent_video_path),
        "parentSourceSha256": parent_video_sha,
        "sourceVideoPath": str(parent_video_path),
        "sourceVideoSha256": parent_video_sha,
        "selectionReceiptPath": str(selection_path.resolve()),
        "selectionReceiptSha256": hashlib.sha256(selection_bytes).hexdigest(),
        "sourcePoseReferencePath": str(reference_path.resolve()),
        "sourcePoseReferenceSha256": source_pose_reference_sha,
        "sourcePosePayloadSha256": hashlib.sha256(pose_text.encode("utf-8")).hexdigest(),
        "clockReceiptPath": str(parent_clock_path.resolve()),
        "clockReceiptSha256": parent_clock_receipt_sha,
        "parentClockOutputSha256": str(parent_clock.get("outputVideoSha256") or "").casefold(),
        "parentClockSourceVideoSha256": parent_clock_sha,
        "parentSourceFrameCount": optional_int(parent_clock.get("sourceFrameCount")),
        "parentSourceTimeOriginSec": optional_float(parent_clock.get("sourceOriginTimeSec")) or 0.0,
        "selectedEndSeconds": optional_float(span.get("endSeconds")) if isinstance(span, dict) else None,
    }


def rebind_source_frame_clock(
    receipt: dict[str, Any],
    *,
    output_video_path: Path,
    transform: str,
) -> dict[str, Any]:
    """Carry a clock through a timeline-preserving image transform, fail closed otherwise."""
    if receipt.get("schemaVersion") != SOURCE_FRAME_CLOCK_SCHEMA_VERSION:
        raise ValueError("cannot rebind an unverified legacy source frame clock")
    source_path = Path(str(receipt.get("sourceVideoPath", ""))).expanduser().resolve()
    parent_output_path = Path(str(receipt.get("outputVideoPath", ""))).expanduser().resolve()
    if (not source_path.is_file()
            or sha256_file(source_path) != receipt.get("sourceVideoSha256")):
        raise ValueError("cannot rebind source frame clock with a changed source video")
    if (not parent_output_path.is_file()
            or sha256_file(parent_output_path) != receipt.get("outputVideoSha256")):
        raise ValueError("cannot rebind source frame clock with a changed prepared input")
    _verify_constant_frame_rate_timestamps(
        source_path, expected_fps=float(receipt.get("sourceFps", 0.0)),
        expected_frame_count=int(receipt.get("sourceFrameCount", -1)), video_role="source",
    )
    _verify_constant_frame_rate_timestamps(
        parent_output_path, expected_fps=float(receipt.get("outputFps", 0.0)),
        expected_frame_count=int(receipt.get("outputFrameCount", -1)), video_role="prepared input",
    )
    output_video_path = output_video_path.expanduser().resolve()
    output_metadata = read_basic_video_metadata(output_video_path)
    if (
        output_metadata.frame_count != int(receipt.get("outputFrameCount", -1))
        or abs(float(output_metadata.fps) - float(receipt.get("outputFps", 0.0))) > 0.02
    ):
        raise ValueError(f"{transform} changed the source-clock frame timeline")
    _verify_constant_frame_rate_timestamps(
        output_video_path, expected_fps=float(receipt.get("outputFps", 0.0)),
        expected_frame_count=int(receipt.get("outputFrameCount", -1)),
        video_role=f"{transform} output",
    )
    rebound = dict(receipt)
    rebound["parentOutputVideoPath"] = receipt.get("outputVideoPath")
    rebound["parentOutputVideoSha256"] = receipt.get("outputVideoSha256")
    rebound["outputVideoPath"] = str(output_video_path)
    rebound["outputVideoSha256"] = sha256_file(output_video_path)
    rebound["timelinePreservingTransform"] = transform
    return rebound


def rebind_existing_source_frame_clock_for_video_copy(
    *,
    source_video_path: Path,
    output_video_path: Path,
    transform: str,
    source_clock_path: Path | None = None,
) -> Path | None:
    """Rebind a verified clock only when a prepared copy is byte-identical."""
    source_video_path = source_video_path.expanduser().resolve()
    output_video_path = output_video_path.expanduser().resolve()
    input_clock_path = (
        source_clock_path.expanduser().resolve()
        if source_clock_path is not None
        else source_frame_clock_path_for_video(source_video_path)
    )
    output_clock_path = source_frame_clock_path_for_video(output_video_path)
    if not input_clock_path.is_file():
        return None
    try:
        # Matching FPS and frame count do not prove exposure identity.
        if sha256_file(source_video_path) != sha256_file(output_video_path):
            return None
        receipt = load_verified_source_frame_clock(
            input_clock_path,
            expected_video_path=source_video_path,
        )
        if source_video_path == output_video_path and input_clock_path == output_clock_path:
            return output_clock_path
        rebound = rebind_source_frame_clock(
            receipt,
            output_video_path=output_video_path,
            transform=transform,
        )
    except (OSError, ValueError, TypeError):
        return None
    return write_source_frame_clock(rebound, output_path=output_clock_path)


def rebind_source_frame_clock_for_exact_transcode(
    *,
    source_video_path: Path,
    output_video_path: Path,
    source_clock_path: Path | None = None,
    transform: str,
) -> Path | None:
    """Compose a source clock through a transcode only when decoded PTS prove 1:1 frames."""
    source_video_path = source_video_path.expanduser().resolve()
    output_video_path = output_video_path.expanduser().resolve()
    input_clock_path = (
        source_clock_path.expanduser().resolve()
        if source_clock_path is not None
        else source_frame_clock_path_for_video(source_video_path)
    )
    output_clock_path = source_frame_clock_path_for_video(output_video_path)
    if not input_clock_path.is_file() or source_video_path == output_video_path:
        return None
    try:
        upstream = load_verified_source_frame_clock(
            input_clock_path,
            expected_video_path=source_video_path,
        )
        source_metadata = read_basic_video_metadata(source_video_path)
        output_metadata = read_basic_video_metadata(output_video_path)
        source_pts, source_time_base = _read_decoded_frame_timestamps(
            source_video_path, video_role="transcode input",
        )
        output_pts, output_time_base = _read_decoded_frame_timestamps(
            output_video_path, video_role="transcode output",
        )
        source_verification = _verify_timestamp_rows(
            source_pts,
            source_time_base,
            expected_fps=float(source_metadata.fps),
            expected_frame_count=int(source_metadata.frame_count),
            video_role="transcode input",
        )
        output_verification = _verify_timestamp_rows(
            output_pts,
            output_time_base,
            expected_fps=float(output_metadata.fps),
            expected_frame_count=int(output_metadata.frame_count),
            video_role="transcode output",
        )
        if (
            source_metadata.frame_count != output_metadata.frame_count
            or abs(float(source_metadata.fps) - float(output_metadata.fps)) > 0.02
            or len(source_pts) != len(output_pts)
            or not source_pts
        ):
            raise ValueError("sanitizer transcode changed its decoded frame sequence")
        period = 1.0 / float(source_metadata.fps)
        tolerance = min(
            max(source_time_base, output_time_base, 1e-7) * 1.1,
            period * 0.01,
        )
        max_relative_pts_error = max(
            abs((output_pts[index] - output_pts[0]) - (source_pts[index] - source_pts[0]))
            for index in range(len(source_pts))
        )
        if max_relative_pts_error > tolerance:
            raise ValueError(
                "sanitizer transcode PTS do not preserve one-to-one source exposures"
            )

        downstream_frames = [
            {
                "outputFrameIndex": index,
                "sourceFrameIndex": index,
                "sourceTimeSec": source_pts[index],
            }
            for index in range(len(source_pts))
        ]
        downstream = {
            "schemaVersion": SOURCE_FRAME_CLOCK_SCHEMA_VERSION,
            "sourceVideoPath": str(source_video_path),
            "sourceVideoSha256": sha256_file(source_video_path),
            "sourceFps": float(source_metadata.fps),
            "sourceFrameCount": int(source_metadata.frame_count),
            "sourceOriginTimeSec": float(source_pts[0]),
            "outputVideoPath": str(output_video_path),
            "outputVideoSha256": sha256_file(output_video_path),
            "outputFps": float(output_metadata.fps),
            "outputFrameCount": len(output_pts),
            "cropStartSeconds": 0.0,
            "sourcePtsVerification": source_verification,
            "outputPtsVerification": output_verification,
            "frames": downstream_frames,
            "timelinePreservingTransform": transform,
            "transcodePtsProof": {
                "method": "decoded_frame_pts_and_order",
                "frameCount": len(source_pts),
                "maximumRelativePtsErrorSec": max_relative_pts_error,
                "toleranceSec": tolerance,
                "inputTimeBaseSec": source_time_base,
                "outputTimeBaseSec": output_time_base,
            },
        }
        composed = compose_source_frame_clocks(upstream, downstream)
        composed["timelinePreservingTransform"] = transform
        composed["transcodePtsProof"] = downstream["transcodePtsProof"]
        write_source_frame_clock(composed, output_path=output_clock_path)
        load_verified_source_frame_clock(
            output_clock_path,
            expected_video_path=output_video_path,
        )
        return output_clock_path
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        output_clock_path.unlink(missing_ok=True)
        return None


def compose_source_frame_clocks(
    upstream: dict[str, Any],
    downstream: dict[str, Any],
) -> dict[str, Any]:
    """Compose output→intermediate and intermediate→source clocks exactly.

    Both inputs must already be verified receipts. Frame indices from the
    downstream receipt select rows in the upstream receipt, preserving the
    decoded source exposure identity (including repeated exposures).
    """
    if upstream.get("schemaVersion") != SOURCE_FRAME_CLOCK_SCHEMA_VERSION or \
            downstream.get("schemaVersion") != SOURCE_FRAME_CLOCK_SCHEMA_VERSION:
        raise ValueError("cannot compose an unverified legacy source frame clock")
    intermediate_path = Path(str(upstream.get("outputVideoPath", ""))).expanduser().resolve()
    downstream_source_path = Path(str(downstream.get("sourceVideoPath", ""))).expanduser().resolve()
    if (intermediate_path != downstream_source_path
            or str(upstream.get("outputVideoSha256", "")).casefold()
            != str(downstream.get("sourceVideoSha256", "")).casefold()):
        raise ValueError("source frame clocks do not share an exact intermediate video")
    upstream_frames = upstream.get("frames")
    downstream_frames = downstream.get("frames")
    if (not isinstance(upstream_frames, list) or not isinstance(downstream_frames, list)
            or len(upstream_frames) != int(upstream.get("outputFrameCount", -1))
            or len(downstream_frames) != int(downstream.get("outputFrameCount", -1))):
        raise ValueError("source frame clock composition has an incomplete frame table")

    composed_frames = []
    for output_index, output_row in enumerate(downstream_frames):
        if not isinstance(output_row, dict) or output_row.get("outputFrameIndex") != output_index:
            raise ValueError("downstream source frame clock is not an ordered frame table")
        intermediate_index = output_row.get("sourceFrameIndex")
        if type(intermediate_index) is not int or not 0 <= intermediate_index < len(upstream_frames):
            raise ValueError("downstream source frame clock references an invalid intermediate frame")
        source_row = upstream_frames[intermediate_index]
        if (not isinstance(source_row, dict)
                or source_row.get("outputFrameIndex") != intermediate_index):
            raise ValueError("upstream source frame clock is not an ordered frame table")
        source_index = source_row.get("sourceFrameIndex")
        source_time = source_row.get("sourceTimeSec")
        if (type(source_index) is not int or not isinstance(source_time, (int, float))
                or not math.isfinite(float(source_time))):
            raise ValueError("upstream source frame clock has an invalid source exposure")
        composed_frames.append({
            "outputFrameIndex": output_index,
            "sourceFrameIndex": source_index,
            "sourceTimeSec": float(source_time),
        })

    upstream_digest = hashlib.sha256(
        json.dumps(upstream, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    downstream_digest = hashlib.sha256(
        json.dumps(downstream, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return {
        "schemaVersion": SOURCE_FRAME_CLOCK_SCHEMA_VERSION,
        "sourceVideoPath": upstream["sourceVideoPath"],
        "sourceVideoSha256": upstream["sourceVideoSha256"],
        "sourceFps": upstream["sourceFps"],
        "sourceFrameCount": upstream["sourceFrameCount"],
        "sourceOriginTimeSec": upstream.get("sourceOriginTimeSec", 0.0),
        "outputVideoPath": downstream["outputVideoPath"],
        "outputVideoSha256": downstream["outputVideoSha256"],
        "outputFps": downstream["outputFps"],
        "outputFrameCount": downstream["outputFrameCount"],
        "cropStartSeconds": (
            float(upstream.get("cropStartSeconds", 0.0))
            + float(downstream.get("cropStartSeconds", 0.0))
        ),
        "sourcePtsVerification": upstream.get("sourcePtsVerification"),
        "outputPtsVerification": downstream.get("outputPtsVerification"),
        "frames": composed_frames,
        "frameClockComposition": {
            "intermediateVideoSha256": upstream["outputVideoSha256"],
            "upstreamReceiptSha256": upstream_digest,
            "downstreamReceiptSha256": downstream_digest,
        },
    }


def _verify_constant_frame_rate_timestamps(
    video_path: Path,
    *,
    expected_fps: float,
    expected_frame_count: int,
    video_role: str,
) -> dict[str, float | int]:
    """Reject a nominal-FPS clock unless real decoded frame PTS form a CFR grid."""
    timestamps, time_base = _read_decoded_frame_timestamps(video_path, video_role=video_role)
    return _verify_timestamp_rows(
        timestamps,
        time_base,
        expected_fps=expected_fps,
        expected_frame_count=expected_frame_count,
        video_role=video_role,
    )


def _verify_timestamp_rows(
    timestamps: list[float],
    time_base: float,
    *,
    expected_fps: float,
    expected_frame_count: int,
    video_role: str,
) -> dict[str, float | int]:
    if (not math.isfinite(expected_fps) or expected_fps <= 0.0
            or expected_frame_count <= 0 or len(timestamps) != expected_frame_count
            or not math.isfinite(time_base) or time_base <= 0.0
            or not all(math.isfinite(value) for value in timestamps)):
        raise ValueError(
            f"{video_role} frame PTS/count are incomplete; refusing an exact source clock"
        )
    # Account for container timestamp quantization, but never let a coarse time
    # base hide a meaningful fraction of a missing/duplicated source frame.
    frame_period = 1.0 / expected_fps
    tolerance = min(max(time_base * 1.1, 1e-7), frame_period * 0.01)
    maximum_grid_error = 0.0
    origin = timestamps[0]
    for index, timestamp in enumerate(timestamps):
        grid_error = abs((timestamp - origin) - index / expected_fps)
        maximum_grid_error = max(maximum_grid_error, grid_error)
        if grid_error > tolerance:
            raise ValueError(
                f"{video_role} is variable-frame-rate or does not match its nominal FPS "
                f"(frame {index} PTS grid error {grid_error:.9g}s, tolerance {tolerance:.9g}s); "
                "exact source clock unavailable"
            )
    return {
        "frameCount": len(timestamps),
        "fps": float(expected_fps),
        "timeBaseSec": float(time_base),
        "maximumGridErrorSec": float(maximum_grid_error),
    }


def _read_decoded_frame_timestamps(
    video_path: Path,
    *,
    video_role: str,
) -> tuple[list[float], float]:
    """Read actual decoded video-frame timestamps using ffprobe or ffmpeg showinfo."""
    ffprobe = resolve_ffprobe_path()
    if ffprobe is not None:
        try:
            result = subprocess.run(
                [
                    ffprobe, "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=time_base:frame=best_effort_timestamp_time",
                    "-of", "json", str(video_path),
                ],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(
                f"cannot verify {video_role} frame PTS; refusing an exact source clock"
            ) from exc
        if result.returncode != 0:
            raise ValueError(
                f"cannot inspect {video_role} frame PTS; refusing an exact source clock: "
                f"{result.stderr.strip()}"
            )
        try:
            payload = json.loads(result.stdout)
            streams = payload.get("streams") or []
            rows = payload.get("frames") or []
            time_base = float(Fraction(str(streams[0]["time_base"])))
            timestamps = [float(row["best_effort_timestamp_time"]) for row in rows]
        except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"cannot read {video_role} frame PTS; refusing an exact source clock"
            ) from exc
    else:
        ffmpeg = resolve_ffmpeg_path()
        if ffmpeg is None:
            raise ValueError(
                f"cannot verify {video_role} frame PTS without ffprobe or ffmpeg; "
                "refusing an exact source clock"
            )
        try:
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "info", "-i", str(video_path),
                 "-map", "0:v:0", "-vf", "showinfo", "-an", "-sn", "-dn",
                 "-f", "null", os.devnull],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(
                f"cannot verify {video_role} frame PTS; refusing an exact source clock"
            ) from exc
        if result.returncode != 0:
            raise ValueError(
                f"cannot inspect {video_role} frame PTS; refusing an exact source clock: "
                f"{result.stderr.strip()}"
            )
        time_base_match = re.search(
            r"config in time_base:\s*(\d+/\d+)", result.stderr,
        )
        frame_rows = re.findall(
            r"\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:([+-]?[\d.]+)",
            result.stderr,
        )
        try:
            time_base = float(Fraction(time_base_match.group(1))) if time_base_match else 0.0
            timestamps = [float(value) for value in frame_rows]
        except (AttributeError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise ValueError(
                f"cannot read {video_role} frame PTS; refusing an exact source clock"
            ) from exc
    if (not math.isfinite(time_base) or time_base <= 0.0
            or not timestamps or not all(math.isfinite(value) for value in timestamps)):
        raise ValueError(
            f"{video_role} frame PTS are incomplete; refusing an exact source clock"
        )
    return timestamps, time_base


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
