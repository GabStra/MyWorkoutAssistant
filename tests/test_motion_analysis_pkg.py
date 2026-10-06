"""Focused tests for the offline motion analysis layer (Phase 3).

Synthetic fixtures use known rep counts, tempos, and phase durations:
acceleration is the sampled gradient of a hand-crafted velocity profile, so
ground truth is exact by construction. All randomness-free; tolerances come
from the documented discretization and hysteresis threshold effects.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from motion_annotation_pkg.analysis import analyze_session
from motion_annotation_pkg.frames import build_sensor_frames
from motion_annotation_pkg.loader import load_export_bundle
from motion_annotation_pkg.phase_detector import RepDetection, detect_rep_phases
from motion_annotation_pkg.rep_detector import count_reps, count_reps_robust
from motion_annotation_pkg.signals import bandpass_filter

SAMPLE_RATE_HZ = 50
_SAMPLE_INTERVAL_NANOS = 20_000_000
_BASE_NANOS = 1_000_000_000
_BASE_EPOCH_MS = 1_000_000


# ---------------------------------------------------------------------------
# Synthetic motion helpers
# ---------------------------------------------------------------------------


def _stroke_profiles(
    duration_s: float,
    reps: int,
    period_s: float,
    up_s: float,
    down_s: float,
    v_up: float,
    pause_s: float = 0.4,
    pad_s: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Velocity profile (and its sampled derivative) for a rest-to-rest lift.

    Up and down stroke areas are balanced (v_down = v_up * up_s / down_s) so the
    wrist returns to its start, and the slower eccentric mimics a controlled
    lowering phase. Acceleration is np.gradient of the velocity samples: exact
    on the sample grid, unlike a truncated analytic cosine.
    """
    n = int(duration_s * SAMPLE_RATE_HZ)
    velocity = np.zeros(n)
    for rep in range(reps):
        start = int((pad_s + rep * period_s) * SAMPLE_RATE_HZ)
        up = int(up_s * SAMPLE_RATE_HZ)
        pause = int(pause_s * SAMPLE_RATE_HZ)
        down = int(down_s * SAMPLE_RATE_HZ)
        velocity[start : start + up] = v_up * np.sin(np.pi * np.arange(up) / SAMPLE_RATE_HZ / up_s)
        down_start = start + up + pause
        velocity[down_start : down_start + down] = (
            -v_up * up_s / down_s * np.sin(np.pi * np.arange(down) / SAMPLE_RATE_HZ / down_s)
        )
    acceleration = np.gradient(velocity, 1.0 / SAMPLE_RATE_HZ)
    return acceleration, velocity


def _lateral_profiles(
    duration_s: float,
    reps: int,
    period_s: float,
    up_s: float,
    down_s: float,
    excursion_m: float,
    pause_s: float = 0.4,
    pad_s: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Lateral sway: one full sine swing per stroke (S-curve out on the way up,
    mirrored on the way down) so each rep traces an open loop instead of a
    retraced vertical line. Net lateral displacement per stroke is zero and the
    pauses stay still."""
    n = int(duration_s * SAMPLE_RATE_HZ)
    velocity = np.zeros(n)
    for rep in range(reps):
        start = int((pad_s + rep * period_s) * SAMPLE_RATE_HZ)
        up = int(up_s * SAMPLE_RATE_HZ)
        pause = int(pause_s * SAMPLE_RATE_HZ)
        down = int(down_s * SAMPLE_RATE_HZ)
        velocity[start : start + up] = excursion_m * np.sin(2 * np.pi * np.arange(up) / SAMPLE_RATE_HZ / up_s)
        velocity[start + up + pause : start + up + pause + down] = (
            -excursion_m * np.sin(2 * np.pi * np.arange(down) / SAMPLE_RATE_HZ / down_s)
        )
    return np.gradient(velocity, 1.0 / SAMPLE_RATE_HZ), velocity


def _row_values(
    accel_z: np.ndarray,
    gyro_z: np.ndarray,
    accel_x: np.ndarray | None = None,
) -> tuple[list[float], list[float], list[float]]:
    """Per-sample (accel xyz, gyro xyz, rotation quaternion) with the device held z-up, identity orientation."""
    n = accel_z.size
    x_values = accel_x if accel_x is not None else np.zeros(n)
    accel = [[float(x_values[i]), 0.0, float(9.81 + accel_z[i])] for i in range(n)]
    gyro = [[0.0, 0.0, float(2.0 * gyro_z[i])] for i in range(n)]
    quaternion = [[0.0, 0.0, 0.0, 1.0]] * n
    return accel, gyro, quaternion


# ---------------------------------------------------------------------------
# Loader tolerance (forward-compatible watch builds)
# ---------------------------------------------------------------------------


def test_loader_tolerates_unknown_sensor_rows_and_gzip_chunks(tmp_path: Path) -> None:
    export_dir = _write_tolerance_export_bundle(tmp_path)

    bundle = load_export_bundle(export_dir)

    assert set(bundle["sensor_chunks"]) == {"chunk_00001.csv", "chunk_00002.csv.gz"}
    plain = bundle["sensor_chunks"]["chunk_00001.csv"]
    gzipped = bundle["sensor_chunks"]["chunk_00002.csv.gz"]
    # HEART_RATE rows survive (no crash, no silent truncation of other types).
    assert "HEART_RATE" in set(plain["sensorType"]) | set(gzipped["sensorType"])
    # The malformed short row was skipped; valid rows kept.
    assert plain["epochTimeMs"].size == 4

    frames = build_sensor_frames(bundle)
    assert set(frames.frames) == {"ACCELEROMETER", "GYROSCOPE", "ROTATION_VECTOR", "HEART_RATE"}
    for frame in frames.frames.values():
        assert frame["x"].size == frames.timestamps_nanos.size


# ---------------------------------------------------------------------------
# Rep counting on clean synthetics
# ---------------------------------------------------------------------------


def test_count_reps_exact_on_clean_synthetics() -> None:
    # Signed gyro-like axis of an alternating movement: one positive extremum per rep.
    _, velocity = _stroke_profiles(12.0, reps=5, period_s=2.0, up_s=0.6, down_s=1.0, v_up=1.5)
    signed_gyro = bandpass_filter(2.0 * velocity, SAMPLE_RATE_HZ)
    detection = count_reps(signed_gyro, SAMPLE_RATE_HZ, signal_source="gyro_z")
    assert detection.rep_count == 5
    true_starts = np.arange(5) * 2.0 + 1.0
    assert np.all(np.abs(detection.starts / SAMPLE_RATE_HZ - true_starts) <= 0.6)

    # Continuous bipolar sine (no quiet points): 6 periods of 1.5 s.
    sine = np.sin(2 * np.pi * np.arange(int(9.0 * SAMPLE_RATE_HZ)) / (1.5 * SAMPLE_RATE_HZ))
    filtered = bandpass_filter(sine, SAMPLE_RATE_HZ)
    sine_detection = count_reps(filtered, SAMPLE_RATE_HZ, signal_source="accel_z")
    assert sine_detection.rep_count == 6

    # Slow tempo at the edge of the rep band: 3 reps, 4 s period. The low edge
    # sits below the 0.25 Hz fundamental, as the adaptive session path computes it.
    slow_accel, _ = _stroke_profiles(15.0, reps=3, period_s=4.0, up_s=1.2, down_s=1.2, v_up=1.2)
    slow = bandpass_filter(9.81 + slow_accel, SAMPLE_RATE_HZ, low_hz=0.1)
    slow_detection = count_reps(slow, SAMPLE_RATE_HZ, signal_source="accel_z")
    assert slow_detection.rep_count == 3
    assert slow_detection.tempo_expected_count == pytest.approx(3.0, abs=0.5)


def test_count_reps_robust_prefers_count_consistent_candidate() -> None:
    # gyro magnitude of a symmetric movement repeats every half period (2 bumps
    # per rep) while the signed axis preserves the full cycle; the consensus
    # selection must land on the signed axis's count.
    _, velocity = _stroke_profiles(12.0, reps=5, period_s=2.0, up_s=0.6, down_s=0.6, v_up=1.5)
    candidates = {
        "gyro_magnitude": bandpass_filter(np.abs(velocity), SAMPLE_RATE_HZ),
        "gyro_z": bandpass_filter(2.0 * velocity, SAMPLE_RATE_HZ),
    }
    source, detection = count_reps_robust(candidates, SAMPLE_RATE_HZ)
    assert detection.rep_count == 5
    assert source == "gyro_z"


# ---------------------------------------------------------------------------
# Phase detection
# ---------------------------------------------------------------------------


def test_phase_detector_boundaries_and_sign_normalization() -> None:
    accel, _ = _stroke_profiles(12.0, reps=5, period_s=2.0, up_s=0.6, down_s=0.6, v_up=1.5)
    filtered = bandpass_filter(9.81 + accel, SAMPLE_RATE_HZ, low_hz=0.1)
    true_starts = (np.arange(5) * 2.0 + 1.0) * SAMPLE_RATE_HZ
    reps = RepDetection(
        starts=true_starts.astype(np.int64),
        peaks=(true_starts + 0.3 * SAMPLE_RATE_HZ).astype(np.int64),
        ends=(true_starts + 1.6 * SAMPLE_RATE_HZ).astype(np.int64),
        signal_source="accel_z",
        tempo_period_s=2.0,
        tempo_quality=0.99,
    )

    phases = detect_rep_phases(filtered, SAMPLE_RATE_HZ, reps)

    assert len(phases) == 5
    for rep in phases:
        labels = [span.label for span in rep.spans if span.label != "pause"]
        assert labels == ["concentric", "eccentric"]
        by_label = {span.label: span.duration_s for span in rep.spans}
        # Hysteresis crossings (35% of peak velocity) trim the half-sine phases;
        # 0.6 s strokes measure ~0.45 s, tolerated at +/- 0.25 s.
        assert by_label["concentric"] == pytest.approx(0.6, abs=0.25)
        assert by_label["eccentric"] == pytest.approx(0.6, abs=0.25)

    flipped = detect_rep_phases(-filtered, SAMPLE_RATE_HZ, reps)
    for rep, reference in zip(flipped, phases):
        assert rep.sequence == reference.sequence


# ---------------------------------------------------------------------------
# Session-level analysis (end to end)
# ---------------------------------------------------------------------------


def test_analyze_session_writes_metrics_plots_and_replay_data(tmp_path: Path) -> None:
    export_dir = _write_analysis_export_bundle(tmp_path, with_short_segment=True)
    session_dir = _copy_into_workspace(export_dir, tmp_path / "workspace")
    ground_truth_path = tmp_path / "ground_truth.json"
    ground_truth_path.write_text(json.dumps({"set-0": 4}), encoding="utf-8")

    analysis_dir = analyze_session(session_dir, ground_truth_path)

    assert analysis_dir == session_dir / "analysis"
    metrics = json.loads((analysis_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["schema_version"] == 1
    assert metrics["sample_rate_hz"] == SAMPLE_RATE_HZ
    assert [entry["status"] for entry in metrics["sets"]] == ["analyzed", "skipped"]

    analyzed = metrics["sets"][0]
    assert analyzed["set_id"] == "set-0"
    assert analyzed["rep_count"] == 4
    assert analyzed["ground_truth_rep_count"] == 4
    assert analyzed["rep_count_error"] == 0
    assert 2.2 <= analyzed["mean_tempo_s"] <= 2.6
    assert set(analyzed["mean_phase_duration_s"]) == {"concentric", "eccentric", "pause"}
    assert analyzed["tempo_quality"] > 0.8
    confidence = analyzed["detector_confidence"]
    assert confidence["band"] == "high"
    assert confidence["count_deviation"] is not None and confidence["count_deviation"] < 1.5
    assert 0.7 <= analyzed["rom_proxy"]["mean_rep_path_length_m"] <= 1.8
    # Balanced strokes return the wrist to its start: residual drift must stay small.
    assert analyzed["drift"]["end_to_end_displacement_m"] < 0.15
    assert analyzed["drift"]["static_fraction"] > 0.1

    skipped = metrics["sets"][1]
    assert skipped["set_id"] == "set-short"
    assert "reason" in skipped

    # Coverage boundary: wrist-only counting reliability aggregated per exercise
    # and per exercise type, including the skipped set.
    by_exercise = metrics["coverage"]["by_exercise"]
    assert len(by_exercise) == 1
    exercise_entry = by_exercise[0]
    assert exercise_entry["exercise_id"] == "exercise-analysis"
    assert exercise_entry["set_count"] == 2
    assert exercise_entry["analyzed_set_count"] == 1
    assert exercise_entry["skipped_set_count"] == 1
    assert exercise_entry["ground_truth_set_count"] == 1
    assert exercise_entry["mean_abs_rep_count_error"] == 0.0
    assert exercise_entry["mean_tempo_quality"] > 0.8
    by_type = metrics["coverage"]["by_exercise_type"]
    assert [entry["exercise_type"] for entry in by_type] == ["WEIGHT"]
    assert by_type[0]["ground_truth_set_count"] == 1

    reps = analyzed["reps"]
    assert [rep["rep_index"] for rep in reps] == [1, 2, 3, 4]
    offsets = [rep["start_offset_s"] for rep in reps]
    assert offsets == sorted(offsets)
    for rep in reps:
        labels = [phase["label"] for phase in rep["phases"]]
        assert labels.index("concentric") < labels.index("eccentric")
        assert rep["end_epoch_ms"] > rep["start_epoch_ms"] > 0

    prefix = "set00_set-0"
    for suffix in ("_timeseries.png", "_trajectory.png", "_path.npz", "_path.csv"):
        assert (analysis_dir / f"{prefix}{suffix}").exists(), suffix

    replay = np.load(analysis_dir / f"{prefix}_path.npz")
    position = replay["position"]
    assert position.ndim == 2 and position.shape[1] == 3 and np.isfinite(position).all()
    assert replay["phase_codes"].shape[0] == position.shape[0]
    assert replay["rep_starts"].size == 4

    rows = (analysis_dir / f"{prefix}_path.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "rep_index,phase,t_offset_s,x_m,y_m,z_m"
    assert len(rows) == position.shape[0] + 1
    assert {row.split(",")[1] for row in rows[1:]} <= {"pause", "concentric", "eccentric"}


def test_analyze_session_without_ground_truth_omits_error_fields(tmp_path: Path) -> None:
    export_dir = _write_analysis_export_bundle(tmp_path, with_short_segment=False)
    session_dir = _copy_into_workspace(export_dir, tmp_path / "workspace")

    analysis_dir = analyze_session(session_dir)

    metrics = json.loads((analysis_dir / "metrics.json").read_text(encoding="utf-8"))
    assert len(metrics["sets"]) == 1
    assert "rep_count_error" not in metrics["sets"][0]
    assert "ground_truth_rep_count" not in metrics["sets"][0]


# ---------------------------------------------------------------------------
# Fixture writers
# ---------------------------------------------------------------------------


def _write_analysis_export_bundle(tmp_path: Path, with_short_segment: bool) -> Path:
    """Full capture bundle: 4 reps (2.4 s period, slow eccentric) + REST + optional tiny set."""
    accel, velocity = _stroke_profiles(
        12.5,
        reps=4,
        period_s=2.4,
        up_s=0.6,
        down_s=1.0,
        v_up=1.5,
    )
    lateral_accel, _ = _lateral_profiles(
        12.5,
        reps=4,
        period_s=2.4,
        up_s=0.6,
        down_s=1.0,
        excursion_m=0.15,
    )
    accel_xyz, gyro_xyz, quaternion = _row_values(accel, velocity, lateral_accel)
    n = accel_xyz.__len__()

    def elapsed(index: int) -> int:
        return _BASE_NANOS + index * _SAMPLE_INTERVAL_NANOS

    segments = [
        _segment(
            "segment-1",
            0,
            elapsed(int(0.5 * SAMPLE_RATE_HZ)),
            elapsed(int(11.0 * SAMPLE_RATE_HZ)),
            "exercise-analysis",
            "Biceps Curl",
            "WEIGHT",
            False,
            "EXERCISE",
            set_id="set-0",
        ),
        _segment(
            "segment-2",
            1,
            elapsed(int(11.0 * SAMPLE_RATE_HZ)),
            elapsed(int(12.0 * SAMPLE_RATE_HZ)),
            "exercise-analysis",
            "Biceps Curl",
            "WEIGHT",
            False,
            "REST",
            set_id="set-rest",
        ),
    ]
    if with_short_segment:
        segments.append(
            _segment(
                "segment-3",
                2,
                elapsed(int(12.0 * SAMPLE_RATE_HZ)),
                elapsed(int(12.5 * SAMPLE_RATE_HZ)),
                "exercise-analysis",
                "Biceps Curl",
                "WEIGHT",
                False,
                "EXERCISE",
                set_id="set-short",
            )
        )

    metadata = {
        "schemaVersion": 2,
        "session": {
            "id": "analysis-session-1",
            "workoutId": str(uuid4()),
            "workoutHistoryId": str(uuid4()),
            "status": "COMPLETED",
            "startedAtEpochMs": _BASE_EPOCH_MS,
            "endedAtEpochMs": _BASE_EPOCH_MS + n * 20,
            "deviceManufacturer": "Google",
            "deviceModel": "Pixel Watch",
            "deviceName": "pixel_watch",
            "appVersion": "1.0.0",
            "sessionDirectoryName": "analysis-session-1",
        },
        "sensorConfig": {
            "sampleRateHz": SAMPLE_RATE_HZ,
            "chunkSampleCount": 500,
            "enabledSensors": ["ACCELEROMETER", "GYROSCOPE", "ROTATION_VECTOR"],
        },
        "workoutContext": {
            "workoutId": str(uuid4()),
            "workoutHistoryId": str(uuid4()),
            "orderedExerciseCandidates": [
                {
                    "exerciseId": "exercise-analysis",
                    "exerciseName": "Biceps Curl",
                    "exerciseType": "WEIGHT",
                    "supersetId": None,
                    "executionOrder": 0,
                    "noRepExpected": False,
                }
            ],
        },
        "coarseReviewedSegments": segments,
        "rawSensorFiles": [{"fileName": "chunk_00001.csv"}, {"fileName": "chunk_00002.csv"}],
        "eventsFile": "events.csv",
    }

    export_dir = tmp_path / "export"
    export_dir.mkdir(parents=True)
    (export_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (export_dir / "events.csv").write_text(
        "eventType,epochTimeMs,elapsedRealtimeNanos,stateName,exerciseId,exerciseName,setId,setIndex,exerciseType,noRepExpected,segmentId,reviewStatus,notes\n"
        f"entered_set,{_BASE_EPOCH_MS},{_BASE_NANOS},Set,exercise-analysis,Biceps Curl,set-0,0,WEIGHT,false,segment-1,,\n",
        encoding="utf-8",
    )

    rows: list[str] = []
    for index in range(n):
        stamp = f"{_BASE_EPOCH_MS + index * 20},{elapsed(index)}"
        rows.append(f"ACCELEROMETER,{stamp},3,{accel_xyz[index][0]},{accel_xyz[index][1]},{accel_xyz[index][2]},\n")
        rows.append(f"GYROSCOPE,{stamp},3,{gyro_xyz[index][0]},{gyro_xyz[index][1]},{gyro_xyz[index][2]},\n")
        rows.append(f"ROTATION_VECTOR,{stamp},3,{quaternion[index][0]},{quaternion[index][1]},{quaternion[index][2]},{quaternion[index][3]}\n")
    half = len(rows) // 2
    (export_dir / "chunk_00001.csv").write_text(_CHUNK_HEADER + "".join(rows[:half]), encoding="utf-8")
    (export_dir / "chunk_00002.csv").write_text(_CHUNK_HEADER + "".join(rows[half:]), encoding="utf-8")
    return export_dir


def _write_tolerance_export_bundle(tmp_path: Path) -> Path:
    """Tiny bundle exercising gzipped chunks, unknown sensor rows, and a malformed row."""
    export_dir = tmp_path / "tolerance_export"
    export_dir.mkdir(parents=True)
    metadata = {
        "schemaVersion": 2,
        "session": {
            "id": "tolerance-session-1",
            "workoutId": str(uuid4()),
            "workoutHistoryId": str(uuid4()),
            "status": "COMPLETED",
            "startedAtEpochMs": _BASE_EPOCH_MS,
            "endedAtEpochMs": _BASE_EPOCH_MS + 300,
            "deviceManufacturer": "Google",
            "deviceModel": "Pixel Watch",
            "deviceName": "pixel_watch",
            "appVersion": "1.0.0",
            "sessionDirectoryName": "tolerance-session-1",
        },
        "sensorConfig": {
            "sampleRateHz": SAMPLE_RATE_HZ,
            "chunkSampleCount": 500,
            "enabledSensors": ["ACCELEROMETER", "GYROSCOPE", "ROTATION_VECTOR"],
        },
        "workoutContext": {"workoutId": str(uuid4()), "workoutHistoryId": str(uuid4()), "orderedExerciseCandidates": []},
        "coarseReviewedSegments": [],
        "rawSensorFiles": [{"fileName": "chunk_00001.csv"}, {"fileName": "chunk_00002.csv.gz"}],
        "eventsFile": "events.csv",
    }
    (export_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (export_dir / "events.csv").write_text(
        "eventType,epochTimeMs,elapsedRealtimeNanos,stateName,exerciseId,exerciseName,setId,setIndex,exerciseType,noRepExpected,segmentId,reviewStatus,notes\n",
        encoding="utf-8",
    )
    # 2 valid rows + 1 unknown-sensor row + 1 forward-compatible row (extra
    # appended columns) + 1 malformed short row.
    plain_rows = (
        f"ACCELEROMETER,{_BASE_EPOCH_MS},{_BASE_NANOS},3,0.0,0.0,9.81,\n"
        f"GYROSCOPE,{_BASE_EPOCH_MS},{_BASE_NANOS},3,0.0,0.0,0.1,\n"
        f"HEART_RATE,{_BASE_EPOCH_MS},{_BASE_NANOS},3,72.0,,,\n"
        f"ACCELEROMETER,{_BASE_EPOCH_MS + 20},{_BASE_NANOS + _SAMPLE_INTERVAL_NANOS},3,0.1,0.0,9.85,,72,\n"
        f"GYROSCOPE,{_BASE_EPOCH_MS + 40}\n"
    )
    (export_dir / "chunk_00001.csv").write_text(_CHUNK_HEADER + plain_rows, encoding="utf-8")
    gz_rows = (
        f"ACCELEROMETER,{_BASE_EPOCH_MS + 60},{_BASE_NANOS + 2 * _SAMPLE_INTERVAL_NANOS},3,0.0,0.1,9.82,\n"
        f"ROTATION_VECTOR,{_BASE_EPOCH_MS + 60},{_BASE_NANOS + 2 * _SAMPLE_INTERVAL_NANOS},3,0.0,0.0,0.0,1.0\n"
    )
    with (export_dir / "chunk_00002.csv.gz").open("wb") as handle:
        handle.write(gzip.compress((_CHUNK_HEADER + gz_rows).encode("utf-8")))
    return export_dir


def _copy_into_workspace(export_dir: Path, workspace: Path) -> Path:
    from motion_annotation_pkg.loader import copy_export_into_workspace

    return copy_export_into_workspace(export_dir, workspace)


_CHUNK_HEADER = "sensorType,epochTimeMs,elapsedRealtimeNanos,accuracy,x,y,z,w\n"


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
    set_id: str,
) -> dict[str, object]:
    label = {
        "kind": label_kind,
        "stateName": "Rest" if label_kind == "REST" else "Set",
        "exerciseId": exercise_id,
        "exerciseName": exercise_name,
        "setId": set_id,
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
        "sessionId": "analysis-session-1",
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
