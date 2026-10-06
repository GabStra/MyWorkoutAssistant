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


def test_contract_cache_survives_prompt_wording_changes(tmp_path, target, contract, monkeypatch):
    # Advisory prompt wording evolves with generation policy; without a policy
    # bump the exercise definition is unchanged and the cached contract must
    # stay reusable instead of being orphaned by key churn.
    settings = module.YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path / "cache")
    assert module.cache_exercise_motion_contract(target, settings, contract)
    monkeypatch.setattr(
        module, "build_exercise_motion_contract_prompt",
        lambda _exercise: "Reworded advisory prompt text for the same exercise.",
    )
    cached = module.load_cached_exercise_motion_contract(target, settings)
    assert cached is not None
    assert cached["cacheStatus"] == "reused"


def test_contract_cache_tracks_definition_and_policy_inputs(tmp_path, target, contract):
    settings = module.YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path / "cache")
    baseline = module.exercise_motion_contract_cache_path(target, settings)
    assert baseline is not None

    changed_context = module.ExerciseEntry(
        exercise_id=target.exercise_id,
        slug=target.slug,
        name=target.name,
        motion_context={"primaryEquipment": {"type": "barbell"}},
    )
    assert module.exercise_motion_contract_cache_path(changed_context, settings) != baseline

    changed_name = module.ExerciseEntry(exercise_id=target.exercise_id, slug=target.slug, name="Other Press")
    assert module.exercise_motion_contract_cache_path(changed_name, settings) != baseline

    original_policy_version = module.EXERCISE_MOTION_CONTRACT_POLICY_VERSION
    try:
        module.EXERCISE_MOTION_CONTRACT_POLICY_VERSION = original_policy_version + 1
        assert module.exercise_motion_contract_cache_path(target, settings) != baseline
    finally:
        module.EXERCISE_MOTION_CONTRACT_POLICY_VERSION = original_policy_version


def _write_legacy_contract_cache_entry(tmp_path, target, settings, contract_policy_version):
    contract = {
        "status": "generated",
        "source": "llm",
        "exerciseName": target.name,
        "advisoryText": "Press the implement away and return under control.",
        "youtubeQueryAliases": [target.name],
        "contractPolicyVersion": contract_policy_version,
    }
    legacy_path = module.exercise_motion_contract_legacy_cache_path(target, settings)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(json.dumps({
        "schemaVersion": module.EXERCISE_MOTION_CONTRACT_CACHE_VERSION,
        "generatedAt": "2026-09-27T00:00:00+00:00",
        "exerciseName": target.name,
        "contract": contract,
    }), encoding="utf-8")
    return legacy_path


def test_contract_cache_migrates_legacy_prompt_keyed_entries(tmp_path, target):
    settings = module.YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path / "cache")
    legacy_path = _write_legacy_contract_cache_entry(
        tmp_path, target, settings, module.EXERCISE_MOTION_CONTRACT_POLICY_VERSION
    )
    stable_path = module.exercise_motion_contract_cache_path(target, settings)
    assert stable_path is not None and not stable_path.exists()

    cached = module.load_cached_exercise_motion_contract(target, settings)
    assert cached is not None
    assert cached["cacheStatus"] == "reused"
    assert cached["cachePath"] == str(stable_path)
    # Carried forward under the stable key so the legacy entry can age out.
    assert stable_path.exists()
    assert module.load_cached_exercise_motion_contract(target, settings) is not None
    assert legacy_path.exists()


def test_contract_cache_rejects_legacy_entries_from_older_contract_policy(tmp_path, target):
    settings = module.YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path / "cache")
    _write_legacy_contract_cache_entry(
        tmp_path, target, settings, module.EXERCISE_MOTION_CONTRACT_POLICY_VERSION - 1
    )
    stable_path = module.exercise_motion_contract_cache_path(target, settings)
    assert stable_path is not None

    assert module.load_cached_exercise_motion_contract(target, settings) is None
    # A policy bump must not be resurrected through the legacy fallback.
    assert not stable_path.exists()


def test_single_dumbbell_rule_reaches_prompts_and_invalidates_two_arm_cache(tmp_path):
    target = module.ExerciseEntry(exercise_id="press", slug="press", name="Single Dumbbell Incline Press")
    contract = {"status": "generated", "source": "llm", "exerciseName": target.name,
                "advisoryText": "Press the single dumbbell with controlled range.",
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
        assert "Set handRelationship to single" in prompt
        assert "A two-handed grip or bilateral dumbbell action is a different movement" in prompt
    saved = json.loads(cache_path.read_text())
    saved["contract"]["validStartState"] = "Grip the dumbbell with both hands."
    cache_path.write_text(json.dumps(saved), encoding="utf-8")
    assert module.load_cached_exercise_motion_contract(target, settings) is None
    assert not module.exercise_motion_contract_is_usable(saved["contract"])
    assert any("more than one working arm" in issue for issue in
               module.exercise_motion_contract_quality_issues(saved["contract"], exercise=target))
    saved["contract"]["handRelationship"] = "rigid_pair"
    assert any("more than one working arm" in issue for issue in
               module.exercise_motion_contract_quality_issues(saved["contract"], exercise=target))


def test_single_dumbbell_discovery_rechecks_legacy_reviews_once():
    target = module.ExerciseEntry(exercise_id="press", slug="press", name="Single Dumbbell Incline Press")
    candidate = module.YouTubeCandidate(url="https://example.test/demo", video_id="demo",
        title=target.name, channel=None, duration_seconds=20, view_count=None,
        upload_date=None, description_snippet=None, thumbnail=None,
        vision_payload={"singleDumbbellNamingPolicyVersion": 2,
                        "semanticGate": {"passed": False}}, status="rejected")
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
    reviewed = result.debug_candidates_by_key[candidate.key()]
    assert reviewed.vision_payload["singleDumbbellNamingPolicyVersion"] == 3
    kwargs["debug_candidates_by_key"] = result.debug_candidates_by_key
    module.run_youtube_candidate_review_batches(**kwargs)
    assert calls == ["demo"]
    other = module.ExerciseEntry(exercise_id="other", slug="other", name="Dumbbell Incline Press")
    assert module.candidate_has_debug_review_payload(candidate, exercise=other)
