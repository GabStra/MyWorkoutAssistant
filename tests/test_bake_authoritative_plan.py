from __future__ import annotations

import json
from pathlib import Path

import pytest

import exercise_motion_pkg.bake_and_rank as bake_and_rank
from exercise_motion_pkg import cli


def _bake_request(tmp_path: Path, *, plan_path: Path | None = None):
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text("{}", encoding="utf-8")
    argv = [
        "bake-and-rank",
        "--candidates-json",
        str(candidates_path),
        "--workspace",
        str(tmp_path / "workspace"),
    ]
    if plan_path is not None:
        argv.extend(["--exercise-plan-json", str(plan_path)])
    args = cli.build_parser().parse_args(argv)
    return cli.build_bake_and_rank_request(args)


def _write_plan(path: Path, exercises: list[dict]) -> Path:
    path.write_text(json.dumps({"schemaVersion": 1, "exercises": exercises}), encoding="utf-8")
    return path


def _exercise(identifier: str, name: str, motion_context: dict) -> dict:
    return {"id": identifier, "name": name, "motionContext": motion_context}


def test_exercise_plan_flag_sets_authoritative_motion_context(tmp_path: Path) -> None:
    context = {
        "exerciseDefinition": {
            "definingAction": "Move a dumbbell diagonally across the body.",
            "bilateralExecution": {},
        },
        "primaryEquipment": {"id": "equipment-1", "type": "DUMBBELL", "name": "Dumbbell"},
    }
    plan_path = _write_plan(
        tmp_path / "exercise_plan.json",
        [_exercise("dumbbell-woodchopper", "Dumbbell Woodchopper", context)],
    )

    request = _bake_request(tmp_path, plan_path=plan_path)

    assert request.authoritative_exercise_motion_context == context
    assert request.authoritative_exercise_motion_context["exerciseDefinition"]["bilateralExecution"] == {}


def test_missing_exercise_plan_flag_keeps_legacy_candidate_fallback(tmp_path: Path) -> None:
    request = _bake_request(tmp_path)

    assert request.authoritative_exercise_motion_context is None


@pytest.mark.parametrize("location", ["direct", "vision", "advisory"])
def test_runtime_contract_keeps_explicit_empty_intent_without_changing_prompt(location):
    from exercise_motion_pkg.youtube import exercise_motion_contract_for_prompt

    contract = {
        "exerciseName": "Diagonal lift", "advisoryText": "Move diagonally and return.",
        "contractScope": "definition_only", "source": "structured_definition",
        "bilateralExecution": {}, "bilateralExecutionAuthority": "structured_definition",
    }
    candidate = {"exerciseMotionContract": contract}
    if location == "vision":
        candidate = {"visionPayload": candidate}
    elif location == "advisory":
        candidate = {"visionPayload": {"advisoryVlmSourceReview": candidate}}
    prompt = exercise_motion_contract_for_prompt(contract)
    assert "bilateralExecution" not in prompt

    extracted = bake_and_rank.exercise_motion_contract_from_candidate(candidate)

    assert extracted["bilateralExecution"] == {}
    assert extracted["bilateralExecutionAuthority"] == "structured_definition"
    assert exercise_motion_contract_for_prompt(extracted) == prompt


def test_execution_intent_alone_does_not_hide_review_source_provenance(tmp_path):
    from types import SimpleNamespace
    from exercise_motion_pkg.youtube import exercise_motion_contract_for_prompt

    contract = {
        "exerciseName": "Diagonal lift", "advisoryText": "Move diagonally and return.",
        "contractScope": "definition_only", "status": "ready", "source": "structured_definition",
        "bilateralExecution": {}, "bilateralExecutionAuthority": "structured_definition",
    }
    echo = {**exercise_motion_contract_for_prompt(contract), "bilateralExecution": {}}
    item = SimpleNamespace(candidate={"exerciseMotionContract": contract}, candidate_workspace=tmp_path)
    ranking = SimpleNamespace(payload={"exerciseMotionContract": echo})

    extracted = bake_and_rank.exercise_motion_contract_for_review_item(item, ranking)

    assert extracted["status"] == "ready"
    assert extracted["source"] == "structured_definition"
    assert extracted["bilateralExecution"] == {}


def test_multi_exercise_plan_is_rejected(tmp_path: Path) -> None:
    plan_path = _write_plan(
        tmp_path / "exercise_plan.json",
        [
            _exercise("exercise-1", "Dumbbell Woodchopper", {"exerciseDefinition": {"definingAction": "a"}}),
            _exercise("exercise-2", "Dumbbell Overhead Press", {"exerciseDefinition": {"definingAction": "b"}}),
        ],
    )

    with pytest.raises(ValueError, match="exactly one exercise"):
        _bake_request(tmp_path, plan_path=plan_path)


WORKSPACE = (
    Path(__file__).resolve().parents[1]
    / ".scratch"
    / "goal-contact-continuation"
    / "wood-normal-owner-host-v32"
    / "workspace"
)
PLAN = WORKSPACE / "dumbbell-woodchopper" / "exercise_plan.json"
CANDIDATES = (
    WORKSPACE
    / "staged-waves"
    / "all13-wood-normal-owner-host-20261114-v32-wave-0001"
    / "candidates-83323568314a45479128b4bb019e7686.json"
)
CACHE_DIR = WORKSPACE / "exercise-motion-contract-cache"
AUTHORITATIVE_CACHE_FILE = (
    CACHE_DIR / "d81d149de7a14ca40fae5d7e42b1ba1e339480e00bb852581a355e2e0db20d96.json"
)


@pytest.mark.skipif(
    not (PLAN.is_file() and CANDIDATES.is_file() and AUTHORITATIVE_CACHE_FILE.is_file()),
    reason="retained v32 authoritative plan/candidate/cache artifacts are unavailable",
)
def test_public_cli_request_resolves_retained_authoritative_contract_without_model(
    tmp_path: Path,
) -> None:
    argv = [
        "bake-and-rank",
        "--candidates-json",
        str(CANDIDATES),
        "--exercise-plan-json",
        str(PLAN),
        "--exercise-motion-contract-cache-dir",
        str(CACHE_DIR),
        "--pre-reconstruction-source-validation",
        "--workspace",
        str(tmp_path / "workspace"),
    ]
    request = cli.build_bake_and_rank_request(cli.build_parser().parse_args(argv))
    manifest = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    exercise = manifest["exercises"][0]
    ranked = bake_and_rank.RankedCandidate(
        0,
        0,
        exercise["exerciseId"],
        exercise["exerciseName"],
        exercise["slug"],
        exercise["candidates"][0],
    )
    no_model = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("model call attempted"))

    resolver = bake_and_rank.build_exercise_motion_contract_resolver(
        request=request, caption_images=no_model
    )
    contract = resolver(ranked)

    assert contract is not None
    assert contract["bilateralExecution"] == {}
    assert contract["bilateralExecutionAuthority"] == "structured_definition"
    assert AUTHORITATIVE_CACHE_FILE.name in str(contract.get("cachePath") or "")
    assert contract["exerciseMotionContractStatus"] == "reused_contract_cache"
    bake_and_rank.require_current_source_contract(contract, ranked)
