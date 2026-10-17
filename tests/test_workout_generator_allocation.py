import copy
import json
import pytest

from workout_generator_pkg.allocation import allocate_workout_sets, allocation_slots
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages


def _audited_messages(equipment, stored, draft):
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    messages.extend([
        {"role": "assistant", "tool_calls": [{"id": "audit", "function": {
            "name": "audit_workout_plan", "arguments": json.dumps(draft)}}]},
        {"role": "tool", "tool_call_id": "audit", "content": json.dumps(result)},
    ])
    return messages, result


def test_allocation_returns_minimal_patch_and_exact_numeric_summary():
    equipment, _, stored, draft = planning_case()
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 3
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 5, "maximum": 6}},
    }, equipment, messages)

    assert allocated["feasible"]
    assert allocated["patch"] == [{"op": "replace", "path": "/workouts/0/exercises/0/numWorkSets", "value": 5}]
    assert allocated["summary"]["weeklyEffectiveSets"]["chest"] == 5
    assert allocated["summary"]["sessions"][0]["estimatedSeconds"] == 810
    assert result["submittedDraft"]["workouts"][0]["exercises"][0]["numWorkSets"] == 3


def test_infeasible_volume_and_duration_reports_conflict_without_patch():
    equipment, requirements, _, draft = planning_case()
    requirements["auditTargets"]["maximumSessionSeconds"] = 500
    from workout_generator_pkg.planning_tools import set_workout_requirements
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 3
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 5, "maximum": 6}},
    }, equipment, messages)

    assert not allocated["feasible"]
    assert "No allocation satisfies" in allocated["reason"]
    assert "patch" not in allocated


@pytest.mark.parametrize('duration_limit', [None, 500])
@pytest.mark.parametrize('omitted_sets', [1, 2])
def test_infeasible_bounds_identify_omitted_slot_for_coupled_targets(duration_limit, omitted_sets):
    equipment, requirements, stored, draft = planning_case()
    requirements["auditTargets"]["weeklyEffectiveSets"] = {
        "glutes": {"minimum": 0, "maximum": 1},
        "shoulders": {"minimum": 0, "maximum": 1},
    }
    requirements["auditTargets"]["perSessionEffectiveSets"] = {}
    requirements["auditTargets"]["maximumSessionSeconds"] = duration_limit
    from workout_generator_pkg.planning_tools import set_workout_requirements
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    equipment["exerciseDefinitions"][0]["trainingMuscles"] = {
        "primary": ["chest", "glutes", "anteriorDelts"], "secondary": [],
    }
    equipment["exerciseDefinitions"].append({
        "id": "glute-shoulder", "name": "Glute Shoulder Compound", "exerciseType": "BODY_WEIGHT",
        "equipmentId": None, "bodyWeightPercentage": 65, "requiredAccessoryEquipmentIds": [],
        "muscleGroups": [], "secondaryMuscleGroups": [],
        "trainingMuscles": {"primary": ["glutes", "anteriorDelts"], "secondary": []},
        "exerciseCategory": "MODERATE_COMPOUND",
    })
    draft["workouts"][0]["exercises"].append({
        **copy.deepcopy(draft["workouts"][0]["exercises"][0]), "definition_id": "LIBRARY_1", "numWorkSets": omitted_sets,
    })
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 5, "maximum": 5}},
    }, equipment, messages)

    assert not allocated["feasible"]
    assert "does not establish" in allocated["reason"]
    json.dumps(allocated, allow_nan=False)
    if omitted_sets == 1:
        assert not any(item['slotId'] == 'SLOT_1' for item in allocated['allocationDiagnostics'])
        return
    omitted = next(item for item in allocated["allocationDiagnostics"] if item["slotId"] == "SLOT_1")
    assert omitted["currentSets"] == 2
    assert omitted["weeklyFrequency"] == 1
    assert omitted["effectiveCreditsPerSet"]["glutes"] == 1
    assert omitted["effectiveCreditsPerSet"]["shoulders"] == 1
    assert {item["target"] for item in omitted["couldAffect"]} == {
        "weekly:glutes", "weekly:shoulders", *(['duration:0'] if duration_limit else [])}
    if duration_limit:
        assert next(item['requestedRange'] for item in omitted['couldAffect']
                    if item['target'] == 'duration:0') == [None, duration_limit]
    assert "explicit bounds" in omitted["reason"]
    json.dumps(allocated, allow_nan=False)


def test_allocation_uses_actual_non_unit_weekly_frequency():
    equipment, requirements, _, draft = planning_case()
    requirements["sessionsPerWeek"] = 2
    requirements["auditTargets"]["weeklyEffectiveSets"]["chest"] = {"minimum": 10, "maximum": 12}
    from workout_generator_pkg.planning_tools import set_workout_requirements
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    draft["workouts"][0]["timesCompletedInAWeek"] = 2
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 3
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 5, "maximum": 6}},
    }, equipment, messages)

    assert allocated["feasible"]
    assert allocated["summary"]["weeklyEffectiveSets"]["chest"] == 10
    assert allocated["summary"]["completeWeek"] is True


def test_allocation_probes_downward_when_current_count_is_at_maximum():
    equipment, _, stored, draft = planning_case()
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 20
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 1, "maximum": 20}},
    }, equipment, messages)

    assert allocated["feasible"]
    assert allocated["patch"] == [{"op": "replace", "path": "/workouts/0/exercises/0/numWorkSets", "value": 6}]


def test_superset_occurrences_are_allocated_as_one_equal_count_group():
    equipment, requirements, stored, draft = planning_case()
    requirements["auditTargets"]["weeklyEffectiveSets"] = {}
    requirements["auditTargets"]["perSessionEffectiveSets"] = {}
    from workout_generator_pkg.planning_tools import set_workout_requirements
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    first = draft["workouts"][0]["exercises"][0]
    first.update(superset="A", restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=40)
    second = copy.deepcopy(first)
    second["numWorkSets"] = 3
    second["restAfterSupersetExerciseSeconds"] = 75
    draft["workouts"][0]["exercises"].append(second)
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 2, "maximum": 3}},
    }, equipment, messages)

    assert allocated["feasible"]
    updated = copy.deepcopy(draft)
    for op in allocated["patch"]:
        index = int(op["path"].split("/")[4])
        updated["workouts"][0]["exercises"][index]["numWorkSets"] = op["value"]
    assert [item["numWorkSets"] for item in updated["workouts"][0]["exercises"]] == [3, 3]
    assert {op["path"] for op in allocated["patch"]} == {
        "/workouts/0/exercises/0/numWorkSets"}


def test_exact_prescriptions_and_stale_slot_or_base_are_rejected():
    equipment, _, stored, draft = planning_case()
    exercise = draft["workouts"][0]["exercises"][0]
    exercise["targetSetPrescriptions"] = [
        {"workSetIndex": index, "reps": 9, "additionalWeight": 0} for index in range(5)]
    exercise["numWorkSets"] = 5
    messages, result = _audited_messages(equipment, stored, draft)

    allocation = {"requirementsId": stored["requirementsId"], "baseDraftId": result["currentDraftId"],
                  "boundsBySlot": {"SLOT_0": {"minimum": 4, "maximum": 4}}}
    rejected = allocate_workout_sets(allocation, equipment, messages)
    assert not rejected["feasible"]
    assert "exact set prescriptions" in rejected["reason"]

    allocation["boundsBySlot"] = {"SLOT_9": {"minimum": 1, "maximum": 2}}
    rejected = allocate_workout_sets(allocation, equipment, messages)
    assert not rejected["feasible"]
    assert "Unknown slot" in rejected["reason"]

    allocation["boundsBySlot"] = {}
    allocation["baseDraftId"] = "REVISION_stale"
    rejected = allocate_workout_sets(allocation, equipment, messages)
    assert not rejected["feasible"]
    assert "stale" in rejected["reason"]

    allocation["baseDraftId"] = result["currentDraftId"]
    payload = json.loads(messages[-1]["content"])
    payload["submittedDraft"]["requirementsId"] = "REQUIREMENTS_OLD"
    messages[-1]["content"] = json.dumps(payload)
    rejected = allocate_workout_sets(allocation, equipment, messages)
    assert not rejected["feasible"]
    assert "different requirements" in rejected["reason"]


def test_slot_references_are_deterministic_occurrence_ids():
    _, _, _, draft = planning_case()
    draft["workouts"].append(copy.deepcopy(draft["workouts"][0]))
    slots = allocation_slots(draft)
    assert list(slots) == ["SLOT_0", "SLOT_1"]
    assert slots["SLOT_1"]["path"] == "/workouts/1/exercises/0"
