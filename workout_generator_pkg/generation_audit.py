"""Deterministic programming audit and bounded prescription repair."""

import copy
import json

from .api_client import json_call_reasoner_only_with_loading
from .domain_ops import build_workout_structure
from .plan_contract import ContractValidationError, validate_plan_index_contract


MUSCLES = {
    "chest": {"FRONT_CHEST"},
    "back": {"BACK_UPPER_BACK"},
    "quads": {"FRONT_QUADRICEPS"},
    "hamstrings": {"BACK_HAMSTRING"},
    "glutes": {"BACK_GLUTEAL"},
    "shoulders": {"FRONT_DELTOIDS", "BACK_DELTOIDS"},
    "biceps": {"FRONT_BICEPS"},
    "triceps": {"FRONT_TRICEPS", "BACK_TRICEPS"},
    "calves": {"FRONT_CALVES", "BACK_CALVES"},
}
ASSUMPTIONS = {
    "secondsPerRep": 3, "generalWarmupSeconds": 300,
    "generatedRampUpSecondsPerExercise": 120, "transitionSeconds": 60,
    "primarySetCredit": 1, "secondaryCompoundSetCredit": 0.5,
}
# Pending calibration labels still represent prescribed work sets, not calibration executions.
EXCLUDED_VOLUME_CATEGORIES = {"WarmupSet", "CalibrationSet"}


def validate_audit_targets(targets):
    if not isinstance(targets, dict):
        raise ContractValidationError("PlanIndex must include auditTargets with agreed numeric goals (empty volume maps and null time limit when unspecified).")
    for field in ("weeklyEffectiveSets", "perSessionEffectiveSets"):
        values = targets.get(field, {})
        if not isinstance(values, dict) or set(values) - MUSCLES.keys():
            raise ContractValidationError(f"auditTargets.{field} must map supported muscle names to minimum/maximum ranges.")
        for muscle, bounds in values.items():
            if not isinstance(bounds, dict):
                raise ContractValidationError(f"Invalid {field} range for {muscle}.")
            lower, upper = bounds.get("minimum"), bounds.get("maximum")
            if (not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lower, upper))
                    or not 0 <= lower <= upper <= 100):
                raise ContractValidationError(f"Invalid {field} range for {muscle}: {bounds}.")
    limit = targets.get("maximumSessionSeconds")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
        raise ContractValidationError("auditTargets.maximumSessionSeconds must be a positive integer or null.")


def _is_work_set(item):
    return item.get("type") in ("WeightSet", "BodyWeightSet") and item.get("subCategory", "WorkSet") not in EXCLUDED_VOLUME_CATEGORIES


def _empty_volume():
    return {muscle: {"direct": 0, "indirect": 0, "effective": 0} for muscle in MUSCLES}


def add_audit_issue(report, code, message, repair, path="/workouts", **details):
    report["issues"].append(message)
    report["errors"].append({"code": code, "path": path, "message": message, "repair": repair, **details})


def audit_workout_package(package, targets):
    validate_audit_targets(targets)
    weekly = _empty_volume()
    report = {"assumptions": ASSUMPTIONS, "targets": copy.deepcopy(targets), "workouts": [], "weeklyVolume": weekly, "issues": [], "errors": []}
    for workout_index, workout in enumerate(package.get("workouts", [])):
        if workout.get("enabled") is False:
            continue
        volume = _empty_volume()
        timing = {"workSeconds": 0, "restSeconds": 0, "generalWarmupSeconds": ASSUMPTIONS["generalWarmupSeconds"], "rampUpSeconds": 0, "transitionSeconds": 0, "calibrationSeconds": 0}
        contributions = []
        logical_sets = 0
        exercises_seen = 0

        def add_exercise(exercise, selected_sets=None, standalone=True):
            nonlocal logical_sets, exercises_seen
            sets = exercise.get("sets", []) if selected_sets is None else selected_sets
            work_sets = [item for item in sets if _is_work_set(item)]
            count = len(work_sets)
            logical_sets += count
            exercises_seen += 1
            primary = set(exercise.get("muscleGroups") or [])
            secondary = set(exercise.get("secondaryMuscleGroups") or [])
            credits = {}
            for muscle, tags in MUSCLES.items():
                direct = count if primary & tags else 0
                indirect = count * ASSUMPTIONS["secondaryCompoundSetCredit"] if not direct and secondary & tags and exercise.get("exerciseCategory") in ("HEAVY_COMPOUND", "MODERATE_COMPOUND") else 0
                volume[muscle]["direct"] += direct
                volume[muscle]["indirect"] += indirect
                volume[muscle]["effective"] += direct + indirect
                if direct or indirect:
                    credits[muscle] = {"direct": direct, "indirect": indirect}
            contributions.append({"exerciseId": exercise["id"], "exercise": exercise["name"], "workingSets": count, "credits": credits})
            sides = 2 if exercise.get("intraSetRestInSeconds") else 1
            for item in sets:
                kind = item.get("type")
                if kind == "RestSet":
                    if standalone:
                        timing["restSeconds"] += item["timeInSeconds"]
                elif kind in ("WeightSet", "BodyWeightSet"):
                    timing["workSeconds"] += item["reps"] * ASSUMPTIONS["secondsPerRep"] * sides
                    if sides == 2:
                        timing["restSeconds"] += exercise["intraSetRestInSeconds"]
                elif kind in ("EnduranceSet", "TimedDurationSet"):
                    duration = item.get("timeInMillis", 0) / 1000
                    timing["workSeconds"] += duration * sides
                    if duration <= 0 and targets.get("maximumSessionSeconds"):
                        add_audit_issue(report, "unknown_duration", f"{workout['name']}: {exercise['name']} has no fixed duration; session duration cannot be validated.",
                                        "Supply a fixed duration if compatible with the requested exercise; otherwise ask the user how to resolve the time constraint.",
                                        path=f"/workouts/{workout_index}", exerciseId=exercise["id"])
                elif kind == "RunningSet" and targets.get("maximumSessionSeconds"):
                    add_audit_issue(report, "unknown_running_duration", f"{workout['name']}: running duration cannot be inferred from distance alone.",
                                    "Distance alone cannot satisfy a hard duration check. Ask the user for an appropriate fixed-duration prescription or an agreed constraint change.",
                                    path=f"/workouts/{workout_index}", exerciseId=exercise["id"])
            if exercise.get("generateWarmUpSets") and not any(s.get("subCategory") == "WarmupSet" for s in sets):
                timing["rampUpSeconds"] += ASSUMPTIONS["generatedRampUpSecondsPerExercise"]
            if exercise.get("requiresLoadCalibration") and work_sets and not any(s.get("subCategory") == "CalibrationSet" for s in sets):
                timing["calibrationSeconds"] += work_sets[0]["reps"] * ASSUMPTIONS["secondsPerRep"] * sides
                if sides == 2:
                    timing["calibrationSeconds"] += exercise["intraSetRestInSeconds"]

        for component in workout.get("workoutComponents", []):
            if component.get("enabled") is False:
                continue
            kind = component.get("type")
            if kind == "Exercise":
                add_exercise(component)
            elif kind == "Rest":
                timing["restSeconds"] += component["timeInSeconds"]
            elif kind == "Superset":
                members = [e for e in component.get("exercises", []) if e.get("enabled") is not False]
                member_sets = [[s for s in e.get("sets", []) if s.get("type") != "RestSet"] for e in members]
                counts = [sum(s.get("subCategory") not in EXCLUDED_VOLUME_CATEGORIES for s in sets) for sets in member_sets]
                if not counts:
                    continue
                if len(set(counts)) != 1:
                    add_audit_issue(report, "superset_set_count_mismatch", f"{workout['name']}: superset work-set counts {counts} differ; the app runs only the shortest member.",
                                    "Give all members equal working-set counts, or separate them into straight sets or different groups. Recheck all volume and duration targets.",
                                    path=f"/workouts/{workout_index}", exerciseIds=[e["id"] for e in members], actual=counts)
                rounds = min(counts)
                if rounds == 0:
                    add_audit_issue(report, "empty_superset", f"{workout['name']}: superset has no executable work rounds.",
                                    "Provide executable working sets for every superset member or remove the empty group.", path=f"/workouts/{workout_index}")
                    continue
                before_work, before_rest = timing["workSeconds"], timing["restSeconds"]
                before = before_work + before_rest
                for exercise, sets in zip(members, member_sets):
                    warmups = [s for s in sets if s.get("subCategory") in EXCLUDED_VOLUME_CATEGORIES]
                    work = [s for s in sets if s.get("subCategory") not in EXCLUDED_VOLUME_CATEGORIES][:rounds]
                    add_exercise(exercise, warmups + work, standalone=False)
                rests = component.get("restSecondsByExercise", {})
                timing["restSeconds"] += rounds * sum(rests.get(e["id"], 0) for e in members) - rests.get(members[-1]["id"], 0)
                if component.get("timeCapSeconds") or component.get("amrap"):
                    if targets.get("weeklyEffectiveSets") or targets.get("perSessionEffectiveSets"):
                        add_audit_issue(report, "unbounded_volume", f"{workout['name']}: time-capped/AMRAP volume is not an exact prescribed set count.",
                                        "Exact set-volume targets require finite prescribed rounds. If AMRAP is required, ask the user to resolve that conflict.", path=f"/workouts/{workout_index}")
                    if component.get("timeCapSeconds"):
                        timing["workSeconds"] = before_work + component["timeCapSeconds"]
                        timing["restSeconds"] = before_rest
                if component.get("roundDurationSeconds"):
                    elapsed = timing["workSeconds"] + timing["restSeconds"] - before
                    timing["restSeconds"] += max(0, rounds * component["roundDurationSeconds"] - elapsed)
        timing["transitionSeconds"] = max(0, exercises_seen - 1) * ASSUMPTIONS["transitionSeconds"]
        seconds = sum(timing.values())
        result = {"name": workout["name"], "workingSets": logical_sets, "volume": volume, "contributions": contributions, "timing": timing, "estimatedSeconds": seconds}
        report["workouts"].append(result)
        # shortcut: each enabled workout runs once weekly unless frequency is supplied; audit phases separately for periodized packages.
        frequency = workout.get("timesCompletedInAWeek") or 1
        for muscle in MUSCLES:
            for field in weekly[muscle]:
                weekly[muscle][field] += volume[muscle][field] * frequency
        limit = targets.get("maximumSessionSeconds")
        if limit and seconds > limit:
            add_audit_issue(report, "duration_exceeded", f"{workout['name']}: estimated duration {seconds:.0f}s exceeds {limit}s by {seconds-limit:.0f}s; breakdown={timing}.",
                            "Use the timing breakdown to reduce work, rests or setup costs within the user's agreed constraints. Preserve all volume targets and re-audit. If no feasible draft is found, ask the user for a tradeoff instead of relaxing requirements.",
                            path=f"/workouts/{workout_index}", actual=seconds, maximum=limit, excessSeconds=seconds-limit)
        _check_volume(volume, targets.get("perSessionEffectiveSets", {}), workout["name"], report, workout_index)
    _check_volume(weekly, targets.get("weeklyEffectiveSets", {}), "Weekly", report)
    return report


def _check_volume(volume, targets, label, report, workout_index=None):
    for muscle, bounds in targets.items():
        actual = volume[muscle]["effective"]
        if not bounds["minimum"] <= actual <= bounds["maximum"]:
            below = actual < bounds["minimum"]
            add_audit_issue(report, "volume_below_target" if below else "volume_above_target",
                            f"{label} {muscle}: {actual:g} effective sets (direct={volume[muscle]['direct']:g}, indirect={volume[muscle]['indirect']:g}); required {bounds['minimum']:g}–{bounds['maximum']:g}.",
                            f"{'Increase' if below else 'Reduce'} effective {muscle} volume by adjusting working-set counts or exercise selection. Use the report's per-exercise contributions; preserve library muscle roles and agreed targets, and re-audit volume and duration together.",
                            path="/workouts" if workout_index is None else f"/workouts/{workout_index}/exercises",
                            scope="weekly" if workout_index is None else "per_session", muscle=muscle,
                            actual=actual, minimum=bounds["minimum"], maximum=bounds["maximum"],
                            difference=bounds["minimum"]-actual if below else actual-bounds["maximum"])


def plan_audit_package(plan, allow_educated_load_guesses=True):
    """Use upper rep targets before emission; actual emitted reps can only take less time."""
    by_id = {}
    for entry in plan["exercises"]:
        exercise = copy.deepcopy(entry)
        exercise["type"] = "Exercise"
        loaded = entry["exerciseType"] == "WEIGHT" or (entry["exerciseType"] == "BODY_WEIGHT" and entry.get("equipmentId") is not None)
        exercise["requiresLoadCalibration"] = loaded and (not allow_educated_load_guesses or not entry.get("targetSetPrescriptions"))
        sets = []
        for index in range(entry.get("numWorkSets", 1)):
            if index:
                sets.append({"type": "RestSet", "timeInSeconds": entry.get("restBetweenSetsSeconds", 0)})
            if entry["exerciseType"] in ("WEIGHT", "BODY_WEIGHT"):
                targets = entry.get("targetSetPrescriptions") or []
                reps = targets[index]["reps"] if targets else entry["maxReps"]
                sets.append({"type": "WeightSet" if entry["exerciseType"] == "WEIGHT" else "BodyWeightSet", "reps": reps})
            elif entry["exerciseType"] == "RUNNING":
                sets.append({"type": "RunningSet"})
            else:
                sets.append({"type": "EnduranceSet", "timeInMillis": entry.get("timeInMillis", 0)})
        exercise["sets"] = sets
        by_id[entry["id"]] = exercise
    workouts = []
    for workout in plan["workouts"]:
        structure = build_workout_structure(workout)
        components = []
        for component in structure["workoutComponents"]:
            kind = component["componentType"]
            if kind == "Exercise":
                components.append(by_id[component["exerciseId"]])
            elif kind == "Superset":
                components.append({**component, "type": kind, "exercises": [by_id[i] for i in component["exerciseIds"]]})
            else:
                components.append({"type": kind, "timeInSeconds": component["timeInSeconds"]})
        workouts.append({**workout, "workoutComponents": components})
    return {"workouts": workouts}


def audit_and_repair_plan(client, plan, provided_equipment, logger=None, max_repairs=2, allow_educated_load_guesses=True):
    targets = copy.deepcopy(plan.get("auditTargets", {}))
    validate_audit_targets(targets)
    applied_changes = []
    for attempt in range(max_repairs + 1):
        report = audit_workout_package(plan_audit_package(plan, allow_educated_load_guesses), targets)
        if not report["issues"]:
            report["prescriptionChanges"] = applied_changes
            return plan, report
        if logger:
            logger.log_print("Programming audit failed: " + " | ".join(report["issues"]))
        if attempt == max_repairs:
            raise ValueError("Programming targets remain infeasible after bounded repair: " + " | ".join(report["issues"]))
        contributions = {item["exerciseId"]: item for workout in report["workouts"] for item in workout["contributions"]}
        repair_exercises = []
        for exercise in plan["exercises"]:
            contribution = contributions.get(exercise["id"], {})
            count = contribution.get("workingSets", 0)
            repair_exercises.append({
                "exerciseId": exercise["id"], "name": exercise["name"], "workingSets": exercise.get("numWorkSets"),
                "creditsPerWorkingSet": {muscle: (credit["direct"] + credit["indirect"]) / count for muscle, credit in contribution.get("credits", {}).items() if count},
                "maxReps": exercise.get("maxReps"), "restBetweenSetsSeconds": exercise.get("restBetweenSetsSeconds"),
                "countsLocked": bool(exercise.get("targetSetPrescriptions")), "placementNotes": exercise.get("placementNotes", ""),
            })
        messages = [
            {"role": "system", "content": (
                "Repair ONLY working-set counts of the supplied plan to satisfy the deterministic audit. "
                "Keep identities, equipment, exercise order, rests, warm-ups, rep ranges and target bounds unchanged. "
                "Superset members must retain equal work-set counts. Never alter exact targetSetPrescriptions. "
                "Update placementNotes when counts change so guidance remains accurate. If infeasible, return changes=[]. "
                "Use the supplied creditsPerWorkingSet coefficients for arithmetic. Correct the FULL shortfall/excess in one attempt, "
                "not one set at a time. Budget additional work and rests against each session's remaining time. "
                'Output JSON only: {"changes":[{"exerciseId":"EXERCISE_0","numWorkSets":4,"placementNotes":"..."}]}.'
            )},
            {"role": "user", "content": json.dumps({"exercises": repair_exercises, "workouts": plan["workouts"], "audit": report}, separators=(",", ":"))},
        ]
        if logger:
            logger.log_request("repair_programming_audit", messages[-1]["content"])
        content = json_call_reasoner_only_with_loading(client, messages, "Repairing programming audit", show_loading=True, logger=logger)
        if content is None:
            raise KeyboardInterrupt
        if logger:
            logger.log_response("repair_programming_audit", content or "")
        changes = json.loads(content).get("changes")
        if not isinstance(changes, list) or not changes:
            raise ValueError("Model could not repair programming targets without changing the confirmed constraints: " + " | ".join(report["issues"]))
        repaired = copy.deepcopy(plan)
        by_id = {e["id"]: e for e in repaired["exercises"]}
        seen = set()
        for change in changes:
            if not isinstance(change, dict) or set(change) - {"exerciseId", "numWorkSets", "placementNotes"}:
                raise ValueError("Audit repair may change only working-set counts and placement notes")
            exercise_id, count = change.get("exerciseId"), change.get("numWorkSets")
            if exercise_id not in by_id or exercise_id in seen or not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 20:
                raise ValueError("Invalid or duplicate exercise/count in audit repair")
            seen.add(exercise_id)
            if by_id[exercise_id].get("targetSetPrescriptions"):
                raise ValueError("Audit repair cannot overwrite exact user-prescribed sets")
            if not isinstance(change.get("placementNotes"), str) or len(change["placementNotes"]) > 500:
                raise ValueError("Audit repair must provide updated placement notes of at most 500 characters")
            applied_changes.append({"exerciseId": exercise_id, "name": by_id[exercise_id]["name"], "previousWorkingSets": by_id[exercise_id]["numWorkSets"], "workingSets": count})
            if logger:
                logger.log_print(f"  Audit repair {attempt+1}/{max_repairs}: {by_id[exercise_id]['name']} working sets {by_id[exercise_id]['numWorkSets']} -> {count}")
            by_id[exercise_id].update(numWorkSets=count, placementNotes=change["placementNotes"])
        validate_plan_index_contract(repaired, provided_equipment)
        plan = repaired
