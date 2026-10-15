import copy
import json
from dataclasses import replace

import pytest

from workout_generator_pkg.planning_tools import (
    audit_workout_plan, confirmed_draft, set_workout_requirements, planning_tool_failure,
)


def planning_case():
    equipment = {"equipments": [], "accessoryEquipments": [], "exerciseDefinitions": [{
        "id": "press", "name": "Push-Up", "exerciseType": "BODY_WEIGHT", "equipmentId": None,
        "bodyWeightPercentage": 65, "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_CHEST"], "secondaryMuscleGroups": ["BACK_TRICEPS"],
        "exerciseCategory": "MODERATE_COMPOUND",
    }]}
    requirements = {"auditTargets": {"weeklyEffectiveSets": {"chest": {"minimum": 5, "maximum": 6}},
                    "perSessionEffectiveSets": {"chest": {"minimum": 5, "maximum": 6}},
                    "maximumSessionSeconds": 1000}, "sessionsPerWeek": 1, "notes": "Working sets at 1–2 RIR."}
    stored = set_workout_requirements(requirements, [{"role": "user", "content": "Plan 5-6 chest sets"}])
    draft = {"name": "Program", "requirementsId": stored["requirementsId"], "workouts": [{
        "name": "Day A", "description": "Full body", "timesCompletedInAWeek": 1,
        "exercises": [{"definition_id": "LIBRARY_0", "numWorkSets": 5, "minReps": 8, "maxReps": 10,
                       "durationSeconds": None, "restBetweenSetsSeconds": 90, "restAfterExerciseSeconds": 0,
                       "superset": None, "restAfterSupersetExerciseSeconds": 0,
                       "intraSetRestInSeconds": None, "generateWarmUpSets": False, "placementNotes": "Controlled reps."}],
    }]}
    return equipment, requirements, stored, draft


def requirement_messages(stored):
    return [{"role": "user", "content": "Plan 5-6 chest sets"},
            {"role": "assistant", "tool_calls": [{"id": "requirements", "function": {"name": "set_workout_requirements"}}]},
            {"role": "tool", "tool_call_id": "requirements", "content": json.dumps(stored)}]


def approved_messages(stored, result):
    return requirement_messages(stored) + [
        {"role": "assistant", "tool_calls": [{"id": "draft", "function": {"name": "audit_workout_plan"}}]},
        {"role": "tool", "tool_call_id": "draft", "content": json.dumps(result)},
        {"role": "assistant", "content": result["preview"], "canonicalDraftPreview": result["draftId"]},
        {"role": "user", "content": "CONFIRM GENERATE"},
    ]


def test_requirements_are_separate_and_frozen_during_repair():
    _, requirements, stored, _ = planning_case()
    changed = copy.deepcopy(requirements)
    changed["auditTargets"]["weeklyEffectiveSets"] = {}
    messages = requirement_messages(stored)
    with pytest.raises(ValueError, match="frozen"):
        set_workout_requirements(changed, messages)
    messages.append({"role": "user", "content": "Remove weekly volume target"})
    updated = set_workout_requirements(changed, messages)
    assert updated["requirementsId"] != stored["requirementsId"]
    assert "Weekly effective sets: unspecified" in updated["requirementsPreview"]


def test_single_draft_audits_real_reps_rests_and_roles_then_renders():
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result["passed"]
    assert result["audit"]["workouts"][0]["estimatedSeconds"] == 810
    assert result["audit"]["weeklyVolume"]["triceps"]["effective"] == 2.5
    assert "| 1 | Push-Up | 5 | 8–10 | 90s |" in result["preview"]
    assert "Estimated duration: 13.5 min" in result["preview"]
    approved = confirmed_draft(approved_messages(stored, result), equipment)
    assert approved["planIndex"] == result["planIndex"]
    approved["planIndex"]["exercises"][0]["numWorkSets"] = 1
    assert result["planIndex"]["exercises"][0]["numWorkSets"] == 5


def test_volume_and_time_failures_return_feedback_without_a_preview():
    equipment, requirements, stored, draft = planning_case()
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 3
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert not failed["passed"] and "preview" not in failed
    assert any("chest: 3 effective sets" in issue for issue in failed["audit"]["issues"])
    requirements["auditTargets"]["maximumSessionSeconds"] = 500
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 5
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert not failed["passed"] and any("810s exceeds 500s" in issue for issue in failed["audit"]["issues"])


def test_confirmation_requires_display_current_library_settings_and_successful_replacement():
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    messages = approved_messages(stored, result)
    with pytest.raises(ValueError, match="displayed"):
        confirmed_draft(messages[:5], equipment)
    changed = copy.deepcopy(equipment)
    changed["exerciseDefinitions"][0]["muscleGroups"] = ["FRONT_DELTOIDS"]
    with pytest.raises(ValueError, match="library or equipment changed"):
        confirmed_draft(messages, changed)
    with pytest.raises(ValueError, match="Calibration settings"):
        confirmed_draft(messages, equipment, False)
    messages.append({"role": "user", "content": "Change the plan"})
    # Conversation text alone does not mutate the structured plan.
    assert confirmed_draft(messages, equipment)["planIndex"] == result["planIndex"]
    messages.extend([
        {"role": "assistant", "tool_calls": [{"id": "replacement", "function": {"name": "audit_workout_plan"}}]},
        {"role": "tool", "tool_call_id": "replacement", "content": '{"passed":false,"errors":[]}'},
    ])
    with pytest.raises(ValueError, match="passing"):
        confirmed_draft(messages, equipment)


def test_prescriptions_have_unique_occurrence_ids_and_superset_rounds():
    equipment, requirements, stored, draft = planning_case()
    requirements["auditTargets"]["weeklyEffectiveSets"] = {}
    requirements["auditTargets"]["perSessionEffectiveSets"] = {}
    requirements["auditTargets"]["maximumSessionSeconds"] = 4500
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    first = draft["workouts"][0]["exercises"][0]
    first.update(superset="A", restAfterSupersetExerciseSeconds=40)
    second = copy.deepcopy(first)
    second["restAfterSupersetExerciseSeconds"] = 75
    draft["workouts"][0]["exercises"].append(second)
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result["passed"]
    assert [e["id"] for e in result["planIndex"]["exercises"]] == ["EXERCISE_0", "EXERCISE_1"]
    assert result["audit"]["workouts"][0]["timing"]["restSeconds"] == 5 * (40 + 75) - 75
    second["numWorkSets"] = 3
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert not failed["passed"] and "shortest member" in failed["audit"]["issues"][0]


def test_pipeline_uses_approved_draft_without_summarizing_or_replanning(tmp_path):
    from workout_generator_pkg.deps import resolve_pipeline_deps
    from workout_generator_pkg.generation_pipeline import execute_workout_generation

    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    messages = approved_messages(stored, result)
    emitted = []

    def no_planning(*_args, **_kwargs):
        pytest.fail("The approved draft must not be summarized or replanned")

    def emission(items, *_args, **_kwargs):
        plan = items[0][1]["plan_index"]
        emitted.append(plan)
        assert plan["exercises"][0]["numWorkSets"] == 5
        assert plan["exercises"][0]["maxReps"] == 10
        assert plan["auditTargets"] == stored["requirements"]["auditTargets"]
        raise RuntimeError("Stopped at emission checkpoint")

    deps = replace(resolve_pipeline_deps(), test_connection=lambda *_a, **_k: (True, None),
                   hash_conversation=lambda *_: "hash", summarize_conversation=no_planning, generate_index=no_planning,
                   save_generation_progress=lambda *_a, **_k: ("progress.json", 0), parallel_emit_items=emission)
    exported = execute_workout_generation(None, messages, provided_equipment=equipment,
                                         script_dir=str(tmp_path), deps=deps, force_use_reasoner=False)
    assert emitted and "emission checkpoint" in exported["error"]


def test_uuid_equipment_validation_keeps_original_identity_and_exact_total_loads():
    equipment, _, stored, draft = planning_case()
    equipment_id = "11111111-1111-4111-8111-111111111111"
    equipment["equipments"] = [{"id": equipment_id, "name": "Barbell", "type": "BARBELL", "barWeight": 10.0, "plates": []}]
    definition = equipment["exerciseDefinitions"][0]
    definition.update(exerciseType="WEIGHT", equipmentId=equipment_id, bodyWeightPercentage=None)
    item = draft["workouts"][0]["exercises"][0]
    item["targetSetPrescriptions"] = [{"workSetIndex": i, "reps": 10, "weight": 10.0} for i in range(5)]
    original = copy.deepcopy(equipment)
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result["passed"] and equipment == original
    assert result["planIndex"]["exercises"][0]["equipmentId"] == equipment_id
    assert result["planIndex"]["exercises"][0]["targetSetPrescriptions"] == item["targetSetPrescriptions"]
    assert "Exact work-set targets" in result["preview"]


def test_timed_draft_uses_real_interval_duration():
    equipment, requirements, _, draft = planning_case()
    requirements.update(sessionsPerWeek=1, auditTargets={"weeklyEffectiveSets": {}, "perSessionEffectiveSets": {}, "maximumSessionSeconds": 1000})
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    equipment["exerciseDefinitions"][0].update(exerciseType="COUNTDOWN", muscleGroups=[], secondaryMuscleGroups=[],
                                               exerciseCategory=None, bodyWeightPercentage=None)
    item = draft["workouts"][0]["exercises"][0]
    item.update(numWorkSets=2, minReps=None, maxReps=None, durationSeconds=30, restBetweenSetsSeconds=60)
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result["passed"]
    assert result["audit"]["workouts"][0]["estimatedSeconds"] == 420
    assert "| 2 | 30s | 60s |" in result["preview"]


def test_status_question_and_identical_submission_reuse_audited_draft(monkeypatch):
    from workout_generator_pkg import planning_tools

    equipment, requirements, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    messages = approved_messages(stored, result)
    messages.append({"role": "user", "content": "What does RIR mean?"})
    assert confirmed_draft(messages, equipment)["draftId"] == result["draftId"]
    monkeypatch.setattr(planning_tools, "audit_workout_package", lambda *_: pytest.fail("Identical draft should not be re-audited"))
    cached = audit_workout_plan(draft, equipment, messages)
    assert cached["cached"] and cached["draftId"] == result["draftId"]
    unchanged = set_workout_requirements(requirements, messages)
    assert unchanged["cached"] and unchanged["requirementsId"] == stored["requirementsId"]
    messages.extend([
        {"role": "assistant", "tool_calls": [{"id": "cached", "function": {"name": "audit_workout_plan"}}]},
        {"role": "tool", "tool_call_id": "cached", "content": json.dumps(cached)},
    ])
    assert confirmed_draft(messages, equipment)["draftId"] == result["draftId"]


def test_changed_requirements_invalidate_previous_successful_draft():
    equipment, requirements, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    messages = approved_messages(stored, result)
    messages.append({"role": "user", "content": "Limit sessions to 10 minutes"})
    requirements["auditTargets"]["maximumSessionSeconds"] = 600
    updated = set_workout_requirements(requirements, messages)
    messages.extend([
        {"role": "assistant", "tool_calls": [{"id": "new-goals", "function": {"name": "set_workout_requirements"}}]},
        {"role": "tool", "tool_call_id": "new-goals", "content": json.dumps(updated)},
    ])
    with pytest.raises(ValueError, match="Requirements changed"):
        confirmed_draft(messages, equipment)


def test_audit_feedback_has_codes_actuals_paths_and_repair_instructions():
    equipment, _, stored, draft = planning_case()
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 3
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    error = next(e for e in failed["errors"] if e["scope"] == "per_session")
    assert error["code"] == "volume_below_target" and error["actual"] == 3
    assert error["minimum"] == 5 and error["difference"] == 2
    assert error["path"] == "/workouts/0/exercises"
    assert "preserve" in error["repair"] and "re-audit" in error["repair"]
    draft["workouts"][0]["exercises"][0]["definition_id"] = "LIBRARY_999"
    with pytest.raises(ValueError) as captured:
        audit_workout_plan(draft, equipment, requirement_messages(stored))
    response = planning_tool_failure("audit_workout_plan", captured.value, draft)
    assert response["errors"][0]["code"] == "unknown_library_reference"
    assert response["errors"][0]["path"] == "/workouts/0/exercises/0/definition_id"
    assert "search_exercise_library" in response["errors"][0]["repair"]


def test_contract_and_execution_failures_use_same_error_envelope():
    from workout_generator_pkg.plan_contract import ContractIssue, ContractValidationError

    _, _, _, arguments = planning_case()
    failure = planning_tool_failure("audit_workout_plan", ContractValidationError("invalid contract", [
        ContractIssue("invalid_example", "Exercise 'EXERCISE_0' has an invalid prescription.")
    ]), arguments)
    assert not failure["passed"]
    error = failure["errors"][0]
    assert error["code"] == "invalid_example" and error["exerciseId"] == "EXERCISE_0"
    assert error["path"] == "/workouts/0/exercises/0" and error["repair"]
    execution = planning_tool_failure("audit_workout_plan", RuntimeError("unexpected failure"), arguments)
    assert execution["errors"][0]["code"] == "tool_execution_failed"
    assert "do not change the draft" in execution["errors"][0]["repair"]
