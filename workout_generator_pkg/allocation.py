"""Deterministic working-set allocation against the existing workout audit."""

from __future__ import annotations

import copy
import math
import json

from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from .generation_audit import audit_workout_package, plan_audit_package
from .planning_tools import (
    _latest_result,
    _DRAFT_SCHEMA,
    _audit_coverage,
    build_draft_plan,
    latest_draft_submission,
    require_approved_requirements,
    audit_workout_plan,
    validate,
)
from .restriction_policy import effective_restrictions


_MAX_SETS = 20
_TOLERANCE = 1e-7

ALLOCATE_WORKOUT_SETS_TOOL = {"type": "function", "function": {
    "name": "allocate_workout_sets",
    "description": "Use only after the numerical audit reports set-volume or duration findings. Supply allowed integer set-count bounds for existing SLOT_n exercise occurrences; omitted slots stay fixed. If no allocation satisfies the supplied bounds, inspect allocationDiagnostics: it identifies omitted slots that could affect violated targets. A bounds-limited infeasibility does not prove the whole draft impossible. Ask the model to provide coordinated explicit bounds for relevant movable slots, preserving user limits and exact prescriptions; never widen bounds silently. The tool proposes only a numWorkSets JSON patch, checks the exact audit, and never changes movements, loads, requirements or approval. Apply a returned patch to currentDraftId, then audit the complete draft and obtain independent review and fresh confirmation.",
    "parameters": {"type": "object", "properties": {
        "requirementsId": {"type": "string"},
        "baseDraftId": {"type": "string"},
        "boundsBySlot": {"type": "object", "description": "Allowed count ranges keyed by SLOT_n occurrence references from the current planning state. Omitted slots remain at their current count.",
            "patternProperties": {"^SLOT_[0-9]+$": {"type": "object", "properties": {
                "minimum": {"type": "integer", "minimum": 1, "maximum": 20},
                "maximum": {"type": "integer", "minimum": 1, "maximum": 20},
            }, "required": ["minimum", "maximum"], "additionalProperties": False}},
            "additionalProperties": False},
    }, "required": ["requirementsId", "baseDraftId", "boundsBySlot"], "additionalProperties": False},
}}


def allocation_slots(draft):
    """Return stable, short references for each exercise occurrence in a draft."""
    result = {}
    for workout_index, workout in enumerate(draft.get("workouts", [])):
        for exercise_index, exercise in enumerate(workout.get("exercises", [])):
            slot_id = f"SLOT_{len(result)}"
            result[slot_id] = {
                "path": f"/workouts/{workout_index}/exercises/{exercise_index}",
                "definition_id": exercise.get("definition_id"),
                "numWorkSets": exercise.get("numWorkSets"),
                "superset": exercise.get("superset"),
                "fixed": bool(exercise.get("targetSetPrescriptions")),
                **({'allocationBounds': copy.deepcopy(exercise['allocationBounds'])} if 'allocationBounds' in exercise else {}),
            }
    return result


def _failure(reason, **details):
    return {"feasible": False, "reason": reason, **details,
            "instruction": "Keep the current draft unchanged. Resolve the stated conflict or revise the allowed set bounds, then audit again."}


def _feature_values(report):
    features = {}
    for index, workout in enumerate(report.get("workouts", [])):
        for muscle, values in workout["volume"].items():
            features[("session", index, muscle)] = float(values["effective"])
        features[("duration", index)] = float(workout["estimatedSeconds"])
    for muscle, values in report.get("weeklyVolume", {}).items():
        features[("weekly", muscle)] = float(values["effective"])
    return features


def _audit_raw(draft, equipment, requirements, restriction_policy, allow_educated_load_guesses):
    plan = build_draft_plan(draft, equipment, requirements, restriction_policy)
    report = audit_workout_package(plan_audit_package(plan, allow_educated_load_guesses), requirements["auditTargets"])
    _audit_coverage(draft, requirements, report)
    return plan, report


def _variables(draft, bounds_by_slot):
    slots = [{"slotId": slot_id, **slot,
              "countPath": slot["path"] + "/numWorkSets",
              "currentSets": slot["numWorkSets"]}
             for slot_id, slot in allocation_slots(draft).items()]
    by_id = {slot["slotId"]: slot for slot in slots}
    unknown = set(bounds_by_slot) - by_id.keys()
    if unknown:
        raise ValueError(f"Unknown slot reference(s): {', '.join(sorted(unknown))}.")
    groups = {}
    for slot in slots:
        path_parts = slot["path"].split("/")
        workout_index = int(path_parts[2])
        exercise_index = int(path_parts[4])
        exercise = draft["workouts"][workout_index]["exercises"][exercise_index]
        current = exercise.get("numWorkSets")
        if not isinstance(current, int) or isinstance(current, bool) or not 1 <= current <= _MAX_SETS:
            raise ValueError(f"{slot['slotId']} has an invalid current set count.")
        requested = bounds_by_slot.get(slot["slotId"])
        if requested is None:
            lower = upper = current
        else:
            if (not isinstance(requested, dict) or set(requested) != {"minimum", "maximum"}
                    or any(not isinstance(v, int) or isinstance(v, bool) for v in requested.values())):
                raise ValueError(f"Bounds for {slot['slotId']} must have integer minimum and maximum values.")
            lower, upper = requested["minimum"], requested["maximum"]
            if not 1 <= lower <= upper <= _MAX_SETS:
                raise ValueError(f"Bounds for {slot['slotId']} must be within 1–{_MAX_SETS} sets.")
        prescribed = exercise.get("targetSetPrescriptions") or []
        if prescribed:
            prescribed_count = len(prescribed)
            if current != prescribed_count:
                raise ValueError(f"{slot['slotId']} has {current} sets but {prescribed_count} exact set prescriptions.")
            if not lower <= prescribed_count <= upper:
                raise ValueError(f"Bounds for {slot['slotId']} conflict with its exact set prescriptions ({prescribed_count} sets).")
            lower = upper = prescribed_count
        key = (workout_index, exercise.get("superset")) if exercise.get("superset") is not None else (workout_index, "SLOT", slot["slotId"])
        groups.setdefault(key, []).append((slot, lower, upper, current))

    variables = []
    for key, members in groups.items():
        lower = max(item[1] for item in members)
        upper = min(item[2] for item in members)
        if lower > upper:
            raise ValueError(f"Superset {key[1]!r} has incompatible member set bounds.")
        if any(item[0]["fixed"] for item in members):
            fixed_counts = {item[3] for item in members if item[0]["fixed"]}
            if len(fixed_counts) != 1:
                raise ValueError(f"Superset {key[1]!r} has conflicting exact set prescriptions.")
            fixed = next(iter(fixed_counts))
            if not lower <= fixed <= upper:
                raise ValueError(f"Superset {key[1]!r} bounds conflict with a fixed member ({fixed} sets).")
            lower = upper = fixed
        variable_index = len(variables)
        variables.append({"key": key, "lower": lower, "upper": upper,
                          "members": [item[0] for item in members],
                          "current": [item[3] for item in members]})
    return slots, variables


def _draft_with_counts(draft, variables, counts):
    candidate = copy.deepcopy(draft)
    for variable, count in zip(variables, counts):
        for slot in variable["members"]:
            parts = slot["path"].split("/")
            candidate["workouts"][int(parts[2])]["exercises"][int(parts[4])]["numWorkSets"] = int(count)
    return candidate


def _constraints(report, requirements, frequency_complete, draft_frequency):
    targets = requirements["auditTargets"]
    rows = []
    for index, workout in enumerate(report["workouts"]):
        for muscle, bounds in targets.get("perSessionEffectiveSets", {}).items():
            rows.append((("session", index, muscle), float(bounds["minimum"]), float(bounds["maximum"])))
        if targets.get("maximumSessionSeconds") is not None:
            rows.append((("duration", index), -math.inf, float(targets["maximumSessionSeconds"])))
    sessions_per_week = requirements.get("sessionsPerWeek")
    if sessions_per_week is not None and frequency_complete and draft_frequency != sessions_per_week:
        raise ValueError(f"Draft frequency is {draft_frequency}; requirements specify {sessions_per_week} sessions per week.")
    for muscle, bounds in targets.get("weeklyEffectiveSets", {}).items():
        rows.append((("weekly", muscle), float(bounds["minimum"]) if frequency_complete else -math.inf,
                     float(bounds["maximum"])))
    return rows


def _milp_solve(variables, features, timeout_seconds=5):
    count = len(variables)
    if not count:
        return "optimal", []
    # Use one integer set-count variable and one deviation variable per exercise occurrence.
    occurrence_count = sum(len(variable["members"]) for variable in variables)
    objective = [0.0] * count + [1.0] * occurrence_count
    lower = [variable["lower"] for variable in variables] + [0.0] * occurrence_count
    upper = [variable["upper"] for variable in variables] + [math.inf] * occurrence_count
    integrality = [1] * count + [0] * occurrence_count
    rows = []
    lows = []
    highs = []
    for feature, minimum, maximum, intercept, coefficients in features:
        rows.append([*coefficients, *([0.0] * occurrence_count)])
        lows.append(minimum - intercept)
        highs.append(maximum - intercept)
    dev_index = count
    for variable_index, variable in enumerate(variables):
        for current in variable["current"]:
            positive = [0.0] * (count + occurrence_count)
            positive[variable_index] = 1
            positive[dev_index] = -1
            rows.append(positive)
            lows.append(-math.inf)
            highs.append(current)
            negative = [0.0] * (count + occurrence_count)
            negative[variable_index] = -1
            negative[dev_index] = -1
            rows.append(negative)
            lows.append(-math.inf)
            highs.append(-current)
            dev_index += 1
    matrix = lil_matrix((len(rows), count + occurrence_count), dtype=float)
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            if value:
                matrix[row_index, column] = value
    result = milp(objective, integrality=integrality, bounds=Bounds(lower, upper),
                  constraints=LinearConstraint(matrix.tocsr(), lows, highs),
                  options={"time_limit": timeout_seconds})
    if result.status == 2:
        return "infeasible", None
    if result.x is None or result.status != 0:
        return "unproven", None
    return "optimal", [int(round(value)) for value in result.x[:count]]


def _check_solution(candidate, plan, report, requirements, frequency_complete):
    if any(error["code"] == "missing_training_muscle_roles" for error in report["errors"]):
        return "The audit cannot verify one or more targeted muscle credits from the loaded library."
    targets = requirements["auditTargets"]
    feature_values = _feature_values(report)
    for index, workout in enumerate(report["workouts"]):
        for muscle, bounds in targets.get("perSessionEffectiveSets", {}).items():
            value = feature_values[("session", index, muscle)]
            if not bounds["minimum"] - _TOLERANCE <= value <= bounds["maximum"] + _TOLERANCE:
                return f"Exact audit found {workout['name']} {muscle} at {value:g} effective sets outside the requested range."
        limit = targets.get("maximumSessionSeconds")
        if limit is not None and feature_values[("duration", index)] > limit + _TOLERANCE:
            seconds = feature_values[("duration", index)]
            return f"Exact audit estimates {workout['name']} at {seconds:g}s, above the {limit}s limit."
    for muscle, bounds in targets.get("weeklyEffectiveSets", {}).items():
        value = feature_values[("weekly", muscle)]
        if value > bounds["maximum"] + _TOLERANCE:
            return f"Exact audit found weekly {muscle} at {value:g} effective sets, above {bounds['maximum']:g}."
        if frequency_complete and value < bounds["minimum"] - _TOLERANCE:
            return f"Exact audit found weekly {muscle} at {value:g} effective sets, below {bounds['minimum']:g}."
    for workout_index, workout in enumerate(candidate["workouts"]):
        groups = {}
        for exercise in workout["exercises"]:
            if exercise.get("superset") is not None:
                groups.setdefault(exercise["superset"], []).append(exercise["numWorkSets"])
        if any(len(set(counts)) > 1 for counts in groups.values()):
            return f"Exact audit candidate has unequal working sets inside a superset in workout {workout_index}."
    return None


def _blocking_audit_errors(report, frequency_complete, requirements):
    supported = {"volume_below_target", "volume_above_target", "duration_exceeded",
                 "superset_set_count_mismatch", "empty_superset"}
    if not frequency_complete and requirements.get("sessionsPerWeek") is not None:
        supported.add("weekly_session_count_mismatch")
    return [error for error in report.get("errors", []) if error.get("code") not in supported]


def _allocation_diagnostics(draft, equipment, requirements, restrictions, allow_educated_load_guesses,
                            supplied_bounds, frequency_complete, frequency):
    """Explain which omitted, unlocked slots could affect currently violated numeric targets."""
    plan, report = _audit_raw(draft, equipment, requirements, restrictions, allow_educated_load_guesses)
    values = _feature_values(report)
    violations = []
    for feature, minimum, maximum in _constraints(report, requirements, frequency_complete, frequency):
        value = values[feature]
        if value < minimum - _TOLERANCE or value > maximum + _TOLERANCE:
            direction = "increase" if value < minimum else "decrease"
            violations.append({"feature": feature, "direction": direction, "value": value,
                               "minimum": minimum, "maximum": maximum})
    if not violations:
        return []

    expanded_bounds = dict(supplied_bounds)
    for slot_id, slot in allocation_slots(draft).items():
        if slot_id not in expanded_bounds and not slot["fixed"]:
            expanded_bounds[slot_id] = {"minimum": 1, "maximum": _MAX_SETS}
    _, variables = _variables(draft, expanded_bounds)
    effects = _variable_effects(plan, report, variables)
    by_slot = {member["slotId"]: (variable, effects[index])
               for index, variable in enumerate(variables) for member in variable["members"]}
    diagnostics = []
    for slot_id, slot in allocation_slots(draft).items():
        if slot_id in supplied_bounds or slot_id not in by_slot:
            continue
        variable, effect = by_slot[slot_id]
        if variable["lower"] == variable["upper"]:
            continue
        matching = []
        for violation in violations:
            if (violation['direction'] == 'decrease' and max(variable['current']) <= variable['lower']
                    or violation['direction'] == 'increase' and min(variable['current']) >= variable['upper']):
                continue
            feature = violation["feature"]
            related = ((feature[0] == "duration" and effect["workout"] == feature[1])
                       or (feature[0] == "session" and effect["workout"] == feature[1]
                           and feature[2] in effect["muscles"])
                       or (feature[0] == "weekly" and feature[1] in effect["muscles"]))
            if related:
                matching.append({"target": ":".join(map(str, feature)),
                                 "currentValue": violation["value"],
                                 "requestedRange": [bound if math.isfinite(bound) else None
                                                    for bound in (violation["minimum"], violation["maximum"])],
                                 "neededDirection": violation["direction"]})
        if not matching:
            continue
        workout_index = effect["workout"]
        credits = {item["exerciseId"]: item["credits"] for item in report["workouts"][workout_index]["contributions"]}
        exercise_index = int(slot["path"].split("/")[4])
        exercise_id = plan["workouts"][workout_index]["exerciseIds"][exercise_index]
        diagnostics.append({"slotId": slot_id, "workout": workout_index,
                            "currentSets": slot["numWorkSets"],
                            "weeklyFrequency": draft["workouts"][workout_index].get("timesCompletedInAWeek") or 1,
                            "effectiveCreditsPerSet": {
                                muscle: (credit.get("direct", 0) + credit.get("indirect", 0)) / slot["numWorkSets"]
                                for muscle, credit in credits.get(exercise_id, {}).items()},
                            "couldAffect": matching,
                            "reason": "Omitted slot stayed at its current count; give it explicit bounds only if those changes are allowed."})
    return diagnostics


def _variable_effects(plan, report, variables):
    effects = []
    for variable in variables:
        workout_index = int(variable["members"][0]["path"].split("/")[2])
        exercise_ids = plan["workouts"][workout_index]["exerciseIds"]
        credits_by_id = {item["exerciseId"]: item["credits"]
                         for item in report["workouts"][workout_index]["contributions"]}
        exercise_indexes = [int(member["path"].split("/")[4]) for member in variable["members"]]
        effects.append({"workout": workout_index,
                        "muscles": {muscle for index in exercise_indexes
                                    for muscle, credit in credits_by_id.get(exercise_ids[index], {}).items()
                                    if credit.get("direct", 0) or credit.get("indirect", 0)}})
    return effects


def _allocate_workout_sets(arguments, equipment, messages, allow_educated_load_guesses=True, training_history=None):
    """Propose a minimal RFC 6902 set-count patch; never stores or approves it."""
    if set(arguments) != {"requirementsId", "baseDraftId", "boundsBySlot"}:
        raise ValueError("Allocation requires requirementsId, baseDraftId and boundsBySlot.")
    require_approved_requirements(messages)
    _, stored = _latest_result(messages, "set_workout_requirements")
    if stored.get("requirementsId") != arguments["requirementsId"] or not stored.get("requirements"):
        raise ValueError("The allocation requirementsId is missing, stale or not approved.")
    draft, draft_id = latest_draft_submission(messages, equipment)
    if draft is None or draft_id != arguments["baseDraftId"]:
        raise ValueError("The allocation baseDraftId is missing or stale.")
    if draft.get("requirementsId") != arguments["requirementsId"]:
        raise ValueError("The current draft was created under different requirements; re-audit it before allocating sets.")
    if not isinstance(arguments["boundsBySlot"], dict):
        raise ValueError("boundsBySlot must map SLOT_n references to integer minimum/maximum bounds.")
    validate(draft, _DRAFT_SCHEMA)
    restrictions = effective_restrictions(stored, equipment)
    slots, variables = _variables(draft, arguments["boundsBySlot"])
    requirements = stored["requirements"]
    base_vector = []
    for variable in variables:
        # Superset members share one count; probe from within the solver's allowed interval.
        base_vector.append(min(max(min(variable["current"]), variable["lower"]), variable["upper"]))
    probe_draft = _draft_with_counts(draft, variables, base_vector)
    base_plan, base_report = _audit_raw(probe_draft, equipment, requirements, restrictions, allow_educated_load_guesses)
    baseline = _feature_values(base_report)
    frequency = sum(workout.get("timesCompletedInAWeek") or 1 for workout in draft["workouts"])
    frequency_complete = requirements.get("sessionsPerWeek") is None or frequency >= requirements["sessionsPerWeek"]
    blockers = _blocking_audit_errors(base_report, frequency_complete, requirements)
    if blockers:
        return _failure("The audit has findings that set allocation cannot repair; keep them visible and resolve them separately.",
                        blockingErrors=blockers)
    constrained = _constraints(base_report, requirements, frequency_complete, frequency)
    feature_constraints = []
    effects = _variable_effects(base_plan, base_report, variables)
    feature_cache = {tuple(base_vector): baseline}
    probe_points = {}
    for variable_index, variable in enumerate(variables):
        if variable["lower"] == variable["upper"]:
            continue
        effect = effects[variable_index]
        relevant = any(
            (feature[0] == "duration" and effect["workout"] == feature[1])
            or (feature[0] == "session" and effect["workout"] == feature[1] and feature[2] in effect["muscles"])
            or (feature[0] == "weekly" and feature[1] in effect["muscles"])
            for feature, _, _ in constrained
        )
        if not relevant:
            continue
        current = base_vector[variable_index]
        upward, downward = variable["upper"] - current, current - variable["lower"]
        if upward >= 2:
            points = [current + 1, current + 2]
        elif downward >= 2:
            points = [current - 1, current - 2]
        elif upward and downward:
            points = [current - 1, current + 1]
        elif upward:
            points = [current + 1]
        elif downward:
            points = [current - 1]
        else:
            continue
        probe_points[variable_index] = points
        for point in points:
            vector = list(base_vector)
            vector[variable_index] = point
            key = tuple(vector)
            if key not in feature_cache:
                _, probe_report = _audit_raw(_draft_with_counts(draft, variables, vector), equipment,
                                            requirements, restrictions, allow_educated_load_guesses)
                feature_cache[key] = _feature_values(probe_report)
    for feature, minimum, maximum in constrained:
        coefficients = []
        for variable_index in range(len(variables)):
            points = probe_points.get(variable_index, [])
            if not points:
                coefficients.append(0.0)
                continue
            effect = effects[variable_index]
            if feature[0] == "duration" and effect["workout"] != feature[1]:
                coefficients.append(0.0)
                continue
            if feature[0] == "session" and (effect["workout"] != feature[1] or feature[2] not in effect["muscles"]):
                coefficients.append(0.0)
                continue
            if feature[0] == "weekly" and feature[1] not in effect["muscles"]:
                coefficients.append(0.0)
                continue
            slopes = [(feature_cache[tuple(base_vector[:variable_index] + [point] + base_vector[variable_index + 1:])][feature]
                       - baseline[feature]) / (point - base_vector[variable_index])
                      for point in points]
            coefficient = slopes[0]
            if any(abs(slope - coefficient) > _TOLERANCE for slope in slopes[1:]):
                return _failure("The existing audit is not affine for this draft; no set-count patch was proposed.", feature=str(feature))
            coefficients.append(coefficient)
        intercept = baseline[feature] - sum(coefficient * value for coefficient, value in zip(coefficients, base_vector))
        feature_constraints.append((feature, minimum, maximum, intercept, coefficients))

    status, counts = _milp_solve(variables, feature_constraints)
    if counts is None:
        if status == "infeasible":
            diagnostics = _allocation_diagnostics(draft, equipment, requirements, restrictions,
                                                  allow_educated_load_guesses, arguments["boundsBySlot"],
                                                  frequency_complete, frequency)
            return _failure("No allocation satisfies the supplied bounds and approved numerical targets; this does not establish that the draft is globally infeasible. The draft was left unchanged.",
                            allocationDiagnostics=diagnostics)
        return _failure("The solver limit was reached before a feasible allocation was proven; the draft was left unchanged.")
    candidate = _draft_with_counts(draft, variables, counts)
    exact_plan, exact_report = _audit_raw(candidate, equipment, requirements, restrictions, allow_educated_load_guesses)
    failure = _check_solution(candidate, exact_plan, exact_report, requirements, frequency_complete)
    if failure:
        return _failure(failure, audit=exact_report)
    exact_features = _feature_values(exact_report)
    for feature, minimum, maximum, intercept, coefficients in feature_constraints:
        predicted = intercept + sum(coefficient * value for coefficient, value in zip(coefficients, counts))
        if abs(predicted - exact_features[feature]) > _TOLERANCE:
            return _failure("The exact audit did not match the probed affine model; no patch was proposed.", feature=str(feature))
    patch = []
    for slot in slots:
        variable_index = next(i for i, variable in enumerate(variables)
                              if slot["slotId"] in {member["slotId"] for member in variable["members"]})
        count = counts[variable_index]
        if count != slot["currentSets"]:
            patch.append({"op": "replace", "path": slot["countPath"], "value": count})
    return {
        "feasible": True,
        "requirementsId": arguments["requirementsId"],
        "baseDraftId": draft_id,
        "patch": patch,
        "summary": {
            "weeklyEffectiveSets": {muscle: values["effective"] for muscle, values in exact_report["weeklyVolume"].items()
                                     if muscle in requirements["auditTargets"].get("weeklyEffectiveSets", {})},
            "sessions": [{"name": item["name"], "estimatedSeconds": item["estimatedSeconds"],
                          "effectiveSets": {muscle: item["volume"][muscle]["effective"] for muscle in requirements["auditTargets"].get("perSessionEffectiveSets", {})}}
                         for item in exact_report["workouts"]],
            "completeWeek": frequency_complete,
        },
        "nextStep": "Apply this patch to the current draft, then call audit_workout_plan and complete independent review and fresh user confirmation. This proposal does not mutate or approve the draft.",
    }


def allocate_workout_sets(arguments, equipment, messages, allow_educated_load_guesses=True, training_history=None):
    """Return conflicts as non-mutating tool results; never turn them into a repair guess."""
    try:
        return _allocate_workout_sets(arguments, equipment, messages, allow_educated_load_guesses, training_history)
    except ValueError as error:
        return _failure(str(error))


def auto_allocate_workout(result, equipment, messages, allow_educated_load_guesses=True, training_history=None, logger=None, progress=None):
    """Try declared flexibility once; every applied patch receives the full normal audit."""
    numeric = {'duration_exceeded', 'volume_below_target', 'volume_above_target', 'superset_set_count_mismatch'}
    dependencies = {'training_evidence_required', 'training_load_suitability_unresolved'}
    errors = result.get('errors', [])
    draft = result.get('submittedDraft')
    if (not draft or result.get('passed') or not any(e.get('code') in numeric for e in errors)
            or any(e.get('code') not in numeric | dependencies for e in errors)):
        return result
    _, stored = _latest_result(messages, 'set_workout_requirements')
    sessions = stored.get('requirements', {}).get('sessionsPerWeek')
    if sessions and sum(day['timesCompletedInAWeek'] for day in draft['workouts']) != sessions:
        return result
    bounds = {}
    for slot, item in allocation_slots(draft).items():
        _, _, day, _, index = item['path'].split('/')
        exercise = draft['workouts'][int(day)]['exercises'][int(index)]
        if exercise.get('allocationBounds') and not item['fixed']:
            bounds[slot] = copy.deepcopy(exercise['allocationBounds'])
    if not bounds:
        return result
    _, previous = _latest_result(messages, 'audit_workout_plan')
    cached = previous.get('automaticAllocation', {})
    if cached.get('inputDraftId') == result['draftId']:
        return {**result, 'automaticAllocation': copy.deepcopy(cached)}
    if progress:
        progress('Allocating sets within declared bounds')
    arguments = {'requirementsId': result['requirementsId'], 'baseDraftId': result['currentDraftId'], 'boundsBySlot': bounds}
    # The solver reads an immutable in-memory receipt; the actual tool result stores its complete provenance.
    baseline = messages + [
        {'role': 'assistant', 'tool_calls': [{'id': 'auto_allocation_base', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'auto_allocation_base', 'content': json.dumps(result)}]
    proposal = allocate_workout_sets(arguments, equipment, baseline, allow_educated_load_guesses, training_history)
    receipt = {'inputDraftId': result['draftId'], 'boundsBySlot': bounds, **proposal}
    if logger:
        logger.log_response('automatic_set_allocation', json.dumps(receipt), truncate_at=0)
    if proposal.get('feasible') and proposal.get('patch'):
        result = audit_workout_plan({'requirementsId': result['requirementsId'], 'baseDraftId': result['currentDraftId'],
            'patch': proposal['patch']}, equipment, baseline, allow_educated_load_guesses, training_history)
    return {**result, 'automaticAllocation': receipt}
