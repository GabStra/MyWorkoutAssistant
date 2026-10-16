"""One structured draft for auditing, displaying and exporting a workout plan."""

import copy
import hashlib
import json
import re

from jsonschema import validate, ValidationError

from .constants import EXACT_GENERATION_CONFIRMATION
from .generation_audit import MUSCLES, ASSUMPTIONS, audit_workout_package, plan_audit_package, add_audit_issue, available_muscle_targets
from .plan_contract import LIBRARY_DEFINITION_OWNED_FIELDS, validate_plan_index_contract, hydrate_plan_index_from_exercise_library, ContractValidationError
from .json_patching import apply_json_patch, validate_patch_operations_scope
from .muscle_roles import TRAINING_MUSCLES, TRAINING_MUSCLE_GROUPS

REQUIREMENTS_CONFIRMATION = "CONFIRM REQUIREMENTS"
AUDIT_VERSION = 8
REQUIREMENTS_VERSION = 3


class PlanningInputError(ValueError):
    def __init__(self, code, message, path, repair, errors=None):
        super().__init__(message)
        self.code, self.path, self.repair = code, path, repair
        self.errors = errors


def planning_tool_failure(tool_name, error, arguments=None):
    arguments = getattr(error, 'submitted_draft', arguments)
    repair = ("Correct the choice and its SOURCE_n references against the recorded user instructions, then call record_planning_decisions. Do not invent delegation or change goals."
              if tool_name == 'record_planning_decisions' else
              "Correct the extracted argument using the original user statements, then call set_workout_requirements. Ask and wait if meaning is ambiguous; do not invent a requirement."
              if tool_name == 'set_workout_requirements' else
              "Correct the indicated tool argument using a targeted patch against currentDraftId; preserve agreed requirements and library-owned fields, then call audit_workout_plan.")
    if isinstance(error, PlanningInputError):
        errors = error.errors or [{"code": error.code, "path": error.path, "message": str(error), "repair": error.repair}]
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
    result = {"passed": False, "tool": tool_name, "errors": errors,
            "instruction": "Follow errors[].repair. Re-audit actual draft changes. If constraints conflict, explain the conflict and ask the user; do not silently change requirements or repeatedly submit an unchanged failing draft."}
    if hasattr(error, 'submitted_draft'):
        result.update(submittedDraft=copy.deepcopy(error.submitted_draft), currentDraftId=error.draft_revision_id,
                      libraryFingerprint=error.draft_library_fingerprint)
    return result


_BOUNDS = {"type": "object", "description": "Include only muscles with user-requested targets. Omit unspecified muscles; 0-0 means an explicit ban on credited working sets, never 'no target'.", "properties": {
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
    "requiredCoverage": {"type": "array", "maxItems": 30, "description": "Only explicit user-required movement patterns, muscle work or exercise slots. No invented balance rules. The source reviewer verifies extraction; exercise suitability is checked during execution review.", "items": {
        "type": "object", "properties": {
            "key": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$", "maxLength": 60},
            "description": {"type": "string", "minLength": 1, "maxLength": 300},
            "scope": {"enum": ["eachSession", "weekly"]},
        }, "required": ["key", "description", "scope"], "additionalProperties": False}},
    "exerciseRestrictions": {"type": "object", "properties": {
        "excludeNameTerms": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1}},
        "exceptNameTerms": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1}},
    }, "required": ["excludeNameTerms", "exceptNameTerms"], "additionalProperties": False},
    "auditTargets": _TARGETS,
    "sessionsPerWeek": {"type": ["integer", "null"], "minimum": 1, "maximum": 21},
    "notes": {"type": "string", "description": "Legacy field; ignored. Original user instructions are retained by the backend, not rewritten into notes."},
}, "required": ["auditTargets", "sessionsPerWeek"], "additionalProperties": False}

SET_WORKOUT_REQUIREMENTS_TOOL = {"type": "function", "function": {
    "name": "set_workout_requirements",
    "description": "After clarifying material ambiguity, extract the user's exact numerical targets, restrictions and requiredCoverage for explicitly requested movement patterns, muscle work or exercise slots. Each submission replaces the extraction: include all still-applicable targets, restrictions, exceptions and coverage from the conversation, not only the latest answer. Omit unspecified muscle targets; zero is a prohibition. Preserve full restriction qualifiers. Original instructions and clarification answers remain authoritative without a rewritten recap. Python checks extraction against that source before showing CONFIRM REQUIREMENTS. Never lower targets to resolve conflicts. For stale policy refresh, resubmit unchanged extracted fields. For ambiguity or unsupported extraction, follow the returned repair: correct the extraction or ask and wait. Every new approved extraction needs confirmation.",
    "parameters": {**_REQUIREMENTS, "properties": {key: value for key, value in _REQUIREMENTS['properties'].items() if key != 'notes'}},
}}


def workout_requirements_tool(equipment):
    tool = copy.deepcopy(SET_WORKOUT_REQUIREMENTS_TOOL)
    supported = available_muscle_targets(equipment)
    for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets'):
        bounds = tool['function']['parameters']['properties']['auditTargets']['properties'][field]
        bounds['properties'] = {key: value for key, value in bounds['properties'].items() if key in supported}
    return tool


_EXERCISE = {"type": "object", "properties": {
    "satisfiesCoverage": {"type": "array", "uniqueItems": True, "items": {"type": "string"}, "description": "requiredCoverage keys this occurrence satisfies. The independent reviewer verifies these claims against the actual library movement; assignment alone is not proof."},
    "definition_id": {"type": "string", "pattern": "^LIBRARY_[0-9]+$"},
    "numWorkSets": {"type": "integer", "minimum": 1, "maximum": 20},
    "minReps": {"type": ["integer", "null"], "minimum": 1, "maximum": 100},
    "maxReps": {"type": ["integer", "null"], "minimum": 1, "maximum": 100},
    "durationSeconds": {"type": ["integer", "null"], "minimum": 1},
    "restBetweenSetsSeconds": {"type": "integer", "minimum": 0, "maximum": 1800, "description": "Straight sets only. Must be 0 for superset members; their rests use restAfterSupersetExerciseSeconds."},
    "restAfterExerciseSeconds": {"type": "integer", "minimum": 0, "maximum": 1800, "description": "Transition after the complete exercise/block, not between superset rounds. Must be 0 on non-final superset members."},
    "superset": {"type": ["string", "null"], "minLength": 1},
    "restAfterSupersetExerciseSeconds": {"type": "integer", "minimum": 0, "maximum": 1800, "description": "Rest after this member every superset round: A-to-B on A, round recovery on the final member (omitted after the last round). Must be 0 for straight sets. Zero transition is allowed only when intended."},
    "intraSetRestInSeconds": {"type": ["integer", "null"], "minimum": 1, "maximum": 300, "description": "Positive seconds between sides of a unilateral set; null for bilateral work. Both sides count for duration, once for muscle volume."},
    "generateWarmUpSets": {"type": "boolean"},
    "requiresEffortCalibration": {"type": "boolean", "description": "Explicitly mark uncertain resistance suitability. Required when current training evidence flags unresolved capacity or related-history concerns. No fixed load prescriptions; volume remains conditional on verifying the prescribed effort. Prefer a supported, loadable variant when available."},
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

_DRAFT_SCHEMA = AUDIT_WORKOUT_PLAN_TOOL['function']['parameters']
_PATCH_SCHEMA = {'type': 'object', 'properties': {
    'requirementsId': {'type': 'string'},
    'baseDraftId': {'type': 'string', 'pattern': '^REVISION_[0-9]+$',
                    'description': 'Copy currentDraftId from the latest snapshot; stale bases are rejected.'},
    'patch': {'type': 'array', 'description': 'RFC 6902 operations against currentDraft, applied in order. Use [] only to re-audit unchanged state after an explicit retry or new evidence.',
        'items': {'type': 'object', 'properties': {
            'op': {'enum': ['add', 'remove', 'replace', 'move', 'copy', 'test']},
            'path': {'type': 'string'}, 'from': {'type': 'string'}, 'value': {},
        }, 'required': ['op', 'path'], 'additionalProperties': False}},
}, 'required': ['requirementsId', 'baseDraftId', 'patch'], 'additionalProperties': False}
AUDIT_WORKOUT_PLAN_TOOL['function']['parameters'] = {'type': 'object', 'oneOf': [_DRAFT_SCHEMA, _PATCH_SCHEMA]}
AUDIT_WORKOUT_PLAN_TOOL['function']['description'] += (
    ' Create the initial draft with name/workouts. For repairs, send requirementsId, baseDraftId=currentDraftId and a small RFC 6902 patch '
    'against currentDraft; leave untouched fields out. Paths may edit only /name and /workouts. Python reconstructs and validates the full draft. '
    'Use full replacement only when creating a draft or when its whole structure needs replacement.')
REPAIR_WORKOUT_PLAN_TOOL = {'type': 'function', 'function': {
    **AUDIT_WORKOUT_PLAN_TOOL['function'], 'parameters': _PATCH_SCHEMA,
    'description': 'Repair the saved currentDraft using requirementsId, baseDraftId and a targeted JSON Patch. '
                   'Address repairTask first and include necessary connected changes. Other findings may remain. '
                   'Python reconstructs and validates the entire workout before any preview is approved. '
                   'Use [] only after an explicit retry or new evidence. Unchanged failures are cached.'}}


def construction_workout_tool(task):
    tool = copy.deepcopy(AUDIT_WORKOUT_PLAN_TOOL)
    schema = copy.deepcopy(_DRAFT_SCHEMA if task['action'] == 'create_first_session' else _PATCH_SCHEMA)
    if task['action'] == 'create_first_session':
        schema['properties']['workouts']['maxItems'] = 1
    tool['function'].update(parameters=schema, description=task['instruction'])
    return tool


def validate_construction_submission(arguments, task):
    """Keep each construction request to its natural unit; the normal audit still validates the complete draft."""
    validate(arguments, _DRAFT_SCHEMA if task['action'] == 'create_first_session' else _PATCH_SCHEMA)
    if task['action'] == 'create_first_session':
        valid = isinstance(arguments.get('workouts'), list) and len(arguments['workouts']) == 1 and 'patch' not in arguments
    else:
        patch = arguments.get('patch', [])
        valid = (arguments.get('baseDraftId') == task['baseDraftId'] and len(patch) == 1
                 and patch[0].get('op') == 'add' and patch[0].get('path') == '/workouts/-')
    if not valid:
        raise PlanningInputError('construction_scope_exceeded', 'Construct one workout session per submission.', '/',
            task['instruction'])


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
                if isinstance(result, dict) and result.get('skipped'):
                    continue
                if tool_name == "set_workout_requirements" and not (isinstance(result, dict) and result.get("requirements")):
                    continue
                return index, result if isinstance(result, dict) else {}
            except (ValueError, TypeError):
                if tool_name == "set_workout_requirements":
                    continue
                return index, {}
    return -1, {}


def latest_draft_submission(messages, equipment=None):
    """Read materialized repairs or legacy full submissions; never replay failed patch operations."""
    calls = {call['id']: call['function'] for message in messages for call in message.get('tool_calls', [])}
    latest, revision = None, -1
    fingerprint = library_fingerprint(equipment) if equipment is not None else None
    for message in messages:
        function = calls.get(message.get('tool_call_id'), {})
        if message.get('role') != 'tool' or function.get('name') != 'audit_workout_plan':
            continue
        if (message.get('content') or '').startswith('Tool call started'):
            continue
        try:
            payload = json.loads(message.get('content') or '{}')
        except (ValueError, TypeError):
            continue
        draft = payload.get('submittedDraft') if isinstance(payload, dict) else None
        if draft is None:
            if not isinstance(payload, dict) or payload.get('tool') == 'audit_workout_plan':
                continue
            try:
                draft = json.loads(function.get('arguments', '{}'))
            except (ValueError, TypeError):
                continue
        if isinstance(draft, dict) and isinstance(draft.get('workouts'), list):
            revision += 1
            if fingerprint and isinstance(payload, dict) and payload.get('libraryFingerprint', fingerprint) != fingerprint:
                latest = None
                continue
            identifier = payload.get('currentDraftId', f'REVISION_{revision}') if isinstance(payload, dict) else f'REVISION_{revision}'
            latest = copy.deepcopy(draft), identifier
    return latest or (None, None)


def _resolve_draft_submission(arguments, messages, equipment):
    validate(arguments, _PATCH_SCHEMA if 'patch' in arguments or 'baseDraftId' in arguments else _DRAFT_SCHEMA)
    previous, current_id = latest_draft_submission(messages, equipment)
    if 'patch' in arguments:
        if previous is None or arguments['baseDraftId'] != current_id:
            raise PlanningInputError('stale_draft_patch', 'The patch base is missing or stale.', '/baseDraftId',
                'Use the currentDraft and currentDraftId in the latest planning snapshot. Do not replay a patch against an older revision.')
        try:
            validate_patch_operations_scope(arguments['patch'], {'/name'}, {'/workouts'})
            draft = apply_json_patch(previous, arguments['patch'])
            draft['requirementsId'] = arguments['requirementsId']
            validate(draft, _DRAFT_SCHEMA)
        except (ValueError, ValidationError) as error:
            raise PlanningInputError('invalid_draft_patch', str(error), '/patch',
                'The patch was not applied. Fix its paths, values or operations against the unchanged currentDraft and currentDraftId.') from error
    else:
        draft = copy.deepcopy(arguments)
    if previous == draft:
        return draft, current_id
    revision = int(current_id.removeprefix('REVISION_')) + 1 if current_id else 0
    return draft, f'REVISION_{revision}'


def _revision_index(messages):
    return next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"
                 and (messages[i].get("content") or "").strip() not in (EXACT_GENERATION_CONFIRMATION, REQUIREMENTS_CONFIRMATION, '/continue')), -1)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def library_fingerprint(equipment):
    return _fingerprint({key: equipment.get(key, []) for key in ("exerciseDefinitions", "equipments", "accessoryEquipments")})


def requirement_sources(messages):
    return [{'messageIndex': i, 'role': m['role'], 'content': m['content']}
            for i, m in enumerate(messages) if m.get('role') in ('user', 'assistant') and m.get('content')
            and not m.get('tool_calls') and not m.get('canonicalRequirementsPreview') and not m.get('canonicalDraftPreview')
            and m['content'].strip() not in (REQUIREMENTS_CONFIRMATION, EXACT_GENERATION_CONFIRMATION, '/continue')]


def source_message_context(sources):
    return {f'SOURCE_{i}': {'role': m['role'], 'content': m['content']} for i, m in enumerate(sources)}


def render_requirements(requirements, restriction_policy=None, confirmation=False):
    lines = ["## Program requirements", "", "### Schedule", "",
             f"- Sessions per week: **{requirements['sessionsPerWeek'] or 'unspecified'}**"]
    limit = requirements["auditTargets"]["maximumSessionSeconds"]
    lines.append(f"- Session duration limit: **{limit / 60:g} minutes**" if limit else "- Session duration limit: unspecified")
    lines.extend(["", "### Effective-set targets", ""])
    weekly = requirements['auditTargets']['weeklyEffectiveSets']
    per_session = requirements['auditTargets']['perSessionEffectiveSets']
    muscles = [muscle for muscle in MUSCLES if muscle in weekly or muscle in per_session]
    if muscles:
        lines.extend(['| Muscle | Per week | Per session |', '| :--- | ---: | ---: |'])
        for muscle in muscles:
            ranges = [f"{values[muscle]['minimum']:g}–{values[muscle]['maximum']:g}" if muscle in values else '—'
                      for values in (weekly, per_session)]
            lines.append(f"| {TRAINING_MUSCLES.get(muscle, muscle.capitalize())} | {ranges[0]} | {ranges[1]} |")
        lines.extend(['', '— means no target specified. Zero is an explicit zero target.'])
    else:
        lines.append('No volume targets specified.')
    if requirements.get('requiredCoverage'):
        lines.extend(['', '### Required exercise coverage', ''])
        for rule in requirements['requiredCoverage']:
            scope = 'each session' if rule['scope'] == 'eachSession' else 'across the week'
            lines.append(f"- {rule['description']} ({scope}; `{rule['key']}`)")
    lines.extend(['', 'Your original instructions and clarification answers also apply.'])
    restrictions = requirements.get('exerciseRestrictions', {})
    sections = [('Excluded exercise / equipment terms', restrictions.get('excludeNameTerms', []))]
    if restriction_policy:
        sections.extend([('Permitted library exceptions', restriction_policy['exceptExerciseNames']),
                         ('Excluded library exercises', restriction_policy['excludedExerciseNames'])])
    elif restrictions.get('exceptNameTerms'):
        sections.append(('Exception terms', restrictions['exceptNameTerms']))
    for label, names in sections:
        if names:
            lines.extend(['', f'### {label}', ''])
            lines.extend('- ' + name for name in names)
    lines.extend(['', '### Duration-estimate defaults', '',
        'These are application estimates, separate from your requirements.', '',
        '| Item | Estimate |', '| :--- | ---: |',
        f"| Each rep | {ASSUMPTIONS['secondsPerRep']} seconds |",
        f"| General warm-up | {ASSUMPTIONS['generalWarmupSeconds']//60} minutes |",
        f"| Ramp-up per flagged exercise | {ASSUMPTIONS['generatedRampUpSecondsPerExercise']//60} minutes |",
        f"| Each setup transition | {ASSUMPTIONS['transitionSeconds']} seconds |", '',
        'Any conflict with your explicit instructions needs clarification.'])
    if confirmation:
        lines.extend(['', '### Approval', '',
            f"Reply with exactly **`{REQUIREMENTS_CONFIRMATION}`** to approve, or describe corrections."])
    return "\n".join(lines)


def set_workout_requirements(arguments, messages, equipment=None, client=None, progress=None):
    from .restriction_policy import RESTRICTION_POLICY_VERSION
    from .planning_decisions import resolved_decisions
    validate(arguments, _REQUIREMENTS)
    arguments = {**copy.deepcopy(arguments), 'notes': ''}
    keys = [rule['key'] for rule in arguments.get('requiredCoverage', [])]
    if len(set(keys)) != len(keys):
        raise PlanningInputError('duplicate_coverage_key', 'Coverage keys must be unique.', '/requiredCoverage',
                                 'Give each source-backed coverage requirement a distinct key.')
    # Use the shared target validator even before a draft exists.
    from .generation_audit import validate_audit_targets
    validate_audit_targets(arguments["auditTargets"])
    supported = available_muscle_targets(equipment)
    requested = {muscle for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets')
                 for muscle, bounds in arguments['auditTargets'][field].items() if bounds['maximum'] > 0}
    if requested - supported.keys():
        raise PlanningInputError('unsupported_muscle_targets', f'The loaded library has no auditable credit for: {sorted(requested - supported.keys())}.',
            '/auditTargets', 'Use the supportedMuscleTargets in auditPolicy. Do not alias missing regions to an aggregate. Preserve the original request and ask whether to enrich the library or explicitly change the targets.')
    prior_index, prior = _latest_result(messages, "set_workout_requirements")
    sources = requirement_sources(messages)
    decisions = resolved_decisions(messages)
    restricted = any(arguments.get('exerciseRestrictions', {}).values())
    if prior.get('supportedMuscleTargets') == supported and prior.get('requirementsVersion') == REQUIREMENTS_VERSION and prior.get('sourceMessages') == sources and prior.get('resolvedDecisions', {}) == decisions and prior.get("requirements") == arguments and (not restricted or
            (prior.get('restrictionPolicy', {}).get('libraryFingerprint') == library_fingerprint(equipment or {})
             and prior.get('restrictionPolicy', {}).get('resolutionVersion') == RESTRICTION_POLICY_VERSION)):
        return {**copy.deepcopy(prior), "cached": True}
    coverage_refresh = (prior.get('requirementsVersion') != REQUIREMENTS_VERSION
        and {key: value for key, value in prior.get('requirements', {}).items() if key != 'requiredCoverage'}
            == {key: value for key, value in arguments.items() if key != 'requiredCoverage'})
    if (prior.get('sourceReview', {}).get('passed') and prior.get("requirements") != arguments
            and prior_index > _revision_index(messages) and not coverage_refresh):
        raise PlanningInputError("requirements_frozen", "Requirements are frozen during automatic repair.", "/",
                                 "Reuse the stored requirementsId and repair the draft. Ask the user before changing a goal.")
    result = {"requirements": copy.deepcopy(arguments), 'requirementsVersion': REQUIREMENTS_VERSION,
              'supportedMuscleTargets': supported,
              'sourceMessages': sources, 'resolvedDecisions': decisions,
              "requirementsId": "REQUIREMENTS_" + _fingerprint({'version': REQUIREMENTS_VERSION, 'requirements': arguments, 'sources': sources})[:16]}
    if restricted:
        from .restriction_policy import resolve_restrictions
        result['restrictionPolicy'] = resolve_restrictions(arguments['exerciseRestrictions'], equipment or {}, client, progress)
        result['requirementsId'] = 'REQUIREMENTS_' + _fingerprint({'version': REQUIREMENTS_VERSION, 'requirements': arguments, 'sources': sources, 'restrictionPolicy': result['restrictionPolicy']})[:16]
    result["requirementsPreview"] = render_requirements(arguments, result.get('restrictionPolicy'), confirmation=True)
    return result


def requirements_approved(messages, result=None):
    if result is None:
        _, result = _latest_result(messages, "set_workout_requirements")
    if not result.get('requirementsId'):
        return False
    review = result.get('sourceReview', {})
    from .plan_review import REQUIREMENTS_REVIEW_VERSION, _requirements_context, _hash
    if (result.get('requirementsVersion') != REQUIREMENTS_VERSION or review.get('version') != REQUIREMENTS_REVIEW_VERSION
            or not review.get('passed') or review.get('failure') or review.get('auditPolicy') != ASSUMPTIONS
            or any(f.get('severity') == 'blocking' for f in review.get('findings', []))):
        return False
    if review.get('inputHash') != _hash(_requirements_context(result)):
        return False
    shown = next((i for i in range(len(messages) - 1, -1, -1)
                  if messages[i].get('role') == 'assistant' and messages[i].get('canonicalRequirementsPreview') == result['requirementsId']
                  and messages[i].get('content') == result['requirementsPreview']), None)
    return shown is not None and any(message.get('role') == 'user' and
        (message.get('content') or '').strip() == REQUIREMENTS_CONFIRMATION for message in messages[shown + 1:])


def require_approved_requirements(messages):
    if not requirements_approved(messages):
        raise PlanningInputError('requirements_not_approved', 'The extracted requirements need user approval.', '/',
                                 f'Display the requirements and wait for {REQUIREMENTS_CONFIRMATION}. Do not search, plan, or invent an approved tradeoff.')


def build_draft_plan(arguments, equipment, requirements, restriction_policy=None):
    if any(requirements.get('exerciseRestrictions', {}).values()) and restriction_policy is None:
        raise PlanningInputError('restriction_policy_unresolved', 'Resolve restrictions to library IDs before building a draft.',
                                 '/exerciseRestrictions', 'Record requirements against the current library, display the resolved policy and get confirmation.')
    definitions = sorted(equipment.get("exerciseDefinitions", []), key=lambda d: d["id"])
    by_reference = {f"LIBRARY_{i}": d for i, d in enumerate(definitions)}
    plan = {"planName": arguments["name"], "auditTargets": copy.deepcopy(requirements["auditTargets"]),
            "equipments": copy.deepcopy(equipment.get("equipments", [])),
            "accessoryEquipments": copy.deepcopy(equipment.get("accessoryEquipments", [])), "exercises": [], "workouts": []}
    input_errors = []
    for day_index, day in enumerate(arguments["workouts"]):
        workout = {"id": f"WORKOUT_{day_index}", "name": day["name"], "description": day["description"],
                   "timesCompletedInAWeek": int(day["timesCompletedInAWeek"]), "exerciseIds": [], "restToNextSeconds": [], "supersetGroups": []}
        groups = {}
        for exercise_index, item in enumerate(day["exercises"]):
            path = f"/workouts/{day_index}/exercises/{exercise_index}"
            if item['superset'] is not None and item['restBetweenSetsSeconds']:
                input_errors.append({'code': 'conflicting_superset_rest', 'path': path + '/restBetweenSetsSeconds',
                    'message': 'Superset member has a straight-set rest that the app does not execute.',
                    'repair': 'Put the intended A-to-B or round recovery in restAfterSupersetExerciseSeconds and set restBetweenSetsSeconds=0. Do not remove the intended rest to meet the time limit.'})
            if item['superset'] is None and item['restAfterSupersetExerciseSeconds']:
                input_errors.append({'code': 'unused_superset_rest', 'path': path + '/restAfterSupersetExerciseSeconds',
                    'message': 'Straight-set exercise has a superset rest that the app does not execute.',
                    'repair': 'Use restBetweenSetsSeconds for between-set rest or restAfterExerciseSeconds for a transition; set restAfterSupersetExerciseSeconds=0.'})
            definition = by_reference.get(item["definition_id"])
            if definition is None:
                raise PlanningInputError("unknown_library_reference", f"Unknown library reference: {item['definition_id']}", path + "/definition_id",
                                         "Call search_exercise_library and use a returned LIBRARY_n ID; explain any movement substitution to the user.")
            from .exercise_library_tools import definition_available
            if not definition_available(definition, equipment, restriction_policy or {}):
                raise PlanningInputError('excluded_exercise', f"Exercise '{definition['name']}' violates approved restrictions or lacks equipment.", path,
                                         'Choose a permitted exercise. Do not remove restrictions to make the draft pass.')
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
            if item.get('requiresEffortCalibration'):
                if item.get('targetSetPrescriptions'):
                    raise PlanningInputError('effort_calibration_with_fixed_load', 'Effort calibration cannot also assert fixed work-set loads.', path,
                                             'Remove targetSetPrescriptions or select an exercise supported by current evidence.')
                exercise['requiresEffortCalibration'] = True
                exercise['placementNotes'] += (' Effort calibration required before counting these as hard working sets: verify the prescribed reps/RIR. '
                    'Calibration attempts are additional to working sets. If available resistance is too easy, select a loadable variant and re-audit; '
                    'do not substitute extra sets or tempo without revalidation.')
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
                    input_errors.append({'code': 'superset_outer_rest',
                        'path': f"/workouts/{day_index}/exercises/{exercise_index-1}/restAfterExerciseSeconds",
                        'message': "Only a superset's final member may have an outer transition rest.",
                        'repair': 'Set outer rest to zero for non-final members. Put round rests in restAfterSupersetExerciseSeconds and any separate transition after the final member.'})
                group["exerciseIds"].append(exercise["id"])
                group["restSecondsByExercise"][exercise["id"]] = int(item["restAfterSupersetExerciseSeconds"])
        plan["workouts"].append(workout)
    try:
        _validate_draft_plan(plan, equipment)
    except ContractValidationError as error:
        input_errors.extend(planning_tool_failure('audit_workout_plan', error, arguments)['errors'])
    if input_errors:
        first = input_errors[0]
        raise PlanningInputError(first['code'], first['message'], first['path'], first['repair'], errors=input_errors)
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


def render_draft(plan, requirements, report, restriction_policy=None):
    def cell(value):
        return str(value).replace("|", "/").replace("\n", " ")

    lines = [f"# {cell(plan['planName'])}", "", render_requirements(requirements, restriction_policy)]
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
        requested = any(muscle in requirements['auditTargets'][field] for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets'))
        if (muscle in TRAINING_MUSCLE_GROUPS and not requested
                and any(report['weeklyVolume'][member]['effective'] for member in TRAINING_MUSCLE_GROUPS[muscle])):
            continue
        if values["effective"] or muscle in requirements["auditTargets"]["weeklyEffectiveSets"]:
            lines.append(f"| {TRAINING_MUSCLES.get(muscle, muscle.capitalize())} | {values['direct']:g} | {values['indirect']:g} | {values['effective']:g} |")
    lines.extend(["", "Superset rests apply after each listed member; omit the final member's recovery after the last round. Outer exercise rests are separate.",
                  f"Duration estimate: {ASSUMPTIONS['secondsPerRep']}s/rep, both sides when unilateral, {ASSUMPTIONS['generalWarmupSeconds']//60} min general warm-up, {ASSUMPTIONS['generatedRampUpSecondsPerExercise']//60} min per generated ramp-up, {ASSUMPTIONS['transitionSeconds']}s per setup transition, plus prescribed rests and minimum calibration time.",
                  "", "Reply with exactly CONFIRM GENERATE to export this plan, or describe a revision."])
    return "\n".join(lines)


def _audit_coverage(arguments, requirements, report):
    rules = {rule['key']: rule for rule in requirements.get('requiredCoverage', [])}
    covered_week = set()
    for day_index, day in enumerate(arguments['workouts']):
        covered = set()
        for index, item in enumerate(day['exercises']):
            claims = set(item.get('satisfiesCoverage', []))
            unknown = claims - rules.keys()
            if unknown:
                add_audit_issue(report, 'unknown_coverage_key', f"Unknown coverage keys: {sorted(unknown)}.",
                    'Use only approved requiredCoverage keys; do not invent a requirement.',
                    path=f'/workouts/{day_index}/exercises/{index}/satisfiesCoverage')
            covered.update(claims & rules.keys())
        covered_week.update(covered)
        for key, rule in rules.items():
            if rule['scope'] == 'eachSession' and key not in covered:
                add_audit_issue(report, 'required_coverage_missing', f"{day['name']}: missing {rule['description']}.",
                    f'Assign satisfiesCoverage={key!r} only to a qualifying exercise, or add/replace a movement and re-audit. Execution review verifies the assignment.',
                    path=f'/workouts/{day_index}/exercises', coverageKey=key)
    for key, rule in rules.items():
        if rule['scope'] == 'weekly' and key not in covered_week:
            add_audit_issue(report, 'required_coverage_missing', f"Weekly plan: missing {rule['description']}.",
                f'Include a qualifying exercise with satisfiesCoverage={key!r} and re-audit. Do not change the requirement.', coverageKey=key)


def audit_workout_plan(arguments, equipment, messages, allow_educated_load_guesses=True, training_history=None):
    from .planning_decisions import resolved_decisions, render_decisions
    require_approved_requirements(messages)
    arguments, revision_id = _resolve_draft_submission(arguments, messages, equipment)
    _, stored = _latest_result(messages, "set_workout_requirements")
    if not stored.get("requirements") or arguments["requirementsId"] != stored.get("requirementsId"):
        raise PlanningInputError("requirements_mismatch", "Call set_workout_requirements first and use its current requirementsId.", "/requirementsId",
                                 "If requirements already exist, reuse their latest requirementsId. Otherwise record the user's agreed requirements first; do not change targets to resolve this ID mismatch.")
    requirements = stored["requirements"]
    from .restriction_policy import effective_restrictions
    restriction_policy = effective_restrictions(stored, equipment)
    fingerprint = library_fingerprint(equipment)
    decisions = resolved_decisions(messages)
    draft_id = "DRAFT_" + _fingerprint({"auditVersion": AUDIT_VERSION, "draft": arguments, "library": fingerprint,
        "history": training_history.fingerprint if training_history else None,
        "calibration": allow_educated_load_guesses, "assumptions": ASSUMPTIONS, 'resolvedDecisions': decisions,
        "muscles": {key: sorted(tags) for key, tags in MUSCLES.items()}})
    _, previous = _latest_result(messages, "audit_workout_plan")
    if not training_history and previous.get("draftId") == draft_id and 'review' not in previous:
        return {**copy.deepcopy(previous), "cached": True, 'submittedDraft': copy.deepcopy(arguments), 'currentDraftId': revision_id}
    try:
        plan = build_draft_plan(arguments, equipment, requirements, restriction_policy)
    except (ValueError, ValidationError) as error:
        error.submitted_draft = copy.deepcopy(arguments)
        error.draft_revision_id = revision_id
        error.draft_library_fingerprint = fingerprint
        raise
    report = audit_workout_package(plan_audit_package(plan, allow_educated_load_guesses), requirements["auditTargets"])
    _audit_coverage(arguments, requirements, report)
    frequency = sum(w["timesCompletedInAWeek"] for w in plan["workouts"])
    if requirements["sessionsPerWeek"] is not None and frequency != requirements["sessionsPerWeek"]:
        add_audit_issue(report, "weekly_session_count_mismatch", f"Weekly sessions: {frequency}; required {requirements['sessionsPerWeek']}.",
                        "Adjust the number of workouts or their weekly frequency to match the agreed session count, then re-audit all targets.",
                        actual=frequency, expected=requirements["sessionsPerWeek"])
    if training_history:
        missing = training_history.unreviewed(plan, messages, equipment)
        if missing:
            add_audit_issue(report, 'training_evidence_required', 'Current training evidence is missing for selected movements.',
                'Retrieve get_training_evidence for definition_ids, reconsider choices and starting loads, and repair these issues together with the numerical findings.',
                definition_ids=missing)
        for error in training_history.load_suitability_errors(plan, messages, equipment):
            report['errors'].append(error)
            report['issues'].append(error.get('message', error['code']))
    result = {"passed": not report["issues"], "requirementsId": stored["requirementsId"], "audit": report,
              "auditVersion": AUDIT_VERSION,
              "draftId": draft_id, "errors": report.get("errors", []),
              "submittedDraft": copy.deepcopy(arguments), "currentDraftId": revision_id,
              "planIndex": plan,
              'resolvedDecisions': decisions,
              "libraryFingerprint": fingerprint, "allowEducatedLoadGuesses": allow_educated_load_guesses}
    if result["passed"]:
        result["preview"] = render_draft(plan, requirements, report, restriction_policy)
        if decisions:
            result['preview'] += '\n\nResolved planning choices:\n' + render_decisions(decisions)
        if any(e.get('requiresEffortCalibration') for e in plan['exercises']):
            result['preview'] += ('\n\nEffort verification pending: the volume totals are prescribed targets, conditional on the marked exercises '
                                  'meeting the requested effort during calibration. The numerical audit does not verify actual hard-set stimulus.')
    else:
        result["instruction"] = "Follow repairTask when supplied. Otherwise address the first finding with a small coordinated patch, using contributions and timing. Preserve interacting constraints; other findings may remain for the next audit. Consider increasing and decreasing sets across existing exercises before adding movements. Python rechecks the entire draft against all targets. Preserve requirements and library fields, then resubmit promptly. Identical submissions reuse this failure; ask about genuine conflicts instead of relaxing goals."
    return result


def confirmed_draft(messages, equipment, allow_educated_load_guesses=True, *, require_confirmation=False):
    from .planning_decisions import resolved_decisions
    require_approved_requirements(messages)
    index, result = _latest_result(messages, "audit_workout_plan")
    _, requirements = _latest_result(messages, "set_workout_requirements")
    from .restriction_policy import effective_restrictions
    effective_restrictions(requirements, equipment)
    if index < 0 or not result.get("passed"):
        raise ValueError("Submit a passing audit_workout_plan draft and review the displayed preview before confirming.")
    if result.get('resolvedDecisions', {}) != resolved_decisions(messages):
        raise ValueError('Planning choices changed; re-audit the draft before confirmation.')
    if result.get("requirementsId") != requirements.get("requirementsId"):
        raise ValueError("Requirements changed; audit the revised draft first.")
    if result.get("libraryFingerprint") != library_fingerprint(equipment):
        raise ValueError("The loaded library or equipment changed; audit the draft again.")
    if result.get("allowEducatedLoadGuesses") != allow_educated_load_guesses:
        raise ValueError("Calibration settings changed; audit the draft again.")
    if result.get("audit", {}).get("assumptions") != ASSUMPTIONS:
        raise ValueError("Audit assumptions changed; audit the draft again.")
    if result.get('auditVersion') != AUDIT_VERSION:
        raise ValueError('Audit validation changed; re-audit the saved draft before confirmation.')
    preview_indexes = [i for i, m in enumerate(messages) if m.get("role") == "assistant"
                       and m.get("canonicalDraftPreview") == result.get("draftId", requirements["requirementsId"])
                       and m.get("content") == result["preview"]]
    if not preview_indexes:
        raise ValueError("The audited draft must be displayed before confirmation.")
    if require_confirmation and not any(m.get('role') == 'user'
            and (m.get('content') or '').strip() == EXACT_GENERATION_CONFIRMATION
            for m in messages[min(preview_indexes) + 1:]):
        raise ValueError('The current draft needs a fresh CONFIRM GENERATE after its preview is displayed.')
    return copy.deepcopy(result)
