import json
import subprocess
import sys

from exercise_motion_pkg.source_turn_budget import (
    SOURCE_TURN_BUDGET_POLICY_VERSION,
    _source_turn_exercise_identity,
    load_source_turn_cursor,
    write_source_turn_cursor_from_wave_state,
)


def test_cursor_writer_and_cli_preserve_exact_turn_and_advance_candidate(tmp_path):
    context = {"requiredActions": ["squat"], "equipment": ["dumbbell"]}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"exercises": [{"id": "ex-1", "name": "Squat", "motionContext": context}]}))
    workspace = tmp_path / "bake"
    workspace.mkdir()
    cursor_path = workspace / "source_turn_resume.json"
    budget_identity = _source_turn_exercise_identity("ex-1", "Squat", context)
    (workspace / "source_turn_budget.json").write_text(json.dumps({
        "sourceTurnExerciseIdentity": budget_identity,
        "sourceTurnScopeIdentity": "review-7",
        "sourceTurnBudgetPolicyVersion": SOURCE_TURN_BUDGET_POLICY_VERSION,
        "sourceTurnAttemptsUsed": 1,
    }))
    receipt = {
        "exerciseId": "ex-1",
        "exerciseName": "Squat",
        "source": {
            "sourceSelectionPolicyVersion": 4,
            "priorAttemptedCandidateKeys": [],
            "priorAttemptedVideoIds": [],
            "attempts": [{"candidateKey": "window-A", "videoId": "video-A"}],
            "nextCandidateKey": "window-B",
        },
    }
    receipt_path = workspace / "wave-state.json"
    receipt_path.write_text(json.dumps(receipt))
    result = subprocess.run(
        [
            sys.executable, "-m", "exercise_motion_pkg.source_turn_cursor_cli",
            "--wave-state-json", str(receipt_path),
            "--exercise-plan-json", str(plan_path),
            "--cursor-path", str(cursor_path),
            "--source-review-turn-id", "review-7",
            "--transition", "next_source_candidate",
        ],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    cursor = load_source_turn_cursor(
        cursor_path,
        source_selection_policy_version=4,
        exercise_id="ex-1",
        exercise_name="Squat",
        authoritative_exercise_motion_context=context,
        source_review_turn_id="review-7",
    )
    assert cursor is not None
    assert cursor["nextCandidateKey"] == "window-B"
    assert cursor["attemptedCandidateKeys"] == ["window-A"]
    assert cursor["attemptedVideoIds"] == ["video-A"]
    assert cursor["sourceTurnAttemptsUsed"] == 1
    assert load_source_turn_cursor(
        cursor_path,
        source_selection_policy_version=4,
        exercise_id="ex-1",
        exercise_name="Squat",
        authoritative_exercise_motion_context=context,
        source_review_turn_id="different-turn",
    ) is None
    assert load_source_turn_cursor(
        cursor_path,
        source_selection_policy_version=5,
        exercise_id="ex-1",
        exercise_name="Squat",
        authoritative_exercise_motion_context=context,
        source_review_turn_id="review-7",
    ) is None


def test_cursor_writer_rejects_missing_next_candidate(tmp_path):
    context = {"requiredActions": ["squat"]}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"exercises": [{"id": "ex-1", "name": "Squat", "motionContext": context}]}))
    receipt = {
        "exerciseId": "ex-1",
        "exerciseName": "Squat",
        "source": {"sourceSelectionPolicyVersion": 4, "attempts": [], "nextCandidateKey": ""},
    }
    import pytest

    with pytest.raises(ValueError, match="no next candidate key"):
        write_source_turn_cursor_from_wave_state(
            tmp_path / "cursor.json", wave_state=receipt, exercise_plan_path=plan_path,
            source_review_turn_id="review-7", transition="next_source_candidate",
        )
