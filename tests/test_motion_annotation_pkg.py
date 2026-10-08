from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from motion_annotation_pkg.loader import copy_export_into_workspace, load_export_bundle
from motion_annotation_pkg.pipeline import (
    build_dataset_index,
    finalize_review_session,
    load_review_session,
    prepare_review_session,
    save_review_session,
    validate_review_session,
)


def test_loader_parses_export_bundle(tmp_path: Path) -> None:
    export_dir = _write_export_bundle(tmp_path)

    bundle = load_export_bundle(export_dir)

    assert bundle["metadata"]["session"]["id"] == "session-1"
    assert [event["eventType"] for event in bundle["events"]] == [
        "entered_set",
        "set_completed",
        "entered_set",
        "timer_started",
        "timer_finished",
        "rest_started",
    ]
    assert set(bundle["sensor_chunks"]) == {"chunk_00001.csv", "chunk_00002.csv"}


def test_prepare_review_session_writes_review_json_and_signals(tmp_path: Path) -> None:
    export_dir = _write_export_bundle(tmp_path)
    workspace = tmp_path / "workspace"
    session_dir = copy_export_into_workspace(export_dir, workspace)

    review_path = prepare_review_session(session_dir)
    review_session = json.loads(review_path.read_text(encoding="utf-8"))
    signals = np.load(session_dir / "signals.npz")

    assert review_session["session_id"] == "session-1"
    assert {"rep_based", "timed_no_rep", "rest"} <= {entry["annotation_kind"] for entry in review_session["reviewed_sets"]}
    assert np.all(np.diff(signals["timestamps_nanos"]) > 0)
    assert "proposal_scores" not in signals


def test_finalize_review_session_writes_training_pair_and_dataset_index(tmp_path: Path) -> None:
    export_dir = _write_export_bundle(tmp_path)
    workspace = tmp_path / "workspace"
    session_dir = copy_export_into_workspace(export_dir, workspace)
    prepare_review_session(session_dir)
    review_session = load_review_session(session_dir)
    rep_set = next(entry for entry in review_session["reviewed_sets"] if entry["annotation_kind"] == "rep_based")
    rep_set["exercise_id"] = "exercise-rep"
    save_review_session(session_dir, review_session)

    finalized_dir = finalize_review_session(session_dir)
    session_payload = json.loads((finalized_dir / "session.json").read_text(encoding="utf-8"))
    signals = np.load(finalized_dir / "signals.npz")

    assert session_payload["session_id"] == "session-1"
    assert len(session_payload["reviewed_sets"]) == 3
    assert set(session_payload.keys()) == {"schema_version", "session_id", "reviewed_sets"}
    assert session_payload["reviewed_sets"][0]["class_label"] == "exercise-rep"
    assert session_payload["reviewed_sets"][1]["class_label"] == "timed_no_rep"
    assert "movement_energy" in signals
    assert "proposal_scores" not in signals

    index_path = build_dataset_index(workspace)
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert index_payload["sessions"][0]["session_id"] == "session-1"


def test_validate_review_session_rejects_rep_markers_on_no_rep_sets(tmp_path: Path) -> None:
    export_dir = _write_export_bundle(tmp_path)
    workspace = tmp_path / "workspace"
    session_dir = copy_export_into_workspace(export_dir, workspace)
    prepare_review_session(session_dir)
    review_session = load_review_session(session_dir)
    timed_set = next(entry for entry in review_session["reviewed_sets"] if entry["annotation_kind"] == "timed_no_rep")
    timed_set["rep_count"] = 1
    timed_set["rep_markers"] = [{"rep_index": 1, "start": 1, "peak": 2, "end": 3}]

    with pytest.raises(ValueError, match="cannot include rep markers"):
        validate_review_session(review_session)


def test_validate_review_session_rejects_out_of_range_or_overlapping_rep_markers(tmp_path: Path) -> None:
    export_dir = _write_export_bundle(tmp_path)
    workspace = tmp_path / "workspace"
    session_dir = copy_export_into_workspace(export_dir, workspace)
    prepare_review_session(session_dir)
    review_session = load_review_session(session_dir)
    rep_set = next(entry for entry in review_session["reviewed_sets"] if entry["annotation_kind"] == "rep_based")
    rep_set["rep_markers"] = [
        {"rep_index": 1, "start": rep_set["start_time"], "peak": rep_set["start_time"] + 1, "end": rep_set["start_time"] + 5},
        {"rep_index": 2, "start": rep_set["start_time"] + 4, "peak": rep_set["start_time"] + 6, "end": rep_set["end_time"]},
    ]
    rep_set["rep_count"] = 2

    with pytest.raises(ValueError, match="overlapping rep markers"):
        validate_review_session(review_session)


def _write_export_bundle(tmp_path: Path) -> Path:
    export_dir = tmp_path / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schemaVersion": 2,
        "session": {
            "id": "session-1",
            "workoutId": str(uuid4()),
            "workoutHistoryId": str(uuid4()),
            "status": "COMPLETED",
            "startedAtEpochMs": 1_000,
            "endedAtEpochMs": 9_000,
            "deviceManufacturer": "Google",
            "deviceModel": "Pixel Watch",
            "deviceName": "pixel_watch",
            "appVersion": "1.0.0",
            "sessionDirectoryName": "session-1",
        },
        "sensorConfig": {
            "sampleRateHz": 10,
            "chunkSampleCount": 4,
            "enabledSensors": ["ACCELEROMETER", "GYROSCOPE", "ROTATION_VECTOR"],
        },
        "workoutContext": {
            "workoutId": str(uuid4()),
            "workoutHistoryId": str(uuid4()),
            "orderedExerciseCandidates": [
                {
                    "exerciseId": "exercise-rep",
                    "exerciseName": "Squat",
                    "exerciseType": "WEIGHT",
                    "supersetId": None,
                    "executionOrder": 0,
                    "noRepExpected": False,
                },
                {
                    "exerciseId": "exercise-timed",
                    "exerciseName": "Run",
                    "exerciseType": "COUNTUP",
                    "supersetId": None,
                    "executionOrder": 1,
                    "noRepExpected": True,
                },
            ],
        },
        "coarseReviewedSegments": [
            _segment("segment-1", 0, 1_000_000_000, 3_000_000_000, "exercise-rep", "Squat", "WEIGHT", False, "EXERCISE"),
            _segment("segment-2", 1, 4_000_000_000, 7_000_000_000, "exercise-timed", "Run", "COUNTUP", True, "EXERCISE"),
            _segment("segment-3", 2, 7_500_000_000, 8_500_000_000, "exercise-timed", "Run", "COUNTUP", True, "REST"),
        ],
        "rawSensorFiles": [{"fileName": "chunk_00001.csv"}, {"fileName": "chunk_00002.csv"}],
        "eventsFile": "events.csv",
        "exportedChunkFiles": ["chunk_00001.csv", "chunk_00002.csv"],
    }
    (export_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (export_dir / "events.csv").write_text(
        "eventType,epochTimeMs,elapsedRealtimeNanos,stateName,exerciseId,exerciseName,setId,setIndex,exerciseType,noRepExpected,segmentId,reviewStatus,notes\n"
        "entered_set,1000,1000000000,Set,exercise-rep,Squat,set-1,0,WEIGHT,false,segment-1,,\n"
        "set_completed,3000,3000000000,Set,exercise-rep,Squat,set-1,0,WEIGHT,false,segment-1,,\n"
        "entered_set,4000,4000000000,Set,exercise-timed,Run,set-2,0,COUNTUP,true,segment-2,,\n"
        "timer_started,4000,4000000000,Set,exercise-timed,Run,set-2,0,COUNTUP,true,segment-2,,\n"
        "timer_finished,7000,7000000000,Set,exercise-timed,Run,set-2,0,COUNTUP,true,segment-2,,\n"
        "rest_started,7500,7500000000,Rest,exercise-timed,Run,set-rest,0,COUNTUP,true,segment-3,,\n",
        encoding="utf-8",
    )
    chunk_header = "sensorType,epochTimeMs,elapsedRealtimeNanos,accuracy,x,y,z,w\n"
    (export_dir / "chunk_00001.csv").write_text(
        chunk_header
        + "ACCELEROMETER,1000,1000000000,3,0.0,0.1,1.0,\n"
        + "GYROSCOPE,1000,1000000000,3,0.0,0.0,0.1,\n"
        + "ACCELEROMETER,2000,2000000000,3,0.4,0.5,1.4,\n"
        + "GYROSCOPE,2000,2000000000,3,0.2,0.1,0.1,\n",
        encoding="utf-8",
    )
    (export_dir / "chunk_00002.csv").write_text(
        chunk_header
        + "ACCELEROMETER,3000,3000000000,3,1.0,0.8,1.2,\n"
        + "GYROSCOPE,3000,3000000000,3,0.4,0.2,0.1,\n"
        + "ACCELEROMETER,4000,4000000000,3,0.2,0.2,1.1,\n"
        + "GYROSCOPE,4000,4000000000,3,0.1,0.1,0.1,\n"
        + "ACCELEROMETER,5000,5000000000,3,0.0,0.0,1.0,\n"
        + "GYROSCOPE,5000,5000000000,3,0.0,0.0,0.0,\n"
        + "ROTATION_VECTOR,5000,5000000000,3,0.0,0.0,0.0,1.0\n",
        encoding="utf-8",
    )
    return export_dir


def _segment(
    segment_id: str,
    sequence_index: int,
    start_nanos: int,
    end_nanos: int,
    exercise_id: str,
    exercise_name: str,
    exercise_type: str,
    no_rep_expected: bool,
    label_kind: str,
) -> dict[str, object]:
    label = {
        "kind": label_kind,
        "stateName": "Rest" if label_kind == "REST" else "Set",
        "exerciseId": exercise_id,
        "exerciseName": exercise_name,
        "setId": f"set-{sequence_index}",
        "setIndex": sequence_index,
        "exerciseType": exercise_type,
        "supersetId": None,
        "noRepExpected": no_rep_expected,
        "isWarmupSet": False,
        "isCalibrationSet": False,
        "isAutoRegulationSet": False,
        "isIntraSetRest": label_kind == "REST",
    }
    return {
        "id": segment_id,
        "sessionId": "session-1",
        "sequenceIndex": sequence_index,
        "startedAtEpochMs": start_nanos // 1_000_000,
        "endedAtEpochMs": end_nanos // 1_000_000,
        "startedAtElapsedRealtimeNanos": start_nanos,
        "endedAtElapsedRealtimeNanos": end_nanos,
        "stateName": label["stateName"],
        "autoLabel": label,
        "correctedLabel": None,
        "reviewStatus": "CONFIRMED",
        "chunkFileNames": ["chunk_00001.csv", "chunk_00002.csv"],
    }
