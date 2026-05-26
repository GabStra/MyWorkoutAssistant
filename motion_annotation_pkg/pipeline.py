from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from motion_annotation_pkg.loader import load_export_bundle

NON_EXERCISE_KINDS = {"transition", "rest", "invalid", "ambiguous"}


def prepare_review_session(session_dir: str | Path) -> Path:
    session_path = Path(session_dir)
    bundle = load_export_bundle(session_path / "raw")
    arrays = _build_aligned_arrays(bundle)
    proposals = _build_proposals(bundle, arrays)
    review_session = {
        "schema_version": 1,
        "session_id": bundle["metadata"]["session"]["id"],
        "metadata": bundle["metadata"],
        "events": bundle["events"],
        "segments": proposals,
        "reviewed_sets": deepcopy(proposals),
        "review_status": "in_review",
        "notes": "",
        "updated_at": _utc_now(),
    }
    (session_path / "review_session.json").write_text(json.dumps(review_session, indent=2), encoding="utf-8")
    np.savez_compressed(session_path / "signals.npz", **arrays)
    return session_path / "review_session.json"


def load_review_session(session_dir: str | Path) -> dict[str, Any]:
    return json.loads((Path(session_dir) / "review_session.json").read_text(encoding="utf-8"))


def save_review_session(session_dir: str | Path, review_session: dict[str, Any]) -> Path:
    review_session["updated_at"] = _utc_now()
    target = Path(session_dir) / "review_session.json"
    target.write_text(json.dumps(review_session, indent=2), encoding="utf-8")
    return target


def validate_review_session(review_session: dict[str, Any]) -> None:
    candidate_ids = {
        candidate["exerciseId"]
        for candidate in review_session["metadata"]["workoutContext"]["orderedExerciseCandidates"]
    }
    reviewed_sets = sorted(review_session["reviewed_sets"], key=lambda entry: (entry["start_time"], entry["end_time"], entry["set_id"]))
    for reviewed_set in reviewed_sets:
        _validate_set(reviewed_set, candidate_ids)


def finalize_review_session(session_dir: str | Path, output_dir: str | Path | None = None) -> Path:
    session_path = Path(session_dir)
    review_session = load_review_session(session_path)
    validate_review_session(review_session)
    target_dir = Path(output_dir) if output_dir else session_path / "finalized"
    target_dir.mkdir(parents=True, exist_ok=True)
    reviewed_sets = sorted(
        review_session["reviewed_sets"],
        key=lambda entry: (entry["start_time"], entry["end_time"], entry["set_id"])
    )
    final_payload = {
        "schema_version": 1,
        "session_id": review_session["session_id"],
        "reviewed_sets": [
            {
                "set_id": entry["set_id"],
                "class_label": _class_label(entry),
                "exercise_id": entry.get("exercise_id"),
                "exercise_type": entry.get("exercise_type"),
                "start_time": entry["start_time"],
                "end_time": entry["end_time"],
                "annotation_kind": entry["annotation_kind"],
                "rep_count": entry["rep_count"],
                "rep_markers": entry["rep_markers"],
            }
            for entry in reviewed_sets
        ],
    }
    (target_dir / "session.json").write_text(json.dumps(final_payload, indent=2), encoding="utf-8")
    signals = np.load(session_path / "signals.npz")
    np.savez_compressed(target_dir / "signals.npz", **{key: signals[key] for key in signals.files if key != "proposal_scores"})
    return target_dir


def build_dataset_index(dataset_dir: str | Path, output_path: str | Path | None = None) -> Path:
    dataset_path = Path(dataset_dir)
    session_files = sorted(dataset_path.glob("**/session.json"))
    entries = []
    for session_file in session_files:
        payload = json.loads(session_file.read_text(encoding="utf-8"))
        entries.append(
            {
                "session_id": payload["session_id"],
                "path": str(session_file.parent),
                "split": _split(payload["session_id"]),
                "review_status": "finalized",
                "reviewed_set_count": len(payload["reviewed_sets"]),
            }
        )
    target = Path(output_path) if output_path else dataset_path / "dataset_index.json"
    target.write_text(json.dumps({"sessions": entries}, indent=2), encoding="utf-8")
    return target


def _build_aligned_arrays(bundle: dict[str, Any]) -> dict[str, np.ndarray]:
    combined = _combine_chunks(bundle["sensor_chunks"])
    sample_rate_hz = int(bundle["metadata"]["sensorConfig"]["sampleRateHz"])
    timeline = _build_timeline(combined["elapsedRealtimeNanos"], sample_rate_hz)
    arrays = {
        "timestamps_nanos": timeline,
        "timestamps_epoch_ms": _interp(combined["elapsedRealtimeNanos"], combined["epochTimeMs"], timeline).astype(np.int64),
    }
    for sensor_type, prefix in {"ACCELEROMETER": "accel", "GYROSCOPE": "gyro", "ROTATION_VECTOR": "rotation"}.items():
        mask = combined["sensorType"] == sensor_type
        sensor_elapsed = combined["elapsedRealtimeNanos"][mask]
        for axis in ("x", "y", "z", "w"):
            key = f"{prefix}_{axis}"
            if sensor_elapsed.size == 0:
                arrays[key] = np.zeros_like(timeline, dtype=np.float32)
                continue
            values = combined[axis][mask].astype(np.float64)
            if np.isnan(values).all():
                arrays[key] = np.zeros_like(timeline, dtype=np.float32)
                continue
            if np.isnan(values).any():
                finite = np.flatnonzero(~np.isnan(values))
                values = np.interp(np.arange(values.size), finite, values[finite])
            arrays[key] = _interp(sensor_elapsed, values, timeline).astype(np.float32)
    arrays["accel_magnitude"] = _magnitude(arrays["accel_x"], arrays["accel_y"], arrays["accel_z"])
    arrays["gyro_magnitude"] = _magnitude(arrays["gyro_x"], arrays["gyro_y"], arrays["gyro_z"])
    arrays["movement_energy"] = _smooth(np.abs(np.gradient(arrays["accel_magnitude"])) + np.abs(np.gradient(arrays["gyro_magnitude"])))
    return arrays


def _build_proposals(bundle: dict[str, Any], arrays: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    segments = bundle["metadata"].get("coarseReviewedSegments", [])
    timestamps = arrays["timestamps_nanos"]
    energy = arrays["movement_energy"]
    proposals = []
    for segment in segments:
        label = segment.get("correctedLabel") or segment["autoLabel"]
        start = int(segment["startedAtElapsedRealtimeNanos"])
        end = int(segment.get("endedAtElapsedRealtimeNanos") or start)
        mask = (timestamps >= start) & (timestamps <= end)
        local_times = timestamps[mask]
        local_energy = energy[mask] if mask.any() else np.array([], dtype=np.float32)
        annotation_kind = _annotation_kind(label)
        rep_markers = _rep_markers(local_times, local_energy) if annotation_kind == "rep_based" else []
        if annotation_kind == "rep_based" and local_times.size:
            start = int(local_times[0])
            end = int(local_times[-1])
        proposals.append(
            {
                "set_id": segment["id"],
                "exercise_id": label.get("exerciseId"),
                "exercise_name": label.get("exerciseName"),
                "exercise_type": label.get("exerciseType"),
                "set_index": label.get("setIndex"),
                "start_time": start,
                "end_time": end,
                "annotation_kind": annotation_kind,
                "rep_count": len(rep_markers),
                "rep_markers": rep_markers,
            }
        )
    return proposals


def _combine_chunks(sensor_chunks: dict[str, dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    keys = ("sensorType", "epochTimeMs", "elapsedRealtimeNanos", "accuracy", "x", "y", "z", "w")
    combined = {key: np.concatenate([chunk[key] for chunk in sensor_chunks.values()]) for key in keys}
    order = np.argsort(combined["elapsedRealtimeNanos"], kind="stable")
    return {key: values[order] for key, values in combined.items()}


def _build_timeline(elapsed_nanos: np.ndarray, sample_rate_hz: int) -> np.ndarray:
    period = max(int(1_000_000_000 / sample_rate_hz), 1)
    return np.arange(int(elapsed_nanos[0]), int(elapsed_nanos[-1]) + period, period, dtype=np.int64)


def _interp(source_timestamps: np.ndarray, source_values: np.ndarray, target_timestamps: np.ndarray) -> np.ndarray:
    return np.interp(target_timestamps.astype(np.float64), source_timestamps.astype(np.float64), source_values.astype(np.float64))


def _magnitude(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    return np.sqrt((x * x) + (y * y) + (z * z)).astype(np.float32)


def _smooth(values: np.ndarray, window: int = 3) -> np.ndarray:
    if values.size <= 1:
        return values.astype(np.float32)
    kernel = np.ones(window, dtype=np.float64) / window
    return np.convolve(values, kernel, mode="same").astype(np.float32)


def _annotation_kind(label: dict[str, Any]) -> str:
    if label["kind"] == "REST":
        return "rest"
    if label["kind"] == "TRANSITION":
        return "transition"
    if label["kind"] == "EXERCISE" and label.get("noRepExpected"):
        return "timed_no_rep"
    if label["kind"] == "EXERCISE":
        return "rep_based"
    return "ambiguous"


def _rep_markers(times: np.ndarray, energy: np.ndarray) -> list[dict[str, int]]:
    if times.size < 3:
        return []
    threshold = float(energy.mean() + (0.25 * energy.std()))
    peaks = []
    for index in range(1, energy.size - 1):
        if energy[index] >= threshold and energy[index] >= energy[index - 1] and energy[index] > energy[index + 1]:
            peaks.append(index)
    return [
        {
            "rep_index": rep_index + 1,
            "start": int(times[max(peak - 1, 0)]),
            "peak": int(times[peak]),
            "end": int(times[min(peak + 1, times.size - 1)]),
        }
        for rep_index, peak in enumerate(peaks)
    ]


def _validate_set(reviewed_set: dict[str, Any], candidate_ids: set[str]) -> None:
    if reviewed_set["start_time"] >= reviewed_set["end_time"]:
        raise ValueError(f"Set {reviewed_set['set_id']} start_time must be before end_time")
    annotation_kind = reviewed_set["annotation_kind"]
    exercise_id = reviewed_set.get("exercise_id")
    if annotation_kind not in NON_EXERCISE_KINDS and exercise_id not in candidate_ids:
        raise ValueError(f"Exercise label {exercise_id!r} is outside the active WOD candidates")
    if annotation_kind != "rep_based":
        if reviewed_set.get("rep_markers"):
            raise ValueError(f"Set {reviewed_set['set_id']} cannot include rep markers for {annotation_kind}")
        if reviewed_set.get("rep_count", 0) not in (0, None):
            raise ValueError(f"Set {reviewed_set['set_id']} cannot include rep_count for {annotation_kind}")
        return
    rep_markers = reviewed_set.get("rep_markers", [])
    if reviewed_set.get("rep_count") != len(rep_markers):
        raise ValueError(f"Set {reviewed_set['set_id']} rep_count does not match rep_markers length")
    previous_end = reviewed_set["start_time"]
    for marker in rep_markers:
        marker_start = marker["start"]
        marker_peak = marker["peak"]
        marker_end = marker["end"]
        if not (reviewed_set["start_time"] <= marker_start <= marker_peak <= marker_end <= reviewed_set["end_time"]):
            raise ValueError(f"Set {reviewed_set['set_id']} has an out-of-range rep marker")
        if marker_start < previous_end:
            raise ValueError(f"Set {reviewed_set['set_id']} has overlapping rep markers")
        previous_end = marker_end


def _class_label(reviewed_set: dict[str, Any]) -> str:
    if reviewed_set["annotation_kind"] == "rep_based":
        return reviewed_set["exercise_id"]
    return reviewed_set["annotation_kind"]


def _split(session_id: str) -> str:
    bucket = int(hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 70:
        return "train"
    if bucket < 85:
        return "validation"
    return "test"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
