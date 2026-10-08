"""Tempo-prior rep counting over filtered movement signals.

Pure functions over 1-D sample arrays (no I/O, no RNG, no hidden state) so the
logic can be ported to Kotlin directly. Sample indices refer to the caller's
arrays; convert to timestamps at the call site.

Selection strategy: candidate signals (gyro magnitude, accel projections, ...)
are scored by autocorrelation peak quality inside the 1-6 s rep-period band and
the best candidate is counted. Peak/valley prominence is chosen from a fixed
deterministic grid as the value whose peak count best matches the
autocorrelation-derived expected rep count.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy.signal import find_peaks

from motion_annotation_pkg.signals import robust_std

DEFAULT_MIN_REP_PERIOD_S = 1.0
DEFAULT_MAX_REP_PERIOD_S = 6.0
# Below this normalized autocorrelation the tempo prior is not trusted and peak
# counting falls back to a fixed prominence.
_MIN_TEMPO_QUALITY = 0.3
# Tolerance for treating a longer lag as a repeat of the fundamental rather than
# a distinct (stronger) periodicity.
_FUNDAMENTAL_MARGIN = 0.05
_PROMINENCE_MULTIPLIERS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
_DEFAULT_PROMINENCE_MULTIPLIER = 0.5
_VALLEY_PROMINENCE_FRACTION = 0.5
# With a trusted tempo, peaks closer than 0.7 of the rep period belong to the
# same rep (acceleration emits a drive and a braking lobe per stroke half);
# without a tempo, 0.6 of the minimum period is the conservative guard.
_TEMPO_DISTANCE_FRACTION = 0.7
_NO_TEMPO_DISTANCE_FRACTION = 0.6
# Rep boundaries are refined to "quiet" samples (|signal| below this fraction of
# the peak) so windows start and end near rest, which the phase detector's
# zero-velocity detrend and the trajectory ZUPT both rely on.
_QUIET_FRACTION = 0.2


@dataclass(frozen=True)
class RepDetection:
    """Rep boundaries as sample indices into the analyzed signal."""

    starts: np.ndarray
    peaks: np.ndarray
    ends: np.ndarray
    signal_source: str
    tempo_period_s: float
    tempo_quality: float
    # Rep count implied by the tempo prior (active span / period); |rep_count -
    # expected| is the detector's self-consistency signal. None without a trusted tempo.
    tempo_expected_count: float | None = None

    @property
    def rep_count(self) -> int:
        return int(self.starts.size)


def autocorrelation_tempo(
    values: np.ndarray,
    sample_rate_hz: float,
    min_period_s: float = DEFAULT_MIN_REP_PERIOD_S,
    max_period_s: float = DEFAULT_MAX_REP_PERIOD_S,
) -> tuple[float, float]:
    """Best periodicity inside the rep-period band as (period_s, quality).

    Quality is the unbiased normalized autocorrelation at the chosen lag clipped
    to [0, 1]; it measures how rep-like the segment is and drives candidate
    signal selection and the expected-rep-count prior.
    """
    x = np.asarray(values, dtype=np.float64)
    n = x.size
    if n < 8:
        return (0.0, 0.0)
    x = x - x.mean()
    zero_lag_energy = float(np.dot(x, x))
    if zero_lag_energy <= 0.0:
        return (0.0, 0.0)
    min_lag = max(int(round(min_period_s * sample_rate_hz)), 1)
    max_lag = min(int(round(max_period_s * sample_rate_hz)), n - 2)
    if max_lag <= min_lag:
        return (0.0, 0.0)
    autocorr = np.correlate(x, x, mode="full")[n - 1 :][min_lag : max_lag + 1]
    overlaps = n - np.arange(min_lag, max_lag + 1)
    normalized = autocorr / overlaps / (zero_lag_energy / n)
    # Perfectly periodic signals make every multiple of the true period score
    # ~1.0; the earliest lag within a small margin of the max is the fundamental.
    best_value = float(normalized.max())
    fundamental_candidates = np.flatnonzero(normalized >= best_value - _FUNDAMENTAL_MARGIN)
    best = int(fundamental_candidates[0])
    quality = float(np.clip(normalized[best], 0.0, 1.0))
    if quality <= 0.0:
        return (0.0, 0.0)
    return ((min_lag + best) / sample_rate_hz, quality)


def count_reps(
    values: np.ndarray,
    sample_rate_hz: float,
    signal_source: str = "",
    min_period_s: float = DEFAULT_MIN_REP_PERIOD_S,
    max_period_s: float = DEFAULT_MAX_REP_PERIOD_S,
) -> RepDetection:
    """Count reps in a filtered movement signal, returning valley-anchored rep boundaries."""
    values = np.asarray(values, dtype=np.float64)
    n = values.size
    empty = RepDetection(
        starts=np.empty(0, dtype=np.int64),
        peaks=np.empty(0, dtype=np.int64),
        ends=np.empty(0, dtype=np.int64),
        signal_source=signal_source,
        tempo_period_s=0.0,
        tempo_quality=0.0,
    )
    if n < 8:
        return empty
    period_s, quality = autocorrelation_tempo(values, sample_rate_hz, min_period_s, max_period_s)
    expected_count = None
    if quality >= _MIN_TEMPO_QUALITY and period_s > 0.0:
        active_span = _active_span_samples(values)
        if active_span is not None:
            active_span_s = (active_span[1] - active_span[0]) / sample_rate_hz
            # Expected reps from the active movement span, not the whole window:
            # trailing rest inside the segment would otherwise inflate the prior.
            expected_count = max(active_span_s / period_s, 1.0)
    sigma = robust_std(values)
    if sigma <= 0.0:
        return RepDetection(empty.starts, empty.peaks, empty.ends, signal_source, period_s, quality, expected_count)
    if expected_count is not None:
        distance = max(int(round(_TEMPO_DISTANCE_FRACTION * period_s * sample_rate_hz)), 1)
    else:
        distance = max(int(round(_NO_TEMPO_DISTANCE_FRACTION * min_period_s * sample_rate_hz)), 1)
    _, prominence = _choose_prominence(values, sigma, distance, expected_count)
    peaks, _ = find_peaks(values, prominence=prominence, distance=distance)
    valleys, _ = find_peaks(
        -values,
        prominence=_VALLEY_PROMINENCE_FRACTION * prominence,
        distance=distance,
    )
    if valleys.size:
        reps = _reps_from_peaks_and_valleys(peaks, valleys, n)
    else:
        period_samples = int(round(period_s * sample_rate_hz)) if period_s > 0 else distance * 2
        reps = _reps_from_peaks(peaks, n, max(period_samples, distance * 2))
    refinement_period = int(round(period_s * sample_rate_hz)) if period_s > 0 else distance * 2
    reps = _refine_boundaries_to_quiet_points(values, reps, max(refinement_period, distance))
    if not reps:
        return RepDetection(empty.starts, empty.peaks, empty.ends, signal_source, period_s, quality, expected_count)
    starts = np.array([rep[0] for rep in reps], dtype=np.int64)
    peaks_out = np.array([rep[1] for rep in reps], dtype=np.int64)
    ends = np.array([rep[2] for rep in reps], dtype=np.int64)
    return RepDetection(starts, peaks_out, ends, signal_source, period_s, quality, expected_count)


def count_reps_robust(
    candidates: dict[str, np.ndarray],
    sample_rate_hz: float,
    max_candidates: int = 4,
) -> tuple[str, RepDetection]:
    """Count reps choosing the candidate whose count best matches the consensus tempo.

    Magnitude signals rectify strokes and can double-count symmetric movements,
    while signed axes see the full cycle; neither failure shows up in
    autocorrelation quality alone. Ranking by count agreement with the median
    candidate period (then quality) resolves it deterministically.
    """
    if not candidates:
        raise ValueError("No candidate signals for rep counting")
    ranked = sorted(candidates, key=lambda name: (-autocorrelation_tempo(candidates[name], sample_rate_hz)[1], name))
    detections = [(name, count_reps(candidates[name], sample_rate_hz, signal_source=name)) for name in ranked[:max_candidates]]
    periods = [detection.tempo_period_s for _, detection in detections if detection.tempo_period_s > 0.0]
    if not periods:
        return detections[0]
    reference_period = float(np.median(periods))
    scored: list[tuple[str, RepDetection, float]] = []
    for name, detection in detections:
        span = _active_span_samples(candidates[name])
        active_span_s = (span[1] - span[0]) / sample_rate_hz if span else candidates[name].size / sample_rate_hz
        scored.append((name, detection, active_span_s / reference_period))
    name, detection, consensus_expected = min(
        scored,
        key=lambda entry: (abs(entry[1].rep_count - entry[2]), -entry[1].tempo_quality, entry[0]),
    )
    return name, replace(detection, tempo_expected_count=consensus_expected)


def _active_span_samples(values: np.ndarray, fraction: float = 0.15) -> tuple[int, int] | None:
    """First and last sample exceeding a fraction of the peak amplitude (movement span)."""
    amplitude = np.abs(values)
    if amplitude.size == 0 or amplitude.max() <= 0.0:
        return None
    active = np.flatnonzero(amplitude > fraction * float(amplitude.max()))
    if active.size == 0:
        return None
    return (int(active[0]), int(active[-1]))


def _choose_prominence(
    values: np.ndarray,
    sigma: float,
    distance: int,
    expected_count: float | None,
) -> tuple[float, float]:
    """Deterministic prominence selection: closest peak count to the tempo prior, ties toward larger prominence."""
    if expected_count is None:
        multiplier = _DEFAULT_PROMINENCE_MULTIPLIER
        return (multiplier, multiplier * sigma)
    best_multiplier, best_score = _PROMINENCE_MULTIPLIERS[0], float("inf")
    for multiplier in _PROMINENCE_MULTIPLIERS:
        peaks, _ = find_peaks(values, prominence=multiplier * sigma, distance=distance)
        score = abs(peaks.size - expected_count)
        if score < best_score or (score == best_score and multiplier > best_multiplier):
            best_multiplier, best_score = multiplier, score
    return (best_multiplier, best_multiplier * sigma)


def _refine_boundaries_to_quiet_points(
    values: np.ndarray,
    reps: list[tuple[int, int, int]],
    period_samples: int,
) -> list[tuple[int, int, int]]:
    """Move rep boundaries to nearby quiet points (local |signal| minima below _QUIET_FRACTION of peak).

    Peak/valley anchors of a signed signal sit at opposite-stroke extrema (e.g.
    the middle of the eccentric stroke), where velocity is maximal; phases
    integrated over such windows would need an invalid detrend. Quiet points
    (the pauses between reps) restore the rest-to-rest rep window: a rep starts
    at the last quiet point before its peak and ends where the next rep starts.
    When no quiet points exist (continuous cyclic signals) the original
    boundaries stay.
    """
    if not reps:
        return reps
    amplitude = np.abs(values)
    peak_amplitude = float(amplitude.max())
    if peak_amplitude <= 0.0:
        return reps
    quiet = amplitude <= _QUIET_FRACTION * peak_amplitude
    quiet_centers = _quiet_run_centers(quiet)
    if quiet_centers.size == 0:
        return reps
    starts: list[int] = []
    for _, peak, original_start in reps:
        before = quiet_centers[quiet_centers < peak]
        starts.append(int(before[-1]) if before.size else original_start)
    refined: list[tuple[int, int, int]] = []
    for index, (_, peak, original_end) in enumerate(reps):
        if index + 1 < len(reps):
            end = max(starts[index + 1], peak + 1)
        else:
            search_limit = min(peak + max(int(1.2 * period_samples), 1), values.size)
            after = quiet_centers[(quiet_centers > peak) & (quiet_centers < search_limit)]
            end = int(after[-1]) if after.size else max(original_end, peak + 1)
        refined.append((starts[index], peak, end))
    return _make_monotonic(refined)


def _quiet_run_centers(quiet: np.ndarray) -> np.ndarray:
    """Centers of consecutive True runs in a boolean mask (edges yield half-open runs)."""
    if quiet.size == 0 or not quiet.any():
        return np.empty(0, dtype=np.int64)
    padded = np.concatenate(([False], quiet, [False]))
    diffs = np.diff(padded.astype(np.int8))
    run_starts = np.flatnonzero(diffs == 1)
    run_ends = np.flatnonzero(diffs == -1)  # exclusive
    return ((run_starts + run_ends) // 2).astype(np.int64)


def _make_monotonic(reps: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    ordered: list[tuple[int, int, int]] = []
    for start, peak, end in sorted(reps):
        if ordered:
            start = max(start, ordered[-1][2])
            peak = max(peak, start + 1)
        end = max(end, peak + 1)
        ordered.append((start, peak, end))
    return ordered


def _reps_from_peaks_and_valleys(peaks: np.ndarray, valleys: np.ndarray, n: int) -> list[tuple[int, int, int]]:
    """Peak-anchored reps: one rep per peak, bounded by the neighboring valleys (or the signal edges).

    Peak count is what the prominence grid tuned against the tempo prior, so the
    rep count always matches it; valleys only refine the boundaries. Clamping
    keeps boundaries monotonic when a valley is missing between two peaks.
    """
    reps: list[tuple[int, int, int]] = []
    previous_end = 0
    for peak in peaks:
        peak = int(peak)
        valleys_before = valleys[valleys < peak]
        valleys_after = valleys[valleys > peak]
        start = int(valleys_before[-1]) if valleys_before.size else 0
        end = int(valleys_after[0]) if valleys_after.size else n - 1
        start = max(start, previous_end)
        end = max(end, peak + 1)
        reps.append((start, peak, end))
        previous_end = end
    return reps


def _reps_from_peaks(peaks: np.ndarray, n: int, period_samples: int) -> list[tuple[int, int, int]]:
    """Fallback when no valleys exist at all (e.g. unipolar pulse train without baseline gaps): midpoint boundaries."""
    if peaks.size < 1:
        return []
    half = max(period_samples // 2, 1)
    midpoints = ((peaks[:-1] + peaks[1:]) // 2).astype(np.int64)
    starts = np.concatenate(([max(int(peaks[0]) - half, 0)], midpoints))
    ends = np.concatenate((midpoints, [min(int(peaks[-1]) + half, n - 1)]))
    return [(int(start), int(peak), int(end)) for start, peak, end in zip(starts, peaks, ends)]
