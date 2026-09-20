import json
from dataclasses import replace

from exercise_motion_pkg import discovery_budget as budget_module
from exercise_motion_pkg.discovery_budget import DiscoveryBudget
from exercise_motion_pkg.youtube import YouTubeCandidate, YouTubeRankingSettings, discover_and_rank_youtube_candidates


def test_discovery_turn_budget_spans_expansion_and_resumes_reviews(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"exercises": [{"name": "Barbell Bench Press"}]}))
    candidates = [YouTubeCandidate(
        url=f"https://www.youtube.com/watch?v=bench-{i}", video_id=f"bench-{i}",
        title=f"Barbell Bench Press {i}", channel="Coach", duration_seconds=45,
        view_count=1000-i, upload_date=None, description_snippet="Bench press", thumbnail=None,
    ) for i in range(8)]
    reviewed = []

    def reject(exercise, candidate, settings):
        reviewed.append(candidate.key())
        return 0.1, ["wrong_exercise"], {"enabled": True, "passed": False, "score": 0.1, "wrongExercise": True}

    settings = YouTubeRankingSettings(
        exercise_motion_contract_enabled=False, exercise_name_rewrite_enabled=False,
        llama_cpp_base_url=None, llama_cpp_auto_start_server=False,
        max_candidates=2, candidate_review_batch_size=2, candidate_review_target_suitable_count=1,
        semantic_gate_enabled=True, semantic_gate_candidates_per_exercise=2,
        semantic_gate_max_candidates_per_exercise=2, discovery_candidate_budget=3,
    )
    def run(options):
        return discover_and_rank_youtube_candidates(
            workout_plan_json=plan, out_json=tmp_path / "candidates.json", settings=options,
            search_fn=lambda *_: candidates, semantic_gate=reject,
        )
    result = run(settings)
    assert len(reviewed) == 3  # Initial and expanded reviews share the same ceiling.
    assert result["exercises"][0]["candidateExpansion"]["discoveryTurn"]["budgetExhausted"]
    run(replace(settings, discovery_candidate_budget=4))
    assert len(reviewed) == 7
    assert len(set(reviewed)) == 7  # Larger second turn never repeats completed reviews.
    run(settings)
    assert len(reviewed) == 8
    run(settings)
    assert len(reviewed) == 8  # Exhausted pool does not loop over the same negatives.


def test_budget_deadline_and_checkpoint_identity(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(budget_module.time, "monotonic", lambda: now[0])
    path = tmp_path / "reviews.json"
    turn = DiscoveryBudget(24, 5, path, "current", started_at=100.0)
    assert turn.remaining(4) == 4
    turn.record({"a": {"status": "candidate"}})
    now[0] = 106.0
    assert turn.exhausted
    assert turn.remaining(4) == 0
    resumed = DiscoveryBudget(96, 900, path, "current")
    resumed.load()
    assert "a" in resumed.reviewed
    assert resumed.consumed == 0
    changed = DiscoveryBudget(96, 900, path, "different contract")
    changed.load()
    assert changed.reviewed == {}



def test_yield_stops_queries_and_preserves_completed_reviews(tmp_path):
    from exercise_motion_pkg.youtube import collect_youtube_search_candidates
    signal = tmp_path / "yield.request"
    budget = DiscoveryBudget(24, 300, tmp_path / "reviews.json", "policy", yield_path=signal)
    budget.record({"reviewed": {"status": "candidate"}})
    calls = []
    def search(query, count):
        calls.append(query)
        signal.write_text("ready")
        return []
    collect_youtube_search_candidates(queries=["one", "two"], settings=YouTubeRankingSettings(),
        search_fn=search, budget=budget)
    assert calls == ["one"]
    assert budget.exhausted
    restored = DiscoveryBudget(checkpoint_path=tmp_path / "reviews.json", signature="policy")
    restored.load()
    assert "reviewed" in restored.reviewed


def test_search_consumes_shared_turn_budget(monkeypatch):
    from exercise_motion_pkg.youtube import collect_youtube_search_candidates
    now = [10.0]
    monkeypatch.setattr(budget_module.time, "monotonic", lambda: now[0])
    budget = DiscoveryBudget(seconds_limit=5, started_at=10)
    calls = []
    def search(query, count):
        calls.append(query)
        now[0] += 6
        return []
    collect_youtube_search_candidates(queries=["one", "two"], settings=YouTubeRankingSettings(),
        search_fn=search, budget=budget)
    assert calls == ["one"]
    assert budget.remaining(4) == 0


def test_prefetched_candidates_are_reviewed_before_search(tmp_path, monkeypatch):
    from exercise_motion_pkg import youtube
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"exercises": [{"name": "Barbell Bench Press"}]}))
    entry = youtube.load_workout_plan_exercises(plan)[0]
    candidate = YouTubeCandidate(url="https://www.youtube.com/watch?v=bench", video_id="bench",
        title="Barbell Bench Press", channel="Coach", duration_seconds=45, view_count=1000,
        upload_date=None, description_snippet="Bench press", thumbnail=None)
    monkeypatch.setattr(youtube, "load_youtube_candidate_prefetch", lambda *a, **k:
        {entry.exercise_id: ([], {candidate.key(): candidate})})
    reviewed = []
    def reject(exercise, candidate, settings):
        reviewed.append(candidate.key())
        return .1, ["wrong_exercise"], {"enabled": True, "passed": False, "score": .1, "wrongExercise": True}
    def forbidden(*args):
        raise AssertionError("Search must not precede the prefetched review")
    settings = YouTubeRankingSettings(exercise_motion_contract_enabled=False, exercise_name_rewrite_enabled=False,
        llama_cpp_base_url=None, llama_cpp_auto_start_server=False, discovery_candidate_budget=1,
        semantic_gate_enabled=True)
    youtube.discover_and_rank_youtube_candidates(workout_plan_json=plan, out_json=tmp_path / "candidates.json",
        settings=settings, search_fn=forbidden, semantic_gate=reject)
    assert reviewed == [candidate.key()]


def test_scheduler_yield_is_not_semantic_exhaustion_and_resume_reviews(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"exercises": [{"name": "Dumbbell Thruster"}]}))
    signal = tmp_path / "discovery_yield.request"
    item = YouTubeCandidate("https://www.youtube.com/watch?v=demo", "demo",
        "Dumbbell Thruster", "Coach", 20, 100, None, None, None)
    reviewed = []
    def search(*args):
        signal.write_text("Reconstruction ready")
        return [item]
    def reject(exercise, candidate, settings):
        reviewed.append(candidate.key())
        return .1, ["wrong_exercise"], {"enabled": True, "passed": False, "score": .1, "wrongExercise": True}
    settings = YouTubeRankingSettings(exercise_motion_contract_enabled=False,
        exercise_name_rewrite_enabled=False, llama_cpp_base_url=None,
        llama_cpp_auto_start_server=False, discovery_candidate_budget=2,
        discovery_time_budget_seconds=300, semantic_gate_enabled=True)
    def run(searcher):
        return discover_and_rank_youtube_candidates(workout_plan_json=plan,
            out_json=tmp_path / "candidates.json", settings=settings,
            search_fn=searcher, semantic_gate=reject)
    result = run(search)
    expansion = result["exercises"][0]["candidateExpansion"]
    assert reviewed == []
    assert expansion["terminalReason"] == "discovery_scheduler_yield"
    turn = expansion["discoveryTurn"]
    assert turn["stopReason"] == "scheduler_yield"
    assert 0 < turn["remainingTimeSeconds"] <= 300
    signal.unlink()
    run(lambda *_: [item])
    assert reviewed == [item.key()]


def test_yield_does_not_renew_exhausted_allowance(tmp_path, monkeypatch):
    signal = tmp_path / "yield.request"
    signal.write_text("pause")
    monkeypatch.setattr(budget_module.time, "monotonic", lambda: 105.0)
    budget = DiscoveryBudget(2, 10, started_at=100, yield_path=signal)
    assert budget.stop_reason == "scheduler_yield"
    assert budget.remaining_seconds() == 0
    assert budget.remaining_seconds(ignore_scheduler_yield=True) == 5
    budget.consumed = 2
    assert budget.stop_reason == "candidate_budget_exhausted"
    budget.consumed = 0
    budget.seconds_limit = 5
    assert budget.stop_reason == "time_budget_exhausted"
