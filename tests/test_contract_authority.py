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
