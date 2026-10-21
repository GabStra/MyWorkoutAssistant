"""One structured draft for auditing, displaying and exporting a workout plan."""

import copy
import hashlib
import heapq
import json
import math
import re

from jsonschema import validate, ValidationError, Draft7Validator

from .constants import EXACT_GENERATION_CONFIRMATION, JSON_SCHEMA
from .generation_audit import MUSCLES, ASSUMPTIONS, audit_workout_package, plan_audit_package, add_audit_issue, available_muscle_targets
from .plan_contract import LIBRARY_DEFINITION_OWNED_FIELDS, validate_plan_index_contract, hydrate_plan_index_from_exercise_library, ContractValidationError
from .json_patching import apply_json_patch, validate_patch_operations_scope
from .muscle_roles import MUSCLE_LABELS
from .programming_guidelines import EXECUTION_RULES_SCHEMA, execution_rule_errors, render_execution_rule, audit_execution_rules, audit_execution_details, normalize_work_set_bounds
from .domain_ops import get_selectable_weights_for_exercise
from .recipe_contracts import PROGRESSION_PLAN_SCHEMA, progression_note, validate_progression_plan
from .requirement_accounting import ACCOUNTING_SCHEMA
from .repair_capabilities import (WORKING_SET_UNDERPERFORMANCE_GUIDANCE,
    has_unresolved_capabilities, repair_capability_contract,
    repair_field_dimensions as _repair_field_dimensions)

REQUIREMENTS_CONFIRMATION = "CONFIRM REQUIREMENTS"
AUDIT_VERSION = 43
REQUIREMENTS_VERSION = 10
# Bound model-written cues; deterministic guidance is not squeezed into this allowance.
_NOTES_SCHEMA = {'type': 'string', 'maxLength': 500}
_LOCAL_RIR_CLAIM = re.compile(r'\b\d+(?:\s*[-–]\s*\d+)?\s*RIR\b', re.IGNORECASE)
_LOCAL_PROGRESSION_CLAIM = re.compile(
    r'\b(?:rep ceiling|at ceiling|next selectable|selectable load|progression trigger|higher-rep re-audit)\b',
    re.IGNORECASE)


def effort_acceptance_guidance(effort_acceptance, working_set_rir=None):
    acceptance = effort_acceptance or ({'kind': 'rir_range', 'minimumRIR': working_set_rir['minimum'],
        'maximumRIR': working_set_rir['maximum'], 'acceptanceCriterion': None, 'terminationCriterion': None}
        if working_set_rir else None)
    if not acceptance:
        return ''
    target_label = 'Working-set acceptance'
    if acceptance['kind'] == 'rir_range':
        source = 'approved' if working_set_rir else 'plan-selected'
        text = (f"{target_label}: complete prescribed reps/time at {acceptance['minimumRIR']:g}–"
            f"{acceptance['maximumRIR']:g} RIR ({source} target). Stop for pain or loss of control. ")
    else:
        source = 'approved' if working_set_rir else 'plan-selected'
        text = (f"{target_label} ({source} technical criteria): accept only when {acceptance['acceptanceCriterion']} Stop when "
            f"{acceptance['terminationCriterion']}. Do not force reps past that limit; stop for pain or loss of control. ")
    text += WORKING_SET_UNDERPERFORMANCE_GUIDANCE + ' '
    return text


_PROGRESSION_NOTES = {
    'doubleProgression': ' Log sets. At prescribed effort, reach the rep ceiling on all sets before adding a supported load step. If load-capped, re-audit.',
    'reps': ' Log sets. Add reps within range at required effort. Stop at the rep ceiling; a new prescription is required before changing resistance or configuration.',
    'duration': ' Log accepted working durations at the prescribed effort. Re-audit planned duration increases against the time limit.',
    'sourceDefined': '',
}
_WORKOUT_DESCRIPTION_SCHEMA = JSON_SCHEMA['$defs']['Workout']['properties']['description']


def export_text_contract(text, schema, generated_text=''):
    maximum = max(0, schema['maxLength'] - len(generated_text))
    return {'text': text, 'maximumCharacters': maximum, 'currentCharacters': len(text),
            'charactersToRemove': max(0, len(text) - maximum),
            'exportMaximumCharacters': schema['maxLength'], 'generatedText': generated_text,
            'reservedCharacters': len(generated_text)}


def description_text_contract(day):
    return {**export_text_contract(day.get('description', ''), _WORKOUT_DESCRIPTION_SCHEMA,
                                  workout_schedule_suffix(day.get('trainingDays', []))),
            'purpose': 'Short training-focus label, not an exercise list or coaching instructions.',
            'example': 'Full body',
            'repair': 'Rewrite as a shorter focus label with margin below maximumCharacters. Do not include generatedText; Python adds it. Preserve schedule, exercises and prescriptions.'}


def placement_notes_limit(item):
    return _NOTES_SCHEMA['maxLength']


def placement_notes_text_contract(item, working_set_rir=None):
    generated = generated_progression_note(item)
    generated += effort_acceptance_guidance(item.get('effortAcceptance'), working_set_rir)
    contract = export_text_contract(item.get('placementNotes', ''), _NOTES_SCHEMA)
    contract.update(generatedText=generated, reservedCharacters=0,
                    exportMaximumCharacters=_NOTES_SCHEMA['maxLength'] + len(generated))
    repair = 'Use local technique/setup cues only; do not invent a numeric RIR target, trial settings, calibration loads, counts or generatedText. Preserve valid execution and stop rules. Do not change the prescription to make text fit.'
    return {**contract,
            'purpose': 'Local execution/setup cues only; typed effort acceptance and progression guidance are rendered separately.',
            'repair': repair}


def generated_progression_note(item):
    if not item.get('progressionPlan'):
        return _PROGRESSION_NOTES.get(item.get('progressionMethod'), '')
    prescriptions = ([item['workSetTemplate']] if item.get('workSetTemplate') else item.get('targetSetPrescriptions', []))
    exact_reps = ([entry['reps'] for entry in prescriptions]
                  if prescriptions and all(isinstance(entry.get('reps'), int) for entry in prescriptions) else None)
    rep_range = (item['minReps'], item['maxReps']) if all(
        isinstance(item.get(key), int) for key in ('minReps', 'maxReps')) else None
    return progression_note(item['progressionPlan'], exact_reps, rep_range, item.get('progressionMethod'))


def workout_schedule_suffix(training_days):
    names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    return ' Schedule: ' + ', '.join(names[day] for day in sorted(training_days)) + '.' if training_days else ''


class PlanningInputError(ValueError):
    def __init__(self, code, message, path, repair, errors=None):
        super().__init__(message)
        self.code, self.path, self.repair = code, path, repair
        self.errors = errors
        self.partial_plan = None


def _reject_unresolved_repair_capability(task):
    assessment = (task or {}).get('findingsAssessment')
    if has_unresolved_capabilities(assessment):
        reasons = [group['reason'] for group in assessment['groups']
            if group.get('disposition') == 'unresolved_capability']
        raise PlanningInputError('unresolved_review_capability',
            'The independent review requires behavior the current generator cannot provide.',
            '/findingsAssessment',
            'Do not compile or audit a subset repair. Preserve the finding, implement the missing supported capability or ask the user about a supported alternative. ' + ' '.join(reasons))


def planning_tool_failure(tool_name, error, arguments=None):
    arguments = getattr(error, 'submitted_draft', arguments)
    repair = ("Correct the choice and its SOURCE_n references against the recorded user instructions, then call record_planning_decisions. Do not invent delegation or change goals."
              if tool_name == 'record_planning_decisions' else
              "Correct the extracted argument using the original user statements, then call set_workout_requirements. Ask and wait if meaning is ambiguous; do not invent a requirement."
              if tool_name == 'set_workout_requirements' else
              f"Correct the indicated preparation arguments, preserve unaffected movement choices and approved requirements, then call {tool_name} again. No draft changes were applied."
              if tool_name in ('prepare_workout_session', 'prepare_workout_sessions', 'draft_workout_sessions') else
              "Correct the rejected typed edits and submit them through repair_workout_alternative using the saved repairCandidateId and originalRequirementsId. Preserve the fixed hypothetical targets and original restrictions; no rejected edits were applied."
              if tool_name == 'repair_workout_alternative' else
              f"Correct the lookup arguments and use returned library references, then call {tool_name} again. Do not change the workout or its requirements to repair a lookup."
              if tool_name in ('get_training_evidence', 'get_exercise_candidates', 'search_exercise_library', 'get_workout_draft') else
              ("Correct the indicated typed edits using currentDraftId and the stable WORKOUT_n/EXERCISE_n references; "
               "keep setFields and removeOptionalFields as sibling keys, preserve approved requirements and limits, "
               "then resubmit through the coordinated edit tool. No malformed edit was applied."
               if tool_name == 'audit_workout_plan' and isinstance(arguments, dict) and 'edits' in arguments else
               "Correct the indicated tool argument using a targeted patch against currentDraftId; preserve agreed requirements and library-owned fields, then call audit_workout_plan."))
    if isinstance(error, PlanningInputError):
        errors = error.errors or [{"code": error.code, "path": error.path, "message": str(error), "repair": error.repair}]
    elif isinstance(error, ValidationError):
        validation_errors = getattr(error, 'validation_errors', [error])
        schema_root = getattr(error, 'validation_schema', None)
        errors = []
        for validation_error in validation_errors:
            path_parts = list(validation_error.absolute_path)
            path = "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in path_parts)
            item_repair = repair
            diagnostic = {"code": "invalid_arguments", "path": path, "message": validation_error.message,
                "validator": validation_error.validator, "expected": validation_error.validator_value,
                "actual": validation_error.instance if not isinstance(validation_error.instance, (dict, list)) else None,
                "repair": item_repair}
            if schema_root is not None and validation_error.validator == 'additionalProperties':
                correction = _schema_sibling_correction(validation_error, schema_root, arguments)
                if correction:
                    diagnostic.update(correction)
                    diagnostic['repair'] = correction['repair']
            if validation_error.validator == 'maxLength' and path.endswith('/placementNotes'):
                contract = placement_notes_text_contract({'placementNotes': validation_error.instance})
                contract['maximumCharacters'] = validation_error.validator_value
                contract['exportMaximumCharacters'] = validation_error.validator_value
                contract['charactersToRemove'] = max(0, len(validation_error.instance) - validation_error.validator_value)
                diagnostic['textFieldContract'] = {key: value for key, value in contract.items() if key != 'text'}
                diagnostic['repair'] += ' ' + contract['repair']
            if path.endswith('/workSetTemplate') or '/workSetTemplate/' in path or '/targetSetPrescriptions' in path:
                diagnostic['repair'] += (' Keep the approved work-set count range unchanged. Correct the prescription with '
                    'workSetTemplate for uniform targets or targetSetPrescriptions for distinct set targets; '
                    'do not remove or widen allocationBounds to make it fit.')
            errors.append(diagnostic)
        errors.extend(getattr(error, 'supplemental_errors', []))
    elif isinstance(error, ContractValidationError) and error.issues:
        positions = [(d, e) for d, day in enumerate((arguments or {}).get("workouts", [])) for e, _ in enumerate(day.get("exercises", []))]
        errors = []
        for issue in error.issues:
            match = re.search(r"\bEXERCISE_(\d+)\b", issue.message)
            path = "/workouts"
            if match and int(match.group(1)) < len(positions):
                day, exercise = positions[int(match.group(1))]
                path = f"/workouts/{day}/exercises/{exercise}"
            issue_repair = repair
            if issue.code == 'target_set_prescription_outside_rep_range' and match:
                work_set = re.search(r"workSetIndex=(\d+)", issue.message)
                if match and int(match.group(1)) < len(positions):
                    source_day, source_exercise = positions[int(match.group(1))]
                    source = (arguments or {}).get('workouts', [])[source_day].get('exercises', [])[source_exercise]
                    minimum, maximum = source.get('minReps'), source.get('maxReps')
                    approved_range = (f"{minimum}–{maximum}" if isinstance(minimum, int) and isinstance(maximum, int)
                                      else 'the existing minReps–maxReps range')
                    if 'workSetTemplate' in source:
                        path = f"/workouts/{source_day}/exercises/{source_exercise}/workSetTemplate/reps"
                        source_field = 'workSetTemplate.reps'
                    elif work_set:
                        prescription_index = int(work_set.group(1))
                        source_targets = source.get('targetSetPrescriptions', [])
                        source_index = next((index for index, target in enumerate(source_targets)
                            if target.get('workSetIndex') == prescription_index), None)
                        if source_index is not None:
                            path = f"/workouts/{source_day}/exercises/{source_exercise}/targetSetPrescriptions/{source_index}/reps"
                        source_field = f'targetSetPrescriptions workSetIndex={prescription_index} reps'
                    else:
                        source_field = 'the source rep target'
                    issue_repair = (f"Keep the existing rep range {approved_range} unchanged. Correct {source_field} "
                        "to fit it. Do not change minReps/maxReps to admit an out-of-range set or invent rep drop-off.")
            errors.append({"code": issue.code, "path": path, "message": issue.message, "repair": issue_repair,
                           "exerciseId": match.group(0) if match else None})
    else:
        editable = isinstance(error, ValueError)
        errors = [{"code": "invalid_plan" if editable else "tool_execution_failed", "path": "/",
                   "message": str(error), "repair": repair if editable else "Report this execution failure; do not change the draft or relax goals to hide it."}]
    result = {"passed": False, "tool": tool_name, "errors": errors,
            "instruction": "Follow errors[].repair. Re-audit actual draft changes. If constraints conflict, explain the conflict and ask the user; do not silently change requirements or repeatedly submit an unchanged failing draft."}
    result['planningOutcome'] = {'status': 'unresolved', 'scope': 'Current tool execution; no requirement conflict established.'}
    for item in errors:
        item['owner'] = ('rendering' if is_metadata_error(item) else 'generator' if item['code'] == 'tool_execution_failed'
                         else 'requirements' if tool_name == 'set_workout_requirements' else 'candidate')
    if tool_name == 'prepare_workout_sessions':
        from .session_drafting import DRAFTING_VERSION
        result['draftingVersion'] = DRAFTING_VERSION
    if any(item['code'] == 'set_allocation_unproven' for item in errors):
        result.update(executionFailure=True, instruction='The bounded solve did not produce a verified result. Preserve the proposal and approved constraints; do not claim infeasibility or ask for a tradeoff. An explicit /continue retries the saved proposal.')
    if any(item['code'] == 'tool_execution_failed' for item in errors):
        result.update(executionFailure=True, instruction='Report this internal tool failure and pause. Do not edit the workout, rephrase lookups or retry automatically to hide it. Completed independent results remain valid; retry only after an explicit user request or a code fix.')
    if hasattr(error, 'submitted_draft'):
        result.update(submittedDraft=copy.deepcopy(error.submitted_draft), currentDraftId=error.draft_revision_id,
                      libraryFingerprint=error.draft_library_fingerprint)
    if hasattr(error, 'preparation_arguments'):
        result['preparationArguments'] = copy.deepcopy(error.preparation_arguments)
    if hasattr(error, 'preparation_repair_task'):
        result['preparationRepairTask'] = copy.deepcopy(error.preparation_repair_task)
    rejected = rejected_metadata_patch(result, arguments)
    if rejected:
        result['rejectedSubmission'] = rejected
        result['instruction'] += ' No operations were applied. Python retains rejectedSubmission; send only the indicated text corrections and it will replay the other operations unchanged.'
    return result


def _schema_value_at_path(schema, path, instance=None):
    """Follow an instance path through the simple properties/items schema emitted by our tools."""
    current = schema
    consumed = []
    for part in path:
        if isinstance(current, dict) and current.get('oneOf'):
            value = _instance_value_at_path(instance, consumed) if instance is not None else None
            branches = current['oneOf']
            matching = [branch for branch in branches if isinstance(value, dict) and all(
                key not in value or value[key] in sub_schema.get('enum', [value[key]])
                for key, sub_schema in branch.get('properties', {}).items()
                if isinstance(sub_schema, dict) and 'enum' in sub_schema)]
            if len(matching) == 1:
                current = matching[0]
        if isinstance(part, int):
            current = current.get('items', {}) if isinstance(current, dict) else {}
        else:
            current = current.get('properties', {}).get(part, {}) if isinstance(current, dict) else {}
        consumed.append(part)
    return current if isinstance(current, dict) else {}


def _instance_value_at_path(instance, path):
    current = instance
    for part in path:
        try:
            current = current[part]
        except (KeyError, IndexError, TypeError):
            return None
    return current


def _schema_sibling_correction(error, schema_root, arguments):
    """Explain an unexpected nested key and, when schema makes it unambiguous, show its sibling location."""
    if not isinstance(error.instance, dict):
        return None
    allowed = set((error.schema or {}).get('properties', {}))
    unexpected = sorted(set(error.instance) - allowed)
    if not unexpected:
        return None
    path_parts = list(error.absolute_path)
    parent_path = path_parts[:-1]
    parent_schema = _schema_value_at_path(schema_root, parent_path, arguments)
    parent_properties = parent_schema.get('properties', {})
    misplaced = [key for key in unexpected if key in parent_properties]
    if not misplaced:
        return {'repair': (f"At {('/' + '/'.join(map(str, path_parts)))}, only these keys are allowed: "
            f"{', '.join(sorted(allowed)) or '(none)'}. Remove or correct unexpected key(s) {', '.join(unexpected)} "
            'according to the advertised typed-edit schema; do not resubmit unchanged intent.')}
    entry_path = parent_path
    entry = _instance_value_at_path(arguments, entry_path)
    if not isinstance(entry, dict):
        return None
    example = copy.deepcopy(entry)
    current_field = path_parts[-1] if path_parts else None
    nested = example.get(current_field)
    if not isinstance(nested, dict):
        return None
    for key in misplaced:
        value = nested.pop(key)
        if key in example:
            return None
        example[key] = value
    ref_key = next((key for key in ('exerciseRef', 'workoutRef') if key in example), None)
    stable_ref = f" for {example[ref_key]}" if ref_key else ''
    sibling_paths = [
        '/' + '/'.join(str(part).replace('~', '~0').replace('/', '~1') for part in (*entry_path, key))
        for key in misplaced]
    path_text = '/' + '/'.join(str(part).replace('~', '~0').replace('/', '~1') for part in path_parts)
    return {'repair': (f"Unexpected key(s) {', '.join(unexpected)} at {path_text}{stable_ref}. "
        f"Allowed keys there are: {', '.join(sorted(allowed)) or '(none)'}. "
        f"Move {', '.join(misplaced)} beside {current_field} at {', '.join(sibling_paths)}. "
        f"Schema-shaped example: {json.dumps(example, separators=(',', ':'))}. "
        'This example is guidance only: submit corrected typed edits explicitly; no malformed edit was applied.')}


def is_metadata_error(error):
    return bool(re.fullmatch(r'/(?:workouts/\d+/(?:description|exercises/\d+/placementNotes)|sessions/\d+/description)', error.get('path', ''))
        and (error.get('code') in ('export_description_too_long', 'export_notes_too_long',
                                   'effort_acceptance_in_local_notes', 'progression_in_local_notes')
             or (error.get('code') == 'invalid_arguments' and error.get('validator') == 'maxLength')))


def rejected_metadata_patch(result, arguments):
    """Keep an atomic proposal available when only text fields rejected it."""
    errors = result.get('errors', [])
    if (result.get('tool') == 'audit_workout_plan' and not result.get('submittedDraft')
            and isinstance(arguments, dict) and 'patch' in arguments and errors
            and all(is_metadata_error(error) for error in errors)):
        return copy.deepcopy(arguments)
    return None


def planning_failure_signature(tool_name, arguments, feedback, messages):
    candidate = feedback.get('preparationArguments') or feedback.get('submittedDraft')
    if candidate is None and feedback.get('preparationRepairTask'):
        candidate = feedback['preparationRepairTask']['arguments']
    if feedback.get('rejectedSubmission'):
        draft, _ = latest_draft_submission(messages)
        if draft is not None:
            candidate = apply_json_patch(draft, feedback['rejectedSubmission']['patch'])
    if candidate is None:
        candidate = ({key: value for key, value in arguments.items() if key != 'basePreparationId'}
                     if isinstance(arguments, dict) else arguments)
    errors = feedback.get('errors') or [item['error'] for item in feedback.get('results', []) if item.get('error')]
    return json.dumps([tool_name, candidate, errors], sort_keys=True)


def metadata_patch_tool(tool, fields):
    """Advertise scoped text edits, retaining explicit limits from legacy repairs."""
    result = copy.deepcopy(tool)
    result['function']['parameters']['properties']['patch'].update(minItems=1, maxItems=len(fields), items={
        'oneOf': [{'type': 'object', 'properties': {
            'op': {'enum': ['add', 'replace']}, 'path': {'const': path},
            'value': {'type': 'string', **({'maxLength': field['maximumCharacters']}
                      if field.get('maximumCharacters') is not None else {})}},
            'required': ['op', 'path', 'value'], 'additionalProperties': False} for path, field in fields.items()]})
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
    'requirementAccounting': ACCOUNTING_SCHEMA,
    'objectiveOrder': {'type': 'array', 'uniqueItems': True, 'items': {'type': 'string', 'enum': ['source_balance', 'distribution', 'progression', 'preservation']},
        'description': 'Only directly supported numerical soft objectives, highest first. Map an explicit source preference for progression headroom to progression and trace it in requirementAccounting. source_balance minimizes differences of approved coverage pairs (not general safety or hypertrophy); distribution reduces concentration of sets; progression prefers supported load headroom; preservation minimizes changes to the CURRENT CANDIDATE (never means preserve user requirements). Safety, equipment, time and volume constraints are enforced separately, never encoded as preservation. Omit unsupported objectives and do not invent a numerical ranking for broad qualitative goals or prioritize mathematical symmetry over a source instruction against it.'},
    "executionRules": EXECUTION_RULES_SCHEMA,
    "requiredCoverage": {"type": "array", "maxItems": 30, "description": "Only explicit user-required movement patterns, muscle work or exercise slots. No invented balance rules. The source reviewer verifies extraction; exercise suitability is checked during execution review.", "items": {
        "type": "object", "properties": {
            "key": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$", "maxLength": 60},
            "description": {"type": "string", "minLength": 1, "maxLength": 300},
            "scope": {"enum": ["eachSession", "weekly"]},
        }, "required": ["key", "description", "scope"], "additionalProperties": False}},
    "exerciseRestrictions": {"type": "object",
        "description": "Encode all explicit exclusions and limited permissions. If only named movements within a family are allowed, exclude that family and list those source-backed movements as exceptions. Do not omit a restriction merely because it is phrased as a permission, or add unrelated exclusions.", "properties": {
        "excludeNameTerms": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1}},
        "exceptNameTerms": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1}},
    }, "required": ["excludeNameTerms", "exceptNameTerms"], "additionalProperties": False},
    "auditTargets": _TARGETS,
    "sessionsPerWeek": {"type": ["integer", "null"], "minimum": 1, "maximum": 21},
    "minimumRestDaysBetweenSessions": {"type": "integer", "minimum": 0, "maximum": 6,
        "description": "Only an explicitly requested minimum of full rest days between sessions, including the weekly wraparound."},
    "workingSetRIR": {"type": "object", "properties": {
        "minimum": {"type": "number", "minimum": 0, "maximum": 10},
        "maximum": {"type": "number", "minimum": 0, "maximum": 10}},
        "required": ["minimum", "maximum"], "additionalProperties": False,
        "description": "Only an explicit general/default working-set reps-in-reserve range. Do not union conditional or exercise-specific exceptions into a wider default. Preserve those qualifiers in the original source and qualified execution notes; omit this field if there is no general default. Used to flag history/prescription uncertainty; history does not prove current effort."},
    "notes": {"type": "string", "description": "Legacy field; ignored. Original user instructions are retained by the backend, not rewritten into notes."},
}, "required": ["auditTargets", "sessionsPerWeek"], "additionalProperties": False}

SET_WORKOUT_REQUIREMENTS_TOOL = {"type": "function", "function": {
    "name": "set_workout_requirements",
    "description": "After clarifying material ambiguity, extract the user's exact numerical targets, restrictions and requiredCoverage for explicitly requested movement patterns, muscle work or exercise slots. Extract explicit order, straight-set, ramp-up and rest constraints into executionRules; use source-backed requiredCoverage keys for execution roles. Each submission replaces the extraction: include all still-applicable fields, not only the latest answer. Omit unspecified muscle targets; zero is a prohibition. Preserve full restriction qualifiers. Original instructions and clarification answers remain authoritative without a rewritten recap. Python checks extraction against that source before showing CONFIRM REQUIREMENTS. Never lower targets to resolve conflicts or promote general training advice to a binding rule. For stale policy refresh, preserve extracted fields and add missing source-backed rules. For ambiguity or unsupported extraction, correct the extraction or ask and wait. Every new approved extraction needs confirmation.",
    "parameters": {**_REQUIREMENTS, "properties": {key: value for key, value in _REQUIREMENTS['properties'].items() if key != 'notes'}},
}}


def requirements_metadata_equivalent(previous, current):
    """Reuse candidate feedback across traceability/preference updates, never approval evidence."""
    ignored = {'requirementAccounting', 'notes'}
    return (bool(previous.get('requirements')) and bool(current.get('requirements'))
        and {key: value for key, value in previous['requirements'].items() if key not in ignored}
            == {key: value for key, value in current['requirements'].items() if key not in ignored}
        and previous.get('sourceMessages') is not None
        and previous['sourceMessages'] == current.get('sourceMessages')
        and previous.get('resolvedDecisions', {}) == current.get('resolvedDecisions', {})
        and previous.get('restrictionPolicy') == current.get('restrictionPolicy'))


def _accounting_refresh_preserves_approved_requirements(base, current):
    if not base or not current:
        return False
    ignored = {'requirementAccounting', 'notes'}
    previous_requirements = base.get('requirements', {})
    current_requirements = current.get('requirements', {})
    previous_accounting = previous_requirements.get('requirementAccounting') or []
    current_accounting = current_requirements.get('requirementAccounting') or []
    accounting_semantics = ('instruction', 'requirementPaths', 'priority', 'enforcement', 'relaxationDirection', 'relaxationRank')
    return ({key: value for key, value in previous_requirements.items() if key not in ignored}
            == {key: value for key, value in current_requirements.items() if key not in ignored}
        and ([tuple(item.get(key) for key in accounting_semantics) for item in previous_accounting]
                == [tuple(item.get(key) for key in accounting_semantics) for item in current_accounting]
             if previous_accounting else all(item.get('priority') == 'mandatory'
                and not item.get('relaxationDirection') for item in current_accounting))
        and base.get('sourceMessages') == current.get('sourceMessages')
        and base.get('resolvedDecisions', {}) == current.get('resolvedDecisions', {})
        and base.get('supportedMuscleTargets') == current.get('supportedMuscleTargets')
        and base.get('restrictionPolicy') == current.get('restrictionPolicy'))


def approved_requirement_base(messages):
    calls = {call.get('id') for message in messages for call in message.get('tool_calls', [])
             if call.get('function', {}).get('name') in ('set_workout_requirements', 'accept_workout_alternative')}
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get('tool_call_id') not in calls:
            continue
        try:
            result = json.loads(message.get('content', '{}'))
        except (ValueError, TypeError):
            continue
        if not isinstance(result, dict) or not result.get('sourceReview', {}).get('passed'):
            continue
        if result.get('accountingRefreshBaseId'):
            previous = approved_requirement_base(messages[:index])
            if (previous and previous.get('requirementsId') == result['accountingRefreshBaseId']
                    and requirements_approved(messages[:index], result)
                    and _accounting_refresh_preserves_approved_requirements(previous, result)):
                return result
        shown = next((i for i in range(index + 1, len(messages))
            if messages[i].get('canonicalRequirementsPreview') == result.get('requirementsId')
            and messages[i].get('content') == result.get('requirementsPreview')), None)
        if shown is not None and result.get('approvedAlternativeId'):
            proposal_id = result['approvedAlternativeId']
            displayed = next((i for i in range(index) if messages[i].get('canonicalAlternativePreview') == proposal_id), None)
            if displayed is not None and any(item.get('role') == 'user' and not item.get('imageAttachments')
                    and (item.get('content') or '').strip() == 'APPROVE ALTERNATIVE ' + proposal_id
                    for item in messages[displayed + 1:index]):
                return result
        if shown is not None and any(item.get('role') == 'user' and not item.get('imageAttachments')
                and (item.get('content') or '').strip() == REQUIREMENTS_CONFIRMATION for item in messages[shown + 1:]):
            return result
    return {}


def workout_requirements_tool(equipment, messages=None, *, accounting_only=None):
    from .plan_review import REQUIREMENTS_REVIEW_VERSION
    tool = copy.deepcopy(SET_WORKOUT_REQUIREMENTS_TOOL)
    tool['function']['parameters']['required'] = [*tool['function']['parameters']['required'], 'requirementAccounting']
    base = approved_requirement_base(messages or [])
    last_user = next(((message.get('content') or '').strip() for message in reversed(messages or []) if message.get('role') == 'user'), '')
    refresh_only = accounting_only if accounting_only is not None else last_user in ('/continue', REQUIREMENTS_CONFIRMATION, EXACT_GENERATION_CONFIRMATION)
    if base and refresh_only and (accounting_only is True or base.get('requirementsVersion') != REQUIREMENTS_VERSION
            or base.get('sourceReview', {}).get('version') != REQUIREMENTS_REVIEW_VERSION
            or not base['requirements'].get('requirementAccounting')):
        tool['function']['parameters'] = {'type': 'object', 'properties': {
            'baseRequirementsId': {'type': 'string', 'enum': [base['requirementsId']]},
            'requirementAccounting': ACCOUNTING_SCHEMA,
            'objectiveOrder': copy.deepcopy(_REQUIREMENTS['properties']['objectiveOrder'])},
            'required': ['baseRequirementsId', 'requirementAccounting'], 'additionalProperties': False}
        tool['function']['description'] = ('Refresh accounting for the existing approved requirements only. Python copies every approved constraint unchanged. '
            'Return baseRequirementsId, requirementAccounting and only source-backed objectiveOrder. Paths refer to the frozen requirements visible in state. '
            'Do not emit auditTargets, requiredCoverage, requirementsId or any prescription. Explicitly classify every original instruction and exception.')
        return tool
    from .planning_decisions import RECORD_PLANNING_DECISIONS_TOOL
    tool['function']['parameters']['properties']['planningDecisions'] = copy.deepcopy(
        RECORD_PLANNING_DECISIONS_TOOL['function']['parameters'])
    tool['function']['description'] += (' When choices and extraction are ready together, include planningDecisions '
        'with decisions/sourceReferences for one independent authorization and requirements review. '
        'Do not invent user authorization; unresolved ambiguity still requires asking the user.')
    supported = available_muscle_targets(equipment)
    for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets'):
        bounds = tool['function']['parameters']['properties']['auditTargets']['properties'][field]
        bounds['properties'] = {key: value for key, value in bounds['properties'].items() if key in supported}
    return tool


_WORK_SET_FIELDS = {"reps": {"type": "integer", "minimum": 1},
                    "weight": {"type": "number", "minimum": 0},
                    "additionalWeight": {"type": "number", "minimum": 0}}
_EFFORT_ACCEPTANCE_SCHEMA = {'type': 'object', 'properties': {
    'kind': {'type': 'string', 'enum': ['rir_range', 'technical_criteria'],
        'description': 'A plan-authored prescription criterion, not a user requirement. Use rir_range for a bounded numeric target or technical_criteria for concrete observable pass/stop cues.'},
    'minimumRIR': {'type': ['number', 'null'], 'minimum': 0, 'maximum': 10},
    'maximumRIR': {'type': ['number', 'null'], 'minimum': 0, 'maximum': 10},
    'acceptanceCriterion': {'type': ['string', 'null'], 'minLength': 12, 'maxLength': 240},
    'terminationCriterion': {'type': ['string', 'null'], 'minLength': 12, 'maxLength': 240}},
    'required': ['kind'],
    'additionalProperties': False}

_EXERCISE = {"type": "object", "properties": {
    'effortAcceptance': {**copy.deepcopy(_EFFORT_ACCEPTANCE_SCHEMA),
        'description': ('Required when no approved general workingSetRIR exists. Choose either a plan-authored 0–10 RIR range (minimum <= maximum), '
            'or technical_criteria with a concrete observable acceptance criterion AND a concrete movement-specific stop criterion. '
            'This is a prescription choice, not a claim about what the user required. When approved workingSetRIR exists, omit this field; Python supplies its exact range.')},
    'progressionPlan': copy.deepcopy(PROGRESSION_PLAN_SCHEMA),
    'progressionMethod': {'enum': list(_PROGRESSION_NOTES),
        'description': 'Source-compatible progression policy. doubleProgression is reps then selectable load; duration is timed progression. reps increases reps at the SAME configuration and stops at the ceiling: it does NOT define a harder configuration. If the source requires a next leverage/ROM/assistance/variant step, use a qualified progressionPlan with sourceDefined. Legacy drafts without a plan must put the complete advancement criterion, next configuration and stop rule in notes. A qualified progressionPlan is rendered by Python, including for sourceDefined; do not duplicate it in notes. Without a plan, sourceDefined remains legacy local guidance. Preserve explicit user policy.'},
    "allocationBounds": {"type": "object", "properties": {
        "minimum": {"type": "integer", "minimum": 1, "maximum": 20},
        "maximum": {"type": "integer", "minimum": 1, "maximum": 20}},
        "required": ["minimum", "maximum"], "additionalProperties": False,
        "description": "Python derives these bounds from approved workSets execution rules; model suggestions and omission do not lock counts. workSetTemplate repeats unchanged as counts vary; exact targetSetPrescriptions remain locked. Never widen an explicit user limit."},
    "satisfiesCoverage": {"type": "array", "uniqueItems": True, "items": {"type": "string"}, "description": "ALL applicable approved requiredCoverage keys this occurrence satisfies, according to their source-backed descriptions. Include every applicable role so pattern totals are complete. The independent reviewer verifies accuracy and completeness against the actual movement; assignment alone is not proof."},
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
    "setupSeconds": {"type": "integer", "minimum": 0, "maximum": 1800,
        "description": "Estimated setup time before this exercise, separate from prescribed rest. Itemize each transition in time-limited plans, including plate/rack/bench/attachment changes. Zero needs a genuinely unchanged or pre-staged setup. This is an estimate, not a measurement."},
    "repDurationSeconds": {"type": ["number", "null"], "exclusiveMinimum": 0,
        "description": "Total seconds per rep including concentric, eccentric and pauses. Default 3 when no tempo is specified. Must cover every explicit tempo instruction in notes; not just its eccentric phase. For timed/running work use null."},
    "placementNotes": {**_NOTES_SCHEMA, 'description':
        "Local technique/setup cues only, at most 500 characters. Python-generated progression and working-set effort guidance is appended separately and does not consume this local allowance; use placementNotesLimits when supplied. Do not prescribe separate calibration trials, trial counts, starting loads, load changes, progression triggers, next variants, or repeat structured loads, counts, rests or generated guidance. Preserve valid instructions when shortening."},
    "workSetTemplate": {"type": "object", "properties": _WORK_SET_FIELDS,
        "required": ["reps"], "additionalProperties": False,
        "description": "Uniform target for every working set. Prefer this for the same reps and load across sets, allowing counts to vary within allocationBounds. For a known starting load, supply weight for WEIGHT or additionalWeight for BODY_WEIGHT using app load conventions. When no starting load is prescribed, omit it; Python enables the app's native requiresLoadCalibration mode. Never combine with targetSetPrescriptions."},
    "targetSetPrescriptions": {"type": "array", "maxItems": 20, "description": "Indexed work-set targets. Include the exercise's expected load field for fixed loads; omit it on every item to use app-native load calibration. Python owns requiresLoadCalibration.", "items": {
        "type": "object", "properties": {
            "workSetIndex": {"type": "integer", "minimum": 0}, **_WORK_SET_FIELDS,
        }, "required": ["workSetIndex", "reps"], "additionalProperties": False,
    }},
}, "required": ["definition_id", "numWorkSets", "minReps", "maxReps", "durationSeconds",
                 "restBetweenSetsSeconds", "restAfterExerciseSeconds", "superset",
                 "restAfterSupersetExerciseSeconds", "intraSetRestInSeconds", "generateWarmUpSets", "placementNotes"],
    "additionalProperties": False,
}
AUDIT_WORKOUT_PLAN_TOOL = {"type": "function", "function": {
    "name": "audit_workout_plan",
    "description": "Call only when creating or changing the structured draft; questions and explanations do not require another audit. Python audits volume, estimated duration and approved executionRules; a passing preview requires the independent execution review too. On failure, follow errors[].repair, change the draft and resubmit without changing requirements. If constraints conflict, explain and ask the user; never silently relax goals or loop on an unchanged failing draft. Export uses this exact draft after CONFIRM GENERATE. Superset members must be contiguous with equal sets; only the final member may have outer rest. Exact loads use app totals (dumbbell pair = combined total).",
    "parameters": {"type": "object", "properties": {
        "requirementsId": {"type": "string"}, "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "programGuidance": {"type": "string", "minLength": 1,
            "description": "Optional program-wide coaching or recovery note for the user to reference manually. This text is shown in the Python preview; it is not added to the exported workout package."},
        "workouts": {"type": "array", "minItems": 1, "maxItems": 30, "items": {
            "type": "object", "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 200},
                "description": {**_WORKOUT_DESCRIPTION_SCHEMA, 'description':
                    'Short training-focus label, not an exercise list. Example: Full body. Export cap 50 INCLUDES generated " Schedule: Monday." (18 characters; leaves 32), or " Schedule: Wednesday." (21; leaves 29). For other days reserve their full schedule suffix. Do not repeat the schedule here. Use descriptionCharacterLimits when supplied.'},
                "timesCompletedInAWeek": {"type": "integer", "minimum": 1, "maximum": 7},
                "trainingDays": {"type": "array", "uniqueItems": True, "minItems": 1, "maxItems": 7,
                    "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    "description": "Weekdays: Monday=0 through Sunday=6. Required when rest-day spacing is constrained; one day per weekly occurrence."},
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
    'description': 'Revise the saved currentDraft using requirementsId, baseDraftId and a targeted JSON Patch. '
                   'Follow repairTask.findingIndexes when present, otherwise the user-requested editTask; preserve untouched prescriptions. '
                   'When findingsAssessment is present, implement its complete coordinated repairPlan and all actionable groups in one atomic patch. Do not submit an allocation-only or notes-only subset. Preserve all interacting approved constraints. '
                   'Python reconstructs and validates the entire workout before any preview is approved. '
                   'Use [] only after an explicit retry or new evidence. Unchanged failures are cached.'}}


def coordinated_repair_tool(task=None):
    tool = copy.deepcopy(REPAIR_WORKOUT_PLAN_TOOL)
    task = task or {}
    indexes = sorted({index for group in task.get('findingsAssessment', {}).get('groups', [])
                      if group.get('disposition') == 'repair' for index in group.get('findingIndexes', [])})
    assessed_repair = isinstance(task.get('findingsAssessment'), dict)
    current_draft = task.get('currentDraft') or {}
    workouts = current_draft.get('workouts', [])
    workout_refs = [f'WORKOUT_{index}' for index in range(len(workouts))]
    exercise_ownership, exercise_identities, exercise_index = [], [], 0
    for workout_index, day in enumerate(workouts):
        references = []
        for exercise in day.get('exercises', []):
            reference = f'EXERCISE_{exercise_index}'
            references.append(reference)
            if exercise.get('definition_id'):
                exercise_identities.append(f"{reference}={exercise['definition_id']}")
            exercise_index += 1
        exercise_ownership.append(f'WORKOUT_{workout_index}: ' + ', '.join(references))
    exercise_refs = [f'EXERCISE_{index}' for index in range(exercise_index)]
    exercise_required = set(_EXERCISE['required'])
    # Allocation bounds are code-owned guardrails, even though drafts can omit
    # them. A coordinated repair must not widen or remove those limits.
    exercise_optional = sorted(set(_EXERCISE['properties']) - exercise_required - {'allocationBounds'})
    workout_fields = _DRAFT_SCHEMA['properties']['workouts']['items']['properties']
    workout_required = set(_DRAFT_SCHEMA['properties']['workouts']['items']['required'])
    workout_optional = sorted(set(workout_fields) - workout_required)
    field_properties = {key: copy.deepcopy(value) for key, value in _EXERCISE['properties'].items()
                        if key != 'allocationBounds' or key in exercise_optional}
    addition_exercise_schema = copy.deepcopy(_EXERCISE)
    addition_exercise_schema['properties'].pop('allocationBounds', None)
    edit_schema = {'type': 'object', 'properties': {
        'workoutUpdates': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'workoutRef': {'type': 'string', 'enum': workout_refs},
            'setFields': {'type': 'object', 'properties': {key: copy.deepcopy(workout_fields[key])
                for key in ('name', 'description', 'timesCompletedInAWeek', 'trainingDays')}, 'additionalProperties': False},
            'removeOptionalFields': {'type': 'array', 'uniqueItems': True,
                'items': {'type': 'string', 'enum': workout_optional}}},
            'required': ['workoutRef'], 'additionalProperties': False}},
        'exerciseUpdates': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'exerciseRef': {'type': 'string', 'enum': exercise_refs},
            'setFields': {'type': 'object', 'properties': field_properties, 'additionalProperties': False},
            'removeOptionalFields': {'type': 'array', 'uniqueItems': True,
                'items': {'type': 'string', 'enum': exercise_optional}}},
            'required': ['exerciseRef'], 'additionalProperties': False}},
        'exerciseAdditions': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'temporaryId': {'type': 'string', 'pattern': '^NEW_EXERCISE_[A-Za-z0-9_]+$'},
            'workoutRef': {'type': 'string', 'enum': workout_refs},
            'exercise': addition_exercise_schema},
            'required': ['temporaryId', 'workoutRef', 'exercise'], 'additionalProperties': False}},
        'exerciseRemovals': {'type': 'array', 'uniqueItems': True,
            'items': {'type': 'string', 'enum': exercise_refs}},
        'exerciseMoves': {'type': 'array', 'description': 'Cross-workout moves only. For ordering within the same workout, use exerciseOrders; do not submit a no-op move.', 'items': {'type': 'object', 'properties': {
            'exerciseRef': {'type': 'string', 'enum': exercise_refs},
            'workoutRef': {'type': 'string', 'enum': workout_refs}},
            'required': ['exerciseRef', 'workoutRef'], 'additionalProperties': False}},
        'workoutOrder': {'type': 'array', 'minItems': len(workout_refs), 'maxItems': len(workout_refs),
            'uniqueItems': True, 'items': {'type': 'string', 'enum': workout_refs}},
        'exerciseOrders': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'workoutRef': {'type': 'string', 'enum': workout_refs},
            'exerciseRefs': {'type': 'array', 'minItems': 1, 'uniqueItems': True, 'items': {'type': 'string'},
                'description': 'Optional relative-order constraint: list the exercise references that must appear in this order. Omitted current exercises retain their source-relative order; list every exercise only when a complete order is necessary.'},
        }, 'required': ['workoutRef', 'exerciseRefs'], 'additionalProperties': False}},
        'programGuidance': copy.deepcopy(_DRAFT_SCHEMA['properties']['programGuidance']),
    }, 'additionalProperties': False}
    # The description schema has a storage maximum, while the actual export cap
    # depends on the proposed trainingDays. Advertise the current allowance as
    # guidance, then validate against the post-edit schedule below.
    current_description_limits = ', '.join(
        f"WORKOUT_{index}={description_text_contract(day)['maximumCharacters']} characters"
        for index, day in enumerate(workouts))
    description_schema = edit_schema['properties']['workoutUpdates']['items']['properties']['setFields']['properties']['description']
    description_schema['description'] = (
        f"Short training-focus label. Current export allowances after schedule suffixes: {current_description_limits}. "
        "If this same edit changes trainingDays, Python recalculates the allowance for the proposed schedule; "
        "preserve that schedule and revise the description only as needed.")
    permitted_paths = task.get('permittedPatchPaths')
    if permitted_paths is not None:
        allowed_workout_fields, allowed_exercise_fields = {}, {}
        for path in permitted_paths:
            workout_match = re.fullmatch(r'/workouts/(\d+)/description', path)
            exercise_match = re.fullmatch(r'/workouts/(\d+)/exercises/(\d+)/placementNotes', path)
            if workout_match:
                allowed_workout_fields.setdefault(f'WORKOUT_{workout_match[1]}', set()).add('description')
            elif exercise_match:
                target = (int(exercise_match[1]), int(exercise_match[2]))
                flat_index = sum(len(day.get('exercises', [])) for day in workouts[:target[0]]) + target[1]
                if target[0] < len(workouts) and target[1] < len(workouts[target[0]].get('exercises', [])):
                    allowed_exercise_fields.setdefault(f'EXERCISE_{flat_index}', set()).add('placementNotes')
        metadata_fields = task.get('metadataFields') or {}
        scoped_properties = {}
        if allowed_workout_fields:
            base = edit_schema['properties']['workoutUpdates']['items']
            variants = []
            for reference, fields in sorted(allowed_workout_fields.items()):
                variant = copy.deepcopy(base)
                variant['properties']['workoutRef']['enum'] = [reference]
                variant['properties']['setFields']['properties'] = {
                    field: copy.deepcopy(workout_fields[field]) for field in sorted(fields)}
                variant['properties'].pop('removeOptionalFields', None)
                for path, contract in metadata_fields.items():
                    if path == f"/workouts/{reference.removeprefix('WORKOUT_')}/description" and contract.get('maximumCharacters') is not None:
                        variant['properties']['setFields']['properties']['description']['maxLength'] = contract['maximumCharacters']
                variants.append(variant)
            scoped_properties['workoutUpdates'] = {'type': 'array', 'items': {'oneOf': variants}}
        if allowed_exercise_fields:
            base = edit_schema['properties']['exerciseUpdates']['items']
            variants = []
            for reference, fields in sorted(allowed_exercise_fields.items()):
                variant = copy.deepcopy(base)
                variant['properties']['exerciseRef']['enum'] = [reference]
                variant['properties']['setFields']['properties'] = {
                    field: copy.deepcopy(field_properties[field]) for field in sorted(fields)}
                variant['properties'].pop('removeOptionalFields', None)
                for path, contract in metadata_fields.items():
                    match = re.fullmatch(r'/workouts/(\d+)/exercises/(\d+)/placementNotes', path)
                    if not match or contract.get('maximumCharacters') is None:
                        continue
                    target = (int(match[1]), int(match[2]))
                    flat_index = sum(len(day.get('exercises', [])) for day in workouts[:target[0]]) + target[1]
                    if reference == f'EXERCISE_{flat_index}':
                        variant['properties']['setFields']['properties']['placementNotes']['maxLength'] = contract['maximumCharacters']
                variants.append(variant)
            scoped_properties['exerciseUpdates'] = {'type': 'array', 'items': {'oneOf': variants}}
        edit_schema['properties'] = scoped_properties
    parameters = {'type': 'object', 'properties': {
        'requirementsId': {'type': 'string'},
        'baseDraftId': copy.deepcopy(_PATCH_SCHEMA['properties']['baseDraftId']),
        'edits': edit_schema,
    }, 'required': ['requirementsId', 'baseDraftId', 'edits'], 'additionalProperties': False}
    if assessed_repair:
        parameters['properties']['addressedFindingIndexes'] = {
            'type': 'array', 'items': {'type': 'integer', 'enum': indexes},
            'minItems': len(indexes), 'maxItems': len(indexes), 'uniqueItems': True,
            'description': 'List every actionable finding index from the current repairTask exactly once.'}
        parameters['required'].append('addressedFindingIndexes')
    has_rejected_proposal = _rejected_coordinated_edits(
        task, task.get('requirementsId'), task.get('baseDraftId')) is not None
    if has_rejected_proposal:
        parameters['properties']['replaceRejectedRepair'] = {
            'type': 'boolean',
            'description': 'Set true only when these edits are a complete replacement for the saved rejected proposal. By default, edits amend that proposal.'}
    tool['function']['parameters'] = parameters
    tool['function']['description'] = (
        (f'Revise the complete assessed candidate using its exact current identifiers and addressedFindingIndexes={indexes}. ' if assessed_repair
         else 'Revise the saved currentDraft using its exact current identifiers. ')
        + 'Use edits with stable WORKOUT_n and EXERCISE_n references from currentDraft; do not submit RFC JSON Patch, array indexes, or replacement workout arrays. '
        + ('Current candidate reference map: ' + '; '.join(exercise_ownership) + '. ' if workouts else '')
        + ('Candidate movement identities: ' + ', '.join(exercise_identities) + '. ' if exercise_identities else '')
        + ('Correct only the listed metadataFields using their stable references and permittedPatchPaths. Preserve structured exercise fields and all other content. Python replays any saved rejected proposal internally, then applies these text edits and validates the complete draft. '
           if permitted_paths is not None else
           'Keep placementNotes to at most 500 characters of local technique/setup cues. Python renders progression and working-set effort guidance. Load calibration is enabled by code from history and exercise type, not through repair fields. Do not repeat generated guidance in placementNotes. Change only typed source fields. Use removeOptionalFields only for an optional field that must be deleted. Replace a movement by updating its existing exerciseRef definition_id; add a movement with a unique NEW_EXERCISE_n temporaryId, target workoutRef, and complete source exercise fields; remove it by exerciseRef. Use exerciseMoves only to move an existing movement to a different workout; use exerciseOrders to reorder within a workout. '
           'For exercise order, send a non-empty relative-order sequence for each affected workout; omitted existing exercises retain their source-relative order. Complete lists are also allowed. Workout order remains a complete list. Use edits.programGuidance for one program-wide note shown as a manual preview reference; it is not exported into the workout package. Python compiles edits to an atomic patch. ')
        + ('checks every assessed repair group, then ' if assessed_repair else '')
        + 'runs the complete audit and review.')
    tool['function']['description'] += (' Shared repair-capability contract: '
        + json.dumps(repair_capability_contract(), separators=(',', ':')))
    if has_rejected_proposal:
        tool['function']['description'] += (
            ' A rejected typed proposal is retained and amended by default. Set replaceRejectedRepair=true only when this submission is the complete replacement proposal; '
            'the prior proposal remains in the receipt history, and the replacement must still address every actionable finding.')
    return tool


def _rejected_coordinated_edits(task, requirements_id, base_draft_id):
    receipt = (task or {}).get('rejectedCoordinatedRepair')
    if not isinstance(receipt, dict) or receipt.get('status', 'rejected_before_materialization') != 'rejected_before_materialization':
        return None
    if (receipt.get('requirementsId') != requirements_id
            or receipt.get('baseDraftId') != base_draft_id
            or receipt.get('currentDraftId', base_draft_id) != base_draft_id
            or not isinstance(receipt.get('submittedEdits'), dict)):
        return None
    assessment = (task or {}).get('findingsAssessment') or {}
    if receipt.get('assessmentInputHash') != assessment.get('inputHash'):
        return None
    review_findings = (task or {}).get('reviewFindings')
    if receipt.get('assessmentHash') is not None:
        if assessment.get('assessmentHash') is not None:
            if receipt['assessmentHash'] != assessment['assessmentHash']:
                return None
        elif isinstance(review_findings, list) and assessment.get('inputHash'):
            from .review_assessment import assessment_hash
            if receipt['assessmentHash'] != assessment_hash({
                    'inputHash': assessment['inputHash'], 'findings': review_findings}):
                return None
    return copy.deepcopy(receipt['submittedEdits'])


def _compose_coordinated_edits(previous, correction):
    """Amend the last rejected typed proposal without reinterpreting stable references."""
    result = copy.deepcopy(previous)
    updates = (
        ('workoutUpdates', 'workoutRef', ('setFields', 'removeOptionalFields')),
        ('exerciseUpdates', 'exerciseRef', ('setFields', 'removeOptionalFields')),
    )
    for collection, identity_key, field_keys in updates:
        old_items = result.setdefault(collection, [])
        new_items = correction.get(collection, [])
        if not new_items:
            continue
        by_identity = {item[identity_key]: item for item in old_items}
        if len(by_identity) != len(old_items) or len({item[identity_key] for item in new_items}) != len(new_items):
            raise PlanningInputError('duplicate_coordinated_edit', 'The retained or correcting proposal repeats a stable reference.', f'/edits/{collection}',
                'Use one typed update per stable reference so the correction can be composed unambiguously.')
        for item in new_items:
            identity = item[identity_key]
            if identity not in by_identity:
                old_items.append(copy.deepcopy(item))
                by_identity[identity] = old_items[-1]
                continue
            target = by_identity[identity]
            for field in field_keys:
                if field not in item:
                    continue
                if field == 'setFields':
                    set_fields = target.setdefault(field, {})
                    removals = set(target.get('removeOptionalFields', []))
                    for name, value in item[field].items():
                        set_fields[name] = copy.deepcopy(value)
                        removals.discard(name)
                    target['removeOptionalFields'] = sorted(removals)
                else:
                    set_fields = target.setdefault('setFields', {})
                    removals = set(target.get(field, []))
                    for name in item[field]:
                        set_fields.pop(name, None)
                        removals.add(name)
                    target[field] = sorted(removals)
            if not target.get('setFields'):
                target.pop('setFields', None)
            if not target.get('removeOptionalFields'):
                target.pop('removeOptionalFields', None)

    keyed_collections = (
        ('exerciseAdditions', 'temporaryId'),
        ('exerciseMoves', 'exerciseRef'),
        ('exerciseOrders', 'workoutRef'),
    )
    for collection, identity_key in keyed_collections:
        old_items = result.setdefault(collection, [])
        new_items = correction.get(collection, [])
        if not new_items:
            continue
        if len({item[identity_key] for item in new_items}) != len(new_items):
            raise PlanningInputError('duplicate_coordinated_edit', 'The correcting proposal repeats a stable reference.', f'/edits/{collection}',
                'Use one typed operation per stable reference so the correction can be composed unambiguously.')
        positions = {item[identity_key]: index for index, item in enumerate(old_items)}
        for item in new_items:
            identity = item[identity_key]
            if identity in positions:
                old_items[positions[identity]] = copy.deepcopy(item)
            else:
                positions[identity] = len(old_items)
                old_items.append(copy.deepcopy(item))
    removals = result.setdefault('exerciseRemovals', [])
    for reference in correction.get('exerciseRemovals', []):
        if reference not in removals:
            removals.append(reference)
    if correction.get('workoutOrder') is not None:
        result['workoutOrder'] = copy.deepcopy(correction['workoutOrder'])
    if 'programGuidance' in correction:
        result['programGuidance'] = copy.deepcopy(correction['programGuidance'])
    return result


def _raise_coordinated_schema_errors(validation_errors, validation_schema, supplemental_errors=None):
    if not validation_errors:
        return

    def flatten(error):
        if error.validator == 'oneOf' and error.context:
            actual = error.instance if isinstance(error.instance, dict) else {}
            selected_index = next((index for index, branch in enumerate(error.schema.get('oneOf', []))
                if all(key not in actual or actual[key] in value_schema.get('enum', [actual[key]])
                    for key, value_schema in branch.get('properties', {}).items()
                    if isinstance(value_schema, dict) and 'enum' in value_schema)), None)
            if selected_index is None:
                yield error
                return
            matching = [nested for nested in error.context
                if (list(nested.schema_path)[0] == selected_index
                    or ('oneOf' in nested.absolute_schema_path and list(nested.absolute_schema_path)[
                        list(nested.absolute_schema_path).index('oneOf') + 1] == selected_index))]
            for nested in matching:
                yield from flatten(nested)
        else:
            yield error

    expanded, seen = [], set()
    for validation_error in validation_errors:
        for nested in flatten(validation_error):
            key = (tuple(nested.absolute_path), nested.validator, nested.message)
            if key not in seen:
                seen.add(key)
                expanded.append(nested)
    expanded.sort(key=lambda item: (tuple(str(part) for part in item.absolute_path), item.validator or '', item.message))
    first = expanded[0] if expanded else validation_errors[0]
    first.validation_errors = expanded or validation_errors
    first.validation_schema = validation_schema
    first.supplemental_errors = supplemental_errors or []
    raise first


def _exercise_reference_inventory(edits, current_draft, *, include_moves=False):
    """Return post-edit workout membership from valid stable references only."""
    inventory = {f'WORKOUT_{index}': [] for index in range(len(current_draft.get('workouts', [])))}
    exercise_owner = {}
    exercise_index = 0
    for workout_index, day in enumerate(current_draft.get('workouts', [])):
        workout_ref = f'WORKOUT_{workout_index}'
        for _ in day.get('exercises', []):
            exercise_ref = f'EXERCISE_{exercise_index}'
            inventory[workout_ref].append(exercise_ref)
            exercise_owner[exercise_ref] = workout_ref
            exercise_index += 1

    edits = edits if isinstance(edits, dict) else {}
    removals = edits.get('exerciseRemovals', [])
    for reference in removals if isinstance(removals, list) else []:
        owner = exercise_owner.pop(reference, None) if isinstance(reference, str) else None
        if owner is not None:
            inventory[owner].remove(reference)

    additions = edits.get('exerciseAdditions', [])
    for addition in additions if isinstance(additions, list) else []:
        if not isinstance(addition, dict):
            continue
        reference, owner = addition.get('temporaryId'), addition.get('workoutRef')
        if (isinstance(reference, str) and isinstance(owner, str)
                and owner in inventory and reference not in exercise_owner):
            inventory[owner].append(reference)
            exercise_owner[reference] = owner

    if include_moves:
        raw_moves = edits.get('exerciseMoves', [])
        moves = [move for move in raw_moves if isinstance(move, dict)] if isinstance(raw_moves, list) else []
        moved_counts = {}
        for move in moves:
            reference = move.get('exerciseRef')
            if isinstance(reference, str):
                moved_counts[reference] = moved_counts.get(reference, 0) + 1
        # A repeated move has no single post-edit owner. Leave it unresolved for
        # the compiler's existing duplicate-move error instead of guessing.
        for move in moves:
            reference, destination = move.get('exerciseRef'), move.get('workoutRef')
            source = exercise_owner.get(reference) if isinstance(reference, str) else None
            if (source is None or moved_counts.get(reference) != 1
                    or not isinstance(destination, str) or destination not in inventory
                    or source == destination):
                continue
            inventory[source].remove(reference)
            inventory[destination].append(reference)
            exercise_owner[reference] = destination
    return inventory


def _exercise_order_reference_errors(edits, current_draft):
    inventory = _exercise_reference_inventory(edits, current_draft, include_moves=True)
    source_inventory = _exercise_reference_inventory({}, current_draft)
    known_references = {reference for references in source_inventory.values() for reference in references}
    raw_moves = edits.get('exerciseMoves', []) if isinstance(edits, dict) else []
    moves = [move for move in raw_moves if isinstance(move, dict)] if isinstance(raw_moves, list) else []
    move_counts = {}
    for move in moves:
        reference = move.get('exerciseRef')
        if isinstance(reference, str):
            move_counts[reference] = move_counts.get(reference, 0) + 1
    ambiguous_moves = {reference for reference, count in move_counts.items() if count > 1}
    raw_orders = edits.get('exerciseOrders', []) if isinstance(edits, dict) else []
    explicit_ordered_workouts = {order.get('workoutRef') for order in raw_orders
        if isinstance(order, dict)} if isinstance(raw_orders, list) else set()
    source_owner = {reference: workout_ref for workout_ref, references in source_inventory.items()
        for reference in references}
    ambiguous_moves.update(move.get('exerciseRef') for move in moves
        if move.get('exerciseRef') in known_references
        and (not isinstance(move.get('workoutRef'), str)
            or move.get('workoutRef') not in inventory
            or (move.get('workoutRef') == source_owner.get(move.get('exerciseRef'))
                and move.get('workoutRef') not in explicit_ordered_workouts)))
    errors = []
    for index, order in enumerate(raw_orders if isinstance(raw_orders, list) else []):
        if not isinstance(order, dict):
            continue
        workout_ref, references = order.get('workoutRef'), order.get('exerciseRefs')
        if (not isinstance(workout_ref, str) or workout_ref not in inventory
                or not isinstance(references, list)
                or any(not isinstance(reference, str) for reference in references)):
            continue
        if set(references) & ambiguous_moves:
            continue
        offending = sorted(set(references) - set(inventory[workout_ref]))
        if not offending:
            continue
        available = inventory[workout_ref]
        errors.append({
            'code': 'unknown_exercise_order_reference',
            'path': f'/edits/exerciseOrders/{index}/exerciseRefs',
            'message': f'{workout_ref} order includes reference absent from that workout after the submitted removals, moves, and additions: {", ".join(offending)}.',
            'repair': (f'For {workout_ref}, use only the available references shown. To change workout ownership, '
                'submit an explicit exerciseMoves entry; omitted exercises keep their existing relative order.'),
            'workoutRef': workout_ref,
            'offendingReferences': offending,
            'availableReferences': copy.deepcopy(available),
        })
    return errors


def _stable_draft_references(draft):
    workout_refs = {f'WORKOUT_{index}': index for index in range(len(draft.get('workouts', [])))}
    exercise_refs = {}
    index = 0
    for workout_index, day in enumerate(draft.get('workouts', [])):
        for exercise_index, _ in enumerate(day.get('exercises', [])):
            exercise_refs[f'EXERCISE_{index}'] = (workout_index, exercise_index)
            index += 1
    return workout_refs, exercise_refs


def compile_coordinated_repair(arguments, task, current_draft, *, return_reference_map=False, proposal_context=None):
    """Compile stable source references into leaf-level RFC 6902 operations."""
    _reject_unresolved_repair_capability(task)
    if not isinstance(current_draft, dict) or not isinstance(current_draft.get('workouts'), list):
        raise PlanningInputError('stale_draft_patch', 'The coordinated repair has no current saved draft.', '/baseDraftId',
            'Refresh currentDraft and use its currentDraftId before submitting stable-reference edits.')
    if arguments.get('baseDraftId') != task.get('baseDraftId'):
        raise PlanningInputError('stale_draft_patch', 'The coordinated repair base is stale.', '/baseDraftId',
            'Use the exact currentDraftId shown in repairTask; do not reuse an older edit contract.')
    rejected_edits = _rejected_coordinated_edits(
        task, arguments.get('requirementsId'), arguments.get('baseDraftId'))
    if proposal_context is not None and rejected_edits is not None:
        proposal_context['submittedEdits'] = copy.deepcopy(rejected_edits)
    tool = coordinated_repair_tool({**task, 'currentDraft': current_draft})
    validation_schema = tool['function']['parameters']
    validation_errors = list(Draft7Validator(validation_schema).iter_errors(arguments))
    effective_arguments = copy.deepcopy(arguments)
    replace_rejected = effective_arguments.pop('replaceRejectedRepair', False)
    if replace_rejected and rejected_edits is None:
        raise PlanningInputError('no_rejected_coordinated_repair',
            'There is no matching rejected proposal to replace.', '/replaceRejectedRepair',
            'Amend the current typed edits, or use replacement only when repairTask contains a rejected proposal for this same requirements and draft revision.')
    diagnostic_arguments = effective_arguments
    if rejected_edits is not None and not replace_rejected and isinstance(effective_arguments.get('edits'), dict):
        try:
            diagnostic_arguments = copy.deepcopy(effective_arguments)
            diagnostic_arguments['edits'] = _compose_coordinated_edits(
                rejected_edits, diagnostic_arguments['edits'])
        except (PlanningInputError, TypeError, KeyError):
            diagnostic_arguments = effective_arguments
    if validation_errors:
        order_reference_errors = _exercise_order_reference_errors(
            diagnostic_arguments.get('edits'), current_draft)
        _raise_coordinated_schema_errors(validation_errors, validation_schema, order_reference_errors)

    if rejected_edits is not None and not replace_rejected:
        effective_arguments['edits'] = _compose_coordinated_edits(rejected_edits, effective_arguments['edits'])
    if proposal_context is not None:
        if replace_rejected:
            proposal_context['replacedSubmittedEdits'] = copy.deepcopy(rejected_edits)
        proposal_context['submittedEdits'] = copy.deepcopy(effective_arguments['edits'])
        proposal_context['proposalCompiled'] = True
    if rejected_edits is not None and not replace_rejected:
        validation_errors = list(Draft7Validator(validation_schema).iter_errors(effective_arguments))
        order_reference_errors = _exercise_order_reference_errors(effective_arguments.get('edits'), current_draft)
        _raise_coordinated_schema_errors(validation_errors, validation_schema, order_reference_errors)
    order_reference_errors = _exercise_order_reference_errors(effective_arguments.get('edits'), current_draft)
    if order_reference_errors:
        first = order_reference_errors[0]
        raise PlanningInputError(first['code'], first['message'], first['path'], first['repair'],
            errors=order_reference_errors)
    edits = effective_arguments['edits']
    if not any(edits.get(key) for key in ('workoutUpdates', 'exerciseUpdates', 'exerciseAdditions',
        'exerciseRemovals', 'exerciseMoves', 'workoutOrder', 'exerciseOrders', 'programGuidance')):
        raise PlanningInputError('empty_coordinated_edits', 'The coordinated repair contains no edits.', '/edits',
            'Submit a concrete typed field or structural change; an empty edit contract does not change the saved candidate.')
    if 'programGuidance' in edits and not edits['programGuidance'].strip():
        raise PlanningInputError('empty_program_guidance', 'Program guidance must contain user-facing text.', '/edits/programGuidance',
            'Provide a concrete program-wide note. Blank text cannot stand in for satisfying a guidance finding.')
    workout_refs, exercise_refs = _stable_draft_references(current_draft)
    workout_refs_by_position = [f'WORKOUT_{index}' for index in range(len(current_draft['workouts']))]
    initial_definition_by_ref = {
        reference: current_draft['workouts'][workout_index]['exercises'][exercise_index].get('definition_id')
        for reference, (workout_index, exercise_index) in exercise_refs.items()
    }
    initial_exercise_refs_by_workout = {reference: [] for reference in workout_refs}
    for exercise_ref, (workout_index, exercise_index) in exercise_refs.items():
        initial_exercise_refs_by_workout[f'WORKOUT_{workout_index}'].append((exercise_index, exercise_ref))
    initial_exercise_refs_by_workout = {
        reference: [exercise_ref for _, exercise_ref in sorted(items)]
        for reference, items in initial_exercise_refs_by_workout.items()
    }
    candidate = copy.deepcopy(current_draft)
    operations, operation_refs = [], []

    def emit(operation, refs):
        operations.append(operation)
        operation_refs.append(sorted(set(refs)))

    if 'programGuidance' in edits:
        operation = 'replace' if 'programGuidance' in candidate else 'add'
        emit({'op': operation, 'path': '/programGuidance', 'value': edits['programGuidance']}, [])
        candidate['programGuidance'] = edits['programGuidance']

    seen_workouts, seen_exercises, seen_new, removed = set(), set(), set(), set()
    for update in edits.get('workoutUpdates', []):
        reference = update['workoutRef']
        if reference in seen_workouts:
            raise PlanningInputError('duplicate_workout_edit', 'A workout may be updated only once per coordinated edit.', '/edits/workoutUpdates',
                'Combine all changes for the same WORKOUT_n into one entry.')
        seen_workouts.add(reference)
        workout_index = workout_refs[reference]
        day = candidate['workouts'][workout_index]
        path = f'/workouts/{workout_index}'
        set_fields = update.get('setFields', {})
        removals = update.get('removeOptionalFields', [])
        if not set_fields and not removals:
            raise PlanningInputError('empty_workout_edit', 'Workout updates need a field change or optional-field removal.', path,
                'Provide typed setFields or removeOptionalFields for this WORKOUT_n.')
        if set(set_fields) & set(removals):
            raise PlanningInputError('conflicting_workout_edit', 'A workout field cannot be set and removed in the same edit.', path,
                'Choose one operation for each workout field.')
        for field, value in set_fields.items():
            operation = 'replace' if field in day else 'add'
            emit({'op': operation, 'path': f'{path}/{field}', 'value': copy.deepcopy(value)}, [reference])
            day[field] = copy.deepcopy(value)
        for field in removals:
            if field not in day:
                raise PlanningInputError('missing_optional_workout_field', f'{field} is absent and cannot be removed.', f'{path}/{field}',
                    'Remove only an existing optional field; no-op removals do not count as repairs.')
            emit({'op': 'remove', 'path': f'{path}/{field}'}, [reference])
            day.pop(field)

    for update in edits.get('exerciseUpdates', []):
        reference = update['exerciseRef']
        if reference in seen_exercises or reference in removed:
            raise PlanningInputError('duplicate_exercise_edit', 'An exercise may be updated only once and cannot also be removed.', '/edits/exerciseUpdates',
                'Combine its field changes in one entry or choose removal.')
        seen_exercises.add(reference)
        workout_index, exercise_index = exercise_refs[reference]
        item = candidate['workouts'][workout_index]['exercises'][exercise_index]
        path = f'/workouts/{workout_index}/exercises/{exercise_index}'
        set_fields = update.get('setFields', {})
        removals = update.get('removeOptionalFields', [])
        if not set_fields and not removals:
            raise PlanningInputError('empty_exercise_edit', 'Exercise updates need a field change or optional-field removal.', path,
                'Provide typed setFields or removeOptionalFields for this EXERCISE_n.')
        if set(set_fields) & set(removals):
            raise PlanningInputError('conflicting_exercise_edit', 'An exercise field cannot be set and removed in the same edit.', path,
                'Choose one operation for each exercise field.')
        for field, value in set_fields.items():
            operation = 'replace' if field in item else 'add'
            emit({'op': operation, 'path': f'{path}/{field}', 'value': copy.deepcopy(value)}, [reference, f'WORKOUT_{workout_index}'])
            item[field] = copy.deepcopy(value)
        for field in removals:
            if field not in item:
                raise PlanningInputError('missing_optional_exercise_field', f'{field} is absent and cannot be removed.', f'{path}/{field}',
                    'Remove only an existing optional field; no-op removals do not count as repairs.')
            emit({'op': 'remove', 'path': f'{path}/{field}'}, [reference, f'WORKOUT_{workout_index}'])
            item.pop(field)

    for reference in edits.get('exerciseRemovals', []):
        if reference in removed or reference in seen_exercises:
            raise PlanningInputError('duplicate_exercise_removal', 'An exercise cannot be updated or removed more than once.', '/edits/exerciseRemovals',
                'Use one coordinated action for each EXERCISE_n.')
        removed.add(reference)

    additions = edits.get('exerciseAdditions', [])
    for addition in additions:
        reference = addition['temporaryId']
        if reference in seen_new or reference in exercise_refs or reference in workout_refs:
            raise PlanningInputError('duplicate_temporary_exercise_id', 'Temporary exercise IDs must be unique.', '/edits/exerciseAdditions',
                'Use a unique NEW_EXERCISE_n reference for every added occurrence.')
        seen_new.add(reference)
        target = addition['workoutRef']
        if target not in workout_refs:
            raise PlanningInputError('unknown_workout_reference', 'An added exercise must target a current workout.', '/edits/exerciseAdditions/workoutRef',
                'Use one of the current WORKOUT_n references; this edit contract does not add workouts.')

    # Apply exercise removals from highest original index to lowest so the
    # remaining field and workout indices retain their current source identity.
    removal_entries = sorted(((reference, *exercise_refs[reference]) for reference in removed),
                             key=lambda value: (value[1], value[2]), reverse=True)
    for reference, workout_index, exercise_index in removal_entries:
        emit({'op': 'remove', 'path': f'/workouts/{workout_index}/exercises/{exercise_index}'},
             [reference, f'WORKOUT_{workout_index}'])
        candidate['workouts'][workout_index]['exercises'].pop(exercise_index)

    for addition in additions:
        temporary_id = addition['temporaryId']
        workout_index = workout_refs[addition['workoutRef']]
        day = candidate['workouts'][workout_index]
        exercise_index = len(day['exercises'])
        base_path = f'/workouts/{workout_index}/exercises/-'
        emit({'op': 'add', 'path': base_path, 'value': {}},
             [temporary_id, addition['workoutRef']])
        day['exercises'].append({})
        for field, value in addition['exercise'].items():
            emit({'op': 'add', 'path': f'/workouts/{workout_index}/exercises/{exercise_index}/{field}',
                  'value': copy.deepcopy(value)}, [temporary_id, addition['workoutRef']])
            day['exercises'][exercise_index][field] = copy.deepcopy(value)

    exercise_ids_by_workout = _exercise_reference_inventory(edits, current_draft)
    moved_exercises = set()
    explicitly_ordered_workouts = {item['workoutRef'] for item in edits.get('exerciseOrders', [])}
    for move in edits.get('exerciseMoves', []):
        reference = move['exerciseRef']
        destination_ref = move['workoutRef']
        if reference in moved_exercises:
            raise PlanningInputError('duplicate_exercise_move', 'An exercise may be moved only once per coordinated edit.', '/edits/exerciseMoves',
                'Include one destination workout for each EXERCISE_n. Do not move the same exercise repeatedly.')
        if reference in removed:
            raise PlanningInputError('move_removed_exercise', 'A removed exercise cannot also be moved.', '/edits/exerciseMoves',
                'Choose either removal or movement for each EXERCISE_n.')
        source_ref = next((workout_ref for workout_ref, refs in exercise_ids_by_workout.items()
                           if reference in refs), None)
        if source_ref is None:
            raise PlanningInputError('unknown_exercise_move', 'The moved exercise is not present in the current candidate.', '/edits/exerciseMoves',
                'Move only a current EXERCISE_n that has not been removed.')
        moved_exercises.add(reference)
        if source_ref == destination_ref:
            if destination_ref in explicitly_ordered_workouts:
                continue
            raise PlanningInputError('same_workout_exercise_move', 'An exercise move must change its workout.', '/edits/exerciseMoves',
                'Use exerciseOrders to change order within the same workout.')
        source_workout_index = workout_refs[source_ref]
        destination_workout_index = workout_refs[destination_ref]
        source_list = exercise_ids_by_workout[source_ref]
        source_index = source_list.index(reference)
        emit({'op': 'move', 'from': f'/workouts/{source_workout_index}/exercises/{source_index}',
              'path': f'/workouts/{destination_workout_index}/exercises/-'},
             [reference, source_ref, destination_ref])
        item = candidate['workouts'][source_workout_index]['exercises'].pop(source_index)
        candidate['workouts'][destination_workout_index]['exercises'].append(item)
        source_list.pop(source_index)
        exercise_ids_by_workout[destination_ref].append(reference)

    seen_orders = set()
    for order in edits.get('exerciseOrders', []):
        workout_ref = order['workoutRef']
        if workout_ref in seen_orders:
            raise PlanningInputError('duplicate_exercise_order', 'Each workout may have at most one exercise order.', '/edits/exerciseOrders',
                'Combine the relative ordering constraints into one sequence per workout.')
        seen_orders.add(workout_ref)
        relative_order = order['exerciseRefs']
        current = exercise_ids_by_workout[workout_ref]
        if not relative_order:
            raise PlanningInputError('empty_exercise_order', 'An exercise order must contain at least one reference.', '/edits/exerciseOrders',
                'Omit exerciseOrders for an unchanged workout, or list the relative sequence that must be preserved.')
        if len(relative_order) != len(set(relative_order)):
            raise PlanningInputError('duplicate_exercise_order_reference', 'An exercise order cannot repeat a reference.', '/edits/exerciseOrders',
                'List each explicitly ordered exercise once.')
        unknown = set(relative_order) - set(current)
        if unknown:
            raise PlanningInputError('unknown_exercise_order_reference', 'An exercise order includes a reference absent from the post-edit workout.', '/edits/exerciseOrders',
                'Use current EXERCISE_n or added NEW_EXERCISE_n references in that workout after removals and moves.')

        # Treat the model's list as precedence constraints, not an inventory
        # reconstruction. Keep omitted exercises in source-relative order and
        # use original position as the stable tie-break among available nodes.
        edges = {reference: set() for reference in current}
        indegree = {reference: 0 for reference in current}
        for before, after in zip(relative_order, relative_order[1:]):
            if after not in edges[before]:
                edges[before].add(after)
                indegree[after] += 1
        omitted = [reference for reference in current if reference not in relative_order]
        for before, after in zip(omitted, omitted[1:]):
            if after not in edges[before]:
                edges[before].add(after)
                indegree[after] += 1
        source_rank = {reference: index for index, reference in enumerate(current)}
        ready = [(source_rank[reference], reference) for reference in current if indegree[reference] == 0]
        heapq.heapify(ready)
        desired = []
        while ready:
            _, reference = heapq.heappop(ready)
            desired.append(reference)
            for following in edges[reference]:
                indegree[following] -= 1
                if indegree[following] == 0:
                    heapq.heappush(ready, (source_rank[following], following))
        if len(desired) != len(current):
            raise PlanningInputError('cyclic_exercise_order', 'The requested exercise-order constraints conflict.', '/edits/exerciseOrders',
                'Remove contradictory order entries and submit one consistent relative sequence per workout.')
        workout_index = workout_refs[workout_ref]
        changed_order_refs = {reference for index, reference in enumerate(desired)
                              if current[index] != reference}
        for target_index, reference in enumerate(desired):
            source_index = current.index(reference)
            if source_index == target_index:
                continue
            emit({'op': 'move', 'from': f'/workouts/{workout_index}/exercises/{source_index}',
                  'path': f'/workouts/{workout_index}/exercises/{target_index}'},
                 changed_order_refs | {workout_ref})
            item = candidate['workouts'][workout_index]['exercises'].pop(source_index)
            candidate['workouts'][workout_index]['exercises'].insert(target_index, item)
            current.insert(target_index, current.pop(source_index))

    workout_order = edits.get('workoutOrder')
    if workout_order is not None:
        current_order = workout_refs_by_position
        if len(workout_order) != len(set(workout_order)) or set(workout_order) != set(current_order):
            raise PlanningInputError('incomplete_workout_order', 'Workout order must list every current workout exactly once.', '/edits/workoutOrder',
                'Include every current WORKOUT_n exactly once; this edit contract does not add or remove workouts.')
        changed_order_refs = {reference for index, reference in enumerate(workout_order)
                              if current_order[index] != reference}
        for target_index, reference in enumerate(workout_order):
            source_index = current_order.index(reference)
            if source_index == target_index:
                continue
            emit({'op': 'move', 'from': f'/workouts/{source_index}', 'path': f'/workouts/{target_index}'},
                 changed_order_refs)
            day = candidate['workouts'].pop(source_index)
            candidate['workouts'].insert(target_index, day)
            current_order.insert(target_index, current_order.pop(source_index))

    if not operations:
        raise PlanningInputError('empty_coordinated_edits', 'The coordinated edit produced no patch operations.', '/edits',
            'Submit a concrete changed field or ordering update; no-op edits do not address findings.')
    compiled = {key: copy.deepcopy(effective_arguments[key]) for key in ('requirementsId', 'baseDraftId')}
    if 'addressedFindingIndexes' in effective_arguments:
        compiled['addressedFindingIndexes'] = copy.deepcopy(effective_arguments['addressedFindingIndexes'])
    compiled['patch'] = operations
    if not return_reference_map:
        return compiled, operation_refs
    reference_map = {
        'workoutRefsByPosition': list(workout_refs_by_position),
        'exerciseRefsByWorkout': copy.deepcopy(exercise_ids_by_workout),
        'initialDefinitionByExerciseRef': initial_definition_by_ref,
        'initialExerciseRefsByWorkout': initial_exercise_refs_by_workout,
        'composedEdits': copy.deepcopy(effective_arguments['edits']),
    }
    return compiled, operation_refs, reference_map

GET_WORKOUT_DRAFT_TOOL = {'type': 'function', 'function': {
    'name': 'get_workout_draft',
    'description': 'Read omitted session details from the saved draft before changing them. Returns exact fields and original patch paths, without mutating the draft or requiring another audit.',
    'parameters': {'type': 'object', 'properties': {
        'baseDraftId': {'type': 'string', 'pattern': '^REVISION_[0-9]+$'},
        'workoutReferences': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
            'items': {'type': 'string', 'pattern': '^WORKOUT_[0-9]+$'}}},
        'required': ['baseDraftId', 'workoutReferences'], 'additionalProperties': False}}}


PREPARE_WORKOUT_SESSION_TOOL = {'type': 'function', 'function': {
    'name': 'prepare_workout_session',
    'description': 'Commit the exact movements for the next session, not a list of alternatives. Python returns current metadata and retrieves missing history before session submission. This does not approve or export a workout.',
    'parameters': {'type': 'object', 'properties': {
        'requirementsId': {'type': 'string'},
        'baseDraftId': {'type': ['string', 'null'], 'pattern': '^REVISION_[0-9]+$'},
        'definition_ids': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'uniqueItems': True,
                           'items': {'type': 'string', 'pattern': '^LIBRARY_[0-9]+$'}}},
        'required': ['requirementsId', 'baseDraftId', 'definition_ids'], 'additionalProperties': False}}}


def prepare_workout_session(arguments, messages, equipment):
    from .exercise_library_tools import get_exercise_candidates
    validate(arguments, PREPARE_WORKOUT_SESSION_TOOL['function']['parameters'])
    require_approved_requirements(messages)
    _, requirements = _latest_result(messages, 'set_workout_requirements')
    _, revision = latest_draft_submission(messages, equipment)
    if arguments['requirementsId'] != requirements['requirementsId'] or arguments['baseDraftId'] != revision:
        raise ValueError('Session preparation is stale; use the current requirementsId and currentDraftId (null before the first draft).')
    index, prepared = _latest_result(messages, 'prepare_workout_session')
    new_instruction = any(message.get('role') == 'user' and message.get('content', '').strip()
                          not in ('/continue', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE') for message in messages[index + 1:])
    if (prepared.get('requirementsId') == arguments['requirementsId'] and prepared.get('baseDraftId') == revision
            and prepared.get('libraryFingerprint') == library_fingerprint(equipment) and not new_instruction):
        raise PlanningInputError('session_selection_locked', 'The next-session selection is already committed.', '/',
            'Use the prepared metadata and history to submit the session. Repair any unsuitable choice through the normal audit before starting another selection.')
    return {**get_exercise_candidates({'definition_ids': arguments['definition_ids']}, equipment, messages),
            'requirementsId': arguments['requirementsId'], 'baseDraftId': revision,
            'definition_ids': arguments['definition_ids'], 'instruction': 'Use these movements for the next session. Python retrieves missing history; then submit the session to audit_workout_plan. Resolve audit findings through patches after submission.'}


def get_workout_draft(arguments, messages, equipment):
    validate(arguments, GET_WORKOUT_DRAFT_TOOL['function']['parameters'])
    require_approved_requirements(messages)
    draft, revision = latest_draft_submission(messages, equipment)
    if draft is None or arguments['baseDraftId'] != revision:
        raise ValueError('Draft reference is stale; use currentDraftId from the current planning state.')
    selected = {}
    for reference in arguments['workoutReferences']:
        index = int(reference.removeprefix('WORKOUT_'))
        if index >= len(draft['workouts']):
            raise ValueError(f'Unknown workout reference: {reference}')
        selected[reference] = copy.deepcopy(draft['workouts'][index])
    references = {item['definition_id'] for day in selected.values() for item in day['exercises']}
    definitions = {f'LIBRARY_{i}': definition['name'] for i, definition in enumerate(sorted(
        equipment.get('exerciseDefinitions', []), key=lambda item: item['id'])) if f'LIBRARY_{i}' in references}
    return {'baseDraftId': revision, 'workouts': selected, 'exerciseNames': definitions}


def _pointer_value(value, path):
    parts = [part.replace('~1', '/').replace('~0', '~') for part in path.lstrip('/').split('/') if part]
    for part in parts:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _operation_repair_dimensions(operation, current_draft):
    path = operation.get('path', '')
    if operation.get('op') == 'move':
        source = operation.get('from', '')
        if source == path:
            return set()
        # Moving list members is an ordering change; shifted element indexes do
        # not count as prescription, selection, or guidance changes.
        source_exercise = re.match(r'^/workouts/(\d+)/exercises/\d+$', source)
        destination_exercise = re.match(r'^/workouts/(\d+)/exercises/(?:\d+|-)$', path)
        exercise_move = bool(source_exercise and destination_exercise)
        workout_move = re.fullmatch(r'/workouts/\d+', source) and re.fullmatch(r'/workouts/\d+', path)
        if exercise_move:
            dimensions = {'ordering'}
            if source_exercise[1] != destination_exercise[1]:
                dimensions.update({'exercise_selection', 'session_timing'})
            return dimensions
        return {'ordering'} if workout_move else set()
    if operation.get('op') in ('test', 'copy'):
        return set()
    parts = [part.replace('~1', '/').replace('~0', '~') for part in path.lstrip('/').split('/') if part]
    if not parts:
        return set()
    field = parts[-1]
    if len(parts) >= 4 and parts[-2] == 'exercises' and (field.isdigit() or field == '-'):
        # Whole exercise or list replacement is selection-only here. It cannot
        # claim every field whose array index shifted as an actual correction.
        return {'exercise_selection'}
    if field.isdigit() or field == '-':
        return set()
    if 'progressionPlan' in parts:
        return {'progression'}
    if 'effortAcceptance' in parts:
        return _repair_field_dimensions('effortAcceptance')
    if 'workSetTemplate' in parts or 'targetSetPrescriptions' in parts:
        return {'prescription', 'session_timing'}
    if 'trainingDays' in parts:
        return _repair_field_dimensions('trainingDays')
    return _repair_field_dimensions(field)


def _structured_repair_coverage(arguments, task, current_draft):
    _reject_unresolved_repair_capability(task)
    assessment = task.get('findingsAssessment') or {}
    groups = [group for group in assessment.get('groups', []) if group.get('disposition') == 'repair']
    expected = sorted({index for group in groups for index in group.get('findingIndexes', [])})
    addressed = arguments.get('addressedFindingIndexes')
    if not isinstance(addressed, list) or sorted(addressed) != expected:
        raise PlanningInputError('incomplete_repair_groups', 'The repair call must explicitly address every actionable assessed finding exactly once.',
            '/addressedFindingIndexes', 'Use the exact actionable finding indexes from repairTask. Apply matching structured changes to all actionable groups in one patch.')

    findings = task.get('reviewFindings', [])
    operations = arguments.get('patch', [])
    operation_source_refs = task.get('_compiledRepairOperationRefs')
    workout_refs, exercise_refs = _stable_draft_references(current_draft or {})
    exercise_ref_by_position = {position: reference for reference, position in exercise_refs.items()}
    exercise_ref_by_flat_index = {index: reference for index, reference in enumerate(exercise_refs)}

    def finding_source_refs(finding):
        source_refs, source_workout_refs = set(), set()
        for path in [finding.get('draftPath'), *(finding.get('evidencePaths') or [])]:
            match = re.match(r'^/(?:draft/)?workouts/(\d+)/exercises/(\d+)(?:/|$)', path or '')
            if match:
                position = tuple(map(int, match.groups()))
                reference = exercise_ref_by_position.get(position)
                if reference:
                    source_refs.add(reference)
                    source_workout_refs.add(f'WORKOUT_{position[0]}')
                continue
            match = re.match(r'^/(?:draft/)?exercises/(\d+)(?:/|$)', path or '')
            if match:
                reference = exercise_ref_by_flat_index.get(int(match[1]))
                if reference:
                    source_refs.add(reference)
                    source_workout_refs.add(f'WORKOUT_{exercise_refs[reference][0]}')
                continue
            match = re.match(r'^/(?:draft/)?workouts/(\d+)(?:/|$)', path or '')
            if match:
                reference = f'WORKOUT_{int(match[1])}'
                if reference in workout_refs:
                    source_refs.add(reference)
                    source_workout_refs.add(reference)
        return source_refs, source_workout_refs

    observed = []
    candidate = copy.deepcopy(current_draft) if current_draft else None
    from .json_patching import apply_json_patch
    for operation in operations:
        before = copy.deepcopy(candidate)
        dimensions = _operation_repair_dimensions(operation, candidate)
        if candidate is not None:
            candidate = apply_json_patch(candidate, [operation])
            # A leaf path only counts if the operation changed its value.
            if operation.get('op') in ('add', 'remove', 'replace') and operation.get('path'):
                try:
                    if before == candidate:
                        dimensions = set()
                except Exception:
                    dimensions = set()
        observed.append((operation, dimensions))

    uncovered = []
    for group in groups:
        indexes = group.get('findingIndexes', [])
        dimensions = set(group.get('repairDimensions', []))
        relevant_paths = []
        relevant_source_refs = set()
        relevant_workout_refs = set()
        for index in indexes:
            if not isinstance(index, int) or index >= len(findings):
                continue
            source_refs, workout_refs_for_finding = finding_source_refs(findings[index])
            relevant_source_refs.update(source_refs)
            relevant_workout_refs.update(workout_refs_for_finding)
            draft_path = findings[index].get('draftPath')
            match = re.match(r'^(/workouts/\d+/exercises/\d+)(?:/|$)', draft_path or '')
            if match:
                relevant_paths.append(match.group(1))
                continue
            match = re.match(r'^(/workouts/\d+)(?:/|$)', draft_path or '')
            if match:
                relevant_paths.append(match.group(1))
        source_definition_ids = {
            current_draft['workouts'][day_index]['exercises'][exercise_index].get('definition_id')
            for reference in relevant_source_refs
            if reference.startswith('EXERCISE_') and reference in exercise_refs
            for day_index, exercise_index in [exercise_refs[reference]]
            if current_draft and day_index < len(current_draft.get('workouts', []))
            and exercise_index < len(current_draft['workouts'][day_index].get('exercises', []))
        }
        matching = set()
        for operation_index, (operation, changed_dimensions) in enumerate(observed):
            # Program guidance is a plan-wide owner, so it may address a
            # finding whose evidence cites one or more workouts without
            # touching those workout occurrence references itself.
            global_owner_change = (operation.get('op') in ('add', 'replace')
                and operation.get('path') == '/programGuidance'
                and 'program_guidance' in changed_dimensions)
            if global_owner_change:
                matching.update(changed_dimensions & dimensions)
                continue
            if operation_source_refs is not None and relevant_source_refs:
                touched_refs = set(operation_source_refs[operation_index])
                workout_scope_dimensions = {'exercise_selection', 'superset'}
                exact_source_match = bool(touched_refs & relevant_source_refs)
                workout_level_finding = not any(reference.startswith('EXERCISE_')
                    for reference in relevant_source_refs)
                path = operation.get('path', '')
                structural_exercise_operation = (operation.get('op') in ('add', 'remove', 'replace')
                    and re.fullmatch(r'/workouts/\d+/exercises/(?:\d+|-)', path))
                same_source_definition_occurrence = ('exercise_selection' in (changed_dimensions & dimensions)
                    and any(reference.startswith('EXERCISE_') and reference in exercise_refs
                        and current_draft['workouts'][exercise_refs[reference][0]]['exercises'][exercise_refs[reference][1]].get('definition_id')
                            in source_definition_ids
                        for reference in touched_refs))
                added_exercise_field_operation = (operation.get('op') == 'add'
                    and any(reference.startswith('NEW_EXERCISE_') for reference in touched_refs)
                    and re.fullmatch(r'/workouts/\d+/exercises/\d+/[^/]+', path))
                workout_scoped_alternative = (bool(changed_dimensions & dimensions & workout_scope_dimensions)
                    and bool(touched_refs & relevant_workout_refs)
                    and bool(structural_exercise_operation or added_exercise_field_operation))
                added_exercise_coverage = (bool(changed_dimensions & dimensions & {'coverage'})
                    and bool(touched_refs & relevant_workout_refs)
                    and added_exercise_field_operation)
                cross_session_schedule = (workout_level_finding
                    and 'ordering' in (changed_dimensions & dimensions)
                    and operation.get('path', '').endswith('/trainingDays')
                    and bool(touched_refs & {reference for reference in workout_refs if reference.startswith('WORKOUT_')}))
                same_workout_order = (workout_level_finding
                    and 'ordering' in (changed_dimensions & dimensions)
                    and bool(touched_refs & relevant_workout_refs))
                if exact_source_match:
                    matching.update(changed_dimensions & dimensions)
                elif same_source_definition_occurrence:
                    matching.add('exercise_selection')
                elif added_exercise_coverage:
                    matching.add('coverage')
                elif workout_scoped_alternative:
                    matching.update(changed_dimensions & dimensions & workout_scope_dimensions)
                elif cross_session_schedule:
                    matching.add('ordering')
                elif same_workout_order:
                    matching.add('ordering')
                else:
                    continue
                continue
            paths = [operation.get('path', '')]
            if operation.get('op') == 'move':
                paths.append(operation.get('from', ''))
            if relevant_paths and not any(any(path == target or path.startswith(target + '/')
                    or target.startswith(path + '/') for target in relevant_paths if path)
                    for path in paths):
                continue
            matching.update(changed_dimensions & dimensions)
        if not matching:
            uncovered.append({'findingIndexes': indexes, 'requiredDimensions': sorted(dimensions)})
    if uncovered:
        raise PlanningInputError('assessed_repair_not_addressed', 'The patch does not change a matching structured field for every actionable finding group.',
            '/patch', 'Correct every listed group with a matching structured field change in one patch. Use leaf-field edits and move for ordering; add/remove exercise array elements with their individual indices. Replacing an entire exercise list or workout is not credited as changing all nested fields. Unchanged or label-only edits cannot stand in for progression, ordering, prescription, coverage, timing, superset, guidance or exercise-selection repairs. Unaffected array-index shifts do not count. ' + json.dumps(uncovered))


def validate_repair_scope(arguments, task, current_draft=None):
    """Do not let a compact request silently edit a session it has not read."""
    _reject_unresolved_repair_capability(task)
    if 'patch' not in arguments and task.get('findingsAssessment') and not task.get('metadataFields'):
        _validate_draft_schema(arguments)
        if task.get('omittedWorkoutReferences'):
            raise PlanningInputError('draft_details_required', 'Read every session before a coordinated replacement.', '/workouts',
                'Retrieve all omitted workouts; preserve their supported prescriptions in the complete candidate.')
        raise PlanningInputError('repair_patch_required', 'A coordinated assessment repair must submit an atomic targeted patch.', '/patch',
            'Use addressedFindingIndexes and a JSON Patch against currentDraftId. Preserve unchanged fields and cover each repair group through its structured dimensions.')
    if task.get('findingsAssessment') and not task.get('metadataFields'):
        expected = sorted({index for group in task['findingsAssessment'].get('groups', [])
                           if group.get('disposition') == 'repair' for index in group.get('findingIndexes', [])})
        schema = copy.deepcopy(_PATCH_SCHEMA)
        schema['properties']['addressedFindingIndexes'] = {'type': 'array', 'minItems': len(expected), 'maxItems': len(expected),
            'uniqueItems': True, 'items': {'type': 'integer', 'enum': expected}}
        schema['required'].append('addressedFindingIndexes')
        validate(arguments, schema)
        _structured_repair_coverage(arguments, task, current_draft)
        arguments = copy.deepcopy(arguments)
        arguments.pop('addressedFindingIndexes', None)
    if task.get('findingCode') in {'duration_exceeded', 'volume_below_target', 'volume_above_target', 'superset_set_count_mismatch'}:
        for operation in arguments.get('patch', []):
            path = operation.get('path', '')
            if (operation.get('op') in ('add', 'replace')
                    and (path in ('', '/workouts') or re.fullmatch(r'/workouts/\d+(?:/exercises)?', path)
                         or (operation.get('op') == 'replace' and re.fullmatch(r'/workouts/\d+/exercises/\d+', path)))):
                raise PlanningInputError('numeric_repair_too_broad', 'Numerical repairs must preserve untouched prescriptions.', path,
                    'Use the allocator proposal within permitted bounds, or patch individual fields and necessary movement additions/removals. '
                    'Do not replace whole workouts, exercise lists or existing exercise objects to repair counts, volume or duration.')
    rejected = task.get('rejectedSubmission')
    if rejected:
        validate(arguments, _PATCH_SCHEMA)
        allowed = set(task.get('permittedPatchPaths', []))
        if (arguments['baseDraftId'] != rejected.get('baseDraftId')
                or arguments['requirementsId'] != rejected.get('requirementsId')):
            raise PlanningInputError('stale_draft_patch', 'Rejected proposal reference is stale.', '/baseDraftId',
                'Reuse the rejectedSubmission requirementsId and baseDraftId with only the indicated text corrections.')
        validate_patch_operations_scope(arguments['patch'], allowed)
        if any(operation['op'] not in ('add', 'replace') for operation in arguments['patch']):
            raise PlanningInputError('invalid_rejected_patch_retry', 'Correct rejected text with add/replace values only.', '/patch',
                'Send replacement values only for permittedPatchPaths. Python replays the original proposal before these corrections.')
        # Compose atomically; the model never needs to reproduce the other, already-scoped operations.
        return {**copy.deepcopy(rejected), 'patch': copy.deepcopy(rejected['patch'] + arguments['patch'])}
    if 'patch' in arguments and task.get('permittedPatchPaths'):
        validate_patch_operations_scope(arguments['patch'], set(task['permittedPatchPaths']))
    omitted = set(task.get('omittedWorkoutReferences', []))
    if not omitted or 'patch' not in arguments:
        return arguments
    validate(arguments['patch'], _PATCH_SCHEMA['properties']['patch'])
    for operation in arguments['patch']:
        for field in ('path', 'from'):
            path = operation.get(field, '')
            if path == '/workouts/-' and operation.get('op') == 'add' and field == 'path':
                continue
            match = re.match(r'^/workouts/(\d+)(/.*)?$', path)
            hidden = match and f'WORKOUT_{int(match[1])}' in omitted
            shifts = path == '/workouts' or (match and not match[2] and operation.get('op') in ('add', 'remove', 'move', 'copy'))
            if hidden or shifts:
                raise PlanningInputError('draft_details_required', 'Read omitted sessions before editing them or changing their indices.', path,
                    'Call get_workout_draft with currentDraftId as baseDraftId and the needed WORKOUT_n references, then retry a targeted patch. Read all omitted sessions before restructuring workout order.')
    return arguments


def construction_workout_tool(task):
    tool = copy.deepcopy(AUDIT_WORKOUT_PLAN_TOOL)
    schema = copy.deepcopy(_DRAFT_SCHEMA if task['action'] == 'create_first_session' else _PATCH_SCHEMA)
    if task['action'] == 'create_first_session':
        schema['properties']['workouts']['maxItems'] = 1
    else:
        schema['properties']['patch'].update(minItems=1, maxItems=1, items={
            'type': 'object', 'properties': {
                'op': {'const': 'add'}, 'path': {'const': '/workouts/-'},
                'value': copy.deepcopy(_DRAFT_SCHEMA['properties']['workouts']['items']),
            }, 'required': ['op', 'path', 'value'], 'additionalProperties': False})
    tool['function'].update(parameters=schema, description=task['instruction'])
    return tool


def validate_construction_submission(arguments, task):
    """Keep each construction request to its natural unit; the normal audit still validates the complete draft."""
    _strip_legacy_calibration_fields(arguments)
    if isinstance(arguments.get('patch'), list) and arguments['patch']:
        _strip_legacy_calibration_fields(arguments['patch'][0].get('value', {}))
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
    # Append patches have arbitrary values in the general repair schema.
    validate(arguments, construction_workout_tool(task)['function']['parameters'])
    if task.get('definition_ids'):
        day = arguments['workouts'][0] if task['action'] == 'create_first_session' else arguments['patch'][0]['value']
        if {item['definition_id'] for item in day['exercises']} != set(task['definition_ids']):
            raise PlanningInputError('session_selection_mismatch', 'The next session must use the committed movement selection.', '/workouts',
                'Submit the prepared session using constructionTask.definition_ids. The normal audit identifies any unsuitable choice for a subsequent targeted repair; do not restart discovery before submitting it.')


def _latest_result(messages, tool_name):
    calls = {call.get("id") for message in messages for call in message.get("tool_calls", [])
             if call.get("function", {}).get("name") in (("set_workout_requirements", "accept_workout_alternative") if tool_name == "set_workout_requirements" else (tool_name,))}
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "tool" and message.get("tool_call_id") in calls:
            if (message.get("content") or "").startswith((
                    "Tool call started",
                    "Tool call was not completed in the previous session. Treat this as a failed tool result and continue.")):
                continue
            try:
                result = json.loads(message.get("content") or "{}")
                if isinstance(result, dict) and result.get('skipped'):
                    continue
                if tool_name == "set_workout_requirements" and isinstance(result, dict) and result.get("approvedAlternativeId") and not result.get("passed"):
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
            if any(isinstance(error, dict) and error.get('code') in ('construction_stage_required', 'lookup_no_progress')
                   for error in payload.get('errors', [])):
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
            latest = _strip_legacy_calibration_fields(copy.deepcopy(draft)), identifier
    return latest or (None, None)


def _bind_effort_acceptance(draft, working_set_rir=None):
    errors = []
    for workout_index, workout in enumerate(draft.get('workouts', [])):
        for exercise_index, exercise in enumerate(workout.get('exercises', [])):
            path = f'/workouts/{workout_index}/exercises/{exercise_index}/effortAcceptance'
            supplied = exercise.get('effortAcceptance')
            notes = exercise.get('placementNotes', '')
            repair = ('Supply either kind=rir_range with minimumRIR/maximumRIR within 0–10, or kind=technical_criteria '
                'with concrete observable acceptanceCriterion and terminationCriterion. This is a plan-authored prescription, '
                'not a new user requirement; local placementNotes remain technique/setup cues.')
            if _LOCAL_RIR_CLAIM.search(notes):
                errors.append({'code': 'effort_acceptance_in_local_notes', 'path': path.rsplit('/', 1)[0] + '/placementNotes',
                    'message': 'Local notes duplicate typed effort acceptance; Python renders the accepted effort and stop criteria.',
                    'repair': 'Remove RIR and rep-acceptance claims from placementNotes; keep only movement-specific technique/setup cues.'})
            if exercise.get('progressionPlan') and _LOCAL_PROGRESSION_CLAIM.search(notes):
                errors.append({'code': 'progression_in_local_notes', 'path': path.rsplit('/', 1)[0] + '/placementNotes',
                    'message': 'Local notes duplicate the typed progressionPlan rendered by Python.',
                    'repair': 'Remove progression triggers and next-variant instructions from placementNotes; edit progressionPlan if its executable route needs to change.'})
            if working_set_rir:
                expected = {'kind': 'rir_range', 'minimumRIR': working_set_rir['minimum'],
                    'maximumRIR': working_set_rir['maximum'], 'acceptanceCriterion': None,
                    'terminationCriterion': None}
                normalized = ({**{'minimumRIR': None, 'maximumRIR': None,
                    'acceptanceCriterion': None, 'terminationCriterion': None}, **supplied}
                    if isinstance(supplied, dict) else supplied)
                if supplied is not None and normalized != expected:
                    errors.append({'code': 'effort_acceptance_conflicts_with_requirement', 'path': path,
                        'message': 'Per-exercise effortAcceptance must match the approved general workingSetRIR exactly.',
                        'repair': 'Omit effortAcceptance and let Python derive the approved range; do not change a user-approved effort target.'})
                exercise['effortAcceptance'] = expected
                continue
            if supplied is None:
                # Keep saved drafts executable when they predate the typed
                # field; the drafting contract uses this standard range too.
                exercise['effortAcceptance'] = {'kind': 'rir_range', 'minimumRIR': 1,
                    'maximumRIR': 2, 'acceptanceCriterion': None, 'terminationCriterion': None}
                continue
            try:
                validate(supplied, _EFFORT_ACCEPTANCE_SCHEMA)
            except ValidationError as error:
                errors.append({'code': 'invalid_effort_acceptance', 'path': path, 'message': error.message,
                    'repair': 'Use the typed effortAcceptance schema: a bounded RIR range or concrete technical acceptance/termination cues.'})
                continue
            supplied = {**{'minimumRIR': None, 'maximumRIR': None,
                'acceptanceCriterion': None, 'terminationCriterion': None}, **supplied}
            exercise['effortAcceptance'] = supplied
            kind = supplied['kind']
            if kind == 'rir_range':
                minimum, maximum = supplied['minimumRIR'], supplied['maximumRIR']
                if (type(minimum) not in (int, float) or type(maximum) not in (int, float)
                        or not math.isfinite(minimum) or not math.isfinite(maximum)
                        or minimum > maximum or supplied['acceptanceCriterion'] is not None
                        or supplied['terminationCriterion'] is not None):
                    errors.append({'code': 'invalid_effort_acceptance', 'path': path,
                        'message': 'RIR acceptance requires an ordered finite range and no technical cue fields.',
                        'repair': 'Use finite minimumRIR <= maximumRIR within 0–10; set acceptanceCriterion and terminationCriterion to null.'})
            elif (supplied['minimumRIR'] is not None or supplied['maximumRIR'] is not None
                  or not supplied['acceptanceCriterion'].strip() or not supplied['terminationCriterion'].strip()
                  or supplied['acceptanceCriterion'].strip().casefold() == supplied['terminationCriterion'].strip().casefold()):
                errors.append({'code': 'invalid_effort_acceptance', 'path': path,
                    'message': 'Technical effort acceptance requires distinct concrete acceptance and stop cues, with no numeric RIR range.',
                    'repair': 'Give distinct, observable criteria for a passing repetition and for stopping; set both RIR fields to null.'})
    if errors:
        first = errors[0]
        raise PlanningInputError(first['code'], first['message'], first['path'], first['repair'], errors=errors)


def _validate_draft_schema(draft, working_set_rir=None):
    _strip_legacy_calibration_fields(draft)
    _bind_effort_acceptance(draft, working_set_rir)
    if isinstance(draft, dict) and 'programGuidance' in draft:
        value = draft['programGuidance']
        if isinstance(value, str) and not value.strip():
            raise PlanningInputError('empty_program_guidance', 'Program guidance must contain user-facing text.', '/programGuidance',
                'Remove the optional field when there is no program-wide note; blank text is not guidance.')
    errors = list(Draft7Validator(_DRAFT_SCHEMA).iter_errors(draft))
    if errors:
        details = [planning_tool_failure('audit_workout_plan', error, draft)['errors'][0] for error in errors]
        for item in details:
            item['repair'] = ('Correct all indicated draft fields together in a targeted patch against currentDraftId. '
                              'Preserve requirements, library-owned data and valid fields. Restore facts from the source; do not invent replacements.')
            parts = item['path'].split('/')
            if item.get('validator') == 'maxLength' and len(parts) >= 4 and parts[1] == 'workouts':
                day = draft['workouts'][int(parts[2])]
                if parts[3:] == ['description']:
                    item['textFieldContract'] = description_text_contract(day)
                elif len(parts) == 6 and parts[3] == 'exercises' and parts[5] == 'placementNotes':
                    item['textFieldContract'] = placement_notes_text_contract(
                        day['exercises'][int(parts[4])], working_set_rir)
                if item.get('textFieldContract'):
                    item['repair'] = item['textFieldContract']['repair']
        first = details[0]
        raise PlanningInputError(first['code'], first['message'], first['path'], first['repair'], errors=details)


def _strip_legacy_calibration_fields(draft):
    if not isinstance(draft, dict):
        return draft
    workouts = (draft or {}).get('workouts', [])
    if not workouts and isinstance((draft or {}).get('exercises'), list):
        workouts = [draft]
    for workout in workouts:
        if not isinstance(workout, dict):
            continue
        for exercise in workout.get('exercises', []):
            if isinstance(exercise, dict):
                exercise.pop('requiresEffortCalibration', None)
                exercise.pop('calibrationAttempts', None)
    return draft


def _resolve_draft_submission(arguments, messages, equipment):
    try:
        _, approved_requirements = _latest_result(messages, 'set_workout_requirements')
        working_set_rir = approved_requirements['requirements'].get('workingSetRIR')
    except (KeyError, ValueError):
        working_set_rir = None
    is_patch = 'patch' in arguments or 'baseDraftId' in arguments
    if is_patch:
        validate(arguments, _PATCH_SCHEMA)
    else:
        _validate_draft_schema(arguments, working_set_rir)
    previous, current_id = latest_draft_submission(messages, equipment)
    if 'patch' in arguments:
        if previous is None or arguments['baseDraftId'] != current_id:
            raise PlanningInputError('stale_draft_patch', 'The patch base is missing or stale.', '/baseDraftId',
                'Use the currentDraft and currentDraftId in the latest planning snapshot. Do not replay a patch against an older revision.')
        try:
            validate_patch_operations_scope(arguments['patch'], {'/name'}, {'/workouts'})
            draft = apply_json_patch(previous, arguments['patch'])
            draft['requirementsId'] = arguments['requirementsId']
            _validate_draft_schema(draft, working_set_rir)
        except PlanningInputError:
            raise
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
                 and (messages[i].get('imageAttachments') or (messages[i].get("content") or "").strip()
                      not in (EXACT_GENERATION_CONFIRMATION, REQUIREMENTS_CONFIRMATION, '/continue'))), -1)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def library_fingerprint(equipment):
    return _fingerprint({key: equipment.get(key, []) for key in ("exerciseDefinitions", "equipments", "accessoryEquipments")})


def requirement_sources(messages):
    return [{'messageIndex': i, 'role': m['role'], 'content': m['content'],
             **({'imageAttachments': copy.deepcopy(m['imageAttachments'])} if m.get('imageAttachments') else {})}
            for i, m in enumerate(messages) if m.get('role') in ('user', 'assistant') and m.get('content')
            and not m.get('tool_calls') and not m.get('canonicalRequirementsPreview') and not m.get('canonicalDraftPreview')
            and (m.get('imageAttachments') or m['content'].strip() not in (REQUIREMENTS_CONFIRMATION, EXACT_GENERATION_CONFIRMATION, '/continue'))]


def source_message_context(sources):
    return {f'SOURCE_{i}': {'role': m['role'], 'content': m['content'],
            **({'images': [{'name': image['name'], 'sha256': image['sha256'],
                           **({'textOffset': image['textOffset']} if 'textOffset' in image else {})} for image in m['imageAttachments']]}
               if m.get('imageAttachments') else {})} for i, m in enumerate(sources)}


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
            lines.append(f"| {MUSCLE_LABELS.get(muscle, muscle.capitalize())} | {ranges[0]} | {ranges[1]} |")
        lines.extend(['', '— means no target specified. Zero is an explicit zero target.'])
    else:
        lines.append('No volume targets specified.')
    if requirements.get('requiredCoverage'):
        lines.extend(['', '### Required exercise coverage', ''])
        for rule in requirements['requiredCoverage']:
            scope = 'each session' if rule['scope'] == 'eachSession' else 'across the week'
            lines.append(f"- {rule['description']} ({scope}; `{rule['key']}`)")
    if requirements.get('executionRules'):
        lines.extend(['', '### Execution rules', ''])
        lines.extend('- ' + render_execution_rule(rule) for rule in requirements['executionRules'])
    if 'minimumRestDaysBetweenSessions' in requirements:
        lines.append(f"- At least {requirements['minimumRestDaysBetweenSessions']} full rest days between sessions, including across weeks.")
    if 'workingSetRIR' in requirements:
        lines.append(f"- Working sets: {requirements['workingSetRIR']['minimum']:g}–{requirements['workingSetRIR']['maximum']:g} RIR.")
    if requirements.get('requirementAccounting'):
        lines.extend(['', '### Instruction accounting', ''])
        for item in requirements['requirementAccounting']:
            lines.append(f"- {item['instruction']} — {item['priority']}; {item['enforcement']}")
    if requirements.get('objectiveOrder'):
        lines.append('Approved optimization order: ' + ', '.join(requirements['objectiveOrder']) + '.')
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
        lines.extend(['', 'Choose an answer in the separate approval question, or describe corrections.'])
    return "\n".join(lines)


def set_workout_requirements(arguments, messages, equipment=None, client=None, progress=None):
    from .restriction_policy import RESTRICTION_POLICY_VERSION
    from .planning_decisions import resolved_decisions
    accounting_refresh = 'baseRequirementsId' in arguments
    if accounting_refresh:
        base = approved_requirement_base(messages)
        if not base or arguments['baseRequirementsId'] != base['requirementsId']:
            raise PlanningInputError('stale_requirements_refresh', 'The accounting refresh does not name the latest approved requirements.', '/baseRequirementsId', 'Use the current accounting refresh tool; do not reconstruct or relax approved targets.')
        validate(arguments, workout_requirements_tool(equipment, messages, accounting_only=True)['function']['parameters'])
        arguments = {**copy.deepcopy(base['requirements']), 'requirementAccounting': arguments['requirementAccounting'],
                     **({'objectiveOrder': arguments['objectiveOrder']} if 'objectiveOrder' in arguments else {})}
    validate(arguments, _REQUIREMENTS)
    arguments = {**copy.deepcopy(arguments), 'notes': ''}
    from .requirement_accounting import validate_accounting
    try:
        validate_accounting(arguments, source_message_context(requirement_sources(messages)))
    except ValueError as error:
        raise PlanningInputError('invalid_requirement_accounting', str(error), '/requirementAccounting',
            'Resubmit set_workout_requirements preserving all original fields. Use JSON pointers into that submitted object (e.g. /requiredCoverage/0), never coverage keys as array indices; semantic-only instructions use requirementPaths=[]. Do not supply requirementsId in extraction arguments.') from error
    keys = [rule['key'] for rule in arguments.get('requiredCoverage', [])]
    if len(set(keys)) != len(keys):
        raise PlanningInputError('duplicate_coverage_key', 'Coverage keys must be unique.', '/requiredCoverage',
                                 'Give each source-backed coverage requirement a distinct key.')
    rule_errors = execution_rule_errors(arguments)
    if rule_errors:
        first = rule_errors[0]
        raise PlanningInputError(first['code'], first['message'], first['path'], first['repair'], errors=rule_errors)
    # Use the shared target validator even before a draft exists.
    from .generation_audit import validate_audit_targets
    validate_audit_targets(arguments["auditTargets"])
    supported = available_muscle_targets(equipment)
    requested = {muscle for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets')
                 for muscle, bounds in arguments['auditTargets'][field].items() if bounds['maximum'] > 0}
    if requested - supported.keys():
        raise PlanningInputError('unsupported_muscle_targets', f'The loaded library has no auditable credit for: {sorted(requested - supported.keys())}.',
            '/auditTargets', 'Use only auditPolicy.supportedMuscleTargets. Preserve the original request and follow auditPolicy.capabilityLimits to resolve an unsupported target.')
    prior_index, prior = _latest_result(messages, "set_workout_requirements")
    sources = requirement_sources(messages)
    decisions = resolved_decisions(messages)
    restricted = any(arguments.get('exerciseRestrictions', {}).values())
    if prior.get('supportedMuscleTargets') == supported and prior.get('requirementsVersion') == REQUIREMENTS_VERSION and prior.get('sourceMessages') == sources and prior.get('resolvedDecisions', {}) == decisions and prior.get("requirements") == arguments and (not restricted or
            (prior.get('restrictionPolicy', {}).get('libraryFingerprint') == library_fingerprint(equipment or {})
             and prior.get('restrictionPolicy', {}).get('resolutionVersion') == RESTRICTION_POLICY_VERSION)):
        return {**copy.deepcopy(prior), "cached": True}
    coverage_refresh = (prior.get('requirementsVersion') != REQUIREMENTS_VERSION
        and {key: value for key, value in prior.get('requirements', {}).items() if key not in ('requiredCoverage', 'executionRules', 'minimumRestDaysBetweenSessions', 'workingSetRIR', 'requirementAccounting', 'objectiveOrder')}
            == {key: value for key, value in arguments.items() if key not in ('requiredCoverage', 'executionRules', 'minimumRestDaysBetweenSessions', 'workingSetRIR', 'requirementAccounting', 'objectiveOrder')})
    if (prior.get('sourceReview', {}).get('passed') and prior.get("requirements") != arguments
            and prior_index > _revision_index(messages) and not coverage_refresh and not accounting_refresh):
        raise PlanningInputError("requirements_frozen", "Requirements are frozen during automatic repair.", "/",
                                 "Reuse the stored requirementsId and repair the draft. Ask the user before changing a goal.")
    result = {"requirements": copy.deepcopy(arguments), 'requirementsVersion': REQUIREMENTS_VERSION,
              'supportedMuscleTargets': supported,
              'sourceMessages': sources, 'resolvedDecisions': decisions,
              "requirementsId": "REQUIREMENTS_" + _fingerprint({'version': REQUIREMENTS_VERSION, 'requirements': arguments, 'sources': sources})[:16]}
    if accounting_refresh:
        result['accountingRefreshBaseId'] = base['requirementsId']
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
    if result.get('accountingRefreshBaseId'):
        base = approved_requirement_base(messages)
        if (base and base.get('requirementsId') == result['accountingRefreshBaseId']
                and _accounting_refresh_preserves_approved_requirements(base, result)):
            return True
    shown = next((i for i in range(len(messages) - 1, -1, -1)
                  if messages[i].get('role') == 'assistant' and messages[i].get('canonicalRequirementsPreview') == result['requirementsId']
                  and messages[i].get('content') == result['requirementsPreview']), None)
    if shown is not None and result.get('approvedAlternativeId'):
        proposal_id = result['approvedAlternativeId']
        displayed = next((i for i, message in enumerate(messages) if message.get('canonicalAlternativePreview') == proposal_id), None)
        return displayed is not None and any(message.get('role') == 'user' and not message.get('imageAttachments')
            and (message.get('content') or '').strip() == 'APPROVE ALTERNATIVE ' + proposal_id
            for message in messages[displayed + 1:shown])
    return shown is not None and any(message.get('role') == 'user' and not message.get('imageAttachments') and
        (message.get('content') or '').strip() == REQUIREMENTS_CONFIRMATION for message in messages[shown + 1:])


def require_approved_requirements(messages):
    if not requirements_approved(messages):
        raise PlanningInputError('requirements_not_approved', 'The extracted requirements need user approval.', '/',
                                 f'Display the requirements and wait for {REQUIREMENTS_CONFIRMATION}. Do not search, plan, or invent an approved tradeoff.')


def build_draft_plan(arguments, equipment, requirements, restriction_policy=None):
    _bind_effort_acceptance(arguments, requirements.get('workingSetRIR'))
    if any(requirements.get('exerciseRestrictions', {}).values()) and restriction_policy is None:
        raise PlanningInputError('restriction_policy_unresolved', 'Resolve restrictions to library IDs before building a draft.',
                                 '/exerciseRestrictions', 'Record requirements against the current library, display the resolved policy and get confirmation.')
    definitions = sorted(equipment.get("exerciseDefinitions", []), key=lambda d: d["id"])
    by_reference = {f"LIBRARY_{i}": d for i, d in enumerate(definitions)}
    loading_equipment = {item['id']: item for item in equipment.get('equipments', [])}
    plan = {"planName": arguments["name"], "auditTargets": copy.deepcopy(requirements["auditTargets"]),
            "equipments": copy.deepcopy(equipment.get("equipments", [])),
            "accessoryEquipments": copy.deepcopy(equipment.get("accessoryEquipments", [])), "exercises": [], "workouts": []}
    if 'workingSetRIR' in requirements:
        plan['workingSetRIR'] = copy.deepcopy(requirements['workingSetRIR'])
    input_errors = []
    for day_index, day in enumerate(arguments["workouts"]):
        workout = {"id": f"WORKOUT_{day_index}", "name": day["name"], "description": day["description"],
                   "timesCompletedInAWeek": int(day["timesCompletedInAWeek"]), "exerciseIds": [], "restToNextSeconds": [], "supersetGroups": []}
        if 'trainingDays' in day:
            workout['trainingDays'] = list(day['trainingDays'])
            workout['description'] += workout_schedule_suffix(day['trainingDays'])
        contract = description_text_contract(day)
        if len(workout['description']) > contract['exportMaximumCharacters']:
            input_errors.append({'code': 'export_description_too_long', 'path': f'/workouts/{day_index}/description',
                'message': 'Description plus generated schedule exceeds its export cap.',
                'textFieldContract': contract, 'repair': contract['repair']})
        groups = {}
        for exercise_index, item in enumerate(day["exercises"]):
            path = f"/workouts/{day_index}/exercises/{exercise_index}"
            bounds = item.get('allocationBounds')
            if bounds and not bounds['minimum'] <= item['numWorkSets'] <= bounds['maximum']:
                input_errors.append({'code': 'set_count_outside_allocation_bounds', 'path': path + '/allocationBounds',
                    'message': f"{item['numWorkSets']} working sets conflict with the declared range {bounds['minimum']}–{bounds['maximum']}.",
                    'repair': ('Keep the approved allocationBounds range fixed and set numWorkSets within its minimum and maximum. '
                        'If the prescription target itself is wrong, correct workSetTemplate for uniform targets or '
                        'targetSetPrescriptions for distinct set targets. Do not widen or remove the approved range; '
                        'surface a conflict if no compliant prescription is available.')})
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
            if 'setupSeconds' in item:
                exercise['setupSeconds'] = item['setupSeconds']
            if 'allocationBounds' in item:
                exercise['allocationBounds'] = copy.deepcopy(item['allocationBounds'])
            if item.get('progressionMethod'):
                method = item['progressionMethod']
                if ((method == 'duration' and item['durationSeconds'] is None)
                        or (method in ('doubleProgression', 'reps') and (item['minReps'] is None or item['maxReps'] is None))):
                    raise PlanningInputError('invalid_progression_method', 'Progression policy does not match the prescription units.',
                        path + '/progressionMethod', 'Choose source-compatible progression in reps for rep prescriptions, or duration for timed work.')
                if method == 'doubleProgression' and len(get_selectable_weights_for_exercise(
                        kind, loading_equipment.get(definition.get('equipmentId'), {}))) < 2:
                    input_errors.append({'code': 'progression_load_unavailable', 'path': path + '/progressionMethod',
                        'message': 'Reps-then-load progression requires more than one selectable load in this configuration.',
                        'repair': 'Use reps progression or sourceDefined with an executable ROM/leverage/variant progression in placementNotes. Preserve user requirements; if load progression is mandatory, select a supported loadable configuration and re-audit instead.',
                        'permittedPaths': {'exact': [path + '/progressionMethod', path + '/placementNotes'],
                                           'descendants': []}})
            if item.get('progressionPlan'):
                try:
                    validate_progression_plan(item['progressionPlan'], definition, equipment, restriction_policy)
                except (ValueError, ValidationError) as error:
                    raise PlanningInputError('invalid_progression_contract', str(error), path + '/progressionPlan',
                        'Use the qualified, executable progression contract; do not invent equipment or variants.') from error
            exercise['placementNotes'] += generated_progression_note(item)
            exercise['placementNotes'] += effort_acceptance_guidance(
                item.get('effortAcceptance'), requirements.get('workingSetRIR'))
            if item.get("targetSetPrescriptions"):
                exercise["targetSetPrescriptions"] = copy.deepcopy(item["targetSetPrescriptions"])
            if 'workSetTemplate' in item:
                if 'targetSetPrescriptions' in item:
                    raise PlanningInputError('conflicting_set_prescriptions', 'Choose one prescription representation.', path,
                        'Use workSetTemplate for uniform work or targetSetPrescriptions for distinct sets, never both.')
                exercise['targetSetPrescriptions'] = [
                    {'workSetIndex': index, **copy.deepcopy(item['workSetTemplate'])}
                    for index in range(item['numWorkSets'])]
            load_field = 'additionalWeight' if kind == 'BODY_WEIGHT' else 'weight'
            targets = exercise.get('targetSetPrescriptions') or []
            if kind == 'BODY_WEIGHT' and exercise.get('equipmentId') is None:
                for target in targets:
                    if isinstance(target, dict) and 'additionalWeight' not in target and 'weight' not in target:
                        target['additionalWeight'] = 0
            supports_load_calibration = kind == 'WEIGHT' or (kind == 'BODY_WEIGHT' and exercise.get('equipmentId') is not None)
            alternate_load_field = 'weight' if load_field == 'additionalWeight' else 'additionalWeight'
            if (supports_load_calibration and (not targets or all(
                    isinstance(target, dict) and load_field not in target and alternate_load_field not in target
                    for target in targets))):
                exercise['requiresLoadCalibration'] = True
            if item.get('repDurationSeconds') is not None:
                if not math.isfinite(item['repDurationSeconds']):
                    raise PlanningInputError('invalid_rep_duration', 'Per-rep duration must be finite.',
                        path + '/repDurationSeconds', 'Supply positive finite seconds covering the complete rep tempo.')
                if exercise['exerciseType'] not in ('WEIGHT', 'BODY_WEIGHT'):
                    raise PlanningInputError('rep_time_for_non_rep_exercise', 'Per-rep timing applies only to rep-based exercise types.',
                        path + '/repDurationSeconds', 'Use durationSeconds for timed work and null for per-rep timing.')
                exercise['repDurationSeconds'] = item['repDurationSeconds']
            contract = placement_notes_text_contract(item, requirements.get('workingSetRIR'))
            if len(exercise['placementNotes']) > contract['exportMaximumCharacters']:
                input_errors.append({'code': 'export_notes_too_long', 'path': path + '/placementNotes',
                    'message': 'Model-written local cues exceed their allowance; generated guidance has a separate budget.',
                    'textFieldContract': contract, 'repair': contract['repair']})
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
        error = PlanningInputError(first['code'], first['message'], first['path'], first['repair'], errors=input_errors)
        # Diagnostic only: independent checks may inspect this complete but unapproved proposal.
        error.partial_plan = plan
        raise error
    return plan


def _validate_draft_plan(plan, equipment):
    # The export contract uses placeholders; keep the conversational draft's original UUIDs intact.
    from .cli import PlaceholderIdManager

    manager = PlaceholderIdManager()
    # Motion playback data is not part of plan validation and can dwarf the exercise library.
    provided = copy.deepcopy({key: value for key, value in equipment.items() if key != 'exerciseMovements'})
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


def render_draft(plan, requirements, report, restriction_policy=None, source_draft=None):
    def cell(value):
        return str(value).replace("|", "/").replace("\n", " ")

    lines = [f"# {cell(plan['planName'])}", "", render_requirements(requirements, restriction_policy)]
    guidance = (source_draft or {}).get('programGuidance')
    if isinstance(guidance, str) and guidance.strip():
        lines.extend(['', '## Program guidance (manual reference)', cell(guidance)])
    effort = requirements.get('workingSetRIR')
    by_id = {e["id"]: e for e in plan["exercises"]}
    effort_by_id = {identifier: item.get('effortAcceptance')
        for day, source_day in zip(plan['workouts'], (source_draft or {}).get('workouts', []))
        for identifier, item in zip(day['exerciseIds'], source_day['exercises'])}
    templates = {identifier: item['workSetTemplate']
        for day, source_day in zip(plan['workouts'], (source_draft or {}).get('workouts', []))
        for identifier, item in zip(day['exerciseIds'], source_day['exercises']) if 'workSetTemplate' in item}
    for day, audit in zip(plan["workouts"], report["workouts"]):
        lines.extend(["", f"## {cell(day['name'])}", cell(day["description"]),
                      f"Frequency: {day['timesCompletedInAWeek']} per week. Estimated duration: {audit['estimatedSeconds'] / 60:.1f} min.",
                      f"Working sets: {audit['workingSets']} (warm-ups excluded).",
                      "Timing breakdown: " + '; '.join(f"{label}: {audit['timing'].get(key, 0) / 60:.1f} min" for key, label in (
                          ('workSeconds', 'work'), ('restSeconds', 'rest'), ('generalWarmupSeconds', 'general warm-up'),
                          ('rampUpSeconds', 'ramp-up'), ('transitionSeconds', 'setup'), ('calibrationSeconds', 'calibration'))),
                      "", "| Order | Exercise | Sets | Reps / duration | Effort acceptance | Primary muscles | Secondary muscles | Rest between sets | Rest after exercise | Superset rest after this exercise | Notes |",
                      "|---|---|---|---|---|---|---|---|---|---|---|"])
        credits = {item['exerciseId']: item['credits'] for item in audit['contributions']}
        groups = {reference: (i + 1, group) for i, group in enumerate(day["supersetGroups"]) for reference in group["exerciseIds"]}
        for i, reference in enumerate(day["exerciseIds"]):
            e = by_id[reference]
            reps = f"{e['minReps']}–{e['maxReps']}" if e["exerciseType"] in ("WEIGHT", "BODY_WEIGHT") else f"{e['timeInMillis'] / 1000:g}s"
            if e.get('repDurationSeconds', ASSUMPTIONS['secondsPerRep']) != ASSUMPTIONS['secondsPerRep']:
                reps += f"; {e['repDurationSeconds']:g}s/rep"
            if e.get("intraSetRestInSeconds"):
                reps += f" per side; {e['intraSetRestInSeconds']}s between sides"
            pair = groups.get(reference)
            between = "—" if pair else f"{e['restBetweenSetsSeconds']}s"
            round_rest = f"Group {pair[0]}: {pair[1]['restSecondsByExercise'][reference]}s" if pair else "—"
            acceptance = effort_by_id.get(reference) or ({'kind': 'rir_range', 'minimumRIR': effort['minimum'],
                'maximumRIR': effort['maximum']} if effort else None)
            if acceptance and acceptance.get('kind') == 'rir_range':
                effort_text = f"{acceptance['minimumRIR']:g}–{acceptance['maximumRIR']:g} RIR"
                if not effort:
                    effort_text += ' (plan choice)'
            elif acceptance:
                effort_text = 'Technical criteria (plan choice)'
            else:
                effort_text = 'Unspecified'
            notes = ('Straight sets. ' if not pair else f'Superset {pair[0]}. ') + e["placementNotes"]
            if i:
                notes += f" Setup estimate: {e.get('setupSeconds', ASSUMPTIONS['transitionSeconds'])}s before this exercise."
            if e["generateWarmUpSets"]:
                notes += " Ramp-up sets before work."
            if reference in templates:
                notes += ' Starting target per work set: ' + json.dumps(templates[reference], separators=(',', ':'))
            elif e.get("targetSetPrescriptions"):
                notes += " Exact work-set targets: " + json.dumps(e["targetSetPrescriptions"], separators=(",", ":"))
            primary, secondary = [', '.join(MUSCLE_LABELS.get(muscle, muscle.capitalize())
                for muscle, values in credits[reference].items() if values.get(role, 0)) or '—' for role in ('direct', 'indirect')]
            lines.append(f"| {i+1} | {cell(e['name'])} | {e['numWorkSets']} | {cell(reps)} | {cell(effort_text)} | {cell(primary)} | {cell(secondary)} | {between} | {day['restToNextSeconds'][i]}s | {round_rest} | {cell(notes)} |")
    indirect_credit = ASSUMPTIONS['secondarySetCredit']
    lines.extend(["", "Weekly volume audit:",
                  f"Effective sets = direct sets + {indirect_credit:g} × indirect sets. Credits follow the selected library's primary/secondary roles, which may differ from illustrative examples; these are accounting conventions, not exact physiological equivalences.",
                  "", "| Muscle | Direct sets | Indirect sets | Effective sets | Weekly target | Status |", "|---|---|---|---|---|---|"])
    for muscle, values in report["weeklyVolume"].items():
        if values["effective"] or muscle in requirements["auditTargets"]["weeklyEffectiveSets"]:
            bounds = requirements['auditTargets']['weeklyEffectiveSets'].get(muscle)
            target = f"{bounds['minimum']:g}–{bounds['maximum']:g}" if bounds else '—'
            status = ('Within target' if bounds['minimum'] <= values['effective'] <= bounds['maximum'] else 'Outside target') if bounds else 'Reported'
            lines.append(f"| {MUSCLE_LABELS.get(muscle, muscle.capitalize())} | {values['direct']:g} | {values['indirect'] / indirect_credit:g} | {values['effective']:g} | {target} | {status} |")
    lines.extend(['', f"Total weekly working sets: {report['weeklyWorkingSets']} (each physical set counted once; warm-ups excluded)."])
    if source_draft and requirements.get('requiredCoverage'):
        lines.extend(['', '| Movement / coverage | Weekly working sets |', '|---|---:|'])
        for rule in requirements['requiredCoverage']:
            count = report['weeklyCoverageSets'].get(rule['key'], 0)
            lines.append(f"| {cell(rule['key'].replace('_', ' '))} | {count} |")
        lines.extend(['', report['coverageAccounting']])
    lines.extend(["", "Superset rests apply after each listed member; omit the final member's recovery after the last round. Outer exercise rests are separate.",
                  f"Duration estimate: {ASSUMPTIONS['secondsPerRep']}s/rep by default (per-exercise overrides shown above), both sides when unilateral, {ASSUMPTIONS['generalWarmupSeconds']//60} min general warm-up, {ASSUMPTIONS['generatedRampUpSecondsPerExercise']//60} min per generated ramp-up, {ASSUMPTIONS['transitionSeconds']}s per setup transition, plus prescribed rests.",
                 "", "Choose an answer in the separate approval question, or describe a revision."])
    return "\n".join(lines)


def draft_coverage_assignments(plan, source_draft):
    return {identifier: list(item.get('satisfiesCoverage', []))
            for day, source_day in zip(plan['workouts'], (source_draft or {}).get('workouts', []))
            for identifier, item in zip(day['exerciseIds'], source_day['exercises'])}


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
    arguments = normalize_work_set_bounds(arguments, equipment, requirements)
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
        from .training_history import apply_native_load_calibration_policy
        apply_native_load_calibration_policy(plan, messages, equipment,
            training_history.fingerprint if training_history else None,
            allow_educated_load_guesses=allow_educated_load_guesses)
    except (ValueError, ValidationError) as error:
        error.submitted_draft = copy.deepcopy(arguments)
        error.draft_revision_id = revision_id
        error.draft_library_fingerprint = fingerprint
        raise
    report = audit_workout_package(plan_audit_package(plan, allow_educated_load_guesses), requirements["auditTargets"],
        coverage_by_exercise=draft_coverage_assignments(plan, arguments))
    _audit_coverage(arguments, requirements, report)
    audit_execution_rules(arguments, requirements, report, plan)
    audit_execution_details(arguments, requirements, report)
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
        result["preview"] = render_draft(plan, requirements, report, restriction_policy, arguments)
        if decisions:
            result['preview'] += '\n\nResolved planning choices:\n' + render_decisions(decisions)
    else:
        result["instruction"] = "Follow repairTask when supplied. Otherwise assess all findings and address them in a coordinated patch using contributions and timing. Preserve interacting constraints and the complete review repair plan. Consider increasing and decreasing sets across existing exercises before adding movements. Python rechecks the entire draft against all targets. Preserve requirements and library fields, then resubmit promptly. Identical submissions reuse this failure; ask about genuine conflicts instead of relaxing goals."
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
            and not m.get('imageAttachments')
            and (m.get('content') or '').strip() == EXACT_GENERATION_CONFIRMATION
            for m in messages[min(preview_indexes) + 1:]):
        raise ValueError('The current draft needs a fresh CONFIRM GENERATE after its preview is displayed.')
    return copy.deepcopy(result)
