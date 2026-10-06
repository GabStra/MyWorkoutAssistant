"""Per-rep exercise-phase detection (concentric / eccentric / pause).

Velocity is reconstructed per rep by integrating the filtered movement-axis
acceleration and detrending it linearly so the rep starts and ends at zero
velocity (valid because reps are delimited at quasi-static points). Phase
transitions use hysteresis (a higher threshold to enter, a lower one to exit)
so sensor noise near zero crossings cannot chatter the labels.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motion_annotation_pkg.rep_detector import RepDetection

PHASE_CONCENTRIC = "concentric"
PHASE_ECCENTRIC = "eccentric"
PHASE_PAUSE = "pause"

# Enter at 35% of the rep's peak velocity, drop back to pause below 15%: wide
# enough separation to be robust against filtered-signal ringing at 50 Hz.
_ENTER_FRACTION = 0.35
_EXIT_FRACTION = 0.15
# Spans shorter than this are folded into pause: at 50 Hz two samples is 40 ms,
# under the fastest physiological phase transition we care about.
_MIN_PHASE_S = 0.04


@dataclass(frozen=True)
class PhaseSpan:
    label: str
    start: int  # inclusive sample index (into the set's signal)
    end: int  # exclusive sample index
    duration_s: float


@dataclass(frozen=True)
class RepPhases:
    rep_index: int
    start: int
    peak: int
    end: int
    spans: tuple[PhaseSpan, ...]

    @property
    def sequence(self) -> str:
        return "-".join(span.label for span in self.spans)


def detect_rep_phases(
    accel_signal: np.ndarray,
    sample_rate_hz: float,
    reps: RepDetection,
    enter_fraction: float = _ENTER_FRACTION,
    exit_fraction: float = _EXIT_FRACTION,
    min_phase_s: float = _MIN_PHASE_S,
) -> list[RepPhases]:
    """Split each detected rep into phase spans using a hysteresis state machine over per-rep velocity."""
    accel_signal = np.asarray(accel_signal, dtype=np.float64)
    results: list[RepPhases] = []
    for rep_index, (start, peak, end) in enumerate(zip(reps.starts, reps.peaks, reps.ends)):
        start_i, end_i = int(start), int(end)
        velocity = _per_rep_velocity(accel_signal[start_i : end_i + 1], sample_rate_hz)
        spans = _velocity_phases(
            velocity,
            sample_rate_hz,
            enter_fraction,
            exit_fraction,
            min_phase_s,
        )
        results.append(
            RepPhases(
                rep_index=rep_index + 1,
                start=start_i,
                peak=int(peak),
                end=end_i,
                spans=tuple(
                    PhaseSpan(label=span[0], start=span[1] + start_i, end=span[2] + start_i, duration_s=span[3])
                    for span in spans
                ),
            )
        )
    return results


def _per_rep_velocity(segment: np.ndarray, sample_rate_hz: float) -> np.ndarray:
    """Integrate accel to velocity and detrend so v(first)=v(last)=0 (rep starts/ends at rest)."""
    dt = 1.0 / sample_rate_hz
    velocity = np.zeros(segment.size, dtype=np.float64)
    if segment.size > 1:
        velocity[1:] = np.cumsum(0.5 * (segment[1:] + segment[:-1]) * dt)
    if segment.size > 1:
        velocity -= np.linspace(velocity[0], velocity[-1], segment.size)
    return velocity


def _velocity_phases(
    velocity: np.ndarray,
    sample_rate_hz: float,
    enter_fraction: float,
    exit_fraction: float,
    min_phase_s: float,
) -> list[tuple[str, int, int, float]]:
    if velocity.size == 0:
        return []
    vmax, vmin = float(velocity.max()), float(velocity.min())
    pos_enter = enter_fraction * vmax
    pos_exit = exit_fraction * vmax
    neg_enter = enter_fraction * vmin  # negative
    neg_exit = exit_fraction * vmin
    # Normalize sign so the first strong swing is concentric (device axes are arbitrary).
    first_strong = np.flatnonzero((velocity > pos_enter) | (velocity < neg_enter))
    if first_strong.size and velocity[first_strong[0]] < 0:
        velocity = -velocity
        vmax, vmin = -vmin, -vmax
        pos_enter, pos_exit = enter_fraction * vmax, exit_fraction * vmax
        neg_enter, neg_exit = enter_fraction * vmin, exit_fraction * vmin
    if vmax <= 0.0 and vmin >= 0.0:
        return [(PHASE_PAUSE, 0, velocity.size, velocity.size / sample_rate_hz)]
    labels = _hysteresis_labels(velocity, pos_enter, pos_exit, neg_enter, neg_exit)
    return _merge_spans(labels, velocity.size, sample_rate_hz, min_phase_s)


def _hysteresis_labels(
    velocity: np.ndarray,
    pos_enter: float,
    pos_exit: float,
    neg_enter: float,
    neg_exit: float,
) -> np.ndarray:
    labels = np.empty(velocity.size, dtype=np.int8)  # 0 pause, 1 concentric, -1 eccentric
    state = 0
    for index, value in enumerate(velocity):
        if state == 0:
            if value > pos_enter:
                state = 1
            elif value < neg_enter:
                state = -1
        elif state == 1:
            if value < pos_exit:
                state = 0
        else:
            if value > neg_exit:
                state = 0
        labels[index] = state
    return labels


def _merge_spans(
    labels: np.ndarray,
    n: int,
    sample_rate_hz: float,
    min_phase_s: float,
) -> list[tuple[str, int, int, float]]:
    label_names = {-1: PHASE_ECCENTRIC, 0: PHASE_PAUSE, 1: PHASE_CONCENTRIC}
    min_samples = max(int(round(min_phase_s * sample_rate_hz)), 1)
    runs: list[list[object]] = []
    for index in range(n):
        if runs and runs[-1][0] == labels[index]:
            runs[-1][2] = index + 1
        else:
            runs.append([int(labels[index]), index, index + 1])
    # Sub-minimum movement blips are filter ringing, not real phases: relabel to pause.
    for run in runs:
        if run[0] != 0 and (int(run[2]) - int(run[1])) < min_samples:
            run[0] = 0
    merged: list[list[object]] = []
    for run in runs:
        if merged and merged[-1][0] == run[0]:
            merged[-1][2] = run[2]
        else:
            merged.append(run)
    return [
        (label_names[int(label)], int(start), int(end), (int(end) - int(start)) / sample_rate_hz)
        for label, start, end in merged
    ]
