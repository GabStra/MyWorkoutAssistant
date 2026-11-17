from exercise_motion_pkg.bake_and_rank import (
    _baked_source_frame_bounds_match,
    _eligible_loop_has_exact_frame_bounds,
)


def _baked_range(source_start: int, frame_count: int) -> dict:
    source_end = source_start + frame_count - 1
    return {
        "frames": [{"sourceFrameIndex": source_start + index} for index in range(frame_count)],
        "loop": {
            "sourceStartFrame": source_start,
            "sourceEndFrame": source_end,
        },
    }


def test_detected_cycle_uses_exact_frame_bounds_and_rejects_browser_truncation():
    selected_loop = {
        "type": "detected_cycle",
        "startFrame": 0,
        "endFrame": 88,
    }
    assert _eligible_loop_has_exact_frame_bounds(selected_loop)
    assert _eligible_loop_has_exact_frame_bounds({
        "type": "exact_source_movement_instance",
        "startFrame": 0,
        "endFrame": 88,
    })
    assert not _eligible_loop_has_exact_frame_bounds({
        "type": "detected_cycle",
        "startFrame": 0,
        "endFrame": None,
    })

    assert _baked_source_frame_bounds_match(
        _baked_range(102, 89),
        local_frame_bounds=(0, 88),
        expected_parent_bounds=(102, 190),
    )
    assert not _baked_source_frame_bounds_match(
        _baked_range(102, 87),
        local_frame_bounds=(0, 88),
        expected_parent_bounds=(102, 190),
    )
