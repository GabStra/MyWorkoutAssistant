"""Deterministic working-set allocation against the existing workout audit."""

from __future__ import annotations

import copy
import math
import json
import time

from scipy.optimize import Bounds, LinearConstraint, OptimizeResult, linprog, milp
from scipy.sparse import lil_matrix

from .generation_audit import ASSUMPTIONS, audit_workout_package, plan_audit_package
from .programming_guidelines import normalize_work_set_bounds
from .planning_tools import (
    _latest_result,
    _fingerprint,
    _DRAFT_SCHEMA,
    PlanningInputError,
    _audit_coverage,
    build_draft_plan,
    draft_coverage_assignments,
    latest_draft_submission,
    library_fingerprint,
    require_approved_requirements,
    audit_workout_plan,
    validate,
)
from .restriction_policy import effective_restrictions


_MAX_SETS = 20
_TOLERANCE = 1e-7


def latest_allocation_conflict(messages):
    """Return the newest proven count conflict, skipping later rejected calls."""
    calls = {call.get('id'): call.get('function', {}).get('name')
             for message in messages for call in message.get('tool_calls', [])}
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get('role') != 'tool' or calls.get(message.get('tool_call_id')) != 'allocate_workout_sets':
            continue
        try:
            payload = json.loads(message.get('content') or '{}')
        except (ValueError, TypeError):
            continue
        conflict = payload.get('allocationConflict') if isinstance(payload, dict) else None
        if isinstance(conflict, dict) and conflict.get('status') == 'infeasible':
            return index, payload
    return -1, {}

ALLOCATE_WORKOUT_SETS_TOOL = {"type": "function", "function": {
    "name": "allocate_workout_sets",
    "description": "Propose coordinated set-count changes for the current draft. Use preferredSetsBySlot only for soft workload preferences. Python derives hard limits exclusively from approved workSets execution rules and preserves exact prescriptions; no model bounds may restrict other movable slots. Inspect the proposal and coverage totals, apply a permitted patch, re-audit and independently review. Fresh confirmation is required before export.",
    "parameters": {"type": "object", "properties": {
        "requirementsId": {"type": "string"},
        "baseDraftId": {"type": "string"},
        "reallocateAcrossSessions": {"type": "boolean", "description": "For distribution repairs requiring movement relocation: jointly reselect/place existing validated recipes across sessions and balance set concentration. Do not combine with SLOT_n preferences, whose identities change. This remains an unapplied proposal; combine with all other assessed repairs."},
        "preferredSetsBySlot": {"type": "object", "description": "Optional soft desired counts keyed by existing SLOT_n references; omitted preferences favor current counts. Approved constraints always win.",
            "patternProperties": {"^SLOT_[0-9]+$": {"type": "integer", "minimum": 1, "maximum": 20}}, "additionalProperties": False},
    }, "required": ["requirementsId", "baseDraftId"], "additionalProperties": False},
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


def allocation_input_fingerprint(draft, requirements_id, equipment, *, history_fingerprint=None,
                                 resolved_decisions=None, allow_educated_load_guesses=True, requirements=None):
    """Bind an allocation result to its draft, approved requirements, and library."""
    source = copy.deepcopy(draft or {})
    if requirements:
        source = normalize_work_set_bounds(source, equipment, requirements)
    workouts = source.get('workouts', [])
    for workout in workouts:
        for field in ('name', 'description', 'reference'):
            workout.pop(field, None)
        for exercise in workout.get('exercises', []):
            for field in ('placementNotes', 'reference', 'numWorkSets'):
                exercise.pop(field, None)
    return _fingerprint({'requirementsId': requirements_id,
        'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': history_fingerprint,
        'resolvedDecisions': resolved_decisions or {},
        'allowEducatedLoadGuesses': bool(allow_educated_load_guesses),
        'workouts': workouts})


def _failure(reason, **details):
    return {"feasible": False, "reason": reason, **details,
            "instruction": "Keep the current draft unchanged. Resolve the stated conflict or revise source-authorized set bounds, preserving approved targets and restrictions, then audit again."}


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
    report = audit_workout_package(plan_audit_package(plan, allow_educated_load_guesses), requirements["auditTargets"],
                                  coverage_by_exercise=draft_coverage_assignments(plan, draft))
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
            declared = slot.get('allocationBounds')
            if declared and not declared['minimum'] <= lower <= upper <= declared['maximum']:
                raise ValueError(f"Bounds for {slot['slotId']} exceed its declared allocationBounds. Explicitly revise that field within source constraints and audit before requesting a wider allocation.")
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


def _milp_with_incumbent(objective, integrality, bounds, constraints, options, initial_values):
    """Use the public HiGHS API when SciPy cannot pass a known feasible start."""
    import highspy

    solver = highspy.Highs()
    def checked(status):
        if status == highspy.HighsStatus.kError:
            raise RuntimeError('HiGHS rejected the model, options, or validated incumbent.')
    checked(solver.setOptionValue('output_flag', False))
    for name, value in options.items():
        checked(solver.setOptionValue(name, value))
    matrix = constraints.A.tocsc()
    model = highspy.HighsLp()
    model.num_col_, model.num_row_ = matrix.shape[1], matrix.shape[0]
    model.col_cost_, model.col_lower_, model.col_upper_ = objective, bounds.lb, bounds.ub
    model.row_lower_, model.row_upper_ = constraints.lb, constraints.ub
    model.integrality_ = [highspy.HighsVarType.kInteger if value else highspy.HighsVarType.kContinuous
                          for value in integrality]
    model.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    model.a_matrix_.start_, model.a_matrix_.index_, model.a_matrix_.value_ = (
        matrix.indptr, matrix.indices, matrix.data)
    checked(solver.passModel(model))
    if initial_values is not None:
        checked(solver.setSolution(len(initial_values), list(range(len(initial_values))), initial_values))
    checked(solver.run())
    status, info, solution = solver.getModelStatus(), solver.getInfo(), solver.getSolution()
    limited = {highspy.HighsModelStatus.kTimeLimit, highspy.HighsModelStatus.kIterationLimit,
        highspy.HighsModelStatus.kSolutionLimit, highspy.HighsModelStatus.kObjectiveBound,
        highspy.HighsModelStatus.kObjectiveTarget, highspy.HighsModelStatus.kInterrupt}
    code = (0 if status == highspy.HighsModelStatus.kOptimal else 1 if status in limited
            else 2 if status == highspy.HighsModelStatus.kInfeasible
            else 3 if status == highspy.HighsModelStatus.kUnbounded else 4)
    feasible = solution.value_valid and info.primal_solution_status == highspy.SolutionStatus.kSolutionStatusFeasible
    return OptimizeResult(status=code, message=solver.modelStatusToString(status),
        x=list(solution.col_value) if feasible else None,
        mip_dual_bound=info.mip_dual_bound, mip_gap=info.mip_gap, mip_node_count=info.mip_node_count)


def _milp_solve(variables, features, timeout_seconds=30, balance=False, preserve_current=True,
                diagnostics=None, incumbent=None):
    started = time.perf_counter()
    build_seconds = 0.0
    solver_seconds = 0.0

    def finish(status, candidate, reason, result=None, validated=False):
        if diagnostics is not None:
            def number(value):
                return float(value) if value is not None and math.isfinite(float(value)) else None
            node_count = getattr(result, 'mip_node_count', None)
            diagnostics.update({
                'terminationStatus': int(result.status) if result is not None else None,
                'terminationMessage': str(result.message) if result is not None else None,
                'incumbentFound': getattr(result, 'x', None) is not None,
                'incumbentValidated': validated,
                'objectiveBound': number(getattr(result, 'mip_dual_bound', None)),
                'relativeGap': number(getattr(result, 'mip_gap', None)),
                'nodeCount': int(node_count) if node_count is not None else None,
                'modelBuildSeconds': build_seconds,
                'solveSeconds': solver_seconds,
                'returnReason': reason,
            })
        return status, candidate

    count = len(variables)
    if not count:
        return finish("optimal", [], 'empty_variable_domain', validated=True)
    # Use one integer set-count variable and one deviation variable per exercise occurrence.
    occurrence_count = sum(len(variable["members"]) for variable in variables)
    objective = [variable.get('objectiveCost', 0.0) for variable in variables] + [1.0 if preserve_current else 0.0] * occurrence_count
    lower = [variable["lower"] for variable in variables] + [0.0] * occurrence_count
    upper = [variable["upper"] for variable in variables] + [math.inf] * occurrence_count
    integrality = [int(variable.get('integer', True)) for variable in variables] + [0] * occurrence_count
    if balance:
        # Initial counts are seeds, not prescriptions: minimize concentration before distance from those seeds.
        epsilon = 1 / (1 + sum(max(abs(v['lower'] - current), abs(v['upper'] - current))
                               for v in variables for current in v['current']))
        objective = [0.0] * count + [epsilon] * occurrence_count + [len(v['members']) for v in variables]
        lower += [v['lower'] ** 2 for v in variables]
        upper += [v['upper'] ** 2 for v in variables]
        integrality += [0] * count
    activations = {}
    for index, variable in enumerate(variables):
        if variable.get('minimumWhenSelected', 1) > 1 or variable.get('selectionCost'):
            activations[index] = len(objective)
            objective.append(variable.get('selectionCost', 0.0))
            lower.append(0)
            upper.append(1)
            integrality.append(1)
    size = len(objective)
    rows = []
    lows = []
    highs = []
    for feature, minimum, maximum, intercept, coefficients in features:
        rows.append(dict(coefficients) if isinstance(coefficients, dict) else dict(enumerate(coefficients)))
        lows.append(minimum - intercept)
        highs.append(maximum - intercept)
    for index, activation in activations.items():
        for limit, low, high in ((variables[index].get('minimumWhenSelected', 1), 0, math.inf),
                                 (variables[index]['upper'], -math.inf, 0)):
            row = {index: 1, activation: -limit}
            rows.append(row)
            lows.append(low)
            highs.append(high)
    dev_index = count
    for variable_index, variable in enumerate(variables):
        for current in variable["current"]:
            positive = {variable_index: 1, dev_index: -1}
            rows.append(positive)
            lows.append(-math.inf)
            highs.append(current)
            negative = {variable_index: -1, dev_index: -1}
            rows.append(negative)
            lows.append(-math.inf)
            highs.append(-current)
            dev_index += 1
    if balance:
        for index, variable in enumerate(variables):
            for step in range(variable['lower'], variable['upper']):
                row = {index: 2 * step + 1, count + occurrence_count + index: -1}
                rows.append(row)
                lows.append(-math.inf)
                highs.append(step * (step + 1))
    matrix = lil_matrix((len(rows), size), dtype=float)
    for row_index, row in enumerate(rows):
        for column, value in row.items():
            if value:
                matrix[row_index, column] = value
    options = {"mip_rel_gap": 0.0} if balance else {}
    if timeout_seconds is not None:
        options['time_limit'] = timeout_seconds
    constraint_matrix = matrix.tocsr()
    bounds = Bounds(lower, upper)
    constraints = LinearConstraint(constraint_matrix, lows, highs)
    initial_values = None
    if incumbent is not None:
        if len(incumbent) != count:
            raise ValueError('The incumbent does not match the current variable domain.')
        initial_values = list(incumbent) + [abs(incumbent[index] - value)
            for index, variable in enumerate(variables) for value in variable['current']]
        if balance:
            initial_values.extend(value ** 2 for value in incumbent)
        initial_values.extend(int(bool(incumbent[index])) for index in activations)
        activities = constraint_matrix @ initial_values
        if (any(not math.isfinite(value) or not low - _TOLERANCE <= value <= high + _TOLERANCE
                or (integer and abs(value - round(value)) > _TOLERANCE)
                for value, low, high, integer in zip(initial_values, lower, upper, integrality))
                or any(not low - _TOLERANCE <= value <= high + _TOLERANCE
                    for value, low, high in zip(activities, lows, highs))):
            raise ValueError('The incumbent violates the current bounds, integrality, or constraints.')
    if diagnostics is not None and initial_values is not None:
        diagnostics['incumbentSupplied'] = True
        diagnostics['backend'] = 'highspy'
    solver_started = time.perf_counter()
    build_seconds = solver_started - started
    solve_started = time.perf_counter()
    result = (milp(objective, integrality=integrality, bounds=bounds,
                   constraints=constraints, options=options) if initial_values is None else
              _milp_with_incumbent(objective, integrality, bounds, constraints, options, initial_values))
    solver_seconds = time.perf_counter() - solve_started
    if result.status == 2:
        return finish("infeasible", None, 'solver_infeasible', result)
    if result.x is None or result.status not in (0, 1):
        return finish("unproven", None, 'no_incumbent' if result.x is None else 'unsupported_solver_status', result)
    values = result.x[:count]
    if any(not math.isfinite(value) or (variable.get('integer', True)
           and abs(value - round(value)) > _TOLERANCE) for variable, value in zip(variables, values)):
        return finish('unproven', None, 'invalid_count_value', result)
    counts = [int(round(value)) if variable.get('integer', True) else float(value)
              for variable, value in zip(variables, values)]
    if any(not variable['lower'] - _TOLERANCE <= value <= variable['upper'] + _TOLERANCE
           or (value and value < variable.get('minimumWhenSelected', variable['lower']))
           for variable, value in zip(variables, counts)):
        return finish('unproven', None, 'count_outside_bounds', result)
    if any(not minimum - _TOLERANCE <= intercept + sum(coeff * counts[index] for index, coeff in
           (coefficients.items() if isinstance(coefficients, dict) else enumerate(coefficients))) <= maximum + _TOLERANCE
           for _, minimum, maximum, intercept, coefficients in features):
        return finish('unproven', None, 'feature_constraint_violation', result)
    return finish('optimal' if result.status == 0 else 'feasible', counts,
                  'accepted_optimal' if result.status == 0 else 'accepted_feasible', result, validated=True)


def _check_solution(candidate, plan, report, requirements, frequency_complete):
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


def _conflicting_targets(variables, features):
    """Explain coupled bound failures; the integer solver and final audit remain authoritative."""
    bounds = [(item['lower'], item['upper']) for item in variables]
    def solve(selected, objective=None):
        rows, limits = [], []
        for _, minimum, maximum, intercept, coefficients in selected:
            if math.isfinite(maximum):
                rows.append(coefficients)
                limits.append(maximum - intercept)
            if math.isfinite(minimum):
                rows.append([-value for value in coefficients])
                limits.append(intercept - minimum)
        return linprog(objective if objective is not None else [0.0] * len(variables),
                       A_ub=rows or None, b_ub=limits or None, bounds=bounds, method='highs')
    def infeasible(selected):
        return solve(selected).status == 2
    integer_only = False
    if not infeasible(features):
        if not any(variable.get('minimumWhenSelected', 1) > 1 for variable in variables):
            return []
        status, _ = _milp_solve(variables, features, preserve_current=False, timeout_seconds=1)
        if status != 'infeasible':
            return []  # Do not report conflicts without an exact infeasibility proof.
        integer_only = True
    ranges = {id(item): [item[3] + sum(value * variable['lower' if value >= 0 else 'upper']
                        for value, variable in zip(item[4], variables)),
                        item[3] + sum(value * variable['upper' if value >= 0 else 'lower']
                        for value, variable in zip(item[4], variables))] for item in features}
    independent = [item for item in features if ranges[id(item)][1] < item[1] - _TOLERANCE
                   or ranges[id(item)][0] > item[2] + _TOLERANCE]
    remaining = [item for item in features if all(item is not conflict for conflict in independent)]
    if integer_only:
        remaining = list(features)
        for feature in list(remaining):
            candidate = [item for item in remaining if item is not feature]
            status, _ = _milp_solve(variables, candidate, preserve_current=False, timeout_seconds=1)
            if status == 'infeasible':
                remaining = candidate
    else:
        if not remaining or not infeasible(remaining):
            remaining = []
        for feature in list(remaining):
            candidate = [item for item in remaining if item is not feature]
            if infeasible(candidate):
                remaining = candidate
    conflicts = []
    for item in independent + remaining:
        feature, minimum, maximum, intercept, coefficients = item
        isolated = any(item is conflict for conflict in independent)
        others = [other for other in remaining if other is not item]
        low = solve(others, coefficients) if not isolated else None
        high = solve(others, [-value for value in coefficients]) if not isolated else None
        conflict = {'target': ':'.join(map(str, feature)),
             'minimum': minimum if math.isfinite(minimum) else None,
             'maximum': maximum if math.isfinite(maximum) else None,
             'rangeWithinSlotBounds': ranges[id(item)],
             'slotIds': [member['slotId'] for value, variable in zip(coefficients, variables)
                         if value for member in variable['members']]}
        if integer_only:
            conflict['integerOnlyConflict'] = True
        if isolated:
            conflict['individuallyUnreachable'] = True
        else:
            conflict['rangeWithOtherConflictingTargets'] = [intercept + low.fun if low.success else None,
                                                           intercept - high.fun if high.success else None]
        conflicts.append(conflict)
    return conflicts


def _prepared_selection_objectives(sessions, candidates, requirements, existing, base_report, variables, features):
    """Build soft, source-approved menu preferences over the early count domain."""
    # Recipe roles are model-proposed until qualify_recipe_contracts runs.  The
    # early menu solve may therefore compare muscle-volume distribution only.
    order = [goal for goal in requirements.get('objectiveOrder', []) if goal == 'distribution']
    if not order:
        return {'order': [], 'terms': {'source_balance': [], 'distribution': []}}
    terms = {'source_balance': [], 'distribution': []}
    base_count = len(variables)
    def term(goal, label, intercept, coefficients, mode, multiplier=1):
        upper = (max(0, intercept + sum(max(0, value) * variable['upper']
                                        for value, variable in zip(coefficients, variables)))
                 if mode == 'shortfall' else
                 abs(intercept) + sum(abs(value) * variable['upper']
                                      for value, variable in zip(coefficients, variables)))
        terms[goal].append({'label': label, 'intercept': intercept, 'coefficients': coefficients,
                            'mode': mode, 'multiplier': multiplier, 'upper': upper})

    if 'source_balance' in order:
        for rule_index, rule in enumerate(item for item in requirements.get('executionRules', [])
                                           if item['kind'] == 'coverageBalance'):
            for day_index in ([None] if rule['scope'] == 'weekly' else range(len(sessions))):
                first, second = rule['first'], rule['second']
                direction = -1 if rule.get('relationship', 'balanced') == 'first_not_less_than_second' else 1
                coefficients = []
                for variable in variables:
                    slot = variable['members'][0]
                    item = sessions[slot['day']]['exercises'][slot['index']]
                    matches = (int(first in item.get('satisfiesCoverage', []))
                               - int(second in item.get('satisfiesCoverage', []))) * direction
                    coefficients.append(matches * (sessions[slot['day']]['timesCompletedInAWeek']
                        if day_index is None else int(slot['day'] == day_index)))
                intercept = 0
                if day_index is None:
                    intercept = sum(workout.get('timesCompletedInAWeek', 1) * item.get('numWorkSets', 0)
                        * (int(first in item.get('satisfiesCoverage', []))
                           - int(second in item.get('satisfiesCoverage', []))) * direction
                        for workout in (existing or {}).get('workouts', []) for item in workout.get('exercises', []))
                mode = 'shortfall' if direction == -1 else 'absolute'
                term('source_balance', {'ruleIndex': rule_index, 'first': first, 'second': second,
                    'scope': rule['scope'], 'workoutIndex': day_index,
                    'relationship': rule.get('relationship', 'balanced')}, intercept, coefficients, mode)

    if 'distribution' in order:
        targets = requirements.get('auditTargets', {})
        muscles = sorted(set(targets.get('weeklyEffectiveSets', {}))
                         | set(targets.get('perSessionEffectiveSets', {})))
        fixed = (base_report or {}).get('workouts', [])
        frequency = sum(day['timesCompletedInAWeek'] for day in sessions) + sum(
            day.get('timesCompletedInAWeek', 1) for day in (existing or {}).get('workouts', []))
        if frequency:
            base_weekly = (base_report or {}).get('weeklyVolume', {})
            for muscle in muscles:
                weekly_intercept = 2 * base_weekly.get(muscle, {}).get('effective', 0)
                credit = [sum(candidates[variable['members'][0]['reference']]['creditsPerWorkingSet']
                              .get(muscle, {}).get(kind, 0) for kind in ('direct', 'indirect'))
                          for variable in variables]
                for day_index, day in enumerate(sessions):
                    coefficients = [2 * ((frequency if variable['members'][0]['day'] == day_index else 0)
                                         - sessions[variable['members'][0]['day']]['timesCompletedInAWeek']) * value
                                    for variable, value in zip(variables, credit)]
                    term('distribution', {'muscle': muscle, 'workoutIndex': day_index, 'fixed': False},
                         -weekly_intercept, coefficients, 'absolute', day['timesCompletedInAWeek'])
                for workout_index, workout in enumerate(fixed):
                    session_volume = workout.get('volume', {}).get(muscle, {}).get('effective', 0)
                    coefficients = [-2 * sessions[variable['members'][0]['day']]['timesCompletedInAWeek'] * value
                                    for variable, value in zip(variables, credit)]
                    intercept = 2 * (frequency * session_volume - base_weekly.get(muscle, {}).get('effective', 0))
                    term('distribution', {'muscle': muscle, 'workoutIndex': workout_index, 'fixed': True},
                         intercept, coefficients, 'absolute', workout.get('timesCompletedInAWeek', 1))

    order = [goal for goal in order if terms[goal]]
    for goal in order:
        for item in terms[goal]:
            auxiliary_index = len(variables)
            variables.append({'lower': 0, 'upper': item['upper'],
                'objectiveCost': 0, 'selectionGoal': goal, 'selectionMultiplier': item['multiplier'],
                'members': [], 'current': []})
            features[:] = [(label, minimum, maximum, intercept, coefficients + [0])
                           for label, minimum, maximum, intercept, coefficients in features]
            coefficients = item['coefficients'] + [0] * (auxiliary_index - base_count) + [-1]
            features.append((('selection_preference', goal, item['label'], 1), -math.inf, 0,
                             item['intercept'], coefficients))
            if item['mode'] == 'absolute':
                features.append((('selection_preference', goal, item['label'], -1), -math.inf, 0,
                                 -item['intercept'], [-value for value in item['coefficients']]
                                 + [0] * (auxiliary_index - base_count) + [-1]))
    return {'order': order, 'terms': terms}


def _selection_preview(sessions, allocated, requirements, existing, candidates, base_report, details,
                       variables, counts, status, hard_features):
    if not details['order']:
        return None
    seed_counts = [sessions[variable['members'][0]['day']]['exercises'][variable['members'][0]['index']]['numWorkSets']
                   for variable in variables]
    selected_counts = counts[:len(variables)]
    baseline_feasible = (all(minimum - _TOLERANCE <= intercept + sum(a*b for a, b in
        zip(coefficients, seed_counts)) <= maximum + _TOLERANCE
        for _, minimum, maximum, intercept, coefficients in hard_features)
        and all(value == 0 or value >= variable.get('minimumWhenSelected', variable['lower'])
                for variable, value in zip(variables, seed_counts)))
    objectives = []
    for goal in details['order']:
        def cost(values):
            return sum(item['multiplier'] * (abs(item['intercept'] + sum(a*b for a, b in
                zip(item['coefficients'], values))) if item['mode'] == 'absolute' else
                max(0, item['intercept'] + sum(a*b for a, b in zip(item['coefficients'], values))))
                for item in details['terms'][goal])
        baseline, proposal = cost(seed_counts), cost(selected_counts)
        objectives.append({'priority': goal, 'baselineCost': baseline, 'proposalCost': proposal,
                           'improvement': baseline - proposal})

    comparisons = []
    distribution = []
    for muscle in sorted(set(requirements.get('auditTargets', {}).get('weeklyEffectiveSets', {}))
                         | set(requirements.get('auditTargets', {}).get('perSessionEffectiveSets', {}))):
        by_session = []
        for source, days in (('candidate', sessions), ('selected', allocated)):
            for index, day in enumerate(days):
                value = sum(item.get('numWorkSets', 0) * sum(
                    candidates[item['definition_id']]['creditsPerWorkingSet'].get(muscle, {}).get(kind, 0)
                    for kind in ('direct', 'indirect')) for item in day.get('exercises', []))
                by_session.append({'source': source, 'workoutIndex': index, 'effectiveSets': value})
        for index, day in enumerate((base_report or {}).get('workouts', [])):
            value = day.get('volume', {}).get(muscle, {}).get('effective', 0)
            by_session.append({'source': 'fixed', 'workoutIndex': index, 'effectiveSets': value})
        distribution.append({'muscle': muscle, 'sessions': by_session})
    return {'scope': 'pre_prescription_count_domain', 'roleMapping': 'unqualified_and_not_used',
            'baselineFeasibleWithinCountDomain': baseline_feasible,
            'objectiveStatus': status, 'objectives': objectives,
            'roleComparisons': comparisons, 'distributionByMuscle': distribution}


def selection_volume_conflicts(sessions, candidates, targets):
    """Reject only selections infeasible even under relaxed source-schema set bounds."""
    slots = [(day_index, reference, index) for day_index, day in enumerate(sessions)
             for index, reference in enumerate(day['definition_ids'])]
    variables = [{'lower': 1, 'upper': _MAX_SETS,
                  'members': [{'slotId': f'/sessions/{day}/definition_ids/{index}'}]} for day, _, index in slots]
    features = []
    for scope, key in (('weekly', 'weeklyEffectiveSets'), ('session', 'perSessionEffectiveSets')):
        for muscle, bounds in targets.get(key, {}).items():
            for day_index in (range(len(sessions)) if scope == 'session' else [None]):
                coefficients = [sum(candidates[ref]['creditsPerWorkingSet'].get(muscle, {}).get(kind, 0)
                                    for kind in ('direct', 'indirect'))
                    * (sessions[day]['timesCompletedInAWeek'] if scope == 'weekly' else int(day == day_index))
                    for day, ref, _ in slots]
                label = (scope, muscle) if day_index is None else (scope, day_index, muscle)
                features.append((label, bounds['minimum'], bounds['maximum'], 0, coefficients))
    return _conflicting_targets(variables, features) if features else []


def allocate_prepared_sets(sessions, candidates, requirements, existing=None, equipment=None, restriction_policy=None,
                           select_movements=False):
    """Allocate the selected week before prescriptions can lock otherwise adjustable counts."""
    base_volume, base_report = {}, None
    if existing:
        _, base_report = _audit_raw(existing, equipment, requirements, restriction_policy, True)
        base_volume = base_report['weeklyVolume']
    variables, layout_errors, bounds_errors = [], [], []
    for day_index, day in enumerate(sessions):
        groups = {}
        for index, item in enumerate(day['exercises']):
            reference = item['definition_id']
            bounds = item.get('allocationBounds') or {'minimum': item['numWorkSets'], 'maximum': item['numWorkSets']}
            if not select_movements and not bounds['minimum'] <= item['numWorkSets'] <= bounds['maximum']:
                path = f'/sessions/{day_index}/exercises/{index}'
                bounds_errors.append({'code': 'prepared_count_bounds_conflict', 'path': path,
                    'message': 'Count is outside its declared bounds.', 'permittedPaths': {
                        'exact': [path + '/numWorkSets', path + '/allocationBounds'], 'descendants': [path + '/allocationBounds']}})
            slot = {'day': day_index, 'index': index, 'reference': reference,
                    'slotId': f'/sessions/{day_index}/exercises/{index}'}
            key = ('group', item['superset']) if item['superset'] is not None and not select_movements else ('slot', index)
            groups.setdefault(key, []).append((slot, {**item, 'allocationBounds': bounds}))
        for key, members in groups.items():
            lower = max(item['allocationBounds']['minimum'] for _, item in members)
            upper = min(item['allocationBounds']['maximum'] for _, item in members)
            indices = [slot['index'] for slot, _ in members]
            if key[0] == 'group' and (len(indices) < 2 or indices != list(range(indices[0], indices[-1] + 1))):
                path = f'/sessions/{day_index}/exercises'
                layout_errors.append({
                        'code': 'prepared_group_layout', 'path': path, 'message': f'Invalid group {key[1]!r}: {indices}.',
                        'permittedPaths': {'exact': [path], 'descendants': [path]}})
                continue
            if lower > upper and not select_movements:
                paths = [slot['slotId'] for slot, _ in members]
                bounds_errors.append({
                        'code': 'prepared_group_bounds', 'path': paths[0], 'message': f'Group {key[1]!r} has no common allowed count.',
                        'permittedPaths': {'exact': [path + '/' + field for path in paths for field in ('numWorkSets', 'allocationBounds', 'superset')],
                                           'descendants': [path + '/allocationBounds' for path in paths]}})
                continue
            # Optional preparation is only a feasibility check; the full recipe
            # pool is retained for the final executable solve.
            variables.append({'lower': 0 if select_movements else lower, 'upper': upper,
                              **({'minimumWhenSelected': lower}
                                 if select_movements else {}),
                              'members': [slot for slot, _ in members],
                              'current': [item['numWorkSets'] for _, item in members]})
    # Layout repairs preserve prescriptions; resolve all layouts before authorizing count/bounds edits.
    errors = layout_errors or bounds_errors
    if errors:
        raise PlanningInputError(errors[0]['code'], 'Prepared groups need correction.', errors[0]['path'],
            'Repair every returned finding within its permitted paths; preserve other choices and source constraints.', errors=errors)
    features = []
    targets = requirements['auditTargets']
    for scope, key in (('weekly', 'weeklyEffectiveSets'), ('session', 'perSessionEffectiveSets')):
        for muscle, bounds in targets.get(key, {}).items():
            for day_index in (range(len(sessions)) if scope == 'session' else [None]):
                coefficients = [sum(sum(candidates[slot['reference']]['creditsPerWorkingSet'].get(muscle, {}).get(kind, 0)
                                        for kind in ('direct', 'indirect')) *
                                    (sessions[slot['day']]['timesCompletedInAWeek'] if scope == 'weekly'
                                     else int(slot['day'] == day_index))
                                    for slot in variable['members']) for variable in variables]
                label = (scope, muscle) if day_index is None else (scope, day_index, muscle)
                intercept = base_volume.get(muscle, {}).get('effective', 0) if scope == 'weekly' else 0
                features.append((label, bounds['minimum'], bounds['maximum'], intercept, coefficients))
    if select_movements:
        for day_index in range(len(sessions)):
            features.append((('session_nonempty', day_index), 1, math.inf, 0,
                [int(v['members'][0]['day'] == day_index) for v in variables]))
    hard_variables, hard_features = copy.deepcopy(variables), copy.deepcopy(features)
    candidate_variables = copy.deepcopy(variables)
    preference_details = (_prepared_selection_objectives(sessions, candidates, requirements, existing,
        base_report, variables, features) if select_movements else {'order': [], 'terms': {}})
    diagnostic_feature_count = len(hard_features)
    if select_movements and preference_details['order']:
        status, counts = 'optimal', None
        def verified_stage_counts(candidate):
            return (candidate is not None and len(candidate) == len(variables)
                and all(minimum - _TOLERANCE <= intercept + sum(a*b for a, b in zip(coefficients, candidate))
                        <= maximum + _TOLERANCE
                        for _, minimum, maximum, intercept, coefficients in features)
                and all(count == 0 or count >= variable.get('minimumWhenSelected', variable['lower'])
                        for variable, count in zip(variables, candidate)))

        for stage_index, goal in enumerate(preference_details['order']):
            for variable in variables:
                variable['objectiveCost'] = (variable.get('selectionMultiplier', 1)
                    if variable.get('selectionGoal') == goal else 0)
            stage_status, stage_counts = _milp_solve(variables, features, preserve_current=False)
            if verified_stage_counts(stage_counts):
                counts = stage_counts
            if stage_status != 'optimal' or not verified_stage_counts(stage_counts):
                status = ('feasible' if counts is not None else
                          'unproven' if stage_index and stage_status == 'infeasible' else
                          stage_status if stage_status != 'optimal' else 'unverified')
                break
            locked_value = sum(variable['objectiveCost'] * count for variable, count in zip(variables, counts))
            features.append((('selection_objective_lock', goal), locked_value, locked_value, 0,
                             [variable['objectiveCost'] if variable.get('selectionGoal') == goal else 0
                              for variable in variables]))
        else:
            status = 'optimal'
    else:
        status, counts = _milp_solve(variables, features, balance=not select_movements,
                                   preserve_current=not select_movements)
    if status not in ('optimal', 'feasible'):
        return {'feasible': False, 'status': status,
                'conflictingTargets': _conflicting_targets(hard_variables, hard_features) if status == 'infeasible' else [],
                'instruction': ('The current candidate pool and approved count limits conflict. Supply qualifying movement alternatives; '
                    'do not invent bounds, relax approved requirements, or claim all other selections are infeasible.')
                    if status == 'infeasible' else 'The bounded solve did not prove feasibility or infeasibility. Preserve the proposal and constraints; retry only after an explicit resume.'}
    # Independently check the returned integer solution; never approve a solver tolerance violation.
    if any(not minimum - _TOLERANCE <= intercept + sum(a*b for a,b in zip(coefficients, counts)) <= maximum + _TOLERANCE
           for _, minimum, maximum, intercept, coefficients in features):
        return {'feasible': False, 'status': 'unverified', 'conflictingTargets': []}
    if any(count and count < variable.get('minimumWhenSelected', variable['lower'])
           for variable, count in zip(variables, counts)):
        return {'feasible': False, 'status': 'unverified', 'conflictingTargets': []}
    allocated = copy.deepcopy(sessions)
    for variable, count in zip(variables, counts):
        for slot in variable['members']:
            allocated[slot['day']]['exercises'][slot['index']]['numWorkSets'] = count
    if select_movements:
        for day in allocated:
            day['exercises'] = [item for item in day['exercises'] if item['numWorkSets']]
            groups = {}
            for index, item in enumerate(day['exercises']):
                if item['superset'] is not None:
                    groups.setdefault(item['superset'], []).append(index)
            for indices in groups.values():
                members = [day['exercises'][i] for i in indices]
                if (len(members) < 2 or len({item['numWorkSets'] for item in members}) > 1
                        or indices != list(range(indices[0], indices[-1] + 1))):
                    for item in members:
                        item['superset'] = None
    diagnostics = []
    rows, limits = [], []
    for _, minimum, maximum, intercept, coefficients in features[:diagnostic_feature_count]:
        if math.isfinite(maximum):
            rows.append(coefficients)
            limits.append(maximum - intercept)
        if math.isfinite(minimum):
            rows.append([-value for value in coefficients])
            limits.append(intercept - minimum)
    if rows:
        diagnostic_objectives = [(
            [int(position == index) for position in range(len(variables))],
            {'slotIds': [slot['slotId'] for slot in variable['members']]})
            for index, variable in enumerate(variables) if variable['members'] and variable['lower'] != variable['upper']]
        for reference in sorted(candidates):
            objective = [sum(sessions[slot['day']]['timesCompletedInAWeek']
                             for slot in variable['members'] if slot['reference'] == reference)
                         for variable in variables]
            slots = [slot['slotId'] for variable in variables for slot in variable['members']
                     if slot['reference'] == reference]
            if len(slots) > 1:
                diagnostic_objectives.append((objective, {'scope': 'weekly',
                    'definitionReference': reference, 'slotIds': slots}))
        for objective, identity in diagnostic_objectives:
            allowed_minimum = sum(value * variable['lower'] for value, variable in zip(objective, variables))
            allowed_maximum = sum(value * variable['upper'] for value, variable in zip(objective, variables))
            minimum = linprog(objective, A_ub=rows, b_ub=limits,
                bounds=[(v['lower'], v['upper']) for v in variables], method='highs')
            if minimum.success:
                required = math.ceil(minimum.fun - _TOLERANCE)
                if required > allowed_minimum:
                    diagnostics.append({**identity,
                        'minimumRequiredSets': required, 'allowedMinimum': allowed_minimum, 'allowedMaximum': allowed_maximum,
                        'instruction': 'These counts are forced by the current selection, placements and approved volume targets. To distribute work, revise placement/selection or source-authorized bounds, not hand-written counts. This is not a physiological set limit.'})
    preview = None
    if select_movements and preference_details['order']:
        preference_details['status'] = status
        preview = _selection_preview(sessions, allocated, requirements, existing, candidates, base_report,
                                     preference_details, candidate_variables, counts, status, hard_features)
    return {'feasible': True, 'solveStatus': status, 'sessions': allocated, 'allocationDiagnostics': diagnostics,
            **({'selectionPreview': preview} if preview else {}),
            'scope': ('Pre-prescription muscle-credit count-domain comparison only; proposed role labels are unqualified and do not constrain this result. '
                'Detailed prescriptions, timing, effort, setup and qualified-role coverage remain for later stages.')}


def _blocking_audit_errors(report, frequency_complete, requirements):
    supported = {"volume_below_target", "volume_above_target", "duration_exceeded",
                 "superset_set_count_mismatch", "empty_superset"}
    if not frequency_complete and requirements.get("sessionsPerWeek") is not None:
        supported.add("weekly_session_count_mismatch")
    return [error for error in report.get("errors", []) if error.get("code") not in supported]


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


def _allocate_workout_sets(arguments, equipment, messages, allow_educated_load_guesses=True, training_history=None, *, balance=False):
    """Propose a minimal RFC 6902 set-count patch; never stores or approves it."""
    required = {"requirementsId", "baseDraftId"}
    if not required <= set(arguments) <= required | {"preferredSetsBySlot", "boundsBySlot", "reallocateAcrossSessions"}:
        raise ValueError("Allocation requires requirementsId and baseDraftId.")
    require_approved_requirements(messages)
    _, stored = _latest_result(messages, "set_workout_requirements")
    if stored.get("requirementsId") != arguments["requirementsId"] or not stored.get("requirements"):
        raise ValueError("The allocation requirementsId is missing, stale or not approved.")
    draft, draft_id = latest_draft_submission(messages, equipment)
    if draft is None or draft_id != arguments["baseDraftId"]:
        raise ValueError("The allocation baseDraftId is missing or stale.")
    if draft.get("requirementsId") != arguments["requirementsId"]:
        raise ValueError("The current draft was created under different requirements; re-audit it before allocating sets.")
    suggested_bounds = arguments.get('boundsBySlot', {})
    if not isinstance(suggested_bounds, dict):
        raise ValueError("boundsBySlot must map SLOT_n references to integer minimum/maximum bounds.")
    validate(draft, _DRAFT_SCHEMA)
    restrictions = effective_restrictions(stored, equipment)
    draft = normalize_work_set_bounds(draft, equipment, stored['requirements'])
    _, latest_audit = _latest_result(messages, 'audit_workout_plan')
    resolved_decisions = latest_audit.get('resolvedDecisions', {})
    history_fingerprint = latest_audit.get('historyFingerprint', getattr(training_history, 'fingerprint', None))
    input_fingerprint = allocation_input_fingerprint(draft, arguments['requirementsId'], equipment,
        history_fingerprint=history_fingerprint, resolved_decisions=resolved_decisions,
        allow_educated_load_guesses=allow_educated_load_guesses, requirements=stored['requirements'])
    relocation = arguments.get('reallocateAcrossSessions', False)
    if type(relocation) is not bool:
        raise ValueError('reallocateAcrossSessions must be a boolean.')
    if relocation:
        if arguments.get('preferredSetsBySlot') or arguments.get('boundsBySlot'):
            raise ValueError('Relocation changes slot identities; omit SLOT_n preferences and bounds.')
        from .joint_planning import solve_prescribed_week, prescription_patch
        joint = solve_prescribed_week(draft['workouts'], stored['requirements'], equipment, restrictions,
            allow_educated_load_guesses=allow_educated_load_guesses, training_history=training_history,
            messages=messages, balance=True)
        if not joint['feasible']:
            return _failure(joint['instruction'], jointPlanning={key: value for key, value in joint.items()
                            if key not in ('sessions', 'audit')})
        return {'feasible': True, 'requirementsId': arguments['requirementsId'], 'baseDraftId': draft_id,
            'scope': 'joint_selection_placement_prescriptions', 'reallocateAcrossSessions': True,
            'patch': prescription_patch(draft['workouts'], joint['sessions']),
            'proposedWorkouts': joint['sessions'], 'summary': joint['audit'],
            'nextStep': 'Combine this structural proposal with all other assessed repairs (progression, calibration, order and notes), then audit the full patch. This proposal does not mutate or approve the draft.'}
    _, previous_allocation = latest_allocation_conflict(messages)
    previous_conflict = previous_allocation.get('allocationConflict') if isinstance(previous_allocation, dict) else None
    if (isinstance(previous_conflict, dict) and previous_conflict.get('status') == 'infeasible'
            and previous_conflict.get('requirementsId') == arguments['requirementsId']
            and previous_conflict.get('baseDraftId') == draft_id
            and previous_conflict.get('inputFingerprint') == input_fingerprint):
        return _failure('This exact count-allocation problem was already proven infeasible. Change the exercise menu or another solver-relevant input, then re-audit; soft set preferences cannot change feasibility.',
            status='infeasible', requirementsId=arguments['requirementsId'], baseDraftId=draft_id,
            allocationConflict=copy.deepcopy(previous_conflict),
            conflictingTargets=copy.deepcopy(previous_conflict.get('conflictingTargets', [])))
    known = allocation_slots(draft)
    if set(suggested_bounds) - known.keys():
        raise ValueError('Unknown slot reference(s) in legacy boundsBySlot.')
    for value in suggested_bounds.values():
        if (not isinstance(value, dict) or set(value) != {'minimum', 'maximum'}
                or any(type(number) is not int for number in value.values())
                or not 1 <= value['minimum'] <= value['maximum'] <= _MAX_SETS):
            raise ValueError('Legacy boundsBySlot must contain integer ranges within 1-20; they are not hard constraints.')
    arguments = {**arguments, 'boundsBySlot': {
        slot: item.get('allocationBounds') or {'minimum': 1, 'maximum': _MAX_SETS} for slot, item in known.items()}}
    slots, variables = _variables(draft, arguments["boundsBySlot"])
    preferences = arguments.get('preferredSetsBySlot', {})
    if (not isinstance(preferences, dict) or set(preferences) - {slot['slotId'] for slot in slots}
            or any(not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= _MAX_SETS
                   for value in preferences.values())):
        raise ValueError('preferredSetsBySlot must map existing SLOT_n references to integer counts within 1-20.')
    for variable in variables:
        variable['current'] = [preferences.get(slot['slotId'], current)
                               for slot, current in zip(variable['members'], variable['current'])]
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

    status, counts = _milp_solve(variables, feature_constraints, balance=balance)
    if counts is None:
        if status == "infeasible":
            conflicting_targets = _conflicting_targets(variables, feature_constraints)
            conflict = {'status': 'infeasible', 'scope': 'count_allocation_for_current_draft',
                'requirementsId': arguments['requirementsId'], 'baseDraftId': draft_id,
                'conflictFingerprint': input_fingerprint, 'inputFingerprint': input_fingerprint,
                'libraryFingerprint': library_fingerprint(equipment),
                'historyFingerprint': history_fingerprint,
                'resolvedDecisions': copy.deepcopy(resolved_decisions),
                'allowEducatedLoadGuesses': bool(allow_educated_load_guesses),
                'conflictingTargets': copy.deepcopy(conflicting_targets)}
            return _failure("The current movements and approved count constraints cannot meet the numerical targets. Changing soft preferredSetsBySlot cannot change feasibility; do not repeat this allocator until permitted prescriptions or movements change. Re-audit that patch first. This does not establish that other movement selections are infeasible. The draft was left unchanged.",
                            status='infeasible', requirementsId=arguments['requirementsId'], baseDraftId=draft_id,
                            allocationConflict=conflict, allocationDiagnostics=[],
                            conflictingTargets=conflicting_targets)
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
    allocated_counts = {slot: value['numWorkSets'] for slot, value in allocation_slots(candidate).items()}
    differences = {slot: {'preferred': preferred, 'allocated': allocated_counts[slot]}
                   for slot, preferred in preferences.items() if allocated_counts[slot] != preferred}
    return {
        "feasible": True,
        "requirementsId": arguments["requirementsId"],
        "baseDraftId": draft_id,
        "patch": patch,
        "preferencesSatisfied": not differences,
        "summary": {
            "weeklyCoverageSets": exact_report.get('weeklyCoverageSets', {}),
            "preferenceDifferences": differences,
            "weeklyEffectiveSets": {muscle: values["effective"] for muscle, values in exact_report["weeklyVolume"].items()
                                     if muscle in requirements["auditTargets"].get("weeklyEffectiveSets", {})},
            "sessions": [{"name": item["name"], "estimatedSeconds": item["estimatedSeconds"],
                          "effectiveSets": {muscle: item["volume"][muscle]["effective"] for muscle in requirements["auditTargets"].get("perSessionEffectiveSets", {})}}
                         for item in exact_report["workouts"]],
            "completeWeek": frequency_complete,
        },
        "nextStep": ("The requested distribution was NOT achieved. This count-only tool cannot add, move or regroup exercise occurrences. Do not retry count preferences on the unchanged draft or apply this as a completed design repair. Combine necessary structural edits with all other assessed repairs, preserving approved constraints, and submit that coordinated patch for audit."
                     if differences else "Apply this patch together with any remaining assessed repairs, then audit the complete workout. This proposal does not mutate or approve the draft."),
    }


def allocate_workout_sets(arguments, equipment, messages, allow_educated_load_guesses=True, training_history=None, *, balance=False):
    """Return conflicts as non-mutating tool results; never turn them into a repair guess."""
    try:
        return _allocate_workout_sets(arguments, equipment, messages, allow_educated_load_guesses, training_history, balance=balance)
    except ValueError as error:
        return _failure(str(error))


def qualify_coordinated_candidate(client, arguments, equipment, messages, training_history=None, logger=None,
                                  coordinated_repair_context=None):
    """A complete repair delegates recipe contracts and numerical placement to their owners."""
    from .review_assessment import latest_assessment
    from .recipe_contracts import qualify_recipe_contracts
    from .exercise_library_tools import get_exercise_candidates
    from .planning_decisions import resolved_decisions
    require_approved_requirements(messages)
    _, stored = _latest_result(messages, 'set_workout_requirements')
    if 'patch' in arguments or 'baseDraftId' in arguments:
        # Qualification and joint solving must see the exact complete candidate,
        # even when the caller submitted the normal compact repair patch.
        from .planning_tools import _resolve_draft_submission
        arguments, _ = _resolve_draft_submission(arguments, messages, equipment)
    if 'workouts' not in arguments:
        return arguments, None
    if arguments.get('requirementsId') != stored.get('requirementsId'):
        raise ValueError('The coordinated candidate requirements are stale.')
    authority = {'requirementsId': arguments.get('requirementsId'), 'libraryFingerprint': library_fingerprint(equipment),
                 'historyFingerprint': getattr(training_history, 'fingerprint', None),
                 'resolvedDecisions': resolved_decisions(messages)}
    _, previous = _latest_result(messages, 'audit_workout_plan')
    assessment = latest_assessment(messages, authority, stored.get('requirements'), equipment or {})
    if assessment is None:
        # A reviewed draft may predate a metadata-only requirements refresh.
        # Reuse its findings as repair guidance only when the stored receipts
        # prove that source and resolved decisions did not change. The active
        # requirements below still own qualification and all later proof.
        previous_id = previous.get('requirementsId')
        previous_requirements = _requirements_receipt_for_id(messages, previous_id)
        if previous_id and previous_id != authority['requirementsId'] and previous_requirements:
            from .planning_tools import requirements_metadata_equivalent
            if (requirements_metadata_equivalent(previous_requirements, stored)
                    and all(previous.get(key) == authority[key] for key in (
                        'libraryFingerprint', 'historyFingerprint', 'resolvedDecisions'))):
                assessment = latest_assessment(messages, previous, stored.get('requirements'), equipment or {})
    validate(arguments, _DRAFT_SCHEMA)
    references = sorted({item['definition_id'] for day in arguments['workouts'] for item in day['exercises']})
    candidates = {}
    for start in range(0, len(references), 100):
        selected = get_exercise_candidates({'definition_ids': references[start:start + 100]}, equipment, messages)
        candidates.update((item['id'], item) for item in selected['exercises'])
    from .planning_tools import requirement_sources, source_message_context
    review_feedback_by_definition = _qualification_review_feedback(assessment, previous)
    qualification_fields_by_occurrence = {}
    ownership = coordinated_repair_context or {}
    initial_refs_by_workout = ownership.get('initialExerciseRefsByWorkout', {})
    for feedback in review_feedback_by_definition.values():
        for item in feedback:
            finding_index = item['findingIndex']
            dimensions = next((group.get('repairDimensions', []) for group in assessment.get('groups', [])
                if finding_index in group.get('findingIndexes', [])), [])
            path_parts = str(item['finding'].get('draftPath') or '').strip('/').split('/')
            if (len(path_parts) < 4 or path_parts[0] != 'workouts'
                    or not path_parts[1].isdigit() or path_parts[2] != 'exercises'
                    or not path_parts[3].isdigit()):
                continue
            workout_reference = f'WORKOUT_{int(path_parts[1])}'
            exercise_index = int(path_parts[3])
            exercise_refs = initial_refs_by_workout.get(workout_reference, [])
            if exercise_index >= len(exercise_refs):
                continue
            occurrence = exercise_refs[exercise_index]
            fields = qualification_fields_by_occurrence.setdefault(occurrence, set())
            field_path = path_parts[4:]
            if field_path and field_path[0] in ('satisfiesCoverage',):
                fields.add(field_path[0])
            elif not field_path:
                if 'coverage' in dimensions:
                    fields.add('satisfiesCoverage')
    prepared = {'definition_ids': references, 'candidates': candidates, 'libraryFingerprint': authority['libraryFingerprint'],
                'sourceMessages': source_message_context(requirement_sources(messages)),
                'reviewFeedbackByDefinition': review_feedback_by_definition}
    cached_qualification = _latest_recipe_qualification(messages)
    qualified = qualify_recipe_contracts(client, prepared, stored, equipment, messages,
        {'historyFingerprint': authority['historyFingerprint']}, cached_qualification, logger)
    contracts = {item['definition_id']: item for item in qualified['contracts']}
    candidate = copy.deepcopy(arguments)
    ownership = coordinated_repair_context or {}
    refs_by_workout = ownership.get('exerciseRefsByWorkout', {})
    workout_refs_by_position = ownership.get('workoutRefsByPosition', [])
    initial_definitions = ownership.get('initialDefinitionByExerciseRef', {})
    typed_edits = ownership.get('typedEdits', {})
    explicit = {}
    for update in typed_edits.get('exerciseUpdates', []):
        explicit[update['exerciseRef']] = set(update.get('setFields', {})) | set(update.get('removeOptionalFields', []))
    for addition in typed_edits.get('exerciseAdditions', []):
        explicit[addition['temporaryId']] = set(addition.get('exercise', {}))
    if ownership and (len(workout_refs_by_position) != len(candidate['workouts'])
            or any(len(refs_by_workout.get(workout_ref, [])) != len(day['exercises'])
                   for workout_ref, day in zip(workout_refs_by_position, candidate['workouts']))):
        raise ValueError('Coordinated repair references no longer match the compiled candidate.')
    for workout_index, day in enumerate(candidate['workouts']):
        workout_ref = workout_refs_by_position[workout_index] if ownership else None
        exercise_refs = refs_by_workout.get(workout_ref, []) if ownership else []
        for exercise_index, item in enumerate(day['exercises']):
            occurrence = exercise_refs[exercise_index] if ownership else None
            is_changed = ownership and (occurrence not in initial_definitions
                or initial_definitions.get(occurrence) != item.get('definition_id'))
            explicitly_owned = explicit.get(occurrence, set())
            owned_fields = ({'satisfiesCoverage'} if is_changed
                else qualification_fields_by_occurrence.get(occurrence, set()))
            owned_fields -= explicitly_owned
            if not owned_fields:
                continue
            contract = contracts[item['definition_id']]
            # Apply defaults only to new/changed recipes or the exact recipe
            # fields an independent finding assigned to qualification. Submitted
            # values/removals remain authoritative.
            for field in ('satisfiesCoverage',):
                if field not in owned_fields:
                    continue
                item.pop(field, None)
                if field in contract:
                    item[field] = copy.deepcopy(contract[field])
    return candidate, qualified


def _qualification_review_feedback(assessment, audit_result):
    """Route only repair findings owned by recipe qualification to their source exercise."""
    review = audit_result.get('review') or {}
    attached = review.get('assessment') or audit_result.get('findingsAssessment')
    if not assessment or attached != assessment:
        return {}
    draft = audit_result.get('submittedDraft') or {}
    findings = review.get('findings') or []
    exercises = draft.get('workouts') or []
    feedback = {}
    owned_fields = {'satisfiesCoverage'}
    for group in assessment.get('groups', []):
        if group.get('disposition') != 'repair':
            continue
        for finding_index in group.get('findingIndexes', []):
            if not isinstance(finding_index, int) or not 0 <= finding_index < len(findings):
                continue
            finding = findings[finding_index]
            parts = str(finding.get('draftPath') or '').strip('/').split('/')
            if (len(parts) < 4 or parts[0] != 'workouts' or parts[2] != 'exercises'
                    or not parts[1].isdigit() or not parts[3].isdigit()):
                continue
            day_index, exercise_index = int(parts[1]), int(parts[3])
            try:
                reference = exercises[day_index]['exercises'][exercise_index]['definition_id']
            except (IndexError, KeyError, TypeError):
                continue
            field_path = parts[4:]
            if field_path and field_path[0] not in owned_fields:
                continue
            feedback.setdefault(reference, []).append({
                'findingIndex': finding_index,
                'reason': group.get('reason', ''),
                'finding': copy.deepcopy(finding),
            })
    return feedback


def _requirements_receipt_for_id(messages, requirements_id):
    """Find a stored approved-requirement receipt by identity, not merely latest."""
    calls = {call.get('id') for message in messages for call in message.get('tool_calls', [])
             if call.get('function', {}).get('name') in ('set_workout_requirements', 'accept_workout_alternative')}
    for message in reversed(messages):
        if message.get('role') != 'tool' or message.get('tool_call_id') not in calls:
            continue
        try:
            result = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            continue
        if (isinstance(result, dict) and result.get('requirementsId') == requirements_id
                and isinstance(result.get('requirements'), dict)):
            return result
    return None


def _latest_recipe_qualification(messages):
    """Recover the newest reusable contracts from any retained tool receipt."""
    for message in reversed(messages):
        if message.get('role') != 'tool':
            continue
        try:
            result = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            continue
        qualification = result.get('recipeQualification') if isinstance(result, dict) else None
        if not isinstance(qualification, dict) or not isinstance(qualification.get('inputHashes'), dict):
            continue
        contracts = qualification.get('contracts')
        if (isinstance(contracts, list) and all(isinstance(item, dict)
                and isinstance(item.get('definition_id'), str)
                and isinstance(item.get('satisfiesCoverage'), list) for item in contracts)):
            return copy.deepcopy(qualification)
    return None


def reusable_joint_receipt(owner, requirements_id, sessions, requirements, equipment, messages, training_history=None,
                           restriction_policy=None, allow_educated_load_guesses=True,
                           preserve_source_selection=False, redistribution_constraints=None):
    """Return prior solver evidence only when the same approved objective still owns this prescription."""
    from .joint_planning import (SELECTION_POLICY_VERSION, joint_objective_input_fingerprint)
    receipt = owner.get('coordinatedJointPlanning') or owner.get('automaticAllocation') or {}
    from .planning_tools import library_fingerprint
    expected_policy = 'approved' if requirements.get('objectiveOrder') is not None else 'preserve_candidate_only'
    # Generic objective identity cannot establish a solve performed under additional repair constraints.
    if (receipt.get('feasible') is not True or receipt.get('status') not in ('feasible', 'optimal')
            or (receipt.get('redistributionOptimization') and not redistribution_constraints)
            or receipt.get('selectionPolicyVersion') != SELECTION_POLICY_VERSION
            or receipt.get('preserveSourceSelection') is not bool(preserve_source_selection)
            or receipt.get('objectivePolicy') != expected_policy
            or receipt.get('approvedObjectiveOrder') != requirements.get('objectiveOrder')
            or owner.get('requirementsId') != requirements_id
            or owner.get('libraryFingerprint') != library_fingerprint(equipment)
            or owner.get('historyFingerprint') != getattr(training_history, 'fingerprint', None)):
        return None
    expected = joint_objective_input_fingerprint(sessions, requirements, equipment, training_history, messages,
        restriction_policy=restriction_policy,
        allow_educated_load_guesses=allow_educated_load_guesses,
        preserve_source_selection=preserve_source_selection,
        redistribution_constraints=redistribution_constraints)
    if receipt.get('objectiveInputFingerprint') != expected:
        return None
    return copy.deepcopy(receipt)


def auto_allocate_workout(result, equipment, messages, allow_educated_load_guesses=True, training_history=None, logger=None, progress=None):
    """Jointly solve complete prescriptions; after preview return a proposal only."""
    numeric = {'duration_exceeded', 'volume_below_target', 'volume_above_target', 'superset_set_count_mismatch'}
    draft = result.get('submittedDraft')
    if not draft:
        return result
    _, stored = _latest_result(messages, 'set_workout_requirements')
    needs_numbers = any(e.get('code') in numeric for e in result.get('errors', []))
    objective_order = set(stored.get('requirements', {}).get('objectiveOrder') or [])
    balance_rules = [rule for rule in stored.get('requirements', {}).get('executionRules', []) if rule['kind'] == 'coverageBalance']
    report = result.get('audit', {})
    needs_balance = 'source_balance' in objective_order and any(any(
        (values.get(rule['first'], 0) < values.get(rule['second'], 0)
            if rule.get('relationship') == 'first_not_less_than_second'
            else values.get(rule['first'], 0) != values.get(rule['second'], 0)) for values in (
        [report.get('weeklyCoverageSets', {})] if rule['scope'] == 'weekly' else
        [day.get('coverageSets', {}) for day in report.get('workouts', [])])) for rule in balance_rules)
    from .joint_planning import (solve_prescribed_week, prescription_patch, prescription_fingerprint,
        joint_problem_fingerprint, SELECTION_POLICY_VERSION)
    _, previous = _latest_result(messages, 'audit_workout_plan')
    _, workers = _latest_result(messages, 'draft_workout_sessions')
    automatic = not any(message.get('canonicalDraftPreview') for message in messages)
    proofs = [(previous.get('automaticAllocation', {}), previous), (workers.get('jointPlanning', {}), workers)]
    requirements = stored.get('requirements', {})
    restrictions = effective_restrictions(stored, equipment)

    def solved_receipt_matches(proof, owner):
        if proof.get('selectionPolicyVersion') != SELECTION_POLICY_VERSION:
            return False
        receipt_owner = {**owner, 'coordinatedJointPlanning': proof}
        receipt = reusable_joint_receipt(receipt_owner, result['requirementsId'], draft['workouts'],
            requirements, equipment, messages, training_history, restrictions,
                        allow_educated_load_guesses, False)
        return bool(receipt and proof.get('solvedPrescriptionHash') == prescription_fingerprint(draft['workouts']))

    already_solved = any(solved_receipt_matches(proof, owner) for proof, owner in proofs)
    needs_balance = needs_balance and not already_solved
    needs_distribution = False
    if automatic and not already_solved and 'distribution' in objective_order:
        frequency = sum(day['timesCompletedInAWeek'] for day in draft['workouts'])
        targets = requirements['auditTargets']
        muscles = set(targets.get('weeklyEffectiveSets', {})) | set(targets.get('perSessionEffectiveSets', {}))
        needs_distribution = bool(frequency) and any(
            abs(day.get('volume', {}).get(muscle, {}).get('effective', 0)
                - report.get('weeklyVolume', {}).get(muscle, {}).get('effective', 0) / frequency) > _TOLERANCE
            for day in report.get('workouts', []) for muscle in muscles)
    durations = [day['estimatedSeconds'] for day in report.get('workouts', [])]
    needs_duration_balance = (automatic and not already_solved and 'duration_balance' in objective_order
                              and len(durations) > 1 and max(durations) - min(durations) > _TOLERANCE)
    if not needs_numbers and not needs_balance and not needs_distribution and not needs_duration_balance:
        return result
    sessions = stored.get('requirements', {}).get('sessionsPerWeek')
    if sessions and sum(day['timesCompletedInAWeek'] for day in draft['workouts']) != sessions:
        return result
    cached = previous.get('automaticAllocation', {})
    application = 'automatic' if automatic else 'proposal'
    current_problem_fingerprint = joint_problem_fingerprint(draft['workouts'], requirements, equipment,
        training_history, messages, restriction_policy=restrictions,
        allow_educated_load_guesses=allow_educated_load_guesses,
        preserve_source_selection=False)
    if (cached.get('inputDraftId') == result['draftId'] and cached.get('objective') == 'joint_prescriptions'
            and cached.get('application') == application and cached.get('selectionPolicyVersion') == SELECTION_POLICY_VERSION
            and cached.get('preserveSourceSelection') is False
            and cached.get('problemFingerprint') == current_problem_fingerprint):
        return {**result, 'automaticAllocation': copy.deepcopy(cached), **(
            {'jointPlanningStopped': True, 'instruction': cached['instruction']} if not cached['feasible'] else {})}
    if progress:
        progress('Solving prescriptions, placement, volume and duration together')
    joint = solve_prescribed_week(draft['workouts'], stored['requirements'], equipment,
        restrictions, allow_educated_load_guesses=allow_educated_load_guesses,
        training_history=training_history, messages=messages,
        preserve_source_selection=False)
    patch = prescription_patch(draft['workouts'], joint['sessions'], joint.get('occurrenceLineage')) if joint['feasible'] else []
    receipt = {'inputDraftId': result['draftId'], 'objective': 'joint_prescriptions', 'application': application,
               **{key: value for key, value in joint.items() if key not in ('sessions', 'audit')}, 'patch': patch}
    if logger:
        logger.log_response('automatic_joint_planning', json.dumps(receipt), truncate_at=0)
    if automatic and joint['feasible'] and patch:
        baseline = messages + [
            {'role': 'assistant', 'tool_calls': [{'id': 'auto_allocation_base', 'function': {'name': 'audit_workout_plan'}}]},
            {'role': 'tool', 'tool_call_id': 'auto_allocation_base', 'content': json.dumps(result)}]
        result = audit_workout_plan({'requirementsId': result['requirementsId'], 'baseDraftId': result['currentDraftId'],
            'patch': patch}, equipment, baseline, allow_educated_load_guesses, training_history)
    if not joint['feasible']:
        result = {**result, 'jointPlanningStopped': True, 'instruction': joint['instruction']}
    return {**result, 'automaticAllocation': receipt}
