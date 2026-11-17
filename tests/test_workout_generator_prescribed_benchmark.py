"""Controlled, provider-free parity and measured local-run checks."""

import copy
import hashlib
import json
import math
import os
import time
from pathlib import Path

from workout_generator_pkg import api_client, generation_pipeline, plan_review
from workout_generator_pkg.planning_tools import confirmed_draft, library_fingerprint
from workout_generator_pkg.prescribed_plan import _hash, run_prescribed_plan
from workout_generator_pkg.usage_reporting import build_workflow_metrics, compare_workflow_metrics


def _approved_small_case(monkeypatch):
    from test_workout_generator_compiler_export import confirmed_recipe

    equipment, messages = confirmed_recipe(monkeypatch)
    snapshot = confirmed_draft(messages, equipment, require_confirmation=True)
    return equipment, snapshot["planIndex"], snapshot.get("requirements", {})


def _exercise_projection(exercise):
    set_fields = ("type", "reps", "weight", "additionalWeight", "timeInMillis", "timeInSeconds", "note")
    return {
        "name": exercise.get("nameOverride") or exercise["name"],
        "notes": exercise.get("notes"),
        "placementNotes": exercise.get("placementNotes"),
        "exerciseType": exercise.get("exerciseType"),
        "minReps": exercise.get("minReps"),
        "maxReps": exercise.get("maxReps"),
        "sets": [{field: item[field] for field in set_fields if field in item}
                 for item in exercise.get("sets", [])],
    }


def _package_projection(path):
    package = json.loads(Path(path).read_text(encoding="utf-8"))
    workouts = []
    for workout in package["workouts"]:
        components = []
        for component in workout["workoutComponents"]:
            if component["type"] == "Exercise":
                components.append({"type": "Exercise", **_exercise_projection(component)})
            elif component["type"] == "Superset":
                components.append({
                    "type": "Superset",
                    "exercises": [_exercise_projection(item) for item in component["exercises"]],
                    "restSecondsByMember": [component.get("restSecondsByExercise", {}).get(item["id"], 0)
                                             for item in component["exercises"]],
                })
            elif component["type"] == "Rest":
                components.append({"type": "Rest", "timeInSeconds": component["timeInSeconds"]})
        workouts.append({"name": workout["name"], "components": components})
    return {"name": package["name"], "workouts": workouts}


def _assert_prescribed_sets_do_not_reapply_history(path):
    package = json.loads(Path(path).read_text(encoding="utf-8"))
    for workout in package["workouts"]:
        for component in workout["workoutComponents"]:
            exercises = ([component] if component["type"] == "Exercise" else
                         component.get("exercises", []) if component["type"] == "Superset" else [])
            for exercise in exercises:
                for set_item in exercise.get("sets", []):
                    if set_item.get("type") != "RestSet":
                        assert set_item.get("shouldReapplyHistoryToSet") is False


def _history_reapply_flags(path):
    package = json.loads(Path(path).read_text(encoding="utf-8"))
    flags = []
    for workout in package["workouts"]:
        for component in workout["workoutComponents"]:
            exercises = ([component] if component["type"] == "Exercise" else
                         component.get("exercises", []) if component["type"] == "Superset" else [])
            for exercise in exercises:
                flags.extend(set_item.get("shouldReapplyHistoryToSet")
                             for set_item in exercise.get("sets", [])
                             if set_item.get("type") != "RestSet")
    return flags


def _identity_for_json_source(source_path, equipment):
    settings = {"model": {}, "allowEducatedLoadGuesses": True}
    return {
        "source": hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
        "library": library_fingerprint(equipment),
        "history": _hash(None),
        "model": _hash({}),
        "settings": _hash(settings),
    }


def _measured_receipt(metrics_path):
    receipt = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
    assert receipt["validPackage"] is True
    assert receipt["totalWallSeconds"] > 0
    assert receipt["latestRunWallSeconds"] == receipt["totalWallSeconds"]
    assert receipt["attemptCountForSource"] >= 1
    assert receipt["cumulativeRunWallSecondsForSource"] >= receipt["latestRunWallSeconds"]
    assert receipt["attemptReceipt"]
    assert Path(receipt["attemptReceipt"]).is_file()
    assert receipt["apiCalls"] == 0
    assert all(value == 0 for value in receipt["tokenTotals"].values())
    assert receipt["stageWallSeconds"]
    assert all(math.isfinite(value) and value >= 0 for value in receipt["stageWallSeconds"].values())
    return receipt


def test_json_prescribed_and_reviewed_workflow_replay_preserve_the_same_recipe_without_providers(
    tmp_path, monkeypatch,
):
    from test_workout_generator_compiler_export import confirmed_recipe

    equipment, messages = confirmed_recipe(monkeypatch)
    snapshot = confirmed_draft(messages, equipment, require_confirmation=True)
    plan_index = snapshot["planIndex"]
    audit_requirements = snapshot.get("requirements", {})
    source_file = tmp_path / "plan.json"
    source_file.write_text(json.dumps(plan_index, ensure_ascii=False), encoding="utf-8")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("PlanIndex JSON must bypass source extraction and providers.")

    monkeypatch.setattr(api_client, "chat_call", forbidden)
    monkeypatch.setattr(plan_review, "_review_call", forbidden)
    extraction_calls = []
    started = time.perf_counter()
    direct = generation_pipeline.execute_workout_generation(
        None, messages, provided_equipment=equipment, script_dir=str(tmp_path / "reviewed"),
    )
    reviewed_replay_wall = time.perf_counter() - started
    assert direct["success"], direct.get("error")

    prescribed = run_prescribed_plan(
        source_file, equipment, equipment, state_dir=tmp_path / "state",
        output_dir=tmp_path / "prescribed", output_file=tmp_path / "prescribed.json",
        extract=lambda *args: extraction_calls.append(args) or forbidden(),
        model_settings={}, audit_requirements=audit_requirements,
    )
    assert prescribed["success"], prescribed.get("error")
    assert extraction_calls == []
    _assert_prescribed_sets_do_not_reapply_history(prescribed["filepath"])
    assert all(flag is None or flag is True for flag in _history_reapply_flags(direct["filepath"]))
    direct_exercise = json.loads(Path(direct["filepath"]).read_text(encoding="utf-8"))[
        "workouts"][0]["workoutComponents"][0]
    prescribed_exercise = json.loads(Path(prescribed["filepath"]).read_text(encoding="utf-8"))[
        "workouts"][0]["workoutComponents"][0]
    assert direct_exercise["progressionMode"] == "AUTO_REGULATION"
    assert prescribed_exercise["progressionMode"] == "OFF"
    assert _package_projection(direct["filepath"]) == _package_projection(prescribed["filepath"])

    prescribed_receipt = _measured_receipt(
        tmp_path / "state" / "workflow_metrics.json")
    open_receipt = build_workflow_metrics(
        [], total_wall_seconds=reviewed_replay_wall,
        stage_times={"reviewedWorkflowReplay": reviewed_replay_wall},
        valid_package=True, identity=_identity_for_json_source(source_file, equipment),
    )
    open_receipt["benchmarkLabel"] = "reviewed existing workflow replay"
    open_receipt["measurementScope"] = (
        "Timed execute_workout_generation using a previously confirmed recipe; the fixture's "
        "single deterministic review stub ran before timing and is not an API call."
    )
    comparison = compare_workflow_metrics(prescribed_receipt, open_receipt)
    assert comparison["controlledComparison"] is True
    assert comparison["identityMismatches"] == []
    report_dir = os.environ.get("PRESCRIBED_BENCHMARK_OUTPUT_DIR")
    if report_dir:
        report_root = Path(report_dir)
        report_root.mkdir(parents=True, exist_ok=True)
        attempt_path = Path(prescribed_receipt["attemptReceipt"])
        retained_attempt = report_root / "attempts" / attempt_path.name
        retained_attempt.parent.mkdir(parents=True, exist_ok=True)
        attempt_snapshot = json.loads(attempt_path.read_text(encoding="utf-8"))
        attempt_snapshot["attemptReceipt"] = str(retained_attempt.resolve())
        retained_attempt.write_text(json.dumps(attempt_snapshot, indent=2), encoding="utf-8")
        source_index = attempt_path.parent / "index.json"
        (retained_attempt.parent / "index.json").write_bytes(source_index.read_bytes())
        prescribed_receipt["attemptReceipt"] = str(retained_attempt.resolve())
        (report_root / "prescribed_metrics.json").write_text(
            json.dumps(prescribed_receipt, indent=2), encoding="utf-8")
        (report_root / "reviewed_workflow_metrics.json").write_text(
            json.dumps(open_receipt, indent=2), encoding="utf-8")
        (report_root / "comparison.json").write_text(
            json.dumps(comparison, indent=2), encoding="utf-8")


def test_text_source_runs_one_stub_extraction_cold_and_none_on_resume(tmp_path, monkeypatch):
    equipment, _, _ = _approved_small_case(monkeypatch)
    source_file = tmp_path / "prescription.txt"
    source_file.write_text("Push-Up 5 x 8-10 reps @RPE 2\nRest 90s\n", encoding="utf-8")
    extraction_calls = []

    def extract(text, spans):
        extraction_calls.append(text)
        exercise_key = next(key for key, line in spans.items() if line.startswith("Push-Up"))
        rest_key = next(key for key, line in spans.items() if line.casefold().startswith("rest"))
        return {
            "planName": "Synthetic prescribed plan",
            "unresolved": [],
            "exercises": [{"sourceKey": exercise_key, "rawName": "Push-Up",
                           "evidenceKeys": [exercise_key]}],
            "workouts": [{"name": "Day A", "blocks": [{"type": "straight",
                "exerciseKeys": [exercise_key], "restKey": rest_key}]}],
        }

    def forbidden(*_args, **_kwargs):
        raise AssertionError("The injected text-extraction stub must avoid provider calls.")

    monkeypatch.setattr(api_client, "chat_call", forbidden)
    monkeypatch.setattr(plan_review, "_review_call", forbidden)
    state_dir = tmp_path / "state"
    output_file = tmp_path / "package.json"
    first = run_prescribed_plan(
        source_file, equipment, equipment, extract=extract, state_dir=state_dir,
        output_dir=tmp_path, output_file=output_file, model_settings={},
    )
    assert first["success"], first.get("error")
    assert len(extraction_calls) == 1
    _assert_prescribed_sets_do_not_reapply_history(first["filepath"])
    first_projection = _package_projection(first["filepath"])

    resumed = run_prescribed_plan(
        source_file, equipment, equipment, extract=extract, state_dir=state_dir,
        output_dir=tmp_path, output_file=output_file, model_settings={},
    )
    assert resumed["success"], resumed.get("error")
    assert len(extraction_calls) == 1
    assert _package_projection(resumed["filepath"]) == first_projection
    receipt = _measured_receipt(state_dir / "workflow_metrics.json")
    assert "sourceFacts" in receipt["reusedStages"]
    assert receipt["attemptCountForSource"] == 2
    assert receipt["elapsedSinceFirstAttemptSecondsForSource"] >= receipt["cumulativeRunWallSecondsForSource"]
    assert "includes idle time between attempts" in receipt["elapsedSinceFirstAttemptNote"]

    repaired_plan = json.loads(Path(resumed["plan_file"]).read_text(encoding="utf-8"))
    direct = generation_pipeline.compile_plan_index(
        repaired_plan, equipment, output_dir=str(tmp_path / "direct"),
    )
    assert direct["success"], direct.get("error")
    assert _package_projection(direct["filepath"]) == first_projection


def test_four_ordered_phase_sessions_keep_occurrence_targets_without_weekly_floors(
    tmp_path, monkeypatch,
):
    equipment, plan_index, _ = _approved_small_case(monkeypatch)
    base_exercise = plan_index["exercises"][0]
    base_workout = plan_index["workouts"][0]
    phases = [
        ("Phase 1 - entry", 8, 2, "Phase 1 occurrence cue."),
        ("Phase 2 - build", 10, 2, "Phase 2 occurrence cue."),
        ("Phase 3 - peak", 12, 3, "Phase 3 occurrence cue."),
        ("Phase 4 - deload", 8, 1, "Phase 4 occurrence cue."),
    ]
    plan_index["auditTargets"] = {"weeklyEffectiveSets": {}, "perSessionEffectiveSets": {}}
    plan_index["exercises"] = []
    plan_index["workouts"] = []
    for index, (name, reps, work_sets, notes) in enumerate(phases):
        exercise_id = f"EXERCISE_{index}"
        workout_id = f"WORKOUT_{index}"
        exercise = copy.deepcopy(base_exercise)
        exercise.update(id=exercise_id, minReps=reps, maxReps=reps,
                        numWorkSets=work_sets, notes=notes)
        exercise.pop("targetSetPrescriptions", None)
        plan_index["exercises"].append(exercise)
        workout = copy.deepcopy(base_workout)
        workout.update(id=workout_id, name=name, exerciseIds=[exercise_id],
                       restToNextSeconds=[0], supersetGroups=[])
        plan_index["workouts"].append(workout)

    result = generation_pipeline.compile_plan_index(
        plan_index, equipment, output_dir=str(tmp_path),
    )
    assert result["success"], result.get("error")
    package = json.loads(Path(result["filepath"]).read_text(encoding="utf-8"))
    report = json.loads(Path(result["filepath"]).with_suffix(".audit.json").read_text(encoding="utf-8"))
    assert [workout["name"] for workout in package["workouts"]] == [phase[0] for phase in phases]
    assert report["targets"]["weeklyEffectiveSets"] == {}
    assert report["targets"]["perSessionEffectiveSets"] == {}
    exercises = [workout["workoutComponents"][0] for workout in package["workouts"]]
    assert [sum(item["type"] != "RestSet" for item in exercise["sets"]) for exercise in exercises] == [2, 2, 3, 1]
    assert [exercise["sets"][0]["reps"] for exercise in exercises] == [8, 10, 12, 8]
    assert [exercise["notes"] for exercise in exercises] == [phase[3] for phase in phases]
