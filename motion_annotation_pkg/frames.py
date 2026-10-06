"""Shared-timeline sensor frames built from a recorded capture session.

Frames are constructed generically for every sensor type present in the chunk
files, so sessions recorded by forward-compatible watch builds (extra sensor
types, gzip-completed chunks) load through the same code path as current
sessions. All arrays of a frame share one uniform elapsed-realtime grid whose
rate comes from the session sensor config.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from motion_annotation_pkg.loader import load_export_bundle

# Preferred source for the shared sample grid: the highest-rate motion sensors
# currently written by the watch app. If none of them is present (forward-compat
# sessions), the type with the most samples is used instead.
_GRID_TYPE_PREFERENCE = ("ACCELEROMETER", "GYROSCOPE", "ROTATION_VECTOR")

_NANOS_PER_SECOND = 1_000_000_000


class SensorFrames:
    """All sensor types resampled onto one uniform grid (elapsed-realtime nanos)."""

    def __init__(
        self,
        timestamps_nanos: np.ndarray,
        timestamps_epoch_ms: np.ndarray,
        sample_rate_hz: float,
        frames: dict[str, dict[str, np.ndarray]],
    ) -> None:
        self.timestamps_nanos = timestamps_nanos
        self.timestamps_epoch_ms = timestamps_epoch_ms
        self.sample_rate_hz = sample_rate_hz
        self.frames = frames

    def frame(self, sensor_type: str) -> dict[str, np.ndarray] | None:
        return self.frames.get(sensor_type)

    def magnitude(self, sensor_type: str) -> np.ndarray | None:
        frame = self.frames.get(sensor_type)
        if frame is None:
            return None
        return magnitude(frame["x"], frame["y"], frame["z"])

    def slice(self, start_nanos: int, end_nanos: int) -> "SensorFrames":
        """Return the sub-frame covering [start_nanos, end_nanos] (inclusive)."""
        mask = (self.timestamps_nanos >= start_nanos) & (self.timestamps_nanos <= end_nanos)
        frames = {name: {axis: values[mask] for axis, values in frame.items()} for name, frame in self.frames.items()}
        return SensorFrames(
            self.timestamps_nanos[mask],
            self.timestamps_epoch_ms[mask],
            self.sample_rate_hz,
            frames,
        )


def build_sensor_frames(bundle: dict[str, Any], sample_rate_hz: int | None = None) -> SensorFrames:
    combined = combine_chunks(bundle["sensor_chunks"])
    if combined["elapsedRealtimeNanos"].size == 0:
        raise ValueError("Session contains no sensor samples")
    rate = float(sample_rate_hz if sample_rate_hz is not None else bundle["metadata"]["sensorConfig"]["sampleRateHz"])
    grid_type = _select_grid_type(combined)
    grid_elapsed = combined["elapsedRealtimeNanos"][combined["sensorType"] == grid_type]
    timeline = build_timeline(grid_elapsed, rate)
    epoch_ms = np.rint(
        interp_to_grid(combined["elapsedRealtimeNanos"], combined["epochTimeMs"].astype(np.float64), timeline)
    ).astype(np.int64)
    frames: dict[str, dict[str, np.ndarray]] = {}
    for sensor_type in np.unique(combined["sensorType"]):
        mask = combined["sensorType"] == sensor_type
        sensor_elapsed = combined["elapsedRealtimeNanos"][mask]
        frames[str(sensor_type)] = {
            axis: interp_to_grid(sensor_elapsed, nan_aware_interp(combined[axis][mask].astype(np.float64)), timeline)
            for axis in ("x", "y", "z", "w")
        }
    return SensorFrames(timeline, epoch_ms, rate, frames)


def resolve_export_dir(session_dir: str | Path) -> Path:
    """Session directories hold the export bundle in raw/ (workspace layout) or directly (export layout)."""
    session_path = Path(session_dir)
    raw_dir = session_path / "raw"
    return raw_dir if (raw_dir / "metadata.json").exists() else session_path


def load_session_frames(session_dir: str | Path) -> SensorFrames:
    """Build frames from a session directory, tolerating both export and workspace layouts."""
    return build_sensor_frames(load_export_bundle(resolve_export_dir(session_dir)))


def combine_chunks(sensor_chunks: dict[str, dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    keys = ("sensorType", "epochTimeMs", "elapsedRealtimeNanos", "accuracy", "x", "y", "z", "w")
    if not sensor_chunks:
        return {key: np.array([]) for key in keys}
    combined = {key: np.concatenate([chunk[key] for chunk in sensor_chunks.values()]) for key in keys}
    order = np.argsort(combined["elapsedRealtimeNanos"], kind="stable")
    return {key: values[order] for key, values in combined.items()}


def build_timeline(elapsed_nanos: np.ndarray, sample_rate_hz: float) -> np.ndarray:
    period = max(int(_NANOS_PER_SECOND / sample_rate_hz), 1)
    return np.arange(int(elapsed_nanos[0]), int(elapsed_nanos[-1]) + period, period, dtype=np.int64)


def interp_to_grid(source_timestamps: np.ndarray, source_values: np.ndarray, target_timestamps: np.ndarray) -> np.ndarray:
    return np.interp(
        target_timestamps.astype(np.float64),
        source_timestamps.astype(np.float64),
        source_values.astype(np.float64),
    )


def nan_aware_interp(values: np.ndarray) -> np.ndarray:
    """Fill NaN samples by interpolation; an all-NaN series collapses to zeros."""
    if values.size == 0:
        return values
    if np.isnan(values).all():
        return np.zeros_like(values, dtype=np.float64)
    if np.isnan(values).any():
        finite = np.flatnonzero(~np.isnan(values))
        values = np.interp(np.arange(values.size), finite, values[finite])
    return values


def magnitude(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    return np.sqrt((x * x) + (y * y) + (z * z)).astype(np.float32)


def _select_grid_type(combined: dict[str, np.ndarray]) -> str:
    types, counts = np.unique(combined["sensorType"], return_counts=True)
    by_name = dict(zip((str(name) for name in types), (int(count) for count in counts)))
    for preferred in _GRID_TYPE_PREFERENCE:
        if preferred in by_name:
            return preferred
    return max(by_name, key=lambda name: by_name[name])
