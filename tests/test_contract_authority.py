import json
from copy import deepcopy

import pytest

from exercise_motion_pkg import youtube as module


@pytest.fixture
def target():
    return module.ExerciseEntry(exercise_id="example", slug="example", name="Example Press")


@pytest.fixture
def contract(target):
    return {"status": "generated", "source": "llm", "exerciseName": target.name,
            "advisoryText": "Press the implement away and return under control.",
            "youtubeQueryAliases": [target.name]}


@pytest.mark.parametrize("legacy_origin", [
    {"source": "support_mode_correction"},
    {"source": "source_observed_completion_boundary"},
    {"supportModeCorrection": {"from": "a", "to": "b"}},
    {"completionBoundaryCorrection": {"from": "a", "to": "b"}},
])
def test_video_derived_contract_cannot_enter_through_cache_seed_or_prompt(tmp_path, target, contract, legacy_origin):
    settings = module.YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path / "cache")
    assert module.exercise_motion_contract_is_usable(contract, exercise=target)
    cache_path = module.cache_exercise_motion_contract(target, settings, contract)
    original_bytes = cache_path.read_bytes()
    changed = {**deepcopy(contract), **legacy_origin}
    assert not module.exercise_motion_contract_is_usable(changed, exercise=target)
    assert module.cache_exercise_motion_contract(target, settings, changed) is None
    assert cache_path.read_bytes() == original_bytes  # Invalid revisions cannot overwrite a valid cache.
    with pytest.raises(ValueError, match="Candidate observations"):
        module.normalize_exercise_motion_contract(changed, exercise=target, source="seeded_candidates_json")
    assert module.exercise_motion_contract_for_prompt(changed) is None
    saved = json.loads(original_bytes)
    saved["contract"] = changed
    cache_path.write_text(json.dumps(saved), encoding="utf-8")
    assert module.load_cached_exercise_motion_contract(target, settings) is None
    seed = tmp_path / "candidates.json"
    seed.write_text(json.dumps({"exercises": [{"exerciseName": target.name, "exerciseMotionContract": changed}]}))
    assert module.load_seed_exercise_motion_contract_from_candidates_json(seed, target) is None


def test_candidate_payload_cannot_supply_target_contract(tmp_path, target, contract):
    seed = tmp_path / "candidates.json"
    seed.write_text(json.dumps({"exercises": [{"exerciseName": target.name,
        "candidates": [{"status": "recommended", "visionPayload": {"exerciseMotionContract": contract}}]}]}))
    assert module.load_seed_exercise_motion_contract_from_candidates_json(seed, target) is None


def test_definition_contract_still_reuses_cache_and_top_level_seed(tmp_path, target, contract):
    settings = module.YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path / "cache")
    assert module.cache_exercise_motion_contract(target, settings, contract)
    assert module.load_cached_exercise_motion_contract(target, settings)["cacheStatus"] == "reused"
    seed = tmp_path / "candidates.json"
    seed.write_text(json.dumps({"exercises": [{"exerciseName": target.name, "exerciseMotionContract": contract}]}))
    assert module.load_seed_exercise_motion_contract_from_candidates_json(seed, target)


def test_single_dumbbell_rule_reaches_prompts_and_invalidates_two_hand_cache(tmp_path):
    target = module.ExerciseEntry(exercise_id="press", slug="press", name="Single Dumbbell Incline Press")
    contract = {"status": "generated", "source": "llm", "exerciseName": target.name,
                "advisoryText": "Press and return. Reject holding the dumbbell with both hands.",
                "validStartState": "Hold the dumbbell in one hand; free hand supports the bench.",
                "youtubeQueryAliases": [target.name]}
    settings = module.YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path / "cache")
    cache_path = module.cache_exercise_motion_contract(target, settings, contract)
    assert cache_path
    assert module.load_cached_exercise_motion_contract(target, settings)
    candidate = module.YouTubeCandidate(url="https://example.test/demo", video_id="demo",
        title=target.name, channel=None, duration_seconds=20, view_count=None,
        upload_date=None, description_snippet=None, thumbnail=None)
    for prompt in (module.build_exercise_motion_contract_prompt(target),
                   module.build_candidate_semantic_gate_prompt(target, candidate),
                   module.exercise_motion_contract_prompt_body(contract)):
        assert "exactly one dumbbell and one working arm" in prompt
    saved = json.loads(cache_path.read_text())
    saved["contract"]["validStartState"] = "Hold the dumbbell with both hands."
    cache_path.write_text(json.dumps(saved), encoding="utf-8")
    assert module.load_cached_exercise_motion_contract(target, settings) is None
    assert not module.exercise_motion_contract_is_usable(saved["contract"])
    assert any("one working arm" in issue for issue in
               module.exercise_motion_contract_quality_issues(saved["contract"], exercise=target))


def test_single_dumbbell_discovery_rechecks_legacy_reviews_once():
    target = module.ExerciseEntry(exercise_id="press", slug="press", name="Single Dumbbell Incline Press")
    candidate = module.YouTubeCandidate(url="https://example.test/demo", video_id="demo",
        title=target.name, channel=None, duration_seconds=20, view_count=None,
        upload_date=None, description_snippet=None, thumbnail=None,
        vision_payload={"semanticGate": {"passed": False}}, status="rejected")
    settings = module.YouTubeRankingSettings(semantic_gate_enabled=True,
        pose_prefilter_enabled=False, rank_with_vision=False)
    calls = []
    def gate(exercise, item, settings):
        calls.append(item.video_id)
        return 0., ["wrong variant"], {"wrongExercise": True}
    kwargs = dict(exercise=target, ranked=[candidate], settings=settings,
                  debug_candidates_by_key={candidate.key(): candidate},
                  semantic_gate=gate, pose_ranker=None, vision_ranker=None)
    result = module.run_youtube_candidate_review_batches(**kwargs)
    assert calls == ["demo"]
    kwargs["debug_candidates_by_key"] = result.debug_candidates_by_key
    module.run_youtube_candidate_review_batches(**kwargs)
    assert calls == ["demo"]
    other = module.ExerciseEntry(exercise_id="other", slug="other", name="Dumbbell Incline Press")
    assert module.candidate_has_debug_review_payload(candidate, exercise=other)
