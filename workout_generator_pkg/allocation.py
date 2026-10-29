"""Deterministic working-set allocation against the existing workout audit."""

from __future__ import annotations

import copy
import hashlib
import math
import json
import time

from scipy.optimize import Bounds, LinearConstraint, OptimizeResult, linprog, milp
from scipy.sparse import coo_matrix

from .generation_audit import (ASSUMPTIONS, audit_workout_package, plan_audit_package,
                              family_set_audit_options, volume_target_bounds)
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
# One tolerance governs solver-boundary normalization and feasibility checks.
_MILP_SOLUTION_TOLERANCE = 1e-6


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
    for family, sets in report.get('weeklyFamilyWorkingSets', {}).items():
        features[('family', family)] = float(sets)
    for definition_id, exposure in report.get('weeklyExerciseExposure', {}).items():
        features[('exercise_sessions', definition_id)] = float(exposure['weeklySessions'])
        features[('exercise_weekly_sets', definition_id)] = float(exposure['weeklyWorkingSets'])
    return features


def _audit_raw(draft, equipment, requirements, restriction_policy, allow_educated_load_guesses, *,
               apply_family_bounds=True):
    plan = build_draft_plan(draft, equipment, requirements, restriction_policy)
    family_options = family_set_audit_options(requirements, equipment)
    if not apply_family_bounds:
        family_options.pop('family_set_requirements', None)
        family_options.pop('family_by_reference', None)
    report = audit_workout_package(plan_audit_package(plan, allow_educated_load_guesses), requirements["auditTargets"],
                                  coverage_by_exercise=draft_coverage_assignments(plan, draft),
                                  **family_options)
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
            minimum, maximum = volume_target_bounds(bounds)
            rows.append((("session", index, muscle), float(minimum), float(maximum)))
        if targets.get("maximumSessionSeconds") is not None:
            rows.append((("duration", index), -math.inf, float(targets["maximumSessionSeconds"])))
    sessions_per_week = requirements.get("sessionsPerWeek")
    if sessions_per_week is not None and frequency_complete and draft_frequency != sessions_per_week:
        raise ValueError(f"Draft frequency is {draft_frequency}; requirements specify {sessions_per_week} sessions per week.")
    for muscle, bounds in targets.get("weeklyEffectiveSets", {}).items():
        minimum, maximum = volume_target_bounds(bounds)
        rows.append((("weekly", muscle), float(minimum) if frequency_complete else -math.inf,
                     float(maximum)))
    for bound in requirements.get('familySetBounds', []):
        rows.append((('family', bound['exerciseFamilyId']),
            float(bound.get('minimumWeeklySets', -math.inf)) if frequency_complete else -math.inf,
            float(bound.get('maximumWeeklySets', math.inf))))
    exposure_rule = next((rule for rule in requirements.get('executionRules', [])
        if rule.get('kind') == 'exerciseExposure'), None)
    if exposure_rule:
        for definition_id in report.get('weeklyExerciseExposure', {}):
            if 'maximumSessionsPerWeek' in exposure_rule:
                rows.append((('exercise_sessions', definition_id), -math.inf,
                    float(exposure_rule['maximumSessionsPerWeek'])))
            if 'maximumWeeklySets' in exposure_rule:
                rows.append((('exercise_weekly_sets', definition_id), -math.inf,
                    float(exposure_rule['maximumWeeklySets'])))
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


def _canonicalize_milp_values(values, integrality, lower, upper, minimum_when_selected=None):
    """Snap only solver-scale integer and bound noise; leave row validation to the source model."""
    if values is None or len(values) != len(lower):
        return None, {'reason': 'invalid_solution_size', 'expected': len(lower),
                      'actual': len(values) if values is not None else None}
    canonical = []
    for index, (raw, integer, low, high) in enumerate(zip(values, integrality, lower, upper)):
        value = float(raw)
        if not math.isfinite(value):
            return None, {'reason': 'non_finite_variable', 'index': index, 'value': str(raw)}
        if integer:
            nearest = round(value)
            if abs(value - nearest) > _MILP_SOLUTION_TOLERANCE:
                return None, {'reason': 'invalid_integrality', 'index': index, 'value': value,
                              'nearestInteger': nearest}
            value = nearest
        else:
            for bound in (low, high):
                if math.isfinite(bound) and abs(value - bound) <= _MILP_SOLUTION_TOLERANCE:
                    value = float(bound)
                    break
            selected_minimum = (minimum_when_selected[index]
                                if minimum_when_selected is not None else None)
            if (value != 0 and selected_minimum is not None and math.isfinite(selected_minimum)
                    and abs(value - selected_minimum) <= _MILP_SOLUTION_TOLERANCE):
                value = float(selected_minimum)
        if value < low or value > high:
            return None, {'reason': 'variable_outside_bounds', 'index': index, 'value': value,
                          'lower': float(low) if math.isfinite(low) else None,
                          'upper': float(high) if math.isfinite(high) else None}
        canonical.append(value)
    return canonical, None


def _first_milp_row_violation(rows, values, lower, upper, identities):
    for index, (coefficients, low, high) in enumerate(zip(rows, lower, upper)):
        value = math.fsum(coefficient * values[column] for column, coefficient in coefficients.items())
        if not math.isfinite(value):
            return {'index': index, 'identity': identities[index], 'value': str(value),
                    'lower': float(low) if math.isfinite(low) else None,
                    'upper': float(high) if math.isfinite(high) else None,
                    'slack': None, 'violation': None}
        below = low - value if math.isfinite(low) else 0.0
        above = value - high if math.isfinite(high) else 0.0
        violation = max(below, above, 0.0)
        if violation > _MILP_SOLUTION_TOLERANCE:
            slack = min(value - low if math.isfinite(low) else math.inf,
                        high - value if math.isfinite(high) else math.inf)
            return {'index': index, 'identity': identities[index], 'value': value,
                    'lower': float(low) if math.isfinite(low) else None,
                    'upper': float(high) if math.isfinite(high) else None,
                    'slack': float(slack), 'violation': float(violation)}
    return None


def _count_series_affine(values, counts):
    if len(values) != len(counts) or len(counts) < 2:
        return None
    slope = (values[-1] - values[0]) / (counts[-1] - counts[0])
    intercept = values[0] - slope * counts[0]
    if all(math.isclose(value, intercept + slope * count, rel_tol=0, abs_tol=1e-10)
           for value, count in zip(values, counts)):
        return slope, intercept
    return None


def _count_series_affine_sparse(position_values, counts):
    """Prove an affine row from its nonzero series coefficients only."""
    if len(counts) < 2:
        return None
    last = len(counts) - 1
    first_value = position_values.get(0, 0.0)
    last_value = position_values.get(last, 0.0)
    slope = (last_value - first_value) / (counts[last] - counts[0])
    intercept = first_value - slope * counts[0]
    for position, value in position_values.items():
        if not math.isclose(value, intercept + slope * counts[position], rel_tol=0, abs_tol=1e-10):
            return None

    # Any omitted coefficient is exactly zero. An affine function's absolute
    # maximum over the omitted positions lies at the first or last omission.
    known = sorted(position_values)
    first_missing = 0
    for position in known:
        if position != first_missing:
            break
        first_missing += 1
    if first_missing <= last:
        last_missing = last
        for position in reversed(known):
            if position != last_missing:
                break
            last_missing -= 1
        if (not math.isclose(0.0, intercept + slope * counts[first_missing], rel_tol=0,
                             abs_tol=1e-10)
                or not math.isclose(0.0, intercept + slope * counts[last_missing], rel_tol=0,
                                    abs_tol=1e-10)):
            return None
    return slope, intercept


def _csr_matrix_from_rows(rows, column_count):
    row_indexes, column_indexes, values = [], [], []
    for row_index, row in enumerate(rows):
        for column, value in row.items():
            if value:
                row_indexes.append(row_index)
                column_indexes.append(column)
                values.append(value)
    return coo_matrix((values, (row_indexes, column_indexes)),
                      shape=(len(rows), column_count), dtype=float).tocsr()


def _compile_count_series(objective, integrality, lower, upper, constraints, lows, highs,
                          initial_values, variables, primary_count, balance=False):
    """Replace eligible one-hot count tables with an equivalent integer count column."""
    import numpy as np

    if balance:
        return None
    groups = {}
    for index, variable in enumerate(variables):
        if 'countSeriesKey' not in variable and 'countSeriesValue' not in variable:
            continue
        try:
            key, count = variable['countSeriesKey'], variable['countSeriesValue']
            hash(key)
        except (KeyError, TypeError):
            continue
        if index >= primary_count or type(count) is not int or count < 1:
            continue
        groups.setdefault(key, []).append((count, index))
    if not groups:
        return None
    matrix = constraints.A.tocsr()
    column_matrix = matrix.tocsc()
    sparse_rows = [dict(zip(matrix.indices[matrix.indptr[index]:matrix.indptr[index + 1]],
                            matrix.data[matrix.indptr[index]:matrix.indptr[index + 1]]))
                   for index in range(matrix.shape[0])]
    eligible = {}
    for key, entries in groups.items():
        entries.sort()
        counts = [count for count, _ in entries]
        indices = [index for _, index in entries]
        if (len(counts) < 2 or len(set(counts)) != len(counts)
                or counts != list(range(counts[0], counts[-1] + 1))
                or any(lower[index] != 0 or upper[index] != 1 or integrality[index] != 1
                       or variables[index].get('minimumWhenSelected', 1) != 1
                       or variables[index].get('selectionCost', 0) for index in indices)):
            continue
        if initial_values is not None:
            starts = [initial_values[index] for index in indices]
            if (any(not math.isclose(value, round(value), rel_tol=0, abs_tol=_TOLERANCE)
                    for value in starts) or sum(round(value) for value in starts) > 1):
                continue
        index_set = set(indices)
        row_values = {}
        for position, index in enumerate(indices):
            start, end = column_matrix.indptr[index:index + 2]
            for row_index, value in zip(column_matrix.indices[start:end], column_matrix.data[start:end]):
                if value:
                    row_values.setdefault(int(row_index), {})[position] = float(value)
        affine_rows = [(0.0, 0.0)] * matrix.shape[0]
        valid = True
        for row_index, values in row_values.items():
            affine = _count_series_affine_sparse(values, counts)
            if affine is None:
                valid = False
                break
            affine_rows[row_index] = affine
        objective_affine = _count_series_affine([objective[index] for index in indices], counts)
        if not valid or objective_affine is None:
            continue
        certified = False
        for row_index, series_values in row_values.items():
            coefficients = sparse_rows[row_index]
            if (len(series_values) != len(indices)
                    or not all(value == 1 for value in series_values.values())
                    or lows[row_index] < 0 or highs[row_index] > 1):
                continue
            if all(value >= 0 and lower[index] >= 0
                   for index, value in coefficients.items() if index not in index_set):
                certified = True
                break
        if certified:
            eligible[key] = {'indices': indices, 'counts': counts,
                'objective': objective_affine, 'rows': affine_rows}
    if not eligible:
        return None

    removed = {index for group in eligible.values() for index in group['indices']}
    old_to_new = {}
    new_lower, new_upper, new_integrality = [], [], []
    for index in range(len(objective)):
        if index in removed:
            continue
        old_to_new[index] = len(new_lower)
        new_lower.append(lower[index]); new_upper.append(upper[index]); new_integrality.append(integrality[index])
    for group in eligible.values():
        group['selection'] = len(new_lower)
        new_lower.append(0); new_upper.append(1); new_integrality.append(1)
        group['count'] = len(new_lower)
        new_lower.append(0); new_upper.append(group['counts'][-1]); new_integrality.append(1)
    new_objective = [objective[index] for index in range(len(objective)) if index not in removed]
    for group in eligible.values():
        slope, intercept = group['objective']
        new_objective.extend((intercept, slope))

    new_rows, new_lows, new_highs = [], list(lows), list(highs)
    for row_index, coefficients in enumerate(sparse_rows):
        transformed = {old_to_new[index]: value for index, value in coefficients.items() if index in old_to_new}
        for group in eligible.values():
            slope, intercept = group['rows'][row_index]
            if intercept:
                transformed[group['selection']] = transformed.get(group['selection'], 0) + intercept
            if slope:
                transformed[group['count']] = transformed.get(group['count'], 0) + slope
        new_rows.append(transformed)
    for group in eligible.values():
        selection, count = group['selection'], group['count']
        new_rows.extend(({selection: -group['counts'][0], count: 1},
                         {selection: -group['counts'][-1], count: 1}))
        new_lows.extend((0, -math.inf)); new_highs.extend((math.inf, 0))
    new_matrix = _csr_matrix_from_rows(new_rows, len(new_lower))
    new_constraints = LinearConstraint(new_matrix, new_lows, new_highs)
    reduced_start = None
    if initial_values is not None:
        reduced_start = [initial_values[index] for index in range(len(objective)) if index not in removed]
        for group in eligible.values():
            selected = [(count, index) for count, index in zip(group['counts'], group['indices'])
                        if round(initial_values[index])]
            reduced_start.extend((1, selected[0][0]) if selected else (0, 0))
        activities = new_matrix @ reduced_start
        if (any(not math.isfinite(value) or
                (integer and abs(value - round(value)) > _MILP_SOLUTION_TOLERANCE)
                or not low - _MILP_SOLUTION_TOLERANCE <= value <= high + _MILP_SOLUTION_TOLERANCE
                for value, low, high, integer in zip(reduced_start, new_lower, new_upper, new_integrality))
                or any(not low - _MILP_SOLUTION_TOLERANCE <= value <= high + _MILP_SOLUTION_TOLERANCE
                       for value, low, high in zip(activities, new_lows, new_highs))):
            return None

    def restore(values):
        if values is None or len(values) != len(new_lower):
            return None
        expanded = [0.0] * len(objective)
        for old, new in old_to_new.items():
            expanded[old] = values[new]
        for group in eligible.values():
            selection = values[group['selection']]
            count = values[group['count']]
            if (not math.isclose(selection, round(selection), rel_tol=0,
                                 abs_tol=_MILP_SOLUTION_TOLERANCE)
                    or not math.isclose(count, round(count), rel_tol=0,
                                        abs_tol=_MILP_SOLUTION_TOLERANCE)):
                return None
            selection, count = round(selection), round(count)
            if round(selection):
                if count not in group['counts']:
                    return None
                expanded[group['indices'][group['counts'].index(count)]] = 1
            elif count != 0:
                return None
        return expanded

    return {'objective': new_objective, 'integrality': new_integrality,
        'bounds': Bounds(new_lower, new_upper),
        'constraints': new_constraints,
        'initialValues': reduced_start, 'restore': restore,
        'inputColumns': len(objective), 'solverColumns': len(new_lower), 'seriesCount': len(eligible)}


def _milp_solve(variables, features, timeout_seconds=60, balance=False, preserve_current=True,
                diagnostics=None, incumbent=None, presence_caps=None):
    started = time.perf_counter()
    build_seconds = 0.0
    assembly_seconds = 0.0
    count_series_seconds = 0.0
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
                'modelAssemblySeconds': assembly_seconds,
                'countSeriesCompileSeconds': count_series_seconds,
                'solveSeconds': solver_seconds,
                'returnReason': reason,
            })
        return status, candidate

    count = len(variables)
    if not count:
        if (any(intercept < minimum - _TOLERANCE or intercept > maximum + _TOLERANCE
                for _, minimum, maximum, intercept, _ in features)
                or any(not cap['groups'] and cap['maximum'] < 0 for cap in (presence_caps or []))):
            return finish('infeasible', None, 'empty_domain_constraints')
        return finish("optimal", [], 'empty_variable_domain', validated=True)
    # Use one integer set-count variable and one deviation variable per exercise occurrence.
    occurrence_count = sum(len(variable["members"]) for variable in variables)
    objective = [variable.get('objectiveCost', 0.0) for variable in variables] + [1.0 if preserve_current else 0.0] * occurrence_count
    lower = [variable["lower"] for variable in variables] + [0.0] * occurrence_count
    upper = [variable["upper"] for variable in variables] + [math.inf] * occurrence_count
    integrality = [int(variable.get('integer', True)) for variable in variables] + [0] * occurrence_count
    variable_identities = [variable.get('domainIdentity') or {'kind': 'decision_variable', 'index': index}
        for index, variable in enumerate(variables)]
    for variable_index, variable in enumerate(variables):
        for member_index, member in enumerate(variable['members']):
            variable_identities.append({'kind': 'preservation_deviation', 'variableIndex': variable_index,
                'slotId': member.get('slotId'), 'memberIndex': member_index})
    if balance:
        # Initial counts are seeds, not prescriptions: minimize concentration before distance from those seeds.
        epsilon = 1 / (1 + sum(max(abs(v['lower'] - current), abs(v['upper'] - current))
                               for v in variables for current in v['current']))
        objective = [0.0] * count + [epsilon] * occurrence_count + [len(v['members']) for v in variables]
        lower += [v['lower'] ** 2 for v in variables]
        upper += [v['upper'] ** 2 for v in variables]
        integrality += [0] * count
        variable_identities.extend({'kind': 'squared_count', 'variableIndex': index}
                                   for index in range(count))
    activations = {}
    presence_caps = presence_caps or []
    presence_member_indexes = {index for cap in presence_caps for group, _ in cap['groups'] for index in group}
    for index, variable in enumerate(variables):
        if (variable.get('minimumWhenSelected', 1) > 1 or variable.get('selectionCost')
                or index in presence_member_indexes):
            activations[index] = len(objective)
            objective.append(variable.get('selectionCost', 0.0))
            lower.append(0)
            upper.append(1)
            integrality.append(1)
            variable_identities.append({'kind': 'activation', 'variableIndex': index})
    presence_variables = []
    for cap_index, cap in enumerate(presence_caps):
        group_variables = []
        for group_index, (members, frequency) in enumerate(cap['groups']):
            active_index = len(objective)
            objective.append(0.0)
            lower.append(0)
            upper.append(1)
            integrality.append(1)
            variable_identities.append({'kind': 'exercise_session_presence',
                'definitionId': cap['definitionId'], 'groupIndex': group_index})
            group_variables.append((active_index, members, frequency))
        presence_variables.append((cap, group_variables))
    size = len(objective)
    rows = []
    lows = []
    highs = []
    row_identities = []
    for feature, minimum, maximum, intercept, coefficients in features:
        rows.append(dict(coefficients) if isinstance(coefficients, dict) else dict(enumerate(coefficients)))
        lows.append(minimum - intercept)
        highs.append(maximum - intercept)
        row_identities.append(feature)
    for index, activation in activations.items():
        for limit, low, high in ((variables[index].get('minimumWhenSelected', 1), 0, math.inf),
                                 (variables[index]['upper'], -math.inf, 0)):
            row = {index: 1, activation: -limit}
            rows.append(row)
            lows.append(low)
            highs.append(high)
            row_identities.append(('activation_minimum_when_selected' if math.isfinite(low)
                                   else 'activation_upper_bound', index))
    for cap, groups in presence_variables:
        cap_row = {}
        for active, members, frequency in groups:
            cap_row[active] = frequency
            member_activations = [activations[index] for index in members]
            rows.append({active: 1, **{index: -1 for index in member_activations}})
            lows.append(-math.inf)
            highs.append(0)
            row_identities.append(('exercise_session_requires_occurrence', cap['definitionId']))
            rows.append({**{index: 1 for index in member_activations}, active: -len(member_activations)})
            lows.append(-math.inf)
            highs.append(0)
            row_identities.append(('exercise_occurrence_requires_session', cap['definitionId']))
        rows.append(cap_row)
        lows.append(-math.inf)
        highs.append(cap['maximum'])
        row_identities.append(('exercise_session_cap', cap['definitionId']))
    dev_index = count
    for variable_index, variable in enumerate(variables):
        for member_index, current in enumerate(variable["current"]):
            positive = {variable_index: 1, dev_index: -1}
            rows.append(positive)
            lows.append(-math.inf)
            highs.append(current)
            row_identities.append(('preservation_deviation_positive', variable_index, member_index))
            negative = {variable_index: -1, dev_index: -1}
            rows.append(negative)
            lows.append(-math.inf)
            highs.append(-current)
            row_identities.append(('preservation_deviation_negative', variable_index, member_index))
            dev_index += 1
    if balance:
        for index, variable in enumerate(variables):
            for step in range(variable['lower'], variable['upper']):
                row = {index: 2 * step + 1, count + occurrence_count + index: -1}
                rows.append(row)
                lows.append(-math.inf)
                highs.append(step * (step + 1))
                row_identities.append(('squared_count_epigraph', index, step))
    matrix = _csr_matrix_from_rows(rows, size)
    options = {"mip_rel_gap": 0.0} if balance else {}
    if timeout_seconds is not None:
        options['time_limit'] = timeout_seconds
    constraint_matrix = matrix
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
        initial_values.extend(int(any(incumbent[index] for index in members))
            for _, groups in presence_variables for _, members, _ in groups)
        initial_values, variable_error = _canonicalize_milp_values(initial_values, integrality, lower, upper,
            [variable.get('minimumWhenSelected', variable['lower']) for variable in variables]
            + [None] * (len(initial_values) - count))
        row_error = (_first_milp_row_violation(rows, initial_values, lows, highs, row_identities)
                     if initial_values is not None else None)
        if variable_error or row_error:
            raise ValueError('The incumbent violates the current bounds, integrality, or constraints.')
    if diagnostics is not None and initial_values is not None:
        diagnostics['incumbentSupplied'] = True
        diagnostics['backend'] = 'highspy'
    original_lower, original_upper, original_integrality = lower, upper, integrality
    original_selected_minimum = [variable.get('minimumWhenSelected', variable['lower'])
                                 for variable in variables] + [None] * (len(lower) - count)
    assembly_seconds = time.perf_counter() - started
    count_series_started = time.perf_counter()
    compiled = (None if presence_caps else _compile_count_series(objective, integrality, lower, upper, constraints,
        lows, highs, initial_values, variables, count, balance))
    count_series_seconds = time.perf_counter() - count_series_started
    if compiled is not None:
        objective, integrality = compiled['objective'], compiled['integrality']
        bounds, constraints, initial_values = compiled['bounds'], compiled['constraints'], compiled['initialValues']
        if diagnostics is not None:
            diagnostics.update({'countSeriesCompressed': True,
                'countSeriesInputColumns': compiled['inputColumns'],
                'countSeriesSolverColumns': compiled['solverColumns'],
                'countSeriesCount': compiled['seriesCount']})
    solver_started = time.perf_counter()
    build_seconds = solver_started - started
    solve_started = time.perf_counter()
    result = (milp(objective, integrality=integrality, bounds=bounds,
                   constraints=constraints, options=options) if initial_values is None else
              _milp_with_incumbent(objective, integrality, bounds, constraints, options, initial_values))
    solver_seconds = time.perf_counter() - solve_started
    if compiled is not None and result.x is not None:
        reduced_values, reduced_error = _canonicalize_milp_values(result.x, integrality, bounds.lb, bounds.ub)
        restored = compiled['restore'](reduced_values) if reduced_values is not None else None
        if restored is None:
            if diagnostics is not None:
                diagnostics['countSeriesReconstructionFailed'] = True
                if reduced_error:
                    diagnostics['rejectedVariable'] = reduced_error
            result.status, result.message, result.x = 1, 'Count-series solution could not be losslessly reconstructed.', None
        else:
            result.x = restored
    if result.status == 2:
        return finish("infeasible", None, 'solver_infeasible', result)
    if result.x is None or result.status not in (0, 1):
        return finish("unproven", None, 'no_incumbent' if result.x is None else 'unsupported_solver_status', result)
    canonical, variable_error = _canonicalize_milp_values(
        result.x, original_integrality, original_lower, original_upper, original_selected_minimum)
    if canonical is None:
        error_index = variable_error.get('index')
        if error_index is not None and error_index < count and variable_error['reason'] == 'variable_outside_bounds':
            variable = variables[error_index]
            rejected = {'index': error_index, 'identity': variable_identities[error_index],
                'slotIds': [member.get('slotId') for member in variable.get('members', [])
                            if member.get('slotId') is not None],
                'value': variable_error['value'], 'lower': variable_error['lower'],
                'upper': variable_error['upper'],
                'minimumWhenSelected': float(variable.get('minimumWhenSelected', variable['lower']))}
            reason = 'count_outside_bounds'
        else:
            rejected = {**variable_error,
                'identity': variable_identities[error_index] if error_index is not None else None}
            reason = ('invalid_count_value' if variable_error['reason'] == 'invalid_integrality'
                      else variable_error['reason'])
        if diagnostics is not None:
            diagnostics['rejectedVariable'] = rejected
        return finish('unproven', None, reason, result)
    counts = canonical[:count]
    for index, (variable, value) in enumerate(zip(variables, counts)):
        if (not variable['lower'] <= value <= variable['upper']
                or (value != 0 and value < variable.get('minimumWhenSelected', variable['lower']))):
            if diagnostics is not None:
                diagnostics['rejectedVariable'] = {
                    'index': index,
                    'identity': variable.get('domainIdentity'),
                    'slotIds': [member.get('slotId') for member in variable.get('members', [])
                                if member.get('slotId') is not None],
                    'value': float(value),
                    'lower': float(variable['lower']),
                    'upper': float(variable['upper']) if math.isfinite(variable['upper']) else None,
                    'minimumWhenSelected': float(variable.get('minimumWhenSelected', variable['lower'])),
                }
            return finish('unproven', None, 'count_outside_bounds', result)
    row_error = _first_milp_row_violation(rows, canonical, lows, highs, row_identities)
    if row_error:
        if diagnostics is not None:
            diagnostics['rejectedRow'] = row_error
        reason = ('feature_constraint_violation' if row_error['index'] < len(features)
                  else 'constraint_violation')
        return finish('unproven', None, reason, result)
    return finish('optimal' if result.status == 0 else 'feasible', counts,
                  'accepted_optimal' if result.status == 0 else 'accepted_feasible', result, validated=True)


def _check_solution(candidate, plan, report, requirements, frequency_complete):
    targets = requirements["auditTargets"]
    feature_values = _feature_values(report)
    for index, workout in enumerate(report["workouts"]):
        for muscle, bounds in targets.get("perSessionEffectiveSets", {}).items():
            value = feature_values[("session", index, muscle)]
            minimum, maximum = volume_target_bounds(bounds)
            if not minimum - _TOLERANCE <= value <= maximum + _TOLERANCE:
                return f"Exact audit found {workout['name']} {muscle} at {value:g} effective sets outside the requested range."
        limit = targets.get("maximumSessionSeconds")
        if limit is not None and feature_values[("duration", index)] > limit + _TOLERANCE:
            seconds = feature_values[("duration", index)]
            return f"Exact audit estimates {workout['name']} at {seconds:g}s, above the {limit}s limit."
    for muscle, bounds in targets.get("weeklyEffectiveSets", {}).items():
        value = feature_values[("weekly", muscle)]
        minimum, maximum = volume_target_bounds(bounds)
        if value > maximum + _TOLERANCE:
            return f"Exact audit found weekly {muscle} at {value:g} effective sets, above {maximum:g}."
        if frequency_complete and value < minimum - _TOLERANCE:
            return f"Exact audit found weekly {muscle} at {value:g} effective sets, below {bounds['minimum']:g}."
    for bound in requirements.get('familySetBounds', []):
        value = feature_values[('family', bound['exerciseFamilyId'])]
        maximum = bound.get('maximumWeeklySets')
        minimum = bound.get('minimumWeeklySets')
        if maximum is not None and value > maximum + _TOLERANCE:
            return f"Exact audit found family {bound['exerciseFamilyId']} at {value:g} weekly sets, above {maximum}."
        if frequency_complete and minimum is not None and value < minimum - _TOLERANCE:
            return f"Exact audit found family {bound['exerciseFamilyId']} at {value:g} weekly sets, below {minimum}."
    exposure_rule = next((rule for rule in requirements.get('executionRules', [])
        if rule.get('kind') == 'exerciseExposure'), None)
    if exposure_rule:
        for definition_id, exposure in report.get('weeklyExerciseExposure', {}).items():
            for field, key in (('maximumSessionsPerWeek', 'weeklySessions'),
                               ('maximumWeeklySets', 'weeklyWorkingSets')):
                maximum = exposure_rule.get(field)
                if maximum is not None and exposure[key] > maximum + _TOLERANCE:
                    return f"Exact audit found exercise definition {definition_id} at {exposure[key]:g} {key}, above {maximum}."
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
                features.append((label, *volume_target_bounds(bounds), 0, coefficients))
    return _conflicting_targets(variables, features) if features else []


def allocate_prepared_sets(sessions, candidates, requirements, existing=None, equipment=None, restriction_policy=None,
                           select_movements=False, source_working_set_budget=None):
    """Allocate variable-session counts under a shared cap before prescriptions are locked."""
    from .joint_planning import _source_working_set_budget_identity
    try:
        normalized_source_budget = _source_working_set_budget_identity(
            sessions, source_working_set_budget)
    except (TypeError, ValueError):
        return {'feasible': False, 'status': 'invalid_options',
                'instruction': 'The shared source working-set budget is malformed.'}
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
                features.append((label, *volume_target_bounds(bounds), intercept, coefficients))
    exposure_rule = next((rule for rule in requirements.get('executionRules', [])
        if rule.get('kind') == 'exerciseExposure'), None)
    presence_caps = []
    exposure_ids = {}
    if exposure_rule:
        from .recipe_contracts import library_definitions_by_reference
        definition_records = library_definitions_by_reference(equipment or {})
        definition_id_by_reference = {reference: value['id'] for reference, value in definition_records.items()}
        definition_id_by_reference.update({value['id']: value['id'] for value in definition_records.values()})
        references = {slot['reference'] for variable in variables for slot in variable['members']}
        unmapped = sorted(reference for reference in references
            if definition_id_by_reference.get(reference) is None)
        if unmapped:
            return {'feasible': False, 'status': 'invalid_options',
                'errors': [{'code': 'exercise_exposure_identity_unknown',
                    'exerciseReferences': [str(value) for value in unmapped]}],
                'instruction': 'The selected exercise definitions cannot be mapped to exact library identities; resolve the library mapping before applying approved exercise caps.'}
        exposure_ids = {reference: definition_id_by_reference[reference] for reference in references}
        all_definition_ids = set(exposure_ids.values())
        if base_report:
            all_definition_ids.update(base_report.get('weeklyExerciseExposure', {}))
        for definition_id in sorted(all_definition_ids):
            existing_exposure = (base_report or {}).get('weeklyExerciseExposure', {}).get(definition_id, {})
            fixed_sets = existing_exposure.get('weeklyWorkingSets', 0)
            fixed_sessions = existing_exposure.get('weeklySessions', 0)
            if 'maximumWeeklySets' in exposure_rule:
                coefficients = [sum(slot['reference'] in exposure_ids
                    and exposure_ids[slot['reference']] == definition_id for slot in variable['members'])
                    * sessions[variable['members'][0]['day']]['timesCompletedInAWeek']
                    for variable in variables]
                features.append((('exercise_weekly_sets', definition_id), -math.inf,
                    exposure_rule['maximumWeeklySets'], fixed_sets, coefficients))
            if 'maximumSessionsPerWeek' in exposure_rule:
                groups = []
                for day_index, day in enumerate(sessions):
                    members = [index for index, variable in enumerate(variables)
                        if any(slot['day'] == day_index and exposure_ids.get(slot['reference']) == definition_id
                            for slot in variable['members'])]
                    if members:
                        groups.append((members, day['timesCompletedInAWeek']))
                presence_caps.append({'definitionId': definition_id,
                    'maximum': exposure_rule['maximumSessionsPerWeek'] - fixed_sessions,
                    'groups': groups})
    source_cap = normalized_source_budget['variableWeeklyWorkingSets']
    if source_cap is not None:
        source_set_coefficients = [sum(
            sessions[slot['day']]['timesCompletedInAWeek'] for slot in variable['members'])
            for variable in variables]
        features.append((('source_working_set_budget',), -math.inf,
            source_cap, 0,
            source_set_coefficients))
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
            stage_status, stage_counts = _milp_solve(variables, features, preserve_current=False,
                presence_caps=presence_caps)
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
            preserve_current=not select_movements, presence_caps=presence_caps)
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
    for cap in presence_caps:
        actual = 0
        for members, frequency in cap['groups']:
            if any(counts[index] for index in members):
                actual += frequency
        if actual > cap['maximum']:
            return {'feasible': False, 'status': 'unverified', 'conflictingTargets': [],
                'exerciseDefinitionId': cap['definitionId'], 'actualVariableSessions': actual,
                'maximumVariableSessions': cap['maximum']}
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
            'sourceWorkingSetBudget': copy.deepcopy(normalized_source_budget),
            **({'selectionPreview': preview} if preview else {}),
            'scope': ('Pre-prescription muscle-credit count-domain comparison only; proposed role labels are unqualified and do not constrain this result. '
                'Detailed prescriptions, timing, effort, setup and qualified-role coverage remain for later stages.')}


def _blocking_audit_errors(report, frequency_complete, requirements):
    supported = {"volume_below_target", "volume_above_target", "duration_exceeded",
                 "superset_set_count_mismatch", "empty_superset",
                 'family_weekly_sets_below_minimum', 'family_weekly_sets_above_maximum',
                 'exercise_sessions_above_maximum', 'exercise_weekly_sets_above_maximum'}
    if not frequency_complete and requirements.get("sessionsPerWeek") is not None:
        supported.add("weekly_session_count_mismatch")
    return [error for error in report.get("errors", []) if error.get("code") not in supported]


def _variable_effects(plan, report, variables, family_by_reference=None):
    effects = []
    for variable in variables:
        workout_index = int(variable["members"][0]["path"].split("/")[2])
        exercise_ids = plan["workouts"][workout_index]["exerciseIds"]
        credits_by_id = {item["exerciseId"]: item["credits"]
                         for item in report["workouts"][workout_index]["contributions"]}
        exercise_indexes = [int(member["path"].split("/")[4]) for member in variable["members"]]
        families = {family_by_reference.get(plan['exercises'][index].get('libraryDefinitionId'))
                    for index in exercise_indexes} - {None}
        definitions = {plan['exercises'][index].get('libraryDefinitionId') or plan['exercises'][index].get('id')
                       for index in exercise_indexes}
        effects.append({"workout": workout_index,
                        "muscles": {muscle for index in exercise_indexes
                                    for muscle, credit in credits_by_id.get(exercise_ids[index], {}).items()
                                    if credit.get("direct", 0) or credit.get("indirect", 0)},
                        'families': families, 'definitions': definitions})
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
        from .repair_execution import current_reviewed_joint_source
        reviewed_source = current_reviewed_joint_source(None,
            requirements_id=arguments['requirementsId'], equipment=equipment,
            messages=messages, training_history=training_history)
        reviewed_baseline_workouts = (copy.deepcopy(reviewed_source['submittedDraft']['workouts'])
            if reviewed_source is not None else None)
        if (reviewed_baseline_workouts is None and latest_audit.get('passed') is True
                and 'preservation' in (stored['requirements'].get('objectiveOrder') or [])):
            reviewed_baseline_workouts = copy.deepcopy(draft['workouts'])
        joint = solve_prescribed_week(draft['workouts'], stored['requirements'], equipment, restrictions,
            allow_educated_load_guesses=allow_educated_load_guesses, training_history=training_history,
            messages=messages, balance=True,
            reviewed_baseline_workouts=reviewed_baseline_workouts)
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
    family_evidence = family_set_audit_options(requirements, equipment).get('family_by_reference', {})
    effects = _variable_effects(base_plan, base_report, variables, family_evidence)
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
            or (feature[0] == 'family' and feature[1] in effect['families'])
            or (feature[0] == 'exercise_weekly_sets' and feature[1] in effect['definitions'])
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
            if feature[0] == 'family' and feature[1] not in effect['families']:
                coefficients.append(0.0)
                continue
            if feature[0] == 'exercise_sessions':
                coefficients.append(0.0)
                continue
            if feature[0] == 'exercise_weekly_sets' and feature[1] not in effect['definitions']:
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


def _current_reviewed_role_contracts(requirements_record, equipment, messages, training_history,
                                     references, review_feedback_by_definition=None):
    """Return role claims from the newest audit whose completed review is still current."""
    if not references or not isinstance(requirements_record, dict):
        return {}
    from .planning_decisions import resolved_decisions
    from .plan_review import _require_review_receipt

    requirements_id = requirements_record.get('requirementsId')
    approved_roles = {item.get('key') for item in
        requirements_record.get('requirements', {}).get('requiredCoverage', [])
        if isinstance(item, dict) and isinstance(item.get('key'), str)}
    expected = {
        'requirementsId': requirements_id,
        'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': getattr(training_history, 'fingerprint', None),
        'resolvedDecisions': resolved_decisions(messages),
    }
    audit_calls = {call.get('id') for message in messages or []
        for call in message.get('tool_calls', [])
        if call.get('function', {}).get('name') == 'audit_workout_plan'}
    for message in reversed(messages or []):
        if message.get('role') != 'tool' or message.get('tool_call_id') not in audit_calls:
            continue
        try:
            snapshot = json.loads(message.get('content') or '')
        except (TypeError, ValueError):
            continue
        if (not isinstance(snapshot, dict) or snapshot.get('passed') is not True
                or any(snapshot.get(key) != value for key, value in expected.items())):
            continue
        try:
            _require_review_receipt(snapshot, messages, equipment, training_history)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        submitted = snapshot.get('submittedDraft')
        qualification = snapshot.get('recipeQualification')
        input_hashes = qualification.get('inputHashes') if isinstance(qualification, dict) else None
        if (not isinstance(submitted, dict) or submitted.get('requirementsId') != requirements_id
                or not isinstance(qualification, dict) or not isinstance(input_hashes, dict)):
            continue
        occurrences_by_ref = {}
        for day in submitted.get('workouts', []):
            for item in day.get('exercises', []):
                ref = item.get('definition_id')
                if ref in references:
                    occurrence_roles = item.get('satisfiesCoverage', [])
                    if (not isinstance(occurrence_roles, list)
                            or len(occurrence_roles) != len(set(occurrence_roles))
                            or set(occurrence_roles) - approved_roles):
                        occurrences_by_ref[ref] = None
                    else:
                        occurrences_by_ref.setdefault(ref, copy.deepcopy(occurrence_roles))
                        if occurrences_by_ref[ref] != occurrence_roles:
                            occurrences_by_ref[ref] = None
        qualification_contracts = {}
        duplicate_contracts = set()
        for contract in qualification.get('contracts', []):
            if not isinstance(contract, dict):
                continue
            ref = contract.get('definition_id')
            if ref in qualification_contracts:
                duplicate_contracts.add(ref)
            qualification_contracts[ref] = contract.get('satisfiesCoverage')
        conflicted = {item.get('definition_id') for item in qualification.get('qualificationConflicts', [])
            if isinstance(item, dict)}
        result = {}
        for ref in references:
            if (ref in duplicate_contracts or ref in conflicted
                    or not isinstance(input_hashes.get(ref), str) or not input_hashes[ref]
                    or not isinstance(occurrences_by_ref.get(ref), list)
                    or qualification_contracts.get(ref) != occurrences_by_ref[ref]
                    or (review_feedback_by_definition or {}).get(ref)):
                continue
            result[ref] = copy.deepcopy(occurrences_by_ref[ref])
        if result:
            return result
    return {}


def qualify_workout_recipes(client, workouts, requirements_record, equipment, messages,
                            training_history=None, logger=None, *,
                            review_feedback_by_definition=None, cached_qualification=None):
    """Normalize every occurrence to its pinned definition-level coverage contract."""
    from .recipe_contracts import qualify_recipe_contracts
    from .exercise_library_tools import get_exercise_candidates
    from .planning_tools import library_fingerprint

    candidate_workouts = copy.deepcopy(workouts)
    references = sorted({item['definition_id'] for day in candidate_workouts for item in day['exercises']})
    candidates = {}
    for start in range(0, len(references), 100):
        selected = get_exercise_candidates({'definition_ids': references[start:start + 100]}, equipment, messages)
        candidates.update((item['id'], item) for item in selected['exercises'])
    prepared = {'definition_ids': references, 'candidates': candidates, 'libraryFingerprint': library_fingerprint(equipment),
                'sourceMessages': _recipe_qualification_source_messages(
                    messages, requirements_record, equipment, getattr(training_history, 'fingerprint', None))}
    if review_feedback_by_definition is not None:
        prepared['reviewFeedbackByDefinition'] = copy.deepcopy(review_feedback_by_definition)
    if cached_qualification is None:
        cached_qualification = _latest_recipe_qualification(messages)
    reviewed_contracts = _current_reviewed_role_contracts(requirements_record, equipment, messages,
        training_history, references, review_feedback_by_definition)
    qualified = qualify_recipe_contracts(client, prepared, requirements_record, equipment, messages,
        {'historyFingerprint': getattr(training_history, 'fingerprint', None)}, cached_qualification, logger,
        reviewed_contracts=reviewed_contracts)
    contracts = {item['definition_id']: item for item in qualified['contracts']}

    if set(contracts) != set(references):
        raise ValueError('Recipe qualification did not return a pinned contract for every selected definition.')
    for day in candidate_workouts:
        for item in day['exercises']:
            contract = contracts[item['definition_id']]
            item['satisfiesCoverage'] = copy.deepcopy(contract.get('satisfiesCoverage', []))
    return candidate_workouts, qualified


def qualify_coordinated_candidate(client, arguments, equipment, messages, training_history=None, logger=None,
                                  coordinated_repair_context=None):
    """A complete repair delegates recipe contracts and numerical placement to their owners."""
    from .review_assessment import latest_assessment
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
    candidate = copy.deepcopy(arguments)
    ownership = coordinated_repair_context or {}
    refs_by_workout = ownership.get('exerciseRefsByWorkout', {})
    workout_refs_by_position = ownership.get('workoutRefsByPosition', [])
    if ownership and (len(workout_refs_by_position) != len(candidate['workouts'])
            or any(len(refs_by_workout.get(workout_ref, [])) != len(day['exercises'])
                   for workout_ref, day in zip(workout_refs_by_position, candidate['workouts']))):
        raise ValueError('Coordinated repair references no longer match the compiled candidate.')
    candidate['workouts'], qualified = qualify_workout_recipes(client, candidate['workouts'], stored,
        equipment, messages, training_history, logger,
        review_feedback_by_definition=_qualification_review_feedback(assessment, previous))
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


def _recipe_qualification_source_messages(messages, requirements_record, equipment, history_fingerprint):
    """Use the prepared source snapshot that owns the current worker's recipe receipt."""
    requirements_id = requirements_record.get('requirementsId')
    library_fp = library_fingerprint(equipment)
    expected = {
        'requirementsId': requirements_id,
        'libraryFingerprint': library_fp,
        'historyFingerprint': history_fingerprint,
        'restrictionPolicy': copy.deepcopy(requirements_record.get('restrictionPolicy')),
    }
    _, worker = _latest_result(messages, 'draft_workout_sessions')
    preparation_id = worker.get('preparationId')
    if (worker.get('requirementsId') == requirements_id
            and worker.get('libraryFingerprint') == library_fp
            and worker.get('historyFingerprint') == history_fingerprint
            and isinstance(worker.get('recipeQualification'), dict)
            and isinstance(preparation_id, str)):
        calls = {call.get('id') for message in messages or []
            for call in message.get('tool_calls', [])
            if call.get('function', {}).get('name') == 'prepare_workout_sessions'}
        for message in reversed(messages or []):
            if message.get('role') != 'tool' or message.get('tool_call_id') not in calls:
                continue
            try:
                preparation = json.loads(message.get('content') or '')
            except (TypeError, ValueError):
                continue
            if not isinstance(preparation, dict):
                continue
            authority = preparation.get('sourceBudgetAuthority')
            source_messages = preparation.get('sourceMessages')
            if (preparation.get('preparationId') == preparation_id
                    and preparation.get('requirementsId') == requirements_id
                    and preparation.get('baseDraftId') == worker.get('baseDraftId')
                    and preparation.get('libraryFingerprint') == library_fp
                    and preparation.get('historyFingerprint') == history_fingerprint
                    and isinstance(authority, dict)
                    and all(authority.get(key) == value for key, value in expected.items())
                    and isinstance(source_messages, dict)):
                return copy.deepcopy(source_messages)

    # A direct audit with no owning preparation uses the approved requirement
    # receipt, never later gate, review, or navigation dialogue.
    sources = requirements_record.get('sourceMessages')
    if isinstance(sources, list):
        return {f'SOURCE_{index}': {key: copy.deepcopy(source[key]) for key in
                ('role', 'content', 'imageAttachments') if key in source}
                for index, source in enumerate(sources) if isinstance(source, dict)}
    if isinstance(sources, dict):
        return copy.deepcopy(sources)
    return {}


def _joint_planning_receipt(owner):
    """Return the current joint proof regardless of which stage stored it."""
    return owner.get('coordinatedJointPlanning') or owner.get('automaticAllocation') or {}


def reusable_joint_receipt(owner, requirements_id, sessions, requirements, equipment, messages, training_history=None,
                           restriction_policy=None, allow_educated_load_guesses=True,
                           preserve_source_selection=False, redistribution_constraints=None,
                           source_working_set_budget=None, reviewed_baseline_workouts=None):
    """Return prior solver evidence only when the same approved objective still owns this prescription."""
    from .joint_planning import (SELECTION_POLICY_VERSION, _attempted_objective_order,
        joint_objective_input_fingerprint, _reviewed_dose_reference_identity,
        _source_working_set_budget_identity)
    receipt = _joint_planning_receipt(owner)
    from .planning_tools import library_fingerprint
    expected_policy = 'approved' if requirements.get('objectiveOrder') is not None else 'preserve_candidate_only'
    try:
        expected_source_budget = _source_working_set_budget_identity(sessions, source_working_set_budget)
    except (TypeError, ValueError):
        return None
    # Generic objective identity cannot establish a solve performed under additional repair constraints.
    if (receipt.get('feasible') is not True or receipt.get('status') not in ('feasible', 'optimal')
            or (receipt.get('redistributionOptimization') and not redistribution_constraints)
            or receipt.get('selectionPolicyVersion') != SELECTION_POLICY_VERSION
            or receipt.get('preserveSourceSelection') is not bool(preserve_source_selection)
            or receipt.get('objectivePolicy') != expected_policy
            or receipt.get('approvedObjectiveOrder') != requirements.get('objectiveOrder')
            or owner.get('libraryFingerprint') != library_fingerprint(equipment)
            or owner.get('historyFingerprint') != getattr(training_history, 'fingerprint', None)):
        return None
    objective_progress = receipt.get('objectiveProgress')
    if not isinstance(objective_progress, list):
        return None
    fallback_order = ['preservation'] if (
        requirements.get('objectiveOrder') is None
        and receipt.get('reviewedDoseReference') is not None) else []
    if receipt.get('objectiveOrderUsed') != _attempted_objective_order(
            requirements.get('objectiveOrder'), objective_progress, fallback_order):
        return None
    if receipt.get('sourceWorkingSetBudget') != expected_source_budget:
        return None
    try:
        recorded_dose_reference = (_reviewed_dose_reference_identity(receipt['reviewedDoseReference'])
            if 'reviewedDoseReference' in receipt else None)
        supplied_dose_reference = _reviewed_dose_reference_identity(reviewed_baseline_workouts)
    except (TypeError, ValueError):
        return None
    if ('reviewedDoseReferenceAvailable' in receipt
            and receipt['reviewedDoseReferenceAvailable'] is not (recorded_dose_reference is not None)):
        return None
    if (reviewed_baseline_workouts is not None and recorded_dose_reference is not None
            and supplied_dose_reference != recorded_dose_reference):
        return None
    if reviewed_baseline_workouts is None:
        reviewed_baseline_workouts = recorded_dose_reference
    if (recorded_dose_reference is not None
            and recorded_dose_reference['frequency'] != sum(day['timesCompletedInAWeek'] for day in sessions)):
        return None
    # A source refresh may mint a new requirements ID without changing the solver domain.
    # Reuse remains safe only when this full fingerprint matches; approval and review gates
    # are enforced by the callers independently of this numerical proof.
    expected = joint_objective_input_fingerprint(sessions, requirements, equipment, training_history, messages,
        restriction_policy=restriction_policy,
        allow_educated_load_guesses=allow_educated_load_guesses,
        preserve_source_selection=preserve_source_selection,
        redistribution_constraints=redistribution_constraints,
        source_working_set_budget=expected_source_budget,
        reviewed_baseline_workouts=reviewed_baseline_workouts)
    if receipt.get('objectiveInputFingerprint') != expected:
        return None
    return copy.deepcopy(receipt)


def reusable_audited_joint_receipt(owner, requirements_id, sessions, requirements, equipment, messages,
                                   training_history=None, restriction_policy=None,
                                   allow_educated_load_guesses=True, redistribution_constraints=None,
                                   source_working_set_budget=None):
    """Retain an exact solved artifact's evidence under its original selection domain."""
    from .joint_planning import prescription_fingerprint

    receipt = _joint_planning_receipt(owner)
    if receipt.get('solvedPrescriptionHash') != prescription_fingerprint(sessions):
        return None
    return reusable_joint_receipt(owner, requirements_id, sessions, requirements, equipment, messages,
        training_history, restriction_policy, allow_educated_load_guesses,
        preserve_source_selection=receipt.get('preserveSourceSelection') is True,
        redistribution_constraints=redistribution_constraints,
        source_working_set_budget=(source_working_set_budget if source_working_set_budget is not None
            else receipt.get('sourceWorkingSetBudget')))


def _joint_candidate_comparison_context(baseline_workouts, candidate_workouts, requirements,
                                       equipment, messages, training_history, restrictions,
                                       source_working_set_budget, *, qualification=None,
                                       review_feedback_by_definition=None):
    """Build shared comparison evidence from current code-owned qualification receipts."""
    from .joint_planning import _source_working_set_budget_identity
    from .programming_demands import demand_distribution_inputs, demand_union_exposure_input
    from .recipe_contracts import (_recipe_context, _retained_contracts,
        canonical_qualified_roles, reviewed_exercise_family_evidence)
    from .planning_tools import _latest_result

    try:
        comparison_source_budget = _source_working_set_budget_identity(
            baseline_workouts or candidate_workouts or [], source_working_set_budget)
    except (TypeError, ValueError):
        return None

    from .exercise_library_tools import get_exercise_candidates
    definitions = sorted(equipment.get('exerciseDefinitions', []), key=lambda item: item['id'])
    reference_to_raw_definition = {f'LIBRARY_{index}': definition
        for index, definition in enumerate(definitions)}
    id_to_reference = {definition['id']: reference
        for reference, definition in reference_to_raw_definition.items()}

    def normalize_reference(value):
        if not isinstance(value, str):
            return None
        return value if value in reference_to_raw_definition else id_to_reference.get(value)

    references = set()
    aliases_by_reference = {}
    for workouts in (baseline_workouts, candidate_workouts):
        for workout in workouts or []:
            for item in workout.get('exercises', []):
                original_reference = item.get('definition_id')
                reference = normalize_reference(original_reference)
                if reference is None:
                    return None
                references.add(reference)
                aliases_by_reference.setdefault(reference, set()).add(original_reference)
    if not references:
        return None
    reference_to_definition = {}
    try:
        for start in range(0, len(references), 100):
            batch = sorted(references)[start:start + 100]
            selected = get_exercise_candidates({'definition_ids': batch}, equipment, messages)['exercises']
            reference_to_definition.update((candidate['id'], candidate) for candidate in selected)
    except (ValueError, KeyError, TypeError):
        return None

    _, current_requirements = _latest_result(messages, 'set_workout_requirements')
    prepared = {
        'candidates': {reference: reference_to_definition[reference] for reference in references},
        'sourceMessages': _recipe_qualification_source_messages(
            messages, current_requirements, equipment, getattr(training_history, 'fingerprint', None)),
    }
    if review_feedback_by_definition is not None:
        prepared['reviewFeedbackByDefinition'] = copy.deepcopy(review_feedback_by_definition)
    input_hashes = {}
    for reference in sorted(references):
        context = _recipe_context(prepared, requirements, reference)
        input_hashes[reference] = hashlib.sha256(
            json.dumps(context, sort_keys=True).encode()).hexdigest()
    required_roles = {rule['key'] for rule in requirements.get('requiredCoverage', [])}
    if required_roles:
        if qualification is None:
            _, workers = _latest_result(messages, 'draft_workout_sessions')
            qualification = workers.get('recipeQualification')
        contracts, conflicts = _retained_contracts(
            messages, qualification, input_hashes, required_roles, reference_to_raw_definition)
        reviewed_contracts = {}
        if current_requirements.get('requirements') == requirements:
            reviewed_contracts = _current_reviewed_role_contracts(current_requirements, equipment,
                messages, training_history, references, review_feedback_by_definition)
        conflicted_references = {item['definition_id'] for item in conflicts}
        qualified_roles = {reference: contract['satisfiesCoverage']
            for reference, contract in contracts.items() if reference not in conflicted_references}
        # A passed current review is stronger than an older contradictory
        # same-input qualification receipt; preserve the conflict in its source
        # receipt for diagnostics, but compare the reviewed role assignment.
        qualified_roles.update({reference: canonical_qualified_roles(
            reference_to_raw_definition[reference], assigned_roles, required_roles)
            for reference, assigned_roles in reviewed_contracts.items()
            if reference in reference_to_raw_definition})
    else:
        # With no approved roles, qualification is code-owned and empty by contract.
        qualified_roles = {reference: [] for reference in references}
    role_evidence = {}
    for reference, roles in qualified_roles.items():
        for alias in aliases_by_reference.get(reference, {reference}):
            role_evidence[alias] = copy.deepcopy(roles)

    demand_inputs = demand_distribution_inputs([reference_to_raw_definition[reference]
        for reference in sorted(references)])
    normalized_groups = {}
    for key, group in demand_inputs.get('groups', {}).items():
        group_copy = copy.deepcopy(group)
        present_refs = []
        evidence_by_ref = {}
        for identifier in group.get('presentDefinitionIds', []):
            reference = id_to_reference.get(identifier)
            if reference is None:
                return None
            aliases = aliases_by_reference.get(reference, {reference})
            present_refs.extend(aliases)
            if identifier in group.get('evidenceByDefinition', {}):
                for alias in aliases:
                    evidence_by_ref[alias] = group['evidenceByDefinition'][identifier]
        group_copy['presentDefinitionRefs'] = sorted(set(present_refs))
        group_copy['evidenceByDefinition'] = evidence_by_ref
        normalized_groups[key] = group_copy
    demand_evidence = {**demand_inputs, 'groups': normalized_groups}
    demand_union = demand_union_exposure_input(demand_inputs)
    if demand_union:
        union_refs = []
        union_evidence = {}
        for identifier in demand_union.get('presentDefinitionIds', []):
            reference = id_to_reference.get(identifier)
            if reference is None:
                return None
            aliases = aliases_by_reference.get(reference, {reference})
            union_refs.extend(aliases)
            facts = demand_union.get('evidenceByDefinition', {}).get(identifier)
            if facts is not None:
                for alias in aliases:
                    union_evidence[alias] = facts
        demand_union = {**demand_union, 'presentDefinitionRefs': sorted(set(union_refs)),
            'evidenceByDefinition': union_evidence}

    family_evidence = reviewed_exercise_family_evidence(equipment, sorted(references))
    for reference, aliases in aliases_by_reference.items():
        if reference in family_evidence['familyByReference']:
            for alias in aliases:
                family_evidence['familyByReference'][alias] = family_evidence['familyByReference'][reference]
                family_evidence['sourcesByReference'][alias] = family_evidence['sourcesByReference'][reference]

    return {
        'restrictionPolicy': copy.deepcopy(restrictions),
        'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': getattr(training_history, 'fingerprint', None),
        'sourceWorkingSetBudget': copy.deepcopy(comparison_source_budget),
        'qualifiedRoleEvidence': role_evidence,
        'exerciseFamilyEvidence': family_evidence,
        'demandEvidence': demand_evidence,
        'demandUnion': demand_union,
    }


def auto_allocate_workout(result, equipment, messages, allow_educated_load_guesses=True, training_history=None, logger=None, progress=None):
    """Jointly solve complete prescriptions; after preview return a proposal only."""
    draft = result.get('submittedDraft')
    if not draft:
        return result
    repair_contract = result.get('repairContract')
    redistribution_constraints = []
    if isinstance(repair_contract, dict):
        from .repair_contract import repair_contract_errors, redistribution_solver_constraints
        contract_errors = repair_contract_errors(repair_contract, draft)
        if contract_errors:
            return {**result, 'passed': False,
                'errors': [*(result.get('errors') or []), *contract_errors],
                'instruction': ('The current candidate does not satisfy its carried repair outcome. Preserve the exact '
                    'redistribution intent and correct the structure before numerical allocation.')}
        redistribution_constraints = redistribution_solver_constraints(repair_contract)
    _, stored = _latest_result(messages, 'set_workout_requirements')
    from .joint_planning import (JOINT_REPAIRABLE_AUDIT_ERRORS, solve_prescribed_week,
        prescription_patch, prescription_fingerprint, joint_problem_fingerprint, SELECTION_POLICY_VERSION)
    needs_numbers = any(e.get('code') in JOINT_REPAIRABLE_AUDIT_ERRORS
        for e in result.get('errors', []))
    objective_order = set(stored.get('requirements', {}).get('objectiveOrder') or [])
    balance_rules = [rule for rule in stored.get('requirements', {}).get('executionRules', []) if rule['kind'] == 'coverageBalance']
    report = result.get('audit', {})
    needs_balance = 'source_balance' in objective_order and any(any(
        (values.get(rule['first'], 0) < values.get(rule['second'], 0)
            if rule.get('relationship') == 'first_not_less_than_second'
            else values.get(rule['first'], 0) != values.get(rule['second'], 0)) for values in (
        [report.get('weeklyCoverageSets', {})] if rule['scope'] == 'weekly' else
        [day.get('coverageSets', {}) for day in report.get('workouts', [])])) for rule in balance_rules)
    _, previous = _latest_result(messages, 'audit_workout_plan')
    _, workers = _latest_result(messages, 'draft_workout_sessions')
    automatic = not any(message.get('canonicalDraftPreview') for message in messages)
    previous_joint = _joint_planning_receipt(previous)
    proofs = [(previous_joint, previous)]
    requirements = stored.get('requirements', {})
    restrictions = effective_restrictions(stored, equipment)
    from .repair_execution import current_reviewed_joint_source
    reviewed_source = current_reviewed_joint_source(None,
        requirements_id=result['requirementsId'], equipment=equipment,
        messages=messages, training_history=training_history)
    reviewed_baseline_workouts = (copy.deepcopy(reviewed_source['submittedDraft']['workouts'])
        if reviewed_source is not None else None)
    if (reviewed_baseline_workouts is None and result.get('passed') is True
            and 'preservation' in objective_order):
        # An explicitly approved preservation objective may retain the current
        # audited candidate even before it has a semantic review receipt.
        reviewed_baseline_workouts = copy.deepcopy(draft['workouts'])
    worker_joint = workers.get('jointPlanning') or workers.get('coordinatedJointPlanning') or {}
    from .session_drafting import source_working_set_budget_for_worker
    source_working_set_budget = source_working_set_budget_for_worker(
        messages, workers, equipment, getattr(training_history, 'fingerprint', None))
    if (not isinstance(worker_joint.get('sourceWorkingSetBudget'), dict)
            or source_working_set_budget is not None):
        proofs.append((worker_joint, workers))
    cached = previous_joint
    effective_source_working_set_budget = source_working_set_budget or cached.get('sourceWorkingSetBudget')

    def solved_receipt_matches(proof, owner):
        if proof.get('selectionPolicyVersion') != SELECTION_POLICY_VERSION:
            return None
        receipt_owner = {**owner, 'coordinatedJointPlanning': proof}
        receipt = reusable_audited_joint_receipt(receipt_owner, result['requirementsId'], draft['workouts'],
            requirements, equipment, messages, training_history, restrictions,
                        allow_educated_load_guesses,
                        redistribution_constraints=redistribution_constraints,
                        source_working_set_budget=source_working_set_budget)
        if not receipt or proof.get('solvedPrescriptionHash') != prescription_fingerprint(draft['workouts']):
            return None
        return receipt

    reused_joint_receipt = None
    for proof, owner in proofs:
        reused_joint_receipt = solved_receipt_matches(proof, owner)
        if reused_joint_receipt:
            break
    already_solved = reused_joint_receipt is not None
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
        if reused_joint_receipt:
            return {**result, 'coordinatedJointPlanning': {**reused_joint_receipt,
                'reusedForValidatedCandidate': True,
                'instruction': ('The unchanged candidate retains its validated prescription objectives; '
                    'no new optimization claim was made.')}}
        return result
    sessions = stored.get('requirements', {}).get('sessionsPerWeek')
    if sessions and sum(day['timesCompletedInAWeek'] for day in draft['workouts']) != sessions:
        return result
    application = 'automatic' if automatic else 'proposal'
    current_problem_fingerprint = joint_problem_fingerprint(draft['workouts'], requirements, equipment,
        training_history, messages, restriction_policy=restrictions,
        allow_educated_load_guesses=allow_educated_load_guesses,
        preserve_source_selection=False,
        redistribution_constraints=redistribution_constraints,
        source_working_set_budget=effective_source_working_set_budget,
        reviewed_baseline_workouts=reviewed_baseline_workouts)
    if (cached.get('inputDraftId') == result['draftId'] and cached.get('objective') == 'joint_prescriptions'
            and cached.get('application') == application and cached.get('selectionPolicyVersion') == SELECTION_POLICY_VERSION
            and cached.get('preserveSourceSelection') is False
            and cached.get('problemFingerprint') == current_problem_fingerprint):
        return {**result, 'automaticAllocation': copy.deepcopy(cached), **(
            {'jointPlanningStopped': True, 'instruction': cached['instruction']} if not cached['feasible'] else {})}

    # A prior unapplied comparison/search is diagnostic evidence, never solver proof.
    # Reuse it only for the identical draft and problem; changed inputs can retry.
    diagnostic_owners = (result, previous)
    for owner in diagnostic_owners:
        prior_diagnostics = [owner.get('jointCandidateSearchDiagnostic'),
            (owner.get('jointCandidateProposal') or {}).get('jointPlanning')]
        for diagnostic in prior_diagnostics:
            if (isinstance(diagnostic, dict)
                and diagnostic.get('application') == 'not_applied'
                and diagnostic.get('objective') == 'joint_prescriptions'
                and diagnostic.get('inputDraftId') == result.get('draftId')
                and diagnostic.get('selectionPolicyVersion') == SELECTION_POLICY_VERSION
                and diagnostic.get('preserveSourceSelection') is False
                and diagnostic.get('problemFingerprint') == current_problem_fingerprint
                and diagnostic.get('sourceWorkingSetBudget') == effective_source_working_set_budget):
                # Carry forward only the prior decision/evidence; the current audit
                # remains authoritative for this exact same input artifact.
                keys = ('jointCandidateSearchDiagnostic', 'jointCandidateProposal',
                    'jointCandidateComparison', 'jointPromotionGate', 'jointPlanningSearchUnproven',
                    'jointPlanningStopped', 'passed', 'errors', 'instruction')
                return {**result, **{key: owner[key] for key in keys if key in owner}}
    if progress:
        progress('Solving prescriptions, placement, volume and duration together')
    joint = solve_prescribed_week(draft['workouts'], stored['requirements'], equipment,
        restrictions, allow_educated_load_guesses=allow_educated_load_guesses,
        training_history=training_history, messages=messages,
        preserve_source_selection=False,
        redistribution_constraints=redistribution_constraints,
        source_working_set_budget=effective_source_working_set_budget,
        reviewed_baseline_workouts=reviewed_baseline_workouts)
    patch = prescription_patch(draft['workouts'], joint['sessions'], joint.get('occurrenceLineage')) if joint['feasible'] else []
    receipt = {'inputDraftId': result['draftId'], 'objective': 'joint_prescriptions', 'application': application,
               'problemFingerprint': current_problem_fingerprint,
               'sourceWorkingSetBudget': copy.deepcopy(effective_source_working_set_budget),
               **({'redistributionConstraints': copy.deepcopy(redistribution_constraints)}
                   if redistribution_constraints else {}),
               **{key: value for key, value in joint.items() if key not in ('sessions', 'audit')}, 'patch': patch}
    active_receipt = receipt

    def unapplied_candidate_receipt(value):
        diagnostic = copy.deepcopy(value)
        diagnostic['application'] = 'not_applied'
        diagnostic['candidateApplied'] = False
        if 'solvedPrescriptionHash' in diagnostic:
            diagnostic['candidateSolvedPrescriptionHash'] = diagnostic.pop('solvedPrescriptionHash')
        return diagnostic

    if automatic and joint['feasible'] and patch:
        carried_contract = None
        if repair_contract:
            from .repair_contract import RepairContractError, carry_repair_contract
            try:
                carried_contract = carry_repair_contract(repair_contract, {},
                    {'workouts': draft['workouts']}, {'workouts': joint['sessions']},
                    requirements_id=result['requirementsId'])
            except RepairContractError as error:
                return {**result, 'passed': False,
                    'errors': [*(result.get('errors') or []), {'code': error.code,
                        'path': error.path, 'owner': 'structural_repair', 'message': str(error)}],
                    'automaticAllocation': receipt,
                    'instruction': ('The automatic candidate did not preserve the carried repair outcome. Keep it '
                        'unapproved and restore the required redistribution before continuing.')}
        baseline_result = result
        baseline_candidate = {'workouts': copy.deepcopy(draft['workouts']),
            'audit': report, 'searchStatus': 'not_searched'}
        baseline = messages + [
            {'role': 'assistant', 'tool_calls': [{'id': 'auto_allocation_base', 'function': {'name': 'audit_workout_plan'}}]},
            {'role': 'tool', 'tool_call_id': 'auto_allocation_base', 'content': json.dumps(result)}]
        candidate_result = audit_workout_plan({'requirementsId': result['requirementsId'], 'baseDraftId': result['currentDraftId'],
            'patch': patch}, equipment, baseline, allow_educated_load_guesses, training_history)
        if carried_contract:
            from .repair_contract import repair_contract_errors
            candidate_contract_errors = repair_contract_errors(carried_contract,
                candidate_result.get('submittedDraft') or {})
            candidate_result['repairContract'] = copy.deepcopy(carried_contract)
            if candidate_contract_errors:
                candidate_result.update(passed=False,
                    errors=[*(candidate_result.get('errors') or []), *candidate_contract_errors],
                    instruction='The audited automatic candidate violated its carried repair outcome; it cannot be promoted.')
        context = _joint_candidate_comparison_context(
            baseline_candidate['workouts'], candidate_result.get('submittedDraft', {}).get('workouts', []),
            requirements, equipment, messages, training_history, restrictions, effective_source_working_set_budget)
        from .joint_planning import compare_audited_joint_candidates
        comparison = compare_audited_joint_candidates(
            baseline_candidate,
            {'workouts': candidate_result.get('submittedDraft', {}).get('workouts', []),
             'audit': candidate_result.get('audit'), 'searchStatus': joint.get('status', 'unknown')},
            requirements=requirements, context=context or {})
        receipt['candidateComparison'] = comparison
        if comparison.get('decision') == 'promote_candidate':
            result = candidate_result
        elif (comparison.get('decision') == 'retain_baseline'
                or baseline_result.get('passed') and comparison.get('decision') == 'incomparable'):
            result = {**baseline_result, 'jointCandidateComparison': comparison,
                'jointCandidateProposal': {'submittedDraft': candidate_result.get('submittedDraft'),
                    'audit': candidate_result.get('audit'),
                    'jointPlanning': unapplied_candidate_receipt(receipt)}}
            active_receipt = None
        else:
            # Incomparable candidates cannot establish a quality improvement. Keep a
            # passing source plan, or preserve the solved candidate as an unapproved
            # proposal when the source plan itself failed the hard audit.
            result = baseline_result if baseline_result.get('passed') else candidate_result
            result = {**result, 'jointPromotionGate': comparison,
                'jointCandidateProposal': {'submittedDraft': candidate_result.get('submittedDraft'),
                    'audit': candidate_result.get('audit'),
                    'jointPlanning': unapplied_candidate_receipt(receipt)},
                'jointCandidateComparison': comparison,
                'passed': False, 'jointPlanningStopped': True,
                'errors': [*(result.get('errors') or []), {
                    'code': 'joint_candidate_comparison_unresolved',
                    'message': 'The automatic candidate lacks a complete shared comparison proof.',
                    'owner': 'generator'}],
                'instruction': ('The automatic candidate could not be compared under one current, verified qualification, '
                    'demand and source-budget context. Preserve the passing source plan and candidate evidence; pause '
                    'for explicit human adjudication. Do not claim that either plan is better or discard an unresolved review obligation.')}
            active_receipt = None
    retained_valid_baseline = False
    if not joint['feasible']:
        if (automatic and result.get('passed') is True
                and joint.get('status') in ('unproven', 'time_limit', 'timed_out', 'feasible_unproven')):
            source_candidate = {'workouts': copy.deepcopy(draft['workouts']), 'audit': report,
                'searchStatus': 'not_searched'}
            context = _joint_candidate_comparison_context(
                source_candidate['workouts'], source_candidate['workouts'], requirements,
                equipment, messages, training_history, restrictions, effective_source_working_set_budget)
            from .joint_planning import compare_audited_joint_candidates
            source_comparison = compare_audited_joint_candidates(source_candidate, source_candidate,
                requirements=requirements, context=context or {})
            if context is not None and not source_comparison.get('baselineAuditErrors'):
                retained_valid_baseline = True
                receipt['candidateComparison'] = source_comparison
                receipt['searchLimitation'] = {'status': joint.get('status'),
                    'objectiveOptimality': 'unproven',
                    'instruction': 'The source plan passed the current code audit and remains eligible. '
                        'The bounded improvement search did not produce a candidate; no optimality claim was made.'}
                receipt['instruction'] = ('The source plan passed the current code audit and remains eligible. '
                    'The bounded improvement search did not produce a candidate; ordinary final review is still required.')
                result = {**result,
                    'jointCandidateSearchDiagnostic': unapplied_candidate_receipt(receipt),
                    'jointPlanningSearchUnproven': joint.get('status'),
                    'instruction': ('The source plan passed the current code audit and is retained because the bounded '
                        'improvement search did not produce a candidate. Continue to ordinary final review; do not '
                        'treat the plan as optimizer-proven or skip review.')}
                active_receipt = None
        if not retained_valid_baseline:
            result = {**result, 'jointPlanningStopped': True, 'instruction': joint['instruction']}
    if logger:
        logger.log_response('automatic_joint_planning', json.dumps(receipt), truncate_at=0)
    return {**result, **({'automaticAllocation': active_receipt} if active_receipt is not None else {})}
