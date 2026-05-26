from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np


def load_export_bundle(export_dir: str | Path) -> dict[str, Any]:
    export_path = Path(export_dir)
    metadata = json.loads((export_path / "metadata.json").read_text(encoding="utf-8"))
    chunk_files = [entry["fileName"] for entry in metadata.get("rawSensorFiles", [])]
    sensor_chunks = {name: _load_chunk(export_path / name) for name in chunk_files}
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
                }
            )
        return rows


def _load_chunk(path: Path) -> dict[str, np.ndarray]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    return {
        "sensorType": np.array([row["sensorType"] for row in rows], dtype=str),
        "epochTimeMs": np.array([int(row["epochTimeMs"]) for row in rows], dtype=np.int64),
        "elapsedRealtimeNanos": np.array([int(row["elapsedRealtimeNanos"]) for row in rows], dtype=np.int64),
        "accuracy": np.array([int(row["accuracy"]) for row in rows], dtype=np.int32),
        "x": np.array([float(row["x"]) for row in rows], dtype=np.float32),
        "y": np.array([float(row["y"]) for row in rows], dtype=np.float32),
        "z": np.array([float(row["z"]) for row in rows], dtype=np.float32),
        "w": np.array([float(row["w"]) if row["w"] else np.nan for row in rows], dtype=np.float32),
    }
