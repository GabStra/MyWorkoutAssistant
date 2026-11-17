from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace

from exercise_motion_pkg.bake_and_rank import (
    BakeAndRankRequest, effective_segment_min_seconds, explicit_segment_min_seconds,
    source_window_min_seconds_for_candidate,
)
from exercise_motion_pkg.segment_detection import (
    CandidateExecution, DetectionSettings, DetectionWindow, WindowDetection, choose_detected_span,
    refine_span_with_comparative_selection,
)


def _complete_execution(end_seconds: float) -> CandidateExecution:
    return CandidateExecution(
        start_seconds=0.0, end_seconds=end_seconds, complete=True, single_execution=True,
        normal_speed=True, not_broken_into_steps=True, fixed_camera=True, single_person=True,
        fully_in_frame=True, unobstructed=True, extra_motion_before=False, extra_motion_after=False,
        partial_movement=False, full_movement_coverage=1.0, start_posture_visible=True,
        full_action_path_visible=True, end_posture_visible=True, target_exercise_match=1.0,
        wrong_exercise_or_unrelated_movement=False, loop_quality=0.0,
        suggested_loop_start_seconds=None, suggested_loop_end_seconds=None,
        actual_demonstration=True, title_or_instruction_screen=False,
        screen_with_embedded_video=False, contains_multiple_executions=False,
        contains_idle_or_reset=False, confidence=0.95, quality=0.9,
    )


def _detection(duration: float, *, structured: bool) -> WindowDetection:
    window = DetectionWindow(index=0, start_seconds=0.0, end_seconds=duration)
    return WindowDetection(
        window=window, movement_present=True, contains_movement_start=True,
        contains_movement_end=True, movement_start_seconds=0.0,
        movement_end_seconds=duration, confidence=0.95, summary="complete cycle",
        reason="complete cycle", camera_variation=0.0, frame_paths=[],
        executions=(_complete_execution(duration),) if structured else (),
    )


def test_default_keeps_complete_structured_short_execution_exact():
    duration = 1.9685518852185517
    span = choose_detected_span(
        detections=[_detection(duration, structured=True)], confidence_threshold=0.45,
        merge_gap_seconds=0.0, max_segment_seconds=20.0,
    )
    assert span is not None
    assert span.start_seconds == 0.0
    assert span.end_seconds == duration


def test_explicit_two_second_minimum_remains_authoritative():
    span = choose_detected_span(
        detections=[_detection(1.9685518852185517, structured=True)],
        confidence_threshold=0.45, merge_gap_seconds=0.0,
        min_segment_seconds=2.0, max_segment_seconds=20.0,
    )
    assert span is None


def test_default_search_floor_still_rejects_short_unstructured_interval():
    span = choose_detected_span(
        detections=[_detection(1.9685518852185517, structured=False)],
        confidence_threshold=0.45, merge_gap_seconds=0.0, max_segment_seconds=20.0,
    )
    assert span is None


def test_default_request_and_cli_preserve_unset_minimum_and_numeric_search_floor():
    request = BakeAndRankRequest(
        candidates_json=Path("candidates.json"), workspace=Path("workspace"),
        body_model_root=None,
    )
    assert request.segment_min_seconds is None
    assert DetectionSettings().min_segment_seconds is None
    assert effective_segment_min_seconds(request.segment_min_seconds) == 2.0
    candidate = SimpleNamespace(candidate={})
    assert source_window_min_seconds_for_candidate(candidate, request) == 2.0

    from exercise_motion_pkg.cli import build_bake_and_rank_request, build_parser
    parser = build_parser()
    default_args = parser.parse_args(["bake-and-rank", "--candidates-json", "candidates.json"])
    assert default_args.segment_min_seconds is None
    assert build_bake_and_rank_request(default_args).segment_min_seconds is None

    explicit_args = parser.parse_args([
        "bake-and-rank", "--candidates-json", "candidates.json", "--segment-min-seconds", "2.0",
    ])
    assert build_bake_and_rank_request(explicit_args).segment_min_seconds == 2.0


def test_source_cut_callers_preserve_only_explicit_minimum():
    assert explicit_segment_min_seconds(None) is None
    assert explicit_segment_min_seconds(2.0) == 2.0


def test_default_minimum_does_not_expand_explicit_maximum():
    span = choose_detected_span(
        detections=[_detection(1.9685518852185517, structured=True)],
        confidence_threshold=0.45, merge_gap_seconds=0.0, max_segment_seconds=1.0,
    )
    assert span is None


def test_comparative_selection_handles_unset_minimum_with_multiple_fast_candidates(monkeypatch):
    import exercise_motion_pkg.segment_detection as segment_detection

    duration = 1.9685518852185517
    first = _detection(duration, structured=True)
    second_execution = replace(
        _complete_execution(duration), start_seconds=3.0, end_seconds=3.0 + duration,
    )
    second = replace(
        first, window=DetectionWindow(index=1, start_seconds=3.0, end_seconds=3.0 + duration),
        executions=(second_execution,),
    )
    detections = [first, second]
    settings = DetectionSettings(comparative_selection_enabled=True)
    selected = choose_detected_span(
        detections=detections, confidence_threshold=0.45, merge_gap_seconds=0.0,
        settings=settings,
    )
    assert selected is not None
    monkeypatch.setattr(
        segment_detection, "select_best_candidate_window_with_vlm",
        lambda **kwargs: 0,
    )

    refined = refine_span_with_comparative_selection(
        client=object(), detections=detections, selected_span=selected,
        confidence_threshold=0.45, min_segment_seconds=settings.min_segment_seconds,
        max_segment_seconds=20.0, settings=settings, exercise_name="test",
    )

    assert refined.start_seconds == 0.0
    assert refined.end_seconds == duration
