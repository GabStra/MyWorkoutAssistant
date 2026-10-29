"""Focused tests for the exercise-motion contract critic patch path."""
from __future__ import annotations

import json

import pytest
from types import SimpleNamespace

from exercise_motion_pkg import contract_critic
from exercise_motion_pkg import youtube
from exercise_motion_pkg.youtube import ExerciseEntry, YouTubeRankingSettings


def _exercise(name: str = "Walking Lunge") -> ExerciseEntry:
    return ExerciseEntry(
        exercise_id=name.casefold().replace(" ", "-"),
        name=name,
        slug=name.casefold().replace(" ", "-"),
    )


def _pose_fields(
    *,
    support_mode: str = "standing",
    hand_height: str = "hip",
    torso_orientation: str = "upright",
    knee_state: str = "flexed",
    stance: str = "split",
) -> dict[str, object]:
    constraints = {
        "supportMode": support_mode,
        "handHeight": hand_height,
        "torsoOrientation": torso_orientation,
        "kneeState": knee_state,
        "stance": stance,
    }
    return {
        "startPoseConstraints": dict(constraints),
        "endPoseConstraints": dict(constraints),
    }


def _walking_lunge_wrong_return_payload() -> dict[str, object]:
    return {
        "movementType": "repetition",
        "groundContactMode": "continuous",
        "completionMode": "return_to_start",
        "requiresReturnToStart": True,
        **_pose_fields(),
        "validStartState": "standing upright with feet together before the step",
        "validEndState": "standing upright with feet together before the step",
        "requiredPhases": [
            "step one leg forward into a split lunge",
            "drive through the front foot and bring the back leg through to advance",
        ],
        "primaryMovingRegions": ["hips", "knees", "feet"],
        "referenceRegions": ["torso"],
        "primaryAxis": "depth",
        "motionPattern": "joint_travel",
    }


def _walking_lunge_corrected_payload() -> dict[str, object]:
    return {
        "movementType": "repetition",
        "groundContactMode": "continuous",
        "completionMode": "distinct_end_state",
        "requiresReturnToStart": False,
        **_pose_fields(),
        "validStartState": "standing upright with feet together before the step",
        "validEndState": "standing in a forward split stance after advancing one step",
        "requiredPhases": [
            "step one leg forward into a split lunge",
            "drive through the front foot and bring the back leg through to advance",
        ],
        "primaryMovingRegions": ["hips", "knees", "feet"],
        "referenceRegions": ["torso"],
        "primaryAxis": "depth",
        "motionPattern": "joint_travel",
    }


def _squat_payload() -> dict[str, object]:
    return {
        "movementType": "repetition",
        "groundContactMode": "continuous",
        "completionMode": "return_to_start",
        "requiresReturnToStart": True,
        **_pose_fields(knee_state="extended", stance="shoulder_width"),
        "validStartState": "standing upright before the squat",
        "validEndState": "standing upright after the squat",
        "requiredPhases": ["lower into the squat", "stand back upright"],
        "primaryMovingRegions": ["hips", "knees"],
        "referenceRegions": ["torso"],
        "primaryAxis": "vertical",
        "motionPattern": "joint_travel",
    }


def test_definition_contract_does_not_promote_guessed_video_details() -> None:
    exercise = ExerciseEntry(
        exercise_id="row", name="Single-Arm Dumbbell Row", slug="row",
        motion_context={"primaryEquipment": {"type": "DUMBBELL"},
                        "requiredAccessories": [{"name": "Adjustable Bench"}]},
    )
    payload = {
        **_squat_payload(),
        "validStartState": "Seated on the bench, dumbbell by the hip",
        "validEndState": "Seated on the bench, dumbbell by the hip",
        "requiredPhases": ["Pause with one knee on the bench", "Pull the dumbbell", "Lower it"],
        "handRelationship": "independent",
        "implementSupportMode": "body_supported",
    }
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        payload, exercise=exercise, source="llm",
    )

    assert youtube.exercise_motion_contract_is_usable(contract, exercise=exercise)
    assert contract["handRelationship"] == "single"
    assert contract["implementSupportMode"] == "none"
    assert not youtube.exercise_motion_contract_has_specific_topology(contract)
    assert contract["requiredPhases"] == [
        "Pause with one knee on the bench", "Pull the dumbbell", "Return to start: Lower it",
    ]
    assert contract["actionDefinitionAuthority"] == "unresolved"
    assert all(key not in contract for key in (
        "validStartState", "validEndState", "startPoseConstraints", "endPoseConstraints", "movementTopology",
    ))
    assert "seated" not in json.dumps(contract).lower()
    assert contract["actionDefinitionStatus"] == "defined"
    assert contract["actionDefinitionAuthority"] == "unresolved"
    prompt = youtube.exercise_motion_contract_prompt_body(
        youtube.exercise_motion_contract_for_prompt(contract)
    )
    assert "seated" not in prompt.lower()
    assert "pause" not in prompt.lower()
    assert "Single-Arm Dumbbell Row" in prompt
    critic_prompt = contract_critic.build_contract_critic_prompt(
        exercise_name=exercise.name, equipment="Dumbbell", contract=contract,
    )
    assert "requiredPhases" not in critic_prompt
    assert "validStartState" not in critic_prompt
    assert "No source video has been seen" in critic_prompt
    candidate = youtube.YouTubeCandidate(
        url="https://example.test/row", video_id="row", title="Row demo",
        channel=None, duration_seconds=8, view_count=None, upload_date=None,
        description_snippet=None, thumbnail=None,
    )
    review_prompt = youtube.build_candidate_vision_prompt(exercise.name, candidate, contract)
    assert "Seated on the bench, dumbbell by the hip" not in review_prompt
    assert "Pause with one knee" not in review_prompt
    reused = youtube.normalize_exercise_motion_contract(
        contract, exercise=exercise, source="reused_candidate_contract",
    )
    assert reused["contractScope"] == "definition_only"
    assert "movementTopology" not in reused
    assert "startPoseConstraints" not in reused


def test_approved_return_action_does_not_require_return_word_in_phase_labels() -> None:
    defining_action = "Press the bar from behind the neck to overhead, then lower it behind the neck."
    phases = ["start position behind neck", "press overhead", "lower behind neck"]
    exercise = ExerciseEntry(
        exercise_id="behind-neck-press",
        name="Barbell Behind-the-Neck Press",
        slug="barbell-behind-the-neck-press",
        motion_context={"exerciseDefinition": {
            "definingAction": defining_action,
            "completionMode": "return_to_start",
            "requiredPhases": phases,
        }},
    )
    retained_response = {
        "definingAction": defining_action,
        "movementType": "repetition",
        "groundContactMode": "continuous",
        "implementSupportMode": "hands_only",
        "handRelationship": "rigid_pair",
        "completionMode": "return_to_start",
        "requiredPhases": phases,
        "actionDefinitionStatus": "defined",
        "primaryMovingRegions": ["shoulders", "upper_limb"],
        "referenceRegions": ["torso", "head"],
        "primaryAxis": "vertical",
        "motionPattern": "distal_limb_vertical",
        "mustBeVisibleRegions": ["hands", "elbows", "shoulders", "torso", "head"],
    }

    contract = youtube.normalize_definition_exercise_motion_contract_response(
        retained_response, exercise=exercise, source="llm",
    )

    assert contract["completionMode"] == "return_to_start"
    assert contract["requiredPhases"] == phases
    assert youtube.exercise_motion_contract_quality_issues(contract, exercise=exercise) == []
    assert youtube.exercise_motion_contract_is_usable(contract, exercise=exercise)


def test_completion_semantics_still_reject_contradictory_endpoints_and_phases() -> None:
    constraints = _pose_fields()
    return_contract = {
        "completionMode": "return_to_start",
        **constraints,
        "requiredPhases": ["lower the bar behind the neck"],
    }
    return_contract["endPoseConstraints"]["stance"] = "shoulder_width"
    assert "return_to_start endpoint pose constraints disagree" in (
        youtube.exercise_motion_contract_quality_issues(return_contract)
    )

    distinct_contract = {
        "completionMode": "distinct_end_state",
        "validStartState": "standing with the bar at shoulder height",
        "validEndState": "standing with the bar overhead",
        "requiredPhases": ["press overhead, then return to the start"],
    }
    assert "distinct_end_state contract includes a return-to-start phase" in (
        youtube.exercise_motion_contract_quality_issues(distinct_contract)
    )


def test_definition_contract_uses_authoritative_pair_equipment() -> None:
    exercise = ExerciseEntry(
        exercise_id="floor", name="Dumbbell Floor Press", slug="floor",
        motion_context={"primaryEquipment": {"type": "DUMBBELLS"}},
    )
    payload = {
        **_squat_payload(),
        "handRelationship": "rigid_pair",
        "implementSupportMode": "body_supported",
        "validStartState": "Arms overhead while standing",
    }
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        payload, exercise=exercise, source="llm",
    )
    assert contract["handRelationship"] == "independent"
    assert contract["implementSupportMode"] == "none"
    assert "overhead" not in json.dumps(contract).lower()
    assert youtube.exercise_motion_contract_is_usable(contract, exercise=exercise)


def test_definition_contract_reuses_without_regenerating_topology(tmp_path) -> None:
    from exercise_motion_pkg.bake_and_rank import resolve_two_scale_exercise_motion_contract
    from exercise_motion_pkg.revalidation_contracts import RevalidationContractCache

    exercise = _exercise("Dumbbell Floor Press")
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        _squat_payload(), exercise=exercise, source="llm",
    )
    def unexpected_model_call(**_kwargs):
        raise AssertionError("definition-only contract must not trigger regeneration")

    resolved, raw, error = resolve_two_scale_exercise_motion_contract(
        SimpleNamespace(), contract=contract, caption_images=unexpected_model_call,
    )
    assert (resolved, raw, error) == (contract, None, None)

    cache_file = tmp_path / "contract.json"
    cache_file.write_text(json.dumps({
        "schemaVersion": youtube.EXERCISE_MOTION_CONTRACT_CACHE_VERSION,
        "contract": contract,
    }), encoding="utf-8")
    assert RevalidationContractCache(tmp_path).resolve(exercise.name, {}) is not None


def test_previous_definition_cache_is_migrated_without_placeholder_states(tmp_path) -> None:
    exercise = _exercise("Dumbbell Floor Press")
    settings = YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path)
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        _squat_payload(), exercise=exercise, source="llm",
    )
    previous = {
        **contract, "contractPolicyVersion": 34,
        "validStartState": "Natural beginning of one execution",
        "requiredPhases": ["Perform one execution"],
        "startPoseConstraints": {"supportMode": "any"},
    }
    key = youtube.exercise_motion_contract_cache_key_payload(exercise, settings)
    key["contractPolicyVersion"] = 34
    previous_path = youtube.exercise_motion_contract_cache_path_for_key_payload(tmp_path, key)
    previous_path.write_text(json.dumps({
        "schemaVersion": youtube.EXERCISE_MOTION_CONTRACT_CACHE_VERSION,
        "contract": previous,
    }), encoding="utf-8")
    from exercise_motion_pkg.revalidation_contracts import RevalidationContractCache
    assert RevalidationContractCache(tmp_path).resolve(exercise.name, {})["contractPolicyVersion"] == youtube.EXERCISE_MOTION_CONTRACT_POLICY_VERSION

    migrated = youtube.load_cached_exercise_motion_contract(exercise, settings)

    assert migrated is not None
    assert migrated["contractPolicyVersion"] == youtube.EXERCISE_MOTION_CONTRACT_POLICY_VERSION
    assert migrated["observableMotionSpec"]["primaryAxis"] == contract["observableMotionSpec"]["primaryAxis"]
    assert "validStartState" not in migrated
    assert migrated["requiredPhases"] == ["Return to start: Perform one execution"]
    assert "startPoseConstraints" not in migrated
    assert youtube.exercise_motion_contract_cache_path(exercise, settings).is_file()


def test_definition_source_review_does_not_queue_topology_question(monkeypatch, tmp_path) -> None:
    from pathlib import Path
    from exercise_motion_pkg import bake_and_rank, review_questions

    exercise = _exercise("Dumbbell Floor Press")
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        _squat_payload(), exercise=exercise, source="llm",
    )
    assert "generated phases" not in bake_and_rank.two_scale_contract_authority_guidance(contract)
    monkeypatch.setattr(bake_and_rank, "final_output_motion_contact_sheets",
                        lambda *_args, **_kwargs: [Path("motion.jpg")])
    monkeypatch.setattr(bake_and_rank, "source_equipment_detail_frames",
                        lambda *_args, **_kwargs: [])

    def unexpected_questions(*_args, **_kwargs):
        raise AssertionError("Unresolved target semantics stop before source review questions")

    monkeypatch.setattr(review_questions, "run_questions", unexpected_questions)
    item = SimpleNamespace(exercise_name=exercise.name, candidate={}, candidate_workspace=tmp_path)
    result = bake_and_rank._validate_two_scale_source_uncached(
        item, uniform_sheet_paths=[Path("uniform.jpg")], output_dir=tmp_path,
        caption_images=lambda **_kwargs: None, exercise_motion_contract=contract,
    )
    assert result["reviewStatus"] == "incomplete"
    assert "two_scale_source_action_definition_unresolved" in result["missingEvidenceReasons"]


def test_reference_region_does_not_become_required_lower_body_motion() -> None:
    from exercise_motion_pkg.target_motion import observable_motion_spec_mentions_lower_body

    contract = {
        "observableMotionSpec": {
            "primaryMovingRegions": ["upper_limb"], "referenceRegions": ["feet"],
        },
    }
    assert not observable_motion_spec_mentions_lower_body(contract)
    contract["observableMotionSpec"]["primaryMovingRegions"] = ["lower_limb"]
    assert observable_motion_spec_mentions_lower_body(contract)


def test_singular_implement_does_not_choose_a_grip_without_arm_evidence() -> None:
    from exercise_motion_pkg.equipment_constraints import declared_hand_relationship

    assert declared_hand_relationship({
        "exerciseName": "Supported Press",
        "motionContext": {"primaryEquipment": {"type": "DUMBBELL"}},
    }) == "unknown"


@pytest.mark.parametrize("name,mode", [
    ("Kneeling Press", "return_to_start"),
    ("Snatch", "distinct_end_state"),
    ("Plank", "stable_hold"),
    ("Farmer Carry", "active_travel"),
])
def test_definition_contract_keeps_only_explicit_boundaries(name: str, mode: str) -> None:
    exercise = _exercise(name)
    payload = {**_squat_payload(), "completionMode": mode}
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        payload, exercise=exercise, source="llm",
    )
    assert youtube.exercise_motion_contract_is_usable(contract, exercise=exercise)
    assert contract["contractScope"] == "definition_only"
    assert contract["completionMode"] == mode
    assert "validStartState" not in contract
    assert "startPoseConstraints" not in contract
    assert contract["requiredPhases"] == ["lower into the squat", "stand back upright"]
    if mode in {"return_to_start", "distinct_end_state", "alternating_pair"}:
        assert youtube.exercise_motion_action_definition_review_reason(contract) == "target_action_definition_unresolved"


def test_definition_only_contract_roundtrip_preserves_nested_observable_motion_identity() -> None:
    motion_context = {"primaryEquipment": {"type": "BARBELL"}}
    exercise = ExerciseEntry(
        exercise_id="squat",
        name="Barbell Back Squat",
        slug="barbell-back-squat",
        motion_context=motion_context,
    )
    observable_spec = {
        "schemaVersion": 1,
        "primaryMovingRegions": ["hips", "knees"],
        "referenceRegions": ["feet", "torso"],
        "primaryAxis": "vertical",
        "motionPattern": "joint_flex_extend",
        "requiresReturnToStart": True,
        "oneWayPartialIsInvalid": True,
        "mustShowFullCycle": True,
        "mustBeVisibleRegions": ["hips", "knees", "feet", "torso"],
    }
    payload = {
        "contractScope": "definition_only",
        "contractPolicyVersion": youtube.EXERCISE_MOTION_CONTRACT_POLICY_VERSION,
        "exerciseName": exercise.name,
        "motionContext": motion_context,
        "movementType": "repetition",
        "groundContactMode": "continuous",
        "implementSupportMode": "body_supported",
        "handRelationship": "rigid_pair",
        "completionMode": "return_to_start",
        "requiresReturnToStart": True,
        "definingAction": "Lower by bending the hips and knees, then rise to standing.",
        "requiredPhases": ["lower into the squat", "stand back upright"],
        "actionDefinitionStatus": "defined",
        "actionDefinitionAuthority": "structured_definition",
        "primaryMovingRegions": ["hips", "knees"],
        "referenceRegions": ["feet", "torso"],
        "mustBeVisibleRegions": ["hips", "knees", "feet", "torso"],
        "observableMotionSpec": observable_spec,
    }
    payload["advisoryText"] = youtube.synthesize_exercise_motion_advisory_text(payload)
    raw_prompt_sha = youtube.exercise_motion_contract_prompt_sha256(payload)

    normalized = youtube.normalize_exercise_motion_contract(
        payload, exercise=exercise, source="reused_candidate_contract",
    )
    normalized_again = youtube.normalize_exercise_motion_contract(
        normalized, exercise=exercise, source="reused_candidate_contract",
    )

    assert normalized["observableMotionSpec"] == observable_spec
    assert normalized_again["observableMotionSpec"] == observable_spec
    assert youtube.exercise_motion_contract_prompt_sha256(normalized) == raw_prompt_sha
    assert youtube.exercise_motion_contract_prompt_sha256(normalized_again) == raw_prompt_sha
    assert youtube.normalize_observable_motion_spec(["vertical"]) is None


def test_parse_drops_whitelist_stale_and_non_enum_ops() -> None:
    parsed = contract_critic.parse_contract_critic_issues(
        {
            "issues": [
                {
                    "field": "notAField",
                    "from": "a",
                    "value": "b",
                    "evidence": "unknown field should drop",
                },
                {
                    "field": "completionMode",
                    "from": "return_to_start",
                    "value": "not_a_mode",
                    "evidence": "non enum should drop",
                },
                {
                    "field": "completionMode",
                    "from": "return_to_start",
                    "value": "distinct_end_state",
                    "evidence": "phases advance to a new stance",
                },
            ]
        }
    )
    assert parsed == [
        {
            "field": "completionMode",
            "from": "return_to_start",
            "value": "distinct_end_state",
            "evidence": "phases advance to a new stance",
        }
    ]


def test_apply_converts_requires_return_bool_and_drops_stale_from() -> None:
    contract = {
        "completionMode": "return_to_start",
        "requiresReturnToStart": True,
        "validEndState": "same as start",
    }
    patched, applied = contract_critic.apply_contract_critic_patches(
        contract,
        [
            {
                "field": "requiresReturnToStart",
                "from": "true",
                "value": "false",
                "evidence": "traveling finish",
            },
            {
                "field": "completionMode",
                "from": "distinct_end_state",
                "value": "active_travel",
                "evidence": "stale from should drop",
            },
        ],
    )
    assert patched["requiresReturnToStart"] is False
    assert patched["completionMode"] == "return_to_start"
    assert applied == [
        {
            "field": "requiresReturnToStart",
            "from": "true",
            "value": False,
            "evidence": "traveling finish",
        }
    ]


def test_clean_contract_skips_extra_generation_attempt() -> None:
    generation_prompts: list[str] = []
    critic_calls = 0

    def caption_images(**kwargs: object) -> str:
        nonlocal critic_calls
        prompt = str(kwargs.get("prompt") or "")
        if "semantic consistency review" in prompt:
            critic_calls += 1
            return '{"issues":[]}'
        generation_prompts.append(prompt)
        return json.dumps(_squat_payload())

    result = youtube.generate_exercise_motion_contract_with_ranker(
        exercise=_exercise("Barbell Squat"),
        settings=YouTubeRankingSettings(exercise_motion_contract_critic_enabled=True),
        ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)),
    )

    assert len(generation_prompts) == 1
    assert critic_calls == 1
    assert result["status"] == "generated"
    assert "criticAdjustments" not in result
    assert result["completionMode"] == "return_to_start"


def test_contract_normalization_aligns_torso_constraint_with_explicit_endpoint_state() -> None:
    payload = _squat_payload()
    payload["startPoseConstraints"]["torsoOrientation"] = "hinged"
    payload["validStartState"] = (
        "standing with feet shoulder-width apart, torso upright, holding the barbell at hip height"
    )

    corrected = youtube.normalize_exercise_motion_contract(
        payload,
        exercise=_exercise("Barbell Romanian Deadlift"),
        source="llm",
    )

    assert corrected["startPoseConstraints"]["torsoOrientation"] == "upright"
    assert youtube.exercise_motion_contract_is_usable(
        corrected,
        exercise=_exercise("Barbell Romanian Deadlift"),
    )

    hinge_payload = _squat_payload()
    hinge_payload["validStartState"] = "standing with the torso hinged forward at the hips"
    hinge_payload["startPoseConstraints"]["torsoOrientation"] = "hinged"
    preserved = youtube.normalize_exercise_motion_contract(
        hinge_payload,
        exercise=_exercise("Barbell Romanian Deadlift"),
        source="llm",
    )
    assert preserved["startPoseConstraints"]["torsoOrientation"] == "hinged"


def test_cached_contract_reconciles_posture_without_regeneration(tmp_path) -> None:
    exercise = _exercise("Barbell Romanian Deadlift")
    settings = YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path)
    payload = _squat_payload()
    payload["validStartState"] = "standing with torso upright before the squat"
    contract = youtube.normalize_exercise_motion_contract(
        payload,
        exercise=exercise,
        source="llm",
    )
    contract["startPoseConstraints"]["torsoOrientation"] = "hinged"
    cache_path = youtube.exercise_motion_contract_cache_path(exercise, settings)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "schemaVersion": youtube.EXERCISE_MOTION_CONTRACT_CACHE_VERSION,
                "contract": contract,
            }
        ),
        encoding="utf-8",
    )

    reused = youtube.load_cached_exercise_motion_contract(exercise, settings)

    assert reused is not None
    assert reused["cacheStatus"] == "reused"
    assert reused["startPoseConstraints"]["torsoOrientation"] == "upright"


def test_malformed_critic_json_retries_then_keeps_unpatched() -> None:
    critic_raw: list[str] = []

    def caption_images(**kwargs: object) -> str:
        prompt = str(kwargs.get("prompt") or "")
        if "semantic consistency review" in prompt:
            critic_raw.append("bad")
            return "not-json"
        return json.dumps(_squat_payload())

    result = youtube.generate_exercise_motion_contract_with_ranker(
        exercise=_exercise("Barbell Squat"),
        settings=YouTubeRankingSettings(exercise_motion_contract_critic_enabled=True),
        ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)),
    )

    assert len(critic_raw) == 2
    assert result["criticError"]["type"] == "ValueError"
    assert contract_critic.parse_contract_critic_issues({"issues": [{"field": "movementType", "value": "repetition", "e": "wrong evidence key"}]}) is None
    assert result["status"] == "generated"
    assert "criticAdjustments" not in result
    assert result["completionMode"] == "return_to_start"


def test_missing_broad_body_action_is_included_in_contract_repair_prompt() -> None:
    generation_prompts: list[str] = []
    invalid_payload = _squat_payload()
    invalid_payload["primaryMovingRegions"] = []
    invalid_payload["referenceRegions"] = []
    invalid_payload["primaryAxis"] = "any"
    invalid_payload["motionPattern"] = "other"

    def caption_images(**kwargs: object) -> str:
        prompt = str(kwargs.get("prompt") or "")
        generation_prompts.append(prompt)
        if len(generation_prompts) < 3:
            return json.dumps(invalid_payload)
        return json.dumps(_squat_payload())

    result = youtube.generate_exercise_motion_contract_with_ranker(
        exercise=_exercise("Barbell Squat"),
        settings=YouTubeRankingSettings(exercise_motion_contract_critic_enabled=False),
        ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)),
    )

    assert len(generation_prompts) == 3
    assert "definition contract had no valid broad body action" in generation_prompts[2]
    assert result["status"] == "generated"
    assert result["generationMode"] == "direct_repair"
    assert result["generationFallbackReasons"]


def test_critic_disabled_skips_critique_call() -> None:
    prompts: list[str] = []

    def caption_images(**kwargs: object) -> str:
        prompts.append(str(kwargs.get("prompt") or ""))
        return json.dumps(_squat_payload())

    result = youtube.generate_exercise_motion_contract_with_ranker(
        exercise=_exercise("Barbell Squat"),
        settings=YouTubeRankingSettings(exercise_motion_contract_critic_enabled=False),
        ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)),
    )

    assert len(prompts) == 1
    assert "semantic consistency review" not in prompts[0]
    assert result["status"] == "generated"


def test_critic_receives_implement_support_and_cannot_leave_inconsistent_hand_fields() -> None:
    payload = _squat_payload()
    payload.update(implementSupportMode='hands_only', handRelationship='independent')
    exercise = _exercise('Dumbbell Squat')
    contract = youtube.normalize_exercise_motion_contract_response(payload, exercise=exercise, source='llm')
    assert contract_critic.contract_critic_projection(contract)['implementSupportMode'] == 'none'
    assert youtube.exercise_motion_contract_for_prompt(contract)['implementSupportMode'] == 'none'
    contract['implementSupportMode'] = 'hands_only'
    for relationship in ['independent', 'single', 'none']:
        contract['handRelationship'] = relationship
        assert 'hands_only implement support requires rigid_pair hand relationship' in (
            youtube.exercise_motion_contract_quality_issues(contract, exercise=exercise))
        assert not youtube.exercise_motion_contract_is_usable(contract, exercise=exercise)
    for relationship in ['rigid_pair', 'unknown']:
        contract['handRelationship'] = relationship
        assert youtube.exercise_motion_contract_is_usable(contract, exercise=exercise)
    contract.update(implementSupportMode='none', handRelationship='independent')
    assert youtube.exercise_motion_contract_is_usable(contract, exercise=exercise)


def test_review_keeps_generated_phases_advisory_and_target_context_unchanged(monkeypatch):
    exercise = ExerciseEntry(exercise_id="test", name="Paused Press", slug="test",
        motion_context={"primaryEquipment": "Dumbbell", "requiredAccessories": ["Bench"]})
    candidate = youtube.YouTubeCandidate(url="https://example.com", video_id="test", title="Press",
        channel=None, duration_seconds=10, view_count=None, upload_date=None,
        description_snippet=None, thumbnail=None)
    contract = youtube.normalize_exercise_motion_contract_response(_squat_payload(), exercise=exercise, source="llm")
    contract["requiredPhases"] = ["Lower the implement", "Pause for two seconds", "Return to the start"]
    seen = []
    def gate(**kwargs):
        seen.append(kwargs["exercise"])
        return kwargs["ranked"]
    monkeypatch.setattr(youtube, "rank_candidates_with_semantic_gate", gate)
    youtube.run_youtube_candidate_review_pass(exercise=exercise, ranked=[candidate],
        settings=YouTubeRankingSettings(semantic_gate_enabled=True, pose_prefilter_enabled=False, rank_with_vision=False),
        debug_candidates_by_key={}, semantic_gate=None, pose_ranker=None, vision_ranker=None,
        exercise_motion_contract=contract)
    assert seen == [exercise]
    assert seen[0] is exercise
    semantic = youtube.build_candidate_semantic_gate_prompt(exercise, candidate)
    assert "original exercise name" in semantic
    assert "requestedMovement in the motion context defines" not in semantic
    vision = youtube.build_candidate_vision_prompt(exercise.name, candidate, contract)
    assert "Generated pauses, tempo, setup and coaching cues are advisory" in vision
    assert "Explicit pauses or holds requested by the target remain required" in vision
    assert "every required phase in the guidance" not in vision
    critic = contract_critic.build_contract_critic_prompt(exercise_name=exercise.name, equipment="Dumbbell", contract=contract)
    assert "Do not replace a supplied variant with a more common version" in critic
    assert "requiredAccessories" in critic


def test_unverified_critic_cannot_rewrite_a_usable_contract_or_trigger_repair():
    payload = _squat_payload()
    calls = []
    advice = [{"field": "completionMode", "value": "distinct_end_state",
               "evidence": "End state must differ even when returning to start"},
              {"field": "validEndState", "value": "Standing in a different forward stance after the movement",
               "evidence": "A different endpoint is always required"}]
    def caption_images(**kwargs):
        calls.append(kwargs['prompt'])
        return json.dumps({'issues': advice} if 'semantic consistency review' in kwargs['prompt'] else payload)
    exercise = _exercise('Barbell Squat')
    original = youtube.normalize_definition_exercise_motion_contract_response(payload, exercise=exercise, source='llm')
    result = youtube.generate_exercise_motion_contract_with_ranker(exercise=exercise,
        settings=YouTubeRankingSettings(exercise_motion_contract_critic_enabled=True), ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)))
    assert len(calls) == 2
    assert result['completionMode'] == original['completionMode']
    assert result['contractScope'] == original['contractScope']
    assert 'validEndState' not in result
    assert result['requiredPhases'] == original['requiredPhases']
    assert result['criticIssues'] == advice[:1]
    assert 'criticAdjustments' not in result


def test_motion_descriptions_preserve_complete_text_and_reject_excessive_lengths():
    payload = _squat_payload()
    endpoint = 'The body remains upright with planted feet and controlled posture. ' * 5 + 'Both elbows remain extended.'
    phase = 'Lower the body while maintaining balance and the observed support contacts. ' * 3 + 'Then return to the original upright posture.'
    payload.update(validStartState=endpoint, validEndState=endpoint,
                   requiredPhases=['Lower the body through the intended range', phase])
    contract = youtube.normalize_exercise_motion_contract_response(payload, exercise=_exercise('Squat'), source='llm')
    assert contract['validStartState'] == endpoint
    assert contract['validEndState'] == endpoint
    assert contract['requiredPhases'][-1] == phase.rstrip('.')
    assert contract['movementTopology']['phases'][-1]['label'] == phase.rstrip('.')
    assert youtube.exercise_motion_contract_quality_issues(contract) == []
    for field, excessive in [('validStartState', 'x' * 1025), ('requiredPhases', ['x' * 513])]:
        with pytest.raises(ValueError, match='too long'):
            youtube.normalize_exercise_motion_contract_response({**payload, field: excessive}, exercise=_exercise(), source='llm')



@pytest.mark.parametrize('equipment_type', ['DUMBBELLS', 'KETTLEBELLS'])
def test_explicit_separate_equipment_corrects_rigid_pair_without_model_authority(equipment_type):
    from exercise_motion_pkg.equipment_constraints import declared_hand_relationship
    exercise = ExerciseEntry(exercise_id='test', name='Loaded Movement', slug='test',
        motion_context={'primaryEquipment': {'type': equipment_type}})
    payload = {**_squat_payload(), 'handRelationship': 'rigid_pair', 'implementSupportMode': 'hands_only',
               'motionContext': {'primaryEquipment': {'type': 'BARBELL'}}}
    contract = youtube.normalize_exercise_motion_contract_response(payload, exercise=exercise, source='llm')
    assert contract['motionContext'] == exercise.motion_context
    assert contract['handRelationship'] == 'independent'
    assert contract['implementSupportMode'] == 'none'
    assert declared_hand_relationship({**payload, 'motionContext': exercise.motion_context}) == 'independent'
    assert contract['requiredPhases'] == youtube.normalize_required_phase_labels(payload['requiredPhases'])


@pytest.mark.parametrize('relationship', ['single', 'independent', 'none'])
def test_non_rigid_hands_cannot_create_a_two_hand_implement_constraint(relationship):
    payload = {**_squat_payload(), 'handRelationship': relationship, 'implementSupportMode': 'hands_only'}
    contract = youtube.normalize_exercise_motion_contract_response(payload, exercise=_exercise(), source='llm')
    assert contract['handRelationship'] == relationship
    assert contract['implementSupportMode'] == 'none'


@pytest.mark.parametrize('equipment_type', ['DUMBBELL', 'KETTLEBELL', 'BARBELL', 'UNKNOWN'])
def test_equipment_alone_does_not_override_a_possible_two_hand_grip(equipment_type):
    exercise = ExerciseEntry(exercise_id='test', name='Loaded Movement', slug='test',
        motion_context={'primaryEquipment': {'type': equipment_type}})
    payload = {**_squat_payload(), 'handRelationship': 'rigid_pair', 'implementSupportMode': 'hands_only'}
    contract = youtube.normalize_exercise_motion_contract_response(payload, exercise=exercise, source='llm')
    assert contract['handRelationship'] == 'rigid_pair'
    assert contract['implementSupportMode'] == 'hands_only'


@pytest.mark.parametrize('code,should_abort', [('structured_output_failed', False), ('server_error', True)])
def test_incomplete_advisory_output_keeps_valid_draft_but_infrastructure_errors_abort(code, should_abort):
    from exercise_motion_pkg.vlm_errors import critical_vlm_http_status_error, CriticalVlmInteractionError
    def caption_images(**kwargs):
        if 'semantic consistency review' in kwargs['prompt']:
            raise critical_vlm_http_status_error(interaction='test', status_code=502,
                body=json.dumps({'error': {'code': code}}), image_count=0, image_bytes=0, prompt_chars=100)
        return json.dumps(_squat_payload())
    def generate():
        return youtube.generate_exercise_motion_contract_with_ranker(exercise=_exercise('Squat'),
            settings=YouTubeRankingSettings(exercise_motion_contract_critic_enabled=True), ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)))
    if should_abort:
        with pytest.raises(CriticalVlmInteractionError):
            generate()
    else:
        result = generate()
        assert result['status'] == 'generated'
        assert result['criticError']['details']['statusCode'] == 502
        assert youtube.exercise_motion_contract_is_usable(result, exercise=_exercise('Squat'))


def test_default_generation_omits_redundant_critic_call():
    prompts = []
    def caption_images(**kwargs):
        prompts.append(kwargs['prompt'])
        return json.dumps(_squat_payload())
    result = youtube.generate_exercise_motion_contract_with_ranker(exercise=_exercise('Squat'),
        settings=YouTubeRankingSettings(), ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)))
    assert result['status'] == 'generated'
    assert len(prompts) == 1
    assert 'criticIssues' not in result
