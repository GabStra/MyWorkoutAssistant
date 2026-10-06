"""Shared validation for the frames and selected interval sent to final review."""
from __future__ import annotations

import math
from typing import Any

from .artifact_state import BOUNDED_MOVEMENT_REBAKE, CYCLIC_REBAKE


def sample_review_frame_indices(export_payload: dict[str, Any], count: int) -> list[int]:
    frames = export_payload.get("frames")
    declared_frame_count = export_payload.get("frameCount")
    frame_count = (
        int(declared_frame_count)
        if isinstance(declared_frame_count, (int, float))
        and not isinstance(declared_frame_count, bool)
        and math.isfinite(float(declared_frame_count))
        and float(declared_frame_count) > 0
        else len(frames) if isinstance(frames, list) else 0
    )
    if frame_count <= 0:
        return [0]
    sample_count = max(1, min(int(count), frame_count))
    if sample_count == frame_count:
        return list(range(frame_count))
    if sample_count == 1:
        return [frame_count // 2]
    return sorted(
        {
            round(index * (frame_count - 1) / (sample_count - 1))
            for index in range(sample_count)
        }
    )


def _frame_time_seconds(frame: dict[str, Any], *, fallback_index: int, fps: float) -> float:
    for key in ("sourceTimeSec", "frameIndex"):
        value = frame.get(key)
        if isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed if key == "sourceTimeSec" else parsed / fps
    return fallback_index / fps


def frame_timestamps_for_indices(
    export_payload: dict[str, Any], frame_indices: list[int | float]
) -> list[float]:
    frames = export_payload.get("frames")
    if not isinstance(frames, list):
        return []
    fps_value = export_payload.get("fps")
    fps = (
        float(fps_value)
        if isinstance(fps_value, (int, float))
        and not isinstance(fps_value, bool)
        and math.isfinite(float(fps_value))
        and float(fps_value) > 0
        else 30.0
    )
    timestamps: list[float] = []
    for frame_index in frame_indices:
        base_index = math.floor(frame_index)
        frame = frames[base_index] if 0 <= base_index < len(frames) else {}
        if not isinstance(frame, dict):
            frame = {}
        timestamps.append(
            _frame_time_seconds(frame, fallback_index=base_index, fps=fps)
            + (frame_index - base_index) / fps
        )
    return timestamps


def artifact_review_selection(
    artifact_state: dict[str, Any], movement_payload: dict[str, Any]
) -> dict[str, Any]:
    artifact_class = artifact_state["artifactClass"]
    evidence = artifact_state.get("selectionEvidence") or {}
    if artifact_class == CYCLIC_REBAKE:
        selected = evidence["cycleSelection"]
        return {
            "artifactClass": artifact_class,
            "selectionId": selected["selectionId"],
            "interval": selected["interval"],
        }
    if artifact_class == BOUNDED_MOVEMENT_REBAKE:
        selected = evidence["boundedMovementSelection"]
        return {
            "artifactClass": artifact_class,
            "selectionId": selected["selectionId"],
            "interval": selected["interval"],
        }

    loop = movement_payload.get("loop")
    frames = movement_payload.get("frames")
    if not isinstance(loop, dict) or not isinstance(frames, list) or not frames:
        raise ValueError("Full-clip review is missing its materialized source interval")
    first = frames[0] if isinstance(frames[0], dict) else {}
    last = frames[-1] if isinstance(frames[-1], dict) else {}
    start_frame = loop.get("sourceStartFrame", first.get("sourceFrameIndex", 0))
    end_frame = loop.get("sourceEndFrame", last.get("sourceFrameIndex", len(frames) - 1))
    start_time = loop.get("sourceStartTimeSec", first.get("sourceTimeSec", 0.0))
    end_time = loop.get("sourceEndTimeSec", last.get("sourceTimeSec"))
    if end_time is None:
        fps_value = movement_payload.get("fps")
        fps = (
            float(fps_value)
            if isinstance(fps_value, (int, float))
            and not isinstance(fps_value, bool)
            and math.isfinite(float(fps_value))
            and float(fps_value) > 0
            else 30.0
        )
        end_time = max(0, len(frames) - 1) / fps
    interval = {
        "type": "full_clip_bake",
        "startFrame": start_frame,
        "endFrame": end_frame,
        "startTimeSec": start_time,
        "endTimeSec": end_time,
        "durationSec": max(0.0, float(end_time) - float(start_time)),
    }
    return {"artifactClass": artifact_class, "selectionId": None, "interval": interval}


def validate_final_output_review_window(
    review_window: Any,
    *,
    artifact_state: dict[str, Any],
    movement_payload: dict[str, Any],
) -> None:
    """Verify persisted review frames and selected interval against the payload."""
    if not isinstance(review_window, dict) or review_window.get("schemaVersion") != 1:
        raise ValueError("Final render evidence is missing its review window")
    frames = movement_payload.get("frames")
    if (
        not isinstance(frames, list)
        or type(review_window.get("frameCount")) is not int
        or review_window.get("frameCount") != len(frames)
    ):
        raise ValueError("Final review window frame count differs from the selected artifact")
    frame_indices = review_window.get("frameIndices")
    if (
        not isinstance(frame_indices, list)
        or not frame_indices
        or any(type(index) is not int or not 0 <= index < len(frames) for index in frame_indices)
    ):
        raise ValueError("Final review window contains invalid frame indices")
    sampling = review_window.get("sampling")
    if not isinstance(sampling, dict):
        raise ValueError("Final review window is missing its sampling policy")
    if sampling.get("policy") == "evenly_spaced_v1":
        requested_count = sampling.get("requestedFrameCount")
        if type(requested_count) is not int or requested_count < 1:
            raise ValueError("Final review window has an invalid requested frame count")
        if sample_review_frame_indices(movement_payload, requested_count) != frame_indices:
            raise ValueError("Final review frame indices differ from their sampling policy")
    elif sampling.get("policy") == "explicit_indices_v1":
        if sampling.get("requestedFrameIndices") != frame_indices:
            raise ValueError("Final review frame indices differ from the explicit request")
    else:
        raise ValueError("Final review window has an unknown sampling policy")
    expected_times = frame_timestamps_for_indices(movement_payload, frame_indices)
    actual_times = review_window.get("frameTimesSec")
    if (
        not isinstance(actual_times, list)
        or len(actual_times) != len(expected_times)
        or any(
            not isinstance(actual, (int, float))
            or isinstance(actual, bool)
            or not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=1e-6)
            for actual, expected in zip(actual_times, expected_times)
        )
    ):
        raise ValueError("Final review timestamps differ from the selected artifact frames")
    expected_selection = artifact_review_selection(artifact_state, movement_payload)
    if review_window.get("selection") != expected_selection:
        raise ValueError("Final review interval differs from the selected artifact lineage")
