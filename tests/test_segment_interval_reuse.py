from collections import Counter
from pathlib import Path

import pytest

from exercise_motion_pkg import segment_detection as segment


@pytest.mark.parametrize("duration,first_response_invalid,expected_calls", [
    (3.003, False, 1), (3.003, True, 2), (25.0, False, None),
])
def test_retry_tiers_reuse_completed_intervals_only(tmp_path, monkeypatch, duration, first_response_invalid, expected_calls):
    monkeypatch.setattr(segment, "sanitize_video_for_processing", lambda path: path)
    monkeypatch.setattr(segment, "read_video_metadata", lambda path: segment.VideoMetadata(duration, 30, int(duration * 30), 640, 360))
    rendered = []
    def frames(**kwargs):
        window = kwargs["window"]
        rendered.append((window.start_seconds, window.end_seconds))
        return [Path("retained-frame.jpg")]
    monkeypatch.setattr(segment, "extract_window_frames", frames)
    reviewed = []
    class Client:
        def detect_window(self, **kwargs):
            window = kwargs["window"]
            reviewed.append((window.start_seconds, window.end_seconds))
            invalid = first_response_invalid and len(reviewed) == 1
            return segment.WindowDetection(window, False, False, False, None, None,
                0.0 if invalid else .9, "Unparsed" if invalid else "No execution",
                "invalid_json" if invalid else "Static setup", 0.0, ["retained-frame.jpg"])
    result = segment.detect_exercise_segment(video_path=tmp_path / "source.mp4",
        output_dir=tmp_path / "detection", client=Client(),
        settings=segment.DetectionSettings(window_seconds=14, classification_workers=1))
    assert result.detected_span is None
    assert rendered == reviewed
    assert len(result.windows) == len(reviewed)
    if expected_calls is not None:
        assert len(reviewed) == expected_calls
    else:
        assert max(Counter(reviewed).values()) == 1
        assert any(end - start > 14 for start, end in reviewed)


@pytest.mark.parametrize("confidences,needs_review", [([.9], False), ([0.0], True), ([.2], True), ([0.0, .9], False), ([], True)])
def test_no_span_routes_missing_evidence_separately_from_quality_rejection(confidences, needs_review):
    from exercise_motion_pkg.bake_and_rank import SourceCandidateRejected, reject_missing_source_span
    windows = [segment.WindowDetection(segment.DetectionWindow(i, 0, 3.003), False,
        False, False, None, None, confidence, "", "", 0, [])
        for i, confidence in enumerate(confidences)]
    result = segment.DetectionResult("source.mp4", "Exercise", 3.003, 14, 3, None, windows)
    with pytest.raises(SourceCandidateRejected) as error:
        reject_missing_source_span(result, confidence_threshold=.45)
    assert error.value.evidence["reviewIncomplete"] is needs_review
    assert error.value.reason_tags == ["source_cut_boundary_review_required" if needs_review else "source_segment_no_usable_span"]
