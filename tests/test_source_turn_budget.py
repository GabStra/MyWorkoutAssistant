import json
import threading
import time
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import wave_pipeline as wave
from exercise_motion_pkg.wave_pipeline import _SourceTurnBudget
from exercise_motion_pkg.source_turn_budget import SourceTurnWaitBudgetExpired


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


def test_source_turn_budget_resumes_within_review_turn_but_resets_for_new_explicit_turn():
    request = SimpleNamespace(
        source_review_timeout_seconds=30.0,
        exercise_timeout_seconds=0.0,
        max_source_window_attempts=3,
    )
    first = _SourceTurnBudget(
        request, started_at=0.0, exercise_identity="exercise", turn_identity="library-run-1"
    )
    first.begin_attempt()
    persisted = first.resume_fields(now=4.0)

    resumed = _SourceTurnBudget(
        request, persisted, started_at=10.0,
        exercise_identity="exercise", turn_identity="library-run-1",
    )
    assert resumed.elapsed_before == 4.0
    assert resumed.attempts_used == 1

    new_turn = _SourceTurnBudget(
        request, persisted, started_at=10.0,
        exercise_identity="exercise", turn_identity="library-run-2",
    )
    assert new_turn.elapsed_before == 0.0
    assert new_turn.attempts_used == 0


def test_source_turn_separates_bounded_shared_wait_from_active_review_time():
    clock = FakeClock()
    request = SimpleNamespace(
        source_review_timeout_seconds=10.0,
        exercise_timeout_seconds=0.0,
        max_source_window_attempts=2,
    )
    budget = _SourceTurnBudget(request, started_at=clock.now)
    budget.begin_attempt()

    clock.now += 3.0  # source preparation and active review work
    deadline = budget.exclude_wait(6.0)  # shared VLM admission and model startup
    clock.now += 6.0
    assert deadline == 16.0
    assert budget.elapsed(clock.now) == 3.0

    clock.now += 5.0  # actual model inference remains charged
    persisted = budget.resume_fields(clock.now)
    assert persisted["sourceTurnElapsedSeconds"] == 8.0
    assert persisted["sourceTurnExcludedWaitSeconds"] == 6.0
    assert persisted["sourceTurnActivePlusWaitSeconds"] == 14.0

    resumed = _SourceTurnBudget(request, persisted, started_at=clock.now)
    assert resumed.attempts_used == 1
    assert resumed.stop_reason(clock.now) is None
    resumed.exclude_wait(4.0)
    clock.now += 4.0
    assert resumed.elapsed(clock.now) == 8.0
    with pytest.raises(SourceTurnWaitBudgetExpired):
        resumed.exclude_wait(0.1)
    assert resumed.stop_reason(clock.now) == "source_turn_wait_budget"

    # The fixed active budget still expires after 10 seconds of charged work.
    active_only = _SourceTurnBudget(request, persisted, started_at=clock.now)
    clock.now += 2.0
    assert active_only.stop_reason(clock.now) == "source_turn_deadline"


def test_vision_queue_and_startup_wait_pause_source_budget_but_inference_is_charged(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    class FakeRanker:
        gpu_lock_wait_seconds = 0.0

        def __init__(self, _settings, *, startup_timeout_seconds=None):
            self.startup_timeout_seconds = startup_timeout_seconds
            time.sleep(min(0.03, startup_timeout_seconds) if startup_timeout_seconds is not None else 0.03)
            self.client = self

        def caption_images(self, **_kwargs):
            time.sleep(0.03)
            return "reviewed"

    monkeypatch.setattr(
        bake, "build_llama_cpp_vision_settings",
        lambda _request: SimpleNamespace(llama_cpp_parallel=1, vision_llm_workers=1),
    )
    monkeypatch.setattr(bake, "LlamaCppVisionRanker", FakeRanker)
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json", workspace=tmp_path,
        body_model_root=None, source_review_timeout_seconds=1.0,
    )
    session = bake.LazyLlamaCppVisionSession(request)
    budget = _SourceTurnBudget(request)
    with session._condition:
        session._active_calls = 1

    def release_queued_slot():
        time.sleep(0.03)
        with session._condition:
            session._active_calls = 0
            session._condition.notify_all()

    release_thread = threading.Thread(target=release_queued_slot)
    session.set_candidate_deadline(
        budget.deadline,
        on_wait=budget.exclude_wait,
        wait_remaining=budget.remaining_wait_seconds,
    )
    release_thread.start()
    assert session.caption_images(frame_paths=[], prompt="source review") == "reviewed"
    release_thread.join(timeout=1)
    session.set_candidate_deadline(None)

    assert not release_thread.is_alive()
    assert budget.excluded_wait_added >= 0.04  # queued slot plus ranker startup
    assert 0.02 <= budget.elapsed() < 0.10  # the actual model request remains charged
    assert 0.0 < session._ranker.startup_timeout_seconds <= budget.wait_timeout_seconds


def test_ranker_startup_gets_only_the_remaining_source_wait_allowance(tmp_path, monkeypatch):
    from types import SimpleNamespace

    class FastRanker:
        gpu_lock_wait_seconds = 0.0

        def __init__(self, _settings, *, startup_timeout_seconds=None):
            self.startup_timeout_seconds = startup_timeout_seconds
            time.sleep(0.001)
            self.client = self

        def caption_images(self, **_kwargs):
            time.sleep(0.02)
            return "reviewed"

    monkeypatch.setattr(
        bake, "build_llama_cpp_vision_settings",
        lambda _request: SimpleNamespace(llama_cpp_parallel=1, vision_llm_workers=1),
    )
    monkeypatch.setattr(bake, "LlamaCppVisionRanker", FastRanker)
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json", workspace=tmp_path,
        body_model_root=None, source_review_timeout_seconds=0.15,
    )
    session = bake.LazyLlamaCppVisionSession(request)
    budget = _SourceTurnBudget(request)
    budget.exclude_wait(0.14)
    time.sleep(0.14)
    session.set_candidate_deadline(
        budget.deadline,
        on_wait=budget.exclude_wait,
        wait_remaining=budget.remaining_wait_seconds,
    )

    assert session.caption_images(frame_paths=[], prompt="source review") == "reviewed"

    assert 0.0 < session._ranker.startup_timeout_seconds <= 0.011
    assert budget.remaining_wait_seconds() < 0.01
    assert 0.015 <= budget.elapsed() < 0.08


def test_staged_source_turn_caps_inflight_caption_and_preserves_unresolved_candidate(tmp_path, monkeypatch):
    deadlines = threading.local()
    caption_calls = []

    class FakeSession:
        def __init__(self, _request):
            pass

        def set_candidate_deadline(self, deadline, *, on_wait=None, wait_remaining=None):
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


def test_source_turn_budget_readiness_requires_matching_explicit_turn_scope(tmp_path):
    from exercise_motion_pkg.source_turn_budget import source_turn_budget_readiness

    workspace = tmp_path / "carry"
    workspace.mkdir()
    request = SimpleNamespace(
        source_review_timeout_seconds=10.0,
        exercise_timeout_seconds=0.0,
        max_source_window_attempts=2,
    )
    identity = wave._source_turn_exercise_identity("carry", "Carry", {"movement": "walk"})
    budget = _SourceTurnBudget(
        request, exercise_identity=identity, turn_identity="library-run-1"
    )
    budget.begin_attempt()
    (workspace / "source_turn_budget.json").write_text(
        json.dumps(budget.resume_fields()), encoding="utf-8"
    )

    same_turn = source_turn_budget_readiness(
        workspace, "carry", "Carry", {"movement": "walk"}, 10.0, 0.0, 2,
        turn_identity="library-run-1",
    )
    new_turn = source_turn_budget_readiness(
        workspace, "carry", "Carry", {"movement": "walk"}, 10.0, 0.0, 2,
        turn_identity="library-run-2",
    )
    assert same_turn["ready"] is True
    assert same_turn["attemptsUsed"] == 1
    assert same_turn["turnScopeMatches"] is True
    assert new_turn["ready"] is True
    assert new_turn["attemptsUsed"] == 0
    assert new_turn["turnScopeMatches"] is False
    assert new_turn["resetRequired"] is True


@pytest.mark.parametrize(
    "cli_turn_id, expected_ready, expected_attempts",
    [("library-run-1", False, 2), ("library-run-2", True, 0)],
)
def test_list_cli_scopes_exhausted_source_ledger_to_explicit_turn(
    tmp_path, monkeypatch, cli_turn_id, expected_ready, expected_attempts
):
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
        "sourceTurnScopeIdentity": "library-run-1",
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
        "--source-review-turn-id", cli_turn_id,
        "--out-json", str(listed_path),
    ])

    main()

    result = json.loads(listed_path.read_text(encoding="utf-8"))
    item = result["exercises"][0]["sourceReviewBudgetReadiness"]
    assert item["ready"] is expected_ready
    assert item["attemptsUsed"] == expected_attempts
    assert item["status"] == ("ready" if expected_ready else "needs_source_review")
    assert item["stopReason"] == (
        None if expected_ready else "source_turn_attempt_budget"
    )
