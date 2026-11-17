"""Focused regression tests for the bounded coarse-negative challenge."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from exercise_motion_pkg.segment_detection import (
    DetectedSpan,
    DetectionWindow,
    MotionInterval,
    StaticChallengeFocus,
    StaticChallengeFocusQuery,
    VideoMetadata,
    WindowDetection,
    _build_static_challenge_span,
    _challenge_negative_coarse_verdict,
    _is_negative_whole_body_verdict,
    _select_motion_witness,
    _static_challenge_focus_query,
    static_challenge_focus_from_pose_payload,
)


def _coarse_detection(
    *,
    movement_present: bool = False,
    confidence: float = 0.95,
) -> WindowDetection:
    return WindowDetection(
        window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.836),
        movement_present=movement_present,
        contains_movement_start=False,
        contains_movement_end=False,
        movement_start_seconds=None,
        movement_end_seconds=None,
        confidence=confidence,
        summary="",
        reason="",
        camera_variation=0.0,
        frame_paths=[],
    )


def _execution(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "complete": True,
        "single_execution": True,
        "normal_speed": True,
        "fixed_camera": True,
        "single_person": True,
        "fully_in_frame": True,
        "partial_movement": False,
        "wrong_exercise_or_unrelated_movement": False,
        "start_posture_visible": True,
        "full_action_path_visible": True,
        "end_posture_visible": True,
        "target_exercise_match": 0.9,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _refined_detection(
    *,
    movement_present: bool = True,
    confidence: float = 0.9,
    executions: tuple[SimpleNamespace, ...] | None = None,
    contains_movement_start: bool = True,
    contains_movement_end: bool = True,
) -> WindowDetection:
    return WindowDetection(
        window=DetectionWindow(index=10_000, start_seconds=0.0, end_seconds=2.836),
        movement_present=movement_present,
        contains_movement_start=contains_movement_start,
        contains_movement_end=contains_movement_end,
        movement_start_seconds=None,
        movement_end_seconds=None,
        confidence=confidence,
        summary="",
        reason="",
        camera_variation=0.0,
        frame_paths=[],
        executions=(_execution(),) if executions is None else executions,
    )


def _challenge(
    *,
    detections: list[WindowDetection],
    intervals: list[MotionInterval],
    refine_window,
    duration_seconds: float = 2.836,
    min_segment_seconds: float = 2.0,
    max_segment_seconds: float = 20.0,
    confidence_threshold: float = 0.45,
    focus_provider=None,
):
    return _challenge_negative_coarse_verdict(
        detections=detections,
        motion_intervals=intervals,
        duration_seconds=duration_seconds,
        min_segment_seconds=min_segment_seconds,
        max_segment_seconds=max_segment_seconds,
        confidence_threshold=confidence_threshold,
        refine_window=refine_window,
        focus_provider=focus_provider,
    )


def test_all_negative_complete_verdicts_open_challenge() -> None:
    assert _is_negative_whole_body_verdict([_coarse_detection()])
    assert not _is_negative_whole_body_verdict([_coarse_detection(movement_present=True)])
    assert not _is_negative_whole_body_verdict([_coarse_detection(confidence=0.0)])
    assert not _is_negative_whole_body_verdict([])


def test_full_duration_fallback_is_not_an_independent_witness() -> None:
    assert (
        _select_motion_witness(
            [MotionInterval(0.0, 2.836, 1.0)],
            duration_seconds=2.836,
        )
        is None
    )
    localized = MotionInterval(1.2, 2.3, 4.0)
    assert (
        _select_motion_witness(
            [MotionInterval(0.0, 2.836, 1.0), localized],
            duration_seconds=2.836,
        )
        is localized
    )


def test_short_witness_expands_to_minimum_segment_duration() -> None:
    span = _build_static_challenge_span(
        MotionInterval(1.2, 2.3, 4.0),
        duration_seconds=2.836,
        min_segment_seconds=2.0,
        max_segment_seconds=20.0,
        confidence_threshold=0.45,
    )
    assert span.end_seconds - span.start_seconds >= 2.0
    assert span.start_seconds >= 0.0
    assert span.end_seconds <= 2.836


def test_complete_finer_positive_promotes_span() -> None:
    calls: list[DetectedSpan] = []

    def refine_window(coarse_span: DetectedSpan, focus):
        calls.append(coarse_span)
        return (
            DetectedSpan(
                start_seconds=1.0,
                end_seconds=2.5,
                confidence=0.8,
                average_camera_variation=0.0,
                contributing_windows=[10_000],
            ),
            [_refined_detection()],
        )

    span, detections, info = _challenge(
        detections=[_coarse_detection()],
        intervals=[MotionInterval(1.15, 2.25, 4.0)],
        refine_window=refine_window,
    )

    assert span is not None
    assert span.start_seconds == 1.0
    assert info["modelCalls"] == 1
    assert info["reason"] == "finer_evidence_complete_positive"
    assert len(calls) == 1
    assert len(detections) == 1


def test_static_negative_stays_negative_without_witness() -> None:
    def refine_window(coarse_span: DetectedSpan, focus):
        raise AssertionError("refinement must not run without a witness")

    span, detections, info = _challenge(
        detections=[_coarse_detection()],
        intervals=[],
        refine_window=refine_window,
    )

    assert span is None
    assert detections == []
    assert info["modelCalls"] == 0
    assert info["reason"] == "no_independent_motion_witness"


def test_full_duration_witness_keeps_static_negative() -> None:
    def refine_window(coarse_span: DetectedSpan, focus):
        raise AssertionError("full-duration fallback must not run refinement")

    span, _, info = _challenge(
        detections=[_coarse_detection()],
        intervals=[MotionInterval(0.0, 2.836, 1.0)],
        refine_window=refine_window,
    )

    assert span is None
    assert info["modelCalls"] == 0


def test_unknown_coarse_verdict_never_challenges() -> None:
    def refine_window(coarse_span: DetectedSpan, focus):
        raise AssertionError("unknown evidence must not run refinement")

    span, _, info = _challenge(
        detections=[_coarse_detection(confidence=0.0)],
        intervals=[MotionInterval(1.2, 2.3, 4.0)],
        refine_window=refine_window,
    )

    assert span is None
    assert info["modelCalls"] == 0
    assert info["reason"] == "coarse_verdict_not_negative_or_unknown"


def test_positive_coarse_verdict_is_not_challenged() -> None:
    def refine_window(coarse_span: DetectedSpan, focus):
        raise AssertionError("positive coarse verdict must use the normal path")

    span, _, info = _challenge(
        detections=[_coarse_detection(movement_present=True)],
        intervals=[MotionInterval(1.2, 2.3, 4.0)],
        refine_window=refine_window,
    )

    assert span is None
    assert info["applied"] is False


def test_incomplete_finer_positive_is_rejected() -> None:
    def refine_window(coarse_span: DetectedSpan, focus):
        return (
            DetectedSpan(
                start_seconds=1.0,
                end_seconds=2.5,
                confidence=0.8,
                average_camera_variation=0.0,
                contributing_windows=[10_000],
            ),
            [_refined_detection(executions=(_execution(complete=False),))],
        )

    span, _, info = _challenge(
        detections=[_coarse_detection()],
        intervals=[MotionInterval(1.2, 2.3, 4.0)],
        refine_window=refine_window,
    )

    assert span is None
    assert info["reason"] == "finer_evidence_incomplete_or_unknown"


def test_negative_finer_result_does_not_promote_coarse_span() -> None:
    def refine_window(coarse_span: DetectedSpan, focus):
        return coarse_span, [_refined_detection(movement_present=False, executions=())]

    span, _, info = _challenge(
        detections=[_coarse_detection()],
        intervals=[MotionInterval(1.2, 2.3, 4.0)],
        refine_window=refine_window,
    )

    assert span is None
    assert info["reason"] == "finer_evidence_negative"


def test_region_focus_provider_runs_only_for_open_challenge() -> None:
    queried: list[DetectedSpan] = []

    def focus_provider(coarse_span: DetectedSpan):
        queried.append(coarse_span)
        return None

    def refine_window(coarse_span: DetectedSpan, focus):
        return coarse_span, []

    _, _, positive_info = _challenge(
        detections=[_coarse_detection(movement_present=True)],
        intervals=[MotionInterval(1.2, 2.3, 4.0)],
        refine_window=refine_window,
        focus_provider=focus_provider,
    )
    assert positive_info["applied"] is False
    assert queried == []

    _, _, no_witness_info = _challenge(
        detections=[_coarse_detection()],
        intervals=[MotionInterval(0.0, 2.836, 1.0)],
        refine_window=refine_window,
        focus_provider=focus_provider,
    )
    assert no_witness_info["modelCalls"] == 0
    assert queried == []

    _, _, info = _challenge(
        detections=[_coarse_detection()],
        intervals=[MotionInterval(1.2, 2.3, 4.0)],
        refine_window=refine_window,
        focus_provider=focus_provider,
    )
    assert len(queried) == 1
    assert info["modelCalls"] == 1
    assert info["regionFocus"] == {"applied": False}


def test_region_focus_is_passed_to_the_single_challenge() -> None:
    focus = StaticChallengeFocus(
        crop_box=(10, 10, 100, 100),
        frame_indices=(1, 2, 3, 4, 5, 6, 7, 8),
        timestamps=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8),
        provenance={"source": "test"},
    )
    received: list[StaticChallengeFocus | None] = []

    def focus_provider(coarse_span: DetectedSpan):
        return focus

    def refine_window(coarse_span: DetectedSpan, applied_focus):
        received.append(applied_focus)
        return (
            DetectedSpan(
                start_seconds=coarse_span.start_seconds,
                end_seconds=coarse_span.end_seconds,
                confidence=0.9,
                average_camera_variation=0.0,
                contributing_windows=[0],
            ),
            [_refined_detection()],
        )

    span, _, info = _challenge(
        detections=[_coarse_detection()],
        intervals=[MotionInterval(1.2, 2.3, 4.0)],
        refine_window=refine_window,
        focus_provider=focus_provider,
    )

    assert span is not None
    assert received == [focus]
    assert info["modelCalls"] == 1
    assert info["regionFocus"]["applied"] is True
    assert info["regionFocus"]["cropBox"] == [10, 10, 100, 100]
    assert info["regionFocus"]["frameIndices"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert info["regionFocus"]["provenance"] == {"source": "test"}
    assert len(info["regionFocus"]["provenanceSha256"]) == 64


def test_focus_query_samples_eight_code_owned_frames_across_window() -> None:
    span = _build_static_challenge_span(
        MotionInterval(1.2, 2.3, 4.0),
        duration_seconds=10.0,
        min_segment_seconds=2.0,
        max_segment_seconds=20.0,
        confidence_threshold=0.45,
    )
    query = _static_challenge_focus_query(
        video_path=Path("clip.mp4"),
        coarse_span=span,
        metadata=VideoMetadata(
            duration_seconds=10.0,
            fps=24.0,
            frame_count=240,
            width=640,
            height=360,
        ),
        focus_regions=("feet", "knees"),
    )

    assert len(query.frame_indices) == 8
    assert len(query.timestamps) == 8
    assert query.frame_indices == tuple(sorted(query.frame_indices))
    assert all(0 <= index < 240 for index in query.frame_indices)
    assert query.timestamps[0] >= span.start_seconds - 1e-9
    assert query.timestamps[-1] <= span.end_seconds + 1e-9
    assert query.focus_regions == ("feet", "knees")


def _pose_payload(
    *,
    person_count: int = 1,
    coverage: float = 0.9,
    joint_confidence: float = 0.9,
) -> dict[str, object]:
    samples = []
    for time_seconds in (0.0, 0.35, 0.7):
        samples.append(
            {
                "timeSeconds": time_seconds,
                "bbox": [0.3, 0.2, 0.7, 0.8],
                "keypoints": {
                    "left_ankle": [0.45, 0.85, joint_confidence],
                    "right_ankle": [0.55, 0.85, joint_confidence],
                    "left_knee": [0.45, 0.5, joint_confidence],
                    "right_knee": [0.55, 0.5, joint_confidence],
                },
            }
        )
    return {
        "dominantPoseSamples": samples,
        "maxSignificantPersonCount": person_count,
        "keypointCoverage": coverage,
        "imageWidth": 640,
        "imageHeight": 360,
    }


def _focus_query() -> StaticChallengeFocusQuery:
    return StaticChallengeFocusQuery(
        video_path=Path("clip.mp4"),
        start_seconds=0.0,
        end_seconds=0.7,
        frame_indices=(0, 3, 7, 10, 13, 17, 20, 23),
        timestamps=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7),
        image_width=640,
        image_height=360,
        source_fps=24.0,
        focus_regions=("feet", "knees"),
    )


def test_focus_crop_unions_observed_regions_with_body_padding() -> None:
    focus = static_challenge_focus_from_pose_payload(_pose_payload(), query=_focus_query())

    assert focus is not None
    left, top, right, bottom = focus.crop_box
    assert left <= int(0.45 * 640) and right >= int(0.55 * 640)
    assert top <= int(0.5 * 360) and bottom >= int(0.85 * 360)
    assert focus.frame_indices == _focus_query().frame_indices
    assert focus.timestamps == _focus_query().timestamps
    assert focus.provenance["focusRegions"] == ["feet", "knees"]


def test_focus_crop_rejects_invalid_person_coverage_or_hidden_regions() -> None:
    assert static_challenge_focus_from_pose_payload(
        _pose_payload(person_count=2),
        query=_focus_query(),
    ) is None
    assert static_challenge_focus_from_pose_payload(
        _pose_payload(coverage=0.2),
        query=_focus_query(),
    ) is None
    assert static_challenge_focus_from_pose_payload(
        _pose_payload(joint_confidence=0.5),
        query=_focus_query(),
    ) is None
    partial = _pose_payload()
    for sample in partial['dominantPoseSamples']:
        sample['keypoints'].pop('left_ankle')
    assert static_challenge_focus_from_pose_payload(partial, query=_focus_query()) is None


def test_focus_provider_uses_exclusive_exact_source_observation(tmp_path, monkeypatch):
    from dataclasses import replace
    from exercise_motion_pkg import bake_and_rank as bake
    query = replace(_focus_query(), video_path=tmp_path / 'source.mp4')
    query.video_path.write_bytes(b'exact source')
    calls = []
    class Owner:
        def caption_images(self, **kwargs):
            raise AssertionError('Crop localization must not query the caption model.')
        def run_without_llama_overlap(self, operation):
            calls.append('exclusive')
            return operation()
    def observe(**kwargs):
        assert calls == ['exclusive']
        assert kwargs['video_path'] == query.video_path
        assert kwargs['settings'].sample_frame_indices == query.frame_indices
        calls.append('yolo')
        return SimpleNamespace(payload=_pose_payload())
    monkeypatch.setattr(bake, 'run_yolo_pose_prefilter', observe)
    provider = bake._static_challenge_crop_provider(caption_images=Owner().caption_images)
    focus = provider(query)
    assert focus is not None and calls == ['exclusive', 'yolo']
    assert len(focus.provenance['sourceVideoSha256']) == 64
    assert bake._static_challenge_crop_provider(caption_images=None)(query) is None
