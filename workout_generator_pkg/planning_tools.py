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
from .plan_contract import (LIBRARY_DEFINITION_OWNED_FIELDS, validate_plan_index_contract,
    hydrate_plan_index_from_exercise_library, ContractValidationError, _exercise_requires_unilateral_rest)
from .json_patching import apply_json_patch, validate_patch_operations_scope
from .muscle_roles import MUSCLE_LABELS, MOVEMENT_COVERAGE_ROLES, coverage_role_descriptions
from .programming_guidelines import (EXECUTION_RULES_SCHEMA, MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE,
    EXECUTION_ORDER_DESCRIPTION,
    execution_rule_errors,
    render_execution_rule, audit_execution_rules, audit_execution_details, normalize_work_set_bounds,
    native_warmup_supported, replacement_supports_required_warmup)
from .domain_ops import get_selectable_weights_for_exercise
from .requirement_accounting import (ACCOUNTING_SCHEMA, RELAXATION_PERMISSIONS_SCHEMA,
    validate_relaxation_permissions, pointer as requirement_pointer,
    structured_requirement_source, seed_structured_requirements)
from .repair_capabilities import (has_unresolved_capabilities,
    repair_field_dimensions as _repair_field_dimensions,
    repair_group_dimensions)

REQUIREMENTS_CONFIRMATION = "CONFIRM REQUIREMENTS"
AUDIT_VERSION = 43
REQUIREMENTS_VERSION = 10
# Bound model-written cues; deterministic guidance is not squeezed into this allowance.
_NOTES_SCHEMA = {'type': 'string', 'maxLength': 500}
# Code-owned fallback for newly selected unilateral recipes with no explicit source prescription.
_UNILATERAL_SIDE_REST_DEFAULT_SECONDS = 30


def _replacement_type_family(exercise_type):
    if exercise_type in ('WEIGHT', 'BODY_WEIGHT'):
        return 'reps'
    if exercise_type in ('COUNTUP', 'COUNTDOWN'):
        return exercise_type
    return None


def _replacement_types_compatible(source_type, replacement_type):
    source_family = _replacement_type_family(source_type)
    return source_family is not None and source_family == _replacement_type_family(replacement_type)


def effort_acceptance_guidance(effort_acceptance, working_set_rir=None):
    acceptance = ({**(effort_acceptance or {}), 'kind': 'rir_range',
        'minimumRIR': working_set_rir['minimum'], 'maximumRIR': working_set_rir['maximum']}
        if working_set_rir else effort_acceptance)
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
    if acceptance['kind'] == 'rir_range' and acceptance.get('acceptanceCriterion'):
        text += (f"Technical acceptance: {acceptance['acceptanceCriterion']} Stop when "
                 f"{acceptance['terminationCriterion']}. ")
    return text


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
    generated = effort_acceptance_guidance(item.get('effortAcceptance'), working_set_rir)
    contract = export_text_contract(item.get('placementNotes', ''), _NOTES_SCHEMA)
    contract.update(generatedText=generated, reservedCharacters=0,
                    exportMaximumCharacters=_NOTES_SCHEMA['maxLength'] + len(generated))
    repair = 'Use local technique/setup cues only; do not invent a numeric RIR target, trial settings, calibration loads, counts or generatedText. Preserve valid execution and stop rules. Do not change the prescription to make text fit.'
    return {**contract,
            'purpose': 'Local execution/setup cues only; typed effort acceptance are rendered separately.',
            'repair': repair}


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
    from .api_metrics import record_submission_rejection
    if isinstance(error, (ValueError, ValidationError, ContractValidationError)):
        record_submission_rejection(error, stage=tool_name)
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
                correction = _schema_sibling_correction(validation_error, schema_root,
                    getattr(error, 'validation_arguments', arguments))
                if correction:
                    diagnostic.update(correction)
                    diagnostic['repair'] = correction['repair']
            if path.endswith('/workSetTemplate') or '/workSetTemplate/' in path or '/targetSetPrescriptions' in path:
                diagnostic['repair'] += (' Keep the approved work-set count range unchanged. Correct the prescription with '
                    'workSetTemplate for uniform targets or targetSetPrescriptions for distinct set targets; '
                    'do not remove or widen allocationBounds to make it fit.')
            errors.append(diagnostic)
        errors.extend(getattr(error, 'supplemental_errors', []))
    elif isinstance(error, ContractValidationError) and error.issues:
        positions = {f'EXERCISE_{index}': position for index, position in enumerate(
            (d, e) for d, day in enumerate((arguments or {}).get("workouts", []))
            for e, _ in enumerate(day.get("exercises", [])))}
        errors = []
        for issue in error.issues:
            path = "/workouts"
            position = positions.get(issue.exercise_id)
            if position is not None:
                day, exercise = position
                path = f"/workouts/{day}/exercises/{exercise}"
                if issue.field:
                    path += '/' + issue.field.replace('~', '~0').replace('/', '~1')
            issue_repair = repair
            if issue.code == 'target_set_prescription_outside_rep_range' and position is not None:
                work_set_index = issue.work_set_index
                source_day, source_exercise = position
                source = (arguments or {}).get('workouts', [])[source_day].get('exercises', [])[source_exercise]
                minimum, maximum = source.get('minReps'), source.get('maxReps')
                approved_range = (f"{minimum}–{maximum}" if isinstance(minimum, int) and isinstance(maximum, int)
                                  else 'the existing minReps–maxReps range')
                if 'workSetTemplate' in source:
                    path = f"/workouts/{source_day}/exercises/{source_exercise}/workSetTemplate/reps"
                    source_field = 'workSetTemplate.reps'
                elif work_set_index is not None:
                    prescription_index = work_set_index
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
                           "exerciseId": issue.exercise_id})
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
        result['instruction'] += ' No operations were applied. Python retains rejectedSubmission as evidence; submit the complete permitted correction against the current saved candidate.'
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
    return bool(re.fullmatch(r'/(?:workouts/\d+/description|sessions/\d+/description)', error.get('path', ''))
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
        "maximum": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
    }, "required": ["minimum", "maximum"], "additionalProperties": False} for muscle in MUSCLES
}, "additionalProperties": False}
_TARGETS = {"type": "object", "properties": {
    "weeklyEffectiveSets": _BOUNDS, "perSessionEffectiveSets": _BOUNDS,
    "maximumSessionSeconds": {"type": ["integer", "null"], "minimum": 1},
}, "required": ["weeklyEffectiveSets", "perSessionEffectiveSets", "maximumSessionSeconds"], "additionalProperties": False}
_FAMILY_SET_BOUNDS = {'type': 'array', 'items': {'type': 'object', 'properties': {
    'exerciseFamilyId': {'type': 'string', 'minLength': 1},
    'minimumWeeklySets': {'type': 'integer', 'minimum': 0},
    'maximumWeeklySets': {'type': 'integer', 'minimum': 0},
}, 'required': ['exerciseFamilyId'], 'additionalProperties': False},
    'description': 'Optional explicit user-approved weekly family bounds, counted across all sessions and frequencies. '
        'Choose a code-provided reviewed family; preserve user quantities. Equal bounds express a target. '
        'Omission imposes no family limit. Do not infer caps from a qualitative concern.'}
_REQUIREMENTS = {"type": "object", "properties": {
    'familySetBounds': _FAMILY_SET_BOUNDS,
    'requirementAccounting': ACCOUNTING_SCHEMA,
    'relaxationPermissions': RELAXATION_PERMISSIONS_SCHEMA,
    'objectiveOrder': {'type': 'array', 'uniqueItems': True, 'items': {'type': 'string', 'enum': [
        'demand_distribution', 'duration_balance', 'source_balance', 'exercise_distribution',
        'workload_economy', 'distribution', 'development_emphasis', 'development_exposure',
        'progression', 'preservation']},
        'description': 'objectiveOrder is authoritative: list applicable supported solver preferences from highest to lowest; omitted preferences do not run. demand_distribution reduces per-session peaks of working-set exposure for sourced library demand properties; missing classifications are unknown, never zero demand. It is exposure distribution, not a fatigue score or tolerance limit. duration_balance minimizes excess spread beyond durationBalanceToleranceSeconds using the same timing model as the hard session limit. source_balance minimizes differences for balanced coverage pairs and one-sided undershoot for source-backed first_not_less_than_second comparisons; these are soft comparisons, not quotas. exercise_distribution spreads working-set exposure across sourced movement families within completely classified qualified-role pools; variants in one reviewed family count together, and unknown pools are omitted rather than treated as diverse. workload_economy minimizes total physical working sets across the week; frequency is counted and supersets do not double-count a physical set. It is a soft preference after the earlier approved priorities and cannot change user-owned counts, hard floors, or other constraints. distribution reduces muscle-set concentration. requiredCoverage.intent=development describes a source-backed purpose; only its explicit minimumWeeklySets/minimumSessions fields create hard floors. Development intent never inserts extra-exposure objectives. development_emphasis and development_exposure are optional preferences, used only when explicitly supported and ranked in objectiveOrder; they maximize role exposure without creating floors or proving adequacy. The app owns progression and load calibration; this generator does not define their policy. preservation minimizes changes to the CURRENT CANDIDATE, never user requirements. Safety, equipment, duration, volume and explicit exercise bounds remain constraints, not optimization preferences. Do not invent qualitative rankings, ratios, fatigue thresholds, or numeric requirements.'},
    'durationBalanceToleranceSeconds': {'type': 'integer', 'minimum': 0,
        'description': 'Optional source-stated soft tolerance for duration_balance: spreads up to this many seconds count as equally balanced, allowing lower-ranked objectives to choose among them. When maximumSessionSeconds is set, this cannot exceed that hard limit. Use only an explicit numeric tolerance from the user; do not translate “similar” or other qualitative wording into guessed seconds. This is not a hard time limit.'},
    "executionRules": EXECUTION_RULES_SCHEMA,
    "requiredCoverage": {"type": "array", "maxItems": 30, "description": "Select only code-defined movement or supported muscle-role keys. Do not add exercise-variant qualifiers in free text; the original user source remains the authority for qualitative meaning. `intent` distinguishes source-backed inclusion from development emphasis; development is qualitative and creates no automatic numeric floor. No invented balance rules.", "items": {
        "type": "object", "properties": {
            "key": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$", "maxLength": 60},
            "description": {"type": "string", "minLength": 1, "maxLength": 300},
            "scope": {"enum": ["eachSession", "weekly"]},
            "intent": {"enum": ["inclusion", "development"]},
            "minimumWeeklySets": {"type": "integer", "minimum": 1, "maximum": 100,
                "description": "Explicitly approved minimum qualified working sets per week for this role; no default is inferred from development emphasis."},
            "minimumSessions": {"type": "integer", "minimum": 1, "maximum": 21,
                "description": "Explicitly approved minimum weekly training occasions containing qualified work for this role; multiple exercises in one session count once."},
        }, "required": ["key", "scope"], "additionalProperties": False}},
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
    "description": "Extract structured requirements from the original instructions. After the first source-checked candidate, submit only typed field updates against its baseRequirementsId; omitted fields stay unchanged. Use null to clear a non-nullable optional field, or the field's normal null value when its schema allows null. Replace arrays explicitly, using [] to clear them. Original instructions remain the source of qualitative intent. Python checks the complete merged result and shows it for confirmation. Never lower targets to resolve conflicts or promote general training advice to a binding rule. For ambiguity, ask and wait.",
    "parameters": {**_REQUIREMENTS, "properties": {key: value for key, value in _REQUIREMENTS['properties'].items() if key != 'notes'}},
}}

_COVERAGE_ROLE_DESCRIPTIONS = coverage_role_descriptions()
_PUBLIC_REQUIRED_COVERAGE = copy.deepcopy(_REQUIREMENTS['properties']['requiredCoverage'])
_PUBLIC_REQUIRED_COVERAGE['items']['properties'].pop('description')
_PUBLIC_REQUIRED_COVERAGE['items']['properties']['key']['description'] = (
    'Choose an explicit source-backed role from the code-owned key list. Its canonical label is added by Python; '
    'do not encode exercise variations or qualifiers in a free-text description.')
_PUBLIC_REQUIRED_COVERAGE['items']['required'] = ['key', 'scope']
SET_WORKOUT_REQUIREMENTS_TOOL['function']['parameters']['properties']['requiredCoverage'] = _PUBLIC_REQUIRED_COVERAGE


def _coverage_role_schema(supported_muscles):
    schema = copy.deepcopy(_PUBLIC_REQUIRED_COVERAGE)
    normalized_supported = {muscle.replace('lowerBack', 'lower_back') for muscle in supported_muscles}
    available_roles = set(MOVEMENT_COVERAGE_ROLES) | normalized_supported
    schema['items']['properties']['key']['enum'] = sorted(available_roles)
    return schema


def _family_set_bounds_schema(equipment):
    from .recipe_contracts import reviewed_exercise_family_evidence, library_definitions_by_reference
    schema = copy.deepcopy(_FAMILY_SET_BOUNDS)
    definitions = library_definitions_by_reference(equipment or {})
    families = reviewed_exercise_family_evidence(equipment or {})['familyByReference']
    choices = {}
    for reference, family in families.items():
        choices.setdefault(family, []).append(definitions[reference]['name'])
    selector = schema['items']['properties']['exerciseFamilyId']
    if choices:
        selector['enum'] = sorted(choices)
    else:
        schema['maxItems'] = 0
    selector['description'] = 'Reviewed family choices: ' + json.dumps(choices, ensure_ascii=False)
    return schema


def _execution_rules_schema(supported_muscles):
    schema = copy.deepcopy(EXECUTION_RULES_SCHEMA)
    keys = _coverage_role_schema(supported_muscles)['items']['properties']['key']['enum']
    for rule in schema['items']['oneOf']:
        for field in ('first', 'second', 'before', 'after', 'coverageKey'):
            selector = rule['properties'].get(field)
            if selector is not None:
                for branch in selector.get('anyOf', [selector]):
                    if branch.get('type') == 'string':
                        branch['enum'] = list(keys)
    return schema


def _canonicalize_required_coverage(arguments, supported_muscles):
    """Fill code-owned labels for fresh roles; retain labels already stored in legacy candidates."""
    supported_roles = set(MOVEMENT_COVERAGE_ROLES) | {
        muscle.replace('lowerBack', 'lower_back') for muscle in supported_muscles}
    for rule in arguments.get('requiredCoverage', []):
        if 'description' in rule:
            continue
        if rule.get('key') not in supported_roles:
            raise PlanningInputError('unknown_coverage_key',
                f"Coverage role '{rule.get('key')}' is not supported by the loaded exercise library.",
                '/requiredCoverage', 'Use a code-defined movement role or a supported muscle-role key.')
        description = _COVERAGE_ROLE_DESCRIPTIONS.get(rule.get('key'))
        if description is None:
            raise PlanningInputError('unknown_coverage_key',
                f"Coverage role '{rule.get('key')}' has no code-defined label.",
                '/requiredCoverage', 'Use one of the code-defined coverage-role keys.')
        rule['description'] = description


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


def latest_requirement_candidate(messages):
    """Latest extracted candidate with a completed source review, approved or not."""
    calls = {call.get('id') for message in messages for call in message.get('tool_calls', [])
             if call.get('function', {}).get('name') in ('set_workout_requirements', 'accept_workout_alternative')}
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get('role') != 'tool' or message.get('tool_call_id') not in calls:
            continue
        try:
            result = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            continue
        if (isinstance(result, dict) and result.get('requirements') and result.get('requirementsId')
                and isinstance(result.get('sourceReview'), dict)):
            return index, result
    return -1, {}


def _resume_approved_requirements_after_unrequested_decision(messages, candidate_index, candidate):
    """Keep the exact approved hard requirements active after a decision-only no-op."""
    if (candidate.get('passed') is not False
            or candidate.get('sourceReview', {}).get('passed') is not False
            or not isinstance(candidate.get('requirements'), dict)):
        return None

    tool_call_id = messages[candidate_index].get('tool_call_id')
    call = next((call for message in messages[:candidate_index] for call in message.get('tool_calls', [])
                 if call.get('id') == tool_call_id), None)
    try:
        arguments = json.loads(call.get('function', {}).get('arguments', '{}')) if call else {}
    except (ValueError, TypeError, AttributeError):
        return None
    if arguments.get('updates') != {}:
        return None

    prior_messages = messages[:candidate_index]
    approved = approved_requirement_base(prior_messages)
    if (not approved or candidate.get('requirements') != approved.get('requirements')
            or not requirements_approved(messages, approved)):
        return None

    from .planning_decisions import _current_reviewed_audit, latest_decision_receipt
    audit_index, audit = _current_reviewed_audit(prior_messages)
    if (audit_index < 0 or audit_index >= candidate_index
            or audit.get('requirementsId') != approved.get('requirementsId')
            or not isinstance(audit.get('submittedDraft'), dict)):
        if not candidate.get('proposedDecisions'):
            return None
        audit_index, audit = _latest_result(prior_messages, 'audit_workout_plan')
        latest_draft = audit.get('submittedDraft') or audit.get('currentDraft')
        if (audit_index < 0 or audit_index >= candidate_index
                or audit.get('requirementsId') != approved.get('requirementsId')
                or not isinstance(latest_draft, dict)):
            return None
    decision_index, decision = latest_decision_receipt(prior_messages)
    boundary = (decision.get('decisionReview') or {}).get('instructionBoundary')
    decision_only = (decision_index > audit_index and decision_index < candidate_index
        and isinstance(boundary, int) and audit_index < boundary < decision_index
        and messages[boundary].get('role') == 'user'
        and not any(message.get('role') == 'user'
                    for message in messages[boundary + 1:candidate_index]))
    if not decision_only:
        # Retain the earlier, already-proven control-only recovery for a rejected
        # decision proposal. It still requires the exact approved base and no
        # intervening user instruction.
        _, latest_audit = _latest_result(prior_messages, 'audit_workout_plan')
        latest_draft = latest_audit.get('submittedDraft') or latest_audit.get('currentDraft')
        controls = {'/continue', '/resume'}
        control_only = (bool(candidate.get('proposedDecisions'))
            and candidate.get('baseRequirementsId') == approved.get('requirementsId')
            and isinstance(latest_draft, dict)
            and latest_audit.get('requirementsId') == approved.get('requirementsId')
            and not any(message.get('role') == 'user'
                and (message.get('content') or '').strip() not in controls
                for message in messages[audit_index + 1:candidate_index]))
        if not control_only:
            return None

    requirement_calls = {call.get('id') for message in prior_messages
                         for call in message.get('tool_calls', [])
                         if call.get('function', {}).get('name') in
                         ('set_workout_requirements', 'accept_workout_alternative')}
    for index in range(candidate_index - 1, -1, -1):
        message = messages[index]
        if message.get('role') != 'tool' or message.get('tool_call_id') not in requirement_calls:
            continue
        try:
            result = json.loads(message.get('content') or '{}')
        except (ValueError, TypeError):
            continue
        if (isinstance(result, dict) and result.get('requirementsId') == approved.get('requirementsId')
                and result.get('sourceReview', {}).get('passed') is True):
            return index, approved
    return None


def active_requirement_result(messages):
    """Return latest requirements, recovering an exact approved base after a decision-only no-op."""
    index, candidate = _latest_requirements_result(messages)
    if index < 0:
        return index, candidate
    recovered = _resume_approved_requirements_after_unrequested_decision(messages, index, candidate)
    return recovered if recovered is not None else (index, candidate)


def _latest_requirements_result(messages):
    """Preserve the original extraction semantics for every set-requirements result."""
    calls = {call.get("id") for message in messages for call in message.get("tool_calls", [])
             if call.get("function", {}).get("name") in ('set_workout_requirements', 'accept_workout_alternative')}
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get('role') != 'tool' or message.get('tool_call_id') not in calls:
            continue
        if (message.get('content') or '').startswith((
                "Tool call started",
                "Tool call was not completed in the previous session. Treat this as a failed tool result and continue.")):
            continue
        try:
            result = json.loads(message.get('content') or '{}')
        except (ValueError, TypeError):
            continue
        if isinstance(result, dict) and result.get('skipped'):
            continue
        if isinstance(result, dict) and result.get('approvedAlternativeId') and not result.get('passed'):
            continue
        if isinstance(result, dict) and result.get('requirements'):
            return index, result
    return -1, {}


def _partial_requirement_schema(schema):
    """Allow sparse typed objects; arrays still replace as a whole."""
    result = copy.deepcopy(schema)
    schema_type = result.get('type')
    if schema_type == 'object' or (isinstance(schema_type, list) and 'object' in schema_type):
        result['type'] = ['object', 'null'] if not isinstance(schema_type, list) or 'null' not in schema_type else schema_type
        result.pop('required', None)
        result['properties'] = {key: _partial_requirement_schema(value)
                                for key, value in result.get('properties', {}).items()}
    elif schema_type == 'array' or (isinstance(schema_type, list) and 'array' in schema_type):
        result['type'] = list(schema_type) if isinstance(schema_type, list) else ['array', 'null']
        if 'null' not in result['type']:
            result['type'].append('null')
    elif schema_type is not None:
        result['type'] = list(schema_type) if isinstance(schema_type, list) else [schema_type]
        if 'null' not in result['type']:
            result['type'].append('null')
    return result


def _merge_requirement_updates(base, updates, schema):
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        field_schema = schema['properties'][key]
        if value is None and 'null' not in (field_schema.get('type') if isinstance(field_schema.get('type'), list)
                                            else [field_schema.get('type')]):
            merged.pop(key, None)
        elif isinstance(value, dict) and (field_schema.get('type') == 'object'
                or 'object' in (field_schema.get('type') if isinstance(field_schema.get('type'), list)
                                else [field_schema.get('type')])):
            existing = merged.get(key)
            merged[key] = _merge_requirement_updates(existing if isinstance(existing, dict) else {}, value, field_schema)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _live_relaxation_permissions_schema(equipment, requirements=None):
    supported = available_muscle_targets(equipment)
    paths = ['/auditTargets/maximumSessionSeconds']
    for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets'):
        targets = (requirements or {}).get('auditTargets', {}).get(field, {})
        for muscle in sorted(supported):
            bounds = targets.get(muscle)
            paths.append(f'/auditTargets/{field}/{muscle}/minimum')
            if not bounds or bounds.get('maximum') is not None:
                paths.append(f'/auditTargets/{field}/{muscle}/maximum')
    schema = copy.deepcopy(RELAXATION_PERMISSIONS_SCHEMA)
    schema['items']['properties']['path']['enum'] = paths
    return schema


def _requirement_changes(before, after, path=''):
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            child_path = f'{path}/{key}'
            if key not in before:
                changes.append((child_path, None, after[key]))
            elif key not in after:
                changes.append((child_path, before[key], None))
            else:
                changes.extend(_requirement_changes(before[key], after[key], child_path))
        return changes
    return [] if before == after else [(path or '/', before, after)]


def _render_requirement_changes(before, after):
    changes = _requirement_changes(before, after)
    if not changes:
        return '### Changes from the previous source-checked candidate\n\nNo structured requirement fields changed.'
    lines = ['### Changes from the previous source-checked candidate', '']
    for path, old, new in changes:
        old_text = 'cleared' if old is None else json.dumps(old, ensure_ascii=False, sort_keys=True)
        new_text = 'cleared' if new is None else json.dumps(new, ensure_ascii=False, sort_keys=True)
        lines.append(f'- `{path}`: {old_text} → {new_text}')
    return '\n'.join(lines)


def _requirement_update_tool(equipment, base, messages=None):
    from .planning_decisions import record_planning_decisions_tool
    properties = {key: _partial_requirement_schema(value)
                  for key, value in _REQUIREMENTS['properties'].items()
                  if key not in ('requirementAccounting', 'notes')}
    properties['relaxationPermissions'] = _partial_requirement_schema(
        _live_relaxation_permissions_schema(equipment, base.get('requirements')))
    supported = available_muscle_targets(equipment)
    properties['requiredCoverage'] = _coverage_role_schema(supported)
    properties['executionRules'] = _partial_requirement_schema(_execution_rules_schema(supported))
    properties['familySetBounds'] = _family_set_bounds_schema(equipment)
    for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets'):
        properties['auditTargets']['properties'][field]['properties'] = {
            key: value for key, value in properties['auditTargets']['properties'][field]['properties'].items()
            if key in supported}
    tool = copy.deepcopy(SET_WORKOUT_REQUIREMENTS_TOOL)
    tool['function']['parameters'] = {'type': 'object', 'properties': {
        'baseRequirementsId': {'type': 'string', 'enum': [base['requirementsId']]},
        'updates': {'type': 'object', 'properties': properties, 'additionalProperties': False},
        'planningDecisions': copy.deepcopy(
            record_planning_decisions_tool(messages or [])['function']['parameters']),
    }, 'required': ['baseRequirementsId', 'updates'], 'additionalProperties': False}
    return tool


def workout_requirements_tool(equipment, messages=None, *, accounting_only=None):
    messages = messages or []
    if accounting_only is True:
        base = approved_requirement_base(messages)
        if base:
            tool = copy.deepcopy(SET_WORKOUT_REQUIREMENTS_TOOL)
            tool['function']['parameters'] = {'type': 'object', 'properties': {
                'baseRequirementsId': {'type': 'string', 'enum': [base['requirementsId']]},
                'requirementAccounting': ACCOUNTING_SCHEMA,
                'objectiveOrder': copy.deepcopy(_REQUIREMENTS['properties']['objectiveOrder'])},
                'required': ['baseRequirementsId', 'requirementAccounting'], 'additionalProperties': False}
            return tool
    supported = available_muscle_targets(equipment)
    _, candidate = latest_requirement_candidate(messages)
    if candidate:
        tool = _requirement_update_tool(equipment, candidate, messages)
        return _structured_requirements_tool(tool, messages, candidate)
    tool = copy.deepcopy(SET_WORKOUT_REQUIREMENTS_TOOL)
    tool['function']['parameters']['properties'].pop('requirementAccounting', None)
    tool['function']['parameters']['properties']['relaxationPermissions'] = _live_relaxation_permissions_schema(equipment)
    tool['function']['parameters']['properties']['requiredCoverage'] = _coverage_role_schema(supported)
    tool['function']['parameters']['properties']['executionRules'] = _execution_rules_schema(supported)
    tool['function']['parameters']['properties']['familySetBounds'] = _family_set_bounds_schema(equipment)
    from .planning_decisions import record_planning_decisions_tool
    tool['function']['parameters']['properties']['planningDecisions'] = copy.deepcopy(
        record_planning_decisions_tool(messages)['function']['parameters'])
    tool['function']['description'] += (' When choices and extraction are ready together, include planningDecisions '
        'with decisions/sourceReferences for one independent authorization and requirements review. '
        'Do not invent user authorization; unresolved ambiguity still requires asking the user.')
    for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets'):
        bounds = tool['function']['parameters']['properties']['auditTargets']['properties'][field]
        bounds['properties'] = {key: value for key, value in bounds['properties'].items() if key in supported}
    return _structured_requirements_tool(tool, messages)


def _structured_requirements_tool(tool, messages, base=None):
    try:
        authority = _structured_requirement_source(requirement_sources(messages))
    except PlanningInputError:
        # The backend reports invalid user input through the existing tool error path.
        return tool
    if base and authority and authority['sourceMessageIndex'] <= max(
            (source['messageIndex'] for source in base.get('sourceMessages', [])), default=-1):
        return tool
    if authority:
        parameters = tool['function']['parameters']
        if base:
            parameters = parameters['properties']['updates']
        for key, value in authority['requirements'].items():
            if key == 'executionRules':
                kinds = {rule['kind'] for rule in value}
                variants = parameters['properties'][key]['items']['oneOf']
                remaining = [rule for rule in variants if rule['properties']['kind']['const'] not in kinds]
                if remaining:
                    parameters['properties'][key]['items']['oneOf'] = remaining
                    parameters['properties'][key]['description'] = 'Additional rule kinds only; Python loads the user-supplied rules.'
                    continue
            parameters['properties'].pop(key, None)
            if key in parameters.get('required', []):
                parameters['required'].remove(key)
        tool['function']['description'] += (
            ' Python loads the explicitly marked user structured requirements directly. '
            'Return only remaining fields; do not repeat supplied values. Additional executionRules use only new rule kinds.')
    return tool


_WORK_SET_FIELDS = {"reps": {"type": "integer", "minimum": 1},
                    "weight": {"type": "number", "minimum": 0},
                    "additionalWeight": {"type": "number", "minimum": 0}}
_EFFORT_ACCEPTANCE_SCHEMA = {'type': 'object', 'properties': {
    'kind': {'type': 'string', 'enum': ['rir_range', 'technical_criteria'],
        'description': 'A plan-authored prescription, not a user requirement. rir_range may also include paired technical acceptance/stop cues; technical_criteria supplies cues without a numeric target.'},
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
            'Paired technical cues may supplement rir_range. Approved workingSetRIR is fixed; Python binds its exact range, preserving supplemental cues.')},
    "allocationBounds": {"type": "object", "properties": {
        "minimum": {"type": "integer", "minimum": 1, "maximum": 20},
        "maximum": {"type": "integer", "minimum": 1, "maximum": 20}},
        "required": ["minimum", "maximum"], "additionalProperties": False,
        "description": "Python derives these bounds from approved workSets execution rules; model suggestions and omission do not lock counts. workSetTemplate repeats unchanged as counts vary; exact targetSetPrescriptions remain locked. Never widen an explicit user limit."},
    "satisfiesCoverage": {"type": "array", "uniqueItems": True, "items": {"type": "string"}, "description": "ALL applicable approved requiredCoverage keys this occurrence satisfies according to the code-defined role and original source. Include every applicable role so pattern totals are complete. Do not infer a specific exercise variation unless the original source requires it. The independent reviewer verifies accuracy and completeness against the actual movement; assignment alone is not proof."},
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
        "description": "Total seconds per rep including concentric, eccentric and pauses. Default 3 when no tempo is specified. Includes concentric and eccentric phases and pauses. For timed/running work use null."},
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
                 "restAfterSupersetExerciseSeconds", "intraSetRestInSeconds", "generateWarmUpSets"],
    "additionalProperties": False,
}
AUDIT_WORKOUT_PLAN_TOOL = {"type": "function", "function": {
    "name": "audit_workout_plan",
    "description": "Call only when creating or changing the structured draft; questions and explanations do not require another audit. Python audits volume, estimated duration and approved executionRules; a passing preview requires the independent execution review too. On failure, follow errors[].repair, change the draft and resubmit without changing requirements. If constraints conflict, explain and ask the user; never silently relax goals or loop on an unchanged failing draft. Export uses this exact draft after CONFIRM GENERATE. Superset members must be contiguous with equal sets; only the final member may have outer rest. Exact loads use app totals (dumbbell pair = combined total).",
    "parameters": {"type": "object", "properties": {
        "requirementsId": {"type": "string"}, "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "programGuidance": {"type": "string", "minLength": 1,
            "description": "Legacy program-wide notes retained in the source only. Active audit disclosures are code-owned. Execution criteria belong in typed effortAcceptance."},
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


def uses_menu_selection(task, *, domain=None):
    task = task or {}
    if task.get('preferSparseEdits') is True:
        return False
    groups = [group for group in (task.get('findingsAssessment') or {}).get('groups', [])
              if group.get('disposition') == 'repair']
    objectives = [objective for group in groups for objective in group.get('repairObjectives', [])]
    if any(objective.get('kind') != 'redistribute_work' for objective in objectives):
        return False
    if task.get('candidateMenuExpansionTask') and not objectives:
        return True
    menu_dimensions = {'exercise_selection', 'ordering', 'superset', 'coverage'}
    group_dimensions = [repair_group_dimensions(group) for group in groups]
    selection_requested = any(dimensions & menu_dimensions for dimensions in group_dimensions)
    if not selection_requested:
        return False
    domain = domain or repair_exercise_domain(task)
    if domain['protected'] and not domain['editable']:
        return False
    return all(dimensions & (menu_dimensions | {'session_labels'}) for dimensions in group_dimensions)


def coordinated_repair_tool(task=None, *, for_compilation=False):
    tool = copy.deepcopy(REPAIR_WORKOUT_PLAN_TOOL)
    task = task or {}
    indexes = sorted({index for group in task.get('findingsAssessment', {}).get('groups', [])
                      if group.get('disposition') == 'repair' for index in group.get('findingIndexes', [])})
    assessed_repair = isinstance(task.get('findingsAssessment'), dict)
    current_draft = task.get('currentDraft') or {}
    workouts = current_draft.get('workouts', [])
    repair_domain = repair_exercise_domain(task, current_draft)
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
    available_definition_references = sorted(set(task.get('replacementDefinitionReferences', [])) |
        {exercise.get('definition_id') for day in workouts for exercise in day.get('exercises', [])
         if isinstance(exercise.get('definition_id'), str)})
    if available_definition_references:
        field_properties['definition_id']['enum'] = available_definition_references
    if assessed_repair and not for_compilation:
        field_properties.pop('numWorkSets', None)
    addition_exercise_schema = copy.deepcopy(_EXERCISE)
    addition_exercise_schema['properties'].pop('allocationBounds', None)
    if available_definition_references:
        addition_exercise_schema['properties']['definition_id']['enum'] = available_definition_references
    exercise_update_items = {'type': 'object', 'properties': {
        'exerciseRef': {'type': 'string', 'enum': exercise_refs},
        'setFields': {'type': 'object', 'properties': copy.deepcopy(field_properties), 'additionalProperties': False},
        'removeOptionalFields': {'type': 'array', 'uniqueItems': True,
            'items': {'type': 'string', 'enum': exercise_optional}}},
        'required': ['exerciseRef'], 'additionalProperties': False}
    edit_schema = {'type': 'object', 'properties': {
        'workoutUpdates': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'workoutRef': {'type': 'string', 'enum': workout_refs},
            'setFields': {'type': 'object', 'properties': {key: copy.deepcopy(workout_fields[key])
                for key in ('name', 'description', 'timesCompletedInAWeek', 'trainingDays')}, 'additionalProperties': False},
            'removeOptionalFields': {'type': 'array', 'uniqueItems': True,
                'items': {'type': 'string', 'enum': workout_optional}}},
            'required': ['workoutRef'], 'additionalProperties': False}},
        'exerciseUpdates': {'type': 'array', 'items': exercise_update_items},
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
        'exerciseRedistributions': {'type': 'array', 'description':
            'Distribute an existing prescription across selected workouts without changing its total weekly sets. Python copies the prescription and computes the split; do not update, move or remove these exerciseRefs separately.',
            'items': {'type': 'object', 'properties': {
                'exerciseRefs': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                    'items': {'type': 'string', 'enum': exercise_refs}},
                'workoutRefs': {'type': 'array', 'minItems': 2, 'uniqueItems': True,
                    'items': {'type': 'string', 'enum': workout_refs}}},
                'required': ['exerciseRefs', 'workoutRefs'], 'additionalProperties': False}},
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
            if workout_match:
                allowed_workout_fields.setdefault(f'WORKOUT_{workout_match[1]}', set()).add('description')
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
        edit_schema['properties'] = scoped_properties
    from .repair_contract import assessed_redistributions
    redistribution_objectives = repair_domain['redistributions']
    if assessed_repair and not for_compilation and not redistribution_objectives and permitted_paths is None:
        from itertools import combinations
        from .repair_contract import (redistribution_destination_count_bounds,
            redistribution_recipe_signature)
        sources = {}
        reference_index = 0
        for day in workouts:
            for exercise in day.get('exercises', []):
                if day.get('timesCompletedInAWeek', 1) == 1:
                    sources.setdefault(redistribution_recipe_signature(exercise), []).append(
                        (f'EXERCISE_{reference_index}', exercise))
                reference_index += 1
        eligible = [ref for ref, day in zip(workout_refs, workouts)
                    if day.get('timesCompletedInAWeek', 1) == 1]
        recipe_definitions = task.get('recipeDefinitions', {})
        requirements = task.get('requirements') or {}
        choices = []
        for group in sources.values():
            source_items = [exercise for _, exercise in group]
            domain = redistribution_destination_count_bounds(
                source_items, len(eligible), requirements, recipe_definitions)
            for size in range(max(2, domain['minimumDestinations']), domain['maximumDestinations'] + 1):
                choices.extend({'exerciseRefs': [ref for ref, _ in group],
                    'workoutRefs': list(destinations)} for destinations in combinations(eligible, size))
        if choices:
            edit_schema['properties']['exerciseRedistributions']['items'] = {'enum': choices}
        else:
            edit_schema['properties'].pop('exerciseRedistributions', None)
    if redistribution_objectives and not for_compilation:
        properties = edit_schema['properties']
        properties.pop('exerciseRedistributions', None)
        protected = repair_domain['protected']
        target_properties = {}
        source_exercises = {f'EXERCISE_{index}': exercise for index, exercise in enumerate(
            exercise for workout in workouts for exercise in workout.get('exercises', []))}
        from itertools import combinations
        from .repair_contract import RepairContractError, redistribution_destination_count_bounds
        eligible_refs = [ref for ref, workout in zip(workout_refs, workouts)
                         if workout.get('timesCompletedInAWeek', 1) == 1]
        for key, objective in redistribution_objectives.items():
            source_items = [source_exercises[ref] for ref in objective['exerciseRefs']]
            domain = redistribution_destination_count_bounds(source_items, len(eligible_refs),
                task.get('requirements') or {}, task.get('recipeDefinitions') or {})
            minimum_size = max(objective['minimumSessions'], domain['minimumDestinations'])
            destinations = [list(choice) for size in range(minimum_size,
                domain['maximumDestinations'] + 1) for choice in combinations(eligible_refs, size)]
            if not destinations:
                raise RepairContractError(
                    'redistribution_no_feasible_destinations',
                    'The assessed session spread cannot be achieved while respecting the source exercise set bounds.',
                    '/edits/redistributionTargets/' + key)
            target_properties[key] = {'type': 'array', 'minItems': objective['minimumSessions'],
                'maxItems': domain['maximumDestinations'], 'uniqueItems': True,
                'items': {'type': 'string', 'enum': workout_refs},
                'enum': destinations,
                'description': 'Destination sessions for source occurrences ' + ', '.join(objective['exerciseRefs'])
                    + '. Code preserves weekly sets and set targets, converts touched supersets to straight sets, and creates/places occurrences.'}
        properties['redistributionTargets'] = {'type': 'object', 'properties': target_properties,
            'required': list(target_properties), 'additionalProperties': False}
        edit_schema['required'] = ['redistributionTargets']
        available_refs = repair_domain['editable']
        for collection in ('exerciseUpdates', 'exerciseMoves', 'exerciseRemovals'):
            if collection not in properties:
                continue
            if not available_refs:
                properties.pop(collection)
            elif collection == 'exerciseRemovals':
                properties[collection]['items']['enum'] = available_refs
            elif 'properties' in properties[collection]['items']:
                properties[collection]['items']['properties']['exerciseRef']['enum'] = available_refs
            else:
                variants = [variant for variant in properties[collection]['items']['oneOf']
                    if variant['properties']['exerciseRef']['enum'][0] in available_refs]
                if variants:
                    properties[collection]['items']['oneOf'] = variants
                else:
                    properties.pop(collection)
        if protected:
            from .repair_contract import REDISTRIBUTION_UPDATE_FIELDS
            policy_update = {'type': 'object', 'properties': {
                'exerciseRef': {'type': 'string', 'enum': sorted(protected)},
                'setFields': {'type': 'object', 'minProperties': 1, 'properties': {
                    field: copy.deepcopy(field_properties[field]) for field in REDISTRIBUTION_UPDATE_FIELDS
                    if field in field_properties},
                    'additionalProperties': False}},
                'required': ['exerciseRef', 'setFields'], 'additionalProperties': False}
            policy_update['properties']['setFields']['properties']['superset'] = {'const': None}
            policy_update['properties']['setFields']['properties']['restAfterSupersetExerciseSeconds'] = {'const': 0}
            existing_update = properties.get('exerciseUpdates', {}).get('items')
            properties['exerciseUpdates'] = {'type': 'array', 'items': (
                {'oneOf': [existing_update, policy_update]} if existing_update else policy_update)}
        if 'exerciseOrders' in properties:
            choices = [{'type': 'string', 'pattern': '^NEW_EXERCISE_[A-Za-z0-9_]+$'}]
            if available_refs:
                choices.insert(0, {'type': 'string', 'enum': available_refs})
            properties['exerciseOrders']['items']['properties']['exerciseRefs']['items'] = {'anyOf': choices}
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
    tool['function']['parameters'] = parameters
    repair_groups = [group for group in task.get('findingsAssessment', {}).get('groups', [])
                     if group.get('disposition') == 'repair']
    if (repair_groups and all(repair_group_dimensions(group) == {'session_labels'}
                             and not group.get('repairObjectives') for group in repair_groups)):
        label_updates = copy.deepcopy(edit_schema['properties']['workoutUpdates'])
        label_updates['minItems'] = 1
        fields = label_updates['items']['properties']
        fields.pop('removeOptionalFields', None)
        fields['setFields']['properties'] = {key: value for key, value in
            fields['setFields']['properties'].items() if key in ('name', 'description')}
        fields['setFields']['minProperties'] = 1
        label_updates['items']['required'] = ['workoutRef', 'setFields']
        parameters['properties']['edits'] = {'type': 'object', 'properties': {
            'workoutUpdates': label_updates}, 'required': ['workoutUpdates'], 'additionalProperties': False}
        return tool
    tool['function']['description'] = (
        (f'Revise the complete assessed candidate using its exact current identifiers and addressedFindingIndexes={indexes}. ' if assessed_repair
         else 'Revise the saved currentDraft using its exact current identifiers. ')
        + 'Use edits with stable WORKOUT_n and EXERCISE_n references from currentDraft; do not submit RFC JSON Patch, array indexes, or replacement workout arrays. '
        + ('Current candidate reference map: ' + '; '.join(exercise_ownership) + '. ' if workouts else '')
        + ('Candidate movement identities: ' + ', '.join(exercise_identities) + '. ' if exercise_identities else '')
        + ('Correct only the listed metadataFields using their stable references and permittedPatchPaths. Preserve structured exercise fields and all other content. Python applies these text edits to the saved current candidate and validates the complete draft. Rejected operations remain evidence only. '
           if permitted_paths is not None else
           'Python renders working-set effort criteria. Load calibration is enabled by code from history and exercise type, not through repair fields. Change only typed source fields. Use removeOptionalFields only for an optional field that must be deleted. Replace a movement by updating its existing exerciseRef definition_id; add a movement with a unique NEW_EXERCISE_n temporaryId, target workoutRef, and complete source exercise fields; remove it by exerciseRef. Use exerciseMoves only to move an existing movement to a different workout; use exerciseOrders to reorder within a workout. '
           'For exercise order, send a non-empty relative-order sequence for each affected workout; omitted existing exercises retain their source-relative order. Complete lists are also allowed. Workout order remains a complete list. Active global guidance is code-owned; edits.programGuidance retains legacy source notes only. Python compiles edits to an atomic patch. ')
        + ('checks every assessed repair group, then ' if assessed_repair else '')
        + 'runs the complete audit and review.')
    if permitted_paths is None and not redistribution_objectives:
        tool['function']['description'] += (
            ' For a redistribute_work objective, use exerciseRedistributions with all source occurrences of the same prescription and your chosen workoutRefs. '
            'Python preserves the recipe and computes weekly-set-conserving splits. A whole exerciseMoves operation is not a partial redistribution. '
            'Do not calculate split counts or change the participating source occurrences separately; use a later reviewed edit for a different prescription. '
            'The complete proposed transaction must retain approved weekly session frequency and every required each-session and weekly coverage role, '
            'and satisfy all structured repairObjectives. Preserve a source occurrence when it is the only movement supplying a required session role. '
            'Structural defects return to repair before numerical solving; a volume-bound trade-off cannot replace a missing movement role. '
            'Rejected proposals are evidence only. Submit all intended corrections against the unchanged current candidate.')
    if redistribution_objectives and not for_compilation:
        tool['function']['description'] += (
            ' For this assessed repair, redistributionTargets is REQUIRED: choose only destination sessions for each '
            'code-bound REDISTRIBUTION_n group. Source exercise references, prescriptions, counts, clones and their '
            'placements are code-owned. Progression corrections apply to the entire redistributed recipe. Do not manually change dose, move, remove, clone or explicitly order these sources '
            'or generated occurrences. Other supported corrections can accompany these targets. All choices apply '
            'to the unchanged current candidate; rejected proposals have not moved any exercise. '
            'When replacing a rejected manual proposal, send the complete destination-only intent plus the other required corrections.')
    if has_rejected_proposal:
        tool['function']['description'] += (' Rejected edits were not applied or merged. Submit a complete correction against currentDraft; every actionable finding still needs to be addressed.')
    if uses_menu_selection(task, domain=repair_domain) and not for_compilation:
        replacement_references = sorted(set(task.get('replacementDefinitionReferences', [])))
        coverage_keys = sorted({rule.get('key') for rule in task.get('requirements', {}).get('requiredCoverage', [])
                                if isinstance(rule, dict) and isinstance(rule.get('key'), str)})
        protected = set(repair_domain['protected'])
        selectable_refs = repair_domain['editable']
        menu_member = {'type': 'string', 'enum': selectable_refs}
        source_definitions = {f'EXERCISE_{index}': exercise.get('definition_id')
            for index, exercise in enumerate(exercise for day in workouts for exercise in day.get('exercises', []))}
        source_types = task.get('replacementDefinitionTypes', {})
        recipe_definitions = task.get('recipeDefinitions', {})
        protected_definitions = set(repair_domain['protectedDefinitions'])
        replacement_choices = []
        references_by_exercise = task.get('replacementDefinitionReferencesByExercise', {})
        for reference in selectable_refs:
            source_id = source_definitions.get(reference)
            source_type = source_types.get(source_id) or recipe_definitions.get(source_id, {}).get('exerciseType')
            eligible_references = (references_by_exercise.get(reference, replacement_references)
                if isinstance(references_by_exercise, dict) else replacement_references)
            candidates = [candidate for candidate in sorted(set(eligible_references) | {source_id})
                          if candidate not in protected_definitions and
                              (source_type is None or _replacement_types_compatible(source_type,
                                  source_types.get(candidate) or recipe_definitions.get(candidate, {}).get('exerciseType')))]
            if candidates:
                replacement_choices.append({'type': 'object', 'properties': {
                    'replaces': {'const': reference},
                    'definition_id': {'type': 'string', 'enum': candidates},
                    'satisfiesCoverage': {'type': 'array', 'uniqueItems': True,
                        'items': {'type': 'string', 'enum': coverage_keys}},
                }, 'required': ['replaces', 'definition_id', 'satisfiesCoverage'], 'additionalProperties': False})
        member_schema = ({'oneOf': [menu_member, *replacement_choices]}
                         if replacement_choices else menu_member)
        # Keep the existing full-menu behavior: any selectable occurrence may
        # be retained in its source session, moved, or reused in another one.
        editable_sessions = workout_refs
        assessed_repair_schema = ({
            'type': 'array', 'items': {'type': 'integer', 'enum': indexes},
            'minItems': len(indexes), 'maxItems': len(indexes), 'uniqueItems': True,
            'description': 'List every actionable finding index from the current repairTask exactly once.'}
            if assessed_repair else None)
        tool['function']['parameters'] = {'type': 'object', 'properties': {
            'requirementsId': {'const': task.get('requirementsId')},
            'baseDraftId': {'const': task.get('baseDraftId')},
            'sessionBlocks': {'type': 'array', 'minItems': len(workout_refs), 'maxItems': len(workout_refs),
                'items': {'type': 'object', 'properties': {
                    'sessionReference': {'type': 'string', 'enum': editable_sessions},
                    'blocks': {'type': 'array', 'minItems': 0 if protected else 1, 'items': {'type': 'object', 'properties': {
                        'exercises': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                                      'items': copy.deepcopy(member_schema)}},
                        'required': ['exercises'], 'additionalProperties': False}}},
                    'required': ['sessionReference', 'blocks'], 'additionalProperties': False}}},
            'required': ['requirementsId', 'baseDraftId', 'sessionBlocks'], 'additionalProperties': False}
        if assessed_repair_schema is not None:
            tool['function']['parameters']['properties']['addressedFindingIndexes'] = assessed_repair_schema
            tool['function']['parameters']['required'].append('addressedFindingIndexes')
        if redistribution_objectives:
            tool['function']['parameters']['properties']['edits'] = {
                'type': 'object', 'properties': {'redistributionTargets': copy.deepcopy(
                    edit_schema['properties']['redistributionTargets'])},
                'required': ['redistributionTargets'], 'additionalProperties': False}
            tool['function']['parameters']['required'].append('edits')
        if any(group.get('disposition') == 'repair' and 'session_labels' in group.get('repairDimensions', [])
               for group in task.get('findingsAssessment', {}).get('groups', [])):
            tool['function']['parameters']['properties']['workoutUpdates'] = {
                'type': 'array', 'maxItems': len(workout_refs), 'items': {'oneOf': [
                    {'type': 'object', 'properties': {
                        'workoutRef': {'const': reference},
                        'setFields': {'type': 'object', 'properties': {
                            'name': copy.deepcopy(workout_fields['name']),
                            'description': {**copy.deepcopy(workout_fields['description']),
                                'maxLength': description_text_contract(day)['maximumCharacters']}},
                            'minProperties': 1, 'additionalProperties': False}},
                     'required': ['workoutRef', 'setFields'], 'additionalProperties': False}
                    for reference, day in zip(workout_refs, workouts)]}}
        tool['function']['description'] = (
            ('Choose the complete menu for non-redistributed occurrences using sessionBlocks. Supply only destination choices in edits.redistributionTargets; code preserves and places the protected source recipes. '
             if protected else 'Choose the complete menu using sessionBlocks. ')
            + 'Each block contains existing EXERCISE references or a replacement object '
            'with replaces, a currently eligible indexed or fully retrieved LIBRARY_n definition_id, and approved satisfiesCoverage keys. '
            'One member means straight sets; several mean a superset. A recipe may be used in multiple sessions. '
            'Python resolves replacements against the full current library and qualifies the resulting menu before solving. '
            'It preserves set counts, drops old load targets on replacement, generates groups and solves timing. Omitted recipes are removed.')
    if (task.get('solverMenu') or {}).get('feasible') is True and not for_compilation and not redistribution_objectives:
        parameters = tool['function']['parameters']
        parameters['properties']['useSolverMenu'] = {'const': True}
        if 'sessionBlocks' in parameters['properties']:
            # A feasible numerical fallback does not own semantic menu selection.
            parameters['required'] = ['requirementsId', 'baseDraftId']
            if assessed_repair:
                parameters['required'].append('addressedFindingIndexes')
            parameters['oneOf'] = [{'required': ['sessionBlocks']}, {'required': ['useSolverMenu']}]
            tool['function']['description'] += (
                ' Alternatively select useSolverMenu=true to submit the code-computed menu below for full independent review. '
                'Choose sessionBlocks instead when a different menu better serves the source goals. '
                'Numerical feasibility does not establish programming quality. Python owns prescriptions and patches. '
                + json.dumps(task['solverMenu']['sessions'], ensure_ascii=False))
        else:
            parameters['properties'].pop('sessionBlocks', None)
            parameters['required'] = ['requirementsId', 'baseDraftId', 'useSolverMenu']
            if assessed_repair:
                parameters['required'].append('addressedFindingIndexes')
            tool['function']['description'] = (
                'Select the feasible code-computed menu with useSolverMenu=true for full independent review. '
                'Python owns prescriptions and patches. ' + json.dumps(task['solverMenu']['sessions'], ensure_ascii=False))
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


def _raise_coordinated_schema_errors(validation_errors, validation_schema, supplemental_errors=None):
    if not validation_errors:
        return

    def flatten(error):
        if error.validator == 'oneOf' and error.context:
            actual = error.instance
            def matches_type(branch):
                expected = branch.get('type')
                if expected is None:
                    return True
                expected = expected if isinstance(expected, list) else [expected]
                return any((kind == 'object' and isinstance(actual, dict))
                    or (kind == 'array' and isinstance(actual, list))
                    or (kind == 'string' and isinstance(actual, str))
                    or (kind == 'integer' and type(actual) is int)
                    or (kind == 'number' and type(actual) in (int, float))
                    or (kind == 'boolean' and type(actual) is bool)
                    or (kind == 'null' and actual is None) for kind in expected)
            candidates = [(index, branch) for index, branch in enumerate(error.schema.get('oneOf', []))
                          if matches_type(branch)]
            def branch_score(branch):
                properties = branch.get('properties', {})
                if not isinstance(actual, dict):
                    return (0, 0)
                present = [(key, value) for key, value in properties.items() if key in actual]
                exact = sum(actual[key] == value['const'] if 'const' in value else
                    actual[key] in value.get('enum', [actual[key]]) for key, value in present)
                return exact, len(present)
            selected_index = max(candidates, key=lambda item: branch_score(item[1]))[0] if candidates else None
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
        removed = set(edits.get('exerciseRemovals', []))
        offending = sorted(set(references) - set(inventory[workout_ref]) - removed)
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


def repair_exercise_domain(task, draft=None):
    """Return the code-owned current occurrence domain for a coordinated repair."""
    task = task or {}
    draft = draft if draft is not None else task.get('currentDraft')
    draft = draft or {'workouts': []}
    _, source_positions = _stable_draft_references(draft)
    source_references = list(source_positions)
    from .repair_contract import assessed_redistributions
    objectives = assessed_redistributions(task, draft) if draft.get('workouts') else assessed_redistributions(task)
    protected_set = {reference for objective in objectives.values()
                     for reference in objective.get('exerciseRefs', [])}
    objective_references = list(dict.fromkeys(reference for objective in objectives.values()
        for reference in objective.get('exerciseRefs', [])))
    protected = ([reference for reference in source_references if reference in protected_set]
        if draft.get('workouts') else objective_references)
    protected_definitions = sorted({
        draft['workouts'][source_positions[reference][0]]['exercises'][source_positions[reference][1]].get('definition_id')
        for reference in protected if reference in source_positions
        and draft['workouts'][source_positions[reference][0]]['exercises'][source_positions[reference][1]].get('definition_id')
    })
    return {
        'all': source_references,
        'protected': protected,
        'editable': [reference for reference in source_references if reference not in protected_set],
        'protectedDefinitions': protected_definitions,
        'redistributions': objectives,
    }


def _validate_protected_repair_edits(edits, domain):
    protected = set(domain['protected'])
    protected_definitions = set(domain['protectedDefinitions'])
    if not protected:
        return
    from .repair_contract import REDISTRIBUTION_UPDATE_FIELDS
    for update in edits.get('exerciseUpdates', []):
        reference = update.get('exerciseRef')
        fields = update.get('setFields', {})
        if reference in protected and not set(fields) <= REDISTRIBUTION_UPDATE_FIELDS:
            raise PlanningInputError('redistribution_manual_conflict',
                'An assessed redistribution source is protected from manual exercise edits.',
                '/edits/exerciseUpdates',
                'Choose redistributionTargets; code preserves the source prescription and compiles any required structural changes.')
        if reference not in protected and fields.get('definition_id') in protected_definitions:
            raise PlanningInputError('redistribution_manual_conflict',
                'Do not replace another occurrence with an assessed redistribution source definition.',
                '/edits/exerciseUpdates',
                'Choose a different eligible replacement; code owns occurrences of the redistributed recipe.')
    if protected.intersection(item.get('exerciseRef') for item in edits.get('exerciseMoves', [])):
        raise PlanningInputError('redistribution_manual_conflict',
            'An assessed redistribution source cannot be moved manually.', '/edits/exerciseMoves',
            'Choose redistributionTargets; code owns source placement.')
    if protected.intersection(edits.get('exerciseRemovals', [])):
        raise PlanningInputError('redistribution_manual_conflict',
            'An assessed redistribution source cannot be removed manually.', '/edits/exerciseRemovals',
            'Choose redistributionTargets; code preserves the source prescription.')
    if protected.intersection(reference for order in edits.get('exerciseOrders', [])
                               for reference in order.get('exerciseRefs', [])):
        raise PlanningInputError('redistribution_manual_conflict',
            'An assessed redistribution source cannot be ordered manually.', '/edits/exerciseOrders',
            'Choose redistributionTargets; code places source and generated occurrences.')


def _normalize_replacement_exercise(item, source, reference, task, *, error_path='/edits/exerciseUpdates',
                                    explicit_fields=()):
    """Rebind fields that belong to the selected library definition."""
    source_id = source.get('definition_id')
    replacement_id = item.get('definition_id')
    if replacement_id == source_id:
        return
    definitions = task.get('recipeDefinitions') or {}
    source_definition = definitions.get(source_id, {})
    replacement_definition = definitions.get(replacement_id, {})
    if not source_definition or not replacement_definition:
        raise PlanningInputError('replacement_definition_unavailable',
            'Python cannot rebind exercise-specific fields without both library definitions.',
            '/edits/exerciseUpdates',
            'Refresh the current library-backed repair task before replacing an exercise.')
    if not _replacement_types_compatible(
            source_definition.get('exerciseType'), replacement_definition.get('exerciseType')):
        raise PlanningInputError('incompatible_replacement_recipe',
            'The selected exercise type cannot reuse the source prescription fields.',
            error_path,
            'Choose a replacement in the same prescription family so Python can preserve valid counts and ranges.')

    requirements = task.get('requirements') or {}
    warmup_roles = {rule.get('coverageKey') for rule in requirements.get('executionRules', [])
                    if rule.get('kind') == 'warmup' and rule.get('coverageKey')}
    source_coverage = source.get('satisfiesCoverage')
    needs_warmup = bool(warmup_roles and (not isinstance(source_coverage, list)
        or warmup_roles.intersection(source_coverage)))
    equipment_ids = set(task.get('equipmentIds') or [])
    warmup_supported = native_warmup_supported(replacement_definition, equipment_ids)
    allowed_by_occurrence = task.get('replacementDefinitionReferencesByExercise') or {}
    allowed = allowed_by_occurrence.get(reference)
    if allowed is not None and replacement_id not in allowed:
        raise PlanningInputError('replacement_not_eligible',
            'The selected replacement is outside the code-computed choices for this source occurrence.',
            error_path,
            'Choose a replacement from the current occurrence-specific menu or keep the source exercise.')
    if needs_warmup:
        if not replacement_supports_required_warmup(source_coverage, replacement_definition,
                                                    equipment_ids, requirements):
            raise PlanningInputError('replacement_warmup_unsupported',
                'The selected replacement cannot provide the approved native ramp-up for this source role.',
                error_path,
                'Keep the source exercise or choose a loaded replacement with supported equipment; preserve its approved warm-up rule.')
    item['generateWarmUpSets'] = bool(needs_warmup or (
        source.get('generateWarmUpSets') and warmup_supported))
    item['intraSetRestInSeconds'] = (_UNILATERAL_SIDE_REST_DEFAULT_SECONDS
        if replacement_definition and _exercise_requires_unilateral_rest(replacement_definition) else None)
    explicit_fields = set(explicit_fields)
    if 'workSetTemplate' not in explicit_fields and isinstance(item.get('workSetTemplate'), dict):
        item['workSetTemplate'].pop('weight', None)
        item['workSetTemplate'].pop('additionalWeight', None)
    if 'targetSetPrescriptions' not in explicit_fields:
        for target in item.get('targetSetPrescriptions', []):
            if isinstance(target, dict):
                target.pop('weight', None)
                target.pop('additionalWeight', None)
    acceptance = item.get('effortAcceptance') or {}
    if acceptance.get('kind') == 'rir_range':
        item['effortAcceptance'] = {key: acceptance[key] for key in
            ('kind', 'minimumRIR', 'maximumRIR') if key in acceptance}
    else:
        item.pop('effortAcceptance', None)


def _menu_selection_edits(arguments, task, current_draft):
    from .joint_planning import _rest_options
    protected = repair_exercise_domain(task, current_draft)['protected']
    occurrences, recoveries, filtered_workouts = {}, {}, []
    _, source_positions = _stable_draft_references(current_draft)
    source_reference = 0
    for day in current_draft['workouts']:
        filtered_day = copy.deepcopy(day)
        filtered_day['exercises'] = []
        for item in day['exercises']:
            reference = f'EXERCISE_{source_reference}'
            source_reference += 1
            if reference in protected:
                continue
            occurrences[reference] = item
            filtered_day['exercises'].append(copy.deepcopy(item))
            group = item.get('superset')
            recoveries[reference] = max([item.get('restBetweenSetsSeconds', 0)] + [
                other.get('restAfterSupersetExerciseSeconds', 0) for other in day['exercises']
                if group is not None and other.get('superset') == group])
        filtered_workouts.append(filtered_day)
    selected = copy.deepcopy(filtered_workouts)
    selected_references = [[] for _ in filtered_workouts]
    member_references = lambda members: [member if isinstance(member, str) else member['replaces'] for member in members]
    seen_sessions = set()
    for update in arguments['sessionBlocks']:
        session_reference = update['sessionReference']
        if session_reference in seen_sessions:
            raise PlanningInputError('duplicate_menu_session',
                'A menu selection may include each session only once.', '/sessionBlocks',
                'Submit one complete menu block list for every current session.')
        seen_sessions.add(session_reference)
        day_index = int(update['sessionReference'].split('_')[1])
        used = set()
        selected_items = []
        for group_index, block in enumerate(update['blocks']):
            for member, reference in zip(block['exercises'], member_references(block['exercises'])):
                if reference not in occurrences or reference in used:
                    raise PlanningInputError('invalid_menu_occurrence',
                        'Each selected menu occurrence must identify one editable source and may appear at most once per session.',
                        f'/sessionBlocks/{day_index}/blocks',
                        'Use current editable occurrence references, once per session; code places protected redistribution sources.')
                used.add(reference)
                item = copy.deepcopy(occurrences[reference])
                if isinstance(member, dict):
                    item['definition_id'] = member['definition_id']
                    item['satisfiesCoverage'] = copy.deepcopy(member['satisfiesCoverage'])
                    _normalize_replacement_exercise(item, occurrences[reference], reference, task,
                                                    error_path='/sessionBlocks')
                item['superset'] = f'MENU_{group_index}' if len(block['exercises']) > 1 else None
                selected_items.append(item)
                selected_references[day_index].append(reference)
        selected[day_index]['exercises'] = selected_items
    expected_sessions = {f'WORKOUT_{index}' for index in range(len(current_draft['workouts']))}
    if seen_sessions != expected_sessions:
        raise PlanningInputError('incomplete_menu_sessions',
            'A complete menu selection must include each current session exactly once.', '/sessionBlocks',
            'Submit one complete block list per current WORKOUT_n; omitted sessions must not be inferred as deletions.')
    # Reuse approved rest-range calculation after changing a block's grouping.
    definitions = {item['definition_id']: {} for item in occurrences.values()}
    definitions.update(task.get('recipeDefinitions', {}))
    for update in arguments['sessionBlocks']:
        day = selected[int(update['sessionReference'].split('_')[1])]
        offset = 0
        for block in update['blocks']:
            items = day['exercises'][offset:offset + len(block['exercises'])]
            for index, (reference, item) in enumerate(zip(member_references(block['exercises']), items)):
                item['restBetweenSetsSeconds'] = recoveries[reference] if len(items) == 1 else 0
                item['restAfterSupersetExerciseSeconds'] = 0 if len(items) == 1 else recoveries[reference]
                if index < len(items) - 1:
                    item['restAfterExerciseSeconds'] = 0
            options = list(_rest_options(items, task.get('requirements', {}), definitions,
                                         max(item['numWorkSets'] for item in items)))
            day['exercises'][offset:offset + len(items)] = options[-1]
            offset += len(items)
    # The menu supplies identity and grouping. Code owns the final exercise order.
    from .programming_guidelines import canonical_execution_order_draft
    for day_index, day in enumerate(selected):
        for item_index, item in enumerate(day['exercises']):
            item['_menuSelectionToken'] = f'{day_index}_{item_index}'
    ordered = canonical_execution_order_draft(
        {'workouts': selected}, task.get('requirements') or {},
        {'exerciseDefinitions': list(definitions_by_reference.values())})
    if ordered is None:
        raise PlanningInputError('cyclic_execution_order',
            'The selected menu conflicts with the approved exercise-order rules.', '/sessionBlocks',
            'Choose a menu whose required ordering rules are compatible; Python applies the default category order.')
    selected = ordered['workouts']
    token_to_reference = {f'{day_index}_{item_index}': reference
        for day_index, references in enumerate(selected_references)
        for item_index, reference in enumerate(references)}
    selected_references = []
    for day in selected:
        references = []
        for item in day['exercises']:
            references.append(token_to_reference[item.pop('_menuSelectionToken')])
        selected_references.append(references)
    placements = {}
    for update in arguments['sessionBlocks']:
        day_index = int(update['sessionReference'].split('_')[1])
        references = selected_references[day_index]
        for index, reference in enumerate(references):
            placements.setdefault(reference, []).append((day_index, index))
    retained = {reference: next((position for position in positions
        if position[0] == source_positions[reference][0]), positions[0])
        for reference, positions in placements.items()}
    edits = {'exerciseUpdates': [], 'exerciseRemovals': sorted(set(occurrences) - set(placements)),
             'exerciseMoves': [], 'exerciseAdditions': [], 'exerciseOrders': []}
    for update in arguments['sessionBlocks']:
        day_index = int(update['sessionReference'].split('_')[1])
        references = selected_references[day_index]
        order = []
        for index, reference in enumerate(references):
            item = selected[day_index]['exercises'][index]
            fields = {key: copy.deepcopy(value) for key, value in item.items()
                      if key in _EXERCISE['properties'] and key != 'allocationBounds'}
            if retained[reference] != (day_index, index):
                clone = f'NEW_EXERCISE_{day_index}_{index}'
                edits['exerciseAdditions'].append({'temporaryId': clone,
                    'workoutRef': update['sessionReference'], 'exercise': fields})
                order.append(clone)
                continue
            changed = {key: value for key, value in fields.items() if occurrences[reference].get(key) != value}
            if fields.get('superset') != occurrences[reference].get('superset'):
                # A redistribution may add code-owned detachment defaults for an
                # original superset partner. Preserve the menu's complete rest
                # prescription even when restBetweenSetsSeconds was already 0
                # in the source and would otherwise be omitted as unchanged.
                for key in ('restBetweenSetsSeconds', 'restAfterSupersetExerciseSeconds'):
                    if key in fields:
                        changed[key] = copy.deepcopy(fields[key])
            removed = [key for key in occurrences[reference] if key in _EXERCISE['properties']
                       and key != 'allocationBounds' and key not in fields]
            if changed or removed:
                edits['exerciseUpdates'].append({'exerciseRef': reference, 'setFields': changed,
                    **({'removeOptionalFields': removed} if removed else {})})
            if source_positions[reference][0] != day_index:
                edits['exerciseMoves'].append({'exerciseRef': reference, 'workoutRef': update['sessionReference']})
            order.append(reference)
        if order:
            edits['exerciseOrders'].append({'workoutRef': update['sessionReference'], 'exerciseRefs': order})
    return {key: value for key, value in edits.items() if value}


def _omit_code_owned_redistribution_menu_members(arguments, protected_references, selection_schema):
    """Drop only valid, code-owned source refs duplicated in menu blocks.

    Their placement is compiled from redistributionTargets. Keep malformed or
    unknown members for the ordinary strict schema validator to reject.
    """
    targets = (arguments.get('edits', {}).get('redistributionTargets')
        if isinstance(arguments.get('edits'), dict) else None)
    edits_schema = selection_schema.get('properties', {}).get('edits')
    if (not protected_references or targets is None or not isinstance(edits_schema, dict)
            or not Draft7Validator(edits_schema).is_valid({'redistributionTargets': targets})):
        return
    session_blocks = arguments.get('sessionBlocks')
    if not isinstance(session_blocks, list):
        return
    protected_references = set(protected_references)
    for session in session_blocks:
        if not isinstance(session, dict) or not isinstance(session.get('blocks'), list):
            continue
        retained_blocks = []
        for block in session['blocks']:
            if (not isinstance(block, dict) or set(block) != {'exercises'}
                    or not isinstance(block.get('exercises'), list) or not block['exercises']):
                retained_blocks.append(block)
                continue
            block['exercises'] = [member for member in block['exercises']
                if not (isinstance(member, str) and member in protected_references)]
            if block['exercises']:
                retained_blocks.append(block)
        session['blocks'] = retained_blocks


def _menu_replacement_edits(selected, current_draft):
    _, source_positions = _stable_draft_references(current_draft)
    source_items = {reference: current_draft['workouts'][workout_index]['exercises'][exercise_index]
        for reference, (workout_index, exercise_index) in source_positions.items()}
    unused = set(source_items)
    edits = {'exerciseUpdates': [], 'exerciseRemovals': [], 'exerciseMoves': [],
             'exerciseAdditions': [], 'exerciseOrders': []}
    for workout_index, day in enumerate(selected):
        workout_ref = f'WORKOUT_{workout_index}'
        references = []
        for exercise_index, item in enumerate(day.get('exercises', [])):
            definition_id = item.get('definition_id')
            matching = sorted((reference for reference in unused
                if source_items[reference].get('definition_id') == definition_id),
                key=lambda reference: (source_positions[reference][0] != workout_index,
                                       source_positions[reference]))
            fields = {key: copy.deepcopy(value) for key, value in item.items()
                      if key in _EXERCISE['properties'] and key != 'allocationBounds'}
            if matching:
                reference = matching[0]
                unused.remove(reference)
                source = source_items[reference]
                changed = {key: value for key, value in fields.items() if source.get(key) != value}
                if changed:
                    edits['exerciseUpdates'].append({'exerciseRef': reference, 'setFields': changed})
                if source_positions[reference][0] != workout_index:
                    edits['exerciseMoves'].append({'exerciseRef': reference, 'workoutRef': workout_ref})
            else:
                reference = f'NEW_EXERCISE_{workout_index}_{exercise_index}'
                edits['exerciseAdditions'].append({'temporaryId': reference, 'workoutRef': workout_ref,
                    'exercise': fields})
            references.append(reference)
        if references:
            edits['exerciseOrders'].append({'workoutRef': workout_ref, 'exerciseRefs': references})
    edits['exerciseRemovals'] = sorted(unused, key=lambda reference: source_positions[reference], reverse=True)
    return {key: value for key, value in edits.items() if value}


def _normalize_explicit_superset_detachments(edits, task, current_draft, redistribution_manifest):
    """Give explicitly detached superset members a valid straight-set recovery.

    Superset membership is a group-level structure: detaching one member can
    leave a one-member group, which the exported plan cannot execute as a
    superset. Keep a valid contiguous remainder paired; flatten a singleton
    remainder with the detached member. Redistributed groups are owned by
    ``expand_redistributions`` and are deliberately left to that compiler.
    """
    updates = edits.get('exerciseUpdates', [])
    regrouped = {item.get('exerciseRef') for item in updates
                 if isinstance(item, dict) and isinstance(item.get('setFields'), dict)
                 and item['setFields'].get('superset') is not None}
    explicit = {item.get('exerciseRef'): item.get('setFields', {}) for item in updates
                if isinstance(item, dict) and isinstance(item.get('setFields'), dict)
                and item['setFields'].get('superset', ...) is None}
    if not explicit:
        return False

    _, refs = _stable_draft_references(current_draft)
    redistributed = {reference for group in redistribution_manifest
                     for reference in group.get('exerciseRefs', [])}
    by_group = {}
    for reference, (workout_index, exercise_index) in refs.items():
        item = current_draft['workouts'][workout_index]['exercises'][exercise_index]
        group = item.get('superset')
        if group is not None:
            by_group.setdefault((workout_index, group), []).append((exercise_index, reference, item))

    generated = {}
    for (workout_index, _), members in by_group.items():
        detached = [reference for _, reference, _ in members if reference in explicit]
        if not detached or any(reference in redistributed for reference in (ref for _, ref, _ in members)):
            continue
        # Explicit new membership owns the result; old-group cleanup cannot detach it.
        remaining = [(index, reference, item) for index, reference, item in members
                     if reference not in detached and reference not in regrouped]
        if len(remaining) == 1:
            normalize = [(index, reference, item) for index, reference, item in members
                         if reference in detached] + remaining
        else:
            normalize = [(index, reference, item) for index, reference, item in members
                         if reference in detached]

        recovery = max(max(item.get('restAfterSupersetExerciseSeconds', 0),
                           item.get('restBetweenSetsSeconds', 0)) for _, _, item in members)
        definitions = task.get('recipeDefinitions', {})
        for _, reference, source_item in normalize:
            fields = {'superset': None, 'restAfterSupersetExerciseSeconds': 0}
            requested_fields = explicit.get(reference, {})
            if 'restBetweenSetsSeconds' in requested_fields:
                fields['restBetweenSetsSeconds'] = copy.deepcopy(requested_fields['restBetweenSetsSeconds'])
            else:
                straight = copy.deepcopy(source_item)
                straight.update(fields, restBetweenSetsSeconds=recovery)
                from .joint_planning import _rest_options
                options = list(_rest_options([straight], task.get('requirements', {}),
                    definitions or {straight['definition_id']: {}}, straight['numWorkSets']))
                fields['restBetweenSetsSeconds'] = options[-1][0].get('restBetweenSetsSeconds', recovery)
            generated[reference] = fields

    if not generated:
        return False
    updates_by_ref = {item['exerciseRef']: item for item in updates}
    for reference, fields in generated.items():
        update = updates_by_ref.get(reference)
        if update is None:
            update = {'exerciseRef': reference, 'setFields': {}}
            updates.append(update)
            updates_by_ref[reference] = update
        update.setdefault('setFields', {}).update(fields)
    return True


def compile_coordinated_repair(arguments, task, current_draft, *, return_reference_map=False, proposal_context=None):
    """Compile stable source references into leaf-level RFC 6902 operations."""
    arguments = copy.deepcopy(arguments)
    for collection in ('exerciseUpdates', 'workoutUpdates'):
        updates = arguments.get('edits', {}).get(collection, [])
        for update in updates if isinstance(updates, list) else []:
            fields = update.get('setFields', {}) if isinstance(update, dict) else {}
            if isinstance(fields, dict) and 'removeOptionalFields' in fields:
                removals = fields.pop('removeOptionalFields')
                if 'removeOptionalFields' in update and update['removeOptionalFields'] != removals:
                    raise PlanningInputError('conflicting_field_removals',
                        'Nested and sibling removal instructions disagree.', '/edits/' + collection,
                        'Submit one unambiguous removal list for this stable reference.')
                update['removeOptionalFields'] = removals
    for targets in arguments.get('edits', {}).get('redistributionTargets', {}).values():
        if isinstance(targets, list) and all(isinstance(ref, str) for ref in targets):
            targets.sort(key=lambda ref: (len(ref), ref))
    _reject_unresolved_repair_capability(task)
    if not isinstance(current_draft, dict) or not isinstance(current_draft.get('workouts'), list):
        raise PlanningInputError('stale_draft_patch', 'The coordinated repair has no current saved draft.', '/baseDraftId',
            'Refresh currentDraft and use its currentDraftId before submitting stable-reference edits.')
    if arguments.get('baseDraftId') != task.get('baseDraftId'):
        raise PlanningInputError('stale_draft_patch', 'The coordinated repair base is stale.', '/baseDraftId',
            'Use the exact currentDraftId shown in repairTask; do not reuse an older edit contract.')
    repair_domain = repair_exercise_domain(task, current_draft)
    _validate_protected_repair_edits(arguments.get('edits') or {}, repair_domain)
    selection = uses_menu_selection(task, domain=repair_domain) and (
        'sessionBlocks' in arguments or 'useSolverMenu' in arguments)
    if selection:
        selection_schema = coordinated_repair_tool(
            {**task, 'currentDraft': current_draft})['function']['parameters']
        if 'sessionBlocks' in arguments:
            _omit_code_owned_redistribution_menu_members(
                arguments, repair_domain['protected'], selection_schema)
        validate(arguments, selection_schema)
        selection_arguments = {key: arguments[key] for key in ('requirementsId', 'baseDraftId')}
        if 'addressedFindingIndexes' in arguments:
            selection_arguments['addressedFindingIndexes'] = copy.deepcopy(arguments['addressedFindingIndexes'])
        selected_edits = (_menu_replacement_edits(task['solverMenu']['sessions'], current_draft)
                          if arguments.get('useSolverMenu') else _menu_selection_edits(arguments, task, current_draft))
        redistribution_targets = arguments.get('edits', {}).get('redistributionTargets')
        if redistribution_targets:
            selected_edits['redistributionTargets'] = copy.deepcopy(redistribution_targets)
        if arguments.get('workoutUpdates'):
            selected_edits['workoutUpdates'] = copy.deepcopy(arguments['workoutUpdates'])
        arguments = selection_arguments | {'edits': selected_edits}
    _, source_positions = _stable_draft_references(current_draft)
    for update in arguments.get('edits', {}).get('exerciseUpdates', []):
        reference = update.get('exerciseRef')
        position = source_positions.get(reference)
        if position is None:
            continue
        source = current_draft['workouts'][position[0]]['exercises'][position[1]]
        set_fields = update.get('setFields', {})
        if set_fields.get('definition_id', source.get('definition_id')) == source.get('definition_id'):
            continue
        replacement = copy.deepcopy(source)
        replacement.update(set_fields)
        for field in update.get('removeOptionalFields', []):
            replacement.pop(field, None)
        _normalize_replacement_exercise(replacement, source, reference, task,
                                        explicit_fields=set(set_fields))
        removals = set(update.get('removeOptionalFields', []))
        for field in ('generateWarmUpSets', 'intraSetRestInSeconds', 'effortAcceptance',
                      'workSetTemplate', 'targetSetPrescriptions'):
            if field in replacement:
                set_fields[field] = copy.deepcopy(replacement[field])
                removals.discard(field)
            elif field in source:
                removals.add(field)
        if removals:
            update['removeOptionalFields'] = sorted(removals)
        else:
            update.pop('removeOptionalFields', None)
    redistribution_bound = False
    if selection and arguments.get('edits', {}).get('redistributionTargets'):
        from .repair_contract import RepairContractError, bind_redistribution_targets
        try:
            arguments['edits'] = bind_redistribution_targets(arguments['edits'], task, current_draft)
        except RepairContractError as error:
            raise PlanningInputError(error.code, str(error), error.path,
                'Use redistributionTargets against the unchanged source candidate; code owns its source groups, counts and occurrences.') from error
        redistribution_bound = True
    rejected_edits = _rejected_coordinated_edits(
        task, arguments.get('requirementsId'), arguments.get('baseDraftId'))
    if proposal_context is not None and rejected_edits is not None:
        proposal_context['submittedEdits'] = copy.deepcopy(rejected_edits)
    tool = coordinated_repair_tool({**task, 'currentDraft': current_draft}, for_compilation=selection)
    validation_schema = tool['function']['parameters']
    validation_errors = list(Draft7Validator(validation_schema).iter_errors(arguments))
    effective_arguments = copy.deepcopy(arguments)
    if validation_errors:
        order_reference_errors = _exercise_order_reference_errors(
            effective_arguments.get('edits'), current_draft)
        _raise_coordinated_schema_errors(validation_errors, validation_schema, order_reference_errors)

    if proposal_context is not None:
        if rejected_edits is not None:
            proposal_context['replacedSubmittedEdits'] = copy.deepcopy(rejected_edits)
        proposal_context['submittedEdits'] = copy.deepcopy(effective_arguments['edits'])
        proposal_context['proposalCompiled'] = True
    effective_schema = (coordinated_repair_tool({**task, 'currentDraft': current_draft}, for_compilation=True)
        ['function']['parameters'] if selection else validation_schema)
    try:
        _raise_coordinated_schema_errors(
            list(Draft7Validator(effective_schema).iter_errors(effective_arguments)), effective_schema)
    except ValidationError as error:
        error.validation_arguments = effective_arguments
        raise
    if not redistribution_bound:
        from .repair_contract import RepairContractError, bind_redistribution_targets
        try:
            effective_arguments['edits'] = bind_redistribution_targets(
                effective_arguments['edits'], task, current_draft)
        except RepairContractError as error:
            raise PlanningInputError(error.code, str(error), error.path,
                'Use redistributionTargets against the unchanged source candidate; code owns its source groups, counts and occurrences.') from error
    compilation_schema = coordinated_repair_tool(
        {**task, 'currentDraft': current_draft}, for_compilation=True)['function']['parameters']
    redistribution_manifest = []
    if effective_arguments.get('edits', {}).get('exerciseRedistributions'):
        from .repair_contract import RepairContractError, expand_redistributions
        try:
            effective_arguments['edits'], redistribution_manifest = expand_redistributions(
                effective_arguments['edits'], current_draft, requirements=task.get('requirements'),
                definitions=task.get('recipeDefinitions'))
        except RepairContractError as error:
            raise PlanningInputError(error.code, str(error), error.path,
                'Correct this structural repair against the unchanged candidate. Choose supported destinations and preserve the source prescription; do not relax requirements.') from error
        _raise_coordinated_schema_errors(
            list(Draft7Validator(compilation_schema).iter_errors(effective_arguments)), compilation_schema)
    normalized_supersets = _normalize_explicit_superset_detachments(
        effective_arguments['edits'], task, current_draft, redistribution_manifest)
    if normalized_supersets:
        _raise_coordinated_schema_errors(
            list(Draft7Validator(compilation_schema).iter_errors(effective_arguments)), compilation_schema)
    if proposal_context is not None:
        proposal_context['redistributionManifest'] = copy.deepcopy(redistribution_manifest)

    order_reference_errors = _exercise_order_reference_errors(effective_arguments.get('edits'), current_draft)
    if order_reference_errors:
        first = order_reference_errors[0]
        raise PlanningInputError(first['code'], first['message'], first['path'], first['repair'],
            errors=order_reference_errors)
    edits = effective_arguments['edits']
    if edits != {} and not any(edits.get(key) for key in ('workoutUpdates', 'exerciseUpdates', 'exerciseAdditions',
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
                continue
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
        definition_changed = set_fields.get('definition_id', item.get('definition_id')) != item.get('definition_id')
        if definition_changed:
            for field in ('workSetTemplate', 'targetSetPrescriptions'):
                if field in set_fields or field in removals or field not in item:
                    continue
                targets = item[field] if field == 'targetSetPrescriptions' else [item[field]]
                for index, target in enumerate(targets):
                    if not isinstance(target, dict):
                        continue
                    for load_field in ('weight', 'additionalWeight'):
                        if load_field not in target:
                            continue
                        target_path = (f'{path}/{field}/{index}/{load_field}' if field == 'targetSetPrescriptions'
                                       else f'{path}/{field}/{load_field}')
                        emit({'op': 'remove', 'path': target_path}, [reference, f'WORKOUT_{workout_index}'])
                        target.pop(load_field)
        if (definition_changed
                and 'effortAcceptance' not in set_fields and 'effortAcceptance' not in removals):
            acceptance = item.get('effortAcceptance') or {}
            if acceptance.get('acceptanceCriterion') or acceptance.get('terminationCriterion'):
                # Movement-specific criteria belong to the replaced definition, not its slot.
                if acceptance.get('kind') == 'rir_range':
                    replacement = {key: acceptance[key] for key in ('kind', 'minimumRIR', 'maximumRIR')}
                    emit({'op': 'replace', 'path': path + '/effortAcceptance', 'value': replacement},
                         [reference, f'WORKOUT_{workout_index}'])
                    item['effortAcceptance'] = replacement
                else:
                    emit({'op': 'remove', 'path': path + '/effortAcceptance'}, [reference, f'WORKOUT_{workout_index}'])
                    item.pop('effortAcceptance')
        for field, value in set_fields.items():
            operation = 'replace' if field in item else 'add'
            emit({'op': operation, 'path': f'{path}/{field}', 'value': copy.deepcopy(value)}, [reference, f'WORKOUT_{workout_index}'])
            item[field] = copy.deepcopy(value)
        for field in removals:
            if field not in item:
                continue
            emit({'op': 'remove', 'path': f'{path}/{field}'}, [reference, f'WORKOUT_{workout_index}'])
            item.pop(field)

    for reference in edits.get('exerciseRemovals', []):
        if reference in removed:
            raise PlanningInputError('duplicate_exercise_removal', 'An exercise cannot be removed more than once.', '/edits/exerciseRemovals',
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
        relative_order = [reference for reference in relative_order if reference not in removed]
        if not relative_order:
            continue
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

    if any(edits.get(key) for key in ('exerciseUpdates', 'exerciseAdditions', 'exerciseRemovals',
                                      'exerciseMoves', 'exerciseOrders')):
        from .programming_guidelines import canonical_execution_order_draft
        definitions = task.get('recipeDefinitions') or {}
        ordered = copy.deepcopy(candidate)
        references_by_workout = {}
        for workout_index, day in enumerate(ordered['workouts']):
            workout_ref = workout_refs_by_position[workout_index]
            references = exercise_ids_by_workout[workout_ref]
            if len(references) != len(day.get('exercises', [])):
                raise PlanningInputError('repair_reference_mismatch',
                    'Compiled exercise references no longer match the candidate exercise list.', '/edits',
                    'Resubmit the repair against the unchanged current draft; Python could not safely preserve occurrence identity.')
            references_by_workout[workout_ref] = references
            for exercise, reference in zip(day.get('exercises', []), references):
                exercise['_repairReference'] = reference
        ordered = canonical_execution_order_draft(ordered, task.get('requirements') or {},
            {'exerciseDefinitions': list(definitions.values())})
        if ordered is None:
            raise PlanningInputError('cyclic_execution_order',
                'The proposed exercise placement conflicts with the approved ordering rules.', '/edits/exerciseOrders',
                'Choose placements compatible with the approved order rules; Python applies the default category order.')
        for workout_index, day in enumerate(ordered['workouts']):
            workout_ref = workout_refs_by_position[workout_index]
            current = exercise_ids_by_workout[workout_ref]
            desired = [item.pop('_repairReference') for item in day.get('exercises', [])]
            target_items = {reference: item
                for reference, item in zip(desired, day.get('exercises', []))}
            # The helper also assigns superset recovery by final member slot.
            for exercise_index, reference in enumerate(current):
                target = target_items.get(reference)
                if target is None:
                    continue
                item = candidate['workouts'][workout_index]['exercises'][exercise_index]
                for field in ('restBetweenSetsSeconds', 'restAfterSupersetExerciseSeconds', 'restAfterExerciseSeconds'):
                    if target.get(field) == item.get(field):
                        continue
                    emit({'op': 'replace', 'path': f'/workouts/{workout_index}/exercises/{exercise_index}/{field}',
                          'value': copy.deepcopy(target.get(field))}, [reference, workout_ref])
                    item[field] = copy.deepcopy(target.get(field))
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

    if not operations and edits != {}:
        raise PlanningInputError('empty_coordinated_edits', 'The coordinated edit produced no patch operations.', '/edits',
            'Submit a concrete changed field or ordering update; no-op edits do not address findings.')
    if (task.get('candidateMenuExpansionTask') and uses_menu_selection(task)) or selection:
        from .joint_planning import candidate_menu_fingerprint
        if candidate_menu_fingerprint(candidate['workouts']) == candidate_menu_fingerprint(current_draft['workouts']):
            raise PlanningInputError('empty_coordinated_edits', 'The selection leaves the exercise menu unchanged.', '/edits',
                'Choose a substantive movement or placement change from the supplied recipes.')
    compiled = {key: copy.deepcopy(effective_arguments[key]) for key in ('requirementsId', 'baseDraftId')}
    if 'addressedFindingIndexes' in effective_arguments:
        compiled['addressedFindingIndexes'] = copy.deepcopy(effective_arguments['addressedFindingIndexes'])
    compiled['patch'] = operations
    if not return_reference_map:
        return compiled, operation_refs
    reference_map = {
        'redistributionManifest': copy.deepcopy(redistribution_manifest),
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
    from .session_drafting import _preparation_choice_domain, _preparation_selection_errors
    choice_domain = _preparation_choice_domain(messages, equipment)
    selection_errors = _preparation_selection_errors({'sessions': [{'exercises': [
        {'definition_id': reference} for reference in arguments['definition_ids']]}]}, choice_domain)
    if selection_errors:
        for index, error in enumerate(selection_errors):
            error['path'] = f'/definition_ids/{index}'
            error['permittedPaths'] = {'exact': [error['path']], 'descendants': []}
        raise PlanningInputError('preparation_selection_outside_reviewed_pool',
            'The fresh selector can choose only reviewed, eligible definitions while demand or family distribution is active.',
            '/definition_ids', 'Choose only the reviewed definition IDs supplied by the current selector, or ask the user if an outside-domain exercise is required.',
            selection_errors)
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
        if 'subjectExerciseRefs' in finding:
            source_refs = set(finding['subjectExerciseRefs']) & exercise_refs.keys()
            source_workout_refs = set(finding.get('subjectWorkoutRefs', [])) & workout_refs.keys()
            return source_refs, source_workout_refs
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
    # Keep occurrence identity alongside the changing draft so a superset
    # repair is credited for changing who trains together, not for renaming a
    # group label. Array indexes are mutable during JSON Patch application.
    occurrence_tokens = [[exercise_ref_by_position[(workout_index, exercise_index)]
                          for exercise_index, _ in enumerate(day.get('exercises', []))]
                         for workout_index, day in enumerate((candidate or {}).get('workouts', []))]

    def membership_snapshot(draft, tokens):
        membership = {}
        for workout_index, day in enumerate(draft.get('workouts', [])):
            groups = {}
            for exercise_index, item in enumerate(day.get('exercises', [])):
                if exercise_index < len(tokens[workout_index]) and item.get('superset') is not None:
                    groups.setdefault(item['superset'], []).append(tokens[workout_index][exercise_index])
            for members in groups.values():
                if len(members) > 1:
                    member_set = frozenset(members)
                    for reference in members:
                        membership[reference] = (workout_index, member_set - {reference})
        return membership

    initial_membership = membership_snapshot(candidate or {}, occurrence_tokens)
    from .json_patching import apply_json_patch
    for operation_index, operation in enumerate(operations):
        before = copy.deepcopy(candidate)
        dimensions = _operation_repair_dimensions(operation, candidate)
        operation_tokens = set()
        path = operation.get('path', '')
        exercise_path = re.fullmatch(r'/workouts/(\d+)/exercises/(\d+|-)(?:/([^/]+))?', path)
        source_path = re.fullmatch(r'/workouts/(\d+)/exercises/(\d+|-)', operation.get('from', ''))
        if exercise_path:
            workout_index = int(exercise_path[1])
            exercise_index = exercise_path[2]
            if workout_index < len(occurrence_tokens):
                resolved_index = len(occurrence_tokens[workout_index]) if exercise_index == '-' else int(exercise_index)
                if resolved_index < len(occurrence_tokens[workout_index]):
                    operation_tokens.add(occurrence_tokens[workout_index][resolved_index])
        if source_path:
            source_workout_index, source_exercise_index = int(source_path[1]), int(source_path[2])
            if source_workout_index < len(occurrence_tokens) and source_exercise_index < len(occurrence_tokens[source_workout_index]):
                operation_tokens.add(occurrence_tokens[source_workout_index][source_exercise_index])
        if candidate is not None:
            candidate = apply_json_patch(candidate, [operation])
            if source_path and exercise_path and operation.get('op') == 'move':
                token = occurrence_tokens[source_workout_index].pop(source_exercise_index)
                destination_workout_index = int(exercise_path[1])
                destination_exercise_index = (len(occurrence_tokens[destination_workout_index])
                    if exercise_path[2] == '-' else int(exercise_path[2]))
                occurrence_tokens[destination_workout_index].insert(destination_exercise_index, token)
            elif exercise_path and operation.get('op') in ('add', 'remove') and exercise_path[3] is None:
                workout_index = int(exercise_path[1])
                exercise_index = exercise_path[2]
                resolved_index = len(occurrence_tokens[workout_index]) if exercise_index == '-' else int(exercise_index)
                if operation.get('op') == 'remove':
                    occurrence_tokens[workout_index].pop(resolved_index)
                else:
                    source_refs_for_operation = (operation_source_refs[operation_index]
                        if operation_source_refs is not None and operation_index < len(operation_source_refs) else [])
                    token = next((reference for reference in source_refs_for_operation
                                  if reference.startswith('NEW_EXERCISE_')), f'NEW_PATCH_{operation_index}')
                    occurrence_tokens[workout_index].insert(resolved_index, token)
                    operation_tokens.add(token)
            # A leaf path only counts if the operation changed its value.
            if operation.get('op') in ('add', 'remove', 'replace') and operation.get('path'):
                try:
                    if before == candidate:
                        dimensions = set()
                except Exception:
                    dimensions = set()
        observed.append((operation, dimensions, operation_tokens))

    final_membership = membership_snapshot(candidate or {}, occurrence_tokens)
    changed_membership_refs = {reference for reference in set(initial_membership) | set(final_membership)
                               if initial_membership.get(reference) != final_membership.get(reference)}
    membership_field_or_structure = lambda operation: (
        operation.get('path', '').endswith('/superset')
        or bool(re.fullmatch(r'/workouts/\d+/exercises/(?:\d+|-)', operation.get('path', '')))
        or bool(re.fullmatch(r'/workouts/\d+/exercises/\d+', operation.get('from', ''))))
    normalized_observed = []
    for operation, dimensions, operation_tokens in observed:
        if 'restAfterSupersetExerciseSeconds' in operation.get('path', '') or membership_field_or_structure(operation):
            dimensions.discard('superset')
        if operation_tokens & changed_membership_refs:
            dimensions.add('superset')
        normalized_observed.append((operation, dimensions, operation_tokens))
    observed = normalized_observed

    uncovered = []
    for group in groups:
        indexes = group.get('findingIndexes', [])
        dimensions = repair_group_dimensions(group)
        relevant_paths = []
        relevant_source_refs = set()
        relevant_workout_refs = set()
        typed_subjects = any('subjectExerciseRefs' in findings[index] for index in indexes
            if isinstance(index, int) and index < len(findings))
        for objective in group.get('repairObjectives', []):
            relevant_source_refs.update(reference for reference in objective.get('exerciseRefs', [])
                                        if isinstance(reference, str))
        for index in indexes:
            if not isinstance(index, int) or index >= len(findings):
                continue
            source_refs, workout_refs_for_finding = finding_source_refs(findings[index])
            relevant_source_refs.update(source_refs)
            relevant_workout_refs.update(workout_refs_for_finding)
            if 'subjectExerciseRefs' in findings[index]:
                relevant_paths.extend(f'/workouts/{exercise_refs[ref][0]}/exercises/{exercise_refs[ref][1]}'
                    for ref in source_refs)
                relevant_paths.extend(f'/workouts/{ref.removeprefix("WORKOUT_")}' for ref in workout_refs_for_finding)
                continue
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
        for operation_index, (operation, changed_dimensions, operation_tokens) in enumerate(observed):
            if ('superset' in changed_dimensions
                    and relevant_source_refs & changed_membership_refs
                    and operation_tokens & changed_membership_refs):
                matching.add('superset')
                continue
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
                same_source_definition_occurrence = (not typed_subjects
                    and 'exercise_selection' in (changed_dimensions & dimensions)
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
            '/patch', 'Correct every listed group with a matching structured field change in one patch. Use leaf-field edits and move for ordering; add/remove exercise array elements with their individual indices. Replacing an entire exercise list or workout is not credited as changing all nested fields. Unchanged or label-only edits cannot stand in for ordering, prescription, coverage, timing, superset or exercise-selection repairs. Unaffected array-index shifts do not count. ' + json.dumps(uncovered))


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
                'Send replacement values only for permittedPatchPaths against the current saved candidate.')
        return copy.deepcopy(arguments)
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
    if tool_name == 'set_workout_requirements':
        index, result = active_requirement_result(messages)
        if index >= 0:
            return index, result
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


def accepted_menu_preparation(messages, requirements_id, base_draft_id, library_fp,
                              history_fp, drafting_version, restriction_policy=None,
                              resolved_decision_context=None):
    """Return the exact current preparation explicitly accepted at its menu-review gate."""
    calls = {call.get('id'): call.get('function', {}) for message in messages
             for call in message.get('tool_calls', [])}
    tool_results = []
    for index, message in enumerate(messages):
        function = calls.get(message.get('tool_call_id'), {})
        if message.get('role') != 'tool' or function.get('name') not in (
                'draft_workout_sessions', 'prepare_workout_sessions'):
            continue
        try:
            payload = json.loads(message.get('content') or '{}')
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            tool_results.append((index, function.get('name'), payload))

    try:
        from .user_interaction import answer_question
    except ImportError:
        return None

    accepted = []
    for gate_index, name, gate in tool_results:
        menu_review = gate.get('menuReview')
        question = gate.get('userQuestion')
        if (name != 'draft_workout_sessions' or not isinstance(menu_review, dict)
                or not isinstance(question, dict) or not gate.get('preparationId')
                or not question.get('options') or len(question['options']) < 2):
            continue
        try:
            accepted_answer = answer_question(question, '2')
        except (ValueError, KeyError, TypeError):
            continue
        answer_index = next((index for index in range(gate_index + 1, len(messages))
                             if messages[index].get('role') == 'user'), None)
        if answer_index is None or messages[answer_index].get('content', '').strip() != accepted_answer:
            continue
        if any(message.get('role') == 'user'
               and message.get('content', '').strip() not in (
                   '/continue', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE')
               for message in messages[answer_index + 1:]):
            continue

        preceding_preparations = [(index, payload) for index, tool_name, payload in tool_results
                                  if index < gate_index and tool_name == 'prepare_workout_sessions']
        if not preceding_preparations:
            continue
        prep_index, prepared = preceding_preparations[-1]
        if not isinstance(prepared, dict):
            continue
        if prepared.get('preparationId') != gate.get('preparationId'):
            continue
        source_budget = prepared.get('sourceWorkingSetBudget')
        if (prepared.get('requirementsId') != requirements_id
                or prepared.get('baseDraftId') != base_draft_id
                or prepared.get('libraryFingerprint') != library_fp
                or prepared.get('historyFingerprint') != history_fp
                or prepared.get('draftingVersion') != drafting_version
                or not isinstance(source_budget, dict)
                or source_budget.get('preparationId') != prepared.get('preparationId')):
            continue
        calls_before_preparation = [message for message in messages[:prep_index]
                                    if message.get('role') != 'assistant' or not message.get('tool_calls')]
        source_snapshot = source_message_context(requirement_sources(calls_before_preparation))
        authority = prepared.get('sourceBudgetAuthority')
        if (prepared.get('sourceMessages') != source_snapshot
                or not isinstance(authority, dict)
                or any(authority.get(key) != value for key, value in {
                    'requirementsId': requirements_id,
                    'baseDraftId': base_draft_id,
                    'libraryFingerprint': library_fp,
                    'historyFingerprint': history_fp,
                    'restrictionPolicy': restriction_policy,
                    'sourceMessages': source_snapshot,
                }.items())):
            continue
        accepted.append((answer_index, prep_index, prepared, gate))
    if not accepted:
        return None
    _, prep_index, prepared, gate = max(accepted, key=lambda item: item[0])
    return {'preparationIndex': prep_index, 'preparation': prepared, 'gateResult': gate}


def latest_draft_audit(messages, draft):
    """Return the saved draft's audit, ignoring later rejected edit requests."""
    draft = _strip_legacy_calibration_fields(copy.deepcopy(draft))
    end = len(messages)
    while end:
        index, result = _latest_result(messages[:end], 'audit_workout_plan')
        if index < 0 or _strip_legacy_calibration_fields(copy.deepcopy(result.get('submittedDraft'))) == draft:
            return index, result
        end = index
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
            repair = ('Supply either kind=rir_range with minimumRIR/maximumRIR within 0–10, or kind=technical_criteria '
                'with concrete observable acceptanceCriterion and terminationCriterion. This is a plan-authored prescription, '
                'not a new user requirement.')
            if supplied is None:
                supplied = {'kind': 'rir_range', 'minimumRIR': 1, 'maximumRIR': 2}
                if working_set_rir:
                    supplied.update(minimumRIR=working_set_rir['minimum'], maximumRIR=working_set_rir['maximum'])
            try:
                validate(supplied, _EFFORT_ACCEPTANCE_SCHEMA)
            except ValidationError as error:
                errors.append({'code': 'invalid_effort_acceptance', 'path': path, 'message': error.message,
                    'repair': 'Use the typed effortAcceptance schema: a bounded RIR range or concrete technical acceptance/termination cues.'})
                continue
            if working_set_rir and isinstance(supplied, dict):
                supplied = copy.deepcopy(supplied)
                bounds = (supplied.get('minimumRIR'), supplied.get('maximumRIR'))
                expected = (working_set_rir['minimum'], working_set_rir['maximum'])
                if bounds not in ((None, None), expected):
                    errors.append({'code': 'effort_acceptance_conflicts_with_requirement', 'path': path,
                        'message': 'Per-exercise effortAcceptance must preserve the approved general workingSetRIR exactly.',
                        'repair': 'Keep the approved range; technical acceptance and stop cues supplement it, never replace it.'})
                    continue
                supplied.update(kind='rir_range', minimumRIR=expected[0], maximumRIR=expected[1])
            supplied = {**{'minimumRIR': None, 'maximumRIR': None,
                'acceptanceCriterion': None, 'terminationCriterion': None}, **supplied}
            exercise['effortAcceptance'] = supplied
            kind = supplied['kind']
            cues = (supplied['acceptanceCriterion'], supplied['terminationCriterion'])
            has_cues = any(value is not None for value in cues)
            valid_cues = (all(isinstance(value, str) and value.strip() for value in cues)
                and cues[0].strip().casefold() != cues[1].strip().casefold())
            if (has_cues and not valid_cues) or (kind == 'technical_criteria' and not valid_cues):
                errors.append({'code': 'invalid_effort_acceptance', 'path': path,
                    'message': 'Technical acceptance requires paired, distinct observable acceptance and stop cues.',
                    'repair': 'Supply both technical criteria, or omit both when a numeric RIR target is sufficient.'})
            if kind == 'rir_range':
                minimum, maximum = supplied['minimumRIR'], supplied['maximumRIR']
                if (type(minimum) not in (int, float) or type(maximum) not in (int, float)
                        or not math.isfinite(minimum) or not math.isfinite(maximum) or minimum > maximum):
                    errors.append({'code': 'invalid_effort_acceptance', 'path': path,
                        'message': 'RIR acceptance requires an ordered finite range.',
                        'repair': 'Use finite minimumRIR <= maximumRIR within 0–10; preserve any valid technical criteria.'})
            elif supplied['minimumRIR'] is not None or supplied['maximumRIR'] is not None:
                errors.append({'code': 'invalid_effort_acceptance', 'path': path,
                    'message': 'Without an approved RIR target, technical_criteria has no numeric RIR fields.',
                    'repair': 'Use rir_range for a numeric target with optional paired technical criteria.'})
    if errors:
        first = errors[0]
        raise PlanningInputError(first['code'], first['message'], first['path'], first['repair'], errors=errors)

    for group in effort_prescription_groups(draft):
        criteria = {(e['effortAcceptance']['acceptanceCriterion'], e['effortAcceptance']['terminationCriterion'])
            for e in group if e['effortAcceptance']['acceptanceCriterion'] is not None}
        if len(criteria) == 1:
            acceptance, termination = next(iter(criteria))
            for exercise in group:
                if exercise['effortAcceptance']['acceptanceCriterion'] is None:
                    exercise['effortAcceptance'].update(acceptanceCriterion=acceptance, terminationCriterion=termination)


def effort_prescription_groups(draft):
    """Group the same prescription without merging intentionally different technical criteria."""
    from .repair_contract import redistribution_recipe_signature
    groups = {}
    for day in draft.get('workouts', []):
        for exercise in day.get('exercises', []):
            recipe = copy.deepcopy(exercise)
            acceptance = recipe.get('effortAcceptance')
            if isinstance(acceptance, dict):
                acceptance.pop('acceptanceCriterion', None)
                acceptance.pop('terminationCriterion', None)
            # Distinct exact per-set targets are not the same prescription.
            signature = (redistribution_recipe_signature(recipe),
                json.dumps(exercise.get('targetSetPrescriptions'), sort_keys=True))
            groups.setdefault(signature, []).append(exercise)
    return list(groups.values())


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
                exercise.pop('placementNotes', None)
                exercise.pop('progressionMethod', None)
                exercise.pop('progressionPlan', None)
                exercise.pop('requiresEffortCalibration', None)
                exercise.pop('calibrationAttempts', None)
    return draft


def _resolve_draft_submission(arguments, messages, equipment):
    arguments = copy.deepcopy(arguments)
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
             and not (m.get('role') == 'assistant' and m.get('unvalidatedProposal'))
            and (m.get('imageAttachments') or m['content'].strip() not in (REQUIREMENTS_CONFIRMATION, EXACT_GENERATION_CONFIRMATION, '/continue'))]


def source_message_context(sources):
    return {f'SOURCE_{i}': {'role': m['role'], 'content': m['content'],
            **({'images': [{'name': image['name'], 'sha256': image['sha256'],
                           **({'textOffset': image['textOffset']} if 'textOffset' in image else {})} for image in m['imageAttachments']]}
               if m.get('imageAttachments') else {})} for i, m in enumerate(sources)}


def _structured_requirement_source(sources):
    try:
        return structured_requirement_source(sources, _REQUIREMENTS)
    except (ValueError, ValidationError) as error:
        raise PlanningInputError('invalid_structured_requirements', str(error), '/sourceMessages',
            'Correct the explicitly marked user structured requirements; no supplied values were changed.') from error


def render_requirements(requirements, restriction_policy=None, confirmation=False):
    lines = ["## Program requirements", "", "### Schedule", "",
             f"- Sessions per week: **{requirements['sessionsPerWeek'] or 'unspecified'}**"]
    limit = requirements["auditTargets"]["maximumSessionSeconds"]
    lines.append(f"- Session duration limit: **{limit / 60:g} minutes**" if limit else "- Session duration limit: unspecified")
    if 'durationBalanceToleranceSeconds' in requirements:
        tolerance = requirements['durationBalanceToleranceSeconds']
        lines.append(f"- Soft duration-balance tolerance: spreads up to **{tolerance / 60:g} minutes** count as equally balanced, allowing lower-ranked objectives to choose within that range; this is not a hard session limit.")
    lines.extend(["", "### Effective-set targets", ""])
    weekly = requirements['auditTargets']['weeklyEffectiveSets']
    per_session = requirements['auditTargets']['perSessionEffectiveSets']
    muscles = [muscle for muscle in MUSCLES if muscle in weekly or muscle in per_session]
    if muscles:
        lines.extend(['| Muscle | Per week | Per session |', '| :--- | ---: | ---: |'])
        for muscle in muscles:
            from .generation_audit import volume_target_text
            ranges = [volume_target_text(values[muscle]) if muscle in values else '—'
                      for values in (weekly, per_session)]
            lines.append(f"| {MUSCLE_LABELS.get(muscle, muscle.capitalize())} | {ranges[0]} | {ranges[1]} |")
        lines.extend(['', '— means no target specified. Zero is an explicit zero target.'])
    else:
        lines.append('No volume targets specified.')
    if requirements.get('requiredCoverage'):
        lines.extend(['', '### Required exercise coverage', ''])
        for rule in requirements['requiredCoverage']:
            scope = 'each session' if rule['scope'] == 'eachSession' else 'across the week'
            intent = rule.get('intent', 'inclusion')
            purpose = 'development emphasis' if intent == 'development' else 'inclusion'
            minimums = []
            if 'minimumWeeklySets' in rule:
                minimums.append(f"at least {rule['minimumWeeklySets']} qualified working sets weekly")
            if 'minimumSessions' in rule:
                minimums.append(f"at least {rule['minimumSessions']} weekly training sessions")
            lines.append(f"- {rule['description']} ({scope}; {purpose}; `{rule['key']}`)" +
                         ('; ' + '; '.join(minimums) + '.' if minimums else
                          '; qualitative emphasis, not an added numeric minimum.' if intent == 'development' else '.'))
    lines.extend(['', '### Default exercise order', '', EXECUTION_ORDER_DESCRIPTION])
    if requirements.get('executionRules'):
        lines.extend(['', '### Execution rules', ''])
        lines.extend('- ' + render_execution_rule(rule) for rule in requirements['executionRules'])
    if requirements.get('familySetBounds'):
        lines.extend(['', '### Approved weekly exercise-family bounds', ''])
        for bound in requirements['familySetBounds']:
            limits = []
            if 'minimumWeeklySets' in bound:
                limits.append(f"at least {bound['minimumWeeklySets']} working sets")
            if 'maximumWeeklySets' in bound:
                limits.append(f"at most {bound['maximumWeeklySets']} working sets")
            lines.append(f"- `{bound['exerciseFamilyId']}`: " + '; '.join(limits) + ' across the week.')
        lines.append('Selected exercises require reviewed family evidence; unknown membership is not zero exposure.')
    if 'minimumRestDaysBetweenSessions' in requirements:
        lines.append(f"- At least {requirements['minimumRestDaysBetweenSessions']} full rest days between sessions, including across weeks.")
    if 'workingSetRIR' in requirements:
        lines.append(f"- Working sets: {requirements['workingSetRIR']['minimum']:g}–{requirements['workingSetRIR']['maximum']:g} RIR.")
    if requirements.get('requirementAccounting'):
        lines.extend(['', '### Instruction accounting', ''])
        for item in requirements['requirementAccounting']:
            lines.append(f"- {item['instruction']} — {item['priority']}; {item['enforcement']}")
    if 'relaxationPermissions' in requirements:
        lines.extend(['', '### Authorized tradeoffs', ''])
        permissions = requirements['relaxationPermissions']
        if not permissions:
            lines.append('No target changes are authorized for relaxation.')
        else:
            directions = {'lower_minimum': 'may propose reducing the minimum',
                          'raise_maximum': 'may propose increasing the maximum',
                          'increase_duration': 'may propose increasing the time limit'}
            for permission in permissions:
                path = permission['path']
                parts = path.strip('/').split('/')
                current = requirement_pointer(requirements, path)
                if parts == ['auditTargets', 'maximumSessionSeconds']:
                    target = f"Session duration limit (currently {current / 60:g} minutes)"
                else:
                    interval = 'weekly' if parts[1] == 'weeklyEffectiveSets' else 'per session'
                    muscle = MUSCLE_LABELS.get(parts[2], parts[2].capitalize())
                    target = f"{interval.capitalize()} {muscle} {parts[3]} (currently {current:g})"
                rank = f"; compromise rank {permission['rank']}" if 'rank' in permission else ''
                lines.append(f"- {target}: {directions[permission['direction']]}{rank}.")
            lines.append('These permissions allow proposals only; any proposed change still needs review and your approval.')
    if requirements.get('objectiveOrder'):
        objective_labels = {
            'demand_distribution': 'reduce known per-session demand peaks',
            'duration_balance': 'balance estimated session durations',
            'source_balance': 'reduce source-backed movement set-count differences',
            'exercise_distribution': 'spread exposure across qualified exercises',
            'workload_economy': 'minimize physical working sets across the week',
            'distribution': 'reduce muscle-set concentration across sessions',
            'development_emphasis': 'maximize the least-exposed development role (explicit preference only)',
            'development_exposure': 'increase combined development-role exposure (explicit preference only)',
            'progression': 'consider app-supported progression configuration during exercise selection',
            'preservation': 'preserve the current candidate',
        }
        lines.append('Approved optimization order: ' + ', then '.join(
            objective_labels.get(objective, objective) for objective in requirements['objectiveOrder']) + '.')
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


def _ensure_application_execution_rules(requirements):
    if 'executionRules' not in requirements:
        rules = []
        requirements['executionRules'] = rules
    else:
        rules = requirements['executionRules']
    if not isinstance(rules, list):
        return
    missing = []
    if not any(isinstance(rule, dict) and rule.get('kind') == 'workSets' and rule.get('coverageKey') is None
               and rule.get('exerciseCategory') is None and type(rule.get('minimumSets')) is int
               and type(rule.get('maximumSets')) is int
               and rule['minimumSets'] >= MINIMUM_WORK_SETS_RULE['minimumSets']
               and rule['maximumSets'] <= MINIMUM_WORK_SETS_RULE['maximumSets'] for rule in rules):
        missing.append(MINIMUM_WORK_SETS_RULE)
    if not all(any(isinstance(rule, dict) and rule.get('kind') == 'sessionStructure'
                   and type(rule.get(field)) is int and rule[field] <= maximum
                   for rule in rules)
               for field, maximum in SESSION_STRUCTURE_RULE.items() if field != 'kind'):
        missing.append(SESSION_STRUCTURE_RULE)
    if len(rules) + len(missing) > EXECUTION_RULES_SCHEMA['maxItems']:
        raise PlanningInputError('execution_rule_limit',
            'The structured execution-rule limit leaves no room for the code-owned execution defaults.',
            '/executionRules', 'Resolve the excessive execution-rule list before approval; preserve the code-owned working-set floor and session-structure bounds.')
    rules.extend(copy.deepcopy(missing))


def set_workout_requirements(arguments, messages, equipment=None, client=None, progress=None):
    from .restriction_policy import RESTRICTION_POLICY_VERSION
    from .planning_decisions import resolved_decisions
    arguments = copy.deepcopy(arguments)
    supported = available_muscle_targets(equipment)
    scoped_update = 'updates' in arguments
    accounting_refresh = 'baseRequirementsId' in arguments and not scoped_update
    update_base = {}
    inherited_legacy_accounting = False
    authority = _structured_requirement_source(requirement_sources(messages))
    if authority and not scoped_update and not accounting_refresh:
        try:
            arguments = seed_structured_requirements(arguments, authority)
        except ValueError as error:
            raise PlanningInputError('structured_requirement_mismatch', str(error), '/',
                'Use the supplied structured values unchanged; propose a scoped amendment only with new user authority.') from error
    if scoped_update:
        _, update_base = latest_requirement_candidate(messages)
        if not update_base or arguments.get('baseRequirementsId') != update_base.get('requirementsId'):
            raise PlanningInputError('stale_requirements_update',
                'The update does not name the latest source-checked requirements candidate.', '/baseRequirementsId',
                'Use the current set_workout_requirements update schema and preserve unrelated fields.')
        validate(arguments, workout_requirements_tool(equipment, messages)['function']['parameters'])
        updates = arguments['updates']
        if authority and authority['sourceMessageIndex'] > max(
                (source['messageIndex'] for source in update_base.get('sourceMessages', [])), default=-1):
            try:
                updates = seed_structured_requirements(updates, authority)
            except ValueError as error:
                raise PlanningInputError('structured_requirement_mismatch', str(error), '/updates',
                    'Use the new structured user amendment unchanged and preserve unrelated requirements.') from error
        inherited_legacy_accounting = 'requirementAccounting' in update_base['requirements']
        arguments = _merge_requirement_updates(update_base['requirements'], updates, _REQUIREMENTS)
        if inherited_legacy_accounting and 'requirementAccounting' not in updates:
            arguments['requirementAccounting'] = copy.deepcopy(update_base['requirements']['requirementAccounting'])
        _ensure_application_execution_rules(arguments)
    elif accounting_refresh:
        base = approved_requirement_base(messages)
        if not base or arguments['baseRequirementsId'] != base['requirementsId']:
            raise PlanningInputError('stale_requirements_refresh', 'The accounting refresh does not name the latest approved requirements.', '/baseRequirementsId', 'Use the current accounting refresh tool; do not reconstruct or relax approved targets.')
        validate(arguments, workout_requirements_tool(equipment, messages, accounting_only=True)['function']['parameters'])
        arguments = {**copy.deepcopy(base['requirements']), 'requirementAccounting': arguments['requirementAccounting'],
                     **({'objectiveOrder': arguments['objectiveOrder']} if 'objectiveOrder' in arguments else {})}
    elif not accounting_refresh:
        _ensure_application_execution_rules(arguments)
    _canonicalize_required_coverage(arguments, supported)
    if not scoped_update and 'relaxationPermissions' not in arguments and 'requirementAccounting' not in arguments:
        arguments['relaxationPermissions'] = []
    validate(arguments, _REQUIREMENTS)
    if arguments.get('familySetBounds'):
        from .generation_audit import validate_family_set_bounds
        from .recipe_contracts import reviewed_exercise_family_evidence
        family_errors = validate_family_set_bounds(arguments,
            reviewed_exercise_family_evidence(equipment or {})['familyByReference'])
        if family_errors:
            first = family_errors[0]
            raise PlanningInputError(first['code'], first['message'], first['path'], first['repair'], errors=family_errors)
    duration_tolerance = arguments.get('durationBalanceToleranceSeconds')
    hard_duration_limit = arguments['auditTargets']['maximumSessionSeconds']
    if duration_tolerance is not None and 'duration_balance' not in arguments.get('objectiveOrder', []):
        raise PlanningInputError('duration_balance_tolerance_without_objective',
            'A duration-balance tolerance requires the approved duration_balance objective.',
            '/durationBalanceToleranceSeconds',
            'Add duration_balance only when the original source supports it, or omit the tolerance.')
    if (duration_tolerance is not None and hard_duration_limit is not None
            and duration_tolerance > hard_duration_limit):
        raise PlanningInputError('duration_balance_tolerance_exceeds_session_limit',
            'The approved duration-balance tolerance cannot exceed the hard maximum session duration.',
            '/durationBalanceToleranceSeconds',
            'Use a source-supported tolerance no greater than auditTargets.maximumSessionSeconds, or omit it; do not alter the hard duration limit.')
    arguments = {**copy.deepcopy(arguments), 'notes': ''}
    from .requirement_accounting import validate_accounting
    if not inherited_legacy_accounting:
        try:
            validate_accounting(arguments, source_message_context(requirement_sources(messages)))
        except ValueError as error:
            raise PlanningInputError('invalid_requirement_accounting', str(error), '/requirementAccounting',
                'Correct the structured requirement fields against the original source instructions; do not add a rewritten accounting ledger.') from error
    try:
        validate_relaxation_permissions(arguments)
    except ValueError as error:
        raise PlanningInputError('invalid_relaxation_permissions', str(error), '/relaxationPermissions',
            'Use only exact source-authorized numeric relaxation paths and directions. Empty means no permission.') from error
    keys = [rule['key'] for rule in arguments.get('requiredCoverage', [])]
    if len(set(keys)) != len(keys):
        raise PlanningInputError('duplicate_coverage_key', 'Coverage keys must be unique.', '/requiredCoverage',
                                 'Give each source-backed coverage requirement a distinct key.')
    for index, rule in enumerate(arguments.get('requiredCoverage', [])):
        if (arguments.get('sessionsPerWeek') is not None
                and rule.get('minimumSessions', 0) > arguments['sessionsPerWeek']):
            raise PlanningInputError('coverage_frequency_exceeds_schedule',
                'A role minimum cannot exceed the approved weekly session count.',
                f'/requiredCoverage/{index}/minimumSessions',
                'Resolve the conflicting approved frequency and schedule explicitly; do not silently lower either.')
    rule_errors = execution_rule_errors(arguments)
    if rule_errors:
        first = rule_errors[0]
        raise PlanningInputError(first['code'], first['message'], first['path'], first['repair'], errors=rule_errors)
    # Use the shared target validator even before a draft exists.
    from .generation_audit import validate_audit_targets
    validate_audit_targets(arguments["auditTargets"])
    requested = {muscle for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets')
                 for muscle, bounds in arguments['auditTargets'][field].items()
                 if bounds['maximum'] is None or bounds['maximum'] > 0}
    if requested - supported.keys():
        raise PlanningInputError('unsupported_muscle_targets', f'The loaded library has no auditable credit for: {sorted(requested - supported.keys())}.',
            '/auditTargets', 'Use only auditPolicy.supportedMuscleTargets. Preserve the original request and follow auditPolicy.capabilityLimits to resolve an unsupported target.')
    prior_index, prior = _latest_result(messages, "set_workout_requirements")
    sources = requirement_sources(messages)
    decisions = resolved_decisions(messages)
    restricted = any(arguments.get('exerciseRestrictions', {}).values())
    restriction_policy = None
    if scoped_update and restricted:
        from .restriction_policy import RESTRICTION_POLICY_VERSION
        previous_policy = update_base.get('restrictionPolicy') or {}
        if (update_base['requirements'].get('exerciseRestrictions') == arguments.get('exerciseRestrictions')
                and previous_policy.get('libraryFingerprint') == library_fingerprint(equipment or {})
                and previous_policy.get('resolutionVersion') == RESTRICTION_POLICY_VERSION):
            restriction_policy = copy.deepcopy(previous_policy)
    if prior.get('supportedMuscleTargets') == supported and prior.get('libraryFingerprint') == library_fingerprint(equipment or {}) and prior.get('requirementsVersion') == REQUIREMENTS_VERSION and prior.get('sourceMessages') == sources and prior.get('resolvedDecisions', {}) == decisions and prior.get("requirements") == arguments and (not restricted or
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
              'libraryFingerprint': library_fingerprint(equipment or {}),
              'supportedMuscleTargets': supported,
              'sourceMessages': sources, 'resolvedDecisions': decisions,
              "requirementsId": "REQUIREMENTS_" + _fingerprint({'version': REQUIREMENTS_VERSION, 'requirements': arguments, 'sources': sources})[:16]}
    if scoped_update:
        result['baseRequirementsId'] = update_base['requirementsId']
    if accounting_refresh:
        result['accountingRefreshBaseId'] = base['requirementsId']
    if restriction_policy is not None:
        result['restrictionPolicy'] = restriction_policy
    elif restricted:
        from .restriction_policy import resolve_restrictions
        result['restrictionPolicy'] = resolve_restrictions(arguments['exerciseRestrictions'], equipment or {}, client, progress)
        result['requirementsId'] = 'REQUIREMENTS_' + _fingerprint({'version': REQUIREMENTS_VERSION, 'requirements': arguments, 'sources': sources, 'restrictionPolicy': result['restrictionPolicy']})[:16]
    result["requirementsPreview"] = render_requirements(arguments, result.get('restrictionPolicy'), confirmation=True)
    if scoped_update:
        result['requirementsPreview'] = _render_requirement_changes(update_base['requirements'], arguments) + '\n\n' + result['requirementsPreview']
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
    # Source approval is for this exact extracted requirements record. Later
    # candidate-scoped decisions still invalidate audit/review receipts, but
    # they do not retroactively change the requirements that were reviewed.
    current_context = _requirements_context(result)
    if review.get('inputHash') != _hash(current_context):
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


def _normalize_required_warmup_flags(arguments, equipment, requirements):
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment.get('exerciseDefinitions', []), key=lambda item: item['id']))}
    equipment_ids = {item['id'] for item in equipment.get('equipments', [])}
    warmup_roles = {rule['coverageKey'] for rule in (requirements or {}).get('executionRules', [])
        if rule.get('kind') == 'warmup'}
    if not warmup_roles:
        return
    for day in arguments.get('workouts', []):
        for item in day.get('exercises', []):
            definition = definitions.get(item.get('definition_id'))
            if (native_warmup_supported(definition, equipment_ids)
                    and warmup_roles.intersection(item.get('satisfiesCoverage', []))):
                item['generateWarmUpSets'] = True


def _filter_unsupported_warmup_candidates(workouts, equipment, requirements):
    """Remove only recipe options that cannot satisfy an approved warm-up role."""
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment.get('exerciseDefinitions', []), key=lambda item: item['id']))}
    equipment_ids = {item['id'] for item in equipment.get('equipments', [])}
    warmup_roles = {rule['coverageKey'] for rule in (requirements or {}).get('executionRules', [])
        if rule.get('kind') == 'warmup'}
    removed = []
    if not warmup_roles:
        return removed
    for day in workouts:
        retained = []
        for item in day.get('exercises', []):
            if warmup_roles.intersection(item.get('satisfiesCoverage', [])):
                definition = definitions.get(item.get('definition_id'))
                if not native_warmup_supported(definition, equipment_ids):
                    removed.append(copy.deepcopy(item))
                    continue
            retained.append(item)
        day['exercises'] = retained
    return removed


def _normalize_definition_dependent_fields(arguments, equipment, requirements=None):
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment.get('exerciseDefinitions', []), key=lambda item: item['id']))}
    for day in arguments.get('workouts', []):
        for exercise_index, item in enumerate(day.get('exercises', [])):
            if exercise_index and 'setupSeconds' not in item:
                item['setupSeconds'] = ASSUMPTIONS['transitionSeconds']
            definition = definitions.get(item.get('definition_id'))
            if not definition:
                continue
            if definition['exerciseType'] not in ('WEIGHT', 'BODY_WEIGHT') or not definition.get('equipmentId'):
                item['generateWarmUpSets'] = False
            if _exercise_requires_unilateral_rest(definition):
                if not isinstance(item.get('intraSetRestInSeconds'), int) or item['intraSetRestInSeconds'] <= 0:
                    item['intraSetRestInSeconds'] = _UNILATERAL_SIDE_REST_DEFAULT_SECONDS
            else:
                item['intraSetRestInSeconds'] = None
    _normalize_required_warmup_flags(arguments, equipment, requirements or {})


def build_draft_plan(arguments, equipment, requirements, restriction_policy=None):
    _normalize_definition_dependent_fields(arguments, equipment, requirements)
    _strip_legacy_calibration_fields(arguments)
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
    if requirements.get('familySetBounds'):
        plan['familySetBounds'] = copy.deepcopy(requirements['familySetBounds'])
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
            exercise.update({key: copy.deepcopy(item[key]) for key in ("numWorkSets", "minReps", "maxReps", "restBetweenSetsSeconds", "intraSetRestInSeconds", "generateWarmUpSets")})
            exercise.update(id=f"EXERCISE_{len(plan['exercises'])}", libraryDefinitionId=definition["id"])
            if 'setupSeconds' in item:
                exercise['setupSeconds'] = item['setupSeconds']
            if 'allocationBounds' in item:
                exercise['allocationBounds'] = copy.deepcopy(item['allocationBounds'])
            exercise['notes'] = exercise.get('notes', '')
            exercise['notes'] += ' ' + effort_acceptance_guidance(
                item.get('effortAcceptance'), requirements.get('workingSetRIR'))
            exercise['notes'] += (f" Setup: prepare {definition['name']} before starting; allow "
                f"{item.get('setupSeconds', ASSUMPTIONS['transitionSeconds'])}s estimated changeover time "
                '(actual setup time is unverified).')
            if item['generateWarmUpSets'] and definition.get('equipmentId'):
                exercise['notes'] += (' Warm-up: complete the app-generated ramp-up sets before working sets; '
                    'follow their displayed loads, repetitions and rests. Exact ramp-ups depend on the working '
                    'load and available equipment, and are generated at runtime.')
            elif kind == 'BODY_WEIGHT' and not definition.get('equipmentId'):
                exercise['notes'] += (' Warm-up: this unweighted configuration cannot generate lighter loaded ramp-up sets; '
                    'an exercise-specific preparation protocol is not established by this plan. '
                    'Personal capability remains unverified.')
            elif not item['generateWarmUpSets']:
                exercise['notes'] += ' Warm-up: no additional app-generated ramp-up sets are prescribed for this exercise.'
            if item.get('intraSetRestInSeconds'):
                exercise['notes'] += (f" Unilateral work: complete {item['numWorkSets']} logged working sets. "
                    f"Each set includes both sides, with {item['intraSetRestInSeconds']}s between sides. "
                    'Finish both sides before logging that set once; '
                    'count that paired set once for muscle volume.')
            if item['superset'] is None:
                exercise['notes'] += (f" Straight sets: complete all {item['numWorkSets']} working sets with "
                    f"{item['restBetweenSetsSeconds']}s between sets, then {item['restAfterExerciseSeconds']}s recovery rest. "
                    "The next exercise's estimated setup time is additional to this rest.")
            else:
                exercise['notes'] += (f" Superset: perform one set of each member in displayed order for "
                    f"{item['numWorkSets']} rounds. Rest {item['restAfterSupersetExerciseSeconds']}s after this "
                    'member before the next member or round; omit round recovery after the final round. '
                    f"After completing the group, this member contributes {item['restAfterExerciseSeconds']}s transition rest.")
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
    from .generation_audit import render_program_guidance
    guidance = render_program_guidance(report, requirements['auditTargets']['weeklyEffectiveSets'],
        source_draft, requirements.get('requiredCoverage', []))
    if isinstance(guidance, str) and guidance.strip():
        lines.extend(['', '## Program guidance (code-owned)', guidance])
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
            notes = ('Straight sets. ' if not pair else f'Superset {pair[0]}. ') + e.get("notes", "")
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
    exposure = report.get('weeklyExerciseExposure', {})
    if exposure:
        canonical_names = {}
        for exercise in plan.get('exercises', []):
            canonical_id = exercise.get('libraryDefinitionId') or exercise.get('id')
            canonical_names.setdefault(canonical_id, exercise.get('name', canonical_id))
        lines.extend(["", "Per-exercise exposure audit (definition-level; variants sharing a library ID are combined):",
            "", "| Exercise definition | Weekly sessions | Weekly working sets |", "|---|---:|---:|"])
        for definition_id, counts in sorted(exposure.items()):
            lines.append(f"| {cell(canonical_names.get(definition_id, definition_id))} | {counts['weeklySessions']} | {counts['weeklyWorkingSets']} |")
    lines.extend(["", "Weekly volume audit:",
                  f"Effective sets = direct sets + {indirect_credit:g} × indirect sets. Credits follow the selected library's primary/secondary roles, which may differ from illustrative examples; these are accounting conventions, not exact physiological equivalences.",
                  "", "| Muscle | Direct sets | Indirect sets | Effective sets | Weekly target | Status |", "|---|---|---|---|---|---|"])
    for muscle, values in report["weeklyVolume"].items():
        if values["effective"] or muscle in requirements["auditTargets"]["weeklyEffectiveSets"]:
            bounds = requirements['auditTargets']['weeklyEffectiveSets'].get(muscle)
            if bounds:
                from .generation_audit import volume_target_bounds, volume_target_text
                minimum, maximum = volume_target_bounds(bounds)
                target = volume_target_text(bounds)
                status = 'Within target' if minimum <= values['effective'] <= maximum else 'Outside target'
            else:
                target, status = '—', 'Reported'
            lines.append(f"| {MUSCLE_LABELS.get(muscle, muscle.capitalize())} | {values['direct']:g} | {values['indirect'] / indirect_credit:g} | {values['effective']:g} | {target} | {status} |")
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
    if 'workouts' in report:
        from .generation_audit import audit_coverage_minimums
        audit_coverage_minimums(report, rules.values())


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
    _normalize_definition_dependent_fields(arguments, equipment, requirements)
    _strip_legacy_calibration_fields(arguments)
    from .restriction_policy import effective_restrictions
    restriction_policy = effective_restrictions(stored, equipment)
    fingerprint = library_fingerprint(equipment)
    decisions = resolved_decisions(messages)
    proposal = stored.get('proposedAlternative')
    overrides = ({'status': 'approved' if proposal.get('approvedAlternativeId')
        and proposal.get('requiresUserApproval') is False else 'proposed', 'changes': copy.deepcopy(proposal['changes'])}
        if proposal else None)
    draft_id = "DRAFT_" + _fingerprint({"auditVersion": AUDIT_VERSION, "draft": arguments, "library": fingerprint,
        "history": training_history.fingerprint if training_history else None,
        "calibration": allow_educated_load_guesses, "assumptions": ASSUMPTIONS, 'resolvedDecisions': decisions,
        "muscles": {key: sorted(tags) for key, tags in MUSCLES.items()}})
    _, previous = _latest_result(messages, "audit_workout_plan")
    if not training_history and previous.get("draftId") == draft_id and 'review' not in previous:
        cached = {**copy.deepcopy(previous), "cached": True, 'submittedDraft': copy.deepcopy(arguments), 'currentDraftId': revision_id}
        if overrides:
            cached['audit']['requirementOverrides'] = overrides
        if cached.get('passed'):
            cached['preview'] = render_draft(cached['planIndex'], requirements, cached['audit'], restriction_policy, arguments)
            if decisions:
                cached['preview'] += '\n\nResolved planning choices:\n' + render_decisions(decisions)
        return cached
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
    from .generation_audit import family_set_audit_options
    report = audit_workout_package(plan_audit_package(plan, allow_educated_load_guesses), requirements["auditTargets"],
        coverage_by_exercise=draft_coverage_assignments(plan, arguments),
        **family_set_audit_options(requirements, equipment))
    if overrides:
        report['requirementOverrides'] = overrides
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
    preview_indexes = [i for i, m in enumerate(messages[index + 1:], start=index + 1) if m.get("role") == "assistant"
                       and m.get("canonicalDraftPreview") == result.get("draftId", requirements["requirementsId"])
                       and m.get("content") == result["preview"]]
    if not preview_indexes:
        raise ValueError("The audited draft must be displayed before confirmation.")
    if require_confirmation and not any(m.get('role') == 'user'
            and not m.get('imageAttachments')
            and (m.get('content') or '').strip() == EXACT_GENERATION_CONFIRMATION
            for m in messages[max(preview_indexes) + 1:]):
        raise ValueError('The current draft needs a fresh CONFIRM GENERATE after its preview is displayed.')
    return copy.deepcopy(result)
