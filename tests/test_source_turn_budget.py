import json
import threading
import time
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import wave_pipeline as wave
from exercise_motion_pkg.wave_pipeline import _SourceTurnBudget


class FakeClock:
    def __init__(self, now=0.0):
        self.now = float(now)


def test_source_turn_deadline_is_shared_across_windows_and_resume():
    clock = FakeClock()
    request = SimpleNamespace(
        source_review_timeout_seconds=10.0,
        exercise_timeout_seconds=0.0,
        max_source_window_attempts=0,
    )
    budget = _SourceTurnBudget(request, started_at=clock.now)
    model_elapsed = []

    def fake_caption():
        remaining = budget.deadline - clock.now
        request_timeout = min(request.source_review_timeout_seconds, remaining)
        duration = min(4.0, request_timeout)
        clock.now += duration
        model_elapsed.append(duration)

    for _window in range(5):
        if budget.stop_reason(clock.now):
            break
        budget.begin_attempt()
        fake_caption()

    assert len(model_elapsed) == 3
    assert sum(model_elapsed) == 10.0
    assert budget.stop_reason(clock.now) == "source_turn_deadline"

    resumed = _SourceTurnBudget(request, budget.resume_fields(clock.now), started_at=clock.now)
    assert resumed.stop_reason(clock.now) == "source_turn_deadline"
    assert resumed.attempts_used == 3


def test_source_turn_attempt_limit_is_shared_across_windows_and_larger_budget_preserves_usage():
    request = SimpleNamespace(
        source_review_timeout_seconds=30.0,
        exercise_timeout_seconds=0.0,
        max_source_window_attempts=2,
    )
    clock = FakeClock()
    budget = _SourceTurnBudget(request, started_at=clock.now)
    for _window in range(2):
        assert budget.stop_reason(clock.now) is None
        budget.begin_attempt()
        clock.now += 1.0
    assert budget.stop_reason(clock.now) == "source_turn_attempt_budget"

    persisted = budget.resume_fields(clock.now)
    request.max_source_window_attempts = 4
    extended = _SourceTurnBudget(request, persisted, started_at=clock.now)
    assert extended.attempts_used == 2
    assert extended.stop_reason(clock.now) is None
    assert extended.budget_extended_by_configuration
    extended.begin_attempt()
    assert extended.attempts_used == 3


def test_staged_source_turn_caps_inflight_caption_and_preserves_unresolved_candidate(tmp_path, monkeypatch):
    deadlines = threading.local()
    caption_calls = []

    class FakeSession:
        def __init__(self, _request):
            pass

        def set_candidate_deadline(self, deadline):
            deadlines.value = deadline

        def caption_images(self, **kwargs):
            deadline = getattr(deadlines, "value", None)
            assert deadline is not None
            remaining = max(0.0, deadline - time.perf_counter())
            request_timeout = min(float(kwargs.get("request_timeout_seconds") or 240.0), remaining)
            caption_calls.append(request_timeout)
            time.sleep(request_timeout + 0.01)
            raise TimeoutError("caption exceeded the shared exercise source-turn deadline")

        def run_without_llama_overlap(self, operation):
            return operation()

        def close(self, **_kwargs):
            pass

    candidates = [
        bake.RankedCandidate(
            exercise_index=0,
            candidate_rank=index,
            exercise_id="carry",
            exercise_name="Carry",
            exercise_slug="carry",
            candidate={"videoId": f"video-{index}"},
        )
        for index in range(3)
    ]
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=tmp_path / "carry",
        body_model_root=None,
        fallback_candidates=0,
        source_review_timeout_seconds=0.05,
        max_source_window_attempts=0,
    )
    item = wave.StagedWaveItem("carry", "Carry", request)
    monkeypatch.setattr(wave, "LazyLlamaCppVisionSession", FakeSession)
    monkeypatch.setattr(wave, "_wave_candidates", lambda _request: candidates)
    monkeypatch.setattr(wave, "build_exercise_motion_contract_resolver", lambda **_kwargs: None)
    monkeypatch.setattr(wave, "first_attempt_readiness_assessment",
                        lambda *_args, **_kwargs: {"eligible": True, "portfolioSize": 1})
    monkeypatch.setattr(wave, "evaluate_source_candidate_gate",
                        lambda *_args, **_kwargs: {"passed": True})

    def prepare(_candidate, *, source_cut_caption_images, **_kwargs):
        source_cut_caption_images(frame_paths=[], prompt="source review", request_timeout_seconds=240.0)

    monkeypatch.setattr(wave, "prepare_candidate_input_video", prepare)
    monkeypatch.setattr(wave, "generate_candidate_motion",
                        lambda *_args, **_kwargs: pytest.fail("inconclusive source reached reconstruction"))
    monkeypatch.setattr(wave, "run_bake_and_rank_pipeline",
                        lambda *_args, **_kwargs: {"selected": None})

    report = wave.run_staged_bake_wave([item], workspace=tmp_path / "wave", wave_id="bounded-source")

    source = report["items"][0]["source"]
    assert len(caption_calls) == 1
    assert caption_calls[0] <= request.source_review_timeout_seconds
    assert source["status"] == "needs_source_review"
    assert source["failureReason"] == "source_review_incomplete"
    assert source["turn"]["stopReason"] == "source_turn_deadline"
    attempt = source["attempts"][0]
    assert attempt["status"] == "needs_source_review"
    resume = json.loads((request.workspace / "source_turn_resume.json").read_text())
    assert resume["nextCandidateKey"] == wave._candidate_key(candidates[0])
    assert resume["attemptedCandidateKeys"] == []
    ledger = json.loads((request.workspace / "source_turn_budget.json").read_text())
    assert ledger["sourceTurnAttemptsUsed"] == 1

    resumed_report = wave.run_staged_bake_wave(
        [item], workspace=tmp_path / "wave-resumed", wave_id="bounded-source-resumed"
    )
    assert len(caption_calls) == 1
    resumed_source = resumed_report["items"][0]["source"]
    assert resumed_source["status"] == "needs_source_review"
    assert resumed_source["turn"]["stopReason"] == "source_turn_deadline"


def test_source_turn_budget_readiness_binds_context_not_candidate_pool_or_run_id(tmp_path):
    from exercise_motion_pkg.wave_pipeline import source_turn_budget_readiness

    workspace = tmp_path / "carry"
    workspace.mkdir()
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=workspace,
        body_model_root=None,
        fallback_candidates=0,
        source_review_timeout_seconds=10.0,
        max_source_window_attempts=2,
        authoritative_exercise_motion_context={"movement": "walk with load"},
    )
    identity = wave._source_turn_exercise_identity(
        "carry", "Carry", request.authoritative_exercise_motion_context
    )
    ledger = _SourceTurnBudget(request, exercise_identity=identity)
    ledger.begin_attempt()
    (workspace / "source_turn_budget.json").write_text(
        json.dumps(ledger.resume_fields()), encoding="utf-8"
    )

    same_context = source_turn_budget_readiness(
        workspace, "carry", "Carry", {"movement": "walk with load"}, 10.0, 0.0, 2
    )
    changed_context = source_turn_budget_readiness(
        workspace, "carry", "Carry", {"movement": "walk without load"}, 10.0, 0.0, 2
    )
    assert same_context["ready"] is True
    assert same_context["attemptsUsed"] == 1
    assert changed_context["ready"] is True
    assert changed_context["attemptsUsed"] == 0
    assert changed_context["resetRequired"] is True


def test_list_cli_marks_matching_exhausted_source_ledger_before_discovery(tmp_path, monkeypatch):
    from exercise_motion_pkg.cli import main
    from exercise_motion_pkg.source_turn_budget import (
        SOURCE_TURN_BUDGET_POLICY_VERSION,
        _source_turn_exercise_identity,
    )

    context = {
        "exerciseDefinition": {
            "definingAction": "Walk while holding two weights.",
            "completionMode": "continuous",
            "source": "manual",
        }
    }
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"exerciseDefinitions": [{
        "id": "carry",
        "name": "Farmer Carry",
        "motionContext": context,
    }]}), encoding="utf-8")
    workspace_root = tmp_path / "workspace"
    ledger_workspace = workspace_root / "farmer-carry" / "bake"
    ledger_workspace.mkdir(parents=True)
    identity = _source_turn_exercise_identity("carry", "Farmer Carry", context)
    (ledger_workspace / "source_turn_budget.json").write_text(json.dumps({
        "sourceTurnBudgetPolicyVersion": SOURCE_TURN_BUDGET_POLICY_VERSION,
        "sourceTurnExerciseIdentity": identity,
        "sourceTurnElapsedSeconds": 0.0,
        "sourceTurnAttemptsUsed": 2,
        "sourceTurnTimeoutSeconds": 10.0,
        "sourceTurnAttemptLimit": 2,
    }), encoding="utf-8")

    listed_path = tmp_path / "listed.json"
    monkeypatch.setattr("sys.argv", [
        "exercise-motion", "list-workout-plan-exercises",
        "--workout-plan-json", str(plan),
        "--source-budget-workspace-root", str(workspace_root),
        "--source-review-timeout-seconds", "10",
        "--max-source-window-attempts", "2",
        "--out-json", str(listed_path),
    ])

    main()

    result = json.loads(listed_path.read_text(encoding="utf-8"))
    item = result["exercises"][0]["sourceReviewBudgetReadiness"]
    assert item["status"] == "needs_source_review"
    assert item["ready"] is False
    assert item["stopReason"] == "source_turn_attempt_budget"
    assert item["attemptsUsed"] == 2
