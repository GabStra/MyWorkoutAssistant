"""Focused tests for the exercise-motion contract critic patch path."""
from __future__ import annotations

import json
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


def test_walking_lunge_critic_patch_flips_completion_mode() -> None:
    generation_prompts: list[str] = []
    critic_calls = 0

    def caption_images(**kwargs: object) -> str:
        nonlocal critic_calls
        prompt = str(kwargs.get("prompt") or "")
        if "semantic consistency review" in prompt:
            critic_calls += 1
            return json.dumps(
                {
                    "issues": [
                        {
                            "field": "completionMode",
                            "from": "return_to_start",
                            "value": "distinct_end_state",
                            "evidence": "phases advance into the next forward step",
                        },
                        {
                            "field": "validEndState",
                            "from": "standing upright with feet together before the step",
                            "value": "standing in a forward split stance after advancing one step",
                            "evidence": "finish after the forward advance, not the start stance",
                        },
                    ]
                }
            )
        generation_prompts.append(prompt)
        return json.dumps(_walking_lunge_wrong_return_payload())

    result = youtube.generate_exercise_motion_contract_with_ranker(
        exercise=_exercise(),
        settings=YouTubeRankingSettings(),
        ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)),
    )

    assert len(generation_prompts) == 1
    assert critic_calls == 1
    assert result["status"] == "generated"
    assert result["completionMode"] == "distinct_end_state"
    assert result["requiresReturnToStart"] is False
    assert result["validEndState"] != result["validStartState"]
    assert result["criticAdjustments"]
    assert {op["field"] for op in result["criticAdjustments"]} >= {
        "completionMode",
        "validEndState",
    }


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
        settings=YouTubeRankingSettings(),
        ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)),
    )

    assert len(generation_prompts) == 1
    assert critic_calls == 1
    assert result["status"] == "generated"
    assert "criticAdjustments" not in result
    assert result["completionMode"] == "return_to_start"


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
        settings=YouTubeRankingSettings(),
        ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)),
    )

    assert len(critic_raw) == 2
    assert result["status"] == "generated"
    assert "criticAdjustments" not in result
    assert result["completionMode"] == "return_to_start"


def test_failed_patch_routes_to_repair_then_keeps_original_if_repair_bad() -> None:
    generation_prompts: list[str] = []
    stage = {"n": 0}

    def caption_images(**kwargs: object) -> str:
        prompt = str(kwargs.get("prompt") or "")
        if "semantic consistency review" in prompt:
            # completionMode-only patch leaves identical start/end after normalize
            return json.dumps(
                {
                    "issues": [
                        {
                            "field": "completionMode",
                            "from": "return_to_start",
                            "value": "distinct_end_state",
                            "evidence": "phases advance forward without returning",
                        }
                    ]
                }
            )
        generation_prompts.append(prompt)
        stage["n"] += 1
        if stage["n"] == 1:
            return json.dumps(_walking_lunge_wrong_return_payload())
        # direct_repair still wrong / unusable relative to critic intent
        return json.dumps(_walking_lunge_wrong_return_payload())

    result = youtube.generate_exercise_motion_contract_with_ranker(
        exercise=_exercise(),
        settings=YouTubeRankingSettings(),
        ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)),
    )

    assert len(generation_prompts) == 2
    assert "Previous draft" in generation_prompts[1]
    assert "critic:" in generation_prompts[1]
    assert result["status"] == "generated"
    assert result["completionMode"] == "return_to_start"
    assert result["criticIssues"]
    assert result["criticIssues"][0]["field"] == "completionMode"


def test_failed_patch_repair_can_accept_corrected_contract() -> None:
    generation_prompts: list[str] = []
    stage = {"n": 0}

    def caption_images(**kwargs: object) -> str:
        prompt = str(kwargs.get("prompt") or "")
        if "semantic consistency review" in prompt:
            return json.dumps(
                {
                    "issues": [
                        {
                            "field": "completionMode",
                            "from": "return_to_start",
                            "value": "distinct_end_state",
                            "evidence": "phases advance forward without returning",
                        }
                    ]
                }
            )
        generation_prompts.append(prompt)
        stage["n"] += 1
        if stage["n"] == 1:
            return json.dumps(_walking_lunge_wrong_return_payload())
        return json.dumps(_walking_lunge_corrected_payload())

    result = youtube.generate_exercise_motion_contract_with_ranker(
        exercise=_exercise(),
        settings=YouTubeRankingSettings(),
        ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)),
    )

    assert len(generation_prompts) == 2
    assert "critic:" in generation_prompts[1]
    assert result["status"] == "generated"
    assert result["generationMode"] == "direct_repair"
    assert result["completionMode"] == "distinct_end_state"
    assert result["requiresReturnToStart"] is False
    assert result["criticIssues"]


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
