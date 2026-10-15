"""One structured draft for auditing, displaying and exporting a workout plan."""

import copy
import hashlib
import json
import re

from jsonschema import validate, ValidationError

from .constants import EXACT_GENERATION_CONFIRMATION
from .generation_audit import MUSCLES, ASSUMPTIONS, audit_workout_package, plan_audit_package, add_audit_issue
from .plan_contract import LIBRARY_DEFINITION_OWNED_FIELDS, validate_plan_index_contract, hydrate_plan_index_from_exercise_library, ContractValidationError


class PlanningInputError(ValueError):
    def __init__(self, code, message, path, repair):
        super().__init__(message)
        self.code, self.path, self.repair = code, path, repair


def planning_tool_failure(tool_name, error, arguments=None):
    repair = "Correct the indicated tool argument, preserve agreed requirements and library-owned fields, then resubmit the complete draft to audit_workout_plan."
    if isinstance(error, PlanningInputError):
        errors = [{"code": error.code, "path": error.path, "message": str(error), "repair": error.repair}]
    elif isinstance(error, ValidationError):
        path = "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in error.absolute_path)
        errors = [{"code": "invalid_arguments", "path": path, "message": error.message,
                   "validator": error.validator, "expected": error.validator_value,
                   "actual": error.instance if not isinstance(error.instance, (dict, list)) else None, "repair": repair}]
    elif isinstance(error, ContractValidationError) and error.issues:
        positions = [(d, e) for d, day in enumerate((arguments or {}).get("workouts", [])) for e, _ in enumerate(day.get("exercises", []))]
        errors = []
        for issue in error.issues:
            match = re.search(r"\bEXERCISE_(\d+)\b", issue.message)
            path = "/workouts"
            if match and int(match.group(1)) < len(positions):
                day, exercise = positions[int(match.group(1))]
                path = f"/workouts/{day}/exercises/{exercise}"
            errors.append({"code": issue.code, "path": path, "message": issue.message, "repair": repair,
                           "exerciseId": match.group(0) if match else None})
    else:
        editable = isinstance(error, ValueError)
        errors = [{"code": "invalid_plan" if editable else "tool_execution_failed", "path": "/",
                   "message": str(error), "repair": repair if editable else "Report this execution failure; do not change the draft or relax goals to hide it."}]
    return {"passed": False, "tool": tool_name, "errors": errors,
            "instruction": "Follow errors[].repair. Re-audit actual draft changes. If constraints conflict, explain the conflict and ask the user; do not silently change requirements or repeatedly submit an unchanged failing draft."}


_BOUNDS = {"type": "object", "properties": {
    muscle: {"type": "object", "properties": {
        "minimum": {"type": "number", "minimum": 0, "maximum": 100},
        "maximum": {"type": "number", "minimum": 0, "maximum": 100},
    }, "required": ["minimum", "maximum"], "additionalProperties": False} for muscle in MUSCLES
}, "additionalProperties": False}
_TARGETS = {"type": "object", "properties": {
    "weeklyEffectiveSets": _BOUNDS, "perSessionEffectiveSets": _BOUNDS,
    "maximumSessionSeconds": {"type": ["integer", "null"], "minimum": 1},
}, "required": ["weeklyEffectiveSets", "perSessionEffectiveSets", "maximumSessionSeconds"], "additionalProperties": False}
_REQUIREMENTS = {"type": "object", "properties": {
    "auditTargets": _TARGETS,
    "sessionsPerWeek": {"type": ["integer", "null"], "minimum": 1, "maximum": 21},
    "notes": {"type": "string", "maxLength": 2000},
}, "required": ["auditTargets", "sessionsPerWeek", "notes"], "additionalProperties": False}

SET_WORKOUT_REQUIREMENTS_TOOL = {"type": "function", "function": {
    "name": "set_workout_requirements",
    "description": "Call once to record the user's agreed targets, then reuse the returned requirementsId. Call again only for a user-requested requirements change, not questions, explanations or automatic repairs. Empty maps/null explicitly mean unspecified; never omit a stated goal. The app displays requirements for review.",
    "parameters": _REQUIREMENTS,
}}
_EXERCISE = {"type": "object", "properties": {
    "definition_id": {"type": "string", "pattern": "^LIBRARY_[0-9]+$"},
    "numWorkSets": {"type": "integer", "minimum": 1, "maximum": 20},
    "minReps": {"type": ["integer", "null"], "minimum": 1, "maximum": 100},
    "maxReps": {"type": ["integer", "null"], "minimum": 1, "maximum": 100},
    "durationSeconds": {"type": ["integer", "null"], "minimum": 1},
    "restBetweenSetsSeconds": {"type": "integer", "minimum": 0, "maximum": 1800},
    "restAfterExerciseSeconds": {"type": "integer", "minimum": 0, "maximum": 1800},
    "superset": {"type": ["string", "null"], "minLength": 1},
    "restAfterSupersetExerciseSeconds": {"type": "integer", "minimum": 0, "maximum": 1800},
    "intraSetRestInSeconds": {"type": ["integer", "null"], "minimum": 1, "maximum": 300},
    "generateWarmUpSets": {"type": "boolean"},
    "placementNotes": {"type": "string", "maxLength": 1000},
    "targetSetPrescriptions": {"type": "array", "maxItems": 20, "items": {
        "type": "object", "properties": {
            "workSetIndex": {"type": "integer", "minimum": 0}, "reps": {"type": "integer", "minimum": 1},
            "weight": {"type": "number", "minimum": 0}, "additionalWeight": {"type": "number", "minimum": 0},
        }, "required": ["workSetIndex", "reps"], "additionalProperties": False,
    }},
}, "required": ["definition_id", "numWorkSets", "minReps", "maxReps", "durationSeconds",
                 "restBetweenSetsSeconds", "restAfterExerciseSeconds", "superset",
                 "restAfterSupersetExerciseSeconds", "intraSetRestInSeconds", "generateWarmUpSets", "placementNotes"],
    "additionalProperties": False}
AUDIT_WORKOUT_PLAN_TOOL = {"type": "function", "function": {
    "name": "audit_workout_plan",
    "description": "Call only when creating or changing the structured draft; questions and explanations do not require another audit. Python audits volume and estimated duration, then displays a passing preview. On failure, follow errors[].repair, change the draft and resubmit without changing requirements. If constraints conflict, explain and ask the user; never silently relax goals or loop on an unchanged failing draft. Export uses this exact draft after CONFIRM GENERATE. Superset members must be contiguous with equal sets; only the final member may have outer rest. Exact loads use app totals (dumbbell pair = combined total).",
    "parameters": {"type": "object", "properties": {
        "requirementsId": {"type": "string"}, "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "workouts": {"type": "array", "minItems": 1, "maxItems": 30, "items": {
            "type": "object", "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 200},
                "description": {"type": "string", "maxLength": 1000},
                "timesCompletedInAWeek": {"type": "integer", "minimum": 1, "maximum": 7},
                "exercises": {"type": "array", "minItems": 1, "maxItems": 100, "items": _EXERCISE},
            }, "required": ["name", "description", "timesCompletedInAWeek", "exercises"], "additionalProperties": False,
        }},
    }, "required": ["requirementsId", "name", "workouts"], "additionalProperties": False},
}}


def _latest_result(messages, tool_name):
    calls = {call.get("id") for message in messages for call in message.get("tool_calls", [])
             if call.get("function", {}).get("name") == tool_name}
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "tool" and message.get("tool_call_id") in calls:
            if (message.get("content") or "").startswith("Tool call started"):
                continue
            try:
                result = json.loads(message.get("content") or "{}")
                if tool_name == "set_workout_requirements" and not (isinstance(result, dict) and result.get("requirements")):
                    continue
                return index, result if isinstance(result, dict) else {}
            except (ValueError, TypeError):
                if tool_name == "set_workout_requirements":
                    continue
                return index, {}
    return -1, {}


def _revision_index(messages):
    return next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"
                 and (messages[i].get("content") or "").strip() != EXACT_GENERATION_CONFIRMATION), -1)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def library_fingerprint(equipment):
    return _fingerprint({key: equipment.get(key, []) for key in ("exerciseDefinitions", "equipments", "accessoryEquipments")})


def render_requirements(requirements):
    lines = ["Program requirements:"]
    lines.append(f"- Sessions per week: {requirements['sessionsPerWeek'] or 'unspecified'}")
    for field, label in (("weeklyEffectiveSets", "Weekly effective sets"), ("perSessionEffectiveSets", "Effective sets per session")):
        values = requirements["auditTargets"][field]
        text = "; ".join(f"{muscle}: {b['minimum']:g}–{b['maximum']:g}" for muscle, b in values.items())
        lines.append(f"- {label}: {text or 'unspecified'}")
    limit = requirements["auditTargets"]["maximumSessionSeconds"]
    lines.append(f"- Session duration limit: {limit / 60:g} minutes" if limit else "- Session duration limit: unspecified")
    if requirements["notes"]:
        lines.append(requirements["notes"])
    return "\n".join(lines)


def set_workout_requirements(arguments, messages):
    validate(arguments, _REQUIREMENTS)
    # Use the shared target validator even before a draft exists.
    from .generation_audit import validate_audit_targets
    validate_audit_targets(arguments["auditTargets"])
    prior_index, prior = _latest_result(messages, "set_workout_requirements")
    if prior.get("requirements") == arguments:
        return {**copy.deepcopy(prior), "cached": True}
    if prior.get("requirements") != arguments and prior_index > _revision_index(messages):
        raise PlanningInputError("requirements_frozen", "Requirements are frozen during automatic repair.", "/",
                                 "Reuse the stored requirementsId and repair the draft. Ask the user before changing a goal.")
    result = {"requirements": copy.deepcopy(arguments), "requirementsId": "REQUIREMENTS_" + _fingerprint(arguments)[:16]}
    result["requirementsPreview"] = render_requirements(arguments)
    return result


def build_draft_plan(arguments, equipment, requirements):
    definitions = sorted(equipment.get("exerciseDefinitions", []), key=lambda d: d["id"])
    by_reference = {f"LIBRARY_{i}": d for i, d in enumerate(definitions)}
    plan = {"planName": arguments["name"], "auditTargets": copy.deepcopy(requirements["auditTargets"]),
            "equipments": copy.deepcopy(equipment.get("equipments", [])),
            "accessoryEquipments": copy.deepcopy(equipment.get("accessoryEquipments", [])), "exercises": [], "workouts": []}
    for day_index, day in enumerate(arguments["workouts"]):
        workout = {"id": f"WORKOUT_{day_index}", "name": day["name"], "description": day["description"],
                   "timesCompletedInAWeek": int(day["timesCompletedInAWeek"]), "exerciseIds": [], "restToNextSeconds": [], "supersetGroups": []}
        groups = {}
        for exercise_index, item in enumerate(day["exercises"]):
            path = f"/workouts/{day_index}/exercises/{exercise_index}"
            definition = by_reference.get(item["definition_id"])
            if definition is None:
                raise PlanningInputError("unknown_library_reference", f"Unknown library reference: {item['definition_id']}", path + "/definition_id",
                                         "Call search_exercise_library and use a returned LIBRARY_n ID; explain any movement substitution to the user.")
            kind = definition["exerciseType"]
            if kind in ("WEIGHT", "BODY_WEIGHT"):
                if item["minReps"] is None or item["maxReps"] is None or item["minReps"] > item["maxReps"]:
                    raise PlanningInputError("invalid_rep_range", "Rep-based exercises require a valid minReps/maxReps range.", path,
                                             "Provide integer minReps and maxReps with minReps <= maxReps, preserving the user's agreed rep range.")
            elif kind not in ("COUNTUP", "COUNTDOWN") or item["durationSeconds"] is None:
                raise PlanningInputError("unsupported_duration", "Timed exercises require durationSeconds; distance-only running cannot be time-audited by this draft tool.", path + "/durationSeconds",
                                         "Provide a fixed duration for COUNTUP/COUNTDOWN. For unsupported running prescriptions, explain the limitation and ask the user instead of inventing a duration.")
            exercise = {key: copy.deepcopy(definition[key]) for key in LIBRARY_DEFINITION_OWNED_FIELDS if key in definition}
            exercise.update({key: copy.deepcopy(item[key]) for key in ("numWorkSets", "minReps", "maxReps", "restBetweenSetsSeconds", "intraSetRestInSeconds", "generateWarmUpSets", "placementNotes")})
            exercise.update(id=f"EXERCISE_{len(plan['exercises'])}", libraryDefinitionId=definition["id"])
            if item.get("targetSetPrescriptions"):
                exercise["targetSetPrescriptions"] = copy.deepcopy(item["targetSetPrescriptions"])
            if item["durationSeconds"] is not None:
                exercise["timeInMillis"] = int(item["durationSeconds"] * 1000)
            plan["exercises"].append(exercise)
            workout["exerciseIds"].append(exercise["id"])
            workout["restToNextSeconds"].append(int(item["restAfterExerciseSeconds"]))
            group_name = item["superset"]
            if group_name is not None:
                if group_name not in groups:
                    groups[group_name] = {"exerciseIds": [], "restSecondsByExercise": {}}
                    workout["supersetGroups"].append(groups[group_name])
                group = groups[group_name]
                if group["exerciseIds"] and workout["exerciseIds"][-2] != group["exerciseIds"][-1]:
                    raise PlanningInputError("noncontiguous_superset", "Superset members must be contiguous.", path + "/superset",
                                             "Place all members of this group together in exercise order, or assign separate groups, then re-audit.")
                if group["exerciseIds"] and workout["restToNextSeconds"][-2]:
                    raise PlanningInputError("superset_outer_rest", "Only a superset's final member may have an outer transition rest.",
                                             f"/workouts/{day_index}/exercises/{exercise_index-1}/restAfterExerciseSeconds",
                                             "Set outer rest to zero for non-final superset members. Put round rests in restAfterSupersetExerciseSeconds and any separate transition after the final member.")
                group["exerciseIds"].append(exercise["id"])
                group["restSecondsByExercise"][exercise["id"]] = int(item["restAfterSupersetExerciseSeconds"])
        plan["workouts"].append(workout)
    _validate_draft_plan(plan, equipment)
    return plan


def _validate_draft_plan(plan, equipment):
    # The export contract uses placeholders; keep the conversational draft's original UUIDs intact.
    from .cli import PlaceholderIdManager

    manager = PlaceholderIdManager()
    provided = copy.deepcopy(equipment)
    for key, accessory in (("equipments", False), ("accessoryEquipments", True)):
        provided[key] = [manager.convert_equipment_uuids_to_placeholders(item, is_accessory=accessory)
                         for item in equipment.get(key, [])]
    for definition in provided.get("exerciseDefinitions", []):
        definition["equipmentId"] = manager.uuid_to_placeholder.get(definition.get("equipmentId"), definition.get("equipmentId"))
        definition["requiredAccessoryEquipmentIds"] = [manager.uuid_to_placeholder.get(i, i) for i in definition.get("requiredAccessoryEquipmentIds", [])]
    mapped = copy.deepcopy(plan)
    mapped["equipments"], mapped["accessoryEquipments"] = provided["equipments"], provided["accessoryEquipments"]
    hydrate_plan_index_from_exercise_library(mapped, provided.get("exerciseDefinitions", []))
    validate_plan_index_contract(mapped, provided)


def render_draft(plan, requirements, report):
    def cell(value):
        return str(value).replace("|", "/").replace("\n", " ")

    lines = [f"# {cell(plan['planName'])}", "", render_requirements(requirements)]
    by_id = {e["id"]: e for e in plan["exercises"]}
    for day, audit in zip(plan["workouts"], report["workouts"]):
        lines.extend(["", f"## {cell(day['name'])}", cell(day["description"]),
                      f"Frequency: {day['timesCompletedInAWeek']} per week. Estimated duration: {audit['estimatedSeconds'] / 60:.1f} min.",
                      "", "| Order | Exercise | Sets | Reps / duration | Rest between sets | Rest after exercise | Superset rest after this exercise | Notes |",
                      "|---|---|---|---|---|---|---|---|"])
        groups = {reference: (i + 1, group) for i, group in enumerate(day["supersetGroups"]) for reference in group["exerciseIds"]}
        for i, reference in enumerate(day["exerciseIds"]):
            e = by_id[reference]
            reps = f"{e['minReps']}–{e['maxReps']}" if e["exerciseType"] in ("WEIGHT", "BODY_WEIGHT") else f"{e['timeInMillis'] / 1000:g}s"
            if e.get("intraSetRestInSeconds"):
                reps += f" per side; {e['intraSetRestInSeconds']}s between sides"
            pair = groups.get(reference)
            between = "—" if pair else f"{e['restBetweenSetsSeconds']}s"
            round_rest = f"Group {pair[0]}: {pair[1]['restSecondsByExercise'][reference]}s" if pair else "—"
            notes = e["placementNotes"]
            if e["generateWarmUpSets"]:
                notes += " Ramp-up sets before work."
            if e.get("targetSetPrescriptions"):
                notes += " Exact work-set targets: " + json.dumps(e["targetSetPrescriptions"], separators=(",", ":"))
            lines.append(f"| {i+1} | {cell(e['name'])} | {e['numWorkSets']} | {cell(reps)} | {between} | {day['restToNextSeconds'][i]}s | {round_rest} | {cell(notes)} |")
    lines.extend(["", "Weekly volume audit:", "", "| Muscle | Direct | Indirect | Effective |", "|---|---|---|---|"])
    for muscle, values in report["weeklyVolume"].items():
        if values["effective"] or muscle in requirements["auditTargets"]["weeklyEffectiveSets"]:
            lines.append(f"| {muscle} | {values['direct']:g} | {values['indirect']:g} | {values['effective']:g} |")
    lines.extend(["", "Superset rests apply after each listed member; omit the final member's recovery after the last round. Outer exercise rests are separate.",
                  f"Duration estimate: {ASSUMPTIONS['secondsPerRep']}s/rep, both sides when unilateral, {ASSUMPTIONS['generalWarmupSeconds']//60} min general warm-up, {ASSUMPTIONS['generatedRampUpSecondsPerExercise']//60} min per generated ramp-up, {ASSUMPTIONS['transitionSeconds']}s per setup transition, plus prescribed rests and minimum calibration time.",
                  "", "Reply with exactly CONFIRM GENERATE to export this plan, or describe a revision."])
    return "\n".join(lines)


def audit_workout_plan(arguments, equipment, messages, allow_educated_load_guesses=True):
    validate(arguments, AUDIT_WORKOUT_PLAN_TOOL["function"]["parameters"])
    _, stored = _latest_result(messages, "set_workout_requirements")
    if not stored.get("requirements") or arguments["requirementsId"] != stored.get("requirementsId"):
        raise PlanningInputError("requirements_mismatch", "Call set_workout_requirements first and use its current requirementsId.", "/requirementsId",
                                 "If requirements already exist, reuse their latest requirementsId. Otherwise record the user's agreed requirements first; do not change targets to resolve this ID mismatch.")
    requirements = stored["requirements"]
    fingerprint = library_fingerprint(equipment)
    draft_id = "DRAFT_" + _fingerprint({"draft": arguments, "library": fingerprint,
        "calibration": allow_educated_load_guesses, "assumptions": ASSUMPTIONS,
        "muscles": {key: sorted(tags) for key, tags in MUSCLES.items()}})
    _, previous = _latest_result(messages, "audit_workout_plan")
    if previous.get("draftId") == draft_id:
        return {**copy.deepcopy(previous), "cached": True}
    plan = build_draft_plan(arguments, equipment, requirements)
    report = audit_workout_package(plan_audit_package(plan, allow_educated_load_guesses), requirements["auditTargets"])
    frequency = sum(w["timesCompletedInAWeek"] for w in plan["workouts"])
    if requirements["sessionsPerWeek"] is not None and frequency != requirements["sessionsPerWeek"]:
        add_audit_issue(report, "weekly_session_count_mismatch", f"Weekly sessions: {frequency}; required {requirements['sessionsPerWeek']}.",
                        "Adjust the number of workouts or their weekly frequency to match the agreed session count, then re-audit all targets.",
                        actual=frequency, expected=requirements["sessionsPerWeek"])
    result = {"passed": not report["issues"], "requirementsId": stored["requirementsId"], "audit": report,
              "draftId": draft_id, "errors": report.get("errors", []),
              "libraryFingerprint": fingerprint, "allowEducatedLoadGuesses": allow_educated_load_guesses}
    if result["passed"]:
        result["planIndex"] = plan
        result["preview"] = render_draft(plan, requirements, report)
    else:
        result["instruction"] = "Repair the interacting errors together using their paths, actual/required values, per-exercise contributions and timing breakdown. Keep requirements and library-owned fields unchanged, then resubmit the complete modified draft. Identical submissions reuse this failure; if you cannot find a feasible repair, explain the conflict and ask the user for a tradeoff."
    return result


def confirmed_draft(messages, equipment, allow_educated_load_guesses=True):
    index, result = _latest_result(messages, "audit_workout_plan")
    _, requirements = _latest_result(messages, "set_workout_requirements")
    if index < 0 or not result.get("passed"):
        raise ValueError("Submit a passing audit_workout_plan draft and review the displayed preview before confirming.")
    if result.get("requirementsId") != requirements.get("requirementsId"):
        raise ValueError("Requirements changed; audit the revised draft first.")
    if result.get("libraryFingerprint") != library_fingerprint(equipment):
        raise ValueError("The loaded library or equipment changed; audit the draft again.")
    if result.get("allowEducatedLoadGuesses") != allow_educated_load_guesses:
        raise ValueError("Calibration settings changed; audit the draft again.")
    if result.get("audit", {}).get("assumptions") != ASSUMPTIONS:
        raise ValueError("Audit assumptions changed; audit the draft again.")
    shown = any(m.get("role") == "assistant" and m.get("canonicalDraftPreview") == result.get("draftId", requirements["requirementsId"])
                and m.get("content") == result["preview"] for m in messages)
    if not shown:
        raise ValueError("The audited draft must be displayed before confirmation.")
    return copy.deepcopy(result)
