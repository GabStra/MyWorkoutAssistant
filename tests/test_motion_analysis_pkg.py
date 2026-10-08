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

from motion_annotation_pkg.analysis import METRICS_FILE_NAME, analyze_session
from motion_annotation_pkg.frames import build_sensor_frames
from motion_annotation_pkg.loader import load_export_bundle
from motion_annotation_pkg.phase_detector import RepDetection, detect_rep_phases
from motion_annotation_pkg.rep_detector import count_reps, count_reps_robust
from motion_annotation_pkg.signals import bandpass_filter

SAMPLE_RATE_HZ = 50
_SAMPLE_INTERVAL_NANOS = 20_000_000
_BASE_NANOS = 1_000_000_000
_BASE_EPOCH_MS = 1_000_000


def _elapsed(index: int) -> int:
    """Elapsed-realtime nanos of the index-th sample on the uniform 50 Hz grid."""
    return _BASE_NANOS + index * _SAMPLE_INTERVAL_NANOS


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


def _drifting_stroke_profiles(
    periods_s: list[float],
    displacement_m: float = 0.9,
    pad_s: float = 1.0,
    tail_s: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Accel/velocity for strokes whose period shrinks every rep (accelerating tempo).

    Each stroke scales with its period (up 0.3, pause 0.1, down 0.5 of it) and
    the per-rep displacement is held constant, so the rep count is the only
    moving ground truth: len(periods_s) reps spanning the given periods.
    """
    velocity_blocks = []
    for period_s in periods_s:
        up_s = 0.3 * period_s
        pause_s = 0.1 * period_s
        down_s = 0.5 * period_s
        v_up = displacement_m * np.pi / (2.0 * up_s)
        up = int(up_s * SAMPLE_RATE_HZ)
        pause = int(pause_s * SAMPLE_RATE_HZ)
        down = int(down_s * SAMPLE_RATE_HZ)
        block = np.zeros(up + pause + down)
        block[:up] = v_up * np.sin(np.pi * np.arange(up) / SAMPLE_RATE_HZ / up_s)
        block[up + pause :] = -v_up * up_s / down_s * np.sin(np.pi * np.arange(down) / SAMPLE_RATE_HZ / down_s)
        velocity_blocks.append(block)
    velocity = np.concatenate(velocity_blocks)
    velocity = np.concatenate([np.zeros(int(pad_s * SAMPLE_RATE_HZ)), velocity, np.zeros(int(tail_s * SAMPLE_RATE_HZ))])
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
    # The file value deliberately differs from the event-embedded actualReps (4):
    # the metrics must carry the event count, proving event ground truth wins.
    ground_truth_path = tmp_path / "ground_truth.json"
    ground_truth_path.write_text(json.dumps({"set-0": 5}), encoding="utf-8")

    analysis_dir = analyze_session(session_dir, ground_truth_path)

    assert analysis_dir == session_dir / "analysis"
    metrics = json.loads((analysis_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["schema_version"] == 1
    assert metrics["sample_rate_hz"] == SAMPLE_RATE_HZ
    assert [entry["status"] for entry in metrics["sets"]] == ["analyzed", "skipped"]

    analyzed = metrics["sets"][0]
    assert analyzed["set_id"] == "set-0"
    assert analyzed["rep_count"] == 4
    assert analyzed["ground_truth_source"] == "event"
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
    export_dir = _write_analysis_export_bundle(tmp_path, with_short_segment=False, with_event_ground_truth=False)
    session_dir = _copy_into_workspace(export_dir, tmp_path / "workspace")

    analysis_dir = analyze_session(session_dir)

    metrics = json.loads((analysis_dir / "metrics.json").read_text(encoding="utf-8"))
    assert len(metrics["sets"]) == 1
    assert "rep_count_error" not in metrics["sets"][0]
    assert "ground_truth_rep_count" not in metrics["sets"][0]
    assert metrics["sets"][0]["ground_truth_source"] is None


def test_analyze_session_uses_ground_truth_file_when_events_lack_actual_reps(tmp_path: Path) -> None:
    export_dir = _write_analysis_export_bundle(tmp_path, with_short_segment=False, with_event_ground_truth=False)
    session_dir = _copy_into_workspace(export_dir, tmp_path / "workspace")
    ground_truth_path = tmp_path / "ground_truth.json"
    ground_truth_path.write_text(json.dumps({"set-0": 4}), encoding="utf-8")

    analyze_session(session_dir, ground_truth_path)

    metrics = json.loads((session_dir / "analysis" / "metrics.json").read_text(encoding="utf-8"))
    analyzed = metrics["sets"][0]
    assert analyzed["ground_truth_source"] == "file"
    assert analyzed["ground_truth_rep_count"] == 4
    assert analyzed["rep_count_error"] == 0


def test_analyze_session_event_ground_truth_falls_back_to_set_id_join(tmp_path: Path) -> None:
    # A SET_COMPLETED whose segmentId matches no segment: the latest set-matching
    # completion at or before the segment end still supplies the ground truth.
    export_dir = _write_analysis_export_bundle(tmp_path, with_short_segment=False, event_segment_id="segment-unknown")
    session_dir = _copy_into_workspace(export_dir, tmp_path / "workspace")

    analyze_session(session_dir)

    metrics = json.loads((session_dir / "analysis" / "metrics.json").read_text(encoding="utf-8"))
    analyzed = metrics["sets"][0]
    assert analyzed["ground_truth_source"] == "event"
    assert analyzed["ground_truth_rep_count"] == 4
    assert analyzed["rep_count_error"] == 0


def test_loader_parses_actual_reps_across_old_and_new_event_headers(tmp_path: Path) -> None:
    new_header_bundle = _write_actual_reps_events_bundle(tmp_path / "new_header", _EVENT_HEADER_NEW)
    old_header_bundle = _write_actual_reps_events_bundle(tmp_path / "old_header", _EVENT_HEADER_OLD)

    new_events = load_export_bundle(new_header_bundle)["events"]
    old_events = load_export_bundle(old_header_bundle)["events"]

    # New 14-column header: an integer value parses; an empty string means "not recorded".
    assert [event["actualReps"] for event in new_events] == [8, None, None]
    # Old 13-column header (pre-actualReps watch builds): the column is absent,
    # every row degrades to None.
    assert [event["actualReps"] for event in old_events] == [None, None]


# ---------------------------------------------------------------------------
# Detector hardening (coverage boundary): honest degradation, never miscounting
# ---------------------------------------------------------------------------


def _analyze_hardening_set(tmp_path: Path, name: str, accel_z: np.ndarray, gyro_z: np.ndarray) -> dict:
    export_dir = _write_hardening_export_bundle(tmp_path, name, accel_z, gyro_z)
    analysis_dir = analyze_session(export_dir)
    metrics = json.loads((analysis_dir / METRICS_FILE_NAME).read_text(encoding="utf-8"))
    assert len(metrics["sets"]) == 1
    assert metrics["sets"][0]["status"] == "analyzed"
    return metrics["sets"][0]


def test_hardening_aperiodic_near_static_segment_stays_low_confidence(tmp_path: Path) -> None:
    # Wrist barely moves: a 0.05 Hz drift far below the 0.3 Hz analysis band and
    # no rep periodicity. Whatever the detector reports, it must be flagged
    # low-confidence instead of asserting a confident (wrong) count.
    n = int(30.0 * SAMPLE_RATE_HZ)
    t = np.arange(n) / SAMPLE_RATE_HZ
    accel = 0.02 * np.sin(2 * np.pi * 0.05 * t)
    report = _analyze_hardening_set(tmp_path, "static-drift", accel, np.zeros(n))

    assert report["rep_count"] == 0 or report["detector_confidence"]["band"] == "low"
    assert report["detector_confidence"]["band"] == "low"


def test_hardening_drifting_tempo_counts_exactly(tmp_path: Path) -> None:
    # 8 reps accelerating from a 3.0 s to a 1.5 s period (mean 2.25 s): the count
    # must stay exact and the measured tempo within tolerance, with the majority
    # of reps still carrying a concentric->eccentric sequence.
    periods = [3.0 - index * (1.5 / 7.0) for index in range(8)]
    accel, velocity = _drifting_stroke_profiles(periods)
    report = _analyze_hardening_set(tmp_path, "drifting-tempo", accel, velocity)

    assert report["rep_count"] == 8
    assert report["mean_tempo_s"] == pytest.approx(2.25, abs=0.35)
    starts = [rep["start_offset_s"] for rep in report["reps"]]
    assert starts == sorted(starts)
    ordered_phase_reps = 0
    for rep in report["reps"]:
        labels = [phase["label"] for phase in rep["phases"]]
        if "concentric" in labels and "eccentric" in labels:
            assert labels.index("concentric") < labels.index("eccentric")
            ordered_phase_reps += 1
    assert ordered_phase_reps >= 6


def test_hardening_symmetric_strokes_resolve_to_true_count(tmp_path: Path) -> None:
    # Symmetric strokes: |gyro|/|accel| rectify into two identical lobes per rep,
    # so a magnitude candidate counts 2x. The robust candidate selection must
    # resolve the true count via a signed full-cycle axis.
    accel, velocity = _stroke_profiles(20.0, reps=8, period_s=2.0, up_s=0.6, down_s=0.6, v_up=1.5)
    report = _analyze_hardening_set(tmp_path, "symmetric-strokes", accel, velocity)

    assert report["rep_count"] == 8
    assert "_magnitude" not in report["signal_source"]


def test_hardening_noise_floor_never_confident_nonzero_count(tmp_path: Path) -> None:
    # White noise with no reps: a nonzero count may only appear flagged
    # low-confidence, never as a confident number.
    rng = np.random.default_rng(20261006)
    n = int(30.0 * SAMPLE_RATE_HZ)
    accel = rng.normal(0.0, 0.15, n)
    gyro = rng.normal(0.0, 0.05, n)
    report = _analyze_hardening_set(tmp_path, "noise-floor", accel, gyro)

    confidence = report["detector_confidence"]
    assert not (report["rep_count"] > 0 and confidence["band"] != "low")
    assert confidence["band"] == "low"


# ---------------------------------------------------------------------------
# Fixture writers
# ---------------------------------------------------------------------------


def _write_analysis_export_bundle(
    tmp_path: Path,
    with_short_segment: bool,
    with_event_ground_truth: bool = True,
    event_segment_id: str = "segment-1",
) -> Path:
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

    segments = [
        _segment(
            "segment-1",
            0,
            _elapsed(int(0.5 * SAMPLE_RATE_HZ)),
            _elapsed(int(11.0 * SAMPLE_RATE_HZ)),
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
            _elapsed(int(11.0 * SAMPLE_RATE_HZ)),
            _elapsed(int(12.0 * SAMPLE_RATE_HZ)),
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
                _elapsed(int(12.0 * SAMPLE_RATE_HZ)),
                _elapsed(int(12.5 * SAMPLE_RATE_HZ)),
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
    events_rows = [
        f"entered_set,{_BASE_EPOCH_MS},{_BASE_NANOS},Set,exercise-analysis,Biceps Curl,set-0,0,WEIGHT,false,segment-1,,\n"
    ]
    if with_event_ground_truth:
        # SET_COMPLETED carrying the new trailing actualReps column (14 fields);
        # timestamped at the segment end so the set-id fallback also applies.
        events_rows.append(
            f"set_completed,{_BASE_EPOCH_MS + 11_000},{_elapsed(int(11.0 * SAMPLE_RATE_HZ))},"
            f"Set,exercise-analysis,Biceps Curl,set-0,0,WEIGHT,false,{event_segment_id},,,4\n"
        )
    if with_short_segment:
        # Old-format row: pre-actualReps watch builds end the line after notes
        # (13 fields under the 14-column header), parsing as actualReps=None.
        events_rows.append(
            f"set_completed,{_BASE_EPOCH_MS + 12_000},{_elapsed(int(12.0 * SAMPLE_RATE_HZ))},"
            f"Set,exercise-analysis,Biceps Curl,set-short,2,WEIGHT,false,segment-3,,\n"
        )
    (export_dir / "events.csv").write_text(_EVENT_HEADER_NEW + "".join(events_rows), encoding="utf-8")

    rows: list[str] = []
    for index in range(n):
        stamp = f"{_BASE_EPOCH_MS + index * 20},{_elapsed(index)}"
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


def _write_actual_reps_events_bundle(root: Path, header: str) -> Path:
    """Minimal bundle whose events.csv exercises one header variant end to end."""
    root.mkdir(parents=True)
    metadata = {
        "schemaVersion": 2,
        "session": {"id": "events-header-session", "status": "COMPLETED"},
        "rawSensorFiles": [],
        "eventsFile": "events.csv",
    }
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    if header == _EVENT_HEADER_NEW:
        rows = (
            "set_completed,1000,1000000000,Set,exercise-rep,Squat,set-1,0,WEIGHT,false,segment-1,,,8\n"
            "set_completed,2000,2000000000,Set,exercise-rep,Squat,set-2,1,WEIGHT,false,segment-2,,\n"
            "entered_set,3000,3000000000,Set,exercise-rep,Squat,set-3,2,WEIGHT,false,segment-3,,\n"
        )
    else:
        rows = (
            "set_completed,1000,1000000000,Set,exercise-rep,Squat,set-1,0,WEIGHT,false,segment-1,,\n"
            "entered_set,3000,3000000000,Set,exercise-rep,Squat,set-3,2,WEIGHT,false,segment-3,,\n"
        )
    (root / "events.csv").write_text(header + rows, encoding="utf-8")
    return root


def _write_hardening_export_bundle(
    tmp_path: Path,
    session_id: str,
    accel_z: np.ndarray,
    gyro_z: np.ndarray,
) -> Path:
    """Single-EXERCISE-segment bundle (50 Hz accel + gyro + rotation vector) for detector hardening."""
    accel_xyz, gyro_xyz, quaternion = _row_values(accel_z, gyro_z)
    n = len(accel_xyz)
    segment = _segment(
        f"segment-{session_id}",
        0,
        _elapsed(0),
        _elapsed(n - 1),
        "exercise-hardening",
        "Hardening Probe",
        "WEIGHT",
        False,
        "EXERCISE",
        f"set-{session_id}",
        session_id=session_id,
    )
    metadata = {
        "schemaVersion": 2,
        "session": {
            "id": session_id,
            "workoutId": str(uuid4()),
            "workoutHistoryId": str(uuid4()),
            "status": "COMPLETED",
            "startedAtEpochMs": _BASE_EPOCH_MS,
            "endedAtEpochMs": _BASE_EPOCH_MS + n * 20,
            "deviceManufacturer": "Google",
            "deviceModel": "Pixel Watch",
            "deviceName": "pixel_watch",
            "appVersion": "1.0.0",
            "sessionDirectoryName": session_id,
        },
        "sensorConfig": {
            "sampleRateHz": SAMPLE_RATE_HZ,
            "chunkSampleCount": 500,
            "enabledSensors": ["ACCELEROMETER", "GYROSCOPE", "ROTATION_VECTOR"],
        },
        "workoutContext": {"workoutId": str(uuid4()), "workoutHistoryId": str(uuid4()), "orderedExerciseCandidates": []},
        "coarseReviewedSegments": [segment],
        "rawSensorFiles": [{"fileName": "chunk_00001.csv"}],
        "eventsFile": "events.csv",
    }
    export_dir = tmp_path / session_id
    export_dir.mkdir(parents=True)
    (export_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (export_dir / "events.csv").write_text(_EVENT_HEADER_NEW, encoding="utf-8")
    rows: list[str] = []
    for index in range(n):
        stamp = f"{_BASE_EPOCH_MS + index * 20},{_elapsed(index)}"
        rows.append(f"ACCELEROMETER,{stamp},3,{accel_xyz[index][0]},{accel_xyz[index][1]},{accel_xyz[index][2]},\n")
        rows.append(f"GYROSCOPE,{stamp},3,{gyro_xyz[index][0]},{gyro_xyz[index][1]},{gyro_xyz[index][2]},\n")
        rows.append(f"ROTATION_VECTOR,{stamp},3,{quaternion[index][0]},{quaternion[index][1]},{quaternion[index][2]},{quaternion[index][3]}\n")
    (export_dir / "chunk_00001.csv").write_text(_CHUNK_HEADER + "".join(rows), encoding="utf-8")
    return export_dir


_CHUNK_HEADER = "sensorType,epochTimeMs,elapsedRealtimeNanos,accuracy,x,y,z,w\n"
# events.csv before the actualReps watch change (13 columns)...
_EVENT_HEADER_OLD = (
    "eventType,epochTimeMs,elapsedRealtimeNanos,stateName,exerciseId,exerciseName,"
    "setId,setIndex,exerciseType,noRepExpected,segmentId,reviewStatus,notes\n"
)
# ...and after it: SET_COMPLETED rows gain the trailing ground-truth column.
_EVENT_HEADER_NEW = _EVENT_HEADER_OLD[:-1] + ",actualReps\n"


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
    session_id: str = "analysis-session-1",
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
        "sessionId": session_id,
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


def _write_rest_recovery_bundle(tmp_path: Path, include_hr: bool) -> Path:
    """Bundle with one skipped short set, a 77 s rest, and a monotonically recovering HR.

    bpm(t) holds 150 for the first 10 s then decays 0.5 bpm/s, so the onset window
    medians exactly 150 and the +30/+60 s deltas are analytically known.
    """
    session_id = "rest-recovery-1"
    export_dir = tmp_path / session_id
    export_dir.mkdir(parents=True)
    rest_start = _elapsed(100)  # 2 s in
    rest_end = rest_start + 77 * 1_000_000_000
    segments = [
        _segment(
            "segment-set-short",
            0,
            _elapsed(0),
            _elapsed(49),
            "exercise-rest-recovery",
            "Rest Recovery Probe",
            "WEIGHT",
            False,
            "EXERCISE",
            "set-rest-recovery",
            session_id=session_id,
        ),
        _segment(
            "segment-rest-long",
            1,
            rest_start,
            rest_end,
            "exercise-rest-recovery",
            "Rest Recovery Probe",
            "WEIGHT",
            False,
            "REST",
            "set-rest-recovery",
            session_id=session_id,
        ),
        _segment(
            "segment-rest-short",
            2,
            rest_end,
            rest_end + 20 * 1_000_000_000,
            "exercise-rest-recovery",
            "Rest Recovery Probe",
            "WEIGHT",
            False,
            "REST",
            "set-rest-recovery",
            session_id=session_id,
        ),
    ]
    metadata = {
        "schemaVersion": 2,
        "session": {
            "id": session_id,
            "workoutId": str(uuid4()),
            "workoutHistoryId": str(uuid4()),
            "status": "COMPLETED",
            "startedAtEpochMs": _BASE_EPOCH_MS,
            "endedAtEpochMs": _BASE_EPOCH_MS + 100_000,
            "deviceManufacturer": "Google",
            "deviceModel": "Pixel Watch",
            "deviceName": "pixel_watch",
            "appVersion": "1.0.0",
            "sessionDirectoryName": session_id,
        },
        "sensorConfig": {
            "sampleRateHz": SAMPLE_RATE_HZ,
            "chunkSampleCount": 500,
            "enabledSensors": ["ACCELEROMETER", "GYROSCOPE", "ROTATION_VECTOR", "HEART_RATE"],
        },
        "workoutContext": {"workoutId": str(uuid4()), "workoutHistoryId": str(uuid4()), "orderedExerciseCandidates": []},
        "coarseReviewedSegments": segments,
        "rawSensorFiles": [{"fileName": "chunk_00001.csv"}],
        "eventsFile": "events.csv",
    }
    (export_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (export_dir / "events.csv").write_text(_EVENT_HEADER_NEW, encoding="utf-8")
    rows: list[str] = []
    # Static motion rows across the FULL 80 s span so the shared resampling grid
    # covers the rest segment (the grid is built from the most frequent type).
    for index in range(80 * SAMPLE_RATE_HZ):
        stamp = f"{_BASE_EPOCH_MS + index * 20},{_elapsed(index)}"
        rows.append(f"ACCELEROMETER,{stamp},3,0.0,0.0,9.81,\n")
        rows.append(f"GYROSCOPE,{stamp},3,0.0,0.0,0.0,\n")
        rows.append(f"ROTATION_VECTOR,{stamp},3,0.0,0.0,0.0,1.0\n")
    if include_hr:
        # 1 Hz bpm series: 150 flat for 10 s, then -0.5 bpm/s for 70 s.
        for second in range(0, 80):
            bpm = 150.0 if second <= 10 else 150.0 - 0.5 * (second - 10)
            stamp = f"{_BASE_EPOCH_MS + second * 1000},{_BASE_NANOS + second * 1_000_000_000}"
            rows.append(f"HEART_RATE,{stamp},3,{bpm:.1f},,,\n")
    (export_dir / "chunk_00001.csv").write_text(_CHUNK_HEADER + "".join(rows), encoding="utf-8")
    return export_dir


def test_rest_recovery_reports_hr_drop_at_30_and_60_seconds(tmp_path: Path) -> None:
    export_dir = _write_rest_recovery_bundle(tmp_path, include_hr=True)
    analysis_dir = analyze_session(_copy_into_workspace(export_dir, tmp_path / "ws"))
    metrics = json.loads((analysis_dir / METRICS_FILE_NAME).read_text(encoding="utf-8"))

    recovery = metrics["rest_recovery"]
    assert len(recovery) == 1, "only the 77 s rest qualifies; the 20 s rest is below the minimum"
    entry = recovery[0]
    assert entry["heart_rate_available"] is True
    assert entry["onset_bpm"] == pytest.approx(150.0, abs=1.0)
    # Rest starts at t=2 s, so rel 30 s / 60 s sample the decay at t=32 / 62:
    # 150 - 0.5*(t-10) -> 139 / 124 bpm.
    assert entry["delta_bpm_30s"] == pytest.approx(-11.0, abs=2.0)
    assert entry["delta_bpm_60s"] == pytest.approx(-26.0, abs=2.0)
    assert entry["delta_bpm_60s"] < entry["delta_bpm_30s"] < 0.0


def test_rest_recovery_is_empty_when_session_has_no_heart_rate(tmp_path: Path) -> None:
    export_dir = _write_rest_recovery_bundle(tmp_path, include_hr=False)
    analysis_dir = analyze_session(_copy_into_workspace(export_dir, tmp_path / "ws"))
    metrics = json.loads((analysis_dir / METRICS_FILE_NAME).read_text(encoding="utf-8"))

    assert metrics["rest_recovery"] == []
