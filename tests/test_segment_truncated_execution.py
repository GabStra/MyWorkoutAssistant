import pytest

from exercise_motion_pkg.segment_detection import DetectionWindow, parse_detection_payload


def test_truncated_structured_execution_cannot_invent_legacy_safety_attestations():
    raw = ('{"movement_present":true,"movement_start_seconds":0.0,'
           '"movement_end_seconds":1.9686,"confidence":0.95,'
           '"executions":[{"complete":true,"loop')
    with pytest.raises(RuntimeError, match="truncated execution JSON"):
        parse_detection_payload(
            raw, window=DetectionWindow(index=0, start_seconds=0., end_seconds=1.9686))
