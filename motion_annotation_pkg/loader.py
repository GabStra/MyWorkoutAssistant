from __future__ import annotations

import csv
import gzip
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np


def load_export_bundle(export_dir: str | Path) -> dict[str, Any]:
    export_path = Path(export_dir)
    metadata = json.loads((export_path / "metadata.json").read_text(encoding="utf-8"))
    sensor_chunks: dict[str, dict[str, np.ndarray]] = {}
    for entry in metadata.get("rawSensorFiles", []):
        chunk_path = _resolve_chunk_file(export_path, entry["fileName"])
        if chunk_path is None:
            continue
        sensor_chunks[chunk_path.name] = _load_chunk(chunk_path)
    events = _load_events(export_path / metadata.get("eventsFile", "events.csv"))
    return {
        "export_dir": export_path,
        "metadata": metadata,
        "events": events,
        "sensor_chunks": sensor_chunks,
    }


def copy_export_into_workspace(export_dir: str | Path, workspace_dir: str | Path) -> Path:
    bundle = load_export_bundle(export_dir)
    session_id = bundle["metadata"]["session"]["id"]
    session_dir = Path(workspace_dir) / "sessions" / session_id
    raw_dir = session_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for file_path in Path(export_dir).iterdir():
        if file_path.is_file():
            shutil.copy2(file_path, raw_dir / file_path.name)
    return session_dir


def _resolve_chunk_file(export_path: Path, file_name: str) -> Path | None:
    """Resolve a chunk reference to an existing file, tolerating plain and gzip-completed sessions."""
    candidates = [export_path / file_name]
    if not file_name.endswith(".gz"):
        candidates.append(export_path / f"{file_name}.gz")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            rows.append(
                {
                    "eventType": row["eventType"],
                    "epochTimeMs": int(row["epochTimeMs"]),
                    "elapsedRealtimeNanos": int(row["elapsedRealtimeNanos"]),
                    "stateName": row.get("stateName") or None,
                    "exerciseId": row.get("exerciseId") or None,
                    "exerciseName": row.get("exerciseName") or None,
                    "setId": row.get("setId") or None,
                    "setIndex": int(row["setIndex"]) if row.get("setIndex") else None,
                    "exerciseType": row.get("exerciseType") or None,
                    "noRepExpected": (row.get("noRepExpected") or "false").lower() == "true",
                    "segmentId": row.get("segmentId") or None,
                    "reviewStatus": row.get("reviewStatus") or None,
                    "notes": row.get("notes") or None,
                    "actualReps": _optional_int(row.get("actualReps")),
                }
            )
        return rows


def _load_chunk(path: Path) -> dict[str, np.ndarray]:
    """Load a raw sensor chunk without assuming a fixed set of sensor types.

    v2 chunks are binary columnar files (see MotionCaptureChunkFormat on the Kotlin side);
    legacy v1 chunks are CSV. Rows from forward-compatible sensor types (heart rate,
    pressure, ...) are parsed generically; rows missing required numeric fields are
    skipped instead of raising.
    """
    if path.name.endswith(".bin") or path.name.endswith(".bin.gz"):
        opener = gzip.open if path.name.endswith(".gz") else open
        with opener(path, "rb") as handle:  # type: ignore[call-overload]
            return _decode_binary_chunk(handle.read())
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:  # type: ignore[call-overload]
        reader = csv.DictReader(handle)
        parsed = [row for row in (_parse_sample_row(raw) for raw in reader) if row is not None]
    return {
        "sensorType": np.array([row[0] for row in parsed], dtype=str),
        "epochTimeMs": np.array([row[1] for row in parsed], dtype=np.int64),
        "elapsedRealtimeNanos": np.array([row[2] for row in parsed], dtype=np.int64),
        "accuracy": np.array([row[3] for row in parsed], dtype=np.int32),
        "x": np.array([row[4] for row in parsed], dtype=np.float32),
        "y": np.array([row[5] for row in parsed], dtype=np.float32),
        "z": np.array([row[6] for row in parsed], dtype=np.float32),
        "w": np.array([row[7] for row in parsed], dtype=np.float32),
    }


def _parse_sample_row(row: dict[str, str | None]) -> tuple[str, int, int, int, float, float, float, float] | None:
    sensor_type = (row.get("sensorType") or "").strip()
    if not sensor_type:
        return None
    try:
        epoch_time_ms = int(row["epochTimeMs"])
        elapsed_realtime_nanos = int(row["elapsedRealtimeNanos"])
        accuracy = int(row["accuracy"])
    except (KeyError, TypeError, ValueError):
        return None
    # Empty numeric fields are legitimate for sensor types that do not fill all
    # axes (e.g. heart rate): they parse as NaN. Unparsable values skip the row.
    x = _optional_float(row.get("x"))
    y = _optional_float(row.get("y"))
    z = _optional_float(row.get("z"))
    w = _optional_float(row.get("w"))
    if x is None or y is None or z is None or w is None:
        return None
    return (sensor_type, epoch_time_ms, elapsed_realtime_nanos, accuracy, x, y, z, w)


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return np.nan
    try:
        return float(value)
    except ValueError:
        return None


def _optional_int(value: str | None) -> int | None:
    """Missing column and empty string both mean "not recorded"; unparsable values degrade to None."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


# Mirrors MotionSensorType's Kotlin declaration order, which the v2 chunk format pins by ordinal.
_MOTION_SENSOR_TYPE_NAMES = [
    "ACCELEROMETER",
    "GYROSCOPE",
    "ROTATION_VECTOR",
    "HEART_RATE",
    "STEP_COUNTER",
    "GRAVITY",
    "LINEAR_ACCELERATION",
    "PRESSURE",
]

_BINARY_CHUNK_MAGIC = b"MCF2"


def _decode_binary_chunk(data: bytes) -> dict[str, np.ndarray]:
    """Decode a v2 columnar chunk (MotionCaptureChunkFormat): header, delta-timestamp columns and
    byte-plane-shuffled float32 value columns. Lossless — values are bit-identical to the watch's."""
    if data[:4] != _BINARY_CHUNK_MAGIC:
        raise ValueError("Not a motion chunk v2 file")
    if data[4] != 2:
        raise ValueError(f"Unsupported motion chunk version {data[4]}")
    count = int.from_bytes(data[5:7], "little")
    base_epoch = int.from_bytes(data[7:15], "little", signed=True)
    base_elapsed = int.from_bytes(data[15:23], "little", signed=True)
    offset = 23
    type_ordinals = np.frombuffer(data[offset:offset + count], dtype=np.uint8)
    offset += count
    accuracy = np.frombuffer(data[offset:offset + count], dtype=np.int8).astype(np.int32)
    offset += count
    epoch_deltas, offset = _decode_varints(data, offset, count)
    elapsed_deltas, offset = _decode_varints(data, offset, count)
    epoch = base_epoch + np.cumsum(epoch_deltas, dtype=np.int64)
    elapsed = base_elapsed + np.cumsum(elapsed_deltas, dtype=np.int64)

    def _value_column() -> np.ndarray:
        nonlocal offset
        planes = np.frombuffer(data[offset:offset + 4 * count], dtype=np.uint8).reshape(4, count)
        offset += 4 * count
        return np.ascontiguousarray(planes.T).view("<f4").reshape(-1)

    return {
        "sensorType": np.array([
            _MOTION_SENSOR_TYPE_NAMES[o] if o < len(_MOTION_SENSOR_TYPE_NAMES) else f"UNKNOWN_{o}"
            for o in type_ordinals
        ], dtype=str),
        "epochTimeMs": epoch,
        "elapsedRealtimeNanos": elapsed,
        "accuracy": accuracy,
        "x": _value_column(),
        "y": _value_column(),
        "z": _value_column(),
        "w": _value_column(),
    }


def _decode_varints(data: bytes, offset: int, count: int) -> tuple[np.ndarray, int]:
    """Decode `count` zigzag LEB128 varints starting at `offset`; returns (values, next_offset)."""
    values = np.empty(count, dtype=np.int64)
    for index in range(count):
        result = 0
        shift = 0
        while True:
            byte = data[offset]
            offset += 1
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        values[index] = (result >> 1) ^ -(result & 1)
    return values, offset
