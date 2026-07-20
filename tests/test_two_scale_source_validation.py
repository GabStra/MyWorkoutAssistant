from __future__ import annotations

import json
from pathlib import Path

from exercise_motion_pkg import bake_and_rank


def make_review_item(tmp_path: Path, exercise_name: str = "Dumbbell Shrug") -> bake_and_rank.ReviewItem:
    placeholder = tmp_path / "placeholder"
    return bake_and_rank.ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name=exercise_name,
        candidate_title=exercise_name,
        candidate_workspace=tmp_path,
        preview_html_path=placeholder,
        skeleton_path=placeholder,
        review_video_path=placeholder,
        duration_sec=4.0,
        loop_start_seconds=0.0,
        loop_end_seconds=4.0,
        candidate={},
    )


def test_two_scale_peak_selector_captures_single_frame_spike_deterministically() -> None:
    scores = [0.0] * 300
    scores[20] = 10.0
    scores[137] = 100.0
    scores[260] = 8.0

    first = bake_and_rank.select_two_scale_motion_peak_indices(scores, 60.0)
    second = bake_and_rank.select_two_scale_motion_peak_indices(scores, 60.0)

    assert 137 in first
    assert first == second


def test_two_scale_source_gate_rejects_when_any_uniform_sheet_has_contamination(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uniform_sheets = [tmp_path / "uniform-1.jpg", tmp_path / "uniform-2.jpg"]
    motion_sheets = [tmp_path / "motion-1.jpg", tmp_path / "motion-2.jpg"]
    for path in [*uniform_sheets, *motion_sheets]:
        path.write_bytes(b"image")
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: motion_sheets,
    )
    responses = iter(
        [
            {"verdict": "match", "observedAction": "shrug", "evidence": "visible"},
            {"unrelatedActionVisible": False, "unrelatedTileNumbers": [], "evidence": "clean"},
            {"unrelatedActionVisible": True, "unrelatedTileNumbers": [9], "evidence": "gesture"},
            {"targetExerciseActionVisible": True, "namedEquipmentEngagedStatus": "engaged", "evidence": "visible"},
            {"targetExerciseActionVisible": False, "namedEquipmentEngagedStatus": "absent", "evidence": "absent"},
            {
                "startStateVisible": True,
                "actionPhaseVisible": True,
                "turningPointVisible": True,
                "returnOrFinishVisible": True,
                "complete": True,
                "evidence": "complete",
            },
        ]
    )

    def caption_images(**_kwargs: object) -> str:
        return json.dumps(next(responses))

    result = bake_and_rank.validate_two_scale_source_with_caption_images(
        make_review_item(tmp_path),
        uniform_sheet_paths=uniform_sheets,
        output_dir=tmp_path / "validation",
        caption_images=caption_images,
    )

    assert result["passed"] is False
    assert "two_scale_source_contamination_detected" in result["rejectionReasons"]


def test_two_scale_source_gate_accepts_when_all_independent_gates_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uniform_sheets = [tmp_path / "uniform.jpg"]
    motion_sheets = [tmp_path / "motion.jpg"]
    for path in [*uniform_sheets, *motion_sheets]:
        path.write_bytes(b"image")
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: motion_sheets,
    )
    responses = iter(
        [
            {"verdict": "match", "observedAction": "press", "evidence": "visible"},
            {"unrelatedActionVisible": False, "unrelatedTileNumbers": [], "evidence": "clean"},
            {"targetExerciseActionVisible": True, "namedEquipmentEngagedStatus": "engaged", "evidence": "visible"},
            {
                "startStateVisible": True,
                "actionPhaseVisible": True,
                "turningPointVisible": True,
                "returnOrFinishVisible": True,
                "complete": True,
                "evidence": "complete",
            },
        ]
    )

    result = bake_and_rank.validate_two_scale_source_with_caption_images(
        make_review_item(tmp_path, "Dumbbell Bench Press"),
        uniform_sheet_paths=uniform_sheets,
        output_dir=tmp_path / "validation",
        caption_images=lambda **_kwargs: json.dumps(next(responses)),
    )

    assert result["passed"] is True
    assert result["rejectionReasons"] == []
