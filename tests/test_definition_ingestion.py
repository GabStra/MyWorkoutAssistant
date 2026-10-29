import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from exercise_motion_pkg.definition_ingestion import (
    prepare_workout_plan_definition_readiness,
    require_definition_readiness,
)
from exercise_motion_pkg.definition_review import _target_fingerprint, approve_definition_review
from exercise_motion_pkg.youtube import load_workout_plan_exercises


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _approved_registry(tmp_path: Path) -> tuple[Path, Path, Path]:
    source_plan = tmp_path / "source-plan.json"
    _write(source_plan, {"exerciseDefinitions": [
        {"id": "pull", "name": "High Pull", "equipmentId": "bar", "motionContext": {"keep": "this"}},
        {"id": "squat", "name": "Back Squat", "motionContext": {}},
    ]})
    target = load_workout_plan_exercises(source_plan)[0]
    review_path = tmp_path / "high-pull-review.json"
    review = {
        "schemaVersion": 1,
        "status": "pending",
        "exerciseId": target.exercise_id,
        "exerciseName": target.name,
        "targetFingerprint": _target_fingerprint(source_plan, target),
        "targetContext": asdict(target),
        "proposalContractSha256": "contract-hash",
        "definition": {
            "definingAction": "Extend the hips and legs, then pull the bar to the upper chest.",
            "completionMode": "distinct_end_state",
            "variantQualifiers": ["clean grip"],
        },
    }
    _write(review_path, review)
    review_hash = hashlib.sha256(review_path.read_bytes()).hexdigest()
    approved_plan = tmp_path / "approved-plan.json"
    definition = {
        **review["definition"],
        "review": {
            "status": "approved",
            "approvedAtUtc": "2026-10-23T12:00:00Z",
            "reviewArtifactSha256": review_hash,
            "proposalContractSha256": "contract-hash",
        },
    }
    registry = {"exerciseDefinitions": [
        {
            "id": "pull",
            "name": "High Pull",
            "equipmentId": "bar",
            "motionContext": {"keep": "this", "exerciseDefinition": definition},
        },
    ]}
    _write(approved_plan, registry)
    return source_plan, approved_plan, review_path


def test_exact_approved_definition_is_reused_and_unresolved_stays_unresolved(tmp_path):
    source_plan, registry, _review_path = _approved_registry(tmp_path)

    effective, entries, report = prepare_workout_plan_definition_readiness(
        plan_path=source_plan,
        approved_registry_path=registry,
    )

    assert report["readyCount"] == 1
    assert report["unresolvedCount"] == 1
    assert report["approvedDefinitionsReused"] == [{
        "exerciseId": "pull",
        "exerciseName": "High Pull",
        "definitionSource": "approved_registry",
    }]
    assert entries[0].motion_context["exerciseDefinition"]["review"]["status"] == "approved"
    assert "exerciseDefinition" not in entries[1].motion_context
    assert report["unresolvedReviewQueue"][0]["exerciseId"] == "squat"
    with pytest.raises(ValueError, match="1 selected exercise"):
        require_definition_readiness(report)


def test_normalized_review_proposal_is_reused_without_rewriting_review_artifact(tmp_path):
    source_plan, _registry, review_path = _approved_registry(tmp_path)
    review_bytes = review_path.read_bytes()
    review = json.loads(review_bytes)
    review["definition"]["definingAction"] = "  Extend the hips and legs, then pull the bar to the upper chest.  "
    review["definition"]["variantQualifiers"] = ["  clean grip  "]
    review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    approved_review_bytes = review_path.read_bytes()
    registry = tmp_path / "approved-normalized-plan.json"

    approve_definition_review(
        plan_path=source_plan,
        exercise_id="pull",
        review_path=review_path,
        output_path=registry,
    )
    _effective, _entries, report = prepare_workout_plan_definition_readiness(
        plan_path=source_plan,
        approved_registry_path=registry,
    )

    assert report["readyCount"] == 1
    assert report["unresolvedCount"] == 1
    assert review_path.read_bytes() == approved_review_bytes
    assert review_bytes != approved_review_bytes


def test_explicit_approved_phase_graph_is_reused_only_when_review_hash_matches(tmp_path):
    source_plan, _registry, review_path = _approved_registry(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["definition"]["requiredPhases"] = ["Pull from floor", "Receive at upper chest"]
    _write(review_path, review)
    registry = tmp_path / "approved-phases-plan.json"
    approve_definition_review(
        plan_path=source_plan,
        exercise_id="pull",
        review_path=review_path,
        output_path=registry,
    )

    _effective, _entries, report = prepare_workout_plan_definition_readiness(
        plan_path=source_plan,
        approved_registry_path=registry,
    )
    assert report["readyCount"] == 1
    assert report["unresolvedCount"] == 1

    payload = json.loads(registry.read_text(encoding="utf-8"))
    definition = payload["exerciseDefinitions"][0]["motionContext"]["exerciseDefinition"]
    definition["requiredPhases"] = ["Unreviewed phase graph"]
    _write(registry, payload)
    _effective, _entries, mismatched_report = prepare_workout_plan_definition_readiness(
        plan_path=source_plan,
        approved_registry_path=registry,
    )
    assert mismatched_report["readyCount"] == 0
    assert mismatched_report["unresolvedReviewQueue"][0]["reason"] == (
        "approved_definition_differs_from_reviewed_proposal"
    )


def test_review_proposal_with_extra_fields_is_not_reused(tmp_path):
    source_plan, registry, review_path = _approved_registry(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["definition"]["unreviewedExtra"] = "must not be ignored"
    _write(review_path, review)
    definition = json.loads(registry.read_text(encoding="utf-8"))
    approved = definition["exerciseDefinitions"][0]["motionContext"]["exerciseDefinition"]
    approved["review"]["reviewArtifactSha256"] = hashlib.sha256(review_path.read_bytes()).hexdigest()
    _write(registry, definition)

    _effective, _entries, report = prepare_workout_plan_definition_readiness(
        plan_path=source_plan,
        approved_registry_path=registry,
    )

    assert report["readyCount"] == 0
    assert report["unresolvedReviewQueue"][0]["reason"] == "approved_definition_review_proposal_invalid"


def test_target_change_does_not_reuse_approved_definition(tmp_path):
    source_plan, registry, _review_path = _approved_registry(tmp_path)
    payload = json.loads(source_plan.read_text())
    payload["exerciseDefinitions"][0]["equipmentId"] = "different-bar"
    _write(source_plan, payload)

    _effective, _entries, report = prepare_workout_plan_definition_readiness(
        plan_path=source_plan,
        approved_registry_path=registry,
    )

    assert report["readyCount"] == 0
    assert report["unresolvedReviewQueue"][0]["reason"] == "approved_definition_target_fingerprint_mismatch"


def test_pending_review_is_listed_but_never_applied(tmp_path):
    source_plan, _registry_with_approval, review_path = _approved_registry(tmp_path)
    registry = tmp_path / "registry-without-approval.json"
    _write(registry, {"exerciseDefinitions": [{
        "id": "pull", "name": "High Pull", "equipmentId": "bar", "motionContext": {"keep": "this"},
    }]})
    review = json.loads(review_path.read_text())
    review["status"] = "pending"
    _write(review_path, review)

    effective, entries, report = prepare_workout_plan_definition_readiness(
        plan_path=source_plan,
        approved_registry_path=registry,
    )

    assert "exerciseDefinition" not in entries[0].motion_context
    assert "exerciseDefinition" not in effective["exerciseDefinitions"][0]["motionContext"]
    queued = next(item for item in report["unresolvedReviewQueue"] if item["exerciseId"] == "pull")
    assert queued["cachedDraft"]["status"] == "pending_review"


@pytest.mark.parametrize("source", ["llm", "model_generated", "draft"])
def test_structured_generated_draft_without_explicit_approval_is_unresolved(tmp_path, source):
    plan = tmp_path / "draft.json"
    _write(plan, {"exerciseDefinitions": [{
        "id": "pull",
        "name": "High Pull",
        "motionContext": {
            "exerciseDefinition": {
                "definingAction": "Pull the bar upward.",
                "completionMode": "distinct_end_state",
                "source": source,
            },
        },
    }]})

    _effective, _entries, report = prepare_workout_plan_definition_readiness(plan_path=plan)

    assert report["readyCount"] == 0
    assert report["unresolvedReviewQueue"][0]["reason"] == "missing_or_untrusted_explicit_action_definition"


def test_explicit_manual_definition_remains_ready_without_registry(tmp_path):
    plan = tmp_path / "manual.json"
    _write(plan, {"exerciseDefinitions": [{
        "id": "pull",
        "name": "High Pull",
        "motionContext": {
            "exerciseDefinition": {
                "definingAction": "Pull the bar upward.",
                "completionMode": "distinct_end_state",
                "source": "manual",
            },
        },
    }]})

    _effective, _entries, report = prepare_workout_plan_definition_readiness(plan_path=plan)

    assert report["readyCount"] == 1
    assert report["readinessByExerciseId"]["pull"]["definitionSource"] == "input_plan"


def test_list_cli_writes_effective_plan_and_readiness_report(tmp_path, monkeypatch):
    from exercise_motion_pkg.cli import main

    source_plan, registry, _review_path = _approved_registry(tmp_path)
    effective_path = tmp_path / "effective-plan.json"
    report_path = tmp_path / "readiness.json"
    list_path = tmp_path / "list.json"
    monkeypatch.setattr("sys.argv", [
        "exercise-motion", "list-workout-plan-exercises",
        "--workout-plan-json", str(source_plan),
        "--approved-exercise-definitions-json", str(registry),
        "--definition-effective-plan-json", str(effective_path),
        "--definition-readiness-report-json", str(report_path),
        "--out-json", str(list_path),
    ])

    main()

    effective = json.loads(effective_path.read_text())
    report = json.loads(report_path.read_text())
    listed = json.loads(list_path.read_text())
    assert effective["exerciseDefinitions"][0]["motionContext"]["exerciseDefinition"]["review"]["status"] == "approved"
    assert "exerciseDefinition" not in effective["exerciseDefinitions"][1]["motionContext"]
    assert report["effectivePlanPath"] == str(effective_path.resolve())
    assert report["readyCount"] == 1 and report["unresolvedCount"] == 1
    assert listed["definitionReadiness"]["approvedDefinitionsReused"] == report["approvedDefinitionsReused"]


def test_find_youtube_cli_blocks_unresolved_before_discovery(tmp_path, monkeypatch):
    from exercise_motion_pkg.cli import main

    plan = tmp_path / "unresolved.json"
    out = tmp_path / "candidates.json"
    _write(plan, {"exerciseDefinitions": [{"id": "pull", "name": "High Pull"}]})
    monkeypatch.setattr("sys.argv", [
        "exercise-motion", "find-youtube-videos",
        "--workout-plan-json", str(plan),
        "--out-json", str(out),
    ])

    with pytest.raises(ValueError, match="preflight blocked discovery"):
        main()
    assert not out.exists()
