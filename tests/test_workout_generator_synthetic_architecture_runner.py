import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workout_generator_architecture_e2e as retained
import workout_generator_synthetic_architecture_e2e as synthetic_runner


def test_resume_rejects_a_live_saved_cli_process(monkeypatch, tmp_path):
    monkeypatch.setattr(synthetic_runner, "process_is_alive", lambda _pid: True)

    with pytest.raises(RuntimeError, match="still running"):
        synthetic_runner.ensure_saved_process_stopped({"status": "running", "childPID": 123}, tmp_path)


def test_current_cached_review_failure_without_task_fails_fast_but_stale_version_can_resume():
    audit = {
        "auditVersion": 40,
        "review": {"version": 63, "pending": False},
        "errors": [{"code": "review_execution_failed", "message": "cached validation failure"}],
    }
    current = {"repairTask": None, "conflictDiagnosisTask": None, "candidateMenuExpansionTask": None}
    assert "cached under the current review versions" in synthetic_runner.cached_review_failure_without_route(
        audit, current, current_audit_version=40, current_review_version=63)
    assert synthetic_runner.cached_review_failure_without_route(
        audit, {**current, "candidateMenuExpansionTask": {"sourceBaseDraftId": "REVISION_1"}}, 40, 63) is None
    assert synthetic_runner.cached_review_failure_without_route(audit, current, 41, 64) is None


def test_provider_balance_failure_is_reported_without_generic_input_timeout():
    assert synthetic_runner.provider_failure_reason("Error: Error code: 402 - {'error': {'message': 'Insufficient Balance'}}") == (
        'Model provider returned HTTP 402 for insufficient balance; saved planning state is resumable.')
    assert synthetic_runner.provider_failure_reason('No provider error') is None


def test_usage_metrics_scope_pending_requests_to_the_latest_attempt(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    events = [
        {"event": "api_request_started", "requestId": "previous", "requestStartedAtUTC": "2026-10-19T19:00:00+00:00"},
        {"event": "api_request_started", "requestId": "current", "requestStartedAtUTC": "2026-10-19T20:00:00+00:00"},
    ]
    (log_dir / "conversation.log").write_text(
        "\n".join("[api_metric] " + json.dumps(event) for event in events), encoding="utf-8")

    metrics = retained.collect_usage(tmp_path, elapsed=12, current_attempt_started_at_utc="2026-10-19T20:00:00+00:00")

    assert metrics["pendingApiRequests"] == 1
    assert metrics["pendingApiRequestDetails"][0]["requestId"] == "current"
    assert metrics["historicalUnterminatedApiRequests"] == 2


def test_stage_wall_time_does_not_sum_parallel_request_latency(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    events = [
        {"event": "api_request", "requestId": "one", "stage": "review",
         "requestStartedAtUTC": "2026-10-19T20:00:00+00:00", "requestFinishedAtUTC": "2026-10-19T20:00:10+00:00"},
        {"event": "api_request", "requestId": "two", "stage": "review",
         "requestStartedAtUTC": "2026-10-19T20:00:08+00:00", "requestFinishedAtUTC": "2026-10-19T20:00:18+00:00"},
    ]
    (log_dir / "conversation.log").write_text(
        "\n".join("[api_metric] " + json.dumps(event) for event in events), encoding="utf-8")

    metrics = retained.collect_usage(tmp_path, elapsed=20)

    assert metrics["apiStageSeconds"]["review"] == 18
    assert metrics["apiStageRequestSeconds"]["review"] == 20


def _repaired_alternative_messages(*, repair_overrides=None, current_requirements_id="REQ_1", competing_proposal=False):
    from workout_generator_pkg.conflict_resolution import render_alternative_preview

    proposal = {
        "proposalId": "ALT_REPAIRED_1", "originalRequirementsId": "REQ_1",
        "changes": [{"path": "/auditTargets/weeklyEffectiveSets/chest/minimum", "from": 15, "to": 14}],
        "workouts": [{"name": "Day 1", "exercises": []}],
        "independentReview": {"passed": True, "preview": "Reviewed repaired candidate"},
        "claim": "Validated for the supplied menu.",
    }
    requirements = {"passed": True, "requirementsId": current_requirements_id,
        "requirements": {"auditTargets": {}}, "sourceReview": {"passed": True},
        "requirementsPreview": "Exact approved requirements preview"}
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "req", "function": {"name": "set_workout_requirements", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "req", "content": json.dumps(requirements)},
        {"role": "assistant", "canonicalRequirementsPreview": current_requirements_id,
         "content": requirements["requirementsPreview"]},
        {"role": "user", "content": "CONFIRM REQUIREMENTS"},
    ]
    if competing_proposal:
        earlier = {**proposal, "proposalId": "ALT_EXISTING_1"}
        messages.extend([
            {"role": "assistant", "tool_calls": [{"id": "diagnosis", "function": {"name": "propose_workout_alternatives", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "diagnosis", "content": json.dumps({"outcome": "alternatives_ready", "proposals": [earlier]})},
            {"role": "assistant", "canonicalAlternativePreview": earlier["proposalId"],
             "content": render_alternative_preview(earlier)},
        ])
    repair_result = {"passed": True, "outcome": "alternatives_ready", "repairStatus": "repaired_and_reviewed",
        "proposal": proposal}
    repair_result.update(repair_overrides or {})
    messages.extend([
        {"role": "assistant", "tool_calls": [{"id": "repair", "function": {"name": "repair_workout_alternative", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "repair", "content": json.dumps(repair_result)},
        {"role": "assistant", "canonicalAlternativePreview": proposal["proposalId"],
         "content": render_alternative_preview(proposal)},
    ])
    return messages, proposal


def test_synthetic_runner_approves_exact_fresh_repaired_alternative_preview():
    from workout_generator_pkg.user_interaction import pending_question

    messages, proposal = _repaired_alternative_messages()

    assert pending_question(messages)["reference"] == proposal["proposalId"]
    assert synthetic_runner.approval_action(messages, 0) == (
        "APPROVE ALTERNATIVE ALT_REPAIRED_1",
        "unique minimum-volume relaxation with exact passing full-review preview")


@pytest.mark.parametrize("overrides,requirements_id", [
    ({"passed": False}, "REQ_1"),
    ({}, "REQ_CHANGED"),
    ({"repairStatus": "repair_failed"}, "REQ_1"),
])
def test_synthetic_runner_rejects_failed_or_stale_repaired_alternative(overrides, requirements_id):
    messages, _ = _repaired_alternative_messages(repair_overrides=overrides,
        current_requirements_id=requirements_id)

    assert synthetic_runner.approval_action(messages, 0) is None


def test_repaired_alternative_keeps_unique_minimum_volume_policy():
    messages, _ = _repaired_alternative_messages(competing_proposal=True)

    assert synthetic_runner.approval_action(messages, 0) is None
