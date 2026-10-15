from exercise_motion_pkg.wave_pipeline import _record_source_attempt_processing_failure


def test_source_attempt_processing_failure_retains_traceback_for_checkpoint_and_log():
    def raise_missing_joint():
        raise KeyError("right_elbow")

    try:
        raise_missing_joint()
    except KeyError as exc:
        attempt = {"videoId": "OZ1D3DEhJuk"}
        attempts = [attempt]
        source_state = {"attempts": []}
        event = _record_source_attempt_processing_failure(
            attempt,
            exc,
            event_prefix="Source attempt: Dumbbell Decline Bench Press",
            attempts=attempts,
            source_state=source_state,
        )

    assert attempt["status"] == "source_processing_failed"
    assert attempt["error"] == "KeyError: 'right_elbow'"
    assert "raise_missing_joint" in attempt["traceback"]
    assert "KeyError: 'right_elbow'" in attempt["traceback"]
    assert "KeyError: 'right_elbow'" in event
    assert "raise_missing_joint" in event
    assert "raise_missing_joint" in source_state["attempts"][0]["traceback"]
