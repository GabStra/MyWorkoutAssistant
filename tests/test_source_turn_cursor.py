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


def test_cursor_keeps_unresolved_attempt_resumable_without_resetting_budget(tmp_path):
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'exercises': [{'id': 'source', 'name': 'Source', 'motionContext': {}}]}))
    (tmp_path / 'source_turn_budget.json').write_text(json.dumps({
        'sourceTurnExerciseIdentity': _source_turn_exercise_identity('source', 'Source', {}),
        'sourceTurnScopeIdentity': 'same-turn', 'sourceTurnBudgetPolicyVersion': SOURCE_TURN_BUDGET_POLICY_VERSION,
        'sourceTurnAttemptsUsed': 2, 'sourceTurnElapsedSeconds': 75.,
    }))
    receipt = {'exerciseId': 'source', 'exerciseName': 'Source', 'source': {
        'sourceSelectionPolicyVersion': 69,
        'attempts': [{'candidateKey': 'pending', 'videoId': 'pending-video', 'status': 'needs_source_review'},
                     {'candidateKey': 'rejected', 'videoId': 'rejected-video', 'status': 'rejected_source_validation'}],
        'turn': {'attemptsUsed': 2, 'elapsedSeconds': 75., 'excludedWaitSeconds': 3.}}}
    cursor = write_source_turn_cursor_from_wave_state(tmp_path / 'source_turn_resume.json',
        wave_state=receipt, exercise_plan_path=plan, source_review_turn_id='same-turn',
        transition='bounded_source_discovery')
    assert cursor['attemptedCandidateKeys'] == ['rejected']
    assert cursor['attemptedVideoIds'] == ['rejected-video']
    assert cursor['sourceTurnAttemptsUsed'] == 2
    assert cursor['sourceTurnElapsedSeconds'] == 75.


def test_bounded_discovery_excludes_support_evidence_windows_but_keeps_video_eligible(tmp_path):
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'exercises': [{'id': 'source', 'name': 'Source', 'motionContext': {}}]}))
    receipt = {'exerciseId': 'source', 'exerciseName': 'Source', 'source': {
        'sourceSelectionPolicyVersion': 69,
        'attempts': [
            {'candidateKey': 'source:window-1', 'videoId': 'same-video',
             'status': 'needs_source_review', 'failureOwner': 'source_evidence'},
            {'candidateKey': 'source:window-2', 'videoId': 'same-video',
             'status': 'needs_source_review', 'failureOwner': 'source_evidence'},
            {'candidateKey': 'source:window-3', 'videoId': 'same-video',
             'status': 'needs_source_review', 'failureOwner': 'source_evidence'},
            {'candidateKey': 'source:window-4', 'videoId': 'same-video',
             'status': 'rejected_source_validation'},
            {'candidateKey': 'source:window-5', 'videoId': 'same-video',
             'status': 'needs_source_review', 'failureOwner': 'review'},
        ],
    }}
    cursor = write_source_turn_cursor_from_wave_state(
        tmp_path / 'source_turn_resume.json', wave_state=receipt,
        exercise_plan_path=plan, source_review_turn_id='turn-1',
        transition='bounded_source_discovery',
    )
    assert cursor['attemptedCandidateKeys'] == [
        'source:window-1', 'source:window-2', 'source:window-3', 'source:window-4',
    ]
    assert cursor['attemptedVideoIds'] == ['same-video']
