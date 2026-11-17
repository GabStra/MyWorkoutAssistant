from __future__ import annotations

from exercise_motion_pkg.segment_detection import (
    DetectionWindow, normalize_execution_timestamp, parse_execution_payloads,
)


def test_structured_execution_snaps_rounded_window_end():
    # Timing fields reduced from the retained v130 response.
    response = {"executions": [{"start_seconds": 0., "end_seconds": 1.97, "complete": True}]}
    window = DetectionWindow(index=0, start_seconds=0.0, end_seconds=1.9685518852185517)

    executions = parse_execution_payloads(response["executions"], window=window)

    assert len(executions) == 1
    assert executions[0].complete is True
    assert executions[0].is_model_candidate is True
    assert executions[0].start_seconds == 0.0
    assert executions[0].end_seconds == window.end_seconds


def test_execution_timestamps_accept_local_and_preserve_absolute_preference():
    local_window = DetectionWindow(index=1, start_seconds=12.0, end_seconds=20.0)
    assert normalize_execution_timestamp(3.0, window=local_window) == 15.0

    overlapping_window = DetectionWindow(index=2, start_seconds=4.0, end_seconds=8.0)
    # 6.0 is inside the absolute window but outside its 4-second local range.
    assert normalize_execution_timestamp(6.0, window=overlapping_window) == 6.0
    assert normalize_execution_timestamp(4.0000005, window=overlapping_window) == 8.0


def test_only_exact_two_decimal_displayed_boundaries_snap():
    window = DetectionWindow(index=3, start_seconds=12.344, end_seconds=20.343)
    assert normalize_execution_timestamp(12.34, window=window) == window.start_seconds

    short_window = DetectionWindow(index=4, start_seconds=0.0, end_seconds=1.9685518852)
    assert normalize_execution_timestamp(1.97, window=short_window) == short_window.end_seconds
    assert normalize_execution_timestamp(1.98, window=short_window) is None
    assert normalize_execution_timestamp(-0.01, window=short_window) is None
