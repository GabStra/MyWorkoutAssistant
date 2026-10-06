"""Offline session analysis: rep counting, exercise-phase detection, 3D wrist reconstruction.

`analyze_session` reads a recorded session (export or workspace layout), analyzes
every rep-based EXERCISE segment, and writes `<session-dir>/analysis/` with
metrics.json, per-set trajectory and time-series PNGs, and per-set replay data
(NPZ + CSV). Per-set rep-count ground truth comes from the SET_COMPLETED events
(actualReps column) when the session carries it, falling back to the optional
ground-truth map (setId -> rep count) file; either source adds per-set
count-error fields tagged with `ground_truth_source`.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from motion_annotation_pkg.frames import SensorFrames, build_sensor_frames, magnitude, resolve_export_dir
from motion_annotation_pkg.loader import load_export_bundle
from motion_annotation_pkg.phase_detector import detect_rep_phases
from motion_annotation_pkg.plots import plot_signal_overlays, plot_trajectory_phases
from motion_annotation_pkg.rep_detector import RepDetection, autocorrelation_tempo, count_reps_robust
from motion_annotation_pkg.signals import bandpass_filter
from motion_annotation_pkg.trajectory import TrajectoryResult, reconstruct_trajectory

ANALYSIS_DIR_NAME = "analysis"
METRICS_FILE_NAME = "metrics.json"
# Sets shorter than this cannot support the bandpass transient plus tempo estimation.
_MIN_SET_SAMPLES = 60
# Signed axis signals usable for phase velocity integration (magnitudes are rectified
# and must not be integrated).
_PHASE_SIGNAL_SOURCES = ("accel_x", "accel_y", "accel_z", "linear_x", "linear_y", "linear_z")
_PHASE_CODES = {"pause": 0, "concentric": 1, "eccentric": 2}
# Detector-confidence bands from autocorrelation peak quality: clean cyclic sets
# score > 0.8; below 0.4 the tempo prior is not trusted for counting at all.
_CONFIDENCE_HIGH = 0.7
_CONFIDENCE_MEDIUM = 0.4


def analyze_session(session_dir: str | Path, ground_truth_reps: str | Path | None = None) -> Path:
    session_path = Path(session_dir)
    export_dir = resolve_export_dir(session_path)
    bundle = load_export_bundle(export_dir)
    frames = build_sensor_frames(bundle)
    metadata = bundle["metadata"]
    analysis_dir = session_path / ANALYSIS_DIR_NAME
    analysis_dir.mkdir(parents=True, exist_ok=True)
    ground_truth = _load_ground_truth(ground_truth_reps)
    event_counts_by_segment, event_counts_by_set = _event_ground_truth(bundle["events"])

    segments = sorted(metadata.get("coarseReviewedSegments", []), key=lambda entry: int(entry["startedAtElapsedRealtimeNanos"]))
    set_reports = []
    exercise_set_index = 0
    for segment in segments:
        label = segment.get("correctedLabel") or segment["autoLabel"]
        if label.get("kind") != "EXERCISE" or label.get("noRepExpected"):
            continue
        set_id = str(label.get("setId") or segment["id"])
        report = _analyze_set(segment, label, set_id, exercise_set_index, frames, analysis_dir)
        ground_truth_count, ground_truth_source = _resolve_ground_truth_count(
            segment, set_id, event_counts_by_segment, event_counts_by_set, ground_truth
        )
        if ground_truth_count is not None and report.get("status") == "analyzed":
            report["ground_truth_rep_count"] = ground_truth_count
            report["ground_truth_source"] = ground_truth_source
            report["rep_count_error"] = report["rep_count"] - ground_truth_count
        set_reports.append(report)
        exercise_set_index += 1

    metrics = {
        "schema_version": 1,
        "session_id": metadata["session"]["id"],
        "sample_rate_hz": frames.sample_rate_hz,
        "sets": set_reports,
        "coverage": _coverage_summary(set_reports),
    }
    (analysis_dir / METRICS_FILE_NAME).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return analysis_dir


def _analyze_set(
    segment: dict[str, Any],
    label: dict[str, Any],
    set_id: str,
    set_index: int,
    frames: SensorFrames,
    analysis_dir: Path,
) -> dict[str, Any]:
    start_nanos = int(segment["startedAtElapsedRealtimeNanos"])
    end_nanos = int(segment.get("endedAtElapsedRealtimeNanos") or start_nanos)
    sub = frames.slice(start_nanos, end_nanos)
    report: dict[str, Any] = {
        "set_id": set_id,
        "segment_id": str(segment["id"]),
        "exercise_id": label.get("exerciseId"),
        "exercise_name": label.get("exerciseName"),
        "exercise_type": label.get("exerciseType"),
        # Null until a rep-count ground truth is attached (event or file).
        "ground_truth_source": None,
    }
    if sub.timestamps_nanos.size < _MIN_SET_SAMPLES:
        report.update({"status": "skipped", "reason": f"only {sub.timestamps_nanos.size} samples in segment"})
        return report

    candidates = _filtered_candidates(sub, sub.sample_rate_hz)
    source, detection = count_reps_robust(candidates, sub.sample_rate_hz)
    phase_source = _select_phase_signal(candidates)
    phase_accel = _phase_integration_signal(sub, phase_source, detection.tempo_period_s)
    phases = detect_rep_phases(phase_accel, sub.sample_rate_hz, detection)
    trajectory = _reconstruct_set_trajectory(sub)

    prefix = f"set{set_index:02d}_{_sanitize(set_id)}"
    phase_per_sample = _phase_per_sample(sub.timestamps_nanos.size, phases)
    _write_set_plots(sub, candidates, source, detection, phase_per_sample, trajectory, prefix, analysis_dir)
    _write_replay_data(sub, trajectory, phases, phase_per_sample, prefix, analysis_dir)

    report.update(
        {
            "status": "analyzed",
            "rep_count": detection.rep_count,
            "signal_source": source,
            "tempo_period_s": detection.tempo_period_s,
            "tempo_quality": detection.tempo_quality,
            "detector_confidence": _detector_confidence(detection),
            **_set_metrics(detection, phases, trajectory, sub.timestamps_nanos),
            "reps": [_rep_row(index, detection, phase, sub, start_nanos, trajectory) for index, phase in enumerate(phases)],
        }
    )
    return report


def _candidate_signals(sub: SensorFrames) -> dict[str, np.ndarray]:
    """Unfiltered movement signals per sensor type, built generically (forward-compatible)."""
    signals: dict[str, np.ndarray] = {}
    gyro = sub.frame("GYROSCOPE")
    if gyro is not None:
        signals["gyro_magnitude"] = magnitude(gyro["x"], gyro["y"], gyro["z"])
        for axis in ("x", "y", "z"):
            signals[f"gyro_{axis}"] = gyro[axis]
    accel = sub.frame("ACCELEROMETER")
    if accel is not None:
        signals["accel_magnitude"] = magnitude(accel["x"], accel["y"], accel["z"])
        for axis in ("x", "y", "z"):
            signals[f"accel_{axis}"] = accel[axis]
    linear = sub.frame("LINEAR_ACCELERATION")  # forward-compat: newer watch builds emit this
    if linear is not None:
        signals["linear_magnitude"] = magnitude(linear["x"], linear["y"], linear["z"])
        for axis in ("x", "y", "z"):
            signals[f"linear_{axis}"] = linear[axis]
    return signals


def _filtered_candidates(sub: SensorFrames, sample_rate_hz: float) -> dict[str, np.ndarray]:
    """Bandpassed candidate signals for rep/phase detection.

    Both magnitudes and signed axis projections are offered: signed axes carry
    the full rep cycle (one extremum per stroke direction), magnitudes are more
    robust when the movement axis is not axis-aligned; count_reps_robust picks
    between them per segment. The highpass edge adapts to a coarse tempo
    estimate so slow reps (period > 3 s, fundamental below 0.3 Hz) keep their
    shape instead of being attenuated by a fixed 0.3 Hz edge.
    """
    raw = _candidate_signals(sub)
    coarse_source = "gyro_magnitude" if "gyro_magnitude" in raw else next(iter(raw), None)
    if coarse_source is None:
        return {}
    low_hz = 0.3
    coarse = bandpass_filter(raw[coarse_source], sample_rate_hz)
    period_s, quality = autocorrelation_tempo(coarse, sample_rate_hz)
    if quality >= _CONFIDENCE_MEDIUM and period_s > 0.0:
        low_hz = float(np.clip(0.25 / period_s, 0.05, 0.3))
    return {name: bandpass_filter(values, sample_rate_hz, low_hz=low_hz) for name, values in raw.items()}


def _detector_confidence(detection: RepDetection) -> dict[str, Any]:
    """Per-set reliability signal: periodicity strength and tempo-vs-count agreement.

    Wrist-only counting cannot serve every exercise; low-band sets must be
    flagged rather than silently miscounted.
    """
    quality = detection.tempo_quality
    band = "high" if quality >= _CONFIDENCE_HIGH else ("medium" if quality >= _CONFIDENCE_MEDIUM else "low")
    expected = detection.tempo_expected_count
    return {
        "tempo_quality": float(quality),
        "band": band,
        "expected_rep_count_from_tempo": round(float(expected), 2) if expected is not None else None,
        "count_deviation": round(abs(detection.rep_count - expected), 2) if expected is not None else None,
    }


def _coverage_summary(set_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Rep-counting coverage boundary aggregated per exercise and per exercise type.

    Ground-truth errors group into mean/max absolute count error so it is
    explicit which movement classes wrist-only counting serves.
    """
    return {
        "by_exercise": _coverage_groups(set_reports, lambda report: (report.get("exercise_id"), report.get("exercise_name"))),
        "by_exercise_type": _coverage_groups(set_reports, lambda report: report.get("exercise_type")),
    }


def _coverage_groups(set_reports: list[dict[str, Any]], key_of) -> list[dict[str, Any]]:
    groups: dict[Any, list[dict[str, Any]]] = {}
    for report in set_reports:
        groups.setdefault(key_of(report), []).append(report)
    entries = []
    for key in sorted(groups, key=lambda value: str(value)):
        reports = groups[key]
        analyzed = [report for report in reports if report.get("status") == "analyzed"]
        with_ground_truth = [report for report in analyzed if report.get("rep_count_error") is not None]
        errors = [abs(int(report["rep_count_error"])) for report in with_ground_truth]
        qualities = [report["detector_confidence"]["tempo_quality"] for report in analyzed]
        entry: dict[str, Any] = {
            "set_count": len(reports),
            "analyzed_set_count": len(analyzed),
            "skipped_set_count": len(reports) - len(analyzed),
            "ground_truth_set_count": len(with_ground_truth),
            "mean_abs_rep_count_error": float(np.mean(errors)) if errors else None,
            "max_abs_rep_count_error": int(max(errors)) if errors else None,
            "mean_tempo_quality": float(np.mean(qualities)) if qualities else None,
            "low_confidence_set_ids": [report["set_id"] for report in analyzed if report["detector_confidence"]["band"] == "low"],
        }
        if isinstance(key, tuple):
            entry["exercise_id"], entry["exercise_name"] = key
        else:
            entry["exercise_type"] = key
        entries.append(entry)
    return entries


def _select_phase_signal(candidates: dict[str, np.ndarray]) -> str:
    """Dominant signed accel axis by bandpassed RMS (ties: alphabetical).

    The phase axis must carry the full stroke: picking by periodicity alone can
    select a secondary sway axis whose velocity sign pattern mislabels phases.
    """
    allowed = [name for name in _PHASE_SIGNAL_SOURCES if name in candidates]
    if not allowed:
        raise ValueError("No signed acceleration axis available for phase detection")
    return min(allowed, key=lambda name: (-float(np.sqrt(np.mean(candidates[name] ** 2))), name))


def _phase_integration_signal(sub: SensorFrames, source: str, tempo_period_s: float) -> np.ndarray:
    """Movement-axis accel filtered for velocity integration (phase detection).

    The highpass edge sits at a quarter of the rep frequency (clamped to
    0.05-0.3 Hz), well below the rep fundamental: a fixed 0.3 Hz edge would
    attenuate strokes slower than ~3 s and distort the integrated velocity
    shape that phase thresholds depend on.
    """
    prefix, axis = source.split("_")
    sensor_type = {"accel": "ACCELEROMETER", "linear": "LINEAR_ACCELERATION"}[prefix]
    frame = sub.frame(sensor_type)
    if frame is None:
        raise ValueError(f"Phase signal source {source} has no {sensor_type} samples")
    low_hz = float(np.clip(0.25 / tempo_period_s, 0.05, 0.3)) if tempo_period_s > 0.0 else 0.3
    return bandpass_filter(frame[axis], sub.sample_rate_hz, low_hz=low_hz)


def _raw_signal(sub: SensorFrames, source: str) -> np.ndarray | None:
    """Unfiltered counterpart of a candidate name, for the overlay plot."""
    parts = source.split("_")
    if parts[0] == "gyro":
        gyro = sub.frame("GYROSCOPE")
        return magnitude(gyro["x"], gyro["y"], gyro["z"]) if gyro else None
    if parts[0] == "accel":
        accel = sub.frame("ACCELEROMETER")
        return None if accel is None else _raw_axis_or_magnitude(accel, parts, 1)
    if parts[0] == "linear":
        linear = sub.frame("LINEAR_ACCELERATION")
        return None if linear is None else _raw_axis_or_magnitude(linear, parts, 1)
    return None


def _raw_axis_or_magnitude(frame: dict[str, np.ndarray], parts: list[str], axis_index: int) -> np.ndarray:
    if len(parts) > axis_index and parts[axis_index] in ("x", "y", "z"):
        return frame[parts[axis_index]]
    return magnitude(frame["x"], frame["y"], frame["z"])


def _reconstruct_set_trajectory(sub: SensorFrames) -> TrajectoryResult | None:
    rotation = sub.frame("ROTATION_VECTOR")
    if rotation is None:
        return None
    quaternions = np.column_stack([rotation["x"], rotation["y"], rotation["z"], rotation["w"]])
    linear = sub.frame("LINEAR_ACCELERATION")
    if linear is not None:
        accel = np.column_stack([linear["x"], linear["y"], linear["z"]])
        return reconstruct_trajectory(accel, quaternions, sub.timestamps_nanos, gravity_removed=True)
    accel = sub.frame("ACCELEROMETER")
    if accel is None:
        return None
    accel_xyz = np.column_stack([accel["x"], accel["y"], accel["z"]])
    return reconstruct_trajectory(accel_xyz, quaternions, sub.timestamps_nanos, gravity_removed=False)


def _set_metrics(
    detection: RepDetection,
    phases: list,
    trajectory: TrajectoryResult | None,
    timestamps_nanos: np.ndarray,
) -> dict[str, Any]:
    rep_durations = (timestamps_nanos[detection.ends] - timestamps_nanos[detection.starts]).astype(np.float64) / 1e9
    metrics: dict[str, Any] = {
        "mean_tempo_s": float(rep_durations.mean()) if rep_durations.size else None,
        "tempo_decay_ratio": _thirds_ratio(rep_durations),
        "mean_phase_duration_s": _mean_phase_durations(phases),
    }
    if trajectory is None:
        return metrics
    speed = np.linalg.norm(trajectory.velocity, axis=1)
    rep_peak_speeds = np.array(
        [float(np.abs(speed[start : end + 1]).max()) if end > start else 0.0 for start, end in zip(detection.starts, detection.ends)]
    )
    rep_path_lengths = np.array(
        [_path_length(trajectory.position, start, end) for start, end in zip(detection.starts, detection.ends)]
    )
    rep_displacements = np.array(
        [_max_displacement(trajectory.position, start, end) for start, end in zip(detection.starts, detection.ends)]
    )
    metrics.update(
        {
            "mean_peak_speed_mps": float(rep_peak_speeds.mean()) if rep_peak_speeds.size else None,
            "speed_decay_ratio": _thirds_ratio(rep_peak_speeds),
            "rom_proxy": {
                "mean_rep_path_length_m": float(rep_path_lengths.mean()) if rep_path_lengths.size else None,
                "mean_rep_max_displacement_m": float(rep_displacements.mean()) if rep_displacements.size else None,
            },
            "drift": trajectory.drift_metrics,
        }
    )
    return metrics


def _mean_phase_durations(phases: list) -> dict[str, float]:
    totals: dict[str, list[float]] = {}
    for rep in phases:
        for span in rep.spans:
            totals.setdefault(span.label, []).append(span.duration_s)
    return {label: float(np.mean(durations)) for label, durations in sorted(totals.items())}


def _thirds_ratio(values: np.ndarray) -> float | None:
    """Last-third mean over first-third mean; > 1 means slower/heavier late in the set."""
    if values.size < 3:
        return None
    third = values.size // 3
    first = float(values[:third].mean())
    last = float(values[-third:].mean())
    return last / first if first > 0 else None


def _path_length(position: np.ndarray, start: int, end: int) -> float:
    segment = position[start : end + 1]
    if segment.shape[0] < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(segment, axis=0), axis=1).sum())


def _max_displacement(position: np.ndarray, start: int, end: int) -> float:
    segment = position[start : end + 1]
    if segment.shape[0] < 2:
        return 0.0
    return float(np.linalg.norm(segment - segment[0], axis=1).max())


def _rep_row(
    index: int,
    detection: RepDetection,
    rep_phases,
    sub: SensorFrames,
    set_start_nanos: int,
    trajectory: TrajectoryResult | None,
) -> dict[str, Any]:
    start, peak, end = int(detection.starts[index]), int(detection.peaks[index]), int(detection.ends[index])
    peak_speed = None
    if trajectory is not None and end > start:
        speed = np.linalg.norm(trajectory.velocity[start : end + 1], axis=1)
        peak_speed = float(speed.max()) if speed.size else None
    return {
        "rep_index": index + 1,
        "start_nanos": int(sub.timestamps_nanos[start]),
        "peak_nanos": int(sub.timestamps_nanos[peak]),
        "end_nanos": int(sub.timestamps_nanos[end]),
        "start_epoch_ms": int(sub.timestamps_epoch_ms[start]),
        "peak_epoch_ms": int(sub.timestamps_epoch_ms[peak]),
        "end_epoch_ms": int(sub.timestamps_epoch_ms[end]),
        "start_offset_s": float((sub.timestamps_nanos[start] - set_start_nanos) / 1e9),
        "peak_offset_s": float((sub.timestamps_nanos[peak] - set_start_nanos) / 1e9),
        "end_offset_s": float((sub.timestamps_nanos[end] - set_start_nanos) / 1e9),
        "duration_s": float((sub.timestamps_nanos[end] - sub.timestamps_nanos[start]) / 1e9),
        "peak_speed_mps": peak_speed,
        "phase_sequence": rep_phases.sequence,
        "phases": [
            {
                "label": span.label,
                "start_offset_s": float((sub.timestamps_nanos[span.start] - set_start_nanos) / 1e9),
                "end_offset_s": float((sub.timestamps_nanos[min(span.end, sub.timestamps_nanos.size - 1)] - set_start_nanos) / 1e9),
                "duration_s": span.duration_s,
            }
            for span in rep_phases.spans
        ],
    }


def _phase_per_sample(n: int, phases: list) -> np.ndarray:
    labels = np.full(n, "pause", dtype=object)
    for rep in phases:
        for span in rep.spans:
            labels[span.start : span.end] = span.label
    return labels


def _write_set_plots(
    sub: SensorFrames,
    candidates: dict[str, np.ndarray],
    source: str,
    detection: RepDetection,
    phase_per_sample: np.ndarray,
    trajectory: TrajectoryResult | None,
    prefix: str,
    analysis_dir: Path,
) -> None:
    times_s = (sub.timestamps_nanos - sub.timestamps_nanos[0]) / 1e9
    boundaries = [float(times_s[index]) for index in detection.starts]
    raw = _raw_signal(sub, source)
    if raw is not None:
        plot_signal_overlays(
            times_s,
            raw,
            candidates[source],
            boundaries,
            analysis_dir / f"{prefix}_timeseries.png",
            title=f"{prefix} reps via {source} ({detection.rep_count} found)",
        )
    if trajectory is not None:
        plot_trajectory_phases(
            trajectory.position,
            phase_per_sample,
            analysis_dir / f"{prefix}_trajectory.png",
            title=f"{prefix} wrist path",
        )


def _write_replay_data(
    sub: SensorFrames,
    trajectory: TrajectoryResult | None,
    phases: list,
    phase_per_sample: np.ndarray,
    prefix: str,
    analysis_dir: Path,
) -> None:
    if trajectory is None:
        return
    np.savez_compressed(
        analysis_dir / f"{prefix}_path.npz",
        timestamps_nanos=sub.timestamps_nanos,
        epoch_ms=sub.timestamps_epoch_ms,
        position=trajectory.position,
        velocity=trajectory.velocity,
        static_mask=trajectory.static_mask,
        drift_metrics=np.array([json.dumps(trajectory.drift_metrics)]),
        phase_codes=np.array([_PHASE_CODES[label] for label in phase_per_sample], dtype=np.uint8),
        rep_starts=np.array([rep.start for rep in phases], dtype=np.int64),
        rep_peaks=np.array([rep.peak for rep in phases], dtype=np.int64),
        rep_ends=np.array([rep.end for rep in phases], dtype=np.int64),
    )
    with (analysis_dir / f"{prefix}_path.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rep_index", "phase", "t_offset_s", "x_m", "y_m", "z_m"])
        rep_index_by_sample = _rep_index_by_sample(sub.timestamps_nanos.size, phases)
        start_nanos = int(sub.timestamps_nanos[0])
        for index in range(sub.timestamps_nanos.size):
            writer.writerow(
                [
                    rep_index_by_sample[index],
                    phase_per_sample[index],
                    (int(sub.timestamps_nanos[index]) - start_nanos) / 1e9,
                    f"{trajectory.position[index, 0]:.5f}",
                    f"{trajectory.position[index, 1]:.5f}",
                    f"{trajectory.position[index, 2]:.5f}",
                ]
            )


def _rep_index_by_sample(n: int, phases: list) -> list[int]:
    indices = [0] * n
    for rep in phases:
        for index in range(rep.start, min(rep.end + 1, n)):
            indices[index] = rep.rep_index
    return indices


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:40]


def _load_ground_truth(ground_truth_reps: str | Path | None) -> dict[str, int]:
    if ground_truth_reps is None:
        return {}
    payload = json.loads(Path(ground_truth_reps).read_text(encoding="utf-8"))
    return {str(set_id): int(count) for set_id, count in payload.items()}


def _event_ground_truth(
    events: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, list[tuple[int, int]]]]:
    """Rep counts embedded in SET_COMPLETED events, indexed by segmentId and by setId.

    Events without a parsable actualReps value (old watch builds, timed sets)
    carry no ground truth and are skipped; a later completion for the same
    segment overrides an earlier one.
    """
    by_segment: dict[str, int] = {}
    by_set: dict[str, list[tuple[int, int]]] = {}
    for event in events:
        if (event.get("eventType") or "").strip().lower() != "set_completed":
            continue
        actual_reps = event.get("actualReps")
        if actual_reps is None:
            continue
        segment_id = event.get("segmentId")
        if segment_id:
            by_segment[segment_id] = int(actual_reps)
        set_id = event.get("setId")
        if set_id:
            by_set.setdefault(set_id, []).append((int(event["elapsedRealtimeNanos"]), int(actual_reps)))
    return by_segment, by_set


def _resolve_ground_truth_count(
    segment: dict[str, Any],
    set_id: str,
    event_counts_by_segment: dict[str, int],
    event_counts_by_set: dict[str, list[tuple[int, int]]],
    file_ground_truth: dict[str, int],
) -> tuple[int | None, str | None]:
    """Per-set rep-count ground truth with its source ("event" | "file" | None).

    Precedence: SET_COMPLETED event ground truth (join by segmentId first, then
    the latest set-matching completion at or before the segment ends) overrides
    the optional --ground-truth-reps JSON file, which remains the fallback for
    sessions whose events carry no actualReps values.
    """
    event_count = event_counts_by_segment.get(str(segment["id"]))
    if event_count is not None:
        return event_count, "event"
    end_nanos = int(segment.get("endedAtElapsedRealtimeNanos") or segment["startedAtElapsedRealtimeNanos"])
    completions_before_end = [entry for entry in event_counts_by_set.get(set_id, []) if entry[0] <= end_nanos]
    if completions_before_end:
        return max(completions_before_end, key=lambda entry: entry[0])[1], "event"
    file_count = file_ground_truth.get(set_id)
    if file_count is not None:
        return file_count, "file"
    return None, None
