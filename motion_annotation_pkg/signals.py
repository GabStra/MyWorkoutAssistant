"""Signal filtering helpers for motion capture analysis.

All functions are pure numpy/scipy operations over 1-D sample arrays sampled at
a uniform rate, so the detectors built on top of them can be ported to Kotlin
without hidden state.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfiltfilt

# Rep-rate band: deliberate wrist movements repeat at 0.3-5 Hz (rep period 0.2-3.3 s
# per stroke half); the default window follows the analysis brief.
DEFAULT_BANDPASS_LOW_HZ = 0.3
DEFAULT_BANDPASS_HIGH_HZ = 5.0
_DEFAULT_ORDER = 4


def bandpass_filter(
    values: np.ndarray,
    sample_rate_hz: float,
    low_hz: float = DEFAULT_BANDPASS_LOW_HZ,
    high_hz: float = DEFAULT_BANDPASS_HIGH_HZ,
    order: int = _DEFAULT_ORDER,
) -> np.ndarray:
    """Zero-phase Butterworth bandpass (filtfilt), returning float64.

    Segments too short for the filter's transient (padlen) return zeros: with
    <1 s of usable samples there is no reliable periodic content to extract and
    callers must treat the result as unusable rather than noise-shaped signal.
    """
    values = np.asarray(values, dtype=np.float64)
    nyquist_hz = sample_rate_hz / 2.0
    if values.size < _MINIMUM_SAMPLES:
        return np.zeros_like(values)
    high = min(high_hz, 0.9 * nyquist_hz)
    low = min(low_hz, high / 2.0)
    sos = butter(order, [low, high], btype="bandpass", fs=sample_rate_hz, output="sos")
    return sosfiltfilt(sos, values, padlen=_padlen(order))


def lowpass_filter(values: np.ndarray, sample_rate_hz: float, cutoff_hz: float, order: int = _DEFAULT_ORDER) -> np.ndarray:
    """Zero-phase Butterworth lowpass with the same short-segment behavior as bandpass_filter."""
    values = np.asarray(values, dtype=np.float64)
    if values.size < _MINIMUM_SAMPLES:
        return np.zeros_like(values)
    cutoff = min(cutoff_hz, 0.9 * sample_rate_hz / 2.0)
    sos = butter(order, cutoff, btype="lowpass", fs=sample_rate_hz, output="sos")
    return sosfiltfilt(sos, values, padlen=_padlen(order))


def robust_std(values: np.ndarray) -> float:
    """MAD-based spread estimate; robust against rep bursts dominating the scale."""
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return 0.0
    median = np.median(values)
    return float(1.4826 * np.median(np.abs(values - median)))


def sliding_std(values: np.ndarray, window_samples: int) -> np.ndarray:
    """Per-sample rolling standard deviation over a centered window (edge windows shrink)."""
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0 or window_samples <= 1:
        return np.zeros_like(values)
    window_samples = min(window_samples, values.size)
    if window_samples <= 1:
        return np.zeros_like(values)
    half = window_samples // 2
    padded = np.pad(values, half, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window_samples)
    return windows.std(axis=1)[: values.size]


def _padlen(order: int) -> int:
    # scipy filtfilt default: 3 * (2*order + 1) for a biquad (sos) chain of one section.
    return 3 * (2 * order + 1)


_MINIMUM_SAMPLES = 3 * _padlen(_DEFAULT_ORDER)
